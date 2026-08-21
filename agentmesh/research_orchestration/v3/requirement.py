from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.common import (
    Identifier,
    NonBlankString,
    Sha256Hex,
    StrictFrozenModel,
    require_unique,
)

Content240 = Annotated[NonBlankString, Field(max_length=240)]
Content500 = Annotated[NonBlankString, Field(max_length=500)]
Content1000 = Annotated[NonBlankString, Field(max_length=1000)]
Content2000 = Annotated[NonBlankString, Field(max_length=2000)]
Content4000 = Annotated[NonBlankString, Field(max_length=4000)]


class ResearchConstraintV3(StrictFrozenModel):
    id: Identifier
    statement: Content1000
    source: Literal["user", "policy"]


class SuccessCriterionV3(StrictFrozenModel):
    id: Identifier
    statement: Content1000


class ResearchAssumptionV3(StrictFrozenModel):
    key: Identifier
    value: Annotated[str, Field(max_length=2000)]
    editable: bool


class ResearchAmbiguityV3(StrictFrozenModel):
    id: Identifier
    statement: Content1000
    blocking: bool


class ClarificationQuestionV3(StrictFrozenModel):
    key: Identifier
    question: Content500
    rationale: Content1000


class BlockingIssueV3(StrictFrozenModel):
    key: Identifier
    reason: Content1000
    kind: Identifier


class ResearchTaskV3(StrictFrozenModel):
    model_config = ConfigDict(json_schema_extra={"$id": "research-task-v3"})

    schema_version: Literal["research-task-v3"] = "research-task-v3"
    task_type: Literal["competitive_research"] = "competitive_research"
    business_domain: Content240
    research_goal: Content4000
    comparison_dimensions: tuple[Annotated[NonBlankString, Field(max_length=120)], ...] | None = Field(
        default=None,
        min_length=2,
        max_length=20,
    )
    target_audience: tuple[Content240, ...] = Field(max_length=20)
    scope: tuple[Content1000, ...] = Field(max_length=20)
    constraints: tuple[ResearchConstraintV3, ...] = Field(max_length=20)
    success_criteria: tuple[SuccessCriterionV3, ...] = Field(min_length=1, max_length=20)
    expected_deliverables: tuple[Literal["competitive_analysis_report"], ...] = (
        "competitive_analysis_report",
    )
    assumptions: tuple[ResearchAssumptionV3, ...] = Field(max_length=20)
    ambiguities: tuple[ResearchAmbiguityV3, ...] = Field(max_length=10)
    clarification_questions: tuple[ClarificationQuestionV3, ...] = Field(max_length=3)
    blocking_issues: tuple[BlockingIssueV3, ...] = Field(max_length=10)
    sensitivity: Literal["public", "internal", "confidential"]
    pii_detected: bool

    @model_validator(mode="after")
    def validate_requirement(self) -> ResearchTaskV3:
        if self.comparison_dimensions is not None:
            require_unique(self.comparison_dimensions, "comparison dimensions")
        require_unique(tuple(item.id for item in self.constraints), "constraint IDs")
        require_unique(tuple(item.id for item in self.success_criteria), "success criterion IDs")
        require_unique(tuple(item.key for item in self.assumptions), "assumption keys")
        require_unique(tuple(item.id for item in self.ambiguities), "ambiguity IDs")
        require_unique(tuple(item.key for item in self.clarification_questions), "clarification keys")
        require_unique(tuple(item.key for item in self.blocking_issues), "blocking issue keys")
        if self.expected_deliverables != ("competitive_analysis_report",):
            raise ValueError("Competitive Text requires exactly the competitive_analysis_report deliverable")
        has_blocker = bool(self.blocking_issues) or any(item.blocking for item in self.ambiguities)
        if any(item.blocking for item in self.ambiguities) and not self.clarification_questions:
            raise ValueError("a blocking ambiguity requires at least one clarification question")
        if not self.scope and not has_blocker:
            raise ValueError("empty scope is allowed only while clarification is required")
        return self

    @property
    def planning_blocked(self) -> bool:
        return bool(self.blocking_issues) or any(item.blocking for item in self.ambiguities)


class RequirementVersionV3(StrictFrozenModel):
    id: Identifier
    run_id: Identifier
    version: Annotated[int, Field(ge=1)]
    schema_version: Literal["research-task-v3"] = "research-task-v3"
    task_type: Literal["competitive_research"] = "competitive_research"
    payload: ResearchTaskV3
    content_hash: Sha256Hex
    created_at: datetime

    @model_validator(mode="after")
    def validate_envelope(self) -> RequirementVersionV3:
        if self.schema_version != self.payload.schema_version:
            raise ValueError("requirement envelope and payload schema versions must agree")
        if self.task_type != self.payload.task_type:
            raise ValueError("requirement envelope and payload task types must agree")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        if self.content_hash != canonical_json_v3_sha256(self.payload):
            raise ValueError("requirement content_hash does not match the canonical payload")
        return self
