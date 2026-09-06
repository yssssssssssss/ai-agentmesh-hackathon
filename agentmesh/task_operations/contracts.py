from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agentmesh.models import (
    AgentRunStatus,
    TaskAssigneeKind,
    TaskDeliveryStage,
    TaskPriority,
    TaskReviewStatus,
    TaskType,
)


class TaskReadinessState(StrEnum):
    BACKLOG = "backlog"
    WAITING_DEPENDENCIES = "waiting_dependencies"
    BLOCKED = "blocked"
    PLANNED = "planned"
    READY = "ready"
    RUNNING = "running"
    REVIEW = "review"
    DONE = "done"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class AgentQueueState(StrEnum):
    BACKLOG = "backlog"
    PLANNED = "planned"
    WAITING_DEPENDENCIES = "waiting_dependencies"
    BLOCKED = "blocked"
    READY = "ready"
    RUNNING = "running"
    REVIEW = "review"


class TaskReadinessV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: TaskReadinessState
    is_execution_ready: bool = False
    dependency_count: int = Field(ge=0)
    completed_dependency_count: int = Field(ge=0)
    blocking_task_ids: list[str] = Field(default_factory=list)
    child_count: int = Field(default=0, ge=0)
    completed_child_count: int = Field(default=0, ge=0)


class TaskOperationsTaskV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    title: str
    task_type: TaskType
    delivery_stage: TaskDeliveryStage
    priority: TaskPriority | None = None
    due_at: datetime | None = None
    assignee_kind: TaskAssigneeKind | None = None
    assignee_id: str | None = None
    parent_task_id: str | None = None
    dependency_task_ids: list[str] = Field(default_factory=list)
    readiness: TaskReadinessV1
    navigation_href: str


class TaskMilestoneV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task: TaskOperationsTaskV1
    descendant_count: int = Field(ge=0)
    completed_descendant_count: int = Field(ge=0)
    progress_percent: int = Field(ge=0, le=100)
    overdue: bool = False


class TaskCalendarItemV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task: TaskOperationsTaskV1
    overdue: bool = False


class TaskCalendarPageV1(BaseModel):
    items: list[TaskCalendarItemV1] = Field(default_factory=list)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    has_next: bool = False
    range_start: datetime
    range_end: datetime


class AgentQueueItemV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task: TaskOperationsTaskV1
    queue_state: AgentQueueState
    active_run_status: AgentRunStatus | None = None


class AgentQueuePageV1(BaseModel):
    items: list[AgentQueueItemV1] = Field(default_factory=list)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    has_next: bool = False


class TaskOperationsMetricsV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tasks_by_stage: dict[TaskDeliveryStage, int] = Field(default_factory=dict)
    tasks_by_readiness: dict[TaskReadinessState, int] = Field(default_factory=dict)
    runs_by_status: dict[AgentRunStatus, int] = Field(default_factory=dict)
    reviews_by_status: dict[TaskReviewStatus, int] = Field(default_factory=dict)
    task_count: int = Field(ge=0)
    open_task_count: int = Field(ge=0)
    overdue_task_count: int = Field(ge=0)
    blocked_task_count: int = Field(ge=0)
    active_run_count: int = Field(ge=0)
    pending_review_count: int = Field(ge=0)
    memory_use_count: int = Field(ge=0)
    cited_memory_use_count: int = Field(ge=0)
    unique_reused_memory_count: int = Field(ge=0)
    accepted_team_knowledge_count: int = Field(ge=0)


class TaskOperationsSnapshotV1(BaseModel):
    schema_version: Literal["task-operations-snapshot-v1"] = "task-operations-snapshot-v1"
    project_id: str
    generated_at: datetime
    metrics: TaskOperationsMetricsV1
    critical_dependency_chain: list[TaskOperationsTaskV1] = Field(default_factory=list, max_length=100)
    critical_dependency_chain_total: int = Field(default=0, ge=0)
    critical_dependency_chain_truncated: bool = False
    milestones: list[TaskMilestoneV1] = Field(default_factory=list, max_length=50)
    milestone_total: int = Field(default=0, ge=0)
    milestones_truncated: bool = False
    calendar: TaskCalendarPageV1
    agent_queue: AgentQueuePageV1
    graph_task_count: int = Field(ge=0)


class TaskOptionV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    title: str
    task_type: TaskType
    delivery_stage: TaskDeliveryStage
    archived: bool = False


class TaskOptionPageV1(BaseModel):
    items: list[TaskOptionV1] = Field(default_factory=list)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    has_next: bool = False
