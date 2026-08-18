from __future__ import annotations

import json
import os
from pathlib import Path

from agents import FunctionTool
from agents.strict_schema import ensure_strict_json_schema

from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.agent_runtime.settings import strict_tools_enabled
from agentmesh.models import AuditEvent, SkillDefinition
from agentmesh.store import SQLiteStore

_MAX_RESOURCE_BYTES = 200 * 1024


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def build_skill_resource_tool(repository: SQLiteStore, skill: SkillDefinition) -> FunctionTool:
    skill_root = Path(skill.source_path).resolve().parent
    roots = [skill_root]
    configured_wiki = os.getenv("AGENTMESH_WIKI_ROOT", "").strip()
    if configured_wiki:
        roots.append(Path(configured_wiki).expanduser().resolve())

    async def invoke(ctx, raw_arguments: str) -> str:  # noqa: ANN001
        if not isinstance(ctx.context, AgentMeshRunContext):
            raise RuntimeError("AgentMesh run context is required")
        payload = json.loads(raw_arguments)
        relative = str(payload.get("path", "")).strip()
        if not relative or Path(relative).is_absolute():
            raise ValueError("Skill resource path must be relative")
        for root in roots:
            candidate = (root / relative).resolve()
            if not _within(candidate, root) or candidate.is_symlink() or not candidate.is_file():
                continue
            size = candidate.stat().st_size
            if size > _MAX_RESOURCE_BYTES:
                raise ValueError("Skill resource exceeds the 200 KiB read limit")
            text = candidate.read_text(encoding="utf-8")
            repository.add_audit_event(
                AuditEvent(
                    actor=ctx.context.user_id,
                    action="sdk_skill_resource_read",
                    target_type="skill_definition",
                    target_id=skill.id,
                    workspace_id=ctx.context.workspace_id,
                    project_id=ctx.context.project_id,
                    metadata={"run_id": ctx.context.run_id, "path": relative},
                )
            )
            return text
        raise FileNotFoundError("Skill resource is unavailable in the approved roots")

    return FunctionTool(
        name="read_skill_resource",
        description=(
            "Read one UTF-8 text resource from the activated Skill package or the admin-configured Wiki root. "
            "Pass a relative path only."
        ),
        params_json_schema=ensure_strict_json_schema(
            {
                "type": "object",
                "properties": {"path": {"type": "string", "minLength": 1}},
                "required": ["path"],
                "additionalProperties": False,
            }
        ),
        on_invoke_tool=invoke,
        strict_json_schema=strict_tools_enabled(),
        needs_approval=False,
        timeout_seconds=10,
        timeout_behavior="error_as_result",
    )
