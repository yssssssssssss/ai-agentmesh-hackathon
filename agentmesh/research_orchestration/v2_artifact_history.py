"""Read-only Artifact access required by historical research-v2 projections."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentmesh.models import AgentRun, Artifact, ArtifactVerificationState
from agentmesh.research_orchestration.contracts import ModelCallReceipt, canonical_json_bytes


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


class ResearchResultSnapshot(BaseModel):
    """Verified IDs and provenance used by the read-only research projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_manifest_id: str | None = None
    claim_ledger_id: str | None = None
    deliverable_id: str | None = None
    review_id: str | None = None
    report_id: str | None = None
    gap_codes: list[str] = Field(default_factory=list, max_length=100)
    actual_model: str | None = Field(default=None, max_length=120)
    integrity_errors: list[str] = Field(default_factory=list, max_length=20)


class ArtifactHistoryRepository(Protocol):
    def _read_connect(self) -> sqlite3.Connection: ...


def _reject_duplicate_keys(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def strict_json(raw: str) -> Any:
    return json.loads(
        raw,
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_json_constant,
    )


class V2ArtifactHistoryReader:
    """Verify and return persisted Artifacts without mutating durable state."""

    def __init__(self, repository: ArtifactHistoryRepository) -> None:
        self.repository = repository

    def read_verified_for_owner(
        self,
        artifact_id: str,
        *,
        reader_scope: ArtifactReaderScope,
        expected_reference: ArtifactRef | None = None,
        invalidate_corrupt: bool = True,
    ) -> Artifact:
        if expected_reference is not None and expected_reference.artifact_id != artifact_id:
            raise ArtifactStoreError("artifact_reference_mismatch")
        artifact, verified = self.read_for_owner(
            artifact_id,
            reader_scope=reader_scope,
            expected_reference=expected_reference,
            invalidate_corrupt=invalidate_corrupt,
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
        invalidate_corrupt: bool = True,
    ) -> tuple[Artifact, bool]:
        if expected_reference is not None and expected_reference.artifact_id != artifact_id:
            raise ArtifactStoreError("artifact_reference_mismatch")
        with self.repository._read_connect() as connection:
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
        run = self._owned_run(row, expected_run_id=str(row["run_id"]), reader_scope=reader_scope)
        if run is None:
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
            invalidate_corrupt=invalidate_corrupt,
        )
        return artifact, True

    def research_result_snapshot(
        self,
        *,
        run_id: str,
        attempt_id: str | None,
        reader_scope: ArtifactReaderScope,
    ) -> ResearchResultSnapshot:
        """Return only result Artifacts that still pass owner and hash verification."""

        if attempt_id is None:
            return ResearchResultSnapshot()
        kinds = ("evidence_manifest", "claim_ledger", "deliverable", "review", "report")
        placeholders = ",".join("?" for _ in kinds)
        with self.repository._read_connect() as connection:
            run_row = connection.execute(
                """SELECT payload AS run_payload,
                          orchestration_version AS run_orchestration_version
                FROM agent_runs WHERE id = ?""",
                (run_id,),
            ).fetchone()
            if self._owned_run(run_row, expected_run_id=run_id, reader_scope=reader_scope) is None:
                return ResearchResultSnapshot()
            rows = connection.execute(
                f"""
                SELECT id, artifact_type FROM artifacts
                WHERE run_id = ? AND attempt_id = ?
                  AND artifact_type IN ({placeholders})
                ORDER BY created_at, id
                """,
                (run_id, attempt_id, *kinds),
            ).fetchall()
            receipt_rows = connection.execute(
                """
                SELECT payload FROM research_model_call_receipts
                WHERE run_id = ? AND owner_kind = 'attempt' AND owner_id = ?
                  AND stage = 'competitive-analysis'
                ORDER BY created_at, id
                """,
                (run_id, attempt_id),
            ).fetchall()

        verified: dict[str, Artifact] = {}
        errors: list[str] = []
        scoped_reader = reader_scope.model_copy(update={"run_id": run_id})
        for row in rows:
            kind = str(row["artifact_type"])
            try:
                artifact, is_verified = self.read_for_owner(
                    str(row["id"]),
                    reader_scope=scoped_reader,
                    invalidate_corrupt=False,
                )
            except ArtifactStoreError as error:
                errors.append(f"{kind}:{error.code}")
                continue
            if not is_verified or artifact.attempt_id != attempt_id or artifact.artifact_type != kind:
                errors.append(f"{kind}:artifact_reference_mismatch")
                continue
            if kind in verified:
                errors.append(f"{kind}:artifact_duplicate")
                continue
            verified[kind] = artifact

        gap_codes: list[str] = []
        manifest = verified.get("evidence_manifest")
        if manifest is not None:
            from agentmesh.research_orchestration.evidence import EvidenceManifest

            try:
                parsed_manifest = EvidenceManifest.model_validate_json(manifest.content)
            except (RecursionError, TypeError, ValueError):
                errors.append("evidence_manifest:artifact_payload_invalid")
                verified.pop("evidence_manifest", None)
            else:
                gap_codes = [item.value for item in parsed_manifest.gap_codes]

        actual_model = None
        for row in receipt_rows:
            try:
                receipt = ModelCallReceipt.model_validate_json(row["payload"])
            except (RecursionError, TypeError, ValueError):
                errors.append("model_receipt:payload_invalid")
                continue
            if receipt.run_id != run_id or receipt.owner_id != attempt_id:
                errors.append("model_receipt:lineage_invalid")
                continue
            actual_model = receipt.actual_model

        if any(kind not in verified for kind in ("evidence_manifest", "claim_ledger", "deliverable", "review")):
            verified.pop("report", None)

        return ResearchResultSnapshot(
            evidence_manifest_id=verified.get("evidence_manifest").id if verified.get("evidence_manifest") else None,
            claim_ledger_id=verified.get("claim_ledger").id if verified.get("claim_ledger") else None,
            deliverable_id=verified.get("deliverable").id if verified.get("deliverable") else None,
            review_id=verified.get("review").id if verified.get("review") else None,
            report_id=verified.get("report").id if verified.get("report") else None,
            gap_codes=list(dict.fromkeys(gap_codes)),
            actual_model=actual_model,
            integrity_errors=list(dict.fromkeys(errors)),
        )

    @staticmethod
    def _owned_run(
        row: sqlite3.Row | None,
        *,
        expected_run_id: str,
        reader_scope: ArtifactReaderScope,
    ) -> AgentRun | None:
        if row is None:
            return None
        try:
            run = AgentRun.model_validate_json(row["run_payload"])
        except (RecursionError, TypeError, ValueError):
            return None
        if (
            row["run_orchestration_version"] != run.orchestration_version
            or run.id != expected_run_id
            or run.user_id != reader_scope.user_id
            or run.workspace_id != reader_scope.workspace_id
            or (reader_scope.project_id is not None and run.project_id != reader_scope.project_id)
            or (reader_scope.run_id is not None and run.id != reader_scope.run_id)
        ):
            return None
        return run

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
        invalidate_corrupt: bool = True,
    ) -> Artifact:
        if row is None:
            raise ArtifactStoreError("artifact_not_found")
        reason, artifact = self._integrity_result(row)
        if reason is not None or artifact is None:
            if invalidate_corrupt:
                self._handle_corrupt(
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

    def _handle_corrupt(
        self,
        artifact_id: str,
        reason: str,
        *,
        fallback_lineage: ArtifactLineage | None = None,
        fallback_run: AgentRun | None = None,
    ) -> None:
        """Extension hook for the writable compatibility Store; history reads do nothing."""

        del artifact_id, reason, fallback_lineage, fallback_run

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
                canonical = canonical_json_bytes(strict_json(artifact.content)).decode("utf-8")
            except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
                return "artifact_json_invalid", artifact
            if canonical != artifact.content:
                return "artifact_json_not_canonical", artifact
        return None, artifact

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
            and row["purged_at"] == (artifact.purged_at.isoformat() if artifact.purged_at is not None else None)
            and row["purged_by"] == artifact.purged_by
            and row["created_at"] == artifact.created_at.isoformat()
            and row["updated_at"] == (artifact.updated_at.isoformat() if artifact.updated_at is not None else None)
        )
