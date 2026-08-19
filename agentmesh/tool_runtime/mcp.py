from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from agents.mcp import MCPServer, MCPServerStdio, MCPServerStreamableHttp
from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, Field

from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.models import AgentRunStatus, Artifact, AuditEvent, SkillDefinition, ToolDefinition, User
from agentmesh.store import SQLiteStore
from agentmesh.tool_runtime.guardrails import contains_credential, unsafe_tool_output_reason
from agentmesh.tools import list_agent_tools

_MAX_MCP_OUTPUT_BYTES = 50 * 1024


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
    ):
        super().__init__(require_approval="always")
        self.inner = inner
        self.repository = repository
        self.context = context
        self.definition = definition
        self.allowed_tool_names = allowed_tool_names

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
        tools = await self.inner.list_tools(run_context, agent)
        return [tool for tool in tools if tool.name in self.allowed_tool_names]

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None,
        meta: dict[str, Any] | None = None,
    ) -> CallToolResult:
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
        self.repository.add_audit_event(
            AuditEvent(
                actor=self.context.user_id,
                action="sdk_mcp_tool_started",
                target_type="tool_definition",
                target_id=self.definition.id,
                workspace_id=self.context.workspace_id,
                project_id=self.context.project_id,
                metadata={"run_id": self.context.run_id, "server": self.name, "tool_name": tool_name},
            )
        )
        result = await self.inner.call_tool(tool_name, arguments, meta)
        output = result.model_dump_json(by_alias=True)
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
            return CallToolResult(content=[TextContent(text="MCP tool output was withheld by AgentMesh policy.")], isError=True)
        artifact_id = ""
        if len(output.encode("utf-8")) > _MAX_MCP_OUTPUT_BYTES:
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
    def __init__(self, repository: SQLiteStore, config: MCPConfigFile | None = None):
        self.repository = repository
        self.config = config or load_mcp_config()

    def build(
        self,
        *,
        user: User,
        context: AgentMeshRunContext,
        skill: SkillDefinition | None = None,
        allowed_tool_names: set[str] | None = None,
    ) -> list[MCPServer]:
        granted = {tool.id: tool for tool in list_agent_tools(self.repository, user.personal_agent_id)}
        requested = allowed_tool_names
        if requested is None:
            requested = set(skill.requested_tools) if skill and skill.requested_tools else None
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
                )
            )
        return servers
