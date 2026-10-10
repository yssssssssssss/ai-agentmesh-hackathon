"""Project Task operations read-model routes."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from agentmesh.automation.contracts import ProjectInspectionReportV1, ProjectInspectionRequestV1
from agentmesh.automation.service import ProjectInspectionService
from agentmesh.models import User, now_utc
from agentmesh.routes.deps import current_user
from agentmesh.store import store
from agentmesh.task_operations.contracts import (
    ProjectStateQueryV1,
    ProjectStateResultV1,
    TaskOperationsSnapshotV1,
    TaskOptionPageV1,
)
from agentmesh.task_operations.service import (
    TaskOperationsError,
    TaskOperationsQuery,
    TaskOperationsService,
    TaskOptionQuery,
)
from agentmesh.task_operations.state import ProjectStateService

router = APIRouter(prefix="/api/task-operations", tags=["task-operations"])


def _http_error(error: TaskOperationsError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.code)


@router.get("/{project_id}/state", response_model=ProjectStateResultV1)
def project_current_state(
    project_id: str, task_id: str | None = Query(default=None, min_length=1, max_length=120),
    user: User = Depends(current_user),
) -> ProjectStateResultV1:
    try:
        return ProjectStateService(store).query(ProjectStateQueryV1(project_id=project_id, task_id=task_id), user)
    except TaskOperationsError as error:
        raise _http_error(error) from error


@router.post("/{project_id}/inspections", response_model=ProjectInspectionReportV1)
def inspect_project(
    project_id: str, request: ProjectInspectionRequestV1, user: User = Depends(current_user),
) -> ProjectInspectionReportV1:
    try:
        return ProjectInspectionService(store).inspect(project_id, request, user)
    except TaskOperationsError as error:
        raise _http_error(error) from error


@router.get("/{project_id}", response_model=TaskOperationsSnapshotV1)
def project_task_operations(
    project_id: str,
    calendar_start: datetime | None = Query(default=None),
    calendar_end: datetime | None = Query(default=None),
    calendar_page: int = Query(default=1, ge=1),
    calendar_page_size: int = Query(default=50, ge=1, le=100),
    queue_page: int = Query(default=1, ge=1),
    queue_page_size: int = Query(default=50, ge=1, le=100),
    queue_agent_id: str | None = Query(default=None, max_length=120),
    user: User = Depends(current_user),
) -> TaskOperationsSnapshotV1:
    now = now_utc()
    start = calendar_start or now - timedelta(days=7)
    end = calendar_end or now + timedelta(days=60)
    try:
        return TaskOperationsService(store).snapshot(
            TaskOperationsQuery(
                project_id=project_id,
                calendar_start=start,
                calendar_end=end,
                calendar_page=calendar_page,
                calendar_page_size=calendar_page_size,
                queue_page=queue_page,
                queue_page_size=queue_page_size,
                queue_agent_id=queue_agent_id,
            ),
            user,
        )
    except TaskOperationsError as error:
        raise _http_error(error) from error


@router.get("/{project_id}/task-options", response_model=TaskOptionPageV1)
def project_task_options(
    project_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    query: str | None = Query(default=None, max_length=200),
    exclude_task_id: str | None = Query(default=None, max_length=120),
    user: User = Depends(current_user),
) -> TaskOptionPageV1:
    try:
        return TaskOperationsService(store).task_options(
            TaskOptionQuery(
                project_id=project_id,
                page=page,
                page_size=page_size,
                query=query,
                exclude_task_id=exclude_task_id,
            ),
            user,
        )
    except TaskOperationsError as error:
        raise _http_error(error) from error
