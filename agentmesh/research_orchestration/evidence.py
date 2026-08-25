"""Frozen research-v2 evidence payloads required by historical reads."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentmesh.research_orchestration.contracts import Sha256Hex, ToolReceipt
from agentmesh.research_orchestration.v2_artifact_history import ArtifactRef

MAX_EVIDENCE_QUOTE_BYTES = 8 * 1024
EVIDENCE_SOURCE_SCHEMA = "evidence-source-v1"
EVIDENCE_MANIFEST_SCHEMA = "evidence-manifest-v1"


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
