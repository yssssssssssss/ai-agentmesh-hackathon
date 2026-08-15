"""Shared dependencies for route modules."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Request

from agentmesh.auth import require_current_user
from agentmesh.model_registry import ensure_model_seed_data
from agentmesh.models import AuditEvent, User
from agentmesh.permissions import ensure_permission, ensure_permission_policy_seed_data
from agentmesh.risk import RiskDecision, ensure_risk_policy_seed_data
from agentmesh.seed import ensure_seed_data
from agentmesh.store import store
from agentmesh.tools import ensure_tool_seed_data


def current_user(request: Request) -> User:
    ensure_seed_data(store)
    ensure_tool_seed_data(store, granted_by="system")
    ensure_model_seed_data(store)
    ensure_risk_policy_seed_data(store)
    ensure_permission_policy_seed_data(store)
    return require_current_user(store, request)

def require_permission(action: str) -> Callable[..., User]:
    def dependency(user: User = Depends(current_user)) -> User:
        ensure_permission(user, action, store.permission_policy_rules)
        return user

    return dependency


def create_audit_event(actor: str, action: str, target_type: str, target_id: str, metadata: dict[str, object]):
    workspace_id: str | None = None
    project_id: str | None = None
    target = None
    if target_type == "task":
        target = store.get_task(target_id)
    elif target_type == "blackboard_post":
        post = store.get_blackboard_post(target_id)
        target = store.get_task(post.task_id) if post is not None else None
    elif target_type == "inbox_item":
        target = store.get_inbox_item(target_id)
    elif target_type == "document":
        target = store.get_document(target_id)
    elif target_type == "memory_item":
        target = store.get_memory_item(target_id)
    elif target_type == "user_memory_item":
        target = store.get_user_memory_item(target_id)

    thread_id = getattr(target, "thread_id", None)
    if thread_id is not None:
        target = store.get_chat_thread(thread_id)
    workspace_id = getattr(target, "workspace_id", None)
    project_id = getattr(target, "project_id", None)
    if workspace_id is None and isinstance(metadata.get("workspace_id"), str):
        workspace_id = metadata["workspace_id"]
    if project_id is None and isinstance(metadata.get("project_id"), str):
        project_id = metadata["project_id"]
    return AuditEvent(
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        workspace_id=workspace_id,
        project_id=project_id,
        metadata=metadata,
    )


def validate_risk_decision(value: str) -> str:
    from fastapi import HTTPException

    if value not in {item.value for item in RiskDecision}:
        raise HTTPException(status_code=400, detail="Unsupported risk decision")
    return value
