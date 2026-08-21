from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, RootModel, model_validator

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.common import (
    ActorType,
    ApprovalRole,
    EvidenceManifestArtifactRefV3,
    FrozenJsonObject,
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
from agentmesh.research_orchestration.v3.execution_plan import ExecutionPlanVersionV3, PlanCandidateSetV3
from agentmesh.research_orchestration.v3.ports import ActorExecutionResultV3
from agentmesh.research_orchestration.v3.report_document import ReportDocumentV3
from agentmesh.research_orchestration.v3.requirement import RequirementVersionV3
from agentmesh.research_orchestration.v3.review import ReportReviewV3

WorkbenchStateId = Literal[
    "idle",
    "clarify",
    "candidates",
    "plan",
    "approval",
    "dag_or_executing",
    "paused",
    "text_report",
]
GateKind = Literal[
    "none",
    "clarification",
    "candidate_selection",
    "plan_confirmation",
    "role_approval",
    "recovery",
]


class WorkbenchGateV1(StrictFrozenModel):
    kind: GateKind
    status: Literal["inactive", "pending", "satisfied", "blocked"]
    required_role: ApprovalRole | None = None

    @model_validator(mode="after")
    def validate_gate(self) -> WorkbenchGateV1:
        if self.kind == "none" and (self.status != "inactive" or self.required_role is not None):
            raise ValueError("an inactive Workbench gate must have kind none and no role")
        if self.kind != "role_approval" and self.required_role is not None:
            raise ValueError("only role approval gates may name a required role")
        if self.kind == "role_approval" and self.required_role is None:
            raise ValueError("role approval gates require a role")
        return self


class WorkbenchWorkflowV1(StrictFrozenModel):
    state: WorkbenchStateId
    state_version: Annotated[int, Field(ge=0)]
    gate: WorkbenchGateV1


class WorkbenchApprovalV1(StrictFrozenModel):
    gate_key: Identifier
    plan_version_id: Identifier
    role: ApprovalRole
    decision: Literal["pending", "approved", "rejected"]
    receipt_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_decision_receipt(self) -> WorkbenchApprovalV1:
        if (self.decision == "pending") != (self.receipt_id is None):
            raise ValueError("approval receipts are present exactly for settled decisions")
        return self


class WorkbenchStepV1(StrictFrozenModel):
    step_number: Annotated[int, Field(ge=1, le=8)]
    actor_type: ActorType
    actor_id: Identifier
    step_contract_hash: Sha256Hex
    status: Literal["pending", "running", "succeeded", "failed", "skipped"]
    result: ActorExecutionResultV3 | None = None
    failure_code: Identifier | None = None

    @model_validator(mode="after")
    def validate_step_result(self) -> WorkbenchStepV1:
        if self.status == "succeeded" and self.result is None:
            raise ValueError("a succeeded Workbench step requires its bound result")
        if self.status != "succeeded" and self.result is not None:
            raise ValueError("only succeeded Workbench steps expose a result")
        if self.status == "failed" and self.failure_code is None:
            raise ValueError("a failed Workbench step requires a failure code")
        if self.status != "failed" and self.failure_code is not None:
            raise ValueError("only failed Workbench steps expose a failure code")
        if self.result is not None and (
            self.result.step_number,
            self.result.actor_type,
            self.result.actor_id,
            self.result.step_contract_hash,
        ) != (
            self.step_number,
            self.actor_type,
            self.actor_id,
            self.step_contract_hash,
        ):
            raise ValueError("Workbench step result does not match its plan-step identity")
        return self


class WorkbenchAttemptV1(StrictFrozenModel):
    attempt_id: Identifier
    run_id: Identifier
    plan_version_id: Identifier
    status: Literal["running", "paused", "completed"]
    steps: tuple[WorkbenchStepV1, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_steps(self) -> WorkbenchAttemptV1:
        numbers = tuple(step.step_number for step in self.steps)
        require_unique(numbers, "Workbench attempt step numbers")
        if numbers != tuple(sorted(numbers)):
            raise ValueError("Workbench attempt steps must be sorted")
        for step in self.steps:
            if step.result is not None and (
                step.result.run_id,
                step.result.plan_version_id,
                step.result.attempt_id,
            ) != (self.run_id, self.plan_version_id, self.attempt_id):
                raise ValueError("Workbench step result does not belong to its attempt")
        return self


class WorkbenchRecoveryV1(StrictFrozenModel):
    failed_step_number: Annotated[int, Field(ge=1, le=8)]
    reason_code: Identifier
    allowed_actions: tuple[Literal["retry", "skip", "abort"], ...] = Field(min_length=1)
    decision_required: Literal[True] = True

    @model_validator(mode="after")
    def validate_actions(self) -> WorkbenchRecoveryV1:
        require_unique(self.allowed_actions, "Workbench recovery actions")
        return self


class WorkbenchEvidenceV1(StrictFrozenModel):
    artifact: EvidenceManifestArtifactRefV3
    manifest: EvidenceManifestV3
    verified_artifacts: tuple[VerifiedArtifactContentV3, ...]

    @model_validator(mode="after")
    def validate_evidence(self) -> WorkbenchEvidenceV1:
        if canonical_json_v3_sha256(self.manifest) != self.artifact.content_hash:
            raise ValueError("Workbench Evidence Manifest does not match its sealed Artifact")
        verify_evidence_manifest_artifacts(self.manifest, self.verified_artifacts)
        return self


class WorkbenchDeliverableV1(StrictFrozenModel):
    artifact: SealedArtifactRefV3
    content: ResearchDeliverableV3

    @model_validator(mode="after")
    def validate_deliverable(self) -> WorkbenchDeliverableV1:
        if self.artifact.kind != "research_deliverable" or self.artifact.schema_version != "research-deliverable-v3":
            raise ValueError("Workbench deliverable Artifact identity is invalid")
        if canonical_json_v3_sha256(self.content) != self.artifact.content_hash:
            raise ValueError("Workbench deliverable does not match its sealed Artifact")
        return self


class WorkbenchReviewV1(StrictFrozenModel):
    artifact: SealedArtifactRefV3
    content: ReportReviewV3

    @model_validator(mode="after")
    def validate_review(self) -> WorkbenchReviewV1:
        if self.artifact.kind != "report_review" or self.artifact.schema_version != "report-review-v3":
            raise ValueError("Workbench review Artifact identity is invalid")
        if canonical_json_v3_sha256(self.content) != self.artifact.content_hash:
            raise ValueError("Workbench review does not match its sealed Artifact")
        return self


class WorkbenchReportV1(StrictFrozenModel):
    artifact: SealedArtifactRefV3
    content: ReportDocumentV3

    @model_validator(mode="after")
    def validate_report(self) -> WorkbenchReportV1:
        if self.artifact.kind != "report_document" or self.artifact.schema_version != "report-document-v3":
            raise ValueError("Workbench report Artifact identity is invalid")
        if canonical_json_v3_sha256(self.content) != self.artifact.content_hash:
            raise ValueError("Workbench report does not match its sealed Artifact")
        return self


class WorkbenchProjectionProvenanceV1(StrictFrozenModel):
    source_kind: Literal["isolated_fixture", "repository_projection", "v2_history_adapter"]
    projection_schema_version: Literal["research-workbench-aggregate-v1"]
    projected_at: datetime
    source_state_version: Annotated[int, Field(ge=0)]
    baseline_state_id: WorkbenchStateId | None = None

    @model_validator(mode="after")
    def validate_projected_at(self) -> WorkbenchProjectionProvenanceV1:
        if self.projected_at.tzinfo is None or self.projected_at.utcoffset() is None:
            raise ValueError("projection timestamp must include a timezone")
        if self.source_kind == "isolated_fixture" and self.baseline_state_id is None:
            raise ValueError("isolated Workbench fixtures require a baseline state ID")
        if self.source_kind != "isolated_fixture" and self.baseline_state_id is not None:
            raise ValueError("only isolated fixtures may bind a baseline state ID")
        return self


class ResearchV3WorkbenchAggregateV1(StrictFrozenModel):
    schema_version: Literal["research-workbench-aggregate-v1"]
    projection_kind: Literal["research-v3-current"]
    orchestration_version: Literal["research-v3"]
    run_id: Identifier
    workflow: WorkbenchWorkflowV1
    requirement: RequirementVersionV3 | None
    candidates: PlanCandidateSetV3 | None
    selected_plan: ExecutionPlanVersionV3 | None
    approvals: tuple[WorkbenchApprovalV1, ...]
    attempt: WorkbenchAttemptV1 | None
    recovery: WorkbenchRecoveryV1 | None
    evidence: WorkbenchEvidenceV1 | None
    deliverable: WorkbenchDeliverableV1 | None
    review: WorkbenchReviewV1 | None
    report: WorkbenchReportV1 | None
    provenance: WorkbenchProjectionProvenanceV1

    @model_validator(mode="after")
    def validate_projection(self) -> ResearchV3WorkbenchAggregateV1:
        expected_gate = {
            "idle": ("none", "inactive"),
            "clarify": ("clarification", "pending"),
            "candidates": ("candidate_selection", "pending"),
            "plan": ("plan_confirmation", "pending"),
            "approval": ("role_approval", "pending"),
            "dag_or_executing": ("none", "inactive"),
            "paused": ("recovery", "blocked"),
            "text_report": ("none", "inactive"),
        }[self.workflow.state]
        if (self.workflow.gate.kind, self.workflow.gate.status) != expected_gate:
            raise ValueError("Workbench workflow state and active gate do not agree")
        if self.provenance.source_state_version != self.workflow.state_version:
            raise ValueError("Workbench provenance and workflow state versions do not agree")
        if self.provenance.baseline_state_id not in {None, self.workflow.state}:
            raise ValueError("Workbench fixture provenance names a different baseline state")

        present = {
            name
            for name in (
                "requirement",
                "candidates",
                "selected_plan",
                "attempt",
                "recovery",
                "evidence",
                "deliverable",
                "review",
                "report",
            )
            if getattr(self, name) is not None
        }
        required_by_state = {
            "idle": set(),
            "clarify": {"requirement"},
            "candidates": {"requirement", "candidates"},
            "plan": {"requirement", "candidates", "selected_plan"},
            "approval": {"requirement", "candidates", "selected_plan"},
            "dag_or_executing": {"requirement", "candidates", "selected_plan", "attempt"},
            "paused": {"requirement", "candidates", "selected_plan", "attempt", "recovery"},
            "text_report": {
                "requirement",
                "candidates",
                "selected_plan",
                "attempt",
                "evidence",
                "deliverable",
                "review",
                "report",
            },
        }[self.workflow.state]
        if present != required_by_state:
            raise ValueError("Workbench aggregate fields do not match the frozen state projection")

        if self.workflow.state == "idle":
            if self.approvals:
                raise ValueError("idle Workbench projection cannot contain approvals")
            return self
        if self.requirement is None or self.requirement.run_id != self.run_id:
            raise ValueError("Workbench requirement does not belong to the projected run")
        if self.selected_plan is not None:
            if (
                self.selected_plan.run_id != self.run_id
                or self.selected_plan.requirement_version_id != self.requirement.id
            ):
                raise ValueError("Workbench selected plan lineage is invalid")
        if self.workflow.state in {"clarify", "candidates", "plan"} and self.approvals:
            raise ValueError("pre-approval Workbench states cannot contain approvals")
        if self.workflow.state == "approval":
            if not self.approvals or not any(item.decision == "pending" for item in self.approvals):
                raise ValueError("approval state requires a pending approval")
        if self.selected_plan is not None:
            if any(item.plan_version_id != self.selected_plan.id for item in self.approvals):
                raise ValueError("Workbench approval references a different selected plan")
        if self.workflow.state in {"dag_or_executing", "paused", "text_report"}:
            if not self.approvals or any(item.decision != "approved" for item in self.approvals):
                raise ValueError("execution and report states require settled approvals")
            if self.attempt is None or self.selected_plan is None or (
                self.attempt.run_id,
                self.attempt.plan_version_id,
            ) != (self.run_id, self.selected_plan.id):
                raise ValueError("Workbench attempt does not belong to the selected plan")
        if self.workflow.state == "dag_or_executing" and self.attempt is not None and self.attempt.status != "running":
            raise ValueError("executing Workbench state requires a running attempt")
        if self.workflow.state == "paused" and self.attempt is not None:
            if self.attempt.status != "paused" or self.recovery is None:
                raise ValueError("paused Workbench state requires a paused attempt and recovery")
            failed = {step.step_number for step in self.attempt.steps if step.status == "failed"}
            if self.recovery.failed_step_number not in failed:
                raise ValueError("Workbench recovery must identify a failed step")
        if self.workflow.state == "text_report":
            self._validate_report_lineage()
        return self

    def _validate_report_lineage(self) -> None:
        if not all((self.attempt, self.selected_plan, self.evidence, self.deliverable, self.review, self.report)):
            raise ValueError("text report projection is incomplete")
        assert self.attempt is not None
        assert self.selected_plan is not None
        assert self.evidence is not None
        assert self.deliverable is not None
        assert self.review is not None
        assert self.report is not None
        if self.attempt.status != "completed":
            raise ValueError("text report projection requires a completed attempt")
        lineage = (self.run_id, self.selected_plan.id, self.attempt.attempt_id)
        evidence_lineage = (
            self.evidence.manifest.run_id,
            self.evidence.manifest.plan_version_id,
            self.evidence.manifest.attempt_id,
        )
        if evidence_lineage != lineage:
            raise ValueError("Workbench Evidence Manifest lineage is invalid")
        deliverable = self.deliverable.content
        if (deliverable.run_id, deliverable.plan_version_id, deliverable.attempt_id) != lineage:
            raise ValueError("Workbench deliverable lineage is invalid")
        if deliverable.evidence_manifest_artifact != self.evidence.artifact:
            raise ValueError("Workbench deliverable references a different Evidence Manifest")
        review = self.review.content
        if (review.run_id, review.plan_version_id, review.attempt_id) != lineage:
            raise ValueError("Workbench review lineage is invalid")
        if review.deliverable_artifact != self.deliverable.artifact:
            raise ValueError("Workbench review references a different deliverable")
        report = self.report.content
        if (report.run_id, report.plan_version_id, report.attempt_id) != lineage:
            raise ValueError("Workbench report lineage is invalid")
        if report.deliverable_artifact != self.deliverable.artifact or report.review_artifact != self.review.artifact:
            raise ValueError("Workbench report references different reviewed Artifacts")


class ResearchV2HistoryWorkbenchAggregateV1(StrictFrozenModel):
    schema_version: Literal["research-workbench-aggregate-v1"]
    projection_kind: Literal["research-v2-history"]
    orchestration_version: Literal["research-v2"]
    read_only: Literal[True] = True
    run_id: Identifier
    history_payload: FrozenJsonObject
    provenance: WorkbenchProjectionProvenanceV1

    @model_validator(mode="after")
    def validate_history_provenance(self) -> ResearchV2HistoryWorkbenchAggregateV1:
        if self.provenance.source_kind != "v2_history_adapter":
            raise ValueError("v2 history projections require v2_history_adapter provenance")
        return self


_WorkbenchAggregateValue = Annotated[
    ResearchV3WorkbenchAggregateV1 | ResearchV2HistoryWorkbenchAggregateV1,
    Field(discriminator="projection_kind"),
]


class WorkbenchAggregateV1(RootModel[_WorkbenchAggregateValue]):
    """Version-first Web DTO; deliberately not wired into the production API."""

    model_config = ConfigDict(frozen=True)
