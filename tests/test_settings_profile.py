from __future__ import annotations

import os

import pytest

from agentmesh.agent_runtime.settings import (
    SkillOrchestrationMode,
    agent_runtime_enabled,
    deepsearch_enabled,
    skill_orchestration_mode,
    task_scenario_routing_enabled,
)
from agentmesh.automation.settings import automation_mode
from agentmesh.memory_context.settings import MemoryContextMode, memory_context_mode
from agentmesh.profiles import PROFILE_ENV, PROFILES, active_profile, validate_profile
from agentmesh.task_management.settings import TaskManagementMode, task_management_mode

PROFILE_FLAGS = (
    "AGENTMESH_AGENT_RUNTIME",
    "AGENTMESH_SKILL_ORCHESTRATION",
    "AGENTMESH_TASK_MANAGEMENT",
    "AGENTMESH_MEMORY_CONTEXT",
    "AGENTMESH_AUTOMATION_MODE",
    "AGENTMESH_TASK_SCENARIO_ROUTING",
    "AGENTMESH_DEEPSEARCH_ENABLED",
)


@pytest.fixture
def clean_flags(monkeypatch):
    monkeypatch.delenv(PROFILE_ENV, raising=False)
    for name in PROFILE_FLAGS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_without_profile_every_flag_keeps_its_existing_default(clean_flags) -> None:
    assert active_profile() is None
    assert agent_runtime_enabled() is False
    assert skill_orchestration_mode() is SkillOrchestrationMode.OFF
    assert task_management_mode() is TaskManagementMode.READ_ONLY
    assert memory_context_mode() is MemoryContextMode.OFF
    assert automation_mode() == "off"
    assert task_scenario_routing_enabled() is False
    assert deepsearch_enabled() is False


def test_pilot_profile_enables_the_single_pilot_path(clean_flags) -> None:
    clean_flags.setenv(PROFILE_ENV, "pilot")

    assert active_profile() == "pilot"
    assert agent_runtime_enabled() is True
    assert memory_context_mode() is MemoryContextMode.INJECT
    assert task_management_mode() is TaskManagementMode.WRITE
    assert automation_mode() == "observe"


def test_pilot_profile_keeps_unreleased_capabilities_off(clean_flags) -> None:
    clean_flags.setenv(PROFILE_ENV, "pilot")

    assert skill_orchestration_mode() is SkillOrchestrationMode.OFF
    assert task_scenario_routing_enabled() is False
    assert deepsearch_enabled() is False


def test_explicit_flag_overrides_the_profile(clean_flags) -> None:
    clean_flags.setenv(PROFILE_ENV, "pilot")
    clean_flags.setenv("AGENTMESH_MEMORY_CONTEXT", "observe")
    clean_flags.setenv("AGENTMESH_AGENT_RUNTIME", "legacy")

    assert memory_context_mode() is MemoryContextMode.OBSERVE
    assert agent_runtime_enabled() is False
    assert task_management_mode() is TaskManagementMode.WRITE


def test_profile_name_is_case_and_whitespace_insensitive(clean_flags) -> None:
    clean_flags.setenv(PROFILE_ENV, "  Pilot ")

    assert active_profile() == "pilot"
    assert agent_runtime_enabled() is True


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_profile_means_no_profile(clean_flags, blank: str) -> None:
    clean_flags.setenv(PROFILE_ENV, blank)

    assert active_profile() is None
    validate_profile()
    assert agent_runtime_enabled() is False


def test_unknown_profile_fails_startup_validation(clean_flags) -> None:
    clean_flags.setenv(PROFILE_ENV, "prod")

    with pytest.raises(ValueError, match="unknown AGENTMESH_PROFILE 'prod'"):
        validate_profile()


def test_unknown_profile_falls_back_to_defaults_at_runtime(clean_flags) -> None:
    clean_flags.setenv(PROFILE_ENV, "prod")

    assert active_profile() is None
    assert agent_runtime_enabled() is False
    assert task_management_mode() is TaskManagementMode.READ_ONLY


def test_pilot_profile_matches_the_closed_loop_evaluation_except_gated_orchestration(clean_flags) -> None:
    """The pilot runs what the closed-loop evaluation measures; orchestration differs only per ADR 0010."""
    from eval.closed_loop import runner

    with runner._evaluation_environment():
        evaluated = {name: os.environ[name] for name in PROFILES["pilot"] if name in os.environ}

    differing = {name for name in evaluated if evaluated[name] != PROFILES["pilot"][name]}
    assert "AGENTMESH_MEMORY_CONTEXT" in evaluated
    assert "AGENTMESH_TASK_MANAGEMENT" in evaluated
    assert differing == {"AGENTMESH_SKILL_ORCHESTRATION"}
