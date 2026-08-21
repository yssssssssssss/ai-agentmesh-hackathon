from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentmesh.research_orchestration.v3.review import DeterministicReviewCheckV3
from agentmesh.research_orchestration.v3.source_adapter import (
    translate_ai_x_current_execution_plan,
    translate_ai_x_problem_graph_v1,
    translate_ai_x_report_document_v1,
    translate_ai_x_report_review_v1,
    translate_ai_x_research_deliverable_v1,
    translate_ai_x_research_task_v2,
)
from agentmesh.research_orchestration.v3.source_contracts import AiXCurrentExecutionPlan
from research_v3_contract_samples import (
    artifact_ref,
    review_body,
    source_deliverable_body,
    source_report_body,
    source_review_body,
)

HASH = "b" * 64


@pytest.fixture
def source_deliverable_fixture() -> dict:
    return source_deliverable_body()


@pytest.fixture
def source_review_fixture() -> dict:
    return source_review_body()


@pytest.fixture
def source_report_fixture() -> dict:
    return source_report_body()


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
    source["capability_decisions"]["eligible"][0]["skill"]["unknown"] = True
    with pytest.raises(ValidationError, match="unknown"):
        translate_ai_x_current_execution_plan(source, candidate_id="depth")

    source = _source_execution_plan()
    source["capability_decisions"]["eligible"][0]["optional_tool_decisions"][0].pop("reason_code")
    with pytest.raises(ValidationError, match="reason"):
        translate_ai_x_current_execution_plan(source, candidate_id="depth")


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
    with pytest.raises(ValidationError, match="pass verdict"):
        translate_ai_x_report_review_v1(
            malformed,
            deliverable_artifact=artifact_ref(
                "artifact_deliverable", "research_deliverable", "research-deliverable-v3"
            ),
            rubric_snapshot_hash=HASH,
            deterministic_checks=checks,
            semantic_model_call_receipt_id="receipt_review_1",
        )


def test_source_report_adapter_translates_full_block_union_without_fallback(
    source_report_fixture: dict,
) -> None:
    translated = translate_ai_x_report_document_v1(
        source_report_fixture,
        presentation_mode="text",
        run_id="run_1",
        requirement_version_id="requirement_1",
        plan_version_id="plan_1",
        attempt_id="attempt_1",
        deliverable_artifact=artifact_ref(
            "artifact_deliverable", "research_deliverable", "research-deliverable-v3"
        ),
        review_artifact=artifact_ref("artifact_review", "report_review", "report-review-v3"),
        template_snapshot_hash=HASH,
    )
    assert translated.schema_version == "report-document-v3"
    assert translated.sections[1].blocks[0].type == "paragraph"
    assert translated.sections[5].blocks[0].type == "fact"

    malformed = deepcopy(source_report_fixture)
    malformed["sections"][1]["blocks"][0]["fallback_payload"] = {}
    with pytest.raises(ValidationError, match="fallback_payload"):
        translate_ai_x_report_document_v1(
            malformed,
            presentation_mode="text",
            run_id="run_1",
            requirement_version_id="requirement_1",
            plan_version_id="plan_1",
            attempt_id="attempt_1",
            deliverable_artifact=artifact_ref(
                "artifact_deliverable", "research_deliverable", "research-deliverable-v3"
            ),
            review_artifact=artifact_ref("artifact_review", "report_review", "report-review-v3"),
            template_snapshot_hash=HASH,
        )
