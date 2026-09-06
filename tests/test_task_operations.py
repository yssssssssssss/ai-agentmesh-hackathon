from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from agentmesh.models import (
    Agent,
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    ChatThread,
    ChatThreadKind,
    Intent,
    MemoryItem,
    MemoryKind,
    MemoryLayer,
    MemoryStatus,
    MemoryUseReceiptV1,
    Project,
    Scope,
    Task,
    TaskAssigneeKind,
    TaskDeliveryStage,
    TaskManagementMetadataV1,
    TaskReviewStatus,
    TaskReviewV1,
    User,
    UserRole,
    Workspace,
    now_utc,
)
from agentmesh.store import ResearchStoreConflict, SQLiteStore
from agentmesh.task_management.contracts import (
    TaskCreateRequest,
    TaskTransitionAction,
    TaskTransitionRequest,
    TaskUpdateRequest,
)
from agentmesh.task_management.service import TaskManagementError, TaskManagementService
from agentmesh.task_operations.contracts import AgentQueueState, TaskReadinessState
from agentmesh.task_operations.service import TaskOperationsQuery, TaskOperationsService, TaskOptionQuery


def _repository(tmp_path) -> tuple[SQLiteStore, Project, User, User, Agent]:
    repository = SQLiteStore(tmp_path / "task-operations.sqlite3")
    workspace = repository.save_workspace(
        Workspace(id="workspace_operations", name="Operations", description="Slice 6")
    )
    manager = repository.save_user(
        User(
            id="user_operations_manager",
            workspace_id=workspace.id,
            default_project_id="project_operations",
            name="Operations manager",
            role=UserRole.TEAM_LEAD,
            personal_agent_id="agent_operations_manager",
        )
    )
    member = repository.save_user(
        User(
            id="user_operations_member",
            workspace_id=workspace.id,
            default_project_id="project_operations",
            name="Operations member",
            role=UserRole.USER,
            personal_agent_id="agent_operations_member",
        )
    )
    project = repository.save_project(
        Project(
            id="project_operations",
            workspace_id=workspace.id,
            name="Operations project",
            goal="Ship the project",
            member_ids=[manager.id, member.id],
        )
    )
    agent = repository.save_agent(
        Agent(
            id=manager.personal_agent_id,
            name="Operations manager agent",
            description="Executes ready project tasks",
            agent_type="personal",
            owner_user_id=manager.id,
            workspace_id=workspace.id,
            status="online",
        )
    )
    return repository, project, manager, member, agent


def _create(
    service: TaskManagementService,
    user: User,
    suffix: str,
    **kwargs,
):
    return service.create_task(
        TaskCreateRequest(
            command_id=f"create-{suffix}",
            title=f"Task {suffix}",
            **kwargs,
        ),
        user,
    )


def _transition(
    service: TaskManagementService,
    user: User,
    task_id: str,
    version: int,
    action: TaskTransitionAction,
):
    return service.transition_task(
        task_id,
        TaskTransitionRequest(
            command_id=f"transition-{task_id}-{version}-{action.value}",
            expected_version=version,
            action=action,
        ),
        user,
    )


def _complete(service: TaskManagementService, user: User, task_id: str, version: int):
    current = _transition(service, user, task_id, version, TaskTransitionAction.PLAN)
    current = _transition(
        service,
        user,
        task_id,
        current.management.version,
        TaskTransitionAction.START,
    )
    current = _transition(
        service,
        user,
        task_id,
        current.management.version,
        TaskTransitionAction.SUBMIT_REVIEW,
    )
    return _transition(
        service,
        user,
        task_id,
        current.management.version,
        TaskTransitionAction.COMPLETE,
    )


def _query(project_id: str) -> TaskOperationsQuery:
    now = now_utc()
    return TaskOperationsQuery(
        project_id=project_id,
        calendar_start=now - timedelta(days=30),
        calendar_end=now + timedelta(days=90),
        calendar_page_size=2,
        queue_page_size=10,
    )


def test_project_graph_drives_readiness_critical_chain_milestone_calendar_and_queue(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    repository, project, manager, _member, agent = _repository(tmp_path)
    tasks = TaskManagementService(repository)
    due = now_utc() + timedelta(days=14)
    milestone = _create(tasks, manager, "milestone", task_type="milestone", due_at=due)
    research = _create(
        tasks,
        manager,
        "research",
        parent_task_id=milestone.task.id,
        assignee_kind=TaskAssigneeKind.AGENT,
        assignee_id=agent.id,
        due_at=due - timedelta(days=8),
    )
    design = _create(
        tasks,
        manager,
        "design",
        parent_task_id=milestone.task.id,
        dependency_task_ids=[research.task.id],
        assignee_kind=TaskAssigneeKind.AGENT,
        assignee_id=agent.id,
        due_at=due - timedelta(days=4),
    )
    launch = _create(
        tasks,
        manager,
        "launch",
        parent_task_id=milestone.task.id,
        dependency_task_ids=[design.task.id],
        assignee_kind=TaskAssigneeKind.AGENT,
        assignee_id=agent.id,
        due_at=due,
    )

    snapshot = TaskOperationsService(repository).snapshot(_query(project.id), manager)
    detail = tasks.get_task_detail(design.task.id, manager)

    assert detail.parent_task is not None and detail.parent_task.id == milestone.task.id
    assert [item.id for item in detail.dependency_tasks] == [research.task.id]
    assert detail.relationships_truncated is False
    assert [item.id for item in tasks.get_task_detail(milestone.task.id, manager).child_tasks] == [
        launch.task.id,
        design.task.id,
        research.task.id,
    ]

    assert [item.id for item in snapshot.critical_dependency_chain] == [
        research.task.id,
        design.task.id,
        launch.task.id,
    ]
    milestone_view = snapshot.milestones[0]
    assert milestone_view.task.id == milestone.task.id
    assert milestone_view.descendant_count == 3
    assert milestone_view.progress_percent == 0
    assert snapshot.calendar.total == 4
    assert snapshot.calendar.has_next is True
    queue_by_task = {item.task.id: item for item in snapshot.agent_queue.items}
    assert queue_by_task[research.task.id].queue_state is AgentQueueState.BACKLOG
    assert queue_by_task[design.task.id].queue_state is AgentQueueState.WAITING_DEPENDENCIES
    assert snapshot.metrics.task_count == 4
    assert snapshot.metrics.open_task_count == 4

    completed = _complete(tasks, manager, research.task.id, research.management.version)
    assert completed.management.delivery_stage is TaskDeliveryStage.DONE
    design = tasks.get_task(design.task.id, manager)
    planned = _transition(
        tasks,
        manager,
        design.task.id,
        design.management.version,
        TaskTransitionAction.PLAN,
    )
    started = _transition(
        tasks,
        manager,
        design.task.id,
        planned.management.version,
        TaskTransitionAction.START,
    )
    assert started.readiness.state is TaskReadinessState.READY
    assert started.readiness.is_execution_ready is True
    repository.save_agent_run(
        AgentRun(
            id="run_operations_design",
            thread_id=started.task.thread_id,
            task_id=started.task.id,
            user_id=manager.id,
            workspace_id=manager.workspace_id,
            project_id=project.id,
            input_text="execute design",
            status=AgentRunStatus.RUNNING,
        )
    )

    refreshed = TaskOperationsService(repository).snapshot(_query(project.id), manager)
    milestone_view = refreshed.milestones[0]
    assert milestone_view.completed_descendant_count == 1
    assert milestone_view.progress_percent == 33
    refreshed_queue = {item.task.id: item for item in refreshed.agent_queue.items}
    assert refreshed_queue[design.task.id].queue_state is AgentQueueState.RUNNING
    assert refreshed_queue[design.task.id].active_run_status is AgentRunStatus.RUNNING
    with pytest.raises(TaskManagementError, match="task_agent_run_already_active"):
        tasks.update_task(
            design.task.id,
            TaskUpdateRequest(
                command_id="relationships-during-active-run",
                expected_version=started.management.version,
                dependency_task_ids=[],
            ),
            manager,
        )
    repository.close()


def test_dependency_and_parent_cycles_are_rejected_atomically(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    repository, _project, manager, _member, _agent = _repository(tmp_path)
    service = TaskManagementService(repository)
    first = _create(service, manager, "cycle-a")
    second = _create(service, manager, "cycle-b")
    first_before = (first.task.status, first.task.collaboration_stage)
    first = service.update_task(
        first.task.id,
        TaskUpdateRequest(
            command_id="dependency-a-on-b",
            expected_version=first.management.version,
            dependency_task_ids=[second.task.id],
        ),
        manager,
    )

    assert (first.task.status, first.task.collaboration_stage) == first_before
    projection = repository.get_task_operations_projection(first.task.id)
    assert projection is not None
    assert projection.dependency_task_ids == (second.task.id,)

    with pytest.raises(TaskManagementError, match="task_dependency_cycle"):
        service.update_task(
            second.task.id,
            TaskUpdateRequest(
                command_id="dependency-b-on-a",
                expected_version=second.management.version,
                dependency_task_ids=[first.task.id],
            ),
            manager,
        )
    assert service.get_task(second.task.id, manager).management.version == 1

    first = service.update_task(
        first.task.id,
        TaskUpdateRequest(
            command_id="parent-a-under-b",
            expected_version=first.management.version,
            dependency_task_ids=[],
            parent_task_id=second.task.id,
        ),
        manager,
    )
    with pytest.raises(TaskManagementError, match="task_parent_cycle"):
        service.update_task(
            second.task.id,
            TaskUpdateRequest(
                command_id="parent-b-under-a",
                expected_version=second.management.version,
                parent_task_id=first.task.id,
            ),
            manager,
        )
    assert service.get_task(second.task.id, manager).management.parent_task_id is None
    with pytest.raises(TaskManagementError) as overlap:
        service.update_task(
            first.task.id,
            TaskUpdateRequest(
                command_id="overlap-parent-dependency",
                expected_version=first.management.version,
                dependency_task_ids=[second.task.id],
            ),
            manager,
        )
    assert overlap.value.code == "task_relationship_overlap"
    assert overlap.value.status_code == 422
    repository.close()


def test_concurrent_relationship_updates_cannot_commit_a_cycle(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    repository, _project, manager, _member, _agent = _repository(tmp_path)
    service = TaskManagementService(repository)
    first = _create(service, manager, "concurrent-cycle-a")
    second = _create(service, manager, "concurrent-cycle-b")

    def update(source, dependency, command):  # noqa: ANN001, ANN202
        try:
            return service.update_task(
                source.task.id,
                TaskUpdateRequest(
                    command_id=command,
                    expected_version=source.management.version,
                    dependency_task_ids=[dependency.task.id],
                ),
                manager,
            )
        except TaskManagementError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda args: update(*args),
                [
                    (first, second, "concurrent-a-on-b"),
                    (second, first, "concurrent-b-on-a"),
                ],
            )
        )

    assert sum(not isinstance(result, str) for result in results) == 1
    assert [result for result in results if isinstance(result, str)] == ["task_dependency_cycle"]
    TaskOperationsService(repository).snapshot(_query(manager.default_project_id), manager)
    repository.close()


def test_relationships_require_project_manager_and_conceal_cross_project_targets(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    repository, project, manager, member, _agent = _repository(tmp_path)
    service = TaskManagementService(repository)
    parent = _create(service, manager, "authorized-parent")
    assert "manage_relationships" in {action.value for action in parent.allowed_actions}
    assert "manage_relationships" not in {
        action.value for action in service.get_task(parent.task.id, member).allowed_actions
    }

    with pytest.raises(TaskManagementError, match="task_action_forbidden"):
        _create(
            service,
            member,
            "member-child",
            parent_task_id=parent.task.id,
        )

    other_project = repository.save_project(
        Project(
            id="project_operations_other",
            workspace_id=project.workspace_id,
            name="Other project",
            goal="Stay isolated",
            member_ids=[manager.id],
        )
    )
    manager.default_project_id = other_project.id
    repository.save_user(manager)
    foreign = _create(service, manager, "foreign")
    manager.default_project_id = project.id
    repository.save_user(manager)

    with pytest.raises(TaskManagementError) as captured:
        _create(
            service,
            manager,
            "cross-project-child",
            dependency_task_ids=[foreign.task.id],
        )
    assert captured.value.code == "task_relationship_target_not_found"
    assert captured.value.status_code == 404
    repository.close()


def test_dependencies_gate_transition_and_transactional_agent_run_claim(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    repository, _project, manager, _member, agent = _repository(tmp_path)
    service = TaskManagementService(repository)
    dependency = _create(service, manager, "run-dependency")
    dependent = _create(
        service,
        manager,
        "run-dependent",
        dependency_task_ids=[dependency.task.id],
        assignee_kind=TaskAssigneeKind.AGENT,
        assignee_id=agent.id,
    )
    planned = _transition(
        service,
        manager,
        dependent.task.id,
        dependent.management.version,
        TaskTransitionAction.PLAN,
    )
    with pytest.raises(TaskManagementError, match="task_dependencies_incomplete"):
        _transition(
            service,
            manager,
            dependent.task.id,
            planned.management.version,
            TaskTransitionAction.START,
        )

    persisted = repository.get_task(dependent.task.id)
    assert persisted is not None and persisted.management is not None
    persisted.management.delivery_stage = TaskDeliveryStage.DONE
    persisted.management.version += 1
    with repository._connect() as connection:
        connection.execute(
            "UPDATE records SET payload = ? WHERE collection = 'tasks' AND id = ?",
            (persisted.model_dump_json(), persisted.id),
        )
    done_view = service.get_task(persisted.id, manager)
    assert "reopen" not in {action.value for action in done_view.allowed_actions}
    with pytest.raises(TaskManagementError, match="task_dependencies_incomplete"):
        _transition(
            service,
            manager,
            persisted.id,
            persisted.management.version,
            TaskTransitionAction.REOPEN,
        )

    persisted.management.delivery_stage = TaskDeliveryStage.IN_PROGRESS
    persisted.management.version += 1
    with repository._connect() as connection:
        connection.execute(
            "UPDATE records SET payload = ? WHERE collection = 'tasks' AND id = ?",
            (persisted.model_dump_json(), persisted.id),
        )
    with pytest.raises(ResearchStoreConflict, match="task_dependencies_incomplete"):
        repository.claim_new_agent_run(
            AgentRun(
                id="run_dependency_gate",
                thread_id=persisted.thread_id,
                task_id=persisted.id,
                user_id=manager.id,
                workspace_id=manager.workspace_id,
                project_id=manager.default_project_id,
                input_text="must remain gated",
                status=AgentRunStatus.RUNNING,
            )
        )
    repository.close()


def test_operations_projection_does_not_expose_managed_legacy_conversation_tasks(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    repository, project, manager, member, _agent = _repository(tmp_path)
    thread = repository.save_chat_thread(
        ChatThread(
            id="thread_private_operations",
            workspace_id=project.workspace_id,
            project_id=project.id,
            user_id=manager.id,
            title="Private legacy thread",
            kind=ChatThreadKind.CONVERSATION,
        )
    )
    repository.save_task(
        Task(
            id="task_private_operations",
            thread_id=thread.id,
            intent=Intent.GENERAL_CHAT,
            title="Private managed legacy task",
            management=TaskManagementMetadataV1(
                created_by=manager.id,
                updated_by=manager.id,
            ),
        )
    )

    manager_snapshot = TaskOperationsService(repository).snapshot(_query(project.id), manager)
    member_snapshot = TaskOperationsService(repository).snapshot(_query(project.id), member)

    assert manager_snapshot.metrics.task_count == 1
    assert member_snapshot.metrics.task_count == 0
    repository.close()


def test_operations_metrics_options_and_restart_are_durable(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    repository, project, manager, _member, _agent = _repository(tmp_path)
    service = TaskManagementService(repository)
    task = _create(service, manager, "metrics", due_at=now_utc() - timedelta(days=1))
    run = repository.save_agent_run(
        AgentRun(
            id="run_operations_metrics",
            thread_id=task.task.thread_id,
            task_id=task.task.id,
            user_id=manager.id,
            workspace_id=manager.workspace_id,
            project_id=project.id,
            input_text="metrics",
            output_text="Used reviewed Memory [T1]",
            status=AgentRunStatus.COMPLETED,
            planning_mode=AgentPlanningMode.STANDARD,
        )
    )
    review = TaskReviewV1(
        id="review_operations_metrics",
        task_id=task.task.id,
        run_id=run.id,
        artifact_ids=["artifact_operations_metrics"],
        artifact_hashes=["a" * 64],
        round=1,
        status=TaskReviewStatus.ACCEPTED,
        requested_by=manager.id,
        reviewer_id=manager.id,
        task_version=task.management.version,
        version=2,
        decided_at=now_utc(),
    )
    with repository._connect() as connection:
        connection.execute(
            """
            INSERT INTO task_reviews(
                id, task_id, run_id, reviewer_id, status, round, version,
                payload, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review.id,
                review.task_id,
                review.run_id,
                review.reviewer_id,
                review.status.value,
                review.round,
                review.version,
                review.model_dump_json(),
                review.created_at.isoformat(),
                review.updated_at.isoformat(),
            ),
        )
    receipt = MemoryUseReceiptV1(
        id="memory_use_operations_metrics",
        run_id=run.id,
        task_id=task.task.id,
        memory_id="memory_operations_metrics",
        memory_kind=MemoryKind.TEAM,
        memory_layer=MemoryLayer.LONG_TERM,
        memory_record_type="memory_item",
        memory_version=1,
        memory_hash="b" * 64,
        retrieval_reason="automatic_run_context",
        retrieval_query_hash="c" * 64,
        citation_label="T1",
        agent_id=manager.personal_agent_id,
    )
    repository._upsert("memory_use_receipts", receipt)
    repository.add_memory_item(
        MemoryItem(
            id="memory_operations_accepted",
            title="Accepted operations knowledge",
            summary="Reusable project operations guidance.",
            memory_type="method",
            scope=Scope.TEAM_ACCEPTED,
            status=MemoryStatus.ACCEPTED,
            workspace_id=manager.workspace_id,
            project_id=project.id,
        )
    )

    operations = TaskOperationsService(repository)
    snapshot = operations.snapshot(_query(project.id), manager)
    assert snapshot.metrics.overdue_task_count == 1
    assert snapshot.metrics.runs_by_status[AgentRunStatus.COMPLETED] == 1
    assert snapshot.metrics.reviews_by_status[TaskReviewStatus.ACCEPTED] == 1
    assert snapshot.metrics.memory_use_count == 1
    assert snapshot.metrics.cited_memory_use_count == 1
    assert snapshot.metrics.unique_reused_memory_count == 1
    assert snapshot.metrics.accepted_team_knowledge_count == 1
    member_snapshot = operations.snapshot(_query(project.id), _member)
    assert member_snapshot.metrics.memory_use_count == 0
    assert member_snapshot.metrics.cited_memory_use_count == 0
    assert member_snapshot.metrics.accepted_team_knowledge_count == 1
    options = operations.task_options(
        TaskOptionQuery(project_id=project.id, query="metrics", page_size=1),
        manager,
    )
    assert [item.id for item in options.items] == [task.task.id]

    with repository._read_connect() as connection:
        projection_count = connection.execute(
            "SELECT COUNT(*) FROM task_operations_projection WHERE project_id = ?",
            (project.id,),
        ).fetchone()[0]
    assert projection_count == 1
    with repository._connect() as connection:
        connection.execute(
            "DELETE FROM task_operations_projection WHERE task_id = ?",
            (task.task.id,),
        )

    database = repository.db_path
    repository.close()
    reopened = SQLiteStore(database)
    restarted = TaskOperationsService(reopened).snapshot(_query(project.id), manager)
    assert restarted.metrics == snapshot.metrics
    reopened.close()
