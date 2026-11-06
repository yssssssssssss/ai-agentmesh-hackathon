from __future__ import annotations

import pytest

from agentmesh.market_read import read_market
from agentmesh.market_scout import MarketScoutReceiptV1, MarketScoutRepository
from agentmesh.models import AuditEvent, BlackboardPost, ConsentGrant, Project, Scope, User, Workspace, now_utc
from agentmesh.seed import PROJECT, TEAM_LEAD, USER
from agentmesh.store import store
from tests.test_chat_flow import authenticated_client, clear_store


@pytest.fixture
def scoped_market():
    clear_store()
    client = authenticated_client()
    store.save_workspace(Workspace(id='foreign-ws', name='Foreign workspace', description='Separate workspace'))
    foreign = store.save_user(User(id='foreign-user', name='Foreign private colleague', role='user',
        workspace_id='foreign-ws', default_project_id='foreign-project', personal_agent_id='foreign-agent'))
    peer = store.save_user(foreign.model_copy(update={'id': 'foreign-peer', 'name': 'Foreign private peer'}))
    store.save_project(Project(id='foreign-project', workspace_id='foreign-ws', name='Foreign project', goal='Keep private',
                               member_ids=[foreign.id, peer.id]))
    store.save_project(Project(id='other-project', workspace_id=USER.workspace_id, name='Other private project',
                               goal='Separate', member_ids=[TEAM_LEAD.id]))
    for owner, project_id, topic in ((foreign, 'foreign-project', 'foreign-secret-topic'),
                                     (TEAM_LEAD, 'other-project', 'other-project-secret-topic')):
        store.set_market_participation(owner.id, True)
        store.add_blackboard_post(BlackboardPost(id=f'bb_signal_{owner.id}', task_id=f'signal_{owner.id}',
            actor=owner.personal_agent_id, post_type='marketplace_signal', title='Restricted signal',
            content=f'能力：设计\n可提供：经验\n需要：{topic}', scope=Scope.PROJECT, permission='project_visible',
            metadata={'workspace_id': owner.workspace_id, 'project_id': project_id}))
        store.add_audit_event(AuditEvent(actor=owner.id, action='marketplace_match', target_type='user',
            target_id=peer.id if owner.id == foreign.id else USER.id, workspace_id=owner.workspace_id,
            project_id=project_id, metadata={'helper': owner.id, 'status': 'answered', 'need': topic}))
    store.add_consent_grant(ConsentGrant(grantor_id=foreign.id, grantee_id=peer.id, workspace_id=foreign.workspace_id,
                                        project_id='foreign-project'))
    return client, foreign


@pytest.mark.parametrize('route', ['status', 'board', 'activity', 'me'])
def test_market_reads_do_not_expose_other_workspaces_or_project_material(scoped_market, route):
    client, foreign = scoped_market
    response = client.get(f'/api/market/{route}')
    assert response.status_code == 200
    body = response.json()
    assert 'foreign-secret-topic' not in response.text
    assert 'other-project-secret-topic' not in response.text
    assert 'Foreign private' not in response.text and foreign.id not in response.text
    if route in {'status', 'board'}:
        assert body['counts']['signals'] == body['counts']['matches'] == body['counts']['consent_grants'] == 0
    if route == 'me':
        assert body['presence']['received_count'] == body['presence']['given_count'] == 0


def test_missing_project_proof_cannot_move_legacy_signal_with_owners_default_project():
    clear_store()
    client = authenticated_client()
    store.add_blackboard_post(BlackboardPost(id='unscoped-legacy-signal', task_id=f'signal_{TEAM_LEAD.id}',
        post_type='marketplace_signal', actor=TEAM_LEAD.personal_agent_id, title='Legacy',
        content='需要：legacy-unscoped-private-topic', scope='project', permission='project_visible'))
    response = client.get('/api/market/board')
    assert response.status_code == 200 and response.json()['signals'] == []
    assert 'legacy-unscoped-private-topic' not in client.get('/api/market/activity').text


def test_removed_project_member_cannot_read_the_old_market_view():
    clear_store()
    client = authenticated_client()
    store.save_project(PROJECT.model_copy(update={'member_ids': [TEAM_LEAD.id]}))
    for route in ('status', 'board', 'me', 'activity'):
        assert client.get(f'/api/market/{route}').status_code == 404


def test_read_uses_current_default_project_instead_of_the_stale_dependency_user():
    clear_store()
    authenticated_client()
    current = store.get_user(USER.id)
    store.save_project(Project(id='new-default', workspace_id=USER.workspace_id, name='New current project',
                               goal='Use current selection', member_ids=[USER.id]))
    store.save_user(current.model_copy(update={'default_project_id': 'new-default'}))
    assert read_market(current, store).project.id == 'new-default'


def test_market_projection_is_bounded_and_counts_all_authorized_records(monkeypatch):
    clear_store()
    client = authenticated_client()
    member_ids = [USER.id, TEAM_LEAD.id]
    for index in range(205):
        peer = store.save_user(USER.model_copy(update={'id': f'scoped-peer-{index}', 'name': f'Peer {index}'}))
        member_ids.append(peer.id)
        store.set_market_participation(peer.id, True)
        store.add_blackboard_post(BlackboardPost(id=f'bounded-signal-{index}', task_id=f'signal_{peer.id}',
            post_type='marketplace_signal', actor=peer.personal_agent_id, title='Public signal', content='需要：公开问题',
            scope='project', permission='project_visible',
            metadata={'workspace_id': USER.workspace_id, 'project_id': PROJECT.id}))
        store.add_audit_event(AuditEvent(actor=peer.id, action='marketplace_match', target_type='user', target_id=USER.id,
            workspace_id=USER.workspace_id, project_id=PROJECT.id, metadata={'helper': peer.id, 'status': 'blocked'}))
    store.save_project(PROJECT.model_copy(update={'member_ids': member_ids}))

    def no_collection_scan(*args, **kwargs):
        pytest.fail('Market reads must filter in SQL instead of hydrating collections')

    monkeypatch.setattr(store, '_list', no_collection_scan)
    data = read_market(USER, store)
    assert data.counts['participants'] == data.counts['signals'] == data.counts['matches'] == 205
    assert len(data.users) == len(data.signals) == len(data.matches) == 200
    assert len(data.participants) <= 200 and USER.id in data.users
    assert data.received_count == 205 and data.given_count == 0
    assert len(client.get('/api/market/board').json()['matches']) == 30
    assert len(client.get('/api/market/activity').json()['items']) == 40


def test_public_worker_details_exclude_other_users_and_projects(scoped_market):
    client, foreign = scoped_market
    for helper, project_id, code in ((foreign, 'foreign-project', 'foreign-error'),
        (TEAM_LEAD, PROJECT.id, 'peer-private-error'), (USER, 'other-project', 'other-project-error')):
        receipt = MarketScoutReceiptV1(id=f'private-receipt-{code}', helper_id=helper.id,
            workspace_id=helper.workspace_id, project_id=project_id, post_id='private-post', fingerprint='a' * 64,
            status='blocked', last_error_code=code, updated_at=now_utc())
        with store._connect() as connection:
            MarketScoutRepository._save(connection, receipt)
    for route in ('status', 'board'):
        response = client.get(f'/api/market/{route}')
        assert response.status_code == 200
        assert response.json()['scout_worker']['queue'] == {'counts': {}, 'last_error_code': None}
        assert 'private-error' not in response.text and 'foreign-error' not in response.text
        assert 'last_triggered' not in response.json()['scout_worker']
        assert 'last_published' not in response.json()['publish_worker']


def test_legacy_match_body_is_not_read_as_a_private_answer():
    clear_store()
    client = authenticated_client()
    store.add_audit_event(AuditEvent(actor=TEAM_LEAD.id, action='marketplace_match', target_type='user', target_id=USER.id,
        workspace_id=USER.workspace_id, project_id=PROJECT.id, metadata={'helper': TEAM_LEAD.id, 'status': 'answered'}))
    store.add_blackboard_post(BlackboardPost(id=f'bb_match_{TEAM_LEAD.id}_{USER.id}', task_id='market_activity',
        post_type='marketplace_match', actor=TEAM_LEAD.id, title='Historical status',
        content='raw-private-answer-must-stay-hidden', scope='project', permission='project_visible'))
    response = client.get('/api/market/me')
    assert response.status_code == 200 and len(response.json()['timeline']) == 1
    assert 'raw-private-answer' not in response.text
    assert response.json()['timeline'][0]['action_ref'] == ''


def test_board_orders_signals_by_instant_instead_of_timestamp_text():
    clear_store()
    client = authenticated_client()
    for identifier, at in [('older', '2026-10-06T20:00:00+12:00'), ('newer', '2026-10-06T10:00:00+00:00')]:
        store.add_blackboard_post(BlackboardPost(id=identifier, task_id=f'signal_{TEAM_LEAD.id}',
            post_type='marketplace_signal', actor=TEAM_LEAD.id, title='Public signal', content=f'需要：{identifier}',
            created_at=at, scope='project', permission='project_visible',
            metadata={'workspace_id': USER.workspace_id, 'project_id': PROJECT.id}))
    assert [item['need'] for item in client.get('/api/market/board').json()['signals']] == ['newer', 'older']


def test_repeated_matches_have_distinct_activity_ids():
    clear_store()
    client = authenticated_client()
    for status in ('awaiting_confirm', 'blocked'):
        store.add_audit_event(AuditEvent(actor=TEAM_LEAD.id, action='marketplace_match', target_type='user',
            target_id=USER.id, workspace_id=USER.workspace_id, project_id=PROJECT.id,
            metadata={'helper': TEAM_LEAD.id, 'status': status}))
    items = client.get('/api/market/activity').json()['items']
    assert len(items) == len({item['id'] for item in items}) == 2


@pytest.mark.parametrize('route', ['status', 'board', 'me', 'activity'])
def test_explicit_market_project_is_the_requested_authorized_scope(route):
    clear_store()
    client = authenticated_client()
    store.save_project(Project(id='selected-project', workspace_id=USER.workspace_id, name='Selected project',
                               goal='Read selected scope', member_ids=[USER.id, TEAM_LEAD.id]))
    store.add_blackboard_post(BlackboardPost(id='selected-signal', task_id=f'signal_{TEAM_LEAD.id}',
        post_type='marketplace_signal', actor=TEAM_LEAD.id, title='Scoped signal', content='需要：selected-scope-topic',
        scope='project', permission='project_visible',
        metadata={'workspace_id': USER.workspace_id, 'project_id': 'selected-project'}))
    store.add_audit_event(AuditEvent(actor=TEAM_LEAD.id, action='marketplace_match', target_type='user', target_id=USER.id,
        workspace_id=USER.workspace_id, project_id='selected-project',
        metadata={'helper': TEAM_LEAD.id, 'status': 'blocked', 'need': 'selected-scope-topic'}))
    response = client.get(f'/api/market/{route}', params={'project_id': 'selected-project'})
    assert response.status_code == 200
    if route == 'status':
        assert response.json()['counts']['signals'] == response.json()['counts']['matches'] == 1
    else:
        assert 'selected-scope-topic' in response.text
    assert 'selected-scope-topic' not in client.get(f'/api/market/{route}').text


def test_explicit_market_project_cannot_bypass_current_membership():
    clear_store()
    client = authenticated_client()
    store.save_project(Project(id='no-member-project', workspace_id=USER.workspace_id, name='Other project',
                               goal='Do not grant access', member_ids=[TEAM_LEAD.id]))
    for route in ('status', 'board', 'me', 'activity'):
        assert client.get(f'/api/market/{route}', params={'project_id': 'no-member-project'}).status_code == 404
