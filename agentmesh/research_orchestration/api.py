from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentmesh.models import AgentRunStatus
from agentmesh.research_orchestration.contracts import ResearchGate, ResearchPhase

ResearchCommandType = Literal["clarify", "confirm_plan", "revise", "execute", "recover", "purge"]


class ResearchNotFoundError(LookupError):
    """The run is absent or outside the authenticated owner's scope."""


class ResearchConflictError(RuntimeError):
    """The command conflicts with current state, version, or idempotency history."""


class ResearchOwnerScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: str = Field(min_length=1, max_length=120)
    workspace_id: str = Field(min_length=1, max_length=120)
    project_id: str = Field(min_length=1, max_length=120)


class ResearchClarificationAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    question_id: str = Field(pattern="^clarify_[a-z0-9_]+$", max_length=80)
    answer: str = Field(min_length=1, max_length=2000)

    @field_validator("answer")
    @classmethod
    def require_non_blank_answer(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("clarification answers must not be blank")
        return value


class ResearchClarifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_state_version: int = Field(ge=1)
    answers: list[ResearchClarificationAnswer] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def require_unique_questions(self) -> ResearchClarifyRequest:
        question_ids = [item.question_id for item in self.answers]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("clarification question IDs must be unique")
        return self


class ResearchConfirmPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_state_version: int = Field(ge=1)


class ResearchAssumptionRevision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    assumption_id: str = Field(pattern="^assumption_[a-z0-9_]+$", max_length=80)
    statement: str | None = Field(default=None, min_length=1, max_length=1000)
    accepted_by_user: bool | None = None

    @model_validator(mode="after")
    def require_a_change(self) -> ResearchAssumptionRevision:
        if self.statement is None and self.accepted_by_user is None:
            raise ValueError("assumption revision must change statement or acceptance")
        if self.statement is not None and not self.statement.strip():
            raise ValueError("assumption statement must not be blank")
        return self


class ResearchRevisePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_state_version: int = Field(ge=1)
    research_goal: str | None = Field(default=None, min_length=1, max_length=4000)
    competitor_scope: str | None = Field(default=None, min_length=1, max_length=2000)
    assumptions: list[ResearchAssumptionRevision] = Field(default_factory=list, max_length=20)
    preferred_plan_version_id: str | None = Field(default=None, min_length=1, max_length=120)
    remove_optional_step_numbers: list[int] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_declarative_changes(self) -> ResearchRevisePlanRequest:
        if self.research_goal is not None and not self.research_goal.strip():
            raise ValueError("research goal must not be blank")
        if self.competitor_scope is not None and not self.competitor_scope.strip():
            raise ValueError("competitor scope must not be blank")
        if any(step_number < 1 for step_number in self.remove_optional_step_numbers):
            raise ValueError("optional step numbers must be positive")
        if len(self.remove_optional_step_numbers) != len(set(self.remove_optional_step_numbers)):
            raise ValueError("optional step numbers must be unique")
        if not any(
            (
                self.research_goal is not None,
                self.competitor_scope is not None,
                bool(self.assumptions),
                self.preferred_plan_version_id is not None,
                bool(self.remove_optional_step_numbers),
            )
        ):
            raise ValueError("at least one declarative revision is required")
        return self


class ResearchExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_state_version: int = Field(ge=1)


class ResearchRecoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_state_version: int = Field(ge=1)
    invocation_id: str = Field(min_length=1, max_length=120)
    action: Literal["retry", "abort"]


class ResearchPurgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_state_version: int = Field(ge=1)


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


class ResearchCommandResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1, max_length=120)
    command_type: ResearchCommandType
    state_version: int | None = Field(default=None, ge=1)
    accepted: Literal[True] = True
    replayed: bool = False
    projection: ResearchRunProjection | None = None
    purged_artifact_count: int | None = Field(default=None, ge=0)
