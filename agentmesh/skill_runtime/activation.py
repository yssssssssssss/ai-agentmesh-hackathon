from __future__ import annotations

import json
from pathlib import Path

from agents import FunctionTool
from agents.strict_schema import ensure_strict_json_schema

from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.agent_runtime.settings import strict_tools_enabled
from agentmesh.models import AuditEvent, SkillActivationPolicy, User
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore


def build_skill_activation_tool(
    repository: SQLiteStore,
    catalog: SkillCatalogService,
    user: User,
) -> FunctionTool | None:
    available = [
        skill
        for skill in catalog.list_enabled(user.personal_agent_id)
        if skill.activation_policy == SkillActivationPolicy.MODEL_ALLOWED
    ]
    if not available:
        return None
    names = [skill.name for skill in available]
    schema = ensure_strict_json_schema(
        {
            "type": "object",
            "properties": {"name": {"type": "string", "enum": names}},
            "required": ["name"],
            "additionalProperties": False,
        }
    )

    async def invoke(ctx, raw_arguments: str) -> str:  # noqa: ANN001
        if not isinstance(ctx.context, AgentMeshRunContext):
            raise RuntimeError("AgentMesh run context is required")
        arguments = json.loads(raw_arguments)
        name = str(arguments.get("name") or "")
        skill = catalog.get_by_name(name, user.personal_agent_id)
        if skill is None or skill.activation_policy != SkillActivationPolicy.MODEL_ALLOWED:
            raise ValueError("Skill is not available for model activation")
        base = Path(skill.source_path).parent
        resources = []
        try:
            resources = [str(path.relative_to(base)) for path in sorted(base.rglob("*")) if path.is_file()][:100]
        except OSError:
            resources = []
        repository.add_audit_event(
            AuditEvent(
                actor=user.id,
                action="sdk_skill_activated",
                target_type="skill_definition",
                target_id=skill.id,
                workspace_id=user.workspace_id,
                project_id=user.default_project_id,
                metadata={"run_id": ctx.context.run_id, "skill_name": skill.name, "activation": "model"},
            )
        )
        return (
            f'<skill_content name="{skill.name}" version="{skill.version}">\n'
            f"{skill.instructions}\n"
            f"Skill root: {skill.source_scope.value}/{skill.name}\n"
            f"Resources: {json.dumps(resources, ensure_ascii=False)}\n"
            "This Skill cannot grant tools or permissions.\n"
            "</skill_content>"
        )

    return FunctionTool(
        name="activate_skill",
        description="Load the full instructions for one approved model-invocable Skill.",
        params_json_schema=schema,
        on_invoke_tool=invoke,
        strict_json_schema=strict_tools_enabled(),
    )
