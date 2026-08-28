"""Pure DeepSearch tool invocation and evidence normalization primitives."""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from agentmesh.acquisition import AcquiredEvidenceItem
from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.artifacts import (
    ArtifactAccessError,
    DeepSearchArtifactSchemaRegistry,
    TrustedEvidenceEnvelopeV1,
)
from agentmesh.canonical_json import canonical_json_bytes, canonical_json_sha256
from agentmesh.models import (
    Artifact,
    ArtifactVerificationState,
    DeepSearchEvidenceBindingDraft,
    DeepSearchEvidenceItemV1,
    DeepSearchToolInvocationV1,
    Source,
    ToolDefinition,
    new_id,
)


class DeepSearchToolRuntimeError(RuntimeError):
    """Stable fail-closed error raised before an untrusted tool handler runs."""


@dataclass(frozen=True, slots=True)
class DeepSearchToolEvidenceBatch:
    sources: tuple[Source, ...]
    source_evidence: tuple[AcquiredEvidenceItem, ...]
    envelopes: tuple[TrustedEvidenceEnvelopeV1, ...]
    artifacts: tuple[Artifact, ...]


def build_deepsearch_tool_invocation(
    *,
    context: AgentMeshRunContext,
    definition: ToolDefinition,
    arguments: Mapping[str, Any],
    tool_call_id: str | None = None,
) -> DeepSearchToolInvocationV1:
    lineage = (
        context.requirement_version_id,
        context.plan_id,
        context.plan_version,
        context.node_id,
        context.node_step_number,
        context.node_attempt,
        definition.implementation_id,
    )
    if any(value is None for value in lineage):
        raise DeepSearchToolRuntimeError("deepsearch_tool_lineage_incomplete")
    call_id = tool_call_id or new_id("tool_call")
    operation_key = canonical_json_sha256(
        {
            "run_id": context.run_id,
            "plan_id": context.plan_id,
            "plan_version": context.plan_version,
            "node_id": context.node_id,
            "node_attempt": context.node_attempt,
            "tool_call_id": call_id,
        }
    )
    return DeepSearchToolInvocationV1(
        run_id=context.run_id,
        requirement_version_id=context.requirement_version_id,
        plan_id=context.plan_id,
        plan_version=context.plan_version,
        node_id=context.node_id,
        node_attempt=context.node_attempt,
        tool_definition_id=definition.id,
        implementation_id=definition.implementation_id,
        implementation_version=definition.implementation_version,
        tool_call_id=call_id,
        operation_key=operation_key,
        canonical_arguments_hash=canonical_json_sha256(arguments),
    )


def _normalize_reference(reference: str) -> str:
    normalized = unicodedata.normalize("NFC", reference.strip())
    if not normalized:
        raise DeepSearchToolRuntimeError("deepsearch_evidence_reference_invalid")
    return normalized


def _validate_invocation_lineage(
    *,
    context: AgentMeshRunContext,
    definition: ToolDefinition,
    invocation: DeepSearchToolInvocationV1,
) -> None:
    if (
        invocation.run_id != context.run_id
        or invocation.requirement_version_id != context.requirement_version_id
        or invocation.plan_id != context.plan_id
        or invocation.plan_version != context.plan_version
        or invocation.node_id != context.node_id
        or invocation.node_attempt != context.node_attempt
        or invocation.tool_definition_id != definition.id
        or invocation.implementation_id != definition.implementation_id
        or invocation.implementation_version != definition.implementation_version
    ):
        raise DeepSearchToolRuntimeError("deepsearch_tool_lineage_mismatch")


def normalize_deepsearch_tool_evidence(
    *,
    context: AgentMeshRunContext,
    definition: ToolDefinition,
    invocation: DeepSearchToolInvocationV1,
    value: Mapping[str, Any],
    execution_mode: Literal["real", "fake", "fallback"],
) -> DeepSearchToolEvidenceBatch:
    """Build a deterministic, unpersisted batch for one real Tool result.

    Persistence is intentionally outside this pure function: callers must atomically
    insert every Source and sealed Artifact before exposing any returned identifier.
    """

    _validate_invocation_lineage(
        context=context,
        definition=definition,
        invocation=invocation,
    )
    if execution_mode != "real":
        raise DeepSearchToolRuntimeError("deepsearch_tool_execution_not_real")
    raw_sources = value.get("sources")
    raw_evidence = value.get("source_evidence")
    if not isinstance(raw_sources, list) or not isinstance(raw_evidence, list):
        raise DeepSearchToolRuntimeError("deepsearch_tool_evidence_invalid")
    try:
        sources = [Source.model_validate(item) for item in raw_sources]
        evidence_items = [AcquiredEvidenceItem.model_validate(item) for item in raw_evidence]
    except (TypeError, ValueError):
        raise DeepSearchToolRuntimeError("deepsearch_tool_evidence_invalid") from None
    source_ids = [source.id for source in sources]
    evidence_ids = [item.source_id for item in evidence_items]
    if (
        len(source_ids) != len(set(source_ids))
        or len(evidence_ids) != len(set(evidence_ids))
        or set(source_ids) != set(evidence_ids)
    ):
        raise DeepSearchToolRuntimeError("deepsearch_tool_evidence_invalid")

    evidence_by_source = {item.source_id: item for item in evidence_items}
    sortable_rows = [
        (
            _normalize_reference(source.reference),
            evidence_by_source[source.id].content_hash,
            unicodedata.normalize("NFC", source.title.strip()),
            source,
            evidence_by_source[source.id],
        )
        for source in sources
    ]
    sort_keys = [row[:3] for row in sortable_rows]
    if len(sort_keys) != len(set(sort_keys)):
        # A tie would otherwise make deterministic ordering depend on provider IDs
        # or on comparing Pydantic models. Neither is a trusted stable identity.
        raise DeepSearchToolRuntimeError("deepsearch_tool_evidence_invalid")
    ordered = sorted(sortable_rows, key=lambda row: row[:3])
    reference_ordinals: dict[str, int] = {}
    normalized_sources: list[Source] = []
    normalized_evidence: list[AcquiredEvidenceItem] = []
    envelopes: list[TrustedEvidenceEnvelopeV1] = []
    artifacts: list[Artifact] = []
    for normalized_reference, _content_hash, _title, source, evidence in ordered:
        source_ordinal = reference_ordinals.get(normalized_reference, 0)
        reference_ordinals[normalized_reference] = source_ordinal + 1
        source_id = "src_deepsearch_" + canonical_json_sha256(
            {
                "run_id": invocation.run_id,
                "plan_id": invocation.plan_id,
                "plan_version": invocation.plan_version,
                "node_id": invocation.node_id,
                "node_attempt": invocation.node_attempt,
                "operation_key": invocation.operation_key,
                "normalized_reference": normalized_reference,
                "source_ordinal": source_ordinal,
            }
        )
        normalized_source = source.model_copy(
            update={
                "id": source_id,
                "reference": normalized_reference,
                "workspace_id": context.workspace_id,
                "project_id": context.project_id,
                "user_id": context.user_id,
                "run_id": context.run_id,
                "skill_id": context.skill_id,
                "created_at": evidence.retrieved_at,
            }
        )
        envelope = TrustedEvidenceEnvelopeV1(
            schema_version="deepsearch-tool-evidence-v1",
            origin_type="tool",
            run_id=invocation.run_id,
            requirement_version_id=invocation.requirement_version_id,
            plan_id=invocation.plan_id,
            plan_version=invocation.plan_version,
            node_id=invocation.node_id,
            attempt=invocation.node_attempt,
            tool_name=definition.name,
            tool_implementation_id=invocation.implementation_id,
            tool_implementation_version=invocation.implementation_version,
            execution_mode="real",
            content_provider=evidence.content_provider,
            tool_call_id=invocation.tool_call_id,
            operation_key=invocation.operation_key,
            request_hash=invocation.canonical_arguments_hash,
            source_id=source_id,
            source_ordinal=source_ordinal,
            normalized_reference=normalized_reference,
            retrieved_at=evidence.retrieved_at,
            excerpt=evidence.excerpt,
            content_hash=evidence.content_hash,
            size_bytes=len(evidence.excerpt.encode("utf-8")),
        )
        content = canonical_json_bytes(envelope.model_dump(mode="python")).decode("utf-8")
        content_bytes = content.encode("utf-8")
        artifact_id = "artifact_deepsearch_evidence_" + canonical_json_sha256(
            {"source_id": source_id}
        )
        artifact = Artifact(
            id=artifact_id,
            run_id=context.run_id,
            workspace_id=context.workspace_id,
            project_id=context.project_id,
            user_id=context.user_id,
            artifact_type="deepsearch_tool_evidence",
            content_type="application/json",
            content=content,
            verification_state=ArtifactVerificationState.SEALED,
            schema_version="deepsearch-tool-evidence-v1",
            content_hash=hashlib.sha256(content_bytes).hexdigest(),
            size_bytes=len(content_bytes),
            requirement_version_id=invocation.requirement_version_id,
            plan_version_id=f"{invocation.plan_id}:v{invocation.plan_version}",
            attempt_id=f"{invocation.node_id}:attempt:{invocation.node_attempt}",
            step_number=context.node_step_number,
            created_at=evidence.retrieved_at,
            updated_at=evidence.retrieved_at,
        )
        normalized_sources.append(normalized_source)
        normalized_evidence.append(evidence.model_copy(update={"source_id": source_id}))
        envelopes.append(envelope)
        artifacts.append(artifact)
    return DeepSearchToolEvidenceBatch(
        sources=tuple(normalized_sources),
        source_evidence=tuple(normalized_evidence),
        envelopes=tuple(envelopes),
        artifacts=tuple(artifacts),
    )


def normalize_deepsearch_evidence_bindings(
    *,
    context: AgentMeshRunContext,
    invocation: DeepSearchToolInvocationV1,
    node_result_id: str,
    drafts: Iterable[DeepSearchEvidenceBindingDraft | Mapping[str, Any]],
    node_question_ids: set[str],
    allowed_success_criterion_ids: set[str],
    artifacts: Mapping[str, Artifact],
) -> tuple[DeepSearchEvidenceItemV1, ...]:
    """Turn model-owned bindings into server-owned items after sealed-evidence checks."""

    if not node_result_id:
        raise DeepSearchToolRuntimeError("deepsearch_evidence_binding_invalid")
    normalized: list[DeepSearchEvidenceItemV1] = []
    for raw_draft in drafts:
        try:
            draft = DeepSearchEvidenceBindingDraft.model_validate(raw_draft)
        except (TypeError, ValueError):
            raise DeepSearchToolRuntimeError("deepsearch_evidence_binding_invalid") from None
        artifact = artifacts.get(draft.evidence_artifact_id)
        if artifact is None or artifact.id != draft.evidence_artifact_id:
            raise DeepSearchToolRuntimeError("deepsearch_evidence_binding_invalid")
        if (
            not set(draft.question_ids).issubset(node_question_ids)
            or not set(draft.success_criterion_ids).issubset(allowed_success_criterion_ids)
            or artifact.verification_state is not ArtifactVerificationState.SEALED
            or artifact.artifact_type != "deepsearch_tool_evidence"
            or artifact.schema_version != "deepsearch-tool-evidence-v1"
            or artifact.run_id != context.run_id
            or artifact.workspace_id != context.workspace_id
            or artifact.project_id != context.project_id
            or artifact.user_id != context.user_id
            or artifact.requirement_version_id != invocation.requirement_version_id
            or artifact.plan_version_id != f"{invocation.plan_id}:v{invocation.plan_version}"
            or artifact.attempt_id != f"{invocation.node_id}:attempt:{invocation.node_attempt}"
            or artifact.step_number != context.node_step_number
            or artifact.content_hash != hashlib.sha256(artifact.content.encode("utf-8")).hexdigest()
            or artifact.size_bytes != len(artifact.content.encode("utf-8"))
        ):
            raise DeepSearchToolRuntimeError("deepsearch_evidence_binding_invalid")
        try:
            parsed = DeepSearchArtifactSchemaRegistry.parse(
                artifact.artifact_type,
                artifact.schema_version,
                artifact.content,
            )
        except (ArtifactAccessError, TypeError, ValueError):
            raise DeepSearchToolRuntimeError("deepsearch_evidence_binding_invalid") from None
        if not isinstance(parsed, TrustedEvidenceEnvelopeV1) or (
            parsed.run_id != invocation.run_id
            or parsed.requirement_version_id != invocation.requirement_version_id
            or parsed.plan_id != invocation.plan_id
            or parsed.plan_version != invocation.plan_version
            or parsed.node_id != invocation.node_id
            or parsed.attempt != invocation.node_attempt
            or parsed.tool_call_id != invocation.tool_call_id
            or parsed.operation_key != invocation.operation_key
            or parsed.request_hash != invocation.canonical_arguments_hash
            or parsed.source_id != draft.source_id
        ):
            raise DeepSearchToolRuntimeError("deepsearch_evidence_binding_invalid")
        question_ids = sorted(draft.question_ids)
        criterion_ids = sorted(draft.success_criterion_ids)
        evidence_id = "evidence_" + canonical_json_sha256(
            {
                "node_result_id": node_result_id,
                "evidence_artifact_id": artifact.id,
                "question_ids": question_ids,
                "success_criterion_ids": criterion_ids,
            }
        )
        normalized.append(
            DeepSearchEvidenceItemV1(
                id=evidence_id,
                node_result_id=node_result_id,
                question_ids=question_ids,
                success_criterion_ids=criterion_ids,
                source_id=parsed.source_id,
                evidence_artifact_id=artifact.id,
            )
        )
    item_ids = [item.id for item in normalized]
    if len(item_ids) != len(set(item_ids)):
        raise DeepSearchToolRuntimeError("deepsearch_evidence_binding_invalid")
    return tuple(sorted(normalized, key=lambda item: item.id))
