from __future__ import annotations

from datetime import datetime
from typing import Annotated, Protocol

from pydantic import Field

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.catalog import CompetitiveTextCatalog
from agentmesh.research_orchestration.v3.common import (
    ActorType,
    EvidenceManifestArtifactRefV3,
    FrozenJsonObject,
    Identifier,
    ProblemGraphArtifactRefV3,
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
from agentmesh.research_orchestration.v3.execution_plan import (
    CapabilityResolutionV3,
    ExecutionPlanV3,
    ExecutionPlanVersionV3,
    PlanCandidateSetV3,
    PlanCandidateV3,
    PlanStepV3,
)
from agentmesh.research_orchestration.v3.problem_graph import ProblemGraphV1, validate_problem_graph_for_task
from agentmesh.research_orchestration.v3.report_document import ReportDocumentV3
from agentmesh.research_orchestration.v3.requirement import RequirementVersionV3, ResearchTaskV3
from agentmesh.research_orchestration.v3.review import PassedReportReviewV3, ReportReviewV3
from agentmesh.research_orchestration.v3.snapshots import ResearchControlSnapshotV3


class ClockPort(Protocol):
    def now(self) -> datetime: ...


class IdGeneratorPort(Protocol):
    def new(self, prefix: str) -> Identifier: ...


class RequirementPlanningPort(Protocol):
    async def refine(
        self,
        *,
        run_id: Identifier,
        user_request: str,
        previous: RequirementVersionV3 | None,
    ) -> ResearchTaskV3: ...


class ProblemGraphPlanningPort(Protocol):
    async def plan(
        self,
        *,
        requirement: RequirementVersionV3,
        catalog: CompetitiveTextCatalog,
    ) -> ProblemGraphV1: ...


class CapabilityResolutionPort(Protocol):
    def resolve(
        self,
        *,
        run_id: Identifier,
        requirement: RequirementVersionV3,
        problem_graph: ProblemGraphV1,
        catalog: CompetitiveTextCatalog,
    ) -> CapabilityResolutionV3: ...


class CandidateGenerationPort(Protocol):
    async def generate(
        self,
        *,
        requirement: RequirementVersionV3,
        problem_graph: ProblemGraphV1,
        capabilities: CapabilityResolutionV3,
    ) -> PlanCandidateSetV3: ...


class CandidateCompilationRequestV3(StrictFrozenModel):
    """Validated compiler boundary; the sealed graph must match the supplied body."""

    requirement: RequirementVersionV3
    problem_graph: ProblemGraphV1
    problem_graph_artifact: ProblemGraphArtifactRefV3
    capabilities: CapabilityResolutionV3
    candidate: PlanCandidateV3

    def model_post_init(self, context: object) -> None:
        del context
        if self.problem_graph_artifact.content_hash != canonical_json_v3_sha256(self.problem_graph):
            raise ValueError("ProblemGraph Artifact hash does not match the canonical ProblemGraph body")


class CandidateCompilerPort(Protocol):
    def compile(self, request: CandidateCompilationRequestV3) -> ExecutionPlanV3: ...


class ActorExecutionRequestV3(StrictFrozenModel):
    run_id: Identifier
    plan_version_id: Identifier
    attempt_id: Identifier
    step: PlanStepV3
    resolved_input: FrozenJsonObject


class ActorExecutionResultV3(StrictFrozenModel):
    """A completion envelope that retains identity even when parallel results are reordered."""

    run_id: Identifier
    plan_version_id: Identifier
    attempt_id: Identifier
    step_number: Annotated[int, Field(ge=1, le=8)]
    actor_type: ActorType
    actor_id: Identifier
    step_contract_hash: Sha256Hex
    result_artifact: SealedArtifactRefV3
    receipt_id: Identifier


def validate_actor_result_for_request(
    request: ActorExecutionRequestV3,
    result: ActorExecutionResultV3,
) -> None:
    if (
        result.run_id,
        result.plan_version_id,
        result.attempt_id,
        result.step_number,
        result.actor_type,
        result.actor_id,
        result.step_contract_hash,
    ) != (
        request.run_id,
        request.plan_version_id,
        request.attempt_id,
        request.step.step_number,
        request.step.actor_type,
        request.step.actor_id,
        request.step.contract_hash,
    ):
        raise ValueError("Actor execution result does not match its request lineage and step contract")


def _validate_plan_requirement_lineage(
    requirement: RequirementVersionV3,
    plan: ExecutionPlanVersionV3,
) -> None:
    if (
        plan.run_id,
        plan.requirement_version_id,
        plan.payload.requirement_version_id,
        plan.payload.requirement_content_hash,
    ) != (
        requirement.run_id,
        requirement.id,
        requirement.id,
        requirement.content_hash,
    ):
        raise ValueError("selected Plan does not match the Requirement version and content")


def validate_delivery_inputs(
    *,
    requirement: RequirementVersionV3,
    plan: ExecutionPlanVersionV3,
    attempt_id: Identifier,
    actor_results: tuple[ActorExecutionResultV3, ...],
    evidence_manifest: EvidenceManifestV3,
    evidence_manifest_artifact: EvidenceManifestArtifactRefV3,
) -> None:
    """Validate the complete typed delivery boundary before composition."""

    _validate_plan_requirement_lineage(requirement, plan)
    if canonical_json_v3_sha256(evidence_manifest) != evidence_manifest_artifact.content_hash:
        raise ValueError("Evidence Manifest does not match its sealed Artifact")
    if (
        evidence_manifest.run_id,
        evidence_manifest.plan_version_id,
        evidence_manifest.attempt_id,
    ) != (requirement.run_id, plan.id, attempt_id):
        raise ValueError("Evidence Manifest does not match the selected Plan attempt")
    result_steps = tuple(result.step_number for result in actor_results)
    require_unique(result_steps, "delivery actor result step numbers")
    if set(result_steps) != {step.step_number for step in plan.payload.steps}:
        raise ValueError("delivery actor results must exactly cover selected Plan steps")
    steps = {step.step_number: step for step in plan.payload.steps}
    for result in actor_results:
        step = steps[result.step_number]
        if (
            result.run_id,
            result.plan_version_id,
            result.attempt_id,
            result.actor_type,
            result.actor_id,
            result.step_contract_hash,
        ) != (
            requirement.run_id,
            plan.id,
            attempt_id,
            step.actor_type,
            step.actor_id,
            step.contract_hash,
        ):
            raise ValueError("delivery actor result drifted from the selected Plan")
    result_artifacts = {result.result_artifact for result in actor_results}
    for evidence in evidence_manifest.evidence:
        if evidence.pointer.artifact not in result_artifacts:
            raise ValueError("Evidence Artifact is not a successful selected-Plan result")


def validate_review_inputs(
    *,
    requirement: RequirementVersionV3,
    plan: ExecutionPlanVersionV3,
    problem_graph: ProblemGraphV1,
    deliverable: ResearchDeliverableV3,
    deliverable_artifact: SealedArtifactRefV3,
    evidence_manifest: EvidenceManifestV3,
    evidence_manifest_artifact: EvidenceManifestArtifactRefV3,
    evidence_artifacts: tuple[VerifiedArtifactContentV3, ...],
) -> None:
    """Validate lineage, graph coverage, sealed inputs, and evidence before Review."""

    _validate_plan_requirement_lineage(requirement, plan)
    if problem_graph.requirement_version_id != requirement.id:
        raise ValueError("ProblemGraph does not belong to the Requirement version")
    if plan.payload.problem_graph_artifact.content_hash != canonical_json_v3_sha256(problem_graph):
        raise ValueError("selected Plan does not bind the supplied ProblemGraph")
    validate_problem_graph_for_task(
        problem_graph,
        requirement.payload,
        policy_requirements=plan.payload.evidence_requirements,
    )
    if (
        deliverable_artifact.kind != "research_deliverable"
        or deliverable_artifact.schema_version != "research-deliverable-v3"
    ):
        raise ValueError("Review requires a sealed research-deliverable-v3 Artifact")
    if canonical_json_v3_sha256(deliverable) != deliverable_artifact.content_hash:
        raise ValueError("Deliverable does not match its sealed Artifact")
    if (
        deliverable.run_id,
        deliverable.requirement_version_id,
        deliverable.plan_version_id,
        deliverable.attempt_id,
    ) != (
        requirement.run_id,
        requirement.id,
        plan.id,
        evidence_manifest.attempt_id,
    ):
        raise ValueError("Deliverable does not match the Requirement and selected Plan lineage")
    if deliverable.evidence_manifest_artifact != evidence_manifest_artifact:
        raise ValueError("Deliverable does not bind the supplied Evidence Manifest")
    if canonical_json_v3_sha256(evidence_manifest) != evidence_manifest_artifact.content_hash:
        raise ValueError("Evidence Manifest does not match its sealed Artifact")
    if (
        evidence_manifest.run_id,
        evidence_manifest.plan_version_id,
        evidence_manifest.attempt_id,
    ) != (requirement.run_id, plan.id, deliverable.attempt_id):
        raise ValueError("Evidence Manifest does not match the reviewed execution lineage")
    verify_evidence_manifest_artifacts(evidence_manifest, evidence_artifacts)
    planned_questions = {
        question_id for step in plan.payload.steps for question_id in step.question_ids
    }
    required_questions = {
        question.id for question in problem_graph.questions if question.priority == "required"
    }
    if planned_questions != required_questions:
        raise ValueError("selected Plan does not exactly cover required ProblemGraph questions")
    covered_questions = {item.question_id for item in deliverable.coverage.question_coverage}
    if covered_questions != planned_questions:
        raise ValueError("Deliverable question coverage does not exactly match the selected Plan")
    covered_criteria = {
        item.success_criterion_id for item in deliverable.coverage.success_criterion_coverage
    }
    if covered_criteria != {item.id for item in requirement.payload.success_criteria}:
        raise ValueError("Deliverable success coverage does not exactly match the Requirement")


class HeterogeneousActorExecutionPort(Protocol):
    async def execute(self, request: ActorExecutionRequestV3) -> ActorExecutionResultV3: ...


class DeliveryPort(Protocol):
    async def create_deliverable(
        self,
        *,
        requirement: RequirementVersionV3,
        plan: ExecutionPlanVersionV3,
        attempt_id: Identifier,
        actor_results: tuple[ActorExecutionResultV3, ...],
        evidence_manifest: EvidenceManifestV3,
        evidence_manifest_artifact: EvidenceManifestArtifactRefV3,
    ) -> ResearchDeliverableV3: ...


class ReviewPort(Protocol):
    async def review(
        self,
        *,
        requirement: RequirementVersionV3,
        plan: ExecutionPlanVersionV3,
        problem_graph: ProblemGraphV1,
        deliverable: ResearchDeliverableV3,
        deliverable_artifact: SealedArtifactRefV3,
        evidence_manifest: EvidenceManifestV3,
        evidence_manifest_artifact: EvidenceManifestArtifactRefV3,
        evidence_artifacts: tuple[VerifiedArtifactContentV3, ...],
        revision_round: int,
    ) -> ReportReviewV3: ...


class ReportCompositionPort(Protocol):
    def compose(
        self,
        *,
        deliverable: ResearchDeliverableV3,
        deliverable_artifact: SealedArtifactRefV3,
        review: PassedReportReviewV3,
        review_artifact: SealedArtifactRefV3,
    ) -> ReportDocumentV3: ...


class ResearchV3RepositoryPort(Protocol):
    """Typed persistence reads/writes; no implementation is reachable from this foundation."""

    def get_requirement(self, run_id: Identifier, version_id: Identifier) -> RequirementVersionV3 | None: ...

    def append_requirement(
        self,
        requirement: RequirementVersionV3,
        *,
        expected_state_version: int,
    ) -> None: ...

    def get_candidate_set(
        self,
        run_id: Identifier,
        requirement_version_id: Identifier,
    ) -> PlanCandidateSetV3 | None: ...

    def append_candidate_set(
        self,
        run_id: Identifier,
        requirement_version_id: Identifier,
        candidate_set: PlanCandidateSetV3,
        *,
        expected_state_version: int,
    ) -> None: ...

    def get_problem_graph(self, artifact: ProblemGraphArtifactRefV3) -> ProblemGraphV1 | None: ...

    def seal_problem_graph(
        self,
        run_id: Identifier,
        graph: ProblemGraphV1,
        *,
        expected_state_version: int,
    ) -> ProblemGraphArtifactRefV3: ...

    def get_plan(self, run_id: Identifier, version_id: Identifier) -> ExecutionPlanVersionV3 | None: ...

    def append_plan(
        self,
        plan: ExecutionPlanVersionV3,
        *,
        expected_state_version: int,
    ) -> None: ...

    def get_control_snapshot(
        self,
        artifact: SealedArtifactRefV3,
    ) -> ResearchControlSnapshotV3 | None: ...

    def append_control_snapshot(
        self,
        run_id: Identifier,
        snapshot: ResearchControlSnapshotV3,
        *,
        expected_state_version: int,
    ) -> SealedArtifactRefV3: ...

    def get_actor_results(
        self,
        run_id: Identifier,
        plan_version_id: Identifier,
        attempt_id: Identifier,
    ) -> tuple[ActorExecutionResultV3, ...]: ...

    def append_actor_result(
        self,
        result: ActorExecutionResultV3,
        *,
        expected_state_version: int,
    ) -> None: ...

    def get_evidence_manifest(
        self,
        artifact: EvidenceManifestArtifactRefV3,
    ) -> EvidenceManifestV3 | None: ...

    def append_evidence_manifest(
        self,
        manifest: EvidenceManifestV3,
        *,
        expected_state_version: int,
    ) -> EvidenceManifestArtifactRefV3: ...

    def get_deliverable(self, artifact: SealedArtifactRefV3) -> ResearchDeliverableV3 | None: ...

    def append_deliverable(
        self,
        deliverable: ResearchDeliverableV3,
        *,
        expected_state_version: int,
    ) -> SealedArtifactRefV3: ...

    def get_review(self, artifact: SealedArtifactRefV3) -> ReportReviewV3 | None: ...

    def append_review(
        self,
        review: ReportReviewV3,
        *,
        expected_state_version: int,
    ) -> SealedArtifactRefV3: ...

    def get_report(self, artifact: SealedArtifactRefV3) -> ReportDocumentV3 | None: ...

    def append_report(
        self,
        report: ReportDocumentV3,
        *,
        expected_state_version: int,
    ) -> SealedArtifactRefV3: ...


class ArtifactReadPort(Protocol):
    """Verified Artifact readback; fail closed on any owner, lineage, or hash mismatch."""

    def read_verified_json(
        self,
        *,
        run_id: Identifier,
        plan_version_id: Identifier,
        attempt_id: Identifier,
        step_number: Annotated[int, Field(ge=1, le=8)],
        artifact: SealedArtifactRefV3,
    ) -> VerifiedArtifactContentV3 | None: ...
