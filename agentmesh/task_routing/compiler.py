from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from yaml.events import AliasEvent
from yaml.nodes import MappingNode, ScalarNode

from agentmesh.canonical_json import canonical_json_sha256, strict_json_loads
from agentmesh.task_routing.contracts import (
    CatalogManifest,
    CatalogManifestV2,
    CatalogSkillReference,
    CatalogStatus,
    CompletionCheckResult,
    KnowledgeCatalogEntry,
    ScenarioCatalogEntry,
    ScenarioCatalogEntryV2,
    ScenarioOutputV2,
    SkillCatalogEntry,
    TaskCatalogEntry,
    TaskRoutingResult,
    TaskSkillMappingEntry,
)

_CATALOG_V1 = "user-research-v1"
_CATALOG_V1_HASH = "480d88f8f9d11c0f24bcff7ecb6f2a333d5852391bb80ee2de9217b81b6b9629"
_CATALOG_V2 = "user-research-v2"
_SUPPORTED_CATALOG_VERSIONS = frozenset({_CATALOG_V1, _CATALOG_V2})
_MANIFEST_FILE = "catalog.json"
_TASKS_FILE = "tasks.json"
_SCENARIOS_FILE = "scenarios.json"
_MAPPING_FILE = "task-skill-mapping.json"
_SKILLS_FILE = "skill-registry.json"
_KNOWLEDGE_FILE = "knowledge-registry.json"
_MAPPING_SOURCE = "01-task-任务/task-skill-knowledge-mapping.md"
_OUTPUT_MAPPING_SOURCE_KEY = "scenario-output-mapping.json"
_REGISTRY_ROOT = "05-registry-索引"
_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_OUTPUT_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_KNOWLEDGE_DESCRIPTORS = frozenset(
    {
        "current-project-materials",
        "当前项目资料",
        "场域知识包：基础与洞察知识",
        "场域知识包：基础知识",
        "场域知识包：基础知识（按需）",
        "场域知识包：指标口径",
        "场域知识包：洞察与经验知识（按需）",
        "场域知识包：洞察知识（按需）",
        "场域知识包：用户旅程（按需）",
        "场域知识包：约束条件",
        "场域知识包：经验知识",
        "场域知识包：经验知识（按需）",
        "用户研究知识：VOC/文本分析/质性编码",
        "用户研究知识：优先级框架",
        "用户研究知识：体验度量/漏斗/功能采纳",
        "用户研究知识：启发式评估/可用性",
        "用户研究知识：定性归纳、文本分析",
        "用户研究知识：机会点研究",
        "用户研究知识：用户画像/分层/分群",
        "用户研究知识：用户需求/JTBD",
        "用户研究知识：转化漏斗/行为数据/体验度量",
        "设计策略方法：优先路线",
        "设计策略方法：优先路线/评审验证",
        "设计策略方法：用户分析",
        "设计策略方法：策略地图",
        "设计策略方法：策略推导",
        "设计策略方法：问题定义/痛点诊断",
    }
)
_RUNTIME_SKILL_NAMES = {
    "ur-skill-build-experience-metrics": "build-experience-metrics",
    "ur-skill-competitive-analysis": "competitive-analysis",
    "ur-skill-generate-interview-guide": "generate-interview-guide",
    "ur-skill-generate-research-plan": "generate-research-plan",
    "ur-skill-generate-survey": "generate-survey",
    "ur-skill-generate-usability-test": "generate-usability-test",
    "ur-skill-issue-prioritization": "issue-prioritization",
    "ur-skill-jobs-to-be-done": "jobs-to-be-done",
}


class TaskCatalogBuildError(ValueError):
    pass


class _SourceTaskRegistryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    level: str
    parent_task: str = ""
    description: str
    status: CatalogStatus
    owner: str
    updated_at: date
    source_path: str
    trigger_keywords: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    workflow_ids: list[str] = Field(default_factory=list)
    recommended_skills: list[str] = Field(default_factory=list)
    required_knowledge_types: list[str] = Field(default_factory=list)


class _SourceRegistryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    type: str
    description: str = ""
    business_domain: str
    status: CatalogStatus
    source_path: str
    capability_domain: list[str] = Field(default_factory=list)
    task_types: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    related_items: list[str] = Field(default_factory=list)


class _SourceScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    parent_task: str
    task_type: str
    definition: str
    trigger_examples: list[str] = Field(default_factory=list)
    required_inputs: list[str] = Field(default_factory=list)
    optional_inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(min_length=1)
    completion_criteria: list[str] = Field(min_length=1)
    default_skills: list[CatalogSkillReference] = Field(default_factory=list)
    optional_skills: list[CatalogSkillReference] = Field(default_factory=list)
    knowledge_requirements: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    fallback: list[str] = Field(default_factory=list)
    human_confirmation: list[str] = Field(default_factory=list)
    status: CatalogStatus
    owner: str
    updated_at: date


class _ScenarioOutputMappingEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    outputs: list[ScenarioOutputV2] = Field(min_length=1)


class _ScenarioOutputMappingDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["task-catalog-v2-output-mapping-v1"]
    catalog_version: Literal["user-research-v2"]
    source_catalog_version: Literal["user-research-v1"]
    source_catalog_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenarios: list[_ScenarioOutputMappingEntry] = Field(min_length=1)


@dataclass(frozen=True)
class CompiledTaskCatalog:
    files: dict[str, Any]
    manifest: CatalogManifest | CatalogManifestV2


class _StrictYamlLoader(yaml.SafeLoader):
    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(AliasEvent):
            raise ValueError("yaml_alias_not_allowed")
        return super().compose_node(parent, index)

    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key_node, value_node in node.value:
            if not isinstance(key_node, ScalarNode) or key_node.tag != "tag:yaml.org,2002:str":
                raise ValueError("yaml_mapping_key_invalid")
            key = self.construct_object(key_node, deep=deep)
            if key == "<<" or key_node.tag == "tag:yaml.org,2002:merge":
                raise ValueError("yaml_merge_not_allowed")
            if key in result:
                raise ValueError(f"yaml_duplicate_key:{key}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _strict_yaml_load(value: str) -> Any:
    return yaml.load(value, Loader=_StrictYamlLoader)


def canonical_sha256(payload: Any) -> str:
    return canonical_json_sha256(payload)


def json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_source_path(source_root: Path, relative_path: str) -> Path:
    path = PurePosixPath(relative_path)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise TaskCatalogBuildError(f"source_path_invalid:{relative_path}")
    if path.as_posix() != relative_path:
        raise TaskCatalogBuildError(f"source_path_invalid:{relative_path}")
    root = source_root.resolve()
    candidate = root
    for part in path.parts:
        candidate = candidate / part
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            raise TaskCatalogBuildError(f"source_path_missing:{relative_path}") from None
        if stat.S_ISLNK(metadata.st_mode):
            raise TaskCatalogBuildError(f"source_path_symlink:{relative_path}")
    if not candidate.is_file():
        raise TaskCatalogBuildError(f"source_path_missing:{relative_path}")
    return candidate


def _safe_regular_file(path: Path, *, label: str) -> Path:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise TaskCatalogBuildError(f"source_path_missing:{label}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise TaskCatalogBuildError(f"source_path_invalid:{label}")
    return path.resolve()


def _load_yaml_list[T: BaseModel](path: Path, adapter: TypeAdapter[list[T]]) -> list[T]:
    try:
        payload = _strict_yaml_load(path.read_text(encoding="utf-8"))
        return adapter.validate_python(payload)
    except OSError as error:
        raise TaskCatalogBuildError(f"source_unavailable:{path}") from error
    except (ValueError, yaml.YAMLError, ValidationError) as error:
        raise TaskCatalogBuildError(f"source_invalid:{path}") from error


def _load_output_mapping(path: Path) -> _ScenarioOutputMappingDocument:
    try:
        payload = strict_json_loads(path.read_bytes())
        return _ScenarioOutputMappingDocument.model_validate(payload)
    except OSError as error:
        raise TaskCatalogBuildError(f"source_unavailable:{path}") from error
    except (UnicodeError, ValueError, ValidationError) as error:
        raise TaskCatalogBuildError(f"source_invalid:{path}") from error


def _frontmatter(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise TaskCatalogBuildError(f"source_unavailable:{path}") from error
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise TaskCatalogBuildError(f"frontmatter_missing:{path}")
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration:
        raise TaskCatalogBuildError(f"frontmatter_unterminated:{path}") from None
    try:
        payload = _strict_yaml_load("\n".join(lines[1:end]))
    except (ValueError, yaml.YAMLError) as error:
        raise TaskCatalogBuildError(f"frontmatter_invalid:{path}") from error
    if not isinstance(payload, dict):
        raise TaskCatalogBuildError(f"frontmatter_not_object:{path}")
    return payload


def _unique_by_id[T: BaseModel](items: list[T], *, source_name: str) -> dict[str, T]:
    result: dict[str, T] = {}
    for item in items:
        item_id = str(item.id)
        if not _ID_PATTERN.fullmatch(item_id):
            raise TaskCatalogBuildError(f"id_invalid:{source_name}:{item_id}")
        if item_id in result:
            raise TaskCatalogBuildError(f"duplicate_id:{source_name}:{item_id}")
        result[item_id] = item
    return result


def _require_unique(values: list[str] | tuple[str, ...], *, label: str) -> None:
    if len(values) != len(set(values)):
        raise TaskCatalogBuildError(f"duplicate_reference:{label}")


def _validate_v2_output_mappings(
    document: _ScenarioOutputMappingDocument,
    scenarios: dict[str, _SourceScenario],
) -> dict[str, tuple[ScenarioOutputV2, ...]]:
    if document.source_catalog_hash != _CATALOG_V1_HASH:
        raise TaskCatalogBuildError("scenario_output_mapping_source_catalog_mismatch")
    mappings: dict[str, tuple[ScenarioOutputV2, ...]] = {}
    for entry in document.scenarios:
        if entry.scenario_id in mappings:
            raise TaskCatalogBuildError(f"scenario_output_mapping_duplicate:{entry.scenario_id}")
        source = scenarios.get(entry.scenario_id)
        if source is None:
            raise TaskCatalogBuildError(f"scenario_output_mapping_unknown:{entry.scenario_id}")
        output_ids = [output.id for output in entry.outputs]
        if len(output_ids) != len(set(output_ids)):
            raise TaskCatalogBuildError(f"scenario_output_id_duplicate:{entry.scenario_id}")
        labels = [output.label for output in entry.outputs]
        if labels != source.outputs:
            raise TaskCatalogBuildError(f"scenario_output_labels_mismatch:{entry.scenario_id}")
        for output in entry.outputs:
            kinds = output.compatible_output_kinds
            if len(kinds) != len(set(kinds)):
                raise TaskCatalogBuildError(
                    f"scenario_output_kind_duplicate:{entry.scenario_id}:{output.id}"
                )
            if any(not _OUTPUT_KIND_PATTERN.fullmatch(kind) for kind in kinds):
                raise TaskCatalogBuildError(
                    f"scenario_output_kind_invalid:{entry.scenario_id}:{output.id}"
                )
        mappings[entry.scenario_id] = tuple(entry.outputs)
    if set(mappings) != set(scenarios):
        missing = ",".join(sorted(set(scenarios) - set(mappings)))
        raise TaskCatalogBuildError(f"scenario_output_mappings_incomplete:{missing}")
    return mappings


def _validate_dependency_graph(scenarios: dict[str, _SourceScenario]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(scenario_id: str) -> None:
        if scenario_id in visiting:
            raise TaskCatalogBuildError(f"scenario_dependency_cycle:{scenario_id}")
        if scenario_id in visited:
            return
        visiting.add(scenario_id)
        for dependency in scenarios[scenario_id].dependencies:
            if dependency == scenario_id:
                raise TaskCatalogBuildError(f"scenario_self_dependency:{scenario_id}")
            if dependency not in scenarios:
                raise TaskCatalogBuildError(f"scenario_dependency_missing:{scenario_id}:{dependency}")
            visit(dependency)
        visiting.remove(scenario_id)
        visited.add(scenario_id)

    for scenario_id in sorted(scenarios):
        visit(scenario_id)


def _parse_list_cell(value: str) -> list[str]:
    cleaned = value.replace("`", "").strip()
    if not cleaned or cleaned in {"-", "无"}:
        return []
    return [part.strip() for part in re.split(r"[,，]", cleaned) if part.strip()]


def _parse_mapping_rows(path: Path) -> list[tuple[str, list[str], list[str], list[str], list[str]]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise TaskCatalogBuildError(f"source_unavailable:{path}") from error
    in_table = False
    rows: list[tuple[str, list[str], list[str], list[str], list[str]]] = []
    for line in lines:
        if line.strip() == "## 15 个 Scenario 映射":
            in_table = True
            continue
        if in_table and line.startswith("## "):
            break
        if not in_table or not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 5 or cells[0] == "Scenario" or set(cells[0]) <= {"-", ":"}:
            continue
        rows.append(
            (
                cells[0],
                _parse_list_cell(cells[1]),
                _parse_list_cell(cells[2]),
                _parse_list_cell(cells[3]),
                _parse_list_cell(cells[4]),
            )
        )
    if not rows:
        raise TaskCatalogBuildError("scenario_mapping_table_missing")
    return rows


def _is_descriptor(value: str) -> bool:
    return value in _KNOWLEDGE_DESCRIPTORS


def _partition_knowledge(values: list[str], known_ids: set[str]) -> tuple[list[str], list[str]]:
    identifiers: list[str] = []
    descriptors: list[str] = []
    for value in values:
        if value in known_ids:
            identifiers.append(value)
        elif _is_descriptor(value):
            descriptors.append(value)
        else:
            raise TaskCatalogBuildError(f"knowledge_reference_missing:{value}")
    return identifiers, descriptors


def _validate_reference_status(reference: CatalogSkillReference, skills: dict[str, _SourceRegistryItem]) -> None:
    if reference.status == CatalogStatus.PLANNED:
        return
    skill = skills.get(reference.id)
    if skill is None:
        raise TaskCatalogBuildError(f"skill_reference_missing:{reference.id}")
    if skill.status != reference.status:
        raise TaskCatalogBuildError(f"skill_status_mismatch:{reference.id}")


def _serialized_list(items: list[BaseModel]) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in sorted(items, key=lambda item: str(getattr(item, "id", "")))]


def _schema(document: dict[str, Any], name: str, *, catalog_version: str) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://agentmesh.local/schemas/task-catalog/{catalog_version}/{name}",
        **document,
    }


def _schema_payloads(
    *,
    catalog_version: str,
    scenario_model: type[ScenarioCatalogEntry] | type[ScenarioCatalogEntryV2],
) -> dict[str, dict[str, Any]]:
    return {
        "schemas/task.schema.json": _schema(
            TypeAdapter(list[TaskCatalogEntry]).json_schema(),
            "task.schema.json",
            catalog_version=catalog_version,
        ),
        "schemas/scenario.schema.json": _schema(
            TypeAdapter(list[scenario_model]).json_schema(),
            "scenario.schema.json",
            catalog_version=catalog_version,
        ),
        "schemas/task-skill-mapping.schema.json": _schema(
            TypeAdapter(list[TaskSkillMappingEntry]).json_schema(),
            "task-skill-mapping.schema.json",
            catalog_version=catalog_version,
        ),
        "schemas/skill-registry.schema.json": _schema(
            TypeAdapter(list[SkillCatalogEntry]).json_schema(),
            "skill-registry.schema.json",
            catalog_version=catalog_version,
        ),
        "schemas/knowledge-registry.schema.json": _schema(
            TypeAdapter(list[KnowledgeCatalogEntry]).json_schema(),
            "knowledge-registry.schema.json",
            catalog_version=catalog_version,
        ),
        "schemas/routing-result.schema.json": _schema(
            TaskRoutingResult.model_json_schema(),
            "routing-result.schema.json",
            catalog_version=catalog_version,
        ),
        "schemas/completion-check.schema.json": _schema(
            CompletionCheckResult.model_json_schema(),
            "completion-check.schema.json",
            catalog_version=catalog_version,
        ),
    }


def compile_task_catalog(
    source_root: Path,
    *,
    catalog_version: str = _CATALOG_V1,
    scenario_output_mapping_path: Path | None = None,
) -> CompiledTaskCatalog:
    if catalog_version not in _SUPPORTED_CATALOG_VERSIONS:
        raise TaskCatalogBuildError(f"catalog_version_unsupported:{catalog_version}")
    if catalog_version == _CATALOG_V1 and scenario_output_mapping_path is not None:
        raise TaskCatalogBuildError("catalog_v1_output_mapping_forbidden")
    if catalog_version == _CATALOG_V2 and scenario_output_mapping_path is None:
        raise TaskCatalogBuildError("catalog_v2_output_mapping_required")
    source_root = source_root.resolve()
    task_registry_path = _safe_source_path(source_root, f"{_REGISTRY_ROOT}/task-registry.yaml")
    skill_registry_path = _safe_source_path(source_root, f"{_REGISTRY_ROOT}/skill-registry.yaml")
    knowledge_registry_path = _safe_source_path(source_root, f"{_REGISTRY_ROOT}/knowledge-registry.yaml")
    mapping_path = _safe_source_path(source_root, _MAPPING_SOURCE)

    task_registry = _load_yaml_list(task_registry_path, TypeAdapter(list[_SourceTaskRegistryItem]))
    skill_registry = _load_yaml_list(skill_registry_path, TypeAdapter(list[_SourceRegistryItem]))
    knowledge_registry = _load_yaml_list(knowledge_registry_path, TypeAdapter(list[_SourceRegistryItem]))
    task_registry_by_id = _unique_by_id(task_registry, source_name="task-registry")
    skills_by_id = _unique_by_id(skill_registry, source_name="skill-registry")
    knowledge_by_id = _unique_by_id(knowledge_registry, source_name="knowledge-registry")
    all_ids = [*task_registry_by_id, *skills_by_id, *knowledge_by_id]
    if len(all_ids) != len(set(all_ids)):
        raise TaskCatalogBuildError("global_duplicate_id")
    if any(item.level not in {"task", "scenario", "legacy-task"} for item in task_registry):
        raise TaskCatalogBuildError("task_level_invalid")
    if any(item.type != "skill" for item in skill_registry):
        raise TaskCatalogBuildError("skill_type_invalid")
    allowed_knowledge_types = {"method", "mechanism", "template", "domain-knowledge"}
    if any(item.type not in allowed_knowledge_types for item in knowledge_registry):
        raise TaskCatalogBuildError("knowledge_type_invalid")

    task_sources = [item for item in task_registry if item.level == "task"]
    scenario_sources = [item for item in task_registry if item.level == "scenario"]
    if not task_sources or not scenario_sources:
        raise TaskCatalogBuildError("task_or_scenario_catalog_empty")
    task_ids = {item.id for item in task_sources}

    tasks: list[TaskCatalogEntry] = []
    for item in task_sources:
        source_path = _safe_source_path(source_root, item.source_path)
        tasks.append(
            TaskCatalogEntry(
                id=item.id,
                title=item.title,
                description=item.description,
                status=item.status,
                owner=item.owner,
                updated_at=item.updated_at,
                trigger_keywords=item.trigger_keywords,
                outputs=item.outputs,
                workflow_ids=item.workflow_ids,
                recommended_skill_ids=item.recommended_skills,
                required_knowledge_types=item.required_knowledge_types,
                source_path=item.source_path,
                source_hash=file_sha256(source_path),
            )
        )

    scenarios_v1: list[ScenarioCatalogEntry] = []
    scenario_sources_by_title: dict[str, _SourceTaskRegistryItem] = {}
    scenario_frontmatter: dict[str, _SourceScenario] = {}
    for item in scenario_sources:
        if item.parent_task not in task_ids:
            raise TaskCatalogBuildError(f"parent_task_missing:{item.id}:{item.parent_task}")
        if item.title in scenario_sources_by_title:
            raise TaskCatalogBuildError(f"duplicate_scenario_title:{item.title}")
        source_path = _safe_source_path(source_root, item.source_path)
        try:
            source = _SourceScenario.model_validate(_frontmatter(source_path))
        except ValidationError as error:
            raise TaskCatalogBuildError(f"scenario_frontmatter_invalid:{item.id}") from error
        if source.task_type != "scenario" or source.id != item.id or source.title != item.title:
            raise TaskCatalogBuildError(f"scenario_registry_mismatch:{item.id}")
        if source.parent_task != item.parent_task or source.status != item.status:
            raise TaskCatalogBuildError(f"scenario_registry_mismatch:{item.id}")
        if (
            source.definition != item.description
            or source.trigger_examples != item.trigger_keywords
            or source.outputs != item.outputs
            or source.owner != item.owner
            or source.updated_at != item.updated_at
            or [reference.id for reference in [*source.default_skills, *source.optional_skills]]
            != item.recommended_skills
            or source.knowledge_requirements != item.required_knowledge_types
        ):
            raise TaskCatalogBuildError(f"scenario_registry_mismatch:{item.id}")
        if not source.default_skills:
            raise TaskCatalogBuildError(f"scenario_default_skill_missing:{item.id}")
        for label, values in {
            "required_inputs": source.required_inputs,
            "optional_inputs": source.optional_inputs,
            "outputs": source.outputs,
            "completion_criteria": source.completion_criteria,
            "knowledge_requirements": source.knowledge_requirements,
            "dependencies": source.dependencies,
            "fallback": source.fallback,
            "human_confirmation": source.human_confirmation,
        }.items():
            _require_unique(values, label=f"{item.id}:{label}")
        skill_references = [*source.default_skills, *source.optional_skills]
        _require_unique([reference.id for reference in skill_references], label=f"{item.id}:skills")
        for reference in skill_references:
            _validate_reference_status(reference, skills_by_id)
        scenarios_v1.append(
            ScenarioCatalogEntry(
                **source.model_dump(exclude={"task_type"}),
                source_path=item.source_path,
                source_hash=file_sha256(source_path),
            )
        )
        scenario_sources_by_title[item.title] = item
        scenario_frontmatter[item.id] = source
    _validate_dependency_graph(scenario_frontmatter)

    output_mapping_path: Path | None = None
    if catalog_version == _CATALOG_V2:
        assert scenario_output_mapping_path is not None
        output_mapping_path = _safe_regular_file(
            scenario_output_mapping_path,
            label=_OUTPUT_MAPPING_SOURCE_KEY,
        )
        output_mappings = _validate_v2_output_mappings(
            _load_output_mapping(output_mapping_path),
            scenario_frontmatter,
        )
        scenarios: list[ScenarioCatalogEntry | ScenarioCatalogEntryV2] = [
            ScenarioCatalogEntryV2(
                **scenario.model_dump(exclude={"outputs"}),
                outputs=output_mappings[scenario.id],
            )
            for scenario in scenarios_v1
        ]
    else:
        scenarios = list(scenarios_v1)

    skills: list[SkillCatalogEntry] = []
    for item in skill_registry:
        source_path = _safe_source_path(source_root, item.source_path)
        skills.append(
            SkillCatalogEntry(
                **item.model_dump(exclude={"type", "source_path"}),
                runtime_skill_name=_RUNTIME_SKILL_NAMES.get(item.id),
                source_path=item.source_path,
                source_hash=file_sha256(source_path),
            )
        )

    knowledge: list[KnowledgeCatalogEntry] = []
    for item in knowledge_registry:
        source_path = _safe_source_path(source_root, item.source_path)
        knowledge.append(
            KnowledgeCatalogEntry(
                **item.model_dump(exclude={"type", "source_path"}),
                item_type=item.type,
                source_path=item.source_path,
                source_hash=file_sha256(source_path),
            )
        )

    mappings: list[TaskSkillMappingEntry] = []
    seen_scenarios: set[str] = set()
    for title, default_skills, optional_skills, required_knowledge, optional_knowledge in _parse_mapping_rows(
        mapping_path
    ):
        item = scenario_sources_by_title.get(title)
        if item is None:
            raise TaskCatalogBuildError(f"mapping_scenario_missing:{title}")
        source = scenario_frontmatter[item.id]
        if item.id in seen_scenarios:
            raise TaskCatalogBuildError(f"mapping_scenario_duplicate:{item.id}")
        seen_scenarios.add(item.id)
        expected_default = [reference.id for reference in source.default_skills]
        expected_optional = [reference.id for reference in source.optional_skills]
        if default_skills != expected_default or optional_skills != expected_optional:
            raise TaskCatalogBuildError(f"mapping_skill_mismatch:{item.id}")
        combined_knowledge = [*required_knowledge, *optional_knowledge]
        if combined_knowledge != source.knowledge_requirements:
            raise TaskCatalogBuildError(f"mapping_knowledge_mismatch:{item.id}")
        required_ids, required_descriptors = _partition_knowledge(required_knowledge, set(knowledge_by_id))
        optional_ids, optional_descriptors = _partition_knowledge(optional_knowledge, set(knowledge_by_id))
        planned_skill_ids = [
            reference.id
            for reference in [*source.default_skills, *source.optional_skills]
            if reference.status == CatalogStatus.PLANNED
        ]
        executable_default = [skill_id for skill_id in default_skills if skill_id not in planned_skill_ids]
        executable_optional = [skill_id for skill_id in optional_skills if skill_id not in planned_skill_ids]
        mappings.append(
            TaskSkillMappingEntry(
                scenario_id=item.id,
                task_id=item.parent_task,
                default_skill_ids=executable_default,
                optional_skill_ids=executable_optional,
                planned_skill_ids=planned_skill_ids,
                required_knowledge_ids=required_ids,
                optional_knowledge_ids=optional_ids,
                required_knowledge_descriptors=required_descriptors,
                optional_knowledge_descriptors=optional_descriptors,
                source_path=_MAPPING_SOURCE,
                source_hash=file_sha256(mapping_path),
            )
        )
    expected_scenario_ids = {item.id for item in scenario_sources}
    if seen_scenarios != expected_scenario_ids:
        missing = ",".join(sorted(expected_scenario_ids - seen_scenarios))
        raise TaskCatalogBuildError(f"mapping_scenarios_incomplete:{missing}")

    data_files: dict[str, Any] = {
        _TASKS_FILE: _serialized_list(tasks),
        _SCENARIOS_FILE: _serialized_list(scenarios),
        _MAPPING_FILE: [
            item.model_dump(mode="json") for item in sorted(mappings, key=lambda mapping: mapping.scenario_id)
        ],
        _SKILLS_FILE: _serialized_list(skills),
        _KNOWLEDGE_FILE: _serialized_list(knowledge),
        **_schema_payloads(
            catalog_version=catalog_version,
            scenario_model=(ScenarioCatalogEntryV2 if catalog_version == _CATALOG_V2 else ScenarioCatalogEntry),
        ),
    }
    file_hashes = {
        name: hashlib.sha256(json_bytes(payload)).hexdigest() for name, payload in sorted(data_files.items())
    }
    registry_hashes = {
        f"{_REGISTRY_ROOT}/knowledge-registry.yaml": file_sha256(knowledge_registry_path),
        f"{_REGISTRY_ROOT}/skill-registry.yaml": file_sha256(skill_registry_path),
        f"{_REGISTRY_ROOT}/task-registry.yaml": file_sha256(task_registry_path),
        _MAPPING_SOURCE: file_sha256(mapping_path),
    }
    if output_mapping_path is not None:
        registry_hashes[_OUTPUT_MAPPING_SOURCE_KEY] = file_sha256(output_mapping_path)
    source_updated_at = max(item.updated_at for item in task_registry)
    counts = {
        "knowledge": len(knowledge),
        "mappings": len(mappings),
        "scenarios": len(scenarios),
        "skills": len(skills),
        "tasks": len(tasks),
    }
    manifest_body = {
        "schema_version": (
            "task-catalog-manifest-v2" if catalog_version == _CATALOG_V2 else "task-catalog-manifest-v1"
        ),
        "catalog_version": catalog_version,
        "hash_algorithm": "sha256-bytes+agentmesh-canonical-json-v3",
        "source_updated_at": source_updated_at.isoformat(),
        "source_registry_hashes": registry_hashes,
        "files": file_hashes,
        "counts": counts,
    }
    manifest_type = CatalogManifestV2 if catalog_version == _CATALOG_V2 else CatalogManifest
    manifest = manifest_type(**manifest_body, catalog_hash=canonical_sha256(manifest_body))
    return CompiledTaskCatalog(files=data_files, manifest=manifest)


def catalog_bytes(compiled: CompiledTaskCatalog) -> dict[str, bytes]:
    return {
        **{relative_path: json_bytes(payload) for relative_path, payload in compiled.files.items()},
        _MANIFEST_FILE: json_bytes(compiled.manifest.model_dump(mode="json")),
    }


def catalog_tree_mismatches(output_root: Path, expected: dict[str, bytes]) -> list[str]:
    if not output_root.exists():
        return sorted(expected)
    metadata = output_root.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise TaskCatalogBuildError("catalog_output_root_invalid")
    actual_paths: set[str] = set()
    for path in output_root.rglob("*"):
        item_metadata = path.lstat()
        relative_path = path.relative_to(output_root).as_posix()
        if stat.S_ISLNK(item_metadata.st_mode):
            raise TaskCatalogBuildError(f"catalog_output_symlink_forbidden:{relative_path}")
        if stat.S_ISDIR(item_metadata.st_mode):
            continue
        if not stat.S_ISREG(item_metadata.st_mode):
            raise TaskCatalogBuildError(f"catalog_output_entry_invalid:{relative_path}")
        actual_paths.add(relative_path)
    mismatches = sorted(set(expected) ^ actual_paths)
    for relative_path, content in sorted(expected.items()):
        path = output_root / relative_path
        if not path.is_file() or path.read_bytes() != content:
            mismatches.append(relative_path)
    return list(dict.fromkeys(mismatches))


def _write_staged_catalog(stage_root: Path, expected: dict[str, bytes]) -> None:
    for relative_path, content in sorted(expected.items()):
        path = stage_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    for directory in sorted(
        {stage_root, *(path.parent for path in stage_root.rglob("*") if path.is_file())},
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def write_task_catalog(compiled: CompiledTaskCatalog, output_root: Path) -> None:
    if output_root.name != compiled.manifest.catalog_version:
        raise TaskCatalogBuildError(
            f"catalog_output_version_mismatch:{compiled.manifest.catalog_version}:{output_root.name}"
        )
    expected = catalog_bytes(compiled)
    if output_root.exists():
        if not catalog_tree_mismatches(output_root, expected):
            return
        raise TaskCatalogBuildError(
            f"catalog_published_version_immutable:{compiled.manifest.catalog_version}"
        )

    output_root.parent.mkdir(parents=True, exist_ok=True)
    lock_path = output_root.parent / f".{output_root.name}.publish.lock"
    try:
        lock_descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise TaskCatalogBuildError(f"catalog_publish_in_progress:{compiled.manifest.catalog_version}") from error
    stage_root: Path | None = None
    try:
        os.close(lock_descriptor)
        if output_root.exists():
            if not catalog_tree_mismatches(output_root, expected):
                return
            raise TaskCatalogBuildError(
                f"catalog_published_version_immutable:{compiled.manifest.catalog_version}"
            )
        stage_root = Path(
            tempfile.mkdtemp(
                prefix=f".{output_root.name}.staging-",
                dir=output_root.parent,
            )
        )
        _write_staged_catalog(stage_root, expected)
        if output_root.exists():
            if not catalog_tree_mismatches(output_root, expected):
                return
            raise TaskCatalogBuildError(
                f"catalog_published_version_immutable:{compiled.manifest.catalog_version}"
            )
        stage_root.rename(output_root)
        stage_root = None
        parent_descriptor = os.open(output_root.parent, os.O_RDONLY)
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    finally:
        if stage_root is not None:
            shutil.rmtree(stage_root, ignore_errors=True)
        lock_path.unlink(missing_ok=True)


def build_task_catalog(
    source_root: Path,
    output_root: Path,
    *,
    catalog_version: str = _CATALOG_V1,
    scenario_output_mapping_path: Path | None = None,
) -> CompiledTaskCatalog:
    compiled = compile_task_catalog(
        source_root,
        catalog_version=catalog_version,
        scenario_output_mapping_path=scenario_output_mapping_path,
    )
    write_task_catalog(compiled, output_root)
    return compiled
