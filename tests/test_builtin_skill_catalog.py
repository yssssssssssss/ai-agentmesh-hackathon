from __future__ import annotations

from agentmesh.models import SkillMemoryWritePolicy
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore

EXPECTED_PILOT_SKILLS = {
    "build-experience-metrics",
    "competitive-analysis",
    "generate-interview-guide",
    "generate-research-plan",
    "generate-survey",
    "generate-usability-test",
    "issue-prioritization",
    "jobs-to-be-done",
    "prd-feasibility",
    "query-experiment-conclusions",
}


def test_ten_builtin_pilot_skills_are_valid_and_governed(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AGENTMESH_WIKI_ROOT", str(tmp_path))
    repository = SQLiteStore(tmp_path / "builtin-skills.sqlite3")
    catalog = SkillCatalogService(repository)
    skills = catalog.reload()
    by_name = {skill.name: skill for skill in skills}

    assert set(by_name) >= EXPECTED_PILOT_SKILLS
    assert not [diagnostic for diagnostic in catalog.diagnostics if diagnostic.level == "error"]
    for name in EXPECTED_PILOT_SKILLS:
        skill = by_name[name]
        assert skill.metadata.get("author")
        assert skill.metadata["source"].endswith("/SKILL.md")
        assert skill.memory_write_policy == SkillMemoryWritePolicy.PRIVATE_SHORT_TERM
        assert skill.activation_policy == "explicit_only"
        assert skill.instructions.strip()
