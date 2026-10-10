from __future__ import annotations

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace

import pytest
from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call
from mcp.types import CallToolResult, TextContent
from mcp.types import Tool as MCPTool

from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.models import (
    AgentRun,
    AgentRunStatus,
    AgentToolGrant,
    ChatThread,
    SkillIntent,
    SkillPlan,
    SkillPlanNode,
    ToolDefinition,
    now_utc,
)
from agentmesh.runtime_capacity import RuntimeCapacityController
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.skill_runtime.sources import plan_run_execution_identity
from agentmesh.store import SQLiteStore
from agentmesh.tool_runtime.mcp import GovernedMCPServer
from agentmesh.tools import ensure_tool_seed_data


@pytest.fixture
def project(tmp_path, monkeypatch):
    repository = SQLiteStore(tmp_path / 'run-tool-budget.sqlite3')
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    ensure_tool_seed_data(repository, granted_by='system')
    thread = repository.add_chat_thread(ChatThread(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, title='Frozen ordinary tool quota'))
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'off')
    for key in ('AGENTMESH_RUN_MAX_TOOL_CALLS', 'AGENTMESH_RUN_MODEL_PRICES_JSON',
                'AGENTMESH_RUN_MODEL_COST_CURRENCY', 'AGENTMESH_RUN_MODEL_MAX_COST_MICROS'):
        monkeypatch.delenv(key, raising=False)
    yield repository, thread
    repository.close()


def test_runtime_stops_before_third_tool_when_frozen_limit_is_two(project, monkeypatch):
    repository, thread = project
    monkeypatch.setenv('AGENTMESH_RUN_MAX_TOOL_CALLS', '2')
    def change_policy_after_first_reservation(_call):
        monkeypatch.setenv('AGENTMESH_RUN_MAX_TOOL_CALLS', '24')
        return [function_call('memory_search', {'query': 'Evidence 0'}, call_id='tool-0')]

    model = ScriptedModel([ModelStep.respond(change_policy_after_first_reservation),
        *[[function_call('memory_search', {'query': f'Evidence {index}'}, call_id=f'tool-{index}')]
          for index in range(1, 3)], [assistant_message('unreachable')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    with pytest.raises(RuntimeError, match='run_tool_budget_exhausted'):
        runtime.run_sync(content='Read bounded evidence', user=USER, thread_id=thread.id, history=[])
    run = next(run for run in repository.list_agent_runs(USER.id) if run.thread_id == thread.id)
    assert run.status is AgentRunStatus.FAILED and run.error_code == 'run_tool_budget_exhausted'
    assert run.tool_call_count == 2 and len(model.calls) == 3
    assert repository.get_run_model_budget(run.id).limits.max_tool_calls == 2
    assert sum(event.action == 'sdk_tool_completed' for event in repository.audit_events) == 2


def test_saving_stale_run_cannot_restore_consumed_tool_quota(project):
    repository, thread = project
    run = repository.save_agent_run(AgentRun(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, thread_id=thread.id, input_text='Monotonic tool quota', status='running'))
    assert repository.consume_agent_run_tool_call(run.id, limit=1) == 1
    repository.save_agent_run(run)
    assert repository.get_agent_run(run.id).tool_call_count == 1
    assert repository.consume_agent_run_tool_call(run.id, limit=1) is None


def _approved_plan(repository, thread, catalog):
    skill = catalog.get_by_name('prd-feasibility', USER.personal_agent_id)
    profile = repository.get_skill_capability_profile(skill.id)
    repository.save_skill_capability_profile(profile.model_copy(update={'required_capabilities': []}))
    run = repository.save_agent_run(AgentRun(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, thread_id=thread.id, input_text='Read original evidence', status='running',
        orchestration_mode='execute', writer_generation_epoch=1))
    node = SkillPlanNode(skill_id=skill.id, skill_version=skill.version, skill_content_hash=skill.content_hash,
        reason='Review requirements', required=True, output_contract=['feasibility_review'], side_effect=profile.side_effect)
    plan = repository.save_skill_plan(SkillPlan(run_id=run.id, status='approved',
        intent=SkillIntent(goal=run.input_text), candidate_skill_ids=[skill.id], nodes=[node],
        output_contract=['feasibility_review']))
    return repository.save_agent_run(run.model_copy(update={'plan_id': plan.id})), plan


@pytest.mark.parametrize('change', ['writer', 'plan_version', 'node_attempt'])
def test_model_return_cannot_start_tool_using_replaced_execution(project, monkeypatch, configure_pilot_wiki, tmp_path, change):
    repository, thread = project
    monkeypatch.setenv('AGENTMESH_SKILL_ORCHESTRATION', 'execute')
    configure_pilot_wiki(tmp_path / 'wiki')
    catalog = SkillCatalogService(repository)
    catalog.reload()
    run, plan = _approved_plan(repository, thread, catalog)
    replacements = []

    def replace_writer(_call):
        if change == 'writer':
            current = repository.get_agent_run(run.id)
            repository.save_agent_run(current.model_copy(update={'writer_generation_epoch': 2}))
        else:
            current_plan = repository.get_skill_plan(plan.id)
            if change == 'plan_version':
                current_plan.version += 1
            else:
                current_plan.nodes[0].attempt += 1
            repository.save_skill_plan(current_plan)
        replacements.append(change)
        return [function_call('read_skill_resource', {'paths': ['SKILL.md']}, call_id='old_resource_call')]

    model = ScriptedModel([ModelStep.respond(replace_writer), [assistant_message('unreachable')]])
    runtime = AgentRuntimeService(repository, model=model, skill_catalog=catalog, enabled=True)

    async def scenario():
        await runtime.start_approved_skill_plan(plan.id, user=USER)
        async with asyncio.timeout(15):
            while runtime.capacity.snapshot()['active_runs']:
                await asyncio.sleep(0.005)

    asyncio.run(scenario())
    current = repository.get_agent_run(run.id)
    assert replacements == [change], (current.error_code, repository.get_skill_plan(plan.id).nodes[0].error_code)
    assert current.tool_call_count == 0, (current.status, current.error_code)
    assert current.status is AgentRunStatus.RUNNING
    assert current.writer_generation_epoch == (2 if change == 'writer' else 1)
    assert len(model.calls) == 1
    assert not any(event.event_type in {'sdk_tool_hook_started', 'tool_call_claimed'}
                   for event in repository.list_agent_run_events(run.id))


@pytest.mark.parametrize('tool_name', ['memory_search', 'read_skill_resource'])
@pytest.mark.parametrize('change', ['writer', 'deadline', 'absolute_deadline'])
def test_queued_tool_rechecks_execution_and_deadlines(project, monkeypatch, configure_pilot_wiki, tmp_path, tool_name, change):
    repository, thread = project
    capacity = RuntimeCapacityController(tool_limit=1)
    catalog = None
    plan = None
    if tool_name == 'read_skill_resource':
        monkeypatch.setenv('AGENTMESH_SKILL_ORCHESTRATION', 'execute')
        configure_pilot_wiki(tmp_path / 'wiki')
        catalog = SkillCatalogService(repository)
        catalog.reload()
        run, plan = _approved_plan(repository, thread, catalog)
    arguments = {'query': 'Evidence'} if tool_name == 'memory_search' else {'paths': ['SKILL.md']}
    model = ScriptedModel([[function_call(tool_name, arguments, call_id='queued_original_tool')],
                           [assistant_message('unreachable')]])
    runtime = AgentRuntimeService(repository, model=model, skill_catalog=catalog, enabled=True, capacity=capacity)

    async def scenario():
        started = asyncio.Event()
        append = repository.append_agent_run_event

        def observe(run_id, event_type, payload=None):
            event = append(run_id, event_type, payload)
            if event_type == 'sdk_tool_hook_started':
                started.set()
            return event

        monkeypatch.setattr(repository, 'append_agent_run_event', observe)
        await capacity.acquire_tool()
        try:
            if plan is None:
                admitted = await runtime.start(content='Queued evidence', user=USER, thread_id=thread.id, history=[])
            else:
                admitted = await runtime.start_approved_skill_plan(plan.id, user=USER)
            async with asyncio.timeout(15):
                await started.wait()
            current = repository.get_agent_run(admitted.id)
            assert current.tool_call_count == 1
            update = ({'writer_generation_epoch': (current.writer_generation_epoch or 0) + 1} if change == 'writer' else
                {'deadline_at' if change == 'deadline' else 'absolute_expires_at': now_utc() - timedelta(seconds=1)})
            repository.save_agent_run(current.model_copy(update=update))
        finally:
            capacity.release_tool()
        async with asyncio.timeout(15):
            while capacity.snapshot()['active_runs']:
                await asyncio.sleep(0.005)
        return admitted

    admitted = asyncio.run(scenario())
    current = repository.get_agent_run(admitted.id)
    assert current.status is (AgentRunStatus.RUNNING if change == 'writer' else AgentRunStatus.FAILED)
    assert current.tool_call_count == 1
    if change != 'writer':
        assert current.error_code == 'run_tool_budget_deadline_exceeded'
    assert len(model.calls) == 1
    assert not any(event.event_type == 'tool_call_claimed' for event in repository.list_agent_run_events(admitted.id))
    assert capacity.snapshot()['active_tool_calls'] == capacity.snapshot()['active_runs'] == 0


def test_concurrent_tool_admissions_share_frozen_quota_and_reopen_keeps_consumption(project, monkeypatch):
    repository, thread = project
    monkeypatch.setenv('AGENTMESH_RUN_MAX_TOOL_CALLS', '1')
    run = repository.save_agent_run(AgentRun(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, thread_id=thread.id, input_text='One shared tool attempt', status='running'))
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: repository.consume_agent_run_tool_call(run.id), range(2)))
    assert sorted(outcomes, key=lambda value: value or 0) == [None, 1]
    monkeypatch.setenv('AGENTMESH_RUN_MAX_TOOL_CALLS', '24')
    reopened = SQLiteStore(repository.db_path)
    try:
        assert reopened.get_agent_run(run.id).tool_call_count == 1
        assert reopened.get_run_model_budget(run.id).limits.max_tool_calls == 1
        assert reopened.consume_agent_run_tool_call(run.id) is None
    finally:
        reopened.close()


@pytest.mark.parametrize('invalid', ['', '0', '25', 'true', '1.5'])
def test_invalid_tool_policy_refuses_before_model(project, monkeypatch, invalid):
    repository, thread = project
    monkeypatch.setenv('AGENTMESH_RUN_MAX_TOOL_CALLS', invalid)
    model = ScriptedModel([[assistant_message('unreachable')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    with pytest.raises(RuntimeError, match='run_model_budget_configuration_invalid'):
        runtime.run_sync(content='Invalid quota', user=USER, thread_id=thread.id, history=[])
    assert not model.calls


def test_tool_counter_policy_and_event_rollback_together(project):
    repository, thread = project
    run = repository.save_agent_run(AgentRun(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, thread_id=thread.id, input_text='Atomic tool quota', status='running'))
    with repository._connect() as connection:
        connection.execute("""CREATE TRIGGER refuse_tool_budget_event BEFORE INSERT ON agent_run_events
            WHEN json_extract(NEW.payload, '$.event_type') = 'run_tool_budget'
            BEGIN SELECT RAISE(ABORT, 'controlled_tool_budget_event_failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match='controlled_tool_budget_event_failure'):
        repository.consume_agent_run_tool_call(run.id)
    assert repository.get_agent_run(run.id).tool_call_count == 0
    assert repository.get_run_model_budget(run.id) is None
    assert not repository.list_agent_run_events(run.id)
    with repository._connect() as connection:
        connection.execute('DROP TRIGGER refuse_tool_budget_event')
    assert repository.consume_agent_run_tool_call(run.id) == 1


def test_approval_resume_keeps_consumed_tool_quota(project, monkeypatch):
    repository, thread = project
    monkeypatch.setenv('AGENTMESH_RUN_MAX_TOOL_CALLS', '1')
    repository.save_agent_tool_grant(AgentToolGrant(id='grant_tool_quota_web', agent_id=USER.personal_agent_id,
        tool_id='tool_web_research', granted_by='test'))
    model = ScriptedModel([[function_call('memory_search', {'query': 'Evidence'}, call_id='first_tool')],
        [function_call('web_research', {'query': 'Approval'}, call_id='quota_approval')],
        [assistant_message('unreachable')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    answer = runtime.run_sync(content='Read bounded evidence', user=USER, thread_id=thread.id, history=[])
    assert answer.waiting_approval and repository.get_agent_run(answer.run_id).tool_call_count == 1
    monkeypatch.setenv('AGENTMESH_RUN_MAX_TOOL_CALLS', '24')
    with pytest.raises(RuntimeError, match='run_tool_budget_exhausted'):
        runtime.resume_sync(answer.run_id, user=USER, decisions={'quota_approval': True})
    current = repository.get_agent_run(answer.run_id)
    assert current.status is AgentRunStatus.FAILED and current.error_code == 'run_tool_budget_exhausted'
    assert current.tool_call_count == 1 and len(model.calls) == 2
    assert repository.get_run_model_budget(current.id).limits.max_tool_calls == 1


@pytest.mark.parametrize('change', ['writer', 'deadline', 'absolute_deadline'])
def test_mcp_wait_rechecks_original_execution_before_provider(project, monkeypatch, change):
    repository, thread = project
    run = repository.save_agent_run(AgentRun(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, thread_id=thread.id, input_text='Governed MCP read', status='running',
        writer_generation_epoch=1))
    definition = repository.save_tool_definition(ToolDefinition(id='tool_mcp_quota', name='mcp_quota_test',
        description='Controlled read', category='integration', side_effect='read'))
    repository.save_agent_tool_grant(AgentToolGrant(id='grant_mcp_quota', agent_id=USER.personal_agent_id,
        tool_id=definition.id, granted_by='test'))
    context = AgentMeshRunContext(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, thread_id=thread.id, run_id=run.id,
        run_execution_hash=plan_run_execution_identity(run))
    calls = []

    async def call_tool(*args, **kwargs):
        calls.append((args, kwargs))
        return CallToolResult(content=[TextContent(type='text', text='unreachable')])

    capacity = RuntimeCapacityController(tool_limit=1)
    server = GovernedMCPServer(SimpleNamespace(name='controlled_mcp', call_tool=call_tool), repository=repository,
        context=context, definition=definition, allowed_tool_names={'lookup'}, capacity=capacity)

    async def scenario():
        await capacity.acquire_tool()
        queued = asyncio.Event()
        acquire = capacity.acquire_tool

        async def observe():
            queued.set()
            await acquire()

        monkeypatch.setattr(capacity, 'acquire_tool', observe)
        task = asyncio.create_task(server.call_tool('lookup', {}))
        try:
            async with asyncio.timeout(10):
                await queued.wait()
            update = ({'writer_generation_epoch': 2} if change == 'writer' else
                {'deadline_at' if change == 'deadline' else 'absolute_expires_at': now_utc() - timedelta(seconds=1)})
            repository.save_agent_run(run.model_copy(update=update))
        finally:
            capacity.release_tool()
        code = 'run_tool_budget_execution_changed' if change == 'writer' else 'run_tool_budget_deadline_exceeded'
        with pytest.raises(RuntimeError, match=code):
            await task

    asyncio.run(scenario())
    assert not calls and not repository.list_agent_run_events(run.id)
    assert capacity.snapshot()['active_tool_calls'] == 0


def test_runtime_mcp_admission_refusal_preserves_code_through_sdk_failure_pipeline(project, monkeypatch):
    repository, thread = project
    definition = repository.save_tool_definition(ToolDefinition(id='tool_sdk_mcp', name='sdk_mcp_test',
        description='Controlled read', category='integration', side_effect='read'))
    repository.save_agent_tool_grant(AgentToolGrant(id='grant_sdk_mcp', agent_id=USER.personal_agent_id,
        tool_id=definition.id, granted_by='test'))
    provider_calls = []

    async def noop(*args):
        pass

    async def list_tools(*args):
        return [MCPTool(name='lookup', inputSchema={'type': 'object', 'properties': {}, 'additionalProperties': False})]

    async def call_tool(*args, **kwargs):
        provider_calls.append((args, kwargs))
        return CallToolResult(content=[TextContent(type='text', text='unreachable')])

    capacity = RuntimeCapacityController(tool_limit=1)
    inner = SimpleNamespace(name='controlled_sdk_mcp', connect=noop, cleanup=noop, list_tools=list_tools, call_tool=call_tool)

    def build(*, context, **kwargs):
        return [GovernedMCPServer(inner, repository=repository, context=context, definition=definition,
            allowed_tool_names={'lookup'}, capacity=capacity)
        ]

    model = ScriptedModel([[function_call('lookup', {}, call_id='sdk_mcp_call')], [assistant_message('unreachable')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True, capacity=capacity,
                                  mcp_factory=SimpleNamespace(build=build))

    async def scenario():
        started = asyncio.Event()
        append = repository.append_agent_run_event

        def observe(run_id, event_type, payload=None):
            event = append(run_id, event_type, payload)
            if event_type == 'sdk_tool_hook_started' and payload['tool_name'] == 'lookup':
                started.set()
            return event

        monkeypatch.setattr(repository, 'append_agent_run_event', observe)
        answer = await runtime.run(content='Read MCP evidence', user=USER, thread_id=thread.id, history=[])
        assert answer.waiting_approval
        await capacity.acquire_tool()
        task = asyncio.create_task(runtime.resume(answer.run_id, user=USER, decisions={'sdk_mcp_call': True}))
        try:
            async with asyncio.timeout(10):
                await started.wait()
            current = repository.get_agent_run(answer.run_id)
            repository.save_agent_run(current.model_copy(update={'deadline_at': now_utc() - timedelta(seconds=1)}))
        finally:
            capacity.release_tool()
        async with asyncio.timeout(10):
            with pytest.raises(RuntimeError, match='run_tool_budget_deadline_exceeded'):
                await task
        return repository.get_agent_run(answer.run_id)

    run = asyncio.run(scenario())
    failed = repository.get_agent_run(run.id)
    assert failed.status is AgentRunStatus.FAILED
    assert failed.error_code == 'run_tool_budget_deadline_exceeded'
    assert len(model.calls) == 1 and not provider_calls
    assert capacity.snapshot()['active_tool_calls'] == capacity.snapshot()['active_runs'] == 0
