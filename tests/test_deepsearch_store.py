from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest

from agentmesh.agent_run_identity import agent_run_create_request_hash
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    DeepSearchBudgetUsageV1,
    DeepSearchBudgetV1,
    SkillOrchestrationRequestMode,
    now_utc,
)
from agentmesh.store import ResearchStoreConflict, SQLiteStore


def _run(
    run_id: str,
    *,
    planning_mode: AgentPlanningMode = AgentPlanningMode.STANDARD,
    client_turn_id: str = "turn_deepsearch_store",
    thread_id: str = "thread_deepsearch_store",
    retry_of_run_id: str | None = None,
    status: AgentRunStatus | None = None,
) -> AgentRun:
    created_at = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    is_deepsearch = planning_mode is AgentPlanningMode.DEEPSEARCH
    status = status or (
        AgentRunStatus.PLANNING if is_deepsearch else AgentRunStatus.CREATED
    )
    return AgentRun(
        id=run_id,
        thread_id=thread_id,
        user_id="user_deepsearch_store",
        workspace_id="workspace_deepsearch_store",
        project_id="project_deepsearch_store",
        input_text="compare the market",
        client_turn_id=client_turn_id,
        retry_of_run_id=retry_of_run_id,
        planning_mode=planning_mode,
        requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
        orchestration_version="v1",
        orchestration_mode="execute",
        status=status,
        deadline_at=None,
        absolute_expires_at=created_at + timedelta(days=7) if is_deepsearch else None,
        deepsearch_budget=DeepSearchBudgetV1() if is_deepsearch else None,
        created_at=created_at,
        updated_at=created_at,
    )


def _replace_run_fixture(repository: SQLiteStore, run: AgentRun) -> AgentRun:
    """Seed an otherwise unreachable persisted state without reopening production writers."""
    with repository._connect() as connection:
        cursor = connection.execute(
            "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
            (run.model_dump_json(), run.updated_at.isoformat(), run.id),
        )
    assert cursor.rowcount == 1
    persisted = repository.get_agent_run(run.id)
    assert persisted is not None
    return persisted


def test_create_request_hash_is_deterministic_and_includes_mode_and_retry_identity() -> None:
    base = {
        "user_id": "user_hash",
        "thread_id": "thread_hash",
        "client_turn_id": "turn_hash",
        "content": "same content",
        "skill_name": None,
        "orchestration_mode": SkillOrchestrationRequestMode.AUTO,
    }

    standard = agent_run_create_request_hash(
        **base,
        planning_mode=AgentPlanningMode.STANDARD,
        retry_of_run_id=None,
    )
    same_standard = agent_run_create_request_hash(
        **base,
        planning_mode="standard",
        retry_of_run_id=None,
    )
    deepsearch = agent_run_create_request_hash(
        **base,
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        retry_of_run_id=None,
    )
    retry_a = agent_run_create_request_hash(
        **base,
        planning_mode=AgentPlanningMode.STANDARD,
        retry_of_run_id="run_retry_a",
    )
    retry_b = agent_run_create_request_hash(
        **base,
        planning_mode=AgentPlanningMode.STANDARD,
        retry_of_run_id="run_retry_b",
    )

    assert same_standard == standard
    assert len(standard) == 64
    assert len({standard, deepsearch, retry_a, retry_b}) == 4


def test_store_persists_hash_and_replays_an_identical_request(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-identical-replay.sqlite3")
    first, first_created = repository.claim_new_agent_run(_run("run_identical_first"))
    replay, replay_created = repository.claim_new_agent_run(_run("run_identical_replay"))

    assert first_created is True
    assert first.create_request_hash is not None
    assert repository.get_agent_run(first.id) == first
    assert replay_created is False
    assert replay.id == first.id
    assert replay.create_request_hash == first.create_request_hash


@pytest.mark.parametrize(
    ("first_mode", "second_mode"),
    [
        (AgentPlanningMode.STANDARD, AgentPlanningMode.DEEPSEARCH),
        (AgentPlanningMode.DEEPSEARCH, AgentPlanningMode.STANDARD),
    ],
)
def test_store_rejects_planning_mode_collisions_in_both_directions(
    tmp_path,
    first_mode: AgentPlanningMode,
    second_mode: AgentPlanningMode,
) -> None:
    repository = SQLiteStore(tmp_path / f"deepsearch-mode-{first_mode.value}.sqlite3")
    first, created = repository.claim_new_agent_run(_run("run_mode_first", planning_mode=first_mode))

    assert created is True
    with pytest.raises(RuntimeError, match="client_turn_id"):
        repository.claim_new_agent_run(_run("run_mode_second", planning_mode=second_mode))

    persisted = repository.get_agent_run_by_client_turn(first.user_id, first.client_turn_id or "")
    assert persisted is not None
    assert persisted.id == first.id
    assert persisted.planning_mode == first_mode


def test_store_rejects_retry_identity_collision(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-retry-collision.sqlite3")
    repository.claim_new_agent_run(_run("run_retry_first", retry_of_run_id="run_original_a"))

    with pytest.raises(RuntimeError, match="client_turn_id"):
        repository.claim_new_agent_run(_run("run_retry_second", retry_of_run_id="run_original_b"))


def test_store_rejects_a_supplied_hash_that_does_not_match_the_request(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-invalid-hash.sqlite3")
    invalid = _run("run_invalid_hash").model_copy(update={"create_request_hash": "0" * 64})

    with pytest.raises(RuntimeError, match="create_request_hash"):
        repository.claim_new_agent_run(invalid)

    assert repository.get_agent_run(invalid.id) is None


def test_concurrent_standard_and_deepsearch_claims_have_one_winner(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-mode-race.sqlite3")
    barrier = Barrier(2)

    def claim(mode: AgentPlanningMode) -> tuple[AgentPlanningMode, bool] | RuntimeError:
        barrier.wait()
        try:
            _claimed, created = repository.claim_new_agent_run(
                _run(f"run_race_{mode.value}", planning_mode=mode)
            )
        except RuntimeError as error:
            return error
        return mode, created

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                claim,
                [AgentPlanningMode.STANDARD, AgentPlanningMode.DEEPSEARCH],
            )
        )

    winners = [outcome for outcome in outcomes if isinstance(outcome, tuple) and outcome[1]]
    conflicts = [outcome for outcome in outcomes if isinstance(outcome, RuntimeError)]
    assert len(winners) == 1
    assert len(conflicts) == 1
    assert "client_turn_id" in str(conflicts[0])


def test_waiting_clarification_blocks_a_second_run_until_cancelled(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-active-gate.sqlite3")
    checked_at = now_utc()
    waiting, created = repository.claim_new_agent_run(
        _run(
            "run_waiting_clarification",
            planning_mode=AgentPlanningMode.DEEPSEARCH,
            client_turn_id="turn_waiting_clarification",
        )
    )
    waiting = _replace_run_fixture(
        repository,
        waiting.model_copy(
            update={
                "status": AgentRunStatus.WAITING_CLARIFICATION,
                "absolute_expires_at": checked_at + timedelta(days=7),
                "interaction_expires_at": checked_at + timedelta(hours=24),
            }
        )
    )
    next_run = _run(
        "run_after_clarification",
        client_turn_id="turn_after_clarification",
    )

    assert created is True
    with pytest.raises(RuntimeError, match="already active"):
        repository.claim_new_agent_run(next_run)

    cancelled = repository.cancel_agent_run_tree(waiting.id, user_id=waiting.user_id)
    assert cancelled is not None
    assert cancelled.status == AgentRunStatus.CANCELLED

    claimed, next_created = repository.claim_new_agent_run(next_run)
    assert next_created is True
    assert claimed.id == next_run.id


@pytest.mark.parametrize(
    "update",
    [
        {"planning_mode": AgentPlanningMode.DEEPSEARCH},
        {"create_request_hash": "0" * 64},
        {"retry_of_run_id": "run_other"},
    ],
)
def test_agent_run_updates_cannot_change_creation_identity(tmp_path, update: dict[str, object]) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-immutable-identity.sqlite3")
    original, created = repository.claim_new_agent_run(_run("run_immutable_identity"))
    assert created is True

    with pytest.raises(ResearchStoreConflict, match="creation identity"):
        repository.save_agent_run(original.model_copy(update=update))

    assert repository.get_agent_run(original.id) == original


def test_save_agent_run_cannot_bypass_deepsearch_lifecycle_invariants(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-save-invariants.sqlite3")
    valid = _run(
        "run_save_deepsearch_invariants",
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        client_turn_id="turn_save_deepsearch_invariants",
    )

    with pytest.raises(ResearchStoreConflict, match="persistence invariants"):
        repository.save_agent_run(valid.model_copy(update={"absolute_expires_at": None}))
    assert repository.get_agent_run(valid.id) is None

    repository.save_agent_run(valid)
    with pytest.raises(ResearchStoreConflict, match="dedicated persistence"):
        repository.save_agent_run(
            valid.model_copy(update={"absolute_expires_at": valid.absolute_expires_at + timedelta(seconds=1)})
        )
    assert repository.get_agent_run(valid.id) == valid


def test_generic_save_cannot_roll_back_existing_deepsearch_state_or_budget(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-generic-save-fence.sqlite3")
    stale, created = repository.claim_new_agent_run(
        _run(
            "run_generic_save_fence",
            planning_mode=AgentPlanningMode.DEEPSEARCH,
            client_turn_id="turn_generic_save_fence",
        )
    )
    assert created is True
    assert stale.deepsearch_budget is not None
    authoritative = stale.model_copy(
        update={
            "status": AgentRunStatus.WAITING_CLARIFICATION,
            "interaction_expires_at": stale.created_at + timedelta(hours=24),
            "deepsearch_budget": stale.deepsearch_budget.model_copy(
                update={
                    "version": 2,
                    "consumed": DeepSearchBudgetUsageV1(llm_calls=1, tokens=100),
                }
            ),
        }
    )
    _replace_run_fixture(repository, authoritative)

    with pytest.raises(ResearchStoreConflict, match="dedicated persistence"):
        repository.save_agent_run(stale)

    assert repository.get_agent_run(stale.id) == authoritative


def test_generic_run_event_writer_cannot_roll_back_deepsearch_without_partial_writes(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-generic-event-fence.sqlite3")
    stale, created = repository.claim_new_agent_run(
        _run(
            "run_generic_event_fence",
            planning_mode=AgentPlanningMode.DEEPSEARCH,
            client_turn_id="turn_generic_event_fence",
        )
    )
    assert created is True
    assert stale.deepsearch_budget is not None
    authoritative = stale.model_copy(
        update={
            "status": AgentRunStatus.WAITING_CLARIFICATION,
            "interaction_expires_at": stale.created_at + timedelta(hours=24),
            "deepsearch_budget": stale.deepsearch_budget.model_copy(
                update={
                    "version": 2,
                    "consumed": DeepSearchBudgetUsageV1(llm_calls=1, tokens=100),
                }
            ),
        }
    )
    _replace_run_fixture(repository, authoritative)
    events_before = repository.list_agent_run_events(stale.id)

    with pytest.raises(ResearchStoreConflict, match="dedicated persistence"):
        repository.save_agent_run_with_event(
            stale.model_copy(update={"status": AgentRunStatus.FAILED}),
            "run_failed",
            expected_statuses={AgentRunStatus.WAITING_CLARIFICATION},
        )

    assert repository.get_agent_run(stale.id) == authoritative
    assert repository.list_agent_run_events(stale.id) == events_before


def test_new_deepsearch_claim_rejects_a_preconsumed_budget(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-pristine-budget.sqlite3")
    run = _run(
        "run_preconsumed_budget",
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        client_turn_id="turn_preconsumed_budget",
    )
    assert run.deepsearch_budget is not None
    polluted_budget = run.deepsearch_budget.model_copy(
        update={
            "version": 2,
            "consumed": run.deepsearch_budget.consumed.model_copy(update={"llm_calls": 1}),
            "stage_recovery_attempts": {"planning": 1},
        }
    )

    with pytest.raises(ResearchStoreConflict, match="persistence invariants"):
        repository.claim_new_agent_run(run.model_copy(update={"deepsearch_budget": polluted_budget}))

    assert repository.get_agent_run(run.id) is None


def test_new_deepsearch_save_rejects_a_preconsumed_budget(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-pristine-save-budget.sqlite3")
    run = _run(
        "run_preconsumed_save_budget",
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        client_turn_id="turn_preconsumed_save_budget",
    )
    assert run.deepsearch_budget is not None
    polluted_budget = run.deepsearch_budget.model_copy(
        update={"consumed": run.deepsearch_budget.consumed.model_copy(update={"tokens": 1})}
    )

    with pytest.raises(ResearchStoreConflict, match="persistence invariants"):
        repository.save_agent_run(run.model_copy(update={"deepsearch_budget": polluted_budget}))

    assert repository.get_agent_run(run.id) is None


@pytest.mark.parametrize(
    ("case", "update"),
    [
        ("status", {"status": AgentRunStatus.WAITING_CLARIFICATION}),
        ("plan", {"plan_id": "plan_existing"}),
        (
            "interaction_expiry",
            {"interaction_expires_at": datetime(2026, 8, 27, 12, 0, tzinfo=UTC)},
        ),
        ("paused", {"paused_state": {"kind": "forged"}}),
        ("output", {"output_text": "already complete"}),
        ("error", {"error_code": "already_failed"}),
        ("tool_count", {"tool_call_count": 1}),
        (
            "request_mode",
            {"requested_orchestration_mode": SkillOrchestrationRequestMode.SINGLE},
        ),
        ("runtime", {"orchestration_version": "research-v3"}),
        ("execution_mode", {"orchestration_mode": "preview"}),
    ],
)
def test_new_deepsearch_claim_requires_a_pristine_planning_state(
    tmp_path,
    case: str,
    update: dict[str, object],
) -> None:
    repository = SQLiteStore(tmp_path / f"deepsearch-pristine-{case}.sqlite3")
    run = _run(
        f"run_pristine_{case}",
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        client_turn_id=f"turn_pristine_{case}",
    ).model_copy(update=update)

    with pytest.raises(ResearchStoreConflict):
        repository.claim_new_agent_run(run)

    assert repository.get_agent_run(run.id) is None


def test_legacy_replay_rejects_a_receipt_whose_payload_identity_was_tampered(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-legacy-receipt-integrity.sqlite3")
    original = _run("run_legacy_receipt_integrity")
    repository.save_agent_run(original)
    with repository._connect() as connection:
        connection.execute(
            "INSERT INTO agent_run_receipts(user_id, client_turn_id, run_id) VALUES (?, ?, ?)",
            (original.user_id, original.client_turn_id, original.id),
        )
        payload = original.model_dump(mode="json")
        payload["user_id"] = "user_tampered"
        connection.execute(
            "UPDATE agent_runs SET payload = ? WHERE id = ?",
            (original.__class__.model_validate(payload).model_dump_json(), original.id),
        )

    with pytest.raises(RuntimeError, match="client_turn_id"):
        repository.claim_new_agent_run(_run("run_legacy_receipt_replay"))
