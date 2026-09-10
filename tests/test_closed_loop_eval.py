from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter

import pytest

from agentmesh.canonical_json import canonical_json_sha256
from eval.closed_loop.contracts import (
    DEFAULT_MANIFEST_PATH,
    DEFAULT_TASKS_PATH,
    estimate_case_input_tokens,
    load_evaluation_dataset,
    render_case_input,
    scan_sensitive_text,
    validate_evaluation_dataset,
)

PILOT_PROFILES = {
    "build-experience-metrics",
    "competitive-analysis",
    "generate-interview-guide",
    "generate-research-plan",
    "generate-survey",
    "generate-usability-test",
    "issue-prioritization",
    "jobs-to-be-done",
    "prd-feasibility",
    "query-experiment-conclusions",
}


def test_closed_loop_dataset_has_24_tasks_and_96_unique_cases() -> None:
    dataset = load_evaluation_dataset(DEFAULT_MANIFEST_PATH, DEFAULT_TASKS_PATH)

    assert len(dataset.tasks) == 24
    assert len(dataset.cases) == 96
    assert len({case.id for case in dataset.cases}) == 96
    assert Counter(case.variant_id for case in dataset.cases) == {
        "V0": 24,
        "V1": 24,
        "V2": 24,
        "V3": 24,
    }
    assert all(case.id == f"CLV1-{case.task_id}-{case.variant_id}" for case in dataset.cases)
    assert Counter(case.security_probe for case in dataset.cases if case.variant_id == "V3") == {
        "prompt_injection": 6,
        "credential_pattern": 6,
        "cross_project_reference": 6,
        "command_replay": 6,
    }
    assert dataset.manifest.content_hash == "32e380502771845bed7408e4456590257547fa5d93fa9f6522ab40fb32d50aa9"


def test_closed_loop_dataset_freezes_materials_profiles_and_execution_modes() -> None:
    dataset = load_evaluation_dataset(DEFAULT_MANIFEST_PATH, DEFAULT_TASKS_PATH)

    assert len(dataset.material_packs) == 8
    assert {material.id for material in dataset.material_packs} == {
        "M01",
        "M02",
        "M03",
        "M04",
        "M05",
        "M06",
        "M07",
        "M08",
    }
    assert all(material.synthetic and material.facts for material in dataset.material_packs)
    assert {task.primary_profile for task in dataset.tasks} == PILOT_PROFILES
    assert {task.id for task in dataset.tasks if task.execution_mode == "deepsearch"} == {"T04", "T05"}
    material_ids = {material.id for material in dataset.material_packs}
    assert all(set(task.material_pack_ids) <= material_ids for task in dataset.tasks)


def test_closed_loop_manifest_limits_review_fault_and_core_ci_scope() -> None:
    dataset = load_evaluation_dataset(DEFAULT_MANIFEST_PATH, DEFAULT_TASKS_PATH)
    manifest = dataset.manifest

    assert len(manifest.memory_reuse_chains) == 6
    assert {chain.source_task_id for chain in manifest.memory_reuse_chains} == {
        "T01",
        "T04",
        "T08",
        "T13",
        "T18",
        "T23",
    }
    assert manifest.review_scope.accepted_task_ids == ["T01", "T04", "T08", "T13", "T18", "T23"]
    assert manifest.review_scope.personal_memory_task_id == "T07"
    assert manifest.review_scope.changes_requested_case_ids == ["CLV1-T10-V2", "CLV1-T16-V2"]
    assert len(manifest.fault_cases) == 8
    assert {fault.injection_point for fault in manifest.fault_cases} == {
        "run_claimed",
        "artifact_sealed",
        "memory_capture_response",
        "receipt_reserved",
        "sqlite_reopen",
        "projection_rebuild",
        "expected_version_conflict",
        "command_replay",
    }
    assert {item.catalog_version for item in manifest.catalogs} == {
        "user-research-v1",
        "user-research-v2",
    }
    assert {item.name for item in manifest.pilot_profiles} == PILOT_PROFILES
    assert len(manifest.core_pr_case_ids) == 24
    assert len(set(manifest.core_pr_case_ids)) == 24
    assert set(manifest.core_pr_case_ids) <= {case.id for case in dataset.cases}


def test_closed_loop_dataset_rejects_task_fixture_hash_drift(tmp_path) -> None:
    manifest_path = tmp_path / "manifest-v1.json"
    tasks_path = tmp_path / "tasks-v1.json"
    manifest_path.write_bytes(DEFAULT_MANIFEST_PATH.read_bytes())
    task_document = json.loads(DEFAULT_TASKS_PATH.read_text(encoding="utf-8"))
    task_document["tasks"][0]["goal"] = "tampered goal"
    tasks_path.write_text(json.dumps(task_document, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="closed_loop_tasks_hash_mismatch"):
        load_evaluation_dataset(manifest_path, tasks_path)


def test_closed_loop_dataset_matches_catalog_profiles_and_scenarios() -> None:
    dataset = load_evaluation_dataset(DEFAULT_MANIFEST_PATH, DEFAULT_TASKS_PATH)

    report = validate_evaluation_dataset(dataset)

    assert report.validated_tasks == 24
    assert report.validated_cases == 96
    assert report.validated_profiles == 10
    assert report.validated_scenarios == 11
    assert report.diagnostics == []


def test_closed_loop_case_inputs_are_bounded_synthetic_and_secret_free() -> None:
    dataset = load_evaluation_dataset(DEFAULT_MANIFEST_PATH, DEFAULT_TASKS_PATH)

    for case in dataset.cases:
        payload = render_case_input(dataset, case)
        assert payload.startswith("[SYNTHETIC EVALUATION DATA]")
        assert estimate_case_input_tokens(payload) <= 6_000
        assert scan_sensitive_text(payload) == []
        if case.variant_id == "V3":
            assert case.security_probe is not None
        else:
            assert case.security_probe is None


def test_closed_loop_dataset_rejects_sensitive_fixture_content(tmp_path) -> None:
    manifest_path = tmp_path / "manifest-v1.json"
    tasks_path = tmp_path / "tasks-v1.json"
    task_document = json.loads(DEFAULT_TASKS_PATH.read_text(encoding="utf-8"))
    task_document["material_packs"][0]["facts"].append("api_key=abcdefghijklmnop")
    tasks_path.write_text(
        json.dumps(task_document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest_document = json.loads(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest_document["tasks_sha256"] = hashlib.sha256(tasks_path.read_bytes()).hexdigest()
    manifest_document.pop("content_hash")
    manifest_document["content_hash"] = canonical_json_sha256(manifest_document)
    manifest_path.write_text(
        json.dumps(manifest_document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    dataset = load_evaluation_dataset(manifest_path, tasks_path)

    with pytest.raises(ValueError, match="closed_loop_fixture_sensitive"):
        validate_evaluation_dataset(dataset)


def test_closed_loop_d0_cli_reports_validation_without_provider_calls() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "eval.run_closed_loop_eval",
            "--mode",
            "validate",
            "--batch",
            "D0",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report == {
        "batch": "D0",
        "case_count": 96,
        "dataset_version": "1",
        "dataset_hash": "32e380502771845bed7408e4456590257547fa5d93fa9f6522ab40fb32d50aa9",
        "diagnostics": [],
        "material_pack_count": 8,
        "mode": "validate",
        "profile_count": 10,
        "provider_calls": 0,
        "scenario_count": 11,
        "task_count": 24,
    }
