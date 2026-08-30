from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import agentmesh.skill_runtime.resources as resource_module
from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    ChatThread,
    DeepSearchBudgetUsageV1,
    DeepSearchBudgetV1,
    SkillCapabilityProfile,
    SkillCapabilityType,
    SkillDefinition,
    SkillLifecycleStage,
    SkillOrchestrationRequestMode,
    SkillSourceScope,
    now_utc,
)
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.skill_runtime.resources import (
    build_skill_resource_manifest_snapshot,
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


def _running_context(
    tmp_path: Path,
    skill: SkillDefinition,
    manifest: dict[str, str],
    *,
    manifest_frozen: bool = False,
) -> tuple[SQLiteStore, object]:
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
        resource_manifest_frozen=manifest_frozen,
    )
    return repository, SimpleNamespace(context=context)


def _deepsearch_context(
    tmp_path: Path,
    skill: SkillDefinition,
    manifest: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[SQLiteStore, object]:
    repository = SQLiteStore(tmp_path / "deepsearch-resource-tool.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    thread = repository.add_chat_thread(
        ChatThread(
            id="thread_deepsearch_resource",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="DeepSearch resource test",
        )
    )
    created_at = now_utc()
    run, created = repository.claim_new_agent_run(
        AgentRun(
            id="run_deepsearch_resource",
            thread_id=thread.id,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="read frozen resource",
            client_turn_id="turn_deepsearch_resource",
            status=AgentRunStatus.PLANNING,
            planning_mode=AgentPlanningMode.DEEPSEARCH,
            requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
            orchestration_version="v1",
            orchestration_mode="execute",
            absolute_expires_at=created_at + timedelta(days=7),
            deepsearch_budget=DeepSearchBudgetV1(),
            created_at=created_at,
            updated_at=created_at,
        )
    )
    assert created is True
    monkeypatch.setattr(repository, "user_can_execute_agent_run", lambda *_args, **_kwargs: True)
    context = AgentMeshRunContext(
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        thread_id=thread.id,
        run_id=run.id,
        requirement_version_id="requirement_resource_v1",
        plan_id="plan_deepsearch_resource",
        plan_version=1,
        node_id="node_deepsearch_resource",
        node_step_number=1,
        node_attempt=1,
        skill_id=skill.id,
        approved_resource_hashes=manifest,
        resource_manifest_frozen=True,
    )
    return repository, SimpleNamespace(context=context, tool_call_id="sdk_resource_call_1")


def _profile(
    skill: SkillDefinition,
    *,
    required_resources: list[str],
) -> SkillCapabilityProfile:
    return SkillCapabilityProfile(
        id=skill.id,
        skill_id=skill.id,
        skill_name=skill.name,
        skill_version=skill.version,
        skill_content_hash=skill.content_hash,
        profile_version="1",
        profile_content_hash="b" * 64,
        primary_stage=SkillLifecycleStage.PRE_DESIGN,
        capability_type=SkillCapabilityType.RESEARCH,
        required_resources=required_resources,
    )


def _workspace_skill(root: Path, *, instructions: str = "No resources.") -> SkillDefinition:
    return SkillDefinition(
        id="skill_strict_resource",
        name="strict-resource",
        title="Strict resource",
        description="Strict resource fixture",
        instructions=instructions,
        source_path=str(root / "SKILL.md"),
        source_scope=SkillSourceScope.WORKSPACE,
        content_hash="a" * 64,
    )


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


def test_standard_resource_tool_can_follow_links_within_registered_wiki_subtree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wiki = tmp_path / "wiki"
    source_file = wiki / "domain" / "skills" / "linked-resource" / "SKILL.md"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("source", encoding="utf-8")
    index = wiki / "domain" / "index.md"
    index.write_text("[Linked guide](linked-guide.md)", encoding="utf-8")
    linked_guide = wiki / "domain" / "linked-guide.md"
    linked_guide.write_text("linked guidance", encoding="utf-8")
    vendored_file = tmp_path / "builtin" / "linked-resource" / "SKILL.md"
    vendored_file.parent.mkdir(parents=True)
    vendored_file.write_text("vendored", encoding="utf-8")
    monkeypatch.setenv("AGENTMESH_WIKI_ROOT", str(wiki))
    skill = SkillDefinition(
        id="skill_linked_resource",
        name="linked-resource",
        title="Linked Resource",
        description="Follow a registered Wiki index",
        instructions="Read `index.md`, then follow its relevant links.",
        source_path=str(vendored_file),
        source_scope=SkillSourceScope.BUILTIN,
        content_hash="linked-resource-hash",
        metadata={"source": "2C-DesignWiki/domain/skills/linked-resource/SKILL.md"},
    )
    manifest = skill_resource_manifest(skill)
    repository, wrapper = _running_context(tmp_path, skill, manifest)

    assert "index.md" in manifest
    assert "linked-guide.md" not in manifest

    output = asyncio.run(
        build_skill_resource_tool(repository, skill).on_invoke_tool(
            wrapper,
            json.dumps({"paths": ["linked-guide.md"]}),
        )
    )

    assert json.loads(output)["resources"][0]["content"] == "linked guidance"


def test_standard_resource_tool_limits_total_paths_across_calls(tmp_path: Path) -> None:
    root = tmp_path / "standard-resource-budget"
    root.mkdir()
    (root / "SKILL.md").write_text("Read only the relevant resources.", encoding="utf-8")
    paths = [f"guide-{index}.md" for index in range(13)]
    for path in paths:
        (root / path).write_text(path, encoding="utf-8")
    skill = _workspace_skill(root)
    repository, wrapper = _running_context(
        tmp_path,
        skill,
        skill_resource_manifest(skill),
        manifest_frozen=True,
    )
    tool = build_skill_resource_tool(repository, skill)

    first = asyncio.run(tool.on_invoke_tool(wrapper, json.dumps({"paths": paths[:12]})))

    assert len(json.loads(first)["resources"]) == 12
    with pytest.raises(ValueError, match="Standard Skill node resource limit is 12 paths"):
        asyncio.run(tool.on_invoke_tool(wrapper, json.dumps({"paths": [paths[12]]})))
    assert wrapper.context.resource_references == paths[:12]


def test_resource_manifest_snapshot_freezes_requirements_paths_and_bytes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    wiki = tmp_path / "wiki"
    source_file = wiki / "domain" / "skills" / "imported-resource" / "SKILL.md"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("source", encoding="utf-8")
    resource = source_file.parent / "template.md"
    resource.write_text("first", encoding="utf-8")
    (wiki / "domain" / "shared.md").write_text("shared", encoding="utf-8")
    vendored_file = tmp_path / "builtin" / "imported-resource" / "SKILL.md"
    vendored_file.parent.mkdir(parents=True)
    vendored_file.write_text("vendored", encoding="utf-8")
    monkeypatch.setenv("AGENTMESH_WIKI_ROOT", str(wiki))
    skill = _imported_skill(
        vendored_file,
        "2C-DesignWiki/domain/skills/imported-resource/SKILL.md",
    )
    profile = _profile(skill, required_resources=["wiki.corpus"])

    first = build_skill_resource_manifest_snapshot(skill, profile)
    replay = build_skill_resource_manifest_snapshot(skill, profile)
    resource.write_text("second", encoding="utf-8")
    changed = build_skill_resource_manifest_snapshot(skill, profile)

    assert replay == first
    assert first.required_resources == ["wiki.corpus"]
    assert first.resource_hashes["template.md"] == hashlib.sha256(b"first").hexdigest()
    assert changed.resource_hashes["template.md"] == hashlib.sha256(b"second").hexdigest()
    assert changed.content_hash != first.content_hash


def test_resource_manifest_snapshot_rejects_unknown_or_unavailable_requirement(
    tmp_path: Path,
) -> None:
    skill_file = tmp_path / "resource-skill" / "SKILL.md"
    skill_file.parent.mkdir()
    skill_file.write_text("skill", encoding="utf-8")
    skill = SkillDefinition(
        id="skill_required_resource",
        name="required-resource",
        title="Required resource",
        description="Required resource fixture",
        instructions="No resources.",
        source_path=str(skill_file),
        source_scope=SkillSourceScope.BUILTIN,
        content_hash="a" * 64,
    )

    with pytest.raises(ValueError, match="unsupported"):
        build_skill_resource_manifest_snapshot(
            skill,
            _profile(skill, required_resources=["private.corpus"]),
        )
    with pytest.raises(ValueError, match="unavailable"):
        build_skill_resource_manifest_snapshot(
            skill,
            _profile(skill, required_resources=["wiki.corpus"]),
        )


def test_strict_resource_manifest_allows_an_empty_resource_directory(tmp_path: Path) -> None:
    root = tmp_path / "empty-skill"
    root.mkdir()
    skill = _workspace_skill(root)

    snapshot = build_skill_resource_manifest_snapshot(
        skill,
        _profile(skill, required_resources=[]),
    )

    assert snapshot.resource_hashes == {}


@pytest.mark.parametrize("invalid_root_kind", ["missing", "file"])
def test_strict_resource_manifest_rejects_an_invalid_package_directory(
    tmp_path: Path,
    invalid_root_kind: str,
) -> None:
    root = tmp_path / "invalid-skill"
    if invalid_root_kind == "file":
        root.write_text("not a directory", encoding="utf-8")
    skill = _workspace_skill(root)

    with pytest.raises(ValueError, match="skill_resource_directory_invalid"):
        build_skill_resource_manifest_snapshot(
            skill,
            _profile(skill, required_resources=[]),
        )


def test_strict_resource_manifest_rejects_an_unresolvable_declared_resource(tmp_path: Path) -> None:
    root = tmp_path / "missing-resource-skill"
    root.mkdir()
    skill = _workspace_skill(root, instructions="Read `missing.md`.")

    with pytest.raises(ValueError, match="skill_resource_resolution_failed"):
        build_skill_resource_manifest_snapshot(
            skill,
            _profile(skill, required_resources=[]),
        )


def test_strict_resource_manifest_rejects_an_unreadable_resource(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "unreadable-resource-skill"
    root.mkdir()
    resource = root / "guide.md"
    resource.write_text("guide", encoding="utf-8")
    skill = _workspace_skill(root)
    original_reader = resource_module._read_bounded_resource

    def fail_read(path: Path) -> bytes:
        if path == resource.resolve():
            raise PermissionError("denied")
        return original_reader(path)

    monkeypatch.setattr(resource_module, "_read_bounded_resource", fail_read)

    with pytest.raises(ValueError, match="skill_resource_read_failed"):
        build_skill_resource_manifest_snapshot(
            skill,
            _profile(skill, required_resources=[]),
        )


def test_strict_resource_manifest_rejects_single_file_limit_without_changing_legacy_behavior(
    tmp_path: Path,
) -> None:
    root = tmp_path / "oversized-resource-skill"
    root.mkdir()
    (root / "large.md").write_bytes(b"x" * (resource_module._MAX_RESOURCE_BYTES + 1))
    skill = _workspace_skill(root)

    assert skill_resource_manifest(skill) == {}
    with pytest.raises(ValueError, match="skill_resource_file_limit_exceeded"):
        build_skill_resource_manifest_snapshot(
            skill,
            _profile(skill, required_resources=[]),
        )


def test_strict_resource_manifest_rejects_file_count_truncation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "too-many-resources-skill"
    root.mkdir()
    (root / "first.md").write_text("first", encoding="utf-8")
    (root / "second.md").write_text("second", encoding="utf-8")
    skill = _workspace_skill(root)
    monkeypatch.setattr(resource_module, "_MAX_RESOURCE_MANIFEST_FILES", 1)

    assert len(skill_resource_manifest(skill)) == 1
    with pytest.raises(ValueError, match="skill_resource_manifest_file_limit_exceeded"):
        build_skill_resource_manifest_snapshot(
            skill,
            _profile(skill, required_resources=[]),
        )


def test_strict_resource_manifest_rejects_scan_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "scan-limit-skill"
    root.mkdir()
    (root / "first.md").write_text("first", encoding="utf-8")
    (root / "second.md").write_text("second", encoding="utf-8")
    skill = _workspace_skill(root)
    monkeypatch.setattr(resource_module, "_MAX_RESOURCE_SCAN_ENTRIES", 1)

    with pytest.raises(ValueError, match="skill_resource_scan_limit_exceeded"):
        build_skill_resource_manifest_snapshot(
            skill,
            _profile(skill, required_resources=[]),
        )


def test_strict_resource_manifest_rejects_non_utf8_and_symlink_entries(tmp_path: Path) -> None:
    binary_root = tmp_path / "binary-resource-skill"
    binary_root.mkdir()
    (binary_root / "binary.txt").write_bytes(b"\xff")
    binary_skill = _workspace_skill(binary_root)

    with pytest.raises(ValueError, match="skill_resource_not_utf8"):
        build_skill_resource_manifest_snapshot(
            binary_skill,
            _profile(binary_skill, required_resources=[]),
        )

    symlink_root = tmp_path / "symlink-resource-skill"
    symlink_root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    (symlink_root / "link.md").symlink_to(outside)
    symlink_skill = _workspace_skill(symlink_root)

    with pytest.raises(ValueError, match="skill_resource_symlink_forbidden"):
        build_skill_resource_manifest_snapshot(
            symlink_skill,
            _profile(symlink_skill, required_resources=[]),
        )


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


def test_deepsearch_resource_read_reserves_before_io_and_settles_actual_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "deepsearch-resource-skill"
    root.mkdir()
    (root / "SKILL.md").write_text("Read `guide.md`.", encoding="utf-8")
    resource = root / "guide.md"
    resource.write_text("trusted guide", encoding="utf-8")
    skill = _workspace_skill(root, instructions="Read `guide.md`.")
    manifest = skill_resource_manifest(skill)
    repository, wrapper = _deepsearch_context(tmp_path, skill, manifest, monkeypatch)
    original_reader = resource_module._read_bounded_resource
    reads: list[Path] = []

    def observe_reserved_budget(path: Path) -> bytes:
        run = repository.get_agent_run(wrapper.context.run_id)
        assert run is not None and run.deepsearch_budget is not None
        assert len(run.deepsearch_budget.reservations) == 1
        reservation = run.deepsearch_budget.reservations[0]
        assert reservation.status == "reserved"
        assert reservation.resource_maxima == DeepSearchBudgetUsageV1(
            active_seconds=10,
            tool_calls=1,
        )
        reads.append(path)
        return original_reader(path)

    clock_values = iter([100.0, 102.5])
    monkeypatch.setattr(resource_module, "monotonic", lambda: next(clock_values), raising=False)
    monkeypatch.setattr(resource_module, "_read_bounded_resource", observe_reserved_budget)

    output = asyncio.run(
        build_skill_resource_tool(repository, skill).on_invoke_tool(
            wrapper,
            json.dumps({"paths": ["guide.md"]}),
        )
    )

    assert json.loads(output)["resources"][0]["content"] == "trusted guide"
    assert reads == [resource.resolve()]
    run = repository.get_agent_run(wrapper.context.run_id)
    assert run is not None and run.deepsearch_budget is not None
    assert run.deepsearch_budget.consumed == DeepSearchBudgetUsageV1(
        active_seconds=2.5,
        tool_calls=1,
    )
    reservation = run.deepsearch_budget.reservations[0]
    assert reservation.status == "settled"
    assert reservation.actual_usage == run.deepsearch_budget.consumed
    assert reservation.tool_invocation is None


def test_deepsearch_resource_read_failure_settles_reserved_maxima(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "failing-deepsearch-resource-skill"
    root.mkdir()
    (root / "SKILL.md").write_text("Read `guide.md`.", encoding="utf-8")
    (root / "guide.md").write_text("unavailable", encoding="utf-8")
    skill = _workspace_skill(root, instructions="Read `guide.md`.")
    repository, wrapper = _deepsearch_context(
        tmp_path,
        skill,
        skill_resource_manifest(skill),
        monkeypatch,
    )

    def fail_read(_path: Path) -> bytes:
        raise OSError("disk read failed")

    monkeypatch.setattr(resource_module, "monotonic", lambda: 100.0)
    monkeypatch.setattr(resource_module, "_read_bounded_resource", fail_read)

    with pytest.raises(FileNotFoundError, match="became unavailable"):
        asyncio.run(
            build_skill_resource_tool(repository, skill).on_invoke_tool(
                wrapper,
                json.dumps({"paths": ["guide.md"]}),
            )
        )

    run = repository.get_agent_run(wrapper.context.run_id)
    assert run is not None and run.deepsearch_budget is not None
    assert run.deepsearch_budget.consumed == DeepSearchBudgetUsageV1(
        active_seconds=10,
        tool_calls=1,
    )
    reservation = run.deepsearch_budget.reservations[0]
    assert reservation.status == "settled"
    assert reservation.actual_usage == reservation.resource_maxima


def test_deepsearch_resource_replay_does_not_read_the_file_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "replayed-deepsearch-resource-skill"
    root.mkdir()
    (root / "SKILL.md").write_text("Read `guide.md`.", encoding="utf-8")
    resource = root / "guide.md"
    resource.write_text("read once", encoding="utf-8")
    skill = _workspace_skill(root, instructions="Read `guide.md`.")
    repository, wrapper = _deepsearch_context(
        tmp_path,
        skill,
        skill_resource_manifest(skill),
        monkeypatch,
    )
    original_reader = resource_module._read_bounded_resource
    reads: list[Path] = []

    def count_read(path: Path) -> bytes:
        reads.append(path)
        return original_reader(path)

    clock_values = iter([100.0, 101.0])
    monkeypatch.setattr(resource_module, "monotonic", lambda: next(clock_values))
    monkeypatch.setattr(resource_module, "_read_bounded_resource", count_read)
    tool = build_skill_resource_tool(repository, skill)
    arguments = json.dumps({"paths": ["guide.md"]})

    asyncio.run(tool.on_invoke_tool(wrapper, arguments))
    with pytest.raises(RuntimeError, match="deepsearch_resource_invocation_replayed"):
        asyncio.run(tool.on_invoke_tool(wrapper, arguments))

    assert reads == [resource.resolve()]
    run = repository.get_agent_run(wrapper.context.run_id)
    assert run is not None and run.deepsearch_budget is not None
    assert len(run.deepsearch_budget.reservations) == 1
    assert run.deepsearch_budget.consumed.tool_calls == 1


@pytest.mark.parametrize(
    "context_update",
    [
        {"node_attempt": None},
        {"skill_id": None},
    ],
)
def test_deepsearch_resource_read_requires_complete_lineage_before_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    context_update: dict[str, object],
) -> None:
    root = tmp_path / "lineage-deepsearch-resource-skill"
    root.mkdir()
    (root / "SKILL.md").write_text("Read `guide.md`.", encoding="utf-8")
    (root / "guide.md").write_text("must not be read", encoding="utf-8")
    skill = _workspace_skill(root, instructions="Read `guide.md`.")
    repository, wrapper = _deepsearch_context(
        tmp_path,
        skill,
        skill_resource_manifest(skill),
        monkeypatch,
    )
    wrapper.context = wrapper.context.model_copy(update=context_update)
    reads: list[Path] = []
    monkeypatch.setattr(resource_module, "_read_bounded_resource", lambda path: reads.append(path))

    with pytest.raises(RuntimeError, match="deepsearch_resource_lineage_incomplete"):
        asyncio.run(
            build_skill_resource_tool(repository, skill).on_invoke_tool(
                wrapper,
                json.dumps({"paths": ["guide.md"]}),
            )
        )

    assert reads == []


def test_deepsearch_resource_read_requires_a_budget_before_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "unbudgeted-deepsearch-resource-skill"
    root.mkdir()
    (root / "SKILL.md").write_text("Read `guide.md`.", encoding="utf-8")
    (root / "guide.md").write_text("must not be read", encoding="utf-8")
    skill = _workspace_skill(root, instructions="Read `guide.md`.")
    repository, wrapper = _deepsearch_context(
        tmp_path,
        skill,
        skill_resource_manifest(skill),
        monkeypatch,
    )
    persisted = repository.get_agent_run(wrapper.context.run_id)
    assert persisted is not None
    monkeypatch.setattr(
        repository,
        "get_agent_run",
        lambda _run_id: persisted.model_copy(update={"deepsearch_budget": None}),
    )
    reads: list[Path] = []
    monkeypatch.setattr(resource_module, "_read_bounded_resource", lambda path: reads.append(path))

    with pytest.raises(RuntimeError, match="deepsearch_resource_budget_unavailable"):
        asyncio.run(
            build_skill_resource_tool(repository, skill).on_invoke_tool(
                wrapper,
                json.dumps({"paths": ["guide.md"]}),
            )
        )

    assert reads == []


def test_frozen_empty_manifest_denies_resources_added_after_planning(tmp_path: Path) -> None:
    skill_file = tmp_path / "workspace-skill" / "SKILL.md"
    skill_file.parent.mkdir()
    skill_file.write_text("skill", encoding="utf-8")
    skill = SkillDefinition(
        id="skill_empty_frozen_manifest",
        name="empty-frozen-manifest",
        title="Empty frozen manifest",
        description="Empty frozen manifest fixture",
        instructions="No resources.",
        source_path=str(skill_file),
        source_scope=SkillSourceScope.WORKSPACE,
        content_hash="a" * 64,
    )
    repository, wrapper = _running_context(
        tmp_path,
        skill,
        {},
        manifest_frozen=True,
    )
    (skill_file.parent / "added.md").write_text("added later", encoding="utf-8")

    with pytest.raises(PermissionError, match="outside the frozen"):
        asyncio.run(
            build_skill_resource_tool(repository, skill).on_invoke_tool(
                wrapper,
                json.dumps({"paths": ["added.md"]}),
            )
        )


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
