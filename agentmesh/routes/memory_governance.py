"""Governed Memory read and review routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from agentmesh.memory_governance.contracts import (
    MemoryEntryViewV1,
    MemoryLineageViewV1,
    MemoryPageV1,
    MemoryReviewDecisionRequest,
    MemoryReviewDecisionResponseV1,
)
from agentmesh.memory_governance.service import (
    MemoryGovernanceError,
    MemoryGovernanceService,
    MemoryListQuery,
)
from agentmesh.models import User
from agentmesh.routes.deps import current_user
from agentmesh.store import store

router = APIRouter(prefix="/api", tags=["memory-governance"])
service = MemoryGovernanceService(store)


def _http_error(error: MemoryGovernanceError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.code)


@router.get("/memory/entries", response_model=MemoryPageV1)
def list_memory_entries(
    project_id: str | None = Query(default=None, min_length=1, max_length=120),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    include_archived: bool = Query(default=False),
    user: User = Depends(current_user),
) -> MemoryPageV1:
    try:
        return service.list_entries(
            MemoryListQuery(
                project_id=project_id or user.default_project_id,
                page=page,
                page_size=page_size,
                include_archived=include_archived,
            ),
            user,
        )
    except MemoryGovernanceError as error:
        raise _http_error(error) from error


@router.get("/memory/entries/{memory_id}", response_model=MemoryEntryViewV1)
def get_memory_entry(
    memory_id: str,
    user: User = Depends(current_user),
) -> MemoryEntryViewV1:
    try:
        return service.get_lineage(memory_id, user).item
    except MemoryGovernanceError as error:
        raise _http_error(error) from error


@router.get("/memory/entries/{memory_id}/lineage", response_model=MemoryLineageViewV1)
def get_memory_lineage(
    memory_id: str,
    user: User = Depends(current_user),
) -> MemoryLineageViewV1:
    try:
        return service.get_lineage(memory_id, user)
    except MemoryGovernanceError as error:
        raise _http_error(error) from error


@router.post(
    "/memory-reviews/{review_id}/decisions",
    response_model=MemoryReviewDecisionResponseV1,
)
def decide_memory_review(
    review_id: str,
    request: MemoryReviewDecisionRequest,
    user: User = Depends(current_user),
) -> MemoryReviewDecisionResponseV1:
    try:
        return service.decide_memory_review(review_id, request, user)
    except MemoryGovernanceError as error:
        raise _http_error(error) from error
