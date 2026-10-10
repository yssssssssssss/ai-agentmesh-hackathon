from __future__ import annotations

import pytest

from agentmesh.memory_context.service import MemoryContextService
from agentmesh.models import (
    AgentMemoryBinding,
    MemoryItem,
    MemoryLayer,
    MemorySearchScope,
    Project,
    Scope,
    TeamMembership,
    UserMemoryItem,
)
from agentmesh.seed import PROJECT, USER, ensure_base_workspace_data
from agentmesh.store import SQLiteStore


def repository_with_memories(tmp_path, count: int = 40) -> SQLiteStore:
    repository = SQLiteStore(tmp_path / 'scoped-search.sqlite3')
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    for index in range(count):
        repository.add_user_memory_item(UserMemoryItem(
            id=f'capacity_{index:04}', user_id=USER.id, workspace_id=USER.workspace_id,
            project_id=PROJECT.id, layer=MemoryLayer.MID_TERM, title='capacitymatch',
            summary='Authorized capacity fixture.', source_kind='note', memory_type='allowed',
        ))
    return repository


@pytest.mark.parametrize('scope', list(MemorySearchScope))
def test_search_never_loads_entire_collections(tmp_path, monkeypatch, scope) -> None:
    repository = repository_with_memories(tmp_path)
    original = repository._list

    def bounded_list(collection, *args, **kwargs):
        assert collection not in {'memory_items', 'user_memory_items', 'documents', 'blackboard_posts',
                                  'tasks', 'chat_threads'}
        return original(collection, *args, **kwargs)

    monkeypatch.setattr(repository, '_list', bounded_list)
    results = MemoryContextService(repository).search_results(
        'capacitymatch', user=USER, agent_id=USER.personal_agent_id, requested_scope=scope, memory_only=True,
    )
    assert len(results) == (5 if scope in {MemorySearchScope.AUTO, MemorySearchScope.PERSONAL} else 0)


def test_layers_and_binding_filter_before_candidate_limit(tmp_path, monkeypatch) -> None:
    repository = repository_with_memories(tmp_path, 1)
    for index in range(205):
        repository.add_user_memory_item(UserMemoryItem(
            id=f'excluded_{index:04}', user_id=USER.id, workspace_id=USER.workspace_id,
            project_id=PROJECT.id, layer=MemoryLayer.SHORT_TERM, title='capacitymatch',
            summary='Excluded type and layer.', source_kind='note', memory_type='disallowed',
        ))
    repository.save_agent_memory_binding(AgentMemoryBinding(
        id='capacity_binding', agent_id=USER.personal_agent_id, allowed_scopes=[Scope.PRIVATE],
        allowed_memory_types=['allowed'], type_policy_version=1, max_results_per_query=1,
    ))
    hydrated = []
    get = repository._get_in_transaction

    def measured_get(connection, collection, record_id, *args, **kwargs):
        if collection in {'memory_items', 'user_memory_items'}:
            hydrated.append(record_id)
        return get(connection, collection, record_id, *args, **kwargs)

    monkeypatch.setattr(repository, '_get_in_transaction', measured_get)
    results = MemoryContextService(repository).search_results(
        'capacitymatch', user=USER, agent_id=USER.personal_agent_id,
        allowed_layers={MemoryLayer.MID_TERM}, memory_only=True,
    )
    assert [result.id for result in results] == ['capacity_0000']
    assert hydrated == ['capacity_0000']


@pytest.mark.parametrize('change', ['disabled_actor', 'workspace_changed', 'membership_removed'])
def test_current_authority_changes_before_sql_recall_are_withheld(tmp_path, monkeypatch, change) -> None:
    repository = repository_with_memories(tmp_path)
    search = repository.search

    def revoke_then_search(*args, **kwargs):
        if change == 'disabled_actor':
            repository.save_user(USER.model_copy(update={'status': 'disabled'}))
        elif change == 'workspace_changed':
            repository.save_user(USER.model_copy(update={'workspace_id': 'foreign_workspace'}))
        else:
            repository.save_project(PROJECT.model_copy(update={'member_ids': ['another_user']}))
        return search(*args, **kwargs)

    monkeypatch.setattr(repository, 'search', revoke_then_search)
    assert MemoryContextService(repository).search_results(
        'capacitymatch', user=USER, agent_id=USER.personal_agent_id, memory_only=True,
    ) == []


def test_team_candidates_require_current_membership_before_limit(tmp_path) -> None:
    repository = repository_with_memories(tmp_path, 0)
    for index in range(205):
        repository.add_memory_item(MemoryItem(
            id=f'team_excluded_{index}', title='capacitymatch', summary='Another team.', memory_type='event',
            workspace_id=USER.workspace_id, project_id=PROJECT.id, team_id='foreign_team',
            scope=Scope.TEAM_ACCEPTED, status='accepted',
        ))
    own = repository.add_memory_item(MemoryItem(
        id='team_visible', title='capacitymatch', summary='Current team.', memory_type='event',
        workspace_id=USER.workspace_id, project_id=PROJECT.id, team_id='own_team',
        scope=Scope.TEAM_ACCEPTED, status='accepted',
    ))
    member = TeamMembership(id='capacity_team_member', team_id='own_team', user_id=USER.id)
    repository.save_team_membership(member)
    service = MemoryContextService(repository)
    assert [result.id for result in service.search_results(
        'capacitymatch', user=USER, agent_id=USER.personal_agent_id, requested_scope=MemorySearchScope.TEAM,
    )] == [own.id]
    repository.remove_team_membership(member.id)
    assert service.search_results('capacitymatch', user=USER, agent_id=USER.personal_agent_id,
                                  requested_scope=MemorySearchScope.TEAM) == []


def test_search_pool_obeys_binding_project_and_current_workspace(tmp_path) -> None:
    repository = repository_with_memories(tmp_path)
    other = repository.save_project(Project(id='pool_other', workspace_id=USER.workspace_id,
                                            name='Other', goal='Different scope'))
    repository.save_agent_memory_binding(AgentMemoryBinding(
        id='pool_binding', agent_id=USER.personal_agent_id, allowed_project_ids=[other.id],
    ))
    assert MemoryContextService(repository).search_pool(USER) == []


def test_vector_provider_runs_outside_local_recall_capacity(tmp_path, monkeypatch) -> None:
    repository = repository_with_memories(tmp_path)

    def vector_search(*args, **kwargs):
        assert repository._fts_lock.acquire(blocking=False)
        repository._fts_lock.release()
        return []

    monkeypatch.setattr(repository, '_vec_search', vector_search)
    assert len(MemoryContextService(repository).search_results(
        'capacitymatch', user=USER, agent_id=USER.personal_agent_id, memory_only=True,
    )) == 5
