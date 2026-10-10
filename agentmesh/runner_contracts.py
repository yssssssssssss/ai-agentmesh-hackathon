from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentmesh.agent_runtime.budget import RunModelUsageV1
from agentmesh.models import new_id, now_utc

RUNNER_PROTOCOL_VERSION = "runner-v1"
RUNNER_CREDENTIAL_SCOPES = [
    "runner:heartbeat",
    "runner:claim",
    "runner:renew",
    "runner:event",
    "runner:artifact",
    "runner:complete",
]


def _runner_jsonable(value):  # noqa: ANN001, ANN202
    if isinstance(value, BaseModel):
        return _runner_jsonable(value.model_dump(mode="python"))
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Runner envelope datetime must include a timezone")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {str(key): _runner_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_runner_jsonable(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    return value


def runner_envelope_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        _runner_jsonable(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class RunnerDeviceStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class RunnerEnrollmentStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    CONSUMED = "consumed"
    EXPIRED = "expired"


class RunnerCapabilitiesV1(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["runner-capabilities-v1"] = "runner-capabilities-v1"
    platform: str = Field(min_length=1, max_length=64)
    architecture: str = Field(min_length=1, max_length=64)
    runner_version: str = Field(min_length=1, max_length=64)
    protocol_version: Literal["runner-v1"] = RUNNER_PROTOCOL_VERSION
    tools: list[str] = Field(default_factory=list, max_length=128)
    model_capabilities: list[str] = Field(default_factory=list, max_length=32)


class RunnerDeviceV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["runner-device-v1"] = "runner-device-v1"
    id: str = Field(default_factory=lambda: new_id("runner"), min_length=1, max_length=120)
    owner_user_id: str = Field(min_length=1, max_length=120)
    workspace_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    capabilities: RunnerCapabilitiesV1
    status: RunnerDeviceStatus = RunnerDeviceStatus.ACTIVE
    last_seen_at: datetime | None = None
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)
    revoked_at: datetime | None = None


class RunnerCredentialV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["runner-credential-v1"] = "runner-credential-v1"
    id: str = Field(default_factory=lambda: new_id("runner_cred"), min_length=1, max_length=120)
    runner_id: str = Field(min_length=1, max_length=120)
    token_hash: str = Field(pattern="^[0-9a-f]{64}$")
    scopes: list[str] = Field(default_factory=lambda: list(RUNNER_CREDENTIAL_SCOPES))
    created_at: datetime = Field(default_factory=now_utc)
    revoked_at: datetime | None = None


class RunnerEnrollmentV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["runner-enrollment-v1"] = "runner-enrollment-v1"
    id: str = Field(default_factory=lambda: new_id("runner_enrollment"), min_length=1, max_length=120)
    runner_id: str = Field(default_factory=lambda: new_id("runner"), min_length=1, max_length=120)
    device_code_hash: str = Field(pattern="^[0-9a-f]{64}$")
    user_code: str = Field(min_length=9, max_length=9, pattern="^[A-Z2-9]{4}-[A-Z2-9]{4}$")
    device_name: str = Field(min_length=1, max_length=120)
    capabilities: RunnerCapabilitiesV1
    status: RunnerEnrollmentStatus = RunnerEnrollmentStatus.PENDING
    owner_user_id: str | None = Field(default=None, max_length=120)
    workspace_id: str | None = Field(default=None, max_length=120)
    expires_at: datetime
    approved_at: datetime | None = None
    consumed_at: datetime | None = None
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class RunnerEnrollmentStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    device_name: str = Field(min_length=1, max_length=120)
    capabilities: RunnerCapabilitiesV1


class RunnerEnrollmentStartResponse(BaseModel):
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


class RunnerEnrollmentApprovalResponse(BaseModel):
    status: RunnerEnrollmentStatus
    runner_id: str


class RunnerEnrollmentReviewResponse(BaseModel):
    runner_id: str
    device_name: str
    capabilities: RunnerCapabilitiesV1
    status: RunnerEnrollmentStatus
    expires_at: datetime


class RunnerEnrollmentTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    device_code: str = Field(min_length=32, max_length=256)


class RunnerEnrollmentTokenResponse(BaseModel):
    status: Literal["authorization_pending", "approved"]
    runner: RunnerDeviceV1 | None = None
    access_token: str | None = None
    token_type: Literal["Bearer"] = "Bearer"


class RunnerHeartbeatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capabilities: RunnerCapabilitiesV1


class RunnerHeartbeatResponse(BaseModel):
    runner: RunnerDeviceV1
    server_time: datetime = Field(default_factory=now_utc)


class RunnerDevicesResponse(BaseModel):
    items: list[RunnerDeviceV1]


class RunnerDispatchLeaseStatus(StrEnum):
    ACTIVE = "active"
    SETTLED = "settled"
    EXPIRED = "expired"
    FAILED = "failed"


class RunnerDispatchLeaseV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["runner-dispatch-lease-v1"] = "runner-dispatch-lease-v1"
    id: str = Field(default_factory=lambda: new_id("runner_lease"), min_length=1, max_length=160)
    runner_id: str = Field(min_length=1, max_length=120)
    run_id: str = Field(min_length=1, max_length=120)
    operation_key: str = Field(min_length=1, max_length=160)
    operation_kind: Literal["standard_direct", "standard_skill_node"]
    dispatch_generation: int = Field(ge=1)
    attempt_count: int = Field(ge=1)
    status: RunnerDispatchLeaseStatus = RunnerDispatchLeaseStatus.ACTIVE
    expires_at: datetime
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)
    settled_at: datetime | None = None


class RunnerConversationMessageV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class RunnerSkillSnapshotV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=40)
    content_hash: str = Field(min_length=1, max_length=128)


class RunnerToolSnapshotV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)
    input_schema: dict[str, Any]
    side_effect: Literal["read"] = "read"
    implementation_id: str = Field(min_length=1, max_length=240)
    implementation_version: str = Field(min_length=1, max_length=80)


class RunnerNodeDispatchStatus(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    COMPLETED = "completed"
    FAILED = "failed"


class RunnerNodeDispatchV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["runner-node-dispatch-v1"] = "runner-node-dispatch-v1"
    id: str = Field(min_length=1, max_length=160)
    run_id: str = Field(min_length=1, max_length=120)
    plan_id: str = Field(min_length=1, max_length=120)
    node_id: str = Field(min_length=1, max_length=120)
    attempt: int = Field(ge=1)
    owner_user_id: str = Field(min_length=1, max_length=120)
    workspace_id: str = Field(min_length=1, max_length=120)
    project_id: str = Field(min_length=1, max_length=120)
    thread_id: str = Field(min_length=1, max_length=120)
    skill: RunnerSkillSnapshotV1
    tools: list[RunnerToolSnapshotV1] = Field(default_factory=list, max_length=24)
    instructions: str = Field(min_length=1, max_length=200_000)
    node_prompt: dict[str, Any]
    model_id: str = Field(min_length=1, max_length=120)
    deadline_at: datetime
    status: RunnerNodeDispatchStatus = RunnerNodeDispatchStatus.PENDING
    runner_id: str | None = Field(default=None, max_length=120)
    lease_id: str | None = Field(default=None, max_length=160)
    result_payload: dict[str, Any] | None = None
    requested_model: str | None = Field(default=None, max_length=160)
    actual_model: str | None = Field(default=None, max_length=160)
    total_tokens: int = Field(default=0, ge=0)
    error_code: str | None = Field(default=None, max_length=160)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class RunnerExecutionEnvelopeV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["runner-execution-envelope-v1"] = "runner-execution-envelope-v1"
    envelope_hash: str = Field(pattern="^[0-9a-f]{64}$")
    operation_kind: Literal["standard_direct", "standard_skill_node"] = "standard_direct"
    lease_id: str = Field(min_length=1, max_length=160)
    lease_expires_at: datetime
    run_id: str = Field(min_length=1, max_length=120)
    operation_key: str = Field(min_length=1, max_length=160)
    dispatch_generation: int = Field(ge=1)
    owner_user_id: str = Field(min_length=1, max_length=120)
    workspace_id: str = Field(min_length=1, max_length=120)
    project_id: str = Field(min_length=1, max_length=120)
    thread_id: str = Field(min_length=1, max_length=120)
    task_id: str | None = Field(default=None, max_length=120)
    input_text: str = Field(min_length=1, max_length=4000)
    history: list[RunnerConversationMessageV1] = Field(default_factory=list, max_length=20)
    skill: RunnerSkillSnapshotV1 | None = None
    tools: list[RunnerToolSnapshotV1] = Field(default_factory=list, max_length=24)
    plan_id: str | None = Field(default=None, max_length=120)
    node_id: str | None = Field(default=None, max_length=120)
    node_attempt: int | None = Field(default=None, ge=1)
    node_prompt: dict[str, Any] | None = None
    instructions: str = Field(min_length=1, max_length=200_000)
    model_id: str = Field(min_length=1, max_length=120)
    deadline_at: datetime


class RunnerDispatchClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capabilities: RunnerCapabilitiesV1


class RunnerSessionSnapshotV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    schema_version: Literal['runner-session-snapshot-v1'] = 'runner-session-snapshot-v1'
    thread_id: str = Field(min_length=1, max_length=120)
    version: int = Field(ge=0)
    items: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)

    @model_validator(mode='after')
    def bounded_items(self) -> RunnerSessionSnapshotV1:
        if len(json.dumps(self.items, ensure_ascii=False).encode('utf-8')) > 1_000_000:
            raise ValueError('runner_session_size_exceeded')
        return self

    @property
    def content_hash(self) -> str:
        return runner_envelope_hash(self.model_dump(mode='python'))


class RunnerSessionCommitV1(RunnerSessionSnapshotV1):
    schema_version: Literal['runner-session-commit-v1'] = 'runner-session-commit-v1'
    snapshot_hash: str = Field(pattern='^[0-9a-f]{64}$')


class RunnerExecutionEnvelopeV2(RunnerExecutionEnvelopeV1):
    schema_version: Literal['runner-execution-envelope-v2'] = 'runner-execution-envelope-v2'
    operation_kind: Literal['standard_direct'] = 'standard_direct'
    history: list[RunnerConversationMessageV1] = Field(default_factory=list, max_length=0)
    session: RunnerSessionSnapshotV1


class RunnerContextReferenceV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    id: str = Field(min_length=1, max_length=120)
    content_hash: str = Field(pattern='^[0-9a-f]{64}$')


class RunnerExecutionEnvelopeV3(RunnerExecutionEnvelopeV1):
    schema_version: Literal['runner-execution-envelope-v3'] = 'runner-execution-envelope-v3'
    history: list[RunnerConversationMessageV1] = Field(default_factory=list, max_length=0)
    session: RunnerSessionSnapshotV1 | None = None
    context: RunnerContextReferenceV1 | None = None

    @model_validator(mode='after')
    def session_matches_operation(self) -> RunnerExecutionEnvelopeV3:
        if (self.operation_kind == 'standard_direct') != (self.session is not None):
            raise ValueError('runner_session_operation_invalid')
        return self


RunnerExecutionEnvelope = RunnerExecutionEnvelopeV1 | RunnerExecutionEnvelopeV2 | RunnerExecutionEnvelopeV3


class RunnerModelHandoffRequestV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    client_request_id: str = Field(min_length=1, max_length=120)
    envelope_hash: str = Field(pattern='^[0-9a-f]{64}$')
    request_hash: str = Field(pattern='^[0-9a-f]{64}$')
    stage: Literal['execution', 'compaction'] = 'execution'
    input_hashes: list[Annotated[str, Field(pattern='^[0-9a-f]{64}$')]] = Field(default_factory=list, max_length=2000)
    instructions_hash: str = Field(pattern='^[0-9a-f]{64}$')
    model_id: str = Field(min_length=1, max_length=160)
    total_chars: int = Field(ge=0)
    estimated_input_tokens: int = Field(ge=0)
    output_token_cap: int = Field(ge=1, le=32000)


class RunnerModelHandoffResponseV1(BaseModel):
    handoff_id: str


class RunnerToolHandoffRequestV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    client_request_id: str = Field(min_length=1, max_length=120)
    envelope_hash: str = Field(pattern='^[0-9a-f]{64}$')
    tool_name: str = Field(min_length=1, max_length=120)
    tool_snapshot_hash: str = Field(pattern='^[0-9a-f]{64}$')
    arguments_hash: str = Field(pattern='^[0-9a-f]{64}$')
    tool_call_hash: str | None = Field(default=None, pattern='^[0-9a-f]{64}$')


class RunnerToolHandoffResponseV1(BaseModel):
    handoff_id: str
    tool_call_count: int


class RunnerModelDeliveryRequestV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    handoff_id: str = Field(min_length=1, max_length=120)
    request_hash: str = Field(pattern='^[0-9a-f]{64}$')
    total_tokens: int | None = Field(default=None, ge=0)
    usage: RunModelUsageV1 | None = None

    @model_validator(mode='after')
    def consistent_usage(self) -> RunnerModelDeliveryRequestV1:
        if self.usage is not None and (self.total_tokens != self.usage.total_tokens or self.total_tokens == 0):
            raise ValueError('runner_model_usage_inconsistent')
        return self


class RunnerModelDeliveryResponseV1(BaseModel):
    handoff_id: str
    receipt_ids: list[str] = Field(default_factory=list)
    budget_error_code: Literal['run_model_request_usage_exceeded', 'run_model_budget_exhausted'] | None = None


class RunnerDeliveryAuthorizationV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    lease_id: str
    runner_id: str
    delivery: RunnerModelDeliveryRequestV1


class RunnerDispatchClaimResponse(BaseModel):
    envelope: RunnerExecutionEnvelope = Field(discriminator='schema_version')


class RunnerLeaseRenewResponse(BaseModel):
    lease_id: str
    lease_expires_at: datetime
    cancel_requested: bool = False


class RunnerExecutionEventV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_event_id: str = Field(min_length=1, max_length=160)
    event_type: Literal[
        "execution_started",
        "model_started",
        "model_completed",
        "tool_started",
        "tool_completed",
        "tool_failed",
        "execution_completed",
        "execution_failed",
    ]
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime


class RunnerEventBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[RunnerExecutionEventV1] = Field(min_length=1, max_length=100)


class RunnerEventBatchResponse(BaseModel):
    accepted_event_ids: list[str]


class RunnerArtifactUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1, max_length=120)
    artifact_type: str = Field(min_length=1, max_length=120)
    content_type: str = Field(min_length=1, max_length=120)
    content: str = Field(max_length=1_000_000)
    content_hash: str = Field(pattern="^[0-9a-f]{64}$")


class RunnerArtifactUploadResponse(BaseModel):
    artifact_id: str
    content_hash: str
    size_bytes: int


class RunnerCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=160)
    output_text: str = Field(min_length=1, max_length=100_000)
    artifact_ids: list[str] = Field(default_factory=list, max_length=20)
    requested_model: str | None = Field(default=None, max_length=160)
    actual_model: str | None = Field(default=None, max_length=160)
    total_tokens: int = Field(default=0, ge=0)


class RunnerCompletionRequestV2(RunnerCompletionRequest):
    schema_version: Literal['runner-completion-v2'] = 'runner-completion-v2'
    session_commit: RunnerSessionCommitV1


class RunnerNodeCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=160)
    result_payload: dict[str, Any]
    requested_model: str | None = Field(default=None, max_length=160)
    actual_model: str | None = Field(default=None, max_length=160)
    total_tokens: int = Field(default=0, ge=0)


class RunnerNodeCompletionRequestV2(RunnerNodeCompletionRequest):
    schema_version: Literal['runner-node-completion-v2'] = 'runner-node-completion-v2'


class RunnerFailureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=160)
    error_code: str = Field(min_length=1, max_length=160)


class RunnerCancellationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=160)


class RunnerDispatchResultResponse(BaseModel):
    run_id: str
    status: str


class RunnerEventReceiptV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=160)
    lease_id: str = Field(min_length=1, max_length=160)
    run_id: str = Field(min_length=1, max_length=120)
    client_event_id: str = Field(min_length=1, max_length=160)
    event_hash: str = Field(pattern="^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=now_utc)


class RunnerCompletionReceiptV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=160)
    lease_id: str = Field(min_length=1, max_length=160)
    run_id: str = Field(min_length=1, max_length=120)
    command_id: str = Field(min_length=1, max_length=160)
    request_hash: str = Field(pattern="^[0-9a-f]{64}$")
    terminal_status: Literal["completed", "failed", "cancelled"]
    created_at: datetime = Field(default_factory=now_utc)
