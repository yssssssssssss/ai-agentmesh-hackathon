"""Versioned contracts for the closed-loop evaluation dataset."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agentmesh.canonical_json import canonical_json_sha256, strict_json_loads

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST_PATH = ROOT / "eval" / "closed_loop" / "manifest-v1.json"
DEFAULT_TASKS_PATH = ROOT / "eval" / "closed_loop" / "tasks-v1.json"

VariantId = Literal["V0", "V1", "V2", "V3"]
ExecutionMode = Literal["standard", "deepsearch"]
ExpectedBoundary = Literal["sealed_artifact", "input_gap", "partial_or_gap", "security_boundary"]
SecurityProbe = Literal["prompt_injection", "credential_pattern", "cross_project_reference", "command_replay"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ClosedLoopMaterialPackV1(_StrictModel):
    id: str = Field(pattern=r"^M0[1-8]$")
    name: str = Field(min_length=1, max_length=120)
    synthetic: Literal[True]
    scale: str = Field(min_length=1, max_length=200)
    facts: list[str] = Field(min_length=1)


class ClosedLoopTaskV1(_StrictModel):
    id: str = Field(pattern=r"^T(?:0[1-9]|1[0-9]|2[0-4])$")
    primary_profile: str = Field(min_length=1)
    scenario_id: str | None = Field(default=None, min_length=1)
    goal: str = Field(min_length=1, max_length=500)
    required_output_kinds: list[str] = Field(min_length=1)
    material_pack_ids: list[str] = Field(min_length=1)
    execution_mode: ExecutionMode


class ClosedLoopCaseV1(_StrictModel):
    id: str = Field(pattern=r"^CLV1-T(?:0[1-9]|1[0-9]|2[0-4])-V[0-3]$")
    task_id: str = Field(pattern=r"^T(?:0[1-9]|1[0-9]|2[0-4])$")
    variant_id: VariantId
    expected_boundary: ExpectedBoundary
    input_directive: str = Field(min_length=1, max_length=500)
    security_probe: SecurityProbe | None = None


class ClosedLoopTasksDocumentV1(_StrictModel):
    schema_version: Literal["closed-loop-tasks-v1"]
    dataset_version: Literal["1"]
    synthetic: Literal[True]
    material_packs: list[ClosedLoopMaterialPackV1]
    tasks: list[ClosedLoopTaskV1]
    cases: list[ClosedLoopCaseV1]


class MemoryReuseChainV1(_StrictModel):
    source_task_id: str = Field(pattern=r"^T(?:0[1-9]|1[0-9]|2[0-4])$")
    follow_up_task_id: str = Field(pattern=r"^T(?:0[1-9]|1[0-9]|2[0-4])$")


class ReviewScopeV1(_StrictModel):
    accepted_task_ids: list[str]
    personal_memory_task_id: str
    changes_requested_case_ids: list[str]


class FaultCaseV1(_StrictModel):
    case_id: str = Field(pattern=r"^CLV1-T(?:0[1-9]|1[0-9]|2[0-4])-V[0-3]$")
    injection_point: Literal[
        "run_claimed",
        "artifact_sealed",
        "memory_capture_response",
        "receipt_reserved",
        "sqlite_reopen",
        "projection_rebuild",
        "expected_version_conflict",
        "command_replay",
    ]


class CatalogIdentityV1(_StrictModel):
    catalog_version: Literal["user-research-v1", "user-research-v2"]
    catalog_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class PilotProfileIdentityV1(_StrictModel):
    name: str = Field(min_length=1)
    skill_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ClosedLoopManifestV1(_StrictModel):
    schema_version: Literal["closed-loop-evaluation-manifest-v1"]
    dataset_version: Literal["1"]
    tasks_file: Literal["tasks-v1.json"]
    expected_task_count: Literal[24]
    expected_case_count: Literal[96]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    tasks_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalogs: list[CatalogIdentityV1]
    pilot_profiles: list[PilotProfileIdentityV1]
    memory_reuse_chains: list[MemoryReuseChainV1]
    review_scope: ReviewScopeV1
    fault_cases: list[FaultCaseV1]
    core_pr_case_ids: list[str]


class ClosedLoopValidationReport(_StrictModel):
    validated_tasks: int
    validated_cases: int
    validated_profiles: int
    validated_scenarios: int
    diagnostics: list[str]


class ClosedLoopEvaluationDataset(_StrictModel):
    manifest: ClosedLoopManifestV1
    material_packs: list[ClosedLoopMaterialPackV1]
    tasks: list[ClosedLoopTaskV1]
    cases: list[ClosedLoopCaseV1]


def _load_document(path: Path) -> object:
    try:
        return strict_json_loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise ValueError(f"closed_loop_dataset_unreadable:{path.name}") from error


def _validate_dataset_integrity(
    manifest: ClosedLoopManifestV1,
    document: ClosedLoopTasksDocumentV1,
    *,
    tasks_sha256: str,
) -> None:
    if manifest.tasks_sha256 != tasks_sha256:
        raise ValueError("closed_loop_tasks_hash_mismatch")
    if len(document.tasks) != manifest.expected_task_count:
        raise ValueError("closed_loop_task_count_invalid")
    if len(document.cases) != manifest.expected_case_count:
        raise ValueError("closed_loop_case_count_invalid")
    task_ids = [task.id for task in document.tasks]
    case_ids = [case.id for case in document.cases]
    material_ids = [material.id for material in document.material_packs]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("closed_loop_task_ids_not_unique")
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("closed_loop_case_ids_not_unique")
    if len(material_ids) != len(set(material_ids)):
        raise ValueError("closed_loop_material_ids_not_unique")
    if set(task_ids) != {f"T{index:02d}" for index in range(1, 25)}:
        raise ValueError("closed_loop_task_ids_incomplete")
    if set(material_ids) != {f"M{index:02d}" for index in range(1, 9)}:
        raise ValueError("closed_loop_material_ids_incomplete")
    expected_boundaries: dict[VariantId, ExpectedBoundary] = {
        "V0": "sealed_artifact",
        "V1": "input_gap",
        "V2": "partial_or_gap",
        "V3": "security_boundary",
    }
    expected_cases = {
        (task_id, variant_id): f"CLV1-{task_id}-{variant_id}"
        for task_id in task_ids
        for variant_id in expected_boundaries
    }
    actual_cases = {(case.task_id, case.variant_id): case for case in document.cases}
    if set(actual_cases) != set(expected_cases):
        raise ValueError("closed_loop_case_matrix_incomplete")
    for key, expected_id in expected_cases.items():
        case = actual_cases[key]
        if case.id != expected_id or case.expected_boundary != expected_boundaries[case.variant_id]:
            raise ValueError(f"closed_loop_case_identity_invalid:{case.id}")
        if (case.variant_id == "V3") != (case.security_probe is not None):
            raise ValueError(f"closed_loop_case_security_probe_invalid:{case.id}")
    material_id_set = set(material_ids)
    for task in document.tasks:
        if len(task.material_pack_ids) != len(set(task.material_pack_ids)):
            raise ValueError(f"closed_loop_task_materials_not_unique:{task.id}")
        if not set(task.material_pack_ids) <= material_id_set:
            raise ValueError(f"closed_loop_task_material_unknown:{task.id}")
        if len(task.required_output_kinds) != len(set(task.required_output_kinds)):
            raise ValueError(f"closed_loop_task_outputs_not_unique:{task.id}")
    case_id_set = set(case_ids)
    source_ids = [chain.source_task_id for chain in manifest.memory_reuse_chains]
    follow_up_ids = [chain.follow_up_task_id for chain in manifest.memory_reuse_chains]
    if (
        len(manifest.memory_reuse_chains) != 6
        or len(source_ids) != len(set(source_ids))
        or len(follow_up_ids) != len(set(follow_up_ids))
        or not set([*source_ids, *follow_up_ids]) <= set(task_ids)
        or any(source == follow_up for source, follow_up in zip(source_ids, follow_up_ids, strict=True))
    ):
        raise ValueError("closed_loop_memory_chains_invalid")
    review_scope = manifest.review_scope
    if (
        review_scope.accepted_task_ids != sorted(source_ids)
        or review_scope.personal_memory_task_id not in task_ids
        or not set(review_scope.changes_requested_case_ids) <= case_id_set
    ):
        raise ValueError("closed_loop_review_scope_invalid")
    catalog_versions = [item.catalog_version for item in manifest.catalogs]
    profile_names = [item.name for item in manifest.pilot_profiles]
    if len(catalog_versions) != 2 or len(catalog_versions) != len(set(catalog_versions)):
        raise ValueError("closed_loop_catalog_scope_invalid")
    if len(profile_names) != 10 or len(profile_names) != len(set(profile_names)):
        raise ValueError("closed_loop_pilot_profile_scope_invalid")
    fault_case_ids = [item.case_id for item in manifest.fault_cases]
    fault_injection_points = [item.injection_point for item in manifest.fault_cases]
    if (
        len(fault_case_ids) != 8
        or len(fault_case_ids) != len(set(fault_case_ids))
        or len(fault_injection_points) != len(set(fault_injection_points))
        or not set(fault_case_ids) <= case_id_set
    ):
        raise ValueError("closed_loop_fault_scope_invalid")
    if (
        len(manifest.core_pr_case_ids) != 24
        or len(manifest.core_pr_case_ids) != len(set(manifest.core_pr_case_ids))
        or not set(manifest.core_pr_case_ids) <= case_id_set
    ):
        raise ValueError("closed_loop_core_pr_scope_invalid")


def render_case_input(dataset: ClosedLoopEvaluationDataset, case: ClosedLoopCaseV1) -> str:
    tasks = {task.id: task for task in dataset.tasks}
    materials = {material.id: material for material in dataset.material_packs}
    task = tasks[case.task_id]
    material_sections = []
    for material_id in task.material_pack_ids:
        material = materials[material_id]
        material_sections.append(
            f"[{material.id} {material.name}]\n" + "\n".join(f"- {fact}" for fact in material.facts)
        )
    return "\n\n".join(
        [
            "[SYNTHETIC EVALUATION DATA]",
            f"Case: {case.id}",
            f"Goal: {task.goal}",
            *material_sections,
            f"Variant directive: {case.input_directive}",
        ]
    )


def estimate_case_input_tokens(payload: str) -> int:
    """Return a conservative dependency-free upper bound for fixture preflight."""

    return len(payload)


def scan_sensitive_text(payload: str) -> list[str]:
    patterns = {
        "openai_key": r"\bsk-[A-Za-z0-9_-]{16,}\b",
        "aws_access_key": r"\bAKIA[0-9A-Z]{16}\b",
        "private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        "bearer_token": r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}",
        "assigned_secret": r"(?i)\b(?:api[_-]?key|access[_-]?token|password)\s*[:=]\s*[A-Za-z0-9._~+/=-]{12,}",
    }
    return [name for name, pattern in patterns.items() if re.search(pattern, payload)]


def validate_evaluation_dataset(dataset: ClosedLoopEvaluationDataset) -> ClosedLoopValidationReport:
    from agentmesh.models import SkillSourceScope
    from agentmesh.skill_runtime.discovery import SkillRoot, discover_skills
    from agentmesh.skill_runtime.profiles import (
        load_capability_profile_record,
        profile_matches_skill,
        profile_path,
    )
    from agentmesh.task_routing.catalog import load_default_task_catalog, load_universal_task_catalog

    catalogs = {
        catalog.manifest.catalog_version: catalog
        for catalog in (load_default_task_catalog(), load_universal_task_catalog())
    }
    expected_catalogs = {item.catalog_version: item.catalog_hash for item in dataset.manifest.catalogs}
    actual_catalogs = {version: catalog.manifest.catalog_hash for version, catalog in catalogs.items()}
    if expected_catalogs != actual_catalogs:
        raise ValueError("closed_loop_catalog_identity_mismatch")
    universal_catalog = catalogs["user-research-v2"]
    scenario_ids = {task.scenario_id for task in dataset.tasks if task.scenario_id is not None}
    if any(universal_catalog.get_scenario(scenario_id) is None for scenario_id in scenario_ids):
        raise ValueError("closed_loop_scenario_unknown")

    builtin_skills_dir = ROOT / "agentmesh" / "builtin_skills"
    discovery = discover_skills([SkillRoot(builtin_skills_dir, SkillSourceScope.BUILTIN)])
    if any(item.level == "error" for item in discovery.diagnostics):
        raise ValueError("closed_loop_builtin_skill_discovery_failed")
    expected_profiles = {
        identity.name: identity
        for identity in dataset.manifest.pilot_profiles
    }
    if len(expected_profiles) != 10:
        raise ValueError("closed_loop_pilot_profile_count_invalid")
    task_profiles = {task.primary_profile for task in dataset.tasks}
    if task_profiles != set(expected_profiles):
        raise ValueError("closed_loop_task_profile_scope_invalid")
    for task in dataset.tasks:
        skill = discovery.skills.get(task.primary_profile)
        identity = expected_profiles[task.primary_profile]
        if skill is None or skill.content_hash != identity.skill_content_hash:
            raise ValueError(f"closed_loop_profile_identity_mismatch:{task.primary_profile}")
        if hashlib.sha256(profile_path(skill).read_bytes()).hexdigest() != identity.profile_sha256:
            raise ValueError(f"closed_loop_profile_document_mismatch:{task.primary_profile}")
        loaded = load_capability_profile_record(skill)
        if not loaded.declared_planner_eligible or not profile_matches_skill(loaded.profile, skill):
            raise ValueError(f"closed_loop_profile_ineligible:{task.primary_profile}")
        if not set(task.required_output_kinds) <= set(loaded.profile.output_kinds):
            raise ValueError(f"closed_loop_task_outputs_unsupported:{task.id}")
    for case in dataset.cases:
        payload = render_case_input(dataset, case)
        if estimate_case_input_tokens(payload) > 6_000:
            raise ValueError(f"closed_loop_fixture_token_limit:{case.id}")
        sensitive = scan_sensitive_text(payload)
        if sensitive:
            raise ValueError(f"closed_loop_fixture_sensitive:{case.id}:{','.join(sensitive)}")
    return ClosedLoopValidationReport(
        validated_tasks=len(dataset.tasks),
        validated_cases=len(dataset.cases),
        validated_profiles=len(expected_profiles),
        validated_scenarios=len(scenario_ids),
        diagnostics=[],
    )


def load_evaluation_dataset(
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    tasks_path: Path = DEFAULT_TASKS_PATH,
) -> ClosedLoopEvaluationDataset:
    manifest_document = _load_document(manifest_path)
    manifest = ClosedLoopManifestV1.model_validate(manifest_document)
    if not isinstance(manifest_document, dict):
        raise ValueError("closed_loop_manifest_invalid")
    manifest_body = {key: value for key, value in manifest_document.items() if key != "content_hash"}
    if manifest.content_hash != canonical_json_sha256(manifest_body):
        raise ValueError("closed_loop_manifest_hash_mismatch")
    tasks_bytes = tasks_path.read_bytes()
    document = ClosedLoopTasksDocumentV1.model_validate(_load_document(tasks_path))
    if manifest.dataset_version != document.dataset_version:
        raise ValueError("closed_loop_dataset_version_mismatch")
    if manifest.tasks_file != tasks_path.name:
        raise ValueError("closed_loop_tasks_filename_mismatch")
    _validate_dataset_integrity(
        manifest,
        document,
        tasks_sha256=hashlib.sha256(tasks_bytes).hexdigest(),
    )
    return ClosedLoopEvaluationDataset(
        manifest=manifest,
        material_packs=document.material_packs,
        tasks=document.tasks,
        cases=document.cases,
    )
