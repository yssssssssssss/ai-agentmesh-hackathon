"""HTTP control plane for owner-scoped research-v2 workflows."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from agentmesh.models import User
from agentmesh.research_orchestration.api import (
    ResearchClarifyRequest,
    ResearchCommandResponse,
    ResearchConfirmPlanRequest,
    ResearchConflictError,
    ResearchExecuteRequest,
    ResearchNotFoundError,
    ResearchOwnerScope,
    ResearchPurgeRequest,
    ResearchRecoverRequest,
    ResearchRevisePlanRequest,
    ResearchRunProjection,
)
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


class ResearchWorkflowService(Protocol):
    def get_projection(
        self,
        run_id: str,
        *,
        owner: ResearchOwnerScope,
    ) -> ResearchRunProjection | Awaitable[ResearchRunProjection]: ...

    def clarify(
        self,
        run_id: str,
        request: ResearchClarifyRequest,
        *,
        owner: ResearchOwnerScope,
        idempotency_key: str,
    ) -> ResearchCommandResponse | Awaitable[ResearchCommandResponse]: ...

    def confirm_plan(
        self,
        run_id: str,
        plan_version_id: str,
        request: ResearchConfirmPlanRequest,
        *,
        owner: ResearchOwnerScope,
        idempotency_key: str,
    ) -> ResearchCommandResponse | Awaitable[ResearchCommandResponse]: ...

    def revise_plan(
        self,
        run_id: str,
        plan_version_id: str,
        request: ResearchRevisePlanRequest,
        *,
        owner: ResearchOwnerScope,
        idempotency_key: str,
    ) -> ResearchCommandResponse | Awaitable[ResearchCommandResponse]: ...

    def execute(
        self,
        run_id: str,
        request: ResearchExecuteRequest,
        *,
        owner: ResearchOwnerScope,
        idempotency_key: str,
    ) -> ResearchCommandResponse | Awaitable[ResearchCommandResponse]: ...

    def recover(
        self,
        run_id: str,
        request: ResearchRecoverRequest,
        *,
        owner: ResearchOwnerScope,
        idempotency_key: str,
    ) -> ResearchCommandResponse | Awaitable[ResearchCommandResponse]: ...

    def purge(
        self,
        run_id: str,
        request: ResearchPurgeRequest,
        *,
        owner: ResearchOwnerScope,
        idempotency_key: str,
    ) -> ResearchCommandResponse | Awaitable[ResearchCommandResponse]: ...


def get_research_workflow_service(request: Request) -> ResearchWorkflowService:
    runtime = getattr(request.app.state, "research_runtime", None)
    service = getattr(runtime, "workflow_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Research workflow service is unavailable")
    return service


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
Service = Annotated[ResearchWorkflowService, Depends(get_research_workflow_service)]
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
    service: Service,
    request: Request,
) -> ResearchRunProjection | ResearchV3AggregateReadResponse:
    if _stored_version(run_id, user) == "research-v3":
        return await _v3_project(run_id, user, request)
    result = await _service_call(lambda: service.get_projection(run_id, owner=_owner_scope(user)))
    return ResearchRunProjection.model_validate(result)


@router.post(
    "/{run_id}/research/clarify",
    response_model=ResearchCommandResponse | ResearchV3ClarifyResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def clarify_research_run(
    run_id: str,
    request_body: ResearchClarifyRequest | ResearchV3ClarifyRequest,
    user: CurrentUser,
    idempotency_key: IdempotencyKey,
    service: Service,
    request: Request,
) -> ResearchCommandResponse | ResearchV3ClarifyResponse:
    if _stored_version(run_id, user) == "research-v3":
        if not isinstance(request_body, ResearchV3ClarifyRequest):
            raise HTTPException(status_code=422, detail="Research-v3 clarification body is invalid")
        return await _v3_mutate(
            run_id=run_id,
            command_type="clarify",
            body=request_body,
            user=user,
            idempotency_key=idempotency_key,
            request=request,
            response_type=ResearchV3ClarifyResponse,
        )
    if not isinstance(request_body, ResearchClarifyRequest):
        raise HTTPException(status_code=422, detail="Research-v2 clarification body is invalid")
    result = await _service_call(
        lambda: service.clarify(
            run_id,
            request_body,
            owner=_owner_scope(user),
            idempotency_key=idempotency_key,
        )
    )
    return ResearchCommandResponse.model_validate(result)


@router.post(
    "/{run_id}/research/plans/{plan_version_id}/confirm",
    response_model=ResearchCommandResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def confirm_research_plan(
    run_id: str,
    plan_version_id: str,
    request: ResearchConfirmPlanRequest,
    user: CurrentUser,
    idempotency_key: IdempotencyKey,
    service: Service,
) -> ResearchCommandResponse:
    result = await _service_call(
        lambda: service.confirm_plan(
            run_id,
            plan_version_id,
            request,
            owner=_owner_scope(user),
            idempotency_key=idempotency_key,
        )
    )
    return ResearchCommandResponse.model_validate(result)


@router.post(
    "/{run_id}/research/plans/{plan_version_id}/revise",
    response_model=ResearchCommandResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def revise_research_plan(
    run_id: str,
    plan_version_id: str,
    request: ResearchRevisePlanRequest,
    user: CurrentUser,
    idempotency_key: IdempotencyKey,
    service: Service,
) -> ResearchCommandResponse:
    result = await _service_call(
        lambda: service.revise_plan(
            run_id,
            plan_version_id,
            request,
            owner=_owner_scope(user),
            idempotency_key=idempotency_key,
        )
    )
    return ResearchCommandResponse.model_validate(result)


@router.post(
    "/{run_id}/research/execute",
    response_model=ResearchCommandResponse | ResearchV3ExecuteResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def execute_research_run(
    run_id: str,
    request_body: ResearchExecuteRequest | ResearchV3ExecuteRequest,
    user: CurrentUser,
    idempotency_key: IdempotencyKey,
    service: Service,
    request: Request,
) -> ResearchCommandResponse | ResearchV3ExecuteResponse:
    if _stored_version(run_id, user) == "research-v3":
        if not isinstance(request_body, ResearchV3ExecuteRequest):
            raise HTTPException(status_code=422, detail="Research-v3 execute body is invalid")
        return await _v3_mutate(
            run_id=run_id,
            command_type="execute",
            body=request_body,
            user=user,
            idempotency_key=idempotency_key,
            request=request,
            response_type=ResearchV3ExecuteResponse,
        )
    if not isinstance(request_body, ResearchExecuteRequest):
        raise HTTPException(status_code=422, detail="Research-v2 execute body is invalid")
    result = await _service_call(
        lambda: service.execute(
            run_id,
            request_body,
            owner=_owner_scope(user),
            idempotency_key=idempotency_key,
        )
    )
    return ResearchCommandResponse.model_validate(result)


@router.post(
    "/{run_id}/research/recover",
    response_model=ResearchCommandResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def recover_research_run(
    run_id: str,
    request: ResearchRecoverRequest,
    user: CurrentUser,
    idempotency_key: IdempotencyKey,
    service: Service,
) -> ResearchCommandResponse:
    result = await _service_call(
        lambda: service.recover(
            run_id,
            request,
            owner=_owner_scope(user),
            idempotency_key=idempotency_key,
        )
    )
    return ResearchCommandResponse.model_validate(result)


@router.delete(
    "/{run_id}/research-data",
    response_model=ResearchCommandResponse | ResearchV3PurgeResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def purge_research_run_data(
    run_id: str,
    request_body: ResearchPurgeRequest | ResearchV3PurgeRequest,
    user: CurrentUser,
    idempotency_key: IdempotencyKey,
    service: Service,
    request: Request,
) -> ResearchCommandResponse | ResearchV3PurgeResponse:
    if _stored_version(run_id, user) == "research-v3":
        if not isinstance(request_body, ResearchV3PurgeRequest):
            raise HTTPException(status_code=422, detail="Research-v3 purge body is invalid")
        return await _v3_mutate(
            run_id=run_id,
            command_type="purge",
            body=request_body,
            user=user,
            idempotency_key=idempotency_key,
            request=request,
            response_type=ResearchV3PurgeResponse,
        )
    if not isinstance(request_body, ResearchPurgeRequest):
        raise HTTPException(status_code=422, detail="Research-v2 purge body is invalid")
    result = await _service_call(
        lambda: service.purge(
            run_id,
            request_body,
            owner=_owner_scope(user),
            idempotency_key=idempotency_key,
        )
    )
    return ResearchCommandResponse.model_validate(result)


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
