from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from agentmesh.models import AgentRun, AgentRunStatus, Artifact, ArtifactVerificationState
from agentmesh.research_orchestration.artifacts import (
    MAX_ARTIFACT_BYTES,
    ArtifactDraft,
    ArtifactLease,
    ArtifactLineage,
    ArtifactReaderScope,
    ArtifactRef,
    ArtifactStore,
    ArtifactStoreError,
)
from agentmesh.research_orchestration.contracts import (
    AttemptStatus,
    ExecutionAttempt,
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
class ArtifactContext:
    repository: SQLiteStore
    artifacts: ArtifactStore
    lineage: ArtifactLineage
    lease: ArtifactLease


def _execution_context(
    database,
    *,
    suffix: str = "1",
    mode: str = "execute",
    gate: ResearchGate = ResearchGate.NONE,
    lease_expires_at: datetime | None = None,
    claim_epoch: int = 1,
) -> ArtifactContext:
    repository = SQLiteStore(database)
    run_id = f"run_{suffix}"
    requirement_id = f"requirement_{suffix}"
    plan_id = f"plan_{suffix}"
    attempt_id = f"attempt_{suffix}"
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
            orchestration_mode=mode,
        )
    )
    requirement_payload = {"goal": "compare"}
    requirement = repository.add_research_requirement_version(
        RequirementVersion(
            id=requirement_id,
            run_id=run_id,
            version=1,
            schema_version="research-task-v2",
            task_type="competitive_research",
            payload=requirement_payload,
            content_hash=canonical_sha256(requirement_payload),
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
            id=plan_id,
            run_id=run_id,
            requirement_version_id=requirement.id,
            version=1,
            schema_version="execution-plan-v2",
            plan_hash=canonical_sha256(plan_payload),
            payload=plan_payload,
        )
    )
    now = datetime.now(UTC)
    attempt = repository.add_research_attempt(
        ExecutionAttempt(
            id=attempt_id,
            run_id=run_id,
            plan_version_id=plan.id,
            attempt_number=1,
            status=AttemptStatus.RUNNING,
            lease_owner="worker_1",
            lease_token="lease_1",
            fencing_epoch=1,
            lease_expires_at=lease_expires_at or now + timedelta(minutes=10),
            deadline_at=now + timedelta(minutes=20),
        )
    )
    repository.add_research_step(
        ResearchStep(
            attempt_id=attempt.id,
            step_number=1,
            status=StepStatus.RUNNING,
            claim_epoch=claim_epoch,
            started_at=now,
        )
    )
    repository.create_research_workflow(
        ResearchWorkflow(
            run_id=run_id,
            phase=ResearchPhase.EXECUTION,
            active_gate=gate,
            active_requirement_version_id=requirement.id,
            active_plan_version_id=plan.id,
            active_attempt_id=attempt.id,
        )
    )
    return ArtifactContext(
        repository=repository,
        artifacts=ArtifactStore(repository),
        lineage=ArtifactLineage(
            run_id=run_id,
            user_id="user_1",
            workspace_id="workspace_1",
            project_id="project_1",
            requirement_version_id=requirement.id,
            plan_version_id=plan.id,
            attempt_id=attempt.id,
            step_number=1,
        ),
        lease=ArtifactLease(owner="worker_1", token="lease_1", fencing_epoch=1),
    )


def _assert_error(code: str, callback) -> None:
    with pytest.raises(ArtifactStoreError) as caught:
        callback()
    assert caught.value.code == code


def test_stage_seal_read_and_replay_are_idempotent(tmp_path) -> None:
    context = _execution_context(tmp_path / "artifacts.sqlite3")
    staged = context.artifacts.stage(
        context.lineage,
        artifact_id="artifact_tool_request",
        kind="tool_request",
        schema_version="tool-request-v1",
        lease=context.lease,
    )
    replayed_stage = context.artifacts.stage(
        context.lineage,
        artifact_id=staged.id,
        kind="tool_request",
        schema_version="tool-request-v1",
        lease=context.lease,
    )
    assert replayed_stage == staged

    draft = ArtifactDraft(
        artifact_id=staged.id,
        kind="tool_request",
        schema_version="tool-request-v1",
        content='{"query":"compare","limit":2}',
    )
    reference = context.artifacts.seal(context.lineage, draft, lease=context.lease)
    replayed_reference = context.artifacts.seal(context.lineage, draft, lease=context.lease)
    artifact = context.artifacts.read_verified(
        reference,
        scope=context.lineage,
        expected_kind="tool_request",
        expected_schema_version="tool-request-v1",
    )

    assert replayed_reference == reference
    assert artifact.content == '{"limit":2,"query":"compare"}'
    assert artifact.content_hash == hashlib.sha256(artifact.content.encode()).hexdigest()
    event_types = [event.event_type for event in context.repository.list_agent_run_events(context.lineage.run_id)]
    assert event_types.count("artifact_staged") == 1
    assert event_types.count("research_artifacts_sealed") == 1


def test_bundle_validation_and_quota_fail_without_partial_writes(tmp_path) -> None:
    context = _execution_context(tmp_path / "bundle.sqlite3")
    drafts = [
        ArtifactDraft(
            artifact_id="artifact_good",
            kind="tool_result",
            schema_version="web-research-output-v1",
            content={"content": "safe"},
        ),
        ArtifactDraft(
            artifact_id="artifact_sensitive",
            kind="tool_result",
            schema_version="web-research-output-v1",
            content={"content": "person@example.com"},
        ),
    ]
    _assert_error(
        "artifact_sensitive_content",
        lambda: context.artifacts.seal_bundle(context.lineage, drafts, lease=context.lease),
    )
    assert context.repository.get_artifact("artifact_good") is None
    assert context.repository.get_artifact("artifact_sensitive") is None

    _assert_error(
        "artifact_size_limit",
        lambda: context.artifacts.seal(
            context.lineage,
            ArtifactDraft(
                artifact_id="artifact_too_large",
                kind="tool_result",
                schema_version="text-v1",
                content_type="text/plain",
                content="x" * (MAX_ARTIFACT_BYTES + 1),
            ),
            lease=context.lease,
        ),
    )
    assert context.repository.get_artifact("artifact_too_large") is None


def test_run_quota_counts_final_bundle_bytes_without_double_counting_replay(tmp_path) -> None:
    context = _execution_context(tmp_path / "quota.sqlite3")
    drafts = [
        ArtifactDraft(
            artifact_id=f"artifact_megabyte_{index}",
            kind="tool_result",
            schema_version="text-v1",
            content_type="text/plain",
            content=chr(65 + index) * MAX_ARTIFACT_BYTES,
        )
        for index in range(5)
    ]
    references = context.artifacts.seal_bundle(context.lineage, drafts, lease=context.lease)
    assert context.artifacts.seal_bundle(context.lineage, drafts, lease=context.lease) == references

    _assert_error(
        "artifact_run_quota",
        lambda: context.artifacts.seal(
            context.lineage,
            ArtifactDraft(
                artifact_id="artifact_over_quota",
                kind="tool_result",
                schema_version="text-v1",
                content_type="text/plain",
                content="z",
            ),
            lease=context.lease,
        ),
    )
    assert context.repository.get_artifact("artifact_over_quota") is None


def test_scope_reference_and_owner_mismatch_do_not_invalidate_valid_artifact(tmp_path) -> None:
    context = _execution_context(tmp_path / "scope.sqlite3")
    reference = context.artifacts.seal(
        context.lineage,
        ArtifactDraft(
            artifact_id="artifact_scoped",
            kind="tool_result",
            schema_version="result-v1",
            content={"value": "safe"},
        ),
        lease=context.lease,
    )
    wrong_lineage = context.lineage.model_copy(update={"project_id": "project_other"})
    _assert_error(
        "artifact_not_found",
        lambda: context.artifacts.read_verified(reference, scope=wrong_lineage),
    )
    _assert_error(
        "artifact_reference_mismatch",
        lambda: context.artifacts.read_verified(
            ArtifactRef(artifact_id=reference.artifact_id, content_hash="f" * 64),
            scope=context.lineage,
        ),
    )
    _assert_error(
        "artifact_not_found",
        lambda: context.artifacts.read_verified_for_owner(
            reference.artifact_id,
            reader_scope=ArtifactReaderScope(user_id="user_other", workspace_id="workspace_1"),
        ),
    )
    assert context.artifacts.read_verified(reference, scope=context.lineage).id == reference.artifact_id


def test_wrong_or_expired_execution_fence_writes_nothing(tmp_path) -> None:
    context = _execution_context(tmp_path / "lease.sqlite3")
    for index, lease in enumerate(
        (
            ArtifactLease(owner="worker_other", token="lease_1", fencing_epoch=1),
            ArtifactLease(owner="worker_1", token="lease_other", fencing_epoch=1),
            ArtifactLease(owner="worker_1", token="lease_1", fencing_epoch=2),
        )
    ):
        _assert_error(
            "artifact_lease_lost",
            lambda lease=lease, index=index: context.artifacts.seal(
                context.lineage,
                ArtifactDraft(
                    artifact_id=f"artifact_wrong_lease_{index}",
                    kind="tool_result",
                    schema_version="result-v1",
                    content={"value": index},
                ),
                lease=lease,
            ),
        )

    expired = _execution_context(
        tmp_path / "expired.sqlite3",
        suffix="expired",
        lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    _assert_error(
        "artifact_lease_lost",
        lambda: expired.artifacts.seal(
            expired.lineage,
            ArtifactDraft(
                artifact_id="artifact_expired",
                kind="tool_result",
                schema_version="result-v1",
                content={"value": "late"},
            ),
            lease=expired.lease,
        ),
    )
    assert context.repository.get_artifact("artifact_wrong_lease_0") is None
    assert expired.repository.get_artifact("artifact_expired") is None


def test_off_preview_gate_and_terminal_workflows_block_execution_artifacts(tmp_path) -> None:
    off = _execution_context(tmp_path / "off.sqlite3", suffix="off", mode="off")
    preview = _execution_context(tmp_path / "preview.sqlite3", suffix="preview", mode="preview")
    gated = _execution_context(
        tmp_path / "gated.sqlite3",
        suffix="gated",
        gate=ResearchGate.TOOL_APPROVAL,
    )
    terminal = _execution_context(tmp_path / "terminal.sqlite3", suffix="terminal")
    assert terminal.repository.finish_research_workflow(
        terminal.lineage.run_id,
        expected_state_version=1,
        terminal_status=AgentRunStatus.CANCELLED,
    ) is not None

    for index, context in enumerate((off, preview, gated, terminal)):
        _assert_error(
            "artifact_write_blocked",
            lambda context=context, index=index: context.artifacts.seal(
                context.lineage,
                ArtifactDraft(
                    artifact_id=f"artifact_blocked_{index}",
                    kind="tool_result",
                    schema_version="result-v1",
                    content={"value": index},
                ),
                lease=context.lease,
            ),
        )


def test_tampering_invalidates_once_and_blocks_all_later_reads(tmp_path) -> None:
    mutations = ("payload", "content_hash", "size_bytes", "plan_version_id")
    for mutation in mutations:
        context = _execution_context(tmp_path / mutation / "tamper.sqlite3", suffix=mutation)
        reference = context.artifacts.seal(
            context.lineage,
            ArtifactDraft(
                artifact_id=f"artifact_{mutation}",
                kind="tool_result",
                schema_version="result-v1",
                content={"value": "safe"},
            ),
            lease=context.lease,
        )
        with sqlite3.connect(context.repository.db_path) as connection:
            if mutation == "payload":
                row = connection.execute(
                    "SELECT payload FROM artifacts WHERE id = ?",
                    (reference.artifact_id,),
                ).fetchone()
                payload = json.loads(row[0])
                payload["content"] = '{"value":"tampered"}'
                connection.execute(
                    "UPDATE artifacts SET payload = ? WHERE id = ?",
                    (json.dumps(payload), reference.artifact_id),
                )
            else:
                replacement = {
                    "content_hash": "f" * 64,
                    "size_bytes": 999,
                    "plan_version_id": "plan_other",
                }[mutation]
                connection.execute(
                    f"UPDATE artifacts SET {mutation} = ? WHERE id = ?",
                    (replacement, reference.artifact_id),
                )

        _assert_error(
            "artifact_integrity_failed",
            lambda context=context, reference=reference: context.artifacts.read_verified(
                reference,
                scope=context.lineage,
            ),
        )
        _assert_error(
            "artifact_invalid",
            lambda context=context, reference=reference: context.artifacts.read_verified(
                reference,
                scope=context.lineage,
            ),
        )
        with sqlite3.connect(context.repository.db_path) as connection:
            state = connection.execute(
                "SELECT verification_state FROM artifacts WHERE id = ?",
                (reference.artifact_id,),
            ).fetchone()[0]
        assert state == ArtifactVerificationState.FAILED.value
        events = context.repository.list_agent_run_events(context.lineage.run_id)
        assert sum(event.event_type == "artifact_invalidated" for event in events) == 1


def test_projection_corruption_is_quarantined_even_when_failed_payload_cannot_use_the_projection(tmp_path) -> None:
    context = _execution_context(tmp_path / "projection-null.sqlite3", suffix="projection_null")
    reference = context.artifacts.seal(
        context.lineage,
        ArtifactDraft(
            artifact_id="artifact_projection_null",
            kind="tool_result",
            schema_version="result-v1",
            content={"value": "private research"},
        ),
        lease=context.lease,
    )
    with sqlite3.connect(context.repository.db_path) as connection:
        connection.execute(
            "UPDATE artifacts SET schema_version = NULL WHERE id = ?",
            (reference.artifact_id,),
        )

    _assert_error(
        "artifact_integrity_failed",
        lambda: context.artifacts.read_verified(reference, scope=context.lineage),
    )

    with sqlite3.connect(context.repository.db_path) as connection:
        row = connection.execute(
            "SELECT verification_state, payload FROM artifacts WHERE id = ?",
            (reference.artifact_id,),
        ).fetchone()
    assert row[0] == ArtifactVerificationState.FAILED.value
    assert json.loads(row[1])["content"] == ""
    assert sum(
        event.event_type == "artifact_invalidated"
        for event in context.repository.list_agent_run_events(context.lineage.run_id)
    ) == 1


def test_payload_scope_corruption_is_quarantined_without_moving_the_artifact(tmp_path) -> None:
    context = _execution_context(tmp_path / "payload-scope.sqlite3", suffix="payload_scope")
    reference = context.artifacts.seal(
        context.lineage,
        ArtifactDraft(
            artifact_id="artifact_payload_scope",
            kind="tool_result",
            schema_version="result-v1",
            content={"value": "private research"},
        ),
        lease=context.lease,
    )
    other_run = AgentRun(
        id="run_payload_scope_other",
        thread_id="thread_payload_scope_other",
        user_id="user_other",
        workspace_id="workspace_other",
        project_id="project_other",
        input_text="other",
        status=AgentRunStatus.PLANNING,
        orchestration_version="research-v2",
        orchestration_mode="execute",
    )
    context.repository.save_agent_run(other_run)
    other_event_count = len(context.repository.list_agent_run_events(other_run.id))
    with sqlite3.connect(context.repository.db_path) as connection:
        row = connection.execute(
            "SELECT payload FROM artifacts WHERE id = ?",
            (reference.artifact_id,),
        ).fetchone()
        payload = json.loads(row[0])
        payload.update(
            {
                "run_id": other_run.id,
                "user_id": other_run.user_id,
                "workspace_id": other_run.workspace_id,
                "project_id": other_run.project_id,
            }
        )
        connection.execute(
            "UPDATE artifacts SET payload = ? WHERE id = ?",
            (json.dumps(payload), reference.artifact_id),
        )

    _assert_error(
        "artifact_integrity_failed",
        lambda: context.artifacts.read_verified(reference, scope=context.lineage),
    )

    with sqlite3.connect(context.repository.db_path) as connection:
        row = connection.execute(
            "SELECT run_id, workspace_id, project_id, user_id, verification_state FROM artifacts WHERE id = ?",
            (reference.artifact_id,),
        ).fetchone()
    assert tuple(row) == (
        context.lineage.run_id,
        context.lineage.workspace_id,
        context.lineage.project_id,
        context.lineage.user_id,
        ArtifactVerificationState.FAILED.value,
    )
    assert len(context.repository.list_agent_run_events(other_run.id)) == other_event_count
    assert sum(
        event.event_type == "artifact_invalidated"
        for event in context.repository.list_agent_run_events(context.lineage.run_id)
    ) == 1


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("verification_state", None),
        ("content_type", "text/html"),
        ("workspace_id", "workspace_other"),
        ("truncated", True),
    ],
)
def test_envelope_downgrade_and_metadata_tampering_fail_closed(tmp_path, field: str, replacement) -> None:
    context = _execution_context(tmp_path / field / "envelope.sqlite3", suffix=field)
    reference = context.artifacts.seal(
        context.lineage,
        ArtifactDraft(
            artifact_id=f"artifact_envelope_{field}",
            kind="tool_result",
            schema_version="result-v1",
            content={"value": "safe"},
        ),
        lease=context.lease,
    )
    with sqlite3.connect(context.repository.db_path) as connection:
        row = connection.execute(
            "SELECT payload FROM artifacts WHERE id = ?",
            (reference.artifact_id,),
        ).fetchone()
        payload = json.loads(row[0])
        payload[field] = replacement
        connection.execute(
            "UPDATE artifacts SET payload = ? WHERE id = ?",
            (json.dumps(payload), reference.artifact_id),
        )

    _assert_error(
        "artifact_integrity_failed",
        lambda: context.artifacts.read_verified(reference, scope=context.lineage),
    )
    _assert_error(
        "artifact_invalid",
        lambda: context.artifacts.read_verified(reference, scope=context.lineage),
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("run_id", "run_projection_other"),
        ("workspace_id", None),
        ("project_id", None),
        ("user_id", None),
        ("artifact_type", None),
        ("content_type", None),
        ("truncated", None),
        ("verification_state", None),
        ("schema_version", None),
        ("content_hash", None),
        ("size_bytes", None),
        ("requirement_version_id", None),
        ("plan_version_id", None),
        ("attempt_id", None),
        ("step_number", None),
        ("created_at", "not-a-timestamp"),
        ("updated_at", "not-a-timestamp"),
    ],
)
def test_corrupt_required_projection_is_rewritten_as_failed_once(tmp_path, field: str, replacement) -> None:
    context = _execution_context(tmp_path / field / "projection.sqlite3", suffix=f"projection_{field}")
    reference = context.artifacts.seal(
        context.lineage,
        ArtifactDraft(
            artifact_id=f"artifact_projection_{field}",
            kind="tool_result",
            schema_version="result-v1",
            content={"value": "safe"},
        ),
        lease=context.lease,
    )
    with sqlite3.connect(context.repository.db_path) as connection:
        connection.execute(
            f"UPDATE artifacts SET {field} = ? WHERE id = ?",
            (replacement, reference.artifact_id),
        )

    _assert_error(
        "artifact_integrity_failed",
        lambda: context.artifacts.read_verified(reference, scope=context.lineage),
    )
    _assert_error(
        "artifact_invalid",
        lambda: context.artifacts.read_verified(reference, scope=context.lineage),
    )
    with sqlite3.connect(context.repository.db_path) as connection:
        state = connection.execute(
            "SELECT verification_state FROM artifacts WHERE id = ?",
            (reference.artifact_id,),
        ).fetchone()[0]
    assert state == ArtifactVerificationState.FAILED.value
    events = context.repository.list_agent_run_events(context.lineage.run_id)
    assert sum(event.event_type == "artifact_invalidated" for event in events) == 1


def test_index_state_tampering_is_not_treated_as_a_legitimate_terminal_state(tmp_path) -> None:
    context = _execution_context(tmp_path / "state-index.sqlite3", suffix="state_index")
    staged = context.artifacts.stage(
        context.lineage,
        artifact_id="artifact_state_index",
        kind="tool_result",
        schema_version="result-v1",
        lease=context.lease,
    )
    with sqlite3.connect(context.repository.db_path) as connection:
        connection.execute(
            "UPDATE artifacts SET verification_state = ? WHERE id = ?",
            (ArtifactVerificationState.PURGED.value, staged.id),
        )

    _assert_error(
        "artifact_integrity_failed",
        lambda: context.artifacts.read_verified(
            ArtifactRef(artifact_id=staged.id, content_hash="a" * 64),
            scope=context.lineage,
        ),
    )


def test_exact_seal_replay_survives_expired_lease_but_mixed_bundle_does_not(tmp_path) -> None:
    context = _execution_context(tmp_path / "expired-replay.sqlite3", suffix="expired_replay")
    draft = ArtifactDraft(
        artifact_id="artifact_replay_after_expiry",
        kind="tool_result",
        schema_version="result-v1",
        content={"value": "accepted"},
    )
    reference = context.artifacts.seal(context.lineage, draft, lease=context.lease)
    expired_at = datetime.now(UTC) - timedelta(seconds=1)
    with sqlite3.connect(context.repository.db_path) as connection:
        row = connection.execute(
            "SELECT payload FROM research_attempts WHERE id = ?",
            (context.lineage.attempt_id,),
        ).fetchone()
        payload = json.loads(row[0])
        payload["lease_expires_at"] = expired_at.isoformat()
        connection.execute(
            "UPDATE research_attempts SET payload = ?, lease_expires_at = ? WHERE id = ?",
            (json.dumps(payload), expired_at.isoformat(), context.lineage.attempt_id),
        )

    assert context.artifacts.seal(context.lineage, draft, lease=context.lease) == reference
    _assert_error(
        "artifact_lease_lost",
        lambda: context.artifacts.seal_bundle(
            context.lineage,
            [
                draft,
                ArtifactDraft(
                    artifact_id="artifact_new_after_expiry",
                    kind="tool_result",
                    schema_version="result-v1",
                    content={"value": "must not be written"},
                ),
            ],
            lease=context.lease,
        ),
    )
    assert context.repository.get_artifact("artifact_new_after_expiry") is None


def test_off_allows_only_atomic_settlement_of_an_already_sent_invocation(tmp_path) -> None:
    context = _execution_context(tmp_path / "off-settlement.sqlite3", suffix="off_settlement")
    request_ref = context.artifacts.seal(
        context.lineage,
        ArtifactDraft(
            artifact_id="artifact_off_request",
            kind="tool_request",
            schema_version="tool-request-v1",
            content={"query": "compare"},
        ),
        lease=context.lease,
    )
    sent_at = datetime.now(UTC)
    invocation = ToolInvocation(
        id="invocation_off_settlement",
        run_id=context.lineage.run_id,
        plan_version_id=context.lineage.plan_version_id or "",
        step_number=context.lineage.step_number or 1,
        operation_key=canonical_sha256({"run": context.lineage.run_id, "query": "compare"}),
        resolved_input_hash=request_ref.content_hash,
        request_artifact_id=request_ref.artifact_id,
        active_attempt_id=context.lineage.attempt_id or "",
        state=InvocationState.SENT,
        send_count=1,
        active_send_sequence=1,
        sent_fencing_epoch=1,
        last_sent_at=sent_at,
    )
    context.repository.add_research_tool_invocation(invocation)
    run = context.repository.get_agent_run(context.lineage.run_id)
    assert run is not None
    run.orchestration_mode = "off"
    context.repository.save_agent_run(run)
    receipt = ToolReceipt(
        provider="tavily",
        implementation_id="agentmesh.tool_runtime.gateway.ToolGateway.web_research",
        mode="real",
        send_sequence=1,
        status_code=200,
        latency_ms=12,
        result_count=2,
    )
    result_draft = ArtifactDraft(
        artifact_id="artifact_off_result",
        kind="tool_result",
        schema_version="web-research-output-v1",
        content={"content": "settled", "sources": []},
    )

    reference, acknowledged = context.artifacts.settle_sent_tool_invocation(
        context.lineage,
        result_draft,
        lease=context.lease,
        invocation_id=invocation.id,
        receipt=receipt,
    )

    assert acknowledged.state == InvocationState.ACKNOWLEDGED
    assert acknowledged.artifact_id == reference.artifact_id
    assert context.artifacts.read_verified(reference, scope=context.lineage).content
    _assert_error(
        "artifact_write_blocked",
        lambda: context.artifacts.seal(
            context.lineage,
            ArtifactDraft(
                artifact_id="artifact_off_new_work",
                kind="tool_result",
                schema_version="result-v1",
                content={"value": "must not start"},
            ),
            lease=context.lease,
        ),
    )
    assert context.repository.finish_research_workflow(
        context.lineage.run_id,
        expected_state_version=1,
        terminal_status=AgentRunStatus.COMPLETED,
    ) is not None
    assert context.artifacts.settle_sent_tool_invocation(
        context.lineage,
        result_draft,
        lease=context.lease,
        invocation_id=invocation.id,
        receipt=receipt,
    ) == (reference, acknowledged)


def test_off_settlement_rolls_back_artifact_when_invocation_ack_fails(tmp_path) -> None:
    context = _execution_context(tmp_path / "off-settlement-rollback.sqlite3", suffix="off_rollback")
    request_ref = context.artifacts.seal(
        context.lineage,
        ArtifactDraft(
            artifact_id="artifact_off_rollback_request",
            kind="tool_request",
            schema_version="tool-request-v1",
            content={"query": "compare"},
        ),
        lease=context.lease,
    )
    invocation = ToolInvocation(
        id="invocation_off_rollback",
        run_id=context.lineage.run_id,
        plan_version_id=context.lineage.plan_version_id or "",
        step_number=context.lineage.step_number or 1,
        operation_key=canonical_sha256({"run": context.lineage.run_id, "query": "compare"}),
        resolved_input_hash=request_ref.content_hash,
        request_artifact_id=request_ref.artifact_id,
        active_attempt_id=context.lineage.attempt_id or "",
        state=InvocationState.SENT,
        send_count=1,
        active_send_sequence=1,
        sent_fencing_epoch=1,
        last_sent_at=datetime.now(UTC),
    )
    context.repository.add_research_tool_invocation(invocation)
    run = context.repository.get_agent_run(context.lineage.run_id)
    assert run is not None
    run.orchestration_mode = "off"
    context.repository.save_agent_run(run)
    with sqlite3.connect(context.repository.db_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_off_invocation_ack
            BEFORE UPDATE OF state ON research_tool_invocations
            WHEN NEW.state = 'acknowledged'
            BEGIN
                SELECT RAISE(ABORT, 'forced invocation ACK failure');
            END
            """
        )
    result_draft = ArtifactDraft(
        artifact_id="artifact_off_rollback_result",
        kind="tool_result",
        schema_version="web-research-output-v1",
        content={"content": "must roll back", "sources": []},
    )
    receipt = ToolReceipt(
        provider="tavily",
        implementation_id="agentmesh.tool_runtime.gateway.ToolGateway.web_research",
        mode="real",
        send_sequence=1,
        status_code=200,
        latency_ms=12,
        result_count=0,
    )
    event_count = len(context.repository.list_agent_run_events(context.lineage.run_id))

    with pytest.raises(sqlite3.IntegrityError, match="forced invocation ACK failure"):
        context.artifacts.settle_sent_tool_invocation(
            context.lineage,
            result_draft,
            lease=context.lease,
            invocation_id=invocation.id,
            receipt=receipt,
        )

    assert context.repository.get_artifact("artifact_off_rollback_result") is None
    persisted = context.repository.get_research_tool_invocation(invocation.id)
    assert persisted is not None and persisted.state == InvocationState.SENT
    with sqlite3.connect(context.repository.db_path) as connection:
        projection = connection.execute(
            """
            SELECT state, receipt_payload, artifact_id, provider_operation_id, acknowledged_at
            FROM research_tool_invocations WHERE id = ?
            """,
            (invocation.id,),
        ).fetchone()
        connection.execute("DROP TRIGGER fail_off_invocation_ack")
    assert tuple(projection) == (InvocationState.SENT.value, None, None, None, None)
    assert len(context.repository.list_agent_run_events(context.lineage.run_id)) == event_count

    reference, acknowledged = context.artifacts.settle_sent_tool_invocation(
        context.lineage,
        result_draft,
        lease=context.lease,
        invocation_id=invocation.id,
        receipt=receipt,
    )
    assert reference.artifact_id == result_draft.artifact_id
    assert acknowledged.state == InvocationState.ACKNOWLEDGED
    assert acknowledged.artifact_id == reference.artifact_id
    context.artifacts.read_verified(reference, scope=context.lineage)


def test_sensitive_scanner_rejects_values_without_blocking_security_descriptions(tmp_path) -> None:
    context = _execution_context(tmp_path / "sensitive.sqlite3", suffix="sensitive")
    safe = context.artifacts.seal(
        context.lineage,
        ArtifactDraft(
            artifact_id="artifact_security_description",
            kind="tool_result",
            schema_version="result-v1",
            content={"content": "API key authentication is supported; password is hashed with Argon2."},
        ),
        lease=context.lease,
    )
    assert context.artifacts.read_verified(safe, scope=context.lineage).id == safe.artifact_id

    for index, content in enumerate(
        (
            {"api_key": "secret-value"},
            {"content": "Set-Cookie: sid=abc"},
            {"content": "Authorization: Bearer secret-token"},
        )
    ):
        _assert_error(
            "artifact_sensitive_content",
            lambda index=index, content=content: context.artifacts.seal(
                context.lineage,
                ArtifactDraft(
                    artifact_id=f"artifact_secret_{index}",
                    kind="tool_result",
                    schema_version="result-v1",
                    content=content,
                ),
                lease=context.lease,
            ),
        )

    _assert_error(
        "artifact_content_invalid",
        lambda: context.artifacts.seal(
            context.lineage,
            ArtifactDraft(
                artifact_id="artifact_active_html",
                kind="tool_result",
                schema_version="result-v1",
                content_type="text/html",
                content="<script>alert(1)</script>",
            ),
            lease=context.lease,
        ),
    )


def test_transient_cleanup_fails_staging_before_terminal_purge(tmp_path) -> None:
    effective_now = datetime.now(UTC)
    old_at = effective_now - timedelta(hours=25)
    active = _execution_context(tmp_path / "active-cleanup.sqlite3", suffix="active_cleanup")
    terminal = _execution_context(tmp_path / "terminal-cleanup.sqlite3", suffix="terminal_cleanup")
    for context, artifact_id in (
        (active, "artifact_active_staging"),
        (terminal, "artifact_terminal_staging"),
    ):
        context.artifacts.stage(
            context.lineage,
            artifact_id=artifact_id,
            kind="tool_result",
            schema_version="result-v1",
            lease=context.lease,
        )
        with sqlite3.connect(context.repository.db_path) as connection:
            row = connection.execute(
                "SELECT payload FROM artifacts WHERE id = ?",
                (artifact_id,),
            ).fetchone()
            payload = json.loads(row[0])
            payload["created_at"] = old_at.isoformat()
            payload["updated_at"] = old_at.isoformat()
            connection.execute(
                "UPDATE artifacts SET payload = ?, created_at = ?, updated_at = ? WHERE id = ?",
                (json.dumps(payload), old_at.isoformat(), old_at.isoformat(), artifact_id),
            )
    assert terminal.repository.finish_research_workflow(
        terminal.lineage.run_id,
        expected_state_version=1,
        terminal_status=AgentRunStatus.COMPLETED,
    ) is not None

    assert active.artifacts.cleanup_expired_transients(now=effective_now) == 1
    assert terminal.artifacts.cleanup_expired_transients(now=effective_now) == 1
    assert active.repository.get_artifact("artifact_active_staging").verification_state == ArtifactVerificationState.FAILED
    failed = terminal.repository.get_artifact("artifact_terminal_staging")
    assert failed.verification_state == ArtifactVerificationState.FAILED
    assert failed.content == ""

    purge_at = effective_now + timedelta(hours=25)
    assert active.artifacts.cleanup_expired_transients(now=purge_at) == 0
    assert terminal.artifacts.cleanup_expired_transients(now=purge_at) == 1
    tombstone = terminal.repository.get_artifact("artifact_terminal_staging")
    assert tombstone.verification_state == ArtifactVerificationState.PURGED
    assert tombstone.content == ""
    assert tombstone.purged_by == "system_cleanup"
    assert any(
        event.action == "cleanup_research_artifact" and event.target_id == tombstone.id
        for event in terminal.repository.audit_events
    )


def test_transient_cleanup_preserves_the_original_hash_after_invalidation(tmp_path) -> None:
    context = _execution_context(tmp_path / "failed-hash.sqlite3", suffix="failed_hash")
    reference = context.artifacts.seal(
        context.lineage,
        ArtifactDraft(
            artifact_id="artifact_failed_hash",
            kind="tool_result",
            schema_version="result-v1",
            content={"value": "private research"},
        ),
        lease=context.lease,
    )
    with sqlite3.connect(context.repository.db_path) as connection:
        row = connection.execute(
            "SELECT payload FROM artifacts WHERE id = ?",
            (reference.artifact_id,),
        ).fetchone()
        payload = json.loads(row[0])
        payload["content"] = '{"value":"tampered"}'
        connection.execute(
            "UPDATE artifacts SET payload = ? WHERE id = ?",
            (json.dumps(payload), reference.artifact_id),
        )
    _assert_error(
        "artifact_integrity_failed",
        lambda: context.artifacts.read_verified(reference, scope=context.lineage),
    )
    failed = context.repository.get_artifact(reference.artifact_id)
    assert failed is not None
    assert failed.verification_state == ArtifactVerificationState.FAILED
    assert failed.content_hash == reference.content_hash
    assert context.repository.finish_research_workflow(
        context.lineage.run_id,
        expected_state_version=1,
        terminal_status=AgentRunStatus.COMPLETED,
    ) is not None

    assert context.artifacts.cleanup_expired_transients(now=failed.updated_at + timedelta(hours=24, seconds=1)) == 1

    tombstone = context.repository.get_artifact(reference.artifact_id)
    assert tombstone is not None
    assert tombstone.verification_state == ArtifactVerificationState.PURGED
    assert tombstone.content_hash == reference.content_hash


def test_transient_cleanup_purges_a_corrupt_failed_payload_in_a_terminal_run(tmp_path) -> None:
    secret = "private corrupt failed payload"
    context = _execution_context(tmp_path / "failed-corrupt.sqlite3", suffix="failed_corrupt")
    reference = context.artifacts.seal(
        context.lineage,
        ArtifactDraft(
            artifact_id="artifact_failed_corrupt",
            kind="tool_result",
            schema_version="result-v1",
            content={"value": secret},
        ),
        lease=context.lease,
    )
    with sqlite3.connect(context.repository.db_path) as connection:
        row = connection.execute(
            "SELECT payload FROM artifacts WHERE id = ?",
            (reference.artifact_id,),
        ).fetchone()
        payload = json.loads(row[0])
        payload["content"] = "tampered"
        connection.execute(
            "UPDATE artifacts SET payload = ? WHERE id = ?",
            (json.dumps(payload), reference.artifact_id),
        )
    _assert_error(
        "artifact_integrity_failed",
        lambda: context.artifacts.read_verified(reference, scope=context.lineage),
    )
    failed = context.repository.get_artifact(reference.artifact_id)
    assert failed is not None and failed.verification_state == ArtifactVerificationState.FAILED
    with sqlite3.connect(context.repository.db_path) as connection:
        connection.execute(
            "UPDATE artifacts SET payload = ? WHERE id = ?",
            (secret, reference.artifact_id),
        )
    assert context.repository.finish_research_workflow(
        context.lineage.run_id,
        expected_state_version=1,
        terminal_status=AgentRunStatus.COMPLETED,
    ) is not None

    assert context.artifacts.cleanup_expired_transients(now=failed.updated_at + timedelta(hours=24, seconds=1)) == 1

    with sqlite3.connect(context.repository.db_path) as connection:
        raw_payload = connection.execute(
            "SELECT payload FROM artifacts WHERE id = ?",
            (reference.artifact_id,),
        ).fetchone()[0]
    tombstone = Artifact.model_validate_json(raw_payload)
    assert secret not in raw_payload
    assert tombstone.verification_state == ArtifactVerificationState.PURGED
    assert tombstone.content == ""


def test_owner_can_purge_terminal_research_data_without_deleting_thread_input(tmp_path) -> None:
    context = _execution_context(tmp_path / "owner-purge.sqlite3", suffix="owner_purge")
    reference = context.artifacts.seal(
        context.lineage,
        ArtifactDraft(
            artifact_id="artifact_owner_purge",
            kind="tool_result",
            schema_version="result-v1",
            content={"value": "private research"},
        ),
        lease=context.lease,
    )
    _assert_error(
        "research_data_not_purgeable",
        lambda: context.artifacts.purge_research_data(
            context.lineage.run_id,
            actor_user_id=context.lineage.user_id,
            workspace_id=context.lineage.workspace_id,
        ),
    )
    assert context.repository.finish_research_workflow(
        context.lineage.run_id,
        expected_state_version=1,
        terminal_status=AgentRunStatus.COMPLETED,
        output_text="private research",
    ) is not None
    _assert_error(
        "artifact_not_found",
        lambda: context.artifacts.purge_research_data(
            context.lineage.run_id,
            actor_user_id="user_other",
            workspace_id=context.lineage.workspace_id,
        ),
    )

    assert context.artifacts.purge_research_data(
        context.lineage.run_id,
        actor_user_id=context.lineage.user_id,
        workspace_id=context.lineage.workspace_id,
    ) == 1
    tombstone = context.repository.get_artifact(reference.artifact_id)
    assert tombstone.verification_state == ArtifactVerificationState.PURGED
    assert tombstone.content == ""
    assert tombstone.content_hash == reference.content_hash
    assert tombstone.purged_by == context.lineage.user_id
    assert context.repository.get_research_workflow(context.lineage.run_id) is None
    assert context.repository.get_research_plan_version(context.lineage.plan_version_id or "") is None
    run = context.repository.get_agent_run(context.lineage.run_id)
    assert run is not None and run.input_text == "compare" and run.output_text is None
    assert any(
        event.action == "purge_research_data" and event.target_id == context.lineage.run_id
        for event in context.repository.audit_events
    )


def test_owner_purge_does_not_move_a_payload_with_forged_scope(tmp_path) -> None:
    context = _execution_context(tmp_path / "owner-purge-scope.sqlite3", suffix="owner_purge_scope")
    reference = context.artifacts.seal(
        context.lineage,
        ArtifactDraft(
            artifact_id="artifact_owner_purge_scope",
            kind="tool_result",
            schema_version="result-v1",
            content={"value": "private research"},
        ),
        lease=context.lease,
    )
    other_run = AgentRun(
        id="run_owner_purge_scope_other",
        thread_id="thread_owner_purge_scope_other",
        user_id="user_other",
        workspace_id="workspace_other",
        project_id="project_other",
        input_text="other",
        status=AgentRunStatus.PLANNING,
        orchestration_version="research-v2",
        orchestration_mode="execute",
    )
    context.repository.save_agent_run(other_run)
    other_event_count = len(context.repository.list_agent_run_events(other_run.id))
    with sqlite3.connect(context.repository.db_path) as connection:
        row = connection.execute(
            "SELECT payload FROM artifacts WHERE id = ?",
            (reference.artifact_id,),
        ).fetchone()
        payload = json.loads(row[0])
        payload.update(
            {
                "run_id": other_run.id,
                "user_id": other_run.user_id,
                "workspace_id": other_run.workspace_id,
                "project_id": other_run.project_id,
            }
        )
        connection.execute(
            "UPDATE artifacts SET payload = ? WHERE id = ?",
            (json.dumps(payload), reference.artifact_id),
        )
    assert context.repository.finish_research_workflow(
        context.lineage.run_id,
        expected_state_version=1,
        terminal_status=AgentRunStatus.COMPLETED,
    ) is not None

    assert context.artifacts.purge_research_data(
        context.lineage.run_id,
        actor_user_id=context.lineage.user_id,
        workspace_id=context.lineage.workspace_id,
    ) == 1

    tombstone = context.repository.get_artifact(reference.artifact_id)
    assert tombstone is not None
    assert (
        tombstone.run_id,
        tombstone.workspace_id,
        tombstone.project_id,
        tombstone.user_id,
    ) == (
        context.lineage.run_id,
        context.lineage.workspace_id,
        context.lineage.project_id,
        context.lineage.user_id,
    )
    assert len(context.repository.list_agent_run_events(other_run.id)) == other_event_count


def test_owner_purge_recovers_an_artifact_with_a_corrupt_run_projection(tmp_path) -> None:
    context = _execution_context(tmp_path / "owner-purge-projection.sqlite3", suffix="owner_purge_projection")
    reference = context.artifacts.seal(
        context.lineage,
        ArtifactDraft(
            artifact_id="artifact_owner_purge_projection",
            kind="tool_result",
            schema_version="result-v1",
            content={"value": "private research"},
        ),
        lease=context.lease,
    )
    with sqlite3.connect(context.repository.db_path) as connection:
        connection.execute(
            "UPDATE artifacts SET run_id = ? WHERE id = ?",
            ("run_corrupt_projection", reference.artifact_id),
        )
    assert context.repository.finish_research_workflow(
        context.lineage.run_id,
        expected_state_version=1,
        terminal_status=AgentRunStatus.COMPLETED,
    ) is not None

    assert context.artifacts.purge_research_data(
        context.lineage.run_id,
        actor_user_id=context.lineage.user_id,
        workspace_id=context.lineage.workspace_id,
    ) == 1

    tombstone = context.repository.get_artifact(reference.artifact_id)
    assert tombstone is not None
    assert tombstone.run_id == context.lineage.run_id
    assert tombstone.verification_state == ArtifactVerificationState.PURGED
    assert tombstone.content == ""


def test_owner_purge_rolls_back_when_artifact_ownership_is_ambiguous(tmp_path) -> None:
    database = tmp_path / "owner-purge-ambiguous.sqlite3"
    target = _execution_context(database, suffix="owner_purge_target")
    other = _execution_context(database, suffix="owner_purge_other")
    target_ref = target.artifacts.seal(
        target.lineage,
        ArtifactDraft(
            artifact_id="artifact_owner_purge_target",
            kind="tool_result",
            schema_version="result-v1",
            content={"value": "target private research"},
        ),
        lease=target.lease,
    )
    other_ref = other.artifacts.seal(
        other.lineage,
        ArtifactDraft(
            artifact_id="artifact_owner_purge_other",
            kind="tool_result",
            schema_version="result-v1",
            content={"value": "other private research"},
        ),
        lease=other.lease,
    )
    with sqlite3.connect(target.repository.db_path) as connection:
        row = connection.execute(
            "SELECT payload FROM artifacts WHERE id = ?",
            (other_ref.artifact_id,),
        ).fetchone()
        payload = json.loads(row[0])
        payload.update(
            {
                "run_id": target.lineage.run_id,
                "requirement_version_id": target.lineage.requirement_version_id,
                "plan_version_id": target.lineage.plan_version_id,
                "attempt_id": target.lineage.attempt_id,
                "step_number": target.lineage.step_number,
            }
        )
        connection.execute(
            "UPDATE artifacts SET payload = ? WHERE id = ?",
            (json.dumps(payload), other_ref.artifact_id),
        )
    assert target.repository.finish_research_workflow(
        target.lineage.run_id,
        expected_state_version=1,
        terminal_status=AgentRunStatus.COMPLETED,
        output_text="target private output",
    ) is not None
    event_count = len(target.repository.list_agent_run_events(target.lineage.run_id))
    audit_count = len(target.repository.audit_events)

    _assert_error(
        "artifact_purge_scope_ambiguous",
        lambda: target.artifacts.purge_research_data(
            target.lineage.run_id,
            actor_user_id=target.lineage.user_id,
            workspace_id=target.lineage.workspace_id,
        ),
    )

    target_artifact = target.repository.get_artifact(target_ref.artifact_id)
    other_artifact = target.repository.get_artifact(other_ref.artifact_id)
    assert target_artifact is not None and target_artifact.verification_state == ArtifactVerificationState.SEALED
    assert target_artifact.content
    assert other_artifact is not None and other_artifact.verification_state == ArtifactVerificationState.SEALED
    assert other_artifact.content
    assert target.repository.get_research_workflow(target.lineage.run_id) is not None
    run = target.repository.get_agent_run(target.lineage.run_id)
    assert run is not None and run.output_text == "target private output"
    assert len(target.repository.list_agent_run_events(target.lineage.run_id)) == event_count
    assert len(target.repository.audit_events) == audit_count


@pytest.mark.parametrize("corruption", ["nonempty_content", "extra_field", "duplicate_content_key"])
def test_owner_purge_rewrites_noncanonical_purged_payloads(tmp_path, corruption: str) -> None:
    secret = f"private-body-{corruption}"
    context = _execution_context(
        tmp_path / corruption / "owner-purge-fake-tombstone.sqlite3",
        suffix=f"owner_purge_{corruption}",
    )
    reference = context.artifacts.seal(
        context.lineage,
        ArtifactDraft(
            artifact_id=f"artifact_owner_purge_{corruption}",
            kind="tool_result",
            schema_version="result-v1",
            content={"value": secret},
        ),
        lease=context.lease,
    )
    original = context.repository.get_artifact(reference.artifact_id)
    assert original is not None
    purged_at = datetime.now(UTC)
    forged = original.model_copy(
        update={
            "content": "",
            "verification_state": ArtifactVerificationState.PURGED,
            "purged_at": purged_at,
            "purged_by": "forged_cleanup",
            "updated_at": purged_at,
        }
    )
    if corruption == "nonempty_content":
        raw_payload = json.dumps(
            {**forged.model_dump(mode="json"), "content": secret},
            separators=(",", ":"),
        )
    elif corruption == "extra_field":
        raw_payload = json.dumps(
            {**forged.model_dump(mode="json"), "private_body": secret},
            separators=(",", ":"),
        )
    else:
        raw_payload = forged.model_dump_json().replace(
            '"content":""',
            f'"content":{json.dumps(secret)},"content":""',
            1,
        )
    with sqlite3.connect(context.repository.db_path) as connection:
        connection.execute(
            """
            UPDATE artifacts SET payload = ?, verification_state = ?, purged_at = ?,
                purged_by = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                raw_payload,
                ArtifactVerificationState.PURGED.value,
                purged_at.isoformat(),
                "forged_cleanup",
                purged_at.isoformat(),
                reference.artifact_id,
            ),
        )
    assert context.repository.finish_research_workflow(
        context.lineage.run_id,
        expected_state_version=1,
        terminal_status=AgentRunStatus.COMPLETED,
    ) is not None

    assert context.artifacts.purge_research_data(
        context.lineage.run_id,
        actor_user_id=context.lineage.user_id,
        workspace_id=context.lineage.workspace_id,
    ) == 1

    with sqlite3.connect(context.repository.db_path) as connection:
        stored_payload = connection.execute(
            "SELECT payload FROM artifacts WHERE id = ?",
            (reference.artifact_id,),
        ).fetchone()[0]
    tombstone = Artifact.model_validate_json(stored_payload)
    assert secret not in stored_payload
    assert tombstone.verification_state == ArtifactVerificationState.PURGED
    assert tombstone.content == ""
    assert tombstone.content_hash == reference.content_hash


def test_owner_purge_clears_null_state_legacy_and_malformed_payload_rows(tmp_path) -> None:
    context = _execution_context(tmp_path / "owner-purge-legacy.sqlite3", suffix="owner_purge_legacy")
    created_at = datetime.now(UTC) - timedelta(days=1)
    legacy_content = "private legacy research"
    legacy = Artifact(
        id="artifact_owner_purge_legacy",
        run_id=context.lineage.run_id,
        workspace_id=context.lineage.workspace_id,
        project_id=context.lineage.project_id,
        user_id=context.lineage.user_id,
        artifact_type="legacy_result",
        content_type="text/plain",
        content=legacy_content,
        created_at=created_at,
    )
    legacy_unverified = Artifact.model_validate(
        {
            **legacy.model_dump(mode="python"),
            "id": "artifact_owner_purge_legacy_unverified",
            "content": "private migrated legacy research",
            "verification_state": ArtifactVerificationState.LEGACY_UNVERIFIED,
        }
    )
    malformed_payload = "private malformed payload"
    with sqlite3.connect(context.repository.db_path) as connection:
        connection.execute(
            """
            INSERT INTO artifacts(
                id, run_id, payload, created_at, workspace_id, project_id, user_id,
                artifact_type, content_type, truncated, verification_state
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                legacy.id,
                legacy.run_id,
                legacy.model_dump_json(),
                created_at.isoformat(),
                legacy.workspace_id,
                legacy.project_id,
                legacy.user_id,
                legacy.artifact_type,
                legacy.content_type,
                0,
            ),
        )
        context.artifacts._insert_artifact(connection, legacy_unverified)
        connection.execute(
            """
            INSERT INTO artifacts(
                id, run_id, payload, created_at, workspace_id, project_id, user_id,
                artifact_type, content_type, truncated, verification_state
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                "artifact_owner_purge_malformed",
                context.lineage.run_id,
                malformed_payload,
                created_at.isoformat(),
                context.lineage.workspace_id,
                context.lineage.project_id,
                context.lineage.user_id,
                "legacy_result",
                "text/plain",
                0,
            ),
        )
    assert context.repository.finish_research_workflow(
        context.lineage.run_id,
        expected_state_version=1,
        terminal_status=AgentRunStatus.COMPLETED,
    ) is not None

    assert context.artifacts.purge_research_data(
        context.lineage.run_id,
        actor_user_id=context.lineage.user_id,
        workspace_id=context.lineage.workspace_id,
    ) == 3

    legacy_tombstone = context.repository.get_artifact(legacy.id)
    legacy_unverified_tombstone = context.repository.get_artifact(legacy_unverified.id)
    malformed_tombstone = context.repository.get_artifact("artifact_owner_purge_malformed")
    assert legacy_tombstone is not None
    assert legacy_tombstone.verification_state == ArtifactVerificationState.PURGED
    assert legacy_tombstone.content == ""
    assert legacy_tombstone.content_hash == hashlib.sha256(legacy_content.encode()).hexdigest()
    assert legacy_tombstone.size_bytes == len(legacy_content.encode())
    assert legacy_unverified_tombstone is not None
    assert legacy_unverified_tombstone.verification_state == ArtifactVerificationState.PURGED
    assert legacy_unverified_tombstone.content == ""
    assert malformed_tombstone is not None
    assert malformed_tombstone.verification_state == ArtifactVerificationState.PURGED
    assert malformed_tombstone.content == ""
    assert malformed_tombstone.content_hash == hashlib.sha256(malformed_payload.encode()).hexdigest()
    assert malformed_tombstone.size_bytes == len(malformed_payload.encode())


def test_owner_purge_rolls_back_everything_when_one_tombstone_write_fails(tmp_path) -> None:
    context = _execution_context(tmp_path / "owner-purge-rollback.sqlite3", suffix="owner_purge_rollback")
    references = [
        context.artifacts.seal(
            context.lineage,
            ArtifactDraft(
                artifact_id=f"artifact_owner_purge_rollback_{index}",
                kind="tool_result",
                schema_version="result-v1",
                content={"value": f"private {index}"},
            ),
            lease=context.lease,
        )
        for index in range(2)
    ]
    assert context.repository.finish_research_workflow(
        context.lineage.run_id,
        expected_state_version=1,
        terminal_status=AgentRunStatus.COMPLETED,
    ) is not None
    with sqlite3.connect(context.repository.db_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_owner_purge_tombstone
            BEFORE UPDATE ON artifacts
            WHEN OLD.id = 'artifact_owner_purge_rollback_1'
                 AND NEW.verification_state = 'purged'
            BEGIN
                SELECT RAISE(ABORT, 'forced purge tombstone failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced purge tombstone failure"):
        context.artifacts.purge_research_data(
            context.lineage.run_id,
            actor_user_id=context.lineage.user_id,
            workspace_id=context.lineage.workspace_id,
        )

    assert context.repository.get_research_workflow(context.lineage.run_id) is not None
    for reference in references:
        artifact = context.repository.get_artifact(reference.artifact_id)
        assert artifact is not None and artifact.verification_state == ArtifactVerificationState.SEALED


def test_staging_failed_purged_and_legacy_artifacts_never_enter_downstream(tmp_path) -> None:
    context = _execution_context(tmp_path / "states.sqlite3")
    staged = context.artifacts.stage(
        context.lineage,
        artifact_id="artifact_staging",
        kind="tool_result",
        schema_version="result-v1",
        lease=context.lease,
    )
    _assert_error(
        "artifact_not_ready",
        lambda: context.artifacts.read_verified(
            ArtifactRef(artifact_id=staged.id, content_hash="a" * 64),
            scope=context.lineage,
        ),
    )

    for state, code in (
        (ArtifactVerificationState.FAILED, "artifact_invalid"),
        (ArtifactVerificationState.PURGED, "artifact_purged"),
    ):
        artifact_id = f"artifact_{state.value}"
        context.artifacts.stage(
            context.lineage,
            artifact_id=artifact_id,
            kind="tool_result",
            schema_version="result-v1",
            lease=context.lease,
        )
        with sqlite3.connect(context.repository.db_path) as connection:
            row = connection.execute(
                "SELECT payload FROM artifacts WHERE id = ?",
                (artifact_id,),
            ).fetchone()
            payload = json.loads(row[0])
            payload["verification_state"] = state.value
            if state == ArtifactVerificationState.PURGED:
                payload["content_hash"] = "a" * 64
                payload["size_bytes"] = 0
                payload["purged_at"] = datetime.now(UTC).isoformat()
                payload["purged_by"] = "test_cleanup"
            connection.execute(
                """
                UPDATE artifacts SET payload = ?, verification_state = ?, content_hash = ?,
                    size_bytes = ?, purged_at = ?, purged_by = ?
                WHERE id = ?
                """,
                (
                    json.dumps(payload),
                    state.value,
                    payload.get("content_hash"),
                    payload.get("size_bytes"),
                    payload.get("purged_at"),
                    payload.get("purged_by"),
                    artifact_id,
                ),
            )
        _assert_error(
            code,
            lambda artifact_id=artifact_id: context.artifacts.read_verified(
                ArtifactRef(artifact_id=artifact_id, content_hash="a" * 64),
                scope=context.lineage,
            ),
        )

    with pytest.raises(ResearchStoreConflict, match="research-v2 artifacts require ArtifactStore"):
        context.repository.save_artifact(
            Artifact(
                id="artifact_v2_downgrade",
                run_id=context.lineage.run_id,
                workspace_id=context.lineage.workspace_id,
                project_id=context.lineage.project_id,
                user_id=context.lineage.user_id,
                artifact_type="legacy",
                content_type="text/plain",
                content="legacy",
            )
        )

    legacy_repository = SQLiteStore(tmp_path / "legacy.sqlite3")
    legacy_run = legacy_repository.save_agent_run(
        AgentRun(
            id="run_legacy_artifact",
            thread_id="thread_legacy_artifact",
            user_id="user_1",
            workspace_id="workspace_1",
            project_id="project_1",
            input_text="legacy",
        )
    )
    legacy = legacy_repository.save_artifact(
        Artifact(
            id="artifact_legacy",
            run_id=legacy_run.id,
            workspace_id=legacy_run.workspace_id,
            project_id=legacy_run.project_id,
            user_id=legacy_run.user_id,
            artifact_type="legacy",
            content_type="text/plain",
            content="legacy",
        )
    )
    _assert_error(
        "artifact_unverified",
        lambda: ArtifactStore(legacy_repository).read_verified(
            ArtifactRef(artifact_id=legacy.id, content_hash=hashlib.sha256(b"legacy").hexdigest()),
            scope=context.lineage.model_copy(
                update={
                    "run_id": legacy_run.id,
                    "requirement_version_id": "legacy_requirement",
                    "plan_version_id": None,
                    "attempt_id": None,
                    "step_number": None,
                }
            ),
        ),
    )


def test_duplicate_json_keys_are_rejected_before_persistence(tmp_path) -> None:
    context = _execution_context(tmp_path / "json.sqlite3")
    _assert_error(
        "artifact_content_invalid",
        lambda: context.artifacts.seal(
            context.lineage,
            ArtifactDraft(
                artifact_id="artifact_duplicate_json",
                kind="tool_result",
                schema_version="result-v1",
                content='{"value":1,"value":2}',
            ),
            lease=context.lease,
        ),
    )
    assert context.repository.get_artifact("artifact_duplicate_json") is None


def test_deep_json_is_rejected_without_leaking_recursion_errors(tmp_path) -> None:
    context = _execution_context(tmp_path / "deep-json.sqlite3", suffix="deep_json")
    nested: object = "leaf"
    for _ in range(2_000):
        nested = [nested]

    _assert_error(
        "artifact_content_invalid",
        lambda: context.artifacts.seal(
            context.lineage,
            ArtifactDraft(
                artifact_id="artifact_deep_json",
                kind="tool_result",
                schema_version="result-v1",
                content=nested,
            ),
            lease=context.lease,
        ),
    )
    assert context.repository.get_artifact("artifact_deep_json") is None


def test_phone_scan_rejects_standalone_pii_without_flagging_hash_substrings(tmp_path) -> None:
    context = _execution_context(tmp_path / "phone-scan.sqlite3")
    reference = context.artifacts.seal(
        context.lineage,
        ArtifactDraft(
            artifact_id="artifact_hash_like_digits",
            kind="tool_result",
            schema_version="result-v1",
            content={"content_hash": "a19601575478b"},
        ),
        lease=context.lease,
    )
    assert context.artifacts.read_verified(reference, scope=context.lineage).id == reference.artifact_id

    _assert_error(
        "artifact_sensitive_content",
        lambda: context.artifacts.seal(
            context.lineage,
            ArtifactDraft(
                artifact_id="artifact_real_phone",
                kind="tool_result",
                schema_version="result-v1",
                content={"contact": "19601575478"},
            ),
            lease=context.lease,
        ),
    )
