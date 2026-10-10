from datetime import UTC, datetime

import pytest
from test_automation_schedules import schedule_project as schedule_project

from agentmesh.automation.schedules import ScheduleDefinitionService
from agentmesh.models import AgentRunStatus, ScheduledAgentTaskCreateRequest, ScheduledAgentTaskUpdateRequest


def _definition(repository, user):
    return ScheduleDefinitionService(repository, clock=lambda: datetime(2026, 10, 4, 0, tzinfo=UTC)).create(
        ScheduledAgentTaskCreateRequest(
            command_id="definition",
            project_id=user.default_project_id,
            template_id="daily_progress",
            title="Daily inspection",
            schedule="30 9 * * *",
        ),
        user,
    )


def test_one_due_slot_atomically_creates_an_occurrence_run_and_dispatch(schedule_project, monkeypatch):
    from agentmesh.automation.coordinator import AutomationCoordinator

    repository, user = schedule_project
    definition = _definition(repository, user)
    monkeypatch.setenv("AGENTMESH_AUTOMATION_MODE", "execute")
    coordinator = AutomationCoordinator(repository, runtime_available=lambda: True)
    result = coordinator.tick(datetime(2026, 10, 4, 1, 30, tzinfo=UTC))
    assert len(result.occurrences) == 1
    occurrence = result.occurrences[0]
    assert occurrence.schedule_id == definition.id
    assert occurrence.definition_version == 1
    assert occurrence.local_slot == "Asia/Shanghai:2026-10-04T09:30"
    assert occurrence.budget == definition.budget
    run = repository.get_agent_run(occurrence.run_id)
    assert run.user_id == user.id
    assert run.orchestration_version == "v1"
    assert run.task_id is None
    assert run.execution_location == "server"
    dispatch = repository.get_latest_run_dispatch(run.id)
    assert dispatch.operation_kind == "project_inspection"
    assert dispatch.payload["occurrence_id"] == occurrence.id
    assert repository.get_scheduled_agent_task_definition(definition.id).next_run_at == datetime(
        2026,
        10,
        5,
        1,
        30,
        tzinfo=UTC,
    )
    assert not coordinator.tick(datetime(2026, 10, 4, 1, 30, tzinfo=UTC)).occurrences


def test_observe_explains_current_owner_revocation_without_writing_an_occurrence(schedule_project, monkeypatch):
    from agentmesh.automation.coordinator import AutomationCoordinator

    repository, user = schedule_project
    definition = _definition(repository, user)
    repository.save_user(user.model_copy(update={"status": "disabled"}))
    monkeypatch.setenv("AGENTMESH_AUTOMATION_MODE", "observe")
    observed = AutomationCoordinator(repository, runtime_available=lambda: True).tick(
        datetime(2026, 10, 4, 1, 30, tzinfo=UTC),
    )
    assert observed.due[0].blocked_reason == "schedule_actor_not_authorized"
    assert observed.occurrences == []
    assert repository.get_scheduled_agent_task_definition(definition.id) == definition
    assert not repository.list_agent_runs()


@pytest.mark.parametrize("mode", [None, "invalid", "off", "observe"])
def test_off_and_observe_never_write_runs_receipts_or_schedule_watermarks(schedule_project, monkeypatch, mode):
    from agentmesh.automation.coordinator import AutomationCoordinator

    repository, user = schedule_project
    definition = _definition(repository, user)
    if mode is None:
        monkeypatch.delenv("AGENTMESH_PROFILE", raising=False)
        monkeypatch.delenv("AGENTMESH_AUTOMATION_MODE", raising=False)
    else:
        monkeypatch.setenv("AGENTMESH_AUTOMATION_MODE", mode)
    result = AutomationCoordinator(repository, runtime_available=lambda: True).tick(
        datetime(2026, 10, 5, 2, tzinfo=UTC),
    )
    assert len(result.due) == (1 if mode == "observe" else 0)
    assert result.occurrences == []
    assert not repository.list_agent_runs()
    assert not repository.list_pending_run_dispatches()
    assert not repository.inbox_items
    assert repository.get_scheduled_agent_task_definition(definition.id) == definition
    with repository._connect() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM records WHERE collection='scheduled_occurrences'").fetchone()[0]
            == 0
        )


def test_missed_slots_coalesce_and_a_running_inspection_skips_overlap(schedule_project, monkeypatch):
    from agentmesh.automation.coordinator import AutomationCoordinator

    repository, user = schedule_project
    definition = _definition(repository, user)
    monkeypatch.setenv("AGENTMESH_AUTOMATION_MODE", "execute")
    coordinator = AutomationCoordinator(repository, runtime_available=lambda: True)
    latest = coordinator.tick(datetime(2026, 10, 7, 2, tzinfo=UTC)).occurrences
    assert len(latest) == 1
    assert latest[0].scheduled_at == datetime(2026, 10, 7, 1, 30, tzinfo=UTC)
    overlap = coordinator.tick(datetime(2026, 10, 8, 2, tzinfo=UTC)).occurrences
    assert overlap[0].admission == "skipped"
    assert overlap[0].reason == "schedule_overlap"
    assert overlap[0].run_id is None
    assert len(repository.list_agent_runs()) == 1
    assert repository.get_scheduled_agent_task_definition(definition.id).next_run_at == datetime(
        2026,
        10,
        9,
        1,
        30,
        tzinfo=UTC,
    )


def test_dispatch_insert_failure_rolls_back_the_whole_trigger(schedule_project, monkeypatch):
    import sqlite3

    from agentmesh.automation.coordinator import AutomationCoordinator

    repository, user = schedule_project
    definition = _definition(repository, user)
    monkeypatch.setenv("AGENTMESH_AUTOMATION_MODE", "execute")
    with repository._connect() as connection:
        connection.execute("""CREATE TRIGGER reject_inspection BEFORE INSERT ON run_dispatch_receipts
            WHEN NEW.operation_kind = 'project_inspection' BEGIN SELECT RAISE(ABORT, 'test_write_failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="test_write_failure"):
        AutomationCoordinator(repository, runtime_available=lambda: True).tick(
            datetime(2026, 10, 4, 1, 30, tzinfo=UTC),
        )
    assert not repository.list_agent_runs()
    assert not repository.chat_threads
    assert not repository.list_pending_run_dispatches()
    assert repository.get_scheduled_agent_task_definition(definition.id) == definition
    with repository._connect() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM records WHERE collection='scheduled_occurrences'").fetchone()[0]
            == 0
        )


def test_owner_permission_revocation_is_blocked_and_does_not_create_a_run(schedule_project, monkeypatch):
    from agentmesh.automation.coordinator import AutomationCoordinator

    repository, user = schedule_project
    definition = _definition(repository, user)
    repository.save_user(user.model_copy(update={"status": "inactive"}))
    monkeypatch.setenv("AGENTMESH_AUTOMATION_MODE", "execute")
    occurrence = (
        AutomationCoordinator(repository, runtime_available=lambda: True)
        .tick(
            datetime(2026, 10, 4, 1, 30, tzinfo=UTC),
        )
        .occurrences[0]
    )
    assert occurrence.admission == "blocked"
    assert occurrence.run_id is None
    assert occurrence.reason == "schedule_actor_not_authorized"
    assert not repository.list_agent_runs()
    assert repository.get_scheduled_agent_task_definition(definition.id).blocked_reason == occurrence.reason


def test_manual_command_replay_has_a_distinct_identity_and_does_not_move_future_slots(schedule_project, monkeypatch):
    from agentmesh.automation.contracts import ScheduledRunNowRequestV1
    from agentmesh.automation.coordinator import AutomationCoordinator
    from agentmesh.automation.occurrences import OccurrenceRepository

    repository, user = schedule_project
    definition = _definition(repository, user)
    monkeypatch.setenv("AGENTMESH_AUTOMATION_MODE", "execute")
    occurrences = OccurrenceRepository(repository)
    command = ScheduledRunNowRequestV1(command_id="manual", expected_version=1)
    manual_at = datetime(2026, 10, 4, 1, 20, tzinfo=UTC)
    manual = occurrences.admit(definition.id, manual_at, runtime_available=True, actor=user, manual=command)
    assert manual == occurrences.admit(definition.id, manual_at, runtime_available=True, actor=user, manual=command)
    assert manual.trigger == "manual"
    assert repository.get_scheduled_agent_task_definition(definition.id).next_run_at == definition.next_run_at
    run = repository.get_agent_run(manual.run_id)
    repository.save_agent_run(run.model_copy(update={"status": AgentRunStatus.COMPLETED}))
    scheduled = (
        AutomationCoordinator(repository, runtime_available=lambda: True)
        .tick(
            datetime(2026, 10, 4, 1, 30, tzinfo=UTC),
        )
        .occurrences[0]
    )
    assert scheduled.trigger == "scheduled"
    assert scheduled.run_id != manual.run_id


def test_pausing_a_definition_cancels_only_not_started_occurrences(schedule_project, monkeypatch):
    from agentmesh.automation.coordinator import AutomationCoordinator

    repository, user = schedule_project
    definition = _definition(repository, user)
    monkeypatch.setenv("AGENTMESH_AUTOMATION_MODE", "execute")
    occurrence = (
        AutomationCoordinator(repository, runtime_available=lambda: True)
        .tick(
            datetime(2026, 10, 4, 1, 30, tzinfo=UTC),
        )
        .occurrences[0]
    )
    ScheduleDefinitionService(repository).update(
        definition.id,
        ScheduledAgentTaskUpdateRequest(
            command_id="pause",
            expected_version=1,
            enabled=False,
        ),
        user,
    )
    assert repository.get_agent_run(occurrence.run_id).status == AgentRunStatus.CANCELLED
    assert repository.get_latest_run_dispatch(occurrence.run_id).state == "settled"


def test_committed_inspection_dispatch_recovers_and_persists_a_real_structured_report(schedule_project, monkeypatch):
    import asyncio
    import json

    from agentmesh.agent_runtime.service import AgentRuntimeService
    from agentmesh.automation.coordinator import AutomationCoordinator
    from agentmesh.models import now_utc
    from agentmesh.store import SQLiteStore

    repository, user = schedule_project
    _definition(repository, user)
    monkeypatch.setenv("AGENTMESH_AUTOMATION_MODE", "execute")
    occurrence = AutomationCoordinator(repository, runtime_available=lambda: True).tick(now_utc()).occurrences[0]
    path = repository.db_path
    repository.close()
    reopened = SQLiteStore(path)
    try:
        assert reopened.reconcile_orphaned_agent_runs() == 0
        runtime = AgentRuntimeService(reopened, enabled=True)

        async def scenario():
            assert await runtime.recover_pending_dispatches() == 1
            await asyncio.gather(*runtime._tasks.values())

        asyncio.run(scenario())
        run = reopened.get_agent_run(occurrence.run_id)
        assert run.status == AgentRunStatus.COMPLETED
        report = json.loads(run.output_text)
        assert report["schema_version"] == "project-inspection-v1"
        assert report["actual_providers"] == ["local_task_store"]
        assert report["data_mode"] == "real"
        assert report["outcome"] == "insufficient_evidence"
        assert report["missing_data"] == ["no_shared_project_tasks"]
        assert run.inspection_usage.attempt_count == 1
        assert run.inspection_usage.model_turns == run.inspection_usage.total_tokens == 0
        assert reopened.get_latest_run_dispatch(run.id).state == "settled"
        assert len(reopened.inbox_items) == 1
        assert not reopened.tasks
        assert not reopened.memory_items
    finally:
        reopened.close()


def test_started_read_dispatch_restarts_with_the_same_run_and_rejects_old_epoch_settlement(
    schedule_project, monkeypatch
):
    from agentmesh.automation.coordinator import AutomationCoordinator
    from agentmesh.automation.inspection_execution import InspectionExecutionRepository
    from agentmesh.models import now_utc

    repository, user = schedule_project
    _definition(repository, user)
    monkeypatch.setenv("AGENTMESH_AUTOMATION_MODE", "execute")
    at = now_utc()
    occurrence = AutomationCoordinator(repository, runtime_available=lambda: True).tick(at).occurrences[0]
    receipt = repository.get_latest_run_dispatch(occurrence.run_id)
    previous = repository.claim_run_dispatch(receipt.operation_key, process_epoch="old-process")
    executions = InspectionExecutionRepository(repository)
    assert executions.start_attempt(previous, at) is not None
    assert repository.reconcile_run_dispatches_for_startup() == 1
    assert repository.reconcile_orphaned_agent_runs() == 0
    assert executions.finish(previous, at, error_code="stale-result") is None
    current = repository.claim_run_dispatch(receipt.operation_key, process_epoch="new-process")
    assert current.run_id == previous.run_id
    assert current.attempt_count == 2
    assert executions.start_attempt(current, at)[0].inspection_usage.attempt_count == 2


def test_transient_read_retries_are_durable_and_respect_retry_after(schedule_project, monkeypatch):
    import asyncio
    from datetime import timedelta

    from agentmesh.automation.coordinator import AutomationCoordinator
    from agentmesh.automation.inspection_execution import InspectionDispatchExecutor, InspectionReadTransientError
    from agentmesh.automation.service import ProjectInspectionService
    from agentmesh.models import now_utc

    repository, user = schedule_project
    _definition(repository, user)
    monkeypatch.setenv("AGENTMESH_AUTOMATION_MODE", "execute")
    clock = [now_utc()]
    occurrence = AutomationCoordinator(repository, runtime_available=lambda: True).tick(clock[0]).occurrences[0]
    receipt = repository.get_latest_run_dispatch(occurrence.run_id)
    claimed = repository.claim_run_dispatch(receipt.operation_key, process_epoch="retry-process")
    original_read = ProjectInspectionService.inspect
    attempts = []

    def transient_read(self, *args):
        attempts.append(len(attempts) + 1)
        if len(attempts) < 3:
            raise InspectionReadTransientError(retry_after=8 if len(attempts) == 1 else 0)
        return original_read(self, *args)

    delays = []

    async def advance(seconds):
        delays.append(seconds)
        pending = repository.get_agent_run(occurrence.run_id).inspection_usage
        assert pending.next_retry_at == clock[0] + timedelta(seconds=seconds)
        clock[0] += timedelta(seconds=seconds)

    monkeypatch.setattr(ProjectInspectionService, "inspect", transient_read)
    asyncio.run(InspectionDispatchExecutor(repository, clock=lambda: clock[0], sleep=advance).execute(claimed))
    assert attempts == [1, 2, 3]
    assert delays == [8, 30]
    run = repository.get_agent_run(occurrence.run_id)
    assert run.status == AgentRunStatus.COMPLETED
    assert run.inspection_usage.attempt_count == 3
    assert run.tool_call_count == 3
    assert run.inspection_usage.next_retry_at is None


def test_permission_change_after_dispatch_is_not_retried_and_does_not_publish_a_report(schedule_project, monkeypatch):
    import asyncio

    from agentmesh.automation.coordinator import AutomationCoordinator
    from agentmesh.automation.inspection_execution import InspectionDispatchExecutor
    from agentmesh.models import now_utc

    repository, user = schedule_project
    _definition(repository, user)
    monkeypatch.setenv("AGENTMESH_AUTOMATION_MODE", "execute")
    at = now_utc()
    occurrence = AutomationCoordinator(repository, runtime_available=lambda: True).tick(at).occurrences[0]
    receipt = repository.get_latest_run_dispatch(occurrence.run_id)
    claimed = repository.claim_run_dispatch(receipt.operation_key, process_epoch="revoked-process")
    repository.save_user(user.model_copy(update={"status": "inactive"}))
    asyncio.run(InspectionDispatchExecutor(repository, clock=lambda: at).execute(claimed))
    run = repository.get_agent_run(occurrence.run_id)
    assert run.status == AgentRunStatus.FAILED
    assert run.error_code == "schedule_actor_not_authorized"
    assert run.inspection_usage.attempt_count == 0
    assert run.output_text is None
    assert not repository.inbox_items


def test_identical_reports_do_not_repeat_inbox_notifications(schedule_project, monkeypatch):
    import asyncio

    from agentmesh.automation.contracts import ScheduledRunNowRequestV1
    from agentmesh.automation.inspection_execution import InspectionDispatchExecutor
    from agentmesh.automation.occurrences import OccurrenceRepository
    from agentmesh.models import now_utc

    repository, user = schedule_project
    definition = _definition(repository, user)
    monkeypatch.setenv("AGENTMESH_AUTOMATION_MODE", "execute")
    at = now_utc()
    for command_id in ("first", "second"):
        occurrence = OccurrenceRepository(repository).admit(
            definition.id,
            at,
            runtime_available=True,
            actor=user,
            manual=ScheduledRunNowRequestV1(command_id=command_id, expected_version=1),
        )
        receipt = repository.get_latest_run_dispatch(occurrence.run_id)
        claimed = repository.claim_run_dispatch(receipt.operation_key, process_epoch="notifier")
        asyncio.run(InspectionDispatchExecutor(repository, clock=lambda: at).execute(claimed))
    assert len(repository.list_agent_runs()) == 2
    assert len(repository.inbox_items) == 1
    assert all(run.status == AgentRunStatus.COMPLETED for run in repository.list_agent_runs())


def test_result_commit_failure_rolls_back_inbox_and_is_recovered_by_the_same_runtime(schedule_project, monkeypatch):
    import asyncio
    import sqlite3

    from agentmesh.agent_runtime.service import AgentRuntimeService
    from agentmesh.automation.coordinator import AutomationCoordinator
    from agentmesh.models import now_utc

    repository, user = schedule_project
    _definition(repository, user)
    monkeypatch.setenv("AGENTMESH_AUTOMATION_MODE", "execute")
    occurrence = AutomationCoordinator(repository, runtime_available=lambda: True).tick(now_utc()).occurrences[0]
    with repository._connect() as connection:
        connection.execute("""CREATE TRIGGER reject_result BEFORE UPDATE ON agent_runs
            WHEN json_extract(NEW.payload, '$.status') = 'completed'
            BEGIN SELECT RAISE(ABORT, 'result_commit_interrupted'); END""")
    runtime = AgentRuntimeService(repository, enabled=True)

    async def scenario():
        assert await runtime.recover_pending_dispatches() == 1
        results = await asyncio.gather(*runtime._tasks.values(), return_exceptions=True)
        assert isinstance(results[0], sqlite3.IntegrityError)
        assert not repository.inbox_items
        assert repository.get_agent_run(occurrence.run_id).output_text is None
        with repository._connect() as connection:
            connection.execute("DROP TRIGGER reject_result")
        await asyncio.sleep(0)
        assert await runtime.recover_pending_dispatches() == 1
        await asyncio.gather(*runtime._tasks.values())

    asyncio.run(scenario())
    run = repository.get_agent_run(occurrence.run_id)
    assert run.status == AgentRunStatus.COMPLETED
    assert run.inspection_usage.attempt_count == 2
    assert len(repository.inbox_items) == 1
    assert len(repository.list_agent_runs()) == 1


@pytest.mark.parametrize("failure", ["deadline", "tool_budget", "transient_exhausted", "invalid_input"])
def test_inspection_failures_are_terminal_visible_and_do_not_invent_reports(schedule_project, monkeypatch, failure):
    import asyncio
    from datetime import timedelta

    from agentmesh.automation.coordinator import AutomationCoordinator
    from agentmesh.automation.inspection_execution import InspectionDispatchExecutor, InspectionReadTransientError
    from agentmesh.automation.service import ProjectInspectionService
    from agentmesh.models import now_utc
    from agentmesh.task_operations.service import TaskOperationsError

    repository, user = schedule_project
    definition = _definition(repository, user)
    monkeypatch.setenv("AGENTMESH_AUTOMATION_MODE", "execute")
    clock = [now_utc()]
    occurrence = AutomationCoordinator(repository, runtime_available=lambda: True).tick(clock[0]).occurrences[0]
    run = repository.get_agent_run(occurrence.run_id)
    if failure == "deadline":
        clock[0] = run.deadline_at
    elif failure == "tool_budget":
        repository.save_agent_run(run.model_copy(update={"tool_call_count": occurrence.budget.max_tool_calls}))
    else:

        def failed_read(*args):
            if failure == "transient_exhausted":
                raise InspectionReadTransientError()
            raise TaskOperationsError("inspection_range_invalid", status_code=422)

        monkeypatch.setattr(ProjectInspectionService, "inspect", failed_read)
    delays = []

    async def advance(seconds):
        delays.append(seconds)
        clock[0] += timedelta(seconds=seconds)

    receipt = repository.get_latest_run_dispatch(run.id)
    claimed = repository.claim_run_dispatch(receipt.operation_key, process_epoch="failure-process")
    asyncio.run(InspectionDispatchExecutor(repository, clock=lambda: clock[0], sleep=advance).execute(claimed))
    failed = repository.get_agent_run(run.id)
    assert failed.status == AgentRunStatus.FAILED
    assert failed.output_text is None
    assert (
        failed.error_code
        == {
            "deadline": "inspection_deadline_exceeded",
            "tool_budget": "inspection_tool_budget_exceeded",
            "transient_exhausted": "inspection_read_retry_exhausted",
            "invalid_input": "inspection_range_invalid",
        }[failure]
    )
    assert delays == ([5, 30] if failure == "transient_exhausted" else [])
    assert repository.get_scheduled_agent_task_definition(definition.id).last_error_code == failed.error_code
    assert repository.get_latest_run_dispatch(run.id).state == "settled"


def test_reports_are_owner_only_and_project_membership_is_rechecked(schedule_project, monkeypatch):
    import asyncio

    from agentmesh.automation.coordinator import AutomationCoordinator
    from agentmesh.automation.inspection_execution import InspectionDispatchExecutor
    from agentmesh.automation.queries import InspectionRunQuery
    from agentmesh.automation.schedule_repository import ScheduleDefinitionError
    from agentmesh.models import now_utc

    repository, user = schedule_project
    definition = _definition(repository, user)
    monkeypatch.setenv("AGENTMESH_AUTOMATION_MODE", "execute")
    at = now_utc()
    occurrence = AutomationCoordinator(repository, runtime_available=lambda: True).tick(at).occurrences[0]
    receipt = repository.get_latest_run_dispatch(occurrence.run_id)
    claimed = repository.claim_run_dispatch(receipt.operation_key, process_epoch="report-process")
    asyncio.run(InspectionDispatchExecutor(repository, clock=lambda: at).execute(claimed))
    query = InspectionRunQuery(repository)
    assert query.report(occurrence.run_id, user).project_id == user.default_project_id
    other = repository.save_user(user.model_copy(update={"id": "other", "role": "admin"}))
    project = repository.get_project(user.default_project_id)
    repository.save_project(project.model_copy(update={"member_ids": [user.id, other.id]}))
    assert query.list_runs(definition.id, other).total_count == 1
    with pytest.raises(ScheduleDefinitionError, match="inspection_report_not_found"):
        query.report(occurrence.run_id, other)
    repository.save_project(project.model_copy(update={"member_ids": [other.id]}))
    with pytest.raises(ScheduleDefinitionError, match="project_not_found"):
        query.report(occurrence.run_id, user)
