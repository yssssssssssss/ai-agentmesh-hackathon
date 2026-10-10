from __future__ import annotations

import asyncio

import pytest

from agentmesh.runner_contracts import RunnerToolSnapshotV1
from agentmesh.runner_tools import LocalRunnerToolRegistry


def _snapshot() -> RunnerToolSnapshotV1:
    return RunnerToolSnapshotV1(
        id="tool_local_file_read",
        name="local_file_read",
        description="read an allowed local text file",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        implementation_id="runner:local_file_read",
        implementation_version="1",
    )


def test_local_file_tool_reads_only_from_an_allowed_root(tmp_path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "notes.md").write_text("approved local content", encoding="utf-8")
    registry = LocalRunnerToolRegistry((root.resolve(),))
    tool = registry.build([_snapshot()])[0]

    output = asyncio.run(tool.on_invoke_tool(None, '{"path":"notes.md"}'))

    assert output == "approved local content"
    assert [event.event_type for event in registry.events] == ["tool_started", "tool_completed"]


def test_local_file_tool_rejects_path_escape(tmp_path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("outside", encoding="utf-8")
    registry = LocalRunnerToolRegistry((root.resolve(),))
    tool = registry.build([_snapshot()])[0]

    with pytest.raises(PermissionError, match="local_file_not_allowed"):
        asyncio.run(tool.on_invoke_tool(None, '{"path":"../secret.txt"}'))
    assert registry.events[-1].event_type == "tool_failed"


def test_local_file_tool_refuses_oversized_content(tmp_path) -> None:
    (tmp_path / "large.md").write_bytes(b"x" * (100 * 1024 + 1))
    registry = LocalRunnerToolRegistry((tmp_path.resolve(),))
    tool = registry.build([_snapshot()])[0]
    with pytest.raises(ValueError, match="local_file_too_large"):
        asyncio.run(tool.on_invoke_tool(None, '{"path":"large.md"}'))
    assert registry.events[-1].event_type == "tool_failed"
