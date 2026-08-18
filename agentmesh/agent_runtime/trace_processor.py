from __future__ import annotations

import threading

from agents import TracingProcessor, set_trace_processors

from agentmesh.models import AuditEvent
from agentmesh.store import SQLiteStore

_ALLOWED_METADATA = {"run_id", "thread_id", "user_id", "workspace_id", "project_id", "skill_name"}
_trace_lock = threading.Lock()
_current_repository: SQLiteStore | None = None


class AgentMeshTraceProcessor(TracingProcessor):
    """Local metadata-only SDK trace projection. Prompt/tool payloads are never exported."""

    def __init__(self, repository: SQLiteStore):
        self.repository = repository

    def on_trace_start(self, trace) -> None:  # noqa: ANN001
        del trace

    def on_trace_end(self, trace) -> None:  # noqa: ANN001
        try:
            exported = trace.export() or {}
            raw_metadata = exported.get("metadata") if isinstance(exported, dict) else {}
            metadata = {
                str(key): value
                for key, value in (raw_metadata or {}).items()
                if key in _ALLOWED_METADATA and isinstance(value, (str, int, float, bool, type(None)))
            }
            trace_id = str(getattr(trace, "trace_id", "sdk_trace"))
            target_id = str(metadata.get("run_id") or metadata.get("thread_id") or trace_id)
            self.repository.add_audit_event(
                AuditEvent(
                    actor=str(metadata.get("user_id") or "agent_runtime"),
                    action="sdk_trace_completed",
                    target_type="agent_run",
                    target_id=target_id,
                    workspace_id=str(metadata["workspace_id"]) if metadata.get("workspace_id") else None,
                    project_id=str(metadata["project_id"]) if metadata.get("project_id") else None,
                    metadata={
                        "trace_id": trace_id,
                        "workflow_name": str(getattr(trace, "name", "Agent workflow")),
                        **metadata,
                    },
                )
            )
        except Exception:
            # Telemetry must never make an otherwise valid Agent run fail.
            return

    def on_span_start(self, span) -> None:  # noqa: ANN001
        del span

    def on_span_end(self, span) -> None:  # noqa: ANN001
        del span

    def shutdown(self) -> None:
        return

    def force_flush(self) -> None:
        return


def configure_agentmesh_tracing(repository: SQLiteStore) -> None:
    """Replace the SDK's default remote exporter with AgentMesh's local processor."""
    global _current_repository
    with _trace_lock:
        if _current_repository is repository:
            return
        set_trace_processors([AgentMeshTraceProcessor(repository)])
        _current_repository = repository
