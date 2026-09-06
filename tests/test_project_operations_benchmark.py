from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_project_operations_benchmark_script_emits_a_passing_contract(tmp_path: Path) -> None:
    output = tmp_path / "project-operations-benchmark.json"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_project_operations_benchmark.py",
            "--tasks",
            "200",
            "--events",
            "500",
            "--memory",
            "200",
            "--accepted-memory",
            "20",
            "--iterations",
            "2",
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(output.read_text())
    assert report["schema_version"] == "project-operations-benchmark-v1"
    assert report["counts"] == {
        "tasks": 200,
        "task_audit_events": 500,
        "memory_records": 200,
        "accepted_team_knowledge": 20,
    }
    assert report["passed"] is True
    assert set(report["measurements"]) == {
        "task_list",
        "task_detail",
        "operations_snapshot",
        "task_options",
        "memory_fts",
    }
