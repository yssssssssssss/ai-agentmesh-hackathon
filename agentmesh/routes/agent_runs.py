"""Durable OpenAI Agents SDK run creation, inspection, streaming, and cancellation routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import StreamingResponse

from agentmesh.agent_runtime.settings import SkillOrchestrationMode, skill_orchestration_mode
from agentmesh.models import (
    AgentRunCreateRequest,
    AgentRunEventsResponse,
    AgentRunRetryRequest,
    AgentRunStatus,
    ChatThread,
    ItemResponse,
    SkillPlanDetailResponse,
    SkillPlanDraft,
    SkillPlanStatus,
    SkillPlanTransitionResponse,
    SkillPlanUpdateRequest,
    SkillPlanVersionRequest,
    SkillSynthesisResult,
    User,
    new_id,
    now_utc,
)
from agentmesh.routes.deps import current_user, require_default_project
from agentmesh.skill_runtime.plan_validation import PlanValidationError, adjust_plan, validate_draft
from agentmesh.skill_runtime.retrieval import SkillCandidateRetriever
from agentmesh.skill_runtime.service import catalog_service
from agentmesh.store import store

router = APIRouter(prefix="/api/agent/runs", tags=["agent-runs"])
_TERMINAL = {"completed", "partial", "failed", "rejected", "cancelled"}


def _visible_run(run_id: str, user: User):
    run = store.get_agent_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    if (
        run.user_id != user.id
        or run.workspace_id != user.workspace_id
        or not store.user_can_execute_agent_run(user.id, run.id)
    ):
        raise HTTPException(status_code=404, detail="Agent run not found")
    return run


def _visible_plan(run_id: str, user: User):
    run = _visible_run(run_id, user)
    plan = store.get_skill_plan_for_run(run.id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Skill plan not found")
    return run, plan


def _reject_expired_plan_approval(run, user: User) -> None:  # noqa: ANN001
    if (
        run.status == AgentRunStatus.WAITING_PLAN_APPROVAL
        and run.deadline_at is not None
        and now_utc() >= run.deadline_at
    ):
        store.cancel_agent_run_tree(run.id, user_id=user.id)
        raise HTTPException(status_code=409, detail="Skill plan approval deadline expired")


def _current_plan_candidates(plan, user: User):  # noqa: ANN001, ANN201
    candidates, _diagnostics = SkillCandidateRetriever(store, catalog_service()).recommend(user, plan.intent)
    by_id = {candidate.skill_id: candidate for candidate in candidates}
    selected = [by_id[skill_id] for skill_id in plan.candidate_skill_ids if skill_id in by_id]
    if any(node.skill_id not in by_id for node in plan.nodes):
        raise HTTPException(status_code=409, detail="A planned Skill is no longer ready or authorized")
    return selected


def _thread(request: AgentRunCreateRequest, user: User) -> ChatThread:
    require_default_project(user, store)
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
    if request.skill_name and request.explicit_skill_name and request.skill_name != request.explicit_skill_name:
        raise HTTPException(status_code=400, detail="skill_name and explicit_skill_name disagree")
    explicit_skill_name = request.explicit_skill_name or request.skill_name
    prior = store.get_agent_run_by_client_turn(user.id, request.client_turn_id)
    if prior is not None:
        prior = _visible_run(prior.id, user)
        if (
            prior.input_text != request.content
            or prior.skill_name != explicit_skill_name
            or (request.thread_id is not None and prior.thread_id != request.thread_id)
            or (
                prior.requested_orchestration_mode is not None
                and prior.requested_orchestration_mode != request.orchestration_mode
            )
        ):
            raise HTTPException(status_code=409, detail="client_turn_id was already used for another Agent run")
        return ItemResponse(item=prior)
    thread = _thread(request, user)
    skill = catalog_service().get_by_name(explicit_skill_name, user.personal_agent_id) if explicit_skill_name else None
    if explicit_skill_name and skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    try:
        mode = skill_orchestration_mode()
        if skill is None and request.orchestration_mode == "auto" and mode != SkillOrchestrationMode.OFF:
            run = await runtime.start_orchestrated(
                content=request.content,
                user=user,
                thread_id=thread.id,
                history=store.list_thread_messages(thread.id),
                client_turn_id=request.client_turn_id,
                mode=mode,
            )
        else:
            run = await runtime.start(
                content=request.content,
                user=user,
                thread_id=thread.id,
                history=store.list_thread_messages(thread.id),
                skill=skill,
                client_turn_id=request.client_turn_id,
                requested_orchestration_mode=request.orchestration_mode,
            )
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return ItemResponse(item=run)


@router.get("/{run_id}", response_model=ItemResponse)
def get_agent_run(run_id: str, user: User = Depends(current_user)) -> ItemResponse:
    return ItemResponse(item=_visible_run(run_id, user))


@router.get("/{run_id}/plan", response_model=SkillPlanDetailResponse)
def get_agent_run_plan(run_id: str, user: User = Depends(current_user)) -> SkillPlanDetailResponse:
    _run, plan = _visible_plan(run_id, user)
    return SkillPlanDetailResponse(
        plan=plan,
        results=store.list_skill_node_results(plan.id),
        synthesis=SkillSynthesisResult.model_validate(plan.synthesis) if plan.synthesis is not None else None,
    )


@router.patch("/{run_id}/plan", response_model=SkillPlanDetailResponse)
def update_agent_run_plan(
    run_id: str,
    request: SkillPlanUpdateRequest,
    user: User = Depends(current_user),
) -> SkillPlanDetailResponse:
    run, plan = _visible_plan(run_id, user)
    _reject_expired_plan_approval(run, user)
    if run.status != AgentRunStatus.WAITING_PLAN_APPROVAL or plan.status != SkillPlanStatus.WAITING_APPROVAL:
        raise HTTPException(status_code=409, detail="Skill plan is not editable")
    if plan.version != request.expected_version:
        raise HTTPException(status_code=409, detail="Skill plan version conflict")
    try:
        adjusted = adjust_plan(plan, request, _current_plan_candidates(plan, user))
    except PlanValidationError as error:
        raise HTTPException(status_code=400, detail={"codes": error.codes}) from error
    if not store.compare_and_swap_skill_plan(
        adjusted,
        expected_version=request.expected_version,
        events=[
            (
                "plan_updated",
                {
                    "plan_id": adjusted.id,
                    "version": request.expected_version + 1,
                    "selected_skill_ids": request.selected_skill_ids,
                },
            )
        ],
    ):
        raise HTTPException(status_code=409, detail="Skill plan version conflict")
    return SkillPlanDetailResponse(plan=adjusted, results=[], synthesis=None)


@router.post("/{run_id}/plan/approve", response_model=SkillPlanTransitionResponse)
async def approve_agent_run_plan(
    run_id: str,
    request: SkillPlanVersionRequest,
    user: User = Depends(current_user),
) -> SkillPlanTransitionResponse:
    from agentmesh.routes.chat import agent

    run, plan = _visible_plan(run_id, user)
    _reject_expired_plan_approval(run, user)
    configured_mode = skill_orchestration_mode()
    if configured_mode == SkillOrchestrationMode.OFF:
        store.cancel_agent_run_tree(run.id, user_id=user.id)
        raise HTTPException(status_code=409, detail="Skill orchestration is disabled")
    candidates = _current_plan_candidates(plan, user)
    try:
        validate_draft(
            SkillPlanDraft(output_contract=plan.output_contract, nodes=plan.nodes),
            candidates,
            intent=plan.intent,
        )
    except PlanValidationError as error:
        raise HTTPException(status_code=409, detail={"codes": error.codes}) from error
    requested_mode = SkillOrchestrationMode(run.orchestration_mode)
    if requested_mode == SkillOrchestrationMode.PREVIEW or configured_mode == SkillOrchestrationMode.PREVIEW:
        message = "计划已确认；当前为 preview 模式，未执行任何 Skill。"
        transition = store.transition_skill_plan_and_run(
            plan_id=plan.id,
            run_id=run.id,
            expected_version=request.expected_version,
            expected_plan_status=SkillPlanStatus.WAITING_APPROVAL,
            expected_run_status=AgentRunStatus.WAITING_PLAN_APPROVAL,
            next_plan_status=SkillPlanStatus.APPROVED,
            next_run_status=AgentRunStatus.COMPLETED,
            events=[
                ("plan_approved", {"plan_id": plan.id}),
                ("run_completed", {"preview_only": True}),
            ],
            output_text=message,
        )
        if transition is None:
            raise HTTPException(status_code=409, detail="Skill plan approval conflict")
        transitioned_plan, transitioned_run = transition
        if agent.agent_runtime is not None:
            agent.agent_runtime.project_orchestration_output(transitioned_run, message)
        return SkillPlanTransitionResponse(plan=transitioned_plan, run=transitioned_run)
    runtime = agent.agent_runtime
    if runtime is None or not runtime.enabled:
        store.cancel_agent_run_tree(run.id, user_id=user.id)
        raise HTTPException(status_code=409, detail="Agent Runtime v2 is disabled")
    if not store.user_can_execute_agent_run(
        user.id,
        run.id,
        allowed_statuses={AgentRunStatus.WAITING_PLAN_APPROVAL},
    ):
        raise HTTPException(status_code=404, detail="Agent run not found")
    transition = store.transition_skill_plan_and_run(
        plan_id=plan.id,
        run_id=run.id,
        expected_version=request.expected_version,
        expected_plan_status=SkillPlanStatus.WAITING_APPROVAL,
        expected_run_status=AgentRunStatus.WAITING_PLAN_APPROVAL,
        next_plan_status=SkillPlanStatus.APPROVED,
        next_run_status=AgentRunStatus.RUNNING,
        events=[("plan_approved", {"plan_id": plan.id})],
    )
    if transition is None:
        raise HTTPException(status_code=409, detail="Skill plan approval conflict")
    transitioned_plan, transitioned_run = transition
    try:
        await runtime.start_approved_skill_plan(transitioned_plan.id, user=user)
    except (LookupError, PermissionError, RuntimeError) as error:
        store.cancel_agent_run_tree(transitioned_run.id, user_id=user.id)
        status_code = 404 if isinstance(error, (LookupError, PermissionError)) else 409
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    return SkillPlanTransitionResponse(plan=transitioned_plan, run=transitioned_run)


@router.post("/{run_id}/plan/reject", response_model=SkillPlanTransitionResponse)
def reject_agent_run_plan(
    run_id: str,
    request: SkillPlanVersionRequest,
    user: User = Depends(current_user),
) -> SkillPlanTransitionResponse:
    from agentmesh.routes.chat import agent

    run, plan = _visible_plan(run_id, user)
    _reject_expired_plan_approval(run, user)
    message = "你已拒绝该多 Skill 计划，未执行任何节点。"
    transition = store.transition_skill_plan_and_run(
        plan_id=plan.id,
        run_id=run.id,
        expected_version=request.expected_version,
        expected_plan_status=SkillPlanStatus.WAITING_APPROVAL,
        expected_run_status=AgentRunStatus.WAITING_PLAN_APPROVAL,
        next_plan_status=SkillPlanStatus.REJECTED,
        next_run_status=AgentRunStatus.REJECTED,
        events=[("plan_rejected", {"plan_id": plan.id}), ("run_rejected", {})],
        output_text=message,
    )
    if transition is None:
        raise HTTPException(status_code=409, detail="Skill plan rejection conflict")
    transitioned_plan, transitioned_run = transition
    if agent.agent_runtime is not None:
        agent.agent_runtime.project_orchestration_output(transitioned_run, message)
    return SkillPlanTransitionResponse(plan=transitioned_plan, run=transitioned_run)


@router.post("/{run_id}/retry", response_model=ItemResponse, status_code=status.HTTP_202_ACCEPTED)
async def retry_agent_run(
    run_id: str,
    request: AgentRunRetryRequest,
    user: User = Depends(current_user),
) -> ItemResponse:
    from agentmesh.routes.chat import agent

    prior = _visible_run(run_id, user)
    if prior.orchestration_version == "research-v2":
        raise HTTPException(status_code=409, detail="Research-v2 runs must use the research recovery API")
    if prior.status not in {
        AgentRunStatus.PARTIAL,
        AgentRunStatus.FAILED,
        AgentRunStatus.CANCELLED,
        AgentRunStatus.REJECTED,
    }:
        raise HTTPException(status_code=409, detail="Only terminal unsuccessful Agent runs can be retried")
    if prior.client_turn_id and request.client_turn_id == prior.client_turn_id:
        raise HTTPException(status_code=409, detail="Retry requires a new client_turn_id")
    runtime = agent.agent_runtime
    if runtime is None or not runtime.enabled:
        raise HTTPException(status_code=409, detail="Agent Runtime v2 is disabled")
    try:
        if prior.plan_id:
            mode = skill_orchestration_mode()
            if mode == SkillOrchestrationMode.OFF:
                raise HTTPException(status_code=409, detail="Skill orchestration is disabled")
            prior_plan = store.get_skill_plan_for_run(prior.id)
            if prior_plan is None:
                raise HTTPException(status_code=409, detail="Prior Skill plan is missing")
            retried = await runtime.retry_orchestrated(
                prior_run=prior,
                prior_plan=prior_plan,
                user=user,
                client_turn_id=request.client_turn_id,
                mode=mode,
            )
        else:
            skill = (
                catalog_service().get_by_name(prior.skill_name or "", user.personal_agent_id)
                if prior.skill_name
                else None
            )
            retried = await runtime.start(
                content=prior.input_text,
                user=user,
                thread_id=prior.thread_id,
                history=store.list_thread_messages(prior.thread_id),
                skill=skill,
                client_turn_id=request.client_turn_id,
                project_id=prior.project_id,
            )
    except PlanValidationError as error:
        raise HTTPException(status_code=409, detail={"codes": error.codes}) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return ItemResponse(item=retried)


@router.get("/{run_id}/events", response_model=AgentRunEventsResponse)
def get_agent_run_events(
    run_id: str,
    after_sequence: int = 0,
    user: User = Depends(current_user),
) -> AgentRunEventsResponse:
    _visible_run(run_id, user)
    return AgentRunEventsResponse(items=store.list_agent_run_events(run_id, after_sequence=max(0, after_sequence)))


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

    run = _visible_run(run_id, user)
    if run.orchestration_version == "research-v2":
        cancelled = store.cancel_agent_run_tree(run.id, user_id=user.id)
        if cancelled is None:
            raise HTTPException(status_code=404, detail="Agent run not found")
        return ItemResponse(item=cancelled)
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
