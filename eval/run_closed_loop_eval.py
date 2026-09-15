#!/usr/bin/env python3
"""Validate or execute the versioned AgentMesh closed-loop evaluation dataset."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from eval.closed_loop.contracts import (
    DEFAULT_MANIFEST_PATH,
    DEFAULT_TASKS_PATH,
    load_evaluation_dataset,
    validate_evaluation_dataset,
)
from eval.closed_loop.real_runner import load_env_file, run_real_r1, selected_real_model
from eval.closed_loop.runner import run_deterministic_evaluation


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("validate", "deterministic", "real"), required=True)
    parser.add_argument("--batch", choices=("D0", "D1", "R1"), required=True)
    parser.add_argument("--case-set", choices=("all", "core_pr"), default="all")
    parser.add_argument("--output", type=Path, default=ROOT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS_PATH)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--model-id")
    parser.add_argument("--max-runs", type=int, default=24)
    parser.add_argument("--max-total-tokens", type=int, default=500_000)
    parser.add_argument("--initial-token-reserve", type=int, default=20_000)
    parser.add_argument("--ack-real-provider", action="store_true")
    return parser


ROOT_OUTPUT = Path("data/eval/closed-loop")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if (arguments.mode, arguments.batch) not in {
        ("validate", "D0"),
        ("deterministic", "D1"),
        ("real", "R1"),
    }:
        _parser().error("validate requires D0, deterministic requires D1, and real requires R1")
    if arguments.mode == "real":
        if not arguments.ack_real_provider:
            _parser().error("real mode requires --ack-real-provider")
        if os.getenv("CI", "").strip().lower() in {"1", "true", "yes", "on"}:
            _parser().error("real mode is forbidden when CI=true")
        if arguments.env_file is not None:
            load_env_file(arguments.env_file)
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
    if arguments.mode == "real":
        arguments.output.mkdir(parents=True, exist_ok=True)
        model_id = arguments.model_id or os.getenv("AGENTMESH_MODEL_DEFAULT", "default")
        with tempfile.TemporaryDirectory(prefix="agentmesh-r1-model-") as directory:
            from agentmesh.store import SQLiteStore

            repository = SQLiteStore(Path(directory) / "model.sqlite3")
            selected = selected_real_model(repository, model_id)
            report = asyncio.run(
                run_real_r1(
                    dataset,
                    selected=selected,
                    output_dir=arguments.output,
                    max_runs=arguments.max_runs,
                    max_total_tokens=arguments.max_total_tokens,
                    initial_reserved_tokens=arguments.initial_token_reserve,
                )
            )
            repository.close()
        summary = {
            "actual_model": report.actual_model,
            "batch": report.batch,
            "completed_cases": report.completed_cases,
            "contract_passed": sum(item.contract_passed for item in report.results),
            "max_total_tokens": report.max_total_tokens,
            "measured_tokens": report.usage.total_tokens,
            "reserved_tokens": report.initial_reserved_tokens + report.failure_reserved_tokens,
            "budget_used_tokens": report.budget_used_tokens,
            "requested_model": report.requested_model,
            "results_path": str(arguments.output / "r1-checkpoint.json"),
            "stopped_reason": report.stopped_reason,
        }
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0 if report.stopped_reason is None else 1
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
