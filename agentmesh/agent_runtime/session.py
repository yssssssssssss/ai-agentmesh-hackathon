from __future__ import annotations

import asyncio
import json
from typing import Any

from agentmesh.models import AgentRun, ChatMessage, ChatRole, SDKSessionRecord, new_id, now_utc
from agentmesh.store import SDKSessionConflict, SQLiteStore


def _json_item(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        payload = item
    elif hasattr(item, "model_dump"):
        payload = item.model_dump(mode="json")
    else:
        payload = json.loads(json.dumps(item, default=str))
    return json.loads(json.dumps(payload, ensure_ascii=False, default=str))


class AgentMeshSession:
    """OpenAI Agents SDK Session protocol backed by AgentMesh's SQLiteStore."""

    session_settings = None

    def __init__(self, session_id: str, repository: SQLiteStore, *, run: AgentRun):
        if session_id != run.thread_id:
            raise SDKSessionConflict('sdk_session_not_authorized')
        self.session_id = session_id
        self.repository = repository
        self._run = run.model_copy(deep=True)
        self._version: int | None = None
        self._lock = asyncio.Lock()

    async def _read(self) -> SDKSessionRecord:
        record = await asyncio.to_thread(self.repository.get_sdk_session, self.session_id, run=self._run)
        self._version = record.version
        return record

    def validate_handoff(self, expected_version: int) -> None:
        record = self.repository.get_sdk_session(self.session_id, run=self._run)
        if record.version != expected_version:
            raise SDKSessionConflict('sdk_session_version_changed')

    def validate_current_handoff(self) -> None:
        if self._version is None:
            raise SDKSessionConflict('sdk_session_version_missing')
        self.validate_handoff(self._version)

    def remaining_seconds(self, maximum: float) -> float:
        if self._run.deadline_at is None:
            return maximum
        return min(maximum, max(0.0, (self._run.deadline_at - now_utc()).total_seconds()))

    def _check_wrapper(self, wrapper: Any) -> None:
        if wrapper is None:
            return
        context = wrapper.context
        expected = {'user_id': self._run.user_id, 'workspace_id': self._run.workspace_id,
                    'project_id': self._run.project_id, 'thread_id': self._run.thread_id, 'run_id': self._run.id}
        if any(getattr(context, field, None) != value for field, value in expected.items()):
            raise SDKSessionConflict('sdk_session_not_authorized')

    async def bootstrap(self, history: list[ChatMessage]) -> None:
        messages: list[tuple[str, dict[str, Any]]] = []
        for message in history:
            if message.role == ChatRole.USER:
                item = {"role": "user", "content": message.content}
            elif message.role == ChatRole.ASSISTANT:
                item = {"role": "assistant", "content": message.content}
            else:
                continue
            messages.append((message.id, item))
        async with self._lock:
            record = await asyncio.to_thread(self.repository.reconcile_sdk_session_messages, self.session_id, messages,
                                            run=self._run)
            self._version = record.version

    async def get_items(self, limit: int | None = None, *, wrapper=None) -> list[dict[str, Any]]:  # noqa: ANN001
        self._check_wrapper(wrapper)
        async with self._lock:
            record = await self._read()
        items = list(record.items)
        if limit is None:
            return items
        if limit <= 0:
            return []
        return items[-limit:]

    async def add_items(self, items, *, wrapper=None) -> None:  # noqa: ANN001
        self._check_wrapper(wrapper)
        normalized = [_json_item(item) for item in items]
        async with self._lock:
            if self._version is None:
                await self._read()
            record = await asyncio.to_thread(self.repository.append_sdk_session_items, self.session_id, normalized,
                                            run=self._run, expected_version=self._version,
                                            command_id=new_id('session_commit'))
            self._version = record.version

    async def mark_chat_messages(self, message_ids: list[str]) -> None:
        async with self._lock:
            record = await asyncio.to_thread(self.repository.mark_sdk_session_chat_messages, self.session_id, message_ids,
                                            run=self._run)
            self._version = record.version

    async def snapshot(self) -> tuple[list[dict[str, Any]], int]:
        async with self._lock:
            record = await self._read()
            return list(record.items), record.version

    async def replace_items(self, items: list[dict[str, Any]], *, expected_version: int) -> bool:
        normalized = [_json_item(item) for item in items]
        async with self._lock:
            replaced = await asyncio.to_thread(
                self.repository.replace_sdk_session_items, self.session_id, normalized,
                expected_version=expected_version, run=self._run,
            )
            if replaced:
                self._version = expected_version + 1
            return replaced

    async def pop_item(self, *, wrapper=None):  # noqa: ANN001
        self._check_wrapper(wrapper)
        async with self._lock:
            if self._version is None:
                await self._read()
            item = await asyncio.to_thread(self.repository.pop_sdk_session_item, self.session_id,
                                          run=self._run, expected_version=self._version)
            if item is not None:
                self._version += 1
            return item

    async def clear_session(self, *, wrapper=None) -> None:  # noqa: ANN001
        self._check_wrapper(wrapper)
        async with self._lock:
            if self._version is None:
                await self._read()
            record = await asyncio.to_thread(self.repository.clear_sdk_session, self.session_id,
                                            run=self._run, expected_version=self._version)
            self._version = record.version
