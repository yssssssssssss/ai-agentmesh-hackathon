"""OpenAI Agents SDK FunctionTool adapters governed by AgentMesh."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentmesh.tool_runtime.factory import AgentMeshToolFactory
    from agentmesh.tool_runtime.gateway import ToolGateway

__all__ = ["AgentMeshToolFactory", "ToolGateway"]


def __getattr__(name: str) -> object:
    if name == "AgentMeshToolFactory":
        from agentmesh.tool_runtime.factory import AgentMeshToolFactory

        return AgentMeshToolFactory
    if name == "ToolGateway":
        from agentmesh.tool_runtime.gateway import ToolGateway

        return ToolGateway
    raise AttributeError(name)
