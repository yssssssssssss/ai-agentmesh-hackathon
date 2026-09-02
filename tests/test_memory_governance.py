from __future__ import annotations

from fastapi.testclient import TestClient

from agentmesh.agents import PersonalAgent
from agentmesh.app import app
from agentmesh.auth import SESSION_COOKIE_NAME, issue_session
from agentmesh.models import (
    Agent,
    BlackboardPost,
    BlackboardPostType,
    MemoryItem,
    MemoryLayer,
    MemoryStatus,
    PermissionPolicyRule,
    Project,
    Scope,
    User,
    UserMemoryItem,
    UserRole,
    Workspace,
)
from agentmesh.seed import PROJECT, TEAM_LEAD, USER
from agentmesh.store import store
from tests.test_chat_flow import authenticated_client, clear_store
from tests.test_task_reviews import _create_reviewable_delivery, _submit_review


def _accepted_task_review(monkeypatch, suffix: str) -> tuple[TestClient, dict, str]:
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    owner = authenticated_client()
    task, run, artifact = _create_reviewable_delivery(owner, suffix)
    submitted = _submit_review(owner, task, run, artifact, suffix)
    review = submitted["item"]["review"]
    reviewer = authenticated_client(TEAM_LEAD.id)
    accepted = reviewer.post(
        f"/api/task-reviews/{review['id']}/decisions",
        json={
            "command_id": f"accept-task-review-for-memory-{suffix}",
            "expected_version": 1,
            "decision": "accepted",
        },
    )
    assert accepted.status_code == 200, accepted.text
    return owner, task, review["id"]


def test_accepted_task_review_captures_private_memory_with_lineage(monkeypatch) -> None:
    clear_store()
    owner, task, review_id = _accepted_task_review(monkeypatch, "personal-memory")

    response = owner.post(
        f"/api/task-reviews/{review_id}/memory-candidates",
        json={
            "command_id": "capture-personal-memory",
            "target": "personal",
            "title": "交付后的个人经验",
            "summary": "该项目需要先冻结产物再进入人工审核。",
            "memory_type": "project_experience",
            "layer": "mid_term",
        },
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    entry = payload["item"]
    assert entry["kind"] == "personal"
    assert entry["scope"] == "private"
    assert entry["status"] == "active"
    assert entry["version"] == 1
    assert entry["provenance"]["source_kind"] == "task_artifact"
    assert entry["provenance"]["task_id"] == task["task"]["id"]
    assert entry["provenance"]["review_id"] == review_id
    assert len(entry["provenance"]["artifact_ids"]) == 1
    assert payload["memory_review"] is None

    replay = owner.post(
        f"/api/task-reviews/{review_id}/memory-candidates",
        json={
            "command_id": "capture-personal-memory",
            "target": "personal",
            "title": "交付后的个人经验",
            "summary": "该项目需要先冻结产物再进入人工审核。",
            "memory_type": "project_experience",
            "layer": "mid_term",
        },
    )
    assert replay.status_code == 201
    assert replay.json()["item"]["id"] == entry["id"]
    assert len([item for item in store.user_memory_items if item.id == entry["id"]]) == 1

    lineage = owner.get(f"/api/memory/entries/{entry['id']}/lineage")
    assert lineage.status_code == 200
    assert lineage.json()["item"]["provenance_state"] == "verified"
    assert lineage.json()["task_review_id"] == review_id
    assert lineage.json()["artifact_ids"] == entry["provenance"]["artifact_ids"]
    assert authenticated_client(TEAM_LEAD.id).get(
        f"/api/memory/entries/{entry['id']}/lineage"
    ).status_code == 404

    owner_detail = owner.get(f"/api/tasks/{task['task']['id']}").json()
    assert [item["id"] for item in owner_detail["memory_links"]] == [entry["id"]]
    reviewer_detail = authenticated_client(TEAM_LEAD.id).get(f"/api/tasks/{task['task']['id']}").json()
    assert reviewer_detail["memory_links"] == []
    legacy = store.add_user_memory_item(
        UserMemoryItem(
            id="legacy_memory_without_provenance",
            user_id=USER.id,
            layer=MemoryLayer.SHORT_TERM,
            title="Legacy memory",
            summary="No structured provenance",
            source_kind="manual",
            workspace_id=USER.workspace_id,
            project_id=PROJECT.id,
        )
    )
    entries = owner.get("/api/memory/entries").json()["items"]
    assert next(item for item in entries if item["id"] == entry["id"])["provenance_state"] == "verified"
    assert next(item for item in entries if item["id"] == legacy.id)["provenance_state"] == "legacy_unverified"
    assert [event.action for event in store.audit_events if event.target_id == entry["id"]] == [
        "capture_memory_from_task_review"
    ]


def test_team_candidate_requires_independent_memory_review(monkeypatch) -> None:
    clear_store()
    owner, task, review_id = _accepted_task_review(monkeypatch, "team-memory")

    response = owner.post(
        f"/api/task-reviews/{review_id}/memory-candidates",
        json={
            "command_id": "capture-team-candidate",
            "target": "team_candidate",
            "title": "团队可复用的审核经验",
            "summary": "交付必须绑定已封存产物和内容哈希。",
            "memory_type": "method",
        },
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    entry = payload["item"]
    memory_review = payload["memory_review"]["review"]
    assert entry["kind"] == "team_candidate"
    assert entry["scope"] == "team_candidate"
    assert entry["status"] == "proposed"
    assert memory_review["status"] == "pending"
    assert memory_review["reviewer_id"] == TEAM_LEAD.id
    assert memory_review["source_task_review_id"] == review_id
    assert store.search_for_agent(
        "团队可复用的审核经验",
        USER.personal_agent_id,
        workspace_id=USER.workspace_id,
        project_id=PROJECT.id,
        user_id=USER.id,
    ) == []

    legacy_bypass = authenticated_client(TEAM_LEAD.id).patch(
        f"/api/memory/{entry['id']}",
        json={"status": "accepted"},
    )
    assert legacy_bypass.status_code == 409
    assert legacy_bypass.json() == {"detail": "memory_governance_transition_required"}
    isolated_workspace = store.save_workspace(
        Workspace(id="workspace_memory_isolated", name="Isolated", description="Memory isolation")
    )
    isolated_project = store.save_project(
        Project(
            id="project_memory_isolated",
            workspace_id=isolated_workspace.id,
            name="Isolated memory project",
            goal="No existence disclosure",
            member_ids=["usr_memory_isolated"],
        )
    )
    isolated_user = store.save_user(
        User(
            id="usr_memory_isolated",
            workspace_id=isolated_workspace.id,
            default_project_id=isolated_project.id,
            name="Isolated memory user",
            role=UserRole.USER,
            personal_agent_id="agent_memory_isolated",
        )
    )
    _, isolated_token = issue_session(store, isolated_user)
    isolated_client = TestClient(app)
    isolated_client.cookies.set(SESSION_COOKIE_NAME, isolated_token)
    concealed = isolated_client.patch(
        f"/api/memory/{entry['id']}",
        json={"status": "accepted"},
    )
    assert concealed.status_code == 404

    reviewer = authenticated_client(TEAM_LEAD.id)
    inbox = next(
        item
        for item in reviewer.get("/api/inbox?include_snoozed=true").json()["items"]
        if item["metadata"].get("memory_review_id") == memory_review["id"]
    )
    assert inbox["allowed_actions"] == ["open_memory_review"]
    assert reviewer.patch(f"/api/inbox/{inbox['id']}", json={"status": "resolved"}).status_code == 409
    assert owner.post(
        f"/api/memory-reviews/{memory_review['id']}/decisions",
        json={
            "command_id": "owner-cannot-accept-memory",
            "expected_memory_version": 1,
            "expected_review_version": 1,
            "decision": "accepted",
        },
    ).status_code == 404

    accepted = reviewer.post(
        f"/api/memory-reviews/{memory_review['id']}/decisions",
        json={
            "command_id": "accept-team-memory-review",
            "expected_memory_version": 1,
            "expected_review_version": 1,
            "decision": "accepted",
            "decision_note": "可以作为团队知识复用。",
        },
    )

    assert accepted.status_code == 200, accepted.text
    accepted_entry = accepted.json()["item"]
    assert accepted_entry["kind"] == "team_knowledge"
    assert accepted_entry["scope"] == "team_accepted"
    assert accepted_entry["status"] == "accepted"
    assert accepted_entry["version"] == 2
    assert accepted.json()["memory_review"]["review"]["status"] == "accepted"
    decision_replay = reviewer.post(
        f"/api/memory-reviews/{memory_review['id']}/decisions",
        json={
            "command_id": "accept-team-memory-review",
            "expected_memory_version": 1,
            "expected_review_version": 1,
            "decision": "accepted",
            "decision_note": "可以作为团队知识复用。",
        },
    )
    assert decision_replay.status_code == 200
    assert decision_replay.json()["item"]["version"] == 2
    conflict = reviewer.post(
        f"/api/memory-reviews/{memory_review['id']}/decisions",
        json={
            "command_id": "accept-team-memory-review",
            "expected_memory_version": 1,
            "expected_review_version": 1,
            "decision": "rejected",
            "decision_note": "conflicting replay",
        },
    )
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "memory_governance_command_conflict"}
    assert any(
        result.id == entry["id"]
        for result in store.search_for_agent(
            "团队可复用的审核经验",
            USER.personal_agent_id,
            workspace_id=USER.workspace_id,
            project_id=PROJECT.id,
            user_id=USER.id,
        )
    )
    assert not any(
        item.metadata.get("memory_review_id") == memory_review["id"] and item.status != "resolved"
        for item in store.inbox_items
    )

    task_detail = reviewer.get(f"/api/tasks/{task['task']['id']}").json()
    assert task_detail["memory_links"][0]["id"] == entry["id"]
    lineage = reviewer.get(f"/api/memory/entries/{entry['id']}/lineage").json()
    assert lineage["memory_reviews"][0]["review"]["status"] == "accepted"
    assert [event.action for event in store.audit_events if event.target_id in {entry["id"], memory_review["id"]}] == [
        "capture_memory_from_task_review",
        "decide_memory_review",
    ]


def test_rejected_memory_candidate_stays_out_of_team_knowledge(monkeypatch) -> None:
    clear_store()
    owner, _task, review_id = _accepted_task_review(monkeypatch, "rejected-memory")
    created = owner.post(
        f"/api/task-reviews/{review_id}/memory-candidates",
        json={
            "command_id": "capture-rejected-candidate",
            "target": "team_candidate",
            "title": "不应进入团队知识",
            "summary": "该候选仍需修正。",
            "memory_type": "method",
        },
    ).json()
    memory_review = created["memory_review"]["review"]

    rejected = authenticated_client(TEAM_LEAD.id).post(
        f"/api/memory-reviews/{memory_review['id']}/decisions",
        json={
            "command_id": "reject-memory-review",
            "expected_memory_version": 1,
            "expected_review_version": 1,
            "decision": "rejected",
            "decision_note": "证据不足。",
        },
    )

    assert rejected.status_code == 200
    assert rejected.json()["item"]["scope"] == "team_candidate"
    assert rejected.json()["item"]["status"] == "disputed"
    assert rejected.json()["memory_review"]["review"]["status"] == "rejected"
    results = store.search(
        "不应进入团队知识",
        {Scope.TEAM_ACCEPTED},
        workspace_id=USER.workspace_id,
        project_id=PROJECT.id,
        user_id=TEAM_LEAD.id,
    )
    assert results == []
    assert not any(
        result.id == created["item"]["id"]
        for result in PersonalAgent(store)._search_team_brain(
            "不应进入团队知识",
            USER,
            workspace_id=USER.workspace_id,
            project_id=PROJECT.id,
        )
    )


def test_memory_capture_revalidates_frozen_artifact_integrity(monkeypatch) -> None:
    clear_store()
    owner, _task, review_id = _accepted_task_review(monkeypatch, "capture-integrity")
    review = store.get_task_review(review_id)
    assert review is not None
    with store._connect() as connection:
        connection.execute(
            "UPDATE artifacts SET content_hash = ? WHERE id = ?",
            ("0" * 64, review.artifact_ids[0]),
        )

    response = owner.post(
        f"/api/task-reviews/{review_id}/memory-candidates",
        json={
            "command_id": "capture-corrupt-artifact-memory",
            "target": "personal",
            "title": "Corrupt source",
            "summary": "Must not persist.",
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "task_review_artifact_integrity_failed"}
    assert not any(item.provenance and item.provenance.review_id == review_id for item in store.user_memory_items)


def test_memory_review_decision_revalidates_source_artifact(monkeypatch) -> None:
    clear_store()
    owner, _task, review_id = _accepted_task_review(monkeypatch, "decision-integrity")
    created = owner.post(
        f"/api/task-reviews/{review_id}/memory-candidates",
        json={
            "command_id": "capture-decision-integrity-candidate",
            "target": "team_candidate",
            "title": "Decision integrity candidate",
            "summary": "The source must remain sealed.",
        },
    ).json()
    task_review = store.get_task_review(review_id)
    assert task_review is not None
    with store._connect() as connection:
        connection.execute(
            "UPDATE artifacts SET content_hash = ? WHERE id = ?",
            ("0" * 64, task_review.artifact_ids[0]),
        )
    memory_review = created["memory_review"]["review"]

    response = authenticated_client(TEAM_LEAD.id).post(
        f"/api/memory-reviews/{memory_review['id']}/decisions",
        json={
            "command_id": "accept-corrupt-memory-source",
            "expected_memory_version": 1,
            "expected_review_version": 1,
            "decision": "accepted",
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "task_review_artifact_integrity_failed"}
    persisted = store.get_memory_item(created["item"]["id"])
    assert persisted is not None and persisted.status is MemoryStatus.PROPOSED
    persisted_review = store.get_memory_review(memory_review["id"])
    assert persisted_review is not None and persisted_review.status.value == "pending"


def test_personal_agent_auto_search_excludes_disputed_memory_and_candidate_posts(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    task, _run, _artifact = _create_reviewable_delivery(authenticated_client(), "auto-memory-filter")
    for item in (
        MemoryItem(
            id="memory_auto_disputed",
            title="unique governed fallback phrase",
            summary="disputed content",
            memory_type="finding",
            scope=Scope.TEAM_ACCEPTED,
            status=MemoryStatus.DISPUTED,
            workspace_id=USER.workspace_id,
            project_id=PROJECT.id,
        ),
        MemoryItem(
            id="memory_auto_candidate",
            title="unique governed fallback phrase",
            summary="candidate content",
            memory_type="finding",
            scope=Scope.TEAM_CANDIDATE,
            status=MemoryStatus.PROPOSED,
            owner_user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=PROJECT.id,
        ),
        MemoryItem(
            id="memory_auto_accepted",
            title="unique governed fallback phrase",
            summary="accepted content",
            memory_type="finding",
            scope=Scope.TEAM_ACCEPTED,
            status=MemoryStatus.ACCEPTED,
            workspace_id=USER.workspace_id,
            project_id=PROJECT.id,
        ),
    ):
        store.add_memory_item(item)
    store.add_blackboard_post(
        BlackboardPost(
            id="bb_auto_memory_candidate",
            task_id=task["task"]["id"],
            post_type=BlackboardPostType.MEMORY_CANDIDATE,
            actor=USER.personal_agent_id,
            title="unique governed fallback phrase",
            content="candidate Blackboard content",
            scope=Scope.TEAM_CANDIDATE,
            permission="project_visible",
        )
    )

    results = PersonalAgent(store)._search_team_brain(
        "unique governed fallback phrase",
        USER,
        workspace_id=USER.workspace_id,
        project_id=PROJECT.id,
    )
    ids = {result.id for result in results}

    assert "memory_auto_accepted" in ids
    assert "memory_auto_disputed" not in ids
    assert "memory_auto_candidate" not in ids
    assert "bb_auto_memory_candidate" not in ids


def test_policy_granted_regular_reviewer_can_view_and_decide_candidate(monkeypatch) -> None:
    clear_store()
    owner, _task, review_id = _accepted_task_review(monkeypatch, "policy-reviewer")
    project = store.get_project(PROJECT.id)
    assert project is not None
    reviewer = store.save_user(
        User(
            id="usr_memory_policy_reviewer",
            workspace_id=USER.workspace_id,
            default_project_id=PROJECT.id,
            name="Memory policy reviewer",
            role=UserRole.USER,
            personal_agent_id="agent_memory_policy_reviewer",
        )
    )
    store.save_agent(
        Agent(
            id=reviewer.personal_agent_id,
            workspace_id=reviewer.workspace_id,
            name="Memory policy reviewer Agent",
            agent_type="personal",
            description="Policy reviewer",
            owner_user_id=reviewer.id,
        )
    )
    project.member_ids = [USER.id, TEAM_LEAD.id, reviewer.id]
    store.save_project(project)
    store.save_permission_policy_rule(
        PermissionPolicyRule(
            id="deny_team_lead_memory_review",
            role=UserRole.TEAM_LEAD,
            action="accept_team_memory",
            effect="deny",
            description="Test deterministic policy reviewer selection",
        )
    )
    store.save_permission_policy_rule(
        PermissionPolicyRule(
            id="allow_regular_memory_review",
            role=UserRole.USER,
            action="accept_team_memory",
            effect="allow",
            description="Test regular reviewer visibility",
        )
    )

    created = owner.post(
        f"/api/task-reviews/{review_id}/memory-candidates",
        json={
            "command_id": "capture-policy-reviewed-candidate",
            "target": "team_candidate",
            "title": "Policy reviewed candidate",
            "summary": "A regular policy-authorized reviewer must not be deadlocked.",
        },
    )
    assert created.status_code == 201
    memory_review = created.json()["memory_review"]["review"]
    assert memory_review["reviewer_id"] == reviewer.id

    _, token = issue_session(store, reviewer)
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    visible = client.get("/api/memory", params={"project_id": PROJECT.id})
    assert visible.status_code == 200
    assert created.json()["item"]["id"] in {item["id"] for item in visible.json()["items"]}
    decision = client.post(
        f"/api/memory-reviews/{memory_review['id']}/decisions",
        json={
            "command_id": "accept-policy-reviewed-candidate",
            "expected_memory_version": 1,
            "expected_review_version": 1,
            "decision": "accepted",
        },
    )
    assert decision.status_code == 200
    assert decision.json()["item"]["status"] == "accepted"


def test_only_review_owner_can_capture_memory(monkeypatch) -> None:
    clear_store()
    owner, _task, review_id = _accepted_task_review(monkeypatch, "capture-privacy")
    response = authenticated_client(TEAM_LEAD.id).post(
        f"/api/task-reviews/{review_id}/memory-candidates",
        json={
            "command_id": "capture-someone-elses-review",
            "target": "personal",
            "title": "不允许的记忆",
            "summary": "不能从其他人的交付创建个人记忆。",
        },
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "memory_capture_forbidden"}
    assert owner.get("/api/memory/entries").status_code == 200


def test_memory_governance_persists_without_providers(monkeypatch) -> None:
    """The route-level tests above exercise the complete path without Provider calls.

    This assertion additionally proves the stored provenance remains readable after a new
    SQLiteStore opens the same database through the ordinary model decoder.
    """
    clear_store()
    owner, _task, review_id = _accepted_task_review(monkeypatch, "governance-persistence")
    entry = owner.post(
        f"/api/task-reviews/{review_id}/memory-candidates",
        json={
            "command_id": "capture-persisted-memory",
            "target": "personal",
            "title": "持久化记忆",
            "summary": "无需任何 Provider。",
        },
    ).json()["item"]
    persisted = store.get_user_memory_item(entry["id"])
    assert persisted is not None
    assert persisted.provenance is not None
    assert persisted.provenance.review_id == review_id
