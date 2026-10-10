from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import pytest
from agents.testing import ScriptedModel, assistant_message, function_call

import agentmesh.runner_executor as runner_executor
from agentmesh.agent_runtime.model_factory import SelectedSDKModel
from agentmesh.memory_context.request_budget import ContextRequestError
from agentmesh.models import now_utc
from agentmesh.runner_contracts import (
    RunnerExecutionEnvelopeV1,
    RunnerExecutionEnvelopeV2,
    RunnerSessionSnapshotV1,
    RunnerToolSnapshotV1,
    runner_envelope_hash,
)
from agentmesh.runner_executor import RunnerExecutionError, execute_runner_envelope, execute_standard_direct


def _envelope(
    *,
    envelope_hash: str | None = None,
    tools: list[RunnerToolSnapshotV1] | None = None,
) -> RunnerExecutionEnvelopeV1:
    now = now_utc()
    tool_snapshots = tools or []
    payload = {
        "operation_kind": "standard_direct",
        "lease_id": "lease-1",
        "lease_expires_at": now + timedelta(minutes=5),
        "run_id": "run-1",
        "operation_key": "dispatch-1",
        "dispatch_generation": 1,
        "owner_user_id": "usr-1",
        "workspace_id": "ws-1",
        "project_id": "prj-1",
        "thread_id": "thread-1",
        "task_id": None,
        "input_text": "hello",
        "history": [],
        "skill": None,
        "tools": tool_snapshots,
        "plan_id": None,
        "node_id": None,
        "node_attempt": None,
        "node_prompt": None,
        "instructions": "answer",
        "model_id": "default",
        "deadline_at": now + timedelta(minutes=5),
    }
    return RunnerExecutionEnvelopeV1(
        envelope_hash=envelope_hash or runner_envelope_hash(payload),
        **payload,
    )


def test_runner_executor_rejects_tampered_envelope_before_model_call() -> None:
    with pytest.raises(RunnerExecutionError, match="hash mismatch"):
        asyncio.run(execute_standard_direct(_envelope(envelope_hash="0" * 64)))


def test_runner_executor_uses_the_local_model(monkeypatch) -> None:
    model = ScriptedModel([[assistant_message("local runner answer")]])
    monkeypatch.setattr(
        runner_executor,
        "selected_model_from_env",
        lambda _model_id: SelectedSDKModel(
            model=model,
            requested_model="default",
            actual_model="scripted-local",
        ),
    )

    result = asyncio.run(execute_standard_direct(_envelope()))

    assert result.output_text == "local runner answer"
    assert result.requested_model == "default"
    assert result.actual_model == "scripted-local"


def test_structured_runner_compacts_large_history_and_returns_its_exact_sdk_items(monkeypatch):
    items = [{'role': 'user' if index % 2 == 0 else 'assistant',
              'content': f'history-{index}: ' + 'x' * 10000} for index in range(6)]
    base = _envelope().model_dump(exclude={'schema_version', 'envelope_hash'})
    base['session'] = RunnerSessionSnapshotV1(thread_id='thread-1', version=3, items=items)
    envelope = RunnerExecutionEnvelopeV2(envelope_hash=runner_envelope_hash(base), **base)
    model = ScriptedModel([[assistant_message('Earlier decisions and sources.')], [assistant_message('Ready.')]])
    monkeypatch.setattr(runner_executor, 'selected_model_from_env', lambda _id:
        SelectedSDKModel(model=model, requested_model='default', actual_model='scripted-local'))
    result = asyncio.run(execute_standard_direct(envelope))
    assert len(model.calls) == 2
    assert 'history-0:' in str(model.calls[0].input)
    delivered = model.calls[1].input
    assert delivered[1:3] == items[-2:]
    assert delivered[-1] == {'role': 'user', 'content': 'hello'}
    assert result.session_commit.items[:-1] == delivered
    assert result.session_commit.version == 3
    assert result.session_commit.snapshot_hash == envelope.session.content_hash
    assert model.calls[1].model_settings.max_tokens == 8192


def test_runner_rejects_an_oversized_request_before_local_model_call(monkeypatch):
    base = _envelope().model_dump(exclude={'schema_version', 'envelope_hash'})
    base['instructions'] = '平台规则' * 6000
    envelope = RunnerExecutionEnvelopeV1(envelope_hash=runner_envelope_hash(base), **base)
    model = ScriptedModel([[assistant_message('unreachable')]])
    monkeypatch.setattr(runner_executor, 'selected_model_from_env', lambda _id:
        SelectedSDKModel(model=model, requested_model='default', actual_model='scripted-local'))
    with pytest.raises(ContextRequestError, match='context_request_budget_exceeded'):
        asyncio.run(execute_standard_direct(envelope))
    assert not model.calls


def test_runner_executor_invokes_an_allowed_local_tool(tmp_path, monkeypatch) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "notes.md").write_text("local evidence", encoding="utf-8")
    monkeypatch.setenv("AGENTMESH_RUNNER_ALLOWED_ROOTS", str(root))
    model = ScriptedModel(
        [
            [function_call("local_file_read", {"path": "notes.md"}, call_id="local-read-1")],
            [assistant_message("Used local evidence")],
        ]
    )
    monkeypatch.setattr(
        runner_executor,
        "selected_model_from_env",
        lambda _model_id: SelectedSDKModel(
            model=model,
            requested_model="default",
            actual_model="scripted-local",
        ),
    )
    tool = RunnerToolSnapshotV1(
        id="tool_local_file_read",
        name="local_file_read",
        description="read a local file",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        implementation_id="runner:local_file_read",
        implementation_version="1",
    )

    result = asyncio.run(execute_standard_direct(_envelope(tools=[tool])))

    assert result.output_text == "Used local evidence"
    assert [event.event_type for event in result.tool_events] == ["tool_started", "tool_completed"]


def test_runner_executor_returns_structured_standard_node_result(monkeypatch) -> None:
    payload = {
        "node_id": "node_1",
        "skill_id": "skill_test",
        "summary": "Completed",
        "deliverable_markdown": "# Deliverable",
    }
    model = ScriptedModel([[assistant_message(json.dumps(payload))]])
    monkeypatch.setattr(
        runner_executor,
        "selected_model_from_env",
        lambda _model_id: SelectedSDKModel(
            model=model,
            requested_model="default",
            actual_model="scripted-local",
        ),
    )
    direct = _envelope()
    node_payload = direct.model_dump(
        mode="python",
        exclude={"schema_version", "envelope_hash"},
    )
    node_payload.update(
        {
            "operation_kind": "standard_skill_node",
            "plan_id": "plan_1",
            "node_id": "node_1",
            "node_attempt": 1,
            "node_prompt": {"goal": "Build deliverable"},
            "skill": {
                "id": "skill_test",
                "name": "test-skill",
                "title": "Test Skill",
                "version": "1",
                "content_hash": "skill-hash",
            },
        }
    )
    envelope = RunnerExecutionEnvelopeV1(
        envelope_hash=runner_envelope_hash(node_payload),
        **node_payload,
    )

    result = asyncio.run(execute_runner_envelope(envelope))

    assert result.result_payload is not None
    assert result.result_payload["summary"] == "Completed"
    assert result.result_payload["node_id"] == "node_1"
