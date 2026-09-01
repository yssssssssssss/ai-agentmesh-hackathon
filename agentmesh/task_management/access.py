from __future__ import annotations

from typing import TYPE_CHECKING

from agentmesh.models import Task, TaskAssigneeKind, User

if TYPE_CHECKING:
    from agentmesh.store import SQLiteStore


def task_assigned_to_user(task: Task, user: User, repository: SQLiteStore) -> bool:
    management = task.management
    if management is None or management.assignee_id is None:
        return False
    if management.assignee_kind == TaskAssigneeKind.USER:
        return management.assignee_id == user.id
    if management.assignee_kind != TaskAssigneeKind.AGENT:
        return False
    if management.assignee_id == user.personal_agent_id:
        return True
    agent = repository.get_agent(management.assignee_id)
    return agent is not None and agent.owner_user_id == user.id
