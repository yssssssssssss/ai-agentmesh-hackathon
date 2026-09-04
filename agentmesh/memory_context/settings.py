from __future__ import annotations

import os
from enum import StrEnum


class MemoryContextMode(StrEnum):
    OFF = "off"
    OBSERVE = "observe"
    INJECT = "inject"


def memory_context_mode() -> MemoryContextMode:
    raw = os.getenv("AGENTMESH_MEMORY_CONTEXT", MemoryContextMode.OFF.value).strip().lower()
    try:
        return MemoryContextMode(raw)
    except ValueError:
        return MemoryContextMode.OFF
