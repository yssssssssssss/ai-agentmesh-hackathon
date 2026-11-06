from __future__ import annotations

import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from agents import Agent, RunConfig, Runner
from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call
from agents.usage import Usage

from agentmesh.agent_runtime.budget import RunModelBudgetLimitsV1, RunModelReservationV1, RunModelUsageV1
from agentmesh.agent_runtime.model_factory import selected_model_from_env
from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.memory_context.service import MemoryContextService
from agentmesh.models import (
    AgentRun,
    AgentRunStatus,
    AgentToolGrant,
    ChatMessage,
    ChatThread,
    SkillIntent,
    SkillPlan,
    SkillPlanNode,
    SkillPlanNodeStatus,
    UserMemoryItem,
    now_utc,
)
from agentmesh.runtime_capacity import RuntimeCapacityController
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.skill_runtime.sources import plan_run_execution_identity
from agentmesh.store import SQLiteStore
from agentmesh.tools import ensure_tool_seed_data


@pytest.fixture
def project(tmp_path, monkeypatch):
    repository = SQLiteStore(tmp_path / 'run-model-budget.sqlite3')
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    ensure_tool_seed_data(repository, granted_by='system')
    thread = repository.add_chat_thread(ChatThread(
        user_id=USER.id, workspace_id=USER.workspace_id, project_id=USER.default_project_id,
        title='Cumulative ordinary model usage',
    ))
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'off')
    yield repository, thread
    repository.close()


def test_approval_resume_shares_original_run_model_call_budget(project, monkeypatch):
    repository, thread = project
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_MAX_CALLS', '1')
    repository.save_agent_tool_grant(AgentToolGrant(
        id='grant_budget_web', agent_id=USER.personal_agent_id,
        tool_id='tool_web_research', granted_by='test',
    ))
    model = ScriptedModel([
        [function_call('web_research', {'query': 'Approval'}, call_id='budget_approval')],
        [assistant_message('must not bypass the original budget')],
    ])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    answer = runtime.run_sync(content='Ask for approval', user=USER, thread_id=thread.id, history=[])
    run = repository.get_agent_run(answer.run_id)
    assert run.status is AgentRunStatus.WAITING_APPROVAL
    with pytest.raises(RuntimeError, match='run_model_budget_exhausted'):
        runtime.resume_sync(run_id=run.id, user=USER, decisions={'budget_approval': False})
    assert len(model.calls) == 1
    assert repository.get_agent_run(run.id).status is AgentRunStatus.FAILED


def _running_run(repository, thread, *, planned=False):
    return repository.save_agent_run(AgentRun(
        user_id=USER.id, workspace_id=USER.workspace_id, project_id=USER.default_project_id,
        thread_id=thread.id, input_text='Bounded local execution', status='running', writer_generation_epoch=1,
        orchestration_mode='execute' if planned else 'off',
    ))


@pytest.mark.parametrize('streamed', [False, True])
def test_reported_usage_releases_unused_reservation_and_limits_survive_new_guards(project, monkeypatch, streamed):
    repository, thread = project
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_MAX_CALLS', '2')
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_MAX_OUTPUT_TOKENS', '8194')
    run = _running_run(repository, thread)
    model = ScriptedModel([ModelStep(output=[assistant_message('bounded answer')],
                                    usage=Usage(input_tokens=10, output_tokens=2, total_tokens=12)) for _ in range(3)])

    async def scenario():
        for index in range(3):
            monkeypatch.setenv('AGENTMESH_RUN_MODEL_MAX_CALLS', '100')
            if index == 0:
                monkeypatch.setenv('AGENTMESH_RUN_MODEL_MAX_CALLS', '2')
            guard = MemoryContextService(repository).guard_model_request(model, run=run, model_id='bounded')
            agent = Agent(name='ordinary stage', model=guard)
            if streamed:
                result = Runner.run_streamed(agent, f'Question {index}', run_config=RunConfig(tracing_disabled=True))
                async for _ in result.stream_events():
                    pass
            else:
                await Runner.run(agent, f'Question {index}', run_config=RunConfig(tracing_disabled=True))

    with pytest.raises(RuntimeError, match='run_model_budget_exhausted'):
        asyncio.run(scenario())
    budget = repository.get_run_model_budget(run.id)
    assert len(model.calls) == 2
    assert budget.limits.max_calls == 2
    assert budget.total_tokens == 24 and budget.output_tokens == 4
    assert all(r.status == 'settled' for r in budget.reservations)


@pytest.mark.parametrize('dimension', ['MAX_TOKENS', 'MAX_OUTPUT_TOKENS'])
def test_unknown_usage_keeps_reservation_and_blocks_further_work(project, monkeypatch, dimension):
    repository, thread = project
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_' + dimension, '10000' if dimension == 'MAX_TOKENS' else '8192')
    run = _running_run(repository, thread)
    model = ScriptedModel([ModelStep(output=[assistant_message('Usage cannot be verified')],
                                    usage=Usage(input_tokens=10, output_tokens=2, total_tokens=99)),
                           [assistant_message('unreachable')]])
    guard = MemoryContextService(repository).guard_model_request(model, run=run, model_id='unknown-usage')

    async def scenario():
        agent = Agent(name='ordinary stage', model=guard)
        await Runner.run(agent, 'Question one', run_config=RunConfig(tracing_disabled=True))
        await Runner.run(agent, 'Question two', run_config=RunConfig(tracing_disabled=True))

    with pytest.raises(RuntimeError, match='run_model_budget_exhausted'):
        asyncio.run(scenario())
    reservation, = repository.get_run_model_budget(run.id).reservations
    assert reservation.status == 'unknown' and reservation.usage is None
    assert len(model.calls) == 1
    assert repository.get_run_model_budget(run.id).output_tokens == 8192


def _reservation(run, invocation='first'):
    return RunModelReservationV1(invocation_id=invocation, request_hash='a' * 64,
        execution_hash=plan_run_execution_identity(run), model_id='bounded',
        input_token_estimate=100, output_token_cap=20)


def test_concurrent_model_reservations_cannot_oversubscribe_one_run(project):
    repository, thread = project
    run = _running_run(repository, thread)

    def reserve(index):
        try:
            repository.reserve_run_model_request(expected_run=run, limits=RunModelBudgetLimitsV1(max_calls=1),
                reservation=_reservation(run, str(index)), allowed_statuses=frozenset({AgentRunStatus.RUNNING}))
            return 'reserved'
        except RuntimeError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(reserve, range(2)))
    assert sorted(outcomes) == ['reserved', 'run_model_budget_exhausted']
    assert len(repository.get_run_model_budget(run.id).reservations) == 1


def test_budget_store_rejects_pre_settled_new_reservations(project):
    repository, thread = project
    run = _running_run(repository, thread)
    reservation = _reservation(run).model_copy(update={'status': 'settled', 'usage': RunModelUsageV1(
        input_tokens=0, output_tokens=0)})
    with pytest.raises(RuntimeError, match='run_model_budget_request_invalid'):
        repository.reserve_run_model_request(expected_run=run, limits=RunModelBudgetLimitsV1(),
            reservation=reservation, allowed_statuses=frozenset({AgentRunStatus.RUNNING}))
    assert repository.get_run_model_budget(run.id) is None


def test_session_compaction_spends_the_same_run_call_budget(project, monkeypatch):
    repository, thread = project
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_MAX_CALLS', '1')
    history = [ChatMessage(thread_id=thread.id, user_id=USER.id, role='user' if i % 2 == 0 else 'assistant',
                           content=f'Historical item {i}: ' + 'x' * 2200) for i in range(30)]
    for message in history:
        repository.add_chat_message(message)
    model = ScriptedModel([[assistant_message('Previous decisions')], [assistant_message('unreachable')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    with pytest.raises(RuntimeError, match='run_model_budget_exhausted'):
        runtime.run_sync(content='Continue', user=USER, thread_id=thread.id, history=history)
    assert len(model.calls) == 1


def test_configured_sdk_client_has_no_unmetered_http_retries(monkeypatch):
    monkeypatch.setenv('AI_API_URL', 'https://model.invalid/v1')
    monkeypatch.setenv('AI_API_KEY', 'test-only-not-a-real-key')
    monkeypatch.setenv('AI_MODEL', 'bounded-model')
    monkeypatch.setenv('AI_API_STYLE', 'chat_completions')
    selected = selected_model_from_env('default')
    try:
        assert selected.client.max_retries == 0
    finally:
        asyncio.run(selected.client.close())


@pytest.mark.parametrize('phase', ['nodes', 'retry'])
def test_plan_nodes_and_physical_stream_retries_share_run_budget(project, monkeypatch, configure_pilot_wiki, tmp_path, phase):
    repository, thread = project
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_MAX_CALLS', '1')
    monkeypatch.setenv('AGENTMESH_SKILL_ORCHESTRATION', 'execute')
    configure_pilot_wiki(tmp_path / 'wiki')
    catalog = SkillCatalogService(repository)
    catalog.reload()
    skill = catalog.get_by_name('prd-feasibility', USER.personal_agent_id)
    profile = repository.get_skill_capability_profile(skill.id)
    repository.save_skill_capability_profile(profile.model_copy(update={'required_capabilities': ['research.request']}))
    repository.save_agent_tool_grant(AgentToolGrant(id='grant_plan_budget_web', agent_id=USER.personal_agent_id,
        tool_id='tool_web_research', granted_by='test'))
    run = _running_run(repository, thread, planned=True)
    nodes = [SkillPlanNode(id=f'budget_node_{i}', skill_id=skill.id, skill_version=skill.version,
        skill_content_hash=skill.content_hash, reason='Review requirements', required=True,
        output_contract=['feasibility_review'], side_effect=profile.side_effect,
        depends_on=['budget_node_0'] if i else []) for i in range(2 if phase == 'nodes' else 1)]
    plan = repository.save_skill_plan(SkillPlan(run_id=run.id, status='approved',
        intent=SkillIntent(goal=run.input_text), candidate_skill_ids=[skill.id], nodes=nodes,
        output_contract=['feasibility_review']))
    repository.save_agent_run(run.model_copy(update={'plan_id': plan.id}))
    first = [assistant_message(json.dumps({'node_id': nodes[0].id, 'skill_id': skill.id, 'summary': 'Committed review'}))]
    model = ScriptedModel([first if phase == 'nodes' else ModelStep.raise_error(ConnectionError('interrupted')),
                           [assistant_message('unreachable')]])
    capacity = RuntimeCapacityController()
    runtime = AgentRuntimeService(repository, model=model, skill_catalog=catalog, capacity=capacity, enabled=True)

    async def scenario():
        await runtime.start_approved_skill_plan(plan.id, user=USER)
        async with asyncio.timeout(10):
            while capacity.snapshot()['active_runs']:
                await asyncio.sleep(0.005)

    asyncio.run(scenario())
    assert len(model.calls) == 1
    assert repository.get_agent_run(run.id).status is AgentRunStatus.FAILED
    assert repository.get_agent_run(run.id).error_code == 'run_model_budget_exhausted'
    budget = repository.get_run_model_budget(run.id)
    assert len(budget.reservations) == 1
    if phase == 'nodes':
        assert repository.get_skill_plan(plan.id).nodes[0].status is SkillPlanNodeStatus.COMPLETED
        assert len(repository.list_skill_node_results(plan.id)) == 1
    else:
        assert budget.reservations[0].status == 'unknown'
    assert capacity.snapshot()['active_llm_calls'] == capacity.snapshot()['active_runs'] == 0


def test_provider_output_usage_over_cap_is_recorded_and_rejected(project):
    repository, thread = project
    run = _running_run(repository, thread)
    model = ScriptedModel([ModelStep(output=[assistant_message('Provider ignored the cap')],
                                    usage=Usage(input_tokens=10, output_tokens=9000, total_tokens=9010))])
    guard = MemoryContextService(repository).guard_model_request(model, run=run, model_id='over-cap')
    with pytest.raises(RuntimeError, match='run_model_request_usage_exceeded'):
        asyncio.run(Runner.run(Agent(name='bounded output', model=guard), 'Question',
                               run_config=RunConfig(tracing_disabled=True)))
    budget = repository.get_run_model_budget(run.id)
    assert budget.total_tokens == 9010 and budget.output_tokens == 9000
    assert budget.reservations[0].status == 'settled'


def test_budget_refusal_does_not_claim_new_memory_was_delivered(project, monkeypatch):
    repository, thread = project
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_MAX_CALLS', '1')
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'inject')
    run = _running_run(repository, thread)
    item = repository.add_user_memory_item(UserMemoryItem(id='later_budget_memory', user_id=USER.id,
        workspace_id=USER.workspace_id, project_id=USER.default_project_id, title='Later evidence',
        summary='Read later evidence: Confirmed team constraints.', source_kind='manual', layer='mid_term'))
    service = MemoryContextService(repository)
    bundle = service.prepare_for_run('later evidence', run=run, user=USER, agent_id=USER.personal_agent_id)
    assert [hit.memory_id for hit in bundle.hits] == [item.id]
    context = AgentMeshRunContext(user_id=USER.id, workspace_id=run.workspace_id, project_id=run.project_id,
                                 thread_id=run.thread_id, run_id=run.id)
    snapshot_id = service.stage_run_snapshot(run=run, user=USER, context=context, input_text=run.input_text,
        query='later evidence', additional_instructions=bundle.rendered_context, bundle=bundle,
        core_preferences=None, reason='automatic_run_context')
    repository.reserve_run_model_request(expected_run=run, limits=RunModelBudgetLimitsV1(max_calls=1),
        reservation=_reservation(run), allowed_statuses=frozenset({AgentRunStatus.RUNNING}))
    model = ScriptedModel([[assistant_message('unreachable')]])
    guard = service.guard_model_request(model, run=run, model_id='bounded', context_snapshot_id=snapshot_id)
    with pytest.raises(RuntimeError, match='run_model_budget_exhausted'):
        asyncio.run(Runner.run(Agent(name='bounded evidence', model=guard, instructions=bundle.rendered_context),
                               run.input_text, run_config=RunConfig(tracing_disabled=True)))
    assert repository.list_memory_use_receipts_for_run(run.id) == []
    assert not model.calls


def test_budget_reopen_preserves_unknown_usage_and_receipts_replay_without_refunding(project):
    repository, thread = project
    run = _running_run(repository, thread)
    reservation = _reservation(run)
    limits = RunModelBudgetLimitsV1(max_calls=1)
    arguments = dict(expected_run=run, limits=limits, reservation=reservation,
                     allowed_statuses=frozenset({AgentRunStatus.RUNNING}))
    assert repository.reserve_run_model_request(**arguments) == reservation
    assert repository.reserve_run_model_request(**arguments) == reservation
    with pytest.raises(RuntimeError, match='run_model_budget_invocation_conflict'):
        repository.reserve_run_model_request(**{**arguments, 'reservation': reservation.model_copy(update={'model_id': 'other'})})
    repository.settle_run_model_request(run_id=run.id, invocation_id=reservation.invocation_id, usage=None)
    database = repository.db_path
    repository.close()
    reopened = SQLiteStore(database)
    try:
        assert reopened.get_run_model_budget(run.id).total_tokens == 120
        assert reopened.get_run_model_budget(run.id).reservations[0].status == 'unknown'
        with pytest.raises(RuntimeError, match='run_model_budget_exhausted'):
            reopened.reserve_run_model_request(**{**arguments, 'reservation': _reservation(run, 'second')})
        usage = RunModelUsageV1(input_tokens=10, output_tokens=2)
        receipt = reopened.settle_run_model_request(run_id=run.id, invocation_id=reservation.invocation_id, usage=usage)
        assert reopened.settle_run_model_request(run_id=run.id, invocation_id=reservation.invocation_id, usage=usage) == receipt
        with pytest.raises(RuntimeError, match='run_model_budget_settlement_conflict'):
            reopened.settle_run_model_request(run_id=run.id, invocation_id=reservation.invocation_id, usage=None)
        assert reopened.get_run_model_budget(run.id).total_tokens == 12
    finally:
        reopened.close()


@pytest.mark.parametrize('change', ['writer', 'terminal', 'deadline'])
def test_actual_reservation_rejects_stale_or_expired_run(project, change):
    repository, thread = project
    run = _running_run(repository, thread)
    updates = {'writer': {'writer_generation_epoch': 2}, 'terminal': {'status': AgentRunStatus.FAILED},
               'deadline': {'deadline_at': now_utc() - timedelta(seconds=1)}}
    replaced = repository.save_agent_run(run.model_copy(update=updates[change]))
    with pytest.raises(RuntimeError, match='run_model_budget_(execution_changed|deadline_exceeded)'):
        repository.reserve_run_model_request(expected_run=run, limits=RunModelBudgetLimitsV1(),
            reservation=_reservation(run), allowed_statuses=frozenset({AgentRunStatus.RUNNING}))
    assert repository.get_agent_run(run.id) == replaced
    assert repository.get_run_model_budget(run.id) is None


@pytest.mark.parametrize('phase', ['reserve', 'settle'])
def test_budget_and_safe_event_commit_atomically_and_can_retry(project, phase):
    repository, thread = project
    run = _running_run(repository, thread)
    reservation = _reservation(run)
    arguments = dict(expected_run=run, limits=RunModelBudgetLimitsV1(), reservation=reservation,
                     allowed_statuses=frozenset({AgentRunStatus.RUNNING}))
    if phase == 'settle':
        repository.reserve_run_model_request(**arguments)
    before = repository.get_run_model_budget(run.id)
    events = repository.list_agent_run_events(run.id)
    with repository._connect() as connection:
        connection.execute("""CREATE TRIGGER refuse_budget_event BEFORE INSERT ON agent_run_events
            WHEN json_extract(NEW.payload, '$.event_type') = 'run_model_budget'
            BEGIN SELECT RAISE(ABORT, 'controlled_budget_event_failure'); END""")

    def commit():
        if phase == 'reserve':
            repository.reserve_run_model_request(**arguments)
        else:
            repository.settle_run_model_request(run_id=run.id, invocation_id=reservation.invocation_id,
                                                usage=RunModelUsageV1(input_tokens=10, output_tokens=2))

    with pytest.raises(sqlite3.IntegrityError, match='controlled_budget_event_failure'):
        commit()
    assert repository.get_run_model_budget(run.id) == before
    assert repository.list_agent_run_events(run.id) == events
    with repository._connect() as connection:
        connection.execute('DROP TRIGGER refuse_budget_event')
    commit()
    assert repository.get_run_model_budget(run.id) is not None


def test_late_reported_usage_settles_original_receipt_without_changing_new_writer(project):
    repository, thread = project
    run = _running_run(repository, thread)
    reservation = _reservation(run)
    repository.reserve_run_model_request(expected_run=run, limits=RunModelBudgetLimitsV1(),
        reservation=reservation, allowed_statuses=frozenset({AgentRunStatus.RUNNING}))
    replaced = repository.save_agent_run(run.model_copy(update={'writer_generation_epoch': 2}))
    repository.settle_run_model_request(run_id=run.id, invocation_id=reservation.invocation_id,
                                        usage=RunModelUsageV1(input_tokens=10, output_tokens=2))
    assert repository.get_agent_run(run.id) == replaced
    assert repository.get_run_model_budget(run.id).total_tokens == 12


def test_identical_physical_model_requests_have_durable_retry_limit(project, monkeypatch):
    repository, thread = project
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_MAX_REQUEST_ATTEMPTS', '2')
    run = _running_run(repository, thread)
    model = ScriptedModel([[assistant_message('answer')] for _ in range(3)])
    guard = MemoryContextService(repository).guard_model_request(model, run=run, model_id='bounded')

    async def scenario():
        for _ in range(3):
            await Runner.run(Agent(name='retry limit', model=guard), 'Identical request',
                             run_config=RunConfig(tracing_disabled=True))

    with pytest.raises(RuntimeError, match='run_model_budget_retry_exhausted'):
        asyncio.run(scenario())
    assert len(model.calls) == 2
    assert len(repository.get_run_model_budget(run.id).reservations) == 2


@pytest.mark.parametrize('change', ['unchanged', 'revoked'])
def test_queue_wait_does_not_reserve_model_usage_and_rechecks_owner(project, monkeypatch, change):
    repository, thread = project
    capacity = RuntimeCapacityController(llm_limit=1)
    model = ScriptedModel([[assistant_message('Current owner answer')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True, capacity=capacity)

    async def scenario():
        admitted = asyncio.Event()
        append = repository.append_agent_run_event

        def observe(run_id, event_type, payload=None):
            event = append(run_id, event_type, payload)
            if event_type == 'context_request_budget':
                admitted.set()
            return event

        monkeypatch.setattr(repository, 'append_agent_run_event', observe)
        async with capacity.llm_slot():
            run = await runtime.start(content='Current owner question', user=USER, thread_id=thread.id, history=[])
            async with asyncio.timeout(10):
                await admitted.wait()
            assert repository.get_run_model_budget(run.id) is None
            assert not model.calls
            if change == 'revoked':
                repository.save_user(USER.model_copy(update={'status': 'disabled'}))
        async with asyncio.timeout(10):
            while capacity.snapshot()['active_runs']:
                await asyncio.sleep(0.005)
        return run

    run = asyncio.run(scenario())
    if change == 'revoked':
        assert repository.get_run_model_budget(run.id) is None
        assert not model.calls
        assert repository.get_agent_run(run.id).status is AgentRunStatus.FAILED
    else:
        assert len(repository.get_run_model_budget(run.id).reservations) == len(model.calls) == 1
        assert repository.get_agent_run(run.id).output_text == 'Current owner answer'


@pytest.mark.parametrize('streamed', [False, True])
def test_sdk_zero_default_usage_is_unknown_and_keeps_reserved_tokens(project, streamed):
    repository, thread = project
    run = _running_run(repository, thread)
    model = ScriptedModel([[assistant_message('Completed without verified usage')]])
    guard = MemoryContextService(repository).guard_model_request(model, run=run, model_id='missing-usage')

    async def scenario():
        agent = Agent(name='unknown usage', model=guard)
        if streamed:
            result = Runner.run_streamed(agent, 'Question', run_config=RunConfig(tracing_disabled=True))
            async for _ in result.stream_events():
                pass
        else:
            await Runner.run(agent, 'Question', run_config=RunConfig(tracing_disabled=True))

    asyncio.run(scenario())
    budget = repository.get_run_model_budget(run.id)
    assert budget.reservations[0].status == 'unknown'
    assert budget.total_tokens > 8192
