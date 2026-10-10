from __future__ import annotations

from enum import StrEnum

from agentmesh.profiles import env_setting


class MemoryContextMode(StrEnum):
    OFF = "off"
    OBSERVE = "observe"
    INJECT = "inject"


def memory_context_mode() -> MemoryContextMode:
    raw = env_setting("AGENTMESH_MEMORY_CONTEXT", MemoryContextMode.OFF.value).strip().lower()
    try:
        return MemoryContextMode(raw)
    except ValueError:
        return MemoryContextMode.OFF
