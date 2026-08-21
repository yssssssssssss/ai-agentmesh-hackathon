from __future__ import annotations

import hashlib
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


class _StrictYamlLoader(yaml.SafeLoader):
    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(AliasEvent):
            raise ValueError("YAML aliases are not allowed in research catalogs")
        return super().compose_node(parent, index)

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


def strict_yaml_load(value: str | bytes) -> Any:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="strict")
    return yaml.load(value, Loader=_StrictYamlLoader)


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


def _resource(root: Traversable, relative_path: str) -> Traversable:
    current = root
    for part in _safe_parts(relative_path):
        current = current.joinpath(part)
        if isinstance(current, Path) and current.is_symlink():
            raise ValueError(f"catalog resources must not be symlinks: {relative_path}")
    if not current.is_file():
        raise ValueError(f"catalog resource is missing: {relative_path}")
    return current


def _read_verified(root: Traversable, relative_path: str, expected_hash: str) -> bytes:
    content = _resource(root, relative_path).read_bytes()
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected_hash:
        raise ValueError(f"catalog resource hash mismatch: {relative_path}")
    return content


def _inventory(root: Traversable, prefix: str = "") -> set[str]:
    result: set[str] = set()
    for child in root.iterdir():
        relative = f"{prefix}/{child.name}" if prefix else child.name
        if isinstance(child, Path) and child.is_symlink():
            raise ValueError(f"catalog resources must not be symlinks: {relative}")
        if child.is_dir():
            result.update(_inventory(child, relative))
        elif child.is_file():
            result.add(relative)
        else:
            raise ValueError(f"catalog contains an unsupported filesystem entry: {relative}")
    return result


def _catalog_root() -> Traversable:
    root: Traversable = files("agentmesh")
    for part in CATALOG_RELATIVE_ROOT:
        root = root.joinpath(part)
    return root


def load_competitive_text_catalog() -> CompetitiveTextCatalog:
    """Load and byte-verify the packaged, non-production Competitive Text catalog."""

    root = _catalog_root()
    catalog_bytes = _resource(root, "catalog.yaml").read_bytes()
    raw_catalog = strict_yaml_load(catalog_bytes)
    if not isinstance(raw_catalog, Mapping):
        raise ValueError("catalog.yaml must contain a mapping")
    catalog = CompetitiveTextCatalog.model_validate(raw_catalog)

    declared = {"catalog.yaml", catalog.source_snapshot}
    resource_hashes: list[tuple[str, str]] = []
    for document in catalog.documents:
        _read_verified(root, document.path, document.sha256)
        declared.add(document.path)
        resource_hashes.append((document.path, document.sha256))

    snapshot_raw = strict_json_v3_loads(_resource(root, catalog.source_snapshot).read_bytes())
    snapshot = CompetitiveTextSourceSnapshot.model_validate(snapshot_raw)
    if snapshot.catalog_id != catalog.catalog_id:
        raise ValueError("source snapshot and catalog IDs must agree")
    for item in snapshot.files:
        if item.target_path != f"source/{item.source_path}":
            raise ValueError("source snapshot target paths must preserve the locked relative path")
        _read_verified(root, item.target_path, item.sha256)
        declared.add(item.target_path)
        resource_hashes.append((item.target_path, item.sha256))

    actual = _inventory(root)
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
    return _read_verified(_catalog_root(), document.path, document.sha256)


def load_catalog_document(catalog: CompetitiveTextCatalog, document_id: str) -> Any:
    document = next((item for item in catalog.documents if item.id == document_id), None)
    if document is None:
        raise KeyError(f"unknown catalog document: {document_id}")
    content = read_catalog_document(catalog, document_id)
    if document.path.endswith((".yaml", ".yml")):
        return strict_yaml_load(content)
    if document.path.endswith(".json"):
        return strict_json_v3_loads(content)
    return content.decode("utf-8", errors="strict")
