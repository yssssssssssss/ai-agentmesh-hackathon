from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentmesh.models import Task, TaskReviewV1, now_utc


class TaskReviewAllowedAction(StrEnum):
    ACCEPT = "accept"
    REQUEST_CHANGES = "request_changes"
    REJECT = "reject"


class TaskReviewSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    command_id: str = Field(min_length=1, max_length=120)
    expected_task_version: int = Field(ge=1)
    run_id: str = Field(min_length=1, max_length=120)
    artifact_ids: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(
        min_length=1,
        max_length=20,
    )

    @model_validator(mode="after")
    def validate_artifacts(self) -> TaskReviewSubmitRequest:
        if len(set(self.artifact_ids)) != len(self.artifact_ids):
            raise ValueError("artifact_ids must be unique")
        return self


class TaskReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    command_id: str = Field(min_length=1, max_length=120)
    expected_version: int = Field(ge=1)
    decision: Literal["accepted", "changes_requested", "rejected"]
    decision_note: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_note(self) -> TaskReviewDecisionRequest:
        note = self.decision_note.strip() if self.decision_note is not None else None
        self.decision_note = note or None
        if self.decision in {"changes_requested", "rejected"} and self.decision_note is None:
            raise ValueError("decision_note is required for changes_requested and rejected")
        return self


class TaskReviewAuthorizationV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_id: str = Field(min_length=1, max_length=120)
    workspace_id: str = Field(min_length=1, max_length=120)
    project_id: str = Field(min_length=1, max_length=120)


class TaskReviewCommandReceiptV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["task-review-command-receipt-v1"] = "task-review-command-receipt-v1"
    id: str = Field(min_length=1, max_length=120)
    command_id: str = Field(min_length=1, max_length=120)
    user_id: str = Field(min_length=1, max_length=120)
    operation: Literal["submit", "decide"]
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_id: str = Field(min_length=1, max_length=120)
    result_review: TaskReviewV1
    result_task: Task
    created_at: datetime = Field(default_factory=now_utc)


class TaskReviewViewV1(BaseModel):
    review: TaskReviewV1
    allowed_actions: list[TaskReviewAllowedAction] = Field(default_factory=list)


class TaskReviewMutationResponseV1(BaseModel):
    item: TaskReviewViewV1
    task: Task
