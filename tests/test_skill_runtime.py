from __future__ import annotations

from pathlib import Path

from agentmesh.models import SkillSourceScope
from agentmesh.skill_runtime.discovery import SkillRoot, discover_skills
from agentmesh.skill_runtime.parser import parse_skill_file


def _write_skill(root: Path, directory: str, frontmatter: str, body: str = "# Instructions\n\nDo the work.") -> Path:
    skill_dir = root / directory
    skill_dir.mkdir(parents=True)
    path = skill_dir / "SKILL.md"
    path.write_text(f"---\n{frontmatter}\n---\n\n{body}\n", encoding="utf-8")
    return path


def test_parse_standard_skill_and_preserve_host_fields(tmp_path: Path) -> None:
    path = _write_skill(
        tmp_path,
        "research-plan",
        "\n".join(
            [
                "name: research-plan",
                "description: Build a research plan when a user has a research question.",
                "license: MIT",
                "compatibility: Requires project documents",
                "allowed-tools: memory_search document_search",
                "disable-model-invocation: true",
                "argument-hint: '[brief]'",
                "metadata:",
                "  author: agentmesh",
                '  version: "1.0"',
            ]
        ),
    )

    result = parse_skill_file(path, source_scope=SkillSourceScope.BUILTIN)

    assert result.skill is not None
    assert result.skill.name == "research-plan"
    assert result.skill.description.startswith("Build a research plan")
    assert result.skill.requested_tools == ["memory_search", "document_search"]
    assert result.skill.activation_policy == "explicit_only"
    assert result.skill.metadata == {"author": "agentmesh", "version": "1.0"}
    assert result.skill.argument_hint == "[brief]"
    assert result.skill.instructions.startswith("# Instructions")
    assert result.skill.content_hash
    assert result.diagnostics == []


def test_parse_title_skips_absolute_prohibitions_preamble(tmp_path: Path) -> None:
    path = _write_skill(
        tmp_path,
        "component-generator",
        "name: component-generator\ndescription: Generate a component.",
        """<!-- ABSOLUTE-PROHIBITIONS:START -->
# 绝对禁止事项（最高优先级）

Do not redraw assets.
<!-- ABSOLUTE-PROHIBITIONS:END -->

# Component Generator

Generate the component.""",
    )

    result = parse_skill_file(path, source_scope=SkillSourceScope.BUILTIN)

    assert result.skill is not None
    assert result.skill.title == "Component Generator"


def test_parse_lenient_description_with_unquoted_colon(tmp_path: Path) -> None:
    path = _write_skill(
        tmp_path,
        "lenient-skill",
        "name: lenient-skill\ndescription: Use this skill when: the user requests analysis",
    )

    result = parse_skill_file(path, source_scope=SkillSourceScope.WORKSPACE)

    assert result.skill is not None
    assert result.skill.description == "Use this skill when: the user requests analysis"
    assert any(item.code == "frontmatter_yaml_repaired" for item in result.diagnostics)


def test_missing_description_skips_only_invalid_skill(tmp_path: Path) -> None:
    path = _write_skill(tmp_path, "invalid", "name: invalid")

    result = parse_skill_file(path, source_scope=SkillSourceScope.WORKSPACE)

    assert result.skill is None
    assert any(item.code == "description_missing" and item.level == "error" for item in result.diagnostics)


def test_invalid_or_reserved_skill_names_are_rejected(tmp_path: Path) -> None:
    invalid = _write_skill(tmp_path, "invalid.name", "name: invalid.name\ndescription: Invalid name")
    reserved_alias = _write_skill(
        tmp_path,
        "valid-name",
        "name: valid-name\ndescription: Reserved alias\naliases: [memory.search]",
    )

    invalid_result = parse_skill_file(invalid, source_scope=SkillSourceScope.WORKSPACE)
    alias_result = parse_skill_file(reserved_alias, source_scope=SkillSourceScope.WORKSPACE)

    assert invalid_result.skill is None
    assert any(item.code == "name_nonstandard" and item.level == "error" for item in invalid_result.diagnostics)
    assert alias_result.skill is None
    assert any(item.code == "alias_invalid" for item in alias_result.diagnostics)


def test_overlong_compatibility_is_a_diagnostic_not_an_exception(tmp_path: Path) -> None:
    path = _write_skill(
        tmp_path,
        "long-compatibility",
        f"name: long-compatibility\ndescription: Test compatibility\ncompatibility: {'x' * 501}",
    )

    result = parse_skill_file(path, source_scope=SkillSourceScope.WORKSPACE)

    assert result.skill is None
    assert any(item.code == "compatibility_too_long" for item in result.diagnostics)


def test_discovery_uses_scope_precedence_and_reports_collision(tmp_path: Path) -> None:
    builtin = tmp_path / "builtin"
    workspace = tmp_path / "workspace"
    project = tmp_path / "project"
    _write_skill(builtin, "shared", "name: shared\ndescription: Builtin description")
    _write_skill(workspace, "shared", "name: shared\ndescription: Workspace description")
    _write_skill(project, "shared", "name: shared\ndescription: Project description")

    result = discover_skills(
        [
            SkillRoot(project, SkillSourceScope.PROJECT),
            SkillRoot(workspace, SkillSourceScope.WORKSPACE),
            SkillRoot(builtin, SkillSourceScope.BUILTIN),
        ]
    )

    assert result.skills["shared"].description == "Project description"
    collisions = [item for item in result.diagnostics if item.code == "skill_name_collision"]
    assert len(collisions) == 2


def test_discovery_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    _write_skill(outside, "escaped", "name: escaped\ndescription: Escaped skill")
    (root / "escaped-link").symlink_to(outside / "escaped", target_is_directory=True)

    result = discover_skills([SkillRoot(root, SkillSourceScope.PROJECT)])

    assert "escaped" not in result.skills
    assert any(item.code == "skill_symlink_escape" for item in result.diagnostics)
