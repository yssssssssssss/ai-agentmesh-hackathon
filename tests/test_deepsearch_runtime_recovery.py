from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from agents.testing import ScriptedModel

import agentmesh.agent_runtime.service as runtime_service_module
import agentmesh.store as store_module
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.agent_runtime.settings import SkillOrchestrationMode
from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.deepsearch.budget import DeepSearchBudgetMeter
from agentmesh.deepsearch.contracts import (
    DeepSearchStateResponse,
    RequirementPayloadV1,
    RequirementScopeV1,
    RequirementSuccessCriterionV1,
    RequirementVersionV1,
    requirement_content_hash,
)
from agentmesh.deepsearch.service import DeepSearchRequirementIntegrityError
from agentmesh.models import (
    AgentRun,
    AgentRunStatus,
    ChatThread,
    DeepSearchBudgetUsageV1,
    RunDispatchReceiptV1,
    RunDispatchState,
    SkillPlan,
    SkillPlanNodeStatus,
)
from agentmesh.skill_runtime.executor import PlanExecutionOutcome
from agentmesh.store import SQLiteStore
from tests.test_deepsearch_plan_execution_claim import (
    NOW,
    _prepare_approved_plan,
    _prepare_waiting_plan,
    _run,
    _seed_runtime,
)


@pytest.fixture(autouse=True)
def _enable_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runtime_service_module,
        "skill_orchestration_mode",
        lambda: SkillOrchestrationMode.EXECUTE,
    )
    monkeypatch.setattr(store_module, "now_utc", lambda: NOW)


class _PlanningService:
    def __init__(self, repository: SQLiteStore) -> None:
        self.repository = repository
        self.calls: list[str] = []

    async def resume_planning(self, run: AgentRun) -> DeepSearchStateResponse:
        self.calls.append(run.id)
        requirement = self.repository.get_active_deepsearch_requirement(run.id)
        if requirement is None:
            raise DeepSearchRequirementIntegrityError(
                "planning requires an active DeepSearch Requirement"
            )
        return DeepSearchStateResponse(run=run, active_requirement=requirement)


def _runtime(
    repository: SQLiteStore,
    planning_service: _PlanningService,
) -> AgentRuntimeService:
    return AgentRuntimeService(
        repository,
        model=ScriptedModel([]),
        enabled=True,
        deepsearch_planning_service=planning_service,
    )


def _prepare_planning_run(
    repository: SQLiteStore,
    *,
    run_id: str,
    with_requirement: bool,
) -> AgentRun:
    _seed_runtime(repository)
    repository.add_chat_thread(
        ChatThread(
            id=f"thread_{run_id}",
            workspace_id="workspace_deepsearch_execution_claim",
            project_id="project_deepsearch_execution_claim",
            user_id="user_deepsearch_execution_claim",
            title="DeepSearch recovery",
        )
    )
    run, created = repository.claim_new_agent_run(_run(run_id))
    assert created is True
    if not with_requirement:
        return run

    payload = RequirementPayloadV1(
        goal=run.input_text,
        scope=RequirementScopeV1(regions=["China"]),
        success_criteria=[
            RequirementSuccessCriterionV1(
                id="criterion_recovery",
                statement="Recover the persisted research requirement",
            )
        ],
        deliverables=["Research report"],
    )
    requirement = RequirementVersionV1(
        id=f"requirement_{run.id}_v1",
        run_id=run.id,
        version=1,
        request_key=run.client_turn_id or f"turn_{run.id}",
        request_hash=run.create_request_hash or "a" * 64,
        content_hash=requirement_content_hash(payload),
        payload=payload,
        created_at=NOW,
    )
    committed = repository.append_deepsearch_requirement_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        requirement=requirement.model_dump(mode="json"),
        expected_requirement_version=None,
        expected_run_status=AgentRunStatus.PLANNING,
        next_run_status=AgentRunStatus.PLANNING,
        events=[],
        checked_at=NOW,
    )
    assert committed is not None
    return committed.run


def _record_executor(runtime: AgentRuntimeService) -> list[tuple[SkillPlan, AgentRun, bool]]:
    calls: list[tuple[SkillPlan, AgentRun, bool]] = []

    async def execute(
        *,
        plan: SkillPlan,
        run: AgentRun,
        user: object,
        resume: bool = False,
    ) -> PlanExecutionOutcome:
        del user
        calls.append((plan.model_copy(deep=True), run.model_copy(deep=True), resume))
        return PlanExecutionOutcome(plan=plan, run=run)

    runtime._execute_approved_skill_plan = execute  # type: ignore[method-assign]
    return calls


def test_recover_planning_run_resumes_from_persisted_requirement(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-recover-planning.sqlite3")
    run = _prepare_planning_run(
        repository,
        run_id="run_recover_planning",
        with_requirement=True,
    )
    planning = _PlanningService(repository)
    runtime = _runtime(repository, planning)
    wakeups = 0

    def wake_recovery() -> None:
        nonlocal wakeups
        wakeups += 1

    runtime.set_deepsearch_recovery_wakeup(wake_recovery)

    recovered = asyncio.run(runtime.recover_deepsearch_run(run.id))

    assert planning.calls == [run.id]
    assert recovered is not None
    assert recovered.id == run.id
    assert wakeups == 1


def test_recover_planning_run_without_requirement_fails_closed(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-recover-missing-requirement.sqlite3")
    run = _prepare_planning_run(
        repository,
        run_id="run_recover_missing_requirement",
        with_requirement=False,
    )
    planning = _PlanningService(repository)
    runtime = _runtime(repository, planning)
    reserved = DeepSearchBudgetMeter(repository).reserve(
        run_id=run.id,
        expected_budget_version=1,
        logical_operation_key="planning:interrupted",
        invocation_key="planning:interrupted:attempt:1",
        physical_attempt=1,
        resource_maxima=DeepSearchBudgetUsageV1(active_seconds=10, llm_calls=1, tokens=100),
    )

    recovered = asyncio.run(runtime.recover_deepsearch_run(run.id))

    assert planning.calls == [run.id]
    assert recovered is not None
    assert recovered.status is AgentRunStatus.FAILED
    assert recovered.error_code == "deepsearch_recovery_state_invalid"
    assert recovered.deepsearch_budget is not None
    assert recovered.deepsearch_budget.version == reserved.budget.version + 1
    assert recovered.deepsearch_budget.reservations[0].status == "settled"
    assert (
        recovered.deepsearch_budget.reservations[0].actual_usage
        == reserved.reservation.resource_maxima
    )
    assert repository.get_skill_plan_for_run(run.id) is None


def test_recover_approved_plan_enters_executor_as_a_new_claim(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-recover-approved.sqlite3")
    run, plan, _snapshot, _grant = _prepare_approved_plan(
        repository,
        run_id="run_recover_approved",
    )
    runtime = _runtime(repository, _PlanningService(repository))
    calls = _record_executor(runtime)

    asyncio.run(runtime.recover_deepsearch_run(run.id))

    assert len(calls) == 1
    called_plan, called_run, resume = calls[0]
    assert called_plan.id == plan.id
    assert called_run.id == run.id
    assert resume is False


def test_recover_running_plan_with_ready_node_resumes_existing_claim(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-recover-ready.sqlite3")
    run, plan, _snapshot, _grant = _prepare_approved_plan(
        repository,
        run_id="run_recover_ready",
    )
    running = repository.claim_skill_plan_for_execution(plan.id, run.id)
    assert running is not None
    ready = running.nodes[0].model_copy(update={"status": SkillPlanNodeStatus.READY})
    assert repository.transition_skill_plan_node(
        plan_id=running.id,
        run_id=run.id,
        node=ready,
        expected_statuses={SkillPlanNodeStatus.PENDING},
        event_type="node_ready",
        event_payload={"plan_id": running.id, "node_id": ready.id},
    ) is not None
    runtime = _runtime(repository, _PlanningService(repository))
    calls = _record_executor(runtime)

    asyncio.run(runtime.recover_deepsearch_run(run.id))

    assert len(calls) == 1
    called_plan, _called_run, resume = calls[0]
    assert called_plan.nodes[0].status is SkillPlanNodeStatus.READY
    assert resume is True


def test_recover_running_plan_uses_checkpoint_path_for_restarted_dispatch(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-recover-dispatch.sqlite3")
    run, plan, _snapshot, _grant = _prepare_approved_plan(
        repository,
        run_id="run_recover_dispatch",
    )
    receipt = RunDispatchReceiptV1(
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
    with repository._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        repository._insert_run_dispatch_in_transaction(connection, receipt)
    repository.claim_run_dispatch(receipt.operation_key, process_epoch="old-process")
    running = repository.claim_skill_plan_for_execution(plan.id, run.id)
    assert running is not None
    ready = running.nodes[0].model_copy(update={"status": SkillPlanNodeStatus.READY})
    assert repository.transition_skill_plan_node(
        plan_id=running.id,
        run_id=run.id,
        node=ready,
        expected_statuses={SkillPlanNodeStatus.PENDING},
        event_type="node_ready",
        event_payload={"plan_id": running.id, "node_id": ready.id},
    ) is not None
    assert repository.reconcile_run_dispatches_for_startup() == 1
    runtime = _runtime(repository, _PlanningService(repository))
    calls: list[tuple[SkillPlan, AgentRun, bool]] = []

    async def execute(
        *,
        plan: SkillPlan,
        run: AgentRun,
        user: object,
        resume: bool = False,
    ) -> PlanExecutionOutcome:
        del user
        calls.append((plan.model_copy(deep=True), run.model_copy(deep=True), resume))
        terminal = repository.fail_deepsearch_recovery_state(
            run_id=run.id,
            error_code="test_recovered",
        )
        assert terminal is not None
        return PlanExecutionOutcome(
            plan=repository.get_skill_plan(plan.id) or plan,
            run=terminal,
        )

    runtime._execute_approved_skill_plan = execute  # type: ignore[method-assign]

    asyncio.run(runtime.recover_deepsearch_run(run.id))

    assert len(calls) == 1 and calls[0][2] is True
    settled = repository.get_run_dispatch(receipt.operation_key)
    assert settled is not None and settled.state is RunDispatchState.SETTLED
    assert settled.attempt_count == 2
    assert repository.get_run_output_projection(run.id) is not None


def test_recover_orphaned_running_node_marks_unknown_before_resume(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-recover-running-node.sqlite3")
    run, plan, _snapshot, _grant = _prepare_approved_plan(
        repository,
        run_id="run_recover_running_node",
    )
    running = repository.claim_skill_plan_for_execution(plan.id, run.id)
    assert running is not None
    ready = running.nodes[0].model_copy(update={"status": SkillPlanNodeStatus.READY})
    assert repository.transition_skill_plan_node(
        plan_id=running.id,
        run_id=run.id,
        node=ready,
        expected_statuses={SkillPlanNodeStatus.PENDING},
        event_type="node_ready",
        event_payload={"plan_id": running.id, "node_id": ready.id},
    ) is not None
    claimed = repository.claim_skill_plan_node(running.id, ready.id)
    assert claimed is not None
    runtime = _runtime(repository, _PlanningService(repository))
    calls = _record_executor(runtime)

    asyncio.run(runtime.recover_deepsearch_run(run.id))

    assert len(calls) == 1
    called_plan, _called_run, resume = calls[0]
    assert resume is True
    assert called_plan.nodes[0].status is SkillPlanNodeStatus.FAILED
    assert called_plan.nodes[0].error_code == "external_outcome_unknown"


def test_recover_all_terminal_nodes_reenters_executor_for_finalization(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-recover-finalizer.sqlite3")
    run, plan, _snapshot, _grant = _prepare_approved_plan(
        repository,
        run_id="run_recover_finalizer",
    )
    running = repository.claim_skill_plan_for_execution(plan.id, run.id)
    assert running is not None
    failed = running.nodes[0].model_copy(
        update={
            "status": SkillPlanNodeStatus.FAILED,
            "error_code": "source_unavailable",
            "completed_at": NOW + timedelta(minutes=1),
        }
    )
    assert repository.transition_skill_plan_node(
        plan_id=running.id,
        run_id=run.id,
        node=failed,
        expected_statuses={SkillPlanNodeStatus.PENDING},
        event_type="node_failed",
        event_payload={"plan_id": running.id, "node_id": failed.id},
    ) is not None
    runtime = _runtime(repository, _PlanningService(repository))
    calls = _record_executor(runtime)

    asyncio.run(runtime.recover_deepsearch_run(run.id))

    assert len(calls) == 1
    called_plan, _called_run, resume = calls[0]
    assert all(
        node.status
        in {
            SkillPlanNodeStatus.COMPLETED,
            SkillPlanNodeStatus.FAILED,
            SkillPlanNodeStatus.SKIPPED,
            SkillPlanNodeStatus.CANCELLED,
        }
        for node in called_plan.nodes
    )
    assert resume is True


def test_recover_deduplicates_an_already_active_run(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-recover-deduplicated.sqlite3")
    run, _plan, _snapshot, _grant = _prepare_approved_plan(
        repository,
        run_id="run_recover_deduplicated",
    )
    runtime = _runtime(repository, _PlanningService(repository))
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def execute(
        *,
        plan: SkillPlan,
        run: AgentRun,
        user: object,
        resume: bool = False,
    ) -> PlanExecutionOutcome:
        nonlocal calls
        del user, resume
        calls += 1
        started.set()
        await release.wait()
        return PlanExecutionOutcome(plan=plan, run=run)

    runtime._execute_approved_skill_plan = execute  # type: ignore[method-assign]

    async def exercise() -> tuple[AgentRun | None, AgentRun | None]:
        first = asyncio.create_task(runtime.recover_deepsearch_run(run.id))
        await started.wait()
        second_result = await runtime.recover_deepsearch_run(run.id)
        release.set()
        return await first, second_result

    first_result, second_result = asyncio.run(exercise())

    assert calls == 1
    assert first_result is not None and first_result.id == run.id
    assert second_result is not None and second_result.id == run.id


def test_recover_waiting_state_does_not_restart_planning_or_execution(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-recover-waiting.sqlite3")
    run, plan, _snapshot, _grant = _prepare_waiting_plan(
        repository,
        run_id="run_recover_waiting",
    )
    planning = _PlanningService(repository)
    runtime = _runtime(repository, planning)
    calls = _record_executor(runtime)

    recovered = asyncio.run(runtime.recover_deepsearch_run(run.id))

    assert recovered == run
    assert planning.calls == []
    assert calls == []
    assert repository.get_skill_plan(plan.id) == plan


def test_recover_does_not_compute_when_server_execution_mode_is_disabled(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-recover-preview-mode.sqlite3")
    run = _prepare_planning_run(
        repository,
        run_id="run_recover_preview_mode",
        with_requirement=True,
    )
    planning = _PlanningService(repository)
    runtime = _runtime(repository, planning)
    monkeypatch.setattr(
        runtime_service_module,
        "skill_orchestration_mode",
        lambda: SkillOrchestrationMode.PREVIEW,
    )

    recovered = asyncio.run(runtime.recover_deepsearch_run(run.id))

    assert recovered == run
    assert planning.calls == []
