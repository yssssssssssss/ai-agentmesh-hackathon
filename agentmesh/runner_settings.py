from __future__ import annotations

import os
from typing import Literal

RunnerExecutionLocation = Literal["server", "runner"]


def execution_location() -> RunnerExecutionLocation:
    value = os.getenv("AGENTMESH_EXECUTION_LOCATION", "server").strip().lower()
    return "runner" if value == "runner" else "server"


def remote_runner_enabled() -> bool:
    return execution_location() == "runner"
