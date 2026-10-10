from __future__ import annotations

import asyncio

import pytest
from agents.testing import ScriptedModel, assistant_message, function_call

from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.memory_context.contracts import MemoryContextBudgetV1
from agentmesh.memory_context.procedure_context import ProcedureQueryV1
from agentmesh.memory_context.service import MemoryContextError, MemoryContextService
from agentmesh.models import AgentRun, ChatThread, Scope
from agentmesh.seed import TEAM_LEAD, USER
from agentmesh.store import store
from agentmesh.task_management.contracts import TaskCreateRequest, TaskTransitionRequest
from agentmesh.task_management.service import TaskManagementService
from agentmesh.tools import ensure_tool_seed_data
from tests.test_chat_flow import clear_store
from tests.test_memory_governance import _accepted_task_review

GOAL = '检查待审核任务'


@pytest.fixture
def procedure(monkeypatch, request):
    clear_store()
    owner, _, review_id = _accepted_task_review(monkeypatch, 'procedure-context')
    ensure_tool_seed_data(store, granted_by='test')
    goal = getattr(request, 'param', GOAL)
    captured = owner.post(f'/api/task-reviews/{review_id}/memory-candidates', json={
        'command_id': 'capture-procedure-context', 'target': 'personal',
        'title': 'Reviewed inspection method', 'summary': 'Inspect current SQL state.',
        'procedure': {'goal_patterns': [goal], 'preconditions': ['project_member'],
                      'tool_versions': {'project_state': '1'}, 'environment_versions': {'openai-agents': '0.21.1'},
                      'steps': ['读取项目任务状态'], 'validation_conditions': ['独立审核任务状态报告']},
    })
    assert captured.status_code == 201, captured.text
    item = store.get_user_memory_item(captured.json()['item']['id'])
    thread = store.add_chat_thread(ChatThread(id='procedure_thread', user_id=USER.id, workspace_id=USER.workspace_id,
                                              project_id=USER.default_project_id, title='Inspection'))
    run = store.save_agent_run(AgentRun(id='run_procedure_context', thread_id=thread.id, user_id=USER.id,
        workspace_id=USER.workspace_id, project_id=USER.default_project_id,
        input_text=goal if hasattr(request, 'param') else f'{goal}并报告', status='running'))
    return item, run, review_id


@pytest.mark.parametrize('procedure', ['项目状态'], indirect=True)
def test_next_task_receives_current_sql_and_reviewed_method_in_one_sdk_request(procedure, monkeypatch):
    item, _run, _review = procedure
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'inject')
    service = TaskManagementService(store)
    task = service.create_task(TaskCreateRequest(command_id='reuse-method-task', project_id=item.project_id,
                                                title='项目状态', description='项目状态'), USER).task
    for action in ('plan', 'start'):
        task = service.transition_task(task.id, TaskTransitionRequest(command_id='reuse-' + action,
            expected_version=task.management.version, action=action), USER).task
    model = ScriptedModel([[assistant_message('根据当前任务事实，参考已审核方法 [P1]。')]])
    runtime = AgentRuntimeService(store, model=model, enabled=True)

    async def execute():
        run = await runtime.start(content=task.management.description, user=USER, thread_id=task.thread_id,
                                  task_id=task.id, project_id=item.project_id, history=[])
        async with asyncio.timeout(10):
            while store.get_agent_run(run.id).status.value in {'created', 'planning', 'running'}:
                await asyncio.sleep(0.01)
        return store.get_agent_run(run.id)

    completed = asyncio.run(execute())
    assert completed.status.value == 'completed', completed.error_code
    instructions = model.calls[0].system_instructions
    assert '<agentmesh_project_state>' in instructions
    assert '<agentmesh_procedure_context>' in instructions
    assert '读取项目任务状态' in instructions
    receipts = store.list_memory_use_receipts_for_run(completed.id)
    assert len(receipts) == 1 and receipts[0].memory_id == item.id
    assert store.list_runtime_tool_call_history(completed.id) == ([], [])


@pytest.mark.parametrize('procedure', ['项目状态'], indirect=True)
def test_combined_context_does_not_record_method_use_after_sql_state_changes(procedure, monkeypatch):
    item, run, _review = procedure
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'inject')
    run = store.save_agent_run(run.model_copy(update={'project_chat': True}))
    service = MemoryContextService(store)
    bundle = service.assemble_for_run(run=run, user=USER, query=run.input_text).bundle
    assert bundle.project_state_context is not None and bundle.procedure_context is not None
    original = store.commit_memory_use_receipts

    def change_state(**kwargs):
        TaskManagementService(store).create_task(TaskCreateRequest(command_id='changed-sql-state', title='New task'), USER)
        return original(**kwargs)

    monkeypatch.setattr(store, 'commit_memory_use_receipts', change_state)
    with pytest.raises(MemoryContextError, match='project_state_context_changed'):
        service.commit_prepared_for_run(bundle, query=run.input_text, run=run, user=USER,
                                       agent_id=USER.personal_agent_id, reason='combined_context')
    assert store.list_memory_use_receipts_for_run(run.id) == []


@pytest.mark.parametrize('procedure', ['项目状态'], indirect=True)
def test_current_sql_keeps_priority_when_method_does_not_fit_shared_budget(procedure, monkeypatch):
    _item, run, _review = procedure
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'inject')
    run = store.save_agent_run(run.model_copy(update={'project_chat': True}))
    assembled = MemoryContextService(store).assemble_for_run(run=run, user=USER, query=run.input_text,
        budget=MemoryContextBudgetV1(max_total_chars=1800))
    assert assembled.bundle.project_state_context.decision == 'prepared'
    assert assembled.total_chars <= 1800
    assert not assembled.bundle.hits
    assert '读取项目任务状态' not in assembled.rendered_context
    assert store.list_memory_use_receipts_for_run(run.id) == []


def prepare(item, run, *, budget=None):
    return MemoryContextService(store).prepare_procedure_for_run(
        ProcedureQueryV1(memory_id=item.id, memory_record_type='user_memory_item'), query_text=run.input_text,
        run=run, user=USER, agent_id=USER.personal_agent_id, budget=budget,
    )


def test_reviewed_procedure_is_selected_only_for_current_literal_goal_and_commits_exact_receipt(procedure):
    item, run, _ = procedure
    bundle = prepare(item, run)
    assert bundle.procedure_context.decision == 'prepared'
    assert bundle.procedure_context.missing_checks == ()
    assert len(bundle.hits) == 1
    assert item.procedure.steps[0] in bundle.rendered_context
    assert item.procedure.successful_runs[0].run_id in bundle.rendered_context
    assert store.list_memory_use_receipts_for_run(run.id) == []
    committed = MemoryContextService(store).commit_prepared_for_run(bundle, query=run.input_text, run=run, user=USER,
                                                                  agent_id=USER.personal_agent_id, reason='procedure_test')
    assert len(committed.receipt_ids) == 1
    assert committed.procedure_context == bundle.procedure_context
    assert store.list_memory_use_receipts_for_run(run.id)[0].memory_hash == bundle.hits[0].memory_hash


def test_procedure_candidates_recheck_capabilities_without_returning_steps(procedure):
    item, run, _ = procedure
    service = MemoryContextService(store)
    bundle = prepare(item, run)
    service.stage_tool_delivery(bundle, query=run.input_text, output=bundle.rendered_context, run=run, user=USER)
    candidate, = service.candidates_for_run(run, USER)
    assert candidate.state == 'prepared' and candidate.current_available
    assert item.procedure.steps[0] not in candidate.model_dump_json()
    tool = store.get_tool_definition('tool_project_state')
    store.save_tool_definition(tool.model_copy(update={'enabled': False}))
    candidate, = service.candidates_for_run(run, USER)
    assert candidate.state == 'withheld' and candidate.title is None and not candidate.current_available
    assert store.list_memory_use_receipts_for_run(run.id) == []


def test_procedure_policy_change_blocks_steps_and_receipts(procedure):
    from agentmesh.models import AgentMemoryBinding

    item, run, _ = procedure
    binding = store.save_agent_memory_binding(AgentMemoryBinding(
        agent_id=USER.personal_agent_id, allowed_memory_types=[item.memory_type], type_policy_version=1))
    bundle = prepare(item, run)
    assert item.procedure.steps[0] in bundle.rendered_context
    store.save_agent_memory_binding(binding.model_copy(update={'type_policy_version': None}))
    with pytest.raises(MemoryContextError, match='memory_use_binding_changed'):
        prepare(item, run)
    with pytest.raises(MemoryContextError):
        MemoryContextService(store).commit_prepared_for_run(bundle, query=run.input_text, run=run, user=USER,
                                                          agent_id=USER.personal_agent_id, reason='binding_types_test')
    assert store.list_memory_use_receipts_for_run(run.id) == []


@pytest.mark.parametrize(('change', 'code'), [
    ('goal', 'procedure_goal_mismatch'), ('precondition', 'procedure_precondition_unknown'),
    ('required_task', 'procedure_precondition_unsatisfied'), ('grant', 'procedure_tool_unavailable'),
    ('tool_version', 'procedure_tool_version_changed'), ('tool_disabled', 'procedure_tool_unavailable'),
    ('unknown_tool', 'procedure_tool_unavailable'), ('environment', 'procedure_environment_changed'),
    ('external_tool', 'procedure_tool_unverified'),
    ('unknown_environment', 'procedure_environment_unknown'), ('review', 'procedure_evidence_unavailable'),
])
def test_unverifiable_procedures_remain_diagnostics_without_steps_or_receipts(procedure, change, code):
    item, run, review_id = procedure
    payload = item.procedure
    if change == 'goal':
        run = store.save_agent_run(run.model_copy(update={'id': 'mismatched_goal_run', 'input_text': '写一首诗'}))
    elif change == 'precondition':
        payload = payload.model_copy(update={'preconditions': ['请确认系统处于可用状态']})
    elif change == 'required_task':
        payload = payload.model_copy(update={'preconditions': ['task_bound']})
    elif change == 'grant':
        grant = next(grant for grant in store.list_agent_tool_grants(USER.personal_agent_id) if grant.tool_id == 'tool_project_state')
        store.save_agent_tool_grant(grant.model_copy(update={'enabled': False}))
    elif change in {'tool_version', 'tool_disabled'}:
        tool = store.get_tool_definition('tool_project_state')
        store.save_tool_definition(tool.model_copy(update={'implementation_version': 'changed'} if change == 'tool_version'
                                                   else {'enabled': False}))
    elif change == 'unknown_tool':
        payload = payload.model_copy(update={'tool_versions': {'imaginary_tool': '1'}})
    elif change == 'external_tool':
        payload = payload.model_copy(update={'tool_versions': {'data_query': '1'}})
    elif change in {'environment', 'unknown_environment'}:
        payload = payload.model_copy(update={'environment_versions': {'python': '0.0'} if change == 'environment'
                                                  else {'enterprise-prod': 'v1'}})
    else:
        with store._connect() as connection:
            connection.execute("UPDATE task_reviews SET payload = json_set(payload, '$.version', 99) WHERE id = ?", (review_id,))
    if payload != item.procedure:
        item = store.save_user_memory_item(item.model_copy(update={'procedure': payload}))
    bundle = prepare(item, run)
    assert bundle.procedure_context.decision == 'withheld'
    assert code in bundle.procedure_context.missing_checks
    assert bundle.hits == []
    assert '读取项目任务状态' not in bundle.rendered_context
    assert store.list_memory_use_receipts_for_run(run.id) == []


@pytest.mark.parametrize('limit', [700, 1])
def test_procedure_is_all_or_nothing_when_complete_rendering_exceeds_budget(procedure, limit):
    item, run, _ = procedure
    bundle = prepare(item, run, budget=MemoryContextBudgetV1(max_total_chars=limit))
    assert bundle.procedure_context.decision == 'budget_dropped'
    assert not bundle.hits
    assert bundle.total_chars <= limit
    assert '读取项目任务状态' not in bundle.rendered_context
    committed = MemoryContextService(store).commit_prepared_for_run(bundle, query=run.input_text, run=run, user=USER,
        agent_id=USER.personal_agent_id, reason='budget_procedure_test')
    assert committed.receipt_ids == []
    assert committed.total_chars <= limit


def test_procedure_grant_change_in_receipt_transaction_rejects_stale_delivery(procedure, monkeypatch):
    item, run, _ = procedure
    bundle = prepare(item, run)
    original = store.commit_memory_use_receipts

    def revoke_grant(**kwargs):
        grant = next(grant for grant in store.list_agent_tool_grants(USER.personal_agent_id) if grant.tool_id == 'tool_project_state')
        store.save_agent_tool_grant(grant.model_copy(update={'enabled': False}))
        return original(**kwargs)

    monkeypatch.setattr(store, 'commit_memory_use_receipts', revoke_grant)
    with pytest.raises(MemoryContextError, match='memory_procedure_context_changed'):
        MemoryContextService(store).commit_prepared_for_run(bundle, query=run.input_text, run=run, user=USER,
                                                          agent_id=USER.personal_agent_id, reason='procedure_test')
    assert store.list_memory_use_receipts_for_run(run.id) == []


def test_personal_procedure_cannot_be_read_by_peer_or_wrong_scope(procedure):
    item, run, _ = procedure
    peer_run = store.save_agent_run(run.model_copy(update={'id': 'peer_procedure_run', 'user_id': TEAM_LEAD.id}))
    with pytest.raises(MemoryContextError):
        MemoryContextService(store).prepare_procedure_for_run(
            ProcedureQueryV1(memory_id=item.id, memory_record_type='user_memory_item'), query_text=peer_run.input_text,
            run=peer_run, user=TEAM_LEAD, agent_id=TEAM_LEAD.personal_agent_id,
        )
    with pytest.raises(MemoryContextError):
        MemoryContextService(store).prepare_procedure_for_run(
            ProcedureQueryV1(memory_id=item.id, memory_record_type='user_memory_item'), query_text=run.input_text,
            run=run, user=USER, agent_id=USER.personal_agent_id, allowed_scopes={Scope.PROJECT},
        )


def test_actual_sdk_memory_search_delivers_typed_procedure_with_current_scope_and_receipt(procedure):
    item, _, _ = procedure
    model = ScriptedModel([[function_call('memory_search', {'query': GOAL, 'procedure_query': {
        'memory_id': item.id, 'memory_record_type': 'user_memory_item',
    }}, call_id='procedure_search')], [assistant_message('参考已审核经验 [P1]')]])
    runtime = AgentRuntimeService(store, model=model, enabled=True)
    result = runtime.run_sync(content=GOAL, user=USER, thread_id='procedure_sdk_thread', history=[])
    assert len(model.calls) == 2
    assert '读取项目任务状态' in str(model.calls[1].input)
    assert len(store.list_memory_use_receipts_for_run(result.run_id)) == 1
    assert store.get_sdk_session('procedure_sdk_thread').memory_dependencies[0].memory_id == item.id


def test_local_project_runtime_automatically_matches_reviewed_goal_without_executing_steps(procedure, monkeypatch):
    item, run, _ = procedure
    run = store.save_agent_run(run.model_copy(update={'id': 'automatic_procedure_run', 'project_chat': True}))
    model = ScriptedModel([[assistant_message('参考已验收方法 [P1]')]])
    runtime = AgentRuntimeService(store, model=model, enabled=True)
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'inject')
    bundle = runtime._prepare_memory_context_for_run(run=run, user=USER, query=run.input_text)
    assert bundle.procedure_context.memory_id == item.id
    assert bundle.procedure_context.decision == 'prepared'
    assert store.list_memory_use_receipts_for_run(run.id) == []
    result = asyncio.run(runtime._execute_run(run=run, selected=runtime._select_model(USER),
                                             content=run.input_text, user=USER, history=[], skill=None))
    assert result.content == '参考已验收方法 [P1]'
    assert '读取项目任务状态' in model.calls[0].system_instructions
    assert len(store.list_memory_use_receipts_for_run(run.id)) == 1
    assert store.list_runtime_tool_call_history(run.id) == ([], [])


def test_proc_forgetting_redacts_withheld_selection_and_blocks_revival_after_reopen(procedure):
    import sqlite3

    from agentmesh.memory_lifecycle import MemoryForgetRequestV1, MemoryForgettingService
    from agentmesh.store import SQLiteStore

    item, run, _ = procedure
    item = store.save_user_memory_item(item.model_copy(update={'procedure': item.procedure.model_copy(
        update={'preconditions': ['unverified environment']},
    )}))
    bundle = prepare(item, run)
    service = MemoryContextService(store)
    output = {'context': bundle.rendered_context}
    import json
    service.stage_tool_delivery(bundle, output=json.dumps(output), query=run.input_text, run=run, user=USER)
    with store._read_connect() as connection:
        row = connection.execute("SELECT id, payload FROM records WHERE collection = 'memory_tool_deliveries' "
                                 "AND json_extract(payload, '$.run_id') = ?", (run.id,)).fetchone()
    MemoryForgettingService(store).forget(item.id, MemoryForgetRequestV1(command_id='forget-proc', expected_version=item.version), USER)
    with store._read_connect() as connection:
        assert connection.execute("SELECT json_extract(payload, '$.status') FROM records "
                                  "WHERE collection = 'memory_tool_deliveries' AND id = ?", (row['id'],)).fetchone()[0] == 'withdrawn'
    reopened = SQLiteStore(store.db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match='memory_source_withdrawn'), reopened._connect() as connection:
            connection.execute("UPDATE records SET payload = ? WHERE collection = 'memory_tool_deliveries' AND id = ?",
                               (row['payload'], row['id']))
    finally:
        reopened.close()


def test_shared_procedure_requires_independent_memory_review_before_selection(procedure):
    item, run, review_id = procedure
    from tests.test_chat_flow import authenticated_client
    owner = authenticated_client()
    captured = owner.post(f'/api/task-reviews/{review_id}/memory-candidates', json={
        'command_id': 'capture-shared-procedure', 'target': 'team_candidate',
        'title': 'Shared inspection method', 'summary': 'Inspect current SQL state.',
        'facts': [{'subject_type': 'project', 'subject_id': run.project_id, 'predicate': 'constraint',
                   'value': 'Use sealed delivery evidence', 'valid_from': '2026-10-01T00:00:00Z'}],
        'procedure': {name: getattr(item.procedure, name) for name in (
            'goal_patterns', 'preconditions', 'tool_versions', 'environment_versions', 'steps', 'validation_conditions',
        )},
    })
    assert captured.status_code == 201, captured.text
    candidate = captured.json()
    request = ProcedureQueryV1(memory_id=candidate['item']['id'], memory_record_type='memory_item')
    service = MemoryContextService(store)
    with pytest.raises(MemoryContextError):
        service.prepare_procedure_for_run(request, query_text=run.input_text, run=run, user=USER, agent_id=USER.personal_agent_id)
    accepted = authenticated_client(TEAM_LEAD.id).post(
        f"/api/memory-reviews/{candidate['memory_review']['review']['id']}/decisions", json={
            'command_id': 'accept-shared-procedure', 'expected_memory_version': 1, 'expected_review_version': 1,
            'decision': 'accepted',
        },
    )
    assert accepted.status_code == 200, accepted.text
    bundle = service.prepare_procedure_for_run(request, query_text=run.input_text, run=run, user=USER,
                                               agent_id=USER.personal_agent_id)
    assert bundle.procedure_context.decision == 'prepared'
    committed = service.commit_prepared_for_run(bundle, query=run.input_text, run=run, user=USER,
                                                agent_id=USER.personal_agent_id, reason='shared_procedure_test')
    assert committed.hits[0].citation_label == 'T1'
    assert len(committed.receipt_ids) == 1
    from agentmesh.memory_payloads import FactQueryV1
    facts = service.prepare_fact_for_run(
        FactQueryV1(project_id=run.project_id, subject_type='project', subject_id=run.project_id, predicate='constraint'),
        query_text='confirmed constraint', run=run, user=USER, agent_id=USER.personal_agent_id,
    )
    assert facts.fact_context.result.outcome == 'known'
    assert '读取项目任务状态' not in facts.rendered_context
    assert 'Use sealed delivery evidence' in facts.rendered_context
    delivered = service.commit_prepared_for_run(facts, query='confirmed constraint', run=run, user=USER,
                                               agent_id=USER.personal_agent_id, reason='shared_fact_test')
    assert len(delivered.receipt_ids) == 1


def test_sdk_history_rechecks_procedure_grants_even_with_memory_off(procedure):
    from agentmesh.agent_runtime.session import AgentMeshSession
    from agentmesh.store import SDKSessionConflict

    item, _, _ = procedure
    model = ScriptedModel([[function_call('memory_search', {'query': GOAL, 'procedure_query': {
        'memory_id': item.id, 'memory_record_type': 'user_memory_item',
    }}, call_id='procedure_history')], [assistant_message('参考已审核经验 [P1]')]])
    result = AgentRuntimeService(store, model=model, enabled=True).run_sync(
        content=GOAL, user=USER, thread_id='procedure_history_thread', history=[],
    )
    assert len(store.list_memory_use_receipts_for_run(result.run_id)) == 1
    assert any(ref.projection_kind == 'procedure' for ref in store.get_sdk_session('procedure_history_thread').memory_dependencies)
    grant = next(grant for grant in store.list_agent_tool_grants(USER.personal_agent_id) if grant.tool_id == 'tool_project_state')
    store.save_agent_tool_grant(grant.model_copy(update={'enabled': False}))
    run = store.save_agent_run(AgentRun(thread_id='procedure_history_thread', user_id=USER.id,
        workspace_id=USER.workspace_id, project_id=USER.default_project_id, input_text=GOAL, status='running'))
    with pytest.raises(SDKSessionConflict, match='sdk_session_source_changed'):
        asyncio.run(AgentMeshSession(run.thread_id, store, run=run).get_items())
