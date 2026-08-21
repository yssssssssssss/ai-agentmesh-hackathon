"""SQLite persistence for research-v3.

Gate 2 installs the additive ``research_v3_*`` namespace through ``SQLiteStore`` and
uses this repository for owner-scoped preview planning. Provider-backed execution
adapters remain uncomposed. Domain records are append-only; mutable coordination is
kept in attempt/invocation tables and is always CAS/fence checked.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Annotated, Literal, TypeVar

from pydantic import BaseModel, Field, TypeAdapter, ValidationError, model_validator

from agentmesh.research_orchestration.v3.canonical import (
    canonical_json_v3_bytes,
    canonical_json_v3_sha256,
    strict_json_v3_loads,
)
from agentmesh.research_orchestration.v3.common import (
    EvidenceManifestArtifactRefV3,
    FrozenJsonObject,
    Identifier,
    ProblemGraphArtifactRefV3,
    SealedArtifactRefV3,
    Sha256Hex,
    StrictFrozenModel,
)
from agentmesh.research_orchestration.v3.deliverable import ResearchDeliverableV3
from agentmesh.research_orchestration.v3.evidence import EvidenceManifestV3, VerifiedArtifactContentV3
from agentmesh.research_orchestration.v3.execution_plan import ExecutionPlanVersionV3, PlanCandidateSetV3
from agentmesh.research_orchestration.v3.ports import ActorExecutionResultV3
from agentmesh.research_orchestration.v3.problem_graph import ProblemGraphV1
from agentmesh.research_orchestration.v3.report_document import ReportDocumentV3
from agentmesh.research_orchestration.v3.requirement import RequirementVersionV3
from agentmesh.research_orchestration.v3.review import ReportReviewV3
from agentmesh.research_orchestration.v3.snapshots import ResearchControlSnapshotV3
from agentmesh.research_orchestration.v3.web_projection import WorkbenchApprovalV1

_ModelT = TypeVar("_ModelT", bound=BaseModel)
_IDENTIFIER_ADAPTER = TypeAdapter(Identifier)
_RECORD_CODECS: dict[str, tuple[str, type[BaseModel]]] = {
    "requirement": ("research-task-v3", RequirementVersionV3),
    "candidate_set": ("plan-candidates-v3", PlanCandidateSetV3),
    "problem_graph": ("problem-graph-v1", ProblemGraphV1),
    "plan": ("execution-plan-v3", ExecutionPlanVersionV3),
    "control_snapshot": ("research-control-snapshot-v3", ResearchControlSnapshotV3),
    "actor_result": ("actor-execution-result-v3", ActorExecutionResultV3),
    "evidence_manifest": ("evidence-manifest-v3", EvidenceManifestV3),
    "deliverable": ("research-deliverable-v3", ResearchDeliverableV3),
    "review": ("report-review-v3", ReportReviewV3),
    "report": ("report-document-v3", ReportDocumentV3),
    "approval": ("workbench-approval-v1", WorkbenchApprovalV1),
}


class ResearchV3PersistenceError(RuntimeError):
    """Base error for the isolated research-v3 SQLite adapter."""


class ResearchV3NotFoundError(ResearchV3PersistenceError):
    pass


class ResearchV3ConflictError(ResearchV3PersistenceError):
    pass


class ResearchV3IntegrityError(ResearchV3PersistenceError):
    pass


class _CommitResearchV3Conflict(ResearchV3ConflictError):
    """Conflict raised after a required coordination transition must be committed."""


_DEADLINE_ERROR_CODE = "attempt_deadline_exceeded"


def _require_aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _require_aware(value, "timestamp").isoformat()


def _parse_time(value: str | None, label: str) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return _require_aware(parsed, label)
    except ValueError:
        raise ResearchV3IntegrityError(f"stored {label} timestamp is invalid") from None


def _artifact_id(*, run_id: str, kind: str, content_hash: str) -> str:
    identity_hash = canonical_json_v3_sha256(
        {"run_id": run_id, "kind": kind, "content_hash": content_hash}
    )
    return f"artifact_{kind}_{identity_hash[:24]}"


def _sealed_ref(
    *, run_id: str, kind: str, schema_version: str, value: BaseModel
) -> SealedArtifactRefV3:
    content_hash = canonical_json_v3_sha256(value)
    return SealedArtifactRefV3(
        artifact_id=_artifact_id(run_id=run_id, kind=kind, content_hash=content_hash),
        kind=kind,
        schema_version=schema_version,
        content_hash=content_hash,
    )


def _artifact_refs_equal(
    left: SealedArtifactRefV3, right: SealedArtifactRefV3
) -> bool:
    return (
        left.artifact_id,
        left.kind,
        left.schema_version,
        left.content_hash,
    ) == (
        right.artifact_id,
        right.kind,
        right.schema_version,
        right.content_hash,
    )


def _encode_model(value: BaseModel) -> tuple[bytes, str]:
    payload = canonical_json_v3_bytes(value)
    return payload, hashlib.sha256(payload).hexdigest()


def _decode_model[DecodedModelT: BaseModel](
    *,
    payload: bytes | str,
    payload_hash: str,
    model_type: type[DecodedModelT],
    label: str,
) -> DecodedModelT:
    raw = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    if hashlib.sha256(raw).hexdigest() != payload_hash:
        raise ResearchV3IntegrityError(f"stored {label} payload hash does not match")
    try:
        decoded = strict_json_v3_loads(raw)
        if canonical_json_v3_bytes(decoded) != raw:
            raise ResearchV3IntegrityError(f"stored {label} payload is not canonical JSON")
        value = model_type.model_validate(decoded)
        if canonical_json_v3_bytes(value) != raw:
            raise ResearchV3IntegrityError(f"stored {label} payload changed during typed decoding")
    except ResearchV3IntegrityError:
        raise
    except (RecursionError, TypeError, UnicodeError, ValueError, ValidationError):
        raise ResearchV3IntegrityError(f"stored {label} payload failed exact typed decoding") from None
    return value


class RepositoryScopeV3(StrictFrozenModel):
    owner_id: Identifier
    workspace_id: Identifier
    project_id: Identifier


PreviewStatusV3 = Literal["active", "confirmed", "cancelled"]


class RepositoryRunV3(StrictFrozenModel):
    run_id: Identifier
    orchestration_version: Literal["research-v3"]
    scope: RepositoryScopeV3
    state_version: Annotated[int, Field(ge=0)]
    preview_status: PreviewStatusV3 = "active"
    created_at: datetime
    tombstoned_at: datetime | None = None

    @model_validator(mode="after")
    def validate_timestamps(self) -> RepositoryRunV3:
        _require_aware(self.created_at, "run created_at")
        if self.tombstoned_at is not None:
            _require_aware(self.tombstoned_at, "run tombstoned_at")
        return self


AttemptStatusV3 = Literal["pending", "running", "paused", "completed", "aborted"]


class AttemptLeaseV3(StrictFrozenModel):
    attempt_id: Identifier
    owner: Identifier
    token: Identifier
    fencing_epoch: Annotated[int, Field(ge=1)]
    expires_at: datetime

    @model_validator(mode="after")
    def validate_expiry(self) -> AttemptLeaseV3:
        _require_aware(self.expires_at, "lease expires_at")
        return self


class ExecutionAttemptV3(StrictFrozenModel):
    attempt_id: Identifier
    run_id: Identifier
    plan_version_id: Identifier
    attempt_number: Annotated[int, Field(ge=1)]
    status: AttemptStatusV3
    lease_owner: Identifier | None = None
    lease_token: Identifier | None = None
    fencing_epoch: Annotated[int, Field(ge=0)] = 0
    lease_expires_at: datetime | None = None
    deadline_at: datetime
    failed_step_number: Annotated[int, Field(ge=1, le=8)] | None = None
    failure_code: Identifier | None = None
    pause_reason: Literal["failed", "unknown"] | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_state(self) -> ExecutionAttemptV3:
        _require_aware(self.deadline_at, "attempt deadline_at")
        _require_aware(self.created_at, "attempt created_at")
        _require_aware(self.updated_at, "attempt updated_at")
        lease_parts = (self.lease_owner, self.lease_token, self.lease_expires_at)
        if any(item is not None for item in lease_parts) != all(item is not None for item in lease_parts):
            raise ValueError("attempt lease owner, token, and expiry must be set together")
        has_lease = all(item is not None for item in lease_parts)
        if (self.status == "running") != has_lease:
            raise ValueError("exactly running attempts carry a lease")
        if self.status == "paused":
            if self.failed_step_number is None or self.failure_code is None or self.pause_reason is None:
                raise ValueError("paused attempts require failed Step, code, and reason")
        elif any(item is not None for item in (self.failed_step_number, self.failure_code, self.pause_reason)):
            raise ValueError("only paused attempts carry failure metadata")
        if self.deadline_at <= self.created_at:
            raise ValueError("attempt deadline must be after creation")
        return self


InvocationStateV3 = Literal["prepared", "sent", "acknowledged", "unknown", "cancelled"]


class ActorInvocationV3(StrictFrozenModel):
    invocation_id: Identifier
    run_id: Identifier
    plan_version_id: Identifier
    attempt_id: Identifier
    step_number: Annotated[int, Field(ge=1, le=8)]
    state: InvocationStateV3
    send_count: Annotated[int, Field(ge=0, le=1)]
    sent_fencing_epoch: Annotated[int, Field(ge=1)] | None = None
    sent_at: datetime | None = None
    unknown_at: datetime | None = None
    receipt_id: Identifier | None = None
    result_artifact: SealedArtifactRefV3 | None = None
    error_code: Identifier | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_state(self) -> ActorInvocationV3:
        _require_aware(self.created_at, "invocation created_at")
        _require_aware(self.updated_at, "invocation updated_at")
        for label, value in (("sent_at", self.sent_at), ("unknown_at", self.unknown_at)):
            if value is not None:
                _require_aware(value, f"invocation {label}")
        sent = self.send_count == 1 and self.sent_fencing_epoch is not None and self.sent_at is not None
        if self.state == "prepared":
            if self.send_count or any(
                item is not None
                for item in (
                    self.sent_fencing_epoch,
                    self.sent_at,
                    self.unknown_at,
                    self.receipt_id,
                    self.result_artifact,
                    self.error_code,
                )
            ):
                raise ValueError("prepared invocation cannot contain send or result metadata")
        elif self.state == "cancelled":
            if self.send_count or any(
                item is not None
                for item in (
                    self.sent_fencing_epoch,
                    self.sent_at,
                    self.unknown_at,
                    self.receipt_id,
                    self.result_artifact,
                )
            ) or self.error_code is None:
                raise ValueError("cancelled invocation requires an unsent cancellation reason")
        elif not sent:
            raise ValueError("post-send invocation states require exactly one persisted send")
        if self.state == "sent" and any(
            item is not None for item in (self.unknown_at, self.receipt_id, self.result_artifact, self.error_code)
        ):
            raise ValueError("sent invocation cannot contain settlement metadata")
        if self.state == "unknown" and (
            self.unknown_at is None
            or self.receipt_id is not None
            or self.result_artifact is not None
            or self.error_code is None
        ):
            raise ValueError("UNKNOWN invocation requires accounting metadata and no accepted result")
        if self.state == "acknowledged" and (
            self.receipt_id is None or self.result_artifact is None or self.unknown_at is not None
        ):
            raise ValueError("acknowledged invocation requires an exact receipt and Artifact")
        return self


class ResearchCommandReceiptV3(StrictFrozenModel):
    schema_version: Literal["research-command-receipt-v3"] = "research-command-receipt-v3"
    run_id: Identifier
    idempotency_key: Identifier
    command_type: Identifier
    request_hash: Sha256Hex
    response_payload: FrozenJsonObject
    committed_state_version: Annotated[int, Field(ge=0)]
    created_at: datetime

    @model_validator(mode="after")
    def validate_created_at(self) -> ResearchCommandReceiptV3:
        _require_aware(self.created_at, "command receipt created_at")
        return self


class RepositoryRecordPayloadV3(StrictFrozenModel):
    """Typed envelope that integrity-binds every generic record projection column."""

    envelope_schema_version: Literal["research-v3-record-envelope-v1"] = (
        "research-v3-record-envelope-v1"
    )
    run_id: Identifier
    record_kind: Identifier
    natural_key: Identifier
    record_schema_version: Identifier
    sequence_number: Annotated[int, Field(ge=1)] | None = None
    requirement_version_id: Identifier | None = None
    plan_version_id: Identifier | None = None
    attempt_id: Identifier | None = None
    step_number: Annotated[int, Field(ge=1, le=8)] | None = None
    artifact: SealedArtifactRefV3 | None = None
    value_json: str


@dataclass(frozen=True, slots=True)
class RepositoryProjectionSnapshotV3:
    run: RepositoryRunV3
    requirement: RequirementVersionV3 | None
    candidates: PlanCandidateSetV3 | None
    selected_plan: ExecutionPlanVersionV3 | None
    approvals: tuple[WorkbenchApprovalV1, ...]
    attempt: ExecutionAttemptV3 | None
    actor_results: tuple[ActorExecutionResultV3, ...]
    evidence: tuple[EvidenceManifestArtifactRefV3, EvidenceManifestV3] | None
    deliverable: tuple[SealedArtifactRefV3, ResearchDeliverableV3] | None
    review: tuple[SealedArtifactRefV3, ReportReviewV3] | None
    report: tuple[SealedArtifactRefV3, ReportDocumentV3] | None
    verified_artifacts: tuple[VerifiedArtifactContentV3, ...]


@dataclass(frozen=True, slots=True)
class PreviewRecordAppendV3:
    """One typed planning record staged for an atomic preview command."""

    record_kind: Literal[
        "requirement",
        "candidate_set",
        "problem_graph",
        "plan",
        "control_snapshot",
    ]
    natural_key: Identifier
    schema_version: Identifier
    value: BaseModel
    sequence_number: int | None = None
    requirement_version_id: Identifier | None = None
    plan_version_id: Identifier | None = None
    artifact: SealedArtifactRefV3 | None = None


class SQLiteResearchV3Repository:
    """Explicitly initialized, owner-scoped implementation of both v3 persistence ports."""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS research_v3_runs (
        run_id TEXT PRIMARY KEY,
        owner_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        orchestration_version TEXT NOT NULL,
        state_version INTEGER NOT NULL CHECK(state_version >= 0),
        preview_status TEXT NOT NULL DEFAULT 'active'
            CHECK(preview_status IN ('active', 'confirmed', 'cancelled')),
        created_at TEXT NOT NULL,
        tombstoned_at TEXT
    );
    CREATE TABLE IF NOT EXISTS research_v3_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL REFERENCES research_v3_runs(run_id) ON DELETE CASCADE,
        record_kind TEXT NOT NULL,
        natural_key TEXT NOT NULL,
        schema_version TEXT NOT NULL,
        sequence_number INTEGER,
        requirement_version_id TEXT,
        plan_version_id TEXT,
        attempt_id TEXT,
        step_number INTEGER,
        artifact_id TEXT,
        artifact_kind TEXT,
        artifact_schema_version TEXT,
        artifact_content_hash TEXT,
        payload BLOB NOT NULL,
        payload_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(run_id, record_kind, natural_key)
    );
    CREATE INDEX IF NOT EXISTS research_v3_records_lookup
        ON research_v3_records(run_id, record_kind, sequence_number, id);
    CREATE UNIQUE INDEX IF NOT EXISTS research_v3_records_artifact
        ON research_v3_records(run_id, artifact_id) WHERE artifact_id IS NOT NULL;
    CREATE TABLE IF NOT EXISTS research_v3_verified_artifacts (
        artifact_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES research_v3_runs(run_id) ON DELETE CASCADE,
        plan_version_id TEXT NOT NULL,
        attempt_id TEXT NOT NULL,
        step_number INTEGER NOT NULL CHECK(step_number BETWEEN 1 AND 8),
        artifact_kind TEXT NOT NULL,
        artifact_schema_version TEXT NOT NULL,
        artifact_content_hash TEXT NOT NULL,
        payload BLOB NOT NULL,
        payload_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS research_v3_verified_artifacts_lineage
        ON research_v3_verified_artifacts(run_id, plan_version_id, attempt_id, step_number);
    CREATE TABLE IF NOT EXISTS research_v3_attempts (
        attempt_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES research_v3_runs(run_id) ON DELETE CASCADE,
        plan_version_id TEXT NOT NULL,
        attempt_number INTEGER NOT NULL,
        status TEXT NOT NULL,
        lease_owner TEXT,
        lease_token TEXT,
        fencing_epoch INTEGER NOT NULL,
        lease_expires_at TEXT,
        deadline_at TEXT NOT NULL,
        failed_step_number INTEGER,
        failure_code TEXT,
        pause_reason TEXT,
        payload BLOB NOT NULL,
        payload_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(run_id, attempt_number)
    );
    CREATE UNIQUE INDEX IF NOT EXISTS research_v3_attempts_one_active
        ON research_v3_attempts(run_id) WHERE status IN ('pending', 'running', 'paused');
    CREATE INDEX IF NOT EXISTS research_v3_attempts_recovery
        ON research_v3_attempts(status, lease_expires_at, deadline_at);
    CREATE TABLE IF NOT EXISTS research_v3_invocations (
        invocation_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES research_v3_runs(run_id) ON DELETE CASCADE,
        plan_version_id TEXT NOT NULL,
        attempt_id TEXT NOT NULL REFERENCES research_v3_attempts(attempt_id) ON DELETE CASCADE,
        step_number INTEGER NOT NULL CHECK(step_number BETWEEN 1 AND 8),
        state TEXT NOT NULL,
        send_count INTEGER NOT NULL CHECK(send_count BETWEEN 0 AND 1),
        sent_fencing_epoch INTEGER,
        sent_at TEXT,
        unknown_at TEXT,
        receipt_id TEXT,
        result_artifact_id TEXT,
        error_code TEXT,
        payload BLOB NOT NULL,
        payload_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(attempt_id, step_number)
    );
    CREATE INDEX IF NOT EXISTS research_v3_invocations_state
        ON research_v3_invocations(run_id, state);
    CREATE TABLE IF NOT EXISTS research_v3_command_receipts (
        run_id TEXT NOT NULL REFERENCES research_v3_runs(run_id) ON DELETE CASCADE,
        idempotency_key TEXT NOT NULL,
        command_type TEXT NOT NULL,
        request_hash TEXT NOT NULL,
        committed_state_version INTEGER NOT NULL,
        payload BLOB NOT NULL,
        payload_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY(run_id, idempotency_key)
    );
    """

    def __init__(
        self,
        database: str | Path | sqlite3.Connection,
        *,
        owner_id: Identifier,
        workspace_id: Identifier,
        project_id: Identifier,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.scope = RepositoryScopeV3(
            owner_id=owner_id, workspace_id=workspace_id, project_id=project_id
        )
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = RLock()
        if isinstance(database, sqlite3.Connection):
            self._connection = database
            self._owns_connection = False
        else:
            self._connection = sqlite3.connect(str(database), check_same_thread=False)
            self._owns_connection = True
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        if self._owns_connection:
            self._connection.close()

    @classmethod
    def initialize_schema_in_connection(cls, connection: sqlite3.Connection) -> None:
        """Install the additive v3 namespace on a caller-owned, non-active connection."""

        for raw_statement in cls._SCHEMA.split(";"):
            statement = raw_statement.strip()
            if statement:
                connection.execute(statement)
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(research_v3_runs)")
        }
        if "preview_status" not in columns:
            connection.execute(
                """ALTER TABLE research_v3_runs
                ADD COLUMN preview_status TEXT NOT NULL DEFAULT 'active'
                CHECK(preview_status IN ('active', 'confirmed', 'cancelled'))"""
            )
        connection.execute(
            """UPDATE research_v3_runs AS runs
            SET preview_status = (
                SELECT CASE receipts.command_type
                    WHEN 'confirm_plan' THEN 'confirmed'
                    WHEN 'cancel' THEN 'cancelled'
                END
                FROM research_v3_command_receipts AS receipts
                WHERE receipts.run_id = runs.run_id
                  AND receipts.command_type IN ('confirm_plan', 'cancel')
                ORDER BY receipts.committed_state_version DESC
                LIMIT 1
            )
            WHERE runs.preview_status = 'active'
              AND EXISTS (
                SELECT 1 FROM research_v3_command_receipts AS receipts
                WHERE receipts.run_id = runs.run_id
                  AND receipts.command_type IN ('confirm_plan', 'cancel')
              )"""
        )

    def initialize_schema(self) -> None:
        """Create the private v3 namespace; never called by production startup."""
        with self._lock:
            self.initialize_schema_in_connection(self._connection)
            self._connection.commit()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                yield self._connection
            except _CommitResearchV3Conflict:
                self._connection.commit()
                raise
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    @classmethod
    def initialize_run_in_transaction(
        cls,
        connection: sqlite3.Connection,
        *,
        run_id: Identifier,
        scope: RepositoryScopeV3,
        created_at: datetime,
    ) -> RepositoryRunV3:
        """Insert the v3 root row without owning the caller's transaction."""

        created = _require_aware(created_at, "run created_at")
        run = RepositoryRunV3(
            run_id=run_id,
            orchestration_version="research-v3",
            scope=scope,
            state_version=0,
            created_at=created,
        )
        try:
            connection.execute(
                """
                INSERT INTO research_v3_runs(
                    run_id, owner_id, workspace_id, project_id, orchestration_version,
                    state_version, preview_status, created_at, tombstoned_at
                ) VALUES (?, ?, ?, ?, ?, 0, 'active', ?, NULL)
                """,
                (
                    run.run_id,
                    run.scope.owner_id,
                    run.scope.workspace_id,
                    run.scope.project_id,
                    run.orchestration_version,
                    _iso(created),
                ),
            )
        except sqlite3.IntegrityError:
            raise ResearchV3ConflictError("research-v3 run identity already exists") from None
        return run

    def create_run(
        self,
        run_id: Identifier,
        *,
        orchestration_version: Literal["research-v3"] = "research-v3",
        created_at: datetime | None = None,
    ) -> RepositoryRunV3:
        if orchestration_version != "research-v3":
            raise ValueError("SQLiteResearchV3Repository creates only research-v3 runs")
        with self._write() as connection:
            return self.initialize_run_in_transaction(
                connection,
                run_id=run_id,
                scope=self.scope,
                created_at=created_at or self._clock(),
            )

    def get_run_record(
        self, run_id: Identifier, *, include_tombstone: bool = False
    ) -> RepositoryRunV3 | None:
        with self._lock:
            row = self._select_run(self._connection, run_id, include_tombstone=include_tombstone)
            return self._run_from_row(row) if row is not None else None

    def state_version(self, run_id: Identifier) -> int:
        run = self.get_run_record(run_id)
        if run is None:
            raise ResearchV3NotFoundError("research-v3 run is not visible in this scope")
        return run.state_version

    def _select_run(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        *,
        include_tombstone: bool = False,
    ) -> sqlite3.Row | None:
        tombstone = "" if include_tombstone else " AND tombstoned_at IS NULL"
        row = connection.execute(
            """
            SELECT * FROM research_v3_runs
            WHERE run_id = ? AND owner_id = ? AND workspace_id = ? AND project_id = ?
            """
            + tombstone,
            (run_id, self.scope.owner_id, self.scope.workspace_id, self.scope.project_id),
        ).fetchone()
        if row is not None and row["orchestration_version"] != "research-v3":
            raise ResearchV3IntegrityError("stored run version is not exactly research-v3")
        return row

    def _require_run(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        *,
        include_tombstone: bool = False,
    ) -> sqlite3.Row:
        row = self._select_run(connection, run_id, include_tombstone=include_tombstone)
        if row is None:
            raise ResearchV3NotFoundError("research-v3 run is not visible in this scope")
        return row

    def _run_from_row(self, row: sqlite3.Row) -> RepositoryRunV3:
        try:
            return RepositoryRunV3(
                run_id=row["run_id"],
                orchestration_version=row["orchestration_version"],
                scope=RepositoryScopeV3(
                    owner_id=row["owner_id"],
                    workspace_id=row["workspace_id"],
                    project_id=row["project_id"],
                ),
                state_version=row["state_version"],
                preview_status=row["preview_status"],
                created_at=_parse_time(row["created_at"], "run created_at"),
                tombstoned_at=_parse_time(row["tombstoned_at"], "run tombstoned_at"),
            )
        except (TypeError, ValueError, ValidationError):
            raise ResearchV3IntegrityError("stored research-v3 run metadata is invalid") from None

    @staticmethod
    def _advance_state(
        connection: sqlite3.Connection, run_id: str, expected_state_version: int
    ) -> None:
        cursor = connection.execute(
            """
            UPDATE research_v3_runs SET state_version = state_version + 1
            WHERE run_id = ? AND state_version = ? AND tombstoned_at IS NULL
            """,
            (run_id, expected_state_version),
        )
        if cursor.rowcount != 1:
            raise ResearchV3ConflictError("research-v3 state version conflict")

    @staticmethod
    def _check_state(row: sqlite3.Row, expected_state_version: int) -> None:
        if row["state_version"] != expected_state_version:
            raise ResearchV3ConflictError(
                f"research-v3 state version conflict: expected {expected_state_version}, "
                f"actual {row['state_version']}"
            )

    def _append_record(
        self,
        connection: sqlite3.Connection,
        *,
        run_id: str,
        record_kind: str,
        natural_key: str,
        schema_version: str,
        value: BaseModel,
        expected_state_version: int,
        sequence_number: int | None = None,
        requirement_version_id: str | None = None,
        plan_version_id: str | None = None,
        attempt_id: str | None = None,
        step_number: int | None = None,
        artifact: SealedArtifactRefV3 | None = None,
        advance_state: bool = True,
    ) -> None:
        row = self._require_run(connection, run_id)
        self._check_state(row, expected_state_version)
        codec = _RECORD_CODECS.get(record_kind)
        if codec is None or codec[0] != schema_version or not isinstance(value, codec[1]):
            raise ResearchV3IntegrityError(f"unsupported typed {record_kind} record append")
        self._validated_record_rows(
            connection,
            run_id=run_id,
            record_kind=record_kind,
            schema_version=schema_version,
            model_type=codec[1],
        )
        value_payload = canonical_json_v3_bytes(value)
        envelope = RepositoryRecordPayloadV3(
            run_id=run_id,
            record_kind=record_kind,
            natural_key=natural_key,
            record_schema_version=schema_version,
            sequence_number=sequence_number,
            requirement_version_id=requirement_version_id,
            plan_version_id=plan_version_id,
            attempt_id=attempt_id,
            step_number=step_number,
            artifact=artifact,
            value_json=value_payload.decode("utf-8"),
        )
        payload, payload_hash = _encode_model(envelope)
        try:
            connection.execute(
                """
                INSERT INTO research_v3_records(
                    run_id, record_kind, natural_key, schema_version, sequence_number,
                    requirement_version_id, plan_version_id, attempt_id, step_number,
                    artifact_id, artifact_kind, artifact_schema_version, artifact_content_hash,
                    payload, payload_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    record_kind,
                    natural_key,
                    schema_version,
                    sequence_number,
                    requirement_version_id,
                    plan_version_id,
                    attempt_id,
                    step_number,
                    artifact.artifact_id if artifact is not None else None,
                    artifact.kind if artifact is not None else None,
                    artifact.schema_version if artifact is not None else None,
                    artifact.content_hash if artifact is not None else None,
                    payload,
                    payload_hash,
                    _iso(self._clock()),
                ),
            )
        except sqlite3.IntegrityError:
            raise ResearchV3ConflictError(f"{record_kind} record was already appended") from None
        if advance_state:
            self._advance_state(connection, run_id, expected_state_version)

    def _read_record(
        self,
        connection: sqlite3.Connection,
        *,
        run_id: str,
        record_kind: str,
        natural_key: str,
        schema_version: str,
        model_type: type[_ModelT],
    ) -> _ModelT | None:
        if self._select_run(connection, run_id) is None:
            return None
        rows = self._validated_record_rows(
            connection,
            run_id=run_id,
            record_kind=record_kind,
            schema_version=schema_version,
            model_type=model_type,
        )
        matches = [value for row, value in rows if row["natural_key"] == natural_key]
        if len(matches) > 1:
            raise ResearchV3IntegrityError(f"stored {record_kind} natural key is not unique")
        return matches[0] if matches else None

    @classmethod
    def _validated_record_rows(
        cls,
        connection: sqlite3.Connection,
        *,
        run_id: str,
        record_kind: str,
        schema_version: str,
        model_type: type[_ModelT],
    ) -> tuple[tuple[sqlite3.Row, _ModelT], ...]:
        rows = connection.execute(
            "SELECT * FROM research_v3_records WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        decoded = tuple((row, cls._decode_any_record_row(row)) for row in rows)
        matches: list[tuple[sqlite3.Row, _ModelT]] = []
        for row, value in decoded:
            if row["record_kind"] != record_kind:
                continue
            if row["schema_version"] != schema_version or not isinstance(value, model_type):
                raise ResearchV3IntegrityError(
                    f"stored {record_kind} record has an unsupported typed codec"
                )
            matches.append((row, value))
        return tuple(matches)

    @classmethod
    def _decode_any_record_row(cls, row: sqlite3.Row) -> BaseModel:
        codec = _RECORD_CODECS.get(row["record_kind"])
        if codec is None:
            raise ResearchV3IntegrityError("stored generic record kind is unsupported")
        schema_version, model_type = codec
        return cls._decode_record_row(
            row,
            expected_kind=row["record_kind"],
            expected_schema=schema_version,
            model_type=model_type,
        )

    @staticmethod
    def _decode_record_row(
        row: sqlite3.Row,
        *,
        expected_kind: str,
        expected_schema: str,
        model_type: type[_ModelT],
    ) -> _ModelT:
        if row["record_kind"] != expected_kind or row["schema_version"] != expected_schema:
            raise ResearchV3IntegrityError(
                f"stored {expected_kind} record has an unsupported exact schema version"
            )
        envelope = _decode_model(
            payload=row["payload"],
            payload_hash=row["payload_hash"],
            model_type=RepositoryRecordPayloadV3,
            label=f"{expected_kind} record envelope",
        )
        artifact_columns = (
            row["artifact_id"],
            row["artifact_kind"],
            row["artifact_schema_version"],
            row["artifact_content_hash"],
        )
        expected_artifact_columns = (
            (
                envelope.artifact.artifact_id,
                envelope.artifact.kind,
                envelope.artifact.schema_version,
                envelope.artifact.content_hash,
            )
            if envelope.artifact is not None
            else (None, None, None, None)
        )
        projection = (
            row["run_id"],
            row["record_kind"],
            row["natural_key"],
            row["schema_version"],
            row["sequence_number"],
            row["requirement_version_id"],
            row["plan_version_id"],
            row["attempt_id"],
            row["step_number"],
            *artifact_columns,
        )
        expected_projection = (
            envelope.run_id,
            envelope.record_kind,
            envelope.natural_key,
            envelope.record_schema_version,
            envelope.sequence_number,
            envelope.requirement_version_id,
            envelope.plan_version_id,
            envelope.attempt_id,
            envelope.step_number,
            *expected_artifact_columns,
        )
        if projection != expected_projection or (
            envelope.record_kind != expected_kind
            or envelope.record_schema_version != expected_schema
        ):
            raise ResearchV3IntegrityError(
                f"stored {expected_kind} indexed columns do not match its typed payload"
            )
        value_raw = envelope.value_json.encode("utf-8")
        value = _decode_model(
            payload=value_raw,
            payload_hash=hashlib.sha256(value_raw).hexdigest(),
            model_type=model_type,
            label=expected_kind,
        )
        if hasattr(value, "schema_version") and value.schema_version != expected_schema:
            raise ResearchV3IntegrityError(f"stored {expected_kind} discriminator does not match its row")
        SQLiteResearchV3Repository._assert_record_value_binding(envelope, value)
        return value

    @staticmethod
    def _assert_record_value_binding(
        envelope: RepositoryRecordPayloadV3,
        value: BaseModel,
    ) -> None:
        artifact: SealedArtifactRefV3 | None = None
        match envelope.record_kind:
            case "requirement":
                natural_key = value.id
                sequence_number = value.version
                run_id = value.run_id
                requirement_version_id = value.id
                plan_version_id = attempt_id = step_number = None
            case "candidate_set":
                natural_key = envelope.requirement_version_id
                sequence_number = None
                run_id = envelope.run_id
                requirement_version_id = envelope.requirement_version_id
                plan_version_id = attempt_id = step_number = None
            case "problem_graph":
                run_id = envelope.run_id
                requirement_version_id = value.requirement_version_id
                sequence_number = plan_version_id = attempt_id = step_number = None
                artifact = _sealed_ref(
                    run_id=run_id,
                    kind="problem_graph",
                    schema_version="problem-graph-v1",
                    value=value,
                )
                natural_key = artifact.artifact_id
            case "plan":
                natural_key = value.id
                sequence_number = value.version
                run_id = value.run_id
                requirement_version_id = value.requirement_version_id
                plan_version_id = value.id
                attempt_id = step_number = None
            case "control_snapshot":
                run_id = envelope.run_id
                sequence_number = requirement_version_id = plan_version_id = None
                attempt_id = step_number = None
                artifact = _sealed_ref(
                    run_id=run_id,
                    kind="research_control_snapshot",
                    schema_version="research-control-snapshot-v3",
                    value=value,
                )
                natural_key = artifact.artifact_id
            case "actor_result":
                run_id = value.run_id
                natural_key = f"{value.attempt_id}:{value.step_number}"
                sequence_number = requirement_version_id = None
                plan_version_id = value.plan_version_id
                attempt_id = value.attempt_id
                step_number = value.step_number
                artifact = value.result_artifact
            case "evidence_manifest":
                run_id = value.run_id
                sequence_number = requirement_version_id = step_number = None
                plan_version_id = value.plan_version_id
                attempt_id = value.attempt_id
                artifact = _sealed_ref(
                    run_id=run_id,
                    kind="evidence_manifest",
                    schema_version="evidence-manifest-v3",
                    value=value,
                )
                natural_key = artifact.artifact_id
            case "deliverable" | "review" | "report":
                run_id = value.run_id
                sequence_number = requirement_version_id = step_number = None
                plan_version_id = value.plan_version_id
                attempt_id = value.attempt_id
                artifact_kind = {
                    "deliverable": "research_deliverable",
                    "review": "report_review",
                    "report": "report_document",
                }[envelope.record_kind]
                artifact = _sealed_ref(
                    run_id=run_id,
                    kind=artifact_kind,
                    schema_version=envelope.record_schema_version,
                    value=value,
                )
                natural_key = artifact.artifact_id
            case "approval":
                run_id = envelope.run_id
                natural_key = value.gate_key
                sequence_number = requirement_version_id = attempt_id = step_number = None
                plan_version_id = value.plan_version_id
            case _:
                raise ResearchV3IntegrityError("stored generic record kind is unsupported")
        expected = (
            run_id,
            natural_key,
            sequence_number,
            requirement_version_id,
            plan_version_id,
            attempt_id,
            step_number,
            artifact,
        )
        actual = (
            envelope.run_id,
            envelope.natural_key,
            envelope.sequence_number,
            envelope.requirement_version_id,
            envelope.plan_version_id,
            envelope.attempt_id,
            envelope.step_number,
            envelope.artifact,
        )
        if actual != expected:
            raise ResearchV3IntegrityError(
                f"stored {envelope.record_kind} columns do not match its typed value"
            )

    @staticmethod
    def _artifact_from_row(row: sqlite3.Row) -> SealedArtifactRefV3:
        try:
            return SealedArtifactRefV3(
                artifact_id=row["artifact_id"],
                kind=row["artifact_kind"],
                schema_version=row["artifact_schema_version"],
                content_hash=row["artifact_content_hash"],
            )
        except (TypeError, ValueError, ValidationError):
            raise ResearchV3IntegrityError("stored Artifact reference is invalid") from None

    def get_requirement(
        self, run_id: Identifier, version_id: Identifier
    ) -> RequirementVersionV3 | None:
        with self._lock:
            return self._read_record(
                self._connection,
                run_id=run_id,
                record_kind="requirement",
                natural_key=version_id,
                schema_version="research-task-v3",
                model_type=RequirementVersionV3,
            )

    def append_requirement(
        self, requirement: RequirementVersionV3, *, expected_state_version: int
    ) -> None:
        with self._write() as connection:
            existing_version = connection.execute(
                """SELECT 1 FROM research_v3_records
                WHERE run_id = ? AND record_kind = 'requirement' AND sequence_number = ?""",
                (requirement.run_id, requirement.version),
            ).fetchone()
            if existing_version is not None:
                raise ResearchV3ConflictError("Requirement version was already appended")
            self._append_record(
                connection,
                run_id=requirement.run_id,
                record_kind="requirement",
                natural_key=requirement.id,
                schema_version="research-task-v3",
                value=requirement,
                expected_state_version=expected_state_version,
                sequence_number=requirement.version,
                requirement_version_id=requirement.id,
            )

    def get_candidate_set(
        self, run_id: Identifier, requirement_version_id: Identifier
    ) -> PlanCandidateSetV3 | None:
        with self._lock:
            return self._read_record(
                self._connection,
                run_id=run_id,
                record_kind="candidate_set",
                natural_key=requirement_version_id,
                schema_version="plan-candidates-v3",
                model_type=PlanCandidateSetV3,
            )

    def append_candidate_set(
        self,
        run_id: Identifier,
        requirement_version_id: Identifier,
        candidate_set: PlanCandidateSetV3,
        *,
        expected_state_version: int,
    ) -> None:
        with self._write() as connection:
            requirement = self._read_record(
                connection,
                run_id=run_id,
                record_kind="requirement",
                natural_key=requirement_version_id,
                schema_version="research-task-v3",
                model_type=RequirementVersionV3,
            )
            if requirement is None:
                raise ResearchV3ConflictError("candidate set Requirement is not persisted")
            self._append_record(
                connection,
                run_id=run_id,
                record_kind="candidate_set",
                natural_key=requirement_version_id,
                schema_version="plan-candidates-v3",
                value=candidate_set,
                expected_state_version=expected_state_version,
                requirement_version_id=requirement_version_id,
            )

    def get_problem_graph(self, artifact: ProblemGraphArtifactRefV3) -> ProblemGraphV1 | None:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT records.* FROM research_v3_records AS records
                JOIN research_v3_runs AS runs ON runs.run_id = records.run_id
                WHERE runs.owner_id = ? AND runs.workspace_id = ? AND runs.project_id = ?
                  AND runs.tombstoned_at IS NULL
                """,
                (
                    self.scope.owner_id,
                    self.scope.workspace_id,
                    self.scope.project_id,
                ),
            ).fetchall()
            matches: list[tuple[sqlite3.Row, ProblemGraphV1]] = []
            for row in rows:
                value = self._decode_any_record_row(row)
                if (
                    row["record_kind"] == "problem_graph"
                    and row["artifact_id"] == artifact.artifact_id
                ):
                    if not isinstance(value, ProblemGraphV1):
                        raise ResearchV3IntegrityError("ProblemGraph record has an invalid typed codec")
                    matches.append((row, value))
            if not matches:
                return None
            if len(matches) != 1:
                raise ResearchV3IntegrityError("ProblemGraph Artifact identity is not unique")
            row, value = matches[0]
            if not _artifact_refs_equal(self._artifact_from_row(row), artifact):
                return None
            if canonical_json_v3_sha256(value) != artifact.content_hash:
                raise ResearchV3IntegrityError("ProblemGraph Artifact content hash does not match")
            return value

    def get_problem_graph_for_requirement(
        self,
        run_id: Identifier,
        requirement_version_id: Identifier,
    ) -> tuple[ProblemGraphArtifactRefV3, ProblemGraphV1] | None:
        with self._lock:
            if self._select_run(self._connection, run_id) is None:
                return None
            rows = self._validated_record_rows(
                self._connection,
                run_id=run_id,
                record_kind="problem_graph",
                schema_version="problem-graph-v1",
                model_type=ProblemGraphV1,
            )
            matches = tuple(
                (row, graph)
                for row, graph in rows
                if graph.requirement_version_id == requirement_version_id
            )
            if not matches:
                return None
            if len(matches) != 1:
                raise ResearchV3IntegrityError(
                    "Requirement has more than one persisted ProblemGraph"
                )
            row, graph = matches[0]
            artifact = ProblemGraphArtifactRefV3.model_validate(
                self._artifact_from_row(row).model_dump(mode="python")
            )
            if artifact.content_hash != canonical_json_v3_sha256(graph):
                raise ResearchV3IntegrityError("ProblemGraph Artifact content hash does not match")
            return artifact, graph

    def seal_problem_graph(
        self,
        run_id: Identifier,
        graph: ProblemGraphV1,
        *,
        expected_state_version: int,
    ) -> ProblemGraphArtifactRefV3:
        content_hash = canonical_json_v3_sha256(graph)
        artifact = ProblemGraphArtifactRefV3(
            artifact_id=_artifact_id(run_id=run_id, kind="problem_graph", content_hash=content_hash),
            kind="problem_graph",
            schema_version="problem-graph-v1",
            content_hash=content_hash,
        )
        with self._write() as connection:
            requirement = self._read_record(
                connection,
                run_id=run_id,
                record_kind="requirement",
                natural_key=graph.requirement_version_id,
                schema_version="research-task-v3",
                model_type=RequirementVersionV3,
            )
            if requirement is None:
                raise ResearchV3ConflictError("ProblemGraph Requirement is not persisted")
            self._append_record(
                connection,
                run_id=run_id,
                record_kind="problem_graph",
                natural_key=artifact.artifact_id,
                schema_version="problem-graph-v1",
                value=graph,
                expected_state_version=expected_state_version,
                requirement_version_id=graph.requirement_version_id,
                artifact=artifact,
            )
        return artifact

    def get_plan(
        self, run_id: Identifier, version_id: Identifier
    ) -> ExecutionPlanVersionV3 | None:
        with self._lock:
            return self._read_record(
                self._connection,
                run_id=run_id,
                record_kind="plan",
                natural_key=version_id,
                schema_version="execution-plan-v3",
                model_type=ExecutionPlanVersionV3,
            )

    def append_plan(
        self, plan: ExecutionPlanVersionV3, *, expected_state_version: int
    ) -> None:
        with self._write() as connection:
            requirement = self._read_record(
                connection,
                run_id=plan.run_id,
                record_kind="requirement",
                natural_key=plan.requirement_version_id,
                schema_version="research-task-v3",
                model_type=RequirementVersionV3,
            )
            if requirement is None or plan.payload.requirement_content_hash != requirement.content_hash:
                raise ResearchV3ConflictError("Plan Requirement lineage is not persisted exactly")
            graph_rows = self._validated_record_rows(
                connection,
                run_id=plan.run_id,
                record_kind="problem_graph",
                schema_version="problem-graph-v1",
                model_type=ProblemGraphV1,
            )
            graph_row = next(
                (
                    row
                    for row, _value in graph_rows
                    if row["artifact_id"] == plan.payload.problem_graph_artifact.artifact_id
                ),
                None,
            )
            snapshot_rows = self._validated_record_rows(
                connection,
                run_id=plan.run_id,
                record_kind="control_snapshot",
                schema_version="research-control-snapshot-v3",
                model_type=ResearchControlSnapshotV3,
            )
            snapshot_row = next(
                (
                    row
                    for row, _value in snapshot_rows
                    if row["artifact_id"] == plan.payload.control_snapshot_artifact.artifact_id
                ),
                None,
            )
            if graph_row is None or not _artifact_refs_equal(
                self._artifact_from_row(graph_row), plan.payload.problem_graph_artifact
            ):
                raise ResearchV3ConflictError("Plan ProblemGraph Artifact is not persisted exactly")
            if snapshot_row is None or not _artifact_refs_equal(
                self._artifact_from_row(snapshot_row), plan.payload.control_snapshot_artifact
            ):
                raise ResearchV3ConflictError("Plan control snapshot Artifact is not persisted exactly")
            existing_version = connection.execute(
                """SELECT 1 FROM research_v3_records
                WHERE run_id = ? AND record_kind = 'plan' AND sequence_number = ?""",
                (plan.run_id, plan.version),
            ).fetchone()
            if existing_version is not None:
                raise ResearchV3ConflictError("Execution Plan version was already appended")
            self._append_record(
                connection,
                run_id=plan.run_id,
                record_kind="plan",
                natural_key=plan.id,
                schema_version="execution-plan-v3",
                value=plan,
                expected_state_version=expected_state_version,
                sequence_number=plan.version,
                requirement_version_id=plan.requirement_version_id,
                plan_version_id=plan.id,
            )

    def get_control_snapshot(
        self, artifact: SealedArtifactRefV3
    ) -> ResearchControlSnapshotV3 | None:
        return self._get_sealed_record(
            artifact,
            record_kind="control_snapshot",
            schema_version="research-control-snapshot-v3",
            model_type=ResearchControlSnapshotV3,
        )

    def read_control_snapshot(
        self, artifact: SealedArtifactRefV3
    ) -> ResearchControlSnapshotV3 | None:
        return self.get_control_snapshot(artifact)

    def append_control_snapshot(
        self,
        run_id: Identifier,
        snapshot: ResearchControlSnapshotV3,
        *,
        expected_state_version: int,
    ) -> SealedArtifactRefV3:
        # Planning descriptors permit 240 chars, while persisted execution/evidence
        # envelopes use Identifier (120). Fail before persistence rather than freeze an
        # implementation identity that no result can represent.
        for actor in snapshot.actors:
            try:
                _IDENTIFIER_ADAPTER.validate_python(actor.implementation_id)
            except (TypeError, ValueError, ValidationError):
                raise ValueError(
                    "persisted Actor implementation_id must satisfy the v3 Identifier contract"
                ) from None
        artifact = _sealed_ref(
            run_id=run_id,
            kind="research_control_snapshot",
            schema_version="research-control-snapshot-v3",
            value=snapshot,
        )
        with self._write() as connection:
            self._append_record(
                connection,
                run_id=run_id,
                record_kind="control_snapshot",
                natural_key=artifact.artifact_id,
                schema_version="research-control-snapshot-v3",
                value=snapshot,
                expected_state_version=expected_state_version,
                artifact=artifact,
            )
        return artifact

    def _get_sealed_record(
        self,
        artifact: SealedArtifactRefV3,
        *,
        record_kind: str,
        schema_version: str,
        model_type: type[_ModelT],
    ) -> _ModelT | None:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT records.* FROM research_v3_records AS records
                JOIN research_v3_runs AS runs ON runs.run_id = records.run_id
                WHERE runs.owner_id = ? AND runs.workspace_id = ? AND runs.project_id = ?
                  AND runs.tombstoned_at IS NULL
                """,
                (
                    self.scope.owner_id,
                    self.scope.workspace_id,
                    self.scope.project_id,
                ),
            ).fetchall()
            matches: list[tuple[sqlite3.Row, _ModelT]] = []
            for row in rows:
                value = self._decode_any_record_row(row)
                if row["record_kind"] == record_kind and row["artifact_id"] == artifact.artifact_id:
                    if not isinstance(value, model_type):
                        raise ResearchV3IntegrityError(
                            f"{record_kind} record has an invalid typed codec"
                        )
                    matches.append((row, value))
            if not matches:
                return None
            if len(matches) != 1:
                raise ResearchV3IntegrityError(f"{record_kind} Artifact identity is not unique")
            row, value = matches[0]
            if not _artifact_refs_equal(self._artifact_from_row(row), artifact):
                return None
            if canonical_json_v3_sha256(value) != artifact.content_hash:
                raise ResearchV3IntegrityError(f"{record_kind} Artifact content hash does not match")
            return value

    def get_actor_results(
        self,
        run_id: Identifier,
        plan_version_id: Identifier,
        attempt_id: Identifier,
    ) -> tuple[ActorExecutionResultV3, ...]:
        with self._lock:
            if self._select_run(self._connection, run_id) is None:
                return ()
            rows = self._validated_record_rows(
                self._connection,
                run_id=run_id,
                record_kind="actor_result",
                schema_version="actor-execution-result-v3",
                model_type=ActorExecutionResultV3,
            )
            values = [
                value
                for _row, value in rows
                if value.plan_version_id == plan_version_id and value.attempt_id == attempt_id
            ]
            return tuple(sorted(values, key=lambda value: value.step_number))

    def append_actor_result(
        self,
        result: ActorExecutionResultV3,
        *,
        expected_state_version: int,
        lease: AttemptLeaseV3 | None = None,
    ) -> None:
        with self._write() as connection:
            attempt = self._load_attempt(connection, result.attempt_id)
            self._assert_attempt_lineage(attempt, result.run_id, result.plan_version_id)
            run = self._require_run(connection, result.run_id)
            self._check_state(run, expected_state_version)
            checked = self._clock()
            self._expire_attempt_or_raise(
                connection,
                attempt,
                now=checked,
                expected_state_version=expected_state_version,
            )
            self._assert_lease(attempt, lease, checked)
            invocation = self._load_invocation_for_step(
                connection, attempt_id=result.attempt_id, step_number=result.step_number
            )
            if invocation is None or invocation.state != "acknowledged" or (
                invocation.receipt_id,
                invocation.result_artifact,
            ) != (result.receipt_id, result.result_artifact):
                raise ResearchV3ConflictError(
                    "Actor result requires its exactly acknowledged invocation receipt and Artifact"
                )
            self._append_record(
                connection,
                run_id=result.run_id,
                record_kind="actor_result",
                natural_key=f"{result.attempt_id}:{result.step_number}",
                schema_version="actor-execution-result-v3",
                value=result,
                expected_state_version=expected_state_version,
                plan_version_id=result.plan_version_id,
                attempt_id=result.attempt_id,
                step_number=result.step_number,
                artifact=result.result_artifact,
            )

    def get_evidence_manifest(
        self, artifact: EvidenceManifestArtifactRefV3
    ) -> EvidenceManifestV3 | None:
        return self._get_sealed_record(
            artifact,
            record_kind="evidence_manifest",
            schema_version="evidence-manifest-v3",
            model_type=EvidenceManifestV3,
        )

    def append_evidence_manifest(
        self, manifest: EvidenceManifestV3, *, expected_state_version: int
    ) -> EvidenceManifestArtifactRefV3:
        content_hash = canonical_json_v3_sha256(manifest)
        artifact = EvidenceManifestArtifactRefV3(
            artifact_id=_artifact_id(
                run_id=manifest.run_id, kind="evidence_manifest", content_hash=content_hash
            ),
            kind="evidence_manifest",
            schema_version="evidence-manifest-v3",
            content_hash=content_hash,
        )
        with self._write() as connection:
            attempt = self._load_attempt(connection, manifest.attempt_id)
            self._assert_attempt_lineage(attempt, manifest.run_id, manifest.plan_version_id)
            if attempt.status != "completed":
                raise ResearchV3ConflictError("Evidence Manifest requires a completed Attempt")
            expected_ids = {
                item.pointer.artifact.artifact_id for item in manifest.evidence
            }
            verified_rows = connection.execute(
                """SELECT * FROM research_v3_verified_artifacts WHERE run_id = ?""",
                (manifest.run_id,),
            ).fetchall()
            verified = tuple(self._verified_from_row(row) for row in verified_rows)
            stored_ids = {
                item.artifact.artifact_id
                for item in verified
                if item.plan_version_id == manifest.plan_version_id
                and item.attempt_id == manifest.attempt_id
            }
            if not expected_ids.issubset(stored_ids):
                raise ResearchV3ConflictError(
                    "Evidence Manifest references an unpersisted verified Actor Artifact"
                )
            self._append_record(
                connection,
                run_id=manifest.run_id,
                record_kind="evidence_manifest",
                natural_key=artifact.artifact_id,
                schema_version="evidence-manifest-v3",
                value=manifest,
                expected_state_version=expected_state_version,
                plan_version_id=manifest.plan_version_id,
                attempt_id=manifest.attempt_id,
                artifact=artifact,
            )
        return artifact

    def get_deliverable(self, artifact: SealedArtifactRefV3) -> ResearchDeliverableV3 | None:
        return self._get_sealed_record(
            artifact,
            record_kind="deliverable",
            schema_version="research-deliverable-v3",
            model_type=ResearchDeliverableV3,
        )

    def append_deliverable(
        self, deliverable: ResearchDeliverableV3, *, expected_state_version: int
    ) -> SealedArtifactRefV3:
        return self._append_lineage_artifact(
            run_id=deliverable.run_id,
            plan_version_id=deliverable.plan_version_id,
            attempt_id=deliverable.attempt_id,
            record_kind="deliverable",
            kind="research_deliverable",
            schema_version="research-deliverable-v3",
            value=deliverable,
            expected_state_version=expected_state_version,
        )

    def get_review(self, artifact: SealedArtifactRefV3) -> ReportReviewV3 | None:
        return self._get_sealed_record(
            artifact,
            record_kind="review",
            schema_version="report-review-v3",
            model_type=ReportReviewV3,
        )

    def append_review(
        self, review: ReportReviewV3, *, expected_state_version: int
    ) -> SealedArtifactRefV3:
        return self._append_lineage_artifact(
            run_id=review.run_id,
            plan_version_id=review.plan_version_id,
            attempt_id=review.attempt_id,
            record_kind="review",
            kind="report_review",
            schema_version="report-review-v3",
            value=review,
            expected_state_version=expected_state_version,
        )

    def get_report(self, artifact: SealedArtifactRefV3) -> ReportDocumentV3 | None:
        return self._get_sealed_record(
            artifact,
            record_kind="report",
            schema_version="report-document-v3",
            model_type=ReportDocumentV3,
        )

    def append_report(
        self, report: ReportDocumentV3, *, expected_state_version: int
    ) -> SealedArtifactRefV3:
        return self._append_lineage_artifact(
            run_id=report.run_id,
            plan_version_id=report.plan_version_id,
            attempt_id=report.attempt_id,
            record_kind="report",
            kind="report_document",
            schema_version="report-document-v3",
            value=report,
            expected_state_version=expected_state_version,
        )

    def _append_lineage_artifact(
        self,
        *,
        run_id: str,
        plan_version_id: str,
        attempt_id: str,
        record_kind: str,
        kind: str,
        schema_version: str,
        value: BaseModel,
        expected_state_version: int,
    ) -> SealedArtifactRefV3:
        artifact = _sealed_ref(
            run_id=run_id, kind=kind, schema_version=schema_version, value=value
        )
        with self._write() as connection:
            attempt = self._load_attempt(connection, attempt_id)
            self._assert_attempt_lineage(attempt, run_id, plan_version_id)
            if attempt.status != "completed":
                raise ResearchV3ConflictError(f"{record_kind} requires a completed Attempt")
            self._append_record(
                connection,
                run_id=run_id,
                record_kind=record_kind,
                natural_key=artifact.artifact_id,
                schema_version=schema_version,
                value=value,
                expected_state_version=expected_state_version,
                plan_version_id=plan_version_id,
                attempt_id=attempt_id,
                artifact=artifact,
            )
        return artifact

    def append_verified_json(
        self,
        content: VerifiedArtifactContentV3,
        *,
        expected_state_version: int,
        lease: AttemptLeaseV3,
    ) -> None:
        with self._write() as connection:
            row = self._require_run(connection, content.run_id)
            self._check_state(row, expected_state_version)
            attempt = self._load_attempt(connection, content.attempt_id)
            self._assert_attempt_lineage(attempt, content.run_id, content.plan_version_id)
            checked = self._clock()
            self._expire_attempt_or_raise(
                connection,
                attempt,
                now=checked,
                expected_state_version=expected_state_version,
            )
            self._assert_lease(attempt, lease, checked)
            payload, payload_hash = _encode_model(content)
            try:
                connection.execute(
                    """
                    INSERT INTO research_v3_verified_artifacts(
                        artifact_id, run_id, plan_version_id, attempt_id, step_number,
                        artifact_kind, artifact_schema_version, artifact_content_hash,
                        payload, payload_hash, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        content.artifact.artifact_id,
                        content.run_id,
                        content.plan_version_id,
                        content.attempt_id,
                        content.step_number,
                        content.artifact.kind,
                        content.artifact.schema_version,
                        content.artifact.content_hash,
                        payload,
                        payload_hash,
                        _iso(self._clock()),
                    ),
                )
            except sqlite3.IntegrityError:
                raise ResearchV3ConflictError("verified Actor Artifact was already appended") from None
            self._advance_state(connection, content.run_id, expected_state_version)

    def read_verified_json(
        self,
        *,
        run_id: Identifier,
        plan_version_id: Identifier,
        attempt_id: Identifier,
        step_number: int,
        artifact: SealedArtifactRefV3,
    ) -> VerifiedArtifactContentV3 | None:
        with self._lock:
            if self._select_run(self._connection, run_id) is None:
                return None
            rows = self._connection.execute(
                """SELECT * FROM research_v3_verified_artifacts WHERE run_id = ?""",
                (run_id,),
            ).fetchall()
            values = tuple(self._verified_from_row(row) for row in rows)
            matches = [value for value in values if value.artifact.artifact_id == artifact.artifact_id]
            if not matches:
                return None
            if len(matches) != 1:
                raise ResearchV3IntegrityError("verified Actor Artifact identity is not unique")
            value = matches[0]
            if (
                value.run_id,
                value.plan_version_id,
                value.attempt_id,
                value.step_number,
                value.artifact,
            ) != (run_id, plan_version_id, attempt_id, step_number, artifact):
                raise ResearchV3IntegrityError(
                    "verified Actor Artifact columns do not match its typed payload"
                )
            return value

    def append_approval(
        self,
        run_id: Identifier,
        approval: WorkbenchApprovalV1,
        *,
        expected_state_version: int,
    ) -> None:
        with self._write() as connection:
            plan = self._read_record(
                connection,
                run_id=run_id,
                record_kind="plan",
                natural_key=approval.plan_version_id,
                schema_version="execution-plan-v3",
                model_type=ExecutionPlanVersionV3,
            )
            if plan is None:
                raise ResearchV3ConflictError("approval Plan is not persisted")
            self._append_record(
                connection,
                run_id=run_id,
                record_kind="approval",
                natural_key=approval.gate_key,
                schema_version="workbench-approval-v1",
                value=approval,
                expected_state_version=expected_state_version,
                plan_version_id=approval.plan_version_id,
            )

    def create_attempt(
        self,
        *,
        run_id: Identifier,
        plan_version_id: Identifier,
        attempt_id: Identifier,
        deadline_at: datetime,
        expected_state_version: int,
        created_at: datetime | None = None,
    ) -> ExecutionAttemptV3:
        created = _require_aware(created_at or self._clock(), "attempt created_at")
        deadline = _require_aware(deadline_at, "attempt deadline_at")
        with self._write() as connection:
            run = self._require_run(connection, run_id)
            self._check_state(run, expected_state_version)
            plan = self._read_record(
                connection,
                run_id=run_id,
                record_kind="plan",
                natural_key=plan_version_id,
                schema_version="execution-plan-v3",
                model_type=ExecutionPlanVersionV3,
            )
            if plan is None:
                raise ResearchV3ConflictError("Attempt Plan is not persisted")
            active_row = connection.execute(
                """SELECT * FROM research_v3_attempts
                WHERE run_id = ? AND status IN ('pending', 'running', 'paused')""",
                (run_id,),
            ).fetchone()
            if active_row is not None:
                active_attempt = self._attempt_from_row(active_row)
                self._expire_attempt_if_due(connection, active_attempt, created)
            next_number = connection.execute(
                "SELECT COALESCE(MAX(attempt_number), 0) + 1 FROM research_v3_attempts WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]
            attempt = ExecutionAttemptV3(
                attempt_id=attempt_id,
                run_id=run_id,
                plan_version_id=plan_version_id,
                attempt_number=next_number,
                status="pending",
                deadline_at=deadline,
                created_at=created,
                updated_at=created,
            )
            payload, payload_hash = _encode_model(attempt)
            try:
                connection.execute(
                    """
                    INSERT INTO research_v3_attempts(
                        attempt_id, run_id, plan_version_id, attempt_number, status,
                        lease_owner, lease_token, fencing_epoch, lease_expires_at,
                        deadline_at, failed_step_number, failure_code, pause_reason,
                        payload, payload_hash, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, NULL, NULL, 0, NULL, ?, NULL, NULL, NULL, ?, ?, ?, ?)
                    """,
                    (
                        attempt.attempt_id,
                        attempt.run_id,
                        attempt.plan_version_id,
                        attempt.attempt_number,
                        attempt.status,
                        _iso(attempt.deadline_at),
                        payload,
                        payload_hash,
                        _iso(created),
                        _iso(created),
                    ),
                )
            except sqlite3.IntegrityError:
                raise ResearchV3ConflictError("only one active Attempt is allowed per run") from None
            self._advance_state(connection, run_id, expected_state_version)
            return attempt

    def get_attempt(self, attempt_id: Identifier) -> ExecutionAttemptV3 | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT attempts.* FROM research_v3_attempts AS attempts
                JOIN research_v3_runs AS runs ON runs.run_id = attempts.run_id
                WHERE attempts.attempt_id = ? AND runs.owner_id = ?
                  AND runs.workspace_id = ? AND runs.project_id = ? AND runs.tombstoned_at IS NULL
                """,
                (
                    attempt_id,
                    self.scope.owner_id,
                    self.scope.workspace_id,
                    self.scope.project_id,
                ),
            ).fetchone()
            return self._attempt_from_row(row) if row is not None else None

    def _load_attempt(
        self, connection: sqlite3.Connection, attempt_id: str
    ) -> ExecutionAttemptV3:
        row = connection.execute(
            "SELECT * FROM research_v3_attempts WHERE attempt_id = ?", (attempt_id,)
        ).fetchone()
        if row is None:
            raise ResearchV3ConflictError("Attempt is not persisted")
        self._require_run(connection, row["run_id"])
        return self._attempt_from_row(row)

    @staticmethod
    def _attempt_from_row(row: sqlite3.Row) -> ExecutionAttemptV3:
        attempt = _decode_model(
            payload=row["payload"],
            payload_hash=row["payload_hash"],
            model_type=ExecutionAttemptV3,
            label="execution Attempt",
        )
        projection = (
            row["attempt_id"],
            row["run_id"],
            row["plan_version_id"],
            row["attempt_number"],
            row["status"],
            row["lease_owner"],
            row["lease_token"],
            row["fencing_epoch"],
            row["lease_expires_at"],
            row["deadline_at"],
            row["failed_step_number"],
            row["failure_code"],
            row["pause_reason"],
            row["created_at"],
            row["updated_at"],
        )
        expected = (
            attempt.attempt_id,
            attempt.run_id,
            attempt.plan_version_id,
            attempt.attempt_number,
            attempt.status,
            attempt.lease_owner,
            attempt.lease_token,
            attempt.fencing_epoch,
            _iso(attempt.lease_expires_at) if attempt.lease_expires_at else None,
            _iso(attempt.deadline_at),
            attempt.failed_step_number,
            attempt.failure_code,
            attempt.pause_reason,
            _iso(attempt.created_at),
            _iso(attempt.updated_at),
        )
        if projection != expected:
            raise ResearchV3IntegrityError("execution Attempt columns do not match its typed payload")
        return attempt

    @staticmethod
    def _store_attempt(connection: sqlite3.Connection, attempt: ExecutionAttemptV3) -> None:
        payload, payload_hash = _encode_model(attempt)
        cursor = connection.execute(
            """
            UPDATE research_v3_attempts SET
                status = ?, lease_owner = ?, lease_token = ?, fencing_epoch = ?,
                lease_expires_at = ?, deadline_at = ?, failed_step_number = ?,
                failure_code = ?, pause_reason = ?, payload = ?, payload_hash = ?, updated_at = ?
            WHERE attempt_id = ?
            """,
            (
                attempt.status,
                attempt.lease_owner,
                attempt.lease_token,
                attempt.fencing_epoch,
                _iso(attempt.lease_expires_at) if attempt.lease_expires_at else None,
                _iso(attempt.deadline_at),
                attempt.failed_step_number,
                attempt.failure_code,
                attempt.pause_reason,
                payload,
                payload_hash,
                _iso(attempt.updated_at),
                attempt.attempt_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ResearchV3ConflictError("Attempt update lost its persistence row")

    @staticmethod
    def _assert_attempt_lineage(
        attempt: ExecutionAttemptV3, run_id: str, plan_version_id: str
    ) -> None:
        if (attempt.run_id, attempt.plan_version_id) != (run_id, plan_version_id):
            raise ResearchV3ConflictError("Attempt does not belong to the supplied Run and Plan")

    @staticmethod
    def _assert_lease(
        attempt: ExecutionAttemptV3,
        lease: AttemptLeaseV3 | None,
        now: datetime,
    ) -> None:
        checked = _require_aware(now, "lease check")
        if lease is None or (
            attempt.status,
            attempt.attempt_id,
            attempt.lease_owner,
            attempt.lease_token,
            attempt.fencing_epoch,
            attempt.lease_expires_at,
        ) != (
            "running",
            lease.attempt_id,
            lease.owner,
            lease.token,
            lease.fencing_epoch,
            lease.expires_at,
        ):
            raise ResearchV3ConflictError("Attempt lease or fencing token is stale")
        if lease.expires_at <= checked or attempt.deadline_at <= checked:
            raise ResearchV3ConflictError("Attempt lease is expired")

    def _expire_attempt_if_due(
        self,
        connection: sqlite3.Connection,
        attempt: ExecutionAttemptV3,
        now: datetime,
    ) -> ExecutionAttemptV3 | None:
        checked = _require_aware(now, "attempt deadline check")
        if attempt.status not in {"pending", "running", "paused"} or attempt.deadline_at > checked:
            return None
        transition_at = attempt.deadline_at
        invocation_rows = connection.execute(
            """SELECT * FROM research_v3_invocations
            WHERE attempt_id = ? ORDER BY step_number, invocation_id""",
            (attempt.attempt_id,),
        ).fetchall()
        for invocation_row in invocation_rows:
            invocation = self._invocation_from_row(invocation_row)
            if invocation.state == "prepared":
                cancelled = invocation.model_copy(
                    update={
                        "state": "cancelled",
                        "error_code": _DEADLINE_ERROR_CODE,
                        "updated_at": transition_at,
                    }
                )
                self._store_invocation(connection, cancelled)
            elif invocation.state == "sent":
                unknown = invocation.model_copy(
                    update={
                        "state": "unknown",
                        "unknown_at": transition_at,
                        "error_code": _DEADLINE_ERROR_CODE,
                        "updated_at": transition_at,
                    }
                )
                self._store_invocation(connection, unknown)
        expired = attempt.model_copy(
            update={
                "status": "aborted",
                "lease_owner": None,
                "lease_token": None,
                "lease_expires_at": None,
                "fencing_epoch": attempt.fencing_epoch + 1,
                "failed_step_number": None,
                "failure_code": None,
                "pause_reason": None,
                "updated_at": transition_at,
            }
        )
        self._store_attempt(connection, expired)
        return expired

    def _expire_attempt_or_raise(
        self,
        connection: sqlite3.Connection,
        attempt: ExecutionAttemptV3,
        *,
        now: datetime,
        expected_state_version: int,
    ) -> None:
        if self._expire_attempt_if_due(connection, attempt, now) is None:
            return
        self._advance_state(connection, attempt.run_id, expected_state_version)
        raise _CommitResearchV3Conflict("Attempt deadline was reached and the Attempt was aborted")

    def claim_attempt(
        self,
        attempt_id: Identifier,
        *,
        owner: Identifier,
        token: Identifier,
        now: datetime,
        lease_ttl: timedelta,
        expected_state_version: int,
    ) -> AttemptLeaseV3 | None:
        checked = _require_aware(now, "claim time")
        if lease_ttl <= timedelta(0):
            raise ValueError("lease_ttl must be positive")
        with self._write() as connection:
            attempt = self._load_attempt(connection, attempt_id)
            run = self._require_run(connection, attempt.run_id)
            self._check_state(run, expected_state_version)
            if self._expire_attempt_if_due(connection, attempt, checked) is not None:
                self._advance_state(connection, attempt.run_id, expected_state_version)
                return None
            if (
                attempt.status == "running"
                and attempt.lease_owner == owner
                and attempt.lease_token == token
                and attempt.lease_expires_at is not None
                and attempt.lease_expires_at > checked
            ):
                return AttemptLeaseV3(
                    attempt_id=attempt.attempt_id,
                    owner=owner,
                    token=token,
                    fencing_epoch=attempt.fencing_epoch,
                    expires_at=attempt.lease_expires_at,
                )
            pending = attempt.status == "pending"
            expired = (
                attempt.status == "running"
                and attempt.lease_expires_at is not None
                and attempt.lease_expires_at <= checked
            )
            if not pending and not expired:
                return None
            if expired:
                sent = connection.execute(
                    """SELECT * FROM research_v3_invocations
                    WHERE attempt_id = ? AND state = 'sent' ORDER BY step_number""",
                    (attempt_id,),
                ).fetchall()
                if sent:
                    for invocation_row in sent:
                        invocation = self._invocation_from_row(invocation_row)
                        unknown = invocation.model_copy(
                            update={
                                "state": "unknown",
                                "unknown_at": checked,
                                "error_code": "lease_expired_after_send",
                                "updated_at": checked,
                            }
                        )
                        self._store_invocation(connection, unknown)
                    first = self._invocation_from_row(sent[0])
                    paused = attempt.model_copy(
                        update={
                            "status": "paused",
                            "lease_owner": None,
                            "lease_token": None,
                            "lease_expires_at": None,
                            "failed_step_number": first.step_number,
                            "failure_code": "actor_result_unknown",
                            "pause_reason": "unknown",
                            "updated_at": checked,
                        }
                    )
                    self._store_attempt(connection, paused)
                    self._advance_state(connection, attempt.run_id, expected_state_version)
                    return None
            expires_at = min(checked + lease_ttl, attempt.deadline_at)
            claimed = attempt.model_copy(
                update={
                    "status": "running",
                    "lease_owner": owner,
                    "lease_token": token,
                    "fencing_epoch": attempt.fencing_epoch + 1,
                    "lease_expires_at": expires_at,
                    "updated_at": checked,
                }
            )
            self._store_attempt(connection, claimed)
            self._advance_state(connection, attempt.run_id, expected_state_version)
            return AttemptLeaseV3(
                attempt_id=attempt_id,
                owner=owner,
                token=token,
                fencing_epoch=claimed.fencing_epoch,
                expires_at=expires_at,
            )

    def heartbeat_attempt(
        self,
        lease: AttemptLeaseV3,
        *,
        now: datetime,
        lease_ttl: timedelta,
        expected_state_version: int,
    ) -> AttemptLeaseV3:
        checked = _require_aware(now, "heartbeat time")
        if lease_ttl <= timedelta(0):
            raise ValueError("lease_ttl must be positive")
        with self._write() as connection:
            attempt = self._load_attempt(connection, lease.attempt_id)
            run = self._require_run(connection, attempt.run_id)
            self._check_state(run, expected_state_version)
            self._expire_attempt_or_raise(
                connection,
                attempt,
                now=checked,
                expected_state_version=expected_state_version,
            )
            self._assert_lease(attempt, lease, checked)
            expires_at = min(checked + lease_ttl, attempt.deadline_at)
            if expires_at <= checked:
                raise ResearchV3ConflictError("Attempt deadline prevents heartbeat")
            updated = attempt.model_copy(
                update={"lease_expires_at": expires_at, "updated_at": checked}
            )
            self._store_attempt(connection, updated)
            self._advance_state(connection, attempt.run_id, expected_state_version)
            return AttemptLeaseV3(
                attempt_id=lease.attempt_id,
                owner=lease.owner,
                token=lease.token,
                fencing_epoch=lease.fencing_epoch,
                expires_at=expires_at,
            )

    def pause_attempt(
        self,
        lease: AttemptLeaseV3,
        *,
        failed_step_number: int,
        failure_code: Identifier,
        reason: Literal["failed", "unknown"],
        now: datetime,
        expected_state_version: int,
    ) -> ExecutionAttemptV3:
        checked = _require_aware(now, "pause time")
        with self._write() as connection:
            attempt = self._load_attempt(connection, lease.attempt_id)
            run = self._require_run(connection, attempt.run_id)
            self._check_state(run, expected_state_version)
            self._expire_attempt_or_raise(
                connection,
                attempt,
                now=checked,
                expected_state_version=expected_state_version,
            )
            self._assert_lease(attempt, lease, checked)
            plan = self._read_record(
                connection,
                run_id=attempt.run_id,
                record_kind="plan",
                natural_key=attempt.plan_version_id,
                schema_version="execution-plan-v3",
                model_type=ExecutionPlanVersionV3,
            )
            if plan is None:
                raise ResearchV3IntegrityError("Attempt Plan disappeared")
            if failed_step_number not in {step.step_number for step in plan.payload.steps}:
                raise ResearchV3ConflictError("failed Step is not in the selected Plan")
            paused = attempt.model_copy(
                update={
                    "status": "paused",
                    "lease_owner": None,
                    "lease_token": None,
                    "lease_expires_at": None,
                    "failed_step_number": failed_step_number,
                    "failure_code": failure_code,
                    "pause_reason": reason,
                    "updated_at": checked,
                }
            )
            self._store_attempt(connection, paused)
            self._advance_state(connection, attempt.run_id, expected_state_version)
            return paused

    def complete_attempt(
        self,
        lease: AttemptLeaseV3,
        *,
        now: datetime,
        expected_state_version: int,
    ) -> ExecutionAttemptV3:
        checked = _require_aware(now, "completion time")
        with self._write() as connection:
            attempt = self._load_attempt(connection, lease.attempt_id)
            run = self._require_run(connection, attempt.run_id)
            self._check_state(run, expected_state_version)
            self._expire_attempt_or_raise(
                connection,
                attempt,
                now=checked,
                expected_state_version=expected_state_version,
            )
            self._assert_lease(attempt, lease, checked)
            plan = self._read_record(
                connection,
                run_id=attempt.run_id,
                record_kind="plan",
                natural_key=attempt.plan_version_id,
                schema_version="execution-plan-v3",
                model_type=ExecutionPlanVersionV3,
            )
            if plan is None:
                raise ResearchV3IntegrityError("Attempt Plan disappeared")
            result_rows = self._validated_record_rows(
                connection,
                run_id=attempt.run_id,
                record_kind="actor_result",
                schema_version="actor-execution-result-v3",
                model_type=ActorExecutionResultV3,
            )
            result_steps = {
                result.step_number
                for _row, result in result_rows
                if result.attempt_id == attempt.attempt_id
            }
            if result_steps != {step.step_number for step in plan.payload.steps}:
                raise ResearchV3ConflictError("Attempt cannot complete without exact Plan Step results")
            unsettled = connection.execute(
                """SELECT 1 FROM research_v3_invocations
                WHERE attempt_id = ? AND state IN ('prepared', 'sent', 'unknown') LIMIT 1""",
                (attempt.attempt_id,),
            ).fetchone()
            if unsettled is not None:
                raise ResearchV3ConflictError("Attempt has an unsettled Actor invocation")
            completed = attempt.model_copy(
                update={
                    "status": "completed",
                    "lease_owner": None,
                    "lease_token": None,
                    "lease_expires_at": None,
                    "updated_at": checked,
                }
            )
            self._store_attempt(connection, completed)
            self._advance_state(connection, attempt.run_id, expected_state_version)
            return completed

    def abort_attempt(
        self,
        attempt_id: Identifier,
        *,
        now: datetime,
        expected_state_version: int,
        lease: AttemptLeaseV3 | None = None,
    ) -> ExecutionAttemptV3:
        aborted_at = _require_aware(now, "abort time")
        with self._write() as connection:
            attempt = self._load_attempt(connection, attempt_id)
            run = self._require_run(connection, attempt.run_id)
            self._check_state(run, expected_state_version)
            expired = self._expire_attempt_if_due(connection, attempt, aborted_at)
            if expired is not None:
                self._advance_state(connection, attempt.run_id, expected_state_version)
                return expired
            if attempt.status == "running":
                self._assert_lease(attempt, lease, aborted_at)
            elif attempt.status not in {"pending", "paused"}:
                raise ResearchV3ConflictError("only an active Attempt may be aborted")
            aborted = attempt.model_copy(
                update={
                    "status": "aborted",
                    "lease_owner": None,
                    "lease_token": None,
                    "lease_expires_at": None,
                    "failed_step_number": None,
                    "failure_code": None,
                    "pause_reason": None,
                    "updated_at": aborted_at,
                }
            )
            self._store_attempt(connection, aborted)
            self._advance_state(connection, attempt.run_id, expected_state_version)
            return aborted

    def list_recoverable_attempts(self, *, now: datetime) -> tuple[ExecutionAttemptV3, ...]:
        checked = _require_aware(now, "recovery time")
        with self._write() as connection:
            expired_rows = connection.execute(
                """
                SELECT attempts.* FROM research_v3_attempts AS attempts
                JOIN research_v3_runs AS runs ON runs.run_id = attempts.run_id
                WHERE runs.owner_id = ? AND runs.workspace_id = ? AND runs.project_id = ?
                  AND runs.tombstoned_at IS NULL AND attempts.deadline_at <= ?
                  AND attempts.status IN ('pending', 'running', 'paused')
                ORDER BY attempts.run_id, attempts.attempt_id
                """,
                (
                    self.scope.owner_id,
                    self.scope.workspace_id,
                    self.scope.project_id,
                    _iso(checked),
                ),
            ).fetchall()
            for row in expired_rows:
                attempt = self._attempt_from_row(row)
                if self._expire_attempt_if_due(connection, attempt, checked) is not None:
                    connection.execute(
                        """UPDATE research_v3_runs SET state_version = state_version + 1
                        WHERE run_id = ? AND tombstoned_at IS NULL""",
                        (attempt.run_id,),
                    )
            rows = connection.execute(
                """
                SELECT attempts.* FROM research_v3_attempts AS attempts
                JOIN research_v3_runs AS runs ON runs.run_id = attempts.run_id
                WHERE runs.owner_id = ? AND runs.workspace_id = ? AND runs.project_id = ?
                  AND runs.tombstoned_at IS NULL AND attempts.deadline_at > ?
                  AND (attempts.status IN ('pending', 'paused')
                       OR (attempts.status = 'running' AND attempts.lease_expires_at <= ?))
                ORDER BY attempts.updated_at, attempts.attempt_id
                """,
                (
                    self.scope.owner_id,
                    self.scope.workspace_id,
                    self.scope.project_id,
                    _iso(checked),
                    _iso(checked),
                ),
            ).fetchall()
            return tuple(self._attempt_from_row(row) for row in rows)

    def prepare_invocation(
        self,
        *,
        invocation_id: Identifier,
        run_id: Identifier,
        plan_version_id: Identifier,
        attempt_id: Identifier,
        step_number: int,
        lease: AttemptLeaseV3,
        now: datetime,
        expected_state_version: int,
    ) -> ActorInvocationV3:
        created = _require_aware(now, "invocation preparation time")
        with self._write() as connection:
            run = self._require_run(connection, run_id)
            self._check_state(run, expected_state_version)
            attempt = self._load_attempt(connection, attempt_id)
            self._assert_attempt_lineage(attempt, run_id, plan_version_id)
            self._expire_attempt_or_raise(
                connection,
                attempt,
                now=created,
                expected_state_version=expected_state_version,
            )
            self._assert_lease(attempt, lease, created)
            plan = self._read_record(
                connection,
                run_id=run_id,
                record_kind="plan",
                natural_key=plan_version_id,
                schema_version="execution-plan-v3",
                model_type=ExecutionPlanVersionV3,
            )
            if plan is None or step_number not in {step.step_number for step in plan.payload.steps}:
                raise ResearchV3ConflictError("invocation Step is not in the selected Plan")
            invocation = ActorInvocationV3(
                invocation_id=invocation_id,
                run_id=run_id,
                plan_version_id=plan_version_id,
                attempt_id=attempt_id,
                step_number=step_number,
                state="prepared",
                send_count=0,
                created_at=created,
                updated_at=created,
            )
            payload, payload_hash = _encode_model(invocation)
            try:
                connection.execute(
                    """
                    INSERT INTO research_v3_invocations(
                        invocation_id, run_id, plan_version_id, attempt_id, step_number,
                        state, send_count, sent_fencing_epoch, sent_at, unknown_at,
                        receipt_id, result_artifact_id, error_code, payload, payload_hash,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'prepared', 0, NULL, NULL, NULL, NULL, NULL, NULL, ?, ?, ?, ?)
                    """,
                    (
                        invocation.invocation_id,
                        invocation.run_id,
                        invocation.plan_version_id,
                        invocation.attempt_id,
                        invocation.step_number,
                        payload,
                        payload_hash,
                        _iso(created),
                        _iso(created),
                    ),
                )
            except sqlite3.IntegrityError:
                raise ResearchV3ConflictError("Actor invocation for this Step already exists") from None
            self._advance_state(connection, run_id, expected_state_version)
            return invocation

    def get_invocation(self, invocation_id: Identifier) -> ActorInvocationV3 | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT invocations.* FROM research_v3_invocations AS invocations
                JOIN research_v3_runs AS runs ON runs.run_id = invocations.run_id
                WHERE invocations.invocation_id = ? AND runs.owner_id = ?
                  AND runs.workspace_id = ? AND runs.project_id = ? AND runs.tombstoned_at IS NULL
                """,
                (
                    invocation_id,
                    self.scope.owner_id,
                    self.scope.workspace_id,
                    self.scope.project_id,
                ),
            ).fetchone()
            return self._invocation_from_row(row) if row is not None else None

    def _load_invocation(
        self, connection: sqlite3.Connection, invocation_id: str
    ) -> ActorInvocationV3:
        row = connection.execute(
            "SELECT * FROM research_v3_invocations WHERE invocation_id = ?", (invocation_id,)
        ).fetchone()
        if row is None:
            raise ResearchV3ConflictError("Actor invocation is not persisted")
        self._require_run(connection, row["run_id"])
        return self._invocation_from_row(row)

    def _load_invocation_for_step(
        self, connection: sqlite3.Connection, *, attempt_id: str, step_number: int
    ) -> ActorInvocationV3 | None:
        row = connection.execute(
            """SELECT * FROM research_v3_invocations
            WHERE attempt_id = ? AND step_number = ?""",
            (attempt_id, step_number),
        ).fetchone()
        return self._invocation_from_row(row) if row is not None else None

    @staticmethod
    def _invocation_from_row(row: sqlite3.Row) -> ActorInvocationV3:
        invocation = _decode_model(
            payload=row["payload"],
            payload_hash=row["payload_hash"],
            model_type=ActorInvocationV3,
            label="Actor invocation",
        )
        projection = (
            row["invocation_id"], row["run_id"], row["plan_version_id"],
            row["attempt_id"], row["step_number"], row["state"], row["send_count"],
            row["sent_fencing_epoch"], row["sent_at"], row["unknown_at"],
            row["receipt_id"], row["result_artifact_id"], row["error_code"],
            row["created_at"], row["updated_at"],
        )
        expected = (
            invocation.invocation_id, invocation.run_id, invocation.plan_version_id,
            invocation.attempt_id, invocation.step_number, invocation.state,
            invocation.send_count, invocation.sent_fencing_epoch,
            _iso(invocation.sent_at) if invocation.sent_at else None,
            _iso(invocation.unknown_at) if invocation.unknown_at else None,
            invocation.receipt_id,
            invocation.result_artifact.artifact_id if invocation.result_artifact else None,
            invocation.error_code, _iso(invocation.created_at), _iso(invocation.updated_at),
        )
        if projection != expected:
            raise ResearchV3IntegrityError("Actor invocation columns do not match its typed payload")
        return invocation

    @staticmethod
    def _store_invocation(
        connection: sqlite3.Connection, invocation: ActorInvocationV3
    ) -> None:
        payload, payload_hash = _encode_model(invocation)
        cursor = connection.execute(
            """
            UPDATE research_v3_invocations SET state = ?, send_count = ?,
                sent_fencing_epoch = ?, sent_at = ?, unknown_at = ?, receipt_id = ?,
                result_artifact_id = ?, error_code = ?, payload = ?, payload_hash = ?, updated_at = ?
            WHERE invocation_id = ?
            """,
            (
                invocation.state,
                invocation.send_count,
                invocation.sent_fencing_epoch,
                _iso(invocation.sent_at) if invocation.sent_at else None,
                _iso(invocation.unknown_at) if invocation.unknown_at else None,
                invocation.receipt_id,
                invocation.result_artifact.artifact_id if invocation.result_artifact else None,
                invocation.error_code,
                payload,
                payload_hash,
                _iso(invocation.updated_at),
                invocation.invocation_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ResearchV3ConflictError("Actor invocation update lost its persistence row")

    def mark_invocation_sent(
        self,
        invocation_id: Identifier,
        *,
        lease: AttemptLeaseV3,
        now: datetime,
        expected_state_version: int,
    ) -> ActorInvocationV3:
        sent_at = _require_aware(now, "invocation send time")
        with self._write() as connection:
            invocation = self._load_invocation(connection, invocation_id)
            run = self._require_run(connection, invocation.run_id)
            self._check_state(run, expected_state_version)
            attempt = self._load_attempt(connection, invocation.attempt_id)
            self._expire_attempt_or_raise(
                connection,
                attempt,
                now=sent_at,
                expected_state_version=expected_state_version,
            )
            self._assert_lease(attempt, lease, sent_at)
            if invocation.state != "prepared":
                raise ResearchV3ConflictError(
                    "only a PREPARED invocation may be sent; UNKNOWN is never replayed"
                )
            sent = invocation.model_copy(
                update={
                    "state": "sent",
                    "send_count": 1,
                    "sent_fencing_epoch": lease.fencing_epoch,
                    "sent_at": sent_at,
                    "updated_at": sent_at,
                }
            )
            self._store_invocation(connection, sent)
            self._advance_state(connection, invocation.run_id, expected_state_version)
            return sent

    def acknowledge_invocation(
        self,
        invocation_id: Identifier,
        *,
        receipt_id: Identifier,
        result_artifact: SealedArtifactRefV3,
        lease: AttemptLeaseV3,
        now: datetime,
        expected_state_version: int,
    ) -> ActorInvocationV3:
        acknowledged_at = _require_aware(now, "invocation acknowledgement time")
        with self._write() as connection:
            invocation = self._load_invocation(connection, invocation_id)
            run = self._require_run(connection, invocation.run_id)
            self._check_state(run, expected_state_version)
            attempt = self._load_attempt(connection, invocation.attempt_id)
            self._expire_attempt_or_raise(
                connection,
                attempt,
                now=acknowledged_at,
                expected_state_version=expected_state_version,
            )
            self._assert_lease(attempt, lease, acknowledged_at)
            if invocation.state != "sent" or invocation.sent_fencing_epoch != lease.fencing_epoch:
                raise ResearchV3ConflictError("only the currently fenced SENT invocation may acknowledge")
            artifact_row = connection.execute(
                """SELECT * FROM research_v3_verified_artifacts WHERE artifact_id = ?""",
                (result_artifact.artifact_id,),
            ).fetchone()
            if artifact_row is None:
                raise ResearchV3ConflictError("acknowledged result Artifact is not persisted and verified")
            verified = self._verified_from_row(artifact_row)
            plan = self._read_record(
                connection,
                run_id=invocation.run_id,
                record_kind="plan",
                natural_key=invocation.plan_version_id,
                schema_version="execution-plan-v3",
                model_type=ExecutionPlanVersionV3,
            )
            plan_step = (
                next(
                    (
                        step
                        for step in plan.payload.steps
                        if step.step_number == invocation.step_number
                    ),
                    None,
                )
                if plan is not None
                else None
            )
            if plan_step is None:
                raise ResearchV3IntegrityError("invocation Step is absent from its persisted Plan")
            if (
                verified.artifact,
                verified.run_id,
                verified.plan_version_id,
                verified.attempt_id,
                verified.step_number,
                verified.receipt_id,
                verified.actor_type,
                verified.actor_id,
                verified.step_contract_hash,
            ) != (
                result_artifact,
                invocation.run_id,
                invocation.plan_version_id,
                invocation.attempt_id,
                invocation.step_number,
                receipt_id,
                plan_step.actor_type,
                plan_step.actor_id,
                plan_step.contract_hash,
            ):
                raise ResearchV3ConflictError(
                    "acknowledged result Artifact does not match its verified Step and receipt"
                )
            acknowledged = invocation.model_copy(
                update={
                    "state": "acknowledged",
                    "receipt_id": receipt_id,
                    "result_artifact": result_artifact,
                    "updated_at": acknowledged_at,
                }
            )
            self._store_invocation(connection, acknowledged)
            self._advance_state(connection, invocation.run_id, expected_state_version)
            return acknowledged

    def mark_invocation_unknown(
        self,
        invocation_id: Identifier,
        *,
        lease: AttemptLeaseV3,
        error_code: Identifier,
        now: datetime,
        expected_state_version: int,
    ) -> ActorInvocationV3:
        unknown_at = _require_aware(now, "invocation UNKNOWN time")
        with self._write() as connection:
            invocation = self._load_invocation(connection, invocation_id)
            run = self._require_run(connection, invocation.run_id)
            self._check_state(run, expected_state_version)
            attempt = self._load_attempt(connection, invocation.attempt_id)
            self._expire_attempt_or_raise(
                connection,
                attempt,
                now=unknown_at,
                expected_state_version=expected_state_version,
            )
            self._assert_lease(attempt, lease, unknown_at)
            if invocation.state != "sent" or invocation.sent_fencing_epoch != lease.fencing_epoch:
                raise ResearchV3ConflictError("only the currently fenced SENT invocation may become UNKNOWN")
            unknown = invocation.model_copy(
                update={
                    "state": "unknown",
                    "unknown_at": unknown_at,
                    "error_code": error_code,
                    "updated_at": unknown_at,
                }
            )
            self._store_invocation(connection, unknown)
            paused = attempt.model_copy(
                update={
                    "status": "paused",
                    "lease_owner": None,
                    "lease_token": None,
                    "lease_expires_at": None,
                    "failed_step_number": invocation.step_number,
                    "failure_code": "actor_result_unknown",
                    "pause_reason": "unknown",
                    "updated_at": unknown_at,
                }
            )
            self._store_attempt(connection, paused)
            self._advance_state(connection, invocation.run_id, expected_state_version)
            return unknown

    def _validate_preview_record_append(
        self,
        connection: sqlite3.Connection,
        *,
        run_id: str,
        record: PreviewRecordAppendV3,
    ) -> None:
        value = record.value
        if record.record_kind == "requirement":
            if not isinstance(value, RequirementVersionV3) or (
                value.run_id != run_id
                or record.natural_key != value.id
                or record.sequence_number != value.version
                or record.requirement_version_id != value.id
                or record.plan_version_id is not None
                or record.artifact is not None
            ):
                raise ResearchV3IntegrityError("preview Requirement append metadata is invalid")
            duplicate = connection.execute(
                """SELECT 1 FROM research_v3_records
                WHERE run_id = ? AND record_kind = 'requirement' AND sequence_number = ?""",
                (run_id, value.version),
            ).fetchone()
            if duplicate is not None:
                raise ResearchV3ConflictError("Requirement version was already appended")
            return
        if record.record_kind == "candidate_set":
            requirement_id = record.requirement_version_id
            requirement = (
                self._read_record(
                    connection,
                    run_id=run_id,
                    record_kind="requirement",
                    natural_key=requirement_id,
                    schema_version="research-task-v3",
                    model_type=RequirementVersionV3,
                )
                if requirement_id is not None
                else None
            )
            if (
                not isinstance(value, PlanCandidateSetV3)
                or requirement is None
                or record.natural_key != requirement_id
                or record.sequence_number is not None
                or record.plan_version_id is not None
                or record.artifact is not None
            ):
                raise ResearchV3ConflictError("preview candidate set Requirement is not persisted")
            return
        if record.record_kind == "problem_graph":
            if not isinstance(value, ProblemGraphV1):
                raise ResearchV3IntegrityError("preview ProblemGraph append type is invalid")
            requirement = self._read_record(
                connection,
                run_id=run_id,
                record_kind="requirement",
                natural_key=value.requirement_version_id,
                schema_version="research-task-v3",
                model_type=RequirementVersionV3,
            )
            expected_artifact = _sealed_ref(
                run_id=run_id,
                kind="problem_graph",
                schema_version="problem-graph-v1",
                value=value,
            )
            if (
                requirement is None
                or record.requirement_version_id != value.requirement_version_id
                or record.natural_key != expected_artifact.artifact_id
                or record.artifact is None
                or not _artifact_refs_equal(record.artifact, expected_artifact)
                or record.sequence_number is not None
                or record.plan_version_id is not None
            ):
                raise ResearchV3ConflictError("preview ProblemGraph lineage is not persisted exactly")
            return
        if record.record_kind == "control_snapshot":
            if not isinstance(value, ResearchControlSnapshotV3):
                raise ResearchV3IntegrityError("preview control snapshot append type is invalid")
            for actor in value.actors:
                try:
                    _IDENTIFIER_ADAPTER.validate_python(actor.implementation_id)
                except (TypeError, ValueError, ValidationError):
                    raise ResearchV3IntegrityError(
                        "persisted Actor implementation_id must satisfy the v3 Identifier contract"
                    ) from None
            expected_artifact = _sealed_ref(
                run_id=run_id,
                kind="research_control_snapshot",
                schema_version="research-control-snapshot-v3",
                value=value,
            )
            if (
                record.natural_key != expected_artifact.artifact_id
                or record.artifact is None
                or not _artifact_refs_equal(record.artifact, expected_artifact)
                or record.sequence_number is not None
                or record.requirement_version_id is not None
                or record.plan_version_id is not None
            ):
                raise ResearchV3IntegrityError("preview control snapshot Artifact metadata is invalid")
            return
        if record.record_kind == "plan":
            if not isinstance(value, ExecutionPlanVersionV3) or value.run_id != run_id:
                raise ResearchV3IntegrityError("preview Plan append type is invalid")
            requirement = self._read_record(
                connection,
                run_id=run_id,
                record_kind="requirement",
                natural_key=value.requirement_version_id,
                schema_version="research-task-v3",
                model_type=RequirementVersionV3,
            )
            graph_rows = self._validated_record_rows(
                connection,
                run_id=run_id,
                record_kind="problem_graph",
                schema_version="problem-graph-v1",
                model_type=ProblemGraphV1,
            )
            snapshot_rows = self._validated_record_rows(
                connection,
                run_id=run_id,
                record_kind="control_snapshot",
                schema_version="research-control-snapshot-v3",
                model_type=ResearchControlSnapshotV3,
            )
            graph_row = next(
                (
                    row
                    for row, _graph in graph_rows
                    if row["artifact_id"] == value.payload.problem_graph_artifact.artifact_id
                ),
                None,
            )
            snapshot_row = next(
                (
                    row
                    for row, _snapshot in snapshot_rows
                    if row["artifact_id"] == value.payload.control_snapshot_artifact.artifact_id
                ),
                None,
            )
            duplicate = connection.execute(
                """SELECT 1 FROM research_v3_records
                WHERE run_id = ? AND record_kind = 'plan' AND sequence_number = ?""",
                (run_id, value.version),
            ).fetchone()
            if (
                requirement is None
                or value.payload.requirement_content_hash != requirement.content_hash
                or record.natural_key != value.id
                or record.sequence_number != value.version
                or record.requirement_version_id != value.requirement_version_id
                or record.plan_version_id != value.id
                or record.artifact is not None
                or graph_row is None
                or snapshot_row is None
                or not _artifact_refs_equal(
                    self._artifact_from_row(graph_row),
                    value.payload.problem_graph_artifact,
                )
                or not _artifact_refs_equal(
                    self._artifact_from_row(snapshot_row),
                    value.payload.control_snapshot_artifact,
                )
            ):
                raise ResearchV3ConflictError("preview Plan lineage is not persisted exactly")
            if duplicate is not None:
                raise ResearchV3ConflictError("Execution Plan version was already appended")
            return
        raise ResearchV3IntegrityError("unsupported preview planning record kind")

    def commit_preview_command(
        self,
        *,
        run_id: Identifier,
        idempotency_key: Identifier,
        command_type: Identifier,
        request_hash: Sha256Hex,
        response_payload: Mapping[str, object],
        expected_state_version: int,
        records: tuple[PreviewRecordAppendV3, ...] = (),
        next_preview_status: Literal["confirmed", "cancelled"] | None = None,
        created_at: datetime | None = None,
    ) -> tuple[ResearchCommandReceiptV3, bool]:
        """Atomically append staged planning records and one command receipt/state transition."""

        created = _require_aware(created_at or self._clock(), "command receipt created_at")
        with self._write() as connection:
            run = self._require_run(connection, run_id)
            existing_row = connection.execute(
                """SELECT * FROM research_v3_command_receipts
                WHERE run_id = ? AND idempotency_key = ?""",
                (run_id, idempotency_key),
            ).fetchone()
            if existing_row is not None:
                existing = self._receipt_from_row(existing_row)
                if existing.command_type != command_type or existing.request_hash != request_hash:
                    raise ResearchV3ConflictError(
                        "idempotency key was already used for a different command"
                    )
                return existing, True
            self._check_state(run, expected_state_version)
            current_run = self._run_from_row(run)
            if current_run.preview_status != "active":
                raise ResearchV3ConflictError(
                    f"research-v3 preview is already {current_run.preview_status}"
                )
            for record in records:
                self._validate_preview_record_append(
                    connection,
                    run_id=run_id,
                    record=record,
                )
                self._append_record(
                    connection,
                    run_id=run_id,
                    record_kind=record.record_kind,
                    natural_key=record.natural_key,
                    schema_version=record.schema_version,
                    value=record.value,
                    expected_state_version=expected_state_version,
                    sequence_number=record.sequence_number,
                    requirement_version_id=record.requirement_version_id,
                    plan_version_id=record.plan_version_id,
                    artifact=record.artifact,
                    advance_state=False,
                )
            receipt = ResearchCommandReceiptV3(
                run_id=run_id,
                idempotency_key=idempotency_key,
                command_type=command_type,
                request_hash=request_hash,
                response_payload=response_payload,
                committed_state_version=expected_state_version + 1,
                created_at=created,
            )
            payload, payload_hash = _encode_model(receipt)
            connection.execute(
                """
                INSERT INTO research_v3_command_receipts(
                    run_id, idempotency_key, command_type, request_hash,
                    committed_state_version, payload, payload_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    idempotency_key,
                    command_type,
                    request_hash,
                    receipt.committed_state_version,
                    payload,
                    payload_hash,
                    _iso(created),
                ),
            )
            if next_preview_status is not None:
                cursor = connection.execute(
                    """UPDATE research_v3_runs SET preview_status = ?
                    WHERE run_id = ? AND preview_status = 'active'
                      AND state_version = ? AND tombstoned_at IS NULL""",
                    (next_preview_status, run_id, expected_state_version),
                )
                if cursor.rowcount != 1:
                    raise ResearchV3ConflictError("research-v3 preview lifecycle conflict")
            self._advance_state(connection, run_id, expected_state_version)
            return receipt, False

    def record_command_receipt(
        self,
        *,
        run_id: Identifier,
        idempotency_key: Identifier,
        command_type: Identifier,
        request_hash: Sha256Hex,
        response_payload: Mapping[str, object],
        expected_state_version: int,
        created_at: datetime | None = None,
    ) -> tuple[ResearchCommandReceiptV3, bool]:
        created = _require_aware(created_at or self._clock(), "command receipt created_at")
        with self._write() as connection:
            run = self._require_run(connection, run_id)
            existing_row = connection.execute(
                """SELECT * FROM research_v3_command_receipts
                WHERE run_id = ? AND idempotency_key = ?""",
                (run_id, idempotency_key),
            ).fetchone()
            if existing_row is not None:
                existing = self._receipt_from_row(existing_row)
                if (
                    existing.command_type != command_type
                    or existing.request_hash != request_hash
                ):
                    raise ResearchV3ConflictError(
                        "idempotency key was already used for a different command"
                    )
                return existing, True
            self._check_state(run, expected_state_version)
            receipt = ResearchCommandReceiptV3(
                run_id=run_id,
                idempotency_key=idempotency_key,
                command_type=command_type,
                request_hash=request_hash,
                response_payload=response_payload,
                committed_state_version=expected_state_version + 1,
                created_at=created,
            )
            payload, payload_hash = _encode_model(receipt)
            connection.execute(
                """
                INSERT INTO research_v3_command_receipts(
                    run_id, idempotency_key, command_type, request_hash,
                    committed_state_version, payload, payload_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    idempotency_key,
                    command_type,
                    request_hash,
                    receipt.committed_state_version,
                    payload,
                    payload_hash,
                    _iso(created),
                ),
            )
            self._advance_state(connection, run_id, expected_state_version)
            return receipt, False

    def get_command_receipt(
        self, run_id: Identifier, idempotency_key: Identifier
    ) -> ResearchCommandReceiptV3 | None:
        with self._lock:
            if self._select_run(self._connection, run_id, include_tombstone=True) is None:
                return None
            row = self._connection.execute(
                """SELECT * FROM research_v3_command_receipts
                WHERE run_id = ? AND idempotency_key = ?""",
                (run_id, idempotency_key),
            ).fetchone()
            return self._receipt_from_row(row) if row is not None else None

    @staticmethod
    def _receipt_from_row(row: sqlite3.Row) -> ResearchCommandReceiptV3:
        receipt = _decode_model(
            payload=row["payload"],
            payload_hash=row["payload_hash"],
            model_type=ResearchCommandReceiptV3,
            label="command receipt",
        )
        if (
            row["run_id"],
            row["idempotency_key"],
            row["command_type"],
            row["request_hash"],
            row["committed_state_version"],
            row["created_at"],
        ) != (
            receipt.run_id,
            receipt.idempotency_key,
            receipt.command_type,
            receipt.request_hash,
            receipt.committed_state_version,
            _iso(receipt.created_at),
        ):
            raise ResearchV3IntegrityError("command receipt columns do not match its typed payload")
        return receipt

    def purge_run(
        self,
        *,
        run_id: Identifier,
        idempotency_key: Identifier,
        request_hash: Sha256Hex,
        expected_state_version: int,
        purged_at: datetime | None = None,
    ) -> tuple[ResearchCommandReceiptV3, bool]:
        purged = _require_aware(purged_at or self._clock(), "purge time")
        with self._write() as connection:
            run = self._require_run(connection, run_id, include_tombstone=True)
            existing_row = connection.execute(
                """SELECT * FROM research_v3_command_receipts
                WHERE run_id = ? AND idempotency_key = ?""",
                (run_id, idempotency_key),
            ).fetchone()
            if existing_row is not None:
                existing = self._receipt_from_row(existing_row)
                if existing.command_type != "purge" or existing.request_hash != request_hash:
                    raise ResearchV3ConflictError(
                        "idempotency key was already used for a different command"
                    )
                if run["tombstoned_at"] is not None:
                    return existing, True
                raise ResearchV3IntegrityError("active run has a committed purge command receipt")
            if run["tombstoned_at"] is not None:
                raise ResearchV3ConflictError("run is already tombstoned")
            self._check_state(run, expected_state_version)
            purged_artifact_count = connection.execute(
                """SELECT
                    (SELECT COUNT(*) FROM research_v3_records
                     WHERE run_id = ? AND artifact_id IS NOT NULL)
                    +
                    (SELECT COUNT(*) FROM research_v3_verified_artifacts
                     WHERE run_id = ?)""",
                (run_id, run_id),
            ).fetchone()[0]
            receipt = ResearchCommandReceiptV3(
                run_id=run_id,
                idempotency_key=idempotency_key,
                command_type="purge",
                request_hash=request_hash,
                response_payload={
                    "purged": True,
                    "purged_artifact_count": purged_artifact_count,
                },
                committed_state_version=expected_state_version + 1,
                created_at=purged,
            )
            payload, payload_hash = _encode_model(receipt)
            connection.execute(
                """INSERT INTO research_v3_command_receipts(
                    run_id, idempotency_key, command_type, request_hash,
                    committed_state_version, payload, payload_hash, created_at
                ) VALUES (?, ?, 'purge', ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    idempotency_key,
                    request_hash,
                    receipt.committed_state_version,
                    payload,
                    payload_hash,
                    _iso(purged),
                ),
            )
            connection.execute("DELETE FROM research_v3_records WHERE run_id = ?", (run_id,))
            connection.execute(
                "DELETE FROM research_v3_verified_artifacts WHERE run_id = ?", (run_id,)
            )
            connection.execute("DELETE FROM research_v3_invocations WHERE run_id = ?", (run_id,))
            connection.execute("DELETE FROM research_v3_attempts WHERE run_id = ?", (run_id,))
            connection.execute(
                """DELETE FROM research_v3_command_receipts
                WHERE run_id = ? AND idempotency_key <> ?""",
                (run_id, idempotency_key),
            )
            cursor = connection.execute(
                """UPDATE research_v3_runs SET state_version = state_version + 1, tombstoned_at = ?
                WHERE run_id = ? AND state_version = ? AND tombstoned_at IS NULL""",
                (_iso(purged), run_id, expected_state_version),
            )
            if cursor.rowcount != 1:
                raise ResearchV3ConflictError("research-v3 state version conflict during purge")
            return receipt, False

    def _latest_record_row(
        self,
        connection: sqlite3.Connection,
        *,
        run_id: str,
        record_kind: str,
        schema_version: str,
        model_type: type[_ModelT],
        plan_version_id: str | None = None,
        attempt_id: str | None = None,
    ) -> sqlite3.Row | None:
        rows = self._validated_record_rows(
            connection,
            run_id=run_id,
            record_kind=record_kind,
            schema_version=schema_version,
            model_type=model_type,
        )
        filtered = [
            row
            for row, _value in rows
            if (plan_version_id is None or row["plan_version_id"] == plan_version_id)
            and (attempt_id is None or row["attempt_id"] == attempt_id)
        ]
        return max(
            filtered,
            key=lambda row: (row["sequence_number"] or 0, row["id"]),
            default=None,
        )

    def projection_snapshot(
        self, run_id: Identifier
    ) -> RepositoryProjectionSnapshotV3 | None:
        """Decode one immutable projection input set without scheduling or repairing work."""
        with self._lock:
            run_row = self._select_run(self._connection, run_id)
            if run_row is None:
                return None
            run = self._run_from_row(run_row)
            requirement_row = self._latest_record_row(
                self._connection,
                run_id=run_id,
                record_kind="requirement",
                schema_version="research-task-v3",
                model_type=RequirementVersionV3,
            )
            requirement = (
                self._decode_record_row(
                    requirement_row,
                    expected_kind="requirement",
                    expected_schema="research-task-v3",
                    model_type=RequirementVersionV3,
                )
                if requirement_row is not None
                else None
            )
            candidates = None
            if requirement is not None:
                candidates = self._read_record(
                    self._connection,
                    run_id=run_id,
                    record_kind="candidate_set",
                    natural_key=requirement.id,
                    schema_version="plan-candidates-v3",
                    model_type=PlanCandidateSetV3,
                )
            plan_row = self._latest_record_row(
                self._connection,
                run_id=run_id,
                record_kind="plan",
                schema_version="execution-plan-v3",
                model_type=ExecutionPlanVersionV3,
            )
            plan = (
                self._decode_record_row(
                    plan_row,
                    expected_kind="plan",
                    expected_schema="execution-plan-v3",
                    model_type=ExecutionPlanVersionV3,
                )
                if plan_row is not None
                else None
            )
            if plan is not None and (
                requirement is None or plan.requirement_version_id != requirement.id
            ):
                raise ResearchV3IntegrityError("latest Plan does not bind the latest Requirement")
            approvals: tuple[WorkbenchApprovalV1, ...] = ()
            attempt: ExecutionAttemptV3 | None = None
            actor_results: tuple[ActorExecutionResultV3, ...] = ()
            evidence: tuple[EvidenceManifestArtifactRefV3, EvidenceManifestV3] | None = None
            deliverable: tuple[SealedArtifactRefV3, ResearchDeliverableV3] | None = None
            review: tuple[SealedArtifactRefV3, ReportReviewV3] | None = None
            report: tuple[SealedArtifactRefV3, ReportDocumentV3] | None = None
            verified: tuple[VerifiedArtifactContentV3, ...] = ()
            if plan is not None:
                approval_rows = self._validated_record_rows(
                    self._connection,
                    run_id=run_id,
                    record_kind="approval",
                    schema_version="workbench-approval-v1",
                    model_type=WorkbenchApprovalV1,
                )
                approvals = tuple(
                    value
                    for _row, value in sorted(
                        approval_rows,
                        key=lambda item: item[0]["natural_key"],
                    )
                    if value.plan_version_id == plan.id
                )
                attempt_rows = self._connection.execute(
                    """SELECT * FROM research_v3_attempts WHERE run_id = ?""",
                    (run_id,),
                ).fetchall()
                attempts = tuple(self._attempt_from_row(row) for row in attempt_rows)
                matching_attempts = [
                    value for value in attempts if value.plan_version_id == plan.id
                ]
                attempt = max(
                    matching_attempts,
                    key=lambda value: value.attempt_number,
                    default=None,
                )
                if attempt is not None:
                    actor_results = self.get_actor_results(run_id, plan.id, attempt.attempt_id)
                    evidence_row = self._latest_record_row(
                        self._connection,
                        run_id=run_id,
                        record_kind="evidence_manifest",
                        schema_version="evidence-manifest-v3",
                        model_type=EvidenceManifestV3,
                        plan_version_id=plan.id,
                        attempt_id=attempt.attempt_id,
                    )
                    if evidence_row is not None:
                        evidence_ref = EvidenceManifestArtifactRefV3.model_validate(
                            self._artifact_from_row(evidence_row).model_dump(mode="python")
                        )
                        evidence_value = self._decode_record_row(
                            evidence_row,
                            expected_kind="evidence_manifest",
                            expected_schema="evidence-manifest-v3",
                            model_type=EvidenceManifestV3,
                        )
                        if canonical_json_v3_sha256(evidence_value) != evidence_ref.content_hash:
                            raise ResearchV3IntegrityError(
                                "Evidence Manifest does not match its Artifact hash"
                            )
                        evidence = (evidence_ref, evidence_value)
                        expected_artifact_ids = {
                            item.pointer.artifact.artifact_id for item in evidence_value.evidence
                        }
                        artifact_rows = self._connection.execute(
                            """SELECT * FROM research_v3_verified_artifacts WHERE run_id = ?""",
                            (run_id,),
                        ).fetchall()
                        verified_values = tuple(
                            self._verified_from_row(row) for row in artifact_rows
                        )
                        verified = tuple(
                            value
                            for value in sorted(
                                verified_values,
                                key=lambda item: (item.step_number, item.artifact.artifact_id),
                            )
                            if value.plan_version_id == plan.id
                            and value.attempt_id == attempt.attempt_id
                            and value.artifact.artifact_id in expected_artifact_ids
                        )
                    deliverable = self._projection_artifact(
                        run_id=run_id,
                        plan_version_id=plan.id,
                        attempt_id=attempt.attempt_id,
                        record_kind="deliverable",
                        schema_version="research-deliverable-v3",
                        model_type=ResearchDeliverableV3,
                    )
                    review = self._projection_artifact(
                        run_id=run_id,
                        plan_version_id=plan.id,
                        attempt_id=attempt.attempt_id,
                        record_kind="review",
                        schema_version="report-review-v3",
                        model_type=ReportReviewV3,
                    )
                    report = self._projection_artifact(
                        run_id=run_id,
                        plan_version_id=plan.id,
                        attempt_id=attempt.attempt_id,
                        record_kind="report",
                        schema_version="report-document-v3",
                        model_type=ReportDocumentV3,
                    )
            return RepositoryProjectionSnapshotV3(
                run=run,
                requirement=requirement,
                candidates=candidates,
                selected_plan=plan,
                approvals=approvals,
                attempt=attempt,
                actor_results=actor_results,
                evidence=evidence,
                deliverable=deliverable,
                review=review,
                report=report,
                verified_artifacts=verified,
            )

    def _projection_artifact(
        self,
        *,
        run_id: str,
        plan_version_id: str,
        attempt_id: str,
        record_kind: str,
        schema_version: str,
        model_type: type[_ModelT],
    ) -> tuple[SealedArtifactRefV3, _ModelT] | None:
        row = self._latest_record_row(
            self._connection,
            run_id=run_id,
            record_kind=record_kind,
            schema_version=schema_version,
            model_type=model_type,
            plan_version_id=plan_version_id,
            attempt_id=attempt_id,
        )
        if row is None:
            return None
        artifact = self._artifact_from_row(row)
        value = self._decode_record_row(
            row,
            expected_kind=record_kind,
            expected_schema=schema_version,
            model_type=model_type,
        )
        if canonical_json_v3_sha256(value) != artifact.content_hash:
            raise ResearchV3IntegrityError(f"{record_kind} does not match its Artifact hash")
        return artifact, value

    @staticmethod
    def _verified_from_row(row: sqlite3.Row) -> VerifiedArtifactContentV3:
        value = _decode_model(
            payload=row["payload"],
            payload_hash=row["payload_hash"],
            model_type=VerifiedArtifactContentV3,
            label="verified Actor Artifact",
        )
        if (
            row["artifact_id"],
            row["run_id"],
            row["plan_version_id"],
            row["attempt_id"],
            row["step_number"],
            row["artifact_kind"],
            row["artifact_schema_version"],
            row["artifact_content_hash"],
        ) != (
            value.artifact.artifact_id,
            value.run_id,
            value.plan_version_id,
            value.attempt_id,
            value.step_number,
            value.artifact.kind,
            value.artifact.schema_version,
            value.artifact.content_hash,
        ):
            raise ResearchV3IntegrityError(
                "verified Actor Artifact columns do not match its typed payload"
            )
        return value
