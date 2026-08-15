from __future__ import annotations

from typing import Protocol

from agentmesh.datasources import is_read_only_data_operation
from agentmesh.models import Agent, AgentToolGrant, ToolDefinition, User
from agentmesh.seed import AGENTS

DATA_QUERY_TOOL_ID = "tool_data_query"


class DataQueryAuthorizationError(PermissionError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class DataAuthorizationRepository(Protocol):
    def get_agent(self, agent_id: str) -> Agent | None: ...

    def get_tool_definition(self, tool_id: str) -> ToolDefinition | None: ...

    def list_agent_tool_grants(self, agent_id: str) -> list[AgentToolGrant]: ...


def authorize_data_query(
    repository: DataAuthorizationRepository,
    user: User,
    connector_name: str,
    operation: str,
) -> None:
    """Authorize the owning Personal Agent and read-only operation before connector execution."""
    agent = repository.get_agent(user.personal_agent_id) or next(
        (item for item in AGENTS if item.id == user.personal_agent_id),
        None,
    )
    if (
        agent is None
        or agent.agent_type != "personal"
        or agent.workspace_id != user.workspace_id
        or agent.owner_user_id != user.id
    ):
        raise DataQueryAuthorizationError(403, "Personal Agent does not control this data query")

    tool = repository.get_tool_definition(DATA_QUERY_TOOL_ID)
    grants = repository.list_agent_tool_grants(agent.id)
    if not (
        tool is not None
        and tool.enabled
        and any(grant.tool_id == DATA_QUERY_TOOL_ID and grant.enabled for grant in grants)
    ):
        raise DataQueryAuthorizationError(403, "Data query tool grant is required")

    if not is_read_only_data_operation(operation):
        raise DataQueryAuthorizationError(400, "Only allowlisted read-only data operations are supported")
    verb = operation.strip().lower().split(maxsplit=1)[0]
    if connector_name == "local_metrics" and verb != "query":
        raise DataQueryAuthorizationError(400, "local_metrics only supports explicit query operations")
