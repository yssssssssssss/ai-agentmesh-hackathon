"""User routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from agentmesh.auth import create_password_hash
from agentmesh.models import (
    Agent,
    AuthCredential,
    ItemResponse,
    ItemsResponse,
    PasswordResetRequest,
    PermissionPoliciesResponse,
    PermissionPolicyRule,
    PermissionPolicyRuleCreateRequest,
    PermissionPolicyRuleUpdateRequest,
    StatusResponse,
    Team,
    TeamCreateRequest,
    TeamMembership,
    TeamMembershipRequest,
    User,
    UserCreateRequest,
    UserItemResponse,
    UsersResponse,
    UserUpdateRequest,
    now_utc,
)
from agentmesh.permissions import (
    ACTION_MANAGE_PERMISSION_POLICIES,
    ACTION_MANAGE_TEAM_MEMBERSHIP,
    ACTION_MANAGE_USERS,
    ACTION_VIEW_PERMISSION_POLICIES,
)
from agentmesh.routes.auth import revoke_user_sessions
from agentmesh.routes.deps import create_audit_event, current_user, require_permission
from agentmesh.seed import PROJECT, WORKSPACE, list_users
from agentmesh.store import store

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=UsersResponse)
def users(_: User = Depends(require_permission(ACTION_MANAGE_USERS))) -> UsersResponse:
    return UsersResponse(items=list_users(store))


@router.post("", response_model=UserItemResponse)
def create_user(
    request: UserCreateRequest,
    user: User = Depends(require_permission(ACTION_MANAGE_USERS)),
) -> UserItemResponse:
    workspace_id = request.workspace_id or WORKSPACE.id
    default_project_id = request.default_project_id or PROJECT.id
    if store.get_workspace(workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    project = store.get_project(default_project_id)
    if project is None or project.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Project not found")

    new_user = User(
        workspace_id=workspace_id,
        default_project_id=default_project_id,
        name=request.name,
        role=request.role,
        personal_agent_id="agent_pending",
    )
    personal_agent = Agent(
        id=f"agent_personal_{new_user.id.removeprefix('usr_')}",
        workspace_id=workspace_id,
        name=f"{request.name}的个人 Agent",
        agent_type="personal",
        description="记录个人上下文、理解用户意图，并在需要时请求服务 Agent。",
        owner_user_id=new_user.id,
        capabilities=["chat", "private_memory", "task_routing"],
    )
    new_user.personal_agent_id = personal_agent.id
    store.save_user(new_user)
    store.save_agent(personal_agent)
    store.save_auth_credential(
        AuthCredential(
            id=new_user.id,
            user_id=new_user.id,
            password_hash=create_password_hash(request.password),
        )
    )
    store.add_audit_event(
        create_audit_event(
            user.id,
            "create_user",
            "user",
            new_user.id,
            {"role": str(new_user.role), "workspace_id": workspace_id},
        )
    )
    return UserItemResponse(item=new_user)


@router.patch("/{user_id}", response_model=UserItemResponse)
def update_user(
    user_id: str,
    request: UserUpdateRequest,
    user: User = Depends(require_permission(ACTION_MANAGE_USERS)),
) -> UserItemResponse:
    target = store.get_user(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    updated = target.model_copy(deep=True)
    if request.name is not None:
        updated.name = request.name
    if request.role is not None:
        updated.role = request.role
    if request.status is not None:
        if request.status not in {"active", "disabled"}:
            raise HTTPException(status_code=400, detail="Unsupported user status")
        updated.status = request.status
        if request.status == "disabled":
            revoke_user_sessions(target.id)
    if request.workspace_id is not None:
        if store.get_workspace(request.workspace_id) is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        updated.workspace_id = request.workspace_id
    if request.default_project_id is not None:
        project = store.get_project(request.default_project_id)
        if project is None or project.workspace_id != updated.workspace_id:
            raise HTTPException(status_code=404, detail="Project not found")
        updated.default_project_id = request.default_project_id
    updated.updated_at = now_utc()
    saved = store.save_user(updated)
    store.add_audit_event(
        create_audit_event(
            user.id,
            "update_user",
            "user",
            saved.id,
            {"role": str(saved.role), "status": saved.status},
        )
    )
    return UserItemResponse(item=saved)


@router.post("/{user_id}/password", response_model=StatusResponse)
def reset_user_password(
    user_id: str,
    request: PasswordResetRequest,
    user: User = Depends(require_permission(ACTION_MANAGE_USERS)),
) -> StatusResponse:
    target = store.get_user(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    credential = store.get_auth_credential(user_id)
    if credential is None:
        credential = AuthCredential(
            id=user_id, user_id=user_id, password_hash=create_password_hash(request.new_password)
        )
    else:
        credential.password_hash = create_password_hash(request.new_password)
        credential.updated_at = now_utc()
    store.save_auth_credential(credential)
    revoked = revoke_user_sessions(user_id)
    store.add_audit_event(create_audit_event(user.id, "reset_password", "user", user_id, {"revoked_sessions": revoked}))
    return StatusResponse(status="ok")


@router.get("/permission-policies", response_model=PermissionPoliciesResponse)
def permission_policies(
    _: User = Depends(require_permission(ACTION_VIEW_PERMISSION_POLICIES)),
) -> PermissionPoliciesResponse:
    return PermissionPoliciesResponse(items=store.permission_policy_rules)


@router.post("/permission-policies", response_model=ItemResponse)
def create_permission_policy(
    request: PermissionPolicyRuleCreateRequest,
    user: User = Depends(require_permission(ACTION_MANAGE_PERMISSION_POLICIES)),
) -> ItemResponse:
    rule = store.save_permission_policy_rule(
        PermissionPolicyRule(
            role=request.role,
            action=request.action,
            effect=request.effect,
            enabled=request.enabled,
            description=request.description,
        )
    )
    store.add_audit_event(
        create_audit_event(user.id, "create_permission_policy", "permission_policy_rule", rule.id, {})
    )
    return ItemResponse(item=rule)


@router.patch("/permission-policies/{rule_id}", response_model=ItemResponse)
def update_permission_policy(
    rule_id: str,
    request: PermissionPolicyRuleUpdateRequest,
    user: User = Depends(require_permission(ACTION_MANAGE_PERMISSION_POLICIES)),
) -> ItemResponse:
    rule = store.get_permission_policy_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Permission policy rule not found")
    updated = rule.model_copy(deep=True)
    if request.role is not None:
        updated.role = request.role
    if request.action is not None:
        updated.action = request.action
    if request.effect is not None:
        updated.effect = request.effect
    if request.enabled is not None:
        updated.enabled = request.enabled
    if request.description is not None:
        updated.description = request.description
    updated.updated_at = now_utc()
    saved = store.save_permission_policy_rule(updated)
    store.add_audit_event(
        create_audit_event(
            user.id,
            "update_permission_policy",
            "permission_policy_rule",
            saved.id,
            {"enabled": saved.enabled, "effect": saved.effect},
        )
    )
    return ItemResponse(item=saved)


@router.get("/teams", response_model=ItemsResponse)
def teams(_: User = Depends(current_user)) -> ItemsResponse:
    return ItemsResponse(items=store.list_teams())


@router.post("/teams", response_model=ItemResponse)
def create_team(
    request: TeamCreateRequest,
    user: User = Depends(require_permission(ACTION_MANAGE_TEAM_MEMBERSHIP)),
) -> ItemResponse:
    workspace_id = request.workspace_id or WORKSPACE.id
    if store.get_workspace(workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    team = store.save_team(Team(workspace_id=workspace_id, name=request.name, description=request.description))
    store.add_audit_event(create_audit_event(user.id, "create_team", "team", team.id, {"workspace_id": workspace_id}))
    return ItemResponse(item=team)


@router.get("/teams/{team_id}", response_model=ItemResponse)
def team_detail(team_id: str, _: User = Depends(current_user)) -> ItemResponse:
    team = store.get_team(team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    memberships = store.list_team_memberships(team_id=team.id)
    members = []
    for membership in memberships:
        member = store.get_user(membership.user_id)
        if member is None:
            continue
        members.append({"membership": membership, "user": member})
    return ItemResponse(item={"team": team, "members": members})


@router.post("/teams/{team_id}/members", response_model=ItemResponse)
def add_team_member(
    team_id: str,
    request: TeamMembershipRequest,
    user: User = Depends(require_permission(ACTION_MANAGE_TEAM_MEMBERSHIP)),
) -> ItemResponse:
    team = store.get_team(team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    member = store.get_user(request.user_id)
    if member is None:
        raise HTTPException(status_code=404, detail="User not found")
    existing = store.list_team_memberships(team_id=team_id, user_id=request.user_id)
    if existing:
        membership = existing[0]
        membership.role = request.role
        membership.updated_at = now_utc()
    else:
        membership = TeamMembership(team_id=team_id, user_id=request.user_id, role=request.role)
    store.save_team_membership(membership)
    store.add_audit_event(
        create_audit_event(user.id, "upsert_team_membership", "team_membership", membership.id, {"team_id": team_id, "user_id": request.user_id})
    )
    return ItemResponse(item=membership)


@router.delete("/teams/{team_id}/members/{user_id}", response_model=StatusResponse)
def remove_team_member(
    team_id: str,
    user_id: str,
    user: User = Depends(require_permission(ACTION_MANAGE_TEAM_MEMBERSHIP)),
) -> StatusResponse:
    memberships = store.list_team_memberships(team_id=team_id, user_id=user_id)
    if not memberships:
        raise HTTPException(status_code=404, detail="Team membership not found")
    removed = store.remove_team_membership(memberships[0].id)
    if not removed:
        raise HTTPException(status_code=404, detail="Team membership not found")
    store.add_audit_event(
        create_audit_event(user.id, "remove_team_membership", "team_membership", memberships[0].id, {"team_id": team_id, "user_id": user_id})
    )
    return StatusResponse(status="ok")
