from __future__ import annotations

from datetime import datetime

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.memory_governance.contracts import MemoryLifecycleAction
from agentmesh.models import MemoryItem, MemoryStatus, Scope, UserMemoryItem


class MemoryLifecycleConflict(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def memory_content_hash(item: MemoryItem | UserMemoryItem) -> str:
    """Hash immutable Memory content while excluding mutable lifecycle fields."""
    if isinstance(item, UserMemoryItem):
        payload = {
            "schema_version": "user-memory-content-v1",
            "id": item.id,
            "title": item.title,
            "summary": item.summary,
            "memory_type": item.memory_type,
            "user_id": item.user_id,
            "workspace_id": item.workspace_id,
            "project_id": item.project_id,
            "layer": item.layer,
            "sources": [source.model_dump(mode="json") for source in item.sources],
            "provenance": item.provenance.model_dump(mode="json") if item.provenance is not None else None,
            "created_at": item.created_at,
        }
    else:
        payload = {
            "schema_version": "memory-content-v1",
            "id": item.id,
            "title": item.title,
            "summary": item.summary,
            "memory_type": item.memory_type,
            "owner_user_id": item.owner_user_id,
            "workspace_id": item.workspace_id,
            "project_id": item.project_id,
            "team_id": item.team_id,
            "sources": [source.model_dump(mode="json") for source in item.sources],
            "metadata": item.metadata,
            "provenance": item.provenance.model_dump(mode="json") if item.provenance is not None else None,
            "created_at": item.created_at,
        }
    return canonical_json_sha256(payload)


def transition_memory_item(
    item: MemoryItem,
    *,
    action: MemoryLifecycleAction,
    actor_id: str,
    changed_at: datetime,
) -> MemoryItem:
    if item.provenance is None:
        raise MemoryLifecycleConflict("memory_governance_required")
    if item.scope not in {Scope.TEAM_CANDIDATE, Scope.TEAM_ACCEPTED}:
        raise MemoryLifecycleConflict("memory_lifecycle_transition_invalid")

    allowed_statuses = {
        MemoryLifecycleAction.DISPUTE: {MemoryStatus.ACCEPTED},
        MemoryLifecycleAction.DEPRECATE: {MemoryStatus.ACCEPTED, MemoryStatus.DISPUTED},
        MemoryLifecycleAction.EXPIRE: {
            MemoryStatus.PROPOSED,
            MemoryStatus.ACCEPTED,
            MemoryStatus.DISPUTED,
        },
        MemoryLifecycleAction.ARCHIVE: {
            MemoryStatus.ACCEPTED,
            MemoryStatus.DISPUTED,
            MemoryStatus.DEPRECATED,
            MemoryStatus.EXPIRED,
        },
    }

    updated = item.model_copy(deep=True)
    if action is MemoryLifecycleAction.RESTORE:
        if item.status is not MemoryStatus.ARCHIVED or item.archived_from_status not in {
            MemoryStatus.ACCEPTED,
            MemoryStatus.DISPUTED,
            MemoryStatus.DEPRECATED,
            MemoryStatus.EXPIRED,
        }:
            raise MemoryLifecycleConflict("memory_lifecycle_transition_invalid")
        updated.status = item.archived_from_status
        updated.archived_at = None
        updated.archived_by = None
        updated.archived_from_status = None
    else:
        if item.status not in allowed_statuses[action]:
            raise MemoryLifecycleConflict("memory_lifecycle_transition_invalid")
        if action is MemoryLifecycleAction.DISPUTE:
            updated.status = MemoryStatus.DISPUTED
        elif action is MemoryLifecycleAction.DEPRECATE:
            updated.status = MemoryStatus.DEPRECATED
        elif action is MemoryLifecycleAction.EXPIRE:
            updated.status = MemoryStatus.EXPIRED
        elif action is MemoryLifecycleAction.ARCHIVE:
            updated.archived_from_status = item.status
            updated.archived_at = changed_at
            updated.archived_by = actor_id
            updated.status = MemoryStatus.ARCHIVED

    updated.version = item.version + 1
    updated.updated_at = changed_at
    return updated
