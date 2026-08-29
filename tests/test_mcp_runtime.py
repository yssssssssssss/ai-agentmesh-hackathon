from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from mcp.types import CallToolResult, GetPromptResult, ListPromptsResult, TextContent

from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    AgentToolGrant,
    ChatThread,
    SkillDefinition,
    SkillSourceScope,
    ToolDefinition,
)
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.skill_runtime.quiesce import (
    OrchestrationQuiesceController,
    OrchestrationQuiescingError,
)
from agentmesh.store import SQLiteStore, store
from agentmesh.tool_runtime.mcp import (
    AgentMeshMCPFactory,
    GovernedMCPServer,
    MCPConfigFile,
    MCPServerConfig,
    load_mcp_config,
)


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


def test_deepsearch_never_exposes_or_calls_an_mcp_server() -> None:
    run = AgentRun(
        id="run_deepsearch_mcp",
        thread_id="thread_deepsearch_mcp",
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        input_text="Research",
        status=AgentRunStatus.RUNNING,
        planning_mode=AgentPlanningMode.DEEPSEARCH,
    )
    context = _context().model_copy(
        update={
            "thread_id": run.thread_id,
            "run_id": run.id,
            "requirement_version_id": "requirement_deepsearch_mcp",
        }
    )
    repository = SimpleNamespace(get_agent_run=lambda _run_id: run)
    config = MCPConfigFile(
        servers=[
            MCPServerConfig(
                name="forbidden-deepsearch-mcp",
                tool_id="tool_web_research",
                allowed_tool_names=["web_research"],
                transport="stdio",
                command="never-started",
            )
        ]
    )

    assert AgentMeshMCPFactory(repository, config).build(  # type: ignore[arg-type]
        user=USER,
        context=context,
        allowed_tool_names={"web_research"},
    ) == []

    inner = _UnsafeInner()
    server = GovernedMCPServer(
        inner,
        repository=repository,  # type: ignore[arg-type]
        context=context,
        definition=ToolDefinition(
            id="tool_web_research",
            name="web_research",
            description="Must use the native DeepSearch gateway",
            category="research",
        ),
        allowed_tool_names={"web_research"},
    )
    result = asyncio.run(server.call_tool("web_research", {"query": "market"}))

    assert result.is_error is True
    assert "unavailable for DeepSearch" in result.content[0].text
    assert inner.calls == 0


def test_wiki_imported_skill_mcp_servers_are_fail_closed(tmp_path) -> None:
    _grant()
    config_path = tmp_path / "wiki-import-mcp.json"
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
                    }
                ]
            }
        )
    )
    factory = AgentMeshMCPFactory(store, load_mcp_config(config_path))
    imported = SkillDefinition(
        id="skill_wiki_import_mcp",
        name="wiki-import-mcp",
        title="Wiki import MCP",
        description="Imported Skill MCP policy",
        instructions="Use only explicitly mapped AgentMesh MCP servers.",
        source_path="tests/wiki-import-mcp/SKILL.md",
        source_scope=SkillSourceScope.BUILTIN,
        content_hash="wiki-import-mcp-hash",
        metadata={"agentmesh-wiki-import": "True"},
    )

    assert factory.build(user=USER, context=_context(), skill=imported) == []
    servers = factory.build(
        user=USER,
        context=_context(),
        skill=imported.model_copy(update={"requested_tools": ["mcp_test_gateway"]}),
    )
    assert len(servers) == 1
    assert servers[0].name == "local"
    assert factory.build(
        user=USER,
        context=_context(),
        skill=imported.model_copy(update={"requested_tools": ["Bash"]}),
    ) == []

    ungranted_user = USER.model_copy(update={"personal_agent_id": "agent_without_mcp_grant"})
    assert factory.build(
        user=ungranted_user,
        context=_context(),
        skill=imported.model_copy(update={"requested_tools": ["mcp_test_gateway"]}),
    ) == []


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

    def __init__(self) -> None:
        self.calls = 0

    async def connect(self):
        return None

    async def cleanup(self):
        return None

    async def list_tools(self, run_context=None, agent=None):
        del run_context, agent
        return []

    async def call_tool(self, tool_name, arguments, meta=None):
        del tool_name, arguments, meta
        self.calls += 1
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
    context = _context()
    ensure_base_workspace_data(store)
    store.save_user(USER)
    store.add_chat_thread(
        ChatThread(
            id=context.thread_id,
            workspace_id=context.workspace_id,
            project_id=context.project_id,
            user_id=context.user_id,
            title="MCP guardrail",
        )
    )
    store.save_agent_run(
        AgentRun(
            id=context.run_id,
            thread_id=context.thread_id,
            user_id=context.user_id,
            workspace_id=context.workspace_id,
            project_id=context.project_id,
            input_text="MCP guardrail",
            status=AgentRunStatus.RUNNING,
        )
    )
    definition = ToolDefinition(
        id="tool_mcp_guardrail",
        name="mcp_guardrail",
        description="Guardrail",
        category="integration",
        side_effect="external",
    )
    store.save_tool_definition(definition)
    store.save_agent_tool_grant(
        AgentToolGrant(
            id="grant_mcp_guardrail",
            agent_id=USER.personal_agent_id,
            tool_id=definition.id,
            granted_by="test",
        )
    )
    inner = _UnsafeInner()
    server = GovernedMCPServer(
        inner,
        repository=store,
        context=context,
        definition=definition,
        allowed_tool_names={"lookup"},
    )

    result = asyncio.run(server.call_tool("lookup", {}))

    assert result.is_error is True
    assert "withheld" in result.content[0].text
    assert "leaked-provider-token" not in result.model_dump_json()
    assert inner.calls == 1
    claims, outcomes = store.list_runtime_tool_call_history(context.run_id)
    assert len(claims) == len(outcomes) == 1
    assert outcomes[0].outcome == "settled"


def test_governed_mcp_quiesce_rejects_before_claim_or_provider_call(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "quiesced-mcp.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    context = _context().model_copy(
        update={"thread_id": "thread_quiesced_mcp", "run_id": "run_quiesced_mcp"}
    )
    repository.save_agent_run(
        AgentRun(
            id=context.run_id,
            thread_id=context.thread_id,
            user_id=context.user_id,
            workspace_id=context.workspace_id,
            project_id=context.project_id,
            input_text="invoke MCP",
            status=AgentRunStatus.RUNNING,
        )
    )
    definition = repository.save_tool_definition(
        ToolDefinition(
            id="tool_quiesced_mcp",
            name="quiesced_mcp",
            description="Quiesced MCP test",
            category="integration",
            side_effect="external",
        )
    )
    repository.save_agent_tool_grant(
        AgentToolGrant(
            id="grant_quiesced_mcp",
            agent_id=USER.personal_agent_id,
            tool_id=definition.id,
            granted_by="test",
        )
    )
    controller = OrchestrationQuiesceController()
    asyncio.run(controller.begin_quiesce())
    inner = _UnsafeInner()
    server = GovernedMCPServer(
        inner,
        repository=repository,
        context=context,
        definition=definition,
        allowed_tool_names={"lookup"},
        admission=controller,
    )

    with pytest.raises(OrchestrationQuiescingError):
        asyncio.run(server.call_tool("lookup", {}))

    assert inner.calls == 0
    assert repository.list_runtime_tool_call_history(context.run_id) == ([], [])


def test_governed_mcp_rechecks_project_membership_before_call(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "revoked-mcp.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    context = _context().model_copy(
        update={"thread_id": "thread_revoked_mcp", "run_id": "run_revoked_mcp"}
    )
    repository.add_chat_thread(
        ChatThread(
            id=context.thread_id,
            workspace_id=context.workspace_id,
            project_id=context.project_id,
            user_id=context.user_id,
            title="Revoked MCP access",
        )
    )
    repository.save_agent_run(
        AgentRun(
            id=context.run_id,
            thread_id=context.thread_id,
            user_id=context.user_id,
            workspace_id=context.workspace_id,
            project_id=context.project_id,
            input_text="invoke MCP",
            status=AgentRunStatus.RUNNING,
        )
    )
    project = repository.get_project(context.project_id)
    assert project is not None
    repository.save_project(project.model_copy(update={"member_ids": ["another_user"]}))
    inner = _UnsafeInner()
    server = GovernedMCPServer(
        inner,
        repository=repository,
        context=context,
        definition=ToolDefinition(
            id="tool_revoked_mcp",
            name="revoked_mcp",
            description="Revoked MCP test",
            category="integration",
            side_effect="external",
        ),
        allowed_tool_names={"lookup"},
    )

    result = asyncio.run(server.call_tool("lookup", {}))

    assert result.is_error is True
    assert "project access was revoked" in result.content[0].text
    assert inner.calls == 0


def test_governed_mcp_rechecks_grant_immediately_before_call(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "revoked-mcp-grant.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    context = _context().model_copy(
        update={"thread_id": "thread_revoked_mcp_grant", "run_id": "run_revoked_mcp_grant"}
    )
    repository.add_chat_thread(
        ChatThread(
            id=context.thread_id,
            workspace_id=context.workspace_id,
            project_id=context.project_id,
            user_id=context.user_id,
            title="Revoked MCP grant",
        )
    )
    repository.save_agent_run(
        AgentRun(
            id=context.run_id,
            thread_id=context.thread_id,
            user_id=context.user_id,
            workspace_id=context.workspace_id,
            project_id=context.project_id,
            input_text="invoke MCP after grant revocation",
            status=AgentRunStatus.RUNNING,
        )
    )
    definition = repository.save_tool_definition(
        ToolDefinition(
            id="tool_revoked_mcp_grant",
            name="revoked_mcp_grant",
            description="Must stop when its grant is revoked",
            category="integration",
            side_effect="external",
        )
    )
    grant = repository.save_agent_tool_grant(
        AgentToolGrant(
            id="grant_revoked_mcp_grant",
            agent_id=USER.personal_agent_id,
            tool_id=definition.id,
            granted_by="test",
        )
    )
    inner = _UnsafeInner()
    server = GovernedMCPServer(
        inner,
        repository=repository,
        context=context,
        definition=definition,
        allowed_tool_names={"lookup"},
    )
    repository.save_agent_tool_grant(grant.model_copy(update={"enabled": False}))

    result = asyncio.run(server.call_tool("lookup", {}))

    assert result.is_error is True
    assert "tool grant was revoked" in result.content[0].text
    assert inner.calls == 0
