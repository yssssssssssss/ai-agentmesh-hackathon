from __future__ import annotations

import pytest
from agents import Agent, RunConfig, Runner
from agents.testing import ScriptedModel, assistant_message
from test_memory_context import _accepted_memory, _linked_run, _repository

from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.memory_context.contracts import MemoryContextBudgetV1
from agentmesh.memory_context.service import MemoryContextService
from agentmesh.memory_learning.contracts import MemoryPreferencesPatchV1
from agentmesh.memory_learning.service import MemoryLearningService
from agentmesh.models import ChatThread
from agentmesh.seed import USER


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
def context_project(tmp_path, monkeypatch):
    repository = _repository(tmp_path)
    run = _linked_run(repository, monkeypatch, 'assembled')
    item = _accepted_memory(repository, 'memory_assembled')
    repository.save_memory_item(item.model_copy(update={
        'summary': 'Checkout evidence: ' + '保留原始依据并核对地址编辑。' * 150,
    }))
    MemoryLearningService(repository).patch_preferences(MemoryPreferencesPatchV1(
        command_id='assembly-preferences', expected_version=1, core_preferences=['回答先列出验证结果。'],
    ), USER)
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'inject')
    yield repository, run
    repository.close()


def test_preferences_and_memory_share_one_rendered_budget_without_premature_use(context_project):
    repository, run = context_project
    assembled = MemoryContextService(repository).assemble_for_run(
        run=run, user=USER, query=run.input_text, budget=MemoryContextBudgetV1(max_total_chars=1400),
    )
    assert assembled.core_preferences.preferences == ('回答先列出验证结果。',)
    assert assembled.bundle.hits
    assert assembled.rendered_context.index('agentmesh_core_preferences') < assembled.rendered_context.index('agentmesh_memory_context')
    assert assembled.total_chars == len(assembled.rendered_context) <= 1400
    assert assembled.bundle.rendered_context in assembled.rendered_context
    assert repository.list_memory_use_receipts_for_run(run.id) == []


@pytest.mark.anyio
async def test_assembled_input_delivers_only_its_exact_selected_memory_versions(context_project):
    repository, run = context_project
    service = MemoryContextService(repository)
    assembled = service.assemble_for_run(run=run, user=USER, query=run.input_text,
                                        budget=MemoryContextBudgetV1(max_total_chars=1400))
    context = AgentMeshRunContext(user_id=USER.id, workspace_id=run.workspace_id,
                                 project_id=run.project_id, thread_id=run.thread_id, run_id=run.id)
    snapshot = service.stage_run_snapshot(run=run, user=USER, context=context, input_text=run.input_text,
        query=run.input_text, additional_instructions=assembled.rendered_context,
        bundle=assembled.bundle, core_preferences=assembled.core_preferences, reason='assembled_context')
    model = ScriptedModel([[assistant_message('参考已审核资料。')]])
    guarded = service.guard_model_request(model, run=run, model_id='scripted', context_snapshot_id=snapshot)
    result = await Runner.run(Agent(name='assembled', instructions=assembled.rendered_context, model=guarded),
                              run.input_text, run_config=RunConfig(tracing_disabled=True))
    assert result.final_output == '参考已审核资料。'
    receipts = repository.list_memory_use_receipts_for_run(run.id)
    assert len(receipts) == 1
    assert receipts[0].memory_id == assembled.bundle.hits[0].memory_id
    assert receipts[0].memory_version == assembled.bundle.hits[0].memory_version
    assert receipts[0].memory_hash == assembled.bundle.hits[0].memory_hash
    assert model.first_call.system_instructions == assembled.rendered_context


def test_optional_memory_is_dropped_before_core_preferences_when_budget_is_small(context_project):
    repository, run = context_project
    assembled = MemoryContextService(repository).assemble_for_run(
        run=run, user=USER, query=run.input_text, budget=MemoryContextBudgetV1(max_total_chars=300),
    )
    assert '回答先列出验证结果。' in assembled.rendered_context
    assert 'Checkout evidence' not in assembled.rendered_context
    assert assembled.total_chars <= 300
    assert not assembled.bundle or not assembled.bundle.hits
    assert repository.list_memory_use_receipts_for_run(run.id) == []


def test_natural_chat_keeps_private_preferences_and_observe_mode_delivers_no_context(context_project, monkeypatch):
    repository, run = context_project
    thread = repository.add_chat_thread(ChatThread(user_id=USER.id, workspace_id=USER.workspace_id,
                                                   project_id=run.project_id, title='Private conversation'))
    private = repository.save_agent_run(run.model_copy(update={
        'id': 'private_assembled_run', 'thread_id': thread.id, 'task_id': None, 'project_chat': False,
    }))
    service = MemoryContextService(repository)
    assembled = service.assemble_for_run(run=private, user=USER, query=run.input_text)
    assert assembled.bundle is None and '回答先列出验证结果。' in assembled.rendered_context
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'observe')
    observed = service.assemble_for_run(run=run, user=USER, query=run.input_text)
    assert observed.bundle is None and observed.core_preferences is None and observed.rendered_context == ''
    assert repository.list_memory_use_receipts_for_run(run.id) == []


def test_project_state_query_uses_sql_evidence_instead_of_recalled_narrative(context_project):
    repository, run = context_project
    assembled = MemoryContextService(repository).assemble_for_run(run=run, user=USER, query='项目状态')
    assert assembled.bundle.project_state_context.result.task_count == 1
    assert not assembled.bundle.hits
    assert 'Checkout evidence' not in assembled.rendered_context
    assert '回答先列出验证结果。' in assembled.rendered_context
    assert repository.list_memory_use_receipts_for_run(run.id) == []
