"""Offline replay of frozen remembered facts. No model quality score is inferred."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / 'eval/memory_cases_v1.json'
CATEGORIES = {'fact_extraction', 'cross_session', 'multi_version', 'historical_time',
              'conflict_unknown', 'withdrawal_permission'}


def load_dataset(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise ValueError('dataset_case_distribution_invalid')
    cases = document.get('cases', [])
    if (document.get('schema_version') != 'memory-cases-v1'
            or document.get('fixture_type') != 'synthetic-frozen-records'
            or len(cases) != 120 or len({case['id'] for case in cases}) != 120
            or Counter(case['category'] for case in cases) != dict.fromkeys(CATEGORIES, 20)
            or any(case.get('split') != 'holdout' for case in cases)
            or {case['id'] for case in cases} & {case['id'] for case in document.get('generation_examples', [])}):
        raise ValueError('dataset_case_distribution_invalid')
    return document, hashlib.sha256(raw).hexdigest()


def run_case(database: Path, case: dict, *, include_contexts: bool = False) -> dict:
    from agentmesh.memory_facts import MemoryFactsError, MemoryFactsService, document_evidence_hash
    from agentmesh.memory_lifecycle import MemoryForgetRequestV1, MemoryForgettingService
    from agentmesh.memory_payloads import FactAssertionV1, FactQueryV1, FactRememberV1
    from agentmesh.models import DocumentRecord, Project, Source, User, Workspace
    from agentmesh.store import SQLiteStore

    now = datetime.fromisoformat(case['snapshot_at'])
    repository = SQLiteStore(database)
    try:
        repository.save_workspace(Workspace(id='workspace', name='Offline fixture', description='Synthetic only'))
        owner = repository.save_user(User(id='owner', name='Fixture owner', workspace_id='workspace',
            default_project_id='project', personal_agent_id='owner_agent', role='user'))
        peer = repository.save_user(owner.model_copy(update={'id': 'peer', 'personal_agent_id': 'peer_agent'}))
        project = repository.save_project(Project(id='project', name='Offline project', workspace_id='workspace',
                                                   goal='Frozen memory replay', member_ids=[owner.id, peer.id]))
        service = MemoryFactsService(repository, clock=lambda: now)
        memories, documents = [], []
        for spec in case['sources']:
            document = repository.add_document(DocumentRecord(id=spec['id'], title=spec['title'], text=spec['text'],
                file_name=spec['id'] + '.txt', content_type='text/plain', uploaded_by=owner.id,
                workspace_id=owner.workspace_id, project_id=project.id, created_at=now, updated_at=now,
                source=Source(id='source_' + spec['id'], title=spec['title'], source_type='document',
                              reference=f"document://{spec['id']}#v1/raw", created_at=now)))
            predecessor = memories[spec['supersedes']] if spec.get('supersedes') is not None else None
            memories.append(service.remember(FactRememberV1(command_id='remember_' + spec['id'], project_id=project.id,
                title=spec['title'], summary='Explicitly confirmed frozen fixture.', source_document_id=document.id,
                source_version=document.version, source_hash=document_evidence_hash(document),
                supersedes_memory_id=predecessor.id if predecessor else None,
                expected_memory_version=predecessor.version if predecessor else None,
                facts=[FactAssertionV1.model_validate(fact) for fact in spec['assertions']]), owner))
            documents.append(document)
        # The same predicate in a peer's private source must never leak into this query.
        peer_document = repository.add_document(documents[0].model_copy(update={'id': 'peer_document',
            'uploaded_by': peer.id, 'text': 'FORBIDDEN_PEER_VALUE',
            'source': Source(id='peer_source', title='Private peer source', source_type='document',
                            reference='document://peer_document#v1/raw', created_at=now)}))
        service.remember(FactRememberV1(command_id='peer_fact', project_id=project.id, title='Peer only',
            summary='Private peer fixture.', source_document_id=peer_document.id, source_version=peer_document.version,
            source_hash=document_evidence_hash(peer_document), facts=[FactAssertionV1(
                subject_type='project', subject_id=project.id, predicate=case['query']['predicate'],
                value='FORBIDDEN_PEER_VALUE', valid_from='2026-01-01T00:00:00Z')]), peer)
        operation = case.get('operation')
        request = MemoryForgetRequestV1(command_id='withdraw-fixture', expected_version=1)
        if operation == 'withdraw_document':
            MemoryForgettingService(repository).withdraw_document(documents[0].id, request, owner)
        elif operation == 'forget_memory':
            MemoryForgettingService(repository).forget(memories[0].id, request, owner)
        elif operation == 'revoke_project':
            repository.save_project(project.model_copy(update={'member_ids': [peer.id]}))
        elif operation == 'disable_actor':
            repository.save_user(owner.model_copy(update={'status': 'disabled'}))
        elif operation == 'move_workspace':
            repository.save_user(owner.model_copy(update={'workspace_id': 'other_workspace'}))
        elif operation == 'replace_document':
            repository.save_document(documents[0].model_copy(update={'version': 2, 'text': 'Replacement source.'}))
        elif operation is not None:
            raise ValueError('dataset_operation_invalid')
        if case.get('reopen_before_query'):
            repository.close()
            repository = SQLiteStore(database)
        try:
            result = MemoryFactsService(repository, clock=lambda: now).query(FactQueryV1.model_validate(case['query']), owner)
            actual = {'outcome': result.outcome, 'values': sorted({hit.fact.value for hit in result.facts}),
                      'evidence': sorted({ref.record_id for hit in result.facts for ref in hit.fact.evidence_refs}),
                      'automatic_eligible': result.automatic_context_eligible}
            private_data_excluded = 'FORBIDDEN_PEER_VALUE' not in result.model_dump_json()
        except MemoryFactsError as error:
            actual = {'error_code': error.code}
            private_data_excluded = True
        expected = case['expected']
        mismatches = sorted(key for key in expected.keys() | actual.keys() if expected.get(key) != actual.get(key))
        if not private_data_excluded:
            mismatches.append('private_data_excluded')
        if repository.memory_use_receipts:
            mismatches.append('read_created_delivery_receipt')
        replay = {'case_id': case['id'], 'category': case['category'], 'passed': not mismatches,
                  'mismatches': mismatches, 'private_data_excluded': private_data_excluded,
                  'reopened': bool(case.get('reopen_before_query'))}
        if include_contexts:
            replay['blocked_code'] = actual.get('error_code')
            replay['contexts'] = {} if replay['blocked_code'] else baseline_contexts(repository, owner, case, memories, result)
        return replay
    finally:
        repository.close()


def baseline_contexts(repository, owner, case, memories, result):
    from contextlib import closing

    from agentmesh.memory_context.origin import memory_origin_available
    from agentmesh.memory_context.service import MemoryContextService

    recent = []
    with closing(repository._read_connect()) as connection, connection:
        connection.execute('BEGIN')
        for memory, source in zip(memories, case['sources'], strict=True):
            item = repository._get_in_transaction(connection, 'user_memory_items', memory.id, type(memory))
            if item is None or item.status != 'active' or item.archived_at is not None or not memory_origin_available(connection, item):
                continue
            recent.append({'document_id': source['id'], 'text': source['text']})
    # A legacy text adapter uses the same authorized observations. Original
    # structured records are preserved for the enhanced strategy's evidence.
    for memory, source in zip(memories, case['sources'], strict=True):
        if source['id'] not in {item['document_id'] for item in recent}:
            continue
        repository.add_user_memory_item(memory.model_copy(update={
            'id': 'legacy_' + memory.id, 'facts': None, 'memory_type': 'note', 'provenance': None,
            'summary': source['text'], 'source_kind': 'note',
        }))
    retrieved = MemoryContextService(repository).retrieve(case['query']['predicate'], user=owner,
        agent_id=owner.personal_agent_id, project_id=owner.default_project_id, record_metrics=False)
    return {'no_long_term': '', 'recent_history_summary': json.dumps(recent[-20:], ensure_ascii=False),
            'governed_fts': retrieved.rendered_context,
            'enhanced_memory': result.model_dump_json()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=DEFAULT_DATASET)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--mode', choices=['scripted', 'real'], default='scripted')
    parser.add_argument('--model')
    parser.add_argument('--case-ids')
    parser.add_argument('--token-cap', type=int)
    args = parser.parse_args()
    if args.mode == 'real' and (not args.model or not args.case_ids or args.token_cap is None
                               or not 1 <= args.token_cap <= 500000 or args.output is None):
        print('real_evaluation_requires_explicit_model_batch_and_budget', file=sys.stderr)
        return 2
    try:
        dataset, digest = load_dataset(args.dataset)
    except (ValueError, KeyError, TypeError, OSError):
        print('dataset_case_distribution_invalid', file=sys.stderr)
        return 2
    # Set isolation before importing any module that creates the global store.
    with tempfile.TemporaryDirectory(prefix='agentmesh-memory-eval-') as directory:
        os.environ['AGENTMESH_DB_PATH'] = str(Path(directory) / 'bootstrap.sqlite3')
        sys.path.insert(0, str(ROOT))
        if args.mode == 'real':
            from eval.memory_quality import run_quality_batch

            return run_quality_batch(dataset, digest, Path(directory), args)
        results = [run_case(Path(directory) / f'case_{index}.sqlite3', case) for index, case in enumerate(dataset['cases'])]
    report = {'schema_version': 'memory-control-replay-v1', 'mode': 'scripted',
              'fixture_type': dataset['fixture_type'], 'dataset_sha256': digest,
              'case_count': len(results), 'passed_count': sum(case['passed'] for case in results),
              'by_category': dict(Counter(case['category'] for case in results)), 'model_tokens': 0,
              'real_model_quality': False, 'answer_correctness': None, 'fact_extraction_quality': None,
              'four_baseline_quality_comparison': None, 'procedure_trace_quality': None,
              'evidence_boundary': dataset['evidence_boundary'], 'cases': results}
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + '\n'
    if args.output:
        args.output.write_text(rendered)
    print(rendered, end='')
    return 0 if report['passed_count'] == report['case_count'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
