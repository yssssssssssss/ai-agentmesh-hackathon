from __future__ import annotations

import os
from enum import StrEnum

from agentmesh.profiles import env_setting


class SkillOrchestrationMode(StrEnum):
    OFF = "off"
    PREVIEW = "preview"
    EXECUTE = "execute"


def agent_runtime_enabled() -> bool:
    return env_setting("AGENTMESH_AGENT_RUNTIME", "legacy").strip().lower() == "v2"


def strict_tools_enabled() -> bool:
    return os.getenv("AGENTMESH_SDK_STRICT_TOOLS", "true").strip().lower() not in {"0", "false", "no", "off"}


def skill_orchestration_mode() -> SkillOrchestrationMode:
    raw = env_setting("AGENTMESH_SKILL_ORCHESTRATION", SkillOrchestrationMode.OFF.value).strip().lower()
    try:
        return SkillOrchestrationMode(raw)
    except ValueError:
        return SkillOrchestrationMode.OFF


def task_scenario_routing_enabled() -> bool:
    return env_setting("AGENTMESH_TASK_SCENARIO_ROUTING", "false").strip().lower() in {"1", "true", "yes", "on"}


def deepsearch_enabled() -> bool:
    return env_setting("AGENTMESH_DEEPSEARCH_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
