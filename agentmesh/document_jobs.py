"""Current-authority claims and atomic document ingestion commits.

Parsing stays outside transactions. A worker may commit only its current lease;
no Source, Document or searchable Memory is exposed by a partial import.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import BaseModel

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.models import (
    DocumentJobRetryReceipt,
    DocumentJobRetryRequest,
    DocumentJobStatus,
    DocumentParseJob,
    DocumentRecord,
    Project,
    User,
    UserMemoryItem,
    now_utc,
)

if TYPE_CHECKING:
    from agentmesh.store import SQLiteStore
    from agentmesh.vector_index import VectorWork

LEASE_SECONDS = 120


class DocumentJobError(RuntimeError):
    """Static codes; upload contents and parser exception bodies are excluded."""


def _record[Record: BaseModel](connection: sqlite3.Connection, collection: str, key: str,
                              model: type[Record]) -> Record | None:
    row = connection.execute('SELECT payload FROM records WHERE collection = ? AND id = ?', (collection, key)).fetchone()
    if row is None:
        return None
    try:
        item = model.model_validate_json(row['payload'])
    except ValueError:
        raise DocumentJobError('document_record_invalid') from None
    if item.id != key:
        raise DocumentJobError('document_record_invalid')
    return item


def authorize_document_job(connection: sqlite3.Connection, job: DocumentParseJob) -> User:
    actor = _record(connection, 'users', job.uploaded_by, User)
    project = _record(connection, 'projects', job.project_id, Project)
    if (actor is None or actor.status != 'active' or actor.workspace_id != job.workspace_id
        or project is None or project.status != 'active' or project.workspace_id != job.workspace_id
        or (project.member_ids and actor.id not in project.member_ids)):
        raise DocumentJobError('document_authority_unavailable')
    return actor


def _input_identity(job: DocumentParseJob) -> str:
    return canonical_json_sha256({key: getattr(job, key) for key in (
        'id', 'file_name', 'content_type', 'workspace_id', 'project_id', 'uploaded_by',
        'input_contract', 'input_staging_ref', 'input_hash', 'input_size_bytes',
        'input_retained_until',
    )})


class DocumentJobStore:
    def __init__(self, repository: SQLiteStore, *, clock: Callable[[], datetime] = now_utc):
        self.repository, self.clock = repository, clock

    def create(self, job: DocumentParseJob) -> DocumentParseJob:
        with self.repository._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            authorize_document_job(connection, job)
            connection.execute('INSERT INTO records(collection,id,payload) VALUES (?,?,?)',
                               ('document_parse_jobs', job.id, job.model_dump_json()))
        return job

    def get(self, job_id: str) -> DocumentParseJob:
        with closing(self.repository._read_connect()) as connection:
            job = _record(connection, 'document_parse_jobs', job_id, DocumentParseJob)
        if job is None:
            raise DocumentJobError('document_job_not_found')
        return job

    def visible(self, user: User, *, project_id: str | None = None, before: int | None = None,
                limit: int = 50) -> tuple[list[DocumentParseJob], int | None]:
        if not 1 <= limit <= 100:
            raise ValueError('document_jobs_limit_invalid')
        with closing(self.repository._read_connect()) as connection:
            connection.execute('BEGIN')
            actor = _record(connection, 'users', user.id, User)
            if actor is None or actor.status != 'active' or actor.workspace_id != user.workspace_id:
                return [], None
            rows = connection.execute("""SELECT j.id, j.payload, j.created_order FROM records j
                JOIN records u ON u.collection = 'users' AND u.id = ?
                JOIN records p ON p.collection = 'projects' AND p.id = json_extract(j.payload, '$.project_id')
                WHERE j.collection = 'document_parse_jobs' AND json_extract(u.payload, '$.status') = 'active'
                  AND json_extract(u.payload, '$.workspace_id') = ?
                  AND json_extract(j.payload, '$.workspace_id') = json_extract(u.payload, '$.workspace_id')
                  AND json_extract(p.payload, '$.workspace_id') = json_extract(u.payload, '$.workspace_id')
                  AND json_extract(p.payload, '$.status') = 'active'
                  AND (json_array_length(json_extract(p.payload, '$.member_ids')) = 0
                       OR EXISTS (SELECT 1 FROM json_each(p.payload, '$.member_ids') WHERE value = u.id))
                  AND (json_extract(u.payload, '$.role') = 'admin' OR json_extract(j.payload, '$.uploaded_by') = u.id)
                  AND (? IS NULL OR json_extract(j.payload, '$.project_id') = ?)
                  AND (? IS NULL OR j.created_order < ?)
                ORDER BY j.created_order DESC LIMIT ?""",
                (user.id, user.workspace_id, project_id, project_id, before, before, limit + 1)).fetchall()
            items = []
            for row in rows[:limit]:
                job = DocumentParseJob.model_validate_json(row['payload'])
                if job.id != row['id']:
                    raise DocumentJobError('document_record_invalid')
                items.append(job)
            return items, rows[limit - 1]['created_order'] if len(rows) > limit else None

    def claim(self, job_id: str) -> tuple[DocumentParseJob, bool]:
        with self.repository._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            job = _record(connection, 'document_parse_jobs', job_id, DocumentParseJob)
            if job is None:
                raise DocumentJobError('document_job_not_found')
            authorize_document_job(connection, job)
            now = self.clock()
            if job.status == DocumentJobStatus.COMPLETED:
                return job, False
            if job.document_id is not None:
                raise DocumentJobError('document_legacy_partial_import_requires_review')
            if job.input_purged or (job.input_retained_until and job.input_retained_until <= now):
                raise DocumentJobError('document_input_expired')
            if job.status == DocumentJobStatus.RUNNING and job.lease_expires_at and job.lease_expires_at > now:
                return job, False
            if job.attempt_count >= 3:
                raise DocumentJobError('document_attempt_limit_reached')
            job.status, job.error, job.error_type = DocumentJobStatus.RUNNING, None, None
            job.claim_id, job.lease_expires_at = uuid4().hex, now + timedelta(seconds=LEASE_SECONDS)
            job.attempt_count += 1
            job.state_version += 1
            job.updated_at = now
            self.repository._upsert_plain_record(connection, 'document_parse_jobs', job)
            return job, True

    def _owned_claim(self, connection: sqlite3.Connection, claimed: DocumentParseJob) -> DocumentParseJob:
        current = _record(connection, 'document_parse_jobs', claimed.id, DocumentParseJob)
        if (current is None or current.status != DocumentJobStatus.RUNNING or not claimed.claim_id
            or current.claim_id != claimed.claim_id or not current.lease_expires_at
            or current.lease_expires_at <= self.clock() or _input_identity(current) != _input_identity(claimed)):
            raise DocumentJobError('document_claim_unavailable')
        authorize_document_job(connection, current)
        if current.input_purged or (current.input_retained_until and current.input_retained_until <= self.clock()):
            raise DocumentJobError('document_input_expired')
        return current

    def renew(self, claimed: DocumentParseJob) -> None:
        with self.repository._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            current = self._owned_claim(connection, claimed)
            current.lease_expires_at = self.clock() + timedelta(seconds=LEASE_SECONDS)
            self.repository._upsert_plain_record(connection, 'document_parse_jobs', current)

    def retry(self, job_id: str, request: DocumentJobRetryRequest, user: User) -> DocumentParseJob:
        with self.repository._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            job = _record(connection, 'document_parse_jobs', job_id, DocumentParseJob)
            if job is None or job.uploaded_by != user.id or job.workspace_id != user.workspace_id:
                raise DocumentJobError('document_job_not_found')
            authorize_document_job(connection, job)
            digest = canonical_json_sha256({'job_id': job.id, 'actor_id': user.id, **request.model_dump()})
            for receipt in job.retry_receipts:
                if receipt.command_id == request.command_id:
                    if receipt.request_hash != digest:
                        raise DocumentJobError('document_retry_command_conflict')
                    return job
            if job.state_version != request.expected_version:
                raise DocumentJobError('document_job_version_conflict')
            if job.status != DocumentJobStatus.FAILED:
                raise DocumentJobError('document_job_not_retryable')
            if job.attempt_count >= 3 or len(job.retry_receipts) >= 3:
                raise DocumentJobError('document_attempt_limit_reached')
            if job.input_contract != 'document-input-v1':
                raise DocumentJobError('document_input_unavailable')
            if job.input_purged or (job.input_retained_until and job.input_retained_until <= self.clock()):
                raise DocumentJobError('document_input_expired')
            job.status, job.claim_id, job.lease_expires_at = DocumentJobStatus.QUEUED, None, None
            job.error, job.error_type = None, None
            job.updated_at = self.clock()
            job.state_version += 1
            job.retry_receipts.append(DocumentJobRetryReceipt(command_id=request.command_id, request_hash=digest))
            self.repository._upsert_plain_record(connection, 'document_parse_jobs', job)
        return job

    def complete(self, claimed: DocumentParseJob, document: DocumentRecord,
                 items: list[UserMemoryItem]) -> tuple[DocumentParseJob, list[VectorWork]]:
        work = []
        with self.repository._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            current = self._owned_claim(connection, claimed)
            if (document.uploaded_by != current.uploaded_by or document.workspace_id != current.workspace_id
                or document.project_id != current.project_id or document.withdrawn_at is not None
                or any(item.user_id != current.uploaded_by or item.workspace_id != current.workspace_id
                       or item.project_id != current.project_id or item.scope != 'private' or item.status != 'active'
                       for item in items)):
                raise DocumentJobError('document_output_owner_mismatch')
            if any(connection.execute('SELECT 1 FROM records WHERE collection = ? AND id = ?', (collection, key)).fetchone()
                   for collection, key in [('documents', document.id), ('sources', document.source.id),
                                           *[('user_memory_items', item.id) for item in items]]):
                raise DocumentJobError('document_output_identity_conflict')
            self.repository._upsert_plain_record(connection, 'sources', document.source)
            for collection, item in [('documents', document), *[('user_memory_items', item) for item in items]]:
                self.repository._upsert_plain_record(connection, collection, item)
                self.repository._sync_fts(connection, collection, item)
                text = document.text if collection == 'documents' else item.summary
                vector = self.repository.vector_index.prepare(connection, collection, item.id, f'{item.title} {text}')
                if vector is not None:
                    work.append(vector)
            current.document_id, current.version = document.id, document.version
            current.expected_chunks, current.completed_chunks = document.expected_chunks, document.completed_chunks
            current.status, current.error, current.error_type = DocumentJobStatus.COMPLETED, None, None
            current.lease_expires_at = None
            current.input_cleanup_pending = True
            current.updated_at = self.clock()
            current.state_version += 1
            self.repository._upsert_plain_record(connection, 'document_parse_jobs', current)
        return current, work

    def fail(self, job_id: str, code: str, error_type: str, *, claimed: DocumentParseJob | None = None) -> DocumentParseJob:
        with self.repository._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            current = _record(connection, 'document_parse_jobs', job_id, DocumentParseJob)
            if current is None:
                raise DocumentJobError('document_job_not_found')
            # A late worker / queue rejection must never overwrite another live
            # claimant or a committed import.
            if current.status == DocumentJobStatus.COMPLETED:
                return current
            if current.status == DocumentJobStatus.RUNNING:
                if claimed is not None and current.claim_id != claimed.claim_id:
                    return current
                if claimed is None and current.lease_expires_at and current.lease_expires_at > self.clock():
                    return current
            current.status, current.error, current.error_type = DocumentJobStatus.FAILED, code, error_type
            current.lease_expires_at = None
            current.updated_at = self.clock()
            current.state_version += 1
            self.repository._upsert_plain_record(connection, 'document_parse_jobs', current)
        return current

    def recoverable(self, *, limit: int = 20) -> list[DocumentParseJob]:
        if not 1 <= limit <= 100:
            raise ValueError('document_recovery_limit_invalid')
        with closing(self.repository._read_connect()) as connection:
            rows = connection.execute("""SELECT id, payload FROM records WHERE collection = 'document_parse_jobs'
                AND (json_extract(payload, '$.status') = 'queued'
                  OR (json_extract(payload, '$.status') = 'running'
                      AND (json_extract(payload, '$.lease_expires_at') IS NULL
                           OR julianday(json_extract(payload, '$.lease_expires_at')) <= julianday(?)))
                  OR (json_extract(payload, '$.status') = 'completed'
                      AND json_extract(payload, '$.input_cleanup_pending') = 1)
                  OR (json_extract(payload, '$.input_contract') = 'document-input-v1'
                      AND coalesce(json_extract(payload, '$.input_purged'), 0) = 0
                      AND julianday(json_extract(payload, '$.input_retained_until')) <= julianday(?)
                      AND (json_extract(payload, '$.status') != 'running'
                           OR json_extract(payload, '$.lease_expires_at') IS NULL
                           OR julianday(json_extract(payload, '$.lease_expires_at')) <= julianday(?))))
                ORDER BY CASE WHEN json_extract(payload, '$.status') = 'completed' THEN 1 ELSE 0 END,
                    created_order LIMIT ?""", (self.clock().isoformat(), self.clock().isoformat(),
                                               self.clock().isoformat(), limit)).fetchall()
            jobs = [DocumentParseJob.model_validate_json(row['payload']) for row in rows]
            if any(job.id != row['id'] for job, row in zip(jobs, rows, strict=True)):
                raise DocumentJobError('document_record_invalid')
            return jobs

    def input_registered(self, reference: str) -> bool:
        with closing(self.repository._read_connect()) as connection:
            return connection.execute("""SELECT 1 FROM records WHERE collection = 'document_parse_jobs'
                AND json_extract(payload, '$.input_contract') = 'document-input-v1'
                AND json_extract(payload, '$.input_staging_ref') = ?
                AND coalesce(json_extract(payload, '$.input_purged'), 0) = 0 LIMIT 1""", (reference,)).fetchone() is not None

    def expire_input(self, observed: DocumentParseJob) -> DocumentParseJob:
        with self.repository._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            current = _record(connection, 'document_parse_jobs', observed.id, DocumentParseJob)
            if current is None or _input_identity(current) != _input_identity(observed):
                raise DocumentJobError('document_input_identity_conflict')
            if current.input_purged or not current.input_retained_until or current.input_retained_until > self.clock():
                return current
            if current.status == DocumentJobStatus.RUNNING and current.lease_expires_at and current.lease_expires_at > self.clock():
                return current
            if current.status != DocumentJobStatus.COMPLETED:
                current.status, current.error, current.error_type = DocumentJobStatus.FAILED, 'document_input_expired', 'DocumentJobError'
                current.lease_expires_at = None
                current.state_version += 1
            current.input_cleanup_pending = True
            current.updated_at = self.clock()
            self.repository._upsert_plain_record(connection, 'document_parse_jobs', current)
        return current

    def cleanup_result(self, completed: DocumentParseJob, *, pending: bool) -> DocumentParseJob:
        with self.repository._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            current = _record(connection, 'document_parse_jobs', completed.id, DocumentParseJob)
            if current is None or current.status not in {DocumentJobStatus.COMPLETED, DocumentJobStatus.FAILED}:
                raise DocumentJobError('document_claim_unavailable')
            if _input_identity(current) != _input_identity(completed):
                raise DocumentJobError('document_input_identity_conflict')
            current.input_cleanup_pending = pending
            current.input_cleanup_error = 'document_input_delete_failed' if pending else None
            current.input_purged = not pending
            self.repository._upsert_plain_record(connection, 'document_parse_jobs', current)
        return current
