"""Single source of truth for DeepSearch creation admission."""

from __future__ import annotations

from collections import Counter
from typing import Protocol

from agentmesh.agent_runtime.settings import deepsearch_enabled, skill_orchestration_mode
from agentmesh.models import DeepSearchAvailability, DeepSearchAvailabilityReason, User

_ADMISSION_REJECTIONS: Counter[str] = Counter()


def record_deepsearch_admission_rejection(reason_code: str) -> None:
    """Record one secret-safe process-local admission rejection."""

    stable_code = reason_code.removeprefix("deepsearch_")
    allowed = {reason.value for reason in DeepSearchAvailabilityReason}
    _ADMISSION_REJECTIONS[stable_code if stable_code in allowed else "unknown"] += 1


def deepsearch_admission_rejections() -> dict[str, int]:
    return dict(sorted(_ADMISSION_REJECTIONS.items()))


class _RuntimeProbe(Protocol):
    @property
    def enabled(self) -> bool: ...

    def select_model(self, user: User) -> object | None: ...


def evaluate_deepsearch_availability(
    *,
    runtime: _RuntimeProbe | None,
    user: User,
) -> DeepSearchAvailability:
    """Evaluate creation readiness without exposing provider configuration."""

    enabled = deepsearch_enabled()
    runtime_mode = skill_orchestration_mode()
    runtime_ready = runtime is not None and runtime.enabled
    model_ready = False
    if runtime_ready:
        select_model = getattr(runtime, "select_model", None)
        if callable(select_model):
            try:
                model_ready = select_model(user) is not None
            except (KeyError, TypeError, ValueError):
                model_ready = False
    planner_ready = model_ready and callable(getattr(runtime, "start_deepsearch", None))
    core_ready = runtime_ready and model_ready and planner_ready

    reason: DeepSearchAvailabilityReason | None = None
    if not enabled:
        reason = DeepSearchAvailabilityReason.DISABLED
    elif runtime_mode.value != "execute":
        reason = DeepSearchAvailabilityReason.EXECUTION_UNAVAILABLE
    elif not runtime_ready:
        reason = DeepSearchAvailabilityReason.RUNTIME_UNAVAILABLE
    elif not model_ready:
        reason = DeepSearchAvailabilityReason.MODEL_UNAVAILABLE
    elif not planner_ready:
        reason = DeepSearchAvailabilityReason.PLANNER_UNAVAILABLE

    return DeepSearchAvailability(
        available=reason is None,
        enabled=enabled,
        runtime_mode=runtime_mode.value,
        core_ready=core_ready,
        reason_code=reason,
    )
