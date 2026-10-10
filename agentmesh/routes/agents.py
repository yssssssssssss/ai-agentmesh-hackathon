"""Agent routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from agentmesh.agent_memory_binding import AgentMemoryBindingService
from agentmesh.agent_registry import list_public_agents
from agentmesh.automation.contracts import (
    AutomationStatusV1,
    ProjectInspectionReportV1,
    ScheduledAgentTaskPageV1,
    ScheduledOccurrenceV1,
    ScheduledRunNowRequestV1,
    ScheduledRunPageV1,
)
from agentmesh.automation.occurrences import OccurrenceRepository
from agentmesh.automation.queries import InspectionRunQuery
from agentmesh.automation.schedule_repository import ScheduleDefinitionError, ScheduleRepository
from agentmesh.automation.schedules import ScheduleDefinitionService
from agentmesh.automation.settings import automation_mode
from agentmesh.model_registry import list_enabled_models, set_agent_model
from agentmesh.models import (
    Agent,
    AgentCreateRequest,
    AgentMemoryBinding,
    AgentModelUpdateRequest,
    AgentsResponse,
    AgentToolsUpdateRequest,
    AgentUpdateRequest,
    BlackboardPost,
    BootstrapState,
    CollaborationStage,
    ItemsResponse,
    ModelsResponse,
    O2StatusResponse,
    O2SyncResponse,
    ScheduledAgentTaskCreateRequest,
    ScheduledAgentTaskDefinition,
    ScheduledAgentTaskUpdateRequest,
    ToolsResponse,
    User,
    new_id,
    now_utc,
)
from agentmesh.o2 import O2RegistryAdapter
from agentmesh.permissions import (
    ACTION_MANAGE_PROJECT_TASKS,
    ACTION_MANAGE_PUBLIC_AGENT,
    ACTION_SYNC_O2,
    ensure_can_manage_agent,
    ensure_can_manage_agent_tools,
    ensure_permission,
)
from agentmesh.routes.deps import create_audit_event, current_user, require_permission
from agentmesh.runtime_admission import current_orchestration_admission
from agentmesh.seed import AGENTS, bootstrap_state, list_agents
from agentmesh.store import store
from agentmesh.tools import list_agent_tools, list_enabled_tools, set_agent_tools, sync_o2_tools

router = APIRouter(prefix="/api", tags=["agents"])

o2_registry = O2RegistryAdapter()


def agent_display_name(agent_id: str) -> str:
    agent_item = store.get_agent(agent_id) or next((item for item in AGENTS if item.id == agent_id), None)
    return agent_item.name if agent_item else agent_id


def agent_runtime_id(agent_item: Agent) -> str:
    if agent_item.id == "agent_research":
        return "research_agent"
    if agent_item.id == "agent_data":
        return "data_agent"
    if agent_item.id == "agent_risk":
        return "risk_agent"
    return agent_item.id


def agents_with_runtime_state() -> list[Agent]:
    tasks_by_id = {task.id: task for task in store.tasks}
    posts_by_owner: dict[str, BlackboardPost] = {}
    for post in store.blackboard_posts:
        owner = post.current_owner_agent_id
        if owner:
            posts_by_owner[owner] = post
        if post.execution_lock and post.execution_lock.active:
            posts_by_owner[post.execution_lock.owner_agent_id] = post

    hydrated: list[Agent] = []
    for agent_item in list_agents(store):
        runtime_id = agent_runtime_id(agent_item)
        post = (
            posts_by_owner.get(runtime_id) or posts_by_owner.get(agent_item.id) or posts_by_owner.get(agent_item.name)
        )
        task = tasks_by_id.get(post.task_id) if post else None
        runtime_status = "idle"
        if post is not None:
            if post.execution_lock and post.execution_lock.active:
                runtime_status = "running"
            elif post.collaboration_stage == CollaborationStage.REVIEW:
                runtime_status = "review"
            elif task and task.status == "waiting_external_agent":
                runtime_status = "waiting_approval"
            elif post.collaboration_stage == CollaborationStage.BLOCKED:
                runtime_status = "blocked"
            else:
                runtime_status = "queued"
        hydrated.append(
            agent_item.model_copy(
                update={
                    "runtime_status": runtime_status,
                    "current_task_id": task.id if task else (post.task_id if post else None),
                    "current_task_title": task.title if task else (post.title if post else None),
                    "last_active_at": post.created_at if post else agent_item.updated_at,
                }
            )
        )
    return hydrated


@router.get("/bootstrap", response_model=BootstrapState)
def bootstrap(user: User = Depends(current_user)) -> BootstrapState:
    from agentmesh.routes.chat import agent

    state = bootstrap_state(store, user, agent_runtime=agent.agent_runtime)
    return state.model_copy(update={"agents": agents_with_runtime_state()})


@router.get("/agents", response_model=AgentsResponse)
def agents(_: User = Depends(require_permission(ACTION_MANAGE_PUBLIC_AGENT))) -> AgentsResponse:
    return AgentsResponse(items=agents_with_runtime_state())


@router.get("/agents/public", response_model=ItemsResponse)
def public_agents(_: User = Depends(current_user)) -> ItemsResponse:
    return ItemsResponse(items=list_public_agents(store))


@router.get("/agents/me", response_model=Agent)
def my_agent(user: User = Depends(current_user)) -> Agent:
    found = next(
        (item for item in agents_with_runtime_state() if item.id == user.personal_agent_id),
        None,
    )
    if found is None:
        raise HTTPException(status_code=404, detail="Personal agent not found")
    return found


@router.post("/agents", response_model=Agent)
def create_personal_agent(request: AgentCreateRequest, user: User = Depends(current_user)) -> Agent:
    agent = Agent(
        id=new_id("agent_personal"),
        workspace_id=user.workspace_id,
        name=request.name,
        agent_type="personal",
        description=request.description,
        owner_user_id=user.id,
        capabilities=[item.strip() for item in request.capabilities if item.strip()],
    )
    store.save_agent(agent)
    store.add_audit_event(create_audit_event(user.id, "create_agent", "agent", agent.id, {"agent_type": "personal"}))
    return agent


@router.patch("/agents/{agent_id}", response_model=Agent)
def update_agent(agent_id: str, request: AgentUpdateRequest, user: User = Depends(current_user)) -> Agent:
    found = store.get_agent(agent_id) or next((item for item in AGENTS if item.id == agent_id), None)
    if found is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    ensure_can_manage_agent(user, found, store.permission_policy_rules)
    updated = found.model_copy(deep=True)
    if request.name is not None:
        updated.name = request.name
    if request.description is not None:
        updated.description = request.description
    if request.status is not None:
        updated.status = request.status
    if request.capabilities is not None:
        updated.capabilities = [item.strip() for item in request.capabilities if item.strip()]
    return store.save_agent(updated)


@router.get("/tools", response_model=ToolsResponse)
def tools(_: User = Depends(current_user)) -> ToolsResponse:
    return ToolsResponse(items=list_enabled_tools(store))


@router.get("/models", response_model=ModelsResponse)
def models(_: User = Depends(current_user)) -> ModelsResponse:
    return ModelsResponse(items=list_enabled_models(store))


@router.patch("/agents/{agent_id}/model", response_model=Agent)
def update_agent_model(
    agent_id: str,
    request: AgentModelUpdateRequest,
    user: User = Depends(current_user),
) -> Agent:
    found = store.get_agent(agent_id) or next((item for item in AGENTS if item.id == agent_id), None)
    if found is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    ensure_can_manage_agent(user, found, store.permission_policy_rules)
    try:
        return set_agent_model(store, found, request.model_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/agents/{agent_id}/tools", response_model=ToolsResponse)
def agent_tools_list(agent_id: str, user: User = Depends(current_user)) -> ToolsResponse:
    found = store.get_agent(agent_id) or next((item for item in AGENTS if item.id == agent_id), None)
    if found is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    ensure_can_manage_agent_tools(user, found, store.permission_policy_rules)
    return ToolsResponse(items=list_agent_tools(store, agent_id))


@router.patch("/agents/{agent_id}/tools", response_model=ToolsResponse)
def update_agent_tools(
    agent_id: str,
    request: AgentToolsUpdateRequest,
    user: User = Depends(current_user),
) -> ToolsResponse:
    found = store.get_agent(agent_id) or next((item for item in AGENTS if item.id == agent_id), None)
    if found is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    ensure_can_manage_agent_tools(user, found, store.permission_policy_rules)
    try:
        result = set_agent_tools(store, agent_id, request.tool_ids, user)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return ToolsResponse(items=result)


@router.get("/agents/scheduled-tasks", response_model=ScheduledAgentTaskPageV1)
def scheduled_agent_tasks(
    project_id: str | None = Query(default=None, min_length=1, max_length=120),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    include_unvalidated: bool = Query(default=False),
    user: User = Depends(current_user),
) -> ScheduledAgentTaskPageV1:
    try:
        return ScheduleRepository(store).list_definitions(
            user,
            project_id=project_id,
            page=page,
            page_size=page_size,
            include_unvalidated=include_unvalidated,
        )
    except ScheduleDefinitionError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from error


@router.post("/agents/scheduled-tasks", response_model=ScheduledAgentTaskDefinition)
def create_scheduled_agent_task(
    request: ScheduledAgentTaskCreateRequest,
    user: User = Depends(current_user),
) -> ScheduledAgentTaskDefinition:
    if request.project_id is not None:
        try:
            return ScheduleDefinitionService(store).create(request, user)
        except ScheduleDefinitionError as error:
            raise HTTPException(status_code=error.status_code, detail=error.code) from error
    ensure_permission(user, ACTION_MANAGE_PUBLIC_AGENT, store.permission_policy_rules)
    found = store.get_agent(request.agent_id) or next((item for item in AGENTS if item.id == request.agent_id), None)
    if found is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    definition = ScheduledAgentTaskDefinition(
        agent_id=request.agent_id,
        title=request.title,
        prompt=request.prompt,
        schedule=request.schedule,
        enabled=request.enabled,
        created_by=user.id,
    )
    store.save_scheduled_agent_task_definition(definition)
    store.add_audit_event(
        create_audit_event(user.id, "create_scheduled_agent_task", "scheduled_agent_task", definition.id, {})
    )
    return definition


def _inspection_runtime():
    from agentmesh.routes.chat import agent

    return agent.agent_runtime


@router.get("/agents/scheduled-tasks/status", response_model=AutomationStatusV1)
def schedule_status(request: Request, user: User = Depends(current_user)) -> AutomationStatusV1:
    ensure_permission(user, ACTION_MANAGE_PROJECT_TASKS, store.permission_policy_rules)
    runtime = _inspection_runtime()
    coordinator = getattr(request.app.state, "automation_coordinator", None)
    return AutomationStatusV1(
        mode=automation_mode(),
        runtime_available=bool(runtime and runtime.enabled),
        running=bool(coordinator and coordinator.running),
        last_tick_at=coordinator.last_tick_at if coordinator else None,
        last_error_code=coordinator.last_error_code if coordinator else None,
    )


@router.post("/agents/scheduled-tasks/{definition_id}/run-now", response_model=ScheduledOccurrenceV1)
def run_scheduled_inspection_now(
    definition_id: str,
    request: ScheduledRunNowRequestV1,
    user: User = Depends(current_user),
) -> ScheduledOccurrenceV1:
    runtime = _inspection_runtime()
    try:
        with current_orchestration_admission().permit():
            occurrence = OccurrenceRepository(store).admit(
                definition_id,
                now_utc(),
                runtime_available=bool(runtime and runtime.enabled),
                actor=user,
                manual=request,
            )
    except ScheduleDefinitionError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from error
    if runtime is not None and occurrence.run_id is not None:
        runtime.wake_dispatch_pump()
    return occurrence


@router.get("/agents/scheduled-tasks/{definition_id}/runs", response_model=ScheduledRunPageV1)
def scheduled_inspection_runs(
    definition_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(current_user),
) -> ScheduledRunPageV1:
    try:
        return InspectionRunQuery(store).list_runs(definition_id, user, page=page, page_size=page_size)
    except ScheduleDefinitionError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from error


@router.get("/agents/inspection-runs/{run_id}/report", response_model=ProjectInspectionReportV1)
def scheduled_inspection_report(run_id: str, user: User = Depends(current_user)) -> ProjectInspectionReportV1:
    try:
        return InspectionRunQuery(store).report(run_id, user)
    except ScheduleDefinitionError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from error


@router.patch("/agents/scheduled-tasks/{definition_id}", response_model=ScheduledAgentTaskDefinition)
def update_scheduled_agent_task(
    definition_id: str,
    request: ScheduledAgentTaskUpdateRequest,
    user: User = Depends(current_user),
) -> ScheduledAgentTaskDefinition:
    definition = store.get_scheduled_agent_task_definition(definition_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="Scheduled agent task not found")
    if definition.schema_version is not None or any(
        (
            request.command_id,
            request.expected_version,
            request.project_id,
            request.template_id,
            request.timezone,
        )
    ):
        try:
            return ScheduleDefinitionService(store).update(definition_id, request, user)
        except ScheduleDefinitionError as error:
            raise HTTPException(status_code=error.status_code, detail=error.code) from error
    ensure_permission(user, ACTION_MANAGE_PUBLIC_AGENT, store.permission_policy_rules)
    creator = store.get_user(definition.created_by)
    if creator is None or creator.workspace_id != user.workspace_id:
        raise HTTPException(status_code=404, detail="Scheduled agent task not found")
    if request.title is not None:
        definition.title = request.title
    if request.prompt is not None:
        definition.prompt = request.prompt
    if request.schedule is not None:
        definition.schedule = request.schedule
    if request.enabled is not None:
        definition.enabled = request.enabled
    definition.updated_at = now_utc()
    store.save_scheduled_agent_task_definition(definition)
    store.add_audit_event(
        create_audit_event(user.id, "update_scheduled_agent_task", "scheduled_agent_task", definition.id, {})
    )
    return definition


@router.get("/integrations/o2/status", response_model=O2StatusResponse)
def o2_status(_: User = Depends(require_permission(ACTION_SYNC_O2))) -> O2StatusResponse:
    return O2StatusResponse.model_validate(o2_registry.status())


@router.post("/integrations/o2/sync", response_model=O2SyncResponse)
def sync_o2_tool_registry(
    user: User = Depends(require_permission(ACTION_SYNC_O2)),
) -> O2SyncResponse:
    try:
        synced_tools = sync_o2_tools(store, user)
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    store.add_audit_event(
        create_audit_event(user.id, "sync_o2_tools", "tool_registry", "o2", {"count": len(synced_tools)})
    )
    return O2SyncResponse(items=synced_tools, count=len(synced_tools))


@router.get("/agents/{agent_id}/memory-binding")
def get_agent_memory_binding(agent_id: str, user: User = Depends(current_user)) -> dict[str, object]:
    """Get the memory binding for an agent."""
    binding = AgentMemoryBindingService(store).get(agent_id, user)
    if binding is None:
        return {"binding": None}
    return {"binding": binding.model_dump()}


@router.put("/agents/{agent_id}/memory-binding")
def set_agent_memory_binding(
    agent_id: str,
    request: AgentMemoryBinding,
    user: User = Depends(current_user),
) -> dict[str, object]:
    """Create or update memory binding for an agent."""
    binding = AgentMemoryBindingService(store).set(agent_id, request, user)
    return {"binding": binding.model_dump()}


@router.delete("/agents/{agent_id}/memory-binding")
def delete_agent_memory_binding(
    agent_id: str,
    user: User = Depends(current_user),
) -> dict[str, str]:
    """Remove the binding; ordinary memory authorization still applies."""
    deleted = AgentMemoryBindingService(store).delete(agent_id, user)
    return {"status": "deleted" if deleted else "no_binding"}
