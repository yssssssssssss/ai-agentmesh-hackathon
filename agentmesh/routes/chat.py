"""Chat routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.agents import ChatThreadNotFoundError, PersonalAgent
from agentmesh.chat_skills import list_chat_skills
from agentmesh.data_authorization import DataQueryAuthorizationError
from agentmesh.models import (
    ChatRequest,
    ChatResponse,
    ChatThread,
    ChatThreadCreateRequest,
    ChatThreadDetailResponse,
    ChatThreadListResponse,
    ChatTurnReceipt,
    ChatTurnReceiptStatus,
    ChatTurnReceiptView,
    ItemsResponse,
    User,
    new_id,
)
from agentmesh.o2 import build_acquisition_agent
from agentmesh.routes.deps import current_user
from agentmesh.skill_runtime.service import catalog_service
from agentmesh.store import store

router = APIRouter(prefix="/api/chat", tags=["chat"])

catalog = catalog_service()
agent = PersonalAgent(
    store,
    acquisition_agent=build_acquisition_agent(),
    agent_runtime=AgentRuntimeService(store, skill_catalog=catalog),
    skill_catalog=catalog,
)


@router.get("/threads", response_model=ChatThreadListResponse)
def chat_threads(user: User = Depends(current_user)) -> ChatThreadListResponse:
    return ChatThreadListResponse(
        items=store.list_user_chat_threads(
            user.id,
            workspace_id=user.workspace_id,
            project_id=user.default_project_id,
        )
    )

@router.post("/threads", response_model=dict[str, ChatThread])
def create_chat_thread(request: ChatThreadCreateRequest, user: User = Depends(current_user)) -> dict[str, ChatThread]:
    thread = store.add_chat_thread(
        ChatThread(
            workspace_id=user.workspace_id,
            project_id=user.default_project_id,
            user_id=user.id,
            title=request.title,
        )
    )
    return {"thread": thread}




@router.get("/skills", response_model=ItemsResponse)
def chat_skills(user: User = Depends(current_user)) -> ItemsResponse:
    items = list_chat_skills()
    runtime = agent.agent_runtime
    if runtime is not None and runtime.enabled:
        catalog = catalog_service()
        items.extend(catalog.to_chat_skill(skill) for skill in catalog.list_enabled(user.personal_agent_id))
    return ItemsResponse(items=items)


def _receipt_conflict(receipt: ChatTurnReceipt, reason: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "client_turn_id": receipt.client_turn_id,
            "state": receipt.status.value,
            "thread_id": receipt.thread_id,
            "reason": reason,
        },
    )


def _receipt_view(receipt: ChatTurnReceipt) -> ChatTurnReceiptView:
    return ChatTurnReceiptView(
        client_turn_id=receipt.client_turn_id,
        status=receipt.status,
        thread_id=receipt.thread_id,
        response=receipt.response,
    )


@router.post("/messages", response_model=ChatResponse)
def create_chat_message(request: ChatRequest, user: User = Depends(current_user)) -> ChatResponse:
    prior = store.get_chat_turn_receipt(user.id, request.client_turn_id)
    if prior is None and request.thread_id is not None:
        thread = store.get_chat_thread(request.thread_id)
        if (
            thread is None
            or thread.user_id != user.id
            or thread.workspace_id != user.workspace_id
            or thread.project_id != user.default_project_id
        ):
            raise HTTPException(status_code=404, detail="Chat thread not found")

    candidate = ChatTurnReceipt(
        id=store.chat_turn_receipt_id(user.id, request.client_turn_id),
        client_turn_id=request.client_turn_id,
        user_id=user.id,
        workspace_id=user.workspace_id,
        project_id=user.default_project_id,
        requested_thread_id=request.thread_id,
        thread_id=request.thread_id or new_id("thread"),
        content=request.content,
    )
    receipt, claimed = store.claim_chat_turn_receipt(candidate)
    if not claimed:
        if receipt.content != request.content or receipt.requested_thread_id != request.thread_id:
            raise _receipt_conflict(receipt, "payload_mismatch")
        if receipt.status == ChatTurnReceiptStatus.COMPLETED and receipt.response is not None:
            return receipt.response
        raise _receipt_conflict(receipt, "prior_attempt_not_retryable")

    try:
        if request.thread_id is None:
            store.add_chat_thread(
                ChatThread(
                    id=receipt.thread_id,
                    workspace_id=user.workspace_id,
                    project_id=user.default_project_id,
                    user_id=user.id,
                    title=request.content.strip()[:60] or "新的团队大脑对话",
                )
            )
        response = agent.handle_chat(content=request.content, thread_id=receipt.thread_id, user=user)
        store.finish_chat_turn_receipt(
            receipt,
            status=ChatTurnReceiptStatus.COMPLETED,
            response=response,
        )
        return response
    except ChatThreadNotFoundError as error:
        store.finish_chat_turn_receipt(
            receipt,
            status=ChatTurnReceiptStatus.FAILED,
            error_code=type(error).__name__,
        )
        raise HTTPException(status_code=404, detail="Chat thread not found") from error
    except DataQueryAuthorizationError as error:
        store.finish_chat_turn_receipt(
            receipt,
            status=ChatTurnReceiptStatus.FAILED,
            error_code=type(error).__name__,
        )
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    except Exception as error:
        store.finish_chat_turn_receipt(
            receipt,
            status=ChatTurnReceiptStatus.FAILED,
            error_code=type(error).__name__,
        )
        raise


@router.get("/messages/receipts/{client_turn_id}", response_model=ChatTurnReceiptView)
def chat_turn_receipt(client_turn_id: str, user: User = Depends(current_user)) -> ChatTurnReceiptView:
    receipt = store.get_chat_turn_receipt(user.id, client_turn_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail="Chat turn receipt not found")
    return _receipt_view(receipt)



@router.get("/threads/{thread_id}", response_model=ChatThreadDetailResponse)
def chat_thread_detail(thread_id: str, user: User = Depends(current_user)) -> ChatThreadDetailResponse:
    thread = store.get_chat_thread(thread_id)
    if (
        thread is None
        or thread.user_id != user.id
        or thread.workspace_id != user.workspace_id
        or thread.project_id != user.default_project_id
    ):
        raise HTTPException(status_code=404, detail="Chat thread not found")
    return ChatThreadDetailResponse(
        thread=thread,
        messages=store.list_thread_messages(thread.id),
        turn_traces=store.list_thread_turn_traces(thread.id),
    )
