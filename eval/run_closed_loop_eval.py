#!/usr/bin/env python3
"""Validate or execute the versioned AgentMesh closed-loop evaluation dataset."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from eval.closed_loop.contracts import (
    DEFAULT_MANIFEST_PATH,
    DEFAULT_TASKS_PATH,
    load_evaluation_dataset,
    validate_evaluation_dataset,
)
from eval.closed_loop.runner import run_deterministic_evaluation


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("validate", "deterministic"), required=True)
    parser.add_argument("--batch", choices=("D0", "D1"), required=True)
    parser.add_argument("--case-set", choices=("all", "core_pr"), default="all")
    parser.add_argument("--output", type=Path, default=ROOT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS_PATH)
    return parser


ROOT_OUTPUT = Path("data/eval/closed-loop")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if (arguments.mode, arguments.batch) not in {("validate", "D0"), ("deterministic", "D1")}:
        _parser().error("validate requires D0 and deterministic requires D1")
    dataset = load_evaluation_dataset(arguments.manifest, arguments.tasks)
    validation = validate_evaluation_dataset(dataset)
    if arguments.mode == "deterministic":
        case_ids = (
            set(dataset.manifest.core_pr_case_ids)
            if arguments.case_set == "core_pr"
            else None
        )
        report = run_deterministic_evaluation(
            dataset,
            output_dir=arguments.output,
            case_ids=case_ids,
        )
        summary = {
            "batch": report.batch,
            "case_count": report.case_count,
            "case_set": arguments.case_set,
            "duration_ms": report.duration_ms,
            "failure_count": report.failure_count,
            "p50_case_ms": report.p50_case_ms,
            "p95_case_ms": report.p95_case_ms,
            "provider_calls": report.provider_calls,
            "results_path": str(arguments.output / "d1-summary.json"),
            "scripted_model_calls": report.scripted_model_calls,
        }
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0 if report.failure_count == 0 else 1
    report = {
        "batch": arguments.batch,
        "case_count": validation.validated_cases,
        "dataset_version": dataset.manifest.dataset_version,
        "dataset_hash": dataset.manifest.content_hash,
        "diagnostics": validation.diagnostics,
        "material_pack_count": len(dataset.material_packs),
        "mode": arguments.mode,
        "profile_count": validation.validated_profiles,
        "provider_calls": 0,
        "scenario_count": validation.validated_scenarios,
        "task_count": validation.validated_tasks,
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
