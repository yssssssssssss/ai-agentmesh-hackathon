from datetime import UTC, datetime

import pytest

from agentmesh.automation.schedule_repository import ScheduleDefinitionError
from agentmesh.automation.schedules import ScheduleDefinitionService
from agentmesh.models import (
    Agent,
    PermissionPolicyRule,
    Project,
    ScheduledAgentTaskCreateRequest,
    ScheduledAgentTaskDefinition,
    ScheduledAgentTaskUpdateRequest,
    User,
    Workspace,
)
from agentmesh.store import SQLiteStore


@pytest.fixture
def schedule_project(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "off")
    path = tmp_path / "schedules.sqlite3"
    repository = SQLiteStore(path)
    workspace = repository.save_workspace(Workspace(id="ws_schedule", name="Pilot", description="Pilot"))
    user = repository.save_user(
        User(
            id="user_schedule",
            workspace_id=workspace.id,
            default_project_id="project_schedule",
            name="Owner",
            role="team_lead",
            personal_agent_id="agent_schedule",
        )
    )
    repository.save_project(
        Project(
            id=user.default_project_id,
            workspace_id=workspace.id,
            name="Pilot",
            goal="Deliver",
            member_ids=[user.id],
        )
    )
    repository.save_agent(
        Agent(
            id=user.personal_agent_id,
            name="Owner agent",
            description="Owner",
            agent_type="personal",
            owner_user_id=user.id,
            workspace_id=workspace.id,
        )
    )
    yield repository, user
    repository.close()


def _request(**changes):
    return ScheduledAgentTaskCreateRequest(
        **{
            "command_id": "schedule-command",
            "project_id": "project_schedule",
            "template_id": "daily_progress",
            "title": "Morning inspection",
            "schedule": "30 9 * * *",
            "timezone": "Asia/Shanghai",
            **changes,
        }
    )


def test_creating_a_project_schedule_is_durable_idempotent_and_server_owned(schedule_project):
    repository, user = schedule_project
    request = ScheduledAgentTaskCreateRequest(
        command_id="schedule-command",
        project_id=user.default_project_id,
        template_id="daily_progress",
        title="Morning inspection",
        schedule="30 9 * * *",
        timezone="Asia/Shanghai",
    )
    service = ScheduleDefinitionService(repository, clock=lambda: datetime(2026, 10, 4, 0, 0, tzinfo=UTC))

    definition = service.create(request, user)
    replay = service.create(request, user)

    assert definition == replay
    assert definition.owner_user_id == user.id
    assert definition.agent_id == user.personal_agent_id
    assert definition.validation_state == "valid"
    assert definition.version == 1
    assert definition.next_run_at == datetime(2026, 10, 4, 1, 30, tzinfo=UTC)
    assert len(repository.scheduled_agent_task_definitions) == 1
    repository.close()
    reopened = SQLiteStore(repository.db_path)
    assert reopened.get_scheduled_agent_task_definition(definition.id) == definition
    reopened.close()


def test_schedule_updates_are_versioned_and_pause_or_restore_the_next_slot(schedule_project):
    repository, user = schedule_project
    service = ScheduleDefinitionService(repository, clock=lambda: datetime(2026, 10, 4, 0, tzinfo=UTC))
    definition = service.create(_request(), user)
    pause = ScheduledAgentTaskUpdateRequest(command_id="pause", expected_version=1, enabled=False)
    paused = service.update(definition.id, pause, user)
    assert paused.version == 2
    assert paused.next_run_at is None
    assert not paused.enabled
    assert service.update(definition.id, pause, user) == paused
    with pytest.raises(ScheduleDefinitionError, match="schedule_version_conflict"):
        service.update(
            definition.id,
            ScheduledAgentTaskUpdateRequest(
                command_id="stale",
                expected_version=1,
                title="Stale title",
            ),
            user,
        )
    service = ScheduleDefinitionService(repository, clock=lambda: datetime(2026, 10, 4, 2, tzinfo=UTC))
    restored = service.update(
        definition.id,
        ScheduledAgentTaskUpdateRequest(
            command_id="restore",
            expected_version=2,
            enabled=True,
        ),
        user,
    )
    assert restored.version == 3
    assert restored.enabled
    assert restored.next_run_at == datetime(2026, 10, 5, 1, 30, tzinfo=UTC)


def test_current_permissions_are_rechecked_even_for_command_replays(schedule_project):
    repository, user = schedule_project
    service = ScheduleDefinitionService(repository)
    service.create(_request(), user)
    repository.save_permission_policy_rule(
        PermissionPolicyRule(
            role=user.role,
            action="manage_project_tasks",
            effect="deny",
            description="Revoked",
        )
    )
    with pytest.raises(ScheduleDefinitionError, match="schedule_permission_denied"):
        service.create(_request(), user)
    assert len(repository.scheduled_agent_task_definitions) == 1


def test_command_reuse_with_changed_content_is_a_conflict(schedule_project):
    repository, user = schedule_project
    service = ScheduleDefinitionService(repository)
    service.create(_request(), user)
    with pytest.raises(ScheduleDefinitionError, match="schedule_command_conflict"):
        service.create(_request(title="Different title"), user)
    assert len(repository.scheduled_agent_task_definitions) == 1
    assert (
        len([event for event in repository.audit_events if event.action == "create_project_inspection_schedule"]) == 1
    )


def test_concurrent_creates_commit_one_definition_and_one_audit(schedule_project):
    from concurrent.futures import ThreadPoolExecutor

    repository, user = schedule_project
    with ThreadPoolExecutor(max_workers=4) as workers:
        definitions = list(
            workers.map(lambda _: ScheduleDefinitionService(repository).create(_request(), user), range(4))
        )
    assert len({definition.id for definition in definitions}) == 1
    assert len(repository.scheduled_agent_task_definitions) == 1
    assert (
        len([event for event in repository.audit_events if event.action == "create_project_inspection_schedule"]) == 1
    )


@pytest.mark.parametrize("revocation", ["membership", "inactive_actor", "inactive_project", "agent_identity"])
def test_creation_rechecks_current_project_and_execution_identity(schedule_project, revocation):
    repository, user = schedule_project
    if revocation == "membership":
        project = repository.get_project(user.default_project_id)
        repository.save_project(project.model_copy(update={"member_ids": ["someone_else"]}))
    elif revocation == "inactive_actor":
        repository.save_user(user.model_copy(update={"status": "inactive"}))
    elif revocation == "inactive_project":
        project = repository.get_project(user.default_project_id)
        repository.save_project(project.model_copy(update={"status": "archived"}))
    else:
        agent = repository.get_agent(user.personal_agent_id)
        repository.save_agent(agent.model_copy(update={"owner_user_id": "someone_else"}))
    with pytest.raises(ScheduleDefinitionError):
        ScheduleDefinitionService(repository).create(_request(), user)
    assert not repository.scheduled_agent_task_definitions
    assert not repository.audit_events


def test_listing_is_paginated_and_scoped_to_current_workspace_and_project_membership(schedule_project):
    from agentmesh.automation.schedule_repository import ScheduleRepository

    repository, user = schedule_project
    service = ScheduleDefinitionService(repository)
    definition = service.create(_request(), user)
    service.create(_request(command_id="second"), user)
    foreign_user = repository.save_user(user.model_copy(update={"id": "foreign", "workspace_id": "other_workspace"}))
    repository.save_scheduled_agent_task_definition(
        ScheduledAgentTaskDefinition(
            agent_id="foreign_agent",
            title="Foreign private schedule",
            prompt="Private",
            schedule="old",
            created_by=foreign_user.id,
        )
    )
    hidden_project = repository.save_project(
        Project(
            id="other_project",
            workspace_id=user.workspace_id,
            name="Other project",
            goal="Private",
            member_ids=[foreign_user.id],
        )
    )
    repository.save_scheduled_agent_task_definition(
        definition.model_copy(
            update={
                "id": "hidden_schedule",
                "project_id": hidden_project.id,
            }
        )
    )
    schedules = ScheduleRepository(repository)
    first = schedules.list_definitions(user, page_size=1)
    second = schedules.list_definitions(user, page=2, page_size=1)
    assert first.total_count == second.total_count == 2
    assert len(first.items) == len(second.items) == 1
    assert first.items[0].id != second.items[0].id
    assert all(item.workspace_id == user.workspace_id for item in [*first.items, *second.items])
    with pytest.raises(ScheduleDefinitionError, match="project_not_found"):
        schedules.list_definitions(user, project_id=hidden_project.id)
    project = repository.get_project(user.default_project_id)
    repository.save_project(project.model_copy(update={"member_ids": [foreign_user.id]}))
    assert schedules.list_definitions(user).items == []


def test_execution_owner_and_agent_cannot_be_supplied_by_another_user(schedule_project):
    from pydantic import ValidationError

    repository, user = schedule_project
    with pytest.raises(ValidationError):
        _request(owner_user_id="someone_else")
    with pytest.raises(ScheduleDefinitionError, match="schedule_agent_not_authorized"):
        ScheduleDefinitionService(repository).create(_request(agent_id="someone_else_agent"), user)
    assert not repository.scheduled_agent_task_definitions


def test_another_project_manager_can_pause_but_cannot_restore_a_revoked_owner(schedule_project):
    repository, user = schedule_project
    service = ScheduleDefinitionService(repository)
    definition = service.create(_request(), user)
    manager = repository.save_user(user.model_copy(update={"id": "manager", "personal_agent_id": "agent_manager"}))
    project = repository.get_project(user.default_project_id)
    repository.save_project(project.model_copy(update={"member_ids": [user.id, manager.id]}))
    repository.save_user(user.model_copy(update={"status": "inactive"}))
    paused = service.update(
        definition.id,
        ScheduledAgentTaskUpdateRequest(
            command_id="pause-revoked",
            expected_version=1,
            enabled=False,
        ),
        manager,
    )
    assert paused.owner_user_id == user.id
    assert paused.agent_id == user.personal_agent_id
    with pytest.raises(ScheduleDefinitionError, match="schedule_owner_not_authorized"):
        service.update(
            definition.id,
            ScheduledAgentTaskUpdateRequest(
                command_id="restore-revoked",
                expected_version=2,
                enabled=True,
            ),
            manager,
        )
    assert repository.get_scheduled_agent_task_definition(definition.id) == paused


def test_legacy_enabled_schedule_requires_an_explicit_project_template_resave(schedule_project):
    repository, user = schedule_project
    legacy = repository.save_scheduled_agent_task_definition(
        ScheduledAgentTaskDefinition(
            agent_id="agent_research",
            title="Old schedule",
            prompt="Old prompt",
            schedule="daily@09:30",
            created_by=user.id,
            enabled=True,
        )
    )
    assert legacy.validation_state == "legacy_schedule_unvalidated"
    assert legacy.next_run_at is None
    service = ScheduleDefinitionService(repository)
    with pytest.raises(ScheduleDefinitionError, match="schedule_project_template_required"):
        service.update(
            legacy.id,
            ScheduledAgentTaskUpdateRequest(
                command_id="unbound",
                expected_version=1,
                schedule="30 9 * * *",
            ),
            user,
        )
    upgraded = service.update(
        legacy.id,
        ScheduledAgentTaskUpdateRequest(
            command_id="upgrade",
            expected_version=1,
            project_id=user.default_project_id,
            template_id="blockers",
            schedule="30 9 * * *",
        ),
        user,
    )
    assert upgraded.id == legacy.id
    assert upgraded.version == 2
    assert upgraded.validation_state == "valid"
    assert upgraded.next_run_at is not None
    assert upgraded.agent_id == user.personal_agent_id
    assert upgraded.prompt == "Project inspection: blockers"


def test_schedule_api_accepts_project_task_permission_and_requires_versioned_updates(schedule_project, monkeypatch):
    from fastapi.testclient import TestClient

    from agentmesh.app import app
    from agentmesh.routes import agents as agent_routes
    from agentmesh.routes.deps import current_user

    repository, user = schedule_project
    repository.save_user(user.model_copy(update={"role": "user"}))
    repository.save_permission_policy_rule(
        PermissionPolicyRule(
            role="user",
            action="manage_project_tasks",
            effect="allow",
            description="Only project tasks",
        )
    )
    monkeypatch.setattr(agent_routes, "store", repository)
    app.dependency_overrides[current_user] = lambda: repository.get_user(user.id)
    try:
        client = TestClient(app)
        created = client.post("/api/agents/scheduled-tasks", json=_request().model_dump(mode="json"))
        assert created.status_code == 200, created.text
        definition = created.json()
        unversioned = client.patch(f"/api/agents/scheduled-tasks/{definition['id']}", json={"enabled": False})
        assert unversioned.status_code == 422
        assert repository.get_scheduled_agent_task_definition(definition["id"]).enabled
        paused = client.patch(
            f"/api/agents/scheduled-tasks/{definition['id']}",
            json={
                "command_id": "api-pause",
                "expected_version": 1,
                "enabled": False,
            },
        )
        assert paused.status_code == 200, paused.text
        listed = client.get("/api/agents/scheduled-tasks")
        assert listed.status_code == 200, listed.text
        assert listed.json()["items"][0]["version"] == 2
    finally:
        app.dependency_overrides.pop(current_user, None)


def test_demo_schedule_uses_a_persisted_personal_agent(schedule_project, monkeypatch):
    from agentmesh.seed import TEAM_LEAD, ensure_demo_seed_data

    repository, _ = schedule_project
    monkeypatch.setenv("AGENTMESH_DEMO_MODE", "1")
    ensure_demo_seed_data(repository)
    definition = ScheduleDefinitionService(repository).create(_request(
        project_id=TEAM_LEAD.default_project_id, command_id="demo-schedule",
    ), TEAM_LEAD)
    agent = repository.get_agent(definition.agent_id)
    assert agent.owner_user_id == TEAM_LEAD.id
    assert agent.workspace_id == definition.workspace_id


def test_manual_inspection_cannot_admit_work_after_process_quiesces(schedule_project, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from agentmesh.app import app
    from agentmesh.routes import agents as agent_routes
    from agentmesh.routes.deps import current_user
    from agentmesh.runtime_admission import current_orchestration_admission, install_orchestration_admission
    from agentmesh.skill_runtime.quiesce import OrchestrationQuiesceController

    repository, user = schedule_project
    definition = ScheduleDefinitionService(repository).create(_request(), user)
    monkeypatch.setenv("AGENTMESH_AUTOMATION_MODE", "execute")
    monkeypatch.setattr(agent_routes, "store", repository)
    monkeypatch.setattr(agent_routes, "_inspection_runtime", lambda: SimpleNamespace(enabled=True, wake_dispatch_pump=lambda: None))
    admission = OrchestrationQuiesceController()
    asyncio.run(admission.begin_quiesce())
    previous = current_orchestration_admission()
    install_orchestration_admission(admission)
    app.dependency_overrides[current_user] = lambda: user
    try:
        response = TestClient(app).post(
            f"/api/agents/scheduled-tasks/{definition.id}/run-now",
            json={"command_id": "quiescing", "expected_version": 1},
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "orchestration_quiescing"
        assert not repository.list_agent_runs()
        assert not repository.list_pending_run_dispatches()
    finally:
        install_orchestration_admission(previous)
        app.dependency_overrides.pop(current_user, None)


def test_paused_schedule_still_requires_a_reachable_calendar(schedule_project):
    repository, user = schedule_project
    with pytest.raises(ScheduleDefinitionError, match="schedule_cron_unreachable"):
        ScheduleDefinitionService(repository).create(_request(schedule="0 9 31 2 *", enabled=False), user)
    assert ScheduleDefinitionService(repository).repository.list_definitions(user).total_count == 0
