"""Manual document commands keep current-authority writes and search atomic."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentmesh.documents import PlainTextDocumentParser
from agentmesh.ingestion import DocumentIngestionService
from agentmesh.memory_lifecycle import MemoryForgetRequestV1, MemoryForgettingService
from agentmesh.models import BlackboardPost, DocumentRecord, Project, Scope, Source, User, now_utc
from agentmesh.routes import documents
from agentmesh.routes.deps import current_user
from agentmesh.store import SQLiteStore


@pytest.fixture
def manual_api(tmp_path, monkeypatch):
    repository = SQLiteStore(tmp_path / 'manual.sqlite3')
    owner = repository.save_user(User(id='owner', name='Owner', role='user', workspace_id='ws',
                                     default_project_id='project', personal_agent_id='agent'))
    peer = repository.save_user(owner.model_copy(update={'id': 'peer'}))
    admin = repository.save_user(owner.model_copy(update={'id': 'admin', 'role': 'admin'}))
    repository.save_project(Project(id='project', name='Pilot', goal='Deliver', workspace_id='ws',
                                    member_ids=[owner.id, peer.id, admin.id]))
    document = repository.add_document(DocumentRecord(id='manual-document', title='Manual guide', file_name='guide.txt',
        content_type='text/plain', text='manual-first-boundary ' + 'x' * 450 + '\n\nmanual-second-boundary ' + 'y' * 450,
        source=Source(id='manual-source', title='Guide', source_type='document', reference='document://guide.txt'),
        workspace_id='ws', project_id='project', uploaded_by=owner.id))
    service = DocumentIngestionService(repository, PlainTextDocumentParser())
    monkeypatch.setattr(documents, 'store', repository)
    monkeypatch.setattr(documents, 'ingestion_service', service)
    app, selected = FastAPI(), [owner]
    app.include_router(documents.router)
    app.dependency_overrides[current_user] = lambda: selected[0]
    yield TestClient(app, raise_server_exceptions=False), repository, service, selected, document
    service.shutdown()
    repository.close()


def test_interrupted_manual_import_leaves_no_chunks_or_progress_and_retry_is_complete(manual_api):
    client, repository, service, _, document = manual_api
    with repository._connect() as connection:
        connection.execute("""CREATE TRIGGER fail_manual_chunk BEFORE INSERT ON records
            WHEN NEW.collection = 'user_memory_items'
             AND instr(json_extract(NEW.payload, '$.summary'), 'manual-second-boundary') > 0
            BEGIN SELECT RAISE(ABORT, 'private-database-failure-body'); END""")
    url = f'/api/documents/{document.id}/import-to-memory'
    failed = client.post(url)
    assert failed.status_code == 500
    assert repository.user_memory_items == []
    assert repository.sources == []
    persisted = client.get(f'/api/documents/{document.id}').json()['item']
    assert persisted['expected_chunks'] == persisted['completed_chunks'] == 0
    assert 'private-database-failure-body' not in failed.text
    with repository._connect() as connection:
        connection.execute('DROP TRIGGER fail_manual_chunk')
    result = client.post(url)
    assert result.status_code == 200 and result.json() == {'status': 'imported', 'chunk_count': 2}
    assert len(service.current_version_chunks(repository.get_document(document.id))) == 2
    assert client.post(url).json() == {'status': 'already_imported', 'chunk_count': 2}


def test_failed_edit_keeps_original_document_and_all_previous_chunks(manual_api):
    client, repository, service, _, document = manual_api
    assert client.post(f'/api/documents/{document.id}/import-to-memory').status_code == 200
    before = repository.get_document(document.id)
    chunks = service.current_version_chunks(before)
    with repository._connect() as connection:
        connection.execute("""CREATE TRIGGER fail_manual_invalidation BEFORE UPDATE ON records
            WHEN NEW.collection = 'user_memory_items' AND json_extract(NEW.payload, '$.status') = 'stale'
            BEGIN SELECT RAISE(ABORT, 'private-invalidation-failure-body'); END""")
    result = client.patch(f'/api/documents/{document.id}', json={'expected_version': 1, 'text': 'new version text'})
    assert result.status_code == 500
    assert repository.get_document(document.id).model_dump() == before.model_dump()
    assert service.current_version_chunks(before) == chunks
    assert 'private-invalidation-failure-body' not in result.text


def test_manual_reimport_recreates_a_missing_stable_source_once(manual_api):
    client, repository, _, _, document = manual_api
    url = f'/api/documents/{document.id}/import-to-memory'
    assert client.post(url).status_code == 200
    source_id = repository.sources[0].id
    with repository._connect() as connection:
        connection.execute("DELETE FROM records WHERE collection = 'sources' AND id = ?", (source_id,))
    result = client.post(url)
    assert result.status_code == 200 and result.json()['status'] == 'imported'
    assert repository.get_source(source_id) is not None
    assert len(repository.sources) == 2
    assert client.post(url).json()['status'] == 'already_imported'


def test_unknown_extra_chunk_requires_review_instead_of_claiming_complete(manual_api):
    client, repository, service, _, document = manual_api
    url = f'/api/documents/{document.id}/import-to-memory'
    assert client.post(url).status_code == 200
    chunk = service.current_version_chunks(repository.get_document(document.id))[0]
    extra = repository.add_user_memory_item(chunk.model_copy(update={'id': 'legacy-extra-chunk',
        'summary': 'unproven previous partial text', 'sources': [chunk.sources[0].model_copy(update={
            'reference': f'document://{document.id}#v1/chunk_99',
        })]}))
    result = client.post(url)
    assert result.status_code == 409 and result.json()['detail'] == 'document_chunk_requires_review'
    assert repository.get_user_memory_item(extra.id) == extra


def test_idempotent_manual_import_repairs_missing_search_projection(manual_api):
    client, repository, service, _, document = manual_api
    url = f'/api/documents/{document.id}/import-to-memory'
    assert client.post(url).status_code == 200
    chunks = service.current_version_chunks(repository.get_document(document.id))
    with repository._connect() as connection:
        connection.execute("DELETE FROM records_fts WHERE collection = 'user_memory_items'")
        connection.execute("DELETE FROM vector_states WHERE collection = 'user_memory_items'")
    assert client.post(url).status_code == 200
    hits = repository.search('manual-first-boundary', {Scope.PRIVATE}, workspace_id='ws', project_id='project',
                             user_id='owner')
    assert chunks[0].id in {hit.id for hit in hits}
    assert len(repository.user_memory_items) == len(repository.sources) == 2


def test_edit_invalidates_owned_old_chunks_and_signal_without_changing_peer_records(manual_api):
    client, repository, service, _, document = manual_api
    assert client.post(f'/api/documents/{document.id}/import-to-memory').status_code == 200
    old_chunks = service.current_version_chunks(repository.get_document(document.id))
    peer_chunk = repository.add_user_memory_item(old_chunks[0].model_copy(update={'id': 'peer-chunk', 'user_id': 'peer'}))
    post = repository.add_blackboard_post(BlackboardPost(id='bb_signal_owner', task_id='signal_owner',
        post_type='marketplace_signal', actor='signal_owner', title='Public summary', content='old automatic summary',
        scope='project', permission='project_visible', metadata={'workspace_id': 'ws', 'project_id': 'project'}))
    updated = client.patch(f'/api/documents/{document.id}', json={'expected_version': 1, 'text': 'replacement guide'})
    assert updated.status_code == 200 and updated.json()['item']['version'] == 2
    assert updated.json()['item']['expected_chunks'] == updated.json()['item']['completed_chunks'] == 0
    assert repository.get_user_memory_item(peer_chunk.id) == peer_chunk
    assert all(repository.get_user_memory_item(item.id).status == 'stale' for item in old_chunks)
    assert all(repository.vector_index.status('user_memory_items', item.id) is None for item in old_chunks)
    assert repository.get_blackboard_post(post.id).status == 'withdrawn'
    assert repository.get_blackboard_post(post.id).content == ''
    assert client.post(f'/api/documents/{document.id}/import-to-memory').json() == {'status': 'imported', 'chunk_count': 1}
    current = service.current_version_chunks(repository.get_document(document.id))
    assert len(current) == 1 and current[0].summary == 'replacement guide'
    assert current[0].sources[0].reference == f'document://{document.id}#v2/chunk_0'
    source = repository.get_source(current[0].sources[0].id)
    assert (source.user_id, source.workspace_id, source.project_id) == ('owner', 'ws', 'project')
    hits = repository.search('manual-first-boundary', {Scope.PRIVATE}, workspace_id='ws', project_id='project',
                             user_id='owner')
    assert not {item.id for item in old_chunks} & {hit.id for hit in hits}


def test_two_manual_imports_and_database_reopen_keep_one_current_import(manual_api):
    client, repository, _, selected, document = manual_api
    url = f'/api/documents/{document.id}/import-to-memory'
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(url), range(2)))
    assert all(response.status_code == 200 for response in responses)
    assert sorted(response.json()['status'] for response in responses) == ['already_imported', 'imported']
    assert len(repository.sources) == len(repository.user_memory_items) == 2
    assert len([event for event in repository.audit_events if event.action == 'import_document_memory']) == 1
    reopened = SQLiteStore(repository.db_path)
    try:
        from agentmesh.document_memory import DocumentMemoryStore

        result = DocumentMemoryStore(reopened).import_current(reopened.get_document(document.id), selected[0])
        assert result.already_imported and len(result.items) == 2
        assert len(reopened.user_memory_items) == len(reopened.sources) == 2
    finally:
        reopened.close()


@pytest.mark.parametrize('operation', ['import', 'edit'])
@pytest.mark.parametrize('change', ['owner_inactive', 'owner_workspace', 'member_removed', 'project_inactive', 'admin_demoted'])
def test_waiting_writer_rechecks_current_authority(operation, change, manual_api, monkeypatch):
    client, repository, _, selected, document = manual_api
    if change == 'admin_demoted':
        selected[0] = repository.get_user('admin')
    waiting = threading.Event()
    original_connect = repository._connect

    def observed_connect():
        connection = original_connect()
        connection.set_trace_callback(lambda sql: waiting.set() if sql == 'BEGIN IMMEDIATE' else None)
        return connection

    with closing(original_connect()) as blocker, blocker:
        blocker.execute('BEGIN IMMEDIATE')
        monkeypatch.setattr(repository, '_connect', observed_connect)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(client.post, f'/api/documents/{document.id}/import-to-memory') if operation == 'import' \
                else pool.submit(client.patch, f'/api/documents/{document.id}',
                                 json={'expected_version': 1, 'text': 'rejected replacement'})
            try:
                assert waiting.wait(5)
                if change == 'owner_inactive':
                    record = repository.get_user('owner').model_copy(update={'status': 'inactive'})
                    collection = 'users'
                elif change == 'owner_workspace':
                    record = repository.get_user('owner').model_copy(update={'workspace_id': 'other-workspace'})
                    collection = 'users'
                elif change == 'admin_demoted':
                    record = repository.get_user('admin').model_copy(update={'role': 'user'})
                    collection = 'users'
                else:
                    record = repository.get_project('project').model_copy(update={
                        'member_ids': ['peer', 'admin']} if change == 'member_removed' else {'status': 'archived'})
                    collection = 'projects'
                repository._upsert_plain_record(blocker, collection, record)
                blocker.commit()
            finally:
                blocker.rollback()
            response = future.result(timeout=5)
    assert response.status_code == 404 and response.json()['detail'] == 'document_not_found'
    assert repository.get_document(document.id) == document
    assert repository.user_memory_items == repository.sources == repository.audit_events == []


@pytest.mark.parametrize('withdraw', [False, True])
def test_manual_import_cannot_restore_forgotten_chunks_or_withdrawn_documents(withdraw, manual_api):
    client, repository, service, selected, document = manual_api
    url = f'/api/documents/{document.id}/import-to-memory'
    assert client.post(url).status_code == 200
    target = document if withdraw else service.current_version_chunks(repository.get_document(document.id))[0]
    lifecycle = MemoryForgettingService(repository)
    request = MemoryForgetRequestV1(command_id='forget-import', expected_version=target.version)
    if withdraw:
        lifecycle.withdraw_document(target.id, request, selected[0])
    else:
        lifecycle.forget(target.id, request, selected[0])
    result = client.post(url)
    assert result.status_code == (404 if withdraw else 409)
    if withdraw:
        assert client.patch(f'/api/documents/{document.id}', json={'expected_version': 1, 'text': 'restore'}).status_code == 404
        assert repository.get_document(document.id).withdrawn_at is not None
    else:
        assert repository.get_user_memory_item(target.id).status == 'forgotten'


def test_manual_import_does_not_unarchive_a_chunk(manual_api):
    client, repository, service, _, document = manual_api
    url = f'/api/documents/{document.id}/import-to-memory'
    assert client.post(url).status_code == 200
    chunk = service.current_version_chunks(repository.get_document(document.id))[0]
    archived = repository.save_user_memory_item(chunk.model_copy(update={'archived_at': now_utc()}))
    assert client.post(url).status_code == 409
    assert repository.get_user_memory_item(chunk.id) == archived


def test_selected_import_version_cannot_silently_switch_to_a_newer_document(manual_api):
    client, repository, _, _, document = manual_api
    assert client.patch(f'/api/documents/{document.id}', json={'expected_version': 1, 'text': 'new guide'}).status_code == 200
    url = f'/api/documents/{document.id}/import-to-memory'
    stale = client.post(url, params={'expected_version': 1})
    assert stale.status_code == 409 and stale.json()['detail'] == 'document_version_conflict'
    assert repository.user_memory_items == repository.sources == []
    assert client.post(url, params={'expected_version': 2}).json() == {'status': 'imported', 'chunk_count': 1}
    assert client.post(url, params={'expected_version': 0}).status_code == 422


@pytest.mark.parametrize('bump_version', [False, True])
def test_waiting_import_rejects_changed_body_even_without_a_version_bump(bump_version, manual_api, monkeypatch):
    client, repository, _, _, document = manual_api
    waiting = threading.Event()
    original_connect = repository._connect

    def observed_connect():
        connection = original_connect()
        connection.set_trace_callback(lambda sql: waiting.set() if sql == 'BEGIN IMMEDIATE' else None)
        return connection

    with closing(original_connect()) as blocker, blocker:
        blocker.execute('BEGIN IMMEDIATE')
        monkeypatch.setattr(repository, '_connect', observed_connect)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(client.post, f'/api/documents/{document.id}/import-to-memory')
            try:
                assert waiting.wait(5)
                changed = document.model_copy(update={'text': 'a different source body',
                    'version': 2 if bump_version else 1})
                repository._upsert_plain_record(blocker, 'documents', changed)
                blocker.commit()
            finally:
                blocker.rollback()
            result = future.result(timeout=5)
    assert result.status_code == 409 and result.json()['detail'] == 'document_version_conflict'
    assert repository.user_memory_items == repository.sources == repository.audit_events == []
    assert repository.get_document(document.id).text == 'a different source body'


@pytest.mark.parametrize('text,code', [('', 'document_text_empty'), ('x' * (1024 * 1024 + 1), 'document_import_too_large')])
def test_manual_import_limits_fail_without_partial_material(text, code, manual_api):
    client, repository, _, _, document = manual_api
    repository.save_document(document.model_copy(update={'text': text}))
    response = client.post(f'/api/documents/{document.id}/import-to-memory')
    assert response.status_code == 422 and response.json()['detail'] == code
    assert repository.user_memory_items == repository.sources == repository.audit_events == []
