from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_bytes, canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.report_document import COMPETITIVE_TEXT_SECTION_ORDER
from agentmesh.research_orchestration.v3.review import REQUIRED_DETERMINISTIC_CHECKS, REVIEW_DIMENSIONS

HASH = "a" * 64


def artifact_ref(
    artifact_id: str,
    kind: str,
    schema_version: str,
    content_hash: str = HASH,
) -> dict[str, str]:
    return {
        "artifact_id": artifact_id,
        "kind": kind,
        "schema_version": schema_version,
        "content_hash": content_hash,
    }


def evidence_artifact_content() -> dict:
    output = {
        "results": [
            {
                "title": "Alpha product documentation",
                "url": "https://example.test/alpha",
                "snippet": "Alpha documents the compared capability.",
            }
        ]
    }
    return {
        "output": output,
        "redacted_output_hash": canonical_json_v3_sha256(output),
    }


def evidence_body() -> dict:
    content = evidence_artifact_content()
    return {
        "schema_version": "evidence-manifest-v3",
        "presentation_mode": "text",
        "payload_schema_version": "competitive-analysis-text-v1",
        "run_id": "run_1",
        "plan_version_id": "plan_1",
        "attempt_id": "attempt_1",
        "collected_at": "2026-08-21T00:10:00Z",
        "evidence": [
            {
                "id": "evidence_1",
                "kind": "tool_output",
                "evidence_class": "public_source",
                "pointer": {
                    "artifact": artifact_ref(
                        "artifact_tool_1",
                        "actor_result",
                        "tool-result-v1",
                        canonical_json_v3_sha256(content),
                    ),
                    "json_pointer": "/output/results/0",
                },
                "source": {
                    "source_kind": "public_web",
                    "url": "https://example.test/alpha",
                    "quote": "Alpha documents the compared capability.",
                    "retrieved_at": "2026-08-21T00:09:00Z",
                    "registrable_domain": "example.test",
                    "independence_group": "example.test",
                    "conflict_status": "none",
                    "risk_flags": [],
                    "truncated": False,
                },
                "proof": {
                    "run_id": "run_1",
                    "plan_version_id": "plan_1",
                    "attempt_id": "attempt_1",
                    "step_number": 1,
                    "actor_type": "tool",
                    "actor_id": "tavily-web-search",
                    "step_contract_hash": plan_body()["steps"][0]["contract_hash"],
                    "receipt_id": "receipt_tool_1",
                    "implementation_id": "tavily-v1",
                    "execution_mode": "real",
                    "redacted_output_hash": content["redacted_output_hash"],
                },
                "sensitivity": "public",
                "redaction": "masked",
            }
        ],
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


def competitive_text_body() -> dict:
    return deepcopy(deliverable_body()["payload"])


def candidate_set_body() -> dict:
    depth_step = {
        "proposed_step_number": 1,
        "name": "Collect evidence",
        "actor_type": "tool",
        "actor_id": "tavily-web-search",
        "question_ids": ["q_capabilities"],
        "depends_on": [],
        "input": {"query": "Alpha Beta", "filters": [{"language": "en"}]},
        "input_bindings": [],
        "expected_outputs": [{"pointer": "/results", "description": "Search results"}],
        "acceptance_criteria": ["At least one result."],
        "requires_approval": True,
        "approval_role": "owner",
    }
    return {
        "schema_version": "plan-candidates-v3",
        "candidates": [
            {
                "candidate_id": "depth",
                "title": "Depth",
                "rationale": "Broader evidence.",
                "tradeoffs": "Higher latency.",
                "assumptions": [],
                "proposed_steps": [depth_step],
            },
            {
                "candidate_id": "speed",
                "title": "Speed",
                "rationale": "Shortest valid path.",
                "tradeoffs": "Narrower evidence.",
                "assumptions": [],
                "proposed_steps": [deepcopy(depth_step)],
            },
        ],
    }


def control_snapshot_body() -> dict:
    content = {"type": "object", "properties": {"query": {"type": "string"}}}
    content_bytes = canonical_json_v3_bytes(content)
    return {
        "schema_version": "research-control-snapshot-v3",
        "catalog_id": "competitive-text-v1",
        "catalog_hash": HASH,
        "resolved_for_agent_id": "agent_1",
        "resolved_at": "2026-08-21T00:00:00Z",
        "model_policy": {
            "requested_provider": "openai",
            "requested_model": "gpt-5.2",
            "structured_output_mode": "json_schema",
            "adapter_compatibility_id": "openai-json-schema-v1",
        },
        "actors": [
            {
                "actor_type": "tool",
                "actor_id": "tavily-web-search",
                "implementation_id": "agentmesh.web_research",
                "implementation_version": "1",
                "execution_mode": "real",
                "enabled": True,
                "eligible": True,
                "tier": "core",
                "approval_role": "owner",
                "required_tool_ids": [],
                "optional_tool_ids": [],
                "instruction_document_id": None,
                "input_schema_document_id": "schema_tool_input",
                "output_schema_document_id": "schema_tool_input",
            }
        ],
        "documents": [
            {
                "document_id": "schema_tool_input",
                "kind": "json_schema",
                "media_type": "application/json",
                "content_hash": canonical_json_v3_sha256(content),
                "size_bytes": len(content_bytes),
                "content": content,
            }
        ],
    }


def source_deliverable_body() -> dict:
    target = deliverable_body()
    payload = target["payload"]
    return {
        "version": "research-deliverable-v1",
        "taskId": target["run_id"],
        "planVersionId": target["plan_version_id"],
        "attemptId": target["attempt_id"],
        "deliverableType": target["deliverable_type"],
        "evidenceManifestArtifactId": target["evidence_manifest_artifact"]["artifact_id"],
        "methodSummary": target["method_summary"],
        "findingGraph": {
            "findings": [
                {
                    "id": "finding_1",
                    "kind": "fact",
                    "evidenceIds": ["evidence_1"],
                    "statement": "Alpha differs.",
                }
            ],
            "analyses": [
                {"id": "analysis_1", "findingIds": ["finding_1"], "statement": "The difference matters."}
            ],
            "subQuestionSummaries": [
                {
                    "id": "summary_1",
                    "findingIds": ["finding_1"],
                    "analysisIds": ["analysis_1"],
                    "summary": "A supported answer.",
                }
            ],
            "overallConclusions": [
                {"id": "conclusion_1", "summaryIds": ["summary_1"], "statement": "Prefer Alpha."}
            ],
        },
        "payload": {
            "competitorSamples": [
                {
                    "id": value["id"],
                    "name": value["name"],
                    "rationale": value["rationale"],
                    "evidenceIds": value["evidence_ids"],
                }
                for value in payload["competitor_samples"]
            ],
            "dimensionMatrix": [
                {
                    "dimension": row["dimension"],
                    "weight": row["weight"],
                    "values": [
                        {
                            "sampleId": value["sample_id"],
                            "value": value["value"],
                            "score": value["score"],
                            "evidenceIds": value["evidence_ids"],
                        }
                        for value in row["values"]
                    ],
                }
                for row in payload["dimension_matrix"]
            ],
            "differences": [
                {
                    "id": value["id"],
                    "dimension": value["dimension"],
                    "statement": value["statement"],
                    "evidenceIds": value["evidence_ids"],
                }
                for value in payload["differences"]
            ],
            "impacts": [
                {
                    "differenceId": value["difference_id"],
                    "audience": value["audience"],
                    "statement": value["statement"],
                }
                for value in payload["impacts"]
            ],
            "actionRecommendations": [
                {
                    "id": value["id"],
                    "differenceIds": value["difference_ids"],
                    "priority": value["priority"],
                    "statement": value["statement"],
                }
                for value in payload["action_recommendations"]
            ],
            "managementSummary": payload["management_summary"],
            "scoringMethod": payload["scoring_method"],
            "roadmap": payload["roadmap"],
            "instrumentationPlan": payload["instrumentation_plan"],
            "userTestScript": payload["user_test_script"],
            "visualEvidence": [],
            "screenshotComparisons": [],
        },
        "recommendations": [
            {"id": "recommendation_1", "summaryIds": ["summary_1"], "statement": "Pilot Alpha."}
        ],
        "coverage": {
            "questionBindings": [{"questionId": "q_capabilities", "summaryIds": ["summary_1"]}],
            "successCriterionBindings": [
                {
                    "successCriterionId": "criterion_traceable",
                    "conclusionIds": ["conclusion_1"],
                    "recommendationIds": [],
                }
            ],
        },
        "risksAndOpenIssues": ["Only public evidence was available."],
        "capabilityProvenance": [{"id": "competitive-analysis", "type": "skill"}],
    }


def source_review_body() -> dict:
    return {
        "version": "report-review-v1",
        "taskId": "run_1",
        "planVersionId": "plan_1",
        "attemptId": "attempt_1",
        "deliverableArtifactId": "artifact_deliverable",
        "verdict": "pass",
        "dimensions": [
            {"id": dimension, "passed": True, "issues": []} for dimension in REVIEW_DIMENSIONS
        ],
        "revisionRound": 0,
    }


def source_report_body() -> dict:
    target = report_body()
    return {
        "version": "report-document-v1",
        "title": target["title"],
        "subtitle": target["subtitle"],
        "executiveSummary": target["executive_summary"],
        "sections": [
            {
                "id": section["id"],
                "title": section["title"],
                "questionIds": section["question_ids"],
                "blocks": [
                    {
                        **{key: value for key, value in block.items() if key != "evidence_ids"},
                        **({"evidenceIds": block["evidence_ids"]} if "evidence_ids" in block else {}),
                    }
                    for block in section["blocks"]
                ],
            }
            for section in target["sections"]
        ],
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
