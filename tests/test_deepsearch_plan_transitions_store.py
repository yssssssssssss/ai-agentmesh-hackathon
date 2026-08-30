from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

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
    SkillBinding,
    SkillCapabilityProfile,
    SkillCapabilityType,
    SkillDefinition,
    SkillIntent,
    SkillLifecycleStage,
    SkillOrchestrationRequestMode,
    SkillPlan,
    SkillPlanNode,
    SkillPlanStatus,
    SkillSourceScope,
    ToolDefinition,
    User,
)
from agentmesh.skill_runtime.resources import build_skill_resource_manifest_snapshot
from agentmesh.store import DeepSearchRequirementConflict, ResearchStoreConflict, SQLiteStore

NOW = datetime(2026, 8, 26, 14, 0, tzinfo=UTC)


def _run(run_id: str) -> AgentRun:
    return AgentRun(
        id=run_id,
        thread_id=f"thread_{run_id}",
        user_id="user_deepsearch_transition",
        workspace_id="workspace_deepsearch_transition",
        project_id="project_deepsearch_transition",
        input_text="Compare collaboration platforms",
        client_turn_id=f"turn_{run_id}",
        status=AgentRunStatus.PLANNING,
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
        orchestration_version="v1",
        orchestration_mode="execute",
        absolute_expires_at=NOW + timedelta(days=7),
        deepsearch_budget=DeepSearchBudgetV1(),
        created_at=NOW,
        updated_at=NOW,
    )


def _requirement(run: AgentRun) -> RequirementVersionV1:
    assert run.client_turn_id is not None
    assert run.create_request_hash is not None
    payload = RequirementPayloadV1(
        goal="Compare collaboration platforms",
        scope=RequirementScopeV1(regions=["China"]),
        success_criteria=[
            RequirementSuccessCriterionV1(
                id="criterion_comparison",
                statement="Compare the leading platforms",
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


def _seed_skill(repository: SQLiteStore, *, skill_id: str, name: str, content_hash: str) -> None:
    skill_path = repository.db_path.parent / "skills" / name / "SKILL.md"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text("test skill", encoding="utf-8")
    repository.save_skill_definition(
        SkillDefinition(
            id=skill_id,
            name=name,
            title=name.replace("-", " ").title(),
            description=f"Execute {name}",
            instructions="Use trustworthy sources.",
            source_path=str(skill_path),
            source_scope=SkillSourceScope.BUILTIN,
            content_hash=content_hash,
            version="1",
        ),
        defer_vector=True,
    )
    repository.save_skill_capability_profile(
        SkillCapabilityProfile(
            id=skill_id,
            skill_id=skill_id,
            skill_name=name,
            skill_version="1",
            skill_content_hash=content_hash,
            profile_version="1",
            profile_content_hash=content_hash,
            primary_stage=SkillLifecycleStage.PRE_DESIGN,
            capability_type=SkillCapabilityType.RESEARCH,
            required_tools=["web_research"],
        ),
        defer_vector=True,
    )


def _prepare_waiting_plan(
    repository: SQLiteStore,
    run_id: str,
    *,
    capability_gaps: list[str] | None = None,
) -> tuple[AgentRun, RequirementVersionV1, SkillPlan, str]:
    repository.save_user(
        User(
            id="user_deepsearch_transition",
            workspace_id="workspace_deepsearch_transition",
            default_project_id="project_deepsearch_transition",
            name="DeepSearch user",
            role="user",
            personal_agent_id="agent_deepsearch_transition",
        )
    )
    repository.save_project(
        Project(
            id="project_deepsearch_transition",
            workspace_id="workspace_deepsearch_transition",
            name="DeepSearch transition project",
            goal="Test DeepSearch Plan transitions",
            member_ids=["user_deepsearch_transition"],
        )
    )
    repository.add_chat_thread(
        ChatThread(
            id=f"thread_{run_id}",
            workspace_id="workspace_deepsearch_transition",
            project_id="project_deepsearch_transition",
            user_id="user_deepsearch_transition",
            title="DeepSearch Plan transition",
        )
    )
    repository.save_tool_definition(
        ToolDefinition(
            id="tool_web_research",
            name="web_research",
            external_name="web_research",
            description="Read public sources",
            category="research",
            side_effect="read",
        )
    )
    repository.save_agent_tool_grant(
        AgentToolGrant(
            agent_id="agent_deepsearch_transition",
            tool_id="tool_web_research",
            granted_by="user_deepsearch_transition",
        )
    )
    _seed_skill(repository, skill_id="skill_primary", name="primary-research", content_hash="a" * 64)
    _seed_skill(repository, skill_id="skill_optional", name="optional-analysis", content_hash="b" * 64)

    run, _created = repository.claim_new_agent_run(_run(run_id))
    requirement = _requirement(run)
    repository.append_deepsearch_requirement_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        requirement=requirement.model_dump(mode="json"),
        expected_requirement_version=None,
        expected_run_status=AgentRunStatus.PLANNING,
        next_run_status=AgentRunStatus.PLANNING,
        events=[],
        checked_at=NOW,
    )
    question = ProblemQuestionV1(
        id=problem_question_id("Which platforms lead the market?"),
        question="Which platforms lead the market?",
        required=True,
        success_criterion_ids=["criterion_comparison"],
        evidence_requirements=["Public market evidence"],
        acceptance_criteria=["Name and compare leading platforms"],
    )
    graph = build_problem_graph(requirement=requirement, questions=[question])
    primary_skill = repository.get_skill_definition("skill_primary")
    primary_profile = repository.get_skill_capability_profile("skill_primary")
    assert primary_skill is not None and primary_profile is not None
    plan = SkillPlan(
        id=f"plan_{run.id}",
        run_id=run.id,
        version=1,
        status=SkillPlanStatus.WAITING_APPROVAL,
        intent=SkillIntent(goal=requirement.payload.goal),
        candidate_skill_ids=["skill_primary", "skill_optional"],
        capability_gaps=capability_gaps or [],
        preferred_order=["skill_primary"],
        nodes=[
            SkillPlanNode(
                id="node_primary",
                skill_id="skill_primary",
                skill_version="1",
                skill_content_hash="a" * 64,
                reason="Answer the required comparison question",
                question_ids=[question.id],
                required_tool_names=["web_research"],
                resource_manifest=build_skill_resource_manifest_snapshot(
                    primary_skill,
                    primary_profile,
                ),
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
    snapshot = build_deepsearch_plan_snapshot(run=run, plan=plan, created_at=NOW)
    committed = repository.save_deepsearch_plan_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        expected_requirement_version=requirement.version,
        plan=plan,
        plan_snapshot=snapshot,
        checked_at=NOW,
    )
    assert committed is not None
    saved_plan, saved_run, saved_snapshot = committed
    return saved_run, requirement, saved_plan, saved_snapshot.id


def _edited_plan(
    repository: SQLiteStore,
    run: AgentRun,
    requirement: RequirementVersionV1,
    current: SkillPlan,
    *,
    created_at: datetime,
) -> tuple[SkillPlan, Artifact]:
    optional_skill = repository.get_skill_definition("skill_optional")
    optional_profile = repository.get_skill_capability_profile("skill_optional")
    assert optional_skill is not None and optional_profile is not None
    adjusted = current.model_copy(deep=True)
    adjusted.version = current.version + 1
    adjusted.nodes.append(
        SkillPlanNode(
            id="node_optional",
            skill_id="skill_optional",
            skill_version="1",
            skill_content_hash="b" * 64,
            reason="Add an optional comparison pass",
            required=False,
            required_tool_names=["web_research"],
            resource_manifest=build_skill_resource_manifest_snapshot(
                optional_skill,
                optional_profile,
            ),
        )
    )
    adjusted.preferred_order = ["skill_primary", "skill_optional"]
    adjusted.plan_content_hash = plan_content_hash(adjusted)
    return adjusted, build_deepsearch_plan_snapshot(
        run=run,
        plan=adjusted,
        created_at=created_at,
    )


def _revoke_execution_authorization(
    repository: SQLiteStore,
    run: AgentRun,
    plan: SkillPlan,
    revocation: str,
) -> None:
    user = repository.get_user(run.user_id)
    project = repository.get_project(run.project_id)
    thread = repository.get_chat_thread(run.thread_id)
    assert user is not None and project is not None and thread is not None
    if revocation == "inactive_user":
        repository.save_user(user.model_copy(update={"status": "disabled"}))
    elif revocation == "inactive_project":
        repository.save_project(project.model_copy(update={"status": "archived"}))
    elif revocation == "project_access_revoked":
        repository.save_project(project.model_copy(update={"member_ids": ["another_user"]}))
    elif revocation == "inactive_thread":
        repository.save_chat_thread(thread.model_copy(update={"status": "deleted"}))
    else:
        repository.save_skill_binding(
            SkillBinding(
                id=f"binding_{run.id}_{plan.nodes[0].skill_id}",
                agent_id=user.personal_agent_id,
                skill_id=plan.nodes[0].skill_id,
                enabled=False,
                granted_by=user.id,
            )
        )


def test_plan_edit_atomically_writes_next_version_snapshot_and_renews_ttl(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-edit.sqlite3")
    run, requirement, current, first_snapshot_id = _prepare_waiting_plan(
        repository,
        "run_plan_edit",
    )
    edited_at = NOW + timedelta(hours=1)
    adjusted, snapshot = _edited_plan(
        repository,
        run,
        requirement,
        current,
        created_at=edited_at,
    )

    result = repository.update_deepsearch_plan_and_snapshot(
        run_id=run.id,
        user_id=run.user_id,
        expected_plan_version=current.version,
        plan=adjusted,
        plan_snapshot=snapshot,
        checked_at=edited_at,
    )

    assert result is not None
    saved_plan, saved_run, saved_snapshot = result
    assert saved_plan.version == 2
    assert saved_plan == repository.get_skill_plan(current.id)
    assert saved_snapshot == repository.get_artifact(snapshot.id)
    assert repository.get_artifact(first_snapshot_id) is not None
    assert saved_run.status is AgentRunStatus.WAITING_PLAN_APPROVAL
    assert saved_run.interaction_expires_at == edited_at + timedelta(hours=24)
    first_snapshot = repository.get_artifact(first_snapshot_id)
    assert first_snapshot is not None
    assert saved_run.deepsearch_budget is not None
    expected_usage = DeepSearchBudgetUsageV1(
        artifact_bytes=(first_snapshot.size_bytes or 0) + (snapshot.size_bytes or 0)
    )
    assert saved_run.deepsearch_budget.consumed == expected_usage
    assert len(saved_run.deepsearch_budget.reservations) == 2
    assert repository.list_agent_run_events(run.id)[-1].event_type == "plan_updated"


def test_plan_approval_atomically_freezes_next_version_and_starts_the_run(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-approve.sqlite3")
    run, _requirement, current, first_snapshot_id = _prepare_waiting_plan(
        repository,
        "run_plan_approve",
    )
    approved = current.model_copy(deep=True)
    approved.version = current.version + 1
    approved.status = SkillPlanStatus.APPROVED
    approved_at = NOW + timedelta(hours=2)
    snapshot = build_deepsearch_plan_snapshot(run=run, plan=approved, created_at=approved_at)
    approved.approved_plan_artifact_id = snapshot.id

    result = repository.approve_deepsearch_plan_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        expected_plan_version=current.version,
        plan=approved,
        plan_snapshot=snapshot,
        checked_at=approved_at,
    )

    assert result is not None
    saved_plan, saved_run, saved_snapshot = result
    assert saved_plan.version == 2
    assert saved_plan.status is SkillPlanStatus.APPROVED
    assert saved_plan.approved_plan_artifact_id == snapshot.id
    assert saved_plan == repository.get_skill_plan(current.id)
    assert saved_snapshot == repository.get_artifact(snapshot.id)
    assert repository.get_artifact(first_snapshot_id) is not None
    assert saved_run.status is AgentRunStatus.RUNNING
    assert saved_run.interaction_expires_at is None
    first_snapshot = repository.get_artifact(first_snapshot_id)
    assert first_snapshot is not None
    assert saved_run.deepsearch_budget is not None
    expected_usage = DeepSearchBudgetUsageV1(
        artifact_bytes=(first_snapshot.size_bytes or 0) + (snapshot.size_bytes or 0)
    )
    assert saved_run.deepsearch_budget.consumed == expected_usage
    assert len(saved_run.deepsearch_budget.reservations) == 2
    assert repository.list_agent_run_events(run.id)[-1].event_type == "plan_approved"


def test_plan_approval_allows_persisted_blocking_capability_gaps(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-approve-gaps.sqlite3")
    run, _requirement, current, _first_snapshot_id = _prepare_waiting_plan(
        repository,
        "run_plan_approve_gaps",
        capability_gaps=["deliverable:unavailable_output"],
    )
    approved = current.model_copy(
        deep=True,
        update={
            "version": current.version + 1,
            "status": SkillPlanStatus.APPROVED,
        },
    )
    approved.plan_content_hash = plan_content_hash(approved)
    approved_at = NOW + timedelta(hours=2)
    approved_snapshot = build_deepsearch_plan_snapshot(
        run=run,
        plan=approved,
        created_at=approved_at,
    )
    approved.approved_plan_artifact_id = approved_snapshot.id

    result = repository.approve_deepsearch_plan_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        expected_plan_version=current.version,
        plan=approved,
        plan_snapshot=approved_snapshot,
        checked_at=approved_at,
    )

    assert result is not None
    saved_plan, saved_run, _saved_snapshot = result
    assert saved_plan.capability_gaps == ["deliverable:unavailable_output"]
    assert saved_run.status is AgentRunStatus.RUNNING


@pytest.mark.parametrize(
    "revocation",
    [
        "inactive_user",
        "inactive_project",
        "project_access_revoked",
        "inactive_thread",
        "disabled_skill_binding",
    ],
)
def test_plan_approval_rechecks_current_execution_authorization_without_partial_writes(
    tmp_path,
    revocation: str,
) -> None:
    repository = SQLiteStore(tmp_path / f"deepsearch-plan-approve-authorization-{revocation}.sqlite3")
    run, _requirement, current, _first_snapshot_id = _prepare_waiting_plan(
        repository,
        f"run_plan_approve_authorization_{revocation}",
    )
    _revoke_execution_authorization(repository, run, current, revocation)
    approved = current.model_copy(deep=True)
    approved.version = current.version + 1
    approved.status = SkillPlanStatus.APPROVED
    approved_at = NOW + timedelta(hours=2)
    snapshot = build_deepsearch_plan_snapshot(run=run, plan=approved, created_at=approved_at)
    approved.approved_plan_artifact_id = snapshot.id
    events_before = repository.list_agent_run_events(run.id)

    with pytest.raises(ResearchStoreConflict, match="authorization"):
        repository.approve_deepsearch_plan_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            expected_plan_version=current.version,
            plan=approved,
            plan_snapshot=snapshot,
            checked_at=approved_at,
        )

    assert repository.get_skill_plan(current.id) == current
    assert repository.get_artifact(snapshot.id) is None
    assert repository.get_agent_run(run.id) == run
    assert repository.list_agent_run_events(run.id) == events_before


def test_plan_edit_rejects_immutable_context_changes_without_partial_writes(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-edit-immutable.sqlite3")
    run, requirement, current, _first_snapshot_id = _prepare_waiting_plan(
        repository,
        "run_plan_edit_immutable",
    )
    adjusted, _snapshot = _edited_plan(
        repository,
        run,
        requirement,
        current,
        created_at=NOW + timedelta(hours=1),
    )
    adjusted.intent = SkillIntent(goal="Replace the approved Requirement")
    adjusted.plan_content_hash = plan_content_hash(adjusted)
    snapshot = build_deepsearch_plan_snapshot(
        run=run,
        plan=adjusted,
        created_at=NOW + timedelta(hours=1),
    )
    events_before = repository.list_agent_run_events(run.id)

    with pytest.raises(ResearchStoreConflict, match="edit"):
        repository.update_deepsearch_plan_and_snapshot(
            run_id=run.id,
            user_id=run.user_id,
            expected_plan_version=current.version,
            plan=adjusted,
            plan_snapshot=snapshot,
            checked_at=NOW + timedelta(hours=1),
        )

    assert repository.get_skill_plan(current.id) == current
    assert repository.get_artifact(snapshot.id) is None
    assert repository.get_agent_run(run.id) == run
    assert repository.list_agent_run_events(run.id) == events_before


@pytest.mark.parametrize("transition", ["edit", "approve"])
def test_plan_transitions_reject_caller_supplied_capability_checks(
    tmp_path,
    transition: str,
) -> None:
    repository = SQLiteStore(tmp_path / f"deepsearch-plan-{transition}-capability-check.sqlite3")
    run, requirement, current, _first_snapshot_id = _prepare_waiting_plan(
        repository,
        f"run_plan_{transition}_capability_check",
    )
    if transition == "edit":
        changed, _snapshot = _edited_plan(
            repository,
            run,
            requirement,
            current,
            created_at=NOW + timedelta(hours=1),
        )
    else:
        changed = current.model_copy(deep=True)
        changed.version += 1
        changed.status = SkillPlanStatus.APPROVED
    changed.capability_check = {"caller_claimed_ready": True}
    changed.plan_content_hash = plan_content_hash(changed)
    snapshot = build_deepsearch_plan_snapshot(
        run=run,
        plan=changed,
        created_at=NOW + timedelta(hours=1),
    )
    if transition == "approve":
        changed.approved_plan_artifact_id = snapshot.id
    events_before = repository.list_agent_run_events(run.id)

    expected_error = "edit" if transition == "edit" else "approval"
    with pytest.raises(ResearchStoreConflict, match=expected_error):
        if transition == "edit":
            repository.update_deepsearch_plan_and_snapshot(
                run_id=run.id,
                user_id=run.user_id,
                expected_plan_version=current.version,
                plan=changed,
                plan_snapshot=snapshot,
                checked_at=NOW + timedelta(hours=1),
            )
        else:
            repository.approve_deepsearch_plan_and_transition(
                run_id=run.id,
                user_id=run.user_id,
                expected_plan_version=current.version,
                plan=changed,
                plan_snapshot=snapshot,
                checked_at=NOW + timedelta(hours=1),
            )

    assert repository.get_skill_plan(current.id) == current
    assert repository.get_artifact(snapshot.id) is None
    assert repository.get_agent_run(run.id) == run
    assert repository.list_agent_run_events(run.id) == events_before


def test_plan_edit_rolls_back_when_the_next_snapshot_is_invalid(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-edit-snapshot.sqlite3")
    run, requirement, current, _first_snapshot_id = _prepare_waiting_plan(
        repository,
        "run_plan_edit_snapshot",
    )
    adjusted, snapshot = _edited_plan(
        repository,
        run,
        requirement,
        current,
        created_at=NOW + timedelta(hours=1),
    )
    invalid_snapshot = snapshot.model_copy(update={"content_hash": "0" * 64})
    events_before = repository.list_agent_run_events(run.id)

    with pytest.raises(ResearchStoreConflict, match="snapshot"):
        repository.update_deepsearch_plan_and_snapshot(
            run_id=run.id,
            user_id=run.user_id,
            expected_plan_version=current.version,
            plan=adjusted,
            plan_snapshot=invalid_snapshot,
            checked_at=NOW + timedelta(hours=1),
        )

    assert repository.get_skill_plan(current.id) == current
    assert repository.get_artifact(snapshot.id) is None
    assert repository.get_agent_run(run.id) == run
    assert repository.list_agent_run_events(run.id) == events_before


def test_plan_edit_compare_and_swap_allows_only_one_concurrent_commit(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-edit-cas.sqlite3")
    run, requirement, current, _first_snapshot_id = _prepare_waiting_plan(
        repository,
        "run_plan_edit_cas",
    )
    edited_at = NOW + timedelta(hours=1)
    attempts = [
        _edited_plan(repository, run, requirement, current, created_at=edited_at)
        for _index in range(2)
    ]

    def commit(attempt: tuple[SkillPlan, Artifact]):
        adjusted, snapshot = attempt
        return repository.update_deepsearch_plan_and_snapshot(
            run_id=run.id,
            user_id=run.user_id,
            expected_plan_version=current.version,
            plan=adjusted,
            plan_snapshot=snapshot,
            checked_at=edited_at,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(commit, attempts))

    assert sum(result is not None for result in results) == 1
    saved = repository.get_skill_plan(current.id)
    assert saved is not None and saved.version == 2
    assert sum(
        event.event_type == "plan_updated"
        for event in repository.list_agent_run_events(run.id)
    ) == 1


def test_plan_approval_rejects_any_frozen_content_change_without_partial_writes(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-approve-frozen.sqlite3")
    run, _requirement, current, _first_snapshot_id = _prepare_waiting_plan(
        repository,
        "run_plan_approve_frozen",
    )
    approved = current.model_copy(deep=True)
    approved.version = current.version + 1
    approved.status = SkillPlanStatus.APPROVED
    approved.nodes[0].reason = "Change the frozen work during approval"
    approved.plan_content_hash = plan_content_hash(approved)
    snapshot = build_deepsearch_plan_snapshot(
        run=run,
        plan=approved,
        created_at=NOW + timedelta(hours=2),
    )
    approved.approved_plan_artifact_id = snapshot.id
    events_before = repository.list_agent_run_events(run.id)

    with pytest.raises(ResearchStoreConflict, match="approval"):
        repository.approve_deepsearch_plan_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            expected_plan_version=current.version,
            plan=approved,
            plan_snapshot=snapshot,
            checked_at=NOW + timedelta(hours=2),
        )

    assert repository.get_skill_plan(current.id) == current
    assert repository.get_artifact(snapshot.id) is None
    assert repository.get_agent_run(run.id) == run
    assert repository.list_agent_run_events(run.id) == events_before


def test_plan_approval_rolls_back_when_the_approved_snapshot_is_invalid(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-approve-snapshot.sqlite3")
    run, _requirement, current, _first_snapshot_id = _prepare_waiting_plan(
        repository,
        "run_plan_approve_snapshot",
    )
    approved = current.model_copy(deep=True)
    approved.version = current.version + 1
    approved.status = SkillPlanStatus.APPROVED
    snapshot = build_deepsearch_plan_snapshot(
        run=run,
        plan=approved,
        created_at=NOW + timedelta(hours=2),
    )
    approved.approved_plan_artifact_id = snapshot.id
    invalid_snapshot = snapshot.model_copy(update={"content_hash": "0" * 64})
    events_before = repository.list_agent_run_events(run.id)

    with pytest.raises(ResearchStoreConflict, match="snapshot"):
        repository.approve_deepsearch_plan_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            expected_plan_version=current.version,
            plan=approved,
            plan_snapshot=invalid_snapshot,
            checked_at=NOW + timedelta(hours=2),
        )

    assert repository.get_skill_plan(current.id) == current
    assert repository.get_artifact(snapshot.id) is None
    assert repository.get_agent_run(run.id) == run
    assert repository.list_agent_run_events(run.id) == events_before


def test_plan_approval_compare_and_swap_allows_only_one_concurrent_commit(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-approve-cas.sqlite3")
    run, _requirement, current, _first_snapshot_id = _prepare_waiting_plan(
        repository,
        "run_plan_approve_cas",
    )
    approved_at = NOW + timedelta(hours=2)

    def attempt() -> tuple[SkillPlan, Artifact]:
        approved = current.model_copy(deep=True)
        approved.version = current.version + 1
        approved.status = SkillPlanStatus.APPROVED
        snapshot = build_deepsearch_plan_snapshot(
            run=run,
            plan=approved,
            created_at=approved_at,
        )
        approved.approved_plan_artifact_id = snapshot.id
        return approved, snapshot

    def commit(item: tuple[SkillPlan, Artifact]):
        approved, snapshot = item
        return repository.approve_deepsearch_plan_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            expected_plan_version=current.version,
            plan=approved,
            plan_snapshot=snapshot,
            checked_at=approved_at,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(commit, [attempt(), attempt()]))

    assert sum(result is not None for result in results) == 1
    saved_plan = repository.get_skill_plan(current.id)
    saved_run = repository.get_agent_run(run.id)
    assert saved_plan is not None and saved_plan.status is SkillPlanStatus.APPROVED
    assert saved_run is not None and saved_run.status is AgentRunStatus.RUNNING
    assert sum(
        event.event_type == "plan_approved"
        for event in repository.list_agent_run_events(run.id)
    ) == 1


def test_plan_approval_rechecks_the_current_tool_grant_without_partial_writes(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-approve-grant.sqlite3")
    run, _requirement, current, _first_snapshot_id = _prepare_waiting_plan(
        repository,
        "run_plan_approve_grant",
    )
    grant = repository.list_agent_tool_grants("agent_deepsearch_transition")[0]
    repository.save_agent_tool_grant(grant.model_copy(update={"enabled": False}))
    approved = current.model_copy(deep=True)
    approved.version = current.version + 1
    approved.status = SkillPlanStatus.APPROVED
    snapshot = build_deepsearch_plan_snapshot(
        run=run,
        plan=approved,
        created_at=NOW + timedelta(hours=2),
    )
    approved.approved_plan_artifact_id = snapshot.id
    events_before = repository.list_agent_run_events(run.id)

    with pytest.raises(ResearchStoreConflict, match="integrity"):
        repository.approve_deepsearch_plan_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            expected_plan_version=current.version,
            plan=approved,
            plan_snapshot=snapshot,
            checked_at=NOW + timedelta(hours=2),
        )

    assert repository.get_skill_plan(current.id) == current
    assert repository.get_artifact(snapshot.id) is None
    assert repository.get_agent_run(run.id) == run
    assert repository.list_agent_run_events(run.id) == events_before


def test_plan_approval_rejects_non_web_tool_even_when_profile_plan_and_grant_match(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-approve-non-web-tool.sqlite3")
    run, _requirement, current, _first_snapshot_id = _prepare_waiting_plan(
        repository,
        "run_plan_approve_non_web_tool",
    )
    profile = repository.get_skill_capability_profile("skill_primary")
    assert profile is not None
    repository.save_skill_capability_profile(
        profile.model_copy(update={"required_tools": ["data_query"]}),
        defer_vector=True,
    )
    tool = repository.save_tool_definition(
        ToolDefinition(
            id="tool_data_query",
            name="data_query",
            description="Read an internal data source",
            category="data",
            side_effect="read",
        )
    )
    repository.save_agent_tool_grant(
        AgentToolGrant(
            agent_id="agent_deepsearch_transition",
            tool_id=tool.id,
            granted_by="user_deepsearch_transition",
        )
    )
    tampered = current.model_copy(deep=True)
    tampered.nodes[0].required_tool_names = ["data_query"]
    tampered.plan_content_hash = plan_content_hash(tampered)
    with repository._connect() as connection:
        connection.execute(
            "UPDATE skill_plans SET payload = ? WHERE id = ?",
            (tampered.model_dump_json(), tampered.id),
        )

    approved = tampered.model_copy(deep=True)
    approved.version += 1
    approved.status = SkillPlanStatus.APPROVED
    approved_at = NOW + timedelta(hours=2)
    snapshot = build_deepsearch_plan_snapshot(run=run, plan=approved, created_at=approved_at)
    approved.approved_plan_artifact_id = snapshot.id
    events_before = repository.list_agent_run_events(run.id)

    with pytest.raises(ResearchStoreConflict, match="integrity"):
        repository.approve_deepsearch_plan_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            expected_plan_version=tampered.version,
            plan=approved,
            plan_snapshot=snapshot,
            checked_at=approved_at,
        )

    assert repository.get_skill_plan(tampered.id) == tampered
    assert repository.get_artifact(snapshot.id) is None
    assert repository.get_agent_run(run.id) == run
    assert repository.list_agent_run_events(run.id) == events_before


@pytest.mark.parametrize("capability", ["wiki.missing-corpus", "unknown.capability"])
def test_plan_approval_rejects_an_unknown_required_capability(
    tmp_path,
    capability: str,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-approve-capability.sqlite3")
    run, _requirement, current, _first_snapshot_id = _prepare_waiting_plan(
        repository,
        f"run_plan_approve_capability_{capability.replace('.', '_')}",
    )
    profile = repository.get_skill_capability_profile("skill_primary")
    assert profile is not None
    repository.save_skill_capability_profile(
        profile.model_copy(update={"required_capabilities": [capability]}),
        defer_vector=True,
    )
    if capability == "unknown.capability":
        tool = repository.save_tool_definition(
            ToolDefinition(
                id="tool_unknown_capability",
                name=capability,
                external_name=capability,
                description="A Tool cannot make an unknown capability valid",
                category="research",
                side_effect="read",
            )
        )
        repository.save_agent_tool_grant(
            AgentToolGrant(
                agent_id="agent_deepsearch_transition",
                tool_id=tool.id,
                granted_by="user_deepsearch_transition",
            )
        )
    approved = current.model_copy(deep=True)
    approved.version += 1
    approved.status = SkillPlanStatus.APPROVED
    snapshot = build_deepsearch_plan_snapshot(
        run=run,
        plan=approved,
        created_at=NOW + timedelta(hours=2),
    )
    approved.approved_plan_artifact_id = snapshot.id
    events_before = repository.list_agent_run_events(run.id)

    with pytest.raises(ResearchStoreConflict, match="integrity"):
        repository.approve_deepsearch_plan_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            expected_plan_version=current.version,
            plan=approved,
            plan_snapshot=snapshot,
            checked_at=NOW + timedelta(hours=2),
        )

    assert repository.get_skill_plan(current.id) == current
    assert repository.get_artifact(snapshot.id) is None
    assert repository.get_agent_run(run.id) == run
    assert repository.list_agent_run_events(run.id) == events_before


def test_plan_approval_accepts_a_ready_mapped_required_capability(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-approve-mapped-capability.sqlite3")
    run, _requirement, current, _first_snapshot_id = _prepare_waiting_plan(
        repository,
        "run_plan_approve_mapped_capability",
    )
    profile = repository.get_skill_capability_profile("skill_primary")
    assert profile is not None
    repository.save_skill_capability_profile(
        profile.model_copy(update={"required_capabilities": ["research.request"]}),
        defer_vector=True,
    )
    approved = current.model_copy(deep=True)
    approved.version += 1
    approved.status = SkillPlanStatus.APPROVED
    snapshot = build_deepsearch_plan_snapshot(
        run=run,
        plan=approved,
        created_at=NOW + timedelta(hours=2),
    )
    approved.approved_plan_artifact_id = snapshot.id

    result = repository.approve_deepsearch_plan_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        expected_plan_version=current.version,
        plan=approved,
        plan_snapshot=snapshot,
        checked_at=NOW + timedelta(hours=2),
    )

    assert result is not None
    saved_plan, saved_run, _saved_snapshot = result
    assert saved_plan.status is SkillPlanStatus.APPROVED
    assert saved_run.status is AgentRunStatus.RUNNING


def test_expired_plan_edit_cancels_instead_of_committing_a_late_version(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-edit-expired.sqlite3")
    run, requirement, current, _first_snapshot_id = _prepare_waiting_plan(
        repository,
        "run_plan_edit_expired",
    )
    adjusted, snapshot = _edited_plan(
        repository,
        run,
        requirement,
        current,
        created_at=NOW + timedelta(hours=25),
    )

    with pytest.raises(DeepSearchRequirementConflict, match="expired"):
        repository.update_deepsearch_plan_and_snapshot(
            run_id=run.id,
            user_id=run.user_id,
            expected_plan_version=current.version,
            plan=adjusted,
            plan_snapshot=snapshot,
            checked_at=NOW + timedelta(hours=25),
        )

    persisted_run = repository.get_agent_run(run.id)
    persisted_plan = repository.get_skill_plan(current.id)
    assert persisted_run is not None and persisted_run.status is AgentRunStatus.CANCELLED
    assert persisted_plan is not None and persisted_plan.status is SkillPlanStatus.CANCELLED
    assert repository.get_artifact(snapshot.id) is None
