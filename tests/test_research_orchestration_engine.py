from __future__ import annotations

import asyncio
import copy
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from research_orchestration_testkit import compiled_competitive_plan, research_execution_context

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
    SkillActor,
    StoreToolCapabilityGuard,
    ToolActor,
)
from agentmesh.research_orchestration.api import ResearchOwnerScope, ResearchRecoverRequest
from agentmesh.research_orchestration.compiler import FrozenModelPolicy, validate_execution_plan_version
from agentmesh.research_orchestration.contracts import AttemptStatus, InvocationState, ResearchGate, ResearchPhase
from agentmesh.research_orchestration.delivery import ResultPipeline
from agentmesh.research_orchestration.execution import ExecutionEngine, ExecutionError, resolve_step_input
from agentmesh.research_orchestration.ports import SkillModelResult, ToolPortResult
from agentmesh.research_orchestration.workflow import ResearchWorkflowService
from agentmesh.tool_runtime.gateway import ToolRuntimeDescriptor


@dataclass(frozen=True)
class _FixedClock:
    current: datetime

    def now(self) -> datetime:
        return self.current


class _ToolPort:
    def __init__(self, clock: _FixedClock, *, fail_calls: int = 0):
        self.clock = clock
        self.calls = 0
        self.fail_calls = fail_calls

    def describe(self, tool_name: str) -> ToolRuntimeDescriptor | None:
        if tool_name != "web_research":
            return None
        return ToolRuntimeDescriptor(
            implementation_id="agentmesh.tool_runtime.gateway.ToolGateway.web_research",
            implementation_version="1",
            execution_mode="real",
            health_state="healthy",
            health_checked_at=self.clock.now(),
        )

    async def invoke(
        self,
        *,
        context,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolPortResult:
        del tool_name, arguments
        self.calls += 1
        if self.calls <= self.fail_calls:
            raise TimeoutError("provider response was lost")
        return ToolPortResult(
            payload={
                "title": "Competitive research",
                "content": "Alpha emphasizes traceability; Beta emphasizes recovery.",
                "sources": [
                    {
                        "id": f"source_{index}",
                        "title": f"Source {index}",
                        "source_type": "web_page",
                        "reference": url,
                        "workspace_id": context.workspace_id,
                        "project_id": context.project_id,
                        "user_id": context.user_id,
                        "run_id": context.run_id,
                        "skill_id": context.skill_id,
                        "created_at": self.clock.now().isoformat(),
                    }
                    for index, url in enumerate(
                        ("https://alpha.example/research", "https://beta.example/report"),
                        start=1,
                    )
                ],
                "permission": "project_visible",
                "metadata": {"actual_provider": "test-web", "mode": "real"},
            },
            transport_request_id="request_engine",
            provider_operation_id="operation_engine",
        )

    async def reconcile(
        self,
        *,
        operation_key: str,
        provider_operation_id: str | None,
    ) -> ToolPortResult | None:
        del operation_key, provider_operation_id
        return None


class _ModelPort:
    def __init__(self, *, forge_evidence: bool = False):
        self.calls = 0
        self.forge_evidence = forge_evidence

    async def generate(
        self,
        *,
        run: AgentRun,
        frozen_skill,
        model_policy: FrozenModelPolicy,
        resolved_input: dict[str, Any],
        evidence: list[dict[str, Any]],
        resources: list[dict[str, str]],
        timeout_seconds: int,
    ) -> SkillModelResult:
        del run, frozen_skill, resolved_input, resources, timeout_seconds
        self.calls += 1
        evidence_id = evidence[0]["evidence_id"]
        if self.forge_evidence:
            evidence_id = "evidence_forged"
        return SkillModelResult(
            payload={
                "summary": "Traceability and recovery differ.",
                "facts": [
                    {
                        "claim_id": "claim_fact_traceability",
                        "statement": "The products expose different traceability and recovery mechanisms.",
                        "evidence_ids": [evidence_id],
                        "parent_claim_ids": [],
                        "question_ids": ["q_evidence_comparison", "q_scenarios"],
                        "success_criterion_ids": ["sc_evidence_comparison", "sc_scenarios"],
                        "confidence": "medium",
                        "conflict_status": "unknown",
                    }
                ],
                "inferences": [
                    {
                        "claim_id": "claim_inference_scenarios",
                        "statement": "Teams may prefer different products by risk profile.",
                        "evidence_ids": [evidence_id],
                        "parent_claim_ids": ["claim_fact_traceability"],
                        "question_ids": ["q_scenarios"],
                        "success_criterion_ids": ["sc_scenarios"],
                        "confidence": "medium",
                        "conflict_status": "unknown",
                    }
                ],
                "recommendations": [
                    {
                        "claim_id": "claim_recommendation_pilot",
                        "statement": "Run a bounded pilot against the highest-risk workflow.",
                        "evidence_ids": [],
                        "parent_claim_ids": ["claim_inference_scenarios"],
                        "question_ids": ["q_recommendations"],
                        "success_criterion_ids": ["sc_recommendations"],
                        "confidence": "low",
                        "conflict_status": "unknown",
                    }
                ],
                "gaps": [],
            },
            requested_provider="openai_agents_sdk",
            requested_model=model_policy.requested_model_id,
            actual_provider="test-model",
            actual_model="gpt-test",
            usage={"requests": 1, "total_tokens": 42},
            provider_receipt_id="response_engine",
        )


class _ResourceLoader:
    def load(self, run: AgentRun, frozen_skill, snapshot: object) -> list[dict[str, str]]:
        del run, frozen_skill, snapshot
        return [{"path": "methods/toolbox/analysis/competitive-analysis.md", "content": "method"}]


def _authorize_execution(context) -> AgentRun:  # noqa: ANN001
    repository = context.repository
    repository.save_workspace(Workspace(id="workspace_1", name="Workspace", description="Test"))
    repository.save_project(
        Project(
            id="project_1",
            workspace_id="workspace_1",
            name="Project",
            goal="Test execution",
            member_ids=["user_1"],
        )
    )
    repository.save_user(
        User(
            id="user_1",
            workspace_id="workspace_1",
            default_project_id="project_1",
            name="Execution User",
            role="user",
            personal_agent_id="agent_user_1",
        )
    )
    run = repository.get_agent_run(context.plan.run_id)
    assert run is not None
    run.status = AgentRunStatus.RUNNING
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
            granted_by=run.user_id,
        )
    )
    return run


def _engine(  # noqa: ANN001, ANN202
    context,
    clock: _FixedClock,
    *,
    forge_evidence: bool = False,
    fail_tool_calls: int = 0,
):
    tool_port = _ToolPort(clock, fail_calls=fail_tool_calls)
    model_port = _ModelPort(forge_evidence=forge_evidence)
    engine = ExecutionEngine(
        context.repository,
        context.artifacts,
        ToolActor(
            context.repository,
            context.artifacts,
            tool_port,
            StoreToolCapabilityGuard(context.repository, tool_port),
            clock=clock,
        ),
        SkillActor(
            context.repository,
            context.artifacts,
            model_port,
            _ResourceLoader(),
            clock=clock,
        ),
        ResultPipeline(context.artifacts),
        clock=clock,
    )
    return engine, tool_port, model_port


def _skill_contract_and_schema():
    _requirement, plan = compiled_competitive_plan("run_engine_binding")
    return plan.payload["steps"][1], plan.payload["control_snapshot"]["skill"]["input_schema"]["content"]


def test_resolve_step_input_copies_only_the_frozen_binding_value() -> None:
    contract_payload, schema = _skill_contract_and_schema()
    from agentmesh.research_orchestration.compiler import PlanStepContract

    contract = PlanStepContract.model_validate(contract_payload)
    upstream = {
        1: {
            "evidence_inputs": [
                {
                    "evidence_id": "evidence_abc123",
                    "artifact_id": "artifact_evidence_1",
                    "content_hash": "a" * 64,
                    "evidence_pointer": "/quote",
                }
            ],
            "evidence_manifest_ref": {
                "artifact_id": "artifact_manifest_1",
                "content_hash": "b" * 64,
            },
        }
    }
    original = copy.deepcopy(upstream)

    resolved = resolve_step_input(contract, upstream=upstream, input_schema=schema)

    assert resolved["evidence_inputs"] == upstream[1]["evidence_inputs"]
    assert "evidence_manifest_ref" not in resolved
    assert upstream == original


@pytest.mark.parametrize(
    ("target", "code"),
    [
        ("/research_goal", "binding_target_already_set"),
        ("/missing/child", "binding_target_parent_missing"),
        ("/evidence~2inputs", "binding_pointer_invalid"),
    ],
)
def test_resolve_step_input_rejects_unsafe_binding_targets(target: str, code: str) -> None:
    contract_payload, schema = _skill_contract_and_schema()
    contract_payload = copy.deepcopy(contract_payload)
    contract_payload["input_bindings"][0]["target_pointer"] = target
    contract_payload_without_hash = {key: value for key, value in contract_payload.items() if key != "contract_hash"}
    from agentmesh.research_orchestration.compiler import PlanStepContract
    from agentmesh.research_orchestration.contracts import canonical_sha256

    contract_payload["contract_hash"] = canonical_sha256(contract_payload_without_hash)
    contract = PlanStepContract.model_validate(contract_payload)
    upstream = {1: {"evidence_inputs": []}}

    with pytest.raises(ExecutionError, match=code):
        resolve_step_input(contract, upstream=upstream, input_schema=schema)


def test_resolve_step_input_validates_the_frozen_schema_after_binding() -> None:
    contract_payload, schema = _skill_contract_and_schema()
    from agentmesh.research_orchestration.compiler import PlanStepContract

    contract = PlanStepContract.model_validate(contract_payload)

    with pytest.raises(ExecutionError, match="resolved_input_schema_invalid"):
        resolve_step_input(
            contract,
            upstream={1: {"evidence_inputs": [{"evidence_id": "forged"}]}},
            input_schema=schema,
        )


def test_execution_engine_runs_tool_skill_delivery_and_strict_finish(tmp_path) -> None:
    context = research_execution_context(tmp_path / "engine-e2e.sqlite3", run_id="run_engine_e2e")
    _authorize_execution(context)
    clock = _FixedClock(datetime.now(UTC))
    engine, tool_port, model_port = _engine(context, clock)

    outcome = asyncio.run(engine.run(context.lineage_step_1.attempt_id or "", context.lease))

    assert outcome.terminal_status == AgentRunStatus.COMPLETED
    assert outcome.delivery.status == "pass"
    assert outcome.delivery.report_ref is not None
    assert outcome.gap_codes == []
    assert tool_port.calls == model_port.calls == 1
    run = context.repository.get_agent_run(context.plan.run_id)
    workflow = context.repository.get_research_workflow(context.plan.run_id)
    attempt = context.repository.get_research_attempt(context.lineage_step_1.attempt_id or "")
    assert run is not None and run.status == AgentRunStatus.COMPLETED and run.output_text
    assert workflow is not None and workflow.phase.value == "terminal"
    assert attempt is not None and attempt.status.value == "completed" and attempt.lease_owner is None


def test_execution_engine_fails_closed_on_forged_model_evidence(tmp_path) -> None:
    context = research_execution_context(tmp_path / "engine-failure.sqlite3", run_id="run_engine_failure")
    _authorize_execution(context)
    clock = _FixedClock(datetime.now(UTC))
    engine, _tool_port, _model_port = _engine(context, clock, forge_evidence=True)

    with pytest.raises(ExecutionError, match="skill_output_unknown_evidence"):
        asyncio.run(engine.run(context.lineage_step_1.attempt_id or "", context.lease))

    run = context.repository.get_agent_run(context.plan.run_id)
    attempt = context.repository.get_research_attempt(context.lineage_step_1.attempt_id or "")
    step = context.repository.get_research_step(context.lineage_step_1.attempt_id or "", 2)
    assert run is not None and run.status == AgentRunStatus.FAILED
    assert attempt is not None and attempt.status.value == "failed" and attempt.lease_owner is None
    assert step is not None and step.status.value == "failed"


def test_execution_engine_recovers_an_expired_attempt_under_a_new_fence(tmp_path) -> None:
    context = research_execution_context(tmp_path / "engine-recovery.sqlite3", run_id="run_engine_recovery")
    _authorize_execution(context)
    clock = _FixedClock(datetime.now(UTC))
    attempt = context.repository.get_research_attempt(context.lineage_step_1.attempt_id or "")
    assert attempt is not None
    expired = attempt.model_copy(update={"lease_expires_at": clock.now(), "updated_at": clock.now()})
    with sqlite3.connect(context.repository.db_path) as connection:
        connection.execute(
            "UPDATE research_attempts SET lease_expires_at = ?, payload = ?, updated_at = ? WHERE id = ?",
            (clock.now().isoformat(), expired.model_dump_json(), clock.now().isoformat(), expired.id),
        )
    engine, tool_port, model_port = _engine(context, clock)

    recovered = asyncio.run(engine.recover_expired())

    assert len(recovered) == 1
    assert recovered[0].error_code is None
    assert recovered[0].outcome is not None
    assert recovered[0].outcome.terminal_status == AgentRunStatus.COMPLETED
    assert tool_port.calls == model_port.calls == 1
    finished = context.repository.get_research_attempt(expired.id)
    assert finished is not None and finished.fencing_epoch == 2 and finished.status.value == "completed"


def test_manual_retry_reuses_request_and_real_engine_completes_new_attempt(tmp_path) -> None:
    context = research_execution_context(tmp_path / "engine-manual-retry.sqlite3", run_id="run_engine_manual_retry")
    _authorize_execution(context)
    clock = _FixedClock(datetime.now(UTC))
    engine, tool_port, model_port = _engine(context, clock, fail_tool_calls=1)
    old_attempt_id = context.lineage_step_1.attempt_id or ""

    with pytest.raises(ExecutionError, match="tool_result_unknown"):
        asyncio.run(engine.run(old_attempt_id, context.lease))

    unknown = context.repository.enter_research_recovery_decision(
        old_attempt_id,
        error_code="tool_result_unknown",
        now=clock.now(),
    )
    assert unknown is not None and unknown.state == InvocationState.UNKNOWN
    original_request = context.repository.get_artifact(unknown.request_artifact_id)
    assert original_request is not None and original_request.attempt_id == old_attempt_id
    recovery_workflow = context.repository.get_research_workflow(context.plan.run_id)
    assert recovery_workflow is not None
    assert recovery_workflow.active_gate == ResearchGate.RECOVERY_DECISION
    service = ResearchWorkflowService(
        context.repository,
        planning=None,  # type: ignore[arg-type]
        execution=engine,
        purger=context.artifacts,
        clock=clock,
    )

    async def retry() -> None:
        await service.recover(
            context.plan.run_id,
            ResearchRecoverRequest(
                expected_state_version=recovery_workflow.state_version,
                invocation_id=unknown.id,
                action="retry",
            ),
            owner=ResearchOwnerScope(
                user_id="user_1",
                workspace_id="workspace_1",
                project_id="project_1",
            ),
            idempotency_key="retry-real-engine",
        )
        await service.wait_for_idle()

    asyncio.run(retry())

    run = context.repository.get_agent_run(context.plan.run_id)
    workflow = context.repository.get_research_workflow(context.plan.run_id)
    retried = context.repository.get_research_tool_invocation(unknown.id)
    assert run is not None and run.status == AgentRunStatus.COMPLETED
    assert workflow is not None and workflow.phase == ResearchPhase.TERMINAL
    assert workflow.active_attempt_id is not None and workflow.active_attempt_id != old_attempt_id
    new_attempt = context.repository.get_research_attempt(workflow.active_attempt_id)
    old_attempt = context.repository.get_research_attempt(old_attempt_id)
    assert new_attempt is not None and new_attempt.status == AttemptStatus.COMPLETED
    assert old_attempt is not None and old_attempt.status == AttemptStatus.FAILED
    assert retried is not None and retried.state == InvocationState.ACKNOWLEDGED
    assert retried.id == unknown.id and retried.operation_key == unknown.operation_key
    assert retried.send_count == retried.active_send_sequence == 2
    assert retried.receipt is not None and retried.receipt.send_sequence == 2
    assert retried.request_artifact_id == original_request.id
    assert context.repository.get_artifact(retried.request_artifact_id).attempt_id == old_attempt_id
    assert retried.artifact_id is not None
    assert context.repository.get_artifact(retried.artifact_id).attempt_id == new_attempt.id
    assert tool_port.calls == 2
    assert model_port.calls == 1
