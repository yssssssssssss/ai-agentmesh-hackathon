"""Document routes."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile

from agentmesh.documents import CompositeDocumentParser, DocumentIngestionRequest, UnsupportedDocumentTypeError
from agentmesh.ingestion import DocumentIngestionService, IngestionQueueFullError
from agentmesh.models import (
    DocumentJobStatus,
    DocumentParseJob,
    DocumentRecord,
    DocumentUpdateRequest,
    User,
    UserMemoryItem,
    UserRole,
    now_utc,
)
from agentmesh.routes.deps import current_user
from agentmesh.seed import PROJECT, WORKSPACE
from agentmesh.store import store

router = APIRouter(prefix="/api/documents", tags=["documents"])

MAX_SYNC_UPLOAD_BYTES = int(os.getenv("AGENTMESH_DOCUMENT_SYNC_THRESHOLD_BYTES", str(1024 * 1024)))
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
document_parser = CompositeDocumentParser()
ingestion_service = DocumentIngestionService(repository=store, parser=document_parser)


def document_visible_to_user(document: DocumentRecord | DocumentParseJob, user: User) -> bool:
    return user.role == UserRole.ADMIN or document.uploaded_by == user.id


@router.post("/upload")
async def upload_document(
    response: Response,
    file: UploadFile = File(...),
    user: User = Depends(current_user),
) -> dict[str, object]:
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="File too large")
    request = DocumentIngestionRequest(
        file_name=file.filename or "upload.txt",
        content_type=file.content_type or "application/octet-stream",
        content=content,
        workspace_id=WORKSPACE.id,
        project_id=PROJECT.id,
        uploaded_by=user.id,
    )
    job = ingestion_service.create_job(request)
    if len(content) > MAX_SYNC_UPLOAD_BYTES:
        try:
            ingestion_service.submit(job.id, request)
        except IngestionQueueFullError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        response.status_code = 202
        return {"job": job}

    try:
        completed_job = await ingestion_service.run_async(job.id, request)
    except IngestionQueueFullError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    if completed_job.status == DocumentJobStatus.FAILED:
        status_code = 400 if completed_job.error_type in {
            UnsupportedDocumentTypeError.__name__,
            UnicodeDecodeError.__name__,
        } else 500
        raise HTTPException(status_code=status_code, detail=completed_job.error or "Document ingestion failed")
    document = store.get_document(completed_job.document_id) if completed_job.document_id else None
    if document is None:
        raise HTTPException(status_code=500, detail="Document ingestion completed without a document")
    return {"item": document}


@router.get("/jobs")
def document_jobs(user: User = Depends(current_user)) -> dict[str, object]:
    jobs = [
        job
        for job in reversed(store.document_parse_jobs)
        if document_visible_to_user(job, user)
    ]
    return {"items": jobs}


@router.get("/jobs/{job_id}")
def document_job_detail(job_id: str, user: User = Depends(current_user)) -> dict[str, object]:
    job = store.get_document_parse_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Document parse job not found")
    if not document_visible_to_user(job, user):
        raise HTTPException(status_code=404, detail="Document parse job not found")
    return {"item": job}


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
    document = store.get_document(document_id)
    if document is None or not document_visible_to_user(document, user):
        raise HTTPException(status_code=404, detail="Document not found")
    if request.expected_version != document.version:
        raise HTTPException(status_code=409, detail="Document version conflict")
    updated = document.model_copy(deep=True)
    updated.version = request.expected_version + 1
    updated.text = request.text
    updated.expected_chunks = 0
    updated.completed_chunks = 0
    updated.updated_at = now_utc()
    updated.metadata["edited_by"] = user.id
    updated.metadata["edited_at"] = updated.updated_at.isoformat()
    if not store.save_document_if_version(updated, request.expected_version):
        raise HTTPException(status_code=409, detail="Document version conflict")
    ingestion_service.invalidate_prior_version_chunks(updated)
    return {"item": updated}


def import_document_chunks(document: DocumentRecord) -> list[UserMemoryItem]:
    """Compatibility wrapper around versioned, idempotent ingestion."""
    return ingestion_service.import_document_chunks(document)


@router.post("/{document_id}/import-to-memory")
def import_document_to_memory(
    document_id: str,
    user: User = Depends(current_user),
) -> dict[str, object]:
    """Manually complete missing chunks for the document's current version."""
    document = store.get_document(document_id)
    if document is None or not document_visible_to_user(document, user):
        raise HTTPException(status_code=404, detail="Document not found")
    existing = ingestion_service.current_version_chunks(document)
    if document.expected_chunks > 0 and len(existing) == document.expected_chunks:
        return {"status": "already_imported", "chunk_count": len(existing)}
    items = ingestion_service.import_document_chunks(document)
    return {"status": "imported", "chunk_count": len(items)}
