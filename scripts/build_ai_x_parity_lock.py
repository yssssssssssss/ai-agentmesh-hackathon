#!/usr/bin/env python3
"""Deterministically regenerate the approved ai-x parity lock from Git objects."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from verify_ai_x_parity_lock import DEFAULT_REVISION, build_lock


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--target", type=Path, default=Path("."))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("agentmesh/research_catalog/ai-x-parity-lock.json"),
    )
    args = parser.parse_args()
    target = args.target.resolve()
    output = target / args.output
    lock = build_lock(target, args.source.resolve(), args.revision)
    raw = (json.dumps(lock, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(raw)
    print(
        json.dumps(
            {
                "excluded_exact_files": lock["excluded_assets"]["exact_file_count"],
                "included_files": lock["included_assets"]["file_count"],
                "output": str(output),
                "slice_1_authorized": lock["slice_1_authorized"],
                "tree_files": lock["tree_manifest"]["file_count"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
