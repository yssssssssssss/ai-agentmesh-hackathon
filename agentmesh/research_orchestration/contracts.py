from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentmesh.models import new_id, now_utc

Sha256Hex = Annotated[str, Field(pattern="^[0-9a-f]{64}$")]


def _canonical_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _canonical_value(value.model_dump(mode="python"))
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical JSON object keys must be strings")
            canonical_key = unicodedata.normalize("NFC", key)
            if canonical_key in normalized:
                raise ValueError("canonical JSON contains duplicate normalized keys")
            normalized[canonical_key] = _canonical_value(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("canonical datetime must include a timezone")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, float):
        raise TypeError("canonical JSON forbids binary floating point values")
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if value is None or isinstance(value, (bool, int)):
        return value
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    normalized = _canonical_value(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


class ResearchPhase(StrEnum):
    REQUIREMENT = "requirement"
    PLANNING = "planning"
    EXECUTION = "execution"
    RESULT = "result"
    TERMINAL = "terminal"


class ResearchGate(StrEnum):
    NONE = "none"
    CLARIFICATION = "clarification"
    PLAN_CONFIRMATION = "plan_confirmation"
    TOOL_APPROVAL = "tool_approval"
    RECOVERY_DECISION = "recovery_decision"


class AmbiguityCode(StrEnum):
    MISSING_COMPETITOR_SCOPE = "missing_competitor_scope"
    AMBIGUOUS_COMPETITOR_SCOPE = "ambiguous_competitor_scope"
    CONFLICTING_SCOPE = "conflicting_scope"
    REQUIRED_EVIDENCE_UNAVAILABLE = "required_evidence_unavailable"
    CAPABILITY_NOT_AUTHORIZED = "capability_not_authorized"


class ResearchConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=1000)
    source: Literal["user", "policy"]


class SuccessCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern="^sc_[a-z0-9_]+$", max_length=80)
    statement: str = Field(min_length=1, max_length=1000)


class ResearchAssumption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern="^assumption_[a-z0-9_]+$", max_length=80)
    statement: str = Field(min_length=1, max_length=1000)
    accepted_by_user: bool = False


class ResearchAmbiguity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: AmbiguityCode
    blocking: bool
    rationale: str = Field(min_length=1, max_length=1000)


class ClarificationQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern="^clarify_[a-z0-9_]+$", max_length=80)
    ambiguity_code: AmbiguityCode
    prompt: str = Field(min_length=1, max_length=500)


class ResearchTaskV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["research-task-v2"] = "research-task-v2"
    task_archetype: Literal["evidence_synthesis"] = "evidence_synthesis"
    task_type: Literal["competitive_research"] = "competitive_research"
    business_domain: str = Field(min_length=1, max_length=240)
    research_goal: str = Field(min_length=1, max_length=4000)
    target_audience: list[str] = Field(default_factory=list, max_length=20)
    competitor_scope: str | None = Field(default=None, max_length=2000)
    analysis_dimensions: list[str] = Field(default_factory=list, max_length=20)
    exclusions: list[str] = Field(default_factory=list, max_length=20)
    constraints: list[ResearchConstraint] = Field(default_factory=list, max_length=20)
    success_criteria: list[SuccessCriterion] = Field(min_length=1, max_length=20)
    expected_deliverables: list[str] = Field(min_length=1, max_length=10)
    assumptions: list[ResearchAssumption] = Field(default_factory=list, max_length=20)
    ambiguities: list[ResearchAmbiguity] = Field(default_factory=list, max_length=10)
    clarification_questions: list[ClarificationQuestion] = Field(default_factory=list, max_length=3)
    sensitivity: Literal["public", "internal", "private"] = "public"
    pii_detected: bool = False

    @model_validator(mode="after")
    def validate_ambiguities(self) -> ResearchTaskV2:
        blocking_codes = {item.code for item in self.ambiguities if item.blocking}
        question_codes = {item.ambiguity_code for item in self.clarification_questions}
        if blocking_codes != question_codes:
            raise ValueError("each blocking ambiguity must have exactly one clarification question code")
        if self.competitor_scope is None and AmbiguityCode.MISSING_COMPETITOR_SCOPE not in blocking_codes:
            raise ValueError("missing competitor scope must be an explicit blocking ambiguity")
        return self


class EvidenceRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_class: Literal["provider_summary", "page_observation", "document", "internal"]
    minimum_sources: int = Field(default=1, ge=1, le=4)
    independent_sources: bool = False


class ProblemQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern="^q_[a-z0-9_]+$", max_length=80)
    statement: str = Field(min_length=1, max_length=1000)
    rationale: str = Field(min_length=1, max_length=1000)
    required: bool = True
    factual: bool = True
    success_criterion_ids: list[str] = Field(min_length=1, max_length=20)
    depends_on: list[str] = Field(default_factory=list, max_length=10)
    evidence_requirement: EvidenceRequirement | None = None
    acceptance_criteria: list[str] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_evidence(self) -> ProblemQuestion:
        if self.required and self.factual and self.evidence_requirement is None:
            raise ValueError("required factual questions need an evidence requirement")
        return self


class ProblemContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["problem-contract-v1"] = "problem-contract-v1"
    success_criterion_ids: list[str] = Field(min_length=1, max_length=20)
    questions: list[ProblemQuestion] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_graph_and_coverage(self) -> ProblemContract:
        question_ids = [question.id for question in self.questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("problem question IDs must be unique")
        criterion_ids = set(self.success_criterion_ids)
        if len(criterion_ids) != len(self.success_criterion_ids):
            raise ValueError("success criterion IDs must be unique")
        referenced_criteria = {
            criterion_id
            for question in self.questions
            for criterion_id in question.success_criterion_ids
        }
        required_coverage = {
            criterion_id
            for question in self.questions
            if question.required
            for criterion_id in question.success_criterion_ids
        }
        if not referenced_criteria.issubset(criterion_ids) or required_coverage != criterion_ids:
            raise ValueError("required questions must cover every success criterion")
        known = set(question_ids)
        dependencies = {question.id: set(question.depends_on) for question in self.questions}
        if any(not items.issubset(known) or question_id in items for question_id, items in dependencies.items()):
            raise ValueError("problem question dependency is invalid")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(question_id: str) -> None:
            if question_id in visiting:
                raise ValueError("problem question dependencies contain a cycle")
            if question_id in visited:
                return
            visiting.add(question_id)
            for dependency_id in dependencies[question_id]:
                visit(dependency_id)
            visiting.remove(question_id)
            visited.add(question_id)

        for question_id in question_ids:
            visit(question_id)
        return self


class AttemptStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    RECOVERY_REQUIRED = "recovery_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class InvocationState(StrEnum):
    PREPARED = "prepared"
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"


class ExecutionLease(BaseModel):
    """The single fencing identity accepted by execution and Artifact writes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    owner: str = Field(min_length=1, max_length=120)
    token: str = Field(min_length=1, max_length=240)
    fencing_epoch: int = Field(ge=1)


class ResearchWorkflow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=120)
    phase: ResearchPhase = ResearchPhase.REQUIREMENT
    active_gate: ResearchGate = ResearchGate.NONE
    active_requirement_version_id: str | None = Field(default=None, max_length=120)
    active_plan_version_id: str | None = Field(default=None, max_length=120)
    active_attempt_id: str | None = Field(default=None, max_length=120)
    state_version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)

    @model_validator(mode="after")
    def validate_terminal_gate(self) -> ResearchWorkflow:
        if self.phase == ResearchPhase.TERMINAL and self.active_gate != ResearchGate.NONE:
            raise ValueError("terminal workflows cannot have an active gate")
        if self.active_gate == ResearchGate.CLARIFICATION and self.phase != ResearchPhase.REQUIREMENT:
            raise ValueError("clarification is only valid during requirement planning")
        if self.active_gate == ResearchGate.PLAN_CONFIRMATION and (
            self.phase != ResearchPhase.PLANNING
            or self.active_requirement_version_id is None
            or self.active_plan_version_id is None
        ):
            raise ValueError("plan confirmation requires an active requirement and plan")
        if self.active_gate in {ResearchGate.TOOL_APPROVAL, ResearchGate.RECOVERY_DECISION} and (
            self.phase != ResearchPhase.EXECUTION or self.active_attempt_id is None
        ):
            raise ValueError("execution gates require an active attempt")
        return self


class RequirementVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(default_factory=lambda: new_id("requirement"), min_length=1, max_length=120)
    run_id: str = Field(min_length=1, max_length=120)
    version: int = Field(ge=1)
    schema_version: str = Field(min_length=1, max_length=120)
    task_type: Literal["competitive_research"]
    payload: dict[str, Any]
    content_hash: Sha256Hex
    created_at: datetime = Field(default_factory=now_utc)


class ExecutionPlanVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(default_factory=lambda: new_id("research_plan"), min_length=1, max_length=120)
    run_id: str = Field(min_length=1, max_length=120)
    requirement_version_id: str = Field(min_length=1, max_length=120)
    version: int = Field(ge=1)
    schema_version: str = Field(min_length=1, max_length=120)
    plan_hash: Sha256Hex
    payload: dict[str, Any]
    created_at: datetime = Field(default_factory=now_utc)


class ResearchCommandReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=1, max_length=120)
    command_type: Literal["clarify", "confirm_plan", "revise", "execute", "recover", "purge"]
    request_hash: Sha256Hex
    response_status: int = Field(ge=100, le=599)
    response_payload: dict[str, Any]
    created_at: datetime = Field(default_factory=now_utc)


class ExecutionAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("attempt"), min_length=1, max_length=120)
    run_id: str = Field(min_length=1, max_length=120)
    plan_version_id: str = Field(min_length=1, max_length=120)
    attempt_number: int = Field(ge=1)
    status: AttemptStatus = AttemptStatus.PENDING
    retry_of_attempt_id: str | None = Field(default=None, max_length=120)
    lease_owner: str | None = Field(default=None, max_length=120)
    lease_token: str | None = Field(default=None, max_length=240)
    fencing_epoch: int = Field(default=0, ge=0)
    lease_expires_at: datetime | None = None
    deadline_at: datetime
    completed_at: datetime | None = None
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)

    @model_validator(mode="after")
    def validate_lease(self) -> ExecutionAttempt:
        lease_parts = (self.lease_owner, self.lease_token, self.lease_expires_at)
        if any(part is not None for part in lease_parts) and not all(part is not None for part in lease_parts):
            raise ValueError("lease owner, token, and expiry must be set together")
        has_lease = all(part is not None for part in lease_parts)
        if self.status == AttemptStatus.RUNNING and (not has_lease or self.fencing_epoch < 1):
            raise ValueError("running attempts require an active lease and fencing epoch")
        if self.status != AttemptStatus.RUNNING and has_lease:
            raise ValueError("only running attempts may hold a lease")
        if self.status == AttemptStatus.PENDING and self.fencing_epoch != 0:
            raise ValueError("pending attempts cannot have a fencing epoch")
        if self.status in {AttemptStatus.COMPLETED, AttemptStatus.FAILED, AttemptStatus.CANCELLED} and self.completed_at is None:
            raise ValueError("terminal attempts require completed_at")
        if self.deadline_at <= self.created_at:
            raise ValueError("attempt deadline must be after creation")
        return self


class ResearchStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: str = Field(min_length=1, max_length=120)
    step_number: int = Field(ge=1)
    status: StepStatus = StepStatus.PENDING
    claim_epoch: int = Field(default=0, ge=0)
    result_artifact_id: str | None = Field(default=None, max_length=120)
    error_code: str | None = Field(default=None, max_length=120)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime = Field(default_factory=now_utc)

    @model_validator(mode="after")
    def validate_status_fields(self) -> ResearchStep:
        if self.status in {StepStatus.PENDING, StepStatus.READY} and any(
            value is not None for value in (self.started_at, self.completed_at, self.result_artifact_id, self.error_code)
        ):
            raise ValueError("unstarted steps cannot contain result fields")
        if self.status == StepStatus.RUNNING and self.started_at is None:
            raise ValueError("running steps require started_at")
        if self.status == StepStatus.RUNNING and any(
            value is not None for value in (self.completed_at, self.result_artifact_id, self.error_code)
        ):
            raise ValueError("running steps cannot contain terminal fields")
        if self.status == StepStatus.COMPLETED and (
            self.result_artifact_id is None or self.completed_at is None
        ):
            raise ValueError("completed steps require result_artifact_id and completed_at")
        if self.status == StepStatus.COMPLETED and self.error_code is not None:
            raise ValueError("completed steps cannot contain an error")
        if self.status in {StepStatus.FAILED, StepStatus.SKIPPED, StepStatus.CANCELLED} and self.completed_at is None:
            raise ValueError("terminal steps require completed_at")
        if self.status == StepStatus.FAILED and self.error_code is None:
            raise ValueError("failed steps require an error_code")
        if self.status in {StepStatus.FAILED, StepStatus.SKIPPED, StepStatus.CANCELLED} and self.result_artifact_id is not None:
            raise ValueError("unsuccessful steps cannot contain a result artifact")
        return self


class ToolReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1, max_length=120)
    implementation_id: str = Field(min_length=1, max_length=240)
    mode: Literal["real", "fake"]
    send_sequence: int = Field(ge=1)
    request_id: str | None = Field(default=None, max_length=240)
    status_code: int | None = Field(default=None, ge=100, le=599)
    latency_ms: int = Field(ge=0)
    result_count: int = Field(ge=0)
    error_code: str | None = Field(default=None, max_length=120)


class ToolInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("invocation"), min_length=1, max_length=120)
    run_id: str = Field(min_length=1, max_length=120)
    plan_version_id: str = Field(min_length=1, max_length=120)
    step_number: int = Field(ge=1)
    operation_key: Sha256Hex
    resolved_input_hash: Sha256Hex
    request_artifact_id: str = Field(min_length=1, max_length=120)
    active_attempt_id: str = Field(min_length=1, max_length=120)
    state: InvocationState = InvocationState.PREPARED
    send_count: int = Field(default=0, ge=0)
    active_send_sequence: int = Field(default=0, ge=0)
    sent_fencing_epoch: int | None = Field(default=None, ge=1)
    provider_operation_id: str | None = Field(default=None, max_length=240)
    receipt: ToolReceipt | None = None
    artifact_id: str | None = Field(default=None, max_length=120)
    error_code: str | None = Field(default=None, max_length=120)
    last_sent_at: datetime | None = None
    acknowledged_at: datetime | None = None
    unknown_at: datetime | None = None
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)

    @model_validator(mode="after")
    def validate_state_fields(self) -> ToolInvocation:
        if self.active_send_sequence != self.send_count:
            raise ValueError("active send sequence must match send_count")
        if self.state in {InvocationState.PREPARED, InvocationState.CANCELLED} and any(
            value is not None
            for value in (
                self.sent_fencing_epoch,
                self.receipt,
                self.artifact_id,
                self.last_sent_at,
                self.acknowledged_at,
                self.unknown_at,
            )
        ):
            raise ValueError("unsent invocations cannot contain send or result fields")
        if self.state == InvocationState.PREPARED and (
            self.provider_operation_id is not None or self.error_code is not None
        ):
            raise ValueError("prepared invocations cannot contain current-send metadata")
        if self.state in {InvocationState.SENT, InvocationState.UNKNOWN, InvocationState.ACKNOWLEDGED} and (
            self.send_count < 1 or self.sent_fencing_epoch is None or self.last_sent_at is None
        ):
            raise ValueError("sent invocations require send ownership and timestamp")
        if self.state == InvocationState.SENT and any(
            value is not None for value in (self.receipt, self.artifact_id, self.acknowledged_at, self.unknown_at)
        ):
            raise ValueError("sent invocations cannot contain a result")
        if self.state == InvocationState.UNKNOWN and (
            self.unknown_at is None or self.receipt is not None or self.artifact_id is not None
        ):
            raise ValueError("unknown invocations require unknown_at and no accepted result")
        if self.state == InvocationState.ACKNOWLEDGED and (
            self.receipt is None or self.artifact_id is None or self.acknowledged_at is None
        ):
            raise ValueError("acknowledged invocations require a receipt and artifact")
        if self.receipt is not None and self.receipt.send_sequence != self.active_send_sequence:
            raise ValueError("receipt must belong to the active send")
        if self.state == InvocationState.ACKNOWLEDGED and self.error_code is not None:
            raise ValueError("acknowledged invocations cannot contain an error")
        return self


class ModelCallReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(default_factory=lambda: new_id("model_call"), min_length=1, max_length=120)
    run_id: str = Field(min_length=1, max_length=120)
    owner_kind: Literal["requirement_version", "plan_version", "attempt"]
    owner_id: str = Field(min_length=1, max_length=120)
    stage: str = Field(min_length=1, max_length=80)
    call_key: Sha256Hex
    requested_provider: str | None = Field(default=None, max_length=120)
    requested_model: str | None = Field(default=None, max_length=120)
    actual_provider: str = Field(min_length=1, max_length=120)
    actual_model: str = Field(min_length=1, max_length=120)
    usage: dict[str, int] = Field(default_factory=dict)
    provider_receipt_id: str | None = Field(default=None, max_length=240)
    created_at: datetime = Field(default_factory=now_utc)
