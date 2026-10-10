"""Read-only pilot metrics: retention, memory reach and adoption, task delivery.

Operators run `scripts/pilot_metrics.py` against a live database; nothing here writes.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

Event = tuple[str, datetime]


@dataclass
class PilotEvents:
    user_messages: list[Event] = field(default_factory=list)  # (user_id, at)
    runs: list[Event] = field(default_factory=list)  # (run_id, created_at)
    memory_use_run_ids: list[Event] = field(default_factory=list)  # (run_id, created_at)
    memory_review_statuses: list[Event] = field(default_factory=list)  # (status, updated_at)
    task_review_statuses: list[Event] = field(default_factory=list)  # (status, updated_at)


def open_read_only(path: str | Path) -> sqlite3.Connection:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    connection = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def load_pilot_events(connection: sqlite3.Connection) -> PilotEvents:
    owners = dict(
        connection.execute(
            "SELECT id, json_extract(payload, '$.user_id') FROM records WHERE collection = 'chat_threads'"
        ).fetchall()
    )
    messages = connection.execute(
        """
        SELECT json_extract(payload, '$.thread_id'), json_extract(payload, '$.created_at')
        FROM records
        WHERE collection = 'chat_messages' AND json_extract(payload, '$.role') = 'user'
        """
    ).fetchall()
    receipts = connection.execute(
        """
        SELECT json_extract(payload, '$.run_id'), json_extract(payload, '$.created_at')
        FROM records WHERE collection = 'memory_use_receipts'
        """
    ).fetchall()
    runs = connection.execute("SELECT id, json_extract(payload, '$.created_at') FROM agent_runs").fetchall()
    return PilotEvents(
        user_messages=[(owners[thread], _parse(at)) for thread, at in messages if thread in owners and at],
        runs=[(run_id, _parse(at)) for run_id, at in runs if at],
        memory_use_run_ids=[(run_id, _parse(at)) for run_id, at in receipts if run_id and at],
        memory_review_statuses=[
            (status, _parse(at)) for status, at in connection.execute("SELECT status, updated_at FROM memory_reviews")
        ],
        task_review_statuses=[
            (status, _parse(at)) for status, at in connection.execute("SELECT status, updated_at FROM task_reviews")
        ],
    )


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def compute_pilot_metrics(events: PilotEvents, *, now: datetime, days: int) -> dict[str, object]:
    if not 1 <= days <= 365:
        raise ValueError("days must be between 1 and 365")
    since = now - timedelta(days=days)

    def recent(items: list[Event]) -> list[Event]:
        return [(key, at) for key, at in items if since <= at <= now]

    active_days: dict[str, set[str]] = defaultdict(set)
    for user_id, at in recent(events.user_messages):
        active_days[user_id].add(at.date().isoformat())
    daily: dict[str, set[str]] = defaultdict(set)
    for user_id, user_days in active_days.items():
        for day in user_days:
            daily[day].add(user_id)

    run_ids = {run_id for run_id, _ in recent(events.runs)}
    memory_run_ids = {run_id for run_id, _ in recent(events.memory_use_run_ids)} & run_ids
    memory_reviews = [status for status, _ in recent(events.memory_review_statuses)]
    task_reviews = [status for status, _ in recent(events.task_review_statuses)]
    memory_accepted, memory_rejected = memory_reviews.count("accepted"), memory_reviews.count("rejected")
    task_counts = {status: task_reviews.count(status) for status in ("accepted", "changes_requested", "rejected")}

    return {
        "window": {"days": days, "since": since.isoformat(), "until": now.isoformat()},
        "users": {
            "active": len(active_days),
            "returning": sum(len(user_days) >= 2 for user_days in active_days.values()),
            "daily_active": {day: len(users) for day, users in sorted(daily.items())},
        },
        "memory": {
            "runs": len(run_ids),
            "runs_with_memory": len(memory_run_ids),
            "reach": _ratio(len(memory_run_ids), len(run_ids)),
            "accepted": memory_accepted,
            "rejected": memory_rejected,
            "acceptance": _ratio(memory_accepted, memory_accepted + memory_rejected),
        },
        "tasks": {**task_counts, "delivery": _ratio(task_counts["accepted"], sum(task_counts.values()))},
    }


def render(metrics: dict[str, object]) -> str:
    return json.dumps(metrics, ensure_ascii=False, indent=2)
