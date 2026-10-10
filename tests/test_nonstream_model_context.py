from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from agents import Agent, ModelSettings, RunConfig, Runner
from agents.retry import ModelRetryAdvice, ModelRetrySettings
from agents.testing import ScriptedModel, assistant_message

from agentmesh.agent_runtime.model_handoff import model_handoff_gate
from agentmesh.agent_runtime.service import (
    AgentRuntimeService,
    _CapacityBoundModel,
    _guard_nonstream_model,
    _ModelRequirementRefiner,
)
from agentmesh.agent_runtime.settings import SkillOrchestrationMode
from agentmesh.memory_context.request_budget import ContextRequestError, ModelAdmissionError
from agentmesh.memory_context.service import MemoryContextError
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    ChatThread,
    DeepSearchBudgetV1,
    SkillIntent,
    SkillNodeResult,
    SkillOrchestrationRequestMode,
    SkillPlan,
    SkillPlanNode,
    SkillPlanNodeStatus,
    SkillPlanStatus,
    SkillResultSource,
    SkillSynthesisResult,
    Source,
    now_utc,
)
from agentmesh.runtime_capacity import RuntimeCapacityController
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.skill_runtime.planner import SkillIntentAnalyzer
from agentmesh.skill_runtime.synthesis import SkillSynthesisService
from agentmesh.store import SQLiteStore


@pytest.fixture
def stage(tmp_path, monkeypatch):
    repository = SQLiteStore(tmp_path / 'nonstream-model.sqlite3')
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    thread = repository.add_chat_thread(ChatThread(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, title='Nonstream stage'))
    run = repository.save_agent_run(AgentRun(thread_id=thread.id, user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, input_text='Bounded current request', status='planning',
        writer_generation_epoch=1, deadline_at=now_utc() + timedelta(minutes=5)))
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'off')
    yield repository, run
    repository.close()


@pytest.mark.parametrize('phase', [AgentRunStatus.PLANNING, AgentRunStatus.RUNNING])
def test_nonstream_stage_budget_rejects_complete_input_without_provider_calls(stage, phase):
    repository, run = stage
    run = repository.save_agent_run(run.model_copy(update={'status': phase}))
    model = ScriptedModel([[assistant_message('must not be called')]])
    guarded = _guard_nonstream_model(repository=repository, run_id=run.id, model=model,
                                    allowed_statuses=frozenset({phase}))
    with pytest.raises(ContextRequestError, match='context_request_budget_exceeded'):
        asyncio.run(Runner.run(Agent(name='bounded stage', model=guarded), '私有材料' * 9000,
                               run_config=RunConfig(tracing_disabled=True)))
    assert model.calls == ()
    assert isinstance(guarded.failure, ContextRequestError)
    event, = [item for item in repository.list_agent_run_events(run.id) if item.event_type == 'context_request_budget']
    assert '私有材料' not in str(event.payload)


def test_requirement_refinement_is_admitted_before_durable_model_reservation(stage):
    repository, run = stage
    run = repository.save_agent_run(run.model_copy(update={'id': 'requirement_stage_run',
        'planning_mode': AgentPlanningMode.DEEPSEARCH,
        'requested_orchestration_mode': SkillOrchestrationRequestMode.AUTO, 'orchestration_mode': 'execute',
        'deadline_at': None, 'deepsearch_budget': DeepSearchBudgetV1(),
        'absolute_expires_at': run.created_at + timedelta(days=7)}))
    model = ScriptedModel([[assistant_message('must not be called')]])
    refiner = _ModelRequirementRefiner(model, repository, run.id)
    with pytest.raises(ContextRequestError, match='context_request_budget_exceeded'):
        asyncio.run(refiner.refine(previous=None, user_request='私有需求' * 9000, answers={}))
    assert model.calls == ()
    assert repository.get_agent_run(run.id).deepsearch_budget.reservations == []


def test_provider_retry_advice_cannot_repeat_admission_refusal(stage):
    repository, run = stage

    class RetryAllModel(ScriptedModel):
        def get_retry_advice(self, _request):
            return ModelRetryAdvice(suggested=True)

    model = RetryAllModel([])
    guarded = _guard_nonstream_model(repository=repository, run_id=run.id, model=model)
    agent = Agent(name='refused retry', model=guarded, model_settings=ModelSettings(
        retry=ModelRetrySettings(max_retries=2)))
    with pytest.raises(ContextRequestError, match='context_request_budget_exceeded'):
        asyncio.run(Runner.run(agent, '私有材料' * 9000, run_config=RunConfig(tracing_disabled=True)))
    assert not model.calls
    assert len([item for item in repository.list_agent_run_events(run.id)
                if item.event_type == 'context_request_budget']) == 1


@pytest.fixture
def completed_synthesis(stage):
    repository, run = stage
    run = repository.save_agent_run(run.model_copy(update={
        'status': AgentRunStatus.RUNNING, 'plan_id': 'source_delivery_plan'}))
    node = SkillPlanNode(id='delivered_node', skill_id='delivered_skill', skill_version='1',
        skill_content_hash='delivered_hash', reason='already completed', output_contract=['analysis_result'],
        status=SkillPlanNodeStatus.COMPLETED, attempt=1, completed_at=now_utc())
    plan = repository.save_skill_plan(SkillPlan(id=run.plan_id, run_id=run.id, status=SkillPlanStatus.APPROVED,
        intent=SkillIntent(goal=run.input_text), candidate_skill_ids=[node.skill_id],
        output_contract=node.output_contract, nodes=[node]))
    source = repository.add_source(Source(title='Current evidence', source_type='web_page',
        reference='https://example.test/current', workspace_id=run.workspace_id, project_id=run.project_id,
        user_id=run.user_id, run_id=run.id, skill_id=node.skill_id))
    result = repository.save_skill_node_result(plan.id, SkillNodeResult(node_id=node.id, skill_id=node.skill_id,
        summary='Current evidence', attempt=1, sources=[SkillResultSource(**source.model_dump())]))
    return repository, run, plan, source, result


@pytest.mark.parametrize('source_change', ['title', 'source_type', 'reference', 'record_id'])
def test_synthesis_rejects_stale_citation_before_first_model_request(completed_synthesis, source_change):
    repository, run, plan, source, _result = completed_synthesis
    if source_change == 'record_id':
        with repository._connect() as connection:
            connection.execute("UPDATE records SET payload = ? WHERE collection = 'sources' AND id = ?",
                (source.model_copy(update={'id': 'src_foreign'}).model_dump_json(), source.id))
    else:
        repository._upsert('sources', source.model_copy(update={source_change: 'changed private evidence'}))
    model = ScriptedModel([])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)

    with pytest.raises(ModelAdmissionError, match='synthesis_sources_changed'):
        asyncio.run(runtime._execute_approved_skill_plan(plan=plan, run=run, user=USER))

    failed = repository.get_agent_run(run.id)
    assert failed.status is AgentRunStatus.FAILED
    assert failed.error_code == 'synthesis_sources_changed'
    assert failed.output_text is None
    assert repository.get_skill_plan(plan.id).synthesis is None
    assert not model.calls


@pytest.mark.parametrize('change', ['deleted', 'title', 'reference', 'skill_id', 'owner_disabled'])
def test_synthesis_withholds_provider_result_after_source_or_owner_changes(completed_synthesis, change):
    repository, run, plan, source, result = completed_synthesis
    output = SkillSynthesisResult(summary='Current evidence', claims=[{
        'text': 'Current evidence', 'node_result_ids': [result.id], 'source_ids': [source.id]}])

    class MutatingModel(ScriptedModel):
        async def get_response(self, *args, **kwargs):
            response = await super().get_response(*args, **kwargs)
            if change == 'owner_disabled':
                repository.save_user(USER.model_copy(update={'status': 'disabled'}))
            elif change == 'deleted':
                with repository._connect() as connection:
                    connection.execute("DELETE FROM records WHERE collection = 'sources' AND id = ?", (source.id,))
            else:
                repository._upsert('sources', source.model_copy(update={change: 'changed private evidence'}))
            return response

    model = MutatingModel([[assistant_message(output.model_dump_json())]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    with pytest.raises(MemoryContextError, match='synthesis_sources_changed'):
        asyncio.run(runtime._execute_approved_skill_plan(plan=plan, run=run, user=USER))

    failed = repository.get_agent_run(run.id)
    assert failed.status is AgentRunStatus.FAILED
    assert failed.error_code == 'synthesis_sources_changed'
    assert failed.output_text is None
    assert repository.get_skill_plan(plan.id).synthesis is None
    assert len(model.calls) == 1
    assert not any(item.event_type == 'synthesis_completed' for item in repository.list_agent_run_events(run.id))


def test_synthesis_delivers_unchanged_authorized_source(completed_synthesis):
    repository, run, plan, source, result = completed_synthesis
    output = SkillSynthesisResult(summary='Current evidence', claims=[{
        'text': 'Current evidence', 'node_result_ids': [result.id], 'source_ids': [source.id]}])
    model = ScriptedModel([[assistant_message(output.model_dump_json())]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)

    outcome = asyncio.run(runtime._execute_approved_skill_plan(plan=plan, run=run, user=USER))

    assert outcome.run.status is AgentRunStatus.COMPLETED
    assert outcome.synthesis.summary == 'Current evidence'
    assert repository.get_skill_plan(plan.id).synthesis['claims'][0]['source_ids'] == [source.id]
    assert len(model.calls) == 1


@pytest.mark.parametrize('consumer', ['intent', 'synthesis'])
def test_rejected_authority_is_not_schema_fallback_or_repair(stage, consumer):
    repository, run = stage
    phase = AgentRunStatus.PLANNING if consumer == 'intent' else AgentRunStatus.RUNNING
    repository.save_agent_run(run.model_copy(update={'status': phase}))
    model = ScriptedModel([[assistant_message('must not be called')]])
    guarded = _guard_nonstream_model(repository=repository, run_id=run.id, model=model,
                                    allowed_statuses=frozenset({phase}))
    repository.save_user(USER.model_copy(update={'status': 'disabled'}))
    with pytest.raises(MemoryContextError, match='model_handoff_not_authorized'):
        if consumer == 'intent':
            asyncio.run(SkillIntentAnalyzer().analyze(run.input_text, model=guarded))
        else:
            asyncio.run(SkillSynthesisService().synthesize(model=guarded, output_contract=[], results=[], degradation=None))
    assert model.calls == ()
    assert len([item for item in repository.list_agent_run_events(run.id)
                if item.event_type == 'context_request_budget']) == 1


def test_synthesis_budget_refusal_is_not_repaired_or_silently_downgraded(stage):
    repository, run = stage
    repository.save_agent_run(run.model_copy(update={'status': AgentRunStatus.RUNNING}))
    model = ScriptedModel([[assistant_message('must not be called')]])
    guarded = _guard_nonstream_model(repository=repository, run_id=run.id, model=model,
                                    allowed_statuses=frozenset({AgentRunStatus.RUNNING}))
    with pytest.raises(ContextRequestError, match='context_request_budget_exceeded'):
        asyncio.run(SkillSynthesisService().synthesize(model=guarded, output_contract=[], results=[],
                                                     degradation='Source-derived limitation. ' * 4000))
    assert model.calls == ()
    assert len([item for item in repository.list_agent_run_events(run.id)
                if item.event_type == 'context_request_budget']) == 1


def test_synthesis_admits_valid_structured_output_and_clamps_output(stage):
    repository, run = stage
    repository.save_agent_run(run.model_copy(update={'status': AgentRunStatus.RUNNING}))
    expected = SkillSynthesisResult(summary='Bounded synthesis')
    model = ScriptedModel([[assistant_message(expected.model_dump_json())]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    guarded = _guard_nonstream_model(repository=repository, run_id=run.id, model=runtime._select_model(USER).model,
                                    allowed_statuses=frozenset({AgentRunStatus.RUNNING}))
    result, fallback = asyncio.run(SkillSynthesisService().synthesize(
        model=guarded, output_contract=[], results=[], degradation=None))
    assert result.summary == expected.summary and not fallback
    assert model.first_call.model_settings.max_tokens == 4096
    assert model_handoff_gate.get() is None


def test_waiting_nonstream_requests_have_independent_gates_and_restore_context(stage):
    repository, run = stage
    other = repository.save_agent_run(run.model_copy(update={'id': 'other_stage_run'}))
    bad_model = ScriptedModel([[assistant_message('must not be called')]])
    good_model = ScriptedModel([[assistant_message('other valid result')]])

    async def scenario():
        capacity = RuntimeCapacityController(llm_limit=1)
        queued = asyncio.Event()

        class WaitingCapacity:
            waiting = 0

            @asynccontextmanager
            async def llm_slot(self):
                self.waiting += 1
                if self.waiting == 2:
                    queued.set()
                async with capacity.llm_slot():
                    yield

        waiting_capacity = WaitingCapacity()
        bad = _guard_nonstream_model(repository=repository, run_id=run.id,
                                    model=_CapacityBoundModel(bad_model, waiting_capacity))
        good = _guard_nonstream_model(repository=repository, run_id=other.id,
                                     model=_CapacityBoundModel(good_model, waiting_capacity))
        async with capacity.llm_slot():
            bad_task = asyncio.create_task(Runner.run(Agent(name='bad', model=bad), 'first',
                                                     run_config=RunConfig(tracing_disabled=True)))
            good_task = asyncio.create_task(Runner.run(Agent(name='good', model=good), 'second',
                                                      run_config=RunConfig(tracing_disabled=True)))
            await asyncio.wait_for(queued.wait(), timeout=5)
            repository.save_agent_run(run.model_copy(update={'status': AgentRunStatus.CANCELLED}))
        results = await asyncio.gather(bad_task, good_task, return_exceptions=True)
        assert isinstance(results[0], MemoryContextError)
        assert results[1].final_output == 'other valid result'
        assert model_handoff_gate.get() is None

    asyncio.run(scenario())
    assert bad_model.calls == () and len(good_model.calls) == 1


@pytest.mark.parametrize('universal', [False, True])
def test_orchestrated_intent_rechecks_queued_authority_without_fallback(stage, monkeypatch, universal):
    repository, run = stage
    repository.save_agent_run(run.model_copy(update={'status': AgentRunStatus.CANCELLED}))
    monkeypatch.setenv('AGENTMESH_TASK_SCENARIO_ROUTING', 'false')
    model = ScriptedModel([])

    async def scenario():
        queued = asyncio.Event()

        class WaitingCapacity(RuntimeCapacityController):
            @asynccontextmanager
            async def llm_slot(self):
                queued.set()
                async with super().llm_slot():
                    yield

        capacity = WaitingCapacity(llm_limit=1)
        runtime = AgentRuntimeService(repository, model=model, enabled=True,
            universal_preview_enabled=universal, capacity=capacity)
        async with capacity.llm_slot():
            queued.clear()
            started = await runtime.start_orchestrated(content='Analyze this product', user=USER, thread_id=run.thread_id,
                history=[], client_turn_id='queued_intent', mode=SkillOrchestrationMode.PREVIEW)
            task = runtime._tasks[started.id]
            await asyncio.wait_for(queued.wait(), timeout=5)
            repository.save_user(USER.model_copy(update={'status': 'disabled'}))
        with pytest.raises(MemoryContextError, match='model_handoff_not_authorized'):
            await task
        return repository.get_agent_run(started.id)

    failed = asyncio.run(scenario())
    assert failed.status is AgentRunStatus.FAILED
    assert failed.error_code == 'model_handoff_not_authorized'
    assert repository.get_skill_plan_for_run(failed.id) is None
    assert len([event for event in repository.list_agent_run_events(failed.id)
                if event.event_type == 'context_request_budget']) == 1
    assert not model.calls


@pytest.mark.parametrize('streamed', [False, True])
def test_sdk_cancellation_while_waiting_restores_gate_and_releases_capacity(stage, streamed):
    repository, run = stage
    model = ScriptedModel([[assistant_message('must not be called')]])

    async def scenario():
        capacity = RuntimeCapacityController(llm_limit=1)
        queued = asyncio.Event()

        class WaitingCapacity:
            @asynccontextmanager
            async def llm_slot(self):
                queued.set()
                async with capacity.llm_slot():
                    yield

        guarded = _guard_nonstream_model(repository=repository, run_id=run.id,
            model=_CapacityBoundModel(model, WaitingCapacity()))
        agent = Agent(name='cancelled stage', model=guarded)
        async with capacity.llm_slot():
            if streamed:
                result = Runner.run_streamed(agent, 'cancelled request', run_config=RunConfig(tracing_disabled=True))
            else:
                task = asyncio.create_task(Runner.run(agent, 'cancelled request',
                    run_config=RunConfig(tracing_disabled=True)))
            await asyncio.wait_for(queued.wait(), timeout=5)
            if streamed:
                result.cancel(mode='immediate')
                async for _event in result.stream_events():
                    pass
            else:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
        assert model_handoff_gate.get() is None
        assert isinstance(guarded.failure, asyncio.CancelledError)
        async with asyncio.timeout(1), capacity.llm_slot():
            pass

    asyncio.run(scenario())
    assert not model.calls


@pytest.mark.parametrize('source_change', ['deleted', 'title', 'source_type', 'reference', 'skill_id'])
def test_actual_synthesis_rechecks_sources_after_capacity_wait_without_fallback(stage, source_change):
    repository, run = stage
    run = repository.save_agent_run(run.model_copy(update={
        'status': AgentRunStatus.RUNNING, 'plan_id': 'queued_synthesis_plan'}))
    node = SkillPlanNode(id='completed_node', skill_id='completed_skill', skill_version='1',
        skill_content_hash='completed_hash', reason='already completed', output_contract=['analysis_result'],
        status=SkillPlanNodeStatus.COMPLETED, attempt=1, completed_at=now_utc())
    plan = repository.save_skill_plan(SkillPlan(id=run.plan_id, run_id=run.id, status=SkillPlanStatus.APPROVED,
        intent=SkillIntent(goal=run.input_text), candidate_skill_ids=[node.skill_id],
        output_contract=node.output_contract, nodes=[node]))
    source = repository.add_source(Source(title='Current evidence', source_type='web_page',
        reference='https://example.test/current', workspace_id=run.workspace_id, project_id=run.project_id,
        user_id=run.user_id, run_id=run.id))
    repository.save_skill_node_result(plan.id, SkillNodeResult(node_id=node.id, skill_id=node.skill_id,
        summary='Current evidence', attempt=1, sources=[SkillResultSource(**source.model_dump())]))
    model = ScriptedModel([[assistant_message(SkillSynthesisResult(summary='must not be called').model_dump_json())]])

    async def scenario():
        capacity = RuntimeCapacityController(llm_limit=1)
        runtime = AgentRuntimeService(repository, model=model, enabled=True, capacity=capacity)
        async with capacity.llm_slot():
            pending = asyncio.create_task(runtime._execute_approved_skill_plan(plan=plan, run=run, user=USER))
            async with asyncio.timeout(5):
                while not any(item.event_type == 'context_request_budget'
                              for item in repository.list_agent_run_events(run.id)):
                    await asyncio.sleep(0.005)
            assert not model.calls
            if source_change == 'deleted':
                with repository._connect() as connection:
                    connection.execute("DELETE FROM records WHERE collection = 'sources' AND id = ?", (source.id,))
            else:
                repository._upsert('sources', source.model_copy(update={source_change: 'changed private evidence'}))
        with pytest.raises(MemoryContextError, match='synthesis_sources_changed'):
            await pending
        assert model_handoff_gate.get() is None

    asyncio.run(scenario())
    failed = repository.get_agent_run(run.id)
    assert failed.status is AgentRunStatus.FAILED
    assert failed.error_code == 'synthesis_sources_changed'
    assert repository.get_skill_plan(plan.id).synthesis is None
    assert not model.calls
    assert len([item for item in repository.list_agent_run_events(run.id)
                if item.event_type == 'context_request_budget']) == 1
