from __future__ import annotations

import asyncio
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace
from typing import Any

import pytest
from agents.testing import ScriptedModel

import agentmesh.agent_runtime.service as runtime_service_module
import agentmesh.deepsearch.finalization as finalization_module
import agentmesh.deepsearch.reporting as reporting_module
from agentmesh.agent_runtime.service import AgentRuntimeService, _BudgetedDeepSearchModel
from agentmesh.artifacts import (
    ArtifactAccessError,
    TrustedEvidenceEnvelopeV1,
    V1VerifiedArtifactStore,
)
from agentmesh.canonical_json import canonical_json_bytes, canonical_json_sha256
from agentmesh.deepsearch.budget import DeepSearchBudgetMeter
from agentmesh.deepsearch.contracts import (
    ProblemQuestionV1,
    RequirementPayloadV1,
    RequirementScopeV1,
    RequirementSuccessCriterionV1,
    RequirementVersionV1,
    build_problem_graph,
    problem_question_id,
    requirement_content_hash,
)
from agentmesh.deepsearch.finalization import DeepSearchFinalizer
from agentmesh.deepsearch.planning import build_deepsearch_plan_snapshot, plan_content_hash
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    Artifact,
    ArtifactVerificationState,
    DeepSearchBudgetUsageV1,
    DeepSearchBudgetV1,
    DeepSearchEvidenceItemV1,
    DeepSearchFinalizationStage,
    SkillIntent,
    SkillNodeResult,
    SkillOrchestrationRequestMode,
    SkillPlan,
    SkillPlanNode,
    SkillPlanNodeStatus,
    SkillPlanStatus,
    SkillResourceManifestV1,
    Source,
)
from agentmesh.seed import USER
from agentmesh.skill_runtime.finalization import PlanExecutionOutcome
from agentmesh.store import SQLiteStore

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _resource_manifest() -> SkillResourceManifestV1:
    payload = {
        "schema_version": "skill-resource-manifest-v1",
        "required_resources": [],
        "resource_hashes": {},
    }
    return SkillResourceManifestV1(
        **payload,
        content_hash=canonical_json_sha256(payload),
    )


def _seed_persisted_finalizer(
    repository: SQLiteStore,
    *,
    suffix: str,
) -> tuple[AgentRun, SkillPlan]:
    run, created = repository.claim_new_agent_run(
        AgentRun(
            id=f"run_{suffix}",
            thread_id=f"thread_{suffix}",
            user_id="user_finalizer",
            workspace_id="workspace_finalizer",
            project_id="project_finalizer",
            input_text="Compare collaboration platforms",
            client_turn_id=f"turn_{suffix}",
            status=AgentRunStatus.PLANNING,
            planning_mode=AgentPlanningMode.DEEPSEARCH,
            requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
            orchestration_version="v1",
            orchestration_mode="execute",
            absolute_expires_at=NOW + timedelta(days=7),
            deepsearch_budget=DeepSearchBudgetV1(),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    assert created is True
    assert run.client_turn_id is not None
    assert run.create_request_hash is not None
    requirement_payload = RequirementPayloadV1(
        goal=run.input_text,
        scope=RequirementScopeV1(regions=["China"]),
        success_criteria=[
            RequirementSuccessCriterionV1(
                id="criterion_comparison",
                statement="Compare the leading platforms",
            )
        ],
        deliverables=["Research report"],
    )
    requirement = RequirementVersionV1(
        id=f"requirement_{suffix}_v1",
        run_id=run.id,
        version=1,
        request_key=run.client_turn_id,
        request_hash=run.create_request_hash,
        content_hash=requirement_content_hash(requirement_payload),
        payload=requirement_payload,
        created_at=NOW,
    )
    appended = repository.append_deepsearch_requirement_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        requirement=requirement.model_dump(mode="json"),
        expected_requirement_version=None,
        expected_run_status=AgentRunStatus.PLANNING,
        next_run_status=AgentRunStatus.PLANNING,
        events=[],
        checked_at=NOW,
    )
    assert appended is not None

    question = ProblemQuestionV1(
        id=problem_question_id("Which platforms lead the market?"),
        question="Which platforms lead the market?",
        required=True,
        success_criterion_ids=["criterion_comparison"],
        evidence_requirements=["Traceable evidence"],
        acceptance_criteria=["Compare the leading platforms"],
    )
    graph = build_problem_graph(requirement=requirement, questions=[question])
    node = SkillPlanNode(
        id=f"node_{suffix}",
        skill_id="skill_research",
        skill_version="1",
        skill_content_hash="a" * 64,
        reason="Collect comparison evidence",
        question_ids=[question.id],
        resource_manifest=_resource_manifest(),
        status=SkillPlanNodeStatus.COMPLETED,
        attempt=1,
        started_at=NOW + timedelta(minutes=1),
        completed_at=NOW + timedelta(minutes=2),
    )
    plan = SkillPlan(
        id=f"plan_{suffix}",
        run_id=run.id,
        version=2,
        status=SkillPlanStatus.RUNNING,
        intent=SkillIntent(goal=run.input_text),
        candidate_skill_ids=[node.skill_id],
        preferred_order=[node.skill_id],
        nodes=[node],
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        requirement_version_id=requirement.id,
        requirement_content_hash=requirement.content_hash,
        problem_graph=graph.model_dump(mode="json"),
        problem_graph_hash=graph.content_hash,
        created_at=NOW,
        updated_at=NOW + timedelta(minutes=2),
    )
    plan.plan_content_hash = plan_content_hash(plan)
    run = run.model_copy(
        update={
            "plan_id": plan.id,
            "status": AgentRunStatus.RUNNING,
            "updated_at": NOW + timedelta(minutes=2),
        }
    )
    snapshot = build_deepsearch_plan_snapshot(
        run=run,
        plan=plan,
        created_at=NOW + timedelta(minutes=2),
    )
    plan.approved_plan_artifact_id = snapshot.id
    with repository._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
            (run.model_dump_json(), run.updated_at.isoformat(), run.id),
        )
        repository._write_skill_plan(connection, plan)
        repository._insert_deepsearch_plan_snapshot_in_transaction(
            connection,
            run=run,
            requirement=requirement,
            plan=plan,
            plan_snapshot=snapshot,
            expected_plan_hash=plan.plan_content_hash,
        )

    source = Source(
        id=f"source_{suffix}",
        title="Market report",
        source_type="knowledge",
        reference="knowledge://market-report",
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        user_id=run.user_id,
        run_id=run.id,
        skill_id=node.skill_id,
        created_at=NOW + timedelta(minutes=1),
    )
    repository.add_source(source)
    excerpt = "Platform A leads the measured sample."
    envelope = TrustedEvidenceEnvelopeV1(
        schema_version="deepsearch-knowledge-evidence-v1",
        origin_type="knowledge",
        run_id=run.id,
        requirement_version_id=requirement.id,
        request_hash="b" * 64,
        source_id=source.id,
        normalized_reference=source.reference,
        retrieved_at=NOW + timedelta(minutes=1),
        excerpt=excerpt,
        content_hash=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
        size_bytes=len(excerpt.encode("utf-8")),
    )
    evidence_content = canonical_json_bytes(envelope.model_dump(mode="python")).decode(
        "utf-8"
    )
    evidence_bytes = evidence_content.encode("utf-8")
    evidence_artifact = Artifact(
        id=f"artifact_evidence_{suffix}",
        run_id=run.id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        user_id=run.user_id,
        artifact_type="deepsearch_knowledge_evidence",
        content_type="application/json",
        content=evidence_content,
        verification_state=ArtifactVerificationState.SEALED,
        schema_version="deepsearch-knowledge-evidence-v1",
        content_hash=hashlib.sha256(evidence_bytes).hexdigest(),
        size_bytes=len(evidence_bytes),
        requirement_version_id=requirement.id,
        created_at=NOW + timedelta(minutes=1),
        updated_at=NOW + timedelta(minutes=1),
    )
    V1VerifiedArtifactStore(repository).insert_sealed(evidence_artifact)
    result_id = f"result_{suffix}"
    evidence_item_id = "evidence_" + canonical_json_sha256(
        {
            "node_result_id": result_id,
            "evidence_artifact_id": evidence_artifact.id,
            "question_ids": [question.id],
            "success_criterion_ids": ["criterion_comparison"],
        }
    )
    repository.save_skill_node_result(
        plan.id,
        SkillNodeResult(
            id=result_id,
            node_id=node.id,
            skill_id=node.skill_id,
            summary="Collected one source",
            evidence_items=[
                DeepSearchEvidenceItemV1(
                    id=evidence_item_id,
                    node_result_id=result_id,
                    question_ids=[question.id],
                    success_criterion_ids=["criterion_comparison"],
                    source_id=source.id,
                    evidence_artifact_id=evidence_artifact.id,
                )
            ],
            artifact_ids=[evidence_artifact.id],
            attempt=1,
            created_at=NOW + timedelta(minutes=2),
        ),
    )
    return run, plan


def _active_pair() -> tuple[SkillPlan, AgentRun]:
    plan = SkillPlan(
        id="plan_finalizer",
        run_id="run_finalizer",
        version=3,
        status=SkillPlanStatus.RUNNING,
        intent=SkillIntent(goal="Research"),
        nodes=[
            SkillPlanNode(
                id="node_finalizer",
                skill_id="skill_research",
                skill_version="1",
                skill_content_hash="a" * 64,
                reason="Research",
                status=SkillPlanNodeStatus.COMPLETED,
                attempt=1,
            )
        ],
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        plan_content_hash="b" * 64,
    )
    run = AgentRun(
        id=plan.run_id,
        thread_id="thread_finalizer",
        user_id="user_finalizer",
        workspace_id="workspace_finalizer",
        project_id="project_finalizer",
        input_text="Research",
        status=AgentRunStatus.RUNNING,
        plan_id=plan.id,
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        orchestration_mode="execute",
    )
    return plan, run


class _Repository:
    def __init__(self, plan: SkillPlan, run: AgentRun) -> None:
        self.plan = plan
        self.run = run
        self.stage_calls: list[dict[str, Any]] = []
        self.terminal_calls: list[dict[str, Any]] = []

    def get_skill_plan(self, _plan_id: str) -> SkillPlan:
        return self.plan

    def get_agent_run(self, _run_id: str) -> AgentRun:
        return self.run

    def list_skill_node_results(self, _plan_id: str) -> list[Any]:
        return []

    def compare_and_swap_deepsearch_finalization(self, **kwargs: Any) -> tuple[SkillPlan, AgentRun]:
        self.stage_calls.append(kwargs)
        hashes = dict(self.plan.finalization_input_hashes)
        hashes[DeepSearchFinalizationStage.NODES_TERMINAL] = kwargs["input_hash"]
        self.plan = self.plan.model_copy(
            update={
                "finalization_stage": DeepSearchFinalizationStage.NODES_TERMINAL,
                "finalization_version": 1,
                "finalization_input_hashes": hashes,
            }
        )
        return self.plan, self.run

    def commit_deepsearch_terminal_without_report(self, **kwargs: Any) -> tuple[SkillPlan, AgentRun]:
        self.terminal_calls.append(kwargs)
        hashes = dict(self.plan.finalization_input_hashes)
        hashes[DeepSearchFinalizationStage.TERMINAL_COMMITTED] = kwargs["input_hash"]
        self.plan = self.plan.model_copy(
            update={
                "status": SkillPlanStatus.FAILED,
                "finalization_stage": DeepSearchFinalizationStage.TERMINAL_COMMITTED,
                "finalization_version": 2,
                "finalization_input_hashes": hashes,
            }
        )
        self.run = self.run.model_copy(
            update={
                "status": AgentRunStatus.FAILED,
                "error_code": kwargs["error_code"],
            }
        )
        return self.plan, self.run


def test_deepsearch_finalizer_records_nodes_terminal_then_fails_closed() -> None:
    plan, run = _active_pair()
    repository = _Repository(plan, run)

    outcome = asyncio.run(
        DeepSearchFinalizer(repository).finalize(
            run_id=run.id,
            plan_id=plan.id,
            expected_plan_version=plan.version,
        )
    )

    assert len(repository.stage_calls) == 1
    assert repository.stage_calls[0]["target_stage"] is DeepSearchFinalizationStage.NODES_TERMINAL
    assert len(repository.stage_calls[0]["input_hash"]) == 64
    assert len(repository.terminal_calls) == 1
    assert repository.terminal_calls[0]["expected_stage"] is DeepSearchFinalizationStage.NODES_TERMINAL
    assert repository.terminal_calls[0]["error_code"] == "deepsearch_evidence_integrity_failed"
    assert outcome.plan.status is SkillPlanStatus.FAILED
    assert outcome.run.status is AgentRunStatus.FAILED
    assert outcome.run.output_text is None


def test_deepsearch_finalizer_rejects_standard_plan_before_writing() -> None:
    plan, run = _active_pair()
    plan = plan.model_copy(update={"planning_mode": AgentPlanningMode.STANDARD})
    repository = _Repository(plan, run)

    with pytest.raises(RuntimeError, match="deepsearch_finalization_state_conflict"):
        asyncio.run(
            DeepSearchFinalizer(repository).finalize(
                run_id=run.id,
                plan_id=plan.id,
                expected_plan_version=plan.version,
            )
        )

    assert repository.stage_calls == []
    assert repository.terminal_calls == []


def test_deepsearch_finalizer_requires_all_nodes_terminal() -> None:
    plan, run = _active_pair()
    plan.nodes[0].status = SkillPlanNodeStatus.RUNNING
    repository = _Repository(plan, run)

    with pytest.raises(RuntimeError, match="deepsearch_nodes_not_terminal"):
        asyncio.run(
            DeepSearchFinalizer(repository).finalize(
                run_id=run.id,
                plan_id=plan.id,
                expected_plan_version=plan.version,
            )
        )

    assert repository.stage_calls == []
    assert repository.terminal_calls == []


def test_runtime_injects_deepsearch_finalizer_without_standard_synthesis(
    tmp_path,
    monkeypatch,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-runtime-finalizer.sqlite3")
    runtime = AgentRuntimeService(repository, model=ScriptedModel([]), enabled=True)
    plan, run = _active_pair()
    plan.status = SkillPlanStatus.APPROVED
    captured: dict[str, Any] = {}
    model_calls: list[tuple[str, _BudgetedDeepSearchModel]] = []

    class RecordingSynthesisService:
        async def synthesize(self, **kwargs: Any) -> str:
            model_calls.append(("synthesis", kwargs["model"]))
            return "synthesis-result"

    class RecordingReviewService:
        async def review(self, **kwargs: Any) -> str:
            model_calls.append(("review", kwargs["model"]))
            return "review-result"

    runtime.deepsearch_synthesis_service = RecordingSynthesisService()  # type: ignore[assignment]
    runtime.deepsearch_review_service = RecordingReviewService()  # type: ignore[assignment]

    class RecordingExecutor:
        def __init__(self, _repository: object, **kwargs: Any) -> None:
            captured.update(kwargs)

        async def run(
            self,
            current_plan: SkillPlan,
            current_run: AgentRun,
            *,
            resume: bool = False,
        ) -> PlanExecutionOutcome:
            captured["resume"] = resume
            return PlanExecutionOutcome(plan=current_plan, run=current_run)

    monkeypatch.setattr(runtime_service_module, "BoundedDAGExecutor", RecordingExecutor)

    outcome = asyncio.run(runtime._execute_approved_skill_plan(plan=plan, run=run, user=USER))

    finalizer = captured["finalization_strategy"]
    assert isinstance(finalizer, DeepSearchFinalizer)
    assert finalizer.synthesis_runner is not None
    assert finalizer.review_runner is not None
    assert "synthesis_runner" not in captured
    assert captured["resume"] is False
    assert outcome.run is run

    manifest = SimpleNamespace(model_dump=lambda **_kwargs: {"id": "manifest"})
    synthesis = SimpleNamespace(
        revision_count=1,
        model_dump=lambda **_kwargs: {"id": "synthesis"},
    )
    synthesis_result = asyncio.run(
        finalizer.synthesis_runner(
            run,
            plan,
            object(),
            object(),
            [],
            manifest,
            {},
            1,
            None,
        )
    )
    review_result = asyncio.run(
        finalizer.review_runner(
            run,
            plan,
            object(),
            object(),
            synthesis,
            manifest,
            {},
            NOW,
        )
    )

    assert synthesis_result == "synthesis-result"
    assert review_result == "review-result"
    assert [stage for stage, _model in model_calls] == ["synthesis", "review"]
    assert all(isinstance(model, _BudgetedDeepSearchModel) for _stage, model in model_calls)
    assert all(model._scope == "standard" for _stage, model in model_calls)
    assert all(not model._request_scoped for _stage, model in model_calls)


def test_real_store_deterministic_digest_is_published_as_sealed_partial(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalizer-partial.sqlite3")
    run, plan = _seed_persisted_finalizer(repository, suffix="partial")

    outcome = asyncio.run(
        DeepSearchFinalizer(repository, clock=lambda: NOW + timedelta(minutes=6)).finalize(
            run_id=run.id,
            plan_id=plan.id,
            expected_plan_version=plan.version,
        )
    )

    assert outcome.plan.status is SkillPlanStatus.PARTIAL
    assert outcome.plan.finalization_stage is DeepSearchFinalizationStage.TERMINAL_COMMITTED
    assert outcome.plan.report_artifact_id is not None
    assert outcome.run.status is AgentRunStatus.PARTIAL
    assert outcome.run.error_code == "deepsearch_synthesis_fallback"
    assert outcome.run.output_text is not None
    assert "Platform A leads the measured sample." in outcome.run.output_text
    assert outcome.plan.deepsearch_syntheses[0].synthesis_mode == "deterministic_evidence_digest"
    assert outcome.plan.review_outcomes[0].outcome == "not_run"
    report_artifact = repository.get_artifact(outcome.plan.report_artifact_id)
    assert report_artifact is not None
    assert report_artifact.verification_state is ArtifactVerificationState.SEALED
    assert report_artifact.content_hash == outcome.plan.report_content_hash
    manifest_artifact = repository.get_artifact(outcome.plan.evidence_manifest_artifact_id)
    assert manifest_artifact is not None
    persisted_run = repository.get_agent_run(run.id)
    assert persisted_run is not None and persisted_run.deepsearch_budget is not None
    reservations = persisted_run.deepsearch_budget.reservations
    assert {item.logical_operation_key.split(":", 2)[1] for item in reservations} == {
        "manifest",
        "digest-v0",
        "coverage-v0",
        "report-v0",
    }
    assert all(item.scope == "finalization" for item in reservations)
    assert all(item.status == "settled" for item in reservations)
    artifact_usage = {
        item.logical_operation_key.split(":", 2)[1]: item.actual_usage.artifact_bytes
        for item in reservations
        if item.actual_usage is not None
    }
    assert artifact_usage["manifest"] == manifest_artifact.size_bytes
    assert artifact_usage["report-v0"] == report_artifact.size_bytes


def test_finalization_reserve_remains_available_after_standard_budget_is_full(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalizer-reserved-capacity.sqlite3")
    run, plan = _seed_persisted_finalizer(repository, suffix="reserved_capacity")
    standard = DeepSearchBudgetMeter(repository).reserve(
        run_id=run.id,
        expected_budget_version=1,
        logical_operation_key="execution:standard-capacity",
        invocation_key="execution:standard-capacity:attempt:1",
        physical_attempt=1,
        resource_maxima=DeepSearchBudgetUsageV1(
            active_seconds=1500,
            artifact_bytes=9_306_112,
        ),
    )
    assert standard.reservation.scope == "standard"

    outcome = asyncio.run(
        DeepSearchFinalizer(repository, clock=lambda: NOW + timedelta(minutes=6)).finalize(
            run_id=run.id,
            plan_id=plan.id,
            expected_plan_version=plan.version,
        )
    )

    assert outcome.run.status is AgentRunStatus.PARTIAL
    assert outcome.plan.report_artifact_id is not None
    persisted = repository.get_agent_run(run.id)
    assert persisted is not None and persisted.deepsearch_budget is not None
    finalization = [
        item for item in persisted.deepsearch_budget.reservations if item.scope == "finalization"
    ]
    assert finalization
    assert all(item.status == "settled" for item in finalization)


def test_manifest_persistence_uses_three_reserved_attempts_before_failing(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalizer-manifest-failure.sqlite3")
    run, plan = _seed_persisted_finalizer(repository, suffix="manifest_failure")
    original_insert = V1VerifiedArtifactStore.insert_sealed
    attempts = 0

    def fail_manifest(
        store: V1VerifiedArtifactStore,
        artifact: Artifact,
        *,
        connection=None,
    ) -> Artifact:
        nonlocal attempts
        if artifact.artifact_type == "deepsearch_evidence_manifest":
            attempts += 1
            raise ArtifactAccessError("artifact_write_failed")
        return original_insert(store, artifact, connection=connection)

    monkeypatch.setattr(V1VerifiedArtifactStore, "insert_sealed", fail_manifest)

    outcome = asyncio.run(
        DeepSearchFinalizer(repository, clock=lambda: NOW + timedelta(minutes=6)).finalize(
            run_id=run.id,
            plan_id=plan.id,
            expected_plan_version=plan.version,
        )
    )

    assert attempts == 3
    assert outcome.run.status is AgentRunStatus.FAILED
    assert outcome.run.error_code == "deepsearch_recovery_exhausted"
    persisted = repository.get_agent_run(run.id)
    assert persisted is not None and persisted.deepsearch_budget is not None
    manifest_reservations = [
        item
        for item in persisted.deepsearch_budget.reservations
        if ":manifest:" in item.logical_operation_key
    ]
    assert [item.physical_attempt for item in manifest_reservations] == [1, 2, 3]
    assert all(item.status == "settled" for item in manifest_reservations)
    assert all(item.actual_usage == item.resource_maxima for item in manifest_reservations)


def test_oversized_manifest_fails_terminal_and_closes_its_reservation(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalizer-manifest-size.sqlite3")
    run, plan = _seed_persisted_finalizer(repository, suffix="manifest_size")
    monkeypatch.setattr(
        reporting_module,
        "canonical_json_bytes",
        lambda _payload: b"x"
        * (reporting_module.DEEPSEARCH_EVIDENCE_MANIFEST_MAX_BYTES + 1),
    )

    outcome = asyncio.run(
        DeepSearchFinalizer(repository, clock=lambda: NOW + timedelta(minutes=6)).finalize(
            run_id=run.id,
            plan_id=plan.id,
            expected_plan_version=plan.version,
        )
    )

    assert outcome.run.status is AgentRunStatus.FAILED
    assert outcome.run.error_code == "deepsearch_delivery_unavailable"
    assert outcome.plan.evidence_manifest_artifact_id is None
    persisted = repository.get_agent_run(run.id)
    assert persisted is not None and persisted.deepsearch_budget is not None
    manifest_reservations = [
        item
        for item in persisted.deepsearch_budget.reservations
        if ":manifest:" in item.logical_operation_key
    ]
    assert len(manifest_reservations) == 1
    assert manifest_reservations[0].status == "settled"
    assert manifest_reservations[0].actual_usage == manifest_reservations[0].resource_maxima


def test_report_create_failure_retries_three_times_then_fails_without_artifact(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalizer-create-failure.sqlite3")
    run, plan = _seed_persisted_finalizer(repository, suffix="create_failure")
    attempts = 0

    def fail_create(
        _store: V1VerifiedArtifactStore,
        _artifact: Artifact,
        *,
        connection=None,
    ) -> Artifact:
        del connection
        nonlocal attempts
        attempts += 1
        raise ArtifactAccessError("artifact_write_failed")

    monkeypatch.setattr(V1VerifiedArtifactStore, "create_staging_report", fail_create)

    outcome = asyncio.run(
        DeepSearchFinalizer(repository, clock=lambda: NOW + timedelta(minutes=6)).finalize(
            run_id=run.id,
            plan_id=plan.id,
            expected_plan_version=plan.version,
        )
    )

    assert attempts == 3
    assert outcome.plan.status is SkillPlanStatus.FAILED
    assert outcome.plan.report_artifact_id is None
    assert outcome.run.status is AgentRunStatus.FAILED
    assert outcome.run.error_code == "deepsearch_report_persistence_failed"
    assert outcome.run.output_text is None
    with repository._read_connect() as connection:
        report_count = connection.execute(
            "SELECT COUNT(*) FROM artifacts WHERE run_id = ? AND artifact_type = ?",
            (run.id, "deepsearch_report"),
        ).fetchone()[0]
    assert report_count == 0


@pytest.mark.parametrize(
    ("builder_error", "suffix"),
    [
        (
            finalization_module.DeepSearchReportingError(
                "deepsearch_delivery_unavailable"
            ),
            "report_builder_known_failure",
        ),
        (RuntimeError("unexpected report artifact build failure"), "report_builder_failure"),
    ],
)
def test_report_artifact_build_failure_closes_its_reservation_at_maxima(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    builder_error: Exception,
    suffix: str,
) -> None:
    repository = SQLiteStore(tmp_path / f"deepsearch-finalizer-{suffix}.sqlite3")
    run, plan = _seed_persisted_finalizer(repository, suffix=suffix)

    def fail_build(**_kwargs):
        raise builder_error

    monkeypatch.setattr(
        finalization_module,
        "build_deepsearch_report_artifacts",
        fail_build,
    )

    outcome = asyncio.run(
        DeepSearchFinalizer(repository, clock=lambda: NOW + timedelta(minutes=6)).finalize(
            run_id=run.id,
            plan_id=plan.id,
            expected_plan_version=plan.version,
        )
    )

    assert outcome.run.status is AgentRunStatus.FAILED
    assert outcome.run.error_code == "deepsearch_delivery_unavailable"
    persisted = repository.get_agent_run(run.id)
    assert persisted is not None and persisted.deepsearch_budget is not None
    report_reservations = [
        item
        for item in persisted.deepsearch_budget.reservations
        if ":report-v0:" in item.logical_operation_key
    ]
    assert len(report_reservations) == 1
    assert report_reservations[0].status == "settled"
    assert report_reservations[0].actual_usage == report_reservations[0].resource_maxima


def test_report_staging_save_time_is_inside_the_reserved_timeout(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalizer-report-timeout.sqlite3")
    run, plan = _seed_persisted_finalizer(repository, suffix="report_timeout")
    elapsed = 0.0
    original_create = V1VerifiedArtifactStore.create_staging_report

    def create_after_deadline(
        store: V1VerifiedArtifactStore,
        artifact: Artifact,
        *,
        connection=None,
    ) -> Artifact:
        nonlocal elapsed
        persisted = original_create(store, artifact, connection=connection)
        elapsed = 31.0
        return persisted

    monkeypatch.setattr(
        V1VerifiedArtifactStore,
        "create_staging_report",
        create_after_deadline,
    )

    outcome = asyncio.run(
        DeepSearchFinalizer(
            repository,
            clock=lambda: NOW + timedelta(minutes=6),
            monotonic_clock=lambda: elapsed,
        ).finalize(
            run_id=run.id,
            plan_id=plan.id,
            expected_plan_version=plan.version,
        )
    )

    assert outcome.run.status is AgentRunStatus.FAILED
    assert outcome.run.error_code == "deepsearch_budget_exhausted"
    persisted = repository.get_agent_run(run.id)
    assert persisted is not None and persisted.deepsearch_budget is not None
    report_reservations = [
        item
        for item in persisted.deepsearch_budget.reservations
        if ":report-v0:" in item.logical_operation_key
    ]
    assert len(report_reservations) == 1
    assert report_reservations[0].status == "settled"
    assert report_reservations[0].actual_usage == report_reservations[0].resource_maxima
    report_rows = [
        repository.get_artifact(artifact_id)
        for artifact_id in [
            "artifact_deepsearch_report_"
            + canonical_json_sha256(
                {
                    "run_id": run.id,
                    "plan_id": plan.id,
                    "plan_version": plan.version,
                    "stage": "terminal_committed",
                    "revision_count": 0,
                    "kind": "deepsearch_report",
                }
            )
        ]
    ]
    assert len(report_rows) == 1
    assert report_rows[0] is not None
    assert report_rows[0].verification_state is ArtifactVerificationState.FAILED


def test_report_seal_failure_retries_three_times_then_marks_staging_failed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalizer-seal-failure.sqlite3")
    run, plan = _seed_persisted_finalizer(repository, suffix="seal_failure")
    attempts = 0

    def fail_seal(
        _store: V1VerifiedArtifactStore,
        _artifact: Artifact,
        *,
        connection=None,
    ) -> Artifact:
        del connection
        nonlocal attempts
        attempts += 1
        raise ArtifactAccessError("artifact_write_failed")

    monkeypatch.setattr(V1VerifiedArtifactStore, "seal_report", fail_seal)

    outcome = asyncio.run(
        DeepSearchFinalizer(repository, clock=lambda: NOW + timedelta(minutes=6)).finalize(
            run_id=run.id,
            plan_id=plan.id,
            expected_plan_version=plan.version,
        )
    )

    assert attempts == 3
    assert outcome.plan.status is SkillPlanStatus.FAILED
    assert outcome.plan.finalization_stage is DeepSearchFinalizationStage.TERMINAL_COMMITTED
    assert outcome.plan.report_artifact_id is None
    assert outcome.plan.report_content_hash is None
    assert outcome.run.status is AgentRunStatus.FAILED
    assert outcome.run.error_code == "deepsearch_report_persistence_failed"
    assert outcome.run.output_text is None
    with repository._read_connect() as connection:
        report_row = connection.execute(
            "SELECT id FROM artifacts WHERE run_id = ? AND artifact_type = ?",
            (run.id, "deepsearch_report"),
        ).fetchone()
    assert report_row is not None
    report_artifact = repository.get_artifact(report_row["id"])
    assert report_artifact is not None
    assert report_artifact.verification_state is ArtifactVerificationState.FAILED
    assert report_artifact.content == ""


def test_terminal_report_cas_loss_returns_to_outer_authoritative_read(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalizer-cas-loss.sqlite3")
    run, plan = _seed_persisted_finalizer(repository, suffix="cas_loss")
    original_commit = repository.commit_deepsearch_terminal_with_report
    commit_calls = 0

    def commit_as_competing_worker(**kwargs):
        nonlocal commit_calls
        commit_calls += 1
        committed = original_commit(**kwargs)
        assert committed is not None
        return None

    monkeypatch.setattr(
        repository,
        "commit_deepsearch_terminal_with_report",
        commit_as_competing_worker,
    )

    outcome = asyncio.run(
        DeepSearchFinalizer(repository, clock=lambda: NOW + timedelta(minutes=6)).finalize(
            run_id=run.id,
            plan_id=plan.id,
            expected_plan_version=plan.version,
        )
    )

    assert commit_calls == 1
    assert outcome.plan.status is SkillPlanStatus.PARTIAL
    assert outcome.run.status is AgentRunStatus.PARTIAL
    assert sum(
        event.event_type == "run_partial"
        for event in repository.list_agent_run_events(run.id)
    ) == 1


def test_concurrent_finalizers_publish_one_report_and_one_terminal_event(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalizer-concurrent.sqlite3")
    run, plan = _seed_persisted_finalizer(repository, suffix="concurrent")

    def finalize() -> PlanExecutionOutcome:
        return asyncio.run(
            DeepSearchFinalizer(
                repository,
                clock=lambda: NOW + timedelta(minutes=6),
            ).finalize(
                run_id=run.id,
                plan_id=plan.id,
                expected_plan_version=plan.version,
            )
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _index: finalize(), range(2)))

    assert all(outcome.plan.status is SkillPlanStatus.PARTIAL for outcome in outcomes)
    assert all(outcome.run.status is AgentRunStatus.PARTIAL for outcome in outcomes)
    final_plan = repository.get_skill_plan(plan.id)
    assert final_plan is not None
    assert final_plan.report_artifact_id is not None
    assert repository.get_artifact(final_plan.report_artifact_id).verification_state is ArtifactVerificationState.SEALED  # type: ignore[union-attr]
    events = repository.list_agent_run_events(run.id)
    assert sum(event.event_type == "run_partial" for event in events) == 1
    assert sum(
        event.event_type == "deepsearch_finalization_stage_changed"
        and event.payload.get("to_stage") == "terminal_committed"
        for event in events
    ) == 1
    with repository._read_connect() as connection:
        report_count = connection.execute(
            "SELECT COUNT(*) FROM artifacts WHERE run_id = ? AND artifact_type = ?",
            (run.id, "deepsearch_report"),
        ).fetchone()[0]
    assert report_count == 1


def test_cancel_wins_concurrent_report_seal_and_fails_only_current_staging_report(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalizer-cancel-race.sqlite3")
    run, plan = _seed_persisted_finalizer(repository, suffix="cancel_race")
    captured_commit: dict[str, Any] = {}
    original_commit = repository.commit_deepsearch_terminal_with_report

    class StopAfterStaging(BaseException):
        pass

    def capture_commit(**kwargs):
        captured_commit.update(kwargs)
        raise StopAfterStaging

    with monkeypatch.context() as patch:
        patch.setattr(
            repository,
            "commit_deepsearch_terminal_with_report",
            capture_commit,
        )
        with pytest.raises(StopAfterStaging):
            asyncio.run(
                DeepSearchFinalizer(
                    repository,
                    clock=lambda: NOW + timedelta(minutes=6),
                ).finalize(
                    run_id=run.id,
                    plan_id=plan.id,
                    expected_plan_version=plan.version,
                )
            )

    staging_id = captured_commit["staging_artifact_id"]
    assert isinstance(staging_id, str)
    current_staging = repository.get_artifact(staging_id)
    assert current_staging is not None
    assert current_staging.verification_state is ArtifactVerificationState.STAGING
    other_plan_staging = current_staging.model_copy(
        update={
            "id": "artifact_other_plan_staging",
            "plan_version_id": "plan_other:v1",
        }
    )
    V1VerifiedArtifactStore(repository).create_staging_report(other_plan_staging)

    cancel_entered = Event()
    release_cancel = Event()
    seal_started = Event()
    original_cancel = repository._cancel_agent_run_tree_in_transaction

    def gated_cancel(connection, current_run, **kwargs):
        cancel_entered.set()
        assert release_cancel.wait(timeout=5)
        return original_cancel(connection, current_run, **kwargs)

    def seal_after_cancel_locks():
        seal_started.set()
        return original_commit(**captured_commit)

    with monkeypatch.context() as patch:
        patch.setattr(repository, "_cancel_agent_run_tree_in_transaction", gated_cancel)
        with ThreadPoolExecutor(max_workers=2) as pool:
            cancel_future = pool.submit(
                repository.cancel_agent_run_tree,
                run.id,
                user_id=run.user_id,
            )
            assert cancel_entered.wait(timeout=5)
            seal_future = pool.submit(seal_after_cancel_locks)
            assert seal_started.wait(timeout=5)
            release_cancel.set()
            cancelled_run = cancel_future.result(timeout=5)
            seal_result = seal_future.result(timeout=5)

    assert cancelled_run is not None
    assert cancelled_run.status is AgentRunStatus.CANCELLED
    assert seal_result is None
    final_plan = repository.get_skill_plan(plan.id)
    final_run = repository.get_agent_run(run.id)
    assert final_plan is not None
    assert final_run is not None
    assert final_plan.status is SkillPlanStatus.CANCELLED
    assert final_plan.report_artifact_id is None
    assert final_plan.report_content_hash is None
    assert final_run.status is AgentRunStatus.CANCELLED
    assert final_run.output_text is None
    report_artifact = repository.get_artifact(staging_id)
    assert report_artifact is not None
    assert report_artifact.verification_state is ArtifactVerificationState.FAILED
    assert (
        repository.get_artifact(other_plan_staging.id).verification_state
        is ArtifactVerificationState.STAGING
    )
    events = repository.list_agent_run_events(run.id)
    assert sum(event.event_type == "run_cancelled" for event in events) == 1
    assert not any(event.event_type == "run_partial" for event in events)
