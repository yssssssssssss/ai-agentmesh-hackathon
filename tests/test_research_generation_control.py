from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from agentmesh.agent_runtime.settings import (
    SkillOrchestrationMode,
    research_preview_allowlist,
)
from agentmesh.models import (
    AgentRun,
    AgentRunStatus,
    SkillIntent,
    SkillOrchestrationRequestMode,
    SkillPlan,
    SkillPlanStatus,
)
from agentmesh.research_orchestration.current import (
    RESEARCH_WRITER_CONTROL_SEED_HASH,
    ResearchRolloutDecision,
    ResearchRunCreationCoordinator,
    ResearchWriterGeneration,
    ResearchWriterLifecycle,
    decide_research_rollout,
    is_competitive_research_request,
    parse_research_preview_allowlist,
)
from agentmesh.store import ResearchStoreConflict, SQLiteStore

NOW = datetime(2026, 8, 21, 9, 15, tzinfo=UTC)


def _run(
    *,
    run_id: str,
    client_turn_id: str,
    thread_id: str,
    input_text: str = "Compare Alpha and Beta",
) -> AgentRun:
    return AgentRun(
        id=run_id,
        thread_id=thread_id,
        user_id="user_gate2_preview_1",
        workspace_id="workspace_gate2",
        project_id="project_gate2",
        input_text=input_text,
        client_turn_id=client_turn_id,
        status=AgentRunStatus.PLANNING,
        requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
        project_chat=True,
        created_at=NOW,
        updated_at=NOW,
    )


def _count(store: SQLiteStore, query: str, parameters: tuple[object, ...] = ()) -> int:
    with store._connect() as connection:
        return int(connection.execute(query, parameters).fetchone()[0])


def test_writer_control_is_seeded_to_retired_v2_and_advances_once(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "writer-control.sqlite3")

    seeded = store.get_research_writer_control()

    assert seeded.active_generation == ResearchWriterGeneration.V2
    assert seeded.lifecycle_state == ResearchWriterLifecycle.RETIRED
    assert seeded.lifecycle_state.accepts_new_runs is False
    assert seeded.lifecycle_state.allows_continuations is False
    assert seeded.generation_epoch == 1
    assert seeded.decision_receipt_hash == RESEARCH_WRITER_CONTROL_SEED_HASH
    assert seeded.updated_at.tzinfo is not None

    advanced = store.compare_and_swap_research_writer_control(
        expected_generation=ResearchWriterGeneration.V2,
        expected_generation_epoch=1,
        target_generation=ResearchWriterGeneration.V3,
        decision_receipt_hash="a" * 64,
        changed_at=NOW,
    )

    assert advanced.active_generation == ResearchWriterGeneration.V3
    assert advanced.lifecycle_state == ResearchWriterLifecycle.ACTIVE
    assert advanced.generation_epoch == 2
    assert store.get_research_writer_control() == advanced

    with pytest.raises(ResearchStoreConflict, match="cannot roll back"):
        store.compare_and_swap_research_writer_control(
            expected_generation=ResearchWriterGeneration.V3,
            expected_generation_epoch=2,
            target_generation=ResearchWriterGeneration.V2,
            decision_receipt_hash="b" * 64,
            changed_at=NOW,
        )


def test_existing_writer_control_schema_migrates_to_retired(tmp_path) -> None:
    database = tmp_path / "writer-control-migration.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE research_writer_control (
                control_key TEXT PRIMARY KEY CHECK(control_key = 'global'),
                active_generation TEXT NOT NULL
                    CHECK(active_generation IN ('research-v2', 'research-v3')),
                generation_epoch INTEGER NOT NULL CHECK(generation_epoch >= 1),
                decision_receipt_hash TEXT NOT NULL CHECK(length(decision_receipt_hash) = 64),
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """INSERT INTO research_writer_control(
                control_key, active_generation, generation_epoch,
                decision_receipt_hash, updated_at
            ) VALUES ('global', 'research-v2', 1, ?, ?)""",
            (RESEARCH_WRITER_CONTROL_SEED_HASH, NOW.isoformat()),
        )

    store = SQLiteStore(database)

    assert store.get_research_writer_control().lifecycle_state == ResearchWriterLifecycle.RETIRED


def test_writer_control_compare_and_swap_rejects_stale_or_invalid_receipts(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "writer-control-conflict.sqlite3")

    with pytest.raises(ResearchStoreConflict, match="compare-and-swap conflict"):
        store.compare_and_swap_research_writer_control(
            expected_generation=ResearchWriterGeneration.V2,
            expected_generation_epoch=9,
            target_generation=ResearchWriterGeneration.V3,
            decision_receipt_hash="a" * 64,
            changed_at=NOW,
        )
    with pytest.raises(ValueError):
        store.compare_and_swap_research_writer_control(
            expected_generation=ResearchWriterGeneration.V2,
            expected_generation_epoch=1,
            target_generation=ResearchWriterGeneration.V3,
            decision_receipt_hash="not-a-sha256",
            changed_at=NOW,
        )

    assert store.get_research_writer_control().generation_epoch == 1


def test_writer_lifecycle_advances_with_compare_and_swap(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "writer-lifecycle.sqlite3")
    active = store.compare_and_swap_research_writer_control(
        expected_generation=ResearchWriterGeneration.V2,
        expected_generation_epoch=1,
        target_generation=ResearchWriterGeneration.V3,
        decision_receipt_hash="0" * 64,
        changed_at=NOW,
    )

    draining = store.compare_and_swap_research_writer_lifecycle(
        expected_generation=ResearchWriterGeneration.V3,
        expected_generation_epoch=active.generation_epoch,
        expected_lifecycle_state=ResearchWriterLifecycle.ACTIVE,
        target_lifecycle_state=ResearchWriterLifecycle.DRAINING,
        decision_receipt_hash="1" * 64,
        changed_at=NOW,
    )
    retired = store.compare_and_swap_research_writer_lifecycle(
        expected_generation=ResearchWriterGeneration.V3,
        expected_generation_epoch=draining.generation_epoch,
        expected_lifecycle_state=ResearchWriterLifecycle.DRAINING,
        target_lifecycle_state=ResearchWriterLifecycle.RETIRED,
        decision_receipt_hash="2" * 64,
        changed_at=NOW,
    )

    assert draining.lifecycle_state == ResearchWriterLifecycle.DRAINING
    assert retired.lifecycle_state == ResearchWriterLifecycle.RETIRED
    assert retired.generation_epoch == 4
    with pytest.raises(ResearchStoreConflict, match="transition is invalid"):
        store.compare_and_swap_research_writer_lifecycle(
            expected_generation=ResearchWriterGeneration.V3,
            expected_generation_epoch=retired.generation_epoch,
            expected_lifecycle_state=ResearchWriterLifecycle.RETIRED,
            target_lifecycle_state=ResearchWriterLifecycle.ACTIVE,
            decision_receipt_hash="3" * 64,
            changed_at=NOW,
        )


@pytest.mark.parametrize(
    "raw",
    [
        "*",
        "user_ok,*",
        "user_ok,user_ok",
        "user_ok,,user_other",
        "user with spaces",
        "-leading-dash",
    ],
)
def test_preview_allowlist_rejects_wildcards_duplicates_and_invalid_ids(raw: str) -> None:
    with pytest.raises(ValueError, match="AGENTMESH_RESEARCH_PREVIEW_ALLOWLIST"):
        parse_research_preview_allowlist(raw)


def test_preview_allowlist_is_server_owned_and_empty_by_default(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("AGENTMESH_RESEARCH_PREVIEW_ALLOWLIST", raising=False)
    assert research_preview_allowlist() == frozenset()

    monkeypatch.setenv(
        "AGENTMESH_RESEARCH_PREVIEW_ALLOWLIST",
        "user_gate2_preview_1, user.gate2:preview-2",
    )
    assert research_preview_allowlist() == {
        "user_gate2_preview_1",
        "user.gate2:preview-2",
    }


def test_competitive_research_classifier_is_independent_of_v2_planning() -> None:
    assert is_competitive_research_request("对比淘宝和拼多多的协作能力并分析差异")
    assert is_competitive_research_request("淘宝、拼多多和京东的购物车体验、会员体系与履约能力分别如何？")
    assert is_competitive_research_request("任意参数", explicit_skill_name="$competitive-analysis")
    assert not is_competitive_research_request("用尼尔森原则检查竞品页面的可用性问题")
    assert not is_competitive_research_request("生成一份访谈提纲")


@pytest.mark.parametrize(
    ("eligible", "mode", "generation", "lifecycle", "allowlisted", "expected"),
    [
        (
            False,
            SkillOrchestrationMode.EXECUTE,
            ResearchWriterGeneration.V3,
            ResearchWriterLifecycle.ACTIVE,
            True,
            ("v1", "off", "not_research_eligible"),
        ),
        (
            True,
            SkillOrchestrationMode.OFF,
            ResearchWriterGeneration.V2,
            ResearchWriterLifecycle.DRAINING,
            True,
            ("v1", "off", "orchestration_off"),
        ),
        (
            True,
            SkillOrchestrationMode.PREVIEW,
            ResearchWriterGeneration.V2,
            ResearchWriterLifecycle.DRAINING,
            False,
            ("v1", "off", "research_writer_draining"),
        ),
        (
            True,
            SkillOrchestrationMode.EXECUTE,
            ResearchWriterGeneration.V2,
            ResearchWriterLifecycle.RETIRED,
            False,
            ("v1", "off", "research_v2_retired"),
        ),
        (
            True,
            SkillOrchestrationMode.EXECUTE,
            ResearchWriterGeneration.V2,
            ResearchWriterLifecycle.ACTIVE,
            False,
            ("v1", "off", "research_v2_retired"),
        ),
        (
            True,
            SkillOrchestrationMode.PREVIEW,
            ResearchWriterGeneration.V3,
            ResearchWriterLifecycle.ACTIVE,
            False,
            ("v1", "off", "v3_preview_not_allowlisted"),
        ),
        (
            True,
            SkillOrchestrationMode.PREVIEW,
            ResearchWriterGeneration.V3,
            ResearchWriterLifecycle.ACTIVE,
            True,
            ("research-v3", "preview", "v3_preview_allowlisted"),
        ),
        (
            True,
            SkillOrchestrationMode.EXECUTE,
            ResearchWriterGeneration.V3,
            ResearchWriterLifecycle.ACTIVE,
            True,
            ("blocked", "off", "v3_execute_not_authorized"),
        ),
    ],
)
def test_rollout_decision_never_selects_the_retired_v2_writer(
    eligible: bool,
    mode: SkillOrchestrationMode,
    generation: ResearchWriterGeneration,
    lifecycle: ResearchWriterLifecycle,
    allowlisted: bool,
    expected: tuple[str, str, str],
) -> None:
    decision = decide_research_rollout(
        research_eligible=eligible,
        configured_mode=mode,
        active_generation=generation,
        lifecycle_state=lifecycle,
        user_id="user_gate2_preview_1",
        preview_allowlist=(
            frozenset({"user_gate2_preview_1"}) if allowlisted else frozenset()
        ),
    )

    assert (decision.target, decision.mode, decision.reason) == expected
    if decision.reason in {"research_writer_draining", "research_v2_retired"}:
        assert decision.research_generation is None


def test_retired_fence_blocks_new_and_historical_v2_run_writes(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "writer-retired-trigger.sqlite3")
    existing = _run(
        run_id="run_existing_v2",
        client_turn_id="turn_existing_v2",
        thread_id="thread_existing_v2",
    ).model_copy(
        update={
            "orchestration_version": "research-v2",
            "orchestration_mode": "execute",
            "writer_generation_epoch": 1,
        }
    )
    store.save_agent_run(existing.model_copy(update={"orchestration_version": "v1"}))
    with store._connect() as connection:
        connection.execute(
            "UPDATE agent_runs SET payload = ?, orchestration_version = ? WHERE id = ?",
            (existing.model_dump_json(), "research-v2", existing.id),
        )

    updated = existing.model_copy(update={"status": AgentRunStatus.COMPLETED})
    with pytest.raises(ResearchStoreConflict, match="historical and read-only"):
        store.save_agent_run(updated)
    assert store.get_agent_run(existing.id) == existing

    with pytest.raises(ResearchStoreConflict, match="historical and read-only"):
        store.save_agent_run(
            existing.model_copy(
                update={
                    "id": "run_new_v2_after_retirement",
                    "client_turn_id": "turn_new_v2_after_retirement",
                }
            )
        )
    assert store.get_agent_run(existing.id) == existing


def test_historical_v2_run_is_ignored_by_generic_admission_and_cancel(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "historical-v2-is-read-only.sqlite3")
    historical = _run(
        run_id="run_historical_v2",
        client_turn_id="turn_historical_v2",
        thread_id="thread_shared_after_v2",
    ).model_copy(
        update={
            "status": AgentRunStatus.RUNNING,
            "orchestration_version": "research-v2",
            "orchestration_mode": "execute",
            "writer_generation_epoch": 1,
        }
    )
    store.claim_new_agent_run(historical.model_copy(update={"orchestration_version": "v1"}))
    with store._connect() as connection:
        connection.execute(
            "UPDATE agent_runs SET payload = ?, orchestration_version = ? WHERE id = ?",
            (historical.model_dump_json(), "research-v2", historical.id),
        )

    replacement, created = store.claim_new_agent_run(
        _run(
            run_id="run_v1_after_historical_v2",
            client_turn_id="turn_v1_after_historical_v2",
            thread_id=historical.thread_id,
        )
    )
    cancel_result = store.cancel_agent_run_tree(historical.id, user_id=historical.user_id)

    assert created is True
    assert replacement.orchestration_version == "v1"
    assert cancel_result is not None and cancel_result.status == AgentRunStatus.RUNNING
    assert store.get_agent_run(historical.id) == historical
    assert store.list_agent_run_events(historical.id) == []


def test_historical_v2_run_and_associated_records_reject_generic_mutations(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "historical-v2-generic-mutations.sqlite3")
    historical = _run(
        run_id="run_historical_v2_mutations",
        client_turn_id="turn_historical_v2_mutations",
        thread_id="thread_historical_v2_mutations",
    ).model_copy(
        update={
            "status": AgentRunStatus.COMPLETED,
            "orchestration_version": "research-v2",
            "orchestration_mode": "execute",
            "writer_generation_epoch": 1,
        }
    )
    store.save_agent_run(historical.model_copy(update={"orchestration_version": "v1"}))
    plan = store.save_skill_plan(
        SkillPlan(
            id="plan_historical_v2_mutations",
            run_id=historical.id,
            status=SkillPlanStatus.RUNNING,
            intent=SkillIntent(goal="prove history remains immutable"),
        )
    )
    event = store.append_agent_run_event(historical.id, "sdk_stream_event", {"delta": "historic"})
    with store._connect() as connection:
        connection.execute(
            "UPDATE agent_runs SET payload = ?, orchestration_version = ? WHERE id = ?",
            (historical.model_dump_json(), "research-v2", historical.id),
        )
        connection.execute(
            "UPDATE agent_run_events SET created_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", event.id),
        )

    assert (
        store.save_agent_run_with_event(
            historical.model_copy(update={"status": AgentRunStatus.FAILED}),
            "run_failed",
        )
        is None
    )
    assert (
        store.finish_skill_plan_and_run(
            plan=plan.model_copy(update={"status": SkillPlanStatus.COMPLETED}),
            run=historical,
            expected_plan_statuses={SkillPlanStatus.RUNNING},
            expected_run_statuses={AgentRunStatus.COMPLETED},
            events=[("run_completed", {})],
        )
        is None
    )
    with pytest.raises(ResearchStoreConflict, match="historical and read-only"):
        store.save_skill_plan(plan.model_copy(update={"status": SkillPlanStatus.COMPLETED}))
    with pytest.raises(ResearchStoreConflict, match="historical and read-only"):
        store.append_agent_run_event(historical.id, "run_failed", {})

    assert store.prune_agent_stream_events(retention_days=1) == 0
    assert store.get_agent_run(historical.id) == historical
    assert store.get_skill_plan(plan.id) == plan
    assert store.list_agent_run_events(historical.id) == [event]


def test_database_trigger_fences_a_stale_v2_writer_after_generation_advance(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "writer-trigger.sqlite3")
    store.compare_and_swap_research_writer_control(
        expected_generation=ResearchWriterGeneration.V2,
        expected_generation_epoch=1,
        target_generation=ResearchWriterGeneration.V3,
        decision_receipt_hash="9" * 64,
        changed_at=NOW,
    )
    stale_v2 = _run(
        run_id="run_stale_v2_trigger",
        client_turn_id="turn_stale_v2_trigger",
        thread_id="thread_stale_v2_trigger",
    ).model_copy(
        update={
            "orchestration_version": "research-v2",
            "orchestration_mode": "preview",
            "writer_generation_epoch": 1,
        }
    )

    with (
        pytest.raises(sqlite3.IntegrityError, match="research writer admission fenced"),
        store._connect() as connection,
    ):
        connection.execute(
            "INSERT INTO agent_runs(id, payload, updated_at, orchestration_version) VALUES (?, ?, ?, ?)",
            (
                stale_v2.id,
                stale_v2.model_dump_json(),
                stale_v2.updated_at.isoformat(),
                stale_v2.orchestration_version,
            ),
        )

    ordinary = _run(
        run_id="run_v1_after_cutover",
        client_turn_id="turn_v1_after_cutover",
        thread_id="thread_v1_after_cutover",
    )
    assert store.save_agent_run(ordinary).orchestration_version == "v1"


def test_database_trigger_rejects_a_stale_epoch_for_the_active_generation(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "writer-epoch-trigger.sqlite3")
    store.compare_and_swap_research_writer_control(
        expected_generation=ResearchWriterGeneration.V2,
        expected_generation_epoch=1,
        target_generation=ResearchWriterGeneration.V3,
        decision_receipt_hash="8" * 64,
        changed_at=NOW,
    )
    stale_epoch = _run(
        run_id="run_stale_v3_epoch",
        client_turn_id="turn_stale_v3_epoch",
        thread_id="thread_stale_v3_epoch",
    ).model_copy(
        update={
            "orchestration_version": "research-v3",
            "orchestration_mode": "preview",
            "writer_generation_epoch": 99,
        }
    )

    with pytest.raises(sqlite3.IntegrityError, match="research writer admission fenced"):
        store.save_agent_run(stale_epoch)


def test_research_run_creation_is_atomic_and_replay_precedes_generation_change(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "atomic-create.sqlite3")
    coordinator = ResearchRunCreationCoordinator(store)
    with store._connect() as connection:
        connection.execute(
            "CREATE TABLE research_gate2_marker(run_id TEXT PRIMARY KEY, generation TEXT NOT NULL)"
        )

    proposed = _run(
        run_id="run_gate2_v2",
        client_turn_id="turn_gate2_replay",
        thread_id="thread_gate2_replay",
    )
    historical = proposed.model_copy(
        update={
            "orchestration_version": "research-v2",
            "orchestration_mode": "preview",
            "writer_generation_epoch": 1,
        }
    )
    store.claim_new_agent_run(historical.model_copy(update={"orchestration_version": "v1"}))
    with store._connect() as connection:
        connection.execute(
            "UPDATE agent_runs SET payload = ?, orchestration_version = ? WHERE id = ?",
            (historical.model_dump_json(), "research-v2", historical.id),
        )
        connection.execute(
            "INSERT INTO research_gate2_marker(run_id, generation) VALUES (?, ?)",
            (historical.id, historical.orchestration_version),
        )

    assert _count(store, "SELECT COUNT(*) FROM research_gate2_marker") == 1

    store.compare_and_swap_research_writer_control(
        expected_generation=ResearchWriterGeneration.V2,
        expected_generation_epoch=1,
        target_generation=ResearchWriterGeneration.V3,
        decision_receipt_hash="c" * 64,
        changed_at=NOW,
    )
    decision_v3 = ResearchRolloutDecision(
        target="research-v3",
        mode="preview",
        reason="v3_preview_allowlisted",
    )
    initializer_calls = 0

    def unexpected_initializer(_connection: sqlite3.Connection, _run: AgentRun) -> None:
        nonlocal initializer_calls
        initializer_calls += 1

    replayed, replay_created = coordinator.claim(
        proposed,
        decision=decision_v3,
        initialize_version_state=unexpected_initializer,
    )

    assert replay_created is False
    assert replayed.id == historical.id
    assert replayed.orchestration_version == "research-v2"
    assert replayed.writer_generation_epoch == 1
    assert initializer_calls == 0


def test_research_run_creation_fences_stale_epoch_and_rolls_back_initializer_failure(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "atomic-create-failure.sqlite3")
    with store._connect() as connection:
        connection.execute(
            "CREATE TABLE research_gate2_marker(run_id TEXT PRIMARY KEY, generation TEXT NOT NULL)"
        )

    stale = _run(
        run_id="run_gate2_stale",
        client_turn_id="turn_gate2_stale",
        thread_id="thread_gate2_stale",
    ).model_copy(
        update={
            "orchestration_version": "research-v2",
            "orchestration_mode": "preview",
            "writer_generation_epoch": 1,
        }
    )
    with pytest.raises(ResearchStoreConflict, match="research-v2 writer is retired"):
        store.claim_research_agent_run(
            stale,
            expected_generation=ResearchWriterGeneration.V2,
            expected_generation_epoch=1,
            expected_lifecycle_state=ResearchWriterLifecycle.ACTIVE,
            initialize_version_state=lambda _connection, _run: None,
        )

    store.compare_and_swap_research_writer_control(
        expected_generation=ResearchWriterGeneration.V2,
        expected_generation_epoch=1,
        target_generation=ResearchWriterGeneration.V3,
        decision_receipt_hash="d" * 64,
        changed_at=NOW,
    )

    coordinator = ResearchRunCreationCoordinator(store)
    decision_v3 = ResearchRolloutDecision(
        target="research-v3",
        mode="preview",
        reason="v3_preview_allowlisted",
    )
    proposed = _run(
        run_id="run_gate2_rollback",
        client_turn_id="turn_gate2_rollback",
        thread_id="thread_gate2_rollback",
    )

    def failing_initializer(connection: sqlite3.Connection, run: AgentRun) -> None:
        connection.execute(
            "INSERT INTO research_gate2_marker(run_id, generation) VALUES (?, ?)",
            (run.id, run.orchestration_version),
        )
        raise RuntimeError("synthetic initializer failure")

    with pytest.raises(RuntimeError, match="synthetic initializer failure"):
        coordinator.claim(
            proposed,
            decision=decision_v3,
            initialize_version_state=failing_initializer,
        )

    assert store.get_agent_run(proposed.id) is None
    assert store.get_agent_run_by_client_turn(proposed.user_id, proposed.client_turn_id or "") is None
    assert _count(store, "SELECT COUNT(*) FROM research_gate2_marker") == 0
