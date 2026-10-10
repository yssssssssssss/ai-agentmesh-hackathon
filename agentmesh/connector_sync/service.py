from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import closing, suppress
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Protocol
from uuid import uuid4

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.connector_sync.authority import connector_id, operator_binding_current
from agentmesh.connector_sync.contracts import ConnectorPageV1, ConnectorSyncCursorV1, ConnectorSyncError
from agentmesh.document_memory import DocumentMemoryStore
from agentmesh.memory_facts import MemoryFactsError, authorize_fact_project
from agentmesh.models import AuditEvent, DocumentRecord, Source, User, now_utc
from agentmesh.source_authority import observe_source_in_transaction
from agentmesh.store import SQLiteStore


class ConnectorReader(Protocol):
    provider: str
    namespace: str
    supports_incremental: bool

    def configuration_hash(self) -> str: ...

    def read_page(self, position: str | None, *, since: datetime | None = None) -> ConnectorPageV1: ...


class ConnectorSyncService:
    def __init__(self, repository: SQLiteStore, reader: ConnectorReader, *,
                 current_configuration_hash: Callable[[], str] | None = None,
                 continue_allowed: Callable[[], bool] | None = None):
        self.repository, self.reader = repository, reader
        self._configuration_hash = current_configuration_hash or reader.configuration_hash
        self._operator_bound = current_configuration_hash is not None
        self._continue_allowed = continue_allowed or (lambda: True)

    def _id(self, user: User, project_id: str) -> str:
        return self._cursor_id(user, project_id, self.reader.provider, self.reader.namespace)

    @staticmethod
    def _cursor_id(user: User, project_id: str, provider: str, namespace: str) -> str:
        return connector_id(user.id, user.workspace_id, project_id, provider, namespace)

    @classmethod
    def authorize_project(cls, repository: SQLiteStore, user: User, project_id: str) -> User:
        with closing(repository._read_connect()) as connection, connection:
            connection.execute('BEGIN')
            return cls._authorize(connection, user, project_id)

    def cursor(self, user: User, *, project_id: str) -> ConnectorSyncCursorV1 | None:
        with closing(self.repository._read_connect()) as connection, connection:
            connection.execute('BEGIN')
            actor = self._authorize(connection, user, project_id)
            return self._cursor_in_transaction(connection, actor, project_id)

    def _cursor_in_transaction(self, connection, actor: User, project_id: str) -> ConnectorSyncCursorV1 | None:
        cursor_id = self._id(actor, project_id)
        current = self.repository._get_in_transaction(connection, 'connector_sync_cursors',
                                                     cursor_id, ConnectorSyncCursorV1)
        if current and (current.id, current.owner_user_id, current.workspace_id, current.project_id,
                        current.provider, current.namespace) != (
            cursor_id, actor.id, actor.workspace_id, project_id, self.reader.provider, self.reader.namespace):
            raise ConnectorSyncError('connector_cursor_conflict')
        return current

    @staticmethod
    def _authorize(connection, user, project_id):
        try:
            return authorize_fact_project(connection, user, project_id)[0]
        except MemoryFactsError:
            raise ConnectorSyncError('connector_not_found', status_code=404) from None

    def _next_cursor(self, actor: User, project_id: str, configuration_hash: str,
                     current: ConnectorSyncCursorV1 | None, mode: str) -> ConnectorSyncCursorV1:
        started = now_utc()
        claim = {'read_claim_id': uuid4().hex, 'read_lease_until': started + timedelta(seconds=90), 'status': 'reading'}
        if current and current.scan_started_at and (
            current.next_position is not None or current.status in {'failed', 'reading'}):
            return current.model_copy(update=claim | {'version': current.version + 1,
                'operator_bound': current.operator_bound or self._operator_bound})
        full = (mode == 'full' or not self.reader.supports_incremental or current is None
                or current.watermark_at is None or current.last_full_sync_at is None
                or current.status == 'cancelled'
                or current.last_error_code in {'connector_access_unavailable', 'connector_root_unavailable'}
                or started - current.last_full_sync_at >= timedelta(days=1))
        values = current.model_dump() if current else {}
        values.update(id=self._id(actor, project_id), owner_user_id=actor.id, workspace_id=actor.workspace_id,
            project_id=project_id, provider=self.reader.provider, namespace=self.reader.namespace,
            configuration_hash=configuration_hash, version=current.version + 1 if current else 1,
            operator_bound=self._operator_bound or bool(current and current.operator_bound),
            status='syncing', next_position=None, observed_count=0, scan_mode='full' if full else 'incremental',
            scan_started_at=started, scan_since=None if full else current.watermark_at - timedelta(seconds=60),
            seen_source_ids=[])
        values.update(claim)
        return ConnectorSyncCursorV1.model_validate(values)

    def _commit_actor(self, connection, user: User, project_id: str, configuration_hash: str,
                      current: ConnectorSyncCursorV1 | None) -> User:
        actor = self._authorize(connection, user, project_id)
        if (self._cursor_in_transaction(connection, actor, project_id) != current
            or self.reader.configuration_hash() != configuration_hash
            or self._configuration_hash() != configuration_hash):
            raise ConnectorSyncError('connector_cursor_conflict')
        return actor

    def _claimed_actor(self, connection, user: User, project_id: str, claim: ConnectorSyncCursorV1) -> User:
        if not self._continue_allowed():
            raise ConnectorSyncError('connector_worker_stopped')
        actor = self._commit_actor(connection, user, project_id, claim.configuration_hash, claim)
        if not claim.read_claim_id or claim.read_lease_until is None or claim.read_lease_until <= now_utc():
            raise ConnectorSyncError('connector_read_expired')
        return actor

    @staticmethod
    def _save_cursor(repository: SQLiteStore, connection, actor: User, cursor: ConnectorSyncCursorV1,
                     *, action: str = 'sync_connector_page') -> None:
        cursor = ConnectorSyncCursorV1.model_validate(cursor.model_dump())
        repository._upsert_plain_record(connection, 'connector_sync_cursors', cursor)
        repository._upsert_plain_record(connection, 'audit_events', AuditEvent(actor=actor.id,
            action=action, target_type='connector', target_id=cursor.id,
            workspace_id=actor.workspace_id, project_id=cursor.project_id,
            metadata={'provider': cursor.provider, 'version': cursor.version, 'status': cursor.status,
                      'observed_count': cursor.observed_count, 'error_code': cursor.last_error_code}))

    @staticmethod
    def _unavailable(repository: SQLiteStore, connection, actor: User, versions: dict[str, int], excluded: set[str],
                     observed_at: datetime, *, before: datetime | None = None) -> None:
        for source_id, revision in versions.items():
            if source_id in excluded:
                continue
            source = repository._get_in_transaction(connection, 'sources', source_id, Source)
            if (source is None or source.snapshot is None or source.snapshot.lifecycle != 'active'
                or (before is not None and source.snapshot.observed_at >= before)):
                continue
            source = source.model_copy(update={'snapshot': source.snapshot.model_copy(update={
                'lifecycle': 'unavailable', 'observed_at': observed_at})})
            observe_source_in_transaction(repository, connection, source, body=None,
                                          user=actor, expected_revision=revision)

    def _record_failure(self, user: User, project_id: str, proposed: ConnectorSyncCursorV1,
                        versions: dict[str, int], error: ConnectorSyncError) -> None:
        observed_at = now_utc()
        safe_codes = {'connector_access_unavailable', 'connector_provider_unavailable', 'connector_rate_limited', 'connector_response_invalid',
            'connector_response_too_large', 'connector_pagination_invalid', 'connector_position_invalid',
            'connector_root_unavailable', 'connector_document_unavailable', 'connector_document_too_large',
            'connector_inventory_limit', 'connector_path_invalid'}
        code = error.code if error.code in safe_codes else 'connector_provider_unavailable'
        with closing(self.repository._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            actor = self._claimed_actor(connection, user, project_id, proposed)
            if code in {'connector_access_unavailable', 'connector_root_unavailable'}:
                self._unavailable(self.repository, connection, actor, versions, set(), observed_at)
                proposed = proposed.model_copy(update={'scan_started_at': None, 'next_position': None,
                                                       'scan_since': None, 'seen_source_ids': [], 'scan_mode': 'full'})
            failed = proposed.model_copy(update={'status': 'failed', 'last_failed_at': observed_at,
                'read_claim_id': None, 'read_lease_until': None,
                'last_error_code': code, **self._retry_schedule(proposed, error, observed_at)})
            self._save_cursor(self.repository, connection, actor, failed)

    @staticmethod
    def _retry_schedule(cursor: ConnectorSyncCursorV1, error: ConnectorSyncError, at: datetime) -> dict:
        failures = min(cursor.consecutive_failures + 1, 2147483647)
        delay = max(5 if failures == 1 else 30, error.retry_after)
        allowed_at = cursor.next_allowed_at
        if error.retry_after > 0:
            try:
                allowed_at = at + timedelta(seconds=error.retry_after)
            except OverflowError:
                allowed_at = datetime.max.replace(tzinfo=at.tzinfo)
        retry = cursor.auto_sync_enabled and error.retryable and failures < 3 and delay <= 86400
        return {'consecutive_failures': failures, 'auto_sync_enabled': retry,
                'next_sync_at': at + timedelta(seconds=delay) if retry else None, 'next_allowed_at': allowed_at}

    def _check_wait(self, connection, current: ConnectorSyncCursorV1 | None, configuration_hash: str) -> None:
        at = now_utc()
        waiting = connection.execute("SELECT 1 FROM records WHERE collection = 'connector_sync_cursors' "
            "AND json_extract(payload, '$.provider') = ? AND json_extract(payload, '$.configuration_hash') = ? "
            "AND json_extract(payload, '$.operator_bound') = 1 "
            "AND julianday(json_extract(payload, '$.next_allowed_at')) > julianday(?) LIMIT 1",
            (self.reader.provider, configuration_hash, at.isoformat())).fetchone()
        if waiting or (current and current.next_allowed_at is not None and current.next_allowed_at > at):
            raise ConnectorSyncError('connector_retry_wait', status_code=429)

    def sync_page(self, user: User, *, project_id: str, expected_version: int,
                  mode: str = 'incremental', automatic: bool = False) -> ConnectorSyncCursorV1:
        if mode not in {'incremental', 'full'}:
            raise ConnectorSyncError('connector_configuration_invalid', status_code=422)
        configuration_hash = self._configuration_hash()
        if self.reader.configuration_hash() != configuration_hash:
            raise ConnectorSyncError('connector_configuration_changed')
        with closing(self.repository._read_connect()) as connection, connection:
            connection.execute('BEGIN')
            actor = self._authorize(connection, user, project_id)
            current = self._cursor_in_transaction(connection, actor, project_id)
            version = current.version if current else 0
            if type(expected_version) is not int or expected_version != version or version >= 2147483647:
                raise ConnectorSyncError('connector_cursor_conflict')
            if current and (not current.enabled or current.status == 'disabled'):
                raise ConnectorSyncError('connector_disabled')
            if current and current.status == 'reading' and (
                current.read_lease_until is None or current.read_lease_until > now_utc()):
                raise ConnectorSyncError('connector_busy')
            if current and current.configuration_hash != configuration_hash:
                raise ConnectorSyncError('connector_configuration_changed')
            self._check_wait(connection, current, configuration_hash)
            if automatic and (current is None or not current.auto_sync_enabled or current.next_sync_at is None
                              or current.next_sync_at > now_utc()):
                raise ConnectorSyncError('connector_not_due')
            source_versions = self._source_versions(connection, actor, project_id, self.reader.provider,
                                                     self.reader.namespace)
            proposed = self._next_cursor(actor, project_id, configuration_hash, current, mode)
        with closing(self.repository._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            actor = self._commit_actor(connection, user, project_id, configuration_hash, current)
            self._check_wait(connection, current, configuration_hash)
            if not self._continue_allowed():
                raise ConnectorSyncError('connector_worker_stopped')
            self._save_cursor(self.repository, connection, actor, proposed, action='claim_connector_page')
        try:
            return self._read_and_commit(user, project_id, proposed, source_versions)
        except Exception as error:
            code = 'connector_read_interrupted'
            if isinstance(error, ConnectorSyncError):
                if error.status_code == 404:
                    code = 'connector_authority_changed'
                elif error.code == 'connector_read_expired':
                    code = error.code
            # Preserve the original failure; a broken writer leaves the lease for recovery.
            with suppress(sqlite3.Error):
                self._abandon_claim(actor, proposed, code)
            raise

    def _read_and_commit(self, user: User, project_id: str, proposed: ConnectorSyncCursorV1,
                         source_versions: dict[str, int]) -> ConnectorSyncCursorV1:
        try:
            page = self.reader.read_page(proposed.next_position, since=proposed.scan_since)
            try:
                page = ConnectorPageV1.model_validate(page.model_dump())
            except ValueError:
                raise ConnectorSyncError('connector_response_invalid', status_code=503) from None
        except ConnectorSyncError as error:
            self._record_failure(user, project_id, proposed, source_versions, error)
            raise
        observed_at = now_utc()
        with closing(self.repository._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            actor = self._claimed_actor(connection, user, project_id, proposed)
            seen = set(proposed.seen_source_ids)
            for item in page.observations:
                digest = canonical_json_sha256({'connector': self._id(actor, project_id), 'external_id': item.external_id})
                source = Source(id='src_connector_' + digest[:32], title=item.title,
                    source_type=self.reader.provider, reference=item.reference, user_id=actor.id,
                    workspace_id=actor.workspace_id, project_id=project_id,
                    snapshot={'provider': self.reader.provider, 'external_id': self.reader.namespace + ':' + item.external_id,
                        'version': item.version, 'body_sha256': sha256(item.text.encode('utf-8')).hexdigest(),
                        'revision': 1, 'observed_at': observed_at})
                source = observe_source_in_transaction(self.repository, connection, source, body=item.text,
                    user=actor, expected_revision=source_versions.get(source.id, 0))
                seen.add(source.id)
                if len(seen) > 1000:
                    raise ConnectorSyncError('connector_inventory_limit', status_code=422)
                document_id = 'doc_connector_' + digest[:32]
                prior = self.repository._get_in_transaction(connection, 'documents', document_id, DocumentRecord)
                if prior and (prior.id != document_id or prior.uploaded_by != actor.id or prior.project_id != project_id
                              or prior.workspace_id != actor.workspace_id or prior.source.id != source.id):
                    raise ConnectorSyncError('connector_document_conflict')
                if prior and prior.source == source and prior.text == item.text and prior.title == item.title:
                    continue
                if prior and prior.withdrawn_at is not None:
                    continue
                document = DocumentRecord(id=document_id, title=item.title, file_name=item.external_id[:512],
                    content_type='text/plain', text=item.text, source=source, uploaded_by=actor.id,
                    workspace_id=actor.workspace_id, project_id=project_id, version=prior.version + 1 if prior else 1,
                    created_at=prior.created_at if prior else observed_at, updated_at=observed_at)
                self.repository._upsert_plain_record(connection, 'documents', document)
                self.repository._sync_fts(connection, 'documents', document)
                self.repository.vector_index.prepare(connection, 'documents', document.id, document.text)
                if prior:
                    DocumentMemoryStore._invalidate_previous(connection, document)
            completed = page.next_position is None
            if completed and proposed.scan_mode == 'full':
                self._unavailable(self.repository, connection, actor, source_versions, seen, observed_at,
                                  before=proposed.scan_started_at)
            cursor = proposed.model_copy(update=dict(
                next_position=page.next_position, last_successful_at=observed_at, status='idle' if completed else 'syncing',
                completed_at=observed_at if completed else proposed.completed_at,
                read_claim_id=None, read_lease_until=None,
                observed_count=len(page.observations), last_error_code=None, consecutive_failures=0, next_allowed_at=None,
                watermark_at=proposed.scan_started_at if completed else proposed.watermark_at,
                last_full_sync_at=observed_at if completed and proposed.scan_mode == 'full' else proposed.last_full_sync_at,
                seen_source_ids=[] if completed else sorted(seen),
                scan_started_at=None if completed else proposed.scan_started_at))
            if proposed.auto_sync_enabled:
                cursor = cursor.model_copy(update={'next_sync_at': observed_at + timedelta(
                    seconds=proposed.interval_seconds if completed else 5)})
            self._save_cursor(self.repository, connection, actor, cursor)
            return cursor

    def _abandon_claim(self, actor: User, claim: ConnectorSyncCursorV1, code: str) -> None:
        # Settlement only releases this previously authorized claim. It cannot
        # observe data, restore access, or modify a replacement execution.
        with closing(self.repository._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            current = self.repository._get_in_transaction(connection, 'connector_sync_cursors', claim.id,
                                                          ConnectorSyncCursorV1)
            if current != claim:
                return
            failed = claim.model_copy(update={'status': 'failed', 'read_claim_id': None, 'read_lease_until': None,
                'auto_sync_enabled': False, 'next_sync_at': None,
                'last_failed_at': now_utc(), 'last_error_code': code,
                'consecutive_failures': min(claim.consecutive_failures + 1, 2147483647)})
            self._save_cursor(self.repository, connection, actor, failed, action='settle_connector_read')

    @staticmethod
    def _source_versions(connection, actor: User, project_id: str, provider: str, namespace: str) -> dict[str, int]:
        versions = {row['id']: row['revision'] for row in connection.execute(
                "SELECT id, COALESCE(json_extract(payload, '$.snapshot.revision'), 0) AS revision FROM records "
                "WHERE collection = 'sources' AND json_extract(payload, '$.user_id') = ? "
                "AND json_extract(payload, '$.workspace_id') = ? AND json_extract(payload, '$.project_id') = ? "
                "AND json_extract(payload, '$.snapshot.provider') = ? "
                "AND substr(json_extract(payload, '$.snapshot.external_id'), 1, ?) = ? LIMIT 1001",
                (actor.id, actor.workspace_id, project_id, provider, len(namespace) + 1, namespace + ':')).fetchall()}
        if len(versions) > 1000:
            raise ConnectorSyncError('connector_inventory_limit', status_code=422)
        return versions

    @classmethod
    def _stored_cursor(cls, repository, connection, actor, project_id, cursor_id) -> ConnectorSyncCursorV1:
        cursor = repository._get_in_transaction(connection, 'connector_sync_cursors', cursor_id, ConnectorSyncCursorV1)
        if cursor is None or (cursor.id, cursor.owner_user_id, cursor.workspace_id, cursor.project_id) != (
            cursor_id, actor.id, actor.workspace_id, project_id):
            raise ConnectorSyncError('connector_not_found', status_code=404)
        if cursor.id != cls._cursor_id(actor, project_id, cursor.provider, cursor.namespace):
            raise ConnectorSyncError('connector_cursor_conflict')
        return cursor

    @classmethod
    def stored_cursors(cls, repository: SQLiteStore, user: User, *, project_id: str) -> list[ConnectorSyncCursorV1]:
        with closing(repository._read_connect()) as connection, connection:
            connection.execute('BEGIN')
            actor = cls._authorize(connection, user, project_id)
            rows = connection.execute("SELECT id FROM records WHERE collection = 'connector_sync_cursors' "
                "AND json_extract(payload, '$.owner_user_id') = ? AND json_extract(payload, '$.workspace_id') = ? "
                "AND json_extract(payload, '$.project_id') = ? ORDER BY id LIMIT 101",
                (actor.id, actor.workspace_id, project_id)).fetchall()
            if len(rows) > 100:
                raise ConnectorSyncError('connector_inventory_limit', status_code=422)
            return [cls._stored_cursor(repository, connection, actor, project_id, row['id']) for row in rows]

    @classmethod
    def reconcile_bindings(cls, repository: SQLiteStore, user: User, *, project_id: str) -> int:
        invalidated = 0
        for candidate in cls.stored_cursors(repository, user, project_id=project_id):
            expired = (candidate.status == 'reading' and candidate.read_lease_until is not None
                       and candidate.read_lease_until <= now_utc())
            if not candidate.enabled or (operator_binding_current(candidate) and not expired):
                continue
            with closing(repository._connect()) as connection, connection:
                connection.execute('BEGIN IMMEDIATE')
                actor = cls._authorize(connection, user, project_id)
                current = cls._stored_cursor(repository, connection, actor, project_id, candidate.id)
                if current != candidate:
                    continue
                if current.version >= 2147483647:
                    raise ConnectorSyncError('connector_cursor_conflict')
                observed_at = now_utc()
                values = {'version': current.version + 1, 'read_claim_id': None,
                          'read_lease_until': None, 'last_failed_at': observed_at}
                if not operator_binding_current(current):
                    versions = cls._source_versions(connection, actor, project_id, current.provider, current.namespace)
                    cls._unavailable(repository, connection, actor, versions, set(), observed_at)
                    values.update(enabled=False, status='disabled', auto_sync_enabled=False, next_sync_at=None,
                        next_position=None, scan_started_at=None,
                        scan_since=None, seen_source_ids=[], observed_count=0, last_error_code='connector_configuration_changed')
                    action = 'connector_binding_invalidated'
                elif current.read_lease_until is not None and current.read_lease_until <= observed_at:
                    values.update(status='failed', last_error_code='connector_read_expired',
                                  **cls._retry_schedule(current, ConnectorSyncError('connector_read_expired',
                                      retryable=True), observed_at))
                    action = 'recover_connector_read'
                else:
                    continue
                result = current.model_copy(update=values)
                cls._save_cursor(repository, connection, actor, result, action=action)
                invalidated += 1
        return invalidated

    @classmethod
    def reconcile_startup_bindings(cls, repository: SQLiteStore) -> int:
        last_id, seen, invalidated = '', set(), 0
        while True:
            with closing(repository._read_connect()) as connection:
                rows = connection.execute("SELECT id, json_extract(payload, '$.owner_user_id') AS owner_id, "
                    "json_extract(payload, '$.project_id') AS project_id FROM records "
                    "WHERE collection = 'connector_sync_cursors' AND id > ? "
                    "AND COALESCE(json_extract(payload, '$.enabled'), 1) = 1 "
                    "AND COALESCE(json_extract(payload, '$.operator_bound'), 1) = 1 ORDER BY id LIMIT 100",
                    (last_id,)).fetchall()
            if not rows:
                return invalidated
            last_id = rows[-1]['id']
            for row in rows:
                key = (row['owner_id'], row['project_id'])
                if key in seen:
                    continue
                seen.add(key)
                user = repository.get_user(row['owner_id'])
                if user is None or user.id != row['owner_id'] or user.status != 'active':
                    continue
                try:
                    invalidated += cls.reconcile_bindings(repository, user, project_id=row['project_id'])
                except ConnectorSyncError as error:
                    if error.status_code != 404:
                        raise

    @classmethod
    def control(cls, repository: SQLiteStore, user: User, *, project_id: str, cursor_id: str,
                expected_version: int, action: str, reader: ConnectorReader | None = None,
                current_configuration_hash: Callable[[], str] | None = None,
                interval_seconds: int = 900) -> ConnectorSyncCursorV1:
        if action not in {'disable', 'reset', 'cancel', 'enable_auto', 'pause_auto'}:
            raise ConnectorSyncError('connector_configuration_invalid', status_code=422)
        with closing(repository._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            actor = cls._authorize(connection, user, project_id)
            current = cls._stored_cursor(repository, connection, actor, project_id, cursor_id)
            if type(expected_version) is not int or expected_version != current.version or current.version >= 2147483647:
                raise ConnectorSyncError('connector_cursor_conflict')
            if action in {'enable_auto', 'pause_auto'}:
                values = {'version': current.version + 1, 'auto_sync_enabled': action == 'enable_auto',
                          'next_sync_at': None}
                if action == 'enable_auto':
                    if type(interval_seconds) is not int or not 300 <= interval_seconds <= 86400:
                        raise ConnectorSyncError('connector_configuration_invalid', status_code=422)
                    if not current.enabled:
                        raise ConnectorSyncError('connector_disabled')
                    if (reader is None or current_configuration_hash is None
                        or (reader.provider, reader.namespace) != (current.provider, current.namespace)
                        or reader.configuration_hash() != current.configuration_hash
                        or current_configuration_hash() != current.configuration_hash):
                        raise ConnectorSyncError('connector_configuration_changed')
                    if current.status == 'reading':
                        raise ConnectorSyncError('connector_busy')
                    values.update(operator_bound=True, interval_seconds=interval_seconds,
                                  next_sync_at=max(now_utc(), current.next_allowed_at or now_utc()), consecutive_failures=0)
                elif current.status == 'reading':
                    values.update(status='cancelled', read_claim_id=None, read_lease_until=None,
                                  scan_started_at=None, scan_since=None, next_position=None, seen_source_ids=[])
                result = current.model_copy(update=values)
                cls._save_cursor(repository, connection, actor, result, action='connector_' + action)
                return result
            values = dict(version=current.version + 1, next_position=None, scan_started_at=None,
                          scan_since=None, seen_source_ids=[], observed_count=0, last_error_code=None,
                          read_claim_id=None, read_lease_until=None,
                          auto_sync_enabled=False, next_sync_at=None,
                          consecutive_failures=0, status='disabled' if action == 'disable' else 'cancelled')
            if action == 'reset':
                if reader is None or (reader.provider, reader.namespace) != (current.provider, current.namespace):
                    raise ConnectorSyncError('connector_not_found', status_code=404)
                configuration_hash = reader.configuration_hash()
                if current_configuration_hash and current_configuration_hash() != configuration_hash:
                    raise ConnectorSyncError('connector_configuration_changed')
                values.update(configuration_hash=configuration_hash, enabled=True, status='idle', scan_mode='full',
                              watermark_at=None, last_full_sync_at=None, completed_at=None,
                              operator_bound=current.operator_bound or current_configuration_hash is not None)
            elif action == 'disable':
                values['enabled'] = False
            elif not current.enabled:
                raise ConnectorSyncError('connector_disabled')
            if action in {'disable', 'reset'}:
                versions = cls._source_versions(connection, actor, project_id, current.provider, current.namespace)
                cls._unavailable(repository, connection, actor, versions, set(), now_utc())
            result = current.model_copy(update=values)
            cls._save_cursor(repository, connection, actor, result, action='connector_' + action)
            return result
