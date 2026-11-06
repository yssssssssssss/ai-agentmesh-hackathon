"""Task-local delivery check at the model adapter's actual capacity handoff."""
from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentmesh.agent_runtime.budget import RunModelBudgetMeter

# SDK request/retry tasks inherit context; concurrent Runs retain distinct gates.
model_handoff_gate: ContextVar[Callable[..., dict] | None] = ContextVar('agentmesh_model_handoff', default=None)
run_model_meter: ContextVar[tuple[RunModelBudgetMeter, Callable[..., dict]] | None] = ContextVar(
    'agentmesh_run_model_meter', default=None,
)
