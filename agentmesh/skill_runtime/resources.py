from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from agents import FunctionTool
from agents.strict_schema import ensure_strict_json_schema

from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.agent_runtime.settings import strict_tools_enabled
from agentmesh.models import AgentRunStatus, AuditEvent, SkillDefinition, SkillSourceScope, Source
from agentmesh.store import SQLiteStore

_MAX_RESOURCE_BYTES = 200 * 1024
_MAX_RESOURCE_BATCH_BYTES = 400 * 1024
_MAX_RESOURCE_MANIFEST_BYTES = 4 * 1024 * 1024
_MAX_RESOURCE_MANIFEST_FILES = 256
_MAX_RESOURCE_SCAN_ENTRIES = 2000
_RESOURCE_REFERENCE_PATTERN = re.compile(r"`([^`\n]+\.(?:md|json|ya?ml|txt))`")


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _contains_symlink(path: Path, root: Path) -> bool:
    try:
        relative = Path(os.path.abspath(path)).relative_to(root)
    except ValueError:
        return True
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return True
    return False


def _read_bounded_resource(path: Path) -> bytes:
    with path.open("rb") as handle:
        data = handle.read(_MAX_RESOURCE_BYTES + 1)
    if len(data) > _MAX_RESOURCE_BYTES:
        raise ValueError("Skill resource exceeds the 200 KiB read limit")
    return data


def _is_managed_wiki_import(skill: SkillDefinition) -> bool:
    return (
        skill.source_scope == SkillSourceScope.BUILTIN
        and skill.metadata.get("agentmesh-wiki-import", "").strip().lower() == "true"
    )


def _configured_wiki_root() -> Path | None:
    configured = os.getenv("AGENTMESH_WIKI_ROOT", "").strip()
    if not configured:
        return None
    try:
        root = Path(configured).expanduser().resolve(strict=True)
    except OSError:
        return None
    return root if root.is_dir() else None


def _approved_wiki_source_file(skill: SkillDefinition, configured_root: Path) -> Path | None:
    if skill.source_scope != SkillSourceScope.BUILTIN:
        return None
    source = skill.metadata.get("source", "").strip()
    if not source or "\\" in source or "\x00" in source:
        return None
    parts = Path(source).parts
    if len(parts) < 2 or parts[0] != "2C-DesignWiki" or any(part in {"", ".", ".."} for part in parts):
        return None
    candidate = configured_root.joinpath(*parts[1:])
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None
    if (
        not _within(resolved, configured_root)
        or not resolved.is_file()
        or _contains_symlink(candidate, configured_root)
    ):
        return None
    return resolved


def _wiki_boundary(skill: SkillDefinition) -> tuple[str, ...] | None:
    if skill.source_scope != SkillSourceScope.BUILTIN:
        return None
    source = skill.metadata.get("source", "").strip()
    if not source:
        return None
    parts = list(Path(source).parts)
    if not parts or parts[0] != "2C-DesignWiki" or any(part in {"", ".", ".."} for part in parts):
        return None
    parts = parts[1:]
    marker_indexes = [parts.index(marker) for marker in ("skills", "_skills") if marker in parts]
    if marker_indexes:
        boundary = tuple(parts[: min(marker_indexes)])
    elif len(parts) >= 3 and parts[-1] == "SKILL.md":
        boundary = tuple(parts[:-2])
    else:
        return None
    return boundary or None


def _approved_wiki_root(skill: SkillDefinition, configured_root: Path) -> Path | None:
    boundary = _wiki_boundary(skill)
    if boundary is None:
        return None
    if len(configured_root.parts) >= len(boundary) and configured_root.parts[-len(boundary) :] == boundary:
        return configured_root if configured_root.is_dir() else None
    candidate = configured_root.joinpath(*boundary)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None
    return resolved if resolved.is_dir() and _within(resolved, configured_root) else None


def approved_skill_wiki_root(skill: SkillDefinition) -> Path | None:
    configured_root = _configured_wiki_root()
    if configured_root is None:
        return None
    return _approved_wiki_root(skill, configured_root)


def skill_wiki_corpus_ready(skill: SkillDefinition, capability: str = "wiki.corpus") -> bool:
    root = approved_skill_wiki_root(skill)
    if root is None:
        return False
    if capability == "wiki.experiments":
        return (root / "_knowledge" / "experiments" / "INDEX.json").is_file()
    checked = 0
    try:
        for path in root.rglob("*"):
            checked += 1
            if path.is_file():
                return True
            if checked >= 200:
                break
    except OSError:
        return False
    return False


def resolve_skill_resource(skill: SkillDefinition, reference: str) -> Path | None:
    if not reference or len(reference) > 500 or "\\" in reference or "\x00" in reference:
        return None
    relative = Path(reference)
    managed_import = _is_managed_wiki_import(skill)
    if relative.is_absolute() or (".." in relative.parts and not managed_import):
        return None
    package_root = Path(skill.source_path).resolve().parent
    candidates: list[tuple[Path, Path]] = [(package_root / relative, package_root)]
    configured_root = _configured_wiki_root()
    if configured_root is not None:
        allowed_wiki_root = approved_skill_wiki_root(skill)
        if allowed_wiki_root is not None:
            source_file = _approved_wiki_source_file(skill, configured_root)
            if source_file is not None:
                source_boundary = configured_root if managed_import else allowed_wiki_root
                candidates.append((source_file.parent / relative, source_boundary))
            candidates.extend(
                [
                    (allowed_wiki_root / relative, allowed_wiki_root),
                    (
                        configured_root / relative,
                        configured_root if managed_import else allowed_wiki_root,
                    ),
                ]
            )
    for candidate, allowed_root in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if _within(resolved, allowed_root) and resolved.is_file() and not _contains_symlink(candidate, allowed_root):
            return resolved
    return None


def _package_resource_references(root: Path) -> set[str]:
    references: set[str] = set()
    scanned = 0
    try:
        for directory, names, files in os.walk(root, followlinks=False):
            base = Path(directory)
            names[:] = sorted(name for name in names if not (base / name).is_symlink())
            for name in sorted(files):
                scanned += 1
                if scanned > _MAX_RESOURCE_SCAN_ENTRIES:
                    return references
                path = base / name
                if path.name != "SKILL.md" and not path.is_symlink():
                    references.add(path.relative_to(root).as_posix())
    except OSError:
        pass
    return references


def skill_resource_manifest(skill: SkillDefinition) -> dict[str, str]:
    discovered_references: set[str] = set()
    package_root = Path(skill.source_path).resolve().parent
    resource_roots = [package_root]
    configured_root = _configured_wiki_root()
    if configured_root is not None:
        source_file = _approved_wiki_source_file(skill, configured_root)
        if source_file is not None and source_file.parent != package_root:
            resource_roots.append(source_file.parent)
    for resource_root in resource_roots:
        discovered_references.update(_package_resource_references(resource_root))
    declared_references = set(_RESOURCE_REFERENCE_PATTERN.findall(skill.instructions))
    references = [*sorted(declared_references), *sorted(discovered_references - declared_references)]
    manifest: dict[str, str] = {}
    total_size = 0
    for reference in references:
        if len(manifest) >= _MAX_RESOURCE_MANIFEST_FILES:
            break
        resource = resolve_skill_resource(skill, reference)
        if resource is None:
            continue
        try:
            data = _read_bounded_resource(resource)
            data.decode("utf-8")
        except (OSError, UnicodeError, ValueError):
            continue
        if total_size + len(data) > _MAX_RESOURCE_MANIFEST_BYTES:
            continue
        manifest[reference] = hashlib.sha256(data).hexdigest()
        total_size += len(data)
    return manifest


def build_skill_resource_tool(repository: SQLiteStore, skill: SkillDefinition) -> FunctionTool:
    async def invoke(ctx, raw_arguments: str) -> str:  # noqa: ANN001
        if not isinstance(ctx.context, AgentMeshRunContext):
            raise RuntimeError("AgentMesh run context is required")
        if not repository.user_can_execute_agent_run(
            ctx.context.user_id,
            ctx.context.run_id,
            allowed_statuses={AgentRunStatus.RUNNING},
        ):
            raise PermissionError("Agent run project access was revoked")
        payload = json.loads(raw_arguments)
        raw_paths = payload.get("paths")
        legacy_single = raw_paths is None
        if legacy_single:
            references = [str(payload.get("path", "")).strip()]
        else:
            if not isinstance(raw_paths, list) or not 1 <= len(raw_paths) <= 12:
                raise ValueError("Skill resource batch must contain between 1 and 12 paths")
            references = [str(value).strip() for value in raw_paths]
        references = list(dict.fromkeys(references))

        resolved_resources: list[tuple[str, Path, str]] = []
        total_size = 0
        approved_manifest = ctx.context.approved_resource_hashes
        for relative in references:
            resource = resolve_skill_resource(skill, relative)
            if resource is None:
                safe_reference = relative.replace("\n", " ").replace("\r", " ")[:240]
                raise FileNotFoundError(
                    f"Skill resource is unavailable in the approved roots: {safe_reference}"
                )
            if (approved_manifest or _is_managed_wiki_import(skill)) and relative not in approved_manifest:
                raise PermissionError("Skill resource is outside the frozen node resource manifest")
            try:
                data = _read_bounded_resource(resource)
            except OSError as error:
                raise FileNotFoundError("Skill resource became unavailable") from error
            actual_hash = hashlib.sha256(data).hexdigest()
            if approved_manifest and actual_hash != approved_manifest[relative]:
                raise PermissionError("Skill resource changed after the node resource manifest was frozen")
            total_size += len(data)
            if total_size > _MAX_RESOURCE_BATCH_BYTES:
                raise ValueError("Skill resource batch exceeds the 400 KiB read limit")
            try:
                content = data.decode("utf-8")
            except UnicodeError as error:
                raise ValueError("Skill resource is not UTF-8 text") from error
            resolved_resources.append((relative, resource, content))

        results: list[dict[str, object]] = []
        for relative, resource, content in resolved_resources:
            source_id = "src_skill_resource_" + hashlib.sha256(
                f"{ctx.context.run_id}:{skill.id}:{relative}".encode()
            ).hexdigest()[:24]
            source = repository.add_source(
                Source(
                    id=source_id,
                    title=f"{skill.title}: {resource.name}",
                    source_type="skill_resource",
                    reference=relative,
                    workspace_id=ctx.context.workspace_id,
                    project_id=ctx.context.project_id,
                    user_id=ctx.context.user_id,
                    run_id=ctx.context.run_id,
                    skill_id=skill.id,
                )
            )
            ctx.context.resource_references = list(dict.fromkeys([*ctx.context.resource_references, relative]))
            ctx.context.source_ids = list(dict.fromkeys([*ctx.context.source_ids, source.id]))
            repository.add_audit_event(
                AuditEvent(
                    actor=ctx.context.user_id,
                    action="sdk_skill_resource_read",
                    target_type="skill_definition",
                    target_id=skill.id,
                    workspace_id=ctx.context.workspace_id,
                    project_id=ctx.context.project_id,
                    metadata={"run_id": ctx.context.run_id, "path": relative, "source_id": source.id},
                )
            )
            results.append({"path": relative, "content": content, "source": source.model_dump(mode="json")})
        response: dict[str, object] = results[0] if legacy_single else {"resources": results}
        return json.dumps(response, ensure_ascii=False, default=str)

    return FunctionTool(
        name="read_skill_resource",
        description=(
            "Read 1-12 UTF-8 text resources from the activated Skill package or its registered Wiki subtree. "
            "Batch related relative paths in one call to conserve the shared 24-call budget. "
            "Each response item includes the only valid Source identity for citation."
        ),
        params_json_schema=ensure_strict_json_schema(
            {
                "type": "object",
                "properties": {
                    "paths": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "minItems": 1,
                        "maxItems": 12,
                    }
                },
                "required": ["paths"],
                "additionalProperties": False,
            }
        ),
        on_invoke_tool=invoke,
        strict_json_schema=strict_tools_enabled(),
        needs_approval=False,
        timeout_seconds=10,
        timeout_behavior="error_as_result",
    )
