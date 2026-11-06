"""One content-type policy at ordinary, SDK, and assembled memory boundaries."""
from __future__ import annotations

import json
from contextlib import closing

import pytest

from agentmesh.market_publication_inputs import save_publication_inputs
from agentmesh.market_publishing import MarketPublishingService
from agentmesh.market_scout_materials import MarketScoutMaterials
from agentmesh.memory_context.service import MemoryContextService
from agentmesh.models import AgentMemoryBinding, BlackboardPost, DocumentRecord, MemoryItem, Source, UserMemoryItem
from agentmesh.retrieval import RetrievalProfile, RetrievalService
from agentmesh.seed import TEAM_LEAD, USER, ensure_base_workspace_data, ensure_seed_data
from agentmesh.store import SQLiteStore, store
from tests.test_chat_flow import authenticated_client


@pytest.fixture
def repository(tmp_path):
    repository = SQLiteStore(tmp_path / 'binding-types.sqlite3')
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    repository.save_user(TEAM_LEAD)
    yield repository
    repository.close()


def _memory(repository, *, kind='private', memory_type='finding', **changes):
    fields = dict(title='bindingcontentprobe', summary='bindingcontentprobe evidence. ' * 20,
                  memory_type=memory_type, workspace_id=USER.workspace_id, project_id=USER.default_project_id)
    if kind == 'private':
        return repository.add_user_memory_item(UserMemoryItem(
            **(fields | dict(user_id=USER.id, layer='mid_term', source_kind='note') | changes)))
    return repository.add_memory_item(MemoryItem(
        **(fields | dict(scope=kind, status='accepted') | changes)))


def _retrieve(repository, consumer, *, profile=None):
    if consumer == 'ordinary':
        return repository.search_for_agent('bindingcontentprobe', USER.personal_agent_id,
            workspace_id=USER.workspace_id, project_id=USER.default_project_id, user_id=USER.id)
    if consumer == 'sdk':
        return [hit.result for hit in RetrievalService(repository).retrieve(
            'bindingcontentprobe', user=USER, agent_id=USER.personal_agent_id, profile=profile).hits]
    return MemoryContextService(repository).search_results(
        'bindingcontentprobe', user=USER, agent_id=USER.personal_agent_id, memory_only=True)


@pytest.mark.parametrize('consumer', ['ordinary', 'sdk', 'context'])
@pytest.mark.parametrize('kind', ['private', 'project', 'team_accepted'])
def test_domain_type_is_filtered_before_candidates_without_collection_scans(repository, monkeypatch, consumer, kind):
    allowed = _memory(repository, kind=kind)
    for index in range(205):
        _memory(repository, kind=kind, id=f'disallowed_{index:03}', memory_type='decision',
                summary='bindingcontentprobe')
    _memory(repository, id='peer_private', user_id=TEAM_LEAD.id)
    _memory(repository, id='other_workspace', workspace_id='other_workspace')
    _memory(repository, id='other_project', project_id='other_project')
    repository.save_agent_memory_binding(AgentMemoryBinding(
        agent_id=USER.personal_agent_id, allowed_memory_types=['finding'], type_policy_version=1,
        max_results_per_query=1,
    ))
    original_list = repository._list

    def bounded_list(collection, *args, **kwargs):
        assert collection not in {'memory_items', 'user_memory_items'}
        return original_list(collection, *args, **kwargs)

    monkeypatch.setattr(repository, '_list', bounded_list)
    assert [hit.id for hit in _retrieve(repository, consumer)] == [allowed.id]


@pytest.mark.parametrize('consumer', ['ordinary', 'sdk', 'context'])
def test_domain_name_document_does_not_grant_raw_document_access(repository, consumer):
    # IDs are collection-local: a whitelist of IDs alone cannot enforce a type.
    memory = _memory(repository, id='same_record_id', memory_type='document')
    repository.add_document(DocumentRecord(
        id=memory.id, title='bindingcontentprobe', file_name='probe.txt', content_type='text/plain',
        text='bindingcontentprobe', uploaded_by=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        source=Source(title='bindingcontentprobe', source_type='document', reference='upload://probe'),
    ))
    repository.save_agent_memory_binding(AgentMemoryBinding(
        agent_id=USER.personal_agent_id, allowed_memory_types=['document'], type_policy_version=1,
    ))
    assert [(hit.result_type, hit.id) for hit in _retrieve(repository, consumer)] == [('user_memory_item', memory.id)]


@pytest.mark.parametrize('consumer', ['ordinary', 'sdk', 'context'])
@pytest.mark.parametrize('types', [['finding'], ['user_memory_item']])
def test_unversioned_restricted_policy_waits_for_explicit_confirmation(repository, consumer, types):
    _memory(repository, memory_type=types[0])
    binding = AgentMemoryBinding(agent_id=USER.personal_agent_id, allowed_memory_types=types,
                                 type_policy_version=1)
    payload = binding.model_dump(mode='json')
    payload.pop('type_policy_version', None)
    with closing(repository._connect()) as connection, connection:
        connection.execute('INSERT INTO records(collection, id, payload) VALUES (?, ?, ?)',
                           ('agent_memory_bindings', binding.id, json.dumps(payload)))
    assert _retrieve(repository, consumer) == []
    # Reading must not silently rewrite a legacy access policy.
    with closing(repository._read_connect()) as connection:
        raw = connection.execute("SELECT payload FROM records WHERE collection = 'agent_memory_bindings' AND id = ?",
                                 (binding.id,)).fetchone()['payload']
    assert 'type_policy_version' not in json.loads(raw)


def test_sdk_result_category_is_a_separate_intersection(repository):
    private = _memory(repository)
    shared = _memory(repository, kind='project')
    _memory(repository, kind='project', memory_type='decision')
    repository.save_agent_memory_binding(AgentMemoryBinding(
        agent_id=USER.personal_agent_id, allowed_memory_types=['finding'], type_policy_version=1))
    results = _retrieve(repository, 'sdk', profile=RetrievalProfile(result_types=['memory_item']))
    assert [hit.id for hit in results] == [shared.id]
    assert private.id not in [hit.id for hit in results]


def test_authorized_resave_confirms_legacy_policy_with_server_version():
    store.reset()
    ensure_seed_data(store)
    memory = _memory(store, memory_type='finding')
    binding = store.add_agent_memory_binding(AgentMemoryBinding(
        agent_id=USER.personal_agent_id, allowed_memory_types=['finding']))
    client = authenticated_client()
    response = client.get(f'/api/agents/{USER.personal_agent_id}/memory-binding')
    assert response.status_code == 200
    assert response.json()['binding']['type_policy_version'] is None
    assert _retrieve(store, 'sdk') == []
    response = client.put(f'/api/agents/{USER.personal_agent_id}/memory-binding', json={
        'agent_id': TEAM_LEAD.personal_agent_id, 'allowed_memory_types': ['finding'],
        'allowed_project_ids': [USER.default_project_id], 'type_policy_version': None,
    })
    assert response.status_code == 200
    saved = response.json()['binding']
    assert saved['type_policy_version'] == 1
    assert saved['id'] == binding.id and saved['created_at'] == binding.created_at.isoformat().replace('+00:00', 'Z')
    assert [hit.id for hit in _retrieve(store, 'ordinary')] == [memory.id]


@pytest.mark.parametrize('consumer', ['ordinary', 'sdk', 'context'])
def test_unrestricted_legacy_binding_still_retrieves_memory(repository, consumer):
    memory = _memory(repository)
    repository.save_agent_memory_binding(AgentMemoryBinding(agent_id=USER.personal_agent_id))
    assert [hit.id for hit in _retrieve(repository, consumer)] == [memory.id]


def test_content_types_restrict_semantic_candidates_before_vector_scoring(repository, monkeypatch):
    import agentmesh.embedding as embedding

    allowed = _memory(repository, title='semantically relevant', summary='no literal query match')
    excluded = [_memory(repository, id=f'vector_excluded_{index}', memory_type='decision',
                        title='different type', summary='no literal query match') for index in range(55)]
    with closing(repository._connect()) as connection, connection:
        for item in [allowed, *excluded]:
            connection.execute('INSERT INTO records_vec(collection, record_id, embedding) VALUES (?, ?, ?)',
                               ('user_memory_items', item.id, embedding.serialize_embedding([1.0, 0.0])))
            connection.execute("UPDATE vector_states SET state = 'ready' WHERE collection = 'user_memory_items' AND record_id = ?",
                               (item.id,))
    repository.save_agent_memory_binding(AgentMemoryBinding(
        agent_id=USER.personal_agent_id, allowed_memory_types=['finding'], type_policy_version=1))
    monkeypatch.setattr(embedding, 'EMBEDDING_ENABLED', True)
    monkeypatch.setattr(embedding, 'embed_text', lambda text: [1.0, 0.0])
    decoded = []
    decode = embedding.deserialize_embedding

    def counted_decode(data):
        decoded.append(data)
        return decode(data)

    monkeypatch.setattr(embedding, 'deserialize_embedding', counted_decode)
    results = repository.search_for_agent('semantic-query-only', USER.personal_agent_id,
        workspace_id=USER.workspace_id, project_id=USER.default_project_id, user_id=USER.id)
    assert [hit.id for hit in results] == [allowed.id]
    assert len(decoded) == 1


def test_content_types_restrict_short_query_like_candidates(repository):
    allowed = _memory(repository, title='预案', summary='允许的记录')
    for index in range(205):
        _memory(repository, id=f'like_excluded_{index}', title='预案', summary='其他内容', memory_type='decision')
    repository.save_agent_memory_binding(AgentMemoryBinding(
        agent_id=USER.personal_agent_id, allowed_memory_types=['finding'], type_policy_version=1))
    results = repository.search_for_agent('预案', USER.personal_agent_id, workspace_id=USER.workspace_id,
                                        project_id=USER.default_project_id, user_id=USER.id)
    assert [hit.id for hit in results] == [allowed.id]


@pytest.mark.parametrize('consumer', ['publisher', 'scout'])
@pytest.mark.parametrize('version', [1, None])
def test_market_memory_types_are_applied_before_material_candidate_budget(repository, consumer, version):
    ensure_seed_data(repository)
    repository.set_market_participation(USER.id, True)
    memory = _memory(repository, title='markettypecapacityprobe')
    for index in range(40):
        _memory(repository, id=f'market_excluded_{index}', title='markettypecapacityprobe excluded',
                memory_type='decision')
    repository.save_agent_memory_binding(AgentMemoryBinding(
        agent_id=USER.personal_agent_id, allowed_memory_types=['finding'], type_policy_version=version))
    if consumer == 'publisher':
        result = MarketPublishingService(repository).prepare(USER)
        memories = [] if result is None else result.memory
        assert [item.id for item in memories] == ([memory.id] if version == 1 else [])
    else:
        # Direct material reads and targeted matching must both honor the same policy.
        for terms in [(), ('markettypecapacityprobe',)]:
            result = MarketScoutMaterials(repository).prepare(USER, USER.default_project_id, query_terms=terms)
            assert (result is not None and 'markettypecapacityprobe' in result.capabilities) == (version == 1)


@pytest.mark.parametrize('version', [1, None])
def test_content_type_confirmation_survives_database_reopen(repository, version):
    memory = _memory(repository)
    repository.save_agent_memory_binding(AgentMemoryBinding(
        agent_id=USER.personal_agent_id, allowed_memory_types=['finding'], type_policy_version=version))
    reopened = SQLiteStore(repository.db_path)
    try:
        assert reopened.get_binding_for_agent(USER.personal_agent_id).type_policy_version == version
        for consumer in ['ordinary', 'sdk', 'context']:
            assert [hit.id for hit in _retrieve(reopened, consumer)] == ([memory.id] if version == 1 else [])
    finally:
        reopened.close()


@pytest.mark.parametrize('types,version,has_memory,withdrawn', [
    (['finding'], None, True, True), (['finding'], None, False, False),
    ([], None, True, False), (['finding'], 1, True, False),
])
def test_startup_retracts_legacy_generated_memory_publications_only(repository, types, version, has_memory, withdrawn):
    # A persisted pre-upgrade publication already has real dependency rows. It
    # must not survive a policy whose content-type meaning is still unknown.
    binding = AgentMemoryBinding(agent_id=USER.personal_agent_id, allowed_memory_types=types,
                                 type_policy_version=version)
    payload = binding.model_dump(mode='json')
    if version is None:
        payload.pop('type_policy_version')
    with closing(repository._connect()) as connection, connection:
        connection.execute('INSERT INTO records(collection, id, payload) VALUES (?, ?, ?)',
                           ('agent_memory_bindings', binding.id, json.dumps(payload)))
    memory = _memory(repository)
    post = repository.add_blackboard_post(BlackboardPost(
        id=f'bb_signal_{USER.id}', task_id=f'signal_{USER.id}', post_type='marketplace_signal',
        actor=USER.personal_agent_id, title='Persisted capability', content='Pre-upgrade shared capability',
        scope='project', permission='project_visible', status='published',
        metadata={'workspace_id': USER.workspace_id, 'project_id': USER.default_project_id,
                  'publication_hash': 'pre_upgrade_snapshot'},
    ))
    inputs = {('agent_memory_bindings', USER.personal_agent_id)}
    if has_memory:
        inputs.add(('user_memory_items', memory.id))
    with closing(repository._connect()) as connection, connection:
        save_publication_inputs(connection, post.id, frozenset(inputs))
    reopened = SQLiteStore(repository.db_path)
    try:
        current = reopened.get_blackboard_post(post.id)
        assert current.status == ('withdrawn' if withdrawn else 'published')
        assert current.content == ('' if withdrawn else post.content)
        if withdrawn:
            with closing(reopened._read_connect()) as connection:
                for table in ['records_fts', 'records_vec', 'vector_states']:
                    assert connection.execute(f"SELECT COUNT(*) FROM {table} WHERE collection = 'blackboard_posts' AND record_id = ?",
                                              (post.id,)).fetchone()[0] == 0
    finally:
        reopened.close()
