from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from agentmesh.research_orchestration.v3.catalog import CompetitiveTextCatalog
from agentmesh.research_orchestration.v3.common import ActorType, Identifier, StrictFrozenModel, SealedArtifactRefV3
from agentmesh.research_orchestration.v3.deliverable import ResearchDeliverableV3
from agentmesh.research_orchestration.v3.execution_plan import (
    CapabilityResolutionV3,
    ExecutionPlanV3,
    ExecutionPlanVersionV3,
    PlanCandidateSetV3,
    PlanCandidateV3,
    PlanStepV3,
)
from agentmesh.research_orchestration.v3.problem_graph import ProblemGraphV1
from agentmesh.research_orchestration.v3.report_document import ReportDocumentV3
from agentmesh.research_orchestration.v3.requirement import RequirementVersionV3, ResearchTaskV3
from agentmesh.research_orchestration.v3.review import ReportReviewV3


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


class CandidateCompilerPort(Protocol):
    def compile(
        self,
        *,
        requirement: RequirementVersionV3,
        problem_graph: ProblemGraphV1,
        capabilities: CapabilityResolutionV3,
        candidate: PlanCandidateV3,
    ) -> ExecutionPlanV3: ...


class ActorExecutionRequestV3(StrictFrozenModel):
    run_id: Identifier
    plan_version_id: Identifier
    attempt_id: Identifier
    step: PlanStepV3
    resolved_input: dict[str, Any]


class ActorExecutionResultV3(StrictFrozenModel):
    actor_type: ActorType
    actor_id: Identifier
    result_artifact: SealedArtifactRefV3
    receipt_id: Identifier


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
    ) -> ResearchDeliverableV3: ...


class ReviewPort(Protocol):
    async def review(
        self,
        *,
        deliverable: ResearchDeliverableV3,
        deliverable_artifact: SealedArtifactRefV3,
        revision_round: int,
    ) -> ReportReviewV3: ...


class ReportCompositionPort(Protocol):
    def compose(
        self,
        *,
        deliverable: ResearchDeliverableV3,
        deliverable_artifact: SealedArtifactRefV3,
        review: ReportReviewV3,
        review_artifact: SealedArtifactRefV3,
    ) -> ReportDocumentV3: ...


class ResearchV3RepositoryPort(Protocol):
    """Persistence boundary; no implementation is reachable from this foundation."""

    def get_requirement(self, run_id: Identifier, version_id: Identifier) -> RequirementVersionV3 | None: ...

    def append_requirement(
        self,
        requirement: RequirementVersionV3,
        *,
        expected_state_version: int,
    ) -> None: ...

    def get_problem_graph(self, artifact: SealedArtifactRefV3) -> ProblemGraphV1 | None: ...

    def seal_problem_graph(
        self,
        run_id: Identifier,
        graph: ProblemGraphV1,
        *,
        expected_state_version: int,
    ) -> SealedArtifactRefV3: ...

    def get_plan(self, run_id: Identifier, version_id: Identifier) -> ExecutionPlanVersionV3 | None: ...

    def append_plan(
        self,
        plan: ExecutionPlanVersionV3,
        *,
        expected_state_version: int,
    ) -> None: ...

    def seal_artifact(
        self,
        run_id: Identifier,
        payload: StrictFrozenModel,
        *,
        kind: Identifier,
        schema_version: Identifier,
        expected_state_version: int,
    ) -> SealedArtifactRefV3: ...
