from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.models import (
    AgentPlanningMode,
    DeepSearchEvidenceBindingDraft,
    DeepSearchEvidenceCoverageV1,
    DeepSearchEvidenceItemV1,
    DeepSearchFinalizationStage,
    DeepSearchReportReviewV1,
    DeepSearchReviewOutcomeV1,
    DeepSearchSynthesisClaimV1,
    DeepSearchSynthesisV1,
    DeepSearchToolInvocationV1,
    SkillIntent,
    SkillNodeResult,
    SkillPlan,
)


def test_deepsearch_finalization_stage_is_a_closed_ordered_checkpoint_set() -> None:
    assert [stage.value for stage in DeepSearchFinalizationStage] == [
        "none",
        "nodes_terminal",
        "evidence_manifest_sealed",
        "synthesis_v0_saved",
        "coverage_v0_checked",
        "review_v0_checked",
        "synthesis_v1_saved",
        "coverage_v1_checked",
        "review_v1_checked",
        "terminal_committed",
    ]


def test_deepsearch_synthesis_rejects_duplicate_claim_identity_or_payload() -> None:
    claim = DeepSearchSynthesisClaimV1(
        id="claim_a",
        text="The market is growing.",
        question_ids=["question_a"],
        success_criterion_ids=["criterion_a"],
        node_result_ids=["result_a"],
        evidence_item_ids=["evidence_a"],
        source_ids=["source_a"],
    )

    with pytest.raises(ValidationError, match="claim IDs must be unique"):
        DeepSearchSynthesisV1(
            revision_count=0,
            synthesis_mode="model",
            claims=[claim, claim],
        )

    with pytest.raises(ValidationError, match="canonical claim payloads must be unique"):
        DeepSearchSynthesisV1(
            revision_count=0,
            synthesis_mode="model",
            claims=[claim, claim.model_copy(update={"id": "claim_b"})],
        )

    with pytest.raises(ValidationError):
        DeepSearchSynthesisV1.model_validate(
            {
                "schema_version": "deepsearch-synthesis-v1",
                "revision_count": 0,
                "synthesis_mode": "model",
                "claims": [],
                "unexpected": True,
            }
        )


def test_evidence_coverage_requires_complete_disjoint_coverage_partitions() -> None:
    coverage = DeepSearchEvidenceCoverageV1(
        revision_count=0,
        synthesis_content_hash="a" * 64,
        required_question_ids=["question_a", "question_b"],
        covered_question_ids=["question_a"],
        uncovered_question_ids=["question_b"],
        required_success_criterion_ids=["criterion_a"],
        covered_success_criterion_ids=["criterion_a"],
        uncovered_success_criterion_ids=[],
        validated_claim_ids=["claim_a"],
        invalid_claim_ids=[],
        validated_source_ids=["source_a"],
        invalid_source_ids=[],
        validated_node_result_ids=["result_a"],
        invalid_node_result_ids=[],
        external_evidence_is_real=True,
        passed=False,
        gap_codes=["question_uncovered"],
    )

    assert coverage.schema_version == "deepsearch-evidence-coverage-v1"

    with pytest.raises(ValidationError, match="question coverage must partition required IDs"):
        DeepSearchEvidenceCoverageV1.model_validate(
            coverage.model_dump(mode="python")
            | {"covered_question_ids": ["question_a", "question_b"]}
        )


def test_review_outcome_must_match_its_review_checkpoint() -> None:
    review = DeepSearchReportReviewV1(
        requirement_version_id="requirement_v1",
        requirement_content_hash="a" * 64,
        problem_graph_hash="b" * 64,
        plan_id="plan_a",
        plan_version=3,
        plan_content_hash="c" * 64,
        synthesis_content_hash="d" * 64,
        verdict="pass",
        revision_count=0,
        reviewer_type="model",
        reviewed_at=datetime(2026, 8, 27, tzinfo=UTC),
    )

    outcome = DeepSearchReviewOutcomeV1(
        revision_count=0,
        synthesis_content_hash="d" * 64,
        outcome="pass",
        review=review,
    )
    assert outcome.reason_code is None

    with pytest.raises(ValidationError, match="must match its review"):
        DeepSearchReviewOutcomeV1(
            revision_count=0,
            synthesis_content_hash="e" * 64,
            outcome="pass",
            review=review,
        )

    with pytest.raises(ValidationError, match="not_run review outcomes require"):
        DeepSearchReviewOutcomeV1(
            revision_count=0,
            synthesis_content_hash="d" * 64,
            outcome="not_run",
            reason_code="arbitrary_reason",
        )


def test_standard_plan_has_empty_backward_compatible_finalization_state() -> None:
    plan = SkillPlan(run_id="run_standard", intent=SkillIntent(goal="Answer briefly"))

    assert plan.planning_mode is AgentPlanningMode.STANDARD
    assert plan.evidence_manifest_artifact_id is None
    assert plan.evidence_manifest_hash is None
    assert plan.evidence_coverage is None
    assert plan.deepsearch_syntheses == []
    assert plan.synthesis_content_hashes == []
    assert plan.review_outcomes == []
    assert plan.report_revision_count == 0
    assert plan.report_artifact_id is None
    assert plan.report_content_hash is None
    assert plan.finalization_stage is DeepSearchFinalizationStage.NONE
    assert plan.finalization_version == 0
    assert plan.finalization_input_hashes == {}


def test_plan_rejects_synthesis_hash_that_does_not_match_canonical_content() -> None:
    synthesis = DeepSearchSynthesisV1(
        revision_count=0,
        synthesis_mode="model",
        claims=[
            DeepSearchSynthesisClaimV1(
                id="claim_a",
                text="The market is growing.",
                question_ids=["question_a"],
                success_criterion_ids=["criterion_a"],
                node_result_ids=["result_a"],
                evidence_item_ids=["evidence_a"],
                source_ids=["source_a"],
            )
        ],
    )
    assert canonical_json_sha256(synthesis.model_dump(mode="python")) != "f" * 64

    with pytest.raises(ValidationError, match="synthesis content hashes must match"):
        SkillPlan(
            run_id="run_deepsearch",
            intent=SkillIntent(goal="Research the market"),
            planning_mode=AgentPlanningMode.DEEPSEARCH,
            deepsearch_syntheses=[synthesis],
            synthesis_content_hashes=["f" * 64],
        )


def test_plan_rejects_coverage_for_an_unknown_synthesis_revision() -> None:
    synthesis = DeepSearchSynthesisV1(
        revision_count=0,
        synthesis_mode="model",
        claims=[],
    )
    synthesis_hash = canonical_json_sha256(synthesis.model_dump(mode="python"))
    coverage = DeepSearchEvidenceCoverageV1(
        revision_count=1,
        synthesis_content_hash="e" * 64,
        required_question_ids=[],
        covered_question_ids=[],
        uncovered_question_ids=[],
        required_success_criterion_ids=[],
        covered_success_criterion_ids=[],
        uncovered_success_criterion_ids=[],
        external_evidence_is_real=True,
        passed=True,
    )

    with pytest.raises(ValidationError, match="evidence coverage must match a synthesis revision"):
        SkillPlan(
            run_id="run_deepsearch",
            intent=SkillIntent(goal="Research the market"),
            planning_mode=AgentPlanningMode.DEEPSEARCH,
            deepsearch_syntheses=[synthesis],
            synthesis_content_hashes=[synthesis_hash],
            evidence_coverage=coverage,
        )


def test_plan_rejects_review_outcome_for_a_different_synthesis() -> None:
    synthesis = DeepSearchSynthesisV1(
        revision_count=0,
        synthesis_mode="deterministic_evidence_digest",
        claims=[],
    )
    synthesis_hash = canonical_json_sha256(synthesis.model_dump(mode="python"))
    outcome = DeepSearchReviewOutcomeV1(
        revision_count=0,
        synthesis_content_hash="e" * 64,
        outcome="not_run",
        reason_code="deterministic_digest",
    )

    with pytest.raises(ValidationError, match="review outcomes must match synthesis revisions"):
        SkillPlan(
            run_id="run_deepsearch",
            intent=SkillIntent(goal="Research the market"),
            planning_mode=AgentPlanningMode.DEEPSEARCH,
            deepsearch_syntheses=[synthesis],
            synthesis_content_hashes=[synthesis_hash],
            review_outcomes=[outcome],
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"evidence_manifest_artifact_id": "artifact_manifest"}, "evidence manifest artifact and hash"),
        ({"report_artifact_id": "artifact_report"}, "report artifact and hash"),
        ({"finalization_version": 1}, "none finalization stage requires version zero"),
        ({"report_revision_count": 1}, "report revision must match the latest synthesis"),
    ],
)
def test_plan_rejects_incomplete_finalization_checkpoint_state(
    overrides: dict[str, object],
    message: str,
) -> None:
    payload = SkillPlan(
        run_id="run_deepsearch",
        intent=SkillIntent(goal="Research the market"),
        planning_mode=AgentPlanningMode.DEEPSEARCH,
    ).model_dump(mode="python")

    with pytest.raises(ValidationError, match=message):
        SkillPlan.model_validate(payload | overrides)


def test_plan_accepts_two_ordered_synthesis_and_review_revisions() -> None:
    syntheses = [
        DeepSearchSynthesisV1(revision_count=0, synthesis_mode="model", claims=[]),
        DeepSearchSynthesisV1(revision_count=1, synthesis_mode="model", claims=[]),
    ]
    synthesis_hashes = [
        canonical_json_sha256(synthesis.model_dump(mode="python"))
        for synthesis in syntheses
    ]
    reviews = [
        DeepSearchReportReviewV1(
            requirement_version_id="requirement_v1",
            requirement_content_hash="a" * 64,
            problem_graph_hash="b" * 64,
            plan_id="plan_deepsearch",
            plan_version=3,
            plan_content_hash="c" * 64,
            synthesis_content_hash=synthesis_hashes[revision],
            verdict=verdict,
            limitation_codes=(
                ["deepsearch_review_not_passed"] if verdict == "revise" else []
            ),
            revision_count=revision,
            reviewer_type="model",
            reviewed_at=datetime(2026, 8, 27, tzinfo=UTC),
        )
        for revision, verdict in enumerate(("revise", "pass"))
    ]
    outcomes = [
        DeepSearchReviewOutcomeV1(
            revision_count=revision,
            synthesis_content_hash=synthesis_hashes[revision],
            outcome=review.verdict,
            review=review,
        )
        for revision, review in enumerate(reviews)
    ]
    coverage = DeepSearchEvidenceCoverageV1(
        revision_count=1,
        synthesis_content_hash=synthesis_hashes[1],
        required_question_ids=[],
        covered_question_ids=[],
        uncovered_question_ids=[],
        required_success_criterion_ids=[],
        covered_success_criterion_ids=[],
        uncovered_success_criterion_ids=[],
        external_evidence_is_real=True,
        passed=True,
    )

    plan = SkillPlan(
        id="plan_deepsearch",
        run_id="run_deepsearch",
        version=3,
        intent=SkillIntent(goal="Research the market"),
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        evidence_manifest_artifact_id="artifact_manifest",
        evidence_manifest_hash="d" * 64,
        evidence_coverage=coverage,
        deepsearch_syntheses=syntheses,
        synthesis_content_hashes=synthesis_hashes,
        review_outcomes=outcomes,
        report_revision_count=1,
        report_artifact_id="artifact_report",
        report_content_hash="e" * 64,
        finalization_stage=DeepSearchFinalizationStage.TERMINAL_COMMITTED,
        finalization_version=9,
        finalization_input_hashes={
            DeepSearchFinalizationStage.NODES_TERMINAL: "f" * 64,
            DeepSearchFinalizationStage.TERMINAL_COMMITTED: "0" * 64,
        },
    )

    payload = plan.model_dump(mode="json")
    assert payload["finalization_input_hashes"] == {
        "nodes_terminal": "f" * 64,
        "terminal_committed": "0" * 64,
    }
    assert SkillPlan.model_validate(payload) == plan


def test_evidence_binding_draft_cannot_accept_server_owned_identity() -> None:
    binding = {
        "question_ids": ["question_a"],
        "success_criterion_ids": ["criterion_a"],
        "source_id": "source_a",
        "evidence_artifact_id": "artifact_evidence_a",
    }

    assert DeepSearchEvidenceBindingDraft.model_validate(binding).source_id == "source_a"
    with pytest.raises(ValidationError):
        DeepSearchEvidenceBindingDraft.model_validate(binding | {"id": "evidence_a"})
    with pytest.raises(ValidationError):
        DeepSearchEvidenceBindingDraft.model_validate(binding | {"node_result_id": "result_a"})


def test_evidence_item_rejects_duplicate_semantic_references() -> None:
    with pytest.raises(ValidationError, match="evidence references must be unique"):
        DeepSearchEvidenceItemV1(
            id="evidence_a",
            question_ids=["question_a", "question_a"],
            success_criterion_ids=["criterion_a"],
            node_result_id="result_a",
            source_id="source_a",
            evidence_artifact_id="artifact_evidence_a",
        )


def test_tool_invocation_requires_complete_lineage_and_hash_operation_key() -> None:
    invocation = {
        "run_id": "run_a",
        "requirement_version_id": "requirement_v1",
        "plan_id": "plan_a",
        "plan_version": 3,
        "node_id": "node_a",
        "node_attempt": 1,
        "tool_definition_id": "tool_web_search",
        "implementation_id": "web_search_real",
        "implementation_version": "1",
        "tool_call_id": "tool_call_a",
        "operation_key": "a" * 64,
        "canonical_arguments_hash": "b" * 64,
    }

    assert DeepSearchToolInvocationV1.model_validate(invocation).node_attempt == 1
    with pytest.raises(ValidationError):
        DeepSearchToolInvocationV1.model_validate(invocation | {"operation_key": "not-a-hash"})
    incomplete = dict(invocation)
    del incomplete["node_id"]
    with pytest.raises(ValidationError):
        DeepSearchToolInvocationV1.model_validate(incomplete)


def test_node_result_defaults_evidence_empty_and_enforces_server_lineage() -> None:
    base = {
        "id": "result_a",
        "node_id": "node_a",
        "skill_id": "skill_a",
        "summary": "Evidence-backed result",
    }
    assert SkillNodeResult.model_validate(base).evidence_items == []

    evidence_item = DeepSearchEvidenceItemV1(
        id="evidence_a",
        question_ids=["question_a"],
        success_criterion_ids=["criterion_a"],
        node_result_id="result_a",
        source_id="source_a",
        evidence_artifact_id="artifact_evidence_a",
    )
    result = SkillNodeResult.model_validate(base | {"evidence_items": [evidence_item]})
    assert result.evidence_items == [evidence_item]

    with pytest.raises(ValidationError, match="evidence item lineage must match"):
        SkillNodeResult.model_validate(
            base
            | {
                "evidence_items": [
                    evidence_item.model_copy(update={"node_result_id": "result_other"})
                ]
            }
        )

    with pytest.raises(ValidationError, match="evidence item IDs must be unique"):
        SkillNodeResult.model_validate(base | {"evidence_items": [evidence_item, evidence_item]})
