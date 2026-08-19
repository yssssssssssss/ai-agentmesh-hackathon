from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from eval.run_skill_retrieval_eval import (
    EXPECTED_SKILLS,
    P95_LATENCY_MAX_MS,
    TOP_K_RECALL_MIN,
    evaluate,
    load_cases,
    nearest_rank_percentile,
    recall_at_k,
)

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "eval" / "skill_retrieval_cases.json"
RUNNER = ROOT / "eval" / "run_skill_retrieval_eval.py"


def test_skill_retrieval_dataset_is_strict_and_balanced() -> None:
    cases = load_cases(DATASET)

    assert len(cases) == 40
    assert len({case.id for case in cases}) == 40
    assert len({case.request for case in cases}) == 40
    assert {case.expected_skill for case in cases} == EXPECTED_SKILLS
    assert Counter(case.expected_skill for case in cases) == {skill: 4 for skill in EXPECTED_SKILLS}
    assert all(not case.request.startswith("$") for case in cases)


def test_retrieval_metrics_use_top_k_and_nearest_rank_percentile() -> None:
    expected = ["alpha", "beta", "gamma", "delta"]
    rankings = [
        ["alpha", "x", "y"],
        ["x", "beta", "y"],
        ["x", "y", "gamma"],
        ["x", "y", "z", "delta"],
    ]

    assert recall_at_k(expected, rankings, k=3) == 0.75
    assert nearest_rank_percentile(list(range(1, 21)), 0.95) == 19
    with pytest.raises(ValueError, match="length_mismatch"):
        recall_at_k(["alpha"], [])


def test_dataset_and_security_probes_meet_retrieval_gates() -> None:
    report = evaluate(load_cases(DATASET))

    assert report.top3_recall >= TOP_K_RECALL_MIN
    assert report.p95_latency_ms < P95_LATENCY_MAX_MS
    probes = {probe.name: probe for probe in report.probes}
    assert set(probes) == {"unavailable", "disabled", "unauthorized"}
    assert all(probe.baseline_recalled for probe in probes.values())
    assert all(probe.filtered_recall == 0 for probe in probes.values())
    assert any(item.endswith("wiki.experiments_unavailable") for item in probes["unavailable"].diagnostics)
    assert any(item.endswith("research.request_not_granted") for item in probes["unauthorized"].diagnostics)


def test_runner_exits_nonzero_and_names_failed_cases(tmp_path: Path) -> None:
    document = json.loads(DATASET.read_text(encoding="utf-8"))
    requests = [case["request"] for case in document["cases"]]
    for index, case in enumerate(document["cases"]):
        case["request"] = requests[(index + 4) % len(requests)]
    failing_dataset = tmp_path / "failing-skill-retrieval-cases.json"
    failing_dataset.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    environment = os.environ.copy()
    environment["AGENTMESH_EMBEDDING_ENABLED"] = "false"

    completed = subprocess.run(
        [sys.executable, str(RUNNER), "--dataset", str(failing_dataset)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "CASE_MISS id=" in completed.stdout
    assert "FAIL gates=top_3_recall" in completed.stdout
