from __future__ import annotations

from agentmesh.memory_context.contracts import RunFactQueryV1
from agentmesh.memory_context.procedure_context import ProcedureQueryV1
from agentmesh.models import AgentToolGrant, ToolDefinition, User
from agentmesh.o2 import O2RegistryAdapter
from agentmesh.store import SQLiteStore
from agentmesh.task_operations.contracts import ProjectStateQueryV1

WEB_RESEARCH_OUTPUT_SCHEMA = {
    "type": "object",
    "required": [
        "title",
        "content",
        "sources",
        "source_evidence",
        "provider_calls",
        "permission",
        "metadata",
    ],
    "properties": {
        "title": {"type": "string", "minLength": 1},
        "content": {"type": "string", "minLength": 1},
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "id",
                    "title",
                    "source_type",
                    "reference",
                    "workspace_id",
                    "project_id",
                    "user_id",
                    "run_id",
                    "skill_id",
                    "created_at",
                ],
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "title": {"type": "string", "minLength": 1},
                    "source_type": {"type": "string", "minLength": 1},
                    "reference": {"type": "string", "minLength": 1},
                    "workspace_id": {"type": ["string", "null"]},
                    "project_id": {"type": ["string", "null"]},
                    "user_id": {"type": ["string", "null"]},
                    "run_id": {"type": ["string", "null"]},
                    "skill_id": {"type": ["string", "null"]},
                    "created_at": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "source_evidence": {
            "type": "array",
            "maxItems": 100,
            "items": {
                "type": "object",
                "required": [
                    "source_id",
                    "content_provider",
                    "excerpt",
                    "retrieved_at",
                    "content_hash",
                    "truncated",
                    "risk_flags",
                    "question_ids",
                ],
                "properties": {
                    "source_id": {"type": "string", "minLength": 1, "maxLength": 120},
                    "content_provider": {"type": "string", "minLength": 1, "maxLength": 120},
                    "excerpt": {"type": "string", "minLength": 1, "maxLength": 8192},
                    "retrieved_at": {"type": "string"},
                    "content_hash": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                    "truncated": {"type": "boolean"},
                    "risk_flags": {
                        "type": "array",
                        "maxItems": 10,
                        "items": {"type": "string"},
                    },
                    "question_ids": {
                        "type": "array",
                        "maxItems": 20,
                        "items": {"type": "string", "minLength": 1, "maxLength": 120},
                    },
                },
                "additionalProperties": False,
            },
        },
        "provider_calls": {
            "type": "array",
            "maxItems": 20,
            "items": {
                "type": "object",
                "required": [
                    "provider",
                    "operation",
                    "request_hash",
                    "status",
                    "latency_ms",
                    "result_count",
                    "error_code",
                ],
                "properties": {
                    "provider": {"type": "string", "minLength": 1, "maxLength": 120},
                    "operation": {"type": "string", "minLength": 1, "maxLength": 80},
                    "request_hash": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                    "status": {"type": "string", "enum": ["success", "error"]},
                    "latency_ms": {"type": "number", "minimum": 0},
                    "result_count": {"type": "integer", "minimum": 0},
                    "error_code": {"type": ["string", "null"], "maxLength": 120},
                },
                "additionalProperties": False,
            },
        },
        "permission": {"type": "string", "minLength": 1},
        "metadata": {"type": "object", "additionalProperties": {"type": "string"}},
    },
    "additionalProperties": False,
}

ZERO_DESIGN_READ_TOOL_ID = "tool_zero_design_read"


SYSTEM_TOOLS = [
    ToolDefinition(
        id="tool_project_state",
        name="project_state",
        description="从当前授权项目的 Task/Review SQL 查询真实任务统计。指定真实 task_id 可查询状态与依赖；"
                    "不从聊天估算完成数，不查询历史或其他项目。project_id 传 null 使用当前项目。",
        category="data",
        risk_level="low",
        side_effect="read",
        implementation_id="agentmesh.tool_runtime.gateway.ToolGateway.project_state",
        implementation_version="1",
        input_schema=ProjectStateQueryV1.model_json_schema(),
    ),
    ToolDefinition(
        id=ZERO_DESIGN_READ_TOOL_ID,
        name="zero_design_read",
        description="通过用户本地 Zero MCP 读取 Relay 设计元数据、上下文、截图、变量和资源。",
        category="design",
        risk_level="medium",
        side_effect="read",
        implementation_id="mcp.zero-design.read",
        implementation_version="1",
        idempotency_support="none",
        approval_required=True,
        input_schema={"type": "object", "additionalProperties": True},
    ),
    ToolDefinition(
        id="tool_memory_search",
        name="memory_search",
        description="检索个人、项目和团队记忆。明确实体/谓词/时间的事实用 fact_query；冲突或无证据时不猜答案。",
        category="memory",
        implementation_version="3",
        risk_level="low",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "要检索的记忆或经验"},
                "fact_query": {"anyOf": [RunFactQueryV1.model_json_schema(), {"type": "null"}],
                               "description": "明确事实查询。project_id 默认当前项目；project/task 的 subject_id 默认当前项目/任务。"
                                              "user/term 必须指定真实 ID，不能猜姓名。普通检索传 null。"},
                "procedure_query": {"anyOf": [ProcedureQueryV1.model_json_schema(), {"type": "null"}],
                                    "description": "按真实记忆 ID 检查已验收经验；目标来自当前 Run，工具授权和版本会重检。"
                                                   "与 fact_query 互斥；普通检索传 null。"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    ToolDefinition(
        id="tool_web_research",
        name="web_research",
        description="通过已配置的 Research provider 检索外部资料并返回来源。",
        category="research",
        risk_level="medium",
        side_effect="read",
        implementation_id="agentmesh.tool_runtime.gateway.ToolGateway.web_research",
        implementation_version="1",
        idempotency_support="none",
        approval_required=True,
        evidence_class="provider_summary",
        timeout_seconds=120,
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "要调研的主题"},
                "question_queries": {
                    "type": "array",
                    "maxItems": 4,
                    "items": {
                        "type": "object",
                        "required": ["query", "question_ids"],
                        "properties": {
                            "query": {"type": "string", "minLength": 1, "maxLength": 4000},
                            "question_ids": {
                                "type": "array",
                                "maxItems": 20,
                                "items": {"type": "string", "minLength": 1, "maxLength": 120},
                            },
                        },
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        output_schema=WEB_RESEARCH_OUTPUT_SCHEMA,
    ),
    ToolDefinition(
        id="tool_local_file_read",
        name="local_file_read",
        description="读取本地 Runner 明确授权目录中的 UTF-8 文本文件。",
        category="local_runner",
        risk_level="low",
        provider="local_runner",
        side_effect="read",
        implementation_id="runner:local_file_read",
        implementation_version="1",
        approval_required=False,
        timeout_seconds=15,
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "位于 Runner 授权根目录中的文件路径",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    ),
    ToolDefinition(
        id="tool_document_upload",
        name="document_upload",
        description="上传并解析用户提供的项目文档。",
        category="document",
        risk_level="medium",
        side_effect="write",
        input_schema={
            "type": "object",
            "properties": {"document_id": {"type": "string"}},
            "required": ["document_id"],
            "additionalProperties": False,
        },
    ),
    ToolDefinition(
        id="tool_document_search",
        name="document_search",
        description="在当前用户可访问的已解析项目文档中检索内容。",
        category="document",
        risk_level="low",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "要检索的文档内容"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    ToolDefinition(
        id="tool_risk_review",
        name="risk_review",
        description="检查外部来源、素材授权和高风险动作。",
        category="risk",
        risk_level="high",
        input_schema={
            "type": "object",
            "properties": {"content": {"type": "string", "description": "要检查的内容或操作"}},
            "required": ["content"],
            "additionalProperties": False,
        },
    ),
    ToolDefinition(
        id="tool_data_query",
        name="data_query",
        description="通过获准的数据连接器执行只读查询。",
        category="data",
        risk_level="medium",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "指标、时间范围和分析问题"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
]

DEFAULT_TOOL_GRANTS = {
    "agent_personal_current": ["tool_memory_search", "tool_project_state", "tool_data_query", "tool_web_research"],

    "agent_personal_lead": ["tool_memory_search", "tool_project_state", "tool_risk_review", "tool_data_query"],
    "agent_personal_admin": ["tool_memory_search", "tool_project_state", "tool_risk_review", "tool_data_query"],
    "agent_research": ["tool_memory_search", "tool_web_research"],
    "agent_data": ["tool_memory_search"],
    "agent_risk": ["tool_risk_review"],
}


def ensure_tool_seed_data(repository: SQLiteStore, granted_by: str) -> None:
    for tool in SYSTEM_TOOLS:
        existing = repository.get_tool_definition(tool.id)
        if existing is None:
            repository.save_tool_definition(tool)
            continue
        updated = tool.model_copy(deep=True)
        updated.enabled = existing.enabled
        updated.created_at = existing.created_at
        updated.updated_at = existing.updated_at
        repository.save_tool_definition(updated)

    for agent_id, tool_ids in DEFAULT_TOOL_GRANTS.items():
        existing_tool_ids = {grant.tool_id for grant in repository.list_agent_tool_grants(agent_id)}
        for tool_id in tool_ids:
            if tool_id not in existing_tool_ids:
                repository.save_agent_tool_grant(
                    AgentToolGrant(agent_id=agent_id, tool_id=tool_id, granted_by=granted_by)
                )


def list_enabled_tools(repository: SQLiteStore) -> list[ToolDefinition]:
    ensure_tool_seed_data(repository, granted_by="system")
    return [tool for tool in repository.tool_definitions if tool.enabled]


def list_agent_tools(repository: SQLiteStore, agent_id: str) -> list[ToolDefinition]:
    ensure_tool_seed_data(repository, granted_by="system")
    tools_by_id = {tool.id: tool for tool in repository.tool_definitions}
    result = []
    seen_tool_ids: set[str] = set()
    for grant in repository.list_agent_tool_grants(agent_id):
        tool = tools_by_id.get(grant.tool_id)
        if grant.enabled and tool is not None and tool.enabled and tool.id not in seen_tool_ids:
            result.append(tool)
            seen_tool_ids.add(tool.id)
    return result


def set_agent_tools(repository: SQLiteStore, agent_id: str, tool_ids: list[str], user: User) -> list[ToolDefinition]:
    ensure_tool_seed_data(repository, granted_by="system")
    requested = {tool_id for tool_id in tool_ids if tool_id}
    existing_tools = {tool.id for tool in repository.tool_definitions if tool.enabled}
    unknown = sorted(requested - existing_tools)
    if unknown:
        raise ValueError(f"Unknown or disabled tools: {', '.join(unknown)}")

    existing_grants = {grant.tool_id: grant for grant in repository.list_agent_tool_grants(agent_id)}
    for tool_id in existing_tools:
        grant = existing_grants.get(tool_id)
        should_enable = tool_id in requested
        if grant is None and should_enable:
            repository.save_agent_tool_grant(AgentToolGrant(agent_id=agent_id, tool_id=tool_id, granted_by=user.id))
            continue
        if grant is not None and grant.enabled != should_enable:
            grant.enabled = should_enable
            grant.granted_by = user.id
            repository.save_agent_tool_grant(grant)
    return list_agent_tools(repository, agent_id)


def sync_o2_tools(repository: SQLiteStore, user: User, limit: int = 50) -> list[ToolDefinition]:
    return O2RegistryAdapter().sync_tools(repository, granted_by=user.id, limit=limit)
