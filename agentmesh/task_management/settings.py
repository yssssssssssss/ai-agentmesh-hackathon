"""Task management settings."""

from __future__ import annotations

from enum import StrEnum

from agentmesh.profiles import env_setting


class TaskManagementMode(StrEnum):
    READ_ONLY = "read_only"
    WRITE = "write"


def task_management_mode() -> TaskManagementMode:
    raw = env_setting("AGENTMESH_TASK_MANAGEMENT", TaskManagementMode.READ_ONLY.value).strip().lower()
    try:
        return TaskManagementMode(raw)
    except ValueError:
        return TaskManagementMode.READ_ONLY
