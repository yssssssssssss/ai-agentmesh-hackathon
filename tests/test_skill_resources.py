from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.models import AgentRun, AgentRunStatus, ChatThread, SkillDefinition, SkillSourceScope
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.skill_runtime.resources import (
    build_skill_resource_tool,
    resolve_skill_resource,
    skill_resource_manifest,
    skill_wiki_corpus_ready,
)
from agentmesh.store import SQLiteStore


def _imported_skill(vendored_file: Path, source: str) -> SkillDefinition:
    return SkillDefinition(
        id="skill_imported_resource",
        name="imported-resource",
        title="Imported Resource",
        description="Imported resource fixture",
        instructions="Read `template.md` and `../../shared.md`.",
        source_path=str(vendored_file),
        source_scope=SkillSourceScope.BUILTIN,
        content_hash="imported-resource-hash",
        metadata={
            "source": source,
            "agentmesh-wiki-import": "true",
        },
    )


def _running_context(tmp_path: Path, skill: SkillDefinition, manifest: dict[str, str]) -> tuple[SQLiteStore, object]:
    repository = SQLiteStore(tmp_path / "resource-tool.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    thread = repository.add_chat_thread(
        ChatThread(
            id="thread_imported_resource",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="Imported resource test",
        )
    )
    run = repository.save_agent_run(
        AgentRun(
            id="run_imported_resource",
            thread_id=thread.id,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="read resource",
            status=AgentRunStatus.RUNNING,
        )
    )
    context = AgentMeshRunContext(
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        thread_id=thread.id,
        run_id=run.id,
        skill_id=skill.id,
        approved_resource_hashes=manifest,
    )
    return repository, SimpleNamespace(context=context)


def test_managed_wiki_import_resolves_original_package_and_safe_parent_references(
    tmp_path: Path,
    monkeypatch,
) -> None:
    wiki = tmp_path / "wiki"
    source_file = wiki / "domain" / "skills" / "imported-resource" / "SKILL.md"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("source", encoding="utf-8")
    template = source_file.parent / "template.md"
    template.write_text("template", encoding="utf-8")
    shared = wiki / "domain" / "shared.md"
    shared.write_text("shared", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    vendored_file = tmp_path / "builtin" / "imported-resource" / "SKILL.md"
    vendored_file.parent.mkdir(parents=True)
    vendored_file.write_text("vendored", encoding="utf-8")
    monkeypatch.setenv("AGENTMESH_WIKI_ROOT", str(wiki))
    skill = _imported_skill(
        vendored_file,
        "2C-DesignWiki/domain/skills/imported-resource/SKILL.md",
    )

    assert skill_wiki_corpus_ready(skill)
    assert resolve_skill_resource(skill, "template.md") == template.resolve()
    assert resolve_skill_resource(skill, "../../shared.md") == shared.resolve()
    assert resolve_skill_resource(skill, "../../../../outside.md") is None


def test_managed_wiki_import_manifest_includes_original_package_and_declared_parent_resource(
    tmp_path: Path,
    monkeypatch,
) -> None:
    wiki = tmp_path / "wiki"
    source_file = wiki / "domain" / "skills" / "imported-resource" / "SKILL.md"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("source", encoding="utf-8")
    template = source_file.parent / "template.md"
    template.write_text("template", encoding="utf-8")
    shared = wiki / "domain" / "shared.md"
    shared.write_text("shared", encoding="utf-8")
    vendored_file = tmp_path / "builtin" / "imported-resource" / "SKILL.md"
    vendored_file.parent.mkdir(parents=True)
    vendored_file.write_text("vendored", encoding="utf-8")
    monkeypatch.setenv("AGENTMESH_WIKI_ROOT", str(wiki))
    skill = _imported_skill(
        vendored_file,
        "2C-DesignWiki/domain/skills/imported-resource/SKILL.md",
    )

    manifest = skill_resource_manifest(skill)

    assert manifest["template.md"] == hashlib.sha256(template.read_bytes()).hexdigest()
    assert manifest["../../shared.md"] == hashlib.sha256(shared.read_bytes()).hexdigest()


def test_wiki_import_marker_is_not_trusted_for_workspace_skills(tmp_path: Path, monkeypatch) -> None:
    wiki = tmp_path / "wiki"
    source_file = wiki / "domain" / "skills" / "imported-resource" / "SKILL.md"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("source", encoding="utf-8")
    (wiki / "domain" / "shared.md").write_text("shared", encoding="utf-8")
    vendored_file = tmp_path / "workspace" / "imported-resource" / "SKILL.md"
    vendored_file.parent.mkdir(parents=True)
    vendored_file.write_text("workspace", encoding="utf-8")
    monkeypatch.setenv("AGENTMESH_WIKI_ROOT", str(wiki))
    skill = _imported_skill(
        vendored_file,
        "2C-DesignWiki/domain/skills/imported-resource/SKILL.md",
    ).model_copy(update={"source_scope": SkillSourceScope.WORKSPACE})

    assert not skill_wiki_corpus_ready(skill)
    assert resolve_skill_resource(skill, "../../shared.md") is None


def test_managed_wiki_import_resource_tool_denies_paths_when_manifest_is_empty(
    tmp_path: Path,
    monkeypatch,
) -> None:
    wiki = tmp_path / "wiki"
    source_file = wiki / "domain" / "skills" / "imported-resource" / "SKILL.md"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("source", encoding="utf-8")
    (source_file.parent / "undeclared.md").write_text("private", encoding="utf-8")
    vendored_file = tmp_path / "builtin" / "imported-resource" / "SKILL.md"
    vendored_file.parent.mkdir(parents=True)
    vendored_file.write_text("vendored", encoding="utf-8")
    monkeypatch.setenv("AGENTMESH_WIKI_ROOT", str(wiki))
    skill = _imported_skill(
        vendored_file,
        "2C-DesignWiki/domain/skills/imported-resource/SKILL.md",
    ).model_copy(update={"instructions": "No resource references."})
    repository, wrapper = _running_context(tmp_path, skill, {})
    tool = build_skill_resource_tool(repository, skill)

    with pytest.raises(PermissionError, match="outside the frozen"):
        asyncio.run(tool.on_invoke_tool(wrapper, json.dumps({"paths": ["undeclared.md"]})))


def test_managed_wiki_import_resource_tool_rejects_content_changed_after_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    wiki = tmp_path / "wiki"
    source_file = wiki / "domain" / "skills" / "imported-resource" / "SKILL.md"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("source", encoding="utf-8")
    resource = source_file.parent / "template.md"
    resource.write_text("original", encoding="utf-8")
    vendored_file = tmp_path / "builtin" / "imported-resource" / "SKILL.md"
    vendored_file.parent.mkdir(parents=True)
    vendored_file.write_text("vendored", encoding="utf-8")
    monkeypatch.setenv("AGENTMESH_WIKI_ROOT", str(wiki))
    skill = _imported_skill(
        vendored_file,
        "2C-DesignWiki/domain/skills/imported-resource/SKILL.md",
    ).model_copy(update={"instructions": "Read `template.md`."})
    manifest = skill_resource_manifest(skill)
    repository, wrapper = _running_context(tmp_path, skill, manifest)
    tool = build_skill_resource_tool(repository, skill)
    resource.write_text("changed", encoding="utf-8")

    with pytest.raises(PermissionError, match="changed after"):
        asyncio.run(tool.on_invoke_tool(wrapper, json.dumps({"paths": ["template.md"]})))


def test_managed_wiki_import_rejects_symlinked_resources(tmp_path: Path, monkeypatch) -> None:
    wiki = tmp_path / "wiki"
    source_file = wiki / "domain" / "skills" / "imported-resource" / "SKILL.md"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("source", encoding="utf-8")
    target = source_file.parent / "target.md"
    target.write_text("target", encoding="utf-8")
    link = source_file.parent / "link.md"
    link.symlink_to(target)
    vendored_file = tmp_path / "builtin" / "imported-resource" / "SKILL.md"
    vendored_file.parent.mkdir(parents=True)
    vendored_file.write_text("vendored", encoding="utf-8")
    monkeypatch.setenv("AGENTMESH_WIKI_ROOT", str(wiki))
    skill = _imported_skill(
        vendored_file,
        "2C-DesignWiki/domain/skills/imported-resource/SKILL.md",
    )

    assert resolve_skill_resource(skill, "link.md") is None
    assert "link.md" not in skill_resource_manifest(skill)
