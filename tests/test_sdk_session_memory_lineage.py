from __future__ import annotations

import asyncio
import sqlite3

import pytest
from agents.testing import ScriptedModel, assistant_message, function_call

from agentmesh.agent_runtime.compaction import compact_session_if_needed
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.agent_runtime.session import AgentMeshSession
from agentmesh.memory_lifecycle import MemoryForgetRequestV1, MemoryForgettingService
from agentmesh.models import (
    AgentRun,
    ChatMessage,
    ChatThread,
    DocumentRecord,
    MemoryLayer,
    Source,
    UserMemoryItem,
    now_utc,
)
from agentmesh.runtime_capacity import RuntimeCapacityController
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.store import SQLiteStore
from agentmesh.tools import ensure_tool_seed_data


@pytest.fixture
def session_memory(tmp_path, monkeypatch):
    repository = SQLiteStore(tmp_path / 'session-lineage.sqlite3')
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    ensure_tool_seed_data(repository, granted_by='system')
    thread = repository.add_chat_thread(ChatThread(user_id=USER.id, workspace_id=USER.workspace_id,
                                                   project_id=USER.default_project_id, title='Memory history'))
    source = repository.add_source(Source(id='session_document_source', source_type='document', title='Session document',
                                          reference='document://session_doc#v1/text', user_id=USER.id,
                                          workspace_id=USER.workspace_id, project_id=USER.default_project_id))
    repository.add_document(DocumentRecord(id='session_doc', title='Session document', text='Use the checkout regression.',
                                           file_name='session.txt', content_type='text/plain', source=source,
                                           uploaded_by=USER.id, workspace_id=USER.workspace_id,
                                           project_id=USER.default_project_id))
    memory = repository.add_user_memory_item(UserMemoryItem(
        id='session_memory', user_id=USER.id, workspace_id=USER.workspace_id, project_id=USER.default_project_id,
        layer=MemoryLayer.MID_TERM, title='Session evidence', summary='Session evidence: use the checkout regression.',
        source_kind='imported_document', sources=[source],
    ))
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'off')
    model = ScriptedModel([[function_call('memory_search', {'query': 'Session evidence'}, call_id='session_lookup')],
                           [assistant_message('Use the checkout regression [P1].')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    answer = runtime.run_sync(content='Search our Session evidence', user=USER, thread_id=thread.id, history=[])
    first = repository.get_agent_run(answer.run_id)
    run = repository.save_agent_run(AgentRun(user_id=USER.id, workspace_id=USER.workspace_id,
                                            project_id=USER.default_project_id, thread_id=thread.id,
                                            input_text='Continue', status='running'))
    yield repository, memory, thread, first, run
    repository.close()


def test_actual_sdk_memory_outputs_archive_versioned_dependencies(session_memory):
    repository, memory, thread, first, run = session_memory
    record = repository.get_sdk_session(thread.id)
    assert any('checkout regression' in str(item) for item in record.items)
    assert len(record.memory_dependencies) == 1
    reference = record.memory_dependencies[0]
    assert reference.memory_id == memory.id
    assert reference.memory_version == memory.version
    assert reference.source_run_id == first.id
    assert len(reference.memory_hash) == 64
    assert asyncio.run(AgentMeshSession(thread.id, repository, run=run).get_items()) == record.items


@pytest.mark.parametrize('change', ['disabled', 'version_changed', 'archived', 'transferred'])
def test_next_run_cannot_reuse_a_stale_memory_body_from_session(session_memory, change):
    repository, memory, thread, _, run = session_memory
    if change == 'disabled':
        repository.save_user_memory_item(memory.model_copy(update={'status': 'inactive'}))
    elif change == 'version_changed':
        repository.save_user_memory_item(memory.model_copy(update={'version': memory.version + 1,
                                                                  'summary': 'Updated evidence'}))
    elif change == 'archived':
        repository.save_user_memory_item(memory.model_copy(update={'archived_at': now_utc()}))
    else:
        repository.save_user_memory_item(memory.model_copy(update={'user_id': 'someone_else'}))
    session = AgentMeshSession(thread.id, repository, run=run)
    with pytest.raises(PermissionError, match='sdk_session_source_changed'):
        asyncio.run(session.get_items())
    model = ScriptedModel([[assistant_message('Unreachable')]])
    with pytest.raises(PermissionError, match='sdk_session_source_changed'):
        asyncio.run(compact_session_if_needed(session, model, trigger_tokens=1, keep_recent_items=1))
    assert not model.calls


def test_forgetting_redacts_session_cache_and_blocks_late_sql_restoration(session_memory):
    repository, memory, thread, _, _ = session_memory
    frozen = repository.get_sdk_session(thread.id)
    MemoryForgettingService(repository).forget(memory.id,
                                              MemoryForgetRequestV1(command_id='forget_session', expected_version=1), USER)
    redacted = repository.get_sdk_session(thread.id)
    assert redacted.items == []
    assert redacted.source_status == 'withdrawn'
    assert redacted.version > frozen.version
    with pytest.raises(sqlite3.IntegrityError, match='sdk_session_source_withdrawn'):
        repository.save_sdk_session(frozen)
    reopened = SQLiteStore(repository.db_path)
    try:
        assert reopened.get_sdk_session(thread.id).items == []
        with pytest.raises(sqlite3.IntegrityError, match='sdk_session_source_withdrawn'):
            reopened.save_sdk_session(frozen)
    finally:
        reopened.close()


def test_forgetting_does_not_remove_delivered_chat_or_artifacts(session_memory):
    repository, memory, thread, _, run = session_memory
    message = repository.add_chat_message(ChatMessage(
        thread_id=thread.id, role='assistant', content='Already delivered answer',
    ))
    MemoryForgettingService(repository).forget(memory.id,
                                              MemoryForgetRequestV1(command_id='forget_history', expected_version=1), USER)
    assert repository._get('chat_messages', message.id, ChatMessage).content == 'Already delivered answer'
    with pytest.raises(PermissionError, match='sdk_session_source_withdrawn'):
        asyncio.run(AgentMeshSession(thread.id, repository, run=run).get_items())


def test_session_memory_is_rechecked_at_off_mode_model_handoff_after_queueing(session_memory):
    repository, memory, _, _, run = session_memory
    model = ScriptedModel([[assistant_message('Must not see withdrawn history')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True, capacity=RuntimeCapacityController(llm_limit=1))

    async def scenario():
        pending = None
        try:
            async with runtime.capacity.llm_slot():
                pending = asyncio.create_task(runtime._execute_run(
                    run=run, selected=runtime._select_model(USER), content=run.input_text,
                    user=USER, history=[], skill=None,
                ))
                async with asyncio.timeout(10):
                    while not any(event.event_type == 'context_request_budget'
                                  for event in repository.list_agent_run_events(run.id)):
                        await asyncio.sleep(0.005)
                assert not model.calls
                MemoryForgettingService(repository).forget(memory.id,
                    MemoryForgetRequestV1(command_id='forget_queued_session', expected_version=1), USER)
            with pytest.raises(PermissionError, match='sdk_session_source_withdrawn'):
                await pending
            assert not model.calls
            assert repository.list_memory_use_receipts_for_run(run.id) == []
        finally:
            if pending is not None and not pending.done():
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending

    asyncio.run(scenario())


@pytest.mark.parametrize('change', ['version_changed', 'withdrawn', 'transferred'])
def test_native_document_changes_invalidate_archived_memory_history(session_memory, change):
    repository, _, thread, _, run = session_memory
    document = repository.get_document('session_doc')
    if change == 'version_changed':
        repository.save_document(document.model_copy(update={'version': 2, 'text': 'Updated native evidence'}))
    elif change == 'withdrawn':
        MemoryForgettingService(repository).withdraw_document(document.id,
            MemoryForgetRequestV1(command_id='withdraw_session_document', expected_version=1), USER)
        assert repository.get_sdk_session(thread.id).items == []
    else:
        repository.save_document(document.model_copy(update={'uploaded_by': 'another_owner'}))
    with pytest.raises(PermissionError, match='sdk_session_source_'):
        asyncio.run(AgentMeshSession(thread.id, repository, run=run).get_items())
