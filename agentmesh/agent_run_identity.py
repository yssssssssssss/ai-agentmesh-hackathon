"""Canonical identity for idempotent Agent Run creation."""

from __future__ import annotations

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.models import (
    AgentExecutionContractVersion,
    AgentPlanningContractVersion,
    AgentPlanningMode,
    AgentRun,
    SkillOrchestrationRequestMode,
)


def _enum_value(
    value: str
    | AgentExecutionContractVersion
    | AgentPlanningContractVersion
    | AgentPlanningMode
    | SkillOrchestrationRequestMode
    | None,
) -> str | None:
    enum_types = (
        AgentExecutionContractVersion,
        AgentPlanningContractVersion,
        AgentPlanningMode,
        SkillOrchestrationRequestMode,
    )
    return value.value if isinstance(value, enum_types) else value


def agent_run_create_request_hash(
    *,
    user_id: str,
    thread_id: str,
    client_turn_id: str,
    content: str,
    skill_name: str | None,
    orchestration_mode: str | SkillOrchestrationRequestMode | None,
    planning_mode: str | AgentPlanningMode,
    retry_of_run_id: str | None,
    planning_contract_version: str | AgentPlanningContractVersion | None = None,
    execution_contract_version: str | AgentExecutionContractVersion | None = None,
) -> str:
    """Hash exactly the fields that define one durable create request.

    Contract markers are omitted for legacy runs. Standard Universal includes
    its execution marker even when it is explicitly null, so a Preview Run can
    never be replayed as an execution-capable Run.
    """

    identity = {
        "client_turn_id": client_turn_id,
        "content": content,
        "orchestration_mode": _enum_value(orchestration_mode),
        "planning_mode": _enum_value(planning_mode),
        "retry_of_run_id": retry_of_run_id,
        "skill_name": skill_name,
        "thread_id": thread_id,
        "user_id": user_id,
    }
    planning_contract = _enum_value(planning_contract_version)
    if planning_contract is not None:
        identity["planning_contract_version"] = planning_contract
    if planning_contract == AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1.value:
        identity["execution_contract_version"] = _enum_value(execution_contract_version)
    return canonical_json_sha256(identity)


def expected_agent_run_create_request_hash(run: AgentRun) -> str | None:
    if run.client_turn_id is None:
        return None
    return agent_run_create_request_hash(
        user_id=run.user_id,
        thread_id=run.thread_id,
        client_turn_id=run.client_turn_id,
        content=run.input_text,
        skill_name=run.skill_name,
        orchestration_mode=run.requested_orchestration_mode,
        planning_mode=run.planning_mode,
        retry_of_run_id=run.retry_of_run_id,
        planning_contract_version=run.planning_contract_version,
        execution_contract_version=run.execution_contract_version,
    )


def agent_run_create_request_hash_for_run(run: AgentRun) -> str | None:
    """Compatibility name used at the persistence boundary."""

    return expected_agent_run_create_request_hash(run)


def agent_run_create_request_matches(
    run: AgentRun,
    *,
    create_request_hash: str,
    user_id: str,
    client_turn_id: str,
    thread_id: str,
    content: str,
    skill_id: str | None,
    skill_name: str | None,
    orchestration_mode: str | SkillOrchestrationRequestMode | None,
    planning_mode: str | AgentPlanningMode,
    retry_of_run_id: str | None,
    planning_contract_version: str | AgentPlanningContractVersion | None = None,
    execution_contract_version: str | AgentExecutionContractVersion | None = None,
) -> bool:
    """Compare a replay against either the current hash or a legacy Run payload."""

    if run.create_request_hash is not None:
        return (
            run.create_request_hash == expected_agent_run_create_request_hash(run)
            and run.create_request_hash == create_request_hash
        )
    mode_matches = (
        run.requested_orchestration_mode is None
        or orchestration_mode is None
        or run.requested_orchestration_mode == orchestration_mode
    )
    return bool(
        run.user_id == user_id
        and run.client_turn_id == client_turn_id
        and run.thread_id == thread_id
        and run.input_text == content
        and run.skill_id == skill_id
        and run.skill_name == skill_name
        and run.planning_mode == planning_mode
        and run.planning_contract_version == planning_contract_version
        and run.execution_contract_version == execution_contract_version
        and run.retry_of_run_id == retry_of_run_id
        and mode_matches
    )


def with_validated_create_request_hash(run: AgentRun) -> AgentRun:
    """Populate a new Run hash, or reject a caller-supplied mismatched hash."""

    expected = expected_agent_run_create_request_hash(run)
    if expected is None:
        if run.create_request_hash is not None:
            raise RuntimeError("create_request_hash requires client_turn_id")
        return run
    if run.create_request_hash is not None and run.create_request_hash != expected:
        raise RuntimeError("create_request_hash does not match the Agent run request")
    if run.create_request_hash == expected:
        return run
    return run.model_copy(update={"create_request_hash": expected})
