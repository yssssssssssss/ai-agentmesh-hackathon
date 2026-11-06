"""Operator-selected project bindings, never request-supplied filesystem or API URLs."""
from __future__ import annotations

import os
from pathlib import Path

from agentmesh.connector_sync.contracts import ConnectorSyncError
from agentmesh.connector_sync.readers import GitHubIssuesReader, RepoDocsReader
from agentmesh.connector_sync.service import ConnectorReader


def configured_readers(project_id: str) -> list[ConnectorReader]:
    if project_id != os.getenv('AGENTMESH_CONNECTOR_PROJECT_ID', '').strip():
        raise ConnectorSyncError('connector_not_found', status_code=404)
    readers: list[ConnectorReader] = []
    root = os.getenv('AGENTMESH_REPO_DOCS_ROOT', '').strip()
    if root:
        readers.append(RepoDocsReader(Path(root), namespace='project_docs'))
    repository = os.getenv('AGENTMESH_GITHUB_REPOSITORY', '').strip()
    if repository:
        token = os.getenv('AGENTMESH_GITHUB_TOKEN', '').strip() or None
        readers.append(GitHubIssuesReader(repository, token=token,
            credential_version=os.getenv('AGENTMESH_GITHUB_CREDENTIAL_VERSION', 'anonymous').strip()))
    return readers


def configured_reader(project_id: str, provider: str) -> ConnectorReader:
    reader = next((reader for reader in configured_readers(project_id) if reader.provider == provider), None)
    if reader is None:
        raise ConnectorSyncError('connector_not_found', status_code=404)
    return reader
