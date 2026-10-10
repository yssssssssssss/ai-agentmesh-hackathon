from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from agents.testing import ScriptedModel, assistant_message, function_call
from fastapi.testclient import TestClient

from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.agent_runtime.session import AgentMeshSession
from agentmesh.memory_context.service import MemoryContextError, MemoryContextService
from agentmesh.memory_facts import MemoryFactsService, document_evidence_hash
from agentmesh.memory_payloads import FactAssertionV1, FactQueryV1, FactRememberV1
from agentmesh.models import AgentRun, AgentToolGrant, DocumentRecord, Project, Source, User, UserRole
from agentmesh.store import SQLiteStore
from agentmesh.terminology import ProjectTerminologyService, TermAliasUpdateV1, TerminologyError
from agentmesh.tools import ensure_tool_seed_data

NOW = datetime(2026, 10, 5, tzinfo=UTC)


@pytest.fixture
def vocabulary(tmp_path):
    repository = SQLiteStore(tmp_path / 'terminology.sqlite3')
    owner = repository.save_user(User(id='term_owner', name='Owner', role='team_lead', personal_agent_id='term_agent',
                                     workspace_id='term_ws', default_project_id='term_project'))
    peer = repository.save_user(owner.model_copy(update={'id': 'term_peer', 'role': UserRole.USER}))
    project = repository.save_project(Project(id=owner.default_project_id, workspace_id=owner.workspace_id,
                                              name='Terms', goal='Ship', member_ids=[owner.id, peer.id]))
    source = repository.add_source(Source(id='term_source', title='Terms evidence', source_type='document',
                                          reference='document://term_doc#v1/text', user_id=owner.id,
                                          workspace_id=owner.workspace_id, project_id=project.id))
    document = repository.add_document(DocumentRecord(id='term_doc', title='Terms evidence', text='Gateway V1. Entry V2.',
                                                       source=source, uploaded_by=owner.id, workspace_id=owner.workspace_id,
                                                       project_id=project.id, file_name='terms.txt', content_type='text/plain'))
    yield repository, owner, peer, project, document
    repository.close()


def remember(repository, owner, document, name, value, command):
    return MemoryFactsService(repository, clock=lambda: NOW).remember(FactRememberV1(
        command_id=command, title='Term version', summary='Confirmed terminology', project_id=document.project_id,
        source_document_id=document.id, source_version=1, source_hash=document_evidence_hash(document),
        facts=[FactAssertionV1(subject_type='term', subject_id=name, predicate='version', value=value, valid_from=NOW)],
    ), owner)


def query(repository, owner, project, name, subject_type='term'):
    return MemoryFactsService(repository, clock=lambda: NOW).query(FactQueryV1(
        project_id=project.id, subject_type=subject_type, subject_id=name, predicate='version',
    ), owner)


def test_confirmed_project_alias_resolves_existing_and_new_facts_without_rewriting_evidence(vocabulary):
    repository, owner, _, project, document = vocabulary
    existing = remember(repository, owner, document, '入口', 'V1', 'existing_term')
    service = ProjectTerminologyService(repository)
    updated = service.update(project.id, TermAliasUpdateV1(command_id='confirm_alias', expected_version=0,
                                                         aliases={'入口': 'API Gateway'}), owner)
    assert updated.version == 1
    result = query(repository, owner, project, ' api   GATEWAY ')
    assert result.outcome == 'known'
    assert result.facts[0].memory_id == existing.id
    assert result.facts[0].fact.subject_id == f'{project.id}::入口'
    assert result.term_resolution.canonical_subject_id == f'{project.id}::api gateway'
    assert result.term_resolution.alias_version == 1
    assert repository.get_user_memory_item(existing.id) == existing
    newer = remember(repository, owner, document, '入口', 'V1', 'new_term')
    assert newer.facts[0].subject_id == f'{project.id}::api gateway'
    assert len(query(repository, owner, project, '入口').facts) == 2


def test_alias_merge_exposes_conflicting_confirmations(vocabulary):
    repository, owner, _, project, document = vocabulary
    remember(repository, owner, document, '入口', 'V1', 'alias_conflict_a')
    remember(repository, owner, document, 'API Gateway', 'V2', 'alias_conflict_b')
    ProjectTerminologyService(repository).update(project.id, TermAliasUpdateV1(
        command_id='merge_terms', expected_version=0, aliases={'入口': 'API Gateway'},
    ), owner)
    result = query(repository, owner, project, '入口')
    assert result.outcome == 'conflict'
    assert not result.automatic_context_eligible
    assert len(result.conflicts[0].fact_indexes) == 2


def test_alias_update_uses_current_permissions_membership_cas_and_durable_command(vocabulary):
    repository, owner, peer, project, _ = vocabulary
    service = ProjectTerminologyService(repository)
    request = TermAliasUpdateV1(command_id='owned_alias', expected_version=0, aliases={'入口': '网关'})
    with pytest.raises(TerminologyError, match='terminology_manage_forbidden'):
        service.update(project.id, request, peer)
    first = service.update(project.id, request, owner)
    assert service.update(project.id, request, owner) == first
    with pytest.raises(TerminologyError, match='terminology_version_conflict'):
        service.update(project.id, request.model_copy(update={'command_id': 'stale_alias'}), owner)
    with pytest.raises(TerminologyError, match='terminology_command_conflict'):
        service.update(project.id, request.model_copy(update={'aliases': {'入口': '其他'}}), owner)
    reopened = SQLiteStore(repository.db_path)
    try:
        assert ProjectTerminologyService(reopened).update(project.id, request, owner) == first
    finally:
        reopened.close()
    repository.save_project(project.model_copy(update={'member_ids': [peer.id]}))
    with pytest.raises(TerminologyError, match='project_not_found'):
        service.update(project.id, request, owner)


@pytest.mark.parametrize('aliases', [{'a': 'b', 'b': 'a'}, {'a': 'b', 'b': 'c'}, {'A': 'b', ' a ': 'c'}])
def test_ambiguous_or_chained_aliases_are_rejected(vocabulary, aliases):
    repository, owner, _, project, _ = vocabulary
    with pytest.raises((TerminologyError, ValueError)):
        ProjectTerminologyService(repository).update(project.id, TermAliasUpdateV1(
            command_id='invalid_alias', expected_version=0, aliases=aliases,
        ), owner)
    assert ProjectTerminologyService(repository).get(project.id, owner).version == 0


def test_terms_do_not_merge_user_identities_or_cross_project_facts(vocabulary):
    repository, owner, peer, project, document = vocabulary
    remember(repository, owner, document, '入口', 'V1', 'scoped_term')
    ProjectTerminologyService(repository).update(project.id, TermAliasUpdateV1(
        command_id='project_only', expected_version=0, aliases={'入口': '网关', peer.id: owner.id},
    ), owner)
    assert query(repository, owner, project, peer.id, subject_type='user').outcome == 'unknown'
    foreign = repository.save_project(project.model_copy(update={'id': 'other_project'}))
    assert query(repository, owner, foreign, '网关').outcome == 'unknown'
    assert ProjectTerminologyService(repository).get(foreign.id, owner).aliases == {}


def test_stale_project_configuration_save_preserves_confirmed_aliases(vocabulary):
    repository, owner, _, project, _ = vocabulary
    service = ProjectTerminologyService(repository)
    vocabulary = service.update(project.id, TermAliasUpdateV1(command_id='preserve_alias', expected_version=0,
                                                             aliases={'入口': '网关'}), owner)
    repository.save_project(project.model_copy(update={'goal': 'New project goal'}))
    assert service.get(project.id, owner) == vocabulary


def test_term_alias_change_invalidates_archived_sdk_fact_output(vocabulary, monkeypatch, stable_sdk_clock):
    repository, owner, _, project, document = vocabulary
    remember(repository, owner, document, '入口', 'V1', 'sdk_term')
    service = ProjectTerminologyService(repository)
    service.update(project.id, TermAliasUpdateV1(command_id='sdk_alias', expected_version=0,
                                                 aliases={'入口': '网关'}), owner)
    ensure_tool_seed_data(repository, granted_by='test')
    repository.save_agent_tool_grant(AgentToolGrant(agent_id=owner.personal_agent_id, tool_id='tool_memory_search',
                                                   granted_by=owner.id))
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'off')
    model = ScriptedModel([[function_call('memory_search', {
        'query': '网关版本', 'fact_query': {'subject_type': 'term', 'subject_id': '网关', 'predicate': 'version',
                                           'as_of': NOW.isoformat()},
    }, call_id='alias_query')], [assistant_message('Version V1 [P1]')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    answer = runtime.run_sync(content='查询网关版本', user=owner, thread_id='term_sdk_thread', history=[])
    assert len(repository.list_memory_use_receipts_for_run(answer.run_id)) == 1
    assert repository.get_sdk_session('term_sdk_thread').term_alias_version == 1
    service.update(project.id, TermAliasUpdateV1(command_id='change_sdk_alias', expected_version=1,
                                                 aliases={'入口': '其他网关'}), owner)
    next_run = repository.save_agent_run(AgentRun(thread_id='term_sdk_thread', user_id=owner.id,
        workspace_id=owner.workspace_id, project_id=project.id, input_text='Continue', status='running'))
    with pytest.raises(PermissionError, match='sdk_session_source_changed'):
        asyncio.run(AgentMeshSession('term_sdk_thread', repository, run=next_run).get_items())


def test_frozen_term_fact_selection_rechecks_alias_version_before_receipt(vocabulary):
    repository, owner, _, project, document = vocabulary
    remember(repository, owner, document, '入口', 'V1', 'frozen_term')
    terminology = ProjectTerminologyService(repository)
    terminology.update(project.id, TermAliasUpdateV1(command_id='freeze_alias', expected_version=0,
                                                       aliases={'入口': '网关'}), owner)
    run = repository.save_agent_run(AgentRun(thread_id='frozen_term_thread', user_id=owner.id,
        workspace_id=owner.workspace_id, project_id=project.id, input_text='网关版本', status='running'))
    service = MemoryContextService(repository)
    bundle = service.prepare_fact_for_run(query_text=run.input_text, run=run, user=owner,
        agent_id=owner.personal_agent_id,
        request=FactQueryV1(project_id=project.id, subject_type='term', subject_id='网关', predicate='version', as_of=NOW))
    assert bundle.fact_context.result.outcome == 'known'
    terminology.update(project.id, TermAliasUpdateV1(command_id='change_freeze_alias', expected_version=1,
                                                       aliases={'入口': '网关', 'gateway': '网关'}), owner)
    with pytest.raises(MemoryContextError, match='memory_fact_context_changed'):
        service.commit_prepared_for_run(bundle, query=run.input_text, run=run, user=owner,
                                        agent_id=owner.personal_agent_id, reason='test_term')
    assert repository.list_memory_use_receipts_for_run(run.id) == []


def test_terminology_http_api_is_scoped_and_current_permission_checked(vocabulary, monkeypatch):
    import agentmesh.routes.memory_facts as routes
    from agentmesh.app import app
    from agentmesh.routes.deps import current_user

    repository, owner, peer, project, _ = vocabulary
    monkeypatch.setattr(routes, 'store', repository)
    app.dependency_overrides[current_user] = lambda: owner
    client = TestClient(app)
    try:
        payload = {'command_id': 'http_alias', 'expected_version': 0, 'aliases': {'入口': '网关'}}
        response = client.put(f'/api/memory/facts/terminology/{project.id}', json=payload)
        assert response.status_code == 200
        assert response.json()['version'] == 1
        app.dependency_overrides[current_user] = lambda: peer
        assert client.get(f'/api/memory/facts/terminology/{project.id}').json()['aliases'] == {'入口': '网关'}
        assert client.put(f'/api/memory/facts/terminology/{project.id}', json=payload).status_code == 403
        repository.save_project(project.model_copy(update={'member_ids': [owner.id]}))
        assert client.get(f'/api/memory/facts/terminology/{project.id}').status_code == 404
    finally:
        app.dependency_overrides.pop(current_user, None)


@pytest.mark.parametrize('name', ['a::b', 'a\u200bb', 'a\x00b', 'x' * 101])
def test_unsafe_term_names_cannot_be_confirmed(vocabulary, name):
    repository, owner, _, project, _ = vocabulary
    with pytest.raises(TerminologyError, match='term_alias_mapping_invalid'):
        ProjectTerminologyService(repository).update(project.id, TermAliasUpdateV1(
            command_id='unsafe_alias', expected_version=0, aliases={name: 'canonical'},
        ), owner)


def test_maximum_alias_dictionary_has_bounded_model_diagnostics(vocabulary):
    repository, owner, _, project, _ = vocabulary
    ProjectTerminologyService(repository).update(project.id, TermAliasUpdateV1(
        command_id='large_alias', expected_version=0, aliases={f'alias_{i}': 'canonical' for i in range(200)},
    ), owner)
    run = repository.save_agent_run(AgentRun(thread_id='large_term_thread', user_id=owner.id,
        workspace_id=owner.workspace_id, project_id=project.id, input_text='canonical version', status='running'))
    bundle = MemoryContextService(repository).prepare_fact_for_run(
        FactQueryV1(project_id=project.id, subject_type='term', subject_id='canonical', predicate='version'),
        query_text=run.input_text, run=run, user=owner, agent_id=owner.personal_agent_id,
    )
    assert len(bundle.fact_context.result.term_resolution.matched_subject_ids) == 201
    assert 'alias_199' not in bundle.rendered_context
    assert '"matched_subject_count":201' in bundle.rendered_context
    assert bundle.total_chars < 2000


def test_alias_change_between_precheck_and_receipt_transaction_is_rejected(vocabulary, monkeypatch):
    repository, owner, _, project, document = vocabulary
    remember(repository, owner, document, '入口', 'V1', 'receipt_term')
    terminology = ProjectTerminologyService(repository)
    terminology.update(project.id, TermAliasUpdateV1(command_id='receipt_alias', expected_version=0,
                                                    aliases={'入口': '网关'}), owner)
    run = repository.save_agent_run(AgentRun(thread_id='receipt_term_thread', user_id=owner.id,
        workspace_id=owner.workspace_id, project_id=project.id, input_text='网关版本', status='running'))
    service = MemoryContextService(repository)
    bundle = service.prepare_fact_for_run(
        FactQueryV1(project_id=project.id, subject_type='term', subject_id='网关', predicate='version', as_of=NOW),
        query_text=run.input_text, run=run, user=owner, agent_id=owner.personal_agent_id,
    )
    original = repository.commit_memory_use_receipts

    def change_alias(**kwargs):
        terminology.update(project.id, TermAliasUpdateV1(command_id='receipt_alias_change', expected_version=1,
                                                        aliases={'入口': '网关', 'gateway': '网关'}), owner)
        return original(**kwargs)

    monkeypatch.setattr(repository, 'commit_memory_use_receipts', change_alias)
    with pytest.raises(MemoryContextError, match='memory_fact_context_changed'):
        service.commit_prepared_for_run(bundle, query=run.input_text, run=run, user=owner,
                                        agent_id=owner.personal_agent_id, reason='test_term')
    assert repository.list_memory_use_receipts_for_run(run.id) == []
