from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Literal

import pytest
from agents import OpenAIChatCompletionsModel

from agentmesh.agent_runtime.model_factory import SelectedSDKModel
from agentmesh.agent_runtime.structured_output import JSONObjectChatCompletionsModel, SDKStructuredOutputMode
from agentmesh.models import (
    AgentRun,
    AgentRunStatus,
    AgentToolGrant,
    Project,
    ToolDefinition,
    User,
    Workspace,
)
from agentmesh.research_orchestration.actors import (
    TOOL_ACTOR_OUTPUT_KIND,
    TOOL_ACTOR_OUTPUT_SCHEMA,
    ActorError,
    AgentsSdkSkillModelPort,
    SkillActor,
    StoreToolCapabilityGuard,
    ToolActor,
    ToolActorOutput,
    skill_call_key,
    tool_operation_key,
)
from agentmesh.research_orchestration.artifacts import ArtifactDraft
from agentmesh.research_orchestration.capabilities import MODEL_ADAPTER_COMPATIBILITY_IDS
from agentmesh.research_orchestration.compiler import PlanStepContract, validate_execution_plan_version
from agentmesh.research_orchestration.contracts import (
    InvocationState,
    ModelCallReceipt,
    canonical_sha256,
)
from agentmesh.research_orchestration.delivery import SKILL_RESULT_KIND, SKILL_RESULT_SCHEMA
from agentmesh.research_orchestration.ports import SkillGenerationContract, SkillModelResult, ToolPortResult
from agentmesh.tool_runtime.gateway import ToolRuntimeDescriptor
from tests.research_orchestration_testkit import ResearchExecutionContext, research_execution_context

VERIFIED_QUOTE = "京东提供带来源的研究摘要。"


@dataclass(frozen=True)
class FixedClock:
    current: datetime

    def now(self) -> datetime:
        return self.current


class RecordingToolPort:
    def __init__(
        self,
        repository,
        *,
        clock: FixedClock,
        expected_invocation_id: str,
        execution_mode: Literal["real", "fake"] = "real",
    ):
        self.repository = repository
        self.clock = clock
        self.expected_invocation_id = expected_invocation_id
        self.execution_mode = execution_mode
        self.calls = 0
        self.observed_states: list[InvocationState] = []

    def describe(self, tool_name: str) -> ToolRuntimeDescriptor | None:
        if tool_name != "web_research":
            return None
        return ToolRuntimeDescriptor(
            implementation_id="agentmesh.tool_runtime.gateway.ToolGateway.web_research",
            implementation_version="1",
            execution_mode=self.execution_mode,
            health_state="healthy",
            health_checked_at=self.clock.now(),
        )

    async def invoke(
        self,
        *,
        context,
        tool_name: str,
        arguments: dict[str, Any],
        operation_key: str,
    ) -> ToolPortResult:
        del tool_name, arguments
        assert len(operation_key) == 64
        self.calls += 1
        invocation = self.repository.get_research_tool_invocation(self.expected_invocation_id)
        assert invocation is not None
        self.observed_states.append(invocation.state)
        return ToolPortResult(
            payload={
                "title": "竞品研究",
                "content": VERIFIED_QUOTE,
                "sources": [
                    {
                        "id": "source_provider_1",
                        "title": "京东研究资料",
                        "source_type": "web_page",
                        "reference": "https://example.com/research",
                        "workspace_id": context.workspace_id,
                        "project_id": context.project_id,
                        "user_id": context.user_id,
                        "run_id": context.run_id,
                        "skill_id": context.skill_id,
                        "created_at": self.clock.now().isoformat(),
                    }
                ],
                "source_evidence": [
                    {
                        "source_id": "source_provider_1",
                        "content_provider": "web_real",
                        "excerpt": VERIFIED_QUOTE,
                        "retrieved_at": self.clock.now().isoformat(),
                        "content_hash": hashlib.sha256(VERIFIED_QUOTE.encode()).hexdigest(),
                        "truncated": False,
                        "risk_flags": [],
                        "question_ids": [],
                    }
                ],
                "provider_calls": [
                    {
                        "provider": "web_real",
                        "operation": "search",
                        "request_hash": hashlib.sha256(b"compare").hexdigest(),
                        "status": "success",
                        "latency_ms": 12,
                        "result_count": 1,
                        "error_code": None,
                    }
                ],
                "permission": "public",
                "metadata": {"actual_provider": "web_real", "mode": "real"},
            },
            transport_request_id="request_provider_1",
            provider_operation_id="operation_provider_1",
        )

    async def reconcile(
        self,
        *,
        operation_key: str,
        provider_operation_id: str | None,
    ) -> ToolPortResult | None:
        del operation_key, provider_operation_id
        return None


class RecordingSkillModelPort:
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        self.calls = 0
        self.evidence: list[dict[str, Any]] | None = None
        self.generation_contract: SkillGenerationContract | None = None

    async def generate(
        self,
        *,
        run: AgentRun,
        frozen_skill,
        model_policy,
        generation_contract: SkillGenerationContract,
        resolved_input: dict[str, Any],
        evidence: list[dict[str, Any]],
        resources: list[dict[str, str]],
        timeout_seconds: int,
    ) -> SkillModelResult:
        del run, frozen_skill, model_policy, resolved_input, resources, timeout_seconds
        self.calls += 1
        self.evidence = evidence
        self.generation_contract = generation_contract
        return SkillModelResult(
            payload=self.payload,
            requested_provider="openai_agents_sdk",
            requested_model="gpt-primary",
            actual_provider="openai_agents_sdk",
            actual_model="gpt-5.5",
            usage={"requests": 1, "total_tokens": 42},
            provider_receipt_id="response_1",
        )


class StaticResourceLoader:
    def load(self, run: AgentRun, frozen_skill, snapshot: object) -> list[dict[str, str]]:
        del run, frozen_skill, snapshot
        return [{"path": "methods/competitive-analysis.md", "content": "verified method"}]


class DriftedModelFactory:
    def __init__(self, selected: SelectedSDKModel):
        self.selected = selected
        self.calls = 0

    def for_user(self, user: User) -> SelectedSDKModel:
        del user
        self.calls += 1
        return self.selected


def _steps(context: ResearchExecutionContext) -> tuple[PlanStepContract, PlanStepContract]:
    body = validate_execution_plan_version(context.plan)
    return body.steps[0], body.steps[1]


def _authorize_runtime(context: ResearchExecutionContext) -> AgentRun:
    repository = context.repository
    repository.save_workspace(Workspace(id="workspace_1", name="Workspace", description="Test"))
    repository.save_project(
        Project(
            id="project_1",
            workspace_id="workspace_1",
            name="Project",
            goal="Test actors",
            member_ids=["user_1"],
        )
    )
    repository.save_user(
        User(
            id="user_1",
            workspace_id="workspace_1",
            default_project_id="project_1",
            name="Actor User",
            role="user",
            personal_agent_id="agent_user_1",
        )
    )
    run = repository.get_agent_run(context.plan.run_id)
    assert run is not None
    run = run.model_copy(update={"status": AgentRunStatus.RUNNING})
    repository.save_agent_run(run)
    frozen = validate_execution_plan_version(context.plan).control_snapshot.tool
    repository.save_tool_definition(
        ToolDefinition(
            id=frozen.tool_id,
            name=frozen.tool_name,
            description="Research",
            category="research",
            enabled=True,
            implementation_id=frozen.implementation_id,
            implementation_version=frozen.implementation_version,
            input_schema=frozen.input_schema.content,
            output_schema=frozen.output_schema.content,
        )
    )
    repository.save_agent_tool_grant(
        AgentToolGrant(
            id=frozen.grant_id,
            agent_id=frozen.granted_to_agent_id,
            tool_id=frozen.tool_id,
            enabled=True,
            granted_by="user_1",
        )
    )
    return run


def _tool_port(
    context: ResearchExecutionContext,
    step: PlanStepContract,
    clock: FixedClock,
    *,
    execution_mode: Literal["real", "fake"] = "real",
) -> RecordingToolPort:
    operation_key = tool_operation_key(context.plan, step, canonical_sha256(step.initial_input))
    return RecordingToolPort(
        context.repository,
        clock=clock,
        expected_invocation_id=f"invocation_{operation_key[:32]}",
        execution_mode=execution_mode,
    )


def _run_tool(
    context: ResearchExecutionContext,
    run: AgentRun,
    clock: FixedClock,
) -> tuple[ToolActorOutput, RecordingToolPort]:
    tool_step, _skill_step = _steps(context)
    port = _tool_port(context, tool_step, clock)
    actor = ToolActor(
        context.repository,
        context.artifacts,
        port,
        StoreToolCapabilityGuard(context.repository, port),
        clock=clock,
    )
    result = asyncio.run(
        actor.run(
            plan=context.plan,
            step=tool_step,
            resolved_input=tool_step.initial_input,
            lineage=context.lineage_step_1,
            lease=context.lease,
            run=run,
        )
    )
    artifact = context.artifacts.read_verified(
        result.output_ref,
        scope=context.lineage_step_1,
        expected_kind=TOOL_ACTOR_OUTPUT_KIND,
        expected_schema_version=TOOL_ACTOR_OUTPUT_SCHEMA,
    )
    return ToolActorOutput.model_validate_json(artifact.content), port


def _skill_input(step: PlanStepContract, tool_output: ToolActorOutput) -> dict[str, Any]:
    return {
        **step.initial_input,
        "evidence_inputs": [item.model_dump(mode="json") for item in tool_output.evidence_inputs],
    }


def _empty_skill_output() -> dict[str, Any]:
    return {
        "summary": "有来源的竞品研究结论。",
        "facts": [],
        "inferences": [],
        "recommendations": [],
        "gaps": [],
    }


def test_tool_provider_observes_sent_invocation_and_ack_replay_does_not_resend(tmp_path) -> None:
    context = research_execution_context(tmp_path / "tool-replay.sqlite3", run_id="run_tool_replay")
    run = _authorize_runtime(context)
    tool_step, _skill_step = _steps(context)
    clock = FixedClock(datetime.now(UTC))
    port = _tool_port(context, tool_step, clock)
    actor = ToolActor(
        context.repository,
        context.artifacts,
        port,
        StoreToolCapabilityGuard(context.repository, port),
        clock=clock,
    )
    arguments = dict(
        plan=context.plan,
        step=tool_step,
        resolved_input=tool_step.initial_input,
        lineage=context.lineage_step_1,
        lease=context.lease,
        run=run,
    )

    first = asyncio.run(actor.run(**arguments))
    replay = asyncio.run(actor.run(**arguments))

    assert port.calls == 1
    assert port.observed_states == [InvocationState.SENT]
    assert replay.output_ref == first.output_ref
    assert replay.invocation == first.invocation
    assert replay.invocation.state == InvocationState.ACKNOWLEDGED
    assert replay.invocation.last_sent_at == clock.now()
    assert replay.invocation.acknowledged_at == clock.now()


@pytest.mark.parametrize(
    ("runtime_change", "expected_code"),
    [
        ("fake", "tool_runtime_unavailable"),
        ("grant_revoked", "tool_grant_revoked"),
        ("implementation_drift", "tool_runtime_drifted"),
    ],
)
def test_tool_runtime_changes_are_rejected_before_provider_send(
    tmp_path,
    runtime_change: str,
    expected_code: str,
) -> None:
    context = research_execution_context(
        tmp_path / f"tool-gate-{runtime_change}.sqlite3",
        run_id=f"run_tool_gate_{runtime_change}",
    )
    run = _authorize_runtime(context)
    tool_step, _skill_step = _steps(context)
    clock = FixedClock(datetime.now(UTC))
    port = _tool_port(
        context,
        tool_step,
        clock,
        execution_mode="fake" if runtime_change == "fake" else "real",
    )
    frozen = validate_execution_plan_version(context.plan).control_snapshot.tool
    if runtime_change == "grant_revoked":
        context.repository.save_agent_tool_grant(
            AgentToolGrant(
                id=frozen.grant_id,
                agent_id=frozen.granted_to_agent_id,
                tool_id=frozen.tool_id,
                enabled=False,
                granted_by="user_1",
            )
        )
    elif runtime_change == "implementation_drift":
        live = context.repository.get_tool_definition(frozen.tool_id)
        assert live is not None
        context.repository.save_tool_definition(live.model_copy(update={"implementation_version": "2"}))
    actor = ToolActor(
        context.repository,
        context.artifacts,
        port,
        StoreToolCapabilityGuard(context.repository, port),
        clock=clock,
    )

    with pytest.raises(ActorError) as denied:
        asyncio.run(
            actor.run(
                plan=context.plan,
                step=tool_step,
                resolved_input=tool_step.initial_input,
                lineage=context.lineage_step_1,
                lease=context.lease,
                run=run,
            )
        )

    assert denied.value.code == expected_code
    assert port.calls == 0
    assert context.repository.get_research_tool_invocation(port.expected_invocation_id) is None


def test_skill_model_receives_only_verified_quote_view(tmp_path) -> None:
    context = research_execution_context(tmp_path / "verified-quote.sqlite3", run_id="run_verified_quote")
    run = _authorize_runtime(context)
    clock = FixedClock(datetime.now(UTC))
    tool_output, _tool_port_instance = _run_tool(context, run, clock)
    _tool_step, skill_step = _steps(context)
    model_port = RecordingSkillModelPort(_empty_skill_output())
    actor = SkillActor(
        context.repository,
        context.artifacts,
        model_port,
        StaticResourceLoader(),
        clock=clock,
    )

    asyncio.run(
        actor.run(
            plan=context.plan,
            step=skill_step,
            resolved_input=_skill_input(skill_step, tool_output),
            tool_output=tool_output,
            evidence_lineage=context.lineage_step_1,
            skill_lineage=context.lineage_step_2,
            lease=context.lease,
            run=run,
        )
    )

    assert model_port.evidence == [
        {
            "evidence_id": tool_output.evidence_inputs[0].evidence_id,
            "quote": VERIFIED_QUOTE,
            "source_tier": "provider_summary",
            "question_ids": [],
            "conflict_status": "unknown",
            "risk_flags": [],
            "sources": [
                {
                    "title": "京东研究资料",
                    "canonical_url": "https://example.com/research",
                }
            ],
        }
    ]
    assert "permission" not in json.dumps(model_port.evidence)
    assert "request_provider_1" not in json.dumps(model_port.evidence)
    body = validate_execution_plan_version(context.plan)
    assert model_port.generation_contract == SkillGenerationContract(
        problem_contract=body.problem_contract,
        evidence_policy=body.control_snapshot.evidence_policy,
        review_rubric=body.control_snapshot.review_rubric,
    )


def test_sdk_model_input_contains_the_frozen_problem_contract(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = research_execution_context(tmp_path / "model-coverage-contract.sqlite3", run_id="run_model_coverage")
    run = _authorize_runtime(context)
    body = validate_execution_plan_version(context.plan)
    policy = body.control_snapshot.model_policy
    factory = DriftedModelFactory(
        SelectedSDKModel(
            model=object.__new__(OpenAIChatCompletionsModel),
            requested_model=policy.requested_model_id,
            actual_model="provider-model",
            structured_output_mode=SDKStructuredOutputMode(policy.structured_output_mode),
        )
    )
    captured: dict[str, Any] = {}
    provider_calls = 0

    async def provider_call(agent, model_input, **kwargs):  # noqa: ANN001, ANN003, ANN202
        nonlocal provider_calls
        provider_calls += 1
        del kwargs
        captured["instructions"] = agent.instructions
        captured["model_input"] = json.loads(model_input)
        output = _empty_skill_output()
        output["facts"] = [
            {
                "claim_id": "claim_direct_fact",
                "statement": "A directly observed fact.",
                "evidence_ids": ["evidence_1"],
                "parent_claim_ids": [],
                "question_ids": ["q_evidence_comparison"],
                "success_criterion_ids": ["sc_evidence_comparison"],
                "confidence": "medium",
                "conflict_status": "unknown",
            },
            {
                "claim_id": "claim_parent_backed_fact",
                "statement": "A derived statement incorrectly labelled as a fact.",
                "evidence_ids": [],
                "parent_claim_ids": ["claim_direct_fact"],
                "question_ids": ["q_evidence_comparison"],
                "success_criterion_ids": ["sc_evidence_comparison"],
                "confidence": "medium",
                "conflict_status": "unknown",
            },
        ]
        return SimpleNamespace(
            final_output=output,
            context_wrapper=None,
            raw_responses=[],
        )

    monkeypatch.setattr("agentmesh.research_orchestration.actors.Runner.run", provider_call)
    model_port = AgentsSdkSkillModelPort(context.repository, factory)
    generation_contract = SkillGenerationContract(
        problem_contract=body.problem_contract,
        evidence_policy=body.control_snapshot.evidence_policy,
        review_rubric=body.control_snapshot.review_rubric,
    )

    result = asyncio.run(
        model_port.generate(
            run=run,
            frozen_skill=body.control_snapshot.skill,
            model_policy=policy,
            generation_contract=generation_contract,
            resolved_input={"brief": "compare"},
            evidence=[],
            resources=[],
            timeout_seconds=30,
        )
    )

    assert captured["model_input"]["frozen_problem_contract"] == body.problem_contract.model_dump(mode="json")
    assert captured["model_input"]["frozen_output_governance"] == {
        "evidence_policy": body.control_snapshot.evidence_policy.content,
        "review_rubric": body.control_snapshot.review_rubric.content,
    }
    assert "question_ids and success_criterion_ids" in captured["instructions"]
    assert "Facts must cite evidence_ids directly and must use an empty parent_claim_ids list" in captured["instructions"]
    assert "Inferences must cite evidence_ids or parent_claim_ids" in captured["instructions"]
    assert "Recommendations must cite at least one parent_claim_id" in captured["instructions"]
    assert "maximum_confidence" in captured["instructions"]
    assert "possible or conflicting" in captured["instructions"]
    assert captured["model_input"]["repair_error_codes"] == ["missing_fact_claim:q_scenarios"]
    assert captured["model_input"]["previous_output"]["facts"][0]["claim_id"] == "claim_direct_fact"
    assert provider_calls == 2
    assert result.usage["repair_attempts"] == 1
    assert [claim["claim_id"] for claim in result.payload["facts"]] == ["claim_direct_fact"]
    assert [claim["claim_id"] for claim in result.payload["inferences"]] == ["claim_parent_backed_fact"]


def test_skill_rejects_model_output_with_forged_evidence_id(tmp_path) -> None:
    context = research_execution_context(tmp_path / "forged-evidence.sqlite3", run_id="run_forged_evidence")
    run = _authorize_runtime(context)
    clock = FixedClock(datetime.now(UTC))
    tool_output, _tool_port_instance = _run_tool(context, run, clock)
    body = validate_execution_plan_version(context.plan)
    skill_step = body.steps[1]
    model_port = RecordingSkillModelPort(
        {
            "summary": "伪造引用",
            "facts": [
                {
                    "claim_id": "claim_forged",
                    "statement": "没有来源支持的事实",
                    "evidence_ids": ["evidence_forged"],
                    "parent_claim_ids": [],
                    "question_ids": [skill_step.question_ids[0]],
                    "success_criterion_ids": [body.problem_contract.success_criterion_ids[0]],
                    "confidence": "high",
                    "conflict_status": "none",
                }
            ],
            "inferences": [],
            "recommendations": [],
            "gaps": [],
        }
    )
    actor = SkillActor(
        context.repository,
        context.artifacts,
        model_port,
        StaticResourceLoader(),
        clock=clock,
    )

    with pytest.raises(ActorError) as denied:
        asyncio.run(
            actor.run(
                plan=context.plan,
                step=skill_step,
                resolved_input=_skill_input(skill_step, tool_output),
                tool_output=tool_output,
                evidence_lineage=context.lineage_step_1,
                skill_lineage=context.lineage_step_2,
                lease=context.lease,
                run=run,
            )
        )

    assert denied.value.code == "skill_output_unknown_evidence"
    assert model_port.calls == 1


@pytest.mark.parametrize("drift", ["model_id", "structured_output_mode", "adapter"])
def test_skill_rejects_frozen_model_policy_drift_before_provider_call(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    context = research_execution_context(
        tmp_path / f"model-drift-{drift}.sqlite3",
        run_id=f"run_model_drift_{drift}",
    )
    run = _authorize_runtime(context)
    clock = FixedClock(datetime.now(UTC))
    tool_output, _tool_port_instance = _run_tool(context, run, clock)
    body = validate_execution_plan_version(context.plan)
    policy = body.control_snapshot.model_policy
    requested_model = policy.requested_model_id
    structured_output_mode = SDKStructuredOutputMode(policy.structured_output_mode)
    if drift == "model_id":
        requested_model = "gpt-drifted"
    elif drift == "structured_output_mode":
        structured_output_mode = (
            SDKStructuredOutputMode.JSON_OBJECT
            if structured_output_mode == SDKStructuredOutputMode.JSON_SCHEMA
            else SDKStructuredOutputMode.JSON_SCHEMA
        )
    elif drift == "adapter":
        monkeypatch.setitem(
            MODEL_ADAPTER_COMPATIBILITY_IDS,
            structured_output_mode.value,
            "openai-agents-sdk.adapter-drifted:v2",
        )
    model_type = (
        JSONObjectChatCompletionsModel
        if structured_output_mode == SDKStructuredOutputMode.JSON_OBJECT
        else OpenAIChatCompletionsModel
    )
    factory = DriftedModelFactory(
        SelectedSDKModel(
            model=object.__new__(model_type),
            requested_model=requested_model,
            actual_model="provider-model",
            structured_output_mode=structured_output_mode,
        )
    )
    provider_calls = 0

    async def provider_call(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        nonlocal provider_calls
        del args, kwargs
        provider_calls += 1
        raise AssertionError("provider must not be called")

    monkeypatch.setattr("agentmesh.research_orchestration.actors.Runner.run", provider_call)
    model_port = AgentsSdkSkillModelPort(context.repository, factory)
    actor = SkillActor(
        context.repository,
        context.artifacts,
        model_port,
        StaticResourceLoader(),
        clock=clock,
    )
    skill_step = body.steps[1]

    with pytest.raises(ActorError) as denied:
        asyncio.run(
            actor.run(
                plan=context.plan,
                step=skill_step,
                resolved_input=_skill_input(skill_step, tool_output),
                tool_output=tool_output,
                evidence_lineage=context.lineage_step_1,
                skill_lineage=context.lineage_step_2,
                lease=context.lease,
                run=run,
            )
        )

    assert denied.value.code == "model_policy_drifted"
    assert factory.calls == 1
    assert provider_calls == 0


def test_skill_settlement_replay_does_not_call_model_again(tmp_path) -> None:
    context = research_execution_context(tmp_path / "skill-replay.sqlite3", run_id="run_skill_replay")
    run = _authorize_runtime(context)
    clock = FixedClock(datetime.now(UTC))
    tool_output, _tool_port_instance = _run_tool(context, run, clock)
    _tool_step, skill_step = _steps(context)
    resolved_input = _skill_input(skill_step, tool_output)
    model_port = RecordingSkillModelPort(_empty_skill_output())
    actor = SkillActor(
        context.repository,
        context.artifacts,
        model_port,
        StaticResourceLoader(),
        clock=clock,
    )
    arguments = dict(
        plan=context.plan,
        step=skill_step,
        resolved_input=resolved_input,
        tool_output=tool_output,
        evidence_lineage=context.lineage_step_1,
        skill_lineage=context.lineage_step_2,
        lease=context.lease,
        run=run,
    )

    first = asyncio.run(actor.run(**arguments))
    replay = asyncio.run(actor.run(**arguments))

    call_key = skill_call_key(context.plan, skill_step, canonical_sha256(resolved_input))
    assert model_port.calls == 1
    assert replay == first
    assert replay.receipt.call_key == call_key
    assert replay.receipt.created_at == clock.now()


@pytest.mark.parametrize("settled_side", ["artifact", "receipt"])
def test_skill_partial_settlement_fails_closed_without_calling_model(tmp_path, settled_side: str) -> None:
    context = research_execution_context(
        tmp_path / f"skill-partial-{settled_side}.sqlite3",
        run_id=f"run_skill_partial_{settled_side}",
    )
    run = _authorize_runtime(context)
    clock = FixedClock(datetime.now(UTC))
    tool_output, _tool_port_instance = _run_tool(context, run, clock)
    _tool_step, skill_step = _steps(context)
    resolved_input = _skill_input(skill_step, tool_output)
    call_key = skill_call_key(context.plan, skill_step, canonical_sha256(resolved_input))
    if settled_side == "artifact":
        context.artifacts.seal(
            context.lineage_step_2,
            ArtifactDraft(
                artifact_id=f"artifact_skill_result_{call_key[:32]}",
                kind=SKILL_RESULT_KIND,
                schema_version=SKILL_RESULT_SCHEMA,
                content=_empty_skill_output(),
            ),
            lease=context.lease,
        )
    else:
        context.repository.add_research_model_call_receipt(
            ModelCallReceipt(
                id=f"model_call_{call_key[:32]}",
                run_id=context.plan.run_id,
                owner_kind="attempt",
                owner_id=context.lineage_step_2.attempt_id or "",
                stage="competitive-analysis",
                call_key=call_key,
                actual_provider="openai_agents_sdk",
                actual_model="gpt-5.5",
                created_at=clock.now(),
            )
        )
    model_port = RecordingSkillModelPort(_empty_skill_output())
    actor = SkillActor(
        context.repository,
        context.artifacts,
        model_port,
        StaticResourceLoader(),
        clock=clock,
    )

    with pytest.raises(ActorError) as denied:
        asyncio.run(
            actor.run(
                plan=context.plan,
                step=skill_step,
                resolved_input=resolved_input,
                tool_output=tool_output,
                evidence_lineage=context.lineage_step_1,
                skill_lineage=context.lineage_step_2,
                lease=context.lease,
                run=run,
            )
        )

    assert denied.value.code == "skill_model_settlement_conflict"
    assert model_port.calls == 0
