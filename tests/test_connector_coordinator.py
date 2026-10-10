from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentmesh.connector_sync import service as service_module
from agentmesh.connector_sync.contracts import ConnectorSyncError
from agentmesh.connector_sync.readers import RepoDocsReader
from agentmesh.routes import data_sources as routes
from agentmesh.routes.deps import current_user
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.store import SQLiteStore

AT = datetime(2026, 10, 7, tzinfo=UTC)


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
def project(tmp_path, monkeypatch):
    repository = SQLiteStore(tmp_path / 'coordinator.sqlite3')
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    root = tmp_path / 'docs'
    root.mkdir()
    monkeypatch.setattr(routes, 'store', repository)
    monkeypatch.setenv('AGENTMESH_CONNECTOR_PROJECT_ID', USER.default_project_id)
    monkeypatch.setenv('AGENTMESH_REPO_DOCS_ROOT', str(root))
    monkeypatch.delenv('AGENTMESH_GITHUB_REPOSITORY', raising=False)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[current_user] = lambda: USER
    with TestClient(app) as client:
        yield repository, root, client
    repository.close()


@pytest.mark.anyio
async def test_tick_only_reads_explicitly_enabled_due_pages_and_preserves_cycle_interval(project, monkeypatch):
    from agentmesh.connector_sync import coordinator as module
    from agentmesh.connector_sync.coordinator import ConnectorSyncCoordinator

    repository, root, client = project
    clock = [AT]
    monkeypatch.setattr(service_module, 'now_utc', lambda: clock[0])
    monkeypatch.setattr(module, 'now_utc', lambda: clock[0])
    for index in range(6):
        (root / f'{index}.md').write_text(f'Project evidence {index}')
    prefix = f'/api/projects/{USER.default_project_id}/connectors'
    first = client.post(prefix + '/repo_docs/sync', json={'expected_version': 0}).json()
    coordinator = ConnectorSyncCoordinator(repository, enabled=lambda: True)
    assert await coordinator.tick() == 0
    enabled = client.post(prefix + '/' + first['id'] + '/control',
        json={'expected_version': first['version'], 'action': 'enable_auto', 'interval_seconds': 300}).json()
    assert await coordinator.tick() == 1
    assert len(repository.documents) == 6
    cursor = client.get(prefix).json()['items'][0]['cursor']
    assert cursor['version'] == enabled['version'] + 1 and cursor['status'] == 'idle'
    assert datetime.fromisoformat(cursor['next_sync_at']) == AT + timedelta(seconds=300)
    assert await coordinator.tick() == 0
    client.app.state.connector_sync_coordinator = coordinator
    assert not client.get(prefix).json()['auto_sync_available']
    await coordinator.start()
    assert client.get(prefix).json()['auto_sync_available']
    await coordinator.stop()
    assert not client.get(prefix).json()['auto_sync_available']


@pytest.mark.anyio
async def test_retry_wait_survives_worker_restart_blocks_manual_reads_and_pauses_after_three_attempts(project, monkeypatch):
    from agentmesh.connector_sync import coordinator as module

    repository, root, client = project
    clock = [AT]
    monkeypatch.setattr(service_module, 'now_utc', lambda: clock[0])
    monkeypatch.setattr(module, 'now_utc', lambda: clock[0])
    (root / 'evidence.md').write_text('Last successful evidence')
    prefix = f'/api/projects/{USER.default_project_id}/connectors'
    first = client.post(prefix + '/repo_docs/sync', json={'expected_version': 0}).json()
    client.post(prefix + '/' + first['id'] + '/control',
                json={'expected_version': first['version'], 'action': 'enable_auto'})
    other = USER.model_copy(update={'id': 'usr_connector_other'})
    repository.save_user(other)
    project_record = repository.get_project(USER.default_project_id)
    repository.save_project(project_record.model_copy(update={'member_ids': [*project_record.member_ids, other.id]}))
    reader = RepoDocsReader(root, namespace='project_docs')
    other_service = service_module.ConnectorSyncService(repository, reader,
        current_configuration_hash=reader.configuration_hash)
    other_cursor = other_service.sync_page(other, project_id=USER.default_project_id, expected_version=0)
    calls = []

    def fail(reader, position, *, since=None):
        calls.append(clock[0])
        if len(calls) == 2:
            raise ConnectorSyncError('connector_rate_limited', status_code=503, retryable=True, retry_after=120)
        raise ConnectorSyncError('connector_provider_unavailable', status_code=503, retryable=True)

    monkeypatch.setattr(RepoDocsReader, 'read_page', fail)
    coordinator = module.ConnectorSyncCoordinator(repository, enabled=lambda: True)
    assert await coordinator.tick() == 0
    cursor = client.get(prefix).json()['items'][0]['cursor']
    assert cursor['consecutive_failures'] == 1 and cursor['auto_sync_enabled']
    assert datetime.fromisoformat(cursor['next_sync_at']) == AT + timedelta(seconds=5)
    assert await coordinator.tick() == 0 and len(calls) == 1
    clock[0] += timedelta(seconds=5)
    assert await coordinator.tick() == 0 and len(calls) == 2
    cursor = client.get(prefix).json()['items'][0]['cursor']
    assert cursor['last_error_code'] == 'connector_rate_limited'
    assert datetime.fromisoformat(cursor['next_sync_at']) == clock[0] + timedelta(seconds=120)
    assert cursor['next_allowed_at'] == cursor['next_sync_at']
    assert client.post(prefix + '/repo_docs/sync', json={'expected_version': cursor['version']}).status_code == 429
    with pytest.raises(ConnectorSyncError, match='connector_retry_wait'):
        other_service.sync_page(other, project_id=USER.default_project_id, expected_version=other_cursor.version)
    assert len(calls) == 2
    coordinator = module.ConnectorSyncCoordinator(repository, enabled=lambda: True)
    assert await coordinator.tick() == 0 and len(calls) == 2
    clock[0] += timedelta(seconds=120)
    assert await coordinator.tick() == 0 and len(calls) == 3
    cursor = client.get(prefix).json()['items'][0]['cursor']
    assert cursor['consecutive_failures'] == 3 and not cursor['auto_sync_enabled']
    assert cursor['next_sync_at'] is None
    assert await coordinator.tick() == 0 and len(calls) == 3
    assert repository.documents[0].text == 'Last successful evidence'


@pytest.mark.anyio
async def test_worker_stop_fences_an_inflight_read_without_overwriting_last_success(project, monkeypatch):
    from agentmesh.connector_sync.coordinator import ConnectorSyncCoordinator

    repository, root, client = project
    (root / 'evidence.md').write_text('Original evidence')
    prefix = f'/api/projects/{USER.default_project_id}/connectors'
    first = client.post(prefix + '/repo_docs/sync', json={'expected_version': 0}).json()
    client.post(prefix + '/' + first['id'] + '/control',
                json={'expected_version': first['version'], 'action': 'enable_auto'})
    (root / 'evidence.md').write_text('Late evidence')
    entered, release = Event(), Event()
    original = RepoDocsReader.read_page

    def blocked(reader, position, *, since=None):
        entered.set()
        assert release.wait(timeout=5)
        return original(reader, position, since=since)

    monkeypatch.setattr(RepoDocsReader, 'read_page', blocked)
    coordinator = ConnectorSyncCoordinator(repository, enabled=lambda: True)
    reading = asyncio.create_task(coordinator.tick())
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        await coordinator.stop()
        assert not coordinator.running
        cursor = client.get(prefix).json()['items'][0]['cursor']
        assert cursor['status'] == 'cancelled' and not cursor['auto_sync_enabled']
        assert cursor['read_claim_id'] is None
    finally:
        release.set()
        await reading
    assert repository.documents[0].text == 'Original evidence'
