#!/usr/bin/env python3
"""Measure JSON planning-contract enumeration on the real SQLite repository."""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from agentmesh.models import (
    AgentPlanningContractVersion,
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
)
from agentmesh.store import SQLiteStore

_ACTIVE_CONTRACTS = {
    AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1,
    AgentPlanningContractVersion.DEEPSEARCH_FROZEN_V2,
}


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    rank = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentile)))
    return ordered[rank]


def _seed(repository: SQLiteStore, records: int) -> int:
    created_at = datetime(2026, 8, 28, tzinfo=UTC)
    rows: list[tuple[str, str, str, str]] = []
    expected_active = 0
    contracts = [
        AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1,
        AgentPlanningContractVersion.DEEPSEARCH_FROZEN_V2,
        AgentPlanningContractVersion.STANDARD_LEGACY_V1,
        None,
    ]
    for index in range(records):
        contract = contracts[index % len(contracts)]
        status = AgentRunStatus.FAILED if index % 10 == 0 else AgentRunStatus.PLANNING
        run = AgentRun(
            id=f"run_probe_{index:08d}",
            thread_id=f"thread_probe_{index:08d}",
            user_id="user_phase0_probe",
            workspace_id="workspace_phase0_probe",
            project_id="project_phase0_probe",
            input_text="phase zero planning contract storage probe",
            status=status,
            planning_mode=(
                contract.planning_mode
                if contract is not None
                else AgentPlanningMode.STANDARD
            ),
            planning_contract_version=contract,
            created_at=created_at,
            updated_at=created_at,
        )
        rows.append((run.id, run.model_dump_json(), run.updated_at.isoformat(), run.orchestration_version))
        if contract in _ACTIVE_CONTRACTS and status is AgentRunStatus.PLANNING:
            expected_active += 1
    with repository._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.executemany(
            "INSERT INTO agent_runs(id, payload, updated_at, orchestration_version) VALUES (?, ?, ?, ?)",
            rows,
        )
    return expected_active


def run_probe(database: Path, *, records: int, iterations: int) -> dict[str, object]:
    repository = SQLiteStore(database)
    expected_active = _seed(repository, records)
    reopened = SQLiteStore(database)

    for _ in range(5):
        reopened.list_active_agent_runs_for_planning_contracts(_ACTIVE_CONTRACTS)
    timings_ms: list[float] = []
    result_count = 0
    for _ in range(iterations):
        started = perf_counter()
        result_count = len(
            reopened.list_active_agent_runs_for_planning_contracts(_ACTIVE_CONTRACTS)
        )
        timings_ms.append((perf_counter() - started) * 1000)
    if result_count != expected_active:
        raise RuntimeError(
            f"planning-contract scan mismatch: expected={expected_active} actual={result_count}"
        )

    with reopened._read_connect() as connection:
        journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
    return {
        "database": str(database),
        "records": records,
        "active_matches": result_count,
        "iterations": iterations,
        "journal_mode": journal_mode,
        "database_bytes": database.stat().st_size,
        "latency_ms": {
            "mean": round(statistics.fmean(timings_ms), 3),
            "p50": round(_percentile(timings_ms, 0.50), 3),
            "p95": round(_percentile(timings_ms, 0.95), 3),
            "p99": round(_percentile(timings_ms, 0.99), 3),
            "max": round(max(timings_ms), 3),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path)
    parser.add_argument("--records", type=int, default=10_000)
    parser.add_argument("--iterations", type=int, default=100)
    args = parser.parse_args()
    if args.records < 1 or args.iterations < 1:
        parser.error("--records and --iterations must be positive")

    if args.database is not None:
        result = run_probe(args.database, records=args.records, iterations=args.iterations)
    else:
        with tempfile.TemporaryDirectory(prefix="agentmesh-phase0-contract-") as directory:
            result = run_probe(
                Path(directory) / "planning-contract.sqlite3",
                records=args.records,
                iterations=args.iterations,
            )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
