from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from agentmesh.research_orchestration.v3.common import (
    Identifier,
    NonBlankString,
    SealedArtifactRefV3,
    Sha256Hex,
    StrictFrozenModel,
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
DeterministicReviewCheckCode = Literal[
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
]
_DIMENSION_CARDINALITY_SCHEMA = {
    "allOf": [
        {
            "contains": {
                "type": "object",
                "properties": {"id": {"const": dimension_id}},
                "required": ["id"],
            },
            "minContains": 1,
            "maxContains": 1,
        }
        for dimension_id in REVIEW_DIMENSIONS
    ],
    "uniqueItems": True,
}
_CHECK_CARDINALITY_SCHEMA = {
    "allOf": [
        {
            "contains": {
                "type": "object",
                "properties": {"code": {"const": code}},
                "required": ["code"],
            },
            "minContains": 1,
            "maxContains": 1,
        }
        for code in sorted(REQUIRED_DETERMINISTIC_CHECKS)
    ],
    "uniqueItems": True,
}


class DeterministicReviewCheckV3(StrictFrozenModel):
    code: DeterministicReviewCheckCode
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
    schema_version: Literal["report-review-v3"]
    run_id: Identifier
    requirement_version_id: Identifier
    plan_version_id: Identifier
    attempt_id: Identifier
    deliverable_artifact: SealedArtifactRefV3
    rubric_snapshot_hash: Sha256Hex
    deterministic_checks: tuple[DeterministicReviewCheckV3, ...] = Field(
        min_length=len(REQUIRED_DETERMINISTIC_CHECKS),
        max_length=len(REQUIRED_DETERMINISTIC_CHECKS),
        json_schema_extra=_CHECK_CARDINALITY_SCHEMA,
    )
    semantic_model_call_receipt_id: Identifier | None
    verdict: Literal["pass", "revise", "block"]
    dimensions: tuple[ReviewDimensionV3, ...] = Field(
        min_length=len(REVIEW_DIMENSIONS),
        max_length=len(REVIEW_DIMENSIONS),
        json_schema_extra=_DIMENSION_CARDINALITY_SCHEMA,
    )
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


class PassedReportReviewV3(ReportReviewV3):
    """A review narrowed to the only verdict accepted by report composition."""

    verdict: Literal["pass"]
