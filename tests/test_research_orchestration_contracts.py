from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from agentmesh.models import AgentRun, AgentRunStatus, Artifact, ArtifactVerificationState
from agentmesh.research_orchestration.contracts import (
    ExecutionAttempt,
    InvocationState,
    ResearchGate,
    ResearchPhase,
    ResearchStep,
    ResearchWorkflow,
    StepStatus,
    ToolInvocation,
    ToolReceipt,
)

NOW = datetime(2026, 8, 19, tzinfo=UTC)
HASH = "a" * 64
EMPTY_OBJECT_HASH = hashlib.sha256(b"{}").hexdigest()


def test_legacy_agent_run_defaults_to_v1_and_status_enum_adds_clarification() -> None:
    run = AgentRun.model_validate(
        {
            "id": "run_legacy",
            "thread_id": "thread_1",
            "user_id": "user_1",
            "workspace_id": "workspace_1",
            "project_id": "project_1",
            "input_text": "legacy",
        }
    )

    assert run.orchestration_version == "v1"
    assert {status.value for status in AgentRunStatus} == {
        "created",
        "planning",
        "waiting_clarification",
        "running",
        "waiting_plan_approval",
        "waiting_approval",
        "completed",
        "partial",
        "failed",
        "rejected",
        "cancelled",
    }


def test_research_contracts_accept_valid_minimal_states() -> None:
    workflow = ResearchWorkflow(run_id="run_1", phase=ResearchPhase.PLANNING)
    attempt = ExecutionAttempt(
        id="attempt_1",
        run_id="run_1",
        plan_version_id="plan_1",
        attempt_number=1,
        status="running",
        deadline_at=NOW + timedelta(minutes=5),
        lease_owner="worker_1",
        lease_token="lease_1",
        fencing_epoch=1,
        lease_expires_at=NOW + timedelta(seconds=60),
        created_at=NOW,
    )
    step = ResearchStep(
        attempt_id=attempt.id,
        step_number=1,
        status=StepStatus.COMPLETED,
        result_artifact_id="artifact_1",
        started_at=NOW,
        completed_at=NOW,
    )
    invocation = ToolInvocation(
        id="invocation_1",
        run_id="run_1",
        plan_version_id="plan_1",
        step_number=1,
        operation_key=HASH,
        resolved_input_hash=HASH,
        request_artifact_id="artifact_request_1",
        active_attempt_id=attempt.id,
        state=InvocationState.ACKNOWLEDGED,
        send_count=1,
        active_send_sequence=1,
        sent_fencing_epoch=1,
        last_sent_at=NOW,
        acknowledged_at=NOW,
        receipt=ToolReceipt(
            provider="fake",
            implementation_id="fake:v1",
            mode="fake",
            send_sequence=1,
            latency_ms=1,
            result_count=1,
        ),
        artifact_id="artifact_1",
    )
    artifact = Artifact(
        run_id="run_1",
        workspace_id="workspace_1",
        project_id="project_1",
        user_id="user_1",
        artifact_type="tool_result",
        content_type="application/json",
        content="{}",
        verification_state=ArtifactVerificationState.SEALED,
        schema_version="tool-result-v1",
        content_hash=EMPTY_OBJECT_HASH,
        size_bytes=2,
        requirement_version_id="requirement_1",
        plan_version_id="plan_1",
        attempt_id="attempt_1",
        step_number=1,
    )

    assert ResearchWorkflow.model_validate_json(workflow.model_dump_json()) == workflow
    assert ExecutionAttempt.model_validate_json(attempt.model_dump_json()) == attempt
    assert ResearchStep.model_validate_json(step.model_dump_json()) == step
    assert ToolInvocation.model_validate_json(invocation.model_dump_json()) == invocation
    assert Artifact.model_validate_json(artifact.model_dump_json()) == artifact


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ResearchWorkflow(
            run_id="run_1",
            phase=ResearchPhase.TERMINAL,
            active_gate=ResearchGate.CLARIFICATION,
        ),
        lambda: ExecutionAttempt(
            id="attempt_1",
            run_id="run_1",
            plan_version_id="plan_1",
            attempt_number=1,
            deadline_at=NOW + timedelta(minutes=5),
            lease_owner="worker_1",
        ),
        lambda: ResearchStep(
            attempt_id="attempt_1",
            step_number=1,
            status=StepStatus.COMPLETED,
            started_at=NOW,
            completed_at=NOW,
        ),
        lambda: ToolInvocation(
            id="invocation_1",
            run_id="run_1",
            plan_version_id="plan_1",
            step_number=1,
            operation_key=HASH,
            resolved_input_hash=HASH,
            request_artifact_id="artifact_request_1",
            active_attempt_id="attempt_1",
            state=InvocationState.ACKNOWLEDGED,
            send_count=1,
        ),
        lambda: Artifact(
            run_id="run_1",
            workspace_id="workspace_1",
            project_id="project_1",
            user_id="user_1",
            artifact_type="tool_result",
            content_type="application/json",
            content="{}",
            verification_state=ArtifactVerificationState.SEALED,
            schema_version="tool-result-v1",
            content_hash=HASH,
            size_bytes=2,
        ),
    ],
)
def test_research_contracts_reject_impossible_state_combinations(factory) -> None:  # noqa: ANN001
    with pytest.raises(ValidationError):
        factory()
