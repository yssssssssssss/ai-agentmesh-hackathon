from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentmesh.artifacts import UniversalSynthesisEnvelopeV1, V1VerifiedArtifactStore
from agentmesh.canonical_json import canonical_json_bytes, canonical_json_sha256
from agentmesh.memory_governance.contracts import TaskReviewMemoryCaptureRequest
from agentmesh.memory_governance.service import MemoryGovernanceService
from agentmesh.models import (
    AgentPlanningContractVersion,
    AgentRun,
    AgentRunStatus,
    Artifact,
    ArtifactVerificationState,
    ChatThread,
    ChatThreadKind,
    Intent,
    Project,
    SkillSynthesisResult,
    Task,
    TaskDeliveryStage,
    TaskManagementMetadataV1,
    User,
    UserRole,
    Workspace,
    now_utc,
)
from agentmesh.routes import task_operations
from agentmesh.routes.deps import current_user
from agentmesh.store import SQLiteStore
from agentmesh.task_management.contracts import TaskCreateRequest, TaskTransitionRequest
from agentmesh.task_management.service import TaskManagementService
from agentmesh.task_review.contracts import TaskReviewDecisionRequest, TaskReviewSubmitRequest
from agentmesh.task_review.service import TaskCompletionService


@pytest.fixture
def inspection_project(monkeypatch, tmp_path):
    repository = SQLiteStore(tmp_path / "inspections.sqlite3")
    workspace = repository.save_workspace(Workspace(id="ws_inspections", name="Pilot", description="Pilot"))
    user = repository.save_user(
        User(
            id="user_inspections",
            workspace_id=workspace.id,
            default_project_id="project_inspections",
            name="Owner",
            role=UserRole.TEAM_LEAD,
            personal_agent_id="agent_inspections",
        )
    )
    project = repository.save_project(
        Project(
            id=user.default_project_id,
            workspace_id=workspace.id,
            name="Pilot",
            goal="Deliver",
            member_ids=[user.id],
        )
    )
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    monkeypatch.setattr(task_operations, "store", repository)
    app = FastAPI()
    app.include_router(task_operations.router)
    app.dependency_overrides[current_user] = lambda: user
    yield repository, user, project, TestClient(app)
    repository.close()


def test_manual_blocker_inspection_reads_real_tasks_without_write_gate(inspection_project, monkeypatch):
    repository, user, project, client = inspection_project
    service = TaskManagementService(repository)
    dependency = service.create_task(
        TaskCreateRequest(
            command_id="create-dependency",
            title="Missing design",
            due_at=now_utc() - timedelta(days=1),
        ),
        user,
    )
    dependent = service.create_task(
        TaskCreateRequest(
            command_id="create-dependent",
            title="Integration",
            dependency_task_ids=[dependency.task.id],
        ),
        user,
    )
    blocked = service.transition_task(
        dependency.task.id,
        TaskTransitionRequest(
            command_id="block-design",
            expected_version=dependency.management.version,
            action="block",
            reason="Waiting for source material",
        ),
        user,
    )
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "off")
    monkeypatch.setenv("AGENTMESH_DEMO_MODE", "0")

    response = client.post(f"/api/task-operations/{project.id}/inspections", json={"template_id": "blockers"})

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["data_mode"] == "real"
    assert report["outcome"] == "completed"
    assert report["actual_providers"] == ["local_task_store"]
    findings = {finding["task_id"]: finding for finding in report["blockers"]}
    assert set(findings[dependency.task.id]["reasons"]) == {"blocked", "overdue"}
    assert findings[dependency.task.id]["blocked_reason"] == "Waiting for source material"
    assert findings[dependent.task.id]["blocking_task_ids"] == [dependency.task.id]
    assert findings[dependent.task.id]["navigation_href"].endswith(dependent.task.id)
    assert report["source_watermarks"]["tasks"]["record_count"] == 2
    assert report["evidence_refs"]
    assert repository.get_task(dependency.task.id) == blocked.task


def test_daily_progress_uses_command_history_for_completed_then_reopened(inspection_project):
    repository, user, project, client = inspection_project
    since = now_utc() - timedelta(minutes=1)
    service = TaskManagementService(repository)
    task = service.create_task(TaskCreateRequest(command_id="create-progress", title="Delivery"), user)
    for action in ("plan", "start", "submit_review", "complete", "reopen"):
        task = service.transition_task(
            task.task.id,
            TaskTransitionRequest(
                command_id=f"progress-{action}",
                expected_version=task.management.version,
                action=action,
            ),
            user,
        )

    response = client.post(
        f"/api/task-operations/{project.id}/inspections",
        json={
            "template_id": "daily_progress",
            "since": since.isoformat(),
        },
    )

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["outcome"] == "completed"
    changes = [item for item in report["changes"] if item["task_id"] == task.task.id]
    assert [item["kind"] for item in changes] == [
        "created",
        "updated",
        "updated",
        "pending_review",
        "completed",
        "reopened",
    ]
    assert [item["version"] for item in changes] == [1, 2, 3, 4, 5, 6]
    assert all(item["evidence_refs"][0]["source_kind"] == "task_command" for item in changes)
    after_changes = client.post(
        f"/api/task-operations/{project.id}/inspections",
        json={
            "template_id": "daily_progress",
            "since": report["snapshot_at"],
        },
    ).json()
    assert after_changes["outcome"] == "no_change"
    assert after_changes["changes"] == []


def _reviewable_delivery(repository, user, suffix):
    service = TaskManagementService(repository)
    task = service.create_task(TaskCreateRequest(command_id=f"create-{suffix}", title=f"Delivery {suffix}"), user)
    for action in ("plan", "start"):
        task = service.transition_task(
            task.task.id,
            TaskTransitionRequest(
                command_id=f"{suffix}-{action}",
                expected_version=task.management.version,
                action=action,
            ),
            user,
        )
    run, _ = repository.claim_new_agent_run(
        AgentRun(
            id=f"run-{suffix}",
            thread_id=task.task.thread_id,
            task_id=task.task.id,
            user_id=user.id,
            workspace_id=user.workspace_id,
            project_id=user.default_project_id,
            input_text="Deliver",
            client_turn_id=f"run-{suffix}",
            status=AgentRunStatus.COMPLETED,
            planning_contract_version=AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1,
        )
    )
    envelope = UniversalSynthesisEnvelopeV1(
        run_id=run.id,
        requirement_version_id=f"requirement-{suffix}",
        plan_id=f"plan-{suffix}",
        plan_version=1,
        synthesis=SkillSynthesisResult(summary="Verified delivery"),
    )
    content = canonical_json_bytes(envelope.model_dump(mode="json")).decode()
    artifact = Artifact(
        id=f"artifact-{suffix}",
        run_id=run.id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        user_id=user.id,
        artifact_type="universal_synthesis",
        content_type="application/json",
        content=content,
        verification_state=ArtifactVerificationState.SEALED,
        schema_version="universal-synthesis-v1",
        content_hash=canonical_json_sha256(envelope.model_dump(mode="json")),
        size_bytes=len(content.encode()),
        requirement_version_id=envelope.requirement_version_id,
        plan_version_id=f"{envelope.plan_id}:v1",
    )
    V1VerifiedArtifactStore(repository).insert_sealed(artifact)
    return TaskCompletionService(repository).submit_review(
        task.task.id,
        TaskReviewSubmitRequest(
            command_id=f"review-{suffix}",
            expected_task_version=task.management.version,
            run_id=run.id,
            artifact_ids=[artifact.id],
        ),
        user,
    )


def test_pending_inspection_includes_real_task_and_assigned_memory_reviews(inspection_project):
    repository, user, project, client = inspection_project
    reviewer = repository.save_user(
        user.model_copy(
            update={
                "id": "user_reviewer",
                "name": "Reviewer",
                "personal_agent_id": "agent_reviewer",
            }
        )
    )
    user = repository.save_user(user.model_copy(update={"role": UserRole.USER}))
    repository.save_project(project.model_copy(update={"member_ids": [user.id, reviewer.id]}))
    completed_delivery = _reviewable_delivery(repository, user, "memory")
    TaskCompletionService(repository).decide_review(
        completed_delivery.item.review.id,
        TaskReviewDecisionRequest(
            command_id="accept-memory-delivery",
            expected_version=1,
            decision="accepted",
        ),
        reviewer,
    )
    candidate = MemoryGovernanceService(repository).capture_from_task_review(
        completed_delivery.item.review.id,
        TaskReviewMemoryCaptureRequest(
            command_id="capture-inspection-memory",
            target="team_candidate",
            title="Team experience",
            summary="Use the verified procedure.",
        ),
        user,
    )
    pending = _reviewable_delivery(repository, user, "pending")
    client.app.dependency_overrides[current_user] = lambda: reviewer

    response = client.post(f"/api/task-operations/{project.id}/inspections", json={"template_id": "pending_reviews"})

    assert response.status_code == 200, response.text
    report = response.json()
    reviews = {item["kind"]: item for item in report["pending_reviews"]}
    assert report["outcome"] == "completed"
    assert reviews["task_review"]["review_id"] == pending.item.review.id
    assert reviews["memory_review"]["review_id"] == candidate.memory_review.review.id
    assert all(item["assigned_to_me"] for item in reviews.values())
    assert reviews["memory_review"]["navigation_href"].startswith("/knowledge?tab=pending")
    assert report["source_watermarks"]["task_reviews"]["record_count"] == 2
    assert report["source_watermarks"]["memory_reviews"]["record_count"] == 1
    client.app.dependency_overrides[current_user] = lambda: user
    owner_report = client.post(
        f"/api/task-operations/{project.id}/inspections", json={"template_id": "pending_reviews"}
    ).json()
    assert [item["kind"] for item in owner_report["pending_reviews"]] == ["task_review"]
    assert not owner_report["pending_reviews"][0]["assigned_to_me"]
    repository.save_user(reviewer.model_copy(update={"role": UserRole.USER}))
    client.app.dependency_overrides[current_user] = lambda: reviewer
    revoked = client.post(
        f"/api/task-operations/{project.id}/inspections", json={"template_id": "pending_reviews"}
    ).json()
    assert all(item["kind"] != "memory_review" for item in revoked["pending_reviews"])
    progress = client.post(
        f"/api/task-operations/{project.id}/inspections", json={"template_id": "daily_progress"}
    ).json()
    completed = [item for item in progress["changes"] if item["kind"] == "completed"]
    assert completed[0]["evidence_refs"][0]["source_kind"] == "task_review_command"


@pytest.mark.parametrize("template", ["daily_progress", "blockers", "pending_reviews"])
def test_empty_project_has_insufficient_evidence(inspection_project, template):
    _, _, project, client = inspection_project
    response = client.post(f"/api/task-operations/{project.id}/inspections", json={"template_id": template})
    assert response.status_code == 200
    assert response.json()["outcome"] == "insufficient_evidence"
    assert response.json()["missing_data"] == ["no_shared_project_tasks"]


def test_inspection_hides_private_chat_and_rechecks_current_membership(inspection_project):
    repository, user, project, client = inspection_project
    public = TaskManagementService(repository).create_task(
        TaskCreateRequest(
            command_id="create-public",
            title="Public task",
        ),
        user,
    )
    private = repository.save_chat_thread(
        ChatThread(
            id="private-thread",
            workspace_id=user.workspace_id,
            project_id=project.id,
            user_id=user.id,
            title="Private chat",
            kind=ChatThreadKind.CONVERSATION,
        )
    )
    repository.save_task(
        Task(
            id="private-task",
            thread_id=private.id,
            intent=Intent.GENERAL_CHAT,
            title="Secret plan",
            management=TaskManagementMetadataV1(
                created_by=user.id,
                updated_by=user.id,
                blocked_reason="Secret blocker",
            ),
        )
    )
    response = client.post(f"/api/task-operations/{project.id}/inspections", json={"template_id": "daily_progress"})
    assert response.status_code == 200
    assert response.json()["source_watermarks"]["tasks"]["record_count"] == 1
    assert "Secret" not in response.text
    assert response.json()["changes"][0]["task_id"] == public.task.id
    repository.save_project(project.model_copy(update={"member_ids": ["another-member"]}))
    denied = client.post(f"/api/task-operations/{project.id}/inspections", json={"template_id": "blockers"})
    assert denied.status_code == 404
    assert "Secret" not in denied.text


def test_inspection_cannot_use_another_workspace_or_inactive_actor(inspection_project):
    repository, user, project, client = inspection_project
    foreign = repository.save_project(project.model_copy(update={"id": "foreign", "workspace_id": "another"}))
    assert (
        client.post(f"/api/task-operations/{foreign.id}/inspections", json={"template_id": "blockers"}).status_code
        == 404
    )
    repository.save_user(user.model_copy(update={"status": "disabled"}))
    assert (
        client.post(f"/api/task-operations/{project.id}/inspections", json={"template_id": "blockers"}).status_code
        == 404
    )


@pytest.mark.parametrize("since", ["2030-01-01T00:00:00", "2030-01-01T00:00:00Z", "2020-01-01T00:00:00Z"])
def test_inspection_rejects_naive_future_and_unbounded_windows(inspection_project, since):
    _, _, project, client = inspection_project
    response = client.post(
        f"/api/task-operations/{project.id}/inspections", json={"template_id": "daily_progress", "since": since}
    )
    assert response.status_code == 422


def test_daily_progress_reports_missing_history_instead_of_inventing_completion(inspection_project):
    repository, user, project, client = inspection_project
    thread = repository.save_chat_thread(
        ChatThread(
            id="imported-task-thread",
            workspace_id=user.workspace_id,
            project_id=project.id,
            user_id=user.id,
            title="Imported task",
            kind=ChatThreadKind.TASK,
        )
    )
    repository.save_task(
        Task(
            id="imported-task",
            thread_id=thread.id,
            intent=Intent.GENERAL_CHAT,
            title="Imported delivery",
            management=TaskManagementMetadataV1(
                created_by=user.id,
                updated_by=user.id,
                delivery_stage=TaskDeliveryStage.DONE,
            ),
        )
    )
    report = client.post(
        f"/api/task-operations/{project.id}/inspections", json={"template_id": "daily_progress"}
    ).json()
    assert report["outcome"] == "insufficient_evidence"
    assert report["changes"] == []
    assert report["missing_data"] == ["task_history_incomplete"]


def test_reopening_uses_the_last_version_before_the_inspection_window(inspection_project):
    repository, user, project, client = inspection_project
    service = TaskManagementService(repository)
    task = service.create_task(TaskCreateRequest(command_id="create-old-completion", title="Delivery"), user)
    for action in ("plan", "start", "submit_review", "complete"):
        task = service.transition_task(
            task.task.id,
            TaskTransitionRequest(
                command_id=f"old-completion-{action}",
                expected_version=task.management.version,
                action=action,
            ),
            user,
        )
    since = now_utc()
    service.transition_task(
        task.task.id,
        TaskTransitionRequest(
            command_id="reopen-old-completion",
            expected_version=task.management.version,
            action="reopen",
        ),
        user,
    )
    report = client.post(
        f"/api/task-operations/{project.id}/inspections",
        json={"template_id": "daily_progress", "since": since.isoformat()},
    ).json()
    assert [(item["kind"], item["version"]) for item in report["changes"]] == [("reopened", 6)]


def test_daily_progress_does_not_mark_an_existing_blocker_as_a_new_change(inspection_project):
    _, user, project, client = inspection_project
    service = TaskManagementService(inspection_project[0])
    task = service.create_task(TaskCreateRequest(command_id="create-old-blocker", title="Existing blocker"), user)
    service.transition_task(
        task.task.id,
        TaskTransitionRequest(
            command_id="old-blocker",
            expected_version=task.management.version,
            action="block",
            reason="Waiting",
        ),
        user,
    )
    since = now_utc()
    report = client.post(
        f"/api/task-operations/{project.id}/inspections",
        json={"template_id": "daily_progress", "since": since.isoformat()},
    ).json()
    assert report["outcome"] == "no_change"
    assert report["changes"] == []
    assert len(report["blockers"]) == 1
