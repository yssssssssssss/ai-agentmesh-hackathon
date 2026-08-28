"""Read-only routes for historical research-v2 runs."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from agentmesh.models import User
from agentmesh.research_orchestration.api import (
    ResearchConflictError,
    ResearchNotFoundError,
    ResearchOwnerScope,
    ResearchRunProjection,
)
from agentmesh.research_orchestration.v2_history import V2HistoryReader
from agentmesh.routes.deps import current_user

router = APIRouter(prefix="/api/agent/runs", tags=["research"])


def get_v2_history_reader(request: Request) -> V2HistoryReader:
    reader = getattr(request.app.state, "research_v2_history_reader", None)
    if reader is None or not callable(getattr(reader, "get_projection", None)):
        raise HTTPException(status_code=503, detail="Research history reader is unavailable")
    return reader


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
        raise HTTPException(status_code=409, detail=str(error) or "Research history conflict") from None


@router.get("/{run_id}/research", response_model=ResearchRunProjection)
async def get_research_run(
    run_id: str,
    user: CurrentUser,
    request: Request,
) -> ResearchRunProjection:
    reader = get_v2_history_reader(request)
    result = await _service_call(lambda: reader.get_projection(run_id, owner=_owner_scope(user)))
    return ResearchRunProjection.model_validate(result)
