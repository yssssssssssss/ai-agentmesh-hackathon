"""A private working copy; the control plane owns the durable Session and CAS."""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime

from agents.exceptions import AgentsException
from agents.models.chatcmpl_converter import Converter

from agentmesh.memory_context.request_budget import ContextRequestError
from agentmesh.models import now_utc
from agentmesh.runner_contracts import RunnerSessionCommitV1, RunnerSessionSnapshotV1
from agentmesh.tool_runtime.guardrails import contains_credential


def validate_runner_session_items(items: list[dict]) -> None:
    calls: set[str] = set()
    outputs: set[str] = set()
    for item in items:
        if item.get('role') not in (None, 'user', 'assistant', 'tool'):
            raise ValueError('runner_session_role_invalid')
        tool_calls = item.get('tool_calls') or []
        if not isinstance(tool_calls, list):
            raise ValueError('runner_session_call_invalid')
        for call in tool_calls:
            if not isinstance(call, dict):
                raise ValueError('runner_session_call_invalid')
            call_id = call.get('id')
            if not isinstance(call_id, str) or not call_id or call_id in calls:
                raise ValueError('runner_session_call_invalid')
            calls.add(call_id)
        if item.get('type') == 'function_call':
            call_id = item.get('call_id')
            if not isinstance(call_id, str) or not call_id or call_id in calls:
                raise ValueError('runner_session_call_invalid')
            calls.add(call_id)
        if item.get('type') == 'function_call_output' or item.get('role') == 'tool':
            call_id = item.get('call_id') or item.get('tool_call_id')
            if not isinstance(call_id, str) or call_id not in calls or call_id in outputs:
                raise ValueError('runner_session_output_invalid')
            outputs.add(call_id)
    if calls != outputs or contains_credential(json.dumps(items, ensure_ascii=False)):
        raise ValueError('runner_session_items_invalid')
    try:
        Converter.items_to_messages(items)
    except (AgentsException, ValueError, KeyError, TypeError) as error:
        raise ValueError('runner_session_items_invalid') from error


class RunnerSession:
    def __init__(self, snapshot: RunnerSessionSnapshotV1, deadline_at: datetime):
        self._snapshot = snapshot
        self._version = snapshot.version
        self._items = deepcopy(snapshot.items)
        self._deadline_at = deadline_at

    async def snapshot(self) -> tuple[list[dict], int]:
        return deepcopy(self._items), self._version

    def validate_handoff(self, expected_version: int) -> None:
        if expected_version != self._version:
            raise ContextRequestError('runner_session_version_changed')
        if self._deadline_at <= now_utc():
            raise ContextRequestError('runner_session_deadline_exceeded')

    def remaining_seconds(self, maximum: float) -> float:
        return min(maximum, max(0.0, (self._deadline_at - now_utc()).total_seconds()))

    async def replace_items(self, items: list[dict], *, expected_version: int) -> bool:
        self.validate_handoff(expected_version)
        self._items = deepcopy(items)
        self._version += 1
        return True

    def commit(self, items: list[dict]) -> RunnerSessionCommitV1:
        return RunnerSessionCommitV1(thread_id=self._snapshot.thread_id, version=self._snapshot.version,
            snapshot_hash=self._snapshot.content_hash, items=items)
