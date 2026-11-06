from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from agentmesh.memory_learning.contracts import (
    DocumentLearnRequestV1,
    DocumentSourceSpanV1,
    LearningConfirmationV1,
    LearningRetryRequestV1,
    MemoryLearningJobV1,
    MemoryLearningStatusV1,
    MemoryPreferencesPatchV1,
    MemoryPreferencesV1,
)
from agentmesh.memory_learning.service import MemoryLearningError, MemoryLearningService
from agentmesh.memory_lifecycle import (
    MemoryForgetRequestV1,
    MemoryForgetResultV1,
    MemoryForgettingService,
    MemoryLifecycleError,
)
from agentmesh.models import User, UserMemoryItem
from agentmesh.routes.deps import current_user
from agentmesh.store import store

router = APIRouter(prefix='/api/memory', tags=['memory-learning'])


def learning_service() -> MemoryLearningService:
    return MemoryLearningService(store)


@router.get('/learning/status', response_model=MemoryLearningStatusV1)
def status(user: User = Depends(current_user)) -> MemoryLearningStatusV1:
    try:
        return learning_service().status(user)
    except MemoryLearningError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from error


@router.get('/preferences', response_model=MemoryPreferencesV1)
def preferences(user: User = Depends(current_user)) -> MemoryPreferencesV1:
    try:
        return learning_service().preferences(user)
    except MemoryLearningError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from error


@router.patch('/preferences', response_model=MemoryPreferencesV1)
def patch_preferences(request: MemoryPreferencesPatchV1, user: User = Depends(current_user)) -> MemoryPreferencesV1:
    try:
        return learning_service().patch_preferences(request, user)
    except MemoryLearningError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from error


@router.post('/learning/jobs', response_model=MemoryLearningJobV1, status_code=201)
def learn(request: DocumentLearnRequestV1, user: User = Depends(current_user)) -> MemoryLearningJobV1:
    try:
        return learning_service().enqueue(request, user)
    except MemoryLearningError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from error


@router.get('/learning/jobs', response_model=list[MemoryLearningJobV1])
def jobs(limit: int = Query(default=50, ge=1, le=100), user: User = Depends(current_user)) -> list[MemoryLearningJobV1]:
    try:
        return learning_service().list_jobs(user, limit=limit)
    except MemoryLearningError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from error


@router.get('/learning/jobs/{job_id}', response_model=MemoryLearningJobV1)
def job(job_id: str, user: User = Depends(current_user)) -> MemoryLearningJobV1:
    try:
        return learning_service().get_job(job_id, user)
    except MemoryLearningError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from error


@router.get('/learning/jobs/{job_id}/candidate', response_model=UserMemoryItem)
def candidate(job_id: str, user: User = Depends(current_user)) -> UserMemoryItem:
    try:
        return learning_service().candidate(job_id, user)
    except MemoryLearningError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from error


@router.post('/learning/jobs/{job_id}/retry', response_model=MemoryLearningJobV1)
def retry(job_id: str, request: LearningRetryRequestV1, user: User = Depends(current_user)) -> MemoryLearningJobV1:
    try:
        return learning_service().retry(job_id, request, user)
    except MemoryLearningError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from error


@router.post('/learning/jobs/{job_id}/confirm', response_model=UserMemoryItem)
def confirm(job_id: str, request: LearningConfirmationV1, user: User = Depends(current_user)) -> UserMemoryItem:
    try:
        return learning_service().confirm(job_id, request, user)
    except MemoryLearningError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from error


@router.get('/source-spans/{span_id}', response_model=DocumentSourceSpanV1)
def source_span(span_id: str, user: User = Depends(current_user)) -> DocumentSourceSpanV1:
    try:
        return learning_service().source_span(span_id, user)
    except MemoryLearningError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from error


@router.post('/{memory_id}/forget', response_model=MemoryForgetResultV1)
def forget(memory_id: str, request: MemoryForgetRequestV1, user: User = Depends(current_user)) -> MemoryForgetResultV1:
    try:
        return MemoryForgettingService(store).forget(memory_id, request, user)
    except MemoryLifecycleError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from error


@router.post('/sources/documents/{document_id}/withdraw', response_model=MemoryForgetResultV1)
def withdraw(document_id: str, request: MemoryForgetRequestV1, user: User = Depends(current_user)) -> MemoryForgetResultV1:
    try:
        return MemoryForgettingService(store).withdraw_document(document_id, request, user)
    except MemoryLifecycleError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from error
