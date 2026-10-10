from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest
from agents.testing import ModelStep, ScriptedModel, assistant_message

from agentmesh.agent_runtime.compaction import compact_session_if_needed
from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.agent_runtime.service import _CapacityBoundModel
from agentmesh.agent_runtime.session import AgentMeshSession
from agentmesh.models import (
    AgentRun,
    AgentRunStatus,
    ChatMessage,
    ChatRole,
    ChatThread,
    Project,
    SDKSessionRecord,
    User,
    Workspace,
    now_utc,
)
from agentmesh.runtime_capacity import RuntimeCapacityController
from agentmesh.store import SQLiteStore


@pytest.fixture
def owned_session(tmp_path):
    repository = SQLiteStore(tmp_path / 'owned-session.sqlite3')
    repository.save_workspace(Workspace(id='ws_session', name='Session', description='Session'))
    owner = repository.save_user(User(id='session_owner', workspace_id='ws_session',
                                     default_project_id='project_session', name='Owner', role='user',
                                     personal_agent_id='agent_session'))
    other = repository.save_user(owner.model_copy(update={'id': 'session_other', 'personal_agent_id': 'agent_other'}))
    repository.save_project(Project(id=owner.default_project_id, workspace_id=owner.workspace_id,
                                    name='Session', goal='Ship', member_ids=[owner.id, other.id]))
    thread = repository.add_chat_thread(ChatThread(id='owned_thread', workspace_id=owner.workspace_id,
                                                   project_id=owner.default_project_id, user_id=owner.id,
                                                   title='Private session'))
    run = repository.save_agent_run(AgentRun(thread_id=thread.id, user_id=owner.id,
                                            workspace_id=owner.workspace_id, project_id=owner.default_project_id,
                                            input_text='Question', status='running', writer_generation_epoch=1))
    yield repository, owner, other, thread, run
    repository.close()


def test_session_cannot_read_another_owners_thread(owned_session):
    repository, _, other, thread, run = owned_session

    async def scenario():
        session = AgentMeshSession(thread.id, repository, run=run)
        await session.add_items([{'role': 'user', 'content': 'Private history'}])
        impostor = repository.save_agent_run(run.model_copy(update={'id': 'other_run', 'user_id': other.id}))
        with pytest.raises(PermissionError, match='sdk_session_not_authorized'):
            await AgentMeshSession(thread.id, repository, run=impostor).get_items()
        assert await session.get_items() == [{'role': 'user', 'content': 'Private history'}]

    asyncio.run(scenario())


def test_bootstrap_uses_current_persisted_message_and_rejects_foreign_history(owned_session):
    repository, _, other, thread, run = owned_session
    canonical = repository.add_chat_message(ChatMessage(thread_id=thread.id, role=ChatRole.USER,
                                                        content='Authoritative content'))
    foreign_thread = repository.add_chat_thread(thread.model_copy(update={'id': 'foreign_thread', 'user_id': other.id}))
    foreign = repository.add_chat_message(ChatMessage(thread_id=foreign_thread.id, role=ChatRole.USER,
                                                      content='Other private content'))

    async def scenario():
        session = AgentMeshSession(thread.id, repository, run=run)
        await session.bootstrap([canonical.model_copy(update={'content': 'Forged caller content'})])
        assert await session.get_items() == [{'role': 'user', 'content': 'Authoritative content'}]
        with pytest.raises(PermissionError, match='sdk_session_history_not_authorized'):
            await session.bootstrap([canonical, foreign])
        with pytest.raises(PermissionError, match='sdk_session_history_not_authorized'):
            await session.bootstrap([canonical.model_copy(update={'id': 'nonexistent_message'})])
        assert len(await session.get_items()) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize('operation', ['read', 'append', 'replace', 'pop', 'clear', 'bootstrap'])
def test_each_session_operation_rejects_replaced_writer(owned_session, operation):
    repository, _, _, thread, run = owned_session
    message = repository.add_chat_message(ChatMessage(thread_id=thread.id, role=ChatRole.USER, content='New input'))

    async def scenario():
        session = AgentMeshSession(thread.id, repository, run=run)
        await session.add_items([{'role': 'user', 'content': 'Original'}])
        _, version = await session.snapshot()
        repository.save_agent_run(run.model_copy(update={'writer_generation_epoch': 2}))
        with pytest.raises(PermissionError, match='sdk_session_writer_changed'):
            if operation == 'read':
                await session.get_items()
            elif operation == 'append':
                await session.add_items([{'role': 'assistant', 'content': 'Stale'}])
            elif operation == 'replace':
                await session.replace_items([], expected_version=version)
            elif operation == 'pop':
                await session.pop_item()
            elif operation == 'clear':
                await session.clear_session()
            else:
                await session.bootstrap([message])
        assert repository.get_sdk_session(thread.id).items == [{'role': 'user', 'content': 'Original'}]

    asyncio.run(scenario())


def test_active_writer_is_exclusive_and_terminal_writer_can_be_replaced(owned_session):
    repository, _, _, thread, run = owned_session
    next_run = repository.save_agent_run(run.model_copy(update={'id': 'next_run'}))

    async def scenario():
        first = AgentMeshSession(thread.id, repository, run=run)
        await first.add_items([{'role': 'user', 'content': 'First'}])
        second = AgentMeshSession(thread.id, repository, run=next_run)
        with pytest.raises(PermissionError, match='sdk_session_writer_busy'):
            await second.get_items()
        repository.save_agent_run(run.model_copy(update={'status': AgentRunStatus.COMPLETED}))
        assert await second.get_items() == [{'role': 'user', 'content': 'First'}]
        await second.add_items([{'role': 'user', 'content': 'Second'}])
        with pytest.raises(PermissionError):
            await first.add_items([{'role': 'assistant', 'content': 'Late first'}])
        assert len(await second.get_items()) == 2

    asyncio.run(scenario())


@pytest.mark.parametrize('change', ['disabled', 'revoked', 'archived_project', 'transferred_thread', 'cancelled_run'])
def test_session_rechecks_current_authority(owned_session, change):
    repository, owner, other, thread, run = owned_session

    async def scenario():
        session = AgentMeshSession(thread.id, repository, run=run)
        await session.add_items([{'role': 'user', 'content': 'Private'}])
        if change == 'disabled':
            repository.save_user(owner.model_copy(update={'status': 'disabled'}))
        elif change == 'revoked':
            project = repository.get_project(run.project_id)
            repository.save_project(project.model_copy(update={'member_ids': [other.id]}))
        elif change == 'archived_project':
            project = repository.get_project(run.project_id)
            repository.save_project(project.model_copy(update={'status': 'archived'}))
        elif change == 'transferred_thread':
            repository.save_chat_thread(thread.model_copy(update={'user_id': other.id}))
        else:
            repository.save_agent_run(run.model_copy(update={'status': AgentRunStatus.CANCELLED}))
        with pytest.raises(PermissionError, match='sdk_session_'):
            await session.get_items()
        with pytest.raises(PermissionError, match='sdk_session_'):
            await session.add_items([{'role': 'assistant', 'content': 'Late'}])

    asyncio.run(scenario())


@pytest.mark.parametrize('operation', ['append', 'pop', 'clear'])
def test_independent_session_instances_cannot_commit_a_stale_version(owned_session, operation):
    repository, _, _, thread, run = owned_session

    async def scenario():
        first = AgentMeshSession(thread.id, repository, run=run)
        second = AgentMeshSession(thread.id, repository, run=run)
        await first.add_items([{'role': 'user', 'content': 'Original'}])
        await second.get_items()
        await first.add_items([{'role': 'assistant', 'content': 'New authoritative result'}])
        with pytest.raises(PermissionError, match='sdk_session_version_changed'):
            if operation == 'append':
                await second.add_items([{'role': 'assistant', 'content': 'Stale duplicate'}])
            elif operation == 'pop':
                await second.pop_item()
            else:
                await second.clear_session()
        assert len(await first.get_items()) == 2

    asyncio.run(scenario())


def test_append_command_is_durable_idempotent_and_conflicting_replay_is_rejected(owned_session):
    repository, _, _, thread, run = owned_session
    version = repository.get_sdk_session(thread.id, run=run).version
    items = [{'role': 'user', 'content': 'Commit exactly once'}]
    first = repository.append_sdk_session_items(thread.id, items, run=run,
                                                expected_version=version, command_id='append_once')
    reopened = SQLiteStore(repository.db_path)
    try:
        replay = reopened.append_sdk_session_items(thread.id, items, run=run,
                                                   expected_version=version, command_id='append_once')
        assert replay.version == first.version
        assert replay.items == items
        with pytest.raises(PermissionError, match='sdk_session_commit_conflict'):
            reopened.append_sdk_session_items(thread.id, [{'role': 'user', 'content': 'Changed payload'}], run=run,
                                               expected_version=version, command_id='append_once')
    finally:
        reopened.close()


def test_unowned_legacy_session_body_is_not_silently_adopted(owned_session):
    repository, _, _, thread, run = owned_session
    repository.save_sdk_session(SDKSessionRecord(id=thread.id,
                                                 items=[{'role': 'user', 'content': 'Unverified legacy body'}]))
    with pytest.raises(PermissionError, match='sdk_session_legacy_unverified'):
        asyncio.run(AgentMeshSession(thread.id, repository, run=run).get_items())
    assert repository.get_sdk_session(thread.id).user_id is None


def test_new_generation_reclaims_writer_without_authorizing_the_old_instance(owned_session):
    repository, _, _, thread, run = owned_session

    async def scenario():
        old = AgentMeshSession(thread.id, repository, run=run)
        await old.add_items([{'role': 'user', 'content': 'Original'}])
        current = repository.save_agent_run(run.model_copy(update={'writer_generation_epoch': 2}))
        new = AgentMeshSession(thread.id, repository, run=current)
        assert await new.get_items() == [{'role': 'user', 'content': 'Original'}]
        await new.add_items([{'role': 'assistant', 'content': 'New generation'}])
        with pytest.raises(PermissionError, match='sdk_session_writer_changed'):
            await old.add_items([{'role': 'assistant', 'content': 'Late old generation'}])

    asyncio.run(scenario())


@pytest.mark.parametrize('change', ['disabled', 'appended', 'expired'])
def test_compaction_rechecks_session_authority_and_version_after_capacity_wait(owned_session, change):
    repository, owner, _, thread, run = owned_session

    async def scenario():
        session = AgentMeshSession(thread.id, repository, run=run)
        await session.add_items([{'role': 'user', 'content': f'Earlier-{i}'} for i in range(25)])
        model = ScriptedModel([[assistant_message('Must not summarize stale context')]])
        capacity = RuntimeCapacityController(llm_limit=1)
        entered = asyncio.Event()

        class QueuedModel(_CapacityBoundModel):
            async def get_response(self, *args, **kwargs):
                entered.set()
                return await super().get_response(*args, **kwargs)

        pending = None
        try:
            async with capacity.llm_slot():
                pending = asyncio.create_task(compact_session_if_needed(
                    session, QueuedModel(model, capacity), trigger_tokens=1, keep_recent_items=4, defer_delivery=True,
                ))
                async with asyncio.timeout(10):
                    await entered.wait()
                assert not model.calls
                if change == 'disabled':
                    repository.save_user(owner.model_copy(update={'status': 'disabled'}))
                elif change == 'appended':
                    await session.add_items([{'role': 'user', 'content': 'Concurrent fresh input'}])
                else:
                    repository.save_agent_run(run.model_copy(update={'deadline_at': now_utc() - timedelta(seconds=1)}))
            with pytest.raises(PermissionError, match='sdk_session_'):
                await pending
            assert not model.calls
            assert len(repository.get_sdk_session(thread.id).items) == (26 if change == 'appended' else 25)
        finally:
            if pending is not None and not pending.done():
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending

    asyncio.run(scenario())


def test_compaction_timeout_preserves_history_and_cancels_provider(owned_session):
    repository, _, _, thread, run = owned_session

    async def scenario():
        session = AgentMeshSession(thread.id, repository, run=run)
        items = [{'role': 'user', 'content': f'Earlier-{i}'} for i in range(25)]
        await session.add_items(items)
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def slow_response(_call):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        model = ScriptedModel([ModelStep.respond(slow_response)])
        with pytest.raises(TimeoutError):
            await compact_session_if_needed(session, model, trigger_tokens=1, keep_recent_items=4,
                                            timeout_seconds=1.0)
        assert started.is_set()
        assert cancelled.is_set()
        assert await session.get_items() == items
        assert len(model.calls) == 1
        assert model.first_call.model_settings.retry.max_retries == 0

    asyncio.run(scenario())


def test_runtime_session_failure_is_terminal_and_has_static_error_code(owned_session):
    from agentmesh.agent_runtime.service import AgentRuntimeService

    repository, _, other, thread, _ = owned_session
    model = ScriptedModel([[assistant_message('Unreachable')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    with pytest.raises(PermissionError, match='sdk_session_not_authorized'):
        runtime.run_sync(content='Other owner cannot continue', user=other, thread_id=thread.id, history=[])
    attempted = repository.list_agent_runs(user_id=other.id)[0]
    assert attempted.status is AgentRunStatus.FAILED
    assert attempted.error_code == 'sdk_session_not_authorized'
    assert not model.calls


def test_sdk_context_wrapper_cannot_substitute_a_different_execution(owned_session):
    repository, _, other, thread, run = owned_session
    context = AgentMeshRunContext(user_id=run.user_id, workspace_id=run.workspace_id, project_id=run.project_id,
                                  thread_id=run.thread_id, run_id=run.id)

    async def scenario():
        session = AgentMeshSession(thread.id, repository, run=run)
        valid = SimpleNamespace(context=context)
        await session.add_items([{'role': 'user', 'content': 'Owned'}], wrapper=valid)
        invalid = SimpleNamespace(context=context.model_copy(update={'user_id': other.id}))
        for operation in (session.get_items, session.pop_item, session.clear_session):
            with pytest.raises(PermissionError, match='sdk_session_not_authorized'):
                await operation(wrapper=invalid)
        with pytest.raises(PermissionError, match='sdk_session_not_authorized'):
            await session.add_items([{'role': 'user', 'content': 'Foreign'}], wrapper=invalid)
        assert len(await session.get_items(wrapper=valid)) == 1

    asyncio.run(scenario())
