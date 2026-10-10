from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentmesh.memory_context.procedure_context import ProcedureContextSelectionV1
from agentmesh.memory_context.request_budget import ContextRequestBudgetV1, ContextRequestMeasurementV1
from agentmesh.memory_payloads import FactQueryResultV1, FactQueryV1
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
from agentmesh.task_operations.contracts import ProjectStateQueryV1, ProjectStateResultV1


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


class CorePreferencesContextV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    owner_user_id: str
    workspace_id: str
    preference_version: int = Field(ge=1)
    preferences: tuple[str, ...] = Field(max_length=8)


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


class MemoryContextCandidateV1(BaseModel):
    """Body-free frozen decision, subordinate to a prepared Memory bundle."""
    model_config = ConfigDict(extra='forbid', frozen=True)
    memory_id: str = Field(min_length=1, max_length=120)
    memory_record_type: Literal['memory_item', 'user_memory_item']
    memory_version: int = Field(ge=1)
    memory_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    decision: Literal['prepared', 'withheld', 'quarantined', 'budget_dropped']
    reason: Literal['selected', 'unsafe_content', 'source_unavailable', 'snapshot_changed', 'budget_limit',
                    'fact_unavailable', 'procedure_unavailable']


class MemoryContextCandidateViewV1(BaseModel):
    candidate: MemoryContextCandidateV1
    state: Literal['prepared', 'withheld', 'quarantined', 'budget_dropped', 'delivered']
    title: str | None = None
    citation_label: str | None = None
    current_available: bool = False


class FactContextSelectionV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    query: FactQueryV1
    result: FactQueryResultV1
    decision: Literal['prepared', 'withheld', 'quarantined', 'budget_dropped']
    allowed_layers: tuple[MemoryLayer, ...] = tuple(MemoryLayer)
    allowed_scopes: tuple[Scope, ...]
    allowed_memory_types: tuple[str, ...] | None = None


class RunFactQueryV1(FactQueryV1):
    """Tool input uses current Run scope without asking the model to invent IDs."""
    project_id: str | None = Field(default=None, min_length=1, max_length=120)
    subject_id: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode='after')
    def require_named_subject(self) -> RunFactQueryV1:
        if self.subject_id is None and self.subject_type in {'user', 'term'}:
            raise ValueError('user and term queries require an explicit subject_id')
        return self


class ProjectStateContextV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    query: ProjectStateQueryV1
    result: ProjectStateResultV1
    decision: Literal['prepared', 'withheld', 'quarantined', 'budget_dropped']


class MemoryContextBundleV1(BaseModel):
    schema_version: Literal["memory-context-bundle-v1"] = "memory-context-bundle-v1"
    query_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested_scope: MemorySearchScope = MemorySearchScope.AUTO
    hits: list[MemoryContextHitV1] = Field(default_factory=list, max_length=8)
    rendered_context: str = ""
    total_chars: int = Field(default=0, ge=0, le=8000)
    receipt_ids: list[str] = Field(default_factory=list)
    # Preserve canonical bytes of legacy bundles/snapshots with no structured selection.
    fact_context: FactContextSelectionV1 | None = Field(default=None, exclude_if=lambda value: value is None)
    project_state_context: ProjectStateContextV1 | None = Field(default=None, exclude_if=lambda value: value is None)
    procedure_context: ProcedureContextSelectionV1 | None = Field(default=None, exclude_if=lambda value: value is None)
    candidates: list[MemoryContextCandidateV1] | None = Field(
        default=None, max_length=200, exclude_if=lambda value: value is None,
    )

    @model_validator(mode='after')
    def separate_query_authorities(self) -> MemoryContextBundleV1:
        if self.procedure_context is not None and self.fact_context is not None:
            raise ValueError('procedure selection has its own evidence authority')
        if self.project_state_context is not None and (
            self.fact_context is not None or ((self.hits or self.receipt_ids) and self.procedure_context is None)
        ):
            raise ValueError('project state does not carry Memory use')
        return self


class MemoryToolDeliveryV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    id: str
    run_id: str
    owner_user_id: str
    workspace_id: str
    project_id: str
    query: str
    output_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    status: Literal['prepared', 'withdrawn'] = 'prepared'
    bundle: MemoryContextBundleV1 | None


class RunContextAssemblyV1(BaseModel):
    """Prepared components; their existing snapshots remain the delivery authority."""
    model_config = ConfigDict(extra='forbid', frozen=True)
    core_preferences: CorePreferencesContextV1 | None = None
    bundle: MemoryContextBundleV1 | None = None
    rendered_context: str = ''
    total_chars: int = Field(default=0, ge=0, le=8000)


class RunContextSnapshotV1(BaseModel):
    """Private execution payload subordinate to one existing Run."""
    model_config = ConfigDict(extra='forbid', frozen=True)
    schema_version: Literal['run-context-snapshot-v1'] = 'run-context-snapshot-v1'
    id: str
    content_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    run_id: str
    owner_user_id: str
    workspace_id: str
    project_id: str
    thread_id: str
    task_id: str | None
    node_id: str | None
    plan_id: str | None
    plan_version: int | None
    writer_generation_epoch: int | None
    skill_id: str | None
    skill_version: str | None
    skill_hash: str | None
    input_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    query: str
    retrieval_reason: str
    additional_instructions: str
    budget: ContextRequestBudgetV1 = Field(default_factory=ContextRequestBudgetV1)
    core_preferences: CorePreferencesContextV1 | None
    bundle: MemoryContextBundleV1 | None
    status: Literal['prepared', 'withdrawn'] = 'prepared'


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
    context_requests: list[ContextRequestMeasurementV1] = Field(default_factory=list, max_length=8)
    memory_candidates: list[MemoryContextCandidateViewV1] = Field(default_factory=list, max_length=200)
    memory_item_id: str | None = None
    memory_disposition: Literal["projected", "policy_skipped", "not_applicable"] = "not_applicable"
