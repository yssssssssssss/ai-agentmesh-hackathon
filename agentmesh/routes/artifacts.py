"""Permission-scoped generated Artifact routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from agentmesh.models import User
from agentmesh.routes.deps import current_user
from agentmesh.store import store

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


@router.get("/{artifact_id}")
def get_artifact(artifact_id: str, user: User = Depends(current_user)) -> Response:
    artifact = store.get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if artifact.user_id != user.id or artifact.workspace_id != user.workspace_id:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return Response(
        content=artifact.content,
        media_type=artifact.content_type,
        headers={"X-AgentMesh-Run-Id": artifact.run_id},
    )
