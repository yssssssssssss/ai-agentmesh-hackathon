from __future__ import annotations

import heapq
from dataclasses import dataclass
from datetime import datetime

from agentmesh.models import TaskDeliveryStage
from agentmesh.task_operations.contracts import TaskReadinessState, TaskReadinessV1


class TaskGraphError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class TaskGraphRecord:
    task_id: str
    delivery_stage: TaskDeliveryStage
    parent_task_id: str | None = None
    dependency_task_ids: tuple[str, ...] = ()
    blocked_reason: str | None = None
    archived_at: datetime | None = None


class TaskGraph:
    """Validated project Task graph with readiness and rollup projections."""

    def __init__(self, records: dict[str, TaskGraphRecord]):
        self.records = records
        self.children_by_parent: dict[str, list[str]] = {task_id: [] for task_id in records}
        self.dependents_by_dependency: dict[str, list[str]] = {task_id: [] for task_id in records}
        for task_id, record in records.items():
            parent_id = record.parent_task_id
            if parent_id is not None:
                if parent_id not in records:
                    raise TaskGraphError("task_relationship_target_not_found")
                if parent_id == task_id:
                    raise TaskGraphError("task_parent_cycle")
                self.children_by_parent[parent_id].append(task_id)
            for dependency_id in record.dependency_task_ids:
                if dependency_id not in records:
                    raise TaskGraphError("task_relationship_target_not_found")
                if dependency_id == task_id:
                    raise TaskGraphError("task_dependency_cycle")
                self.dependents_by_dependency[dependency_id].append(task_id)
        for values in self.children_by_parent.values():
            values.sort()
        for values in self.dependents_by_dependency.values():
            values.sort()
        self._validate_parent_graph()
        self._dependency_topological_order = self._validate_dependency_graph()

    def readiness(
        self,
        task_id: str,
        *,
        active_run: bool = False,
    ) -> TaskReadinessV1:
        record = self.records.get(task_id)
        if record is None:
            raise TaskGraphError("task_not_found")
        dependencies = [self.records[item] for item in record.dependency_task_ids]
        completed_dependencies = [
            item for item in dependencies if item.delivery_stage is TaskDeliveryStage.DONE
        ]
        blocking_ids = [
            item.task_id
            for item in dependencies
            if item.delivery_stage is not TaskDeliveryStage.DONE
        ]
        child_ids = self.children_by_parent.get(task_id, [])
        completed_children = [
            child_id
            for child_id in child_ids
            if self.records[child_id].delivery_stage is TaskDeliveryStage.DONE
        ]
        if record.archived_at is not None:
            state = TaskReadinessState.ARCHIVED
        elif record.delivery_stage is TaskDeliveryStage.DONE:
            state = TaskReadinessState.DONE
        elif record.delivery_stage is TaskDeliveryStage.CANCELLED:
            state = TaskReadinessState.CANCELLED
        elif record.delivery_stage is TaskDeliveryStage.REVIEW:
            state = TaskReadinessState.REVIEW
        elif active_run and record.delivery_stage is TaskDeliveryStage.IN_PROGRESS:
            state = TaskReadinessState.RUNNING
        elif record.blocked_reason is not None:
            state = TaskReadinessState.BLOCKED
        elif blocking_ids:
            state = TaskReadinessState.WAITING_DEPENDENCIES
        elif record.delivery_stage is TaskDeliveryStage.BACKLOG:
            state = TaskReadinessState.BACKLOG
        elif record.delivery_stage is TaskDeliveryStage.PLANNED:
            state = TaskReadinessState.PLANNED
        else:
            state = TaskReadinessState.READY
        return TaskReadinessV1(
            state=state,
            is_execution_ready=(
                state is TaskReadinessState.READY
                and record.delivery_stage is TaskDeliveryStage.IN_PROGRESS
            ),
            dependency_count=len(dependencies),
            completed_dependency_count=len(completed_dependencies),
            blocking_task_ids=blocking_ids,
            child_count=len(child_ids),
            completed_child_count=len(completed_children),
        )

    def dependencies_done(self, task_id: str) -> bool:
        return not self.readiness(task_id).blocking_task_ids

    def descendants(self, task_id: str) -> list[str]:
        if task_id not in self.records:
            raise TaskGraphError("task_not_found")
        result: list[str] = []
        pending = list(reversed(self.children_by_parent.get(task_id, [])))
        while pending:
            current = pending.pop()
            result.append(current)
            pending.extend(reversed(self.children_by_parent.get(current, [])))
        return result

    def critical_dependency_chain(self) -> list[str]:
        active_ids = {
            task_id
            for task_id, record in self.records.items()
            if record.archived_at is None
            and record.delivery_stage not in {TaskDeliveryStage.DONE, TaskDeliveryStage.CANCELLED}
        }
        chains: dict[str, list[str]] = {}
        for task_id in self._dependency_topological_order:
            if task_id not in active_ids:
                continue
            active_dependencies = [
                dependency_id
                for dependency_id in self.records[task_id].dependency_task_ids
                if dependency_id in active_ids
            ]
            if not active_dependencies:
                chains[task_id] = [task_id]
                continue
            best_dependency = min(
                active_dependencies,
                key=lambda dependency_id: (-len(chains.get(dependency_id, [])), dependency_id),
            )
            chains[task_id] = [*chains.get(best_dependency, [best_dependency]), task_id]
        if not chains:
            return []
        best = min(chains.values(), key=lambda chain: (-len(chain), tuple(chain)))
        return best if len(best) >= 2 else []

    def _validate_parent_graph(self) -> None:
        complete: set[str] = set()
        for start in sorted(self.records):
            if start in complete:
                continue
            path: list[str] = []
            positions: dict[str, int] = {}
            current: str | None = start
            while current is not None and current not in complete:
                if current in positions:
                    raise TaskGraphError("task_parent_cycle")
                positions[current] = len(path)
                path.append(current)
                current = self.records[current].parent_task_id
            complete.update(path)

    def _validate_dependency_graph(self) -> list[str]:
        indegree = {
            task_id: len(record.dependency_task_ids)
            for task_id, record in self.records.items()
        }
        ready = [task_id for task_id, value in indegree.items() if value == 0]
        heapq.heapify(ready)
        ordered: list[str] = []
        while ready:
            task_id = heapq.heappop(ready)
            ordered.append(task_id)
            for dependent_id in self.dependents_by_dependency.get(task_id, []):
                indegree[dependent_id] -= 1
                if indegree[dependent_id] == 0:
                    heapq.heappush(ready, dependent_id)
        if len(ordered) != len(self.records):
            raise TaskGraphError("task_dependency_cycle")
        return ordered
