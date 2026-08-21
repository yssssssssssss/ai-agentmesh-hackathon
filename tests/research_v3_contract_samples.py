from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.report_document import COMPETITIVE_TEXT_SECTION_ORDER
from agentmesh.research_orchestration.v3.review import REQUIRED_DETERMINISTIC_CHECKS, REVIEW_DIMENSIONS

HASH = "a" * 64


def artifact_ref(artifact_id: str, kind: str, schema_version: str) -> dict[str, str]:
    return {
        "artifact_id": artifact_id,
        "kind": kind,
        "schema_version": schema_version,
        "content_hash": HASH,
    }


def requirement_body() -> dict:
    return {
        "schema_version": "research-task-v3",
        "task_type": "competitive_research",
        "business_domain": "productivity_software",
        "research_goal": "Compare Alpha and Beta for team adoption.",
        "comparison_dimensions": ["capabilities", "limitations"],
        "target_audience": ["product_team"],
        "scope": ["Alpha", "Beta"],
        "constraints": [
            {"id": "constraint_public", "statement": "Use public evidence.", "source": "user"}
        ],
        "success_criteria": [
            {"id": "criterion_traceable", "statement": "Every material difference is traceable."}
        ],
        "expected_deliverables": ["competitive_analysis_report"],
        "assumptions": [{"key": "market", "value": "global", "editable": True}],
        "ambiguities": [],
        "clarification_questions": [],
        "blocking_issues": [],
        "sensitivity": "public",
        "pii_detected": False,
    }


def requirement_envelope() -> dict:
    body = requirement_body()
    return {
        "id": "requirement_1",
        "run_id": "run_1",
        "version": 1,
        "schema_version": "research-task-v3",
        "task_type": "competitive_research",
        "payload": body,
        "content_hash": canonical_json_v3_sha256(body),
        "created_at": "2026-08-21T00:00:00Z",
    }


def problem_graph_body() -> dict:
    return {
        "schema_version": "problem-graph-v1",
        "requirement_version_id": "requirement_1",
        "questions": [
            {
                "id": "q_capabilities",
                "statement": "What material differences are observable?",
                "rationale": "Establish a factual baseline.",
                "priority": "required",
                "success_criterion_ids": ["criterion_traceable"],
                "evidence_requirements": [
                    {
                        "id": "competitive-analysis-report",
                        "accepted_classes": ["public_source"],
                        "minimum_count": 1,
                        "required": True,
                    }
                ],
                "acceptance_criteria": ["Every material fact cites public evidence."],
                "depends_on": [],
            }
        ],
        "provenance": {
            "model_call_receipt_id": "receipt_1",
            "model_name": "model",
            "model_version": "1",
            "prompt_hash": HASH,
            "trace_id": "trace_1",
            "context_manifest_hash": HASH,
        },
    }


def plan_body() -> dict:
    first = {
        "step_number": 1,
        "name": "Collect public evidence",
        "actor_type": "tool",
        "actor_id": "tavily-web-search",
        "question_ids": ["q_capabilities"],
        "depends_on": [],
        "input": {"query": "Alpha Beta comparison"},
        "input_bindings": [],
        "expected_outputs": [{"pointer": "/results", "description": "Verified search results"}],
        "acceptance_criteria": ["At least one public result."],
        "required": True,
        "requires_approval": True,
        "approval_role": "owner",
        "timeout_seconds": 30,
        "max_sends": 2,
        "invocation_semantics": "tool_read",
        "actor_snapshot_hash": HASH,
        "input_schema_hash": HASH,
        "output_schema_hash": HASH,
    }
    first["contract_hash"] = canonical_json_v3_sha256(first)
    second = {
        "step_number": 2,
        "name": "Analyze competitors",
        "actor_type": "skill",
        "actor_id": "competitive-analysis",
        "question_ids": ["q_capabilities"],
        "depends_on": [1],
        "input": {"evidence": None},
        "input_bindings": [
            {"source_step_number": 1, "source_pointer": "/results", "target_pointer": "/evidence"}
        ],
        "expected_outputs": [{"pointer": "/payload", "description": "Competitive analysis payload"}],
        "acceptance_criteria": ["Claims cite evidence."],
        "required": True,
        "requires_approval": False,
        "approval_role": None,
        "timeout_seconds": 120,
        "max_sends": 1,
        "invocation_semantics": "skill_once",
        "actor_snapshot_hash": HASH,
        "input_schema_hash": HASH,
        "output_schema_hash": HASH,
    }
    second["contract_hash"] = canonical_json_v3_sha256(second)
    return {
        "schema_version": "execution-plan-v3",
        "task_type": "competitive_research",
        "requirement_version_id": "requirement_1",
        "requirement_content_hash": canonical_json_v3_sha256(requirement_body()),
        "problem_graph_artifact": artifact_ref("artifact_graph", "problem_graph", "problem-graph-v1"),
        "candidate_id": "depth",
        "deliverable_type": "competitive_analysis_report",
        "payload_schema_version": "competitive-analysis-text-v1",
        "evidence_requirements": [
            {
                "id": "competitive-analysis-report",
                "accepted_classes": ["public_source"],
                "minimum_count": 1,
                "required": True,
            }
        ],
        "capability_decisions": [
            {
                "actor_type": "tool",
                "actor_id": "tavily-web-search",
                "status": "eligible",
                "required_approvals": [
                    {"capability_type": "tool", "capability_id": "tavily-web-search", "authority": "owner"}
                ],
                "reasons": [{"code": "eligible", "message": "Real Tavily adapter is available."}],
                "pending_inputs": [],
                "optional_tool_decisions": [],
            }
        ],
        "capability_gaps": [],
        "steps": [first, second],
        "candidate_title": "Depth",
        "candidate_rationale": "Use evidence and analysis.",
        "candidate_tradeoffs": "Higher latency.",
        "activated_nodes": [
            "D1_research_goal",
            "D3_method_selection",
            "D5_competitive",
            "D6_data_sensitivity",
            "D7_output_standard",
        ],
        "control_snapshot_artifact": artifact_ref(
            "artifact_control", "research_control_snapshot", "research-control-snapshot-v3"
        ),
        "execution_budget_seconds": 300,
        "max_tool_calls": 24,
        "max_wave_concurrency": 3,
    }


def deliverable_body() -> dict:
    return {
        "schema_version": "research-deliverable-v3",
        "run_id": "run_1",
        "requirement_version_id": "requirement_1",
        "plan_version_id": "plan_1",
        "attempt_id": "attempt_1",
        "deliverable_type": "competitive_analysis_report",
        "payload_schema_version": "competitive-analysis-text-v1",
        "evidence_manifest_artifact": artifact_ref(
            "artifact_evidence", "evidence_manifest", "evidence-manifest-v3"
        ),
        "method_summary": "Compared public evidence using the frozen method.",
        "finding_graph": {
            "findings": [{"id": "finding_1", "kind": "fact", "evidence_ids": ["evidence_1"], "statement": "Alpha differs."}],
            "analyses": [{"id": "analysis_1", "finding_ids": ["finding_1"], "statement": "The difference matters."}],
            "sub_question_summaries": [
                {"id": "summary_1", "finding_ids": ["finding_1"], "analysis_ids": ["analysis_1"], "summary": "A supported answer."}
            ],
            "overall_conclusions": [
                {"id": "conclusion_1", "summary_ids": ["summary_1"], "statement": "Prefer Alpha for this need."}
            ],
        },
        "payload": {
            "competitor_samples": [
                {"id": "alpha", "name": "Alpha", "rationale": "In scope.", "evidence_ids": ["evidence_1"]},
                {"id": "beta", "name": "Beta", "rationale": "In scope.", "evidence_ids": ["evidence_1"]},
            ],
            "dimension_matrix": [
                {
                    "dimension": "capabilities",
                    "weight": Decimal("0.5"),
                    "values": [
                        {"sample_id": "alpha", "value": "Strong", "score": Decimal("4"), "evidence_ids": ["evidence_1"]},
                        {"sample_id": "beta", "value": "Moderate", "score": Decimal("3"), "evidence_ids": ["evidence_1"]},
                    ],
                }
            ],
            "differences": [
                {"id": "difference_1", "dimension": "capabilities", "statement": "Alpha is stronger.", "evidence_ids": ["evidence_1"]}
            ],
            "impacts": [{"difference_id": "difference_1", "audience": "product_team", "statement": "Faster adoption."}],
            "action_recommendations": [
                {"id": "action_1", "difference_ids": ["difference_1"], "priority": "P1", "statement": "Pilot Alpha."}
            ],
            "management_summary": None,
            "scoring_method": None,
            "roadmap": None,
            "instrumentation_plan": None,
            "user_test_script": None,
            "visual_evidence": [],
            "screenshot_comparisons": [],
        },
        "recommendations": [
            {"id": "recommendation_1", "priority": "P1", "statement": "Pilot Alpha.", "finding_ids": ["finding_1"]}
        ],
        "coverage": {
            "question_coverage": [{"question_id": "q_capabilities", "summary_ids": ["summary_1"]}],
            "success_criterion_coverage": [
                {"success_criterion_id": "criterion_traceable", "conclusion_or_recommendation_ids": ["conclusion_1"]}
            ],
        },
        "risks_and_open_issues": ["Only public evidence was available."],
        "capability_provenance": [
            {
                "actor_type": "skill",
                "actor_id": "competitive-analysis",
                "result_artifact": artifact_ref("artifact_skill", "skill_result", "skill-output-v2"),
            }
        ],
    }


def review_body() -> dict:
    dimensions = [{"id": dimension, "passed": True, "issues": []} for dimension in REVIEW_DIMENSIONS]
    checks = [
        {"code": code, "dimension_id": "requirement_coverage", "passed": True, "issues": []}
        for code in sorted(REQUIRED_DETERMINISTIC_CHECKS)
    ]
    return {
        "schema_version": "report-review-v3",
        "run_id": "run_1",
        "plan_version_id": "plan_1",
        "attempt_id": "attempt_1",
        "deliverable_artifact": artifact_ref(
            "artifact_deliverable", "research_deliverable", "research-deliverable-v3"
        ),
        "rubric_snapshot_hash": HASH,
        "deterministic_checks": checks,
        "semantic_model_call_receipt_id": "receipt_review_1",
        "verdict": "pass",
        "dimensions": dimensions,
        "revision_round": 0,
    }


def report_body() -> dict:
    sections = [
        {"id": section_id, "title": section_id.replace("-", " ").title(), "question_ids": [], "blocks": []}
        for section_id in COMPETITIVE_TEXT_SECTION_ORDER
    ]
    sections[1]["blocks"] = [{"id": "block_summary", "type": "paragraph", "text": "Alpha is preferred."}]
    sections[5]["question_ids"] = ["q_capabilities"]
    sections[5]["blocks"] = [
        {"id": "block_fact", "type": "fact", "text": "Alpha differs.", "evidence_ids": ["evidence_1"]}
    ]
    return {
        "schema_version": "report-document-v3",
        "presentation_mode": "text",
        "run_id": "run_1",
        "requirement_version_id": "requirement_1",
        "plan_version_id": "plan_1",
        "attempt_id": "attempt_1",
        "deliverable_artifact": artifact_ref(
            "artifact_deliverable", "research_deliverable", "research-deliverable-v3"
        ),
        "review_artifact": artifact_ref("artifact_review", "report_review", "report-review-v3"),
        "template_snapshot_hash": HASH,
        "title": "Alpha versus Beta",
        "subtitle": "Evidence-backed competitive analysis",
        "executive_summary": "Alpha is preferred for the stated need.",
        "sections": sections,
    }


def copy_without_decimal(value: dict) -> dict:
    copy = deepcopy(value)

    def convert(item):
        if isinstance(item, Decimal):
            return int(item) if item == item.to_integral_value() else item
        if isinstance(item, dict):
            return {key: convert(value) for key, value in item.items()}
        if isinstance(item, list):
            return [convert(value) for value in item]
        return item

    return convert(copy)
