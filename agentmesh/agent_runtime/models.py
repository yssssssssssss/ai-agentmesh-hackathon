from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field


class AgentMeshRunContext(BaseModel):
    """Serializable identities only; SDK RunState may persist this object."""

    user_id: str
    workspace_id: str
    project_id: str
    thread_id: str
    run_id: str
    run_execution_hash: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    requirement_version_id: str | None = Field(default=None, max_length=120)
    plan_id: str | None = None
    plan_version: int | None = Field(default=None, ge=1)
    plan_execution_hash: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    node_id: str | None = None
    node_step_number: int | None = Field(default=None, ge=1, le=6)
    node_attempt: int | None = Field(default=None, ge=1, le=2)
    skill_id: str | None = None
    policy_snapshot_ids: list[str] = Field(default_factory=list)
    approved_resource_hashes: dict[str, str] = Field(default_factory=dict)
    resource_manifest_frozen: bool = False
    source_ids: list[str] = Field(default_factory=list)
    memory_use_receipt_ids: list[str] = Field(default_factory=list)
    context_snapshot_id: str | None = Field(default=None, max_length=120)
    artifact_ids: list[str] = Field(default_factory=list)
    resource_references: list[str] = Field(default_factory=list)
    tool_call_count: int = Field(default=0, ge=0)


@dataclass(frozen=True, slots=True)
class RuntimeAnswer:
    content: str
    llm_used: bool
    skill_name: str | None = None
    requested_model: str | None = None
    actual_model: str | None = None
    total_tokens: int = 0
    run_id: str | None = None
    waiting_approval: bool = False
    interruptions: tuple[dict[str, str], ...] = ()
