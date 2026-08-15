from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi.testclient import TestClient

from agentmesh.app import app
from agentmesh.auth import SESSION_COOKIE_NAME, issue_session
from agentmesh.models import (
    Agent,
    BlackboardPost,
    BlackboardPostType,
    ChatThread,
    DocumentRecord,
    InboxItem,
    Intent,
    MemoryItem,
    MemoryStatus,
    Project,
    Scope,
    Source,
    Task,
    User,
    UserRole,
    Workspace,
)
from agentmesh.store import store

WORKSPACE_ID = "ws_m8_contract"
PROJECT_ID = "prj_m8_contract"


def setup_function() -> None:
    store.reset()
    store.save_workspace(Workspace(id=WORKSPACE_ID, name="M8", description="M8 contracts"))
    store.save_project(
        Project(
            id=PROJECT_ID,
            workspace_id=WORKSPACE_ID,
            name="M8 project",
            goal="Verify governance and collaboration contracts",
        )
    )


def _user(user_id: str, role: UserRole = UserRole.USER) -> User:
    user = User(
        id=user_id,
        workspace_id=WORKSPACE_ID,
        default_project_id=PROJECT_ID,
        name=user_id,
        role=role,
        personal_agent_id=f"agent_{user_id}",
    )
    store.save_user(user)
    store.save_agent(
        Agent(
            id=user.personal_agent_id,
            workspace_id=WORKSPACE_ID,
            name=f"{user_id} twin",
            agent_type="personal",
            description="M8 contract twin",
            owner_user_id=user.id,
        )
    )
    return user


def _client(user: User) -> TestClient:
    client = TestClient(app)
    _, token = issue_session(store, user)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    return client

def _brief_review(owner: User, text: str = "# Draft\n\nOriginal") -> tuple[DocumentRecord, InboxItem]:
    source = Source(title="Generated Brief", source_type="generated_brief", reference="generated://brief/test")
    store.add_source(source)
    document = store.add_document(
        DocumentRecord(
            title="Brief draft",
            file_name="brief.md",
            content_type="text/markdown",
            text=text,
            source=source,
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            uploaded_by=owner.id,
            metadata={"artifact_type": "brief_draft"},
        )
    )
    item = store.add_inbox_item(
        InboxItem(
            title="Confirm Brief",
            summary="Review edited Brief",
            item_type="decision_review",
            scope=Scope.PROJECT,
            user_id=owner.id,
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            metadata={"artifact_type": "brief_draft", "document_id": document.id},
        )
    )
    return document, item


def _task_post(owner: User, *, scope: Scope = Scope.PROJECT) -> tuple[Task, BlackboardPost]:
    thread = store.add_chat_thread(
        ChatThread(
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            user_id=owner.id,
            title="Visible task detail",
        )
    )
    task = store.add_task(Task(thread_id=thread.id, intent=Intent.GENERAL_CHAT, title="Visible task detail"))
    post = store.add_blackboard_post(
        BlackboardPost(
            task_id=task.id,
            post_type=BlackboardPostType.REQUEST,
            actor=owner.personal_agent_id,
            title="Request",
            content="A task controlled by its initiator.",
            scope=scope,
            permission="project_visible",
        )
    )
    return task, post


def test_inbox_returns_only_canonical_allowed_actions() -> None:
    owner = _user("usr_owner")
    brief = store.add_inbox_item(
        InboxItem(
            title="Brief",
            summary="Confirm the generated Brief",
            item_type="decision_review",
            scope=Scope.PRIVATE,
            user_id=owner.id,
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            metadata={"artifact_type": "brief_draft", "document_id": "doc_missing"},
        )
    )
    injection = store.add_inbox_item(
        InboxItem(
            title="Injection",
            summary="Review quarantined evidence",
            item_type="prompt_injection_review",
            scope=Scope.PRIVATE,
            user_id=owner.id,
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
        )
    )
    resolved = store.add_inbox_item(
        InboxItem(
            title="Resolved",
            summary="Already complete",
            item_type="decision_review",
            scope=Scope.PRIVATE,
            user_id=owner.id,
            status="resolved",
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
        )
    )

    items = _client(owner).get("/api/inbox", params={"include_snoozed": True}).json()["items"]
    by_id = {item["id"]: item for item in items}

    assert set(by_id[brief.id]["allowed_actions"]) == {"confirm_brief", "snooze"}
    assert set(by_id[injection.id]["allowed_actions"]) == {"release", "discard", "snooze"}
    assert by_id[resolved.id]["allowed_actions"] == []

def test_generic_resolve_cannot_bypass_dedicated_governance_transitions() -> None:
    owner = _user("usr_owner")
    _, brief = _brief_review(owner)
    injection = store.add_inbox_item(
        InboxItem(
            title="Injection",
            summary="Review quarantined evidence",
            item_type="prompt_injection_review",
            scope=Scope.PROJECT,
            user_id=owner.id,
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
        )
    )
    client = _client(owner)

    for item in (brief, injection):
        before = item.model_dump()
        response = client.patch(f"/api/inbox/{item.id}", json={"status": "resolved"})

        assert response.status_code == 409
        assert store.get_inbox_item(item.id).model_dump() == before


def test_confirm_brief_atomically_persists_edited_document_candidate_and_inbox_reference() -> None:
    owner = _user("usr_owner")
    document, item = _brief_review(owner)
    edited_text = "# Confirmed Brief\n\nUse the canonical edited content."

    response = _client(owner).post(
        f"/api/inbox/{item.id}/confirm-brief",
        json={"text": edited_text, "expected_document_version": document.version},
    )

    assert response.status_code == 200
    payload = response.json()
    persisted_document = store.get_document(document.id)
    persisted_item = store.get_inbox_item(item.id)
    candidates = [memory for memory in store.memory_items if memory.metadata.get("inbox_item_id") == item.id]
    assert persisted_document.text == edited_text
    assert persisted_document.version == document.version + 1
    assert persisted_document.metadata["edited_by"] == owner.id
    assert persisted_item.status == "resolved"
    assert persisted_item.metadata["confirmed_memory_id"] == payload["memory_item"]["id"]
    assert persisted_item.metadata["confirmed_document_id"] == document.id
    assert candidates == [store.get_memory_item(payload["memory_item"]["id"])]
    assert candidates[0].summary == "# Confirmed Brief Use the canonical edited content."


def test_concurrent_duplicate_brief_confirm_creates_exactly_one_candidate() -> None:
    owner = _user("usr_owner")
    document, item = _brief_review(owner)
    barrier = Barrier(2)

    def confirm(client: TestClient):
        barrier.wait()
        return client.post(
            f"/api/inbox/{item.id}/confirm-brief",
            json={"text": "# One winner", "expected_document_version": document.version},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(confirm, (_client(owner), _client(owner))))

    assert sorted(response.status_code for response in responses) == [200, 409]
    candidates = [memory for memory in store.memory_items if memory.metadata.get("inbox_item_id") == item.id]
    assert len(candidates) == 1
    assert store.get_inbox_item(item.id).metadata["confirmed_memory_id"] == candidates[0].id


def test_stale_brief_confirm_cannot_overwrite_document_or_create_candidate() -> None:
    owner = _user("usr_owner")
    document, item = _brief_review(owner)
    stale_version = document.version
    document.text = "# Concurrent canonical edit"
    document.version += 1
    store.save_document(document)

    response = _client(owner).post(
        f"/api/inbox/{item.id}/confirm-brief",
        json={"text": "# Stale losing edit", "expected_document_version": stale_version},
    )

    assert response.status_code == 409
    assert store.get_document(document.id).text == "# Concurrent canonical edit"
    assert store.get_inbox_item(item.id).status == "open"
    assert not [memory for memory in store.memory_items if memory.metadata.get("inbox_item_id") == item.id]


def test_brief_confirm_requires_inbox_and_document_ownership() -> None:
    owner = _user("usr_owner")
    stranger = _user("usr_stranger")
    document, item = _brief_review(owner)

    response = _client(stranger).post(
        f"/api/inbox/{item.id}/confirm-brief",
        json={"text": "# Unauthorized edit", "expected_document_version": document.version},
    )

    assert response.status_code == 403
    assert store.get_document(document.id).text == document.text
    assert store.get_inbox_item(item.id).status == "open"
    assert not [memory for memory in store.memory_items if memory.metadata.get("inbox_item_id") == item.id]


def test_memory_allowed_actions_follow_team_memory_policy() -> None:
    owner = _user("usr_owner")
    lead = _user("usr_lead", UserRole.TEAM_LEAD)
    candidate = store.add_memory_item(
        MemoryItem(
            title="Candidate",
            summary="Awaiting review",
            memory_type="brief_decision",
            scope=Scope.TEAM_CANDIDATE,
            status=MemoryStatus.PROPOSED,
            owner_user_id=owner.id,
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
        )
    )

    lead_items = _client(lead).get("/api/memory").json()["items"]
    returned = next(item for item in lead_items if item["id"] == candidate.id)
    assert returned["allowed_actions"] == ["accept"]

    accepted = _client(lead).patch(f"/api/memory/{candidate.id}", json={"status": "accepted"})
    assert accepted.status_code == 200
    refreshed = _client(lead).get("/api/memory").json()["items"]
    returned = next(item for item in refreshed if item["id"] == candidate.id)
    assert returned["allowed_actions"] == []


def test_task_detail_returns_filtered_posts_and_server_actions() -> None:
    owner = _user("usr_owner")
    task, post = _task_post(owner)

    response = _client(owner).get(f"/api/blackboard/tasks/{task.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_card"]["task"]["id"] == task.id
    assert payload["task_card"]["target_post_id"] == post.id
    assert {"reply", "lock", "handoff", "read"} <= set(payload["task_card"]["allowed_actions"])
    assert payload["posts"][0]["id"] == post.id
    assert payload["posts"][0]["allowed_actions"] == payload["task_card"]["allowed_actions"]


def test_hidden_task_detail_returns_not_found_and_direct_action_is_denied() -> None:
    owner = _user("usr_owner")
    stranger = _user("usr_stranger")
    task, post = _task_post(owner, scope=Scope.PRIVATE)
    client = _client(stranger)

    detail = client.get(f"/api/blackboard/tasks/{task.id}")
    reply = client.post(
        f"/api/blackboard/posts/{post.id}/reply",
        json={"post_type": "evidence", "title": "Forbidden", "content": "Must not persist"},
    )

    assert detail.status_code == 404
    assert reply.status_code == 404
    assert len([item for item in store.blackboard_posts if item.task_id == task.id]) == 1


def test_lock_state_changes_returned_task_actions() -> None:
    owner = _user("usr_owner")
    task, post = _task_post(owner)
    client = _client(owner)

    locked = client.post(
        f"/api/blackboard/posts/{post.id}/lock",
        json={"owner_agent_id": owner.personal_agent_id},
    )
    detail = client.get(f"/api/blackboard/tasks/{task.id}").json()

    assert locked.status_code == 200
    assert {"unlock", "handoff", "reply", "read"} <= set(detail["task_card"]["allowed_actions"])


def _handoff_payload(next_owner_agent_id: str) -> dict[str, object]:
    return {
        "goal": "Continue the governed task",
        "current_result": "Initial evidence is ready",
        "done_when": "The recipient verifies the evidence",
        "next_owner_agent_id": next_owner_agent_id,
    }


def test_handoff_recipient_personal_agent_receives_usable_control() -> None:
    owner = _user("usr_owner")
    recipient = _user("usr_recipient")
    task, post = _task_post(owner)

    handed_off = _client(owner).post(
        f"/api/blackboard/posts/{post.id}/handoff",
        json=_handoff_payload(recipient.personal_agent_id),
    )

    assert handed_off.status_code == 200
    handoff_post = handed_off.json()["item"]
    recipient_client = _client(recipient)
    detail = recipient_client.get(f"/api/blackboard/tasks/{task.id}")
    assert detail.status_code == 200
    assert detail.json()["task_card"]["target_post_id"] == handoff_post["id"]
    assert {"reply", "lock", "handoff"} <= set(detail.json()["task_card"]["allowed_actions"])

    reply = recipient_client.post(
        f"/api/blackboard/posts/{handoff_post['id']}/reply",
        json={"post_type": "evidence", "title": "Recipient evidence", "content": "Recipient can reply."},
    )
    assert reply.status_code == 200
    reply_post = reply.json()["item"]
    refreshed = recipient_client.get(f"/api/blackboard/tasks/{task.id}").json()["task_card"]
    assert refreshed["target_post_id"] == reply_post["id"]
    assert {"reply", "lock", "handoff"} <= set(refreshed["allowed_actions"])

    locked = recipient_client.post(
        f"/api/blackboard/posts/{reply_post['id']}/lock",
        json={"owner_agent_id": recipient.personal_agent_id},
    )
    onward = recipient_client.post(
        f"/api/blackboard/posts/{reply_post['id']}/handoff",
        json=_handoff_payload(owner.personal_agent_id),
    )

    assert [locked.status_code, onward.status_code] == [200, 200]


def test_handoff_rejects_unknown_ineligible_and_cross_scope_recipients_without_state_change() -> None:
    owner = _user("usr_owner")
    task, post = _task_post(owner)
    inactive = _user("usr_inactive")
    inactive.status = "disabled"
    store.save_user(inactive)
    offline = _user("usr_offline")
    offline_agent = store.get_agent(offline.personal_agent_id)
    assert offline_agent is not None
    offline_agent.status = "offline"
    store.save_agent(offline_agent)

    store.save_workspace(Workspace(id="ws_foreign", name="Foreign", description="Other tenant"))
    store.save_project(Project(id="prj_foreign", workspace_id="ws_foreign", name="Foreign", goal="Other tenant"))
    foreign_user = User(
        id="usr_foreign",
        workspace_id="ws_foreign",
        default_project_id="prj_foreign",
        name="Foreign user",
        role=UserRole.USER,
        personal_agent_id="agent_usr_foreign",
    )
    store.save_user(foreign_user)
    store.save_agent(
        Agent(
            id=foreign_user.personal_agent_id,
            workspace_id="ws_foreign",
            name="Foreign twin",
            agent_type="personal",
            description="Cross-workspace recipient",
            owner_user_id=foreign_user.id,
        )
    )

    store.save_project(
        Project(id="prj_other", workspace_id=WORKSPACE_ID, name="Other project", goal="Separate project")
    )
    other_project_user = User(
        id="usr_other_project",
        workspace_id=WORKSPACE_ID,
        default_project_id="prj_other",
        name="Other project user",
        role=UserRole.USER,
        personal_agent_id="agent_usr_other_project",
    )
    store.save_user(other_project_user)
    store.save_agent(
        Agent(
            id=other_project_user.personal_agent_id,
            workspace_id=WORKSPACE_ID,
            name="Other project twin",
            agent_type="personal",
            description="Cross-project recipient",
            owner_user_id=other_project_user.id,
        )
    )

    client = _client(owner)
    attempts = {
        "missing_agent": 404,
        foreign_user.personal_agent_id: 404,
        other_project_user.personal_agent_id: 404,
        inactive.personal_agent_id: 409,
        offline.personal_agent_id: 409,
    }
    for agent_id, expected_status in attempts.items():
        response = client.post(
            f"/api/blackboard/posts/{post.id}/handoff",
            json=_handoff_payload(agent_id),
        )
        assert response.status_code == expected_status
    assert _client(other_project_user).get(f"/api/blackboard/tasks/{task.id}").status_code == 404

    persisted_task = store.get_task(task.id)
    assert persisted_task is not None
    assert persisted_task.current_owner_agent_id is None
    assert len([item for item in store.blackboard_posts if item.task_id == task.id]) == 1
