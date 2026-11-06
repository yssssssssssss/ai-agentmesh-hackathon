"""Atomic manual imports of a current, authorized document version."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.chunker import chunk_text
from agentmesh.memory_facts import MemoryFactsError, authorize_fact_project
from agentmesh.models import (
    AuditEvent,
    DocumentRecord,
    DocumentUpdateRequest,
    MemoryLayer,
    Scope,
    Source,
    User,
    UserMemoryItem,
    now_utc,
)

if TYPE_CHECKING:
    from agentmesh.store import SQLiteStore

MAX_DOCUMENT_CHUNKS = 2200


class DocumentMemoryError(RuntimeError):
    def __init__(self, code: str, *, status_code: int = 409):
        super().__init__(code)
        self.code, self.status_code = code, status_code


@dataclass(frozen=True)
class DocumentImportResult:
    items: list[UserMemoryItem]
    already_imported: bool


def _record[Record: BaseModel](connection: sqlite3.Connection, collection: str, key: str,
                              model: type[Record]) -> Record | None:
    row = connection.execute('SELECT payload FROM records WHERE collection = ? AND id = ?', (collection, key)).fetchone()
    if row is None:
        return None
    try:
        item = model.model_validate_json(row['payload'])
    except ValueError:
        raise DocumentMemoryError('document_record_invalid') from None
    if item.id != key:
        raise DocumentMemoryError('document_record_invalid')
    return item


def _identity(document: DocumentRecord) -> str:
    # Another successful import may update progress, but cannot change its input.
    return canonical_json_sha256(document.model_dump(mode='json', exclude={
        'expected_chunks', 'completed_chunks', 'updated_at',
    }))


def document_chunk_id(document_id: str, version: int, index: int) -> str:
    digest = hashlib.sha256(f'{document_id}:{version}:{index}'.encode()).hexdigest()[:24]
    return f'umem_chunk_{digest}'


class DocumentMemoryStore:
    def __init__(self, repository: SQLiteStore):
        self.repository = repository

    @staticmethod
    def _authorize(connection: sqlite3.Connection, document: DocumentRecord, user: User | None) -> None:
        owner = _record(connection, 'users', document.uploaded_by, User)
        if owner is None or owner.workspace_id != document.workspace_id or document.withdrawn_at is not None:
            raise DocumentMemoryError('document_not_found', status_code=404)
        try:
            authorize_fact_project(connection, owner, document.project_id)
            actor, _ = authorize_fact_project(connection, user or owner, document.project_id)
        except MemoryFactsError:
            raise DocumentMemoryError('document_not_found', status_code=404) from None
        if actor.workspace_id != document.workspace_id or (actor.id != owner.id and actor.role != 'admin'):
            raise DocumentMemoryError('document_not_found', status_code=404)
        from agentmesh.source_authority import document_source_available

        if not document_source_available(connection, document):
            raise DocumentMemoryError('document_not_found', status_code=404)

    def import_current(self, document: DocumentRecord, user: User | None = None) -> DocumentImportResult:
        # Chunking is bounded and stays outside the writer transaction.
        if (len(document.text.encode('utf-8')) > 1024 * 1024 or len(document.title) > 512
            or len(document.file_name) > 512):
            raise DocumentMemoryError('document_import_too_large', status_code=422)
        if len(document.id) > 120 or any(character in document.id for character in '/#'):
            raise DocumentMemoryError('document_source_identity_invalid', status_code=422)
        chunks = chunk_text(document.text)
        if not chunks:
            raise DocumentMemoryError('document_text_empty', status_code=422)
        if len(chunks) > MAX_DOCUMENT_CHUNKS:
            raise DocumentMemoryError('document_chunk_limit_exceeded', status_code=422)
        with closing(self.repository._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            current = _record(connection, 'documents', document.id, DocumentRecord)
            if current is None:
                raise DocumentMemoryError('document_not_found', status_code=404)
            self._authorize(connection, current, user)
            if _identity(current) != _identity(document):
                raise DocumentMemoryError('document_version_conflict')
            prefix = f'document://{current.id}#v{current.version}/chunk_'
            expected_ids = [document_chunk_id(current.id, current.version, index) for index in range(len(chunks))]
            extra = connection.execute("""SELECT 1 FROM records WHERE collection = 'user_memory_items'
                AND json_extract(payload, '$.user_id') = ? AND json_extract(payload, '$.workspace_id') = ?
                AND json_extract(payload, '$.project_id') = ? AND json_extract(payload, '$.scope') = 'private'
                AND json_extract(payload, '$.source_kind') = 'document_import'
                AND json_extract(payload, '$.status') IN ('active', 'staging')
                AND EXISTS (SELECT 1 FROM json_each(payload, '$.sources') AS s
                            WHERE substr(json_extract(s.value, '$.reference'), 1, ?) = ?)
                AND id NOT IN (SELECT value FROM json_each(?)) LIMIT 1""",
                (current.uploaded_by, current.workspace_id, current.project_id, len(prefix), prefix,
                 json.dumps(expected_ids))).fetchone()
            if extra is not None:
                raise DocumentMemoryError('document_chunk_requires_review')
            items = []
            unchanged = current.expected_chunks == current.completed_chunks == len(chunks)
            for index, text in enumerate(chunks):
                key = expected_ids[index]
                source = Source(id=key.replace('umem_', 'src_', 1), title=current.file_name, source_type='document',
                    reference=f'document://{current.id}#v{current.version}/chunk_{index}',
                    workspace_id=current.workspace_id, project_id=current.project_id, user_id=current.uploaded_by)
                item = UserMemoryItem(id=key, user_id=current.uploaded_by, layer=MemoryLayer.LONG_TERM,
                    title=f'{current.title} [{index + 1}/{len(chunks)}]', summary=text, source_kind='document_import',
                    memory_type='document_chunk', scope=Scope.PRIVATE, workspace_id=current.workspace_id,
                    project_id=current.project_id, sources=[source])
                existing_source = _record(connection, 'sources', source.id, Source)
                if existing_source is not None and existing_source.model_dump(exclude={'created_at'}) != source.model_dump(
                    exclude={'created_at'}):
                    raise DocumentMemoryError('document_source_identity_conflict')
                old = _record(connection, 'user_memory_items', key, UserMemoryItem)
                if old is not None:
                    if (any(getattr(old, field) != getattr(item, field) for field in (
                        'user_id', 'workspace_id', 'project_id', 'scope', 'layer', 'source_kind', 'memory_type',
                        'title', 'summary',
                    )) or old.status not in {'active', 'staging'} or old.archived_at is not None
                        or old.facts is not None or old.procedure is not None or old.sensitivity != 'normal'
                        or old.provenance is not None or old.source_thread_id is not None or old.source_task_id is not None
                        or old.supersedes_memory_id is not None
                        or len(old.sources) != 1 or old.sources[0].reference != source.reference
                        or old.sources[0].source_type != 'document'
                        or any(getattr(old.sources[0], field) not in {None, getattr(source, field)}
                               for field in ('workspace_id', 'project_id', 'user_id'))):
                        raise DocumentMemoryError('document_chunk_requires_review')
                    item = old.model_copy(update={'status': 'active', 'sources': [source], 'updated_at': now_utc()})
                    exact_source = old.sources[0].model_dump(exclude={'created_at'}) == source.model_dump(
                        exclude={'created_at'})
                    if old.status == 'active' and exact_source and existing_source is not None:
                        self.repository._sync_fts(connection, 'user_memory_items', old)
                        self.repository.vector_index.prepare(connection, 'user_memory_items', old.id,
                                                             f'{old.title} {old.summary}')
                        items.append(old)
                        continue
                unchanged = False
                if existing_source is None:
                    self.repository._upsert_plain_record(connection, 'sources', source)
                self.repository._upsert_plain_record(connection, 'user_memory_items', item)
                self.repository._sync_fts(connection, 'user_memory_items', item)
                self.repository.vector_index.prepare(connection, 'user_memory_items', item.id,
                                                     f'{item.title} {item.summary}')
                items.append(item)
            if not unchanged:
                current.expected_chunks = current.completed_chunks = len(chunks)
                current.updated_at = now_utc()
                self.repository._upsert_plain_record(connection, 'documents', current)
                self.repository._upsert_plain_record(connection, 'audit_events', AuditEvent(
                    actor=user.id if user else current.uploaded_by, action='import_document_memory',
                    target_type='document', target_id=current.id, workspace_id=current.workspace_id,
                    project_id=current.project_id, metadata={'document_version': current.version, 'chunk_count': len(items)},
                ))
            return DocumentImportResult(items, unchanged)

    def current_chunks(self, document: DocumentRecord) -> list[UserMemoryItem]:
        prefix = f'document://{document.id}#v{document.version}/chunk_'
        with closing(self.repository._read_connect()) as connection, connection:
            connection.execute('BEGIN')
            current = _record(connection, 'documents', document.id, DocumentRecord)
            if current is None or _identity(current) != _identity(document):
                return []
            self._authorize(connection, current, None)
            rows = connection.execute("""SELECT id, CASE WHEN length(payload) <= 8192 THEN payload END AS payload
                FROM records
                WHERE collection = 'user_memory_items'
                  AND json_extract(payload, '$.user_id') = ? AND json_extract(payload, '$.workspace_id') = ?
                  AND json_extract(payload, '$.project_id') = ? AND json_extract(payload, '$.scope') = 'private'
                  AND json_extract(payload, '$.source_kind') = 'document_import'
                  AND json_extract(payload, '$.memory_type') = 'document_chunk'
                  AND json_extract(payload, '$.status') = 'active' AND json_extract(payload, '$.archived_at') IS NULL
                  AND EXISTS (SELECT 1 FROM json_each(payload, '$.sources') AS s
                              WHERE substr(json_extract(s.value, '$.reference'), 1, ?) = ?)
                ORDER BY created_order LIMIT ?""", (current.uploaded_by, current.workspace_id, current.project_id,
                                                       len(prefix), prefix, MAX_DOCUMENT_CHUNKS + 1)).fetchall()
            if len(rows) > MAX_DOCUMENT_CHUNKS:
                raise DocumentMemoryError('document_chunk_limit_exceeded')
            if any(row['payload'] is None for row in rows):
                raise DocumentMemoryError('document_chunk_requires_review')
            items = [UserMemoryItem.model_validate_json(row['payload']) for row in rows]
            if any(item.id != row['id'] for item, row in zip(items, rows, strict=True)):
                raise DocumentMemoryError('document_record_invalid')
            return items

    def update(self, document_id: str, request: DocumentUpdateRequest, user: User) -> DocumentRecord:
        with closing(self.repository._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            current = _record(connection, 'documents', document_id, DocumentRecord)
            if current is None:
                raise DocumentMemoryError('document_not_found', status_code=404)
            self._authorize(connection, current, user)
            if current.version != request.expected_version:
                raise DocumentMemoryError('document_version_conflict')
            if current.source.snapshot is not None or current.source.origin is not None:
                raise DocumentMemoryError('document_source_read_only')
            current.version += 1
            current.text = request.text
            current.expected_chunks = current.completed_chunks = 0
            current.updated_at = now_utc()
            current.metadata.update(edited_by=user.id, edited_at=current.updated_at.isoformat())
            self.repository._upsert_plain_record(connection, 'documents', current)
            self.repository._sync_fts(connection, 'documents', current)
            self.repository.vector_index.prepare(connection, 'documents', current.id, f'{current.title} {current.text}')
            self._invalidate_previous(connection, current)
            self.repository._withdraw_market_signal_in_transaction(connection, current.uploaded_by)
            self.repository._upsert_plain_record(connection, 'audit_events', AuditEvent(
                actor=user.id, action='edit_document', target_type='document', target_id=current.id,
                workspace_id=current.workspace_id, project_id=current.project_id,
                metadata={'document_version': current.version},
            ))
            return current

    @staticmethod
    def _invalidate_previous(connection: sqlite3.Connection, document: DocumentRecord) -> None:
        # SQL changes only this owner's native imported text, never shared facts or
        # another person's independent record carrying the same source reference.
        prefix = f'document://{document.id}#'
        version_prefix = f'{prefix}v{document.version}/'
        summary_prefix = f'umem_{document.id}_v'
        where = """collection = 'user_memory_items'
            AND json_extract(payload, '$.user_id') = ? AND json_extract(payload, '$.workspace_id') = ?
            AND json_extract(payload, '$.project_id') = ? AND json_extract(payload, '$.scope') = 'private'
            AND json_extract(payload, '$.source_kind') IN ('document_import', 'document_upload')
            AND (EXISTS (SELECT 1 FROM json_each(payload, '$.sources') AS s
                         WHERE substr(json_extract(s.value, '$.reference'), 1, ?) = ?
                           AND substr(json_extract(s.value, '$.reference'), 1, ?) != ?)
                 OR (json_extract(payload, '$.source_kind') = 'document_upload'
                     AND substr(id, 1, ?) = ? AND id != ?))"""
        values = (document.uploaded_by, document.workspace_id, document.project_id, len(prefix), prefix,
                  len(version_prefix), version_prefix, len(summary_prefix), summary_prefix,
                  f'{summary_prefix}{document.version}_summary')
        connection.execute(f"""UPDATE records SET payload = json_set(payload, '$.status', 'stale', '$.updated_at', ?)
            WHERE {where} AND json_extract(payload, '$.status') IN ('active', 'staging')
              AND json_extract(payload, '$.archived_at') IS NULL""", (document.updated_at.isoformat(), *values))
        stale_ids = f"SELECT id FROM records WHERE {where} AND json_extract(payload, '$.status') = 'stale'"
        for table in ('records_fts', 'records_vec', 'vector_states'):
            connection.execute(f"DELETE FROM {table} WHERE collection = 'user_memory_items' "
                               f"AND record_id IN ({stale_ids})", values)
