"""Durable OpenAI Agents SDK run creation, inspection, streaming, and cancellation routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import StreamingResponse

from agentmesh.models import AgentRunCreateRequest, ChatThread, ItemResponse, ItemsResponse, User, new_id
from agentmesh.routes.deps import current_user
from agentmesh.skill_runtime.service import catalog_service
from agentmesh.store import store

router = APIRouter(prefix="/api/agent/runs", tags=["agent-runs"])
_TERMINAL = {"completed", "failed", "cancelled"}


def _visible_run(run_id: str, user: User):
    run = store.get_agent_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    if run.user_id != user.id or run.workspace_id != user.workspace_id:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return run


def _thread(request: AgentRunCreateRequest, user: User) -> ChatThread:
    if request.thread_id:
        thread = store.get_chat_thread(request.thread_id)
        if (
            thread is None
            or thread.user_id != user.id
            or thread.workspace_id != user.workspace_id
            or thread.project_id != user.default_project_id
        ):
            raise HTTPException(status_code=404, detail="Chat thread not found")
        return thread
    return store.add_chat_thread(
        ChatThread(
            id=new_id("thread"),
            workspace_id=user.workspace_id,
            project_id=user.default_project_id,
            user_id=user.id,
            title=request.content.strip()[:60] or "新的 Agent 运行",
        )
    )


@router.post("", response_model=ItemResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_agent_run(
    request: AgentRunCreateRequest,
    user: User = Depends(current_user),
) -> ItemResponse:
    from agentmesh.routes.chat import agent

    runtime = agent.agent_runtime
    if runtime is None or not runtime.enabled:
        raise HTTPException(status_code=409, detail="Agent Runtime v2 is disabled")
    prior = store.get_agent_run_by_client_turn(user.id, request.client_turn_id)
    if prior is not None:
        if (
            prior.input_text != request.content
            or prior.skill_name != request.skill_name
            or (request.thread_id is not None and prior.thread_id != request.thread_id)
        ):
            raise HTTPException(status_code=409, detail="client_turn_id was already used for another Agent run")
        return ItemResponse(item=prior)
    thread = _thread(request, user)
    skill = catalog_service().get_by_name(request.skill_name, user.personal_agent_id) if request.skill_name else None
    if request.skill_name and skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    try:
        run = await runtime.start(
            content=request.content,
            user=user,
            thread_id=thread.id,
            history=store.list_thread_messages(thread.id),
            skill=skill,
            client_turn_id=request.client_turn_id,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return ItemResponse(item=run)


@router.get("/{run_id}", response_model=ItemResponse)
def get_agent_run(run_id: str, user: User = Depends(current_user)) -> ItemResponse:
    return ItemResponse(item=_visible_run(run_id, user))


@router.get("/{run_id}/events", response_model=ItemsResponse)
def get_agent_run_events(
    run_id: str,
    after_sequence: int = 0,
    user: User = Depends(current_user),
) -> ItemsResponse:
    _visible_run(run_id, user)
    return ItemsResponse(items=store.list_agent_run_events(run_id, after_sequence=max(0, after_sequence)))


@router.get("/{run_id}/events/stream")
def stream_agent_run_events(
    run_id: str,
    after_sequence: int = 0,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    user: User = Depends(current_user),
) -> StreamingResponse:
    _visible_run(run_id, user)
    try:
        resume_sequence = int(last_event_id) if last_event_id is not None else 0
    except ValueError:
        resume_sequence = 0

    async def event_stream():
        sequence = max(0, after_sequence, resume_sequence)
        while True:
            events = store.list_agent_run_events(run_id, sequence)
            for event in events:
                sequence = event.sequence
                yield f"id: {event.sequence}\nevent: {event.event_type}\ndata: {event.model_dump_json()}\n\n"
            run = store.get_agent_run(run_id)
            if run is None or (run.status.value in _TERMINAL and not events):
                break
            await asyncio.sleep(0.1)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.post("/{run_id}/cancel", response_model=ItemResponse)
async def cancel_agent_run(run_id: str, user: User = Depends(current_user)) -> ItemResponse:
    from agentmesh.routes.chat import agent

    _visible_run(run_id, user)
    runtime = agent.agent_runtime
    if runtime is None:
        raise HTTPException(status_code=409, detail="Agent Runtime v2 is disabled")
    try:
        run = await runtime.cancel(run_id, user=user)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    return ItemResponse(item=run)
