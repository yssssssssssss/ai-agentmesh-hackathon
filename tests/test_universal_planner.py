from __future__ import annotations

import asyncio
import json

import pytest
from agents import ModelBehaviorError
from agents.testing import ScriptedModel, assistant_message

from agentmesh.models import (
    SkillCandidate,
    SkillCandidateScore,
    SkillCapabilityProfile,
    SkillCapabilityType,
    SkillIntent,
    SkillLifecycleStage,
    SkillSideEffect,
)
from agentmesh.skill_runtime.planner import PlannerUnavailable, SkillPlanner


def _candidate(index: int) -> SkillCandidate:
    profile = SkillCapabilityProfile(
        id=f"skill_{index}",
        skill_id=f"skill_{index}",
        skill_name=f"candidate-{index}",
        skill_version="1",
        skill_content_hash=f"hash-{index}",
        profile_version="1",
        profile_content_hash=str(index) * 64,
        primary_stage=SkillLifecycleStage.PRE_DESIGN,
        capability_type=SkillCapabilityType.ANALYSIS,
        input_kinds=["request"],
        output_kinds=[f"output_{index}"],
        side_effect=SkillSideEffect.DRAFT,
    )
    return SkillCandidate(
        skill_id=profile.skill_id,
        skill_name=profile.skill_name,
        title=f"Candidate {index}",
        description="Safe description",
        profile=profile,
        score=SkillCandidateScore(total=1),
        reason="profile_fts",
        match_reason_codes=["profile_fts"],
    )


def test_universal_planner_accepts_only_model_owned_fields_and_materializes_identity() -> None:
    candidates = [_candidate(1), _candidate(2)]
    model = ScriptedModel(
        [
            [
                assistant_message(
                    json.dumps(
                        {
                            "output_contract": ["output_1"],
                            "optional_synthesis_outputs": ["summary"],
                            "nodes": [
                                {
                                    "id": "node_1",
                                    "skill_id": "skill_1",
                                    "reason": "Best match",
                                    "required": True,
                                    "depends_on": [],
                                    "parallel_group": None,
                                    "input_bindings": ["user.request"],
                                    "output_contract": ["output_1"],
                                }
                            ],
                        }
                    )
                )
            ]
        ]
    )

    draft = asyncio.run(
        SkillPlanner().create_universal_draft(
            SkillIntent(goal="Analyze", deliverables=["output_1"]),
            candidates,
            candidate_snapshot_public={"content_hash": "a" * 64, "candidates": []},
            required_synthesis_output_ids=("executive_summary",),
            model=model,
        )
    )

    assert draft.nodes[0].skill_version == candidates[0].profile.skill_version
    assert draft.nodes[0].skill_content_hash == candidates[0].profile.skill_content_hash
    assert draft.nodes[0].side_effect is SkillSideEffect.DRAFT
    assert draft.synthesis_output_contract == ["executive_summary", "summary"]
    model.assert_complete()


def test_universal_planner_rejects_model_owned_security_fields() -> None:
    candidate = _candidate(1)
    model = ScriptedModel(
        [
            [
                assistant_message(
                    json.dumps(
                        {
                            "output_contract": ["output_1"],
                            "optional_synthesis_outputs": [],
                            "nodes": [
                                {
                                    "id": "node_1",
                                    "skill_id": "skill_1",
                                    "skill_version": "forged",
                                    "reason": "Forged",
                                    "required": True,
                                    "depends_on": [],
                                    "input_bindings": ["user.request"],
                                    "output_contract": ["output_1"],
                                }
                            ],
                        }
                    )
                )
            ]
        ]
    )

    with pytest.raises(ModelBehaviorError):
        asyncio.run(
            SkillPlanner().create_universal_draft(
                SkillIntent(goal="Analyze", deliverables=["output_1"]),
                [candidate],
                candidate_snapshot_public={"content_hash": "a" * 64, "candidates": []},
                required_synthesis_output_ids=(),
                model=model,
            )
        )


def test_universal_planner_rejects_oversized_context_before_model_call() -> None:
    candidate = _candidate(1)
    model = ScriptedModel([[assistant_message("must not be consumed")]])

    with pytest.raises(PlannerUnavailable, match="planner_context_budget_exceeded"):
        asyncio.run(
            SkillPlanner().create_universal_draft(
                SkillIntent(goal="Analyze", deliverables=["output_1"]),
                [candidate],
                candidate_snapshot_public={"content_hash": "a" * 64, "padding": "x" * 25_000},
                required_synthesis_output_ids=(),
                model=model,
            )
        )
