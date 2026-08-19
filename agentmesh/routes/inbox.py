"""Inbox routes."""

from __future__ import annotations

import json
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException

from agentmesh.models import (
    BriefConfirmRequest,
    ChatMessage,
    ChatRole,
    ChatWorkflowTrace,
    InboxItem,
    InboxItemsResponse,
    InboxItemView,
    InboxUpdateRequest,
    Intent,
    ItemResponse,
    Scope,
    User,
    UserRole,
    now_utc,
)
from agentmesh.routes.deps import create_audit_event, current_user
from agentmesh.store import BriefConfirmationError, store

router = APIRouter(prefix="/api/inbox", tags=["inbox"])


def is_active_inbox_item(item: InboxItem, now) -> bool:
    if item.status == "resolved":
        return False
    if item.status == "snoozed" and item.snooze_until is not None:
        return item.snooze_until <= now
    return True


def inbox_item_view(item: InboxItem) -> InboxItemView:
    actions: list[str] = []
    if item.status != "resolved":
        if item.status != "snoozed":
            actions.append("snooze")
        if item.item_type == "prompt_injection_review":
            if item.status == "open":
                actions.extend(("release", "discard"))
        elif is_brief_confirmation(item):
            if item.status == "open":
                actions.append("confirm_brief")
        elif item.item_type == "sdk_tool_approval":
            if item.status == "open":
                actions.extend(("approve_tool", "reject_tool"))
        else:
            actions.append("resolve")
    return InboxItemView(**item.model_dump(), allowed_actions=actions)


@router.get("", response_model=InboxItemsResponse)
def inbox_items(
    include_snoozed: bool = False,
    user: User = Depends(current_user),
) -> InboxItemsResponse:
    now = now_utc()
    items = [item for item in reversed(store.inbox_items) if inbox_visible_to_user(item, user)]
    if not include_snoozed:
        items = [item for item in items if is_active_inbox_item(item, now)]
    return InboxItemsResponse(items=[inbox_item_view(item) for item in items])


@router.patch("/{item_id}", response_model=ItemResponse)
def update_inbox_item(
    item_id: str,
    request: InboxUpdateRequest,
    user: User = Depends(current_user),
) -> ItemResponse:
    item = store.get_inbox_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Inbox item not found")
    if not inbox_visible_to_user(item, user):
        raise HTTPException(status_code=403, detail="Not allowed to update this inbox item")
    if requires_dedicated_transition(item) and (request.status == "resolved" or item.status == "resolved"):
        raise HTTPException(status_code=409, detail="Inbox item requires its dedicated governance transition")
    if request.ttl_minutes is not None and request.snooze_until is not None:
        raise HTTPException(status_code=400, detail="Use ttl_minutes or snooze_until, not both")
    next_status = request.status or item.status
    if next_status not in {"open", "snoozed", "resolved"}:
        raise HTTPException(status_code=400, detail="Unsupported inbox status")

    now = now_utc()
    item.status = next_status
    item.updated_at = now
    if next_status == "resolved":
        item.resolved_at = now
        item.acknowledged_at = item.acknowledged_at or now
        item.snooze_until = None
    elif next_status == "snoozed":
        snooze_until = request.snooze_until or (
            now + timedelta(minutes=request.ttl_minutes) if request.ttl_minutes is not None else None
        )
        if snooze_until is None or snooze_until <= now:
            raise HTTPException(status_code=400, detail="snooze_until must be in the future")
        item.acknowledged_at = now
        item.snooze_until = snooze_until
        item.resolved_at = None
    else:
        item.snooze_until = None
        item.resolved_at = None
    store.save_inbox_item(item)
    store.add_audit_event(
        create_audit_event(user.id, "update_inbox_item", "inbox_item", item.id, {"status": item.status})
    )
    return ItemResponse(item=item)


@router.post("/{item_id}/confirm-brief")
def confirm_brief_item(
    item_id: str,
    request: BriefConfirmRequest,
    user: User = Depends(current_user),
) -> dict[str, object]:
    try:
        result = store.confirm_brief(
            item_id=item_id,
            owner_user_id=user.id,
            text=request.text,
            expected_document_version=request.expected_document_version,
        )
    except BriefConfirmationError as error:
        status_code = {
            "not_found": 404,
            "forbidden": 403,
            "invalid": 400,
            "conflict": 409,
        }.get(error.code, 409)
        raise HTTPException(status_code=status_code, detail=error.detail) from error
    return {
        "item": result.inbox_item,
        "document": result.document,
        "memory_item": result.memory_item,
    }


@router.post("/{item_id}/resolve-injection-review")
def resolve_injection_review_item(
    item_id: str,
    action: str,
    user: User = Depends(current_user),
) -> dict[str, object]:
    from agentmesh.agents import RequestAlreadyFulfilledError
    from agentmesh.routes.chat import agent

    item = store.get_inbox_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Inbox item not found")
    if not inbox_visible_to_user(item, user):
        raise HTTPException(status_code=403, detail="Not allowed to update this inbox item")
    if item.item_type != "prompt_injection_review":
        raise HTTPException(status_code=400, detail="Inbox item is not a prompt-injection review")
    if action not in {"release", "discard"}:
        raise HTTPException(status_code=400, detail="action must be 'release' or 'discard'")
    if item.status != "open":
        raise HTTPException(status_code=409, detail="Prompt-injection review is no longer open")
    request_post_id = item.metadata.get("request_post_id")
    evidence_post_id = item.metadata.get("evidence_post_id")
    if not request_post_id or not evidence_post_id:
        raise HTTPException(status_code=400, detail="Inbox item is missing quarantine references")
    request_post = store.get_blackboard_post(request_post_id)
    evidence_post = store.get_blackboard_post(evidence_post_id)
    if request_post is None or evidence_post is None:
        raise HTTPException(status_code=404, detail="Quarantined blackboard posts not found")

    try:
        fulfillment = agent.resolve_quarantined_research(request_post, evidence_post, user, action)
    except RequestAlreadyFulfilledError as error:
        raise HTTPException(status_code=409, detail="Quarantined evidence has already been resolved") from error

    now = now_utc()
    item.status = "resolved"
    item.acknowledged_at = item.acknowledged_at or now
    item.resolved_at = now
    item.updated_at = now
    item.metadata["injection_review_action"] = action
    store.save_inbox_item(item)
    store.add_audit_event(
        create_audit_event(
            user.id,
            "resolve_injection_review",
            "inbox_item",
            item.id,
            {
                "action": action,
                "request_post_id": request_post.id,
                "evidence_post_id": evidence_post.id,
                "task_id": fulfillment.task.id,
            },
        )
    )
    return {
        "item": item,
        "request_post": fulfillment.request_post,
        "evidence_post": fulfillment.evidence_post,
        "task": fulfillment.task,
        "assistant_message": fulfillment.assistant_message,
        "activity_logs": fulfillment.activity_logs,
        "quarantined": fulfillment.quarantined,
    }

@router.post("/{item_id}/resolve-tool-approval")
def resolve_sdk_tool_approval(
    item_id: str,
    action: str,
    call_id: str,
    user: User = Depends(current_user),
) -> dict[str, object]:
    from agentmesh.routes.chat import agent

    item = store.get_inbox_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Inbox item not found")
    if not inbox_visible_to_user(item, user):
        raise HTTPException(status_code=403, detail="Not allowed to update this inbox item")
    if item.item_type != "sdk_tool_approval":
        raise HTTPException(status_code=400, detail="Inbox item is not an SDK tool approval")
    if item.status != "open":
        raise HTTPException(status_code=409, detail="Tool approval is no longer open")
    now = now_utc()
    if now - item.created_at > timedelta(hours=24):
        store.expire_agent_run_approval(
            run_id=item.metadata.get("run_id", ""),
            user_id=user.id,
            inbox_id=item.id,
            checked_at=now,
        )
        raise HTTPException(status_code=409, detail="Tool approval has expired")
    if action not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")
    run_id = item.metadata.get("run_id")
    if not call_id:
        raise HTTPException(status_code=400, detail="call_id is required")
    if not run_id or agent.agent_runtime is None:
        raise HTTPException(status_code=400, detail="Inbox item is missing Agent runtime state")
    try:
        answer = agent.agent_runtime.resume_sync(
            run_id,
            user=user,
            decisions={call_id: action == "approve"},
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except RuntimeError as error:
        failed_run = store.get_agent_run(run_id)
        current_item = store.get_inbox_item(item.id)
        if (
            failed_run is not None
            and failed_run.status in {"completed", "partial", "failed", "rejected", "cancelled"}
            and current_item is not None
            and current_item.status == "open"
        ):
            failed_at = now_utc()
            current_item.status = "resolved"
            current_item.acknowledged_at = current_item.acknowledged_at or failed_at
            current_item.resolved_at = failed_at
            current_item.updated_at = failed_at
            current_item.metadata["approval_failure"] = failed_run.error_code or failed_run.status.value
            store.save_inbox_item(current_item)
        raise HTTPException(status_code=409, detail=str(error)) from error
    except Exception as error:
        failed_run = store.get_agent_run(run_id)
        if failed_run is not None and failed_run.status == "failed":
            failed_at = now_utc()
            item.status = "resolved"
            item.acknowledged_at = item.acknowledged_at or failed_at
            item.resolved_at = failed_at
            item.updated_at = failed_at
            item.metadata["approval_failure"] = failed_run.error_code or type(error).__name__
            store.save_inbox_item(item)
            store.add_audit_event(
                create_audit_event(
                    user.id,
                    "resolve_sdk_tool_approval_failed",
                    "inbox_item",
                    item.id,
                    {"run_id": run_id, "call_id": call_id, "error_code": item.metadata["approval_failure"]},
                )
            )
        raise HTTPException(status_code=409, detail="Tool approval execution failed") from error

    now = now_utc()
    if answer.waiting_approval:
        item.metadata["interruptions"] = json.dumps(answer.interruptions, ensure_ascii=False)
        item.updated_at = now
        store.save_inbox_item(item)
        return {"item": item, "run_id": run_id, "waiting_approval": True}

    item.status = "resolved"
    item.acknowledged_at = item.acknowledged_at or now
    item.resolved_at = now
    item.updated_at = now
    item.metadata["approval_action"] = action
    store.save_inbox_item(item)
    run = store.get_agent_run(run_id)
    assistant_message = None
    if run is not None and not run.project_chat:
        assistant_message = store.add_chat_message(
            ChatMessage(
                thread_id=run.thread_id,
                role=ChatRole.ASSISTANT,
                content=answer.content,
                scope=Scope.PRIVATE,
                workflow_trace=ChatWorkflowTrace(
                    intent=Intent.GENERAL_CHAT,
                    confidence=1.0,
                    source="skill" if answer.skill_name else "chat",
                    selected_workflow=f"${answer.skill_name}" if answer.skill_name else "chat",
                    persisted=True,
                    llm_used=answer.llm_used,
                    requested_provider="openai_agents_sdk",
                    actual_provider="openai_agents_sdk",
                    requested_model=answer.requested_model,
                    actual_model=answer.actual_model,
                    provider_mode="real",
                ),
            )
        )
        agent.agent_runtime.mark_projected_messages(run.thread_id, [assistant_message.id])
    store.add_audit_event(
        create_audit_event(
            user.id,
            "resolve_sdk_tool_approval",
            "inbox_item",
            item.id,
            {"action": action, "run_id": run_id, "call_id": call_id},
        )
    )
    return {"item": item, "run_id": run_id, "answer": answer.content, "assistant_message": assistant_message}


def is_brief_confirmation(item: InboxItem) -> bool:
    return (
        item.item_type == "decision_review"
        and item.metadata.get("artifact_type") == "brief_draft"
        and bool(item.metadata.get("document_id"))
    )


def requires_dedicated_transition(item: InboxItem) -> bool:
    return item.item_type in {"prompt_injection_review", "sdk_tool_approval"} or is_brief_confirmation(item)




def inbox_visible_to_user(item: InboxItem, user: User) -> bool:
    if user.role == UserRole.ADMIN:
        return True
    if item.scope == Scope.PRIVATE:
        if item.user_id is not None:
            return item.user_id == user.id
        return item.workspace_id == user.workspace_id and (
            item.project_id is None or item.project_id == user.default_project_id
        )
    if user.role == UserRole.TEAM_LEAD:
        return item.workspace_id in {None, user.workspace_id}
    if item.user_id is not None:
        return item.user_id == user.id
    return item.workspace_id in {None, user.workspace_id} and item.project_id in {None, user.default_project_id}
