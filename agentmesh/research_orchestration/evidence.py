from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal
from urllib.parse import SplitResult, urlsplit, urlunsplit

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentmesh.research_orchestration.artifacts import (
    ArtifactDraft,
    ArtifactLease,
    ArtifactLineage,
    ArtifactRef,
    ArtifactStore,
    ArtifactStoreError,
)
from agentmesh.research_orchestration.compiler import PlanCompileError, validate_execution_plan_version
from agentmesh.research_orchestration.contracts import (
    ExecutionPlanVersion,
    InvocationState,
    Sha256Hex,
    ToolInvocation,
    ToolReceipt,
    canonical_sha256,
)
from agentmesh.risk import RiskDecision, assess_external_content
from agentmesh.store import ResearchStoreConflict

MAX_EVIDENCE_QUOTE_BYTES = 8 * 1024
TOOL_RESULT_KIND = "tool_result"
TOOL_RESULT_SCHEMA_V1 = "web-research-output-v1"
TOOL_RESULT_SCHEMA_V2 = "web-research-output-v2"
TOOL_RESULT_SCHEMA = TOOL_RESULT_SCHEMA_V2
SUPPORTED_TOOL_RESULT_SCHEMAS = frozenset({TOOL_RESULT_SCHEMA_V1, TOOL_RESULT_SCHEMA_V2})
EVIDENCE_SOURCE_KIND = "evidence_source"
EVIDENCE_SOURCE_SCHEMA = "evidence-source-v1"
EVIDENCE_MANIFEST_KIND = "evidence_manifest"
EVIDENCE_MANIFEST_SCHEMA = "evidence-manifest-v1"


def _tool_output_schema_for_version(schema: object, schema_version: str) -> object:
    if schema_version != TOOL_RESULT_SCHEMA_V1:
        return schema
    legacy_schema = copy.deepcopy(schema)
    if isinstance(legacy_schema, dict) and isinstance(legacy_schema.get("required"), list):
        legacy_schema["required"] = [
            item
            for item in legacy_schema["required"]
            if item not in {"source_evidence", "provider_calls"}
        ]
    return legacy_schema


class EvidenceError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class EvidenceRiskFlag(StrEnum):
    PROMPT_INJECTION_SUSPECTED = "prompt_injection_suspected"
    TRUNCATED = "truncated"


class EvidenceGapCode(StrEnum):
    NO_SOURCES = "no_sources"
    INSUFFICIENT_SOURCES = "insufficient_sources"
    INSUFFICIENT_INDEPENDENT_SOURCES = "insufficient_independent_sources"
    PROMPT_INJECTION_SUSPECTED = "prompt_injection_suspected"
    TRUNCATED_PROVIDER_SUMMARY = "truncated_provider_summary"


class ProviderSourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=2000)
    canonical_url: str = Field(min_length=1, max_length=2000)
    retrieved_at: datetime
    evidence_pointer: str = Field(pattern=r"^/sources/[0-9]+$", max_length=1000)
    origin_pointer: str = Field(min_length=1, max_length=1000)
    redirect_chain: list[str] = Field(default_factory=list, max_length=10)
    freshness: Literal["unknown"] = "unknown"
    independent_group: str = Field(min_length=1, max_length=253)

    @field_validator("retrieved_at")
    @classmethod
    def require_aware_retrieval_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("source retrieval time must be timezone-aware")
        return value


class EvidenceSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default=EVIDENCE_SOURCE_SCHEMA, pattern="^evidence-source-v1$")
    evidence_id: str = Field(pattern="^evidence_[a-z0-9]+$", max_length=120)
    evidence_class: str = Field(default="provider_summary", pattern="^provider_summary$")
    source_tier: str = Field(default="provider_summary", pattern="^provider_summary$")
    provider: str = Field(min_length=1, max_length=120)
    content_provider: str | None = Field(default=None, min_length=1, max_length=120)
    question_ids: list[str] = Field(default_factory=list, max_length=20)
    quote: str = Field(min_length=1)
    evidence_pointer: str = Field(default="/quote", pattern="^/quote$")
    quote_origin_pointer: str = Field(
        default="/content",
        pattern=r"^/(?:content|source_evidence/[0-9]+/excerpt)$",
    )
    quote_truncated: bool = False
    sources: list[ProviderSourceRef] = Field(min_length=1, max_length=20)
    origin_artifact: ArtifactRef
    tool_invocation_id: str = Field(min_length=1, max_length=120)
    operation_key: Sha256Hex
    receipt: ToolReceipt
    authorization_scope: str = Field(min_length=1, max_length=80)
    applicable_scope: dict[str, str]
    conflict_status: Literal["unknown", "none", "possible", "conflicting"] = "unknown"
    risk_flags: list[EvidenceRiskFlag] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_source_bundle(self) -> EvidenceSource:
        if len(self.quote.encode("utf-8")) > MAX_EVIDENCE_QUOTE_BYTES:
            raise ValueError("Evidence quote exceeds the byte limit")
        source_ids = [source.source_id for source in self.sources]
        origin_pointers = [source.origin_pointer for source in self.sources]
        evidence_pointers = [source.evidence_pointer for source in self.sources]
        if (
            len(source_ids) != len(set(source_ids))
            or len(origin_pointers) != len(set(origin_pointers))
            or len(evidence_pointers) != len(set(evidence_pointers))
        ):
            raise ValueError("Evidence sources must have unique identities and pointers")
        if self.risk_flags != sorted(set(self.risk_flags), key=str):
            raise ValueError("Evidence risk flags must be ordered and unique")
        if self.question_ids != list(dict.fromkeys(self.question_ids)):
            raise ValueError("Evidence question IDs must be ordered and unique")
        if self.quote_truncated != (EvidenceRiskFlag.TRUNCATED in self.risk_flags):
            raise ValueError("truncated Evidence must carry the matching risk flag")
        document = self.model_dump(mode="json")
        try:
            if resolve_json_pointer(document, self.evidence_pointer) != self.quote:
                raise ValueError("Evidence quote pointer does not resolve to the quote")
            for source in self.sources:
                resolved = resolve_json_pointer(document, source.evidence_pointer)
                if ProviderSourceRef.model_validate(resolved) != source:
                    raise ValueError("Evidence source pointer does not resolve to the source")
        except EvidenceError as error:
            raise ValueError("Evidence pointer is invalid") from error
        return self


class EvidenceInputRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(pattern="^evidence_[a-z0-9]+$", max_length=120)
    artifact_id: str = Field(min_length=1, max_length=120)
    content_hash: Sha256Hex
    evidence_pointer: str = Field(default="/quote", pattern="^/quote$")


class EvidenceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default=EVIDENCE_MANIFEST_SCHEMA, pattern="^evidence-manifest-v1$")
    policy_version: str = Field(pattern="^evidence-policy-v1$")
    entries: list[EvidenceInputRef] = Field(default_factory=list, max_length=20)
    gap_codes: list[EvidenceGapCode] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_manifest(self) -> EvidenceManifest:
        evidence_ids = [entry.evidence_id for entry in self.entries]
        artifact_ids = [entry.artifact_id for entry in self.entries]
        if len(evidence_ids) != len(set(evidence_ids)) or len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("Evidence Manifest entries must be unique")
        if self.gap_codes != sorted(set(self.gap_codes), key=str):
            raise ValueError("Evidence gaps must be ordered and unique")
        return self


class PreparedEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_ref: ArtifactRef
    source_refs: list[ArtifactRef]
    evidence_inputs: list[EvidenceInputRef]
    gap_codes: list[EvidenceGapCode]


class _RawSourceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1, max_length=120)
    content_provider: str = Field(min_length=1, max_length=120)
    excerpt: str = Field(min_length=1, max_length=8192)
    retrieved_at: datetime
    content_hash: Sha256Hex
    truncated: bool = False
    risk_flags: list[EvidenceRiskFlag] = Field(default_factory=list, max_length=10)
    question_ids: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_content(self) -> _RawSourceEvidence:
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("source evidence retrieval time must be timezone-aware")
        if hashlib.sha256(self.excerpt.encode("utf-8")).hexdigest() != self.content_hash:
            raise ValueError("source evidence content hash mismatch")
        if self.risk_flags != sorted(set(self.risk_flags), key=str):
            raise ValueError("source evidence risk flags must be ordered and unique")
        if self.question_ids != list(dict.fromkeys(self.question_ids)):
            raise ValueError("source evidence question IDs must be ordered and unique")
        if self.truncated != (EvidenceRiskFlag.TRUNCATED in self.risk_flags):
            raise ValueError("truncated source evidence must carry the matching risk flag")
        return self


class _RawProviderSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=500)
    source_type: str = Field(min_length=1, max_length=120)
    reference: str = Field(min_length=1, max_length=2000)
    workspace_id: str | None = Field(default=None, max_length=120)
    project_id: str | None = Field(default=None, max_length=120)
    user_id: str | None = Field(default=None, max_length=120)
    run_id: str | None = Field(default=None, max_length=120)
    skill_id: str | None = Field(default=None, max_length=120)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def require_aware_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("source created_at must be timezone-aware")
        return value


def _decode_pointer_token(token: str) -> str:
    decoded: list[str] = []
    index = 0
    while index < len(token):
        character = token[index]
        if character != "~":
            decoded.append(character)
            index += 1
            continue
        if index + 1 >= len(token) or token[index + 1] not in {"0", "1"}:
            raise EvidenceError("evidence_pointer_invalid")
        decoded.append("~" if token[index + 1] == "0" else "/")
        index += 2
    return "".join(decoded)


def resolve_json_pointer(document: object, pointer: str) -> object:
    if not pointer.startswith("/") or len(pointer) > 1000:
        raise EvidenceError("evidence_pointer_invalid")
    tokens = pointer[1:].split("/")
    if len(tokens) > 64:
        raise EvidenceError("evidence_pointer_invalid")
    current = document
    for raw_token in tokens:
        token = _decode_pointer_token(raw_token)
        if isinstance(current, dict):
            if token not in current:
                raise EvidenceError("evidence_pointer_missing")
            current = current[token]
            continue
        if isinstance(current, list):
            if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                raise EvidenceError("evidence_pointer_invalid")
            index = int(token)
            if index >= len(current):
                raise EvidenceError("evidence_pointer_missing")
            current = current[index]
            continue
        raise EvidenceError("evidence_pointer_type_mismatch")
    return current


def _canonical_https_url(value: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise EvidenceError("evidence_source_url_invalid") from None
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise EvidenceError("evidence_source_url_invalid")
    try:
        hostname = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError:
        raise EvidenceError("evidence_source_url_invalid") from None
    if not hostname:
        raise EvidenceError("evidence_source_url_invalid")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise EvidenceError("evidence_source_url_invalid")
    display_host = f"[{hostname}]" if ":" in hostname else hostname
    netloc = display_host if port in {None, 443} else f"{display_host}:{port}"
    canonical = urlunsplit(
        SplitResult(
            scheme="https",
            netloc=netloc,
            path=parsed.path or "/",
            query="",
            fragment="",
        )
    )
    return canonical, _registrable_domain(hostname)


def _registrable_domain(hostname: str) -> str:
    labels = hostname.rstrip(".").split(".")
    if len(labels) <= 2:
        return hostname
    common_second_level = {"ac", "co", "com", "edu", "gov", "net", "org"}
    if len(labels[-1]) == 2 and labels[-2] in common_second_level:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _truncate_quote(value: str) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= MAX_EVIDENCE_QUOTE_BYTES:
        return value, False
    return encoded[:MAX_EVIDENCE_QUOTE_BYTES].decode("utf-8", errors="ignore"), True


def _stable_id(prefix: str, payload: object) -> str:
    return f"{prefix}_{canonical_sha256(payload)[:32]}"


def _derived_gap_codes(
    sources: list[EvidenceSource],
    *,
    minimum_sources: int,
    require_independent: bool,
) -> list[EvidenceGapCode]:
    provider_sources = [provider_source for source in sources for provider_source in source.sources]
    gaps: set[EvidenceGapCode] = set()
    if not provider_sources:
        gaps.add(EvidenceGapCode.NO_SOURCES)
    elif len(provider_sources) < minimum_sources:
        gaps.add(EvidenceGapCode.INSUFFICIENT_SOURCES)
    if require_independent and len({source.independent_group for source in provider_sources}) < minimum_sources:
        gaps.add(EvidenceGapCode.INSUFFICIENT_INDEPENDENT_SOURCES)
    risk_flags = {flag for source in sources for flag in source.risk_flags}
    if EvidenceRiskFlag.TRUNCATED in risk_flags:
        gaps.add(EvidenceGapCode.TRUNCATED_PROVIDER_SUMMARY)
    if EvidenceRiskFlag.PROMPT_INJECTION_SUSPECTED in risk_flags:
        gaps.add(EvidenceGapCode.PROMPT_INJECTION_SUSPECTED)
    return sorted(gaps, key=str)


def _manifest_artifact_id(lineage: ArtifactLineage, manifest: EvidenceManifest) -> str:
    return _stable_id(
        "artifact_manifest",
        {
            "lineage": lineage.model_dump(mode="json"),
            "schema_version": EVIDENCE_MANIFEST_SCHEMA,
            "entries": [entry.model_dump(mode="json") for entry in manifest.entries],
            "gaps": [gap.value for gap in manifest.gap_codes],
            "policy_version": manifest.policy_version,
        },
    )


class EvidenceService:
    def __init__(self, artifacts: ArtifactStore):
        self.artifacts = artifacts

    def prepare(
        self,
        *,
        plan: ExecutionPlanVersion,
        raw_artifact_ref: ArtifactRef,
        lineage: ArtifactLineage,
        lease: ArtifactLease,
        invocation: ToolInvocation,
    ) -> PreparedEvidence:
        try:
            persisted_plan = self.artifacts.repository.get_research_plan_version(plan.id)
        except ResearchStoreConflict:
            raise EvidenceError("evidence_plan_invalid") from None
        if persisted_plan != plan:
            raise EvidenceError("evidence_plan_not_persisted")
        try:
            plan_body = validate_execution_plan_version(plan)
        except PlanCompileError:
            raise EvidenceError("evidence_plan_invalid") from None
        if (
            plan.id != lineage.plan_version_id
            or plan.run_id != lineage.run_id
            or plan.requirement_version_id != lineage.requirement_version_id
            or plan_body.requirement_version_id != lineage.requirement_version_id
            or lineage.step_number != 1
        ):
            raise EvidenceError("evidence_lineage_invalid")
        try:
            persisted_invocation = self.artifacts.read_verified_tool_invocation(invocation.id)
        except ArtifactStoreError:
            raise EvidenceError("evidence_invocation_not_persisted") from None
        if persisted_invocation != invocation:
            raise EvidenceError("evidence_invocation_not_persisted")
        if (
            invocation.state != InvocationState.ACKNOWLEDGED
            or invocation.run_id != lineage.run_id
            or invocation.plan_version_id != lineage.plan_version_id
            or invocation.active_attempt_id != lineage.attempt_id
            or invocation.step_number != lineage.step_number
            or invocation.artifact_id != raw_artifact_ref.artifact_id
            or invocation.receipt is None
            or invocation.receipt.mode != "real"
            or plan_body.control_snapshot.tool.execution_mode != "real"
            or plan_body.control_snapshot.tool.evidence_class != "provider_summary"
            or invocation.receipt.implementation_id
            != plan_body.control_snapshot.tool.implementation_id
        ):
            raise EvidenceError("evidence_invocation_invalid")
        raw_artifact = self.artifacts.read_verified(
            raw_artifact_ref,
            scope=lineage,
            expected_kind=TOOL_RESULT_KIND,
        )
        if raw_artifact.schema_version not in SUPPORTED_TOOL_RESULT_SCHEMAS:
            raise EvidenceError("evidence_tool_payload_invalid")
        try:
            payload = json.loads(raw_artifact.content)
            Draft202012Validator(
                _tool_output_schema_for_version(
                    plan_body.control_snapshot.tool.output_schema.content,
                    raw_artifact.schema_version,
                )
            ).validate(payload)
        except (json.JSONDecodeError, JsonSchemaValidationError, TypeError, ValueError):
            raise EvidenceError("evidence_tool_payload_invalid") from None
        if not isinstance(payload, dict):
            raise EvidenceError("evidence_tool_payload_invalid")
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            raise EvidenceError("evidence_tool_payload_invalid")
        provider = metadata.get("actual_provider")
        if (
            not isinstance(provider, str)
            or not provider
            or metadata.get("mode") != "real"
            or provider != invocation.receipt.provider
        ):
            raise EvidenceError("evidence_provider_mismatch")
        quote_value = resolve_json_pointer(payload, "/content")
        sources_value = resolve_json_pointer(payload, "/sources")
        source_evidence_value = payload.get("source_evidence", [])
        provider_calls_value = payload.get("provider_calls", [])
        if (
            not isinstance(quote_value, str)
            or not quote_value
            or not isinstance(sources_value, list)
            or not isinstance(source_evidence_value, list)
            or not isinstance(provider_calls_value, list)
            or (
                raw_artifact.schema_version == TOOL_RESULT_SCHEMA
                and ("source_evidence" not in payload or "provider_calls" not in payload)
            )
        ):
            raise EvidenceError("evidence_tool_payload_invalid")
        if invocation.receipt.result_count != len(sources_value):
            raise EvidenceError("evidence_receipt_mismatch")

        provider_sources = [
            self._source_from_payload(
                payload,
                lineage=lineage,
                invocation=invocation,
                index=index,
            )
            for index in range(len(sources_value))
        ]
        source_ids = [source.source_id for source in provider_sources]
        if len(source_ids) != len(set(source_ids)):
            raise EvidenceError("evidence_source_duplicate")
        try:
            raw_source_evidence = [
                _RawSourceEvidence.model_validate(item) for item in source_evidence_value
            ]
        except (TypeError, ValueError):
            raise EvidenceError("evidence_tool_payload_invalid") from None
        raw_evidence_ids = [item.source_id for item in raw_source_evidence]
        if raw_source_evidence and (
            len(raw_evidence_ids) != len(set(raw_evidence_ids))
            or not set(raw_evidence_ids).issubset(source_ids)
        ):
            raise EvidenceError("evidence_source_mismatch")
        if raw_artifact.schema_version == TOOL_RESULT_SCHEMA and set(raw_evidence_ids) != set(source_ids):
            raise EvidenceError("evidence_source_mismatch")
        policy = plan_body.control_snapshot.evidence_policy.content
        minimum_sources, require_independent, policy_version = self._policy(policy)

        source_models: list[EvidenceSource] = []
        source_drafts: list[ArtifactDraft] = []
        evidence_inputs: list[EvidenceInputRef] = []
        if raw_source_evidence:
            source_indexes = {source_id: index for index, source_id in enumerate(source_ids)}
            for evidence_index, raw_evidence in enumerate(raw_source_evidence):
                source_index = source_indexes[raw_evidence.source_id]
                provider_source = self._source_from_payload(
                    payload,
                    lineage=lineage,
                    invocation=invocation,
                    index=source_index,
                    evidence_index=0,
                    retrieved_at=raw_evidence.retrieved_at,
                )
                quote, locally_truncated = _truncate_quote(raw_evidence.excerpt)
                truncated = raw_evidence.truncated or locally_truncated
                flags = set(raw_evidence.risk_flags)
                if truncated:
                    flags.add(EvidenceRiskFlag.TRUNCATED)
                if assess_external_content(raw_evidence.excerpt).decision != RiskDecision.ALLOW:
                    flags.add(EvidenceRiskFlag.PROMPT_INJECTION_SUSPECTED)
                quote_pointer = f"/source_evidence/{evidence_index}/excerpt"
                self._append_evidence_source(
                    source_models=source_models,
                    source_drafts=source_drafts,
                    evidence_inputs=evidence_inputs,
                    provider=provider,
                    content_provider=raw_evidence.content_provider,
                    question_ids=raw_evidence.question_ids,
                    quote=quote,
                    quote_pointer=quote_pointer,
                    quote_truncated=truncated,
                    provider_sources=[provider_source],
                    raw_artifact_ref=raw_artifact_ref,
                    invocation=invocation,
                    payload=payload,
                    lineage=lineage,
                    flags=flags,
                )
        elif provider_sources:
            quote, truncated = _truncate_quote(quote_value)
            flags: set[EvidenceRiskFlag] = set()
            if truncated:
                flags.add(EvidenceRiskFlag.TRUNCATED)
            if assess_external_content(quote_value).decision != RiskDecision.ALLOW:
                flags.add(EvidenceRiskFlag.PROMPT_INJECTION_SUSPECTED)
            self._append_evidence_source(
                source_models=source_models,
                source_drafts=source_drafts,
                evidence_inputs=evidence_inputs,
                provider=provider,
                content_provider=None,
                question_ids=[],
                quote=quote,
                quote_pointer="/content",
                quote_truncated=truncated,
                provider_sources=provider_sources,
                raw_artifact_ref=raw_artifact_ref,
                invocation=invocation,
                payload=payload,
                lineage=lineage,
                flags=flags,
            )

        ordered_gaps = _derived_gap_codes(
            source_models,
            minimum_sources=minimum_sources,
            require_independent=require_independent,
        )
        manifest = EvidenceManifest(
            policy_version=policy_version,
            entries=evidence_inputs,
            gap_codes=ordered_gaps,
        )
        manifest_artifact_id = _manifest_artifact_id(lineage, manifest)
        references = self.artifacts.seal_bundle(
            lineage,
            [
                *source_drafts,
                ArtifactDraft(
                    artifact_id=manifest_artifact_id,
                    kind=EVIDENCE_MANIFEST_KIND,
                    schema_version=EVIDENCE_MANIFEST_SCHEMA,
                    content=manifest,
                ),
            ],
            lease=lease,
        )
        source_refs = references[: len(source_models)]
        manifest_ref = references[-1]
        if any(
            reference.content_hash != evidence_input.content_hash
            for reference, evidence_input in zip(source_refs, evidence_inputs, strict=True)
        ):
            raise EvidenceError("evidence_artifact_hash_mismatch")
        return PreparedEvidence(
            manifest_ref=manifest_ref,
            source_refs=source_refs,
            evidence_inputs=evidence_inputs,
            gap_codes=ordered_gaps,
        )

    @staticmethod
    def _append_evidence_source(
        *,
        source_models: list[EvidenceSource],
        source_drafts: list[ArtifactDraft],
        evidence_inputs: list[EvidenceInputRef],
        provider: str,
        content_provider: str | None,
        question_ids: list[str],
        quote: str,
        quote_pointer: str,
        quote_truncated: bool,
        provider_sources: list[ProviderSourceRef],
        raw_artifact_ref: ArtifactRef,
        invocation: ToolInvocation,
        payload: dict[str, object],
        lineage: ArtifactLineage,
        flags: set[EvidenceRiskFlag],
    ) -> None:
        identity = {
            "origin": raw_artifact_ref.model_dump(mode="json"),
            "invocation_id": invocation.id,
            "operation_key": invocation.operation_key,
            "source_ids": [source.source_id for source in provider_sources],
            "quote_pointer": quote_pointer,
        }
        evidence_id = _stable_id("evidence", identity)
        evidence_source = EvidenceSource(
            evidence_id=evidence_id,
            provider=provider,
            content_provider=content_provider,
            question_ids=question_ids,
            quote=quote,
            quote_origin_pointer=quote_pointer,
            quote_truncated=quote_truncated,
            sources=provider_sources,
            origin_artifact=raw_artifact_ref,
            tool_invocation_id=invocation.id,
            operation_key=invocation.operation_key,
            receipt=invocation.receipt,
            authorization_scope=str(payload["permission"]),
            applicable_scope={
                "user_id": lineage.user_id,
                "workspace_id": lineage.workspace_id,
                "project_id": lineage.project_id,
                "run_id": lineage.run_id,
            },
            risk_flags=sorted(flags, key=str),
        )
        source_artifact_id = _stable_id("artifact_evidence", identity)
        source_hash = canonical_sha256(evidence_source.model_dump(mode="json"))
        source_models.append(evidence_source)
        source_drafts.append(
            ArtifactDraft(
                artifact_id=source_artifact_id,
                kind=EVIDENCE_SOURCE_KIND,
                schema_version=EVIDENCE_SOURCE_SCHEMA,
                content=evidence_source,
            )
        )
        evidence_inputs.append(
            EvidenceInputRef(
                evidence_id=evidence_id,
                artifact_id=source_artifact_id,
                content_hash=source_hash,
                evidence_pointer=evidence_source.evidence_pointer,
            )
        )

    def verify_source_provenance(
        self,
        *,
        plan: ExecutionPlanVersion,
        source_ref: ArtifactRef,
        source: EvidenceSource,
        lineage: ArtifactLineage,
    ) -> None:
        try:
            persisted_plan = self.artifacts.repository.get_research_plan_version(plan.id)
            plan_body = validate_execution_plan_version(plan)
        except (PlanCompileError, ResearchStoreConflict):
            raise EvidenceError("evidence_plan_invalid") from None
        if persisted_plan != plan:
            raise EvidenceError("evidence_plan_not_persisted")
        if (
            plan.id != lineage.plan_version_id
            or plan.run_id != lineage.run_id
            or plan.requirement_version_id != lineage.requirement_version_id
            or plan_body.requirement_version_id != lineage.requirement_version_id
            or lineage.step_number != 1
        ):
            raise EvidenceError("evidence_lineage_invalid")
        try:
            invocation = self.artifacts.read_verified_tool_invocation(source.tool_invocation_id)
        except ArtifactStoreError:
            raise EvidenceError("evidence_invocation_invalid") from None
        try:
            raw_artifact = self.artifacts.read_verified(
                source.origin_artifact,
                scope=lineage,
                expected_kind=TOOL_RESULT_KIND,
            )
        except ArtifactStoreError:
            raise EvidenceError("evidence_origin_invalid") from None
        if raw_artifact.schema_version not in SUPPORTED_TOOL_RESULT_SCHEMAS:
            raise EvidenceError("evidence_origin_invalid")
        self._validate_source_provenance(
            plan=plan,
            plan_body=plan_body,
            source_ref=source_ref,
            source=source,
            lineage=lineage,
            invocation=invocation,
            raw_artifact=raw_artifact,
        )

    def verify_manifest_provenance(
        self,
        *,
        plan: ExecutionPlanVersion,
        manifest_ref: ArtifactRef,
        manifest: EvidenceManifest,
        sources: list[EvidenceSource],
        lineage: ArtifactLineage,
    ) -> None:
        try:
            persisted_plan = self.artifacts.repository.get_research_plan_version(plan.id)
            plan_body = validate_execution_plan_version(plan)
        except (PlanCompileError, ResearchStoreConflict):
            raise EvidenceError("evidence_plan_invalid") from None
        if persisted_plan != plan:
            raise EvidenceError("evidence_plan_not_persisted")
        if (
            plan.id != lineage.plan_version_id
            or plan.run_id != lineage.run_id
            or plan.requirement_version_id != lineage.requirement_version_id
            or plan_body.requirement_version_id != lineage.requirement_version_id
            or lineage.step_number != 1
        ):
            raise EvidenceError("evidence_lineage_invalid")
        minimum_sources, require_independent, policy_version = self._policy(
            plan_body.control_snapshot.evidence_policy.content
        )
        expected_gaps = _derived_gap_codes(
            sources,
            minimum_sources=minimum_sources,
            require_independent=require_independent,
        )
        if (
            manifest.policy_version != policy_version
            or manifest.gap_codes != expected_gaps
            or manifest_ref.artifact_id != _manifest_artifact_id(lineage, manifest)
            or manifest_ref.content_hash != canonical_sha256(manifest.model_dump(mode="json"))
        ):
            raise EvidenceError("evidence_manifest_invalid")

    @staticmethod
    def _validate_source_provenance(
        *,
        plan: ExecutionPlanVersion,
        plan_body,
        source_ref: ArtifactRef,
        source: EvidenceSource,
        lineage: ArtifactLineage,
        invocation: ToolInvocation,
        raw_artifact,
    ) -> None:
        if (
            plan.id != lineage.plan_version_id
            or plan.run_id != lineage.run_id
            or plan.requirement_version_id != lineage.requirement_version_id
            or plan_body.requirement_version_id != lineage.requirement_version_id
            or lineage.step_number != 1
            or plan_body.control_snapshot.tool.execution_mode != "real"
            or plan_body.control_snapshot.tool.evidence_class != "provider_summary"
        ):
            raise EvidenceError("evidence_lineage_invalid")
        if (
            invocation.state != InvocationState.ACKNOWLEDGED
            or invocation.run_id != lineage.run_id
            or invocation.plan_version_id != lineage.plan_version_id
            or invocation.active_attempt_id != lineage.attempt_id
            or invocation.step_number != lineage.step_number
            or invocation.operation_key != source.operation_key
            or invocation.receipt != source.receipt
            or invocation.artifact_id != source.origin_artifact.artifact_id
            or invocation.receipt is None
            or invocation.receipt.mode != "real"
            or invocation.receipt.implementation_id
            != plan_body.control_snapshot.tool.implementation_id
        ):
            raise EvidenceError("evidence_invocation_invalid")
        expected_scope = {
            "user_id": lineage.user_id,
            "workspace_id": lineage.workspace_id,
            "project_id": lineage.project_id,
            "run_id": lineage.run_id,
        }
        if source.applicable_scope != expected_scope:
            raise EvidenceError("evidence_source_lineage_invalid")
        if (
            raw_artifact.id != source.origin_artifact.artifact_id
            or raw_artifact.content_hash != source.origin_artifact.content_hash
            or raw_artifact.artifact_type != TOOL_RESULT_KIND
            or raw_artifact.schema_version not in SUPPORTED_TOOL_RESULT_SCHEMAS
            or raw_artifact.run_id != lineage.run_id
            or raw_artifact.user_id != lineage.user_id
            or raw_artifact.workspace_id != lineage.workspace_id
            or raw_artifact.project_id != lineage.project_id
            or raw_artifact.requirement_version_id != lineage.requirement_version_id
            or raw_artifact.plan_version_id != lineage.plan_version_id
            or raw_artifact.attempt_id != lineage.attempt_id
            or raw_artifact.step_number != lineage.step_number
        ):
            raise EvidenceError("evidence_origin_invalid")
        identity = {
            "origin": source.origin_artifact.model_dump(mode="json"),
            "invocation_id": invocation.id,
            "operation_key": invocation.operation_key,
            "source_ids": [item.source_id for item in source.sources],
            "quote_pointer": source.quote_origin_pointer,
        }
        valid_source_hashes = {
            canonical_sha256(source.model_dump(mode="json")),
            canonical_sha256(source.model_dump(mode="json", exclude_unset=True)),
        }
        if (
            source.evidence_id != _stable_id("evidence", identity)
            or source_ref.artifact_id != _stable_id("artifact_evidence", identity)
            or source_ref.content_hash not in valid_source_hashes
        ):
            raise EvidenceError("evidence_identity_invalid")

        try:
            payload = json.loads(raw_artifact.content)
            Draft202012Validator(
                _tool_output_schema_for_version(
                    plan_body.control_snapshot.tool.output_schema.content,
                    raw_artifact.schema_version,
                )
            ).validate(payload)
        except (json.JSONDecodeError, JsonSchemaValidationError, RecursionError, TypeError, ValueError):
            raise EvidenceError("evidence_tool_payload_invalid") from None
        if not isinstance(payload, dict):
            raise EvidenceError("evidence_tool_payload_invalid")
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            raise EvidenceError("evidence_tool_payload_invalid")
        sources_value = resolve_json_pointer(payload, "/sources")
        if not isinstance(sources_value, list):
            raise EvidenceError("evidence_tool_payload_invalid")
        expected_content_provider: str | None = None
        expected_question_ids: list[str] = []
        declared_truncated = False
        declared_flags: set[EvidenceRiskFlag] = set()
        if source.quote_origin_pointer == "/content":
            quote_value = resolve_json_pointer(payload, source.quote_origin_pointer)
            expected_sources = [
                EvidenceService._source_from_payload(
                    payload,
                    lineage=lineage,
                    invocation=invocation,
                    index=index,
                )
                for index in range(len(sources_value))
            ]
        else:
            tokens = source.quote_origin_pointer.strip("/").split("/")
            if len(tokens) != 3 or tokens[:1] != ["source_evidence"] or tokens[2] != "excerpt":
                raise EvidenceError("evidence_pointer_invalid")
            try:
                evidence_index = int(tokens[1])
                raw_evidence = _RawSourceEvidence.model_validate(
                    resolve_json_pointer(payload, f"/source_evidence/{evidence_index}")
                )
            except (TypeError, ValueError):
                raise EvidenceError("evidence_tool_payload_invalid") from None
            source_indexes = {
                str(item.get("id")): index
                for index, item in enumerate(sources_value)
                if isinstance(item, dict)
            }
            source_index = source_indexes.get(raw_evidence.source_id)
            if source_index is None:
                raise EvidenceError("evidence_source_mismatch")
            quote_value = raw_evidence.excerpt
            expected_sources = [
                EvidenceService._source_from_payload(
                    payload,
                    lineage=lineage,
                    invocation=invocation,
                    index=source_index,
                    evidence_index=0,
                    retrieved_at=raw_evidence.retrieved_at,
                )
            ]
            expected_content_provider = raw_evidence.content_provider
            expected_question_ids = raw_evidence.question_ids
            declared_truncated = raw_evidence.truncated
            declared_flags = set(raw_evidence.risk_flags)
        if not isinstance(quote_value, str):
            raise EvidenceError("evidence_tool_payload_invalid")
        expected_quote, locally_truncated = _truncate_quote(quote_value)
        expected_truncated = declared_truncated or locally_truncated
        expected_flags = set(declared_flags)
        if expected_truncated:
            expected_flags.add(EvidenceRiskFlag.TRUNCATED)
        if assess_external_content(quote_value).decision != RiskDecision.ALLOW:
            expected_flags.add(EvidenceRiskFlag.PROMPT_INJECTION_SUSPECTED)
        if (
            source.provider != metadata.get("actual_provider")
            or source.content_provider != expected_content_provider
            or source.question_ids != expected_question_ids
            or metadata.get("mode") != "real"
            or source.provider != invocation.receipt.provider
            or source.authorization_scope != str(payload.get("permission"))
            or invocation.receipt.result_count != len(sources_value)
            or source.quote != expected_quote
            or source.quote_truncated != expected_truncated
            or source.sources != expected_sources
            or source.conflict_status != "unknown"
            or source.risk_flags != sorted(expected_flags, key=str)
        ):
            raise EvidenceError("evidence_provenance_mismatch")

    @staticmethod
    def _source_from_payload(
        payload: dict[str, object],
        *,
        lineage: ArtifactLineage,
        invocation: ToolInvocation,
        index: int,
        evidence_index: int | None = None,
        retrieved_at: datetime | None = None,
    ) -> ProviderSourceRef:
        pointer = f"/sources/{index}"
        value = resolve_json_pointer(payload, pointer)
        try:
            source = _RawProviderSource.model_validate(value)
        except (TypeError, ValueError):
            raise EvidenceError("evidence_source_invalid") from None
        if (
            source.source_type != "web_page"
            or source.run_id != lineage.run_id
            or source.user_id != lineage.user_id
            or source.workspace_id != lineage.workspace_id
            or source.project_id != lineage.project_id
        ):
            raise EvidenceError("evidence_source_lineage_invalid")
        effective_retrieved_at = retrieved_at or source.created_at
        if (
            invocation.last_sent_at is None
            or invocation.acknowledged_at is None
            or effective_retrieved_at < invocation.last_sent_at - timedelta(minutes=5)
            or effective_retrieved_at > invocation.acknowledged_at + timedelta(minutes=5)
        ):
            raise EvidenceError("evidence_source_time_invalid")
        canonical_url, independent_group = _canonical_https_url(source.reference)
        return ProviderSourceRef(
            source_id=source.id,
            title=source.title,
            url=source.reference,
            canonical_url=canonical_url,
            retrieved_at=effective_retrieved_at,
            evidence_pointer=f"/sources/{evidence_index if evidence_index is not None else index}",
            origin_pointer=pointer,
            independent_group=independent_group,
        )

    @staticmethod
    def _policy(policy: object) -> tuple[int, bool, str]:
        if not isinstance(policy, dict) or policy.get("version") != "evidence-policy-v1":
            raise EvidenceError("evidence_policy_invalid")
        provider_summary = policy.get("provider_summary")
        if not isinstance(provider_summary, dict):
            raise EvidenceError("evidence_policy_invalid")
        minimum_sources = provider_summary.get("minimum_sources")
        require_independent = provider_summary.get("independent_sources")
        if (
            not isinstance(minimum_sources, int)
            or isinstance(minimum_sources, bool)
            or not 1 <= minimum_sources <= 20
            or not isinstance(require_independent, bool)
            or provider_summary.get("maximum_confidence") != "medium"
        ):
            raise EvidenceError("evidence_policy_invalid")
        return minimum_sources, require_independent, str(policy["version"])
