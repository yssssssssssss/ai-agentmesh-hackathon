"""Artifact access seams for v1 legacy and verified DeepSearch data."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentmesh.canonical_json import canonical_json_bytes, canonical_json_sha256, strict_json_loads
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    Artifact,
    ArtifactVerificationState,
    SkillIntent,
    SkillPlanKnowledgeBindings,
    SkillResourceManifestV1,
    SkillSideEffect,
)
from agentmesh.task_routing.contracts import TaskRoutingResult

_HASH_PATTERN = "^[0-9a-f]{64}$"


class ArtifactAccessError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class ArtifactAccessScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: str = Field(min_length=1, max_length=120)
    workspace_id: str = Field(min_length=1, max_length=120)
    project_id: str | None = Field(default=None, max_length=120)
    run_id: str | None = Field(default=None, max_length=120)


class DeepSearchFrozenPlanNodeV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=120)
    skill_id: str = Field(min_length=1, max_length=120)
    skill_version: str = Field(min_length=1, max_length=120)
    skill_content_hash: str = Field(pattern=_HASH_PATTERN)
    reason: str = Field(min_length=1, max_length=1000)
    task_id: str | None = Field(default=None, max_length=120)
    scenario_id: str | None = Field(default=None, max_length=120)
    skill_registry_id: str | None = Field(default=None, max_length=160)
    skill_status: Literal["draft", "reviewed", "validated"] | None = None
    required: bool = True
    depends_on: list[str] = Field(default_factory=list, max_length=6)
    parallel_group: str | None = Field(default=None, max_length=120)
    condition: str | None = Field(default=None, max_length=500)
    question_ids: list[str] = Field(default_factory=list, max_length=100)
    input_bindings: list[str] = Field(default_factory=list, max_length=20)
    output_contract: list[str] = Field(default_factory=list, max_length=20)
    knowledge_bindings: SkillPlanKnowledgeBindings = Field(default_factory=SkillPlanKnowledgeBindings)
    required_tool_names: list[str] = Field(default_factory=list, max_length=20)
    resource_manifest: SkillResourceManifestV1
    completion_criteria: list[str] = Field(default_factory=list, max_length=20)
    side_effect: SkillSideEffect = SkillSideEffect.READ


class DeepSearchFrozenPlanV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["deepsearch-plan-v1"] = "deepsearch-plan-v1"
    requirement_version_id: str = Field(min_length=1, max_length=120)
    requirement_content_hash: str = Field(pattern=_HASH_PATTERN)
    problem_graph_hash: str = Field(pattern=_HASH_PATTERN)
    intent: SkillIntent
    routing_result: TaskRoutingResult | None = None
    candidate_skill_ids: list[str] = Field(default_factory=list, max_length=12)
    output_contract: list[str] = Field(default_factory=list, max_length=20)
    synthesis_output_contract: list[str] = Field(default_factory=list, max_length=20)
    capability_gaps: list[str] = Field(default_factory=list, max_length=100)
    preferred_order: list[str] = Field(default_factory=list, max_length=6)
    nodes: list[DeepSearchFrozenPlanNodeV1] = Field(default_factory=list, max_length=6)


class DeepSearchPlanSnapshotV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["deepsearch-plan-snapshot-v1"]
    run_id: str = Field(min_length=1, max_length=120)
    requirement_version_id: str = Field(min_length=1, max_length=120)
    requirement_content_hash: str = Field(pattern=_HASH_PATTERN)
    plan_id: str = Field(min_length=1, max_length=120)
    plan_version: int = Field(ge=1)
    plan_content_hash: str = Field(pattern=_HASH_PATTERN)
    frozen_plan: DeepSearchFrozenPlanV1

    @model_validator(mode="after")
    def validate_frozen_plan(self) -> DeepSearchPlanSnapshotV1:
        if self.requirement_version_id != self.frozen_plan.requirement_version_id:
            raise ValueError("requirement_version_id does not match frozen_plan")
        if self.requirement_content_hash != self.frozen_plan.requirement_content_hash:
            raise ValueError("requirement_content_hash does not match frozen_plan")
        expected_hash = canonical_json_sha256(self.frozen_plan.model_dump(mode="python"))
        if self.plan_content_hash != expected_hash:
            raise ValueError("plan_content_hash does not match frozen_plan")
        return self


class TrustedEvidenceEnvelopeV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[
        "deepsearch-tool-evidence-v1",
        "deepsearch-user-evidence-v1",
        "deepsearch-knowledge-evidence-v1",
    ]
    origin_type: Literal["tool", "user_input", "knowledge"]
    run_id: str = Field(min_length=1, max_length=120)
    requirement_version_id: str = Field(min_length=1, max_length=120)
    plan_id: str | None = Field(default=None, max_length=120)
    plan_version: int | None = Field(default=None, ge=1)
    node_id: str | None = Field(default=None, max_length=120)
    attempt: int | None = Field(default=None, ge=1)
    tool_name: str | None = Field(default=None, max_length=160)
    tool_implementation_id: str | None = Field(default=None, max_length=160)
    tool_implementation_version: str | None = Field(default=None, max_length=120)
    execution_mode: Literal["real", "fake", "fallback"] | None = None
    content_provider: str | None = Field(default=None, max_length=160)
    tool_call_id: str | None = Field(default=None, max_length=160)
    operation_key: str | None = Field(default=None, max_length=128)
    request_hash: str = Field(pattern=_HASH_PATTERN)
    source_id: str | None = Field(default=None, max_length=160)
    source_ordinal: int | None = Field(default=None, ge=0)
    normalized_reference: str = Field(min_length=1, max_length=4000)
    retrieved_at: datetime
    excerpt: str = Field(max_length=8192)
    content_hash: str = Field(pattern=_HASH_PATTERN)
    size_bytes: int = Field(ge=0, le=8192)

    @model_validator(mode="after")
    def validate_envelope(self) -> TrustedEvidenceEnvelopeV1:
        encoded = self.excerpt.encode("utf-8")
        if self.content_hash != hashlib.sha256(encoded).hexdigest() or self.size_bytes != len(encoded):
            raise ValueError("evidence excerpt hash or size mismatch")
        expected_origin = {
            "deepsearch-tool-evidence-v1": "tool",
            "deepsearch-user-evidence-v1": "user_input",
            "deepsearch-knowledge-evidence-v1": "knowledge",
        }[self.schema_version]
        if self.origin_type != expected_origin:
            raise ValueError("evidence schema and origin_type mismatch")
        if self.origin_type == "tool":
            required = (
                self.plan_id,
                self.plan_version,
                self.node_id,
                self.attempt,
                self.tool_name,
                self.tool_implementation_id,
                self.tool_implementation_version,
                self.tool_call_id,
                self.operation_key,
                self.source_id,
                self.source_ordinal,
            )
            if any(value is None for value in required) or self.execution_mode != "real":
                raise ValueError("tool evidence requires complete real invocation lineage")
        elif any(
            value is not None
            for value in (
                self.plan_id,
                self.plan_version,
                self.node_id,
                self.attempt,
                self.tool_name,
                self.tool_implementation_id,
                self.tool_implementation_version,
                self.execution_mode,
                self.tool_call_id,
                self.operation_key,
                self.source_ordinal,
            )
        ):
            raise ValueError("non-tool evidence cannot carry tool invocation lineage")
        return self


class DeepSearchEvidenceManifestItemV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_item_id: str = Field(min_length=1, max_length=160)
    node_result_id: str = Field(min_length=1, max_length=160)
    evidence_artifact_id: str = Field(min_length=1, max_length=160)
    evidence_artifact_content_hash: str = Field(pattern=_HASH_PATTERN)
    source_id: str | None = Field(default=None, max_length=160)
    origin_type: Literal["tool", "user_input", "knowledge"]
    question_ids: list[str] = Field(default_factory=list, max_length=100)
    success_criterion_ids: list[str] = Field(default_factory=list, max_length=100)


class DeepSearchEvidenceManifestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["deepsearch-evidence-manifest-v1"]
    run_id: str = Field(min_length=1, max_length=120)
    requirement_version_id: str = Field(min_length=1, max_length=120)
    plan_id: str = Field(min_length=1, max_length=120)
    plan_version: int = Field(ge=1)
    plan_content_hash: str = Field(pattern=_HASH_PATTERN)
    items: list[DeepSearchEvidenceManifestItemV1] = Field(min_length=1, max_length=60)

    @model_validator(mode="after")
    def validate_items(self) -> DeepSearchEvidenceManifestV1:
        ids = [item.evidence_item_id for item in self.items]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ValueError("evidence manifest items must be uniquely sorted by evidence_item_id")
        return self


class DeepSearchReportClaimV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=160)
    text: str = Field(min_length=1, max_length=8192)
    node_result_ids: list[str] = Field(default_factory=list, max_length=20)
    evidence_item_ids: list[str] = Field(default_factory=list, max_length=60)
    source_ids: list[str] = Field(default_factory=list, max_length=100)
    question_ids: list[str] = Field(default_factory=list, max_length=100)
    success_criterion_ids: list[str] = Field(default_factory=list, max_length=100)
    recommendation: bool = False


class DeepSearchReportSectionV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    section_id: str = Field(min_length=1, max_length=160)
    server_heading: str = Field(min_length=1, max_length=500)
    claim_ids: list[str] = Field(default_factory=list, max_length=100)


class DeepSearchReportSourceV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=500)
    normalized_reference: str = Field(min_length=1, max_length=4000)
    content_hash: str = Field(pattern=_HASH_PATTERN)


class DeepSearchReportLimitationV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1, max_length=160)
    related_ids: list[str] = Field(default_factory=list, max_length=100)
    description: str = Field(min_length=1, max_length=2000)


class DeepSearchReportV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["deepsearch-report-v1"]
    run_id: str = Field(min_length=1, max_length=120)
    requirement_version_id: str = Field(min_length=1, max_length=120)
    plan_id: str = Field(min_length=1, max_length=120)
    plan_version: int = Field(ge=1)
    requirement_content_hash: str = Field(pattern=_HASH_PATTERN)
    problem_graph_hash: str = Field(pattern=_HASH_PATTERN)
    plan_content_hash: str = Field(pattern=_HASH_PATTERN)
    evidence_manifest_hash: str = Field(pattern=_HASH_PATTERN)
    synthesis_content_hash: str = Field(pattern=_HASH_PATTERN)
    review_outcome: Literal["not_run", "pass", "revise", "block", "error"]
    review_reason_code: str | None = Field(default=None, max_length=160)
    report_status: Literal["complete", "partial"]
    title: str = Field(min_length=1, max_length=500)
    claims: list[DeepSearchReportClaimV1] = Field(default_factory=list, max_length=100)
    executive_summary_claim_ids: list[str] = Field(default_factory=list, max_length=100)
    sections: list[DeepSearchReportSectionV1] = Field(default_factory=list, max_length=100)
    sources: list[DeepSearchReportSourceV1] = Field(default_factory=list, max_length=100)
    limitations: list[DeepSearchReportLimitationV1] = Field(default_factory=list, max_length=100)
    rendered_text: str = Field(max_length=262144)

    @model_validator(mode="after")
    def validate_review_reason(self) -> DeepSearchReportV1:
        if self.review_outcome in {"pass", "revise", "block"} and self.review_reason_code is not None:
            raise ValueError("review verdicts cannot carry a reason code")
        if self.review_outcome in {"not_run", "error"} and not self.review_reason_code:
            raise ValueError("review non-verdict outcomes require a reason code")
        claim_ids = [claim.id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("report claim IDs must be unique")
        if any(
            not claim.evidence_item_ids
            or not claim.question_ids
            or any(
                len(values) != len(set(values))
                for values in (
                    claim.node_result_ids,
                    claim.evidence_item_ids,
                    claim.source_ids,
                    claim.question_ids,
                    claim.success_criterion_ids,
                )
            )
            for claim in self.claims
        ):
            raise ValueError("report claims require unique evidence and question references")
        if (
            len(self.executive_summary_claim_ids)
            != len(set(self.executive_summary_claim_ids))
            or not set(self.executive_summary_claim_ids).issubset(claim_ids)
        ):
            raise ValueError("report executive summary references unknown or duplicate claims")
        section_ids = [section.section_id for section in self.sections]
        section_claim_ids = [
            claim_id for section in self.sections for claim_id in section.claim_ids
        ]
        if (
            len(section_ids) != len(set(section_ids))
            or any(
                len(section.claim_ids) != len(set(section.claim_ids))
                for section in self.sections
            )
            or not set(section_claim_ids).issubset(claim_ids)
            or set(section_claim_ids) != set(claim_ids)
        ):
            raise ValueError("report sections must cover every claim with known references")
        source_ids = [source.source_id for source in self.sources]
        referenced_source_ids = {
            source_id for claim in self.claims for source_id in claim.source_ids
        }
        if len(source_ids) != len(set(source_ids)) or set(source_ids) != referenced_source_ids:
            raise ValueError("report sources must exactly match claim references")
        limitation_codes = [item.code for item in self.limitations]
        if len(limitation_codes) != len(set(limitation_codes)) or any(
            len(item.related_ids) != len(set(item.related_ids))
            for item in self.limitations
        ):
            raise ValueError("report limitations must be unique")
        if self.report_status == "partial" and not self.limitations:
            raise ValueError("partial reports require an explicit limitation")
        if not self.rendered_text.strip():
            raise ValueError("report rendered_text must not be empty")
        return self


class DeepSearchArtifactSchemaRegistry:
    """Frozen mapping from Artifact identity to its strict content contract."""

    _schemas: dict[tuple[str, str], type[BaseModel]] = {
        ("deepsearch_plan_snapshot", "deepsearch-plan-snapshot-v1"): DeepSearchPlanSnapshotV1,
        ("deepsearch_tool_evidence", "deepsearch-tool-evidence-v1"): TrustedEvidenceEnvelopeV1,
        ("deepsearch_user_evidence", "deepsearch-user-evidence-v1"): TrustedEvidenceEnvelopeV1,
        ("deepsearch_knowledge_evidence", "deepsearch-knowledge-evidence-v1"): TrustedEvidenceEnvelopeV1,
        ("deepsearch_evidence_manifest", "deepsearch-evidence-manifest-v1"): DeepSearchEvidenceManifestV1,
        ("deepsearch_report", "deepsearch-report-v1"): DeepSearchReportV1,
    }

    @classmethod
    def contains(cls, artifact_type: str | None, schema_version: str | None) -> bool:
        return (artifact_type, schema_version) in cls._schemas

    @classmethod
    def parse(cls, artifact_type: str, schema_version: str, content: str) -> BaseModel:
        model = cls._schemas.get((artifact_type, schema_version))
        if model is None:
            raise ArtifactAccessError("artifact_integrity_failed")
        try:
            payload = strict_json_loads(content)
            if canonical_json_bytes(payload).decode("utf-8") != content:
                raise ValueError("Artifact JSON is not canonical")
            parsed = model.model_validate(payload)
            if getattr(parsed, "schema_version", None) != schema_version:
                raise ValueError("Artifact content schema does not match its envelope")
            return parsed
        except (TypeError, ValueError):
            raise ArtifactAccessError("artifact_integrity_failed") from None


class ArtifactRepository(Protocol):
    def _connect(self) -> sqlite3.Connection: ...

    def _read_connect(self) -> sqlite3.Connection: ...


_INDEXED_ARTIFACT_FIELDS = (
    "id",
    "run_id",
    "workspace_id",
    "project_id",
    "user_id",
    "artifact_type",
    "content_type",
    "truncated",
    "verification_state",
    "schema_version",
    "content_hash",
    "size_bytes",
    "requirement_version_id",
    "plan_version_id",
    "attempt_id",
    "step_number",
    "purged_at",
    "purged_by",
    "created_at",
    "updated_at",
)


def _serialized(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _strict_mapping(raw: str) -> dict[str, Any]:
    try:
        value = strict_json_loads(raw)
    except (TypeError, ValueError):
        raise ArtifactAccessError("artifact_integrity_failed") from None
    if not isinstance(value, dict):
        raise ArtifactAccessError("artifact_integrity_failed")
    return value


def _row_payload_matches_indexes(row: sqlite3.Row, payload: dict[str, Any]) -> bool:
    for field in _INDEXED_ARTIFACT_FIELDS:
        expected = payload.get(field)
        if field == "truncated":
            expected = int(bool(expected))
        elif field in {"created_at", "updated_at", "purged_at"} and expected is not None:
            try:
                indexed = datetime.fromisoformat(str(row[field]).replace("Z", "+00:00"))
                expected = datetime.fromisoformat(str(expected).replace("Z", "+00:00"))
            except ValueError:
                return False
            if indexed != expected:
                return False
            continue
        if row[field] != expected:
            return False
    return True


def _validate_verified_outer_artifact(
    artifact: Artifact,
    run: AgentRun,
    *,
    enforce_writable_state: bool = False,
) -> None:
    if (
        run.orchestration_version != "v1"
        or run.planning_mode != AgentPlanningMode.DEEPSEARCH
        or artifact.run_id != run.id
        or artifact.user_id != run.user_id
        or artifact.workspace_id != run.workspace_id
        or artifact.project_id != run.project_id
        or artifact.content_type != "application/json"
        or artifact.truncated
        or not DeepSearchArtifactSchemaRegistry.contains(artifact.artifact_type, artifact.schema_version)
        or artifact.requirement_version_id is None
    ):
        raise ArtifactAccessError("artifact_integrity_failed")

    requires_plan = artifact.artifact_type in {
        "deepsearch_plan_snapshot",
        "deepsearch_tool_evidence",
        "deepsearch_evidence_manifest",
        "deepsearch_report",
    }
    if requires_plan != (artifact.plan_version_id is not None):
        raise ArtifactAccessError("artifact_integrity_failed")

    is_tool_evidence = artifact.artifact_type == "deepsearch_tool_evidence"
    if is_tool_evidence != (artifact.attempt_id is not None and artifact.step_number is not None):
        raise ArtifactAccessError("artifact_integrity_failed")
    if not is_tool_evidence and (artifact.attempt_id is not None or artifact.step_number is not None):
        raise ArtifactAccessError("artifact_integrity_failed")

    state = artifact.verification_state
    if state not in {
        ArtifactVerificationState.STAGING,
        ArtifactVerificationState.SEALED,
        ArtifactVerificationState.FAILED,
        ArtifactVerificationState.PURGED,
    }:
        raise ArtifactAccessError("artifact_integrity_failed")
    if not enforce_writable_state:
        return
    if state == ArtifactVerificationState.SEALED:
        if artifact.purged_at is not None or artifact.purged_by is not None:
            raise ArtifactAccessError("artifact_integrity_failed")
        return
    if state in {ArtifactVerificationState.STAGING, ArtifactVerificationState.FAILED}:
        if (
            artifact.artifact_type != "deepsearch_report"
            or artifact.content
            or artifact.content_hash is not None
            or artifact.size_bytes is not None
            or artifact.purged_at is not None
            or artifact.purged_by is not None
        ):
            raise ArtifactAccessError("artifact_integrity_failed")
        return
    if state == ArtifactVerificationState.PURGED:
        if not artifact.purged_at or not artifact.purged_by or artifact.content:
            raise ArtifactAccessError("artifact_integrity_failed")
        return
    raise ArtifactAccessError("artifact_integrity_failed")


def _verified_artifact_from_row(row: sqlite3.Row, run: AgentRun) -> Artifact:
    payload = _strict_mapping(row["payload"])
    if set(payload) != set(Artifact.model_fields) or not _row_payload_matches_indexes(row, payload):
        raise ArtifactAccessError("artifact_integrity_failed")
    validation_payload = payload
    if payload.get("verification_state") in {
        ArtifactVerificationState.STAGING.value,
        ArtifactVerificationState.PURGED.value,
    }:
        validation_payload = {**payload, "content": ""}
    try:
        artifact = Artifact.model_validate(validation_payload)
    except (TypeError, ValueError):
        raise ArtifactAccessError("artifact_integrity_failed") from None
    _validate_verified_outer_artifact(artifact, run)
    return artifact


def _owned_run(row: sqlite3.Row, reader_scope: ArtifactAccessScope) -> AgentRun:
    try:
        run = AgentRun.model_validate_json(row["run_payload"])
    except (TypeError, ValueError):
        raise ArtifactAccessError("artifact_integrity_failed") from None
    if (
        run.id != row["run_id"]
        or run.user_id != reader_scope.user_id
        or run.workspace_id != reader_scope.workspace_id
        or (reader_scope.project_id is not None and run.project_id != reader_scope.project_id)
        or (reader_scope.run_id is not None and run.id != reader_scope.run_id)
    ):
        raise ArtifactAccessError("artifact_not_found")
    return run


def _artifact_row(repository: ArtifactRepository, artifact_id: str) -> sqlite3.Row:
    with repository._read_connect() as connection:
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
        raise ArtifactAccessError("artifact_not_found")
    return row


def resolve_artifact_runtime(
    repository: ArtifactRepository,
    artifact_id: str,
    *,
    reader_scope: ArtifactAccessScope,
) -> Literal["v1_legacy", "v1_verified", "research-v2"]:
    row = _artifact_row(repository, artifact_id)
    run = _owned_run(row, reader_scope)
    if row["run_orchestration_version"] != run.orchestration_version:
        raise ArtifactAccessError("artifact_integrity_failed")
    if run.orchestration_version == "research-v2":
        return "research-v2"
    if run.orchestration_version != "v1":
        raise ArtifactAccessError("artifact_integrity_failed")
    if row["verification_state"] is None:
        return "v1_legacy"
    _verified_artifact_from_row(row, run)
    return "v1_verified"


class V1ArtifactReader:
    def __init__(self, repository: ArtifactRepository) -> None:
        self.repository = repository

    def read_for_owner(
        self,
        artifact_id: str,
        *,
        reader_scope: ArtifactAccessScope,
    ) -> Artifact:
        runtime = resolve_artifact_runtime(self.repository, artifact_id, reader_scope=reader_scope)
        if runtime == "research-v2":
            raise ArtifactAccessError("artifact_integrity_failed")
        row = _artifact_row(self.repository, artifact_id)
        run = _owned_run(row, reader_scope)
        if runtime == "v1_legacy":
            try:
                artifact = Artifact.model_validate_json(row["payload"])
            except (TypeError, ValueError):
                raise ArtifactAccessError("artifact_integrity_failed") from None
            if (
                artifact.verification_state is not None
                or artifact.run_id != run.id
                or artifact.user_id != run.user_id
                or artifact.workspace_id != run.workspace_id
                or artifact.project_id != run.project_id
            ):
                raise ArtifactAccessError("artifact_integrity_failed")
            return artifact

        artifact = _verified_artifact_from_row(row, run)
        state = artifact.verification_state.value if artifact.verification_state is not None else None
        error_by_state = {
            ArtifactVerificationState.STAGING.value: "artifact_not_ready",
            ArtifactVerificationState.FAILED.value: "artifact_invalid",
            ArtifactVerificationState.PURGED.value: "artifact_purged",
        }
        if state != ArtifactVerificationState.SEALED.value:
            raise ArtifactAccessError(error_by_state.get(state, "artifact_integrity_failed"))
        content_bytes = artifact.content.encode("utf-8")
        if (
            artifact.content_hash != hashlib.sha256(content_bytes).hexdigest()
            or artifact.size_bytes != len(content_bytes)
        ):
            raise ArtifactAccessError("artifact_integrity_failed")
        parsed = DeepSearchArtifactSchemaRegistry.parse(
            artifact.artifact_type,
            artifact.schema_version or "",
            artifact.content,
        )
        _validate_content_lineage(artifact, parsed)
        return artifact


def _validate_content_lineage(artifact: Artifact, parsed: BaseModel) -> None:
    if getattr(parsed, "run_id", None) != artifact.run_id:
        raise ArtifactAccessError("artifact_integrity_failed")
    if getattr(parsed, "requirement_version_id", None) != artifact.requirement_version_id:
        raise ArtifactAccessError("artifact_integrity_failed")
    plan_id = getattr(parsed, "plan_id", None)
    plan_version = getattr(parsed, "plan_version", None)
    expected_plan_version_id = f"{plan_id}:v{plan_version}" if plan_id is not None else None
    if artifact.plan_version_id != expected_plan_version_id:
        raise ArtifactAccessError("artifact_integrity_failed")
    node_id = getattr(parsed, "node_id", None)
    attempt = getattr(parsed, "attempt", None)
    expected_attempt_id = f"{node_id}:attempt:{attempt}" if node_id is not None else None
    if artifact.attempt_id != expected_attempt_id:
        raise ArtifactAccessError("artifact_integrity_failed")


class V1VerifiedArtifactStore:
    def __init__(self, repository: ArtifactRepository) -> None:
        self.repository = repository

    def insert_sealed(
        self,
        artifact: Artifact,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> Artifact:
        if artifact.verification_state != ArtifactVerificationState.SEALED:
            raise ArtifactAccessError("artifact_state_transition_invalid")
        if artifact.artifact_type == "deepsearch_report":
            raise ArtifactAccessError("artifact_state_transition_invalid")
        with self._write_connection(connection) as current:
            validated, _run = self._validate_artifact(artifact, parse_content=True, connection=current)
            return self._insert(validated, connection=current)

    def create_staging_report(
        self,
        artifact: Artifact,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> Artifact:
        if (
            artifact.artifact_type != "deepsearch_report"
            or artifact.verification_state != ArtifactVerificationState.STAGING
            or artifact.content
            or artifact.content_hash is not None
            or artifact.size_bytes is not None
        ):
            raise ArtifactAccessError("artifact_state_transition_invalid")
        with self._write_connection(connection) as current:
            validated, _run = self._validate_artifact(artifact, parse_content=False, connection=current)
            return self._insert(validated, connection=current)

    def seal_report(
        self,
        artifact: Artifact,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> Artifact:
        if artifact.artifact_type != "deepsearch_report" or artifact.verification_state != ArtifactVerificationState.SEALED:
            raise ArtifactAccessError("artifact_state_transition_invalid")
        with self._write_connection(connection) as current:
            validated, run = self._validate_artifact(artifact, parse_content=True, connection=current)
            return self._transition_report(
                validated,
                run=run,
                expected_state=ArtifactVerificationState.STAGING,
                connection=current,
            )

    def fail_report(
        self,
        artifact: Artifact,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> Artifact:
        if (
            artifact.artifact_type != "deepsearch_report"
            or artifact.verification_state != ArtifactVerificationState.FAILED
            or artifact.content
            or artifact.content_hash is not None
            or artifact.size_bytes is not None
        ):
            raise ArtifactAccessError("artifact_state_transition_invalid")
        with self._write_connection(connection) as current:
            validated, run = self._validate_artifact(artifact, parse_content=False, connection=current)
            return self._transition_report(
                validated,
                run=run,
                expected_state=ArtifactVerificationState.STAGING,
                connection=current,
            )

    @contextmanager
    def _write_connection(self, connection: sqlite3.Connection | None):
        if connection is not None:
            yield connection
            return
        with self.repository._connect() as owned:
            owned.execute("BEGIN IMMEDIATE")
            yield owned

    def _validate_artifact(
        self,
        artifact: Artifact,
        *,
        parse_content: bool,
        connection: sqlite3.Connection | None,
    ) -> tuple[Artifact, AgentRun]:
        try:
            artifact = Artifact.model_validate(artifact.model_dump(mode="python"))
        except (TypeError, ValueError):
            raise ArtifactAccessError("artifact_integrity_failed") from None
        with self._read_or_caller_connection(connection) as current:
            row = current.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (artifact.run_id,),
            ).fetchone()
        if row is None:
            raise ArtifactAccessError("artifact_integrity_failed")
        try:
            run = AgentRun.model_validate_json(row["payload"])
        except (TypeError, ValueError):
            raise ArtifactAccessError("artifact_integrity_failed") from None
        if (
            row["orchestration_version"] != "v1"
            or run.orchestration_version != "v1"
            or run.planning_mode != AgentPlanningMode.DEEPSEARCH
            or run.user_id != artifact.user_id
            or run.workspace_id != artifact.workspace_id
            or run.project_id != artifact.project_id
        ):
            raise ArtifactAccessError("artifact_integrity_failed")
        _validate_verified_outer_artifact(artifact, run, enforce_writable_state=True)
        if parse_content:
            content_bytes = artifact.content.encode("utf-8")
            if (
                artifact.content_hash != hashlib.sha256(content_bytes).hexdigest()
                or artifact.size_bytes != len(content_bytes)
            ):
                raise ArtifactAccessError("artifact_integrity_failed")
            parsed = DeepSearchArtifactSchemaRegistry.parse(
                artifact.artifact_type,
                artifact.schema_version or "",
                artifact.content,
            )
            _validate_content_lineage(artifact, parsed)
        return artifact, run

    @contextmanager
    def _read_or_caller_connection(self, connection: sqlite3.Connection | None):
        if connection is not None:
            yield connection
            return
        with self.repository._read_connect() as owned:
            yield owned

    def _insert(self, artifact: Artifact, *, connection: sqlite3.Connection | None) -> Artifact:
        with self._write_connection(connection) as current:
            existing = current.execute("SELECT * FROM artifacts WHERE id = ?", (artifact.id,)).fetchone()
            if existing is not None:
                return self._exact_replay(existing, artifact)
            self._insert_row(current, artifact)
        return artifact

    def _transition_report(
        self,
        artifact: Artifact,
        *,
        run: AgentRun,
        expected_state: ArtifactVerificationState,
        connection: sqlite3.Connection | None,
    ) -> Artifact:
        with self._write_connection(connection) as current:
            existing = current.execute("SELECT * FROM artifacts WHERE id = ?", (artifact.id,)).fetchone()
            if existing is None:
                raise ArtifactAccessError("artifact_state_transition_invalid")
            if existing["verification_state"] == artifact.verification_state.value:
                return self._exact_replay(existing, artifact)
            if existing["verification_state"] != expected_state.value:
                raise ArtifactAccessError("artifact_state_transition_invalid")
            existing_artifact = _verified_artifact_from_row(existing, run)
            if existing_artifact.verification_state != expected_state:
                raise ArtifactAccessError("artifact_integrity_failed")
            existing_payload = existing_artifact.model_dump(mode="json")
            immutable_fields = (
                "id",
                "run_id",
                "workspace_id",
                "project_id",
                "user_id",
                "artifact_type",
                "content_type",
                "truncated",
                "schema_version",
                "requirement_version_id",
                "plan_version_id",
                "attempt_id",
                "step_number",
                "created_at",
            )
            target_payload = artifact.model_dump(mode="json")
            if any(existing_payload.get(field) != target_payload.get(field) for field in immutable_fields):
                raise ArtifactAccessError("artifact_identity_conflict")
            cursor = current.execute(
                """
                UPDATE artifacts SET
                    payload = ?, verification_state = ?, content_hash = ?, size_bytes = ?,
                    purged_at = ?, purged_by = ?, updated_at = ?
                WHERE id = ? AND verification_state = ?
                """,
                (
                    artifact.model_dump_json(),
                    artifact.verification_state.value,
                    artifact.content_hash,
                    artifact.size_bytes,
                    artifact.purged_at.isoformat() if artifact.purged_at is not None else None,
                    artifact.purged_by,
                    artifact.updated_at.isoformat() if artifact.updated_at is not None else None,
                    artifact.id,
                    expected_state.value,
                ),
            )
            if cursor.rowcount != 1:
                raise ArtifactAccessError("artifact_state_transition_invalid")
        return artifact

    @staticmethod
    def _exact_replay(row: sqlite3.Row, artifact: Artifact) -> Artifact:
        payload = _strict_mapping(row["payload"])
        if payload != artifact.model_dump(mode="json") or not _row_payload_matches_indexes(row, payload):
            raise ArtifactAccessError("artifact_identity_conflict")
        return Artifact.model_validate(payload)

    @staticmethod
    def _insert_row(connection: sqlite3.Connection, artifact: Artifact) -> None:
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
                artifact.purged_at.isoformat() if artifact.purged_at is not None else None,
                artifact.purged_by,
                artifact.updated_at.isoformat() if artifact.updated_at is not None else None,
            ),
        )
