from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Literal, Protocol

from pydantic import model_validator

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.catalog import (
    CompetitiveTextCatalog,
    load_catalog_document,
    read_catalog_document,
)
from agentmesh.research_orchestration.v3.common import (
    EvidenceManifestArtifactRefV3,
    Identifier,
    SealedArtifactRefV3,
    Sha256Hex,
    StrictFrozenModel,
    require_unique,
)
from agentmesh.research_orchestration.v3.deliverable import ResearchDeliverableV3
from agentmesh.research_orchestration.v3.evidence import (
    EvidenceManifestV3,
    VerifiedArtifactContentV3,
    verify_evidence_manifest_artifacts,
)
from agentmesh.research_orchestration.v3.evidence_materializer import read_verified_actor_artifacts
from agentmesh.research_orchestration.v3.execution_plan import ExecutionPlanVersionV3
from agentmesh.research_orchestration.v3.ports import (
    ActorExecutionResultV3,
    ArtifactReadPort,
    validate_review_inputs,
)
from agentmesh.research_orchestration.v3.problem_graph import ProblemGraphV1
from agentmesh.research_orchestration.v3.requirement import RequirementVersionV3
from agentmesh.research_orchestration.v3.review import (
    REVIEW_DIMENSIONS,
    DeterministicReviewCheckV3,
    ReportReviewV3,
    ReviewDimensionV3,
)

_CHECK_ORDER = (
    "schema_valid",
    "lineage_binding_valid",
    "requirement_coverage",
    "question_coverage",
    "evidence_coverage",
    "finding_graph_valid",
    "recommendation_roots_valid",
    "gap_disclosure",
    "sensitive_content_absent",
    "artifact_hash_valid",
    "text_mode_no_visual_references",
)
_CHECK_DIMENSIONS = {
    "schema_valid": "requirement_coverage",
    "lineage_binding_valid": "requirement_coverage",
    "requirement_coverage": "requirement_coverage",
    "question_coverage": "question_coverage",
    "evidence_coverage": "evidence_coverage",
    "finding_graph_valid": "reasoning_quality",
    "recommendation_roots_valid": "recommendation_quality",
    "gap_disclosure": "risk_disclosure",
    "sensitive_content_absent": "risk_disclosure",
    "artifact_hash_valid": "evidence_coverage",
    "text_mode_no_visual_references": "visual_quality",
}


class SemanticReviewResultV3(StrictFrozenModel):
    receipt_id: Identifier
    rubric_snapshot_hash: Sha256Hex
    verdict: Literal["pass", "revise", "block"]
    dimensions: tuple[ReviewDimensionV3, ...]

    @model_validator(mode="after")
    def validate_semantic_result(self) -> SemanticReviewResultV3:
        dimension_ids = tuple(item.id for item in self.dimensions)
        require_unique(dimension_ids, "semantic review dimension IDs")
        if set(dimension_ids) != set(REVIEW_DIMENSIONS):
            raise ValueError("semantic review must assess every review dimension exactly once")
        if self.verdict == "pass" and any(
            not dimension.passed or dimension.issues for dimension in self.dimensions
        ):
            raise ValueError("semantic pass requires every dimension to pass without issues")
        if self.verdict == "revise" and all(dimension.passed for dimension in self.dimensions):
            raise ValueError("semantic revision requires at least one failed dimension")
        return self


class SemanticReviewPort(Protocol):
    async def review(
        self,
        *,
        requirement: RequirementVersionV3,
        plan: ExecutionPlanVersionV3,
        problem_graph: ProblemGraphV1,
        deliverable: ResearchDeliverableV3,
        evidence_manifest: EvidenceManifestV3,
        actor_artifacts: tuple[VerifiedArtifactContentV3, ...],
        rubric_content: str,
        rubric_snapshot_hash: Sha256Hex,
    ) -> SemanticReviewResultV3: ...


class ReportReviewService:
    """Run fail-closed deterministic checks before an injected semantic Review."""

    def __init__(
        self,
        semantic_review: SemanticReviewPort,
        *,
        rubric_snapshot_hash: Sha256Hex,
        rubric_content: str,
        artifacts: ArtifactReadPort,
    ) -> None:
        if hashlib.sha256(rubric_content.encode("utf-8")).hexdigest() != rubric_snapshot_hash:
            raise ValueError("Review rubric content does not match its frozen snapshot hash")
        self._semantic_review = semantic_review
        self._rubric_snapshot_hash = rubric_snapshot_hash
        self._rubric_content = rubric_content
        self._artifacts = artifacts

    @classmethod
    def from_catalog(
        cls,
        semantic_review: SemanticReviewPort,
        catalog: CompetitiveTextCatalog,
        *,
        artifacts: ArtifactReadPort,
    ) -> ReportReviewService:
        deliverable = next(
            (item for item in catalog.deliverables if item.id == "competitive_analysis_report"),
            None,
        )
        if deliverable is None:
            raise ValueError("Competitive Text catalog lacks its Deliverable definition")
        document = next(
            (item for item in catalog.documents if item.id == deliverable.review_rubric),
            None,
        )
        if document is None:
            raise ValueError("Competitive Text catalog lacks its frozen Review rubric")
        raw_rubric = load_catalog_document(catalog, document.id)
        if not isinstance(raw_rubric, Mapping):
            raise ValueError("frozen Review rubric is not an object")
        raw_dimensions = raw_rubric.get("dimensions")
        if not isinstance(raw_dimensions, list) or tuple(
            item.get("id") for item in raw_dimensions if isinstance(item, Mapping)
        ) != REVIEW_DIMENSIONS:
            raise ValueError("frozen Review rubric dimensions do not match the Review contract")
        rubric_content = read_catalog_document(catalog, document.id).decode("utf-8", errors="strict")
        return cls(
            semantic_review,
            rubric_snapshot_hash=document.sha256,
            rubric_content=rubric_content,
            artifacts=artifacts,
        )

    async def review(
        self,
        *,
        requirement: RequirementVersionV3,
        plan: ExecutionPlanVersionV3,
        problem_graph: ProblemGraphV1,
        deliverable: ResearchDeliverableV3,
        deliverable_artifact: SealedArtifactRefV3,
        actor_results: tuple[ActorExecutionResultV3, ...],
        evidence_manifest: EvidenceManifestV3,
        evidence_manifest_artifact: EvidenceManifestArtifactRefV3,
        evidence_artifacts: tuple[VerifiedArtifactContentV3, ...],
        revision_round: int,
    ) -> ReportReviewV3:
        if revision_round not in (0, 1):
            raise ValueError("Competitive Text Review permits only revision rounds zero and one")
        try:
            actor_artifacts = read_verified_actor_artifacts(self._artifacts, actor_results)
            actor_artifact_error: str | None = None
        except ValueError as exc:
            actor_artifacts = ()
            actor_artifact_error = str(exc)
        checks = self._deterministic_checks(
            requirement=requirement,
            plan=plan,
            problem_graph=problem_graph,
            deliverable=deliverable,
            deliverable_artifact=deliverable_artifact,
            actor_results=actor_results,
            evidence_manifest=evidence_manifest,
            evidence_manifest_artifact=evidence_manifest_artifact,
            evidence_artifacts=evidence_artifacts,
            actor_artifact_error=actor_artifact_error,
        )
        if any(not check.passed for check in checks):
            return ReportReviewV3(
                schema_version="report-review-v3",
                run_id=requirement.run_id,
                requirement_version_id=requirement.id,
                plan_version_id=plan.id,
                attempt_id=deliverable.attempt_id,
                deliverable_artifact=deliverable_artifact,
                rubric_snapshot_hash=self._rubric_snapshot_hash,
                deterministic_checks=checks,
                semantic_model_call_receipt_id=None,
                verdict="block",
                dimensions=_dimensions_from_checks(checks),
                revision_round=revision_round,
            )

        semantic = await self._semantic_review.review(
            requirement=requirement,
            plan=plan,
            problem_graph=problem_graph,
            deliverable=deliverable,
            evidence_manifest=evidence_manifest,
            actor_artifacts=actor_artifacts,
            rubric_content=self._rubric_content,
            rubric_snapshot_hash=self._rubric_snapshot_hash,
        )
        if semantic.rubric_snapshot_hash != self._rubric_snapshot_hash:
            raise ValueError("semantic Review response does not bind the frozen rubric")
        verdict = semantic.verdict
        dimensions = semantic.dimensions
        if revision_round == 1 and verdict == "revise":
            verdict = "block"
        return ReportReviewV3(
            schema_version="report-review-v3",
            run_id=requirement.run_id,
            requirement_version_id=requirement.id,
            plan_version_id=plan.id,
            attempt_id=deliverable.attempt_id,
            deliverable_artifact=deliverable_artifact,
            rubric_snapshot_hash=self._rubric_snapshot_hash,
            deterministic_checks=checks,
            semantic_model_call_receipt_id=semantic.receipt_id,
            verdict=verdict,
            dimensions=dimensions,
            revision_round=revision_round,
        )

    @staticmethod
    def _deterministic_checks(
        *,
        requirement: RequirementVersionV3,
        plan: ExecutionPlanVersionV3,
        problem_graph: ProblemGraphV1,
        deliverable: ResearchDeliverableV3,
        deliverable_artifact: SealedArtifactRefV3,
        actor_results: tuple[ActorExecutionResultV3, ...],
        evidence_manifest: EvidenceManifestV3,
        evidence_manifest_artifact: EvidenceManifestArtifactRefV3,
        evidence_artifacts: tuple[VerifiedArtifactContentV3, ...],
        actor_artifact_error: str | None,
    ) -> tuple[DeterministicReviewCheckV3, ...]:
        issues: dict[str, list[str]] = {code: [] for code in _CHECK_ORDER}

        try:
            validate_review_inputs(
                requirement=requirement,
                plan=plan,
                problem_graph=problem_graph,
                deliverable=deliverable,
                deliverable_artifact=deliverable_artifact,
                actor_results=actor_results,
                evidence_manifest=evidence_manifest,
                evidence_manifest_artifact=evidence_manifest_artifact,
                evidence_artifacts=evidence_artifacts,
            )
        except ValueError as exc:
            issues["schema_valid"].append(f"review input boundary rejected: {exc}")

        if (
            deliverable.run_id,
            deliverable.requirement_version_id,
            deliverable.plan_version_id,
            deliverable.attempt_id,
            evidence_manifest.run_id,
            evidence_manifest.plan_version_id,
            evidence_manifest.attempt_id,
        ) != (
            requirement.run_id,
            requirement.id,
            plan.id,
            evidence_manifest.attempt_id,
            requirement.run_id,
            plan.id,
            deliverable.attempt_id,
        ):
            issues["lineage_binding_valid"].append(
                "Requirement, Plan, Deliverable, and Evidence lineage do not agree"
            )
        if deliverable.evidence_manifest_artifact != evidence_manifest_artifact:
            issues["lineage_binding_valid"].append(
                "Deliverable does not bind the reviewed Evidence Manifest"
            )
        expected_provenance = {
            (result.actor_type, result.actor_id, result.result_artifact)
            for result in actor_results
        }
        actual_provenance = {
            (item.actor_type, item.actor_id, item.result_artifact)
            for item in deliverable.capability_provenance
        }
        if actual_provenance != expected_provenance:
            issues["lineage_binding_valid"].append(
                "Deliverable capability provenance does not match Actor results"
            )

        required_criteria = {item.id for item in requirement.payload.success_criteria}
        covered_criteria = {
            item.success_criterion_id for item in deliverable.coverage.success_criterion_coverage
        }
        if covered_criteria != required_criteria:
            issues["requirement_coverage"].append(
                "Deliverable does not exactly cover Requirement success criteria"
            )

        required_questions = {
            item.id for item in problem_graph.questions if item.priority == "required"
        }
        planned_questions = {
            question_id for step in plan.payload.steps for question_id in step.question_ids
        }
        covered_questions = {
            item.question_id for item in deliverable.coverage.question_coverage
        }
        if planned_questions != required_questions or covered_questions != planned_questions:
            issues["question_coverage"].append(
                "ProblemGraph, Plan, and Deliverable question coverage do not agree"
            )

        known_evidence = {item.id for item in evidence_manifest.evidence}
        referenced_evidence = _deliverable_evidence_ids(deliverable)
        if not referenced_evidence.issubset(known_evidence):
            issues["evidence_coverage"].append(
                "Deliverable references Evidence outside the reviewed Manifest"
            )
        for policy in plan.payload.evidence_requirements:
            count = sum(
                item.evidence_class in policy.accepted_classes
                for item in evidence_manifest.evidence
            )
            if policy.required and count < policy.minimum_count:
                issues["evidence_coverage"].append(
                    f"Evidence policy {policy.id} minimum is not satisfied"
                )
        try:
            verify_evidence_manifest_artifacts(evidence_manifest, evidence_artifacts)
        except ValueError as exc:
            issues["evidence_coverage"].append(f"Evidence Artifact verification failed: {exc}")

        try:
            type(deliverable.finding_graph).model_validate(
                deliverable.finding_graph.model_dump(mode="python", round_trip=True)
            )
        except ValueError as exc:
            issues["finding_graph_valid"].append(f"FindingGraph validation failed: {exc}")

        finding_ids = {item.id for item in deliverable.finding_graph.findings}
        if any(
            not set(recommendation.finding_ids).issubset(finding_ids)
            for recommendation in deliverable.recommendations
        ):
            issues["recommendation_roots_valid"].append(
                "Recommendation roots are absent from the FindingGraph"
            )

        undisclosed_gaps = [
            gap
            for gap in plan.payload.capability_gaps
            if not any(
                gap.capability_id in risk or gap.code in risk
                for risk in deliverable.risks_and_open_issues
            )
        ]
        if undisclosed_gaps:
            issues["gap_disclosure"].append("Deliverable does not disclose every capability gap")

        if any(
            item.evidence_class != "public_source" or item.sensitivity != "public"
            for item in evidence_manifest.evidence
        ):
            issues["sensitive_content_absent"].append(
                "Competitive Text contains non-public Evidence"
            )

        if actor_artifact_error is not None:
            issues["artifact_hash_valid"].append(
                f"Actor Artifact verification failed: {actor_artifact_error}"
            )
        if (
            canonical_json_v3_sha256(deliverable) != deliverable_artifact.content_hash
            or canonical_json_v3_sha256(evidence_manifest)
            != evidence_manifest_artifact.content_hash
        ):
            issues["artifact_hash_valid"].append(
                "Deliverable or Evidence Manifest Artifact hash does not match"
            )

        if (
            deliverable.payload.visual_evidence
            or deliverable.payload.screenshot_comparisons
            or evidence_manifest.presentation_mode != "text"
        ):
            issues["text_mode_no_visual_references"].append(
                "Competitive Text contains a visual reference"
            )

        return tuple(
            DeterministicReviewCheckV3(
                code=code,
                dimension_id=_CHECK_DIMENSIONS[code],
                passed=not issues[code],
                issues=tuple(issues[code]),
            )
            for code in _CHECK_ORDER
        )


def _deliverable_evidence_ids(deliverable: ResearchDeliverableV3) -> set[str]:
    identifiers: set[str] = set()
    for finding in deliverable.finding_graph.findings:
        if finding.kind == "fact":
            identifiers.update(finding.evidence_ids)
    for sample in deliverable.payload.competitor_samples:
        identifiers.update(sample.evidence_ids)
    for row in deliverable.payload.dimension_matrix:
        for value in row.values:
            identifiers.update(value.evidence_ids)
    for difference in deliverable.payload.differences:
        identifiers.update(difference.evidence_ids)
    return identifiers


def _dimensions_from_checks(
    checks: tuple[DeterministicReviewCheckV3, ...],
) -> tuple[ReviewDimensionV3, ...]:
    dimensions: list[ReviewDimensionV3] = []
    for dimension_id in REVIEW_DIMENSIONS:
        dimension_issues = tuple(
            issue
            for check in checks
            if check.dimension_id == dimension_id
            for issue in check.issues
        )
        dimensions.append(
            ReviewDimensionV3(
                id=dimension_id,
                passed=not dimension_issues,
                issues=dimension_issues,
            )
        )
    return tuple(dimensions)
