from __future__ import annotations

import asyncio
import json

import pytest
from agents.testing import ScriptedModel, assistant_message, function_call

from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.memory_context.service import MemoryContextError, MemoryContextService
from agentmesh.models import (
    AgentRun,
    AgentRunStatus,
    AgentToolGrant,
    ChatThread,
    ChatThreadKind,
    Intent,
    Project,
    Task,
    TaskDeliveryStage,
    TaskManagementMetadataV1,
    TaskReviewV1,
    User,
    Workspace,
    now_utc,
)
from agentmesh.store import SQLiteStore
from agentmesh.task_management.contracts import TaskTransitionRequest
from agentmesh.task_management.service import TaskManagementService


@pytest.fixture
def project_state(tmp_path):
    repository = SQLiteStore(tmp_path / 'project-state.sqlite3')
    repository.save_workspace(Workspace(id='ws_state', name='State', description='State'))
    owner = repository.save_user(User(id='owner_state', workspace_id='ws_state', default_project_id='project_state',
                                     name='Owner', role='team_lead', personal_agent_id='agent_state'))
    repository.save_project(Project(id='project_state', workspace_id=owner.workspace_id, name='State', goal='Ship',
                                    member_ids=[owner.id]))
    thread = repository.add_chat_thread(ChatThread(user_id=owner.id, workspace_id=owner.workspace_id,
                                                   project_id=owner.default_project_id, title='Project query'))
    run = repository.save_agent_run(AgentRun(thread_id=thread.id, user_id=owner.id, workspace_id=owner.workspace_id,
                                            project_id=owner.default_project_id, project_chat=True,
                                            input_text='这个项目完成了多少任务？', status=AgentRunStatus.RUNNING))

    def task(task_id, *, stage=TaskDeliveryStage.BACKLOG, dependencies=(), kind=ChatThreadKind.TASK,
             project_id=run.project_id, archived=False, title=None):
        thread = repository.add_chat_thread(ChatThread(user_id=owner.id, workspace_id=owner.workspace_id,
                                                       project_id=project_id, kind=kind, title='Work'))
        return repository.add_task(Task(
            id=task_id, thread_id=thread.id, intent=Intent.REQUEST_EXTERNAL_RESEARCH, title=title or task_id,
            management=TaskManagementMetadataV1(delivery_stage=stage, dependency_task_ids=list(dependencies),
                created_by=owner.id, updated_by=owner.id, archived_at=now_utc() if archived else None),
        ))

    yield repository, owner, run, task
    repository.close()


def test_sql_counts_exclude_private_foreign_and_archived_tasks(project_state):
    from agentmesh.task_operations.contracts import ProjectStateQueryV1
    from agentmesh.task_operations.state import ProjectStateService

    repository, owner, run, task = project_state
    task('done', stage=TaskDeliveryStage.DONE)
    task('backlog')
    task('private', stage=TaskDeliveryStage.DONE, kind=ChatThreadKind.CONVERSATION)
    task('foreign', stage=TaskDeliveryStage.DONE, project_id='project_elsewhere')
    task('archived', stage=TaskDeliveryStage.DONE, archived=True)
    result = ProjectStateService(repository).query(ProjectStateQueryV1(project_id=run.project_id), owner)
    assert result.outcome == 'known'
    assert result.task_count == 2
    assert result.tasks_by_stage[TaskDeliveryStage.DONE] == 1
    assert result.archived_task_count == 1
    assert result.task_watermark.record_count == 3
    assert repository.memory_use_receipts == []


def test_dependency_query_reports_unavailable_targets_without_exposing_them(project_state):
    from agentmesh.task_operations.contracts import ProjectStateQueryV1
    from agentmesh.task_operations.state import ProjectStateService

    repository, owner, run, task = project_state
    task('complete', stage=TaskDeliveryStage.DONE)
    task('waiting')
    task('secret', kind=ChatThreadKind.CONVERSATION, title='PRIVATE BODY')
    task('foreign', project_id='other-project', title='FOREIGN BODY')
    task('archive', archived=True, title='ARCHIVED BODY')
    root = task('root', stage=TaskDeliveryStage.IN_PROGRESS,
                dependencies=('complete', 'waiting', 'secret', 'foreign', 'archive', 'missing'))
    result = ProjectStateService(repository).query(ProjectStateQueryV1(project_id=run.project_id, task_id=root.id), owner)
    assert result.outcome == 'insufficient_evidence'
    assert [item.id for item in result.dependencies] == ['complete', 'waiting']
    assert result.completed_dependency_count == 1
    assert result.blocking_task_ids == ('waiting',)
    assert result.unavailable_dependency_count == 4
    assert result.execution_ready is False
    rendered = result.model_dump_json()
    assert all(text not in rendered for text in ['PRIVATE BODY', 'FOREIGN BODY', 'ARCHIVED BODY'])


def test_current_task_with_active_run_is_not_execution_ready(project_state):
    from agentmesh.task_operations.contracts import ProjectStateQueryV1
    from agentmesh.task_operations.state import ProjectStateService

    repository, owner, run, task = project_state
    item = task('already-running', stage=TaskDeliveryStage.IN_PROGRESS)
    repository.save_agent_run(AgentRun(
        id='active-task-run', thread_id=item.thread_id, task_id=item.id, user_id=owner.id,
        workspace_id=run.workspace_id, project_id=run.project_id, input_text='Active delivery',
        status=AgentRunStatus.RUNNING,
    ))
    result = ProjectStateService(repository).query(ProjectStateQueryV1(project_id=run.project_id, task_id=item.id), owner)
    assert result.execution_ready is False
    assert result.active_run_count == 1


def test_review_counts_only_join_current_shared_active_tasks(project_state):
    from agentmesh.task_operations.contracts import ProjectStateQueryV1
    from agentmesh.task_operations.state import ProjectStateService

    repository, owner, run, task = project_state
    for identifier, options in [('shared', {}), ('private', {'kind': ChatThreadKind.CONVERSATION}),
                                ('foreign', {'project_id': 'other-project'}), ('archive', {'archived': True})]:
        item = task(identifier, **options)
        review = TaskReviewV1(
            id='review-' + identifier, task_id=item.id, run_id='delivery-' + identifier,
            artifact_ids=['artifact-' + identifier], artifact_hashes=['a' * 64], round=1,
            requested_by=owner.id, reviewer_id=owner.id, task_version=1,
        )
        repository.save_agent_run(AgentRun(
            id=review.run_id, thread_id=item.thread_id, user_id=owner.id, workspace_id=run.workspace_id,
            project_id=run.project_id, input_text='Fixture reviewed delivery', status=AgentRunStatus.COMPLETED,
        ))
        with repository._connect() as connection:
            connection.execute(
                'INSERT INTO task_reviews(id, task_id, run_id, reviewer_id, status, round, version, '
                'payload, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (review.id, review.task_id, review.run_id, review.reviewer_id, review.status.value, review.round,
                 review.version, review.model_dump_json(), review.created_at.isoformat(), review.updated_at.isoformat()),
            )
    result = ProjectStateService(repository).query(ProjectStateQueryV1(project_id=run.project_id), owner)
    assert result.reviews_by_status['pending'] == 1
    assert result.review_watermark.record_count == 1


@pytest.mark.parametrize('change', ['membership', 'owner_disabled', 'project_inactive'])
def test_project_state_uses_current_database_authority(project_state, change):
    from agentmesh.task_operations.contracts import ProjectStateQueryV1
    from agentmesh.task_operations.service import TaskOperationsError
    from agentmesh.task_operations.state import ProjectStateService

    repository, owner, run, _ = project_state
    if change == 'membership':
        project = repository.get_project(run.project_id)
        project.member_ids = ['someone_else']
        repository.save_project(project)
    elif change == 'owner_disabled':
        repository.save_user(owner.model_copy(update={'status': 'disabled'}))
    else:
        project = repository.get_project(run.project_id)
        repository.save_project(project.model_copy(update={'status': 'archived'}))
    with pytest.raises(TaskOperationsError, match='project_not_found'):
        ProjectStateService(repository).query(ProjectStateQueryV1(project_id=run.project_id), owner)


def test_current_project_count_question_reaches_sdk_with_sql_result(project_state, monkeypatch):
    repository, owner, run, task = project_state
    task('done', stage=TaskDeliveryStage.DONE)
    task('working', stage=TaskDeliveryStage.IN_PROGRESS)
    task('private', stage=TaskDeliveryStage.DONE, kind=ChatThreadKind.CONVERSATION)
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'inject')
    model = ScriptedModel([[assistant_message('完成 1 项，共 2 项。')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    asyncio.run(runtime._execute_run(run=run, selected=runtime._select_model(owner), content=run.input_text,
                                    user=owner, history=[], skill=None))
    instructions = model.first_call.system_instructions
    assert '<agentmesh_project_state>' in instructions
    assert '"done":1' in instructions and '"task_count":2' in instructions
    assert repository.list_memory_use_receipts_for_run(run.id) == []


def test_state_changed_after_preparation_stops_handoff(project_state, monkeypatch):
    repository, owner, run, task = project_state
    item = task('working')
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'inject')
    monkeypatch.setenv('AGENTMESH_TASK_MANAGEMENT', 'write')
    model = ScriptedModel([[assistant_message('stale')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    original = runtime.memory_context.stage_run_snapshot

    def change_after_snapshot(**kwargs):
        identity = original(**kwargs)
        TaskManagementService(repository).transition_task(item.id, TaskTransitionRequest(
            command_id='changed-after-snapshot', expected_version=1, action='plan',
        ), owner)
        return identity

    monkeypatch.setattr(runtime.memory_context, 'stage_run_snapshot', change_after_snapshot)
    with pytest.raises(MemoryContextError, match='project_state_context_changed'):
        asyncio.run(runtime._execute_run(run=run, selected=runtime._select_model(owner), content=run.input_text,
                                        user=owner, history=[], skill=None))
    assert not model.calls


def test_granted_project_state_tool_uses_run_project_at_next_request(project_state, monkeypatch):
    from agentmesh.tools import ensure_tool_seed_data

    repository, owner, run, task = project_state
    task('done', stage=TaskDeliveryStage.DONE)
    ensure_tool_seed_data(repository, granted_by=owner.id)
    repository.save_agent_tool_grant(AgentToolGrant(agent_id=owner.personal_agent_id, tool_id='tool_project_state',
                                                   granted_by=owner.id))
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'off')
    model = ScriptedModel([
        [function_call('project_state', {'project_id': None, 'task_id': None}, call_id='state_call')],
        [assistant_message('完成 1 项。')],
    ])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    asyncio.run(runtime._execute_run(run=run, selected=runtime._select_model(owner), content='查询项目任务统计',
                                    user=owner, history=[], skill=None))
    output = next(item['output'] for item in model.calls[1].input if item.get('type') == 'function_call_output')
    value = json.loads(output)
    assert '"done":1' in value['context']
    assert value['project_id'] == run.project_id
    assert repository.memory_use_receipts == []


def test_counts_remain_exact_above_inspection_hydration_limit(project_state):
    from agentmesh.task_operations.contracts import ProjectStateQueryV1
    from agentmesh.task_operations.state import ProjectStateService

    repository, owner, run, task = project_state
    original = task('bulk-base', stage=TaskDeliveryStage.DONE)
    with repository._connect() as connection:
        connection.execute(
            """WITH RECURSIVE numbers(value) AS (
                 SELECT 1 UNION ALL SELECT value + 1 FROM numbers WHERE value < 10020)
               INSERT INTO records(collection, id, payload)
               SELECT 'tasks', 'bulk-' || value, json_set(?, '$.id', 'bulk-' || value) FROM numbers""",
            (original.model_dump_json(),),
        )
    result = ProjectStateService(repository).query(ProjectStateQueryV1(project_id=run.project_id), owner)
    assert result.task_count == 10021
    assert result.tasks_by_stage[TaskDeliveryStage.DONE] == 10021


def test_state_api_returns_current_counts_and_checks_membership(project_state, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from agentmesh.routes import task_operations
    from agentmesh.routes.deps import current_user

    repository, owner, run, task = project_state
    item = task('api-task', stage=TaskDeliveryStage.IN_PROGRESS)
    monkeypatch.setattr(task_operations, 'store', repository)
    app = FastAPI()
    app.include_router(task_operations.router)
    app.dependency_overrides[current_user] = lambda: owner
    client = TestClient(app)
    response = client.get(f'/api/task-operations/{run.project_id}/state', params={'task_id': item.id})
    assert response.status_code == 200
    assert response.json()['task']['version'] == 1
    assert response.json()['task']['navigation_href'] == '/tasks?task=api-task'
    assert response.json()['execution_ready'] is True
    project = repository.get_project(run.project_id)
    project.member_ids = ['someone_else']
    repository.save_project(project)
    assert client.get(f'/api/task-operations/{run.project_id}/state').status_code == 404


def test_explicit_tool_query_cannot_change_run_project(project_state):
    from agentmesh.agent_runtime.models import AgentMeshRunContext
    from agentmesh.tool_runtime.gateway import ToolGateway

    repository, owner, run, _ = project_state
    context = AgentMeshRunContext(user_id=owner.id, workspace_id=run.workspace_id, project_id=run.project_id,
                                  thread_id=run.thread_id, run_id=run.id)
    with pytest.raises(MemoryContextError, match='memory_context_project_mismatch'):
        ToolGateway(repository).project_state(context, {'project_id': 'other-project', 'task_id': None})


def test_changed_pending_sql_tool_output_cannot_enter_next_model_request(project_state, monkeypatch):
    from agentmesh.tools import ensure_tool_seed_data

    repository, owner, run, task = project_state
    item = task('tool-working')
    ensure_tool_seed_data(repository, granted_by=owner.id)
    repository.save_agent_tool_grant(AgentToolGrant(agent_id=owner.personal_agent_id, tool_id='tool_project_state',
                                                   granted_by=owner.id))
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'off')
    monkeypatch.setenv('AGENTMESH_TASK_MANAGEMENT', 'write')
    model = ScriptedModel([
        [function_call('project_state', {'project_id': None, 'task_id': None}, call_id='changed_state_call')],
        [assistant_message('stale')],
    ])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    original = runtime.tool_factory.gateway.memory_context.stage_tool_delivery
    changes = []

    def change_after_tool(*args, **kwargs):
        original(*args, **kwargs)
        changes.append(True)
        TaskManagementService(repository).transition_task(item.id, TaskTransitionRequest(
            command_id='changed-after-tool', expected_version=1, action='plan',
        ), owner)

    monkeypatch.setattr(runtime.tool_factory.gateway.memory_context, 'stage_tool_delivery', change_after_tool)
    with pytest.raises(MemoryContextError, match='project_state_context_changed'):
        asyncio.run(runtime._execute_run(run=run, selected=runtime._select_model(owner), content='查询统计',
                                        user=owner, history=[], skill=None))
    assert changes == [True]
    assert len(model.calls) == 1
    assert repository.memory_use_receipts == []


@pytest.mark.parametrize('change', [False, True])
def test_approval_recovery_rechecks_frozen_sql_state_before_tools(project_state, monkeypatch, change):
    from agentmesh.tools import ensure_tool_seed_data

    repository, owner, run, task = project_state
    item = task('approval-task')
    ensure_tool_seed_data(repository, granted_by=owner.id)
    repository.save_agent_tool_grant(AgentToolGrant(agent_id=owner.personal_agent_id, tool_id='tool_web_research',
                                                   granted_by=owner.id))
    definition = repository.get_tool_definition('tool_web_research')
    repository.save_tool_definition(definition.model_copy(update={'approval_required': True}))
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'inject')
    monkeypatch.setenv('AGENTMESH_TASK_MANAGEMENT', 'write')
    model = ScriptedModel([
        [function_call('web_research', {'query': 'state'}, call_id='state-approval')],
        [assistant_message('Resumed SQL state')],
    ])
    tool_calls = []

    def read_tool(*_args):
        tool_calls.append(True)
        return {'outcome': 'insufficient_evidence'}

    async def scenario():
        runtime = AgentRuntimeService(repository, model=model, enabled=True)
        monkeypatch.setattr(runtime.tool_factory.gateway, 'web_research', read_tool)
        paused = await runtime._execute_run(run=run, selected=runtime._select_model(owner), content=run.input_text,
                                             user=owner, history=[], skill=None)
        assert paused.waiting_approval
        if change:
            TaskManagementService(repository).transition_task(item.id, TaskTransitionRequest(
                command_id='changed-during-approval', expected_version=1, action='plan',
            ), owner)
        restored = AgentRuntimeService(repository, model=model, enabled=True)
        monkeypatch.setattr(restored.tool_factory.gateway, 'web_research', read_tool)
        if change:
            with pytest.raises(MemoryContextError, match='project_state_context_changed'):
                await restored.resume(run.id, user=owner, decisions={'state-approval': True})
            assert tool_calls == [] and len(model.calls) == 1
        else:
            answer = await restored.resume(run.id, user=owner, decisions={'state-approval': True})
            assert answer.content == 'Resumed SQL state'
            assert tool_calls == [True]
            assert '<agentmesh_project_state>' in model.calls[1].system_instructions

    asyncio.run(scenario())


@pytest.mark.parametrize('mode', ['off', 'observe', 'private_chat'])
def test_project_state_automatic_context_respects_mode_and_private_chat(project_state, monkeypatch, mode):
    repository, owner, run, task = project_state
    task('shared')
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'inject' if mode == 'private_chat' else mode)
    if mode == 'private_chat':
        run.project_chat = False
        repository.save_agent_run(run)
    model = ScriptedModel([[assistant_message('Ordinary answer')]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    asyncio.run(runtime._execute_run(run=run, selected=runtime._select_model(owner), content=run.input_text,
                                    user=owner, history=[], skill=None))
    assert '<agentmesh_project_state>' not in model.first_call.system_instructions
    events = [item.event_type for item in repository.list_agent_run_events(run.id)]
    assert ('project_state_context_observed' in events) is (mode == 'observe')
    assert 'project_state_context_delivered' not in events


@pytest.mark.parametrize('reason', ['unsafe', 'budget'])
def test_project_state_selection_withholds_unsafe_or_oversized_bodies(project_state, reason):
    from agentmesh.memory_context.contracts import MemoryContextBudgetV1
    from agentmesh.task_operations.contracts import ProjectStateQueryV1

    repository, owner, run, task = project_state
    item = task('unsafe-or-big', title='Authorization: Bearer abcdefghijklmnop' if reason == 'unsafe' else '文' * 5000)
    bundle = MemoryContextService(repository).prepare_project_state_for_run(
        ProjectStateQueryV1(task_id=item.id), query_text='current task', run=run, user=owner,
        budget=MemoryContextBudgetV1(max_total_chars=1200),
    )
    assert bundle.project_state_context.decision == ('quarantined' if reason == 'unsafe' else 'budget_dropped')
    assert item.title not in bundle.rendered_context
    assert bundle.total_chars <= 1200 and bundle.hits == []


@pytest.mark.parametrize('question', ['调查项目完成情况', '九月完成了多少任务？', '另一个项目的任务状态是什么？'])
def test_unstructured_or_historical_state_queries_are_not_guessed(project_state, question):
    _, _, run, _ = project_state
    assert MemoryContextService.project_state_query(question, run=run) is None
