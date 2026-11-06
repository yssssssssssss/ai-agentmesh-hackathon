from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from agentmesh.models import (
    AgentRunStatus,
    ScheduledAgentTaskDefinition,
    ScheduledInspectionBudgetV1,
    ScheduledInspectionUsageV1,
    TaskDeliveryStage,
)

InspectionTemplate = Literal["daily_progress", "blockers", "pending_reviews"]


class ScheduledAgentTaskPageV1(BaseModel):
    items: list[ScheduledAgentTaskDefinition]
    total_count: int
    page: int
    page_size: int


class ScheduledOccurrenceV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scheduled-occurrence-v1"] = "scheduled-occurrence-v1"
    id: str
    schedule_id: str
    definition_version: int = Field(ge=1)
    trigger: Literal["scheduled", "manual", "change"]
    trigger_key: str
    scheduled_at: AwareDatetime
    local_slot: str | None = None
    source_cursor: int | None = Field(default=None, ge=0)
    workspace_id: str
    project_id: str
    owner_user_id: str
    template_id: InspectionTemplate
    budget: ScheduledInspectionBudgetV1
    run_id: str | None = None
    admission: Literal["admitted", "skipped", "blocked"]
    reason: str | None = None
    manual_actor_id: str | None = None
    command_hash: str | None = None
    created_at: AwareDatetime


class ScheduleDuePreviewV1(BaseModel):
    schedule_id: str
    definition_version: int
    scheduled_at: AwareDatetime
    local_slot: str | None
    trigger: Literal["scheduled", "change"] = "scheduled"
    source_cursor: int | None = Field(default=None, ge=0)
    budget: ScheduledInspectionBudgetV1
    blocked_reason: str | None = None


class AutomationTickV1(BaseModel):
    mode: Literal["off", "observe", "execute"]
    due: list[ScheduleDuePreviewV1] = Field(default_factory=list)
    occurrences: list[ScheduledOccurrenceV1] = Field(default_factory=list)
    has_more: bool = False


class ScheduledRunNowRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    command_id: str = Field(min_length=1, max_length=120)
    expected_version: int = Field(ge=1)


class AutomationStatusV1(BaseModel):
    mode: Literal["off", "observe", "execute"]
    runtime_available: bool
    running: bool
    last_tick_at: AwareDatetime | None = None
    last_error_code: str | None = None


class ScheduledRunSummaryV1(BaseModel):
    occurrence: ScheduledOccurrenceV1
    status: AgentRunStatus | None = None
    error_code: str | None = None
    tool_call_count: int = 0
    usage: ScheduledInspectionUsageV1 | None = None


class ScheduledRunPageV1(BaseModel):
    items: list[ScheduledRunSummaryV1]
    total_count: int
    page: int
    page_size: int


class ProjectInspectionRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: InspectionTemplate
    since: AwareDatetime | None = None


class InspectionEvidenceRefV1(BaseModel):
    source_kind: Literal["task", "task_command", "task_review_command", "task_review", "memory_review"]
    source_id: str
    version: int = Field(ge=1)
    observed_at: datetime
    navigation_href: str


class InspectionSourceWatermarkV1(BaseModel):
    record_count: int = Field(ge=0)
    latest_updated_at: datetime | None = None


class InspectionBlockerV1(BaseModel):
    task_id: str
    title: str
    delivery_stage: TaskDeliveryStage
    reasons: list[Literal["blocked", "dependency", "overdue", "stale"]]
    blocked_reason: str | None = None
    blocking_task_ids: list[str] = Field(default_factory=list)
    due_at: datetime | None = None
    updated_at: datetime
    navigation_href: str
    evidence_refs: list[InspectionEvidenceRefV1] = Field(default_factory=list)


class InspectionChangeV1(BaseModel):
    task_id: str
    title: str
    kind: Literal["created", "updated", "completed", "reopened", "blocked", "unblocked", "pending_review", "archived"]
    occurred_at: datetime
    version: int = Field(ge=1)
    navigation_href: str
    evidence_refs: list[InspectionEvidenceRefV1] = Field(default_factory=list)


class InspectionPendingReviewV1(BaseModel):
    review_id: str
    kind: Literal["task_review", "memory_review"]
    subject_id: str
    title: str
    reviewer_id: str
    assigned_to_me: bool
    navigation_href: str
    evidence_refs: list[InspectionEvidenceRefV1] = Field(default_factory=list)


class InspectionRecommendationV1(BaseModel):
    reason: str
    navigation_href: str
    evidence_refs: list[InspectionEvidenceRefV1] = Field(default_factory=list)


class ProjectInspectionReportV1(BaseModel):
    schema_version: Literal["project-inspection-v1"] = "project-inspection-v1"
    project_id: str
    template_id: InspectionTemplate
    snapshot_at: datetime
    since: datetime
    data_mode: Literal["real"] = "real"
    outcome: Literal["completed", "no_change", "insufficient_evidence"]
    source_watermarks: dict[str, InspectionSourceWatermarkV1]
    changes: list[InspectionChangeV1] = Field(default_factory=list)
    blockers: list[InspectionBlockerV1] = Field(default_factory=list)
    pending_reviews: list[InspectionPendingReviewV1] = Field(default_factory=list)
    recommendations: list[InspectionRecommendationV1] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    actual_providers: list[str] = Field(default_factory=lambda: ["local_task_store"])
    evidence_refs: list[InspectionEvidenceRefV1] = Field(default_factory=list)
