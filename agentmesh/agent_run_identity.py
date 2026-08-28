"""Canonical identity for idempotent Agent Run creation."""

from __future__ import annotations

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.models import AgentPlanningMode, AgentRun, SkillOrchestrationRequestMode


def _enum_value(value: str | AgentPlanningMode | SkillOrchestrationRequestMode | None) -> str | None:
    return value.value if isinstance(value, (AgentPlanningMode, SkillOrchestrationRequestMode)) else value


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
) -> str:
    """Hash exactly the fields that define one durable create request."""

    return canonical_json_sha256(
        {
            "client_turn_id": client_turn_id,
            "content": content,
            "orchestration_mode": _enum_value(orchestration_mode),
            "planning_mode": _enum_value(planning_mode),
            "retry_of_run_id": retry_of_run_id,
            "skill_name": skill_name,
            "thread_id": thread_id,
            "user_id": user_id,
        }
    )


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
) -> bool:
    """Compare a replay against either the new hash or a legacy Run payload."""

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
