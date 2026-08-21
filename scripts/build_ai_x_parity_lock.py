#!/usr/bin/env python3
"""Deterministically regenerate the ai-x Gate 0 evidence lock."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from verify_ai_x_parity_lock import DEFAULT_REVISION, LOCK_PATH, build_lock


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--target", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=LOCK_PATH)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = args.target.resolve()
    output = target / args.output
    lock = build_lock(target, args.source.resolve(), args.revision)
    raw = canonical_bytes(lock)
    if args.check:
        if not output.is_file() or output.read_bytes() != raw:
            raise SystemExit(f"lock drift: regenerate {output}")
        action = "checked"
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(raw)
        action = "written"
    print(
        json.dumps(
            {
                "action": action,
                "blocking_criteria": lock["authorization"]["blocking_criteria"],
                "excluded_exact_files": lock["excluded_assets"]["exact_file_count"],
                "included_files": lock["included_assets"]["file_count"],
                "output": str(output),
                "slice_1_authorized": lock["authorization"]["slice_1_authorized"],
                "tree_files": lock["tree_manifest"]["file_count"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
