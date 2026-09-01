from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentmesh.models import (
    Task,
    TaskAssigneeKind,
    TaskDeliveryStage,
    TaskManagementMetadataV1,
    TaskPriority,
    TaskType,
    now_utc,
)


class TaskManagementAction(StrEnum):
    EDIT = "edit"
    ASSIGN = "assign"
    PLAN = "plan"
    START = "start"
    SUBMIT_REVIEW = "submit_review"
    COMPLETE = "complete"
    REOPEN = "reopen"
    BLOCK = "block"
    UNBLOCK = "unblock"
    CANCEL = "cancel"
    ARCHIVE = "archive"


class TaskTransitionAction(StrEnum):
    PLAN = "plan"
    START = "start"
    SUBMIT_REVIEW = "submit_review"
    COMPLETE = "complete"
    REOPEN = "reopen"
    BLOCK = "block"
    UNBLOCK = "unblock"
    CANCEL = "cancel"


class TaskCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    command_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    task_type: TaskType = TaskType.PROJECT_ACTION
    priority: TaskPriority | None = None
    due_at: datetime | None = None
    assignee_kind: TaskAssigneeKind | None = None
    assignee_id: str | None = Field(default=None, max_length=120)
    tags: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def validate_assignee(self) -> TaskCreateRequest:
        if (self.assignee_kind is None) != (self.assignee_id is None):
            raise ValueError("assignee_kind and assignee_id must be set together")
        if self.due_at is not None and self.due_at.utcoffset() is None:
            raise ValueError("due_at must include a timezone")
        return self


class TaskUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    command_id: str = Field(min_length=1, max_length=120)
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    task_type: TaskType | None = None
    priority: TaskPriority | None = None
    due_at: datetime | None = None
    assignee_kind: TaskAssigneeKind | None = None
    assignee_id: str | None = Field(default=None, max_length=120)
    tags: list[str] | None = Field(default=None, max_length=12)

    @model_validator(mode="after")
    def validate_patch(self) -> TaskUpdateRequest:
        fields = self.model_fields_set - {"command_id", "expected_version"}
        if not fields:
            raise ValueError("at least one task field is required")
        for required_field in ("title", "description", "task_type"):
            if required_field in fields and getattr(self, required_field) is None:
                raise ValueError(f"{required_field} cannot be null")
        assignee_fields = {"assignee_kind", "assignee_id"}
        if fields & assignee_fields and not assignee_fields.issubset(fields):
            raise ValueError("assignee_kind and assignee_id must be updated together")
        if assignee_fields.issubset(fields) and (self.assignee_kind is None) != (self.assignee_id is None):
            raise ValueError("assignee_kind and assignee_id must be set together")
        if "due_at" in fields and self.due_at is not None and self.due_at.utcoffset() is None:
            raise ValueError("due_at must include a timezone")
        return self


class TaskTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    command_id: str = Field(min_length=1, max_length=120)
    expected_version: int = Field(ge=1)
    action: TaskTransitionAction
    reason: str | None = Field(default=None, max_length=1000)


class TaskArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    command_id: str = Field(min_length=1, max_length=120)
    expected_version: int = Field(ge=1)


class TaskCommandAuthorizationV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_id: str = Field(min_length=1, max_length=120)
    workspace_id: str = Field(min_length=1, max_length=120)
    project_id: str = Field(min_length=1, max_length=120)
    require_project_manager: bool = False
    validate_assignee: bool = False
    assignee_kind: TaskAssigneeKind | None = None
    assignee_id: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_target(self) -> TaskCommandAuthorizationV1:
        if self.validate_assignee and (self.assignee_kind is None) != (self.assignee_id is None):
            raise ValueError("assignee_kind and assignee_id must be set together")
        return self


class TaskCommandReceiptV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["task-command-receipt-v1"] = "task-command-receipt-v1"
    id: str = Field(min_length=1, max_length=120)
    command_id: str = Field(min_length=1, max_length=120)
    user_id: str = Field(min_length=1, max_length=120)
    operation: Literal["create", "update", "transition", "archive"]
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_id: str = Field(min_length=1, max_length=120)
    result_task: Task
    created_at: datetime = Field(default_factory=now_utc)


class TaskManagementViewV1(BaseModel):
    task: Task
    management: TaskManagementMetadataV1
    allowed_actions: list[TaskManagementAction] = Field(default_factory=list)


class TaskManagementItemResponse(BaseModel):
    item: TaskManagementViewV1


class TaskManagementPageV1(BaseModel):
    items: list[TaskManagementViewV1]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    has_next: bool
    counts: dict[TaskDeliveryStage, int] = Field(default_factory=dict)


class TaskManagementDetailV1(BaseModel):
    item: TaskManagementViewV1
