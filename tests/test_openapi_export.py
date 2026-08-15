from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_openapi_export_does_not_create_database_in_calling_directory(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    script = repository_root / "agentmesh-demo" / "scripts" / "export_openapi.py"
    environment = os.environ.copy()
    environment.pop("AGENTMESH_DB_PATH", None)
    environment["AGENTMESH_DEMO_MODE"] = "0"
    environment["AGENTMESH_EMBEDDING_ENABLED"] = "false"

    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert not (tmp_path / "data" / "agentmesh.sqlite3").exists()
