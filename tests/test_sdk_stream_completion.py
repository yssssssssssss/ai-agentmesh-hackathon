from __future__ import annotations

import asyncio

import pytest
from agents.testing import ModelStep, ScriptedModel, function_call
from openai.types.responses import ResponseTextDeltaEvent

from agentmesh.agent_runtime.model_retry import AtomicStreamModel
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.models import (
    AgentRun,
    AgentRunStatus,
    AgentToolGrant,
    ChatThread,
    RuntimeToolCallClaimV1,
    SkillIntent,
    SkillPlan,
    SkillPlanNode,
    SkillPlanNodeStatus,
    SkillPlanStatus,
)
from agentmesh.runtime_capacity import RuntimeCapacityController
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore
from agentmesh.tools import ensure_tool_seed_data


@pytest.fixture
def stream(tmp_path, monkeypatch):
    repository = SQLiteStore(tmp_path / "sdk-stream-completion.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    ensure_tool_seed_data(repository, granted_by="system")
    thread = repository.add_chat_thread(
        ChatThread(
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            title="Current SDK stream",
        )
    )
    monkeypatch.setenv("AGENTMESH_MEMORY_CONTEXT", "off")
    yield repository, thread
    repository.close()


@pytest.mark.parametrize("mode", ["direct", "resume"])
@pytest.mark.parametrize("atomic", [False, True])
@pytest.mark.parametrize("partial", [False, True])
def test_cancelled_sdk_producer_cannot_complete_a_run(stream, mode, atomic, partial):
    repository, thread = stream

    def cancel_model(_call):
        raise asyncio.CancelledError

    async def cancel_stream(_call):
        yield ResponseTextDeltaEvent(
            type="response.output_text.delta",
            content_index=0,
            delta="Uncommitted model text",
            item_id="partial_output",
            output_index=0,
            sequence_number=1,
            logprobs=[],
        )
        raise asyncio.CancelledError

    step = ModelStep(stream_events=cancel_stream) if partial else ModelStep(responder=cancel_model)
    steps = [step]
    if mode == "resume":
        repository.save_agent_tool_grant(
            AgentToolGrant(
                id="grant_cancel_web",
                agent_id=USER.personal_agent_id,
                tool_id="tool_web_research",
                granted_by="test",
            )
        )
        steps.insert(0, [function_call("web_research", {"query": "Approval"}, call_id="cancel_approval")])
    model = ScriptedModel(steps)
    runtime = AgentRuntimeService(repository, model=AtomicStreamModel(model) if atomic else model, enabled=True)
    paused = (
        runtime.run_sync(content="Request approval", user=USER, thread_id=thread.id, history=[])
        if mode == "resume"
        else None
    )
    with pytest.raises(asyncio.CancelledError):
        if paused is not None:
            runtime.resume_sync(paused.run_id, user=USER, decisions={"cancel_approval": False})
        else:
            runtime.run_sync(content="Keep cancellation visible", user=USER, thread_id=thread.id, history=[])
    (current,) = repository.list_agent_runs(USER.id)
    assert current.status is AgentRunStatus.CANCELLED
    assert current.output_text is None and current.paused_state is None
    assert len(model.calls) == (2 if mode == "resume" else 1)
    if mode == "resume":
        assert repository.get_inbox_item(f"inbox_tool_approval_{current.id}").status == "resolved"
    events = repository.list_agent_run_events(current.id)
    assert sum(event.event_type == "run_cancelled" for event in events) == 1
    assert not any(event.event_type in {"run_completed", "run_output_projected"} for event in events)


@pytest.mark.parametrize("replace_writer", [False, True])
def test_approved_runtime_plan_propagates_sdk_producer_cancellation(
    stream, monkeypatch, configure_pilot_wiki, tmp_path, replace_writer
):
    repository, thread = stream
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "execute")
    configure_pilot_wiki(tmp_path / "wiki")
    catalog = SkillCatalogService(repository)
    catalog.reload()
    skill = catalog.get_by_name("generate-research-plan", USER.personal_agent_id)
    assert skill is not None
    run = repository.save_agent_run(
        AgentRun(
            thread_id=thread.id,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="Plan current research",
            status=AgentRunStatus.RUNNING,
        )
    )
    node = SkillPlanNode(
        id="cancel_node",
        skill_id=skill.id,
        skill_version=skill.version,
        skill_content_hash=skill.content_hash,
        reason="Plan research",
        output_contract=["research_plan"],
    )
    plan = repository.save_skill_plan(
        SkillPlan(
            run_id=run.id,
            status=SkillPlanStatus.APPROVED,
            intent=SkillIntent(goal=run.input_text),
            candidate_skill_ids=[skill.id],
            nodes=[node],
            output_contract=["research_plan"],
        )
    )
    repository.save_agent_run(run.model_copy(update={"plan_id": plan.id}))
    expected = {}

    def cancel_model(_call):
        if replace_writer:
            current = repository.get_agent_run(run.id)
            expected["run"] = repository.save_agent_run(current.model_copy(update={"writer_generation_epoch": 2}))
            expected["plan"] = repository.get_skill_plan(plan.id)
        raise asyncio.CancelledError

    model = ScriptedModel([ModelStep(responder=cancel_model)])
    capacity = RuntimeCapacityController()
    runtime = AgentRuntimeService(repository, model=model, skill_catalog=catalog, capacity=capacity, enabled=True)

    async def scenario():
        await runtime.start_approved_skill_plan(plan.id, user=USER)
        async with asyncio.timeout(10):
            while capacity.snapshot()["active_runs"]:
                await asyncio.sleep(0.005)

    asyncio.run(scenario())
    assert len(model.calls) == 1
    current = repository.get_agent_run(run.id)
    current_plan = repository.get_skill_plan(plan.id)
    if replace_writer:
        assert current == expected["run"] and current_plan == expected["plan"]
    else:
        assert current.status is AgentRunStatus.CANCELLED
        assert current_plan.status is SkillPlanStatus.CANCELLED
        assert current_plan.nodes[0].status is SkillPlanNodeStatus.CANCELLED
    assert current.output_text is None and current_plan.synthesis is None
    assert capacity.snapshot()["active_nodes"] == capacity.snapshot()["active_llm_calls"] == 0
    assert not any(
        event.event_type in {"run_completed", "synthesis_completed", "run_output_projected"}
        for event in repository.list_agent_run_events(run.id)
    )


@pytest.mark.parametrize("mode", ["direct", "resume"])
def test_cancelled_producer_preserves_unknown_external_write_outcome(stream, mode):
    repository, thread = stream

    def cancel_after_write_claim(_call):
        (run,) = repository.list_agent_runs(USER.id)
        repository.claim_runtime_tool_call(
            RuntimeToolCallClaimV1(
                call_id="pending_write",
                run_id=run.id,
                tool_definition_id="tool_write",
                tool_name="write_tool",
                implementation_id="provider.write",
                implementation_version="1",
                side_effect="external",
                operation_identity="a" * 64,
            )
        )
        raise asyncio.CancelledError

    steps = [ModelStep(responder=cancel_after_write_claim)]
    if mode == "resume":
        repository.save_agent_tool_grant(
            AgentToolGrant(
                id="grant_cancel_web",
                agent_id=USER.personal_agent_id,
                tool_id="tool_web_research",
                granted_by="test",
            )
        )
        steps.insert(0, [function_call("web_research", {"query": "Approval"}, call_id="cancel_approval")])
    model = ScriptedModel(steps)
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    paused = (
        runtime.run_sync(content="Request approval", user=USER, thread_id=thread.id, history=[])
        if mode == "resume"
        else None
    )
    with pytest.raises(asyncio.CancelledError):
        if paused is not None:
            runtime.resume_sync(paused.run_id, user=USER, decisions={"cancel_approval": False})
        else:
            runtime.run_sync(content="Continue an interrupted operation", user=USER, thread_id=thread.id, history=[])
    (current,) = repository.list_agent_runs(USER.id)
    assert current.status is AgentRunStatus.FAILED and current.error_code == "external_outcome_unknown"
    assert current.output_text is None and current.paused_state is None
    claims, outcomes = repository.list_runtime_tool_call_history(current.id)
    assert len(claims) == 1 and not outcomes
    assert len(model.calls) == (2 if mode == "resume" else 1)
    assert not any(
        event.event_type in {"run_completed", "run_cancelled", "run_output_projected"}
        for event in repository.list_agent_run_events(current.id)
    )
