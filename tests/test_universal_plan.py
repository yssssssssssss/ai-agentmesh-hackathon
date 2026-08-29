from __future__ import annotations

from pathlib import Path

import pytest

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.models import (
    CandidateIdentityV1,
    CandidateSnapshotV1,
    DeliverableAtomV1,
    ScenarioOutputAtomV1,
    SkillCandidate,
    SkillCandidateScore,
    SkillCapabilityProfile,
    SkillCapabilityType,
    SkillDefinition,
    SkillIntent,
    SkillLifecycleStage,
    SkillNodeResult,
    SkillPlan,
    SkillPlanDraft,
    SkillPlanNode,
    SkillPlanNodeStatus,
    SkillPlanStatus,
    SkillSourceScope,
)
from agentmesh.skill_runtime.plan_validation import PlanValidationError
from agentmesh.skill_runtime.profiles import skill_capability_card
from agentmesh.skill_runtime.universal_plan import (
    covered_result_atom_ids,
    evaluate_universal_completion,
    has_valid_partial_delivery,
    materialize_universal_draft,
    validate_universal_plan,
)
from agentmesh.task_routing.catalog import load_universal_task_catalog
from agentmesh.task_routing.contracts import ScenarioRoute, TaskRoute, TaskRoutingResult


def _candidate(tmp_path: Path, index: int) -> tuple[SkillDefinition, SkillCandidate, CandidateIdentityV1]:
    root = tmp_path / f"skill-{index}"
    root.mkdir()
    path = root / "SKILL.md"
    path.write_text(f"# Skill {index}\n", encoding="utf-8")
    skill = SkillDefinition(
        id=f"skill_{index}",
        name=f"skill-{index}",
        title=f"Skill {index}",
        description="Research planning",
        instructions=f"# Skill {index}",
        source_path=str(path),
        source_scope=SkillSourceScope.BUILTIN,
        content_hash=f"{index}" * 64,
        version="1",
    )
    profile = SkillCapabilityProfile(
        id=skill.id,
        skill_id=skill.id,
        skill_name=skill.name,
        skill_title=skill.title,
        skill_version=skill.version,
        skill_content_hash=skill.content_hash,
        profile_version="1",
        profile_content_hash=("a" if index == 1 else "b") * 64,
        primary_stage=SkillLifecycleStage.PRE_DESIGN,
        capability_type=SkillCapabilityType.PLANNING,
        input_kinds=["request"],
        output_kinds=["research_plan"],
        side_effect="draft",
        planner_eligible=False,
    )
    candidate = SkillCandidate(
        skill_id=skill.id,
        skill_name=skill.name,
        title=skill.title,
        description=skill.description,
        profile=profile,
        score=SkillCandidateScore(total=1),
        reason="profile_fts",
        match_reason_codes=["profile_fts"],
    )
    card = skill_capability_card(skill, profile)
    identity = CandidateIdentityV1(
        skill_id=skill.id,
        skill_name=skill.name,
        skill_version=skill.version,
        skill_content_hash=skill.content_hash,
        profile_version=profile.profile_version,
        profile_content_hash=profile.profile_content_hash,
        capability_card=card,
        capability_card_hash=canonical_json_sha256(card),
        match_reason_codes=("profile_fts",),
        coverage_witness_scenario_id=(
            "metrics-validation" if index == 1 else "trend-change-identification"
        ),
        covered_requirement_ids=(
            "deliverable:research_plan",
            (
                "scenario:metrics-validation:output:validation_plan"
                if index == 1
                else "scenario:trend-change-identification:output:open_validation_questions"
            ),
        ),
    )
    return skill, candidate, identity


def _snapshot(identities: list[CandidateIdentityV1]) -> CandidateSnapshotV1:
    atoms = [
        DeliverableAtomV1(
            id="deliverable:research_plan",
            label="research_plan",
            output_kind="research_plan",
        ),
        ScenarioOutputAtomV1(
            id="scenario:metrics-validation:output:validation_plan",
            label="验证计划",
            scenario_id="metrics-validation",
            output_id="validation_plan",
            compatible_output_kinds=("research_plan",),
        ),
        ScenarioOutputAtomV1(
            id="scenario:trend-change-identification:output:open_validation_questions",
            label="待验证问题",
            scenario_id="trend-change-identification",
            output_id="open_validation_questions",
            compatible_output_kinds=("research_plan",),
        ),
    ]
    body = {
        "schema_version": "candidate-snapshot-v1",
        "retrieval_policy_version": "universal-profile-rrf-v2",
        "required_coverage_atoms": [atom.model_dump(mode="json") for atom in atoms],
        "plannable_coverage_atom_ids": [atom.id for atom in atoms],
        "required_synthesis_output_ids": [],
        "coverage_witness_skill_ids": [identity.skill_id for identity in identities],
        "candidates": [identity.model_dump(mode="json") for identity in identities],
    }
    return CandidateSnapshotV1(**body, content_hash=canonical_json_sha256(body))


def test_universal_scenario_assignment_is_server_owned_and_required_before_approval(tmp_path: Path) -> None:
    catalog = load_universal_task_catalog()
    skills_and_candidates = [_candidate(tmp_path, 1), _candidate(tmp_path, 2)]
    skills = {skill.id: skill for skill, _candidate_value, _identity in skills_and_candidates}
    candidates = [candidate for _skill, candidate, _identity in skills_and_candidates]
    snapshot = _snapshot([identity for _skill, _candidate_value, identity in skills_and_candidates])
    routing = TaskRoutingResult(
        catalog_version=catalog.manifest.catalog_version,
        catalog_hash=catalog.manifest.catalog_hash,
        task=TaskRoute(task_id="define-strategy", confidence="high"),
        scenario=ScenarioRoute(
            scenario_id="metrics-validation",
            confidence="high",
            supporting_scenarios=["trend-change-identification"],
        ),
    )
    intent = SkillIntent(goal="Plan validation", deliverables=["research_plan"])
    proposed = SkillPlanDraft(
        output_contract=["research_plan"],
        nodes=[
            SkillPlanNode(
                id=f"node_{index}",
                skill_id=candidate.skill_id,
                skill_version=candidate.profile.skill_version,
                skill_content_hash=candidate.profile.skill_content_hash,
                reason="Cover one Scenario",
                input_bindings=["user.request"],
                output_contract=["research_plan"],
                side_effect="draft",
            )
            for index, candidate in enumerate(candidates, start=1)
        ],
    )

    ambiguous = materialize_universal_draft(
        draft=proposed,
        intent=intent,
        candidates=candidates,
        snapshot=snapshot,
        routing=routing,
        catalog=catalog,
        skill_lookup=skills.get,
    )

    assert all(node.scenario_id is None for node in ambiguous.nodes)
    assert set(ambiguous.capability_gaps) >= {
        "scenario_assignment_required:skill_1",
        "scenario_assignment_required:skill_2",
    }

    assigned = materialize_universal_draft(
        draft=proposed,
        intent=intent,
        candidates=candidates,
        snapshot=snapshot,
        routing=routing,
        catalog=catalog,
        skill_lookup=skills.get,
        scenario_assignments={
            "skill_1": "metrics-validation",
            "skill_2": "trend-change-identification",
        },
    )
    from agentmesh.models import SkillPlan

    plan = SkillPlan(
        id="plan_assigned",
        run_id="run_assigned",
        status=SkillPlanStatus.WAITING_APPROVAL,
        intent=intent,
        routing_result=routing,
        candidate_skill_ids=[candidate.skill_id for candidate in candidates],
        candidate_snapshot=snapshot,
        output_contract=assigned.output_contract,
        synthesis_output_contract=assigned.synthesis_output_contract,
        capability_gaps=assigned.capability_gaps,
        nodes=assigned.nodes,
    )
    validate_universal_plan(
        plan=plan,
        candidates=candidates,
        catalog=catalog,
        require_concrete_assignments=True,
    )
    assert [node.scenario_id for node in assigned.nodes] == [
        "metrics-validation",
        "trend-change-identification",
    ]
    assert assigned.capability_gaps == []

    (tmp_path / "skill-1" / "new-resource.md").write_text("drift", encoding="utf-8")
    with pytest.raises(PlanValidationError, match="skill_resource_changed"):
        materialize_universal_draft(
            draft=assigned,
            intent=intent,
            candidates=candidates,
            snapshot=snapshot,
            routing=routing,
            catalog=catalog,
            skill_lookup=skills.get,
            scenario_assignments={
                "skill_1": "metrics-validation",
                "skill_2": "trend-change-identification",
            },
        )


def test_universal_result_coverage_uses_delivered_kinds_and_scenario_output_ids(tmp_path: Path) -> None:
    catalog = load_universal_task_catalog()
    skills_and_candidates = [_candidate(tmp_path, 1), _candidate(tmp_path, 2)]
    skills = {skill.id: skill for skill, _candidate_value, _identity in skills_and_candidates}
    candidates = [candidate for _skill, candidate, _identity in skills_and_candidates]
    snapshot = _snapshot([identity for _skill, _candidate_value, identity in skills_and_candidates])
    routing = TaskRoutingResult(
        catalog_version=catalog.manifest.catalog_version,
        catalog_hash=catalog.manifest.catalog_hash,
        task=TaskRoute(task_id="define-strategy", confidence="high"),
        scenario=ScenarioRoute(
            scenario_id="metrics-validation",
            confidence="high",
            supporting_scenarios=["trend-change-identification"],
        ),
    )
    intent = SkillIntent(goal="Plan validation", deliverables=["research_plan"])
    proposed = SkillPlanDraft(
        output_contract=["research_plan"],
        nodes=[
            SkillPlanNode(
                id=f"node_{index}",
                skill_id=candidate.skill_id,
                skill_version=candidate.profile.skill_version,
                skill_content_hash=candidate.profile.skill_content_hash,
                reason="Cover one Scenario",
                input_bindings=["user.request"],
                output_contract=["research_plan"],
                side_effect="draft",
            )
            for index, candidate in enumerate(candidates, start=1)
        ],
    )
    assigned = materialize_universal_draft(
        draft=proposed,
        intent=intent,
        candidates=candidates,
        snapshot=snapshot,
        routing=routing,
        catalog=catalog,
        skill_lookup=skills.get,
        scenario_assignments={
            "skill_1": "metrics-validation",
            "skill_2": "trend-change-identification",
        },
    )
    completed_nodes = [
        node.model_copy(update={"status": SkillPlanNodeStatus.COMPLETED}) for node in assigned.nodes
    ]
    plan = SkillPlan(
        id="plan_result_coverage",
        run_id="run_result_coverage",
        status=SkillPlanStatus.RUNNING,
        intent=intent,
        routing_result=routing,
        candidate_skill_ids=[candidate.skill_id for candidate in candidates],
        candidate_snapshot=snapshot,
        output_contract=assigned.output_contract,
        synthesis_output_contract=assigned.synthesis_output_contract,
        capability_gaps=assigned.capability_gaps,
        nodes=completed_nodes,
    )
    results = [
        SkillNodeResult(
            id=f"result_{index}",
            node_id=node.id,
            skill_id=node.skill_id,
            summary="Delivered",
            deliverable_markdown="Non-empty deliverable",
            delivered_output_kinds=["research_plan"],
            scenario_outputs=[
                "validation_plan"
                if node.scenario_id == "metrics-validation"
                else "open_validation_questions"
            ],
        )
        for index, node in enumerate(completed_nodes, start=1)
    ]

    covered = covered_result_atom_ids(plan=plan, results=results)
    completion = evaluate_universal_completion(
        plan=plan,
        results=results,
        synthesis=None,
        synthesis_artifacts_sealed=False,
    )

    assert set(covered) == set(snapshot.plannable_coverage_atom_ids)
    assert completion.completed is True
    assert completion.gaps == []
    assert has_valid_partial_delivery(plan=plan, results=results) is True

    invalid = results[0].model_copy(update={"delivered_output_kinds": [], "scenario_outputs": ["验证计划"]})
    assert "scenario:metrics-validation:output:validation_plan" not in covered_result_atom_ids(
        plan=plan,
        results=[invalid, results[1]],
    )
