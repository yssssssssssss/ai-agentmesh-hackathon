"""Permission-scoped generated Artifact routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from agentmesh.artifacts import (
    ArtifactAccessError,
    ArtifactAccessScope,
    V1ArtifactReader,
    resolve_artifact_runtime,
)
from agentmesh.models import User
from agentmesh.research_orchestration.v2_artifact_history import (
    ArtifactReaderScope,
    ArtifactStoreError,
    V2ArtifactHistoryReader,
)
from agentmesh.routes.deps import current_user
from agentmesh.store import store

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])
v1_artifact_reader = V1ArtifactReader(store)
v2_artifact_reader = V2ArtifactHistoryReader(store)


@router.get("/{artifact_id}")
def get_artifact(artifact_id: str, user: User = Depends(current_user)) -> Response:
    access_scope = ArtifactAccessScope(user_id=user.id, workspace_id=user.workspace_id)
    try:
        runtime = resolve_artifact_runtime(store, artifact_id, reader_scope=access_scope)
        if runtime == "research-v2":
            artifact, verified = v2_artifact_reader.read_for_owner(
                artifact_id,
                reader_scope=ArtifactReaderScope(user_id=user.id, workspace_id=user.workspace_id),
                invalidate_corrupt=False,
            )
        else:
            artifact = v1_artifact_reader.read_for_owner(artifact_id, reader_scope=access_scope)
            verified = runtime == "v1_verified"
    except (ArtifactAccessError, ArtifactStoreError) as error:
        if error.code == "artifact_not_found":
            raise HTTPException(status_code=404, detail="Artifact not found") from None
        raise HTTPException(status_code=409, detail=error.code) from None
    headers = {
        "X-AgentMesh-Run-Id": artifact.run_id,
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    }
    if verified:
        headers["X-AgentMesh-Artifact-Hash"] = artifact.content_hash or ""
    if artifact.content_type in {"text/html", "application/xhtml+xml", "image/svg+xml"}:
        headers["Content-Disposition"] = f'attachment; filename="{artifact.id}.txt"'
    return Response(
        content=artifact.content,
        media_type=artifact.content_type,
        headers=headers,
    )
