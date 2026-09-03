from __future__ import annotations

import json

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


def _accepted_team_memory(monkeypatch, suffix: str) -> tuple[TestClient, TestClient, dict, dict]:
    owner, task, review_id = _accepted_task_review(monkeypatch, suffix)
    created = owner.post(
        f"/api/task-reviews/{review_id}/memory-candidates",
        json={
            "command_id": f"capture-team-candidate-{suffix}",
            "target": "team_candidate",
            "title": f"Team knowledge {suffix}",
            "summary": f"Accepted team knowledge for {suffix}.",
            "memory_type": "method",
        },
    )
    assert created.status_code == 201, created.text
    candidate = created.json()
    reviewer = authenticated_client(TEAM_LEAD.id)
    accepted = reviewer.post(
        f"/api/memory-reviews/{candidate['memory_review']['review']['id']}/decisions",
        json={
            "command_id": f"accept-team-candidate-{suffix}",
            "expected_memory_version": 1,
            "expected_review_version": 1,
            "decision": "accepted",
        },
    )
    assert accepted.status_code == 200, accepted.text
    return owner, reviewer, task, accepted.json()["item"]


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
    assert owner_detail["memory_links"][0]["navigation_href"] == (
        f"/knowledge?project={PROJECT.id}&memory={entry['id']}"
    )
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


def test_pre_slice4b_command_receipt_without_content_hash_remains_replayable(monkeypatch) -> None:
    clear_store()
    owner, _task, review_id = _accepted_task_review(monkeypatch, "legacy-receipt")
    request = {
        "command_id": "capture-legacy-receipt-memory",
        "target": "personal",
        "title": "Legacy receipt",
        "summary": "The stored Slice 4A response predates content_hash.",
    }
    first = owner.post(f"/api/task-reviews/{review_id}/memory-candidates", json=request)
    assert first.status_code == 201
    with store._connect() as connection:
        row = connection.execute(
            "SELECT id, payload FROM records WHERE collection = 'memory_governance_command_receipts'"
        ).fetchone()
        assert row is not None
        payload = json.loads(row["payload"])
        payload["result_entry"].pop("content_hash", None)
        connection.execute(
            "UPDATE records SET payload = ? WHERE collection = 'memory_governance_command_receipts' AND id = ?",
            (json.dumps(payload), row["id"]),
        )

    replay = owner.post(f"/api/task-reviews/{review_id}/memory-candidates", json=request)

    assert replay.status_code == 201
    assert replay.json()["item"]["id"] == first.json()["item"]["id"]
    assert replay.json()["item"]["content_hash"] is None


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


def test_team_memory_revision_activates_new_version_and_deprecates_source_atomically(monkeypatch) -> None:
    clear_store()
    owner, reviewer, _task, source = _accepted_team_memory(monkeypatch, "revision-activation")

    created = owner.post(
        f"/api/memory/{source['id']}/revisions",
        json={
            "command_id": "create-memory-revision",
            "expected_version": source["version"],
            "title": "Revised team knowledge",
            "summary": "The revised conclusion keeps an immutable predecessor.",
            "memory_type": "method",
        },
    )

    assert created.status_code == 201, created.text
    candidate = created.json()["item"]
    memory_review = created.json()["memory_review"]["review"]
    assert candidate["scope"] == "team_candidate"
    assert candidate["status"] == "proposed"
    assert candidate["supersedes_memory_id"] == source["id"]
    assert candidate["provenance"]["source_kind"] == "memory_revision"
    assert candidate["provenance"]["source_memory_ids"] == [source["id"]]
    assert candidate["provenance"]["source_memory_versions"] == [source["version"]]
    assert candidate["provenance"]["source_memory_hashes"] == [source["content_hash"]]
    unchanged_source = store.get_memory_item(source["id"])
    assert unchanged_source is not None and unchanged_source.status is MemoryStatus.ACCEPTED
    competing = owner.post(
        f"/api/memory/{source['id']}/revisions",
        json={
            "command_id": "create-competing-memory-revision",
            "expected_version": source["version"],
            "title": "Competing revision",
            "summary": "Only one pending successor may exist.",
            "memory_type": "method",
        },
    )
    assert competing.status_code == 409
    assert competing.json() == {"detail": "memory_revision_successor_exists"}

    accepted = reviewer.post(
        f"/api/memory-reviews/{memory_review['id']}/decisions",
        json={
            "command_id": "accept-memory-revision",
            "expected_memory_version": candidate["version"],
            "expected_review_version": memory_review["version"],
            "decision": "accepted",
            "decision_note": "The correction is supported.",
        },
    )

    assert accepted.status_code == 200, accepted.text
    activated = accepted.json()["item"]
    assert activated["scope"] == "team_accepted"
    assert activated["status"] == "accepted"
    assert activated["version"] == 2
    superseded = store.get_memory_item(source["id"])
    assert superseded is not None
    assert superseded.status is MemoryStatus.DEPRECATED
    assert superseded.version == source["version"] + 1
    assert store.memory_item_eligible_for_agent(superseded) is False
    assert store.memory_item_eligible_for_agent(store.get_memory_item(activated["id"])) is True
    search_ids = {
        result.id
        for result in store.search_for_agent(
            "team knowledge",
            USER.personal_agent_id,
            workspace_id=USER.workspace_id,
            project_id=PROJECT.id,
            user_id=USER.id,
        )
    }
    assert activated["id"] in search_ids
    assert source["id"] not in search_ids

    lineage = reviewer.get(f"/api/memory/entries/{activated['id']}/lineage")
    assert lineage.status_code == 200
    assert lineage.json()["source_memories"] == [
        {
            "id": source["id"],
            "title": source["title"],
            "status": "deprecated",
            "scope": "team_accepted",
            "version": source["version"] + 1,
            "content_hash": source["content_hash"],
            "navigation_href": f"/knowledge?project={PROJECT.id}&memory={source['id']}",
        }
    ]
    source_lineage = reviewer.get(f"/api/memory/entries/{source['id']}/lineage").json()
    assert [item["id"] for item in source_lineage["superseded_by_memories"]] == [activated["id"]]
    assert {event["action"] for event in source_lineage["governance_events"]} >= {
        "capture_memory_from_task_review",
        "decide_memory_review",
    }
    run_id = activated["provenance"]["run_id"]
    artifact_id = activated["provenance"]["artifact_ids"][0]
    run_links = owner.get(f"/api/agent/runs/{run_id}/memory-links")
    artifact_links = owner.get(f"/api/artifacts/{artifact_id}/memory-links")
    assert run_links.status_code == 200
    assert artifact_links.status_code == 200
    assert {item["id"] for item in run_links.json()["items"]} == {source["id"], activated["id"]}
    assert {item["id"] for item in artifact_links.json()["items"]} == {source["id"], activated["id"]}
    assert reviewer.get(f"/api/agent/runs/{run_id}/memory-links").status_code == 404
    assert reviewer.get(f"/api/artifacts/{artifact_id}/memory-links").status_code == 404
    assert {event["action"] for event in lineage.json()["governance_events"]} >= {
        "create_memory_revision",
        "decide_memory_review",
    }

    replay = owner.post(
        f"/api/memory/{source['id']}/revisions",
        json={
            "command_id": "create-memory-revision",
            "expected_version": source["version"],
            "title": "Revised team knowledge",
            "summary": "The revised conclusion keeps an immutable predecessor.",
            "memory_type": "method",
        },
    )
    assert replay.status_code == 201
    assert replay.json()["item"]["id"] == candidate["id"]
    assert len([item for item in store.memory_items if item.supersedes_memory_id == source["id"]]) == 1


def test_memory_revision_revalidates_original_artifact_integrity(monkeypatch) -> None:
    clear_store()
    owner, _reviewer, _task, source = _accepted_team_memory(monkeypatch, "revision-artifact-integrity")
    artifact_id = source["provenance"]["artifact_ids"][0]
    with store._connect() as connection:
        connection.execute(
            "UPDATE artifacts SET content_hash = ? WHERE id = ?",
            ("0" * 64, artifact_id),
        )

    response = owner.post(
        f"/api/memory/{source['id']}/revisions",
        json={
            "command_id": "revision-with-corrupt-artifact",
            "expected_version": source["version"],
            "title": "Corrupt revision",
            "summary": "Must not be persisted.",
            "memory_type": "method",
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "task_review_artifact_integrity_failed"}
    assert not any(item.supersedes_memory_id == source["id"] for item in store.memory_items)


def test_memory_revision_acceptance_fails_when_source_version_changes(monkeypatch) -> None:
    clear_store()
    owner, reviewer, _task, source = _accepted_team_memory(monkeypatch, "revision-stale-source")
    created = owner.post(
        f"/api/memory/{source['id']}/revisions",
        json={
            "command_id": "create-stale-source-revision",
            "expected_version": source["version"],
            "title": "Stale source revision",
            "summary": "This must not activate after the source changes.",
            "memory_type": "method",
        },
    ).json()

    disputed = reviewer.post(
        f"/api/memory/{source['id']}/transitions",
        json={
            "command_id": "dispute-revision-source",
            "expected_version": source["version"],
            "action": "dispute",
        },
    )
    assert disputed.status_code == 200, disputed.text
    memory_review = created["memory_review"]["review"]
    decision = reviewer.post(
        f"/api/memory-reviews/{memory_review['id']}/decisions",
        json={
            "command_id": "accept-stale-source-revision",
            "expected_memory_version": created["item"]["version"],
            "expected_review_version": memory_review["version"],
            "decision": "accepted",
        },
    )

    assert decision.status_code == 409
    assert decision.json() == {"detail": "memory_revision_source_version_conflict"}
    candidate = store.get_memory_item(created["item"]["id"])
    assert candidate is not None and candidate.status is MemoryStatus.PROPOSED
    current_source = store.get_memory_item(source["id"])
    assert current_source is not None and current_source.status is MemoryStatus.DISPUTED


def test_noop_memory_revision_is_rejected(monkeypatch) -> None:
    clear_store()
    owner, _reviewer, _task, source = _accepted_team_memory(monkeypatch, "revision-noop")

    response = owner.post(
        f"/api/memory/{source['id']}/revisions",
        json={
            "command_id": "create-noop-memory-revision",
            "expected_version": source["version"],
            "title": source["title"],
            "summary": source["summary"],
            "memory_type": source["memory_type"],
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "memory_revision_no_changes"}
    assert not any(item.supersedes_memory_id == source["id"] for item in store.memory_items)


def test_pending_revision_is_concealed_from_unrelated_project_member(monkeypatch) -> None:
    clear_store()
    owner, reviewer, _task, source = _accepted_team_memory(monkeypatch, "revision-concealment")
    project = store.get_project(PROJECT.id)
    assert project is not None
    viewer = store.save_user(
        User(
            id="usr_memory_revision_viewer",
            workspace_id=USER.workspace_id,
            default_project_id=PROJECT.id,
            name="Memory revision viewer",
            role=UserRole.USER,
            personal_agent_id="agent_memory_revision_viewer",
        )
    )
    project.member_ids = [*project.member_ids, viewer.id]
    store.save_project(project)
    _, token = issue_session(store, viewer)
    viewer_client = TestClient(app)
    viewer_client.cookies.set(SESSION_COOKIE_NAME, token)
    created = owner.post(
        f"/api/memory/{source['id']}/revisions",
        json={
            "command_id": "create-concealed-revision",
            "expected_version": source["version"],
            "title": "Concealed pending revision",
            "summary": "Not visible before independent acceptance.",
            "memory_type": "method",
        },
    ).json()

    pending_lineage = viewer_client.get(f"/api/memory/entries/{source['id']}/lineage")
    assert pending_lineage.status_code == 200
    assert pending_lineage.json()["superseded_by_memory_ids"] == []
    assert "create_memory_revision" not in {
        event["action"] for event in pending_lineage.json()["governance_events"]
    }
    assert viewer_client.get(f"/api/memory/entries/{created['item']['id']}").status_code == 404

    review = created["memory_review"]["review"]
    accepted = reviewer.post(
        f"/api/memory-reviews/{review['id']}/decisions",
        json={
            "command_id": "accept-concealed-revision",
            "expected_memory_version": 1,
            "expected_review_version": 1,
            "decision": "accepted",
        },
    )
    assert accepted.status_code == 200
    visible_lineage = viewer_client.get(f"/api/memory/entries/{source['id']}/lineage").json()
    assert visible_lineage["superseded_by_memory_ids"] == [created["item"]["id"]]
    assert "create_memory_revision" in {
        event["action"] for event in visible_lineage["governance_events"]
    }


def test_hidden_manager_revision_suppresses_source_owner_revise_action(monkeypatch) -> None:
    clear_store()
    owner, manager, _task, source = _accepted_team_memory(monkeypatch, "hidden-manager-revision")
    created = manager.post(
        f"/api/memory/{source['id']}/revisions",
        json={
            "command_id": "manager-created-hidden-revision",
            "expected_version": source["version"],
            "title": "Manager correction",
            "summary": "The original owner cannot see this pending candidate.",
            "memory_type": "method",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["item"]["owner_user_id"] == TEAM_LEAD.id
    assert owner.get(f"/api/memory/entries/{created.json()['item']['id']}").status_code == 404

    listed = owner.get("/api/memory/entries", params={"project_id": PROJECT.id}).json()["items"]
    listed_source = next(item for item in listed if item["id"] == source["id"])
    detailed_source = owner.get(f"/api/memory/entries/{source['id']}").json()
    assert "revise" not in listed_source["allowed_actions"]
    assert listed_source["allowed_actions"] == detailed_source["allowed_actions"]
    competing = owner.post(
        f"/api/memory/{source['id']}/revisions",
        json={
            "command_id": "owner-competing-hidden-revision",
            "expected_version": source["version"],
            "title": "Competing owner correction",
            "summary": "This must fail instead of creating a second pending revision.",
            "memory_type": "method",
        },
    )
    assert competing.status_code == 409
    assert competing.json() == {"detail": "memory_revision_successor_exists"}


def test_memory_revision_acceptance_rejects_source_content_tampering(monkeypatch) -> None:
    clear_store()
    owner, reviewer, _task, source = _accepted_team_memory(monkeypatch, "revision-source-integrity")
    created = owner.post(
        f"/api/memory/{source['id']}/revisions",
        json={
            "command_id": "create-integrity-revision",
            "expected_version": source["version"],
            "title": "Integrity revision",
            "summary": "The source content hash must still match.",
            "memory_type": "method",
        },
    ).json()
    source_item = store.get_memory_item(source["id"])
    assert source_item is not None
    tampered = source_item.model_copy(update={"summary": "tampered without a version increment"})
    with store._connect() as connection:
        connection.execute(
            "UPDATE records SET payload = ? WHERE collection = 'memory_items' AND id = ?",
            (tampered.model_dump_json(), source_item.id),
        )

    review = created["memory_review"]["review"]
    decision = reviewer.post(
        f"/api/memory-reviews/{review['id']}/decisions",
        json={
            "command_id": "accept-tampered-source-revision",
            "expected_memory_version": created["item"]["version"],
            "expected_review_version": review["version"],
            "decision": "accepted",
        },
    )

    assert decision.status_code == 409
    assert decision.json() == {"detail": "memory_revision_source_integrity_failed"}
    candidate = store.get_memory_item(created["item"]["id"])
    assert candidate is not None and candidate.status is MemoryStatus.PROPOSED


def test_rejected_revision_keeps_source_active_and_allows_a_later_attempt(monkeypatch) -> None:
    clear_store()
    owner, reviewer, _task, source = _accepted_team_memory(monkeypatch, "revision-retry")
    first = owner.post(
        f"/api/memory/{source['id']}/revisions",
        json={
            "command_id": "create-rejected-revision",
            "expected_version": source["version"],
            "title": "Rejected revision",
            "summary": "This proposal will be rejected.",
            "memory_type": "method",
        },
    ).json()
    review = first["memory_review"]["review"]
    rejected = reviewer.post(
        f"/api/memory-reviews/{review['id']}/decisions",
        json={
            "command_id": "reject-revision",
            "expected_memory_version": first["item"]["version"],
            "expected_review_version": review["version"],
            "decision": "rejected",
            "decision_note": "Needs another correction.",
        },
    )
    assert rejected.status_code == 200
    current_source = store.get_memory_item(source["id"])
    assert current_source is not None and current_source.status is MemoryStatus.ACCEPTED
    assert current_source.version == source["version"]

    second = owner.post(
        f"/api/memory/{source['id']}/revisions",
        json={
            "command_id": "create-second-revision",
            "expected_version": source["version"],
            "title": "Second revision",
            "summary": "A corrected retry after independent rejection.",
            "memory_type": "method",
        },
    )
    assert second.status_code == 201, second.text
    assert second.json()["item"]["supersedes_memory_id"] == source["id"]


def test_memory_lifecycle_requires_manage_permission_and_valid_transition(monkeypatch) -> None:
    clear_store()
    owner, reviewer, _task, source = _accepted_team_memory(monkeypatch, "lifecycle-auth")

    forbidden = owner.post(
        f"/api/memory/{source['id']}/transitions",
        json={
            "command_id": "owner-cannot-dispute-team-memory",
            "expected_version": source["version"],
            "action": "dispute",
        },
    )
    assert forbidden.status_code == 403
    assert forbidden.json() == {"detail": "memory_lifecycle_forbidden"}

    invalid = reviewer.post(
        f"/api/memory/{source['id']}/transitions",
        json={
            "command_id": "cannot-restore-active-memory",
            "expected_version": source["version"],
            "action": "restore",
        },
    )
    assert invalid.status_code == 409
    assert invalid.json() == {"detail": "memory_lifecycle_transition_invalid"}


def test_policy_can_revoke_team_memory_lifecycle_management(monkeypatch) -> None:
    clear_store()
    _owner, reviewer, _task, source = _accepted_team_memory(monkeypatch, "lifecycle-policy-deny")
    store.save_permission_policy_rule(
        PermissionPolicyRule(
            id="deny_team_lead_memory_management",
            role=UserRole.TEAM_LEAD,
            action="manage_team_memory",
            effect="deny",
            description="Test lifecycle revocation",
        )
    )

    detail = reviewer.get(f"/api/memory/entries/{source['id']}")
    assert detail.status_code == 200
    assert "dispute" not in detail.json()["allowed_actions"]
    response = reviewer.post(
        f"/api/memory/{source['id']}/transitions",
        json={
            "command_id": "denied-memory-transition",
            "expected_version": source["version"],
            "action": "dispute",
        },
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "memory_lifecycle_forbidden"}


def test_memory_lifecycle_respects_read_only_mode(monkeypatch) -> None:
    clear_store()
    _owner, reviewer, _task, source = _accepted_team_memory(monkeypatch, "lifecycle-read-only")
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "read_only")

    response = reviewer.post(
        f"/api/memory/{source['id']}/transitions",
        json={
            "command_id": "read-only-memory-transition",
            "expected_version": source["version"],
            "action": "dispute",
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "task_management_read_only"}


def test_memory_lifecycle_transitions_are_versioned_audited_and_retrieval_safe(monkeypatch) -> None:
    clear_store()
    owner, reviewer, _task, source = _accepted_team_memory(monkeypatch, "lifecycle")
    owner_view = owner.get(f"/api/memory/entries/{source['id']}").json()
    assert "revise" in owner_view["allowed_actions"]
    assert "dispute" not in owner_view["allowed_actions"]
    manager_view = reviewer.get(f"/api/memory/entries/{source['id']}").json()
    assert {"revise", "dispute", "deprecate", "expire", "archive"} <= set(manager_view["allowed_actions"])

    disputed = reviewer.post(
        f"/api/memory/{source['id']}/transitions",
        json={
            "command_id": "transition-memory-disputed",
            "expected_version": source["version"],
            "action": "dispute",
        },
    )
    assert disputed.status_code == 200, disputed.text
    disputed_item = disputed.json()["item"]
    assert disputed_item["status"] == "disputed"
    assert disputed_item["version"] == source["version"] + 1
    assert store.search_for_agent(
        source["title"],
        USER.personal_agent_id,
        workspace_id=USER.workspace_id,
        project_id=PROJECT.id,
        user_id=USER.id,
    ) == []

    replay = reviewer.post(
        f"/api/memory/{source['id']}/transitions",
        json={
            "command_id": "transition-memory-disputed",
            "expected_version": source["version"],
            "action": "dispute",
        },
    )
    assert replay.status_code == 200
    assert replay.json() == disputed.json()
    conflict = reviewer.post(
        f"/api/memory/{source['id']}/transitions",
        json={
            "command_id": "transition-memory-disputed",
            "expected_version": source["version"],
            "action": "archive",
        },
    )
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "memory_governance_command_conflict"}

    archived = reviewer.post(
        f"/api/memory/{source['id']}/transitions",
        json={
            "command_id": "archive-disputed-memory",
            "expected_version": disputed_item["version"],
            "action": "archive",
        },
    ).json()["item"]
    assert archived["status"] == "archived"
    assert archived["archived_from_status"] == "disputed"
    assert archived["archived_at"] is not None
    hidden_by_default = reviewer.get("/api/memory/entries", params={"project_id": PROJECT.id})
    assert source["id"] not in {item["id"] for item in hidden_by_default.json()["items"]}
    included_history = reviewer.get(
        "/api/memory/entries",
        params={"project_id": PROJECT.id, "include_archived": "true"},
    )
    assert source["id"] in {item["id"] for item in included_history.json()["items"]}
    restored = reviewer.post(
        f"/api/memory/{source['id']}/transitions",
        json={
            "command_id": "restore-disputed-memory",
            "expected_version": archived["version"],
            "action": "restore",
        },
    ).json()["item"]
    assert restored["status"] == "disputed"
    assert restored["archived_from_status"] is None
    assert restored["archived_at"] is None
    assert [event.action for event in store.audit_events if event.target_id == source["id"]][-3:] == [
        "transition_memory_dispute",
        "transition_memory_archive",
        "transition_memory_restore",
    ]


def test_restoring_archived_accepted_memory_reenables_agent_context(monkeypatch) -> None:
    clear_store()
    _owner, reviewer, _task, source = _accepted_team_memory(monkeypatch, "restore-accepted")
    archived = reviewer.post(
        f"/api/memory/{source['id']}/transitions",
        json={
            "command_id": "archive-accepted-memory",
            "expected_version": source["version"],
            "action": "archive",
        },
    ).json()["item"]
    assert archived["status"] == "archived"
    assert not any(
        result.id == source["id"]
        for result in store.search_for_agent(
            source["title"],
            USER.personal_agent_id,
            workspace_id=USER.workspace_id,
            project_id=PROJECT.id,
            user_id=USER.id,
        )
    )

    restored = reviewer.post(
        f"/api/memory/{source['id']}/transitions",
        json={
            "command_id": "restore-accepted-memory",
            "expected_version": archived["version"],
            "action": "restore",
        },
    )

    assert restored.status_code == 200
    assert restored.json()["item"]["status"] == "accepted"
    assert any(
        result.id == source["id"]
        for result in store.search_for_agent(
            source["title"],
            USER.personal_agent_id,
            workspace_id=USER.workspace_id,
            project_id=PROJECT.id,
            user_id=USER.id,
        )
    )


def test_archived_accepted_revision_cannot_restore_beside_newer_active_sibling(monkeypatch) -> None:
    clear_store()
    owner, reviewer, _task, source = _accepted_team_memory(monkeypatch, "restore-sibling")
    first = owner.post(
        f"/api/memory/{source['id']}/revisions",
        json={
            "command_id": "create-first-successor",
            "expected_version": source["version"],
            "title": "First accepted successor",
            "summary": "This version will later be archived.",
            "memory_type": "method",
        },
    ).json()
    first_review = first["memory_review"]["review"]
    first_accepted = reviewer.post(
        f"/api/memory-reviews/{first_review['id']}/decisions",
        json={
            "command_id": "accept-first-successor",
            "expected_memory_version": 1,
            "expected_review_version": 1,
            "decision": "accepted",
        },
    ).json()["item"]
    archived = reviewer.post(
        f"/api/memory/{first_accepted['id']}/transitions",
        json={
            "command_id": "archive-first-successor",
            "expected_version": first_accepted["version"],
            "action": "archive",
        },
    ).json()["item"]
    current_source = store.get_memory_item(source["id"])
    assert current_source is not None and current_source.status is MemoryStatus.DEPRECATED
    second = owner.post(
        f"/api/memory/{source['id']}/revisions",
        json={
            "command_id": "create-second-active-successor",
            "expected_version": current_source.version,
            "title": "Second accepted successor",
            "summary": "This version remains active.",
            "memory_type": "method",
        },
    ).json()
    second_review = second["memory_review"]["review"]
    assert reviewer.post(
        f"/api/memory-reviews/{second_review['id']}/decisions",
        json={
            "command_id": "accept-second-active-successor",
            "expected_memory_version": 1,
            "expected_review_version": 1,
            "decision": "accepted",
        },
    ).status_code == 200

    archived_detail = reviewer.get(f"/api/memory/entries/{archived['id']}")
    assert "restore" not in archived_detail.json()["allowed_actions"]
    restore = reviewer.post(
        f"/api/memory/{archived['id']}/transitions",
        json={
            "command_id": "restore-obsolete-accepted-successor",
            "expected_version": archived["version"],
            "action": "restore",
        },
    )
    assert restore.status_code == 409
    assert restore.json() == {"detail": "memory_restore_active_successor_exists"}
    assert store.get_memory_item(archived["id"]).status is MemoryStatus.ARCHIVED


def test_expiring_candidate_cancels_review_and_resolves_inbox(monkeypatch) -> None:
    clear_store()
    owner, _task, review_id = _accepted_task_review(monkeypatch, "expire-candidate")
    created = owner.post(
        f"/api/task-reviews/{review_id}/memory-candidates",
        json={
            "command_id": "capture-expiring-candidate",
            "target": "team_candidate",
            "title": "Expiring candidate",
            "summary": "This candidate should leave the review queue.",
        },
    ).json()
    item = created["item"]
    review = created["memory_review"]["review"]

    expired = authenticated_client(TEAM_LEAD.id).post(
        f"/api/memory/{item['id']}/transitions",
        json={
            "command_id": "expire-memory-candidate",
            "expected_version": item["version"],
            "action": "expire",
        },
    )

    assert expired.status_code == 200, expired.text
    assert expired.json()["item"]["status"] == "expired"
    stored_review = store.get_memory_review(review["id"])
    assert stored_review is not None and stored_review.status.value == "cancelled"
    assert not any(
        inbox.metadata.get("memory_review_id") == review["id"] and inbox.status != "resolved"
        for inbox in store.inbox_items
    )
    stale_decision = authenticated_client(TEAM_LEAD.id).post(
        f"/api/memory-reviews/{review['id']}/decisions",
        json={
            "command_id": "accept-expired-candidate",
            "expected_memory_version": item["version"] + 1,
            "expected_review_version": review["version"] + 1,
            "decision": "accepted",
        },
    )
    assert stale_decision.status_code == 409
    assert stale_decision.json() == {"detail": "memory_review_already_decided"}
    replay = authenticated_client(TEAM_LEAD.id).post(
        f"/api/memory/{item['id']}/transitions",
        json={
            "command_id": "expire-memory-candidate",
            "expected_version": item["version"],
            "action": "expire",
        },
    )
    assert replay.status_code == 200
    assert replay.json() == expired.json()


def test_memory_history_filters_and_legacy_governance_boundary(monkeypatch) -> None:
    clear_store()
    _owner, reviewer, _task, source = _accepted_team_memory(monkeypatch, "history-filter")
    deprecated = reviewer.post(
        f"/api/memory/{source['id']}/transitions",
        json={
            "command_id": "deprecate-filter-memory",
            "expected_version": source["version"],
            "action": "deprecate",
        },
    )
    assert deprecated.status_code == 200
    for index in range(110):
        store.add_memory_item(
            MemoryItem(
                id=f"active-history-crowd-{index:03d}",
                title=f"Active history crowd {index}",
                summary="Must not crowd inactive governance history.",
                memory_type="method",
                scope=Scope.TEAM_ACCEPTED,
                status=MemoryStatus.ACCEPTED,
                workspace_id=USER.workspace_id,
                project_id=PROJECT.id,
            )
        )
    inactive_page = reviewer.get(
        "/api/memory/entries",
        params={
            "project_id": PROJECT.id,
            "lifecycle": "inactive",
            "include_archived": "true",
            "page_size": 1,
        },
    )
    assert inactive_page.status_code == 200
    assert inactive_page.json()["total"] == 1
    assert [item["id"] for item in inactive_page.json()["items"]] == [source["id"]]

    filtered = reviewer.get(
        "/api/memory/entries",
        params={
            "project_id": PROJECT.id,
            "status": "deprecated",
            "kind": "team_knowledge",
            "scope": "team_accepted",
            "include_archived": "true",
        },
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()["items"]] == [source["id"]]

    legacy = store.add_memory_item(
        MemoryItem(
            id="legacy_accepted_memory_for_governance",
            title="Legacy accepted memory",
            summary="No structured provenance.",
            memory_type="legacy",
            scope=Scope.TEAM_ACCEPTED,
            status=MemoryStatus.ACCEPTED,
            workspace_id=USER.workspace_id,
            project_id=PROJECT.id,
        )
    )
    legacy_detail = reviewer.get(f"/api/memory/entries/{legacy.id}")
    assert legacy_detail.status_code == 200
    assert legacy_detail.json()["provenance_state"] == "legacy_unverified"
    assert legacy_detail.json()["allowed_actions"] == []
    revision = reviewer.post(
        f"/api/memory/{legacy.id}/revisions",
        json={
            "command_id": "revise-legacy-memory",
            "expected_version": 1,
            "title": "Should fail",
            "summary": "Legacy provenance cannot be invented.",
            "memory_type": "legacy",
        },
    )
    assert revision.status_code == 409
    assert revision.json() == {"detail": "memory_governance_required"}


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


def test_policy_granted_regular_manager_can_expire_candidate_without_review_permission(monkeypatch) -> None:
    clear_store()
    owner, _task, review_id = _accepted_task_review(monkeypatch, "policy-manager")
    project = store.get_project(PROJECT.id)
    assert project is not None
    manager = store.save_user(
        User(
            id="usr_memory_policy_manager",
            workspace_id=USER.workspace_id,
            default_project_id=PROJECT.id,
            name="Memory policy manager",
            role=UserRole.USER,
            personal_agent_id="agent_memory_policy_manager",
        )
    )
    project.member_ids = [USER.id, TEAM_LEAD.id, manager.id]
    store.save_project(project)
    store.save_permission_policy_rule(
        PermissionPolicyRule(
            id="allow_regular_memory_management",
            role=UserRole.USER,
            action="manage_team_memory",
            effect="allow",
            description="Test lifecycle permission visibility",
        )
    )
    created = owner.post(
        f"/api/task-reviews/{review_id}/memory-candidates",
        json={
            "command_id": "capture-policy-managed-candidate",
            "target": "team_candidate",
            "title": "Policy managed candidate",
            "summary": "A manager may expire but not accept this review.",
        },
    ).json()
    _, token = issue_session(store, manager)
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE_NAME, token)

    detail = client.get(f"/api/memory/entries/{created['item']['id']}")
    assert detail.status_code == 200
    assert "expire" in detail.json()["allowed_actions"]
    assert "accept_review" not in detail.json()["allowed_actions"]
    expired = client.post(
        f"/api/memory/{created['item']['id']}/transitions",
        json={
            "command_id": "policy-manager-expire-candidate",
            "expected_version": 1,
            "action": "expire",
        },
    )
    assert expired.status_code == 200
    assert expired.json()["item"]["status"] == "expired"


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
