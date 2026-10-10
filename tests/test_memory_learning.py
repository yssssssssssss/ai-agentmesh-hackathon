from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from agentmesh.memory_facts import MemoryFactsService, document_evidence_hash
from agentmesh.memory_learning.contracts import (
    DocumentLearnRequestV1,
    ExtractionResultV1,
    LearningConfirmationV1,
    MemoryPreferencesPatchV1,
)
from agentmesh.memory_learning.service import MemoryLearningError, MemoryLearningService
from agentmesh.memory_lifecycle import MemoryForgetRequestV1, MemoryForgettingService
from agentmesh.memory_payloads import FactQueryV1
from agentmesh.models import DocumentRecord, Project, Source, User
from agentmesh.skill_runtime.quiesce import OrchestrationQuiesceController
from agentmesh.store import SQLiteStore

NOW = datetime(2026, 10, 4, tzinfo=UTC)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def learning_project(tmp_path):
    store = SQLiteStore(tmp_path / 'learning.sqlite3')
    user = store.save_user(User(id='owner', name='Owner', role='user', workspace_id='ws', default_project_id='project',
                               personal_agent_id='agent'))
    peer = store.save_user(user.model_copy(update={'id': 'peer'}))
    store.save_project(Project(id='project', workspace_id='ws', name='Pilot', goal='Deliver', member_ids=[user.id, peer.id]))
    source = store.add_source(Source(id='source', title='Assignment', source_type='document', reference='local://doc',
                                     workspace_id='ws', project_id='project', user_id=user.id))
    doc = store.add_document(DocumentRecord(id='doc', title='Assignment', text='Bob owns the project.',
                                            source=source, workspace_id='ws', project_id='project', uploaded_by=user.id,
                                            file_name='assignment.txt', content_type='text/plain'))
    service = MemoryLearningService(store, clock=lambda: NOW, mode_provider=lambda: 'execute',
                                    admission=OrchestrationQuiesceController())
    yield store, user, peer, doc, service
    store.close()


def enable(service, user):
    return service.patch_preferences(MemoryPreferencesPatchV1(command_id='enable', expected_version=1,
                                                               learning_enabled=True), user)


def enqueue(service, user, doc):
    return service.enqueue(DocumentLearnRequestV1(source_document_id=doc.id, source_version=doc.version,
                                                   source_hash=document_evidence_hash(doc)), user)


def extracted(doc):
    return ExtractionResultV1.model_validate({'title': 'Candidate owner', 'summary': 'Suggested assignment', 'facts': [{
        'assertion': {'subject_type': 'project', 'subject_id': 'project', 'predicate': 'owner', 'value': 'Bob',
                      'time_precision': 'unknown'}, 'start': 0, 'end': len(doc.text), 'quote': doc.text,
    }]})


class ScriptedExtractor:
    def __init__(self, result, action=None):
        self.result = result
        self.action = action
        self.calls = 0

    async def extract(self, document, actor, *, max_output_tokens):
        self.calls += 1
        assert max_output_tokens > 0
        if self.action:
            self.action()
        return self.result, 120


@pytest.mark.anyio
@pytest.mark.parametrize('headers,delay', [
    ({'retry-after': '120'}, 120),
    ({'retry-after-ms': '12500'}, 12.5),
    ({'retry-after': 'Sun, 04 Oct 2026 00:02:00 GMT'}, 120),
    ({'retry-after': 'not a valid date'}, 5),
    ({'retry-after': 'nan'}, 5),
    ({'retry-after': '-1'}, 5),
])
async def test_rate_limit_respects_retry_timing_and_keeps_unknown_usage(learning_project, headers, delay):
    import httpx
    from openai import RateLimitError

    store, user, peer, doc, service = learning_project
    enable(service, user)
    job = enqueue(service, user, doc)

    class LimitedExtractor:
        async def extract(self, *args, **kwargs):
            response = httpx.Response(429, headers=headers, request=httpx.Request('POST', 'https://unit.test/model'))
            raise RateLimitError('sensitive Provider error text', response=response, body={'secret': 'not persisted'})

    assert await service.run_once(LimitedExtractor()) == 1
    saved = service.repository.job(job.id)
    assert saved.status == 'retry_wait' and saved.next_attempt_at == NOW + timedelta(seconds=delay)
    assert saved.usage_status == 'unknown' and saved.unreported_attempts == 1 and saved.reserved_tokens > 0
    assert 'sensitive Provider' not in saved.model_dump_json() and 'secret' not in saved.model_dump_json()
    service.clock = lambda: NOW + timedelta(seconds=delay - .1)
    assert service.claim_next() is None
    service.clock = lambda: NOW + timedelta(seconds=delay)
    assert service.claim_next().attempt == 2


@pytest.mark.anyio
async def test_unbounded_provider_retry_window_blocks_without_shortening_it(learning_project):
    import httpx
    from openai import RateLimitError

    store, user, peer, doc, service = learning_project
    enable(service, user)
    job = enqueue(service, user, doc)

    class LimitedExtractor:
        async def extract(self, *args, **kwargs):
            response = httpx.Response(429, headers={'retry-after': '172800'},
                                      request=httpx.Request('POST', 'https://unit.test/model'))
            raise RateLimitError('Unavailable', response=response, body=None)

    assert await service.run_once(LimitedExtractor()) == 1
    saved = service.repository.job(job.id)
    assert saved.status == 'blocked' and saved.next_attempt_at is None
    assert saved.error_code == 'memory_learning_retry_window_unavailable'
    assert saved.reserved_tokens > 0 and service.claim_next() is None


def test_learning_heartbeat_renews_only_current_live_lease(learning_project):
    store, user, peer, doc, service = learning_project
    enable(service, user)
    job = enqueue(service, user, doc)
    claimed = service.claim_next()
    service.clock = lambda: NOW + timedelta(seconds=60)
    assert service.heartbeat(claimed)
    renewed = service.repository.job(job.id)
    assert renewed.lease_expires_at == NOW + timedelta(seconds=180)
    assert renewed.reserved_tokens == claimed.reserved_tokens and renewed.attempt == claimed.attempt
    assert not service.heartbeat(claimed.model_copy(update={'lease_epoch': claimed.lease_epoch + 1}))
    service.clock = lambda: renewed.lease_expires_at
    assert not service.heartbeat(claimed)
    assert service.repository.job(job.id).lease_expires_at == renewed.lease_expires_at


@pytest.mark.parametrize('change', ['pause', 'withdraw', 'mode_off'])
def test_learning_heartbeat_stops_after_policy_or_source_changes(learning_project, change):
    store, user, peer, doc, service = learning_project
    enable(service, user)
    job = enqueue(service, user, doc)
    claimed = service.claim_next()
    if change == 'pause':
        service.patch_preferences(MemoryPreferencesPatchV1(command_id='pause-heartbeat', expected_version=2,
                                                            learning_enabled=False), user)
    elif change == 'withdraw':
        MemoryForgettingService(store).withdraw_document(doc.id, MemoryForgetRequestV1(command_id='withdraw-heartbeat',
                                                                                      expected_version=1), user)
    else:
        service.mode_provider = lambda: 'off'
    assert not service.heartbeat(claimed)
    saved = service.repository.job(job.id)
    assert saved.status == 'cancelled' and saved.lease_expires_at is None
    assert saved.reserved_tokens == claimed.reserved_tokens


@pytest.mark.anyio
async def test_worker_renews_during_actual_extraction_wait(learning_project, monkeypatch):
    store, user, peer, doc, service = learning_project
    enable(service, user)
    job = enqueue(service, user, doc)
    renewed = asyncio.Event()
    heartbeat = service.heartbeat
    monkeypatch.setattr('agentmesh.memory_learning.service.LEASE_HEARTBEAT_SECONDS', .001)

    def observed_heartbeat(claimed):
        result = heartbeat(claimed)
        renewed.set()
        return result

    monkeypatch.setattr(service, 'heartbeat', observed_heartbeat)

    class WaitingExtractor:
        async def extract(self, *args, **kwargs):
            service.clock = lambda: NOW + timedelta(seconds=60)
            await renewed.wait()
            return extracted(doc), 120

    assert await asyncio.wait_for(service.run_once(WaitingExtractor()), timeout=2) == 1
    saved = service.repository.job(job.id)
    assert renewed.is_set() and saved.status == 'completed'
    assert saved.attempt == 1 and saved.actual_tokens == 120 and saved.usage_status == 'reported'


@pytest.mark.anyio
async def test_worker_cancels_waiting_extraction_after_opt_out(learning_project, monkeypatch):
    store, user, peer, doc, service = learning_project
    enable(service, user)
    job = enqueue(service, user, doc)
    cancelled = asyncio.Event()
    monkeypatch.setattr('agentmesh.memory_learning.service.LEASE_HEARTBEAT_SECONDS', .001)

    class WaitingExtractor:
        async def extract(self, *args, **kwargs):
            service.patch_preferences(MemoryPreferencesPatchV1(command_id='opt-out-waiting', expected_version=2,
                                                                learning_enabled=False), user)
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    assert await asyncio.wait_for(service.run_once(WaitingExtractor()), timeout=2) == 1
    saved = service.repository.job(job.id)
    assert cancelled.is_set() and saved.status == 'cancelled' and not store.user_memory_items
    assert saved.reserved_tokens > 0 and saved.usage_status == 'unknown'


def test_learning_health_is_owned_scoped_and_reports_due_wait_only(learning_project):
    store, user, peer, doc, service = learning_project
    enable(service, user)
    job = enqueue(service, user, doc)
    with store._connect() as connection:
        service.repository.save(connection, job.model_copy(update={'id': 'peer-health-job', 'user_id': peer.id}))
    assert service.status(peer).queue.ready == 1
    service.clock = lambda: NOW + timedelta(seconds=300)
    status = service.status(user)
    assert status.queue.ready == 1 and status.queue.oldest_ready_age_seconds == 300
    assert status.alerts == ['queue_delayed']
    claimed = service.claim_next()
    assert service.status(user).queue.running == 1 and not service.status(user).alerts
    service.fail(claimed, 'memory_learning_transient_failure', transient=True,
                 retry_at=NOW + timedelta(hours=1))
    assert service.status(user).queue.oldest_ready_age_seconds is None
    service.clock = lambda: NOW + timedelta(hours=1, seconds=301)
    status = service.status(user)
    assert status.queue.ready == 1 and status.queue.oldest_ready_age_seconds == 301
    assert status.alerts == ['queue_delayed', 'usage_unreported']
    store.save_project(store.get_project('project').model_copy(update={'member_ids': [peer.id]}))
    assert service.status(user).queue.ready == 0 and service.status(user).queue.retry_wait == 0
    assert not service.status(user).alerts


def test_learning_health_reports_expired_lease_budget_and_cleanup_backlog(learning_project):
    store, user, peer, doc, service = learning_project
    enable(service, user)
    enqueue(service, user, doc)
    service.claim_next()
    service.clock = lambda: NOW + timedelta(seconds=121)
    status = service.status(user)
    assert status.queue.expired_leases == 1 and 'lease_expired' in status.alerts
    assert status.queue.unreported_attempts == 1
    with store._connect() as connection:
        connection.execute("INSERT INTO records(collection, id, payload) VALUES ('memory_learning_budgets', ?, ?) "
                           'ON CONFLICT(collection, id) DO UPDATE SET payload=excluded.payload',
                           (service._ledger_id(user, service.clock()), '{"reserved_tokens": 64000}'))
    MemoryForgettingService(store, clock=lambda: NOW).withdraw_document(
        doc.id, MemoryForgetRequestV1(command_id='cleanup-health', expected_version=1), user,
    )
    status = service.status(user)
    assert status.cleanup_pending == 1 and status.queue.oldest_cleanup_age_seconds == 121
    assert 'budget_exhausted' in status.alerts and 'cleanup_delayed' in status.alerts
    assert service.status(peer).cleanup_pending == 0 and not service.status(peer).alerts


def test_learning_health_api_exposes_only_owned_metadata(learning_project, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from agentmesh.routes import memory_learning

    store, user, peer, doc, service = learning_project
    enable(service, user)
    enqueue(service, user, doc)
    app = FastAPI()
    app.include_router(memory_learning.router)
    app.dependency_overrides[memory_learning.current_user] = lambda: user
    monkeypatch.setattr(memory_learning, 'learning_service', lambda: service)
    with TestClient(app) as client:
        response = client.get('/api/memory/learning/status')
        assert response.status_code == 200 and response.json()['queue']['ready'] == 1
        assert doc.text not in response.text and doc.source.reference not in response.text
        app.dependency_overrides[memory_learning.current_user] = lambda: peer
        assert client.get('/api/memory/learning/status').json()['queue']['ready'] == 0
        store.save_user(peer.model_copy(update={'status': 'disabled'}))
        assert client.get('/api/memory/learning/status').status_code == 404


def test_learning_is_off_by_default_and_preferences_are_owned_versioned_idempotent(learning_project):
    store, user, peer, doc, service = learning_project
    assert not service.preferences(user).learning_enabled
    with pytest.raises(MemoryLearningError, match='memory_learning_paused'):
        enqueue(service, user, doc)
    saved = enable(service, user)
    assert saved.version == 2 and saved.learning_enabled
    assert enable(service, user) == saved
    assert not service.preferences(peer).learning_enabled
    with pytest.raises(MemoryLearningError, match='memory_preferences_version_conflict'):
        service.patch_preferences(MemoryPreferencesPatchV1(command_id='stale', expected_version=1,
                                                            learning_enabled=False), user)
    store.close()
    reopened = SQLiteStore(store.db_path)
    try:
        assert MemoryLearningService(reopened).preferences(user) == saved
    finally:
        reopened.close()


@pytest.mark.anyio
async def test_document_learning_is_durable_deduplicated_private_and_requires_confirmation(learning_project):
    store, user, peer, doc, service = learning_project
    enable(service, user)
    job = enqueue(service, user, doc)
    assert enqueue(service, user, doc).id == job.id
    worker = ScriptedExtractor(extracted(doc))
    assert await service.run_once(worker) == 1
    assert await service.run_once(worker) == 0
    assert worker.calls == 1
    finished = service.get_job(job.id, user)
    assert finished.status == 'completed' and finished.attempt == 1 and finished.actual_tokens == 120
    memory = store.get_user_memory_item(finished.candidate_memory_id)
    assert memory.status == 'proposed' and memory.scope == 'private'
    assert memory.facts[0].source_classification == 'model_inference'
    assert memory.facts[0].evidence_refs[0].record_type == 'source_span'
    with pytest.raises(MemoryLearningError, match='memory_learning_job_not_found'):
        service.get_job(job.id, peer)
    assert not service.list_jobs(peer)
    with pytest.raises(MemoryLearningError, match='memory_learning_job_not_found'):
        service.confirm(job.id, LearningConfirmationV1(command_id='confirm', expected_memory_version=1,
                                                        selected_fact_indexes=[0]), peer)
    request = LearningConfirmationV1(command_id='confirm', expected_memory_version=1, selected_fact_indexes=[0])
    confirmed = service.confirm(job.id, request, user)
    assert confirmed.status == 'active' and confirmed.version == 2
    assert confirmed.facts[0].source_classification == 'human_confirmed'
    assert service.confirm(job.id, request, user) == confirmed
    assert confirmed.facts[0].time_precision == 'unknown'
    result = MemoryFactsService(store).query(FactQueryV1(project_id='project', subject_type='project',
                                                       subject_id='project', predicate='owner'), user)
    assert result.outcome == 'insufficient_evidence'
    assert 'fact_valid_time_unknown' in result.missing_data


@pytest.mark.anyio
@pytest.mark.parametrize('change', ['withdraw', 'edit', 'pause', 'revoke', 'disable'])
async def test_late_learning_cannot_publish_after_source_policy_or_authorization_changes(learning_project, change):
    store, user, peer, doc, service = learning_project
    enable(service, user)
    job = enqueue(service, user, doc)

    def mutate():
        if change == 'withdraw':
            MemoryForgettingService(store).withdraw_document(doc.id, MemoryForgetRequestV1(command_id='withdraw',
                                                                                           expected_version=1), user)
        elif change == 'edit':
            store.save_document(doc.model_copy(update={'text': 'Alice is owner.', 'version': 2}))
        elif change == 'pause':
            service.patch_preferences(MemoryPreferencesPatchV1(command_id='pause', expected_version=2,
                                                                learning_enabled=False), user)
        elif change == 'revoke':
            store.save_project(store.get_project('project').model_copy(update={'member_ids': [peer.id]}))
        else:
            store.save_user(user.model_copy(update={'status': 'disabled'}))

    worker = ScriptedExtractor(extracted(doc), action=mutate)
    assert await service.run_once(worker) == 1
    assert not store.user_memory_items
    assert service.repository.job(job.id).status in {'cancelled', 'blocked'}


@pytest.mark.anyio
async def test_invented_or_out_of_range_quotes_are_rejected_without_a_candidate(learning_project):
    store, user, _, doc, service = learning_project
    enable(service, user)
    job = enqueue(service, user, doc)
    invalid = extracted(doc).model_copy(deep=True)
    invalid.facts[0].quote = 'Alice owns the project.'
    worker = ScriptedExtractor(invalid)
    await service.run_once(worker)
    assert service.get_job(job.id, user).status == 'failed'
    assert service.get_job(job.id, user).error_code == 'memory_learning_quote_mismatch'
    assert not store.user_memory_items


@pytest.mark.anyio
async def test_missing_model_is_blocked_and_never_creates_template_memory(learning_project):
    store, user, _, doc, service = learning_project
    enable(service, user)
    job = enqueue(service, user, doc)

    class Unavailable:
        async def extract(self, *args, **kwargs):
            raise MemoryLearningError('model_unavailable')

    await service.run_once(Unavailable())
    assert service.get_job(job.id, user).status == 'blocked'
    assert not store.user_memory_items


@pytest.mark.anyio
async def test_claims_are_fenced_and_recovered_with_a_fixed_attempt_and_token_cap(learning_project):
    store, user, _, doc, service = learning_project
    enable(service, user)
    job = enqueue(service, user, doc)
    first = service.claim_next()
    assert first.id == job.id and first.attempt == 1
    assert service.claim_next() is None
    later = MemoryLearningService(store, clock=lambda: NOW + timedelta(minutes=3), mode_provider=lambda: 'execute')
    second = later.claim_next()
    assert second.id == job.id and second.attempt == 2 and second.lease_epoch > first.lease_epoch
    assert not service.apply(first, extracted(doc), actual_tokens=120)
    assert later.apply(second, extracted(doc), actual_tokens=120)
    finished = later.get_job(job.id, user)
    assert finished.reserved_tokens <= finished.token_cap
    assert len(store.user_memory_items) == 1


@pytest.mark.anyio
async def test_source_withdrawn_after_candidate_cannot_be_confirmed_or_relearned(learning_project):
    store, user, _, doc, service = learning_project
    enable(service, user)
    job = enqueue(service, user, doc)
    await service.run_once(ScriptedExtractor(extracted(doc)))
    MemoryForgettingService(store).withdraw_document(doc.id, MemoryForgetRequestV1(command_id='withdraw',
                                                                                   expected_version=1), user)
    with pytest.raises(MemoryLearningError):
        service.confirm(job.id, LearningConfirmationV1(command_id='confirm', expected_memory_version=1,
                                                        selected_fact_indexes=[0]), user)
    with pytest.raises(MemoryLearningError, match='memory_learning_source_not_found'):
        enqueue(service, user, doc)
    assert store.get_user_memory_item(service.get_job(job.id, user).candidate_memory_id).status == 'forgotten'


@pytest.mark.anyio
async def test_sdk_extractor_caps_output_and_transport_retries_and_requires_real_usage(learning_project, monkeypatch):
    from types import SimpleNamespace

    from agentmesh.memory_learning.extractor import SDKDocumentExtractor

    store, user, _, doc, _ = learning_project
    selected = SimpleNamespace(model='scripted-model', client=None)
    arguments = {}

    def select(actor, **kwargs):
        arguments.update(kwargs)
        return selected

    async def run(agent, input, **kwargs):
        assert agent.model_settings.max_tokens == 2000
        assert agent.model_settings.retry.max_retries == 0
        assert agent.tools == []
        assert kwargs['max_turns'] == 1
        assert kwargs['run_config'].tracing_disabled
        assert not kwargs['run_config'].trace_include_sensitive_data
        assert doc.text in input
        return SimpleNamespace(final_output=extracted(doc), raw_responses=[SimpleNamespace(
            usage=SimpleNamespace(total_tokens=137),
        )])

    extractor = SDKDocumentExtractor(store)
    monkeypatch.setattr(extractor.factory, 'for_user', select)
    monkeypatch.setattr('agentmesh.memory_learning.extractor.Runner.run', run)
    output, tokens = await extractor.extract(doc, user, max_output_tokens=2000)
    assert output == extracted(doc) and tokens == 137
    assert arguments == {'timeout_seconds': 85, 'max_retries': 0}

    async def missing_usage(*args, **kwargs):
        return SimpleNamespace(final_output=extracted(doc), raw_responses=[])

    monkeypatch.setattr('agentmesh.memory_learning.extractor.Runner.run', missing_usage)
    with pytest.raises(MemoryLearningError, match='memory_learning_usage_unavailable'):
        await extractor.extract(doc, user, max_output_tokens=2000)


def test_api_reads_sources_and_candidates_only_for_their_owner(learning_project, monkeypatch):
    import asyncio

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from agentmesh.routes import memory_learning
    from agentmesh.routes.deps import current_user

    store, user, peer, doc, service = learning_project
    enable(service, user)
    job = enqueue(service, user, doc)
    asyncio.run(service.run_once(ScriptedExtractor(extracted(doc))))
    candidate = service.candidate(job.id, user)
    span_id = candidate.facts[0].evidence_refs[0].record_id
    monkeypatch.setattr(memory_learning, 'store', store)
    monkeypatch.setattr(memory_learning, 'learning_service', lambda: service)
    app = FastAPI()
    app.include_router(memory_learning.router)
    app.dependency_overrides[current_user] = lambda: user
    client = TestClient(app)
    assert client.get('/api/memory/preferences').status_code == 200
    assert client.get(f'/api/memory/learning/jobs/{job.id}/candidate').status_code == 200
    assert client.get(f'/api/memory/source-spans/{span_id}').json()['quote'] == doc.text
    app.dependency_overrides[current_user] = lambda: peer
    assert client.get(f'/api/memory/learning/jobs/{job.id}/candidate').status_code == 404
    assert client.get(f'/api/memory/source-spans/{span_id}').status_code == 404
    assert client.post(f'/api/memory/{candidate.id}/forget', json={'command_id': 'peer-forget',
                                                                 'expected_version': 1}).status_code == 404
    app.dependency_overrides[current_user] = lambda: user
    assert client.post(f'/api/memory/sources/documents/{doc.id}/withdraw', json={'command_id': 'withdraw',
                                                                              'expected_version': 1}).status_code == 200
    assert client.get(f'/api/memory/source-spans/{span_id}').status_code == 404


@pytest.mark.anyio
async def test_transient_errors_retry_with_a_durable_budget_but_auth_errors_do_not(learning_project):
    store, user, _, doc, service = learning_project
    enable(service, user)
    job = enqueue(service, user, doc)

    class TimeoutExtractor:
        async def extract(self, *args, **kwargs):
            raise TimeoutError('secret provider detail')

    await service.run_once(TimeoutExtractor())
    waiting = service.get_job(job.id, user)
    assert waiting.status == 'retry_wait' and waiting.usage_status == 'unknown'
    assert waiting.error_code == 'memory_learning_transient_failure'
    assert service.claim_next() is None
    later = MemoryLearningService(store, clock=lambda: NOW + timedelta(seconds=5), mode_provider=lambda: 'execute')
    await later.run_once(ScriptedExtractor(extracted(doc)))
    finished = later.get_job(job.id, user)
    assert finished.attempt == 2 and finished.status == 'completed' and finished.actual_tokens == 120
    assert finished.reserved_tokens > waiting.reserved_tokens


def test_global_off_observe_and_quiescing_never_admit_a_model_call(learning_project):
    import asyncio

    store, user, _, doc, service = learning_project
    enable(service, user)
    job = enqueue(service, user, doc)
    for mode in ('off', 'observe'):
        inactive = MemoryLearningService(store, mode_provider=lambda mode=mode: mode)
        worker = ScriptedExtractor(extracted(doc))
        assert asyncio.run(inactive.run_once(worker)) == 0 and worker.calls == 0
        with pytest.raises(MemoryLearningError, match='memory_learning_unavailable'):
            enqueue(inactive, user, doc)
    assert service.get_job(job.id, user).attempt == 0
    asyncio.run(service.admission.begin_quiesce())
    assert service.claim_next() is None


def test_daily_budget_is_independent_of_chat_and_is_not_refunded_after_a_crash(learning_project):
    _, user, _, doc, service = learning_project
    service.patch_preferences(MemoryPreferencesPatchV1(command_id='limited', expected_version=1,
                                                        learning_enabled=True, daily_token_cap=4000), user)
    job = enqueue(service, user, doc)
    assert service.claim_next() is None
    blocked = service.get_job(job.id, user)
    assert blocked.status == 'blocked' and blocked.error_code == 'memory_learning_daily_budget_exhausted'
    assert blocked.reserved_tokens == 0


@pytest.mark.anyio
async def test_upload_uses_the_current_authorized_workspace_and_project(learning_project, monkeypatch):
    from io import BytesIO

    from fastapi import Response, UploadFile

    from agentmesh.documents import PlainTextDocumentParser
    from agentmesh.ingestion import DocumentIngestionService
    from agentmesh.routes import documents

    store, user, _, _, _ = learning_project
    ingestion = DocumentIngestionService(repository=store, parser=PlainTextDocumentParser())
    monkeypatch.setattr(documents, 'store', store)
    monkeypatch.setattr(documents, 'ingestion_service', ingestion)
    try:
        result = await documents.upload_document(Response(), UploadFile(filename='pilot.txt', file=BytesIO(b'Project note.')), user)
        assert result['item'].workspace_id == user.workspace_id
        assert result['item'].project_id == user.default_project_id
        assert result['item'].uploaded_by == user.id
    finally:
        ingestion.shutdown()


def test_admin_document_visibility_still_obeys_the_workspace_boundary(learning_project):
    from agentmesh.routes.documents import document_visible_to_user

    _, user, _, doc, _ = learning_project
    foreign_admin = user.model_copy(update={'id': 'foreign_admin', 'role': 'admin', 'workspace_id': 'other'})
    assert not document_visible_to_user(doc, foreign_admin)


def test_observation_discovers_owned_sources_once_and_skips_unapproved_users_projects(learning_project):
    store, user, peer, doc, service = learning_project
    assert service.discover_sources() == 0
    enable(service, user)
    store.add_document(doc.model_copy(update={'id': 'peer_doc', 'uploaded_by': peer.id}))
    store.save_project(Project(id='private_project', workspace_id='ws', name='Other', goal='Other', member_ids=[peer.id]))
    store.add_document(doc.model_copy(update={'id': 'revoked_doc', 'project_id': 'private_project'}))
    assert service.discover_sources() == 1
    assert service.discover_sources() == 0
    assert [job.source_document_id for job in service.list_jobs(user)] == [doc.id]
    assert not service.list_jobs(peer)
    store.save_document(doc.model_copy(update={'version': 2, 'text': 'A changed assignment.'}))
    assert service.discover_sources() == 1
    assert len(service.list_jobs(user)) == 2


def test_manual_retry_keeps_attempt_reservations_and_can_resume_after_pausing(learning_project):
    from agentmesh.memory_learning.contracts import LearningRetryRequestV1

    _, user, _, doc, service = learning_project
    enable(service, user)
    job = enqueue(service, user, doc)
    claimed = service.claim_next()
    service.fail(claimed, 'model_unavailable')
    request = LearningRetryRequestV1(command_id='retry', expected_lease_epoch=claimed.lease_epoch)
    replay = service.retry(job.id, request, user)
    assert replay.status == 'queued' and replay.attempt == 1 and replay.reserved_tokens == claimed.reserved_tokens
    assert service.retry(job.id, request, user) == replay
    second = service.claim_next()
    assert second.attempt == 2 and second.reserved_tokens > replay.reserved_tokens
    assert service.status(user).daily_reserved_tokens == second.reserved_tokens
