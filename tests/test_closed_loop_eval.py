from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
from collections import Counter

import pytest
from agents.testing import ScriptedModel, assistant_message

from agentmesh.agent_runtime.model_factory import SelectedSDKModel
from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.store import SQLiteStore
from eval.closed_loop.contracts import (
    DEFAULT_MANIFEST_PATH,
    DEFAULT_TASKS_PATH,
    estimate_case_input_tokens,
    load_evaluation_dataset,
    render_case_input,
    scan_sensitive_text,
    validate_evaluation_dataset,
)
from eval.closed_loop.r2_runner import (
    MissingInputOutputV1,
    run_real_r2,
    validate_missing_input_output,
)
from eval.closed_loop.real_runner import (
    RealDeliverableV1,
    RealTaskOutputV1,
    run_real_r1,
    validate_real_output,
)
from eval.closed_loop.runner import run_deterministic_evaluation

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


def test_d1_executes_all_cases_to_their_expected_boundary_without_provider_calls(tmp_path) -> None:
    dataset = load_evaluation_dataset(DEFAULT_MANIFEST_PATH, DEFAULT_TASKS_PATH)

    report = run_deterministic_evaluation(dataset, output_dir=tmp_path)

    assert report.batch == "D1"
    assert report.case_count == 96
    assert report.provider_calls == 0
    assert report.scripted_model_calls == 48
    assert report.boundary_counts == {
        "sealed_artifact": 24,
        "input_gap": 24,
        "partial_or_gap": 24,
        "security_boundary": 24,
    }
    assert all(item.actual_boundary == item.expected_boundary for item in report.results)
    assert report.task_count == 96
    assert report.run_count == 72
    assert report.artifact_count == 48
    assert report.synthetic_task_review_count == 9
    assert report.synthetic_memory_review_count == 6
    assert report.memory_use_receipt_count == 6
    assert report.fault_case_count == 8
    assert report.failure_count == 0
    assert (tmp_path / "d1-summary.json").is_file()


def test_d1_cli_runs_only_the_bounded_core_pr_case_set(tmp_path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "eval.run_closed_loop_eval",
            "--mode",
            "deterministic",
            "--batch",
            "D1",
            "--case-set",
            "core_pr",
            "--output",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert summary["batch"] == "D1"
    assert summary["case_set"] == "core_pr"
    assert summary["case_count"] == 24
    assert summary["provider_calls"] == 0
    assert summary["failure_count"] == 0
    assert summary["results_path"] == str(tmp_path / "d1-summary.json")


def test_r1_cli_requires_explicit_real_provider_acknowledgement(tmp_path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "eval.run_closed_loop_eval",
            "--mode",
            "real",
            "--batch",
            "R1",
            "--output",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "--ack-real-provider" in completed.stderr
    assert not (tmp_path / "r1-checkpoint.json").exists()


def test_r1_validator_does_not_treat_jtbd_as_a_tbd_placeholder() -> None:
    dataset = load_evaluation_dataset(DEFAULT_MANIFEST_PATH, DEFAULT_TASKS_PATH)
    case = next(item for item in dataset.cases if item.id == "CLV1-T18-V0")
    task = next(item for item in dataset.tasks if item.id == "T18")
    output = RealTaskOutputV1(
        case_id=case.id,
        summary="A complete Jobs to Be Done analysis based on the synthetic interviews.",
        deliverables=[
            RealDeliverableV1(
                kind="jtbd_analysis",
                content="The JTBD analysis separates the triggering situation, functional job, emotional job, and "
                "evidence-backed desired outcomes for first purchase.",
            ),
            RealDeliverableV1(
                kind="opportunity_definition",
                content="Prioritize transparent handoff state, source visibility, and recoverable execution while "
                "keeping external publication behind explicit confirmation.",
            ),
        ],
    )

    assert validate_real_output(output, case=case, task=task, requires_memory_citation=False) == []


def test_r1_runner_can_checkpoint_one_real_model_contract_with_scripted_model(tmp_path) -> None:
    dataset = load_evaluation_dataset(DEFAULT_MANIFEST_PATH, DEFAULT_TASKS_PATH)
    output = RealTaskOutputV1(
        case_id="CLV1-T01-V0",
        summary="A complete synthetic experience-metrics delivery.",
        deliverables=[
            RealDeliverableV1(
                kind="experience_metrics",
                content="Define relevance success, reformulation, no-click, and satisfaction metrics with segment cuts. "
                "Track weekly baselines, guardrails, and owners for every metric.",
            ),
            RealDeliverableV1(
                kind="measurement_plan",
                content="Instrument query, result, click, reformulation, and satisfaction events. Compare weekly cohorts and "
                "investigate changes outside the agreed guardrail thresholds.",
            ),
        ],
        assumptions=["All fixture data is synthetic."],
        limitations=[],
        next_actions=["Validate event definitions."],
    )
    selected = SelectedSDKModel(
        model=ScriptedModel([[assistant_message(output.model_dump_json())]]),
        requested_model="test",
        actual_model="scripted-test",
    )

    report = asyncio.run(
        run_real_r1(
            dataset,
            selected=selected,
            output_dir=tmp_path,
            max_runs=1,
            max_total_tokens=100_000,
            initial_reserved_tokens=0,
        )
    )

    assert report.completed_cases == 1
    assert report.stopped_reason is None
    assert report.results[0].case_id == "CLV1-T01-V0"
    assert report.results[0].contract_passed is True
    assert report.results[0].status == "passed"
    assert report.usage.total_tokens == 0
    assert report.budget_used_tokens == 0
    assert (tmp_path / "r1-checkpoint.json").is_file()
    assert (tmp_path / "cases" / "CLV1-T01-V0.json").is_file()

    resumed = asyncio.run(
        run_real_r1(
            dataset,
            selected=SelectedSDKModel(
                model=ScriptedModel([]),
                requested_model="test",
                actual_model="scripted-test",
            ),
            output_dir=tmp_path,
            max_runs=1,
            max_total_tokens=100_000,
            initial_reserved_tokens=0,
        )
    )
    assert resumed.results == report.results
    assert resumed.usage == report.usage


def test_r2_validator_requires_missing_input_and_clarifying_question() -> None:
    dataset = load_evaluation_dataset(DEFAULT_MANIFEST_PATH, DEFAULT_TASKS_PATH)
    case = next(item for item in dataset.cases if item.id == "CLV1-T06-V1")
    task = next(item for item in dataset.tasks if item.id == "T06")
    output = MissingInputOutputV1(
        case_id=case.id,
        disposition="clarification_required",
        missing_inputs=["目标访谈人群"],
        clarifying_questions=["本次应访谈哪类首次使用者？"],
        bounded_deliverables=[],
        assumptions=[],
        limitations=["未提供目标人群，不能确定问题措辞和招募口径。"],
    )

    assert validate_missing_input_output(output, case=case, task=task) == []


def test_r2_runner_checkpoints_one_missing_input_case(tmp_path) -> None:
    dataset = load_evaluation_dataset(DEFAULT_MANIFEST_PATH, DEFAULT_TASKS_PATH)
    output = MissingInputOutputV1(
        case_id="CLV1-T01-V1",
        disposition="clarification_required",
        missing_inputs=["搜索成功指标定义"],
        clarifying_questions=["成功搜索应由点击、不再改写还是满意度定义？"],
        bounded_deliverables=[],
        assumptions=[],
        limitations=["未获得成功指标定义，不生成确定性指标树。"],
    )
    selected = SelectedSDKModel(
        model=ScriptedModel([[assistant_message(output.model_dump_json())]]),
        requested_model="test",
        actual_model="scripted-test",
    )
    repository = SQLiteStore(tmp_path / "r2.sqlite3")

    report = asyncio.run(
        run_real_r2(
            dataset,
            selected=selected,
            repository=repository,
            output_dir=tmp_path,
            max_runs=1,
            max_total_tokens=100_000,
        )
    )

    assert report.completed_cases == 1
    assert report.results[0].case_id == "CLV1-T01-V1"
    assert report.results[0].contract_passed is True
    assert report.results[0].preflight_status == "complete"
    assert (tmp_path / "r2-checkpoint.json").is_file()
    repository.close()
