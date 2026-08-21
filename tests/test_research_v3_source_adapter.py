from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.review import DeterministicReviewCheckV3, PassedReportReviewV3
from agentmesh.research_orchestration.v3.source_adapter import (
    translate_ai_x_current_execution_plan,
    translate_ai_x_problem_graph_v1,
    translate_ai_x_report_document_v1,
    translate_ai_x_report_review_v1,
    translate_ai_x_research_deliverable_v1,
    translate_ai_x_research_task_v2,
)
from agentmesh.research_orchestration.v3.source_contracts import (
    AiXCurrentExecutionPlan,
    AiXProblemGraphV1,
    AiXReportDocumentV1,
    AiXResearchTaskV2,
)
from research_v3_contract_samples import (
    artifact_ref,
    review_body,
    source_deliverable_body,
    source_report_body,
    source_review_body,
)

HASH = "b" * 64
SOURCE_SCHEMA_ROOT = Path("agentmesh/research_catalog/research-v3/competitive-text-v1/source/schemas")


def _source_schema(relative_path: str) -> dict:
    return json.loads((SOURCE_SCHEMA_ROOT / relative_path).read_text(encoding="utf-8"))


def _source_report_blocks() -> list[dict]:
    asset = {"assetId": "asset_1", "manifestArtifactId": "manifest_1"}
    return [
        {"id": "paragraph_1", "type": "paragraph", "text": "Narrative."},
        {
            "id": "fact_1",
            "type": "fact",
            "text": "Supported fact.",
            "evidenceIds": ["evidence_1"],
        },
        {
            "id": "metric_1",
            "type": "metric",
            "label": "Score",
            "value": 4,
            "evidenceIds": ["evidence_1"],
        },
        {"id": "list_1", "type": "list", "items": ["First"]},
        {
            "id": "image_1",
            "type": "image",
            "assetRef": asset,
            "caption": "Image caption.",
            "altText": "Image alternative.",
            "evidenceIds": ["evidence_1"],
        },
        {
            "id": "comparison_1",
            "type": "image-comparison",
            "beforeAssetRef": asset,
            "afterAssetRef": {"assetId": "asset_2", "manifestArtifactId": "manifest_1"},
            "caption": "Comparison caption.",
            "altText": "Comparison alternative.",
            "evidenceIds": ["evidence_1"],
        },
        {
            "id": "chart_1",
            "type": "chart",
            "chartRef": {
                "chartId": "chart_1",
                "assetId": "asset_3",
                "manifestArtifactId": "manifest_1",
            },
            "specHash": f"sha256:{HASH}",
            "spec": {
                "version": "chart-spec-v1",
                "chartId": "chart_1",
                "type": "comparison",
                "title": "Comparison",
                "categories": ["Alpha"],
                "series": [
                    {
                        "key": "score",
                        "label": "Score",
                        "values": [4],
                        "evidenceIds": [["evidence_1"]],
                    }
                ],
            },
            "table": {
                "caption": "Accessible data.",
                "columns": ["Competitor", "Score"],
                "rows": [
                    {
                        "key": "alpha",
                        "label": "Alpha",
                        "cells": [4],
                        "evidenceIds": [["evidence_1"]],
                    }
                ],
            },
            "caption": "Chart caption.",
            "altText": "Chart alternative.",
        },
    ]


@pytest.fixture
def source_deliverable_fixture() -> dict:
    return source_deliverable_body()


@pytest.fixture
def source_review_fixture() -> dict:
    return source_review_body()


@pytest.fixture
def source_report_fixture() -> dict:
    return source_report_body()


def test_source_requirement_uniqueness_matches_locked_schema() -> None:
    source = json.loads(Path("tests/fixtures/ai_x_parity/requirement.json").read_text(encoding="utf-8"))[
        "source_normalized_example"
    ]
    AiXResearchTaskV2.model_validate(source)
    jsonschema.Draft7Validator(_source_schema("research-task-v2.schema.json")).validate(source)

    duplicate = deepcopy(source)
    duplicate["comparison_dimensions"] = ["capabilities", "capabilities"]
    with pytest.raises(ValidationError, match="comparison dimensions"):
        AiXResearchTaskV2.model_validate(duplicate)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft7Validator(_source_schema("research-task-v2.schema.json")).validate(duplicate)


def test_source_problem_graph_and_plan_keep_distinct_minimum_count_semantics() -> None:
    graph_fixture = json.loads(
        Path("tests/fixtures/ai_x_parity/problem-graph-problem-contract.json").read_text(encoding="utf-8")
    )["source_normalized_example"]
    standalone_zero = deepcopy(graph_fixture)
    standalone_zero["questions"][0]["evidence_requirements"][0]["minimumCount"] = 0
    with pytest.raises(ValidationError):
        AiXProblemGraphV1.model_validate(standalone_zero)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft7Validator(_source_schema("problem-graph.schema.json")).validate(standalone_zero)

    current = _source_execution_plan()
    assert AiXCurrentExecutionPlan.model_validate(current).evidence_requirements[0].minimumCount == 0
    jsonschema.Draft7Validator(_source_schema("current-execution-plan.schema.json")).validate(current)
    current["evidence_requirements"][0]["minimumCount"] = -1
    with pytest.raises(ValidationError):
        AiXCurrentExecutionPlan.model_validate(current)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft7Validator(_source_schema("current-execution-plan.schema.json")).validate(current)


def test_source_research_task_is_translated_before_target_validation() -> None:
    fixture = json.loads(Path("tests/fixtures/ai_x_parity/requirement.json").read_text(encoding="utf-8"))
    source = fixture["source_normalized_example"]
    target = translate_ai_x_research_task_v2(source)
    dumped = target.model_dump(mode="python")
    assert dumped["schema_version"] == "research-task-v3"
    assert "version" not in dumped
    assert target.expected_deliverables == ("competitive_analysis_report",)
    assert target.scope == ("Product Alpha", "Product Beta")

    unsupported = dict(source, task_type="design_audit")
    with pytest.raises(ValueError, match="only competitive_research"):
        translate_ai_x_research_task_v2(unsupported)


def test_source_problem_graph_camel_case_fields_are_explicitly_translated() -> None:
    fixture = json.loads(
        Path("tests/fixtures/ai_x_parity/problem-graph-problem-contract.json").read_text(encoding="utf-8")
    )
    graph = translate_ai_x_problem_graph_v1(
        fixture["source_normalized_example"],
        requirement_version_id="requirement_1",
        model_call_receipt_id="receipt_1",
        model_name="planner",
        model_version="1",
        prompt_hash=HASH,
        trace_id="trace_1",
        context_manifest_hash=HASH,
    )
    requirement = graph.questions[0].evidence_requirements[0]
    assert requirement.accepted_classes == ("public_source", "screenshot")
    assert requirement.minimum_count == 2
    assert "acceptedClasses" not in graph.model_dump(mode="python")["questions"][0]["evidence_requirements"][0]


def _source_execution_plan() -> dict:
    return {
        "task_id": "source-task",
        "deliverable_type": "competitive_analysis_report",
        "evidence_requirements": [
            {
                "id": "optional-observation",
                "acceptedClasses": ["public_source"],
                "minimumCount": 0,
                "required": False,
            }
        ],
        "problem_graph": {
            "version": "problem-graph-v1",
            "questions": [
                {
                    "id": "q1",
                    "statement": "What differs?",
                    "rationale": "Compare products.",
                    "priority": "required",
                    "success_criterion_ids": ["criterion1"],
                    "evidence_requirements": [
                        {
                            "id": "optional-observation",
                            "acceptedClasses": ["public_source"],
                            "minimumCount": 0,
                            "required": False,
                        }
                    ],
                    "acceptance_criteria": ["Cited answer."],
                    "depends_on": [],
                }
            ],
        },
        "problem_graph_provenance": {
            "receiptId": "1b49af79-e4d6-45ee-a281-4e507ad4f107",
            "modelName": "planner",
            "modelVersion": "1",
            "promptHash": HASH,
            "traceId": "trace_1",
        },
        "capability_decisions": {
            "eligible": [
                {
                    "skill": {
                        "id": "competitive-analysis",
                        "status": "active",
                        "task_types": ["competitive_research"],
                        "inputs": ["evidence"],
                        "outputs": ["payload"],
                        "required_tools": [],
                        "optional_tools": ["playwright-page-capture"],
                    },
                    "required_approvals": [],
                    "reasons": [{"code": "eligible", "message": "Skill is active."}],
                    "pending_inputs": [],
                    "optional_tool_decisions": [
                        {
                            "tool_id": "playwright-page-capture",
                            "status": "unavailable",
                            "reason_code": "optional_tool_real_adapter_unavailable",
                            "message": "Excluded from Competitive Text.",
                        }
                    ],
                }
            ],
            "rejected": [],
        },
        "capability_gaps": [
            {
                "capability_type": "tool",
                "capability_id": "playwright-page-capture",
                "code": "optional_tool_real_adapter_unavailable",
                "message": "Excluded from Competitive Text.",
            }
        ],
        "steps": [
            {
                "step_no": 9,
                "step_name": "Draft evidence",
                "actor_type": "llm",
                "actor_id": "synthesis actor",
                "question_ids": ["q1"],
                "depends_on": [],
                "input": {"nested": [{"query": "Alpha"}]},
                "input_bindings": [],
                "expected_outputs": [{"pointer": "/text", "description": "Draft text"}],
                "acceptance_criteria": ["Evidence-backed."],
                "requires_approval": False,
                "fallback_actor_ids": [],
            }
        ],
        "candidate_metadata": {
            "title": "Depth",
            "rationale": "Use explicit synthesis.",
            "tradeoffs": "More latency.",
        },
        "activated_nodes": ["D1_research_goal"],
    }


def test_source_execution_plan_is_schema_faithful_and_becomes_non_authoritative_candidate() -> None:
    source = _source_execution_plan()
    source_model = AiXCurrentExecutionPlan.model_validate(source)
    assert source_model.problem_graph.questions[0].evidence_requirements[0].minimumCount == 0
    assert source_model.capability_decisions.eligible[0].skill.id == "competitive-analysis"

    candidate = translate_ai_x_current_execution_plan(source, candidate_id="depth")
    assert candidate.candidate_id == "depth"
    assert candidate.proposed_steps[0].proposed_step_number == 9
    assert candidate.proposed_steps[0].actor_id.startswith("actor_synthesis-actor_")
    assert "contract_hash" not in candidate.model_dump(mode="python")["proposed_steps"][0]

    source["steps"][0]["fallback_actor_ids"] = ["fallback"]
    with pytest.raises(ValueError, match="fallback actor"):
        translate_ai_x_current_execution_plan(source, candidate_id="depth")


def test_source_capability_decisions_reject_shape_fallbacks() -> None:
    source = _source_execution_plan()
    AiXCurrentExecutionPlan.model_validate(source)
    jsonschema.Draft7Validator(_source_schema("current-execution-plan.schema.json")).validate(source)

    source["capability_decisions"]["eligible"][0]["skill"]["unknown"] = True
    with pytest.raises(jsonschema.ValidationError, match="Additional properties"):
        translate_ai_x_current_execution_plan(source, candidate_id="depth")

    source = _source_execution_plan()
    source["capability_decisions"]["eligible"][0]["optional_tool_decisions"][0].pop("reason_code")
    with pytest.raises(jsonschema.ValidationError, match="required"):
        translate_ai_x_current_execution_plan(source, candidate_id="depth")

    source = _source_execution_plan()
    decision = source["capability_decisions"]["eligible"][0]["optional_tool_decisions"][0]
    source["capability_decisions"]["eligible"][0]["optional_tool_decisions"] = [decision, decision]
    with pytest.raises(ValidationError, match="optional Tool decisions"):
        AiXCurrentExecutionPlan.model_validate(source)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft7Validator(_source_schema("current-execution-plan.schema.json")).validate(source)


def test_source_deliverable_adapter_has_explicit_lineage_and_typed_payload(
    source_deliverable_fixture: dict,
) -> None:
    translated = translate_ai_x_research_deliverable_v1(
        source_deliverable_fixture,
        requirement_version_id="requirement_1",
        evidence_manifest_artifact=artifact_ref(
            "artifact_evidence", "evidence_manifest", "evidence-manifest-v3"
        ),
        capability_result_artifacts={
            "competitive-analysis": artifact_ref("artifact_skill", "skill_result", "skill-output-v2")
        },
        recommendation_priorities={"recommendation_1": "P1"},
    )
    assert translated.schema_version == "research-deliverable-v3"
    assert translated.payload.competitor_samples[0].name == "Alpha"
    assert translated.recommendations[0].finding_ids == ("finding_1",)
    assert translated.capability_provenance[0].result_artifact.artifact_id == "artifact_skill"

    malformed = deepcopy(source_deliverable_fixture)
    malformed["findingGraph"]["findings"][0]["unmodeled"] = True
    with pytest.raises(ValidationError, match="unmodeled"):
        translate_ai_x_research_deliverable_v1(
            malformed,
            requirement_version_id="requirement_1",
            evidence_manifest_artifact=artifact_ref(
                "artifact_evidence", "evidence_manifest", "evidence-manifest-v3"
            ),
            capability_result_artifacts={
                "competitive-analysis": artifact_ref("artifact_skill", "skill_result", "skill-output-v2")
            },
            recommendation_priorities={"recommendation_1": "P1"},
        )


def test_source_review_adapter_requires_exact_sealed_deliverable(
    source_review_fixture: dict,
) -> None:
    checks = tuple(
        DeterministicReviewCheckV3.model_validate(value) for value in review_body()["deterministic_checks"]
    )
    translated = translate_ai_x_report_review_v1(
        source_review_fixture,
        requirement_version_id="requirement_1",
        deliverable_artifact=artifact_ref(
            "artifact_deliverable", "research_deliverable", "research-deliverable-v3"
        ),
        rubric_snapshot_hash=HASH,
        deterministic_checks=checks,
        semantic_model_call_receipt_id="receipt_review_1",
    )
    assert translated.schema_version == "report-review-v3"
    assert translated.verdict == "pass"

    malformed = deepcopy(source_review_fixture)
    malformed["dimensions"][0]["passed"] = False
    with pytest.raises(jsonschema.ValidationError):
        translate_ai_x_report_review_v1(
            malformed,
            requirement_version_id="requirement_1",
            deliverable_artifact=artifact_ref(
                "artifact_deliverable", "research_deliverable", "research-deliverable-v3"
            ),
            rubric_snapshot_hash=HASH,
            deterministic_checks=checks,
            semantic_model_call_receipt_id="receipt_review_1",
        )


def test_source_report_contract_rejects_missing_discriminators_and_duplicate_nested_evidence() -> None:
    missing_type = source_report_body()
    missing_type["sections"][1]["blocks"][0].pop("type")
    with pytest.raises(ValidationError):
        AiXReportDocumentV1.model_validate(missing_type)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft7Validator(_source_schema("report-document.schema.json")).validate(missing_type)

    duplicate_nested_evidence = source_report_body()
    chart = deepcopy(_source_report_blocks()[-1])
    chart["spec"]["series"][0]["evidenceIds"][0] = ["evidence_1", "evidence_1"]
    duplicate_nested_evidence["sections"][1]["blocks"] = [chart]
    with pytest.raises(ValidationError, match="chart-series Evidence IDs"):
        AiXReportDocumentV1.model_validate(duplicate_nested_evidence)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft7Validator(_source_schema("report-document.schema.json")).validate(
            duplicate_nested_evidence
        )

    duplicate_table_evidence = source_report_body()
    chart = deepcopy(_source_report_blocks()[-1])
    chart["table"]["rows"][0]["evidenceIds"][0] = ["evidence_1", "evidence_1"]
    duplicate_table_evidence["sections"][1]["blocks"] = [chart]
    with pytest.raises(ValidationError, match="chart-table Evidence IDs"):
        AiXReportDocumentV1.model_validate(duplicate_table_evidence)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft7Validator(_source_schema("report-document.schema.json")).validate(
            duplicate_table_evidence
        )


def test_source_optional_properties_reject_explicit_null() -> None:
    source = _source_execution_plan()
    source["capability_decisions"]["eligible"][0]["skill"]["name"] = None
    with pytest.raises(ValidationError, match="do not accept null"):
        AiXCurrentExecutionPlan.model_validate(source)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft7Validator(_source_schema("current-execution-plan.schema.json")).validate(source)


def _translate_source_report(source: dict | str | bytes, *, presentation_mode: str = "text"):
    deliverable_artifact = artifact_ref(
        "artifact_deliverable", "research_deliverable", "research-deliverable-v3"
    )
    review_value = review_body()
    review_value["deliverable_artifact"] = deliverable_artifact
    review = PassedReportReviewV3.model_validate(review_value)
    return translate_ai_x_report_document_v1(
        source,
        presentation_mode=presentation_mode,  # type: ignore[arg-type]
        run_id="run_1",
        requirement_version_id="requirement_1",
        plan_version_id="plan_1",
        attempt_id="attempt_1",
        deliverable_artifact=deliverable_artifact,
        review=review,
        review_artifact=artifact_ref(
            "artifact_review",
            "report_review",
            "report-review-v3",
            canonical_json_v3_sha256(review),
        ),
        template_snapshot_hash=HASH,
    )


def test_source_adapters_apply_locked_json_schemas_before_typed_translation() -> None:
    requirement = json.loads(
        Path("tests/fixtures/ai_x_parity/requirement.json").read_text(encoding="utf-8")
    )["source_normalized_example"]
    requirement["pii_detected"] = "false"
    with pytest.raises(jsonschema.ValidationError):
        translate_ai_x_research_task_v2(requirement)

    graph = json.loads(
        Path("tests/fixtures/ai_x_parity/problem-graph-problem-contract.json").read_text(encoding="utf-8")
    )["source_normalized_example"]
    graph["questions"][0]["evidence_requirements"][0]["minimumCount"] = 0
    with pytest.raises(jsonschema.ValidationError):
        translate_ai_x_problem_graph_v1(
            graph,
            requirement_version_id="requirement_1",
            model_call_receipt_id="receipt_1",
            model_name="planner",
            model_version="1",
            prompt_hash=HASH,
            trace_id="trace_1",
            context_manifest_hash=HASH,
        )

    plan = _source_execution_plan()
    plan["steps"][0]["requires_approval"] = "false"
    with pytest.raises(jsonschema.ValidationError):
        translate_ai_x_current_execution_plan(plan, candidate_id="depth")

    deliverable = source_deliverable_body()
    deliverable["payload"]["competitorSamples"][0]["evidenceIds"] = []
    with pytest.raises(jsonschema.ValidationError):
        translate_ai_x_research_deliverable_v1(
            deliverable,
            requirement_version_id="requirement_1",
            evidence_manifest_artifact=artifact_ref(
                "artifact_evidence", "evidence_manifest", "evidence-manifest-v3"
            ),
            capability_result_artifacts={
                "competitive-analysis": artifact_ref(
                    "artifact_skill", "skill_result", "skill-output-v2"
                )
            },
            recommendation_priorities={"recommendation_1": "P1"},
        )

    review = source_review_body()
    review["dimensions"][0]["passed"] = "true"
    checks = tuple(
        DeterministicReviewCheckV3.model_validate(value) for value in review_body()["deterministic_checks"]
    )
    with pytest.raises(jsonschema.ValidationError):
        translate_ai_x_report_review_v1(
            review,
            requirement_version_id="requirement_1",
            deliverable_artifact=artifact_ref(
                "artifact_deliverable", "research_deliverable", "research-deliverable-v3"
            ),
            rubric_snapshot_hash=HASH,
            deterministic_checks=checks,
            semantic_model_call_receipt_id="receipt_review_1",
        )

    report = source_report_body()
    report["sections"][1]["blocks"] = [
        {
            "id": "metric_1",
            "type": "metric",
            "label": "Score",
            "value": "4",
            "evidenceIds": ["evidence_1"],
        }
    ]
    with pytest.raises(jsonschema.ValidationError):
        _translate_source_report(report)


def test_source_adapter_rejects_duplicate_json_keys_before_model_parsing() -> None:
    requirement = json.loads(
        Path("tests/fixtures/ai_x_parity/requirement.json").read_text(encoding="utf-8")
    )["source_normalized_example"]
    encoded = json.dumps(requirement, separators=(",", ":"))
    encoded = encoded.replace(
        '"pii_detected":false',
        '"pii_detected":false,"pii_detected":true',
    )
    with pytest.raises(ValueError, match="duplicate normalized keys"):
        translate_ai_x_research_task_v2(encoded)


def test_source_report_contract_accepts_every_locked_block_variant() -> None:
    source = source_report_body()
    source["sections"][1]["blocks"] = _source_report_blocks()
    AiXReportDocumentV1.model_validate(source)
    jsonschema.Draft7Validator(_source_schema("report-document.schema.json")).validate(source)


@pytest.mark.parametrize("block", _source_report_blocks()[:4], ids=lambda block: block["type"])
def test_source_report_adapter_translates_each_text_block_variant(block: dict) -> None:
    source = source_report_body()
    source["sections"][1]["blocks"] = [block]
    translated = _translate_source_report(source)
    assert translated.sections[1].blocks[0].type == block["type"]


@pytest.mark.parametrize("block", _source_report_blocks()[4:], ids=lambda block: block["type"])
def test_source_report_adapter_rejects_every_visual_block_variant(block: dict) -> None:
    source = source_report_body()
    source["sections"][1]["blocks"] = [block]
    with pytest.raises(ValueError, match="cannot translate source"):
        _translate_source_report(source)


def test_source_report_adapter_rejects_multimodal_presentation_and_unknown_fields(
    source_report_fixture: dict,
) -> None:
    with pytest.raises(ValueError, match="text presentation only"):
        _translate_source_report(source_report_fixture, presentation_mode="multimodal")

    malformed = deepcopy(source_report_fixture)
    malformed["sections"][1]["blocks"][0]["fallback_payload"] = {}
    with pytest.raises(jsonschema.ValidationError):
        _translate_source_report(malformed)
