"""Current Task/Review authority, independent of historical Memory retrieval."""
from __future__ import annotations

from typing import TYPE_CHECKING

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.models import User
from agentmesh.task_operations.contracts import ProjectStateQueryV1, ProjectStateResultV1
from agentmesh.task_operations.service import TaskOperationsError

if TYPE_CHECKING:
    from agentmesh.store import SQLiteStore


class ProjectStateService:
    def __init__(self, repository: SQLiteStore):
        self.repository = repository

    def query(self, request: ProjectStateQueryV1, user: User) -> ProjectStateResultV1:
        result = self.repository.read_project_state(
            user_id=user.id, workspace_id=user.workspace_id,
            project_id=request.project_id or user.default_project_id, task_id=request.task_id,
        )
        if result is None:
            raise TaskOperationsError('project_not_found', status_code=404)
        return result


def project_state_hash(result: ProjectStateResultV1) -> str:
    # The read clock is diagnostic, not the identity of the current result.
    return canonical_json_sha256(result.model_dump(mode='json', exclude={'snapshot_at'}))
