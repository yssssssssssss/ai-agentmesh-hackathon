"""Frozen research-v2 delivery payloads required by historical reads."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentmesh.research_orchestration.v2_artifact_history import ArtifactRef

CLAIM_LEDGER_SCHEMA = "claim-ledger-v1"
DELIVERABLE_SCHEMA = "deliverable-document-v1"
REVIEW_SCHEMA = "deterministic-review-v1"
REPORT_SCHEMA = "report-document-v1"


class ClaimType(StrEnum):
    FACT = "fact"
    INFERENCE = "inference"
    RECOMMENDATION = "recommendation"


class ClaimConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ClaimRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str = Field(pattern="^claim_[a-zA-Z0-9_-]+$", max_length=120)
    statement: str = Field(min_length=1, max_length=8000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=40)
    parent_claim_ids: list[str] = Field(default_factory=list, max_length=40)
    question_ids: list[str] = Field(min_length=1, max_length=20)
    success_criterion_ids: list[str] = Field(min_length=1, max_length=20)
    confidence: ClaimConfidence
    conflict_status: Literal["unknown", "none", "possible", "conflicting"]
    claim_type: ClaimType
    recommendation: bool
    authoring_actor: Literal["competitive-analysis"] = "competitive-analysis"
    model_call_receipt_id: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_unique_references(self) -> ClaimRecord:
        for values in (
            self.evidence_ids,
            self.parent_claim_ids,
            self.question_ids,
            self.success_criterion_ids,
        ):
            if len(values) != len(set(values)):
                raise ValueError("Claim references must be unique")
        return self

    @model_validator(mode="after")
    def validate_recommendation_flag(self) -> ClaimRecord:
        if self.recommendation != (self.claim_type == ClaimType.RECOMMENDATION):
            raise ValueError("recommendation flag differs from Claim type")
        return self


class ClaimLedger(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default=CLAIM_LEDGER_SCHEMA, pattern="^claim-ledger-v1$")
    source_skill_artifact: ArtifactRef
    model_call_receipt_id: str = Field(min_length=1, max_length=120)
    claims: list[ClaimRecord] = Field(max_length=300)
    gaps: list[str] = Field(default_factory=list, max_length=200)


class CompetitiveComparisonItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str = Field(pattern="^claim_[a-zA-Z0-9_-]+$", max_length=120)
    claim_type: Literal["fact", "inference"]
    statement: str = Field(min_length=1, max_length=8000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=40)
    parent_claim_ids: list[str] = Field(default_factory=list, max_length=40)
    confidence: ClaimConfidence
    conflict_status: Literal["unknown", "none", "possible", "conflicting"]


class CompetitiveRecommendationItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str = Field(pattern="^claim_[a-zA-Z0-9_-]+$", max_length=120)
    statement: str = Field(min_length=1, max_length=8000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=40)
    parent_claim_ids: list[str] = Field(min_length=1, max_length=40)
    confidence: ClaimConfidence
    conflict_status: Literal["unknown", "none", "possible", "conflicting"]


class CompetitiveAnalysisPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str = Field(min_length=1, max_length=12000)
    summary_claim_ids: list[str] = Field(default_factory=list, max_length=20)
    comparison: list[CompetitiveComparisonItem] = Field(default_factory=list, max_length=200)
    recommendations: list[CompetitiveRecommendationItem] = Field(default_factory=list, max_length=100)
    limitations: list[str] = Field(default_factory=list, max_length=200)
    claim_ids: list[str] = Field(default_factory=list, max_length=300)

    @model_validator(mode="after")
    def validate_claim_ids(self) -> CompetitiveAnalysisPayload:
        if (
            len(self.claim_ids) != len(set(self.claim_ids))
            or len(self.summary_claim_ids) != len(set(self.summary_claim_ids))
            or not set(self.summary_claim_ids).issubset(self.claim_ids)
        ):
            raise ValueError("Deliverable Claim IDs must be unique")
        return self


class CoverageEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_id: str = Field(min_length=1, max_length=120)
    claim_ids: list[str] = Field(default_factory=list, max_length=300)


class DeliverableDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default=DELIVERABLE_SCHEMA, pattern="^deliverable-document-v1$")
    task_type: Literal["competitive_research"] = "competitive_research"
    payload: CompetitiveAnalysisPayload
    source_skill_artifact: ArtifactRef
    evidence_manifest_artifact: ArtifactRef
    claim_ledger_artifact: ArtifactRef
    question_coverage: list[CoverageEntry]
    success_criterion_coverage: list[CoverageEntry]


class ReviewCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(pattern="^[a-z0-9_]+$", max_length=120)
    passed: bool


class DeterministicReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default=REVIEW_SCHEMA, pattern="^deterministic-review-v1$")
    rubric_version: str = Field(pattern="^competitive-analysis-review-v1$")
    deliverable_artifact: ArtifactRef
    status: Literal["pass", "block"]
    checks: list[ReviewCheck] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def validate_status(self) -> DeterministicReview:
        codes = [check.code for check in self.checks]
        if len(codes) != len(set(codes)):
            raise ValueError("Review check codes must be unique")
        expected = "pass" if all(check.passed for check in self.checks) else "block"
        if self.status != expected:
            raise ValueError("Review status cannot override deterministic checks")
        return self


class ReportDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default=REPORT_SCHEMA, pattern="^report-document-v1$")
    renderer_version: Literal["competitive-markdown-html-v1"] = "competitive-markdown-html-v1"
    deliverable_artifact: ArtifactRef
    review_artifact: ArtifactRef
    title: str = Field(min_length=1, max_length=500)
    markdown: str = Field(min_length=1)
    html: str = Field(min_length=1)
