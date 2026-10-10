from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from agents.testing import ScriptedModel, assistant_message, function_call

from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.memory_context.service import MemoryContextError, MemoryContextService
from agentmesh.memory_facts import MemoryFactsService, document_evidence_hash
from agentmesh.memory_payloads import FactAssertionV1, FactQueryV1, FactRememberV1
from agentmesh.models import (
    AgentRun,
    AgentRunStatus,
    ChatThread,
    DocumentRecord,
    Project,
    Source,
    User,
    Workspace,
)
from agentmesh.store import SQLiteStore

NOW = datetime(2026, 10, 4, 1, 30, tzinfo=UTC)


@pytest.fixture
def facts(tmp_path):
    repository = SQLiteStore(tmp_path / 'fact-context.sqlite3')
    repository.save_workspace(Workspace(id='ws_facts', name='Facts', description='Facts'))
    owner = repository.save_user(User(id='owner_facts', workspace_id='ws_facts', default_project_id='project_facts',
                                     name='Owner', role='user', personal_agent_id='agent_facts'))
    repository.save_project(Project(id='project_facts', workspace_id=owner.workspace_id, name='Facts project',
                                    goal='Deliver', member_ids=[owner.id]))
    thread = repository.add_chat_thread(ChatThread(user_id=owner.id, workspace_id=owner.workspace_id,
                                                   project_id=owner.default_project_id, title='Facts'))
    run = repository.save_agent_run(AgentRun(thread_id=thread.id, user_id=owner.id, workspace_id=owner.workspace_id,
                                            project_id=owner.default_project_id, project_chat=True,
                                            input_text='这个项目的负责人是谁？', status=AgentRunStatus.RUNNING))
    document = repository.add_document(DocumentRecord(
        id='fact_context_document', title='Assignments', file_name='assignments.txt', content_type='text/plain',
        text='Alice owned the project in September. Bob owns it in October. Charlie disputes the assignment.',
        source=Source(id='fact_context_source', title='Assignments', source_type='document', reference='upload://assignments'),
        workspace_id=owner.workspace_id, project_id=run.project_id, uploaded_by=owner.id,
    ))
    service = MemoryFactsService(repository, clock=lambda: NOW)

    def remember(value='Bob', *, command='fact-owner', start='2026-10-01T00:00:00+00:00', end=None):
        return service.remember(FactRememberV1(
            command_id=command, title='Assignment facts', summary='Human-confirmed assignments.',
            project_id=run.project_id, source_document_id=document.id, source_version=document.version,
            source_hash=document_evidence_hash(document), facts=[FactAssertionV1(
                subject_type='project', subject_id=run.project_id, predicate='owner', value=value,
                valid_from=start, valid_to=end,
            )],
        ), owner)

    yield repository, owner, run, document, remember
    repository.close()


def test_current_project_fact_question_uses_structured_evidence_at_model_handoff(facts, monkeypatch):
    repository, owner, run, _, remember = facts
    item = remember()
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'inject')
    model = ScriptedModel([[assistant_message('Bob [P1]')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    asyncio.run(runtime._execute_run(run=run, selected=runtime._select_model(owner), content=run.input_text,
                                    user=owner, history=[], skill=None))
    assert '"predicate":"owner"' in model.first_call.system_instructions
    assert '"value":"Bob"' in model.first_call.system_instructions
    assert document_evidence_hash(repository.get_document('fact_context_document')) in model.first_call.system_instructions
    receipts = repository.list_memory_use_receipts_for_run(run.id)
    assert [receipt.memory_id for receipt in receipts] == [item.id]
    assert receipts[0].citation_label == 'P1'
    candidate, = MemoryContextService(repository).candidates_for_run(repository.get_agent_run(run.id), owner)
    assert candidate.state == 'delivered' and candidate.current_available and candidate.title == item.title
    assert 'Bob' not in candidate.model_dump_json()
    remember('Charlie', command='conflict-after-delivery')
    candidate, = MemoryContextService(repository).candidates_for_run(repository.get_agent_run(run.id), owner)
    assert candidate.state == 'delivered' and not candidate.current_available and candidate.title is None


@pytest.mark.parametrize('outcome', ['unknown', 'conflict'])
def test_fact_context_reports_missing_or_conflicting_evidence_without_using_it(facts, monkeypatch, outcome):
    repository, owner, run, _, remember = facts
    if outcome == 'conflict':
        remember()
        remember('Charlie', command='conflicting-owner')
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'inject')
    model = ScriptedModel([[assistant_message('需要确认负责人。')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    asyncio.run(runtime._execute_run(run=run, selected=runtime._select_model(owner), content=run.input_text,
                                    user=owner, history=[], skill=None))
    assert f'"outcome":"{outcome}"' in model.first_call.system_instructions
    assert '"value":"Bob"' not in model.first_call.system_instructions
    assert repository.list_memory_use_receipts_for_run(run.id) == []


@pytest.mark.parametrize('change', ['source_version', 'new_conflict'])
def test_prepared_fact_context_is_rechecked_before_actual_model_handoff(facts, monkeypatch, change):
    repository, owner, run, document, remember = facts
    remember()
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'inject')
    model = ScriptedModel([[assistant_message('unreachable')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    original_streamed = runtime._run_streamed

    async def change_before_sdk(*args, **kwargs):
        if change == 'source_version':
            repository.save_document(document.model_copy(update={'version': 2, 'text': 'Changed assignments.'}))
        else:
            remember('Charlie', command='new-conflict')
        return await original_streamed(*args, **kwargs)

    monkeypatch.setattr(runtime, '_run_streamed', change_before_sdk)
    with pytest.raises(MemoryContextError):
        asyncio.run(runtime._execute_run(run=run, selected=runtime._select_model(owner), content=run.input_text,
                                        user=owner, history=[], skill=None))
    assert not model.calls
    assert repository.list_memory_use_receipts_for_run(run.id) == []


@pytest.mark.parametrize('scoped', [False, True])
def test_explicit_fact_query_tool_delivers_historical_fact_with_exact_version_receipt(facts, monkeypatch, scoped):
    from agentmesh.models import AgentToolGrant
    from agentmesh.tools import ensure_tool_seed_data

    repository, owner, run, _, remember = facts
    past = remember('Alice', start='2026-09-01T00:00:00+00:00', end='2026-10-01T00:00:00+00:00')
    remember(command='current-owner')
    ensure_tool_seed_data(repository, granted_by='test')
    repository.save_agent_tool_grant(AgentToolGrant(agent_id=owner.personal_agent_id,
                                                    tool_id='tool_memory_search', granted_by='test'))
    query = FactQueryV1(project_id=run.project_id, subject_type='project', subject_id=run.project_id,
                        predicate='owner', as_of='2026-09-15T00:00:00+00:00')
    arguments = query.model_dump(mode='json', exclude={'project_id', 'subject_id'} if scoped else set())
    model = ScriptedModel([[function_call('memory_search', {'query': 'September owner',
                                                            'fact_query': arguments}, call_id='historical-fact')],
                           [assistant_message('Alice [P1]')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'off')
    asyncio.run(runtime._execute_run(run=run, selected=runtime._select_model(owner), content=run.input_text,
                                    user=owner, history=[], skill=None))
    assert 'Alice' in str(model.calls[1].input)
    assert '"value":"Bob"' not in str(model.calls[1].input)
    receipts = repository.list_memory_use_receipts_for_run(run.id)
    assert [receipt.memory_id for receipt in receipts] == [past.id]


def test_explicit_fact_context_cannot_select_another_project(facts):
    repository, owner, run, _, remember = facts
    remember()
    query = FactQueryV1(project_id='other_project', subject_type='project', subject_id='other_project', predicate='owner')
    with pytest.raises(MemoryContextError, match='memory_context_project_mismatch'):
        MemoryContextService(repository).prepare_fact_for_run(
            query, query_text='owner', run=run, user=owner, agent_id=owner.personal_agent_id,
        )


def test_fact_conflict_inserted_at_receipt_commit_is_caught_in_the_same_transaction(facts, monkeypatch):
    repository, owner, run, _, remember = facts
    remember()
    service = MemoryContextService(repository)
    bundle = service.prepare_fact_for_run(
        FactQueryV1(project_id=run.project_id, subject_type='project', subject_id=run.project_id, predicate='owner'),
        query_text='owner', run=run, user=owner, agent_id=owner.personal_agent_id,
    )
    original = repository.commit_memory_use_receipts

    def insert_conflict(**kwargs):
        remember('Charlie', command='commit-conflict')
        return original(**kwargs)

    monkeypatch.setattr(repository, 'commit_memory_use_receipts', insert_conflict)
    with pytest.raises(MemoryContextError, match='memory_fact_context_changed'):
        service.commit_prepared_for_run(bundle, query='owner', run=run, user=owner,
                                        agent_id=owner.personal_agent_id, reason='automatic_run_context')
    assert repository.list_memory_use_receipts_for_run(run.id) == []


def test_agent_binding_filters_facts_before_conflict_detection(facts):
    from agentmesh.models import AgentMemoryBinding, MemoryItem, MemoryStatus, Scope

    repository, owner, run, _, remember = facts
    personal = remember()
    repository.add_memory_item(MemoryItem(
        id='team_conflicting_fact', title='Team assignment', summary='Conflicting team assignment.',
        memory_type='fact', scope=Scope.TEAM_ACCEPTED, status=MemoryStatus.ACCEPTED,
        owner_user_id=owner.id, workspace_id=owner.workspace_id, project_id=run.project_id,
        sources=personal.sources, facts=[personal.facts[0].model_copy(update={'value': 'Charlie'})],
    ))
    repository.save_agent_memory_binding(AgentMemoryBinding(agent_id=owner.personal_agent_id, allowed_scopes=[Scope.PRIVATE]))
    service = MemoryContextService(repository)
    bundle = service.prepare_fact_for_run(
        FactQueryV1(project_id=run.project_id, subject_type='project', subject_id=run.project_id, predicate='owner'),
        query_text='owner', run=run, user=owner, agent_id=owner.personal_agent_id,
    )
    assert bundle.fact_context.result.outcome == 'known'
    assert [hit.memory_id for hit in bundle.hits] == [personal.id]
    assert 'Charlie' not in bundle.rendered_context


@pytest.mark.parametrize('version', [1, None])
def test_fact_context_requires_confirmed_content_type_policy(facts, version):
    from agentmesh.models import AgentMemoryBinding

    repository, owner, run, _, remember = facts
    item = remember()
    repository.save_agent_memory_binding(AgentMemoryBinding(
        agent_id=owner.personal_agent_id, allowed_memory_types=[item.memory_type], type_policy_version=version))
    bundle = MemoryContextService(repository).prepare_fact_for_run(
        FactQueryV1(project_id=run.project_id, subject_type='project', subject_id=run.project_id, predicate='owner'),
        query_text='owner', run=run, user=owner, agent_id=owner.personal_agent_id)
    assert bundle.fact_context.result.outcome == ('known' if version == 1 else 'unknown')
    assert [hit.memory_id for hit in bundle.hits] == ([item.id] if version == 1 else [])
    if version is None:
        assert 'Bob' not in bundle.rendered_context


def test_fact_policy_change_blocks_prepared_delivery_and_candidate_metadata(facts):
    from agentmesh.models import AgentMemoryBinding

    repository, owner, run, _, remember = facts
    item = remember()
    binding = repository.save_agent_memory_binding(AgentMemoryBinding(
        agent_id=owner.personal_agent_id, allowed_memory_types=[item.memory_type], type_policy_version=1))
    service = MemoryContextService(repository)
    bundle = service.prepare_fact_for_run(
        FactQueryV1(project_id=run.project_id, subject_type='project', subject_id=run.project_id, predicate='owner'),
        query_text='owner', run=run, user=owner, agent_id=owner.personal_agent_id)
    service.stage_tool_delivery(bundle, query='owner', output=bundle.rendered_context, run=run, user=owner)
    repository.save_agent_memory_binding(binding.model_copy(update={'type_policy_version': None}))
    candidate, = service.candidates_for_run(run, owner)
    assert not candidate.current_available and candidate.title is None
    with pytest.raises(MemoryContextError):
        service.commit_prepared_for_run(bundle, query='owner', run=run, user=owner,
                                       agent_id=owner.personal_agent_id, reason='binding_types_test')
    assert repository.list_memory_use_receipts_for_run(run.id) == []


def test_fact_groups_exceeding_budget_are_withheld_without_truncating_assertions(facts):
    from agentmesh.memory_context.contracts import MemoryContextBudgetV1

    repository, owner, run, _, remember = facts
    remember('Bob' * 600)
    service = MemoryContextService(repository)
    bundle = service.prepare_fact_for_run(
        FactQueryV1(project_id=run.project_id, subject_type='project', subject_id=run.project_id, predicate='owner'),
        query_text='owner', run=run, user=owner, agent_id=owner.personal_agent_id,
        budget=MemoryContextBudgetV1(max_total_chars=1200),
    )
    assert bundle.fact_context.decision == 'budget_dropped'
    assert bundle.hits == []
    assert 'Bob' not in bundle.rendered_context
    assert bundle.total_chars <= 1200
    assert repository.list_memory_use_receipts_for_run(run.id) == []


def test_forgetting_redacts_withheld_fact_candidates_and_blocks_their_late_snapshot_restore(facts):
    import sqlite3

    from agentmesh.agent_runtime.models import AgentMeshRunContext
    from agentmesh.memory_lifecycle import MemoryForgetRequestV1, MemoryForgettingService

    repository, owner, run, _, remember = facts
    forgotten = remember()
    remember('Charlie', command='conflict-before-forget')
    service = MemoryContextService(repository)
    bundle = service.prepare_fact_for_run(
        FactQueryV1(project_id=run.project_id, subject_type='project', subject_id=run.project_id, predicate='owner'),
        query_text='owner', run=run, user=owner, agent_id=owner.personal_agent_id,
    )
    assert bundle.hits == [] and bundle.fact_context.result.outcome == 'conflict'
    snapshot_id = service.stage_run_snapshot(
        run=run, user=owner, context=AgentMeshRunContext(user_id=owner.id, workspace_id=run.workspace_id,
                                                       project_id=run.project_id, thread_id=run.thread_id, run_id=run.id),
        input_text=run.input_text, query='owner', additional_instructions=bundle.rendered_context,
        bundle=bundle, core_preferences=None, reason='automatic_run_context',
    )
    frozen = service.load_run_snapshot(snapshot_id, run=run)
    service.stage_tool_delivery(bundle, query='owner', output=bundle.rendered_context, run=run, user=owner)
    MemoryForgettingService(repository).forget(forgotten.id, MemoryForgetRequestV1(
        command_id='forget-withheld', expected_version=1,
    ), owner)
    reopened = SQLiteStore(repository.db_path)
    try:
        with reopened._read_connect() as connection:
            rows = connection.execute("SELECT payload FROM records WHERE collection IN "
                                      "('run_context_snapshots', 'memory_tool_deliveries')").fetchall()
        assert all('Bob' not in row['payload'] for row in rows)
        with pytest.raises(MemoryContextError, match='memory_use_source_changed'):
            MemoryContextService(reopened).load_run_snapshot(snapshot_id, run=run)
        with pytest.raises(sqlite3.IntegrityError, match='memory_source_withdrawn|context_snapshot_immutable'):
            reopened._upsert('run_context_snapshots', frozen)
        with pytest.raises(sqlite3.IntegrityError, match='memory_source_withdrawn'):
            MemoryContextService(reopened).stage_tool_delivery(bundle, query='owner', output=bundle.rendered_context,
                                                               run=run, user=owner)
    finally:
        reopened.close()


@pytest.mark.parametrize('question', ['调查项目负责人职责', '这个项目的负责人在九月是谁？', '谁负责另外一个项目？'])
def test_unstructured_or_historical_questions_do_not_get_guessed_current_fact_routes(facts, question):
    _, _, run, _, _ = facts
    assert MemoryContextService.project_fact_query(question, run=run) is None


def test_fact_selection_from_mixed_payload_never_injects_procedure_steps(facts, monkeypatch):
    from agentmesh.memory_payloads import ProcedureMemoryV1

    repository, owner, run, _, remember = facts
    item = remember()
    repository.save_user_memory_item(item.model_copy(update={'procedure': ProcedureMemoryV1(
        goal_patterns=['Unconfirmed procedure'], steps=['UNCONFIRMED_PROCEDURE_STEP'],
        validation_conditions=['Needs human verification'],
    )}))
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'inject')
    model = ScriptedModel([[assistant_message('Bob [P1]')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    asyncio.run(runtime._execute_run(run=run, selected=runtime._select_model(owner), content=run.input_text,
                                    user=owner, history=[], skill=None))
    assert '"value":"Bob"' in model.first_call.system_instructions
    assert 'UNCONFIRMED_PROCEDURE_STEP' not in model.first_call.system_instructions
    assert [receipt.memory_id for receipt in repository.list_memory_use_receipts_for_run(run.id)] == [item.id]


def test_cancelled_run_cannot_deliver_unknown_fact_context_or_preferences(facts, monkeypatch):
    repository, owner, run, _, _ = facts
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'inject')
    model = ScriptedModel([[assistant_message('unreachable')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    original_streamed = runtime._run_streamed

    async def cancel_before_sdk(*args, **kwargs):
        repository.save_agent_run(run.model_copy(update={'status': AgentRunStatus.CANCELLED}))
        return await original_streamed(*args, **kwargs)

    monkeypatch.setattr(runtime, '_run_streamed', cancel_before_sdk)
    with pytest.raises(PermissionError, match='sdk_session_run_inactive'):
        asyncio.run(runtime._execute_run(run=run, selected=runtime._select_model(owner), content=run.input_text,
                                        user=owner, history=[], skill=None))
    assert not model.calls
    assert repository.list_memory_use_receipts_for_run(run.id) == []
