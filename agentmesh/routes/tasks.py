"""Project task management routes."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from agentmesh.models import TaskAssigneeKind, TaskDeliveryStage, TaskPriority, User
from agentmesh.routes.deps import current_user
from agentmesh.store import store
from agentmesh.task_management.contracts import (
    TaskArchiveRequest,
    TaskCreateRequest,
    TaskManagementDetailV1,
    TaskManagementItemResponse,
    TaskManagementPageV1,
    TaskTransitionRequest,
    TaskUpdateRequest,
)
from agentmesh.task_management.service import TaskListQuery, TaskManagementError, TaskManagementService

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
service = TaskManagementService(store)


def _http_error(error: TaskManagementError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.code)


@router.get("", response_model=TaskManagementPageV1)
def list_tasks(
    project_id: str | None = Query(default=None, min_length=1, max_length=120),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    include_archived: bool = Query(default=False),
    delivery_stage: TaskDeliveryStage | None = Query(default=None),
    priority: TaskPriority | None = Query(default=None),
    assignee_kind: TaskAssigneeKind | None = Query(default=None),
    assignee_id: str | None = Query(default=None, max_length=120),
    due_before: datetime | None = Query(default=None),
    due_after: datetime | None = Query(default=None),
    query: str | None = Query(default=None, max_length=200),
    user: User = Depends(current_user),
) -> TaskManagementPageV1:
    try:
        return service.list_tasks(
            TaskListQuery(
                project_id=project_id or user.default_project_id,
                page=page,
                page_size=page_size,
                include_archived=include_archived,
                delivery_stage=delivery_stage,
                priority=priority,
                assignee_kind=assignee_kind,
                assignee_id=assignee_id,
                due_before=due_before,
                due_after=due_after,
                query=query,
            ),
            user,
        )
    except TaskManagementError as error:
        raise _http_error(error) from error


@router.post("", response_model=TaskManagementItemResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    request: TaskCreateRequest,
    user: User = Depends(current_user),
) -> TaskManagementItemResponse:
    try:
        return TaskManagementItemResponse(item=service.create_task(request, user))
    except TaskManagementError as error:
        raise _http_error(error) from error


@router.get("/{task_id}", response_model=TaskManagementDetailV1)
def get_task(task_id: str, user: User = Depends(current_user)) -> TaskManagementDetailV1:
    try:
        return TaskManagementDetailV1(item=service.get_task(task_id, user))
    except TaskManagementError as error:
        raise _http_error(error) from error


@router.patch("/{task_id}", response_model=TaskManagementItemResponse)
def update_task(
    task_id: str,
    request: TaskUpdateRequest,
    user: User = Depends(current_user),
) -> TaskManagementItemResponse:
    try:
        return TaskManagementItemResponse(item=service.update_task(task_id, request, user))
    except TaskManagementError as error:
        raise _http_error(error) from error


@router.post("/{task_id}/transitions", response_model=TaskManagementItemResponse)
def transition_task(
    task_id: str,
    request: TaskTransitionRequest,
    user: User = Depends(current_user),
) -> TaskManagementItemResponse:
    try:
        return TaskManagementItemResponse(item=service.transition_task(task_id, request, user))
    except TaskManagementError as error:
        raise _http_error(error) from error


@router.post("/{task_id}/archive", response_model=TaskManagementItemResponse)
def archive_task(
    task_id: str,
    request: TaskArchiveRequest,
    user: User = Depends(current_user),
) -> TaskManagementItemResponse:
    try:
        return TaskManagementItemResponse(item=service.archive_task(task_id, request, user))
    except TaskManagementError as error:
        raise _http_error(error) from error
