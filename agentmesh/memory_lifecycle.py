"""Owned forgetting commands and durable barriers against late derived writes."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.memory_facts import _record
from agentmesh.memory_governance.lifecycle import memory_content_hash
from agentmesh.models import AuditEvent, DocumentRecord, MemoryItem, MemoryStatus, Scope, User, UserMemoryItem, now_utc
from agentmesh.store import SQLiteStore


class MemoryLifecycleError(RuntimeError):
    def __init__(self, code: str, *, status_code: int = 409):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class MemoryForgetRequestV1(BaseModel):
    model_config = ConfigDict(extra='forbid')
    command_id: str = Field(min_length=1, max_length=120)
    expected_version: int = Field(ge=1)


class MemoryForgetResultV1(BaseModel):
    target_id: str
    invalidated_count: int = Field(ge=1)
    cleanup_status: str = 'queued'
    retention_notice: str = '阻止后续记忆使用并清理检索索引；已交付内容、团队审核记录、审计和备份不在本次删除范围内。'


def _matches_source(frozen: dict[str, tuple[int, str]], source_id: str, version: int | str,
                    content_hash: str | None) -> bool:
    expected = frozen.get(source_id)
    if expected is None or content_hash != expected[1]:
        return False
    try:
        source_version = int(version)
    except (TypeError, ValueError):
        return False
    # Lifecycle changes advance versions without changing canonical content.
    # An older frozen reference still derives from the content being withdrawn.
    return 0 < source_version <= expected[0]


def ensure_forgetting_schema(connection: sqlite3.Connection) -> None:
    # Subordinate invalidation/cleanup receipts, not another Memory content store.
    connection.execute('''CREATE TABLE IF NOT EXISTS memory_tombstones (
        collection TEXT NOT NULL, record_id TEXT NOT NULL, source_id TEXT,
        owner_user_id TEXT NOT NULL, workspace_id TEXT NOT NULL, project_id TEXT,
        created_at TEXT NOT NULL, cleaned_at TEXT,
        PRIMARY KEY(collection, record_id)
    )''')
    connection.execute('CREATE INDEX IF NOT EXISTS idx_memory_tombstones_source ON memory_tombstones(source_id)')
    connection.execute('CREATE INDEX IF NOT EXISTS idx_memory_tombstones_cleanup ON memory_tombstones(cleaned_at)')
    connection.execute("CREATE INDEX IF NOT EXISTS idx_memory_tool_deliveries_run "
                       "ON records(json_extract(payload, '$.run_id')) WHERE collection = 'memory_tool_deliveries'")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_run_context_snapshots_run "
                       "ON records(json_extract(payload, '$.run_id')) WHERE collection = 'run_context_snapshots'")
    for operation in ('INSERT', 'UPDATE'):
        connection.execute(f'''CREATE TRIGGER IF NOT EXISTS sdk_session_source_withdrawn_v1_{operation.lower()}
            BEFORE {operation} ON records
            WHEN NEW.collection = 'sdk_sessions' AND json_array_length(NEW.payload, '$.items') > 0
             AND (EXISTS (SELECT 1 FROM json_each(NEW.payload, '$.memory_dependencies') AS ref
                          JOIN memory_tombstones AS t
                           ON t.record_id = json_extract(ref.value, '$.memory_id')
                          WHERE t.collection = CASE json_extract(ref.value, '$.memory_record_type')
                           WHEN 'user_memory_item' THEN 'user_memory_items' ELSE 'memory_items' END)
                  OR EXISTS (SELECT 1 FROM records AS old WHERE old.collection = NEW.collection AND old.id = NEW.id
                             AND json_extract(old.payload, '$.source_status') = 'withdrawn'))
            BEGIN SELECT RAISE(ABORT, 'sdk_session_source_withdrawn'); END''')
    for operation in ('INSERT', 'UPDATE'):
        connection.execute(f'DROP TRIGGER IF EXISTS memory_tool_delivery_withdrawn_{operation.lower()}')
        connection.execute(f'DROP TRIGGER IF EXISTS memory_context_withdrawn_v2_{operation.lower()}')
        connection.execute(f'DROP TRIGGER IF EXISTS memory_context_withdrawn_v3_{operation.lower()}')
        connection.execute(f'DROP TRIGGER IF EXISTS memory_context_withdrawn_v4_{operation.lower()}')
        connection.execute(f'''CREATE TRIGGER IF NOT EXISTS memory_context_withdrawn_v5_{operation.lower()}
            BEFORE {operation} ON records
            WHEN NEW.collection IN ('memory_tool_deliveries', 'run_context_snapshots')
             AND json_extract(NEW.payload, '$.bundle') IS NOT NULL
             AND EXISTS (SELECT 1 FROM (
                         SELECT value FROM json_each(NEW.payload, '$.bundle.hits')
                         UNION ALL SELECT value FROM json_each(NEW.payload, '$.bundle.candidates')
                         UNION ALL SELECT value FROM json_each(NEW.payload, '$.bundle.fact_context.result.facts')
                         UNION ALL SELECT json_extract(NEW.payload, '$.bundle.procedure_context')
                          WHERE json_extract(NEW.payload, '$.bundle.procedure_context') IS NOT NULL) AS hit
                         JOIN memory_tombstones AS t ON t.record_id = json_extract(hit.value, '$.memory_id')
                          AND t.collection = CASE COALESCE(json_extract(hit.value, '$.result.result_type'),
                                                            json_extract(hit.value, '$.memory_record_type'))
                              WHEN 'user_memory_item' THEN 'user_memory_items' ELSE 'memory_items' END)
            BEGIN SELECT RAISE(ABORT, 'memory_source_withdrawn'); END''')
        connection.execute(f'DROP TRIGGER IF EXISTS run_context_snapshot_immutable_{operation.lower()}')
        connection.execute(f'''CREATE TRIGGER IF NOT EXISTS run_context_snapshot_immutable_v2_{operation.lower()}
            BEFORE {operation} ON records
            WHEN NEW.collection = 'run_context_snapshots'
             AND EXISTS (SELECT 1 FROM records AS old WHERE old.collection = NEW.collection AND old.id = NEW.id
                         AND old.payload != NEW.payload
                         AND (json_extract(NEW.payload, '$.status') != 'withdrawn'
                              OR json_extract(old.payload, '$.status') = 'withdrawn'
                              OR json_extract(NEW.payload, '$.bundle') IS NOT NULL
                              OR json_extract(NEW.payload, '$.core_preferences') IS NOT NULL
                              OR json_extract(NEW.payload, '$.additional_instructions') != ''
                              OR json_extract(NEW.payload, '$.query') != ''))
            BEGIN SELECT RAISE(ABORT, 'context_snapshot_immutable'); END''')
        connection.execute(f'DROP TRIGGER IF EXISTS memory_forgotten_{operation.lower()}')
        connection.execute(f'DROP TRIGGER IF EXISTS memory_source_withdrawn_{operation.lower()}')
        # Keep the last redacted/invalidated payload immutable. All writers, including
        # old workers using raw aggregate SQL, encounter the same barrier.
        connection.execute(f'''CREATE TRIGGER IF NOT EXISTS memory_forgotten_v2_{operation.lower()}
            BEFORE {operation} ON records
            WHEN NEW.collection IN ('documents', 'user_memory_items', 'memory_items')
             AND EXISTS (SELECT 1 FROM memory_tombstones AS t
                         WHERE t.collection = NEW.collection AND t.record_id = NEW.id)
             AND ((NEW.collection = 'memory_items' AND json_extract(NEW.payload, '$.status')
                   IN ('active', 'staging', 'proposed', 'accepted'))
                  OR (NEW.collection != 'memory_items' AND NOT EXISTS (
                      SELECT 1 FROM records AS old WHERE old.collection = NEW.collection
                       AND old.id = NEW.id AND old.payload = NEW.payload)))
            BEGIN SELECT RAISE(ABORT, 'memory_forgotten'); END''')
        connection.execute(f'''CREATE TRIGGER IF NOT EXISTS memory_source_withdrawn_v2_{operation.lower()}
            BEFORE {operation} ON records
            WHEN NEW.collection IN ('user_memory_items', 'memory_items')
             AND COALESCE(json_extract(NEW.payload, '$.status'), 'active')
                 IN ('active', 'staging', 'proposed', 'accepted')
             AND (
                EXISTS (SELECT 1 FROM json_each(NEW.payload, '$.provenance.source_memory_ids') AS parent
                        JOIN memory_tombstones AS t ON t.record_id = parent.value
                        WHERE t.collection IN ('user_memory_items', 'memory_items'))
                OR EXISTS (SELECT 1 FROM json_each(NEW.payload, '$.sources') AS source
                           JOIN memory_tombstones AS t ON t.collection = 'documents'
                           WHERE json_extract(source.value, '$.id') = t.source_id
                              OR substr(json_extract(source.value, '$.reference'), 1,
                                        length('document://' || t.record_id || '#'))
                                 = 'document://' || t.record_id || '#')
                OR EXISTS (SELECT 1 FROM json_each(NEW.payload, '$.facts') AS fact,
                                         json_each(fact.value, '$.evidence_refs') AS ref
                           JOIN memory_tombstones AS t ON t.collection = 'documents'
                            AND t.record_id = json_extract(ref.value, '$.record_id')
                           WHERE json_extract(ref.value, '$.record_type') = 'document')
                OR EXISTS (SELECT 1 FROM memory_tombstones AS t WHERE t.collection = 'documents'
                           AND t.record_id = json_extract(NEW.payload, '$.metadata.document_id'))
                OR EXISTS (SELECT 1 FROM memory_tombstones AS t WHERE t.collection = 'user_memory_items'
                           AND t.record_id = json_extract(NEW.payload, '$.metadata.source_memory_id'))
             )
            BEGIN SELECT RAISE(ABORT, 'memory_source_withdrawn'); END''')


class MemoryForgettingService:
    def __init__(self, repository: SQLiteStore, *, clock: Callable[[], datetime] = now_utc):
        self.repository = repository
        self.clock = clock

    def forget(self, memory_id: str, request: MemoryForgetRequestV1, user: User) -> MemoryForgetResultV1:
        return self._invalidate('user_memory_items', memory_id, request, user)

    def withdraw_document(self, document_id: str, request: MemoryForgetRequestV1, user: User) -> MemoryForgetResultV1:
        return self._invalidate('documents', document_id, request, user)

    @staticmethod
    def _actor(connection: sqlite3.Connection, user: User) -> User:
        actor = _record(connection, 'users', user.id, User)
        if actor is None or actor.status != 'active' or actor.workspace_id != user.workspace_id:
            raise MemoryLifecycleError('memory_actor_unavailable', status_code=404)
        return actor

    def _invalidate(self, collection: str, target_id: str, request: MemoryForgetRequestV1,
                    user: User) -> MemoryForgetResultV1:
        request_hash = canonical_json_sha256({'collection': collection, 'target_id': target_id,
                                              'request': request.model_dump(mode='json')})
        receipt_id = canonical_json_sha256({'user_id': user.id, 'command_id': request.command_id})
        changed_at = self.clock()
        with closing(self.repository._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            actor = self._actor(connection, user)
            model = DocumentRecord if collection == 'documents' else UserMemoryItem
            item = _record(connection, collection, target_id, model)
            owned = item and item.workspace_id == actor.workspace_id and (
                item.uploaded_by == actor.id if isinstance(item, DocumentRecord)
                else item.user_id == actor.id and item.scope is Scope.PRIVATE
            )
            if not owned:
                raise MemoryLifecycleError('source_not_found' if collection == 'documents' else 'memory_not_found',
                                           status_code=404)
            replay = connection.execute("SELECT payload FROM records WHERE collection = 'memory_forget_commands' "
                                        'AND id = ?', (receipt_id,)).fetchone()
            if replay:
                payload = json.loads(replay['payload'])
                if payload['request_hash'] != request_hash:
                    raise MemoryLifecycleError('memory_forget_command_conflict')
                return MemoryForgetResultV1.model_validate(payload['result'])
            if item.version != request.expected_version:
                raise MemoryLifecycleError('memory_version_conflict')
            if connection.execute('SELECT 1 FROM memory_tombstones WHERE collection = ? AND record_id = ?',
                                  (collection, target_id)).fetchone():
                raise MemoryLifecycleError('memory_already_forgotten')
            dependents = self._dependents(connection, collection, item)
            targets = [(collection, item), *dependents]
            if collection == 'documents':
                connection.execute("DELETE FROM records WHERE collection = 'source_spans' "
                                   "AND json_extract(payload, '$.document_id') = ?", (item.id,))
            for target_collection, target in targets:
                record_type = {'user_memory_items': 'user_memory_item', 'memory_items': 'memory_item'}.get(target_collection)
                connection.execute("UPDATE records SET payload = json_set(payload, '$.items', json('[]'), "
                                   "'$.source_status', 'withdrawn', '$.version', "
                                   "COALESCE(json_extract(payload, '$.version'), 0) + 1, '$.updated_at', ?) "
                                   "WHERE collection = 'sdk_sessions' AND EXISTS (SELECT 1 FROM "
                                   "json_each(records.payload, '$.memory_dependencies') AS ref "
                                   "WHERE json_extract(ref.value, '$.memory_id') = ? "
                                   "AND json_extract(ref.value, '$.memory_record_type') = ?)",
                                   (changed_at.isoformat(), target.id, record_type))
                connection.execute("UPDATE records SET payload = json_set(payload, '$.bundle', json('null'), "
                                   "'$.core_preferences', json('null'), '$.additional_instructions', '', "
                                   "'$.status', 'withdrawn', '$.query', '') WHERE collection = 'run_context_snapshots' "
                                   "AND EXISTS (SELECT 1 FROM (SELECT value FROM json_each(records.payload, '$.bundle.hits') "
                                   "UNION ALL SELECT value FROM json_each(records.payload, '$.bundle.candidates') "
                                   "UNION ALL SELECT value FROM json_each(records.payload, '$.bundle.fact_context.result.facts') "
                                   "UNION ALL SELECT json_extract(records.payload, '$.bundle.procedure_context') "
                                   "WHERE json_extract(records.payload, '$.bundle.procedure_context') IS NOT NULL) AS hit "
                                   "WHERE json_extract(hit.value, '$.memory_id') = ? "
                                   "AND COALESCE(json_extract(hit.value, '$.result.result_type'), "
                                   "json_extract(hit.value, '$.memory_record_type')) = ?)", (
                                       target.id, record_type,
                                   ))
                connection.execute("UPDATE records SET payload = json_set(payload, '$.bundle', json('null'), "
                                   "'$.status', 'withdrawn', '$.query', '') WHERE collection = 'memory_tool_deliveries' "
                                   "AND EXISTS (SELECT 1 FROM (SELECT value FROM json_each(records.payload, '$.bundle.hits') "
                                   "UNION ALL SELECT value FROM json_each(records.payload, '$.bundle.candidates') "
                                   "UNION ALL SELECT value FROM json_each(records.payload, '$.bundle.fact_context.result.facts') "
                                   "UNION ALL SELECT json_extract(records.payload, '$.bundle.procedure_context') "
                                   "WHERE json_extract(records.payload, '$.bundle.procedure_context') IS NOT NULL) AS hit "
                                   "WHERE json_extract(hit.value, '$.memory_id') = ? "
                                   "AND COALESCE(json_extract(hit.value, '$.result.result_type'), "
                                   "json_extract(hit.value, '$.memory_record_type')) = ?)", (
                                       target.id, record_type,
                                   ))
                if target_collection == 'documents':
                    updated = target.model_copy(update={'text': '', 'title': '已撤回资料', 'metadata': {},
                                                        'withdrawn_at': changed_at, 'withdrawn_by': actor.id,
                                                        'version': target.version + 1, 'updated_at': changed_at})
                elif target_collection == 'user_memory_items':
                    updated = target.model_copy(update={'title': '已遗忘记忆', 'summary': '', 'facts': None,
                                                        'procedure': None, 'sources': [], 'status': 'forgotten',
                                                        'version': target.version + 1, 'updated_at': changed_at})
                else:
                    # Source revocation removes evidence eligibility, not team-owned content or its Review.
                    status = {
                        MemoryStatus.ACCEPTED: MemoryStatus.DISPUTED,
                        MemoryStatus.PROPOSED: MemoryStatus.EXPIRED,
                    }.get(target.status, target.status)
                    updated = target.model_copy(update={'status': status, 'version': target.version + 1,
                                                        'updated_at': changed_at, 'evidence_withdrawn_at': changed_at})
                self.repository._upsert_plain_record(connection, target_collection, updated)
                # Remove searchable bytes in the same barrier transaction. Deleting
                # vector state also fences an embedding already in flight.
                self.repository._sync_fts(connection, target_collection, updated)
                connection.execute('DELETE FROM records_vec WHERE collection = ? AND record_id = ?',
                                   (target_collection, target.id))
                connection.execute('DELETE FROM vector_states WHERE collection = ? AND record_id = ?',
                                   (target_collection, target.id))
                connection.execute('''INSERT OR IGNORE INTO memory_tombstones
                    (collection, record_id, source_id, owner_user_id, workspace_id, project_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)''', (
                        target_collection, target.id, target.source.id if isinstance(target, DocumentRecord) else None,
                        actor.id, target.workspace_id, target.project_id, changed_at.isoformat(),
                    ))
            # The aggregate automatic signal is public and cannot retain forgotten material.
            # Clear it conservatively; a future tick can summarize only remaining eligible inputs.
            self.repository._withdraw_market_signal_in_transaction(connection, actor.id)
            result = MemoryForgetResultV1(target_id=target_id, invalidated_count=len(targets))
            connection.execute("INSERT INTO records(collection, id, payload) VALUES ('memory_forget_commands', ?, ?)",
                               (receipt_id, json.dumps({'request_hash': request_hash,
                                                        'result': result.model_dump(mode='json')})))
            self.repository._upsert_plain_record(connection, 'audit_events', AuditEvent(
                actor=actor.id, action='withdraw_memory_source' if collection == 'documents' else 'forget_private_memory',
                target_type=collection, target_id=target_id, workspace_id=actor.workspace_id, project_id=item.project_id,
                metadata={'invalidated_count': len(targets)}, created_at=changed_at,
            ))
        return result

    @staticmethod
    def _dependents(connection: sqlite3.Connection, collection: str,
                    root: DocumentRecord | UserMemoryItem) -> list[tuple[str, UserMemoryItem | MemoryItem]]:
        # Traverse only recorded lineage in the source's own project; never guess from text similarity.
        rows = connection.execute('''SELECT collection, payload FROM records
            WHERE collection IN ('user_memory_items', 'memory_items')
              AND json_extract(payload, '$.workspace_id') = ?
              AND json_extract(payload, '$.project_id') IS ?''', (root.workspace_id, root.project_id)).fetchall()
        remaining = []
        for row in rows:
            model = UserMemoryItem if row['collection'] == 'user_memory_items' else MemoryItem
            item = model.model_validate_json(row['payload'])
            if row['collection'] == collection and item.id == root.id:
                continue
            if isinstance(item, UserMemoryItem) and item.user_id != (
                root.uploaded_by if isinstance(root, DocumentRecord) else root.user_id
            ):
                continue
            remaining.append((row['collection'], item))
        frozen = {} if isinstance(root, DocumentRecord) else {root.id: (root.version, memory_content_hash(root))}
        result = []
        while remaining:
            next_remaining = []
            for child_collection, child in remaining:
                proven = bool(child.provenance and any(
                    _matches_source(frozen, parent_id, version, content_hash)
                    for parent_id, version, content_hash in zip(
                        child.provenance.source_memory_ids, child.provenance.source_memory_versions,
                        child.provenance.source_memory_hashes, strict=False,
                    )
                ))
                if isinstance(child, MemoryItem):
                    proven |= _matches_source(frozen, child.metadata.get('source_memory_id', ''),
                                              child.metadata.get('source_memory_version', ''),
                                              child.metadata.get('source_memory_hash'))
                if isinstance(root, DocumentRecord):
                    proven |= any(source.id == root.source.id or source.reference.startswith(f'document://{root.id}#')
                                  for source in child.sources)
                    proven |= any(ref.record_type == 'document' and ref.record_id == root.id
                                  for fact in child.facts or [] for ref in fact.evidence_refs)
                if proven:
                    result.append((child_collection, child))
                    frozen[child.id] = (child.version, memory_content_hash(child))
                else:
                    next_remaining.append((child_collection, child))
            if len(next_remaining) == len(remaining):
                break
            remaining = next_remaining
        return result

    def cleanup(self, *, limit: int = 100) -> int:
        if not 1 <= limit <= 100:
            raise ValueError('cleanup limit must be between 1 and 100')
        with closing(self.repository._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            rows = connection.execute('SELECT collection, record_id FROM memory_tombstones WHERE cleaned_at IS NULL '
                                      'ORDER BY created_at, collection, record_id LIMIT ?', (limit,)).fetchall()
            for row in rows:
                identity = (row['collection'], row['record_id'])
                for table in ('records_fts', 'records_vec', 'vector_states'):
                    connection.execute(f'DELETE FROM {table} WHERE collection = ? AND record_id = ?', identity)
                connection.execute('UPDATE memory_tombstones SET cleaned_at = ? WHERE collection = ? AND record_id = ?',
                                   (self.clock().isoformat(), *identity))
        return len(rows)
