from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path

import pytest

_TEST_DB_DIRECTORY = tempfile.TemporaryDirectory(prefix="agentmesh-pytest-")
TEST_DB_PATH = Path(_TEST_DB_DIRECTORY.name) / "agentmesh-pytest.sqlite3"

os.environ["AGENTMESH_SKIP_DOTENV"] = "1"
os.environ["AGENTMESH_DB_PATH"] = str(TEST_DB_PATH)
os.environ["AGENTMESH_DEMO_MODE"] = "1"
os.environ["AGENTMESH_EMBEDDING_ENABLED"] = "false"
os.environ["AGENTMESH_EMBEDDING_API_URL"] = ""
os.environ["AGENTMESH_EMBEDDING_API_KEY"] = ""


@pytest.fixture
def configure_pilot_wiki(monkeypatch: pytest.MonkeyPatch) -> Callable[[Path], Path]:
    def configure(root: Path) -> Path:
        corpus_files = (
            root / "jd-design-system-md-v16" / "horizontal" / "user-research" / "canonical.md",
            root
            / "jd-design-system-md-v16"
            / "product-architecture"
            / "comprehensive-business"
            / "content-ecosystem"
            / "canonical.md",
            root
            / "jd-design-system-md-v16"
            / "product-architecture"
            / "plus-and-new-channel"
            / "_knowledge"
            / "experiments"
            / "INDEX.json",
        )
        for path in corpus_files:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}" if path.suffix == ".json" else "canonical", encoding="utf-8")
        monkeypatch.setenv("AGENTMESH_WIKI_ROOT", str(root))
        return root

    return configure

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
    "AGENTMESH_FIRECRAWL_ENABLED",
    "AGENTMESH_FIRECRAWL_API_URL",
    "AGENTMESH_FIRECRAWL_API_KEY",
    "AGENTMESH_FIRECRAWL_TIMEOUT_SECONDS",
    "AGENTMESH_FIRECRAWL_MAX_PAGES",
    "AGENTMESH_FIRECRAWL_MAX_CONTENT_CHARS",
):
    os.environ[key] = ""


@pytest.fixture(autouse=True)
def _reset_web_provider_telemetry(monkeypatch: pytest.MonkeyPatch):
    from agentmesh import web_research
    from agentmesh.provider_status import ProviderTelemetry

    monkeypatch.setattr(web_research, "_tavily_telemetry", ProviderTelemetry())
    monkeypatch.setattr(web_research, "_firecrawl_telemetry", ProviderTelemetry())
    yield


@pytest.fixture(autouse=True)
def _reset_market_scout_state():
    """The scout dedup cache is a process-lifetime module global; clear it between tests
    so a fingerprint from one test doesn't suppress matching in another."""
    from agentmesh.marketplace import reset_scout_state

    reset_scout_state()
    yield
