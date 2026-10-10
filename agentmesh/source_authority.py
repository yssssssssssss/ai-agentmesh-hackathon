"""Current observations and lifecycle on the existing Source record."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from hashlib import sha256
from typing import TYPE_CHECKING

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.memory_facts import MemoryFactsError, authorize_fact_project
from agentmesh.models import AuditEvent, DocumentRecord, Source, User

if TYPE_CHECKING:
    from agentmesh.store import SQLiteStore


class SourceAuthorityError(ValueError):
    def __init__(self, code: str, *, status_code: int = 409):
        super().__init__(code)
        self.code, self.status_code = code, status_code


def snapshot_identity(source: Source) -> dict | None:
    return (source.snapshot.model_dump(mode='json', exclude={'observed_at', 'revision'})
            if source.snapshot is not None else None)


def observe_source(repository: SQLiteStore, source: Source, *, body: str | None, user: User,
                   expected_revision: int) -> Source:
    with closing(repository._connect()) as connection, connection:
        connection.execute('BEGIN IMMEDIATE')
        return observe_source_in_transaction(repository, connection, source, body=body, user=user,
                                             expected_revision=expected_revision)


def observe_source_in_transaction(repository: SQLiteStore, connection: sqlite3.Connection, source: Source,
                                  *, body: str | None, user: User, expected_revision: int) -> Source:
    try:
        source = Source.model_validate(source.model_dump())
    except ValueError:
        raise SourceAuthorityError('source_observation_invalid', status_code=422) from None
    snapshot = source.snapshot
    if (snapshot is None or source.origin is not None or type(expected_revision) is not int or expected_revision < 0
        or not source.project_id or not source.workspace_id or not source.user_id
        or len(source.id) > 120 or len(source.title) > 512 or len(source.reference) > 2048):
        raise SourceAuthorityError('source_observation_invalid', status_code=422)
    if body is not None and (not isinstance(body, str) or len(body.encode('utf-8')) > 1024 * 1024
                            or sha256(body.encode('utf-8')).hexdigest() != snapshot.body_sha256):
        raise SourceAuthorityError('source_body_hash_mismatch', status_code=422)
    try:
        actor, _ = authorize_fact_project(connection, user, source.project_id)
    except MemoryFactsError:
        raise SourceAuthorityError('source_not_found', status_code=404) from None
    if actor.id != source.user_id or actor.workspace_id != source.workspace_id:
        raise SourceAuthorityError('source_not_found', status_code=404)
    current = repository._get_in_transaction(connection, 'sources', source.id, Source)
    if current is not None and current.origin is not None:
        raise SourceAuthorityError('source_identity_conflict')
    actual_revision = current.snapshot.revision if current and current.snapshot else 0
    if actual_revision != expected_revision:
        raise SourceAuthorityError('source_revision_conflict')
    if current is not None and any(getattr(current, field) != getattr(source, field) for field in (
        'id', 'source_type', 'workspace_id', 'project_id', 'user_id', 'run_id', 'skill_id',
    )):
        raise SourceAuthorityError('source_identity_conflict')
    if current is not None and current.snapshot is not None:
        old = current.snapshot
        if (snapshot.provider, snapshot.external_id) != (old.provider, old.external_id):
            raise SourceAuthorityError('source_identity_conflict')
        if snapshot.version == old.version and snapshot.body_sha256 != old.body_sha256:
            raise SourceAuthorityError('source_version_content_conflict')
        if (snapshot_identity(source) == snapshot_identity(current)
            and source.title == current.title and source.reference == current.reference):
            return current
        if old.lifecycle == 'deleted':
            raise SourceAuthorityError('source_deleted')
        if snapshot.observed_at < old.observed_at:
            raise SourceAuthorityError('source_observation_stale')
    if body is None and (snapshot.lifecycle == 'active' or current is None or current.snapshot is None
        or (snapshot.version, snapshot.body_sha256) != (current.snapshot.version, current.snapshot.body_sha256)):
        raise SourceAuthorityError('source_observation_body_required', status_code=422)
    if actual_revision >= 2147483647:
        raise SourceAuthorityError('source_revision_exhausted')
    changed = source.model_copy(update={
        'created_at': current.created_at if current else source.created_at,
        'snapshot': snapshot.model_copy(update={'revision': actual_revision + 1}),
    })
    # No new lifecycle table: this bounded unique projection belongs to Source.
    try:
        connection.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_source_external_identity_v1
            ON records(json_extract(payload, '$.user_id'), json_extract(payload, '$.workspace_id'),
                       json_extract(payload, '$.project_id'), json_extract(payload, '$.snapshot.provider'),
                       json_extract(payload, '$.snapshot.external_id'))
            WHERE collection = 'sources' AND json_type(payload, '$.snapshot') = 'object'""")
        repository._upsert_plain_record(connection, 'sources', changed)
    except sqlite3.IntegrityError:
        raise SourceAuthorityError('source_identity_conflict') from None
    repository._upsert_plain_record(connection, 'audit_events', AuditEvent(
        actor=actor.id, action='observe_source', target_type='source', target_id=changed.id,
        workspace_id=changed.workspace_id, project_id=changed.project_id,
        metadata={'provider': snapshot.provider, 'revision': changed.snapshot.revision,
                  'lifecycle': snapshot.lifecycle},
    ))
    return changed


def source_snapshot_available(connection: sqlite3.Connection, source: Source, *, owner_id: str | None,
                              workspace_id: str | None, project_id: str | None,
                              proof: dict[str, str] | None = None) -> bool:
    row = connection.execute("SELECT payload FROM records WHERE collection = 'sources' AND id = ?",
                             (source.id,)).fetchone()
    try:
        current = Source.model_validate_json(row['payload']) if row else None
    except ValueError:
        return False
    if source.origin is not None:
        origin = source.origin
        if source.snapshot is not None or current != source:
            return False
        row = connection.execute("SELECT payload FROM records WHERE collection = 'sources' AND id = ?",
                                 (origin.source_id,)).fetchone()
        try:
            root = Source.model_validate_json(row['payload']) if row else None
        except ValueError:
            return False
        if (root is None or root.id != origin.source_id or root.origin is not None or root.snapshot is None
            or root.snapshot.revision != origin.revision or root.snapshot.body_sha256 != origin.body_sha256
            or canonical_json_sha256(root.model_dump(mode='json')) != origin.source_hash
            or any(getattr(root, field) != getattr(source, field) for field in (
                'title', 'source_type', 'reference', 'workspace_id', 'project_id', 'user_id',
            )) or not source_snapshot_available(connection, root, owner_id=owner_id,
                workspace_id=workspace_id, project_id=project_id, proof=proof)):
            return False
        if proof is not None:
            key = 'sources/' + current.id
            if len(proof) >= 64 and key not in proof:
                return False
            proof[key] = canonical_json_sha256(current.model_dump(mode='json'))
        return True
    if source.snapshot is None:
        if current is None:
            return True  # Unregistered legacy citations have no current snapshot to prove.
        if current.id != source.id or current.snapshot is not None or current.origin is not None:
            return False
        if proof is not None:
            key = 'sources/' + current.id
            if len(proof) >= 64 and key not in proof:
                return False
            proof[key] = canonical_json_sha256(current.model_dump(mode='json'))
        return True
    if (current is None or current.id != source.id or current.snapshot is None or current.origin is not None
        or current.snapshot.lifecycle != 'active' or source.snapshot.lifecycle != 'active'
        or current.snapshot.revision != source.snapshot.revision or snapshot_identity(current) != snapshot_identity(source)
        or any(getattr(current, field) != getattr(source, field) for field in (
            'title', 'source_type', 'reference', 'workspace_id', 'project_id', 'user_id', 'run_id', 'skill_id', 'created_at',
        )) or (current.user_id, current.workspace_id, current.project_id) != (owner_id, workspace_id, project_id)):
        return False
    actor = connection.execute("SELECT payload FROM records WHERE collection = 'users' AND id = ?",
                               (owner_id,)).fetchone()
    try:
        user = User.model_validate_json(actor['payload']) if actor else None
        if user is None or user.id != owner_id:
            return False
        authorize_fact_project(connection, user, project_id)
    except (ValueError, MemoryFactsError):
        return False
    from agentmesh.connector_sync.authority import connector_source_available

    if not connector_source_available(connection, current):
        return False
    if proof is not None:
        key = 'sources/' + current.id
        if len(proof) >= 64 and key not in proof:
            return False
        proof[key] = canonical_json_sha256(current.model_dump(mode='json'))
    return True


def document_source_available(connection: sqlite3.Connection, document: DocumentRecord,
                              *, proof: dict[str, str] | None = None) -> bool:
    if not source_snapshot_available(connection, document.source, owner_id=document.uploaded_by,
        workspace_id=document.workspace_id, project_id=document.project_id, proof=proof):
        return False
    body_hash = (document.source.snapshot.body_sha256 if document.source.snapshot is not None else
                 document.source.origin.body_sha256 if document.source.origin is not None else None)
    if body_hash is None:
        return True
    return (len(document.text.encode('utf-8')) <= 1024 * 1024
            and sha256(document.text.encode('utf-8')).hexdigest() == body_hash)
