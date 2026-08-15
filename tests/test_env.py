from __future__ import annotations

import os
from pathlib import Path

from agentmesh.env import load_dotenv


def test_skip_dotenv_prevents_loading_local_configuration(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("AGENTMESH_TEST_DOTENV_SECRET=must-not-load\n", encoding="utf-8")
    monkeypatch.setenv("AGENTMESH_SKIP_DOTENV", "1")
    monkeypatch.delenv("AGENTMESH_TEST_DOTENV_SECRET", raising=False)

    load_dotenv(env_file)

    assert "AGENTMESH_TEST_DOTENV_SECRET" not in os.environ
