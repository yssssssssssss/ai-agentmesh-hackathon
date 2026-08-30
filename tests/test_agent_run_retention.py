from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agentmesh.models import (
    AgentRun,
    AgentRunStatus,
    InboxItem,
    Scope,
    SkillIntent,
    SkillPlan,
    SkillPlanNode,
    SkillPlanNodeStatus,
    SkillPlanStatus,
)
from agentmesh.store import SQLiteStore


def _save_expired_tool_approval(repository: SQLiteStore, *, suffix: str) -> tuple[AgentRun, InboxItem]:
    run = repository.save_agent_run(
        AgentRun(
            id=f"run_expired_tool_{suffix}",
            thread_id=f"thread_expired_tool_{suffix}",
            user_id="user",
            workspace_id="workspace",
            project_id="project",
            input_text="old",
            client_turn_id=f"turn_expired_tool_{suffix}",
            status=AgentRunStatus.WAITING_APPROVAL,
            paused_state={"expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()},
        )
    )
    inbox = repository.add_inbox_item(
        InboxItem(
            id=f"inbox_expired_tool_{suffix}",
            title="Approve tool",
            summary="Waiting",
            item_type="sdk_tool_approval",
            scope=Scope.PRIVATE,
            user_id=run.user_id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            metadata={"run_id": run.id},
        )
    )
    return run, inbox


def test_retention_preserves_stream_events_for_active_runs(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "active-retention.sqlite3")
    run = repository.save_agent_run(
        AgentRun(
            id="run_active_retention",
            thread_id="thread_active_retention",
            user_id="user",
            workspace_id="workspace",
            project_id="project",
            input_text="test",
            status=AgentRunStatus.WAITING_APPROVAL,
            paused_state={"state": "paused"},
        )
    )
    stream = repository.append_agent_run_event(run.id, "sdk_stream_event", {"delta": "old"})
    old = (datetime.now(UTC) - timedelta(days=60)).isoformat()
    with repository._connect() as connection:
        connection.execute("UPDATE agent_run_events SET created_at = ? WHERE id = ?", (old, stream.id))

    assert repository.prune_agent_stream_events(retention_days=30) == 0
    assert repository.list_agent_run_events(run.id)


def test_startup_reconciles_orphaned_running_runs(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "orphaned-run.sqlite3")
    repository.save_agent_run(
        AgentRun(
            id="run_orphaned",
            thread_id="thread_orphaned",
            user_id="user",
            workspace_id="workspace",
            project_id="project",
            input_text="test",
            status=AgentRunStatus.RUNNING,
        )
    )

    assert repository.reconcile_orphaned_agent_runs() == 1
    run = repository.get_agent_run("run_orphaned")
    assert run.status == AgentRunStatus.FAILED
    assert run.error_code == "process_restarted"
    assert repository.list_agent_run_events(run.id)[-1].event_type == "run_failed"


def test_startup_reconciler_never_mutates_historical_research_v2(tmp_path) -> None:  # noqa: ANN001
    repository = SQLiteStore(tmp_path / "research-orphaned-run.sqlite3")
    historical = AgentRun(
        id="run_research_orphaned",
        thread_id="thread_research_orphaned",
        user_id="user",
        workspace_id="workspace",
        project_id="project",
        input_text="test",
        status=AgentRunStatus.RUNNING,
        orchestration_version="research-v2",
    )
    repository.save_agent_run(historical.model_copy(update={"orchestration_version": "v1"}))
    with repository._connect() as connection:
        connection.execute(
            "UPDATE agent_runs SET payload = ?, orchestration_version = ? WHERE id = ?",
            (historical.model_dump_json(), "research-v2", historical.id),
        )

    assert repository.reconcile_orphaned_agent_runs() == 0
    assert repository.get_agent_run(historical.id).status == AgentRunStatus.RUNNING  # type: ignore[union-attr]


def test_startup_reconciles_planning_run_and_related_plan_nodes(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "orphaned-plan.sqlite3")
    run = repository.save_agent_run(
        AgentRun(
            id="run_orphaned_plan",
            thread_id="thread_orphaned_plan",
            user_id="user",
            workspace_id="workspace",
            project_id="project",
            input_text="test",
            status=AgentRunStatus.PLANNING,
        )
    )
    repository.save_skill_plan(
        SkillPlan(
            id="plan_orphaned",
            run_id=run.id,
            status=SkillPlanStatus.RUNNING,
            intent=SkillIntent(goal="test"),
            candidate_skill_ids=["skill"],
            output_contract=["result"],
            nodes=[
                SkillPlanNode(
                    id="node_orphaned",
                    skill_id="skill",
                    skill_version="1",
                    skill_content_hash="hash",
                    reason="test",
                    output_contract=["result"],
                    status=SkillPlanNodeStatus.RUNNING,
                    attempt=1,
                )
            ],
        )
    )

    assert repository.reconcile_orphaned_agent_runs() == 1
    reconciled_run = repository.get_agent_run(run.id)
    reconciled_plan = repository.get_skill_plan("plan_orphaned")
    assert reconciled_run is not None and reconciled_run.status == AgentRunStatus.FAILED
    assert reconciled_plan is not None and reconciled_plan.status == SkillPlanStatus.FAILED
    assert reconciled_plan.nodes[0].status == SkillPlanNodeStatus.FAILED


def test_startup_cancels_expired_plan_approval(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "expired-plan-startup.sqlite3")
    run = repository.save_agent_run(
        AgentRun(
            id="run_expired_plan_startup",
            thread_id="thread_expired_plan_startup",
            user_id="user",
            workspace_id="workspace",
            project_id="project",
            input_text="test",
            status=AgentRunStatus.WAITING_PLAN_APPROVAL,
            deadline_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    repository.save_skill_plan(
        SkillPlan(
            id="plan_expired_startup",
            run_id=run.id,
            status=SkillPlanStatus.WAITING_APPROVAL,
            intent=SkillIntent(goal="test"),
            candidate_skill_ids=["skill"],
            output_contract=["result"],
            nodes=[
                SkillPlanNode(
                    id="node_expired_startup",
                    skill_id="skill",
                    skill_version="1",
                    skill_content_hash="hash",
                    reason="test",
                    output_contract=["result"],
                )
            ],
        )
    )

    assert repository.reconcile_orphaned_agent_runs() == 1
    assert repository.get_agent_run(run.id).status == AgentRunStatus.CANCELLED  # type: ignore[union-attr]
    assert repository.get_skill_plan("plan_expired_startup").status == SkillPlanStatus.CANCELLED  # type: ignore[union-attr]


def test_expired_plan_approval_does_not_block_a_new_thread_run(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "expired-plan-liveness.sqlite3")
    expired = repository.save_agent_run(
        AgentRun(
            id="run_expired_plan_liveness",
            thread_id="thread_expired_plan_liveness",
            user_id="user",
            workspace_id="workspace",
            project_id="project",
            input_text="old",
            client_turn_id="turn_old",
            status=AgentRunStatus.WAITING_PLAN_APPROVAL,
            deadline_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    repository.save_skill_plan(
        SkillPlan(
            id="plan_expired_liveness",
            run_id=expired.id,
            status=SkillPlanStatus.WAITING_APPROVAL,
            intent=SkillIntent(goal="old"),
            candidate_skill_ids=["skill"],
            output_contract=["result"],
            nodes=[
                SkillPlanNode(
                    id="node_expired_liveness",
                    skill_id="skill",
                    skill_version="1",
                    skill_content_hash="hash",
                    reason="test",
                    output_contract=["result"],
                )
            ],
        )
    )
    fresh = AgentRun(
        id="run_fresh_after_expiry",
        thread_id=expired.thread_id,
        user_id=expired.user_id,
        workspace_id=expired.workspace_id,
        project_id=expired.project_id,
        input_text="new",
        client_turn_id="turn_new",
        status=AgentRunStatus.CREATED,
    )

    claimed, created = repository.claim_new_agent_run(fresh)

    assert created is True and claimed.id == fresh.id
    assert repository.get_agent_run(expired.id).status == AgentRunStatus.CANCELLED  # type: ignore[union-attr]
    assert repository.get_skill_plan("plan_expired_liveness").status == SkillPlanStatus.CANCELLED  # type: ignore[union-attr]


def test_startup_cancels_expired_tool_approval_and_resolves_inbox(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "expired-tool-startup.sqlite3")
    run, inbox = _save_expired_tool_approval(repository, suffix="startup")

    assert repository.reconcile_orphaned_agent_runs() == 1
    assert repository.get_agent_run(run.id).status == AgentRunStatus.CANCELLED  # type: ignore[union-attr]
    assert repository.get_inbox_item(inbox.id).status == "resolved"  # type: ignore[union-attr]


def test_expired_tool_approval_does_not_block_a_new_thread_run(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "expired-tool-liveness.sqlite3")
    expired, inbox = _save_expired_tool_approval(repository, suffix="liveness")
    fresh = AgentRun(
        id="run_fresh_after_tool_expiry",
        thread_id=expired.thread_id,
        user_id=expired.user_id,
        workspace_id=expired.workspace_id,
        project_id=expired.project_id,
        input_text="new",
        client_turn_id="turn_fresh_after_tool_expiry",
        status=AgentRunStatus.CREATED,
    )

    claimed, created = repository.claim_new_agent_run(fresh)

    assert created is True and claimed.id == fresh.id
    assert repository.get_agent_run(expired.id).status == AgentRunStatus.CANCELLED  # type: ignore[union-attr]
    assert repository.get_inbox_item(inbox.id).status == "resolved"  # type: ignore[union-attr]


def test_retention_prunes_only_old_stream_deltas(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "retention.sqlite3")
    run = repository.save_agent_run(
        AgentRun(
            id="run_retention",
            thread_id="thread_retention",
            user_id="user",
            workspace_id="workspace",
            project_id="project",
            input_text="test",
            status=AgentRunStatus.COMPLETED,
        )
    )
    stream = repository.append_agent_run_event(run.id, "sdk_stream_event", {"delta": "old"})
    completed = repository.append_agent_run_event(run.id, "run_completed", {})
    old = (datetime.now(UTC) - timedelta(days=60)).isoformat()
    with repository._connect() as connection:  # test-only age fixture
        connection.execute(
            "UPDATE agent_run_events SET created_at = ? WHERE id IN (?, ?)",
            (old, stream.id, completed.id),
        )

    deleted = repository.prune_agent_stream_events(retention_days=30)

    assert deleted == 1
    assert [event.event_type for event in repository.list_agent_run_events(run.id)] == ["run_completed"]
