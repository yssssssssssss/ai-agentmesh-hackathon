"""Governed Memory read and review routes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from agentmesh.memory_governance.contracts import (
    MemoryEntryKind,
    MemoryEntryViewV1,
    MemoryLineageViewV1,
    MemoryPageV1,
    MemoryReviewDecisionRequest,
    MemoryReviewDecisionResponseV1,
    MemoryRevisionRequest,
    MemoryRevisionResponseV1,
    MemoryTransitionRequest,
    MemoryTransitionResponseV1,
)
from agentmesh.memory_governance.service import (
    MemoryGovernanceError,
    MemoryGovernanceService,
    MemoryListQuery,
)
from agentmesh.models import MemoryLayer, MemoryStatus, Scope, User
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
    lifecycle: Literal["inactive"] | None = Query(default=None),
    kind: MemoryEntryKind | None = Query(default=None),
    status: MemoryStatus | Literal["active"] | None = Query(default=None),
    scope: Scope | None = Query(default=None),
    layer: MemoryLayer | None = Query(default=None),
    user: User = Depends(current_user),
) -> MemoryPageV1:
    try:
        return service.list_entries(
            MemoryListQuery(
                project_id=project_id or user.default_project_id,
                page=page,
                page_size=page_size,
                include_archived=include_archived,
                inactive_only=lifecycle == "inactive",
                kind=kind,
                status=status,
                scope=scope,
                layer=layer,
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
    "/memory/{memory_id}/revisions",
    response_model=MemoryRevisionResponseV1,
    status_code=201,
)
def create_memory_revision(
    memory_id: str,
    request: MemoryRevisionRequest,
    user: User = Depends(current_user),
) -> MemoryRevisionResponseV1:
    try:
        return service.create_revision(memory_id, request, user)
    except MemoryGovernanceError as error:
        raise _http_error(error) from error


@router.post(
    "/memory/{memory_id}/transitions",
    response_model=MemoryTransitionResponseV1,
)
def transition_memory(
    memory_id: str,
    request: MemoryTransitionRequest,
    user: User = Depends(current_user),
) -> MemoryTransitionResponseV1:
    try:
        return service.transition_memory(memory_id, request, user)
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
