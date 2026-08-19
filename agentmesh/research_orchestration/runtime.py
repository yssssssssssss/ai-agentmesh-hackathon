"""Production composition root for research-v2 workflows."""

from __future__ import annotations

from datetime import timedelta

from agentmesh.agent_runtime.model_factory import AgentMeshModelFactory
from agentmesh.agent_runtime.settings import SkillOrchestrationMode
from agentmesh.models import (
    AgentRun,
    AgentRunStatus,
    ChatMessage,
    ChatRole,
    Scope,
    SkillDefinition,
    SkillOrchestrationRequestMode,
    User,
    now_utc,
)
from agentmesh.research_orchestration.api import ResearchRevisePlanRequest
from agentmesh.research_orchestration.artifacts import ArtifactStore
from agentmesh.research_orchestration.capabilities import CompetitiveCapabilityResolver
from agentmesh.research_orchestration.compiler import CompetitivePlanCompiler, PlanCompileError
from agentmesh.research_orchestration.contracts import ExecutionPlanVersion, RequirementVersion
from agentmesh.research_orchestration.planning import (
    CompetitiveRequirementPlanner,
    is_competitive_research_request,
    requirement_version_from_result,
)
from agentmesh.research_orchestration.resource_snapshot import ResourceSnapshotFactory
from agentmesh.research_orchestration.workflow import ResearchWorkflowService
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore
from agentmesh.tool_runtime.gateway import ToolGateway

_COMPETITIVE_RESOURCE_PATHS = ("methods/toolbox/analysis/competitive-analysis.md",)


class CompetitiveResearchPlanning:
    """Turn one competitive request into a persisted requirement and frozen plan."""

    def __init__(
        self,
        repository: SQLiteStore,
        catalog: SkillCatalogService,
        artifacts: ArtifactStore,
        tool_gateway: ToolGateway,
        *,
        requirement_planner: CompetitiveRequirementPlanner | None = None,
        plan_compiler: CompetitivePlanCompiler | None = None,
        model_factory: AgentMeshModelFactory | None = None,
    ):
        if artifacts.repository is not repository or catalog.repository is not repository:
            raise ValueError("research planning dependencies must share one repository")
        if tool_gateway.repository is not repository:
            raise ValueError("research Tool gateway must share the workflow repository")
        self.repository = repository
        self.catalog = catalog
        self.requirement_planner = requirement_planner or CompetitiveRequirementPlanner()
        self.plan_compiler = plan_compiler or CompetitivePlanCompiler()
        self.model_factory = model_factory or AgentMeshModelFactory(repository)
        self.resource_snapshots = ResourceSnapshotFactory(repository, artifacts)
        self.capabilities = CompetitiveCapabilityResolver(
            repository,
            catalog,
            tool_gateway,
            self.model_factory,
        )

    async def prepare_requirement(
        self,
        run: AgentRun,
        *,
        version: int,
        clarification_answers: dict[str, str] | None = None,
        revision: ResearchRevisePlanRequest | None = None,
    ) -> RequirementVersion:
        answers = dict(clarification_answers or {})
        raw_input = run.input_text
        if revision is not None:
            if revision.research_goal is not None:
                raw_input = revision.research_goal
            if revision.competitor_scope is not None:
                answers["clarify_competitor_scope"] = revision.competitor_scope

        selected = None
        user = self.repository.get_user(run.user_id)
        if user is not None:
            try:
                selected = self.model_factory.for_user(user)
            except ValueError:
                selected = None
        result = await self.requirement_planner.plan(
            raw_input,
            explicit_skill_name="competitive-analysis",
            clarification_answers=answers,
            model=selected.model if selected is not None else None,
        )
        return requirement_version_from_result(run.id, version, result)

    def compile_plan(
        self,
        run: AgentRun,
        requirement: RequirementVersion,
        *,
        version: int,
    ) -> ExecutionPlanVersion:
        skill = self.catalog.get_by_name("competitive-analysis")
        if skill is None:
            raise PlanCompileError("skill_not_eligible")
        resource_snapshot = self.resource_snapshots.create(
            run=run,
            requirement=requirement,
            skill=skill,
            relative_paths=list(_COMPETITIVE_RESOURCE_PATHS),
        )
        capability_snapshot = self.capabilities.resolve(
            run_id=run.id,
            user_id=run.user_id,
            resource_snapshot=resource_snapshot,
        )
        return self.plan_compiler.compile(
            requirement,
            capability_snapshot,
            plan_version=version,
            now=capability_snapshot.resolved_at,
        )


class _PreviewOnlyExecution:
    async def claim_and_run(self, attempt_id: str, *, token: str | None = None) -> object:
        del attempt_id, token
        raise RuntimeError("research_execution_not_enabled")


class ResearchRuntime:
    """Own process-local research services while SQLite remains authoritative."""

    def __init__(
        self,
        repository: SQLiteStore,
        workflow_service: ResearchWorkflowService,
        *,
        execution_enabled: bool = False,
    ):
        if workflow_service.repository is not repository:
            raise ValueError("ResearchRuntime dependencies must share one repository")
        self.repository = repository
        self.workflow_service = workflow_service
        self.execution_enabled = execution_enabled
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    async def start(self) -> None:
        self._started = True

    async def shutdown(self) -> None:
        self._started = False
        await self.workflow_service.wait_for_idle()

    async def start_run(
        self,
        *,
        content: str,
        user: User,
        thread_id: str,
        client_turn_id: str,
        mode: SkillOrchestrationMode,
        requested_orchestration_mode: SkillOrchestrationRequestMode,
        explicit_skill: SkillDefinition | None = None,
    ) -> AgentRun:
        if not self._started:
            raise RuntimeError("Research Runtime is unavailable")
        if mode == SkillOrchestrationMode.OFF:
            raise RuntimeError("Research orchestration is disabled")
        explicit_name = explicit_skill.name if explicit_skill is not None else None
        if not is_competitive_research_request(content, explicit_skill_name=explicit_name):
            raise RuntimeError("Request is not eligible for research-v2")

        # Slice 1 is preview-only. Keeping the persisted mode honest prevents a
        # manually forged execute command from crossing the unfinished gate.
        effective_mode = mode if self.execution_enabled else SkillOrchestrationMode.PREVIEW
        run = AgentRun(
            thread_id=thread_id,
            user_id=user.id,
            workspace_id=user.workspace_id,
            project_id=user.default_project_id,
            input_text=content,
            client_turn_id=client_turn_id,
            status=AgentRunStatus.PLANNING,
            skill_id=explicit_skill.id if explicit_skill is not None else None,
            skill_name=explicit_name,
            orchestration_version="research-v2",
            orchestration_mode=effective_mode.value,
            requested_orchestration_mode=requested_orchestration_mode,
            project_chat=True,
            deadline_at=now_utc() + timedelta(minutes=5),
        )
        if not await self.workflow_service.start_if_applicable(run):
            raise RuntimeError("Research workflow was not started")
        stored = self.repository.get_agent_run(run.id)
        if stored is None:
            raise RuntimeError("Research workflow did not persist its Agent run")
        self.repository.add_chat_message(
            ChatMessage(
                thread_id=thread_id,
                role=ChatRole.USER,
                content=content,
                scope=Scope.PRIVATE,
            )
        )
        return stored


def build_research_runtime(
    repository: SQLiteStore,
    catalog: SkillCatalogService,
) -> ResearchRuntime:
    """Assemble the production Web Preview runtime without execution side effects."""

    artifacts = ArtifactStore(repository)
    tool_gateway = ToolGateway(repository)
    model_factory = AgentMeshModelFactory(repository)
    planning = CompetitiveResearchPlanning(
        repository,
        catalog,
        artifacts,
        tool_gateway,
        model_factory=model_factory,
    )
    service = ResearchWorkflowService(
        repository,
        planning,
        _PreviewOnlyExecution(),
        artifacts,
    )
    return ResearchRuntime(repository, service, execution_enabled=False)
