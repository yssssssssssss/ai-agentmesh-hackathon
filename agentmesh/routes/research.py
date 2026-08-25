"""Read-only research-v2 history and research-v3 preview routes."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from agentmesh.models import User
from agentmesh.research_orchestration.api import (
    ResearchConflictError,
    ResearchNotFoundError,
    ResearchOwnerScope,
    ResearchRunProjection,
)
from agentmesh.research_orchestration.v2_history import V2HistoryReader
from agentmesh.research_orchestration.v3.api import (
    ResearchV3AbortRequest,
    ResearchV3AbortResponse,
    ResearchV3AggregateReadRequest,
    ResearchV3AggregateReadResponse,
    ResearchV3ApprovalRequest,
    ResearchV3ApprovalResponse,
    ResearchV3CancelRequest,
    ResearchV3CancelResponse,
    ResearchV3CandidateSelectRequest,
    ResearchV3CandidateSelectResponse,
    ResearchV3ClarifyRequest,
    ResearchV3ClarifyResponse,
    ResearchV3ConfirmRequest,
    ResearchV3ConfirmResponse,
    ResearchV3ConflictError,
    ResearchV3ExecuteRequest,
    ResearchV3ExecuteResponse,
    ResearchV3MutationReceipt,
    ResearchV3NotFoundError,
    ResearchV3OwnerScope,
    ResearchV3PlanStreamResult,
    ResearchV3PurgeRequest,
    ResearchV3PurgeResponse,
    ResearchV3RetryRequest,
    ResearchV3RetryResponse,
    ResearchV3ReviseRequest,
    ResearchV3ReviseResponse,
    ResearchV3SkipRequest,
    ResearchV3SkipResponse,
)
from agentmesh.routes.deps import current_user
from agentmesh.store import store

router = APIRouter(prefix="/api/agent/runs", tags=["research"])


def get_v2_history_reader(request: Request) -> V2HistoryReader:
    reader = getattr(request.app.state, "research_v2_history_reader", None)
    if reader is None or not callable(getattr(reader, "get_projection", None)):
        raise HTTPException(status_code=503, detail="Research history reader is unavailable")
    return reader


def _required_idempotency_key(
    value: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=120),
    ],
) -> str:
    if not value.strip() or value != value.strip():
        raise HTTPException(status_code=400, detail="Idempotency-Key must be non-blank and canonical")
    return value


IdempotencyKey = Annotated[str, Depends(_required_idempotency_key)]
CurrentUser = Annotated[User, Depends(current_user)]


def _owner_scope(user: User) -> ResearchOwnerScope:
    return ResearchOwnerScope(
        user_id=user.id,
        workspace_id=user.workspace_id,
        project_id=user.default_project_id,
    )


def _v3_owner_scope(user: User) -> ResearchV3OwnerScope:
    return ResearchV3OwnerScope(
        user_id=user.id,
        workspace_id=user.workspace_id,
        project_id=user.default_project_id,
    )


def _stored_version(run_id: str, user: User) -> str | None:
    run = store.get_agent_run(run_id)
    if run is None:
        return None
    if (
        run.user_id != user.id
        or run.workspace_id != user.workspace_id
        or run.project_id != user.default_project_id
    ):
        raise HTTPException(status_code=404, detail="Research run not found")
    return run.orchestration_version


def _v3_service(request: Request):  # noqa: ANN202
    service = getattr(request.app.state, "research_v3_preview", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Research-v3 preview service is unavailable")
    return service


async def _v3_project(run_id: str, user: User, request: Request) -> ResearchV3AggregateReadResponse:
    try:
        raw = _v3_service(request).project_authoritative(
            ResearchV3AggregateReadRequest(run_id=run_id, owner=_v3_owner_scope(user))
        )
        if inspect.isawaitable(raw):
            raw = await raw
        return ResearchV3AggregateReadResponse.model_validate(raw)
    except ResearchV3NotFoundError:
        raise HTTPException(status_code=404, detail="Research run not found") from None
    except ResearchV3ConflictError as error:
        raise HTTPException(status_code=409, detail=str(error) or "Research-v3 preview conflict") from None


async def _v3_mutate(
    *,
    run_id: str,
    command_type: str,
    body,
    user: User,
    idempotency_key: str,
    request: Request,
    response_type,
):  # noqa: ANN001, ANN202
    try:
        raw = _v3_service(request).apply(
            run_id,
            command_type,
            body,
            owner=_v3_owner_scope(user),
            idempotency_key=idempotency_key,
        )
        if inspect.isawaitable(raw):
            raw = await raw
        receipt = ResearchV3MutationReceipt.model_validate(raw)
        expected = (
            run_id,
            command_type,
            idempotency_key,
            body.request_hash,
            body.expected_state_version,
        )
        actual = (
            receipt.run_id,
            receipt.command_type,
            receipt.idempotency_key,
            receipt.request_hash,
            receipt.previous_state_version,
        )
        if actual != expected:
            raise ResearchV3ConflictError("workflow receipt does not match the submitted command")
        values = {
            "run_id": receipt.run_id,
            "command_type": receipt.command_type,
            "request_hash": receipt.request_hash,
            "previous_state_version": receipt.previous_state_version,
            "state_version": receipt.state_version,
            "accepted": receipt.accepted,
            "replayed": receipt.replayed,
        }
        if response_type is ResearchV3PurgeResponse:
            values["purged_artifact_count"] = receipt.purged_artifact_count
        return response_type.model_validate(values)
    except ResearchV3NotFoundError:
        raise HTTPException(status_code=404, detail="Research run not found") from None
    except ResearchV3ConflictError as error:
        raise HTTPException(status_code=409, detail=str(error) or "Research-v3 preview conflict") from None


async def _service_call(operation: Callable[[], object]) -> object:
    try:
        result = operation()
        if inspect.isawaitable(result):
            result = await result
        return result
    except ResearchNotFoundError:
        raise HTTPException(status_code=404, detail="Research run not found") from None
    except ResearchConflictError as error:
        raise HTTPException(status_code=409, detail=str(error) or "Research workflow conflict") from None


@router.get(
    "/{run_id}/research",
    response_model=ResearchRunProjection | ResearchV3AggregateReadResponse,
)
async def get_research_run(
    run_id: str,
    user: CurrentUser,
    request: Request,
) -> ResearchRunProjection | ResearchV3AggregateReadResponse:
    if _stored_version(run_id, user) == "research-v3":
        return await _v3_project(run_id, user, request)
    reader = get_v2_history_reader(request)
    result = await _service_call(lambda: reader.get_projection(run_id, owner=_owner_scope(user)))
    return ResearchRunProjection.model_validate(result)


@router.post(
    "/{run_id}/research/clarify",
    response_model=ResearchV3ClarifyResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def clarify_research_run(
    run_id: str,
    request_body: ResearchV3ClarifyRequest,
    user: CurrentUser,
    idempotency_key: IdempotencyKey,
    request: Request,
) -> ResearchV3ClarifyResponse:
    _require_v3_version(run_id, user)
    return await _v3_mutate(
        run_id=run_id,
        command_type="clarify",
        body=request_body,
        user=user,
        idempotency_key=idempotency_key,
        request=request,
        response_type=ResearchV3ClarifyResponse,
    )


@router.post(
    "/{run_id}/research/execute",
    response_model=ResearchV3ExecuteResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def execute_research_run(
    run_id: str,
    request_body: ResearchV3ExecuteRequest,
    user: CurrentUser,
    idempotency_key: IdempotencyKey,
    request: Request,
) -> ResearchV3ExecuteResponse:
    _require_v3_version(run_id, user)
    return await _v3_mutate(
        run_id=run_id,
        command_type="execute",
        body=request_body,
        user=user,
        idempotency_key=idempotency_key,
        request=request,
        response_type=ResearchV3ExecuteResponse,
    )


@router.delete(
    "/{run_id}/research-data",
    response_model=ResearchV3PurgeResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def purge_research_run_data(
    run_id: str,
    request_body: ResearchV3PurgeRequest,
    user: CurrentUser,
    idempotency_key: IdempotencyKey,
    request: Request,
) -> ResearchV3PurgeResponse:
    _require_v3_version(run_id, user)
    return await _v3_mutate(
        run_id=run_id,
        command_type="purge",
        body=request_body,
        user=user,
        idempotency_key=idempotency_key,
        request=request,
        response_type=ResearchV3PurgeResponse,
    )


def _require_v3_version(run_id: str, user: User) -> None:
    version = _stored_version(run_id, user)
    if version is None:
        raise HTTPException(status_code=404, detail="Research run not found")
    if version != "research-v3":
        raise HTTPException(status_code=409, detail="Command is not available for the stored research version")


@router.get(
    "/{run_id}/research/refresh",
    response_model=ResearchV3AggregateReadResponse,
)
async def refresh_research_v3(
    run_id: str,
    user: CurrentUser,
    request: Request,
) -> ResearchV3AggregateReadResponse:
    _require_v3_version(run_id, user)
    return await _v3_project(run_id, user, request)


@router.get("/{run_id}/research/plan/stream")
async def stream_research_v3_plan(
    run_id: str,
    user: CurrentUser,
    request: Request,
    after_state_version: Annotated[int | None, Query(ge=0)] = None,
) -> StreamingResponse:
    del after_state_version
    _require_v3_version(run_id, user)
    aggregate = (await _v3_project(run_id, user, request)).root
    result = ResearchV3PlanStreamResult(
        event_id=f"state:{aggregate.workflow.state_version}",
        run_id=aggregate.run_id,
        state_version=aggregate.workflow.state_version,
        aggregate=aggregate,
    )

    async def event_stream():  # noqa: ANN202
        yield f"id: {result.event_id}\nevent: projection\ndata: {result.model_dump_json()}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/{run_id}/research/candidates/select",
    response_model=ResearchV3CandidateSelectResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def select_research_v3_candidate(
    run_id: str,
    body: ResearchV3CandidateSelectRequest,
    user: CurrentUser,
    idempotency_key: IdempotencyKey,
    request: Request,
) -> ResearchV3CandidateSelectResponse:
    _require_v3_version(run_id, user)
    return await _v3_mutate(
        run_id=run_id,
        command_type="select_candidate",
        body=body,
        user=user,
        idempotency_key=idempotency_key,
        request=request,
        response_type=ResearchV3CandidateSelectResponse,
    )


@router.post(
    "/{run_id}/research/plans/revise",
    response_model=ResearchV3ReviseResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def revise_research_v3_plan(
    run_id: str,
    body: ResearchV3ReviseRequest,
    user: CurrentUser,
    idempotency_key: IdempotencyKey,
    request: Request,
) -> ResearchV3ReviseResponse:
    _require_v3_version(run_id, user)
    return await _v3_mutate(
        run_id=run_id,
        command_type="revise_plan",
        body=body,
        user=user,
        idempotency_key=idempotency_key,
        request=request,
        response_type=ResearchV3ReviseResponse,
    )


@router.post(
    "/{run_id}/research/plans/confirm",
    response_model=ResearchV3ConfirmResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def confirm_research_v3_plan(
    run_id: str,
    body: ResearchV3ConfirmRequest,
    user: CurrentUser,
    idempotency_key: IdempotencyKey,
    request: Request,
) -> ResearchV3ConfirmResponse:
    _require_v3_version(run_id, user)
    return await _v3_mutate(
        run_id=run_id,
        command_type="confirm_plan",
        body=body,
        user=user,
        idempotency_key=idempotency_key,
        request=request,
        response_type=ResearchV3ConfirmResponse,
    )


@router.post(
    "/{run_id}/research/approvals",
    response_model=ResearchV3ApprovalResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def approve_research_v3_plan(
    run_id: str,
    body: ResearchV3ApprovalRequest,
    user: CurrentUser,
    idempotency_key: IdempotencyKey,
    request: Request,
) -> ResearchV3ApprovalResponse:
    _require_v3_version(run_id, user)
    return await _v3_mutate(
        run_id=run_id,
        command_type="approval",
        body=body,
        user=user,
        idempotency_key=idempotency_key,
        request=request,
        response_type=ResearchV3ApprovalResponse,
    )


@router.post(
    "/{run_id}/research/recovery/retry",
    response_model=ResearchV3RetryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_research_v3(
    run_id: str,
    body: ResearchV3RetryRequest,
    user: CurrentUser,
    idempotency_key: IdempotencyKey,
    request: Request,
) -> ResearchV3RetryResponse:
    _require_v3_version(run_id, user)
    return await _v3_mutate(
        run_id=run_id,
        command_type="retry",
        body=body,
        user=user,
        idempotency_key=idempotency_key,
        request=request,
        response_type=ResearchV3RetryResponse,
    )


@router.post(
    "/{run_id}/research/recovery/skip",
    response_model=ResearchV3SkipResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def skip_research_v3(
    run_id: str,
    body: ResearchV3SkipRequest,
    user: CurrentUser,
    idempotency_key: IdempotencyKey,
    request: Request,
) -> ResearchV3SkipResponse:
    _require_v3_version(run_id, user)
    return await _v3_mutate(
        run_id=run_id,
        command_type="skip",
        body=body,
        user=user,
        idempotency_key=idempotency_key,
        request=request,
        response_type=ResearchV3SkipResponse,
    )


@router.post(
    "/{run_id}/research/recovery/abort",
    response_model=ResearchV3AbortResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def abort_research_v3(
    run_id: str,
    body: ResearchV3AbortRequest,
    user: CurrentUser,
    idempotency_key: IdempotencyKey,
    request: Request,
) -> ResearchV3AbortResponse:
    _require_v3_version(run_id, user)
    return await _v3_mutate(
        run_id=run_id,
        command_type="abort",
        body=body,
        user=user,
        idempotency_key=idempotency_key,
        request=request,
        response_type=ResearchV3AbortResponse,
    )


@router.post(
    "/{run_id}/research/cancel",
    response_model=ResearchV3CancelResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_research_v3(
    run_id: str,
    body: ResearchV3CancelRequest,
    user: CurrentUser,
    idempotency_key: IdempotencyKey,
    request: Request,
) -> ResearchV3CancelResponse:
    _require_v3_version(run_id, user)
    return await _v3_mutate(
        run_id=run_id,
        command_type="cancel",
        body=body,
        user=user,
        idempotency_key=idempotency_key,
        request=request,
        response_type=ResearchV3CancelResponse,
    )
