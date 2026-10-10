from __future__ import annotations

import json

import pytest
from agents.testing import ScriptedModel, assistant_message, function_call

from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.models import AgentRunStatus, AgentToolGrant, ChatMessage
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.store import SQLiteStore
from agentmesh.tools import ensure_tool_seed_data


@pytest.fixture
def paused_session(tmp_path, monkeypatch):
    repository = SQLiteStore(tmp_path / 'session-checkpoint.sqlite3')
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    ensure_tool_seed_data(repository, granted_by='system')
    repository.save_agent_tool_grant(AgentToolGrant(id='session_checkpoint_web', agent_id=USER.personal_agent_id,
                                                   tool_id='tool_web_research', granted_by='test'))
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'off')
    model = ScriptedModel([[function_call('web_research', {'query': 'Checkpoint'}, call_id='checkpoint_call')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    answer = runtime.run_sync(content='Research with an approval', user=USER, thread_id='thread_checkpoint', history=[])
    assert answer.waiting_approval
    run = repository.get_agent_run(answer.run_id)
    yield repository, run
    repository.close()


def test_direct_approval_freezes_session_version_and_hash_even_with_memory_off(paused_session):
    repository, run = paused_session
    checkpoint = run.paused_state['agentmesh_session_checkpoint']
    assert checkpoint['version'] == repository.get_sdk_session(run.thread_id).version
    assert checkpoint['writer_run_id'] == run.id
    assert len(checkpoint['content_hash']) == 64
    assert 'Research with an approval' not in json.dumps(checkpoint)


@pytest.mark.parametrize('change', ['version', 'same_version_body', 'owner', 'writer'])
def test_changed_session_blocks_approval_before_claim_or_next_model(paused_session, change):
    repository, run = paused_session
    session = repository.get_sdk_session(run.thread_id)
    if change in {'version', 'same_version_body'}:
        update = {'items': [*session.items, {'role': 'user', 'content': 'Unexpected newer context'}]}
        if change == 'version':
            update['version'] = session.version + 1
    else:
        update = {'user_id': 'another_owner'} if change == 'owner' else {'writer_run_id': 'another_writer'}
    repository.save_sdk_session(session.model_copy(update=update))
    model = ScriptedModel([[assistant_message('Must not resume stale context')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    with pytest.raises(PermissionError, match='sdk_session_'):
        runtime.resume_sync(run.id, user=USER, decisions={'checkpoint_call': False})
    assert not model.calls
    assert repository.get_agent_run(run.id).status is AgentRunStatus.WAITING_APPROVAL
    assert not any(event.event_type == 'approval_resolved' for event in repository.list_agent_run_events(run.id))


def test_unchanged_session_resumes_after_database_reopen(paused_session):
    repository, run = paused_session
    reopened = SQLiteStore(repository.db_path)
    model = ScriptedModel([[assistant_message('Resumed trusted context')]])
    try:
        result = AgentRuntimeService(reopened, model=model, enabled=True).resume_sync(
            run.id, user=USER, decisions={'checkpoint_call': False},
        )
        assert result.content == 'Resumed trusted context'
        assert reopened.get_agent_run(run.id).status is AgentRunStatus.COMPLETED
    finally:
        reopened.close()


def test_projected_chat_marker_does_not_change_frozen_sdk_context(paused_session):
    repository, run = paused_session
    message = repository.add_chat_message(ChatMessage(thread_id=run.thread_id, role='assistant',
                                                       content='Already displayed pending approval'))
    before = repository.get_sdk_session(run.thread_id)
    repository.mark_sdk_session_chat_messages(run.thread_id, [message.id])
    assert repository.get_sdk_session(run.thread_id).version == before.version
    model = ScriptedModel([[assistant_message('Resumed after projection marker')]])
    result = AgentRuntimeService(repository, model=model, enabled=True).resume_sync(
        run.id, user=USER, decisions={'checkpoint_call': False},
    )
    assert result.content == 'Resumed after projection marker'


def test_session_change_between_precheck_and_claim_is_rejected_atomically(paused_session, monkeypatch):
    repository, run = paused_session
    claim = repository.claim_agent_run_for_resume

    def change_before_claim(*args, **kwargs):
        session = repository.get_sdk_session(run.thread_id)
        repository.save_sdk_session(session.model_copy(update={'version': session.version + 1,
                                                               'items': [*session.items, {'role': 'user', 'content': 'Late change'}]}))
        return claim(*args, **kwargs)

    monkeypatch.setattr(repository, 'claim_agent_run_for_resume', change_before_claim)
    model = ScriptedModel([[assistant_message('Must not resume')]])
    with pytest.raises(PermissionError, match='sdk_session_checkpoint_changed'):
        AgentRuntimeService(repository, model=model, enabled=True).resume_sync(
            run.id, user=USER, decisions={'checkpoint_call': False},
        )
    assert not model.calls
    assert repository.get_agent_run(run.id).status is AgentRunStatus.WAITING_APPROVAL
    assert not any(event.event_type == 'approval_resolved' for event in repository.list_agent_run_events(run.id))


@pytest.mark.parametrize('change', ['writer_generation', 'missing_checkpoint'])
def test_changed_writer_or_unverified_legacy_checkpoint_is_not_resumed(paused_session, change):
    repository, run = paused_session
    if change == 'writer_generation':
        repository.save_agent_run(run.model_copy(update={'writer_generation_epoch': (run.writer_generation_epoch or 0) + 1}))
    else:
        paused = {key: value for key, value in run.paused_state.items() if key != 'agentmesh_session_checkpoint'}
        repository.save_agent_run(run.model_copy(update={'paused_state': paused}))
    model = ScriptedModel([[assistant_message('Must not resume')]])
    with pytest.raises(PermissionError, match='sdk_session_checkpoint_'):
        AgentRuntimeService(repository, model=model, enabled=True).resume_sync(
            run.id, user=USER, decisions={'checkpoint_call': False},
        )
    assert not model.calls
    assert repository.get_agent_run(run.id).status is AgentRunStatus.WAITING_APPROVAL
