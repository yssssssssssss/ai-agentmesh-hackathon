from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentmesh.models import AgentRunStatus
from agentmesh.research_orchestration.contracts import ResearchGate, ResearchPhase


class ResearchNotFoundError(LookupError):
    """The run is absent or outside the authenticated owner's scope."""


class ResearchConflictError(RuntimeError):
    """The command conflicts with current state, version, or idempotency history."""


class ResearchOwnerScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: str = Field(min_length=1, max_length=120)
    workspace_id: str = Field(min_length=1, max_length=120)
    project_id: str = Field(min_length=1, max_length=120)


class ResearchWorkflowProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    phase: ResearchPhase
    active_gate: ResearchGate
    state_version: int = Field(ge=1)
    active_requirement_version_id: str | None = Field(default=None, max_length=120)
    active_plan_version_id: str | None = Field(default=None, max_length=120)
    active_attempt_id: str | None = Field(default=None, max_length=120)
    updated_at: datetime | None = None


class ResearchClarificationProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    question_id: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=1, max_length=500)


class ResearchRequirementProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_version_id: str = Field(min_length=1, max_length=120)
    version: int = Field(ge=1)
    research_goal: str = Field(min_length=1, max_length=4000)
    competitor_scope: str | None = Field(default=None, max_length=2000)
    blocking: bool = False
    clarification_questions: list[ResearchClarificationProjection] = Field(default_factory=list, max_length=3)


class ResearchPlanStepProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    step_number: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=120)
    actor_type: Literal["tool", "skill"]
    actor_id: str = Field(min_length=1, max_length=120)
    required: bool = True


class ResearchPlanProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_version_id: str = Field(min_length=1, max_length=120)
    version: int = Field(ge=1)
    recommended: bool = False
    plan_hash: str = Field(pattern="^[0-9a-f]{64}$")
    steps: list[ResearchPlanStepProjection] = Field(default_factory=list, max_length=100)


class ResearchStepProgressProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    step_number: int = Field(ge=1)
    status: str = Field(min_length=1, max_length=40)
    attempt_count: int = Field(default=0, ge=0)
    result_artifact_id: str | None = Field(default=None, max_length=120)
    error_code: str | None = Field(default=None, max_length=120)


class ResearchAttemptProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_id: str = Field(min_length=1, max_length=120)
    attempt_number: int = Field(ge=1)
    status: str = Field(min_length=1, max_length=40)
    steps: list[ResearchStepProgressProjection] = Field(default_factory=list, max_length=100)


class ResearchGapProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=1000)
    question_ids: list[str] = Field(default_factory=list, max_length=20)


class ResearchArtifactProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_manifest_id: str | None = Field(default=None, max_length=120)
    claim_ledger_id: str | None = Field(default=None, max_length=120)
    deliverable_id: str | None = Field(default=None, max_length=120)
    review_id: str | None = Field(default=None, max_length=120)
    report_id: str | None = Field(default=None, max_length=120)


class ResearchSourceLinkProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=2000)
    retrieved_at: datetime

    @field_validator("url")
    @classmethod
    def require_public_http_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("research source URL must be public HTTP(S)")
        return value


class ResearchEvidenceProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(min_length=1, max_length=120)
    quote: str = Field(min_length=1, max_length=8192)
    sources: list[ResearchSourceLinkProjection] = Field(default_factory=list, max_length=20)
    conflict_status: Literal["unknown", "none", "possible", "conflicting"]
    risk_flags: list[str] = Field(default_factory=list, max_length=10)


class ResearchClaimProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str = Field(min_length=1, max_length=120)
    claim_type: Literal["fact", "inference", "recommendation"]
    statement: str = Field(min_length=1, max_length=8000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=40)
    parent_claim_ids: list[str] = Field(default_factory=list, max_length=40)
    confidence: Literal["low", "medium", "high"]
    conflict_status: Literal["unknown", "none", "possible", "conflicting"]


class ResearchDeliverableProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str = Field(min_length=1, max_length=12000)
    summary_claim_ids: list[str] = Field(default_factory=list, max_length=20)
    comparison: list[ResearchClaimProjection] = Field(default_factory=list, max_length=200)
    recommendations: list[ResearchClaimProjection] = Field(default_factory=list, max_length=100)
    limitations: list[str] = Field(default_factory=list, max_length=200)


class ResearchReviewCheckProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1, max_length=120)
    passed: bool


class ResearchReviewProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["pass", "block"]
    checks: list[ResearchReviewCheckProjection] = Field(default_factory=list, max_length=40)


class ResearchReportProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1, max_length=500)
    markdown: str = Field(min_length=1)


class ResearchResultProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence: list[ResearchEvidenceProjection] = Field(default_factory=list, max_length=20)
    claims: list[ResearchClaimProjection] = Field(default_factory=list, max_length=300)
    deliverable: ResearchDeliverableProjection | None = None
    review: ResearchReviewProjection | None = None
    report: ResearchReportProjection | None = None


class ResearchProvenanceProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_model: str | None = Field(default=None, max_length=120)
    actual_model: str | None = Field(default=None, max_length=120)
    tool_implementation_id: str | None = Field(default=None, max_length=240)
    tool_execution_mode: Literal["real", "fake"] | None = None


class ResearchRecoveryProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    invocation_id: str = Field(min_length=1, max_length=120)
    state: Literal["unknown"] = "unknown"
    send_count: int = Field(ge=1)
    error_code: str | None = Field(default=None, max_length=120)


class ResearchToolApprovalProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    inbox_item_id: str = Field(min_length=1, max_length=120)
    call_id: str = Field(min_length=1, max_length=240)
    tool_name: str = Field(min_length=1, max_length=120)


class ResearchRunProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1, max_length=120)
    orchestration_version: Literal["research-v2"] = "research-v2"
    status: AgentRunStatus
    error_code: str | None = Field(default=None, max_length=120)
    workflow: ResearchWorkflowProjection
    requirement: ResearchRequirementProjection | None = None
    plans: list[ResearchPlanProjection] = Field(default_factory=list, max_length=2)
    attempt: ResearchAttemptProjection | None = None
    gaps: list[ResearchGapProjection] = Field(default_factory=list, max_length=100)
    artifacts: ResearchArtifactProjection = Field(default_factory=ResearchArtifactProjection)
    result: ResearchResultProjection = Field(default_factory=ResearchResultProjection)
    provenance: ResearchProvenanceProjection = Field(default_factory=ResearchProvenanceProjection)
    tool_approval: ResearchToolApprovalProjection | None = None
    recovery: ResearchRecoveryProjection | None = None
    integrity_errors: list[str] = Field(default_factory=list, max_length=20)
