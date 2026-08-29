from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any, Literal

from agents import FunctionTool
from agents.strict_schema import ensure_strict_json_schema

from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.agent_runtime.settings import strict_tools_enabled
from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.deepsearch.artifact_budget import save_runtime_artifact
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
from agentmesh.risk import RiskDecision, assess_tool_request
from agentmesh.runtime_admission import current_orchestration_admission
from agentmesh.skill_runtime.quiesce import OrchestrationQuiesceController
from agentmesh.store import RuntimeToolCallConflict, SQLiteStore
from agentmesh.tool_runtime.deepsearch import DeepSearchToolRuntimeError, build_deepsearch_tool_invocation
from agentmesh.tool_runtime.gateway import ToolGateway, collect_source_ids, encode_tool_output
from agentmesh.tool_runtime.guardrails import (
    quarantine_unsafe_output,
    reject_secret_arguments,
    unsafe_tool_output_reason,
)
from agentmesh.tools import list_agent_tools

_MAX_OUTPUT_BYTES = 50 * 1024
_MAX_PROVIDER_OUTPUT_BYTES = 1024 * 1024
_MAX_OUTPUT_LINES = 2000


def _is_wiki_import(skill: SkillDefinition | None) -> bool:
    return bool(
        skill
        and skill.metadata.get("agentmesh-wiki-import", "").strip().lower() in {"1", "true", "yes", "on"}
    )


class AgentMeshToolFactory:
    def __init__(
        self,
        repository: SQLiteStore,
        gateway: ToolGateway | None = None,
        admission: OrchestrationQuiesceController | None = None,
    ):
        self.repository = repository
        self.gateway = gateway or ToolGateway(repository)
        self.admission = admission or current_orchestration_admission()

    def set_admission_controller(self, admission: OrchestrationQuiesceController) -> None:
        self.admission = admission

    def _claim(
        self,
        *,
        context: AgentMeshRunContext,
        definition: ToolDefinition,
        arguments: dict[str, Any],
        sdk_call_id: object,
        deepsearch_operation_key: str | None,
    ) -> RuntimeToolCallClaimV1:
        arguments_hash = hashlib.sha256(
            json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode(
                "utf-8"
            )
        ).hexdigest()
        raw_call_id = sdk_call_id if isinstance(sdk_call_id, str) and sdk_call_id else None
        call_id = raw_call_id or "tool_call_" + canonical_json_sha256(
            {
                "run_id": context.run_id,
                "plan_id": context.plan_id,
                "node_id": context.node_id,
                "tool_definition_id": definition.id,
                "arguments_hash": arguments_hash,
                "ordinal": context.tool_call_count,
            }
        )[:24]
        operation_identity = deepsearch_operation_key or canonical_json_sha256(
            {
                "run_id": context.run_id,
                "plan_id": context.plan_id,
                "node_id": context.node_id,
                "call_id": call_id,
                "tool_definition_id": definition.id,
                "implementation_id": definition.implementation_id or f"builtin:{definition.name}",
                "implementation_version": definition.implementation_version,
                "arguments_hash": arguments_hash,
            }
        )
        return RuntimeToolCallClaimV1(
            call_id=call_id,
            run_id=context.run_id,
            plan_id=context.plan_id,
            node_id=context.node_id,
            tool_definition_id=definition.id,
            tool_name=definition.name,
            implementation_id=definition.implementation_id or f"builtin:{definition.name}",
            implementation_version=definition.implementation_version,
            side_effect=definition.side_effect,
            operation_identity=operation_identity,
        )

    def _finish_claim(
        self,
        claim: RuntimeToolCallClaimV1,
        *,
        outcome: Literal["settled", "abandoned", "outcome_unknown"],
        result_hash: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self.repository.finish_runtime_tool_call(
            RuntimeToolCallOutcomeV1(
                call_id=claim.call_id,
                run_id=claim.run_id,
                outcome=outcome,
                result_hash=result_hash,
                error_code=error_code,
            )
        )

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
            if skill and skill.requested_tools:
                requested = set(skill.requested_tools)
            elif _is_wiki_import(skill):
                requested = set()
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
            if definition.side_effect != "read":
                return True
            assessment = assess_tool_request(json.dumps(params, ensure_ascii=False, default=str))
            if assessment.decision != RiskDecision.ALLOW:
                return True
            # A Skill can only see tools already granted to the user's personal Agent.
            # That durable grant is sufficient for routine read-only calls, so the SDK
            # must not interrupt the run for a second, call-scoped approval.
            if ctx.context.skill_id is not None:
                return False
            return definition.approval_required

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
            run = self.repository.get_agent_run(ctx.context.run_id)
            deepsearch_invocation = None
            sdk_call_id = getattr(ctx, "tool_call_id", None)
            if run is not None and run.planning_mode is AgentPlanningMode.DEEPSEARCH:
                if not isinstance(sdk_call_id, str) or not sdk_call_id:
                    raise DeepSearchToolRuntimeError("deepsearch_tool_call_identity_missing")
                deepsearch_invocation = build_deepsearch_tool_invocation(
                    context=ctx.context,
                    definition=definition,
                    arguments=arguments,
                    tool_call_id=sdk_call_id,
                )
            claim = self._claim(
                context=ctx.context,
                definition=definition,
                arguments=arguments,
                sdk_call_id=sdk_call_id,
                deepsearch_operation_key=(
                    deepsearch_invocation.operation_key
                    if deepsearch_invocation is not None
                    else None
                ),
            )
            with self.admission.permit():
                claimed = self.repository.claim_runtime_tool_call(claim)
            if not claimed:
                raise RuntimeToolCallConflict("tool_call_already_claimed")
            self.repository.add_audit_event(
                AuditEvent(
                    actor=ctx.context.user_id,
                    action="sdk_tool_started",
                    target_type="tool_definition",
                    target_id=definition.id,
                    workspace_id=ctx.context.workspace_id,
                    project_id=ctx.context.project_id,
                    metadata={
                        "run_id": ctx.context.run_id,
                        "tool_name": definition.name,
                        "argument_keys": sorted(arguments),
                    },
                )
            )
            try:
                if deepsearch_invocation is not None:
                    gateway_invoke = getattr(self.gateway, "invoke", None)
                    if not callable(gateway_invoke):
                        raise DeepSearchToolRuntimeError("deepsearch_tool_persistence_unavailable")
                    value = await asyncio.to_thread(
                        gateway_invoke,
                        context=ctx.context,
                        definition=definition,
                        arguments=arguments,
                        invocation=deepsearch_invocation,
                    )
                else:
                    value = await asyncio.to_thread(handler, ctx.context, arguments)
                ctx.context.source_ids = list(
                    dict.fromkeys([*ctx.context.source_ids, *self._registered_source_ids(value, ctx.context)])
                )
                output = encode_tool_output(value)
                if len(output.encode("utf-8")) > _MAX_PROVIDER_OUTPUT_BYTES:
                    raise RuntimeError("tool_output_limit_exceeded")
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
                    visible = "Tool output was withheld by AgentMesh policy."
                    artifact_id = None
                else:
                    visible, artifact_id = self._bounded_output(
                        ctx.context,
                        definition,
                        output,
                        planning_mode=(
                            run.planning_mode
                            if run is not None
                            else AgentPlanningMode.STANDARD
                        ),
                    )
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
            except BaseException:
                self._finish_claim(
                    claim,
                    outcome=("abandoned" if definition.side_effect == "read" else "outcome_unknown"),
                    error_code=(
                        "process_restarted"
                        if definition.side_effect == "read"
                        else "external_outcome_unknown"
                    ),
                )
                raise
            self._finish_claim(
                claim,
                outcome="settled",
                result_hash=hashlib.sha256(output.encode("utf-8")).hexdigest(),
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
        *,
        planning_mode: AgentPlanningMode = AgentPlanningMode.STANDARD,
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
        artifact = save_runtime_artifact(
            self.repository,
            Artifact(
                run_id=context.run_id,
                workspace_id=context.workspace_id,
                project_id=context.project_id,
                user_id=context.user_id,
                artifact_type="tool_output",
                content_type="application/json",
                content=output,
                truncated=True,
            ),
            planning_mode=planning_mode,
        )
        suffix = f"\n\n[Output truncated. Full result artifact: {artifact.id}]"
        return visible + suffix, artifact.id
