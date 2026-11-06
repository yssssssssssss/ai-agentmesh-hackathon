from __future__ import annotations

import pytest

from agentmesh.seed import ADMIN, PROJECT, TEAM_LEAD, USER
from agentmesh.store import store
from tests.test_chat_flow import authenticated_client, clear_store
from tests.test_delegated_queries import RecordingLLM


@pytest.fixture
def clients(monkeypatch):
    clear_store()
    requester = authenticated_client(TEAM_LEAD.id)
    target = authenticated_client(USER.id)
    admin = authenticated_client(ADMIN.id)
    model = RecordingLLM()
    monkeypatch.setattr('agentmesh.agents.chat_llm_client', lambda *args, **kwargs: model)
    return requester, target, admin, model


def test_api_confirmation_and_verified_adoption_use_session_actors(clients):
    from agentmesh.models import MemoryLayer, UserMemoryItem

    requester, target, admin, model = clients
    store.add_user_memory_item(UserMemoryItem(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=PROJECT.id, source_kind='note', layer=MemoryLayer.MID_TERM,
        title='降级预案', summary='按业务等级控制阈值。'))
    body = {'project_id': PROJECT.id, 'target_id': USER.id, 'question': '降级预案', 'command_id': 'api-query'}
    response = requester.post('/api/market/queries', json=body)
    assert response.status_code == 200
    query = response.json()
    assert query['status'] == 'awaiting_confirm' and not model.calls
    query_url = f"/api/market/queries/{query['id']}"
    assert admin.get(query_url).status_code == 404
    assert admin.get('/api/market/queries', params={'project_id': PROJECT.id}).json()['items'] == []
    assert all(item['id'] != query['inbox_item_id'] for item in admin.get('/api/inbox').json()['items'])
    inbox = next(item for item in target.get('/api/inbox').json()['items'] if item['id'] == query['inbox_item_id'])
    assert inbox['allowed_actions'] == ['open_delegated_query']
    assert target.patch(f"/api/inbox/{inbox['id']}", json={'status': 'resolved'}).status_code == 409
    assert requester.post(query_url + '/resolve', json={'action': 'approve', 'expected_version': query['version']}).status_code == 403
    answer_response = target.post(query_url + '/resolve', json={'action': 'approve', 'expected_version': query['version']})
    assert answer_response.status_code == 200
    answer = answer_response.json()
    assert answer['status'] == 'answered' and answer['current_available'] and len(model.calls) == 1
    adoption = {'command_id': 'api-adopt', 'expected_version': answer['version'], 'artifact_hash': answer['artifact_hash']}
    assert target.post(query_url + '/adopt', json=adoption).status_code == 403
    adopted = requester.post(query_url + '/adopt', json=adoption)
    assert adopted.status_code == 200
    assert requester.post(query_url + '/adopt', json=adoption).json() == adopted.json()
    assert len(store.contribution_points) == 1
    assert requester.post('/api/market/queries', json={**body, 'requester_id': ADMIN.id}).status_code == 422


def test_real_api_approval_with_unconfigured_model_is_blocked(clients, monkeypatch):
    from agentmesh.models import MemoryLayer, UserMemoryItem

    requester, target, _, model = clients
    monkeypatch.setattr('agentmesh.agents.chat_llm_client', lambda *args, **kwargs: None)
    store.add_user_memory_item(UserMemoryItem(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=PROJECT.id, source_kind='note', layer=MemoryLayer.MID_TERM, title='降级', summary='按等级控制。'))
    query = requester.post('/api/market/queries', json={'project_id': PROJECT.id, 'target_id': USER.id,
        'question': '降级预案', 'command_id': 'api-blocked'}).json()
    answer = target.post(f"/api/market/queries/{query['id']}/resolve", json={
        'action': 'approve', 'expected_version': query['version'],
    }).json()
    assert answer['status'] == 'blocked' and not answer['answer'] and not answer['citations']
    assert not model.calls and not store.contribution_points


def test_consent_api_is_owned_project_scoped_versioned_and_never_enables_market(clients):
    requester, target, _, _ = clients
    body = {'project_id': PROJECT.id, 'grantee_id': TEAM_LEAD.id, 'enabled': True,
            'expected_version': 0, 'command_id': 'api-consent'}
    first = target.put('/api/market/query-consents', json=body)
    assert first.status_code == 200 and first.json()['version'] == 1
    assert target.put('/api/market/query-consents', json=body).json() == first.json()
    assert requester.get('/api/market/query-consents', params={'project_id': PROJECT.id}).json()['items'] == []
    assert not store.is_market_participant(USER.id) and not store.is_market_participant(TEAM_LEAD.id)
    assert target.put('/api/market/query-consents', json={**body, 'enabled': False}).status_code == 409
    assert target.put('/api/market/query-consents', json={**body, 'grantor_id': ADMIN.id}).status_code == 422
