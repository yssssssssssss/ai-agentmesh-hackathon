from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from eval.research_orchestration.run_eval import (
    CATEGORY_COUNTS,
    MachineObservation,
    evaluate_machine_gates,
    load_cases,
    load_observations,
    load_rubric,
)


def test_fixed_research_dataset_and_rubric_are_release_ready() -> None:
    cases = load_cases()
    rubric = load_rubric()

    assert len(cases) == 20
    assert {category: sum(case.category == category for case in cases) for category in CATEGORY_COUNTS} == CATEGORY_COUNTS
    assert sum(case.requires_clarification for case in cases) == 5
    assert rubric["machine_gates"]["completed_cases_minimum"] == 18
    assert rubric["review_process"]["required_pilot_users"] == 10


def test_observations_require_exact_case_coverage(tmp_path: Path) -> None:
    path = tmp_path / "observations.jsonl"
    path.write_text(
        json.dumps(
            {
                "case_id": "unknown",
                "completed": True,
                "factual_claim_count": 1,
                "factual_claims_with_evidence": 1,
                "evidence_support_reviewed_fact_count": 1,
                "evidence_support_supported_fact_count": 1,
                "severity_1_unsupported_fact_count": 0,
                "plan_accepted_without_replan": True,
                "time_to_plan_seconds": 1,
                "end_to_end_seconds": 2,
                "model_call_count": 1,
                "model_receipt_count": 1,
                "tool_call_count": 1,
                "tool_receipt_count": 1,
                "v1_provider_cost_units": 1,
                "v2_provider_cost_units": 1,
                "provider_cost_unit": "normalized_usage",
            }
        ),
        encoding="utf-8",
    )

    try:
        load_observations(path, {"clear_01", "clear_02"})
    except ValueError as error:
        assert str(error) == "observations_must_cover_every_case_once"
    else:
        raise AssertionError("incomplete observations must be rejected")


def test_machine_gate_reports_failures_without_claiming_human_release() -> None:
    rubric = load_rubric()
    observations = [
        MachineObservation(
            case_id=f"case_{index}",
            completed=index < 18,
            factual_claim_count=2,
            factual_claims_with_evidence=2,
            evidence_support_reviewed_fact_count=2,
            evidence_support_supported_fact_count=2,
            severity_1_unsupported_fact_count=0,
            plan_accepted_without_replan=index < 16,
            time_to_plan_seconds=20,
            end_to_end_seconds=300,
            model_call_count=1,
            model_receipt_count=1,
            tool_call_count=4,
            tool_receipt_count=4,
            v1_provider_cost_units=100,
            v2_provider_cost_units=200,
            provider_cost_unit="normalized_usage",
        )
        for index in range(20)
    ]

    report = evaluate_machine_gates(observations, rubric["machine_gates"])

    assert report["passed"]
    assert all(report["checks"].values())
    failed = observations.copy()
    failed[0] = replace(failed[0], factual_claims_with_evidence=1)
    failed_report = evaluate_machine_gates(failed, rubric["machine_gates"])
    assert not failed_report["passed"]
    assert not failed_report["checks"]["factual_claim_evidence_coverage"]

    unsupported = [replace(observation, evidence_support_supported_fact_count=1) for observation in observations]
    unsupported_report = evaluate_machine_gates(unsupported, rubric["machine_gates"])
    assert not unsupported_report["checks"]["evidence_support_accuracy"]

    missing_receipt = observations.copy()
    missing_receipt[0] = replace(missing_receipt[0], tool_receipt_count=3)
    missing_receipt_report = evaluate_machine_gates(missing_receipt, rubric["machine_gates"])
    assert not missing_receipt_report["checks"]["usage_receipt_coverage"]

    expensive = [replace(observation, v2_provider_cost_units=201) for observation in observations]
    expensive_report = evaluate_machine_gates(expensive, rubric["machine_gates"])
    assert not expensive_report["checks"]["median_provider_cost_ratio_to_v1"]
