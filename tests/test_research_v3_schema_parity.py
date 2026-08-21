from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from agentmesh.research_orchestration.v3.deliverable import ResearchDeliverableV3
from agentmesh.research_orchestration.v3.execution_plan import ExecutionPlanV3
from agentmesh.research_orchestration.v3.report_document import ReportDocumentV3
from agentmesh.research_orchestration.v3.requirement import ResearchTaskV3
from agentmesh.research_orchestration.v3.review import ReportReviewV3
from research_v3_contract_samples import (
    deliverable_body,
    plan_body,
    report_body,
    requirement_body,
    review_body,
)

CASES = (
    ("research-task-v3.schema.json", "research-task-v3", ResearchTaskV3, requirement_body),
    ("execution-plan-v3.schema.json", "execution-plan-v3", ExecutionPlanV3, plan_body),
    (
        "research-deliverable-v3.schema.json",
        "research-deliverable-v3",
        ResearchDeliverableV3,
        deliverable_body,
    ),
    ("report-review-v3.schema.json", "report-review-v3", ReportReviewV3, review_body),
    ("report-document-v3.schema.json", "report-document-v3", ReportDocumentV3, report_body),
)


def _schema(filename: str) -> dict:
    return json.loads(Path("agentmesh/schemas/research", filename).read_text(encoding="utf-8"))


@pytest.mark.parametrize(("filename", "identity", "model_type", "sample_factory"), CASES)
def test_target_schema_identity_and_positive_fixture_parity(filename, identity, model_type, sample_factory) -> None:
    schema = _schema(filename)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == identity
    jsonschema.Draft202012Validator.check_schema(schema)
    sample = sample_factory()
    model_type.model_validate(sample)
    jsonschema.Draft202012Validator(schema).validate(sample)


@pytest.mark.parametrize(("filename", "identity", "model_type", "sample_factory"), CASES)
def test_target_schema_and_pydantic_both_reject_wrong_discriminator(filename, identity, model_type, sample_factory) -> None:
    sample = sample_factory()
    sample["schema_version"] = f"not-{identity}"
    with pytest.raises(ValidationError):
        model_type.model_validate(sample)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(_schema(filename)).validate(sample)


@pytest.mark.parametrize(("filename", "identity", "model_type", "sample_factory"), CASES)
def test_target_schema_and_pydantic_both_reject_unknown_fields(filename, identity, model_type, sample_factory) -> None:
    sample = deepcopy(sample_factory())
    sample["unexpected"] = True
    with pytest.raises(ValidationError):
        model_type.model_validate(sample)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(_schema(filename)).validate(sample)
