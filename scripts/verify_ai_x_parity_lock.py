#!/usr/bin/env python3
"""Build and validate the immutable ai-x Gate 0 parity lock.

The lock is derived from Git objects, never mutable checkout files. A valid
lock may remain on HOLD; --require-slice-1-authorized is the release mode.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

DEFAULT_REVISION = "d7ec877fbff0684b0886cb86a7e09eb42ebf7d77"
SOURCE_REPOSITORY = "https://github.com/yssssssssssss/ai-x.git"
SOURCE_BRANCH_LABEL = "agent/ai-x-parity-source-freeze-final"
FREEZE_MANIFEST_PATH = "docs/development/ai-x-parity-source-freeze.json"
TARGET_BASE_COMMIT = "dec6b55b3e97913c052ee2b665c063aec77a9dd3"
TARGET_BASE_TREE = "eb39f8159afb421233b657747192447734fd8b07"
FIXTURE_ROOT = Path("tests/fixtures/ai_x_parity")
BASELINE_ROOT = Path("docs/verification/ai-x-parity-baselines")

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
    "agentmesh/research_catalog/ai-x-parity-lock.json",
    "docs/adr/0006-single-active-research-writer.md",
    "docs/superpowers/plans/2026-08-20-ai-x-workbench-full-parity-migration-plan.md",
    "docs/verification/2026-08-20-ai-x-parity-gate0.md",
    "scripts/build_ai_x_parity_lock.py", "scripts/verify_ai_x_parity_lock.py",
}
ALLOWED_GATE0_PREFIXES = (
    "docs/verification/ai-x-parity-baselines/", "tests/fixtures/ai_x_parity/",
)


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

def source_state(source: Path, revision: str) -> dict[str, Any]:
    commit = resolve_commit(source, revision)
    tree_hash = git(source, "show", "-s", "--format=%T", commit).decode().strip()
    parents = git(source, "show", "-s", "--format=%P", commit).decode().strip().split()
    require(len(parents) == 1, "snapshot must have one parent")
    parent = parents[0]
    parent_tree = git(source, "show", "-s", "--format=%T", parent).decode().strip()
    tree = read_tree(source, commit)
    require(FREEZE_MANIFEST_PATH in tree, "freeze manifest missing")
    freeze = json_blob(tree, FREEZE_MANIFEST_PATH)
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
        "authoritative_for_migration": False,
        "approved_content_commit": approved_commit,
        "approved_content_tree": approved_tree,
        "base_commit": base_commit,
        "branch_label": SOURCE_BRANCH_LABEL,
        "checkout_attestation": {"required_head": commit, "required_status": "clean", "verified_by_default": False},
        "commit_subject": git(source, "show", "-s", "--format=%s", commit).decode().strip(),
        "durable_retention": {
            "evidence": [],
            "reason": "No protected remote ref, signed tag, or verified Git bundle was supplied to Gate 0.",
            "status": "missing_blocker",
        },
        "freeze_manifest": {
            "blob_sha256": tree[FREEZE_MANIFEST_PATH]["sha256"], "git_blob": tree[FREEZE_MANIFEST_PATH]["git_blob"],
            "path": FREEZE_MANIFEST_PATH, "schema_version": freeze.get("schemaVersion"),
            "size_bytes": tree[FREEZE_MANIFEST_PATH]["size_bytes"],
        },
        "inventory_commit": commit, "inventory_tree": tree_hash,
        "manifest_relationship": {
            "approved_content_commit": approved_commit, "approved_content_tree": approved_tree,
            "change_path": FREEZE_MANIFEST_PATH, "change_type": "modified",
            "metadata_discrepancy": (
                "The source manifest calls approvedContentTree pre-manifest/non-self-referential, but that parent "
                "tree contains the predecessor manifest blob. This lock relies only on the verified parent, tree, "
                "and single-path modified relationship."
            ),
            "snapshot_parent_equals_approved_content_commit": True,
        },
        "owner_approval": "approved_snapshot", "owner_approval_evidence": FREEZE_MANIFEST_PATH,
        "repository": SOURCE_REPOSITORY, "snapshot_commit": commit, "snapshot_parent": parent,
        "snapshot_tree": tree_hash,
    }
    return {
        "excluded": excluded, "included": included, "integrity": integrity, "normalized": normalized,
        "source": metadata, "tree": tree,
        "tree_manifest": {"file_count": len(tree), "manifest_sha256": manifest_sha256(set(tree), tree),
                          "modes": ["100644", "100755"]},
    }


def file_record(path: Path, relative_path: str) -> dict[str, Any]:
    value = path.read_bytes()
    return {"path": relative_path, "sha256": sha256(value), "size_bytes": len(value)}


def target_evidence(project_root: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    manifest_path = project_root / FIXTURE_ROOT / "manifest.json"
    require(manifest_path.is_file(), f"missing copied fixture manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_bytes())
    require(manifest.get("source", {}).get("commit") == snapshot["source"]["snapshot_commit"], "fixture source mismatch")
    require(manifest.get("source", {}).get("tree") == snapshot["source"]["snapshot_tree"], "fixture source tree mismatch")
    require(manifest.get("target", {}).get("base_commit") == TARGET_BASE_COMMIT, "fixture target mismatch")
    require(manifest.get("target", {}).get("tree") == TARGET_BASE_TREE, "fixture target tree mismatch")
    files = []
    for declared in manifest.get("files", []):
        relative = declared["path"]
        path = project_root / FIXTURE_ROOT / relative
        require(path.is_file(), f"missing fixture: {relative}")
        record = file_record(path, (FIXTURE_ROOT / relative).as_posix())
        require(record["sha256"] == declared["sha256"], f"fixture hash mismatch: {relative}")
        require(record["size_bytes"] == declared["bytes"], f"fixture size mismatch: {relative}")
        files.append({**record, "fixture_id": declared["fixture_id"]})
    files.sort(key=lambda item: item["path"].encode())
    manifest_record = file_record(manifest_path, (FIXTURE_ROOT / "manifest.json").as_posix())

    browser_manifest_path = project_root / BASELINE_ROOT / "manifest.json"
    required_states = ["approval", "candidates", "clarify", "dag_or_executing", "idle", "paused", "plan", "text_report"]
    if not browser_manifest_path.is_file():
        browser = {
            "assets": [], "manifest_path": None,
            "reason": (
                "No finalized browser-baseline manifest or screenshots were supplied; only transient capture work "
                "files existed, so Gate 0 copied no invented visual evidence."
            ),
            "required_slice_1_states": required_states, "status": "missing_blocker",
        }
    else:
        browser_manifest = json.loads(browser_manifest_path.read_bytes())
        require(
            browser_manifest.get("sourceCommit") == snapshot["source"]["snapshot_commit"],
            "browser baseline source commit mismatch",
        )
        require(
            browser_manifest.get("schemaVersion") == "source-workbench-browser-baseline-v1",
            "browser baseline schema mismatch",
        )
        declared_artifacts = browser_manifest.get("artifacts")
        require(isinstance(declared_artifacts, list) and declared_artifacts, "browser baseline manifest is empty")
        assets = []
        for declared in declared_artifacts:
            require(declared.get("sourceCommit") == snapshot["source"]["snapshot_commit"], "baseline asset source mismatch")
            require(declared.get("browserEngine") == "chromium", "baseline browser engine mismatch")
            require(isinstance(declared.get("browserVersion"), str) and declared["browserVersion"], "missing browser version")
            require(isinstance(declared.get("stateFixtureId"), str) and declared["stateFixtureId"], "missing fixture id")
            require(isinstance(declared.get("sanitizationStatement"), str) and declared["sanitizationStatement"],
                    "missing baseline sanitization statement")
            viewport = declared.get("viewport")
            require(
                isinstance(viewport, dict)
                and all(isinstance(viewport.get(key), int) and viewport[key] > 0
                        for key in ("width", "height", "deviceScaleFactor")),
                "invalid baseline viewport",
            )
            relative = declared["path"]
            path = project_root / BASELINE_ROOT / relative
            require(path.is_file(), f"missing browser baseline: {relative}")
            record = file_record(path, (BASELINE_ROOT / relative).as_posix())
            require(record["sha256"] == declared["fileSha256"], f"baseline hash mismatch: {relative}")
            assets.append({**record, "fixture_id": declared.get("stateFixtureId")})
        assets.sort(key=lambda item: item["path"].encode())
        browser = {
            "assets": assets, "manifest": file_record(browser_manifest_path, (BASELINE_ROOT / "manifest.json").as_posix()),
            "manifest_path": (BASELINE_ROOT / "manifest.json").as_posix(),
            "required_slice_1_states": required_states,
            "status": "captured_pending_state_coverage_review" if assets else "missing_blocker",
        }
    return {
        "browser_baseline": browser,
        "contract_fixtures": {"files": files, "manifest": manifest_record,
                              "manifest_path": manifest_record["path"], "status": "characterization_only"},
        "target_base_commit": TARGET_BASE_COMMIT, "target_base_tree": TARGET_BASE_TREE,
    }


def gate0_changed_paths(project_root: Path) -> list[str]:
    changed = set(filter(None, git(project_root, "diff", "--name-only", TARGET_BASE_COMMIT, "--", ".").decode().splitlines()))
    changed.update(filter(None, git(project_root, "ls-files", "--others", "--exclude-standard").decode().splitlines()))
    return byte_sorted(changed)


def allowed_gate0_path(path: str) -> bool:
    return path in ALLOWED_GATE0_EXACT or path.startswith(ALLOWED_GATE0_PREFIXES)


def ownership_ledger() -> list[dict[str, Any]]:
    rows = (
        ("AX-SOURCE", "ai-x Source Custodian", "source lock and immutable source approval"),
        ("AM-ARCH", "AgentMesh Architecture Owner", "ADR, schema namespace, and atomic cutover"),
        ("AM-CONTRACTS-HISTORY", "Research Contracts and v2 History Owner", "v2 history adapter and v3 contracts"),
        ("AM-RUNTIME-STORE", "Research Runtime and Store Owner", "retirement drain and writer fence"),
        ("AM-WEB", "Workbench and Projection Owner", "visual baselines and versioned renderers"),
        ("AM-SECURITY-RETENTION", "Security, Audit and Retention Owner", "security review, retention, and purge"),
        ("AM-RELEASE-QA", "Release Verification Owner", "release gate and lock verification"),
        ("AM-PRODUCT-RESEARCH", "Product and Research Owner", "Slice acceptance and rollout policy"),
    )
    return [{"accountability": accountability, "binding_status": "unbound_blocker", "handle": None,
             "name": name, "owner_id": owner_id} for owner_id, name, accountability in rows]


def build_authorization(
    project_root: Path, snapshot: dict[str, Any], evidence: dict[str, Any], owners: list[dict[str, Any]]
) -> dict[str, Any]:
    changed = gate0_changed_paths(project_root)
    assigned = all(item["binding_status"] == "assigned" and isinstance(item["handle"], str)
                   and item["handle"].startswith("@") for item in owners)
    retained = snapshot["source"]["durable_retention"]["status"] == "verified"
    browser = evidence["browser_baseline"]
    criteria = [
        ("gate0-01-ownership-ledger", ["AM-ARCH"],
         ["docs/verification/2026-08-20-ai-x-parity-gate0.md#5-named-ownership-ledger"], assigned),
        ("gate0-02-final-source-authority-and-durable-retention", ["AX-SOURCE"], [FREEZE_MANIFEST_PATH],
         snapshot["source"]["owner_approval"] == "approved_snapshot" and retained),
        ("gate0-03-authoritative-parity-lock", ["AM-RELEASE-QA", "AX-SOURCE"],
         ["agentmesh/research_catalog/ai-x-parity-lock.json"],
         snapshot["source"]["authoritative_for_migration"] and retained),
        ("gate0-04-offline-source-quality", ["AX-SOURCE", "AM-RELEASE-QA"], [], False),
        ("gate0-05-visual-identity", ["AX-SOURCE", "AM-WEB"],
         [browser["manifest_path"]] if browser["manifest_path"] else [],
         browser["status"] == "available" and bool(browser["assets"])),
        ("gate0-06-accepted-architecture-and-exact-contracts", ["AM-ARCH", "AM-CONTRACTS-HISTORY"], [
            "docs/adr/0006-single-active-research-writer.md",
            "docs/superpowers/plans/2026-08-20-ai-x-workbench-full-parity-migration-plan.md"], False),
        ("gate0-07-target-characterization", ["AM-RELEASE-QA"],
         [evidence["contract_fixtures"]["manifest_path"]], False),
        ("gate0-08-zero-production-behavior-diff", ["AM-ARCH", "AM-RELEASE-QA"], changed,
         all(allowed_gate0_path(path) for path in changed)),
        ("gate0-09-v2-compatibility-and-slice-1-work-plan",
         ["AM-CONTRACTS-HISTORY", "AM-RUNTIME-STORE", "AM-WEB", "AM-SECURITY-RETENTION"], [
             "docs/adr/0006-single-active-research-writer.md#safe-deletion-gate",
             "docs/verification/2026-08-20-ai-x-parity-gate0.md#6-v2-history-retirement-and-security-work-package"], False),
        ("gate0-10-handoff-and-authorization", ["AM-ARCH", "AM-RELEASE-QA"], [], False),
    ]
    records = [{"evidence": ev, "id": item_id, "owner_ids": owner_ids, "passed": passed}
               for item_id, owner_ids, ev, passed in criteria]
    blocking = [item["id"] for item in records if not item["passed"]]
    return {"blocking_criteria": blocking, "criteria": records, "slice_1_authorized": not blocking}


def build_lock(project_root: Path, source: Path, revision: str = DEFAULT_REVISION) -> dict[str, Any]:
    snapshot = source_state(source, revision)
    evidence = target_evidence(project_root, snapshot)
    owners = ownership_ledger()
    authorization = build_authorization(project_root, snapshot, evidence, owners)
    return {
        "attestation": {
            "blocking_findings": authorization["blocking_criteria"], "provider_smoke_run": False,
            "source_assets_copied": False,
            "source_quality": {"commands": [], "status": "not_run_by_gate0_writer"},
            "user_data_read_or_migrated": False,
        },
        "authorization": authorization,
        "canonicalization": {
            "file_hash": "SHA-256 of exact Git blob bytes",
            "json": "UTF-8; object keys sorted; two-space indentation; LF; one trailing LF",
            "manifest": "for each bytewise-sorted path emit '<mode> <sha256> <size_bytes>  <path>\\n'; SHA-256 the concatenated UTF-8 bytes",
            "path_order": "repository-relative UTF-8 POSIX paths sorted by encoded bytes",
        },
        "excluded_assets": snapshot["excluded"],
        "generator": {"id": "agentmesh-gate0-approved-snapshot-inventory", "version": 2},
        "included_assets": snapshot["included"], "integrity": snapshot["integrity"],
        "lock_version": "ai-x-parity-lock-v2", "normalized_inventory": snapshot["normalized"],
        "owners": owners, "slice_1_authorized": authorization["slice_1_authorized"],
        "source": snapshot["source"], "status": "approved_source_snapshot_pending_gate0_evidence",
        "target_contract_mapping": {
            "deliverable_contracts": {
                "deliverable": {"source_identity": "research-deliverable-v1",
                                "target_persisted_identity": "research-deliverable-v3",
                                "target_type": "ResearchDeliverableV3"},
                "report": {"source_identity": "report-document-v1",
                           "target_persisted_identity": "report-document-v3", "target_type": "ReportDocumentV3"},
                "review": {"source_identity": "report-review-v1",
                           "target_persisted_identity": "report-review-v3", "target_type": "ReportReviewV3"},
            },
            "execution_plan": {"source_identity": "current-execution-plan",
                               "target_persisted_identity": "execution-plan-v3", "target_type": "ExecutionPlanV3"},
            "orchestration_version": "research-v3",
            "requirement": {"source_identity": "research-task-v2",
                            "target_persisted_identity": "research-task-v3", "target_type": "ResearchTaskV3"},
            "reserved_historical_target_identities": [
                "competitive-analysis-review-v1", "deliverable-document-v1", "deterministic-review-v1",
                "execution-plan-v2", "report-document-v1", "research-task-v2",
            ],
        },
        "target_evidence": evidence, "tree_manifest": snapshot["tree_manifest"],
    }


def validate_mapping(lock: dict[str, Any]) -> None:
    mapping = lock["target_contract_mapping"]
    require(mapping["orchestration_version"] == "research-v3", "orchestration identity drift")
    reserved = set(mapping["reserved_historical_target_identities"])
    current = {
        mapping["requirement"]["target_persisted_identity"],
        mapping["execution_plan"]["target_persisted_identity"],
        *(item["target_persisted_identity"] for item in mapping["deliverable_contracts"].values()),
    }
    require(
        reserved
        == {
            "competitive-analysis-review-v1", "deliverable-document-v1", "deterministic-review-v1",
            "execution-plan-v2", "report-document-v1", "research-task-v2",
        },
        "historical identity drift",
    )
    require(
        current
        == {
            "research-task-v3", "execution-plan-v3", "research-deliverable-v3",
            "report-review-v3", "report-document-v3",
        },
        "current identity drift",
    )
    require(not current & reserved, "current/historical schema collision")


def validate(
    lock_path: Path, source: Path, revision: str | None,
    require_clean_checkout: bool = False, require_slice_1_authorized: bool = False,
) -> dict[str, Any]:
    project_root = lock_path.resolve().parents[2]
    raw = lock_path.read_bytes()
    lock = json.loads(raw)
    canonical = (json.dumps(lock, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    require(raw == canonical, "lock JSON is not canonical")
    require(lock.get("lock_version") == "ai-x-parity-lock-v2", "unsupported lock version")
    effective_revision = revision or lock["source"]["snapshot_commit"]
    require(resolve_commit(source, effective_revision) == lock["source"]["snapshot_commit"], "revision mismatch")
    expected = build_lock(project_root, source, effective_revision)
    require(lock == expected, "lock drift: regenerate with scripts/build_ai_x_parity_lock.py")
    validate_mapping(lock)
    criteria = lock["authorization"]["criteria"]
    for criterion in criteria:
        if not criterion["passed"]:
            continue
        for evidence_path in criterion["evidence"]:
            evidence_file = evidence_path.split("#", 1)[0]
            require((project_root / evidence_file).is_file(), f"missing passed-criterion evidence: {evidence_path}")
    derived_authorized = all(item["passed"] for item in criteria)
    derived_blockers = [item["id"] for item in criteria if not item["passed"]]
    require(lock["slice_1_authorized"] == derived_authorized, "Slice 1 authorization is not derived")
    require(lock["authorization"]["blocking_criteria"] == derived_blockers, "authorization blocker drift")
    require(lock["attestation"]["blocking_findings"] == derived_blockers, "attestation blocker drift")
    if require_clean_checkout:
        require(resolve_commit(source, "HEAD") == effective_revision, "source checkout HEAD mismatch")
        require(git(source, "status", "--porcelain=v1", "-z") == b"", "source checkout is not clean")
    if require_slice_1_authorized:
        require(derived_authorized, "Slice 1 is on HOLD")
    return {
        "authorization_result": "authorized" if derived_authorized else "hold",
        "blocking_criteria": derived_blockers,
        "excluded_exact_files": lock["excluded_assets"]["exact_file_count"],
        "included_files": lock["included_assets"]["file_count"],
        "lock_result": "valid", "lock_sha256": sha256(raw),
        "slice_1_authorized": derived_authorized,
        "source_commit": lock["source"]["snapshot_commit"], "source_tree": lock["source"]["snapshot_tree"],
        "tree_files": lock["tree_manifest"]["file_count"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, default=Path("agentmesh/research_catalog/ai-x-parity-lock.json"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--revision")
    parser.add_argument("--require-clean-checkout", action="store_true")
    parser.add_argument("--require-slice-1-authorized", action="store_true")
    args = parser.parse_args()
    result = validate(
        args.lock, args.source.resolve(), args.revision,
        require_clean_checkout=args.require_clean_checkout,
        require_slice_1_authorized=args.require_slice_1_authorized,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
