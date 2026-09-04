from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentmesh.models import (
    AgentRun,
    MemoryKind,
    MemoryLayer,
    MemorySearchScope,
    MemoryUseReceiptV1,
    Scope,
    SearchResult,
    Source,
)


class MemoryContextBudgetV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["memory-context-budget-v1"] = "memory-context-budget-v1"
    top_k: int = Field(default=8, ge=1, le=8)
    max_total_chars: int = Field(default=8000, ge=1, le=8000)
    max_summary_chars: int = Field(default=2000, ge=1, le=2000)
    allowed_layers: tuple[MemoryLayer, ...] = Field(
        default_factory=lambda: tuple(MemoryLayer),
        min_length=1,
        max_length=3,
    )

    @model_validator(mode="after")
    def unique_layers(self) -> MemoryContextBudgetV1:
        if len(self.allowed_layers) != len(set(self.allowed_layers)):
            raise ValueError("allowed_layers must be unique")
        return self


class MemoryContextHitV1(BaseModel):
    citation_label: str = Field(pattern=r"^[PJT][1-9][0-9]*$")
    memory_id: str
    memory_kind: MemoryKind
    memory_version: int = Field(ge=1)
    memory_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope: Scope
    layer: MemoryLayer
    result: SearchResult
    receipt_id: str | None = None


class MemoryContextBundleV1(BaseModel):
    schema_version: Literal["memory-context-bundle-v1"] = "memory-context-bundle-v1"
    query_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested_scope: MemorySearchScope = MemorySearchScope.AUTO
    hits: list[MemoryContextHitV1] = Field(default_factory=list, max_length=8)
    rendered_context: str = ""
    total_chars: int = Field(default=0, ge=0, le=8000)
    receipt_ids: list[str] = Field(default_factory=list)


class MemoryCitationRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    memory_id: str = Field(min_length=1, max_length=120)
    memory_kind: MemoryKind
    memory_record_type: Literal["memory_item", "user_memory_item"]
    memory_version: int = Field(ge=1)


class MemoryUseAuthorizationV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_id: str = Field(min_length=1, max_length=120)
    workspace_id: str = Field(min_length=1, max_length=120)
    project_id: str = Field(min_length=1, max_length=120)
    run_id: str = Field(min_length=1, max_length=120)
    task_id: str | None = Field(default=None, max_length=120)
    agent_id: str = Field(min_length=1, max_length=120)


class MemoryUseViewV1(BaseModel):
    receipt: MemoryUseReceiptV1
    title: str | None = None
    scope: Scope | None = None
    layer: MemoryLayer | None = None
    sources: list[Source] = Field(default_factory=list)
    cited_in_output: bool = False
    memory_navigation_href: str | None = None
    task_navigation_href: str | None = None


class MemoryUseBacklinkV1(BaseModel):
    receipt_id: str
    run_id: str
    task_id: str | None = None
    citation_label: str
    memory_version: int = Field(ge=1)
    memory_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieval_reason: str
    created_at: datetime
    run_navigation_href: str | None = None
    task_navigation_href: str | None = None


class AgentRunDetailResponseV1(BaseModel):
    item: AgentRun
    memory_uses: list[MemoryUseViewV1] = Field(default_factory=list)
