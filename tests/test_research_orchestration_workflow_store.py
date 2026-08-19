from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from agentmesh.models import AgentRun, AgentRunStatus
from agentmesh.research_orchestration.api import ResearchOwnerScope
from agentmesh.research_orchestration.artifacts import ArtifactDraft, ArtifactLineage, ArtifactStore
from agentmesh.research_orchestration.contracts import (
    AttemptStatus,
    ExecutionAttempt,
    ExecutionLease,
    ExecutionPlanVersion,
    InvocationState,
    RequirementVersion,
    ResearchCommandReceipt,
    ResearchGate,
    ResearchPhase,
    ResearchStep,
    ResearchWorkflow,
    StepStatus,
    ToolInvocation,
    canonical_sha256,
)
from agentmesh.research_orchestration.workflow import CommandMutation, PlanningMutation
from agentmesh.store import ResearchStoreConflict, SQLiteStore


def _run(run_id: str, *, turn_id: str | None = None) -> AgentRun:
    return AgentRun(
        id=run_id,
        thread_id=f"thread_{run_id}",
        user_id="user_1",
        workspace_id="workspace_1",
        project_id="project_1",
        input_text="compare competitors",
        client_turn_id=turn_id or f"turn_{run_id}",
        status=AgentRunStatus.CREATED,
        orchestration_version="research-v2",
        orchestration_mode="execute",
    )


def _owner() -> ResearchOwnerScope:
    return ResearchOwnerScope(user_id="user_1", workspace_id="workspace_1", project_id="project_1")


def _ensure(repository: SQLiteStore, run_id: str):
    return repository.ensure_workflow(
        _run(run_id),
        ResearchWorkflow(run_id=run_id, phase=ResearchPhase.REQUIREMENT),
    )


def _requirement(run_id: str, version: int = 1) -> RequirementVersion:
    payload = {"goal": f"compare-v{version}"}
    return RequirementVersion(
        id=f"requirement_{run_id}_{version}",
        run_id=run_id,
        version=version,
        schema_version="research-task-v2",
        task_type="competitive_research",
        payload=payload,
        content_hash=canonical_sha256(payload),
    )


def _plan(run_id: str, requirement: RequirementVersion, version: int = 1) -> ExecutionPlanVersion:
    payload = {
        "steps": [
            {"step_number": 1, "actor_type": "tool"},
            {"step_number": 2, "actor_type": "skill"},
        ]
    }
    return ExecutionPlanVersion(
        id=f"plan_{run_id}_{version}",
        run_id=run_id,
        requirement_version_id=requirement.id,
        version=version,
        schema_version="execution-plan-v2",
        payload=payload,
        plan_hash=canonical_sha256(payload),
    )


def _publish(repository: SQLiteStore, run_id: str):
    _ensure(repository, run_id)
    requirement = _requirement(run_id)
    plan = _plan(run_id, requirement)
    context = repository.publish_planning(
        PlanningMutation(
            run_id=run_id,
            expected_state_version=1,
            workflow=ResearchWorkflow(
                run_id=run_id,
                phase=ResearchPhase.PLANNING,
                active_gate=ResearchGate.PLAN_CONFIRMATION,
                active_requirement_version_id=requirement.id,
                active_plan_version_id=plan.id,
            ),
            requirement=requirement,
            plan=plan,
        )
    )
    return context, requirement, plan


def _receipt(run_id: str, command_type: str, key: str, *, state_version: int) -> ResearchCommandReceipt:
    request_hash = canonical_sha256({"run_id": run_id, "command_type": command_type, "key": key})
    return ResearchCommandReceipt(
        run_id=run_id,
        idempotency_key=key,
        command_type=command_type,
        request_hash=request_hash,
        response_status=200,
        response_payload={
            "run_id": run_id,
            "command_type": command_type,
            "state_version": state_version,
            "accepted": True,
            "replayed": False,
        },
    )


def test_ensure_workflow_atomically_creates_run_receipt_workflow_and_event(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "ensure.sqlite3")
    run = _run("run_ensure")
    workflow = ResearchWorkflow(run_id=run.id, phase=ResearchPhase.REQUIREMENT)

    created = repository.ensure_workflow(run, workflow)
    replayed = repository.ensure_workflow(run, workflow)

    assert created == replayed
    assert created.run.status == AgentRunStatus.PLANNING
    assert created.workflow.state_version == 1
    assert repository.get_agent_run_by_client_turn(run.user_id, run.client_turn_id or "") == created.run
    assert [event.event_type for event in repository.list_agent_run_events(run.id)] == ["run_started"]
    with pytest.raises(ResearchStoreConflict, match="identity"):
        repository.ensure_workflow(
            run.model_copy(update={"input_text": "changed"}),
            workflow,
        )


def test_ensure_workflow_rolls_back_every_object_when_workflow_insert_fails(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "ensure-rollback.sqlite3")
    run = _run("run_ensure_rollback")
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_workflow_create
            BEFORE INSERT ON research_workflows
            BEGIN
                SELECT RAISE(ABORT, 'forced workflow create failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced workflow create failure"):
        repository.ensure_workflow(run, ResearchWorkflow(run_id=run.id))

    assert repository.get_agent_run(run.id) is None
    assert repository.get_agent_run_by_client_turn(run.user_id, run.client_turn_id or "") is None
    assert repository.get_research_workflow(run.id) is None
    assert repository.list_agent_run_events(run.id) == []


def test_load_context_is_owner_hidden_ordered_and_projection_strict(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "load-context.sqlite3")
    context, requirement, plan = _publish(repository, "run_load")

    loaded = repository.load_context(context.run.id, owner=_owner())
    hidden = repository.load_context(
        context.run.id,
        owner=_owner().model_copy(update={"user_id": "other"}),
    )

    assert loaded is not None and hidden is None
    assert loaded.active_requirement == requirement
    assert loaded.active_plan == plan
    assert loaded.requirements == (requirement,)
    assert loaded.plans == (plan,)
    assert loaded.active_attempt is None and loaded.steps == () and loaded.attempt_count == 0

    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            "UPDATE research_requirement_versions SET version = 99 WHERE id = ?",
            (requirement.id,),
        )
    with pytest.raises(ResearchStoreConflict, match="integrity verification"):
        repository.load_context(context.run.id, owner=_owner())


def test_publish_planning_is_atomic_and_rejects_stale_or_wrong_lineage(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "publish.sqlite3")
    _ensure(repository, "run_publish")
    requirement = _requirement("run_publish")
    plan = _plan("run_publish", requirement)
    mutation = PlanningMutation(
        run_id="run_publish",
        expected_state_version=1,
        workflow=ResearchWorkflow(
            run_id="run_publish",
            phase=ResearchPhase.PLANNING,
            active_gate=ResearchGate.PLAN_CONFIRMATION,
            active_requirement_version_id=requirement.id,
            active_plan_version_id=plan.id,
        ),
        requirement=requirement,
        plan=plan,
    )

    context = repository.publish_planning(mutation)
    assert context.workflow.state_version == 2
    assert context.active_requirement == requirement and context.active_plan == plan
    assert context.run.status == AgentRunStatus.WAITING_PLAN_APPROVAL
    with pytest.raises(ResearchStoreConflict, match="state version"):
        repository.publish_planning(mutation)

    wrong_requirement = _requirement("run_publish", 2)
    wrong_plan = _plan("run_publish", wrong_requirement, 2).model_copy(
        update={"requirement_version_id": "missing_requirement"}
    )
    with pytest.raises(ResearchStoreConflict):
        repository.publish_planning(
            PlanningMutation(
                run_id="run_publish",
                expected_state_version=2,
                workflow=context.workflow.model_copy(
                    update={
                        "active_requirement_version_id": wrong_requirement.id,
                        "active_plan_version_id": wrong_plan.id,
                    }
                ),
                requirement=wrong_requirement,
                plan=wrong_plan,
            )
        )
    assert repository.get_research_requirement_version(wrong_requirement.id) is None


def test_publish_planning_rolls_back_requirement_when_plan_insert_fails(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "publish-rollback.sqlite3")
    _ensure(repository, "run_publish_rollback")
    requirement = _requirement("run_publish_rollback")
    plan = _plan("run_publish_rollback", requirement)
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_plan_insert
            BEFORE INSERT ON research_plan_versions
            BEGIN
                SELECT RAISE(ABORT, 'forced plan failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced plan failure"):
        repository.publish_planning(
            PlanningMutation(
                run_id="run_publish_rollback",
                expected_state_version=1,
                workflow=ResearchWorkflow(
                    run_id="run_publish_rollback",
                    phase=ResearchPhase.PLANNING,
                    active_gate=ResearchGate.PLAN_CONFIRMATION,
                    active_requirement_version_id=requirement.id,
                    active_plan_version_id=plan.id,
                ),
                requirement=requirement,
                plan=plan,
            )
        )

    assert repository.get_research_requirement_version(requirement.id) is None
    assert repository.get_research_plan_version(plan.id) is None
    workflow = repository.get_research_workflow("run_publish_rollback")
    assert workflow is not None and workflow.state_version == 1


def test_commit_command_replays_exactly_and_rejects_hash_or_version_conflicts(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "command.sqlite3")
    context, requirement, plan = _publish(repository, "run_command")
    receipt = _receipt("run_command", "confirm_plan", "confirm-1", state_version=3)
    workflow = context.workflow.model_copy(update={"active_gate": ResearchGate.NONE})
    mutation = CommandMutation(
        receipt=receipt,
        expected_state_version=2,
        workflow=workflow,
    )

    committed = repository.commit_command(mutation)
    replayed = repository.commit_command(
        CommandMutation(
            receipt=receipt.model_copy(update={"response_payload": {"ignored": True}}),
            expected_state_version=999,
            workflow=ResearchWorkflow(run_id="run_command"),
        )
    )

    assert committed.created and not replayed.created
    assert replayed.receipt == committed.receipt == receipt
    assert committed.context.workflow.state_version == replayed.context.workflow.state_version == 3
    assert committed.context.active_requirement == requirement and committed.context.active_plan == plan
    assert repository.replay_command(
        "run_command",
        owner=_owner(),
        idempotency_key=receipt.idempotency_key,
        command_type="confirm_plan",
        request_hash=receipt.request_hash,
    ) == receipt
    with pytest.raises(ResearchStoreConflict, match="different research command"):
        repository.replay_command(
            "run_command",
            owner=_owner(),
            idempotency_key=receipt.idempotency_key,
            command_type="confirm_plan",
            request_hash="f" * 64,
        )
    with pytest.raises(ResearchStoreConflict, match="state version"):
        repository.commit_command(
            CommandMutation(
                receipt=_receipt("run_command", "revise", "revise-stale", state_version=4),
                expected_state_version=2,
                workflow=workflow,
            )
        )


def _execution_mutation(run_id: str, context, plan: ExecutionPlanVersion, *, key: str = "execute-1"):
    now = datetime.now(UTC)
    attempt = ExecutionAttempt(
        id=f"attempt_{run_id}_1",
        run_id=run_id,
        plan_version_id=plan.id,
        attempt_number=1,
        deadline_at=now + timedelta(minutes=20),
        created_at=now,
        updated_at=now,
    )
    steps = (
        ResearchStep(attempt_id=attempt.id, step_number=1, status=StepStatus.READY, updated_at=now),
        ResearchStep(attempt_id=attempt.id, step_number=2, status=StepStatus.PENDING, updated_at=now),
    )
    return CommandMutation(
        receipt=_receipt(run_id, "execute", key, state_version=context.workflow.state_version + 1),
        expected_state_version=context.workflow.state_version,
        workflow=context.workflow.model_copy(
            update={
                "phase": ResearchPhase.EXECUTION,
                "active_gate": ResearchGate.NONE,
                "active_attempt_id": attempt.id,
            }
        ),
        attempt=attempt,
        steps=steps,
    )


def _mark_recovery_required(repository: SQLiteStore, context):
    old_attempt = context.active_attempt
    assert old_attempt is not None
    now = datetime.now(UTC)
    claimed_attempt = repository.claim_research_attempt(
        old_attempt.id,
        owner="worker_recovery_test",
        token="lease_recovery_test",
        now=now,
    )
    assert claimed_attempt is not None
    lease = ExecutionLease(
        owner="worker_recovery_test",
        token="lease_recovery_test",
        fencing_epoch=claimed_attempt.fencing_epoch,
    )
    assert repository.claim_research_step(old_attempt.id, 1, lease=lease, now=now) is not None
    request_ref = ArtifactStore(repository).seal(
        ArtifactLineage(
            run_id=context.run.id,
            user_id=context.run.user_id,
            workspace_id=context.run.workspace_id,
            project_id=context.run.project_id,
            requirement_version_id=context.workflow.active_requirement_version_id,
            plan_version_id=context.workflow.active_plan_version_id,
            attempt_id=old_attempt.id,
            step_number=1,
        ),
        ArtifactDraft(
            artifact_id=f"artifact_request_{context.run.id}",
            kind="tool_request",
            schema_version="tool-request-v1",
            content={"query": "compare"},
        ),
        lease=lease,
    )
    prepared, created = repository.prepare_research_tool_invocation(
        ToolInvocation(
        id=f"invocation_{context.run.id}",
        run_id=context.run.id,
        plan_version_id=old_attempt.plan_version_id,
        step_number=1,
        operation_key="1" * 64,
            resolved_input_hash=request_ref.content_hash,
            request_artifact_id=request_ref.artifact_id,
        active_attempt_id=old_attempt.id,
        ),
        lease=lease,
        now=now,
    )
    assert created
    sent = repository.mark_research_tool_invocation_sent(prepared.id, lease=lease, sent_at=now)
    assert sent is not None
    invocation = repository.mark_research_tool_invocation_unknown(
        sent.id,
        expected_send_sequence=sent.active_send_sequence,
        expected_sent_fencing_epoch=sent.sent_fencing_epoch or lease.fencing_epoch,
        unknown_at=now,
    )
    assert invocation is not None
    assert repository.enter_research_recovery_decision(old_attempt.id, error_code="tool_result_unknown", now=now)
    recovery = repository.load_context(context.run.id, owner=_owner())
    assert recovery is not None and recovery.active_attempt is not None
    return recovery.active_attempt, recovery.workflow, invocation


def test_execute_command_atomically_creates_receipt_attempt_steps_workflow_and_run(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "execute.sqlite3")
    context, _requirement_value, plan = _publish(repository, "run_execute")
    mutation = _execution_mutation("run_execute", context, plan)

    committed = repository.commit_command(mutation)

    assert committed.created
    assert committed.context.run.status == AgentRunStatus.RUNNING
    assert committed.context.active_attempt == mutation.attempt
    assert [step.status for step in committed.context.steps] == [StepStatus.READY, StepStatus.PENDING]
    assert committed.context.attempt_count == 1
    replayed = repository.commit_command(mutation)
    assert not replayed.created and replayed.context == committed.context


def test_execute_command_rolls_back_all_objects_when_step_insert_fails(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "execute-rollback.sqlite3")
    context, _requirement_value, plan = _publish(repository, "run_execute_rollback")
    mutation = _execution_mutation("run_execute_rollback", context, plan)
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_second_step
            BEFORE INSERT ON research_steps
            WHEN NEW.step_number = 2
            BEGIN
                SELECT RAISE(ABORT, 'forced step failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced step failure"):
        repository.commit_command(mutation)

    assert repository.get_research_attempt(mutation.attempt.id if mutation.attempt else "") is None
    assert repository.get_research_step(mutation.attempt.id if mutation.attempt else "", 1) is None
    assert repository.replay_command(
        "run_execute_rollback",
        owner=_owner(),
        idempotency_key=mutation.receipt.idempotency_key,
        command_type="execute",
        request_hash=mutation.receipt.request_hash,
    ) is None
    loaded = repository.load_context("run_execute_rollback", owner=_owner())
    assert loaded is not None and loaded.workflow.state_version == context.workflow.state_version
    assert loaded.run.status == AgentRunStatus.WAITING_PLAN_APPROVAL


def test_recover_retry_atomically_retires_old_attempt_and_creates_new_attempt(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "recover.sqlite3")
    context, _requirement_value, plan = _publish(repository, "run_recover")
    executed = repository.commit_command(_execution_mutation("run_recover", context, plan)).context
    recovery_attempt, recovery_workflow, invocation = _mark_recovery_required(repository, executed)
    old_attempt = executed.active_attempt
    assert old_attempt is not None
    now = datetime.now(UTC)
    retry = ExecutionAttempt(
        id="attempt_run_recover_2",
        run_id="run_recover",
        plan_version_id=plan.id,
        attempt_number=2,
        retry_of_attempt_id=old_attempt.id,
        deadline_at=now + timedelta(minutes=20),
        created_at=now,
        updated_at=now,
    )
    mutation = CommandMutation(
        receipt=_receipt(
            "run_recover",
            "recover",
            "recover-retry",
            state_version=recovery_workflow.state_version + 1,
        ),
        expected_state_version=recovery_workflow.state_version,
        workflow=recovery_workflow.model_copy(
            update={"active_gate": ResearchGate.NONE, "active_attempt_id": retry.id}
        ),
        attempt=retry,
        steps=(
            ResearchStep(attempt_id=retry.id, step_number=1, status=StepStatus.READY, updated_at=now),
            ResearchStep(attempt_id=retry.id, step_number=2, status=StepStatus.PENDING, updated_at=now),
        ),
        superseded_attempt_id=old_attempt.id,
        superseded_attempt_status=AttemptStatus.FAILED,
        recovery_invocation_id=invocation.id,
        recovery_action="retry",
    )

    committed = repository.commit_command(mutation)

    retired = repository.get_research_attempt(old_attempt.id)
    assert retired is not None and retired.status == AttemptStatus.FAILED and retired.completed_at is not None
    assert committed.context.active_attempt == retry
    assert committed.context.attempt_count == 2
    retried_invocation = repository.get_research_tool_invocation(invocation.id)
    assert retried_invocation is not None
    assert retried_invocation.active_attempt_id == retry.id
    assert retried_invocation.state == InvocationState.PREPARED
    assert retried_invocation.send_count == retried_invocation.active_send_sequence == 1
    assert retried_invocation.sent_fencing_epoch is None
    assert retried_invocation.last_sent_at is None
    assert retried_invocation.unknown_at is None
    assert retried_invocation.error_code is None
    assert retried_invocation.provider_operation_id is None
    retry_events = [
        event
        for event in repository.list_agent_run_events("run_recover")
        if event.event_type == "research_tool_invocation_retry_authorized"
    ]
    assert len(retry_events) == 1
    assert retry_events[0].payload == {
        "invocation_id": invocation.id,
        "operation_key": invocation.operation_key,
        "previous_attempt_id": old_attempt.id,
        "retry_attempt_id": retry.id,
        "previous_send_sequence": 1,
        "unknown_at": invocation.unknown_at.isoformat(),
    }
    assert all(
        repository.get_research_step(old_attempt.id, step_number).status == StepStatus.CANCELLED
        for step_number in (1, 2)
    )
    retry_now = datetime.now(UTC)
    claimed_retry = repository.claim_research_attempt(
        retry.id,
        owner="worker_retry",
        token="lease_retry",
        now=retry_now,
    )
    assert claimed_retry is not None
    retry_lease = ExecutionLease(
        owner="worker_retry",
        token="lease_retry",
        fencing_epoch=claimed_retry.fencing_epoch,
    )
    assert repository.claim_research_step(retry.id, 1, lease=retry_lease, now=retry_now) is not None
    second_send = repository.mark_research_tool_invocation_sent(
        invocation.id,
        lease=retry_lease,
        sent_at=retry_now,
    )
    stale_old_lease = ExecutionLease(
        owner="worker_recovery_test",
        token="lease_recovery_test",
        fencing_epoch=1,
    )
    assert second_send is not None and second_send.active_send_sequence == 2
    assert (
        repository.mark_research_tool_invocation_sent(
            invocation.id,
            lease=stale_old_lease,
            sent_at=retry_now,
        )
        is None
    )
    assert (
        repository.mark_research_tool_invocation_sent(
            invocation.id,
            lease=retry_lease,
            sent_at=retry_now,
        )
        == second_send
    )


def test_recover_abort_atomically_retires_attempt_and_terminates_run(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "recover-abort.sqlite3")
    context, _requirement_value, plan = _publish(repository, "run_recover_abort")
    executed = repository.commit_command(_execution_mutation("run_recover_abort", context, plan)).context
    _recovery_attempt, recovery_workflow, invocation = _mark_recovery_required(repository, executed)
    old_attempt = executed.active_attempt
    assert old_attempt is not None
    mutation = CommandMutation(
        receipt=_receipt(
            "run_recover_abort",
            "recover",
            "recover-abort",
            state_version=recovery_workflow.state_version + 1,
        ),
        expected_state_version=recovery_workflow.state_version,
        workflow=recovery_workflow.model_copy(
            update={"phase": ResearchPhase.TERMINAL, "active_gate": ResearchGate.NONE}
        ),
        superseded_attempt_id=old_attempt.id,
        superseded_attempt_status=AttemptStatus.CANCELLED,
        recovery_invocation_id=invocation.id,
        recovery_action="abort",
        terminal_status=AgentRunStatus.CANCELLED,
        error_code="recovery_aborted",
    )

    committed = repository.commit_command(mutation)

    retired = repository.get_research_attempt(old_attempt.id)
    assert retired is not None and retired.status == AttemptStatus.CANCELLED
    assert committed.context.workflow.phase == ResearchPhase.TERMINAL
    assert committed.context.run.status == AgentRunStatus.CANCELLED
    aborted_invocation = repository.get_research_tool_invocation(invocation.id)
    assert aborted_invocation is not None
    assert aborted_invocation.active_attempt_id == old_attempt.id
    assert aborted_invocation.state == InvocationState.UNKNOWN
    assert all(
        repository.get_research_step(old_attempt.id, step_number).status == StepStatus.CANCELLED
        for step_number in (1, 2)
    )
