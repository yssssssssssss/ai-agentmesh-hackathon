#!/usr/bin/env python3
"""Build and validate the immutable ai-x Gate 0 parity lock.

The lock is derived from Git objects, never mutable checkout files. A valid
lock may remain on HOLD; --require-slice-1-authorized is the release mode.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import re
import sqlite3
import struct
import subprocess
import tempfile
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

DEFAULT_REVISION = "d7ec877fbff0684b0886cb86a7e09eb42ebf7d77"
SOURCE_REPOSITORY = "https://github.com/yssssssssssss/ai-x.git"
TARGET_REPOSITORY = "https://github.com/yssssssssssss/ai-agentmesh-hackathon.git"
SOURCE_BRANCH_LABEL = "agent/ai-x-parity-source-freeze-final"
SOURCE_BUNDLE_REF = f"refs/heads/{SOURCE_BRANCH_LABEL}"
SOURCE_BUNDLE_PATH = Path("agentmesh/research_catalog/source-bundles/ai-x-parity-source-d7ec877.bundle")
SOURCE_BUNDLE_ATTESTATION = Path(
    "agentmesh/research_catalog/source-bundles/ai-x-parity-source-d7ec877.attestation.json"
)
OWNER_ACCEPTANCE_PATH = Path("docs/verification/ai-x-parity-evidence/gate0-owner-acceptance.json")
SOURCE_QUALITY_PATH = Path("docs/verification/ai-x-parity-evidence/source-quality.json")
FREEZE_MANIFEST_PATH = "docs/development/ai-x-parity-source-freeze.json"
TARGET_BASE_COMMIT = "dec6b55b3e97913c052ee2b665c063aec77a9dd3"
TARGET_BASE_TREE = "eb39f8159afb421233b657747192447734fd8b07"
FIXTURE_ROOT = Path("tests/fixtures/ai_x_parity")
HISTORY_ROOT = Path("tests/fixtures/ai_x_history")
BASELINE_ROOT = Path("docs/verification/ai-x-parity-baselines")
LOCK_PATH = Path("agentmesh/research_catalog/ai-x-parity-lock.json")

EXACT_INCLUDED = {
    ".env.example", ".gitignore", "package.json", "pnpm-lock.yaml", "tsconfig.json",
    "apps/web/index.html", "apps/web/package.json", "apps/web/pnpm-lock.yaml",
    "apps/web/tsconfig.json", "apps/web/vite.config.ts", "external-tools/README.md",
    "scripts/current-real-smoke.ts", "scripts/start-labs.mjs",
    "docs/development/research-orchestration-migration-guide.md", FREEZE_MANIFEST_PATH,
}
INCLUDED_PREFIXES = (
    "apps/agent-api/src/", "apps/orchestrator-runtime/src/", "apps/web/src/", "database/",
    "evaluations/skills/", "knowledge-base/", "orchestrator/", "packages/api-contract/",
    "schemas/", "skills/", "tests/", "tools/",
)
LAB_IDS = (
    "aesthetic-quant-lab", "attention-analysis-lab", "experience-model-lab",
    "virtual-user-lab", "vision-brand-lab",
)
LAB_PREFIXES = tuple(f"external-tools/{lab_id}/" for lab_id in LAB_IDS)
PLANNING_ONLY_EXCLUSIONS = {
    "docs/plans/2026-08-20-zero-report-publication-development.md",
    "docs/plans/2026-08-20-zero-report-publication-todolist.md",
}
REGISTRY_PATHS = (
    "orchestrator/decision-graph.yaml", "orchestrator/deliverable-registry.yaml",
    "orchestrator/evidence-policy.yaml", "orchestrator/gold-policy.yaml",
    "orchestrator/skill-registry.yaml", "orchestrator/tool-registry.yaml",
)
ALLOWED_GATE0_EXACT = {
    LOCK_PATH.as_posix(),
    "docs/adr/0006-single-active-research-writer.md",
    "docs/superpowers/plans/2026-08-20-ai-x-workbench-full-parity-migration-plan.md",
    "docs/verification/2026-08-20-ai-x-parity-gate0.md",
    "scripts/build_ai_x_parity_lock.py", "scripts/verify_ai_x_parity_lock.py",
    "tests/test_ai_x_parity_lock_verifier.py",
}
ALLOWED_GATE0_PREFIXES = (
    "agentmesh/research_catalog/source-bundles/",
    "docs/verification/ai-x-parity-baselines/",
    "docs/verification/ai-x-parity-evidence/",
    "tests/fixtures/ai_x_history/",
    "tests/fixtures/ai_x_parity/",
)

REQUIRED_FIXTURES = (
    "candidate-plan-shape.json",
    "competitive-request-routing.json",
    "evidence-deliverable-review-report.json",
    "problem-graph-problem-contract.json",
    "requirement.json",
    "state-transition-matrix.json",
    "v2-historical-read-compatibility.json",
)
HISTORICAL_IDENTITY_POLICY = {
    "orchestration_versions": ["research-v2"],
    "payload_or_schema_identities": [
        "claim-ledger-v1", "competitive-analysis-output-v1", "deliverable-document-v1",
        "deterministic-review-v1", "evidence-manifest-v1", "evidence-source-v1",
        "execution-plan-v2", "problem-contract-v1", "report-document-v1", "research-task-v2",
    ],
    "resource_versions": ["competitive-analysis-review-v1", "evidence-policy-v1"],
}
HISTORICAL_IDENTITY_POLICY["combined"] = byte_sorted_values = sorted(
    HISTORICAL_IDENTITY_POLICY["orchestration_versions"]
    + HISTORICAL_IDENTITY_POLICY["payload_or_schema_identities"]
    + HISTORICAL_IDENTITY_POLICY["resource_versions"],
    key=lambda value: value.encode("utf-8"),
)
CURRENT_IDENTITIES = [
    "execution-plan-v3", "report-document-v3", "report-review-v3",
    "research-deliverable-v3", "research-task-v3", "research-v3",
]
OWNER_ACCOUNTABILITIES = {
    "AX-SOURCE": "immutable source identity, source approval, source quality, durable retention, source visual-fixture provenance",
    "AM-ARCH": "ADR, schema namespace, owner registry, single-writer and cutover decision",
    "AM-CONTRACTS-HISTORY": "v3 contracts, source adapter, immutable v2 decoder and historical database fixture",
    "AM-RUNTIME-STORE": "atomic writer fence, v2 continuation, drain and retirement checks",
    "AM-WEB": "source baselines and stored-version-specific renderers",
    "AM-SECURITY-RETENTION": "owner scope, integrity failure, retention, purge and tombstone behavior",
    "AM-RELEASE-QA": "verifier, target characterization, zero-diff validation and Gate handoff",
    "AM-PRODUCT-RESEARCH": "Slice 1 scope and rollout acceptance policy",
}
CRITERION_OWNERS = {
    "gate0-01-ownership-ledger": ["AM-ARCH"],
    "gate0-02-final-source-authority-and-durable-retention": ["AX-SOURCE"],
    "gate0-03-authoritative-parity-lock": ["AX-SOURCE", "AM-RELEASE-QA"],
    "gate0-04-offline-source-quality": ["AX-SOURCE", "AM-RELEASE-QA"],
    "gate0-05-visual-identity": ["AX-SOURCE", "AM-WEB"],
    "gate0-06-accepted-architecture-and-exact-contracts": ["AM-ARCH", "AM-CONTRACTS-HISTORY"],
    "gate0-07-target-characterization": ["AM-RELEASE-QA"],
    "gate0-08-zero-production-behavior-diff": ["AM-ARCH", "AM-RELEASE-QA"],
    "gate0-09-v2-compatibility-and-slice-1-work-plan": [
        "AM-CONTRACTS-HISTORY", "AM-RUNTIME-STORE", "AM-WEB", "AM-SECURITY-RETENTION",
    ],
    "gate0-10-handoff-and-authorization": ["AM-ARCH", "AM-RELEASE-QA"],
}
REQUIRED_TARGET_CASES = {
    "v1-routing", "research-v2-routing", "client-turn-replay", "missing-runtime-fail-closed",
    "owner-hiding-404", "artifact-corruption-fail-closed", "restart-read-without-scheduling",
    "purge-tombstone", "off-rollback", "historical-database-fixture-read",
}
REQUIRED_BASELINE_STATES = {
    "approval", "candidates", "clarify", "dag_or_executing", "idle", "paused", "plan", "text_report",
}
REQUIRED_VIEWPORTS = {
    "wide": {"width": 1440, "height": 900, "device_scale_factor": 1},
    "desktop": {"width": 1280, "height": 800, "device_scale_factor": 1},
    "mobile": {"width": 390, "height": 844, "device_scale_factor": 1},
}
CONTRACT_SOURCE_PATHS = {
    "AgentMesh": {
        "agentmesh/models.py", "agentmesh/research_orchestration/api.py",
        "agentmesh/research_orchestration/compiler.py", "agentmesh/research_orchestration/contracts.py",
        "agentmesh/research_orchestration/delivery.py", "agentmesh/research_orchestration/evidence.py",
        "agentmesh/research_orchestration/planning.py", "agentmesh/research_orchestration/result_projection.py",
        "agentmesh/research_orchestration/workflow.py", "agentmesh/routes/agent_runs.py",
        "agentmesh/routes/inbox.py", "agentmesh/routes/research.py", "agentmesh/store.py",
    },
    "ai-x": {
        "apps/agent-api/src/routes/control-planning.ts", "apps/agent-api/src/routes/control-tasks.ts",
        "apps/orchestrator-runtime/src/control/requirement-refinement-service.ts",
        "apps/orchestrator-runtime/src/control/task-workflow.ts",
        "apps/orchestrator-runtime/src/planners/plan-compiler.ts",
        "apps/orchestrator-runtime/src/planners/problem-graph-planner.ts",
        "apps/orchestrator-runtime/src/planners/routed-planner.ts",
        "apps/orchestrator-runtime/src/report/current-deliverable-service.ts",
        "apps/orchestrator-runtime/src/report/report-document-composer.ts", "database/control-plane.ts",
        "packages/api-contract/control-workflow.ts", "packages/api-contract/plan.ts",
        "packages/api-contract/research-deliverable.ts", "schemas/current-execution-plan.schema.json",
        "schemas/current-plan-candidates.schema.json",
        "schemas/deliverables/competitive-analysis-report.schema.json", "schemas/problem-graph.schema.json",
        "schemas/report-document.schema.json", "schemas/report-review.schema.json",
        "schemas/research-task-v2.schema.json",
    },
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def git(source: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    result = subprocess.run(
        ("git", *args), cwd=source, input=input_bytes, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout


def byte_sorted(values: list[str] | set[str] | tuple[str, ...]) -> list[str]:
    return sorted(values, key=lambda value: value.encode("utf-8"))


def validate_relative_path(value: str) -> None:
    require(bool(value), "empty path is forbidden")
    require(unicodedata.normalize("NFC", value) == value, f"path is not NFC: {value}")
    path = PurePosixPath(value)
    require(value == path.as_posix(), f"path is not normalized POSIX: {value}")
    require(not path.is_absolute(), f"absolute path is forbidden: {value}")
    require(".." not in path.parts, f"parent traversal is forbidden: {value}")


def resolve_commit(source: Path, revision: str) -> str:
    return git(source, "rev-parse", "--verify", f"{revision}^{{commit}}").decode().strip()


def read_tree(source: Path, revision: str) -> dict[str, dict[str, Any]]:
    raw = git(source, "ls-tree", "-r", "-z", "--full-tree", revision)
    parsed: list[tuple[str, str, str]] = []
    casefolded: dict[str, str] = {}
    for record in filter(None, raw.split(b"\0")):
        metadata, raw_path = record.split(b"\t", 1)
        mode_raw, kind_raw, oid_raw = metadata.split(b" ", 2)
        path = raw_path.decode("utf-8", errors="strict")
        validate_relative_path(path)
        folded = path.casefold()
        require(folded not in casefolded, f"case-fold collision: {casefolded.get(folded)} / {path}")
        casefolded[folded] = path
        mode, kind, oid = mode_raw.decode(), kind_raw.decode(), oid_raw.decode()
        require(kind == "blob", f"unsupported Git object at {path}: {kind}")
        require(mode in {"100644", "100755"}, f"unsupported Git mode at {path}: {mode}")
        parsed.append((path, mode, oid))
    paths = [item[0] for item in parsed]
    require(paths == byte_sorted(paths), "Git tree is not bytewise sorted")

    batch_input = "".join(f"{oid}\n" for _, _, oid in parsed).encode("ascii")
    stream = io.BytesIO(git(source, "cat-file", "--batch", input_bytes=batch_input))
    tree: dict[str, dict[str, Any]] = {}
    for path, mode, oid in parsed:
        header = stream.readline().decode("ascii").strip().split()
        require(len(header) == 3, f"invalid cat-file header: {path}")
        actual_oid, kind, size_raw = header
        require((actual_oid, kind) == (oid, "blob"), f"cat-file identity mismatch: {path}")
        size = int(size_raw)
        value = stream.read(size)
        require(len(value) == size and stream.read(1) == b"\n", f"short cat-file read: {path}")
        tree[path] = {
            "bytes": value, "git_blob": oid, "mode": mode,
            "sha256": sha256(value), "size_bytes": size,
        }
    require(stream.read() == b"", "unexpected cat-file output")
    return tree


def manifest_sha256(paths: list[str] | set[str], tree: dict[str, dict[str, Any]]) -> str:
    lines = []
    for path in byte_sorted(paths):
        item = tree[path]
        lines.append(f"{item['mode']} {item['sha256']} {item['size_bytes']}  {path}\n")
    return sha256("".join(lines).encode("utf-8"))


def legacy_manifest(paths: list[str] | set[str], tree: dict[str, dict[str, Any]]) -> str:
    value = "".join(f"{tree[path]['sha256']}  {path}\n" for path in byte_sorted(paths)).encode()
    return sha256(value)


def category_for(path: str) -> str | None:
    if path == FREEZE_MANIFEST_PATH:
        return "source_freeze_metadata"
    if path == "docs/development/research-orchestration-migration-guide.md":
        return "migration_guide"
    if path in {".env.example", ".gitignore", "package.json", "pnpm-lock.yaml", "tsconfig.json"}:
        return "dependency_config_provenance"
    if path.startswith("apps/web/src/") or path in EXACT_INCLUDED and path.startswith("apps/web/"):
        return "workbench_ui"
    categories = (
        ("apps/agent-api/src/", "source_api"),
        ("apps/orchestrator-runtime/src/", "source_runtime"),
        ("database/", "source_database"), ("evaluations/skills/", "evaluation_contracts"),
        ("knowledge-base/", "knowledge_assets"), ("orchestrator/", "registries_and_resources"),
        ("packages/api-contract/", "api_contracts"), ("schemas/", "canonical_schemas"),
        ("skills/", "skill_bundles"), ("tests/", "source_tests"), ("tools/", "tool_bundles"),
    )
    for prefix, category in categories:
        if path.startswith(prefix):
            return category
    if path.startswith(LAB_PREFIXES):
        return "lab_source"
    if path in {"external-tools/README.md", "scripts/current-real-smoke.ts", "scripts/start-labs.mjs"}:
        return "supporting_sources"
    require(path not in EXACT_INCLUDED and not path.startswith(INCLUDED_PREFIXES), f"uncategorized path: {path}")
    return None


def prohibited_reason(path: str) -> str | None:
    parts = PurePosixPath(path).parts
    basename = parts[-1]
    lowered = basename.casefold()
    if basename == ".env" or basename.startswith(".env.bak"):
        return "environment_secret_file"
    if lowered in {"cookie.json", "cookies.json", "credential.json", "credentials.json", "token.json", "tokens.json"}:
        return "credential_material"
    if {"node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next"}.intersection(parts):
        return "generated_or_dependency_directory"
    if parts[0] in {".logs", ".pids", "references", "wiki", ".worktrees"}:
        return "forbidden_root"
    if path.startswith("run-inputs/"):
        return "runtime_input"
    if path.startswith("run-workspaces/") and path != "run-workspaces/README.md":
        return "runtime_workspace"
    if path.startswith("audit/gold-runs/") and path != "audit/gold-runs/README.md":
        return "gold_run_material"
    if path.startswith("external-tools/users-research-all/"):
        return "out_of_scope_user_research_tool"
    if basename in {".harness-active", "harness-progress.txt", "harness-tasks.json", "harness-tasks.json.bak"}:
        return "harness_runtime_state"
    if basename == ".DS_Store":
        return "os_metadata"
    if lowered.endswith((".sqlite", ".sqlite3", ".db", ".wal", ".shm", ".log", ".tmp")):
        return "runtime_or_temporary_file"
    return None


def build_inventory(tree: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    included, excluded = [], []
    for path in byte_sorted(set(tree)):
        reason = prohibited_reason(path)
        require(reason is None, f"prohibited path ({reason}): {path}")
        item = tree[path]
        common = {
            "approval": "approved_snapshot", "file_kind": "regular_blob", "git_blob": item["git_blob"],
            "mode": item["mode"], "path": path, "sha256": item["sha256"],
            "size_bytes": item["size_bytes"], "source_status": "snapshot_committed",
        }
        category = category_for(path)
        if category:
            included.append({**common, "category": category, "disposition": "included"})
        else:
            exclusion = "planning_only_not_ai_x_parity" if path in PLANNING_ONLY_EXCLUSIONS else "outside_selected_parity_scope"
            excluded.append({**common, "disposition": "excluded", "reason": exclusion})
    included_paths = [item["path"] for item in included]
    excluded_paths = [item["path"] for item in excluded]
    require(not set(included_paths) & set(excluded_paths), "inventory overlap")
    require(set(included_paths) | set(excluded_paths) == set(tree), "inventory is incomplete")
    categories: dict[str, list[str]] = {}
    for item in included:
        categories.setdefault(item["category"], []).append(item["path"])
    category_manifests = {
        category: {"file_count": len(paths), "manifest_sha256": manifest_sha256(paths, tree)}
        for category, paths in sorted(categories.items())
    }
    return (
        {"category_manifests": category_manifests, "file_count": len(included), "files": included,
         "manifest_sha256": manifest_sha256(included_paths, tree)},
        {"exact_file_count": len(excluded), "files": excluded,
         "manifest_sha256": manifest_sha256(excluded_paths, tree)},
    )

class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate keys."""


def _unique_mapping(loader: UniqueKeyLoader, node: yaml.nodes.MappingNode, deep: bool = False) -> Any:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        require(key not in mapping, f"duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def yaml_blob(tree: dict[str, dict[str, Any]], path: str) -> dict[str, Any]:
    value = yaml.load(tree[path]["bytes"].decode("utf-8"), Loader=UniqueKeyLoader)
    require(isinstance(value, dict), f"expected YAML mapping: {path}")
    return value


def json_blob(tree: dict[str, dict[str, Any]], path: str) -> dict[str, Any]:
    value = json.loads(tree[path]["bytes"])
    require(isinstance(value, dict), f"expected JSON object: {path}")
    return value


def string_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    require(isinstance(value, list) and all(isinstance(item, str) for item in value), f"invalid list: {label}")
    require(len(value) == len(set(value)), f"duplicate values: {label}")
    return byte_sorted(value)


def ensure_resource(path: str | None, tree: dict[str, dict[str, Any]], included: set[str], label: str) -> None:
    if path is None:
        return
    require(isinstance(path, str), f"invalid resource path: {label}")
    validate_relative_path(path)
    require(path in tree, f"missing resource for {label}: {path}")
    require(path in included, f"resource is not included for {label}: {path}")


def css_properties(value: bytes, selector: str) -> dict[str, str]:
    text = value.decode("utf-8")
    match = re.search(re.escape(selector) + r"\s*\{(?P<body>.*?)\}", text, flags=re.DOTALL)
    require(match is not None, f"missing CSS selector: {selector}")
    result: dict[str, str] = {}
    for name, raw_value in re.findall(r"(--[A-Za-z0-9_-]+)\s*:\s*([^;]+);", match.group("body")):
        require(name not in result, f"duplicate CSS property: {selector} {name}")
        result[name] = raw_value.strip()
    require(bool(result), f"no CSS properties: {selector}")
    return dict(sorted(result.items()))


def derive_capabilities(
    tree: dict[str, dict[str, Any]], included_section: dict[str, Any], freeze: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    included = {item["path"] for item in included_section["files"]}
    skill_registry = yaml_blob(tree, "orchestrator/skill-registry.yaml")
    tool_registry = yaml_blob(tree, "orchestrator/tool-registry.yaml")
    deliverable_registry = yaml_blob(tree, "orchestrator/deliverable-registry.yaml")
    decision_graph = yaml_blob(tree, "orchestrator/decision-graph.yaml")
    evidence_policy = yaml_blob(tree, "orchestrator/evidence-policy.yaml")

    raw_tools = tool_registry.get("tools")
    require(isinstance(raw_tools, list), "Tool registry must contain a list")
    tools, tool_ids = [], set()
    for raw in raw_tools:
        require(isinstance(raw, dict), "invalid Tool entry")
        tool_id = raw.get("id")
        require(isinstance(tool_id, str) and tool_id not in tool_ids, f"duplicate/invalid Tool: {tool_id}")
        tool_ids.add(tool_id)
        manifest_path = raw.get("path")
        ensure_resource(manifest_path, tree, included, f"Tool {tool_id} manifest")
        manifest = yaml_blob(tree, manifest_path)
        for key in ("id", "adapter_type", "auth_required", "risk_level"):
            require(manifest.get(key) == raw.get(key), f"Tool registry/manifest {key} mismatch: {tool_id}")
        for key in ("input_schema", "output_schema"):
            ensure_resource(manifest.get(key), tree, included, f"Tool {tool_id} {key}")
        tools.append({
            "adapter": raw.get("adapter_type"), "auth_required": raw.get("auth_required"),
            "base_url_env": manifest.get("base_url_env"), "entrypoint": manifest.get("entrypoint"),
            "id": tool_id, "input_schema": manifest.get("input_schema"), "manifest_path": manifest_path,
            "output_schema": manifest.get("output_schema"), "risk_level": raw.get("risk_level"),
            "status": raw.get("status"), "tier": raw.get("tier"),
        })
    tools.sort(key=lambda item: item["id"].encode())

    raw_skills = skill_registry.get("skills")
    require(isinstance(raw_skills, list), "Skill registry must contain a list")
    skills, skill_ids = [], set()
    for raw in raw_skills:
        require(isinstance(raw, dict), "invalid Skill entry")
        skill_id = raw.get("id")
        require(isinstance(skill_id, str) and skill_id not in skill_ids, f"duplicate/invalid Skill: {skill_id}")
        skill_ids.add(skill_id)
        entry = raw.get("entry") or raw.get("path")
        require(isinstance(entry, str) and entry.endswith(".md"), f"Skill entry is not a file: {skill_id}")
        ensure_resource(entry, tree, included, f"Skill {skill_id} entry")
        required = string_list(raw.get("required_tools"), f"Skill {skill_id} required Tools")
        optional = string_list(raw.get("optional_tools"), f"Skill {skill_id} optional Tools")
        require(not set(required) & set(optional), f"Skill Tool tier overlap: {skill_id}")
        require((set(required) | set(optional)).issubset(tool_ids), f"unknown Tool in Skill: {skill_id}")
        schemas = {"input": raw.get("input_schema"), "output": raw.get("output_schema"), "payload": raw.get("payload_schema")}
        for key, path in schemas.items():
            ensure_resource(path, tree, included, f"Skill {skill_id} {key} schema")
        skills.append({
            "entry_path": entry, "id": skill_id,
            "input_roles": string_list(raw.get("inputs"), f"Skill {skill_id} inputs"),
            "multiple_visual_inputs": string_list(raw.get("multiple_visual_inputs"), f"Skill {skill_id} multiple visuals"),
            "optional_tools": optional, "required_tools": required, "risk_level": raw.get("risk_level"),
            "schemas": schemas, "status": raw.get("status"),
            "task_types": string_list(raw.get("task_types"), f"Skill {skill_id} task types"),
            "visual_inputs": string_list(raw.get("visual_inputs"), f"Skill {skill_id} visuals"),
        })
    skills.sort(key=lambda item: item["id"].encode())

    policies = evidence_policy.get("policies")
    raw_deliverables = deliverable_registry.get("deliverables")
    require(isinstance(policies, list) and isinstance(raw_deliverables, list), "invalid Deliverable sources")
    deliverables, deliverable_ids, task_owners = [], set(), {}
    for raw in raw_deliverables:
        require(isinstance(raw, dict), "invalid Deliverable entry")
        deliverable_id = raw.get("id")
        require(isinstance(deliverable_id, str) and deliverable_id not in deliverable_ids, f"duplicate Deliverable: {deliverable_id}")
        deliverable_ids.add(deliverable_id)
        task_types = string_list(raw.get("task_types"), f"Deliverable {deliverable_id} task types")
        for task_type in task_types:
            require(task_type not in task_owners, f"multiple Deliverables for task type: {task_type}")
            task_owners[task_type] = deliverable_id
        template_id = raw.get("report_template")
        require(isinstance(template_id, str), f"missing template id: {deliverable_id}")
        resources = {
            "evidence_policy_path": "orchestrator/evidence-policy.yaml", "payload_schema": raw.get("payload_schema"),
            "review_rubric": raw.get("review_rubric"), "synthesis_prompt": raw.get("synthesis_prompt"),
            "template_path": f"orchestrator/report-templates/{template_id}.yaml",
        }
        for key, path in resources.items():
            ensure_resource(path, tree, included, f"Deliverable {deliverable_id} {key}")
        require(yaml_blob(tree, resources["template_path"]).get("id") == template_id, f"template id mismatch: {deliverable_id}")
        policy_id = raw.get("evidence_policy")
        for task_type in task_types:
            matching = [
                policy for policy in policies
                if isinstance(policy, dict) and policy.get("task_type") == task_type
                and policy.get("deliverable_type") == deliverable_id
                and any(isinstance(req, dict) and req.get("id") == policy_id for req in policy.get("requirements", []))
            ]
            require(len(matching) == 1, f"evidence policy mismatch: {deliverable_id}/{task_type}")
        deliverables.append({
            "aliases": string_list(raw.get("aliases"), f"Deliverable {deliverable_id} aliases"),
            "envelope_version": raw.get("envelope_version"), "evidence_policy_id": policy_id,
            "id": deliverable_id, "resources": resources, "status": raw.get("status"),
            "task_types": task_types, "template_id": template_id,
        })
    deliverables.sort(key=lambda item: item["id"].encode())

    raw_nodes = decision_graph.get("nodes")
    require(isinstance(raw_nodes, list), "Decision Graph must contain nodes")
    nodes, node_ids = [], set()
    for raw in raw_nodes:
        require(isinstance(raw, dict), "invalid Decision Node")
        node_id, tier = raw.get("key"), raw.get("tier")
        require(isinstance(node_id, str) and node_id not in node_ids, f"duplicate Decision Node: {node_id}")
        require(tier in {"core", "optional"}, f"invalid Decision Node tier: {node_id}")
        node_ids.add(node_id)
        nodes.append({
            "applies_to": string_list(raw.get("applies_to"), f"Decision Node {node_id} applies_to"),
            "id": node_id, "required": tier == "core", "tier": tier,
        })
    nodes.sort(key=lambda item: item["id"].encode())

    skill_types = {task for item in skills if item["status"] == "active" for task in item["task_types"]}
    deliverable_types = {task for item in deliverables if item["status"] == "active" for task in item["task_types"]}
    decision_types = {task for item in nodes for task in item["applies_to"]}
    require(skill_types == deliverable_types == decision_types, "task type sets disagree")
    task_types = byte_sorted(skill_types)

    labs = []
    for tool in [item for item in tools if item["adapter"] == "rest_json" and item["id"].endswith("-lab")]:
        lab_id, root = tool["id"], f"external-tools/{tool['id']}"
        paths = [path for path in tree if path.startswith(f"{root}/")]
        require(paths and set(paths).issubset(included), f"Lab root not fully included: {lab_id}")
        env_path = f"{root}/.env.example"
        require(env_path in tree, f"missing Lab env declaration: {lab_id}")
        env = tree[env_path]["bytes"].decode("utf-8")
        server_match, web_match = re.search(r"(?m)^SERVER_PORT=(\d+)$", env), re.search(r"(?m)^WEB_PORT=(\d+)$", env)
        require(server_match is not None and web_match is not None, f"invalid Lab ports: {lab_id}")
        server_port, web_port = int(server_match.group(1)), int(web_match.group(1))
        config_path = f"{root}/apps/server/src/config/env.ts"
        require(config_path in tree, f"missing Lab server config: {lab_id}")
        require(
            f"intFromEnv('SERVER_PORT', {server_port})" in tree[config_path]["bytes"].decode("utf-8"),
            f"Lab server port mismatch: {lab_id}",
        )
        labs.append({
            "auth_required": tool["auth_required"], "base_url_env": tool["base_url_env"],
            "endpoint": tool["entrypoint"], "file_count": len(paths), "id": lab_id,
            "manifest_path": tool["manifest_path"], "manifest_sha256": manifest_sha256(paths, tree),
            "risk_level": tool["risk_level"], "server_port": server_port, "source_root": root,
            "status": tool["status"], "web_port": web_port,
        })
    labs.sort(key=lambda item: item["id"].encode())

    all_paths = set(tree)
    families = {
        "schemas": {path for path in all_paths if path.startswith("schemas/") and path.endswith(".schema.json")},
        "prompts": {path for path in all_paths if path.startswith("orchestrator/prompts/") and path.endswith(".md")},
        "rubrics": {path for path in all_paths if path.startswith("orchestrator/report-rubrics/") and path.endswith(".yaml")},
        "templates": {path for path in all_paths if path.startswith("orchestrator/report-templates/") and path.endswith(".yaml")},
        "knowledge_markdown": {path for path in all_paths if path.startswith("knowledge-base/") and path.endswith(".md")},
        "skill_bodies": {
            path for path in all_paths if path.endswith("/SKILL.md")
            and path.startswith(("knowledge-base/skills/", "skills/", "orchestrator/research-orchestrator/"))
        },
        "references": {
            path for path in all_paths
            if re.fullmatch(r"knowledge-base/skills/[^/]+/references/[^/]+\.md", path)
        },
        "registries_and_policies": set(REGISTRY_PATHS),
    }
    resource_families = {name: byte_sorted(paths) for name, paths in families.items()}
    for name, paths in resource_families.items():
        require(set(paths).issubset(included), f"resource family not fully included: {name}")

    references = resource_families["references"]
    reference_hash = legacy_manifest(references, tree)
    migration_path = "docs/development/research-orchestration-migration-guide.md"
    integrity = {
        "migration_guide": {"path": migration_path, "sha256": tree[migration_path]["sha256"],
                            "size_bytes": tree[migration_path]["size_bytes"]},
        "required_references": {
            "file_count": len(references),
            "manifest_algorithm": "sha256 lines '<file-sha256>  <repository-relative-path>\\n' in bytewise path order",
            "manifest_sha256": reference_hash, "paths": references,
        },
    }
    source_integrity = freeze.get("integrity", {})
    require(source_integrity.get("requiredReferenceManifest", {}).get("hash") == reference_hash,
            "source freeze reference manifest mismatch")
    require(source_integrity.get("migrationGuide", {}).get("hash") == tree[migration_path]["sha256"],
            "source freeze migration guide mismatch")

    counts = {
        "canonical_schemas": len(resource_families["schemas"]), "decision_nodes": len(nodes),
        "deliverables": len(deliverables), "labs": len(labs), "prompts": len(resource_families["prompts"]),
        "rubrics": len(resource_families["rubrics"]), "skills": len(skills), "task_types": len(task_types),
        "templates": len(resource_families["templates"]),
        "tools_active": sum(item["status"] == "active" for item in tools),
        "tools_draft": sum(item["status"] == "draft" for item in tools), "tools_total": len(tools),
    }
    source_counts, source_assets = freeze.get("registryCounts", {}), freeze.get("assetCounts", {})
    expected_counts = {
        "skills": counts["skills"], "tools": counts["tools_total"], "deliverables": counts["deliverables"],
        "decisionNodes": counts["decision_nodes"], "labs": counts["labs"],
    }
    require(all(source_counts.get(key) == value for key, value in expected_counts.items()), "source freeze registry counts mismatch")
    require(source_assets.get("requiredReferences") == len(references), "source freeze reference count mismatch")
    require(source_assets.get("knowledgeMarkdownFiles") == len(resource_families["knowledge_markdown"]),
            "source freeze knowledge count mismatch")
    require(source_assets.get("schemaFiles") == len(resource_families["schemas"]), "source freeze schema count mismatch")

    theme_path, report_path = "apps/web/src/theme.css", "apps/web/src/reporting/report-print.css"
    normalized = {
        "capability_counts": counts, "decision_nodes": nodes, "deliverables": deliverables, "labs": labs,
        "registry_sources": {
            path: {"sha256": tree[path]["sha256"], "size_bytes": tree[path]["size_bytes"]}
            for path in REGISTRY_PATHS
        },
        "resource_families": resource_families, "skills": skills, "task_types": task_types, "tools": tools,
        "ui_tokens": {
            "report": css_properties(tree[report_path]["bytes"], ".report-document"),
            "report_path": report_path, "report_sha256": tree[report_path]["sha256"],
            "theme": css_properties(tree[theme_path]["bytes"], ":root"),
            "theme_path": theme_path, "theme_sha256": tree[theme_path]["sha256"],
        },
    }
    return normalized, integrity

def strict_json_bytes(raw: bytes, label: str, *, require_canonical: bool = True) -> Any:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            require(key not in result, f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON in {label}: {exc}") from exc
    if require_canonical:
        canonical = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
        require(raw == canonical, f"JSON is not canonical: {label}")
    return value


def strict_json_file(path: Path, root: Path | None = None) -> Any:
    label = path.as_posix() if root is None else path.relative_to(root).as_posix()
    require(path.is_file() and not path.is_symlink(), f"missing regular JSON file: {label}")
    return strict_json_bytes(path.read_bytes(), label)


def source_state(source: Path, revision: str) -> dict[str, Any]:
    commit = resolve_commit(source, revision)
    tree_hash = git(source, "show", "-s", "--format=%T", commit).decode().strip()
    require(commit == DEFAULT_REVISION, "unexpected source snapshot commit")
    require(tree_hash == "ca63e2fdb4c3fcff0f50c8095a1497f8db4cdd12", "unexpected source snapshot tree")
    parents = git(source, "show", "-s", "--format=%P", commit).decode().strip().split()
    require(len(parents) == 1, "snapshot must have one parent")
    parent = parents[0]
    parent_tree = git(source, "show", "-s", "--format=%T", parent).decode().strip()
    tree = read_tree(source, commit)
    require(FREEZE_MANIFEST_PATH in tree, "freeze manifest missing")
    freeze = strict_json_bytes(tree[FREEZE_MANIFEST_PATH]["bytes"], FREEZE_MANIFEST_PATH, require_canonical=False)
    require(isinstance(freeze, dict), "freeze manifest must be an object")
    manifest_source = freeze.get("source", {})
    approved_commit = manifest_source.get("approvedIntegratedSourceCommit")
    approved_tree = manifest_source.get("approvedContentTree", {}).get("hash")
    base_commit = manifest_source.get("baseCommit")
    require(parent == approved_commit, "snapshot parent/approved content commit mismatch")
    require(parent_tree == approved_tree, "approved content tree mismatch")
    require(git(source, "merge-base", "--is-ancestor", base_commit, commit) == b"", "base is not an ancestor")
    changed = git(source, "diff-tree", "--no-commit-id", "--name-status", "-r", parent, commit).decode().splitlines()
    require(changed == [f"M\t{FREEZE_MANIFEST_PATH}"], "snapshot must only modify the freeze manifest")
    included, excluded = build_inventory(tree)
    normalized, integrity = derive_capabilities(tree, included, freeze)
    metadata = {
        "approved_content_commit": approved_commit,
        "approved_content_tree": approved_tree,
        "base_commit": base_commit,
        "branch_label": SOURCE_BRANCH_LABEL,
        "commit_subject": git(source, "show", "-s", "--format=%s", commit).decode().strip(),
        "freeze_manifest": {
            "blob_sha256": tree[FREEZE_MANIFEST_PATH]["sha256"],
            "git_blob": tree[FREEZE_MANIFEST_PATH]["git_blob"],
            "path": FREEZE_MANIFEST_PATH,
            "schema_version": freeze.get("schemaVersion"),
            "size_bytes": tree[FREEZE_MANIFEST_PATH]["size_bytes"],
        },
        "inventory_commit": commit,
        "inventory_tree": tree_hash,
        "manifest_relationship": {
            "approved_content_commit": approved_commit,
            "approved_content_tree": approved_tree,
            "change_path": FREEZE_MANIFEST_PATH,
            "change_type": "modified",
            "snapshot_parent_equals_approved_content_commit": True,
        },
        "repository": SOURCE_REPOSITORY,
        "snapshot_commit": commit,
        "snapshot_parent": parent,
        "snapshot_tree": tree_hash,
    }
    return {
        "excluded": excluded,
        "included": included,
        "integrity": integrity,
        "normalized": normalized,
        "source": metadata,
        "tree": tree,
        "tree_manifest": {
            "file_count": len(tree),
            "manifest_sha256": manifest_sha256(set(tree), tree),
            "modes": ["100644", "100755"],
        },
    }


def file_record(path: Path, relative_path: str) -> dict[str, Any]:
    validate_relative_path(relative_path)
    require(path.is_file() and not path.is_symlink(), f"missing regular evidence file: {relative_path}")
    value = path.read_bytes()
    return {"path": relative_path, "sha256": sha256(value), "size_bytes": len(value)}


def validate_bundle_file(project_root: Path) -> dict[str, Any]:
    bundle_path = project_root / SOURCE_BUNDLE_PATH
    attestation_path = project_root / SOURCE_BUNDLE_ATTESTATION
    attestation = strict_json_file(attestation_path, project_root)
    record = file_record(bundle_path, SOURCE_BUNDLE_PATH.as_posix())
    require(record["sha256"] == "bc498a854c0b60835036e87dfd576d37aa233c65833cdbde493a10504670369f", "bundle SHA-256 mismatch")
    require(record["size_bytes"] == 16185062, "bundle byte size mismatch")
    require(attestation.get("schema_version") == "agentmesh-ai-x-source-bundle-attestation-v1", "bundle attestation schema mismatch")
    require(attestation.get("source_repository") == SOURCE_REPOSITORY, "bundle repository mismatch")
    require(attestation.get("advertised_ref") == SOURCE_BUNDLE_REF, "bundle advertised-ref declaration mismatch")
    declared_record = {"bytes": record["size_bytes"], "path": record["path"], "sha256": record["sha256"]}
    require(attestation.get("bundle") == declared_record, "bundle attestation file record mismatch")
    require(attestation.get("bundle_verify") == {"complete_history": True, "result": "okay"}, "bundle verification declaration mismatch")
    require(
        attestation.get("restored")
        == {
            "commit": DEFAULT_REVISION,
            "fsck_full_strict": "passed",
            "tree": "ca63e2fdb4c3fcff0f50c8095a1497f8db4cdd12",
        },
        "bundle restore declaration mismatch",
    )
    runtime = attestation.get("runtime_loading", {})
    require(runtime.get("importable_python_package") is False and runtime.get("loaded_automatically") is False,
            "bundle must be excluded from runtime loading")
    heads = subprocess.run(
        ("git", "bundle", "list-heads", str(bundle_path)),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    require(heads.returncode == 0, f"git bundle list-heads failed: {heads.stderr.decode(errors='replace').strip()}")
    require(heads.stdout.decode().splitlines() == [f"{DEFAULT_REVISION} {SOURCE_BUNDLE_REF}"], "bundle advertised ref mismatch")
    return {
        "attestation": file_record(attestation_path, SOURCE_BUNDLE_ATTESTATION.as_posix()),
        **declared_record,
    }


@contextlib.contextmanager
def materialized_source_bundle(bundle_path: Path):
    with tempfile.TemporaryDirectory(prefix="agentmesh-ai-x-bundle-") as temporary:
        clone = Path(temporary) / "source"
        result = subprocess.run(
            ("git", "clone", "--mirror", str(bundle_path), str(clone)),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        require(result.returncode == 0, f"self-contained bundle clone failed: {result.stderr.decode(errors='replace').strip()}")
        git(clone, "fsck", "--full", "--strict")
        require(resolve_commit(clone, SOURCE_BUNDLE_REF) == DEFAULT_REVISION, "restored bundle commit mismatch")
        restored_tree = git(clone, "show", "-s", "--format=%T", DEFAULT_REVISION).decode().strip()
        require(restored_tree == "ca63e2fdb4c3fcff0f50c8095a1497f8db4cdd12", "restored bundle tree mismatch")
        yield clone


def validate_contract_sources(
    project_root: Path, source_tree: dict[str, dict[str, Any]], entries: Any
) -> list[dict[str, Any]]:
    require(isinstance(entries, list) and len(entries) == 33, "contract source list must contain exactly 33 entries")
    seen: set[tuple[str, str]] = set()
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        require(isinstance(entry, dict), "invalid contract source entry")
        repository, path = entry.get("repository"), entry.get("path")
        require(repository in CONTRACT_SOURCE_PATHS and isinstance(path, str), "unknown contract source repository/path")
        validate_relative_path(path)
        key = (repository, path)
        require(key not in seen, f"duplicate contract source: {repository}:{path}")
        seen.add(key)
        require(path in CONTRACT_SOURCE_PATHS[repository], f"undeclared contract source: {repository}:{path}")
        expected_ref = DEFAULT_REVISION if repository == "ai-x" else TARGET_BASE_COMMIT
        require(entry.get("ref") == expected_ref, f"contract source ref mismatch: {repository}:{path}")
        if repository == "ai-x":
            require(path in source_tree, f"source contract blob missing: {path}")
            actual = source_tree[path]["bytes"]
        else:
            actual = git(project_root, "show", f"{TARGET_BASE_COMMIT}:{path}")
        require(entry.get("sha256") == sha256(actual), f"contract source hash mismatch: {repository}:{path}")
        normalized.append(entry)
    expected = {(repository, path) for repository, paths in CONTRACT_SOURCE_PATHS.items() for path in paths}
    require(seen == expected, "contract source exact set mismatch")
    return sorted(normalized, key=lambda item: (item["repository"].encode(), item["path"].encode()))


def validate_contract_fixtures(project_root: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    root = project_root / FIXTURE_ROOT
    manifest_path = root / "manifest.json"
    manifest = strict_json_file(manifest_path, project_root)
    require(manifest.get("manifest_version") == "ai-x-agentmesh-gate0-fixture-manifest-v1", "fixture manifest version mismatch")
    require(manifest.get("characterization_only") is True and manifest.get("executable_tests") is False,
            "fixture execution classification mismatch")
    require(manifest.get("source", {}).get("logical_repository") == SOURCE_REPOSITORY, "fixture source repository mismatch")
    require(manifest.get("source", {}).get("commit") == DEFAULT_REVISION, "fixture source commit mismatch")
    require(manifest.get("source", {}).get("tree") == snapshot["source"]["snapshot_tree"], "fixture source tree mismatch")
    require(manifest.get("target", {}).get("logical_repository") == TARGET_REPOSITORY, "fixture target repository mismatch")
    require(manifest.get("target", {}).get("base_commit") == TARGET_BASE_COMMIT, "fixture target commit mismatch")
    require(manifest.get("target", {}).get("tree") == TARGET_BASE_TREE, "fixture target tree mismatch")
    declared = manifest.get("files")
    require(isinstance(declared, list), "fixture files must be a list")
    paths = [entry.get("path") for entry in declared if isinstance(entry, dict)]
    require(len(paths) == len(declared) == len(set(paths)), "duplicate or invalid fixture path")
    require(set(paths) == set(REQUIRED_FIXTURES), "fixture exact path set mismatch")
    actual = {path.name for path in root.iterdir() if path.is_file()}
    require(actual == {"manifest.json", *REQUIRED_FIXTURES}, "fixture directory contains omitted or undeclared files")
    ids: set[str] = set()
    records = []
    for entry in declared:
        relative = entry["path"]
        validate_relative_path(relative)
        require(len(PurePosixPath(relative).parts) == 1, f"fixture path must be single-level: {relative}")
        payload_path = root / relative
        payload = strict_json_file(payload_path, project_root)
        fixture_id = entry.get("fixture_id")
        require(isinstance(fixture_id, str) and fixture_id and fixture_id not in ids, f"duplicate/invalid fixture ID: {fixture_id}")
        ids.add(fixture_id)
        require(payload.get("fixture_id") == fixture_id, f"top-level fixture ID mismatch: {relative}")
        require(payload.get("fixture_version") == "ai-x-agentmesh-gate0-characterization-v1", f"fixture version mismatch: {relative}")
        require(payload.get("normalization_profile") == "gate0-semantic-normalization-v1", f"normalization profile mismatch: {relative}")
        record = file_record(payload_path, (FIXTURE_ROOT / relative).as_posix())
        require(record["sha256"] == entry.get("sha256") and record["size_bytes"] == entry.get("bytes"),
                f"fixture hash/size mismatch: {relative}")
        records.append({**record, "fixture_id": fixture_id})
    historical = strict_json_file(root / "v2-historical-read-compatibility.json", project_root)
    manifest_policy = manifest.get("schema_ids", {}).get("target", {}).get("canonical_historical_identity_policy")
    require(manifest_policy == HISTORICAL_IDENTITY_POLICY, "fixture manifest historical identity policy mismatch")
    require(historical.get("canonical_historical_identity_policy") == HISTORICAL_IDENTITY_POLICY,
            "historical fixture identity policy mismatch")
    contract_sources = validate_contract_sources(project_root, snapshot["tree"], manifest.get("contract_source_files"))
    return {
        "contract_source_count": len(contract_sources),
        "files": sorted(records, key=lambda item: item["path"].encode()),
        "manifest": file_record(manifest_path, (FIXTURE_ROOT / "manifest.json").as_posix()),
        "status": "valid_characterization_only",
    }


def validate_history_fixture(project_root: Path) -> dict[str, Any]:
    root = project_root / HISTORY_ROOT
    manifest_path = root / "manifest.json"
    manifest = strict_json_file(manifest_path, project_root)
    require(manifest.get("schema_version") == "agentmesh-research-v2-history-fixture-manifest-v1", "history manifest schema mismatch")
    require(manifest.get("origin") == {
        "base_commit": TARGET_BASE_COMMIT,
        "base_tree": TARGET_BASE_TREE,
        "repository": TARGET_REPOSITORY,
    }, "history fixture origin mismatch")
    require(manifest.get("canonical_historical_identity_policy") == HISTORICAL_IDENTITY_POLICY,
            "history fixture identity policy mismatch")
    expected_names = {"SHA256SUMS", "attestation.json", "characterize_v2_history.py", "manifest.json", "research-v2-history.sqlite3"}
    actual_names = {path.name for path in root.iterdir() if path.is_file()}
    require(actual_names == expected_names, "history fixture contains omitted or undeclared files")
    entries = manifest.get("files")
    require(isinstance(entries, list) and {entry.get("path") for entry in entries} == expected_names - {"manifest.json"},
            "history fixture manifest exact set mismatch")
    for entry in entries:
        path = root / entry["path"]
        record = file_record(path, (HISTORY_ROOT / entry["path"]).as_posix())
        require(record["sha256"] == entry.get("sha256") and record["size_bytes"] == entry.get("bytes"),
                f"history evidence hash/size mismatch: {entry['path']}")
    sums: dict[str, str] = {}
    for line in (root / "SHA256SUMS").read_text().splitlines():
        parts = line.split("  ", 1)
        require(len(parts) == 2 and re.fullmatch(r"[0-9a-f]{64}", parts[0]) is not None, "invalid SHA256SUMS line")
        require(parts[1] not in sums, "duplicate SHA256SUMS path")
        sums[parts[1]] = parts[0]
    require(set(sums) == {"attestation.json", "characterize_v2_history.py", "research-v2-history.sqlite3"},
            "history SHA256SUMS exact set mismatch")
    for name, digest in sums.items():
        require(sha256((root / name).read_bytes()) == digest, f"history SHA256SUMS mismatch: {name}")
    attestation = strict_json_file(root / "attestation.json", project_root)
    require(attestation.get("overall") == "passed", "history attestation did not pass")
    require(attestation.get("sanitization", {}).get("passed") is True, "history fixture sanitization failed")
    require(attestation.get("execution", {}).get("external_provider_calls") == 0, "history evidence used a Provider")
    require(attestation.get("execution", {}).get("network_used") is False, "history evidence used network")
    require(attestation.get("source", {}).get("target_base") == TARGET_BASE_COMMIT, "history target base mismatch")
    fixture = root / "research-v2-history.sqlite3"
    require(attestation.get("fixture", {}).get("sha256") == sha256(fixture.read_bytes()), "history fixture attested hash mismatch")
    require(attestation.get("fixture", {}).get("bytes") == fixture.stat().st_size, "history fixture attested size mismatch")
    require(not (root / "research-v2-history.sqlite3-wal").exists() and not (root / "research-v2-history.sqlite3-shm").exists(),
            "history fixture WAL/SHM companion is forbidden")
    connection = sqlite3.connect(f"file:{fixture}?mode=ro", uri=True)
    try:
        require(connection.execute("PRAGMA integrity_check").fetchone() == ("ok",), "history fixture SQLite integrity failure")
    finally:
        connection.close()
    checks = attestation.get("checks", {})
    case_map = {
        "owner-hiding-404": checks.get("foreign_owner_hidden", {}).get("passed") is True,
        "artifact-corruption-fail-closed": checks.get("integrity_corruption_rejected", {}).get("passed") is True,
        "restart-read-without-scheduling": checks.get("restart_read", {}).get("passed") is True
        and checks.get("history_projection_no_mutation_actions", {}).get("passed") is True,
        "purge-tombstone": checks.get("purge_tombstones", {}).get("passed") is True,
        "historical-database-fixture-read": checks.get("owner_read", {}).get("passed") is True,
    }
    return {
        "attestation": file_record(root / "attestation.json", (HISTORY_ROOT / "attestation.json").as_posix()),
        "characterized_target_cases": byte_sorted({case for case, passed in case_map.items() if passed}),
        "fixture": file_record(fixture, (HISTORY_ROOT / fixture.name).as_posix()),
        "manifest": file_record(manifest_path, (HISTORY_ROOT / "manifest.json").as_posix()),
        "status": "valid_sanitized_historical_fixture",
    }


def png_dimensions(raw: bytes, label: str) -> tuple[int, int]:
    require(raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) >= 24, f"invalid PNG signature: {label}")
    require(raw[12:16] == b"IHDR", f"missing PNG IHDR: {label}")
    return struct.unpack(">II", raw[16:24])


def validate_browser_baseline(project_root: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    root = project_root / BASELINE_ROOT
    if not root.exists():
        return {
            "available": False,
            "missing_state_viewport_pairs": [
                f"{state}/{viewport}" for state in byte_sorted(REQUIRED_BASELINE_STATES)
                for viewport in byte_sorted(set(REQUIRED_VIEWPORTS))
            ],
            "reason": "No committed baseline satisfies the exact eight-state by three-viewport Gate policy.",
            "required_screenshot_count": 24,
        }
    manifest = strict_json_file(root / "manifest.json", project_root)
    require(manifest.get("schema_version") == "agentmesh-ai-x-browser-baseline-v1", "baseline manifest schema mismatch")
    require(manifest.get("source") == {
        "commit": DEFAULT_REVISION,
        "repository": SOURCE_REPOSITORY,
        "tree": snapshot["source"]["snapshot_tree"],
    }, "baseline source identity mismatch")
    require(manifest.get("viewports") == [{"id": key, **REQUIRED_VIEWPORTS[key]} for key in byte_sorted(set(REQUIRED_VIEWPORTS))],
            "baseline exact viewport set mismatch")
    screenshots = manifest.get("screenshots")
    require(isinstance(screenshots, list) and len(screenshots) == 24, "baseline must declare exactly 24 screenshots")
    tuples: set[tuple[str, str]] = set()
    declared_files = {"manifest.json"}
    browser_versions: set[str] = set()
    state_fixtures: dict[str, str] = {}
    for item in screenshots:
        require(isinstance(item, dict), "invalid baseline entry")
        state, viewport_id = item.get("state_id"), item.get("viewport_id")
        require(state in REQUIRED_BASELINE_STATES and viewport_id in REQUIRED_VIEWPORTS, "unknown baseline state/viewport")
        require((state, viewport_id) not in tuples, "duplicate baseline state/viewport tuple")
        tuples.add((state, viewport_id))
        relative = item.get("path")
        require(isinstance(relative, str), "missing baseline path")
        validate_relative_path(relative)
        path = root / relative
        record = file_record(path, (BASELINE_ROOT / relative).as_posix())
        require(record["sha256"] == item.get("sha256") and record["size_bytes"] == item.get("bytes"),
                f"baseline hash/size mismatch: {relative}")
        width, height = png_dimensions(path.read_bytes(), relative)
        viewport = REQUIRED_VIEWPORTS[viewport_id]
        require((width, height) == (viewport["width"] * viewport["device_scale_factor"],
                                    viewport["height"] * viewport["device_scale_factor"]),
                f"baseline PNG dimensions mismatch: {relative}")
        require(item.get("browser_engine") == "chromium", "baseline browser engine mismatch")
        browser_version = item.get("browser_version")
        require(isinstance(browser_version, str) and browser_version, "missing pinned browser version")
        browser_versions.add(browser_version)
        fixture_id, fixture_hash = item.get("state_fixture_id"), item.get("state_fixture_sha256")
        require(isinstance(fixture_id, str) and fixture_id and re.fullmatch(r"[0-9a-f]{64}", str(fixture_hash)),
                "invalid baseline state fixture identity")
        previous = state_fixtures.setdefault(state, fixture_hash)
        require(previous == fixture_hash, f"state fixture hash drift: {state}")
        for key in ("locale", "timezone", "color_scheme", "reduced_motion", "font_fingerprint"):
            require(isinstance(item.get(key), str) and item[key], f"missing baseline environment field: {key}")
        require(item.get("sanitization_status") == "passed" and isinstance(item.get("sanitization_statement"), str)
                and item["sanitization_statement"], "baseline sanitization evidence missing")
        declared_files.add(relative)
    expected_tuples = {(state, viewport) for state in REQUIRED_BASELINE_STATES for viewport in REQUIRED_VIEWPORTS}
    require(tuples == expected_tuples and len(browser_versions) == 1, "baseline matrix/browser version mismatch")
    actual_files = {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file() and not path.is_symlink()
    }
    require(actual_files == declared_files, "baseline directory contains omitted or undeclared files")
    return {
        "available": True,
        "manifest": file_record(root / "manifest.json", (BASELINE_ROOT / "manifest.json").as_posix()),
        "screenshot_count": 24,
    }


def validate_owner_acceptance(project_root: Path) -> dict[str, Any]:
    path = project_root / OWNER_ACCEPTANCE_PATH
    evidence = strict_json_file(path, project_root)
    require(evidence.get("schema_version") == "agentmesh-ai-x-gate0-interim-owner-acceptance-v1", "owner acceptance schema mismatch")
    require(evidence.get("binding_scope") == "Gate 0 and isolated Slice 1 development only", "owner binding scope mismatch")
    require(evidence.get("interim_binding_approved") is True, "interim owner binding is not approved")
    require(evidence.get("signed_by_handle") == "@heyunshen", "interim acceptance signer mismatch")
    require(evidence.get("criterion_owners") == CRITERION_OWNERS, "criterion owner policy mismatch")
    rows = evidence.get("owner_bindings")
    require(isinstance(rows, list) and len(rows) == len(OWNER_ACCOUNTABILITIES), "owner binding count mismatch")
    bindings: dict[str, str] = {}
    for row in rows:
        owner_id, handle = row.get("owner_id"), row.get("handle")
        require(owner_id in OWNER_ACCOUNTABILITIES and owner_id not in bindings, f"duplicate/unknown owner: {owner_id}")
        require(row.get("accountability") == OWNER_ACCOUNTABILITIES[owner_id], f"owner accountability mismatch: {owner_id}")
        require(handle == "@heyunshen" and row.get("proof_of_control") == "authenticated Gate 0 instruction",
                f"owner binding proof mismatch: {owner_id}")
        bindings[owner_id] = handle
    require(set(bindings) == set(OWNER_ACCOUNTABILITIES), "owner exact set mismatch")
    production = evidence.get("production_cutover", {})
    require(production.get("authorized") is False and production.get("same_person_or_key_allowed") is False,
            "production cutover must remain separately blocked")
    approvals = evidence.get("approved_criteria_by_owner")
    require(isinstance(approvals, dict) and set(approvals) == set(OWNER_ACCOUNTABILITIES), "owner approvals exact set mismatch")
    for owner_id in OWNER_ACCOUNTABILITIES:
        expected = byte_sorted({criterion for criterion, owners in CRITERION_OWNERS.items() if owner_id in owners})
        require(approvals[owner_id] == expected, f"owner criterion approval mismatch: {owner_id}")
    return {
        "bindings": [{"handle": bindings[owner_id], "owner_id": owner_id} for owner_id in byte_sorted(set(bindings))],
        "evidence": file_record(path, OWNER_ACCEPTANCE_PATH.as_posix()),
        "scope": evidence["binding_scope"],
        "signed_by_handle": evidence["signed_by_handle"],
    }


def validate_source_quality(project_root: Path, snapshot: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    path = project_root / SOURCE_QUALITY_PATH
    evidence = strict_json_file(path, project_root)
    require(evidence.get("schema_version") == "ai-x-inherited-source-quality-v1", "source quality schema mismatch")
    require(evidence.get("source") == {
        "approved_content_commit": snapshot["source"]["approved_content_commit"],
        "commit": DEFAULT_REVISION,
        "repository": SOURCE_REPOSITORY,
        "tree": snapshot["source"]["snapshot_tree"],
    }, "source quality source identity mismatch")
    require(evidence.get("bundle") == {key: bundle[key] for key in ("bytes", "path", "sha256")},
            "source quality bundle mismatch")
    package = evidence.get("package_contract", {})
    require(package == {"node": ">=22", "package_json_sha256": snapshot["tree"]["package.json"]["sha256"], "pnpm": "9.12.1"},
            "source quality runtime contract mismatch")
    checks = evidence.get("inherited_checks")
    require(isinstance(checks, list) and [item.get("argv") for item in checks] == [
        ["pnpm", "quality"], ["pnpm", "--dir", "apps/web", "build"]
    ], "source quality command set mismatch")
    for item in checks:
        evidence_path = item.get("evidence_path")
        require(isinstance(evidence_path, str) and evidence_path in snapshot["tree"], "source quality evidence blob missing")
        require(item.get("evidence_blob_sha256") == snapshot["tree"][evidence_path]["sha256"], "source quality evidence hash mismatch")
        require(item.get("result", {}).get("status") == "passed", "inherited source quality check did not pass")
    require(evidence.get("provider_calls") == 0 and evidence.get("user_data_accessed") is False,
            "source quality evidence used Provider or user data")
    require(evidence.get("release_browser_validation_performed") is False, "source quality must not claim browser release validation")
    attestation = evidence.get("attestation", {})
    require(attestation.get("signed_by_handle") == "@heyunshen"
            and attestation.get("approved_for_scope") == "Gate 0 and isolated Slice 1 development only",
            "source quality attestation mismatch")
    return {
        "commands": [item["argv"] for item in checks],
        "evidence": file_record(path, SOURCE_QUALITY_PATH.as_posix()),
        "kind": "inherited_frozen_lineage",
        "passed": True,
    }


def gate0_changed_paths(project_root: Path) -> list[str]:
    tracked = git(project_root, "diff", "--name-only", TARGET_BASE_COMMIT, "--", ".").decode().splitlines()
    untracked = git(project_root, "ls-files", "--others", "--exclude-standard").decode().splitlines()
    return byte_sorted(set(filter(None, tracked + untracked)))


def allowed_gate0_path(path: str) -> bool:
    return path in ALLOWED_GATE0_EXACT or path.startswith(ALLOWED_GATE0_PREFIXES)


def working_gate_artifact_manifest(project_root: Path) -> dict[str, Any]:
    names = gate0_changed_paths(project_root)
    require(names and all(allowed_gate0_path(path) for path in names), "target change set escapes the Gate 0 allowlist")
    records = []
    for path in names:
        validate_relative_path(path)
        value_path = project_root / path
        require(value_path.is_file() and not value_path.is_symlink(), f"Gate artifact is not a regular file: {path}")
        mode = "100755" if value_path.stat().st_mode & 0o111 else "100644"
        raw = value_path.read_bytes()
        base_exists = subprocess.run(
            ("git", "cat-file", "-e", f"{TARGET_BASE_COMMIT}:{path}"),
            cwd=project_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode == 0
        status = "M" if base_exists else "A"
        records.append({"bytes": len(raw), "mode": mode, "path": path, "sha256": sha256(raw), "status": status})
    non_lock = [record for record in records if record["path"] != LOCK_PATH.as_posix()]
    lines = "".join(
        f"{record['status']} {record['mode']} {record['sha256']} {record['bytes']}  {record['path']}\n"
        for record in non_lock
    ).encode()
    return {
        "algorithm": "SHA-256 over '<A-or-M> <mode> <sha256> <bytes>  <path>\\n' in bytewise path order; generated lock excluded to avoid self-reference",
        "file_count": len(non_lock),
        "files": non_lock,
        "manifest_sha256": sha256(lines),
    }


def committed_gate_artifact_manifest(project_root: Path, revision: str) -> dict[str, Any]:
    commit = resolve_commit(project_root, revision)
    require(git(project_root, "merge-base", "--is-ancestor", TARGET_BASE_COMMIT, commit) == b"", "target base is not an ancestor")
    raw = git(project_root, "diff-tree", "--no-commit-id", "--name-status", "-r", "-z", TARGET_BASE_COMMIT, commit)
    fields = raw.split(b"\0")
    records: list[dict[str, Any]] = []
    index = 0
    while index < len(fields) and fields[index]:
        status = fields[index].decode(); index += 1
        require(status in {"A", "M"}, f"unsupported Gate change status: {status}")
        path = fields[index].decode(); index += 1
        validate_relative_path(path)
        require(allowed_gate0_path(path), f"target change escapes Gate 0 allowlist: {path}")
        ls = git(project_root, "ls-tree", commit, "--", path).decode().rstrip("\n")
        metadata, listed_path = ls.split("\t", 1)
        mode, kind, _oid = metadata.split(" ")
        require(listed_path == path and kind == "blob" and mode in {"100644", "100755"}, f"unsupported target blob: {path}")
        value = git(project_root, "show", f"{commit}:{path}")
        records.append({"bytes": len(value), "mode": mode, "path": path, "sha256": sha256(value), "status": status})
    records.sort(key=lambda item: item["path"].encode())
    lines = "".join(
        f"{record['status']} {record['mode']} {record['sha256']} {record['bytes']}  {record['path']}\n"
        for record in records
    ).encode()
    tree = git(project_root, "show", "-s", "--format=%T", commit).decode().strip()
    return {
        "commit": commit,
        "file_count": len(records),
        "files": records,
        "manifest_sha256": sha256(lines),
        "tree": tree,
    }


def build_evidence(project_root: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    bundle = validate_bundle_file(project_root)
    owners = validate_owner_acceptance(project_root)
    quality = validate_source_quality(project_root, snapshot, bundle)
    fixtures = validate_contract_fixtures(project_root, snapshot)
    history = validate_history_fixture(project_root)
    browser = validate_browser_baseline(project_root, snapshot)
    characterized = set(history["characterized_target_cases"])
    target_characterization = {
        "complete": characterized == REQUIRED_TARGET_CASES,
        "missing_cases": byte_sorted(REQUIRED_TARGET_CASES - characterized),
        "passing_cases": byte_sorted(characterized),
        "required_cases": byte_sorted(REQUIRED_TARGET_CASES),
    }
    return {
        "browser_baseline": browser,
        "contract_fixtures": fixtures,
        "historical_database_fixture": history,
        "owner_acceptance": owners,
        "source_bundle": bundle,
        "source_quality": quality,
        "target_characterization": target_characterization,
    }


def criterion_assessment(evidence: dict[str, Any], artifact_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    owner_ok = len(evidence["owner_acceptance"]["bindings"]) == len(OWNER_ACCOUNTABILITIES)
    facts = {
        "gate0-01-ownership-ledger": owner_ok,
        "gate0-02-final-source-authority-and-durable-retention": evidence["source_bundle"]["sha256"]
        == "bc498a854c0b60835036e87dfd576d37aa233c65833cdbde493a10504670369f",
        "gate0-03-authoritative-parity-lock": evidence["contract_fixtures"]["status"] == "valid_characterization_only",
        "gate0-04-offline-source-quality": evidence["source_quality"]["passed"],
        "gate0-05-visual-identity": evidence["browser_baseline"]["available"],
        "gate0-06-accepted-architecture-and-exact-contracts": owner_ok,
        "gate0-07-target-characterization": evidence["target_characterization"]["complete"],
        "gate0-08-zero-production-behavior-diff": artifact_manifest["file_count"] > 0,
        "gate0-09-v2-compatibility-and-slice-1-work-plan":
        evidence["historical_database_fixture"]["status"] == "valid_sanitized_historical_fixture",
    }
    facts["gate0-10-handoff-and-authorization"] = all(facts.values())
    return [
        {
            "id": criterion,
            "owner_ids": owners,
            "satisfied_by_committed_evidence": facts[criterion],
        }
        for criterion, owners in CRITERION_OWNERS.items()
    ]


def build_lock(project_root: Path, source: Path, revision: str = DEFAULT_REVISION) -> dict[str, Any]:
    snapshot = source_state(source, revision)
    evidence = build_evidence(project_root, snapshot)
    target_manifest = working_gate_artifact_manifest(project_root)
    criteria = criterion_assessment(evidence, target_manifest)
    blockers = [item["id"] for item in criteria if not item["satisfied_by_committed_evidence"]]
    return {
        "authorization": {
            "blocking_criteria": blockers,
            "criteria": criteria,
            "production_cutover_authorized": False,
            "scope": "Gate 0 and isolated Slice 1 development only",
            "slice_1_authorized": not blockers,
        },
        "canonicalization": {
            "file_hash": "SHA-256 of exact bytes",
            "json": "UTF-8; duplicate keys forbidden; object keys sorted; two-space indentation; LF; one trailing LF",
            "manifest": "'<A-or-M> <mode> <sha256> <bytes>  <path>\\n' in bytewise path order",
            "path_order": "repository-relative NFC UTF-8 POSIX paths sorted by encoded bytes",
        },
        "excluded_assets": snapshot["excluded"],
        "generator": {"id": "agentmesh-gate0-evidence-lock", "version": 3},
        "included_assets": snapshot["included"],
        "integrity": snapshot["integrity"],
        "lock_version": "ai-x-parity-lock-v3",
        "normalized_inventory": snapshot["normalized"],
        "owner_policy": {
            "accountabilities": OWNER_ACCOUNTABILITIES,
            "criterion_owners": CRITERION_OWNERS,
            "interim_binding_scope": "Gate 0 and isolated Slice 1 development only",
            "production_cutover_requires_independent_architecture_and_release_reviewers": True,
        },
        "source": {
            **snapshot["source"],
            "bundle": evidence["source_bundle"],
            "owner_acceptance": evidence["owner_acceptance"]["evidence"],
            "quality_evidence": evidence["source_quality"]["evidence"],
        },
        "target": {
            "artifact_manifest_without_generated_lock": target_manifest,
            "base_commit": TARGET_BASE_COMMIT,
            "base_tree": TARGET_BASE_TREE,
            "exact_commit_binding": "derived by the verifier from the clean target revision; not embedded to avoid commit self-reference",
            "repository": TARGET_REPOSITORY,
        },
        "target_contract_mapping": {
            "current_identities": CURRENT_IDENTITIES,
            "historical_identity_policy": HISTORICAL_IDENTITY_POLICY,
            "source_aliases": {
                "current-execution-plan": "execution-plan-v3",
                "report-document-v1": "report-document-v3",
                "report-review-v1": "report-review-v3",
                "research-deliverable-v1": "research-deliverable-v3",
                "research-task-v2": "research-task-v3",
            },
        },
        "target_evidence": evidence,
        "tree_manifest": snapshot["tree_manifest"],
    }


def validate_mapping(lock: dict[str, Any]) -> None:
    mapping = lock["target_contract_mapping"]
    require(mapping["historical_identity_policy"] == HISTORICAL_IDENTITY_POLICY, "historical identity drift")
    require(mapping["current_identities"] == CURRENT_IDENTITIES, "current identity drift")
    require(not set(mapping["current_identities"]) & set(HISTORICAL_IDENTITY_POLICY["combined"]),
            "current/historical schema collision")


def validate(
    lock_path: Path,
    source: Path,
    revision: str | None,
    *,
    source_bundle: Path | None = None,
    target_revision: str = "HEAD",
    require_clean_source: bool = False,
    require_clean_target: bool = False,
    require_slice_1_authorized: bool = False,
) -> dict[str, Any]:
    project_root = lock_path.resolve().parents[2]
    raw = lock_path.read_bytes()
    lock = strict_json_bytes(raw, LOCK_PATH.as_posix())
    require(lock.get("lock_version") == "ai-x-parity-lock-v3", "unsupported lock version")
    effective_revision = revision or lock["source"]["snapshot_commit"]
    require(effective_revision == DEFAULT_REVISION, "source revision mismatch")
    expected = build_lock(project_root, source, effective_revision)
    require(lock == expected, "lock drift: regenerate with scripts/build_ai_x_parity_lock.py")
    validate_mapping(lock)
    bundle_path = source_bundle or project_root / SOURCE_BUNDLE_PATH
    require(bundle_path.resolve() == (project_root / SOURCE_BUNDLE_PATH).resolve(), "release bundle must be the committed durable Gate artifact")
    with materialized_source_bundle(bundle_path):
        pass
    target = committed_gate_artifact_manifest(project_root, target_revision)
    non_lock = [record for record in target["files"] if record["path"] != LOCK_PATH.as_posix()]
    non_lock_lines = "".join(
        f"{record['status']} {record['mode']} {record['sha256']} {record['bytes']}  {record['path']}\n"
        for record in non_lock
    ).encode()
    persisted_manifest = lock["target"]["artifact_manifest_without_generated_lock"]
    require(persisted_manifest["files"] == non_lock, "accepted target artifacts differ from the lock manifest")
    require(persisted_manifest["file_count"] == len(non_lock)
            and persisted_manifest["manifest_sha256"] == sha256(non_lock_lines), "accepted target artifact manifest mismatch")
    lock_blob = next((item for item in target["files"] if item["path"] == LOCK_PATH.as_posix()), None)
    require(lock_blob is not None and lock_blob["sha256"] == sha256(raw) and lock_blob["bytes"] == len(raw),
            "accepted target lock blob mismatch")
    require(git(project_root, "show", "-s", "--format=%T", TARGET_BASE_COMMIT).decode().strip() == TARGET_BASE_TREE,
            "target base tree mismatch")
    source_clean = resolve_commit(source, "HEAD") == effective_revision and git(source, "status", "--porcelain=v1", "-z") == b""
    target_clean = resolve_commit(project_root, "HEAD") == target["commit"] and git(project_root, "status", "--porcelain=v1", "-z") == b""
    if require_clean_source:
        require(source_clean, "source checkout is not clean at the frozen commit")
    if require_clean_target:
        require(target_clean, "target checkout is not clean at the accepted commit")
    criteria = []
    for item in lock["authorization"]["criteria"]:
        passed = item["satisfied_by_committed_evidence"]
        if item["id"] == "gate0-08-zero-production-behavior-diff":
            passed = passed and target_clean
        if item["id"] == "gate0-10-handoff-and-authorization":
            passed = False
        criteria.append({"id": item["id"], "owner_ids": item["owner_ids"], "passed": passed})
    prior_pass = all(item["passed"] for item in criteria if item["id"] != "gate0-10-handoff-and-authorization")
    for item in criteria:
        if item["id"] == "gate0-10-handoff-and-authorization":
            item["passed"] = prior_pass and target_clean
    blockers = [item["id"] for item in criteria if not item["passed"]]
    authorized = not blockers
    if require_slice_1_authorized:
        require(authorized, "Slice 1 is on HOLD")
    return {
        "authorization_result": "authorized" if authorized else "hold",
        "blocking_criteria": blockers,
        "criteria": criteria,
        "excluded_exact_files": lock["excluded_assets"]["exact_file_count"],
        "gate_artifact_count": target["file_count"],
        "gate_artifact_manifest_sha256": target["manifest_sha256"],
        "included_files": lock["included_assets"]["file_count"],
        "lock_result": "valid",
        "lock_sha256": sha256(raw),
        "slice_1_authorized": authorized,
        "source_bundle_sha256": lock["source"]["bundle"]["sha256"],
        "source_commit": lock["source"]["snapshot_commit"],
        "source_tree": lock["source"]["snapshot_tree"],
        "target_clean": target_clean,
        "target_commit": target["commit"],
        "target_tree": target["tree"],
        "tree_files": lock["tree_manifest"]["file_count"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, default=LOCK_PATH)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-bundle", type=Path)
    parser.add_argument("--revision")
    parser.add_argument("--target-revision", default="HEAD")
    parser.add_argument("--require-clean-checkout", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--require-clean-source", action="store_true")
    parser.add_argument("--require-clean-target", action="store_true")
    parser.add_argument("--require-slice-1-authorized", action="store_true")
    args = parser.parse_args()
    result = validate(
        args.lock,
        args.source.resolve(),
        args.revision,
        source_bundle=args.source_bundle,
        target_revision=args.target_revision,
        require_clean_source=args.require_clean_source or args.require_clean_checkout,
        require_clean_target=args.require_clean_target,
        require_slice_1_authorized=args.require_slice_1_authorized,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
