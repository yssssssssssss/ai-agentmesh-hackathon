"""Regression coverage for the MVP cross-user privacy boundary."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from agentmesh.agents import ChatThreadNotFoundError
from agentmesh.app import app
from agentmesh.models import ActivityLog, DocumentParseJob, DocumentRecord, MemoryItem, Project, Scope, Source
from agentmesh.routes import chat as chat_routes
from agentmesh.seed import ADMIN, PROJECT, TEAM_LEAD, USER, WORKSPACE
from agentmesh.store import store

PASSWORDS = {
    USER.id: "designer123",
    TEAM_LEAD.id: "lead123",
    ADMIN.id: "admin123",
}


def setup_function() -> None:
    store.reset()


def authenticated_client(user_id: str) -> TestClient:
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"user_id": user_id, "password": PASSWORDS[user_id]})
    assert response.status_code == 200
    return client


def add_document(owner_id: str, suffix: str) -> DocumentRecord:
    return store.add_document(
        DocumentRecord(
            title=f"隔离文档 {suffix}",
            file_name=f"isolation-{suffix}.md",
            content_type="text/markdown",
            text=f"private-document-{suffix} 仅文档所有者可见。",
            source=Source(
                title=f"isolation-{suffix}.md",
                source_type="document",
                reference=f"document://isolation-{suffix}.md",
            ),
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
            uploaded_by=owner_id,
        )
    )


def test_foreign_thread_is_rejected_before_history_read_or_write(monkeypatch: pytest.MonkeyPatch) -> None:
    owner_client = authenticated_client(USER.id)
    other_client = authenticated_client(TEAM_LEAD.id)
    created = owner_client.post("/api/chat/threads", json={"title": "Owner private thread"})
    assert created.status_code == 200
    thread = created.json()["thread"]

    first_turn = owner_client.post(
        "/api/chat/messages",
        json={"thread_id": thread["id"], "content": "owner-only-context-marker"},
    )
    assert first_turn.status_code == 200
    message_ids_before = [message.id for message in store.list_thread_messages(thread["id"])]

    history_was_read = False
    original_get_history = chat_routes.agent._get_thread_history

    def record_history_read(thread_id: str):
        nonlocal history_was_read
        history_was_read = True
        return original_get_history(thread_id)

    monkeypatch.setattr(chat_routes.agent, "_get_thread_history", record_history_read)

    response = other_client.post(
        "/api/chat/messages",
        json={"thread_id": thread["id"], "content": "foreign write attempt"},
    )

    assert response.status_code == 404
    assert history_was_read is False
    assert [message.id for message in store.list_thread_messages(thread["id"])] == message_ids_before
    with pytest.raises(ChatThreadNotFoundError):
        chat_routes.agent._ensure_thread(thread["id"], "defense in depth", TEAM_LEAD)


def test_supplied_nonexistent_thread_id_is_not_claimed() -> None:
    client = authenticated_client(USER.id)

    response = client.post(
        "/api/chat/messages",
        json={"thread_id": "thread_caller_chosen", "content": "claim this id"},
    )

    assert response.status_code == 404
    assert store.get_chat_thread("thread_caller_chosen") is None


def test_private_chat_search_is_owner_only() -> None:
    owner_client = authenticated_client(USER.id)
    other_client = authenticated_client(TEAM_LEAD.id)
    turn = owner_client.post("/api/chat/messages", json={"content": "m2-private-thread-search-marker"})
    assert turn.status_code == 200
    private_message_id = turn.json()["user_message"]["id"]

    owner_results = owner_client.get("/api/search", params={"q": "m2-private-thread-search-marker"})
    other_results = other_client.get("/api/search", params={"q": "m2-private-thread-search-marker"})

    assert owner_results.status_code == 200
    assert private_message_id in {item["id"] for item in owner_results.json()["items"]}
    assert other_results.status_code == 200
    assert private_message_id not in {item["id"] for item in other_results.json()["items"]}


def test_search_rejects_workspace_and_inaccessible_project_overrides() -> None:
    client = authenticated_client(USER.id)
    inaccessible_project = store.save_project(
        Project(
            workspace_id=WORKSPACE.id,
            name="Unrelated project",
            goal="Must not be searchable by the current user",
            member_ids=[TEAM_LEAD.id],
        )
    )

    wrong_workspace = client.get("/api/search", params={"q": "anything", "workspace_id": "ws_unrelated"})
    wrong_project = client.get(
        "/api/search",
        params={"q": "anything", "project_id": inaccessible_project.id},
    )
    missing_project = client.get("/api/search", params={"q": "anything", "project_id": "prj_missing"})
    default_project = client.get("/api/search", params={"q": "anything"})

    assert wrong_workspace.status_code == 404
    assert wrong_project.status_code == 404
    assert missing_project.status_code == 404
    assert default_project.status_code == 200


def test_private_governed_memory_search_is_owner_only() -> None:
    owner_client = authenticated_client(USER.id)
    other_client = authenticated_client(TEAM_LEAD.id)
    item = store.add_memory_item(
        MemoryItem(
            title="Private governed memory",
            summary="m2-private-governed-memory-marker",
            memory_type="note",
            scope=Scope.PRIVATE,
            owner_user_id=USER.id,
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
        )
    )

    owner_results = owner_client.get("/api/search", params={"q": "m2-private-governed-memory-marker"})
    other_results = other_client.get("/api/search", params={"q": "m2-private-governed-memory-marker"})

    assert item.id in {result["id"] for result in owner_results.json()["items"]}
    assert item.id not in {result["id"] for result in other_results.json()["items"]}
    assert item.id not in {result.id for result in chat_routes.agent._memory_search_pool(TEAM_LEAD)}



def test_private_activity_is_owner_only_in_feed_and_search() -> None:
    owner_client = authenticated_client(USER.id)
    other_client = authenticated_client(TEAM_LEAD.id)
    activity = store.add_activity_log(
        ActivityLog(
            actor=USER.personal_agent_id,
            user_id=USER.id,
            title="Private activity",
            summary="m2-private-activity-marker",
            category="personal",
            scope=Scope.PRIVATE,
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
        )
    )

    owner_feed = owner_client.get("/api/activity/today", params={"project_id": PROJECT.id}).json()["personal"]
    other_feed = other_client.get("/api/activity/today", params={"project_id": PROJECT.id}).json()["personal"]
    owner_search = owner_client.get("/api/search", params={"q": "m2-private-activity-marker"}).json()["items"]
    other_search = other_client.get("/api/search", params={"q": "m2-private-activity-marker"}).json()["items"]

    assert activity.id in {item["id"] for item in owner_feed}
    assert activity.id not in {item["id"] for item in other_feed}
    assert activity.id in {item["id"] for item in owner_search}
    assert activity.id not in {item["id"] for item in other_search}

def test_document_list_and_detail_are_owner_only_with_admin_access() -> None:
    owner_client = authenticated_client(USER.id)
    other_client = authenticated_client(TEAM_LEAD.id)
    admin_client = authenticated_client(ADMIN.id)
    owner_document = add_document(USER.id, "owner-list")
    other_document = add_document(TEAM_LEAD.id, "other-list")

    owner_ids = {item["id"] for item in owner_client.get("/api/documents").json()["items"]}
    other_ids = {item["id"] for item in other_client.get("/api/documents").json()["items"]}
    admin_ids = {item["id"] for item in admin_client.get("/api/documents").json()["items"]}

    assert owner_document.id in owner_ids
    assert other_document.id not in owner_ids
    assert other_document.id in other_ids
    assert owner_document.id not in other_ids
    assert {owner_document.id, other_document.id}.issubset(admin_ids)
    assert owner_client.get(f"/api/documents/{owner_document.id}").status_code == 200
    assert other_client.get(f"/api/documents/{owner_document.id}").status_code == 404
    assert admin_client.get(f"/api/documents/{owner_document.id}").status_code == 200


def test_document_update_and_import_allow_only_owner_or_admin() -> None:
    owner_client = authenticated_client(USER.id)
    other_client = authenticated_client(TEAM_LEAD.id)
    admin_client = authenticated_client(ADMIN.id)
    owner_document = add_document(USER.id, "owner-actions")
    admin_document = add_document(USER.id, "admin-actions")

    assert other_client.patch(
        f"/api/documents/{owner_document.id}",
        json={"text": "foreign replacement", "expected_version": owner_document.version},
    ).status_code == 404
    owner_update = owner_client.patch(
        f"/api/documents/{owner_document.id}",
        json={"text": "owner replacement", "expected_version": owner_document.version},
    )
    admin_update = admin_client.patch(
        f"/api/documents/{admin_document.id}",
        json={"text": "admin replacement", "expected_version": admin_document.version},
    )
    assert owner_update.status_code == 200
    assert admin_update.status_code == 200

    assert other_client.post(f"/api/documents/{owner_document.id}/import-to-memory").status_code == 404
    owner_import = owner_client.post(f"/api/documents/{owner_document.id}/import-to-memory")
    admin_import = admin_client.post(f"/api/documents/{admin_document.id}/import-to-memory")
    assert owner_import.status_code == 200
    assert owner_import.json()["status"] == "imported"
    assert admin_import.status_code == 200
    assert admin_import.json()["status"] == "imported"


def test_document_patch_atomically_rejects_concurrent_and_stale_versions() -> None:
    first_client = authenticated_client(USER.id)
    second_client = authenticated_client(USER.id)
    document = add_document(USER.id, "concurrent-version")
    expected_version = document.version

    def patch(client: TestClient, text: str):
        return client.patch(
            f"/api/documents/{document.id}",
            json={"text": text, "expected_version": expected_version},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda args: patch(*args),
                [(first_client, "concurrent winner one"), (second_client, "concurrent winner two")],
            )
        )

    assert sorted(response.status_code for response in responses) == [200, 409]
    persisted = store.get_document(document.id)
    assert persisted is not None
    assert persisted.version == expected_version + 1
    assert persisted.text in {"concurrent winner one", "concurrent winner two"}

    stale = first_client.patch(
        f"/api/documents/{document.id}",
        json={"text": "stale loser", "expected_version": expected_version},
    )
    assert stale.status_code == 409
    assert store.get_document(document.id).model_dump() == persisted.model_dump()


def test_memory_list_validates_and_filters_requested_project() -> None:
    client = authenticated_client(USER.id)
    other_project = store.save_project(
        Project(
            id="prj_memory_other",
            workspace_id=WORKSPACE.id,
            name="Other visible memory project",
            goal="Project filter regression",
            member_ids=[USER.id],
        )
    )
    inaccessible_project = store.save_project(
        Project(
            id="prj_memory_inaccessible",
            workspace_id=WORKSPACE.id,
            name="Inaccessible memory project",
            goal="Access validation regression",
            member_ids=[TEAM_LEAD.id],
        )
    )
    current = store.add_memory_item(
        MemoryItem(
            id="mem_project_current",
            title="Current project memory",
            summary="Only the default project should return this item.",
            memory_type="standard",
            scope=Scope.TEAM_ACCEPTED,
            status="accepted",
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
        )
    )
    other = store.add_memory_item(
        MemoryItem(
            id="mem_project_other",
            title="Other project memory",
            summary="Only the explicitly selected project should return this item.",
            memory_type="standard",
            scope=Scope.TEAM_ACCEPTED,
            status="accepted",
            workspace_id=WORKSPACE.id,
            project_id=other_project.id,
        )
    )

    default_response = client.get("/api/memory")
    other_response = client.get("/api/memory", params={"project_id": other_project.id})
    inaccessible_response = client.get("/api/memory", params={"project_id": inaccessible_project.id})

    assert default_response.status_code == 200
    assert {item["id"] for item in default_response.json()["items"]} == {current.id}
    assert other_response.status_code == 200
    assert {item["id"] for item in other_response.json()["items"]} == {other.id}
    assert inaccessible_response.status_code == 404


def test_document_jobs_are_owner_only_with_admin_access() -> None:
    owner_client = authenticated_client(USER.id)
    other_client = authenticated_client(TEAM_LEAD.id)
    admin_client = authenticated_client(ADMIN.id)
    owner_job = store.save_document_parse_job(
        DocumentParseJob(
            file_name="owner-job.md",
            content_type="text/markdown",
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
            uploaded_by=USER.id,
        )
    )
    other_job = store.save_document_parse_job(
        DocumentParseJob(
            file_name="other-job.md",
            content_type="text/markdown",
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
            uploaded_by=TEAM_LEAD.id,
        )
    )

    owner_ids = {item["id"] for item in owner_client.get("/api/documents/jobs").json()["items"]}
    other_ids = {item["id"] for item in other_client.get("/api/documents/jobs").json()["items"]}
    admin_ids = {item["id"] for item in admin_client.get("/api/documents/jobs").json()["items"]}

    assert owner_job.id in owner_ids
    assert other_job.id not in owner_ids
    assert other_job.id in other_ids
    assert owner_job.id not in other_ids
    assert {owner_job.id, other_job.id}.issubset(admin_ids)
    assert owner_client.get(f"/api/documents/jobs/{owner_job.id}").status_code == 200
    assert other_client.get(f"/api/documents/jobs/{owner_job.id}").status_code == 404
    assert admin_client.get(f"/api/documents/jobs/{owner_job.id}").status_code == 200
