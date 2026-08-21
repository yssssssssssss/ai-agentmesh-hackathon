from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from agentmesh.research_orchestration.v3.deliverable import (
    CompetitiveAnalysisTextPayloadV1,
    ResearchDeliverableV3,
)
from agentmesh.research_orchestration.v3.evidence import EvidenceManifestV3
from agentmesh.research_orchestration.v3.execution_plan import ExecutionPlanV3, PlanCandidateSetV3
from agentmesh.research_orchestration.v3.problem_graph import ProblemGraphV1
from agentmesh.research_orchestration.v3.report_document import ReportDocumentV3
from agentmesh.research_orchestration.v3.requirement import ResearchTaskV3
from agentmesh.research_orchestration.v3.review import ReportReviewV3
from agentmesh.research_orchestration.v3.snapshots import ResearchControlSnapshotV3
from agentmesh.research_orchestration.v3.web_projection import WorkbenchAggregateV1
from research_v3_contract_samples import (
    candidate_set_body,
    competitive_text_body,
    control_snapshot_body,
    deliverable_body,
    evidence_body,
    plan_body,
    problem_graph_body,
    report_body,
    requirement_body,
    review_body,
)


def workbench_idle_body() -> dict:
    return json.loads(
        Path("tests/fixtures/research_v3_workbench/idle.json").read_text(encoding="utf-8")
    )


CASES = (
    # This matrix claims same-record structural parity only. Canonical hash bindings and
    # cross-record lineage/ownership invariants are intentionally enforced at typed ports.

    ("research-task-v3.schema.json", "research-task-v3", ResearchTaskV3, requirement_body, True),
    ("problem-graph-v1.schema.json", "problem-graph-v1", ProblemGraphV1, problem_graph_body, True),
    ("plan-candidates-v3.schema.json", "plan-candidates-v3", PlanCandidateSetV3, candidate_set_body, True),
    ("execution-plan-v3.schema.json", "execution-plan-v3", ExecutionPlanV3, plan_body, True),
    (
        "research-control-snapshot-v3.schema.json",
        "research-control-snapshot-v3",
        ResearchControlSnapshotV3,
        control_snapshot_body,
        True,
    ),
    (
        "competitive-analysis-text-v1.schema.json",
        "competitive-analysis-text-v1",
        CompetitiveAnalysisTextPayloadV1,
        competitive_text_body,
        False,
    ),
    (
        "research-deliverable-v3.schema.json",
        "research-deliverable-v3",
        ResearchDeliverableV3,
        deliverable_body,
        True,
    ),
    ("report-review-v3.schema.json", "report-review-v3", ReportReviewV3, review_body, True),
    ("report-document-v3.schema.json", "report-document-v3", ReportDocumentV3, report_body, True),
    (
        "evidence-manifest-v3.schema.json",
        "evidence-manifest-v3",
        EvidenceManifestV3,
        evidence_body,
        True,
    ),
    (
        "research-workbench-aggregate-v1.schema.json",
        "research-workbench-aggregate-v1",
        WorkbenchAggregateV1,
        workbench_idle_body,
        True,
    ),
)


def _schema(filename: str) -> dict:
    return json.loads(Path("agentmesh/schemas/research", filename).read_text(encoding="utf-8"))


def test_parity_matrix_covers_every_committed_research_schema() -> None:
    committed = {path.name for path in Path("agentmesh/schemas/research").glob("*.schema.json")}
    assert {case[0] for case in CASES} == committed
    assert len(CASES) == 11


@pytest.mark.parametrize(("filename", "identity", "model_type", "sample_factory", "has_discriminator"), CASES)
def test_target_schema_identity_and_positive_fixture_parity(
    filename,
    identity,
    model_type,
    sample_factory,
    has_discriminator,
) -> None:
    schema = _schema(filename)
    generated = model_type.model_json_schema(mode="validation")
    generated["$id"] = identity
    generated["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    assert schema == generated
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == identity
    jsonschema.Draft202012Validator.check_schema(schema)
    sample = sample_factory()
    model_type.model_validate(sample)
    jsonschema.Draft202012Validator(schema).validate(sample)
    assert has_discriminator == ("schema_version" in sample)


@pytest.mark.parametrize(
    ("filename", "identity", "model_type", "sample_factory", "has_discriminator"),
    [case for case in CASES if case[4]],
)
def test_target_schema_and_pydantic_both_reject_wrong_discriminator(
    filename,
    identity,
    model_type,
    sample_factory,
    has_discriminator,
) -> None:
    assert has_discriminator
    sample = sample_factory()
    sample["schema_version"] = f"not-{identity}"
    with pytest.raises(ValidationError):
        model_type.model_validate(sample)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(_schema(filename)).validate(sample)


@pytest.mark.parametrize(
    ("filename", "identity", "model_type", "sample_factory", "has_discriminator"),
    [case for case in CASES if case[4]],
)
def test_target_schema_and_pydantic_both_require_top_level_discriminator(
    filename,
    identity,
    model_type,
    sample_factory,
    has_discriminator,
) -> None:
    del identity
    assert has_discriminator
    sample = sample_factory()
    sample.pop("schema_version")
    with pytest.raises(ValidationError):
        model_type.model_validate(sample)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(_schema(filename)).validate(sample)


@pytest.mark.parametrize(("filename", "identity", "model_type", "sample_factory", "has_discriminator"), CASES)
def test_target_schema_and_pydantic_both_reject_unknown_fields(
    filename,
    identity,
    model_type,
    sample_factory,
    has_discriminator,
) -> None:
    del identity, has_discriminator
    sample = deepcopy(sample_factory())
    sample["unexpected"] = True
    with pytest.raises(ValidationError):
        model_type.model_validate(sample)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(_schema(filename)).validate(sample)


def _assert_model_and_schema_reject(model_type, filename: str, sample: dict) -> None:
    with pytest.raises(ValidationError):
        model_type.model_validate(sample)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(_schema(filename)).validate(sample)


def test_unique_items_are_enforced_by_models_and_supporting_schemas() -> None:
    requirement = requirement_body()
    requirement["comparison_dimensions"] = ["capabilities", "capabilities"]
    _assert_model_and_schema_reject(ResearchTaskV3, "research-task-v3.schema.json", requirement)

    graph = problem_graph_body()
    graph["questions"][0]["evidence_requirements"][0]["accepted_classes"] = [
        "public_source",
        "public_source",
    ]
    _assert_model_and_schema_reject(ProblemGraphV1, "problem-graph-v1.schema.json", graph)

    candidates = candidate_set_body()
    candidates["candidates"][0]["proposed_steps"][0]["question_ids"] = [
        "q_capabilities",
        "q_capabilities",
    ]
    _assert_model_and_schema_reject(PlanCandidateSetV3, "plan-candidates-v3.schema.json", candidates)

    report = report_body()
    report["sections"][5]["blocks"][0]["evidence_ids"] = ["evidence_1", "evidence_1"]
    _assert_model_and_schema_reject(ReportDocumentV3, "report-document-v3.schema.json", report)

    snapshot = control_snapshot_body()
    snapshot["actors"][0]["required_tool_ids"] = ["tool_1", "tool_1"]
    _assert_model_and_schema_reject(
        ResearchControlSnapshotV3,
        "research-control-snapshot-v3.schema.json",
        snapshot,
    )

    evidence = evidence_body()
    evidence["evidence"][0]["source"]["risk_flags"] = ["risk_1", "risk_1"]
    _assert_model_and_schema_reject(EvidenceManifestV3, "evidence-manifest-v3.schema.json", evidence)

    payload = competitive_text_body()
    payload["visual_evidence"] = [{"assetId": "asset_1"}]
    _assert_model_and_schema_reject(
        CompetitiveAnalysisTextPayloadV1,
        "competitive-analysis-text-v1.schema.json",
        payload,
    )


def test_nested_discriminators_and_review_cardinality_have_structural_parity() -> None:
    deliverable = deliverable_body()
    deliverable["finding_graph"]["findings"][0].pop("kind")
    _assert_model_and_schema_reject(
        ResearchDeliverableV3,
        "research-deliverable-v3.schema.json",
        deliverable,
    )

    report = report_body()
    report["sections"][1]["blocks"][0].pop("type")
    _assert_model_and_schema_reject(ReportDocumentV3, "report-document-v3.schema.json", report)

    review = review_body()
    review["dimensions"].pop()
    _assert_model_and_schema_reject(ReportReviewV3, "report-review-v3.schema.json", review)

    review = review_body()
    review["deterministic_checks"].pop()
    _assert_model_and_schema_reject(ReportReviewV3, "report-review-v3.schema.json", review)
