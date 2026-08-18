from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agentmesh.models import AgentRun, AgentRunStatus
from agentmesh.store import SQLiteStore


def test_retention_preserves_stream_events_for_active_runs(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "active-retention.sqlite3")
    run = repository.save_agent_run(
        AgentRun(
            id="run_active_retention",
            thread_id="thread_active_retention",
            user_id="user",
            workspace_id="workspace",
            project_id="project",
            input_text="test",
            status=AgentRunStatus.WAITING_APPROVAL,
            paused_state={"state": "paused"},
        )
    )
    stream = repository.append_agent_run_event(run.id, "sdk_stream_event", {"delta": "old"})
    old = (datetime.now(UTC) - timedelta(days=60)).isoformat()
    with repository._connect() as connection:
        connection.execute("UPDATE agent_run_events SET created_at = ? WHERE id = ?", (old, stream.id))

    assert repository.prune_agent_stream_events(retention_days=30) == 0
    assert repository.list_agent_run_events(run.id)


def test_startup_reconciles_orphaned_running_runs(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "orphaned-run.sqlite3")
    repository.save_agent_run(
        AgentRun(
            id="run_orphaned",
            thread_id="thread_orphaned",
            user_id="user",
            workspace_id="workspace",
            project_id="project",
            input_text="test",
            status=AgentRunStatus.RUNNING,
        )
    )

    assert repository.reconcile_orphaned_agent_runs() == 1
    run = repository.get_agent_run("run_orphaned")
    assert run.status == AgentRunStatus.FAILED
    assert run.error_code == "process_restarted"
    assert repository.list_agent_run_events(run.id)[-1].event_type == "run_failed"


def test_retention_prunes_only_old_stream_deltas(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "retention.sqlite3")
    run = repository.save_agent_run(
        AgentRun(
            id="run_retention",
            thread_id="thread_retention",
            user_id="user",
            workspace_id="workspace",
            project_id="project",
            input_text="test",
            status=AgentRunStatus.COMPLETED,
        )
    )
    stream = repository.append_agent_run_event(run.id, "sdk_stream_event", {"delta": "old"})
    completed = repository.append_agent_run_event(run.id, "run_completed", {})
    old = (datetime.now(UTC) - timedelta(days=60)).isoformat()
    with repository._connect() as connection:  # test-only age fixture
        connection.execute(
            "UPDATE agent_run_events SET created_at = ? WHERE id IN (?, ?)",
            (old, stream.id, completed.id),
        )

    deleted = repository.prune_agent_stream_events(retention_days=30)

    assert deleted == 1
    assert [event.event_type for event in repository.list_agent_run_events(run.id)] == ["run_completed"]
