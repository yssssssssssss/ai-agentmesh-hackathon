from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from agentmesh.store import SQLiteStore


def _probe(db_path: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["AGENTMESH_DB_PATH"] = str(db_path)
    return subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from agentmesh.store import store; "
                "print(store.writer_lock_diagnostics()['pid']); "
                "store.close()"
            ),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_application_writer_lock_rejects_a_second_process_before_schema_writes(tmp_path) -> None:
    db_path = tmp_path / "writer-lock.sqlite3"
    owner = SQLiteStore(db_path, enforce_writer_lock=True)
    before = db_path.read_bytes()

    blocked = _probe(db_path)

    assert blocked.returncode != 0
    assert "sqlite_writer_lock_unavailable" in blocked.stderr
    assert db_path.read_bytes() == before

    owner.close()
    accepted = _probe(db_path)
    assert accepted.returncode == 0, accepted.stderr
    assert accepted.stdout.strip().isdigit()
