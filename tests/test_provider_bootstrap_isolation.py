from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_test_bootstrap_ignores_host_provider_configuration() -> None:
    repository = Path(__file__).resolve().parents[1]
    environment = {
        **os.environ,
        "AGENTMESH_O2_COMMAND": sys.executable,
        "AGENTMESH_O2_RESEARCH_ENABLED": "true",
        "AGENTMESH_WEB_PROVIDER": "tavily",
        "AGENTMESH_TAVILY_API_KEY": "host-key-must-not-be-used",
        "AGENTMESH_TAVILY_API_URL": "https://host-web-provider.invalid",
        "AGENTMESH_WEB_COMMAND": sys.executable,
        "AGENTMESH_DATA_API_URL": "https://host-provider.invalid",
        "AGENTMESH_CONNECTOR_WORKER_ENABLED": "true",
        "AGENTMESH_GITHUB_REPOSITORY": "host/repository-must-not-be-used",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import runpy; runpy.run_path('tests/conftest.py'); "
            "from agentmesh.o2 import build_acquisition_agent; "
            "from agentmesh.datasources import default_data_source_registry; "
            "from agentmesh.connector_sync.coordinator import worker_enabled; "
            "assert not worker_enabled(); "
            "assert not __import__('os').getenv('AGENTMESH_GITHUB_REPOSITORY'); "
            "assert type(build_acquisition_agent()).__name__ == 'MockAcquisitionAgent'; "
            "assert default_data_source_registry().list_connectors() == ['local_metrics']",
        ],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
