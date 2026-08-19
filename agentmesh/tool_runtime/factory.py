from __future__ import annotations

import asyncio
import json
from typing import Any

from agents import FunctionTool
from agents.strict_schema import ensure_strict_json_schema

from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.agent_runtime.settings import strict_tools_enabled
from agentmesh.models import AgentRunStatus, Artifact, AuditEvent, SkillDefinition, ToolDefinition, User
from agentmesh.risk import RiskDecision, assess_tool_request
from agentmesh.store import SQLiteStore
from agentmesh.tool_runtime.gateway import ToolGateway, collect_source_ids, encode_tool_output
from agentmesh.tool_runtime.guardrails import (
    quarantine_unsafe_output,
    reject_secret_arguments,
    unsafe_tool_output_reason,
)
from agentmesh.tools import list_agent_tools

_MAX_OUTPUT_BYTES = 50 * 1024
_MAX_OUTPUT_LINES = 2000


class AgentMeshToolFactory:
    def __init__(self, repository: SQLiteStore, gateway: ToolGateway | None = None):
        self.repository = repository
        self.gateway = gateway or ToolGateway(repository)

    def _registered_source_ids(self, value: Any, context: AgentMeshRunContext) -> list[str]:
        allowed: list[str] = []
        for source_id in sorted(collect_source_ids(value)):
            source = self.repository.get_source(source_id)
            if source is None:
                continue
            if (
                source.workspace_id == context.workspace_id
                and source.project_id == context.project_id
                and source.user_id == context.user_id
                and source.run_id == context.run_id
                and source.skill_id == context.skill_id
            ):
                allowed.append(source_id)
        return allowed

    def build(
        self,
        user: User,
        skill: SkillDefinition | None = None,
        *,
        allowed_tool_names: set[str] | None = None,
    ) -> list[FunctionTool]:
        handlers = self.gateway.handlers()
        requested = allowed_tool_names
        if requested is None:
            requested = set(skill.requested_tools) if skill and skill.requested_tools else None
        definitions = [
            definition
            for definition in list_agent_tools(self.repository, user.personal_agent_id)
            if definition.name in handlers and (requested is None or definition.name in requested)
        ]
        return [self._tool(definition, user) for definition in definitions]

    def _tool(self, definition: ToolDefinition, user: User) -> FunctionTool:
        handler = self.gateway.handlers()[definition.name]

        def is_enabled(ctx, _agent) -> bool:  # noqa: ANN001
            if not isinstance(ctx.context, AgentMeshRunContext) or ctx.context.user_id != user.id:
                return False
            return any(tool.id == definition.id for tool in list_agent_tools(self.repository, user.personal_agent_id))

        async def needs_approval(ctx, params: dict[str, Any], _call_id: str) -> bool:  # noqa: ANN001
            if not isinstance(ctx.context, AgentMeshRunContext):
                return True
            if definition.name == "risk_review":
                return False
            if definition.approval_required:
                return True
            if definition.side_effect != "read":
                return True
            assessment = assess_tool_request(json.dumps(params, ensure_ascii=False, default=str))
            return assessment.decision != RiskDecision.ALLOW

        async def invoke(ctx, raw_arguments: str) -> str:  # noqa: ANN001
            if not isinstance(ctx.context, AgentMeshRunContext):
                raise RuntimeError("AgentMesh run context is required")
            if not self.repository.user_can_execute_agent_run(
                ctx.context.user_id,
                ctx.context.run_id,
                allowed_statuses={AgentRunStatus.RUNNING},
            ):
                raise PermissionError("Agent run project access was revoked")
            if not any(
                tool.id == definition.id
                for tool in list_agent_tools(self.repository, user.personal_agent_id)
            ):
                raise PermissionError("Agent tool grant was revoked")
            arguments = json.loads(raw_arguments)
            if not isinstance(arguments, dict):
                raise ValueError("Tool arguments must be an object")
            self.repository.add_audit_event(
                AuditEvent(
                    actor=ctx.context.user_id,
                    action="sdk_tool_started",
                    target_type="tool_definition",
                    target_id=definition.id,
                    workspace_id=ctx.context.workspace_id,
                    project_id=ctx.context.project_id,
                    metadata={"run_id": ctx.context.run_id, "tool_name": definition.name, "argument_keys": sorted(arguments)},
                )
            )
            value = await asyncio.to_thread(handler, ctx.context, arguments)
            ctx.context.source_ids = list(
                dict.fromkeys([*ctx.context.source_ids, *self._registered_source_ids(value, ctx.context)])
            )
            output = encode_tool_output(value)
            unsafe_reason = unsafe_tool_output_reason(output)
            if unsafe_reason is not None:
                self.repository.add_audit_event(
                    AuditEvent(
                        actor=ctx.context.user_id,
                        action="sdk_tool_output_withheld",
                        target_type="tool_definition",
                        target_id=definition.id,
                        workspace_id=ctx.context.workspace_id,
                        project_id=ctx.context.project_id,
                        metadata={
                            "run_id": ctx.context.run_id,
                            "tool_name": definition.name,
                            "reason": unsafe_reason,
                        },
                    )
                )
                return "Tool output was withheld by AgentMesh policy."
            visible, artifact_id = self._bounded_output(ctx.context, definition, output)
            if artifact_id:
                ctx.context.artifact_ids = list(dict.fromkeys([*ctx.context.artifact_ids, artifact_id]))
            self.repository.add_audit_event(
                AuditEvent(
                    actor=ctx.context.user_id,
                    action="sdk_tool_completed",
                    target_type="tool_definition",
                    target_id=definition.id,
                    workspace_id=ctx.context.workspace_id,
                    project_id=ctx.context.project_id,
                    metadata={
                        "run_id": ctx.context.run_id,
                        "tool_name": definition.name,
                        "artifact_id": artifact_id or "",
                    },
                )
            )
            return visible

        return FunctionTool(
            name=definition.name,
            description=definition.description,
            params_json_schema=ensure_strict_json_schema(definition.input_schema),
            on_invoke_tool=invoke,
            strict_json_schema=strict_tools_enabled(),
            is_enabled=is_enabled,
            tool_input_guardrails=[reject_secret_arguments],
            tool_output_guardrails=[quarantine_unsafe_output],
            needs_approval=needs_approval,
            timeout_seconds=definition.timeout_seconds,
            timeout_behavior="error_as_result",
        )

    def _bounded_output(
        self,
        context: AgentMeshRunContext,
        definition: ToolDefinition,
        output: str,
    ) -> tuple[str, str | None]:
        lines = output.splitlines()
        encoded = output.encode("utf-8")
        if len(lines) <= _MAX_OUTPUT_LINES and len(encoded) <= _MAX_OUTPUT_BYTES:
            return output, None
        visible_lines = lines[:_MAX_OUTPUT_LINES]
        visible = "\n".join(visible_lines)
        visible_bytes = visible.encode("utf-8")
        if len(visible_bytes) > _MAX_OUTPUT_BYTES:
            visible = visible_bytes[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="ignore")
        artifact = self.repository.save_artifact(
            Artifact(
                run_id=context.run_id,
                workspace_id=context.workspace_id,
                project_id=context.project_id,
                user_id=context.user_id,
                artifact_type="tool_output",
                content_type="application/json",
                content=output,
                truncated=True,
            )
        )
        suffix = f"\n\n[Output truncated. Full result artifact: {artifact.id}]"
        return visible + suffix, artifact.id
