from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_bytes, strict_json_v3_loads
from agentmesh.research_orchestration.v3.web_projection import (
    ResearchV2HistoryWorkbenchAggregateV1,
    ResearchV3WorkbenchAggregateV1,
    WorkbenchAggregateV1,
)
from research_v3_workbench_samples import WORKBENCH_STATES

FIXTURE_ROOT = Path("tests/fixtures/research_v3_workbench")
SCHEMA_PATH = Path("agentmesh/schemas/research/research-workbench-aggregate-v1.schema.json")


def _fixture(state: str) -> dict:
    value = strict_json_v3_loads((FIXTURE_ROOT / f"{state}.json").read_bytes())
    assert isinstance(value, dict)
    return value


def test_eight_workbench_fixtures_are_exact_canonical_schema_valid_aggregates() -> None:
    fixture_paths = sorted(FIXTURE_ROOT.glob("*.json"))
    assert tuple(path.stem for path in fixture_paths) == tuple(sorted(WORKBENCH_STATES))
    schema = strict_json_v3_loads(SCHEMA_PATH.read_bytes())

    for state in WORKBENCH_STATES:
        path = FIXTURE_ROOT / f"{state}.json"
        raw = _fixture(state)
        aggregate = WorkbenchAggregateV1.model_validate(raw)
        assert isinstance(aggregate.root, ResearchV3WorkbenchAggregateV1)
        assert aggregate.root.workflow.state == state
        assert path.read_bytes() == canonical_json_v3_bytes(aggregate.model_dump(mode="python")) + b"\n"
        jsonschema.Draft202012Validator(schema).validate(raw)


def test_workbench_state_fixtures_freeze_the_full_progressive_projection() -> None:
    expected_present = {
        "idle": set(),
        "clarify": {"requirement"},
        "candidates": {"requirement", "candidates"},
        "plan": {"requirement", "candidates", "selected_plan"},
        "approval": {"requirement", "candidates", "selected_plan"},
        "dag_or_executing": {"requirement", "candidates", "selected_plan", "attempt"},
        "paused": {"requirement", "candidates", "selected_plan", "attempt", "recovery"},
        "text_report": {
            "requirement",
            "candidates",
            "selected_plan",
            "attempt",
            "evidence",
            "deliverable",
            "review",
            "report",
        },
    }
    field_names = (
        "requirement",
        "candidates",
        "selected_plan",
        "attempt",
        "recovery",
        "evidence",
        "deliverable",
        "review",
        "report",
    )

    for state, expected in expected_present.items():
        aggregate = WorkbenchAggregateV1.model_validate(_fixture(state)).root
        assert isinstance(aggregate, ResearchV3WorkbenchAggregateV1)
        assert {name for name in field_names if getattr(aggregate, name) is not None} == expected

    report = WorkbenchAggregateV1.model_validate(_fixture("text_report")).root
    assert isinstance(report, ResearchV3WorkbenchAggregateV1)
    assert report.attempt is not None
    assert tuple(step.result.step_number for step in report.attempt.steps if step.result is not None) == (1, 2)
    assert report.evidence is not None
    assert report.deliverable is not None
    assert report.review is not None
    assert report.report is not None


def test_workbench_projection_rejects_unknown_fields_and_cross_attempt_report_lineage() -> None:
    idle = _fixture("idle")
    idle["ambient_state"] = {"must": "not be consulted"}
    with pytest.raises(ValidationError):
        WorkbenchAggregateV1.model_validate(idle)

    report = deepcopy(_fixture("text_report"))
    report["report"]["content"]["attempt_id"] = "attempt_other"
    with pytest.raises(ValidationError):
        WorkbenchAggregateV1.model_validate(report)


def test_v2_history_has_an_explicit_read_only_discriminator() -> None:
    body = {
        "schema_version": "research-workbench-aggregate-v1",
        "projection_kind": "research-v2-history",
        "orchestration_version": "research-v2",
        "read_only": True,
        "run_id": "run_v2_history",
        "history_payload": {
            "schema_version": "research-task-v2",
            "status": "completed",
        },
        "provenance": {
            "source_kind": "v2_history_adapter",
            "projection_schema_version": "research-workbench-aggregate-v1",
            "projected_at": "2026-08-21T01:00:00Z",
            "source_state_version": 9,
            "baseline_state_id": None,
        },
    }
    aggregate = WorkbenchAggregateV1.model_validate(body)
    assert isinstance(aggregate.root, ResearchV2HistoryWorkbenchAggregateV1)
    assert aggregate.root.read_only is True

    body["orchestration_version"] = "research-v3"
    with pytest.raises(ValidationError):
        WorkbenchAggregateV1.model_validate(body)


def test_projection_contract_remains_non_production() -> None:
    source = Path("agentmesh/research_orchestration/v3/web_projection.py").read_text(encoding="utf-8")
    assert "research_orchestration.api" not in source
    assert "FastAPI" not in source
