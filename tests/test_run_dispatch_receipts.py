from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from agents.testing import ScriptedModel, assistant_message

import agentmesh.agent_runtime.service as runtime_service_module
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.agent_runtime.settings import SkillOrchestrationMode
from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.models import (
    AgentPlanningContractVersion,
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    ChatThread,
    DeepSearchBudgetV1,
    RunDispatchReceiptV1,
    RunDispatchState,
    SkillIntent,
    SkillOrchestrationRequestMode,
    SkillPlan,
    SkillPlanStatus,
)
from agentmesh.runtime_capacity import RuntimeCapacityController
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.skill_runtime.executor import PlanExecutionOutcome
from agentmesh.store import SQLiteStore


def _run() -> AgentRun:
    return AgentRun(
        id="run_dispatch_test",
        thread_id="thread_dispatch_test",
        user_id="usr_test",
        workspace_id="ws_test",
        project_id="prj_test",
        input_text="dispatch me",
        client_turn_id="turn_dispatch_test",
        status=AgentRunStatus.PLANNING,
    )


def _receipt(run_id: str) -> RunDispatchReceiptV1:
    identity = {
        "run_id": run_id,
        "operation_kind": "standard_plan",
        "generation": 1,
    }
    return RunDispatchReceiptV1(
        operation_key="dispatch:" + canonical_json_sha256(identity),
        run_id=run_id,
        operation_kind="standard_plan",
        generation=1,
    )


def test_dispatch_table_has_required_unique_and_cursor_indexes(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "dispatch-indexes.sqlite3")
    with repository._connect() as connection:
        indexes = {
            row["name"]: row["sql"]
            for row in connection.execute(
                """
                SELECT name, sql FROM sqlite_master
                WHERE type = 'index' AND tbl_name = 'run_dispatch_receipts'
                """
            ).fetchall()
        }

    assert "idx_run_dispatch_one_active" in indexes
    assert "WHERE state IN ('pending', 'started')" in indexes[
        "idx_run_dispatch_one_active"
    ]
    assert "idx_run_dispatch_state_cursor" in indexes
    assert "idx_run_dispatch_run_state" in indexes


def test_run_and_pending_dispatch_are_claimed_atomically_and_replay_is_read_only(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "dispatch.sqlite3")
    run = _run()
    receipt = _receipt(run.id)

    created, claimed = repository.claim_new_agent_run(run, dispatch=receipt)
    replayed, replay_claimed = repository.claim_new_agent_run(run, dispatch=receipt)

    assert claimed is True
    assert replay_claimed is False
    assert replayed.id == created.id
    assert repository.list_pending_run_dispatches() == [receipt]
    inventory = repository.universal_quiesce_inventory()
    assert inventory.active_dispatch_operation_keys == (receipt.operation_key,)
    assert inventory.run_ids == (run.id,)


def test_dispatch_has_one_cas_winner_and_requires_same_epoch_to_settle(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "dispatch-cas.sqlite3")
    run = _run()
    receipt = _receipt(run.id)
    repository.claim_new_agent_run(run, dispatch=receipt)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda epoch: repository.claim_run_dispatch(
                    receipt.operation_key,
                    process_epoch=epoch,
                ),
                ["epoch-a", "epoch-b"],
            )
        )

    winners = [item for item in results if item is not None]
    assert len(winners) == 1
    winner = winners[0]
    assert winner.state is RunDispatchState.STARTED
    loser_epoch = "epoch-b" if winner.process_epoch == "epoch-a" else "epoch-a"
    assert repository.settle_run_dispatch(
        receipt.operation_key,
        process_epoch=loser_epoch,
    ) is None
    settled = repository.settle_run_dispatch(
        receipt.operation_key,
        process_epoch=winner.process_epoch or "",
    )
    assert settled is not None and settled.state is RunDispatchState.SETTLED
    assert repository.list_pending_run_dispatches() == []


def test_approval_hands_off_started_planning_dispatch_atomically(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "dispatch-approval-handoff.sqlite3")
    run = _run().model_copy(update={"status": AgentRunStatus.WAITING_PLAN_APPROVAL})
    planning = _receipt(run.id)
    repository.claim_new_agent_run(run, dispatch=planning)
    repository.claim_run_dispatch(planning.operation_key, process_epoch="planner")
    plan = repository.save_skill_plan(
        SkillPlan(
            id="plan_dispatch_handoff",
            run_id=run.id,
            status=SkillPlanStatus.WAITING_APPROVAL,
            intent=SkillIntent(goal="approve safely"),
        )
    )
    execution = RunDispatchReceiptV1(
        operation_key="dispatch:"
        + canonical_json_sha256(
            {
                "run_id": run.id,
                "operation_kind": "approved_plan",
                "generation": 1,
            }
        ),
        run_id=run.id,
        operation_kind="approved_plan",
    )

    transition = repository.transition_skill_plan_and_run(
        plan_id=plan.id,
        run_id=run.id,
        expected_version=plan.version,
        expected_plan_status=SkillPlanStatus.WAITING_APPROVAL,
        expected_run_status=AgentRunStatus.WAITING_PLAN_APPROVAL,
        next_plan_status=SkillPlanStatus.APPROVED,
        next_run_status=AgentRunStatus.RUNNING,
        events=[("plan_approved", {"plan_id": plan.id})],
        dispatch=execution,
    )

    assert transition is not None
    assert repository.get_run_dispatch(planning.operation_key).state is RunDispatchState.SETTLED  # type: ignore[union-attr]
    assert repository.get_run_dispatch(execution.operation_key).state is RunDispatchState.PENDING  # type: ignore[union-attr]


def test_immediate_approval_queues_execution_until_planning_task_exits(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        runtime_service_module,
        "skill_orchestration_mode",
        lambda: SkillOrchestrationMode.EXECUTE,
    )
    repository = SQLiteStore(tmp_path / "dispatch-approval-barrier.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    thread = repository.add_chat_thread(
        ChatThread(
            id="thread_dispatch_approval_barrier",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="Approval barrier",
        )
    )
    run = AgentRun(
        id="run_dispatch_approval_barrier",
        thread_id=thread.id,
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        input_text="approve immediately",
        client_turn_id="turn_dispatch_approval_barrier",
        status=AgentRunStatus.WAITING_PLAN_APPROVAL,
        orchestration_mode="execute",
    )
    planning = _receipt(run.id)
    repository.claim_new_agent_run(run, dispatch=planning)
    runtime = AgentRuntimeService(
        repository=repository,
        model=ScriptedModel([]),
        enabled=True,
    )
    repository.claim_run_dispatch(
        planning.operation_key,
        process_epoch=runtime._process_epoch,
    )
    plan = repository.save_skill_plan(
        SkillPlan(
            id="plan_dispatch_approval_barrier",
            run_id=run.id,
            status=SkillPlanStatus.WAITING_APPROVAL,
            intent=SkillIntent(goal="approve immediately"),
        )
    )
    execution = runtime.new_dispatch_receipt(run.id, "approved_plan")
    transition = repository.transition_skill_plan_and_run(
        plan_id=plan.id,
        run_id=run.id,
        expected_version=plan.version,
        expected_plan_status=SkillPlanStatus.WAITING_APPROVAL,
        expected_run_status=AgentRunStatus.WAITING_PLAN_APPROVAL,
        next_plan_status=SkillPlanStatus.APPROVED,
        next_run_status=AgentRunStatus.RUNNING,
        events=[("plan_approved", {"plan_id": plan.id})],
        dispatch=execution,
    )
    assert transition is not None
    approved_plan, approved_run = transition

    async def scenario() -> None:
        planning_released = asyncio.Event()
        planning_task = asyncio.create_task(planning_released.wait())
        runtime._tasks[run.id] = planning_task
        planning_task.add_done_callback(
            lambda completed: runtime._finish_background_task(
                run.id,
                completed,
                dispatch_operation_key=planning.operation_key,
            )
        )

        async def execute(
            *,
            plan: SkillPlan,
            run: AgentRun,
            user: object,
            resume: bool = False,
        ) -> PlanExecutionOutcome:
            del user, resume
            terminal_plan = plan.model_copy(update={"status": SkillPlanStatus.COMPLETED})
            terminal_run = run.model_copy(
                update={
                    "status": AgentRunStatus.COMPLETED,
                    "output_text": "approved execution completed",
                }
            )
            persisted = repository.finish_skill_plan_and_run(
                plan=terminal_plan,
                run=terminal_run,
                expected_plan_statuses={SkillPlanStatus.APPROVED},
                expected_run_statuses={AgentRunStatus.RUNNING},
                events=[("run_completed", {"plan_id": plan.id})],
            )
            assert persisted is not None
            return PlanExecutionOutcome(plan=persisted[0], run=persisted[1])

        runtime._execute_approved_skill_plan = execute  # type: ignore[method-assign]
        queued = await runtime.start_approved_skill_plan(
            approved_plan.id,
            user=USER,
            dispatch_receipt=execution,
        )
        assert queued.id == run.id
        assert repository.get_run_dispatch(execution.operation_key).state is RunDispatchState.PENDING  # type: ignore[union-attr]

        await runtime.start_dispatch_pump()
        planning_released.set()
        try:
            for _ in range(200):
                current = repository.get_run_dispatch(execution.operation_key)
                if current is not None and current.state is RunDispatchState.SETTLED:
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("approved dispatch remained pending")
        finally:
            await runtime.stop_dispatch_pump()

    asyncio.run(scenario())
    assert repository.get_agent_run(run.id).status is AgentRunStatus.COMPLETED  # type: ignore[union-attr]


def test_pending_dispatch_survives_orphan_reconciliation(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "dispatch-pending-reconcile.sqlite3")
    run = _run()
    receipt = _receipt(run.id)
    repository.claim_new_agent_run(run, dispatch=receipt)

    assert repository.reconcile_orphaned_agent_runs() == 0
    assert repository.get_agent_run(run.id).status is AgentRunStatus.PLANNING  # type: ignore[union-attr]
    assert repository.get_run_dispatch(receipt.operation_key).state is RunDispatchState.PENDING  # type: ignore[union-attr]


def test_started_standard_dispatch_fails_closed_and_settles_on_restart(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "dispatch-started-reconcile.sqlite3")
    run = _run()
    receipt = _receipt(run.id)
    repository.claim_new_agent_run(run, dispatch=receipt)
    repository.claim_run_dispatch(receipt.operation_key, process_epoch="old-process")

    assert repository.reconcile_run_dispatches_for_startup() == 0
    assert repository.reconcile_orphaned_agent_runs() == 1

    stored_run = repository.get_agent_run(run.id)
    stored_receipt = repository.get_run_dispatch(receipt.operation_key)
    assert stored_run is not None and stored_run.status is AgentRunStatus.FAILED
    assert stored_receipt is not None and stored_receipt.state is RunDispatchState.PENDING


def test_started_deepsearch_dispatch_resets_to_pending_for_checkpoint_recovery(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "dispatch-deepsearch-reconcile.sqlite3")
    created_at = _run().created_at
    run = AgentRun(
        id="run_dispatch_deepsearch",
        thread_id="thread_dispatch_deepsearch",
        user_id="usr_test",
        workspace_id="ws_test",
        project_id="prj_test",
        input_text="research",
        client_turn_id="turn_dispatch_deepsearch",
        status=AgentRunStatus.PLANNING,
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        planning_contract_version=AgentPlanningContractVersion.DEEPSEARCH_FROZEN_V2,
        orchestration_mode="execute",
        requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
        absolute_expires_at=created_at + timedelta(days=7),
        deepsearch_budget=DeepSearchBudgetV1(),
        created_at=created_at,
        updated_at=created_at,
    )
    receipt = RunDispatchReceiptV1(
        operation_key="dispatch:"
        + canonical_json_sha256(
            {
                "run_id": run.id,
                "operation_kind": "deepsearch_plan",
                "generation": 1,
            }
        ),
        run_id=run.id,
        operation_kind="deepsearch_plan",
    )
    repository.claim_new_agent_run(run, dispatch=receipt)
    repository.claim_run_dispatch(receipt.operation_key, process_epoch="old-process")

    assert repository.reconcile_run_dispatches_for_startup() == 1
    assert repository.reconcile_orphaned_agent_runs() == 0

    stored = repository.get_run_dispatch(receipt.operation_key)
    assert stored is not None and stored.state is RunDispatchState.PENDING
    assert stored.process_epoch is None


def test_terminal_started_dispatch_repairs_status_projection_after_restart(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "dispatch-terminal-projection.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    run = _run().model_copy(
        update={
            "id": "run_terminal_dispatch",
            "client_turn_id": "turn_terminal_dispatch",
            "status": AgentRunStatus.FAILED,
            "error_code": "process_restarted",
        }
    )
    receipt = _receipt(run.id).model_copy(
        update={
            "operation_key": "dispatch:"
            + canonical_json_sha256(
                {
                    "run_id": run.id,
                    "operation_kind": "standard_plan",
                    "generation": 1,
                }
            )
        }
    )
    repository.claim_new_agent_run(run, dispatch=receipt)
    repository.claim_run_dispatch(receipt.operation_key, process_epoch="old-process")
    assert repository.reconcile_run_dispatches_for_startup() == 1
    runtime = AgentRuntimeService(
        repository=repository,
        model=ScriptedModel([]),
        enabled=True,
    )

    assert asyncio.run(runtime.recover_pending_dispatches()) == 0

    projected = repository.get_run_output_projection(run.id)
    settled = repository.get_run_dispatch(receipt.operation_key)
    assert projected is not None and projected.disposition == "status_only"
    assert settled is not None and settled.state is RunDispatchState.SETTLED


def test_pending_dispatch_is_rescheduled_without_duplicate_user_message(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "dispatch-recover-pending.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    thread = repository.add_chat_thread(
        ChatThread(
            id="thread_dispatch_recover",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="Dispatch recovery",
        )
    )
    run = AgentRun(
        id="run_dispatch_recover",
        thread_id=thread.id,
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        input_text="recover me",
        client_turn_id="turn_dispatch_recover",
        status=AgentRunStatus.RUNNING,
        project_chat=True,
    )
    receipt = RunDispatchReceiptV1(
        operation_key="dispatch:"
        + canonical_json_sha256(
            {
                "run_id": run.id,
                "operation_kind": "standard_direct",
                "generation": 1,
            }
        ),
        run_id=run.id,
        operation_kind="standard_direct",
    )
    repository.claim_new_agent_run(run, dispatch=receipt)
    model = ScriptedModel([[assistant_message("recovered")]])
    runtime = AgentRuntimeService(repository=repository, model=model, enabled=True)

    async def scenario() -> int:
        scheduled = await runtime.recover_pending_dispatches()
        await asyncio.gather(*runtime._tasks.values())
        await asyncio.sleep(0)
        return scheduled

    assert asyncio.run(scenario()) == 1
    assert repository.get_run_dispatch(receipt.operation_key).state is RunDispatchState.SETTLED  # type: ignore[union-attr]
    messages = repository.list_thread_messages(thread.id)
    assert [message.content for message in messages].count("recover me") == 1
    assert any(message.content == "recovered" for message in messages)


def test_pending_planned_dispatch_is_not_claimed_while_orchestration_is_off(
    tmp_path,
    monkeypatch,
) -> None:
    repository = SQLiteStore(tmp_path / "dispatch-off.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    run = _run().model_copy(
        update={
            "user_id": USER.id,
            "workspace_id": USER.workspace_id,
            "project_id": USER.default_project_id,
        }
    )
    receipt = _receipt(run.id)
    repository.claim_new_agent_run(run, dispatch=receipt)
    runtime = AgentRuntimeService(
        repository=repository,
        model=ScriptedModel([]),
        enabled=True,
    )
    monkeypatch.setattr(
        runtime_service_module,
        "skill_orchestration_mode",
        lambda: SkillOrchestrationMode.OFF,
    )

    assert asyncio.run(runtime.recover_pending_dispatches()) == 0
    stored = repository.get_run_dispatch(receipt.operation_key)
    assert stored is not None and stored.state is RunDispatchState.PENDING


def test_pending_standard_plan_dispatch_recovers_in_preview_mode(
    tmp_path,
    monkeypatch,
) -> None:
    repository = SQLiteStore(tmp_path / "dispatch-preview.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    run = _run().model_copy(
        update={
            "user_id": USER.id,
            "workspace_id": USER.workspace_id,
            "project_id": USER.default_project_id,
            "orchestration_mode": SkillOrchestrationMode.PREVIEW.value,
        }
    )
    receipt = _receipt(run.id)
    repository.claim_new_agent_run(run, dispatch=receipt)
    runtime = AgentRuntimeService(
        repository=repository,
        model=ScriptedModel([]),
        enabled=True,
    )
    monkeypatch.setattr(
        runtime_service_module,
        "skill_orchestration_mode",
        lambda: SkillOrchestrationMode.PREVIEW,
    )

    async def complete_preview_plan(**kwargs):  # noqa: ANN003, ANN202
        current = repository.get_agent_run(kwargs["run"].id)
        assert current is not None
        current.status = AgentRunStatus.WAITING_PLAN_APPROVAL
        saved = repository.save_agent_run_with_event(
            current,
            "plan_waiting_approval",
            {"recovered": True},
            expected_statuses={AgentRunStatus.PLANNING},
        )
        assert saved is not None

    runtime._prepare_orchestration = complete_preview_plan  # type: ignore[method-assign]

    async def scenario() -> int:
        scheduled = await runtime.recover_pending_dispatches()
        await asyncio.gather(*runtime._tasks.values())
        await asyncio.sleep(0)
        return scheduled

    assert asyncio.run(scenario()) == 1
    stored = repository.get_run_dispatch(receipt.operation_key)
    assert stored is not None and stored.state is RunDispatchState.SETTLED
    recovered = repository.get_agent_run(run.id)
    assert recovered is not None and recovered.status is AgentRunStatus.WAITING_PLAN_APPROVAL


def test_dispatch_pump_drains_backlog_after_capacity_releases(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "dispatch-pump.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    for suffix in ("one", "two"):
        thread = repository.add_chat_thread(
            ChatThread(
                id=f"thread_dispatch_pump_{suffix}",
                workspace_id=USER.workspace_id,
                project_id=USER.default_project_id,
                user_id=USER.id,
                title=f"Dispatch pump {suffix}",
            )
        )
        run = AgentRun(
            id=f"run_dispatch_pump_{suffix}",
            thread_id=thread.id,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text=f"run {suffix}",
            client_turn_id=f"turn_dispatch_pump_{suffix}",
            status=AgentRunStatus.RUNNING,
            project_chat=True,
        )
        operation_kind = "standard_direct"
        receipt = RunDispatchReceiptV1(
            operation_key="dispatch:"
            + canonical_json_sha256(
                {
                    "run_id": run.id,
                    "operation_kind": operation_kind,
                    "generation": 1,
                }
            ),
            run_id=run.id,
            operation_kind=operation_kind,
        )
        repository.claim_new_agent_run(run, dispatch=receipt)

    runtime = AgentRuntimeService(
        repository=repository,
        model=ScriptedModel(
            [[assistant_message("first")], [assistant_message("second")]]
        ),
        enabled=True,
        capacity=RuntimeCapacityController(
            process_run_limit=1,
            user_run_limit=1,
            node_limit=1,
        ),
    )

    async def scenario() -> None:
        await runtime.start_dispatch_pump()
        try:
            for _ in range(200):
                receipts = [
                    repository.get_latest_run_dispatch(f"run_dispatch_pump_{suffix}")
                    for suffix in ("one", "two")
                ]
                if all(
                    receipt is not None and receipt.state is RunDispatchState.SETTLED
                    for receipt in receipts
                ):
                    return
                await asyncio.sleep(0.01)
            raise AssertionError("dispatch pump did not drain the persisted backlog")
        finally:
            await runtime.stop_dispatch_pump()

    asyncio.run(scenario())
    assert all(
        repository.get_agent_run(f"run_dispatch_pump_{suffix}").status
        is AgentRunStatus.COMPLETED
        for suffix in ("one", "two")
    )


def test_status_only_projection_is_idempotent_and_creates_no_message(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "status-projection.sqlite3")
    run = repository.save_agent_run(
        _run().model_copy(
            update={
                "id": "run_status_projection",
                "client_turn_id": "turn_status_projection",
                "status": AgentRunStatus.FAILED,
                "error_code": "process_restarted",
            }
        )
    )

    first = repository.project_terminal_run_status(
        run_id=run.id,
        skipped_reason="process_restarted",
    )
    replay = repository.project_terminal_run_status(
        run_id=run.id,
        skipped_reason="process_restarted",
    )

    assert replay == first
    assert first.disposition == "status_only"
    assert first.assistant_message_id is None
    assert repository.list_thread_messages(run.thread_id) == []


def test_runtime_settles_dispatch_after_background_completion(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "dispatch-runtime.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    thread = repository.add_chat_thread(
        ChatThread(
            id="thread_dispatch_runtime",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="Dispatch runtime",
        )
    )
    model = ScriptedModel([[assistant_message("done")]])
    runtime = AgentRuntimeService(repository=repository, model=model, enabled=True)

    async def scenario():
        run = await runtime.start(
            content="hello",
            user=USER,
            thread_id=thread.id,
            history=[],
            client_turn_id="turn_dispatch_runtime",
        )
        await runtime._tasks[run.id]
        await asyncio.sleep(0)
        return run

    run = asyncio.run(scenario())
    operation_key = runtime._dispatch_operation_key(run.id, "standard_direct")
    receipt = repository.get_run_dispatch(operation_key)

    assert receipt is not None and receipt.state is RunDispatchState.SETTLED
    assert receipt.attempt_count == 1
    event_types = [event.event_type for event in repository.list_agent_run_events(run.id)]
    assert event_types[:3] == [
        "run_started",
        "run_dispatch_pending",
        "run_dispatch_started",
    ]
    assert "run_dispatch_settled" in event_types
    assert repository.get_agent_run(run.id).status is AgentRunStatus.COMPLETED  # type: ignore[union-attr]
    assert [message.content for message in repository.list_thread_messages(thread.id)].count("hello") == 1
    model.assert_complete()
