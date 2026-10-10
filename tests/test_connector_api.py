from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentmesh.routes import data_sources as routes
from agentmesh.routes.deps import current_user
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.store import SQLiteStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    repository = SQLiteStore(tmp_path / 'connector-api.sqlite3')
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    monkeypatch.setattr(routes, 'store', repository)
    monkeypatch.setenv('AGENTMESH_CONNECTOR_PROJECT_ID', USER.default_project_id)
    monkeypatch.delenv('AGENTMESH_GITHUB_REPOSITORY', raising=False)
    monkeypatch.delenv('AGENTMESH_REPO_DOCS_ROOT', raising=False)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[current_user] = lambda: USER
    with TestClient(app) as http:
        yield http, repository
    repository.close()


def test_configured_docs_sync_is_reachable_without_accepting_paths_from_http(client, tmp_path, monkeypatch):
    http, repository = client
    root = tmp_path / 'docs'
    root.mkdir()
    (root / 'a.md').write_text('Authorized project documentation')
    monkeypatch.setenv('AGENTMESH_REPO_DOCS_ROOT', str(root))
    prefix = f'/api/projects/{USER.default_project_id}/connectors'
    status = http.get(prefix)
    assert status.status_code == 200
    assert status.json()['items'][0]['provider'] == 'repo_docs'
    assert status.json()['items'][0]['cursor'] is None
    synced = http.post(prefix + '/repo_docs/sync', json={'expected_version': 0})
    assert synced.status_code == 200 and synced.json()['version'] == 1
    assert repository.documents[0].text == 'Authorized project documentation'
    assert str(root) not in synced.text
    assert http.post(prefix + '/repo_docs/sync', json={'expected_version': 0}).status_code == 409
    rejected = http.post(prefix + '/repo_docs/sync', json={'expected_version': 1, 'root': '/private'})
    assert rejected.status_code == 422


def test_empty_connector_status_still_requires_current_project_authority(client):
    http, repository = client
    repository.save_user(USER.model_copy(update={'status': 'disabled'}))
    response = http.get(f'/api/projects/{USER.default_project_id}/connectors')
    assert response.status_code == 404


def test_sync_rechecks_operator_project_binding_after_provider_returns(client, monkeypatch):
    from agentmesh.connector_sync import configuration
    from agentmesh.connector_sync.readers import GitHubIssuesReader

    http, repository = client
    monkeypatch.setenv('AGENTMESH_GITHUB_REPOSITORY', 'example/pilot')
    monkeypatch.delenv('AGENTMESH_GITHUB_TOKEN', raising=False)
    monkeypatch.delenv('AGENTMESH_GITHUB_CREDENTIAL_VERSION', raising=False)

    def respond(request):
        monkeypatch.setenv('AGENTMESH_CONNECTOR_PROJECT_ID', 'different_project')
        return httpx.Response(200, json=[])

    with httpx.Client(transport=httpx.MockTransport(respond)) as github:
        monkeypatch.setattr(configuration, 'GitHubIssuesReader',
                            lambda repository, **kwargs: GitHubIssuesReader(repository, client=github, **kwargs))
        response = http.post(f'/api/projects/{USER.default_project_id}/connectors/github_issues/sync',
                             json={'expected_version': 0})
    assert response.status_code == 404
    assert not repository.documents


def test_provider_failure_after_actor_revocation_only_settles_the_existing_claim(client, monkeypatch):
    from agentmesh.connector_sync import configuration
    from agentmesh.connector_sync.readers import GitHubIssuesReader

    http, repository = client
    monkeypatch.setenv('AGENTMESH_GITHUB_REPOSITORY', 'example/pilot')
    monkeypatch.delenv('AGENTMESH_GITHUB_TOKEN', raising=False)
    monkeypatch.delenv('AGENTMESH_GITHUB_CREDENTIAL_VERSION', raising=False)

    def respond(request):
        repository.save_user(USER.model_copy(update={'status': 'disabled'}))
        return httpx.Response(403, json={'message': 'private diagnostic'})

    with httpx.Client(transport=httpx.MockTransport(respond)) as github:
        monkeypatch.setattr(configuration, 'GitHubIssuesReader',
                            lambda repository, **kwargs: GitHubIssuesReader(repository, client=github, **kwargs))
        prefix = f'/api/projects/{USER.default_project_id}/connectors'
        response = http.post(prefix + '/github_issues/sync', json={'expected_version': 0})
        assert response.status_code == 404
        repository.save_user(USER)
        cursor = http.get(prefix).json()['items'][0]['cursor']
        assert cursor['status'] == 'failed' and cursor['last_error_code'] == 'connector_authority_changed'
        assert cursor['last_successful_at'] is None and not repository.documents


def test_disabling_connector_withholds_old_sources_and_refuses_further_sync(client, tmp_path, monkeypatch):
    http, repository = client
    (tmp_path / 'a.md').write_text('Authorized project documentation')
    monkeypatch.setenv('AGENTMESH_REPO_DOCS_ROOT', str(tmp_path))
    prefix = f'/api/projects/{USER.default_project_id}/connectors'
    original = http.post(prefix + '/repo_docs/sync', json={'expected_version': 0}).json()
    source_id = repository.documents[0].source.id
    disabled = http.post(prefix + '/' + original['id'] + '/control',
                         json={'expected_version': 1, 'action': 'disable'})
    assert disabled.status_code == 200 and disabled.json()['status'] == 'disabled'
    assert disabled.json()['version'] == 2
    assert repository.get_source(source_id).snapshot.lifecycle == 'unavailable'
    refused = http.post(prefix + '/repo_docs/sync', json={'expected_version': 2})
    assert refused.status_code == 409 and refused.json()['detail'] == 'connector_disabled'
    assert http.post(prefix + '/' + original['id'] + '/control',
                     json={'expected_version': 1, 'action': 'reset'}).status_code == 409
    restored = http.post(prefix + '/' + original['id'] + '/control',
                         json={'expected_version': 2, 'action': 'reset'})
    assert restored.status_code == 200 and restored.json()['enabled'] is True
    assert repository.get_source(source_id).snapshot.lifecycle == 'unavailable'


def test_reset_rebinds_changed_configuration_and_requires_a_fresh_observation(client, tmp_path, monkeypatch):
    http, repository = client
    old_root, new_root = tmp_path / 'old', tmp_path / 'new'
    old_root.mkdir()
    new_root.mkdir()
    (old_root / 'a.md').write_text('Original authorized documentation')
    (new_root / 'a.md').write_text('Replacement authorized documentation')
    monkeypatch.setenv('AGENTMESH_REPO_DOCS_ROOT', str(old_root))
    prefix = f'/api/projects/{USER.default_project_id}/connectors'
    original = http.post(prefix + '/repo_docs/sync', json={'expected_version': 0}).json()
    document = repository.documents[0]
    monkeypatch.setenv('AGENTMESH_REPO_DOCS_ROOT', str(new_root))
    assert http.post(prefix + '/repo_docs/sync', json={'expected_version': 1}).status_code == 409
    reset = http.post(prefix + '/' + original['id'] + '/control', json={'expected_version': 1, 'action': 'reset'})
    assert reset.status_code == 200
    assert reset.json()['configuration_hash'] != original['configuration_hash']
    assert reset.json()['watermark_at'] is None and reset.json()['completed_at'] is None
    assert repository.get_source(document.source.id).snapshot.lifecycle == 'unavailable'
    synced = http.post(prefix + '/repo_docs/sync', json={'expected_version': 2})
    assert synced.status_code == 200 and synced.json()['scan_mode'] == 'full'
    assert repository.get_document(document.id).text == 'Replacement authorized documentation'


def test_cancel_during_provider_read_prevents_the_old_page_from_committing(client, monkeypatch):
    from agentmesh.connector_sync import configuration
    from agentmesh.connector_sync.readers import GitHubIssuesReader

    http, repository = client
    monkeypatch.setenv('AGENTMESH_GITHUB_REPOSITORY', 'example/pilot')
    monkeypatch.delenv('AGENTMESH_GITHUB_TOKEN', raising=False)
    monkeypatch.delenv('AGENTMESH_GITHUB_CREDENTIAL_VERSION', raising=False)
    prefix = f'/api/projects/{USER.default_project_id}/connectors'
    initial = {}

    def respond(request):
        if initial:
            current = http.get(prefix).json()['items'][0]['cursor']
            cancelled = http.post(prefix + '/' + initial['id'] + '/control',
                                  json={'expected_version': current['version'], 'action': 'cancel'})
            assert cancelled.status_code == 200
        return httpx.Response(200, json=[{'number': 1, 'title': 'Evidence', 'body': 'Late evidence' if initial else 'Original',
            'state': 'open', 'updated_at': '2026-10-07T01:00:00Z' if initial else '2026-10-07T00:00:00Z',
            'html_url': 'https://github.com/example/pilot/issues/1'}])

    with httpx.Client(transport=httpx.MockTransport(respond)) as github:
        monkeypatch.setattr(configuration, 'GitHubIssuesReader',
                            lambda repository, **kwargs: GitHubIssuesReader(repository, client=github, **kwargs))
        initial.update(http.post(prefix + '/github_issues/sync', json={'expected_version': 0}).json())
        document = repository.documents[0]
        response = http.post(prefix + '/github_issues/sync', json={'expected_version': 1})
    assert response.status_code == 409
    assert repository.get_document(document.id) == document
    assert http.get(prefix).json()['items'][0]['cursor']['status'] == 'cancelled'


def test_removed_configuration_keeps_owned_cursor_visible_and_can_be_disabled(client, tmp_path, monkeypatch):
    http, repository = client
    (tmp_path / 'a.md').write_text('Authorized project documentation')
    monkeypatch.setenv('AGENTMESH_REPO_DOCS_ROOT', str(tmp_path))
    prefix = f'/api/projects/{USER.default_project_id}/connectors'
    original = http.post(prefix + '/repo_docs/sync', json={'expected_version': 0}).json()
    monkeypatch.delenv('AGENTMESH_REPO_DOCS_ROOT')
    item = http.get(prefix).json()['items'][0]
    assert item['configured'] is False and item['cursor']['id'] == original['id']
    disabled = http.post(prefix + '/' + original['id'] + '/control',
                         json={'expected_version': item['cursor']['version'], 'action': 'disable'})
    assert disabled.status_code == 200
    assert repository.get_source(repository.documents[0].source.id).snapshot.lifecycle == 'unavailable'


def test_control_rechecks_the_actual_actor_before_mutating_sources(client, tmp_path, monkeypatch):
    http, repository = client
    (tmp_path / 'a.md').write_text('Authorized project documentation')
    monkeypatch.setenv('AGENTMESH_REPO_DOCS_ROOT', str(tmp_path))
    prefix = f'/api/projects/{USER.default_project_id}/connectors'
    original = http.post(prefix + '/repo_docs/sync', json={'expected_version': 0}).json()
    source_id = repository.documents[0].source.id
    repository.save_user(USER.model_copy(update={'status': 'disabled'}))
    response = http.post(prefix + '/' + original['id'] + '/control',
                         json={'expected_version': 1, 'action': 'disable'})
    assert response.status_code == 404
    assert repository.get_source(source_id).snapshot.lifecycle == 'active'


@pytest.mark.parametrize('change', ['removed', 'changed'])
def test_changed_operator_binding_withholds_memory_without_waiting_for_a_control_click(client, tmp_path, monkeypatch, change):
    from agentmesh.memory_context.service import MemoryContextService
    from agentmesh.models import UserMemoryItem

    http, repository = client
    (tmp_path / 'a.md').write_text('Authorized project documentation')
    monkeypatch.setenv('AGENTMESH_REPO_DOCS_ROOT', str(tmp_path))
    prefix = f'/api/projects/{USER.default_project_id}/connectors'
    assert http.post(prefix + '/repo_docs/sync', json={'expected_version': 0}).status_code == 200
    source = repository.documents[0].source
    repository.add_user_memory_item(UserMemoryItem(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, title='Authorized project documentation',
        summary='Authorized project documentation', layer='long_term', source_kind='manual', sources=[source]))
    service = MemoryContextService(repository)
    query = dict(user=USER, agent_id=USER.personal_agent_id, project_id=USER.default_project_id)
    assert service.retrieve('Authorized project documentation', **query).hits
    if change == 'removed':
        monkeypatch.delenv('AGENTMESH_REPO_DOCS_ROOT')
    else:
        monkeypatch.setenv('AGENTMESH_REPO_DOCS_ROOT', str(tmp_path / 'different'))
    assert not service.retrieve('Authorized project documentation', **query).hits


def test_status_reconciliation_latches_removed_binding_until_explicit_reset(client, tmp_path, monkeypatch):
    http, repository = client
    (tmp_path / 'a.md').write_text('Authorized project documentation')
    monkeypatch.setenv('AGENTMESH_REPO_DOCS_ROOT', str(tmp_path))
    prefix = f'/api/projects/{USER.default_project_id}/connectors'
    assert http.post(prefix + '/repo_docs/sync', json={'expected_version': 0}).status_code == 200
    source_id = repository.documents[0].source.id
    monkeypatch.delenv('AGENTMESH_REPO_DOCS_ROOT')
    cursor = http.get(prefix).json()['items'][0]['cursor']
    assert cursor['enabled'] is False and cursor['version'] == 2
    assert cursor['last_error_code'] == 'connector_configuration_changed'
    assert repository.get_source(source_id).snapshot.lifecycle == 'unavailable'
    monkeypatch.setenv('AGENTMESH_REPO_DOCS_ROOT', str(tmp_path))
    assert http.post(prefix + '/repo_docs/sync', json={'expected_version': 2}).status_code == 409
    assert repository.get_source(source_id).snapshot.lifecycle == 'unavailable'


def test_startup_reconciliation_invalidates_removed_operator_bindings(client, tmp_path, monkeypatch):
    from agentmesh.connector_sync.service import ConnectorSyncService

    http, repository = client
    (tmp_path / 'a.md').write_text('Authorized project documentation')
    monkeypatch.setenv('AGENTMESH_REPO_DOCS_ROOT', str(tmp_path))
    prefix = f'/api/projects/{USER.default_project_id}/connectors'
    assert http.post(prefix + '/repo_docs/sync', json={'expected_version': 0}).status_code == 200
    source_id = repository.documents[0].source.id
    monkeypatch.delenv('AGENTMESH_REPO_DOCS_ROOT')
    assert ConnectorSyncService.reconcile_startup_bindings(repository) == 1
    assert repository.get_source(source_id).snapshot.lifecycle == 'unavailable'


def test_first_page_has_a_visible_claim_and_can_be_cancelled_before_any_document_commits(client, monkeypatch):
    from agentmesh.connector_sync import configuration
    from agentmesh.connector_sync.readers import GitHubIssuesReader

    http, repository = client
    monkeypatch.setenv('AGENTMESH_GITHUB_REPOSITORY', 'example/pilot')
    monkeypatch.delenv('AGENTMESH_GITHUB_TOKEN', raising=False)
    monkeypatch.delenv('AGENTMESH_GITHUB_CREDENTIAL_VERSION', raising=False)
    prefix = f'/api/projects/{USER.default_project_id}/connectors'

    def respond(request):
        cursor = http.get(prefix).json()['items'][0]['cursor']
        assert cursor is not None and cursor['status'] == 'reading'
        assert http.post(prefix + '/github_issues/sync', json={'expected_version': cursor['version']}).status_code == 409
        cancelled = http.post(prefix + '/' + cursor['id'] + '/control',
                              json={'expected_version': cursor['version'], 'action': 'cancel'})
        assert cancelled.status_code == 200
        return httpx.Response(200, json=[{'number': 1, 'title': 'Evidence', 'body': 'First late evidence',
            'state': 'open', 'updated_at': '2026-10-07T00:00:00Z',
            'html_url': 'https://github.com/example/pilot/issues/1'}])

    with httpx.Client(transport=httpx.MockTransport(respond)) as github:
        monkeypatch.setattr(configuration, 'GitHubIssuesReader',
                            lambda repository, **kwargs: GitHubIssuesReader(repository, client=github, **kwargs))
        response = http.post(prefix + '/github_issues/sync', json={'expected_version': 0})
    assert response.status_code == 409 and not repository.documents
    assert http.get(prefix).json()['items'][0]['cursor']['status'] == 'cancelled'


def test_automatic_sync_requires_explicit_enable_and_can_be_paused(client, tmp_path, monkeypatch):
    http, repository = client
    (tmp_path / 'a.md').write_text('Authorized project documentation')
    monkeypatch.setenv('AGENTMESH_REPO_DOCS_ROOT', str(tmp_path))
    prefix = f'/api/projects/{USER.default_project_id}/connectors'
    initial = http.post(prefix + '/repo_docs/sync', json={'expected_version': 0}).json()
    assert initial.get('auto_sync_enabled', False) is False
    endpoint = prefix + '/' + initial['id'] + '/control'
    enabled = http.post(endpoint, json={'expected_version': initial['version'], 'action': 'enable_auto',
                                       'interval_seconds': 300})
    assert enabled.status_code == 200 and enabled.json()['auto_sync_enabled'] is True
    assert enabled.json()['next_sync_at'] is not None
    paused = http.post(endpoint, json={'expected_version': enabled.json()['version'], 'action': 'pause_auto'})
    assert paused.status_code == 200 and paused.json()['auto_sync_enabled'] is False
    assert paused.json()['next_sync_at'] is None
    assert repository.documents[0].source.snapshot.lifecycle == 'active'
