"""Isolated authorized Memory retrieval workload; no real model or embeddings.

Reports SQLite execute/fetch, connection setup, and Python RRF independently.
SQLite timing includes row transfer but excludes Pydantic model hydration.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]


def percentile(values: list[float], p: float) -> float:
    return sorted(values)[max(0, math.ceil(len(values) * p) - 1)]


class MeasuredCursor:
    def __init__(self, cursor, local):
        self.cursor, self.local = cursor, local

    def _fetch(self, method, *args):
        started = perf_counter()
        try:
            return getattr(self.cursor, method)(*args)
        finally:
            self.local.db_ms += (perf_counter() - started) * 1000

    def fetchall(self):
        return self._fetch('fetchall')

    def fetchone(self):
        return self._fetch('fetchone')

    def __getattr__(self, name):
        return getattr(self.cursor, name)


class MeasuredConnection:
    def __init__(self, connection, local):
        self.connection, self.local = connection, local

    def execute(self, *args):
        started = perf_counter()
        try:
            return MeasuredCursor(self.connection.execute(*args), self.local)
        finally:
            self.local.db_ms += (perf_counter() - started) * 1000

    def __enter__(self):
        self.connection.__enter__()
        return self

    def __exit__(self, *args):
        return self.connection.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self.connection, name)


class MeasuredLock:
    def __init__(self, lock, local):
        self.lock, self.local = lock, local

    def __enter__(self):
        started = perf_counter()
        self.lock.acquire()
        self.local.wait_ms += (perf_counter() - started) * 1000

    def __exit__(self, *args):
        self.lock.release()


def seed_workload(repository, count: int):
    from agentmesh.models import MemoryItem, Project, Source, User, UserMemoryItem, Workspace
    from agentmesh.store import _extract_fts_doc

    user = repository.save_user(User(id='bench_owner', name='Fixture owner', role='user', workspace_id='bench_ws',
                                     default_project_id='bench_project', personal_agent_id='bench_agent'))
    repository.save_workspace(Workspace(id=user.workspace_id, name='Synthetic benchmark', description='Isolated workload'))
    repository.save_project(Project(id=user.default_project_id, workspace_id=user.workspace_id, name='Benchmark',
                                     goal='Measure authorized retrieval', member_ids=[user.id]))
    instant = datetime(2026, 10, 1, tzinfo=UTC)
    source = Source(id='bench_source', title='Synthetic benchmark records', source_type='benchmark',
                    reference='benchmark://synthetic-memory-v1')
    personal = UserMemoryItem(id='placeholder', user_id=user.id, workspace_id=user.workspace_id,
                             layer='mid_term',
                             project_id=user.default_project_id, title='检索容量案例', summary='项目检索容量与授权过滤的合成记录。',
                             source_kind='synthetic_fixture', sources=[source], created_at=instant, updated_at=instant)
    shared = MemoryItem(id='placeholder', title=personal.title, summary=personal.summary, memory_type='event',
                        scope='team_accepted', status='accepted', owner_user_id=user.id, workspace_id=user.workspace_id,
                        project_id=user.default_project_id, sources=[source], created_at=instant, updated_at=instant)
    templates = [
        ('visible_private', 'user_memory_items', personal.model_dump(mode='json')),
        ('visible_team', 'memory_items', shared.model_dump(mode='json')),
        ('other_private', 'user_memory_items', personal.model_copy(update={'user_id': 'bench_peer'}).model_dump(mode='json')),
        ('other_workspace', 'memory_items', shared.model_copy(update={'workspace_id': 'other_ws',
                                                                     'project_id': 'other_project'}).model_dump(mode='json')),
    ]
    with repository._connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        for index in range(count):
            bucket, collection, template = templates[index % len(templates)]
            payload = {**template, 'id': f'{bucket}_{index:06d}'}
            connection.execute('INSERT INTO records(collection, id, payload) VALUES (?, ?, ?)',
                               (collection, payload['id'], json.dumps(payload, ensure_ascii=False)))
            model = UserMemoryItem if collection == 'user_memory_items' else MemoryItem
            # Every fixture ID is new: avoid the production replacement DELETE
            # scanning an ever-growing FTS table during bulk fixture creation.
            doc = _extract_fts_doc(collection, model.model_validate(payload))
            assert doc is not None
            connection.execute(
                'INSERT INTO records_fts(collection, record_id, title, body, scope, workspace_id, '
                'project_id, user_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (doc.collection, doc.record_id, doc.title, doc.body, doc.scope, doc.workspace_id,
                 doc.project_id, doc.user_id, doc.created_at),
            )
    return user


def run_benchmark(*, records: int = 50_000, concurrency: int = 10, queries: int = 100,
                  scope: str = 'auto') -> dict:
    from agentmesh.memory_context.service import MemoryContextService
    from agentmesh.models import MemorySearchScope
    from agentmesh.store import SQLiteStore

    if scope not in {'auto', 'personal', 'team'}:
        raise ValueError('unsupported_benchmark_scope')

    with tempfile.TemporaryDirectory(prefix='agentmesh-memory-benchmark-') as directory:
        repository = SQLiteStore(Path(directory) / 'benchmark.sqlite3')
        try:
            user = seed_workload(repository, records)
            service = MemoryContextService(repository)
            local = threading.local()
            search = repository.search
            connect, read_connect, rrf = repository._connect, repository._read_connect, repository._rrf_merge

            def connection_factory(factory):
                def measured_connect():
                    started = perf_counter()
                    connection = factory()
                    local.connect_ms += (perf_counter() - started) * 1000
                    return MeasuredConnection(connection, local)
                return measured_connect

            def measured_rrf(*args, **kwargs):
                started = perf_counter()
                try:
                    return rrf(*args, **kwargs)
                finally:
                    local.rrf_ms += (perf_counter() - started) * 1000

            def measured_search(*args, **kwargs):
                started = perf_counter()
                try:
                    return search(*args, **kwargs)
                finally:
                    local.store_ms += (perf_counter() - started) * 1000

            repository.search = measured_search
            repository._connect = connection_factory(connect)
            repository._read_connect = connection_factory(read_connect)
            repository._rrf_merge = measured_rrf
            repository._fts_lock = MeasuredLock(repository._fts_lock, local)

            def query(index: int):
                local.store_ms = local.db_ms = local.connect_ms = local.rrf_ms = local.wait_ms = 0.0
                started = perf_counter()
                bundle = service.retrieve('检索容量案例', user=user, agent_id=user.personal_agent_id,
                                          requested_scope=MemorySearchScope(scope), record_metrics=False)
                elapsed = (perf_counter() - started) * 1000
                prefixes = {'auto': ('visible_private_', 'visible_team_'), 'personal': ('visible_private_',),
                            'team': ('visible_team_',)}[scope]
                visible = all(hit.memory_id.startswith(prefixes) for hit in bundle.hits)
                return {'index': index, 'milliseconds': elapsed, 'store_search_ms': local.store_ms,
                        'db_execute_fetch_ms': local.db_ms, 'db_connect_ms': local.connect_ms,
                        'rrf_ms': local.rrf_ms, 'recall_capacity_wait_ms': local.wait_ms, 'hits': len(bundle.hits),
                        'authorized': visible and len(bundle.hits) == 8}

            warmup = query(-1)
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                observations = list(executor.map(query, range(queries)))
            latency = [item['milliseconds'] for item in observations]
            p95 = percentile(latency, .95)
            return {
                'schema_version': 'memory-retrieval-benchmark-v1', 'fixture': 'isolated-synthetic-records',
                'records': records, 'concurrency': concurrency, 'queries': queries, 'warmup_ms': warmup['milliseconds'],
                'requested_scope': scope,
                'p50_ms': percentile(latency, .5), 'p95_ms': p95, 'max_ms': max(latency),
                'store_search_p95_ms': percentile([item['store_search_ms'] for item in observations], .95),
                'db_execute_fetch_p95_ms': percentile([item['db_execute_fetch_ms'] for item in observations], .95),
                'db_connect_p95_ms': percentile([item['db_connect_ms'] for item in observations], .95),
                'rrf_p95_ms': percentile([item['rrf_ms'] for item in observations], .95),
                'recall_capacity_wait_p95_ms': percentile([item['recall_capacity_wait_ms'] for item in observations], .95),
                'embedding_ms': 0, 'embedding_mode': 'disabled', 'external_rerank_ms': 0,
                'rerank_mode': 'no_external_reranker; Python RRF reported separately; bm25 in SQL span',
                'db_timing_method': 'execute plus fetch, including row transfer; connection/PRAGMAs separate',
                'db_instrumentation_complete': True, 'bulk_memory_pool_hydration': False,
                'all_authorized': warmup['authorized'] and all(item['authorized'] for item in observations),
                'latency_target_ms': 1000, 'latency_target_passed': p95 <= 1000,
                'samples': observations, 'real_model_tokens': 0, 'enterprise_provider_smoke': False,
            }
        finally:
            repository.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records', type=int, default=50_000)
    parser.add_argument('--concurrency', type=int, default=10)
    parser.add_argument('--queries', type=int, default=100)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scope', choices=['auto', 'personal', 'team'], default='auto')
    args = parser.parse_args()
    if args.records < 32 or not 1 <= args.concurrency <= 32 or args.queries < args.concurrency:
        parser.error('Use at least 32 records and enough queries for 1–32 concurrent workers.')
    # Set before importing application modules; never benchmark the user's DB or providers.
    with tempfile.TemporaryDirectory(prefix='agentmesh-benchmark-bootstrap-') as bootstrap:
        os.environ.update({'AGENTMESH_DB_PATH': str(Path(bootstrap) / 'bootstrap.sqlite3'),
                           'AGENTMESH_SKIP_DOTENV': '1', 'AGENTMESH_EMBEDDING_ENABLED': 'false',
                           'AGENTMESH_O2_COMMAND': 'agentmesh-o2-disabled-for-tests',
                           'AGENTMESH_MEMORY_LEARNING': 'off'})
        sys.path.insert(0, str(ROOT))
        report = run_benchmark(records=args.records, concurrency=args.concurrency, queries=args.queries, scope=args.scope)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('records', 'concurrency', 'queries', 'p95_ms', 'all_authorized',
                                                  'latency_target_passed')}, ensure_ascii=False))
    return 0 if report['all_authorized'] and report['latency_target_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
