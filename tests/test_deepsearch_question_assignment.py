from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentmesh.agent_runtime.service import _assign_problem_questions
from agentmesh.deepsearch.contracts import (
    ProblemQuestionV1,
    RequirementPayloadV1,
    RequirementScopeV1,
    RequirementSuccessCriterionV1,
    RequirementVersionV1,
    build_problem_graph,
    problem_question_id,
    requirement_content_hash,
)
from agentmesh.models import (
    SkillCandidate,
    SkillCandidateScore,
    SkillCapabilityProfile,
    SkillCapabilityType,
    SkillLifecycleStage,
    SkillPlanDraft,
    SkillPlanNode,
)
from agentmesh.skill_runtime.planner import PlannerUnavailable


def _requirement() -> RequirementVersionV1:
    payload = RequirementPayloadV1(
        goal="Evaluate a market and recommend a product direction",
        scope=RequirementScopeV1(),
        success_criteria=[
            RequirementSuccessCriterionV1(id="criterion_market", statement="Quantify the market size"),
            RequirementSuccessCriterionV1(id="criterion_direction", statement="Recommend a product direction"),
        ],
        deliverables=["Research report"],
    )
    return RequirementVersionV1(
        id="requirement_semantic_assignment",
        run_id="run_semantic_assignment",
        version=1,
        request_key="turn_semantic_assignment",
        request_hash="a" * 64,
        content_hash=requirement_content_hash(payload),
        payload=payload,
        created_at=datetime(2026, 8, 27, tzinfo=UTC),
    )


def _question(
    text: str,
    *,
    criterion_id: str,
    evidence: str,
    acceptance: str,
) -> ProblemQuestionV1:
    return ProblemQuestionV1(
        id=problem_question_id(text),
        question=text,
        required=True,
        success_criterion_ids=[criterion_id],
        evidence_requirements=[evidence],
        acceptance_criteria=[acceptance],
    )


def _candidate(skill_id: str, name: str, title: str, description: str, output: str) -> SkillCandidate:
    profile = SkillCapabilityProfile(
        id=f"profile_{skill_id}",
        skill_id=skill_id,
        skill_name=name,
        skill_version="1",
        skill_content_hash=skill_id[-1] * 64,
        profile_version="1",
        profile_content_hash="f" * 64,
        primary_stage=SkillLifecycleStage.PRE_DESIGN,
        capability_type=SkillCapabilityType.RESEARCH,
        output_kinds=[output],
    )
    return SkillCandidate(
        skill_id=skill_id,
        skill_name=name,
        title=title,
        description=description,
        profile=profile,
        score=SkillCandidateScore(total=10),
        reason=description,
    )


def test_problem_questions_follow_node_semantics_instead_of_array_order() -> None:
    requirement = _requirement()
    recommendation = _question(
        "What product direction should we recommend?",
        criterion_id="criterion_direction",
        evidence="Use the market findings",
        acceptance="Recommend one evidence-linked product direction",
    )
    market = _question(
        "What is the market size?",
        criterion_id="criterion_market",
        evidence="Use current public market data",
        acceptance="State a sourced market-size estimate",
    )
    graph = build_problem_graph(requirement=requirement, questions=[recommendation, market])
    market_candidate = _candidate(
        "skill_market_1",
        "market-research",
        "Market research",
        "Quantify market size from public sources",
        "market_analysis",
    )
    direction_candidate = _candidate(
        "skill_direction_2",
        "product-direction",
        "Product direction",
        "Recommend an evidence-linked product direction",
        "product_recommendation",
    )
    draft = SkillPlanDraft(
        nodes=[
            SkillPlanNode(
                id="node_market",
                skill_id=market_candidate.skill_id,
                skill_version="1",
                skill_content_hash=market_candidate.profile.skill_content_hash,
                reason="Quantify the market size",
                output_contract=["market_analysis"],
            ),
            SkillPlanNode(
                id="node_direction",
                skill_id=direction_candidate.skill_id,
                skill_version="1",
                skill_content_hash=direction_candidate.profile.skill_content_hash,
                reason="Recommend a product direction",
                output_contract=["product_recommendation"],
            ),
        ]
    )

    assigned = _assign_problem_questions(
        requirement=requirement,
        graph=graph,
        draft=draft,
        candidates=[market_candidate, direction_candidate],
    )

    by_id = {node.id: node.question_ids for node in assigned.nodes}
    assert by_id == {
        "node_market": [market.id],
        "node_direction": [recommendation.id],
    }


def test_problem_question_assignment_fails_closed_without_a_unique_semantic_match() -> None:
    requirement = _requirement()
    question = _question(
        "What is the market size?",
        criterion_id="criterion_market",
        evidence="Use current public data",
        acceptance="State a sourced estimate",
    )
    direction = _question(
        "Which product direction should be recommended?",
        criterion_id="criterion_direction",
        evidence="Use the findings",
        acceptance="Give one recommendation",
    )
    graph = build_problem_graph(requirement=requirement, questions=[question, direction])
    first = _candidate("skill_generic_1", "generic-one", "General analysis", "Analyze the request", "analysis")
    second = _candidate("skill_generic_2", "generic-two", "General analysis", "Analyze the request", "analysis")
    draft = SkillPlanDraft(
        nodes=[
            SkillPlanNode(
                id="node_one",
                skill_id=first.skill_id,
                skill_version="1",
                skill_content_hash=first.profile.skill_content_hash,
                reason="Analyze the request",
            ),
            SkillPlanNode(
                id="node_two",
                skill_id=second.skill_id,
                skill_version="1",
                skill_content_hash=second.profile.skill_content_hash,
                reason="Analyze the request",
            ),
        ]
    )

    with pytest.raises(PlannerUnavailable, match=question.id):
        _assign_problem_questions(
            requirement=requirement,
            graph=graph,
            draft=draft,
            candidates=[first, second],
        )
