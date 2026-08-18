from __future__ import annotations

import asyncio
import json
from typing import Any

from agentmesh.models import ChatMessage, ChatRole
from agentmesh.store import SQLiteStore


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

    def __init__(self, session_id: str, repository: SQLiteStore):
        self.session_id = session_id
        self.repository = repository

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
        if messages:
            await asyncio.to_thread(self.repository.reconcile_sdk_session_messages, self.session_id, messages)

    async def get_items(self, limit: int | None = None, *, wrapper=None) -> list[dict[str, Any]]:  # noqa: ANN001
        del wrapper
        record = await asyncio.to_thread(self.repository.get_sdk_session, self.session_id)
        items = list(record.items) if record is not None else []
        if limit is None:
            return items
        if limit <= 0:
            return []
        return items[-limit:]

    async def add_items(self, items, *, wrapper=None) -> None:  # noqa: ANN001
        del wrapper
        normalized = [_json_item(item) for item in items]
        await asyncio.to_thread(self.repository.append_sdk_session_items, self.session_id, normalized)

    async def mark_chat_messages(self, message_ids: list[str]) -> None:
        await asyncio.to_thread(self.repository.mark_sdk_session_chat_messages, self.session_id, message_ids)

    async def snapshot(self) -> tuple[list[dict[str, Any]], int]:
        record = await asyncio.to_thread(self.repository.get_sdk_session, self.session_id)
        return (list(record.items), record.version) if record is not None else ([], 0)

    async def replace_items(self, items: list[dict[str, Any]], *, expected_version: int) -> bool:
        normalized = [_json_item(item) for item in items]
        return await asyncio.to_thread(
            self.repository.replace_sdk_session_items,
            self.session_id,
            normalized,
            expected_version=expected_version,
        )

    async def pop_item(self, *, wrapper=None):  # noqa: ANN001
        del wrapper
        return await asyncio.to_thread(self.repository.pop_sdk_session_item, self.session_id)

    async def clear_session(self, *, wrapper=None) -> None:  # noqa: ANN001
        del wrapper
        await asyncio.to_thread(self.repository.clear_sdk_session, self.session_id)
