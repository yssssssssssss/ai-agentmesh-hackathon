from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import agentmesh.routes.auth as auth_routes
from agentmesh.app import app
from agentmesh.auth import SESSION_COOKIE_NAME, issue_session
from agentmesh.models import (
    Agent,
    BlackboardPost,
    BlackboardPostType,
    ChatThread,
    Intent,
    MemoryItem,
    MemoryLayer,
    MemoryStatus,
    Project,
    Scope,
    Task,
    User,
    UserMemoryItem,
    UserRole,
)
from agentmesh.store import store

WORKSPACE_ID = "ws_mvp_governance"
PROJECT_ID = "prj_mvp_governance"


def _user(
    user_id: str,
    role: UserRole = UserRole.USER,
    *,
    status: str = "active",
    oauth_provider: str | None = None,
    oauth_subject: str | None = None,
) -> User:
    user = User(
        id=user_id,
        workspace_id=WORKSPACE_ID,
        default_project_id=PROJECT_ID,
        name=user_id,
        role=role,
        status=status,
        personal_agent_id=f"agent_{user_id}",
        oauth_provider=oauth_provider,
        oauth_subject=oauth_subject,
    )
    store.save_user(user)
    project = store.get_project(PROJECT_ID)
    if project is None:
        project = Project(
            id=PROJECT_ID,
            workspace_id=WORKSPACE_ID,
            name="MVP governance",
            goal="Exercise project governance",
            member_ids=[user.id],
        )
    elif user.id not in project.member_ids:
        project.member_ids.append(user.id)
    store.save_project(project)
    store.save_agent(
        Agent(
            id=user.personal_agent_id,
            workspace_id=WORKSPACE_ID,
            name=f"{user_id} agent",
            agent_type="personal",
            description="MVP governance test agent",
            owner_user_id=user.id,
        )
    )
    return user


def _client(user: User | None = None) -> TestClient:
    client = TestClient(app)
    if user is not None:
        _, token = issue_session(store, user)
        client.cookies.set(SESSION_COOKIE_NAME, token)
    return client


def _task_post(initiator: User, *, scope: Scope = Scope.PROJECT) -> BlackboardPost:
    thread = store.add_chat_thread(
        ChatThread(
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            user_id=initiator.id,
            title="Governed task",
        )
    )
    task = store.add_task(Task(thread_id=thread.id, intent=Intent.GENERAL_CHAT, title="Governed task"))
    return store.add_blackboard_post(
        BlackboardPost(
            task_id=task.id,
            post_type=BlackboardPostType.REQUEST,
            actor=initiator.personal_agent_id,
            title="Governed request",
            content="Only the task controller may mutate this post.",
            scope=scope,
            permission="project_visible",
        )
    )


def _oauth_env(monkeypatch, *, default_role: str = "user") -> None:
    values = {
        "AGENTMESH_OAUTH_ENABLED": "true",
        "AGENTMESH_OAUTH_PROVIDER": "corp",
        "AGENTMESH_OAUTH_AUTHORIZE_URL": "https://sso.example/authorize",
        "AGENTMESH_OAUTH_TOKEN_URL": "https://sso.example/token",
        "AGENTMESH_OAUTH_USERINFO_URL": "https://sso.example/userinfo",
        "AGENTMESH_OAUTH_CLIENT_ID": "agentmesh-client",
        "AGENTMESH_OAUTH_CLIENT_SECRET": "secret",
        "AGENTMESH_OAUTH_REDIRECT_URI": "http://testserver/api/auth/oauth/callback",
        "AGENTMESH_OAUTH_DEFAULT_ROLE": default_role,
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(auth_routes, "exchange_oauth_code", lambda config, code: {"access_token": "token"})


def _oauth_callback(client: TestClient) -> object:
    start = client.get("/api/auth/oauth/start", follow_redirects=False)
    state = start.cookies.get(auth_routes.OAUTH_STATE_COOKIE)
    assert start.status_code == 302
    assert state
    return client.get(f"/api/auth/oauth/callback?code=ok&state={state}")


def setup_function() -> None:
    store.reset()


def test_regular_user_cannot_create_accepted_team_memory_directly() -> None:
    user = _user("usr_member")

    response = _client(user).post(
        "/api/memory",
        json={
            "title": "Unreviewed team memory",
            "summary": "Must enter the review queue.",
            "memory_type": "decision",
            "scope": "team_accepted",
        },
    )

    assert response.status_code == 403
    assert store.memory_items == []


def test_new_team_memory_is_owned_proposed_candidate() -> None:
    user = _user("usr_member")

    response = _client(user).post(
        "/api/memory",
        json={
            "title": "Candidate",
            "summary": "Awaiting review.",
            "memory_type": "decision",
            "scope": "team_candidate",
        },
    )

    assert response.status_code == 200
    item = response.json()["item"]
    assert item["owner_user_id"] == user.id
    assert item["scope"] == "team_candidate"
    assert item["status"] == "proposed"


@pytest.mark.parametrize("payload", [{"status": "draft"}, {"status": "deprecated"}, {"status": "expired"}, {"scope": "private"}])
def test_regular_user_cannot_downgrade_shared_memory(payload: dict[str, str]) -> None:
    user = _user("usr_member")
    item = store.add_memory_item(
        MemoryItem(
            title="Accepted",
            summary="Shared team truth.",
            memory_type="decision",
            scope=Scope.TEAM_ACCEPTED,
            status=MemoryStatus.ACCEPTED,
            owner_user_id=user.id,
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
        )
    )

    response = _client(user).patch(f"/api/memory/{item.id}", json=payload)

    assert response.status_code == 403
    persisted = store.get_memory_item(item.id)
    assert persisted is not None
    assert persisted.scope == Scope.TEAM_ACCEPTED
    assert persisted.status == MemoryStatus.ACCEPTED


def test_regular_user_cannot_mutate_foreign_or_shared_memory() -> None:
    owner = _user("usr_owner")
    member = _user("usr_member")
    foreign = store.add_memory_item(
        MemoryItem(
            title="Foreign",
            summary="Private owner content.",
            memory_type="note",
            scope=Scope.PRIVATE,
            owner_user_id=owner.id,
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
        )
    )
    shared = store.add_memory_item(
        MemoryItem(
            title="Candidate",
            summary="Shared review content.",
            memory_type="decision",
            scope=Scope.TEAM_CANDIDATE,
            owner_user_id=owner.id,
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
        )
    )
    client = _client(member)

    foreign_response = client.patch(f"/api/memory/{foreign.id}", json={"status": "disputed"})
    shared_response = client.patch(f"/api/memory/{shared.id}", json={"status": "disputed"})

    assert foreign_response.status_code == 404
    assert shared_response.status_code == 404


@pytest.mark.parametrize("role", [UserRole.TEAM_LEAD, UserRole.ADMIN])
def test_team_lead_and_admin_can_accept_candidate_memory(role: UserRole) -> None:
    owner = _user("usr_owner")
    reviewer = _user(f"usr_{role}", role)
    item = store.add_memory_item(
        MemoryItem(
            title="Candidate",
            summary="Reviewed team knowledge.",
            memory_type="decision",
            scope=Scope.TEAM_CANDIDATE,
            owner_user_id=owner.id,
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
        )
    )

    response = _client(reviewer).patch(f"/api/memory/{item.id}", json={"status": "accepted"})

    assert response.status_code == 200
    assert response.json()["item"]["scope"] == "team_accepted"
    assert response.json()["item"]["status"] == "accepted"


def test_existing_accepted_and_disputed_team_memory_remains_readable() -> None:
    member = _user("usr_member")
    accepted = store.add_memory_item(
        MemoryItem(
            title="Accepted legacy memory",
            summary="Compatibility read.",
            memory_type="decision",
            scope=Scope.TEAM_ACCEPTED,
            status=MemoryStatus.ACCEPTED,
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
        )
    )
    disputed = store.add_memory_item(
        MemoryItem(
            title="Disputed legacy memory",
            summary="Compatibility read.",
            memory_type="decision",
            scope=Scope.TEAM_ACCEPTED,
            status=MemoryStatus.DISPUTED,
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
        )
    )

    response = _client(member).get("/api/memory")

    assert response.status_code == 200
    assert {accepted.id, disputed.id} <= {item["id"] for item in response.json()["items"]}


@pytest.mark.parametrize("action", ["lock", "reply", "read"])
def test_hidden_blackboard_post_actions_return_not_found(action: str) -> None:
    owner = _user("usr_owner")
    stranger = _user("usr_stranger")
    post = _task_post(owner, scope=Scope.PRIVATE)
    client = _client(stranger)
    if action == "lock":
        response = client.post(f"/api/blackboard/posts/{post.id}/lock", json={"owner_agent_id": stranger.personal_agent_id})
    elif action == "reply":
        response = client.post(
            f"/api/blackboard/posts/{post.id}/reply",
            json={"post_type": "evidence", "title": "Hidden reply", "content": "Must not be created."},
        )
    else:
        response = client.patch(f"/api/blackboard/posts/{post.id}/read")

    assert response.status_code == 404


def test_visible_foreign_post_cannot_be_unlocked_by_regular_user() -> None:
    owner = _user("usr_owner")
    stranger = _user("usr_stranger")
    post = store.add_blackboard_post(
        BlackboardPost(
            task_id=f"manual_{owner.id}",
            post_type=BlackboardPostType.REQUEST,
            actor=owner.personal_agent_id,
            title="Visible owner post",
            content="Only the owner controls this task.",
            scope=Scope.PROJECT,
            permission="project_visible",
        )
    )
    owner_client = _client(owner)
    assert owner_client.post(
        f"/api/blackboard/posts/{post.id}/lock", json={"owner_agent_id": owner.personal_agent_id}
    ).status_code == 200

    response = _client(stranger).post(f"/api/blackboard/posts/{post.id}/unlock", json={"reason": "takeover"})

    assert response.status_code == 403
    assert store.get_blackboard_post(post.id).execution_lock.active is True


def test_task_initiator_can_lock_reply_handoff_unlock_and_read() -> None:
    initiator = _user("usr_initiator")
    recipient = _user("usr_recipient")
    post = _task_post(initiator)
    client = _client(initiator)

    lock = client.post(
        f"/api/blackboard/posts/{post.id}/lock", json={"owner_agent_id": initiator.personal_agent_id}
    )
    reply = client.post(
        f"/api/blackboard/posts/{post.id}/reply",
        json={"post_type": "evidence", "title": "Evidence", "content": "Initiator supplied evidence."},
    )
    handoff = client.post(
        f"/api/blackboard/posts/{post.id}/handoff",
        json={
            "goal": "Continue",
            "current_result": "Evidence collected",
            "done_when": "Reviewed",
            "next_owner_agent_id": recipient.personal_agent_id,
        },
    )
    unlock = client.post(f"/api/blackboard/posts/{post.id}/unlock", json={"reason": "review"})
    read = client.patch(f"/api/blackboard/posts/{post.id}/read")

    assert [response.status_code for response in (lock, reply, handoff, unlock, read)] == [200, 200, 200, 200, 200]
    assert reply.json()["item"]["task_id"] == post.task_id
    assert reply.json()["item"]["actor"] == initiator.personal_agent_id


@pytest.mark.parametrize("role", [UserRole.TEAM_LEAD, UserRole.ADMIN])
def test_team_lead_and_admin_can_control_visible_foreign_task(role: UserRole) -> None:
    owner = _user("usr_owner")
    controller = _user(f"usr_{role}", role)
    post = _task_post(owner)

    response = _client(controller).post(
        f"/api/blackboard/posts/{post.id}/lock", json={"owner_agent_id": controller.personal_agent_id}
    )

    assert response.status_code == 200


def test_manual_post_rejects_identity_state_and_tenant_mass_assignment() -> None:
    user = _user("usr_member")
    client = _client(user)
    base = {"post_type": "digest", "title": "Daily", "content": "Completed work."}

    rejected = [
        client.post("/api/blackboard/posts", json={**base, field: value})
        for field, value in (
            ("actor", "admin"),
            ("status", "reviewed"),
            ("task_id", "foreign_task"),
            ("workspace_id", "foreign_workspace"),
            ("project_id", "foreign_project"),
        )
    ]
    valid_response = client.post("/api/blackboard/posts", json=base)

    assert all(response.status_code == 422 for response in rejected)
    assert valid_response.status_code == 200
    item = valid_response.json()["item"]
    assert item["actor"] == user.personal_agent_id
    assert item["task_id"] == f"manual_{user.id}"
    assert item["status"] == "published"


def test_auto_post_cannot_be_pre_marked_reviewed_and_review_drain_are_admin_only() -> None:
    member = _user("usr_member")
    admin = _user("usr_admin", UserRole.ADMIN)
    task_post = _task_post(member)
    payload = {
        "task_id": task_post.task_id,
        "post_type": "digest",
        "title": "Queued digest",
        "content": "Governance review required.",
    }
    member_client = _client(member)

    mass_assignment = member_client.post("/api/blackboard/auto-posts", json={**payload, "status": "reviewed"})
    enqueue = member_client.post("/api/blackboard/auto-posts", json=payload)
    request_id = enqueue.json()["item"]["id"]
    denied_review = member_client.post(f"/api/blackboard/auto-posts/{request_id}/review")
    denied_drain = member_client.post("/api/blackboard/auto-posts/drain")
    admin_client = _client(admin)
    review = admin_client.post(f"/api/blackboard/auto-posts/{request_id}/review")
    drain = admin_client.post("/api/blackboard/auto-posts/drain")

    assert mass_assignment.status_code == 422
    assert enqueue.status_code == 200
    assert enqueue.json()["item"]["status"] == "queued"
    assert denied_review.status_code == 403
    assert denied_drain.status_code == 403
    assert review.status_code == 200
    assert drain.status_code == 200
    assert drain.json()["posted"] == 1


@pytest.mark.parametrize("path", ["/api/market/status", "/api/market/board"])
def test_market_reads_require_authentication(path: str) -> None:
    response = _client().get(path)

    assert response.status_code == 401


def test_market_participation_remains_current_user_scoped() -> None:
    first = _user("usr_first")
    second = _user("usr_second")

    response = _client(first).put("/api/market/participation", json={"enabled": True})

    assert response.status_code == 200
    assert response.json()["user_id"] == first.id
    assert store.is_market_participant(first.id) is True
    assert store.is_market_participant(second.id) is False


def test_oauth_callback_does_not_reactivate_disabled_user(monkeypatch) -> None:
    _oauth_env(monkeypatch)
    disabled = _user(
        "usr_oauth_disabled",
        status="disabled",
        oauth_provider="corp",
        oauth_subject="disabled",
    )
    monkeypatch.setattr(
        auth_routes,
        "fetch_oauth_userinfo",
        lambda config, token: {"sub": "disabled", "email": "disabled@example.com", "name": "Disabled", "role": "admin"},
    )

    response = _oauth_callback(_client())

    assert response.status_code == 403
    assert store.get_user(disabled.id).status == "disabled"
    assert all(session.user_id != disabled.id for session in store.auth_sessions)


def test_oauth_callback_preserves_state_validation(monkeypatch) -> None:
    _oauth_env(monkeypatch)
    monkeypatch.setattr(
        auth_routes,
        "exchange_oauth_code",
        lambda config, code: pytest.fail("invalid state must fail before token exchange"),
    )

    response = _client().get("/api/auth/oauth/callback?code=ok&state=untrusted")

    assert response.status_code == 400


def test_oauth_callback_rejects_token_response_without_access_token(monkeypatch) -> None:
    _oauth_env(monkeypatch)
    monkeypatch.setattr(auth_routes, "exchange_oauth_code", lambda config, code: {})
    client = _client()
    start = client.get("/api/auth/oauth/start", follow_redirects=False)
    state = start.cookies.get(auth_routes.OAUTH_STATE_COOKIE)

    response = client.get(f"/api/auth/oauth/callback?code=ok&state={state}")

    assert response.status_code == 502


def test_oauth_profile_role_cannot_promote_new_user(monkeypatch) -> None:
    _oauth_env(monkeypatch, default_role="user")
    monkeypatch.setattr(
        auth_routes,
        "fetch_oauth_userinfo",
        lambda config, token: {"sub": "new", "email": "new@example.com", "name": "New", "role": "admin"},
    )

    response = _oauth_callback(_client())

    assert response.status_code == 200
    assert response.json()["user"]["role"] == "user"


def test_oauth_profile_role_cannot_promote_existing_user(monkeypatch) -> None:
    _oauth_env(monkeypatch, default_role="team_lead")
    existing = _user(
        "usr_oauth_existing",
        UserRole.USER,
        oauth_provider="corp",
        oauth_subject="existing",
    )
    monkeypatch.setattr(
        auth_routes,
        "fetch_oauth_userinfo",
        lambda config, token: {"sub": "existing", "email": "existing@example.com", "name": "Existing", "role": "admin"},
    )

    response = _oauth_callback(_client())

    assert response.status_code == 200
    assert response.json()["user"]["role"] == "user"
    assert store.get_user(existing.id).role == UserRole.USER


def test_configured_oauth_default_role_is_used_for_new_user(monkeypatch) -> None:
    _oauth_env(monkeypatch, default_role="team_lead")
    monkeypatch.setattr(
        auth_routes,
        "fetch_oauth_userinfo",
        lambda config, token: {"sub": "lead", "email": "lead@example.com", "name": "Lead", "role": "user"},
    )

    response = _oauth_callback(_client())

    assert response.status_code == 200
    assert response.json()["user"]["role"] == "team_lead"


def test_oauth_subject_binding_survives_email_change(monkeypatch) -> None:
    _oauth_env(monkeypatch)
    profiles = iter(
        [
            {"sub": "stable-subject", "email": "old@example.com", "name": "Old Name"},
            {"sub": "stable-subject", "email": "new@example.com", "name": "New Name"},
        ]
    )
    monkeypatch.setattr(auth_routes, "fetch_oauth_userinfo", lambda config, token: next(profiles))
    client = _client()

    first = _oauth_callback(client)
    second = _oauth_callback(client)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["user"]["id"] == second.json()["user"]["id"]
    assert second.json()["user"]["name"] == "New Name"


def test_distinct_oauth_subjects_with_colliding_emails_get_distinct_users(monkeypatch) -> None:
    _oauth_env(monkeypatch)
    profiles = iter(
        [
            {"sub": "subject-a", "email": "a.b@example.com", "name": "A"},
            {"sub": "subject-b", "email": "a-b@example.com", "name": "B"},
        ]
    )
    monkeypatch.setattr(auth_routes, "fetch_oauth_userinfo", lambda config, token: next(profiles))
    client = _client()

    first = _oauth_callback(client)
    second = _oauth_callback(client)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["user"]["id"] != second.json()["user"]["id"]


def test_disabled_oauth_subject_stays_disabled_after_email_change(monkeypatch) -> None:
    _oauth_env(monkeypatch)
    profiles = iter(
        [
            {"sub": "disabled-stable-subject", "email": "before@example.com", "name": "Before"},
            {"sub": "disabled-stable-subject", "email": "after@example.com", "name": "After"},
        ]
    )
    monkeypatch.setattr(auth_routes, "fetch_oauth_userinfo", lambda config, token: next(profiles))
    client = _client()
    first = _oauth_callback(client)
    user = store.get_user(first.json()["user"]["id"])
    user.status = "disabled"
    store.save_user(user)

    second = _oauth_callback(client)

    assert second.status_code == 403
    assert len([item for item in store.users if item.oauth_subject == "disabled-stable-subject"]) == 1


def test_task_initiator_cannot_forge_or_release_another_agent_lock() -> None:
    initiator = _user("usr_initiator")
    controller = _user("usr_controller", UserRole.TEAM_LEAD)
    victim = _user("usr_victim")
    post = _task_post(initiator)

    forged = _client(initiator).post(
        f"/api/blackboard/posts/{post.id}/lock", json={"owner_agent_id": victim.personal_agent_id}
    )
    held = _client(controller).post(
        f"/api/blackboard/posts/{post.id}/lock", json={"owner_agent_id": controller.personal_agent_id}
    )
    unauthorized_unlock = _client(initiator).post(
        f"/api/blackboard/posts/{post.id}/unlock", json={"reason": "not owner"}
    )
    unauthorized_handoff = _client(initiator).post(
        f"/api/blackboard/posts/{post.id}/handoff",
        json={
            "goal": "Take over",
            "current_result": "None",
            "done_when": "Done",
            "next_owner_agent_id": initiator.personal_agent_id,
        },
    )

    assert forged.status_code == 403
    assert held.status_code == 200
    assert unauthorized_unlock.status_code == 403
    assert unauthorized_handoff.status_code == 403


def test_auto_post_queue_is_admin_only_and_actor_is_server_derived() -> None:
    member = _user("usr_member")
    other = _user("usr_other")
    admin = _user("usr_admin", UserRole.ADMIN)
    post = _task_post(member)
    payload = {
        "task_id": post.task_id,
        "post_type": "digest",
        "title": "Queued",
        "content": "Private queued content",
        "scope": "private",
    }

    enqueue = _client(member).post("/api/blackboard/auto-posts", json=payload)
    forged_actor = _client(member).post(
        "/api/blackboard/auto-posts", json={**payload, "actor": other.personal_agent_id}
    )
    foreign_task = _client(member).post(
        "/api/blackboard/auto-posts", json={**payload, "task_id": "task_foreign"}
    )

    assert enqueue.status_code == 200
    assert enqueue.json()["item"]["actor"] == member.personal_agent_id
    assert forged_actor.status_code == 422
    assert foreign_task.status_code == 404
    assert _client(other).get("/api/blackboard/auto-posts").status_code == 403
    assert _client(admin).get("/api/blackboard/auto-posts").status_code == 200



def test_regular_user_cannot_trigger_research_dispatch_drain() -> None:
    member = _user("usr_member")
    admin = _user("usr_admin", UserRole.ADMIN)

    assert _client(member).post("/api/blackboard/research-dispatch/drain").status_code == 403
    assert _client(admin).post("/api/blackboard/research-dispatch/drain").status_code == 200


def test_personal_memory_rejects_inaccessible_project() -> None:
    member = _user("usr_member")
    foreign_project = store.save_project(
        Project(
            workspace_id=WORKSPACE_ID,
            name="Foreign project",
            goal="Not available to the member",
            member_ids=["usr_other"],
        )
    )

    response = _client(member).post(
        "/api/memory/user",
        json={
            "layer": "short_term",
            "title": "Foreign",
            "summary": "Must not be attached",
            "project_id": foreign_project.id,
        },
    )

    assert response.status_code == 404


def test_personal_memory_cannot_be_shared_to_inaccessible_project() -> None:
    member = _user("usr_member")
    foreign_project = store.save_project(
        Project(
            workspace_id=WORKSPACE_ID,
            name="Foreign project",
            goal="Not available to the member",
            member_ids=["usr_other"],
        )
    )
    item = store.add_user_memory_item(
        UserMemoryItem(
            user_id=member.id,
            layer=MemoryLayer.MID_TERM,
            title="Private project memory",
            summary="Must not cross project membership",
            source_kind="note",
            workspace_id=WORKSPACE_ID,
            project_id=foreign_project.id,
        )
    )

    response = _client(member).post(f"/api/memory/user/{item.id}/share-to-project")

    assert response.status_code == 404
