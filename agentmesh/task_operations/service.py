from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote

from agentmesh.models import (
    AgentRun,
    AgentRunStatus,
    ChatThreadKind,
    MemoryUseReceiptV1,
    TaskAssigneeKind,
    TaskDeliveryStage,
    TaskReviewStatus,
    TaskReviewV1,
    TaskType,
    User,
    UserRole,
    now_utc,
)
from agentmesh.store import SQLiteStore, TaskOperationsProjectionRow
from agentmesh.task_operations.contracts import (
    AgentQueueItemV1,
    AgentQueuePageV1,
    AgentQueueState,
    TaskCalendarItemV1,
    TaskCalendarPageV1,
    TaskMilestoneV1,
    TaskOperationsMetricsV1,
    TaskOperationsSnapshotV1,
    TaskOperationsTaskV1,
    TaskOptionPageV1,
    TaskOptionV1,
    TaskReadinessState,
)
from agentmesh.task_operations.graph import TaskGraph, TaskGraphError, TaskGraphRecord


class TaskOperationsError(RuntimeError):
    def __init__(self, code: str, *, status_code: int = 409):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class TaskOperationsQuery:
    project_id: str
    calendar_start: datetime
    calendar_end: datetime
    calendar_page: int = 1
    calendar_page_size: int = 50
    queue_page: int = 1
    queue_page_size: int = 50
    queue_agent_id: str | None = None


@dataclass(frozen=True, slots=True)
class TaskOptionQuery:
    project_id: str
    page: int = 1
    page_size: int = 50
    query: str | None = None
    exclude_task_id: str | None = None


class TaskOperationsService:
    """Project operations read model over server-owned Task and execution facts."""

    ACTIVE_RUN_STATUSES = {
        AgentRunStatus.CREATED,
        AgentRunStatus.PLANNING,
        AgentRunStatus.WAITING_CLARIFICATION,
        AgentRunStatus.WAITING_INPUT,
        AgentRunStatus.WAITING_PLAN_APPROVAL,
        AgentRunStatus.WAITING_APPROVAL,
        AgentRunStatus.RUNNING,
    }

    def __init__(self, repository: SQLiteStore):
        self.repository = repository

    def snapshot(self, query: TaskOperationsQuery, user: User) -> TaskOperationsSnapshotV1:
        self._project_for_user(query.project_id, user)
        self._validate_query(query)
        records = self._visible_records(query.project_id, user)
        graph = self._graph(records)
        runs = [
            run
            for run in self.repository.list_agent_runs_for_project(query.project_id)
            if run.task_id in records
        ]
        active_run_by_task = {}
        for run in runs:
            if run.task_id is None:
                continue
            if run.status in self.ACTIVE_RUN_STATUSES and run.task_id not in active_run_by_task:
                active_run_by_task[run.task_id] = run
        active_task_ids = set(active_run_by_task)
        view_cache: dict[str, TaskOperationsTaskV1] = {}

        def task_view(task_id: str) -> TaskOperationsTaskV1:
            if task_id not in view_cache:
                view_cache[task_id] = self._task_view(
                    records[task_id],
                    graph,
                    active_run=task_id in active_task_ids,
                )
            return view_cache[task_id]

        now = now_utc()
        milestones = self._milestones(records, task_view, graph, now)
        calendar = self._calendar_page_from_records(records, task_view, query, now)
        agent_queue = self._queue_page_from_records(
            records,
            task_view,
            active_run_by_task,
            query,
        )
        reviews = [
            review
            for review in self.repository.list_task_reviews_for_project(
                workspace_id=user.workspace_id,
                project_id=query.project_id,
            )
            if review.task_id in records
        ]
        run_by_id = {run.id: run for run in runs}
        receipt_visible_run_ids = {
            run.id for run in runs if run.user_id == user.id
        }
        receipts = [
            receipt
            for receipt in self.repository.list_memory_use_receipts_for_project(query.project_id)
            if receipt.run_id in receipt_visible_run_ids
        ]
        metrics = self._metrics(
            records=records,
            graph=graph,
            active_task_ids=active_task_ids,
            runs=runs,
            reviews=reviews,
            receipts=receipts,
            run_by_id=run_by_id,
            accepted_team_knowledge_count=self.repository.count_accepted_team_memory(
                workspace_id=user.workspace_id,
                project_id=query.project_id,
                user_id=user.id,
            ),
            now=now,
        )
        chain_ids = graph.critical_dependency_chain()
        chain = [task_view(task_id) for task_id in chain_ids[-100:]]
        return TaskOperationsSnapshotV1(
            project_id=query.project_id,
            generated_at=now,
            metrics=metrics,
            critical_dependency_chain=chain,
            critical_dependency_chain_total=len(chain_ids),
            critical_dependency_chain_truncated=len(chain_ids) > len(chain),
            milestones=milestones[:50],
            milestone_total=len(milestones),
            milestones_truncated=len(milestones) > 50,
            calendar=calendar,
            agent_queue=agent_queue,
            graph_task_count=len(records),
        )

    def task_options(self, query: TaskOptionQuery, user: User) -> TaskOptionPageV1:
        self._project_for_user(query.project_id, user)
        if query.page < 1 or not 1 <= query.page_size <= 100:
            raise TaskOperationsError("task_options_page_invalid", status_code=422)
        normalized = (query.query or "").strip().casefold()
        records = [
            record
            for record in self._visible_records(query.project_id, user).values()
            if record.task_id != query.exclude_task_id
            and record.archived_at is None
            and (
                not normalized
                or normalized in record.title.casefold()
                or normalized in record.description.casefold()
            )
        ]
        records.sort(key=lambda item: (item.title.casefold(), item.task_id))
        start = (query.page - 1) * query.page_size
        end = start + query.page_size
        return TaskOptionPageV1(
            items=[
                TaskOptionV1(
                    id=record.task_id,
                    title=record.title,
                    task_type=record.task_type,
                    delivery_stage=record.delivery_stage,
                    archived=False,
                )
                for record in records[start:end]
            ],
            total=len(records),
            page=query.page,
            page_size=query.page_size,
            has_next=end < len(records),
        )

    def _visible_records(
        self,
        project_id: str,
        user: User,
    ) -> dict[str, TaskOperationsProjectionRow]:
        can_view_legacy = user.role in {UserRole.TEAM_LEAD, UserRole.ADMIN}
        records: dict[str, TaskOperationsProjectionRow] = {}
        for row in self.repository.list_project_task_projection(
            workspace_id=user.workspace_id,
            project_id=project_id,
        ):
            visible = (
                row.thread_kind is ChatThreadKind.TASK
                or can_view_legacy
                or row.thread_user_id == user.id
            )
            if not visible and row.assignee_kind is TaskAssigneeKind.USER:
                visible = row.assignee_id == user.id
            if not visible and row.assignee_kind is TaskAssigneeKind.AGENT:
                agent = self.repository.get_agent(row.assignee_id or "")
                visible = row.assignee_id == user.personal_agent_id or (
                    agent is not None and agent.owner_user_id == user.id
                )
            if visible:
                records[row.task_id] = row
        return records

    @staticmethod
    def _graph(records: dict[str, TaskOperationsProjectionRow]) -> TaskGraph:
        try:
            return TaskGraph(
                {
                    task_id: TaskGraphRecord(
                        task_id=task_id,
                        delivery_stage=row.delivery_stage,
                        parent_task_id=row.parent_task_id,
                        dependency_task_ids=row.dependency_task_ids,
                        blocked_reason=row.blocked_reason,
                        archived_at=row.archived_at,
                    )
                    for task_id, row in records.items()
                }
            )
        except TaskGraphError as error:
            raise TaskOperationsError(error.code) from error

    @staticmethod
    def _task_view(
        record: TaskOperationsProjectionRow,
        graph: TaskGraph,
        *,
        active_run: bool,
    ) -> TaskOperationsTaskV1:
        return TaskOperationsTaskV1(
            id=record.task_id,
            title=record.title,
            task_type=record.task_type,
            delivery_stage=record.delivery_stage,
            priority=record.priority,
            due_at=record.due_at,
            assignee_kind=record.assignee_kind,
            assignee_id=record.assignee_id,
            parent_task_id=record.parent_task_id,
            dependency_task_ids=list(record.dependency_task_ids),
            readiness=graph.readiness(record.task_id, active_run=active_run),
            navigation_href=f"/tasks?task={quote(record.task_id, safe='')}",
        )

    @staticmethod
    def _overdue(record: TaskOperationsProjectionRow, now: datetime) -> bool:
        return bool(
            record.due_at is not None
            and record.due_at < now
            and record.archived_at is None
            and record.delivery_stage
            not in {TaskDeliveryStage.DONE, TaskDeliveryStage.CANCELLED}
        )

    def _milestones(
        self,
        records: dict[str, TaskOperationsProjectionRow],
        task_view: Callable[[str], TaskOperationsTaskV1],
        graph: TaskGraph,
        now: datetime,
    ) -> list[TaskMilestoneV1]:
        milestones: list[TaskMilestoneV1] = []
        for task_id, record in records.items():
            if record.task_type is not TaskType.MILESTONE or record.archived_at is not None:
                continue
            descendants = [
                descendant_id
                for descendant_id in graph.descendants(task_id)
                if records[descendant_id].archived_at is None
                and records[descendant_id].delivery_stage is not TaskDeliveryStage.CANCELLED
            ]
            completed = [
                descendant_id
                for descendant_id in descendants
                if records[descendant_id].delivery_stage is TaskDeliveryStage.DONE
            ]
            progress = (
                round(len(completed) * 100 / len(descendants))
                if descendants
                else 100
                if record.delivery_stage is TaskDeliveryStage.DONE
                else 0
            )
            milestones.append(
                TaskMilestoneV1(
                    task=task_view(task_id),
                    descendant_count=len(descendants),
                    completed_descendant_count=len(completed),
                    progress_percent=progress,
                    overdue=self._overdue(record, now),
                )
            )
        milestones.sort(
            key=lambda item: (
                item.task.due_at is None,
                item.task.due_at or now,
                item.task.id,
            )
        )
        return milestones

    @staticmethod
    def _queue_page_from_records(
        records: dict[str, TaskOperationsProjectionRow],
        task_view: Callable[[str], TaskOperationsTaskV1],
        active_run_by_task: dict[str, AgentRun],
        query: TaskOperationsQuery,
    ) -> AgentQueuePageV1:
        state_map = {
            TaskReadinessState.BACKLOG: AgentQueueState.BACKLOG,
            TaskReadinessState.PLANNED: AgentQueueState.PLANNED,
            TaskReadinessState.WAITING_DEPENDENCIES: AgentQueueState.WAITING_DEPENDENCIES,
            TaskReadinessState.BLOCKED: AgentQueueState.BLOCKED,
            TaskReadinessState.READY: AgentQueueState.READY,
            TaskReadinessState.RUNNING: AgentQueueState.RUNNING,
            TaskReadinessState.REVIEW: AgentQueueState.REVIEW,
        }
        order = {
            AgentQueueState.RUNNING: 0,
            AgentQueueState.READY: 1,
            AgentQueueState.WAITING_DEPENDENCIES: 2,
            AgentQueueState.BLOCKED: 3,
            AgentQueueState.REVIEW: 4,
            AgentQueueState.PLANNED: 5,
            AgentQueueState.BACKLOG: 6,
        }
        candidates: list[tuple[int, bool, str, bool, datetime, str, AgentQueueState]] = []
        for task_id, record in records.items():
            if (
                record.archived_at is not None
                or record.assignee_kind is not TaskAssigneeKind.AGENT
                or record.assignee_id is None
                or (query.queue_agent_id is not None and record.assignee_id != query.queue_agent_id)
            ):
                continue
            view = task_view(task_id)
            queue_state = state_map.get(view.readiness.state)
            if queue_state is None:
                continue
            candidates.append(
                (
                    order[queue_state],
                    record.priority is None,
                    record.priority.value if record.priority is not None else "",
                    record.due_at is None,
                    record.due_at or query.calendar_end,
                    task_id,
                    queue_state,
                )
            )
        candidates.sort(key=lambda item: item[:-1])
        start = (query.queue_page - 1) * query.queue_page_size
        end = start + query.queue_page_size
        items = []
        for *_sort, task_id, queue_state in candidates[start:end]:
            run = active_run_by_task.get(task_id)
            items.append(
                AgentQueueItemV1(
                    task=task_view(task_id),
                    queue_state=queue_state,
                    active_run_status=run.status if run is not None else None,
                )
            )
        return AgentQueuePageV1(
            items=items,
            total=len(candidates),
            page=query.queue_page,
            page_size=query.queue_page_size,
            has_next=end < len(candidates),
        )

    @staticmethod
    def _calendar_page_from_records(
        records: dict[str, TaskOperationsProjectionRow],
        task_view: Callable[[str], TaskOperationsTaskV1],
        query: TaskOperationsQuery,
        now: datetime,
    ) -> TaskCalendarPageV1:
        candidates = [
            record
            for record in records.values()
            if record.archived_at is None
            and record.due_at is not None
            and query.calendar_start <= record.due_at < query.calendar_end
        ]
        candidates.sort(key=lambda record: (record.due_at or query.calendar_end, record.task_id))
        start = (query.calendar_page - 1) * query.calendar_page_size
        end = start + query.calendar_page_size
        return TaskCalendarPageV1(
            items=[
                TaskCalendarItemV1(
                    task=task_view(record.task_id),
                    overdue=TaskOperationsService._overdue(record, now),
                )
                for record in candidates[start:end]
            ],
            total=len(candidates),
            page=query.calendar_page,
            page_size=query.calendar_page_size,
            has_next=end < len(candidates),
            range_start=query.calendar_start,
            range_end=query.calendar_end,
        )

    @staticmethod
    def _metrics(
        *,
        records: dict[str, TaskOperationsProjectionRow],
        graph: TaskGraph,
        active_task_ids: set[str],
        runs: list[AgentRun],
        reviews: list[TaskReviewV1],
        receipts: list[MemoryUseReceiptV1],
        run_by_id: dict[str, AgentRun],
        accepted_team_knowledge_count: int,
        now: datetime,
    ) -> TaskOperationsMetricsV1:
        tasks_by_stage = {stage: 0 for stage in TaskDeliveryStage}
        tasks_by_readiness = {state: 0 for state in TaskReadinessState}
        for task_id, record in records.items():
            if record.archived_at is not None:
                continue
            tasks_by_stage[record.delivery_stage] += 1
            tasks_by_readiness[
                graph.readiness(task_id, active_run=task_id in active_task_ids).state
            ] += 1
        runs_by_status: dict[AgentRunStatus, int] = {status: 0 for status in AgentRunStatus}
        for run in runs:
            runs_by_status[run.status] += 1
        reviews_by_status = {status: 0 for status in TaskReviewStatus}
        for review in reviews:
            reviews_by_status[review.status] += 1
        current_records = [record for record in records.values() if record.archived_at is None]
        cited = [
            receipt
            for receipt in receipts
            if (run := run_by_id.get(receipt.run_id)) is not None
            and run.output_text is not None
            and f"[{receipt.citation_label}]" in run.output_text
        ]
        return TaskOperationsMetricsV1(
            tasks_by_stage=tasks_by_stage,
            tasks_by_readiness=tasks_by_readiness,
            runs_by_status=runs_by_status,
            reviews_by_status=reviews_by_status,
            task_count=len(current_records),
            open_task_count=sum(
                1
                for record in current_records
                if record.delivery_stage
                not in {TaskDeliveryStage.DONE, TaskDeliveryStage.CANCELLED}
            ),
            overdue_task_count=sum(
                1
                for record in current_records
                if TaskOperationsService._overdue(record, now)
            ),
            blocked_task_count=sum(
                1 for record in current_records if record.blocked_reason is not None
            ),
            active_run_count=sum(
                1 for run in runs if run.status in TaskOperationsService.ACTIVE_RUN_STATUSES
            ),
            pending_review_count=reviews_by_status[TaskReviewStatus.PENDING],
            memory_use_count=len(receipts),
            cited_memory_use_count=len(cited),
            unique_reused_memory_count=len({receipt.memory_id for receipt in receipts}),
            accepted_team_knowledge_count=accepted_team_knowledge_count,
        )

    def _project_for_user(self, project_id: str, user: User) -> None:
        project = self.repository.get_project(project_id)
        if (
            project is None
            or project.workspace_id != user.workspace_id
            or not self.repository.user_can_access_project(user.id, project_id)
        ):
            raise TaskOperationsError("project_not_found", status_code=404)

    @staticmethod
    def _validate_query(query: TaskOperationsQuery) -> None:
        if query.calendar_start.utcoffset() is None or query.calendar_end.utcoffset() is None:
            raise TaskOperationsError("task_calendar_timezone_required", status_code=422)
        if query.calendar_start >= query.calendar_end:
            raise TaskOperationsError("task_calendar_range_invalid", status_code=422)
        if (query.calendar_end - query.calendar_start).days > 366:
            raise TaskOperationsError("task_calendar_range_too_large", status_code=422)
        if (
            query.calendar_page < 1
            or query.queue_page < 1
            or not 1 <= query.calendar_page_size <= 100
            or not 1 <= query.queue_page_size <= 100
        ):
            raise TaskOperationsError("task_operations_page_invalid", status_code=422)
