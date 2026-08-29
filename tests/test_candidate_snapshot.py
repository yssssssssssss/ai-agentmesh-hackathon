from __future__ import annotations

import pytest

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.models import (
    AgentPlanningContractVersion,
    AgentRun,
    AgentRunStatus,
    CandidateIdentityV1,
    CandidateSnapshotPublicViewV1,
    CandidateSnapshotV1,
    DeliverableAtomV1,
    SkillIntent,
    SkillPlan,
    SkillPlanNode,
    SkillPlanPublicView,
    SkillPlanStatus,
    SkillResourceManifestV1,
)
from agentmesh.store import SQLiteStore


def _snapshot() -> CandidateSnapshotV1:
    atom = DeliverableAtomV1(
        id="deliverable:analysis_result",
        label="Analysis result",
        output_kind="analysis_result",
    )
    card = {
        "skill_id": "skill_candidate",
        "name": "candidate",
        "title": "Candidate",
        "description": "Analyze a bounded input.",
        "aliases": [],
        "primary_stage": "pre_design",
        "capability_type": "analysis",
        "input_kinds": ["request"],
        "output_kinds": ["analysis_result"],
        "side_effect": "read",
        "cost_level": "low",
        "risk_level": "low",
        "required_tools": [],
    }
    candidate = CandidateIdentityV1(
        skill_id="skill_candidate",
        skill_name="candidate",
        skill_version="1",
        skill_content_hash="a" * 64,
        profile_version="1",
        profile_content_hash="b" * 64,
        capability_card=card,
        capability_card_hash=canonical_json_sha256(card),
        match_reason_codes=("profile_fts",),
        covered_requirement_ids=(atom.id,),
    )
    body = {
        "schema_version": "candidate-snapshot-v1",
        "retrieval_policy_version": "universal-profile-rrf-v2",
        "required_coverage_atoms": [atom.model_dump(mode="json")],
        "plannable_coverage_atom_ids": [atom.id],
        "required_synthesis_output_ids": [],
        "coverage_witness_skill_ids": [candidate.skill_id],
        "candidates": [candidate.model_dump(mode="json")],
    }
    return CandidateSnapshotV1(**body, content_hash=canonical_json_sha256(body))


def test_candidate_snapshot_hash_and_plan_projection_are_strict() -> None:
    snapshot = _snapshot()
    plan = SkillPlan(
        id="plan_snapshot",
        run_id="run_snapshot",
        intent=SkillIntent(goal="Analyze this", deliverables=["analysis_result"]),
        candidate_skill_ids=["skill_candidate"],
        candidate_snapshot=snapshot,
        nodes=[
            SkillPlanNode(
                id="node_snapshot",
                skill_id="skill_candidate",
                skill_version="1",
                skill_content_hash="a" * 64,
                reason="Analyze",
                output_contract=["analysis_result"],
                required_tool_names=["private_tool"],
                resource_manifest=SkillResourceManifestV1(
                    required_resources=["private/path.md"],
                    resource_hashes={"private/path.md": "c" * 64},
                    content_hash=canonical_json_sha256(
                        {
                            "schema_version": "skill-resource-manifest-v1",
                            "required_resources": ["private/path.md"],
                            "resource_hashes": {"private/path.md": "c" * 64},
                        }
                    ),
                ),
            )
        ],
    )

    public = SkillPlanPublicView.from_plan(plan)

    assert isinstance(public.candidate_snapshot, CandidateSnapshotPublicViewV1)
    serialized = public.model_dump_json()
    assert snapshot.content_hash in serialized
    assert "profile_content_hash" not in serialized
    assert "skill_content_hash" not in serialized
    assert "evidence_path_witnesses" not in serialized
    assert "tool_implementation_id" not in serialized
    assert "skill_content_hash" not in serialized
    assert "resource_manifest" not in serialized
    assert "private/path.md" not in serialized


def test_candidate_snapshot_rejects_full_canonical_payload_over_32_kib() -> None:
    atom = DeliverableAtomV1(
        id="deliverable:analysis_result",
        label="Analysis result",
        output_kind="analysis_result",
    )
    candidates = []
    for index in range(12):
        card = {
            "skill_id": f"skill_{index}",
            "name": f"candidate-{index}",
            "title": f"Candidate {index}",
            "description": "x" * 2000,
            "aliases": [],
            "primary_stage": "pre_design",
            "capability_type": "analysis",
            "input_kinds": ["request"],
            "output_kinds": ["analysis_result"],
            "side_effect": "read",
            "cost_level": "low",
            "risk_level": "low",
            "required_tools": [],
        }
        candidates.append(
            CandidateIdentityV1(
                skill_id=f"skill_{index}",
                skill_name=f"candidate-{index}",
                skill_version="1",
                skill_content_hash="a" * 64,
                profile_version="1",
                profile_content_hash="b" * 64,
                capability_card=card,
                capability_card_hash=canonical_json_sha256(card),
                covered_requirement_ids=(atom.id,),
            )
        )
    body = {
        "schema_version": "candidate-snapshot-v1",
        "retrieval_policy_version": "universal-profile-rrf-v2",
        "required_coverage_atoms": [atom.model_dump(mode="json")],
        "plannable_coverage_atom_ids": [atom.id],
        "required_synthesis_output_ids": [],
        "coverage_witness_skill_ids": ["skill_0"],
        "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
    }

    with pytest.raises(ValueError, match="candidate snapshot exceeds 32 KiB"):
        CandidateSnapshotV1(**body, content_hash=canonical_json_sha256(body))


def test_standard_planning_skeleton_is_created_completed_and_failed_atomically(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "candidate-skeleton.sqlite3")
    run = repository.save_agent_run(
        AgentRun(
            id="run_candidate_skeleton",
            thread_id="thread_candidate_skeleton",
            user_id="usr_test",
            workspace_id="ws_test",
            project_id="prj_test",
            input_text="Analyze this",
            status=AgentRunStatus.PLANNING,
            planning_contract_version=AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1,
        )
    )
    snapshot = _snapshot()
    skeleton = SkillPlan(
        id="plan_candidate_skeleton",
        run_id=run.id,
        intent=SkillIntent(goal="Analyze this", deliverables=["analysis_result"]),
        candidate_skill_ids=["skill_candidate"],
        candidate_snapshot=snapshot,
        status=SkillPlanStatus.PLANNING,
        nodes=[],
    )

    created = repository.create_standard_planning_skeleton(run_id=run.id, plan=skeleton)

    assert created is not None
    persisted_plan, persisted_run = created
    assert persisted_run.plan_id == persisted_plan.id
    assert persisted_run.status is AgentRunStatus.PLANNING
    assert repository.list_agent_run_events(run.id)[-1].event_type == "candidate_snapshot_created"

    completed = skeleton.model_copy(
        deep=True,
        update={
            "status": SkillPlanStatus.WAITING_APPROVAL,
            "nodes": [
                SkillPlanNode(
                    id="node_candidate_skeleton",
                    skill_id="skill_candidate",
                    skill_version="1",
                    skill_content_hash="a" * 64,
                    reason="Analyze",
                    output_contract=["analysis_result"],
                )
            ],
        },
    )
    transition = repository.complete_standard_planning_skeleton(
        plan=completed,
        expected_version=1,
        next_run_status=AgentRunStatus.WAITING_PLAN_APPROVAL,
        events=[("plan_created", {"plan_id": completed.id})],
    )

    assert transition is not None
    final_plan, final_run = transition
    assert final_plan.version == 2
    assert final_run.status is AgentRunStatus.WAITING_PLAN_APPROVAL


def test_standard_planning_skeleton_failure_preserves_snapshot_for_audit(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "candidate-skeleton-failure.sqlite3")
    run = repository.save_agent_run(
        AgentRun(
            id="run_candidate_skeleton_failure",
            thread_id="thread_candidate_skeleton_failure",
            user_id="usr_test",
            workspace_id="ws_test",
            project_id="prj_test",
            input_text="Analyze this",
            status=AgentRunStatus.PLANNING,
            planning_contract_version=AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1,
        )
    )
    snapshot = _snapshot()
    skeleton = SkillPlan(
        id="plan_candidate_skeleton_failure",
        run_id=run.id,
        intent=SkillIntent(goal="Analyze this", deliverables=["analysis_result"]),
        candidate_skill_ids=["skill_candidate"],
        candidate_snapshot=snapshot,
        status=SkillPlanStatus.PLANNING,
        nodes=[],
    )
    assert repository.create_standard_planning_skeleton(run_id=run.id, plan=skeleton) is not None

    failed = repository.fail_standard_planning_skeleton(
        run_id=run.id,
        plan_id=skeleton.id,
        error_code="planner_schema_invalid",
    )

    assert failed is not None
    failed_plan, failed_run = failed
    assert failed_plan.status is SkillPlanStatus.FAILED
    assert failed_plan.candidate_snapshot == snapshot
    assert failed_run.status is AgentRunStatus.FAILED
    assert failed_run.error_code == "planner_schema_invalid"


def test_skill_plan_rejects_candidate_projection_order_drift() -> None:
    snapshot = _snapshot()

    try:
        SkillPlan(
            id="plan_snapshot_drift",
            run_id="run_snapshot_drift",
            intent=SkillIntent(goal="Analyze this", deliverables=["analysis_result"]),
            candidate_skill_ids=["different_skill"],
            candidate_snapshot=snapshot,
        )
    except ValueError as error:
        assert "candidate_skill_ids" in str(error)
    else:
        raise AssertionError("candidate projection drift was accepted")
