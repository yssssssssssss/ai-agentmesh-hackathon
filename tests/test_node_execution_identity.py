from __future__ import annotations

import asyncio
import json
from contextlib import suppress

import pytest
from agents import RunState
from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.models import (
    AgentRun,
    AgentRunStatus,
    AgentToolGrant,
    ChatThread,
    RuntimeToolCallClaimV1,
    SkillIntent,
    SkillNodeResult,
    SkillPlan,
    SkillPlanNode,
    SkillPlanNodeStatus,
    SkillPlanStatus,
    SkillSynthesisResult,
)
from agentmesh.runtime_capacity import RuntimeCapacityController
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.skill_runtime.executor import BoundedDAGExecutor, NodeExecutionOutcome, PlanExecutionConflict
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore
from agentmesh.tools import ensure_tool_seed_data


@pytest.fixture
def node_execution(tmp_path, monkeypatch, configure_pilot_wiki, request):
    monkeypatch.setenv("AGENTMESH_MEMORY_CONTEXT", "off")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "execute")
    configure_pilot_wiki(tmp_path / "wiki")
    repository = SQLiteStore(tmp_path / "node-execution.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    ensure_tool_seed_data(repository, granted_by="system")
    thread = repository.add_chat_thread(
        ChatThread(
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            title="Current node execution",
        )
    )
    catalog = SkillCatalogService(repository)
    catalog.reload()
    skill = catalog.get_by_name("prd-feasibility", USER.personal_agent_id)
    assert skill is not None
    profile = repository.get_skill_capability_profile(skill.id)
    assert profile is not None
    repository.save_skill_capability_profile(profile.model_copy(update={"required_capabilities": ["research.request"]}))
    repository.save_agent_tool_grant(
        AgentToolGrant(
            id="grant_node_web",
            agent_id=USER.personal_agent_id,
            tool_id="tool_web_research",
            granted_by="test",
        )
    )
    run = repository.save_agent_run(
        AgentRun(
            thread_id=thread.id,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="Review current requirements",
            status=AgentRunStatus.RUNNING,
            orchestration_mode="execute",
            execution_location=getattr(request, "param", "server"),
        )
    )
    node = SkillPlanNode(
        id="identity_node",
        skill_id=skill.id,
        skill_version=skill.version,
        skill_content_hash=skill.content_hash,
        reason="Review current requirements",
        output_contract=["feasibility_review"],
        side_effect=profile.side_effect,
    )
    plan = repository.save_skill_plan(
        SkillPlan(
            run_id=run.id,
            status=SkillPlanStatus.APPROVED,
            intent=SkillIntent(goal=run.input_text),
            candidate_skill_ids=[skill.id],
            nodes=[node],
            output_contract=["feasibility_review"],
        )
    )
    repository.save_agent_run(run.model_copy(update={"plan_id": plan.id}))
    yield repository, catalog, plan, run
    repository.close()


def _request_node_approval(repository, catalog, plan, steps):
    capacity = RuntimeCapacityController()
    model = ScriptedModel(
        [[function_call("web_research", {"query": "批量抓取 current issues"}, call_id="identity_approval")], *steps]
    )
    runtime = AgentRuntimeService(repository, model=model, skill_catalog=catalog, capacity=capacity, enabled=True)
    _start_plan(runtime, plan, capacity)
    current = repository.get_agent_run(plan.run_id)
    assert current is not None and current.status is AgentRunStatus.WAITING_APPROVAL
    assert repository.get_skill_plan(plan.id).nodes[0].status is SkillPlanNodeStatus.WAITING_TOOL_APPROVAL
    return runtime, model, capacity


def _start_plan(runtime, plan, capacity):
    async def scenario():
        await runtime.start_approved_skill_plan(plan.id, user=USER)
        async with asyncio.timeout(10):
            while capacity.snapshot()["active_runs"]:
                await asyncio.sleep(0.005)

    asyncio.run(scenario())


def _replace_execution(repository, plan, run, replacement):
    current = repository.get_agent_run(run.id)
    current_plan = repository.get_skill_plan(plan.id)
    if replacement in {"writer", "runner", "paused_state"}:
        update = {"writer_generation_epoch": 2}
        if replacement == "runner":
            update = {"runner_id": "new_runner"}
        elif replacement == "paused_state":
            update = {"paused_state": {**current.paused_state, "changed_checkpoint": True}}
        repository.save_agent_run(current.model_copy(update=update))
    elif replacement == "plan_version":
        repository.save_skill_plan(current_plan.model_copy(update={"version": current_plan.version + 1}))
    elif replacement == "plan_input":
        repository.save_skill_plan(current_plan.model_copy(update={
            "intent": current_plan.intent.model_copy(update={"goal": "New goal"}),
        }))
    else:
        update = {"attempt": current_plan.nodes[0].attempt + 1}
        if replacement == "node_input":
            update = {"input_bindings": ["new.requirements"]}
        repository.update_skill_plan_node(plan.id, current_plan.nodes[0].model_copy(update=update))
    return {
        "run": repository.get_agent_run(run.id),
        "plan": repository.get_skill_plan(plan.id),
        "inbox": repository.get_inbox_item(f"inbox_tool_approval_{run.id}"),
    }


@pytest.mark.parametrize("failure", ["error", "cancel"])
@pytest.mark.parametrize("replacement", ["writer", "runner", "plan_version", "attempt", "node_input", "plan_input"])
def test_old_node_resume_failure_cannot_terminate_replacement_writer(node_execution, failure, replacement):
    repository, catalog, plan, run = node_execution
    expected = {}

    def replace_then_fail(_call):
        expected.update(_replace_execution(repository, plan, run, replacement))
        if failure == "cancel":
            raise asyncio.CancelledError
        raise RuntimeError("controlled_node_failure")

    runtime, model, capacity = _request_node_approval(
        repository, catalog, plan, [ModelStep(responder=replace_then_fail)]
    )
    with pytest.raises(asyncio.CancelledError if failure == "cancel" else RuntimeError):
        runtime.resume_sync(run.id, user=USER, decisions={"identity_approval": False})
    assert repository.get_agent_run(run.id) == expected["run"]
    assert repository.get_skill_plan(plan.id) == expected["plan"]
    assert repository.get_inbox_item(f"inbox_tool_approval_{run.id}") == expected["inbox"]
    assert repository.list_skill_node_results(plan.id) == []
    assert capacity.snapshot()["active_runs"] == capacity.snapshot()["active_llm_calls"] == 0
    assert len(model.calls) == 2


@pytest.mark.parametrize("replacement", ["writer", "runner", "plan_version", "attempt", "node_input", "plan_input"])
def test_old_node_result_cannot_enter_replacement_execution(node_execution, replacement):
    repository, catalog, plan, run = node_execution
    expected = {}

    def replace_then_return(_call):
        expected.update(_replace_execution(repository, plan, run, replacement))
        return [assistant_message(json.dumps({
            "node_id": plan.nodes[0].id,
            "skill_id": plan.nodes[0].skill_id,
            "summary": "Old uncommitted review",
        }))]

    runtime, model, capacity = _request_node_approval(
        repository, catalog, plan, [ModelStep(responder=replace_then_return)]
    )
    with pytest.raises(RuntimeError):
        runtime.resume_sync(run.id, user=USER, decisions={"identity_approval": False})
    assert repository.get_agent_run(run.id) == expected["run"]
    assert repository.get_skill_plan(plan.id) == expected["plan"]
    assert repository.list_skill_node_results(plan.id) == []
    assert capacity.snapshot()["active_nodes"] == capacity.snapshot()["active_llm_calls"] == 0
    assert len(model.calls) == 2


@pytest.mark.parametrize("replacement", ["writer", "runner", "plan_version", "attempt", "node_input", "plan_input"])
def test_old_node_pause_cannot_interrupt_replacement_execution(node_execution, replacement):
    repository, catalog, plan, run = node_execution
    expected = {}

    def replace_then_pause(_call):
        expected.update(_replace_execution(repository, plan, run, replacement))
        return [function_call("web_research", {"query": "批量抓取 current issues"}, call_id="stale_approval")]

    model = ScriptedModel([ModelStep(responder=replace_then_pause)])
    capacity = RuntimeCapacityController()
    runtime = AgentRuntimeService(repository, model=model, skill_catalog=catalog, capacity=capacity, enabled=True)
    _start_plan(runtime, plan, capacity)
    assert repository.get_agent_run(run.id) == expected["run"]
    assert repository.get_skill_plan(plan.id) == expected["plan"]
    assert repository.get_inbox_item(f"inbox_tool_approval_{run.id}") is None
    assert repository.list_skill_node_results(plan.id) == []
    assert capacity.snapshot()["active_nodes"] == capacity.snapshot()["active_llm_calls"] == 0
    assert len(model.calls) == 1


@pytest.mark.parametrize(
    "replacement", ["writer", "runner", "plan_version", "attempt", "node_input", "plan_input", "paused_state"],
)
def test_restored_approval_cannot_claim_replacement_execution(node_execution, monkeypatch, replacement):
    repository, catalog, plan, run = node_execution
    expected = {}

    def unexpected_model(_call):
        raise RuntimeError("approval_should_not_send")

    runtime, model, capacity = _request_node_approval(
        repository, catalog, plan, [ModelStep(responder=unexpected_model)]
    )
    restore = RunState.from_json

    async def restore_then_replace(agent, state_json, **kwargs):
        state = await restore(agent, state_json, **kwargs)
        expected.update(_replace_execution(repository, plan, run, replacement))
        return state

    monkeypatch.setattr(RunState, "from_json", staticmethod(restore_then_replace))
    with pytest.raises(RuntimeError):
        runtime.resume_sync(run.id, user=USER, decisions={"identity_approval": False})
    assert repository.get_agent_run(run.id) == expected["run"]
    assert repository.get_skill_plan(plan.id) == expected["plan"]
    assert repository.get_inbox_item(f"inbox_tool_approval_{run.id}") == expected["inbox"]
    assert len(model.calls) == 1
    assert capacity.snapshot()["active_runs"] == capacity.snapshot()["active_llm_calls"] == 0


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("replacement", ["writer", "runner", "plan_version", "node_input", "plan_input"])
def test_stale_executor_cannot_claim_or_resume_replacement_execution(node_execution, resume, replacement):
    repository, _catalog, plan, run = node_execution
    run = repository.get_agent_run(run.id)
    if resume:
        plan = repository.claim_skill_plan_for_execution(plan.id, run.id)
        assert plan is not None
    expected = _replace_execution(repository, plan, run, replacement)
    node_calls = []

    async def node_runner(_plan, node, _results):
        node_calls.append(node.id)
        return NodeExecutionOutcome(result=SkillNodeResult(
            node_id=node.id, skill_id=node.skill_id, attempt=node.attempt, summary="Stale execution",
        ))

    async def synthesis_runner(_plan, _results):
        return SkillSynthesisResult(summary="Stale synthesis"), False

    with pytest.raises(PlanExecutionConflict):
        asyncio.run(BoundedDAGExecutor(
            repository, node_runner=node_runner, synthesis_runner=synthesis_runner,
        ).run(plan, run, resume=resume))
    assert repository.get_agent_run(run.id) == expected["run"]
    assert repository.get_skill_plan(plan.id) == expected["plan"]
    assert repository.list_skill_node_results(plan.id) == []
    assert not node_calls


@pytest.mark.parametrize("replacement", ["writer", "runner", "plan_version", "attempt", "node_input", "plan_input"])
def test_queued_node_cannot_claim_replacement_execution(node_execution, replacement):
    repository, _catalog, plan, run = node_execution
    run = repository.get_agent_run(run.id)
    capacity = RuntimeCapacityController(node_limit=1)
    expected = {}
    node_calls = []

    async def node_runner(_plan, node, _results):
        node_calls.append(node.id)
        return NodeExecutionOutcome(result=SkillNodeResult(
            node_id=node.id, skill_id=node.skill_id, attempt=node.attempt, summary="Queued old result",
        ))

    async def synthesis_runner(_plan, _results):
        return SkillSynthesisResult(summary="Queued synthesis"), False

    async def scenario():
        async with capacity.node_slot():
            task = asyncio.create_task(BoundedDAGExecutor(
                repository, node_runner=node_runner, synthesis_runner=synthesis_runner, capacity=capacity,
            ).run(plan, run))
            async with asyncio.timeout(5):
                while repository.get_skill_plan(plan.id).nodes[0].status is not SkillPlanNodeStatus.READY:
                    await asyncio.sleep(0.005)
            expected.update(_replace_execution(repository, plan, run, replacement))
        with pytest.raises(RuntimeError):
            await task

    asyncio.run(scenario())
    assert repository.get_agent_run(run.id) == expected["run"]
    assert repository.get_skill_plan(plan.id) == expected["plan"]
    assert repository.list_skill_node_results(plan.id) == []
    assert not node_calls
    assert capacity.snapshot()["active_nodes"] == 0


@pytest.mark.parametrize("failure", ["error", "cancel"])
def test_node_resume_preserves_unknown_external_write_outcome(node_execution, failure):
    repository, catalog, plan, run = node_execution

    def interrupt_write(_call):
        repository.claim_runtime_tool_call(RuntimeToolCallClaimV1(
            call_id="unknown_node_write", run_id=run.id, plan_id=plan.id, node_id=plan.nodes[0].id,
            tool_definition_id="controlled_write", tool_name="controlled_write",
            implementation_id="controlled.write", implementation_version="1", side_effect="external",
            operation_identity="b" * 64,
        ))
        if failure == "cancel":
            raise asyncio.CancelledError
        raise RuntimeError("controlled_write_interrupted")

    runtime, model, capacity = _request_node_approval(
        repository, catalog, plan, [ModelStep(responder=interrupt_write)]
    )
    with pytest.raises(asyncio.CancelledError if failure == "cancel" else RuntimeError):
        runtime.resume_sync(run.id, user=USER, decisions={"identity_approval": False})
    current = repository.get_agent_run(run.id)
    assert current.status is AgentRunStatus.FAILED and current.error_code == "external_outcome_unknown"
    assert current.paused_state is None and current.output_text is None
    assert repository.get_skill_plan(plan.id).status is SkillPlanStatus.FAILED
    assert repository.get_inbox_item(f"inbox_tool_approval_{run.id}").status == "resolved"
    claims, outcomes = repository.list_runtime_tool_call_history(run.id)
    assert len(claims) == 1 and all(outcome.outcome == "outcome_unknown" for outcome in outcomes)
    assert repository.list_skill_node_results(plan.id) == []
    assert len(model.calls) == 2
    assert capacity.snapshot()["active_runs"] == capacity.snapshot()["active_llm_calls"] == 0


def test_committed_node_handoff_cannot_adopt_a_new_writer(node_execution, monkeypatch):
    repository, catalog, plan, run = node_execution
    expected = {}

    def unexpected_synthesis(_call):
        raise RuntimeError("stale_synthesis_should_not_send")

    runtime, model, capacity = _request_node_approval(repository, catalog, plan, [
        [assistant_message(json.dumps({
            "node_id": plan.nodes[0].id, "skill_id": plan.nodes[0].skill_id, "summary": "Committed review",
        }))],
        ModelStep(responder=unexpected_synthesis),
    ])
    transition = repository.transition_skill_plan_node

    def replace_after_commit(**kwargs):
        result = transition(**kwargs)
        if result is not None and kwargs["event_type"] == "node_completed":
            expected.update(_replace_execution(repository, plan, run, "writer"))
        return result

    monkeypatch.setattr(repository, "transition_skill_plan_node", replace_after_commit)
    with suppress(RuntimeError):
        runtime.resume_sync(run.id, user=USER, decisions={"identity_approval": False})
    assert repository.get_agent_run(run.id) == expected["run"]
    assert repository.get_skill_plan(plan.id) == expected["plan"]
    assert len(repository.list_skill_node_results(plan.id)) == 1
    assert len(model.calls) == 2
    assert capacity.snapshot()["active_runs"] == capacity.snapshot()["active_llm_calls"] == 0


def test_stale_terminal_write_cannot_terminate_an_active_new_attempt(node_execution):
    repository, _catalog, plan, run = node_execution
    assert repository.claim_skill_plan_for_execution(plan.id, run.id) is not None
    ready = plan.nodes[0].model_copy(update={"status": SkillPlanNodeStatus.READY})
    assert repository.transition_skill_plan_node(
        plan_id=plan.id, run_id=run.id, node=ready,
        expected_statuses={SkillPlanNodeStatus.PENDING}, event_type="node_ready", event_payload={},
    ) is not None
    first = repository.claim_skill_plan_node(plan.id, ready.id)
    assert first is not None
    stale_plan = repository.get_skill_plan(plan.id)
    stale_run = repository.get_agent_run(run.id)
    assert repository.transition_skill_plan_node(
        plan_id=plan.id, run_id=run.id, node=first.model_copy(update={"status": SkillPlanNodeStatus.READY}),
        expected_statuses={SkillPlanNodeStatus.RUNNING}, event_type="node_retry_scheduled", event_payload={},
    ) is not None
    second = repository.claim_skill_plan_node(plan.id, ready.id)
    assert second is not None and second.attempt == 2
    current_plan = repository.get_skill_plan(plan.id)
    current_run = repository.get_agent_run(run.id)
    stale_plan.status = SkillPlanStatus.FAILED
    stale_plan.nodes[0].status = SkillPlanNodeStatus.FAILED
    stale_run.status = AgentRunStatus.FAILED
    assert repository.finish_skill_plan_and_run(
        plan=stale_plan, run=stale_run, expected_plan_statuses={SkillPlanStatus.RUNNING},
        expected_run_statuses={AgentRunStatus.RUNNING}, events=[("run_failed", {})],
    ) is None
    assert repository.get_agent_run(run.id) == current_run
    assert repository.get_skill_plan(plan.id) == current_plan


@pytest.mark.parametrize("replacement", ["writer", "plan_input"])
@pytest.mark.parametrize("node_execution", ["runner"], indirect=True)
def test_runner_node_result_still_fences_controller_identity(node_execution, replacement):
    repository, _catalog, plan, run = node_execution
    run = repository.get_agent_run(run.id)
    expected = {}

    async def node_runner(_plan, node, _results):
        expected.update(_replace_execution(repository, plan, run, replacement))
        return NodeExecutionOutcome(result=SkillNodeResult(
            node_id=node.id, skill_id=node.skill_id, attempt=node.attempt, summary="Old remote result",
        ))

    async def synthesis_runner(_plan, _results):
        return SkillSynthesisResult(summary="Remote synthesis"), False

    with pytest.raises(RuntimeError):
        asyncio.run(BoundedDAGExecutor(
            repository, node_runner=node_runner, synthesis_runner=synthesis_runner,
        ).run(plan, run))
    assert repository.get_agent_run(run.id) == expected["run"]
    assert repository.get_skill_plan(plan.id) == expected["plan"]
    assert repository.list_skill_node_results(plan.id) == []
