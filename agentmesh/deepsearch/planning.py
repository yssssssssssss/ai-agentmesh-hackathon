"""Narrow planning interfaces for DeepSearch.

The requirement phase deliberately has no Tool surface.  A production adapter may
call a structured-output model, but it must be wrapped by the DeepSearch budget
meter before the runtime exposes DeepSearch creation.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from agentmesh.artifacts import (
    DeepSearchFrozenPlanNodeV1,
    DeepSearchFrozenPlanV1,
    DeepSearchPlanSnapshotV1,
)
from agentmesh.canonical_json import canonical_json_bytes, canonical_json_sha256
from agentmesh.deepsearch.contracts import (
    ClarificationAnswerValue,
    ProblemGraphV1,
    RequirementRefinementDraftV1,
    RequirementVersionV1,
    canonical_planning_input,
    validate_plan_question_coverage,
    validate_problem_graph_against_requirement,
)
from agentmesh.deepsearch.tool_policy import DEEPSEARCH_V1_TOOL_NAMES
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    Artifact,
    ArtifactVerificationState,
    SkillCandidate,
    SkillDefinition,
    SkillIntent,
    SkillPlan,
    SkillPlanDraft,
    SkillPlanStatus,
    SkillSideEffect,
    ToolDefinition,
    User,
)
from agentmesh.skill_runtime.plan_validation import PlanValidationError, build_plan, validate_draft
from agentmesh.skill_runtime.resources import build_skill_resource_manifest_snapshot
from agentmesh.skill_runtime.retrieval import tool_names_for_profile
from agentmesh.task_routing.contracts import TaskRoutingResult


class RequirementRefiner(Protocol):
    async def refine(
        self,
        *,
        previous: RequirementVersionV1 | None,
        user_request: str,
        answers: dict[str, ClarificationAnswerValue],
    ) -> RequirementRefinementDraftV1:
        """Return content only; lifecycle fields and question IDs remain server-owned."""


class RequirementRefinerUnavailable(RuntimeError):
    """Raised while no budgeted production Requirement refiner is installed."""


class UnavailableRequirementRefiner:
    async def refine(
        self,
        *,
        previous: RequirementVersionV1 | None,
        user_request: str,
        answers: dict[str, ClarificationAnswerValue],
    ) -> RequirementRefinementDraftV1:
        del previous, user_request, answers
        raise RequirementRefinerUnavailable("DeepSearch Requirement refiner is unavailable")


class DeepSearchTaskRouter(Protocol):
    def route(
        self,
        content: str,
        *,
        project_summary: str = "",
        thread_summary: str = "",
    ) -> tuple[TaskRoutingResult, list[str]]: ...


class DeepSearchIntentAnalyzer(Protocol):
    async def analyze(
        self,
        content: str,
        *,
        model: object | None,
        project_summary: str = "",
        thread_summary: str = "",
    ) -> tuple[SkillIntent, list[str]]: ...


class ProblemGraphPlanner(Protocol):
    async def build(
        self,
        *,
        requirement: RequirementVersionV1,
        planning_input: str,
        model: object | None,
    ) -> ProblemGraphV1: ...


class DeepSearchCandidateRetriever(Protocol):
    def retrieve(
        self,
        *,
        user: User,
        requirement: RequirementVersionV1,
        planning_input: str,
        intent: SkillIntent,
        graph: ProblemGraphV1,
        routing_result: TaskRoutingResult,
    ) -> tuple[list[SkillCandidate], list[str]]: ...


class DeepSearchDraftPlanner(Protocol):
    async def create_draft(
        self,
        *,
        requirement: RequirementVersionV1,
        planning_input: str,
        intent: SkillIntent,
        graph: ProblemGraphV1,
        routing_result: TaskRoutingResult,
        candidates: list[SkillCandidate],
        model: object | None,
    ) -> SkillPlanDraft: ...


type ToolDefinitionLookup = Callable[[str], ToolDefinition | None]
type SkillDefinitionLookup = Callable[[str], SkillDefinition | None]


def freeze_deepsearch_plan_resources(
    *,
    plan: SkillPlan,
    candidates: list[SkillCandidate],
    skill_definition_lookup: SkillDefinitionLookup,
) -> SkillPlan:
    """Replace model-owned resource fields with server-built node manifests."""

    candidates_by_id = {candidate.skill_id: candidate for candidate in candidates}
    frozen_nodes = []
    errors: list[str] = []
    for node in plan.nodes:
        candidate = candidates_by_id.get(node.skill_id)
        skill = skill_definition_lookup(node.skill_id)
        if candidate is None or skill is None:
            errors.append("deepsearch_skill_missing")
            continue
        try:
            resource_manifest = build_skill_resource_manifest_snapshot(skill, candidate.profile)
        except ValueError:
            errors.append("deepsearch_resource_unavailable")
            continue
        frozen_nodes.append(node.model_copy(update={"resource_manifest": resource_manifest}))
    if errors:
        raise PlanValidationError(errors)
    return plan.model_copy(update={"nodes": frozen_nodes})


def deepsearch_frozen_plan(plan: SkillPlan) -> DeepSearchFrozenPlanV1:
    """Return the sole immutable projection used by snapshots and Plan hashing."""

    if (
        plan.planning_mode is not AgentPlanningMode.DEEPSEARCH
        or plan.requirement_version_id is None
        or plan.requirement_content_hash is None
        or plan.problem_graph_hash is None
    ):
        raise ValueError("DeepSearch Plan lineage is incomplete")
    node_fields = set(DeepSearchFrozenPlanNodeV1.model_fields)
    return DeepSearchFrozenPlanV1(
        requirement_version_id=plan.requirement_version_id,
        requirement_content_hash=plan.requirement_content_hash,
        problem_graph_hash=plan.problem_graph_hash,
        intent=plan.intent,
        routing_result=plan.routing_result,
        candidate_skill_ids=plan.candidate_skill_ids,
        output_contract=plan.output_contract,
        synthesis_output_contract=plan.synthesis_output_contract,
        capability_gaps=plan.capability_gaps,
        preferred_order=plan.preferred_order,
        nodes=[
            DeepSearchFrozenPlanNodeV1.model_validate(
                node.model_dump(mode="python", include=node_fields)
            )
            for node in plan.nodes
        ],
    )


def plan_content_hash(plan: SkillPlan) -> str:
    """Hash only the immutable DeepSearch Plan projection."""

    return canonical_json_sha256(deepsearch_frozen_plan(plan).model_dump(mode="python"))


def build_deepsearch_plan_snapshot(
    *,
    run: AgentRun,
    plan: SkillPlan,
    created_at: datetime,
) -> Artifact:
    """Build one deterministic sealed Artifact from an authoritative DeepSearch Plan."""

    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("created_at must include a timezone")
    if run.orchestration_version != "v1" or run.planning_mode is not AgentPlanningMode.DEEPSEARCH:
        raise ValueError("Run is not a v1 DeepSearch Run")
    if plan.planning_mode is not AgentPlanningMode.DEEPSEARCH:
        raise ValueError("Plan is not a DeepSearch Plan")
    if plan.run_id != run.id or (run.plan_id is not None and run.plan_id != plan.id):
        raise ValueError("DeepSearch Run and Plan lineage do not match")

    frozen_plan = deepsearch_frozen_plan(plan)
    expected_plan_hash = canonical_json_sha256(frozen_plan.model_dump(mode="python"))
    if plan.plan_content_hash != expected_plan_hash:
        raise ValueError("DeepSearch Plan content hash is invalid")

    snapshot = DeepSearchPlanSnapshotV1(
        schema_version="deepsearch-plan-snapshot-v1",
        run_id=run.id,
        requirement_version_id=frozen_plan.requirement_version_id,
        requirement_content_hash=frozen_plan.requirement_content_hash,
        plan_id=plan.id,
        plan_version=plan.version,
        plan_content_hash=expected_plan_hash,
        frozen_plan=frozen_plan,
    )
    content_bytes = canonical_json_bytes(snapshot.model_dump(mode="python"))
    artifact_id_hash = canonical_json_sha256(
        {
            "kind": "deepsearch_plan_snapshot",
            "run_id": run.id,
            "plan_id": plan.id,
            "plan_version": plan.version,
        }
    )
    return Artifact(
        id=f"artifact_{artifact_id_hash}",
        run_id=run.id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        user_id=run.user_id,
        artifact_type="deepsearch_plan_snapshot",
        content_type="application/json",
        content=content_bytes.decode("utf-8"),
        verification_state=ArtifactVerificationState.SEALED,
        schema_version="deepsearch-plan-snapshot-v1",
        content_hash=canonical_json_sha256(snapshot.model_dump(mode="python")),
        size_bytes=len(content_bytes),
        requirement_version_id=frozen_plan.requirement_version_id,
        plan_version_id=f"{plan.id}:v{plan.version}",
        created_at=created_at,
        updated_at=created_at,
    )


class DeepSearchPlanCompiler:
    """Validate and freeze one generic Skill draft as a DeepSearch Plan."""

    def __init__(
        self,
        *,
        tool_definition_lookup: ToolDefinitionLookup,
        skill_definition_lookup: SkillDefinitionLookup,
    ) -> None:
        self._tool_definition_lookup = tool_definition_lookup
        self._skill_definition_lookup = skill_definition_lookup

    def compile(
        self,
        *,
        run_id: str,
        requirement: RequirementVersionV1,
        graph: ProblemGraphV1,
        intent: SkillIntent,
        routing_result: TaskRoutingResult | None,
        candidates: list[SkillCandidate],
        draft: SkillPlanDraft,
    ) -> SkillPlan:
        if run_id != requirement.run_id:
            raise PlanValidationError(["requirement_run_mismatch"])
        try:
            validate_problem_graph_against_requirement(graph=graph, requirement=requirement)
            validate_plan_question_coverage(graph=graph, nodes=draft.nodes)
        except ValueError as error:
            raise PlanValidationError(["problem_graph_invalid"]) from error

        validate_draft(draft, candidates, intent=intent)
        self._validate_deepsearch_nodes(draft=draft, candidates=candidates)
        plan = build_plan(
            run_id=run_id,
            intent=intent,
            candidates=candidates,
            draft=draft,
            status=SkillPlanStatus.WAITING_APPROVAL,
            routing_result=routing_result,
        ).model_copy(
            update={
                "planning_mode": AgentPlanningMode.DEEPSEARCH,
                "requirement_version_id": requirement.id,
                "requirement_content_hash": requirement.content_hash,
                "problem_graph": graph.model_dump(mode="json"),
                "problem_graph_hash": graph.content_hash,
            }
        )
        plan = freeze_deepsearch_plan_resources(
            plan=plan,
            candidates=candidates,
            skill_definition_lookup=self._skill_definition_lookup,
        )
        plan.plan_content_hash = plan_content_hash(plan)
        return plan

    def _validate_deepsearch_nodes(
        self,
        *,
        draft: SkillPlanDraft,
        candidates: list[SkillCandidate],
    ) -> None:
        errors: list[str] = []
        candidate_by_id = {candidate.skill_id: candidate for candidate in candidates}
        for node in draft.nodes:
            candidate = candidate_by_id.get(node.skill_id)
            if candidate is None:
                continue
            if node.side_effect not in {SkillSideEffect.READ, SkillSideEffect.DRAFT}:
                errors.append("deepsearch_node_side_effect_not_allowed")
            expected_tools = tool_names_for_profile(candidate.profile)
            if not expected_tools.issubset(DEEPSEARCH_V1_TOOL_NAMES):
                errors.append("deepsearch_tool_not_supported")
            if len(node.required_tool_names) != len(set(node.required_tool_names)):
                errors.append("duplicate_required_tool")
            if set(node.required_tool_names) != expected_tools:
                errors.append("required_tool_mismatch")
            for reference in node.required_tool_names:
                tool = self._tool_definition_lookup(reference)
                if tool is None:
                    errors.append("deepsearch_tool_missing")
                    continue
                if reference not in {tool.id, tool.name, tool.external_name}:
                    errors.append("deepsearch_tool_definition_mismatch")
                if tool.name not in DEEPSEARCH_V1_TOOL_NAMES:
                    errors.append("deepsearch_tool_not_supported")
                if not tool.enabled:
                    errors.append("deepsearch_tool_disabled")
                if tool.side_effect != "read":
                    errors.append("deepsearch_tool_not_read_only")
        if errors:
            raise PlanValidationError(errors)


class DeepSearchPlanningPipeline:
    """Compile one complete Requirement into one immutable, reviewable Plan."""

    def __init__(
        self,
        *,
        task_router: DeepSearchTaskRouter,
        intent_analyzer: DeepSearchIntentAnalyzer,
        problem_graph_planner: ProblemGraphPlanner,
        candidate_retriever: DeepSearchCandidateRetriever,
        draft_planner: DeepSearchDraftPlanner,
        compiler: DeepSearchPlanCompiler,
        model: object | None,
    ) -> None:
        self._task_router = task_router
        self._intent_analyzer = intent_analyzer
        self._problem_graph_planner = problem_graph_planner
        self._candidate_retriever = candidate_retriever
        self._draft_planner = draft_planner
        self._compiler = compiler
        self._model = model

    async def create_plan(
        self,
        *,
        run: AgentRun,
        requirement: RequirementVersionV1,
        user: User,
        created_at: datetime,
    ) -> tuple[SkillPlan, Artifact]:
        if (
            run.orchestration_version != "v1"
            or run.planning_mode is not AgentPlanningMode.DEEPSEARCH
            or requirement.run_id != run.id
            or user.id != run.user_id
            or user.workspace_id != run.workspace_id
            or user.default_project_id != run.project_id
        ):
            raise PlanValidationError(["deepsearch_planning_lineage_invalid"])

        planning_input = canonical_planning_input(requirement)
        routing_result, _routing_diagnostics = self._task_router.route(
            planning_input,
            project_summary="",
            thread_summary="",
        )
        routing_result = TaskRoutingResult.model_validate(routing_result)
        intent, _intent_diagnostics = await self._intent_analyzer.analyze(
            planning_input,
            model=self._model,
            project_summary="",
            thread_summary="",
        )
        intent = SkillIntent.model_validate(intent)
        graph = ProblemGraphV1.model_validate(
            await self._problem_graph_planner.build(
                requirement=requirement,
                planning_input=planning_input,
                model=self._model,
            )
        )
        validate_problem_graph_against_requirement(graph=graph, requirement=requirement)
        candidates, _retrieval_diagnostics = self._candidate_retriever.retrieve(
            user=user,
            requirement=requirement,
            planning_input=planning_input,
            intent=intent,
            graph=graph,
            routing_result=routing_result,
        )
        candidates = [
            SkillCandidate.model_validate(candidate.model_dump(mode="python"))
            for candidate in candidates
        ]
        if not candidates:
            raise PlanValidationError(["no_skill_candidates"])
        draft = SkillPlanDraft.model_validate(
            await self._draft_planner.create_draft(
                requirement=requirement,
                planning_input=planning_input,
                intent=intent,
                graph=graph,
                routing_result=routing_result,
                candidates=candidates,
                model=self._model,
            )
        )
        plan = self._compiler.compile(
            run_id=run.id,
            requirement=requirement,
            graph=graph,
            intent=intent,
            routing_result=routing_result,
            candidates=candidates,
            draft=draft,
        )
        snapshot = build_deepsearch_plan_snapshot(
            run=run,
            plan=plan,
            created_at=created_at,
        )
        return plan, snapshot
