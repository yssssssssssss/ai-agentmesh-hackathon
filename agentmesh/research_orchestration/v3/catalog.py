from __future__ import annotations

import hashlib
import stat
from collections.abc import Mapping
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml
from pydantic import Field, model_validator
from yaml.events import AliasEvent
from yaml.nodes import MappingNode, ScalarNode

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_sha256, strict_json_v3_loads
from agentmesh.research_orchestration.v3.common import (
    Identifier,
    NonBlankString,
    Sha256Hex,
    StrictFrozenModel,
    require_unique,
)

CATALOG_RELATIVE_ROOT = ("research_catalog", "research-v3", "competitive-text-v1")
CATALOG_MAX_FILES = 64
CATALOG_MAX_FILE_BYTES = 262_144
CATALOG_MAX_AGGREGATE_BYTES = 2_097_152
CATALOG_MAX_VISITED_ENTRIES = 256
CATALOG_MAX_DIRECTORIES = 64
CATALOG_MAX_DIRECTORY_DEPTH = 16
CATALOG_MAX_DOCUMENT_DEPTH = 32
CATALOG_MAX_DOCUMENT_NODES = 50_000
CATALOG_MAX_CATALOG_BYTES = 65_536
CATALOG_MAX_SNAPSHOT_BYTES = 65_536


class _StrictYamlLoader(yaml.SafeLoader):
    def __init__(self, stream: Any) -> None:
        super().__init__(stream)
        self._resource_depth = 0
        self._resource_nodes = 0

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(AliasEvent):
            raise ValueError("YAML aliases are not allowed in research catalogs")
        self._resource_depth += 1
        self._resource_nodes += 1
        try:
            if self._resource_depth > CATALOG_MAX_DOCUMENT_DEPTH:
                raise ValueError("research catalog YAML exceeds the maximum document depth")
            if self._resource_nodes > CATALOG_MAX_DOCUMENT_NODES:
                raise ValueError("research catalog YAML exceeds the maximum node count")
            return super().compose_node(parent, index)
        finally:
            self._resource_depth -= 1

    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[str, Any]:
        if not isinstance(node, MappingNode):
            raise ValueError("expected a YAML mapping")
        result: dict[str, Any] = {}
        for key_node, value_node in node.value:
            if not isinstance(key_node, ScalarNode) or key_node.tag != "tag:yaml.org,2002:str":
                raise ValueError("research catalog YAML mapping keys must be strings")
            key = self.construct_object(key_node, deep=deep)
            if key == "<<" or key_node.tag == "tag:yaml.org,2002:merge":
                raise ValueError("YAML merge keys are not allowed in research catalogs")
            if key in result:
                raise ValueError(f"duplicate YAML key: {key}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _validate_document_resources(value: Any, *, media_type: str) -> Any:
    stack = [(value, 1)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if depth > CATALOG_MAX_DOCUMENT_DEPTH:
            raise ValueError(f"research catalog {media_type} exceeds the maximum document depth")
        if nodes > CATALOG_MAX_DOCUMENT_NODES:
            raise ValueError(f"research catalog {media_type} exceeds the maximum node count")
        if isinstance(current, Mapping):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, (list, tuple)):
            stack.extend((item, depth + 1) for item in current)
    return value


def strict_yaml_load(value: str | bytes) -> Any:
    if isinstance(value, bytes):
        if len(value) > CATALOG_MAX_FILE_BYTES:
            raise ValueError("research catalog YAML exceeds the maximum byte size")
        value = value.decode("utf-8", errors="strict")
    elif len(value.encode("utf-8")) > CATALOG_MAX_FILE_BYTES:
        raise ValueError("research catalog YAML exceeds the maximum byte size")
    return _validate_document_resources(
        yaml.load(value, Loader=_StrictYamlLoader),
        media_type="YAML",
    )


def _strict_json_resource_load(value: str | bytes | bytearray) -> Any:
    byte_length = len(value) if not isinstance(value, str) else len(value.encode("utf-8"))
    if byte_length > CATALOG_MAX_FILE_BYTES:
        raise ValueError("research catalog JSON exceeds the maximum byte size")
    try:
        parsed = strict_json_v3_loads(value)
    except RecursionError as exc:
        raise ValueError("research catalog JSON exceeds the maximum document depth") from exc
    return _validate_document_resources(parsed, media_type="JSON")


class CatalogDocument(StrictFrozenModel):
    id: Identifier
    kind: Literal[
        "json_schema",
        "skill_instructions",
        "knowledge",
        "evidence_policy",
        "review_rubric",
        "report_template",
        "synthesis_prompt",
        "source_metadata",
    ]
    path: NonBlankString
    sha256: Sha256Hex


class CatalogDecisionNode(StrictFrozenModel):
    id: Identifier
    required: bool


class CatalogTool(StrictFrozenModel):
    id: Identifier
    tier: Literal["core", "optional"]
    required_provider: Identifier
    execution_mode: Literal["real"]
    runtime_tool_definition_id: Identifier
    runtime_gateway_name: Identifier
    approval_role: Literal["owner", "legal", "security"]


class CatalogSkill(StrictFrozenModel):
    id: Identifier
    required_tools: tuple[Identifier, ...]
    required_resources: tuple[Identifier, ...] = ()
    source_optional_tools: tuple[Identifier, ...]
    enabled_optional_tools: tuple[Identifier, ...]
    output_root: str = Field(pattern=r"^/")


class CatalogModelActor(StrictFrozenModel):
    id: Identifier
    output_root: str = Field(pattern=r"^/")


class CatalogActors(StrictFrozenModel):
    tools: tuple[CatalogTool, ...]
    skills: tuple[CatalogSkill, ...]
    llm: tuple[CatalogModelActor, ...]
    reviewers: tuple[CatalogModelActor, ...]


class CatalogDeliverable(StrictFrozenModel):
    id: Literal["competitive_analysis_report"]
    task_types: tuple[Literal["competitive_research"], ...]
    envelope_version: Literal["research-deliverable-v3"]
    payload_schema_version: Literal["competitive-analysis-text-v1"]
    evidence_policy: Identifier
    review_rubric: Identifier
    report_template: Identifier
    synthesis_prompt: Identifier


class ExcludedSourceCapability(StrictFrozenModel):
    id: Identifier
    reason: Identifier


class CompetitiveTextCatalog(StrictFrozenModel):
    schema_version: Literal["research-catalog-v3"]
    catalog_id: Literal["competitive-text-v1"]
    orchestration_version: Literal["research-v3"]
    task_types: tuple[Literal["competitive_research"], ...]
    decision_nodes: tuple[CatalogDecisionNode, ...]
    actors: CatalogActors
    deliverables: tuple[CatalogDeliverable, ...]
    excluded_source_capabilities: tuple[ExcludedSourceCapability, ...]
    documents: tuple[CatalogDocument, ...]
    source_snapshot: Literal["source-snapshot.json"]
    catalog_hash: Sha256Hex | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> CompetitiveTextCatalog:
        if self.task_types != ("competitive_research",):
            raise ValueError("Slice 1 catalog must expose only Competitive Text research")
        expected_nodes = (
            ("D1_research_goal", True),
            ("D3_method_selection", True),
            ("D5_competitive", False),
            ("D6_data_sensitivity", True),
            ("D7_output_standard", True),
        )
        if tuple((node.id, node.required) for node in self.decision_nodes) != expected_nodes:
            raise ValueError("Competitive Text decision node scope differs from the locked catalog")
        if tuple(tool.id for tool in self.actors.tools) != ("tavily-web-search",):
            raise ValueError("Slice 1 exposes exactly one Tavily Tool")
        tool = self.actors.tools[0]
        if (
            tool.required_provider,
            tool.execution_mode,
            tool.runtime_tool_definition_id,
            tool.runtime_gateway_name,
            tool.approval_role,
        ) != ("tavily", "real", "tool_web_research", "web_research", "owner"):
            raise ValueError("Tavily Tool mapping must retain AgentMesh's stronger approval policy")
        if tuple(skill.id for skill in self.actors.skills) != (
            "competitive-web-research",
            "competitive-analysis",
        ):
            raise ValueError("Slice 1 exposes exactly the two Competitive Text Skills")
        if tuple(actor.id for actor in self.actors.llm) != ("competitive-text-synthesis-v1",):
            raise ValueError("Slice 1 exposes exactly one synthesis actor")
        if tuple(actor.id for actor in self.actors.reviewers) != ("competitive-text-quality-reviewer-v1",):
            raise ValueError("Slice 1 exposes exactly one Reviewer")
        web_skill = self.actors.skills[0]
        if web_skill.required_tools != ("tavily-web-search",) or web_skill.enabled_optional_tools:
            raise ValueError("Competitive Web Research must require Tavily and enable no optional Tool")
        if web_skill.source_optional_tools != ("playwright-page-capture",):
            raise ValueError("the excluded source Playwright capability must remain explicit")
        if tuple(item.id for item in self.deliverables) != ("competitive_analysis_report",):
            raise ValueError("Slice 1 exposes exactly one Competitive Text deliverable")
        excluded = tuple(item.id for item in self.excluded_source_capabilities)
        if excluded != (
            "competitive-app-analysis",
            "digital-human-competitive-analysis",
            "playwright-page-capture",
        ):
            raise ValueError("Slice 1 excluded capability set differs from the locked scope")
        require_unique(tuple(item.id for item in self.documents), "catalog document IDs")
        require_unique(tuple(item.path for item in self.documents), "catalog document paths")
        return self


class SourceSnapshotFile(StrictFrozenModel):
    source_path: NonBlankString
    target_path: NonBlankString
    mode: Literal["100644"]
    sha256: Sha256Hex
    copy_mode: Literal["verbatim"]
    runtime_role: Literal[
        "source_adapter_input",
        "source_metadata",
        "skill_instructions",
        "knowledge",
        "synthesis_prompt",
        "review_rubric",
        "report_template",
        "tool_contract",
    ]


class CompetitiveTextSourceSnapshot(StrictFrozenModel):
    schema_version: Literal["ai-x-competitive-text-source-snapshot-v1"]
    source_commit: Literal["d7ec877fbff0684b0886cb86a7e09eb42ebf7d77"]
    source_tree: Literal["ca63e2fdb4c3fcff0f50c8095a1497f8db4cdd12"]
    catalog_id: Literal["competitive-text-v1"]
    files: tuple[SourceSnapshotFile, ...]

    @model_validator(mode="after")
    def validate_files(self) -> CompetitiveTextSourceSnapshot:
        require_unique(tuple(item.source_path for item in self.files), "source snapshot source paths")
        require_unique(tuple(item.target_path for item in self.files), "source snapshot target paths")
        return self


def _safe_parts(relative_path: str) -> tuple[str, ...]:
    path = PurePosixPath(relative_path)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe catalog resource path: {relative_path!r}")
    if str(path) != relative_path:
        raise ValueError(f"catalog resource path is not normalized: {relative_path!r}")
    return path.parts


def _resource(root: Traversable, relative_path: str) -> Path:
    if not isinstance(root, Path):
        raise ValueError("catalog resources must be backed by a local filesystem path")
    current = root
    for part in _safe_parts(relative_path):
        current = current.joinpath(part)
        try:
            metadata = current.lstat()
        except FileNotFoundError as exc:
            raise ValueError(f"catalog resource is missing: {relative_path}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError(f"catalog resources must not be symlinks: {relative_path}")
    if not stat.S_ISREG(current.lstat().st_mode):
        raise ValueError(f"catalog resource is not a regular file: {relative_path}")
    return current


def _preflight_inventory(
    root: Traversable,
    *,
    max_files: int = CATALOG_MAX_FILES,
    max_aggregate_bytes: int = CATALOG_MAX_AGGREGATE_BYTES,
    max_file_bytes: int = CATALOG_MAX_FILE_BYTES,
    max_visited_entries: int = CATALOG_MAX_VISITED_ENTRIES,
    max_directories: int = CATALOG_MAX_DIRECTORIES,
) -> dict[str, int]:
    """Bound the entire filesystem-backed inventory before reading any resource bytes."""

    if not isinstance(root, Path):
        raise ValueError("catalog resources must be backed by a local filesystem path")
    try:
        root_metadata = root.lstat()
    except FileNotFoundError as exc:
        raise ValueError("catalog resource root is missing") from exc
    if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode):
        raise ValueError("catalog resource root must be a real directory")

    inventory: dict[str, int] = {}
    aggregate_bytes = 0
    visited_entries = 0
    directory_count = 1
    if directory_count > max_directories:
        raise ValueError("catalog directory count exceeds the resource limit")
    pending = [(root, "", 0)]
    while pending:
        directory, prefix, depth = pending.pop()
        if depth > CATALOG_MAX_DIRECTORY_DEPTH:
            raise ValueError("catalog directory depth exceeds the resource limit")
        for child in directory.iterdir():
            visited_entries += 1
            if visited_entries > max_visited_entries:
                raise ValueError("catalog visited entry count exceeds the resource limit")
            relative = f"{prefix}/{child.name}" if prefix else child.name
            metadata = child.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError(f"catalog resources must not be symlinks: {relative}")
            if stat.S_ISDIR(metadata.st_mode):
                directory_count += 1
                if directory_count > max_directories:
                    raise ValueError("catalog directory count exceeds the resource limit")
                pending.append((child, relative, depth + 1))
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError(f"catalog contains an unsupported filesystem entry: {relative}")
            if len(inventory) >= max_files:
                raise ValueError("catalog file count exceeds the resource limit")
            if metadata.st_size > max_file_bytes:
                raise ValueError(f"catalog resource exceeds the per-file byte limit: {relative}")
            aggregate_bytes += metadata.st_size
            if aggregate_bytes > max_aggregate_bytes:
                raise ValueError("catalog aggregate bytes exceed the resource limit")
            inventory[relative] = metadata.st_size
    return inventory


def _read_resource(
    root: Traversable,
    relative_path: str,
    inventory: Mapping[str, int],
    *,
    max_bytes: int = CATALOG_MAX_FILE_BYTES,
) -> bytes:
    expected_size = inventory.get(relative_path)
    if expected_size is None:
        raise ValueError(f"catalog resource is missing from the pre-read inventory: {relative_path}")
    if expected_size > max_bytes:
        raise ValueError(f"catalog resource exceeds its byte limit: {relative_path}")
    resource = _resource(root, relative_path)
    if resource.lstat().st_size != expected_size:
        raise ValueError(f"catalog resource size changed after pre-read inventory: {relative_path}")
    with resource.open("rb") as stream:
        content = stream.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError(f"catalog resource exceeds its byte limit: {relative_path}")
    if len(content) != expected_size:
        raise ValueError(f"catalog resource size changed while reading: {relative_path}")
    return content


def _read_verified(
    root: Traversable,
    relative_path: str,
    expected_hash: str,
    inventory: Mapping[str, int],
) -> bytes:
    content = _read_resource(root, relative_path, inventory)
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected_hash:
        raise ValueError(f"catalog resource hash mismatch: {relative_path}")
    return content


def _catalog_root() -> Traversable:
    root: Traversable = files("agentmesh")
    for part in CATALOG_RELATIVE_ROOT:
        root = root.joinpath(part)
    return root


def load_competitive_text_catalog() -> CompetitiveTextCatalog:
    """Load and byte-verify the packaged, non-production Competitive Text catalog."""

    root = _catalog_root()
    inventory = _preflight_inventory(root)
    catalog_bytes = _read_resource(
        root,
        "catalog.yaml",
        inventory,
        max_bytes=CATALOG_MAX_CATALOG_BYTES,
    )
    raw_catalog = strict_yaml_load(catalog_bytes)
    if not isinstance(raw_catalog, Mapping):
        raise ValueError("catalog.yaml must contain a mapping")
    catalog = CompetitiveTextCatalog.model_validate(raw_catalog)

    declared = {"catalog.yaml", catalog.source_snapshot}
    resource_hashes: list[tuple[str, str]] = []
    for document in catalog.documents:
        _read_verified(root, document.path, document.sha256, inventory)
        declared.add(document.path)
        resource_hashes.append((document.path, document.sha256))

    snapshot_bytes = _read_resource(
        root,
        catalog.source_snapshot,
        inventory,
        max_bytes=CATALOG_MAX_SNAPSHOT_BYTES,
    )
    snapshot_raw = _strict_json_resource_load(snapshot_bytes)
    snapshot = CompetitiveTextSourceSnapshot.model_validate(snapshot_raw)
    if snapshot.catalog_id != catalog.catalog_id:
        raise ValueError("source snapshot and catalog IDs must agree")
    for item in snapshot.files:
        if item.target_path != f"source/{item.source_path}":
            raise ValueError("source snapshot target paths must preserve the locked relative path")
        _read_verified(root, item.target_path, item.sha256, inventory)
        declared.add(item.target_path)
        resource_hashes.append((item.target_path, item.sha256))

    final_inventory = _preflight_inventory(root)
    if final_inventory != inventory:
        raise ValueError("catalog inventory changed while loading")
    actual = set(final_inventory)
    if actual != declared:
        extra = sorted(actual - declared)
        missing = sorted(declared - actual)
        raise ValueError(f"catalog file declaration mismatch; extra={extra!r}, missing={missing!r}")

    catalog_hash = canonical_json_v3_sha256(
        {
            "catalog": raw_catalog,
            "resources": sorted(resource_hashes),
            "source_snapshot": snapshot_raw,
        }
    )
    return catalog.model_copy(update={"catalog_hash": catalog_hash})


def read_catalog_document(catalog: CompetitiveTextCatalog, document_id: str) -> bytes:
    matches = [document for document in catalog.documents if document.id == document_id]
    if len(matches) != 1:
        raise KeyError(f"unknown catalog document: {document_id}")
    document = matches[0]
    root = _catalog_root()
    inventory = _preflight_inventory(root)
    return _read_verified(root, document.path, document.sha256, inventory)


def load_catalog_document(catalog: CompetitiveTextCatalog, document_id: str) -> Any:
    document = next((item for item in catalog.documents if item.id == document_id), None)
    if document is None:
        raise KeyError(f"unknown catalog document: {document_id}")
    content = read_catalog_document(catalog, document_id)
    if document.path.endswith((".yaml", ".yml")):
        return strict_yaml_load(content)
    if document.path.endswith(".json"):
        return _strict_json_resource_load(content)
    return content.decode("utf-8", errors="strict")
