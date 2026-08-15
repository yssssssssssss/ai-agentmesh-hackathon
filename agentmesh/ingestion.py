"""Bounded, retryable document ingestion outside async request execution."""

from __future__ import annotations

import asyncio
import hashlib
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TYPE_CHECKING, TypeVar

from agentmesh.chunker import chunk_text
from agentmesh.documents import DocumentIngestionRequest, DocumentParser
from agentmesh.models import (
    DocumentJobStatus,
    DocumentParseJob,
    DocumentRecord,
    MemoryLayer,
    Scope,
    Source,
    UserMemoryItem,
    now_utc,
)

if TYPE_CHECKING:
    from agentmesh.store import SQLiteStore

ResultT = TypeVar("ResultT")


class IngestionQueueFullError(RuntimeError):
    pass


class IngestionShutdownError(RuntimeError):
    pass


class StaleDocumentVersionError(RuntimeError):
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
    ):
        self.repository = repository
        self.parser = parser
        self.executor = executor or BoundedIngestionExecutor()
        self._submitted: dict[Future[DocumentParseJob], str] = {}
        self._submitted_lock = threading.Lock()
        self._shutdown_lock = threading.Lock()
        self._shutdown_started = False
        self._shutdown_complete = threading.Event()

    def create_job(self, request: DocumentIngestionRequest) -> DocumentParseJob:
        return self.repository.save_document_parse_job(
            DocumentParseJob(
                file_name=request.file_name,
                content_type=request.content_type,
                workspace_id=request.workspace_id,
                project_id=request.project_id,
                uploaded_by=request.uploaded_by,
            )
        )

    def submit(self, job_id: str, request: DocumentIngestionRequest) -> Future[DocumentParseJob]:
        try:
            with self._shutdown_lock:
                if self._shutdown_started:
                    raise IngestionShutdownError("Document ingestion service is shutting down")
                future = self.executor.submit(self.run_job, job_id, request)
                with self._submitted_lock:
                    self._submitted[future] = job_id
                future.add_done_callback(self._forget_future)
                return future
        except (IngestionQueueFullError, IngestionShutdownError) as error:
            self.fail_job(job_id, error)
            raise

    async def run_async(self, job_id: str, request: DocumentIngestionRequest) -> DocumentParseJob:
        return await asyncio.wrap_future(self.submit(job_id, request))

    def shutdown(self) -> None:
        with self._shutdown_lock:
            already_started = self._shutdown_started
            self._shutdown_started = True
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

    def run_job(self, job_id: str, request: DocumentIngestionRequest) -> DocumentParseJob:
        job = self.repository.get_document_parse_job(job_id)
        if job is None:
            raise LookupError(f"Document parse job not found: {job_id}")
        if job.status == DocumentJobStatus.COMPLETED:
            document = self.repository.get_document(job.document_id) if job.document_id else None
            if (
                document is not None
                and job.version == document.version
                and document.completed_chunks == document.expected_chunks
            ):
                return job

        job.status = DocumentJobStatus.RUNNING
        job.error = None
        job.error_type = None
        job.updated_at = now_utc()
        try:
            self.repository.save_document_parse_job(job)
        except Exception as error:
            return self.fail_job(job_id, error)

        try:
            document = self._load_or_parse_document(job, request)
            self._save_summary(document)
            chunks = self.import_document_chunks(document, activate=False)
            self._activate_version_items(document.id, document.version)
            current = self._require_current_document(document.id, document.version)
            current.expected_chunks = len(chunks)
            current.completed_chunks = len(chunks)
            current.updated_at = now_utc()
            self._save_document_progress(current, document.version)
            job.document_id = document.id
            job.version = document.version
            job.expected_chunks = len(chunks)
            job.completed_chunks = len(chunks)
            job.status = DocumentJobStatus.COMPLETED
            job.error = None
            job.error_type = None
            job.updated_at = now_utc()
            finalized = self.repository.save_document_parse_job_if_document_version(
                job,
                document.id,
                document.version,
            )
            if not finalized:
                self._require_current_document(document.id, document.version)
                raise StaleDocumentVersionError(
                    f"Document {document.id} changed during job finalization"
                )
            return job
        except Exception as error:
            return self.fail_job(job_id, error)

    def fail_job(self, job_id: str, error: BaseException) -> DocumentParseJob:
        job = self.repository.get_document_parse_job(job_id)
        if job is None:
            raise LookupError(f"Document parse job not found: {job_id}") from error
        if job.document_id:
            self._invalidate_version_items(job.document_id, job.version)
            document = self.repository.get_document(job.document_id)
            if document is not None and document.version == job.version:
                job.expected_chunks = document.expected_chunks
                job.completed_chunks = document.completed_chunks
        job.status = DocumentJobStatus.FAILED
        job.error = (str(error) or error.__class__.__name__)[:1000]
        job.error_type = error.__class__.__name__
        job.updated_at = now_utc()
        return self.repository.save_document_parse_job(job)

    def _load_or_parse_document(
        self,
        job: DocumentParseJob,
        request: DocumentIngestionRequest,
    ) -> DocumentRecord:
        if job.document_id:
            existing = self.repository.get_document(job.document_id)
            if existing is None:
                raise LookupError(f"Document not found: {job.document_id}")
            if existing.version != job.version:
                raise StaleDocumentVersionError(
                    f"Document {existing.id} advanced from version {job.version} to {existing.version}"
                )
            return existing

        parsed = self.parser.parse(request)
        self.repository.add_source(parsed.source)
        document = self.repository.add_document(
            DocumentRecord(
                title=parsed.title,
                file_name=request.file_name,
                content_type=request.content_type,
                text=parsed.text,
                source=parsed.source,
                workspace_id=parsed.workspace_id,
                project_id=parsed.project_id,
                uploaded_by=parsed.uploaded_by,
                metadata=parsed.metadata,
            )
        )
        job.document_id = document.id
        job.version = document.version
        job.updated_at = now_utc()
        self.repository.save_document_parse_job(job)
        return document

    def _require_current_document(self, document_id: str, version: int) -> DocumentRecord:
        current = self.repository.get_document(document_id)
        if current is None:
            raise LookupError(f"Document not found: {document_id}")
        if current.version != version:
            raise StaleDocumentVersionError(
                f"Document {document_id} advanced from version {version} to {current.version}"
            )
        return current

    def _save_document_progress(self, document: DocumentRecord, version: int) -> None:
        self._require_current_document(document.id, version)
        if not self.repository.save_document_if_version(document, version):
            current = self.repository.get_document(document.id)
            current_version = current.version if current is not None else "missing"
            raise StaleDocumentVersionError(
                f"Document {document.id} advanced from version {version} to {current_version}"
            )

    def _save_summary(self, document: DocumentRecord) -> UserMemoryItem:
        current = self._require_current_document(document.id, document.version)
        return self.repository.add_user_memory_item(
            UserMemoryItem(
                id=f"umem_{current.id}_v{current.version}_summary",
                user_id=current.uploaded_by,
                layer=MemoryLayer.SHORT_TERM,
                title=f"文档摘要：{current.title}",
                summary=summarize_document_text(current.text),
                source_kind="document_upload",
                memory_type="document_summary",
                memory_date=now_utc().date(),
                workspace_id=current.workspace_id,
                project_id=current.project_id,
                status="staging",
                sources=[
                    Source(
                        title=current.file_name,
                        source_type="document",
                        reference=f"document://{current.id}#v{current.version}/summary",
                    )
                ],
            )
        )

    def import_document_chunks(
        self,
        document: DocumentRecord,
        *,
        activate: bool = True,
    ) -> list[UserMemoryItem]:
        version = document.version
        current = self._require_current_document(document.id, version)
        chunks = chunk_text(current.text)
        current.expected_chunks = len(chunks)
        current.completed_chunks = 0
        current.updated_at = now_utc()
        self._save_document_progress(current, version)

        items: list[UserMemoryItem] = []
        for index, text in enumerate(chunks):
            current = self._require_current_document(document.id, version)
            item = self.repository.add_user_memory_item(
                UserMemoryItem(
                    id=document_chunk_id(current.id, version, index),
                    user_id=current.uploaded_by,
                    layer=MemoryLayer.LONG_TERM,
                    title=f"{current.title} [{index + 1}/{len(chunks)}]",
                    summary=text,
                    source_kind="document_import",
                    memory_type="document_chunk",
                    memory_date=now_utc().date(),
                    scope=Scope.PRIVATE,
                    workspace_id=current.workspace_id,
                    project_id=current.project_id,
                    status="staging",
                    sources=[
                        Source(
                            title=current.file_name,
                            source_type="document",
                            reference=document_chunk_reference(current.id, version, index),
                        )
                    ],
                )
            )
            items.append(item)
            progress = self._require_current_document(document.id, version)
            progress.expected_chunks = len(chunks)
            progress.completed_chunks = len(items)
            progress.updated_at = now_utc()
            self._save_document_progress(progress, version)

        if activate:
            self._activate_version_items(document.id, version)
        return items

    def current_version_chunks(self, document: DocumentRecord) -> list[UserMemoryItem]:
        prefix = f"document://{document.id}#v{document.version}/chunk_"
        return [
            item
            for item in self.repository.user_memory_items
            if item.source_kind == "document_import"
            and item.status == "active"
            and any(source.reference.startswith(prefix) for source in item.sources)
        ]

    def _version_items(self, document_id: str, version: int) -> list[UserMemoryItem]:
        reference_prefix = f"document://{document_id}#v{version}/"
        summary_id = f"umem_{document_id}_v{version}_summary"
        return [
            item
            for item in self.repository.user_memory_items
            if item.id == summary_id
            or any(source.reference.startswith(reference_prefix) for source in item.sources)
        ]

    def _activate_version_items(self, document_id: str, version: int) -> None:
        for item in self._version_items(document_id, version):
            self._require_current_document(document_id, version)
            item.status = "active"
            item.updated_at = now_utc()
            self.repository.save_user_memory_item(item)

    def _invalidate_version_items(self, document_id: str, version: int) -> None:
        for item in self._version_items(document_id, version):
            if item.status == "stale":
                continue
            item.status = "stale"
            item.updated_at = now_utc()
            self.repository.save_user_memory_item(item)

    def invalidate_prior_version_chunks(self, document: DocumentRecord) -> None:
        current_chunk_prefix = f"document://{document.id}#v{document.version}/chunk_"
        document_prefix = f"document://{document.id}#"
        current_summary_id = f"umem_{document.id}_v{document.version}_summary"
        summary_prefix = f"umem_{document.id}_v"
        for item in self.repository.user_memory_items:
            if item.source_kind not in {"document_import", "document_upload"} or item.status == "stale":
                continue
            references = [source.reference for source in item.sources]
            old_chunk = item.source_kind == "document_import" and any(
                reference.startswith(document_prefix) and not reference.startswith(current_chunk_prefix)
                for reference in references
            )
            old_summary = (
                item.source_kind == "document_upload"
                and item.id.startswith(summary_prefix)
                and item.id != current_summary_id
            )
            if old_chunk or old_summary:
                item.status = "stale"
                item.updated_at = now_utc()
                self.repository.save_user_memory_item(item)


def document_chunk_id(document_id: str, version: int, index: int) -> str:
    digest = hashlib.sha256(f"{document_id}:{version}:{index}".encode()).hexdigest()[:24]
    return f"umem_chunk_{digest}"


def document_chunk_reference(document_id: str, version: int, index: int) -> str:
    return f"document://{document_id}#v{version}/chunk_{index}"


def summarize_document_text(text: str) -> str:
    normalized = " ".join(text.split())
    if not normalized:
        return "文档没有解析出可用正文。"
    return normalized[:1200]
