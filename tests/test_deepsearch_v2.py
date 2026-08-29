from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from agents import ModelBehaviorError
from agents.testing import ScriptedModel

from agentmesh.agent_run_identity import agent_run_create_request_hash
from agentmesh.agent_runtime import service as runtime_service
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.artifacts import ArtifactAccessScope, V1ArtifactReader
from agentmesh.canonical_json import canonical_json_sha256
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
from agentmesh.deepsearch.planning import build_deepsearch_plan_snapshot
from agentmesh.models import (
    AgentPlanningContractVersion,
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    CandidateIdentityV1,
    ChatThread,
    DeepSearchBudgetV1,
    DeliverableAtomV1,
    SkillCandidate,
    SkillCandidateScore,
    SkillDefinition,
    SkillIntent,
    SkillOrchestrationRequestMode,
    SkillPlanDraft,
    SkillPlanNode,
    SkillPlanStatus,
    SkillSourceScope,
)
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.skill_runtime.plan_validation import PlanValidationError
from agentmesh.skill_runtime.planner import PlannerUnavailable, SkillPlanner
from agentmesh.skill_runtime.profiles import load_capability_profile_record, skill_capability_card
from agentmesh.skill_runtime.recommendation import UniversalSkillSearchResult
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore
from agentmesh.task_routing.contracts import ScenarioRoute, TaskRoute, TaskRoutingResult


def _setup(tmp_path: Path):  # noqa: ANN202
    repository = SQLiteStore(tmp_path / "deepsearch-v2.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    thread = repository.add_chat_thread(
        ChatThread(
            id="thread_deepsearch_v2",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="DeepSearch v2",
        )
    )
    root = tmp_path / "deepsearch-v2-skill"
    (root / "agents").mkdir(parents=True)
    skill_path = root / "SKILL.md"
    skill_path.write_text(
        "---\nname: deepsearch-v2-skill\ndescription: Build a research plan.\n---\n",
        encoding="utf-8",
    )
    skill_hash = hashlib.sha256(skill_path.read_bytes()).hexdigest()
    skill = SkillDefinition(
        id="skill_deepsearch_v2",
        name="deepsearch-v2-skill",
        title="DeepSearch v2 Skill",
        description="Build a research plan.",
        instructions="Build a research plan.",
        source_path=str(skill_path),
        source_scope=SkillSourceScope.BUILTIN,
        content_hash=skill_hash,
        version="1",
    )
    (root / "agents" / "agentmesh.yaml").write_text(
        yaml.safe_dump(
            {
                "skill_id": "auto",
                "skill_version": "1",
                "skill_content_hash": skill_hash,
                "profile_version": "1",
                "display_description": "Build a research plan.",
                "primary_stage": "pre_design",
                "capability_type": "planning",
                "input_kinds": ["request"],
                "output_kinds": ["research_plan"],
                "examples": ["Create a research plan", "Plan research", "Research planning"],
                "negative_examples": ["Write production data", "Deploy code"],
                "required_tools": [],
                "required_resources": [],
                "owner": "@owner",
                "review_state": "approved",
                "side_effect": "draft",
                "planner_eligible": True,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    loaded = load_capability_profile_record(skill)
    repository.save_skill_definition(skill, defer_vector=True)
    repository.save_skill_capability_profile(loaded.profile, defer_vector=True)
    catalog = SkillCatalogService(repository)
    catalog._skills = {skill.name: skill}
    candidate = SkillCandidate(
        skill_id=skill.id,
        skill_name=skill.name,
        title=skill.title,
        description=skill.description,
        profile=loaded.profile,
        score=SkillCandidateScore(total=1),
        reason="profile_fts",
        match_reason_codes=["profile_fts"],
        covered_requirement_ids=["deliverable:research_plan"],
    )
    card = skill_capability_card(skill, loaded.profile)
    identity = CandidateIdentityV1(
        skill_id=skill.id,
        skill_name=skill.name,
        skill_version=skill.version,
        skill_content_hash=skill.content_hash,
        profile_version=loaded.profile.profile_version,
        profile_content_hash=loaded.profile.profile_content_hash,
        capability_card=card,
        capability_card_hash=canonical_json_sha256(card),
        match_reason_codes=("profile_fts",),
        covered_requirement_ids=("deliverable:research_plan",),
    )
    atom = DeliverableAtomV1(
        id="deliverable:research_plan",
        label="Research plan",
        output_kind="research_plan",
    )
    search_result = UniversalSkillSearchResult(
        retrieval_policy_version="universal-profile-rrf-v2",
        query_atoms=("research plan",),
        required_coverage_atoms=(atom,),
        plannable_coverage_atom_ids=(atom.id,),
        required_synthesis_output_ids=(),
        coverage_witness_skill_ids=(skill.id,),
        ranked_matches=(candidate,),
        selectable_candidates=(candidate,),
        blocked_matches=(),
        capability_gaps=(),
        outcome_code="ok",
        corpus_count=1,
        searchable_count=1,
        security_filtered_count=0,
        diagnostics=(),
    )
    return repository, catalog, thread, skill, candidate, identity, search_result


def test_deepsearch_v2_preserves_stable_planning_error_codes() -> None:
    assert AgentRuntimeService._deepsearch_planning_error_code(
        PlanValidationError(["no_matching_skill"])
    ) == "no_matching_skill"
    assert AgentRuntimeService._deepsearch_planning_error_code(
        PlannerUnavailable("planner_context_budget_exceeded")
    ) == "planner_context_budget_exceeded"
    assert AgentRuntimeService._deepsearch_planning_error_code(
        PlanValidationError(["planner_schema_invalid"])
    ) == "planner_schema_invalid"
    assert AgentRuntimeService._deepsearch_planning_error_code(
        PlanValidationError(["internal_unknown"])
    ) == "deepsearch_planning_failed"


def test_deepsearch_v2_persists_snapshot_before_planner_and_publishes_v2_artifact(
    tmp_path,
    monkeypatch,
) -> None:
    repository, catalog, thread, skill, candidate, _identity, search_result = _setup(tmp_path)
    created_at = datetime(2026, 8, 29, 9, 0, tzinfo=UTC)
    payload = RequirementPayloadV1(
        goal="Create a research plan",
        scope=RequirementScopeV1(),
        success_criteria=[
            RequirementSuccessCriterionV1(
                id="criterion_plan",
                statement="Provide a usable plan",
            )
        ],
        deliverables=["Research plan"],
        ambiguities=[],
        clarification_questions=[],
    )
    run_request_hash = agent_run_create_request_hash(
        user_id=USER.id,
        thread_id=thread.id,
        client_turn_id="turn_deepsearch_v2",
        content=payload.goal,
        skill_name=None,
        orchestration_mode=SkillOrchestrationRequestMode.AUTO,
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        retry_of_run_id=None,
        planning_contract_version=AgentPlanningContractVersion.DEEPSEARCH_FROZEN_V2,
    )
    run = repository.save_agent_run(
        AgentRun(
            id="run_deepsearch_v2",
            thread_id=thread.id,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text=payload.goal,
            client_turn_id="turn_deepsearch_v2",
            status=AgentRunStatus.PLANNING,
            planning_mode=AgentPlanningMode.DEEPSEARCH,
            planning_contract_version=AgentPlanningContractVersion.DEEPSEARCH_FROZEN_V2,
            orchestration_mode="execute",
            requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
            create_request_hash=run_request_hash,
            absolute_expires_at=created_at + timedelta(days=7),
            deepsearch_budget=DeepSearchBudgetV1(),
            created_at=created_at,
            updated_at=created_at,
        )
    )
    assert run.create_request_hash is not None
    requirement = RequirementVersionV1(
        id="requirement_deepsearch_v2",
        run_id=run.id,
        version=1,
        request_key=run.client_turn_id or "",
        request_hash=run.create_request_hash,
        content_hash=requirement_content_hash(payload),
        payload=payload,
        created_at=created_at,
    )
    committed = repository.append_deepsearch_requirement_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        requirement=requirement.model_dump(mode="json"),
        expected_requirement_version=None,
        expected_run_status=AgentRunStatus.PLANNING,
        next_run_status=AgentRunStatus.PLANNING,
        interaction_expires_at=None,
        error_code=None,
        events=[],
        checked_at=created_at,
    )
    assert committed is not None
    question = ProblemQuestionV1(
        id=problem_question_id("What should the research plan contain?"),
        question="What should the research plan contain?",
        required=True,
        success_criterion_ids=["criterion_plan"],
        evidence_requirements=["Current approved product context"],
        acceptance_criteria=["Provide a usable plan"],
    )
    graph = build_problem_graph(requirement=requirement, questions=[question])

    class IntentAnalyzer:
        async def analyze(self, *_args, **_kwargs):
            return SkillIntent(goal=payload.goal, deliverables=["research_plan"]), []

    class Router:
        @staticmethod
        def route(*_args, **_kwargs):
            v1 = runtime_service.load_default_task_catalog()
            return (
                TaskRoutingResult(
                    catalog_version=v1.manifest.catalog_version,
                    catalog_hash=v1.manifest.catalog_hash,
                    task=TaskRoute(task_id="define-strategy", confidence="high"),
                    scenario=ScenarioRoute(
                        scenario_id="metrics-validation",
                        confidence="high",
                    ),
                ),
                ["deterministic_task_router"],
            )

    search_calls: list[str] = []

    class Search:
        @staticmethod
        def search(**_kwargs):
            search_calls.append("search")
            return search_result

    draft_calls: list[list[str]] = []

    async def draft_factory(_intent, _candidates):  # noqa: ANN001
        persisted = repository.get_skill_plan_for_run(run.id)
        assert persisted is not None
        assert persisted.status.value == "planning"
        assert persisted.candidate_snapshot is not None
        draft_calls.append([candidate.skill_id for candidate in _candidates])
        if len(draft_calls) == 1:
            raise ModelBehaviorError("invalid structured output")
        return SkillPlanDraft(
            output_contract=["research_plan"],
            nodes=[
                SkillPlanNode(
                    id="node_deepsearch_v2",
                    skill_id=skill.id,
                    skill_version=skill.version,
                    skill_content_hash=skill.content_hash,
                    reason="Build the plan",
                    input_bindings=["user.request"],
                    output_contract=["research_plan"],
                    side_effect="draft",
                )
            ],
        )

    async def fake_graph(self, **_kwargs):  # noqa: ANN001
        return graph

    monkeypatch.setattr(runtime_service._ModelProblemGraphPlanner, "build", fake_graph)

    class Trust:
        available = True

        def __call__(self, _skill, _loaded):  # noqa: ANN001, ANN204
            return True

    runtime = AgentRuntimeService(
        repository,
        model=ScriptedModel([]),
        enabled=True,
        skill_catalog=catalog,
        intent_analyzer=IntentAnalyzer(),  # type: ignore[arg-type]
        skill_planner=SkillPlanner(draft_factory=draft_factory),
        task_router=Router(),  # type: ignore[arg-type]
        profile_trust=Trust(),  # type: ignore[arg-type]
        universal_search=Search(),  # type: ignore[arg-type]
        universal_preview_enabled=True,
    )
    selected = runtime.select_model(USER)
    assert selected is not None
    assert runtime.planning_contract_for(
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        planned=True,
    ) is AgentPlanningContractVersion.DEEPSEARCH_FROZEN_V2

    plan, artifact = asyncio.run(
        runtime._create_universal_deepsearch_plan(
            run=run,
            requirement=requirement,
            user=USER,
            selected=selected,
            created_at=created_at,
        )
    )

    assert repository.get_skill_plan(plan.id).status.value == "planning"  # type: ignore[union-attr]
    assert plan.candidate_snapshot is not None
    assert artifact.schema_version == "deepsearch-plan-snapshot-v2"
    resumed_run = repository.get_agent_run(run.id)
    assert resumed_run is not None and resumed_run.plan_id == plan.id
    skeleton_state = runtime.deepsearch_planning_service.get_state(resumed_run)
    assert skeleton_state.plan is None
    assert skeleton_state.problem_graph == graph
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "execute")
    recovered = asyncio.run(runtime.recover_deepsearch_run(run.id))
    assert recovered is not None
    assert search_calls == ["search"]
    assert len(draft_calls) == 3
    persisted_plan = repository.get_skill_plan_for_run(run.id)
    persisted_artifact = repository.get_artifact(artifact.id)
    assert persisted_plan is not None and persisted_artifact is not None
    assert recovered.status is AgentRunStatus.WAITING_PLAN_APPROVAL
    assert recovered.deepsearch_budget is not None
    assert len(
        [
            item
            for item in recovered.deepsearch_budget.reservations
            if item.actual_usage is not None and item.actual_usage.artifact_bytes > 0
        ]
    ) == 1
    assert persisted_plan.candidate_snapshot == plan.candidate_snapshot
    assert persisted_artifact.schema_version == "deepsearch-plan-snapshot-v2"
    verified = V1ArtifactReader(repository).read_for_owner(
        persisted_artifact.id,
        reader_scope=ArtifactAccessScope(
            user_id=run.user_id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            run_id=run.id,
        ),
    )
    assert verified == persisted_artifact
    public_state = runtime.deepsearch_planning_service.get_state(recovered)
    assert public_state.plan is not None
    assert public_state.plan.candidate_snapshot is not None
    assert "profile_content_hash" not in public_state.plan.model_dump_json()

    approved = persisted_plan.model_copy(
        update={
            "status": SkillPlanStatus.APPROVED,
            "version": persisted_plan.version + 1,
        }
    )
    approved_snapshot = build_deepsearch_plan_snapshot(
        run=recovered,
        plan=approved,
        created_at=persisted_artifact.created_at,
    )
    approved.approved_plan_artifact_id = approved_snapshot.id
    approved_transition = repository.approve_deepsearch_plan_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        expected_plan_version=persisted_plan.version,
        plan=approved,
        plan_snapshot=approved_snapshot,
        checked_at=persisted_artifact.created_at,
    )
    assert approved_transition is not None
    approved_plan, approved_run, approved_artifact = approved_transition
    assert approved_run.status is AgentRunStatus.RUNNING
    assert approved_run.deepsearch_budget is not None
    assert len(
        [
            item
            for item in approved_run.deepsearch_budget.reservations
            if item.actual_usage is not None and item.actual_usage.artifact_bytes > 0
        ]
    ) == 2
    assert approved_plan.candidate_snapshot == plan.candidate_snapshot
    assert approved_artifact.schema_version == "deepsearch-plan-snapshot-v2"
