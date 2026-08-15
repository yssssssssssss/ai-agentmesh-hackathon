from __future__ import annotations

from fastapi import HTTPException, status

from agentmesh.models import (
    Agent,
    BlackboardPost,
    MemoryItem,
    MemoryStatus,
    PermissionPolicyRule,
    Scope,
    User,
    UserRole,
)

ACTION_ACCEPT_TEAM_MEMORY = "accept_team_memory"
ACTION_MANAGE_PERMISSION_POLICIES = "manage_permission_policies"
ACTION_MANAGE_PUBLIC_AGENT = "manage_public_agent"
ACTION_MANAGE_TEAM_MEMBERSHIP = "manage_team_membership"
ACTION_MANAGE_USERS = "manage_users"
ACTION_MANAGE_RISK_POLICIES = "manage_risk_policies"
ACTION_SYNC_O2 = "sync_o2"
ACTION_VIEW_AUDIT = "view_audit"
ACTION_VIEW_PERMISSION_POLICIES = "view_permission_policies"
ACTION_VIEW_PROVIDER_HEALTH = "view_provider_health"

DEFAULT_ROLE_POLICIES: dict[UserRole, set[str]] = {
    UserRole.USER: set(),
    UserRole.TEAM_LEAD: {
        ACTION_ACCEPT_TEAM_MEMORY,
        ACTION_MANAGE_PUBLIC_AGENT,
    },
    UserRole.ADMIN: {
        ACTION_ACCEPT_TEAM_MEMORY,
        ACTION_MANAGE_PUBLIC_AGENT,
        ACTION_MANAGE_TEAM_MEMBERSHIP,
    },
}


def is_admin(user: User) -> bool:
    return user.role == UserRole.ADMIN


def is_team_lead(user: User) -> bool:
    return user.role == UserRole.TEAM_LEAD


def ensure_admin(user: User) -> None:
    if is_admin(user):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin permission required")


def has_permission(user: User, action: str, rules: list[PermissionPolicyRule] | None = None) -> bool:
    role = UserRole(user.role)
    if role == UserRole.ADMIN:
        return True
    decision = action in DEFAULT_ROLE_POLICIES.get(role, set())
    for rule in rules or []:
        if not rule.enabled or rule.role != role or rule.action != action:
            continue
        decision = rule.effect == "allow"
    return decision

def capabilities_for_user(user: User, rules: list[PermissionPolicyRule] | None = None) -> list[str]:
    """Return the effective capability names the frontend may expose."""

    role = UserRole(user.role)
    actions = set(DEFAULT_ROLE_POLICIES.get(role, set()))
    actions.update(rule.action for rule in rules or [] if rule.role == role)
    if is_admin(user):
        actions.update(
            {
                ACTION_MANAGE_PERMISSION_POLICIES,
                ACTION_MANAGE_USERS,
                ACTION_MANAGE_RISK_POLICIES,
                ACTION_SYNC_O2,
                ACTION_VIEW_AUDIT,
                ACTION_VIEW_PERMISSION_POLICIES,
                ACTION_VIEW_PROVIDER_HEALTH,
            }
        )
    return sorted(action for action in actions if has_permission(user, action, rules))


def ensure_permission(user: User, action: str, rules: list[PermissionPolicyRule] | None = None) -> None:
    if has_permission(user, action, rules):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Permission denied: {action}")


def ensure_can_manage_agent(
    user: User,
    agent: Agent,
    rules: list[PermissionPolicyRule] | None = None,
) -> None:
    if is_admin(user):
        return
    if agent.agent_type == "personal" and agent.owner_user_id == user.id:
        return
    if agent.agent_type != "personal" and has_permission(user, ACTION_MANAGE_PUBLIC_AGENT, rules):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to manage this agent")


def ensure_can_manage_agent_tools(
    user: User,
    agent: Agent,
    rules: list[PermissionPolicyRule] | None = None,
) -> None:
    ensure_can_manage_agent(user, agent, rules)


def ensure_can_update_memory(
    user: User,
    item: MemoryItem,
    status_value: MemoryStatus | None,
    scope: Scope | None,
    rules: list[PermissionPolicyRule] | None = None,
) -> None:
    if item.owner_user_id != user.id and item.scope == Scope.PRIVATE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory item not found")
    if (
        item.owner_user_id != user.id
        and item.scope == Scope.TEAM_CANDIDATE
        and user.role == UserRole.USER
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory item not found")
    accepts_team_memory = status_value == MemoryStatus.ACCEPTED or scope == Scope.TEAM_ACCEPTED
    if accepts_team_memory:
        if item.status != MemoryStatus.PROPOSED or item.scope != Scope.TEAM_CANDIDATE:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Memory is not an open team candidate")
        if status_value not in {None, MemoryStatus.ACCEPTED} or scope not in {None, Scope.TEAM_ACCEPTED}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid team memory acceptance")
        if has_permission(user, ACTION_ACCEPT_TEAM_MEMORY, rules):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to accept team memory")

    if item.owner_user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to update shared memory")
    if item.scope != Scope.PRIVATE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to update shared memory")
    if scope not in {None, Scope.PRIVATE} or status_value != MemoryStatus.DISPUTED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Memory transition is not available")


def can_control_blackboard_task(
    user: User,
    post: BlackboardPost,
    task_initiator_user_id: str | None,
) -> bool:
    return (
        user.role in {UserRole.TEAM_LEAD, UserRole.ADMIN}
        or task_initiator_user_id == user.id
        or post.current_owner_agent_id == user.personal_agent_id
    )


def authorize_blackboard_action(
    user: User,
    post: BlackboardPost,
    action: str,
    *,
    visible: bool,
    task_initiator_user_id: str | None,
) -> None:
    if not visible:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Blackboard post not found")
    if action == "read":
        return
    if can_control_blackboard_task(user, post, task_initiator_user_id):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Not allowed to {action} this task")


def ensure_can_release_execution_lock(user: User, post: BlackboardPost) -> None:
    lock = post.execution_lock
    if lock is None or not lock.active:
        return
    if user.role in {UserRole.TEAM_LEAD, UserRole.ADMIN}:
        return
    if lock.owner_agent_id == user.personal_agent_id:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to release this lock")


def default_permission_policy_rules() -> list[PermissionPolicyRule]:
    return [
        PermissionPolicyRule(
            id="perm_team_lead_accept_team_memory",
            role=UserRole.TEAM_LEAD,
            action=ACTION_ACCEPT_TEAM_MEMORY,
            effect="allow",
            description="组长可以审核并接受团队候选记忆。",
        ),
        PermissionPolicyRule(
            id="perm_team_lead_manage_public_agent",
            role=UserRole.TEAM_LEAD,
            action=ACTION_MANAGE_PUBLIC_AGENT,
            effect="allow",
            description="组长可以调整公共 Agent 的基础配置。",
        ),
        PermissionPolicyRule(
            id="perm_admin_manage_team_membership",
            role=UserRole.ADMIN,
            action=ACTION_MANAGE_TEAM_MEMBERSHIP,
            effect="allow",
            description="管理员可以维护团队和成员关系。",
        ),
    ]


def ensure_permission_policy_seed_data(repository) -> None:
    existing_ids = {rule.id for rule in repository.permission_policy_rules}
    for rule in default_permission_policy_rules():
        if rule.id not in existing_ids:
            repository.save_permission_policy_rule(rule)
