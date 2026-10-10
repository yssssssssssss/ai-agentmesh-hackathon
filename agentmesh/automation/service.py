from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from urllib.parse import quote

from agentmesh.automation.contracts import (
    InspectionBlockerV1,
    InspectionChangeV1,
    InspectionEvidenceRefV1,
    InspectionPendingReviewV1,
    InspectionRecommendationV1,
    InspectionSourceWatermarkV1,
    ProjectInspectionReportV1,
    ProjectInspectionRequestV1,
)
from agentmesh.models import MemoryReviewStatus, TaskDeliveryStage, TaskReviewStatus, User, now_utc
from agentmesh.store import (
    MemoryGovernanceConflict,
    ProjectInspectionRecords,
    SQLiteStore,
    TaskInspectionEvent,
    TaskOperationsProjectionRow,
    TaskReviewConflict,
)
from agentmesh.task_operations.graph import TaskGraph, TaskGraphError, TaskGraphRecord
from agentmesh.task_operations.service import TaskOperationsError


class ProjectInspectionService:
    def __init__(self, repository: SQLiteStore, *, clock: Callable[[], datetime] = now_utc):
        self.repository = repository
        self.clock = clock

    def inspect(self, project_id: str, request: ProjectInspectionRequestV1, user: User) -> ProjectInspectionReportV1:
        snapshot_at = self.clock()
        since = request.since or snapshot_at - timedelta(days=1)
        if since >= snapshot_at or snapshot_at - since > timedelta(days=366):
            raise TaskOperationsError("inspection_range_invalid", status_code=422)
        try:
            records = self.repository.read_project_inspection(
                user_id=user.id,
                workspace_id=user.workspace_id,
                project_id=project_id,
                include_history=request.template_id == "daily_progress",
            )
        except (TaskReviewConflict, MemoryGovernanceConflict) as error:
            raise TaskOperationsError(error.code) from error
        if records is None:
            raise TaskOperationsError("project_not_found", status_code=404)
        missing_data: list[str] = []
        if not records.tasks:
            missing_data.append("no_shared_project_tasks")
        if records.tasks_truncated:
            missing_data.append("project_task_limit_exceeded")
        if records.reviews_truncated:
            missing_data.append("project_review_limit_exceeded")
        blockers = (
            []
            if records.tasks_truncated or request.template_id == "pending_reviews"
            else self._blockers(
                records.tasks,
                snapshot_at,
                missing_data,
            )
        )
        changes = (
            self._changes(records, since, snapshot_at, missing_data) if request.template_id == "daily_progress" else []
        )
        reviews = self._pending_reviews(records, missing_data) if request.template_id != "blockers" else []
        evidence = list(
            {
                (ref.source_kind, ref.source_id, ref.version): ref
                for item in [*changes, *blockers, *reviews]
                for ref in item.evidence_refs
            }.values()
        )
        has_findings = bool(changes) if request.template_id == "daily_progress" else bool(blockers or reviews)
        return ProjectInspectionReportV1(
            project_id=project_id,
            template_id=request.template_id,
            snapshot_at=snapshot_at,
            since=since,
            outcome="insufficient_evidence" if missing_data else "completed" if has_findings else "no_change",
            source_watermarks={
                "tasks": InspectionSourceWatermarkV1(
                    record_count=len(records.tasks),
                    latest_updated_at=max((row.updated_at for row in records.tasks), default=None),
                ),
                "task_reviews": InspectionSourceWatermarkV1(
                    record_count=len(records.task_reviews),
                    latest_updated_at=max((review.updated_at for review in records.task_reviews), default=None),
                ),
                "memory_reviews": InspectionSourceWatermarkV1(
                    record_count=len(records.memory_reviews),
                    latest_updated_at=max((review.updated_at for review, _ in records.memory_reviews), default=None),
                ),
            },
            changes=changes,
            blockers=blockers,
            pending_reviews=reviews,
            missing_data=sorted(set(missing_data)),
            evidence_refs=evidence,
            recommendations=[
                InspectionRecommendationV1(
                    reason="请核对任务阻塞、依赖或截止日期；确认后在任务详情采取行动。",
                    navigation_href=item.navigation_href,
                    evidence_refs=item.evidence_refs,
                )
                for item in blockers
            ]
            + [
                InspectionRecommendationV1(
                    reason="请查看待审核材料；提交审核决定时会重新检查权限和版本。",
                    navigation_href=item.navigation_href,
                    evidence_refs=item.evidence_refs,
                )
                for item in reviews
                if item.assigned_to_me
            ],
        )

    @staticmethod
    def _pending_reviews(records: ProjectInspectionRecords, missing_data: list[str]) -> list[InspectionPendingReviewV1]:
        tasks = {row.task_id: row for row in records.tasks}
        result = []
        for review in records.task_reviews:
            task = tasks.get(review.task_id)
            if review.status is not TaskReviewStatus.PENDING or task is None or task.archived_at is not None:
                continue
            if task.version != review.task_version:
                missing_data.append("task_review_subject_changed")
            href = f"/tasks?task={quote(task.task_id, safe='')}"
            result.append(
                InspectionPendingReviewV1(
                    review_id=review.id,
                    kind="task_review",
                    subject_id=task.task_id,
                    title=task.title,
                    reviewer_id=review.reviewer_id,
                    assigned_to_me=review.reviewer_id == records.actor.id,
                    navigation_href=href,
                    evidence_refs=[
                        InspectionEvidenceRefV1(
                            source_kind="task_review",
                            source_id=review.id,
                            version=review.version,
                            observed_at=review.updated_at,
                            navigation_href=href,
                        ),
                        ProjectInspectionService._task_ref(task),
                    ],
                )
            )
        for review, memory in records.memory_reviews:
            if review.status is not MemoryReviewStatus.PENDING:
                continue
            if memory.version != review.memory_version:
                missing_data.append("memory_review_subject_changed")
            href = f"/knowledge?tab=pending&project={quote(records.project.id, safe='')}&memory={quote(memory.id, safe='')}"
            result.append(
                InspectionPendingReviewV1(
                    review_id=review.id,
                    kind="memory_review",
                    subject_id=memory.id,
                    title=memory.title,
                    reviewer_id=review.reviewer_id,
                    assigned_to_me=review.reviewer_id == records.actor.id,
                    navigation_href=href,
                    evidence_refs=[
                        InspectionEvidenceRefV1(
                            source_kind="memory_review",
                            source_id=review.id,
                            version=review.version,
                            observed_at=review.updated_at,
                            navigation_href=href,
                        )
                    ],
                )
            )
        return result

    @staticmethod
    def _changes(
        records: ProjectInspectionRecords,
        since: datetime,
        snapshot_at: datetime,
        missing_data: list[str],
    ) -> list[InspectionChangeV1]:
        if records.history_truncated:
            missing_data.append("task_history_limit_exceeded")
            return []
        changes = []
        previous: dict[str, TaskInspectionEvent] = {}
        for event in records.task_history:
            if event.observed_at > snapshot_at:
                continue
            prior = previous.get(event.task_id)
            if prior is not None and prior.version >= event.version:
                continue
            previous[event.task_id] = event
            if event.observed_at <= since:
                continue
            kind = "updated"
            if event.version == 1:
                kind = "created"
            elif prior is None or event.version != prior.version + 1:
                missing_data.append("task_history_incomplete")
                continue
            elif event.archived_at is not None and prior.archived_at is None:
                kind = "archived"
            elif event.delivery_stage is TaskDeliveryStage.DONE and prior.delivery_stage is not TaskDeliveryStage.DONE:
                kind = "completed"
            elif prior.delivery_stage is TaskDeliveryStage.DONE and event.delivery_stage is not TaskDeliveryStage.DONE:
                kind = "reopened"
            elif event.blocked_reason and not prior.blocked_reason:
                kind = "blocked"
            elif prior.blocked_reason and not event.blocked_reason:
                kind = "unblocked"
            elif (
                event.delivery_stage is TaskDeliveryStage.REVIEW
                and prior.delivery_stage is not TaskDeliveryStage.REVIEW
            ):
                kind = "pending_review"
            href = f"/tasks?task={quote(event.task_id, safe='')}"
            changes.append(
                InspectionChangeV1(
                    task_id=event.task_id,
                    title=event.title,
                    kind=kind,
                    occurred_at=event.observed_at,
                    version=event.version,
                    navigation_href=href,
                    evidence_refs=[
                        InspectionEvidenceRefV1(
                            source_kind=event.source_kind,
                            source_id=event.receipt_id,
                            version=event.version,
                            observed_at=event.observed_at,
                            navigation_href=href,
                        )
                    ],
                )
            )
        if any(row.task_id not in previous or row.version != previous[row.task_id].version for row in records.tasks):
            missing_data.append("task_history_incomplete")
        changes.sort(key=lambda item: (item.occurred_at, item.task_id, item.version))
        return changes

    @staticmethod
    def _blockers(
        tasks: tuple[TaskOperationsProjectionRow, ...],
        snapshot_at: datetime,
        missing_data: list[str],
    ) -> list[InspectionBlockerV1]:
        try:
            graph = TaskGraph(
                {
                    row.task_id: TaskGraphRecord(
                        task_id=row.task_id,
                        delivery_stage=row.delivery_stage,
                        parent_task_id=row.parent_task_id,
                        dependency_task_ids=row.dependency_task_ids,
                        blocked_reason=row.blocked_reason,
                        archived_at=row.archived_at,
                    )
                    for row in tasks
                }
            )
        except TaskGraphError:
            missing_data.append("task_relationship_evidence_unavailable")
            graph = None
        findings = []
        by_id = {row.task_id: row for row in tasks}
        for row in tasks:
            if row.archived_at is not None or row.delivery_stage in {
                TaskDeliveryStage.DONE,
                TaskDeliveryStage.CANCELLED,
            }:
                continue
            blocking_ids = graph.readiness(row.task_id).blocking_task_ids if graph is not None else []
            reasons = []
            if row.blocked_reason:
                reasons.append("blocked")
            if blocking_ids:
                reasons.append("dependency")
            if row.due_at is not None and row.due_at < snapshot_at:
                reasons.append("overdue")
            if row.updated_at <= snapshot_at - timedelta(days=7):
                reasons.append("stale")
            if reasons:
                findings.append(
                    InspectionBlockerV1(
                        task_id=row.task_id,
                        title=row.title,
                        delivery_stage=row.delivery_stage,
                        reasons=reasons,
                        blocked_reason=row.blocked_reason,
                        blocking_task_ids=blocking_ids,
                        due_at=row.due_at,
                        updated_at=row.updated_at,
                        navigation_href=f"/tasks?task={quote(row.task_id, safe='')}",
                        evidence_refs=[
                            ProjectInspectionService._task_ref(by_id[task_id])
                            for task_id in [row.task_id, *blocking_ids]
                        ],
                    )
                )
        return findings

    @staticmethod
    def _task_ref(row: TaskOperationsProjectionRow) -> InspectionEvidenceRefV1:
        return InspectionEvidenceRefV1(
            source_kind="task",
            source_id=row.task_id,
            version=row.version,
            observed_at=row.updated_at,
            navigation_href=f"/tasks?task={quote(row.task_id, safe='')}",
        )
