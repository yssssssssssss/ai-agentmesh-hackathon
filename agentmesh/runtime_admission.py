"""Process-local runtime admission registry.

The registry gives HTTP routes, Agent Runtime, executors, Tool dispatch, and recovery
one shared quiesce controller without treating request headers or global mode as an
authority. Application startup installs a fresh one-way latch for that process.
"""

from __future__ import annotations

import threading

from agentmesh.skill_runtime.quiesce import OrchestrationQuiesceController

_lock = threading.Lock()
_controller = OrchestrationQuiesceController()


def current_orchestration_admission() -> OrchestrationQuiesceController:
    with _lock:
        return _controller


def install_orchestration_admission(
    controller: OrchestrationQuiesceController,
) -> OrchestrationQuiesceController:
    global _controller
    with _lock:
        _controller = controller
    return controller
