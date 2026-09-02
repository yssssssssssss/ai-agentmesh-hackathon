from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.memory_governance.contracts import (
    MemoryCaptureResponseV1,
    MemoryCaptureTarget,
    MemoryEntryKind,
    MemoryEntryViewV1,
    MemoryGovernanceAuthorizationV1,
    MemoryGovernanceCommandReceiptV1,
    MemoryLineageViewV1,
    MemoryPageV1,
    MemoryReviewAllowedAction,
    MemoryReviewDecisionRequest,
    MemoryReviewDecisionResponseV1,
    MemoryReviewViewV1,
    TaskMemoryLinkV1,
    TaskReviewMemoryCaptureRequest,
)
from agentmesh.models import (
    AuditEvent,
    InboxItem,
    MemoryItem,
    MemoryProvenanceV1,
    MemoryRelation,
    MemoryReviewStatus,
    MemoryReviewV1,
    MemorySourceKind,
    MemoryStatus,
    Scope,
    TaskReviewStatus,
    User,
    UserMemoryItem,
    now_utc,
)
from agentmesh.permissions import ACTION_ACCEPT_TEAM_MEMORY, has_permission
from agentmesh.store import MemoryGovernanceConflict, SQLiteStore, TaskReviewConflict
from agentmesh.task_management.contracts import TaskManagementViewV1
from agentmesh.task_management.service import TaskManagementError, TaskManagementService
from agentmesh.task_management.settings import TaskManagementMode, task_management_mode


class MemoryGovernanceError(RuntimeError):
    def __init__(self, code: str, *, status_code: int = 409):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class MemoryListQuery:
    project_id: str
    page: int = 1
    page_size: int = 50
    include_archived: bool = False


class MemoryGovernanceService:
    def __init__(self, repository: SQLiteStore):
        self.repository = repository
        self.task_service = TaskManagementService(repository)

    def capture_from_task_review(
        self,
        task_review_id: str,
        request: TaskReviewMemoryCaptureRequest,
        user: User,
    ) -> MemoryCaptureResponseV1:
        request_hash = canonical_json_sha256(
            {"task_review_id": task_review_id, "request": request.model_dump(mode="json")}
        )
        receipt_id = self._receipt_id(user.id, request.command_id)
        existing = self._get_receipt(receipt_id)
        if existing is not None:
            self._validate_replay(existing, "capture", request_hash)
            self._require_entry_visible(existing.result_entry, user)
            return MemoryCaptureResponseV1(
                item=existing.result_entry,
                memory_review=self._review_view(existing.result_review, user)
                if existing.result_review is not None
                else None,
            )
        self._require_write_mode()
        try:
            task_review = self.repository.get_task_review(task_review_id)
        except TaskReviewConflict as error:
            raise MemoryGovernanceError(error.code) from error
        if task_review is None or task_review.status is not TaskReviewStatus.ACCEPTED:
            raise MemoryGovernanceError("memory_source_review_not_found", status_code=404)
        task_view = self._task_view(task_review.task_id, user)
        if task_review.requested_by != user.id:
            raise MemoryGovernanceError("memory_capture_forbidden", status_code=403)
        thread = self.repository.get_chat_thread(task_view.task.thread_id)
        if thread is None:
            raise MemoryGovernanceError("memory_source_review_not_found", status_code=404)
        now = now_utc()
        provenance = MemoryProvenanceV1(
            source_kind=MemorySourceKind.TASK_ARTIFACT,
            task_id=task_review.task_id,
            run_id=task_review.run_id,
            review_id=task_review.id,
            artifact_ids=list(task_review.artifact_ids),
            artifact_hashes=list(task_review.artifact_hashes),
            created_by=user.id,
            created_at=now,
        )
        memory_review: MemoryReviewV1 | None = None
        inbox: InboxItem | None = None
        if request.target is MemoryCaptureTarget.PERSONAL:
            item: MemoryItem | UserMemoryItem = UserMemoryItem(
                user_id=user.id,
                layer=request.layer,
                title=request.title,
                summary=request.summary,
                source_kind=MemorySourceKind.TASK_ARTIFACT.value,
                memory_type=request.memory_type,
                scope=Scope.PRIVATE,
                workspace_id=user.workspace_id,
                project_id=thread.project_id,
                source_task_id=task_review.task_id,
                provenance=provenance,
                created_at=now,
                updated_at=now,
            )
        else:
            reviewer = self.repository.select_memory_reviewer(project_id=thread.project_id, owner_id=user.id)
            if reviewer is None:
                raise MemoryGovernanceError("memory_reviewer_unavailable")
            item = MemoryItem(
                title=request.title,
                summary=request.summary,
                memory_type=request.memory_type,
                scope=Scope.TEAM_CANDIDATE,
                status=MemoryStatus.PROPOSED,
                owner_user_id=user.id,
                workspace_id=user.workspace_id,
                project_id=thread.project_id,
                provenance=provenance,
                created_at=now,
                updated_at=now,
            )
            memory_review = MemoryReviewV1(
                memory_id=item.id,
                source_task_review_id=task_review.id,
                requested_by=user.id,
                reviewer_id=reviewer.id,
                memory_version=item.version,
                created_at=now,
                updated_at=now,
            )
            inbox = InboxItem(
                title=f"审核团队记忆候选：{item.title}",
                summary="该候选来自已接受的 Task Review，需要独立 Memory Review。",
                item_type="memory_review",
                scope=Scope.PRIVATE,
                user_id=reviewer.id,
                workspace_id=user.workspace_id,
                project_id=thread.project_id,
                metadata={
                    "memory_review_id": memory_review.id,
                    "memory_id": item.id,
                    "task_review_id": task_review.id,
                },
                created_at=now,
                updated_at=now,
            )
        entry = self.entry_view(item, user)
        relations = [
            MemoryRelation(
                from_memory_id=item.id,
                to_source_id=task_review.id,
                relation_type="derived_from_task_review",
            ),
            *[
                MemoryRelation(
                    from_memory_id=item.id,
                    to_source_id=artifact_id,
                    relation_type="derived_from_artifact",
                )
                for artifact_id in task_review.artifact_ids
            ],
        ]
        audit = AuditEvent(
            actor=user.id,
            action="capture_memory_from_task_review",
            target_type="memory",
            target_id=item.id,
            workspace_id=user.workspace_id,
            project_id=thread.project_id,
            metadata={
                "source_task_review_id": task_review.id,
                "target": entry.kind.value,
                "memory_version": item.version,
            },
            created_at=now,
        )
        receipt = MemoryGovernanceCommandReceiptV1(
            id=receipt_id,
            command_id=request.command_id,
            user_id=user.id,
            operation="capture",
            request_hash=request_hash,
            memory_id=item.id,
            result_entry=entry,
            result_review=memory_review,
            created_at=now,
        )
        try:
            result = self.repository.capture_memory_from_task_review(
                item=item,
                memory_review=memory_review,
                inbox=inbox,
                relations=relations,
                audit=audit,
                receipt=receipt,
                authorization=MemoryGovernanceAuthorizationV1(
                    actor_id=user.id,
                    workspace_id=user.workspace_id,
                    project_id=thread.project_id,
                ),
            )
        except MemoryGovernanceConflict as error:
            raise MemoryGovernanceError(error.code, status_code=self._status_for_error(error.code)) from error
        return MemoryCaptureResponseV1(
            item=self.entry_view(result.item, user),
            memory_review=self._review_view(result.review, user) if result.review is not None else None,
        )

    def decide_memory_review(
        self,
        review_id: str,
        request: MemoryReviewDecisionRequest,
        user: User,
    ) -> MemoryReviewDecisionResponseV1:
        request_hash = canonical_json_sha256(
            {"memory_review_id": review_id, "request": request.model_dump(mode="json")}
        )
        receipt_id = self._receipt_id(user.id, request.command_id)
        existing = self._get_receipt(receipt_id)
        if existing is not None:
            self._validate_replay(existing, "review_decision", request_hash)
            self._require_entry_visible(existing.result_entry, user)
            assert existing.result_review is not None
            return MemoryReviewDecisionResponseV1(
                item=existing.result_entry,
                memory_review=self._review_view(existing.result_review, user),
            )
        self._require_write_mode()
        try:
            current_review = self.repository.get_memory_review(review_id)
        except MemoryGovernanceConflict as error:
            raise MemoryGovernanceError(error.code) from error
        if current_review is None:
            raise MemoryGovernanceError("memory_review_not_found", status_code=404)
        item = self.repository.get_memory_item(current_review.memory_id)
        if item is None:
            raise MemoryGovernanceError("memory_review_not_found", status_code=404)
        self._require_entry_visible(self.entry_view(item, user), user)
        if current_review.reviewer_id != user.id or not has_permission(
            user,
            ACTION_ACCEPT_TEAM_MEMORY,
            self.repository.permission_policy_rules,
        ):
            raise MemoryGovernanceError("memory_review_not_found", status_code=404)
        if current_review.version != request.expected_review_version:
            raise MemoryGovernanceError("memory_review_version_conflict")
        if item.version != request.expected_memory_version:
            raise MemoryGovernanceError("memory_version_conflict")
        if current_review.status is not MemoryReviewStatus.PENDING:
            raise MemoryGovernanceError("memory_review_already_decided")
        now = now_utc()
        decision = MemoryReviewStatus(request.decision)
        decided_review = MemoryReviewV1.model_validate(
            current_review.model_copy(
                update={
                    "status": decision,
                    "decision_note": request.decision_note,
                    "version": current_review.version + 1,
                    "updated_at": now,
                    "decided_at": now,
                }
            ).model_dump()
        )
        expected_item = item.model_copy(deep=True)
        expected_item.version += 1
        expected_item.updated_at = now
        if decision is MemoryReviewStatus.ACCEPTED:
            expected_item.status = MemoryStatus.ACCEPTED
            expected_item.scope = Scope.TEAM_ACCEPTED
        else:
            expected_item.status = MemoryStatus.DISPUTED
        entry = self.entry_view(expected_item, user)
        audit = AuditEvent(
            actor=user.id,
            action="decide_memory_review",
            target_type="memory_review",
            target_id=decided_review.id,
            workspace_id=item.workspace_id,
            project_id=item.project_id,
            metadata={
                "memory_id": item.id,
                "source_task_review_id": current_review.source_task_review_id,
                "decision": decision.value,
                "memory_version": expected_item.version,
                "memory_review_version": decided_review.version,
            },
            created_at=now,
        )
        receipt = MemoryGovernanceCommandReceiptV1(
            id=receipt_id,
            command_id=request.command_id,
            user_id=user.id,
            operation="review_decision",
            request_hash=request_hash,
            memory_id=item.id,
            result_entry=entry,
            result_review=decided_review,
            created_at=now,
        )
        try:
            result = self.repository.decide_memory_review(
                review=decided_review,
                expected_memory_version=request.expected_memory_version,
                expected_review_version=request.expected_review_version,
                audit=audit,
                receipt=receipt,
                authorization=MemoryGovernanceAuthorizationV1(
                    actor_id=user.id,
                    workspace_id=item.workspace_id or user.workspace_id,
                    project_id=item.project_id or user.default_project_id,
                ),
            )
        except MemoryGovernanceConflict as error:
            raise MemoryGovernanceError(error.code, status_code=self._status_for_error(error.code)) from error
        return MemoryReviewDecisionResponseV1(
            item=self.entry_view(result.item, user),
            memory_review=self._review_view(result.review, user),
        )

    def list_entries(self, query: MemoryListQuery, user: User) -> MemoryPageV1:
        project = self.repository.get_project(query.project_id)
        if (
            project is None
            or project.workspace_id != user.workspace_id
            or not self.repository.user_can_access_project(user.id, project.id)
        ):
            raise MemoryGovernanceError("memory_not_found", status_code=404)
        entries = [
            self.entry_view(item, user)
            for item in self.repository.user_memory_items
            if item.user_id == user.id
            and item.project_id == project.id
            and (query.include_archived or item.status != "archived")
        ]
        entries.extend(
            self.entry_view(item, user)
            for item in self.repository.memory_items
            if item.project_id == project.id
            and self._shared_visible(item, user)
            and (query.include_archived or item.status is not MemoryStatus.ARCHIVED)
        )
        entries.sort(key=lambda item: (item.updated_at, item.id), reverse=True)
        start = (query.page - 1) * query.page_size
        end = start + query.page_size
        return MemoryPageV1(
            items=entries[start:end],
            total=len(entries),
            page=query.page,
            page_size=query.page_size,
            has_next=end < len(entries),
        )

    def get_lineage(self, memory_id: str, user: User) -> MemoryLineageViewV1:
        item = self.repository.get_user_memory_item(memory_id)
        if item is None:
            item = self.repository.get_memory_item(memory_id)
        if item is None:
            raise MemoryGovernanceError("memory_not_found", status_code=404)
        entry = self.entry_view(item, user)
        self._require_entry_visible(entry, user)
        provenance = entry.provenance
        memory_review = self.repository.get_memory_review_for_memory(entry.id)
        return MemoryLineageViewV1(
            item=entry,
            task_id=provenance.task_id if provenance is not None else None,
            run_id=provenance.run_id if provenance is not None else None,
            task_review_id=provenance.review_id if provenance is not None else None,
            artifact_ids=list(provenance.artifact_ids) if provenance is not None else [],
            artifact_hashes=list(provenance.artifact_hashes) if provenance is not None else [],
            source_memory_ids=list(provenance.source_memory_ids) if provenance is not None else [],
            superseded_by_memory_ids=[
                candidate.id
                for candidate in self.repository.memory_items
                if candidate.supersedes_memory_id == entry.id
            ],
            memory_reviews=[self._review_view(memory_review, user)] if memory_review is not None else [],
        )

    def task_memory_links(self, task_id: str, user: User) -> list[TaskMemoryLinkV1]:
        entries: list[MemoryEntryViewV1] = []
        entries.extend(
            self.entry_view(item, user)
            for item in self.repository.list_user_memory_items_for_task(task_id, user.id)
        )
        entries.extend(
            self.entry_view(item, user)
            for item in self.repository.list_memory_items_for_task(task_id)
            if self._shared_visible(item, user)
        )
        return [
            TaskMemoryLinkV1(
                id=entry.id,
                kind=entry.kind,
                title=entry.title,
                status=entry.status,
                version=entry.version,
                navigation_href=f"/knowledge?memory={quote(entry.id, safe='')}",
                source_review_id=entry.provenance.review_id,
            )
            for entry in entries
            if entry.provenance is not None and entry.provenance.review_id is not None
        ]

    def entry_view(self, item: MemoryItem | UserMemoryItem, user: User) -> MemoryEntryViewV1:
        if isinstance(item, UserMemoryItem):
            return MemoryEntryViewV1(
                id=item.id,
                kind=MemoryEntryKind.PERSONAL,
                title=item.title,
                summary=item.summary,
                memory_type=item.memory_type,
                scope=item.scope,
                status=item.status,
                owner_user_id=item.user_id,
                workspace_id=item.workspace_id,
                project_id=item.project_id,
                team_id=None,
                layer=item.layer,
                version=item.version,
                provenance=item.provenance,
                provenance_state="verified" if item.provenance is not None else "legacy_unverified",
                supersedes_memory_id=item.supersedes_memory_id,
                archived_at=item.archived_at,
                archived_by=item.archived_by,
                created_at=item.created_at,
                updated_at=item.updated_at,
                navigation_href=f"/knowledge?memory={quote(item.id, safe='')}",
            )
        kind = (
            MemoryEntryKind.TEAM_CANDIDATE
            if item.scope is Scope.TEAM_CANDIDATE
            else MemoryEntryKind.TEAM_KNOWLEDGE
            if item.scope is Scope.TEAM_ACCEPTED
            else MemoryEntryKind.LEGACY_SHARED
        )
        actions: list[str] = []
        review = self.repository.get_memory_review_for_memory(item.id)
        if (
            review is not None
            and review.status is MemoryReviewStatus.PENDING
            and review.reviewer_id == user.id
            and has_permission(user, ACTION_ACCEPT_TEAM_MEMORY, self.repository.permission_policy_rules)
            and task_management_mode() is TaskManagementMode.WRITE
        ):
            actions.extend([MemoryReviewAllowedAction.ACCEPT.value, MemoryReviewAllowedAction.REJECT.value])
        return MemoryEntryViewV1(
            id=item.id,
            kind=kind,
            title=item.title,
            summary=item.summary,
            memory_type=item.memory_type,
            scope=item.scope,
            status=item.status.value,
            owner_user_id=item.owner_user_id,
            workspace_id=item.workspace_id or user.workspace_id,
            project_id=item.project_id,
            team_id=item.team_id,
            version=item.version,
            provenance=item.provenance,
            provenance_state="verified" if item.provenance is not None else "legacy_unverified",
            supersedes_memory_id=item.supersedes_memory_id,
            archived_at=item.archived_at,
            archived_by=item.archived_by,
            created_at=item.created_at,
            updated_at=item.updated_at or item.created_at,
            allowed_actions=actions,
            navigation_href=f"/knowledge?memory={quote(item.id, safe='')}",
        )

    def _review_view(self, review: MemoryReviewV1 | None, user: User) -> MemoryReviewViewV1:
        if review is None:
            raise MemoryGovernanceError("memory_review_not_found", status_code=404)
        actions = []
        if (
            review.status is MemoryReviewStatus.PENDING
            and review.reviewer_id == user.id
            and has_permission(user, ACTION_ACCEPT_TEAM_MEMORY, self.repository.permission_policy_rules)
            and task_management_mode() is TaskManagementMode.WRITE
        ):
            actions = [MemoryReviewAllowedAction.ACCEPT, MemoryReviewAllowedAction.REJECT]
        return MemoryReviewViewV1(review=review, allowed_actions=actions)

    def _shared_visible(self, item: MemoryItem, user: User) -> bool:
        if not self.repository.memory_item_visible_to_user(item, user.id):
            return False
        if item.workspace_id != user.workspace_id:
            return False
        if item.project_id is not None and not self.repository.user_can_access_project(user.id, item.project_id):
            return False
        if item.scope is Scope.TEAM_CANDIDATE:
            return item.owner_user_id == user.id or has_permission(
                user,
                ACTION_ACCEPT_TEAM_MEMORY,
                self.repository.permission_policy_rules,
            )
        return item.scope in {Scope.PROJECT, Scope.TEAM_ACCEPTED}

    def _require_entry_visible(self, entry: MemoryEntryViewV1, user: User) -> None:
        if entry.workspace_id != user.workspace_id:
            raise MemoryGovernanceError("memory_not_found", status_code=404)
        if entry.project_id is not None and not self.repository.user_can_access_project(user.id, entry.project_id):
            raise MemoryGovernanceError("memory_not_found", status_code=404)
        if entry.kind is MemoryEntryKind.PERSONAL and entry.owner_user_id != user.id:
            raise MemoryGovernanceError("memory_not_found", status_code=404)
        if entry.kind is not MemoryEntryKind.PERSONAL:
            item = self.repository.get_memory_item(entry.id)
            if item is None or not self.repository.memory_item_visible_to_user(item, user.id):
                raise MemoryGovernanceError("memory_not_found", status_code=404)
        if entry.kind is MemoryEntryKind.TEAM_CANDIDATE and (
            entry.owner_user_id != user.id
            and not has_permission(user, ACTION_ACCEPT_TEAM_MEMORY, self.repository.permission_policy_rules)
        ):
            raise MemoryGovernanceError("memory_not_found", status_code=404)

    def _get_receipt(self, receipt_id: str) -> MemoryGovernanceCommandReceiptV1 | None:
        try:
            return self.repository.get_memory_governance_receipt(receipt_id)
        except MemoryGovernanceConflict as error:
            raise MemoryGovernanceError(error.code) from error

    def _task_view(self, task_id: str, user: User) -> TaskManagementViewV1:
        try:
            return self.task_service.get_task(task_id, user)
        except TaskManagementError as error:
            raise MemoryGovernanceError(error.code, status_code=error.status_code) from error

    @staticmethod
    def _validate_replay(
        receipt: MemoryGovernanceCommandReceiptV1,
        operation: str,
        request_hash: str,
    ) -> None:
        if receipt.operation != operation or receipt.request_hash != request_hash:
            raise MemoryGovernanceError("memory_governance_command_conflict")

    @staticmethod
    def _receipt_id(user_id: str, command_id: str) -> str:
        digest = canonical_json_sha256({"user_id": user_id, "command_id": command_id})[:24]
        return f"memory_governance_command_{digest}"

    @staticmethod
    def _status_for_error(code: str) -> int:
        if code in {"memory_not_found", "memory_review_not_found", "memory_source_review_not_found"}:
            return 404
        if code in {"memory_capture_forbidden", "memory_reviewer_forbidden"}:
            return 403
        return 409

    @staticmethod
    def _require_write_mode() -> None:
        if task_management_mode() is not TaskManagementMode.WRITE:
            raise MemoryGovernanceError("task_management_read_only")
