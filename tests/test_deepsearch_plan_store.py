from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from agentmesh.artifacts import (
    ArtifactAccessError,
    DeepSearchPlanSnapshotV1,
    V1VerifiedArtifactStore,
)
from agentmesh.canonical_json import canonical_json_bytes
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
from agentmesh.deepsearch.planning import build_deepsearch_plan_snapshot, plan_content_hash
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    AgentToolGrant,
    Artifact,
    ChatThread,
    DeepSearchBudgetUsageV1,
    DeepSearchBudgetV1,
    Project,
    SkillCapabilityProfile,
    SkillCapabilityType,
    SkillDefinition,
    SkillIntent,
    SkillLifecycleStage,
    SkillOrchestrationRequestMode,
    SkillPlan,
    SkillPlanNode,
    SkillPlanStatus,
    SkillSideEffect,
    SkillSourceScope,
    ToolDefinition,
    User,
)
from agentmesh.skill_runtime.resources import build_skill_resource_manifest_snapshot
from agentmesh.store import ResearchStoreConflict, SQLiteStore

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def _run(run_id: str) -> AgentRun:
    return AgentRun(
        id=run_id,
        thread_id=f"thread_{run_id}",
        user_id="user_deepsearch_plan",
        workspace_id="workspace_deepsearch_plan",
        project_id="project_deepsearch_plan",
        input_text="Evaluate the collaboration software market",
        client_turn_id=f"turn_{run_id}",
        status=AgentRunStatus.PLANNING,
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
        orchestration_version="v1",
        orchestration_mode="execute",
        deadline_at=None,
        absolute_expires_at=NOW + timedelta(days=7),
        deepsearch_budget=DeepSearchBudgetV1(),
        created_at=NOW,
        updated_at=NOW,
    )


def _complete_requirement(run: AgentRun) -> RequirementVersionV1:
    assert run.client_turn_id is not None
    assert run.create_request_hash is not None
    payload = RequirementPayloadV1(
        goal="Evaluate the collaboration software market",
        scope=RequirementScopeV1(regions=["China"]),
        success_criteria=[
            RequirementSuccessCriterionV1(
                id="criterion_market",
                statement="Quantify the market",
            )
        ],
        deliverables=["Research report"],
    )
    return RequirementVersionV1(
        id=f"requirement_{run.id}_v1",
        run_id=run.id,
        version=1,
        request_key=run.client_turn_id,
        request_hash=run.create_request_hash,
        content_hash=requirement_content_hash(payload),
        payload=payload,
        created_at=NOW,
    )


def _plan_and_snapshot(
    repository: SQLiteStore,
    run: AgentRun,
    requirement: RequirementVersionV1,
) -> tuple[SkillPlan, Artifact]:
    skill = repository.get_skill_definition("skill_market_research")
    profile = repository.get_skill_capability_profile("skill_market_research")
    assert skill is not None and profile is not None
    question = ProblemQuestionV1(
        id=problem_question_id("What is the market size?"),
        question="What is the market size?",
        required=True,
        success_criterion_ids=["criterion_market"],
        evidence_requirements=["Public market data"],
        acceptance_criteria=["State a sourced estimate"],
    )
    graph = build_problem_graph(requirement=requirement, questions=[question])
    plan = SkillPlan(
        id=f"plan_{run.id}",
        run_id=run.id,
        version=1,
        status=SkillPlanStatus.WAITING_APPROVAL,
        intent=SkillIntent(goal=requirement.payload.goal),
        candidate_skill_ids=["skill_market_research"],
        nodes=[
            SkillPlanNode(
                id="node_market",
                skill_id="skill_market_research",
                skill_version="1",
                skill_content_hash="a" * 64,
                reason="Answer the required market question",
                question_ids=[question.id],
                required_tool_names=["web_research"],
                resource_manifest=build_skill_resource_manifest_snapshot(skill, profile),
            )
        ],
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        requirement_version_id=requirement.id,
        requirement_content_hash=requirement.content_hash,
        problem_graph=graph.model_dump(mode="json"),
        problem_graph_hash=graph.content_hash,
        created_at=NOW,
        updated_at=NOW,
    )
    plan.plan_content_hash = plan_content_hash(plan)
    return plan, _snapshot_for_plan(run, requirement, plan)


def _snapshot_for_plan(
    run: AgentRun,
    requirement: RequirementVersionV1,
    plan: SkillPlan,
) -> Artifact:
    assert plan.requirement_version_id == requirement.id
    return build_deepsearch_plan_snapshot(run=run, plan=plan, created_at=NOW)


def _assert_plan_not_committed(
    repository: SQLiteStore,
    *,
    run_id: str,
    plan_id: str,
    snapshot_id: str,
    events_before: list,
) -> None:
    persisted_run = repository.get_agent_run(run_id)
    assert persisted_run is not None
    assert persisted_run.status is AgentRunStatus.PLANNING
    assert persisted_run.plan_id is None
    assert persisted_run.deepsearch_budget == DeepSearchBudgetV1()
    assert repository.get_skill_plan(plan_id) is None
    assert repository.get_artifact(snapshot_id) is None
    assert repository.list_agent_run_events(run_id) == events_before


def _seed_plan_skill(repository: SQLiteStore) -> None:
    skill_path = repository.db_path.parent / "skills" / "market-research" / "SKILL.md"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text("test skill", encoding="utf-8")
    repository.save_skill_definition(
        SkillDefinition(
            id="skill_market_research",
            name="market-research",
            title="Market research",
            description="Research a market",
            instructions="Use trustworthy sources.",
            source_path=str(skill_path),
            source_scope=SkillSourceScope.BUILTIN,
            content_hash="a" * 64,
            version="1",
        ),
        defer_vector=True,
    )
    repository.save_skill_capability_profile(
        SkillCapabilityProfile(
            id="skill_market_research",
            skill_id="skill_market_research",
            skill_name="market-research",
            skill_version="1",
            skill_content_hash="a" * 64,
            profile_version="1",
            profile_content_hash="c" * 64,
            primary_stage=SkillLifecycleStage.PRE_DESIGN,
            capability_type=SkillCapabilityType.RESEARCH,
            required_tools=["web_research"],
        ),
        defer_vector=True,
    )
    repository.save_tool_definition(
        ToolDefinition(
            id="tool_web_research",
            name="web_research",
            external_name="web_research",
            description="Read public web sources",
            category="research",
            side_effect="read",
        )
    )
    repository.save_user(
        User(
            id="user_deepsearch_plan",
            workspace_id="workspace_deepsearch_plan",
            default_project_id="project_deepsearch_plan",
            name="DeepSearch planner",
            role="user",
            personal_agent_id="agent_deepsearch_plan",
        )
    )
    repository.save_agent_tool_grant(
        AgentToolGrant(
            agent_id="agent_deepsearch_plan",
            tool_id="tool_web_research",
            granted_by="user_deepsearch_plan",
        )
    )


def _prepare_planning_run(repository: SQLiteStore, run_id: str) -> tuple[AgentRun, RequirementVersionV1]:
    _seed_plan_skill(repository)
    repository.save_project(
        Project(
            id="project_deepsearch_plan",
            workspace_id="workspace_deepsearch_plan",
            name="DeepSearch project",
            goal="Research",
            member_ids=["user_deepsearch_plan"],
        )
    )
    repository.add_chat_thread(
        ChatThread(
            id=f"thread_{run_id}",
            workspace_id="workspace_deepsearch_plan",
            project_id="project_deepsearch_plan",
            user_id="user_deepsearch_plan",
            title="DeepSearch plan",
        )
    )
    run, _created = repository.claim_new_agent_run(_run(run_id))
    requirement = _complete_requirement(run)
    repository.append_deepsearch_requirement_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        requirement=requirement.model_dump(mode="json"),
        expected_requirement_version=None,
        expected_run_status=AgentRunStatus.PLANNING,
        next_run_status=AgentRunStatus.PLANNING,
        events=[
            (
                "deepsearch_requirement_created",
                {
                    "requirement_version_id": requirement.id,
                    "requirement_version": requirement.version,
                    "content_hash": requirement.content_hash,
                },
            )
        ],
        checked_at=NOW,
    )
    return run, requirement


def test_initial_plan_commit_atomically_persists_plan_snapshot_run_and_events(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-commit.sqlite3")
    run, requirement = _prepare_planning_run(repository, "run_plan_commit")
    plan, snapshot = _plan_and_snapshot(repository, run, requirement)
    committed_at = NOW + timedelta(minutes=1)

    result = repository.save_deepsearch_plan_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        expected_requirement_version=requirement.version,
        plan=plan,
        plan_snapshot=snapshot,
        checked_at=committed_at,
    )

    assert result is not None
    saved_plan, saved_run, saved_snapshot = result
    assert saved_plan == repository.get_skill_plan(plan.id)
    assert saved_snapshot == repository.get_artifact(snapshot.id)
    assert saved_run.plan_id == plan.id
    assert saved_run.status is AgentRunStatus.WAITING_PLAN_APPROVAL
    assert saved_run.deadline_at is None
    assert saved_run.interaction_expires_at == committed_at + timedelta(hours=24)
    assert saved_run.deepsearch_budget is not None
    expected_usage = DeepSearchBudgetUsageV1(artifact_bytes=snapshot.size_bytes or 0)
    assert saved_run.deepsearch_budget.consumed == expected_usage
    assert saved_run.deepsearch_budget.reservations[-1].resource_maxima == expected_usage
    assert saved_run.deepsearch_budget.reservations[-1].actual_usage == expected_usage
    assert [event.event_type for event in repository.list_agent_run_events(run.id)][-2:] == [
        "deepsearch_problem_graph_created",
        "deepsearch_plan_ready",
    ]


def test_initial_plan_commit_rejects_a_mismatched_snapshot_without_partial_writes(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-snapshot-mismatch.sqlite3")
    run, requirement = _prepare_planning_run(repository, "run_plan_snapshot_mismatch")
    plan, snapshot = _plan_and_snapshot(repository, run, requirement)
    payload = DeepSearchPlanSnapshotV1.model_validate_json(snapshot.content).model_copy(
        update={"plan_content_hash": "f" * 64}
    )
    content = canonical_json_bytes(payload.model_dump(mode="python")).decode("utf-8")
    snapshot = snapshot.model_copy(
        update={
            "content": content,
            "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "size_bytes": len(content.encode("utf-8")),
        }
    )
    events_before = repository.list_agent_run_events(run.id)

    with pytest.raises(ResearchStoreConflict, match="snapshot"):
        repository.save_deepsearch_plan_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            expected_requirement_version=requirement.version,
            plan=plan,
            plan_snapshot=snapshot,
            checked_at=NOW + timedelta(minutes=1),
        )

    _assert_plan_not_committed(
        repository,
        run_id=run.id,
        plan_id=plan.id,
        snapshot_id=snapshot.id,
        events_before=events_before,
    )


def test_initial_plan_snapshot_insert_failure_rolls_back_budget_and_plan(
    tmp_path,
    monkeypatch,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-snapshot-write-failure.sqlite3")
    run, requirement = _prepare_planning_run(repository, "run_plan_snapshot_write_failure")
    plan, snapshot = _plan_and_snapshot(repository, run, requirement)
    events_before = repository.list_agent_run_events(run.id)

    def fail_insert(_store, _artifact, *, connection=None):  # noqa: ANN001, ANN202
        assert connection is not None
        raise ArtifactAccessError("artifact_write_failed")

    monkeypatch.setattr(V1VerifiedArtifactStore, "insert_sealed", fail_insert)

    with pytest.raises(ResearchStoreConflict, match="snapshot"):
        repository.save_deepsearch_plan_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            expected_requirement_version=requirement.version,
            plan=plan,
            plan_snapshot=snapshot,
            checked_at=NOW + timedelta(minutes=1),
        )

    _assert_plan_not_committed(
        repository,
        run_id=run.id,
        plan_id=plan.id,
        snapshot_id=snapshot.id,
        events_before=events_before,
    )


def test_initial_plan_commit_rejects_a_nondeterministic_snapshot_id(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-snapshot-id.sqlite3")
    run, requirement = _prepare_planning_run(repository, "run_plan_snapshot_id")
    plan, snapshot = _plan_and_snapshot(repository, run, requirement)
    forged = snapshot.model_copy(update={"id": "artifact_caller_selected"})
    events_before = repository.list_agent_run_events(run.id)

    with pytest.raises(ResearchStoreConflict, match="snapshot"):
        repository.save_deepsearch_plan_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            expected_requirement_version=requirement.version,
            plan=plan,
            plan_snapshot=forged,
            checked_at=NOW + timedelta(minutes=1),
        )

    _assert_plan_not_committed(
        repository,
        run_id=run.id,
        plan_id=plan.id,
        snapshot_id=forged.id,
        events_before=events_before,
    )


def test_initial_plan_commit_rejects_a_stale_requirement_version_without_partial_writes(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-stale-requirement.sqlite3")
    run, requirement = _prepare_planning_run(repository, "run_plan_stale_requirement")
    plan, snapshot = _plan_and_snapshot(repository, run, requirement)
    events_before = repository.list_agent_run_events(run.id)

    with pytest.raises(ResearchStoreConflict, match="version_conflict"):
        repository.save_deepsearch_plan_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            expected_requirement_version=requirement.version + 1,
            plan=plan,
            plan_snapshot=snapshot,
            checked_at=NOW + timedelta(minutes=1),
        )

    _assert_plan_not_committed(
        repository,
        run_id=run.id,
        plan_id=plan.id,
        snapshot_id=snapshot.id,
        events_before=events_before,
    )


def test_initial_plan_commit_hides_another_users_run_without_partial_writes(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-owner.sqlite3")
    run, requirement = _prepare_planning_run(repository, "run_plan_owner")
    plan, snapshot = _plan_and_snapshot(repository, run, requirement)
    events_before = repository.list_agent_run_events(run.id)

    result = repository.save_deepsearch_plan_and_transition(
        run_id=run.id,
        user_id="user_intruder",
        expected_requirement_version=requirement.version,
        plan=plan,
        plan_snapshot=snapshot,
        checked_at=NOW + timedelta(minutes=1),
    )

    assert result is None
    _assert_plan_not_committed(
        repository,
        run_id=run.id,
        plan_id=plan.id,
        snapshot_id=snapshot.id,
        events_before=events_before,
    )


def test_initial_plan_commit_does_not_replace_an_existing_plan(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-existing.sqlite3")
    run, requirement = _prepare_planning_run(repository, "run_plan_existing")
    first_plan, first_snapshot = _plan_and_snapshot(repository, run, requirement)
    first_result = repository.save_deepsearch_plan_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        expected_requirement_version=requirement.version,
        plan=first_plan,
        plan_snapshot=first_snapshot,
        checked_at=NOW + timedelta(minutes=1),
    )
    assert first_result is not None
    second_plan = first_plan.model_copy(update={"id": "plan_replacement"}, deep=True)
    second_snapshot = _snapshot_for_plan(run, requirement, second_plan)
    events_before = repository.list_agent_run_events(run.id)

    with pytest.raises(ResearchStoreConflict, match="initial Plan state"):
        repository.save_deepsearch_plan_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            expected_requirement_version=requirement.version,
            plan=second_plan,
            plan_snapshot=second_snapshot,
            checked_at=NOW + timedelta(minutes=2),
        )

    persisted_run = repository.get_agent_run(run.id)
    assert persisted_run is not None
    assert persisted_run.plan_id == first_plan.id
    assert persisted_run.status is AgentRunStatus.WAITING_PLAN_APPROVAL
    assert repository.get_skill_plan(first_plan.id) is not None
    assert repository.get_skill_plan(second_plan.id) is None
    assert repository.get_artifact(first_snapshot.id) is not None
    assert repository.get_artifact(second_snapshot.id) is None
    assert repository.list_agent_run_events(run.id) == events_before


def test_initial_plan_commit_rejects_a_self_consistent_but_forged_graph_hash(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-graph-hash.sqlite3")
    run, requirement = _prepare_planning_run(repository, "run_plan_graph_hash")
    plan, _snapshot = _plan_and_snapshot(repository, run, requirement)
    plan.problem_graph_hash = "d" * 64
    plan.plan_content_hash = plan_content_hash(plan)
    snapshot = _snapshot_for_plan(run, requirement, plan)
    events_before = repository.list_agent_run_events(run.id)

    with pytest.raises(ResearchStoreConflict, match="integrity"):
        repository.save_deepsearch_plan_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            expected_requirement_version=requirement.version,
            plan=plan,
            plan_snapshot=snapshot,
            checked_at=NOW + timedelta(minutes=1),
        )

    _assert_plan_not_committed(
        repository,
        run_id=run.id,
        plan_id=plan.id,
        snapshot_id=snapshot.id,
        events_before=events_before,
    )


def test_initial_plan_commit_rejects_a_write_side_effect_node_without_partial_writes(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-write-node.sqlite3")
    run, requirement = _prepare_planning_run(repository, "run_plan_write_node")
    plan, _snapshot = _plan_and_snapshot(repository, run, requirement)
    plan.nodes[0].side_effect = SkillSideEffect.LOCAL_WRITE
    plan.plan_content_hash = plan_content_hash(plan)
    snapshot = _snapshot_for_plan(run, requirement, plan)
    events_before = repository.list_agent_run_events(run.id)

    with pytest.raises(ResearchStoreConflict, match="integrity"):
        repository.save_deepsearch_plan_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            expected_requirement_version=requirement.version,
            plan=plan,
            plan_snapshot=snapshot,
            checked_at=NOW + timedelta(minutes=1),
        )

    _assert_plan_not_committed(
        repository,
        run_id=run.id,
        plan_id=plan.id,
        snapshot_id=snapshot.id,
        events_before=events_before,
    )


def test_initial_plan_commit_rejects_a_cyclic_dag_without_partial_writes(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-cycle.sqlite3")
    run, requirement = _prepare_planning_run(repository, "run_plan_cycle")
    plan, _snapshot = _plan_and_snapshot(repository, run, requirement)
    plan.nodes[0].depends_on = [plan.nodes[0].id]
    plan.plan_content_hash = plan_content_hash(plan)
    snapshot = _snapshot_for_plan(run, requirement, plan)
    events_before = repository.list_agent_run_events(run.id)

    with pytest.raises(ResearchStoreConflict, match="integrity"):
        repository.save_deepsearch_plan_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            expected_requirement_version=requirement.version,
            plan=plan,
            plan_snapshot=snapshot,
            checked_at=NOW + timedelta(minutes=1),
        )

    _assert_plan_not_committed(
        repository,
        run_id=run.id,
        plan_id=plan.id,
        snapshot_id=snapshot.id,
        events_before=events_before,
    )


@pytest.mark.parametrize(
    "case",
    [
        "unknown_dependency",
        "missing_required_coverage",
        "unsupported_output",
        "unsupported_input",
        "required_tool_mismatch",
    ],
)
def test_initial_plan_commit_revalidates_the_frozen_plan_structure(case: str, tmp_path) -> None:
    repository = SQLiteStore(tmp_path / f"deepsearch-plan-{case}.sqlite3")
    run, requirement = _prepare_planning_run(repository, f"run_plan_{case}")
    plan, _snapshot = _plan_and_snapshot(repository, run, requirement)
    if case == "unknown_dependency":
        plan.nodes[0].depends_on = ["node_missing"]
    elif case == "missing_required_coverage":
        plan.nodes[0].question_ids = []
    elif case == "unsupported_output":
        plan.nodes[0].output_contract = ["unsupported_output"]
    elif case == "unsupported_input":
        plan.nodes[0].input_bindings = ["user.unsupported_input"]
    else:
        plan.nodes[0].required_tool_names = []
    plan.plan_content_hash = plan_content_hash(plan)
    snapshot = _snapshot_for_plan(run, requirement, plan)
    events_before = repository.list_agent_run_events(run.id)

    with pytest.raises(ResearchStoreConflict, match="integrity"):
        repository.save_deepsearch_plan_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            expected_requirement_version=requirement.version,
            plan=plan,
            plan_snapshot=snapshot,
            checked_at=NOW + timedelta(minutes=1),
        )

    _assert_plan_not_committed(
        repository,
        run_id=run.id,
        plan_id=plan.id,
        snapshot_id=snapshot.id,
        events_before=events_before,
    )


def test_initial_plan_commit_rejects_a_stale_skill_hash_without_partial_writes(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-stale-skill.sqlite3")
    run, requirement = _prepare_planning_run(repository, "run_plan_stale_skill")
    plan, snapshot = _plan_and_snapshot(repository, run, requirement)
    current_skill = repository.get_skill_definition(plan.nodes[0].skill_id)
    assert current_skill is not None
    repository.save_skill_definition(
        current_skill.model_copy(update={"content_hash": "b" * 64}),
        defer_vector=True,
    )
    events_before = repository.list_agent_run_events(run.id)

    with pytest.raises(ResearchStoreConflict, match="integrity"):
        repository.save_deepsearch_plan_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            expected_requirement_version=requirement.version,
            plan=plan,
            plan_snapshot=snapshot,
            checked_at=NOW + timedelta(minutes=1),
        )

    _assert_plan_not_committed(
        repository,
        run_id=run.id,
        plan_id=plan.id,
        snapshot_id=snapshot.id,
        events_before=events_before,
    )


def test_initial_plan_commit_rejects_a_write_tool_without_partial_writes(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-write-tool.sqlite3")
    run, requirement = _prepare_planning_run(repository, "run_plan_write_tool")
    plan, snapshot = _plan_and_snapshot(repository, run, requirement)
    tool = repository.get_tool_definition("tool_web_research")
    assert tool is not None
    repository.save_tool_definition(tool.model_copy(update={"side_effect": "write"}))
    events_before = repository.list_agent_run_events(run.id)

    with pytest.raises(ResearchStoreConflict, match="integrity"):
        repository.save_deepsearch_plan_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            expected_requirement_version=requirement.version,
            plan=plan,
            plan_snapshot=snapshot,
            checked_at=NOW + timedelta(minutes=1),
        )

    _assert_plan_not_committed(
        repository,
        run_id=run.id,
        plan_id=plan.id,
        snapshot_id=snapshot.id,
        events_before=events_before,
    )
