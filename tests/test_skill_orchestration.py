from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import timedelta

import httpx
import pytest
from agents import (
    Agent,
    ModelRetryBackoffSettings,
    ModelRetrySettings,
    ModelSettings,
    function_tool,
    retry_policies,
)
from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call
from openai.types.responses import ResponseTextDeltaEvent

from agentmesh.agent_runtime.model_retry import (
    AtomicStreamModel,
    ModelStreamRetryExhausted,
    retry_transient_atomic_stream,
)
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    AgentToolGrant,
    ChatThread,
    InboxItem,
    Scope,
    SkillCapabilityProfile,
    SkillCapabilityType,
    SkillDefinition,
    SkillIntent,
    SkillLifecycleStage,
    SkillNodeResult,
    SkillPlan,
    SkillPlanNode,
    SkillPlanNodeStatus,
    SkillPlanStatus,
    SkillResultSource,
    SkillSideEffect,
    SkillSourceScope,
    SkillSynthesisResult,
    Source,
    now_utc,
)
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.skill_runtime.executor import (
    BoundedDAGExecutor,
    NodeExecutionOutcome,
    NodePause,
    PlanExecutionConflict,
    PlanExecutionOutcome,
    StandardPlanFinalizer,
)
from agentmesh.skill_runtime.resources import build_skill_resource_manifest_snapshot
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore
from agentmesh.tool_runtime.factory import AgentMeshToolFactory
from agentmesh.tools import ensure_tool_seed_data


def _node(
    node_id: str,
    *,
    required: bool = True,
    depends_on: list[str] | None = None,
    output_contract: list[str] | None = None,
    side_effect: SkillSideEffect = SkillSideEffect.READ,
) -> SkillPlanNode:
    return SkillPlanNode(
        id=node_id,
        skill_id=f"skill_{node_id}",
        skill_version="1",
        skill_content_hash=f"hash_{node_id}",
        reason=f"execute {node_id}",
        required=required,
        depends_on=depends_on or [],
        input_bindings=["user.request"],
        output_contract=output_contract or [f"output_{node_id}"],
        side_effect=side_effect,
    )


def _persist_plan(
    repository: SQLiteStore,
    nodes: list[SkillPlanNode],
    *,
    output_contract: list[str],
    suffix: str,
) -> tuple[SkillPlan, AgentRun]:
    run = repository.save_agent_run(
        AgentRun(
            id=f"run_{suffix}",
            thread_id=f"thread_{suffix}",
            user_id="user",
            workspace_id="workspace",
            project_id="project",
            input_text="execute the plan",
            status=AgentRunStatus.RUNNING,
            deadline_at=now_utc() + timedelta(seconds=300),
        )
    )
    plan = repository.save_skill_plan(
        SkillPlan(
            id=f"plan_{suffix}",
            run_id=run.id,
            status=SkillPlanStatus.APPROVED,
            intent=SkillIntent(goal="execute the plan"),
            candidate_skill_ids=[node.skill_id for node in nodes],
            output_contract=output_contract,
            nodes=nodes,
        )
    )
    run.plan_id = plan.id
    repository.save_agent_run(run)
    return plan, run


def _result(node: SkillPlanNode) -> SkillNodeResult:
    return SkillNodeResult(
        id=f"result_{node.id}_{node.attempt}",
        node_id=node.id,
        skill_id=node.skill_id,
        summary=f"completed {node.id}",
        attempt=node.attempt,
    )


def test_deepsearch_node_security_uses_frozen_resources_and_rejects_drift(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-resource-drift.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    thread = repository.add_chat_thread(
        ChatThread(
            id="thread_deepsearch_resource_drift",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="DeepSearch resource drift",
        )
    )
    skill_root = tmp_path / "competitive-analysis"
    skill_root.mkdir()
    skill_path = skill_root / "SKILL.md"
    skill_path.write_text("skill", encoding="utf-8")
    resource_path = skill_root / "guide.md"
    resource_path.write_text("approved", encoding="utf-8")
    skill = repository.save_skill_definition(
        SkillDefinition(
            id="skill_deepsearch_resource_drift",
            name="competitive-analysis",
            title="Competitive analysis",
            description="Analyze competitors",
            instructions="Read `guide.md`.",
            source_path=str(skill_path),
            source_scope=SkillSourceScope.BUILTIN,
            content_hash="a" * 64,
        ),
        defer_vector=True,
    )
    profile = repository.save_skill_capability_profile(
        SkillCapabilityProfile(
            id=skill.id,
            skill_id=skill.id,
            skill_name=skill.name,
            skill_version=skill.version,
            skill_content_hash=skill.content_hash,
            profile_version="1",
            profile_content_hash="b" * 64,
            primary_stage=SkillLifecycleStage.PRE_DESIGN,
            capability_type=SkillCapabilityType.RESEARCH,
        ),
        defer_vector=True,
    )
    plan_id = "plan_deepsearch_resource_drift"
    persisted_run = repository.save_agent_run(
        AgentRun(
            id="run_deepsearch_resource_drift",
            thread_id=thread.id,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="analyze competitors",
            status=AgentRunStatus.RUNNING,
            plan_id=plan_id,
        )
    )
    run = persisted_run.model_copy(update={"planning_mode": AgentPlanningMode.DEEPSEARCH})
    resource_manifest = build_skill_resource_manifest_snapshot(skill, profile)
    node = SkillPlanNode(
        id="node_deepsearch_resource_drift",
        skill_id=skill.id,
        skill_version=skill.version,
        skill_content_hash=skill.content_hash,
        reason="Use the approved resource",
        resource_manifest=resource_manifest,
    )
    plan = SkillPlan(
        id=plan_id,
        run_id=run.id,
        status=SkillPlanStatus.RUNNING,
        intent=SkillIntent(goal=run.input_text),
        candidate_skill_ids=[skill.id],
        nodes=[node],
        planning_mode=AgentPlanningMode.DEEPSEARCH,
    )
    catalog = SkillCatalogService(repository)
    catalog._skills = {skill.name: skill}
    runtime = AgentRuntimeService(repository, model=ScriptedModel([]), enabled=True, skill_catalog=catalog)

    resolved = runtime._resolve_plan_node_security(plan=plan, node=node, run=run, user=USER)

    assert resolved[3] == resource_manifest.resource_hashes
    assert resolved[4] is True
    resource_path.write_text("changed", encoding="utf-8")
    with pytest.raises(RuntimeError, match="planned_resource_changed"):
        runtime._resolve_plan_node_security(plan=plan, node=node, run=run, user=USER)


def _synthesis_runner(
    calls: list[list[str]],
) -> Callable[[SkillPlan, list[SkillNodeResult]], Awaitable[tuple[SkillSynthesisResult, bool]]]:
    async def synthesize(
        _plan: SkillPlan,
        results: list[SkillNodeResult],
    ) -> tuple[SkillSynthesisResult, bool]:
        calls.append([result.node_id for result in results])
        return SkillSynthesisResult(summary="synthesized"), False

    return synthesize


def test_executor_delegates_terminal_plan_to_injected_finalization_strategy(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "finalization-strategy.sqlite3")
    plan, run = _persist_plan(
        repository,
        [_node("finalize")],
        output_contract=["synthesis"],
        suffix="finalization_strategy",
    )
    calls: list[tuple[str, str, int]] = []

    async def node_runner(
        _plan: SkillPlan,
        node: SkillPlanNode,
        _upstream: list[SkillNodeResult],
    ) -> NodeExecutionOutcome:
        return NodeExecutionOutcome(result=_result(node))

    class RecordingFinalizer:
        async def finalize(
            self,
            *,
            run_id: str,
            plan_id: str,
            expected_plan_version: int,
        ) -> PlanExecutionOutcome:
            calls.append((run_id, plan_id, expected_plan_version))
            persisted_plan = repository.get_skill_plan(plan_id)
            persisted_run = repository.get_agent_run(run_id)
            assert persisted_plan is not None
            assert persisted_run is not None
            assert all(
                node.status
                in {
                    SkillPlanNodeStatus.COMPLETED,
                    SkillPlanNodeStatus.FAILED,
                    SkillPlanNodeStatus.SKIPPED,
                    SkillPlanNodeStatus.CANCELLED,
                }
                for node in persisted_plan.nodes
            )
            return PlanExecutionOutcome(plan=persisted_plan, run=persisted_run)

    outcome = asyncio.run(
        BoundedDAGExecutor(
            repository,
            node_runner=node_runner,
            finalization_strategy=RecordingFinalizer(),
        ).run(plan, run)
    )

    assert outcome.run.id == run.id
    assert calls == [(run.id, plan.id, plan.version)]


def test_executor_rejects_ambiguous_finalization_configuration(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "ambiguous-finalization.sqlite3")

    class UnusedFinalizer:
        async def finalize(
            self,
            *,
            run_id: str,
            plan_id: str,
            expected_plan_version: int,
        ) -> PlanExecutionOutcome:
            raise AssertionError((run_id, plan_id, expected_plan_version))

    async def unused_node_runner(
        _plan: SkillPlan,
        _node: SkillPlanNode,
        _upstream: list[SkillNodeResult],
    ) -> NodeExecutionOutcome:
        raise AssertionError("node runner must not be called")

    with pytest.raises(ValueError, match="mutually exclusive"):
        BoundedDAGExecutor(
            repository,
            node_runner=unused_node_runner,
            synthesis_runner=_synthesis_runner([]),
            finalization_strategy=UnusedFinalizer(),
        )


def test_standard_finalizer_rejects_deepsearch_before_synthesis(tmp_path, monkeypatch) -> None:
    repository = SQLiteStore(tmp_path / "standard-finalizer-deepsearch.sqlite3")
    plan, run = _persist_plan(
        repository,
        [_node("deepsearch")],
        output_contract=["synthesis"],
        suffix="standard_finalizer_deepsearch",
    )
    deepsearch_plan = plan.model_copy(
        update={
            "planning_mode": AgentPlanningMode.DEEPSEARCH,
            "status": SkillPlanStatus.RUNNING,
        }
    )
    deepsearch_run = run.model_copy(
        update={
            "planning_mode": AgentPlanningMode.DEEPSEARCH,
            "status": AgentRunStatus.RUNNING,
        }
    )
    monkeypatch.setattr(repository, "get_skill_plan", lambda _plan_id: deepsearch_plan)
    monkeypatch.setattr(repository, "get_agent_run", lambda _run_id: deepsearch_run)
    synthesis_calls: list[list[str]] = []
    finalizer = StandardPlanFinalizer(
        repository,
        synthesis_runner=_synthesis_runner(synthesis_calls),
    )

    with pytest.raises(RuntimeError, match="deepsearch_finalization_strategy_required"):
        asyncio.run(
            finalizer.finalize(
                run_id=run.id,
                plan_id=plan.id,
                expected_plan_version=plan.version,
            )
        )

    assert synthesis_calls == []


def test_executor_resume_claims_persisted_ready_node(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "resume-ready.sqlite3")
    plan, run = _persist_plan(
        repository,
        [_node("ready")],
        output_contract=["synthesis"],
        suffix="resume_ready",
    )
    running_plan = repository.claim_skill_plan_for_execution(plan.id, run.id)
    assert running_plan is not None
    node = running_plan.nodes[0]
    persisted_ready = repository.transition_skill_plan_node(
        plan_id=plan.id,
        run_id=run.id,
        node=node.model_copy(update={"status": SkillPlanNodeStatus.READY}),
        expected_statuses={SkillPlanNodeStatus.PENDING},
        event_type="node_ready",
        event_payload={"plan_id": plan.id, "node_id": node.id},
    )
    assert persisted_ready is not None
    executed: list[str] = []

    async def node_runner(
        _plan: SkillPlan,
        ready_node: SkillPlanNode,
        _upstream: list[SkillNodeResult],
    ) -> NodeExecutionOutcome:
        executed.append(ready_node.id)
        return NodeExecutionOutcome(result=_result(ready_node))

    outcome = asyncio.run(
        BoundedDAGExecutor(
            repository,
            node_runner=node_runner,
            synthesis_runner=_synthesis_runner([]),
        ).run(running_plan, run, resume=True)
    )

    assert executed == [node.id]
    assert outcome.run.status is AgentRunStatus.COMPLETED
    event_types = [event.event_type for event in repository.list_agent_run_events(run.id)]
    assert event_types.count("node_ready") == 1


@pytest.mark.parametrize(
    "persisted_status",
    [SkillPlanNodeStatus.RUNNING, SkillPlanNodeStatus.WAITING_TOOL_APPROVAL],
)
def test_executor_does_not_finalize_with_persisted_nonterminal_node(tmp_path, persisted_status) -> None:  # noqa: ANN001
    repository = SQLiteStore(tmp_path / f"resume-{persisted_status.value}.sqlite3")
    plan, run = _persist_plan(
        repository,
        [_node("in_flight")],
        output_contract=["synthesis"],
        suffix=f"resume_{persisted_status.value}",
    )
    running_plan = repository.claim_skill_plan_for_execution(plan.id, run.id)
    assert running_plan is not None
    node = running_plan.nodes[0]
    transitioned = repository.transition_skill_plan_node(
        plan_id=plan.id,
        run_id=run.id,
        node=node.model_copy(update={"status": persisted_status}),
        expected_statuses={SkillPlanNodeStatus.PENDING},
        event_type="seed_nonterminal_node",
        event_payload={"plan_id": plan.id, "node_id": node.id},
    )
    assert transitioned is not None
    finalizer_called = False

    class RecordingFinalizer:
        async def finalize(
            self,
            *,
            run_id: str,
            plan_id: str,
            expected_plan_version: int,
        ) -> PlanExecutionOutcome:
            nonlocal finalizer_called
            finalizer_called = True
            raise AssertionError((run_id, plan_id, expected_plan_version))

    async def unused_node_runner(
        _plan: SkillPlan,
        _node: SkillPlanNode,
        _upstream: list[SkillNodeResult],
    ) -> NodeExecutionOutcome:
        raise AssertionError("persisted in-flight nodes must not be executed")

    with pytest.raises(RuntimeError, match="dag_has_nonterminal_node"):
        asyncio.run(
            BoundedDAGExecutor(
                repository,
                node_runner=unused_node_runner,
                finalization_strategy=RecordingFinalizer(),
            ).run(running_plan, run, resume=True)
        )

    assert finalizer_called is False


def test_executor_bounds_concurrency_and_preserves_shared_tool_budget(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "bounded.sqlite3")
    nodes = [_node(f"n{index}") for index in range(4)]
    plan, run = _persist_plan(repository, nodes, output_contract=["synthesis"], suffix="bounded")
    active = 0
    maximum = 0
    synthesis_calls: list[list[str]] = []

    async def node_runner(
        _plan: SkillPlan,
        node: SkillPlanNode,
        _upstream: list[SkillNodeResult],
    ) -> NodeExecutionOutcome:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        assert repository.consume_agent_run_tool_call(run.id) is not None
        await asyncio.sleep(0.02)
        active -= 1
        return NodeExecutionOutcome(result=_result(node))

    outcome = asyncio.run(
        BoundedDAGExecutor(
            repository,
            node_runner=node_runner,
            synthesis_runner=_synthesis_runner(synthesis_calls),
        ).run(plan, run)
    )

    persisted_run = repository.get_agent_run(run.id)
    persisted_plan = repository.get_skill_plan(plan.id)
    assert outcome.synthesis is not None
    assert maximum == 3
    assert persisted_run is not None and persisted_run.status == AgentRunStatus.COMPLETED
    assert persisted_run.tool_call_count == 4
    assert persisted_plan is not None and persisted_plan.status == SkillPlanStatus.COMPLETED
    assert all(node.status == SkillPlanNodeStatus.COMPLETED for node in persisted_plan.nodes)
    assert synthesis_calls == [["n0", "n1", "n2", "n3"]]
    events = [event.event_type for event in repository.list_agent_run_events(run.id)]
    assert events[-2:] == ["synthesis_completed", "run_completed"]


def test_executor_retries_only_transient_read_or_draft_failure_once(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "retry.sqlite3")
    plan, run = _persist_plan(
        repository,
        [_node("retry", output_contract=["analysis"], side_effect=SkillSideEffect.DRAFT)],
        output_contract=["analysis"],
        suffix="retry",
    )
    calls = 0

    async def node_runner(
        _plan: SkillPlan,
        node: SkillPlanNode,
        _upstream: list[SkillNodeResult],
    ) -> NodeExecutionOutcome:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("temporary provider connection")
        return NodeExecutionOutcome(result=_result(node))

    asyncio.run(
        BoundedDAGExecutor(
            repository,
            node_runner=node_runner,
            synthesis_runner=_synthesis_runner([]),
        ).run(plan, run)
    )

    persisted = repository.get_skill_plan(plan.id)
    assert calls == 2
    assert persisted is not None
    assert persisted.nodes[0].attempt == 2
    assert persisted.nodes[0].status == SkillPlanNodeStatus.COMPLETED


def test_executor_retries_remote_protocol_disconnect_once(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "remote-protocol-retry.sqlite3")
    plan, run = _persist_plan(
        repository,
        [_node("remote_protocol_retry", output_contract=["analysis"], side_effect=SkillSideEffect.DRAFT)],
        output_contract=["analysis"],
        suffix="remote_protocol_retry",
    )
    calls = 0

    class RemoteProtocolError(Exception):
        pass

    async def node_runner(
        _plan: SkillPlan,
        node: SkillPlanNode,
        _upstream: list[SkillNodeResult],
    ) -> NodeExecutionOutcome:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RemoteProtocolError("peer closed connection without sending complete message body")
        return NodeExecutionOutcome(result=_result(node))

    asyncio.run(
        BoundedDAGExecutor(
            repository,
            node_runner=node_runner,
            synthesis_runner=_synthesis_runner([]),
        ).run(plan, run)
    )

    persisted = repository.get_skill_plan(plan.id)
    assert calls == 2
    assert persisted is not None
    assert persisted.nodes[0].attempt == 2
    assert persisted.nodes[0].status == SkillPlanNodeStatus.COMPLETED


def test_executor_does_not_replay_node_after_model_stream_retries_are_exhausted(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "model-stream-retry-exhausted.sqlite3")
    plan, run = _persist_plan(
        repository,
        [_node("model_stream_retry", output_contract=["analysis"], side_effect=SkillSideEffect.DRAFT)],
        output_contract=["analysis"],
        suffix="model_stream_retry_exhausted",
    )
    calls = 0

    class RemoteProtocolError(Exception):
        pass

    async def node_runner(
        _plan: SkillPlan,
        _node: SkillPlanNode,
        _upstream: list[SkillNodeResult],
    ) -> NodeExecutionOutcome:
        nonlocal calls
        calls += 1
        raise ModelStreamRetryExhausted(
            RemoteProtocolError("peer closed connection without sending complete message body"),
            attempts=3,
        )

    asyncio.run(
        BoundedDAGExecutor(
            repository,
            node_runner=node_runner,
            synthesis_runner=_synthesis_runner([]),
        ).run(plan, run)
    )

    persisted = repository.get_skill_plan(plan.id)
    assert calls == 1
    assert persisted is not None
    assert persisted.nodes[0].attempt == 1
    assert persisted.nodes[0].status == SkillPlanNodeStatus.FAILED
    assert persisted.nodes[0].error_code == "RemoteProtocolError"
    node_failed = next(
        event for event in repository.list_agent_run_events(run.id) if event.event_type == "node_failed"
    )
    assert node_failed.payload["error_detail"].startswith("model stream failed after 3 attempts:")


def test_model_stream_retries_do_not_replay_completed_tool_or_dag_node(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "model-stream-retry-tool-reuse.sqlite3")
    plan, run = _persist_plan(
        repository,
        [_node("model_stream_tool_reuse", output_contract=["analysis"], side_effect=SkillSideEffect.READ)],
        output_contract=["analysis"],
        suffix="model_stream_tool_reuse",
    )
    tool_calls: list[str] = []
    node_calls = 0

    @function_tool
    def web_research(query: str) -> str:
        tool_calls.append(query)
        return "cached evidence"

    async def interrupted_report(_call):  # noqa: ANN001, ANN202
        yield ResponseTextDeltaEvent(
            type="response.output_text.delta",
            content_index=0,
            delta="PARTIAL",
            item_id="msg_partial",
            logprobs=[],
            output_index=0,
            sequence_number=0,
        )
        raise httpx.RemoteProtocolError("peer closed incomplete body")

    scripted = ScriptedModel(
        [
            [function_call("web_research", {"query": "market"}, call_id="lookup_once")],
            *[ModelStep.stream(interrupted_report) for _ in range(3)],
        ]
    )
    agent = Agent(
        name="retry integration",
        model=AtomicStreamModel(scripted),
        tools=[web_research],
        model_settings=ModelSettings(
            retry=ModelRetrySettings(
                max_retries=2,
                backoff=ModelRetryBackoffSettings(initial_delay=0, max_delay=0, jitter=False),
                policy=retry_policies.any(
                    retry_policies.provider_suggested(),
                    retry_policies.network_error(),
                    retry_transient_atomic_stream,
                ),
            )
        ),
    )
    runtime = AgentRuntimeService(repository=repository, model=scripted, enabled=True)

    async def node_runner(
        _plan: SkillPlan,
        _node: SkillPlanNode,
        _upstream: list[SkillNodeResult],
    ) -> NodeExecutionOutcome:
        nonlocal node_calls
        node_calls += 1
        await runtime._run_streamed(agent, "research", run=run)
        raise AssertionError("stream exhaustion must not produce a node result")

    asyncio.run(
        BoundedDAGExecutor(
            repository,
            node_runner=node_runner,
            synthesis_runner=_synthesis_runner([]),
        ).run(plan, run)
    )

    persisted_plan = repository.get_skill_plan(plan.id)
    persisted_run = repository.get_agent_run(run.id)
    assert node_calls == 1
    assert tool_calls == ["market"]
    assert len(scripted.calls) == 4
    assert persisted_plan is not None
    assert persisted_plan.nodes[0].attempt == 1
    assert persisted_plan.nodes[0].error_code == "RemoteProtocolError"
    assert persisted_run is not None
    assert persisted_run.error_code == "output_contract_unsatisfied"


def test_optional_failure_yields_partial_when_contract_remains_satisfied(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "partial.sqlite3")
    plan, run = _persist_plan(
        repository,
        [
            _node("required", output_contract=["analysis"]),
            _node("optional", required=False),
        ],
        output_contract=["analysis"],
        suffix="partial",
    )
    synthesis_calls: list[list[str]] = []

    async def node_runner(
        _plan: SkillPlan,
        node: SkillPlanNode,
        _upstream: list[SkillNodeResult],
    ) -> NodeExecutionOutcome:
        if node.id == "optional":
            raise ValueError("permanent failure")
        return NodeExecutionOutcome(result=_result(node))

    asyncio.run(
        BoundedDAGExecutor(
            repository,
            node_runner=node_runner,
            synthesis_runner=_synthesis_runner(synthesis_calls),
        ).run(plan, run)
    )

    persisted_run = repository.get_agent_run(run.id)
    persisted_plan = repository.get_skill_plan(plan.id)
    assert persisted_run is not None and persisted_run.status == AgentRunStatus.PARTIAL
    assert persisted_plan is not None and persisted_plan.status == SkillPlanStatus.PARTIAL
    assert {node.id: node.status for node in persisted_plan.nodes} == {
        "required": SkillPlanNodeStatus.COMPLETED,
        "optional": SkillPlanNodeStatus.FAILED,
    }
    assert synthesis_calls == [["required"]]


@pytest.mark.parametrize(
    ("plan_degradation", "result_degradation", "synthesis_fallback"),
    [
        ("planner_validation_fallback_single", None, False),
        (None, "provider_unavailable", False),
        (None, None, True),
    ],
)
def test_executor_marks_any_degraded_success_as_partial(
    tmp_path,
    plan_degradation: str | None,
    result_degradation: str | None,
    synthesis_fallback: bool,
) -> None:
    repository = SQLiteStore(tmp_path / f"degraded-{synthesis_fallback}.sqlite3")
    plan, run = _persist_plan(
        repository,
        [_node("required", output_contract=["analysis"])],
        output_contract=["analysis"],
        suffix=f"degraded_{synthesis_fallback}_{bool(plan_degradation)}_{bool(result_degradation)}",
    )
    plan.degradation = plan_degradation
    repository.save_skill_plan(plan)

    async def node_runner(
        _plan: SkillPlan,
        node: SkillPlanNode,
        _upstream: list[SkillNodeResult],
    ) -> NodeExecutionOutcome:
        return NodeExecutionOutcome(result=_result(node).model_copy(update={"degradation": result_degradation}))

    async def synthesis_runner(
        _plan: SkillPlan,
        _results: list[SkillNodeResult],
    ) -> tuple[SkillSynthesisResult, bool]:
        return SkillSynthesisResult(summary="synthesized"), synthesis_fallback

    asyncio.run(
        BoundedDAGExecutor(
            repository,
            node_runner=node_runner,
            synthesis_runner=synthesis_runner,
        ).run(plan, run)
    )

    persisted_run = repository.get_agent_run(run.id)
    persisted_plan = repository.get_skill_plan(plan.id)
    assert persisted_run is not None and persisted_run.status == AgentRunStatus.PARTIAL
    assert persisted_plan is not None and persisted_plan.status == SkillPlanStatus.PARTIAL
    assert [event.event_type for event in repository.list_agent_run_events(run.id)][-1] == "run_partial"


def test_parallel_approval_reschedule_does_not_consume_an_attempt(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "parallel-approval-attempt.sqlite3")
    nodes = [_node(f"approval_{index}") for index in range(3)]
    plan, run = _persist_plan(repository, nodes, output_contract=["synthesis"], suffix="parallel_approval")

    async def node_runner(
        _plan: SkillPlan,
        node: SkillPlanNode,
        _upstream: list[SkillNodeResult],
    ) -> NodeExecutionOutcome:
        return NodeExecutionOutcome(
            pause=NodePause(
                sdk_state={},
                interruptions=({"name": "tool", "argument_keys": "", "call_id": f"call_{node.id}"},),
                grant_snapshot_ids=(),
            )
        )

    outcome = asyncio.run(
        BoundedDAGExecutor(
            repository,
            node_runner=node_runner,
            synthesis_runner=_synthesis_runner([]),
        ).run(plan, run)
    )

    persisted = repository.get_skill_plan(plan.id)
    assert outcome.paused_node_id == nodes[0].id
    assert persisted is not None
    assert [(node.status, node.attempt) for node in persisted.nodes] == [
        (SkillPlanNodeStatus.RUNNING, 1),
        (SkillPlanNodeStatus.PENDING, 0),
        (SkillPlanNodeStatus.PENDING, 0),
    ]


def test_required_failure_skips_dependants_and_fails_unsatisfied_plan(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "required-failure.sqlite3")
    plan, run = _persist_plan(
        repository,
        [
            _node("root", output_contract=["analysis"]),
            _node("dependent", depends_on=["root"], output_contract=["report"]),
        ],
        output_contract=["report"],
        suffix="required_failure",
    )
    synthesis_calls: list[list[str]] = []

    async def node_runner(
        _plan: SkillPlan,
        node: SkillPlanNode,
        _upstream: list[SkillNodeResult],
    ) -> NodeExecutionOutcome:
        raise ValueError(f"{node.id} failed")

    asyncio.run(
        BoundedDAGExecutor(
            repository,
            node_runner=node_runner,
            synthesis_runner=_synthesis_runner(synthesis_calls),
        ).run(plan, run)
    )

    persisted_run = repository.get_agent_run(run.id)
    persisted_plan = repository.get_skill_plan(plan.id)
    assert persisted_run is not None and persisted_run.status == AgentRunStatus.FAILED
    assert persisted_run.error_code == "output_contract_unsatisfied"
    assert persisted_plan is not None and persisted_plan.status == SkillPlanStatus.FAILED
    assert {node.id: node.status for node in persisted_plan.nodes} == {
        "root": SkillPlanNodeStatus.FAILED,
        "dependent": SkillPlanNodeStatus.SKIPPED,
    }
    terminal_event = repository.list_agent_run_events(run.id)[-1]
    assert terminal_event.event_type == "run_failed"
    assert terminal_event.payload == {
        "error_code": "output_contract_unsatisfied",
        "causes": [{"node_id": "root", "error_code": "ValueError", "attempt": 1}],
        "missing_outputs": ["report"],
    }
    assert synthesis_calls == []


def test_required_failure_skips_all_transitive_dependants(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "transitive-required-failure.sqlite3")
    plan, run = _persist_plan(
        repository,
        [
            _node("root", output_contract=["analysis"]),
            _node("middle", depends_on=["root"], output_contract=["brief"]),
            _node("leaf", depends_on=["middle"], output_contract=["report"]),
        ],
        output_contract=["report"],
        suffix="transitive_required_failure",
    )

    async def node_runner(
        _plan: SkillPlan,
        node: SkillPlanNode,
        _upstream: list[SkillNodeResult],
    ) -> NodeExecutionOutcome:
        if node.id == "root":
            raise ValueError("root failed")
        raise AssertionError(f"dependent node {node.id} must not run")

    asyncio.run(
        BoundedDAGExecutor(
            repository,
            node_runner=node_runner,
            synthesis_runner=_synthesis_runner([]),
        ).run(plan, run)
    )

    persisted_run = repository.get_agent_run(run.id)
    persisted_plan = repository.get_skill_plan(plan.id)
    assert persisted_run is not None and persisted_run.status == AgentRunStatus.FAILED
    assert persisted_plan is not None and persisted_plan.status == SkillPlanStatus.FAILED
    assert {node.id: node.status for node in persisted_plan.nodes} == {
        "root": SkillPlanNodeStatus.FAILED,
        "middle": SkillPlanNodeStatus.SKIPPED,
        "leaf": SkillPlanNodeStatus.SKIPPED,
    }


def test_cancelling_executor_atomically_cancels_plan_nodes_and_run(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "cancel.sqlite3")
    plan, run = _persist_plan(repository, [_node("slow")], output_contract=["synthesis"], suffix="cancel")
    started = asyncio.Event()

    async def node_runner(
        _plan: SkillPlan,
        _node: SkillPlanNode,
        _upstream: list[SkillNodeResult],
    ) -> NodeExecutionOutcome:
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def scenario() -> None:
        task = asyncio.create_task(
            BoundedDAGExecutor(
                repository,
                node_runner=node_runner,
                synthesis_runner=_synthesis_runner([]),
            ).run(plan, run)
        )
        await started.wait()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    persisted_run = repository.get_agent_run(run.id)
    persisted_plan = repository.get_skill_plan(plan.id)
    assert persisted_run is not None and persisted_run.status == AgentRunStatus.CANCELLED
    assert persisted_plan is not None and persisted_plan.status == SkillPlanStatus.CANCELLED
    assert persisted_plan.nodes[0].status == SkillPlanNodeStatus.CANCELLED
    assert [event.event_type for event in repository.list_agent_run_events(run.id)][-1] == "run_cancelled"


def test_late_node_completion_cannot_overwrite_external_cancellation(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "late-node.sqlite3")
    plan, run = _persist_plan(
        repository,
        [_node("late")],
        output_contract=["synthesis"],
        suffix="late_node",
    )
    started = asyncio.Event()
    release = asyncio.Event()

    async def node_runner(
        _plan: SkillPlan,
        node: SkillPlanNode,
        _upstream: list[SkillNodeResult],
    ) -> NodeExecutionOutcome:
        started.set()
        await release.wait()
        return NodeExecutionOutcome(result=_result(node))

    async def scenario() -> None:
        task = asyncio.create_task(
            BoundedDAGExecutor(
                repository,
                node_runner=node_runner,
                synthesis_runner=_synthesis_runner([]),
            ).run(plan, run)
        )
        await started.wait()
        assert repository.cancel_agent_run_tree(run.id, user_id=run.user_id) is not None
        release.set()
        with suppress(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    persisted_run = repository.get_agent_run(run.id)
    persisted_plan = repository.get_skill_plan(plan.id)
    assert persisted_run is not None and persisted_run.status == AgentRunStatus.CANCELLED
    assert persisted_plan is not None and persisted_plan.status == SkillPlanStatus.CANCELLED
    assert persisted_plan.nodes[0].status == SkillPlanNodeStatus.CANCELLED
    assert repository.list_skill_node_results(plan.id) == []
    assert "node_completed" not in {
        event.event_type for event in repository.list_agent_run_events(run.id)
    }


def test_losing_executor_does_not_fail_the_winning_plan(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "executor-owner.sqlite3")
    plan, run = _persist_plan(
        repository,
        [_node("owner")],
        output_contract=["synthesis"],
        suffix="executor_owner",
    )
    stale_plan = plan.model_copy(deep=True)
    assert repository.claim_skill_plan_for_execution(plan.id, run.id) is not None
    runtime = AgentRuntimeService(repository, model=ScriptedModel([]), enabled=True)

    with pytest.raises(PlanExecutionConflict, match="plan_execution_claim_conflict"):
        asyncio.run(runtime._execute_approved_skill_plan(plan=stale_plan, run=run, user=USER))

    persisted_run = repository.get_agent_run(run.id)
    persisted_plan = repository.get_skill_plan(plan.id)
    assert persisted_run is not None and persisted_run.status == AgentRunStatus.RUNNING
    assert persisted_plan is not None and persisted_plan.status == SkillPlanStatus.RUNNING
    assert persisted_plan.nodes[0].status == SkillPlanNodeStatus.PENDING


def test_initial_plan_pause_failure_converges_plan_and_run(tmp_path, monkeypatch) -> None:
    repository = SQLiteStore(tmp_path / "pause-failure.sqlite3")
    plan, run = _persist_plan(
        repository,
        [_node("pause_failure")],
        output_contract=["synthesis"],
        suffix="pause_failure",
    )
    runtime = AgentRuntimeService(repository, model=ScriptedModel([]), enabled=True)

    async def pause_node(**_kwargs) -> NodeExecutionOutcome:
        return NodeExecutionOutcome(
            pause=NodePause(
                sdk_state={},
                interruptions=({"name": "tool", "argument_keys": "", "call_id": "call_pause"},),
                grant_snapshot_ids=(),
            )
        )

    monkeypatch.setattr(runtime, "_execute_skill_plan_node", pause_node)
    monkeypatch.setattr(repository, "pause_skill_plan_node_and_run", lambda **_kwargs: None)

    with pytest.raises(RuntimeError, match="changed while pausing"):
        asyncio.run(runtime._execute_approved_skill_plan(plan=plan, run=run, user=USER))

    persisted_run = repository.get_agent_run(run.id)
    persisted_plan = repository.get_skill_plan(plan.id)
    assert persisted_run is not None and persisted_run.status == AgentRunStatus.FAILED
    assert persisted_plan is not None and persisted_plan.status == SkillPlanStatus.FAILED
    assert persisted_plan.nodes[0].status == SkillPlanNodeStatus.FAILED


def test_plan_node_stops_when_project_membership_is_revoked(tmp_path, configure_pilot_wiki) -> None:
    configure_pilot_wiki(tmp_path / "wiki")
    repository = SQLiteStore(tmp_path / "revoked-project.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    catalog = SkillCatalogService(repository)
    catalog.reload()
    skill = catalog.get_by_name("prd-feasibility", USER.personal_agent_id)
    assert skill is not None
    profile = repository.get_skill_capability_profile(skill.id)
    assert profile is not None
    thread = repository.add_chat_thread(
        ChatThread(
            id="thread_revoked_project",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="Revoked project",
        )
    )
    run = repository.save_agent_run(
        AgentRun(
            id="run_revoked_project",
            thread_id=thread.id,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="review this PRD",
            status=AgentRunStatus.RUNNING,
            plan_id="plan_revoked_project",
            deadline_at=now_utc() + timedelta(seconds=300),
        )
    )
    node = SkillPlanNode(
        id="node_revoked_project",
        skill_id=skill.id,
        skill_version=skill.version,
        skill_content_hash=skill.content_hash,
        reason="review the PRD",
        input_bindings=["user.prd"],
        output_contract=["feasibility_review"],
        side_effect=profile.side_effect,
    )
    plan = repository.save_skill_plan(
        SkillPlan(
            id=run.plan_id,
            run_id=run.id,
            status=SkillPlanStatus.APPROVED,
            intent=SkillIntent(goal="review this PRD", input_kinds=["prd"]),
            candidate_skill_ids=[skill.id],
            output_contract=["feasibility_review"],
            nodes=[node],
        )
    )
    project = repository.get_project(run.project_id)
    assert project is not None
    repository.save_project(project.model_copy(update={"member_ids": ["another_user"]}))
    model = ScriptedModel([])
    runtime = AgentRuntimeService(repository, model=model, enabled=True, skill_catalog=catalog)

    asyncio.run(runtime._execute_approved_skill_plan(plan=plan, run=run, user=USER))

    failed_run = repository.get_agent_run(run.id)
    failed_plan = repository.get_skill_plan(plan.id)
    assert failed_run is not None and failed_run.status == AgentRunStatus.FAILED
    assert failed_plan is not None and failed_plan.status == SkillPlanStatus.FAILED
    assert failed_plan.nodes[0].status == SkillPlanNodeStatus.FAILED
    assert failed_plan.nodes[0].error_code == "planned_project_access_revoked"
    assert repository.list_skill_node_results(plan.id) == []
    assert model.calls == ()


def test_plan_execution_rejects_skill_outside_pilot_scope(tmp_path, configure_pilot_wiki) -> None:
    configure_pilot_wiki(tmp_path / "wiki")
    repository = SQLiteStore(tmp_path / "outside-pilot-skill.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    catalog = SkillCatalogService(repository)
    catalog.reload()
    builtin = catalog.get_by_name("prd-feasibility", USER.personal_agent_id)
    assert builtin is not None
    builtin_profile = repository.get_skill_capability_profile(builtin.id)
    assert builtin_profile is not None
    outside = builtin.model_copy(
        update={
            "id": "skill_workspace_outside_pilot",
            "name": "workspace-outside-pilot",
            "source_path": "/virtual/workspace-outside-pilot/SKILL.md",
            "source_scope": SkillSourceScope.WORKSPACE,
        }
    )
    outside_profile = builtin_profile.model_copy(
        update={
            "id": outside.id,
            "skill_id": outside.id,
            "skill_name": outside.name,
            "planner_eligible": True,
        }
    )
    repository.save_skill_definition(outside)
    repository.save_skill_capability_profile(outside_profile)

    class CatalogStub:
        def list_for_agent(self, _agent_id):
            return [(outside, True)]

    model = ScriptedModel([])
    runtime = AgentRuntimeService(
        repository,
        model=model,
        enabled=True,
        skill_catalog=CatalogStub(),  # type: ignore[arg-type]
    )
    thread = repository.add_chat_thread(
        ChatThread(
            id="thread_outside_pilot",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="Outside pilot",
        )
    )
    node = SkillPlanNode(
        id="node_outside_pilot",
        skill_id=outside.id,
        skill_version=outside.version,
        skill_content_hash=outside.content_hash,
        reason="must be rejected",
        input_bindings=["user.request"],
        output_contract=[outside_profile.output_kinds[0]],
        side_effect=outside_profile.side_effect,
    )
    run = repository.save_agent_run(
        AgentRun(
            id="run_outside_pilot",
            thread_id=thread.id,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="run outside pilot",
            status=AgentRunStatus.RUNNING,
            plan_id="plan_outside_pilot",
        )
    )
    plan = repository.save_skill_plan(
        SkillPlan(
            id=run.plan_id,
            run_id=run.id,
            status=SkillPlanStatus.APPROVED,
            intent=SkillIntent(goal=run.input_text),
            candidate_skill_ids=[outside.id],
            output_contract=node.output_contract,
            nodes=[node],
        )
    )

    with pytest.raises(RuntimeError, match="planned_skill_outside_pilot_scope"):
        runtime._resolve_plan_node_security(plan=plan, node=node, run=run, user=USER)

    assert model.calls == ()


def test_synthesis_stops_when_project_access_is_revoked(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "synthesis-project-revocation.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    thread = repository.add_chat_thread(
        ChatThread(
            id="thread_synthesis_project_revocation",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="Revoke before synthesis",
        )
    )
    node = SkillPlanNode(
        id="node_completed_before_revocation",
        skill_id="skill_completed_before_revocation",
        skill_version="1",
        skill_content_hash="hash_completed_before_revocation",
        reason="already completed",
        input_bindings=["user.request"],
        output_contract=["design_analysis"],
        status=SkillPlanNodeStatus.COMPLETED,
        attempt=1,
        completed_at=now_utc(),
    )
    run = repository.save_agent_run(
        AgentRun(
            id="run_synthesis_project_revocation",
            thread_id=thread.id,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="synthesize safely",
            status=AgentRunStatus.RUNNING,
            plan_id="plan_synthesis_project_revocation",
            deadline_at=now_utc() + timedelta(seconds=300),
        )
    )
    plan = repository.save_skill_plan(
        SkillPlan(
            id=run.plan_id,
            run_id=run.id,
            status=SkillPlanStatus.APPROVED,
            intent=SkillIntent(goal=run.input_text),
            candidate_skill_ids=[node.skill_id],
            output_contract=node.output_contract,
            nodes=[node],
        )
    )
    repository.save_skill_node_result(
        plan.id,
        SkillNodeResult(
            id="result_completed_before_revocation",
            node_id=node.id,
            skill_id=node.skill_id,
            summary="Completed before access was revoked",
            attempt=1,
        ),
    )
    project = repository.get_project(USER.default_project_id)
    assert project is not None
    repository.save_project(project.model_copy(update={"member_ids": ["usr_someone_else"]}))
    model = ScriptedModel([])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)

    with pytest.raises(RuntimeError, match="planned_project_access_revoked"):
        asyncio.run(runtime._execute_approved_skill_plan(plan=plan, run=run, user=USER))

    failed_run = repository.get_agent_run(run.id)
    assert failed_run is not None and failed_run.status == AgentRunStatus.FAILED
    assert model.calls == ()


@pytest.mark.parametrize("foreign_source", [False, True], ids=["same_run", "foreign_run_and_project"])
def test_downstream_node_accepts_only_same_run_project_upstream_sources(
    tmp_path,
    configure_pilot_wiki,
    foreign_source: bool,
) -> None:
    configure_pilot_wiki(tmp_path / "wiki")
    repository = SQLiteStore(tmp_path / f"source-lineage-{foreign_source}.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    catalog = SkillCatalogService(repository)
    catalog.reload()
    research = catalog.get_by_name("generate-research-plan", USER.personal_agent_id)
    interview = catalog.get_by_name("generate-interview-guide", USER.personal_agent_id)
    assert research is not None and interview is not None
    research_profile = repository.get_skill_capability_profile(research.id)
    interview_profile = repository.get_skill_capability_profile(interview.id)
    assert research_profile is not None and interview_profile is not None
    suffix = "foreign" if foreign_source else "same_run"
    thread = repository.add_chat_thread(
        ChatThread(
            id=f"thread_source_lineage_{suffix}",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="Source lineage",
        )
    )
    run = repository.save_agent_run(
        AgentRun(
            id=f"run_source_lineage_{suffix}",
            thread_id=thread.id,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="制定研究计划并生成访谈提纲",
            status=AgentRunStatus.RUNNING,
            plan_id=f"plan_source_lineage_{suffix}",
            deadline_at=now_utc() + timedelta(seconds=300),
        )
    )
    source = repository.add_source(
        Source(
            id=f"src_source_lineage_{suffix}",
            title="Validated research evidence",
            source_type="web_page",
            reference="https://example.test/research",
            workspace_id=run.workspace_id,
            project_id="project_foreign" if foreign_source else run.project_id,
            user_id=run.user_id,
            run_id="run_foreign" if foreign_source else run.id,
            skill_id=research.id,
        )
    )
    first = SkillPlanNode(
        id="node_research_plan",
        skill_id=research.id,
        skill_version=research.version,
        skill_content_hash=research.content_hash,
        reason="create the research plan",
        input_bindings=["user.design_requirement"],
        output_contract=["research_plan"],
        side_effect=research_profile.side_effect,
        status=SkillPlanNodeStatus.COMPLETED,
        attempt=1,
        completed_at=now_utc(),
    )
    second = SkillPlanNode(
        id="node_interview_guide",
        skill_id=interview.id,
        skill_version=interview.version,
        skill_content_hash=interview.content_hash,
        reason="turn the plan into an interview guide",
        depends_on=[first.id],
        input_bindings=[f"{first.id}.research_plan"],
        output_contract=["interview_guide"],
        side_effect=interview_profile.side_effect,
    )
    plan = repository.save_skill_plan(
        SkillPlan(
            id=run.plan_id,
            run_id=run.id,
            status=SkillPlanStatus.APPROVED,
            intent=SkillIntent(
                goal=run.input_text,
                input_kinds=["design_requirement"],
                deliverables=["research_plan", "interview_guide"],
            ),
            candidate_skill_ids=[research.id, interview.id],
            output_contract=["interview_guide"],
            nodes=[first, second],
        )
    )
    upstream_result = repository.save_skill_node_result(
        plan.id,
        SkillNodeResult(
            id=f"result_{first.id}",
            node_id=first.id,
            skill_id=research.id,
            summary="Research plan completed",
            sources=[
                SkillResultSource(
                    id=source.id,
                    title=source.title,
                    source_type=source.source_type,
                    reference=source.reference,
                )
            ],
            attempt=1,
        ),
    )
    second_result_id = f"node_result_{plan.id}_{second.id}_1"
    steps = [
        [
            assistant_message(
                json.dumps(
                    {
                        "node_id": second.id,
                        "skill_id": interview.id,
                        "summary": "Interview guide completed from verified evidence",
                        "sources": [
                            {
                                "id": source.id,
                                "title": "model supplied title is replaced",
                                "source_type": "model_supplied",
                                "reference": "model-supplied://reference",
                            }
                        ],
                    }
                )
            )
        ]
    ]
    if not foreign_source:
        steps.append(
            [
                assistant_message(
                    json.dumps(
                        {
                            "summary": "Research workflow completed",
                            "claims": [
                                {
                                    "text": "The interview guide follows the verified research evidence",
                                    "node_result_ids": [second_result_id],
                                    "source_ids": [source.id],
                                    "recommendation": False,
                                }
                            ],
                        }
                    )
                )
            ]
        )
    model = ScriptedModel(steps)
    runtime = AgentRuntimeService(repository, model=model, enabled=True, skill_catalog=catalog)

    asyncio.run(runtime._execute_approved_skill_plan(plan=plan, run=run, user=USER))

    persisted_run = repository.get_agent_run(run.id)
    persisted_plan = repository.get_skill_plan(plan.id)
    assert persisted_run is not None and persisted_plan is not None
    if foreign_source:
        assert persisted_run.status == AgentRunStatus.FAILED
        assert persisted_plan.status == SkillPlanStatus.FAILED
        assert persisted_plan.nodes[1].error_code == "unauthorized_node_source"
        assert [result.id for result in repository.list_skill_node_results(plan.id)] == [upstream_result.id]
    else:
        assert persisted_run.status == AgentRunStatus.COMPLETED
        assert persisted_plan.status == SkillPlanStatus.COMPLETED
        results = repository.list_skill_node_results(plan.id)
        assert [result.id for result in results] == [upstream_result.id, second_result_id]
        assert results[1].sources[0].title == source.title
        assert persisted_plan.synthesis is not None
    model.assert_complete()


def test_synthesis_rejects_a_node_source_that_no_longer_exists(tmp_path, configure_pilot_wiki) -> None:
    configure_pilot_wiki(tmp_path / "wiki")
    repository = SQLiteStore(tmp_path / "missing-synthesis-source.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    catalog = SkillCatalogService(repository)
    catalog.reload()
    skill = catalog.get_by_name("prd-feasibility", USER.personal_agent_id)
    assert skill is not None
    profile = repository.get_skill_capability_profile(skill.id)
    assert profile is not None
    thread = repository.add_chat_thread(
        ChatThread(
            id="thread_missing_synthesis_source",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="Missing synthesis source",
        )
    )
    run = repository.save_agent_run(
        AgentRun(
            id="run_missing_synthesis_source",
            thread_id=thread.id,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="review this PRD",
            status=AgentRunStatus.RUNNING,
            plan_id="plan_missing_synthesis_source",
            deadline_at=now_utc() + timedelta(seconds=300),
        )
    )
    node = SkillPlanNode(
        id="node_missing_synthesis_source",
        skill_id=skill.id,
        skill_version=skill.version,
        skill_content_hash=skill.content_hash,
        reason="review the PRD",
        input_bindings=["user.prd"],
        output_contract=["feasibility_review"],
        side_effect=profile.side_effect,
        status=SkillPlanNodeStatus.COMPLETED,
        attempt=1,
        completed_at=now_utc(),
    )
    plan = repository.save_skill_plan(
        SkillPlan(
            id=run.plan_id,
            run_id=run.id,
            status=SkillPlanStatus.APPROVED,
            intent=SkillIntent(goal=run.input_text, input_kinds=["prd"]),
            candidate_skill_ids=[skill.id],
            output_contract=["feasibility_review"],
            nodes=[node],
        )
    )
    repository.save_skill_node_result(
        plan.id,
        SkillNodeResult(
            id="result_missing_synthesis_source",
            node_id=node.id,
            skill_id=skill.id,
            summary="Untrusted persisted result",
            sources=[
                SkillResultSource(
                    id="src_missing_synthesis_source",
                    title="Missing",
                    source_type="web_page",
                    reference="https://example.test/missing",
                )
            ],
            attempt=1,
        ),
    )
    model = ScriptedModel([])
    runtime = AgentRuntimeService(repository, model=model, enabled=True, skill_catalog=catalog)

    with pytest.raises(ValueError, match="unknown_synthesis_source"):
        asyncio.run(runtime._execute_approved_skill_plan(plan=plan, run=run, user=USER))

    failed_run = repository.get_agent_run(run.id)
    failed_plan = repository.get_skill_plan(plan.id)
    assert failed_run is not None and failed_run.status == AgentRunStatus.FAILED
    assert failed_plan is not None and failed_plan.status == SkillPlanStatus.FAILED
    assert model.calls == ()


def test_plan_node_high_risk_tool_confirmation_resumes_node_then_remaining_dag(
    tmp_path,
    monkeypatch,
    configure_pilot_wiki,
) -> None:
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "execute")
    configure_pilot_wiki(tmp_path / "wiki")
    repository = SQLiteStore(tmp_path / "approval.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    catalog = SkillCatalogService(repository)
    catalog.reload()
    skill = catalog.get_by_name("prd-feasibility", USER.personal_agent_id)
    assert skill is not None
    profile = repository.get_skill_capability_profile(skill.id)
    assert profile is not None
    repository.save_skill_capability_profile(
        profile.model_copy(update={"required_capabilities": ["research.request"]})
    )
    ensure_tool_seed_data(repository, granted_by="system")
    repository.save_agent_tool_grant(
        AgentToolGrant(
            id="grant_plan_web",
            agent_id=USER.personal_agent_id,
            tool_id="tool_web_research",
            granted_by="test",
        )
    )
    thread = repository.add_chat_thread(
        ChatThread(
            id="thread_plan_approval",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="Plan approval",
        )
    )
    run = repository.save_agent_run(
        AgentRun(
            id="run_plan_approval",
            thread_id=thread.id,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="review this PRD",
            status=AgentRunStatus.RUNNING,
            orchestration_mode="execute",
            project_chat=True,
            deadline_at=now_utc() + timedelta(seconds=300),
        )
    )
    node = SkillPlanNode(
        id="node_plan_approval",
        skill_id=skill.id,
        skill_version=skill.version,
        skill_content_hash=skill.content_hash,
        reason="review the PRD",
        input_bindings=["user.prd"],
        output_contract=["feasibility_review"],
        side_effect=profile.side_effect,
    )
    plan = repository.save_skill_plan(
        SkillPlan(
            id="plan_tool_approval",
            run_id=run.id,
            status=SkillPlanStatus.APPROVED,
            intent=SkillIntent(goal="review this PRD", input_kinds=["prd"]),
            candidate_skill_ids=[skill.id],
            output_contract=["feasibility_review"],
            nodes=[node],
        )
    )
    run.plan_id = plan.id
    repository.save_agent_run(run)
    result_id = f"node_result_{plan.id}_{node.id}_1"
    model = ScriptedModel(
        [
            [
                function_call("web_research", {"query": "批量抓取 PRD benchmark A"}, call_id="plan_web_call_a"),
                function_call("web_research", {"query": "批量抓取 PRD benchmark B"}, call_id="plan_web_call_b"),
            ],
            [
                assistant_message(
                    json.dumps(
                        {
                            "node_id": node.id,
                            "skill_id": skill.id,
                            "summary": "PRD review completed",
                        }
                    )
                )
            ],
            [
                assistant_message(
                    json.dumps(
                        {
                            "summary": "Synthesis completed",
                            "claims": [
                                {
                                    "text": "Review completed",
                                    "node_result_ids": [result_id],
                                    "source_ids": [],
                                    "recommendation": True,
                                }
                            ],
                        }
                    )
                )
            ],
        ]
    )
    tool_projects: list[str] = []

    class GatewayStub:
        @staticmethod
        def handlers():
            def web_research(context, _arguments):  # noqa: ANN001, ANN202
                tool_projects.append(context.project_id)
                return {"title": "benchmark", "sources": []}

            return {"web_research": web_research}

    runtime = AgentRuntimeService(
        repository,
        model=model,
        enabled=True,
        tool_factory=AgentMeshToolFactory(repository, gateway=GatewayStub()),  # type: ignore[arg-type]
        skill_catalog=catalog,
    )

    paused = asyncio.run(runtime._execute_approved_skill_plan(plan=plan, run=run, user=USER))
    assert paused.pause is not None
    waiting_run = repository.get_agent_run(run.id)
    waiting_plan = repository.get_skill_plan(plan.id)
    assert waiting_run is not None and waiting_run.status == AgentRunStatus.WAITING_APPROVAL
    assert waiting_plan is not None
    assert waiting_plan.nodes[0].status == SkillPlanNodeStatus.WAITING_TOOL_APPROVAL

    switched_user = USER.model_copy(update={"default_project_id": "project_switched"})
    with pytest.raises(RuntimeError, match="pending call IDs"):
        runtime.resume_sync(
            run.id,
            user=switched_user,
            decisions={"unknown_call": True},
        )
    still_waiting = repository.get_agent_run(run.id)
    assert still_waiting is not None and still_waiting.status == AgentRunStatus.WAITING_APPROVAL

    partial = runtime.resume_sync(
        run.id,
        user=switched_user,
        decisions={"plan_web_call_a": True},
    )
    assert partial.waiting_approval is True
    assert [item["call_id"] for item in partial.interruptions] == ["plan_web_call_b"]
    assert tool_projects == [USER.default_project_id]

    answer = runtime.resume_sync(
        run.id,
        user=switched_user,
        decisions={"plan_web_call_b": True},
    )

    completed_run = repository.get_agent_run(run.id)
    completed_plan = repository.get_skill_plan(plan.id)
    assert answer.waiting_approval is False
    assert completed_run is not None and completed_run.status == AgentRunStatus.COMPLETED
    assert completed_plan is not None and completed_plan.status == SkillPlanStatus.COMPLETED
    assert completed_plan.nodes[0].status == SkillPlanNodeStatus.COMPLETED
    assert [result.id for result in repository.list_skill_node_results(plan.id)] == [result_id]
    assert tool_projects == [USER.default_project_id, USER.default_project_id]
    assert len(repository.list_thread_messages(thread.id)) == 1
    model.assert_complete()
    assert [call.model_settings.max_tokens for call in model.calls if call.streamed] == [8_192, 8_192]


def test_plan_node_approval_is_refused_without_mutation_when_orchestration_is_off(tmp_path, monkeypatch) -> None:
    repository = SQLiteStore(tmp_path / "approval-rollback.sqlite3")
    node = _node("approval_rollback", output_contract=["analysis"])
    plan, run = _persist_plan(
        repository,
        [node],
        output_contract=["analysis"],
        suffix="approval_rollback",
    )
    waiting_node = node.model_copy(update={"status": SkillPlanNodeStatus.WAITING_TOOL_APPROVAL, "attempt": 1})
    plan.status = SkillPlanStatus.RUNNING
    plan.nodes = [waiting_node]
    repository.save_skill_plan(plan)
    run.status = AgentRunStatus.WAITING_APPROVAL
    run.paused_state = {
        "kind": "skill_plan_node",
        "plan_id": plan.id,
        "node_id": waiting_node.id,
        "expires_at": (now_utc() + timedelta(hours=1)).isoformat(),
    }
    repository.save_agent_run(run)
    inbox = repository.add_inbox_item(
        InboxItem(
            id=f"inbox_tool_approval_{run.id}",
            title="Approve",
            summary="Waiting",
            item_type="sdk_tool_approval",
            scope=Scope.PRIVATE,
            user_id=run.user_id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            metadata={"run_id": run.id},
        )
    )
    runtime = AgentRuntimeService(repository, model=ScriptedModel([]), enabled=True)
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "off")

    with pytest.raises(RuntimeError, match="execution is disabled"):
        runtime.resume_sync(
            run.id,
            user=USER.model_copy(
                update={
                    "id": run.user_id,
                    "workspace_id": run.workspace_id,
                    "default_project_id": run.project_id,
                }
            ),
            decisions={},
        )

    assert repository.get_agent_run(run.id).status == AgentRunStatus.WAITING_APPROVAL  # type: ignore[union-attr]
    assert repository.get_skill_plan(plan.id).status == SkillPlanStatus.RUNNING  # type: ignore[union-attr]
    assert repository.get_inbox_item(inbox.id).status == "open"  # type: ignore[union-attr]


def test_revoked_grant_fails_waiting_plan_and_resolves_inbox(
    tmp_path,
    monkeypatch,
    configure_pilot_wiki,
) -> None:
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "execute")
    configure_pilot_wiki(tmp_path / "wiki")
    repository = SQLiteStore(tmp_path / "revoked-grant.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    catalog = SkillCatalogService(repository)
    catalog.reload()
    skill = catalog.get_by_name("prd-feasibility", USER.personal_agent_id)
    assert skill is not None
    profile = repository.get_skill_capability_profile(skill.id)
    assert profile is not None
    repository.save_skill_capability_profile(
        profile.model_copy(update={"required_capabilities": ["research.request"]})
    )
    ensure_tool_seed_data(repository, granted_by="system")
    grant = next(
        item
        for item in repository.list_agent_tool_grants(USER.personal_agent_id)
        if item.tool_id == "tool_web_research"
    )
    node = SkillPlanNode(
        id="node_revoked_grant",
        skill_id=skill.id,
        skill_version=skill.version,
        skill_content_hash=skill.content_hash,
        reason="review the PRD",
        input_bindings=["user.prd"],
        output_contract=["feasibility_review"],
        side_effect=profile.side_effect,
        status=SkillPlanNodeStatus.WAITING_TOOL_APPROVAL,
        attempt=1,
    )
    run = repository.save_agent_run(
        AgentRun(
            id="run_revoked_grant",
            thread_id="thread_revoked_grant",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="review this PRD",
            status=AgentRunStatus.WAITING_APPROVAL,
            plan_id="plan_revoked_grant",
            paused_state={
                "kind": "skill_plan_node",
                "plan_id": "plan_revoked_grant",
                "node_id": node.id,
                "skill_id": skill.id,
                "skill_content_hash": skill.content_hash,
                "grant_snapshot_ids": [grant.id],
                "sdk_state": {},
                "expires_at": (now_utc() + timedelta(hours=24)).isoformat(),
            },
        )
    )
    plan = repository.save_skill_plan(
        SkillPlan(
            id="plan_revoked_grant",
            run_id=run.id,
            status=SkillPlanStatus.RUNNING,
            intent=SkillIntent(goal="review this PRD"),
            candidate_skill_ids=[skill.id],
            output_contract=["feasibility_review"],
            nodes=[node],
        )
    )
    inbox = repository.add_inbox_item(
        InboxItem(
            id=f"inbox_tool_approval_{run.id}",
            title="Approve",
            summary="Waiting",
            item_type="sdk_tool_approval",
            scope=Scope.PRIVATE,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            metadata={"run_id": run.id, "interruptions": '[]'},
        )
    )
    repository.save_agent_tool_grant(grant.model_copy(update={"enabled": False}))
    assert not any(
        item.enabled and item.tool_id == "tool_web_research"
        for item in repository.list_agent_tool_grants(USER.personal_agent_id)
    )
    runtime = AgentRuntimeService(repository, model=ScriptedModel([]), enabled=True, skill_catalog=catalog)

    with pytest.raises(RuntimeError, match="planned_tool_grant_revoked"):
        runtime.resume_sync(run.id, user=USER, decisions={"call": True})

    failed_run = repository.get_agent_run(run.id)
    failed_plan = repository.get_skill_plan(plan.id)
    assert failed_run is not None and failed_run.status == AgentRunStatus.FAILED
    assert failed_plan is not None and failed_plan.status == SkillPlanStatus.FAILED
    assert failed_plan.nodes[0].status == SkillPlanNodeStatus.FAILED
    assert repository.get_inbox_item(inbox.id).status == "resolved"  # type: ignore[union-attr]
    assert repository.list_skill_node_results(plan.id) == []
    run_failed = repository.list_agent_run_events(run.id)[-1]
    assert run_failed.event_type == "run_failed"
    assert run_failed.payload["causes"] == [
        {
            "node_id": node.id,
            "error_code": "planned_tool_grant_revoked",
            "attempt": node.attempt,
        }
    ]
    assert run_failed.payload["missing_outputs"] == ["feasibility_review"]


def test_revoked_grant_fails_optional_waiting_node_and_continues_partial_plan(
    tmp_path,
    monkeypatch,
    configure_pilot_wiki,
) -> None:
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "execute")
    configure_pilot_wiki(tmp_path / "wiki")
    repository = SQLiteStore(tmp_path / "revoked-optional-grant.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    catalog = SkillCatalogService(repository)
    catalog.reload()
    skill = catalog.get_by_name("prd-feasibility", USER.personal_agent_id)
    assert skill is not None
    profile = repository.get_skill_capability_profile(skill.id)
    assert profile is not None
    repository.save_skill_capability_profile(
        profile.model_copy(update={"required_capabilities": ["research.request"]})
    )
    ensure_tool_seed_data(repository, granted_by="system")
    grant = next(
        item
        for item in repository.list_agent_tool_grants(USER.personal_agent_id)
        if item.tool_id == "tool_web_research"
    )
    required_node = SkillPlanNode(
        id="node_required_complete",
        skill_id="skill_required_complete",
        skill_version="1",
        skill_content_hash="hash_required_complete",
        reason="provide the required review",
        input_bindings=["user.prd"],
        output_contract=["feasibility_review"],
        status=SkillPlanNodeStatus.COMPLETED,
        attempt=1,
        completed_at=now_utc(),
    )
    optional_node = SkillPlanNode(
        id="node_optional_revoked_grant",
        skill_id=skill.id,
        skill_version=skill.version,
        skill_content_hash=skill.content_hash,
        reason="collect optional external evidence",
        required=False,
        input_bindings=["user.prd"],
        output_contract=["external_evidence"],
        side_effect=profile.side_effect,
        status=SkillPlanNodeStatus.WAITING_TOOL_APPROVAL,
        attempt=1,
    )
    dependent_node = SkillPlanNode(
        id="node_optional_dependent",
        skill_id="skill_optional_dependent",
        skill_version="1",
        skill_content_hash="hash_optional_dependent",
        reason="use the optional external evidence",
        required=False,
        depends_on=[optional_node.id],
        input_bindings=[f"{optional_node.id}.external_evidence"],
        output_contract=["evidence_followup"],
    )
    run = repository.save_agent_run(
        AgentRun(
            id="run_revoked_optional_grant",
            thread_id="thread_revoked_optional_grant",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="review this PRD with optional evidence",
            status=AgentRunStatus.WAITING_APPROVAL,
            plan_id="plan_revoked_optional_grant",
            paused_state={
                "kind": "skill_plan_node",
                "plan_id": "plan_revoked_optional_grant",
                "node_id": optional_node.id,
                "skill_id": skill.id,
                "skill_content_hash": skill.content_hash,
                "grant_snapshot_ids": [grant.id],
                "sdk_state": {},
                "expires_at": (now_utc() + timedelta(hours=24)).isoformat(),
            },
            deadline_at=now_utc() + timedelta(seconds=300),
        )
    )
    plan = repository.save_skill_plan(
        SkillPlan(
            id="plan_revoked_optional_grant",
            run_id=run.id,
            status=SkillPlanStatus.RUNNING,
            intent=SkillIntent(goal="review this PRD with optional evidence"),
            candidate_skill_ids=[skill.id],
            output_contract=["feasibility_review"],
            nodes=[required_node, optional_node, dependent_node],
        )
    )
    required_result = repository.save_skill_node_result(
        plan.id,
        SkillNodeResult(
            id="result_required_complete",
            node_id=required_node.id,
            skill_id=required_node.skill_id,
            summary="Required PRD review completed",
            attempt=required_node.attempt,
        ),
    )
    inbox = repository.add_inbox_item(
        InboxItem(
            id=f"inbox_tool_approval_{run.id}",
            title="Approve",
            summary="Waiting",
            item_type="sdk_tool_approval",
            scope=Scope.PRIVATE,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            metadata={
                "run_id": run.id,
                "interruptions": json.dumps([{"call_id": "revoked_optional_call"}]),
            },
        )
    )
    repository.save_agent_tool_grant(grant.model_copy(update={"enabled": False}))
    assert not any(
        item.enabled and item.tool_id == "tool_web_research"
        for item in repository.list_agent_tool_grants(USER.personal_agent_id)
    )
    model = ScriptedModel(
        [
            [
                assistant_message(
                    json.dumps(
                        {
                            "summary": "Required review retained without optional evidence",
                            "claims": [
                                {
                                    "text": "Required review completed",
                                    "node_result_ids": [required_result.id],
                                    "source_ids": [],
                                    "recommendation": True,
                                }
                            ],
                            "limitations": ["Optional external evidence was unavailable"],
                        }
                    )
                )
            ]
        ]
    )
    tool_calls: list[str] = []

    class GatewayStub:
        @staticmethod
        def handlers():
            def web_research(_context, _arguments):  # noqa: ANN001, ANN202
                tool_calls.append("web_research")
                return {"title": "unexpected", "sources": []}

            return {"web_research": web_research}

    runtime = AgentRuntimeService(
        repository,
        model=model,
        enabled=True,
        tool_factory=AgentMeshToolFactory(repository, gateway=GatewayStub()),  # type: ignore[arg-type]
        skill_catalog=catalog,
    )

    answer = runtime.resume_sync(run.id, user=USER, decisions={"revoked_optional_call": True})

    partial_run = repository.get_agent_run(run.id)
    partial_plan = repository.get_skill_plan(plan.id)
    assert answer.waiting_approval is False
    assert partial_run is not None and partial_run.status == AgentRunStatus.PARTIAL
    assert partial_plan is not None and partial_plan.status == SkillPlanStatus.PARTIAL
    assert {node.id: node.status for node in partial_plan.nodes} == {
        required_node.id: SkillPlanNodeStatus.COMPLETED,
        optional_node.id: SkillPlanNodeStatus.FAILED,
        dependent_node.id: SkillPlanNodeStatus.SKIPPED,
    }
    assert partial_plan.nodes[1].error_code == "planned_tool_grant_revoked"
    assert partial_plan.nodes[2].error_code == "dependency_failed"
    assert [result.id for result in repository.list_skill_node_results(plan.id)] == [required_result.id]
    assert repository.get_inbox_item(inbox.id).status == "resolved"  # type: ignore[union-attr]
    assert tool_calls == []
    event_types = [event.event_type for event in repository.list_agent_run_events(run.id)]
    assert "node_failed" in event_types
    assert "node_skipped" in event_types
    assert event_types[-2:] == ["synthesis_completed", "run_partial"]
    model.assert_complete()
