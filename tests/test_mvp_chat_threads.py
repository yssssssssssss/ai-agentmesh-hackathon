from __future__ import annotations

import json
from datetime import timedelta

from fastapi.testclient import TestClient

from agentmesh.app import app
from agentmesh.auth import SESSION_COOKIE_NAME, issue_session
from agentmesh.models import (
    ChatMessage,
    ChatRole,
    ChatThread,
    MemoryLayer,
    Project,
    Scope,
    User,
    UserMemoryItem,
    Workspace,
    now_utc,
)
from agentmesh.seed import PROJECT, TEAM_LEAD, USER, WORKSPACE
from agentmesh.store import store

PASSWORDS = {
    USER.id: "designer123",
    TEAM_LEAD.id: "lead123",
}


def setup_function() -> None:
    store.reset()


def authenticated_client(user_id: str) -> TestClient:
    client = TestClient(app)
    response = client.post(
        "/api/auth/login",
        json={"user_id": user_id, "password": PASSWORDS[user_id]},
    )
    assert response.status_code == 200
    return client


def add_thread(owner_id: str, title: str, *, updated_at=None) -> ChatThread:
    timestamp = updated_at or now_utc()
    return store.add_chat_thread(
        ChatThread(
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
            user_id=owner_id,
            title=title,
            created_at=timestamp,
            updated_at=timestamp,
        )
    )


def test_thread_list_and_detail_are_owner_only_and_messages_are_ordered() -> None:
    owner = authenticated_client(USER.id)
    other = authenticated_client(TEAM_LEAD.id)
    owner_thread = add_thread(USER.id, "Owner workspace thread")
    foreign_thread = add_thread(TEAM_LEAD.id, "Foreign workspace thread")
    later = now_utc()
    earlier = later - timedelta(minutes=5)
    second = store.add_chat_message(
        ChatMessage(
            id="msg_second",
            thread_id=owner_thread.id,
            role=ChatRole.ASSISTANT,
            content="second",
            scope=Scope.PRIVATE,
            created_at=later,
        )
    )
    first = store.add_chat_message(
        ChatMessage(
            id="msg_first",
            thread_id=owner_thread.id,
            role=ChatRole.USER,
            content="first",
            scope=Scope.PRIVATE,
            created_at=earlier,
        )
    )

    listed = owner.get("/api/chat/threads")
    detail = owner.get(f"/api/chat/threads/{owner_thread.id}")

    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [owner_thread.id]
    assert detail.status_code == 200
    assert detail.json()["thread"]["id"] == owner_thread.id
    assert [item["id"] for item in detail.json()["messages"]] == [first.id, second.id]
    assert other.get(f"/api/chat/threads/{owner_thread.id}").status_code == 404
    assert owner.get(f"/api/chat/threads/{foreign_thread.id}").status_code == 404
    assert owner.get("/api/chat/threads/thread_missing").status_code == 404
    assert TestClient(app).get(f"/api/chat/threads/{owner_thread.id}").status_code == 401

def test_thread_detail_reads_legacy_turn_trace_without_confidence() -> None:
    client = authenticated_client(USER.id)
    thread = add_thread(USER.id, "Legacy turn trace")
    user_message = store.add_chat_message(
        ChatMessage(thread_id=thread.id, role=ChatRole.USER, content="legacy question", scope=Scope.PRIVATE)
    )
    assistant_message = store.add_chat_message(
        ChatMessage(thread_id=thread.id, role=ChatRole.ASSISTANT, content="legacy answer", scope=Scope.PRIVATE)
    )
    legacy_trace = {
        "id": "trace_legacy_without_confidence",
        "thread_id": thread.id,
        "user_message_id": user_message.id,
        "assistant_message_id": assistant_message.id,
        "intent": "general_chat",
        "source": "legacy",
        "selected_workflow": "legacy_chat",
        "persisted": True,
        "llm_used": False,
        "created_at": now_utc().isoformat(),
    }
    with store._connect() as connection:
        connection.execute(
            "INSERT INTO records(collection, id, payload) VALUES (?, ?, ?)",
            ("chat_turn_traces", legacy_trace["id"], json.dumps(legacy_trace)),
        )

    response = client.get(f"/api/chat/threads/{thread.id}")

    assert response.status_code == 200
    assert response.json()["turn_traces"][0]["confidence"] == 0.0


def test_persisting_message_touches_thread_and_moves_it_to_top_of_list() -> None:
    client = authenticated_client(USER.id)
    recent = add_thread(USER.id, "Recent", updated_at=now_utc() - timedelta(minutes=5))
    stale = add_thread(USER.id, "Stale", updated_at=now_utc() - timedelta(days=1))
    stale_updated_at = stale.updated_at

    store.add_chat_message(
        ChatMessage(
            thread_id=stale.id,
            role=ChatRole.USER,
            content="new activity",
            scope=Scope.PRIVATE,
            created_at=now_utc() - timedelta(days=2),
        )
    )

    refreshed = store.get_chat_thread(stale.id)
    listed = client.get("/api/chat/threads")

    assert refreshed is not None
    assert refreshed.updated_at > stale_updated_at
    assert refreshed.updated_at > recent.updated_at
    assert [item["id"] for item in listed.json()["items"]] == [stale.id, recent.id]


def test_thread_detail_persists_source_and_provider_trace_across_reads() -> None:
    client = authenticated_client(USER.id)
    created = client.post("/api/chat/threads", json={"title": "Provider trace"})
    thread_id = created.json()["thread"]["id"]

    sent = client.post(
        "/api/chat/messages",
        json={
            "thread_id": thread_id,
            "content": "$research.request 查找 618 家电会场历史项目",
        },
    )
    detail = client.get(f"/api/chat/threads/{thread_id}")

    assert sent.status_code == 200
    assert detail.status_code == 200
    assistant = detail.json()["messages"][-1]
    assert assistant["role"] == "assistant"
    assert assistant["sources"]
    assert assistant["sources"][0]["title"]
    assert assistant["sources"][0]["reference"]
    assert assistant["workflow_trace"]["requested_provider"] == "research"
    assert assistant["workflow_trace"]["actual_provider"] == "mock"
    assert assistant["workflow_trace"]["provider_mode"] == "fallback"
    assert assistant["workflow_trace"]["fallback_reason"] == "no_real_provider_configured"
    assert assistant["workflow_trace"]["latency_ms"] == 0.0
    assert "provider" not in assistant["workflow_trace"]
    assert assistant["workflow_trace"]["persisted"] is True


def test_thread_detail_returns_owner_scoped_turn_traces_with_memory_provenance() -> None:
    owner = authenticated_client(USER.id)
    other = authenticated_client(TEAM_LEAD.id)
    memory = store.add_user_memory_item(
        UserMemoryItem(
            user_id=USER.id,
            layer=MemoryLayer.SHORT_TERM,
            title="Canonical detail memory",
            summary="canonical detail memory trace",
            source_kind="note",
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
        )
    )

    sent = owner.post(
        "/api/chat/messages",
        json={"content": "$memory.personal canonical detail memory trace"},
    )
    thread_id = sent.json()["thread_id"]
    detail = owner.get(f"/api/chat/threads/{thread_id}")

    assert sent.status_code == 200
    assert detail.status_code == 200
    assert TestClient(app).get(f"/api/chat/threads/{thread_id}").status_code == 401
    assert other.get(f"/api/chat/threads/{thread_id}").status_code == 404
    assert owner.get("/api/chat/threads/thread_missing").status_code == 404

    payload = detail.json()
    assert set(payload) == {"thread", "messages", "turn_traces"}
    messages = payload["messages"]
    traces = payload["turn_traces"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert len(traces) == 1

    trace = traces[0]
    assert trace["thread_id"] == thread_id
    assert trace["user_message_id"] == messages[0]["id"]
    assert trace["assistant_message_id"] == messages[-1]["id"]
    assert trace["intent"] == "ask_memory"
    assert trace["selected_workflow"] == "$memory.personal"
    assert "searched_memory" in trace["steps"]
    assert trace["sources"] == messages[-1]["sources"]
    message_trace = messages[-1]["workflow_trace"]
    for field in (
        "confidence",
        "requested_provider",
        "actual_provider",
        "requested_model",
        "actual_model",
        "provider_mode",
        "latency_ms",
        "fallback_reason",
        "model_fallback_reason",
    ):
        assert trace[field] == message_trace[field]

    memory_search = trace["memory_search"]
    assert memory_search["requested_scope"] == "personal"
    assert memory_search["personal_count"] == 1
    assert memory_search["project_count"] == 0
    assert memory_search["team_count"] == 0
    assert memory_search["results"][0]["result_id"] == memory.id
    assert memory_search["results"][0]["citation_label"] == "P1"



def test_client_turn_retry_returns_the_same_canonical_turn_without_duplicate_side_effects() -> None:
    client = authenticated_client(USER.id)
    client_turn_id = "turn_workspace_retry_001"
    before_tasks = len(store.tasks)
    before_posts = len(store.blackboard_posts)

    first = client.post(
        "/api/chat/messages",
        json={
            "content": "$research.request 幂等发送验证",
            "client_turn_id": client_turn_id,
        },
    )
    after_first_tasks = len(store.tasks)
    after_first_posts = len(store.blackboard_posts)
    retry = client.post(
        "/api/chat/messages",
        json={
            "content": "$research.request 幂等发送验证",
            "client_turn_id": client_turn_id,
        },
    )

    assert first.status_code == 200
    assert retry.status_code == 200
    assert retry.json() == first.json()
    assert after_first_tasks == before_tasks + 1
    assert len(store.tasks) == after_first_tasks
    assert after_first_posts > before_posts
    assert len(store.blackboard_posts) == after_first_posts
    thread_id = first.json()["thread_id"]
    assert len(store.list_thread_messages(thread_id)) == 2
    assert [item["id"] for item in client.get("/api/chat/threads").json()["items"]] == [thread_id]


def test_client_turn_id_rejects_changed_payload_and_reports_canonical_state() -> None:
    client = authenticated_client(USER.id)
    client_turn_id = "turn_workspace_payload_conflict"
    sent = client.post(
        "/api/chat/messages",
        json={"content": "原始消息", "client_turn_id": client_turn_id},
    )
    conflict = client.post(
        "/api/chat/messages",
        json={"content": "被修改的消息", "client_turn_id": client_turn_id},
    )

    assert sent.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == {
        "client_turn_id": client_turn_id,
        "state": "completed",
        "thread_id": sent.json()["thread_id"],
        "reason": "payload_mismatch",
    }
    assert len(store.list_thread_messages(sent.json()["thread_id"])) == 2


def test_failed_client_turn_is_terminal_and_retry_does_not_repeat_partial_side_effects(monkeypatch) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    login = client.post(
        "/api/auth/login",
        json={"user_id": USER.id, "password": PASSWORDS[USER.id]},
    )
    assert login.status_code == 200
    client_turn_id = "turn_workspace_ambiguous_failure"

    def fail_after_user_message(*, content, thread_id, user):
        assert thread_id is not None
        store.add_chat_message(
            ChatMessage(
                thread_id=thread_id,
                role=ChatRole.USER,
                content=content,
                scope=Scope.PRIVATE,
            )
        )
        raise RuntimeError("provider response lost")

    monkeypatch.setattr("agentmesh.routes.chat.agent.handle_chat", fail_after_user_message)
    first = client.post(
        "/api/chat/messages",
        json={"content": "只执行一次", "client_turn_id": client_turn_id},
    )
    message_count = len(store.chat_messages)
    retry = client.post(
        "/api/chat/messages",
        json={"content": "只执行一次", "client_turn_id": client_turn_id},
    )

    assert first.status_code == 500
    assert retry.status_code == 409
    assert retry.json()["detail"]["client_turn_id"] == client_turn_id
    assert retry.json()["detail"]["state"] == "failed"
    assert retry.json()["detail"]["reason"] == "prior_attempt_not_retryable"
    assert len(store.chat_messages) == message_count


def test_client_turn_receipts_are_user_scoped() -> None:
    owner = authenticated_client(USER.id)
    other = authenticated_client(TEAM_LEAD.id)
    client_turn_id = "turn_workspace_cross_user"

    owner_sent = owner.post(
        "/api/chat/messages",
        json={"content": "owner turn", "client_turn_id": client_turn_id},
    )
    hidden = other.get(f"/api/chat/messages/receipts/{client_turn_id}")
    other_sent = other.post(
        "/api/chat/messages",
        json={"content": "other turn", "client_turn_id": client_turn_id},
    )

    assert owner_sent.status_code == 200
    assert hidden.status_code == 404
    assert other_sent.status_code == 200
    assert other_sent.json()["thread_id"] != owner_sent.json()["thread_id"]
    assert other_sent.json()["user_message"]["id"] != owner_sent.json()["user_message"]["id"]
    receipt = other.get(f"/api/chat/messages/receipts/{client_turn_id}")
    assert receipt.status_code == 200
    assert receipt.json()["response"] == other_sent.json()
    assert receipt.json()["status"] == "completed"


def test_create_thread_uses_current_user_tenant_and_remains_visible() -> None:
    workspace = store.save_workspace(
        Workspace(id="ws_custom_chat", name="Custom chat workspace", description="Tenant isolation test")
    )
    project = store.save_project(
        Project(
            id="prj_custom_chat",
            workspace_id=workspace.id,
            name="Custom chat project",
            goal="Keep created threads in the current tenant",
            member_ids=["usr_custom_chat"],
        )
    )
    user = store.save_user(
        User(
            id="usr_custom_chat",
            workspace_id=workspace.id,
            default_project_id=project.id,
            name="Custom chat user",
            role="user",
            personal_agent_id="agent_custom_chat",
        )
    )
    client = TestClient(app)
    _, token = issue_session(store, user)
    client.cookies.set(SESSION_COOKIE_NAME, token)

    created = client.post("/api/chat/threads", json={"title": "Tenant-scoped thread"})

    assert created.status_code == 200
    thread = created.json()["thread"]
    assert thread["workspace_id"] == workspace.id
    assert thread["project_id"] == project.id
    assert [item["id"] for item in client.get("/api/chat/threads").json()["items"]] == [thread["id"]]
    assert client.get(f"/api/chat/threads/{thread['id']}").status_code == 200
