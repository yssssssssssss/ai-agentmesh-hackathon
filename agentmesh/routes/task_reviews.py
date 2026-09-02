"""Task deliverable review routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from agentmesh.models import User
from agentmesh.routes.deps import current_user
from agentmesh.store import store
from agentmesh.task_review.contracts import (
    TaskReviewDecisionRequest,
    TaskReviewMutationResponseV1,
    TaskReviewSubmitRequest,
)
from agentmesh.task_review.service import TaskCompletionService, TaskReviewError

router = APIRouter(prefix="/api", tags=["task-reviews"])
service = TaskCompletionService(store)


def _http_error(error: TaskReviewError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.code)


@router.post(
    "/tasks/{task_id}/reviews",
    response_model=TaskReviewMutationResponseV1,
    status_code=status.HTTP_201_CREATED,
)
def submit_task_review(
    task_id: str,
    request: TaskReviewSubmitRequest,
    user: User = Depends(current_user),
) -> TaskReviewMutationResponseV1:
    try:
        return service.submit_review(task_id, request, user)
    except TaskReviewError as error:
        raise _http_error(error) from error


@router.get("/task-reviews/{review_id}/artifacts/{artifact_id}")
def inspect_task_review_artifact(
    review_id: str,
    artifact_id: str,
    user: User = Depends(current_user),
) -> Response:
    try:
        artifact = service.get_review_artifact(review_id, artifact_id, user)
    except TaskReviewError as error:
        raise _http_error(error) from error
    headers = {
        "X-AgentMesh-Run-Id": artifact.run_id,
        "X-AgentMesh-Artifact-Hash": artifact.content_hash or "",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Cache-Control": "private, no-store",
    }
    if artifact.content_type in {"text/html", "application/xhtml+xml", "image/svg+xml"}:
        headers["Content-Disposition"] = f'attachment; filename="{artifact.id}.txt"'
    return Response(content=artifact.content, media_type=artifact.content_type, headers=headers)


@router.post(
    "/task-reviews/{review_id}/decisions",
    response_model=TaskReviewMutationResponseV1,
)
def decide_task_review(
    review_id: str,
    request: TaskReviewDecisionRequest,
    user: User = Depends(current_user),
) -> TaskReviewMutationResponseV1:
    try:
        return service.decide_review(review_id, request, user)
    except TaskReviewError as error:
        raise _http_error(error) from error
