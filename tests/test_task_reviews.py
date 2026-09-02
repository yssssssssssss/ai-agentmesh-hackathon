from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from fastapi.testclient import TestClient

from agentmesh.app import app
from agentmesh.artifacts import UniversalSynthesisEnvelopeV1, V1VerifiedArtifactStore
from agentmesh.auth import SESSION_COOKIE_NAME, issue_session
from agentmesh.canonical_json import canonical_json_bytes
from agentmesh.models import (
    AgentPlanningContractVersion,
    AgentRun,
    AgentRunStatus,
    Artifact,
    ArtifactVerificationState,
    BlackboardPost,
    BlackboardPostType,
    Project,
    Scope,
    SkillOrchestrationRequestMode,
    SkillSynthesisResult,
    TaskReviewStatus,
    TaskReviewV1,
    User,
    Workspace,
    now_utc,
)
from agentmesh.seed import ADMIN, TEAM_LEAD, USER
from agentmesh.store import store
from tests.test_chat_flow import authenticated_client, clear_store


def _create_in_progress_task(client: TestClient, suffix: str) -> dict:
    item = client.post(
        "/api/tasks",
        json={"command_id": f"review-create-{suffix}", "title": f"Review task {suffix}"},
    ).json()["item"]
    for action in ("plan", "start"):
        response = client.post(
            f"/api/tasks/{item['task']['id']}/transitions",
            json={
                "command_id": f"review-{action}-{suffix}",
                "expected_version": item["management"]["version"],
                "action": action,
            },
        )
        assert response.status_code == 200
        item = response.json()["item"]
    return item


def _create_reviewable_delivery(client: TestClient, suffix: str) -> tuple[dict, AgentRun, Artifact]:
    task = _create_in_progress_task(client, suffix)
    run, created = store.claim_new_agent_run(
        AgentRun(
            id=f"run_review_{suffix}",
            thread_id=task["task"]["thread_id"],
            task_id=task["task"]["id"],
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="Produce a reviewable project delivery",
            client_turn_id=f"review-run-{suffix}",
            status=AgentRunStatus.COMPLETED,
            requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
            orchestration_mode="preview",
            planning_contract_version=AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1,
        )
    )
    assert created is True
    envelope = UniversalSynthesisEnvelopeV1(
        run_id=run.id,
        requirement_version_id=f"review-requirement-{suffix}",
        plan_id=f"review-plan-{suffix}",
        plan_version=1,
        synthesis=SkillSynthesisResult(summary="Reviewable project delivery"),
    )
    content = canonical_json_bytes(envelope.model_dump(mode="json")).decode()
    artifact = Artifact(
        id=f"artifact_review_{suffix}",
        run_id=run.id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        user_id=run.user_id,
        artifact_type="universal_synthesis",
        content_type="application/json",
        content=content,
        verification_state=ArtifactVerificationState.SEALED,
        schema_version="universal-synthesis-v1",
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        size_bytes=len(content.encode()),
        requirement_version_id=envelope.requirement_version_id,
        plan_version_id=f"{envelope.plan_id}:v{envelope.plan_version}",
    )
    V1VerifiedArtifactStore(store).insert_sealed(artifact)
    return task, run, artifact


def _submit_review(client: TestClient, task: dict, run: AgentRun, artifact: Artifact, suffix: str) -> dict:
    response = client.post(
        f"/api/tasks/{task['task']['id']}/reviews",
        json={
            "command_id": f"submit-review-{suffix}",
            "expected_task_version": task["management"]["version"],
            "run_id": run.id,
            "artifact_ids": [artifact.id],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_submit_and_accept_review_atomically_gates_linked_task_completion(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    requester = authenticated_client()
    task, run, artifact = _create_reviewable_delivery(requester, "accepted")

    bypass = requester.post(
        f"/api/tasks/{task['task']['id']}/transitions",
        json={
            "command_id": "bypass-artifact-review",
            "expected_version": task["management"]["version"],
            "action": "submit_review",
        },
    )
    assert bypass.status_code == 409
    assert bypass.json() == {"detail": "task_artifact_review_required"}

    submitted = _submit_review(requester, task, run, artifact, "accepted")
    review = submitted["item"]["review"]
    assert review["schema_version"] == "task-review-v1"
    assert review["artifact_ids"] == [artifact.id]
    assert review["artifact_hashes"] == [artifact.content_hash]
    assert review["reviewer_id"] == TEAM_LEAD.id
    assert review["status"] == "pending"
    assert review["round"] == 1
    assert review["task_version"] == task["management"]["version"] + 1
    assert submitted["task"]["management"]["delivery_stage"] == "review"
    assert submitted["task"]["status"] == task["task"]["status"]
    assert submitted["task"]["collaboration_stage"] == task["task"]["collaboration_stage"]
    assert requester.get(f"/api/tasks/{task['task']['id']}").json()["item"]["allowed_actions"] == []
    pending_update = requester.patch(
        f"/api/tasks/{task['task']['id']}",
        json={
            "command_id": "edit-during-pending-review",
            "expected_version": review["task_version"],
            "description": "This must not change frozen review criteria.",
        },
    )
    assert pending_update.status_code == 409
    assert pending_update.json() == {"detail": "task_review_pending"}
    parent = store.add_blackboard_post(
        BlackboardPost(
            id="bb_review_freeze",
            task_id=task["task"]["id"],
            post_type=BlackboardPostType.REQUEST,
            actor=USER.personal_agent_id,
            title="Pending review handoff",
            content="Do not alter review criteria",
            scope=Scope.PROJECT,
            permission="project_visible",
            current_owner_agent_id=USER.personal_agent_id,
            current_owner_label="Owner",
            done_when="Original criterion",
        )
    )
    handoff = requester.post(
        f"/api/blackboard/posts/{parent.id}/handoff",
        json={
            "goal": "Change owner",
            "current_result": "Pending review",
            "done_when": "Changed criterion",
            "next_owner_agent_id": TEAM_LEAD.personal_agent_id,
            "blockers": [],
            "requires_input_from": [],
        },
    )
    assert handoff.status_code == 409
    assert handoff.json() == {"detail": "task_review_pending"}
    frozen_task = store.get_task(task["task"]["id"])
    assert frozen_task is not None
    assert frozen_task.done_when == task["task"]["done_when"]
    assert frozen_task.steps == task["task"]["steps"]
    stale_legacy_write = frozen_task.model_copy(deep=True)
    stale_legacy_write.done_when = "Changed after the review was submitted"
    stale_legacy_write.steps.append("changed_acceptance_criteria")
    store.save_task(stale_legacy_write)
    preserved_task = store.get_task(task["task"]["id"])
    assert preserved_task is not None
    assert preserved_task.done_when == frozen_task.done_when
    assert preserved_task.steps == frozen_task.steps

    replay = requester.post(
        f"/api/tasks/{task['task']['id']}/reviews",
        json={
            "command_id": "submit-review-accepted",
            "expected_task_version": task["management"]["version"],
            "run_id": run.id,
            "artifact_ids": [artifact.id],
        },
    )
    assert replay.status_code == 201
    assert replay.json()["item"]["review"]["id"] == review["id"]
    assert len(store.list_task_reviews(task["task"]["id"])) == 1

    reviewer = authenticated_client(TEAM_LEAD.id)
    reviewer_detail = reviewer.get(f"/api/tasks/{task['task']['id']}").json()
    assert reviewer_detail["item"]["allowed_actions"] == ["review_deliverable"]
    assert reviewer_detail["reviews"][0]["review"]["id"] == review["id"]
    assert reviewer_detail["artifacts"][0]["download_href"] is None
    inspection = reviewer.get(
        f"/api/task-reviews/{review['id']}/artifacts/{artifact.id}"
    )
    assert inspection.status_code == 200
    assert inspection.text == artifact.content
    assert inspection.headers["x-agentmesh-artifact-hash"] == artifact.content_hash
    assert inspection.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert inspection.headers["cache-control"] == "private, no-store"
    assert requester.get(
        f"/api/task-reviews/{review['id']}/artifacts/{artifact.id}"
    ).status_code == 404
    assert reviewer.get(
        f"/api/task-reviews/{review['id']}/artifacts/artifact_not_frozen"
    ).status_code == 404
    inbox = reviewer.get("/api/inbox").json()["items"]
    review_inbox = next(item for item in inbox if item["metadata"].get("review_id") == review["id"])
    assert review_inbox["allowed_actions"] == ["snooze", "open_task_review"]
    generic_resolution = reviewer.patch(
        f"/api/inbox/{review_inbox['id']}",
        json={"status": "resolved"},
    )
    assert generic_resolution.status_code == 409
    snoozed = reviewer.patch(
        f"/api/inbox/{review_inbox['id']}",
        json={"status": "snoozed", "ttl_minutes": 10},
    )
    assert snoozed.status_code == 200

    forbidden = requester.post(
        f"/api/task-reviews/{review['id']}/decisions",
        json={
            "command_id": "forbidden-review-decision",
            "expected_version": 1,
            "decision": "accepted",
        },
    )
    assert forbidden.status_code == 404

    accepted = reviewer.post(
        f"/api/task-reviews/{review['id']}/decisions",
        json={
            "command_id": "accept-review-delivery",
            "expected_version": 1,
            "decision": "accepted",
            "decision_note": "Meets the delivery requirements.",
        },
    )
    assert accepted.status_code == 200, accepted.text
    accepted_payload = accepted.json()
    assert accepted_payload["item"]["review"]["status"] == "accepted"
    assert accepted_payload["item"]["review"]["version"] == 2
    assert accepted_payload["item"]["allowed_actions"] == []
    assert accepted_payload["task"]["management"]["delivery_stage"] == "done"
    assert accepted_payload["task"]["management"]["version"] == review["task_version"] + 1

    detail = reviewer.get(f"/api/tasks/{task['task']['id']}").json()
    assert detail["item"]["management"]["delivery_stage"] == "done"
    assert detail["reviews"][0]["review"]["status"] == "accepted"
    assert detail["reviews_truncated"] is False
    assert not any(
        item["metadata"].get("review_id") == review["id"]
        for item in reviewer.get("/api/inbox").json()["items"]
    )
    audit = [event for event in store.audit_events if event.target_id == review["id"]]
    assert [event.action for event in audit] == ["submit_task_review", "decide_task_review"]
    assert all("decision_note" not in event.metadata for event in audit)

    decision_replay = reviewer.post(
        f"/api/task-reviews/{review['id']}/decisions",
        json={
            "command_id": "accept-review-delivery",
            "expected_version": 1,
            "decision": "accepted",
            "decision_note": "Meets the delivery requirements.",
        },
    )
    assert decision_replay.status_code == 200
    assert decision_replay.json()["item"]["review"]["id"] == review["id"]
    assert len([event for event in store.audit_events if event.target_id == review["id"]]) == 2


def test_changes_requested_returns_task_to_work_and_next_submission_increments_round(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    requester = authenticated_client()
    task, run, artifact = _create_reviewable_delivery(requester, "changes")
    first = _submit_review(requester, task, run, artifact, "changes")
    review = first["item"]["review"]
    reviewer = authenticated_client(TEAM_LEAD.id)

    missing_note = reviewer.post(
        f"/api/task-reviews/{review['id']}/decisions",
        json={
            "command_id": "changes-without-note",
            "expected_version": 1,
            "decision": "changes_requested",
        },
    )
    assert missing_note.status_code == 422

    changes = reviewer.post(
        f"/api/task-reviews/{review['id']}/decisions",
        json={
            "command_id": "request-review-changes",
            "expected_version": 1,
            "decision": "changes_requested",
            "decision_note": "Add the missing verification evidence.",
        },
    )
    assert changes.status_code == 200
    changed_task = changes.json()["task"]
    assert changes.json()["item"]["review"]["status"] == "changes_requested"
    assert changed_task["management"]["delivery_stage"] == "in_progress"

    second = requester.post(
        f"/api/tasks/{task['task']['id']}/reviews",
        json={
            "command_id": "submit-review-round-two",
            "expected_task_version": changed_task["management"]["version"],
            "run_id": run.id,
            "artifact_ids": [artifact.id],
        },
    )
    assert second.status_code == 201, second.text
    second_review = second.json()["item"]["review"]
    assert second_review["round"] == 2
    rejected = reviewer.post(
        f"/api/task-reviews/{second_review['id']}/decisions",
        json={
            "command_id": "reject-review-round-two",
            "expected_version": 1,
            "decision": "rejected",
            "decision_note": "The delivery does not satisfy the task.",
        },
    )
    assert rejected.status_code == 200
    assert rejected.json()["item"]["review"]["status"] == "rejected"
    assert rejected.json()["task"]["management"]["delivery_stage"] == "in_progress"
    assert len(store.list_task_reviews(task["task"]["id"])) == 2


def test_review_submission_rejects_unsealed_cross_run_and_nonterminal_artifacts(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    client = authenticated_client()
    task, run, artifact = _create_reviewable_delivery(client, "invalid")
    owner_detail = client.get(f"/api/tasks/{task['task']['id']}").json()
    assert "submit_review" in owner_detail["item"]["allowed_actions"]
    assert owner_detail["runs"][0]["can_submit_review"] is True
    lead_client = authenticated_client(TEAM_LEAD.id)
    lead_detail = lead_client.get(f"/api/tasks/{task['task']['id']}").json()
    assert "submit_review" not in lead_detail["item"]["allowed_actions"]
    assert lead_detail["runs"][0]["can_submit_review"] is False
    non_owner = lead_client.post(
        f"/api/tasks/{task['task']['id']}/reviews",
        json={
            "command_id": "submit-someone-elses-artifact",
            "expected_task_version": task["management"]["version"],
            "run_id": run.id,
            "artifact_ids": [artifact.id],
        },
    )
    assert non_owner.status_code == 403
    assert non_owner.json() == {"detail": "task_review_submitter_not_run_owner"}
    unsealed = Artifact(
        id="artifact_review_unsealed",
        run_id=run.id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        user_id=run.user_id,
        artifact_type="task_output",
        content_type="text/plain",
        content="mutable output",
    )
    store.save_artifact(unsealed)

    invalid = client.post(
        f"/api/tasks/{task['task']['id']}/reviews",
        json={
            "command_id": "submit-unsealed-review",
            "expected_task_version": task["management"]["version"],
            "run_id": run.id,
            "artifact_ids": [unsealed.id],
        },
    )
    assert invalid.status_code == 409
    assert invalid.json() == {"detail": "task_review_artifact_not_reviewable"}

    other_task, other_run, other_artifact = _create_reviewable_delivery(client, "other")
    cross_run = client.post(
        f"/api/tasks/{task['task']['id']}/reviews",
        json={
            "command_id": "submit-cross-run-review",
            "expected_task_version": task["management"]["version"],
            "run_id": run.id,
            "artifact_ids": [other_artifact.id],
        },
    )
    assert cross_run.status_code == 404
    assert cross_run.json() == {"detail": "task_review_artifact_not_found"}

    running = store.get_agent_run(other_run.id)
    assert running is not None
    store.save_agent_run(running.model_copy(update={"status": AgentRunStatus.RUNNING}))
    nonterminal = client.post(
        f"/api/tasks/{other_task['task']['id']}/reviews",
        json={
            "command_id": "submit-running-review",
            "expected_task_version": other_task["management"]["version"],
            "run_id": other_run.id,
            "artifact_ids": [other_artifact.id],
        },
    )
    assert nonterminal.status_code == 409
    assert nonterminal.json() == {"detail": "task_review_run_not_complete"}
    assert store.list_task_reviews(task["task"]["id"]) == []
    assert store.list_task_reviews(other_task["task"]["id"]) == []


def test_review_decision_fails_closed_when_frozen_artifact_or_task_changes(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    requester = authenticated_client()
    task, run, artifact = _create_reviewable_delivery(requester, "integrity")
    submitted = _submit_review(requester, task, run, artifact, "integrity")
    review = submitted["item"]["review"]
    reviewer = authenticated_client(TEAM_LEAD.id)

    with store._connect() as connection:
        connection.execute(
            "UPDATE artifacts SET content_hash = ? WHERE id = ?",
            ("0" * 64, artifact.id),
        )
    response = reviewer.post(
        f"/api/task-reviews/{review['id']}/decisions",
        json={
            "command_id": "accept-corrupt-artifact",
            "expected_version": 1,
            "decision": "accepted",
        },
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "task_review_artifact_integrity_failed"}
    persisted = store.get_task_review(review["id"])
    assert persisted is not None and persisted.status.value == "pending"
    persisted_task = store.get_task(task["task"]["id"])
    assert persisted_task is not None
    assert persisted_task.management is not None
    assert persisted_task.management.delivery_stage.value == "review"
    inbox = next(item for item in store.inbox_items if item.metadata.get("review_id") == review["id"])
    assert inbox.status == "open"


def test_stale_inbox_snooze_cannot_reopen_a_decided_review(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    requester = authenticated_client()
    task, run, artifact = _create_reviewable_delivery(requester, "inbox-race")
    submitted = _submit_review(requester, task, run, artifact, "inbox-race")
    review = submitted["item"]["review"]
    reviewer_for_patch = authenticated_client(TEAM_LEAD.id)
    reviewer_for_decision = authenticated_client(TEAM_LEAD.id)
    inbox = next(item for item in store.inbox_items if item.metadata.get("review_id") == review["id"])
    entered = Event()
    release = Event()
    original_update = store.update_task_review_inbox

    def blocked_update(**kwargs):  # noqa: ANN003, ANN202
        entered.set()
        assert release.wait(timeout=5)
        return original_update(**kwargs)

    monkeypatch.setattr(store, "update_task_review_inbox", blocked_update)
    with ThreadPoolExecutor(max_workers=2) as executor:
        snooze = executor.submit(
            reviewer_for_patch.patch,
            f"/api/inbox/{inbox.id}",
            json={"status": "snoozed", "ttl_minutes": 10},
        )
        assert entered.wait(timeout=5)
        decision = reviewer_for_decision.post(
            f"/api/task-reviews/{review['id']}/decisions",
            json={
                "command_id": "accept-before-stale-snooze",
                "expected_version": 1,
                "decision": "accepted",
            },
        )
        release.set()
        snooze_response = snooze.result(timeout=5)

    assert decision.status_code == 200
    assert snooze_response.status_code == 409
    assert snooze_response.json() == {"detail": "task_review_inbox_resolved"}
    persisted_inbox = store.get_inbox_item(inbox.id)
    assert persisted_inbox is not None and persisted_inbox.status == "resolved"


def test_review_submission_wins_handoff_race_without_partial_handoff(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    handoff_client = authenticated_client()
    review_client = authenticated_client()
    task, run, artifact = _create_reviewable_delivery(review_client, "handoff-race")
    parent = store.add_blackboard_post(
        BlackboardPost(
            id="bb_review_handoff_race",
            task_id=task["task"]["id"],
            post_type=BlackboardPostType.REQUEST,
            actor=USER.personal_agent_id,
            title="Race handoff against review",
            content="No partial handoff may survive",
            scope=Scope.PROJECT,
            permission="project_visible",
            current_owner_agent_id=USER.personal_agent_id,
            current_owner_label="Owner",
            done_when="Original criterion",
        )
    )
    entered = Event()
    release = Event()
    original_commit = store.commit_blackboard_handoff

    def blocked_commit(**kwargs):  # noqa: ANN003, ANN202
        entered.set()
        assert release.wait(timeout=5)
        return original_commit(**kwargs)

    monkeypatch.setattr(store, "commit_blackboard_handoff", blocked_commit)
    before_post_ids = {post.id for post in store.blackboard_posts}
    with ThreadPoolExecutor(max_workers=2) as executor:
        handoff_future = executor.submit(
            handoff_client.post,
            f"/api/blackboard/posts/{parent.id}/handoff",
            json={
                "goal": "Race owner change",
                "current_result": "Review is starting",
                "done_when": "Changed criterion",
                "next_owner_agent_id": TEAM_LEAD.personal_agent_id,
                "blockers": [],
                "requires_input_from": [],
            },
        )
        assert entered.wait(timeout=5)
        submitted = review_client.post(
            f"/api/tasks/{task['task']['id']}/reviews",
            json={
                "command_id": "submit-review-before-handoff-commit",
                "expected_task_version": task["management"]["version"],
                "run_id": run.id,
                "artifact_ids": [artifact.id],
            },
        )
        release.set()
        handoff_response = handoff_future.result(timeout=5)

    assert submitted.status_code == 201
    assert handoff_response.status_code == 409
    assert handoff_response.json() == {"detail": "task_review_pending"}
    assert {post.id for post in store.blackboard_posts} == before_post_ids
    persisted_task = store.get_task(task["task"]["id"])
    assert persisted_task is not None
    assert persisted_task.done_when == task["task"]["done_when"]
    assert persisted_task.steps == task["task"]["steps"]
    assert not any(
        event.action == "create_handoff" and event.target_id not in before_post_ids
        for event in store.audit_events
    )


def test_private_review_inbox_is_hidden_from_unassigned_admins_across_workspaces(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    requester = authenticated_client()
    task, run, artifact = _create_reviewable_delivery(requester, "inbox-privacy")
    submitted = _submit_review(requester, task, run, artifact, "inbox-privacy")
    review_id = submitted["item"]["review"]["id"]
    inbox = next(item for item in store.inbox_items if item.metadata.get("review_id") == review_id)

    same_workspace_admin = authenticated_client(ADMIN.id)
    assert inbox.id not in {
        item["id"] for item in same_workspace_admin.get("/api/inbox?include_snoozed=true").json()["items"]
    }
    assert same_workspace_admin.patch(
        f"/api/inbox/{inbox.id}",
        json={"status": "snoozed", "ttl_minutes": 10},
    ).status_code == 404
    assert same_workspace_admin.get(
        f"/api/task-reviews/{review_id}/artifacts/{artifact.id}"
    ).status_code == 404

    other_workspace = store.save_workspace(
        Workspace(id="workspace_review_isolated", name="Isolated", description="Review isolation")
    )
    other_project = store.save_project(
        Project(
            id="project_review_isolated",
            workspace_id=other_workspace.id,
            name="Isolated review project",
            goal="Verify Inbox isolation",
            member_ids=["usr_review_isolated_admin"],
        )
    )
    other_admin = store.save_user(
        User(
            id="usr_review_isolated_admin",
            workspace_id=other_workspace.id,
            default_project_id=other_project.id,
            name="Isolated admin",
            role="admin",
            personal_agent_id="agent_review_isolated_admin",
        )
    )
    _, token = issue_session(store, other_admin)
    isolated_client = TestClient(app)
    isolated_client.cookies.set(SESSION_COOKIE_NAME, token)
    assert inbox.id not in {
        item["id"] for item in isolated_client.get("/api/inbox?include_snoozed=true").json()["items"]
    }
    assert isolated_client.patch(
        f"/api/inbox/{inbox.id}",
        json={"status": "snoozed", "ttl_minutes": 10},
    ).status_code == 404
    assert isolated_client.get(
        f"/api/task-reviews/{review_id}/artifacts/{artifact.id}"
    ).status_code == 404


def test_task_review_projection_corruption_fails_task_detail(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    client = authenticated_client()
    task, run, artifact = _create_reviewable_delivery(client, "projection")
    submitted = _submit_review(client, task, run, artifact, "projection")
    review_id = submitted["item"]["review"]["id"]
    with store._connect() as connection:
        connection.execute(
            "UPDATE task_reviews SET task_id = ? WHERE id = ?",
            ("task_corrupt_projection", review_id),
        )

    response = client.get(f"/api/tasks/{task['task']['id']}")

    assert response.status_code == 409
    assert response.json() == {"detail": "task_review_integrity_failed"}


def test_task_detail_bounds_review_history(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    client = authenticated_client()
    task, run, artifact = _create_reviewable_delivery(client, "review-truncation")
    decided_at = now_utc()
    with store._connect() as connection:
        for round_number in range(1, 52):
            review = TaskReviewV1(
                id=f"task_review_history_{round_number:02d}",
                task_id=task["task"]["id"],
                run_id=run.id,
                artifact_ids=[artifact.id],
                artifact_hashes=[artifact.content_hash],
                round=round_number,
                status=TaskReviewStatus.REJECTED,
                requested_by=USER.id,
                reviewer_id=TEAM_LEAD.id,
                task_version=task["management"]["version"],
                decision_note="Historical rejection",
                version=2,
                created_at=decided_at,
                updated_at=decided_at,
                decided_at=decided_at,
            )
            connection.execute(
                """
                INSERT INTO task_reviews(
                    id, task_id, run_id, reviewer_id, status, round, version,
                    payload, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review.id,
                    review.task_id,
                    review.run_id,
                    review.reviewer_id,
                    review.status.value,
                    review.round,
                    review.version,
                    review.model_dump_json(),
                    review.created_at.isoformat(),
                    review.updated_at.isoformat(),
                ),
            )

    detail = client.get(f"/api/tasks/{task['task']['id']}")

    assert detail.status_code == 200
    assert detail.json()["reviews_truncated"] is True
    assert len(detail.json()["reviews"]) == 50
    assert [item["review"]["round"] for item in detail.json()["reviews"][:2]] == [51, 50]


def test_review_command_conflicts_and_versions_do_not_duplicate_side_effects(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    client = authenticated_client()
    task, run, artifact = _create_reviewable_delivery(client, "commands")
    submitted = _submit_review(client, task, run, artifact, "commands")
    review = submitted["item"]["review"]

    conflict = client.post(
        f"/api/tasks/{task['task']['id']}/reviews",
        json={
            "command_id": "submit-review-commands",
            "expected_task_version": task["management"]["version"],
            "run_id": "run_conflicting_identity",
            "artifact_ids": [artifact.id],
        },
    )
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "task_review_command_conflict"}

    reviewer = authenticated_client(TEAM_LEAD.id)
    stale = reviewer.post(
        f"/api/task-reviews/{review['id']}/decisions",
        json={
            "command_id": "stale-review-version",
            "expected_version": 2,
            "decision": "accepted",
        },
    )
    assert stale.status_code == 409
    assert stale.json() == {"detail": "task_review_version_conflict"}
    assert len(store.list_task_reviews(task["task"]["id"])) == 1
    assert len([item for item in store.inbox_items if item.metadata.get("review_id") == review["id"]]) == 1
