#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from agentmesh.task_routing.compiler import build_task_catalog, compile_task_catalog, json_bytes

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = PROJECT_ROOT / "wiki" / "user-research"
DEFAULT_OUTPUT = PROJECT_ROOT / "agentmesh" / "task_catalog" / "user-research-v1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compile the user-research task catalog for AgentMesh runtime use.")
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compile in memory and fail when the checked-in catalog differs.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not args.check:
        compiled = build_task_catalog(args.source_root, args.output_root)
        print(f"built {compiled.manifest.catalog_version} {compiled.manifest.catalog_hash}")
        return 0

    compiled = compile_task_catalog(args.source_root)
    expected = {**compiled.files, "catalog.json": compiled.manifest.model_dump(mode="json")}
    expected_paths = set(expected)
    actual_paths = {
        path.relative_to(args.output_root).as_posix()
        for path in args.output_root.rglob("*")
        if path.is_file()
    }
    mismatches = sorted(expected_paths ^ actual_paths)
    for relative_path, payload in sorted(expected.items()):
        path = args.output_root / relative_path
        if not path.is_file() or path.read_bytes() != json_bytes(payload):
            mismatches.append(relative_path)
    mismatches = list(dict.fromkeys(mismatches))
    if mismatches:
        print("task catalog is stale: " + ", ".join(mismatches))
        return 1
    print(f"task catalog is current: {compiled.manifest.catalog_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
