from __future__ import annotations

from dataclasses import dataclass

from agentmesh.artifacts import ArtifactAccessError, ArtifactAccessScope, V1ArtifactReader
from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.models import (
    AgentRunStatus,
    Artifact,
    ArtifactVerificationState,
    AuditEvent,
    InboxItem,
    Scope,
    TaskDeliveryStage,
    TaskManagementMetadataV1,
    TaskReviewStatus,
    TaskReviewV1,
    User,
    now_utc,
)
from agentmesh.permissions import ACTION_REVIEW_TASK_DELIVERABLES, has_permission
from agentmesh.store import ResearchStoreConflict, SQLiteStore, TaskReviewConflict
from agentmesh.task_management.contracts import TaskManagementAction, TaskManagementViewV1
from agentmesh.task_management.service import TaskManagementError, TaskManagementService
from agentmesh.task_management.settings import TaskManagementMode, task_management_mode
from agentmesh.task_review.contracts import (
    TaskReviewAllowedAction,
    TaskReviewAuthorizationV1,
    TaskReviewCommandReceiptV1,
    TaskReviewDecisionRequest,
    TaskReviewMutationResponseV1,
    TaskReviewSubmitRequest,
    TaskReviewViewV1,
)


class TaskReviewError(RuntimeError):
    def __init__(self, code: str, *, status_code: int = 409):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class TaskReviewPage:
    items: list[TaskReviewViewV1]
    truncated: bool


class TaskCompletionService:
    def __init__(self, repository: SQLiteStore):
        self.repository = repository
        self.task_service = TaskManagementService(repository)
        self.artifact_reader = V1ArtifactReader(repository)

    def submit_review(
        self,
        task_id: str,
        request: TaskReviewSubmitRequest,
        user: User,
    ) -> TaskReviewMutationResponseV1:
        request_hash = canonical_json_sha256(
            {"task_id": task_id, "request": request.model_dump(mode="json")}
        )
        receipt_id = self._receipt_id(user.id, request.command_id)
        try:
            existing = self.repository.get_task_review_command_receipt(receipt_id)
        except TaskReviewConflict as error:
            raise TaskReviewError(error.code) from error
        if existing is not None:
            self._validate_replay(existing, "submit", request_hash)
            self._task_view(existing.result_review.task_id, user)
            persisted = self.repository.get_task_review(existing.result_review.id)
            return TaskReviewMutationResponseV1(
                item=self.view(
                    existing.result_review,
                    user,
                    current_status=persisted.status if persisted is not None else existing.result_review.status,
                ),
                task=existing.result_task,
            )
        self._require_write_mode()
        task_view = self._task_view(task_id, user)
        task = task_view.task
        management = task_view.management
        thread = self.repository.get_chat_thread(task.thread_id)
        if thread is None:
            raise TaskReviewError("task_not_found", status_code=404)
        if management.version != request.expected_task_version:
            raise TaskReviewError("task_version_conflict")
        if management.archived_at is not None:
            raise TaskReviewError("task_archived")
        if management.blocked_reason is not None:
            raise TaskReviewError("task_blocked")
        if management.delivery_stage is not TaskDeliveryStage.IN_PROGRESS:
            raise TaskReviewError("task_review_requires_in_progress")
        if TaskManagementAction.SUBMIT_REVIEW not in task_view.allowed_actions:
            raise TaskReviewError("task_action_forbidden", status_code=403)
        try:
            run = self.repository.get_agent_run(request.run_id)
        except ResearchStoreConflict as error:
            raise TaskReviewError("task_review_run_integrity_failed") from error
        if (
            run is None
            or run.task_id != task.id
            or run.workspace_id != thread.workspace_id
            or run.project_id != thread.project_id
        ):
            raise TaskReviewError("task_review_run_not_found", status_code=404)
        if run.status not in {AgentRunStatus.COMPLETED, AgentRunStatus.PARTIAL}:
            raise TaskReviewError("task_review_run_not_complete")
        if run.user_id != user.id:
            raise TaskReviewError("task_review_submitter_not_run_owner", status_code=403)
        artifact_hashes: list[str] = []
        for artifact_id in request.artifact_ids:
            try:
                artifact = self.artifact_reader.read_for_owner(
                    artifact_id,
                    reader_scope=ArtifactAccessScope(
                        user_id=run.user_id,
                        workspace_id=run.workspace_id,
                        project_id=run.project_id,
                        run_id=run.id,
                    ),
                )
            except ArtifactAccessError as error:
                code = (
                    "task_review_artifact_not_found"
                    if str(error) == "artifact_not_found"
                    else "task_review_artifact_not_reviewable"
                )
                raise TaskReviewError(code, status_code=404 if code.endswith("not_found") else 409) from error
            if artifact.verification_state is not ArtifactVerificationState.SEALED or artifact.content_hash is None:
                raise TaskReviewError("task_review_artifact_not_reviewable")
            artifact_hashes.append(artifact.content_hash)
        reviewer = self.repository.select_task_reviewer(
            project_id=thread.project_id,
            requested_by=user.id,
        )
        if reviewer is None:
            raise TaskReviewError("task_review_reviewer_unavailable")
        next_round = self.repository.next_task_review_round(task.id)
        now = now_utc()
        review = TaskReviewV1(
            task_id=task.id,
            run_id=run.id,
            artifact_ids=list(request.artifact_ids),
            artifact_hashes=artifact_hashes,
            round=next_round,
            requested_by=user.id,
            reviewer_id=reviewer.id,
            task_version=management.version + 1,
            created_at=now,
            updated_at=now,
        )
        updated_management = TaskManagementMetadataV1.model_validate(
            management.model_copy(
                update={
                    "delivery_stage": TaskDeliveryStage.REVIEW,
                    "version": management.version + 1,
                    "updated_by": user.id,
                }
            ).model_dump()
        )
        updated_task = task.model_copy(
            update={"management": updated_management, "updated_at": now},
            deep=True,
        )
        inbox = InboxItem(
            title=f"审核任务交付：{task.title}",
            summary=f"第 {review.round} 轮交付包含 {len(review.artifact_ids)} 个已封存产物。",
            item_type="task_review",
            scope=Scope.PRIVATE,
            user_id=reviewer.id,
            workspace_id=thread.workspace_id,
            project_id=thread.project_id,
            metadata={
                "review_id": review.id,
                "task_id": task.id,
                "run_id": run.id,
                "artifact_count": str(len(review.artifact_ids)),
                "round": str(review.round),
            },
            created_at=now,
            updated_at=now,
        )
        audit = AuditEvent(
            actor=user.id,
            action="submit_task_review",
            target_type="task_review",
            target_id=review.id,
            workspace_id=thread.workspace_id,
            project_id=thread.project_id,
            metadata={
                "task_id": task.id,
                "run_id": run.id,
                "artifact_count": len(review.artifact_ids),
                "round": review.round,
                "task_version": review.task_version,
                "reviewer_id": review.reviewer_id,
            },
            created_at=now,
        )
        receipt = TaskReviewCommandReceiptV1(
            id=receipt_id,
            command_id=request.command_id,
            user_id=user.id,
            operation="submit",
            request_hash=request_hash,
            review_id=review.id,
            result_review=review,
            result_task=updated_task,
            created_at=now,
        )
        try:
            result = self.repository.submit_task_review_command(
                review=review,
                expected_task_version=request.expected_task_version,
                inbox=inbox,
                audit=audit,
                receipt=receipt,
                authorization=TaskReviewAuthorizationV1(
                    actor_id=user.id,
                    workspace_id=thread.workspace_id,
                    project_id=thread.project_id,
                ),
            )
        except TaskReviewConflict as error:
            raise TaskReviewError(error.code, status_code=self._status_for_error(error.code)) from error
        return TaskReviewMutationResponseV1(
            item=self.view(result.review, user),
            task=result.task,
        )

    def decide_review(
        self,
        review_id: str,
        request: TaskReviewDecisionRequest,
        user: User,
    ) -> TaskReviewMutationResponseV1:
        request_hash = canonical_json_sha256(
            {"review_id": review_id, "request": request.model_dump(mode="json")}
        )
        receipt_id = self._receipt_id(user.id, request.command_id)
        try:
            existing = self.repository.get_task_review_command_receipt(receipt_id)
        except TaskReviewConflict as error:
            raise TaskReviewError(error.code) from error
        if existing is not None:
            self._validate_replay(existing, "decide", request_hash)
            self._task_view(existing.result_review.task_id, user)
            persisted = self.repository.get_task_review(existing.result_review.id)
            return TaskReviewMutationResponseV1(
                item=self.view(
                    existing.result_review,
                    user,
                    current_status=persisted.status if persisted is not None else existing.result_review.status,
                ),
                task=existing.result_task,
            )
        self._require_write_mode()
        try:
            current = self.repository.get_task_review(review_id)
        except TaskReviewConflict as error:
            raise TaskReviewError(error.code) from error
        if current is None:
            raise TaskReviewError("task_review_not_found", status_code=404)
        task_view = self._task_view(current.task_id, user)
        task = task_view.task
        thread = self.repository.get_chat_thread(task.thread_id)
        if thread is None:
            raise TaskReviewError("task_review_not_found", status_code=404)
        if current.reviewer_id != user.id or not has_permission(
            user,
            ACTION_REVIEW_TASK_DELIVERABLES,
            self.repository.permission_policy_rules,
        ):
            raise TaskReviewError("task_review_not_found", status_code=404)
        if current.version != request.expected_version:
            raise TaskReviewError("task_review_version_conflict")
        if current.status is not TaskReviewStatus.PENDING:
            raise TaskReviewError("task_review_already_decided")
        management = task_view.management
        if (
            management.version != current.task_version
            or management.delivery_stage is not TaskDeliveryStage.REVIEW
        ):
            raise TaskReviewError("task_review_task_changed")
        now = now_utc()
        status = TaskReviewStatus(request.decision)
        decided = TaskReviewV1.model_validate(
            current.model_copy(
                update={
                    "status": status,
                    "decision_note": request.decision_note,
                    "version": current.version + 1,
                    "updated_at": now,
                    "decided_at": now,
                }
            ).model_dump()
        )
        next_stage = (
            TaskDeliveryStage.DONE
            if status is TaskReviewStatus.ACCEPTED
            else TaskDeliveryStage.IN_PROGRESS
        )
        updated_management = TaskManagementMetadataV1.model_validate(
            management.model_copy(
                update={
                    "delivery_stage": next_stage,
                    "blocked_reason": None,
                    "blocked_at": None,
                    "version": management.version + 1,
                    "updated_by": user.id,
                }
            ).model_dump()
        )
        updated_task = task.model_copy(
            update={"management": updated_management, "updated_at": now},
            deep=True,
        )
        audit = AuditEvent(
            actor=user.id,
            action="decide_task_review",
            target_type="task_review",
            target_id=decided.id,
            workspace_id=thread.workspace_id,
            project_id=thread.project_id,
            metadata={
                "task_id": decided.task_id,
                "run_id": decided.run_id,
                "decision": decided.status.value,
                "round": decided.round,
                "review_version": decided.version,
                "task_version": updated_management.version,
            },
            created_at=now,
        )
        receipt = TaskReviewCommandReceiptV1(
            id=receipt_id,
            command_id=request.command_id,
            user_id=user.id,
            operation="decide",
            request_hash=request_hash,
            review_id=decided.id,
            result_review=decided,
            result_task=updated_task,
            created_at=now,
        )
        try:
            result = self.repository.decide_task_review_command(
                review=decided,
                expected_version=request.expected_version,
                audit=audit,
                receipt=receipt,
                authorization=TaskReviewAuthorizationV1(
                    actor_id=user.id,
                    workspace_id=thread.workspace_id,
                    project_id=thread.project_id,
                ),
            )
        except TaskReviewConflict as error:
            raise TaskReviewError(error.code, status_code=self._status_for_error(error.code)) from error
        return TaskReviewMutationResponseV1(
            item=self.view(result.review, user),
            task=result.task,
        )

    def get_review_artifact(self, review_id: str, artifact_id: str, user: User) -> Artifact:
        try:
            review = self.repository.get_task_review(review_id)
        except TaskReviewConflict as error:
            raise TaskReviewError(error.code) from error
        if review is None:
            raise TaskReviewError("task_review_not_found", status_code=404)
        task_view = self._task_view(review.task_id, user)
        task = task_view.task
        thread = self.repository.get_chat_thread(task.thread_id)
        if (
            thread is None
            or review.reviewer_id != user.id
            or not has_permission(
                user,
                ACTION_REVIEW_TASK_DELIVERABLES,
                self.repository.permission_policy_rules,
            )
        ):
            raise TaskReviewError("task_review_not_found", status_code=404)
        try:
            artifact_index = review.artifact_ids.index(artifact_id)
        except ValueError:
            raise TaskReviewError("task_review_artifact_not_found", status_code=404) from None
        try:
            run = self.repository.get_agent_run(review.run_id)
        except ResearchStoreConflict as error:
            raise TaskReviewError("task_review_run_integrity_failed") from error
        if (
            run is None
            or run.task_id != review.task_id
            or run.user_id != review.requested_by
            or run.workspace_id != thread.workspace_id
            or run.project_id != thread.project_id
        ):
            raise TaskReviewError("task_review_not_found", status_code=404)
        try:
            artifact = self.artifact_reader.read_for_owner(
                artifact_id,
                reader_scope=ArtifactAccessScope(
                    user_id=run.user_id,
                    workspace_id=run.workspace_id,
                    project_id=run.project_id,
                    run_id=run.id,
                ),
            )
        except ArtifactAccessError as error:
            raise TaskReviewError(
                "task_review_artifact_not_found" if str(error) == "artifact_not_found" else str(error),
                status_code=404 if str(error) == "artifact_not_found" else 409,
            ) from error
        if artifact.content_hash != review.artifact_hashes[artifact_index]:
            raise TaskReviewError("task_review_artifact_integrity_failed")
        return artifact

    def list_for_task(self, task_id: str, user: User, *, limit: int = 50) -> TaskReviewPage:
        self._task_view(task_id, user)
        try:
            reviews = self.repository.list_task_reviews(task_id, limit=limit + 1)
        except TaskReviewConflict as error:
            raise TaskReviewError(error.code) from error
        return TaskReviewPage(
            items=[self.view(review, user) for review in reviews[:limit]],
            truncated=len(reviews) > limit,
        )

    def view(
        self,
        review: TaskReviewV1,
        user: User,
        *,
        current_status: TaskReviewStatus | None = None,
    ) -> TaskReviewViewV1:
        pending = (current_status or review.status) is TaskReviewStatus.PENDING
        can_decide = (
            pending
            and review.reviewer_id == user.id
            and has_permission(
                user,
                ACTION_REVIEW_TASK_DELIVERABLES,
                self.repository.permission_policy_rules,
            )
            and task_management_mode() is TaskManagementMode.WRITE
        )
        actions = (
            [
                TaskReviewAllowedAction.ACCEPT,
                TaskReviewAllowedAction.REQUEST_CHANGES,
                TaskReviewAllowedAction.REJECT,
            ]
            if can_decide
            else []
        )
        return TaskReviewViewV1(review=review, allowed_actions=actions)

    def _task_view(self, task_id: str, user: User) -> TaskManagementViewV1:
        try:
            return self.task_service.get_task(task_id, user)
        except TaskManagementError as error:
            raise TaskReviewError(error.code, status_code=error.status_code) from error

    @staticmethod
    def _validate_replay(
        receipt: TaskReviewCommandReceiptV1,
        operation: str,
        request_hash: str,
    ) -> None:
        if receipt.operation != operation or receipt.request_hash != request_hash:
            raise TaskReviewError("task_review_command_conflict")

    @staticmethod
    def _receipt_id(user_id: str, command_id: str) -> str:
        digest = canonical_json_sha256({"user_id": user_id, "command_id": command_id})[:24]
        return f"task_review_command_{digest}"

    @staticmethod
    def _status_for_error(code: str) -> int:
        if code in {
            "task_not_found",
            "task_review_not_found",
            "task_review_run_not_found",
            "task_review_artifact_not_found",
        }:
            return 404
        if code in {
            "task_action_forbidden",
            "task_review_actor_not_authorized",
            "task_review_submitter_not_run_owner",
        }:
            return 403
        if code in {"task_review_artifact_not_reviewable"}:
            return 422
        return 409

    @staticmethod
    def _require_write_mode() -> None:
        if task_management_mode() is not TaskManagementMode.WRITE:
            raise TaskReviewError("task_management_read_only")
