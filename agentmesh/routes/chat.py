"""Chat routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from agentmesh.agents import ChatThreadAccessError, PersonalAgent
from agentmesh.chat_skills import list_chat_skills
from agentmesh.models import ChatRequest, ChatResponse, ChatThread, ChatThreadCreateRequest, ItemsResponse, User
from agentmesh.o2 import build_acquisition_agent
from agentmesh.routes.deps import current_user
from agentmesh.seed import PROJECT, WORKSPACE
from agentmesh.store import store

router = APIRouter(prefix="/api/chat", tags=["chat"])

agent = PersonalAgent(store, acquisition_agent=build_acquisition_agent())


@router.post("/threads", response_model=dict[str, ChatThread])
def create_chat_thread(request: ChatThreadCreateRequest, user: User = Depends(current_user)) -> dict[str, ChatThread]:
    thread = store.add_chat_thread(
        ChatThread(
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
            user_id=user.id,
            title=request.title,
        )
    )
    return {"thread": thread}

@router.get("/threads", response_model=ItemsResponse)
def chat_threads(user: User = Depends(current_user)) -> ItemsResponse:
    return ItemsResponse(items=store.list_chat_threads(user.id))


@router.get("/threads/{thread_id}/messages", response_model=ItemsResponse)
def chat_thread_messages(thread_id: str, user: User = Depends(current_user)) -> ItemsResponse:
    thread = store.get_chat_thread(thread_id)
    if thread is None or thread.user_id != user.id:
        raise HTTPException(status_code=404, detail="Chat thread not found")
    messages = sorted(store.list_thread_messages(thread_id), key=lambda message: message.created_at)
    return ItemsResponse(items=messages)

@router.get("/threads/{thread_id}/turn-traces", response_model=ItemsResponse)
def chat_thread_turn_traces(thread_id: str, user: User = Depends(current_user)) -> ItemsResponse:
    thread = store.get_chat_thread(thread_id)
    if thread is None or thread.user_id != user.id:
        raise HTTPException(status_code=404, detail="Chat thread not found")
    return ItemsResponse(items=store.list_thread_turn_traces(thread_id))



@router.get("/skills", response_model=ItemsResponse)
def chat_skills(_: User = Depends(current_user)) -> ItemsResponse:
    return ItemsResponse(items=list_chat_skills())


@router.post("/messages", response_model=ChatResponse)
def create_chat_message(request: ChatRequest, user: User = Depends(current_user)) -> ChatResponse:
    try:
        return agent.handle_chat(content=request.content, thread_id=request.thread_id, user=user)
    except ChatThreadAccessError as error:
        raise HTTPException(status_code=404, detail="Chat thread not found") from error
