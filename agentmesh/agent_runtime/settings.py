from __future__ import annotations

import os
from enum import StrEnum


class SkillOrchestrationMode(StrEnum):
    OFF = "off"
    PREVIEW = "preview"
    EXECUTE = "execute"


def agent_runtime_enabled() -> bool:
    return os.getenv("AGENTMESH_AGENT_RUNTIME", "legacy").strip().lower() == "v2"


def strict_tools_enabled() -> bool:
    return os.getenv("AGENTMESH_SDK_STRICT_TOOLS", "true").strip().lower() not in {"0", "false", "no", "off"}


def skill_orchestration_mode() -> SkillOrchestrationMode:
    raw = os.getenv("AGENTMESH_SKILL_ORCHESTRATION", SkillOrchestrationMode.OFF.value).strip().lower()
    try:
        return SkillOrchestrationMode(raw)
    except ValueError:
        return SkillOrchestrationMode.OFF


def research_preview_allowlist() -> frozenset[str]:
    from agentmesh.research_orchestration.current import parse_research_preview_allowlist

    return parse_research_preview_allowlist(os.getenv("AGENTMESH_RESEARCH_PREVIEW_ALLOWLIST", ""))
