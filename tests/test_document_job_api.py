from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentmesh.document_parser_process import IsolatedDocumentParser
from agentmesh.documents import PlainTextDocumentParser
from agentmesh.ingestion import DocumentIngestionService
from agentmesh.models import DocumentParseJob, Project, User
from agentmesh.routes import documents
from agentmesh.routes.deps import current_user
from agentmesh.store import SQLiteStore


@pytest.fixture
def document_api(tmp_path, monkeypatch):
    repository = SQLiteStore(tmp_path / 'api.sqlite3')
    owner = repository.save_user(User(id='owner', name='Owner', role='user', workspace_id='ws',
                                     default_project_id='project', personal_agent_id='agent'))
    peer = repository.save_user(owner.model_copy(update={'id': 'peer'}))
    admin = repository.save_user(owner.model_copy(update={'id': 'admin', 'role': 'admin'}))
    repository.save_project(Project(id='project', name='Pilot', goal='Deliver', workspace_id='ws',
                                    member_ids=[owner.id, peer.id, admin.id]))

    class InitiallyUnavailableParser(PlainTextDocumentParser):
        calls = 0

        def parse(self, request):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError('must-never-persist-or-return-private-parser-body')
            return super().parse(request)

    parser = InitiallyUnavailableParser()
    service = DocumentIngestionService(repository, parser)
    monkeypatch.setattr(documents, 'store', repository)
    monkeypatch.setattr(documents, 'ingestion_service', service)
    app, selected = FastAPI(), [owner]
    app.include_router(documents.router)
    app.dependency_overrides[current_user] = lambda: selected[0]
    yield TestClient(app), repository, service, parser, selected, owner, peer, admin
    service.shutdown()
    repository.close()


def test_real_isolated_upload_entry_and_invalid_encoding_preserve_atomic_private_contract(document_api):
    client, repository, service, _parser, _selected, owner, *_others = document_api
    service.parser = IsolatedDocumentParser()
    response = client.post('/api/documents/upload', files={'file': ('note.txt', b'# Project\nCurrent source', 'text/plain')})
    assert response.status_code == 200
    document = response.json()['item']
    assert document['uploaded_by'] == owner.id and document['text'] == 'Current source'
    assert len(repository.documents) == len(repository.sources) == 1
    invalid = client.post('/api/documents/upload', files={'file': ('bad.txt', b'private input\xff', 'text/plain')})
    assert invalid.status_code == 400 and invalid.json()['detail'] == 'document_text_encoding_invalid'
    assert 'private input' not in invalid.text
    assert len(repository.documents) == len(repository.sources) == 1
    jobs = client.get('/api/documents/jobs').json()['items']
    assert len(jobs) == 2 and sum(item['status'] == 'failed' for item in jobs) == 1


def test_owned_retry_is_versioned_idempotent_and_keeps_parser_errors_private(document_api, monkeypatch):
    client, repository, service, parser, selected, owner, peer, admin = document_api
    failed = client.post('/api/documents/upload', files={'file': ('note.txt', b'original upload', 'text/plain')})
    assert failed.status_code == 500 and failed.json()['detail'] == 'document_ingestion_failed'
    assert 'private-parser-body' not in failed.text
    job = client.get('/api/documents/jobs').json()['items'][0]
    assert 'private-parser-body' not in str(job)
    url = f"/api/documents/jobs/{job['id']}"
    body = {'expected_version': job['state_version'], 'command_id': 'retry-upload'}
    for actor in (peer, admin):
        selected[0] = actor
        assert client.post(url + '/retry', json=body).status_code == 404
    selected[0] = owner
    assert client.post(url + '/retry', json={**body, 'uploaded_by': admin.id}).status_code == 422
    assert client.post(url + '/retry', json={**body, 'expected_version': 1}).status_code == 409
    assert client.post(url + '/retry', json=body).status_code == 202
    service.shutdown()
    assert client.get(url).json()['item']['status'] == 'completed'
    reopened = DocumentIngestionService(SQLiteStore(repository.db_path), parser)
    monkeypatch.setattr(documents, 'ingestion_service', reopened)
    try:
        replay = client.post(url + '/retry', json=body)
        assert replay.status_code == 202 and replay.json()['item']['status'] == 'completed'
        assert client.post(url + '/retry', json={**body, 'expected_version': 999}).status_code == 409
        assert parser.calls == 2 and len(repository.documents) == len(repository.sources) == 1
    finally:
        reopened.shutdown()


def test_current_project_membership_controls_job_reads_and_retry(document_api):
    client, repository, _, _, _, owner, _, _ = document_api
    client.post('/api/documents/upload', files={'file': ('note.txt', b'input', 'text/plain')})
    job = client.get('/api/documents/jobs').json()['items'][0]
    repository.save_project(repository.get_project('project').model_copy(update={'member_ids': ['peer']}))
    assert client.get('/api/documents/jobs').json()['items'] == []
    url = f"/api/documents/jobs/{job['id']}"
    assert client.get(url).status_code == 404
    assert client.post(url + '/retry', json={'expected_version': job['state_version'], 'command_id': 'revoked'}).status_code == 404
    assert repository.get_user(owner.id).status == 'active'


def test_job_pagination_is_bounded_and_does_not_materialize_other_owners(document_api):
    client, repository, _, _, selected, owner, peer, _ = document_api
    for index in range(5):
        repository.save_document_parse_job(DocumentParseJob(id=f'owned-{index}', workspace_id='ws',
            project_id='project', uploaded_by=owner.id, file_name=f'{index}.txt', content_type='text/plain'))
        repository.save_document_parse_job(DocumentParseJob(id=f'peer-{index}', workspace_id='ws',
            project_id='project', uploaded_by=peer.id, file_name=f'{index}.txt', content_type='text/plain'))
    first = client.get('/api/documents/jobs', params={'limit': 2}).json()
    assert [job['id'] for job in first['items']] == ['owned-4', 'owned-3']
    second = client.get('/api/documents/jobs', params={'limit': 2, 'before': first['next_cursor']}).json()
    assert [job['id'] for job in second['items']] == ['owned-2', 'owned-1']
    selected[0] = peer
    assert all(job['uploaded_by'] == peer.id for job in client.get('/api/documents/jobs').json()['items'])
    assert client.get('/api/documents/jobs', params={'limit': 101}).status_code == 422


def test_public_retry_never_exceeds_three_parser_attempts(document_api, monkeypatch):
    import time

    client, repository, _, parser, _, _, _, _ = document_api

    def unavailable(_request):
        parser.calls += 1
        raise RuntimeError('private parser failure')

    monkeypatch.setattr(parser, 'parse', unavailable)
    client.post('/api/documents/upload', files={'file': ('note.txt', b'input', 'text/plain')})
    job = client.get('/api/documents/jobs').json()['items'][0]
    url = f"/api/documents/jobs/{job['id']}"
    for attempt in (2, 3):
        assert client.post(url + '/retry', json={'expected_version': job['state_version'],
                                               'command_id': f'retry-{attempt}'}).status_code == 202
        deadline = time.monotonic() + 5
        while True:
            job = client.get(url).json()['item']
            if job['status'] == 'failed' and job['attempt_count'] == attempt:
                break
            assert time.monotonic() < deadline
            time.sleep(0.01)
    rejected = client.post(url + '/retry', json={'expected_version': job['state_version'], 'command_id': 'too-many'})
    assert rejected.status_code == 409 and rejected.json()['detail'] == 'document_attempt_limit_reached'
    assert parser.calls == 3 and repository.documents == repository.sources == repository.user_memory_items == []
