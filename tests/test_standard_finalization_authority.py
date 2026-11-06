from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from agents.testing import ScriptedModel, assistant_message
from test_universal_plan import _candidate

from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.models import (
    AgentExecutionContractVersion,
    AgentPlanningContractVersion,
    AgentRun,
    AgentRunStatus,
    CandidateSnapshotV1,
    ChatThread,
    SkillIntent,
    SkillNodeResult,
    SkillPlan,
    SkillPlanNode,
    SkillResultSource,
    SkillSideEffect,
    SkillSynthesisResult,
    Source,
    new_id,
    now_utc,
)
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.store import SQLiteStore


@pytest.fixture
def finalization(tmp_path, monkeypatch):
    repository = SQLiteStore(tmp_path / 'finalization-authority.sqlite3')
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    thread = repository.add_chat_thread(ChatThread(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, title='Atomic finalization'))
    run = repository.save_agent_run(AgentRun(thread_id=thread.id, user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, input_text='Synthesize current evidence', status='running',
        writer_generation_epoch=1, deadline_at=now_utc() + timedelta(minutes=5)))
    node = SkillPlanNode(id='completed_node', skill_id='completed_skill', skill_version='1',
        skill_content_hash='completed_hash', reason='already completed', output_contract=['analysis_result'],
        status='completed', attempt=1, completed_at=now_utc())
    plan = repository.save_skill_plan(SkillPlan(run_id=run.id, status='approved',
        intent=SkillIntent(goal=run.input_text), candidate_skill_ids=[node.skill_id],
        output_contract=node.output_contract, nodes=[node]))
    run = repository.save_agent_run(run.model_copy(update={'plan_id': plan.id}))
    source = repository.add_source(Source(title='Current evidence', source_type='web_page',
        reference='https://example.test/current', workspace_id=run.workspace_id, project_id=run.project_id,
        user_id=run.user_id, run_id=run.id, skill_id=node.skill_id))
    result = repository.save_skill_node_result(plan.id, SkillNodeResult(node_id=node.id, skill_id=node.skill_id,
        summary='Current evidence', attempt=1, sources=[SkillResultSource(**source.model_dump())]))
    output = SkillSynthesisResult(summary='Current evidence', claims=[{
        'text': 'Current evidence', 'node_result_ids': [result.id], 'source_ids': [source.id]}])
    model = ScriptedModel([[assistant_message(output.model_dump_json())]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'off')
    yield repository, runtime, run, plan, source, result, model
    repository.close()


def test_source_deleted_after_synthesis_return_cannot_commit_report(finalization, monkeypatch):
    repository, runtime, run, plan, source, _result, model = finalization
    original_finish = repository.finish_skill_plan_and_run

    def delete_before_commit(**kwargs):
        if kwargs['plan'].synthesis is not None:
            with repository._connect() as connection:
                connection.execute("DELETE FROM records WHERE collection = 'sources' AND id = ?", (source.id,))
        return original_finish(**kwargs)

    monkeypatch.setattr(repository, 'finish_skill_plan_and_run', delete_before_commit)
    with pytest.raises(RuntimeError, match='synthesis_sources_changed'):
        asyncio.run(runtime._execute_approved_skill_plan(plan=plan, run=run, user=USER))

    failed = repository.get_agent_run(run.id)
    assert failed.status is AgentRunStatus.FAILED
    assert failed.error_code == 'synthesis_sources_changed'
    assert failed.output_text is None
    assert repository.get_skill_plan(plan.id).synthesis is None
    assert len(model.calls) == 1
    assert not any(event.event_type in {'synthesis_completed', 'run_completed'}
                   for event in repository.list_agent_run_events(run.id))


@pytest.fixture
def universal_finalization(finalization, tmp_path):
    repository, _runtime, run, plan, source, result, _model = finalization
    _skill, candidate, identity = _candidate(tmp_path, 1)
    identity = identity.model_copy(update={'covered_requirement_ids': (), 'coverage_witness_scenario_id': None})
    body = {'schema_version': 'candidate-snapshot-v1', 'retrieval_policy_version': 'universal-profile-rrf-v2',
        'required_coverage_atoms': [], 'plannable_coverage_atom_ids': [], 'coverage_witness_skill_ids': [],
        'required_synthesis_output_ids': ['summary'], 'candidates': [identity.model_dump(mode='json')]}
    snapshot = CandidateSnapshotV1(**body, content_hash=canonical_json_sha256(body))
    plan_id = new_id('plan')
    run = repository.save_agent_run(run.model_copy(update={'id': new_id('run'), 'plan_id': plan_id,
        'planning_contract_version': AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1,
        'execution_contract_version': AgentExecutionContractVersion.STANDARD_UNIVERSAL_V1}))
    source = repository.add_source(source.model_copy(update={'id': new_id('src'), 'run_id': run.id,
                                                            'skill_id': candidate.skill_id}))
    node = plan.nodes[0].model_copy(update={'id': 'universal_node', 'skill_id': candidate.skill_id,
        'skill_content_hash': identity.skill_content_hash,
        'side_effect': SkillSideEffect.DRAFT, 'output_contract': ['research_plan']})
    plan = repository.save_skill_plan(plan.model_copy(update={'id': plan_id, 'run_id': run.id, 'candidate_snapshot': snapshot,
        'execution_contract_version': run.execution_contract_version, 'candidate_skill_ids': [candidate.skill_id],
        'synthesis_output_contract': ['summary'], 'output_contract': ['research_plan', 'summary'], 'nodes': [node]}))
    result = repository.save_skill_node_result(plan.id, result.model_copy(update={'id': new_id('node_result'),
        'node_id': node.id, 'skill_id': node.skill_id, 'sources': [SkillResultSource(**source.model_dump())],
        'deliverable_markdown': '# Current research plan', 'delivered_output_kinds': ['research_plan']}))
    output = SkillSynthesisResult(summary='Current evidence', presentation_outputs=['summary'], claims=[{
        'text': 'Current evidence', 'node_result_ids': [result.id], 'source_ids': [source.id]}])
    model = ScriptedModel([[assistant_message(output.model_dump_json())]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    return repository, runtime, run, plan, source, result, model


def test_universal_synthesis_artifact_rolls_back_with_failed_terminal_event(universal_finalization):
    repository, runtime, run, plan, _source, _result, model = universal_finalization
    with repository._connect() as connection:
        connection.execute('''CREATE TRIGGER fail_synthesis_event BEFORE INSERT ON agent_run_events
            WHEN json_extract(NEW.payload, '$.event_type') = 'synthesis_completed'
            BEGIN SELECT RAISE(ABORT, 'controlled_commit_failure'); END''')

    with pytest.raises(Exception, match='controlled_commit_failure'):
        asyncio.run(runtime._execute_approved_skill_plan(plan=plan, run=run, user=USER))

    assert repository.get_agent_run(run.id).output_text is None
    assert repository.get_skill_plan(plan.id).synthesis is None
    assert len(model.calls) == 1
    with repository._read_connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM artifacts WHERE run_id = ? AND artifact_type = 'universal_synthesis'",
                                  (run.id,)).fetchone()[0] == 0


@pytest.mark.parametrize('change', ['source', 'owner'])
def test_universal_refusal_cannot_become_partial_or_leave_synthesis_artifact(universal_finalization, monkeypatch, change):
    repository, runtime, run, plan, source, _result, model = universal_finalization
    original_finish = repository.finish_skill_plan_and_run

    def revoke_before_commit(**kwargs):
        if kwargs['plan'].synthesis is not None:
            if change == 'owner':
                repository.save_user(USER.model_copy(update={'status': 'disabled'}))
            else:
                with repository._connect() as connection:
                    connection.execute("DELETE FROM records WHERE collection = 'sources' AND id = ?", (source.id,))
        return original_finish(**kwargs)

    monkeypatch.setattr(repository, 'finish_skill_plan_and_run', revoke_before_commit)
    with pytest.raises(RuntimeError, match='synthesis_'):
        asyncio.run(runtime._execute_approved_skill_plan(plan=plan, run=run, user=USER))

    failed = repository.get_agent_run(run.id)
    assert failed.status is AgentRunStatus.FAILED
    assert failed.output_text is None
    assert repository.get_skill_plan(plan.id).synthesis is None
    assert len(model.calls) == 1
    with repository._read_connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM artifacts WHERE run_id = ? AND artifact_type = 'universal_synthesis'",
                                  (run.id,)).fetchone()[0] == 0


def test_universal_synthesis_and_terminal_state_commit_together(universal_finalization):
    repository, runtime, run, plan, source, _result, model = universal_finalization
    outcome = asyncio.run(runtime._execute_approved_skill_plan(plan=plan, run=run, user=USER))

    assert outcome.run.status is AgentRunStatus.COMPLETED
    assert outcome.synthesis.claims[0].source_ids == [source.id]
    assert len(model.calls) == 1
    stored = repository.get_skill_plan(plan.id)
    artifact = repository.get_artifact(outcome.synthesis.artifact_ids[-1])
    assert artifact.verification_state.value == 'sealed'
    assert artifact.plan_version_id == f'{plan.id}:v{stored.version}'
    assert stored.synthesis['artifact_ids'][-1] == artifact.id
    assert repository.get_agent_run(run.id).output_text


@pytest.mark.parametrize('change', ['plan_version', 'node_result', 'source_identity', 'runner'])
def test_changed_frozen_input_cannot_commit_old_synthesis(finalization, monkeypatch, change):
    repository, runtime, run, plan, source, result, model = finalization
    original_finish = repository.finish_skill_plan_and_run

    def change_before_commit(**kwargs):
        if kwargs['plan'].synthesis is not None:
            if change == 'plan_version':
                current = repository.get_skill_plan(plan.id)
                repository.save_skill_plan(current.model_copy(update={'version': current.version + 1}))
            elif change == 'runner':
                current = repository.get_agent_run(run.id)
                repository.save_agent_run(current.model_copy(update={'runner_id': 'replacement_runner'}))
            elif change == 'node_result':
                with repository._connect() as connection:
                    connection.execute('UPDATE skill_node_results SET payload = ? WHERE plan_id = ? AND node_id = ? AND attempt = ?',
                        (result.model_copy(update={'summary': 'Revised node evidence'}).model_dump_json(),
                         plan.id, result.node_id, result.attempt))
            else:
                repository._upsert('sources', source.model_copy(update={'reference': 'https://example.test/revised'}))
        return original_finish(**kwargs)

    monkeypatch.setattr(repository, 'finish_skill_plan_and_run', change_before_commit)
    with pytest.raises(RuntimeError, match='synthesis_'):
        asyncio.run(runtime._execute_approved_skill_plan(plan=plan, run=run, user=USER))

    current_plan = repository.get_skill_plan(plan.id)
    current_run = repository.get_agent_run(run.id)
    assert current_plan.synthesis is None
    assert current_run.output_text is None
    assert len(model.calls) == 1
    if change in {'plan_version', 'runner'}:
        if change == 'plan_version':
            assert current_plan.version == plan.version + 1
        else:
            assert current_run.runner_id == 'replacement_runner'
        assert current_plan.status.value == 'running'
        assert current_run.status is AgentRunStatus.RUNNING
    else:
        assert current_run.status is AgentRunStatus.FAILED


@pytest.mark.parametrize('change', ['owner_disabled', 'project_archived', 'membership', 'thread_archived',
                                  'deadline', 'generation'])
def test_current_execution_authority_is_rechecked_at_final_commit(finalization, monkeypatch, change):
    repository, runtime, run, plan, _source, _result, model = finalization
    original_finish = repository.finish_skill_plan_and_run

    def revoke_before_commit(**kwargs):
        if kwargs['plan'].synthesis is not None:
            if change == 'owner_disabled':
                repository.save_user(USER.model_copy(update={'status': 'disabled'}))
            elif change in {'project_archived', 'membership'}:
                project = repository.get_project(run.project_id)
                update = {'status': 'archived'} if change == 'project_archived' else {'member_ids': ['other_user']}
                repository.save_project(project.model_copy(update=update))
            elif change == 'thread_archived':
                thread = repository.get_chat_thread(run.thread_id)
                repository.save_chat_thread(thread.model_copy(update={'status': 'archived'}))
            else:
                current = repository.get_agent_run(run.id)
                update = ({'deadline_at': now_utc() - timedelta(seconds=1)} if change == 'deadline'
                          else {'writer_generation_epoch': 2})
                repository.save_agent_run(current.model_copy(update=update))
        return original_finish(**kwargs)

    monkeypatch.setattr(repository, 'finish_skill_plan_and_run', revoke_before_commit)
    with pytest.raises(RuntimeError, match='synthesis_finalization_'):
        asyncio.run(runtime._execute_approved_skill_plan(plan=plan, run=run, user=USER))

    failed = repository.get_agent_run(run.id)
    assert failed.status is (AgentRunStatus.RUNNING if change == 'generation' else AgentRunStatus.FAILED)
    if change == 'generation':
        assert failed.writer_generation_epoch == 2
        assert failed.error_code is None
    assert failed.output_text is None
    assert repository.get_skill_plan(plan.id).synthesis is None
    assert len(model.calls) == 1
    assert not any(event.event_type in {'synthesis_completed', 'run_completed'}
                   for event in repository.list_agent_run_events(run.id))
