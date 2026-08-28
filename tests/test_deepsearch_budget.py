from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from agentmesh.deepsearch.budget import DeepSearchBudgetMeter
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    DeepSearchBudgetUsageV1,
    DeepSearchBudgetV1,
    SkillOrchestrationRequestMode,
)
from agentmesh.store import DeepSearchBudgetConflict, SQLiteStore

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _deepsearch_run(repository: SQLiteStore, run_id: str) -> AgentRun:
    run, created = repository.claim_new_agent_run(
        AgentRun(
            id=run_id,
            thread_id=f"thread_{run_id}",
            user_id="user_budget",
            workspace_id="workspace_budget",
            project_id="project_budget",
            input_text="Run budgeted DeepSearch work",
            client_turn_id=f"turn_{run_id}",
            status=AgentRunStatus.PLANNING,
            planning_mode=AgentPlanningMode.DEEPSEARCH,
            requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
            orchestration_version="v1",
            orchestration_mode="execute",
            absolute_expires_at=NOW + timedelta(days=7),
            deepsearch_budget=DeepSearchBudgetV1(),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    assert created is True
    return run


def _replace_run(repository: SQLiteStore, run: AgentRun) -> None:
    with repository._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
            (run.model_dump_json(), run.updated_at.isoformat(), run.id),
        )


def test_budget_meter_reserves_maxima_before_work_and_settles_to_actual_usage(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-budget-reserve-settle.sqlite3")
    run = _deepsearch_run(repository, "run_budget_reserve_settle")
    meter = DeepSearchBudgetMeter(repository)
    maxima = DeepSearchBudgetUsageV1(active_seconds=10, llm_calls=1, tokens=100)

    reserved = meter.reserve(
        run_id=run.id,
        expected_budget_version=1,
        logical_operation_key="planning:problem-graph",
        invocation_key="planning:problem-graph:attempt:1",
        physical_attempt=1,
        resource_maxima=maxima,
    )

    assert reserved.replayed is False
    assert reserved.budget.version == 2
    assert reserved.budget.consumed == maxima
    assert len(reserved.budget.reservations) == 1
    assert reserved.reservation.status == "reserved"
    assert reserved.reservation.scope == "standard"

    actual = DeepSearchBudgetUsageV1(active_seconds=4, llm_calls=1, tokens=40)
    settled = meter.settle(
        run_id=run.id,
        expected_budget_version=2,
        invocation_key="planning:problem-graph:attempt:1",
        actual_usage=actual,
    )

    assert settled.replayed is False
    assert settled.budget.version == 3
    assert settled.budget.consumed == actual
    assert settled.reservation.status == "settled"
    assert settled.reservation.actual_usage == actual
    persisted = repository.get_agent_run(run.id)
    assert persisted is not None
    assert persisted.deepsearch_budget == settled.budget


def test_budget_reserve_exact_replay_is_idempotent_but_identity_collision_fails(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-budget-reserve-replay.sqlite3")
    run = _deepsearch_run(repository, "run_budget_reserve_replay")
    meter = DeepSearchBudgetMeter(repository)
    request = {
        "run_id": run.id,
        "expected_budget_version": 1,
        "logical_operation_key": "planning:plan",
        "invocation_key": "planning:plan:attempt:1",
        "physical_attempt": 1,
        "resource_maxima": DeepSearchBudgetUsageV1(llm_calls=1, tokens=500),
    }
    first = meter.reserve(**request)

    replay = meter.reserve(**request)

    assert replay.replayed is True
    assert replay.budget == first.budget
    assert replay.reservation == first.reservation
    with pytest.raises(
        DeepSearchBudgetConflict,
        match="deepsearch_budget_invocation_conflict",
    ):
        meter.reserve(
            **{
                **request,
                "resource_maxima": DeepSearchBudgetUsageV1(llm_calls=1, tokens=501),
            }
        )
    persisted = repository.get_agent_run(run.id)
    assert persisted is not None
    assert persisted.deepsearch_budget == first.budget


def test_budget_settle_rejects_stale_or_over_max_usage_and_replays_exactly(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-budget-stale-settle.sqlite3")
    run = _deepsearch_run(repository, "run_budget_stale_settle")
    meter = DeepSearchBudgetMeter(repository)
    first = meter.reserve(
        run_id=run.id,
        expected_budget_version=1,
        logical_operation_key="planning:requirement",
        invocation_key="planning:requirement:attempt:1",
        physical_attempt=1,
        resource_maxima=DeepSearchBudgetUsageV1(llm_calls=1, tokens=100),
    )
    second = meter.reserve(
        run_id=run.id,
        expected_budget_version=first.budget.version,
        logical_operation_key="planning:graph",
        invocation_key="planning:graph:attempt:1",
        physical_attempt=1,
        resource_maxima=DeepSearchBudgetUsageV1(llm_calls=1, tokens=200),
    )

    with pytest.raises(
        DeepSearchBudgetConflict,
        match="deepsearch_budget_version_conflict",
    ):
        meter.settle(
            run_id=run.id,
            expected_budget_version=first.budget.version,
            invocation_key=first.reservation.invocation_key,
            actual_usage=DeepSearchBudgetUsageV1(llm_calls=1, tokens=80),
        )
    with pytest.raises(
        DeepSearchBudgetConflict,
        match="deepsearch_budget_settlement_invalid",
    ):
        meter.settle(
            run_id=run.id,
            expected_budget_version=second.budget.version,
            invocation_key=first.reservation.invocation_key,
            actual_usage=DeepSearchBudgetUsageV1(llm_calls=1, tokens=101),
        )
    unchanged = repository.get_agent_run(run.id)
    assert unchanged is not None
    assert unchanged.deepsearch_budget == second.budget

    settled = meter.settle(
        run_id=run.id,
        expected_budget_version=second.budget.version,
        invocation_key=first.reservation.invocation_key,
        actual_usage=DeepSearchBudgetUsageV1(llm_calls=1, tokens=80),
    )
    replay = meter.settle(
        run_id=run.id,
        expected_budget_version=second.budget.version,
        invocation_key=first.reservation.invocation_key,
        actual_usage=DeepSearchBudgetUsageV1(llm_calls=1, tokens=80),
    )

    assert settled.budget.version == 4
    assert settled.budget.consumed == DeepSearchBudgetUsageV1(llm_calls=2, tokens=280)
    assert replay.replayed is True
    assert replay.budget == settled.budget


def test_budget_reserve_serializes_concurrent_oversubscription(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-budget-concurrent-oversubscription.sqlite3")
    run = _deepsearch_run(repository, "run_budget_concurrent_oversubscription")
    meter = DeepSearchBudgetMeter(repository)

    def reserve(operation: str) -> str:
        expected_version = 1
        while True:
            try:
                meter.reserve(
                    run_id=run.id,
                    expected_budget_version=expected_version,
                    logical_operation_key=operation,
                    invocation_key=f"{operation}:attempt:1",
                    physical_attempt=1,
                    resource_maxima=DeepSearchBudgetUsageV1(tokens=200000),
                )
                return "reserved"
            except DeepSearchBudgetConflict as error:
                if error.code != "deepsearch_budget_version_conflict":
                    return error.code
                assert error.current_budget_version is not None
                expected_version = error.current_budget_version

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(reserve, ["node:a", "node:b"]))

    assert sorted(outcomes) == ["deepsearch_budget_exhausted", "reserved"]
    persisted = repository.get_agent_run(run.id)
    assert persisted is not None
    assert persisted.deepsearch_budget is not None
    assert persisted.deepsearch_budget.version == 2
    assert persisted.deepsearch_budget.consumed.tokens == 200000
    assert len(persisted.deepsearch_budget.reservations) == 1


def test_budget_meter_is_unavailable_to_standard_runs(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "standard-run-budget-disabled.sqlite3")
    run = repository.save_agent_run(
        AgentRun(
            id="run_standard_budget_disabled",
            thread_id="thread_standard_budget_disabled",
            user_id="user_budget",
            workspace_id="workspace_budget",
            project_id="project_budget",
            input_text="Run ordinary work",
            status=AgentRunStatus.RUNNING,
            created_at=NOW,
            updated_at=NOW,
        )
    )

    with pytest.raises(DeepSearchBudgetConflict, match="deepsearch_budget_run_invalid"):
        DeepSearchBudgetMeter(repository).reserve(
            run_id=run.id,
            expected_budget_version=1,
            logical_operation_key="standard:llm",
            invocation_key="standard:llm:attempt:1",
            physical_attempt=1,
            resource_maxima=DeepSearchBudgetUsageV1(llm_calls=1),
        )


def test_unsettled_reservation_remains_billed_after_store_restart(tmp_path) -> None:
    database_path = tmp_path / "deepsearch-budget-crash-accounting.sqlite3"
    repository = SQLiteStore(database_path)
    run = _deepsearch_run(repository, "run_budget_crash_accounting")
    maxima = DeepSearchBudgetUsageV1(active_seconds=120, llm_calls=1, tokens=250000)

    DeepSearchBudgetMeter(repository).reserve(
        run_id=run.id,
        expected_budget_version=1,
        logical_operation_key="planning:model",
        invocation_key="planning:model:attempt:1",
        physical_attempt=1,
        resource_maxima=maxima,
    )

    restarted_repository = SQLiteStore(database_path)
    persisted = restarted_repository.get_agent_run(run.id)
    assert persisted is not None
    assert persisted.deepsearch_budget is not None
    assert persisted.deepsearch_budget.consumed == maxima
    assert persisted.deepsearch_budget.reservations[0].status == "reserved"
    with pytest.raises(DeepSearchBudgetConflict, match="deepsearch_budget_exhausted"):
        DeepSearchBudgetMeter(restarted_repository).reserve(
            run_id=run.id,
            expected_budget_version=persisted.deepsearch_budget.version,
            logical_operation_key="planning:another-model",
            invocation_key="planning:another-model:attempt:1",
            physical_attempt=1,
            resource_maxima=DeepSearchBudgetUsageV1(tokens=1),
        )


def test_standard_budget_preserves_finalization_partition_and_finalization_is_independent(
    tmp_path,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-budget-finalization-partition.sqlite3")
    run = _deepsearch_run(repository, "run_budget_finalization_partition")
    meter = DeepSearchBudgetMeter(repository)
    standard_limit = DeepSearchBudgetUsageV1(
        active_seconds=1500,
        artifact_bytes=9306112,
    )
    standard = meter.reserve(
        run_id=run.id,
        expected_budget_version=1,
        logical_operation_key="execution:standard-capacity",
        invocation_key="execution:standard-capacity:attempt:1",
        physical_attempt=1,
        resource_maxima=standard_limit,
    )

    for operation, excess in (
        ("execution:active-second-overflow", DeepSearchBudgetUsageV1(active_seconds=1)),
        ("execution:artifact-byte-overflow", DeepSearchBudgetUsageV1(artifact_bytes=1)),
    ):
        with pytest.raises(DeepSearchBudgetConflict, match="deepsearch_budget_exhausted"):
            meter.reserve(
                run_id=run.id,
                expected_budget_version=standard.budget.version,
                logical_operation_key=operation,
                invocation_key=f"{operation}:attempt:1",
                physical_attempt=1,
                resource_maxima=excess,
            )
    with pytest.raises(DeepSearchBudgetConflict, match="deepsearch_budget_state_conflict"):
        meter.reserve(
            run_id=run.id,
            expected_budget_version=standard.budget.version,
            logical_operation_key="finalization:too-early",
            invocation_key="finalization:too-early:attempt:1",
            physical_attempt=1,
            resource_maxima=DeepSearchBudgetUsageV1(active_seconds=1),
            scope="finalization",
        )

    running = run.model_copy(
        update={
            "status": AgentRunStatus.RUNNING,
            "deepsearch_budget": standard.budget,
            "updated_at": NOW + timedelta(minutes=1),
        }
    )
    _replace_run(repository, running)
    finalization_limit = DeepSearchBudgetUsageV1(
        active_seconds=300,
        artifact_bytes=1179648,
    )
    finalization = meter.reserve(
        run_id=run.id,
        expected_budget_version=standard.budget.version,
        logical_operation_key="finalization:report",
        invocation_key="finalization:report:attempt:1",
        physical_attempt=1,
        resource_maxima=finalization_limit,
        scope="finalization",
    )

    assert finalization.reservation.scope == "finalization"
    assert finalization.budget.consumed == DeepSearchBudgetUsageV1(
        active_seconds=1800,
        artifact_bytes=10485760,
    )
    persisted = repository.get_agent_run(run.id)
    assert persisted is not None
    assert persisted.deepsearch_budget == finalization.budget
    for operation, excess in (
        ("finalization:active-second-overflow", DeepSearchBudgetUsageV1(active_seconds=1)),
        ("finalization:artifact-byte-overflow", DeepSearchBudgetUsageV1(artifact_bytes=1)),
    ):
        with pytest.raises(DeepSearchBudgetConflict, match="deepsearch_budget_exhausted"):
            meter.reserve(
                run_id=run.id,
                expected_budget_version=finalization.budget.version,
                logical_operation_key=operation,
                invocation_key=f"{operation}:attempt:1",
                physical_attempt=1,
                resource_maxima=excess,
                scope="finalization",
            )
    with pytest.raises(DeepSearchBudgetConflict, match="deepsearch_budget_scope_invalid"):
        meter.reserve(
            run_id=run.id,
            expected_budget_version=finalization.budget.version,
            logical_operation_key="finalization:model",
            invocation_key="finalization:model:attempt:1",
            physical_attempt=1,
            resource_maxima=DeepSearchBudgetUsageV1(tokens=1),
            scope="finalization",
        )
    unchanged = repository.get_agent_run(run.id)
    assert unchanged is not None
    assert unchanged.deepsearch_budget == finalization.budget


def test_terminal_cancellation_settles_all_reservations_in_one_budget_version(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-budget-terminal-cancel.sqlite3")
    run = _deepsearch_run(repository, "run_budget_terminal_cancel")
    meter = DeepSearchBudgetMeter(repository)
    first = meter.reserve(
        run_id=run.id,
        expected_budget_version=1,
        logical_operation_key="planning:requirement",
        invocation_key="planning:requirement:attempt:1",
        physical_attempt=1,
        resource_maxima=DeepSearchBudgetUsageV1(active_seconds=5, llm_calls=1, tokens=100),
    )
    second = meter.reserve(
        run_id=run.id,
        expected_budget_version=first.budget.version,
        logical_operation_key="planning:graph",
        invocation_key="planning:graph:attempt:1",
        physical_attempt=1,
        resource_maxima=DeepSearchBudgetUsageV1(active_seconds=7, llm_calls=1, tokens=200),
    )

    cancelled = repository.cancel_agent_run_tree(run.id, user_id=run.user_id)

    assert cancelled is not None
    assert cancelled.status is AgentRunStatus.CANCELLED
    assert cancelled.deepsearch_budget is not None
    assert cancelled.deepsearch_budget.version == second.budget.version + 1
    assert cancelled.deepsearch_budget.consumed == DeepSearchBudgetUsageV1(
        active_seconds=12,
        llm_calls=2,
        tokens=300,
    )
    assert all(
        reservation.status == "settled"
        and reservation.actual_usage == reservation.resource_maxima
        for reservation in cancelled.deepsearch_budget.reservations
    )

    replay = repository.cancel_agent_run_tree(run.id, user_id=run.user_id)
    assert replay is not None
    assert replay.deepsearch_budget == cancelled.deepsearch_budget


def test_planning_failure_settles_outstanding_reservation_at_its_maximum(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-budget-planning-failure.sqlite3")
    run = _deepsearch_run(repository, "run_budget_planning_failure")
    reserved = DeepSearchBudgetMeter(repository).reserve(
        run_id=run.id,
        expected_budget_version=1,
        logical_operation_key="planning:requirement",
        invocation_key="planning:requirement:attempt:1",
        physical_attempt=1,
        resource_maxima=DeepSearchBudgetUsageV1(active_seconds=10, llm_calls=1, tokens=500),
    )

    failed = repository.fail_deepsearch_planning_run(
        run_id=run.id,
        user_id=run.user_id,
        error_code="deepsearch_requirement_invalid",
        checked_at=NOW + timedelta(minutes=1),
    )

    assert failed is not None
    assert failed.status is AgentRunStatus.FAILED
    assert failed.deepsearch_budget is not None
    assert failed.deepsearch_budget.version == reserved.budget.version + 1
    assert failed.deepsearch_budget.reservations[0].status == "settled"
    assert (
        failed.deepsearch_budget.reservations[0].actual_usage
        == reserved.reservation.resource_maxima
    )
