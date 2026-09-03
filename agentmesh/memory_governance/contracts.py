from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentmesh.models import (
    MemoryLayer,
    MemoryProvenanceV1,
    MemoryReviewV1,
    MemoryStatus,
    Scope,
    now_utc,
)


class MemoryCaptureTarget(StrEnum):
    PERSONAL = "personal"
    TEAM_CANDIDATE = "team_candidate"


class MemoryEntryKind(StrEnum):
    PERSONAL = "personal"
    TEAM_CANDIDATE = "team_candidate"
    TEAM_KNOWLEDGE = "team_knowledge"
    LEGACY_SHARED = "legacy_shared"


class MemoryReviewAllowedAction(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"


class MemoryLifecycleAction(StrEnum):
    DISPUTE = "dispute"
    DEPRECATE = "deprecate"
    EXPIRE = "expire"
    ARCHIVE = "archive"
    RESTORE = "restore"


class MemoryGovernanceAllowedAction(StrEnum):
    REVISE = "revise"
    DISPUTE = "dispute"
    DEPRECATE = "deprecate"
    EXPIRE = "expire"
    ARCHIVE = "archive"
    RESTORE = "restore"


class TaskReviewMemoryCaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    command_id: str = Field(min_length=1, max_length=120)
    target: MemoryCaptureTarget
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2000)
    memory_type: str = Field(default="project_experience", min_length=1, max_length=80)
    layer: MemoryLayer = MemoryLayer.MID_TERM


class MemoryReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    command_id: str = Field(min_length=1, max_length=120)
    expected_memory_version: int = Field(ge=1)
    expected_review_version: int = Field(ge=1)
    decision: Literal["accepted", "rejected"]
    decision_note: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_note(self) -> MemoryReviewDecisionRequest:
        note = self.decision_note.strip() if self.decision_note is not None else None
        self.decision_note = note or None
        if self.decision == "rejected" and self.decision_note is None:
            raise ValueError("decision_note is required when rejecting a Memory Candidate")
        return self


class MemoryRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    command_id: str = Field(min_length=1, max_length=120)
    expected_version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2000)
    memory_type: str = Field(min_length=1, max_length=80)


class MemoryTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    command_id: str = Field(min_length=1, max_length=120)
    expected_version: int = Field(ge=1)
    action: MemoryLifecycleAction


class MemoryEntryViewV1(BaseModel):
    schema_version: Literal["memory-entry-view-v1"] = "memory-entry-view-v1"
    id: str
    kind: MemoryEntryKind
    title: str
    summary: str
    memory_type: str
    scope: Scope
    status: str
    owner_user_id: str | None = None
    workspace_id: str
    project_id: str | None = None
    team_id: str | None = None
    layer: MemoryLayer | None = None
    version: int = Field(ge=1)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    provenance: MemoryProvenanceV1 | None = None
    provenance_state: Literal["verified", "legacy_unverified"]
    supersedes_memory_id: str | None = None
    archived_at: datetime | None = None
    archived_by: str | None = None
    archived_from_status: MemoryStatus | None = None
    created_at: datetime
    updated_at: datetime
    allowed_actions: list[str] = Field(default_factory=list)
    memory_review: MemoryReviewV1 | None = None
    navigation_href: str


class MemoryReviewViewV1(BaseModel):
    review: MemoryReviewV1
    allowed_actions: list[MemoryReviewAllowedAction] = Field(default_factory=list)


class MemoryGovernanceAuthorizationV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_id: str = Field(min_length=1, max_length=120)
    workspace_id: str = Field(min_length=1, max_length=120)
    project_id: str = Field(min_length=1, max_length=120)


class MemoryGovernanceCommandReceiptV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["memory-governance-command-receipt-v1"] = "memory-governance-command-receipt-v1"
    id: str = Field(min_length=1, max_length=120)
    command_id: str = Field(min_length=1, max_length=120)
    user_id: str = Field(min_length=1, max_length=120)
    operation: Literal["capture", "review_decision", "revision", "transition"]
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    memory_id: str = Field(min_length=1, max_length=120)
    result_entry: MemoryEntryViewV1
    result_review: MemoryReviewV1 | None = None
    created_at: datetime = Field(default_factory=now_utc)


class MemoryCaptureResponseV1(BaseModel):
    item: MemoryEntryViewV1
    memory_review: MemoryReviewViewV1 | None = None


class MemoryReviewDecisionResponseV1(BaseModel):
    item: MemoryEntryViewV1
    memory_review: MemoryReviewViewV1


class MemoryRevisionResponseV1(BaseModel):
    item: MemoryEntryViewV1
    memory_review: MemoryReviewViewV1


class MemoryTransitionResponseV1(BaseModel):
    item: MemoryEntryViewV1


class MemoryRevisionLinkV1(BaseModel):
    id: str
    title: str
    status: str
    scope: Scope
    version: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    navigation_href: str


class MemoryGovernanceEventV1(BaseModel):
    id: str
    action: str
    actor: str
    created_at: datetime
    metadata: dict[str, object] = Field(default_factory=dict)


class MemoryPageV1(BaseModel):
    items: list[MemoryEntryViewV1]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    has_next: bool


class MemoryLineageViewV1(BaseModel):
    item: MemoryEntryViewV1
    task_id: str | None = None
    run_id: str | None = None
    task_review_id: str | None = None
    artifact_ids: list[str] = Field(default_factory=list)
    artifact_hashes: list[str] = Field(default_factory=list)
    source_memory_ids: list[str] = Field(default_factory=list)
    source_memories: list[MemoryRevisionLinkV1] = Field(default_factory=list)
    superseded_by_memory_ids: list[str] = Field(default_factory=list)
    superseded_by_memories: list[MemoryRevisionLinkV1] = Field(default_factory=list)
    memory_reviews: list[MemoryReviewViewV1] = Field(default_factory=list)
    governance_events: list[MemoryGovernanceEventV1] = Field(default_factory=list)


class TaskMemoryLinkV1(BaseModel):
    id: str
    kind: MemoryEntryKind
    title: str
    status: str
    version: int = Field(ge=1)
    navigation_href: str
    source_review_id: str


class MemoryBacklinksV1(BaseModel):
    items: list[TaskMemoryLinkV1] = Field(default_factory=list)
