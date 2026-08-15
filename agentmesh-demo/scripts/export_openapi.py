from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).resolve().parents[1] / "openapi.json"
sys.path.insert(0, str(REPO_ROOT))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentmesh-openapi-") as temp_dir:
        os.environ["AGENTMESH_DB_PATH"] = str(Path(temp_dir) / "openapi.sqlite3")
        os.environ["AGENTMESH_DEMO_MODE"] = "0"
        os.environ["AGENTMESH_EMBEDDING_ENABLED"] = "false"
        app = importlib.import_module("agentmesh.app").app
        OUTPUT.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
