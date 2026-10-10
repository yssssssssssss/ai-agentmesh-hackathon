"""Owner-only, body-free projection of prepared decisions and actual receipts."""
from __future__ import annotations

import sqlite3
from contextlib import closing

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.memory_context.contracts import (
    MemoryContextBundleV1,
    MemoryContextCandidateV1,
    MemoryContextCandidateViewV1,
    MemoryToolDeliveryV1,
    RunContextSnapshotV1,
)
from agentmesh.memory_context.fact_context import fact_result_hash
from agentmesh.memory_context.origin import memory_origin_available
from agentmesh.memory_context.procedure_context import procedure_selection_hash, select_procedure_in_transaction
from agentmesh.memory_facts import MemoryFactsError, MemoryFactsService, authorize_fact_project
from agentmesh.memory_governance.lifecycle import memory_content_hash
from agentmesh.models import (
    AgentRun,
    ChatThread,
    MemoryItem,
    MemoryKind,
    MemoryUseReceiptV1,
    Scope,
    Task,
    User,
    UserMemoryItem,
)
from agentmesh.store import MemoryContextConflict, SQLiteStore
from agentmesh.tool_runtime.guardrails import unsafe_tool_output_reason


def bundle_candidates(bundle: MemoryContextBundleV1) -> list[MemoryContextCandidateV1]:
    if bundle.candidates is not None:
        return bundle.candidates
    selection = bundle.procedure_context or bundle.fact_context
    proofs = ([bundle.procedure_context] if bundle.procedure_context else bundle.fact_context.result.facts
              if bundle.fact_context else bundle.hits)
    decision = selection.decision if selection else 'prepared'
    reason = {'prepared': 'selected', 'quarantined': 'unsafe_content', 'budget_dropped': 'budget_limit',
              'withheld': 'procedure_unavailable' if bundle.procedure_context else 'fact_unavailable'}[decision]
    candidates = {}
    for proof in proofs:
        candidate = MemoryContextCandidateV1(
            memory_id=proof.memory_id, memory_record_type=(proof.memory_record_type if selection else proof.result.result_type),
            memory_version=proof.memory_version, memory_hash=proof.memory_hash, decision=decision, reason=reason,
        )
        candidates[_key(candidate)] = candidate
    return list(candidates.values())


def _key(candidate: MemoryContextCandidateV1) -> tuple[str, str, int, str]:
    return candidate.memory_record_type, candidate.memory_id, candidate.memory_version, candidate.memory_hash


def _bundles(connection: sqlite3.Connection, run: AgentRun) -> list[MemoryContextBundleV1]:
    bundles = []
    for collection, model in (('run_context_snapshots', RunContextSnapshotV1),
                              ('memory_tool_deliveries', MemoryToolDeliveryV1)):
        rows = connection.execute(
            'SELECT id, payload FROM records WHERE collection = ? AND json_extract(payload, \'$.run_id\') = ? '
            'AND json_extract(payload, \'$.owner_user_id\') = ? AND json_extract(payload, \'$.workspace_id\') = ? '
            'AND json_extract(payload, \'$.project_id\') = ? ORDER BY rowid DESC LIMIT 16',
            (collection, run.id, run.user_id, run.workspace_id, run.project_id),
        ).fetchall()
        for row in rows:
            try:
                record = model.model_validate_json(row['payload'])
                if record.id != row['id'] or record.status != 'prepared' or record.bundle is None:
                    continue
                if isinstance(record, RunContextSnapshotV1):
                    if (record.thread_id, record.task_id) != (run.thread_id, run.task_id):
                        continue
                    digest = canonical_json_sha256(record.model_dump(mode='json', exclude={'id', 'content_hash', 'status'}))
                    if digest != record.content_hash or record.id != 'context_' + digest[:32]:
                        continue
                elif record.id != canonical_json_sha256({'run_id': run.id,
                                                         'bundle': record.bundle.model_dump(mode='json'),
                                                         'output_hash': record.output_hash}):
                    continue
            except ValueError:
                continue
            bundles.append(record.bundle)
    return bundles


def _structured_available(repository: SQLiteStore, connection: sqlite3.Connection, bundle: MemoryContextBundleV1,
                          run: AgentRun, actor: User) -> bool:
    try:
        if selection := bundle.procedure_context:
            current = select_procedure_in_transaction(
                repository, connection, selection.query, run=run, user=actor,
                allowed_scopes=selection.allowed_scopes, allowed_layers=selection.allowed_layers,
            )
            return current.decision == 'prepared' and procedure_selection_hash(current) == procedure_selection_hash(selection)
        if selection := bundle.fact_context:
            binding = repository._memory_binding_in_transaction(connection, actor.personal_agent_id)
            scopes = set(selection.allowed_scopes)
            types = set(selection.allowed_memory_types) if selection.allowed_memory_types is not None else None
            if binding:
                scopes &= set(binding.allowed_scopes or [Scope.PRIVATE])
                binding_types = binding.effective_memory_types
                if binding_types is not None:
                    types = binding_types if types is None else types & binding_types
            current = MemoryFactsService.query_in_transaction(
                connection, selection.query, actor, snapshot_at=selection.result.snapshot_at,
                allowed_scopes=scopes, allowed_memory_types=types, allowed_layers=set(selection.allowed_layers),
            )
            return current.automatic_context_eligible and fact_result_hash(current) == fact_result_hash(selection.result)
    except (MemoryContextConflict, MemoryFactsError, ValueError):
        return False
    return True


def _available_item(repository: SQLiteStore, connection: sqlite3.Connection, candidate: MemoryContextCandidateV1,
                    run: AgentRun, actor: User, *, structured: bool) -> MemoryItem | UserMemoryItem | None:
    if candidate.decision in {'quarantined', 'withheld'}:
        return None
    collection = 'user_memory_items' if candidate.memory_record_type == 'user_memory_item' else 'memory_items'
    item = repository._get_in_transaction(connection, collection, candidate.memory_id,
                                          UserMemoryItem if collection == 'user_memory_items' else MemoryItem)
    if item is None:
        return None
    kind = MemoryKind.PERSONAL if item.scope is Scope.PRIVATE else MemoryKind.PROJECT if item.scope is Scope.PROJECT else MemoryKind.TEAM
    try:
        item = repository._memory_item_for_use_in_transaction(
            connection, memory_id=item.id, memory_kind=kind, memory_record_type=candidate.memory_record_type,
            memory_version=candidate.memory_version, actor=actor, run=run,
            binding=repository._memory_binding_in_transaction(connection, actor.personal_agent_id),
        )
    except MemoryContextConflict:
        return None
    if ((item.facts is not None or item.procedure is not None) and not structured
            or memory_content_hash(item) != candidate.memory_hash or not memory_origin_available(connection, item)
            or unsafe_tool_output_reason(item.title + '\n' + item.summary + '\n' +
                                         '\n'.join(source.model_dump_json() for source in item.sources))):
        return None
    return item


def candidates_for_run(repository: SQLiteStore, run: AgentRun, user: User) -> list[MemoryContextCandidateViewV1]:
    with closing(repository._read_connect()) as connection, connection:
        connection.execute('BEGIN')
        actor, _ = authorize_fact_project(connection, user, run.project_id)
        row = connection.execute('SELECT payload FROM agent_runs WHERE id = ?', (run.id,)).fetchone()
        current = AgentRun.model_validate_json(row['payload']) if row else None
        if current is None or (current.user_id, current.workspace_id, current.project_id) != (
            actor.id, actor.workspace_id, run.project_id,
        ) or any(getattr(current, field) != getattr(run, field) for field in (
            'user_id', 'workspace_id', 'project_id', 'thread_id', 'task_id', 'writer_generation_epoch',
        )):
            raise MemoryContextConflict('memory_context_run_not_found')
        thread = repository._get_in_transaction(connection, 'chat_threads', current.thread_id, ChatThread)
        task = repository._get_in_transaction(connection, 'tasks', current.task_id, Task) if current.task_id else None
        if thread is not None and ((thread.workspace_id, thread.project_id) != (current.workspace_id, current.project_id)
                                   or (thread.user_id != actor.id and (task is None or task.thread_id != thread.id))):
            raise MemoryContextConflict('memory_context_run_not_found')
        views = {}
        for bundle in _bundles(connection, current):
            structured = _structured_available(repository, connection, bundle, current, actor)
            for candidate in bundle_candidates(bundle):
                key = _key(candidate)
                if key in views or len(views) >= 200:
                    continue
                receipt_row = connection.execute(
                    "SELECT payload FROM records WHERE collection = 'memory_use_receipts' "
                    "AND json_extract(payload, '$.run_id') = ? AND json_extract(payload, '$.memory_record_type') = ? "
                    "AND json_extract(payload, '$.memory_id') = ? AND json_extract(payload, '$.memory_version') = ? "
                    "AND json_extract(payload, '$.memory_hash') = ? ORDER BY rowid DESC LIMIT 1", (current.id, *key),
                ).fetchone()
                receipt = MemoryUseReceiptV1.model_validate_json(receipt_row['payload']) if receipt_row else None
                item = _available_item(repository, connection, candidate, current, actor, structured=structured)
                state = 'delivered' if receipt else 'withheld' if item is None and candidate.decision == 'prepared' else candidate.decision
                views[key] = MemoryContextCandidateViewV1(candidate=candidate, state=state,
                    title=item.title if item else None, citation_label=receipt.citation_label if receipt else None,
                    current_available=item is not None)
        return list(views.values())
