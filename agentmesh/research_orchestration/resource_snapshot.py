from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath

from agentmesh.models import AgentRun, SkillDefinition
from agentmesh.research_orchestration.artifacts import ArtifactDraft, ArtifactLineage, ArtifactStore
from agentmesh.research_orchestration.compiler import FrozenDocument, FrozenResourceSnapshot
from agentmesh.research_orchestration.contracts import RequirementVersion, canonical_json_bytes, canonical_sha256
from agentmesh.skill_runtime.resources import approved_skill_wiki_root, resolve_skill_resource
from agentmesh.store import SQLiteStore

RESOURCE_SNAPSHOT_KIND = "resource_snapshot"
RESOURCE_SNAPSHOT_SCHEMA = "resource-snapshot-v1"

_MAX_RESOURCE_FILES = 12
_MAX_RESOURCE_BYTES = 200 * 1024
_MAX_RESOURCE_BATCH_BYTES = 400 * 1024


class ResourceSnapshotError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class ResourceSnapshotFactory:
    """Seal the exact, server-approved Skill resources selected for one requirement."""

    def __init__(self, repository: SQLiteStore, artifacts: ArtifactStore):
        if artifacts.repository is not repository:
            raise ValueError("ResourceSnapshotFactory dependencies must share one repository")
        self.repository = repository
        self.artifacts = artifacts

    def create(
        self,
        *,
        run: AgentRun,
        requirement: RequirementVersion,
        skill: SkillDefinition,
        relative_paths: list[str],
    ) -> FrozenResourceSnapshot:
        self._validate_context(run, requirement, skill)
        if not relative_paths:
            raise ResourceSnapshotError("resource_snapshot_empty")
        if len(relative_paths) > _MAX_RESOURCE_FILES:
            raise ResourceSnapshotError("resource_snapshot_file_limit")

        normalized_paths: list[str] = []
        for value in relative_paths:
            normalized_paths.append(self._normalize_relative_path(value))
        if len(normalized_paths) != len(set(normalized_paths)):
            raise ResourceSnapshotError("resource_path_duplicate")

        files: list[dict[str, str | int]] = []
        resolved_paths: set[Path] = set()
        total_size = 0
        for relative_path in sorted(normalized_paths):
            self._reject_symlink_path(skill, relative_path)
            resource = resolve_skill_resource(skill, relative_path)
            if resource is None or not resource.is_file():
                raise ResourceSnapshotError("resource_unavailable")
            if resource in resolved_paths:
                raise ResourceSnapshotError("resource_path_duplicate")
            resolved_paths.add(resource)
            try:
                content = resource.read_bytes()
            except OSError:
                raise ResourceSnapshotError("resource_read_failed") from None
            try:
                content.decode("utf-8")
            except UnicodeDecodeError:
                raise ResourceSnapshotError("resource_encoding_invalid") from None
            if len(content) > _MAX_RESOURCE_BYTES:
                raise ResourceSnapshotError("resource_size_limit")
            total_size += len(content)
            if total_size > _MAX_RESOURCE_BATCH_BYTES:
                raise ResourceSnapshotError("resource_batch_size_limit")
            files.append(
                {
                    "path": relative_path,
                    "content_hash": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                }
            )

        manifest = {"files": files}
        manifest_hash = canonical_sha256(manifest)
        artifact_identity_hash = canonical_sha256(
            {
                "run_id": run.id,
                "requirement_version_id": requirement.id,
                "manifest_hash": manifest_hash,
            }
        )
        artifact_id = f"artifact_resource_snapshot_{artifact_identity_hash}"
        lineage = ArtifactLineage(
            run_id=run.id,
            user_id=run.user_id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            requirement_version_id=requirement.id,
        )
        reference = self.artifacts.seal(
            lineage,
            ArtifactDraft(
                artifact_id=artifact_id,
                kind=RESOURCE_SNAPSHOT_KIND,
                schema_version=RESOURCE_SNAPSHOT_SCHEMA,
                content=manifest,
            ),
        )
        if reference.artifact_id != artifact_id or reference.content_hash != manifest_hash:
            raise ResourceSnapshotError("resource_snapshot_seal_mismatch")
        document = FrozenDocument(content=manifest, content_hash=reference.content_hash)
        return FrozenResourceSnapshot(
            artifact_id=reference.artifact_id,
            content_hash=reference.content_hash,
            size_bytes=len(canonical_json_bytes(manifest)),
            manifest=document,
        )

    def _validate_context(
        self,
        run: AgentRun,
        requirement: RequirementVersion,
        skill: SkillDefinition,
    ) -> None:
        stored_run = self.repository.get_agent_run(run.id)
        if (
            stored_run is None
            or stored_run.orchestration_version != "research-v2"
            or stored_run.user_id != run.user_id
            or stored_run.workspace_id != run.workspace_id
            or stored_run.project_id != run.project_id
            or requirement.run_id != run.id
        ):
            raise ResourceSnapshotError("resource_snapshot_context_invalid")
        stored_requirement = self.repository.get_research_requirement_version(requirement.id)
        if stored_requirement != requirement:
            raise ResourceSnapshotError("resource_snapshot_context_invalid")
        stored_skill = self.repository.get_skill_definition(skill.id)
        if stored_skill != skill or not skill.enabled:
            raise ResourceSnapshotError("resource_snapshot_skill_invalid")

    @staticmethod
    def _normalize_relative_path(value: str) -> str:
        if not isinstance(value, str) or not value or len(value) > 500 or "\\" in value or "\x00" in value:
            raise ResourceSnapshotError("resource_path_invalid")
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or not path.parts
            or path.as_posix() != value
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ResourceSnapshotError("resource_path_invalid")
        return value

    @classmethod
    def _reject_symlink_path(cls, skill: SkillDefinition, relative_path: str) -> None:
        relative = Path(*PurePosixPath(relative_path).parts)
        try:
            package_root = Path(skill.source_path).resolve(strict=True).parent
        except OSError:
            raise ResourceSnapshotError("resource_snapshot_skill_invalid") from None
        candidates: list[tuple[Path, Path]] = [(package_root / relative, package_root)]
        allowed_wiki_root = approved_skill_wiki_root(skill)
        configured = os.getenv("AGENTMESH_WIKI_ROOT", "").strip()
        if allowed_wiki_root is not None:
            candidates.append((allowed_wiki_root / relative, allowed_wiki_root))
            if configured:
                try:
                    configured_root = Path(configured).expanduser().resolve(strict=True)
                except OSError:
                    configured_root = None
                if configured_root is not None:
                    candidates.append((configured_root / relative, configured_root))
        if any(cls._contains_symlink(candidate, root) for candidate, root in candidates):
            raise ResourceSnapshotError("resource_symlink_forbidden")

    @staticmethod
    def _contains_symlink(candidate: Path, root: Path) -> bool:
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            return True
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                return True
        return False
