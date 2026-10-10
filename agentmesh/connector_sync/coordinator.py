"""Single-process, opt-in page scheduling on the existing durable cursor."""
from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from contextlib import closing, suppress
from datetime import datetime

from agentmesh.connector_sync.configuration import configured_reader
from agentmesh.connector_sync.contracts import ConnectorSyncCursorV1, ConnectorSyncError
from agentmesh.connector_sync.service import ConnectorSyncService
from agentmesh.models import User, now_utc
from agentmesh.skill_runtime.quiesce import OrchestrationQuiesceController
from agentmesh.store import SQLiteStore


def worker_enabled() -> bool:
    return os.getenv('AGENTMESH_CONNECTOR_WORKER_ENABLED', 'false').lower() in {'1', 'true', 'yes'}


class ConnectorSyncCoordinator:
    def __init__(self, repository: SQLiteStore, *, enabled: Callable[[], bool] = worker_enabled,
                 admission: OrchestrationQuiesceController | None = None):
        self.repository, self.enabled, self.admission = repository, enabled, admission
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._stopping = False
        self._reconcile_after = ''
        self._due_after = ''
        self._active: tuple[User, str, str, int] | None = None
        self.last_error_code: str | None = None
        self.last_tick_at: datetime | None = None

    def _allowed(self) -> bool:
        return not self._stopping and self.enabled() and not (self.admission and self.admission.is_quiescing)

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def available(self) -> bool:
        return self.running and self._allowed()

    async def start(self) -> None:
        if self.enabled() and not self.running:
            self._stopping = False
            self._task = asyncio.create_task(self._loop(), name='agentmesh-connectors')

    async def stop(self) -> None:
        self._stopping = True
        if self._active:
            user, project_id, cursor_id, version = self._active
            with suppress(ConnectorSyncError):
                await asyncio.to_thread(ConnectorSyncService.control, self.repository, user,
                    project_id=project_id, cursor_id=cursor_id, expected_version=version, action='cancel')
        task, self._task = self._task, None
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    def _reconcile(self) -> None:
        with closing(self.repository._read_connect()) as connection:
            rows = connection.execute("SELECT id, payload FROM records WHERE collection = 'connector_sync_cursors' "
                "AND id > ? AND COALESCE(json_extract(payload, '$.enabled'), 1) = 1 "
                "AND COALESCE(json_extract(payload, '$.operator_bound'), 1) = 1 ORDER BY id LIMIT 20",
                (self._reconcile_after,)).fetchall()
        self._reconcile_after = rows[-1]['id'] if rows else ''
        seen = set()
        for row in rows:
            cursor = ConnectorSyncCursorV1.model_validate_json(row['payload'])
            scope = (cursor.owner_user_id, cursor.project_id)
            if scope in seen:
                continue
            seen.add(scope)
            user = self.repository.get_user(cursor.owner_user_id)
            if user is None or user.id != cursor.owner_user_id or user.status != 'active':
                continue
            try:
                ConnectorSyncService.reconcile_bindings(self.repository, user, project_id=cursor.project_id)
            except ConnectorSyncError as error:
                if error.status_code != 404:
                    raise

    async def tick(self) -> int:
        if not self._allowed() or self._lock.locked():
            return 0
        async with self._lock:
            await asyncio.to_thread(self._reconcile)
            with closing(self.repository._read_connect()) as connection:
                rows = connection.execute("SELECT id, payload FROM records WHERE collection = 'connector_sync_cursors' "
                    "AND id > ? "
                    "AND json_extract(payload, '$.auto_sync_enabled') = 1 "
                    "AND json_extract(payload, '$.enabled') = 1 AND json_extract(payload, '$.operator_bound') = 1 "
                    "AND json_extract(payload, '$.status') != 'reading' "
                    "AND julianday(json_extract(payload, '$.next_sync_at')) <= julianday(?) "
                    "AND (json_extract(payload, '$.next_allowed_at') IS NULL "
                    "OR julianday(json_extract(payload, '$.next_allowed_at')) <= julianday(?)) "
                    "ORDER BY id LIMIT 20",
                    (self._due_after, now_utc().isoformat(), now_utc().isoformat())).fetchall()
            if not rows:
                self._due_after = ''
                return 0
            for row in rows:
                if not self._allowed():
                    return 0
                self._due_after = row['id']
                cursor = ConnectorSyncCursorV1.model_validate_json(row['payload'])
                user = self.repository.get_user(cursor.owner_user_id)
                if user is None or user.id != cursor.owner_user_id or user.status != 'active':
                    continue
                try:
                    reader = configured_reader(cursor.project_id, cursor.provider)
                    if reader.namespace != cursor.namespace:
                        continue
                    service = ConnectorSyncService(self.repository, reader,
                        current_configuration_hash=lambda project_id=cursor.project_id, provider=cursor.provider:
                            configured_reader(project_id, provider).configuration_hash(),
                        continue_allowed=self._allowed)
                    self._active = (user, cursor.project_id, cursor.id, cursor.version + 1)
                    await asyncio.to_thread(service.sync_page, user, project_id=cursor.project_id,
                                            expected_version=cursor.version, automatic=True)
                    return 1
                except ConnectorSyncError as error:
                    if error.status_code != 404:
                        return 0
                finally:
                    self._active = None
            return 0

    async def _loop(self) -> None:
        while self._allowed():
            try:
                await self.tick()
                self.last_tick_at, self.last_error_code = now_utc(), None
            except Exception:
                self.last_error_code = 'connector_tick_failed'
            await asyncio.sleep(5)
