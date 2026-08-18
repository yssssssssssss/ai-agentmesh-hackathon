from __future__ import annotations

import asyncio
import json

import pytest
from mcp.types import CallToolResult, GetPromptResult, ListPromptsResult, TextContent

from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.models import AgentToolGrant, ToolDefinition
from agentmesh.seed import USER
from agentmesh.store import store
from agentmesh.tool_runtime.mcp import AgentMeshMCPFactory, GovernedMCPServer, load_mcp_config


def _context() -> AgentMeshRunContext:
    return AgentMeshRunContext(
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        thread_id="thread_mcp_test",
        run_id="run_mcp_test",
    )


def _grant() -> None:
    store.save_tool_definition(
        ToolDefinition(
            id="tool_mcp_test",
            name="mcp_test_gateway",
            description="Governed test MCP server",
            category="integration",
            side_effect="external",
        )
    )
    store.save_agent_tool_grant(
        AgentToolGrant(
            id="grant_mcp_test",
            agent_id=USER.personal_agent_id,
            tool_id="tool_mcp_test",
            granted_by="test",
        )
    )


def test_mcp_is_disabled_without_admin_config(monkeypatch) -> None:
    monkeypatch.delenv("AGENTMESH_MCP_CONFIG", raising=False)
    assert load_mcp_config().servers == []
    assert AgentMeshMCPFactory(store).build(user=USER, context=_context()) == []


def test_mcp_config_builds_only_granted_governed_servers(tmp_path, monkeypatch) -> None:
    _grant()
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "name": "local",
                        "tool_id": "tool_mcp_test",
                        "allowed_tool_names": ["lookup"],
                        "transport": "stdio",
                        "command": "python",
                        "args": ["server.py"],
                    },
                    {
                        "name": "remote",
                        "tool_id": "tool_not_granted",
                        "allowed_tool_names": ["write"],
                        "transport": "streamable_http",
                        "url": "https://mcp.example/api",
                        "headers": {"Authorization": "$MCP_TEST_TOKEN"},
                    },
                ]
            }
        )
    )
    monkeypatch.setenv("MCP_TEST_TOKEN", "test-token")

    servers = AgentMeshMCPFactory(store, load_mcp_config(config_path)).build(user=USER, context=_context())

    assert len(servers) == 1
    assert isinstance(servers[0], GovernedMCPServer)
    assert servers[0].name == "local"
    assert servers[0].allowed_tool_names == {"lookup"}


def test_mcp_config_rejects_unresolved_header_secret(tmp_path, monkeypatch) -> None:
    _grant()
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "name": "remote",
                        "tool_id": "tool_mcp_test",
                        "allowed_tool_names": ["lookup"],
                        "transport": "streamable_http",
                        "url": "https://mcp.example/api",
                        "headers": {"Authorization": "$MISSING_MCP_TOKEN"},
                    }
                ]
            }
        )
    )
    monkeypatch.delenv("MISSING_MCP_TOKEN", raising=False)

    with pytest.raises(ValueError, match="unresolved header secret"):
        AgentMeshMCPFactory(store, load_mcp_config(config_path)).build(user=USER, context=_context())


class _UnsafeInner:
    name = "unsafe"

    async def connect(self):
        return None

    async def cleanup(self):
        return None

    async def list_tools(self, run_context=None, agent=None):
        del run_context, agent
        return []

    async def call_tool(self, tool_name, arguments, meta=None):
        del tool_name, arguments, meta
        return CallToolResult(content=[TextContent(text="Authorization: Bearer leaked-provider-token")])

    async def list_prompts(self):
        return ListPromptsResult(prompts=[])

    async def get_prompt(self, name, arguments=None):
        del name, arguments
        return GetPromptResult(description="test", messages=[])

    async def list_resources(self, cursor=None):
        raise NotImplementedError

    async def read_resource(self, uri):
        raise NotImplementedError

    async def list_resource_templates(self, cursor=None):
        raise NotImplementedError


def test_governed_mcp_withholds_secret_output() -> None:
    definition = ToolDefinition(
        id="tool_mcp_guardrail",
        name="mcp_guardrail",
        description="Guardrail",
        category="integration",
        side_effect="external",
    )
    server = GovernedMCPServer(
        _UnsafeInner(),
        repository=store,
        context=_context(),
        definition=definition,
        allowed_tool_names={"lookup"},
    )

    result = asyncio.run(server.call_tool("lookup", {}))

    assert result.is_error is True
    assert "withheld" in result.content[0].text
    assert "leaked-provider-token" not in result.model_dump_json()
