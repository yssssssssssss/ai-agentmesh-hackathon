from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.common import (
    ActorType,
    ApprovalRole,
    FrozenJsonObject,
    Identifier,
    NonBlankString,
    ProblemGraphArtifactRefV3,
    Sha256Hex,
    StrictFrozenModel,
    SealedArtifactRefV3,
    require_unique,
)
from agentmesh.research_orchestration.v3.problem_graph import EvidenceRequirementV1
from agentmesh.research_orchestration.v3.requirement import ResearchAssumptionV3


class CapabilityReasonV3(StrictFrozenModel):
    code: Identifier
    message: Annotated[NonBlankString, Field(max_length=1000)]
    related_id: Identifier | None = None


class CapabilityApprovalV3(StrictFrozenModel):
    capability_type: Literal["skill", "tool"]
    capability_id: Identifier
    authority: ApprovalRole


class CapabilityPendingInputV3(StrictFrozenModel):
    kind: Literal["value", "visual"]
    role: Identifier
    label: Annotated[NonBlankString, Field(max_length=240)]
    multiple: bool
    capability_id: Identifier


class OptionalToolDecisionV3(StrictFrozenModel):
    tool_id: Identifier
    status: Literal["available", "unavailable"]
    reason_code: Literal[
        "optional_tool_health_unknown",
        "optional_tool_unhealthy",
        "optional_tool_real_adapter_unavailable",
        "not_enabled_in_slice",
    ] | None = None
    message: Annotated[NonBlankString, Field(max_length=300)] | None = None

    @model_validator(mode="after")
    def validate_status(self) -> OptionalToolDecisionV3:
        if self.status == "available" and (self.reason_code is not None or self.message is not None):
            raise ValueError("available optional Tools cannot have an unavailability reason")
        if self.status == "unavailable" and (self.reason_code is None or self.message is None):
            raise ValueError("unavailable optional Tools require a reason and message")
        return self


class CapabilityDecisionV3(StrictFrozenModel):
    actor_type: Literal["tool", "skill"]
    actor_id: Identifier
    status: Literal["eligible", "rejected"]
    required_approvals: tuple[CapabilityApprovalV3, ...]
    reasons: tuple[CapabilityReasonV3, ...] = Field(min_length=1)
    pending_inputs: tuple[CapabilityPendingInputV3, ...]
    optional_tool_decisions: tuple[OptionalToolDecisionV3, ...] = Field(
        json_schema_extra={"uniqueItems": True}
    )

    @model_validator(mode="after")
    def validate_decision(self) -> CapabilityDecisionV3:
        require_unique(
            tuple(item.tool_id for item in self.optional_tool_decisions),
            "optional Tool decision IDs",
        )
        return self


class CapabilityGapV3(StrictFrozenModel):
    capability_type: Literal["tool", "skill", "llm", "reviewer"]
    capability_id: Identifier
    code: Identifier
    message: Annotated[NonBlankString, Field(max_length=300)]
    required: bool


class CapabilityResolutionV3(StrictFrozenModel):
    decisions: tuple[CapabilityDecisionV3, ...]
    gaps: tuple[CapabilityGapV3, ...]
    control_snapshot_artifact: SealedArtifactRefV3

    @model_validator(mode="after")
    def validate_resolution(self) -> CapabilityResolutionV3:
        require_unique(
            tuple((item.actor_type, item.actor_id) for item in self.decisions),
            "capability decision actor keys",
        )
        return self


class PlanInputBindingV3(StrictFrozenModel):
    source_step_number: Annotated[int, Field(ge=1, le=8)]
    source_pointer: Annotated[str, Field(pattern=r"^/", max_length=500)]
    target_pointer: Annotated[str, Field(pattern=r"^/", max_length=500)]


class ExpectedOutputV3(StrictFrozenModel):
    pointer: Annotated[str, Field(pattern=r"^/", max_length=500)]
    description: Annotated[NonBlankString, Field(max_length=500)]


class PlanStepProposalV3(StrictFrozenModel):
    proposed_step_number: Annotated[int, Field(ge=1)]
    name: Annotated[NonBlankString, Field(max_length=120)]
    actor_type: ActorType
    actor_id: Identifier
    question_ids: tuple[Identifier, ...] = Field(json_schema_extra={"uniqueItems": True})
    depends_on: tuple[Annotated[int, Field(ge=1)], ...] = Field(json_schema_extra={"uniqueItems": True})
    input: FrozenJsonObject
    input_bindings: tuple[PlanInputBindingV3, ...]
    expected_outputs: tuple[ExpectedOutputV3, ...]
    acceptance_criteria: tuple[Annotated[NonBlankString, Field(max_length=1000)], ...]
    requires_approval: bool
    approval_role: ApprovalRole | None = None

    @model_validator(mode="after")
    def validate_proposal(self) -> PlanStepProposalV3:
        require_unique(self.question_ids, "proposed step question IDs")
        require_unique(self.depends_on, "proposed step dependencies")
        require_unique(tuple(item.pointer for item in self.expected_outputs), "proposed step output pointers")
        if self.requires_approval != (self.approval_role is not None):
            raise ValueError("approval role must be present exactly when approval is required")
        return self


class PlanCandidateV3(StrictFrozenModel):
    candidate_id: Literal["depth", "speed"]
    title: Annotated[NonBlankString, Field(max_length=240)]
    rationale: Annotated[NonBlankString, Field(max_length=2000)]
    tradeoffs: Annotated[NonBlankString, Field(max_length=2000)]
    assumptions: tuple[ResearchAssumptionV3, ...]
    proposed_steps: tuple[PlanStepProposalV3, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_candidate(self) -> PlanCandidateV3:
        if self.candidate_id == "speed" and len(self.proposed_steps) > 4:
            raise ValueError("speed candidates may contain at most four steps")
        return self


class PlanCandidateSetV3(StrictFrozenModel):
    schema_version: Literal["plan-candidates-v3"]
    candidates: tuple[PlanCandidateV3, PlanCandidateV3]

    @model_validator(mode="after")
    def validate_candidate_order(self) -> PlanCandidateSetV3:
        if tuple(item.candidate_id for item in self.candidates) != ("depth", "speed"):
            raise ValueError("candidate set must contain depth then speed")
        return self


class PlanStepV3(StrictFrozenModel):
    step_number: Annotated[int, Field(ge=1, le=8)]
    name: Annotated[NonBlankString, Field(max_length=120)]
    actor_type: ActorType
    actor_id: Identifier
    question_ids: tuple[Identifier, ...] = Field(
        min_length=1,
        max_length=20,
        json_schema_extra={"uniqueItems": True},
    )
    depends_on: tuple[Annotated[int, Field(ge=1, le=8)], ...] = Field(
        json_schema_extra={"uniqueItems": True}
    )
    input: FrozenJsonObject
    input_bindings: tuple[PlanInputBindingV3, ...]
    expected_outputs: tuple[ExpectedOutputV3, ...] = Field(min_length=1)
    acceptance_criteria: tuple[Annotated[NonBlankString, Field(max_length=1000)], ...] = Field(min_length=1)
    required: bool
    requires_approval: bool
    approval_role: ApprovalRole | None = None
    timeout_seconds: Annotated[int, Field(ge=1, le=300)]
    max_sends: Annotated[int, Field(ge=1, le=3)]
    invocation_semantics: Literal["tool_read", "skill_once", "llm_once", "reviewer_once"]
    actor_snapshot_hash: Sha256Hex
    input_schema_hash: Sha256Hex
    output_schema_hash: Sha256Hex
    contract_hash: Sha256Hex

    @model_validator(mode="after")
    def validate_step(self) -> PlanStepV3:
        require_unique(self.question_ids, "step question IDs")
        require_unique(self.depends_on, "step dependencies")
        require_unique(tuple(item.pointer for item in self.expected_outputs), "step output pointers")
        if self.requires_approval != (self.approval_role is not None):
            raise ValueError("approval role must be present exactly when approval is required")
        expected_semantics = {
            "tool": "tool_read",
            "skill": "skill_once",
            "llm": "llm_once",
            "reviewer": "reviewer_once",
        }[self.actor_type]
        if self.invocation_semantics != expected_semantics:
            raise ValueError("invocation semantics do not match actor type")
        expected_hash = canonical_json_v3_sha256(self.model_dump(mode="python", exclude={"contract_hash"}))
        if self.contract_hash != expected_hash:
            raise ValueError("step contract_hash does not match the canonical step contract")
        return self


class ExecutionPlanV3(StrictFrozenModel):
    schema_version: Literal["execution-plan-v3"]
    task_type: Literal["competitive_research"]
    requirement_version_id: Identifier
    requirement_content_hash: Sha256Hex
    problem_graph_artifact: ProblemGraphArtifactRefV3
    candidate_id: Literal["depth", "speed"]
    deliverable_type: Literal["competitive_analysis_report"]
    payload_schema_version: Literal["competitive-analysis-text-v1"]
    evidence_requirements: tuple[EvidenceRequirementV1, ...]
    capability_decisions: tuple[CapabilityDecisionV3, ...]
    capability_gaps: tuple[CapabilityGapV3, ...]
    steps: tuple[PlanStepV3, ...] = Field(min_length=1, max_length=8)
    candidate_title: Annotated[NonBlankString, Field(max_length=240)]
    candidate_rationale: Annotated[NonBlankString, Field(max_length=2000)]
    candidate_tradeoffs: Annotated[NonBlankString, Field(max_length=2000)]
    activated_nodes: tuple[Identifier, ...] = Field(json_schema_extra={"uniqueItems": True})
    control_snapshot_artifact: SealedArtifactRefV3
    execution_budget_seconds: Literal[300] = 300
    max_tool_calls: Literal[24] = 24
    max_wave_concurrency: Literal[3] = 3

    @model_validator(mode="after")
    def validate_plan(self) -> ExecutionPlanV3:
        if self.problem_graph_artifact.kind != "problem_graph" or (
            self.problem_graph_artifact.schema_version != "problem-graph-v1"
        ):
            raise ValueError("plan must reference a sealed problem-graph-v1 Artifact")
        if self.control_snapshot_artifact.kind != "research_control_snapshot" or (
            self.control_snapshot_artifact.schema_version != "research-control-snapshot-v3"
        ):
            raise ValueError("plan must reference a sealed research-v3 control snapshot")
        require_unique(tuple(item.id for item in self.evidence_requirements), "plan evidence requirement IDs")
        require_unique(self.activated_nodes, "activated decision node IDs")
        numbers = tuple(step.step_number for step in self.steps)
        if numbers != tuple(range(1, len(self.steps) + 1)):
            raise ValueError("compiled step numbers must be contiguous from one")
        if self.candidate_id == "speed" and len(self.steps) > 4:
            raise ValueError("speed plans may contain at most four steps")
        known = set(numbers)
        depths: dict[int, int] = {}
        wave_widths: dict[int, int] = {}
        for step in self.steps:
            if any(dependency not in known or dependency >= step.step_number for dependency in step.depends_on):
                raise ValueError("step dependencies must reference earlier plan steps")
            for binding in step.input_bindings:
                if binding.source_step_number not in step.depends_on:
                    raise ValueError("binding sources must be direct declared dependencies")
            depth = 1 + max((depths[item] for item in step.depends_on), default=0)
            if depth > 4:
                raise ValueError("plan DAG depth exceeds four")
            depths[step.step_number] = depth
            wave_widths[depth] = wave_widths.get(depth, 0) + 1
        if any(width > self.max_wave_concurrency for width in wave_widths.values()):
            raise ValueError("plan wave width exceeds the frozen concurrency limit")
        return self


class ExecutionPlanVersionV3(StrictFrozenModel):
    id: Identifier
    run_id: Identifier
    requirement_version_id: Identifier
    version: Annotated[int, Field(ge=1)]
    schema_version: Literal["execution-plan-v3"]
    plan_hash: Sha256Hex
    payload: ExecutionPlanV3
    created_at: datetime

    @model_validator(mode="after")
    def validate_envelope(self) -> ExecutionPlanVersionV3:
        if self.schema_version != self.payload.schema_version:
            raise ValueError("plan envelope and payload schema versions must agree")
        if self.requirement_version_id != self.payload.requirement_version_id:
            raise ValueError("plan envelope and body requirement versions must agree")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        if self.plan_hash != canonical_json_v3_sha256(self.payload):
            raise ValueError("plan_hash does not match the canonical plan body")
        return self
