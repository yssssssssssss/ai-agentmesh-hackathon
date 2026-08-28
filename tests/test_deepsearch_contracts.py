from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentmesh.app import app
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunCreateRequest,
    AgentRunStatus,
    DeepSearchAvailability,
    DeepSearchBudgetV1,
)


def test_agent_run_create_request_defaults_to_standard_planning() -> None:
    request = AgentRunCreateRequest(content="keep the existing path", client_turn_id="turn_contract_default")

    assert request.planning_mode == AgentPlanningMode.STANDARD
    assert request.model_dump(mode="json")["planning_mode"] == "standard"


def test_legacy_agent_run_payload_gets_only_backward_compatible_deepsearch_defaults() -> None:
    run = AgentRun.model_validate(
        {
            "id": "run_legacy_contract",
            "thread_id": "thread_legacy_contract",
            "user_id": "user_legacy_contract",
            "workspace_id": "workspace_legacy_contract",
            "project_id": "project_legacy_contract",
            "input_text": "legacy payload",
        }
    )

    assert run.planning_mode == AgentPlanningMode.STANDARD
    assert run.create_request_hash is None
    assert run.interaction_expires_at is None
    assert run.absolute_expires_at is None
    assert run.deepsearch_budget is None
    assert run.orchestration_version == "v1"


def test_waiting_clarification_is_a_first_class_agent_run_status() -> None:
    run = AgentRun(
        thread_id="thread_waiting_clarification_contract",
        user_id="user_waiting_clarification_contract",
        workspace_id="workspace_waiting_clarification_contract",
        project_id="project_waiting_clarification_contract",
        input_text="clarify this goal",
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        status=AgentRunStatus.WAITING_CLARIFICATION,
    )

    assert run.model_dump(mode="json")["status"] == "waiting_clarification"


def test_deepsearch_availability_contract_contains_only_secret_safe_fields() -> None:
    availability = DeepSearchAvailability(
        available=False,
        enabled=True,
        runtime_mode="execute",
        core_ready=False,
        reason_code="planner_unavailable",
    )

    assert availability.model_dump(mode="json") == {
        "available": False,
        "enabled": True,
        "runtime_mode": "execute",
        "core_ready": False,
        "reason_code": "planner_unavailable",
    }


def test_deepsearch_budget_contract_is_strict_and_uses_fixed_limits() -> None:
    budget = DeepSearchBudgetV1()

    assert budget.limits.tokens == 250000
    assert budget.finalization_reserve.active_seconds == 300
    with pytest.raises(ValidationError):
        DeepSearchBudgetV1.model_validate({"unexpected": True})
    with pytest.raises(ValidationError):
        DeepSearchBudgetV1.model_validate({"consumed": {"tokens": 250001}})


def test_openapi_adds_deepsearch_without_making_old_request_fields_invalid() -> None:
    schemas = app.openapi()["components"]["schemas"]
    create_schema = schemas["AgentRunCreateRequest"]
    run_schema = schemas["AgentRun"]

    assert set(create_schema["required"]) == {"content", "client_turn_id"}
    assert create_schema["properties"]["planning_mode"]["default"] == "standard"
    assert "planning_mode" not in run_schema.get("required", [])
    assert {
        "planning_mode",
        "create_request_hash",
        "interaction_expires_at",
        "absolute_expires_at",
        "deepsearch_budget",
    } <= set(run_schema["properties"])
    assert "waiting_clarification" in schemas["AgentRunStatus"]["enum"]
    assert "deepsearch_availability" in schemas["BootstrapState"]["properties"]
