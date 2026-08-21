from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, model_validator

from agentmesh.research_orchestration.v3.common import (
    ActorType,
    ApprovalRole,
    Identifier,
    NonBlankString,
    Sha256Hex,
    StrictFrozenModel,
    require_unique,
)


class FrozenDocumentV3(StrictFrozenModel):
    document_id: Identifier
    kind: Literal[
        "json_schema",
        "skill_instructions",
        "knowledge",
        "evidence_policy",
        "review_rubric",
        "report_template",
        "synthesis_prompt",
    ]
    media_type: Literal["application/json", "application/yaml", "text/markdown"]
    content_hash: Sha256Hex
    size_bytes: Annotated[int, Field(ge=1, le=1_048_576)]
    content: Any


class FrozenActorV3(StrictFrozenModel):
    actor_type: ActorType
    actor_id: Identifier
    implementation_id: Annotated[NonBlankString, Field(max_length=240)]
    implementation_version: Annotated[NonBlankString, Field(max_length=120)]
    execution_mode: Literal["real", "model", "deterministic"]
    enabled: bool
    eligible: bool
    tier: Literal["core", "optional"] | None = None
    approval_role: ApprovalRole | None = None
    required_tool_ids: tuple[Identifier, ...]
    optional_tool_ids: tuple[Identifier, ...]
    instruction_document_id: Identifier | None = None
    input_schema_document_id: Identifier
    output_schema_document_id: Identifier

    @model_validator(mode="after")
    def validate_actor(self) -> FrozenActorV3:
        require_unique(self.required_tool_ids, "required Tool IDs")
        require_unique(self.optional_tool_ids, "optional Tool IDs")
        if set(self.required_tool_ids) & set(self.optional_tool_ids):
            raise ValueError("a Tool cannot be both required and optional")
        if self.actor_type == "tool" and self.execution_mode != "real":
            raise ValueError("Slice 1 Tool snapshots must represent a real implementation")
        return self


class FrozenModelPolicyV3(StrictFrozenModel):
    requested_provider: Annotated[NonBlankString, Field(max_length=120)]
    requested_model: Annotated[NonBlankString, Field(max_length=120)]
    structured_output_mode: Literal["json_schema", "json_object"]
    adapter_compatibility_id: Annotated[NonBlankString, Field(max_length=240)]


class ResearchControlSnapshotV3(StrictFrozenModel):
    model_config = ConfigDict(json_schema_extra={"$id": "research-control-snapshot-v3"})

    schema_version: Literal["research-control-snapshot-v3"] = "research-control-snapshot-v3"
    catalog_id: Literal["competitive-text-v1"] = "competitive-text-v1"
    catalog_hash: Sha256Hex
    resolved_for_agent_id: Identifier
    resolved_at: datetime
    model_policy: FrozenModelPolicyV3
    actors: tuple[FrozenActorV3, ...]
    documents: tuple[FrozenDocumentV3, ...]

    @model_validator(mode="after")
    def validate_snapshot(self) -> ResearchControlSnapshotV3:
        if self.resolved_at.tzinfo is None or self.resolved_at.utcoffset() is None:
            raise ValueError("resolved_at must include a timezone")
        if self.actors != tuple(sorted(self.actors, key=lambda item: (item.actor_type, item.actor_id))):
            raise ValueError("frozen actors must be sorted by actor_type and actor_id")
        if self.documents != tuple(sorted(self.documents, key=lambda item: item.document_id)):
            raise ValueError("frozen documents must be sorted by document_id")
        require_unique(tuple(actor.actor_id for actor in self.actors), "frozen actor IDs")
        document_ids = tuple(document.document_id for document in self.documents)
        require_unique(document_ids, "frozen document IDs")
        known_documents = set(document_ids)
        for actor in self.actors:
            referenced = {
                actor.input_schema_document_id,
                actor.output_schema_document_id,
            }
            if actor.instruction_document_id is not None:
                referenced.add(actor.instruction_document_id)
            if not referenced.issubset(known_documents):
                raise ValueError(f"frozen actor {actor.actor_id} references an unknown document")
        return self
