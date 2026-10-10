from __future__ import annotations

from typing import Literal

from agentmesh.profiles import env_setting


def automation_mode() -> Literal["off", "observe", "execute"]:
    raw = env_setting("AGENTMESH_AUTOMATION_MODE", "off").strip().lower()
    return raw if raw in {"observe", "execute"} else "off"
