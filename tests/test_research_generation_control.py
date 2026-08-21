from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from agentmesh.agent_runtime.settings import (
    SkillOrchestrationMode,
    research_preview_allowlist,
)
from agentmesh.models import AgentRun, AgentRunStatus, SkillOrchestrationRequestMode
from agentmesh.research_orchestration.current import (
    RESEARCH_WRITER_CONTROL_SEED_HASH,
    ResearchRolloutDecision,
    ResearchRunCreationCoordinator,
    ResearchWriterGeneration,
    decide_research_rollout,
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


def test_writer_control_is_seeded_to_v2_and_advances_once(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "writer-control.sqlite3")

    seeded = store.get_research_writer_control()

    assert seeded.active_generation == ResearchWriterGeneration.V2
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


@pytest.mark.parametrize(
    ("eligible", "mode", "generation", "allowlisted", "expected"),
    [
        (
            False,
            SkillOrchestrationMode.EXECUTE,
            ResearchWriterGeneration.V3,
            True,
            ("v1", "off", "not_research_eligible"),
        ),
        (
            True,
            SkillOrchestrationMode.OFF,
            ResearchWriterGeneration.V2,
            True,
            ("v1", "off", "orchestration_off"),
        ),
        (
            True,
            SkillOrchestrationMode.PREVIEW,
            ResearchWriterGeneration.V2,
            False,
            ("research-v2", "preview", "active_research_v2"),
        ),
        (
            True,
            SkillOrchestrationMode.EXECUTE,
            ResearchWriterGeneration.V2,
            False,
            ("research-v2", "execute", "active_research_v2"),
        ),
        (
            True,
            SkillOrchestrationMode.PREVIEW,
            ResearchWriterGeneration.V3,
            False,
            ("v1", "off", "v3_preview_not_allowlisted"),
        ),
        (
            True,
            SkillOrchestrationMode.PREVIEW,
            ResearchWriterGeneration.V3,
            True,
            ("research-v3", "preview", "v3_preview_allowlisted"),
        ),
        (
            True,
            SkillOrchestrationMode.EXECUTE,
            ResearchWriterGeneration.V3,
            True,
            ("blocked", "off", "v3_execute_not_authorized"),
        ),
    ],
)
def test_rollout_decision_never_uses_allowlist_to_select_a_generation(
    eligible: bool,
    mode: SkillOrchestrationMode,
    generation: ResearchWriterGeneration,
    allowlisted: bool,
    expected: tuple[str, str, str],
) -> None:
    decision = decide_research_rollout(
        research_eligible=eligible,
        configured_mode=mode,
        active_generation=generation,
        user_id="user_gate2_preview_1",
        preview_allowlist=(
            frozenset({"user_gate2_preview_1"}) if allowlisted else frozenset()
        ),
    )

    assert (decision.target, decision.mode, decision.reason) == expected


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

    with pytest.raises(sqlite3.IntegrityError, match="research writer generation fenced"):
        store.save_agent_run(stale_v2)

    ordinary = _run(
        run_id="run_v1_after_cutover",
        client_turn_id="turn_v1_after_cutover",
        thread_id="thread_v1_after_cutover",
    )
    assert store.save_agent_run(ordinary).orchestration_version == "v1"


def test_research_run_creation_is_atomic_and_replay_precedes_generation_change(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "atomic-create.sqlite3")
    coordinator = ResearchRunCreationCoordinator(store)
    with store._connect() as connection:
        connection.execute(
            "CREATE TABLE research_gate2_marker(run_id TEXT PRIMARY KEY, generation TEXT NOT NULL)"
        )

    decision_v2 = ResearchRolloutDecision(
        target="research-v2",
        mode="preview",
        reason="active_research_v2",
    )
    proposed = _run(
        run_id="run_gate2_v2",
        client_turn_id="turn_gate2_replay",
        thread_id="thread_gate2_replay",
    )

    claimed, created = coordinator.claim(
        proposed,
        decision=decision_v2,
        initialize_version_state=lambda connection, run: connection.execute(
            "INSERT INTO research_gate2_marker(run_id, generation) VALUES (?, ?)",
            (run.id, run.orchestration_version),
        ),
    )

    assert created is True
    assert claimed.orchestration_version == "research-v2"
    assert claimed.writer_generation_epoch == 1
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
    assert replayed.id == claimed.id
    assert replayed.orchestration_version == "research-v2"
    assert replayed.writer_generation_epoch == 1
    assert initializer_calls == 0


def test_research_run_creation_fences_stale_epoch_and_rolls_back_initializer_failure(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "atomic-create-failure.sqlite3")
    with store._connect() as connection:
        connection.execute(
            "CREATE TABLE research_gate2_marker(run_id TEXT PRIMARY KEY, generation TEXT NOT NULL)"
        )
    store.compare_and_swap_research_writer_control(
        expected_generation=ResearchWriterGeneration.V2,
        expected_generation_epoch=1,
        target_generation=ResearchWriterGeneration.V3,
        decision_receipt_hash="d" * 64,
        changed_at=NOW,
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
    with pytest.raises(ResearchStoreConflict, match="generation changed"):
        store.claim_research_agent_run(
            stale,
            expected_generation=ResearchWriterGeneration.V2,
            expected_generation_epoch=1,
            initialize_version_state=lambda _connection, _run: None,
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
