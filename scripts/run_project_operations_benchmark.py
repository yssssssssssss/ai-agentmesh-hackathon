#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import statistics
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter

from agentmesh.models import (
    ChatThread,
    ChatThreadKind,
    Intent,
    MemoryItem,
    MemoryStatus,
    Project,
    Scope,
    Task,
    TaskDeliveryStage,
    TaskManagementMetadataV1,
    TaskType,
    User,
    UserRole,
    Workspace,
)
from agentmesh.store import SQLiteStore
from agentmesh.task_management.service import TaskListQuery, TaskManagementService
from agentmesh.task_operations.service import (
    TaskOperationsQuery,
    TaskOperationsService,
    TaskOptionQuery,
)


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * ratio)))
    return ordered[index]


def measure(callback, iterations: int) -> dict[str, float]:  # noqa: ANN001
    callback()
    values: list[float] = []
    for _ in range(iterations):
        started = perf_counter()
        callback()
        values.append((perf_counter() - started) * 1000)
    return {
        "p50_ms": round(percentile(values, 0.50), 3),
        "p95_ms": round(percentile(values, 0.95), 3),
        "mean_ms": round(statistics.fmean(values), 3),
    }


def seed(
    repository: SQLiteStore,
    *,
    task_count: int,
    event_count: int,
    memory_count: int,
    accepted_memory_count: int,
) -> tuple[User, Project, str]:
    workspace = repository.save_workspace(
        Workspace(id="workspace_benchmark", name="Benchmark", description="Slice 6 scale")
    )
    user = repository.save_user(
        User(
            id="user_benchmark",
            workspace_id=workspace.id,
            default_project_id="project_benchmark",
            name="Benchmark manager",
            role=UserRole.TEAM_LEAD,
            personal_agent_id="agent_benchmark",
        )
    )
    project = repository.save_project(
        Project(
            id="project_benchmark",
            workspace_id=workspace.id,
            name="Benchmark project",
            goal="Measure project operations",
            member_ids=[user.id],
        )
    )
    now = datetime.now(UTC).replace(microsecond=0)
    task_rows: list[tuple[str, str, str]] = []
    thread_rows: list[tuple[str, str, str]] = []
    for index in range(task_count):
        task_id = f"task_benchmark_{index:05d}"
        thread_id = f"thread_benchmark_{index:05d}"
        thread = ChatThread(
            id=thread_id,
            workspace_id=workspace.id,
            project_id=project.id,
            user_id=user.id,
            title=f"Benchmark task {index}",
            kind=ChatThreadKind.TASK,
            created_at=now,
            updated_at=now,
        )
        parent_id = f"task_benchmark_{index - index % 100:05d}" if index % 100 != 0 else None
        dependency_ids = (
            [f"task_benchmark_{index - 1:05d}"]
            if index % 5 != 0 and f"task_benchmark_{index - 1:05d}" != parent_id
            else []
        )
        management = TaskManagementMetadataV1(
            description=f"Benchmark searchable payload cohort-{index % 37}",
            task_type=TaskType.MILESTONE if index % 100 == 0 else TaskType.PROJECT_ACTION,
            delivery_stage=(
                TaskDeliveryStage.DONE
                if index % 7 == 0
                else TaskDeliveryStage.IN_PROGRESS
                if index % 3 == 0
                else TaskDeliveryStage.PLANNED
            ),
            due_at=now + timedelta(days=(index % 120) - 30),
            parent_task_id=parent_id,
            dependency_task_ids=dependency_ids,
            created_by=user.id,
            updated_by=user.id,
        )
        task = Task(
            id=task_id,
            thread_id=thread_id,
            intent=Intent.GENERAL_CHAT,
            title=f"Benchmark task {index}",
            management=management,
            created_at=now,
            updated_at=now + timedelta(seconds=index),
        )
        thread_rows.append(("chat_threads", thread.id, thread.model_dump_json()))
        task_rows.append(("tasks", task.id, task.model_dump_json()))
    with repository._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.executemany(
            "INSERT INTO records(collection, id, payload) VALUES (?, ?, ?)",
            [*thread_rows, *task_rows],
        )
        audit_rows = []
        for index in range(event_count):
            payload = json.dumps(
                {
                    "id": f"audit_benchmark_{index:05d}",
                    "actor": user.id,
                    "action": "benchmark_task_event",
                    "target_type": "task",
                    "target_id": f"task_benchmark_{index % task_count:05d}",
                    "workspace_id": workspace.id,
                    "project_id": project.id,
                    "metadata": {"ordinal": index},
                    "created_at": now.isoformat(),
                },
                separators=(",", ":"),
            )
            audit_rows.append(("audit_events", f"audit_benchmark_{index:05d}", payload))
        connection.executemany(
            "INSERT INTO records(collection, id, payload) VALUES (?, ?, ?)",
            audit_rows,
        )
        memory_rows = []
        for index in range(memory_count):
            accepted = index < accepted_memory_count
            memory = MemoryItem(
                id=f"memory_benchmark_{index:05d}",
                title=f"Benchmark memory {index}",
                summary=f"Reusable benchmark insight cohort-{index % 41}",
                memory_type="benchmark",
                scope=Scope.TEAM_ACCEPTED,
                status=MemoryStatus.ACCEPTED if accepted else MemoryStatus.DISPUTED,
                owner_user_id=user.id,
                workspace_id=workspace.id,
                project_id=project.id,
                created_at=now,
                updated_at=now,
            )
            memory_rows.append(("memory_items", memory.id, memory.model_dump_json()))
        connection.executemany(
            "INSERT INTO records(collection, id, payload) VALUES (?, ?, ?)",
            memory_rows,
        )
    repository._backfill_fts()
    return user, project, "task_benchmark_05000" if task_count > 5000 else "task_benchmark_00000"


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark AgentMesh project operations on SQLite")
    parser.add_argument("--tasks", type=int, default=10_000)
    parser.add_argument("--events", type=int, default=50_000)
    parser.add_argument("--memory", type=int, default=10_000)
    parser.add_argument("--accepted-memory", type=int, default=1_000)
    parser.add_argument("--iterations", type=int, default=7)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()
    if not 0 <= args.accepted_memory <= args.memory:
        parser.error("--accepted-memory must be between zero and --memory")
    os.environ["AGENTMESH_TASK_MANAGEMENT"] = "write"
    temporary = tempfile.TemporaryDirectory(prefix="agentmesh-project-operations-")
    database = args.database or Path(temporary.name) / "benchmark.sqlite3"
    repository = SQLiteStore(database)
    user, project, detail_task_id = seed(
        repository,
        task_count=args.tasks,
        event_count=args.events,
        memory_count=args.memory,
        accepted_memory_count=args.accepted_memory,
    )
    now = datetime.now(UTC)
    task_management = TaskManagementService(repository)
    operations = TaskOperationsService(repository)
    measurements = {
        "task_list": measure(
            lambda: task_management.list_tasks(
                TaskListQuery(project_id=project.id, page=1, page_size=100),
                user,
            ),
            args.iterations,
        ),
        "task_detail": measure(
            lambda: task_management.get_task_detail(detail_task_id, user),
            args.iterations,
        ),
        "operations_snapshot": measure(
            lambda: operations.snapshot(
                TaskOperationsQuery(
                    project_id=project.id,
                    calendar_start=now - timedelta(days=30),
                    calendar_end=now + timedelta(days=90),
                    calendar_page_size=50,
                    queue_page_size=50,
                ),
                user,
            ),
            args.iterations,
        ),
        "task_options": measure(
            lambda: operations.task_options(
                TaskOptionQuery(project_id=project.id, query="cohort-7", page_size=50),
                user,
            ),
            args.iterations,
        ),
        "memory_fts": measure(
            lambda: repository.search(
                "benchmark insight cohort-7",
                {Scope.TEAM_ACCEPTED},
                workspace_id=user.workspace_id,
                project_id=project.id,
                max_results=8,
                agent_context=True,
            ),
            args.iterations,
        ),
    }
    threshold_ms = 500.0
    passed = all(result["p95_ms"] <= threshold_ms for result in measurements.values())
    report = {
        "schema_version": "project-operations-benchmark-v1",
        "database": str(database) if args.database is not None else "temporary",
        "counts": {
            "tasks": args.tasks,
            "task_audit_events": args.events,
            "memory_records": args.memory,
            "accepted_team_knowledge": args.accepted_memory,
        },
        "iterations": args.iterations,
        "threshold_p95_ms": threshold_ms,
        "measurements": measurements,
        "passed": passed,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n")
    repository.close()
    temporary.cleanup()
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
