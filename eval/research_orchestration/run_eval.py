#!/usr/bin/env python3
"""Validate the fixed competitive-research assets and score release observations.

Evidence-support counts must come from human inspection; this script never
synthesizes them. Human A/B ratings and the 10-person pilot remain external gates.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = ROOT / "eval" / "research_orchestration" / "competitive-research-v1.jsonl"
DEFAULT_RUBRIC = ROOT / "eval" / "research_orchestration" / "rubric-v1.yaml"
CATEGORY_COUNTS = {
    "clear_low_complexity": 5,
    "ambiguous_scope": 5,
    "conflict_or_stale": 5,
    "insufficient_or_adversarial": 5,
}
OBSERVATION_FIELDS = {
    "case_id",
    "completed",
    "factual_claim_count",
    "factual_claims_with_evidence",
    "evidence_support_reviewed_fact_count",
    "evidence_support_supported_fact_count",
    "severity_1_unsupported_fact_count",
    "plan_accepted_without_replan",
    "time_to_plan_seconds",
    "end_to_end_seconds",
    "model_call_count",
    "model_receipt_count",
    "tool_call_count",
    "tool_receipt_count",
    "v1_provider_cost_units",
    "v2_provider_cost_units",
    "provider_cost_unit",
}


@dataclass(frozen=True, slots=True)
class ResearchCase:
    id: str
    category: str
    request: str
    requires_clarification: bool
    expected_gap_codes: tuple[str, ...]
    risk_tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MachineObservation:
    case_id: str
    completed: bool
    factual_claim_count: int
    factual_claims_with_evidence: int
    evidence_support_reviewed_fact_count: int
    evidence_support_supported_fact_count: int
    severity_1_unsupported_fact_count: int
    plan_accepted_without_replan: bool
    time_to_plan_seconds: float
    end_to_end_seconds: float
    model_call_count: int
    model_receipt_count: int
    tool_call_count: int
    tool_receipt_count: int
    v1_provider_cost_units: float
    v2_provider_cost_units: float
    provider_cost_unit: str


def _json_lines(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError(f"file_unreadable:{path.name}") from error
    values: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue
        try:
            value = json.loads(raw_line)
        except json.JSONDecodeError as error:
            raise ValueError(f"jsonl_invalid:{path.name}:{line_number}") from error
        if not isinstance(value, dict):
            raise ValueError(f"jsonl_row_invalid:{path.name}:{line_number}")
        values.append(value)
    return values


def load_cases(path: Path = DEFAULT_DATASET) -> list[ResearchCase]:
    rows = _json_lines(path)
    if len(rows) != 20:
        raise ValueError("dataset_must_contain_20_cases")
    cases: list[ResearchCase] = []
    for index, row in enumerate(rows, start=1):
        if set(row) != {"id", "category", "request", "expected"}:
            raise ValueError(f"dataset_case_invalid:{index}")
        expected = row["expected"]
        if not isinstance(expected, dict) or set(expected) != {
            "requires_clarification",
            "expected_gap_codes",
            "risk_tags",
        }:
            raise ValueError(f"dataset_expectation_invalid:{index}")
        if (
            not isinstance(row["id"], str)
            or not row["id"].strip()
            or not isinstance(row["category"], str)
            or row["category"] not in CATEGORY_COUNTS
            or not isinstance(row["request"], str)
            or not row["request"].strip()
            or not isinstance(expected["requires_clarification"], bool)
            or not isinstance(expected["expected_gap_codes"], list)
            or not all(isinstance(value, str) and value for value in expected["expected_gap_codes"])
            or not isinstance(expected["risk_tags"], list)
            or not all(isinstance(value, str) and value for value in expected["risk_tags"])
        ):
            raise ValueError(f"dataset_case_invalid:{index}")
        cases.append(
            ResearchCase(
                id=row["id"].strip(),
                category=row["category"],
                request=row["request"].strip(),
                requires_clarification=expected["requires_clarification"],
                expected_gap_codes=tuple(expected["expected_gap_codes"]),
                risk_tags=tuple(expected["risk_tags"]),
            )
        )
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("dataset_case_ids_not_unique")
    if len({case.request for case in cases}) != len(cases):
        raise ValueError("dataset_requests_not_unique")
    if Counter(case.category for case in cases) != Counter(CATEGORY_COUNTS):
        raise ValueError("dataset_category_distribution_invalid")
    if any(case.requires_clarification for case in cases if case.category == "clear_low_complexity"):
        raise ValueError("clear_case_cannot_require_clarification")
    if any(not case.requires_clarification for case in cases if case.category == "ambiguous_scope"):
        raise ValueError("ambiguous_case_must_require_clarification")
    return cases


def load_rubric(path: Path = DEFAULT_RUBRIC) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"rubric_unreadable:{path.name}") from error
    if not isinstance(value, dict) or value.get("version") != "competitive-research-rubric-v1":
        raise ValueError("rubric_version_invalid")
    dimensions = value.get("dimensions")
    gates = value.get("machine_gates")
    process = value.get("review_process")
    observation_schema = value.get("observation_schema")
    if not isinstance(dimensions, dict) or len(dimensions) != 5:
        raise ValueError("rubric_dimensions_invalid")
    weights = [item.get("weight") for item in dimensions.values() if isinstance(item, dict)]
    if len(weights) != 5 or not math.isclose(sum(weights), 1.0):
        raise ValueError("rubric_dimension_weights_invalid")
    if not isinstance(gates, dict) or set(gates) != {
        "completed_cases_minimum",
        "factual_claim_evidence_coverage_minimum",
        "evidence_support_accuracy_minimum",
        "severity_1_unsupported_facts_maximum",
        "plan_acceptance_without_replan_minimum",
        "time_to_plan_p50_seconds_maximum",
        "end_to_end_p95_seconds_maximum",
        "tool_calls_per_case_maximum",
        "usage_receipt_coverage_minimum",
        "median_provider_cost_ratio_to_v1_maximum",
    }:
        raise ValueError("rubric_machine_gates_invalid")
    if (
        not isinstance(process, dict)
        or process.get("reviewers_per_output") != 2
        or process.get("required_pilot_users") != 10
        or process.get("minimum_pilot_users_reporting_value") != 8
    ):
        raise ValueError("rubric_review_process_invalid")
    if not isinstance(observation_schema, dict) or set(observation_schema.get("required_fields", [])) != OBSERVATION_FIELDS:
        raise ValueError("rubric_observation_schema_invalid")
    return value


def load_observations(path: Path, case_ids: set[str]) -> list[MachineObservation]:
    rows = _json_lines(path)
    if len(rows) != len(case_ids):
        raise ValueError("observations_must_cover_every_case_once")
    observations: list[MachineObservation] = []
    for index, row in enumerate(rows, start=1):
        if set(row) != OBSERVATION_FIELDS:
            raise ValueError(f"observation_invalid:{index}")
        if (
            not isinstance(row["case_id"], str)
            or not isinstance(row["completed"], bool)
            or not isinstance(row["plan_accepted_without_replan"], bool)
            or any(
                not isinstance(row[field], int) or isinstance(row[field], bool) or row[field] < 0
                for field in (
                    "factual_claim_count",
                    "factual_claims_with_evidence",
                    "evidence_support_reviewed_fact_count",
                    "evidence_support_supported_fact_count",
                    "severity_1_unsupported_fact_count",
                    "model_call_count",
                    "model_receipt_count",
                    "tool_call_count",
                    "tool_receipt_count",
                )
            )
            or any(
                not isinstance(row[field], int | float) or isinstance(row[field], bool) or row[field] < 0
                for field in (
                    "time_to_plan_seconds",
                    "end_to_end_seconds",
                    "v1_provider_cost_units",
                    "v2_provider_cost_units",
                )
            )
            or row["factual_claims_with_evidence"] > row["factual_claim_count"]
            or row["evidence_support_reviewed_fact_count"] > row["factual_claims_with_evidence"]
            or row["evidence_support_supported_fact_count"] > row["evidence_support_reviewed_fact_count"]
            or row["model_receipt_count"] > row["model_call_count"]
            or row["tool_receipt_count"] > row["tool_call_count"]
            or row["v1_provider_cost_units"] <= 0
            or not isinstance(row["provider_cost_unit"], str)
            or row["provider_cost_unit"] not in {"currency", "normalized_usage"}
        ):
            raise ValueError(f"observation_invalid:{index}")
        observations.append(MachineObservation(**row))
    observed_ids = {observation.case_id for observation in observations}
    if observed_ids != case_ids or len(observed_ids) != len(observations):
        raise ValueError("observations_case_ids_invalid")
    if len({observation.provider_cost_unit for observation in observations}) != 1:
        raise ValueError("observations_provider_cost_unit_mismatch")
    return observations


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[math.ceil(percentile * len(ordered)) - 1]


def evaluate_machine_gates(observations: Sequence[MachineObservation], gates: dict[str, Any]) -> dict[str, Any]:
    if not observations:
        raise ValueError("observations_required")
    factual_claims = sum(observation.factual_claim_count for observation in observations)
    covered_claims = sum(observation.factual_claims_with_evidence for observation in observations)
    reviewed_facts = sum(observation.evidence_support_reviewed_fact_count for observation in observations)
    supported_facts = sum(observation.evidence_support_supported_fact_count for observation in observations)
    completed = sum(observation.completed for observation in observations)
    plan_acceptance = sum(observation.plan_accepted_without_replan for observation in observations) / len(observations)
    receipt_complete = sum(
        observation.model_call_count == observation.model_receipt_count
        and observation.tool_call_count == observation.tool_receipt_count
        for observation in observations
    )
    median_v1_cost = statistics.median(observation.v1_provider_cost_units for observation in observations)
    median_v2_cost = statistics.median(observation.v2_provider_cost_units for observation in observations)
    metrics = {
        "completed_cases": completed,
        "factual_claim_evidence_coverage": covered_claims / factual_claims if factual_claims else 0.0,
        "evidence_support_accuracy": supported_facts / reviewed_facts if reviewed_facts else 0.0,
        "severity_1_unsupported_facts": sum(
            observation.severity_1_unsupported_fact_count for observation in observations
        ),
        "plan_acceptance_without_replan": plan_acceptance,
        "time_to_plan_p50_seconds": _percentile(
            [observation.time_to_plan_seconds for observation in observations], 0.50
        ),
        "end_to_end_p95_seconds": _percentile(
            [observation.end_to_end_seconds for observation in observations], 0.95
        ),
        "maximum_tool_calls": max(observation.tool_call_count for observation in observations),
        "usage_receipt_coverage": receipt_complete / len(observations),
        "median_provider_cost_ratio_to_v1": median_v2_cost / median_v1_cost,
        "provider_cost_unit": observations[0].provider_cost_unit,
    }
    checks = {
        "completed_cases": metrics["completed_cases"] >= gates["completed_cases_minimum"],
        "factual_claim_evidence_coverage": metrics["factual_claim_evidence_coverage"]
        >= gates["factual_claim_evidence_coverage_minimum"],
        "evidence_support_accuracy": metrics["evidence_support_accuracy"]
        >= gates["evidence_support_accuracy_minimum"],
        "severity_1_unsupported_facts": metrics["severity_1_unsupported_facts"]
        <= gates["severity_1_unsupported_facts_maximum"],
        "plan_acceptance_without_replan": metrics["plan_acceptance_without_replan"]
        >= gates["plan_acceptance_without_replan_minimum"],
        "time_to_plan_p50_seconds": metrics["time_to_plan_p50_seconds"]
        <= gates["time_to_plan_p50_seconds_maximum"],
        "end_to_end_p95_seconds": metrics["end_to_end_p95_seconds"]
        <= gates["end_to_end_p95_seconds_maximum"],
        "maximum_tool_calls": metrics["maximum_tool_calls"] <= gates["tool_calls_per_case_maximum"],
        "usage_receipt_coverage": metrics["usage_receipt_coverage"]
        >= gates["usage_receipt_coverage_minimum"],
        "median_provider_cost_ratio_to_v1": metrics["median_provider_cost_ratio_to_v1"]
        <= gates["median_provider_cost_ratio_to_v1_maximum"],
    }
    return {"metrics": metrics, "checks": checks, "passed": all(checks.values())}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--rubric", type=Path, default=DEFAULT_RUBRIC)
    parser.add_argument("--observations", type=Path, help="optional JSONL with one machine observation per case")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cases = load_cases(args.dataset)
        rubric = load_rubric(args.rubric)
        report: dict[str, Any] = {
            "assets_valid": True,
            "case_count": len(cases),
            "category_counts": dict(sorted(Counter(case.category for case in cases).items())),
            "rubric_version": rubric["version"],
            "machine_gate_evaluated": False,
            "human_review_complete": False,
            "pilot_complete": False,
            "release_gate_passed": False,
        }
        exit_code = 0
        if args.observations is not None:
            observations = load_observations(args.observations, {case.id for case in cases})
            machine = evaluate_machine_gates(observations, rubric["machine_gates"])
            report["machine_gate_evaluated"] = True
            report["machine_gate"] = machine
            exit_code = 0 if machine["passed"] else 1
    except ValueError as error:
        print(json.dumps({"assets_valid": False, "error_code": str(error)}, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
