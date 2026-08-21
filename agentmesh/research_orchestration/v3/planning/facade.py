from __future__ import annotations

from agentmesh.research_orchestration.v3.catalog import CompetitiveTextCatalog
from agentmesh.research_orchestration.v3.execution_plan import ExecutionPlanVersionV3
from agentmesh.research_orchestration.v3.planning.candidates import CompetitiveTextCandidateGenerator
from agentmesh.research_orchestration.v3.planning.capabilities import CompetitiveTextCapabilityResolver
from agentmesh.research_orchestration.v3.planning.compiler import CompetitiveTextCandidateCompiler
from agentmesh.research_orchestration.v3.planning.models import CompetitiveTextPlanningBundleV3
from agentmesh.research_orchestration.v3.planning.problem_graphs import CompetitiveTextProblemGraphPlanner
from agentmesh.research_orchestration.v3.planning.requirements import CompetitiveTextRequirementPlanner
from agentmesh.research_orchestration.v3.ports import CandidateCompilationRequestV3
from agentmesh.research_orchestration.v3.requirement import RequirementVersionV3


class CompetitiveTextPlanningFacade:
    """Non-routed composition facade for the isolated pure-planning lane."""

    def __init__(
        self,
        *,
        catalog: CompetitiveTextCatalog,
        requirements: CompetitiveTextRequirementPlanner,
        problem_graphs: CompetitiveTextProblemGraphPlanner,
        capabilities: CompetitiveTextCapabilityResolver,
        candidates: CompetitiveTextCandidateGenerator,
        compiler: CompetitiveTextCandidateCompiler,
    ) -> None:
        self._catalog = catalog
        self._requirements = requirements
        self._problem_graphs = problem_graphs
        self._capabilities = capabilities
        self._candidates = candidates
        self._compiler = compiler

    async def prepare(
        self,
        *,
        run_id: str,
        user_request: str,
        previous_requirement: RequirementVersionV3 | None = None,
    ) -> CompetitiveTextPlanningBundleV3:
        requirement_result = await self._requirements.refine_version(
            run_id=run_id,
            user_request=user_request,
            previous=previous_requirement,
        )
        requirement = requirement_result.requirement
        if requirement.payload.planning_blocked:
            return CompetitiveTextPlanningBundleV3(
                requirement=requirement,
                requirement_receipt=requirement_result.receipt,
            )
        graph_result = await self._problem_graphs.plan_and_seal(
            requirement=requirement,
            catalog=self._catalog,
        )
        capabilities = self._capabilities.resolve(
            run_id=run_id,
            requirement=requirement,
            problem_graph=graph_result.graph,
            catalog=self._catalog,
        )
        candidates = await self._candidates.generate(
            requirement=requirement,
            problem_graph=graph_result.graph,
            capabilities=capabilities,
        )
        return CompetitiveTextPlanningBundleV3(
            requirement=requirement,
            requirement_receipt=requirement_result.receipt,
            problem_graph=graph_result.graph,
            problem_graph_artifact=graph_result.artifact,
            capabilities=capabilities,
            candidates=candidates,
        )

    def compile_selected(
        self,
        *,
        bundle: CompetitiveTextPlanningBundleV3,
        candidate_id: str,
        plan_version: int = 1,
    ) -> ExecutionPlanVersionV3:
        if (
            bundle.problem_graph is None
            or bundle.problem_graph_artifact is None
            or bundle.capabilities is None
            or bundle.candidates is None
        ):
            raise ValueError("requirement_clarification_required")
        candidate = next(
            (item for item in bundle.candidates.candidates if item.candidate_id == candidate_id),
            None,
        )
        if candidate is None:
            raise ValueError("unknown_candidate")
        request = CandidateCompilationRequestV3(
            requirement=bundle.requirement,
            problem_graph=bundle.problem_graph,
            problem_graph_artifact=bundle.problem_graph_artifact,
            capabilities=bundle.capabilities,
            candidate=candidate,
        )
        return self._compiler.compile_version(
            run_id=bundle.requirement.run_id,
            version=plan_version,
            request=request,
        )
