"""Bounded, retryable document ingestion outside async request execution."""

from __future__ import annotations

import asyncio
import hashlib
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager, suppress
from datetime import timedelta
from typing import TYPE_CHECKING, TypeVar

from agentmesh.chunker import chunk_text
from agentmesh.document_jobs import DocumentJobError, DocumentJobStore
from agentmesh.document_memory import DocumentMemoryStore, document_chunk_id
from agentmesh.document_parser_process import IsolatedDocumentParser
from agentmesh.document_staging import DocumentInputStaging, DocumentStagingError
from agentmesh.documents import (
    DocumentIngestionRequest,
    DocumentParseError,
    DocumentParser,
    ParsedDocument,
    UnsupportedDocumentTypeError,
    validate_parsed_limits,
)
from agentmesh.models import (
    DocumentJobRetryRequest,
    DocumentJobStatus,
    DocumentParseJob,
    DocumentRecord,
    MemoryLayer,
    Scope,
    Source,
    User,
    UserMemoryItem,
    memory_date_for,
    now_utc,
)

if TYPE_CHECKING:
    from agentmesh.store import SQLiteStore

ResultT = TypeVar("ResultT")
_CLAIM_HEARTBEAT_SECONDS = 30


class IngestionQueueFullError(RuntimeError):
    pass


class IngestionShutdownError(RuntimeError):
    pass


class BoundedIngestionExecutor:
    """A bounded worker pool with deterministic, idempotent shutdown."""

    def __init__(self, max_workers: int = 2, max_queue_size: int = 8):
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="document-ingestion")
        self._capacity = threading.BoundedSemaphore(max_workers + max_queue_size)
        self._lock = threading.Lock()
        self._shutdown_started = False
        self._shutdown_complete = threading.Event()

    def submit(self, operation: Callable[..., ResultT], *args: object) -> Future[ResultT]:
        with self._lock:
            if self._shutdown_started:
                raise IngestionShutdownError("Document ingestion service is shutting down")
            if not self._capacity.acquire(blocking=False):
                raise IngestionQueueFullError("Document ingestion queue is full")
            try:
                future = self._executor.submit(operation, *args)
            except BaseException:
                self._capacity.release()
                raise
            future.add_done_callback(lambda _: self._capacity.release())
            return future

    async def run(self, operation: Callable[..., ResultT], *args: object) -> ResultT:
        return await asyncio.wrap_future(self.submit(operation, *args))

    def shutdown(self, *, wait: bool = True) -> None:
        with self._lock:
            already_started = self._shutdown_started
            self._shutdown_started = True
        if already_started:
            if wait:
                self._shutdown_complete.wait()
            return
        try:
            self._executor.shutdown(wait=wait, cancel_futures=True)
        finally:
            self._shutdown_complete.set()


class DocumentIngestionService:
    def __init__(
        self,
        repository: SQLiteStore,
        parser: DocumentParser,
        executor: BoundedIngestionExecutor | None = None,
        staging: DocumentInputStaging | None = None,
    ):
        self.repository = repository
        self.parser = parser
        self.jobs = DocumentJobStore(repository)
        self.memory = DocumentMemoryStore(repository)
        self.executor = executor or BoundedIngestionExecutor()
        self.staging = staging or DocumentInputStaging(repository.db_path.with_suffix('.inputs'))
        self._submitted: dict[Future[DocumentParseJob], str] = {}
        self._submitted_lock = threading.Lock()
        self._shutdown_lock = threading.Lock()
        self._shutdown_started = False
        self._shutdown_complete = threading.Event()
        self._recovery_task: asyncio.Task | None = None
        self._cancel_parsers = threading.Event()

    def create_job(self, request: DocumentIngestionRequest) -> DocumentParseJob:
        job = self.staging.save(
            DocumentParseJob(
                file_name=request.file_name,
                content_type=request.content_type,
                workspace_id=request.workspace_id,
                project_id=request.project_id,
                uploaded_by=request.uploaded_by,
                input_retained_until=now_utc() + timedelta(days=7),
            ), request,
        )
        try:
            return self.jobs.create(job)
        except Exception:
            self.staging.delete(job)
            raise

    def submit(self, job_id: str, request: DocumentIngestionRequest | None = None,
               *, recovery: bool = False) -> Future[DocumentParseJob]:
        try:
            with self._shutdown_lock:
                if self._shutdown_started:
                    raise IngestionShutdownError("Document ingestion service is shutting down")
                with self._submitted_lock:
                    existing = next((future for future, key in self._submitted.items() if key == job_id), None)
                    if existing is not None:
                        return existing
                future = self.executor.submit(self.run_job, job_id, request)
                with self._submitted_lock:
                    self._submitted[future] = job_id
                future.add_done_callback(self._forget_future)
                return future
        except (IngestionQueueFullError, IngestionShutdownError) as error:
            if not recovery:
                self.fail_job(job_id, error)
            raise

    def recover_once(self, *, limit: int = 20) -> int:
        submitted = 0
        for job in self.jobs.recoverable(limit=limit):
            if job.input_retained_until and job.input_retained_until <= self.jobs.clock():
                expired = self.jobs.expire_input(job)
                if expired.input_cleanup_pending:
                    self._cleanup_input(expired)
                continue
            if job.status == DocumentJobStatus.COMPLETED:
                self._cleanup_input(job)
                continue
            try:
                self.submit(job.id, recovery=True)
                submitted += 1
            except (IngestionQueueFullError, IngestionShutdownError):
                break
        self.staging.sweep_orphans(self.jobs.input_registered,
                                  older_than=(self.jobs.clock() - timedelta(days=7)).timestamp(), limit=100)
        return submitted

    async def start_recovery(self) -> None:
        if self._recovery_task is None:
            self._recovery_task = asyncio.create_task(self._recover_loop(), name='document-ingestion-recovery')

    async def stop_recovery(self) -> None:
        task, self._recovery_task = self._recovery_task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _recover_loop(self) -> None:
        while not self._shutdown_started:
            with suppress(Exception):  # Jobs remain eligible; no input bodies are logged.
                await asyncio.to_thread(self.recover_once)
            await asyncio.sleep(5)

    async def run_async(self, job_id: str, request: DocumentIngestionRequest | None = None) -> DocumentParseJob:
        return await asyncio.wrap_future(self.submit(job_id, request))

    def retry(self, job_id: str, request: DocumentJobRetryRequest, user: User) -> DocumentParseJob:
        job = self.jobs.retry(job_id, request, user)
        if job.status == DocumentJobStatus.QUEUED:
            # A full local queue keeps the durable accepted command queued.
            with suppress(IngestionQueueFullError, IngestionShutdownError):
                self.submit(job_id, recovery=True)
        return self.jobs.get(job_id)

    def shutdown(self) -> None:
        with self._shutdown_lock:
            already_started = self._shutdown_started
            self._shutdown_started = True
            self._cancel_parsers.set()
        if already_started:
            self._shutdown_complete.wait()
            return
        with self._submitted_lock:
            submitted = list(self._submitted.items())
        try:
            self.executor.shutdown(wait=True)
            for future, job_id in submitted:
                if future.cancelled():
                    self.fail_job(job_id, IngestionShutdownError("Queued ingestion canceled during shutdown"))
        finally:
            self._shutdown_complete.set()

    def _forget_future(self, future: Future[DocumentParseJob]) -> None:
        with self._submitted_lock:
            self._submitted.pop(future, None)

    @contextmanager
    def _keep_claim(self, job: DocumentParseJob):
        stop = threading.Event()
        lost = threading.Event()

        def renew():
            while not stop.wait(_CLAIM_HEARTBEAT_SECONDS):
                try:
                    self.jobs.renew(job)
                except Exception:
                    lost.set()
                    return  # The commit rechecks the lease and current authority.

        heartbeat = threading.Thread(target=renew, name='document-claim-heartbeat', daemon=True)
        heartbeat.start()
        try:
            yield lost
        finally:
            stop.set()
            heartbeat.join()

    def run_job(self, job_id: str, request: DocumentIngestionRequest | None = None) -> DocumentParseJob:
        try:
            job, acquired = self.jobs.claim(job_id)
        except DocumentJobError as error:
            return self.fail_job(job_id, error)
        if not acquired:
            return self._cleanup_input(job) if job.status == DocumentJobStatus.COMPLETED else job
        try:
            with self._keep_claim(job) as lost:
                original = self.staging.load(job)
                if request is not None and request != original:
                    raise DocumentStagingError('document_input_identity_conflict')
                parsed = (self.parser.parse(original, cancelled=lambda: lost.is_set() or self._cancel_parsers.is_set())
                          if isinstance(self.parser, IsolatedDocumentParser) else self.parser.parse(original))
                document, items = self._prepare_import(job, parsed)
                completed, vectors = self.jobs.complete(job, document, items)
        except Exception as error:
            return self.fail_job(job_id, error, claimed=job)
        # Cache/optional vector work cannot change the committed import outcome.
        completed = self._cleanup_input(completed)
        from agentmesh.embedding import EMBEDDING_ENABLED

        if EMBEDDING_ENABLED:
            for work in vectors:
                try:
                    self.repository.vector_index.process(work)
                except Exception:
                    break  # Pending vector work is separate from lexical visibility.
        return completed

    def _prepare_import(self, job: DocumentParseJob, parsed: ParsedDocument) -> tuple[DocumentRecord, list[UserMemoryItem]]:
        if any(getattr(parsed, key) != getattr(job, key) for key in ('workspace_id', 'project_id', 'uploaded_by')):
            raise DocumentJobError('document_parser_owner_mismatch')
        validate_parsed_limits(parsed)
        digest = hashlib.sha256(job.id.encode()).hexdigest()[:32]
        document_id = f'doc_input_{digest}'
        source = Source(id=f'src_input_{digest}', title=job.file_name, source_type='document',
                        reference=f'document://{document_id}#v1/original', workspace_id=job.workspace_id,
                        project_id=job.project_id, user_id=job.uploaded_by)
        chunks = chunk_text(parsed.text)
        if len(chunks) > 2200:
            raise DocumentJobError('document_chunk_limit_exceeded')
        document = DocumentRecord(id=document_id, title=parsed.title, file_name=job.file_name,
            content_type=job.content_type, text=parsed.text, source=source, workspace_id=job.workspace_id,
            project_id=job.project_id, uploaded_by=job.uploaded_by, metadata=parsed.metadata,
            expected_chunks=len(chunks), completed_chunks=len(chunks))
        common = dict(user_id=job.uploaded_by, workspace_id=job.workspace_id, project_id=job.project_id,
                      memory_date=memory_date_for(), scope=Scope.PRIVATE, status='active')
        items = [UserMemoryItem(id=f'umem_{document.id}_v1_summary', layer=MemoryLayer.SHORT_TERM,
            title=f'文档摘要：{document.title}', summary=summarize_document_text(document.text),
            source_kind='document_upload', memory_type='document_summary', sources=[source.model_copy(update={
                'id': f'src_{document.id}_summary', 'reference': f'document://{document.id}#v1/summary',
            })], **common)]
        for index, text in enumerate(chunks):
            items.append(UserMemoryItem(id=document_chunk_id(document.id, 1, index), layer=MemoryLayer.LONG_TERM,
                title=f'{document.title} [{index + 1}/{len(chunks)}]', summary=text, source_kind='document_import',
                memory_type='document_chunk', sources=[source.model_copy(update={
                    'id': f'src_{document.id}_chunk_{index}',
                    'reference': document_chunk_reference(document.id, 1, index),
                })], **common))
        return document, items

    def _cleanup_input(self, job: DocumentParseJob) -> DocumentParseJob:
        if not job.input_contract or not job.input_cleanup_pending:
            return job
        pending = True
        try:
            self.staging.delete(job)
            pending = False
        except DocumentStagingError:
            pass
        try:
            return self.jobs.cleanup_result(job, pending=pending)
        except Exception:
            return job  # Durable pending=true is retried after reopen.

    def fail_job(self, job_id: str, error: BaseException, *, claimed: DocumentParseJob | None = None) -> DocumentParseJob:
        if isinstance(error, (DocumentJobError, DocumentStagingError, DocumentParseError)):
            code = str(error)
        elif isinstance(error, UnsupportedDocumentTypeError):
            code = 'document_type_unsupported'
        elif isinstance(error, UnicodeDecodeError):
            code = 'document_text_encoding_invalid'
        elif isinstance(error, IngestionQueueFullError):
            code = 'document_ingestion_queue_full'
        elif isinstance(error, IngestionShutdownError):
            code = 'document_ingestion_shutdown'
        else:
            code = 'document_ingestion_failed'
        return self.jobs.fail(job_id, code, type(error).__name__, claimed=claimed)

    def import_document_chunks(self, document: DocumentRecord) -> list[UserMemoryItem]:
        return self.memory.import_current(document).items

    def current_version_chunks(self, document: DocumentRecord) -> list[UserMemoryItem]:
        return self.memory.current_chunks(document)


def document_chunk_reference(document_id: str, version: int, index: int) -> str:
    return f"document://{document_id}#v{version}/chunk_{index}"


def summarize_document_text(text: str) -> str:
    normalized = " ".join(text.split())
    if not normalized:
        return "文档没有解析出可用正文。"
    return normalized[:1200]
