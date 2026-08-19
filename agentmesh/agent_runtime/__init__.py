"""OpenAI Agents SDK integration owned by AgentMesh."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentmesh.agent_runtime.service import AgentRuntimeService, RuntimeAnswer

__all__ = ["AgentRuntimeService", "RuntimeAnswer"]


def __getattr__(name: str) -> object:
    if name == "AgentRuntimeService":
        from agentmesh.agent_runtime.service import AgentRuntimeService

        return AgentRuntimeService
    if name == "RuntimeAnswer":
        from agentmesh.agent_runtime.service import RuntimeAnswer

        return RuntimeAnswer
    raise AttributeError(name)
