from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from agentmesh.research_orchestration.v3.canonical import (
    canonical_json_v3_bytes,
    canonical_json_v3_sha256,
    strict_json_v3_loads,
)
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
    assert isinstance(schema, dict)
    assert "VerifiedArtifactContentV3" not in schema.get("$defs", {})
    assert "EvidenceManifestV3" not in schema.get("$defs", {})

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
    evidence_dump = report.evidence.model_dump(mode="json")
    assert set(evidence_dump) == {
        "artifact",
        "presentation_mode",
        "run_id",
        "plan_version_id",
        "attempt_id",
        "evidence",
    }
    assert "manifest" not in evidence_dump
    assert "verified_artifacts" not in evidence_dump
    assert set(evidence_dump["evidence"][0]) == {
        "evidence_id",
        "source_id",
        "title",
        "url",
        "quote",
        "gap_metadata",
        "provenance",
    }
    assert evidence_dump["evidence"][0]["source_id"] == "source_alpha"
    assert evidence_dump["evidence"][0]["title"] == "Alpha product documentation"
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


def test_workbench_projection_rejects_selected_plan_and_result_artifact_drift() -> None:
    selected_plan_drift = deepcopy(_fixture("text_report"))
    selected_plan_drift["attempt"]["steps"][0]["expected_outputs"][0]["description"] = "Altered output"
    with pytest.raises(ValidationError, match="selected Plan contracts"):
        WorkbenchAggregateV1.model_validate(selected_plan_drift)

    evidence_drift = deepcopy(_fixture("text_report"))
    evidence_drift["evidence"]["evidence"][0]["provenance"]["artifact"]["artifact_id"] = "artifact_other"
    with pytest.raises(ValidationError, match="successful attempt result"):
        WorkbenchAggregateV1.model_validate(evidence_drift)


def _reseal_report_chain(body: dict) -> None:
    deliverable_artifact = body["deliverable"]["artifact"]
    deliverable_artifact["content_hash"] = canonical_json_v3_sha256(body["deliverable"]["content"])
    body["review"]["content"]["deliverable_artifact"] = deepcopy(deliverable_artifact)
    review_artifact = body["review"]["artifact"]
    review_artifact["content_hash"] = canonical_json_v3_sha256(body["review"]["content"])
    body["report"]["content"]["deliverable_artifact"] = deepcopy(deliverable_artifact)
    body["report"]["content"]["review_artifact"] = deepcopy(review_artifact)
    body["report"]["artifact"]["content_hash"] = canonical_json_v3_sha256(body["report"]["content"])


def test_workbench_projection_rejects_capability_requirement_and_verdict_drift() -> None:
    capability_drift = deepcopy(_fixture("text_report"))
    capability_drift["deliverable"]["content"]["capability_provenance"][0]["result_artifact"][
        "artifact_id"
    ] = "artifact_other"
    _reseal_report_chain(capability_drift)
    with pytest.raises(ValidationError, match="capability Artifact"):
        WorkbenchAggregateV1.model_validate(capability_drift)

    plan_requirement_drift = deepcopy(_fixture("text_report"))
    plan_requirement_drift["selected_plan"]["requirement_version_id"] = "requirement_other"
    plan_requirement_drift["selected_plan"]["payload"]["requirement_version_id"] = "requirement_other"
    plan_requirement_drift["selected_plan"]["plan_hash"] = canonical_json_v3_sha256(
        plan_requirement_drift["selected_plan"]["payload"]
    )
    with pytest.raises(ValidationError, match="selected plan requirement lineage"):
        WorkbenchAggregateV1.model_validate(plan_requirement_drift)

    plan_content_drift = deepcopy(_fixture("text_report"))
    plan_content_drift["selected_plan"]["payload"]["requirement_content_hash"] = "f" * 64
    plan_content_drift["selected_plan"]["plan_hash"] = canonical_json_v3_sha256(
        plan_content_drift["selected_plan"]["payload"]
    )
    with pytest.raises(ValidationError, match="selected plan requirement lineage"):
        WorkbenchAggregateV1.model_validate(plan_content_drift)

    deliverable_requirement_drift = deepcopy(_fixture("text_report"))
    deliverable_requirement_drift["deliverable"]["content"]["requirement_version_id"] = "requirement_other"
    _reseal_report_chain(deliverable_requirement_drift)
    with pytest.raises(ValidationError, match="deliverable requirement lineage"):
        WorkbenchAggregateV1.model_validate(deliverable_requirement_drift)

    review_requirement_drift = deepcopy(_fixture("text_report"))
    review_requirement_drift["review"]["content"]["requirement_version_id"] = "requirement_other"
    _reseal_report_chain(review_requirement_drift)
    with pytest.raises(ValidationError, match="review requirement lineage"):
        WorkbenchAggregateV1.model_validate(review_requirement_drift)

    report_requirement_drift = deepcopy(_fixture("text_report"))
    report_requirement_drift["report"]["content"]["requirement_version_id"] = "requirement_other"
    report_requirement_drift["report"]["artifact"]["content_hash"] = canonical_json_v3_sha256(
        report_requirement_drift["report"]["content"]
    )
    with pytest.raises(ValidationError, match="report requirement lineage"):
        WorkbenchAggregateV1.model_validate(report_requirement_drift)

    revise = deepcopy(_fixture("text_report"))
    revise["review"]["content"]["verdict"] = "revise"
    _reseal_report_chain(revise)
    with pytest.raises(ValidationError, match="pass review"):
        WorkbenchAggregateV1.model_validate(revise)


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
