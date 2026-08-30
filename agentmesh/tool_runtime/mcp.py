from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal

from agents.mcp import MCPServer, MCPServerStdio, MCPServerStreamableHttp
from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, Field

from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.models import (
    AgentPlanningMode,
    AgentRunStatus,
    Artifact,
    AuditEvent,
    RuntimeToolCallClaimV1,
    RuntimeToolCallOutcomeV1,
    SkillDefinition,
    ToolDefinition,
    User,
)
from agentmesh.runtime_admission import current_orchestration_admission
from agentmesh.runtime_capacity import RuntimeCapacityController, current_runtime_capacity
from agentmesh.skill_runtime.quiesce import OrchestrationQuiesceController
from agentmesh.store import RuntimeToolCallConflict, SQLiteStore
from agentmesh.tool_runtime.guardrails import contains_credential, unsafe_tool_output_reason
from agentmesh.tools import list_agent_tools

_MAX_MCP_OUTPUT_BYTES = 50 * 1024
_MAX_MCP_PROVIDER_OUTPUT_BYTES = 1024 * 1024


def _is_deepsearch_context(repository: SQLiteStore, context: AgentMeshRunContext) -> bool:
    run = repository.get_agent_run(context.run_id)
    return context.requirement_version_id is not None or (
        run is not None and run.planning_mode is AgentPlanningMode.DEEPSEARCH
    )


def _is_wiki_import(skill: SkillDefinition | None) -> bool:
    return bool(
        skill
        and skill.metadata.get("agentmesh-wiki-import", "").strip().lower() in {"1", "true", "yes", "on"}
    )


class MCPServerConfig(BaseModel):
    name: str
    tool_id: str
    allowed_tool_names: list[str] = Field(min_length=1)
    transport: Literal["stdio", "streamable_http"]
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    # Retained for config compatibility. AgentMesh always requires approval for MCP calls.
    require_approval: bool = True
    cache_tools_list: bool = True


class MCPConfigFile(BaseModel):
    servers: list[MCPServerConfig] = Field(default_factory=list)


def _resolve_value(value: str) -> str:
    if value.startswith("$") and len(value) > 1:
        return os.getenv(value[1:], "")
    return value


def load_mcp_config(path: str | Path | None = None) -> MCPConfigFile:
    configured = Path(path or os.getenv("AGENTMESH_MCP_CONFIG", "")).expanduser() if (path or os.getenv("AGENTMESH_MCP_CONFIG")) else None
    if configured is None:
        return MCPConfigFile()
    payload = json.loads(configured.read_text(encoding="utf-8"))
    return MCPConfigFile.model_validate(payload)


class GovernedMCPServer(MCPServer):
    """MCP adapter that enforces AgentMesh approval, filtering, audit, and output policy."""

    def __init__(
        self,
        inner: MCPServer,
        *,
        repository: SQLiteStore,
        context: AgentMeshRunContext,
        definition: ToolDefinition,
        allowed_tool_names: set[str],
        admission: OrchestrationQuiesceController | None = None,
        capacity: RuntimeCapacityController | None = None,
    ):
        super().__init__(require_approval="always")
        self.inner = inner
        self.repository = repository
        self.context = context
        self.definition = definition
        self.allowed_tool_names = allowed_tool_names
        self.admission = admission or current_orchestration_admission()
        self.capacity = capacity or current_runtime_capacity()

    @property
    def name(self) -> str:
        return self.inner.name

    async def connect(self):  # noqa: ANN201
        return await self.inner.connect()

    async def cleanup(self):  # noqa: ANN201
        return await self.inner.cleanup()

    async def __aenter__(self) -> GovernedMCPServer:
        await self.inner.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        await self.inner.cleanup()

    async def list_tools(self, run_context=None, agent=None):  # noqa: ANN001, ANN201
        if _is_deepsearch_context(self.repository, self.context):
            return []
        tools = await self.inner.list_tools(run_context, agent)
        return [tool for tool in tools if tool.name in self.allowed_tool_names]

    def _claim(self, tool_name: str, arguments: dict[str, Any], meta: dict[str, Any] | None) -> RuntimeToolCallClaimV1:
        arguments_hash = hashlib.sha256(
            json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode(
                "utf-8"
            )
        ).hexdigest()
        raw_call_id = (meta or {}).get("call_id")
        call_id = raw_call_id if isinstance(raw_call_id, str) and raw_call_id else "mcp_call_" + canonical_json_sha256(
            {
                "run_id": self.context.run_id,
                "plan_id": self.context.plan_id,
                "node_id": self.context.node_id,
                "tool_definition_id": self.definition.id,
                "tool_name": tool_name,
                "arguments_hash": arguments_hash,
                "ordinal": self.context.tool_call_count,
            }
        )[:24]
        return RuntimeToolCallClaimV1(
            call_id=call_id,
            run_id=self.context.run_id,
            plan_id=self.context.plan_id,
            node_id=self.context.node_id,
            tool_definition_id=self.definition.id,
            tool_name=tool_name,
            implementation_id=self.definition.implementation_id or f"mcp:{self.name}",
            implementation_version=self.definition.implementation_version,
            side_effect=self.definition.side_effect,
            operation_identity=canonical_json_sha256(
                {
                    "run_id": self.context.run_id,
                    "plan_id": self.context.plan_id,
                    "node_id": self.context.node_id,
                    "call_id": call_id,
                    "tool_definition_id": self.definition.id,
                    "tool_name": tool_name,
                    "arguments_hash": arguments_hash,
                }
            ),
        )

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None,
        meta: dict[str, Any] | None = None,
    ) -> CallToolResult:
        if _is_deepsearch_context(self.repository, self.context):
            return CallToolResult(
                content=[TextContent(text="MCP tools are unavailable for DeepSearch.")],
                isError=True,
            )
        if not self.repository.user_can_execute_agent_run(
            self.context.user_id,
            self.context.run_id,
            allowed_statuses={AgentRunStatus.RUNNING},
        ):
            return CallToolResult(content=[TextContent(text="Agent run project access was revoked.")], isError=True)
        user = self.repository.get_user(self.context.user_id)
        if user is None or not any(
            tool.id == self.definition.id
            for tool in list_agent_tools(self.repository, user.personal_agent_id)
        ):
            return CallToolResult(content=[TextContent(text="Agent tool grant was revoked.")], isError=True)
        if tool_name not in self.allowed_tool_names:
            return CallToolResult(content=[TextContent(text="MCP tool is not granted by AgentMesh.")], isError=True)
        raw_arguments = json.dumps(arguments or {}, ensure_ascii=False, default=str)
        if contains_credential(raw_arguments):
            return CallToolResult(content=[TextContent(text="MCP tool arguments were withheld by policy.")], isError=True)
        claim = self._claim(tool_name, arguments or {}, meta)
        await self.capacity.acquire_tool()
        try:
            if not self.repository.user_can_execute_agent_run(
                self.context.user_id,
                self.context.run_id,
                allowed_statuses={AgentRunStatus.RUNNING},
            ):
                raise PermissionError("Agent run project access was revoked")
            current_user = self.repository.get_user(self.context.user_id)
            if current_user is None or not any(
                tool.id == self.definition.id
                for tool in list_agent_tools(
                    self.repository,
                    current_user.personal_agent_id,
                )
            ):
                raise PermissionError("Agent tool grant was revoked")
            if tool_name not in self.allowed_tool_names:
                raise PermissionError("MCP tool is not granted by AgentMesh")
            with self.admission.permit():
                claimed = self.repository.claim_runtime_tool_call(claim)
        except BaseException:
            self.capacity.release_tool()
            raise
        if not claimed:
            self.capacity.release_tool()
            raise RuntimeToolCallConflict("tool_call_already_claimed")
        try:
            self.repository.add_audit_event(
                AuditEvent(
                    actor=self.context.user_id,
                    action="sdk_mcp_tool_started",
                    target_type="tool_definition",
                    target_id=self.definition.id,
                    workspace_id=self.context.workspace_id,
                    project_id=self.context.project_id,
                    metadata={
                        "run_id": self.context.run_id,
                        "server": self.name,
                        "tool_name": tool_name,
                    },
                )
            )
        except BaseException:
            try:
                self.repository.finish_runtime_tool_call(
                    RuntimeToolCallOutcomeV1(
                        call_id=claim.call_id,
                        run_id=claim.run_id,
                        outcome=("abandoned" if self.definition.side_effect == "read" else "outcome_unknown"),
                        error_code=(
                            "process_restarted"
                            if self.definition.side_effect == "read"
                            else "external_outcome_unknown"
                        ),
                    )
                )
            finally:
                self.capacity.release_tool()
            raise
        try:
            result = await self.inner.call_tool(tool_name, arguments, meta)
            output = result.model_dump_json(by_alias=True)
            if len(output.encode("utf-8")) > _MAX_MCP_PROVIDER_OUTPUT_BYTES:
                raise RuntimeError("mcp_output_limit_exceeded")
            unsafe_reason = unsafe_tool_output_reason(output)
            if unsafe_reason is not None:
                self.repository.add_audit_event(
                    AuditEvent(
                        actor=self.context.user_id,
                        action="sdk_mcp_tool_output_withheld",
                        target_type="tool_definition",
                        target_id=self.definition.id,
                        workspace_id=self.context.workspace_id,
                        project_id=self.context.project_id,
                        metadata={
                            "run_id": self.context.run_id,
                            "server": self.name,
                            "tool_name": tool_name,
                            "reason": unsafe_reason,
                        },
                    )
                )
                result = CallToolResult(
                    content=[TextContent(text="MCP tool output was withheld by AgentMesh policy.")],
                    isError=True,
                )
            artifact_id = ""
            if unsafe_reason is None and len(output.encode("utf-8")) > _MAX_MCP_OUTPUT_BYTES:
                artifact = self.repository.save_artifact(
                    Artifact(
                        run_id=self.context.run_id,
                        workspace_id=self.context.workspace_id,
                        project_id=self.context.project_id,
                        user_id=self.context.user_id,
                        artifact_type="mcp_tool_output",
                        content_type="application/json",
                        content=output,
                        truncated=True,
                    )
                )
                artifact_id = artifact.id
                visible = output.encode("utf-8")[:_MAX_MCP_OUTPUT_BYTES].decode("utf-8", errors="ignore")
                result = CallToolResult(
                    content=[TextContent(text=f"{visible}\n\n[Output truncated. Full result artifact: {artifact.id}]")],
                    isError=result.is_error,
                )
            self.repository.add_audit_event(
                AuditEvent(
                    actor=self.context.user_id,
                    action="sdk_mcp_tool_completed",
                    target_type="tool_definition",
                    target_id=self.definition.id,
                    workspace_id=self.context.workspace_id,
                    project_id=self.context.project_id,
                    metadata={
                        "run_id": self.context.run_id,
                        "server": self.name,
                        "tool_name": tool_name,
                        "artifact_id": artifact_id,
                    },
                )
            )
        except BaseException:
            try:
                self.repository.finish_runtime_tool_call(
                    RuntimeToolCallOutcomeV1(
                        call_id=claim.call_id,
                        run_id=claim.run_id,
                        outcome=("abandoned" if self.definition.side_effect == "read" else "outcome_unknown"),
                        error_code=(
                            "process_restarted"
                            if self.definition.side_effect == "read"
                            else "external_outcome_unknown"
                        ),
                    )
                )
            finally:
                self.capacity.release_tool()
            raise
        try:
            self.repository.finish_runtime_tool_call(
                RuntimeToolCallOutcomeV1(
                    call_id=claim.call_id,
                    run_id=claim.run_id,
                    outcome="settled",
                    result_hash=hashlib.sha256(output.encode("utf-8")).hexdigest(),
                )
            )
        finally:
            self.capacity.release_tool()
        return result

    async def list_prompts(self):  # noqa: ANN201
        return await self.inner.list_prompts()

    async def get_prompt(self, name: str, arguments: dict[str, Any] | None = None):  # noqa: ANN201
        return await self.inner.get_prompt(name, arguments)

    async def list_resources(self, cursor: str | None = None):  # noqa: ANN201
        return await self.inner.list_resources(cursor)

    async def read_resource(self, uri: str):  # noqa: ANN201
        return await self.inner.read_resource(uri)

    async def list_resource_templates(self, cursor: str | None = None):  # noqa: ANN201
        return await self.inner.list_resource_templates(cursor)


class AgentMeshMCPFactory:
    def __init__(
        self,
        repository: SQLiteStore,
        config: MCPConfigFile | None = None,
        admission: OrchestrationQuiesceController | None = None,
        capacity: RuntimeCapacityController | None = None,
    ):
        self.repository = repository
        self.config = config or load_mcp_config()
        self.admission = admission or current_orchestration_admission()
        self.capacity = capacity or current_runtime_capacity()

    def set_capacity_controller(self, capacity: RuntimeCapacityController) -> None:
        self.capacity = capacity

    def set_admission_controller(self, admission: OrchestrationQuiesceController) -> None:
        self.admission = admission

    def build(
        self,
        *,
        user: User,
        context: AgentMeshRunContext,
        skill: SkillDefinition | None = None,
        allowed_tool_names: set[str] | None = None,
    ) -> list[MCPServer]:
        if _is_deepsearch_context(self.repository, context):
            return []
        granted = {tool.id: tool for tool in list_agent_tools(self.repository, user.personal_agent_id)}
        requested = allowed_tool_names
        if requested is None:
            if skill and skill.requested_tools:
                requested = set(skill.requested_tools)
            elif _is_wiki_import(skill):
                requested = set()
        servers: list[MCPServer] = []
        for config in self.config.servers:
            definition = granted.get(config.tool_id)
            if definition is None or (requested is not None and definition.name not in requested):
                continue
            if config.transport == "stdio":
                if not config.command:
                    raise ValueError(f"MCP stdio server '{config.name}' is missing command")
                inner: MCPServer = MCPServerStdio(
                    params={"command": config.command, "args": config.args, "env": None},
                    name=config.name,
                    cache_tools_list=config.cache_tools_list,
                    require_approval="always",
                )
            else:
                if not config.url:
                    raise ValueError(f"MCP HTTP server '{config.name}' is missing url")
                headers = {key: _resolve_value(value) for key, value in config.headers.items()}
                if any(not value for value in headers.values()):
                    raise ValueError(f"MCP HTTP server '{config.name}' has an unresolved header secret")
                inner = MCPServerStreamableHttp(
                    params={"url": config.url, "headers": headers},
                    name=config.name,
                    cache_tools_list=config.cache_tools_list,
                    require_approval="always",
                )
            servers.append(
                GovernedMCPServer(
                    inner,
                    repository=self.repository,
                    context=context,
                    definition=definition,
                    allowed_tool_names=set(config.allowed_tool_names),
                    admission=self.admission,
                    capacity=self.capacity,
                )
            )
        return servers
