from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

TEST_DB_PATH = Path(tempfile.gettempdir()) / "agentmesh-pytest.sqlite3"
if TEST_DB_PATH.exists():
    TEST_DB_PATH.unlink()

os.environ["AGENTMESH_SKIP_DOTENV"] = "1"
os.environ["AGENTMESH_DB_PATH"] = str(TEST_DB_PATH)
os.environ["AGENTMESH_DEMO_MODE"] = "1"
os.environ["AGENTMESH_EMBEDDING_ENABLED"] = "false"
os.environ["AGENTMESH_EMBEDDING_API_URL"] = ""
os.environ["AGENTMESH_EMBEDDING_API_KEY"] = ""

for key in (
    "AI_API_URL",
    "AI_API_KEY",
    "AI_MODEL",
    "AI_API_STYLE",
    "AGENTMESH_LLM_BASE_URL",
    "AGENTMESH_LLM_API_KEY",
    "AGENTMESH_LLM_MODEL",
    "AGENTMESH_LLM_API_STYLE",
    "AGENTMESH_MODEL_DEFAULT",
    "AGENTMESH_MODELS",
    "AGENTMESH_LLM_FALLBACK_MODEL_ID",
    "AGENTMESH_MODEL_PRIMARY_BASE_URL",
    "AGENTMESH_MODEL_PRIMARY_API_KEY",
    "AGENTMESH_MODEL_PRIMARY_MODEL",
    "AGENTMESH_MODEL_PRIMARY_API_STYLE",
    "AGENTMESH_MODEL_FALLBACK_BASE_URL",
    "AGENTMESH_MODEL_FALLBACK_API_KEY",
    "AGENTMESH_MODEL_FALLBACK_MODEL",
    "AGENTMESH_MODEL_FALLBACK_API_STYLE",
):
    os.environ[key] = ""


@pytest.fixture(autouse=True)
def _reset_market_scout_state():
    """The scout dedup cache is a process-lifetime module global; clear it between tests
    so a fingerprint from one test doesn't suppress matching in another."""
    from agentmesh.marketplace import reset_scout_state

    reset_scout_state()
    yield

