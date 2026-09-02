from __future__ import annotations

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agentmesh.artifacts import UniversalSynthesisEnvelopeV1, V1VerifiedArtifactStore
from agentmesh.canonical_json import canonical_json_bytes
from agentmesh.models import (
    Agent,
    AgentPlanningContractVersion,
    AgentRun,
    AgentRunStatus,
    Artifact,
    ArtifactVerificationState,
    AuditEvent,
    ChatThread,
    ChatThreadKind,
    CollaborationStage,
    Intent,
    Project,
    SkillOrchestrationRequestMode,
    SkillSynthesisResult,
    Task,
    TaskManagementMetadataV1,
    TaskStatus,
    User,
    Workspace,
    now_utc,
)
from agentmesh.store import SQLiteStore, TaskCommandConflict
from agentmesh.task_management.contracts import (
    TaskCommandAuthorizationV1,
    TaskCommandReceiptV1,
    TaskCreateRequest,
    TaskTransitionRequest,
    TaskUpdateRequest,
)
from agentmesh.task_management.service import TaskManagementError, TaskManagementService
from agentmesh.task_review.contracts import TaskReviewDecisionRequest, TaskReviewSubmitRequest
from agentmesh.task_review.service import TaskCompletionService


def test_concurrent_task_create_replays_one_durable_command(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    repository = SQLiteStore(tmp_path / "concurrent-task.sqlite3")
    workspace = repository.save_workspace(Workspace(name="Concurrent", description="Command replay"))
    project = repository.save_project(
        Project(workspace_id=workspace.id, name="Concurrent project", goal="Create one task")
    )
    user = repository.save_user(
        User(
            workspace_id=workspace.id,
            default_project_id=project.id,
            name="Concurrent owner",
            role="user",
            personal_agent_id="agent_concurrent_owner",
        )
    )
    project.member_ids = [user.id]
    repository.save_project(project)
    request = TaskCreateRequest(command_id="concurrent-create", title="Create exactly once")

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(lambda _index: TaskManagementService(repository).create_task(request, user), range(10)))

    assert len({result.task.id for result in results}) == 1
    assert len({result.task.thread_id for result in results}) == 1
    assert len(repository.tasks) == 1
    assert len(repository.chat_threads) == 1
    assert len([event for event in repository.audit_events if event.action == "create_project_task"]) == 1
    repository.close()


def test_concurrent_task_updates_allow_one_expected_version(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    repository = SQLiteStore(tmp_path / "concurrent-update.sqlite3")
    workspace = repository.save_workspace(Workspace(name="Update", description="CAS update"))
    project = repository.save_project(Project(workspace_id=workspace.id, name="Update project", goal="CAS"))
    user = repository.save_user(
        User(
            workspace_id=workspace.id,
            default_project_id=project.id,
            name="Update owner",
            role="user",
            personal_agent_id="agent_update_owner",
        )
    )
    project.member_ids = [user.id]
    repository.save_project(project)
    service = TaskManagementService(repository)
    task_id = service.create_task(
        TaskCreateRequest(command_id="update-create", title="Concurrent update"),
        user,
    ).task.id
    requests = [
        TaskUpdateRequest(
            command_id=f"concurrent-update-{index}",
            expected_version=1,
            description=f"Update {index}",
        )
        for index in range(2)
    ]

    def update(request: TaskUpdateRequest) -> str:
        try:
            service.update_task(task_id, request, user)
            return "updated"
        except TaskManagementError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(update, requests))

    assert sorted(outcomes) == ["task_version_conflict", "updated"]
    persisted = repository.get_task(task_id)
    assert persisted is not None
    assert persisted.management is not None
    assert persisted.management.version == 2
    repository.close()


def test_management_and_execution_writers_preserve_each_others_fields(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    repository = SQLiteStore(tmp_path / "interleaved-task.sqlite3")
    workspace = repository.save_workspace(Workspace(name="Interleave", description="CAS regression"))
    project = repository.save_project(
        Project(workspace_id=workspace.id, name="Interleave project", goal="Preserve task fields")
    )
    user = repository.save_user(
        User(
            workspace_id=workspace.id,
            default_project_id=project.id,
            name="Task owner",
            role="user",
            personal_agent_id="agent_interleave_owner",
        )
    )
    project.member_ids = [user.id]
    repository.save_project(project)
    service = TaskManagementService(repository)
    created = service.create_task(TaskCreateRequest(command_id="interleave-create", title="Original title"), user)
    stale_management = created.task.model_copy(deep=True)
    stale_legacy = created.task.model_copy(deep=True)

    execution_update = repository.get_task(created.task.id)
    assert execution_update is not None
    execution_update.status = TaskStatus.RUNNING
    execution_update.collaboration_stage = CollaborationStage.EXECUTION
    repository.save_task(execution_update)

    assert stale_management.management is not None
    stale_management.title = "Managed title"
    stale_management.management.version = 2
    stale_management.management.description = "Management update"
    stale_management.updated_at = now_utc()
    receipt = TaskCommandReceiptV1(
        id="task_command_interleave_update",
        command_id="interleave-update",
        user_id=user.id,
        operation="update",
        request_hash="a" * 64,
        task_id=stale_management.id,
        result_task=stale_management,
    )
    repository.save_managed_task_command(
        task=stale_management,
        expected_version=1,
        audit=AuditEvent(
            actor=user.id,
            action="update_project_task",
            target_type="task",
            target_id=stale_management.id,
            workspace_id=workspace.id,
            project_id=project.id,
        ),
        receipt=receipt,
        authorization=TaskCommandAuthorizationV1(
            actor_id=user.id,
            workspace_id=workspace.id,
            project_id=project.id,
        ),
    )
    after_management = repository.get_task(created.task.id)
    assert after_management is not None
    assert after_management.status == TaskStatus.RUNNING
    assert after_management.collaboration_stage == CollaborationStage.EXECUTION
    assert after_management.title == "Managed title"
    assert after_management.management is not None
    assert after_management.management.version == 2

    stale_legacy.status = TaskStatus.COMPLETED
    stale_legacy.collaboration_stage = CollaborationStage.COMPLETED
    repository.save_task(stale_legacy)
    after_legacy = repository.get_task(created.task.id)
    assert after_legacy is not None
    assert after_legacy.status == TaskStatus.COMPLETED
    assert after_legacy.collaboration_stage == CollaborationStage.COMPLETED
    assert after_legacy.title == "Managed title"
    assert after_legacy.management is not None
    assert after_legacy.management.version == 2
    repository.close()


def test_transaction_rechecks_assignee_eligibility_before_task_commit(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    repository = SQLiteStore(tmp_path / "task-assignee-race.sqlite3")
    workspace = repository.save_workspace(Workspace(name="Assignee", description="Eligibility race"))
    project = repository.save_project(Project(workspace_id=workspace.id, name="Assignee project", goal="Recheck target"))
    manager = repository.save_user(
        User(
            workspace_id=workspace.id,
            default_project_id=project.id,
            name="Task manager",
            role="team_lead",
            personal_agent_id="agent_task_manager",
        )
    )
    assignee = repository.save_user(
        User(
            workspace_id=workspace.id,
            default_project_id=project.id,
            name="Task assignee",
            role="user",
            personal_agent_id="agent_task_assignee",
        )
    )
    project.member_ids = [manager.id, assignee.id]
    repository.save_project(project)
    created = TaskManagementService(repository).create_task(
        TaskCreateRequest(command_id="assignee-create", title="Assignee race"),
        manager,
    )
    stale = created.task.model_copy(deep=True)
    assert stale.management is not None
    stale.management.version = 2
    stale.management.assignee_kind = "user"
    stale.management.assignee_id = assignee.id
    assignee.status = "disabled"
    repository.save_user(assignee)

    with pytest.raises(TaskCommandConflict, match="task_assignee_not_found"):
        repository.save_managed_task_command(
            task=stale,
            expected_version=1,
            audit=AuditEvent(
                actor=manager.id,
                action="update_project_task",
                target_type="task",
                target_id=stale.id,
                workspace_id=workspace.id,
                project_id=project.id,
            ),
            receipt=TaskCommandReceiptV1(
                id="task_command_assignee_revoked",
                command_id="assignee-revoked",
                user_id=manager.id,
                operation="update",
                request_hash="d" * 64,
                task_id=stale.id,
                result_task=stale,
            ),
            authorization=TaskCommandAuthorizationV1(
                actor_id=manager.id,
                workspace_id=workspace.id,
                project_id=project.id,
                validate_assignee=True,
                assignee_kind="user",
                assignee_id=assignee.id,
            ),
        )
    persisted = repository.get_task(stale.id)
    assert persisted is not None
    assert persisted.management is not None
    assert persisted.management.version == 1
    assert persisted.management.assignee_id is None
    repository.close()


def test_transaction_rechecks_membership_before_task_commit(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    repository = SQLiteStore(tmp_path / "task-membership-race.sqlite3")
    workspace = repository.save_workspace(Workspace(name="Membership", description="Authorization race"))
    project = repository.save_project(
        Project(workspace_id=workspace.id, name="Membership project", goal="Recheck membership")
    )
    user = repository.save_user(
        User(
            workspace_id=workspace.id,
            default_project_id=project.id,
            name="Former member",
            role="user",
            personal_agent_id="agent_former_member",
        )
    )
    project.member_ids = [user.id]
    repository.save_project(project)
    created = TaskManagementService(repository).create_task(
        TaskCreateRequest(command_id="membership-create", title="Membership task"),
        user,
    )
    stale = created.task.model_copy(deep=True)
    assert stale.management is not None
    stale.management.version = 2
    stale.management.description = "Must not persist after revocation"
    project.member_ids = ["usr_someone_else"]
    repository.save_project(project)

    with pytest.raises(TaskCommandConflict, match="project_not_found"):
        repository.save_managed_task_command(
            task=stale,
            expected_version=1,
            audit=AuditEvent(
                actor=user.id,
                action="update_project_task",
                target_type="task",
                target_id=stale.id,
                workspace_id=workspace.id,
                project_id=project.id,
            ),
            receipt=TaskCommandReceiptV1(
                id="task_command_membership_revoked",
                command_id="membership-revoked",
                user_id=user.id,
                operation="update",
                request_hash="b" * 64,
                task_id=stale.id,
                result_task=stale,
            ),
            authorization=TaskCommandAuthorizationV1(
                actor_id=user.id,
                workspace_id=workspace.id,
                project_id=project.id,
            ),
        )
    persisted = repository.get_task(stale.id)
    assert persisted is not None
    assert persisted.management is not None
    assert persisted.management.version == 1
    repository.close()


def test_task_and_thread_creation_roll_back_together_on_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    repository = SQLiteStore(tmp_path / "task-create-rollback.sqlite3")
    workspace = repository.save_workspace(Workspace(name="Rollback", description="Atomic task creation"))
    project = repository.save_project(Project(workspace_id=workspace.id, name="Rollback project", goal="Atomicity"))
    user = repository.save_user(
        User(
            workspace_id=workspace.id,
            default_project_id=project.id,
            name="Rollback owner",
            role="user",
            personal_agent_id="agent_rollback_owner",
        )
    )
    project.member_ids = [user.id]
    repository.save_project(project)
    conflicting_audit = repository.add_audit_event(
        AuditEvent(
            id="audit_task_create_conflict",
            actor=user.id,
            action="existing",
            target_type="task",
            target_id="existing",
            workspace_id=workspace.id,
            project_id=project.id,
        )
    )
    thread = ChatThread(
        id="thread_atomic_task",
        workspace_id=workspace.id,
        project_id=project.id,
        user_id=user.id,
        title="Atomic task",
        kind=ChatThreadKind.TASK,
    )
    task = Task(
        id="task_atomic_create",
        thread_id=thread.id,
        intent=Intent.GENERAL_CHAT,
        title="Atomic task",
        management=TaskManagementMetadataV1(created_by=user.id, updated_by=user.id),
    )
    receipt = TaskCommandReceiptV1(
        id="task_command_atomic_create",
        command_id="atomic-create",
        user_id=user.id,
        operation="create",
        request_hash="c" * 64,
        task_id=task.id,
        result_task=task,
    )

    with pytest.raises(sqlite3.IntegrityError):
        repository.create_managed_task(
            thread=thread,
            task=task,
            audit=conflicting_audit,
            receipt=receipt,
            authorization=TaskCommandAuthorizationV1(
                actor_id=user.id,
                workspace_id=workspace.id,
                project_id=project.id,
            ),
        )

    assert repository.get_task(task.id) is None
    assert repository.get_chat_thread(thread.id) is None
    assert repository.get_task_command_receipt(receipt.id) is None
    repository.close()


def test_task_management_survives_restart_without_providers(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    monkeypatch.setenv("AGENTMESH_EMBEDDING_ENABLED", "false")
    monkeypatch.delenv("AGENTMESH_LLM_API_KEY", raising=False)
    database = tmp_path / "standalone-task.sqlite3"
    first = SQLiteStore(database)
    workspace = first.save_workspace(Workspace(name="Standalone", description="Standalone smoke"))
    project = first.save_project(
        Project(workspace_id=workspace.id, name="Local project", goal="Complete a local task")
    )
    user = first.save_user(
        User(
            workspace_id=workspace.id,
            default_project_id=project.id,
            name="Local owner",
            role="user",
            personal_agent_id="agent_local_owner",
        )
    )
    project.member_ids = [user.id]
    first.save_project(project)
    first.save_agent(
        Agent(
            id=user.personal_agent_id,
            workspace_id=workspace.id,
            name="Local Agent",
            agent_type="personal",
            description="Standalone personal agent",
            owner_user_id=user.id,
        )
    )
    first_service = TaskManagementService(first)
    created = first_service.create_task(
        TaskCreateRequest(
            command_id="standalone-create",
            title="Persist without providers",
            assignee_kind="user",
            assignee_id=user.id,
        ),
        user,
    )
    planned = first_service.transition_task(
        created.task.id,
        TaskTransitionRequest(
            command_id="standalone-plan",
            expected_version=1,
            action="plan",
        ),
        user,
    )
    first.close()

    restarted = SQLiteStore(database)
    restarted_service = TaskManagementService(restarted)
    restored = restarted_service.get_task(planned.task.id, user)

    assert restored.task.title == "Persist without providers"
    assert restored.management.delivery_stage == "planned"
    assert restored.management.version == 2
    assert restarted.get_chat_thread(restored.task.thread_id).kind == "task"
    restarted.close()


def test_task_review_survives_restart_without_providers(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    monkeypatch.setenv("AGENTMESH_EMBEDDING_ENABLED", "false")
    monkeypatch.delenv("AGENTMESH_LLM_API_KEY", raising=False)
    database = tmp_path / "standalone-task-review.sqlite3"
    first = SQLiteStore(database)
    workspace = first.save_workspace(Workspace(name="Review", description="Standalone review"))
    project = first.save_project(Project(workspace_id=workspace.id, name="Review project", goal="Review locally"))
    reviewer = first.save_user(
        User(
            workspace_id=workspace.id,
            default_project_id=project.id,
            name="Local reviewer",
            role="team_lead",
            personal_agent_id="agent_local_reviewer",
        )
    )
    project.member_ids = [reviewer.id]
    first.save_project(project)
    task_service = TaskManagementService(first)
    created = task_service.create_task(
        TaskCreateRequest(command_id="standalone-review-create", title="Review without providers"),
        reviewer,
    )
    task_service.transition_task(
        created.task.id,
        TaskTransitionRequest(command_id="standalone-review-plan", expected_version=1, action="plan"),
        reviewer,
    )
    started = task_service.transition_task(
        created.task.id,
        TaskTransitionRequest(command_id="standalone-review-start", expected_version=2, action="start"),
        reviewer,
    )
    run, claimed = first.claim_new_agent_run(
        AgentRun(
            id="run_standalone_review",
            thread_id=started.task.thread_id,
            task_id=started.task.id,
            user_id=reviewer.id,
            workspace_id=workspace.id,
            project_id=project.id,
            input_text="Local deterministic output",
            status=AgentRunStatus.COMPLETED,
            requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
            orchestration_mode="preview",
            planning_contract_version=AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1,
        )
    )
    assert claimed is True
    envelope = UniversalSynthesisEnvelopeV1(
        run_id=run.id,
        requirement_version_id="standalone-review-requirement",
        plan_id="standalone-review-plan",
        plan_version=1,
        synthesis=SkillSynthesisResult(summary="Provider-free review output"),
    )
    content = canonical_json_bytes(envelope.model_dump(mode="json")).decode()
    artifact = Artifact(
        id="artifact_standalone_review",
        run_id=run.id,
        workspace_id=workspace.id,
        project_id=project.id,
        user_id=reviewer.id,
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
    V1VerifiedArtifactStore(first).insert_sealed(artifact)
    submitted = TaskCompletionService(first).submit_review(
        started.task.id,
        TaskReviewSubmitRequest(
            command_id="standalone-review-submit",
            expected_task_version=3,
            run_id=run.id,
            artifact_ids=[artifact.id],
        ),
        reviewer,
    )
    first.close()

    restarted = SQLiteStore(database)
    completion = TaskCompletionService(restarted)
    restored_review = restarted.get_task_review(submitted.item.review.id)
    assert restored_review is not None
    assert restored_review.status == "pending"
    decided = completion.decide_review(
        restored_review.id,
        TaskReviewDecisionRequest(
            command_id="standalone-review-accept",
            expected_version=1,
            decision="accepted",
        ),
        reviewer,
    )

    assert decided.item.review.status == "accepted"
    assert decided.task.management is not None
    assert decided.task.management.delivery_stage == "done"
    assert next(
        item for item in restarted.inbox_items if item.metadata.get("review_id") == restored_review.id
    ).status == "resolved"
    assert [
        event.action for event in restarted.audit_events if event.target_id == restored_review.id
    ] == ["submit_task_review", "decide_task_review"]
    restarted.close()
