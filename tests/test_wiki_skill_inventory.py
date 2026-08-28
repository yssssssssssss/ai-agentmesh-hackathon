from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from agentmesh.models import SkillActivationPolicy, SkillSourceScope
from agentmesh.skill_runtime.discovery import SkillRoot, discover_skills
from agentmesh.skill_runtime.parser import parse_skill_file
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore
from scripts.sync_wiki_skills import (
    CanonicalSkill,
    SourceSkill,
    SyncPlan,
    build_sync_plan,
    check_sync,
    generate_profile_stubs,
)

ROOT = Path(__file__).parents[1]
BUILTIN_ROOT = ROOT / "agentmesh" / "builtin_skills"
MANIFEST_PATH = BUILTIN_ROOT / "wiki-skill-provenance.json"
WIKI_ROOT = ROOT / "2C-DesignWiki"
requires_wiki_source = pytest.mark.skipif(
    not WIKI_ROOT.is_dir(),
    reason="2C-DesignWiki is an ignored external source corpus",
)

EXPECTED_ADAPTER_SOURCES = {
    "ai-decision-lab": "2C-DesignWiki/jd-design-system-md-v16/horizontal/user-research/skills/AI-Decision-Lab/SKILL.md",
    "platform-transaction-address": (
        "2C-DesignWiki/jd-design-system-md-v16/product-architecture/platform-transaction/交易链路/地址/SKILL.md"
    ),
    "platform-transaction-cart": (
        "2C-DesignWiki/jd-design-system-md-v16/product-architecture/platform-transaction/交易链路/购物车/SKILL.md"
    ),
    "platform-transaction-cashier": (
        "2C-DesignWiki/jd-design-system-md-v16/product-architecture/platform-transaction/交易链路/收银台/SKILL.md"
    ),
    "platform-transaction-settlement": (
        "2C-DesignWiki/jd-design-system-md-v16/product-architecture/platform-transaction/交易链路/结算/SKILL.md"
    ),
    "platform-transaction-shared-foundation": (
        "2C-DesignWiki/jd-design-system-md-v16/product-architecture/platform-transaction/_共享底座/SKILL.md"
    ),
    "platform-transaction-success-page": (
        "2C-DesignWiki/jd-design-system-md-v16/product-architecture/platform-transaction/交易链路/成功页/SKILL.md"
    ),
}

EXPECTED_DUPLICATE_SELECTIONS = {
    "4405264795472393813077b0451a2ae99a8b62be11f0027c143dc5ebc867c587": (
        "2C-DesignWiki/jd-design-system-md-v16/product-architecture/plus-and-new-channel/_skills/zero-id-to-md/SKILL.md"
    ),
    "dc9aad37b98bfc97df4d555121482c5f281e3fd651a8e946992d1bd0e44a98b2": (
        "2C-DesignWiki/tools/dwiki/SKILL.md"
    ),
}

EXPECTED_STAGE_COUNTS = {
    "during_design": 26,
    "post_design": 41,
    "pre_design": 17,
}


def _manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_builtin_wiki_inventory_has_84_unique_valid_skills() -> None:
    result = discover_skills([SkillRoot(BUILTIN_ROOT, SkillSourceScope.BUILTIN)])

    assert len(result.skills) == 84
    assert len(set(result.skills)) == 84
    assert not [diagnostic for diagnostic in result.diagnostics if diagnostic.level == "error"]
    assert not [diagnostic for diagnostic in result.diagnostics if diagnostic.code == "skill_name_collision"]


def test_generate_profile_stubs_is_create_only_and_does_not_guess_safety_fields(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source" / "SKILL.md"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("source", encoding="utf-8")
    source = SourceSkill(
        path=source_path,
        relative_path="source/SKILL.md",
        source_sha256=hashlib.sha256(b"source").hexdigest(),
        frontmatter={"name": "journey-map"},
        body="# Source\n",
    )
    plan = SyncPlan(
        source_file_count=1,
        skills=(CanonicalSkill(name="journey-map", source=source, adapter=None),),
        duplicate_groups={},
    )
    builtin_root = tmp_path / "builtin"
    skill_path = builtin_root / "journey-map" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        """---
name: journey-map
description: Journey map draft
metadata:
  version: "1"
  short-description: Journey map draft
  agentmesh-stage: pre_design
---
# Journey map
""",
        encoding="utf-8",
    )

    created = generate_profile_stubs(plan, builtin_root)
    sidecar = builtin_root / "journey-map" / "agents" / "agentmesh.yaml"
    payload = yaml.safe_load(sidecar.read_text(encoding="utf-8"))

    assert created == [sidecar]
    assert payload["review_state"] == "draft"
    assert payload["planner_eligible"] is False
    assert payload["skill_content_hash"] == hashlib.sha256(skill_path.read_bytes()).hexdigest()
    assert "capability_type" not in payload
    original = sidecar.read_bytes()
    assert generate_profile_stubs(plan, builtin_root) == []
    assert sidecar.read_bytes() == original


@requires_wiki_source
def test_vendored_wiki_snapshot_is_current() -> None:
    assert check_sync(build_sync_plan(WIKI_ROOT), BUILTIN_ROOT) == []


def test_wiki_skill_provenance_is_complete_and_selects_a_single_source() -> None:
    manifest = _manifest()
    skills = manifest["skills"]
    assert isinstance(skills, list)
    rows = {str(item["name"]): item for item in skills}

    assert manifest["source_file_count"] == 86
    assert manifest["unique_source_count"] == 84
    assert manifest["preserved_builtin_count"] == 10
    assert manifest["generated_builtin_count"] == 74
    assert manifest["stage_counts"] == EXPECTED_STAGE_COUNTS
    assert len(skills) == 84
    assert len(rows) == 84
    assert len({str(item["source"]) for item in skills}) == 84
    assert len({str(item["source_sha256"]) for item in skills}) == 84
    assert sum(item["mode"] == "preserved" for item in skills) == 10
    assert sum(item["mode"] == "generated" for item in skills) == 74
    assert {str(item["stage"]) for item in skills} == set(EXPECTED_STAGE_COUNTS)
    assert {
        stage: sum(item["stage"] == stage for item in skills)
        for stage in EXPECTED_STAGE_COUNTS
    } == EXPECTED_STAGE_COUNTS
    assert {
        path.relative_to(ROOT).as_posix()
        for path in BUILTIN_ROOT.rglob("SKILL.md")
        if path.is_file()
    } == {str(item["destination"]) for item in skills}

    adapters = {name: str(item["source"]) for name, item in rows.items() if item["adapter"]}
    assert adapters == EXPECTED_ADAPTER_SOURCES
    duplicate_selections = {
        str(item["source_sha256"]): str(item["canonical_source"])
        for item in manifest["duplicate_groups"]
    }
    assert duplicate_selections == EXPECTED_DUPLICATE_SELECTIONS

    for name, item in rows.items():
        destination = ROOT / str(item["destination"])
        assert destination == BUILTIN_ROOT / name / "SKILL.md"
        assert hashlib.sha256(destination.read_bytes()).hexdigest() == item["builtin_sha256"]
        assert str(item["source"]).startswith("2C-DesignWiki/")
        assert ".." not in Path(str(item["source"])).parts

        parsed = parse_skill_file(destination, source_scope=SkillSourceScope.BUILTIN)
        assert parsed.skill is not None
        assert parsed.skill.name == name
        assert parsed.skill.metadata["source"] == item["source"]
        assert parsed.skill.activation_policy == SkillActivationPolicy.EXPLICIT_ONLY

        if item["mode"] == "generated":
            assert parsed.skill.metadata["agentmesh-wiki-import"] == "true"
            assert parsed.skill.metadata["agentmesh-stage"] == item["stage"]
            assert parsed.skill.metadata["agentmesh-activation"] == "explicit_only"
            assert parsed.skill.metadata["author"]
            assert 1 <= len(parsed.skill.metadata["short-description"]) <= 100
        else:
            profile_path = destination.parent / "agents" / "agentmesh.yaml"
            profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
            assert profile["primary_stage"] == item["stage"]
            assert profile["skill_content_hash"] == item["builtin_sha256"]


def test_catalog_uses_stage_metadata_for_unprofiled_wiki_imports(tmp_path: Path) -> None:
    expected = {
        "design-advisor": "pre_design",
        "prototype-generation": "during_design",
        "design-review": "post_design",
    }
    catalog = SkillCatalogService(SQLiteStore(tmp_path / "wiki-stage-fallback.sqlite3"))

    for name, stage in expected.items():
        parsed = parse_skill_file(BUILTIN_ROOT / name / "SKILL.md", source_scope=SkillSourceScope.BUILTIN)
        assert parsed.skill is not None

        item = catalog.to_chat_skill(parsed.skill)

        assert item["primary_stage"] == stage
        assert item["planner_eligible"] is False


@requires_wiki_source
def test_catalog_reports_imported_skills_with_unavailable_host_tools(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENTMESH_WIKI_ROOT", str(ROOT / "2C-DesignWiki"))
    result = discover_skills([SkillRoot(BUILTIN_ROOT, SkillSourceScope.BUILTIN)])
    catalog = SkillCatalogService(SQLiteStore(tmp_path / "wiki-tool-readiness.sqlite3"))

    items = [catalog.to_chat_skill(skill) for skill in result.skills.values()]
    limited = [item for item in items if item["execution_readiness"] == "tool_limited"]

    assert len(limited) == 27
    assert sum(item["execution_readiness"] == "complete" for item in items) == 57
    design_review = next(item for item in limited if item["command"] == "$design-review")
    assert "Bash" in design_review["missing_tools"]
    assert "mcp__zero-design__get_screenshot" in design_review["missing_tools"]


@requires_wiki_source
def test_sync_check_rejects_preserved_pilot_stage_drift(tmp_path: Path) -> None:
    copied_root = tmp_path / "builtin_skills"
    shutil.copytree(BUILTIN_ROOT, copied_root)
    profile_path = copied_root / "generate-research-plan" / "agents" / "agentmesh.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["primary_stage"] = "post_design"
    profile_path.write_text(yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8")

    problems = check_sync(build_sync_plan(WIKI_ROOT), copied_root)

    assert "preserved builtin stage differs from stage mapping: generate-research-plan" in problems


@requires_wiki_source
def test_sync_check_rejects_preserved_pilot_version_drift(tmp_path: Path) -> None:
    copied_root = tmp_path / "builtin_skills"
    shutil.copytree(BUILTIN_ROOT, copied_root)
    profile_path = copied_root / "generate-research-plan" / "agents" / "agentmesh.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["skill_version"] = "999"
    profile_path.write_text(yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8")

    problems = check_sync(build_sync_plan(WIKI_ROOT), copied_root)

    assert "preserved builtin profile version differs from Skill metadata: generate-research-plan" in problems


@requires_wiki_source
def test_sync_check_rejects_preserved_pilot_source_drift(tmp_path: Path) -> None:
    copied_root = tmp_path / "builtin_skills"
    shutil.copytree(BUILTIN_ROOT, copied_root)
    skill_path = copied_root / "generate-research-plan" / "SKILL.md"
    content = skill_path.read_text(encoding="utf-8").replace(
        'source: "2C-DesignWiki/jd-design-system-md-v16/horizontal/user-research/skills/generate-research-plan/SKILL.md"',
        'source: "2C-DesignWiki/wrong/SKILL.md"',
        1,
    )
    skill_path.write_text(content, encoding="utf-8")

    problems = check_sync(build_sync_plan(WIKI_ROOT), copied_root)

    assert "preserved builtin source differs from canonical source: generate-research-plan" in problems


@requires_wiki_source
def test_sync_check_rejects_nested_unexpected_skill(tmp_path: Path) -> None:
    copied_root = tmp_path / "builtin_skills"
    shutil.copytree(BUILTIN_ROOT, copied_root)
    nested = copied_root / "design-review" / "resources" / "unexpected" / "SKILL.md"
    nested.parent.mkdir(parents=True)
    nested.write_text("---\nname: unexpected\ndescription: unexpected\n---\n# Unexpected\n", encoding="utf-8")

    problems = check_sync(build_sync_plan(WIKI_ROOT), copied_root)

    assert any("design-review/resources/unexpected/SKILL.md" in problem for problem in problems)
