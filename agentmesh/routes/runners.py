from __future__ import annotations

import json
import os
from datetime import timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from agentmesh.memory_context.request_budget import ModelAdmissionError
from agentmesh.memory_context.service import MemoryContextError
from agentmesh.model_registry import resolve_agent_model_id
from agentmesh.models import ChatRole, StatusResponse, User, now_utc
from agentmesh.routes.deps import create_audit_event, current_user
from agentmesh.runner_auth import (
    AuthenticatedRunner,
    generate_runner_token,
    generate_runner_user_code,
    hash_runner_token,
    require_current_runner,
)
from agentmesh.runner_context_service import RunnerContextService
from agentmesh.runner_contracts import (
    RunnerArtifactUploadRequest,
    RunnerArtifactUploadResponse,
    RunnerCancellationRequest,
    RunnerCompletionRequest,
    RunnerCompletionRequestV2,
    RunnerContextReferenceV1,
    RunnerConversationMessageV1,
    RunnerDevicesResponse,
    RunnerDeviceStatus,
    RunnerDispatchClaimRequest,
    RunnerDispatchClaimResponse,
    RunnerDispatchResultResponse,
    RunnerEnrollmentApprovalResponse,
    RunnerEnrollmentReviewResponse,
    RunnerEnrollmentStartRequest,
    RunnerEnrollmentStartResponse,
    RunnerEnrollmentStatus,
    RunnerEnrollmentTokenRequest,
    RunnerEnrollmentTokenResponse,
    RunnerEnrollmentV1,
    RunnerEventBatchRequest,
    RunnerEventBatchResponse,
    RunnerExecutionEnvelopeV1,
    RunnerExecutionEnvelopeV2,
    RunnerExecutionEnvelopeV3,
    RunnerFailureRequest,
    RunnerHeartbeatRequest,
    RunnerHeartbeatResponse,
    RunnerLeaseRenewResponse,
    RunnerModelDeliveryRequestV1,
    RunnerModelDeliveryResponseV1,
    RunnerModelHandoffRequestV1,
    RunnerModelHandoffResponseV1,
    RunnerNodeCompletionRequest,
    RunnerNodeCompletionRequestV2,
    RunnerSkillSnapshotV1,
    RunnerToolHandoffRequestV1,
    RunnerToolHandoffResponseV1,
    RunnerToolSnapshotV1,
    runner_envelope_hash,
)
from agentmesh.runner_settings import remote_runner_enabled
from agentmesh.store import ResearchStoreConflict, RunnerDispatchConflict, store
from agentmesh.tool_runtime.guardrails import contains_credential
from agentmesh.tools import list_agent_tools

router = APIRouter(prefix="/api", tags=["runners"])

_RUNNER_ENROLLMENT_TTL = timedelta(minutes=10)
_RUNNER_ENROLLMENT_POLL_INTERVAL_SECONDS = 2


def _new_user_code() -> str:
    for _ in range(20):
        user_code = generate_runner_user_code()
        if store.get_runner_enrollment_by_user_code(user_code) is None:
            return user_code
    raise HTTPException(status_code=503, detail="Unable to allocate runner enrollment code")


def _verification_uri(request: Request, user_code: str) -> str:
    public_url = os.getenv("AGENTMESH_PUBLIC_URL", "").strip().rstrip("/")
    base_url = public_url or str(request.base_url).rstrip("/")
    return f"{base_url}/admin?{urlencode({'section': 'runners', 'runner_enrollment': user_code})}"


@router.post(
    "/runner/enrollment/start",
    response_model=RunnerEnrollmentStartResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_runner_enrollment(
    payload: RunnerEnrollmentStartRequest,
    request: Request,
) -> RunnerEnrollmentStartResponse:
    device_code = generate_runner_token()
    now = now_utc()
    enrollment = RunnerEnrollmentV1(
        device_code_hash=hash_runner_token(device_code),
        user_code=_new_user_code(),
        device_name=payload.device_name,
        capabilities=payload.capabilities,
        expires_at=now + _RUNNER_ENROLLMENT_TTL,
        created_at=now,
        updated_at=now,
    )
    store.save_runner_enrollment(enrollment)
    return RunnerEnrollmentStartResponse(
        device_code=device_code,
        user_code=enrollment.user_code,
        verification_uri=_verification_uri(request, enrollment.user_code),
        expires_in=int(_RUNNER_ENROLLMENT_TTL.total_seconds()),
        interval=_RUNNER_ENROLLMENT_POLL_INTERVAL_SECONDS,
    )


@router.get(
    "/runner/enrollment/{user_code}",
    response_model=RunnerEnrollmentReviewResponse,
)
def get_runner_enrollment(
    user_code: str,
    user: User = Depends(current_user),
) -> RunnerEnrollmentReviewResponse:
    enrollment = store.get_runner_enrollment_by_user_code(user_code.strip().upper())
    if enrollment is None:
        raise HTTPException(status_code=404, detail="Runner enrollment not found")
    if enrollment.expires_at <= now_utc() and enrollment.status in {
        RunnerEnrollmentStatus.PENDING,
        RunnerEnrollmentStatus.APPROVED,
    }:
        raise HTTPException(status_code=410, detail="Runner enrollment expired")
    if enrollment.owner_user_id is not None and enrollment.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Runner enrollment not found")
    return RunnerEnrollmentReviewResponse(
        runner_id=enrollment.runner_id,
        device_name=enrollment.device_name,
        capabilities=enrollment.capabilities,
        status=enrollment.status,
        expires_at=enrollment.expires_at,
    )


@router.post(
    "/runner/enrollment/{user_code}/approve",
    response_model=RunnerEnrollmentApprovalResponse,
)
def approve_runner_enrollment(
    user_code: str,
    user: User = Depends(current_user),
) -> RunnerEnrollmentApprovalResponse:
    enrollment = store.approve_runner_enrollment(
        user_code.strip().upper(),
        user_id=user.id,
        workspace_id=user.workspace_id,
    )
    if enrollment is None:
        raise HTTPException(status_code=404, detail="Runner enrollment not found")
    if enrollment.status is RunnerEnrollmentStatus.EXPIRED:
        raise HTTPException(status_code=410, detail="Runner enrollment expired")
    if enrollment.owner_user_id != user.id:
        raise HTTPException(status_code=409, detail="Runner enrollment was approved by another user")
    store.add_audit_event(
        create_audit_event(
            user.id,
            "approve_runner_enrollment",
            "runner_device",
            enrollment.runner_id,
            {"workspace_id": user.workspace_id},
        )
    )
    return RunnerEnrollmentApprovalResponse(
        status=enrollment.status,
        runner_id=enrollment.runner_id,
    )


@router.post(
    "/runner/enrollment/token",
    response_model=RunnerEnrollmentTokenResponse,
)
def exchange_runner_enrollment_token(
    payload: RunnerEnrollmentTokenRequest,
) -> RunnerEnrollmentTokenResponse:
    enrollment, device = store.activate_runner_enrollment(hash_runner_token(payload.device_code))
    if enrollment is None:
        raise HTTPException(status_code=404, detail="Runner enrollment not found")
    if enrollment.status is RunnerEnrollmentStatus.EXPIRED:
        raise HTTPException(status_code=410, detail="Runner enrollment expired")
    if enrollment.status is RunnerEnrollmentStatus.PENDING:
        return RunnerEnrollmentTokenResponse(status="authorization_pending")
    if device is None or device.status is not RunnerDeviceStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Runner enrollment is unavailable")
    return RunnerEnrollmentTokenResponse(
        status="approved",
        runner=device,
        access_token=payload.device_code,
    )


@router.post("/runner/heartbeat", response_model=RunnerHeartbeatResponse)
def runner_heartbeat(
    payload: RunnerHeartbeatRequest,
    authenticated: AuthenticatedRunner = Depends(require_current_runner),
) -> RunnerHeartbeatResponse:
    if "runner:heartbeat" not in authenticated.credential.scopes:
        raise HTTPException(status_code=403, detail="Runner credential cannot send heartbeats")
    now = now_utc()
    updated = authenticated.device.model_copy(
        update={
            "capabilities": payload.capabilities,
            "last_seen_at": now,
            "updated_at": now,
        }
    )
    store.save_runner_device(updated)
    return RunnerHeartbeatResponse(runner=updated, server_time=now)


@router.post("/runner/dispatches/claim", response_model=RunnerDispatchClaimResponse)
def claim_runner_dispatch(
    payload: RunnerDispatchClaimRequest,
    authenticated: AuthenticatedRunner = Depends(require_current_runner),
):  # noqa: ANN201
    if not remote_runner_enabled():
        raise HTTPException(status_code=409, detail={"code": "remote_runner_disabled"})
    if "runner:claim" not in authenticated.credential.scopes:
        raise HTTPException(status_code=403, detail="Runner credential cannot claim dispatches")
    now = now_utc()
    updated_device = authenticated.device.model_copy(
        update={
            "capabilities": payload.capabilities,
            "last_seen_at": now,
            "updated_at": now,
        }
    )
    store.save_runner_device(updated_device)
    live_tools = {'context-handoff-v1', 'tool-handoff-v1'} <= set(updated_device.capabilities.model_capabilities)
    node_claimed = store.claim_runner_node_dispatch(
        runner_id=updated_device.id,
        owner_user_id=authenticated.user.id,
        workspace_id=authenticated.user.workspace_id,
        available_tool_names=set(updated_device.capabilities.tools) if live_tools else set(),
    )
    if node_claimed is not None:
        lease, run, node_dispatch = node_claimed
        envelope_payload = {
            "operation_kind": "standard_skill_node",
            "lease_id": lease.id,
            "lease_expires_at": lease.expires_at,
            "run_id": run.id,
            "operation_key": node_dispatch.id,
            "dispatch_generation": node_dispatch.attempt,
            "owner_user_id": run.user_id,
            "workspace_id": run.workspace_id,
            "project_id": run.project_id,
            "thread_id": run.thread_id,
            "task_id": run.task_id,
            "input_text": run.input_text,
            "history": [],
            "skill": node_dispatch.skill,
            "tools": node_dispatch.tools if live_tools else [],
            "plan_id": node_dispatch.plan_id,
            "node_id": node_dispatch.node_id,
            "node_attempt": node_dispatch.attempt,
            "node_prompt": node_dispatch.node_prompt,
            "instructions": node_dispatch.instructions,
            "model_id": node_dispatch.model_id,
            "deadline_at": node_dispatch.deadline_at,
        }
        context_service = RunnerContextService(store)
        snapshot = context_service.node_context(run, node_dispatch.node_id, node_dispatch.node_prompt, node_dispatch.instructions)
        if 'context-handoff-v1' in updated_device.capabilities.model_capabilities:
            envelope_payload['session'] = None
            envelope_payload['context'] = RunnerContextReferenceV1(id=snapshot.id, content_hash=snapshot.content_hash) if snapshot else None
            envelope = RunnerExecutionEnvelopeV3(envelope_hash=runner_envelope_hash(envelope_payload), **envelope_payload)
            context_service.bind(envelope, runner_id=updated_device.id)
        else:
            envelope_payload['node_prompt'] = {**node_dispatch.node_prompt, 'memory_context': ''}
            if snapshot and snapshot.core_preferences:
                envelope_payload['instructions'] = node_dispatch.instructions.removesuffix(
                    context_service.memory.render_core_preferences(snapshot.core_preferences))
            envelope = RunnerExecutionEnvelopeV1(envelope_hash=runner_envelope_hash(envelope_payload), **envelope_payload)
        return RunnerDispatchClaimResponse(envelope=envelope)
    claimed = store.claim_runner_dispatch(
        runner_id=updated_device.id,
        owner_user_id=authenticated.user.id,
        workspace_id=authenticated.user.workspace_id,
    )
    if claimed is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    lease, run, dispatch = claimed
    from agentmesh.routes.chat import agent

    runtime = agent.agent_runtime
    if runtime is None:
        raise HTTPException(status_code=409, detail={"code": "runner_runtime_unavailable"})
    skill = store.get_skill_definition(run.skill_id) if run.skill_id else None
    live_context = 'context-handoff-v1' in updated_device.capabilities.model_capabilities
    structured_session = live_context or 'structured-session-v1' in updated_device.capabilities.model_capabilities
    history = [] if structured_session else store.list_recent_thread_messages(
        run.thread_id, limit=10, max_content_bytes=20_000,
    )
    if history and history[-1].role is ChatRole.USER and history[-1].content == run.input_text:
        history = history[:-1]
    skill_snapshot = (
        RunnerSkillSnapshotV1(
            id=skill.id,
            name=skill.name,
            title=skill.title,
            version=skill.version,
            content_hash=skill.content_hash,
        )
        if skill is not None
        else None
    )
    tool_definitions = [
        definition
        for definition in list_agent_tools(store, authenticated.user.personal_agent_id)
        if definition.name in updated_device.capabilities.tools
        and live_tools
        and definition.side_effect == "read"
        and not definition.approval_required
        and (definition.implementation_id or "").startswith("runner:")
        and (skill is None or not skill.requested_tools or definition.name in skill.requested_tools)
    ]
    tool_snapshots = [
        RunnerToolSnapshotV1(
            id=definition.id,
            name=definition.name,
            description=definition.description,
            input_schema=definition.input_schema,
            implementation_id=definition.implementation_id or "",
            implementation_version=definition.implementation_version,
        )
        for definition in tool_definitions
    ]
    deadline_at = run.deadline_at or lease.expires_at
    envelope_payload = {
        "operation_kind": "standard_direct",
        "lease_id": lease.id,
        "lease_expires_at": lease.expires_at,
        "run_id": run.id,
        "operation_key": dispatch.operation_key,
        "dispatch_generation": dispatch.generation,
        "owner_user_id": run.user_id,
        "workspace_id": run.workspace_id,
        "project_id": run.project_id,
        "thread_id": run.thread_id,
        "task_id": run.task_id,
        "input_text": run.input_text,
        "history": [
            RunnerConversationMessageV1(role=message.role.value, content=message.content)
            for message in history
            if message.role in {ChatRole.USER, ChatRole.ASSISTANT}
        ],
        "skill": skill_snapshot,
        "tools": tool_snapshots,
        "plan_id": None,
        "node_id": None,
        "node_attempt": None,
        "node_prompt": None,
        "instructions": runtime.runner_instructions(skill),
        "model_id": resolve_agent_model_id(store, authenticated.user),
        "deadline_at": deadline_at,
    }
    if structured_session:
        try:
            snapshot = store.prepare_runner_session(lease_id=lease.id, runner_id=updated_device.id)
        except RunnerDispatchConflict as error:
            raise _runner_dispatch_http_error(error) from error
        envelope_payload['history'] = []
        envelope_payload['session'] = snapshot
        if live_context:
            context_service = RunnerContextService(store)
            reference, instructions = context_service.prepare_direct(run, authenticated.user, skill, envelope_payload['instructions'])
            envelope_payload['context'], envelope_payload['instructions'] = reference, instructions
            envelope = RunnerExecutionEnvelopeV3(envelope_hash=runner_envelope_hash(envelope_payload), **envelope_payload)
            context_service.bind(envelope, runner_id=updated_device.id)
        else:
            envelope = RunnerExecutionEnvelopeV2(envelope_hash=runner_envelope_hash(envelope_payload), **envelope_payload)
    else:
        envelope = RunnerExecutionEnvelopeV1(
            envelope_hash=runner_envelope_hash(envelope_payload), **envelope_payload,
        )
    return RunnerDispatchClaimResponse(envelope=envelope)


def _runner_dispatch_http_error(error: RunnerDispatchConflict) -> HTTPException:
    status_code = 404 if error.code in {"runner_lease_not_found", "runner_dispatch_not_found"} else 409
    return HTTPException(status_code=status_code, detail={"code": error.code})


@router.post('/runner/dispatches/{lease_id}/model-handoffs', response_model=RunnerModelHandoffResponseV1)
def authorize_runner_model_handoff(lease_id: str, payload: RunnerModelHandoffRequestV1,
                                   authenticated: AuthenticatedRunner = Depends(require_current_runner)) -> RunnerModelHandoffResponseV1:
    if 'runner:event' not in authenticated.credential.scopes:
        raise HTTPException(status_code=403, detail={'code': 'runner_model_handoff_not_authorized'})
    try:
        identity = RunnerContextService(store).authorize(lease_id, authenticated.device.id, payload)
    except (MemoryContextError, RunnerDispatchConflict, ResearchStoreConflict, ModelAdmissionError) as error:
        raise HTTPException(status_code=409, detail={'code': getattr(error, 'code', 'runner_context_not_authorized')}) from error
    return RunnerModelHandoffResponseV1(handoff_id=identity)


@router.post('/runner/dispatches/{lease_id}/tool-handoffs', response_model=RunnerToolHandoffResponseV1)
def authorize_runner_tool_handoff(lease_id: str, payload: RunnerToolHandoffRequestV1,
                                 authenticated: AuthenticatedRunner = Depends(require_current_runner)) -> RunnerToolHandoffResponseV1:
    if 'runner:event' not in authenticated.credential.scopes:
        raise HTTPException(status_code=403, detail={'code': 'runner_tool_handoff_not_authorized'})
    try:
        return RunnerContextService(store).authorize_tool(lease_id, authenticated.device.id, payload)
    except (MemoryContextError, RunnerDispatchConflict, ResearchStoreConflict, ModelAdmissionError) as error:
        raise HTTPException(status_code=409, detail={'code': getattr(error, 'code', 'runner_tool_handoff_denied')}) from error


@router.post('/runner/dispatches/{lease_id}/model-deliveries', response_model=RunnerModelDeliveryResponseV1)
def confirm_runner_model_delivery(lease_id: str, payload: RunnerModelDeliveryRequestV1,
                                  authenticated: AuthenticatedRunner = Depends(require_current_runner)) -> RunnerModelDeliveryResponseV1:
    if 'runner:event' not in authenticated.credential.scopes:
        raise HTTPException(status_code=403, detail={'code': 'runner_model_handoff_not_authorized'})
    try:
        return RunnerContextService(store).confirm(lease_id, authenticated.device.id, payload)
    except (MemoryContextError, RunnerDispatchConflict, ResearchStoreConflict, ModelAdmissionError) as error:
        raise HTTPException(status_code=409, detail={'code': getattr(error, 'code', 'runner_context_not_authorized')}) from error


@router.post(
    "/runner/dispatches/{lease_id}/renew",
    response_model=RunnerLeaseRenewResponse,
)
def renew_runner_dispatch(
    lease_id: str,
    authenticated: AuthenticatedRunner = Depends(require_current_runner),
) -> RunnerLeaseRenewResponse:
    if "runner:renew" not in authenticated.credential.scopes:
        raise HTTPException(status_code=403, detail="Runner credential cannot renew dispatches")
    now = now_utc()
    store.save_runner_device(authenticated.device.model_copy(update={"last_seen_at": now, "updated_at": now}))
    try:
        lease, cancel_requested = store.renew_runner_dispatch(
            lease_id=lease_id,
            runner_id=authenticated.device.id,
        )
    except RunnerDispatchConflict as error:
        raise _runner_dispatch_http_error(error) from error
    return RunnerLeaseRenewResponse(
        lease_id=lease.id,
        lease_expires_at=lease.expires_at,
        cancel_requested=cancel_requested,
    )


@router.post(
    "/runner/dispatches/{lease_id}/events",
    response_model=RunnerEventBatchResponse,
)
def append_runner_events(
    lease_id: str,
    payload: RunnerEventBatchRequest,
    authenticated: AuthenticatedRunner = Depends(require_current_runner),
) -> RunnerEventBatchResponse:
    if "runner:event" not in authenticated.credential.scopes:
        raise HTTPException(status_code=403, detail="Runner credential cannot append events")
    if any(len(json.dumps(event.payload, ensure_ascii=False).encode("utf-8")) > 16_384 for event in payload.events):
        raise HTTPException(status_code=400, detail={"code": "runner_event_payload_too_large"})
    try:
        accepted = store.append_runner_event_batch(
            lease_id=lease_id,
            runner_id=authenticated.device.id,
            events=payload.events,
        )
    except RunnerDispatchConflict as error:
        raise _runner_dispatch_http_error(error) from error
    return RunnerEventBatchResponse(accepted_event_ids=accepted)


@router.post(
    "/runner/dispatches/{lease_id}/node-complete",
    response_model=RunnerDispatchResultResponse,
)
def complete_runner_node_dispatch(
    lease_id: str,
    payload: RunnerNodeCompletionRequestV2 | RunnerNodeCompletionRequest,
    authenticated: AuthenticatedRunner = Depends(require_current_runner),
) -> RunnerDispatchResultResponse:
    if "runner:complete" not in authenticated.credential.scopes:
        raise HTTPException(status_code=403, detail="Runner credential cannot complete node dispatches")
    try:
        node_dispatch = store.complete_runner_node_dispatch(
            lease_id=lease_id,
            runner_id=authenticated.device.id,
            request=payload,
        )
    except RunnerDispatchConflict as error:
        raise _runner_dispatch_http_error(error) from error
    return RunnerDispatchResultResponse(run_id=node_dispatch.run_id, status=node_dispatch.status.value)


@router.post(
    "/runner/dispatches/{lease_id}/node-fail",
    response_model=RunnerDispatchResultResponse,
)
def fail_runner_node_dispatch(
    lease_id: str,
    payload: RunnerFailureRequest,
    authenticated: AuthenticatedRunner = Depends(require_current_runner),
) -> RunnerDispatchResultResponse:
    if "runner:complete" not in authenticated.credential.scopes:
        raise HTTPException(status_code=403, detail="Runner credential cannot fail node dispatches")
    try:
        node_dispatch = store.fail_runner_node_dispatch(
            lease_id=lease_id,
            runner_id=authenticated.device.id,
            request=payload,
        )
    except RunnerDispatchConflict as error:
        raise _runner_dispatch_http_error(error) from error
    return RunnerDispatchResultResponse(run_id=node_dispatch.run_id, status=node_dispatch.status.value)


@router.post(
    "/runner/dispatches/{lease_id}/artifacts",
    response_model=RunnerArtifactUploadResponse,
)
def upload_runner_artifact(
    lease_id: str,
    payload: RunnerArtifactUploadRequest,
    authenticated: AuthenticatedRunner = Depends(require_current_runner),
) -> RunnerArtifactUploadResponse:
    if "runner:artifact" not in authenticated.credential.scopes:
        raise HTTPException(status_code=403, detail="Runner credential cannot upload artifacts")
    try:
        artifact = store.save_runner_artifact(
            lease_id=lease_id,
            runner_id=authenticated.device.id,
            request=payload,
        )
    except RunnerDispatchConflict as error:
        raise _runner_dispatch_http_error(error) from error
    return RunnerArtifactUploadResponse(
        artifact_id=artifact.id,
        content_hash=artifact.content_hash or payload.content_hash,
        size_bytes=artifact.size_bytes or len(artifact.content.encode("utf-8")),
    )


@router.post(
    "/runner/dispatches/{lease_id}/complete",
    response_model=RunnerDispatchResultResponse,
)
def complete_runner_dispatch(
    lease_id: str,
    payload: RunnerCompletionRequestV2 | RunnerCompletionRequest,
    authenticated: AuthenticatedRunner = Depends(require_current_runner),
) -> RunnerDispatchResultResponse:
    if "runner:complete" not in authenticated.credential.scopes:
        raise HTTPException(status_code=403, detail="Runner credential cannot complete dispatches")
    if contains_credential(payload.output_text):
        raise HTTPException(status_code=400, detail={"code": "runner_output_credential_detected"})
    try:
        run = store.complete_runner_dispatch(
            lease_id=lease_id,
            runner_id=authenticated.device.id,
            request=payload,
        )
    except RunnerDispatchConflict as error:
        raise _runner_dispatch_http_error(error) from error
    from agentmesh.routes.chat import agent

    runtime = agent.agent_runtime
    if runtime is None:
        raise HTTPException(status_code=409, detail={"code": "runner_runtime_unavailable"})
    runtime.project_remote_run_output(
        run,
        content=payload.output_text,
        requested_model=payload.requested_model,
        actual_model=payload.actual_model,
        total_tokens=payload.total_tokens,
    )
    return RunnerDispatchResultResponse(run_id=run.id, status=run.status.value)


@router.post(
    "/runner/dispatches/{lease_id}/fail",
    response_model=RunnerDispatchResultResponse,
)
def fail_runner_dispatch(
    lease_id: str,
    payload: RunnerFailureRequest,
    authenticated: AuthenticatedRunner = Depends(require_current_runner),
) -> RunnerDispatchResultResponse:
    if "runner:complete" not in authenticated.credential.scopes:
        raise HTTPException(status_code=403, detail="Runner credential cannot fail dispatches")
    try:
        run = store.fail_runner_dispatch(
            lease_id=lease_id,
            runner_id=authenticated.device.id,
            request=payload,
        )
    except RunnerDispatchConflict as error:
        raise _runner_dispatch_http_error(error) from error
    store.project_terminal_run_status(run_id=run.id, skipped_reason=payload.error_code)
    return RunnerDispatchResultResponse(run_id=run.id, status=run.status.value)


@router.post(
    "/runner/dispatches/{lease_id}/cancelled",
    response_model=RunnerDispatchResultResponse,
)
def acknowledge_runner_cancellation(
    lease_id: str,
    payload: RunnerCancellationRequest,
    authenticated: AuthenticatedRunner = Depends(require_current_runner),
) -> RunnerDispatchResultResponse:
    if "runner:complete" not in authenticated.credential.scopes:
        raise HTTPException(status_code=403, detail="Runner credential cannot acknowledge cancellation")
    try:
        run = store.acknowledge_runner_cancellation(
            lease_id=lease_id,
            runner_id=authenticated.device.id,
            request=payload,
        )
    except RunnerDispatchConflict as error:
        raise _runner_dispatch_http_error(error) from error
    return RunnerDispatchResultResponse(run_id=run.id, status=run.status.value)


@router.get("/runners", response_model=RunnerDevicesResponse)
def list_runners(user: User = Depends(current_user)) -> RunnerDevicesResponse:
    return RunnerDevicesResponse(items=store.list_runner_devices_for_user(user.id))


@router.post("/runners/{runner_id}/revoke", response_model=StatusResponse)
def revoke_runner(
    runner_id: str,
    user: User = Depends(current_user),
) -> StatusResponse:
    runner = store.revoke_runner_device(runner_id, owner_user_id=user.id)
    if runner is None:
        raise HTTPException(status_code=404, detail="Runner not found")
    store.add_audit_event(
        create_audit_event(
            user.id,
            "revoke_runner",
            "runner_device",
            runner.id,
            {"workspace_id": user.workspace_id},
        )
    )
    return StatusResponse(status="ok")
