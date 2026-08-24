from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from agentmesh.task_routing.catalog import TaskCatalogLoadError, load_default_task_catalog, load_task_catalog
from agentmesh.task_routing.compiler import (
    TaskCatalogBuildError,
    build_task_catalog,
    canonical_sha256,
    compile_task_catalog,
    json_bytes,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _source_tree(tmp_path: Path) -> Path:
    root = tmp_path / "user-research"
    _write(
        root / "05-registry-索引/task-registry.yaml",
        """
- id: find-direction
  title: 找方向
  level: task
  parent_task: ""
  description: 判断探索方向。
  status: draft
  owner: test
  updated_at: "2026-08-05"
  source_path: 01-task-任务/find-direction/index.md
  trigger_keywords: [找方向]
  outputs: [方向判断]
  workflow_ids: []
  recommended_skills: []
  required_knowledge_types: [current-project-materials]
- id: competitor-benchmark-research
  title: 竞品与标杆研究
  level: scenario
  parent_task: find-direction
  description: 对比竞品模式。
  status: draft
  owner: test
  updated_at: "2026-08-05"
  source_path: 01-task-任务/find-direction/competitor.md
  trigger_keywords: [帮我看看竞品]
  outputs: [模式对比]
  workflow_ids: []
  recommended_skills: [ds-skill-competitor, planned-future-skill]
  required_knowledge_types: [method-one, 当前项目资料]
""".strip()
        + "\n",
    )
    _write(
        root / "05-registry-索引/skill-registry.yaml",
        """
- id: ds-skill-competitor
  title: 竞品分析
  type: skill
  description: 分析竞品。
  business_domain: general
  status: draft
  source_path: 02-skills-技能/competitor/SKILL.md
  capability_domain: [design-strategy]
  task_types: [competitor-analysis]
  tags: [skill]
  dependencies: []
  related_items: []
""".strip()
        + "\n",
    )
    _write(
        root / "05-registry-索引/knowledge-registry.yaml",
        """
- id: method-one
  title: 竞品方法
  type: method
  description: 分析方法。
  business_domain: general
  status: draft
  source_path: 03-knowledge-知识/method-one.md
  capability_domain: [design-strategy]
  task_types: [competitor-analysis]
  tags: [method]
  dependencies: []
  related_items: []
""".strip()
        + "\n",
    )
    _write(root / "01-task-任务/find-direction/index.md", "# 找方向\n")
    _write(root / "02-skills-技能/competitor/SKILL.md", "# 竞品分析\n")
    _write(root / "03-knowledge-知识/method-one.md", "# 竞品方法\n")
    _write(
        root / "01-task-任务/find-direction/competitor.md",
        """
---
id: competitor-benchmark-research
title: 竞品与标杆研究
parent_task: find-direction
task_type: scenario
definition: 对比竞品模式。
trigger_examples: [帮我看看竞品]
required_inputs: [研究目标]
optional_inputs: [竞品资料]
outputs: [模式对比]
completion_criteria: [结论有来源]
default_skills:
  - id: ds-skill-competitor
    status: draft
optional_skills:
  - id: planned-future-skill
    status: planned
knowledge_requirements: [method-one, 当前项目资料]
dependencies: []
fallback: [资料不足时输出采集清单。]
human_confirmation: [涉及不可逆业务决策。]
status: draft
owner: test
updated_at: "2026-08-05"
---
# 竞品与标杆研究
""".strip()
        + "\n",
    )
    _write(
        root / "01-task-任务/task-skill-knowledge-mapping.md",
        """
# Task Skill Knowledge 映射

## 15 个 Scenario 映射

| Scenario | 默认 Skill | 按需 Skill | 必需 Knowledge | 按需 Knowledge |
|---|---|---|---|---|
| 竞品与标杆研究 | `ds-skill-competitor` | `planned-future-skill` | method-one | 当前项目资料 |

## 知识调用原则
""".lstrip(),
    )
    return root


def _yaml_items(path: Path) -> list[dict[str, object]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    return payload


def _refresh_manifest_hash(output: Path, relative_path: str, payload: object) -> None:
    manifest_path = output / "catalog.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][relative_path] = hashlib.sha256(json_bytes(payload)).hexdigest()
    manifest_body = {key: value for key, value in manifest.items() if key != "catalog_hash"}
    manifest["catalog_hash"] = canonical_sha256(manifest_body)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_build_and_load_task_catalog(tmp_path: Path) -> None:
    source = _source_tree(tmp_path)
    output = tmp_path / "catalog"

    compiled = build_task_catalog(source, output)
    catalog = load_task_catalog(output)

    assert compiled.manifest.counts == {
        "knowledge": 1,
        "mappings": 1,
        "scenarios": 1,
        "skills": 1,
        "tasks": 1,
    }
    assert catalog.get_task("find-direction") is not None
    assert catalog.get_scenario("competitor-benchmark-research") is not None
    mapping = catalog.get_mapping("competitor-benchmark-research")
    assert mapping is not None
    assert mapping.default_skill_ids == ("ds-skill-competitor",)
    assert mapping.optional_skill_ids == ()
    assert mapping.planned_skill_ids == ("planned-future-skill",)
    assert mapping.required_knowledge_ids == ("method-one",)
    assert mapping.optional_knowledge_descriptors == ("当前项目资料",)
    assert catalog.scenarios_for_task("find-direction")[0].id == "competitor-benchmark-research"


def test_task_catalog_build_is_deterministic(tmp_path: Path) -> None:
    source = _source_tree(tmp_path)

    first = compile_task_catalog(source)
    second = compile_task_catalog(source)

    assert first.manifest == second.manifest
    assert first.files == second.files


def test_duplicate_registry_id_is_rejected(tmp_path: Path) -> None:
    source = _source_tree(tmp_path)
    registry = source / "05-registry-索引/task-registry.yaml"
    items = _yaml_items(registry)
    items.append(copy.deepcopy(items[0]))
    registry.write_text(yaml.safe_dump(items, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with pytest.raises(TaskCatalogBuildError, match="duplicate_id:task-registry:find-direction"):
        compile_task_catalog(source)


def test_missing_parent_task_is_rejected(tmp_path: Path) -> None:
    source = _source_tree(tmp_path)
    registry = source / "05-registry-索引/task-registry.yaml"
    items = _yaml_items(registry)
    items[1]["parent_task"] = "missing-task"
    registry.write_text(yaml.safe_dump(items, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with pytest.raises(TaskCatalogBuildError, match="parent_task_missing"):
        compile_task_catalog(source)


def test_unregistered_executable_skill_is_rejected(tmp_path: Path) -> None:
    source = _source_tree(tmp_path)
    scenario = source / "01-task-任务/find-direction/competitor.md"
    scenario.write_text(
        scenario.read_text(encoding="utf-8").replace("ds-skill-competitor", "missing-skill"),
        encoding="utf-8",
    )
    registry = source / "05-registry-索引/task-registry.yaml"
    items = _yaml_items(registry)
    items[1]["recommended_skills"][0] = "missing-skill"
    registry.write_text(yaml.safe_dump(items, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with pytest.raises(TaskCatalogBuildError, match="skill_reference_missing:missing-skill"):
        compile_task_catalog(source)


def test_unknown_ascii_knowledge_reference_is_rejected(tmp_path: Path) -> None:
    source = _source_tree(tmp_path)
    mapping = source / "01-task-任务/task-skill-knowledge-mapping.md"
    mapping.write_text(
        mapping.read_text(encoding="utf-8").replace("method-one", "missing-method"),
        encoding="utf-8",
    )
    scenario = source / "01-task-任务/find-direction/competitor.md"
    scenario.write_text(
        scenario.read_text(encoding="utf-8").replace("method-one", "missing-method"),
        encoding="utf-8",
    )
    registry = source / "05-registry-索引/task-registry.yaml"
    items = _yaml_items(registry)
    items[1]["required_knowledge_types"][0] = "missing-method"
    registry.write_text(yaml.safe_dump(items, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with pytest.raises(TaskCatalogBuildError, match="knowledge_reference_missing:missing-method"):
        compile_task_catalog(source)


def test_unknown_unicode_knowledge_descriptor_is_rejected(tmp_path: Path) -> None:
    source = _source_tree(tmp_path)
    mapping = source / "01-task-任务/task-skill-knowledge-mapping.md"
    mapping.write_text(
        mapping.read_text(encoding="utf-8").replace("当前项目资料", "当前项目资枓"),
        encoding="utf-8",
    )
    scenario = source / "01-task-任务/find-direction/competitor.md"
    scenario.write_text(
        scenario.read_text(encoding="utf-8").replace("当前项目资料", "当前项目资枓"),
        encoding="utf-8",
    )
    registry = source / "05-registry-索引/task-registry.yaml"
    items = _yaml_items(registry)
    items[1]["required_knowledge_types"][1] = "当前项目资枓"
    registry.write_text(yaml.safe_dump(items, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with pytest.raises(TaskCatalogBuildError, match="knowledge_reference_missing:当前项目资枓"):
        compile_task_catalog(source)


def test_scenario_dependency_cycle_is_rejected(tmp_path: Path) -> None:
    source = _source_tree(tmp_path)
    scenario = source / "01-task-任务/find-direction/competitor.md"
    scenario.write_text(
        scenario.read_text(encoding="utf-8").replace(
            "dependencies: []",
            "dependencies: [competitor-benchmark-research]",
        ),
        encoding="utf-8",
    )

    with pytest.raises(TaskCatalogBuildError, match="scenario_self_dependency"):
        compile_task_catalog(source)


def test_source_path_cannot_escape_catalog_root(tmp_path: Path) -> None:
    source = _source_tree(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    registry = source / "05-registry-索引/task-registry.yaml"
    items = _yaml_items(registry)
    items[0]["source_path"] = "../outside.md"
    registry.write_text(yaml.safe_dump(items, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with pytest.raises(TaskCatalogBuildError, match="source_path_invalid"):
        compile_task_catalog(source)


def test_loader_detects_catalog_file_drift(tmp_path: Path) -> None:
    source = _source_tree(tmp_path)
    output = tmp_path / "catalog"
    build_task_catalog(source, output)
    tasks_path = output / "tasks.json"
    payload = json.loads(tasks_path.read_text(encoding="utf-8"))
    payload[0]["title"] = "被篡改"
    tasks_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(TaskCatalogLoadError, match="catalog_file_hash_mismatch:tasks.json"):
        load_task_catalog(output)


def test_loader_detects_cross_file_parent_mismatch(tmp_path: Path) -> None:
    source = _source_tree(tmp_path)
    registry = source / "05-registry-索引/task-registry.yaml"
    items = _yaml_items(registry)
    second_task = copy.deepcopy(items[0])
    second_task["id"] = "understand-users"
    second_task["title"] = "懂用户"
    items.insert(1, second_task)
    registry.write_text(yaml.safe_dump(items, allow_unicode=True, sort_keys=False), encoding="utf-8")
    output = tmp_path / "catalog"
    build_task_catalog(source, output)
    scenarios_path = output / "scenarios.json"
    payload = json.loads(scenarios_path.read_text(encoding="utf-8"))
    payload[0]["parent_task"] = "understand-users"
    scenarios_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _refresh_manifest_hash(output, "scenarios.json", payload)

    with pytest.raises(TaskCatalogLoadError, match="catalog_mapping_parent_mismatch"):
        load_task_catalog(output)


def test_loader_rejects_undeclared_files(tmp_path: Path) -> None:
    source = _source_tree(tmp_path)
    output = tmp_path / "catalog"
    build_task_catalog(source, output)
    (output / "unexpected.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(TaskCatalogLoadError, match="catalog_undeclared_files"):
        load_task_catalog(output)


def test_planned_default_skill_never_becomes_executable(tmp_path: Path) -> None:
    source = _source_tree(tmp_path)
    scenario = source / "01-task-任务/find-direction/competitor.md"
    scenario.write_text(
        scenario.read_text(encoding="utf-8").replace(
            "default_skills:\n  - id: ds-skill-competitor\n    status: draft",
            "default_skills:\n  - id: ds-skill-competitor\n    status: draft\n"
            "  - id: planned-default-skill\n    status: planned-next",
        ),
        encoding="utf-8",
    )
    mapping_path = source / "01-task-任务/task-skill-knowledge-mapping.md"
    mapping_path.write_text(
        mapping_path.read_text(encoding="utf-8").replace(
            "| `ds-skill-competitor` |",
            "| `ds-skill-competitor`, `planned-default-skill` |",
        ),
        encoding="utf-8",
    )
    registry = source / "05-registry-索引/task-registry.yaml"
    items = _yaml_items(registry)
    items[1]["recommended_skills"].insert(1, "planned-default-skill")
    registry.write_text(yaml.safe_dump(items, allow_unicode=True, sort_keys=False), encoding="utf-8")

    compiled = compile_task_catalog(source)
    mapping = compiled.files["task-skill-mapping.json"][0]

    assert mapping["default_skill_ids"] == ["ds-skill-competitor"]
    assert mapping["planned_skill_ids"] == ["planned-default-skill", "planned-future-skill"]


def test_default_loader_returns_fresh_catalog_instances() -> None:
    first = load_default_task_catalog()
    first.manifest.files["tasks.json"] = "0" * 64

    second = load_default_task_catalog()

    assert second is not first
    assert second.manifest.files["tasks.json"] != "0" * 64


def test_generated_schemas_declare_draft_and_identity() -> None:
    catalog_root = Path("agentmesh/task_catalog/user-research-v1")
    for schema_path in sorted((catalog_root / "schemas").glob("*.json")):
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"].endswith(schema_path.name)
        Draft202012Validator.check_schema(schema)


def test_catalog_contains_explicit_runtime_skill_bindings() -> None:
    catalog = load_default_task_catalog()

    competitive = catalog.get_skill("ur-skill-competitive-analysis")
    design_strategy = catalog.get_skill("ds-skill-competitor-strategy-analysis")
    assert competitive is not None and competitive.runtime_skill_name == "competitive-analysis"
    assert design_strategy is not None and design_strategy.runtime_skill_name is None


def test_checked_in_catalog_has_expected_core_coverage() -> None:
    catalog = load_default_task_catalog()

    assert len(catalog.tasks) == 5
    assert len(catalog.scenarios) == 15
    assert len(catalog.mappings) == 15
    assert catalog.get_task("define-strategy") is not None
    assert {scenario.id for scenario in catalog.scenarios_for_task("define-strategy")} == {
        "strategy-synthesis",
        "priority-roadmap",
        "metrics-validation",
    }
    opportunity = catalog.get_mapping("opportunity-direction-evaluation")
    assert opportunity is not None
    assert opportunity.planned_skill_ids == ("planned-opportunity-evaluation-skill",)
