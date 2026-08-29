#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from agentmesh.task_routing.compiler import (
    build_task_catalog,
    catalog_bytes,
    catalog_tree_mismatches,
    compile_task_catalog,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = PROJECT_ROOT / "wiki" / "user-research"
DEFAULT_V2_OUTPUT_MAPPING = (
    PROJECT_ROOT / "agentmesh" / "task_catalog" / "sources" / "user-research-v2-scenario-outputs.json"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compile the user-research task catalog for AgentMesh runtime use.")
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--catalog-version", choices=("user-research-v1", "user-research-v2"), required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--scenario-output-mapping",
        type=Path,
        help="Required for user-research-v2; defaults to the checked-in v2 mapping source.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compile in memory and fail when the checked-in catalog differs.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    output_mapping = args.scenario_output_mapping
    if args.catalog_version == "user-research-v2" and output_mapping is None:
        output_mapping = DEFAULT_V2_OUTPUT_MAPPING
    compile_kwargs = {
        "catalog_version": args.catalog_version,
        "scenario_output_mapping_path": output_mapping,
    }
    if not args.check:
        compiled = build_task_catalog(args.source_root, args.output_root, **compile_kwargs)
        print(f"built {compiled.manifest.catalog_version} {compiled.manifest.catalog_hash}")
        return 0

    compiled = compile_task_catalog(args.source_root, **compile_kwargs)
    expected = catalog_bytes(compiled)
    mismatches = catalog_tree_mismatches(args.output_root, expected)
    if mismatches:
        print("task catalog is stale: " + ", ".join(mismatches))
        return 1
    print(f"task catalog is current: {compiled.manifest.catalog_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
