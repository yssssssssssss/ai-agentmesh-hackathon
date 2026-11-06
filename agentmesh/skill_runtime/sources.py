"""Local execution and citation identities for runtime transactions."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from agentmesh.canonical_json import canonical_json_sha256, strict_json_loads
from agentmesh.memory_context.request_budget import ModelAdmissionError
from agentmesh.models import AgentRun, SkillNodeResult, SkillPlan, SkillPlanNode, Source
from agentmesh.source_authority import source_snapshot_available


class SynthesisSourceError(ModelAdmissionError):
    pass


@dataclass(frozen=True, slots=True)
class SynthesisFinalizationSnapshot:
    run_id: str
    plan_id: str
    run_identity_hash: str
    plan_hash: str
    results_hash: str
    sources: dict[str, str]


def run_finalization_identity(run: AgentRun) -> str:
    keys = ('id', 'user_id', 'workspace_id', 'project_id', 'thread_id', 'task_id', 'plan_id',
            'writer_generation_epoch', 'orchestration_version', 'planning_contract_version',
            'execution_contract_version', 'agent_definition_version', 'execution_location', 'runner_id')
    return canonical_json_sha256(run.model_dump(mode='json', include=set(keys)))


def plan_run_execution_identity(run: AgentRun) -> str:
    # Node leases authorize individual devices. The parent's runner_id records
    # the most recently leased node's device, not the DAG controller's writer.
    if run.execution_location == 'runner' and run.plan_id is not None:
        run = run.model_copy(update={'runner_id': None})
    return run_finalization_identity(run)


def node_execution_identity(node: SkillPlanNode) -> str:
    return canonical_json_sha256(node.model_dump(mode='json', exclude={
        'status', 'attempt', 'error_code', 'started_at', 'completed_at',
    }))


def plan_execution_identity(plan: SkillPlan) -> str:
    payload = plan.model_dump(mode='json', include={
        'id', 'run_id', 'version', 'intent', 'routing_result', 'candidate_skill_ids',
        'candidate_snapshot', 'output_contract', 'synthesis_output_contract',
        'capability_gaps', 'preferred_order', 'planning_mode', 'execution_contract_version',
        'requirement_version_id', 'requirement_content_hash', 'problem_graph',
        'problem_graph_hash', 'plan_content_hash', 'approved_plan_artifact_id', 'capability_check',
    })
    payload['nodes'] = [node_execution_identity(node) for node in plan.nodes]
    return canonical_json_sha256(payload)


def plan_finalization_identity(plan: SkillPlan) -> str:
    payload = plan.model_dump(mode='json', exclude={
        'created_at', 'updated_at', 'completion_check', 'synthesis',
    })
    return canonical_json_sha256(strict_json_loads(json.dumps(payload, ensure_ascii=False, allow_nan=False)))


def results_finalization_identity(results: list[SkillNodeResult]) -> str:
    payload = [item.model_dump(mode='json') for item in sorted(results, key=lambda item: item.id)]
    return canonical_json_sha256(strict_json_loads(json.dumps(payload, ensure_ascii=False, allow_nan=False)))


def source_identity_hash(source: Source) -> str:
    return canonical_json_sha256(source.model_dump(mode='json', exclude={'created_at'}))


def synthesis_source_snapshot(connection: sqlite3.Connection, run: AgentRun,
                              results: list[SkillNodeResult]) -> dict[str, str]:
    allowed_runs = {run.id, *(result.reused_from_run_id for result in results if result.reused_from_run_id)}
    snapshot: dict[str, str] = {}
    current: dict[str, Source] = {}
    for result in results:
        for citation in result.sources:
            if citation.id not in current:
                if len(current) >= 600:
                    raise SynthesisSourceError('synthesis_sources_changed')
                row = connection.execute("SELECT payload FROM records WHERE collection = 'sources' AND id = ?",
                                         (citation.id,)).fetchone()
                try:
                    if row is None or len(row['payload'].encode('utf-8')) > 16384:
                        raise ValueError
                    current[citation.id] = Source.model_validate_json(row['payload'])
                except ValueError:
                    raise SynthesisSourceError('synthesis_sources_changed') from None
            source = current[citation.id]
            if (source.workspace_id != run.workspace_id or source.project_id != run.project_id
                or source.user_id != run.user_id or source.run_id not in allowed_runs
                or source.origin != citation.origin
                or any(getattr(source, key) != getattr(citation, key)
                       for key in ('id', 'title', 'source_type', 'reference'))):
                raise SynthesisSourceError('synthesis_sources_changed')
            if not source_snapshot_available(connection, source, owner_id=run.user_id,
                workspace_id=run.workspace_id, project_id=run.project_id):
                raise SynthesisSourceError('synthesis_sources_changed')
            snapshot[source.id] = source_identity_hash(source)
    return snapshot


def require_source_snapshot(connection: sqlite3.Connection, snapshot: dict[str, str]) -> None:
    if len(snapshot) > 600:
        raise SynthesisSourceError('synthesis_sources_changed')
    for source_id, expected in snapshot.items():
        row = connection.execute("SELECT payload FROM records WHERE collection = 'sources' AND id = ?",
                                 (source_id,)).fetchone()
        try:
            if row is None or len(row['payload'].encode('utf-8')) > 16384:
                raise ValueError
            source = Source.model_validate_json(row['payload'])
        except ValueError:
            raise SynthesisSourceError('synthesis_sources_changed') from None
        if source.id != source_id or source_identity_hash(source) != expected:
            raise SynthesisSourceError('synthesis_sources_changed')
        if not source_snapshot_available(connection, source, owner_id=source.user_id,
            workspace_id=source.workspace_id, project_id=source.project_id):
            raise SynthesisSourceError('synthesis_sources_changed')
