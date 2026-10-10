"""Named configuration profiles.

A profile supplies defaults for a group of release flags. An explicitly set
environment variable always wins, and no profile keeps every existing default.
"""

from __future__ import annotations

import os

PROFILE_ENV = "AGENTMESH_PROFILE"

PROFILES: dict[str, dict[str, str]] = {
    # One governed path for an internal pilot (ADR 0053). Multi-Skill orchestration
    # stays off for real users until ADR 0010's production gates pass.
    "pilot": {
        "AGENTMESH_AGENT_RUNTIME": "v2",
        "AGENTMESH_MEMORY_CONTEXT": "inject",
        "AGENTMESH_TASK_MANAGEMENT": "write",
        "AGENTMESH_SKILL_ORCHESTRATION": "off",
        "AGENTMESH_AUTOMATION_MODE": "observe",
    },
}


def _requested_profile() -> str:
    return os.getenv(PROFILE_ENV, "").strip().lower()


def active_profile() -> str | None:
    name = _requested_profile()
    return name if name in PROFILES else None


def validate_profile() -> None:
    name = _requested_profile()
    if name and name not in PROFILES:
        known = ", ".join(sorted(PROFILES))
        raise ValueError(f"unknown {PROFILE_ENV} '{name}'; expected one of: {known}")


def env_setting(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is not None:
        return value
    profile = active_profile()
    if profile is None:
        return default
    return PROFILES[profile].get(name, default)
