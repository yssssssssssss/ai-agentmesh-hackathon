from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from time import monotonic

from agents import FunctionTool
from agents.strict_schema import ensure_strict_json_schema

from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.agent_runtime.settings import strict_tools_enabled
from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.deepsearch.budget import DeepSearchBudgetMeter
from agentmesh.models import (
    AgentPlanningMode,
    AgentRunStatus,
    AuditEvent,
    DeepSearchBudgetUsageV1,
    RuntimeToolCallClaimV1,
    RuntimeToolCallOutcomeV1,
    SkillCapabilityProfile,
    SkillDefinition,
    SkillResourceManifestV1,
    SkillSourceScope,
    Source,
)
from agentmesh.runtime_admission import current_orchestration_admission
from agentmesh.skill_runtime.quiesce import OrchestrationQuiesceController
from agentmesh.store import RuntimeToolCallConflict, SQLiteStore

_MAX_RESOURCE_BYTES = 200 * 1024
_MAX_RESOURCE_BATCH_BYTES = 400 * 1024
_MAX_RESOURCE_MANIFEST_BYTES = 4 * 1024 * 1024
_MAX_RESOURCE_MANIFEST_FILES = 256
_MAX_RESOURCE_SCAN_ENTRIES = 2000
_STANDARD_RESOURCE_PATH_LIMIT = 12
_RESOURCE_REFERENCE_PATTERN = re.compile(r"`([^`\n]+\.(?:md|json|ya?ml|txt))`")
_SUPPORTED_REQUIRED_RESOURCES = frozenset({"wiki.corpus", "wiki.experiments"})
_DEEPSEARCH_RESOURCE_BUDGET_CAS_ATTEMPTS = 4
_DEEPSEARCH_RESOURCE_MAXIMA = DeepSearchBudgetUsageV1(active_seconds=10, tool_calls=1)


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


def _strict_package_resource_references(root: Path) -> set[str]:
    """List every package entry or fail when the scan cannot prove completeness."""

    if not root.exists() or root.is_symlink() or not root.is_dir():
        raise ValueError("skill_resource_directory_invalid")

    references: set[str] = set()
    scanned = 0

    def scan_error(error: OSError) -> None:
        raise error

    try:
        for directory, names, files in os.walk(
            root,
            topdown=True,
            onerror=scan_error,
            followlinks=False,
        ):
            base = Path(directory)
            ordered_names = sorted(names)
            ordered_files = sorted(files)
            scanned += len(ordered_names) + len(ordered_files)
            if scanned > _MAX_RESOURCE_SCAN_ENTRIES:
                raise ValueError("skill_resource_scan_limit_exceeded")
            for name in ordered_names:
                path = base / name
                if path.is_symlink():
                    raise ValueError("skill_resource_symlink_forbidden")
                if not path.is_dir():
                    raise ValueError("skill_resource_directory_invalid")
            names[:] = ordered_names
            for name in ordered_files:
                path = base / name
                if path.is_symlink():
                    raise ValueError("skill_resource_symlink_forbidden")
                if not path.is_file():
                    raise ValueError("skill_resource_file_invalid")
                if path.name != "SKILL.md":
                    references.add(path.relative_to(root).as_posix())
    except ValueError:
        raise
    except OSError as error:
        raise ValueError("skill_resource_scan_failed") from error
    return references


def _strict_skill_resource_manifest(skill: SkillDefinition) -> dict[str, str]:
    """Build a complete bounded manifest; unlike the legacy helper it never truncates."""

    discovered_references: set[str] = set()
    package_root = Path(skill.source_path).expanduser().parent
    resource_roots = [package_root]
    configured_root = _configured_wiki_root()
    if configured_root is not None:
        source_file = _approved_wiki_source_file(skill, configured_root)
        if source_file is not None and source_file.parent.resolve() != package_root.resolve():
            resource_roots.append(source_file.parent)
    for resource_root in resource_roots:
        discovered_references.update(_strict_package_resource_references(resource_root))

    declared_references = set(_RESOURCE_REFERENCE_PATTERN.findall(skill.instructions))
    references = [*sorted(declared_references), *sorted(discovered_references - declared_references)]
    if len(references) > _MAX_RESOURCE_MANIFEST_FILES:
        raise ValueError("skill_resource_manifest_file_limit_exceeded")

    manifest: dict[str, str] = {}
    total_size = 0
    for reference in references:
        resource = resolve_skill_resource(skill, reference)
        if resource is None:
            raise ValueError("skill_resource_resolution_failed")
        try:
            data = _read_bounded_resource(resource)
        except ValueError as error:
            raise ValueError("skill_resource_file_limit_exceeded") from error
        except OSError as error:
            raise ValueError("skill_resource_read_failed") from error
        try:
            data.decode("utf-8")
        except UnicodeError as error:
            raise ValueError("skill_resource_not_utf8") from error
        total_size += len(data)
        if total_size > _MAX_RESOURCE_MANIFEST_BYTES:
            raise ValueError("skill_resource_manifest_bytes_exceeded")
        manifest[reference] = hashlib.sha256(data).hexdigest()
    return manifest


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


def build_skill_resource_manifest_snapshot(
    skill: SkillDefinition,
    profile: SkillCapabilityProfile,
) -> SkillResourceManifestV1:
    """Freeze the exact resource allowlist used by one planned Skill node."""

    if (
        profile.skill_id != skill.id
        or profile.skill_name != skill.name
        or profile.skill_version != skill.version
        or profile.skill_content_hash != skill.content_hash
    ):
        raise ValueError("skill_resource_profile_mismatch")
    required_resources = sorted(profile.required_resources)
    if len(required_resources) != len(set(required_resources)):
        raise ValueError("skill_required_resources_invalid")
    if any(reference not in _SUPPORTED_REQUIRED_RESOURCES for reference in required_resources):
        raise ValueError("skill_required_resource_unsupported")
    if any(not skill_wiki_corpus_ready(skill, reference) for reference in required_resources):
        raise ValueError("skill_required_resource_unavailable")

    resource_hashes = _strict_skill_resource_manifest(skill)
    if required_resources and not resource_hashes:
        raise ValueError("skill_required_resource_manifest_empty")
    content = {
        "schema_version": "skill-resource-manifest-v1",
        "required_resources": required_resources,
        "resource_hashes": resource_hashes,
    }
    return SkillResourceManifestV1(
        **content,
        content_hash=canonical_json_sha256(content),
    )


def _deepsearch_resource_invocation_key(
    context: AgentMeshRunContext,
    skill: SkillDefinition,
    tool_call_id: object,
) -> str:
    lineage = (
        context.requirement_version_id,
        context.plan_id,
        context.plan_version,
        context.node_id,
        context.node_step_number,
        context.node_attempt,
        context.skill_id,
    )
    if any(value is None for value in lineage):
        raise RuntimeError("deepsearch_resource_lineage_incomplete")
    if context.skill_id != skill.id:
        raise RuntimeError("deepsearch_resource_lineage_mismatch")
    if not isinstance(tool_call_id, str) or not tool_call_id:
        raise RuntimeError("deepsearch_resource_tool_call_identity_missing")
    return "skill-resource:" + canonical_json_sha256(
        {
            "run_id": context.run_id,
            "requirement_version_id": context.requirement_version_id,
            "plan_id": context.plan_id,
            "plan_version": context.plan_version,
            "node_id": context.node_id,
            "node_step_number": context.node_step_number,
            "node_attempt": context.node_attempt,
            "skill_id": context.skill_id,
            "tool_call_id": tool_call_id,
        }
    )


def _current_deepsearch_budget(repository: SQLiteStore, run_id: str):  # noqa: ANN202
    run = repository.get_agent_run(run_id)
    if (
        run is None
        or run.planning_mode is not AgentPlanningMode.DEEPSEARCH
        or run.deepsearch_budget is None
    ):
        raise RuntimeError("deepsearch_resource_budget_unavailable")
    return run.deepsearch_budget


def _reserve_deepsearch_resource_read(
    repository: SQLiteStore,
    *,
    context: AgentMeshRunContext,
    skill: SkillDefinition,
    tool_call_id: object,
) -> str:
    invocation_key = _deepsearch_resource_invocation_key(context, skill, tool_call_id)
    meter = DeepSearchBudgetMeter(repository)
    last_conflict: Exception | None = None
    for _ in range(_DEEPSEARCH_RESOURCE_BUDGET_CAS_ATTEMPTS):
        budget = _current_deepsearch_budget(repository, context.run_id)
        try:
            result = meter.reserve(
                run_id=context.run_id,
                expected_budget_version=budget.version,
                logical_operation_key=invocation_key,
                invocation_key=invocation_key,
                physical_attempt=1,
                resource_maxima=_DEEPSEARCH_RESOURCE_MAXIMA,
                # Skill package files are execution method material, not report Evidence.
                # Deliberately omit a DeepSearchToolInvocationV1 evidence identity.
                tool_invocation=None,
            )
        except Exception as error:
            if getattr(error, "code", None) != "deepsearch_budget_version_conflict":
                raise
            last_conflict = error
            continue
        if result.replayed:
            raise RuntimeError("deepsearch_resource_invocation_replayed")
        return invocation_key
    assert last_conflict is not None
    raise last_conflict


def _settle_deepsearch_resource_read(
    repository: SQLiteStore,
    *,
    run_id: str,
    invocation_key: str,
    actual_usage: DeepSearchBudgetUsageV1,
) -> None:
    meter = DeepSearchBudgetMeter(repository)
    last_conflict: Exception | None = None
    for _ in range(_DEEPSEARCH_RESOURCE_BUDGET_CAS_ATTEMPTS):
        budget = _current_deepsearch_budget(repository, run_id)
        try:
            meter.settle(
                run_id=run_id,
                expected_budget_version=budget.version,
                invocation_key=invocation_key,
                actual_usage=actual_usage,
            )
            return
        except Exception as error:
            if getattr(error, "code", None) != "deepsearch_budget_version_conflict":
                raise
            last_conflict = error
    assert last_conflict is not None
    raise last_conflict


def build_skill_resource_tool(
    repository: SQLiteStore,
    skill: SkillDefinition,
    *,
    admission: OrchestrationQuiesceController | None = None,
) -> FunctionTool:
    admission = admission or current_orchestration_admission()

    async def invoke(ctx, raw_arguments: str) -> str:  # noqa: ANN001
        if not isinstance(ctx.context, AgentMeshRunContext):
            raise RuntimeError("AgentMesh run context is required")
        if not repository.user_can_execute_agent_run(
            ctx.context.user_id,
            ctx.context.run_id,
            allowed_statuses={AgentRunStatus.RUNNING},
        ):
            raise PermissionError("Agent run project access was revoked")
        run = repository.get_agent_run(ctx.context.run_id)
        raw_call_id = getattr(ctx, "tool_call_id", None)
        call_ordinal = ctx.context.tool_call_count
        ctx.context.tool_call_count += 1
        raw_arguments_hash = hashlib.sha256(raw_arguments.encode("utf-8")).hexdigest()
        call_id = (
            raw_call_id
            if isinstance(raw_call_id, str) and raw_call_id
            else "resource_call_"
            + canonical_json_sha256(
                {
                    "run_id": ctx.context.run_id,
                    "plan_id": ctx.context.plan_id,
                    "node_id": ctx.context.node_id,
                    "skill_id": skill.id,
                    "raw_arguments_hash": raw_arguments_hash,
                    "ordinal": call_ordinal,
                }
            )[:24]
        )
        claim = RuntimeToolCallClaimV1(
            call_id=call_id,
            run_id=ctx.context.run_id,
            plan_id=ctx.context.plan_id,
            node_id=ctx.context.node_id,
            tool_definition_id="internal:read_skill_resource",
            tool_name="read_skill_resource",
            implementation_id="agentmesh.skill_runtime.resources.read_skill_resource",
            implementation_version="1",
            side_effect="read",
            operation_identity=canonical_json_sha256(
                {
                    "run_id": ctx.context.run_id,
                    "plan_id": ctx.context.plan_id,
                    "node_id": ctx.context.node_id,
                    "call_id": call_id,
                    "skill_id": skill.id,
                    "raw_arguments_hash": raw_arguments_hash,
                }
            ),
        )
        invocation_key: str | None = None
        try:
            with admission.permit():
                if run is not None and run.planning_mode is AgentPlanningMode.DEEPSEARCH:
                    invocation_key = _reserve_deepsearch_resource_read(
                        repository,
                        context=ctx.context,
                        skill=skill,
                        tool_call_id=raw_call_id,
                    )
                claimed = repository.claim_runtime_tool_call(claim)
                if not claimed:
                    raise RuntimeToolCallConflict("tool_call_already_claimed")
        except BaseException:
            if invocation_key is not None:
                _settle_deepsearch_resource_read(
                    repository,
                    run_id=ctx.context.run_id,
                    invocation_key=invocation_key,
                    actual_usage=_DEEPSEARCH_RESOURCE_MAXIMA,
                )
            raise
        try:
            started_at = monotonic() if invocation_key is not None else None
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
            if run is not None and run.planning_mode is AgentPlanningMode.STANDARD:
                requested_paths = set(ctx.context.resource_references)
                requested_paths.update(references)
                if len(requested_paths) > _STANDARD_RESOURCE_PATH_LIMIT:
                    raise ValueError("Standard Skill node resource limit is 12 paths")

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
                manifest_membership_required = (
                    ctx.context.resource_manifest_frozen or _is_managed_wiki_import(skill)
                )
                if manifest_membership_required and relative not in approved_manifest:
                    raise PermissionError("Skill resource is outside the frozen node resource manifest")
                try:
                    data = _read_bounded_resource(resource)
                except OSError as error:
                    raise FileNotFoundError("Skill resource became unavailable") from error
                actual_hash = hashlib.sha256(data).hexdigest()
                if relative in approved_manifest and actual_hash != approved_manifest[relative]:
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
                ctx.context.resource_references = list(
                    dict.fromkeys([*ctx.context.resource_references, relative])
                )
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
            encoded_response = json.dumps(response, ensure_ascii=False, default=str)
        except BaseException as error:
            if invocation_key is not None:
                try:
                    _settle_deepsearch_resource_read(
                        repository,
                        run_id=ctx.context.run_id,
                        invocation_key=invocation_key,
                        actual_usage=_DEEPSEARCH_RESOURCE_MAXIMA,
                    )
                except BaseException as settlement_error:
                    repository.finish_runtime_tool_call(
                        RuntimeToolCallOutcomeV1(
                            call_id=call_id,
                            run_id=ctx.context.run_id,
                            outcome="abandoned",
                            error_code="resource_budget_settlement_failed",
                        )
                    )
                    settlement_error.add_note(f"Skill resource read failed before settlement: {error}")
                    raise settlement_error from error
            repository.finish_runtime_tool_call(
                RuntimeToolCallOutcomeV1(
                    call_id=call_id,
                    run_id=ctx.context.run_id,
                    outcome="abandoned",
                    error_code=type(error).__name__,
                )
            )
            raise

        if invocation_key is not None:
            assert started_at is not None
            _settle_deepsearch_resource_read(
                repository,
                run_id=ctx.context.run_id,
                invocation_key=invocation_key,
                actual_usage=DeepSearchBudgetUsageV1(
                    active_seconds=min(
                        max(monotonic() - started_at, 0),
                        _DEEPSEARCH_RESOURCE_MAXIMA.active_seconds,
                    ),
                    tool_calls=1,
                ),
            )
        repository.finish_runtime_tool_call(
            RuntimeToolCallOutcomeV1(
                call_id=call_id,
                run_id=ctx.context.run_id,
                outcome="settled",
                result_hash=hashlib.sha256(encoded_response.encode("utf-8")).hexdigest(),
            )
        )
        return encoded_response

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
