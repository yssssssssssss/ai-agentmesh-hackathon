"""Search, activity, audit, and workspace routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from agentmesh.models import (
    ActivityTodayResponse,
    AuditListResponse,
    Project,
    ProjectCreateRequest,
    Scope,
    SearchResult,
    User,
    Workspace,
    WorkspaceCreateRequest,
    now_utc,
)
from agentmesh.permissions import ACTION_VIEW_AUDIT, ensure_admin
from agentmesh.routes.deps import current_user, require_permission
from agentmesh.seed import WORKSPACE, list_projects, list_workspaces
from agentmesh.store import store

router = APIRouter(prefix="/api", tags=["workspace"])

SEARCH_VISIBILITY_SCOPES: dict[str, set[Scope]] = {
    "personal": {Scope.PRIVATE, Scope.PROJECT, Scope.TEAM_CANDIDATE, Scope.TEAM_ACCEPTED},
    "project": {Scope.PROJECT, Scope.TEAM_CANDIDATE, Scope.TEAM_ACCEPTED},
    "team": {Scope.TEAM_ACCEPTED},
}

def require_read_model_project(user: User, project_id: str) -> Project:
    project = store.get_project(project_id)
    if (
        project is None
        or project.workspace_id != user.workspace_id
        or not store.user_can_access_project(user.id, project_id)
    ):
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/activity/today", response_model=ActivityTodayResponse)
def activity_today(
    project_id: str = Query(min_length=1, max_length=120),
    user: User = Depends(current_user),
) -> ActivityTodayResponse:
    require_read_model_project(user, project_id)
    today = now_utc().date()

    def visible_today(log) -> bool:
        return (
            log.project_id == project_id
            and log.created_at.date() == today
            and store.activity_log_visible_to_user(log, user.id)
        )

    return ActivityTodayResponse(
        personal=[log for log in store.list_personal_activity() if visible_today(log)],
        external=[log for log in store.list_external_activity() if visible_today(log)],
    )


@router.get("/audit", response_model=AuditListResponse)
def audit_events(
    limit: int = Query(default=50, ge=1, le=200),
    action: str | None = Query(default=None, min_length=1, max_length=120),
    target_type: str | None = Query(default=None, min_length=1, max_length=120),
    _: User = Depends(require_permission(ACTION_VIEW_AUDIT)),
) -> AuditListResponse:
    events = list(reversed(store.audit_events))
    if action is not None:
        events = [event for event in events if event.action == action]
    if target_type is not None:
        events = [event for event in events if event.target_type == target_type]
    visible_events = events[:limit]
    counts: dict[str, int] = {}
    for event in events:
        counts[event.action] = counts.get(event.action, 0) + 1
    return AuditListResponse(items=visible_events, total=len(events), limit=limit, counts=counts)

@router.get("/insights/audit", response_model=AuditListResponse)
def insights_audit_events(
    project_id: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=20, ge=1, le=200),
    action: str | None = Query(default=None, min_length=1, max_length=120),
    target_type: str | None = Query(default=None, min_length=1, max_length=120),
    user: User = Depends(current_user),
) -> AuditListResponse:
    require_read_model_project(user, project_id)
    events = [
        event
        for event in reversed(store.audit_events)
        if event.workspace_id == user.workspace_id and event.project_id == project_id
    ]
    if action is not None:
        events = [event for event in events if event.action == action]
    if target_type is not None:
        events = [event for event in events if event.target_type == target_type]
    counts: dict[str, int] = {}
    for event in events:
        counts[event.action] = counts.get(event.action, 0) + 1
    return AuditListResponse(items=events[:limit], total=len(events), limit=limit, counts=counts)


@router.get("/search", response_model=dict[str, list[SearchResult]])
def search_items(
    q: str = Query(min_length=1, max_length=200),
    workspace_id: str | None = None,
    project_id: str | None = None,
    visibility: str = "personal",
    limit: int = Query(default=20, ge=1, le=100),
    max_chars: int = Query(default=8000, ge=100, le=50000),
    user: User = Depends(current_user),
) -> dict[str, list[SearchResult]]:
    allowed_scopes = SEARCH_VISIBILITY_SCOPES.get(visibility)
    if allowed_scopes is None:
        raise HTTPException(status_code=400, detail="Unsupported search visibility")
    resolved_workspace_id = workspace_id or user.workspace_id
    if resolved_workspace_id != WORKSPACE.id or resolved_workspace_id != user.workspace_id:
        raise HTTPException(status_code=404, detail="Workspace not found")

    resolved_project_id = project_id or user.default_project_id
    project = store.get_project(resolved_project_id)
    if (
        project is None
        or project.workspace_id != resolved_workspace_id
        or not store.user_can_access_project(user.id, resolved_project_id)
    ):
        raise HTTPException(status_code=404, detail="Project not found")

    return {
        "items": store.search(
            q,
            allowed_scopes,
            workspace_id=resolved_workspace_id,
            project_id=resolved_project_id,
            user_id=user.id,
            max_results=limit,
            max_chars=max_chars,
        )
    }


@router.get("/workspaces")
def workspaces(_: User = Depends(current_user)) -> dict[str, object]:
    return {"items": list_workspaces(store)}


@router.get("/workspaces/{workspace_id}")
def workspace_detail(workspace_id: str, _: User = Depends(current_user)) -> dict[str, object]:
    workspace = store.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"item": workspace}


@router.post("/workspaces")
def create_workspace(request: WorkspaceCreateRequest, user: User = Depends(current_user)) -> dict[str, object]:
    ensure_admin(user)
    workspace = store.save_workspace(Workspace(name=request.name, description=request.description))
    return {"item": workspace}


@router.get("/projects")
def projects(workspace_id: str | None = None, _: User = Depends(current_user)) -> dict[str, object]:
    return {"items": list_projects(store, workspace_id=workspace_id)}


@router.get("/projects/{project_id}")
def project_detail(project_id: str, _: User = Depends(current_user)) -> dict[str, object]:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"item": project}


@router.post("/projects")
def create_project(request: ProjectCreateRequest, user: User = Depends(current_user)) -> dict[str, object]:
    ensure_admin(user)
    if store.get_workspace(request.workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    project = store.save_project(
        Project(
            workspace_id=request.workspace_id,
            name=request.name,
            goal=request.goal,
            member_ids=[user.id],
        )
    )
    return {"item": project}
