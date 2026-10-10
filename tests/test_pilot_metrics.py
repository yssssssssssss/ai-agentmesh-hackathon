from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta

from agentmesh.pilot_metrics import PilotEvents, compute_pilot_metrics, load_pilot_events, open_read_only

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)


def _days_ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


def test_empty_pilot_reports_zero_counts_and_unknown_rates() -> None:
    metrics = compute_pilot_metrics(PilotEvents(), now=NOW, days=7)

    assert metrics["users"] == {"active": 0, "returning": 0, "daily_active": {}}
    assert metrics["memory"]["reach"] is None
    assert metrics["memory"]["acceptance"] is None
    assert metrics["tasks"]["delivery"] is None


def test_returning_users_are_active_on_two_distinct_days() -> None:
    events = PilotEvents(
        user_messages=[
            ("alice", _days_ago(1)),
            ("alice", _days_ago(3)),
            ("bob", _days_ago(2)),
            ("bob", _days_ago(2.01)),
        ]
    )

    users = compute_pilot_metrics(events, now=NOW, days=7)["users"]

    assert users["active"] == 2
    assert users["returning"] == 1
    assert users["daily_active"] == {"2026-10-07": 1, "2026-10-08": 1, "2026-10-09": 1}


def test_events_outside_the_window_are_ignored() -> None:
    events = PilotEvents(
        user_messages=[("alice", _days_ago(8))],
        runs=[("run_old", _days_ago(10))],
        memory_use_run_ids=[("run_old", _days_ago(10))],
        memory_review_statuses=[("accepted", _days_ago(9))],
        task_review_statuses=[("accepted", _days_ago(9))],
    )

    metrics = compute_pilot_metrics(events, now=NOW, days=7)

    assert metrics["users"]["active"] == 0
    assert metrics["memory"]["runs"] == 0
    assert metrics["memory"]["acceptance"] is None
    assert metrics["tasks"]["delivery"] is None


def test_memory_reach_counts_runs_that_received_memory_once() -> None:
    events = PilotEvents(
        runs=[("run_1", _days_ago(1)), ("run_2", _days_ago(1)), ("run_3", _days_ago(2)), ("run_4", _days_ago(2))],
        memory_use_run_ids=[("run_1", _days_ago(1)), ("run_1", _days_ago(1)), ("run_3", _days_ago(2))],
    )

    memory = compute_pilot_metrics(events, now=NOW, days=7)["memory"]

    assert memory["runs"] == 4
    assert memory["runs_with_memory"] == 2
    assert memory["reach"] == 0.5


def test_acceptance_and_delivery_ignore_pending_and_cancelled_reviews() -> None:
    events = PilotEvents(
        memory_review_statuses=[
            ("accepted", _days_ago(1)),
            ("rejected", _days_ago(1)),
            ("pending", _days_ago(1)),
            ("cancelled", _days_ago(1)),
        ],
        task_review_statuses=[
            ("accepted", _days_ago(1)),
            ("accepted", _days_ago(2)),
            ("changes_requested", _days_ago(2)),
            ("rejected", _days_ago(3)),
            ("pending", _days_ago(1)),
        ],
    )

    metrics = compute_pilot_metrics(events, now=NOW, days=7)

    assert metrics["memory"]["accepted"] == 1
    assert metrics["memory"]["rejected"] == 1
    assert metrics["memory"]["acceptance"] == 0.5
    assert metrics["tasks"] == {"accepted": 2, "changes_requested": 1, "rejected": 1, "delivery": 0.5}


def test_window_must_be_positive() -> None:
    import pytest

    with pytest.raises(ValueError, match="days must be between 1 and 365"):
        compute_pilot_metrics(PilotEvents(), now=NOW, days=0)


def _seed(path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE records (collection TEXT, id TEXT, payload TEXT, created_order INTEGER PRIMARY KEY);
        CREATE TABLE agent_runs (id TEXT PRIMARY KEY, payload TEXT, updated_at TEXT);
        CREATE TABLE task_reviews (id TEXT PRIMARY KEY, status TEXT, updated_at TEXT);
        CREATE TABLE memory_reviews (id TEXT PRIMARY KEY, status TEXT, updated_at TEXT);
        """
    )
    day = _days_ago(1).isoformat()
    connection.executemany(
        "INSERT INTO records(collection, id, payload) VALUES (?, ?, ?)",
        [
            ("chat_threads", "t1", '{"id": "t1", "user_id": "alice"}'),
            ("chat_messages", "m1", f'{{"thread_id": "t1", "role": "user", "created_at": "{day}"}}'),
            ("chat_messages", "m2", f'{{"thread_id": "t1", "role": "assistant", "created_at": "{day}"}}'),
            ("memory_use_receipts", "r1", f'{{"run_id": "run_1", "created_at": "{day}"}}'),
        ],
    )
    connection.execute("INSERT INTO agent_runs VALUES ('run_1', ?, ?)", (f'{{"created_at": "{day}"}}', day))
    connection.execute("INSERT INTO task_reviews VALUES ('tr1', 'accepted', ?)", (day,))
    connection.execute("INSERT INTO memory_reviews VALUES ('mr1', 'rejected', ?)", (day,))
    connection.commit()
    connection.close()


def test_loader_reads_a_database_without_modifying_it(tmp_path) -> None:
    path = tmp_path / "pilot.sqlite3"
    _seed(path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    with open_read_only(path) as connection:
        metrics = compute_pilot_metrics(load_pilot_events(connection), now=NOW, days=7)

    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert metrics["users"]["active"] == 1
    assert metrics["memory"]["reach"] == 1.0
    assert metrics["memory"]["acceptance"] == 0.0
    assert metrics["tasks"]["delivery"] == 1.0


def test_read_only_connection_rejects_writes(tmp_path) -> None:
    import pytest

    path = tmp_path / "pilot.sqlite3"
    _seed(path)

    with open_read_only(path) as connection, pytest.raises(sqlite3.OperationalError):
        connection.execute("DELETE FROM task_reviews")


def test_missing_database_is_reported_instead_of_created(tmp_path) -> None:
    import pytest

    path = tmp_path / "missing.sqlite3"

    with pytest.raises(FileNotFoundError):
        open_read_only(path)
    assert not path.exists()


def test_script_prints_metrics_and_reports_bad_input(tmp_path, capsys) -> None:
    import json

    from scripts.pilot_metrics import main

    path = tmp_path / "pilot.sqlite3"
    _seed(path)

    assert main(["--db", str(path), "--days", "30"]) == 0
    assert json.loads(capsys.readouterr().out)["tasks"]["accepted"] == 1
    assert main(["--db", str(tmp_path / "missing.sqlite3")]) == 2
    assert main(["--db", str(path), "--days", "0"]) == 2
