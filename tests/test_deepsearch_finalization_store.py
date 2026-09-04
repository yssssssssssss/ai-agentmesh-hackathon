from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

import agentmesh.store as store_module
from agentmesh.artifacts import (
    DeepSearchEvidenceManifestItemV1,
    DeepSearchEvidenceManifestV1,
    DeepSearchReportClaimV1,
    DeepSearchReportLimitationV1,
    DeepSearchReportSectionV1,
    DeepSearchReportV1,
    V1VerifiedArtifactStore,
)
from agentmesh.canonical_json import canonical_json_bytes, canonical_json_sha256
from agentmesh.deepsearch.budget import DeepSearchBudgetMeter
from agentmesh.deepsearch.contracts import (
    ProblemGraphV1,
    ProblemQuestionV1,
    RequirementPayloadV1,
    RequirementScopeV1,
    RequirementSuccessCriterionV1,
    RequirementVersionV1,
    build_problem_graph,
    problem_question_id,
    requirement_content_hash,
)
from agentmesh.deepsearch.planning import build_deepsearch_plan_snapshot, plan_content_hash
from agentmesh.deepsearch.reporting import build_deepsearch_report_artifacts, deepsearch_claim_id
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    Artifact,
    ArtifactVerificationState,
    DeepSearchBudgetUsageV1,
    DeepSearchBudgetV1,
    DeepSearchEvidenceCoverageV1,
    DeepSearchFinalizationStage,
    DeepSearchReportReviewV1,
    DeepSearchReviewOutcomeV1,
    DeepSearchSynthesisClaimV1,
    DeepSearchSynthesisV1,
    InboxItem,
    Scope,
    SkillIntent,
    SkillOrchestrationRequestMode,
    SkillPlan,
    SkillPlanNode,
    SkillPlanNodeStatus,
    SkillPlanStatus,
    SkillResourceManifestV1,
)
from agentmesh.store import DeepSearchBudgetConflict, ResearchStoreConflict, SQLiteStore

NOW = datetime.now(UTC).replace(microsecond=0)


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


def _seed_running_deepsearch(
    repository: SQLiteStore,
    *,
    run_id: str,
    node_status: SkillPlanNodeStatus = SkillPlanNodeStatus.COMPLETED,
    plan_status: SkillPlanStatus = SkillPlanStatus.RUNNING,
    run_status: AgentRunStatus = AgentRunStatus.RUNNING,
) -> tuple[AgentRun, SkillPlan]:
    run, created = repository.claim_new_agent_run(
        AgentRun(
            id=run_id,
            thread_id=f"thread_{run_id}",
            user_id="user_finalization",
            workspace_id="workspace_finalization",
            project_id="project_finalization",
            input_text="Compare collaboration platforms",
            client_turn_id=f"turn_{run_id}",
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
        id=f"requirement_{run.id}_v1",
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
        evidence_requirements=["Public market evidence"],
        acceptance_criteria=["Compare the leading platforms"],
    )
    graph = build_problem_graph(requirement=requirement, questions=[question])
    node = SkillPlanNode(
        id="node_research",
        skill_id="skill_research",
        skill_version="1",
        skill_content_hash="a" * 64,
        reason="Answer the comparison question",
        question_ids=[question.id],
        resource_manifest=_resource_manifest(),
        status=node_status,
        attempt=1,
        started_at=NOW + timedelta(minutes=1),
        completed_at=(
            NOW + timedelta(minutes=2)
            if node_status
            in {
                SkillPlanNodeStatus.COMPLETED,
                SkillPlanNodeStatus.FAILED,
                SkillPlanNodeStatus.SKIPPED,
                SkillPlanNodeStatus.CANCELLED,
            }
            else None
        ),
    )
    plan = SkillPlan(
        id=f"plan_{run.id}",
        run_id=run.id,
        version=2,
        status=plan_status,
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
            "status": run_status,
            "paused_state": (
                {"kind": "skill_plan_node", "node_id": node.id}
                if run_status is AgentRunStatus.WAITING_APPROVAL
                else None
            ),
            "interaction_expires_at": (
                NOW + timedelta(hours=24)
                if run_status
                in {
                    AgentRunStatus.WAITING_PLAN_APPROVAL,
                    AgentRunStatus.WAITING_APPROVAL,
                }
                else None
            ),
            "updated_at": NOW + timedelta(minutes=2),
        }
    )
    snapshot = build_deepsearch_plan_snapshot(run=run, plan=plan, created_at=NOW + timedelta(minutes=2))
    if plan_status is not SkillPlanStatus.WAITING_APPROVAL:
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
    return run, plan


def _replace_run(repository: SQLiteStore, run: AgentRun) -> None:
    with repository._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
            (run.model_dump_json(), run.updated_at.isoformat(), run.id),
        )


def _reserve_finalization_transition(
    repository: SQLiteStore,
    *,
    run_id: str,
    operation: str,
    resource_maxima: DeepSearchBudgetUsageV1,
    actual_usage: DeepSearchBudgetUsageV1,
) -> dict[str, object]:
    current_run = repository.get_agent_run(run_id)
    assert current_run is not None and current_run.deepsearch_budget is not None
    logical_key = f"test-finalization:{operation}"
    reservation = DeepSearchBudgetMeter(repository).reserve(
        run_id=run_id,
        expected_budget_version=current_run.deepsearch_budget.version,
        logical_operation_key=logical_key,
        invocation_key=f"{logical_key}:attempt:1",
        physical_attempt=1,
        resource_maxima=resource_maxima,
        scope="finalization",
    )
    return {
        "budget_invocation_key": reservation.reservation.invocation_key,
        "budget_actual_usage": actual_usage,
    }


def _finalization_payloads(
    repository: SQLiteStore,
    *,
    run: AgentRun,
    plan: SkillPlan,
    report_status: str = "complete",
    review_verdict: str = "pass",
) -> tuple[
    Artifact,
    DeepSearchSynthesisV1,
    DeepSearchEvidenceCoverageV1,
    DeepSearchReviewOutcomeV1,
    Artifact,
    Artifact,
]:
    requirement = RequirementVersionV1.model_validate(
        repository.get_active_deepsearch_requirement(run.id)
    )
    graph = ProblemGraphV1.model_validate(plan.problem_graph)
    question_id = graph.questions[0].id
    criterion_id = requirement.payload.success_criteria[0].id
    evidence_item_id = f"evidence_{run.id}"
    node_result_id = f"result_{run.id}"
    manifest = DeepSearchEvidenceManifestV1(
        schema_version="deepsearch-evidence-manifest-v1",
        run_id=run.id,
        requirement_version_id=requirement.id,
        plan_id=plan.id,
        plan_version=plan.version,
        plan_content_hash=plan.plan_content_hash or "",
        items=[
            DeepSearchEvidenceManifestItemV1(
                evidence_item_id=evidence_item_id,
                node_result_id=node_result_id,
                evidence_artifact_id=f"artifact_evidence_{run.id}",
                evidence_artifact_content_hash="a" * 64,
                origin_type="knowledge",
                question_ids=[question_id],
                success_criterion_ids=[criterion_id],
            )
        ],
    )
    manifest_content = canonical_json_bytes(manifest.model_dump(mode="python")).decode(
        "utf-8"
    )
    manifest_bytes = manifest_content.encode("utf-8")
    manifest_artifact = Artifact(
        id=f"artifact_manifest_{run.id}",
        run_id=run.id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        user_id=run.user_id,
        artifact_type="deepsearch_evidence_manifest",
        content_type="application/json",
        content=manifest_content,
        verification_state=ArtifactVerificationState.SEALED,
        schema_version="deepsearch-evidence-manifest-v1",
        content_hash=hashlib.sha256(manifest_bytes).hexdigest(),
        size_bytes=len(manifest_bytes),
        requirement_version_id=requirement.id,
        plan_version_id=f"{plan.id}:v{plan.version}",
        created_at=NOW + timedelta(minutes=3),
        updated_at=NOW + timedelta(minutes=3),
    )
    claim_payload = {
        "text": "Platform A leads the measured sample.",
        "question_ids": [question_id],
        "success_criterion_ids": [criterion_id],
        "node_result_ids": [node_result_id],
        "evidence_item_ids": [evidence_item_id],
        "source_ids": [],
        "recommendation": False,
    }
    claim = DeepSearchSynthesisClaimV1(
        id=deepsearch_claim_id(
            run_id=run.id,
            plan_id=plan.id,
            plan_version=plan.version,
            revision_count=0,
            ordinal=1,
            claim=claim_payload,
        ),
        **claim_payload,
    )
    synthesis = DeepSearchSynthesisV1(
        revision_count=0,
        synthesis_mode="model",
        claims=[claim],
    )
    synthesis_hash = canonical_json_sha256(synthesis.model_dump(mode="python"))
    coverage = DeepSearchEvidenceCoverageV1(
        revision_count=0,
        synthesis_content_hash=synthesis_hash,
        required_question_ids=[question_id],
        covered_question_ids=[question_id],
        uncovered_question_ids=[],
        required_success_criterion_ids=[criterion_id],
        covered_success_criterion_ids=[criterion_id],
        uncovered_success_criterion_ids=[],
        validated_claim_ids=[claim.id],
        invalid_claim_ids=[],
        validated_source_ids=[],
        invalid_source_ids=[],
        validated_node_result_ids=[node_result_id],
        invalid_node_result_ids=[],
        external_evidence_is_real=True,
        passed=True,
        gap_codes=[],
    )
    review = DeepSearchReportReviewV1(
        requirement_version_id=requirement.id,
        requirement_content_hash=requirement.content_hash,
        problem_graph_hash=graph.content_hash,
        plan_id=plan.id,
        plan_version=plan.version,
        plan_content_hash=plan.plan_content_hash or "",
        synthesis_content_hash=synthesis_hash,
        verdict=review_verdict,
        unsupported_claim_ids=[claim.id] if review_verdict == "revise" else [],
        revision_count=0,
        reviewer_type="test-reviewer",
        reviewed_at=NOW + timedelta(minutes=4),
    )
    review_outcome = DeepSearchReviewOutcomeV1(
        revision_count=0,
        synthesis_content_hash=synthesis_hash,
        outcome=review_verdict,
        review=review,
    )
    limitations = (
        []
        if report_status == "complete"
        else [
            DeepSearchReportLimitationV1(
                code="deepsearch_required_coverage_incomplete",
                description="The report is intentionally partial.",
            )
        ]
    )
    report = DeepSearchReportV1(
        schema_version="deepsearch-report-v1",
        run_id=run.id,
        requirement_version_id=requirement.id,
        plan_id=plan.id,
        plan_version=plan.version,
        requirement_content_hash=requirement.content_hash,
        problem_graph_hash=graph.content_hash,
        plan_content_hash=plan.plan_content_hash or "",
        evidence_manifest_hash=manifest_artifact.content_hash or "",
        synthesis_content_hash=synthesis_hash,
        review_outcome=review_verdict,
        report_status=report_status,
        title="Platform comparison",
        claims=[DeepSearchReportClaimV1(**claim.model_dump(mode="python"))],
        executive_summary_claim_ids=[claim.id],
        sections=[
            DeepSearchReportSectionV1(
                section_id=question_id,
                server_heading=graph.questions[0].question,
                claim_ids=[claim.id],
            )
        ],
        limitations=limitations,
        rendered_text="# Platform comparison\n\nPlatform A leads the measured sample.",
    )
    staging_report, sealed_report = build_deepsearch_report_artifacts(
        run=run,
        plan=plan,
        report=report,
        created_at=NOW + timedelta(minutes=5),
    )
    return (
        manifest_artifact,
        synthesis,
        coverage,
        review_outcome,
        staging_report,
        sealed_report,
    )


def _advance_to_review_v0(
    repository: SQLiteStore,
    *,
    run: AgentRun,
    plan: SkillPlan,
    report_status: str = "complete",
    review_verdict: str = "pass",
) -> tuple[SkillPlan, AgentRun, Artifact, Artifact]:
    manifest_artifact, synthesis, coverage, review_outcome, staging, sealed = (
        _finalization_payloads(
            repository,
            run=run,
            plan=plan,
            report_status=report_status,
            review_verdict=review_verdict,
        )
    )
    transitions = [
        (
            DeepSearchFinalizationStage.NONE,
            DeepSearchFinalizationStage.NODES_TERMINAL,
            {},
        ),
        (
            DeepSearchFinalizationStage.NODES_TERMINAL,
            DeepSearchFinalizationStage.EVIDENCE_MANIFEST_SEALED,
            {"evidence_manifest_artifact": manifest_artifact},
        ),
        (
            DeepSearchFinalizationStage.EVIDENCE_MANIFEST_SEALED,
            DeepSearchFinalizationStage.SYNTHESIS_V0_SAVED,
            {"synthesis": synthesis},
        ),
        (
            DeepSearchFinalizationStage.SYNTHESIS_V0_SAVED,
            DeepSearchFinalizationStage.COVERAGE_V0_CHECKED,
            {"coverage": coverage},
        ),
        (
            DeepSearchFinalizationStage.COVERAGE_V0_CHECKED,
            DeepSearchFinalizationStage.REVIEW_V0_CHECKED,
            {"review_outcome": review_outcome},
        ),
    ]
    current_plan = plan
    current_run = run
    for version, (current_stage, target_stage, payload) in enumerate(transitions):
        budget_kwargs: dict[str, object] = {}
        if target_stage is DeepSearchFinalizationStage.EVIDENCE_MANIFEST_SEALED:
            assert manifest_artifact.size_bytes is not None
            budget_kwargs = _reserve_finalization_transition(
                repository,
                run_id=run.id,
                operation="manifest",
                resource_maxima=DeepSearchBudgetUsageV1(
                    active_seconds=30,
                    artifact_bytes=131_072,
                ),
                actual_usage=DeepSearchBudgetUsageV1(
                    artifact_bytes=manifest_artifact.size_bytes,
                ),
            )
        elif target_stage is DeepSearchFinalizationStage.COVERAGE_V0_CHECKED:
            budget_kwargs = _reserve_finalization_transition(
                repository,
                run_id=run.id,
                operation="coverage-v0",
                resource_maxima=DeepSearchBudgetUsageV1(active_seconds=15),
                actual_usage=DeepSearchBudgetUsageV1(),
            )
        transitioned = repository.compare_and_swap_deepsearch_finalization(
            run_id=run.id,
            plan_id=plan.id,
            expected_plan_version=plan.version,
            expected_finalization_version=version,
            expected_stage=current_stage,
            target_stage=target_stage,
            input_hash=f"{version}" * 64,
            **payload,
            **budget_kwargs,
        )
        assert transitioned is not None
        current_plan, current_run = transitioned
    return current_plan, current_run, staging, sealed


def test_nodes_terminal_cas_advances_checkpoint_and_preserves_latest_budget(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalization-nodes-terminal.sqlite3")
    run, plan = _seed_running_deepsearch(repository, run_id="run_nodes_terminal")
    latest_budget = DeepSearchBudgetV1(
        version=2,
        stage_recovery_attempts={"evidence_manifest": 2},
    )
    _replace_run(
        repository,
        run.model_copy(
            update={
                "deepsearch_budget": latest_budget,
                "updated_at": NOW + timedelta(minutes=3),
            }
        ),
    )

    transitioned = repository.compare_and_swap_deepsearch_finalization(
        run_id=run.id,
        plan_id=plan.id,
        expected_plan_version=plan.version,
        expected_finalization_version=0,
        expected_stage=DeepSearchFinalizationStage.NONE,
        target_stage=DeepSearchFinalizationStage.NODES_TERMINAL,
        input_hash="b" * 64,
    )

    assert transitioned is not None
    current_plan, current_run = transitioned
    assert current_plan.version == plan.version
    assert current_plan.status is SkillPlanStatus.RUNNING
    assert current_plan.finalization_stage is DeepSearchFinalizationStage.NODES_TERMINAL
    assert current_plan.finalization_version == 1
    assert current_plan.finalization_input_hashes == {
        DeepSearchFinalizationStage.NODES_TERMINAL: "b" * 64
    }
    assert current_run.status is AgentRunStatus.RUNNING
    assert current_run.deepsearch_budget == latest_budget
    events_after_first_commit = repository.list_agent_run_events(run.id)

    stale = repository.compare_and_swap_deepsearch_finalization(
        run_id=run.id,
        plan_id=plan.id,
        expected_plan_version=plan.version,
        expected_finalization_version=0,
        expected_stage=DeepSearchFinalizationStage.NONE,
        target_stage=DeepSearchFinalizationStage.NODES_TERMINAL,
        input_hash="b" * 64,
    )

    assert stale is None
    assert repository.get_skill_plan(plan.id) == current_plan
    assert repository.get_agent_run(run.id) == current_run
    assert repository.list_agent_run_events(run.id) == events_after_first_commit


def test_nodes_terminal_cas_rejects_nonterminal_nodes_without_partial_writes(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalization-node-still-running.sqlite3")
    run, plan = _seed_running_deepsearch(
        repository,
        run_id="run_node_still_running",
        node_status=SkillPlanNodeStatus.RUNNING,
    )
    plan_before = repository.get_skill_plan(plan.id)
    run_before = repository.get_agent_run(run.id)
    events_before = repository.list_agent_run_events(run.id)

    with pytest.raises(ResearchStoreConflict, match="all nodes to be terminal"):
        repository.compare_and_swap_deepsearch_finalization(
            run_id=run.id,
            plan_id=plan.id,
            expected_plan_version=plan.version,
            expected_finalization_version=0,
            expected_stage=DeepSearchFinalizationStage.NONE,
            target_stage=DeepSearchFinalizationStage.NODES_TERMINAL,
            input_hash="c" * 64,
        )

    assert repository.get_skill_plan(plan.id) == plan_before
    assert repository.get_agent_run(run.id) == run_before
    assert repository.list_agent_run_events(run.id) == events_before


def test_finalization_cas_rejects_tampered_plan_hash_without_partial_writes(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalization-tampered-plan.sqlite3")
    run, plan = _seed_running_deepsearch(repository, run_id="run_tampered_finalization_plan")
    tampered = plan.model_copy(
        update={"intent": SkillIntent(goal="A different goal injected after approval")}
    )
    with repository._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        repository._write_skill_plan(connection, tampered)
    run_before = repository.get_agent_run(run.id)
    events_before = repository.list_agent_run_events(run.id)

    with pytest.raises(ResearchStoreConflict, match="lineage is invalid"):
        repository.compare_and_swap_deepsearch_finalization(
            run_id=run.id,
            plan_id=plan.id,
            expected_plan_version=plan.version,
            expected_finalization_version=0,
            expected_stage=DeepSearchFinalizationStage.NONE,
            target_stage=DeepSearchFinalizationStage.NODES_TERMINAL,
            input_hash="3" * 64,
        )

    assert repository.get_skill_plan(plan.id) == tampered
    assert repository.get_agent_run(run.id) == run_before
    assert repository.list_agent_run_events(run.id) == events_before


def test_finalization_cas_rejects_skipped_stage_without_partial_writes(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalization-skipped-stage.sqlite3")
    run, plan = _seed_running_deepsearch(repository, run_id="run_skipped_finalization_stage")
    plan_before = repository.get_skill_plan(plan.id)
    run_before = repository.get_agent_run(run.id)
    events_before = repository.list_agent_run_events(run.id)

    with pytest.raises(ResearchStoreConflict, match="stage transition is invalid"):
        repository.compare_and_swap_deepsearch_finalization(
            run_id=run.id,
            plan_id=plan.id,
            expected_plan_version=plan.version,
            expected_finalization_version=0,
            expected_stage=DeepSearchFinalizationStage.NONE,
            target_stage=DeepSearchFinalizationStage.SYNTHESIS_V0_SAVED,
            input_hash="4" * 64,
        )

    assert repository.get_skill_plan(plan.id) == plan_before
    assert repository.get_agent_run(run.id) == run_before
    assert repository.list_agent_run_events(run.id) == events_before


@pytest.mark.parametrize(
    ("terminal_status", "error_code", "event_type", "expected_plan_status"),
    [
        (
            AgentRunStatus.FAILED,
            "deepsearch_evidence_integrity_failed",
            "run_failed",
            SkillPlanStatus.FAILED,
        ),
        (AgentRunStatus.CANCELLED, None, "run_cancelled", SkillPlanStatus.CANCELLED),
    ],
)
def test_terminal_without_report_commits_plan_run_and_closes_inbox_from_fresh_state(
    tmp_path,
    terminal_status: AgentRunStatus,
    error_code: str | None,
    event_type: str,
    expected_plan_status: SkillPlanStatus,
) -> None:
    repository = SQLiteStore(tmp_path / f"deepsearch-finalization-{terminal_status.value}.sqlite3")
    run, plan = _seed_running_deepsearch(
        repository,
        run_id=f"run_terminal_{terminal_status.value}",
    )
    checkpoint = repository.compare_and_swap_deepsearch_finalization(
        run_id=run.id,
        plan_id=plan.id,
        expected_plan_version=plan.version,
        expected_finalization_version=0,
        expected_stage=DeepSearchFinalizationStage.NONE,
        target_stage=DeepSearchFinalizationStage.NODES_TERMINAL,
        input_hash="d" * 64,
    )
    assert checkpoint is not None

    inbox = InboxItem(
        id=f"inbox_{terminal_status.value}",
        title="Pending DeepSearch decision",
        summary="Must be closed with the terminal transaction.",
        item_type="deepsearch_review",
        scope=Scope.PRIVATE,
        user_id=run.user_id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        metadata={"run_id": run.id},
        created_at=NOW,
        updated_at=NOW,
    )
    repository.save_inbox_item(inbox)
    latest_budget = DeepSearchBudgetV1(
        version=3,
        stage_recovery_attempts={"evidence_manifest": 3},
    )
    persisted_run = repository.get_agent_run(run.id)
    assert persisted_run is not None
    _replace_run(
        repository,
        persisted_run.model_copy(
            update={
                "deepsearch_budget": latest_budget,
                "updated_at": NOW + timedelta(minutes=4),
            }
        ),
    )
    events = [
        (
            event_type,
            {
                "plan_id": plan.id,
                "error_code": error_code,
            },
        )
    ]

    committed = repository.commit_deepsearch_terminal_without_report(
        run_id=run.id,
        plan_id=plan.id,
        expected_plan_version=plan.version,
        expected_finalization_version=1,
        expected_stage=DeepSearchFinalizationStage.NODES_TERMINAL,
        expected_plan_status=SkillPlanStatus.RUNNING,
        expected_run_status=AgentRunStatus.RUNNING,
        terminal_status=terminal_status,
        error_code=error_code,
        input_hash="e" * 64,
        events=events,
    )

    assert committed is not None
    terminal_plan, terminal_run = committed
    assert terminal_plan.version == plan.version
    assert terminal_plan.status is expected_plan_status
    assert terminal_plan.finalization_stage is DeepSearchFinalizationStage.TERMINAL_COMMITTED
    assert terminal_plan.finalization_version == 2
    assert terminal_plan.finalization_input_hashes == {
        DeepSearchFinalizationStage.NODES_TERMINAL: "d" * 64,
        DeepSearchFinalizationStage.TERMINAL_COMMITTED: "e" * 64,
    }
    assert terminal_plan.report_artifact_id is None
    assert terminal_plan.report_content_hash is None
    assert terminal_run.status is terminal_status
    assert terminal_run.error_code == error_code
    assert terminal_run.output_text is None
    assert terminal_run.deepsearch_budget == latest_budget
    resolved = repository.get_inbox_item(inbox.id)
    assert resolved is not None
    assert resolved.status == "resolved"
    assert resolved.metadata["approval_failure"] == (error_code or terminal_status.value)
    assert repository.list_agent_run_events(run.id)[-1].event_type == event_type


def test_terminal_without_report_cancels_nonterminal_nodes_in_the_same_transaction(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalization-cancel-active-node.sqlite3")
    run, plan = _seed_running_deepsearch(
        repository,
        run_id="run_cancel_active_node",
        node_status=SkillPlanNodeStatus.RUNNING,
    )

    committed = repository.commit_deepsearch_terminal_without_report(
        run_id=run.id,
        plan_id=plan.id,
        expected_plan_version=plan.version,
        expected_finalization_version=0,
        expected_stage=DeepSearchFinalizationStage.NONE,
        expected_plan_status=SkillPlanStatus.RUNNING,
        expected_run_status=AgentRunStatus.RUNNING,
        terminal_status=AgentRunStatus.CANCELLED,
        error_code=None,
        input_hash="f" * 64,
        events=[
            (
                "run_cancelled",
                {"plan_id": plan.id, "error_code": None},
            )
        ],
    )

    assert committed is not None
    terminal_plan, _terminal_run = committed
    assert terminal_plan.nodes[0].status is SkillPlanNodeStatus.CANCELLED
    assert terminal_plan.nodes[0].completed_at is not None
    assert [event.event_type for event in repository.list_agent_run_events(run.id)][-3:] == [
        "node_cancelled",
        "deepsearch_finalization_stage_changed",
        "run_cancelled",
    ]


def test_terminal_without_report_fails_closed_when_a_staging_report_exists(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalization-staging-report.sqlite3")
    run, plan = _seed_running_deepsearch(repository, run_id="run_staging_report")
    staging = V1VerifiedArtifactStore(repository).create_staging_report(
        Artifact(
            id="artifact_staging_report",
            run_id=run.id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            user_id=run.user_id,
            artifact_type="deepsearch_report",
            content_type="application/json",
            content="",
            verification_state=ArtifactVerificationState.STAGING,
            schema_version="deepsearch-report-v1",
            requirement_version_id=plan.requirement_version_id,
            plan_version_id=f"{plan.id}:v{plan.version}",
            created_at=NOW + timedelta(minutes=3),
            updated_at=NOW + timedelta(minutes=3),
        )
    )
    plan_before = repository.get_skill_plan(plan.id)
    run_before = repository.get_agent_run(run.id)
    events_before = repository.list_agent_run_events(run.id)

    with pytest.raises(ResearchStoreConflict, match="staging report"):
        repository.commit_deepsearch_terminal_without_report(
            run_id=run.id,
            plan_id=plan.id,
            expected_plan_version=plan.version,
            expected_finalization_version=0,
            expected_stage=DeepSearchFinalizationStage.NONE,
            expected_plan_status=SkillPlanStatus.RUNNING,
            expected_run_status=AgentRunStatus.RUNNING,
            terminal_status=AgentRunStatus.FAILED,
            error_code="deepsearch_report_persistence_failed",
            input_hash="1" * 64,
            events=[
                (
                    "run_failed",
                    {
                        "plan_id": plan.id,
                        "error_code": "deepsearch_report_persistence_failed",
                    },
                )
            ],
        )

    assert repository.get_skill_plan(plan.id) == plan_before
    assert repository.get_agent_run(run.id) == run_before
    assert repository.list_agent_run_events(run.id) == events_before
    assert repository.get_artifact(staging.id) == staging


@pytest.mark.parametrize(
    ("plan_status", "run_status", "node_status"),
    [
        (
            SkillPlanStatus.APPROVED,
            AgentRunStatus.RUNNING,
            SkillPlanNodeStatus.PENDING,
        ),
        (
            SkillPlanStatus.RUNNING,
            AgentRunStatus.WAITING_APPROVAL,
            SkillPlanNodeStatus.WAITING_TOOL_APPROVAL,
        ),
    ],
)
def test_terminal_without_report_cas_covers_executor_bypass_states(
    tmp_path,
    plan_status: SkillPlanStatus,
    run_status: AgentRunStatus,
    node_status: SkillPlanNodeStatus,
) -> None:
    repository = SQLiteStore(tmp_path / f"deepsearch-finalization-{plan_status.value}-{run_status.value}.sqlite3")
    run, plan = _seed_running_deepsearch(
        repository,
        run_id=f"run_{plan_status.value}_{run_status.value}",
        node_status=node_status,
        plan_status=plan_status,
        run_status=run_status,
    )
    inbox = InboxItem(
        id=f"inbox_{plan_status.value}_{run_status.value}",
        title="Pending DeepSearch decision",
        summary="Must be closed when the bypass path fails.",
        item_type="deepsearch_review",
        scope=Scope.PRIVATE,
        user_id=run.user_id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        metadata={"run_id": run.id},
    )
    repository.save_inbox_item(inbox)
    plan_before = repository.get_skill_plan(plan.id)
    run_before = repository.get_agent_run(run.id)
    events_before = repository.list_agent_run_events(run.id)

    stale = repository.commit_deepsearch_terminal_without_report(
        run_id=run.id,
        plan_id=plan.id,
        expected_plan_version=plan.version,
        expected_finalization_version=0,
        expected_stage=DeepSearchFinalizationStage.NONE,
        expected_plan_status=SkillPlanStatus.RUNNING,
        expected_run_status=AgentRunStatus.RUNNING,
        terminal_status=AgentRunStatus.FAILED,
        error_code="deepsearch_execution_transient",
        input_hash="2" * 64,
        events=[
            (
                "run_failed",
                {
                    "plan_id": plan.id,
                    "error_code": "deepsearch_execution_transient",
                },
            )
        ],
    )
    if plan_status is SkillPlanStatus.RUNNING and run_status is AgentRunStatus.RUNNING:
        raise AssertionError("test fixture must exercise a non-default bypass state")
    assert stale is None
    assert repository.get_skill_plan(plan.id) == plan_before
    assert repository.get_agent_run(run.id) == run_before
    assert repository.list_agent_run_events(run.id) == events_before
    assert repository.get_inbox_item(inbox.id) == inbox

    committed = repository.commit_deepsearch_terminal_without_report(
        run_id=run.id,
        plan_id=plan.id,
        expected_plan_version=plan.version,
        expected_finalization_version=0,
        expected_stage=DeepSearchFinalizationStage.NONE,
        expected_plan_status=plan_status,
        expected_run_status=run_status,
        terminal_status=AgentRunStatus.FAILED,
        error_code="deepsearch_execution_transient",
        input_hash="2" * 64,
        events=[
            (
                "run_failed",
                {
                    "plan_id": plan.id,
                    "error_code": "deepsearch_execution_transient",
                },
            )
        ],
    )

    assert committed is not None
    terminal_plan, terminal_run = committed
    assert terminal_plan.status is SkillPlanStatus.FAILED
    assert terminal_plan.nodes[0].status is SkillPlanNodeStatus.CANCELLED
    assert terminal_run.status is AgentRunStatus.FAILED
    assert terminal_run.paused_state is None
    assert terminal_run.interaction_expires_at is None
    assert repository.get_inbox_item(inbox.id).status == "resolved"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("plan_status", "run_status", "node_status"),
    [
        (
            SkillPlanStatus.WAITING_APPROVAL,
            AgentRunStatus.WAITING_PLAN_APPROVAL,
            SkillPlanNodeStatus.PENDING,
        ),
        (
            SkillPlanStatus.APPROVED,
            AgentRunStatus.RUNNING,
            SkillPlanNodeStatus.PENDING,
        ),
        (
            SkillPlanStatus.RUNNING,
            AgentRunStatus.RUNNING,
            SkillPlanNodeStatus.RUNNING,
        ),
    ],
)
def test_cancel_deepsearch_with_existing_plan_commits_matching_terminal_state(
    tmp_path,
    plan_status: SkillPlanStatus,
    run_status: AgentRunStatus,
    node_status: SkillPlanNodeStatus,
) -> None:
    repository = SQLiteStore(
        tmp_path / f"deepsearch-cancel-{plan_status.value}-{run_status.value}.sqlite3"
    )
    run, plan = _seed_running_deepsearch(
        repository,
        run_id=f"run_cancel_{plan_status.value}_{run_status.value}",
        node_status=node_status,
        plan_status=plan_status,
        run_status=run_status,
    )

    cancelled = repository.cancel_agent_run_tree(run.id, user_id=run.user_id)

    assert cancelled is not None
    assert cancelled.status is AgentRunStatus.CANCELLED
    current_plan = repository.get_skill_plan(plan.id)
    assert current_plan is not None
    assert current_plan.status is SkillPlanStatus.CANCELLED
    assert current_plan.finalization_stage is DeepSearchFinalizationStage.TERMINAL_COMMITTED
    assert current_plan.finalization_version == 1
    assert list(current_plan.finalization_input_hashes) == [
        DeepSearchFinalizationStage.TERMINAL_COMMITTED
    ]
    assert len(current_plan.finalization_input_hashes[DeepSearchFinalizationStage.TERMINAL_COMMITTED]) == 64
    assert current_plan.nodes[0].status is SkillPlanNodeStatus.CANCELLED
    assert current_plan.nodes[0].completed_at is not None
    event_types = [event.event_type for event in repository.list_agent_run_events(run.id)]
    assert event_types[-3:] == [
        "node_cancelled",
        "deepsearch_finalization_stage_changed",
        "run_cancelled",
    ]


def test_cancel_deepsearch_without_plan_does_not_invent_finalization_state(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-cancel-without-plan.sqlite3")
    run, created = repository.claim_new_agent_run(
        AgentRun(
            id="run_cancel_without_plan",
            thread_id="thread_cancel_without_plan",
            user_id="user_finalization",
            workspace_id="workspace_finalization",
            project_id="project_finalization",
            input_text="Cancel before planning finishes",
            client_turn_id="turn_cancel_without_plan",
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

    cancelled = repository.cancel_agent_run_tree(run.id, user_id=run.user_id)

    assert cancelled is not None
    assert cancelled.status is AgentRunStatus.CANCELLED
    assert repository.get_skill_plan_for_run(run.id) is None
    assert "deepsearch_finalization_stage_changed" not in {
        event.event_type for event in repository.list_agent_run_events(run.id)
    }


def test_cancel_standard_plan_does_not_write_deepsearch_finalization_state(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "standard-cancel-finalization-compatibility.sqlite3")
    run = repository.save_agent_run(
        AgentRun(
            id="run_standard_cancel_finalization",
            thread_id="thread_standard_cancel_finalization",
            user_id="user_standard_cancel_finalization",
            workspace_id="workspace_standard_cancel_finalization",
            project_id="project_standard_cancel_finalization",
            input_text="Cancel a standard plan",
            status=AgentRunStatus.RUNNING,
        )
    )
    plan = repository.save_skill_plan(
        SkillPlan(
            id="plan_standard_cancel_finalization",
            run_id=run.id,
            status=SkillPlanStatus.RUNNING,
            intent=SkillIntent(goal=run.input_text),
            nodes=[
                SkillPlanNode(
                    id="node_standard_cancel_finalization",
                    skill_id="skill_standard",
                    skill_version="1",
                    skill_content_hash="a" * 64,
                    reason="Run standard work",
                )
            ],
        )
    )
    repository.save_agent_run(run.model_copy(update={"plan_id": plan.id}))

    cancelled = repository.cancel_agent_run_tree(run.id, user_id=run.user_id)

    assert cancelled is not None
    current_plan = repository.get_skill_plan(plan.id)
    assert current_plan is not None
    assert current_plan.status is SkillPlanStatus.CANCELLED
    assert current_plan.finalization_stage is DeepSearchFinalizationStage.NONE
    assert current_plan.finalization_version == 0
    assert current_plan.finalization_input_hashes == {}
    assert "deepsearch_finalization_stage_changed" not in {
        event.event_type for event in repository.list_agent_run_events(run.id)
    }


def test_completed_node_uses_only_dedicated_finalization_writers(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-dedicated-finalization-chain.sqlite3")
    run, plan = _seed_running_deepsearch(
        repository,
        run_id="run_dedicated_finalization_chain",
        node_status=SkillPlanNodeStatus.RUNNING,
    )
    generic_writer_calls: list[str] = []

    def unexpected_save_agent_run(*_args, **_kwargs):
        generic_writer_calls.append("save_agent_run")
        raise AssertionError("DeepSearch finalization called generic save_agent_run")

    def unexpected_save_skill_plan(*_args, **_kwargs):
        generic_writer_calls.append("save_skill_plan")
        raise AssertionError("DeepSearch finalization called generic save_skill_plan")

    monkeypatch.setattr(repository, "save_agent_run", unexpected_save_agent_run)
    monkeypatch.setattr(repository, "save_skill_plan", unexpected_save_skill_plan)

    completed_node = plan.nodes[0].model_copy(
        update={
            "status": SkillPlanNodeStatus.COMPLETED,
            "completed_at": NOW + timedelta(minutes=3),
        }
    )
    completed = repository.transition_skill_plan_node(
        plan_id=plan.id,
        run_id=run.id,
        node=completed_node,
        expected_statuses={SkillPlanNodeStatus.RUNNING},
        expected_attempt=completed_node.attempt,
        event_type="node_completed",
        event_payload={"plan_id": plan.id, "node_id": completed_node.id},
    )
    assert completed is not None
    after_node = repository.get_skill_plan(plan.id)
    assert after_node is not None
    assert after_node.finalization_stage is DeepSearchFinalizationStage.NONE
    assert after_node.finalization_version == 0

    checkpoint = repository.compare_and_swap_deepsearch_finalization(
        run_id=run.id,
        plan_id=plan.id,
        expected_plan_version=plan.version,
        expected_finalization_version=0,
        expected_stage=DeepSearchFinalizationStage.NONE,
        target_stage=DeepSearchFinalizationStage.NODES_TERMINAL,
        input_hash="5" * 64,
    )
    assert checkpoint is not None
    checkpoint_plan, _checkpoint_run = checkpoint
    assert checkpoint_plan.finalization_stage is DeepSearchFinalizationStage.NODES_TERMINAL
    assert checkpoint_plan.finalization_version == 1

    terminal = repository.commit_deepsearch_terminal_without_report(
        run_id=run.id,
        plan_id=plan.id,
        expected_plan_version=plan.version,
        expected_finalization_version=1,
        expected_stage=DeepSearchFinalizationStage.NODES_TERMINAL,
        expected_plan_status=SkillPlanStatus.RUNNING,
        expected_run_status=AgentRunStatus.RUNNING,
        terminal_status=AgentRunStatus.FAILED,
        error_code="deepsearch_delivery_unavailable",
        input_hash="6" * 64,
        events=[
            (
                "run_failed",
                {
                    "plan_id": plan.id,
                    "error_code": "deepsearch_delivery_unavailable",
                },
            )
        ],
    )
    assert terminal is not None
    terminal_plan, terminal_run = terminal
    assert terminal_plan.finalization_stage is DeepSearchFinalizationStage.TERMINAL_COMMITTED
    assert terminal_plan.finalization_version == 2
    assert terminal_plan.status is SkillPlanStatus.FAILED
    assert terminal_run.status is AgentRunStatus.FAILED
    assert generic_writer_calls == []
    finalization_events = [
        event.payload["to_stage"]
        for event in repository.list_agent_run_events(run.id)
        if event.event_type == "deepsearch_finalization_stage_changed"
    ]
    assert finalization_events == ["nodes_terminal", "terminal_committed"]


def test_nodes_terminal_cas_is_concurrent_and_stale_request_idempotent(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalization-concurrent-cas.sqlite3")
    run, plan = _seed_running_deepsearch(
        repository,
        run_id="run_concurrent_finalization_cas",
    )

    def claim_nodes_terminal():
        return repository.compare_and_swap_deepsearch_finalization(
            run_id=run.id,
            plan_id=plan.id,
            expected_plan_version=plan.version,
            expected_finalization_version=0,
            expected_stage=DeepSearchFinalizationStage.NONE,
            target_stage=DeepSearchFinalizationStage.NODES_TERMINAL,
            input_hash="7" * 64,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _index: claim_nodes_terminal(), range(8)))

    assert sum(result is not None for result in results) == 1
    committed_plan = repository.get_skill_plan(plan.id)
    committed_run = repository.get_agent_run(run.id)
    assert committed_plan is not None
    assert committed_run is not None
    assert committed_plan.finalization_stage is DeepSearchFinalizationStage.NODES_TERMINAL
    assert committed_plan.finalization_version == 1
    events_after_race = repository.list_agent_run_events(run.id)
    assert sum(
        event.event_type == "deepsearch_finalization_stage_changed"
        for event in events_after_race
    ) == 1

    stale = claim_nodes_terminal()

    assert stale is None
    assert repository.get_skill_plan(plan.id) == committed_plan
    assert repository.get_agent_run(run.id) == committed_run
    assert repository.list_agent_run_events(run.id) == events_after_race


def test_typed_finalization_chain_persists_each_checkpoint_atomically(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalization-typed-chain.sqlite3")
    run, plan = _seed_running_deepsearch(repository, run_id="run_typed_chain")
    current_plan, current_run, _staging, _sealed = _advance_to_review_v0(
        repository,
        run=run,
        plan=plan,
    )

    assert current_plan.finalization_stage is DeepSearchFinalizationStage.REVIEW_V0_CHECKED
    assert current_plan.finalization_version == 5
    assert current_plan.evidence_manifest_artifact_id is not None
    assert current_plan.evidence_manifest_hash is not None
    assert len(current_plan.deepsearch_syntheses) == 1
    assert len(current_plan.synthesis_content_hashes) == 1
    assert current_plan.evidence_coverage is not None
    assert current_plan.evidence_coverage.passed is True
    assert len(current_plan.review_outcomes) == 1
    assert current_plan.review_outcomes[0].outcome == "pass"
    assert current_run.status is AgentRunStatus.RUNNING
    manifest = repository.get_artifact(current_plan.evidence_manifest_artifact_id)
    assert manifest is not None
    assert manifest.verification_state is ArtifactVerificationState.SEALED
    assert manifest.content_hash == current_plan.evidence_manifest_hash
    assert [
        event.payload["to_stage"]
        for event in repository.list_agent_run_events(run.id)
        if event.event_type == "deepsearch_finalization_stage_changed"
    ] == [
        "nodes_terminal",
        "evidence_manifest_sealed",
        "synthesis_v0_saved",
        "coverage_v0_checked",
        "review_v0_checked",
    ]


def test_typed_finalization_chain_preserves_v0_coverage_until_v1_replaces_it(
    tmp_path,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalization-revision-chain.sqlite3")
    run, plan = _seed_running_deepsearch(repository, run_id="run_revision_chain")
    review_plan, _review_run, _staging, _sealed = _advance_to_review_v0(
        repository,
        run=run,
        plan=plan,
        review_verdict="revise",
    )
    coverage_v0 = review_plan.evidence_coverage
    synthesis_v0 = review_plan.deepsearch_syntheses[0]
    assert coverage_v0 is not None

    claim_v0 = synthesis_v0.claims[0]
    claim_payload = {
        **claim_v0.model_dump(mode="python", exclude={"id"}),
        "text": "Platform A leads the measured sample after review.",
    }
    claim_v1 = DeepSearchSynthesisClaimV1(
        id=deepsearch_claim_id(
            run_id=run.id,
            plan_id=plan.id,
            plan_version=plan.version,
            revision_count=1,
            ordinal=1,
            claim=claim_payload,
        ),
        **claim_payload,
    )
    synthesis_v1 = DeepSearchSynthesisV1(
        revision_count=1,
        synthesis_mode="model",
        claims=[claim_v1],
    )
    synthesis_checkpoint = repository.compare_and_swap_deepsearch_finalization(
        run_id=run.id,
        plan_id=plan.id,
        expected_plan_version=plan.version,
        expected_finalization_version=5,
        expected_stage=DeepSearchFinalizationStage.REVIEW_V0_CHECKED,
        target_stage=DeepSearchFinalizationStage.SYNTHESIS_V1_SAVED,
        input_hash="5" * 64,
        synthesis=synthesis_v1,
    )
    assert synthesis_checkpoint is not None
    synthesis_plan, _current_run = synthesis_checkpoint
    assert synthesis_plan.evidence_coverage == coverage_v0

    synthesis_v1_hash = canonical_json_sha256(synthesis_v1.model_dump(mode="python"))
    coverage_v1 = coverage_v0.model_copy(
        update={
            "revision_count": 1,
            "synthesis_content_hash": synthesis_v1_hash,
            "validated_claim_ids": [claim_v1.id],
        }
    )
    coverage_budget = _reserve_finalization_transition(
        repository,
        run_id=run.id,
        operation="coverage-v1",
        resource_maxima=DeepSearchBudgetUsageV1(active_seconds=15),
        actual_usage=DeepSearchBudgetUsageV1(),
    )
    coverage_checkpoint = repository.compare_and_swap_deepsearch_finalization(
        run_id=run.id,
        plan_id=plan.id,
        expected_plan_version=plan.version,
        expected_finalization_version=6,
        expected_stage=DeepSearchFinalizationStage.SYNTHESIS_V1_SAVED,
        target_stage=DeepSearchFinalizationStage.COVERAGE_V1_CHECKED,
        input_hash="6" * 64,
        coverage=coverage_v1,
        **coverage_budget,
    )
    assert coverage_checkpoint is not None

    review_v0 = review_plan.review_outcomes[0].review
    assert review_v0 is not None
    review_v1 = DeepSearchReportReviewV1(
        **{
            **review_v0.model_dump(mode="python"),
            "synthesis_content_hash": synthesis_v1_hash,
            "verdict": "pass",
            "unsupported_claim_ids": [],
            "revision_count": 1,
            "reviewed_at": NOW + timedelta(minutes=6),
        }
    )
    outcome_v1 = DeepSearchReviewOutcomeV1(
        revision_count=1,
        synthesis_content_hash=synthesis_v1_hash,
        outcome="pass",
        review=review_v1,
    )
    review_checkpoint = repository.compare_and_swap_deepsearch_finalization(
        run_id=run.id,
        plan_id=plan.id,
        expected_plan_version=plan.version,
        expected_finalization_version=7,
        expected_stage=DeepSearchFinalizationStage.COVERAGE_V1_CHECKED,
        target_stage=DeepSearchFinalizationStage.REVIEW_V1_CHECKED,
        input_hash="7" * 64,
        review_outcome=outcome_v1,
    )

    assert review_checkpoint is not None
    final_plan, final_run = review_checkpoint
    assert final_plan.finalization_stage is DeepSearchFinalizationStage.REVIEW_V1_CHECKED
    assert final_plan.finalization_version == 8
    assert final_plan.report_revision_count == 1
    assert final_plan.evidence_coverage == coverage_v1
    assert final_plan.deepsearch_syntheses == [synthesis_v0, synthesis_v1]
    assert final_plan.review_outcomes == [review_plan.review_outcomes[0], outcome_v1]
    assert final_run.status is AgentRunStatus.RUNNING


def test_manifest_insert_rolls_back_when_plan_checkpoint_write_fails(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalization-manifest-rollback.sqlite3")
    run, plan = _seed_running_deepsearch(repository, run_id="run_manifest_rollback")
    manifest, _synthesis, _coverage, _review, _staging, _sealed = (
        _finalization_payloads(repository, run=run, plan=plan)
    )
    nodes_terminal = repository.compare_and_swap_deepsearch_finalization(
        run_id=run.id,
        plan_id=plan.id,
        expected_plan_version=plan.version,
        expected_finalization_version=0,
        expected_stage=DeepSearchFinalizationStage.NONE,
        target_stage=DeepSearchFinalizationStage.NODES_TERMINAL,
        input_hash="0" * 64,
    )
    assert nodes_terminal is not None
    assert manifest.size_bytes is not None
    manifest_budget = _reserve_finalization_transition(
        repository,
        run_id=run.id,
        operation="manifest-rollback",
        resource_maxima=DeepSearchBudgetUsageV1(
            active_seconds=30,
            artifact_bytes=131_072,
        ),
        actual_usage=DeepSearchBudgetUsageV1(artifact_bytes=manifest.size_bytes),
    )
    plan_before = repository.get_skill_plan(plan.id)
    run_before = repository.get_agent_run(run.id)
    events_before = repository.list_agent_run_events(run.id)

    def fail_plan_write(*_args, **_kwargs) -> None:
        raise RuntimeError("injected plan write failure")

    with monkeypatch.context() as patch:
        patch.setattr(repository, "_write_skill_plan", fail_plan_write)
        with pytest.raises(RuntimeError, match="injected plan write failure"):
            repository.compare_and_swap_deepsearch_finalization(
                run_id=run.id,
                plan_id=plan.id,
                expected_plan_version=plan.version,
                expected_finalization_version=1,
                expected_stage=DeepSearchFinalizationStage.NODES_TERMINAL,
                target_stage=DeepSearchFinalizationStage.EVIDENCE_MANIFEST_SEALED,
                input_hash="1" * 64,
                evidence_manifest_artifact=manifest,
                **manifest_budget,
            )

    assert repository.get_artifact(manifest.id) is None
    assert repository.get_skill_plan(plan.id) == plan_before
    assert repository.get_agent_run(run.id) == run_before
    assert repository.list_agent_run_events(run.id) == events_before


def test_manifest_checkpoint_requires_a_finalization_reservation(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalization-manifest-budget.sqlite3")
    run, plan = _seed_running_deepsearch(repository, run_id="run_manifest_budget_required")
    manifest, _synthesis, _coverage, _review, _staging, _sealed = (
        _finalization_payloads(repository, run=run, plan=plan)
    )
    assert repository.compare_and_swap_deepsearch_finalization(
        run_id=run.id,
        plan_id=plan.id,
        expected_plan_version=plan.version,
        expected_finalization_version=0,
        expected_stage=DeepSearchFinalizationStage.NONE,
        target_stage=DeepSearchFinalizationStage.NODES_TERMINAL,
        input_hash="0" * 64,
    ) is not None

    with pytest.raises(DeepSearchBudgetConflict, match="deepsearch_budget_request_invalid"):
        repository.compare_and_swap_deepsearch_finalization(
            run_id=run.id,
            plan_id=plan.id,
            expected_plan_version=plan.version,
            expected_finalization_version=1,
            expected_stage=DeepSearchFinalizationStage.NODES_TERMINAL,
            target_stage=DeepSearchFinalizationStage.EVIDENCE_MANIFEST_SEALED,
            input_hash="1" * 64,
            evidence_manifest_artifact=manifest,
        )

    assert repository.get_artifact(manifest.id) is None


def test_typed_checkpoint_exact_replay_is_idempotent_and_conflict_has_no_side_effects(
    tmp_path,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalization-typed-replay.sqlite3")
    run, plan = _seed_running_deepsearch(repository, run_id="run_typed_replay")
    manifest, _synthesis, _coverage, _review, _staging, _sealed = (
        _finalization_payloads(repository, run=run, plan=plan)
    )
    assert repository.compare_and_swap_deepsearch_finalization(
        run_id=run.id,
        plan_id=plan.id,
        expected_plan_version=plan.version,
        expected_finalization_version=0,
        expected_stage=DeepSearchFinalizationStage.NONE,
        target_stage=DeepSearchFinalizationStage.NODES_TERMINAL,
        input_hash="0" * 64,
    ) is not None
    assert manifest.size_bytes is not None
    manifest_budget = _reserve_finalization_transition(
        repository,
        run_id=run.id,
        operation="manifest-replay",
        resource_maxima=DeepSearchBudgetUsageV1(
            active_seconds=30,
            artifact_bytes=131_072,
        ),
        actual_usage=DeepSearchBudgetUsageV1(artifact_bytes=manifest.size_bytes),
    )
    committed = repository.compare_and_swap_deepsearch_finalization(
        run_id=run.id,
        plan_id=plan.id,
        expected_plan_version=plan.version,
        expected_finalization_version=1,
        expected_stage=DeepSearchFinalizationStage.NODES_TERMINAL,
        target_stage=DeepSearchFinalizationStage.EVIDENCE_MANIFEST_SEALED,
        input_hash="1" * 64,
        evidence_manifest_artifact=manifest,
        **manifest_budget,
    )
    assert committed is not None
    events_after_commit = repository.list_agent_run_events(run.id)

    replay = repository.compare_and_swap_deepsearch_finalization(
        run_id=run.id,
        plan_id=plan.id,
        expected_plan_version=plan.version,
        expected_finalization_version=1,
        expected_stage=DeepSearchFinalizationStage.NODES_TERMINAL,
        target_stage=DeepSearchFinalizationStage.EVIDENCE_MANIFEST_SEALED,
        input_hash="1" * 64,
        evidence_manifest_artifact=manifest,
        **manifest_budget,
    )

    assert replay == committed
    assert repository.list_agent_run_events(run.id) == events_after_commit

    parsed_manifest = DeepSearchEvidenceManifestV1.model_validate_json(manifest.content)
    conflicting_manifest = parsed_manifest.model_copy(
        update={
            "items": [
                parsed_manifest.items[0].model_copy(
                    update={"node_result_id": "result_conflicting"}
                )
            ]
        }
    )
    conflicting_content = canonical_json_bytes(
        conflicting_manifest.model_dump(mode="python")
    ).decode("utf-8")
    conflicting_bytes = conflicting_content.encode("utf-8")
    conflicting_artifact = manifest.model_copy(
        update={
            "content": conflicting_content,
            "content_hash": hashlib.sha256(conflicting_bytes).hexdigest(),
            "size_bytes": len(conflicting_bytes),
        }
    )
    plan_before = repository.get_skill_plan(plan.id)
    artifact_before = repository.get_artifact(manifest.id)

    with pytest.raises(ResearchStoreConflict, match="replay payload conflicts"):
        repository.compare_and_swap_deepsearch_finalization(
            run_id=run.id,
            plan_id=plan.id,
            expected_plan_version=plan.version,
            expected_finalization_version=1,
            expected_stage=DeepSearchFinalizationStage.NODES_TERMINAL,
            target_stage=DeepSearchFinalizationStage.EVIDENCE_MANIFEST_SEALED,
            input_hash="1" * 64,
            evidence_manifest_artifact=conflicting_artifact,
            **manifest_budget,
        )

    assert repository.get_skill_plan(plan.id) == plan_before
    assert repository.get_artifact(manifest.id) == artifact_before
    assert repository.list_agent_run_events(run.id) == events_after_commit


def test_terminal_report_seal_and_plan_run_completion_commit_together(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalization-report-seal.sqlite3")
    run, plan = _seed_running_deepsearch(repository, run_id="run_report_seal")
    review_plan, review_run, staging, sealed = _advance_to_review_v0(
        repository,
        run=run,
        plan=plan,
    )
    assert sealed.size_bytes is not None
    report_budget = _reserve_finalization_transition(
        repository,
        run_id=run.id,
        operation="report-seal",
        resource_maxima=DeepSearchBudgetUsageV1(
            active_seconds=30,
            artifact_bytes=262_144,
        ),
        actual_usage=DeepSearchBudgetUsageV1(artifact_bytes=sealed.size_bytes),
    )
    V1VerifiedArtifactStore(repository).create_staging_report(staging)
    events = [
        (
            "run_completed",
            {"plan_id": plan.id, "report_artifact_id": sealed.id, "error_code": None},
        )
    ]

    committed = repository.commit_deepsearch_terminal_with_report(
        run_id=run.id,
        plan_id=plan.id,
        expected_plan_version=plan.version,
        expected_finalization_version=review_plan.finalization_version,
        expected_stage=review_plan.finalization_stage,
        expected_plan_status=review_plan.status,
        expected_run_status=review_run.status,
        staging_artifact_id=staging.id,
        sealed_report=sealed,
        terminal_status=AgentRunStatus.COMPLETED,
        error_code=None,
        input_hash="5" * 64,
        events=events,
        **report_budget,
    )

    assert committed is not None
    terminal_plan, terminal_run = committed
    assert terminal_plan.status is SkillPlanStatus.COMPLETED
    assert terminal_plan.finalization_stage is DeepSearchFinalizationStage.TERMINAL_COMMITTED
    assert terminal_plan.finalization_version == 6
    assert terminal_plan.report_artifact_id == sealed.id
    assert terminal_plan.report_content_hash == sealed.content_hash
    assert terminal_run.status is AgentRunStatus.COMPLETED
    assert terminal_run.output_text == DeepSearchReportV1.model_validate_json(
        sealed.content
    ).rendered_text
    assert terminal_run.error_code is None
    assert repository.get_artifact(staging.id) == sealed
    events_after_commit = repository.list_agent_run_events(run.id)
    assert events_after_commit[-1].event_type == "run_completed"

    replay = repository.commit_deepsearch_terminal_with_report(
        run_id=run.id,
        plan_id=plan.id,
        expected_plan_version=plan.version,
        expected_finalization_version=review_plan.finalization_version,
        expected_stage=review_plan.finalization_stage,
        expected_plan_status=review_plan.status,
        expected_run_status=review_run.status,
        staging_artifact_id=staging.id,
        sealed_report=sealed,
        terminal_status=AgentRunStatus.COMPLETED,
        error_code=None,
        input_hash="5" * 64,
        events=events,
        **report_budget,
    )
    assert replay == committed
    assert repository.list_agent_run_events(run.id) == events_after_commit


def test_terminal_report_settles_actual_report_usage_and_other_reservations_once(
    tmp_path,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalization-budget-close.sqlite3")
    run, plan = _seed_running_deepsearch(repository, run_id="run_report_budget_close")
    review_plan, review_run, staging, sealed = _advance_to_review_v0(
        repository,
        run=run,
        plan=plan,
    )
    assert sealed.size_bytes is not None
    meter = DeepSearchBudgetMeter(repository)
    current_run = repository.get_agent_run(run.id)
    assert current_run is not None and current_run.deepsearch_budget is not None
    orphan = meter.reserve(
        run_id=run.id,
        expected_budget_version=current_run.deepsearch_budget.version,
        logical_operation_key="finalization:orphan",
        invocation_key="finalization:orphan:attempt:1",
        physical_attempt=1,
        resource_maxima=DeepSearchBudgetUsageV1(active_seconds=4, artifact_bytes=10),
        scope="finalization",
    )
    report_maxima = DeepSearchBudgetUsageV1(
        active_seconds=30,
        artifact_bytes=sealed.size_bytes + 100,
    )
    report = meter.reserve(
        run_id=run.id,
        expected_budget_version=orphan.budget.version,
        logical_operation_key="finalization:report-v0",
        invocation_key="finalization:report-v0:attempt:1",
        physical_attempt=1,
        resource_maxima=report_maxima,
        scope="finalization",
    )
    actual_report_usage = DeepSearchBudgetUsageV1(
        active_seconds=3,
        artifact_bytes=sealed.size_bytes,
    )
    V1VerifiedArtifactStore(repository).create_staging_report(staging)

    committed = repository.commit_deepsearch_terminal_with_report(
        run_id=run.id,
        plan_id=plan.id,
        expected_plan_version=plan.version,
        expected_finalization_version=review_plan.finalization_version,
        expected_stage=review_plan.finalization_stage,
        expected_plan_status=review_plan.status,
        expected_run_status=review_run.status,
        staging_artifact_id=staging.id,
        sealed_report=sealed,
        terminal_status=AgentRunStatus.COMPLETED,
        error_code=None,
        input_hash="6" * 64,
        events=[
            (
                "run_completed",
                {"plan_id": plan.id, "report_artifact_id": sealed.id, "error_code": None},
            )
        ],
        budget_invocation_key=report.reservation.invocation_key,
        budget_actual_usage=actual_report_usage,
    )

    assert committed is not None
    _terminal_plan, terminal_run = committed
    assert terminal_run.deepsearch_budget is not None
    terminal_budget = terminal_run.deepsearch_budget
    assert terminal_budget.version == report.budget.version + 1
    reservations = {item.invocation_key: item for item in terminal_budget.reservations}
    assert all(item.status == "settled" for item in reservations.values())
    settled_report_usage = reservations[report.reservation.invocation_key].actual_usage
    assert settled_report_usage is not None
    assert 3 <= settled_report_usage.active_seconds <= report_maxima.active_seconds
    assert settled_report_usage.artifact_bytes == sealed.size_bytes
    assert (
        reservations[orphan.reservation.invocation_key].actual_usage
        == orphan.reservation.resource_maxima
    )
    assert terminal_budget.consumed == repository._billed_deepsearch_budget_usage(
        terminal_budget.reservations
    )


def test_terminal_report_persistence_timeout_rolls_back_the_seal_and_budget(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalization-report-timeout.sqlite3")
    run, plan = _seed_running_deepsearch(repository, run_id="run_report_store_timeout")
    review_plan, review_run, staging, sealed = _advance_to_review_v0(
        repository,
        run=run,
        plan=plan,
    )
    assert sealed.size_bytes is not None
    report_budget = _reserve_finalization_transition(
        repository,
        run_id=run.id,
        operation="report-store-timeout",
        resource_maxima=DeepSearchBudgetUsageV1(
            active_seconds=30,
            artifact_bytes=262_144,
        ),
        actual_usage=DeepSearchBudgetUsageV1(artifact_bytes=sealed.size_bytes),
    )
    V1VerifiedArtifactStore(repository).create_staging_report(staging)
    plan_before = repository.get_skill_plan(plan.id)
    run_before = repository.get_agent_run(run.id)
    terminal_kwargs = {
        "run_id": run.id,
        "plan_id": plan.id,
        "expected_plan_version": plan.version,
        "expected_finalization_version": review_plan.finalization_version,
        "expected_stage": review_plan.finalization_stage,
        "expected_plan_status": review_plan.status,
        "expected_run_status": review_run.status,
        "staging_artifact_id": staging.id,
        "sealed_report": sealed,
        "terminal_status": AgentRunStatus.COMPLETED,
        "error_code": None,
        "input_hash": "8" * 64,
        "events": [
            (
                "run_completed",
                {
                    "plan_id": plan.id,
                    "report_artifact_id": sealed.id,
                    "error_code": None,
                },
            )
        ],
    }
    with pytest.raises(DeepSearchBudgetConflict, match="deepsearch_budget_request_invalid"):
        repository.commit_deepsearch_terminal_with_report(**terminal_kwargs)

    ticks = iter([10.0, 41.0])
    monkeypatch.setattr(store_module, "monotonic", lambda: next(ticks))

    with pytest.raises(DeepSearchBudgetConflict, match="deepsearch_budget_exhausted"):
        repository.commit_deepsearch_terminal_with_report(
            **terminal_kwargs,
            **report_budget,
        )

    assert repository.get_artifact(staging.id) == staging
    assert repository.get_skill_plan(plan.id) == plan_before
    assert repository.get_agent_run(run.id) == run_before


def test_failed_staging_report_and_failed_plan_run_commit_together(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalization-report-failed.sqlite3")
    run, plan = _seed_running_deepsearch(repository, run_id="run_report_failed")
    review_plan, review_run, staging, _sealed = _advance_to_review_v0(
        repository,
        run=run,
        plan=plan,
    )
    V1VerifiedArtifactStore(repository).create_staging_report(staging)
    failed = staging.model_copy(
        update={
            "verification_state": ArtifactVerificationState.FAILED,
            "updated_at": NOW + timedelta(minutes=6),
        }
    )
    error_code = "deepsearch_report_persistence_failed"

    committed = repository.fail_deepsearch_staging_report_and_commit_terminal(
        run_id=run.id,
        plan_id=plan.id,
        expected_plan_version=plan.version,
        expected_finalization_version=review_plan.finalization_version,
        expected_stage=review_plan.finalization_stage,
        expected_plan_status=review_plan.status,
        expected_run_status=review_run.status,
        staging_artifact_id=staging.id,
        failed_report=failed,
        error_code=error_code,
        input_hash="5" * 64,
        events=[
            (
                "run_failed",
                {"plan_id": plan.id, "error_code": error_code},
            )
        ],
    )

    assert committed is not None
    terminal_plan, terminal_run = committed
    assert terminal_plan.status is SkillPlanStatus.FAILED
    assert terminal_plan.finalization_stage is DeepSearchFinalizationStage.TERMINAL_COMMITTED
    assert terminal_plan.report_artifact_id is None
    assert terminal_plan.report_content_hash is None
    assert terminal_run.status is AgentRunStatus.FAILED
    assert terminal_run.output_text is None
    assert terminal_run.error_code == error_code
    assert repository.get_artifact(staging.id) == failed
    assert repository.list_agent_run_events(run.id)[-1].event_type == "run_failed"


def test_terminal_report_seal_rolls_back_to_staging_when_plan_write_fails(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-finalization-report-rollback.sqlite3")
    run, plan = _seed_running_deepsearch(repository, run_id="run_report_rollback")
    review_plan, review_run, staging, sealed = _advance_to_review_v0(
        repository,
        run=run,
        plan=plan,
    )
    assert sealed.size_bytes is not None
    report_budget = _reserve_finalization_transition(
        repository,
        run_id=run.id,
        operation="report-rollback",
        resource_maxima=DeepSearchBudgetUsageV1(
            active_seconds=30,
            artifact_bytes=262_144,
        ),
        actual_usage=DeepSearchBudgetUsageV1(artifact_bytes=sealed.size_bytes),
    )
    V1VerifiedArtifactStore(repository).create_staging_report(staging)
    plan_before = repository.get_skill_plan(plan.id)
    run_before = repository.get_agent_run(run.id)
    events_before = repository.list_agent_run_events(run.id)

    def fail_plan_write(*_args, **_kwargs) -> None:
        raise RuntimeError("injected terminal plan write failure")

    with monkeypatch.context() as patch:
        patch.setattr(repository, "_write_skill_plan", fail_plan_write)
        with pytest.raises(RuntimeError, match="injected terminal plan write failure"):
            repository.commit_deepsearch_terminal_with_report(
                run_id=run.id,
                plan_id=plan.id,
                expected_plan_version=plan.version,
                expected_finalization_version=review_plan.finalization_version,
                expected_stage=review_plan.finalization_stage,
                expected_plan_status=review_plan.status,
                expected_run_status=review_run.status,
                staging_artifact_id=staging.id,
                sealed_report=sealed,
                terminal_status=AgentRunStatus.COMPLETED,
                error_code=None,
                input_hash="5" * 64,
                events=[
                    (
                        "run_completed",
                        {
                            "plan_id": plan.id,
                            "report_artifact_id": sealed.id,
                            "error_code": None,
                        },
                    )
                ],
                **report_budget,
            )

    assert repository.get_artifact(staging.id) == staging
    assert repository.get_skill_plan(plan.id) == plan_before
    assert repository.get_agent_run(run.id) == run_before
    assert repository.list_agent_run_events(run.id) == events_before


@pytest.mark.parametrize(
    ("report_status", "terminal_status", "error_code", "event_type"),
    [
        ("complete", AgentRunStatus.PARTIAL, "deepsearch_partial", "run_partial"),
        ("partial", AgentRunStatus.COMPLETED, None, "run_completed"),
    ],
)
def test_terminal_report_rejects_report_and_terminal_status_mismatch(
    tmp_path,
    report_status: str,
    terminal_status: AgentRunStatus,
    error_code: str | None,
    event_type: str,
) -> None:
    repository = SQLiteStore(
        tmp_path / f"deepsearch-finalization-status-mismatch-{report_status}.sqlite3"
    )
    run, plan = _seed_running_deepsearch(
        repository,
        run_id=f"run_status_mismatch_{report_status}",
    )
    review_plan, review_run, staging, sealed = _advance_to_review_v0(
        repository,
        run=run,
        plan=plan,
        report_status=report_status,
    )
    V1VerifiedArtifactStore(repository).create_staging_report(staging)
    plan_before = repository.get_skill_plan(plan.id)
    run_before = repository.get_agent_run(run.id)
    events_before = repository.list_agent_run_events(run.id)

    with pytest.raises(ResearchStoreConflict, match="terminal report is invalid"):
        repository.commit_deepsearch_terminal_with_report(
            run_id=run.id,
            plan_id=plan.id,
            expected_plan_version=plan.version,
            expected_finalization_version=review_plan.finalization_version,
            expected_stage=review_plan.finalization_stage,
            expected_plan_status=review_plan.status,
            expected_run_status=review_run.status,
            staging_artifact_id=staging.id,
            sealed_report=sealed,
            terminal_status=terminal_status,
            error_code=error_code,
            input_hash="5" * 64,
            events=[
                (
                    event_type,
                    {
                        "plan_id": plan.id,
                        "report_artifact_id": sealed.id,
                        "error_code": error_code,
                    },
                )
            ],
        )

    assert repository.get_artifact(staging.id) == staging
    assert repository.get_skill_plan(plan.id) == plan_before
    assert repository.get_agent_run(run.id) == run_before
    assert repository.list_agent_run_events(run.id) == events_before


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("synthesis_content_hash", "b" * 64),
        ("problem_graph_hash", "c" * 64),
        ("review_outcome", "block"),
    ],
)
def test_terminal_report_rejects_review_hash_and_lineage_mismatch(
    tmp_path,
    field: str,
    bad_value: str,
) -> None:
    repository = SQLiteStore(
        tmp_path / f"deepsearch-finalization-lineage-mismatch-{field}.sqlite3"
    )
    run, plan = _seed_running_deepsearch(
        repository,
        run_id=f"run_lineage_mismatch_{field}",
    )
    review_plan, review_run, staging, sealed = _advance_to_review_v0(
        repository,
        run=run,
        plan=plan,
    )
    report = DeepSearchReportV1.model_validate_json(sealed.content).model_copy(
        update={field: bad_value}
    )
    _unused_staging, mismatched_sealed = build_deepsearch_report_artifacts(
        run=run,
        plan=plan,
        report=report,
        created_at=staging.created_at,
    )
    assert mismatched_sealed.size_bytes is not None
    report_budget = _reserve_finalization_transition(
        repository,
        run_id=run.id,
        operation=f"report-lineage-{field}",
        resource_maxima=DeepSearchBudgetUsageV1(
            active_seconds=30,
            artifact_bytes=262_144,
        ),
        actual_usage=DeepSearchBudgetUsageV1(
            artifact_bytes=mismatched_sealed.size_bytes,
        ),
    )
    V1VerifiedArtifactStore(repository).create_staging_report(staging)
    plan_before = repository.get_skill_plan(plan.id)
    run_before = repository.get_agent_run(run.id)
    events_before = repository.list_agent_run_events(run.id)

    with pytest.raises(ResearchStoreConflict, match="terminal report lineage is invalid"):
        repository.commit_deepsearch_terminal_with_report(
            run_id=run.id,
            plan_id=plan.id,
            expected_plan_version=plan.version,
            expected_finalization_version=review_plan.finalization_version,
            expected_stage=review_plan.finalization_stage,
            expected_plan_status=review_plan.status,
            expected_run_status=review_run.status,
            staging_artifact_id=staging.id,
            sealed_report=mismatched_sealed,
            terminal_status=AgentRunStatus.COMPLETED,
            error_code=None,
            input_hash="5" * 64,
            events=[
                (
                    "run_completed",
                    {
                        "plan_id": plan.id,
                        "report_artifact_id": sealed.id,
                        "error_code": None,
                    },
                )
            ],
            **report_budget,
        )

    assert repository.get_artifact(staging.id) == staging
    assert repository.get_skill_plan(plan.id) == plan_before
    assert repository.get_agent_run(run.id) == run_before
    assert repository.list_agent_run_events(run.id) == events_before
