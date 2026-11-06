"""Memory binding API authority and identity guarantees."""
from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Barrier, Event

import pytest

from agentmesh.agents import PersonalAgent
from agentmesh.app import app
from agentmesh.models import AgentMemoryBinding, MemoryItem, PermissionPolicyRule, Project, Scope, UserMemoryItem
from agentmesh.permissions import ACTION_MANAGE_PUBLIC_AGENT
from agentmesh.routes.deps import current_user
from agentmesh.seed import ADMIN, AGENTS, TEAM_LEAD, USER, ensure_seed_data
from agentmesh.store import MemoryContextConflict, store
from tests.test_chat_flow import authenticated_client


@pytest.fixture(autouse=True)
def binding_setup():
    store.reset()
    ensure_seed_data(store)


def test_binding_request_cannot_overwrite_another_agents_binding():
    victim = store.add_agent_memory_binding(AgentMemoryBinding(
        id='other-agent-binding', agent_id=TEAM_LEAD.personal_agent_id,
        allowed_scopes=[Scope.TEAM_ACCEPTED], max_results_per_query=2,
    ))
    client = authenticated_client()
    response = client.put(f'/api/agents/{USER.personal_agent_id}/memory-binding', json={
        'id': victim.id, 'agent_id': TEAM_LEAD.personal_agent_id,
        'allowed_scopes': ['private'], 'max_results_per_query': 3,
    })
    assert response.status_code == 200
    assert response.json()['binding']['id'] != victim.id
    assert response.json()['binding']['agent_id'] == USER.personal_agent_id
    other_client = authenticated_client(TEAM_LEAD.id)
    assert other_client.get(f'/api/agents/{TEAM_LEAD.personal_agent_id}/memory-binding').json()['binding'] == (
        victim.model_dump(mode='json'))


@pytest.mark.parametrize('agent_id,expected_status', [(TEAM_LEAD.personal_agent_id, 403), ('missing-agent', 404)])
def test_binding_read_requires_authority_over_a_current_agent(agent_id, expected_status):
    store.add_agent_memory_binding(AgentMemoryBinding(
        agent_id=TEAM_LEAD.personal_agent_id, allowed_project_ids=['private-project-id'],
    ))
    response = authenticated_client().get(f'/api/agents/{agent_id}/memory-binding')
    assert response.status_code == expected_status
    assert 'private-project-id' not in response.text


@pytest.mark.parametrize('method', ['put', 'delete'])
def test_binding_write_rechecks_actor_after_authentication(method, monkeypatch):
    original = store.add_agent_memory_binding(AgentMemoryBinding(agent_id=USER.personal_agent_id))
    client = authenticated_client()
    # Authentication supplies an earlier snapshot; configuration must use current authority.
    monkeypatch.setitem(app.dependency_overrides, current_user, lambda: USER)
    store.save_user(USER.model_copy(update={'status': 'disabled'}))
    arguments = {'json': {'agent_id': USER.personal_agent_id, 'allowed_scopes': ['team_accepted']}} if method == 'put' else {}
    response = client.request(method, f'/api/agents/{USER.personal_agent_id}/memory-binding', **arguments)
    assert response.status_code == 403
    assert store.get_binding_for_agent(USER.personal_agent_id) == original


@pytest.mark.parametrize('kind', ['missing', 'foreign', 'nonmember', 'archived'])
def test_binding_cannot_select_an_unavailable_project(kind):
    project_id = 'binding-test-project'
    if kind != 'missing':
        store.save_project(Project(
            id=project_id, workspace_id='another-workspace' if kind == 'foreign' else USER.workspace_id,
            name='Separate project', goal='Separate materials',
            member_ids=[TEAM_LEAD.id] if kind == 'nonmember' else [USER.id],
            status='archived' if kind == 'archived' else 'active',
        ))
    response = authenticated_client().put(f'/api/agents/{USER.personal_agent_id}/memory-binding', json={
        'agent_id': USER.personal_agent_id, 'allowed_project_ids': [project_id],
    })
    assert response.status_code == 404
    assert store.get_binding_for_agent(USER.personal_agent_id) is None


@pytest.mark.parametrize('configuration', [
    {'max_results_per_query': 0}, {'max_results_per_query': 101}, {'allowed_scopes': []},
    {'allowed_memory_types': ['x' * 81]}, {'allowed_memory_types': ['memory_item'] * 33},
    {'allowed_project_ids': ['x' * 121]}, {'allowed_project_ids': ['project'] * 101},
    {'type_policy_version': 2},
])
def test_binding_configuration_is_bounded(configuration):
    response = authenticated_client().put(f'/api/agents/{USER.personal_agent_id}/memory-binding', json={
        'agent_id': USER.personal_agent_id, **configuration,
    })
    assert response.status_code == 422
    assert store.get_binding_for_agent(USER.personal_agent_id) is None


def test_duplicate_bindings_do_not_silently_select_a_more_permissive_binding():
    store.add_agent_memory_binding(AgentMemoryBinding(agent_id=USER.personal_agent_id))
    store.add_agent_memory_binding(AgentMemoryBinding(agent_id=USER.personal_agent_id,
                                                    allowed_scopes=[Scope.TEAM_ACCEPTED]))
    with pytest.raises(MemoryContextConflict, match='memory_binding_integrity_failed'):
        store.search_for_agent('anything', USER.personal_agent_id, workspace_id=USER.workspace_id,
                               project_id=USER.default_project_id, user_id=USER.id)


@pytest.mark.parametrize('method', ['get', 'put', 'delete'])
def test_duplicate_binding_configuration_is_rejected_without_modifying_it(method):
    for scopes in [[Scope.PRIVATE], [Scope.TEAM_ACCEPTED]]:
        store.add_agent_memory_binding(AgentMemoryBinding(agent_id=USER.personal_agent_id, allowed_scopes=scopes))
    before = store.agent_memory_bindings
    arguments = {'json': {'agent_id': USER.personal_agent_id}} if method == 'put' else {}
    response = authenticated_client().request(method, f'/api/agents/{USER.personal_agent_id}/memory-binding', **arguments)
    assert response.status_code == 409
    assert store.agent_memory_bindings == before


def test_simultaneous_binding_creation_keeps_one_server_identity(monkeypatch):
    client = authenticated_client()
    monkeypatch.setitem(app.dependency_overrides, current_user, lambda: USER)
    start = Barrier(2)

    def configure(scope):
        start.wait(timeout=5)
        return client.put(f'/api/agents/{USER.personal_agent_id}/memory-binding', json={
            'id': f'caller-{scope}', 'agent_id': 'ignored-agent', 'allowed_scopes': [scope],
            'created_at': '2000-01-01T00:00:00Z', 'updated_at': '2000-01-01T00:00:00Z',
        })

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(configure, ['private', 'team_accepted']))
    assert [result.status_code for result in results] == [200, 200]
    bindings = [result.json()['binding'] for result in results]
    assert bindings[0]['id'] == bindings[1]['id']
    assert bindings[0]['created_at'] == bindings[1]['created_at']
    assert not bindings[0]['created_at'].startswith('2000-')
    assert len(store.agent_memory_bindings) == 1
    assert client.get(f'/api/agents/{USER.personal_agent_id}/memory-binding').json()['binding']['id'] == bindings[0]['id']


@pytest.mark.parametrize('method', ['put', 'delete'])
@pytest.mark.parametrize('change', ['disabled_user', 'agent_owner', 'agent_workspace', 'public_policy'])
def test_binding_write_rechecks_authority_after_waiting_for_the_database_writer(method, change, monkeypatch):
    user = TEAM_LEAD if change == 'public_policy' else USER
    agent_id = 'agent_research' if change == 'public_policy' else USER.personal_agent_id
    if change == 'public_policy':
        store.save_agent(next(agent for agent in AGENTS if agent.id == agent_id))
    original = store.add_agent_memory_binding(AgentMemoryBinding(agent_id=agent_id))
    client = authenticated_client(user.id)
    monkeypatch.setitem(app.dependency_overrides, current_user, lambda: user)
    agent = store.get_agent(agent_id)
    if change == 'disabled_user':
        collection, changed, expected_status = 'users', user.model_copy(update={'status': 'disabled'}), 403
    elif change == 'agent_owner':
        collection, changed, expected_status = 'agents', agent.model_copy(update={'owner_user_id': TEAM_LEAD.id}), 403
    elif change == 'agent_workspace':
        collection, changed, expected_status = 'agents', agent.model_copy(update={'workspace_id': 'other-workspace'}), 404
    else:
        collection, changed, expected_status = 'permission_policy_rules', PermissionPolicyRule(
            role='team_lead', action=ACTION_MANAGE_PUBLIC_AGENT, effect='deny'), 403
    entered = Event()
    connect = store._connect

    class WaitingConnection:
        def __init__(self):
            self.connection = connect()

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *arguments):
            return self.connection.__exit__(*arguments)

        def execute(self, sql, *arguments):
            if sql == 'BEGIN IMMEDIATE':
                entered.set()
            return self.connection.execute(sql, *arguments)

    with closing(connect()) as held, held:
        held.execute('BEGIN IMMEDIATE')
        monkeypatch.setattr(store, '_connect', WaitingConnection)
        arguments = {'json': {'agent_id': agent_id, 'allowed_scopes': ['team_accepted']}} if method == 'put' else {}
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(client.request, method, f'/api/agents/{agent_id}/memory-binding', **arguments)
            try:
                assert entered.wait(timeout=5)
                store._upsert_plain_record(held, collection, changed)
            finally:
                held.commit()
            response = pending.result(timeout=5)
    assert response.status_code == expected_status
    assert store.get_binding_for_agent(agent_id) == original


@pytest.mark.parametrize('method', ['get', 'put', 'delete'])
def test_even_an_admin_cannot_access_another_workspaces_agent_binding(method):
    agent = store.get_agent(USER.personal_agent_id)
    store.save_agent(agent.model_copy(update={'workspace_id': 'foreign-workspace'}))
    original = store.add_agent_memory_binding(AgentMemoryBinding(agent_id=agent.id,
                                                               allowed_project_ids=['private-project-identity']))
    arguments = {'json': {'agent_id': agent.id}} if method == 'put' else {}
    response = authenticated_client(ADMIN.id).request(method, f'/api/agents/{agent.id}/memory-binding', **arguments)
    assert response.status_code == 404
    assert 'private-project-identity' not in response.text
    assert store.get_binding_for_agent(agent.id) == original


def test_public_agent_binding_follows_current_management_permission():
    agent = next(agent for agent in AGENTS if agent.id == 'agent_research')
    store.save_agent(agent)
    client = authenticated_client(TEAM_LEAD.id)
    response = client.put(f'/api/agents/{agent.id}/memory-binding', json={
        'agent_id': agent.id, 'allowed_project_ids': [USER.default_project_id], 'allowed_scopes': ['project'],
    })
    assert response.status_code == 200
    assert client.get(f'/api/agents/{agent.id}/memory-binding').json()['binding'] == response.json()['binding']
    assert client.delete(f'/api/agents/{agent.id}/memory-binding').json() == {'status': 'deleted'}
    assert client.delete(f'/api/agents/{agent.id}/memory-binding').json() == {'status': 'no_binding'}


@pytest.mark.parametrize('method', ['get', 'put', 'delete'])
def test_binding_payload_identity_must_match_the_stored_identity(method):
    original = store.add_agent_memory_binding(AgentMemoryBinding(agent_id=USER.personal_agent_id))
    with closing(store._connect()) as connection, connection:
        connection.execute("UPDATE records SET payload = ? WHERE collection = 'agent_memory_bindings' AND id = ?",
                           (original.model_copy(update={'id': 'mismatched-identity'}).model_dump_json(), original.id))
    arguments = {'json': {'agent_id': USER.personal_agent_id}} if method == 'put' else {}
    response = authenticated_client().request(method, f'/api/agents/{USER.personal_agent_id}/memory-binding', **arguments)
    assert response.status_code == 409
    with pytest.raises(MemoryContextConflict, match='memory_binding_integrity_failed'):
        store.get_binding_for_agent(USER.personal_agent_id)


def _publish_owned_material():
    store.set_market_participation(USER.id, True)
    store.add_user_memory_item(UserMemoryItem(
        user_id=USER.id, workspace_id=USER.workspace_id, project_id=USER.default_project_id,
        layer='mid_term', title='容量规划', summary='按容量实施降级。', source_kind='promotion',
    ))
    post = PersonalAgent(store).publish_marketplace_signal(USER)
    assert post is not None
    return post


def test_binding_api_change_withdraws_the_previous_generated_publication():
    client = authenticated_client()
    assert client.get(f'/api/agents/{USER.personal_agent_id}/memory-binding').json() == {'binding': None}
    post = _publish_owned_material()
    assert client.get(f'/api/agents/{USER.personal_agent_id}/memory-binding').status_code == 200
    assert store.get_blackboard_post(post.id).status == 'published'
    response = client.put(f'/api/agents/{USER.personal_agent_id}/memory-binding', json={
        'agent_id': USER.personal_agent_id, 'allowed_scopes': ['team_accepted'],
    })
    assert response.status_code == 200
    withdrawn = store.get_blackboard_post(post.id)
    assert withdrawn.status == 'withdrawn'
    assert withdrawn.content == ''
    assert withdrawn.title == '协作信号已撤回'


def test_publication_cleanup_failure_rolls_back_binding_api_creation():
    client = authenticated_client()
    assert client.get(f'/api/agents/{USER.personal_agent_id}/memory-binding').json() == {'binding': None}
    post = _publish_owned_material()
    with closing(store._connect()) as connection, connection:
        connection.execute("""CREATE TRIGGER binding_test_cleanup_failure BEFORE DELETE ON vector_states
            WHEN OLD.collection = 'blackboard_posts'
            BEGIN SELECT RAISE(ABORT, 'binding_cleanup_failed'); END""")
    try:
        with pytest.raises(sqlite3.IntegrityError, match='binding_cleanup_failed'):
            client.put(f'/api/agents/{USER.personal_agent_id}/memory-binding', json={
                'agent_id': USER.personal_agent_id, 'allowed_scopes': ['team_accepted'],
            })
        assert client.get(f'/api/agents/{USER.personal_agent_id}/memory-binding').json() == {'binding': None}
        assert store.get_blackboard_post(post.id) == post
    finally:
        with closing(store._connect()) as connection, connection:
            connection.execute('DROP TRIGGER binding_test_cleanup_failure')


def test_binding_restricts_search_without_replacing_the_requested_project():
    project = store.save_project(Project(id='second-binding-project', workspace_id=USER.workspace_id,
                                        name='Second project', goal='Separate memory', member_ids=[USER.id]))
    memory = store.add_memory_item(MemoryItem(
        title='部署规范', summary='另一个项目的部署规范', memory_type='standard', scope=Scope.PROJECT,
        status='accepted', workspace_id=USER.workspace_id, project_id=project.id,
    ))
    store.add_agent_memory_binding(AgentMemoryBinding(agent_id=USER.personal_agent_id,
                                                    allowed_scopes=[Scope.PROJECT], allowed_project_ids=[project.id]))
    assert store.search_for_agent('部署规范', USER.personal_agent_id, workspace_id=USER.workspace_id,
                                  project_id=USER.default_project_id, user_id=USER.id) == []
    results = store.search_for_agent('部署规范', USER.personal_agent_id, workspace_id=USER.workspace_id,
                                    project_id=project.id, user_id=USER.id)
    assert [result.id for result in results] == [memory.id]


def test_binding_content_types_are_applied_before_the_result_budget():
    for _ in range(5):
        store.add_user_memory_item(UserMemoryItem(
            user_id=USER.id, workspace_id=USER.workspace_id, project_id=USER.default_project_id,
            layer='mid_term', title='bindingtypeprobe', summary='bindingtypeprobe ' * 8, source_kind='promotion',
        ))
    allowed = store.add_memory_item(MemoryItem(
        title='bindingtypeprobe 团队规范', summary='明确接受的规范。' * 200, memory_type='standard',
        scope=Scope.TEAM_ACCEPTED, status='accepted', workspace_id=USER.workspace_id, project_id=USER.default_project_id,
    ))
    store.add_agent_memory_binding(AgentMemoryBinding(agent_id=USER.personal_agent_id,
                                                    allowed_memory_types=['standard'], type_policy_version=1,
                                                    max_results_per_query=1))
    results = store.search_for_agent('bindingtypeprobe', USER.personal_agent_id, workspace_id=USER.workspace_id,
                                    project_id=USER.default_project_id, user_id=USER.id)
    assert [result.id for result in results] == [allowed.id]
