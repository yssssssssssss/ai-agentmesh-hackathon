from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from agentmesh.app import app
from agentmesh.models import ActivityLog, AuditEvent, ChatThread, Intent, Project, Scope, Task, UserRole, now_utc
from agentmesh.seed import ADMIN, PROJECT, TEAM_LEAD, USER, WORKSPACE
from agentmesh.store import store


def authenticated_client(user_id: str = USER.id) -> TestClient:
    client = TestClient(app)
    password = {
        USER.id: "designer123",
        TEAM_LEAD.id: "lead123",
        ADMIN.id: "admin123",
    }[user_id]
    response = client.post("/api/auth/login", json={"user_id": user_id, "password": password})
    assert response.status_code == 200
    return client


def test_personal_agent_read_model_uses_canonical_runtime_hydration() -> None:
    store.reset()
    client = authenticated_client()
    post_response = client.post(
        "/api/blackboard/posts",
        json={
            "post_type": "request",
            "title": "Personal runtime marker",
            "content": "Keep this request active while Digital Self reads runtime state.",
            "scope": "project",
            "permission": "project_visible",
        },
    )
    assert post_response.status_code == 200
    post = post_response.json()["item"]
    lock_response = client.post(
        f"/api/blackboard/posts/{post['id']}/lock",
        json={"owner_agent_id": USER.personal_agent_id},
    )
    assert lock_response.status_code == 200

    response = client.get("/api/agents/me")

    assert response.status_code == 200
    payload = response.json()
    assert payload["runtime_status"] == "running"
    assert payload["current_task_id"] == post["task_id"]
    assert payload["current_task_title"] == "Personal runtime marker"


def test_insights_read_models_require_project_and_isolate_date_project_and_counts() -> None:
    store.reset()
    client = authenticated_client()
    other_project = store.save_project(
        Project(
            id="prj_read_model_other",
            workspace_id=WORKSPACE.id,
            name="Other project",
            goal="Must not leak into current project Insights",
            member_ids=[USER.id],
        )
    )
    target_thread = store.add_chat_thread(
        ChatThread(
            id="thread_read_model_target",
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
            user_id=USER.id,
            title="Current project task",
        )
    )
    other_thread = store.add_chat_thread(
        ChatThread(
            id="thread_read_model_other",
            workspace_id=WORKSPACE.id,
            project_id=other_project.id,
            user_id=USER.id,
            title="Other project task",
        )
    )
    target_task = store.add_task(Task(thread_id=target_thread.id, intent=Intent.GENERAL_CHAT, title="Visible task"))
    store.add_task(Task(thread_id=other_thread.id, intent=Intent.GENERAL_CHAT, title="Hidden task"))
    today = now_utc()
    visible_activity = store.add_activity_log(
        ActivityLog(
            actor=USER.personal_agent_id,
            user_id=USER.id,
            title="Visible activity",
            summary="Current day and project",
            category="personal",
            scope=Scope.PRIVATE,
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
            created_at=today,
        )
    )
    store.add_activity_log(
        ActivityLog(
            actor=USER.personal_agent_id,
            user_id=USER.id,
            title="Historical activity",
            summary="Same project, previous day",
            category="personal",
            scope=Scope.PRIVATE,
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
            created_at=today - timedelta(days=1),
        )
    )
    store.add_activity_log(
        ActivityLog(
            actor=USER.personal_agent_id,
            user_id=USER.id,
            title="Cross-project activity",
            summary="Current day, other project",
            category="personal",
            scope=Scope.PRIVATE,
            workspace_id=WORKSPACE.id,
            project_id=other_project.id,
            created_at=today,
        )
    )
    visible_audit = store.add_audit_event(
        AuditEvent(
            actor=USER.id,
            action="visible_action",
            target_type="task",
            target_id=target_task.id,
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
        )
    )
    store.add_audit_event(
        AuditEvent(
            actor=USER.id,
            action="hidden_action",
            target_type="task",
            target_id="task_other",
            workspace_id=WORKSPACE.id,
            project_id=other_project.id,
        )
    )

    assert client.get("/api/activity/today").status_code == 422
    assert client.get("/api/blackboard/task-cards").status_code == 422
    assert client.get("/api/insights/audit").status_code == 422

    activity = client.get("/api/activity/today", params={"project_id": PROJECT.id})
    tasks = client.get("/api/blackboard/task-cards", params={"project_id": PROJECT.id})
    audit = client.get("/api/insights/audit", params={"project_id": PROJECT.id, "limit": 20})

    assert activity.status_code == 200
    assert {item["id"] for item in activity.json()["personal"]} == {visible_activity.id}
    assert tasks.status_code == 200
    assert {item["task"]["id"] for item in tasks.json()["items"]} == {target_task.id}
    assert audit.status_code == 200
    assert [item["id"] for item in audit.json()["items"]] == [visible_audit.id]
    assert audit.json()["total"] == 1
    assert audit.json()["counts"] == {"visible_action": 1}


def test_admin_and_team_lead_roles_do_not_bypass_project_membership() -> None:
    store.reset()
    authenticated_client()
    restricted_project = store.save_project(
        Project(
            id="prj_read_model_restricted",
            workspace_id=WORKSPACE.id,
            name="Restricted project",
            goal="Only the current designer is a member",
            member_ids=[USER.id],
        )
    )

    for principal in (ADMIN, TEAM_LEAD):
        assert principal.role in {UserRole.ADMIN, UserRole.TEAM_LEAD}
        client = authenticated_client(principal.id)
        assert client.get("/api/activity/today", params={"project_id": restricted_project.id}).status_code == 404
        assert client.get("/api/blackboard/task-cards", params={"project_id": restricted_project.id}).status_code == 404
        assert client.get("/api/insights/audit", params={"project_id": restricted_project.id}).status_code == 404
