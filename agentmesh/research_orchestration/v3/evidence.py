from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.common import (
    ActorType,
    EvidenceClass,
    FrozenJson,
    FrozenJsonObject,
    Identifier,
    NonBlankString,
    Sha256Hex,
    StrictFrozenModel,
    SealedArtifactRefV3,
    require_unique,
)

EvidenceText = Annotated[NonBlankString, Field(max_length=4000)]
HttpsUrl = Annotated[str, Field(pattern=r"^https://[^\s]+$", max_length=2048)]
JsonPointer = Annotated[str, Field(pattern=r"^(?:/(?:[^~/]|~[01])*)+$", max_length=1000)]
DomainName = Annotated[
    str,
    Field(
        pattern=r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
        r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$",
        max_length=253,
    ),
]


class EvidenceSourceV3(StrictFrozenModel):
    """The human-auditable public source represented by one text evidence item."""

    source_kind: Literal["public_web"] = "public_web"
    url: HttpsUrl
    quote: EvidenceText
    retrieved_at: datetime
    registrable_domain: DomainName
    independence_group: Identifier
    conflict_status: Literal["none", "corroborated", "conflicting"]
    risk_flags: tuple[Identifier, ...]
    truncated: bool

    @model_validator(mode="after")
    def validate_source(self) -> EvidenceSourceV3:
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("evidence retrieved_at must include a timezone")
        require_unique(self.risk_flags, "evidence source risk flags")
        return self


class EvidenceProofV3(StrictFrozenModel):
    """Execution proof that prevents public facts from being detached from their Tool call."""

    run_id: Identifier
    plan_version_id: Identifier
    attempt_id: Identifier
    step_number: Annotated[int, Field(ge=1, le=8)]
    actor_type: Literal["tool"] = "tool"
    actor_id: Identifier
    step_contract_hash: Sha256Hex
    receipt_id: Identifier
    implementation_id: Identifier
    execution_mode: Literal["real"] = "real"
    redacted_output_hash: Sha256Hex


class VerifiedArtifactPointerV3(StrictFrozenModel):
    """A pointer bound to the exact sealed Artifact bytes that must be read and verified."""

    artifact: SealedArtifactRefV3
    json_pointer: JsonPointer


class EvidenceItemV3(StrictFrozenModel):
    id: Identifier
    kind: Literal["tool_output"] = "tool_output"
    evidence_class: Literal["public_source"] = "public_source"
    pointer: VerifiedArtifactPointerV3
    source: EvidenceSourceV3
    proof: EvidenceProofV3
    sensitivity: Literal["public"] = "public"
    redaction: Literal["none", "masked"]


class EvidenceManifestV3(StrictFrozenModel):
    """Slice 1 Evidence Manifest: public, real-Tool, text-only evidence from one execution."""

    model_config = ConfigDict(json_schema_extra={"$id": "evidence-manifest-v3"})

    schema_version: Literal["evidence-manifest-v3"] = "evidence-manifest-v3"
    presentation_mode: Literal["text"] = "text"
    payload_schema_version: Literal["competitive-analysis-text-v1"] = "competitive-analysis-text-v1"
    run_id: Identifier
    plan_version_id: Identifier
    attempt_id: Identifier
    collected_at: datetime
    evidence: tuple[EvidenceItemV3, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_manifest(self) -> EvidenceManifestV3:
        if self.collected_at.tzinfo is None or self.collected_at.utcoffset() is None:
            raise ValueError("evidence collected_at must include a timezone")
        evidence_ids = tuple(item.id for item in self.evidence)
        require_unique(evidence_ids, "Evidence Manifest IDs")
        if evidence_ids != tuple(sorted(evidence_ids)):
            raise ValueError("Evidence Manifest entries must be sorted by ID")
        pointer_keys = tuple(
            (item.pointer.artifact.artifact_id, item.pointer.json_pointer) for item in self.evidence
        )
        require_unique(pointer_keys, "Evidence Manifest Artifact pointers")
        expected_lineage = (self.run_id, self.plan_version_id, self.attempt_id)
        for item in self.evidence:
            proof_lineage = (item.proof.run_id, item.proof.plan_version_id, item.proof.attempt_id)
            if proof_lineage != expected_lineage:
                raise ValueError("every Evidence proof must belong to the Manifest run, plan, and attempt")
        return self


class VerifiedArtifactContentV3(StrictFrozenModel):
    """Hash-verified JSON Artifact content plus the execution lineage read from persistence."""

    run_id: Identifier
    plan_version_id: Identifier
    attempt_id: Identifier
    step_number: Annotated[int, Field(ge=1, le=8)]
    actor_type: ActorType
    actor_id: Identifier
    step_contract_hash: Sha256Hex
    receipt_id: Identifier
    artifact: SealedArtifactRefV3
    content: FrozenJson

    @model_validator(mode="after")
    def validate_content_hash(self) -> VerifiedArtifactContentV3:
        if canonical_json_v3_sha256(self.content) != self.artifact.content_hash:
            raise ValueError("verified Artifact content does not match its sealed content hash")
        return self


def _resolve_json_pointer(value: FrozenJson, pointer: str) -> FrozenJson | None:
    current: FrozenJson = value
    for encoded_segment in pointer[1:].split("/"):
        segment = encoded_segment.replace("~1", "/").replace("~0", "~")
        if isinstance(current, tuple):
            if not segment.isdigit() or (segment.startswith("0") and segment != "0"):
                return None
            index = int(segment)
            if index >= len(current):
                return None
            current = current[index]
        elif isinstance(current, FrozenJsonObject):
            if segment not in current:
                return None
            current = current[segment]
        else:
            return None
    return current


def _resolved_source_url(value: FrozenJson) -> str | None:
    if not isinstance(value, Mapping):
        return None
    url = value.get("url")
    if not isinstance(url, str):
        url = value.get("oss_url")
    return url if isinstance(url, str) else None


def verify_evidence_manifest_artifacts(
    manifest: EvidenceManifestV3,
    artifacts: tuple[VerifiedArtifactContentV3, ...],
) -> None:
    """Verify every pointer/proof against explicit Artifact contents, with no ambient lookup."""

    artifact_ids = tuple(item.artifact.artifact_id for item in artifacts)
    require_unique(artifact_ids, "verified Artifact IDs")
    artifacts_by_id = {item.artifact.artifact_id: item for item in artifacts}
    expected_ids = {item.pointer.artifact.artifact_id for item in manifest.evidence}
    if set(artifact_ids) != expected_ids:
        raise ValueError("verified Artifact contents must exactly cover Evidence Manifest Artifacts")

    manifest_lineage = (manifest.run_id, manifest.plan_version_id, manifest.attempt_id)
    for evidence in manifest.evidence:
        verified = artifacts_by_id[evidence.pointer.artifact.artifact_id]
        proof = evidence.proof
        if verified.artifact != evidence.pointer.artifact:
            raise ValueError("Evidence pointer does not match the verified sealed Artifact")
        if (verified.run_id, verified.plan_version_id, verified.attempt_id) != manifest_lineage:
            raise ValueError("verified Evidence Artifact does not belong to the Manifest execution")
        if (
            verified.step_number,
            verified.actor_type,
            verified.actor_id,
            verified.step_contract_hash,
            verified.receipt_id,
        ) != (
            proof.step_number,
            proof.actor_type,
            proof.actor_id,
            proof.step_contract_hash,
            proof.receipt_id,
        ):
            raise ValueError("Evidence proof does not match verified Artifact execution lineage")
        resolved = _resolve_json_pointer(verified.content, evidence.pointer.json_pointer)
        if resolved is None:
            raise ValueError("Evidence pointer does not resolve in the verified Artifact")
        if _resolved_source_url(resolved) != evidence.source.url:
            raise ValueError("Evidence source URL does not match its verified Artifact pointer")
        if not isinstance(verified.content, Mapping):
            raise ValueError("public Evidence Artifact content must be an object")
        output = verified.content.get("output")
        output_hash = verified.content.get("redacted_output_hash")
        if output is None or output_hash != proof.redacted_output_hash:
            raise ValueError("Evidence proof hash is absent from the verified Artifact")
        if canonical_json_v3_sha256(output) != proof.redacted_output_hash:
            raise ValueError("Evidence proof hash does not match the verified redacted Tool output")


def validate_evidence_classes_are_text_only(classes: tuple[EvidenceClass, ...]) -> None:
    """Shared guard for callers assembling Slice 1 policy inputs."""

    if any(evidence_class != "public_source" for evidence_class in classes):
        raise ValueError("Competitive Text accepts only public_source evidence")
