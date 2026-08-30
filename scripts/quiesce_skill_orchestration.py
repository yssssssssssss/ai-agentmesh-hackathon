#!/usr/bin/env python3
"""Dry-run or apply fail-closed terminalization for Universal orchestration rollback."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import stat
import sys
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from agentmesh.canonical_json import strict_json_loads  # noqa: E402
from agentmesh.store import RuntimeToolCallConflict, SQLiteStore  # noqa: E402


class QuiesceCommandError(RuntimeError):
    pass


def _database_facts(connection: sqlite3.Connection) -> dict[str, object]:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()
    if integrity is None or integrity[0] != "ok":
        raise QuiesceCommandError("backup_integrity_failed")

    table_counts: dict[str, int] = {}
    for table in (
        "agent_runs",
        "skill_plans",
        "artifacts",
        "run_dispatch_receipts",
    ):
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        table_counts[table] = (
            int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            if exists is not None
            else 0
        )
    records_exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'records'"
    ).fetchone()
    table_counts["run_output_projection_receipts"] = (
        int(
            connection.execute(
                "SELECT COUNT(*) FROM records WHERE collection = ?",
                ("run_output_projection_receipts",),
            ).fetchone()[0]
        )
        if records_exists is not None
        else 0
    )
    return {
        "integrity_check": "ok",
        "schema_version": int(connection.execute("PRAGMA schema_version").fetchone()[0]),
        "user_version": int(connection.execute("PRAGMA user_version").fetchone()[0]),
        "page_count": int(connection.execute("PRAGMA page_count").fetchone()[0]),
        "page_size": int(connection.execute("PRAGMA page_size").fetchone()[0]),
        "table_counts": table_counts,
    }


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_private_file(
    source: Path,
    target: Path,
    *,
    exists_code: str,
    publish_code: str,
) -> None:
    if os.path.lexists(target):
        raise QuiesceCommandError(exists_code)
    source_stat = source.lstat()
    if not stat.S_ISREG(source_stat.st_mode) or stat.S_IMODE(source_stat.st_mode) != 0o600:
        raise QuiesceCommandError(publish_code)
    descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.link(source, target, follow_symlinks=False)
    except FileExistsError as error:
        raise QuiesceCommandError(exists_code) from error
    except OSError as error:
        raise QuiesceCommandError(publish_code) from error
    try:
        target_stat = target.lstat()
        if (
            not stat.S_ISREG(target_stat.st_mode)
            or stat.S_IMODE(target_stat.st_mode) != 0o600
            or (target_stat.st_dev, target_stat.st_ino)
            != (source_stat.st_dev, source_stat.st_ino)
        ):
            raise QuiesceCommandError(publish_code)
        source.unlink()
        _fsync_directory(target.parent)
    except BaseException:
        with suppress(OSError):
            current = target.lstat()
            if (current.st_dev, current.st_ino) == (
                source_stat.st_dev,
                source_stat.st_ino,
            ):
                target.unlink()
        raise


def _write_private_json(
    path: Path,
    payload: dict[str, object],
    *,
    create_only: bool,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    try:
        try:
            os.fchmod(descriptor, 0o600)
            remaining = memoryview(encoded)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise QuiesceCommandError("receipt_write_failed")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if create_only:
            _publish_private_file(
                temporary,
                path,
                exists_code="receipt_path_exists",
                publish_code="receipt_publish_failed",
            )
        else:
            try:
                current = path.lstat()
            except OSError as error:
                raise QuiesceCommandError("receipt_path_invalid") from error
            if (
                not stat.S_ISREG(current.st_mode)
                or stat.S_IMODE(current.st_mode) != 0o600
            ):
                raise QuiesceCommandError("receipt_path_invalid")
            os.replace(temporary, path)
            _fsync_directory(path.parent)
        try:
            persisted = strict_json_loads(path.read_bytes())
            expected = strict_json_loads(encoded)
        except (OSError, UnicodeError, ValueError) as error:
            raise QuiesceCommandError("receipt_persistence_failed") from error
        if persisted != expected:
            raise QuiesceCommandError("receipt_persistence_failed")
    finally:
        temporary.unlink(missing_ok=True)


def _backup_database(
    database: Path,
    backup: Path,
    *,
    expected_inventory_checksum: str,
) -> dict[str, object]:
    if os.path.lexists(backup):
        raise QuiesceCommandError("backup_path_exists")
    if backup.parent.resolve() == database.parent.resolve():
        raise QuiesceCommandError("backup_directory_must_differ")
    backup.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{backup.name}.",
        suffix=".tmp",
        dir=backup.parent,
    )
    temporary = Path(temporary_name)
    os.fchmod(descriptor, 0o600)
    os.close(descriptor)

    try:
        source = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
        destination = sqlite3.connect(temporary)
        try:
            source_facts = _database_facts(source)
            source.backup(destination)
            destination.commit()
            backup_facts = _database_facts(destination)
        finally:
            destination.close()
            source.close()
        os.chmod(temporary, 0o600)

        if (
            backup_facts["user_version"] != source_facts["user_version"]
            or backup_facts["table_counts"] != source_facts["table_counts"]
        ):
            raise QuiesceCommandError("backup_snapshot_mismatch")

        backup_sha256 = hashlib.sha256(temporary.read_bytes()).hexdigest()
        backup_bytes = temporary.stat().st_size
        with tempfile.TemporaryDirectory(
            prefix="agentmesh-quiesce-restore-",
            dir=backup.parent,
        ) as restore_directory:
            restored_path = Path(restore_directory) / "restored.sqlite3"
            backup_source = sqlite3.connect(
                f"{temporary.resolve().as_uri()}?mode=ro",
                uri=True,
            )
            restored = sqlite3.connect(restored_path)
            try:
                backup_source.backup(restored)
                restored.commit()
                restored_facts = _database_facts(restored)
            finally:
                restored.close()
                backup_source.close()
            if (
                restored_facts["user_version"] != source_facts["user_version"]
                or restored_facts["table_counts"] != source_facts["table_counts"]
            ):
                raise QuiesceCommandError("backup_restore_mismatch")
            restored_repository = SQLiteStore(
                restored_path,
                enforce_writer_lock=True,
                initialize_schema=False,
            )
            try:
                restored_inventory = restored_repository.universal_quiesce_inventory()
            finally:
                restored_repository.close()
            if restored_inventory.operation_checksum != expected_inventory_checksum:
                raise QuiesceCommandError("backup_restore_inventory_mismatch")

        _publish_private_file(
            temporary,
            backup,
            exists_code="backup_path_exists",
            publish_code="backup_publish_failed",
        )
        return {
            "path": str(backup),
            "sha256": backup_sha256,
            "bytes": backup_bytes,
            "created_at": datetime.now(UTC).isoformat(),
            "source": source_facts,
            "backup": backup_facts,
            "restore_smoke": {
                **restored_facts,
                "inventory_operation_checksum": restored_inventory.operation_checksum,
            },
        }
    finally:
        temporary.unlink(missing_ok=True)


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
    parser.add_argument("--receipt", type=Path)
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
        if args.backup is None or args.approval_file is None or args.receipt is None:
            raise QuiesceCommandError("quiesce_backup_approval_and_receipt_required")
        backup_path = Path(os.path.abspath(args.backup.expanduser()))
        receipt_path = Path(os.path.abspath(args.receipt.expanduser()))
        if receipt_path in {database, backup_path}:
            raise QuiesceCommandError("receipt_path_invalid")
        if os.path.lexists(receipt_path):
            raise QuiesceCommandError("receipt_path_exists")
        reviewers = _validate_approval(args.approval_file, checksum=inventory.operation_checksum)
        backup_evidence = _backup_database(
            database,
            backup_path,
            expected_inventory_checksum=inventory.operation_checksum,
        )
        receipt_payload: dict[str, object] = {
            "schema_version": "orchestration-quiesce-apply-receipt-v1",
            "status": "backup_verified",
            "database": str(database),
            "operation_checksum": inventory.operation_checksum,
            "approved_by": reviewers,
            "backup": backup_evidence,
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        _write_private_json(receipt_path, receipt_payload, create_only=True)
        try:
            applied = repository.apply_universal_quiesce(
                expected_operation_checksum=inventory.operation_checksum,
            )
        except BaseException as error:
            receipt_payload.update(
                {
                    "status": "apply_failed",
                    "error_code": getattr(error, "code", type(error).__name__),
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )
            _write_private_json(receipt_path, receipt_payload, create_only=False)
            raise
        receipt_payload.update(
            {
                "status": "applied",
                "applied_inventory": applied.model_dump(mode="json"),
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
        _write_private_json(receipt_path, receipt_payload, create_only=False)
        try:
            remaining = repository.universal_quiesce_inventory()
        except BaseException as error:
            receipt_payload.update(
                {
                    "status": "postcheck_failed",
                    "error_code": getattr(error, "code", type(error).__name__),
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )
            _write_private_json(receipt_path, receipt_payload, create_only=False)
            raise
        if (
            remaining.run_ids
            or remaining.active_dispatch_operation_keys
            or remaining.unresolved_tool_call_ids
            or remaining.anomaly_codes
        ):
            receipt_payload.update(
                {
                    "status": "postcheck_failed",
                    "error_code": "quiesce_postcheck_failed",
                    "postcheck": remaining.model_dump(mode="json"),
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )
            _write_private_json(receipt_path, receipt_payload, create_only=False)
            raise QuiesceCommandError("quiesce_postcheck_failed")
        receipt_payload.update(
            {
                "status": "verified",
                "postcheck": remaining.model_dump(mode="json"),
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
        _write_private_json(receipt_path, receipt_payload, create_only=False)
        payload.update(
            {
                "inventory": applied.model_dump(mode="json"),
                "backup": backup_evidence["path"],
                "backup_sha256": backup_evidence["sha256"],
                "backup_bytes": backup_evidence["bytes"],
                "backup_created_at": backup_evidence["created_at"],
                "backup_source": backup_evidence["source"],
                "backup_snapshot": backup_evidence["backup"],
                "restore_smoke": backup_evidence["restore_smoke"],
                "approved_by": reviewers,
                "receipt": str(receipt_path),
                "receipt_status": receipt_payload["status"],
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
