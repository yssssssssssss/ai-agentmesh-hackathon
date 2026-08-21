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
