"""Explicit fact confirmation and authorized temporal queries."""

from fastapi import APIRouter, Depends, HTTPException

from agentmesh.memory_facts import MemoryFactsError, MemoryFactsService
from agentmesh.memory_payloads import (
    FactQueryResultV1,
    FactQueryV1,
    FactRememberV1,
    MemoryEvidenceRefV1,
    ProjectTermAliasesV1,
)
from agentmesh.models import User, UserMemoryItem
from agentmesh.routes.deps import current_user
from agentmesh.store import store
from agentmesh.terminology import ProjectTerminologyService, TermAliasUpdateV1, TerminologyError

router = APIRouter(prefix="/api/memory/facts", tags=["memory-facts"])


@router.get('/terminology/{project_id}', response_model=ProjectTermAliasesV1)
def project_terminology(project_id: str, user: User = Depends(current_user)) -> ProjectTermAliasesV1:
    try:
        return ProjectTerminologyService(store).get(project_id, user)
    except TerminologyError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from error


@router.put('/terminology/{project_id}', response_model=ProjectTermAliasesV1)
def update_project_terminology(
    project_id: str, request: TermAliasUpdateV1, user: User = Depends(current_user),
) -> ProjectTermAliasesV1:
    try:
        return ProjectTerminologyService(store).update(project_id, request, user)
    except TerminologyError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from error


@router.get("/source-documents/{document_id}", response_model=MemoryEvidenceRefV1)
def document_evidence(document_id: str, user: User = Depends(current_user)) -> MemoryEvidenceRefV1:
    try:
        return MemoryFactsService(store).document_evidence(document_id, user)
    except MemoryFactsError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from error


@router.post("/remember", response_model=UserMemoryItem, status_code=201)
def remember_facts(request: FactRememberV1, user: User = Depends(current_user)) -> UserMemoryItem:
    try:
        return MemoryFactsService(store).remember(request, user)
    except MemoryFactsError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from error


@router.post("/query", response_model=FactQueryResultV1)
def query_facts(request: FactQueryV1, user: User = Depends(current_user)) -> FactQueryResultV1:
    try:
        return MemoryFactsService(store).query(request, user)
    except MemoryFactsError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from error
