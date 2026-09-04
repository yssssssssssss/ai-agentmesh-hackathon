from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.memory_context.service import MemoryContextService
from agentmesh.memory_governance.contracts import (
    MemoryCaptureResponseV1,
    MemoryCaptureTarget,
    MemoryEntryKind,
    MemoryEntryViewV1,
    MemoryGovernanceAllowedAction,
    MemoryGovernanceAuthorizationV1,
    MemoryGovernanceCommandReceiptV1,
    MemoryGovernanceEventV1,
    MemoryLineageViewV1,
    MemoryPageV1,
    MemoryReviewAllowedAction,
    MemoryReviewDecisionRequest,
    MemoryReviewDecisionResponseV1,
    MemoryReviewViewV1,
    MemoryRevisionLinkV1,
    MemoryRevisionRequest,
    MemoryRevisionResponseV1,
    MemoryTransitionRequest,
    MemoryTransitionResponseV1,
    TaskMemoryLinkV1,
    TaskReviewMemoryCaptureRequest,
)
from agentmesh.memory_governance.lifecycle import (
    MemoryLifecycleConflict,
    memory_content_hash,
    transition_memory_item,
)
from agentmesh.models import (
    AuditEvent,
    InboxItem,
    MemoryItem,
    MemoryLayer,
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
from agentmesh.permissions import (
    ACTION_ACCEPT_TEAM_MEMORY,
    ACTION_MANAGE_TEAM_MEMORY,
    has_permission,
)
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
    inactive_only: bool = False
    kind: MemoryEntryKind | None = None
    status: str | None = None
    scope: Scope | None = None
    layer: MemoryLayer | None = None


class MemoryGovernanceService:
    def __init__(self, repository: SQLiteStore):
        self.repository = repository
        self.task_service = TaskManagementService(repository)
        self.memory_context = MemoryContextService(repository)

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
                layer=(
                    request.layer
                    if "layer" in request.model_fields_set
                    else MemoryLayer.LONG_TERM
                ),
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
            item=result.receipt.result_entry,
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
        audit_metadata: dict[str, object] = {
            "memory_id": item.id,
            "source_task_review_id": current_review.source_task_review_id,
            "decision": decision.value,
            "memory_version": expected_item.version,
            "memory_review_version": decided_review.version,
        }
        if (
            item.provenance is not None
            and item.provenance.source_kind is MemorySourceKind.MEMORY_REVISION
            and item.supersedes_memory_id is not None
        ):
            audit_metadata.update(
                {
                    "source_memory_id": item.supersedes_memory_id,
                    "source_memory_version": item.provenance.source_memory_versions[0],
                    "source_memory_hash": item.provenance.source_memory_hashes[0],
                }
            )
        audit = AuditEvent(
            actor=user.id,
            action="decide_memory_review",
            target_type="memory_review",
            target_id=decided_review.id,
            workspace_id=item.workspace_id,
            project_id=item.project_id,
            metadata=audit_metadata,
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
            item=result.receipt.result_entry,
            memory_review=self._review_view(result.review, user),
        )

    def create_revision(
        self,
        memory_id: str,
        request: MemoryRevisionRequest,
        user: User,
    ) -> MemoryRevisionResponseV1:
        request_hash = canonical_json_sha256(
            {"memory_id": memory_id, "request": request.model_dump(mode="json")}
        )
        receipt_id = self._receipt_id(user.id, request.command_id)
        existing = self._get_receipt(receipt_id)
        if existing is not None:
            self._validate_replay(existing, "revision", request_hash)
            self._require_entry_visible(existing.result_entry, user)
            assert existing.result_review is not None
            return MemoryRevisionResponseV1(
                item=existing.result_entry,
                memory_review=self._review_view(existing.result_review, user),
            )
        self._require_write_mode()
        source = self.repository.get_memory_item(memory_id)
        if source is None:
            raise MemoryGovernanceError("memory_not_found", status_code=404)
        source_entry = self.entry_view(source, user)
        self._require_entry_visible(source_entry, user)
        if source.provenance is None or source.scope is not Scope.TEAM_ACCEPTED:
            raise MemoryGovernanceError("memory_governance_required")
        if source.status not in {
            MemoryStatus.ACCEPTED,
            MemoryStatus.DISPUTED,
            MemoryStatus.DEPRECATED,
            MemoryStatus.EXPIRED,
        }:
            raise MemoryGovernanceError("memory_revision_source_invalid")
        if source.version != request.expected_version:
            raise MemoryGovernanceError("memory_version_conflict")
        if source.owner_user_id != user.id and not self._can_manage_team_memory(user):
            raise MemoryGovernanceError("memory_revision_forbidden", status_code=403)
        if (
            request.title == source.title
            and request.summary == source.summary
            and request.memory_type == source.memory_type
        ):
            raise MemoryGovernanceError("memory_revision_no_changes")
        if source.project_id is None or source.provenance.review_id is None:
            raise MemoryGovernanceError("memory_governance_required")
        reviewer = self.repository.select_memory_reviewer(project_id=source.project_id, owner_id=user.id)
        if reviewer is None:
            raise MemoryGovernanceError("memory_reviewer_unavailable")
        now = now_utc()
        provenance = MemoryProvenanceV1(
            source_kind=MemorySourceKind.MEMORY_REVISION,
            task_id=source.provenance.task_id,
            run_id=source.provenance.run_id,
            review_id=source.provenance.review_id,
            artifact_ids=list(source.provenance.artifact_ids),
            artifact_hashes=list(source.provenance.artifact_hashes),
            source_memory_ids=[source.id],
            source_memory_versions=[source.version],
            source_memory_hashes=[memory_content_hash(source)],
            created_by=user.id,
            created_at=now,
        )
        item = MemoryItem(
            title=request.title,
            summary=request.summary,
            memory_type=request.memory_type,
            scope=Scope.TEAM_CANDIDATE,
            layer=source.layer or MemoryLayer.LONG_TERM,
            status=MemoryStatus.PROPOSED,
            owner_user_id=user.id,
            workspace_id=source.workspace_id,
            project_id=source.project_id,
            team_id=source.team_id,
            sources=list(source.sources),
            metadata=dict(source.metadata),
            provenance=provenance,
            supersedes_memory_id=source.id,
            created_at=now,
            updated_at=now,
        )
        memory_review = MemoryReviewV1(
            memory_id=item.id,
            source_task_review_id=source.provenance.review_id,
            requested_by=user.id,
            reviewer_id=reviewer.id,
            memory_version=item.version,
            created_at=now,
            updated_at=now,
        )
        inbox = InboxItem(
            title=f"审核团队记忆修订：{item.title}",
            summary="该候选修订会在接受后替代上一版团队知识。",
            item_type="memory_review",
            scope=Scope.PRIVATE,
            user_id=reviewer.id,
            workspace_id=source.workspace_id,
            project_id=source.project_id,
            metadata={
                "memory_review_id": memory_review.id,
                "memory_id": item.id,
                "source_memory_id": source.id,
                "task_review_id": source.provenance.review_id,
            },
            created_at=now,
            updated_at=now,
        )
        relations = [
            MemoryRelation(
                from_memory_id=item.id,
                to_source_id=source.id,
                relation_type="supersedes",
            ),
            MemoryRelation(
                from_memory_id=item.id,
                to_source_id=source.id,
                relation_type="derived_from_memory",
            ),
        ]
        entry = self.entry_view(item, user)
        audit = AuditEvent(
            actor=user.id,
            action="create_memory_revision",
            target_type="memory",
            target_id=item.id,
            workspace_id=source.workspace_id,
            project_id=source.project_id,
            metadata={
                "source_memory_id": source.id,
                "source_memory_version": source.version,
                "source_memory_hash": memory_content_hash(source),
                "memory_version": item.version,
            },
            created_at=now,
        )
        receipt = MemoryGovernanceCommandReceiptV1(
            id=receipt_id,
            command_id=request.command_id,
            user_id=user.id,
            operation="revision",
            request_hash=request_hash,
            memory_id=item.id,
            result_entry=entry,
            result_review=memory_review,
            created_at=now,
        )
        try:
            result = self.repository.create_memory_revision(
                source_memory_id=source.id,
                expected_source_version=request.expected_version,
                item=item,
                memory_review=memory_review,
                inbox=inbox,
                relations=relations,
                audit=audit,
                receipt=receipt,
                authorization=MemoryGovernanceAuthorizationV1(
                    actor_id=user.id,
                    workspace_id=source.workspace_id or user.workspace_id,
                    project_id=source.project_id,
                ),
            )
        except MemoryGovernanceConflict as error:
            raise MemoryGovernanceError(error.code, status_code=self._status_for_error(error.code)) from error
        return MemoryRevisionResponseV1(
            item=result.receipt.result_entry,
            memory_review=self._review_view(result.review, user),
        )

    def transition_memory(
        self,
        memory_id: str,
        request: MemoryTransitionRequest,
        user: User,
    ) -> MemoryTransitionResponseV1:
        request_hash = canonical_json_sha256(
            {"memory_id": memory_id, "request": request.model_dump(mode="json")}
        )
        receipt_id = self._receipt_id(user.id, request.command_id)
        existing = self._get_receipt(receipt_id)
        if existing is not None:
            self._validate_replay(existing, "transition", request_hash)
            self._require_entry_visible(existing.result_entry, user)
            return MemoryTransitionResponseV1(item=existing.result_entry)
        self._require_write_mode()
        item = self.repository.get_memory_item(memory_id)
        if item is None:
            raise MemoryGovernanceError("memory_not_found", status_code=404)
        self._require_entry_visible(self.entry_view(item, user), user)
        if not self._can_manage_team_memory(user):
            raise MemoryGovernanceError("memory_lifecycle_forbidden", status_code=403)
        if item.version != request.expected_version:
            raise MemoryGovernanceError("memory_version_conflict")
        now = now_utc()
        try:
            updated = transition_memory_item(
                item,
                action=request.action,
                actor_id=user.id,
                changed_at=now,
            )
        except MemoryLifecycleConflict as error:
            raise MemoryGovernanceError(error.code) from error
        entry = self.entry_view(updated, user)
        audit = AuditEvent(
            actor=user.id,
            action=f"transition_memory_{request.action.value}",
            target_type="memory",
            target_id=item.id,
            workspace_id=item.workspace_id,
            project_id=item.project_id,
            metadata={
                "from_status": item.status.value,
                "to_status": updated.status.value,
                "from_version": item.version,
                "memory_version": updated.version,
            },
            created_at=now,
        )
        receipt = MemoryGovernanceCommandReceiptV1(
            id=receipt_id,
            command_id=request.command_id,
            user_id=user.id,
            operation="transition",
            request_hash=request_hash,
            memory_id=item.id,
            result_entry=entry,
            created_at=now,
        )
        try:
            result = self.repository.transition_memory(
                memory_id=item.id,
                expected_version=request.expected_version,
                action=request.action,
                updated_item=updated,
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
        return MemoryTransitionResponseV1(item=result.receipt.result_entry)

    def list_entries(self, query: MemoryListQuery, user: User) -> MemoryPageV1:
        project = self.repository.get_project(query.project_id)
        if (
            project is None
            or project.workspace_id != user.workspace_id
            or not self.repository.user_can_access_project(user.id, project.id)
        ):
            raise MemoryGovernanceError("memory_not_found", status_code=404)
        personal_items = [
            item
            for item in self.repository.user_memory_items
            if item.user_id == user.id and item.project_id == project.id
        ]
        project_memory_items = [
            item for item in self.repository.memory_items if item.project_id == project.id
        ]
        shared_items = [item for item in project_memory_items if self._shared_visible(item, user)]
        active_successor_ids = {
            item.supersedes_memory_id
            for item in project_memory_items
            if item.supersedes_memory_id is not None
            and (
                item.status is MemoryStatus.PROPOSED
                or (item.status is MemoryStatus.ACCEPTED and item.scope is Scope.TEAM_ACCEPTED)
            )
        }
        entries = [self.entry_view(item, user) for item in personal_items]
        entries.extend(
            self.entry_view(item, user, active_successor_ids=active_successor_ids)
            for item in shared_items
        )
        entries = [
            entry
            for entry in entries
            if (query.include_archived or entry.status != MemoryStatus.ARCHIVED.value)
            and (
                not query.inactive_only
                or entry.status
                in {
                    MemoryStatus.DISPUTED.value,
                    MemoryStatus.DEPRECATED.value,
                    MemoryStatus.EXPIRED.value,
                    MemoryStatus.ARCHIVED.value,
                }
            )
            and (query.kind is None or entry.kind is query.kind)
            and (query.status is None or entry.status == query.status)
            and (query.scope is None or entry.scope is query.scope)
            and (query.layer is None or entry.layer is query.layer)
        ]
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
        source_items = []
        for source_id in provenance.source_memory_ids if provenance is not None else []:
            source_item = self.repository.get_memory_item(source_id)
            if source_item is not None and self._shared_visible(source_item, user):
                source_items.append(source_item)
        successor_items = [
            candidate
            for candidate in self.repository.memory_items
            if candidate.supersedes_memory_id == entry.id and self._shared_visible(candidate, user)
        ]
        review_ids = {memory_review.id} if memory_review is not None else set()
        governance_events = []
        for event in self.repository.audit_events:
            if event.workspace_id != entry.workspace_id or event.project_id != entry.project_id:
                continue
            related_memory_id = (
                event.metadata.get("memory_id")
                if isinstance(event.metadata.get("memory_id"), str)
                else event.target_id
                if event.target_type == "memory"
                else None
            )
            related_item = (
                self.repository.get_memory_item(related_memory_id)
                if related_memory_id is not None
                else None
            )
            if related_item is not None and not self._shared_visible(related_item, user):
                continue
            if not (
                event.target_id == entry.id
                or event.target_id in review_ids
                or event.metadata.get("memory_id") == entry.id
                or event.metadata.get("source_memory_id") == entry.id
            ):
                continue
            governance_events.append(
                MemoryGovernanceEventV1(
                    id=event.id,
                    action=event.action,
                    actor=event.actor,
                    created_at=event.created_at,
                    metadata=dict(event.metadata),
                )
            )
        governance_events.sort(key=lambda event: (event.created_at, event.id))
        return MemoryLineageViewV1(
            item=entry,
            task_id=provenance.task_id if provenance is not None else None,
            run_id=provenance.run_id if provenance is not None else None,
            task_review_id=provenance.review_id if provenance is not None else None,
            artifact_ids=list(provenance.artifact_ids) if provenance is not None else [],
            artifact_hashes=list(provenance.artifact_hashes) if provenance is not None else [],
            source_memory_ids=[item.id for item in source_items],
            source_memories=[self._revision_link(item) for item in source_items],
            superseded_by_memory_ids=[item.id for item in successor_items],
            superseded_by_memories=[self._revision_link(item) for item in successor_items],
            memory_reviews=[self._review_view(memory_review, user)] if memory_review is not None else [],
            governance_events=governance_events,
            usage=self.memory_context.usage_backlinks(entry.id, user),
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
        return self._memory_links(entries)

    def run_memory_links(self, run_id: str, user: User) -> list[TaskMemoryLinkV1]:
        run = self.repository.get_agent_run(run_id)
        if (
            run is None
            or run.user_id != user.id
            or run.workspace_id != user.workspace_id
            or not self.repository.user_can_execute_agent_run(user.id, run.id)
        ):
            raise MemoryGovernanceError("agent_run_not_found", status_code=404)
        entries = [
            self.entry_view(item, user)
            for item in self.repository.user_memory_items
            if item.user_id == user.id
            and item.provenance is not None
            and item.provenance.run_id == run.id
        ]
        entries.extend(
            self.entry_view(item, user)
            for item in self.repository.memory_items
            if item.provenance is not None
            and item.provenance.run_id == run.id
            and self._shared_visible(item, user)
        )
        return self._memory_links(entries)

    def artifact_memory_links(self, artifact_id: str, user: User) -> list[TaskMemoryLinkV1]:
        artifact = self.repository.get_artifact(artifact_id)
        run = self.repository.get_agent_run(artifact.run_id) if artifact is not None else None
        if (
            artifact is None
            or run is None
            or run.user_id != user.id
            or run.workspace_id != user.workspace_id
            or not self.repository.user_can_execute_agent_run(user.id, run.id)
        ):
            raise MemoryGovernanceError("artifact_not_found", status_code=404)
        entries = [
            self.entry_view(item, user)
            for item in self.repository.user_memory_items
            if item.user_id == user.id
            and item.provenance is not None
            and artifact.id in item.provenance.artifact_ids
        ]
        entries.extend(
            self.entry_view(item, user)
            for item in self.repository.memory_items
            if item.provenance is not None
            and artifact.id in item.provenance.artifact_ids
            and self._shared_visible(item, user)
        )
        return self._memory_links(entries)

    @staticmethod
    def _memory_links(entries: list[MemoryEntryViewV1]) -> list[TaskMemoryLinkV1]:
        entries.sort(key=lambda entry: (entry.updated_at, entry.id), reverse=True)
        return [
            TaskMemoryLinkV1(
                id=entry.id,
                kind=entry.kind,
                title=entry.title,
                status=entry.status,
                version=entry.version,
                navigation_href=MemoryGovernanceService._navigation_href(entry.id, entry.project_id),
                source_review_id=entry.provenance.review_id,
            )
            for entry in entries
            if entry.provenance is not None and entry.provenance.review_id is not None
        ]

    def entry_view(
        self,
        item: MemoryItem | UserMemoryItem,
        user: User,
        *,
        active_successor_ids: set[str] | None = None,
    ) -> MemoryEntryViewV1:
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
                content_hash=memory_content_hash(item),
                provenance=item.provenance,
                provenance_state="verified" if item.provenance is not None else "legacy_unverified",
                supersedes_memory_id=item.supersedes_memory_id,
                archived_at=item.archived_at,
                archived_by=item.archived_by,
                archived_from_status=None,
                created_at=item.created_at,
                updated_at=item.updated_at,
                navigation_href=self._navigation_href(item.id, item.project_id),
            )
        kind = (
            MemoryEntryKind.TEAM_CANDIDATE
            if item.scope is Scope.TEAM_CANDIDATE
            else MemoryEntryKind.TEAM_KNOWLEDGE
            if item.scope is Scope.TEAM_ACCEPTED
            else MemoryEntryKind.LEGACY_SHARED
        )
        review = self.repository.get_memory_review_for_memory(item.id)
        actions = self._allowed_actions(
            item,
            review,
            user,
            active_successor_ids=active_successor_ids,
        )
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
            layer=(
                item.layer
                or (
                    MemoryLayer.LONG_TERM
                    if item.scope in {Scope.TEAM_CANDIDATE, Scope.TEAM_ACCEPTED}
                    else MemoryLayer.MID_TERM
                )
            ),
            version=item.version,
            content_hash=memory_content_hash(item),
            provenance=item.provenance,
            provenance_state="verified" if item.provenance is not None else "legacy_unverified",
            supersedes_memory_id=item.supersedes_memory_id,
            archived_at=item.archived_at,
            archived_by=item.archived_by,
            archived_from_status=item.archived_from_status,
            created_at=item.created_at,
            updated_at=item.updated_at or item.created_at,
            allowed_actions=actions,
            memory_review=review,
            navigation_href=self._navigation_href(item.id, item.project_id),
        )

    def _allowed_actions(
        self,
        item: MemoryItem,
        review: MemoryReviewV1 | None,
        user: User,
        *,
        active_successor_ids: set[str] | None = None,
    ) -> list[str]:
        if item.provenance is None:
            if (
                item.status is MemoryStatus.PROPOSED
                and item.scope is Scope.TEAM_CANDIDATE
                and has_permission(user, ACTION_ACCEPT_TEAM_MEMORY, self.repository.permission_policy_rules)
            ):
                return [MemoryReviewAllowedAction.ACCEPT.value]
            return []
        if task_management_mode() is not TaskManagementMode.WRITE:
            return []
        actions: list[str] = []
        if (
            review is not None
            and review.status is MemoryReviewStatus.PENDING
            and review.reviewer_id == user.id
            and has_permission(user, ACTION_ACCEPT_TEAM_MEMORY, self.repository.permission_policy_rules)
        ):
            actions.extend(["accept_review", "reject_review"])
        can_manage = self._can_manage_team_memory(user)
        can_revise = item.owner_user_id == user.id or can_manage
        if active_successor_ids is None:
            active_successor_ids = {
                candidate.supersedes_memory_id
                for candidate in self.repository.memory_items
                if candidate.supersedes_memory_id is not None
                and (
                    candidate.status is MemoryStatus.PROPOSED
                    or (
                        candidate.status is MemoryStatus.ACCEPTED
                        and candidate.scope is Scope.TEAM_ACCEPTED
                    )
                )
            }
        if (
            can_revise
            and item.scope is Scope.TEAM_ACCEPTED
            and item.status
            in {
                MemoryStatus.ACCEPTED,
                MemoryStatus.DISPUTED,
                MemoryStatus.DEPRECATED,
                MemoryStatus.EXPIRED,
            }
            and item.id not in active_successor_ids
        ):
            actions.append(MemoryGovernanceAllowedAction.REVISE.value)
        if not can_manage:
            return actions
        lifecycle_actions = {
            MemoryStatus.PROPOSED: [MemoryGovernanceAllowedAction.EXPIRE],
            MemoryStatus.ACCEPTED: [
                MemoryGovernanceAllowedAction.DISPUTE,
                MemoryGovernanceAllowedAction.DEPRECATE,
                MemoryGovernanceAllowedAction.EXPIRE,
                MemoryGovernanceAllowedAction.ARCHIVE,
            ],
            MemoryStatus.DISPUTED: [
                MemoryGovernanceAllowedAction.DEPRECATE,
                MemoryGovernanceAllowedAction.EXPIRE,
                MemoryGovernanceAllowedAction.ARCHIVE,
            ],
            MemoryStatus.DEPRECATED: [MemoryGovernanceAllowedAction.ARCHIVE],
            MemoryStatus.EXPIRED: [MemoryGovernanceAllowedAction.ARCHIVE],
            MemoryStatus.ARCHIVED: (
                []
                if item.archived_from_status is MemoryStatus.ACCEPTED
                and item.supersedes_memory_id is not None
                and item.supersedes_memory_id in active_successor_ids
                else [MemoryGovernanceAllowedAction.RESTORE]
            ),
        }
        actions.extend(action.value for action in lifecycle_actions.get(item.status, []))
        return actions

    @staticmethod
    def _revision_link(item: MemoryItem) -> MemoryRevisionLinkV1:
        return MemoryRevisionLinkV1(
            id=item.id,
            title=item.title,
            status=item.status.value,
            scope=item.scope,
            version=item.version,
            content_hash=memory_content_hash(item),
            navigation_href=MemoryGovernanceService._navigation_href(item.id, item.project_id),
        )

    @staticmethod
    def _navigation_href(memory_id: str, project_id: str | None) -> str:
        memory_query = f"memory={quote(memory_id, safe='')}"
        if project_id is None:
            return f"/knowledge?{memory_query}"
        return f"/knowledge?project={quote(project_id, safe='')}&{memory_query}"

    def _can_manage_team_memory(self, user: User) -> bool:
        return has_permission(
            user,
            ACTION_MANAGE_TEAM_MEMORY,
            self.repository.permission_policy_rules,
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
            return item.owner_user_id == user.id or any(
                has_permission(user, action, self.repository.permission_policy_rules)
                for action in (ACTION_ACCEPT_TEAM_MEMORY, ACTION_MANAGE_TEAM_MEMORY)
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
            and not any(
                has_permission(user, action, self.repository.permission_policy_rules)
                for action in (ACTION_ACCEPT_TEAM_MEMORY, ACTION_MANAGE_TEAM_MEMORY)
            )
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
        if code in {
            "agent_run_not_found",
            "artifact_not_found",
            "memory_not_found",
            "memory_review_not_found",
            "memory_source_review_not_found",
        }:
            return 404
        if code in {
            "memory_capture_forbidden",
            "memory_lifecycle_forbidden",
            "memory_reviewer_forbidden",
            "memory_revision_forbidden",
        }:
            return 403
        return 409

    @staticmethod
    def _require_write_mode() -> None:
        if task_management_mode() is not TaskManagementMode.WRITE:
            raise MemoryGovernanceError("task_management_read_only")
