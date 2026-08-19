from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agentmesh.models import AgentRun, AgentRunStatus
from agentmesh.research_orchestration.artifacts import (
    ArtifactDraft,
    ArtifactLineage,
    ArtifactStore,
    ArtifactStoreError,
)
from agentmesh.research_orchestration.contracts import (
    AttemptStatus,
    ExecutionAttempt,
    ExecutionLease,
    ExecutionPlanVersion,
    InvocationState,
    RequirementVersion,
    ResearchGate,
    ResearchPhase,
    ResearchStep,
    ResearchWorkflow,
    StepStatus,
    ToolInvocation,
    ToolReceipt,
    canonical_sha256,
)
from agentmesh.store import ResearchStoreConflict, SQLiteStore


@dataclass(frozen=True)
class ResearchExecutionContext:
    repository: SQLiteStore
    artifacts: ArtifactStore
    requirement: RequirementVersion
    plan: ExecutionPlanVersion
    lineage_step_1: ArtifactLineage
    lineage_step_2: ArtifactLineage
    lease: ExecutionLease


def _execution_context(database: Path, *, run_id: str) -> ResearchExecutionContext:
    now = datetime.now(UTC)
    repository = SQLiteStore(database)
    repository.save_agent_run(
        AgentRun(
            id=run_id,
            thread_id=f"thread_{run_id}",
            user_id="user_1",
            workspace_id="workspace_1",
            project_id="project_1",
            input_text="compare",
            status=AgentRunStatus.PLANNING,
            orchestration_version="research-v2",
            orchestration_mode="execute",
        )
    )
    requirement_payload = {"goal": "compare"}
    requirement = repository.add_research_requirement_version(
        RequirementVersion(
            id=f"requirement_{run_id}",
            run_id=run_id,
            version=1,
            schema_version="research-task-v2",
            task_type="competitive_research",
            payload=requirement_payload,
            content_hash=canonical_sha256(requirement_payload),
            created_at=now,
        )
    )
    plan_payload = {
        "steps": [
            {"step_number": 1, "actor_type": "tool"},
            {"step_number": 2, "actor_type": "skill"},
        ]
    }
    plan = repository.add_research_plan_version(
        ExecutionPlanVersion(
            id=f"plan_{run_id}",
            run_id=run_id,
            requirement_version_id=requirement.id,
            version=1,
            schema_version="execution-plan-v2",
            payload=plan_payload,
            plan_hash=canonical_sha256(plan_payload),
            created_at=now,
        )
    )
    attempt = repository.add_research_attempt(
        ExecutionAttempt(
            id=f"attempt_{run_id}",
            run_id=run_id,
            plan_version_id=plan.id,
            attempt_number=1,
            status=AttemptStatus.RUNNING,
            lease_owner="worker_1",
            lease_token="lease_1",
            fencing_epoch=1,
            lease_expires_at=now + timedelta(minutes=10),
            deadline_at=now + timedelta(minutes=20),
            created_at=now,
            updated_at=now,
        )
    )
    for step_number in (1, 2):
        repository.add_research_step(
            ResearchStep(
                attempt_id=attempt.id,
                step_number=step_number,
                status=StepStatus.RUNNING,
                claim_epoch=1,
                started_at=now,
                updated_at=now,
            )
        )
    repository.create_research_workflow(
        ResearchWorkflow(
            run_id=run_id,
            phase=ResearchPhase.EXECUTION,
            active_requirement_version_id=requirement.id,
            active_plan_version_id=plan.id,
            active_attempt_id=attempt.id,
            created_at=now,
            updated_at=now,
        )
    )
    common_lineage = {
        "run_id": run_id,
        "user_id": "user_1",
        "workspace_id": "workspace_1",
        "project_id": "project_1",
        "requirement_version_id": requirement.id,
        "plan_version_id": plan.id,
        "attempt_id": attempt.id,
    }
    return ResearchExecutionContext(
        repository=repository,
        artifacts=ArtifactStore(repository),
        requirement=requirement,
        plan=plan,
        lineage_step_1=ArtifactLineage(**common_lineage, step_number=1),
        lineage_step_2=ArtifactLineage(**common_lineage, step_number=2),
        lease=ExecutionLease(owner="worker_1", token="lease_1", fencing_epoch=1),
    )


def _sent_invocation(
    tmp_path,
    *,
    run_id: str,
) -> tuple[ResearchExecutionContext, ToolInvocation, ToolReceipt, ArtifactDraft]:
    context = _execution_context(tmp_path / f"{run_id}.sqlite3", run_id=run_id)
    request_ref = context.artifacts.seal(
        context.lineage_step_1,
        ArtifactDraft(
            artifact_id=f"artifact_request_{run_id}",
            kind="tool_request",
            schema_version="tool-request-v1",
            content={"query": "compare"},
        ),
        lease=context.lease,
    )
    now = datetime.now(UTC)
    invocation, created = context.repository.prepare_research_tool_invocation(
        ToolInvocation(
            id=f"invocation_{run_id}",
            run_id=run_id,
            plan_version_id=context.plan.id,
            step_number=1,
            operation_key=canonical_sha256({"run_id": run_id, "request": request_ref.content_hash}),
            resolved_input_hash=request_ref.content_hash,
            request_artifact_id=request_ref.artifact_id,
            active_attempt_id=context.lineage_step_1.attempt_id or "",
        ),
        lease=context.lease,
        now=now,
    )
    assert created
    sent = context.repository.mark_research_tool_invocation_sent(
        invocation.id,
        lease=context.lease,
        sent_at=now,
    )
    assert sent is not None
    receipt = ToolReceipt(
        provider="test-provider",
        implementation_id="test-tool",
        mode="fake",
        send_sequence=sent.active_send_sequence,
        request_id=f"request_{run_id}",
        status_code=200,
        latency_ms=1,
        result_count=1,
    )
    result = ArtifactDraft(
        artifact_id=f"artifact_tool_result_{run_id}",
        kind="tool_result",
        schema_version="tool-result-v1",
        content={"items": [{"title": "result"}]},
    )
    return context, sent, receipt, result


def _completed_execution(
    tmp_path,
    *,
    run_id: str,
    review_status: str = "pass",
    include_report: bool = True,
) -> tuple[ResearchExecutionContext, dict[str, str | None]]:
    context, sent, receipt, raw_result = _sent_invocation(tmp_path, run_id=run_id)
    context.artifacts.settle_sent_tool_invocation(
        context.lineage_step_1,
        raw_result,
        lease=context.lease,
        invocation_id=sent.id,
        receipt=receipt,
    )
    tool_output = context.artifacts.seal(
        context.lineage_step_1,
        ArtifactDraft(
            artifact_id=f"artifact_tool_actor_output_{run_id}",
            kind="tool_actor_output",
            schema_version="tool-actor-output-v2",
            content={"evidence_inputs": [], "evidence_manifest_ref": {"artifact_id": "manifest", "content_hash": "a" * 64}},
        ),
        lease=context.lease,
    )
    now = datetime.now(UTC)
    completed_tool = context.repository.compare_and_swap_research_step(
        context.lineage_step_1.attempt_id or "",
        1,
        lease=context.lease,
        expected_status=StepStatus.RUNNING,
        next_status=StepStatus.COMPLETED,
        result_artifact_id=tool_output.artifact_id,
        now=now,
    )
    assert completed_tool is not None

    skill_output = context.artifacts.seal(
        context.lineage_step_2,
        ArtifactDraft(
            artifact_id=f"artifact_skill_result_{run_id}",
            kind="skill_result",
            schema_version="competitive-analysis-output-v1",
            content={"summary": "result", "facts": [], "inferences": [], "recommendations": [], "gaps": []},
        ),
        lease=context.lease,
    )
    drafts = [
        ArtifactDraft(
            artifact_id=f"artifact_claim_ledger_{run_id}",
            kind="claim_ledger",
            schema_version="claim-ledger-v1",
            content={"claims": []},
        ),
        ArtifactDraft(
            artifact_id=f"artifact_deliverable_{run_id}",
            kind="deliverable",
            schema_version="deliverable-document-v1",
            content={"summary": "result"},
        ),
        ArtifactDraft(
            artifact_id=f"artifact_review_{run_id}",
            kind="review",
            schema_version="deterministic-review-v1",
            content={"status": review_status},
        ),
    ]
    if include_report:
        drafts.append(
            ArtifactDraft(
                artifact_id=f"artifact_report_{run_id}",
                kind="report",
                schema_version="report-document-v1",
                content={"markdown": "result", "html": "<p>result</p>"},
            )
        )
    delivery_refs = context.artifacts.seal_bundle(
        context.lineage_step_2,
        drafts,
        lease=context.lease,
    )
    completed_skill = context.repository.compare_and_swap_research_step(
        context.lineage_step_2.attempt_id or "",
        2,
        lease=context.lease,
        expected_status=StepStatus.RUNNING,
        next_status=StepStatus.COMPLETED,
        result_artifact_id=skill_output.artifact_id,
        now=datetime.now(UTC),
    )
    assert completed_skill is not None
    by_kind = {draft.kind: reference.artifact_id for draft, reference in zip(drafts, delivery_refs, strict=True)}
    return context, {
        "claim_ledger": by_kind["claim_ledger"],
        "deliverable": by_kind["deliverable"],
        "review": by_kind["review"],
        "report": by_kind.get("report"),
    }


def test_unknown_invocation_requires_explicit_reconciliation(tmp_path) -> None:
    context, sent, receipt, result = _sent_invocation(tmp_path, run_id="unknown_explicit")
    unknown_at = datetime.now(UTC)
    unknown = context.repository.mark_research_tool_invocation_unknown(
        sent.id,
        expected_send_sequence=sent.active_send_sequence,
        expected_sent_fencing_epoch=context.lease.fencing_epoch,
        unknown_at=unknown_at,
    )
    assert unknown is not None and unknown.state == InvocationState.UNKNOWN

    with pytest.raises(ArtifactStoreError, match="artifact_invocation_invalid"):
        context.artifacts.settle_sent_tool_invocation(
            context.lineage_step_1,
            result,
            lease=context.lease,
            invocation_id=sent.id,
            receipt=receipt,
        )

    reference, reconciled = context.artifacts.settle_reconciled_tool_invocation(
        context.lineage_step_1,
        result,
        lease=context.lease,
        invocation_id=sent.id,
        receipt=receipt,
    )
    replay = context.artifacts.settle_reconciled_tool_invocation(
        context.lineage_step_1,
        result,
        lease=context.lease,
        invocation_id=sent.id,
        receipt=receipt,
    )

    assert reconciled.state == InvocationState.ACKNOWLEDGED
    assert reconciled.unknown_at == unknown_at
    assert replay == (reference, reconciled)


def test_expired_takeover_marks_sent_unknown_and_reclaims_running_step(tmp_path) -> None:
    context, sent, _receipt, _result = _sent_invocation(tmp_path, run_id="takeover")
    first_attempt = context.repository.get_research_attempt(context.lineage_step_1.attempt_id or "")
    assert first_attempt is not None and first_attempt.lease_expires_at is not None
    takeover_at = first_attempt.lease_expires_at

    claimed = context.repository.claim_research_attempt(
        first_attempt.id,
        owner="worker_2",
        token="lease_2",
        now=takeover_at,
    )
    assert claimed is not None and claimed.fencing_epoch == 2
    unknown = context.repository.get_research_tool_invocation(sent.id)
    assert unknown is not None and unknown.state == InvocationState.UNKNOWN
    assert unknown.unknown_at == takeover_at

    lease_2 = ExecutionLease(owner="worker_2", token="lease_2", fencing_epoch=2)
    reclaimed = context.repository.claim_research_step(
        first_attempt.id,
        1,
        lease=lease_2,
        now=takeover_at,
    )
    assert reclaimed is not None and reclaimed.claim_epoch == 2
    assert reclaimed.started_at is not None

    assert context.repository.compare_and_swap_research_step(
        first_attempt.id,
        1,
        lease=context.lease,
        expected_status=StepStatus.RUNNING,
        next_status=StepStatus.FAILED,
        error_code="late_writer",
        now=takeover_at,
    ) is None


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("id", "invocation_tampered"),
        ("receipt_payload", "not-json"),
        ("created_at", "2000-01-01T00:00:00+00:00"),
        ("updated_at", "2000-01-01T00:00:00+00:00"),
    ],
)
def test_invocation_projection_tampering_is_rejected(tmp_path, column: str, value: str) -> None:
    context, sent, _receipt, _result = _sent_invocation(tmp_path, run_id=f"projection_{column}")
    with sqlite3.connect(context.repository.db_path) as connection:
        connection.execute(
            f"UPDATE research_tool_invocations SET {column} = ? WHERE id = ?",
            (value, sent.id),
        )

    lookup_id = value if column == "id" else sent.id
    with pytest.raises(ArtifactStoreError, match="artifact_invocation_invalid"):
        context.artifacts.read_verified_tool_invocation(lookup_id)


def test_takeover_rolls_back_when_unknown_projection_update_fails(tmp_path) -> None:
    context, sent, _receipt, _result = _sent_invocation(tmp_path, run_id="takeover_rollback")
    attempt = context.repository.get_research_attempt(context.lineage_step_1.attempt_id or "")
    assert attempt is not None and attempt.lease_expires_at is not None
    with sqlite3.connect(context.repository.db_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_takeover_unknown
            BEFORE UPDATE OF state ON research_tool_invocations
            BEGIN
                SELECT RAISE(ABORT, 'forced takeover failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced takeover failure"):
        context.repository.claim_research_attempt(
            attempt.id,
            owner="worker_2",
            token="lease_2",
            now=attempt.lease_expires_at,
        )

    assert context.repository.get_research_attempt(attempt.id) == attempt
    assert context.repository.get_research_tool_invocation(sent.id) == sent


def test_invocation_projection_conflict_uses_store_integrity_error(tmp_path) -> None:
    context, sent, _receipt, _result = _sent_invocation(tmp_path, run_id="store_projection")
    with sqlite3.connect(context.repository.db_path) as connection:
        connection.execute(
            "UPDATE research_tool_invocations SET updated_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", sent.id),
        )

    with pytest.raises(ResearchStoreConflict, match="integrity verification"):
        context.repository.mark_research_tool_invocation_unknown(
            sent.id,
            expected_send_sequence=sent.active_send_sequence,
            expected_sent_fencing_epoch=sent.sent_fencing_epoch or 0,
            unknown_at=datetime.now(UTC) + timedelta(seconds=1),
        )


def test_reconciliation_requires_current_lease_and_matching_send_sequence(tmp_path) -> None:
    context, sent, receipt, result = _sent_invocation(tmp_path, run_id="reconcile_fence")
    with pytest.raises(ArtifactStoreError, match="artifact_invocation_invalid"):
        context.artifacts.settle_reconciled_tool_invocation(
            context.lineage_step_1,
            result,
            lease=context.lease,
            invocation_id=sent.id,
            receipt=receipt,
        )
    attempt = context.repository.get_research_attempt(context.lineage_step_1.attempt_id or "")
    assert attempt is not None and attempt.lease_expires_at is not None
    lease_2 = ExecutionLease(owner="worker_2", token="lease_2", fencing_epoch=2)
    assert context.repository.claim_research_attempt(
        attempt.id,
        owner=lease_2.owner,
        token=lease_2.token,
        now=attempt.lease_expires_at,
    ) is not None
    assert context.repository.claim_research_step(
        attempt.id,
        1,
        lease=lease_2,
        now=attempt.lease_expires_at,
    ) is not None

    with pytest.raises(ArtifactStoreError, match="artifact_lease_lost"):
        context.artifacts.settle_reconciled_tool_invocation(
            context.lineage_step_1,
            result,
            lease=context.lease,
            invocation_id=sent.id,
            receipt=receipt,
        )
    with pytest.raises(ArtifactStoreError, match="artifact_invocation_invalid"):
        context.artifacts.settle_reconciled_tool_invocation(
            context.lineage_step_1,
            result,
            lease=lease_2,
            invocation_id=sent.id,
            receipt=receipt.model_copy(update={"send_sequence": receipt.send_sequence + 1}),
        )

    _reference, reconciled = context.artifacts.settle_reconciled_tool_invocation(
        context.lineage_step_1,
        result,
        lease=lease_2,
        invocation_id=sent.id,
        receipt=receipt,
    )
    assert reconciled.sent_fencing_epoch == 1
    assert reconciled.unknown_at == attempt.lease_expires_at


def test_valid_but_mismatched_receipt_projection_is_rejected(tmp_path) -> None:
    context, sent, receipt, result = _sent_invocation(tmp_path, run_id="receipt_projection")
    context.artifacts.settle_sent_tool_invocation(
        context.lineage_step_1,
        result,
        lease=context.lease,
        invocation_id=sent.id,
        receipt=receipt,
    )
    with sqlite3.connect(context.repository.db_path) as connection:
        connection.execute(
            "UPDATE research_tool_invocations SET receipt_payload = ? WHERE id = ?",
            (receipt.model_copy(update={"request_id": "different"}).model_dump_json(), sent.id),
        )

    with pytest.raises(ResearchStoreConflict, match="integrity verification"):
        context.repository.get_research_tool_invocation(sent.id)


def test_reconciliation_rolls_back_artifact_when_ack_update_fails(tmp_path) -> None:
    context, sent, receipt, result = _sent_invocation(tmp_path, run_id="reconcile_rollback")
    unknown = context.repository.mark_research_tool_invocation_unknown(
        sent.id,
        expected_send_sequence=sent.active_send_sequence,
        expected_sent_fencing_epoch=context.lease.fencing_epoch,
        unknown_at=datetime.now(UTC),
    )
    assert unknown is not None
    with sqlite3.connect(context.repository.db_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_reconciled_ack
            BEFORE UPDATE OF state ON research_tool_invocations
            WHEN NEW.state = 'acknowledged'
            BEGIN
                SELECT RAISE(ABORT, 'forced reconciled ack failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced reconciled ack failure"):
        context.artifacts.settle_reconciled_tool_invocation(
            context.lineage_step_1,
            result,
            lease=context.lease,
            invocation_id=sent.id,
            receipt=receipt,
        )

    assert context.repository.get_artifact(result.artifact_id) is None
    assert context.repository.get_research_tool_invocation(sent.id) == unknown


def test_strict_success_finish_atomically_closes_attempt_workflow_and_run(tmp_path) -> None:
    context, artifacts = _completed_execution(tmp_path, run_id="finish_success")
    completed_at = datetime.now(UTC)

    finished = context.repository.finish_research_execution(
        context.plan.run_id,
        attempt_id=context.lineage_step_1.attempt_id or "",
        lease=context.lease,
        expected_state_version=1,
        claim_ledger_artifact_id=artifacts["claim_ledger"] or "",
        deliverable_artifact_id=artifacts["deliverable"] or "",
        review_artifact_id=artifacts["review"] or "",
        report_artifact_id=artifacts["report"],
        terminal_status=AgentRunStatus.COMPLETED,
        output_text="result",
        completed_at=completed_at,
    )

    assert finished is not None
    workflow, run = finished
    attempt = context.repository.get_research_attempt(context.lineage_step_1.attempt_id or "")
    assert attempt is not None and attempt.status == AttemptStatus.COMPLETED
    assert attempt.lease_owner is None and attempt.lease_token is None and attempt.lease_expires_at is None
    assert attempt.completed_at == completed_at
    assert workflow.phase == ResearchPhase.TERMINAL and workflow.state_version == 2
    assert run.status == AgentRunStatus.COMPLETED and run.output_text == "result"
    assert [event.event_type for event in context.repository.list_agent_run_events(run.id)[-3:]] == [
        "research_attempt_completed",
        "research_updated",
        "run_completed",
    ]


def test_strict_success_finish_rejects_stale_lease_incomplete_steps_and_wrong_artifacts(tmp_path) -> None:
    incomplete = _execution_context(tmp_path / "finish_incomplete.sqlite3", run_id="finish_incomplete")
    finish_kwargs = {
        "attempt_id": incomplete.lineage_step_1.attempt_id or "",
        "expected_state_version": 1,
        "claim_ledger_artifact_id": "missing_claims",
        "deliverable_artifact_id": "missing_deliverable",
        "review_artifact_id": "missing_review",
        "completed_at": datetime.now(UTC),
    }
    assert incomplete.repository.finish_research_execution(
        incomplete.plan.run_id,
        lease=incomplete.lease,
        **finish_kwargs,
    ) is None

    complete, artifacts = _completed_execution(tmp_path, run_id="finish_rejections")
    assert complete.repository.finish_research_execution(
        complete.plan.run_id,
        attempt_id=complete.lineage_step_1.attempt_id or "",
        lease=ExecutionLease(owner="stale", token="stale", fencing_epoch=1),
        expected_state_version=1,
        claim_ledger_artifact_id=artifacts["claim_ledger"] or "",
        deliverable_artifact_id=artifacts["deliverable"] or "",
        review_artifact_id=artifacts["review"] or "",
        completed_at=datetime.now(UTC),
    ) is None
    with pytest.raises(ResearchStoreConflict, match="Artifact"):
        complete.repository.finish_research_execution(
            complete.plan.run_id,
            attempt_id=complete.lineage_step_1.attempt_id or "",
            lease=complete.lease,
            expected_state_version=1,
            claim_ledger_artifact_id="missing_claims",
            deliverable_artifact_id=artifacts["deliverable"] or "",
            review_artifact_id=artifacts["review"] or "",
            completed_at=datetime.now(UTC),
        )
    with pytest.raises(ResearchStoreConflict, match="distinct|provenance"):
        complete.repository.finish_research_execution(
            complete.plan.run_id,
            attempt_id=complete.lineage_step_1.attempt_id or "",
            lease=complete.lease,
            expected_state_version=1,
            claim_ledger_artifact_id=artifacts["claim_ledger"] or "",
            deliverable_artifact_id=artifacts["claim_ledger"] or "",
            review_artifact_id=artifacts["review"] or "",
            completed_at=datetime.now(UTC),
        )


def test_strict_success_finish_rejects_tampered_delivery_and_rolls_back_on_write_failure(tmp_path) -> None:
    tampered, artifacts = _completed_execution(tmp_path, run_id="finish_tampered")
    with sqlite3.connect(tampered.repository.db_path) as connection:
        row = connection.execute(
            "SELECT payload FROM artifacts WHERE id = ?",
            (artifacts["deliverable"],),
        ).fetchone()
        payload = json.loads(row[0])
        payload["content"] = '{"summary":"tampered"}'
        connection.execute(
            "UPDATE artifacts SET payload = ? WHERE id = ?",
            (json.dumps(payload), artifacts["deliverable"]),
        )
    with pytest.raises(ResearchStoreConflict, match="integrity verification"):
        tampered.repository.finish_research_execution(
            tampered.plan.run_id,
            attempt_id=tampered.lineage_step_1.attempt_id or "",
            lease=tampered.lease,
            expected_state_version=1,
            claim_ledger_artifact_id=artifacts["claim_ledger"] or "",
            deliverable_artifact_id=artifacts["deliverable"] or "",
            review_artifact_id=artifacts["review"] or "",
            completed_at=datetime.now(UTC),
        )

    rollback, rollback_artifacts = _completed_execution(tmp_path, run_id="finish_rollback")
    with sqlite3.connect(rollback.repository.db_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_finish_run
            BEFORE UPDATE ON agent_runs
            BEGIN
                SELECT RAISE(ABORT, 'forced finish failure');
            END
            """
        )
    with pytest.raises(sqlite3.IntegrityError, match="forced finish failure"):
        rollback.repository.finish_research_execution(
            rollback.plan.run_id,
            attempt_id=rollback.lineage_step_1.attempt_id or "",
            lease=rollback.lease,
            expected_state_version=1,
            claim_ledger_artifact_id=rollback_artifacts["claim_ledger"] or "",
            deliverable_artifact_id=rollback_artifacts["deliverable"] or "",
            review_artifact_id=rollback_artifacts["review"] or "",
            completed_at=datetime.now(UTC),
        )
    attempt = rollback.repository.get_research_attempt(rollback.lineage_step_1.attempt_id or "")
    workflow = rollback.repository.get_research_workflow(rollback.plan.run_id)
    run = rollback.repository.get_agent_run(rollback.plan.run_id)
    assert attempt is not None and attempt.status == AttemptStatus.RUNNING
    assert workflow is not None and workflow.phase == ResearchPhase.EXECUTION
    assert run is not None and run.status == AgentRunStatus.RUNNING


def test_failure_finish_requires_failed_step_and_closes_atomically(tmp_path) -> None:
    context = _execution_context(tmp_path / "finish_failure.sqlite3", run_id="finish_failure")
    for step_number in (1, 2):
        assert context.repository.compare_and_swap_research_step(
            context.lineage_step_1.attempt_id or "",
            step_number,
            lease=context.lease,
            expected_status=StepStatus.RUNNING,
            next_status=StepStatus.FAILED,
            error_code=f"step_{step_number}_failed",
            now=datetime.now(UTC),
        ) is not None

    finished = context.repository.fail_research_execution(
        context.plan.run_id,
        attempt_id=context.lineage_step_1.attempt_id or "",
        lease=context.lease,
        expected_state_version=1,
        error_code="execution_failed",
        completed_at=datetime.now(UTC),
    )

    assert finished is not None
    workflow, run = finished
    attempt = context.repository.get_research_attempt(context.lineage_step_1.attempt_id or "")
    assert attempt is not None and attempt.status == AttemptStatus.FAILED and attempt.lease_owner is None
    assert workflow.phase == ResearchPhase.TERMINAL
    assert run.status == AgentRunStatus.FAILED and run.error_code == "execution_failed"


def test_failure_finish_accepts_completed_steps_only_for_blocking_review(tmp_path) -> None:
    context, artifacts = _completed_execution(
        tmp_path,
        run_id="finish_review_block",
        review_status="block",
        include_report=False,
    )
    finished = context.repository.fail_research_execution(
        context.plan.run_id,
        attempt_id=context.lineage_step_1.attempt_id or "",
        lease=context.lease,
        expected_state_version=1,
        error_code="deterministic_review_blocked",
        review_artifact_id=artifacts["review"],
        completed_at=datetime.now(UTC),
    )
    assert finished is not None and finished[1].status == AgentRunStatus.FAILED


def test_expired_attempt_scan_filters_runtime_state_and_detects_corruption(tmp_path) -> None:
    candidate = _execution_context(tmp_path / "scan_candidate.sqlite3", run_id="scan_candidate")
    attempt = candidate.repository.get_research_attempt(candidate.lineage_step_1.attempt_id or "")
    assert attempt is not None and attempt.lease_expires_at is not None
    assert candidate.repository.list_expired_research_attempt_ids(attempt.lease_expires_at) == [attempt.id]

    gated = _execution_context(tmp_path / "scan_gated.sqlite3", run_id="scan_gated")
    gated_attempt = gated.repository.get_research_attempt(gated.lineage_step_1.attempt_id or "")
    gated_workflow = gated.repository.get_research_workflow(gated.plan.run_id)
    assert gated_attempt is not None and gated_attempt.lease_expires_at is not None and gated_workflow is not None
    gated_workflow.active_gate = ResearchGate.RECOVERY_DECISION
    with sqlite3.connect(gated.repository.db_path) as connection:
        connection.execute(
            "UPDATE research_workflows SET active_gate = ?, payload = ? WHERE run_id = ?",
            (gated_workflow.active_gate.value, gated_workflow.model_dump_json(), gated.plan.run_id),
        )
    assert gated.repository.list_expired_research_attempt_ids(gated_attempt.lease_expires_at) == []

    wrong_mode = _execution_context(tmp_path / "scan_mode.sqlite3", run_id="scan_mode")
    wrong_mode_attempt = wrong_mode.repository.get_research_attempt(wrong_mode.lineage_step_1.attempt_id or "")
    wrong_mode_run = wrong_mode.repository.get_agent_run(wrong_mode.plan.run_id)
    assert wrong_mode_attempt is not None and wrong_mode_attempt.lease_expires_at is not None and wrong_mode_run is not None
    wrong_mode_run.orchestration_mode = "off"
    wrong_mode.repository.save_agent_run(wrong_mode_run)
    assert wrong_mode.repository.list_expired_research_attempt_ids(wrong_mode_attempt.lease_expires_at) == []

    expired_deadline = _execution_context(tmp_path / "scan_deadline.sqlite3", run_id="scan_deadline")
    deadline_attempt = expired_deadline.repository.get_research_attempt(expired_deadline.lineage_step_1.attempt_id or "")
    assert deadline_attempt is not None and deadline_attempt.lease_expires_at is not None
    deadline_attempt.deadline_at = deadline_attempt.lease_expires_at
    with sqlite3.connect(expired_deadline.repository.db_path) as connection:
        connection.execute(
            "UPDATE research_attempts SET payload = ? WHERE id = ?",
            (deadline_attempt.model_dump_json(), deadline_attempt.id),
        )
    assert expired_deadline.repository.list_expired_research_attempt_ids(deadline_attempt.lease_expires_at) == []

    corrupt = _execution_context(tmp_path / "scan_corrupt.sqlite3", run_id="scan_corrupt")
    corrupt_attempt = corrupt.repository.get_research_attempt(corrupt.lineage_step_1.attempt_id or "")
    assert corrupt_attempt is not None and corrupt_attempt.lease_expires_at is not None
    with sqlite3.connect(corrupt.repository.db_path) as connection:
        connection.execute(
            "UPDATE research_attempts SET updated_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", corrupt_attempt.id),
        )
    with pytest.raises(ResearchStoreConflict, match="integrity verification"):
        corrupt.repository.list_expired_research_attempt_ids(corrupt_attempt.lease_expires_at)
