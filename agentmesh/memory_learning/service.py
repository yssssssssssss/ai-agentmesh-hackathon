from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from contextlib import closing, suppress
from datetime import UTC, datetime, timedelta
from typing import Protocol

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.memory_facts import (
    MemoryFactsError,
    _record,
    authorize_fact_project,
    document_evidence_hash,
    normalized_subject_id,
    validate_fact_subject,
    validate_memory_payload_evidence,
)
from agentmesh.memory_learning.contracts import (
    EXTRACTION_SCHEMA,
    MAX_OUTPUT_TOKENS,
    DocumentLearnRequestV1,
    DocumentSourceSpanV1,
    ExtractionResultV1,
    LearningConfirmationV1,
    LearningRetryRequestV1,
    MemoryLearningJobV1,
    MemoryLearningStatusV1,
    MemoryPreferencesPatchV1,
    MemoryPreferencesV1,
    extraction_token_reservation,
)
from agentmesh.memory_learning.health import learning_alerts, queue_health
from agentmesh.memory_learning.repository import MemoryLearningRepository
from agentmesh.memory_learning.retry import RetryWindowTooLong, provider_retry_at
from agentmesh.memory_payloads import MemoryEvidenceRefV1, MemoryFactV1
from agentmesh.model_registry import resolve_agent_model_id
from agentmesh.models import (
    AuditEvent,
    DocumentRecord,
    InboxItem,
    MemoryLayer,
    MemoryProvenanceV1,
    Scope,
    User,
    UserMemoryItem,
    now_utc,
)
from agentmesh.runtime_admission import current_orchestration_admission
from agentmesh.skill_runtime.quiesce import OrchestrationQuiesceController
from agentmesh.store import SQLiteStore
from agentmesh.tool_runtime.guardrails import unsafe_tool_output_reason

LEASE_HEARTBEAT_SECONDS = 30


def memory_learning_mode() -> str:
    raw = os.getenv('AGENTMESH_MEMORY_LEARNING', 'off').strip().lower()
    return raw if raw in {'off', 'observe', 'execute'} else 'off'


class MemoryLearningError(RuntimeError):
    def __init__(self, code: str, *, status_code: int = 409):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class DocumentExtractor(Protocol):
    async def extract(self, document: DocumentRecord, actor: User, *, max_output_tokens: int) -> tuple[ExtractionResultV1, int]:
        ...


class MemoryLearningService:
    def __init__(self, store: SQLiteStore, *, clock: Callable[[], datetime] = now_utc,
                 mode_provider: Callable[[], str] = memory_learning_mode,
                 admission: OrchestrationQuiesceController | None = None):
        self.store = store
        self.repository = MemoryLearningRepository(store)
        self.clock = clock
        self.mode_provider = mode_provider
        self.admission = admission or current_orchestration_admission()

    @staticmethod
    def _actor(connection, user: User) -> User:
        actor = _record(connection, 'users', user.id, User)
        if actor is None or actor.status != 'active' or actor.workspace_id != user.workspace_id:
            raise MemoryLearningError('memory_learning_actor_unavailable', status_code=404)
        return actor

    def _preferences(self, connection, actor: User) -> MemoryPreferencesV1:
        item = _record(connection, 'memory_preferences', actor.id, MemoryPreferencesV1)
        if item and (item.user_id != actor.id or item.workspace_id != actor.workspace_id):
            raise MemoryLearningError('memory_preferences_integrity_failed')
        return item or MemoryPreferencesV1(id=actor.id, user_id=actor.id, workspace_id=actor.workspace_id,
                                           updated_at=self.clock())

    def preferences(self, user: User) -> MemoryPreferencesV1:
        with closing(self.store._read_connect()) as connection, connection:
            connection.execute('BEGIN')
            return self._preferences(connection, self._actor(connection, user))

    def status(self, user: User) -> MemoryLearningStatusV1:
        with closing(self.store._read_connect()) as connection, connection:
            connection.execute('BEGIN')
            actor = self._actor(connection, user)
            preferences = self._preferences(connection, actor)
            now = self.clock()
            ledger_id = self._ledger_id(actor, now)
            row = connection.execute("SELECT payload FROM records WHERE collection = 'memory_learning_budgets' "
                                     'AND id = ?', (ledger_id,)).fetchone()
            pending = connection.execute('SELECT COUNT(*) FROM memory_tombstones WHERE owner_user_id = ? '
                                         'AND workspace_id = ? AND cleaned_at IS NULL',
                                         (actor.id, actor.workspace_id)).fetchone()[0]
            reserved = json.loads(row['payload'])['reserved_tokens'] if row else 0
            queue = queue_health(connection, actor, now)
            return MemoryLearningStatusV1(
                mode=self.mode_provider(), learning_enabled=preferences.learning_enabled,
                daily_reserved_tokens=reserved, daily_token_cap=preferences.daily_token_cap,
                cleanup_pending=pending, queue=queue,
                alerts=learning_alerts(queue, reserved_tokens=reserved, daily_cap=preferences.daily_token_cap),
            )

    @staticmethod
    def _ledger_id(actor: User, at: datetime) -> str:
        return canonical_json_sha256({'actor': actor.id, 'workspace': actor.workspace_id,
                                       'date': at.astimezone(UTC).date().isoformat()})

    def patch_preferences(self, request: MemoryPreferencesPatchV1, user: User) -> MemoryPreferencesV1:
        request_hash = canonical_json_sha256(request.model_dump(mode='json', exclude_unset=True))
        key = canonical_json_sha256({'actor': user.id, 'command': request.command_id, 'kind': 'preferences'})
        with closing(self.store._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            actor = self._actor(connection, user)
            current = self._preferences(connection, actor)
            receipt = self._receipt(connection, key, request_hash)
            if receipt is not None:
                return current
            if current.version != request.expected_version:
                raise MemoryLearningError('memory_preferences_version_conflict')
            changes = request.model_dump(exclude_unset=True, exclude={'command_id', 'expected_version'})
            if unsafe_tool_output_reason(json.dumps(changes, ensure_ascii=False)):
                raise MemoryLearningError('memory_preferences_requires_review', status_code=422)
            updated = current.model_copy(update={**changes, 'version': current.version + 1, 'updated_at': self.clock()})
            self.store._upsert_plain_record(connection, 'memory_preferences', updated)
            self._save_receipt(connection, key, request_hash, actor.id)
            self._audit(connection, actor, 'update_memory_preferences', actor.id, None,
                        {'preferences_version': updated.version, 'learning_enabled': updated.learning_enabled})
            return updated

    def _source(self, connection, request: DocumentLearnRequestV1, user: User) -> tuple[User, DocumentRecord]:
        actor = self._actor(connection, user)
        document = _record(connection, 'documents', request.source_document_id, DocumentRecord)
        if (document is None or document.withdrawn_at is not None or document.uploaded_by != actor.id
                or document.workspace_id != actor.workspace_id):
            raise MemoryLearningError('memory_learning_source_not_found', status_code=404)
        try:
            authorize_fact_project(connection, actor, document.project_id)
        except MemoryFactsError as error:
            raise MemoryLearningError('memory_learning_project_unavailable', status_code=404) from error
        if document.version != request.source_version or document_evidence_hash(document) != request.source_hash:
            raise MemoryLearningError('memory_learning_source_changed')
        from agentmesh.source_authority import document_source_available

        if not document_source_available(connection, document):
            raise MemoryLearningError('memory_learning_source_changed')
        return actor, document

    def enqueue(self, request: DocumentLearnRequestV1, user: User) -> MemoryLearningJobV1:
        if self.mode_provider() != 'execute':
            raise MemoryLearningError('memory_learning_unavailable')
        with self.admission.permit(), closing(self.store._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            actor, document = self._source(connection, request, user)
            preferences = self._preferences(connection, actor)
            if not preferences.learning_enabled:
                raise MemoryLearningError('memory_learning_paused')
            job_id = 'learning_' + canonical_json_sha256({
                'source_id': document.source.id, 'document_id': document.id, 'version': request.source_version,
                'hash': request.source_hash, 'schema': EXTRACTION_SCHEMA, 'actor': actor.id,
            })
            existing = self.repository.from_connection(connection, job_id)
            if existing:
                return existing
            now = self.clock()
            job = MemoryLearningJobV1(id=job_id, source_document_id=document.id, source_id=document.source.id,
                                     source_version=document.version, source_hash=request.source_hash,
                                     user_id=actor.id, workspace_id=actor.workspace_id, project_id=document.project_id,
                                     model_id=resolve_agent_model_id(self.store, actor),
                                     preferences_version=preferences.version, created_at=now, updated_at=now)
            if len(document.text.encode('utf-8')) > 12000:
                job = job.model_copy(update={'status': 'blocked', 'error_code': 'memory_learning_source_too_large'})
            self.repository.save(connection, job)
            self._audit(connection, actor, 'enqueue_memory_learning', job.id, job.project_id,
                        {'source_id': document.id, 'source_version': document.version})
            return job

    def discover_sources(self, *, limit: int = 20) -> int:
        if not 1 <= limit <= 50:
            raise ValueError('discovery limit must be between 1 and 50')
        if self.mode_provider() != 'execute' or self.admission.is_quiescing:
            return 0
        # Native document edits advance version. Authorize before hydrating text;
        # completed/blocked observations are durable and cannot starve later sources.
        with closing(self.store._read_connect()) as connection:
            rows = connection.execute('''SELECT document.payload, actor.payload AS actor_payload FROM records AS document
                JOIN records AS actor ON actor.collection = 'users'
                  AND actor.id = json_extract(document.payload, '$.uploaded_by')
                  AND json_extract(actor.payload, '$.status') = 'active'
                  AND json_extract(actor.payload, '$.workspace_id') = json_extract(document.payload, '$.workspace_id')
                JOIN records AS preferences ON preferences.collection = 'memory_preferences' AND preferences.id = actor.id
                  AND json_extract(preferences.payload, '$.learning_enabled') = 1
                  AND json_extract(preferences.payload, '$.workspace_id') = json_extract(actor.payload, '$.workspace_id')
                JOIN records AS project ON project.collection = 'projects'
                  AND project.id = json_extract(document.payload, '$.project_id')
                  AND json_extract(project.payload, '$.status') = 'active'
                  AND json_extract(project.payload, '$.workspace_id') = json_extract(document.payload, '$.workspace_id')
                WHERE document.collection = 'documents' AND json_extract(document.payload, '$.withdrawn_at') IS NULL
                  AND (json_array_length(project.payload, '$.member_ids') = 0
                       OR EXISTS (SELECT 1 FROM json_each(project.payload, '$.member_ids') WHERE value = actor.id))
                  AND NOT EXISTS (SELECT 1 FROM records AS job WHERE job.collection = 'memory_learning_jobs'
                                  AND json_extract(job.payload, '$.source_document_id') = document.id
                                  AND json_extract(job.payload, '$.source_version') = json_extract(document.payload, '$.version')
                                  AND json_extract(job.payload, '$.extraction_schema_version') = ?)
                ORDER BY document.created_order LIMIT ?''', (EXTRACTION_SCHEMA, limit)).fetchall()
        discovered = 0
        for row in rows:
            document = DocumentRecord.model_validate_json(row['payload'])
            actor = User.model_validate_json(row['actor_payload'])
            try:
                self.enqueue(DocumentLearnRequestV1(source_document_id=document.id, source_version=document.version,
                                                     source_hash=document_evidence_hash(document)), actor)
                discovered += 1
            except MemoryLearningError:
                # Source or policy changed after observation; a later bounded scan will recheck it.
                continue
        return discovered

    def get_job(self, job_id: str, user: User) -> MemoryLearningJobV1:
        with closing(self.store._read_connect()) as connection, connection:
            connection.execute('BEGIN')
            actor = self._actor(connection, user)
            job = self.repository.from_connection(connection, job_id)
            if job is None or job.user_id != actor.id or job.workspace_id != actor.workspace_id:
                raise MemoryLearningError('memory_learning_job_not_found', status_code=404)
            try:
                authorize_fact_project(connection, actor, job.project_id)
            except MemoryFactsError as error:
                raise MemoryLearningError('memory_learning_job_not_found', status_code=404) from error
            return job

    def candidate(self, job_id: str, user: User) -> UserMemoryItem:
        job = self.get_job(job_id, user)
        with closing(self.store._read_connect()) as connection, connection:
            connection.execute('BEGIN')
            actor, _, _ = self._current_source(connection, job, require_learning=False)
            item = _record(connection, 'user_memory_items', job.candidate_memory_id or '', UserMemoryItem)
            if (item is None or item.user_id != actor.id or item.workspace_id != actor.workspace_id
                    or item.project_id != job.project_id or item.scope is not Scope.PRIVATE
                    or item.status not in {'proposed', 'active'}):
                raise MemoryLearningError('memory_learning_candidate_not_found', status_code=404)
            return item

    def source_span(self, span_id: str, user: User) -> DocumentSourceSpanV1:
        with closing(self.store._read_connect()) as connection, connection:
            connection.execute('BEGIN')
            actor = self._actor(connection, user)
            span = _record(connection, 'source_spans', span_id, DocumentSourceSpanV1)
            if span is None or span.user_id != actor.id or span.workspace_id != actor.workspace_id:
                raise MemoryLearningError('memory_source_span_not_found', status_code=404)
            _, document = self._source(connection, DocumentLearnRequestV1(
                source_document_id=span.document_id, source_version=span.source_version, source_hash=span.source_hash,
            ), actor)
            if (document.project_id != span.project_id or document.source.id != span.source_id
                    or not 0 <= span.start < span.end <= len(document.text)
                    or document.text[span.start:span.end] != span.quote):
                raise MemoryLearningError('memory_source_span_not_found', status_code=404)
            return span

    def list_jobs(self, user: User, *, limit: int = 50) -> list[MemoryLearningJobV1]:
        if not 1 <= limit <= 100:
            raise ValueError('job limit must be between 1 and 100')
        with closing(self.store._read_connect()) as connection:
            actor = self._actor(connection, user)
            rows = connection.execute("SELECT payload FROM records WHERE collection = 'memory_learning_jobs' "
                                      "AND json_extract(payload, '$.user_id') = ? "
                                      "AND json_extract(payload, '$.workspace_id') = ? "
                                      'ORDER BY created_order DESC LIMIT ?', (actor.id, actor.workspace_id, limit)).fetchall()
            jobs = []
            for row in rows:
                job = MemoryLearningJobV1.model_validate_json(row['payload'])
                try:
                    authorize_fact_project(connection, actor, job.project_id)
                except MemoryFactsError:
                    continue
                jobs.append(job)
            return jobs

    @staticmethod
    def _request(job: MemoryLearningJobV1) -> DocumentLearnRequestV1:
        return DocumentLearnRequestV1(source_document_id=job.source_document_id, source_version=job.source_version,
                                      source_hash=job.source_hash)

    def _current_source(self, connection, job: MemoryLearningJobV1, *, require_learning: bool = True):
        user = _record(connection, 'users', job.user_id, User)
        if user is None or user.workspace_id != job.workspace_id:
            raise MemoryLearningError('memory_learning_actor_unavailable')
        actor, document = self._source(connection, self._request(job), user)
        preferences = self._preferences(connection, actor)
        if require_learning:
            if not preferences.learning_enabled:
                raise MemoryLearningError('memory_learning_paused')
            if resolve_agent_model_id(self.store, actor) != job.model_id:
                raise MemoryLearningError('memory_learning_model_changed')
        return actor, document, preferences

    def retry(self, job_id: str, request: LearningRetryRequestV1, user: User) -> MemoryLearningJobV1:
        if self.mode_provider() != 'execute':
            raise MemoryLearningError('memory_learning_unavailable')
        request_hash = canonical_json_sha256({'job_id': job_id, 'request': request.model_dump(mode='json')})
        key = canonical_json_sha256({'actor': user.id, 'command': request.command_id, 'kind': 'retry'})
        with self.admission.permit(), closing(self.store._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            actor = self._actor(connection, user)
            job = self.repository.from_connection(connection, job_id)
            if job is None or job.user_id != actor.id or job.workspace_id != actor.workspace_id:
                raise MemoryLearningError('memory_learning_job_not_found', status_code=404)
            _, document = self._source(connection, self._request(job), actor)
            preferences = self._preferences(connection, actor)
            if not preferences.learning_enabled:
                raise MemoryLearningError('memory_learning_paused')
            if self._receipt(connection, key, request_hash) is not None:
                return job
            if job.lease_epoch != request.expected_lease_epoch or job.status not in {'blocked', 'failed', 'cancelled'}:
                raise MemoryLearningError('memory_learning_retry_conflict')
            if job.attempt >= 3 or job.reserved_tokens + extraction_token_reservation(document) > job.token_cap:
                raise MemoryLearningError('memory_learning_budget_exhausted')
            updated = job.model_copy(update={'status': 'queued', 'error_code': None, 'updated_at': self.clock(),
                                             'model_id': resolve_agent_model_id(self.store, actor)})
            self.repository.save(connection, updated)
            self._save_receipt(connection, key, request_hash, job.id)
            self._audit(connection, actor, 'retry_memory_learning', job.id, job.project_id,
                        {'attempt': job.attempt, 'reserved_tokens': job.reserved_tokens,
                         'previous_model_id': job.model_id, 'requested_model_id': updated.model_id})
            return updated

    def claim_next(self) -> MemoryLearningJobV1 | None:
        if self.mode_provider() != 'execute' or self.admission.is_quiescing:
            return None
        now = self.clock()
        with self.admission.permit(), closing(self.store._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            rows = connection.execute('''SELECT payload FROM records WHERE collection = 'memory_learning_jobs'
                AND (json_extract(payload, '$.status') = 'queued'
                     OR (json_extract(payload, '$.status') = 'retry_wait'
                         AND julianday(json_extract(payload, '$.next_attempt_at')) <= julianday(?))
                     OR (json_extract(payload, '$.status') = 'running'
                         AND julianday(json_extract(payload, '$.lease_expires_at')) <= julianday(?)))
                ORDER BY created_order LIMIT 20''', (now.isoformat(), now.isoformat())).fetchall()
            for row in rows:
                job = MemoryLearningJobV1.model_validate_json(row['payload'])
                try:
                    actor, document, preferences = self._current_source(connection, job)
                    reservation = extraction_token_reservation(document)
                    if job.attempt >= 3 or job.reserved_tokens + reservation > job.token_cap:
                        raise MemoryLearningError('memory_learning_budget_exhausted')
                    ledger_id = self._ledger_id(actor, now)
                    ledger = connection.execute("SELECT payload FROM records WHERE collection = 'memory_learning_budgets' "
                                                'AND id = ?', (ledger_id,)).fetchone()
                    used = json.loads(ledger['payload'])['reserved_tokens'] if ledger else 0
                    if used + reservation > preferences.daily_token_cap:
                        raise MemoryLearningError('memory_learning_daily_budget_exhausted')
                except MemoryLearningError as error:
                    self._settle_error(connection, job, error.code, now)
                    continue
                connection.execute("INSERT INTO records(collection, id, payload) VALUES ('memory_learning_budgets', ?, ?) "
                                   'ON CONFLICT(collection, id) DO UPDATE SET payload = excluded.payload',
                                   (ledger_id, json.dumps({'reserved_tokens': used + reservation})))
                claimed = job.model_copy(update={
                    'status': 'running', 'attempt': job.attempt + 1, 'lease_epoch': job.lease_epoch + 1,
                    'lease_expires_at': now + timedelta(seconds=120), 'next_attempt_at': None,
                    'preferences_version': preferences.version, 'reserved_tokens': job.reserved_tokens + reservation,
                    'attempt_token_reservation': reservation, 'updated_at': now, 'error_code': None,
                    'usage_status': 'unknown',
                    'unreported_attempts': job.unreported_attempts + 1,
                })
                self.repository.save(connection, claimed)
                return claimed
        return None

    @staticmethod
    def _fenced(current: MemoryLearningJobV1 | None, claimed: MemoryLearningJobV1, now: datetime) -> bool:
        return bool(current and current.status == 'running' and current.lease_epoch == claimed.lease_epoch
                    and current.attempt == claimed.attempt and current.lease_expires_at is not None
                    and current.lease_expires_at > now)

    def heartbeat(self, claimed: MemoryLearningJobV1) -> bool:
        now = self.clock()
        with closing(self.store._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            current = self.repository.from_connection(connection, claimed.id)
            if not self._fenced(current, claimed, now):
                return False
            try:
                _, _, preferences = self._current_source(connection, current)
                if self.mode_provider() != 'execute' or preferences.version != current.preferences_version:
                    raise MemoryLearningError('memory_learning_policy_changed')
            except MemoryLearningError as error:
                self._settle_error(connection, current, error.code, now)
                return False
            self.repository.save(connection, current.model_copy(update={
                'lease_expires_at': now + timedelta(seconds=120), 'updated_at': now,
            }))
            return True

    async def _extract_with_lease(self, extractor: DocumentExtractor, document: DocumentRecord, actor: User,
                                  claimed: MemoryLearningJobV1) -> tuple[ExtractionResultV1, int]:
        task = asyncio.create_task(extractor.extract(document, actor, max_output_tokens=MAX_OUTPUT_TOKENS))
        try:
            while True:
                completed, _ = await asyncio.wait({task}, timeout=LEASE_HEARTBEAT_SECONDS)
                if completed:
                    return await task
                if not self.heartbeat(claimed):
                    raise MemoryLearningError('memory_learning_lease_lost')
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    def apply(self, claimed: MemoryLearningJobV1, output: ExtractionResultV1, *, actual_tokens: int) -> bool:
        now = self.clock()
        with closing(self.store._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            current = self.repository.from_connection(connection, claimed.id)
            if not self._fenced(current, claimed, now):
                return False
            if actual_tokens >= 0:
                unreported = max(0, current.unreported_attempts - 1)
                current = current.model_copy(update={'actual_tokens': current.actual_tokens + actual_tokens,
                                                     'unreported_attempts': unreported,
                                                     'usage_status': 'unknown' if unreported else 'reported'})
            try:
                actor, document, preferences = self._current_source(connection, current)
                if self.mode_provider() != 'execute' or preferences.version != current.preferences_version:
                    raise MemoryLearningError('memory_learning_policy_changed')
                if actual_tokens < 0 or actual_tokens > current.attempt_token_reservation:
                    raise MemoryLearningError('memory_learning_usage_invalid')
                project = authorize_fact_project(connection, actor, current.project_id)[1]
                if unsafe_tool_output_reason(output.model_dump_json()):
                    raise MemoryLearningError('memory_learning_content_requires_review')
                spans, facts = [], []
                for extracted in output.facts:
                    if (not 0 <= extracted.start < extracted.end <= len(document.text)
                            or document.text[extracted.start:extracted.end] != extracted.quote):
                        raise MemoryLearningError('memory_learning_quote_mismatch')
                    validate_fact_subject(connection, extracted.assertion, project)
                    span_id = 'span_' + canonical_json_sha256({'document': document.id, 'version': document.version,
                                                               'hash': current.source_hash, 'start': extracted.start,
                                                               'end': extracted.end})
                    span = DocumentSourceSpanV1(id=span_id, document_id=document.id, source_id=document.source.id,
                                                source_version=document.version, source_hash=current.source_hash,
                                                workspace_id=actor.workspace_id, project_id=project.id, user_id=actor.id,
                                                start=extracted.start, end=extracted.end, quote=extracted.quote,
                                                created_at=now)
                    spans.append(span)
                    ref = MemoryEvidenceRefV1(record_type='source_span', record_id=span.id, version=1,
                                              content_hash=source_span_hash(span))
                    facts.append(MemoryFactV1(**{
                        **extracted.assertion.model_dump(mode='python'),
                        'subject_id': normalized_subject_id(extracted.assertion, project.id),
                    }, observed_at=now, evidence_refs=[ref], source_classification='model_inference'))
            except (MemoryLearningError, MemoryFactsError) as error:
                self._settle_error(connection, current, error.code, now)
                return False
            memory = None
            if facts:
                memory = UserMemoryItem(id='candidate_' + current.id, user_id=actor.id, workspace_id=actor.workspace_id,
                                        project_id=project.id, layer=MemoryLayer.MID_TERM, title=output.title,
                                        summary=output.summary, source_kind='document_learning', memory_type='fact',
                                        status='proposed', facts=facts, sources=[document.source],
                                        provenance=MemoryProvenanceV1(source_kind='imported_document', created_by=actor.id),
                                        created_at=now, updated_at=now)
                for span in spans:
                    # Offset-derived ID is idempotent; keep its first observation time/hash.
                    prior = _record(connection, 'source_spans', span.id, DocumentSourceSpanV1)
                    if prior:
                        for fact in memory.facts:
                            if fact.evidence_refs[0].record_id == span.id:
                                fact.evidence_refs[0].content_hash = source_span_hash(prior)
                    else:
                        self.store._upsert_plain_record(connection, 'source_spans', span)
                self.store._upsert_plain_record(connection, 'user_memory_items', memory)
                self.store._upsert_plain_record(connection, 'inbox_items', InboxItem(
                    id='inbox_' + current.id, user_id=actor.id, workspace_id=actor.workspace_id, project_id=project.id,
                    scope=Scope.PRIVATE, item_type='memory_learning_review', title='资料产生了待确认记忆',
                    summary='请逐条检查来源与有效时间，确认后才会进入可用记忆。',
                    metadata={'learning_job_id': current.id, 'memory_id': memory.id}, created_at=now, updated_at=now,
                ))
            completed = current.model_copy(update={'status': 'completed', 'lease_expires_at': None,
                                                   'candidate_memory_id': memory.id if memory else None, 'updated_at': now})
            self.repository.save(connection, completed)
            self._audit(connection, actor, 'complete_memory_learning', current.id, project.id,
                        {'fact_count': len(facts), 'actual_tokens': actual_tokens, 'attempt': current.attempt})
        return True

    async def run_once(self, extractor: DocumentExtractor) -> int:
        claimed = self.claim_next()
        if claimed is None:
            return 0
        try:
            with closing(self.store._read_connect()) as connection, connection:
                connection.execute('BEGIN')
                actor, document, _ = self._current_source(connection, claimed)
            output, usage = await asyncio.wait_for(self._extract_with_lease(extractor, document, actor, claimed), timeout=90)
            self.apply(claimed, ExtractionResultV1.model_validate(output), actual_tokens=usage)
        except asyncio.CancelledError:
            # Keep the durable lease and full reservation: startup will recover it.
            raise
        except Exception as error:
            from openai import (
                APIConnectionError,
                APIStatusError,
                AuthenticationError,
                PermissionDeniedError,
                RateLimitError,
            )

            transient = isinstance(error, TimeoutError | APIConnectionError | RateLimitError) or (
                isinstance(error, APIStatusError) and error.status_code >= 500
            )
            code = 'memory_learning_model_auth_unavailable' if isinstance(error, AuthenticationError | PermissionDeniedError) else (
                error.code if isinstance(error, MemoryLearningError) else (
                'memory_learning_transient_failure' if transient else 'memory_learning_extraction_failed'
            ))
            retry_at = None
            if transient:
                try:
                    retry_at = provider_retry_at(error, self.clock())
                except RetryWindowTooLong:
                    code, transient = 'memory_learning_retry_window_unavailable', False
            self.fail(claimed, code, transient=transient, retry_at=retry_at)
        return 1

    def fail(self, claimed: MemoryLearningJobV1, code: str, *, transient: bool = False,
             retry_at: datetime | None = None) -> None:
        now = self.clock()
        with closing(self.store._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            current = self.repository.from_connection(connection, claimed.id)
            if not self._fenced(current, claimed, now):
                return
            if transient and current.attempt < 3:
                next_attempt = now + timedelta(seconds=(5, 30)[current.attempt - 1])
                if retry_at is not None:
                    next_attempt = max(next_attempt, retry_at)
                updated = current.model_copy(update={'status': 'retry_wait', 'lease_expires_at': None,
                                                     'next_attempt_at': next_attempt,
                                                     'error_code': code, 'updated_at': now})
                self.repository.save(connection, updated)
            else:
                self._settle_error(connection, current, code, now)

    def _settle_error(self, connection, job: MemoryLearningJobV1, code: str, now: datetime) -> None:
        cancelled = code in {'memory_learning_paused', 'memory_learning_policy_changed',
                             'memory_learning_source_changed', 'memory_learning_source_not_found',
                             'memory_learning_actor_unavailable', 'memory_learning_project_unavailable'}
        blocked = code in {'model_unavailable', 'memory_learning_model_auth_unavailable',
                           'memory_learning_model_changed', 'memory_learning_budget_exhausted',
                           'memory_learning_daily_budget_exhausted', 'memory_learning_retry_window_unavailable'}
        self.repository.save(connection, job.model_copy(update={
            'status': 'cancelled' if cancelled else 'blocked' if blocked else 'failed',
            'error_code': code, 'lease_expires_at': None, 'next_attempt_at': None, 'updated_at': now,
        }))

    def confirm(self, job_id: str, request: LearningConfirmationV1, user: User) -> UserMemoryItem:
        request_hash = canonical_json_sha256({'job_id': job_id, 'request': request.model_dump(mode='json')})
        key = canonical_json_sha256({'actor': user.id, 'command': request.command_id, 'kind': 'confirmation'})
        with closing(self.store._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            actor = self._actor(connection, user)
            job = self.repository.from_connection(connection, job_id)
            if job is None or job.user_id != actor.id or job.workspace_id != actor.workspace_id:
                raise MemoryLearningError('memory_learning_job_not_found', status_code=404)
            self._current_source(connection, job, require_learning=False)
            memory = _record(connection, 'user_memory_items', job.candidate_memory_id or '', UserMemoryItem)
            if memory is None or memory.user_id != actor.id or memory.scope is not Scope.PRIVATE:
                raise MemoryLearningError('memory_learning_candidate_not_found', status_code=404)
            replay = self._receipt(connection, key, request_hash)
            if replay is not None:
                if memory.status != 'active' or memory.archived_at is not None:
                    raise MemoryLearningError('memory_learning_candidate_unavailable')
                return memory
            if memory.status != 'proposed' or memory.version != request.expected_memory_version:
                raise MemoryLearningError('memory_learning_candidate_version_conflict')
            if memory.facts is None or any(index >= len(memory.facts) for index in request.selected_fact_indexes):
                raise MemoryLearningError('memory_learning_fact_selection_invalid', status_code=422)
            now = self.clock()
            facts = [memory.facts[index].model_copy(update={'source_classification': 'human_confirmed', 'observed_at': now})
                     for index in request.selected_fact_indexes]
            # Model-written summaries can contain unselected suggestions. Render only the confirmed assertions.
            updated = memory.model_copy(update={'status': 'active', 'version': memory.version + 1, 'facts': facts,
                                                'summary': '\n'.join(f'{fact.predicate}: {fact.value}' for fact in facts),
                                                'title': '已确认的资料记忆', 'updated_at': now})
            project = authorize_fact_project(connection, actor, job.project_id)[1]
            try:
                validate_memory_payload_evidence(connection, updated, project)
            except MemoryFactsError as error:
                raise MemoryLearningError(error.code) from error
            self.store._upsert_plain_record(connection, 'user_memory_items', updated)
            self.store._sync_fts(connection, 'user_memory_items', updated)
            self.store.vector_index.prepare(connection, 'user_memory_items', updated.id, updated.summary)
            inbox = _record(connection, 'inbox_items', 'inbox_' + job.id, InboxItem)
            if inbox:
                self.store._upsert_plain_record(connection, 'inbox_items', inbox.model_copy(update={
                    'status': 'resolved', 'resolved_at': now, 'updated_at': now,
                }))
            self._save_receipt(connection, key, request_hash, updated.id)
            self._audit(connection, actor, 'confirm_learned_memory', updated.id, job.project_id, {'fact_count': len(facts)})
            return updated

    @staticmethod
    def _receipt(connection, key: str, request_hash: str) -> dict | None:
        row = connection.execute("SELECT payload FROM records WHERE collection = 'memory_learning_commands' AND id = ?",
                                 (key,)).fetchone()
        if not row:
            return None
        receipt = json.loads(row['payload'])
        if receipt['request_hash'] != request_hash:
            raise MemoryLearningError('memory_learning_command_conflict')
        return receipt

    @staticmethod
    def _save_receipt(connection, key: str, request_hash: str, result_id: str) -> None:
        connection.execute("INSERT INTO records(collection, id, payload) VALUES ('memory_learning_commands', ?, ?)",
                           (key, json.dumps({'request_hash': request_hash, 'result_id': result_id})))

    def _audit(self, connection, actor: User, action: str, target_id: str, project_id: str | None, metadata: dict) -> None:
        self.store._upsert_plain_record(connection, 'audit_events', AuditEvent(
            actor=actor.id, action=action, target_type='memory', target_id=target_id, workspace_id=actor.workspace_id,
            project_id=project_id, metadata=metadata, created_at=self.clock(),
        ))


def source_span_hash(span: DocumentSourceSpanV1) -> str:
    return canonical_json_sha256(span.model_dump(mode='json'))
