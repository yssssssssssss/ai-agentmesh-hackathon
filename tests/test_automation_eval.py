from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "eval" / "automation_cases_v1.json"


def _run(tmp_path, *arguments):
    host_database = tmp_path / "host.sqlite3"
    host_database.write_bytes(b"do not touch this database")
    result = subprocess.run(
        [sys.executable, str(ROOT / "eval" / "run_automation_eval.py"), *arguments],
        cwd=ROOT,
        env={**os.environ, "AGENTMESH_DB_PATH": str(host_database)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert host_database.read_bytes() == b"do not touch this database"
    return result


def test_frozen_inspection_evaluation_is_offline_and_leaves_host_database_untouched(tmp_path):
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(result.stdout)
    assert report["mode"] == "scripted"
    assert report["fixture_type"] == "synthetic-frozen-records"
    assert report["case_count"] == report["passed_count"] == 30
    assert report["by_template"] == {"daily_progress": 10, "blockers": 10, "pending_reviews": 10}
    assert report["model_tokens"] == 0
    assert len(report["dataset_sha256"]) == 64
    assert all(case["read_only"] and case["private_data_excluded"] for case in report["cases"])


def test_evaluation_returns_failure_when_a_frozen_expectation_is_wrong(tmp_path):
    dataset = json.loads(DATASET.read_text())
    dataset["cases"][0]["expected"]["outcome"] = "completed"
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(dataset))
    result = _run(tmp_path, "--dataset", str(changed))
    assert result.returncode == 1, result.stderr + result.stdout
    report = json.loads(result.stdout)
    assert report["passed_count"] == 29
    assert report["cases"][0]["mismatches"] == ["outcome"]


def test_evaluation_rejects_incomplete_or_duplicate_case_batches(tmp_path):
    dataset = json.loads(DATASET.read_text())
    dataset["cases"][-1] = dataset["cases"][0]
    changed = tmp_path / "duplicate.json"
    changed.write_text(json.dumps(dataset))
    result = _run(tmp_path, "--dataset", str(changed))
    assert result.returncode == 2
    assert "dataset_case_distribution_invalid" in result.stderr
