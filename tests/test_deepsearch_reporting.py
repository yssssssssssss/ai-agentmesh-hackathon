from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import agentmesh.deepsearch.reporting as reporting_module
from agentmesh.artifacts import DeepSearchArtifactSchemaRegistry, TrustedEvidenceEnvelopeV1
from agentmesh.canonical_json import canonical_json_bytes, canonical_json_sha256
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
from agentmesh.deepsearch.finalization import _with_required_synthesis_sections
from agentmesh.deepsearch.planning import plan_content_hash
from agentmesh.deepsearch.reporting import (
    DEEPSEARCH_EVIDENCE_MANIFEST_MAX_BYTES,
    DeepSearchReportingError,
    build_deepsearch_report,
    build_deepsearch_report_artifacts,
    build_deterministic_evidence_digest,
    build_evidence_manifest_artifact,
    decide_deepsearch_terminal,
    deepsearch_claim_id,
    evaluate_evidence_coverage,
    materialize_deepsearch_review,
    materialize_deepsearch_synthesis,
    select_safe_claims,
)
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    Artifact,
    ArtifactVerificationState,
    DeepSearchBudgetV1,
    DeepSearchEvidenceItemV1,
    DeepSearchReportReviewV1,
    DeepSearchReviewOutcomeV1,
    DeepSearchSynthesisClaimV1,
    DeepSearchSynthesisV1,
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

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _resource_manifest() -> SkillResourceManifestV1:
    payload = {
        "schema_version": "skill-resource-manifest-v1",
        "required_resources": [],
        "resource_hashes": {},
    }
    return SkillResourceManifestV1(**payload, content_hash=canonical_json_sha256(payload))


def _fixture() -> tuple[
    AgentRun,
    SkillPlan,
    RequirementVersionV1,
    ProblemGraphV1,
    SkillNodeResult,
    Artifact,
]:
    run = AgentRun(
        id="run_reporting",
        thread_id="thread_reporting",
        user_id="user_reporting",
        workspace_id="workspace_reporting",
        project_id="project_reporting",
        input_text="Compare collaboration platforms",
        client_turn_id="turn_reporting",
        status=AgentRunStatus.RUNNING,
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
        orchestration_version="v1",
        orchestration_mode="execute",
        absolute_expires_at=NOW + timedelta(days=7),
        deepsearch_budget=DeepSearchBudgetV1(),
        created_at=NOW,
        updated_at=NOW,
    )
    payload = RequirementPayloadV1(
        goal=run.input_text,
        scope=RequirementScopeV1(regions=["China"]),
        success_criteria=[
            RequirementSuccessCriterionV1(
                id="criterion_market",
                statement="Identify the leading platforms",
            )
        ],
        deliverables=["Research report"],
    )
    requirement = RequirementVersionV1(
        id="requirement_reporting_v1",
        run_id=run.id,
        version=1,
        request_key=run.client_turn_id or "",
        request_hash="1" * 64,
        content_hash=requirement_content_hash(payload),
        payload=payload,
        created_at=NOW,
    )
    question = ProblemQuestionV1(
        id=problem_question_id("Which platforms lead the market?"),
        question="Which platforms lead the market?",
        required=True,
        success_criterion_ids=["criterion_market"],
        evidence_requirements=["Current public sources"],
        acceptance_criteria=["Name at least one supported platform"],
    )
    graph = build_problem_graph(requirement=requirement, questions=[question])
    node = SkillPlanNode(
        id="node_reporting",
        skill_id="skill_research",
        skill_version="1",
        skill_content_hash="2" * 64,
        reason="Collect market evidence",
        question_ids=[question.id],
        output_contract=["research_evidence"],
        required_tool_names=["web_research"],
        resource_manifest=_resource_manifest(),
        status=SkillPlanNodeStatus.COMPLETED,
        attempt=1,
        completed_at=NOW,
    )
    plan = SkillPlan(
        id="plan_reporting",
        run_id=run.id,
        status=SkillPlanStatus.RUNNING,
        intent=SkillIntent(
            goal=run.input_text,
            external_evidence_required=True,
        ),
        candidate_skill_ids=[node.skill_id],
        output_contract=["research_evidence"],
        nodes=[node],
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        requirement_version_id=requirement.id,
        requirement_content_hash=requirement.content_hash,
        problem_graph=graph.model_dump(mode="json"),
        problem_graph_hash=graph.content_hash,
    )
    plan.plan_content_hash = plan_content_hash(plan)
    run = run.model_copy(update={"plan_id": plan.id})

    excerpt = "Platform A leads the measured sample."
    envelope = TrustedEvidenceEnvelopeV1(
        schema_version="deepsearch-tool-evidence-v1",
        origin_type="tool",
        run_id=run.id,
        requirement_version_id=requirement.id,
        plan_id=plan.id,
        plan_version=plan.version,
        node_id=node.id,
        attempt=1,
        tool_name="web_research",
        tool_implementation_id="gateway.web_research",
        tool_implementation_version="1",
        execution_mode="real",
        content_provider="provider",
        tool_call_id="tool_call_reporting",
        operation_key="3" * 64,
        request_hash="4" * 64,
        source_id="source_reporting",
        source_ordinal=0,
        normalized_reference="https://example.test/report",
        retrieved_at=NOW,
        excerpt=excerpt,
        content_hash=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
        size_bytes=len(excerpt.encode("utf-8")),
    )
    content = canonical_json_bytes(envelope.model_dump(mode="python")).decode("utf-8")
    encoded = content.encode("utf-8")
    artifact = Artifact(
        id="artifact_evidence_reporting",
        run_id=run.id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        user_id=run.user_id,
        artifact_type="deepsearch_tool_evidence",
        content_type="application/json",
        content=content,
        verification_state=ArtifactVerificationState.SEALED,
        schema_version="deepsearch-tool-evidence-v1",
        content_hash=hashlib.sha256(encoded).hexdigest(),
        size_bytes=len(encoded),
        requirement_version_id=requirement.id,
        plan_version_id=f"{plan.id}:v{plan.version}",
        attempt_id=f"{node.id}:attempt:1",
        step_number=1,
        created_at=NOW,
        updated_at=NOW,
    )
    evidence_id = "evidence_" + canonical_json_sha256(
        {
            "node_result_id": "result_reporting",
            "evidence_artifact_id": artifact.id,
            "question_ids": [question.id],
            "success_criterion_ids": ["criterion_market"],
        }
    )
    result = SkillNodeResult(
        id="result_reporting",
        node_id=node.id,
        skill_id=node.skill_id,
        summary="Collected one source",
        attempt=1,
        evidence_items=[
            DeepSearchEvidenceItemV1(
                id=evidence_id,
                node_result_id="result_reporting",
                question_ids=[question.id],
                success_criterion_ids=["criterion_market"],
                source_id=envelope.source_id,
                evidence_artifact_id=artifact.id,
            )
        ],
    )
    return run, plan, requirement, graph, result, artifact


def test_manifest_digest_and_coverage_form_a_deterministic_trusted_chain() -> None:
    run, plan, requirement, graph, result, evidence_artifact = _fixture()

    manifest, manifest_artifact = build_evidence_manifest_artifact(
        run=run,
        plan=plan,
        requirement=requirement,
        graph=graph,
        results=[result],
        evidence_artifacts={evidence_artifact.id: evidence_artifact},
        created_at=NOW,
    )
    replay_manifest, replay_artifact = build_evidence_manifest_artifact(
        run=run,
        plan=plan,
        requirement=requirement,
        graph=graph,
        results=[result],
        evidence_artifacts={evidence_artifact.id: evidence_artifact},
        created_at=NOW,
    )

    assert replay_manifest == manifest
    assert replay_artifact == manifest_artifact
    assert manifest_artifact.verification_state is ArtifactVerificationState.SEALED
    synthesis = build_deterministic_evidence_digest(
        run=run,
        plan=plan,
        manifest=manifest,
        evidence_artifacts={evidence_artifact.id: evidence_artifact},
    )
    assert synthesis.claims[0].text == "Platform A leads the measured sample."

    coverage = evaluate_evidence_coverage(
        run=run,
        plan=plan,
        requirement=requirement,
        graph=graph,
        results=[result],
        manifest=manifest,
        evidence_artifacts={evidence_artifact.id: evidence_artifact},
        synthesis=synthesis,
    )

    assert coverage.passed is True
    assert coverage.external_evidence_is_real is True
    assert coverage.uncovered_question_ids == []
    assert coverage.uncovered_success_criterion_ids == []


@pytest.mark.parametrize(
    ("size_bytes", "accepted"),
    [
        (DEEPSEARCH_EVIDENCE_MANIFEST_MAX_BYTES, True),
        (DEEPSEARCH_EVIDENCE_MANIFEST_MAX_BYTES + 1, False),
    ],
)
def test_manifest_enforces_its_canonical_byte_limit(
    size_bytes: int,
    accepted: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, plan, requirement, graph, result, evidence_artifact = _fixture()
    monkeypatch.setattr(
        reporting_module,
        "canonical_json_bytes",
        lambda _payload: b"x" * size_bytes,
    )

    if not accepted:
        with pytest.raises(DeepSearchReportingError, match="deepsearch_delivery_unavailable"):
            build_evidence_manifest_artifact(
                run=run,
                plan=plan,
                requirement=requirement,
                graph=graph,
                results=[result],
                evidence_artifacts={evidence_artifact.id: evidence_artifact},
                created_at=NOW,
            )
        return

    _manifest, artifact = build_evidence_manifest_artifact(
        run=run,
        plan=plan,
        requirement=requirement,
        graph=graph,
        results=[result],
        evidence_artifacts={evidence_artifact.id: evidence_artifact},
        created_at=NOW,
    )
    assert artifact.size_bytes == DEEPSEARCH_EVIDENCE_MANIFEST_MAX_BYTES


def test_manifest_rejects_cross_attempt_tool_evidence() -> None:
    run, plan, requirement, graph, result, evidence_artifact = _fixture()
    stale = evidence_artifact.model_copy(
        update={"attempt_id": "node_reporting:attempt:2", "step_number": 2}
    )

    with pytest.raises(DeepSearchReportingError, match="deepsearch_evidence_integrity_failed"):
        build_evidence_manifest_artifact(
            run=run,
            plan=plan,
            requirement=requirement,
            graph=graph,
            results=[result],
            evidence_artifacts={stale.id: stale},
            created_at=NOW,
        )


def test_coverage_rejects_a_source_only_claim_without_evidence_item_lineage() -> None:
    run, plan, requirement, graph, result, evidence_artifact = _fixture()
    manifest, _artifact = build_evidence_manifest_artifact(
        run=run,
        plan=plan,
        requirement=requirement,
        graph=graph,
        results=[result],
        evidence_artifacts={evidence_artifact.id: evidence_artifact},
        created_at=NOW,
    )
    question_id = graph.questions[0].id
    payload = {
        "text": "Unsupported model statement",
        "question_ids": [question_id],
        "success_criterion_ids": ["criterion_market"],
        "node_result_ids": [result.id],
        "evidence_item_ids": [],
        "source_ids": ["source_reporting"],
        "recommendation": False,
    }
    claim = DeepSearchSynthesisClaimV1(
        id=deepsearch_claim_id(
            run_id=run.id,
            plan_id=plan.id,
            plan_version=plan.version,
            revision_count=0,
            ordinal=1,
            claim=payload,
        ),
        **payload,
    )
    synthesis = DeepSearchSynthesisV1(
        revision_count=0,
        synthesis_mode="model",
        claims=[claim],
    )

    coverage = evaluate_evidence_coverage(
        run=run,
        plan=plan,
        requirement=requirement,
        graph=graph,
        results=[result],
        manifest=manifest,
        evidence_artifacts={evidence_artifact.id: evidence_artifact},
        synthesis=synthesis,
    )

    assert coverage.passed is False
    assert coverage.invalid_claim_ids == [claim.id]
    assert coverage.gap_codes == [
        "claim_reference_invalid",
        "question_uncovered",
        "success_criterion_uncovered",
        "external_evidence_not_real",
    ]


def _report_inputs():
    run, plan, requirement, graph, result, evidence_artifact = _fixture()
    manifest, manifest_artifact = build_evidence_manifest_artifact(
        run=run,
        plan=plan,
        requirement=requirement,
        graph=graph,
        results=[result],
        evidence_artifacts={evidence_artifact.id: evidence_artifact},
        created_at=NOW,
    )
    digest = build_deterministic_evidence_digest(
        run=run,
        plan=plan,
        manifest=manifest,
        evidence_artifacts={evidence_artifact.id: evidence_artifact},
    )
    source = Source(
        id="source_reporting",
        title="Market report",
        source_type="web",
        reference="https://example.test/report",
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        user_id=run.user_id,
        run_id=run.id,
        skill_id="skill_research",
        created_at=NOW,
    )
    return (
        run,
        plan,
        requirement,
        graph,
        result,
        evidence_artifact,
        manifest,
        manifest_artifact,
        digest,
        source,
    )


def test_digest_fallback_builds_one_deterministic_sealable_partial_report() -> None:
    (
        run,
        plan,
        requirement,
        graph,
        result,
        evidence_artifact,
        manifest,
        manifest_artifact,
        digest,
        source,
    ) = _report_inputs()
    coverage = evaluate_evidence_coverage(
        run=run,
        plan=plan,
        requirement=requirement,
        graph=graph,
        results=[result],
        manifest=manifest,
        evidence_artifacts={evidence_artifact.id: evidence_artifact},
        synthesis=digest,
    )
    review_outcome = DeepSearchReviewOutcomeV1(
        revision_count=0,
        synthesis_content_hash=coverage.synthesis_content_hash,
        outcome="not_run",
        reason_code="deterministic_digest",
    )

    report = build_deepsearch_report(
        run=run,
        plan=plan,
        requirement=requirement,
        graph=graph,
        results=[result],
        manifest=manifest,
        manifest_artifact=manifest_artifact,
        evidence_artifacts={evidence_artifact.id: evidence_artifact},
        sources={source.id: source},
        synthesis=digest,
        coverage=coverage,
        review_outcome=review_outcome,
        report_status="partial",
    )
    staging, sealed = build_deepsearch_report_artifacts(
        run=run,
        plan=plan,
        report=report,
        created_at=NOW,
    )
    replay_staging, replay_sealed = build_deepsearch_report_artifacts(
        run=run,
        plan=plan,
        report=report,
        created_at=NOW,
    )

    assert report.report_status == "partial"
    assert report.executive_summary_claim_ids == [digest.claims[0].id]
    assert report.sources[0].normalized_reference == source.reference
    assert [item.code for item in report.limitations] == [
        "deterministic_digest",
        "deepsearch_synthesis_fallback",
    ]
    assert "状态：部分报告" in report.rendered_text
    assert staging.verification_state is ArtifactVerificationState.STAGING
    assert sealed.verification_state is ArtifactVerificationState.SEALED
    assert staging.id == sealed.id
    assert (replay_staging, replay_sealed) == (staging, sealed)
    assert DeepSearchArtifactSchemaRegistry.parse(
        sealed.artifact_type,
        sealed.schema_version or "",
        sealed.content,
    ) == report


def test_model_claim_drafts_receive_ids_and_can_form_a_complete_report() -> None:
    (
        run,
        plan,
        requirement,
        graph,
        result,
        evidence_artifact,
        manifest,
        manifest_artifact,
        digest,
        source,
    ) = _report_inputs()
    synthesis = materialize_deepsearch_synthesis(
        run=run,
        plan=plan,
        revision_count=0,
        drafts=[digest.claims[0].model_dump(mode="python", exclude={"id"})],
    )
    coverage = evaluate_evidence_coverage(
        run=run,
        plan=plan,
        requirement=requirement,
        graph=graph,
        results=[result],
        manifest=manifest,
        evidence_artifacts={evidence_artifact.id: evidence_artifact},
        synthesis=synthesis,
    )
    review = DeepSearchReportReviewV1(
        requirement_version_id=requirement.id,
        requirement_content_hash=requirement.content_hash,
        problem_graph_hash=graph.content_hash,
        plan_id=plan.id,
        plan_version=plan.version,
        plan_content_hash=plan.plan_content_hash or "",
        synthesis_content_hash=coverage.synthesis_content_hash,
        verdict="pass",
        revision_count=0,
        reviewer_type="model",
        reviewed_at=NOW,
    )
    review_outcome = DeepSearchReviewOutcomeV1(
        revision_count=0,
        synthesis_content_hash=coverage.synthesis_content_hash,
        outcome="pass",
        review=review,
    )

    report = build_deepsearch_report(
        run=run,
        plan=plan,
        requirement=requirement,
        graph=graph,
        results=[result],
        manifest=manifest,
        manifest_artifact=manifest_artifact,
        evidence_artifacts={evidence_artifact.id: evidence_artifact},
        sources={source.id: source},
        synthesis=synthesis,
        coverage=coverage,
        review_outcome=review_outcome,
        report_status="complete",
    )

    assert report.report_status == "complete"
    assert report.review_outcome == "pass"
    assert report.limitations == []
    projected = _with_required_synthesis_sections(
        plan=SimpleNamespace(
            candidate_snapshot=SimpleNamespace(
                required_synthesis_output_ids=("strategy_map", "roadmap")
            )
        ),  # type: ignore[arg-type]
        report=report,
    )
    assert {
        "synthesis_output:strategy_map",
        "synthesis_output:roadmap",
    }.issubset({section.section_id for section in projected.sections})
    assert "## 策略地图" in projected.rendered_text
    assert "## 实施路径" in projected.rendered_text
    missing = _with_required_synthesis_sections(
        plan=SimpleNamespace(
            candidate_snapshot=SimpleNamespace(
                required_synthesis_output_ids=("strategy_map", "unsupported_output")
            )
        ),  # type: ignore[arg-type]
        report=report,
    )
    assert "synthesis_output:strategy_map" in {
        section.section_id for section in missing.sections
    }
    assert "synthesis_output:unsupported_output" not in {
        section.section_id for section in missing.sections
    }
    assert decide_deepsearch_terminal(
        plan=plan,
        synthesis=synthesis,
        coverage=coverage,
        review_outcome=review_outcome,
        safe_partial_report=True,
        report_available=True,
    ).status is AgentRunStatus.COMPLETED


def test_review_draft_cannot_mint_lineage_or_reference_unknown_claims() -> None:
    (
        run,
        plan,
        requirement,
        graph,
        result,
        evidence_artifact,
        manifest,
        _manifest_artifact,
        digest,
        _source,
    ) = _report_inputs()
    synthesis = materialize_deepsearch_synthesis(
        run=run,
        plan=plan,
        revision_count=0,
        drafts=[digest.claims[0].model_dump(mode="python", exclude={"id"})],
    )
    coverage = evaluate_evidence_coverage(
        run=run,
        plan=plan,
        requirement=requirement,
        graph=graph,
        results=[result],
        manifest=manifest,
        evidence_artifacts={evidence_artifact.id: evidence_artifact},
        synthesis=synthesis,
    )

    outcome = materialize_deepsearch_review(
        run=run,
        plan=plan,
        requirement=requirement,
        graph=graph,
        synthesis=synthesis,
        draft={
            "verdict": "pass",
            "unsupported_claim_ids": [],
            "contradictory_claim_ids": [],
            "missing_section_ids": [],
            "limitation_codes": [],
        },
        reviewer_type="model",
        reviewed_at=NOW,
    )
    assert outcome.synthesis_content_hash == coverage.synthesis_content_hash
    assert outcome.review is not None
    assert outcome.review.requirement_version_id == requirement.id

    with pytest.raises(DeepSearchReportingError, match="deepsearch_review_invalid"):
        materialize_deepsearch_review(
            run=run,
            plan=plan,
            requirement=requirement,
            graph=graph,
            synthesis=synthesis,
            draft={
                "verdict": "block",
                "unsupported_claim_ids": ["claim_unknown"],
                "contradictory_claim_ids": [],
                "missing_section_ids": [],
                "limitation_codes": [],
            },
            reviewer_type="model",
            reviewed_at=NOW,
        )


def test_reviewed_claims_are_removed_before_partial_delivery() -> None:
    (
        run,
        plan,
        requirement,
        graph,
        result,
        evidence_artifact,
        manifest,
        manifest_artifact,
        digest,
        source,
    ) = _report_inputs()
    synthesis = materialize_deepsearch_synthesis(
        run=run,
        plan=plan,
        revision_count=0,
        drafts=[digest.claims[0].model_dump(mode="python", exclude={"id"})],
    )
    coverage = evaluate_evidence_coverage(
        run=run,
        plan=plan,
        requirement=requirement,
        graph=graph,
        results=[result],
        manifest=manifest,
        evidence_artifacts={evidence_artifact.id: evidence_artifact},
        synthesis=synthesis,
    )
    review = DeepSearchReportReviewV1(
        requirement_version_id=requirement.id,
        requirement_content_hash=requirement.content_hash,
        problem_graph_hash=graph.content_hash,
        plan_id=plan.id,
        plan_version=plan.version,
        plan_content_hash=plan.plan_content_hash or "",
        synthesis_content_hash=coverage.synthesis_content_hash,
        verdict="block",
        unsupported_claim_ids=[synthesis.claims[0].id],
        revision_count=0,
        reviewer_type="model",
        reviewed_at=NOW,
    )
    review_outcome = DeepSearchReviewOutcomeV1(
        revision_count=0,
        synthesis_content_hash=coverage.synthesis_content_hash,
        outcome="block",
        review=review,
    )

    assert select_safe_claims(
        synthesis=synthesis,
        coverage=coverage,
        review_outcome=review_outcome,
    ) == ()
    with pytest.raises(DeepSearchReportingError, match="deepsearch_delivery_unavailable"):
        build_deepsearch_report(
            run=run,
            plan=plan,
            requirement=requirement,
            graph=graph,
            results=[result],
            manifest=manifest,
            manifest_artifact=manifest_artifact,
            evidence_artifacts={evidence_artifact.id: evidence_artifact},
            sources={source.id: source},
            synthesis=synthesis,
            coverage=coverage,
            review_outcome=review_outcome,
            report_status="partial",
        )
    decision = decide_deepsearch_terminal(
        plan=plan,
        synthesis=synthesis,
        coverage=coverage,
        review_outcome=review_outcome,
        safe_partial_report=False,
        report_available=False,
    )
    assert decision.status is AgentRunStatus.FAILED
    assert decision.error_code == "deepsearch_delivery_unavailable"


def test_partial_report_never_leaks_a_review_rejected_claim() -> None:
    (
        run,
        plan,
        requirement,
        graph,
        result,
        evidence_artifact,
        manifest,
        manifest_artifact,
        digest,
        source,
    ) = _report_inputs()
    base = digest.claims[0].model_dump(mode="python", exclude={"id"})
    synthesis = materialize_deepsearch_synthesis(
        run=run,
        plan=plan,
        revision_count=0,
        drafts=[
            {**base, "text": "This sentence must not be published."},
            {**base, "text": "This sentence remains supported."},
        ],
    )
    coverage = evaluate_evidence_coverage(
        run=run,
        plan=plan,
        requirement=requirement,
        graph=graph,
        results=[result],
        manifest=manifest,
        evidence_artifacts={evidence_artifact.id: evidence_artifact},
        synthesis=synthesis,
    )
    review = DeepSearchReportReviewV1(
        requirement_version_id=requirement.id,
        requirement_content_hash=requirement.content_hash,
        problem_graph_hash=graph.content_hash,
        plan_id=plan.id,
        plan_version=plan.version,
        plan_content_hash=plan.plan_content_hash or "",
        synthesis_content_hash=coverage.synthesis_content_hash,
        verdict="block",
        unsupported_claim_ids=[synthesis.claims[0].id],
        revision_count=0,
        reviewer_type="model",
        reviewed_at=NOW,
    )
    review_outcome = DeepSearchReviewOutcomeV1(
        revision_count=0,
        synthesis_content_hash=coverage.synthesis_content_hash,
        outcome="block",
        review=review,
    )

    report = build_deepsearch_report(
        run=run,
        plan=plan,
        requirement=requirement,
        graph=graph,
        results=[result],
        manifest=manifest,
        manifest_artifact=manifest_artifact,
        evidence_artifacts={evidence_artifact.id: evidence_artifact},
        sources={source.id: source},
        synthesis=synthesis,
        coverage=coverage,
        review_outcome=review_outcome,
        report_status="partial",
    )

    assert [claim.text for claim in report.claims] == ["This sentence remains supported."]
    assert "This sentence must not be published." not in report.rendered_text
    assert "deepsearch_review_not_passed" in {
        limitation.code for limitation in report.limitations
    }


def test_terminal_decision_keeps_failure_precedence_and_partial_gate() -> None:
    (
        run,
        plan,
        requirement,
        graph,
        result,
        evidence_artifact,
        manifest,
        _manifest_artifact,
        digest,
        _source,
    ) = _report_inputs()
    coverage = evaluate_evidence_coverage(
        run=run,
        plan=plan,
        requirement=requirement,
        graph=graph,
        results=[result],
        manifest=manifest,
        evidence_artifacts={evidence_artifact.id: evidence_artifact},
        synthesis=digest,
    )
    outcome = DeepSearchReviewOutcomeV1(
        revision_count=0,
        synthesis_content_hash=coverage.synthesis_content_hash,
        outcome="not_run",
        reason_code="deterministic_digest",
    )

    integrity_failure = decide_deepsearch_terminal(
        plan=plan,
        synthesis=digest,
        coverage=coverage,
        review_outcome=outcome,
        safe_partial_report=True,
        report_available=True,
        budget_exhausted=True,
        evidence_integrity_failed=True,
    )
    budget_partial = decide_deepsearch_terminal(
        plan=plan,
        synthesis=digest,
        coverage=coverage,
        review_outcome=outcome,
        safe_partial_report=True,
        report_available=True,
        budget_exhausted=True,
    )
    budget_failure = decide_deepsearch_terminal(
        plan=plan,
        synthesis=digest,
        coverage=coverage,
        review_outcome=outcome,
        safe_partial_report=False,
        report_available=False,
        budget_exhausted=True,
    )

    assert integrity_failure == (
        integrity_failure.__class__(
            status=AgentRunStatus.FAILED,
            error_code="deepsearch_evidence_integrity_failed",
        )
    )
    assert budget_partial.status is AgentRunStatus.PARTIAL
    assert budget_partial.error_code == "deepsearch_budget_exhausted"
    assert budget_failure.status is AgentRunStatus.FAILED
    assert budget_failure.error_code == "deepsearch_budget_exhausted"
