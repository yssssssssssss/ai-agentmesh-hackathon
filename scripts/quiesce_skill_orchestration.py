#!/usr/bin/env python3
"""Dry-run or apply fail-closed terminalization for Universal orchestration rollback."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from agentmesh.canonical_json import strict_json_loads  # noqa: E402
from agentmesh.store import RuntimeToolCallConflict, SQLiteStore  # noqa: E402


class QuiesceCommandError(RuntimeError):
    pass


def _backup_database(database: Path, backup: Path) -> str:
    if backup.exists():
        raise QuiesceCommandError("backup_path_exists")
    backup.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(database)
    destination = sqlite3.connect(backup)
    try:
        source.backup(destination)
        integrity = destination.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise QuiesceCommandError("backup_integrity_failed")
    finally:
        destination.close()
        source.close()
    return hashlib.sha256(backup.read_bytes()).hexdigest()


def _validate_approval(path: Path, *, checksum: str) -> tuple[str, ...]:
    try:
        payload = strict_json_loads(path.read_bytes())
    except (OSError, UnicodeError, ValueError) as error:
        raise QuiesceCommandError("quiesce_approval_invalid") from error
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "operation_checksum",
        "approved_by",
    }:
        raise QuiesceCommandError("quiesce_approval_invalid")
    reviewers = payload["approved_by"]
    if (
        payload["schema_version"] != "orchestration-quiesce-approval-v1"
        or payload["operation_checksum"] != checksum
        or not isinstance(reviewers, list)
        or len(reviewers) < 2
        or len(reviewers) != len(set(reviewers))
        or not all(isinstance(reviewer, str) and reviewer.startswith("@") for reviewer in reviewers)
    ):
        raise QuiesceCommandError("quiesce_approval_invalid")
    return tuple(reviewers)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-operation-checksum")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--approval-file", type=Path)
    args = parser.parse_args(argv)

    database = args.database.resolve()
    if not database.is_file():
        raise QuiesceCommandError("database_unavailable")
    try:
        repository = SQLiteStore(
            database,
            enforce_writer_lock=True,
            initialize_schema=False,
        )
    except RuntimeError as error:
        if str(error) == "sqlite_writer_lock_unavailable":
            raise QuiesceCommandError("database_writer_lock_unavailable") from error
        raise
    try:
        inventory = repository.universal_quiesce_inventory()
        payload: dict[str, object] = {
            "mode": "apply" if args.apply else "dry-run",
            "inventory": inventory.model_dump(mode="json"),
        }
        if not args.apply:
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            return 1 if inventory.anomaly_codes else 0
        if inventory.anomaly_codes:
            raise QuiesceCommandError("quiesce_inventory_invalid")
        if not args.expected_operation_checksum or args.expected_operation_checksum != inventory.operation_checksum:
            raise QuiesceCommandError("quiesce_operation_checksum_required")
        if args.backup is None or args.approval_file is None:
            raise QuiesceCommandError("quiesce_backup_and_approval_required")
        reviewers = _validate_approval(args.approval_file, checksum=inventory.operation_checksum)
        backup_sha256 = _backup_database(database, args.backup.resolve())
        applied = repository.apply_universal_quiesce(
            expected_operation_checksum=inventory.operation_checksum,
        )
        remaining = repository.universal_quiesce_inventory()
        if (
            remaining.run_ids
            or remaining.unresolved_tool_call_ids
            or remaining.anomaly_codes
        ):
            raise QuiesceCommandError("quiesce_postcheck_failed")
        payload.update(
            {
                "inventory": applied.model_dump(mode="json"),
                "backup": str(args.backup.resolve()),
                "backup_sha256": backup_sha256,
                "approved_by": reviewers,
                "postcheck": remaining.model_dump(mode="json"),
            }
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except RuntimeToolCallConflict as error:
        raise QuiesceCommandError(error.code) from error
    finally:
        repository.close()


if __name__ == "__main__":
    raise SystemExit(main())
