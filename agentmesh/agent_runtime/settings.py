from __future__ import annotations

import os


def strict_tools_enabled() -> bool:
    return os.getenv("AGENTMESH_SDK_STRICT_TOOLS", "true").strip().lower() not in {"0", "false", "no", "off"}
