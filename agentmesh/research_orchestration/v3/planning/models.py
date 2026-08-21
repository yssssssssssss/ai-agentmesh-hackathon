from __future__ import annotations

from typing import Literal, Protocol

from pydantic import Field, model_validator

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.catalog import CompetitiveTextCatalog
from agentmesh.research_orchestration.v3.common import (
    ActorType,
    Identifier,
    ProblemGraphArtifactRefV3,
    SealedArtifactRefV3,
    Sha256Hex,
    StrictFrozenModel,
    require_unique,
)
from agentmesh.research_orchestration.v3.execution_plan import CapabilityResolutionV3, PlanCandidateSetV3
from agentmesh.research_orchestration.v3.problem_graph import ProblemGraphV1
from agentmesh.research_orchestration.v3.requirement import RequirementVersionV3, ResearchTaskV3
from agentmesh.research_orchestration.v3.snapshots import FrozenDocumentV3, ResearchControlSnapshotV3


class PlanningModelCallReceiptV3(StrictFrozenModel):
    """Provider-neutral proof attached to every model-shaped planning proposal."""

    id: Identifier
    run_id: Identifier
    stage: Literal["requirement_refinement", "problem_graph"]
    model_name: str = Field(min_length=1, max_length=120)
    model_version: str = Field(min_length=1, max_length=120)
    prompt_hash: Sha256Hex
    trace_id: Identifier
    context_manifest_hash: Sha256Hex
    output_hash: Sha256Hex


class RequirementProposalRequestV3(StrictFrozenModel):
    run_id: Identifier
    user_request: str = Field(min_length=1, max_length=20_000)
    previous: RequirementVersionV3 | None


class RequirementProposalV3(StrictFrozenModel):
    task: ResearchTaskV3
    receipt: PlanningModelCallReceiptV3

    @model_validator(mode="after")
    def validate_receipt(self) -> RequirementProposalV3:
        if self.receipt.stage != "requirement_refinement":
            raise ValueError("Requirement proposal requires a requirement_refinement receipt")
        if self.receipt.output_hash != canonical_json_v3_sha256(self.task):
            raise ValueError("Requirement proposal receipt does not bind the structured task")
        return self


class RequirementStructuredProposalPort(Protocol):
    async def propose(self, request: RequirementProposalRequestV3) -> RequirementProposalV3: ...


class RequirementPlanningResultV3(StrictFrozenModel):
    requirement: RequirementVersionV3
    receipt: PlanningModelCallReceiptV3

    @model_validator(mode="after")
    def validate_lineage(self) -> RequirementPlanningResultV3:
        if self.receipt.run_id != self.requirement.run_id:
            raise ValueError("Requirement receipt does not belong to the Requirement Run")
        if self.receipt.output_hash != self.requirement.content_hash:
            raise ValueError("Requirement receipt does not bind the version payload")
        return self


class ProblemGraphProposalV3(StrictFrozenModel):
    graph: ProblemGraphV1
    receipt: PlanningModelCallReceiptV3

    @model_validator(mode="after")
    def validate_receipt(self) -> ProblemGraphProposalV3:
        provenance = self.graph.provenance
        if self.receipt.stage != "problem_graph":
            raise ValueError("ProblemGraph proposal requires a problem_graph receipt")
        if self.receipt.output_hash != canonical_json_v3_sha256(self.graph):
            raise ValueError("ProblemGraph receipt does not bind the structured graph")
        if (
            provenance.model_call_receipt_id,
            provenance.model_name,
            provenance.model_version,
            provenance.prompt_hash,
            provenance.trace_id,
            provenance.context_manifest_hash,
        ) != (
            self.receipt.id,
            self.receipt.model_name,
            self.receipt.model_version,
            self.receipt.prompt_hash,
            self.receipt.trace_id,
            self.receipt.context_manifest_hash,
        ):
            raise ValueError("ProblemGraph provenance does not match its model receipt")
        return self


class ProblemGraphStructuredProposalPort(Protocol):
    async def propose(
        self,
        *,
        requirement: RequirementVersionV3,
        catalog: CompetitiveTextCatalog,
    ) -> ProblemGraphProposalV3: ...


class ProblemGraphPlanningResultV3(StrictFrozenModel):
    graph: ProblemGraphV1
    artifact: ProblemGraphArtifactRefV3
    receipt: PlanningModelCallReceiptV3

    @model_validator(mode="after")
    def validate_artifact(self) -> ProblemGraphPlanningResultV3:
        if self.artifact.content_hash != canonical_json_v3_sha256(self.graph):
            raise ValueError("ProblemGraph Artifact does not bind the planned graph")
        if self.receipt.output_hash != self.artifact.content_hash:
            raise ValueError("ProblemGraph receipt and Artifact bind different graph content")
        return self


class ActorRuntimeDescriptorV3(StrictFrozenModel):
    """Planning-time runtime identity; Tool descriptors must prove a real adapter."""

    actor_type: ActorType
    actor_id: Identifier
    implementation_id: str = Field(min_length=1, max_length=240)
    implementation_version: str = Field(min_length=1, max_length=120)
    execution_mode: Literal["real", "model", "deterministic"]
    health_state: Literal["healthy", "unavailable", "unknown", "stale"]
    enabled: bool
    authorized: bool
    required_provider: Identifier | None = None
    runtime_tool_definition_id: Identifier | None = None
    runtime_gateway_name: Identifier | None = None
    input_schema_document_id: Identifier
    output_schema_document_id: Identifier
    instruction_document_id: Identifier | None = None
    documents: tuple[FrozenDocumentV3, ...] = ()

    @model_validator(mode="after")
    def validate_documents(self) -> ActorRuntimeDescriptorV3:
        require_unique(tuple(item.document_id for item in self.documents), "descriptor document IDs")
        return self


class ActorDescriptorPort(Protocol):
    def describe(self, actor_type: ActorType, actor_id: Identifier) -> ActorRuntimeDescriptorV3 | None: ...


class ApprovalAvailabilityPort(Protocol):
    def can_request(
        self,
        *,
        run_id: Identifier,
        authority: Literal["owner", "legal", "security"],
        capability_type: Literal["skill", "tool"],
        capability_id: Identifier,
    ) -> bool: ...


class PlanningArtifactPort(Protocol):
    def seal_problem_graph(
        self,
        *,
        run_id: Identifier,
        graph: ProblemGraphV1,
    ) -> ProblemGraphArtifactRefV3: ...

    def seal_control_snapshot(
        self,
        *,
        run_id: Identifier,
        snapshot: ResearchControlSnapshotV3,
    ) -> SealedArtifactRefV3: ...

    def read_control_snapshot(
        self,
        artifact: SealedArtifactRefV3,
    ) -> ResearchControlSnapshotV3 | None: ...


class CapabilityResolutionResultV3(StrictFrozenModel):
    resolution: CapabilityResolutionV3
    snapshot: ResearchControlSnapshotV3

    @model_validator(mode="after")
    def validate_snapshot_artifact(self) -> CapabilityResolutionResultV3:
        artifact = self.resolution.control_snapshot_artifact
        if artifact.kind != "research_control_snapshot" or artifact.schema_version != "research-control-snapshot-v3":
            raise ValueError("Capability resolution requires a research-v3 control snapshot Artifact")
        if artifact.content_hash != canonical_json_v3_sha256(self.snapshot):
            raise ValueError("Capability resolution Artifact does not bind its frozen snapshot")
        return self


class CompetitiveTextPlanningBundleV3(StrictFrozenModel):
    requirement: RequirementVersionV3
    requirement_receipt: PlanningModelCallReceiptV3
    problem_graph: ProblemGraphV1 | None = None
    problem_graph_artifact: ProblemGraphArtifactRefV3 | None = None
    capabilities: CapabilityResolutionV3 | None = None
    candidates: PlanCandidateSetV3 | None = None

    @model_validator(mode="after")
    def validate_state(self) -> CompetitiveTextPlanningBundleV3:
        planning_values = (
            self.problem_graph,
            self.problem_graph_artifact,
            self.capabilities,
            self.candidates,
        )
        if self.requirement.payload.planning_blocked:
            if any(value is not None for value in planning_values):
                raise ValueError("blocked Requirements cannot contain downstream planning outputs")
        elif any(value is None for value in planning_values):
            raise ValueError("unblocked Requirements require complete planning outputs")
        if (
            self.problem_graph is not None
            and self.problem_graph_artifact is not None
            and self.problem_graph_artifact.content_hash != canonical_json_v3_sha256(self.problem_graph)
        ):
            raise ValueError("planning bundle ProblemGraph Artifact hash mismatch")
        return self
