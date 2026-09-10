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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("validate",), required=True)
    parser.add_argument("--batch", choices=("D0",), required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS_PATH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    dataset = load_evaluation_dataset(arguments.manifest, arguments.tasks)
    validation = validate_evaluation_dataset(dataset)
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
