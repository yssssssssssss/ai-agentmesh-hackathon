from __future__ import annotations

import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from agents.testing import ScriptedModel, assistant_message
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.agents import PersonalAgent
from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.document_memory import DocumentMemoryError, DocumentMemoryStore
from agentmesh.memory_context.service import MemoryContextError, MemoryContextService
from agentmesh.memory_facts import MemoryFactsError, MemoryFactsService, document_evidence_hash
from agentmesh.memory_governance.lifecycle import memory_content_hash
from agentmesh.memory_learning.contracts import DocumentLearnRequestV1, ExtractionResultV1, MemoryPreferencesPatchV1
from agentmesh.memory_learning.service import MemoryLearningService
from agentmesh.memory_payloads import FactAssertionV1, FactQueryV1, FactRememberV1
from agentmesh.models import Agent, AgentRun, ChatThread, DocumentRecord, DocumentUpdateRequest, Source, UserMemoryItem
from agentmesh.runtime_capacity import RuntimeCapacityController
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.store import SQLiteStore

AT = datetime(2026, 10, 7, tzinfo=UTC)
BODY_HASH = sha256(b'Original evidence').hexdigest()


@pytest.fixture
def project(tmp_path):
    repository = SQLiteStore(tmp_path / 'source-authority.sqlite3')
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    yield repository
    repository.close()


def _remember(repository, source):
    return repository.add_user_memory_item(UserMemoryItem(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, title='Original evidence', summary='Original evidence',
        layer='long_term', scope='private', source_kind='manual', sources=[source]))


def _retrieve(repository):
    return MemoryContextService(repository).retrieve('Original evidence', user=USER, agent_id=USER.personal_agent_id,
                                                   project_id=USER.default_project_id)


def _source(**changes):
    values = dict(id='src_versioned_evidence', title='Original evidence', source_type='web_page',
        reference='https://example.test/evidence', workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, user_id=USER.id, created_at=AT,
        snapshot=dict(provider='test_provider', external_id='evidence-1', version='provider-v1',
                      body_sha256=BODY_HASH, revision=1, observed_at=AT, lifecycle='active'))
    return Source(**(values | changes))


def test_source_snapshot_survives_storage_and_reopening(tmp_path):
    path = tmp_path / 'source-authority.sqlite3'
    repository = SQLiteStore(path)
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    repository.add_source(_source())
    repository.close()

    reopened = SQLiteStore(path)
    try:
        source = reopened.get_source('src_versioned_evidence')
        snapshot = source.model_dump(mode='json')['snapshot']
        assert snapshot['provider'] == 'test_provider'
        assert snapshot['external_id'] == 'evidence-1'
        assert snapshot['version'] == 'provider-v1'
        assert snapshot['body_sha256'] == BODY_HASH
        assert snapshot['revision'] == 1 and snapshot['lifecycle'] == 'active'
    finally:
        reopened.close()


def test_new_source_version_withholds_old_material_from_retrieval(tmp_path):
    repository = SQLiteStore(tmp_path / 'source-version-change.sqlite3')
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    try:
        source = repository.observe_source(_source(), body='Original evidence', user=USER, expected_revision=0)
        repository.add_user_memory_item(UserMemoryItem(user_id=USER.id, workspace_id=USER.workspace_id,
            project_id=USER.default_project_id, title='Original evidence', summary='Original evidence',
            layer='long_term', scope='private', source_kind='manual', sources=[source]))
        service = MemoryContextService(repository)
        before = service.retrieve('Original evidence', user=USER, agent_id=USER.personal_agent_id,
                                  project_id=USER.default_project_id)
        assert len(before.hits) == 1
        replacement = source.model_copy(update={'snapshot': source.snapshot.model_copy(update={
            'version': 'provider-v2', 'body_sha256': sha256(b'Updated evidence').hexdigest(),
        })})
        changed = repository.observe_source(replacement, body='Updated evidence', user=USER, expected_revision=1)
        assert changed.id == source.id and changed.snapshot.revision == 2
        assert not service.retrieve('Original evidence', user=USER, agent_id=USER.personal_agent_id,
                                    project_id=USER.default_project_id).hits
    finally:
        repository.close()


def test_immutable_source_entry_cannot_adopt_newer_snapshot_for_old_body(tmp_path):
    repository = SQLiteStore(tmp_path / 'source-old-writer.sqlite3')
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    try:
        old = repository.observe_source(_source(), body='Original evidence', user=USER, expected_revision=0)
        replacement = old.model_copy(update={'snapshot': old.snapshot.model_copy(update={
            'version': 'provider-v2', 'body_sha256': sha256(b'Updated evidence').hexdigest(),
        })})
        repository.observe_source(replacement, body='Updated evidence', user=USER, expected_revision=1)
        with pytest.raises(ValueError, match='source_snapshot_conflict'):
            repository.add_source(old)
        assert repository.get_source(old.id).snapshot.revision == 2
    finally:
        repository.close()


def test_legacy_source_and_memory_hashes_keep_the_original_wire_contract():
    source = Source(id='src_legacy_wire', title='Evidence', source_type='web_page',
                    reference='https://example.test/evidence', created_at=AT)
    assert 'snapshot' not in source.model_dump() and 'snapshot' not in source.model_dump_json()
    assert canonical_json_sha256(source.model_dump(mode='json')) == (
        'ef0c944c2d51d92ea0e3c77c1498562948b3636ce0eff5c9ad4dfe0e4c7d2e42'
    )
    item = UserMemoryItem(id='umem_legacy_wire', user_id='owner', workspace_id='workspace', project_id='project',
        title='Evidence', summary='Recorded evidence', layer='long_term', source_kind='manual', sources=[source],
        created_at=AT, updated_at=AT)
    assert memory_content_hash(item) == '2084379b41a6e2d0c354bf13ae5f087d60b49b128e294c3207a27231be713eb5'


@pytest.mark.parametrize('lifecycle', ['archived', 'deleted', 'unavailable'])
def test_source_lifecycle_withholds_material_without_mutating_memory_governance(project, lifecycle):
    source = project.observe_source(_source(), body='Original evidence', user=USER, expected_revision=0)
    memory = _remember(project, source)
    original_hash = memory_content_hash(memory)
    assert len(_retrieve(project).hits) == 1
    withdrawn = source.model_copy(update={'snapshot': source.snapshot.model_copy(update={'lifecycle': lifecycle})})
    changed = project.observe_source(withdrawn, body=None, user=USER, expected_revision=1)
    assert changed.snapshot.revision == 2 and changed.snapshot.lifecycle == lifecycle
    assert not _retrieve(project).hits
    current = project.get_user_memory_item(memory.id)
    assert current.status == 'active' and current.version == memory.version
    assert memory_content_hash(current) == original_hash


def test_prepared_material_cannot_commit_a_receipt_after_source_withdrawal(project):
    source = project.observe_source(_source(), body='Original evidence', user=USER, expected_revision=0)
    _remember(project, source)
    thread = project.add_chat_thread(ChatThread(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, project_chat=True, title='Source delivery'))
    run = project.save_agent_run(AgentRun(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, thread_id=thread.id, status='running', input_text='Original evidence'))
    service = MemoryContextService(project)
    prepared = service.prepare_for_run('Original evidence', run=run, user=USER, agent_id=USER.personal_agent_id)
    assert len(prepared.hits) == 1 and not project.list_memory_use_receipts_for_run(run.id)
    changed = source.model_copy(update={'snapshot': source.snapshot.model_copy(update={'lifecycle': 'deleted'})})
    project.observe_source(changed, body=None, user=USER, expected_revision=1)
    with pytest.raises(MemoryContextError, match='memory_use_source_changed'):
        service.commit_prepared_for_run(prepared, query='Original evidence', run=run, user=USER,
            agent_id=USER.personal_agent_id, reason='automatic_context')
    assert not project.list_memory_use_receipts_for_run(run.id)


def test_deleted_source_rejects_new_data_and_late_old_observation(project):
    source = project.observe_source(_source(), body='Original evidence', user=USER, expected_revision=0)
    deleted = source.model_copy(update={'snapshot': source.snapshot.model_copy(update={'lifecycle': 'deleted'})})
    terminal = project.observe_source(deleted, body=None, user=USER, expected_revision=1)
    with pytest.raises(ValueError, match='source_revision_conflict'):
        project.observe_source(source, body='Original evidence', user=USER, expected_revision=1)
    newer = source.model_copy(update={'snapshot': source.snapshot.model_copy(update={
        'version': 'provider-v2', 'body_sha256': sha256(b'Updated evidence').hexdigest(),
    })})
    with pytest.raises(ValueError, match='source_deleted'):
        project.observe_source(newer, body='Updated evidence', user=USER, expected_revision=2)
    assert project.get_source(source.id) == terminal


def test_same_provider_version_cannot_describe_different_body(project):
    source = project.observe_source(_source(), body='Original evidence', user=USER, expected_revision=0)
    forged = source.model_copy(update={'snapshot': source.snapshot.model_copy(update={
        'body_sha256': sha256(b'Different evidence').hexdigest(),
    })})
    with pytest.raises(ValueError, match='source_version_content_conflict'):
        project.observe_source(forged, body='Different evidence', user=USER, expected_revision=1)
    assert project.get_source(source.id) == source


@pytest.mark.parametrize('body', ['Different evidence', None])
def test_active_observation_needs_matching_original_bytes(project, body):
    with pytest.raises(ValueError, match='source_body_hash_mismatch|source_observation_body_required'):
        project.observe_source(_source(), body=body, user=USER, expected_revision=0)
    assert project.get_source('src_versioned_evidence') is None


def test_unchanged_observation_keeps_first_revision_time_and_audit(project):
    original = project.observe_source(_source(), body='Original evidence', user=USER, expected_revision=0)
    replay = original.model_copy(update={'created_at': AT + timedelta(days=1),
        'snapshot': original.snapshot.model_copy(update={'observed_at': AT + timedelta(days=1), 'revision': 999})})
    assert project.observe_source(replay, body='Original evidence', user=USER, expected_revision=1) == original
    assert len([event for event in project.audit_events if event.action == 'observe_source']) == 1


@pytest.mark.parametrize('field,value', [('provider', 'other_provider'), ('external_id', 'other-evidence')])
def test_registered_source_cannot_change_provider_identity(project, field, value):
    source = project.observe_source(_source(), body='Original evidence', user=USER, expected_revision=0)
    replaced = source.model_copy(update={'snapshot': source.snapshot.model_copy(update={field: value})})
    with pytest.raises(ValueError, match='source_identity_conflict'):
        project.observe_source(replaced, body='Original evidence', user=USER, expected_revision=1)
    assert project.get_source(source.id) == source


def test_one_external_identity_cannot_acquire_two_source_ids(project):
    source = project.observe_source(_source(), body='Original evidence', user=USER, expected_revision=0)
    duplicate = source.model_copy(update={'id': 'src_duplicate_identity'})
    with pytest.raises(ValueError, match='source_identity_conflict'):
        project.observe_source(duplicate, body='Original evidence', user=USER, expected_revision=0)
    assert project.get_source(source.id) == source and project.get_source(duplicate.id) is None


def test_older_observation_cannot_replace_current_provider_version(project):
    source = project.observe_source(_source(), body='Original evidence', user=USER, expected_revision=0)
    earlier = source.model_copy(update={'snapshot': source.snapshot.model_copy(update={
        'version': 'provider-v0', 'observed_at': AT - timedelta(seconds=1),
    })})
    with pytest.raises(ValueError, match='source_observation_stale'):
        project.observe_source(earlier, body='Original evidence', user=USER, expected_revision=1)
    assert project.get_source(source.id) == source


def test_concurrent_observations_and_reopening_preserve_one_next_revision(project):
    source = project.observe_source(_source(), body='Original evidence', user=USER, expected_revision=0)
    def update(index):
        body = f'Next evidence {index}'
        candidate = source.model_copy(update={'snapshot': source.snapshot.model_copy(update={
            'version': f'provider-v2-{index}', 'body_sha256': sha256(body.encode()).hexdigest(),
        })})
        try:
            return project.observe_source(candidate, body=body, user=USER, expected_revision=1).snapshot.revision
        except ValueError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(update, range(2)))
    assert sorted(outcomes, key=str) == [2, 'source_revision_conflict']
    reopened = SQLiteStore(project.db_path)
    try:
        current = reopened.get_source(source.id)
        assert current.snapshot.revision == 2
        with pytest.raises(ValueError, match='source_revision_conflict'):
            reopened.observe_source(source, body='Original evidence', user=USER, expected_revision=1)
    finally:
        reopened.close()


def test_failed_audit_rolls_back_observation_and_revision(project):
    with project._connect() as connection:
        connection.execute("""CREATE TRIGGER refuse_source_audit BEFORE INSERT ON records
            WHEN NEW.collection = 'audit_events' AND json_extract(NEW.payload, '$.action') = 'observe_source'
            BEGIN SELECT RAISE(ABORT, 'controlled_source_audit_failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match='controlled_source_audit_failure'):
        project.observe_source(_source(), body='Original evidence', user=USER, expected_revision=0)
    assert project.get_source('src_versioned_evidence') is None
    with project._connect() as connection:
        connection.execute('DROP TRIGGER refuse_source_audit')
    assert project.observe_source(_source(), body='Original evidence', user=USER, expected_revision=0).snapshot.revision == 1


def test_upgrading_legacy_source_does_not_invent_proof_on_old_memory(project):
    legacy = project.add_source(_source(snapshot=None))
    memory = _remember(project, legacy)
    original_hash = memory_content_hash(memory)
    assert len(_retrieve(project).hits) == 1
    project.observe_source(_source(), body='Original evidence', user=USER, expected_revision=0)
    assert not _retrieve(project).hits
    assert project.get_user_memory_item(memory.id).sources[0].snapshot is None
    assert memory_content_hash(project.get_user_memory_item(memory.id)) == original_hash


@pytest.mark.parametrize('change', ['version', 'withdrawal', 'legacy_upgrade'])
def test_changing_published_source_retracts_the_selected_public_signal(project, change):
    project.save_agent(Agent(id=USER.personal_agent_id, name='Source publisher', agent_type='personal', status='online',
        description='Controlled source publisher', owner_user_id=USER.id, workspace_id=USER.workspace_id))
    project.set_market_participation(USER.id, True)
    source = (project.add_source(_source(snapshot=None)) if change == 'legacy_upgrade' else
              project.observe_source(_source(), body='Original evidence', user=USER, expected_revision=0))
    _remember(project, source)

    class Client:
        def complete(self, *args):
            return '能力：来源分析\n可提供：证据答疑\n需要：项目进度支持'

    post = PersonalAgent(project, llm_client=Client()).publish_marketplace_signal(USER)
    assert post is not None
    if change == 'legacy_upgrade':
        project.observe_source(_source(), body='Original evidence', user=USER, expected_revision=0)
    else:
        update = ({'version': 'provider-v2', 'body_sha256': sha256(b'Updated evidence').hexdigest()}
              if change == 'version' else {'lifecycle': 'deleted'})
        replacement = source.model_copy(update={'snapshot': source.snapshot.model_copy(update=update)})
        project.observe_source(replacement, body='Updated evidence' if change == 'version' else None,
            user=USER, expected_revision=1)
    withdrawn = project.get_blackboard_post(post.id)
    assert withdrawn.status == 'withdrawn' and withdrawn.content == ''


def test_document_chunks_follow_the_current_parent_source_snapshot(project):
    source = project.observe_source(_source(source_type='document'), body='Original evidence', user=USER,
                                    expected_revision=0)
    document = project.add_document(DocumentRecord(title='Original evidence', file_name='evidence.txt',
        content_type='text/plain', text='Original evidence', source=source, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, uploaded_by=USER.id))
    DocumentMemoryStore(project).import_current(document, USER)
    assert len(_retrieve(project).hits) == 1
    unavailable = source.model_copy(update={'snapshot': source.snapshot.model_copy(update={'lifecycle': 'unavailable'})})
    project.observe_source(unavailable, body=None, user=USER, expected_revision=1)
    assert not _retrieve(project).hits


def test_late_learning_result_cannot_create_candidate_after_source_withdrawal(project):
    source = project.observe_source(_source(source_type='document'), body='Original evidence', user=USER,
                                    expected_revision=0)
    document = project.add_document(DocumentRecord(title='Original evidence', file_name='evidence.txt',
        content_type='text/plain', text='Original evidence', source=source, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, uploaded_by=USER.id))
    service = MemoryLearningService(project, mode_provider=lambda: 'execute', clock=lambda: AT)
    service.patch_preferences(MemoryPreferencesPatchV1(command_id='enable', expected_version=1,
                                                     learning_enabled=True), USER)
    job = service.enqueue(DocumentLearnRequestV1(source_document_id=document.id, source_version=document.version,
                                                source_hash=document_evidence_hash(document)), USER)

    class Extractor:
        async def extract(self, *args, **kwargs):
            changed = source.model_copy(update={'snapshot': source.snapshot.model_copy(update={'lifecycle': 'deleted'})})
            project.observe_source(changed, body=None, user=USER, expected_revision=1)
            return ExtractionResultV1.model_validate({'title': 'Candidate evidence', 'summary': 'Original evidence',
                'facts': [{'assertion': {'subject_type': 'project', 'subject_id': USER.default_project_id,
                    'predicate': 'constraint', 'value': 'Original evidence', 'time_precision': 'unknown'},
                    'start': 0, 'end': len(document.text), 'quote': document.text}]}), 100

    assert asyncio.run(service.run_once(Extractor())) == 1
    current = service.get_job(job.id, USER)
    assert current.candidate_memory_id is None and current.error_code == 'memory_learning_source_changed'
    assert not project.user_memory_items


@pytest.mark.parametrize('entry', ['fact_evidence', 'reimport', 'chunks'])
def test_source_withdrawal_reaches_public_document_consumers(project, entry):
    source = project.observe_source(_source(source_type='document'), body='Original evidence', user=USER,
                                    expected_revision=0)
    document = project.add_document(DocumentRecord(title='Original evidence', file_name='evidence.txt',
        content_type='text/plain', text='Original evidence', source=source, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, uploaded_by=USER.id))
    imports = DocumentMemoryStore(project)
    imports.import_current(document, USER)
    assert MemoryFactsService(project).document_evidence(document.id, USER).version == 1
    document = project.get_document(document.id)
    unavailable = source.model_copy(update={'snapshot': source.snapshot.model_copy(update={'lifecycle': 'unavailable'})})
    project.observe_source(unavailable, body=None, user=USER, expected_revision=1)
    error = MemoryFactsError if entry == 'fact_evidence' else DocumentMemoryError
    with pytest.raises(error, match='fact_source_not_found|document_not_found'):
        if entry == 'fact_evidence':
            MemoryFactsService(project).document_evidence(document.id, USER)
        elif entry == 'reimport':
            imports.import_current(document, USER)
        else:
            imports.current_chunks(document)


@pytest.mark.parametrize('change', ['withdrawal', 'tampered_body'])
def test_document_http_reads_withhold_unavailable_or_inconsistent_source(project, monkeypatch, change):
    from agentmesh.routes import documents as routes
    from agentmesh.routes.deps import current_user

    source = project.observe_source(_source(source_type='document'), body='Original evidence', user=USER,
                                    expected_revision=0)
    document = project.add_document(DocumentRecord(title='Original evidence', file_name='evidence.txt',
        content_type='text/plain', text='Original evidence', source=source, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, uploaded_by=USER.id))
    monkeypatch.setattr(routes, 'store', project)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[current_user] = lambda: USER
    with TestClient(app) as client:
        assert client.get(f'/api/documents/{document.id}').status_code == 200
        assert len(client.get('/api/documents').json()['items']) == 1
        if change == 'withdrawal':
            withdrawn = source.model_copy(update={'snapshot': source.snapshot.model_copy(
                update={'lifecycle': 'unavailable'})})
            project.observe_source(withdrawn, body=None, user=USER, expected_revision=1)
        else:
            project.add_document(document.model_copy(update={'text': 'Unverified replacement evidence'}))
        assert client.get(f'/api/documents/{document.id}').status_code == 404
        assert client.get('/api/documents').json()['items'] == []


def test_local_document_edit_cannot_forge_a_managed_external_source_version(project):
    source = project.observe_source(_source(source_type='document'), body='Original evidence', user=USER,
                                    expected_revision=0)
    document = project.add_document(DocumentRecord(title='Original evidence', file_name='evidence.txt',
        content_type='text/plain', text='Original evidence', source=source, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, uploaded_by=USER.id))
    original = document.model_dump(mode='json')
    with pytest.raises(DocumentMemoryError, match='document_source_read_only'):
        DocumentMemoryStore(project).update(document.id,
            DocumentUpdateRequest(text='Local edit', expected_version=document.version), USER)
    assert project.get_document(document.id).model_dump(mode='json') == original
    assert project.get_source(source.id).snapshot.revision == 1


def test_server_owned_source_revision_cannot_overflow_its_wire_contract(project):
    maximum = 2147483647
    source = project.add_source(_source(snapshot=dict(provider='test_provider', external_id='evidence-1',
        version='provider-v1', body_sha256=BODY_HASH, revision=maximum, observed_at=AT)))
    changed = source.model_copy(update={'snapshot': source.snapshot.model_copy(update={'lifecycle': 'archived'})})
    with pytest.raises(ValueError, match='source_revision_exhausted'):
        project.observe_source(changed, body=None, user=USER, expected_revision=maximum)
    assert project.get_source(source.id).snapshot.revision == maximum


@pytest.mark.parametrize('field,value', [
    ('provider', 'unsafe/provider'), ('external_id', ''), ('version', ''), ('body_sha256', 'not-a-hash'),
    ('revision', True), ('revision', 0), ('revision', 2147483648),
    ('observed_at', AT.replace(tzinfo=None)), ('lifecycle', 'unknown'),
])
def test_invalid_observation_is_revalidated_before_a_write(project, field, value):
    source = _source()
    malformed = source.model_copy(update={'snapshot': source.snapshot.model_copy(update={field: value})})
    with pytest.raises(ValueError, match='source_observation_invalid'):
        project.observe_source(malformed, body='Original evidence', user=USER, expected_revision=0)
    assert project.get_source(source.id) is None


def test_source_snapshot_rejects_unknown_fields_at_the_wire_boundary():
    payload = _source().model_dump(mode='json')
    payload['snapshot']['unknown_field'] = 'unexpected'
    with pytest.raises(ValidationError, match='extra_forbidden'):
        Source.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize('change', ['disabled', 'membership', 'project_archived', 'wrong_owner'])
def test_observation_requires_current_owner_and_active_project_authority(project, change):
    source = project.observe_source(_source(), body='Original evidence', user=USER, expected_revision=0)
    changed = source.model_copy(update={'snapshot': source.snapshot.model_copy(update={'lifecycle': 'archived'})})
    if change == 'disabled':
        project.save_user(USER.model_copy(update={'status': 'disabled'}))
    elif change in {'membership', 'project_archived'}:
        current = project.get_project(USER.default_project_id)
        updates = {'member_ids': ['different_member']} if change == 'membership' else {'status': 'archived'}
        project.save_project(current.model_copy(update=updates))
    else:
        changed = changed.model_copy(update={'user_id': 'different_owner'})
    with pytest.raises(ValueError, match='source_not_found'):
        project.observe_source(changed, body=None, user=USER, expected_revision=1)
    assert project.get_source(source.id) == source


@pytest.mark.parametrize('change', ['unchanged', 'withdrawal'])
def test_queued_sdk_request_sends_only_current_source_material(project, monkeypatch, change):
    source = project.observe_source(_source(), body='Original evidence', user=USER, expected_revision=0)
    _remember(project, source)
    thread = project.add_chat_thread(ChatThread(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, project_chat=True, title='Queued source delivery'))
    run = project.save_agent_run(AgentRun(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, thread_id=thread.id, project_chat=True,
        status='running', input_text='Original evidence'))
    model = ScriptedModel([[assistant_message('Original evidence [P1]')]])
    runtime = AgentRuntimeService(project, model=model, enabled=True, capacity=RuntimeCapacityController(llm_limit=1))
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'inject')

    async def scenario():
        admitted = asyncio.Event()
        append = project.append_agent_run_event

        def record_admission(run_id, event_type, payload=None):
            event = append(run_id, event_type, payload)
            if run_id == run.id and event_type == 'context_request_budget':
                admitted.set()
            return event

        monkeypatch.setattr(project, 'append_agent_run_event', record_admission)
        pending = None
        try:
            async with runtime.capacity.llm_slot():
                pending = asyncio.create_task(runtime._execute_run(run=run, selected=runtime._select_model(USER),
                    content=run.input_text, user=USER, history=[], skill=None))
                async with asyncio.timeout(10):
                    await admitted.wait()
                assert not model.calls and not project.list_memory_use_receipts_for_run(run.id)
                if change == 'withdrawal':
                    withdrawn = source.model_copy(update={'snapshot': source.snapshot.model_copy(
                        update={'lifecycle': 'deleted'})})
                    project.observe_source(withdrawn, body=None, user=USER, expected_revision=1)
            if change == 'withdrawal':
                with pytest.raises(MemoryContextError, match='memory_use_source_changed'):
                    await pending
                assert not model.calls and not project.list_memory_use_receipts_for_run(run.id)
            else:
                answer = await pending
                assert answer.content == 'Original evidence [P1]' and len(model.calls) == 1
                assert len(project.list_memory_use_receipts_for_run(run.id)) == 1
        finally:
            if pending is not None and not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)

    asyncio.run(scenario())


def test_fact_query_and_command_replay_require_current_source_evidence(project):
    source = project.observe_source(_source(source_type='document'), body='Original evidence', user=USER,
                                    expected_revision=0)
    document = project.add_document(DocumentRecord(title='Original evidence', file_name='evidence.txt',
        content_type='text/plain', text='Original evidence', source=source, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, uploaded_by=USER.id))
    service = MemoryFactsService(project, clock=lambda: AT)
    request = FactRememberV1(command_id='managed-source-fact', title='Confirmed constraint',
        summary='Original evidence', project_id=USER.default_project_id, source_document_id=document.id,
        source_version=document.version, source_hash=document_evidence_hash(document), facts=[
            FactAssertionV1(subject_type='project', subject_id=USER.default_project_id,
                            predicate='constraint', value='Original evidence', valid_from=AT)])
    memory = service.remember(request, USER)
    query = FactQueryV1(project_id=USER.default_project_id, subject_type='project',
                       subject_id=USER.default_project_id, predicate='constraint')
    assert service.query(query, USER).outcome == 'known'
    assert service.remember(request, USER).id == memory.id
    withdrawn = source.model_copy(update={'snapshot': source.snapshot.model_copy(update={'lifecycle': 'unavailable'})})
    project.observe_source(withdrawn, body=None, user=USER, expected_revision=1)
    result = service.query(query, USER)
    assert result.outcome == 'insufficient_evidence' and not result.facts
    with pytest.raises(MemoryFactsError, match='fact_memory_no_longer_available'):
        service.remember(request, USER)
    assert len(project.user_memory_items) == 1


def test_unselected_source_change_and_observation_replay_preserve_selected_publication(project):
    project.save_agent(Agent(id=USER.personal_agent_id, name='Source publisher', agent_type='personal', status='online',
        description='Controlled source publisher', owner_user_id=USER.id, workspace_id=USER.workspace_id))
    project.set_market_participation(USER.id, True)
    source = project.observe_source(_source(), body='Original evidence', user=USER, expected_revision=0)
    _remember(project, source)
    extra = source.model_copy(update={'id': 'src_unselected', 'snapshot': source.snapshot.model_copy(
        update={'external_id': 'unselected-evidence'})})
    extra = project.observe_source(extra, body='Original evidence', user=USER, expected_revision=0)
    skipped = _remember(project, extra)
    project.save_user_memory_item(skipped.model_copy(update={'sensitivity': 'high'}))

    class Client:
        def complete(self, *args):
            return '能力：来源分析\n可提供：证据答疑\n需要：项目进度支持'

    post = PersonalAgent(project, llm_client=Client()).publish_marketplace_signal(USER)
    assert post is not None
    replay = source.model_copy(update={'snapshot': source.snapshot.model_copy(
        update={'observed_at': AT + timedelta(days=1)})})
    assert project.observe_source(replay, body='Original evidence', user=USER, expected_revision=1) == source
    archived = extra.model_copy(update={'snapshot': extra.snapshot.model_copy(update={'lifecycle': 'archived'})})
    project.observe_source(archived, body=None, user=USER, expected_revision=1)
    assert project.get_blackboard_post(post.id) == post


def test_source_withdrawal_during_model_generation_refuses_late_publication(project):
    project.save_agent(Agent(id=USER.personal_agent_id, name='Source publisher', agent_type='personal', status='online',
        description='Controlled source publisher', owner_user_id=USER.id, workspace_id=USER.workspace_id))
    project.set_market_participation(USER.id, True)
    source = project.observe_source(_source(), body='Original evidence', user=USER, expected_revision=0)
    _remember(project, source)

    class Client:
        def complete(self, *args):
            withdrawn = source.model_copy(update={'snapshot': source.snapshot.model_copy(
                update={'lifecycle': 'deleted'})})
            project.observe_source(withdrawn, body=None, user=USER, expected_revision=1)
            return '能力：来源分析\n可提供：证据答疑\n需要：项目进度支持'

    assert PersonalAgent(project, llm_client=Client()).publish_marketplace_signal(USER) is None
    assert not project.blackboard_posts


def test_source_and_publication_retraction_roll_back_when_audit_cannot_commit(project):
    project.save_agent(Agent(id=USER.personal_agent_id, name='Source publisher', agent_type='personal', status='online',
        description='Controlled source publisher', owner_user_id=USER.id, workspace_id=USER.workspace_id))
    project.set_market_participation(USER.id, True)
    source = project.observe_source(_source(), body='Original evidence', user=USER, expected_revision=0)
    _remember(project, source)

    class Client:
        def complete(self, *args):
            return '能力：来源分析\n可提供：证据答疑\n需要：项目进度支持'

    post = PersonalAgent(project, llm_client=Client()).publish_marketplace_signal(USER)
    assert post is not None
    with project._connect() as connection:
        connection.execute("""CREATE TRIGGER refuse_source_update_audit BEFORE INSERT ON records
            WHEN NEW.collection = 'audit_events' AND json_extract(NEW.payload, '$.action') = 'observe_source'
            BEGIN SELECT RAISE(ABORT, 'controlled_source_audit_failure'); END""")
    withdrawn = source.model_copy(update={'snapshot': source.snapshot.model_copy(update={'lifecycle': 'deleted'})})
    with pytest.raises(sqlite3.IntegrityError, match='controlled_source_audit_failure'):
        project.observe_source(withdrawn, body=None, user=USER, expected_revision=1)
    assert project.get_source(source.id) == source
    assert project.get_blackboard_post(post.id) == post


@pytest.mark.parametrize('origin', ['direct_memory', 'document_parent', 'current_proof'])
def test_reopen_withdraws_legacy_generated_signals_without_registered_source_dependencies(project, origin):
    project.save_agent(Agent(id=USER.personal_agent_id, name='Source publisher', agent_type='personal', status='online',
        description='Controlled source publisher', owner_user_id=USER.id, workspace_id=USER.workspace_id))
    project.set_market_participation(USER.id, True)
    source = project.observe_source(_source(source_type='document' if origin == 'document_parent' else 'web_page'),
                                    body='Original evidence', user=USER, expected_revision=0)
    if origin == 'document_parent':
        document = project.add_document(DocumentRecord(title='Original evidence', file_name='evidence.txt',
            content_type='text/plain', text='Original evidence', source=source, workspace_id=USER.workspace_id,
            project_id=USER.default_project_id, uploaded_by=USER.id))
        DocumentMemoryStore(project).import_current(document, USER)
    else:
        _remember(project, source)

    class Client:
        def complete(self, *args):
            return '能力：来源分析\n可提供：证据答疑\n需要：项目进度支持'

    post = PersonalAgent(project, llm_client=Client()).publish_marketplace_signal(USER)
    assert post is not None
    if origin != 'current_proof':
        # Characterize an older publication that tracked Memory/Document but not Source.
        with project._connect() as connection:
            connection.execute("DELETE FROM market_publication_inputs WHERE post_id = ? "
                               "AND collection = 'sources' AND record_id = ?", (post.id, source.id))
    project.close()
    reopened = SQLiteStore(project.db_path)
    try:
        current = reopened.get_blackboard_post(post.id)
        if origin == 'current_proof':
            assert current == post
        else:
            assert current.status == 'withdrawn' and current.content == ''
    finally:
        reopened.close()
