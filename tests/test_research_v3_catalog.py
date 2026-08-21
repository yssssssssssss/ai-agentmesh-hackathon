from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
import yaml

from agentmesh.research_orchestration.v3.catalog import (
    CATALOG_MAX_DOCUMENT_DEPTH,
    _preflight_inventory,
    _read_resource,
    _strict_json_resource_load,
    load_catalog_document,
    load_competitive_text_catalog,
    strict_yaml_load,
)


def test_competitive_text_catalog_loads_from_verified_package_resources() -> None:
    catalog = load_competitive_text_catalog()
    assert catalog.catalog_hash is not None
    assert catalog.catalog_id == "competitive-text-v1"
    assert catalog.orchestration_version == "research-v3"
    assert catalog.task_types == ("competitive_research",)
    assert tuple(item.id for item in catalog.actors.tools) == ("tavily-web-search",)
    assert tuple(item.id for item in catalog.actors.skills) == (
        "competitive-web-research",
        "competitive-analysis",
    )
    assert catalog.actors.tools[0].execution_mode == "real"
    assert catalog.actors.tools[0].approval_role == "owner"
    assert catalog.actors.skills[0].enabled_optional_tools == ()
    assert tuple(item.id for item in catalog.excluded_source_capabilities) == (
        "competitive-app-analysis",
        "digital-human-competitive-analysis",
        "playwright-page-capture",
    )


def test_catalog_exposes_locked_policy_rubric_template_and_source_metadata() -> None:
    catalog = load_competitive_text_catalog()
    policy = load_catalog_document(catalog, "competitive-analysis-text-v3")
    rubric = load_catalog_document(catalog, "competitive-analysis-review-v3")
    template = load_catalog_document(catalog, "competitive-analysis-text-template-v3")
    source_graph = load_catalog_document(catalog, "source-decision-graph")
    source_tool = load_catalog_document(catalog, "source-tavily-manifest")
    assert policy["requirements"][0]["accepted_classes"] == ["public_source"]
    assert [item["id"] for item in rubric["dimensions"]] == [
        "requirement_coverage",
        "question_coverage",
        "evidence_coverage",
        "reasoning_quality",
        "recommendation_quality",
        "visual_quality",
        "risk_disclosure",
    ]
    assert len(template["sections"]) == 13
    assert source_graph["version"] == 1
    assert source_tool["adapter_type"] == "tavily"


def test_source_snapshot_binds_exact_locked_commit_tree_and_hashes() -> None:
    root = Path("agentmesh/research_catalog/research-v3/competitive-text-v1")
    snapshot = json.loads((root / "source-snapshot.json").read_text(encoding="utf-8"))
    assert snapshot["source_commit"] == "d7ec877fbff0684b0886cb86a7e09eb42ebf7d77"
    assert snapshot["source_tree"] == "ca63e2fdb4c3fcff0f50c8095a1497f8db4cdd12"
    rows = {item["source_path"]: item["sha256"] for item in snapshot["files"]}
    assert len(rows) == 24
    assert rows["schemas/research-task-v2.schema.json"] == (
        "299c4fa147d28a3e7ff38fea0e2f981dc3b38a1d8aad07498d2f6734ad24dbea"
    )
    assert rows["orchestrator/decision-graph.yaml"] == (
        "7ef06d665cdd6738e59237c61236c2bd3790e421213838d055e10b064d7f948a"
    )
    assert rows["tools/tavily-web-search/manifest.yaml"] == (
        "bd01fe58b45909a0f9f41b57fa2f88a961331b3a89f6c309c3e4760ed1518cd8"
    )


def test_catalog_yaml_rejects_ambiguous_or_unsafe_constructs() -> None:
    with pytest.raises(ValueError, match="duplicate YAML key"):
        strict_yaml_load("id: one\nid: two\n")
    with pytest.raises(ValueError, match="aliases"):
        strict_yaml_load("first: &value one\nsecond: *value\n")
    with pytest.raises(ValueError, match="mapping keys must be strings"):
        strict_yaml_load("1: value\n")
    with pytest.raises(yaml.constructor.ConstructorError):  # type: ignore[name-defined]
        strict_yaml_load("value: !unsafe payload\n")


def test_catalog_preflight_enforces_file_count_size_and_aggregate_limits(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.yaml"
    first.write_bytes(b"{}")
    second.write_bytes(b"key: value\n")

    with pytest.raises(ValueError, match="file count"):
        _preflight_inventory(tmp_path, max_files=1)
    with pytest.raises(ValueError, match="aggregate bytes"):
        _preflight_inventory(tmp_path, max_aggregate_bytes=4)
    with pytest.raises(ValueError, match="per-file byte limit"):
        _preflight_inventory(tmp_path, max_file_bytes=4)

    inventory = _preflight_inventory(tmp_path)
    with pytest.raises(ValueError, match="its byte limit"):
        _read_resource(tmp_path, "second.yaml", inventory, max_bytes=4)


def test_catalog_yaml_and_json_depth_limits_are_fail_closed() -> None:
    yaml_lines = ["value:"]
    yaml_lines.extend(f"{'  ' * depth}child:" for depth in range(1, CATALOG_MAX_DOCUMENT_DEPTH + 2))
    yaml_lines.append(f"{'  ' * (CATALOG_MAX_DOCUMENT_DEPTH + 2)}leaf: value")
    with pytest.raises(ValueError, match="document depth"):
        strict_yaml_load("\n".join(yaml_lines))

    nested_json = "{}"
    for _ in range(CATALOG_MAX_DOCUMENT_DEPTH + 1):
        nested_json = '{"child":' + nested_json + "}"
    with pytest.raises(ValueError, match="document depth"):
        _strict_json_resource_load(nested_json)


def test_catalog_loading_never_uses_unbounded_path_read_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject_read_bytes(self: Path) -> bytes:
        raise AssertionError(f"unbounded read_bytes called for {self}")

    monkeypatch.setattr(Path, "read_bytes", reject_read_bytes)
    assert load_competitive_text_catalog().catalog_hash is not None


def test_package_data_is_narrow_and_excludes_evidence_bundle() -> None:
    package_data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"][
        "package-data"
    ]["agentmesh"]
    assert "schemas/research/*.json" in package_data
    assert "research_catalog/research-v3/competitive-text-v1/**" in package_data
    assert "research_catalog/**" not in package_data
    assert all("source-bundles" not in value for value in package_data)
