from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.models import (
    Agent,
    AuditEvent,
    ChatThread,
    ChatThreadKind,
    CollaborationStage,
    Intent,
    Project,
    Task,
    TaskAssigneeKind,
    TaskDeliveryStage,
    TaskManagementMetadataV1,
    TaskPriority,
    TaskStatus,
    User,
    UserRole,
    now_utc,
)
from agentmesh.permissions import ACTION_MANAGE_PROJECT_TASKS, has_permission
from agentmesh.store import SQLiteStore, TaskCommandConflict
from agentmesh.task_management.access import task_assigned_to_user
from agentmesh.task_management.contracts import (
    TaskArchiveRequest,
    TaskCommandAuthorizationV1,
    TaskCommandReceiptV1,
    TaskCreateRequest,
    TaskManagementAction,
    TaskManagementPageV1,
    TaskManagementViewV1,
    TaskTransitionAction,
    TaskTransitionRequest,
    TaskUpdateRequest,
)
from agentmesh.task_management.settings import TaskManagementMode, task_management_mode


class TaskManagementError(RuntimeError):
    def __init__(self, code: str, *, status_code: int = 409):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class TaskListQuery:
    project_id: str
    page: int = 1
    page_size: int = 50
    include_archived: bool = False
    delivery_stage: TaskDeliveryStage | None = None
    priority: TaskPriority | None = None
    assignee_kind: TaskAssigneeKind | None = None
    assignee_id: str | None = None
    due_before: datetime | None = None
    due_after: datetime | None = None
    query: str | None = None


_TRANSITIONS: dict[TaskDeliveryStage, dict[TaskTransitionAction, TaskDeliveryStage]] = {
    TaskDeliveryStage.BACKLOG: {
        TaskTransitionAction.PLAN: TaskDeliveryStage.PLANNED,
        TaskTransitionAction.CANCEL: TaskDeliveryStage.CANCELLED,
    },
    TaskDeliveryStage.PLANNED: {
        TaskTransitionAction.START: TaskDeliveryStage.IN_PROGRESS,
        TaskTransitionAction.CANCEL: TaskDeliveryStage.CANCELLED,
    },
    TaskDeliveryStage.IN_PROGRESS: {
        TaskTransitionAction.SUBMIT_REVIEW: TaskDeliveryStage.REVIEW,
        TaskTransitionAction.CANCEL: TaskDeliveryStage.CANCELLED,
    },
    TaskDeliveryStage.REVIEW: {
        TaskTransitionAction.START: TaskDeliveryStage.IN_PROGRESS,
        TaskTransitionAction.COMPLETE: TaskDeliveryStage.DONE,
        TaskTransitionAction.CANCEL: TaskDeliveryStage.CANCELLED,
    },
    TaskDeliveryStage.DONE: {
        TaskTransitionAction.REOPEN: TaskDeliveryStage.IN_PROGRESS,
    },
    TaskDeliveryStage.CANCELLED: {
        TaskTransitionAction.REOPEN: TaskDeliveryStage.BACKLOG,
    },
}


class TaskManagementService:
    def __init__(self, repository: SQLiteStore):
        self.repository = repository

    def create_task(self, request: TaskCreateRequest, user: User) -> TaskManagementViewV1:
        project = self._project_for_user(user, user.default_project_id)
        request_hash = canonical_json_sha256(request.model_dump(mode="json"))
        receipt_id = self._receipt_id(user.id, request.command_id)
        existing = self.repository.get_task_command_receipt(receipt_id)
        if existing is not None:
            self._validate_replay(existing, "create", request_hash)
            self._visible_task(existing.task_id, user)
            return self.view(existing.result_task, user)
        self._require_write_mode()
        self._validate_assignee(user, request.assignee_kind, request.assignee_id, project.id)

        thread = ChatThread(
            workspace_id=user.workspace_id,
            project_id=project.id,
            user_id=user.id,
            title=request.title,
            kind=ChatThreadKind.TASK,
        )
        management = TaskManagementMetadataV1(
            description=request.description,
            task_type=request.task_type,
            priority=request.priority,
            due_at=request.due_at,
            assignee_kind=request.assignee_kind,
            assignee_id=request.assignee_id,
            tags=self._normalize_tags(request.tags),
            created_by=user.id,
            updated_by=user.id,
        )
        task = Task(
            thread_id=thread.id,
            intent=Intent.GENERAL_CHAT,
            title=request.title,
            management=management,
        )
        receipt = TaskCommandReceiptV1(
            id=receipt_id,
            command_id=request.command_id,
            user_id=user.id,
            operation="create",
            request_hash=request_hash,
            task_id=task.id,
            result_task=task,
        )
        audit = self._audit(
            user,
            "create_project_task",
            task,
            {"version": management.version, "task_type": management.task_type.value},
        )
        try:
            result = self.repository.create_managed_task(
                thread=thread,
                task=task,
                audit=audit,
                receipt=receipt,
                authorization=TaskCommandAuthorizationV1(
                    actor_id=user.id,
                    workspace_id=user.workspace_id,
                    project_id=project.id,
                    validate_assignee=True,
                    assignee_kind=request.assignee_kind,
                    assignee_id=request.assignee_id,
                ),
            )
        except TaskCommandConflict as error:
            raise TaskManagementError(error.code, status_code=self._status_for_store_error(error.code)) from error
        return self.view(result.task, user)

    def list_tasks(self, query: TaskListQuery, user: User) -> TaskManagementPageV1:
        self._project_for_user(user, query.project_id)
        for boundary in (query.due_after, query.due_before):
            if boundary is not None and boundary.utcoffset() is None:
                raise TaskManagementError("task_due_filter_timezone_required", status_code=422)
        if query.due_after is not None and query.due_before is not None and query.due_after > query.due_before:
            raise TaskManagementError("task_due_filter_invalid", status_code=422)
        normalized_query = (query.query or "").strip().casefold()
        items: list[TaskManagementViewV1] = []
        for task in self.repository.tasks:
            thread = self.repository.get_chat_thread(task.thread_id)
            if thread is None or thread.workspace_id != user.workspace_id or thread.project_id != query.project_id:
                continue
            if not self._task_visible(task, thread, user):
                continue
            management = self.management_for(task, thread)
            if not query.include_archived and management.archived_at is not None:
                continue
            if query.delivery_stage is not None and management.delivery_stage != query.delivery_stage:
                continue
            if query.priority is not None and management.priority != query.priority:
                continue
            if query.assignee_kind is not None and management.assignee_kind != query.assignee_kind:
                continue
            if query.assignee_id is not None and management.assignee_id != query.assignee_id:
                continue
            if query.due_before is not None and (
                management.due_at is None or management.due_at > query.due_before
            ):
                continue
            if query.due_after is not None and (
                management.due_at is None or management.due_at < query.due_after
            ):
                continue
            if normalized_query and normalized_query not in self._searchable_text(task, management):
                continue
            items.append(self.view(task, user, thread=thread, management=management))
        items.sort(key=lambda item: (item.task.updated_at, item.task.id), reverse=True)
        counts = {stage: 0 for stage in TaskDeliveryStage}
        for item in items:
            counts[item.management.delivery_stage] += 1
        start = (query.page - 1) * query.page_size
        end = start + query.page_size
        return TaskManagementPageV1(
            items=items[start:end],
            total=len(items),
            page=query.page,
            page_size=query.page_size,
            has_next=end < len(items),
            counts=counts,
        )

    def get_task(self, task_id: str, user: User) -> TaskManagementViewV1:
        task, thread = self._visible_task(task_id, user)
        return self.view(task, user, thread=thread)

    def update_task(self, task_id: str, request: TaskUpdateRequest, user: User) -> TaskManagementViewV1:
        request_hash = canonical_json_sha256(
            {"task_id": task_id, "request": request.model_dump(mode="json", exclude_unset=True)}
        )
        replay = self._replayed_task(user, request.command_id, "update", request_hash)
        if replay is not None:
            return self.view(replay, user)
        self._require_write_mode()
        task, thread = self._visible_task(task_id, user)
        management = self.management_for(task, thread)
        self._require_manage(user, management)
        self._require_not_archived(management)
        if management.version != request.expected_version:
            raise TaskManagementError("task_version_conflict")
        patch = request.model_dump(exclude={"command_id", "expected_version"}, exclude_unset=True)
        if "assignee_kind" in patch:
            self._validate_assignee(
                user,
                request.assignee_kind,
                request.assignee_id,
                thread.project_id,
            )
        updated = task.model_copy(deep=True)
        updated_management = management.model_copy(deep=True)
        thread_update: ChatThread | None = None
        changed_fields: list[str] = []
        if "title" in patch:
            updated.title = request.title or updated.title
            if thread.kind == ChatThreadKind.TASK:
                thread_update = thread.model_copy(update={"title": updated.title, "updated_at": now_utc()})
            changed_fields.append("title")
        for field in (
            "description",
            "task_type",
            "priority",
            "due_at",
            "assignee_kind",
            "assignee_id",
        ):
            if field in patch:
                setattr(updated_management, field, getattr(request, field))
                changed_fields.append(field)
        if "tags" in patch:
            updated_management.tags = self._normalize_tags(request.tags or [])
            changed_fields.append("tags")
        updated_management.version += 1
        updated_management.updated_by = user.id
        updated_management = TaskManagementMetadataV1.model_validate(updated_management.model_dump())
        updated.management = updated_management
        updated.updated_at = now_utc()
        return self._save_command(
            user=user,
            operation="update",
            command_id=request.command_id,
            request_hash=request_hash,
            task=updated,
            expected_version=request.expected_version,
            thread=thread_update,
            audit_action="update_project_task",
            audit_metadata={"version": updated_management.version, "changed_fields": changed_fields},
            validate_assignee="assignee_kind" in patch,
        )

    def transition_task(
        self,
        task_id: str,
        request: TaskTransitionRequest,
        user: User,
    ) -> TaskManagementViewV1:
        request_hash = canonical_json_sha256(
            {"task_id": task_id, "request": request.model_dump(mode="json")}
        )
        replay = self._replayed_task(user, request.command_id, "transition", request_hash)
        if replay is not None:
            return self.view(replay, user)
        self._require_write_mode()
        task, thread = self._visible_task(task_id, user)
        management = self.management_for(task, thread)
        self._require_manage(user, management)
        self._require_not_archived(management)
        if request.action == TaskTransitionAction.COMPLETE:
            self._require_project_manager(user)
        if management.version != request.expected_version:
            raise TaskManagementError("task_version_conflict")
        updated_management = management.model_copy(deep=True)
        if request.action == TaskTransitionAction.BLOCK:
            reason = (request.reason or "").strip()
            if not reason:
                raise TaskManagementError("task_block_reason_required", status_code=422)
            if management.delivery_stage in {TaskDeliveryStage.DONE, TaskDeliveryStage.CANCELLED}:
                raise TaskManagementError("task_transition_invalid")
            updated_management.blocked_reason = reason
            updated_management.blocked_at = now_utc()
        elif request.action == TaskTransitionAction.UNBLOCK:
            if management.blocked_reason is None:
                raise TaskManagementError("task_not_blocked")
            updated_management.blocked_reason = None
            updated_management.blocked_at = None
        else:
            if management.blocked_reason is not None and request.action != TaskTransitionAction.CANCEL:
                raise TaskManagementError("task_blocked")
            next_stage = _TRANSITIONS.get(management.delivery_stage, {}).get(request.action)
            if next_stage is None:
                raise TaskManagementError("task_transition_invalid")
            updated_management.delivery_stage = next_stage
            if next_stage in {TaskDeliveryStage.DONE, TaskDeliveryStage.CANCELLED}:
                updated_management.blocked_reason = None
                updated_management.blocked_at = None
        updated_management.version += 1
        updated_management.updated_by = user.id
        updated_management = TaskManagementMetadataV1.model_validate(updated_management.model_dump())
        updated = task.model_copy(
            update={"management": updated_management, "updated_at": now_utc()},
            deep=True,
        )
        return self._save_command(
            user=user,
            operation="transition",
            command_id=request.command_id,
            request_hash=request_hash,
            task=updated,
            expected_version=request.expected_version,
            audit_action="transition_project_task",
            audit_metadata={
                "action": request.action.value,
                "from_stage": management.delivery_stage.value,
                "to_stage": updated_management.delivery_stage.value,
                "version": updated_management.version,
            },
            require_project_manager=request.action == TaskTransitionAction.COMPLETE,
        )

    def archive_task(self, task_id: str, request: TaskArchiveRequest, user: User) -> TaskManagementViewV1:
        request_hash = canonical_json_sha256(
            {"task_id": task_id, "request": request.model_dump(mode="json")}
        )
        replay = self._replayed_task(user, request.command_id, "archive", request_hash)
        if replay is not None:
            return self.view(replay, user)
        self._require_write_mode()
        task, thread = self._visible_task(task_id, user)
        management = self.management_for(task, thread)
        self._require_project_manager(user)
        self._require_not_archived(management)
        if management.version != request.expected_version:
            raise TaskManagementError("task_version_conflict")
        if management.delivery_stage not in {TaskDeliveryStage.DONE, TaskDeliveryStage.CANCELLED}:
            raise TaskManagementError("task_archive_requires_terminal_stage")
        if management.archived_at is not None:
            raise TaskManagementError("task_already_archived")
        updated_management = TaskManagementMetadataV1.model_validate(
            management.model_copy(
                update={
                    "archived_at": now_utc(),
                    "version": management.version + 1,
                    "updated_by": user.id,
                }
            ).model_dump()
        )
        updated = task.model_copy(update={"management": updated_management, "updated_at": now_utc()}, deep=True)
        return self._save_command(
            user=user,
            operation="archive",
            command_id=request.command_id,
            request_hash=request_hash,
            task=updated,
            expected_version=request.expected_version,
            audit_action="archive_project_task",
            audit_metadata={"version": updated_management.version},
            require_project_manager=True,
        )

    def management_for(self, task: Task, thread: ChatThread) -> TaskManagementMetadataV1:
        if task.management is not None:
            return task.management.model_copy(deep=True)
        stage = {
            TaskStatus.CREATED: TaskDeliveryStage.BACKLOG,
            TaskStatus.RUNNING: TaskDeliveryStage.IN_PROGRESS,
            TaskStatus.WAITING_EXTERNAL_AGENT: TaskDeliveryStage.IN_PROGRESS,
            TaskStatus.SYNTHESIZING: TaskDeliveryStage.IN_PROGRESS,
            TaskStatus.COMPLETED: TaskDeliveryStage.DONE,
            TaskStatus.FAILED: TaskDeliveryStage.IN_PROGRESS,
        }[task.status]
        if task.collaboration_stage == CollaborationStage.REVIEW and stage not in {
            TaskDeliveryStage.DONE,
            TaskDeliveryStage.CANCELLED,
        }:
            stage = TaskDeliveryStage.REVIEW
        return TaskManagementMetadataV1(
            delivery_stage=stage,
            blocked_reason="Legacy task is blocked" if task.collaboration_stage == CollaborationStage.BLOCKED else None,
            blocked_at=task.updated_at if task.collaboration_stage == CollaborationStage.BLOCKED else None,
            assignee_kind=TaskAssigneeKind.AGENT if task.current_owner_agent_id else None,
            assignee_id=task.current_owner_agent_id,
            created_by=thread.user_id,
            updated_by=thread.user_id,
        )

    def view(
        self,
        task: Task,
        user: User,
        *,
        thread: ChatThread | None = None,
        management: TaskManagementMetadataV1 | None = None,
    ) -> TaskManagementViewV1:
        resolved_thread = thread or self.repository.get_chat_thread(task.thread_id)
        if resolved_thread is None:
            raise TaskManagementError("task_not_found", status_code=404)
        resolved_management = management or self.management_for(task, resolved_thread)
        return TaskManagementViewV1(
            task=task,
            management=resolved_management,
            allowed_actions=self.allowed_actions(user, resolved_management),
        )

    def allowed_actions(
        self,
        user: User,
        management: TaskManagementMetadataV1,
    ) -> list[TaskManagementAction]:
        if task_management_mode() is not TaskManagementMode.WRITE or management.archived_at is not None:
            return []
        if not self._can_manage(user, management):
            return []
        actions = [TaskManagementAction.EDIT, TaskManagementAction.ASSIGN]
        if management.blocked_reason is not None:
            actions.extend([TaskManagementAction.UNBLOCK, TaskManagementAction.CANCEL])
            return list(dict.fromkeys(actions))
        if management.delivery_stage not in {TaskDeliveryStage.DONE, TaskDeliveryStage.CANCELLED}:
            actions.append(TaskManagementAction.BLOCK)
        transitions = _TRANSITIONS.get(management.delivery_stage, {})
        actions.extend(
            TaskManagementAction(action.value)
            for action in transitions
            if action != TaskTransitionAction.COMPLETE or self._is_project_manager(user)
        )
        if (
            management.delivery_stage in {TaskDeliveryStage.DONE, TaskDeliveryStage.CANCELLED}
            and self._is_project_manager(user)
        ):
            actions.append(TaskManagementAction.ARCHIVE)
        return list(dict.fromkeys(actions))

    def _visible_task(self, task_id: str, user: User) -> tuple[Task, ChatThread]:
        task = self.repository.get_task(task_id)
        if task is None:
            raise TaskManagementError("task_not_found", status_code=404)
        thread = self.repository.get_chat_thread(task.thread_id)
        if thread is None or not self._task_visible(task, thread, user):
            raise TaskManagementError("task_not_found", status_code=404)
        return task, thread

    def _task_visible(self, task: Task, thread: ChatThread, user: User) -> bool:
        if thread.workspace_id != user.workspace_id or not self.repository.user_can_access_project(
            user.id, thread.project_id
        ):
            return False
        if thread.kind == ChatThreadKind.TASK:
            return True
        if user.role in {UserRole.TEAM_LEAD, UserRole.ADMIN} or thread.user_id == user.id:
            return True
        if task_assigned_to_user(task, user, self.repository):
            return True
        personal_agent_ids = {user.personal_agent_id}
        for post in self.repository.blackboard_posts:
            if post.task_id != task.id:
                continue
            values = {
                post.actor,
                post.current_owner_agent_id or "",
                post.current_owner_label or "",
                *(post.read_by_agents or []),
            }
            if post.execution_lock is not None:
                values.update({post.execution_lock.owner_agent_id, post.execution_lock.owner_label})
            if values & personal_agent_ids:
                return True
        return False

    def _can_manage(self, user: User, management: TaskManagementMetadataV1) -> bool:
        if has_permission(user, ACTION_MANAGE_PROJECT_TASKS, self.repository.permission_policy_rules):
            return True
        if management.created_by == user.id:
            return True
        if management.assignee_kind == TaskAssigneeKind.USER and management.assignee_id == user.id:
            return True
        if management.assignee_kind == TaskAssigneeKind.AGENT and management.assignee_id:
            agent = self._resolve_agent(management.assignee_id)
            return agent is not None and agent.owner_user_id == user.id
        return False

    def _require_manage(self, user: User, management: TaskManagementMetadataV1) -> None:
        if not self._can_manage(user, management):
            raise TaskManagementError("task_action_forbidden", status_code=403)

    def _is_project_manager(self, user: User) -> bool:
        return has_permission(
            user,
            ACTION_MANAGE_PROJECT_TASKS,
            self.repository.permission_policy_rules,
        )

    def _require_project_manager(self, user: User) -> None:
        if not self._is_project_manager(user):
            raise TaskManagementError("task_action_forbidden", status_code=403)

    @staticmethod
    def _require_not_archived(management: TaskManagementMetadataV1) -> None:
        if management.archived_at is not None:
            raise TaskManagementError("task_archived")

    def _validate_assignee(
        self,
        user: User,
        kind: TaskAssigneeKind | None,
        assignee_id: str | None,
        project_id: str,
    ) -> None:
        if kind is None and assignee_id is None:
            return
        if kind is None or assignee_id is None:
            raise TaskManagementError("task_assignee_invalid", status_code=422)
        can_manage_project = has_permission(
            user,
            ACTION_MANAGE_PROJECT_TASKS,
            self.repository.permission_policy_rules,
        )
        if kind == TaskAssigneeKind.USER:
            assignee = self.repository.get_user(assignee_id)
            if (
                assignee is None
                or assignee.workspace_id != user.workspace_id
                or assignee.status != "active"
                or not self.repository.user_can_access_project(assignee.id, project_id)
            ):
                raise TaskManagementError("task_assignee_not_found", status_code=404)
            if assignee.id != user.id and not can_manage_project:
                raise TaskManagementError("task_assignment_forbidden", status_code=403)
            return
        agent = self._resolve_agent(assignee_id)
        if agent is None or agent.workspace_id != user.workspace_id or agent.status != "online":
            raise TaskManagementError("task_assignee_not_found", status_code=404)
        if agent.owner_user_id == user.id:
            return
        if agent.owner_user_id is None and can_manage_project:
            return
        raise TaskManagementError("task_assignment_forbidden", status_code=403)

    def _resolve_agent(self, agent_id: str) -> Agent | None:
        from agentmesh.seed import AGENTS

        return self.repository.get_agent(agent_id) or next(
            (candidate for candidate in AGENTS if candidate.id == agent_id),
            None,
        )

    def _project_for_user(self, user: User, project_id: str) -> Project:
        project = self.repository.get_project(project_id)
        if (
            project is None
            or project.workspace_id != user.workspace_id
            or not self.repository.user_can_access_project(user.id, project_id)
        ):
            raise TaskManagementError("project_not_found", status_code=404)
        return project

    def _replayed_task(
        self,
        user: User,
        command_id: str,
        operation: str,
        request_hash: str,
    ) -> Task | None:
        receipt = self.repository.get_task_command_receipt(self._receipt_id(user.id, command_id))
        if receipt is None:
            return None
        self._validate_replay(receipt, operation, request_hash)
        self._visible_task(receipt.task_id, user)
        return receipt.result_task.model_copy(deep=True)

    @staticmethod
    def _validate_replay(receipt: TaskCommandReceiptV1, operation: str, request_hash: str) -> None:
        if receipt.operation != operation or receipt.request_hash != request_hash:
            raise TaskManagementError("task_command_conflict")

    def _save_command(
        self,
        *,
        user: User,
        operation: str,
        command_id: str,
        request_hash: str,
        task: Task,
        expected_version: int,
        audit_action: str,
        audit_metadata: dict[str, object],
        thread: ChatThread | None = None,
        require_project_manager: bool = False,
        validate_assignee: bool = False,
    ) -> TaskManagementViewV1:
        current_thread = thread or self.repository.get_chat_thread(task.thread_id)
        if current_thread is None:
            raise TaskManagementError("task_not_found", status_code=404)
        receipt = TaskCommandReceiptV1(
            id=self._receipt_id(user.id, command_id),
            command_id=command_id,
            user_id=user.id,
            operation=operation,
            request_hash=request_hash,
            task_id=task.id,
            result_task=task,
        )
        audit = self._audit(user, audit_action, task, audit_metadata)
        try:
            result = self.repository.save_managed_task_command(
                task=task,
                expected_version=expected_version,
                audit=audit,
                receipt=receipt,
                authorization=TaskCommandAuthorizationV1(
                    actor_id=user.id,
                    workspace_id=user.workspace_id,
                    project_id=current_thread.project_id,
                    require_project_manager=require_project_manager,
                    validate_assignee=validate_assignee,
                    assignee_kind=task.management.assignee_kind if task.management is not None else None,
                    assignee_id=task.management.assignee_id if task.management is not None else None,
                ),
                thread=thread,
            )
        except TaskCommandConflict as error:
            raise TaskManagementError(
                error.code,
                status_code=self._status_for_store_error(error.code),
            ) from error
        return self.view(result.task, user, thread=thread)

    @staticmethod
    def _status_for_store_error(code: str) -> int:
        if code in {"task_not_found", "project_not_found", "task_assignee_not_found"}:
            return 404
        if code in {"task_action_forbidden", "task_assignment_forbidden", "task_actor_not_authorized"}:
            return 403
        if code == "task_assignee_invalid":
            return 422
        return 409

    @staticmethod
    def _receipt_id(user_id: str, command_id: str) -> str:
        digest = canonical_json_sha256({"user_id": user_id, "command_id": command_id})[:24]
        return f"task_command_{digest}"

    @staticmethod
    def _normalize_tags(tags: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in tags:
            tag = value.strip()
            if not tag or tag in normalized:
                continue
            if len(tag) > 40:
                raise TaskManagementError("task_tag_invalid", status_code=422)
            normalized.append(tag)
        if len(normalized) > 12:
            raise TaskManagementError("task_tags_limit_exceeded", status_code=422)
        return normalized

    @staticmethod
    def _searchable_text(task: Task, management: TaskManagementMetadataV1) -> str:
        return " ".join(
            [
                task.title,
                management.description,
                management.assignee_id or "",
                *management.tags,
            ]
        ).casefold()

    def _audit(
        self,
        user: User,
        action: str,
        task: Task,
        metadata: dict[str, object],
    ) -> AuditEvent:
        thread = self.repository.get_chat_thread(task.thread_id)
        return AuditEvent(
            actor=user.id,
            action=action,
            target_type="task",
            target_id=task.id,
            workspace_id=thread.workspace_id if thread is not None else user.workspace_id,
            project_id=thread.project_id if thread is not None else user.default_project_id,
            metadata=metadata,
        )

    @staticmethod
    def _require_write_mode() -> None:
        if task_management_mode() is not TaskManagementMode.WRITE:
            raise TaskManagementError("task_management_read_only")
