from __future__ import annotations

import sqlite3

import pytest

from agentmesh.agents import PersonalAgent
from agentmesh.memory_lifecycle import MemoryForgetRequestV1, MemoryForgettingService
from agentmesh.model_registry import resolve_agent_model_id
from agentmesh.models import (
    AgentMemoryBinding,
    BlackboardPost,
    ChatThread,
    DocumentRecord,
    ModelDefinition,
    Project,
    Scope,
    Source,
    Task,
    UserMemoryItem,
    now_utc,
)
from agentmesh.seed import PROJECT, TEAM_LEAD, USER, ensure_seed_data
from agentmesh.store import SQLiteStore, store

SIGNAL = '能力：稳定性设计\n可提供：降级方法答疑\n需要：容量规划支持'


def _prepare():
    store.reset()
    ensure_seed_data(store)
    store.set_market_participation(USER.id, True)
    memory = store.add_user_memory_item(UserMemoryItem(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=PROJECT.id, layer='mid_term', title='降级经验', summary='按容量规划实施降级。', source_kind='promotion'))
    return memory


def _signals():
    return [item for item in store.blackboard_posts if item.post_type == 'marketplace_signal']


def test_market_publication_requires_current_opt_in():
    _prepare()
    store.set_market_participation(USER.id, False)
    assert PersonalAgent(store).publish_marketplace_signal(USER) is None
    assert _signals() == []


@pytest.mark.parametrize('change', ['opt_out', 'project', 'member', 'archive', 'memory_changed', 'binding'])
def test_model_wait_cannot_publish_after_current_authority_or_frozen_material_changes(change):
    memory = _prepare()

    class Client:
        def complete(self, system_prompt, user_prompt):
            if change == 'opt_out':
                store.set_market_participation(USER.id, False)
            elif change == 'project':
                store.save_project(Project(id='new-project', workspace_id=USER.workspace_id, name='New', goal='New',
                                           member_ids=[USER.id]))
                store.save_user(store.get_user(USER.id).model_copy(update={'default_project_id': 'new-project'}))
            elif change == 'member':
                store.save_project(PROJECT.model_copy(update={'member_ids': [TEAM_LEAD.id]}))
            elif change == 'archive':
                store.save_user_memory_item(memory.model_copy(update={'archived_at': now_utc()}))
            elif change == 'memory_changed':
                store.save_user_memory_item(memory.model_copy(update={'summary': 'Changed without a version bump'}))
            else:
                store.save_agent_memory_binding(AgentMemoryBinding(agent_id=USER.personal_agent_id,
                                                                  allowed_scopes=['team_accepted']))
            return SIGNAL

    assert PersonalAgent(store, llm_client=Client()).publish_marketplace_signal(USER) is None
    assert _signals() == []
    assert not [item for item in store.audit_events if item.action == 'publish_marketplace_signal']


@pytest.mark.parametrize('change', ['sensitive', 'other_project', 'archived'])
def test_unqualified_private_material_never_reaches_the_publisher_model(change):
    memory = _prepare()
    update = {'sensitivity': 'high'} if change == 'sensitive' else (
        {'archived_at': now_utc()} if change == 'archived' else {'project_id': 'other-project'})
    if change == 'other_project':
        store.save_project(Project(id='other-project', workspace_id=USER.workspace_id, name='Other', goal='Separate',
                                   member_ids=[USER.id]))
    store.save_user_memory_item(memory.model_copy(update=update))

    class Client:
        def complete(self, *args):
            pytest.fail('Unqualified private evidence must not enter a model call')

    assert PersonalAgent(store, llm_client=Client()).publish_marketplace_signal(USER) is None


def test_withdrawn_native_document_cannot_supply_publication_material():
    memory = _prepare()
    source = Source(id='native-publication-source', title='Original document', source_type='document',
                    reference='upload://publication.md', workspace_id=USER.workspace_id,
                    project_id=PROJECT.id, user_id=USER.id)
    store.save_document(DocumentRecord(id='native-publication-doc', title='Original document', file_name='publication.md',
        content_type='text/markdown', text='Original private content', source=source, workspace_id=USER.workspace_id,
        project_id=PROJECT.id, uploaded_by=USER.id, withdrawn_at=now_utc()))
    store.save_user_memory_item(memory.model_copy(update={'sources': [source]}))
    assert PersonalAgent(store).publish_marketplace_signal(USER) is None
    assert _signals() == []


def test_unsafe_model_output_is_not_published_or_replaced_by_a_template():
    _prepare()

    class Client:
        def complete(self, *args):
            return '能力：运维\n可提供：password=synthetic-private-secret\n需要：协作'

    assert PersonalAgent(store, llm_client=Client()).publish_marketplace_signal(USER) is None
    assert _signals() == []


def test_current_opt_in_is_checked_after_model_client_resolution(monkeypatch):
    import agentmesh.agents as agents_module

    _prepare()

    class Client:
        def complete(self, *args):
            pytest.fail('The opt-out must stop the first model request')

    def resolve(*args, **kwargs):
        store.set_market_participation(USER.id, False)
        return Client()

    monkeypatch.setattr(agents_module, 'chat_llm_client', resolve)
    assert PersonalAgent(store).publish_marketplace_signal(USER) is None


def test_delayed_publication_cannot_replace_a_newer_committed_signal():
    _prepare()
    assert PersonalAgent(store).publish_marketplace_signal(USER) is not None
    newer_content = SIGNAL.replace('容量规划支持', '已完成新的协作发布')

    class FastClient:
        def complete(self, *args):
            return newer_content

    class SlowClient:
        def complete(self, *args):
            assert PersonalAgent(store, llm_client=FastClient()).publish_marketplace_signal(USER) is not None
            return SIGNAL

    assert PersonalAgent(store, llm_client=SlowClient()).publish_marketplace_signal(USER) is None
    assert _signals()[0].content == newer_content
    assert len([item for item in store.audit_events if item.action == 'publish_marketplace_signal']) == 2


def test_index_failure_rolls_back_signal_and_audit_then_allows_a_clean_retry(monkeypatch):
    _prepare()
    real_sync = store._sync_fts

    def fail(*args):
        raise RuntimeError('synthetic index failure')

    monkeypatch.setattr(store, '_sync_fts', fail)
    with pytest.raises(RuntimeError, match='synthetic index failure'):
        PersonalAgent(store).publish_marketplace_signal(USER)
    assert _signals() == []
    assert not [item for item in store.audit_events if item.action == 'publish_marketplace_signal']
    monkeypatch.setattr(store, '_sync_fts', real_sync)
    assert PersonalAgent(store).publish_marketplace_signal(USER) is not None


def test_disabled_model_does_not_receive_private_publication_material():
    _prepare()
    store.save_model_definition(ModelDefinition(id=resolve_agent_model_id(store, USER), label='Disabled',
        provider='test', model_name='disabled-model', enabled=False))

    class Client:
        def complete(self, *args):
            pytest.fail('A disabled configured model must not receive material')

    assert PersonalAgent(store, llm_client=Client()).publish_marketplace_signal(USER) is None


def test_unversioned_document_material_requires_reimport_before_publication():
    memory = _prepare()
    source = Source(id='legacy-publication-source', title='Legacy document', source_type='document',
                    reference='upload://legacy.md', workspace_id=USER.workspace_id, project_id=PROJECT.id, user_id=USER.id)
    store.save_document(DocumentRecord(id='legacy-publication-doc', title='Legacy document', file_name='legacy.md',
        content_type='text/markdown', text='Current content without a frozen source version', source=source,
        workspace_id=USER.workspace_id, project_id=PROJECT.id, uploaded_by=USER.id))
    store.save_user_memory_item(memory.model_copy(update={'sources': [source]}))
    assert PersonalAgent(store).publish_marketplace_signal(USER) is None


def test_private_adopted_answer_is_not_automatic_publication_material():
    memory = _prepare()
    store.save_user_memory_item(memory.model_copy(update={'source_kind': 'delegated_answer'}))
    assert PersonalAgent(store).publish_marketplace_signal(USER) is None


@pytest.mark.parametrize('action', ['opt_out', 'forget'])
def test_opt_out_and_owned_forgetting_clear_the_automatic_public_signal(action):
    memory = _prepare()
    post = PersonalAgent(store).publish_marketplace_signal(USER)
    assert post is not None and '降级经验' in post.content
    if action == 'opt_out':
        store.set_market_participation(USER.id, False)
    else:
        MemoryForgettingService(store).forget(memory.id,
            MemoryForgetRequestV1(command_id='forget-publication-source', expected_version=memory.version), USER)
    withdrawn = store.get_blackboard_post(post.id)
    assert withdrawn.status == 'withdrawn' and withdrawn.content == ''
    with store._read_connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM records_fts WHERE collection = 'blackboard_posts' "
                                  'AND record_id = ?', (post.id,)).fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM vector_states WHERE collection = 'blackboard_posts' "
                                  'AND record_id = ?', (post.id,)).fetchone()[0] == 0


@pytest.mark.parametrize('update', [
    {'archived_at': now_utc()}, {'summary': 'Changed without a version bump'}, {'status': 'stale'},
    {'scope': Scope.PROJECT}, {'sensitivity': 'high'}, {'user_id': TEAM_LEAD.id}, {'project_id': 'other-project'},
])
def test_changing_published_memory_retracts_its_existing_automatic_signal(update):
    memory = _prepare()
    post = PersonalAgent(store).publish_marketplace_signal(USER)
    assert post is not None and '降级经验' in post.content

    store.save_user_memory_item(memory.model_copy(update=update))

    withdrawn = store.get_blackboard_post(post.id)
    assert withdrawn.status == 'withdrawn' and withdrawn.content == ''


@pytest.mark.parametrize('when', ['after_publication', 'during_model_wait'])
def test_native_document_body_changes_without_a_version_bump_invalidate_publication(when):
    memory = _prepare()
    source = Source(id='publication-version-source', title='Original document', source_type='document',
        reference='document://publication-version-doc#v1/chunk_0', user_id=USER.id,
        workspace_id=USER.workspace_id, project_id=PROJECT.id)
    document = store.save_document(DocumentRecord(id='publication-version-doc', title='Original document',
        file_name='publication.md', content_type='text/markdown', text='Original private content', source=source,
        workspace_id=USER.workspace_id, project_id=PROJECT.id, uploaded_by=USER.id))
    store.save_user_memory_item(memory.model_copy(update={'sources': [source]}))

    def change():
        store.save_document(document.model_copy(update={'text': 'Changed without increasing the version'}))

    if when == 'during_model_wait':
        class Client:
            def complete(self, *args):
                change()
                return SIGNAL

        assert PersonalAgent(store, llm_client=Client()).publish_marketplace_signal(USER) is None
        assert _signals() == []
    else:
        post = PersonalAgent(store).publish_marketplace_signal(USER)
        assert post is not None
        change()
        withdrawn = store.get_blackboard_post(post.id)
        assert withdrawn.status == 'withdrawn' and withdrawn.content == ''


def test_archiving_a_published_task_thread_retracts_the_automatic_signal():
    _prepare()
    thread = store.save_chat_thread(ChatThread(id='publication-task-thread', user_id=USER.id,
        workspace_id=USER.workspace_id, project_id=PROJECT.id, title='私有任务'))
    store.add_task(Task(title='降级部署', intent='general_chat', thread_id=thread.id))
    post = PersonalAgent(store).publish_marketplace_signal(USER)
    assert post is not None and '降级部署' in post.content

    store.save_chat_thread(thread.model_copy(update={'status': 'archived'}))

    withdrawn = store.get_blackboard_post(post.id)
    assert withdrawn.status == 'withdrawn' and withdrawn.content == ''


def test_withdrawn_publication_search_projections_stay_absent_after_database_reopen():
    memory = _prepare()
    post = PersonalAgent(store).publish_marketplace_signal(USER)
    assert post is not None
    store.save_user_memory_item(memory.model_copy(update={'archived_at': now_utc()}))
    store.close()
    reopened = SQLiteStore(store.db_path)
    try:
        assert reopened.get_blackboard_post(post.id).content == ''
        with reopened._read_connect() as connection:
            for table in ('records_fts', 'records_vec', 'vector_states'):
                assert connection.execute(f"SELECT COUNT(*) FROM {table} WHERE collection = 'blackboard_posts' "
                                          'AND record_id = ?', (post.id,)).fetchone()[0] == 0
    finally:
        reopened.close()


def test_recording_signal_readers_preserves_its_source_invalidation():
    memory = _prepare()
    post = PersonalAgent(store).publish_marketplace_signal(USER)
    assert post is not None
    store.add_blackboard_post(post.model_copy(update={'read_by_agents': [USER.personal_agent_id, 'reader-agent']}))

    store.save_user_memory_item(memory.model_copy(update={'archived_at': now_utc()}))

    withdrawn = store.get_blackboard_post(post.id)
    assert withdrawn.status == 'withdrawn' and withdrawn.content == ''


@pytest.mark.parametrize('change', [
    'user_inactive', 'user_workspace', 'user_project', 'project_inactive', 'project_member',
    'agent_offline', 'binding_insert', 'binding_update', 'model_insert',
])
def test_current_authority_changes_retract_an_existing_publication(change):
    _prepare()
    if change == 'binding_update':
        store.save_agent_memory_binding(AgentMemoryBinding(id='publication-binding', agent_id=USER.personal_agent_id))
    post = PersonalAgent(store).publish_marketplace_signal(USER)
    assert post is not None

    if change.startswith('user_'):
        update = {'status': 'inactive'} if change == 'user_inactive' else (
            {'workspace_id': 'other-workspace'} if change == 'user_workspace' else {'default_project_id': 'other-project'})
        store.save_user(store.get_user(USER.id).model_copy(update=update))
    elif change.startswith('project_'):
        update = {'status': 'inactive'} if change == 'project_inactive' else {'member_ids': [TEAM_LEAD.id]}
        store.save_project(store.get_project(PROJECT.id).model_copy(update=update))
    elif change == 'agent_offline':
        store.save_agent(store.get_agent(USER.personal_agent_id).model_copy(update={'status': 'offline'}))
    elif change.startswith('binding_'):
        store.save_agent_memory_binding(AgentMemoryBinding(id='publication-binding', agent_id=USER.personal_agent_id,
                                                          allowed_scopes=['team_accepted']))
    else:
        store.save_model_definition(ModelDefinition(id=resolve_agent_model_id(store, USER), label='Disabled',
            provider='test', model_name='disabled-model', enabled=False))

    withdrawn = store.get_blackboard_post(post.id)
    assert withdrawn.status == 'withdrawn' and withdrawn.content == ''


def test_no_op_and_unrelated_writes_preserve_the_existing_publication():
    memory = _prepare()
    skipped = store.add_user_memory_item(memory.model_copy(update={'id': 'excluded-private-memory',
                                                                  'sensitivity': 'high'}))
    post = PersonalAgent(store).publish_marketplace_signal(USER)
    assert post is not None
    store.save_user_memory_item(memory)
    store.save_user_memory_item(skipped.model_copy(update={'summary': 'Changed excluded private material'}))
    store.add_user_memory_item(memory.model_copy(update={'id': 'new-unselected-memory', 'title': '新增资料'}))
    store.save_user_memory_item(memory.model_copy(update={'id': 'peer-memory', 'user_id': TEAM_LEAD.id}))
    assert store.get_blackboard_post(post.id) == post


def test_published_dependencies_survive_reopen_and_republication_selects_fresh_material():
    memory = _prepare()
    remaining = store.add_user_memory_item(memory.model_copy(update={'id': 'remaining-material', 'title': '剩余经验'}))
    post = PersonalAgent(store).publish_marketplace_signal(USER)
    assert post is not None
    store.close()
    reopened = SQLiteStore(store.db_path)
    try:
        assert reopened.get_blackboard_post(post.id) == post
        reopened.save_user_memory_item(memory.model_copy(update={'archived_at': now_utc()}))
        assert reopened.get_blackboard_post(post.id).status == 'withdrawn'
        replacement = PersonalAgent(reopened).publish_marketplace_signal(USER)
        assert replacement is not None and '剩余经验' in replacement.content and '降级经验' not in replacement.content
        reopened.save_user_memory_item(remaining.model_copy(update={'sensitivity': 'high'}))
        assert reopened.get_blackboard_post(post.id).status == 'withdrawn'
    finally:
        reopened.close()


@pytest.mark.parametrize('operation', ['update', 'delete'])
def test_raw_source_writers_cannot_bypass_publication_invalidation(operation):
    memory = _prepare()
    post = PersonalAgent(store).publish_marketplace_signal(USER)
    assert post is not None
    with store._connect() as connection:
        if operation == 'update':
            connection.execute("UPDATE records SET payload = json_set(payload, '$.status', 'stale') "
                               "WHERE collection = 'user_memory_items' AND id = ?", (memory.id,))
        else:
            connection.execute("DELETE FROM records WHERE collection = 'user_memory_items' AND id = ?", (memory.id,))
    assert store.get_blackboard_post(post.id).status == 'withdrawn'


def test_source_write_and_publication_retraction_roll_back_together_on_index_failure():
    memory = _prepare()
    post = PersonalAgent(store).publish_marketplace_signal(USER)
    assert post is not None
    with store._connect() as connection:
        connection.execute("""CREATE TRIGGER reject_publication_index_delete BEFORE DELETE ON vector_states
            WHEN OLD.collection = 'blackboard_posts'
            BEGIN SELECT RAISE(ABORT, 'synthetic_publication_index_failure'); END""")
    try:
        with pytest.raises(sqlite3.IntegrityError, match='synthetic_publication_index_failure'):
            store.save_user_memory_item(memory.model_copy(update={'archived_at': now_utc()}))
        assert store.get_user_memory_item(memory.id).archived_at is None
        assert store.get_blackboard_post(post.id) == post
    finally:
        with store._connect() as connection:
            connection.execute('DROP TRIGGER reject_publication_index_delete')
    store.save_user_memory_item(memory.model_copy(update={'archived_at': now_utc()}))
    assert store.get_blackboard_post(post.id).status == 'withdrawn'


def test_unproven_legacy_generated_signal_is_withdrawn_on_reopen_without_changing_manual_posts():
    _prepare()
    legacy = store.add_blackboard_post(BlackboardPost(id=f'bb_signal_{USER.id}', task_id=f'signal_{USER.id}',
        post_type='marketplace_signal', actor=USER.personal_agent_id, title='旧自动信号', content=SIGNAL,
        scope='project', permission='project_visible',
        metadata={'workspace_id': USER.workspace_id, 'project_id': PROJECT.id}))
    manual = store.add_blackboard_post(legacy.model_copy(update={'id': 'manual-marketplace-post', 'title': '人工信号'}))
    store.close()
    reopened = SQLiteStore(store.db_path)
    try:
        withdrawn = reopened.get_blackboard_post(legacy.id)
        assert withdrawn.status == 'withdrawn' and withdrawn.content == ''
        assert reopened.get_blackboard_post(manual.id) == manual
    finally:
        reopened.close()


def test_dependency_write_failure_cannot_commit_an_untracked_publication():
    _prepare()
    with store._connect() as connection:
        connection.execute("""CREATE TRIGGER reject_publication_inputs BEFORE INSERT ON market_publication_inputs
            BEGIN SELECT RAISE(ABORT, 'synthetic_publication_input_failure'); END""")
    try:
        with pytest.raises(sqlite3.IntegrityError, match='synthetic_publication_input_failure'):
            PersonalAgent(store).publish_marketplace_signal(USER)
        assert _signals() == []
        assert not [item for item in store.audit_events if item.action == 'publish_marketplace_signal']
    finally:
        with store._connect() as connection:
            connection.execute('DROP TRIGGER reject_publication_inputs')
    assert PersonalAgent(store).publish_marketplace_signal(USER) is not None


def test_retraction_erases_private_dependencies_and_fences_late_embedding_completion(monkeypatch):
    from agentmesh import embedding

    memory = _prepare()
    post = PersonalAgent(store).publish_marketplace_signal(USER)
    assert post is not None
    assert set(post.metadata) == {'workspace_id', 'project_id', 'publication_hash'}
    assert memory.id not in post.model_dump_json()
    with store._connect() as connection:
        work = store.vector_index.prepare(connection, 'blackboard_posts', post.id, f'{post.title} {post.content}')
    assert work is not None

    store.save_user_memory_item(memory.model_copy(update={'archived_at': now_utc()}))
    monkeypatch.setattr(embedding, 'embed_text', lambda _: [0.1, 0.2, 0.3])
    store.vector_index.process(work)

    with store._read_connect() as connection:
        assert connection.execute('SELECT COUNT(*) FROM market_publication_inputs WHERE post_id = ?',
                                  (post.id,)).fetchone()[0] == 0
        for table in ('records_fts', 'records_vec', 'vector_states'):
            assert connection.execute(f"SELECT COUNT(*) FROM {table} WHERE collection = 'blackboard_posts' "
                                      'AND record_id = ?', (post.id,)).fetchone()[0] == 0
