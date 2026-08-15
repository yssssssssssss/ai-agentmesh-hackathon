"""Agent routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from agentmesh.agent_registry import list_public_agents
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
    ACTION_MANAGE_PUBLIC_AGENT,
    ACTION_SYNC_O2,
    ensure_can_manage_agent,
    ensure_can_manage_agent_tools,
)
from agentmesh.routes.deps import create_audit_event, current_user, require_permission
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
    state = bootstrap_state(store, user)
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


@router.get("/agents/scheduled-tasks", response_model=ItemsResponse)
def scheduled_agent_tasks(
    _: User = Depends(require_permission(ACTION_MANAGE_PUBLIC_AGENT)),
) -> ItemsResponse:
    return ItemsResponse(items=list(reversed(store.scheduled_agent_task_definitions)))


@router.post("/agents/scheduled-tasks", response_model=ScheduledAgentTaskDefinition)
def create_scheduled_agent_task(
    request: ScheduledAgentTaskCreateRequest,
    user: User = Depends(require_permission(ACTION_MANAGE_PUBLIC_AGENT)),
) -> ScheduledAgentTaskDefinition:
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


@router.patch("/agents/scheduled-tasks/{definition_id}", response_model=ScheduledAgentTaskDefinition)
def update_scheduled_agent_task(
    definition_id: str,
    request: ScheduledAgentTaskUpdateRequest,
    user: User = Depends(require_permission(ACTION_MANAGE_PUBLIC_AGENT)),
) -> ScheduledAgentTaskDefinition:
    definition = store.get_scheduled_agent_task_definition(definition_id)
    if definition is None:
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
def get_agent_memory_binding(agent_id: str, _: User = Depends(current_user)) -> dict[str, object]:
    """Get the memory binding for an agent."""
    binding = store.get_binding_for_agent(agent_id)
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
    agent = store.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    ensure_can_manage_agent(user, agent, store.permission_policy_rules)
    existing = store.get_binding_for_agent(agent_id)
    if existing:
        existing.allowed_scopes = request.allowed_scopes
        existing.allowed_memory_types = request.allowed_memory_types
        existing.allowed_project_ids = request.allowed_project_ids
        existing.max_results_per_query = request.max_results_per_query
        existing.updated_at = now_utc()
        store.save_agent_memory_binding(existing)
        return {"binding": existing.model_dump()}
    request.agent_id = agent_id
    binding = store.add_agent_memory_binding(request)
    return {"binding": binding.model_dump()}


@router.delete("/agents/{agent_id}/memory-binding")
def delete_agent_memory_binding(
    agent_id: str,
    user: User = Depends(current_user),
) -> dict[str, str]:
    """Remove memory binding (agent reverts to full access)."""
    agent = store.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    ensure_can_manage_agent(user, agent, store.permission_policy_rules)
    existing = store.get_binding_for_agent(agent_id)
    if existing is None:
        return {"status": "no_binding"}
    with store._connect() as connection:
        connection.execute(
            "DELETE FROM records WHERE collection = ? AND id = ?",
            ("agent_memory_bindings", existing.id),
        )
    return {"status": "deleted"}
