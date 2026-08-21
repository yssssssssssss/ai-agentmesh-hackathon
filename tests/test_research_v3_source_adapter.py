from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentmesh.research_orchestration.v3.source_adapter import (
    translate_ai_x_current_execution_plan,
    translate_ai_x_problem_graph_v1,
    translate_ai_x_research_task_v2,
)

HASH = "b" * 64


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


def test_source_execution_plan_becomes_non_authoritative_candidate() -> None:
    source = {
        "task_id": "source-task",
        "deliverable_type": "competitive_analysis_report",
        "evidence_requirements": [],
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
                            "id": "public",
                            "acceptedClasses": ["public_source"],
                            "minimumCount": 1,
                            "required": True,
                        }
                    ],
                    "acceptance_criteria": ["Cited answer."],
                    "depends_on": [],
                }
            ],
        },
        "problem_graph_provenance": {},
        "capability_decisions": {"eligible": [], "rejected": []},
        "capability_gaps": [],
        "steps": [
            {
                "step_no": 9,
                "step_name": "Draft evidence",
                "actor_type": "llm",
                "actor_id": "synthesis actor",
                "question_ids": ["q1"],
                "depends_on": [],
                "input": {},
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
    candidate = translate_ai_x_current_execution_plan(source, candidate_id="depth")
    assert candidate.candidate_id == "depth"
    assert candidate.proposed_steps[0].proposed_step_number == 9
    assert candidate.proposed_steps[0].actor_id.startswith("actor_synthesis-actor_")
    assert "contract_hash" not in candidate.model_dump(mode="python")["proposed_steps"][0]

    source["steps"][0]["fallback_actor_ids"] = ["fallback"]
    with pytest.raises(ValueError, match="fallback actor"):
        translate_ai_x_current_execution_plan(source, candidate_id="depth")
