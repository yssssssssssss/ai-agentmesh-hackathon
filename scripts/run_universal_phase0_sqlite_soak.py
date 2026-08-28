#!/usr/bin/env python3
"""Production-shaped SQLite concurrency soak for universal orchestration Phase 0."""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import shutil
import sqlite3
import statistics
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from agentmesh.canonical_json import canonical_json_bytes
from agentmesh.models import (
    AgentPlanningContractVersion,
    AgentRun,
    AgentRunStatus,
)
from agentmesh.store import SQLiteStore


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    rank = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentile)))
    return ordered[rank]


def _snapshot_payload(size_bytes: int = 32 * 1024) -> dict[str, object]:
    prefix = {
        "candidate_snapshot_hash": "a" * 64,
        "retrieval_policy_version": "phase0-probe-v1",
        "candidate_snapshot": "",
    }
    fixed_size = len(canonical_json_bytes(prefix))
    if fixed_size > size_bytes:
        raise ValueError("snapshot envelope exceeds requested size")
    prefix["candidate_snapshot"] = "x" * (size_bytes - fixed_size)
    actual_size = len(canonical_json_bytes(prefix))
    if actual_size != size_bytes:
        raise RuntimeError(f"snapshot payload size mismatch: {actual_size}")
    return prefix


def _configure_journal(database: Path, journal_mode: str) -> str:
    with sqlite3.connect(database) as connection:
        if journal_mode != "current":
            actual = str(connection.execute(f"PRAGMA journal_mode={journal_mode}").fetchone()[0])
        else:
            actual = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)") if actual == "wal" else None
        return actual


def _run_fixture(index: int, *, prefix: str = "run_soak") -> AgentRun:
    created_at = datetime(2026, 8, 28, tzinfo=UTC)
    return AgentRun(
        id=f"{prefix}_{index}",
        thread_id=f"thread_{prefix}_{index}",
        user_id="user_phase0_soak",
        workspace_id="workspace_phase0_soak",
        project_id="project_phase0_soak",
        input_text="phase zero SQLite concurrency soak",
        status=AgentRunStatus.RUNNING,
        planning_contract_version=AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1,
        created_at=created_at,
        updated_at=created_at,
    )


def _checkpoint(database: Path) -> float:
    started = perf_counter()
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    return (perf_counter() - started) * 1000


def _sqlite_footprint(database: Path) -> int:
    return sum(
        path.stat().st_size
        for path in (database, Path(f"{database}-wal"))
        if path.exists()
    )


def _measure_per_run_increments(
    repository: SQLiteStore,
    database: Path,
    *,
    sample_runs: int,
    snapshot_payload: dict[str, object],
) -> list[float]:
    increments: list[float] = []
    for index in range(sample_runs):
        _checkpoint(database)
        before = _sqlite_footprint(database)
        run = _run_fixture(index, prefix="run_capacity")
        repository.save_agent_run(run)
        repository.append_agent_run_event(run.id, "skill_search_completed", snapshot_payload)
        repository.append_agent_run_event(
            run.id,
            "tool_call_claimed",
            {"call_id": f"capacity_call_{index}", "node_id": "node_capacity", "side_effect": "read"},
        )
        repository.append_agent_run_event(
            run.id,
            "tool_call_settled",
            {"call_id": f"capacity_call_{index}", "node_id": "node_capacity", "side_effect": "read"},
        )
        _checkpoint(database)
        increments.append(float(max(0, _sqlite_footprint(database) - before)))
    return increments


def run_soak(
    database: Path,
    *,
    duration_seconds: float,
    writer_count: int,
    reader_count: int,
    journal_mode: str,
    expected_runs_per_day: int | None,
    writer_interval_ms: float = 5.0,
    reader_interval_ms: float = 25.0,
    capacity_sample_runs: int = 100,
) -> dict[str, object]:
    repository = SQLiteStore(database)
    actual_journal_mode = _configure_journal(database, journal_mode)
    snapshot_payload = _snapshot_payload()
    per_run_increments = _measure_per_run_increments(
        repository,
        database,
        sample_runs=capacity_sample_runs,
        snapshot_payload=snapshot_payload,
    )
    runs = [_run_fixture(index) for index in range(writer_count)]
    for run in runs:
        repository.save_agent_run(run)

    starting_bytes = _sqlite_footprint(database)
    deadline = perf_counter() + duration_seconds
    stop = threading.Event()
    metrics_lock = threading.Lock()
    write_latencies: list[float] = []
    read_latencies: list[float] = []
    lock_errors: list[str] = []
    writer_successes = [0 for _ in runs]
    reader_calls = [0 for _ in range(reader_count)]
    wal_peak_bytes = 0

    def record_lock_error(error: BaseException) -> None:
        if isinstance(error, sqlite3.OperationalError) and "locked" in str(error).lower():
            with metrics_lock:
                lock_errors.append(str(error))
            return
        raise error

    def writer(index: int) -> None:
        run = runs[index]
        iteration = 0
        event_types = ("skill_search_completed", "tool_call_claimed", "tool_call_settled")
        while not stop.is_set() and perf_counter() < deadline:
            event_type = event_types[iteration % len(event_types)]
            payload = snapshot_payload if event_type == "skill_search_completed" else {
                "call_id": f"call_{index}_{iteration // 3}",
                "node_id": f"node_{index}",
                "side_effect": "read",
            }
            started = perf_counter()
            try:
                repository.append_agent_run_event(run.id, event_type, payload)
            except BaseException as error:
                record_lock_error(error)
            else:
                elapsed_ms = (perf_counter() - started) * 1000
                with metrics_lock:
                    write_latencies.append(elapsed_ms)
                    writer_successes[index] += 1
            iteration += 1
            stop.wait(writer_interval_ms / 1000)

    def reader(index: int) -> None:
        run = runs[index % len(runs)]
        after_sequence = 0
        while not stop.is_set() and perf_counter() < deadline:
            started = perf_counter()
            try:
                events = repository.list_agent_run_events(run.id, after_sequence=after_sequence)
            except BaseException as error:
                record_lock_error(error)
            else:
                if events:
                    after_sequence = events[-1].sequence
                elapsed_ms = (perf_counter() - started) * 1000
                with metrics_lock:
                    read_latencies.append(elapsed_ms)
                    reader_calls[index] += 1
            stop.wait(reader_interval_ms / 1000)

    async def exercise() -> float:
        nonlocal wal_peak_bytes
        loop_lag_max_ms = 0.0
        with ThreadPoolExecutor(max_workers=writer_count + reader_count) as executor:
            futures = [executor.submit(writer, index) for index in range(writer_count)]
            futures.extend(executor.submit(reader, index) for index in range(reader_count))
            expected_tick = perf_counter()
            while perf_counter() < deadline:
                await asyncio.sleep(0.01)
                observed = perf_counter()
                loop_lag_max_ms = max(loop_lag_max_ms, max(0.0, observed - expected_tick - 0.01) * 1000)
                expected_tick = observed
                wal_path = Path(f"{database}-wal")
                if wal_path.exists():
                    wal_peak_bytes = max(wal_peak_bytes, wal_path.stat().st_size)
            stop.set()
            for future in futures:
                future.result()
        return loop_lag_max_ms

    loop_lag_max_ms = asyncio.run(exercise())
    expected_events = sum(writer_successes)
    with repository._read_connect() as connection:
        actual_events = int(
            connection.execute(
                "SELECT COUNT(*) FROM agent_run_events WHERE run_id LIKE 'run_soak_%'"
            ).fetchone()[0]
        )
        sequence_gaps = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT run_id, COUNT(*) AS count, MAX(sequence) AS max_sequence
                    FROM agent_run_events
                    WHERE run_id LIKE 'run_soak_%'
                    GROUP BY run_id
                    HAVING count != max_sequence
                )
                """
            ).fetchone()[0]
        )
    checkpoint_ms = _checkpoint(database) if actual_journal_mode == "wal" else 0.0

    ending_bytes = _sqlite_footprint(database)
    per_run_p99_bytes = _percentile(per_run_increments, 0.99)
    disk = shutil.disk_usage(database.parent)
    projected_90_day_bytes = (
        int(per_run_p99_bytes * expected_runs_per_day * 90)
        if expected_runs_per_day is not None
        else None
    )
    capacity_required_bytes = (
        2 * (ending_bytes + projected_90_day_bytes + ending_bytes)
        if projected_90_day_bytes is not None
        else None
    )
    capacity_passed = (
        disk.free >= capacity_required_bytes
        if capacity_required_bytes is not None
        else None
    )
    write_p95 = _percentile(write_latencies, 0.95)
    write_p99 = _percentile(write_latencies, 0.99)
    passed = (
        not lock_errors
        and expected_events == actual_events
        and sequence_gaps == 0
        and write_p95 <= 100
        and write_p99 <= 500
        and loop_lag_max_ms <= 100
        and capacity_passed is not False
    )
    return {
        "passed": passed,
        "runner": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python": platform.python_version(),
        },
        "duration_seconds": duration_seconds,
        "writer_count": writer_count,
        "reader_count": reader_count,
        "writer_interval_ms": writer_interval_ms,
        "reader_interval_ms": reader_interval_ms,
        "journal_mode": actual_journal_mode,
        "snapshot_payload_bytes": len(canonical_json_bytes(snapshot_payload)),
        "expected_events": expected_events,
        "actual_events": actual_events,
        "sequence_gap_groups": sequence_gaps,
        "database_bytes_start": starting_bytes,
        "database_bytes_end": ending_bytes,
        "capacity_sample_runs": capacity_sample_runs,
        "per_run_p99_bytes": round(per_run_p99_bytes, 3),
        "wal_peak_bytes": wal_peak_bytes,
        "checkpoint_ms": round(checkpoint_ms, 3),
        "write_latency_ms": {
            "mean": round(statistics.fmean(write_latencies), 3) if write_latencies else None,
            "p95": round(write_p95, 3),
            "p99": round(write_p99, 3),
            "max": round(max(write_latencies), 3) if write_latencies else None,
        },
        "read_latency_ms": {
            "mean": round(statistics.fmean(read_latencies), 3) if read_latencies else None,
            "p95": round(_percentile(read_latencies, 0.95), 3),
            "p99": round(_percentile(read_latencies, 0.99), 3),
            "max": round(max(read_latencies), 3) if read_latencies else None,
        },
        "event_loop_lag_max_ms": round(loop_lag_max_ms, 3),
        "lock_error_count": len(lock_errors),
        "lock_errors": sorted(set(lock_errors)),
        "writer_successes": writer_successes,
        "reader_calls": reader_calls,
        "disk_free_bytes": disk.free,
        "expected_runs_per_day": expected_runs_per_day,
        "projected_90_day_bytes": projected_90_day_bytes,
        "capacity_required_bytes": capacity_required_bytes,
        "capacity_passed": capacity_passed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path)
    parser.add_argument("--duration-seconds", type=float, default=1800)
    parser.add_argument("--writers", type=int, default=3)
    parser.add_argument("--readers", type=int, default=10)
    parser.add_argument("--journal-mode", choices=("current", "delete", "wal"), default="current")
    parser.add_argument("--expected-runs-per-day", type=int)
    parser.add_argument("--writer-interval-ms", type=float, default=5.0)
    parser.add_argument("--reader-interval-ms", type=float, default=25.0)
    parser.add_argument("--capacity-sample-runs", type=int, default=100)
    args = parser.parse_args()
    if (
        args.duration_seconds <= 0
        or args.writers < 1
        or args.readers < 1
        or args.writer_interval_ms < 0
        or args.reader_interval_ms < 0
        or args.capacity_sample_runs < 1
    ):
        parser.error("duration and counts must be positive; intervals must be non-negative")
    if args.expected_runs_per_day is not None and args.expected_runs_per_day < 1:
        parser.error("--expected-runs-per-day must be positive")

    if args.database is not None:
        result = run_soak(
            args.database,
            duration_seconds=args.duration_seconds,
            writer_count=args.writers,
            reader_count=args.readers,
            journal_mode=args.journal_mode,
            expected_runs_per_day=args.expected_runs_per_day,
            writer_interval_ms=args.writer_interval_ms,
            reader_interval_ms=args.reader_interval_ms,
            capacity_sample_runs=args.capacity_sample_runs,
        )
    else:
        with tempfile.TemporaryDirectory(prefix="agentmesh-phase0-soak-") as directory:
            result = run_soak(
                Path(directory) / "soak.sqlite3",
                duration_seconds=args.duration_seconds,
                writer_count=args.writers,
                reader_count=args.readers,
                journal_mode=args.journal_mode,
                expected_runs_per_day=args.expected_runs_per_day,
                writer_interval_ms=args.writer_interval_ms,
                reader_interval_ms=args.reader_interval_ms,
                capacity_sample_runs=args.capacity_sample_runs,
            )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
