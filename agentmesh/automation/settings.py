from __future__ import annotations

import os
from typing import Literal


def automation_mode() -> Literal["off", "observe", "execute"]:
    raw = os.getenv("AGENTMESH_AUTOMATION_MODE", "off").strip().lower()
    return raw if raw in {"observe", "execute"} else "off"
