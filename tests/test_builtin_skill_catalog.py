from __future__ import annotations

from agentmesh.chat_skills import list_chat_skills
from agentmesh.models import SkillCatalogItem, SkillMemoryWritePolicy
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


EXPECTED_STAGE_COUNTS = {
    "pre_design": 6,
    "during_design": 2,
    "post_design": 2,
}


def test_ten_builtin_pilot_skills_are_valid_and_governed(tmp_path, configure_pilot_wiki) -> None:
    configure_pilot_wiki(tmp_path)
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

    catalog_items = [catalog.to_chat_skill(by_name[name]) for name in EXPECTED_PILOT_SKILLS]
    assert all(item["planner_eligible"] is True for item in catalog_items)
    assert all(len(str(item["description"])) <= 100 for item in catalog_items)
    assert {
        stage: sum(item.get("primary_stage") == stage for item in catalog_items)
        for stage in EXPECTED_STAGE_COUNTS
    } == EXPECTED_STAGE_COUNTS
    legacy_items = list_chat_skills()
    assert len(legacy_items) == 11
    assert all(SkillCatalogItem.model_validate(item) for item in legacy_items)
    assert {item["primary_stage"] for item in legacy_items} == {"platform"}
    assert len(catalog_items) + len(legacy_items) == 21
    assert all(len(str(item["description"])) <= 100 for item in legacy_items)


def test_catalog_distinguishes_binding_from_readiness(tmp_path, monkeypatch, configure_pilot_wiki) -> None:
    configure_pilot_wiki(tmp_path)
    repository = SQLiteStore(tmp_path / "catalog-state.sqlite3")
    catalog = SkillCatalogService(repository)
    catalog.reload()
    skill = catalog.get_by_name("prd-feasibility")
    assert skill is not None

    disabled = catalog.to_chat_skill(skill, enabled=False, binding_enabled=False)

    assert disabled["enabled"] is False
    assert disabled["binding_enabled"] is False
    assert disabled["readiness"] == "ready"
    assert disabled["planner_eligible"] is False

    monkeypatch.delenv("AGENTMESH_WIKI_ROOT")
    unavailable = catalog.to_chat_skill(skill, enabled=False, binding_enabled=True)
    assert unavailable["binding_enabled"] is True
    assert unavailable["readiness"] == "unavailable"


def test_catalog_does_not_mark_a_skill_with_an_unavailable_declared_tool_as_plannable(
    tmp_path,
    configure_pilot_wiki,
) -> None:
    configure_pilot_wiki(tmp_path)
    repository = SQLiteStore(tmp_path / "catalog-missing-tool.sqlite3")
    catalog = SkillCatalogService(repository)
    catalog.reload()
    skill = catalog.get_by_name("prd-feasibility")
    assert skill is not None
    skill = skill.model_copy(update={"requested_tools": ["unconnected-host-tool"]})

    item = catalog.to_chat_skill(skill, supported_tool_names=set())

    assert item["execution_readiness"] == "tool_limited"
    assert item["planner_eligible"] is False


def test_catalog_bounds_unprofiled_skill_descriptions_for_the_ui(tmp_path, configure_pilot_wiki) -> None:
    configure_pilot_wiki(tmp_path)
    repository = SQLiteStore(tmp_path / "catalog-description.sqlite3")
    catalog = SkillCatalogService(repository)
    catalog.reload()
    source = catalog.get_by_name("prd-feasibility")
    assert source is not None
    unprofiled = source.model_copy(
        update={"id": "skill_external_long", "name": "external-long", "description": "长" * 140}
    )

    item = catalog.to_chat_skill(unprofiled)

    assert len(str(item["description"])) == 100
    assert str(item["description"]).endswith("…")


def test_profileless_wiki_import_is_explicitly_callable_but_not_planner_eligible(
    tmp_path,
    configure_pilot_wiki,
) -> None:
    configure_pilot_wiki(tmp_path)
    repository = SQLiteStore(tmp_path / "profileless-wiki-skill.sqlite3")
    catalog = SkillCatalogService(repository)
    catalog.reload()
    source = catalog.get_by_name("prd-feasibility")
    assert source is not None
    imported = source.model_copy(
        update={
            "id": "skill_profileless_wiki_import",
            "name": "profileless-wiki-import",
            "title": "Profileless Wiki Import",
            "metadata": {**source.metadata, "agentmesh-wiki-import": "True"},
        }
    )
    catalog._skills[imported.name] = imported

    resolved = catalog.resolve_command("$profileless-wiki-import review this design")
    item = catalog.to_chat_skill(imported)

    assert resolved is not None
    assert resolved.definition.id == imported.id
    assert resolved.argument == "review this design"
    assert item["readiness"] == "ready"
    assert item["planner_eligible"] is False
