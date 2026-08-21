from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from agentmesh.research_orchestration.v3.common import (
    Identifier,
    NonBlankString,
    Sha256Hex,
    StrictFrozenModel,
    SealedArtifactRefV3,
    require_unique,
)

ReviewDimensionId = Literal[
    "requirement_coverage",
    "question_coverage",
    "evidence_coverage",
    "reasoning_quality",
    "recommendation_quality",
    "visual_quality",
    "risk_disclosure",
]
REVIEW_DIMENSIONS = (
    "requirement_coverage",
    "question_coverage",
    "evidence_coverage",
    "reasoning_quality",
    "recommendation_quality",
    "visual_quality",
    "risk_disclosure",
)
REQUIRED_DETERMINISTIC_CHECKS = frozenset(
    {
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
    }
)


class DeterministicReviewCheckV3(StrictFrozenModel):
    code: Identifier
    dimension_id: ReviewDimensionId
    passed: bool
    issues: tuple[Annotated[NonBlankString, Field(max_length=1000)], ...]

    @model_validator(mode="after")
    def validate_issues(self) -> DeterministicReviewCheckV3:
        if self.passed and self.issues:
            raise ValueError("passing deterministic checks cannot contain issues")
        return self


class ReviewDimensionV3(StrictFrozenModel):
    id: ReviewDimensionId
    passed: bool
    issues: tuple[Annotated[NonBlankString, Field(max_length=1000)], ...]

    @model_validator(mode="after")
    def validate_issues(self) -> ReviewDimensionV3:
        if self.passed and self.issues:
            raise ValueError("passing review dimensions cannot contain issues")
        return self


class ReportReviewV3(StrictFrozenModel):
    model_config = ConfigDict(json_schema_extra={"$id": "report-review-v3"})

    schema_version: Literal["report-review-v3"] = "report-review-v3"
    run_id: Identifier
    plan_version_id: Identifier
    attempt_id: Identifier
    deliverable_artifact: SealedArtifactRefV3
    rubric_snapshot_hash: Sha256Hex
    deterministic_checks: tuple[DeterministicReviewCheckV3, ...]
    semantic_model_call_receipt_id: Identifier | None
    verdict: Literal["pass", "revise", "block"]
    dimensions: tuple[ReviewDimensionV3, ...]
    revision_round: Literal[0, 1]

    @model_validator(mode="after")
    def validate_review(self) -> ReportReviewV3:
        if self.deliverable_artifact.kind != "research_deliverable" or (
            self.deliverable_artifact.schema_version != "research-deliverable-v3"
        ):
            raise ValueError("review must bind a research-deliverable-v3 Artifact")
        codes = tuple(item.code for item in self.deterministic_checks)
        require_unique(codes, "deterministic review check codes")
        if set(codes) != REQUIRED_DETERMINISTIC_CHECKS:
            raise ValueError("review must contain exactly the required deterministic checks")
        dimension_ids = tuple(item.id for item in self.dimensions)
        require_unique(dimension_ids, "review dimension IDs")
        if set(dimension_ids) != set(REVIEW_DIMENSIONS):
            raise ValueError("review must contain every review dimension exactly once")
        deterministic_failed = any(not item.passed for item in self.deterministic_checks)
        if deterministic_failed and self.verdict != "block":
            raise ValueError("a deterministic failure forces a block verdict")
        if not deterministic_failed and self.semantic_model_call_receipt_id is None:
            raise ValueError("semantic review receipt is required after deterministic checks pass")
        if self.verdict == "pass" and any(not item.passed or item.issues for item in self.dimensions):
            raise ValueError("pass requires every review dimension to pass without issues")
        if self.verdict == "revise" and self.revision_round != 0:
            raise ValueError("only revision round zero may request revision")
        if self.revision_round == 1 and self.verdict == "revise":
            raise ValueError("a nonpassing round-one review must block")
        return self
