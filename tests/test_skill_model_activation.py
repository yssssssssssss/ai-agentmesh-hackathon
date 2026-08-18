from __future__ import annotations

from agents.testing import ScriptedModel, assistant_message, function_call

from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore
from agentmesh.tools import ensure_tool_seed_data


def test_model_can_activate_only_approved_model_allowed_skill(monkeypatch, tmp_path) -> None:
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "model-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: model-skill
description: Use when the model needs the approved specialist workflow.
metadata:
  version: "1"
  agentmesh-activation: model_allowed
---

# Model Skill

Follow the specialist workflow.
"""
    )
    monkeypatch.setenv("AGENTMESH_SKILL_PATHS", str(skill_root))
    repository = SQLiteStore(tmp_path / "activation.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    ensure_tool_seed_data(repository, granted_by="system")
    catalog = SkillCatalogService(repository)
    catalog.reload()
    model = ScriptedModel(
        [
            [function_call("activate_skill", {"name": "model-skill"}, call_id="activate_call")],
            [assistant_message("Specialist workflow loaded.")],
        ]
    )
    runtime = AgentRuntimeService(repository, model=model, enabled=True, skill_catalog=catalog)

    answer = runtime.run_sync(
        content="Use an appropriate specialist workflow",
        user=USER,
        thread_id="thread_model_activation",
        history=[],
    )

    assert answer.content == "Specialist workflow loaded."
    assert any(event.action == "sdk_skill_activated" for event in repository.audit_events)
    model.assert_complete()
