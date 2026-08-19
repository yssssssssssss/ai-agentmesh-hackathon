from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.models import AgentRun, AgentRunStatus
from agentmesh.research_orchestration.compiler import FrozenModelPolicy, FrozenSkillActor, FrozenToolActor
from agentmesh.research_orchestration.contracts import ResearchCommandReceipt, ResearchWorkflow
from agentmesh.tool_runtime.gateway import ToolRuntimeDescriptor


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class IdGenerator(Protocol):
    def new(self, prefix: str) -> str: ...


class ToolPortResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    payload: dict[str, Any]
    transport_request_id: str | None = Field(default=None, max_length=240)
    status_code: int | None = Field(default=200, ge=100, le=599)
    provider_operation_id: str | None = Field(default=None, max_length=240)


class SkillModelResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    payload: dict[str, Any]
    requested_provider: str = Field(min_length=1, max_length=120)
    requested_model: str = Field(min_length=1, max_length=120)
    actual_provider: str = Field(min_length=1, max_length=120)
    actual_model: str = Field(min_length=1, max_length=120)
    usage: dict[str, int] = Field(default_factory=dict)
    provider_receipt_id: str | None = Field(default=None, max_length=240)


class ToolPort(Protocol):
    def describe(self, tool_name: str) -> ToolRuntimeDescriptor | None: ...

    async def invoke(
        self,
        *,
        context: AgentMeshRunContext,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolPortResult: ...

    async def reconcile(
        self,
        *,
        operation_key: str,
        provider_operation_id: str | None,
    ) -> ToolPortResult | None: ...


class SkillModelPort(Protocol):
    async def generate(
        self,
        *,
        run: AgentRun,
        frozen_skill: FrozenSkillActor,
        model_policy: FrozenModelPolicy,
        resolved_input: dict[str, Any],
        evidence: list[dict[str, Any]],
        resources: list[dict[str, str]],
        timeout_seconds: int,
    ) -> SkillModelResult: ...


class ToolCapabilityGuard(Protocol):
    def validate(self, run: AgentRun, frozen_tool: FrozenToolActor) -> None: ...


class FrozenResourceLoader(Protocol):
    def load(self, run: AgentRun, frozen_skill: FrozenSkillActor, snapshot: object) -> list[dict[str, str]]: ...


class ResearchWorkflowRepository(Protocol):
    def get_research_workflow(self, run_id: str) -> ResearchWorkflow | None: ...

    def compare_and_swap_research_workflow(
        self,
        workflow: ResearchWorkflow,
        *,
        expected_state_version: int,
    ) -> bool: ...

    def apply_research_workflow_command(
        self,
        receipt: ResearchCommandReceipt,
        workflow: ResearchWorkflow,
        *,
        expected_state_version: int,
    ) -> tuple[ResearchCommandReceipt, ResearchWorkflow, bool]: ...

    def finish_research_workflow(
        self,
        run_id: str,
        *,
        expected_state_version: int,
        terminal_status: AgentRunStatus,
        error_code: str | None = None,
        output_text: str | None = None,
    ) -> tuple[ResearchWorkflow, AgentRun] | None: ...
