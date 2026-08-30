from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import suppress
from datetime import UTC, datetime, timedelta

import pytest

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
    ArtifactVerificationState,
    ChatThread,
    DeepSearchBudgetV1,
    InboxItem,
    Project,
    Scope,
    SkillBinding,
    SkillCapabilityProfile,
    SkillCapabilityType,
    SkillDefinition,
    SkillIntent,
    SkillLifecycleStage,
    SkillNodeResult,
    SkillOrchestrationRequestMode,
    SkillPlan,
    SkillPlanNode,
    SkillPlanNodeStatus,
    SkillPlanStatus,
    SkillSourceScope,
    ToolDefinition,
    User,
)
from agentmesh.skill_runtime.executor import BoundedDAGExecutor, NodeExecutionOutcome
from agentmesh.skill_runtime.finalization import PlanExecutionOutcome
from agentmesh.skill_runtime.resources import build_skill_resource_manifest_snapshot
from agentmesh.store import ResearchStoreConflict, SQLiteStore

NOW = datetime(2026, 8, 26, 16, 0, tzinfo=UTC)


def _run(run_id: str) -> AgentRun:
    return AgentRun(
        id=run_id,
        thread_id=f"thread_{run_id}",
        user_id="user_deepsearch_execution_claim",
        workspace_id="workspace_deepsearch_execution_claim",
        project_id="project_deepsearch_execution_claim",
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


def _seed_runtime(
    repository: SQLiteStore,
    *,
    required_tools: list[str] | None = None,
) -> AgentToolGrant:
    required_tools = ["web_research"] if required_tools is None else required_tools
    skill_file = repository.db_path.parent / "skills" / "execution-claim" / "SKILL.md"
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text("# Execution claim\n", encoding="utf-8")
    repository.save_user(
        User(
            id="user_deepsearch_execution_claim",
            workspace_id="workspace_deepsearch_execution_claim",
            default_project_id="project_deepsearch_execution_claim",
            name="DeepSearch execution claimant",
            role="user",
            personal_agent_id="agent_deepsearch_execution_claim",
        )
    )
    repository.save_project(
        Project(
            id="project_deepsearch_execution_claim",
            workspace_id="workspace_deepsearch_execution_claim",
            name="DeepSearch execution project",
            goal="Test DeepSearch execution authorization",
            member_ids=["user_deepsearch_execution_claim"],
        )
    )
    repository.save_skill_definition(
        SkillDefinition(
            id="skill_execution_claim",
            name="execution-claim",
            title="Execution claim",
            description="Read trusted evidence",
            instructions="Use trustworthy sources.",
            source_path=str(skill_file),
            source_scope=SkillSourceScope.BUILTIN,
            content_hash="a" * 64,
            version="1",
        ),
        defer_vector=True,
    )
    repository.save_skill_capability_profile(
        SkillCapabilityProfile(
            id="skill_execution_claim",
            skill_id="skill_execution_claim",
            skill_name="execution-claim",
            skill_version="1",
            skill_content_hash="a" * 64,
            profile_version="1",
            profile_content_hash="b" * 64,
            primary_stage=SkillLifecycleStage.PRE_DESIGN,
            capability_type=SkillCapabilityType.RESEARCH,
            required_tools=required_tools,
        ),
        defer_vector=True,
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
    return repository.save_agent_tool_grant(
        AgentToolGrant(
            id="grant_execution_claim",
            agent_id="agent_deepsearch_execution_claim",
            tool_id="tool_web_research",
            granted_by="user_deepsearch_execution_claim",
        )
    )


def _prepare_waiting_plan(
    repository: SQLiteStore,
    *,
    run_id: str,
    required_tools: list[str] | None = None,
) -> tuple[AgentRun, SkillPlan, Artifact, AgentToolGrant]:
    required_tools = ["web_research"] if required_tools is None else required_tools
    grant = _seed_runtime(repository, required_tools=required_tools)
    skill = repository.get_skill_definition("skill_execution_claim")
    profile = repository.get_skill_capability_profile("skill_execution_claim")
    assert skill is not None and profile is not None
    repository.add_chat_thread(
        ChatThread(
            id=f"thread_{run_id}",
            workspace_id="workspace_deepsearch_execution_claim",
            project_id="project_deepsearch_execution_claim",
            user_id="user_deepsearch_execution_claim",
            title="DeepSearch execution claim",
        )
    )
    run, created = repository.claim_new_agent_run(_run(run_id))
    assert created is True
    assert run.client_turn_id is not None
    assert run.create_request_hash is not None
    payload = RequirementPayloadV1(
        goal=run.input_text,
        scope=RequirementScopeV1(regions=["China"]),
        success_criteria=[
            RequirementSuccessCriterionV1(
                id="criterion_comparison",
                statement="Compare the leading platforms",
            )
        ],
        deliverables=["Research report"],
    )
    requirement = RequirementVersionV1(
        id=f"requirement_{run.id}_v1",
        run_id=run.id,
        version=1,
        request_key=run.client_turn_id,
        request_hash=run.create_request_hash,
        content_hash=requirement_content_hash(payload),
        payload=payload,
        created_at=NOW,
    )
    appended = repository.append_deepsearch_requirement_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        requirement=requirement.model_dump(mode="json"),
        expected_requirement_version=None,
        expected_run_status=AgentRunStatus.PLANNING,
        next_run_status=AgentRunStatus.PLANNING,
        events=[],
        checked_at=NOW,
    )
    assert appended is not None
    question = ProblemQuestionV1(
        id=problem_question_id("Which platforms lead the market?"),
        question="Which platforms lead the market?",
        required=True,
        success_criterion_ids=["criterion_comparison"],
        evidence_requirements=["Public market evidence"],
        acceptance_criteria=["Compare the leading platforms"],
    )
    graph = build_problem_graph(requirement=requirement, questions=[question])
    plan = SkillPlan(
        id=f"plan_{run.id}",
        run_id=run.id,
        status=SkillPlanStatus.WAITING_APPROVAL,
        intent=SkillIntent(goal=run.input_text),
        candidate_skill_ids=["skill_execution_claim"],
        preferred_order=["skill_execution_claim"],
        nodes=[
            SkillPlanNode(
                id="node_execution_claim",
                skill_id="skill_execution_claim",
                skill_version="1",
                skill_content_hash="a" * 64,
                reason="Answer the required comparison question",
                question_ids=[question.id],
                required_tool_names=required_tools,
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
    initial_snapshot = build_deepsearch_plan_snapshot(run=run, plan=plan, created_at=NOW)
    initial = repository.save_deepsearch_plan_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        expected_requirement_version=requirement.version,
        plan=plan,
        plan_snapshot=initial_snapshot,
        checked_at=NOW,
    )
    assert initial is not None
    current_plan, waiting_run, initial_snapshot = initial
    return waiting_run, current_plan, initial_snapshot, grant


def _prepare_approved_plan(
    repository: SQLiteStore,
    *,
    run_id: str,
    required_tools: list[str] | None = None,
) -> tuple[AgentRun, SkillPlan, Artifact, AgentToolGrant]:
    waiting_run, current_plan, _initial_snapshot, grant = _prepare_waiting_plan(
        repository,
        run_id=run_id,
        required_tools=required_tools,
    )
    approved = current_plan.model_copy(deep=True)
    approved.version += 1
    approved.status = SkillPlanStatus.APPROVED
    approved_snapshot = build_deepsearch_plan_snapshot(
        run=waiting_run,
        plan=approved,
        created_at=NOW + timedelta(minutes=1),
    )
    approved.approved_plan_artifact_id = approved_snapshot.id
    committed = repository.approve_deepsearch_plan_and_transition(
        run_id=waiting_run.id,
        user_id=waiting_run.user_id,
        expected_plan_version=current_plan.version,
        plan=approved,
        plan_snapshot=approved_snapshot,
        checked_at=NOW + timedelta(minutes=1),
    )
    assert committed is not None
    approved_plan, running_run, sealed_snapshot = committed
    return running_run, approved_plan, sealed_snapshot, grant


def _replace_snapshot(repository: SQLiteStore, artifact: Artifact) -> None:
    with repository._connect() as connection:
        connection.execute(
            """UPDATE artifacts SET
                payload = ?, verification_state = ?, content_hash = ?, size_bytes = ?,
                requirement_version_id = ?, plan_version_id = ?
            WHERE id = ?""",
            (
                artifact.model_dump_json(),
                artifact.verification_state.value if artifact.verification_state is not None else None,
                artifact.content_hash,
                artifact.size_bytes,
                artifact.requirement_version_id,
                artifact.plan_version_id,
                artifact.id,
            ),
        )


def _replace_run_fixture(repository: SQLiteStore, run: AgentRun) -> AgentRun:
    """Seed an otherwise unreachable persisted state without reopening production writers."""
    with repository._connect() as connection:
        cursor = connection.execute(
            "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
            (run.model_dump_json(), run.updated_at.isoformat(), run.id),
        )
    assert cursor.rowcount == 1
    persisted = repository.get_agent_run(run.id)
    assert persisted is not None
    return persisted


def _assert_execution_claim_rejected(
    repository: SQLiteStore,
    plan: SkillPlan,
    run: AgentRun,
    *,
    match: str | None = None,
) -> None:
    with pytest.raises(ResearchStoreConflict, match=match):
        repository.claim_skill_plan_for_execution(plan.id, run.id)
    persisted = repository.get_skill_plan(plan.id)
    assert persisted is not None
    assert persisted.status is SkillPlanStatus.APPROVED
    assert repository.get_agent_run(run.id) == run


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


def test_deepsearch_execution_claim_revalidates_plan_and_approved_snapshot(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-execution-claim.sqlite3")
    run, plan, _snapshot, _grant = _prepare_approved_plan(
        repository,
        run_id="run_execution_claim",
    )

    claimed = repository.claim_skill_plan_for_execution(plan.id, run.id)

    assert claimed is not None
    assert claimed.status is SkillPlanStatus.RUNNING
    assert repository.claim_skill_plan_for_execution(plan.id, run.id) is None


def test_deepsearch_recovery_marks_orphaned_running_node_unknown_without_replay(
    tmp_path,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-orphan-node-recovery.sqlite3")
    run, plan, _snapshot, _grant = _prepare_approved_plan(
        repository,
        run_id="run_orphan_node_recovery",
    )
    running_plan = repository.claim_skill_plan_for_execution(plan.id, run.id)
    assert running_plan is not None
    ready = running_plan.nodes[0].model_copy(update={"status": SkillPlanNodeStatus.READY})
    assert repository.transition_skill_plan_node(
        plan_id=running_plan.id,
        run_id=run.id,
        node=ready,
        expected_statuses={SkillPlanNodeStatus.PENDING},
        event_type="node_ready",
        event_payload={"plan_id": running_plan.id, "node_id": ready.id},
    ) is not None
    claimed = repository.claim_skill_plan_node(running_plan.id, ready.id)
    assert claimed is not None
    event_count = len(repository.list_agent_run_events(run.id))

    recovered = repository.prepare_deepsearch_execution_recovery(
        run_id=run.id,
        checked_at=NOW + timedelta(minutes=2),
    )

    assert recovered is not None
    recovered_plan, recovered_run = recovered
    assert recovered_run.status is AgentRunStatus.RUNNING
    assert recovered_plan.nodes[0].status is SkillPlanNodeStatus.FAILED
    assert recovered_plan.nodes[0].error_code == "external_outcome_unknown"
    assert recovered_plan.nodes[0].attempt == claimed.attempt
    events = repository.list_agent_run_events(run.id)
    assert len(events) == event_count + 1
    assert events[-1].event_type == "node_failed"
    assert events[-1].payload["error_code"] == "external_outcome_unknown"

    replayed = repository.prepare_deepsearch_execution_recovery(
        run_id=run.id,
        checked_at=NOW + timedelta(minutes=3),
    )
    assert replayed is not None
    assert replayed[0] == recovered_plan
    assert len(repository.list_agent_run_events(run.id)) == len(events)


def test_process_task_cancellation_leaves_deepsearch_node_for_recovery(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-cancelled-task-recovery.sqlite3")
    run, plan, _snapshot, _grant = _prepare_approved_plan(
        repository,
        run_id="run_cancelled_task_recovery",
    )
    started = asyncio.Event()

    async def node_runner(
        _plan: SkillPlan,
        _node: SkillPlanNode,
        _upstream: list[SkillNodeResult],
    ) -> NodeExecutionOutcome:
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    class UnusedFinalizer:
        async def finalize(
            self,
            *,
            run_id: str,
            plan_id: str,
            expected_plan_version: int,
        ) -> PlanExecutionOutcome:
            raise AssertionError((run_id, plan_id, expected_plan_version))

    async def crash() -> None:
        task = asyncio.create_task(
            BoundedDAGExecutor(
                repository,
                node_runner=node_runner,
                finalization_strategy=UnusedFinalizer(),
            ).run(plan, run)
        )
        await started.wait()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    asyncio.run(crash())

    abandoned_run = repository.get_agent_run(run.id)
    abandoned_plan = repository.get_skill_plan(plan.id)
    assert abandoned_run is not None and abandoned_run.status is AgentRunStatus.RUNNING
    assert abandoned_plan is not None and abandoned_plan.status is SkillPlanStatus.RUNNING
    assert abandoned_plan.nodes[0].status is SkillPlanNodeStatus.RUNNING

    recovered = repository.prepare_deepsearch_execution_recovery(run_id=run.id)

    assert recovered is not None
    assert recovered[0].nodes[0].status is SkillPlanNodeStatus.FAILED
    assert recovered[0].nodes[0].error_code == "external_outcome_unknown"


def test_deepsearch_recovery_lists_only_active_deepsearch_runs(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-recovery-list.sqlite3")
    active, _created = repository.claim_new_agent_run(_run("run_recovery_active"))
    terminal, _created = repository.claim_new_agent_run(_run("run_recovery_terminal"))
    assert repository.fail_deepsearch_planning_run(
        run_id=terminal.id,
        user_id=terminal.user_id,
        error_code="deepsearch_planning_failed",
        checked_at=NOW,
    ) is not None
    repository.save_agent_run(
        AgentRun(
            id="run_recovery_standard",
            thread_id="thread_recovery_standard",
            user_id="user_recovery_standard",
            workspace_id="workspace_recovery_standard",
            project_id="project_recovery_standard",
            input_text="standard",
            status=AgentRunStatus.RUNNING,
        )
    )

    recoverable = repository.list_recoverable_deepsearch_runs()

    assert [run.id for run in recoverable] == [active.id]


def test_invalid_preplan_recovery_state_fails_without_creating_a_plan(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-invalid-recovery.sqlite3")
    run, created = repository.claim_new_agent_run(_run("run_invalid_recovery"))
    assert created is True

    failed = repository.fail_deepsearch_recovery_state(
        run_id=run.id,
        checked_at=NOW + timedelta(minutes=1),
    )

    assert failed is not None
    assert failed.status is AgentRunStatus.FAILED
    assert failed.error_code == "deepsearch_recovery_state_invalid"
    assert repository.get_skill_plan_for_run(run.id) is None
    assert repository.list_agent_run_events(run.id)[-1].payload == {
        "error_code": "deepsearch_recovery_state_invalid"
    }


def test_invalid_approved_plan_recovery_fails_plan_and_run_together(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-invalid-plan-recovery.sqlite3")
    run, plan, _snapshot, _grant = _prepare_approved_plan(
        repository,
        run_id="run_invalid_plan_recovery",
    )

    failed = repository.fail_deepsearch_recovery_state(
        run_id=run.id,
        checked_at=NOW + timedelta(minutes=2),
    )

    assert failed is not None
    assert failed.status is AgentRunStatus.FAILED
    assert failed.error_code == "deepsearch_recovery_state_invalid"
    persisted_plan = repository.get_skill_plan(plan.id)
    assert persisted_plan is not None
    assert persisted_plan.status is SkillPlanStatus.FAILED
    assert persisted_plan.finalization_stage.value == "terminal_committed"
    assert persisted_plan.nodes[0].status is SkillPlanNodeStatus.CANCELLED
    assert repository.list_agent_run_events(run.id)[-1].event_type == "run_failed"


def test_tampered_running_plan_is_rejected_then_failed_closed(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-tampered-recovery.sqlite3")
    run, plan, _snapshot, _grant = _prepare_approved_plan(
        repository,
        run_id="run_tampered_recovery",
    )
    running = repository.claim_skill_plan_for_execution(plan.id, run.id)
    assert running is not None
    tampered_node = running.nodes[0].model_copy(update={"reason": "tampered"})
    tampered = running.model_copy(update={"nodes": [tampered_node]})
    with repository._connect() as connection:
        repository._write_skill_plan(connection, tampered)

    with pytest.raises(ResearchStoreConflict, match="lineage"):
        repository.prepare_deepsearch_execution_recovery(run_id=run.id)

    failed = repository.fail_deepsearch_recovery_state(run_id=run.id)

    assert failed is not None
    assert failed.status is AgentRunStatus.FAILED
    assert failed.error_code == "deepsearch_recovery_state_invalid"
    failed_plan = repository.get_skill_plan(plan.id)
    assert failed_plan is not None
    assert failed_plan.status is SkillPlanStatus.FAILED
    assert failed_plan.finalization_stage.value == "terminal_committed"


def test_malformed_plan_payload_cannot_leave_recovery_run_active(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-malformed-recovery.sqlite3")
    run, plan, _snapshot, _grant = _prepare_approved_plan(
        repository,
        run_id="run_malformed_recovery",
    )
    with repository._connect() as connection:
        connection.execute(
            "UPDATE skill_plans SET payload = ? WHERE id = ?",
            ("{malformed", plan.id),
        )

    with pytest.raises(ResearchStoreConflict, match="Plan is invalid"):
        repository.prepare_deepsearch_execution_recovery(run_id=run.id)

    failed = repository.fail_deepsearch_recovery_state(run_id=run.id)

    assert failed is not None
    assert failed.status is AgentRunStatus.FAILED
    assert failed.error_code == "deepsearch_recovery_state_invalid"
    with repository._read_connect() as connection:
        status = connection.execute(
            "SELECT status FROM skill_plans WHERE id = ?",
            (plan.id,),
        ).fetchone()["status"]
    assert status == SkillPlanStatus.FAILED.value


@pytest.mark.parametrize(
    "corruption",
    ["missing", "wrong_version", "tampered_content", "not_sealed"],
)
def test_deepsearch_execution_claim_rejects_invalid_approved_snapshot(
    tmp_path,
    corruption: str,
) -> None:
    repository = SQLiteStore(tmp_path / f"deepsearch-execution-snapshot-{corruption}.sqlite3")
    run, plan, snapshot, _grant = _prepare_approved_plan(
        repository,
        run_id=f"run_execution_snapshot_{corruption}",
    )
    if corruption == "missing":
        with repository._connect() as connection:
            connection.execute("DELETE FROM artifacts WHERE id = ?", (snapshot.id,))
    elif corruption == "wrong_version":
        _replace_snapshot(
            repository,
            snapshot.model_copy(update={"plan_version_id": f"{plan.id}:v{plan.version - 1}"}),
        )
    elif corruption == "tampered_content":
        payload = json.loads(snapshot.content)
        payload["frozen_plan"]["nodes"][0]["reason"] = "tampered after approval"
        content = canonical_json_bytes(payload).decode("utf-8")
        encoded = content.encode("utf-8")
        _replace_snapshot(
            repository,
            snapshot.model_copy(
                update={
                    "content": content,
                    "content_hash": hashlib.sha256(encoded).hexdigest(),
                    "size_bytes": len(encoded),
                }
            ),
        )
    else:
        _replace_snapshot(
            repository,
            snapshot.model_copy(update={"verification_state": ArtifactVerificationState.FAILED}),
        )

    _assert_execution_claim_rejected(repository, plan, run)


def test_deepsearch_execution_claim_rechecks_current_tool_grant(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-execution-grant.sqlite3")
    run, plan, _snapshot, grant = _prepare_approved_plan(
        repository,
        run_id="run_execution_grant",
    )
    repository.save_agent_tool_grant(grant.model_copy(update={"enabled": False}))

    _assert_execution_claim_rejected(repository, plan, run)


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
def test_deepsearch_execution_claim_rechecks_current_authorization(
    tmp_path,
    revocation: str,
) -> None:
    repository = SQLiteStore(tmp_path / f"deepsearch-execution-authorization-{revocation}.sqlite3")
    run, plan, _snapshot, _grant = _prepare_approved_plan(
        repository,
        run_id=f"run_execution_authorization_{revocation}",
    )
    _revoke_execution_authorization(repository, run, plan, revocation)

    _assert_execution_claim_rejected(repository, plan, run, match="authorization")


def test_deepsearch_execution_claim_rechecks_binding_without_required_tools(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-execution-binding-without-tools.sqlite3")
    run, plan, _snapshot, _grant = _prepare_approved_plan(
        repository,
        run_id="run_execution_binding_without_tools",
        required_tools=[],
    )
    _revoke_execution_authorization(repository, run, plan, "disabled_skill_binding")

    _assert_execution_claim_rejected(repository, plan, run, match="authorization")


def test_generic_save_skill_plan_rejects_deepsearch(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-generic-plan-save.sqlite3")
    run, created = repository.claim_new_agent_run(_run("run_generic_plan_save"))
    assert created is True
    plan = SkillPlan(
        id="plan_generic_plan_save",
        run_id=run.id,
        status=SkillPlanStatus.WAITING_APPROVAL,
        intent=SkillIntent(goal=run.input_text),
        planning_mode=AgentPlanningMode.DEEPSEARCH,
    )

    with pytest.raises(ResearchStoreConflict, match="dedicated persistence"):
        repository.save_skill_plan(plan)

    assert repository.get_skill_plan(plan.id) is None


def test_generic_plan_compare_and_swap_rejects_deepsearch(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-generic-plan-cas.sqlite3")
    _run_state, plan, _snapshot, _grant = _prepare_waiting_plan(
        repository,
        run_id="run_generic_plan_cas",
    )

    with pytest.raises(ResearchStoreConflict, match="dedicated persistence"):
        repository.compare_and_swap_skill_plan(
            plan.model_copy(deep=True),
            expected_version=plan.version,
        )

    assert repository.get_skill_plan(plan.id) == plan


def test_generic_plan_transition_cannot_start_deepsearch(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-generic-plan-transition.sqlite3")
    run, plan, _snapshot, _grant = _prepare_approved_plan(
        repository,
        run_id="run_generic_plan_transition",
    )

    with pytest.raises(ResearchStoreConflict, match="dedicated transitions"):
        repository.transition_skill_plan_and_run(
            plan_id=plan.id,
            run_id=run.id,
            expected_version=plan.version,
            expected_plan_status=SkillPlanStatus.APPROVED,
            expected_run_status=AgentRunStatus.RUNNING,
            next_plan_status=SkillPlanStatus.RUNNING,
            next_run_status=AgentRunStatus.RUNNING,
            events=[],
        )

    persisted = repository.get_skill_plan(plan.id)
    assert persisted is not None
    assert persisted.status is SkillPlanStatus.APPROVED


def test_generic_plan_transition_allows_only_deepsearch_rejection(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-generic-plan-reject.sqlite3")
    run, plan, _snapshot, _grant = _prepare_waiting_plan(
        repository,
        run_id="run_generic_plan_reject",
    )

    result = repository.transition_skill_plan_and_run(
        plan_id=plan.id,
        run_id=run.id,
        expected_version=plan.version,
        expected_plan_status=SkillPlanStatus.WAITING_APPROVAL,
        expected_run_status=AgentRunStatus.WAITING_PLAN_APPROVAL,
        next_plan_status=SkillPlanStatus.REJECTED,
        next_run_status=AgentRunStatus.REJECTED,
        events=[("plan_rejected", {"plan_id": plan.id}), ("run_rejected", {})],
        output_text="Plan rejected",
    )

    assert result is not None
    rejected_plan, rejected_run = result
    assert rejected_plan.status is SkillPlanStatus.REJECTED
    assert rejected_run.status is AgentRunStatus.REJECTED


def test_generic_pause_cannot_mutate_a_deepsearch_run_or_create_an_inbox(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-generic-pause-fence.sqlite3")
    run, plan, _snapshot, _grant = _prepare_approved_plan(
        repository,
        run_id="run_generic_pause_fence",
    )
    inbox = InboxItem(
        id="inbox_generic_pause_fence",
        title="Approve tool call",
        summary="Must not be persisted through the generic pause writer.",
        item_type="sdk_tool_approval",
        scope=Scope.PRIVATE,
        user_id=run.user_id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        metadata={"run_id": run.id},
    )
    events_before = repository.list_agent_run_events(run.id)

    with pytest.raises(ResearchStoreConflict, match="dedicated persistence"):
        repository.pause_agent_run_with_inbox(
            run_id=run.id,
            paused_state={"kind": "generic"},
            inbox_item=inbox,
            interruptions=[],
        )

    assert repository.get_agent_run(run.id) == run
    assert repository.get_skill_plan(plan.id) == plan
    assert repository.get_inbox_item(inbox.id) is None
    assert repository.list_agent_run_events(run.id) == events_before


def test_generic_finalizer_cannot_mutate_a_deepsearch_plan_or_run(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-generic-finalizer-fence.sqlite3")
    run, plan, _snapshot, _grant = _prepare_approved_plan(
        repository,
        run_id="run_generic_finalizer_fence",
    )
    terminal_plan = plan.model_copy(update={"status": SkillPlanStatus.COMPLETED})
    terminal_run = run.model_copy(
        update={
            "status": AgentRunStatus.COMPLETED,
            "output_text": "stale terminal output",
        }
    )
    events_before = repository.list_agent_run_events(run.id)

    with pytest.raises(ResearchStoreConflict, match="dedicated persistence"):
        repository.finish_skill_plan_and_run(
            plan=terminal_plan,
            run=terminal_run,
            expected_plan_statuses={SkillPlanStatus.APPROVED},
            expected_run_statuses={AgentRunStatus.RUNNING},
            events=[("run_completed", {"plan_id": plan.id})],
        )

    assert repository.get_agent_run(run.id) == run
    assert repository.get_skill_plan(plan.id) == plan
    assert repository.list_agent_run_events(run.id) == events_before


def test_deepsearch_node_pause_and_resume_manage_interaction_ttl_without_changing_budget(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-node-pause-ttl.sqlite3")
    run, plan, _snapshot, _grant = _prepare_approved_plan(
        repository,
        run_id="run_node_pause_ttl",
    )
    running_plan = repository.claim_skill_plan_for_execution(plan.id, run.id)
    assert running_plan is not None
    pending_node = running_plan.nodes[0]
    ready_node = pending_node.model_copy(update={"status": SkillPlanNodeStatus.READY})
    assert repository.transition_skill_plan_node(
        plan_id=running_plan.id,
        run_id=run.id,
        node=ready_node,
        expected_statuses={SkillPlanNodeStatus.PENDING},
        event_type="node_ready",
        event_payload={"plan_id": running_plan.id, "node_id": ready_node.id},
    ) is not None
    running_node = repository.claim_skill_plan_node(running_plan.id, ready_node.id)
    assert running_node is not None

    paused_at = run.absolute_expires_at - timedelta(minutes=30)  # type: ignore[operator]
    monkeypatch.setattr("agentmesh.store.now_utc", lambda: paused_at)
    inbox = InboxItem(
        id="inbox_node_pause_ttl",
        title="Approve tool call",
        summary="Confirm the planned read operation.",
        item_type="sdk_tool_approval",
        scope=Scope.PRIVATE,
        user_id=run.user_id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        metadata={"run_id": run.id},
        created_at=paused_at,
        updated_at=paused_at,
    )
    paused = repository.pause_skill_plan_node_and_run(
        plan_id=running_plan.id,
        run_id=run.id,
        node_id=running_node.id,
        attempt=running_node.attempt,
        paused_state={
            "kind": "skill_plan_node",
            "plan_id": running_plan.id,
            "node_id": running_node.id,
            "expires_at": run.absolute_expires_at.isoformat(),  # type: ignore[union-attr]
        },
        inbox_item=inbox,
        call_ids=[],
    )

    assert paused is not None
    _paused_plan, paused_run, _paused_node = paused
    assert paused_run.interaction_expires_at == run.absolute_expires_at
    assert paused_run.deepsearch_budget == run.deepsearch_budget

    resumed = repository.claim_agent_run_for_resume(
        run.id,
        run.user_id,
        inbox_id=inbox.id,
    )

    assert resumed is not None
    assert resumed.status is AgentRunStatus.RUNNING
    assert resumed.interaction_expires_at is None
    assert resumed.deepsearch_budget == run.deepsearch_budget

    restored_expiry = paused_at + timedelta(hours=1)
    restored = _replace_run_fixture(
        repository,
        resumed.model_copy(update={"interaction_expires_at": restored_expiry}),
    )
    assert restored.paused_state is not None
    assert restored.interaction_expires_at == restored_expiry
    completed_node = running_node.model_copy(
        update={
            "status": SkillPlanNodeStatus.COMPLETED,
            "completed_at": paused_at,
        }
    )

    transitioned = repository.transition_skill_plan_node(
        plan_id=running_plan.id,
        run_id=run.id,
        node=completed_node,
        expected_statuses={SkillPlanNodeStatus.RUNNING},
        event_type="node_completed",
        event_payload={"plan_id": running_plan.id, "node_id": completed_node.id},
        clear_run_paused_state=True,
    )

    assert transitioned is not None
    cleared = repository.get_agent_run(run.id)
    assert cleared is not None
    assert cleared.paused_state is None
    assert cleared.interaction_expires_at is None
    assert cleared.deepsearch_budget == run.deepsearch_budget


def test_standard_generic_plan_write_paths_remain_available(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "standard-generic-plan-writes.sqlite3")
    run = repository.save_agent_run(
        AgentRun(
            id="run_standard_generic_writes",
            thread_id="thread_standard_generic_writes",
            user_id="user_standard_generic_writes",
            workspace_id="workspace_standard_generic_writes",
            project_id="project_standard_generic_writes",
            input_text="Run a standard plan",
            status=AgentRunStatus.WAITING_PLAN_APPROVAL,
        )
    )
    plan = repository.save_skill_plan(
        SkillPlan(
            id="plan_standard_generic_writes",
            run_id=run.id,
            status=SkillPlanStatus.WAITING_APPROVAL,
            intent=SkillIntent(goal=run.input_text),
        )
    )
    run.plan_id = plan.id
    repository.save_agent_run(run)
    assert repository.compare_and_swap_skill_plan(
        plan.model_copy(deep=True),
        expected_version=plan.version,
    )

    transition = repository.transition_skill_plan_and_run(
        plan_id=plan.id,
        run_id=run.id,
        expected_version=plan.version + 1,
        expected_plan_status=SkillPlanStatus.WAITING_APPROVAL,
        expected_run_status=AgentRunStatus.WAITING_PLAN_APPROVAL,
        next_plan_status=SkillPlanStatus.APPROVED,
        next_run_status=AgentRunStatus.RUNNING,
        events=[("plan_approved", {"plan_id": plan.id})],
    )

    assert transition is not None
    approved_plan, running_run = transition
    assert approved_plan.status is SkillPlanStatus.APPROVED
    assert running_run.status is AgentRunStatus.RUNNING


def test_standard_execution_claim_does_not_require_a_deepsearch_snapshot(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "standard-execution-claim.sqlite3")
    run = repository.save_agent_run(
        AgentRun(
            id="run_standard_execution_claim",
            thread_id="thread_standard_execution_claim",
            user_id="user_standard_execution_claim",
            workspace_id="workspace_standard_execution_claim",
            project_id="project_standard_execution_claim",
            input_text="Run a standard plan",
            status=AgentRunStatus.RUNNING,
        )
    )
    plan = repository.save_skill_plan(
        SkillPlan(
            id="plan_standard_execution_claim",
            run_id=run.id,
            status=SkillPlanStatus.APPROVED,
            intent=SkillIntent(goal=run.input_text),
        )
    )

    claimed = repository.claim_skill_plan_for_execution(plan.id, run.id)

    assert claimed is not None
    assert claimed.status is SkillPlanStatus.RUNNING
