from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentmesh.models import (
    AgentRun,
    AgentRunStatus,
    Artifact,
    ArtifactVerificationState,
    AuditEvent,
    new_id,
    now_utc,
)
from agentmesh.research_orchestration.contracts import (
    AttemptStatus,
    ExecutionAttempt,
    ExecutionLease,
    ExecutionPlanVersion,
    InvocationState,
    ModelCallReceipt,
    ResearchCommandReceipt,
    ResearchPhase,
    ResearchStep,
    ResearchWorkflow,
    StepStatus,
    ToolInvocation,
    ToolReceipt,
    canonical_json_bytes,
    canonical_sha256,
)
from agentmesh.store import ResearchStoreConflict, SQLiteStore
from agentmesh.tool_runtime.guardrails import contains_credential, redact_sensitive_text

MAX_ARTIFACT_BYTES = 1024 * 1024
MAX_RUN_ARTIFACT_BYTES = 5 * 1024 * 1024
TRANSIENT_RETENTION = timedelta(hours=24)
RAW_TOOL_RETENTION = timedelta(days=30)

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<![A-Za-z0-9])1[3-9]\d{9}(?![A-Za-z0-9])")
_V2_CONTENT_TYPES = {"application/json", "text/plain"}
_SENSITIVE_FIELD_KEYS = {
    "api_key",
    "apikey",
    "access_token",
    "authorization",
    "bearer_token",
    "client_secret",
    "cookie",
    "credentials",
    "password",
    "refresh_token",
    "secret",
    "set_cookie",
    "token",
}
_TERMINAL_RUN_STATUSES = {
    AgentRunStatus.COMPLETED,
    AgentRunStatus.PARTIAL,
    AgentRunStatus.FAILED,
    AgentRunStatus.REJECTED,
    AgentRunStatus.CANCELLED,
}


class ArtifactStoreError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class ArtifactRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str = Field(min_length=1, max_length=120)
    content_hash: str = Field(pattern="^[0-9a-f]{64}$")


class ArtifactLineage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1, max_length=120)
    user_id: str = Field(min_length=1, max_length=120)
    workspace_id: str = Field(min_length=1, max_length=120)
    project_id: str = Field(min_length=1, max_length=120)
    requirement_version_id: str = Field(min_length=1, max_length=120)
    plan_version_id: str | None = Field(default=None, max_length=120)
    attempt_id: str | None = Field(default=None, max_length=120)
    step_number: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_hierarchy(self) -> ArtifactLineage:
        if self.plan_version_id is None and (self.attempt_id is not None or self.step_number is not None):
            raise ValueError("execution lineage requires a plan")
        if (self.attempt_id is None) != (self.step_number is None):
            raise ValueError("attempt and step lineage must be set together")
        return self


class ArtifactReaderScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: str = Field(min_length=1, max_length=120)
    workspace_id: str = Field(min_length=1, max_length=120)
    project_id: str | None = Field(default=None, max_length=120)
    run_id: str | None = Field(default=None, max_length=120)


ArtifactLease = ExecutionLease


class ArtifactDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    artifact_id: str = Field(default_factory=lambda: new_id("artifact"), min_length=1, max_length=120)
    kind: str = Field(min_length=1, max_length=120)
    schema_version: str = Field(min_length=1, max_length=120)
    content_type: str = Field(default="application/json", min_length=1, max_length=120)
    content: Any


def _reject_duplicate_keys(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _strict_json(raw: str) -> Any:
    return json.loads(
        raw,
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_json_constant,
    )


def _encoded_content(draft: ArtifactDraft) -> str:
    if draft.content_type not in _V2_CONTENT_TYPES:
        raise ValueError("unsupported v2 Artifact content type")
    if draft.content_type == "application/json":
        value = _strict_json(draft.content) if isinstance(draft.content, str) else draft.content
        return canonical_json_bytes(value).decode("utf-8")
    if not isinstance(draft.content, str):
        raise TypeError("non-JSON Artifact content must be text")
    return draft.content


def contains_sensitive_artifact_content(content: str) -> bool:
    try:
        parsed = _strict_json(content)
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
        parsed = None
    pending = [parsed]
    inspected = 0
    while pending:
        current = pending.pop()
        inspected += 1
        if inspected > 100_000:
            return True
        if isinstance(current, dict):
            if any(str(key).lower().replace("-", "_").replace(" ", "_") in _SENSITIVE_FIELD_KEYS for key in current):
                return True
            pending.extend(current.values())
        elif isinstance(current, list):
            pending.extend(current)
    return (
        contains_credential(content)
        or redact_sensitive_text(content) != content
        or ("@" in content and _EMAIL.search(content) is not None)
        or (any(character.isdigit() for character in content) and _PHONE.search(content) is not None)
    )


class ArtifactStore:
    def __init__(self, repository: SQLiteStore):
        self.repository = repository

    def stage(
        self,
        lineage: ArtifactLineage,
        *,
        kind: str,
        schema_version: str,
        lease: ArtifactLease | None = None,
        artifact_id: str | None = None,
        content_type: str = "application/json",
    ) -> Artifact:
        if lineage.attempt_id is not None and lease is None:
            raise ArtifactStoreError("artifact_lease_required")
        if content_type not in _V2_CONTENT_TYPES:
            raise ArtifactStoreError("artifact_content_type_invalid")
        artifact = Artifact(
            id=artifact_id or new_id("artifact"),
            run_id=lineage.run_id,
            workspace_id=lineage.workspace_id,
            project_id=lineage.project_id,
            user_id=lineage.user_id,
            artifact_type=kind,
            content_type=content_type,
            content="",
            verification_state=ArtifactVerificationState.STAGING,
            schema_version=schema_version,
            requirement_version_id=lineage.requirement_version_id,
            plan_version_id=lineage.plan_version_id,
            attempt_id=lineage.attempt_id,
            step_number=lineage.step_number,
        )
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._validate_write_context(connection, lineage, lease)
            row = connection.execute("SELECT * FROM artifacts WHERE id = ?", (artifact.id,)).fetchone()
            if row is not None:
                try:
                    existing = Artifact.model_validate_json(row["payload"])
                except (TypeError, ValueError):
                    raise ArtifactStoreError("artifact_conflict") from None
                if (
                    existing.verification_state == ArtifactVerificationState.STAGING
                    and self._indexed_columns_match(row, existing)
                    and self._same_identity(existing, lineage, kind, schema_version)
                    and existing.content_type == content_type
                ):
                    return existing
                raise ArtifactStoreError("artifact_conflict")
            self._insert_artifact(connection, artifact)
            self._append_event(connection, artifact, "artifact_staged")
        return artifact

    def seal(
        self,
        lineage: ArtifactLineage,
        draft: ArtifactDraft,
        *,
        lease: ArtifactLease | None = None,
    ) -> ArtifactRef:
        return self.seal_bundle(lineage, [draft], lease=lease)[0]

    def seal_bundle(
        self,
        lineage: ArtifactLineage,
        drafts: list[ArtifactDraft],
        *,
        lease: ArtifactLease | None = None,
    ) -> list[ArtifactRef]:
        if not drafts:
            raise ArtifactStoreError("artifact_bundle_empty")
        if len({draft.artifact_id for draft in drafts}) != len(drafts):
            raise ArtifactStoreError("artifact_bundle_duplicate_id")
        if lineage.attempt_id is not None and lease is None:
            raise ArtifactStoreError("artifact_lease_required")
        prepared: list[tuple[ArtifactDraft, str, str, int]] = []
        for draft in drafts:
            try:
                content = _encoded_content(draft)
            except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
                raise ArtifactStoreError("artifact_content_invalid") from None
            encoded = content.encode("utf-8")
            if len(encoded) > MAX_ARTIFACT_BYTES:
                raise ArtifactStoreError("artifact_size_limit")
            if contains_sensitive_artifact_content(content):
                raise ArtifactStoreError("artifact_sensitive_content")
            prepared.append((draft, content, hashlib.sha256(encoded).hexdigest(), len(encoded)))

        sealed: list[Artifact] = []
        newly_sealed: list[Artifact] = []
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows: dict[str, sqlite3.Row | None] = {}
            for draft, *_ in prepared:
                row = connection.execute("SELECT * FROM artifacts WHERE id = ?", (draft.artifact_id,)).fetchone()
                rows[draft.artifact_id] = row
            if all(
                row is not None
                and row["verification_state"] == ArtifactVerificationState.SEALED.value
                and self._sealed_row_matches(row, lineage, draft, content, content_hash, size_bytes)
                for (draft, content, content_hash, size_bytes), row in zip(
                    prepared,
                    rows.values(),
                    strict=True,
                )
            ):
                return [
                    ArtifactRef(artifact_id=draft.artifact_id, content_hash=content_hash)
                    for draft, _, content_hash, _ in prepared
                ]
            self._validate_write_context(connection, lineage, lease)
            for draft, content, content_hash, size_bytes in prepared:
                row = rows[draft.artifact_id]
                if row is None:
                    continue
                if row["verification_state"] == ArtifactVerificationState.SEALED.value:
                    if not self._sealed_row_matches(row, lineage, draft, content, content_hash, size_bytes):
                        raise ArtifactStoreError("artifact_conflict")
                    continue
                if row["verification_state"] != ArtifactVerificationState.STAGING.value:
                    raise ArtifactStoreError("artifact_conflict")
                try:
                    staged = Artifact.model_validate_json(row["payload"])
                except (TypeError, ValueError):
                    raise ArtifactStoreError("artifact_conflict") from None
                if (
                    not self._indexed_columns_match(row, staged)
                    or not self._same_identity(staged, lineage, draft.kind, draft.schema_version)
                    or staged.content_type != draft.content_type
                ):
                    raise ArtifactStoreError("artifact_conflict")
            artifact_ids = [draft.artifact_id for draft, *_ in prepared]
            placeholders = ",".join("?" for _ in artifact_ids)
            used_bytes = connection.execute(
                f"""
                SELECT COALESCE(SUM(size_bytes), 0)
                FROM artifacts
                WHERE run_id = ?
                  AND verification_state IN (?, ?, ?)
                  AND id NOT IN ({placeholders})
                """,
                (
                    lineage.run_id,
                    ArtifactVerificationState.STAGING.value,
                    ArtifactVerificationState.SEALED.value,
                    ArtifactVerificationState.FAILED.value,
                    *artifact_ids,
                ),
            ).fetchone()[0]
            if used_bytes + sum(item[3] for item in prepared) > MAX_RUN_ARTIFACT_BYTES:
                raise ArtifactStoreError("artifact_run_quota")

            for draft, content, content_hash, size_bytes in prepared:
                row = rows[draft.artifact_id]
                if row is not None and row["verification_state"] == ArtifactVerificationState.SEALED.value:
                    sealed.append(Artifact.model_validate_json(row["payload"]))
                    continue
                artifact = Artifact(
                    id=draft.artifact_id,
                    run_id=lineage.run_id,
                    workspace_id=lineage.workspace_id,
                    project_id=lineage.project_id,
                    user_id=lineage.user_id,
                    artifact_type=draft.kind,
                    content_type=draft.content_type,
                    content=content,
                    verification_state=ArtifactVerificationState.SEALED,
                    schema_version=draft.schema_version,
                    content_hash=content_hash,
                    size_bytes=size_bytes,
                    requirement_version_id=lineage.requirement_version_id,
                    plan_version_id=lineage.plan_version_id,
                    attempt_id=lineage.attempt_id,
                    step_number=lineage.step_number,
                    created_at=(
                        Artifact.model_validate_json(row["payload"]).created_at if row is not None else now_utc()
                    ),
                    updated_at=now_utc(),
                )
                if row is None:
                    self._insert_artifact(connection, artifact)
                else:
                    self._update_artifact(connection, artifact)
                sealed.append(artifact)
                newly_sealed.append(artifact)
            if newly_sealed:
                self.repository._append_agent_run_events(
                    connection,
                    lineage.run_id,
                    [
                        (
                            "research_artifacts_sealed",
                            {
                                "artifacts": [
                                    {
                                        "artifact_id": artifact.id,
                                        "kind": artifact.artifact_type,
                                        "content_hash": artifact.content_hash,
                                    }
                                    for artifact in newly_sealed
                                ]
                            },
                        )
                    ],
                )
        return [ArtifactRef(artifact_id=item.id, content_hash=item.content_hash or "") for item in sealed]

    def settle_sent_tool_invocation(
        self,
        lineage: ArtifactLineage,
        draft: ArtifactDraft,
        *,
        lease: ArtifactLease,
        invocation_id: str,
        receipt: ToolReceipt,
        provider_operation_id: str | None = None,
        acknowledged_at: datetime | None = None,
    ) -> tuple[ArtifactRef, ToolInvocation]:
        return self._settle_tool_invocation(
            lineage,
            draft,
            lease=lease,
            invocation_id=invocation_id,
            receipt=receipt,
            provider_operation_id=provider_operation_id,
            acknowledged_at=acknowledged_at,
            expected_state=InvocationState.SENT,
        )

    def settle_reconciled_tool_invocation(
        self,
        lineage: ArtifactLineage,
        draft: ArtifactDraft,
        *,
        lease: ArtifactLease,
        invocation_id: str,
        receipt: ToolReceipt,
        provider_operation_id: str | None = None,
        acknowledged_at: datetime | None = None,
    ) -> tuple[ArtifactRef, ToolInvocation]:
        return self._settle_tool_invocation(
            lineage,
            draft,
            lease=lease,
            invocation_id=invocation_id,
            receipt=receipt,
            provider_operation_id=provider_operation_id,
            acknowledged_at=acknowledged_at,
            expected_state=InvocationState.UNKNOWN,
        )

    def _settle_tool_invocation(
        self,
        lineage: ArtifactLineage,
        draft: ArtifactDraft,
        *,
        lease: ArtifactLease,
        invocation_id: str,
        receipt: ToolReceipt,
        provider_operation_id: str | None,
        acknowledged_at: datetime | None,
        expected_state: InvocationState,
    ) -> tuple[ArtifactRef, ToolInvocation]:
        if lineage.attempt_id is None or draft.kind != "tool_result":
            raise ArtifactStoreError("artifact_context_invalid")
        try:
            content = _encoded_content(draft)
        except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
            raise ArtifactStoreError("artifact_content_invalid") from None
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_ARTIFACT_BYTES:
            raise ArtifactStoreError("artifact_size_limit")
        if contains_sensitive_artifact_content(content):
            raise ArtifactStoreError("artifact_sensitive_content")
        content_hash = hashlib.sha256(encoded).hexdigest()
        size_bytes = len(encoded)
        settled_at = acknowledged_at or now_utc()

        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            invocation_row = connection.execute(
                "SELECT * FROM research_tool_invocations WHERE id = ?",
                (invocation_id,),
            ).fetchone()
            if invocation_row is None:
                raise ArtifactStoreError("artifact_invocation_invalid")
            try:
                invocation = ToolInvocation.model_validate_json(invocation_row["payload"])
            except (RecursionError, TypeError, ValueError):
                raise ArtifactStoreError("artifact_invocation_invalid") from None
            if not self._invocation_projection_matches(invocation_row, invocation):
                raise ArtifactStoreError("artifact_invocation_invalid")

            if expected_state == InvocationState.UNKNOWN:
                self._validate_write_context(
                    connection,
                    lineage,
                    lease,
                    allow_off_settlement=True,
                )

            artifact_row = connection.execute(
                "SELECT * FROM artifacts WHERE id = ?",
                (draft.artifact_id,),
            ).fetchone()
            if invocation.state == InvocationState.ACKNOWLEDGED:
                if (
                    invocation.artifact_id == draft.artifact_id
                    and invocation.receipt == receipt
                    and (provider_operation_id is None or invocation.provider_operation_id == provider_operation_id)
                    and (expected_state != InvocationState.UNKNOWN or invocation.unknown_at is not None)
                    and artifact_row is not None
                    and artifact_row["verification_state"] == ArtifactVerificationState.SEALED.value
                    and self._sealed_row_matches(
                        artifact_row,
                        lineage,
                        draft,
                        content,
                        content_hash,
                        size_bytes,
                    )
                ):
                    return (
                        ArtifactRef(artifact_id=draft.artifact_id, content_hash=content_hash),
                        invocation,
                    )
                raise ArtifactStoreError("artifact_invocation_conflict")
            if (
                invocation.state != expected_state
                or invocation.run_id != lineage.run_id
                or invocation.plan_version_id != lineage.plan_version_id
                or invocation.active_attempt_id != lineage.attempt_id
                or invocation.step_number != lineage.step_number
                or invocation.sent_fencing_epoch is None
                or (
                    expected_state == InvocationState.SENT
                    and invocation.sent_fencing_epoch != lease.fencing_epoch
                )
                or (
                    expected_state == InvocationState.UNKNOWN
                    and invocation.sent_fencing_epoch > lease.fencing_epoch
                )
                or receipt.send_sequence != invocation.active_send_sequence
                or invocation.receipt is not None
                or invocation.artifact_id is not None
            ):
                raise ArtifactStoreError("artifact_invocation_invalid")
            self._validate_write_context(
                connection,
                lineage,
                lease,
                allow_off_settlement=True,
            )
            if artifact_row is not None:
                if artifact_row["verification_state"] != ArtifactVerificationState.STAGING.value:
                    raise ArtifactStoreError("artifact_conflict")
                try:
                    staged = Artifact.model_validate_json(artifact_row["payload"])
                except (RecursionError, TypeError, ValueError):
                    raise ArtifactStoreError("artifact_conflict") from None
                if (
                    not self._indexed_columns_match(artifact_row, staged)
                    or not self._same_identity(staged, lineage, draft.kind, draft.schema_version)
                    or staged.content_type != draft.content_type
                ):
                    raise ArtifactStoreError("artifact_conflict")
            used_bytes = connection.execute(
                """
                SELECT COALESCE(SUM(size_bytes), 0)
                FROM artifacts
                WHERE run_id = ? AND verification_state IN (?, ?, ?) AND id != ?
                """,
                (
                    lineage.run_id,
                    ArtifactVerificationState.STAGING.value,
                    ArtifactVerificationState.SEALED.value,
                    ArtifactVerificationState.FAILED.value,
                    draft.artifact_id,
                ),
            ).fetchone()[0]
            if used_bytes + size_bytes > MAX_RUN_ARTIFACT_BYTES:
                raise ArtifactStoreError("artifact_run_quota")
            artifact = Artifact(
                id=draft.artifact_id,
                run_id=lineage.run_id,
                workspace_id=lineage.workspace_id,
                project_id=lineage.project_id,
                user_id=lineage.user_id,
                artifact_type=draft.kind,
                content_type=draft.content_type,
                content=content,
                verification_state=ArtifactVerificationState.SEALED,
                schema_version=draft.schema_version,
                content_hash=content_hash,
                size_bytes=size_bytes,
                requirement_version_id=lineage.requirement_version_id,
                plan_version_id=lineage.plan_version_id,
                attempt_id=lineage.attempt_id,
                step_number=lineage.step_number,
                created_at=(
                    Artifact.model_validate_json(artifact_row["payload"]).created_at
                    if artifact_row is not None
                    else settled_at
                ),
                updated_at=settled_at,
            )
            if artifact_row is None:
                self._insert_artifact(connection, artifact)
            else:
                self._update_artifact(connection, artifact)
            try:
                acknowledged = ToolInvocation.model_validate(
                    {
                        **invocation.model_dump(mode="python"),
                        "state": InvocationState.ACKNOWLEDGED,
                        "receipt": receipt,
                        "artifact_id": artifact.id,
                        "provider_operation_id": provider_operation_id or invocation.provider_operation_id,
                        "acknowledged_at": settled_at,
                        "error_code": None,
                        "updated_at": settled_at,
                    }
                )
            except (TypeError, ValueError):
                raise ArtifactStoreError("artifact_invocation_invalid") from None
            cursor = connection.execute(
                """
                UPDATE research_tool_invocations
                SET state = ?, receipt_payload = ?, artifact_id = ?, provider_operation_id = ?,
                    acknowledged_at = ?, payload = ?, updated_at = ?
                WHERE id = ? AND state = ? AND active_attempt_id = ?
                  AND active_send_sequence = ? AND sent_fencing_epoch = ?
                """,
                (
                    acknowledged.state.value,
                    receipt.model_dump_json(),
                    artifact.id,
                    acknowledged.provider_operation_id,
                    settled_at.isoformat(),
                    acknowledged.model_dump_json(),
                    settled_at.isoformat(),
                    invocation.id,
                    expected_state.value,
                    invocation.active_attempt_id,
                    invocation.active_send_sequence,
                    invocation.sent_fencing_epoch,
                ),
            )
            if cursor.rowcount != 1:
                raise ArtifactStoreError("artifact_invocation_conflict")
            self.repository._append_agent_run_events(
                connection,
                lineage.run_id,
                [
                    (
                        "research_artifacts_sealed",
                        {
                            "artifacts": [
                                {
                                    "artifact_id": artifact.id,
                                    "kind": artifact.artifact_type,
                                    "content_hash": artifact.content_hash,
                                }
                            ],
                            "invocation_id": invocation.id,
                        },
                    )
                ],
            )
        return ArtifactRef(artifact_id=artifact.id, content_hash=content_hash), acknowledged

    def settle_model_call(
        self,
        lineage: ArtifactLineage,
        draft: ArtifactDraft,
        *,
        lease: ArtifactLease,
        receipt: ModelCallReceipt,
        settled_at: datetime | None = None,
    ) -> tuple[ArtifactRef, ModelCallReceipt]:
        if (
            lineage.attempt_id is None
            or lineage.step_number is None
            or draft.kind != "skill_result"
            or receipt.run_id != lineage.run_id
            or receipt.owner_kind != "attempt"
            or receipt.owner_id != lineage.attempt_id
            or receipt.stage != "competitive-analysis"
        ):
            raise ArtifactStoreError("artifact_model_call_invalid")
        try:
            content = _encoded_content(draft)
        except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
            raise ArtifactStoreError("artifact_content_invalid") from None
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_ARTIFACT_BYTES:
            raise ArtifactStoreError("artifact_size_limit")
        if contains_sensitive_artifact_content(content):
            raise ArtifactStoreError("artifact_sensitive_content")
        content_hash = hashlib.sha256(encoded).hexdigest()
        size_bytes = len(encoded)
        effective_settled_at = settled_at or now_utc()

        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            artifact_row = connection.execute(
                "SELECT * FROM artifacts WHERE id = ?",
                (draft.artifact_id,),
            ).fetchone()
            receipt_row = connection.execute(
                "SELECT payload FROM research_model_call_receipts WHERE id = ?",
                (receipt.id,),
            ).fetchone()
            existing_receipt: ModelCallReceipt | None = None
            if receipt_row is not None:
                try:
                    existing_receipt = ModelCallReceipt.model_validate_json(receipt_row["payload"])
                except (RecursionError, TypeError, ValueError):
                    raise ArtifactStoreError("artifact_model_call_invalid") from None
            if artifact_row is not None and existing_receipt is not None:
                if (
                    existing_receipt == receipt
                    and artifact_row["verification_state"] == ArtifactVerificationState.SEALED.value
                    and self._sealed_row_matches(
                        artifact_row,
                        lineage,
                        draft,
                        content,
                        content_hash,
                        size_bytes,
                    )
                ):
                    return ArtifactRef(artifact_id=draft.artifact_id, content_hash=content_hash), existing_receipt
                raise ArtifactStoreError("artifact_model_call_conflict")
            if existing_receipt is not None:
                raise ArtifactStoreError("artifact_model_call_conflict")
            if artifact_row is not None:
                if artifact_row["verification_state"] != ArtifactVerificationState.STAGING.value:
                    raise ArtifactStoreError("artifact_model_call_conflict")
                try:
                    staged = Artifact.model_validate_json(artifact_row["payload"])
                except (RecursionError, TypeError, ValueError):
                    raise ArtifactStoreError("artifact_model_call_conflict") from None
                if (
                    not self._indexed_columns_match(artifact_row, staged)
                    or not self._same_identity(staged, lineage, draft.kind, draft.schema_version)
                    or staged.content_type != draft.content_type
                ):
                    raise ArtifactStoreError("artifact_model_call_conflict")

            self._validate_write_context(connection, lineage, lease)
            owner = connection.execute(
                "SELECT run_id FROM research_attempts WHERE id = ?",
                (receipt.owner_id,),
            ).fetchone()
            if owner is None or owner["run_id"] != receipt.run_id:
                raise ArtifactStoreError("artifact_model_call_invalid")
            duplicate = connection.execute(
                """
                SELECT payload FROM research_model_call_receipts
                WHERE owner_kind = ? AND owner_id = ? AND stage = ? AND call_key = ?
                """,
                (receipt.owner_kind, receipt.owner_id, receipt.stage, receipt.call_key),
            ).fetchone()
            if duplicate is not None:
                raise ArtifactStoreError("artifact_model_call_conflict")
            used_bytes = connection.execute(
                """
                SELECT COALESCE(SUM(size_bytes), 0)
                FROM artifacts
                WHERE run_id = ? AND verification_state IN (?, ?, ?) AND id != ?
                """,
                (
                    lineage.run_id,
                    ArtifactVerificationState.STAGING.value,
                    ArtifactVerificationState.SEALED.value,
                    ArtifactVerificationState.FAILED.value,
                    draft.artifact_id,
                ),
            ).fetchone()[0]
            if used_bytes + size_bytes > MAX_RUN_ARTIFACT_BYTES:
                raise ArtifactStoreError("artifact_run_quota")
            artifact = Artifact(
                id=draft.artifact_id,
                run_id=lineage.run_id,
                workspace_id=lineage.workspace_id,
                project_id=lineage.project_id,
                user_id=lineage.user_id,
                artifact_type=draft.kind,
                content_type=draft.content_type,
                content=content,
                verification_state=ArtifactVerificationState.SEALED,
                schema_version=draft.schema_version,
                content_hash=content_hash,
                size_bytes=size_bytes,
                requirement_version_id=lineage.requirement_version_id,
                plan_version_id=lineage.plan_version_id,
                attempt_id=lineage.attempt_id,
                step_number=lineage.step_number,
                created_at=(
                    Artifact.model_validate_json(artifact_row["payload"]).created_at
                    if artifact_row is not None
                    else effective_settled_at
                ),
                updated_at=effective_settled_at,
            )
            if artifact_row is None:
                self._insert_artifact(connection, artifact)
            else:
                self._update_artifact(connection, artifact)
            connection.execute(
                """
                INSERT INTO research_model_call_receipts(
                    id, run_id, owner_kind, owner_id, stage, call_key, payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.id,
                    receipt.run_id,
                    receipt.owner_kind,
                    receipt.owner_id,
                    receipt.stage,
                    receipt.call_key,
                    receipt.model_dump_json(),
                    receipt.created_at.isoformat(),
                ),
            )
            self.repository._append_agent_run_events(
                connection,
                lineage.run_id,
                [
                    (
                        "research_model_call_settled",
                        {
                            "receipt_id": receipt.id,
                            "artifact_id": artifact.id,
                            "stage": receipt.stage,
                        },
                    )
                ],
            )
        return ArtifactRef(artifact_id=artifact.id, content_hash=content_hash), receipt

    def cleanup_expired_transients(self, *, now: datetime | None = None) -> int:
        effective_now = now or now_utc()
        cutoff = (effective_now - TRANSIENT_RETENTION).isoformat()
        transitioned = 0
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT a.*, w.phase AS workflow_phase, w.payload AS workflow_payload,
                       w.updated_at AS workflow_updated_at,
                       r.payload AS run_payload, r.orchestration_version AS run_orchestration_version,
                       r.updated_at AS run_updated_at
                FROM artifacts a
                JOIN research_workflows w ON w.run_id = a.run_id
                JOIN agent_runs r ON r.id = a.run_id
                WHERE a.verification_state IN (?, ?)
                  AND julianday(COALESCE(a.updated_at, a.created_at)) < julianday(?)
                """,
                (
                    ArtifactVerificationState.STAGING.value,
                    ArtifactVerificationState.FAILED.value,
                    cutoff,
                ),
            ).fetchall()
            for row in rows:
                reason, artifact = self._integrity_result(row)
                if row["verification_state"] == ArtifactVerificationState.STAGING.value:
                    if self._invalidate(
                        connection,
                        row,
                        reason or "artifact_staging_expired",
                        updated_at=effective_now,
                    ):
                        failed_row = connection.execute(
                            "SELECT * FROM artifacts WHERE id = ?",
                            (row["id"],),
                        ).fetchone()
                        self._append_cleanup_failure_audit(
                            connection,
                            failed_row or row,
                            failed_at=effective_now,
                        )
                        transitioned += 1
                    continue
                if not self._terminal_context_matches(row, now=effective_now):
                    continue
                self._purge_row(connection, row, actor="system_cleanup", purged_at=effective_now)
                self._append_purge_audit(
                    connection,
                    row,
                    actor="system_cleanup",
                    action="cleanup_research_artifact",
                    purged_at=effective_now,
                )
                transitioned += 1
        return transitioned

    def purge_expired_raw_tool_artifacts(self, *, now: datetime | None = None) -> int:
        effective_now = now or now_utc()
        purged = 0
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT a.*, w.phase AS workflow_phase, w.payload AS workflow_payload,
                       w.updated_at AS workflow_updated_at,
                       r.payload AS run_payload, r.orchestration_version AS run_orchestration_version,
                       r.updated_at AS run_updated_at
                FROM artifacts a
                JOIN research_workflows w ON w.run_id = a.run_id
                JOIN agent_runs r ON r.id = a.run_id
                WHERE a.verification_state = ?
                  AND a.artifact_type = 'tool_result'
                """,
                (ArtifactVerificationState.SEALED.value,),
            ).fetchall()
            for row in rows:
                terminal_at = self._terminal_timestamp(row, now=effective_now)
                if terminal_at is None or effective_now - terminal_at < RAW_TOOL_RETENTION:
                    continue
                reason, artifact = self._integrity_result(row)
                if reason is not None or artifact is None:
                    self._invalidate(
                        connection,
                        row,
                        reason or "artifact_payload_invalid",
                        updated_at=effective_now,
                    )
                    continue
                if not self._has_verified_evidence_source(connection, artifact):
                    continue
                self._purge_row(connection, row, actor="system_raw_retention", purged_at=effective_now)
                self._append_purge_audit(
                    connection,
                    row,
                    actor="system_raw_retention",
                    action="purge_raw_tool_artifact",
                    purged_at=effective_now,
                )
                purged += 1
        return purged

    def purge_research_data(
        self,
        run_id: str,
        *,
        actor_user_id: str,
        workspace_id: str,
        now: datetime | None = None,
    ) -> int:
        effective_now = now or now_utc()
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            purged_rows = self._purge_research_data_in_transaction(
                connection,
                run_id,
                actor_user_id=actor_user_id,
                workspace_id=workspace_id,
                purged_at=effective_now,
                expected_state_version=None,
                preserve_command_key=None,
            )
        return purged_rows

    def purge_research_data_command(
        self,
        run_id: str,
        *,
        actor_user_id: str,
        workspace_id: str,
        expected_state_version: int,
        idempotency_key: str,
        request_hash: str,
        now: datetime | None = None,
    ) -> ResearchCommandReceipt:
        if not idempotency_key or len(idempotency_key) > 120:
            raise ValueError("a bounded Idempotency-Key is required")
        effective_now = now or now_utc()
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run_row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if run_row is None:
                raise ArtifactStoreError("artifact_not_found")
            try:
                run = AgentRun.model_validate_json(run_row["payload"])
            except (RecursionError, TypeError, ValueError):
                raise ArtifactStoreError("artifact_context_invalid") from None
            if run.user_id != actor_user_id or run.workspace_id != workspace_id:
                raise ArtifactStoreError("artifact_not_found")
            existing_row = connection.execute(
                "SELECT payload FROM research_commands WHERE run_id = ? AND idempotency_key = ?",
                (run_id, idempotency_key),
            ).fetchone()
            if existing_row is not None:
                try:
                    existing = ResearchCommandReceipt.model_validate_json(existing_row["payload"])
                except (RecursionError, TypeError, ValueError):
                    raise ResearchStoreConflict("stored research command failed integrity verification") from None
                if existing.command_type != "purge" or existing.request_hash != request_hash:
                    raise ResearchStoreConflict("idempotency key was used for a different research command")
                return existing

            purged_rows = self._purge_research_data_in_transaction(
                connection,
                run_id,
                actor_user_id=actor_user_id,
                workspace_id=workspace_id,
                purged_at=effective_now,
                expected_state_version=expected_state_version,
                preserve_command_key=idempotency_key,
            )
            receipt = ResearchCommandReceipt(
                run_id=run_id,
                idempotency_key=idempotency_key,
                command_type="purge",
                request_hash=request_hash,
                response_status=200,
                response_payload={
                    "run_id": run_id,
                    "purged": True,
                    "artifact_count": purged_rows,
                    "purged_at": effective_now.isoformat(),
                    "retained": ["agent_run_input", "chat_messages", "audit_tombstones"],
                },
                created_at=effective_now,
            )
            connection.execute(
                """
                INSERT INTO research_commands(
                    run_id, idempotency_key, command_type, request_hash,
                    response_status, response_payload, payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.run_id,
                    receipt.idempotency_key,
                    receipt.command_type,
                    receipt.request_hash,
                    receipt.response_status,
                    json.dumps(receipt.response_payload, ensure_ascii=False, separators=(",", ":")),
                    receipt.model_dump_json(),
                    receipt.created_at.isoformat(),
                ),
            )
        return receipt

    def _purge_research_data_in_transaction(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        *,
        actor_user_id: str,
        workspace_id: str,
        purged_at: datetime,
        expected_state_version: int | None,
        preserve_command_key: str | None,
    ) -> int:
        run_row = connection.execute(
            "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        workflow_row = connection.execute(
            "SELECT phase, state_version, payload FROM research_workflows WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if run_row is None or workflow_row is None:
            raise ArtifactStoreError("artifact_not_found")
        try:
            run = AgentRun.model_validate_json(run_row["payload"])
            workflow = ResearchWorkflow.model_validate_json(workflow_row["payload"])
        except (RecursionError, TypeError, ValueError):
            raise ArtifactStoreError("artifact_context_invalid") from None
        if run.user_id != actor_user_id or run.workspace_id != workspace_id:
            raise ArtifactStoreError("artifact_not_found")
        if (
            run.orchestration_version != "research-v2"
            or run_row["orchestration_version"] != "research-v2"
            or run.status not in _TERMINAL_RUN_STATUSES
            or workflow.phase != ResearchPhase.TERMINAL
            or workflow_row["phase"] != ResearchPhase.TERMINAL.value
            or workflow.state_version != workflow_row["state_version"]
            or (
                expected_state_version is not None
                and workflow.state_version != expected_state_version
            )
        ):
            raise ArtifactStoreError("research_data_not_purgeable")

        rows = self._owner_purge_rows(connection, run)
        candidate_ids = [row["id"] for row in rows]
        purged_rows = 0
        for row in rows:
            if self._is_valid_purged_tombstone(row):
                continue
            self._purge_row(
                connection,
                row,
                actor=actor_user_id,
                purged_at=purged_at,
                fallback_run=run,
            )
            purged_rows += 1
        if candidate_ids:
            placeholders = ",".join("?" for _ in candidate_ids)
            remaining = connection.execute(
                f"SELECT * FROM artifacts WHERE id IN ({placeholders})",
                candidate_ids,
            ).fetchall()
        else:
            remaining = []
        if len(remaining) != len(candidate_ids) or any(
            not self._is_valid_purged_tombstone(row) for row in remaining
        ):
            raise ArtifactStoreError("artifact_purge_incomplete")
        rediscovered = self._owner_purge_rows(connection, run)
        if any(not self._is_valid_purged_tombstone(row) for row in rediscovered):
            raise ArtifactStoreError("artifact_purge_incomplete")
        attempt_ids = [
            row["id"]
            for row in connection.execute(
                "SELECT id FROM research_attempts WHERE run_id = ?",
                (run_id,),
            ).fetchall()
        ]
        if attempt_ids:
            placeholders = ",".join("?" for _ in attempt_ids)
            connection.execute(
                f"DELETE FROM research_steps WHERE attempt_id IN ({placeholders})",
                attempt_ids,
            )
        for table in (
            "research_tool_invocations",
            "research_model_call_receipts",
            "research_attempts",
            "research_plan_versions",
            "research_requirement_versions",
            "research_workflows",
        ):
            connection.execute(f"DELETE FROM {table} WHERE run_id = ?", (run_id,))
        if preserve_command_key is None:
            connection.execute("DELETE FROM research_commands WHERE run_id = ?", (run_id,))
        else:
            connection.execute(
                "DELETE FROM research_commands WHERE run_id = ? AND idempotency_key != ?",
                (run_id, preserve_command_key),
            )
        run.output_text = None
        run.updated_at = purged_at
        connection.execute(
            "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
            (run.model_dump_json(), purged_at.isoformat(), run_id),
        )
        audit = AuditEvent(
            actor=actor_user_id,
            action="purge_research_data",
            target_type="agent_run",
            target_id=run_id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            metadata={"artifact_count": purged_rows, "purged_at": purged_at.isoformat()},
            created_at=purged_at,
        )
        self._insert_audit_event(connection, audit)
        self.repository._append_agent_run_events(
            connection,
            run_id,
            [("research_data_purged", {"artifact_count": purged_rows})],
        )
        return purged_rows

    def read_verified(
        self,
        reference: ArtifactRef,
        *,
        scope: ArtifactLineage,
        expected_kind: str | None = None,
        expected_schema_version: str | None = None,
    ) -> Artifact:
        with self.repository._connect() as connection:
            row = connection.execute("SELECT * FROM artifacts WHERE id = ?", (reference.artifact_id,)).fetchone()
        return self._verify_row(
            row,
            reference=reference,
            scope=scope,
            reader_scope=None,
            invalidation_run=None,
            expected_kind=expected_kind,
            expected_schema_version=expected_schema_version,
        )

    def read_verified_tool_invocation(self, invocation_id: str) -> ToolInvocation:
        with self.repository._connect() as connection:
            row = connection.execute(
                "SELECT * FROM research_tool_invocations WHERE id = ?",
                (invocation_id,),
            ).fetchone()
        if row is None:
            raise ArtifactStoreError("artifact_invocation_not_found")
        try:
            invocation = ToolInvocation.model_validate_json(row["payload"])
        except (RecursionError, TypeError, ValueError):
            raise ArtifactStoreError("artifact_invocation_invalid") from None
        if not self._invocation_projection_matches(row, invocation):
            raise ArtifactStoreError("artifact_invocation_invalid")
        return invocation

    def reuse_verified_tool_request(
        self,
        invocation_id: str,
        *,
        operation_key: str,
        lineage: ArtifactLineage,
        draft: ArtifactDraft,
        lease: ArtifactLease,
    ) -> ArtifactRef:
        """Reuse an immutable request only when its origin is in the active retry lineage."""

        if (
            lineage.attempt_id is None
            or lineage.step_number is None
            or draft.kind != "tool_request"
            or draft.schema_version != "tool-request-v1"
        ):
            raise ArtifactStoreError("artifact_context_invalid")
        try:
            expected_content = _encoded_content(draft)
        except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
            raise ArtifactStoreError("artifact_content_invalid") from None
        expected_hash = hashlib.sha256(expected_content.encode("utf-8")).hexdigest()

        with self.repository._connect() as connection:
            self._validate_write_context(connection, lineage, lease)
            invocation_row = connection.execute(
                "SELECT * FROM research_tool_invocations WHERE id = ?",
                (invocation_id,),
            ).fetchone()
            if invocation_row is None:
                raise ArtifactStoreError("artifact_invocation_not_found")
            try:
                invocation = ToolInvocation.model_validate_json(invocation_row["payload"])
            except (RecursionError, TypeError, ValueError):
                raise ArtifactStoreError("artifact_invocation_invalid") from None
            if (
                not self._invocation_projection_matches(invocation_row, invocation)
                or invocation.state == InvocationState.CANCELLED
                or invocation.operation_key != operation_key
                or invocation.run_id != lineage.run_id
                or invocation.plan_version_id != lineage.plan_version_id
                or invocation.step_number != lineage.step_number
                or invocation.active_attempt_id != lineage.attempt_id
                or invocation.request_artifact_id != draft.artifact_id
                or invocation.resolved_input_hash != expected_hash
            ):
                raise ArtifactStoreError("artifact_invocation_invalid")
            artifact_row = connection.execute(
                "SELECT * FROM artifacts WHERE id = ?",
                (invocation.request_artifact_id,),
            ).fetchone()
            attempt_id = lineage.attempt_id
            origin_attempt_id = artifact_row["attempt_id"] if artifact_row is not None else None
            origin_is_ancestor = False
            visited: set[str] = set()
            while attempt_id not in visited and len(visited) < 64:
                visited.add(attempt_id)
                attempt_row = connection.execute(
                    "SELECT * FROM research_attempts WHERE id = ?",
                    (attempt_id,),
                ).fetchone()
                if attempt_row is None:
                    break
                try:
                    attempt = ExecutionAttempt.model_validate_json(attempt_row["payload"])
                except (RecursionError, TypeError, ValueError):
                    break
                if (
                    not SQLiteStore._research_attempt_projection_matches(attempt_row, attempt)
                    or attempt.run_id != lineage.run_id
                    or attempt.plan_version_id != lineage.plan_version_id
                ):
                    break
                if attempt.id == origin_attempt_id:
                    origin_is_ancestor = True
                    break
                if attempt.retry_of_attempt_id is None:
                    break
                attempt_id = attempt.retry_of_attempt_id
        reference = ArtifactRef(artifact_id=draft.artifact_id, content_hash=expected_hash)
        artifact = self._verify_row(
            artifact_row,
            reference=reference,
            scope=None,
            reader_scope=None,
            invalidation_run=None,
            expected_kind=draft.kind,
            expected_schema_version=draft.schema_version,
        )
        if (
            not origin_is_ancestor
            or artifact.content != expected_content
            or artifact.run_id != lineage.run_id
            or artifact.user_id != lineage.user_id
            or artifact.workspace_id != lineage.workspace_id
            or artifact.project_id != lineage.project_id
            or artifact.requirement_version_id != lineage.requirement_version_id
            or artifact.plan_version_id != lineage.plan_version_id
            or artifact.step_number != lineage.step_number
        ):
            raise ArtifactStoreError("artifact_reference_mismatch")
        return reference

    def read_verified_for_owner(
        self,
        artifact_id: str,
        *,
        reader_scope: ArtifactReaderScope,
        expected_reference: ArtifactRef | None = None,
    ) -> Artifact:
        if expected_reference is not None and expected_reference.artifact_id != artifact_id:
            raise ArtifactStoreError("artifact_reference_mismatch")
        artifact, verified = self.read_for_owner(
            artifact_id,
            reader_scope=reader_scope,
            expected_reference=expected_reference,
        )
        if not verified:
            raise ArtifactStoreError("artifact_unverified")
        return artifact

    def read_for_owner(
        self,
        artifact_id: str,
        *,
        reader_scope: ArtifactReaderScope,
        expected_reference: ArtifactRef | None = None,
    ) -> tuple[Artifact, bool]:
        if expected_reference is not None and expected_reference.artifact_id != artifact_id:
            raise ArtifactStoreError("artifact_reference_mismatch")
        with self.repository._connect() as connection:
            row = connection.execute(
                """
                SELECT a.*, r.payload AS run_payload,
                       r.orchestration_version AS run_orchestration_version
                FROM artifacts a
                JOIN agent_runs r ON r.id = a.run_id
                WHERE a.id = ?
                """,
                (artifact_id,),
            ).fetchone()
        if row is None:
            raise ArtifactStoreError("artifact_not_found")
        try:
            run = AgentRun.model_validate_json(row["run_payload"])
        except (TypeError, ValueError):
            raise ArtifactStoreError("artifact_not_found") from None
        if (
            row["run_orchestration_version"] != run.orchestration_version
            or row["run_id"] != run.id
            or run.user_id != reader_scope.user_id
            or run.workspace_id != reader_scope.workspace_id
            or (reader_scope.project_id is not None and run.project_id != reader_scope.project_id)
            or (reader_scope.run_id is not None and run.id != reader_scope.run_id)
        ):
            raise ArtifactStoreError("artifact_not_found")
        if run.orchestration_version == "v1":
            if row["verification_state"] is not None:
                raise ArtifactStoreError("artifact_integrity_failed")
            try:
                artifact = Artifact.model_validate_json(row["payload"])
            except (TypeError, ValueError):
                raise ArtifactStoreError("artifact_integrity_failed") from None
            if (
                artifact.verification_state is not None
                or artifact.run_id != run.id
                or artifact.user_id != run.user_id
                or artifact.workspace_id != run.workspace_id
                or artifact.project_id != run.project_id
            ):
                raise ArtifactStoreError("artifact_integrity_failed")
            return artifact, False
        artifact = self._verify_row(
            row,
            reference=expected_reference,
            scope=None,
            reader_scope=reader_scope,
            invalidation_run=run,
            expected_kind=None,
            expected_schema_version=None,
        )
        return artifact, True

    def _verify_row(
        self,
        row: sqlite3.Row | None,
        *,
        reference: ArtifactRef | None,
        scope: ArtifactLineage | None,
        reader_scope: ArtifactReaderScope | None,
        invalidation_run: AgentRun | None,
        expected_kind: str | None,
        expected_schema_version: str | None,
    ) -> Artifact:
        if row is None:
            raise ArtifactStoreError("artifact_not_found")
        reason, artifact = self._integrity_result(row)
        if reason is not None or artifact is None:
            self._invalidate_if_corrupt(
                row["id"],
                reason or "artifact_payload_invalid",
                fallback_lineage=scope,
                fallback_run=invalidation_run,
            )
            raise ArtifactStoreError("artifact_integrity_failed")
        self._raise_for_unreadable_state(row["verification_state"])
        if scope is not None and not self._same_scope(artifact, scope):
            raise ArtifactStoreError("artifact_not_found")
        if reader_scope is not None and (
            artifact.user_id != reader_scope.user_id
            or artifact.workspace_id != reader_scope.workspace_id
            or (reader_scope.project_id is not None and artifact.project_id != reader_scope.project_id)
            or (reader_scope.run_id is not None and artifact.run_id != reader_scope.run_id)
        ):
            raise ArtifactStoreError("artifact_not_found")
        if (
            (expected_kind is not None and artifact.artifact_type != expected_kind)
            or (expected_schema_version is not None and artifact.schema_version != expected_schema_version)
            or (reference is not None and artifact.content_hash != reference.content_hash)
        ):
            raise ArtifactStoreError("artifact_reference_mismatch")
        return artifact

    @staticmethod
    def _raise_for_unreadable_state(state: str | None) -> None:
        error_by_state = {
            ArtifactVerificationState.STAGING.value: "artifact_not_ready",
            ArtifactVerificationState.FAILED.value: "artifact_invalid",
            ArtifactVerificationState.PURGED.value: "artifact_purged",
            ArtifactVerificationState.LEGACY_UNVERIFIED.value: "artifact_unverified",
            None: "artifact_unverified",
        }
        if state != ArtifactVerificationState.SEALED.value:
            raise ArtifactStoreError(error_by_state.get(state, "artifact_integrity_failed"))

    def _integrity_result(self, row: sqlite3.Row) -> tuple[str | None, Artifact | None]:
        try:
            artifact = Artifact.model_validate_json(row["payload"])
        except (RecursionError, TypeError, ValueError):
            return "artifact_payload_invalid", None
        if not self._indexed_columns_match(row, artifact):
            return "artifact_index_mismatch", artifact
        if row["verification_state"] != ArtifactVerificationState.SEALED.value:
            return None, artifact
        encoded = artifact.content.encode("utf-8")
        if hashlib.sha256(encoded).hexdigest() != artifact.content_hash or len(encoded) != artifact.size_bytes:
            return "artifact_hash_mismatch", artifact
        if artifact.content_type == "application/json":
            try:
                canonical = canonical_json_bytes(_strict_json(artifact.content)).decode("utf-8")
            except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
                return "artifact_json_invalid", artifact
            if canonical != artifact.content:
                return "artifact_json_not_canonical", artifact
        return None, artifact

    def _invalidate_if_corrupt(
        self,
        artifact_id: str,
        reason: str,
        *,
        fallback_lineage: ArtifactLineage | None = None,
        fallback_run: AgentRun | None = None,
    ) -> None:
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
            if row is None:
                return
            current_reason, artifact = self._integrity_result(row)
            if current_reason is None:
                return
            payload_state = artifact.verification_state.value if artifact is not None else None
            if payload_state is None:
                try:
                    payload = json.loads(row["payload"])
                except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
                    payload = {}
                if isinstance(payload, dict):
                    payload_state = payload.get("verification_state")
            if (
                row["verification_state"] != ArtifactVerificationState.SEALED.value
                and payload_state != ArtifactVerificationState.SEALED.value
            ):
                return
            self._invalidate(
                connection,
                row,
                current_reason or reason,
                fallback_lineage=fallback_lineage,
                fallback_run=fallback_run,
            )

    @staticmethod
    def _same_identity(
        artifact: Artifact,
        lineage: ArtifactLineage,
        kind: str,
        schema_version: str,
    ) -> bool:
        return (
            ArtifactStore._same_scope(artifact, lineage)
            and artifact.artifact_type == kind
            and artifact.schema_version == schema_version
        )

    @staticmethod
    def _same_scope(artifact: Artifact, lineage: ArtifactLineage) -> bool:
        return (
            artifact.run_id == lineage.run_id
            and artifact.user_id == lineage.user_id
            and artifact.workspace_id == lineage.workspace_id
            and artifact.project_id == lineage.project_id
            and artifact.requirement_version_id == lineage.requirement_version_id
            and artifact.plan_version_id == lineage.plan_version_id
            and artifact.attempt_id == lineage.attempt_id
            and artifact.step_number == lineage.step_number
        )

    @staticmethod
    def _indexed_columns_match(row: sqlite3.Row, artifact: Artifact) -> bool:
        return (
            row["run_id"] == artifact.run_id
            and row["workspace_id"] == artifact.workspace_id
            and row["project_id"] == artifact.project_id
            and row["user_id"] == artifact.user_id
            and row["artifact_type"] == artifact.artifact_type
            and row["content_type"] == artifact.content_type
            and row["truncated"] == int(artifact.truncated)
            and row["verification_state"]
            == (artifact.verification_state.value if artifact.verification_state is not None else None)
            and row["schema_version"] == artifact.schema_version
            and row["content_hash"] == artifact.content_hash
            and row["size_bytes"] == artifact.size_bytes
            and row["requirement_version_id"] == artifact.requirement_version_id
            and row["plan_version_id"] == artifact.plan_version_id
            and row["attempt_id"] == artifact.attempt_id
            and row["step_number"] == artifact.step_number
            and row["purged_at"]
            == (artifact.purged_at.isoformat() if artifact.purged_at is not None else None)
            and row["purged_by"] == artifact.purged_by
            and row["created_at"] == artifact.created_at.isoformat()
            and row["updated_at"]
            == (artifact.updated_at.isoformat() if artifact.updated_at is not None else None)
        )

    @staticmethod
    def _terminal_timestamp(row: sqlite3.Row, *, now: datetime) -> datetime | None:
        try:
            run = AgentRun.model_validate_json(row["run_payload"])
            workflow = ResearchWorkflow.model_validate_json(row["workflow_payload"])
            workflow_updated_at = datetime.fromisoformat(row["workflow_updated_at"])
            run_updated_at = datetime.fromisoformat(row["run_updated_at"])
        except (RecursionError, TypeError, ValueError):
            return None
        if (
            workflow_updated_at.tzinfo is None
            or workflow_updated_at.utcoffset() is None
            or run_updated_at.tzinfo is None
            or run_updated_at.utcoffset() is None
            or workflow_updated_at > now
            or run_updated_at > now
        ):
            return None
        if not (
            run.id == row["run_id"]
            and run.orchestration_version == "research-v2"
            and row["run_orchestration_version"] == "research-v2"
            and run.status in _TERMINAL_RUN_STATUSES
            and workflow.run_id == run.id
            and workflow.phase == ResearchPhase.TERMINAL
            and row["workflow_phase"] == ResearchPhase.TERMINAL.value
            and workflow.updated_at == workflow_updated_at
            and run.updated_at == run_updated_at
        ):
            return None
        return workflow_updated_at

    @staticmethod
    def _terminal_context_matches(row: sqlite3.Row, *, now: datetime) -> bool:
        return ArtifactStore._terminal_timestamp(row, now=now) is not None

    def _has_verified_evidence_source(
        self,
        connection: sqlite3.Connection,
        origin: Artifact,
    ) -> bool:
        from agentmesh.research_orchestration.compiler import PlanCompileError, validate_execution_plan_version
        from agentmesh.research_orchestration.evidence import (  # local import avoids the ArtifactStore cycle
            EVIDENCE_SOURCE_SCHEMA,
            EvidenceError,
            EvidenceService,
            EvidenceSource,
        )

        if (
            origin.requirement_version_id is None
            or origin.plan_version_id is None
            or origin.attempt_id is None
            or origin.step_number is None
        ):
            return False
        plan_row = connection.execute(
            "SELECT * FROM research_plan_versions WHERE id = ?",
            (origin.plan_version_id,),
        ).fetchone()
        if plan_row is None:
            return False
        try:
            plan = ExecutionPlanVersion.model_validate_json(plan_row["payload"])
            plan_body = validate_execution_plan_version(plan)
        except (PlanCompileError, RecursionError, TypeError, ValueError):
            return False
        if (
            plan_row["id"] != plan.id
            or plan_row["run_id"] != plan.run_id
            or plan_row["requirement_version_id"] != plan.requirement_version_id
            or plan_row["version"] != plan.version
            or plan_row["plan_hash"] != plan.plan_hash
            or canonical_sha256(plan.payload) != plan.plan_hash
            or plan.id != origin.plan_version_id
            or plan.run_id != origin.run_id
            or plan.requirement_version_id != origin.requirement_version_id
        ):
            return False

        lineage = ArtifactLineage(
            run_id=origin.run_id,
            user_id=origin.user_id,
            workspace_id=origin.workspace_id,
            project_id=origin.project_id,
            requirement_version_id=origin.requirement_version_id,
            plan_version_id=origin.plan_version_id,
            attempt_id=origin.attempt_id,
            step_number=origin.step_number,
        )

        rows = connection.execute(
            """
            SELECT * FROM artifacts
            WHERE run_id = ? AND artifact_type = 'evidence_source' AND verification_state = ?
            """,
            (origin.run_id, ArtifactVerificationState.SEALED.value),
        ).fetchall()
        for row in rows:
            reason, evidence_artifact = self._integrity_result(row)
            if reason is not None or evidence_artifact is None:
                continue
            if (
                evidence_artifact.artifact_type != "evidence_source"
                or evidence_artifact.schema_version != EVIDENCE_SOURCE_SCHEMA
                or not self._same_scope(evidence_artifact, lineage)
            ):
                continue
            try:
                evidence = EvidenceSource.model_validate_json(evidence_artifact.content)
                invocation_row = connection.execute(
                    "SELECT * FROM research_tool_invocations WHERE id = ?",
                    (evidence.tool_invocation_id,),
                ).fetchone()
                if invocation_row is None:
                    continue
                invocation = ToolInvocation.model_validate_json(invocation_row["payload"])
                if not self._invocation_projection_matches(invocation_row, invocation):
                    continue
                EvidenceService._validate_source_provenance(
                    plan=plan,
                    plan_body=plan_body,
                    source_ref=ArtifactRef(
                        artifact_id=evidence_artifact.id,
                        content_hash=evidence_artifact.content_hash or "",
                    ),
                    source=evidence,
                    lineage=lineage,
                    invocation=invocation,
                    raw_artifact=origin,
                )
            except (EvidenceError, RecursionError, TypeError, ValueError):
                continue
            return True
        return False

    @staticmethod
    def _lineage_owner(
        connection: sqlite3.Connection,
        values: sqlite3.Row | dict[str, Any],
    ) -> tuple[bool, str | None]:
        def field(name: str) -> Any:
            try:
                return values[name]
            except (IndexError, KeyError):
                return None

        requirement_id = field("requirement_version_id")
        plan_id = field("plan_version_id")
        attempt_id = field("attempt_id")
        step_number = field("step_number")
        has_lineage = any(value is not None for value in (requirement_id, plan_id, attempt_id, step_number))
        if not has_lineage:
            return False, None
        if any(
            value is not None and (not isinstance(value, str) or not value)
            for value in (requirement_id, plan_id, attempt_id)
        ):
            return True, None
        if step_number is not None and (
            isinstance(step_number, bool) or not isinstance(step_number, int) or step_number < 1
        ):
            return True, None

        owners: set[str] = set()
        if requirement_id is not None:
            requirement_row = connection.execute(
                "SELECT run_id FROM research_requirement_versions WHERE id = ?",
                (requirement_id,),
            ).fetchone()
            if requirement_row is None:
                return True, None
            owners.add(requirement_row["run_id"])
        if plan_id is not None:
            plan_row = connection.execute(
                "SELECT run_id, requirement_version_id FROM research_plan_versions WHERE id = ?",
                (plan_id,),
            ).fetchone()
            if plan_row is None or (
                requirement_id is not None and plan_row["requirement_version_id"] != requirement_id
            ):
                return True, None
            owners.add(plan_row["run_id"])
        if attempt_id is not None:
            attempt_row = connection.execute(
                "SELECT run_id, plan_version_id FROM research_attempts WHERE id = ?",
                (attempt_id,),
            ).fetchone()
            if attempt_row is None or (plan_id is not None and attempt_row["plan_version_id"] != plan_id):
                return True, None
            owners.add(attempt_row["run_id"])
        if step_number is not None:
            if attempt_id is None:
                return True, None
            step_row = connection.execute(
                "SELECT 1 FROM research_steps WHERE attempt_id = ? AND step_number = ?",
                (attempt_id, step_number),
            ).fetchone()
            if step_row is None:
                return True, None
        if len(owners) != 1:
            return True, None
        return True, next(iter(owners))

    def _owner_purge_rows(self, connection: sqlite3.Connection, run: AgentRun) -> list[sqlite3.Row]:
        candidates: list[sqlite3.Row] = []
        for row in connection.execute("SELECT * FROM artifacts").fetchall():
            raw_payload = row["payload"] if isinstance(row["payload"], str) else ""
            try:
                payload_values = _strict_json(raw_payload)
            except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
                payload_values = None
            if not isinstance(payload_values, dict):
                if row["run_id"] == run.id:
                    candidates.append(row)
                elif run.id in raw_payload and '"run_id"' in raw_payload:
                    raise ArtifactStoreError("artifact_purge_scope_ambiguous")
                continue

            payload_run_id = payload_values.get("run_id")
            row_has_lineage, row_owner = self._lineage_owner(connection, row)
            payload_has_lineage, payload_owner = self._lineage_owner(connection, payload_values)
            if row["run_id"] == run.id:
                if (
                    payload_run_id != run.id
                    and payload_has_lineage
                    and payload_owner is not None
                    and payload_owner == payload_run_id
                ):
                    raise ArtifactStoreError("artifact_purge_scope_ambiguous")
                candidates.append(row)
                continue
            if payload_run_id != run.id:
                continue
            if any(
                payload_values.get(name) != getattr(run, name)
                for name in ("user_id", "workspace_id", "project_id")
            ):
                raise ArtifactStoreError("artifact_purge_scope_ambiguous")
            if not payload_has_lineage or payload_owner != run.id:
                raise ArtifactStoreError("artifact_purge_scope_ambiguous")
            if row_has_lineage and row_owner != run.id:
                raise ArtifactStoreError("artifact_purge_scope_ambiguous")
            candidates.append(row)
        return candidates

    def _is_valid_purged_tombstone(self, row: sqlite3.Row) -> bool:
        if row["verification_state"] != ArtifactVerificationState.PURGED.value:
            return False
        raw_payload = row["payload"]
        if not isinstance(raw_payload, str):
            return False
        try:
            raw_values = _strict_json(raw_payload)
            artifact = Artifact.model_validate(raw_values)
        except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
            return False
        if not isinstance(raw_values, dict) or raw_values != artifact.model_dump(mode="json"):
            return False
        reason, artifact = self._integrity_result(row)
        return reason is None and artifact is not None and artifact.content == ""

    @staticmethod
    def _purge_row(
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        actor: str,
        purged_at: datetime,
        fallback_run: AgentRun | None = None,
    ) -> None:
        raw_payload = row["payload"] if isinstance(row["payload"], str) else ""
        try:
            source = Artifact.model_validate_json(raw_payload)
        except (RecursionError, TypeError, ValueError):
            source = None
        try:
            payload_values = json.loads(raw_payload)
        except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
            payload_values = {}
        if not isinstance(payload_values, dict):
            payload_values = {}

        def value(name: str, fallback: Any = None) -> Any:
            if source is not None:
                candidate = getattr(source, name)
                if candidate is not None:
                    return candidate
            candidate = payload_values.get(name)
            if candidate is not None:
                return candidate
            try:
                candidate = row[name]
            except (IndexError, KeyError):
                candidate = None
            return candidate if candidate is not None else fallback

        content = value("content", raw_payload)
        if not isinstance(content, str):
            content = raw_payload
        encoded = content.encode("utf-8")

        stored_hash = row["content_hash"]
        if not isinstance(stored_hash, str) or re.fullmatch(r"[0-9a-f]{64}", stored_hash) is None:
            stored_hash = value("content_hash")
        content_hash = (
            stored_hash
            if isinstance(stored_hash, str) and re.fullmatch(r"[0-9a-f]{64}", stored_hash) is not None
            else hashlib.sha256(encoded).hexdigest()
        )
        stored_size = row["size_bytes"]
        if isinstance(stored_size, bool) or not isinstance(stored_size, int) or stored_size < 0:
            stored_size = value("size_bytes")
        size_bytes = (
            stored_size
            if isinstance(stored_size, int) and not isinstance(stored_size, bool) and stored_size >= 0
            else len(encoded)
        )

        def required_text(name: str, fallback: str) -> str:
            candidate = value(name, fallback)
            return candidate if isinstance(candidate, str) and candidate else fallback

        def routed_text(name: str, fallback: str) -> str:
            if fallback_run is not None:
                candidate = fallback_run.id if name == "run_id" else getattr(fallback_run, name, None)
                if isinstance(candidate, str) and candidate:
                    return candidate
            try:
                candidate = row[name]
            except (IndexError, KeyError):
                candidate = None
            if isinstance(candidate, str) and candidate:
                return candidate
            return required_text(name, fallback)

        def optional_text(name: str) -> str | None:
            candidate = value(name)
            return candidate[:120] if isinstance(candidate, str) and candidate else None

        plan_version_id = optional_text("plan_version_id")
        attempt_id = optional_text("attempt_id")
        step_number = value("step_number")
        if isinstance(step_number, bool) or not isinstance(step_number, int) or step_number < 1:
            step_number = None
        if plan_version_id is None or (attempt_id is None) != (step_number is None):
            attempt_id = None
            step_number = None
        created_at_value = value("created_at", purged_at)
        try:
            created_at = (
                created_at_value
                if isinstance(created_at_value, datetime)
                else datetime.fromisoformat(str(created_at_value))
            )
        except ValueError:
            created_at = purged_at
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            created_at = created_at.replace(tzinfo=UTC)
        try:
            tombstone = Artifact(
                id=row["id"],
                run_id=routed_text("run_id", "invalid_run"),
                workspace_id=routed_text("workspace_id", "unknown_workspace"),
                project_id=routed_text("project_id", "unknown_project"),
                user_id=routed_text("user_id", "unknown_user"),
                artifact_type=required_text("artifact_type", "legacy_artifact"),
                content_type=required_text("content_type", "text/plain"),
                content="",
                truncated=bool(value("truncated", False)),
                verification_state=ArtifactVerificationState.PURGED,
                schema_version=optional_text("schema_version"),
                content_hash=content_hash,
                size_bytes=size_bytes,
                requirement_version_id=optional_text("requirement_version_id"),
                plan_version_id=plan_version_id,
                attempt_id=attempt_id,
                step_number=step_number,
                purged_at=purged_at,
                purged_by=actor,
                created_at=created_at,
                updated_at=purged_at,
            )
        except (TypeError, ValueError):
            raise ArtifactStoreError("artifact_context_invalid") from None
        cursor = connection.execute(
            """
            UPDATE artifacts
            SET run_id = ?, payload = ?, created_at = ?, workspace_id = ?, project_id = ?,
                user_id = ?, artifact_type = ?, content_type = ?, truncated = ?,
                verification_state = ?, schema_version = ?, content_hash = ?, size_bytes = ?,
                requirement_version_id = ?, plan_version_id = ?, attempt_id = ?, step_number = ?,
                purged_at = ?, purged_by = ?, updated_at = ?
            WHERE id = ? AND verification_state IS ?
            """,
            (
                tombstone.run_id,
                tombstone.model_dump_json(),
                tombstone.created_at.isoformat(),
                tombstone.workspace_id,
                tombstone.project_id,
                tombstone.user_id,
                tombstone.artifact_type,
                tombstone.content_type,
                int(tombstone.truncated),
                ArtifactVerificationState.PURGED.value,
                tombstone.schema_version,
                content_hash,
                size_bytes,
                tombstone.requirement_version_id,
                tombstone.plan_version_id,
                tombstone.attempt_id,
                tombstone.step_number,
                purged_at.isoformat(),
                actor,
                purged_at.isoformat(),
                row["id"],
                row["verification_state"],
            ),
        )
        if cursor.rowcount != 1:
            raise ArtifactStoreError("artifact_conflict")

    def _append_cleanup_failure_audit(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        failed_at: datetime,
    ) -> None:
        self._insert_audit_event(
            connection,
            AuditEvent(
                actor="system_cleanup",
                action="cleanup_research_artifact",
                target_type="artifact",
                target_id=row["id"],
                workspace_id=row["workspace_id"],
                project_id=row["project_id"],
                metadata={
                    "run_id": row["run_id"],
                    "kind": row["artifact_type"],
                    "state": ArtifactVerificationState.FAILED.value,
                    "failed_at": failed_at.isoformat(),
                },
                created_at=failed_at,
            ),
        )

    def _append_purge_audit(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        actor: str,
        action: str,
        purged_at: datetime,
    ) -> None:
        audit = AuditEvent(
            actor=actor,
            action=action,
            target_type="artifact",
            target_id=row["id"],
            workspace_id=row["workspace_id"],
            project_id=row["project_id"],
            metadata={
                "run_id": row["run_id"],
                "kind": row["artifact_type"],
                "content_hash": row["content_hash"],
                "purged_at": purged_at.isoformat(),
            },
            created_at=purged_at,
        )
        self._insert_audit_event(connection, audit)
        self.repository._append_agent_run_events(
            connection,
            row["run_id"],
            [
                (
                    "artifact_purged",
                    {
                        "artifact_id": row["id"],
                        "kind": row["artifact_type"],
                        "actor": actor,
                    },
                )
            ],
        )

    @staticmethod
    def _insert_audit_event(connection: sqlite3.Connection, audit: AuditEvent) -> None:
        connection.execute(
            """
            INSERT INTO records(collection, id, payload)
            VALUES ('audit_events', ?, ?)
            """,
            (audit.id, audit.model_dump_json()),
        )

    def _sealed_row_matches(
        self,
        row: sqlite3.Row,
        lineage: ArtifactLineage,
        draft: ArtifactDraft,
        content: str,
        content_hash: str,
        size_bytes: int,
    ) -> bool:
        try:
            artifact = Artifact.model_validate_json(row["payload"])
        except (RecursionError, TypeError, ValueError):
            return False
        return (
            self._indexed_columns_match(row, artifact)
            and self._same_identity(artifact, lineage, draft.kind, draft.schema_version)
            and artifact.content_type == draft.content_type
            and artifact.content == content
            and artifact.content_hash == content_hash
            and artifact.size_bytes == size_bytes
        )

    def _validate_write_context(
        self,
        connection: sqlite3.Connection,
        lineage: ArtifactLineage,
        lease: ArtifactLease | None,
        *,
        allow_off_settlement: bool = False,
    ) -> None:
        run_row = connection.execute(
            "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
            (lineage.run_id,),
        ).fetchone()
        if run_row is None:
            raise ArtifactStoreError("artifact_context_invalid")
        try:
            run = AgentRun.model_validate_json(run_row["payload"])
        except (TypeError, ValueError):
            raise ArtifactStoreError("artifact_context_invalid") from None
        if (
            run.orchestration_version != "research-v2"
            or run_row["orchestration_version"] != "research-v2"
            or run.user_id != lineage.user_id
            or run.workspace_id != lineage.workspace_id
            or run.project_id != lineage.project_id
        ):
            raise ArtifactStoreError("artifact_context_invalid")
        if run.status in _TERMINAL_RUN_STATUSES or (
            run.orchestration_mode == "off" and not allow_off_settlement
        ):
            raise ArtifactStoreError("artifact_write_blocked")
        workflow_row = connection.execute(
            """
            SELECT phase, active_gate, active_requirement_version_id, active_plan_version_id,
                   active_attempt_id, state_version, payload
            FROM research_workflows WHERE run_id = ?
            """,
            (lineage.run_id,),
        ).fetchone()
        if workflow_row is None:
            raise ArtifactStoreError("artifact_context_invalid")
        try:
            workflow = ResearchWorkflow.model_validate_json(workflow_row["payload"])
        except (TypeError, ValueError):
            raise ArtifactStoreError("artifact_context_invalid") from None
        if (
            workflow_row["phase"] != workflow.phase.value
            or workflow_row["active_gate"] != workflow.active_gate.value
            or workflow_row["active_requirement_version_id"] != workflow.active_requirement_version_id
            or workflow_row["active_plan_version_id"] != workflow.active_plan_version_id
            or workflow_row["active_attempt_id"] != workflow.active_attempt_id
            or workflow_row["state_version"] != workflow.state_version
        ):
            raise ArtifactStoreError("artifact_context_invalid")
        if workflow.phase == ResearchPhase.TERMINAL:
            raise ArtifactStoreError("artifact_write_blocked")
        requirement = connection.execute(
            "SELECT run_id, content_hash, payload FROM research_requirement_versions WHERE id = ?",
            (lineage.requirement_version_id,),
        ).fetchone()
        if requirement is None or requirement["run_id"] != lineage.run_id:
            raise ArtifactStoreError("artifact_context_invalid")
        try:
            requirement_payload = json.loads(requirement["payload"])
            requirement_body = requirement_payload["payload"]
        except (json.JSONDecodeError, KeyError, TypeError):
            raise ArtifactStoreError("artifact_context_invalid") from None
        try:
            requirement_hash_matches = canonical_sha256(requirement_body) == requirement["content_hash"]
        except (TypeError, ValueError):
            requirement_hash_matches = False
        if requirement_payload.get("content_hash") != requirement["content_hash"] or not requirement_hash_matches:
            raise ArtifactStoreError("artifact_context_invalid")
        if workflow.active_requirement_version_id != lineage.requirement_version_id:
            raise ArtifactStoreError("artifact_context_invalid")

        plan_row: sqlite3.Row | None = None
        if lineage.plan_version_id is not None:
            plan_row = connection.execute(
                "SELECT run_id, requirement_version_id, plan_hash, payload FROM research_plan_versions WHERE id = ?",
                (lineage.plan_version_id,),
            ).fetchone()
            if (
                plan_row is None
                or plan_row["run_id"] != lineage.run_id
                or plan_row["requirement_version_id"] != lineage.requirement_version_id
            ):
                raise ArtifactStoreError("artifact_context_invalid")
            try:
                plan_payload = json.loads(plan_row["payload"])
                plan_body = plan_payload["payload"]
            except (json.JSONDecodeError, KeyError, TypeError):
                raise ArtifactStoreError("artifact_context_invalid") from None
            try:
                plan_hash_matches = canonical_sha256(plan_body) == plan_row["plan_hash"]
            except (TypeError, ValueError):
                plan_hash_matches = False
            if plan_payload.get("plan_hash") != plan_row["plan_hash"] or not plan_hash_matches:
                raise ArtifactStoreError("artifact_context_invalid")
            if workflow.active_plan_version_id != lineage.plan_version_id:
                raise ArtifactStoreError("artifact_context_invalid")

        if lineage.attempt_id is None:
            if lease is not None:
                raise ArtifactStoreError("artifact_context_invalid")
            if workflow.phase not in {ResearchPhase.REQUIREMENT, ResearchPhase.PLANNING}:
                raise ArtifactStoreError("artifact_write_blocked")
            return
        if lease is None:
            raise ArtifactStoreError("artifact_lease_required")
        if (
            plan_row is None
            or (
                run.orchestration_mode != "execute"
                and not (allow_off_settlement and run.orchestration_mode == "off")
            )
            or run.status != AgentRunStatus.RUNNING
            or workflow.phase != ResearchPhase.EXECUTION
            or workflow.active_gate.value != "none"
            or workflow.active_attempt_id != lineage.attempt_id
        ):
            raise ArtifactStoreError("artifact_write_blocked")
        attempt_row = connection.execute(
            """
            SELECT run_id, plan_version_id, status, lease_owner, lease_token, fencing_epoch,
                   lease_expires_at, payload
            FROM research_attempts WHERE id = ?
            """,
            (lineage.attempt_id,),
        ).fetchone()
        if attempt_row is None:
            raise ArtifactStoreError("artifact_context_invalid")
        try:
            attempt = ExecutionAttempt.model_validate_json(attempt_row["payload"])
        except (TypeError, ValueError):
            raise ArtifactStoreError("artifact_context_invalid") from None
        if (
            attempt.run_id != lineage.run_id
            or attempt.plan_version_id != lineage.plan_version_id
            or attempt_row["run_id"] != attempt.run_id
            or attempt_row["plan_version_id"] != attempt.plan_version_id
            or attempt_row["status"] != attempt.status.value
            or attempt_row["lease_owner"] != attempt.lease_owner
            or attempt_row["lease_token"] != attempt.lease_token
            or attempt_row["fencing_epoch"] != attempt.fencing_epoch
            or attempt_row["lease_expires_at"]
            != (attempt.lease_expires_at.isoformat() if attempt.lease_expires_at is not None else None)
            or attempt.status != AttemptStatus.RUNNING
            or attempt.lease_owner != lease.owner
            or attempt.lease_token != lease.token
            or attempt.fencing_epoch != lease.fencing_epoch
            or attempt.lease_expires_at is None
            or attempt.lease_expires_at <= datetime.now(UTC)
        ):
            raise ArtifactStoreError("artifact_lease_lost")

        step_row = connection.execute(
            "SELECT status, claim_epoch, payload FROM research_steps WHERE attempt_id = ? AND step_number = ?",
            (lineage.attempt_id, lineage.step_number),
        ).fetchone()
        if step_row is None:
            raise ArtifactStoreError("artifact_context_invalid")
        plan_steps = plan_body.get("steps") if isinstance(plan_body, dict) else None
        if not any(
            isinstance(item, dict) and item.get("step_number") == lineage.step_number
            for item in plan_steps or []
        ):
            raise ArtifactStoreError("artifact_context_invalid")
        try:
            step = ResearchStep.model_validate_json(step_row["payload"])
        except (TypeError, ValueError):
            raise ArtifactStoreError("artifact_context_invalid") from None
        if (
            step_row["status"] != step.status.value
            or step_row["claim_epoch"] != step.claim_epoch
            or step.attempt_id != lineage.attempt_id
            or step.step_number != lineage.step_number
            or step.status != StepStatus.RUNNING
            or step.claim_epoch != lease.fencing_epoch
        ):
            raise ArtifactStoreError("artifact_lease_lost")

    @staticmethod
    def _invocation_projection_matches(row: sqlite3.Row, invocation: ToolInvocation) -> bool:
        return SQLiteStore._research_invocation_projection_matches(row, invocation)

    @staticmethod
    def _insert_artifact(connection: sqlite3.Connection, artifact: Artifact) -> None:
        try:
            connection.execute(
                """
                INSERT INTO artifacts(
                    id, run_id, payload, created_at, workspace_id, project_id, user_id,
                    artifact_type, content_type, truncated, verification_state, schema_version,
                    content_hash, size_bytes, requirement_version_id, plan_version_id,
                    attempt_id, step_number, purged_at, purged_by, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.id,
                    artifact.run_id,
                    artifact.model_dump_json(),
                    artifact.created_at.isoformat(),
                    artifact.workspace_id,
                    artifact.project_id,
                    artifact.user_id,
                    artifact.artifact_type,
                    artifact.content_type,
                    int(artifact.truncated),
                    artifact.verification_state.value if artifact.verification_state is not None else None,
                    artifact.schema_version,
                    artifact.content_hash,
                    artifact.size_bytes,
                    artifact.requirement_version_id,
                    artifact.plan_version_id,
                    artifact.attempt_id,
                    artifact.step_number,
                    artifact.purged_at.isoformat() if artifact.purged_at else None,
                    artifact.purged_by,
                    artifact.updated_at.isoformat() if artifact.updated_at else None,
                ),
            )
        except sqlite3.IntegrityError:
            raise ArtifactStoreError("artifact_conflict") from None

    @staticmethod
    def _update_artifact(connection: sqlite3.Connection, artifact: Artifact) -> None:
        cursor = connection.execute(
            """
            UPDATE artifacts SET
                payload = ?, workspace_id = ?, project_id = ?, user_id = ?, artifact_type = ?,
                content_type = ?, truncated = ?, verification_state = ?, schema_version = ?,
                content_hash = ?, size_bytes = ?, requirement_version_id = ?, plan_version_id = ?,
                attempt_id = ?, step_number = ?, purged_at = ?, purged_by = ?, updated_at = ?
            WHERE id = ? AND verification_state = ?
            """,
            (
                artifact.model_dump_json(),
                artifact.workspace_id,
                artifact.project_id,
                artifact.user_id,
                artifact.artifact_type,
                artifact.content_type,
                int(artifact.truncated),
                artifact.verification_state.value,
                artifact.schema_version,
                artifact.content_hash,
                artifact.size_bytes,
                artifact.requirement_version_id,
                artifact.plan_version_id,
                artifact.attempt_id,
                artifact.step_number,
                artifact.purged_at.isoformat() if artifact.purged_at else None,
                artifact.purged_by,
                artifact.updated_at.isoformat() if artifact.updated_at else None,
                artifact.id,
                ArtifactVerificationState.STAGING.value,
            ),
        )
        if cursor.rowcount != 1:
            raise ArtifactStoreError("artifact_conflict")

    def _invalidate(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        reason: str,
        *,
        updated_at: datetime | None = None,
        fallback_lineage: ArtifactLineage | None = None,
        fallback_run: AgentRun | None = None,
    ) -> bool:
        effective_now = updated_at or now_utc()
        raw_payload = row["payload"] if isinstance(row["payload"], str) else ""
        try:
            source = Artifact.model_validate_json(raw_payload)
        except (RecursionError, TypeError, ValueError):
            source = None
        try:
            payload_values = json.loads(raw_payload)
        except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
            payload_values = {}
        if not isinstance(payload_values, dict):
            payload_values = {}

        def value(name: str, fallback: Any = None) -> Any:
            if source is not None:
                candidate = getattr(source, name)
                if candidate is not None:
                    return candidate
            candidate = payload_values.get(name)
            if candidate is not None:
                return candidate
            try:
                candidate = row[name]
            except (IndexError, KeyError):
                candidate = None
            return candidate if candidate is not None else fallback

        def required_text(name: str, fallback: str) -> str:
            candidate = value(name, fallback)
            return candidate if isinstance(candidate, str) and candidate else fallback

        def routed_text(name: str, fallback: str) -> str:
            if fallback_lineage is not None:
                candidate = getattr(fallback_lineage, name, None)
                if isinstance(candidate, str) and candidate:
                    return candidate
            if fallback_run is not None:
                candidate = fallback_run.id if name == "run_id" else getattr(fallback_run, name, None)
                if isinstance(candidate, str) and candidate:
                    return candidate
            try:
                candidate = row[name]
            except (IndexError, KeyError):
                candidate = None
            if isinstance(candidate, str) and candidate:
                return candidate
            return required_text(name, fallback)

        def optional_text(name: str) -> str | None:
            candidate = value(name)
            return candidate[:120] if isinstance(candidate, str) and candidate else None

        content_hash = next(
            (
                candidate
                for candidate in (
                    row["content_hash"],
                    getattr(source, "content_hash", None),
                    payload_values.get("content_hash"),
                )
                if isinstance(candidate, str) and re.fullmatch(r"[0-9a-f]{64}", candidate) is not None
            ),
            None,
        )
        size_bytes = next(
            (
                candidate
                for candidate in (
                    row["size_bytes"],
                    getattr(source, "size_bytes", None),
                    payload_values.get("size_bytes"),
                )
                if isinstance(candidate, int) and not isinstance(candidate, bool) and candidate >= 0
            ),
            None,
        )

        def lineage_value(name: str) -> Any:
            if fallback_lineage is not None:
                return getattr(fallback_lineage, name)
            return value(name)

        def optional_lineage_text(name: str) -> str | None:
            candidate = lineage_value(name)
            return candidate[:120] if isinstance(candidate, str) and candidate else None

        plan_version_id = optional_lineage_text("plan_version_id")
        attempt_id = optional_lineage_text("attempt_id")
        step_number = lineage_value("step_number")
        if isinstance(step_number, bool) or not isinstance(step_number, int) or step_number < 1:
            step_number = None
        if plan_version_id is None or (attempt_id is None) != (step_number is None):
            attempt_id = None
            step_number = None
        created_at_value = value("created_at", effective_now)
        try:
            created_at = (
                created_at_value
                if isinstance(created_at_value, datetime)
                else datetime.fromisoformat(str(created_at_value))
            )
        except ValueError:
            created_at = effective_now
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            created_at = created_at.replace(tzinfo=UTC)
        try:
            failed = Artifact(
                id=row["id"],
                run_id=routed_text("run_id", "invalid_run"),
                workspace_id=routed_text("workspace_id", "unknown_workspace"),
                project_id=routed_text("project_id", "unknown_project"),
                user_id=routed_text("user_id", "unknown_user"),
                artifact_type=required_text("artifact_type", "invalid_artifact"),
                content_type=required_text("content_type", "text/plain"),
                content="",
                truncated=bool(value("truncated", False)),
                verification_state=ArtifactVerificationState.FAILED,
                schema_version=optional_text("schema_version") or "invalid-artifact-v1",
                content_hash=content_hash,
                size_bytes=size_bytes,
                requirement_version_id=optional_lineage_text("requirement_version_id") or "invalid_requirement",
                plan_version_id=plan_version_id,
                attempt_id=attempt_id,
                step_number=step_number,
                created_at=created_at,
                updated_at=effective_now,
            )
        except (TypeError, ValueError):
            raise ArtifactStoreError("artifact_context_invalid") from None
        cursor = connection.execute(
            """
            UPDATE artifacts SET
                run_id = ?, payload = ?, created_at = ?, workspace_id = ?, project_id = ?,
                user_id = ?, artifact_type = ?, content_type = ?, truncated = ?,
                verification_state = ?, schema_version = ?, content_hash = ?, size_bytes = ?,
                requirement_version_id = ?, plan_version_id = ?, attempt_id = ?, step_number = ?,
                purged_at = NULL, purged_by = NULL, updated_at = ?
            WHERE id = ? AND verification_state IS ?
            """,
            (
                failed.run_id,
                failed.model_dump_json(),
                failed.created_at.isoformat(),
                failed.workspace_id,
                failed.project_id,
                failed.user_id,
                failed.artifact_type,
                failed.content_type,
                int(failed.truncated),
                ArtifactVerificationState.FAILED.value,
                failed.schema_version,
                failed.content_hash,
                failed.size_bytes,
                failed.requirement_version_id,
                failed.plan_version_id,
                failed.attempt_id,
                failed.step_number,
                effective_now.isoformat(),
                row["id"],
                row["verification_state"],
            ),
        )
        if cursor.rowcount != 1:
            raise ArtifactStoreError("artifact_conflict")
        self.repository._append_agent_run_events(
            connection,
            failed.run_id,
            [("artifact_invalidated", {"artifact_id": row["id"], "reason": reason})],
        )
        return True

    def _append_event(self, connection: sqlite3.Connection, artifact: Artifact, event_type: str) -> None:
        self.repository._append_agent_run_events(
            connection,
            artifact.run_id,
            [
                (
                    event_type,
                    {
                        "artifact_id": artifact.id,
                        "kind": artifact.artifact_type,
                        "verification_state": artifact.verification_state.value,
                    },
                )
            ],
        )
