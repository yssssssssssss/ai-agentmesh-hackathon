"""HTTP control plane for owner-scoped research-v2 workflows."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Header, HTTPException, status

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
from agentmesh.routes.deps import current_user

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


research_workflow_service: ResearchWorkflowService | None = None


def get_research_workflow_service() -> ResearchWorkflowService:
    if research_workflow_service is None:
        raise HTTPException(status_code=503, detail="Research workflow service is unavailable")
    return research_workflow_service


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


@router.get("/{run_id}/research", response_model=ResearchRunProjection)
async def get_research_run(
    run_id: str,
    user: CurrentUser,
    service: Service,
) -> ResearchRunProjection:
    result = await _service_call(lambda: service.get_projection(run_id, owner=_owner_scope(user)))
    return ResearchRunProjection.model_validate(result)


@router.post(
    "/{run_id}/research/clarify",
    response_model=ResearchCommandResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def clarify_research_run(
    run_id: str,
    request: ResearchClarifyRequest,
    user: CurrentUser,
    idempotency_key: IdempotencyKey,
    service: Service,
) -> ResearchCommandResponse:
    result = await _service_call(
        lambda: service.clarify(
            run_id,
            request,
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
    response_model=ResearchCommandResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def execute_research_run(
    run_id: str,
    request: ResearchExecuteRequest,
    user: CurrentUser,
    idempotency_key: IdempotencyKey,
    service: Service,
) -> ResearchCommandResponse:
    result = await _service_call(
        lambda: service.execute(
            run_id,
            request,
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
    response_model=ResearchCommandResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def purge_research_run_data(
    run_id: str,
    request: ResearchPurgeRequest,
    user: CurrentUser,
    idempotency_key: IdempotencyKey,
    service: Service,
) -> ResearchCommandResponse:
    result = await _service_call(
        lambda: service.purge(
            run_id,
            request,
            owner=_owner_scope(user),
            idempotency_key=idempotency_key,
        )
    )
    return ResearchCommandResponse.model_validate(result)
