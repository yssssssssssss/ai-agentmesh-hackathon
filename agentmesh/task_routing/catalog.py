from __future__ import annotations

import hashlib
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError

from agentmesh.research_orchestration.v3.canonical import strict_json_v3_loads
from agentmesh.task_routing.compiler import canonical_sha256
from agentmesh.task_routing.contracts import (
    CatalogManifest,
    KnowledgeCatalogEntry,
    ScenarioCatalogEntry,
    SkillCatalogEntry,
    TaskCatalogEntry,
    TaskSkillMappingEntry,
)

_DATA_FILES = {
    "tasks.json",
    "scenarios.json",
    "task-skill-mapping.json",
    "skill-registry.json",
    "knowledge-registry.json",
}
_MAX_FILES = 32
_MAX_FILE_BYTES = 524_288
_MAX_AGGREGATE_BYTES = 2_097_152


class TaskCatalogLoadError(ValueError):
    pass


@dataclass(frozen=True)
class TaskCatalog:
    manifest: CatalogManifest
    tasks: tuple[TaskCatalogEntry, ...]
    scenarios: tuple[ScenarioCatalogEntry, ...]
    mappings: tuple[TaskSkillMappingEntry, ...]
    skills: tuple[SkillCatalogEntry, ...]
    knowledge: tuple[KnowledgeCatalogEntry, ...]
    _tasks_by_id: Mapping[str, TaskCatalogEntry]
    _scenarios_by_id: Mapping[str, ScenarioCatalogEntry]
    _mappings_by_scenario_id: Mapping[str, TaskSkillMappingEntry]
    _skills_by_id: Mapping[str, SkillCatalogEntry]
    _knowledge_by_id: Mapping[str, KnowledgeCatalogEntry]

    def get_task(self, task_id: str) -> TaskCatalogEntry | None:
        return self._tasks_by_id.get(task_id)

    def get_scenario(self, scenario_id: str) -> ScenarioCatalogEntry | None:
        return self._scenarios_by_id.get(scenario_id)

    def get_mapping(self, scenario_id: str) -> TaskSkillMappingEntry | None:
        return self._mappings_by_scenario_id.get(scenario_id)

    def get_skill(self, skill_id: str) -> SkillCatalogEntry | None:
        return self._skills_by_id.get(skill_id)

    def get_knowledge(self, knowledge_id: str) -> KnowledgeCatalogEntry | None:
        return self._knowledge_by_id.get(knowledge_id)

    def scenarios_for_task(self, task_id: str) -> tuple[ScenarioCatalogEntry, ...]:
        return tuple(scenario for scenario in self.scenarios if scenario.parent_task == task_id)


def _default_catalog_root() -> Path:
    root = files("agentmesh").joinpath("task_catalog", "user-research-v1")
    if not isinstance(root, Path):
        raise TaskCatalogLoadError("catalog_resources_not_filesystem_backed")
    return root


def _safe_relative_path(relative_path: str) -> PurePosixPath:
    path = PurePosixPath(relative_path)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise TaskCatalogLoadError(f"catalog_path_invalid:{relative_path}")
    if path.as_posix() != relative_path:
        raise TaskCatalogLoadError(f"catalog_path_invalid:{relative_path}")
    return path


def _preflight_inventory(root: Path) -> dict[str, int]:
    try:
        root_metadata = root.lstat()
    except FileNotFoundError:
        raise TaskCatalogLoadError("catalog_root_unavailable") from None
    if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode):
        raise TaskCatalogLoadError("catalog_root_invalid")
    inventory: dict[str, int] = {}
    aggregate_size = 0
    for path in root.rglob("*"):
        metadata = path.lstat()
        relative_path = path.relative_to(root).as_posix()
        if stat.S_ISLNK(metadata.st_mode):
            raise TaskCatalogLoadError(f"catalog_symlink_forbidden:{relative_path}")
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise TaskCatalogLoadError(f"catalog_entry_invalid:{relative_path}")
        if len(inventory) >= _MAX_FILES:
            raise TaskCatalogLoadError("catalog_file_limit_exceeded")
        if metadata.st_size > _MAX_FILE_BYTES:
            raise TaskCatalogLoadError(f"catalog_file_too_large:{relative_path}")
        aggregate_size += metadata.st_size
        if aggregate_size > _MAX_AGGREGATE_BYTES:
            raise TaskCatalogLoadError("catalog_aggregate_size_exceeded")
        inventory[relative_path] = metadata.st_size
    return inventory


def _read_bytes(root: Path, relative_path: str, inventory: Mapping[str, int]) -> bytes:
    _safe_relative_path(relative_path)
    expected_size = inventory.get(relative_path)
    if expected_size is None:
        raise TaskCatalogLoadError(f"catalog_file_unavailable:{relative_path}")
    path = root.joinpath(*PurePosixPath(relative_path).parts)
    try:
        content = path.read_bytes()
    except OSError as error:
        raise TaskCatalogLoadError(f"catalog_file_unavailable:{relative_path}") from error
    if len(content) != expected_size:
        raise TaskCatalogLoadError(f"catalog_file_size_changed:{relative_path}")
    return content


def _parse_json(content: bytes, name: str) -> Any:
    try:
        return strict_json_v3_loads(content)
    except (UnicodeError, ValueError) as error:
        raise TaskCatalogLoadError(f"catalog_file_invalid:{name}") from error


def _load_list[T: BaseModel](payload: Any, name: str, model: type[T]) -> tuple[T, ...]:
    try:
        return tuple(TypeAdapter(list[model]).validate_python(payload))
    except ValidationError as error:
        raise TaskCatalogLoadError(f"catalog_schema_invalid:{name}") from error


def _index[T](items: tuple[T, ...], *, label: str, key: Callable[[T], str]) -> Mapping[str, T]:
    result: dict[str, T] = {}
    for item in items:
        item_id = key(item)
        if not item_id or item_id in result:
            raise TaskCatalogLoadError(f"catalog_duplicate_id:{label}:{item_id}")
        result[item_id] = item
    return MappingProxyType(result)


def _manifest_body(manifest: CatalogManifest) -> dict[str, Any]:
    return manifest.model_dump(mode="json", exclude={"catalog_hash"})


def _validate_scenario_dependencies(scenarios: Mapping[str, ScenarioCatalogEntry]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(scenario_id: str) -> None:
        if scenario_id in visiting:
            raise TaskCatalogLoadError(f"catalog_scenario_dependency_cycle:{scenario_id}")
        if scenario_id in visited:
            return
        visiting.add(scenario_id)
        for dependency in scenarios[scenario_id].dependencies:
            if dependency == scenario_id:
                raise TaskCatalogLoadError(f"catalog_scenario_self_dependency:{scenario_id}")
            if dependency not in scenarios:
                raise TaskCatalogLoadError(f"catalog_scenario_dependency_missing:{scenario_id}:{dependency}")
            visit(dependency)
        visiting.remove(scenario_id)
        visited.add(scenario_id)

    for scenario_id in sorted(scenarios):
        visit(scenario_id)


def load_task_catalog(root: Path | None = None) -> TaskCatalog:
    catalog_root = (root or _default_catalog_root()).resolve()
    inventory = _preflight_inventory(catalog_root)
    manifest_payload = _parse_json(_read_bytes(catalog_root, "catalog.json", inventory), "catalog.json")
    try:
        manifest = CatalogManifest.model_validate(manifest_payload)
    except ValidationError as error:
        raise TaskCatalogLoadError("catalog_manifest_invalid") from error
    if canonical_sha256(_manifest_body(manifest)) != manifest.catalog_hash:
        raise TaskCatalogLoadError("catalog_manifest_hash_mismatch")
    if not _DATA_FILES.issubset(manifest.files):
        raise TaskCatalogLoadError("catalog_manifest_files_missing")
    declared_files = {"catalog.json", *manifest.files}
    if set(inventory) != declared_files:
        raise TaskCatalogLoadError("catalog_undeclared_files")
    payloads: dict[str, Any] = {}
    for relative_path, expected_hash in manifest.files.items():
        content = _read_bytes(catalog_root, relative_path, inventory)
        if hashlib.sha256(content).hexdigest() != expected_hash:
            raise TaskCatalogLoadError(f"catalog_file_hash_mismatch:{relative_path}")
        payloads[relative_path] = _parse_json(content, relative_path)
    if _preflight_inventory(catalog_root) != inventory:
        raise TaskCatalogLoadError("catalog_inventory_changed")

    tasks = _load_list(payloads["tasks.json"], "tasks.json", TaskCatalogEntry)
    scenarios = _load_list(payloads["scenarios.json"], "scenarios.json", ScenarioCatalogEntry)
    mappings = _load_list(payloads["task-skill-mapping.json"], "task-skill-mapping.json", TaskSkillMappingEntry)
    skills = _load_list(payloads["skill-registry.json"], "skill-registry.json", SkillCatalogEntry)
    knowledge = _load_list(payloads["knowledge-registry.json"], "knowledge-registry.json", KnowledgeCatalogEntry)

    expected_counts = {
        "knowledge": len(knowledge),
        "mappings": len(mappings),
        "scenarios": len(scenarios),
        "skills": len(skills),
        "tasks": len(tasks),
    }
    if manifest.counts != expected_counts:
        raise TaskCatalogLoadError("catalog_counts_mismatch")

    task_index = _index(tasks, label="tasks", key=lambda item: item.id)
    scenario_index = _index(scenarios, label="scenarios", key=lambda item: item.id)
    mapping_index = _index(mappings, label="mappings", key=lambda item: item.scenario_id)
    skill_index = _index(skills, label="skills", key=lambda item: item.id)
    knowledge_index = _index(knowledge, label="knowledge", key=lambda item: item.id)
    if set(mapping_index) != set(scenario_index):
        raise TaskCatalogLoadError("catalog_mapping_coverage_mismatch")
    _validate_scenario_dependencies(scenario_index)
    for scenario in scenarios:
        if scenario.parent_task not in task_index:
            raise TaskCatalogLoadError(f"catalog_parent_task_missing:{scenario.id}")
        for reference in [*scenario.default_skills, *scenario.optional_skills]:
            if reference.status.value == "planned":
                continue
            skill = skill_index.get(reference.id)
            if skill is None:
                raise TaskCatalogLoadError(f"catalog_scenario_skill_missing:{reference.id}")
            if skill.status != reference.status:
                raise TaskCatalogLoadError(f"catalog_scenario_skill_status_mismatch:{reference.id}")
    for mapping in mappings:
        scenario = scenario_index.get(mapping.scenario_id)
        if mapping.task_id not in task_index:
            raise TaskCatalogLoadError(f"catalog_mapping_task_missing:{mapping.scenario_id}")
        if scenario is None:
            raise TaskCatalogLoadError(f"catalog_mapping_scenario_missing:{mapping.scenario_id}")
        if mapping.task_id != scenario.parent_task:
            raise TaskCatalogLoadError(f"catalog_mapping_parent_mismatch:{mapping.scenario_id}")
        expected_default = tuple(
            reference.id for reference in scenario.default_skills if reference.status.value != "planned"
        )
        expected_optional = tuple(
            reference.id for reference in scenario.optional_skills if reference.status.value != "planned"
        )
        expected_planned = tuple(
            reference.id
            for reference in [*scenario.default_skills, *scenario.optional_skills]
            if reference.status.value == "planned"
        )
        if (
            mapping.default_skill_ids != expected_default
            or mapping.optional_skill_ids != expected_optional
            or mapping.planned_skill_ids != expected_planned
        ):
            raise TaskCatalogLoadError(f"catalog_mapping_skill_mismatch:{mapping.scenario_id}")
        mapped_knowledge = {
            *mapping.required_knowledge_ids,
            *mapping.optional_knowledge_ids,
            *mapping.required_knowledge_descriptors,
            *mapping.optional_knowledge_descriptors,
        }
        if mapped_knowledge != set(scenario.knowledge_requirements):
            raise TaskCatalogLoadError(f"catalog_mapping_knowledge_mismatch:{mapping.scenario_id}")
        for skill_id in [*mapping.default_skill_ids, *mapping.optional_skill_ids]:
            if skill_id not in skill_index:
                raise TaskCatalogLoadError(f"catalog_mapping_skill_missing:{skill_id}")
        for knowledge_id in [*mapping.required_knowledge_ids, *mapping.optional_knowledge_ids]:
            if knowledge_id not in knowledge_index:
                raise TaskCatalogLoadError(f"catalog_mapping_knowledge_missing:{knowledge_id}")

    return TaskCatalog(
        manifest=manifest,
        tasks=tasks,
        scenarios=scenarios,
        mappings=mappings,
        skills=skills,
        knowledge=knowledge,
        _tasks_by_id=task_index,
        _scenarios_by_id=scenario_index,
        _mappings_by_scenario_id=mapping_index,
        _skills_by_id=skill_index,
        _knowledge_by_id=knowledge_index,
    )


def load_default_task_catalog() -> TaskCatalog:
    return load_task_catalog()
