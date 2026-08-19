from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentmesh.agent_runtime.model_factory import SelectedSDKModel
from agentmesh.agent_runtime.structured_output import SDKStructuredOutputMode
from agentmesh.models import AgentRun, AgentRunStatus, ArtifactVerificationState, SkillDefinition, SkillSourceScope
from agentmesh.research_orchestration.artifacts import (
    ArtifactDraft,
    ArtifactLineage,
    ArtifactRef,
    ArtifactStore,
    ArtifactStoreError,
)
from agentmesh.research_orchestration.capabilities import frozen_model_policy
from agentmesh.research_orchestration.compiler import (
    CompetitiveCapabilitySnapshot,
    CompetitivePlanCompiler,
    FrozenModelPolicy,
    PlanCompileError,
)
from agentmesh.research_orchestration.contracts import (
    RequirementVersion,
    ResearchPhase,
    ResearchWorkflow,
    canonical_json_bytes,
    canonical_sha256,
)
from agentmesh.research_orchestration.resource_snapshot import (
    RESOURCE_SNAPSHOT_KIND,
    RESOURCE_SNAPSHOT_SCHEMA,
    ResourceSnapshotError,
    ResourceSnapshotFactory,
)
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore
from tests.research_orchestration_testkit import competitive_snapshot, compiled_competitive_plan


@dataclass(frozen=True)
class SnapshotContext:
    repository: SQLiteStore
    artifacts: ArtifactStore
    factory: ResourceSnapshotFactory
    run: AgentRun
    requirement: RequirementVersion
    skill: SkillDefinition
    skill_root: Path

    @property
    def lineage(self) -> ArtifactLineage:
        return ArtifactLineage(
            run_id=self.run.id,
            user_id=self.run.user_id,
            workspace_id=self.run.workspace_id,
            project_id=self.run.project_id,
            requirement_version_id=self.requirement.id,
        )


def _context(tmp_path: Path) -> SnapshotContext:
    repository = SQLiteStore(tmp_path / "resource-snapshot.sqlite3")
    run = AgentRun(
        id="run_resource_snapshot",
        thread_id="thread_resource_snapshot",
        user_id="user_1",
        workspace_id="workspace_1",
        project_id="project_1",
        input_text="compare",
        status=AgentRunStatus.PLANNING,
        orchestration_version="research-v2",
        orchestration_mode="preview",
    )
    repository.save_agent_run(run)
    requirement_payload = {"goal": "compare two products"}
    requirement = RequirementVersion(
        id="requirement_resource_snapshot",
        run_id=run.id,
        version=1,
        schema_version="research-requirement-v2",
        task_type="competitive_research",
        payload=requirement_payload,
        content_hash=canonical_sha256(requirement_payload),
    )
    repository.add_research_requirement_version(requirement)
    repository.create_research_workflow(
        ResearchWorkflow(
            run_id=run.id,
            phase=ResearchPhase.PLANNING,
            active_requirement_version_id=requirement.id,
        )
    )

    skill_root = tmp_path / "skill-package"
    skill_root.mkdir()
    skill_file = skill_root / "SKILL.md"
    skill_file.write_text("---\nname: test-skill\n---\n", encoding="utf-8")
    skill = SkillDefinition(
        id="skill_resource_snapshot",
        name="test-skill",
        title="Test skill",
        description="Test resource snapshot boundaries",
        instructions=skill_file.read_text(encoding="utf-8"),
        source_path=str(skill_file),
        source_scope=SkillSourceScope.BUILTIN,
        content_hash=hashlib.sha256(skill_file.read_bytes()).hexdigest(),
    )
    repository.save_skill_definition(skill)
    artifacts = ArtifactStore(repository)
    return SnapshotContext(
        repository=repository,
        artifacts=artifacts,
        factory=ResourceSnapshotFactory(repository, artifacts),
        run=run,
        requirement=requirement,
        skill=skill,
        skill_root=skill_root,
    )


def _write(context: SnapshotContext, relative_path: str, content: bytes) -> Path:
    path = context.skill_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_factory_seals_sorted_byte_faithful_manifest_and_is_idempotent(tmp_path: Path) -> None:
    context = _context(tmp_path)
    alpha = _write(context, "resources/alpha.md", "alpha-方法".encode())
    beta = _write(context, "resources/beta.txt", b"beta\r\n")

    first = context.factory.create(
        run=context.run,
        requirement=context.requirement,
        skill=context.skill,
        relative_paths=["resources/beta.txt", "resources/alpha.md"],
    )
    second = context.factory.create(
        run=context.run,
        requirement=context.requirement,
        skill=context.skill,
        relative_paths=["resources/alpha.md", "resources/beta.txt"],
    )

    assert first == second
    assert [item["path"] for item in first.manifest.content["files"]] == [
        "resources/alpha.md",
        "resources/beta.txt",
    ]
    assert first.manifest.content["files"] == [
        {
            "path": "resources/alpha.md",
            "content_hash": hashlib.sha256(alpha.read_bytes()).hexdigest(),
            "size_bytes": len(alpha.read_bytes()),
        },
        {
            "path": "resources/beta.txt",
            "content_hash": hashlib.sha256(beta.read_bytes()).hexdigest(),
            "size_bytes": len(beta.read_bytes()),
        },
    ]
    assert first.content_hash == canonical_sha256(first.manifest.content)
    assert first.size_bytes == len(canonical_json_bytes(first.manifest.content))
    expected_identity_hash = canonical_sha256(
        {
            "run_id": context.run.id,
            "requirement_version_id": context.requirement.id,
            "manifest_hash": first.content_hash,
        }
    )
    assert first.artifact_id == f"artifact_resource_snapshot_{expected_identity_hash}"

    artifact = context.repository.get_artifact(first.artifact_id)
    assert artifact is not None
    assert artifact.verification_state == ArtifactVerificationState.SEALED
    assert artifact.artifact_type == RESOURCE_SNAPSHOT_KIND
    assert artifact.schema_version == RESOURCE_SNAPSHOT_SCHEMA
    assert artifact.plan_version_id is None
    assert artifact.attempt_id is None
    assert artifact.step_number is None
    assert json.loads(artifact.content) == first.manifest.content
    assert context.artifacts.read_verified(
        reference=ArtifactRef(artifact_id=first.artifact_id, content_hash=first.content_hash),
        scope=context.lineage,
        expected_kind=RESOURCE_SNAPSHOT_KIND,
        expected_schema_version=RESOURCE_SNAPSHOT_SCHEMA,
    ) == artifact


def test_changed_resource_creates_a_new_immutable_snapshot(tmp_path: Path) -> None:
    context = _context(tmp_path)
    resource = _write(context, "resources/method.md", b"version one")
    first = context.factory.create(
        run=context.run,
        requirement=context.requirement,
        skill=context.skill,
        relative_paths=["resources/method.md"],
    )

    resource.write_bytes(b"version two")
    second = context.factory.create(
        run=context.run,
        requirement=context.requirement,
        skill=context.skill,
        relative_paths=["resources/method.md"],
    )

    assert second.content_hash != first.content_hash
    assert second.artifact_id != first.artifact_id
    assert context.repository.get_artifact(first.artifact_id) is not None
    assert context.repository.get_artifact(second.artifact_id) is not None


def test_identical_manifests_in_different_runs_do_not_share_artifact_identity(tmp_path: Path) -> None:
    context = _context(tmp_path)
    _write(context, "resources/method.md", b"method")
    first = context.factory.create(
        run=context.run,
        requirement=context.requirement,
        skill=context.skill,
        relative_paths=["resources/method.md"],
    )
    second_run = context.run.model_copy(
        update={
            "id": "run_resource_snapshot_2",
            "thread_id": "thread_resource_snapshot_2",
        }
    )
    context.repository.save_agent_run(second_run)
    second_requirement = context.requirement.model_copy(
        update={
            "id": "requirement_resource_snapshot_2",
            "run_id": second_run.id,
        }
    )
    context.repository.add_research_requirement_version(second_requirement)
    context.repository.create_research_workflow(
        ResearchWorkflow(
            run_id=second_run.id,
            phase=ResearchPhase.PLANNING,
            active_requirement_version_id=second_requirement.id,
        )
    )

    second = context.factory.create(
        run=second_run,
        requirement=second_requirement,
        skill=context.skill,
        relative_paths=["resources/method.md"],
    )

    assert second.content_hash == first.content_hash
    assert second.artifact_id != first.artifact_id


def test_factory_seals_an_approved_wiki_resource_for_the_builtin_skill(
    tmp_path: Path,
    configure_pilot_wiki,
) -> None:
    context = _context(tmp_path)
    wiki_root = configure_pilot_wiki(tmp_path / "wiki")
    method = (
        wiki_root
        / "jd-design-system-md-v16"
        / "horizontal"
        / "user-research"
        / "methods"
        / "toolbox"
        / "analysis"
        / "competitive-analysis.md"
    )
    method.parent.mkdir(parents=True, exist_ok=True)
    method.write_text("# Canonical competitive method\n", encoding="utf-8")
    catalog = SkillCatalogService(context.repository)
    catalog.reload()
    skill = catalog.get_by_name("competitive-analysis")
    assert skill is not None

    snapshot = context.factory.create(
        run=context.run,
        requirement=context.requirement,
        skill=skill,
        relative_paths=["methods/toolbox/analysis/competitive-analysis.md"],
    )

    assert snapshot.manifest.content["files"] == [
        {
            "path": "methods/toolbox/analysis/competitive-analysis.md",
            "content_hash": hashlib.sha256(method.read_bytes()).hexdigest(),
            "size_bytes": len(method.read_bytes()),
        }
    ]


@pytest.mark.parametrize(
    ("relative_paths", "expected_code"),
    [
        ([], "resource_snapshot_empty"),
        (["/etc/passwd"], "resource_path_invalid"),
        (["../escape.md"], "resource_path_invalid"),
        (["resources/../outside.md"], "resource_path_invalid"),
        (["./resources/method.md"], "resource_path_invalid"),
        (["resources//method.md"], "resource_path_invalid"),
        (["resources/method.md", "resources/method.md"], "resource_path_duplicate"),
        (["resources"], "resource_unavailable"),
        (["resources/missing.md"], "resource_unavailable"),
    ],
)
def test_factory_rejects_noncanonical_escaping_duplicate_and_unavailable_paths(
    tmp_path: Path,
    relative_paths: list[str],
    expected_code: str,
) -> None:
    context = _context(tmp_path)
    _write(context, "resources/method.md", b"method")

    with pytest.raises(ResourceSnapshotError) as raised:
        context.factory.create(
            run=context.run,
            requirement=context.requirement,
            skill=context.skill,
            relative_paths=relative_paths,
        )

    assert raised.value.code == expected_code


def test_factory_rejects_leaf_and_ancestor_symlinks(tmp_path: Path) -> None:
    context = _context(tmp_path)
    real_directory = context.skill_root / "real"
    real_directory.mkdir()
    (real_directory / "method.md").write_bytes(b"method")
    (context.skill_root / "method-link.md").symlink_to(real_directory / "method.md")
    (context.skill_root / "directory-link").symlink_to(real_directory, target_is_directory=True)

    for relative_path in ("method-link.md", "directory-link/method.md"):
        with pytest.raises(ResourceSnapshotError) as raised:
            context.factory.create(
                run=context.run,
                requirement=context.requirement,
                skill=context.skill,
                relative_paths=[relative_path],
            )
        assert raised.value.code == "resource_symlink_forbidden"


def test_factory_does_not_trust_a_preexisting_artifact_with_the_expected_id(tmp_path: Path) -> None:
    context = _context(tmp_path)
    resource = _write(context, "resources/method.md", b"method")
    manifest = {
        "files": [
            {
                "path": "resources/method.md",
                "content_hash": hashlib.sha256(resource.read_bytes()).hexdigest(),
                "size_bytes": len(resource.read_bytes()),
            }
        ]
    }
    artifact_identity_hash = canonical_sha256(
        {
            "run_id": context.run.id,
            "requirement_version_id": context.requirement.id,
            "manifest_hash": canonical_sha256(manifest),
        }
    )
    artifact_id = f"artifact_resource_snapshot_{artifact_identity_hash}"
    context.artifacts.seal(
        context.lineage,
        ArtifactDraft(
            artifact_id=artifact_id,
            kind=RESOURCE_SNAPSHOT_KIND,
            schema_version=RESOURCE_SNAPSHOT_SCHEMA,
            content={"files": [{"path": "forged.md", "content_hash": "0" * 64, "size_bytes": 0}]},
        ),
    )

    with pytest.raises(ArtifactStoreError, match="artifact_conflict"):
        context.factory.create(
            run=context.run,
            requirement=context.requirement,
            skill=context.skill,
            relative_paths=["resources/method.md"],
        )

    assert "artifact_id" not in inspect.signature(context.factory.create).parameters


@pytest.mark.parametrize(
    "payload",
    [
        {"structured_output_mode": "json_schema", "adapter_compatibility_id": "adapter:v1"},
        {
            "requested_model_id": "",
            "structured_output_mode": "json_schema",
            "adapter_compatibility_id": "adapter:v1",
        },
        {
            "requested_model_id": "gpt-primary",
            "structured_output_mode": "json_schema",
            "adapter_compatibility_id": "   ",
        },
    ],
)
def test_frozen_model_policy_rejects_missing_or_blank_identity(payload: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        FrozenModelPolicy.model_validate(payload)


def test_model_policy_factory_rejects_mode_that_does_not_match_the_runtime_adapter() -> None:
    selected = SelectedSDKModel(
        model=object(),  # type: ignore[arg-type]
        requested_model="gpt-primary",
        actual_model="gpt-test",
        structured_output_mode=SDKStructuredOutputMode.JSON_SCHEMA,
    )

    with pytest.raises(ValueError, match="does not match"):
        frozen_model_policy(selected)


def test_compiler_fails_closed_when_model_policy_or_compatibility_was_bypassed() -> None:
    requirement, baseline = compiled_competitive_plan("run_model_policy_invalid")
    snapshot = competitive_snapshot(baseline.created_at)
    without_policy = CompetitiveCapabilitySnapshot.model_construct(
        **{
            name: getattr(snapshot, name)
            for name in CompetitiveCapabilitySnapshot.model_fields
            if name != "model_policy"
        }
    )
    with pytest.raises(PlanCompileError) as missing:
        CompetitivePlanCompiler().compile(
            requirement,
            without_policy,
            plan_version=2,
            now=baseline.created_at,
        )
    assert "model_policy_not_frozen" in missing.value.codes

    blank_compatibility = FrozenModelPolicy.model_construct(
        requested_model_id="gpt-primary",
        structured_output_mode="json_schema",
        adapter_compatibility_id="",
    )
    with pytest.raises(PlanCompileError) as incompatible:
        CompetitivePlanCompiler().compile(
            requirement,
            snapshot.model_copy(update={"model_policy": blank_compatibility}),
            plan_version=2,
            now=baseline.created_at,
        )
    assert "model_adapter_compatibility_not_frozen" in incompatible.value.codes


def test_frozen_model_policy_is_part_of_the_canonical_plan_hash() -> None:
    requirement, baseline = compiled_competitive_plan("run_model_policy")
    baseline_snapshot = competitive_snapshot(baseline.created_at)
    changed_snapshot = baseline_snapshot.model_copy(
        update={
            "model_policy": FrozenModelPolicy(
                requested_model_id="gpt-secondary",
                structured_output_mode="json_object",
                adapter_compatibility_id="agentmesh.openai-chat-completions.json-object:v1",
            )
        }
    )
    changed = CompetitivePlanCompiler().compile(
        requirement,
        changed_snapshot,
        plan_version=2,
        now=baseline.created_at,
    )

    assert baseline.payload["control_snapshot"]["model_policy"] == {
        "requested_model_id": "gpt-primary",
        "structured_output_mode": "json_schema",
        "adapter_compatibility_id": "openai-agents-sdk.chat-completions.json-schema:v1",
    }
    assert changed.plan_hash != baseline.plan_hash
