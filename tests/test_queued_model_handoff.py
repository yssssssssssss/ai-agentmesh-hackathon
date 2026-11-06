from __future__ import annotations

import asyncio

import pytest
from agents import function_tool
from agents.testing import ScriptedModel, assistant_message

from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.memory_context.request_budget import ContextRequestError
from agentmesh.memory_context.service import MemoryContextError
from agentmesh.models import (
    AgentRun,
    AgentRunStatus,
    ChatThread,
    MemoryLayer,
    Project,
    User,
    UserMemoryItem,
    Workspace,
)
from agentmesh.runtime_capacity import RuntimeCapacityController
from agentmesh.store import SQLiteStore


@pytest.mark.parametrize('change', ['unchanged', 'owner_disabled', 'memory_changed', 'tool_schema_changed', 'concurrent_owner'])
def test_queued_request_delivers_memory_only_after_capacity_and_current_authority(tmp_path, monkeypatch, change):
    repository = SQLiteStore(tmp_path / 'queued-model.sqlite3')
    repository.save_workspace(Workspace(id='ws_queue', name='Queue', description='Queue'))
    owner = repository.save_user(User(id='user_queue', workspace_id='ws_queue', default_project_id='project_queue',
                                     name='Queue owner', role='user', personal_agent_id='agent_queue'))
    repository.save_project(Project(id=owner.default_project_id, workspace_id=owner.workspace_id,
                                    name='Queue', goal='Ship', member_ids=[owner.id]))
    thread = repository.add_chat_thread(ChatThread(user_id=owner.id, workspace_id=owner.workspace_id,
                                                   project_id=owner.default_project_id, title='Queue'))
    run = repository.save_agent_run(AgentRun(thread_id=thread.id, user_id=owner.id, workspace_id=owner.workspace_id,
                                            project_id=owner.default_project_id, project_chat=True,
                                            input_text='queue memory', status=AgentRunStatus.RUNNING))
    memory = repository.add_user_memory_item(UserMemoryItem(
        id='queue_memory', title='Queue memory', summary='Approved queue guidance.',
        layer=MemoryLayer.MID_TERM, user_id=owner.id, workspace_id=owner.workspace_id,
        project_id=run.project_id, source_kind='manual',
    ))
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'inject')
    model = ScriptedModel([[assistant_message('Queued guidance [P1]')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True, capacity=RuntimeCapacityController(llm_limit=1))
    agents = []
    other = None
    other_model = ScriptedModel([[assistant_message('Must not leak into another owner')]])
    if change == 'tool_schema_changed':
        @function_tool
        def lookup() -> str:
            """Read current project facts."""
            return 'Known'

        build = runtime._build_agent

        def capture_agent(**kwargs):
            agent = build(**kwargs)
            agent.tools.append(lookup)
            agents.append(agent)
            return agent

        monkeypatch.setattr(runtime, '_build_agent', capture_agent)
    elif change == 'concurrent_owner':
        second = repository.save_user(owner.model_copy(update={'id': 'queue_other', 'personal_agent_id': 'agent_queue_other'}))
        project = repository.get_project(run.project_id)
        repository.save_project(project.model_copy(update={'member_ids': [owner.id, second.id]}))
        second_thread = repository.add_chat_thread(thread.model_copy(update={'id': 'queue_other_thread', 'user_id': second.id}))
        second_run = repository.save_agent_run(run.model_copy(update={'id': 'queue_other_run', 'user_id': second.id,
                                                                     'thread_id': second_thread.id}))
        repository.add_user_memory_item(memory.model_copy(update={'id': 'queue_other_memory', 'user_id': second.id}))
        other = (second, second_run, AgentRuntimeService(repository, model=other_model, enabled=True, capacity=runtime.capacity))

    async def scenario():
        pending = None
        other_pending = None
        admitted = {run.id: asyncio.Event()}
        if other:
            admitted[other[1].id] = asyncio.Event()
        append_event = repository.append_agent_run_event

        def record_admission(run_id, event_type, payload=None):
            event = append_event(run_id, event_type, payload)
            if event_type == 'context_request_budget' and run_id in admitted:
                admitted[run_id].set()
            return event

        monkeypatch.setattr(repository, 'append_agent_run_event', record_admission)
        try:
            async with runtime.capacity.llm_slot():
                pending = asyncio.create_task(runtime._execute_run(
                    run=run, selected=runtime._select_model(owner), content=run.input_text,
                    user=owner, history=[], skill=None,
                ))
                if other:
                    actor, other_run, other_runtime = other
                    other_pending = asyncio.create_task(other_runtime._execute_run(
                        run=other_run, selected=other_runtime._select_model(actor), content=other_run.input_text,
                        user=actor, history=[], skill=None,
                    ))
                async with asyncio.timeout(10):
                    await admitted[run.id].wait()
                    if other:
                        await admitted[other[1].id].wait()
                assert all(any(event.event_type == 'context_request_budget'
                               for event in repository.list_agent_run_events(run_id)) for run_id in admitted)
                assert not model.calls
                assert repository.list_memory_use_receipts_for_run(run.id) == []
                if change == 'owner_disabled':
                    repository.save_user(owner.model_copy(update={'status': 'disabled'}))
                elif change == 'memory_changed':
                    repository.save_user_memory_item(memory.model_copy(update={'status': 'forgotten', 'version': 2}))
                elif change == 'tool_schema_changed':
                    agents[0].tools[-1].description = '字段定义' * 30000
                elif other:
                    repository.save_user(other[0].model_copy(update={'status': 'disabled'}))
                    assert repository.list_memory_use_receipts_for_run(other[1].id) == []
            if change in {'unchanged', 'concurrent_owner'}:
                answer = await pending
                assert answer.content == 'Queued guidance [P1]'
                assert len(model.calls) == 1
                assert len(repository.list_memory_use_receipts_for_run(run.id)) == 1
                if other:
                    with pytest.raises(MemoryContextError):
                        await other_pending
                    assert not other_model.calls
                    assert repository.list_memory_use_receipts_for_run(other[1].id) == []
            else:
                with pytest.raises(ContextRequestError if change == 'tool_schema_changed' else MemoryContextError):
                    await pending
                assert not model.calls
                assert repository.list_memory_use_receipts_for_run(run.id) == []
        finally:
            if pending is not None and not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            if other_pending is not None and not other_pending.done():
                other_pending.cancel()
                await asyncio.gather(other_pending, return_exceptions=True)

    try:
        asyncio.run(scenario())
    finally:
        repository.close()
