from __future__ import annotations

import hashlib
import json
import os
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from agents import FunctionTool
from agents.strict_schema import ensure_strict_json_schema

from agentmesh.models import new_id, now_utc
from agentmesh.runner_contracts import RunnerExecutionEventV1, RunnerToolSnapshotV1
from agentmesh.tool_runtime.guardrails import contains_credential, quarantine_unsafe_output, reject_secret_arguments

if TYPE_CHECKING:
    from agentmesh.runner_handoff import RunnerModelHandoff

_MAX_LOCAL_FILE_BYTES = 100 * 1024


def allowed_roots() -> tuple[Path, ...]:
    raw = os.getenv("AGENTMESH_RUNNER_ALLOWED_ROOTS", "")
    roots: list[Path] = []
    for item in raw.split(os.pathsep):
        if not item.strip():
            continue
        root = Path(item).expanduser().resolve()
        if root.is_dir() and root not in roots:
            roots.append(root)
    return tuple(roots)


def available_local_tool_names() -> list[str]:
    return ["local_file_read"] if allowed_roots() else []


class LocalRunnerToolRegistry:
    def __init__(self, roots: tuple[Path, ...] | None = None, *, handoff: RunnerModelHandoff | None = None):
        self.roots = roots if roots is not None else allowed_roots()
        self.handoff = handoff
        self.events: list[RunnerExecutionEventV1] = []

    @staticmethod
    def _event(event_type: str, payload: dict[str, object]) -> RunnerExecutionEventV1:
        return RunnerExecutionEventV1(
            client_event_id=new_id("runner_event"),
            event_type=event_type,
            payload=payload,
            occurred_at=now_utc(),
        )

    def _resolve_file(self, value: str) -> Path:
        requested = Path(value).expanduser()
        candidates = (
            [requested.resolve()] if requested.is_absolute() else [(root / requested).resolve() for root in self.roots]
        )
        for candidate in candidates:
            if not candidate.is_file():
                continue
            if any(candidate == root or root in candidate.parents for root in self.roots):
                return candidate
        raise PermissionError("local_file_not_allowed")

    def _read_text(self, raw_arguments: str) -> str:
        arguments = json.loads(raw_arguments)
        if not isinstance(arguments, dict) or not isinstance(arguments.get("path"), str):
            raise ValueError("local_file_path_required")
        path_hash = hashlib.sha256(arguments["path"].encode("utf-8")).hexdigest()
        self.events.append(self._event("tool_started", {"tool_name": "local_file_read", "path_hash": path_hash}))
        try:
            path = self._resolve_file(arguments["path"])
            with path.open("rb") as source:
                content = source.read(_MAX_LOCAL_FILE_BYTES + 1)
            if len(content) > _MAX_LOCAL_FILE_BYTES:
                raise ValueError("local_file_too_large")
            text = content.decode("utf-8")
            if contains_credential(text):
                raise PermissionError("local_file_credential_detected")
        except Exception as error:
            self.events.append(
                self._event(
                    "tool_failed",
                    {"tool_name": "local_file_read", "error_code": type(error).__name__},
                )
            )
            raise
        self.events.append(
            self._event(
                "tool_completed",
                {
                    "tool_name": "local_file_read",
                    "content_hash": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                },
            )
        )
        return text

    async def _invoke(self, ctx, raw_arguments: str, *, snapshot: RunnerToolSnapshotV1) -> str:  # noqa: ANN001
        if self.handoff is not None:
            await self.handoff.authorize_tool(snapshot, raw_arguments, getattr(ctx, "tool_call_id", None))
        return self._read_text(raw_arguments)

    def build(self, snapshots: list[RunnerToolSnapshotV1]) -> list[FunctionTool]:
        tools: list[FunctionTool] = []
        for snapshot in snapshots:
            if snapshot.name != "local_file_read" or snapshot.implementation_id != "runner:local_file_read":
                continue
            if not self.roots:
                continue
            tools.append(
                FunctionTool(
                    name=snapshot.name,
                    description=snapshot.description,
                    params_json_schema=ensure_strict_json_schema(snapshot.input_schema),
                    on_invoke_tool=partial(self._invoke, snapshot=snapshot),
                    strict_json_schema=True,
                    tool_input_guardrails=[reject_secret_arguments],
                    tool_output_guardrails=[quarantine_unsafe_output],
                    timeout_seconds=15,
                    timeout_behavior="error_as_result",
                )
            )
        return tools
