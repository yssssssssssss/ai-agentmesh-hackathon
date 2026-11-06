from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from agents import Agent, RunConfig, Runner
from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call
from agents.usage import Usage

from agentmesh.agent_runtime.budget import RunModelBudgetLimitsV1, RunModelReservationV1, RunModelUsageV1
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.memory_context.service import MemoryContextService
from agentmesh.models import (
    AgentRun,
    AgentRunStatus,
    AgentToolGrant,
    ChatThread,
    SkillIntent,
    SkillPlan,
    SkillPlanNode,
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
    repository = SQLiteStore(tmp_path / 'run-cost-budget.sqlite3')
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    thread = repository.add_chat_thread(ChatThread(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, title='Explicit model pricing'))
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'off')
    monkeypatch.delenv('AGENTMESH_RUN_MODEL_PRICES_JSON', raising=False)
    monkeypatch.delenv('AGENTMESH_RUN_MODEL_MAX_COST_MICROS', raising=False)
    monkeypatch.delenv('AGENTMESH_RUN_MODEL_COST_CURRENCY', raising=False)
    yield repository, thread
    repository.close()


def test_cost_limit_without_price_mapping_refuses_before_calling_model(project, monkeypatch):
    repository, thread = project
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_MAX_COST_MICROS', '0')
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_COST_CURRENCY', 'USD')
    model = ScriptedModel([[assistant_message('unreachable')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    with pytest.raises(RuntimeError, match='run_model_price_unavailable'):
        runtime.run_sync(content='Price-governed request', user=USER, thread_id=thread.id, history=[])
    assert not model.calls


def _price(currency='USD', **updates):
    return {'currency': currency, 'version': 'test-price-v1',
            'input_micros_per_million_tokens': 1000000,
            'output_micros_per_million_tokens': 2000000, **updates}


def _running_run(repository, thread):
    return repository.save_agent_run(AgentRun(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, thread_id=thread.id, input_text='Priced request', status='running'))


@pytest.mark.parametrize('streamed', [False, True])
def test_price_snapshot_settles_to_reported_token_estimate_and_does_not_drift(project, monkeypatch, streamed):
    repository, thread = project
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_PRICES_JSON', json.dumps({'priced-model': _price()}))
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_COST_CURRENCY', 'USD')
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_MAX_COST_MICROS', '100000')
    run = _running_run(repository, thread)
    model = ScriptedModel([ModelStep(output=[assistant_message('Priced answer')],
        usage=Usage(input_tokens=10, output_tokens=2, total_tokens=12)) for _ in range(2)])

    async def scenario():
        for index in range(2):
            if index:
                monkeypatch.setenv('AGENTMESH_RUN_MODEL_PRICES_JSON', json.dumps({'priced-model': _price(
                    'CNY', version='later-price', input_micros_per_million_tokens=9000000)}))
            guard = MemoryContextService(repository).guard_model_request(model, run=run, model_id='priced-model')
            agent = Agent(name='priced stage', model=guard)
            if streamed:
                result = Runner.run_streamed(agent, f'Question {index}', run_config=RunConfig(tracing_disabled=True))
                async for _ in result.stream_events():
                    pass
            else:
                await Runner.run(agent, f'Question {index}', run_config=RunConfig(tracing_disabled=True))

    asyncio.run(scenario())
    budget = repository.get_run_model_budget(run.id)
    assert budget.cost_currency == 'USD'
    assert budget.estimated_cost_micros == budget.reported_estimated_cost_micros == 28
    assert [r.estimated_cost_micros for r in budget.reservations] == [14, 14]
    assert all(r.price.version == 'test-price-v1' for r in budget.reservations)


@pytest.mark.parametrize('failure', ['missing', 'error', 'cancel'])
def test_attempted_unknown_usage_keeps_cost_reservation(project, monkeypatch, failure):
    repository, thread = project
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_PRICES_JSON', json.dumps({'priced-model': _price()}))
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_COST_CURRENCY', 'USD')
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_MAX_COST_MICROS', '20000')
    run = _running_run(repository, thread)

    async def fail(_call):
        if failure == 'cancel':
            raise asyncio.CancelledError
        raise ConnectionError('attempt interrupted')

    model = ScriptedModel([[assistant_message('Missing usage')] if failure == 'missing' else ModelStep.respond(fail),
                           [assistant_message('unreachable')]])
    guard = MemoryContextService(repository).guard_model_request(model, run=run, model_id='priced-model')

    async def scenario():
        agent = Agent(name='cost bound', model=guard)
        if failure == 'missing':
            await Runner.run(agent, 'Question', run_config=RunConfig(tracing_disabled=True))
        else:
            with pytest.raises(asyncio.CancelledError if failure == 'cancel' else ConnectionError):
                await Runner.run(agent, 'Question', run_config=RunConfig(tracing_disabled=True))
        with pytest.raises(RuntimeError, match='run_model_budget_exhausted'):
            await Runner.run(agent, 'Next question', run_config=RunConfig(tracing_disabled=True))

    asyncio.run(scenario())
    budget = repository.get_run_model_budget(run.id)
    assert len(model.calls) == 1
    assert budget.estimated_cost_micros > 16384
    assert budget.reported_estimated_cost_micros is None
    assert budget.reservations[0].status == 'unknown'


@pytest.mark.parametrize('reason', ['currency', 'expired', 'future'])
def test_unavailable_or_wrong_currency_price_refuses_before_provider(project, monkeypatch, reason):
    repository, thread = project
    updates = {'currency': {'currency': 'CNY'}, 'expired': {'valid_until': '2000-01-01T00:00:00Z'},
               'future': {'valid_from': '2050-01-01T00:00:00Z'}}
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_PRICES_JSON', json.dumps({'ScriptedModel': _price(**updates[reason])}))
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_COST_CURRENCY', 'USD')
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_MAX_COST_MICROS', '100000')
    model = ScriptedModel([[assistant_message('unreachable')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    code = 'run_model_price_currency_mismatch' if reason == 'currency' else 'run_model_price_unavailable'
    with pytest.raises(RuntimeError, match=code):
        runtime.run_sync(content='Explicit currency', user=USER, thread_id=thread.id, history=[])
    assert not model.calls


@pytest.mark.parametrize('prices', [None, {'priced-model': _price('USD')},
                                   {'priced-model': _price('USD', valid_until='2000-01-01T00:00:00Z')}])
def test_price_absence_or_expiry_without_cost_gate_does_not_fabricate_cost(project, monkeypatch, prices):
    repository, thread = project
    if prices is not None:
        monkeypatch.setenv('AGENTMESH_RUN_MODEL_PRICES_JSON', json.dumps(prices))
    run = _running_run(repository, thread)
    model = ScriptedModel([ModelStep(output=[assistant_message('Completed')],
        usage=Usage(input_tokens=10, output_tokens=2, total_tokens=12))])
    guard = MemoryContextService(repository).guard_model_request(model, run=run, model_id='priced-model')
    asyncio.run(Runner.run(Agent(name='optional pricing', model=guard), 'Question', run_config=RunConfig(tracing_disabled=True)))
    budget = repository.get_run_model_budget(run.id)
    if prices is not None and 'valid_until' not in prices['priced-model']:
        assert budget.estimated_cost_micros == 14
    else:
        assert budget.estimated_cost_micros is budget.reported_estimated_cost_micros is None


@pytest.mark.parametrize('invalid', [{'AGENTMESH_RUN_MODEL_MAX_COST_MICROS': '100'},
                                    {'AGENTMESH_RUN_MODEL_COST_CURRENCY': 'USD'},
                                    {'AGENTMESH_RUN_MODEL_MAX_CALLS': ''}])
def test_invalid_cost_or_call_configuration_fails_closed_before_model(project, monkeypatch, invalid):
    repository, thread = project
    for key, value in invalid.items():
        monkeypatch.setenv(key, value)
    model = ScriptedModel([[assistant_message('unreachable')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    with pytest.raises(RuntimeError, match='run_model_budget_configuration_invalid'):
        runtime.run_sync(content='Invalid budget configuration', user=USER, thread_id=thread.id, history=[])
    assert not model.calls


@pytest.mark.parametrize('raw', ['[]', '{', '{"ScriptedModel":null}',
    json.dumps({'ScriptedModel': _price(input_micros_per_million_tokens=-1)}),
    json.dumps({'ScriptedModel': _price(input_micros_per_million_tokens=True)}),
    json.dumps({'ScriptedModel': _price(output_micros_per_million_tokens=1.5)}),
    json.dumps({'ScriptedModel': _price(version='')}),
    json.dumps({'ScriptedModel': _price(currency='usd')}),
    json.dumps({'ScriptedModel': _price(valid_until='2050-01-01T00:00:00')}),
    json.dumps({'ScriptedModel': _price(valid_from='2050-01-02T00:00:00Z', valid_until='2050-01-01T00:00:00Z')}),
    '{"ScriptedModel":' + json.dumps(_price()) + ',"ScriptedModel":' + json.dumps(_price('CNY')) + '}'])
def test_invalid_price_configuration_never_reaches_provider(project, monkeypatch, raw):
    repository, thread = project
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_PRICES_JSON', raw)
    model = ScriptedModel([[assistant_message('unreachable')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    with pytest.raises(RuntimeError, match='run_model_price_configuration_invalid'):
        runtime.run_sync(content='Malformed price policy', user=USER, thread_id=thread.id, history=[])
    assert not model.calls


def _reservation(run, invocation='first'):
    return RunModelReservationV1(invocation_id=invocation, model_id='priced-model', request_hash='a' * 64,
        execution_hash=plan_run_execution_identity(run), input_token_estimate=100, output_token_cap=20)


def _reserve(repository, run, reservation, **limits):
    return repository.reserve_run_model_request(expected_run=run,
        limits=RunModelBudgetLimitsV1(cost_currency='USD', max_cost_micros=140, **limits),
        reservation=reservation, allowed_statuses=frozenset({AgentRunStatus.RUNNING}))


def test_concurrent_cost_reservations_cannot_overspend_one_run(project, monkeypatch):
    repository, thread = project
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_PRICES_JSON', json.dumps({'priced-model': _price()}))
    run = _running_run(repository, thread)

    def reserve(index):
        try:
            _reserve(repository, run, _reservation(run, str(index)))
            return 'reserved'
        except RuntimeError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(reserve, range(2)))
    assert sorted(outcomes) == ['reserved', 'run_model_budget_exhausted']
    assert repository.get_run_model_budget(run.id).estimated_cost_micros == 140


def test_database_reopen_keeps_unknown_cost_and_late_receipt_uses_original_price(project, monkeypatch):
    repository, thread = project
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_PRICES_JSON', json.dumps({'priced-model': _price()}))
    run = _running_run(repository, thread)
    reservation = _reserve(repository, run, _reservation(run))
    assert _reserve(repository, run, reservation) == reservation
    repository.settle_run_model_request(run_id=run.id, invocation_id=reservation.invocation_id, usage=None)
    database = repository.db_path
    repository.close()
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_PRICES_JSON', json.dumps({'priced-model': _price('CNY', version='changed-price')}))
    reopened = SQLiteStore(database)
    try:
        assert reopened.get_run_model_budget(run.id).estimated_cost_micros == 140
        with pytest.raises(RuntimeError, match='run_model_budget_exhausted'):
            _reserve(reopened, run, _reservation(run, 'second'))
        usage = RunModelUsageV1(input_tokens=10, output_tokens=2)
        receipt = reopened.settle_run_model_request(run_id=run.id, invocation_id=reservation.invocation_id, usage=usage)
        assert receipt.estimated_cost_micros == 14 and receipt.price.currency == 'USD'
        assert reopened.settle_run_model_request(run_id=run.id, invocation_id=reservation.invocation_id, usage=usage) == receipt
        assert reopened.get_run_model_budget(run.id).estimated_cost_micros == 14
    finally:
        reopened.close()


def test_cost_estimates_round_each_request_up_without_floating_point(project, monkeypatch):
    repository, thread = project
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_PRICES_JSON', json.dumps({'priced-model': _price(
        input_micros_per_million_tokens=3, output_micros_per_million_tokens=5)}))
    run = _running_run(repository, thread)
    reservation = _reserve(repository, run, _reservation(run))
    assert reservation.estimated_cost_micros == 1
    receipt = repository.settle_run_model_request(run_id=run.id, invocation_id=reservation.invocation_id,
        usage=RunModelUsageV1(input_tokens=1, output_tokens=0))
    assert receipt.estimated_cost_micros == 1


def test_unreported_cost_does_not_gain_a_price_after_configuration_changes(project, monkeypatch):
    repository, thread = project
    run = _running_run(repository, thread)
    model = ScriptedModel([ModelStep(output=[assistant_message('Unpriced answer')],
        usage=Usage(input_tokens=10, output_tokens=2, total_tokens=12)) for _ in range(2)])

    async def scenario():
        for index in range(2):
            if index:
                monkeypatch.setenv('AGENTMESH_RUN_MODEL_PRICES_JSON', json.dumps({'priced-model': _price()}))
            guard = MemoryContextService(repository).guard_model_request(model, run=run, model_id='priced-model')
            await Runner.run(Agent(name='first price policy', model=guard), f'Question {index}',
                run_config=RunConfig(tracing_disabled=True))

    asyncio.run(scenario())
    budget = repository.get_run_model_budget(run.id)
    assert budget.estimated_cost_micros is None
    assert all(r.price is None for r in budget.reservations)


def test_different_currencies_do_not_become_one_reported_amount(project, monkeypatch):
    repository, thread = project
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_PRICES_JSON', json.dumps({'usd-model': _price('USD'), 'cny-model': _price('CNY')}))
    run = _running_run(repository, thread)
    model = ScriptedModel([ModelStep(output=[assistant_message('Known token usage')],
        usage=Usage(input_tokens=10, output_tokens=2, total_tokens=12)) for _ in range(2)])

    async def scenario():
        for model_id in ('usd-model', 'cny-model'):
            guard = MemoryContextService(repository).guard_model_request(model, run=run, model_id=model_id)
            await Runner.run(Agent(name='separate currencies', model=guard), model_id, run_config=RunConfig(tracing_disabled=True))

    asyncio.run(scenario())
    budget = repository.get_run_model_budget(run.id)
    assert [r.estimated_cost_micros for r in budget.reservations] == [14, 14]
    assert budget.cost_currency is budget.estimated_cost_micros is budget.reported_estimated_cost_micros is None


@pytest.mark.parametrize('price_policy,code', [
    (None, 'run_model_price_unavailable'),
    (json.dumps({'ScriptedModel': _price('CNY')}), 'run_model_price_currency_mismatch'),
    ('{', 'run_model_price_configuration_invalid'),
])
def test_failed_plan_preserves_price_reason_instead_of_output_contract(project, monkeypatch,
                                                                     configure_pilot_wiki, tmp_path, price_policy, code):
    repository, thread = project
    monkeypatch.setenv('AGENTMESH_SKILL_ORCHESTRATION', 'execute')
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_COST_CURRENCY', 'USD')
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_MAX_COST_MICROS', '100000')
    if price_policy is not None:
        monkeypatch.setenv('AGENTMESH_RUN_MODEL_PRICES_JSON', price_policy)
    configure_pilot_wiki(tmp_path / 'wiki')
    catalog = SkillCatalogService(repository)
    catalog.reload()
    skill = catalog.get_by_name('prd-feasibility', USER.personal_agent_id)
    profile = repository.get_skill_capability_profile(skill.id)
    repository.save_skill_capability_profile(profile.model_copy(update={'required_capabilities': []}))
    run = repository.save_agent_run(AgentRun(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, thread_id=thread.id, input_text='Price-governed plan',
        status='running', orchestration_mode='execute', writer_generation_epoch=1))
    node = SkillPlanNode(skill_id=skill.id, skill_version=skill.version, skill_content_hash=skill.content_hash,
        reason='Review requirements', required=True, output_contract=['feasibility_review'], side_effect=profile.side_effect)
    plan = repository.save_skill_plan(SkillPlan(run_id=run.id, status='approved',
        intent=SkillIntent(goal=run.input_text), candidate_skill_ids=[skill.id], nodes=[node],
        output_contract=['feasibility_review']))
    repository.save_agent_run(run.model_copy(update={'plan_id': plan.id}))
    model = ScriptedModel([[assistant_message('unreachable')]])
    runtime = AgentRuntimeService(repository, model=model, skill_catalog=catalog, enabled=True)

    async def scenario():
        await runtime.start_approved_skill_plan(plan.id, user=USER)
        async with asyncio.timeout(10):
            while runtime.capacity.snapshot()['active_runs']:
                await asyncio.sleep(0.005)

    asyncio.run(scenario())
    failed = repository.get_agent_run(run.id)
    assert failed.status is AgentRunStatus.FAILED
    assert failed.error_code == code
    assert not model.calls


@pytest.mark.parametrize('streamed', [False, True])
def test_proven_unsent_admission_releases_cost_but_keeps_frozen_price_book(project, monkeypatch, streamed):
    repository, thread = project
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_PRICES_JSON', json.dumps({'priced-model': _price()}))
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_COST_CURRENCY', 'USD')
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_MAX_COST_MICROS', '100000')
    run = _running_run(repository, thread)
    model = ScriptedModel([ModelStep(output=[assistant_message('Current answer')],
        usage=Usage(input_tokens=10, output_tokens=2, total_tokens=12))])

    def refuse():
        assert repository.get_run_model_budget(run.id).estimated_cost_micros > 0
        raise RuntimeError('controlled_admission_refusal')

    async def request(guard):
        agent = Agent(name='unsent admission', model=guard)
        if streamed:
            result = Runner.run_streamed(agent, 'Question', run_config=RunConfig(tracing_disabled=True))
            async for _ in result.stream_events():
                pass
        else:
            await Runner.run(agent, 'Question', run_config=RunConfig(tracing_disabled=True))

    guard = MemoryContextService(repository).guard_model_request(model, run=run, model_id='priced-model', on_handoff=refuse)
    with pytest.raises(RuntimeError, match='controlled_admission_refusal'):
        asyncio.run(request(guard))
    budget = repository.get_run_model_budget(run.id)
    assert not model.calls and not budget.reservations
    assert budget.estimated_cost_micros == 0
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_PRICES_JSON', json.dumps({'priced-model': _price('CNY')}))
    guard = MemoryContextService(repository).guard_model_request(model, run=run, model_id='priced-model')
    asyncio.run(request(guard))
    assert len(model.calls) == 1
    assert repository.get_run_model_budget(run.id).reported_estimated_cost_micros == 14


@pytest.mark.parametrize('streamed', [False, True])
def test_reported_cost_over_cap_is_preserved_and_output_refused(project, monkeypatch, streamed):
    repository, thread = project
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_PRICES_JSON', json.dumps({'priced-model': _price(
        input_micros_per_million_tokens=0, output_micros_per_million_tokens=1000000)}))
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_COST_CURRENCY', 'USD')
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_MAX_COST_MICROS', '8192')
    run = _running_run(repository, thread)
    model = ScriptedModel([ModelStep(output=[assistant_message('Provider exceeded output cap')],
        usage=Usage(input_tokens=10, output_tokens=9000, total_tokens=9010))])
    guard = MemoryContextService(repository).guard_model_request(model, run=run, model_id='priced-model')

    async def scenario():
        agent = Agent(name='reported overspend', model=guard)
        if streamed:
            result = Runner.run_streamed(agent, 'Question', run_config=RunConfig(tracing_disabled=True))
            async for _ in result.stream_events():
                pass
        else:
            await Runner.run(agent, 'Question', run_config=RunConfig(tracing_disabled=True))

    with pytest.raises(RuntimeError, match='run_model_request_usage_exceeded'):
        asyncio.run(scenario())
    budget = repository.get_run_model_budget(run.id)
    assert len(model.calls) == 1 and budget.exhausted
    assert budget.estimated_cost_micros == budget.reported_estimated_cost_micros == 9000
    assert budget.reservations[0].status == 'settled'


def test_queued_request_rechecks_price_expiry_before_actual_model_call(project, monkeypatch):
    repository, thread = project
    capacity = RuntimeCapacityController(llm_limit=1)
    model = ScriptedModel([[assistant_message('unreachable')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True, capacity=capacity)
    expiry = now_utc() + timedelta(seconds=10)
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_PRICES_JSON', json.dumps({'ScriptedModel': _price(
        valid_until=expiry.isoformat())}))
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_COST_CURRENCY', 'USD')
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_MAX_COST_MICROS', '100000')

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
            run = await runtime.start(content='Queued priced question', user=USER, thread_id=thread.id, history=[])
            async with asyncio.timeout(10):
                await admitted.wait()
            assert repository.get_run_model_budget(run.id) is None and not model.calls
            monkeypatch.setattr('agentmesh.agent_runtime.budget.now_utc', lambda: expiry + timedelta(seconds=1))
        async with asyncio.timeout(10):
            while capacity.snapshot()['active_runs']:
                await asyncio.sleep(0.005)
        return run

    run = asyncio.run(scenario())
    assert not model.calls and repository.get_run_model_budget(run.id) is None
    assert repository.get_agent_run(run.id).error_code == 'run_model_price_unavailable'


def test_price_expiry_does_not_reprice_late_receipts_but_blocks_new_requests(project, monkeypatch):
    repository, thread = project
    expiry = now_utc() + timedelta(minutes=10)
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_PRICES_JSON', json.dumps({'priced-model': _price(valid_until=expiry.isoformat())}))
    run = _running_run(repository, thread)
    reservation = _reserve(repository, run, _reservation(run))
    monkeypatch.setattr('agentmesh.agent_runtime.budget.now_utc', lambda: expiry + timedelta(minutes=1))
    receipt = repository.settle_run_model_request(run_id=run.id, invocation_id=reservation.invocation_id,
        usage=RunModelUsageV1(input_tokens=10, output_tokens=2))
    assert receipt.estimated_cost_micros == 14
    assert _reserve(repository, run, _reservation(run)) == receipt
    with pytest.raises(RuntimeError, match='run_model_price_unavailable'):
        _reserve(repository, run, _reservation(run, 'after-expiry'))


def test_approval_resume_keeps_cost_limit_and_reports_budget_reason(project, monkeypatch):
    repository, thread = project
    ensure_tool_seed_data(repository, granted_by='system')
    repository.save_agent_tool_grant(AgentToolGrant(id='grant_priced_approval', agent_id=USER.personal_agent_id,
        tool_id='tool_web_research', granted_by='test'))
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_PRICES_JSON', json.dumps({'ScriptedModel': _price(
        input_micros_per_million_tokens=0, output_micros_per_million_tokens=1000000)}))
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_COST_CURRENCY', 'USD')
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_MAX_COST_MICROS', '8192')
    model = ScriptedModel([[function_call('web_research', {'query': 'Approval'}, call_id='priced_approval')],
                           [assistant_message('unreachable')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    answer = runtime.run_sync(content='Ask for approval', user=USER, thread_id=thread.id, history=[])
    assert repository.get_agent_run(answer.run_id).status is AgentRunStatus.WAITING_APPROVAL
    monkeypatch.setenv('AGENTMESH_RUN_MODEL_MAX_COST_MICROS', '1000000')
    with pytest.raises(RuntimeError, match='run_model_budget_exhausted'):
        runtime.resume_sync(run_id=answer.run_id, user=USER, decisions={'priced_approval': False})
    failed = repository.get_agent_run(answer.run_id)
    assert failed.status is AgentRunStatus.FAILED
    assert failed.error_code == 'run_model_budget_exhausted'
    assert len(model.calls) == 1
    assert repository.get_run_model_budget(failed.id).estimated_cost_micros == 8192
