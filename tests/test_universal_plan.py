from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.models import (
    AgentExecutionContractVersion,
    AgentPlanningContractVersion,
    AgentRun,
    AgentRunStatus,
    ArtifactVerificationState,
    CandidateEvidencePathWitnessV1,
    CandidateIdentityV1,
    CandidateSnapshotV1,
    DeliverableAtomV1,
    EvidenceAtomV1,
    RuntimeToolCallClaimV1,
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
    SkillSynthesisResult,
    Source,
    ToolDefinition,
)
from agentmesh.skill_runtime.finalization import StandardPlanFinalizer
from agentmesh.skill_runtime.plan_validation import PlanValidationError
from agentmesh.skill_runtime.profiles import skill_capability_card
from agentmesh.skill_runtime.synthesis import _synthesis_node_projection, deterministic_synthesis
from agentmesh.skill_runtime.universal_plan import (
    covered_result_atom_ids,
    evaluate_universal_completion,
    has_valid_partial_delivery,
    materialize_universal_draft,
    validate_universal_plan,
)
from agentmesh.store import SQLiteStore
from agentmesh.task_routing.catalog import load_universal_task_catalog
from agentmesh.task_routing.contracts import ScenarioRoute, TaskRoute, TaskRoutingResult
from agentmesh.tool_runtime.factory import AgentMeshToolFactory


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
    synthesis_projection = _synthesis_node_projection(assigned.nodes[0])
    assert "resource_manifest" not in synthesis_projection
    assert "skill_content_hash" not in synthesis_projection
    assert "required_tool_names" not in synthesis_projection

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
            completion_criteria_met=list(node.completion_criteria),
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
    assert completion.criteria_results
    assert all(key.startswith("scenario:") for key in completion.criteria_results)
    assert has_valid_partial_delivery(plan=plan, results=results) is True

    invalid = results[0].model_copy(update={"delivered_output_kinds": [], "scenario_outputs": ["验证计划"]})
    assert "scenario:metrics-validation:output:validation_plan" not in covered_result_atom_ids(
        plan=plan,
        results=[invalid, results[1]],
    )


def test_universal_finalizer_uses_delivered_output_kinds_for_completion(tmp_path: Path) -> None:
    repository = SQLiteStore(tmp_path / "universal-finalization.sqlite3")
    skill, candidate, identity = _candidate(tmp_path, 1)
    del skill
    atom = DeliverableAtomV1(
        id="deliverable:research_plan",
        label="research_plan",
        output_kind="research_plan",
    )
    identity = identity.model_copy(
        update={
            "coverage_witness_scenario_id": None,
            "covered_requirement_ids": (atom.id,),
        }
    )
    snapshot_body = {
        "schema_version": "candidate-snapshot-v1",
        "retrieval_policy_version": "universal-profile-rrf-v2",
        "required_coverage_atoms": [atom.model_dump(mode="json")],
        "plannable_coverage_atom_ids": [atom.id],
        "required_synthesis_output_ids": ["summary"],
        "coverage_witness_skill_ids": [identity.skill_id],
        "candidates": [identity.model_dump(mode="json")],
    }
    snapshot = CandidateSnapshotV1(
        **snapshot_body,
        content_hash=canonical_json_sha256(snapshot_body),
    )
    run = repository.save_agent_run(
        AgentRun(
            id="run_universal_finalization",
            thread_id="thread_universal_finalization",
            user_id="usr_test",
            workspace_id="ws_test",
            project_id="prj_test",
            input_text="Create a research plan",
            status=AgentRunStatus.RUNNING,
            planning_contract_version=AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1,
            execution_contract_version=AgentExecutionContractVersion.STANDARD_UNIVERSAL_V1,
        )
    )
    node = SkillPlanNode(
        id="node_universal_finalization",
        skill_id=candidate.skill_id,
        skill_version=candidate.profile.skill_version,
        skill_content_hash=candidate.profile.skill_content_hash,
        reason="Create the plan",
        output_contract=["research_plan"],
        side_effect="draft",
        status=SkillPlanNodeStatus.COMPLETED,
    )
    plan = repository.save_skill_plan(
        SkillPlan(
            id="plan_universal_finalization",
            run_id=run.id,
            status=SkillPlanStatus.RUNNING,
            intent=SkillIntent(goal="Create a research plan", deliverables=["research_plan"]),
            routing_result=TaskRoutingResult(
                catalog_version=load_universal_task_catalog().manifest.catalog_version,
                catalog_hash=load_universal_task_catalog().manifest.catalog_hash,
                task=TaskRoute(task_id="define-strategy", confidence="high"),
                scenario=ScenarioRoute(
                    scenario_id="metrics-validation",
                    confidence="high",
                ),
            ),
            candidate_skill_ids=[candidate.skill_id],
            candidate_snapshot=snapshot,
            execution_contract_version=AgentExecutionContractVersion.STANDARD_UNIVERSAL_V1,
            output_contract=["research_plan"],
            nodes=[node],
        )
    )
    repository.save_agent_run(run.model_copy(update={"plan_id": plan.id}))
    repository.save_skill_node_result(
        plan.id,
        SkillNodeResult(
            id="result_universal_finalization",
            node_id=node.id,
            skill_id=node.skill_id,
            summary="Research plan complete",
            deliverable_markdown="# Research plan",
            delivered_output_kinds=["research_plan"],
        ),
    )

    async def synthesize(_plan, _results):  # noqa: ANN001, ANN202
        return SkillSynthesisResult(
            summary="Complete",
            presentation_outputs=["summary"],
        ), False

    outcome = asyncio.run(
        StandardPlanFinalizer(repository, synthesis_runner=synthesize).finalize(
            run_id=run.id,
            plan_id=plan.id,
            expected_plan_version=plan.version,
        )
    )

    assert outcome.plan.status is SkillPlanStatus.COMPLETED
    assert outcome.run.status is AgentRunStatus.COMPLETED
    assert outcome.plan.completion_check is not None
    assert outcome.plan.completion_check.completed is True
    assert outcome.synthesis is not None and outcome.synthesis.artifact_ids
    synthesis_artifact = repository.get_artifact(outcome.synthesis.artifact_ids[-1])
    assert synthesis_artifact is not None
    assert synthesis_artifact.verification_state is ArtifactVerificationState.SEALED
    fallback = deterministic_synthesis(
        repository.list_skill_node_results(plan.id),
        degradation=None,
        presentation_requirements=["summary"],
        plan_nodes=plan.nodes,
    )
    assert fallback.presentation_outputs == ["summary"]
    assert any(section.startswith("总结：") for section in fallback.sections)


def test_universal_web_tool_output_is_sealed_as_evidence(tmp_path: Path) -> None:
    repository = SQLiteStore(tmp_path / "universal-evidence.sqlite3")
    _skill, candidate, identity = _candidate(tmp_path, 1)
    atom = DeliverableAtomV1(
        id="deliverable:research_plan",
        label="research_plan",
        output_kind="research_plan",
    )
    evidence_atom = EvidenceAtomV1()
    witness_body = {
        "atom_id": evidence_atom.id,
        "tool_implementation_id": "provider.web.search",
        "tool_implementation_version": "1",
        "resource_or_adapter_identity": "tool:tool_web_research",
    }
    identity = identity.model_copy(
        update={
            "coverage_witness_scenario_id": None,
            "covered_requirement_ids": (atom.id, evidence_atom.id),
            "evidence_path_witnesses": (
                CandidateEvidencePathWitnessV1(
                    **witness_body,
                    identity_hash=canonical_json_sha256(witness_body),
                ),
            ),
        }
    )
    snapshot_body = {
        "schema_version": "candidate-snapshot-v1",
        "retrieval_policy_version": "universal-profile-rrf-v2",
        "required_coverage_atoms": [
            atom.model_dump(mode="json"),
            evidence_atom.model_dump(mode="json"),
        ],
        "plannable_coverage_atom_ids": [atom.id, evidence_atom.id],
        "required_synthesis_output_ids": [],
        "coverage_witness_skill_ids": [identity.skill_id],
        "candidates": [identity.model_dump(mode="json")],
    }
    snapshot = CandidateSnapshotV1(
        **snapshot_body,
        content_hash=canonical_json_sha256(snapshot_body),
    )
    run = repository.save_agent_run(
        AgentRun(
            id="run_universal_evidence",
            thread_id="thread_universal_evidence",
            user_id="usr_test",
            workspace_id="ws_test",
            project_id="prj_test",
            input_text="Research",
            status=AgentRunStatus.RUNNING,
            planning_contract_version=AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1,
            execution_contract_version=AgentExecutionContractVersion.STANDARD_UNIVERSAL_V1,
        )
    )
    node = SkillPlanNode(
        id="node_universal_evidence",
        skill_id=candidate.skill_id,
        skill_version=candidate.profile.skill_version,
        skill_content_hash=candidate.profile.skill_content_hash,
        reason="Research",
        output_contract=["research_plan"],
        status=SkillPlanNodeStatus.RUNNING,
        attempt=1,
    )
    plan = repository.save_skill_plan(
        SkillPlan(
            id="plan_universal_evidence",
            run_id=run.id,
            status=SkillPlanStatus.RUNNING,
            intent=SkillIntent(goal="Research", deliverables=["research_plan"]),
            candidate_skill_ids=[candidate.skill_id],
            candidate_snapshot=snapshot,
            execution_contract_version=AgentExecutionContractVersion.STANDARD_UNIVERSAL_V1,
            output_contract=["research_plan"],
            nodes=[node],
        )
    )
    repository.save_agent_run(run.model_copy(update={"plan_id": plan.id}))
    source = repository.add_source(
        Source(
            id="source_universal_evidence",
            title="Evidence",
            source_type="web_page",
            reference="https://example.test/evidence",
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            user_id=run.user_id,
            run_id=run.id,
            skill_id=node.skill_id,
        )
    )
    definition = ToolDefinition(
        id="tool_web_research",
        name="web_research",
        description="Research",
        category="research",
        implementation_id="provider.web.search",
        implementation_version="1",
    )

    class Gateway:
        @staticmethod
        def describe(_name):  # noqa: ANN001, ANN205
            return SimpleNamespace(execution_mode="real")

    factory = AgentMeshToolFactory(repository, gateway=Gateway())  # type: ignore[arg-type]
    context = AgentMeshRunContext(
        user_id=run.user_id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        thread_id=run.thread_id,
        run_id=run.id,
        plan_id=plan.id,
        node_id=node.id,
        skill_id=node.skill_id,
        source_ids=[source.id],
    )
    claim = RuntimeToolCallClaimV1(
        call_id="call_universal_evidence",
        run_id=run.id,
        plan_id=plan.id,
        node_id=node.id,
        tool_definition_id=definition.id,
        tool_name=definition.name,
        implementation_id=definition.implementation_id or "",
        implementation_version=definition.implementation_version,
        side_effect="read",
        operation_identity="c" * 64,
    )

    artifact_ids = factory._save_universal_tool_evidence(
        context=context,
        definition=definition,
        claim=claim,
        arguments={"query": "evidence"},
        output='{"answer":"evidence"}',
        source_ids=[source.id],
    )

    assert len(artifact_ids) == 1
    artifact = repository.get_artifact(artifact_ids[0])
    assert artifact is not None
    assert artifact.verification_state is ArtifactVerificationState.SEALED
    assert artifact.schema_version == "universal-tool-evidence-v1"
    assert artifact.requirement_version_id == "candidate_snapshot:" + snapshot.content_hash[:64]


def test_universal_finalizer_publishes_valid_subset_as_partial(tmp_path: Path) -> None:
    repository = SQLiteStore(tmp_path / "universal-partial-finalization.sqlite3")
    _skill_one, candidate_one, identity_one = _candidate(tmp_path, 1)
    _skill_two, candidate_two, identity_two = _candidate(tmp_path, 2)
    research_atom = DeliverableAtomV1(
        id="deliverable:research_plan",
        label="Research plan",
        output_kind="research_plan",
    )
    measurement_atom = DeliverableAtomV1(
        id="deliverable:measurement_plan",
        label="Measurement plan",
        output_kind="measurement_plan",
    )
    second_card = {
        **identity_two.capability_card,
        "output_kinds": ["measurement_plan"],
    }
    identity_one = identity_one.model_copy(
        update={
            "coverage_witness_scenario_id": None,
            "covered_requirement_ids": (research_atom.id,),
        }
    )
    identity_two = identity_two.model_copy(
        update={
            "coverage_witness_scenario_id": None,
            "covered_requirement_ids": (measurement_atom.id,),
            "capability_card": second_card,
            "capability_card_hash": canonical_json_sha256(second_card),
        }
    )
    snapshot_body = {
        "schema_version": "candidate-snapshot-v1",
        "retrieval_policy_version": "universal-profile-rrf-v2",
        "required_coverage_atoms": [
            research_atom.model_dump(mode="json"),
            measurement_atom.model_dump(mode="json"),
        ],
        "plannable_coverage_atom_ids": [research_atom.id, measurement_atom.id],
        "required_synthesis_output_ids": [],
        "coverage_witness_skill_ids": [identity_one.skill_id, identity_two.skill_id],
        "candidates": [
            identity_one.model_dump(mode="json"),
            identity_two.model_dump(mode="json"),
        ],
    }
    snapshot = CandidateSnapshotV1(
        **snapshot_body,
        content_hash=canonical_json_sha256(snapshot_body),
    )
    run = repository.save_agent_run(
        AgentRun(
            id="run_universal_partial_finalization",
            thread_id="thread_universal_partial_finalization",
            user_id="usr_test",
            workspace_id="ws_test",
            project_id="prj_test",
            input_text="Create plans",
            status=AgentRunStatus.RUNNING,
            planning_contract_version=AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1,
            execution_contract_version=AgentExecutionContractVersion.STANDARD_UNIVERSAL_V1,
        )
    )
    completed = SkillPlanNode(
        id="node_research_partial",
        skill_id=candidate_one.skill_id,
        skill_version=candidate_one.profile.skill_version,
        skill_content_hash=candidate_one.profile.skill_content_hash,
        reason="Delivered",
        output_contract=["research_plan"],
        status=SkillPlanNodeStatus.COMPLETED,
    )
    failed = SkillPlanNode(
        id="node_measurement_failed",
        skill_id=candidate_two.skill_id,
        skill_version=candidate_two.profile.skill_version,
        skill_content_hash=candidate_two.profile.skill_content_hash,
        reason="Failed",
        output_contract=["measurement_plan"],
        status=SkillPlanNodeStatus.FAILED,
        error_code="provider_unavailable",
    )
    plan = repository.save_skill_plan(
        SkillPlan(
            id="plan_universal_partial_finalization",
            run_id=run.id,
            status=SkillPlanStatus.RUNNING,
            intent=SkillIntent(
                goal="Create plans",
                deliverables=["research_plan", "measurement_plan"],
            ),
            candidate_skill_ids=[candidate_one.skill_id, candidate_two.skill_id],
            candidate_snapshot=snapshot,
            execution_contract_version=AgentExecutionContractVersion.STANDARD_UNIVERSAL_V1,
            output_contract=["research_plan", "measurement_plan"],
            nodes=[completed, failed],
        )
    )
    repository.save_agent_run(run.model_copy(update={"plan_id": plan.id}))
    repository.save_skill_node_result(
        plan.id,
        SkillNodeResult(
            id="result_research_partial",
            node_id=completed.id,
            skill_id=completed.skill_id,
            summary="Research plan complete",
            deliverable_markdown="# Research plan",
            delivered_output_kinds=["research_plan"],
        ),
    )

    async def synthesize(_plan, _results):  # noqa: ANN001, ANN202
        return SkillSynthesisResult(summary="Partial delivery"), False

    outcome = asyncio.run(
        StandardPlanFinalizer(repository, synthesis_runner=synthesize).finalize(
            run_id=run.id,
            plan_id=plan.id,
            expected_plan_version=plan.version,
        )
    )

    assert outcome.plan.status is SkillPlanStatus.PARTIAL
    assert outcome.run.status is AgentRunStatus.PARTIAL
    assert outcome.synthesis is not None
    assert measurement_atom.id in outcome.plan.completion_check.gaps  # type: ignore[union-attr]
