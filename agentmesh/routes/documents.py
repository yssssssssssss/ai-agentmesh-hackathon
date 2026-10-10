"""Document routes."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile

from agentmesh.document_jobs import DocumentJobError
from agentmesh.document_memory import DocumentMemoryError
from agentmesh.document_parser_process import IsolatedDocumentParser
from agentmesh.document_staging import DocumentStagingError
from agentmesh.documents import DocumentIngestionRequest, UnsupportedDocumentTypeError
from agentmesh.ingestion import DocumentIngestionService, IngestionQueueFullError
from agentmesh.memory_facts import MemoryFactsError, authorize_fact_project
from agentmesh.models import (
    DocumentJobItemResponse,
    DocumentJobRetryRequest,
    DocumentJobsResponse,
    DocumentJobStatus,
    DocumentParseJob,
    DocumentRecord,
    DocumentUpdateRequest,
    User,
    UserMemoryItem,
    UserRole,
)
from agentmesh.routes.deps import current_user
from agentmesh.source_authority import document_source_available
from agentmesh.store import store

router = APIRouter(prefix="/api/documents", tags=["documents"])

MAX_SYNC_UPLOAD_BYTES = int(os.getenv("AGENTMESH_DOCUMENT_SYNC_THRESHOLD_BYTES", str(1024 * 1024)))
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
document_parser = IsolatedDocumentParser()
ingestion_service = DocumentIngestionService(repository=store, parser=document_parser)


def document_visible_to_user(document: DocumentRecord | DocumentParseJob, user: User) -> bool:
    if document.workspace_id != user.workspace_id:
        return False
    if isinstance(document, DocumentRecord) and document.withdrawn_at is not None:
        return False
    try:
        with closing(store._read_connect()) as connection, connection:
            connection.execute('BEGIN')
            actor, _ = authorize_fact_project(connection, user, document.project_id)
            if isinstance(document, DocumentRecord):
                current = store._get_in_transaction(connection, 'documents', document.id, DocumentRecord)
                if current != document or not document_source_available(connection, current):
                    return False
            return actor.role == UserRole.ADMIN or document.uploaded_by == actor.id
    except (MemoryFactsError, ValueError):
        return False


@router.post("/upload")
async def upload_document(
    response: Response,
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    project_id: str | None = None,
) -> dict[str, object]:
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="File too large")
    try:
        with closing(store._read_connect()) as connection, connection:
            connection.execute("BEGIN")
            actor, project = authorize_fact_project(connection, user, project_id or user.default_project_id)
    except MemoryFactsError as error:
        raise HTTPException(status_code=404, detail=error.code) from error
    request = DocumentIngestionRequest(
        file_name=file.filename or "upload.txt",
        content_type=file.content_type or "application/octet-stream",
        content=content,
        workspace_id=actor.workspace_id,
        project_id=project.id,
        uploaded_by=actor.id,
    )
    try:
        job = ingestion_service.create_job(request)
    except DocumentJobError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except DocumentStagingError as error:
        raise HTTPException(status_code=503, detail=str(error)) from None
    if len(content) > MAX_SYNC_UPLOAD_BYTES:
        try:
            ingestion_service.submit(job.id)
        except IngestionQueueFullError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        response.status_code = 202
        return {"job": job}

    try:
        completed_job = await ingestion_service.run_async(job.id)
    except IngestionQueueFullError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    if completed_job.status == DocumentJobStatus.FAILED:
        status_code = 400 if completed_job.error in {
            'document_type_unsupported', 'document_text_encoding_invalid', 'document_parsed_text_too_large',
            'document_parser_metadata_too_large', 'document_pdf_page_limit_exceeded', 'document_archive_limit_exceeded',
            'document_archive_xml_unsafe',
        } or completed_job.error_type in {
            UnsupportedDocumentTypeError.__name__,
            UnicodeDecodeError.__name__,
        } else 500
        raise HTTPException(status_code=status_code, detail=completed_job.error or "Document ingestion failed")
    document = store.get_document(completed_job.document_id) if completed_job.document_id else None
    if document is None:
        raise HTTPException(status_code=500, detail="Document ingestion completed without a document")
    if not document_visible_to_user(document, user):
        raise HTTPException(status_code=404, detail='Document not found')
    return {"item": document}


@router.get("/jobs", response_model=DocumentJobsResponse)
def document_jobs(user: User = Depends(current_user), project_id: str | None = None,
                  limit: Annotated[int, Query(ge=1, le=100)] = 50,
                  before: Annotated[int | None, Query(ge=1)] = None) -> DocumentJobsResponse:
    jobs, cursor = ingestion_service.jobs.visible(user, project_id=project_id, before=before, limit=limit)
    return DocumentJobsResponse(items=jobs, next_cursor=cursor)


@router.get("/jobs/{job_id}", response_model=DocumentJobItemResponse)
def document_job_detail(job_id: str, user: User = Depends(current_user)) -> dict[str, object]:
    job = store.get_document_parse_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Document parse job not found")
    if not document_visible_to_user(job, user):
        raise HTTPException(status_code=404, detail="Document parse job not found")
    return {"item": job}


@router.post('/jobs/{job_id}/retry', response_model=DocumentJobItemResponse, status_code=202)
def retry_document_job(job_id: str, request: DocumentJobRetryRequest,
                       user: User = Depends(current_user)) -> DocumentJobItemResponse:
    try:
        job = ingestion_service.retry(job_id, request, user)
    except DocumentJobError as error:
        code = str(error)
        status = 404 if code in {'document_job_not_found', 'document_authority_unavailable'} else 409
        raise HTTPException(status_code=status, detail=code) from None
    return DocumentJobItemResponse(item=job)


def parse_document_job(job_id: str, request: DocumentIngestionRequest) -> DocumentParseJob:
    """Compatibility entry point for workers and focused tests."""
    return ingestion_service.run_job(job_id, request)


def parse_document_request(request: DocumentIngestionRequest) -> DocumentRecord:
    """Synchronous compatibility helper; async routes use the bounded executor."""
    job = ingestion_service.create_job(request)
    completed = ingestion_service.run_job(job.id, request)
    if completed.status == DocumentJobStatus.FAILED:
        raise RuntimeError(completed.error or "Document ingestion failed")
    document = store.get_document(completed.document_id) if completed.document_id else None
    if document is None:
        raise RuntimeError("Document ingestion completed without a document")
    return document


@router.get("")
def documents(user: User = Depends(current_user)) -> dict[str, object]:
    items = [
        document
        for document in reversed(store.documents)
        if document_visible_to_user(document, user)
    ]
    return {"items": items}


@router.get("/{document_id}")
def document_detail(document_id: str, user: User = Depends(current_user)) -> dict[str, object]:
    document = store.get_document(document_id)
    if document is None or not document_visible_to_user(document, user):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"item": document}


@router.patch("/{document_id}")
def update_document(document_id: str, request: DocumentUpdateRequest, user: User = Depends(current_user)) -> dict[str, object]:
    try:
        updated = ingestion_service.memory.update(document_id, request, user)
    except DocumentMemoryError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from None
    except sqlite3.Error:
        raise HTTPException(status_code=500, detail='document_update_failed') from None
    return {"item": updated}


def import_document_chunks(document: DocumentRecord) -> list[UserMemoryItem]:
    """Compatibility wrapper around versioned, idempotent ingestion."""
    return ingestion_service.import_document_chunks(document)


@router.post("/{document_id}/import-to-memory")
def import_document_to_memory(
    document_id: str,
    user: User = Depends(current_user),
    expected_version: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, object]:
    """Manually complete missing chunks for the document's current version."""
    document = store.get_document(document_id)
    if document is None or not document_visible_to_user(document, user):
        raise HTTPException(status_code=404, detail="Document not found")
    if expected_version is not None and document.version != expected_version:
        raise HTTPException(status_code=409, detail='document_version_conflict')
    try:
        result = ingestion_service.memory.import_current(document, user)
    except DocumentMemoryError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from None
    except sqlite3.Error:
        raise HTTPException(status_code=500, detail='document_import_failed') from None
    return {"status": "already_imported" if result.already_imported else "imported", "chunk_count": len(result.items)}
