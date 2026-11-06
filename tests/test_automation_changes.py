import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_automation_schedules import schedule_project as schedule_project
from test_project_inspections import _reviewable_delivery

from agentmesh.automation.coordinator import AutomationCoordinator
from agentmesh.automation.inspection_execution import InspectionDispatchExecutor
from agentmesh.automation.queries import InspectionRunQuery
from agentmesh.automation.schedules import ScheduleDefinitionService
from agentmesh.models import (
    AgentRunStatus,
    ChatThreadKind,
    ScheduledAgentTaskCreateRequest,
    ScheduledAgentTaskDefinition,
    ScheduledAgentTaskUpdateRequest,
)
from agentmesh.routes.deps import current_user
from agentmesh.store import SQLiteStore
from agentmesh.task_management.contracts import TaskCreateRequest
from agentmesh.task_management.service import TaskManagementService

AT = datetime(2026, 10, 6, 0, tzinfo=UTC)


def _definition(repository, user, **changes):
    return ScheduleDefinitionService(repository, clock=lambda: AT).create(
        ScheduledAgentTaskCreateRequest(
            **{
                "command_id": "definition",
                "project_id": user.default_project_id,
                "template_id": "daily_progress",
                "title": "Project changes",
                "schedule": "0 12 * * *",
                "on_project_changes": True,
                **changes,
            }
        ), user,
    )


def _task(repository, user, monkeypatch, *, command="task-create", at=AT):
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    task = TaskManagementService(repository).create_task(
        TaskCreateRequest(command_id=command, title="Release checklist"), user,
    ).task
    _stamp(repository, command, at)
    return task


def _stamp(repository, command, at, *, collection="task_command_receipts"):
    with repository._connect() as connection:
        connection.execute(
            """UPDATE records SET payload = json_set(payload, '$.created_at', ?)
            WHERE collection = ? AND json_extract(payload, '$.command_id') = ?""",
            (at.isoformat(), collection, command),
        )


def _coordinator(repository, monkeypatch, *, runtime=True, mode="execute"):
    monkeypatch.setenv("AGENTMESH_AUTOMATION_MODE", mode)
    return AutomationCoordinator(repository, runtime_available=lambda: runtime)


def test_committed_change_coalesces_and_reuses_the_existing_occurrence_run_and_dispatch(schedule_project, monkeypatch):
    repository, user = schedule_project
    definition = _definition(repository, user)
    _task(repository, user, monkeypatch)
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "off")
    monkeypatch.setenv("AGENTMESH_AUTOMATION_MODE", "execute")
    coordinator = AutomationCoordinator(repository, runtime_available=lambda: True)
    assert not coordinator.tick(AT + timedelta(seconds=29)).occurrences
    result = coordinator.tick(AT + timedelta(seconds=30))
    assert len(result.occurrences) == 1
    occurrence = result.occurrences[0]
    assert occurrence.trigger == "change"
    assert occurrence.schedule_id == definition.id
    assert occurrence.source_cursor > definition.change_cursor
    assert occurrence.local_slot is None
    run = repository.get_agent_run(occurrence.run_id)
    assert run.task_id is None
    assert run.user_id == user.id
    assert run.orchestration_version == "v1"
    dispatch = repository.get_latest_run_dispatch(run.id)
    assert dispatch.operation_kind == "project_inspection"
    assert dispatch.payload == {"occurrence_id": occurrence.id}
    current = repository.get_scheduled_agent_task_definition(definition.id)
    assert current.change_cursor == occurrence.source_cursor
    assert current.next_run_at == definition.next_run_at
    assert not coordinator.tick(AT + timedelta(seconds=31)).occurrences


def test_continuous_changes_coalesce_at_the_latest_watermark(schedule_project, monkeypatch):
    repository, user = schedule_project
    definition = _definition(repository, user)
    _task(repository, user, monkeypatch)
    _task(repository, user, monkeypatch, command="second", at=AT + timedelta(seconds=20))
    coordinator = _coordinator(repository, monkeypatch)
    assert not coordinator.tick(AT + timedelta(seconds=30)).occurrences
    assert not coordinator.tick(AT + timedelta(seconds=49)).occurrences
    occurrence = coordinator.tick(AT + timedelta(seconds=50)).occurrences[0]
    assert occurrence.scheduled_at == AT + timedelta(seconds=50)
    assert len(repository.list_agent_runs()) == 1
    assert repository.get_scheduled_agent_task_definition(definition.id).change_cursor == occurrence.source_cursor
    assert len(repository.tasks) == 2
    assert not repository.memory_items


def test_sustained_edits_cannot_postpone_the_coalescing_window_forever(schedule_project, monkeypatch):
    repository, user = schedule_project
    _definition(repository, user)
    _task(repository, user, monkeypatch)
    for seconds in (25, 50, 100, 150, 200, 250, 290):
        _task(repository, user, monkeypatch, command=f"edit-{seconds}", at=AT + timedelta(seconds=seconds))
    coordinator = _coordinator(repository, monkeypatch)
    assert not coordinator.tick(AT + timedelta(seconds=299)).occurrences
    occurrence = coordinator.tick(AT + timedelta(minutes=5)).occurrences[0]
    assert occurrence.admission == "admitted"
    assert occurrence.scheduled_at == AT + timedelta(minutes=5)


def test_change_trigger_is_explicit_and_does_not_replay_history_before_opt_in(schedule_project, monkeypatch):
    repository, user = schedule_project
    _task(repository, user, monkeypatch)
    definition = _definition(repository, user, on_project_changes=False)
    coordinator = _coordinator(repository, monkeypatch)
    assert not coordinator.tick(AT + timedelta(seconds=30)).occurrences
    assert definition.change_cursor is None
    definition = ScheduleDefinitionService(repository, clock=lambda: AT).update(
        definition.id, ScheduledAgentTaskUpdateRequest(
            command_id="enable-changes", expected_version=1, on_project_changes=True,
        ), user,
    )
    assert definition.change_cursor is not None
    assert not coordinator.tick(AT + timedelta(seconds=31)).occurrences
    _task(repository, user, monkeypatch, command="new-change", at=AT + timedelta(seconds=40))
    assert coordinator.tick(AT + timedelta(seconds=70)).occurrences[0].trigger == "change"


@pytest.mark.parametrize("mode", ["off", "invalid", "observe"])
def test_off_and_observe_do_not_advance_change_cursors_or_write_runs(schedule_project, monkeypatch, mode):
    repository, user = schedule_project
    definition = _definition(repository, user)
    _task(repository, user, monkeypatch)
    with repository._connect() as connection:
        before = connection.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    result = _coordinator(repository, monkeypatch, mode=mode).tick(AT + timedelta(seconds=30))
    assert len(result.due) == (1 if mode == "observe" else 0)
    assert not result.occurrences
    assert not repository.list_agent_runs()
    assert not repository.list_pending_run_dispatches()
    assert repository.get_scheduled_agent_task_definition(definition.id) == definition
    with repository._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM records").fetchone()[0] == before


def test_change_admission_rolls_back_cursor_occurrence_and_run_on_dispatch_failure(schedule_project, monkeypatch):
    repository, user = schedule_project
    definition = _definition(repository, user)
    _task(repository, user, monkeypatch)
    coordinator = _coordinator(repository, monkeypatch)
    with repository._connect() as connection:
        connection.execute("""CREATE TRIGGER reject_change_dispatch BEFORE INSERT ON run_dispatch_receipts
            BEGIN SELECT RAISE(ABORT, 'test_dispatch_failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="test_dispatch_failure"):
        coordinator.tick(AT + timedelta(seconds=30))
    assert repository.get_scheduled_agent_task_definition(definition.id) == definition
    assert not repository.list_agent_runs()
    with repository._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM records WHERE collection='scheduled_occurrences'").fetchone()[0] == 0
        connection.execute("DROP TRIGGER reject_change_dispatch")
    assert len(coordinator.tick(AT + timedelta(seconds=30)).occurrences) == 1


def test_rolled_back_task_command_does_not_trigger_an_inspection(schedule_project, monkeypatch):
    repository, user = schedule_project
    definition = _definition(repository, user)
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    with repository._connect() as connection:
        connection.execute("""CREATE TRIGGER reject_task_command BEFORE INSERT ON records
            WHEN NEW.collection='task_command_receipts'
            BEGIN SELECT RAISE(ABORT, 'test_task_rollback'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="test_task_rollback"):
        TaskManagementService(repository).create_task(TaskCreateRequest(command_id="rolled-back", title="No commit"), user)
    assert not _coordinator(repository, monkeypatch).tick(AT + timedelta(seconds=30)).occurrences
    assert repository.get_scheduled_agent_task_definition(definition.id) == definition
    assert not repository.tasks


@pytest.mark.parametrize("thread_change", [{"kind": ChatThreadKind.CONVERSATION}, {"project_id": "other"}, {"workspace_id": "other"}])
def test_current_visibility_excludes_private_and_foreign_task_changes(schedule_project, monkeypatch, thread_change):
    repository, user = schedule_project
    _definition(repository, user)
    task = _task(repository, user, monkeypatch)
    thread = repository.get_chat_thread(task.thread_id)
    repository.save_chat_thread(thread.model_copy(update=thread_change))
    assert not _coordinator(repository, monkeypatch).tick(AT + timedelta(seconds=30)).due
    assert not repository.list_agent_runs()


def test_raw_task_write_without_a_committed_command_does_not_trigger(schedule_project, monkeypatch):
    repository, user = schedule_project
    task = _task(repository, user, monkeypatch)
    _definition(repository, user)
    repository.save_task(task.model_copy(update={"title": "Uncommanded edit"}))
    assert not _coordinator(repository, monkeypatch).tick(AT + timedelta(seconds=30)).occurrences


def test_database_reopen_and_two_coordinators_do_not_duplicate_a_change_trigger(schedule_project, monkeypatch):
    repository, user = schedule_project
    definition = _definition(repository, user)
    _task(repository, user, monkeypatch)
    coordinator = _coordinator(repository, monkeypatch)
    second = AutomationCoordinator(repository, runtime_available=lambda: True)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda item: item.tick(AT + timedelta(seconds=30)), [coordinator, second]))
    assert sum(len(item.occurrences) for item in results) == 1
    repository.close()
    reopened = SQLiteStore(repository.db_path)
    try:
        assert not AutomationCoordinator(reopened, runtime_available=lambda: True).tick(AT + timedelta(seconds=31)).occurrences
        assert len(reopened.list_agent_runs()) == 1
        assert reopened.get_scheduled_agent_task_definition(definition.id).change_cursor > definition.change_cursor
    finally:
        reopened.close()


@pytest.mark.parametrize("revocation", ["actor", "workspace", "permission", "project", "membership", "agent", "runtime"])
def test_change_admission_checks_current_authority(schedule_project, monkeypatch, revocation):
    repository, user = schedule_project
    _definition(repository, user)
    _task(repository, user, monkeypatch)
    if revocation in {"actor", "workspace", "permission"}:
        changes = {"actor": {"status": "disabled"}, "workspace": {"workspace_id": "other"}, "permission": {"role": "user"}}
        repository.save_user(user.model_copy(update=changes[revocation]))
    elif revocation in {"project", "membership"}:
        project = repository.get_project(user.default_project_id)
        changes = {"status": "archived"} if revocation == "project" else {"member_ids": ["other"]}
        repository.save_project(project.model_copy(update=changes))
    elif revocation == "agent":
        agent = repository.get_agent(user.personal_agent_id)
        repository.save_agent(agent.model_copy(update={"status": "offline"}))
    result = _coordinator(repository, monkeypatch, runtime=revocation != "runtime").tick(AT + timedelta(seconds=30))
    assert len(result.occurrences) == 1
    assert result.occurrences[0].admission == "blocked"
    assert result.occurrences[0].reason is not None
    assert not repository.list_agent_runs()


def test_revocation_after_preview_is_checked_inside_admission(schedule_project, monkeypatch):
    repository, user = schedule_project
    _definition(repository, user)
    _task(repository, user, monkeypatch)
    coordinator = _coordinator(repository, monkeypatch)
    admit = coordinator.repository.admit

    def revoke_and_admit(*args, **kwargs):
        repository.save_user(user.model_copy(update={"status": "disabled"}))
        return admit(*args, **kwargs)

    monkeypatch.setattr(coordinator.repository, "admit", revoke_and_admit)
    result = coordinator.tick(AT + timedelta(seconds=30))
    assert result.occurrences[0].reason == "schedule_actor_not_authorized"
    assert not repository.list_agent_runs()


def test_pending_change_waits_for_the_existing_five_minute_run_floor(schedule_project, monkeypatch):
    repository, user = schedule_project
    definition = _definition(repository, user)
    _task(repository, user, monkeypatch)
    coordinator = _coordinator(repository, monkeypatch)
    first = coordinator.tick(AT + timedelta(seconds=30)).occurrences[0]
    run = repository.get_agent_run(first.run_id)
    repository.save_agent_run(run.model_copy(update={"status": AgentRunStatus.COMPLETED}))
    _task(repository, user, monkeypatch, command="later", at=AT + timedelta(seconds=40))
    assert not coordinator.tick(AT + timedelta(minutes=5, seconds=29)).occurrences
    pending = repository.get_scheduled_agent_task_definition(definition.id)
    assert pending.change_cursor == first.source_cursor
    second = coordinator.tick(AT + timedelta(minutes=5, seconds=30)).occurrences[0]
    assert second.admission == "admitted"
    assert second.source_cursor > first.source_cursor


def test_overlap_is_recorded_as_skipped_without_creating_another_run(schedule_project, monkeypatch):
    repository, user = schedule_project
    _definition(repository, user)
    _task(repository, user, monkeypatch)
    coordinator = _coordinator(repository, monkeypatch)
    first = coordinator.tick(AT + timedelta(seconds=30)).occurrences[0]
    _task(repository, user, monkeypatch, command="later", at=AT + timedelta(minutes=5))
    second = coordinator.tick(AT + timedelta(minutes=5, seconds=30)).occurrences[0]
    assert second.admission == "skipped"
    assert second.reason == "schedule_overlap"
    assert second.run_id is None
    assert first.run_id is not None
    assert len(repository.list_agent_runs()) == 1


def test_due_cron_consumes_current_change_watermark_once(schedule_project, monkeypatch):
    repository, user = schedule_project
    definition = _definition(repository, user, schedule="1 8 * * *")
    _task(repository, user, monkeypatch)
    coordinator = _coordinator(repository, monkeypatch)
    occurrence = coordinator.tick(AT + timedelta(minutes=1)).occurrences[0]
    assert occurrence.trigger == "scheduled"
    assert occurrence.source_cursor is not None
    assert repository.get_scheduled_agent_task_definition(definition.id).change_cursor == occurrence.source_cursor
    assert not coordinator.tick(AT + timedelta(minutes=6)).occurrences


def test_configuration_update_preserves_a_cursor_advanced_after_the_command_was_prepared(schedule_project, monkeypatch):
    repository, user = schedule_project
    definition = _definition(repository, user)
    _task(repository, user, monkeypatch)
    service = ScheduleDefinitionService(repository, clock=lambda: AT + timedelta(seconds=30))
    commit = service.repository.commit_definition
    occurrence = []

    def tick_then_commit(*args, **kwargs):
        occurrence.extend(_coordinator(repository, monkeypatch).tick(AT + timedelta(seconds=30)).occurrences)
        return commit(*args, **kwargs)

    monkeypatch.setattr(service.repository, "commit_definition", tick_then_commit)
    updated = service.update(definition.id, ScheduledAgentTaskUpdateRequest(command_id="rename", expected_version=1, title="Renamed"), user)
    assert updated.change_cursor == occurrence[0].source_cursor
    assert updated.last_run_at == AT + timedelta(seconds=30)


def test_pause_resume_and_template_change_start_at_a_new_committed_watermark(schedule_project, monkeypatch):
    repository, user = schedule_project
    definition = _definition(repository, user)
    service = ScheduleDefinitionService(repository, clock=lambda: AT)
    paused = service.update(definition.id, ScheduledAgentTaskUpdateRequest(command_id="pause", expected_version=1, enabled=False), user)
    _task(repository, user, monkeypatch)
    coordinator = _coordinator(repository, monkeypatch)
    assert not coordinator.tick(AT + timedelta(seconds=30)).occurrences
    resumed = service.update(paused.id, ScheduledAgentTaskUpdateRequest(command_id="resume", expected_version=2, enabled=True), user)
    assert resumed.change_cursor > paused.change_cursor
    assert not coordinator.tick(AT + timedelta(seconds=31)).occurrences
    _task(repository, user, monkeypatch, command="new", at=AT + timedelta(seconds=40))
    changed = service.update(resumed.id, ScheduledAgentTaskUpdateRequest(command_id="template", expected_version=3, template_id="blockers"), user)
    assert changed.change_cursor > resumed.change_cursor
    assert not coordinator.tick(AT + timedelta(seconds=70)).occurrences


def test_actual_review_command_triggers_the_same_read_only_runtime_path(schedule_project, monkeypatch):
    repository, user = schedule_project
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    # Review commands and the schedule must share a fixed clock. A wall-clock
    # command can cross the next cron slot and correctly trigger a scheduled run.
    monkeypatch.setattr("agentmesh.task_review.service.now_utc", lambda: AT)
    delivery = _reviewable_delivery(repository, user, "change")
    definition = _definition(repository, user, schedule="59 23 * * *")
    # A real decide command is the first newly committed event after opt-in.
    from agentmesh.task_review.contracts import TaskReviewDecisionRequest
    from agentmesh.task_review.service import TaskCompletionService

    TaskCompletionService(repository).decide_review(
        delivery.item.review.id, TaskReviewDecisionRequest(command_id="decision", expected_version=1, decision="accepted"), user,
    )
    at = repository.get_task(delivery.task.id).updated_at + timedelta(seconds=30)
    coordinator = _coordinator(repository, monkeypatch)
    occurrence = coordinator.tick(at).occurrences[0]
    assert occurrence.trigger == "change"
    assert occurrence.source_cursor > definition.change_cursor
    dispatch = repository.get_latest_run_dispatch(occurrence.run_id)
    claimed = repository.claim_run_dispatch(dispatch.operation_key, process_epoch="change-inspection")
    inbox_count = len(repository.inbox_items)
    task_before = repository.get_task(delivery.task.id)
    asyncio.run(InspectionDispatchExecutor(repository, clock=lambda: at).execute(claimed))
    completed = repository.get_agent_run(occurrence.run_id)
    assert completed.status == AgentRunStatus.COMPLETED
    assert completed.inspection_usage.total_tokens == completed.inspection_usage.model_turns == 0
    report = InspectionRunQuery(repository).report(completed.id, user)
    assert report.data_mode == "real"
    assert report.actual_providers == ["local_task_store"]
    assert any(change.task_id == delivery.task.id and change.kind == "completed" for change in report.changes)
    assert any(ref.source_kind == "task_review_command" for ref in report.evidence_refs)
    assert len(repository.inbox_items) == inbox_count + 1
    assert repository.get_task(delivery.task.id) == task_before
    assert not repository.memory_items


def test_public_api_exposes_explicit_opt_in_but_cannot_accept_a_client_cursor(schedule_project, monkeypatch):
    from agentmesh.routes import agents as routes

    repository, user = schedule_project
    monkeypatch.setattr(routes, "store", repository)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[current_user] = lambda: user
    client = TestClient(app)
    payload = {"command_id": "api-create", "project_id": user.default_project_id, "title": "Changes",
               "template_id": "daily_progress", "schedule": "0 12 * * *", "on_project_changes": True}
    created = client.post("/api/agents/scheduled-tasks", json=payload)
    assert created.status_code == 200, created.text
    assert created.json()["on_project_changes"] is True
    assert created.json()["change_cursor"] >= 0
    rejected = client.patch(f"/api/agents/scheduled-tasks/{created.json()['id']}", json={
        "command_id": "fake-cursor", "expected_version": 1, "change_cursor": 0,
    })
    assert rejected.status_code == 422


def test_legacy_schedules_and_request_payloads_cannot_silently_enable_change_execution():
    with pytest.raises(ValidationError):
        ScheduledAgentTaskDefinition(agent_id="old", title="Old", prompt="Query", schedule="0 12 * * *", created_by="owner", on_project_changes=True)
    with pytest.raises(ValidationError):
        ScheduledAgentTaskCreateRequest(agent_id="old", title="Old", prompt="Query", schedule="0 12 * * *", on_project_changes=True)


def test_change_scan_respects_tick_limit_and_advances_through_the_remaining_definitions(schedule_project, monkeypatch):
    repository, user = schedule_project
    for index in range(3):
        _definition(repository, user, command_id=f"definition-{index}")
    _task(repository, user, monkeypatch)
    coordinator = _coordinator(repository, monkeypatch)
    for remaining in (2, 1, 0):
        result = coordinator.tick(AT + timedelta(seconds=30), limit=1)
        assert len(result.occurrences) == 1
        assert result.has_more == bool(remaining)
    assert not coordinator.tick(AT + timedelta(seconds=30), limit=1).occurrences
    assert len(repository.list_agent_runs()) == 3


def test_new_edits_on_an_already_served_definition_cannot_starve_the_other_pending_definition(schedule_project, monkeypatch):
    repository, user = schedule_project
    for index in range(2):
        _definition(repository, user, command_id=f"definition-{index}")
    _task(repository, user, monkeypatch)
    coordinator = _coordinator(repository, monkeypatch)
    first = coordinator.tick(AT + timedelta(seconds=30), limit=1).occurrences[0]
    _task(repository, user, monkeypatch, command="more-edits", at=AT + timedelta(seconds=31))
    result = coordinator.tick(AT + timedelta(seconds=61), limit=1)
    assert len(result.occurrences) == 1
    assert result.occurrences[0].schedule_id != first.schedule_id
    assert result.occurrences[0].admission == "admitted"
