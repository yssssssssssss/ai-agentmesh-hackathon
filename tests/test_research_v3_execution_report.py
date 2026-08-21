from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime

import pytest

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.catalog import load_competitive_text_catalog
from agentmesh.research_orchestration.v3.common import SealedArtifactRefV3
from agentmesh.research_orchestration.v3.delivery_service import (
    CompetitiveDeliverableDraftV3,
    CompetitiveTextDeliverableService,
)
from agentmesh.research_orchestration.v3.evidence import VerifiedArtifactContentV3
from agentmesh.research_orchestration.v3.evidence_materializer import EvidenceManifestMaterializer
from agentmesh.research_orchestration.v3.execution import (
    ExecutionRecoveryStateMachine,
    HeterogeneousActorDispatcher,
    RecoveryPauseReason,
    RecoveryStatus,
    RecoveryTransitionError,
    StepExecutionStatus,
    WaveExecutionEngine,
)
from agentmesh.research_orchestration.v3.execution_plan import ExecutionPlanV3, ExecutionPlanVersionV3
from agentmesh.research_orchestration.v3.in_memory import (
    InMemoryAppendError,
    InMemoryArtifactReadAdapter,
    InMemoryResearchV3Repository,
)
from agentmesh.research_orchestration.v3.ports import ActorExecutionRequestV3, ActorExecutionResultV3
from agentmesh.research_orchestration.v3.problem_graph import ProblemGraphV1
from agentmesh.research_orchestration.v3.report_composition import (
    CompetitiveTextReportCompositionService,
    ReportCompositionError,
)
from agentmesh.research_orchestration.v3.report_document import COMPETITIVE_TEXT_SECTION_ORDER
from agentmesh.research_orchestration.v3.requirement import RequirementVersionV3
from agentmesh.research_orchestration.v3.review import (
    REVIEW_DIMENSIONS,
    PassedReportReviewV3,
    ReviewDimensionV3,
)
from agentmesh.research_orchestration.v3.review_service import (
    ReportReviewService,
    SemanticReviewResultV3,
)
from tests.research_v3_contract_samples import (
    HASH,
    deliverable_body,
    evidence_artifact_content,
    plan_body,
    problem_graph_body,
    requirement_envelope,
)

NOW = datetime(2026, 8, 21, 0, 10, tzinfo=UTC)


def _plan_version(body: dict | None = None) -> ExecutionPlanVersionV3:
    payload = ExecutionPlanV3.model_validate(body or plan_body())
    return ExecutionPlanVersionV3.model_validate(
        {
            "id": "plan_1",
            "run_id": "run_1",
            "requirement_version_id": "requirement_1",
            "version": 1,
            "schema_version": "execution-plan-v3",
            "plan_hash": canonical_json_v3_sha256(payload),
            "payload": payload,
            "created_at": "2026-08-21T00:05:00Z",
        }
    )


def _step(
    number: int,
    *,
    actor_type: str,
    actor_id: str,
    required: bool,
    depends_on: list[int],
) -> dict:
    semantics = {
        "tool": "tool_read",
        "skill": "skill_once",
        "llm": "llm_once",
        "reviewer": "reviewer_once",
    }
    step = {
        "step_number": number,
        "name": f"Step {number}",
        "actor_type": actor_type,
        "actor_id": actor_id,
        "question_ids": ["q_capabilities"],
        "depends_on": depends_on,
        "input": {"step": number},
        "input_bindings": [],
        "expected_outputs": [{"pointer": "/result", "description": "Result"}],
        "acceptance_criteria": ["Return a valid result."],
        "required": required,
        "requires_approval": False,
        "approval_role": None,
        "timeout_seconds": 30,
        "max_sends": 1,
        "invocation_semantics": semantics[actor_type],
        "actor_snapshot_hash": HASH,
        "input_schema_hash": HASH,
        "output_schema_hash": HASH,
    }
    step["contract_hash"] = canonical_json_v3_sha256(step)
    return step


def _heterogeneous_plan() -> ExecutionPlanVersionV3:
    body = plan_body()
    body["steps"] = [
        _step(1, actor_type="tool", actor_id="tool_1", required=True, depends_on=[]),
        _step(2, actor_type="skill", actor_id="skill_1", required=False, depends_on=[]),
        _step(3, actor_type="llm", actor_id="llm_1", required=True, depends_on=[]),
        _step(4, actor_type="reviewer", actor_id="reviewer_1", required=True, depends_on=[1, 2, 3]),
    ]
    return _plan_version(body)


def _actor_result(
    request: ActorExecutionRequestV3,
    *,
    execution_mode: str,
    artifact: SealedArtifactRefV3 | None = None,
    implementation_id: str | None = None,
) -> ActorExecutionResultV3:
    return ActorExecutionResultV3(
        run_id=request.run_id,
        plan_version_id=request.plan_version_id,
        attempt_id=request.attempt_id,
        step_number=request.step.step_number,
        actor_type=request.step.actor_type,
        actor_id=request.step.actor_id,
        step_contract_hash=request.step.contract_hash,
        result_artifact=artifact
        or SealedArtifactRefV3(
            artifact_id=f"artifact_result_{request.step.step_number}",
            kind="actor_result",
            schema_version="actor-result-v1",
            content_hash=HASH,
        ),
        receipt_id=f"receipt_{request.step.step_number}",
        implementation_id=implementation_id or f"implementation_{request.step.actor_type}",
        execution_mode=execution_mode,
    )


class _TrackingActor:
    def __init__(self, actor_type: str, tracker: dict, failures: set[int]) -> None:
        self.actor_type = actor_type
        self.tracker = tracker
        self.failures = failures

    async def execute(self, request: ActorExecutionRequestV3) -> ActorExecutionResultV3:
        assert request.step.actor_type == self.actor_type
        self.tracker["calls"].append((self.actor_type, request.step.step_number))
        self.tracker["active"] += 1
        self.tracker["max_active"] = max(self.tracker["max_active"], self.tracker["active"])
        await asyncio.sleep(0)
        self.tracker["active"] -= 1
        if request.step.step_number in self.failures:
            raise RuntimeError(f"step {request.step.step_number} failed")
        mode = "real" if self.actor_type == "tool" else "model"
        return _actor_result(request, execution_mode=mode)


def _dispatcher(failures: set[int]) -> tuple[HeterogeneousActorDispatcher, dict]:
    tracker = {"calls": [], "active": 0, "max_active": 0}
    return (
        HeterogeneousActorDispatcher(
            tool=_TrackingActor("tool", tracker, failures),
            skill=_TrackingActor("skill", tracker, failures),
            llm=_TrackingActor("llm", tracker, failures),
            reviewer=_TrackingActor("reviewer", tracker, failures),
        ),
        tracker,
    )


def test_wave_execution_dispatches_all_actor_types_and_propagates_failures() -> None:
    plan = _heterogeneous_plan()
    optional_dispatcher, optional_tracker = _dispatcher({2})
    optional = asyncio.run(
        WaveExecutionEngine(optional_dispatcher).execute(plan=plan, attempt_id="attempt_optional")
    )

    assert optional.waves == ((1, 2, 3), (4,))
    assert optional_tracker["max_active"] == 3
    assert {actor_type for actor_type, _ in optional_tracker["calls"]} == {
        "tool",
        "skill",
        "llm",
        "reviewer",
    }
    assert optional.optional_gap_step_numbers == (2,)
    assert optional.succeeded

    core_dispatcher, core_tracker = _dispatcher({1})
    core = asyncio.run(
        WaveExecutionEngine(core_dispatcher).execute(plan=plan, attempt_id="attempt_core")
    )
    statuses = {record.step_number: record.status for record in core.steps}
    assert statuses[1] == StepExecutionStatus.CORE_FAILED
    assert statuses[4] == StepExecutionStatus.BLOCKED
    assert ("reviewer", 4) not in core_tracker["calls"]
    assert not core.succeeded


class _WrongLineageActor:
    async def execute(self, request: ActorExecutionRequestV3) -> ActorExecutionResultV3:
        result = _actor_result(request, execution_mode="real")
        return result.model_copy(update={"attempt_id": "attempt_wrong"})


def test_dispatcher_rejects_actor_result_lineage_drift() -> None:
    plan = _heterogeneous_plan()
    dispatcher, _ = _dispatcher(set())
    dispatcher = HeterogeneousActorDispatcher(
        tool=_WrongLineageActor(),
        skill=dispatcher._ports["skill"],
        llm=dispatcher._ports["llm"],
        reviewer=dispatcher._ports["reviewer"],
    )
    request = ActorExecutionRequestV3(
        run_id=plan.run_id,
        plan_version_id=plan.id,
        attempt_id="attempt_1",
        step=plan.payload.steps[0],
        resolved_input=plan.payload.steps[0].input,
    )

    with pytest.raises(ValueError, match="lineage"):
        asyncio.run(dispatcher.execute(request))


def _verified_tool_execution(
    plan: ExecutionPlanVersionV3,
) -> tuple[ActorExecutionResultV3, VerifiedArtifactContentV3]:
    step = plan.payload.steps[0]
    request = ActorExecutionRequestV3(
        run_id=plan.run_id,
        plan_version_id=plan.id,
        attempt_id="attempt_1",
        step=step,
        resolved_input=step.input,
    )
    content = evidence_artifact_content()
    artifact = SealedArtifactRefV3(
        artifact_id="artifact_tool_1",
        kind="actor_result",
        schema_version="tool-result-v1",
        content_hash=canonical_json_v3_sha256(content),
    )
    result = _actor_result(
        request,
        execution_mode="real",
        artifact=artifact,
        implementation_id="tavily-v1",
    )
    verified = VerifiedArtifactContentV3(
        run_id=result.run_id,
        plan_version_id=result.plan_version_id,
        attempt_id=result.attempt_id,
        step_number=result.step_number,
        actor_type=result.actor_type,
        actor_id=result.actor_id,
        step_contract_hash=result.step_contract_hash,
        receipt_id=result.receipt_id,
        implementation_id=result.implementation_id,
        execution_mode=result.execution_mode,
        artifact=result.result_artifact,
        content=content,
    )
    return result, verified


def _skill_result(plan: ExecutionPlanVersionV3) -> ActorExecutionResultV3:
    step = plan.payload.steps[1]
    request = ActorExecutionRequestV3(
        run_id=plan.run_id,
        plan_version_id=plan.id,
        attempt_id="attempt_1",
        step=step,
        resolved_input=step.input,
    )
    return _actor_result(request, execution_mode="model")


def _replace_evidence_id(value, evidence_id: str):
    if value == "evidence_1":
        return evidence_id
    if isinstance(value, dict):
        return {key: _replace_evidence_id(item, evidence_id) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_evidence_id(item, evidence_id) for item in value]
    return value


class _StaticSynthesis:
    def __init__(self, draft: CompetitiveDeliverableDraftV3) -> None:
        self.draft = draft
        self.calls = 0

    async def synthesize(self, **kwargs) -> CompetitiveDeliverableDraftV3:
        self.calls += 1
        assert kwargs["evidence_manifest"].evidence
        return self.draft


class _SemanticReview:
    def __init__(self, verdict: str = "pass") -> None:
        self.verdict = verdict
        self.calls = 0

    async def review(self, **kwargs) -> SemanticReviewResultV3:
        self.calls += 1
        dimensions = []
        for index, dimension_id in enumerate(REVIEW_DIMENSIONS):
            failed = self.verdict == "revise" and index == 0
            dimensions.append(
                ReviewDimensionV3(
                    id=dimension_id,
                    passed=not failed,
                    issues=("Needs one bounded revision.",) if failed else (),
                )
            )
        return SemanticReviewResultV3(
            receipt_id=f"semantic_receipt_{self.calls}",
            verdict=self.verdict,
            dimensions=tuple(dimensions),
        )


async def _build_delivery_inputs():
    requirement = RequirementVersionV3.model_validate(requirement_envelope())
    plan = _plan_version()
    graph = ProblemGraphV1.model_validate(problem_graph_body())
    tool_result, verified = _verified_tool_execution(plan)
    actor_results = (tool_result, _skill_result(plan))
    artifact_reader = InMemoryArtifactReadAdapter()
    artifact_reader.append_verified_json(verified)
    manifest, verified_artifacts = EvidenceManifestMaterializer(artifact_reader).materialize(
        plan=plan,
        attempt_id="attempt_1",
        actor_results=actor_results,
        collected_at=NOW,
    )
    repository = InMemoryResearchV3Repository()
    manifest_ref = repository.append_evidence_manifest(
        manifest,
        expected_state_version=0,
    )
    raw_deliverable = _replace_evidence_id(
        deepcopy(deliverable_body()), manifest.evidence[0].id
    )
    draft = CompetitiveDeliverableDraftV3.model_validate(
        {
            key: raw_deliverable[key]
            for key in (
                "method_summary",
                "finding_graph",
                "payload",
                "recommendations",
                "coverage",
                "risks_and_open_issues",
            )
        }
    )
    synthesis = _StaticSynthesis(draft)
    deliverable = await CompetitiveTextDeliverableService(synthesis).create_deliverable(
        requirement=requirement,
        plan=plan,
        attempt_id="attempt_1",
        actor_results=actor_results,
        evidence_manifest=manifest,
        evidence_manifest_artifact=manifest_ref,
    )
    deliverable_ref = repository.append_deliverable(
        deliverable,
        expected_state_version=1,
    )
    return {
        "requirement": requirement,
        "plan": plan,
        "graph": graph,
        "actor_results": actor_results,
        "manifest": manifest,
        "manifest_ref": manifest_ref,
        "verified_artifacts": verified_artifacts,
        "repository": repository,
        "deliverable": deliverable,
        "deliverable_ref": deliverable_ref,
        "synthesis": synthesis,
    }


def test_evidence_delivery_review_and_text_report_pipeline() -> None:
    values = asyncio.run(_build_delivery_inputs())
    semantic = _SemanticReview()
    catalog = load_competitive_text_catalog()
    review_service = ReportReviewService.from_catalog(semantic, catalog)
    review = asyncio.run(
        review_service.review(
            requirement=values["requirement"],
            plan=values["plan"],
            problem_graph=values["graph"],
            deliverable=values["deliverable"],
            deliverable_artifact=values["deliverable_ref"],
            actor_results=values["actor_results"],
            evidence_manifest=values["manifest"],
            evidence_manifest_artifact=values["manifest_ref"],
            evidence_artifacts=values["verified_artifacts"],
            revision_round=0,
        )
    )

    assert review.verdict == "pass"
    assert semantic.calls == 1
    assert values["synthesis"].calls == 1
    passed_review = PassedReportReviewV3.model_validate(review.model_dump(mode="python"))
    review_ref = values["repository"].append_review(
        passed_review,
        expected_state_version=2,
    )
    report = CompetitiveTextReportCompositionService.from_catalog(catalog).compose(
        deliverable=values["deliverable"],
        deliverable_artifact=values["deliverable_ref"],
        review=passed_review,
        review_artifact=review_ref,
    )
    report_ref = values["repository"].append_report(report, expected_state_version=3)

    assert tuple(section.id for section in report.sections) == COMPETITIVE_TEXT_SECTION_ORDER
    assert {block.type for section in report.sections for block in section.blocks} <= {
        "paragraph",
        "fact",
        "metric",
        "list",
    }
    assert report.sections[7].blocks[0].type == "paragraph"
    assert values["repository"].get_report(report_ref) == report


def test_review_blocks_deterministic_failure_and_allows_at_most_one_revision() -> None:
    values = asyncio.run(_build_delivery_inputs())
    catalog = load_competitive_text_catalog()
    revise_semantic = _SemanticReview("revise")
    service = ReportReviewService.from_catalog(revise_semantic, catalog)
    common = {
        "requirement": values["requirement"],
        "plan": values["plan"],
        "problem_graph": values["graph"],
        "deliverable": values["deliverable"],
        "deliverable_artifact": values["deliverable_ref"],
        "actor_results": values["actor_results"],
        "evidence_manifest": values["manifest"],
        "evidence_manifest_artifact": values["manifest_ref"],
        "evidence_artifacts": values["verified_artifacts"],
    }

    first = asyncio.run(service.review(**common, revision_round=0))
    second = asyncio.run(service.review(**common, revision_round=1))
    assert first.verdict == "revise"
    assert second.verdict == "block"
    assert revise_semantic.calls == 2

    never_called = _SemanticReview()
    deterministic_service = ReportReviewService.from_catalog(never_called, catalog)
    bad_ref = values["deliverable_ref"].model_copy(update={"content_hash": HASH})
    blocked = asyncio.run(
        deterministic_service.review(
            **{**common, "deliverable_artifact": bad_ref},
            revision_round=0,
        )
    )
    assert blocked.verdict == "block"
    assert blocked.semantic_model_call_receipt_id is None
    assert never_called.calls == 0

    composer = CompetitiveTextReportCompositionService.from_catalog(catalog)
    with pytest.raises(ReportCompositionError, match="pass-typed"):
        composer.compose(
            deliverable=values["deliverable"],
            deliverable_artifact=values["deliverable_ref"],
            review=first,  # type: ignore[arg-type]
            review_artifact=SealedArtifactRefV3(
                artifact_id="artifact_review_revise",
                kind="report_review",
                schema_version="report-review-v3",
                content_hash=canonical_json_v3_sha256(first),
            ),
        )


def test_in_memory_adapters_are_append_only_and_fail_closed() -> None:
    repository = InMemoryResearchV3Repository()
    requirement = RequirementVersionV3.model_validate(requirement_envelope())
    repository.append_requirement(requirement, expected_state_version=0)

    assert repository.state_version("run_1") == 1
    assert repository.get_requirement("run_1", "requirement_1") == requirement
    with pytest.raises(InMemoryAppendError, match="already appended"):
        repository.append_requirement(requirement, expected_state_version=1)

    plan = _plan_version()
    _, verified = _verified_tool_execution(plan)
    artifacts = InMemoryArtifactReadAdapter()
    artifacts.append_verified_json(verified)
    assert (
        artifacts.read_verified_json(
            run_id="run_1",
            plan_version_id="plan_1",
            attempt_id="attempt_1",
            step_number=1,
            artifact=verified.artifact,
        )
        == verified
    )
    assert (
        artifacts.read_verified_json(
            run_id="run_other",
            plan_version_id="plan_1",
            attempt_id="attempt_1",
            step_number=1,
            artifact=verified.artifact,
        )
        is None
    )
    with pytest.raises(InMemoryAppendError, match="already appended"):
        artifacts.append_verified_json(verified)


def test_retry_skip_abort_are_isolated_terminal_state_transitions() -> None:
    running = ExecutionRecoveryStateMachine.start("attempt_1")
    optional_failure = ExecutionRecoveryStateMachine.pause(
        running,
        step_number=2,
        required=False,
        reason=RecoveryPauseReason.FAILED,
    )
    skipped = ExecutionRecoveryStateMachine.skip(
        optional_failure,
        new_plan_version_id="plan_2",
    )
    assert skipped.status == RecoveryStatus.SKIP_SCHEDULED
    assert skipped.successor_plan_version_id == "plan_2"
    with pytest.raises(RecoveryTransitionError, match="paused"):
        ExecutionRecoveryStateMachine.retry(skipped, new_attempt_id="attempt_2")

    unknown = ExecutionRecoveryStateMachine.pause(
        ExecutionRecoveryStateMachine.start("attempt_2"),
        step_number=1,
        required=True,
        reason=RecoveryPauseReason.UNKNOWN,
    )
    retried = ExecutionRecoveryStateMachine.retry(unknown, new_attempt_id="attempt_3")
    assert retried.status == RecoveryStatus.RETRY_SCHEDULED
    assert retried.successor_attempt_id == "attempt_3"

    aborted = ExecutionRecoveryStateMachine.abort(unknown)
    assert aborted.status == RecoveryStatus.ABORTED
    with pytest.raises(RecoveryTransitionError, match="paused"):
        ExecutionRecoveryStateMachine.accept_late_success(aborted)

    required_failure = ExecutionRecoveryStateMachine.pause(
        ExecutionRecoveryStateMachine.start("attempt_4"),
        step_number=1,
        required=True,
        reason=RecoveryPauseReason.FAILED,
    )
    with pytest.raises(RecoveryTransitionError, match="optional failed"):
        ExecutionRecoveryStateMachine.skip(
            required_failure,
            new_plan_version_id="plan_3",
        )
