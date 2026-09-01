from __future__ import annotations

from fastapi.testclient import TestClient

from agentmesh.app import app
from agentmesh.auth import SESSION_COOKIE_NAME, issue_session
from agentmesh.models import Agent, ChatThread, Intent, Project, Task, User
from agentmesh.seed import TEAM_LEAD, USER
from agentmesh.store import store
from tests.test_chat_flow import authenticated_client, clear_store


def test_task_management_is_read_only_by_default(monkeypatch) -> None:
    clear_store()
    monkeypatch.delenv("AGENTMESH_TASK_MANAGEMENT", raising=False)
    client = authenticated_client()

    response = client.post(
        "/api/tasks",
        json={"command_id": "task-create-read-only", "title": "Prepare launch review"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "task_management_read_only"}


def test_invalid_task_management_mode_fails_closed(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "unexpected")
    client = authenticated_client()

    response = client.post(
        "/api/tasks",
        json={"command_id": "task-create-invalid-mode", "title": "Do not create"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "task_management_read_only"}


def test_create_task_is_idempotent_and_persists_a_task_thread(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    client = authenticated_client()
    payload = {
        "command_id": "task-create-001",
        "title": "Prepare launch review",
        "description": "Collect the release evidence and request approval.",
        "task_type": "review",
        "priority": "p1",
        "tags": ["release", "review", "release"],
        "assignee_kind": "user",
        "assignee_id": USER.id,
    }

    created = client.post("/api/tasks", json=payload)
    replayed = client.post("/api/tasks", json=payload)

    assert created.status_code == 201
    assert replayed.status_code == 201
    assert replayed.json() == created.json()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "read_only")
    read_only_replay = client.post("/api/tasks", json=payload)
    assert read_only_replay.status_code == 201
    assert read_only_replay.json()["item"]["task"]["id"] == created.json()["item"]["task"]["id"]
    assert read_only_replay.json()["item"]["allowed_actions"] == []
    item = created.json()["item"]
    assert item["task"]["title"] == payload["title"]
    assert item["management"] == {
        "schema_version": "task-management-v1",
        "description": payload["description"],
        "task_type": "review",
        "delivery_stage": "backlog",
        "priority": "p1",
        "due_at": None,
        "assignee_kind": "user",
        "assignee_id": USER.id,
        "tags": ["release", "review"],
        "blocked_reason": None,
        "blocked_at": None,
        "version": 1,
        "archived_at": None,
        "created_by": USER.id,
        "updated_by": USER.id,
    }
    assert set(item["allowed_actions"]) >= {"edit", "assign", "plan", "cancel"}
    task = store.get_task(item["task"]["id"])
    assert task is not None
    thread = store.get_chat_thread(task.thread_id)
    assert thread is not None
    assert thread.kind == "task"
    assert thread.id not in {
        item["id"] for item in client.get("/api/chat/threads").json()["items"]
    }

    conflict = client.post("/api/tasks", json={**payload, "title": "Different title"})
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "task_command_conflict"}


def test_task_list_returns_created_project_task(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    client = authenticated_client()
    created = client.post(
        "/api/tasks",
        json={
            "command_id": "task-list-001",
            "title": "Review memory lineage",
            "priority": "p2",
            "due_at": "2026-09-05T09:00:00+08:00",
        },
    )
    task_id = created.json()["item"]["task"]["id"]

    response = client.get("/api/tasks", params={"project_id": USER.default_project_id})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["page"] == 1
    assert payload["page_size"] == 50
    assert payload["has_next"] is False
    assert payload["counts"]["backlog"] == 1
    assert [item["task"]["id"] for item in payload["items"]] == [task_id]
    assert client.get("/api/tasks", params={"priority": "p1"}).json()["total"] == 0
    assert client.get(
        "/api/tasks",
        params={"priority": "p2", "due_before": "2026-09-06T00:00:00+08:00"},
    ).json()["total"] == 1


def test_task_list_paginates_more_than_fifty_tasks(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    client = authenticated_client()
    for index in range(51):
        response = client.post(
            "/api/tasks",
            json={"command_id": f"task-page-{index}", "title": f"Task {index:02d}"},
        )
        assert response.status_code == 201

    first = client.get("/api/tasks", params={"page": 1, "page_size": 50}).json()
    second = client.get("/api/tasks", params={"page": 2, "page_size": 50}).json()

    assert first["total"] == 51
    assert len(first["items"]) == 50
    assert first["has_next"] is True
    assert len(second["items"]) == 1
    assert second["has_next"] is False


def test_update_task_uses_version_cas_and_updates_thread_title(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    client = authenticated_client()
    created = client.post(
        "/api/tasks",
        json={"command_id": "task-update-create", "title": "Draft title"},
    ).json()["item"]
    task_id = created["task"]["id"]

    payload = {
        "command_id": "task-update-001",
        "expected_version": 1,
        "title": "Final title",
        "description": "A durable project task.",
        "priority": "p0",
        "tags": ["critical", "task"],
        "assignee_kind": "agent",
        "assignee_id": USER.personal_agent_id,
    }
    updated = client.patch(f"/api/tasks/{task_id}", json=payload)
    replayed = client.patch(f"/api/tasks/{task_id}", json=payload)

    assert updated.status_code == 200
    assert replayed.json() == updated.json()
    item = updated.json()["item"]
    assert item["task"]["title"] == "Final title"
    assert item["management"]["version"] == 2
    assert item["management"]["priority"] == "p0"
    assert item["management"]["assignee_id"] == USER.personal_agent_id
    task = store.get_task(task_id)
    assert task is not None
    assert store.get_chat_thread(task.thread_id).title == "Final title"

    stale = client.patch(
        f"/api/tasks/{task_id}",
        json={
            "command_id": "task-update-stale",
            "expected_version": 1,
            "description": "Stale update",
        },
    )
    assert stale.status_code == 409
    assert stale.json() == {"detail": "task_version_conflict"}

    second = client.post(
        "/api/tasks",
        json={"command_id": "task-update-second-create", "title": "Second task"},
    ).json()["item"]
    reused_for_another_task = client.patch(
        f"/api/tasks/{second['task']['id']}",
        json={
            "command_id": payload["command_id"],
            "expected_version": 1,
            "title": payload["title"],
            "description": payload["description"],
            "priority": payload["priority"],
            "tags": payload["tags"],
            "assignee_kind": payload["assignee_kind"],
            "assignee_id": payload["assignee_id"],
        },
    )
    assert reused_for_another_task.status_code == 409
    assert reused_for_another_task.json() == {"detail": "task_command_conflict"}


def test_editing_a_legacy_task_does_not_rename_its_conversation(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    client = authenticated_client()
    thread = store.add_chat_thread(
        ChatThread(
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="Original conversation",
        )
    )
    task = store.add_task(Task(thread_id=thread.id, intent=Intent.GENERAL_CHAT, title="Legacy task"))

    response = client.patch(
        f"/api/tasks/{task.id}",
        json={
            "command_id": "legacy-task-title",
            "expected_version": 1,
            "title": "Managed legacy task",
        },
    )

    assert response.status_code == 200
    assert response.json()["item"]["management"]["version"] == 2
    assert store.get_chat_thread(thread.id).title == "Original conversation"


def test_task_delivery_transitions_blocking_and_archive(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    client = authenticated_client()
    item = client.post(
        "/api/tasks",
        json={"command_id": "task-transition-create", "title": "Ship task workflow"},
    ).json()["item"]
    task_id = item["task"]["id"]
    version = 1

    invalid = client.post(
        f"/api/tasks/{task_id}/transitions",
        json={"command_id": "task-transition-invalid", "expected_version": version, "action": "complete"},
    )
    assert invalid.status_code == 403
    assert invalid.json() == {"detail": "task_action_forbidden"}

    for action in ("plan", "start"):
        response = client.post(
            f"/api/tasks/{task_id}/transitions",
            json={"command_id": f"task-transition-{action}", "expected_version": version, "action": action},
        )
        assert response.status_code == 200
        version += 1
        assert response.json()["item"]["management"]["version"] == version

    blocked = client.post(
        f"/api/tasks/{task_id}/transitions",
        json={
            "command_id": "task-transition-block",
            "expected_version": version,
            "action": "block",
            "reason": "Waiting for evidence",
        },
    )
    assert blocked.status_code == 200
    version += 1
    assert blocked.json()["item"]["management"]["blocked_reason"] == "Waiting for evidence"
    blocked_progress = client.post(
        f"/api/tasks/{task_id}/transitions",
        json={
            "command_id": "task-transition-blocked-progress",
            "expected_version": version,
            "action": "submit_review",
        },
    )
    assert blocked_progress.status_code == 409
    assert blocked_progress.json() == {"detail": "task_blocked"}

    unblocked = client.post(
        f"/api/tasks/{task_id}/transitions",
        json={"command_id": "task-transition-unblock", "expected_version": version, "action": "unblock"},
    )
    assert unblocked.status_code == 200
    version += 1
    assert unblocked.json()["item"]["management"]["blocked_reason"] is None

    response = client.post(
        f"/api/tasks/{task_id}/transitions",
        json={
            "command_id": "task-transition-submit_review",
            "expected_version": version,
            "action": "submit_review",
        },
    )
    assert response.status_code == 200
    version += 1
    assert "complete" not in response.json()["item"]["allowed_actions"]
    denied_complete = client.post(
        f"/api/tasks/{task_id}/transitions",
        json={
            "command_id": "task-transition-user-complete-denied",
            "expected_version": version,
            "action": "complete",
        },
    )
    assert denied_complete.status_code == 403
    assert denied_complete.json() == {"detail": "task_action_forbidden"}

    lead_client = authenticated_client(TEAM_LEAD.id)
    completed = lead_client.post(
        f"/api/tasks/{task_id}/transitions",
        json={"command_id": "task-transition-complete", "expected_version": version, "action": "complete"},
    )
    assert completed.status_code == 200
    version += 1
    assert "archive" in completed.json()["item"]["allowed_actions"]
    denied_archive = client.post(
        f"/api/tasks/{task_id}/archive",
        json={"command_id": "task-archive-user-denied", "expected_version": version},
    )
    assert denied_archive.status_code == 403
    assert denied_archive.json() == {"detail": "task_action_forbidden"}

    archived = lead_client.post(
        f"/api/tasks/{task_id}/archive",
        json={"command_id": "task-archive-001", "expected_version": version},
    )
    assert archived.status_code == 200
    assert archived.json()["item"]["management"]["archived_at"] is not None
    archived_version = archived.json()["item"]["management"]["version"]
    rejected_update = lead_client.patch(
        f"/api/tasks/{task_id}",
        json={
            "command_id": "task-archived-update",
            "expected_version": archived_version,
            "description": "Archived tasks are immutable",
        },
    )
    rejected_transition = lead_client.post(
        f"/api/tasks/{task_id}/transitions",
        json={
            "command_id": "task-archived-reopen",
            "expected_version": archived_version,
            "action": "reopen",
        },
    )
    assert rejected_update.status_code == 409
    assert rejected_update.json() == {"detail": "task_archived"}
    assert rejected_transition.status_code == 409
    assert rejected_transition.json() == {"detail": "task_archived"}
    assert client.get("/api/tasks").json()["total"] == 0
    assert client.get("/api/tasks", params={"include_archived": True}).json()["total"] == 1
    assert task_id not in {
        card["task"]["id"]
        for card in client.get(
            "/api/blackboard/task-cards",
            params={"project_id": USER.default_project_id},
        ).json()["items"]
    }


def test_project_member_can_read_but_cannot_edit_someone_elses_task(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    owner_client = authenticated_client()
    item = owner_client.post(
        "/api/tasks",
        json={"command_id": "task-member-create", "title": "Shared project task"},
    ).json()["item"]

    project = store.get_project(USER.default_project_id)
    assert project is not None
    member = store.save_user(
        User(
            id="usr_task_member",
            workspace_id=USER.workspace_id,
            default_project_id=project.id,
            name="Task member",
            role="user",
            personal_agent_id="agent_task_member",
        )
    )
    store.save_agent(
        Agent(
            id=member.personal_agent_id,
            workspace_id=member.workspace_id,
            name="Task member Agent",
            agent_type="personal",
            description="Task member personal agent",
            owner_user_id=member.id,
        )
    )
    project.member_ids.append(member.id)
    store.save_project(project)
    _, token = issue_session(store, member)
    member_client = TestClient(app)
    member_client.cookies.set(SESSION_COOKIE_NAME, token)

    listed = member_client.get("/api/tasks")
    assert listed.status_code == 200
    assert [entry["task"]["id"] for entry in listed.json()["items"]] == [item["task"]["id"]]
    assert listed.json()["items"][0]["allowed_actions"] == []
    blackboard_cards = member_client.get(
        "/api/blackboard/task-cards",
        params={"project_id": project.id},
    )
    assert blackboard_cards.status_code == 200
    assert [card["task"]["id"] for card in blackboard_cards.json()["items"]] == [item["task"]["id"]]

    denied = member_client.patch(
        f"/api/tasks/{item['task']['id']}",
        json={"command_id": "task-member-denied", "expected_version": 1, "description": "No access"},
    )
    assert denied.status_code == 403
    assert denied.json() == {"detail": "task_action_forbidden"}


def test_assigned_member_can_see_and_manage_a_materialized_legacy_task(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    authenticated_client()
    project = store.get_project(USER.default_project_id)
    assert project is not None
    member = store.save_user(
        User(
            id="usr_legacy_assignee",
            workspace_id=USER.workspace_id,
            default_project_id=project.id,
            name="Legacy assignee",
            role="user",
            personal_agent_id="agent_legacy_assignee",
        )
    )
    project.member_ids.append(member.id)
    store.save_project(project)
    thread = store.add_chat_thread(
        ChatThread(
            workspace_id=USER.workspace_id,
            project_id=project.id,
            user_id=USER.id,
            title="Legacy owner conversation",
        )
    )
    task = store.add_task(Task(thread_id=thread.id, intent=Intent.GENERAL_CHAT, title="Legacy assignment"))
    lead_client = authenticated_client(TEAM_LEAD.id)
    assigned = lead_client.patch(
        f"/api/tasks/{task.id}",
        json={
            "command_id": "legacy-assign-member",
            "expected_version": 1,
            "assignee_kind": "user",
            "assignee_id": member.id,
        },
    )
    assert assigned.status_code == 200

    _, token = issue_session(store, member)
    member_client = TestClient(app)
    member_client.cookies.set(SESSION_COOKIE_NAME, token)
    assert member_client.get(f"/api/tasks/{task.id}").status_code == 200
    cards = member_client.get(
        "/api/blackboard/task-cards",
        params={"project_id": project.id},
    ).json()["items"]
    assert task.id in {card["task"]["id"] for card in cards}
    updated = member_client.patch(
        f"/api/tasks/{task.id}",
        json={
            "command_id": "legacy-assignee-update",
            "expected_version": 2,
            "description": "Assignee can maintain the task",
        },
    )
    assert updated.status_code == 200


def test_cross_project_assignment_is_rejected(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    owner_client = authenticated_client()
    task = owner_client.post(
        "/api/tasks",
        json={"command_id": "cross-project-create", "title": "Scoped assignment"},
    ).json()["item"]
    other_project = store.save_project(
        Project(
            id="prj_other_task_assignment",
            workspace_id=USER.workspace_id,
            name="Other task project",
            goal="Keep assignment scoped",
            member_ids=["usr_other_task_member"],
        )
    )
    outsider = store.save_user(
        User(
            id="usr_other_task_member",
            workspace_id=USER.workspace_id,
            default_project_id=other_project.id,
            name="Other project member",
            role="user",
            personal_agent_id="agent_other_task_member",
        )
    )
    lead_client = authenticated_client(TEAM_LEAD.id)

    response = lead_client.patch(
        f"/api/tasks/{task['task']['id']}",
        json={
            "command_id": "cross-project-assign",
            "expected_version": 1,
            "assignee_kind": "user",
            "assignee_id": outsider.id,
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "task_assignee_not_found"}


def test_team_lead_can_manage_project_task(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    owner_client = authenticated_client()
    item = owner_client.post(
        "/api/tasks",
        json={"command_id": "task-lead-create", "title": "Lead managed task"},
    ).json()["item"]
    lead_client = authenticated_client(TEAM_LEAD.id)

    response = lead_client.patch(
        f"/api/tasks/{item['task']['id']}",
        json={
            "command_id": "task-lead-update",
            "expected_version": 1,
            "priority": "p1",
            "assignee_kind": "user",
            "assignee_id": TEAM_LEAD.id,
        },
    )

    assert response.status_code == 200
    assert response.json()["item"]["management"]["assignee_id"] == TEAM_LEAD.id


def test_bootstrap_exposes_task_management_mode(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    client = authenticated_client()

    response = client.get("/api/bootstrap")

    assert response.status_code == 200
    assert response.json()["task_management_mode"] == "write"


def test_task_routes_require_authentication(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    client = TestClient(app)

    assert client.get("/api/tasks").status_code == 401
    assert client.post(
        "/api/tasks",
        json={"command_id": "task-anonymous", "title": "Anonymous task"},
    ).status_code == 401
