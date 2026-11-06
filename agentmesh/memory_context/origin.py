"""Fresh origin checks for native documents and frozen personal summary/share lineage."""
from __future__ import annotations

import re
import sqlite3

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.chunker import chunk_text
from agentmesh.memory_governance.lifecycle import memory_content_hash
from agentmesh.models import DocumentRecord, MemoryItem, Scope, UserMemoryItem

_DOCUMENT_VERSION = re.compile(r'^document://([^/#]+)#v([1-9][0-9]*)/[^\s]+$')
_DOCUMENT_CHUNK = re.compile(r'^document://[^/#]+#v[1-9][0-9]*/chunk_(0|[1-9][0-9]*)$')
_ROLLUPS = {'daily_summary', 'short_term_rollup', 'project_archive'}


def document_reference_identity(reference: str) -> tuple[str, int] | None:
    match = _DOCUMENT_VERSION.fullmatch(reference)
    return (match[1], int(match[2])) if match is not None else None


def memory_origin_available(connection: sqlite3.Connection, item: MemoryItem | UserMemoryItem,
                            *, ancestors: frozenset[str] = frozenset(), require_document_version: bool = False,
                            proof: dict[str, str] | None = None) -> bool:
    if item.id in ancestors or len(ancestors) >= 4:
        return False
    owner_id = item.user_id if isinstance(item, UserMemoryItem) else item.owner_user_id
    for source in item.sources:
        from agentmesh.source_authority import source_snapshot_available

        if not source_snapshot_available(connection, source, owner_id=owner_id,
            workspace_id=item.workspace_id, project_id=item.project_id, proof=proof):
            return False
        if source.source_type == 'delegated_answer' or source.reference.startswith('delegated-query://'):
            from agentmesh.delegated_queries import delegated_source_available

            if (source.user_id != owner_id or source.workspace_id != item.workspace_id
                or source.project_id != item.project_id
                or not delegated_source_available(connection, source, ancestors=ancestors | {item.id})):
                return False
        if source.source_type != 'document' and not source.reference.startswith('document://'):
            continue
        match = document_reference_identity(source.reference)
        if match is None and require_document_version:
            return False
        if match is not None:
            row = connection.execute("SELECT payload FROM records WHERE collection = 'documents' AND id = ?",
                                     (match[0],)).fetchone()
        else:
            row = connection.execute("SELECT payload FROM records WHERE collection = 'documents' "
                                     "AND json_extract(payload, '$.source.id') = ?", (source.id,)).fetchone()
        if row is None:
            return False
        document = DocumentRecord.model_validate_json(row['payload'])
        from agentmesh.source_authority import document_source_available

        if (document.withdrawn_at is not None or document.uploaded_by != owner_id
            or document.workspace_id != item.workspace_id or document.project_id != item.project_id
            or (match is not None and document.id != match[0])
            or (match is not None and document.version != match[1])):
            return False
        if not document_source_available(connection, document, proof=proof):
            return False
        if (require_document_version and isinstance(item, UserMemoryItem) and item.source_kind == 'document_import'
            and item.facts is None and item.procedure is None):
            chunk = _DOCUMENT_CHUNK.fullmatch(source.reference)
            if chunk is None or len(document.text.encode('utf-8')) > 1024 * 1024:
                return False
            pieces = chunk_text(document.text)
            index = int(chunk[1])
            if index >= len(pieces) or item.summary != pieces[index]:
                return False
        if proof is not None:
            key = 'documents/' + document.id
            if len(proof) >= 64 and key not in proof:
                return False
            proof[key] = canonical_json_sha256(document.model_dump(mode='json'))
    parents: list[tuple[str, int, str]] = []
    if isinstance(item, UserMemoryItem) and item.source_kind in _ROLLUPS:
        provenance = item.provenance
        if not provenance or not provenance.source_memory_ids or not provenance.source_memory_versions:
            return False  # No invented lineage for old rollups.
        parents = list(zip(provenance.source_memory_ids, provenance.source_memory_versions,
                           provenance.source_memory_hashes, strict=True))
    elif isinstance(item, MemoryItem) and item.metadata.get('source_memory_id'):
        try:
            version = int(item.metadata.get('source_memory_version', ''))
        except ValueError:
            return False
        parents = [(item.metadata['source_memory_id'], version, item.metadata.get('source_memory_hash', ''))]
    for parent_id, version, content_hash in parents:
        row = connection.execute("SELECT payload FROM records WHERE collection = 'user_memory_items' AND id = ?",
                                 (parent_id,)).fetchone()
        if row is None:
            return False
        parent = UserMemoryItem.model_validate_json(row['payload'])
        if (parent.id != parent_id or parent.user_id != owner_id
            or parent.workspace_id != item.workspace_id or parent.project_id != item.project_id
            or parent.scope is not Scope.PRIVATE or parent.status != 'active' or parent.archived_at is not None
            or parent.version != version or memory_content_hash(parent) != content_hash):
            return False
        key = 'user_memory_items/' + parent.id
        if proof is not None and key in proof:
            continue  # This immutable read snapshot already proved the same parent.
        if proof is not None and len(proof) >= 64:
            return False
        if not memory_origin_available(connection, parent, ancestors=ancestors | {item.id},
                                       require_document_version=require_document_version, proof=proof):
            return False
        if proof is not None:
            if len(proof) >= 64 and key not in proof:
                return False
            proof[key] = canonical_json_sha256(parent.model_dump(mode='json'))
    return True
