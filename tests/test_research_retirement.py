from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from agentmesh.models import AgentRun, AgentRunStatus, InboxItem, Scope
from agentmesh.research_orchestration.api import ResearchOwnerScope
from agentmesh.store import SQLiteStore


def _run(run_id: str, *, orchestration_version: str = "v1") -> AgentRun:
    return AgentRun(
        id=run_id,
        thread_id=f"thread_{run_id}",
        user_id="user",
        workspace_id="workspace",
        project_id="project",
        input_text="test",
        orchestration_version=orchestration_version,
    )


def test_fresh_store_has_no_research_v3_or_writer_control_schema(tmp_path) -> None:  # noqa: ANN001
    database = tmp_path / "fresh.sqlite3"
    SQLiteStore(database)
    reopened = SQLiteStore(database)

    reopened.save_agent_run(_run("run_v1_after_reopen"))
    with reopened._connect() as connection:
        object_names = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'trigger')"
            ).fetchall()
        }

    assert "research_writer_control" not in object_names
    assert not any(name.startswith("research_v3_") for name in object_names)
    assert "retired_research_run_admission_fence" in object_names
    assert reopened.get_agent_run("run_v1_after_reopen") is not None


@pytest.mark.parametrize("retired_version", ["research-v2", "research-v3"])
def test_store_upgrade_removes_legacy_writer_triggers_without_dropping_data(
    tmp_path,  # noqa: ANN001
    retired_version: str,
) -> None:
    database = tmp_path / "legacy-writer-control.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE agent_runs (
                id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                orchestration_version TEXT NOT NULL DEFAULT 'v1'
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE research_writer_control (
                control_key TEXT PRIMARY KEY,
                marker TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO research_writer_control(control_key, marker) VALUES ('global', 'keep')"
        )
        for trigger_name in (
            "agent_runs_research_writer_guard",
            "research_writer_generation_fence",
            "research_writer_admission_fence_v2",
        ):
            connection.execute(
                f"""CREATE TRIGGER {trigger_name}
                BEFORE INSERT ON agent_runs
                BEGIN
                    SELECT RAISE(ABORT, 'legacy writer trigger');
                END"""  # noqa: S608
            )

    repository = SQLiteStore(database)
    repository.save_agent_run(_run("run_v1_after_upgrade"))
    with repository._connect() as connection:
        legacy_triggers = connection.execute(
            """SELECT name FROM sqlite_master
            WHERE type = 'trigger' AND name IN (
                'agent_runs_research_writer_guard',
                'research_writer_generation_fence',
                'research_writer_admission_fence_v2'
            )"""
        ).fetchall()
        retained = connection.execute(
            "SELECT marker FROM research_writer_control WHERE control_key = 'global'"
        ).fetchone()

        historical = _run(f"run_retired_{retired_version}", orchestration_version=retired_version)
        with pytest.raises(sqlite3.IntegrityError, match="retired research writer is disabled"):
            connection.execute(
                "INSERT INTO agent_runs(id, payload, updated_at, orchestration_version) VALUES (?, ?, ?, ?)",
                (
                    historical.id,
                    historical.model_dump_json(),
                    historical.updated_at.isoformat(),
                    historical.orchestration_version,
                ),
            )

    assert legacy_triggers == []
    assert retained["marker"] == "keep"
    assert repository.get_agent_run("run_v1_after_upgrade") is not None


def test_startup_reconciliation_leaves_legacy_v3_rows_byte_identical(tmp_path) -> None:  # noqa: ANN001
    database = tmp_path / "legacy-v3.sqlite3"
    repository = SQLiteStore(database)
    historical = _run("run_legacy_v3", orchestration_version="research-v3").model_copy(
        update={"status": AgentRunStatus.RUNNING}
    )
    payload = historical.model_dump_json()

    with repository._connect() as connection:
        connection.execute("DROP TRIGGER retired_research_run_admission_fence")
        connection.execute(
            "INSERT INTO agent_runs(id, payload, updated_at, orchestration_version) VALUES (?, ?, ?, ?)",
            (historical.id, payload, historical.updated_at.isoformat(), historical.orchestration_version),
        )
        connection.execute("CREATE TABLE research_v3_runs(run_id TEXT PRIMARY KEY, payload BLOB NOT NULL)")
        connection.execute(
            "INSERT INTO research_v3_runs(run_id, payload) VALUES (?, ?)",
            (historical.id, b"legacy-v3-row"),
        )

    reopened = SQLiteStore(database)
    assert reopened.reconcile_orphaned_agent_runs() == 0
    reopened.save_agent_run(_run("run_foreign_v1"))
    foreign_owner = ResearchOwnerScope(user_id="other", workspace_id="other", project_id="other")
    assert reopened.load_context(historical.id, owner=foreign_owner) is None
    assert reopened.load_context("run_foreign_v1", owner=foreign_owner) is None
    with reopened._connect() as connection:
        run_row = connection.execute(
            "SELECT payload FROM agent_runs WHERE id = ?", (historical.id,)
        ).fetchone()
        v3_row = connection.execute(
            "SELECT payload FROM research_v3_runs WHERE run_id = ?", (historical.id,)
        ).fetchone()

    assert run_row["payload"] == payload
    assert v3_row["payload"] == b"legacy-v3-row"


def test_store_mutators_trust_either_v3_projection_and_leave_legacy_rows_unchanged(tmp_path) -> None:  # noqa: ANN001
    repository = SQLiteStore(tmp_path / "legacy-v3-mutators.sqlite3")
    legacy = _run("run_legacy_v3_projection").model_copy(
        update={"status": AgentRunStatus.RUNNING}
    )
    repository.save_agent_run(legacy)
    original_payload = legacy.model_dump_json()
    ignored_inbox = InboxItem(
        id="inbox_must_not_be_created",
        title="Do not create",
        summary="Legacy v3 is read-only",
        item_type="sdk_tool_approval",
        scope=Scope.PRIVATE,
        user_id=legacy.user_id,
        workspace_id=legacy.workspace_id,
        project_id=legacy.project_id,
        metadata={"run_id": legacy.id},
    )
    with repository._connect() as connection:
        connection.execute(
            "UPDATE agent_runs SET orchestration_version = 'research-v3' WHERE id = ?",
            (legacy.id,),
        )

    assert repository.pause_agent_run_with_inbox(
        run_id=legacy.id,
        paused_state={"kind": "tool_approval"},
        inbox_item=ignored_inbox,
        interruptions=[],
    ) is None
    assert repository.consume_agent_run_tool_call(legacy.id) is None
    assert repository.cancel_agent_run_tree(legacy.id, user_id=legacy.user_id).status == AgentRunStatus.RUNNING  # type: ignore[union-attr]
    assert repository.reconcile_orphaned_agent_runs() == 0

    fresh = _run("run_after_legacy_v3_projection").model_copy(
        update={
            "thread_id": legacy.thread_id,
            "client_turn_id": "turn_after_legacy_v3_projection",
        }
    )
    claimed, created = repository.claim_new_agent_run(fresh)
    assert created is True
    assert claimed.id == fresh.id

    with repository._connect() as connection:
        stored = connection.execute(
            "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
            (legacy.id,),
        ).fetchone()
        event_count = connection.execute(
            "SELECT COUNT(*) FROM agent_run_events WHERE run_id = ?",
            (legacy.id,),
        ).fetchone()[0]
        inbox_count = connection.execute(
            "SELECT COUNT(*) FROM records WHERE collection = 'inbox_items' AND id = ?",
            (ignored_inbox.id,),
        ).fetchone()[0]

    assert stored["payload"] == original_payload
    assert stored["orchestration_version"] == "research-v3"
    assert event_count == 0
    assert inbox_count == 0


def test_approval_mutators_leave_column_projected_legacy_v3_unchanged(tmp_path) -> None:  # noqa: ANN001
    repository = SQLiteStore(tmp_path / "legacy-v3-approval.sqlite3")
    expired_at = datetime.now(UTC) - timedelta(hours=25)
    legacy = _run("run_legacy_v3_approval").model_copy(
        update={
            "status": AgentRunStatus.WAITING_APPROVAL,
            "paused_state": {"kind": "tool_approval", "expires_at": expired_at.isoformat()},
        }
    )
    repository.save_agent_run(legacy)
    inbox = repository.add_inbox_item(
        InboxItem(
            id="inbox_legacy_v3_approval",
            title="Approve tool",
            summary="Waiting",
            item_type="sdk_tool_approval",
            scope=Scope.PRIVATE,
            user_id=legacy.user_id,
            workspace_id=legacy.workspace_id,
            project_id=legacy.project_id,
            metadata={"run_id": legacy.id},
            created_at=expired_at,
        )
    )
    with repository._connect() as connection:
        connection.execute(
            "UPDATE agent_runs SET orchestration_version = 'research-v3' WHERE id = ?",
            (legacy.id,),
        )
        original_run_payload = connection.execute(
            "SELECT payload FROM agent_runs WHERE id = ?",
            (legacy.id,),
        ).fetchone()["payload"]
        original_inbox_payload = connection.execute(
            "SELECT payload FROM records WHERE collection = 'inbox_items' AND id = ?",
            (inbox.id,),
        ).fetchone()["payload"]

    assert repository.claim_agent_run_for_resume(legacy.id, legacy.user_id, inbox_id=inbox.id) is None
    assert repository.expire_agent_run_approval(
        run_id=legacy.id,
        user_id=legacy.user_id,
        inbox_id=inbox.id,
    ) is False

    with repository._connect() as connection:
        run_payload = connection.execute(
            "SELECT payload FROM agent_runs WHERE id = ?",
            (legacy.id,),
        ).fetchone()["payload"]
        inbox_payload = connection.execute(
            "SELECT payload FROM records WHERE collection = 'inbox_items' AND id = ?",
            (inbox.id,),
        ).fetchone()["payload"]
        event_count = connection.execute(
            "SELECT COUNT(*) FROM agent_run_events WHERE run_id = ?",
            (legacy.id,),
        ).fetchone()[0]

    assert run_payload == original_run_payload
    assert inbox_payload == original_inbox_payload
    assert event_count == 0
