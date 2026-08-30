from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FrozenStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CatalogStatus(StrEnum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    VALIDATED = "validated"
    PLANNED = "planned"

    @classmethod
    def _missing_(cls, value: object) -> CatalogStatus | None:
        if isinstance(value, str) and value.startswith("planned-"):
            return cls.PLANNED
        return None


class ExecutionRelation(StrEnum):
    SERIAL = "serial"
    PARALLEL = "parallel"
    PARALLEL_THEN_MERGE = "parallel_then_merge"
    CONDITIONAL = "conditional"


class RoutingConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class InputDecision(StrEnum):
    CONTINUE = "continue"
    DEGRADE = "degrade"
    CLARIFY = "clarify"
    HUMAN_CONFIRMATION = "human_confirmation"


class SourceSnapshot(FrozenStrictModel):
    source_path: str = Field(min_length=1, max_length=500)
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class TaskCatalogEntry(SourceSnapshot):
    id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    status: CatalogStatus
    owner: str = Field(min_length=1, max_length=200)
    updated_at: date
    trigger_keywords: tuple[str, ...] = Field(default_factory=tuple)
    outputs: tuple[str, ...] = Field(default_factory=tuple)
    workflow_ids: tuple[str, ...] = Field(default_factory=tuple)
    recommended_skill_ids: tuple[str, ...] = Field(default_factory=tuple)
    required_knowledge_types: tuple[str, ...] = Field(default_factory=tuple)


class CatalogSkillReference(FrozenStrictModel):
    id: str = Field(min_length=1, max_length=160)
    status: CatalogStatus


class ScenarioCatalogEntry(SourceSnapshot):
    id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=200)
    parent_task: str = Field(min_length=1, max_length=120)
    definition: str = Field(min_length=1)
    trigger_examples: tuple[str, ...] = Field(default_factory=tuple)
    required_inputs: tuple[str, ...] = Field(default_factory=tuple)
    optional_inputs: tuple[str, ...] = Field(default_factory=tuple)
    outputs: tuple[str, ...] = Field(min_length=1)
    completion_criteria: tuple[str, ...] = Field(min_length=1)
    default_skills: tuple[CatalogSkillReference, ...] = Field(default_factory=tuple)
    optional_skills: tuple[CatalogSkillReference, ...] = Field(default_factory=tuple)
    knowledge_requirements: tuple[str, ...] = Field(default_factory=tuple)
    dependencies: tuple[str, ...] = Field(default_factory=tuple)
    fallback: tuple[str, ...] = Field(default_factory=tuple)
    human_confirmation: tuple[str, ...] = Field(default_factory=tuple)
    status: CatalogStatus
    owner: str = Field(min_length=1, max_length=200)
    updated_at: date


# Explicit alias for code that dispatches on a persisted Catalog version. Keeping
# the original class name preserves the generated v1 JSON Schema byte contract.
ScenarioCatalogEntryV1 = ScenarioCatalogEntry


OutputKindV2 = Annotated[
    str,
    Field(
        min_length=1,
        max_length=120,
        pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$",
    ),
]


class ScenarioOutputV2(FrozenStrictModel):
    id: str = Field(
        pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$",
        min_length=1,
        max_length=120,
    )
    label: str = Field(min_length=1, max_length=200)
    compatible_output_kinds: tuple[OutputKindV2, ...] = Field(min_length=1, max_length=20)


class ScenarioCatalogEntryV2(SourceSnapshot):
    id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=200)
    parent_task: str = Field(min_length=1, max_length=120)
    definition: str = Field(min_length=1)
    trigger_examples: tuple[str, ...] = Field(default_factory=tuple)
    required_inputs: tuple[str, ...] = Field(default_factory=tuple)
    optional_inputs: tuple[str, ...] = Field(default_factory=tuple)
    outputs: tuple[ScenarioOutputV2, ...] = Field(min_length=1)
    completion_criteria: tuple[str, ...] = Field(min_length=1)
    default_skills: tuple[CatalogSkillReference, ...] = Field(default_factory=tuple)
    optional_skills: tuple[CatalogSkillReference, ...] = Field(default_factory=tuple)
    knowledge_requirements: tuple[str, ...] = Field(default_factory=tuple)
    dependencies: tuple[str, ...] = Field(default_factory=tuple)
    fallback: tuple[str, ...] = Field(default_factory=tuple)
    human_confirmation: tuple[str, ...] = Field(default_factory=tuple)
    status: CatalogStatus
    owner: str = Field(min_length=1, max_length=200)
    updated_at: date


class SkillCatalogEntry(SourceSnapshot):
    id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=240)
    description: str = ""
    business_domain: str = Field(min_length=1, max_length=120)
    status: CatalogStatus
    runtime_skill_name: str | None = Field(default=None, min_length=1, max_length=120)
    capability_domain: tuple[str, ...] = Field(default_factory=tuple)
    task_types: tuple[str, ...] = Field(default_factory=tuple)
    tags: tuple[str, ...] = Field(default_factory=tuple)
    dependencies: tuple[str, ...] = Field(default_factory=tuple)
    related_items: tuple[str, ...] = Field(default_factory=tuple)


class KnowledgeCatalogEntry(SourceSnapshot):
    id: str = Field(min_length=1, max_length=240)
    title: str = Field(min_length=1, max_length=300)
    item_type: str = Field(min_length=1, max_length=80)
    description: str = ""
    business_domain: str = Field(min_length=1, max_length=120)
    status: CatalogStatus
    capability_domain: tuple[str, ...] = Field(default_factory=tuple)
    task_types: tuple[str, ...] = Field(default_factory=tuple)
    tags: tuple[str, ...] = Field(default_factory=tuple)
    dependencies: tuple[str, ...] = Field(default_factory=tuple)
    related_items: tuple[str, ...] = Field(default_factory=tuple)


class TaskSkillMappingEntry(SourceSnapshot):
    scenario_id: str = Field(min_length=1, max_length=120)
    task_id: str = Field(min_length=1, max_length=120)
    default_skill_ids: tuple[str, ...] = Field(default_factory=tuple)
    optional_skill_ids: tuple[str, ...] = Field(default_factory=tuple)
    planned_skill_ids: tuple[str, ...] = Field(default_factory=tuple)
    required_knowledge_ids: tuple[str, ...] = Field(default_factory=tuple)
    optional_knowledge_ids: tuple[str, ...] = Field(default_factory=tuple)
    required_knowledge_descriptors: tuple[str, ...] = Field(default_factory=tuple)
    optional_knowledge_descriptors: tuple[str, ...] = Field(default_factory=tuple)


class CatalogManifest(FrozenStrictModel):
    """Task Catalog v1 manifest; retained for exact legacy parsing."""

    schema_version: Literal["task-catalog-manifest-v1"] = "task-catalog-manifest-v1"
    catalog_version: Literal["user-research-v1"] = "user-research-v1"
    hash_algorithm: Literal["sha256-bytes+agentmesh-canonical-json-v3"] = (
        "sha256-bytes+agentmesh-canonical-json-v3"
    )
    catalog_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_updated_at: date
    source_registry_hashes: dict[str, str]
    files: dict[str, str]
    counts: dict[str, int]


CatalogManifestV1 = CatalogManifest


class CatalogManifestV2(FrozenStrictModel):
    schema_version: Literal["task-catalog-manifest-v2"] = "task-catalog-manifest-v2"
    catalog_version: Literal["user-research-v2"] = "user-research-v2"
    hash_algorithm: Literal["sha256-bytes+agentmesh-canonical-json-v3"] = (
        "sha256-bytes+agentmesh-canonical-json-v3"
    )
    catalog_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_updated_at: date
    source_registry_hashes: dict[str, str]
    files: dict[str, str]
    counts: dict[str, int]


class TaskRoute(StrictModel):
    task_id: str = Field(min_length=1, max_length=120)
    confidence: RoutingConfidence
    reason: str = ""
    secondary_tasks: list[str] = Field(default_factory=list)
    execution_relation: ExecutionRelation = ExecutionRelation.SERIAL


class ScenarioRoute(StrictModel):
    scenario_id: str = Field(min_length=1, max_length=120)
    confidence: RoutingConfidence
    supporting_scenarios: list[str] = Field(default_factory=list)
    alternative_scenarios: list[str] = Field(default_factory=list)


class RoutingContext(StrictModel):
    domain: str | None = None
    page: str | None = None
    journey: list[str] = Field(default_factory=list)
    project: str | None = None
    user_segment: str | None = None
    data_scope: str | None = None


class InputCheckResult(StrictModel):
    available_inputs: list[str] = Field(default_factory=list)
    missing_required_inputs: list[str] = Field(default_factory=list)
    missing_optional_inputs: list[str] = Field(default_factory=list)
    input_decision: InputDecision = InputDecision.CONTINUE


class SkillRoutingDecision(StrictModel):
    default_skills: list[str] = Field(default_factory=list)
    optional_skills: list[str] = Field(default_factory=list)
    planned_skills: list[str] = Field(default_factory=list)
    execution_mode: ExecutionRelation = ExecutionRelation.SERIAL
    fallback_skill: str | None = None


class KnowledgeRoutingDecision(StrictModel):
    required_knowledge: list[str] = Field(default_factory=list)
    optional_knowledge: list[str] = Field(default_factory=list)
    excluded_knowledge: list[str] = Field(default_factory=list)


class EvidenceRequirement(StrictModel):
    external_evidence_required: bool = False
    freshness: str | None = None
    minimum_sources: int = Field(default=0, ge=0, le=100)
    independent_sources: int = Field(default=0, ge=0, le=100)


class CompletionCheckResult(StrictModel):
    completed: bool = False
    scenario_outputs: dict[str, Any] = Field(default_factory=dict)
    missing_outputs: list[str] = Field(default_factory=list)
    criteria_results: dict[str, bool] = Field(default_factory=dict)
    evidence_sufficient: bool = False
    confidence: RoutingConfidence = RoutingConfidence.LOW
    gaps: list[str] = Field(default_factory=list)
    human_confirmation_required: bool = False
    reason: str = ""


class HumanConfirmationDecision(StrictModel):
    required: bool = False
    reason: str = ""


class TaskRoutingResult(StrictModel):
    catalog_version: str = Field(min_length=1, max_length=120)
    catalog_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    task: TaskRoute
    scenario: ScenarioRoute
    context: RoutingContext = Field(default_factory=RoutingContext)
    input_check: InputCheckResult = Field(default_factory=InputCheckResult)
    skill_routing: SkillRoutingDecision = Field(default_factory=SkillRoutingDecision)
    knowledge_routing: KnowledgeRoutingDecision = Field(default_factory=KnowledgeRoutingDecision)
    evidence_requirement: EvidenceRequirement = Field(default_factory=EvidenceRequirement)
    analysis_requirements: list[str] = Field(default_factory=list)
    presentation_requirements: list[str] = Field(default_factory=list)
    completion_check: CompletionCheckResult = Field(default_factory=CompletionCheckResult)
    human_confirmation: HumanConfirmationDecision = Field(default_factory=HumanConfirmationDecision)


class TaskRoutingPreviewRequest(StrictModel):
    content: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = Field(default=None, max_length=120)
    planning_mode: Literal["standard", "deepsearch"] = "standard"


class TaskRoutingPreviewResponse(StrictModel):
    routing_result: TaskRoutingResult
    planning_contract_version: str
    execution_contract_version: str | None = None
    catalog_version: str
    catalog_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    diagnostics: list[str] = Field(default_factory=list)
