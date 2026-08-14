"""Document routes."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Response, UploadFile

from agentmesh.chunker import chunk_text
from agentmesh.documents import CompositeDocumentParser, DocumentIngestionRequest, UnsupportedDocumentTypeError
from agentmesh.models import (
    DocumentParseJob,
    DocumentRecord,
    DocumentUpdateRequest,
    MemoryLayer,
    Scope,
    Source,
    User,
    UserMemoryItem,
    UserRole,
    now_utc,
)
from agentmesh.routes.deps import current_user
from agentmesh.seed import PROJECT, WORKSPACE
from agentmesh.store import store

router = APIRouter(prefix="/api/documents", tags=["documents"])

MAX_SYNC_UPLOAD_BYTES = 1024 * 1024
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
document_parser = CompositeDocumentParser()


@router.post("/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
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
    if len(content) > MAX_SYNC_UPLOAD_BYTES:
        job = store.save_document_parse_job(
            DocumentParseJob(
                file_name=request.file_name,
                content_type=request.content_type,
                workspace_id=request.workspace_id,
                project_id=request.project_id,
                uploaded_by=request.uploaded_by,
            )
        )
        background_tasks.add_task(parse_document_job, job.id, request)
        response.status_code = 202
        return {"job": job}
    try:
        document = parse_document_request(request)
    except (UnsupportedDocumentTypeError, UnicodeDecodeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"item": document}


@router.get("/jobs")
def document_jobs(user: User = Depends(current_user)) -> dict[str, object]:
    jobs = list(reversed(store.document_parse_jobs))
    if user.role != UserRole.ADMIN:
        jobs = [job for job in jobs if job.uploaded_by == user.id]
    return {"items": jobs}


@router.get("/jobs/{job_id}")
def document_job_detail(job_id: str, user: User = Depends(current_user)) -> dict[str, object]:
    job = store.get_document_parse_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Document parse job not found")
    if user.role != UserRole.ADMIN and job.uploaded_by != user.id:
        raise HTTPException(status_code=404, detail="Document parse job not found")
    return {"item": job}


def parse_document_job(job_id: str, request: DocumentIngestionRequest) -> None:
    job = store.get_document_parse_job(job_id)
    if job is None:
        return
    job.status = "running"
    job.updated_at = now_utc()
    store.save_document_parse_job(job)
    try:
        document = parse_document_request(request)
    except (UnsupportedDocumentTypeError, UnicodeDecodeError) as error:
        job.status = "failed"
        job.error = str(error)
        job.updated_at = now_utc()
        store.save_document_parse_job(job)
        return
    job.status = "completed"
    job.document_id = document.id
    job.updated_at = now_utc()
    store.save_document_parse_job(job)


def parse_document_request(request: DocumentIngestionRequest) -> DocumentRecord:
    parsed = document_parser.parse(request)
    store.add_source(parsed.source)
    document = store.add_document(
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
    store.add_user_memory_item(
        UserMemoryItem(
            user_id=request.uploaded_by,
            layer=MemoryLayer.SHORT_TERM,
            title=f"文档摘要：{document.title}",
            summary=summarize_document_text(document.text),
            source_kind="document_upload",
            memory_type="document_summary",
            memory_date=now_utc().date(),
            workspace_id=document.workspace_id,
            project_id=document.project_id,
            sources=[document.source],
        )
    )
    import_document_chunks(document)
    return document


@router.get("")
def documents(_: User = Depends(current_user)) -> dict[str, object]:
    return {"items": list(reversed(store.documents))}


@router.get("/{document_id}")
def document_detail(document_id: str, _: User = Depends(current_user)) -> dict[str, object]:
    document = store.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"item": document}


@router.patch("/{document_id}")
def update_document(document_id: str, request: DocumentUpdateRequest, user: User = Depends(current_user)) -> dict[str, object]:
    document = store.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if user.role != UserRole.ADMIN and document.uploaded_by != user.id:
        raise HTTPException(status_code=403, detail="Not allowed to update this document")
    document.text = request.text
    document.metadata["edited_by"] = user.id
    document.metadata["edited_at"] = now_utc().isoformat()
    return {"item": store.save_document(document)}


def summarize_document_text(text: str) -> str:
    normalized = " ".join(text.split())
    if not normalized:
        return "文档没有解析出可用正文。"
    return normalized[:1200]


def import_document_chunks(document: DocumentRecord) -> list[UserMemoryItem]:
    """Chunk document text and write each chunk as a long-term memory item."""
    chunks = chunk_text(document.text)
    items: list[UserMemoryItem] = []
    for i, chunk in enumerate(chunks):
        item = store.add_user_memory_item(
            UserMemoryItem(
                user_id=document.uploaded_by,
                layer=MemoryLayer.LONG_TERM,
                title=f"{document.title} [{i + 1}/{len(chunks)}]",
                summary=chunk,
                source_kind="document_import",
                memory_type="document_chunk",
                memory_date=now_utc().date(),
                scope=Scope.PRIVATE,
                workspace_id=document.workspace_id,
                project_id=document.project_id,
                sources=[
                    Source(
                        title=document.file_name,
                        source_type="document",
                        reference=f"document://{document.id}#chunk_{i}",
                    )
                ],
            )
        )
        items.append(item)
    return items


@router.post("/{document_id}/import-to-memory")
def import_document_to_memory(
    document_id: str,
    user: User = Depends(current_user),
) -> dict[str, object]:
    """Manually trigger chunk import for an existing document."""
    document = store.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if user.role != UserRole.ADMIN and document.uploaded_by != user.id:
        raise HTTPException(status_code=403, detail="Not allowed")
    existing = [
        item for item in store.user_memory_items
        if item.source_kind == "document_import"
        and any(f"document://{document_id}" in s.reference for s in item.sources)
    ]
    if existing:
        return {"status": "already_imported", "chunk_count": len(existing)}
    items = import_document_chunks(document)
    return {"status": "imported", "chunk_count": len(items)}
