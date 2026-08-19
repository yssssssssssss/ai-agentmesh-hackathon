from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from research_orchestration_testkit import compiled_competitive_plan, research_execution_context

from agentmesh.models import AgentRun, AgentRunStatus
from agentmesh.research_orchestration.artifacts import ArtifactDraft, ArtifactLineage, ArtifactStore
from agentmesh.research_orchestration.contracts import (
    AttemptStatus,
    ExecutionAttempt,
    ExecutionLease,
    ExecutionPlanVersion,
    InvocationState,
    ModelCallReceipt,
    RequirementVersion,
    ResearchPhase,
    ResearchStep,
    ResearchWorkflow,
    StepStatus,
    ToolInvocation,
    canonical_sha256,
)
from agentmesh.store import ResearchStoreConflict, SQLiteStore


def _pending_execution(repository: SQLiteStore, *, suffix: str = "1", now: datetime | None = None):
    current = now or datetime.now(UTC)
    run_id = f"run_execution_{suffix}"
    requirement_payload = {"goal": "compare"}
    plan_payload = {
        "steps": [
            {"step_number": 1, "actor_type": "tool"},
            {"step_number": 2, "actor_type": "skill"},
        ]
    }
    repository.save_agent_run(
        AgentRun(
            id=run_id,
            thread_id=f"thread_{suffix}",
            user_id="user_1",
            workspace_id="workspace_1",
            project_id="project_1",
            input_text="compare",
            status=AgentRunStatus.PLANNING,
            orchestration_version="research-v2",
            orchestration_mode="execute",
        )
    )
    requirement = repository.add_research_requirement_version(
        RequirementVersion(
            id=f"requirement_execution_{suffix}",
            run_id=run_id,
            version=1,
            schema_version="research-task-v2",
            task_type="competitive_research",
            payload=requirement_payload,
            content_hash=canonical_sha256(requirement_payload),
        )
    )
    plan = repository.add_research_plan_version(
        ExecutionPlanVersion(
            id=f"plan_execution_{suffix}",
            run_id=run_id,
            requirement_version_id=requirement.id,
            version=1,
            schema_version="execution-plan-v2",
            payload=plan_payload,
            plan_hash=canonical_sha256(plan_payload),
        )
    )
    attempt = repository.add_research_attempt(
        ExecutionAttempt(
            id=f"attempt_execution_{suffix}",
            run_id=run_id,
            plan_version_id=plan.id,
            attempt_number=1,
            deadline_at=current + timedelta(minutes=5),
        )
    )
    for step_number in (1, 2):
        repository.add_research_step(
            ResearchStep(
                attempt_id=attempt.id,
                step_number=step_number,
                status=StepStatus.READY,
            )
        )
    repository.create_research_workflow(
        ResearchWorkflow(
            run_id=run_id,
            phase=ResearchPhase.EXECUTION,
            active_requirement_version_id=requirement.id,
            active_plan_version_id=plan.id,
            active_attempt_id=attempt.id,
        )
    )
    return run_id, requirement, plan, attempt


def _sent_invocation(repository: SQLiteStore, *, suffix: str, now: datetime):
    run_id, requirement, plan, attempt = _pending_execution(repository, suffix=suffix, now=now)
    claimed = repository.claim_research_attempt(
        attempt.id,
        owner="worker_1",
        token="token_1",
        now=now,
    )
    assert claimed is not None
    lease = ExecutionLease(owner="worker_1", token="token_1", fencing_epoch=claimed.fencing_epoch)
    assert repository.claim_research_step(attempt.id, 1, lease=lease, now=now) is not None
    lineage = ArtifactLineage(
        run_id=run_id,
        user_id="user_1",
        workspace_id="workspace_1",
        project_id="project_1",
        requirement_version_id=requirement.id,
        plan_version_id=plan.id,
        attempt_id=attempt.id,
        step_number=1,
    )
    request_ref = ArtifactStore(repository).seal(
        lineage,
        ArtifactDraft(
            artifact_id=f"artifact_request_{suffix}",
            kind="tool_request",
            schema_version="tool-request-v1",
            content={"query": "compare"},
        ),
        lease=lease,
    )
    invocation, _created = repository.prepare_research_tool_invocation(
        ToolInvocation(
            id=f"invocation_{suffix}",
            run_id=run_id,
            plan_version_id=plan.id,
            step_number=1,
            operation_key=canonical_sha256({"run_id": run_id, "input": request_ref.content_hash}),
            resolved_input_hash=request_ref.content_hash,
            request_artifact_id=request_ref.artifact_id,
            active_attempt_id=attempt.id,
        ),
        lease=lease,
        now=now,
    )
    sent = repository.mark_research_tool_invocation_sent(invocation.id, lease=lease, sent_at=now)
    assert sent is not None
    return lineage, lease, sent


def test_compiler_publishes_manifest_reference_alongside_evidence_bindings() -> None:
    _requirement, plan = compiled_competitive_plan("run_tool_actor_schema")
    schema = plan.payload["control_snapshot"]["tool"]["published_output_schema"]["content"]

    assert schema["required"] == ["evidence_inputs", "evidence_manifest_ref"]
    assert set(schema["properties"]) == {"evidence_inputs", "evidence_manifest_ref"}


def test_attempt_claim_is_fenced_and_same_token_replay_does_not_advance_epoch(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "attempt-claim.sqlite3")
    now = datetime.now(UTC)
    _run_id, _requirement, _plan, attempt = _pending_execution(repository, now=now)

    first = repository.claim_research_attempt(
        attempt.id,
        owner="worker_1",
        token="token_1",
        now=now,
    )
    replay = repository.claim_research_attempt(
        attempt.id,
        owner="worker_1",
        token="token_1",
        now=now + timedelta(seconds=1),
    )
    loser = repository.claim_research_attempt(
        attempt.id,
        owner="worker_2",
        token="token_2",
        now=now + timedelta(seconds=1),
    )

    assert first is not None and first.status == AttemptStatus.RUNNING
    assert first.fencing_epoch == 1
    assert replay == first
    assert loser is None


def test_expired_attempt_cannot_heartbeat_and_takeover_fences_old_step_writer(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "attempt-takeover.sqlite3")
    now = datetime.now(UTC)
    _run_id, _requirement, _plan, attempt = _pending_execution(repository, now=now)
    first = repository.claim_research_attempt(
        attempt.id,
        owner="worker_1",
        token="token_1",
        now=now,
        lease_ttl=timedelta(seconds=10),
    )
    assert first is not None
    lease_1 = ExecutionLease(owner="worker_1", token="token_1", fencing_epoch=1)
    step = repository.claim_research_step(attempt.id, 1, lease=lease_1, now=now)
    assert step is not None and step.claim_epoch == 1

    assert repository.heartbeat_research_attempt(
        attempt.id,
        lease=lease_1,
        now=now + timedelta(seconds=10),
    ) is None
    second = repository.claim_research_attempt(
        attempt.id,
        owner="worker_2",
        token="token_2",
        now=now + timedelta(seconds=10),
    )
    assert second is not None and second.fencing_epoch == 2
    assert repository.compare_and_swap_research_step(
        attempt.id,
        1,
        lease=lease_1,
        expected_status=StepStatus.RUNNING,
        next_status=StepStatus.FAILED,
        error_code="late_writer",
        now=now + timedelta(seconds=11),
    ) is None


def test_steps_in_same_attempt_share_epoch_without_fencing_each_other(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "same-wave.sqlite3")
    now = datetime.now(UTC)
    _run_id, _requirement, _plan, attempt = _pending_execution(repository, now=now)
    claimed = repository.claim_research_attempt(
        attempt.id,
        owner="worker_1",
        token="token_1",
        now=now,
    )
    assert claimed is not None
    lease = ExecutionLease(owner="worker_1", token="token_1", fencing_epoch=claimed.fencing_epoch)

    first = repository.claim_research_step(attempt.id, 1, lease=lease, now=now)
    second = repository.claim_research_step(attempt.id, 2, lease=lease, now=now)

    assert first is not None and second is not None
    assert first.claim_epoch == second.claim_epoch == claimed.fencing_epoch


def test_invocation_is_persisted_sent_before_provider_boundary_and_mark_sent_is_idempotent(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "invocation-sent.sqlite3")
    now = datetime.now(UTC)
    run_id, requirement, plan, attempt = _pending_execution(repository, now=now)
    claimed = repository.claim_research_attempt(
        attempt.id,
        owner="worker_1",
        token="token_1",
        now=now,
    )
    assert claimed is not None
    lease = ExecutionLease(owner="worker_1", token="token_1", fencing_epoch=claimed.fencing_epoch)
    assert repository.claim_research_step(attempt.id, 1, lease=lease, now=now) is not None
    lineage = ArtifactLineage(
        run_id=run_id,
        user_id="user_1",
        workspace_id="workspace_1",
        project_id="project_1",
        requirement_version_id=requirement.id,
        plan_version_id=plan.id,
        attempt_id=attempt.id,
        step_number=1,
    )
    request_ref = ArtifactStore(repository).seal(
        lineage,
        ArtifactDraft(
            artifact_id="artifact_execution_request",
            kind="tool_request",
            schema_version="tool-request-v1",
            content={"query": "compare"},
        ),
        lease=lease,
    )
    invocation = ToolInvocation(
        id="invocation_execution_1",
        run_id=run_id,
        plan_version_id=plan.id,
        step_number=1,
        operation_key=canonical_sha256({"run_id": run_id, "input": request_ref.content_hash}),
        resolved_input_hash=request_ref.content_hash,
        request_artifact_id=request_ref.artifact_id,
        active_attempt_id=attempt.id,
    )

    prepared, created = repository.prepare_research_tool_invocation(
        invocation,
        lease=lease,
        now=now,
    )
    sent = repository.mark_research_tool_invocation_sent(
        prepared.id,
        lease=lease,
        sent_at=now,
    )
    replay = repository.mark_research_tool_invocation_sent(
        prepared.id,
        lease=lease,
        sent_at=now + timedelta(seconds=1),
    )

    assert created and prepared.state == InvocationState.PREPARED
    assert sent is not None and sent.state == InvocationState.SENT
    assert sent.send_count == sent.active_send_sequence == 1
    assert replay == sent


def test_cancel_closes_execution_ledger_and_late_step_commit_loses(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "cancel-ledger.sqlite3")
    now = datetime.now(UTC)
    run_id, _requirement, _plan, attempt = _pending_execution(repository, now=now)
    claimed = repository.claim_research_attempt(
        attempt.id,
        owner="worker_1",
        token="token_1",
        now=now,
    )
    assert claimed is not None
    lease = ExecutionLease(owner="worker_1", token="token_1", fencing_epoch=claimed.fencing_epoch)
    assert repository.claim_research_step(attempt.id, 1, lease=lease, now=now) is not None

    cancelled = repository.cancel_agent_run_tree(run_id, user_id="user_1")

    assert cancelled is not None and cancelled.status == AgentRunStatus.CANCELLED
    closed_attempt = repository.get_research_attempt(attempt.id)
    closed_step = repository.get_research_step(attempt.id, 1)
    assert closed_attempt is not None and closed_attempt.status == AttemptStatus.CANCELLED
    assert closed_attempt.lease_owner is None and closed_attempt.completed_at is not None
    assert closed_step is not None and closed_step.status == StepStatus.CANCELLED
    assert repository.compare_and_swap_research_step(
        attempt.id,
        1,
        lease=lease,
        expected_status=StepStatus.RUNNING,
        next_status=StepStatus.FAILED,
        error_code="late_writer",
        now=now + timedelta(seconds=1),
    ) is None


def test_sent_invocation_becomes_unknown_once_and_is_never_implicitly_resent(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "invocation-unknown.sqlite3")
    now = datetime.now(UTC)
    _lineage, lease, sent = _sent_invocation(repository, suffix="unknown", now=now)

    unknown = repository.mark_research_tool_invocation_unknown(
        sent.id,
        expected_send_sequence=1,
        expected_sent_fencing_epoch=lease.fencing_epoch,
        unknown_at=now + timedelta(seconds=1),
    )
    replay = repository.mark_research_tool_invocation_unknown(
        sent.id,
        expected_send_sequence=1,
        expected_sent_fencing_epoch=lease.fencing_epoch,
        unknown_at=now + timedelta(seconds=2),
    )
    implicit_resend = repository.mark_research_tool_invocation_sent(
        sent.id,
        lease=lease,
        sent_at=now + timedelta(seconds=3),
    )

    assert unknown is not None and unknown.state == InvocationState.UNKNOWN
    assert replay == unknown
    assert implicit_resend is None
    assert unknown.send_count == 1


def test_skill_result_and_model_receipt_settle_in_one_transaction(tmp_path) -> None:
    context = research_execution_context(tmp_path / "model-settlement.sqlite3")
    call_key = canonical_sha256({"run": context.plan.run_id, "stage": "competitive-analysis"})
    receipt = ModelCallReceipt(
        id=f"model_call_{call_key[:32]}",
        run_id=context.plan.run_id,
        owner_kind="attempt",
        owner_id=context.lineage_step_2.attempt_id or "",
        stage="competitive-analysis",
        call_key=call_key,
        requested_provider="openai_agents_sdk",
        requested_model="gpt-primary",
        actual_provider="openai_agents_sdk",
        actual_model="gpt-5.5",
        usage={"requests": 1, "total_tokens": 42},
    )
    draft = ArtifactDraft(
        artifact_id=f"artifact_skill_result_{call_key[:32]}",
        kind="skill_result",
        schema_version="competitive-analysis-output-v1",
        content={
            "summary": "verified summary",
            "facts": [],
            "inferences": [],
            "recommendations": [],
            "gaps": [],
        },
    )
    with sqlite3.connect(context.repository.db_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_model_receipt_insert
            BEFORE INSERT ON research_model_call_receipts
            BEGIN
                SELECT RAISE(ABORT, 'forced model receipt failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced model receipt failure"):
        context.artifacts.settle_model_call(
            context.lineage_step_2,
            draft,
            lease=context.lease,
            receipt=receipt,
        )

    assert context.repository.get_artifact(draft.artifact_id) is None
    assert context.repository.get_research_model_call_receipt(receipt.id) is None
    with sqlite3.connect(context.repository.db_path) as connection:
        connection.execute("DROP TRIGGER fail_model_receipt_insert")

    reference, stored_receipt = context.artifacts.settle_model_call(
        context.lineage_step_2,
        draft,
        lease=context.lease,
        receipt=receipt,
    )
    assert stored_receipt == receipt
    assert context.artifacts.settle_model_call(
        context.lineage_step_2,
        draft,
        lease=context.lease,
        receipt=receipt,
    ) == (reference, receipt)


def test_purge_command_receipt_survives_deleted_workflow_and_replays_exactly(tmp_path) -> None:
    context = research_execution_context(tmp_path / "purge-command.sqlite3", run_id="run_purge_command")
    finished = context.repository.finish_research_workflow(
        context.plan.run_id,
        expected_state_version=1,
        terminal_status=AgentRunStatus.COMPLETED,
        output_text="sensitive rendered output",
    )
    assert finished is not None
    request_hash = canonical_sha256(
        {"command_type": "purge", "run_id": context.plan.run_id, "expected_state_version": 2}
    )

    first = context.artifacts.purge_research_data_command(
        context.plan.run_id,
        actor_user_id="user_1",
        workspace_id="workspace_1",
        expected_state_version=2,
        idempotency_key="purge-command-1",
        request_hash=request_hash,
    )
    replay = context.artifacts.purge_research_data_command(
        context.plan.run_id,
        actor_user_id="user_1",
        workspace_id="workspace_1",
        expected_state_version=2,
        idempotency_key="purge-command-1",
        request_hash=request_hash,
    )

    assert replay == first
    assert first.command_type == "purge"
    assert first.response_payload["run_id"] == context.plan.run_id
    assert first.response_payload["purged"] is True
    assert context.repository.get_research_workflow(context.plan.run_id) is None
    with pytest.raises(ResearchStoreConflict, match="different research command"):
        context.artifacts.purge_research_data_command(
            context.plan.run_id,
            actor_user_id="user_1",
            workspace_id="workspace_1",
            expected_state_version=2,
            idempotency_key="purge-command-1",
            request_hash="f" * 64,
        )
