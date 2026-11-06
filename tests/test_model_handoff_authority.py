from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta

import httpx
import pytest
from agents import Agent, RunConfig, Runner
from agents.testing import ModelStep, ScriptedModel, assistant_message

from agentmesh.memory_context.service import MemoryContextError, MemoryContextService
from agentmesh.models import AgentRun, AgentRunStatus, ChatThread, Project, User, Workspace, now_utc
from agentmesh.store import SQLiteStore


@pytest.fixture
def model_authority(tmp_path, monkeypatch):
    repository = SQLiteStore(tmp_path / 'model-authority.sqlite3')
    repository.save_workspace(Workspace(id='ws_handoff', name='Handoff', description='Handoff'))
    user = repository.save_user(User(id='user_handoff', workspace_id='ws_handoff', default_project_id='project_handoff',
                                    name='Owner', role='user', personal_agent_id='agent_handoff'))
    repository.save_project(Project(id=user.default_project_id, workspace_id=user.workspace_id,
                                    name='Handoff', goal='Ship', member_ids=[user.id]))
    thread = repository.add_chat_thread(ChatThread(user_id=user.id, workspace_id=user.workspace_id,
                                                   project_id=user.default_project_id, title='Private'))
    run = repository.save_agent_run(AgentRun(thread_id=thread.id, user_id=user.id, workspace_id=user.workspace_id,
                                            project_id=user.default_project_id, input_text='Private question',
                                            status=AgentRunStatus.RUNNING, writer_generation_epoch=1))
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'off')
    yield repository, user, run
    repository.close()


@pytest.mark.parametrize('streamed', [False, True])
@pytest.mark.parametrize('change,code', [
    ('cancelled', 'model_handoff_run_inactive'),
    ('waiting', 'model_handoff_run_inactive'),
    ('owner_disabled', 'model_handoff_not_authorized'),
    ('membership_revoked', 'model_handoff_not_authorized'),
    ('thread_transferred', 'model_handoff_not_authorized'),
    ('writer_replaced', 'model_handoff_identity_changed'),
    ('project_inactive', 'model_handoff_not_authorized'),
    ('deadline_expired', 'model_handoff_deadline_exceeded'),
])
def test_every_local_handoff_checks_current_authority_without_memory(model_authority, streamed, change, code):
    repository, user, run = model_authority
    model = ScriptedModel([[assistant_message('must not be called')]])
    handoffs = []
    guarded = MemoryContextService(repository).guard_model_request(model, run=run,
                                                                  on_handoff=lambda: handoffs.append(True))
    if change in {'cancelled', 'waiting'}:
        current = repository.get_agent_run(run.id)
        current.status = AgentRunStatus.CANCELLED if change == 'cancelled' else AgentRunStatus.WAITING_APPROVAL
        repository.save_agent_run(current)
    elif change == 'owner_disabled':
        repository.save_user(user.model_copy(update={'status': 'disabled'}))
    elif change == 'membership_revoked':
        project = repository.get_project(run.project_id)
        repository.save_project(project.model_copy(update={'member_ids': ['someone_else']}))
    elif change == 'thread_transferred':
        thread = repository.get_chat_thread(run.thread_id)
        repository.save_chat_thread(thread.model_copy(update={'user_id': 'someone_else'}))
    elif change == 'project_inactive':
        project = repository.get_project(run.project_id)
        repository.save_project(project.model_copy(update={'status': 'archived'}))
    elif change == 'deadline_expired':
        current = repository.get_agent_run(run.id)
        repository.save_agent_run(current.model_copy(update={'deadline_at': now_utc() - timedelta(seconds=1)}))
    else:
        current = repository.get_agent_run(run.id)
        repository.save_agent_run(current.model_copy(update={'writer_generation_epoch': 2}))

    async def scenario():
        agent = Agent(name='handoff', instructions='Private instructions', model=guarded)
        if streamed:
            result = Runner.run_streamed(agent, run.input_text, run_config=RunConfig(tracing_disabled=True))
            async for _event in result.stream_events():
                pass
        else:
            await Runner.run(agent, run.input_text, run_config=RunConfig(tracing_disabled=True))

    with pytest.raises(MemoryContextError, match=code):
        asyncio.run(scenario())
    assert not model.calls
    assert handoffs == []


def test_authorized_off_mode_handoff_keeps_budget_and_execution_callbacks(model_authority):
    repository, _, run = model_authority
    model = ScriptedModel([[assistant_message('authorized answer')]])
    seen = []
    guarded = MemoryContextService(repository).guard_model_request(model, run=run,
                                                                  on_handoff=lambda: seen.append(len(model.calls)))
    result = asyncio.run(Runner.run(Agent(name='handoff', model=guarded), run.input_text,
                                    run_config=RunConfig(tracing_disabled=True)))
    assert result.final_output == 'authorized answer'
    assert seen == [0]
    assert model.first_call.model_settings.max_tokens == 8192


def test_mutating_callers_run_cannot_replace_admitted_writer_identity(model_authority):
    repository, _, run = model_authority
    model = ScriptedModel([[assistant_message('must not be called')]])
    guarded = MemoryContextService(repository).guard_model_request(model, run=run)
    run.writer_generation_epoch = 2
    repository.save_agent_run(run)
    with pytest.raises(MemoryContextError, match='model_handoff_identity_changed'):
        asyncio.run(Runner.run(Agent(name='handoff', model=guarded), run.input_text,
                               run_config=RunConfig(tracing_disabled=True)))
    assert not model.calls


def test_stream_retry_rechecks_revoked_authority_before_second_provider_call(model_authority):
    from agentmesh.agent_runtime.model_retry import AtomicStreamModel
    from agentmesh.agent_runtime.service import AgentRuntimeService

    repository, user, run = model_authority

    async def interrupted(_call):
        repository.save_user(user.model_copy(update={'status': 'disabled'}))
        raise httpx.RemoteProtocolError('test stream interrupted')
        yield  # pragma: no cover

    model = ScriptedModel([ModelStep.stream(interrupted), [assistant_message('must not be called')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    agent = runtime._build_agent(selected=runtime._select_model(user), user=user, skill=None,
                                 model=AtomicStreamModel(model), allow_skill_activation=False)
    with pytest.raises(MemoryContextError, match='model_handoff_not_authorized'):
        asyncio.run(runtime._run_streamed(agent, run.input_text, run=run))
    assert len(model.calls) == 1


@pytest.mark.parametrize('streamed', [False, True])
def test_deferred_guard_owns_its_capacity_gate_without_runtime_stream_wrapper(model_authority, streamed):
    from agentmesh.agent_runtime.service import _CapacityBoundModel

    repository, user, run = model_authority
    model = ScriptedModel([[assistant_message('must not be called')]])

    class Capacity:
        @asynccontextmanager
        async def llm_slot(self):
            repository.save_user(user.model_copy(update={'status': 'disabled'}))
            yield

    guarded = MemoryContextService(repository).guard_model_request(
        _CapacityBoundModel(model, Capacity()), run=run, defer_delivery=True)

    async def scenario():
        agent = Agent(name='nonstream handoff', model=guarded)
        if streamed:
            result = Runner.run_streamed(agent, run.input_text, run_config=RunConfig(tracing_disabled=True))
            async for _ in result.stream_events():
                pass
        else:
            await Runner.run(agent, run.input_text, run_config=RunConfig(tracing_disabled=True))

    with pytest.raises(MemoryContextError, match='model_handoff_not_authorized'):
        asyncio.run(scenario())
    assert model.calls == ()


def test_planning_handoff_uses_explicit_phase_and_still_blocks_phase_change(model_authority):
    repository, _, run = model_authority
    run = repository.save_agent_run(run.model_copy(update={'status': AgentRunStatus.PLANNING}))
    model = ScriptedModel([[assistant_message('valid planning')], [assistant_message('must not be called')]])
    guarded = MemoryContextService(repository).guard_model_request(
        model, run=run, allowed_run_statuses=frozenset({AgentRunStatus.PLANNING}))
    agent = Agent(name='planning handoff', model=guarded)
    result = asyncio.run(Runner.run(agent, run.input_text, run_config=RunConfig(tracing_disabled=True)))
    assert result.final_output == 'valid planning'
    repository.save_agent_run(run.model_copy(update={'status': AgentRunStatus.WAITING_PLAN_APPROVAL}))
    with pytest.raises(MemoryContextError, match='model_handoff_run_inactive'):
        asyncio.run(Runner.run(agent, run.input_text, run_config=RunConfig(tracing_disabled=True)))
    assert len(model.calls) == 1
