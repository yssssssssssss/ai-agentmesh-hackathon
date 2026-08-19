from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from agentmesh.models import AgentRun, AgentRunStatus, Artifact, ArtifactVerificationState
from agentmesh.research_orchestration.artifacts import ArtifactDraft, ArtifactLease, ArtifactLineage, ArtifactStore
from agentmesh.research_orchestration.contracts import (
    AttemptStatus,
    ExecutionAttempt,
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
from agentmesh.store import ResearchStoreConflict, SQLiteStore

HASH_A = "a" * 64
HASH_B = "b" * 64


def _run(*, run_id: str = "run_research", version: str = "research-v2") -> AgentRun:
    return AgentRun(
        id=run_id,
        thread_id="thread_1",
        user_id="user_1",
        workspace_id="workspace_1",
        project_id="project_1",
        input_text="对比三个研究助手",
        status=AgentRunStatus.PLANNING,
        orchestration_version=version,
    )


def _add_versions(
    repository: SQLiteStore,
    *,
    run_id: str = "run_research",
    suffix: str = "1",
) -> tuple[RequirementVersion, ExecutionPlanVersion]:
    requirement = repository.add_research_requirement_version(
        RequirementVersion(
            id=f"requirement_{suffix}",
            run_id=run_id,
            version=1,
            schema_version="research-task-v2",
            task_type="competitive_research",
            payload={"goal": "compare"},
            content_hash=canonical_sha256({"goal": "compare"}),
        )
    )
    plan = repository.add_research_plan_version(
        ExecutionPlanVersion(
            id=f"plan_{suffix}",
            run_id=run_id,
            requirement_version_id=requirement.id,
            version=1,
            schema_version="execution-plan-v2",
            plan_hash=canonical_sha256({"steps": []}),
            payload={"steps": []},
        )
    )
    return requirement, plan


def test_old_database_is_upgraded_additively(tmp_path) -> None:
    database = tmp_path / "legacy.sqlite3"
    legacy_run = _run(run_id="run_legacy", version="v1").model_dump(mode="json")
    legacy_run.pop("orchestration_version")
    legacy_artifact = Artifact(
        id="artifact_legacy",
        run_id="run_legacy",
        workspace_id="workspace_1",
        project_id="project_1",
        user_id="user_1",
        artifact_type="legacy",
        content_type="text/plain",
        content="legacy body",
    )
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE agent_runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL)")
        connection.execute(
            "CREATE TABLE artifacts (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO agent_runs(id, payload, updated_at) VALUES (?, ?, ?)",
            ("run_legacy", json.dumps(legacy_run), legacy_run["updated_at"]),
        )
        connection.execute(
            "INSERT INTO artifacts(id, run_id, payload, created_at) VALUES (?, ?, ?, ?)",
            (
                legacy_artifact.id,
                legacy_artifact.run_id,
                legacy_artifact.model_dump_json(),
                legacy_artifact.created_at.isoformat(),
            ),
        )

    repository = SQLiteStore(database)

    with sqlite3.connect(database) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        artifact_columns = {row[1] for row in connection.execute("PRAGMA table_info(artifacts)")}
        artifact_indexes = {row[1] for row in connection.execute("PRAGMA index_list(artifacts)")}
    assert {
        "research_workflows",
        "research_requirement_versions",
        "research_plan_versions",
        "research_commands",
        "research_attempts",
        "research_steps",
        "research_tool_invocations",
        "research_model_call_receipts",
    }.issubset(tables)
    assert {
        "verification_state",
        "schema_version",
        "content_hash",
        "size_bytes",
        "requirement_version_id",
        "plan_version_id",
        "attempt_id",
        "step_number",
        "purged_at",
    }.issubset(artifact_columns)
    assert "idx_artifacts_run_provenance" in artifact_indexes
    assert repository.get_agent_run("run_legacy").orchestration_version == "v1"
    assert repository.get_artifact("artifact_legacy").content == "legacy body"


def test_workflow_compare_and_swap_rejects_stale_writer_and_updates_run(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "workflow.sqlite3")
    repository.save_agent_run(_run())
    repository.create_research_workflow(ResearchWorkflow(run_id="run_research", phase=ResearchPhase.PLANNING))
    requirement, plan = _add_versions(repository)

    winner = ResearchWorkflow(
        run_id="run_research",
        phase=ResearchPhase.PLANNING,
        active_gate=ResearchGate.PLAN_CONFIRMATION,
        active_requirement_version_id=requirement.id,
        active_plan_version_id=plan.id,
    )
    stale = ResearchWorkflow(
        run_id="run_research",
        phase=ResearchPhase.REQUIREMENT,
        active_gate=ResearchGate.CLARIFICATION,
    )

    assert repository.compare_and_swap_research_workflow(winner, expected_state_version=1)
    assert not repository.compare_and_swap_research_workflow(stale, expected_state_version=1)

    stored = repository.get_research_workflow("run_research")
    assert stored is not None
    assert stored.state_version == 2
    assert stored.active_gate == ResearchGate.PLAN_CONFIRMATION
    assert repository.get_agent_run("run_research").status == AgentRunStatus.WAITING_PLAN_APPROVAL
    assert [event.event_type for event in repository.list_agent_run_events("run_research")] == ["research_updated"]


def test_agent_run_orchestration_version_is_immutable(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "immutable-run-version.sqlite3")
    repository.save_agent_run(_run())

    with pytest.raises(ResearchStoreConflict):
        repository.save_agent_run(_run(version="v1"))

    assert repository.get_agent_run("run_research").orchestration_version == "research-v2"


def test_finish_research_workflow_atomically_terminates_run_and_blocks_late_cas(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "finish-workflow.sqlite3")
    repository.save_agent_run(_run())
    repository.create_research_workflow(ResearchWorkflow(run_id="run_research", phase=ResearchPhase.RESULT))

    finished = repository.finish_research_workflow(
        "run_research",
        expected_state_version=1,
        terminal_status=AgentRunStatus.COMPLETED,
        output_text="done",
    )

    assert finished is not None
    workflow, run = finished
    assert workflow.phase == ResearchPhase.TERMINAL
    assert workflow.state_version == 2
    assert run.status == AgentRunStatus.COMPLETED
    assert run.output_text == "done"
    assert not repository.compare_and_swap_research_workflow(
        ResearchWorkflow(run_id=run.id, phase=ResearchPhase.EXECUTION),
        expected_state_version=2,
    )


def test_cancel_atomically_terminates_workflow_and_blocks_late_writer(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "cancel-race.sqlite3")
    run = repository.save_agent_run(_run())
    repository.create_research_workflow(ResearchWorkflow(run_id=run.id, phase=ResearchPhase.EXECUTION))
    cancelled = repository.cancel_agent_run_tree(run.id, user_id=run.user_id)

    assert cancelled is not None and cancelled.status == AgentRunStatus.CANCELLED
    assert not repository.compare_and_swap_research_workflow(
        ResearchWorkflow(run_id=run.id, phase=ResearchPhase.RESULT),
        expected_state_version=2,
    )
    assert repository.get_agent_run(run.id).status == AgentRunStatus.CANCELLED
    workflow = repository.get_research_workflow(run.id)
    assert workflow is not None and workflow.phase == ResearchPhase.TERMINAL
    assert workflow.state_version == 2


def test_workflow_rejects_cross_run_active_requirement(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "cross-run-workflow.sqlite3")
    repository.save_agent_run(_run(run_id="run_a"))
    repository.save_agent_run(_run(run_id="run_b"))
    repository.create_research_workflow(ResearchWorkflow(run_id="run_a", phase=ResearchPhase.REQUIREMENT))
    other_requirement = repository.add_research_requirement_version(
        RequirementVersion(
            id="requirement_b",
            run_id="run_b",
            version=1,
            schema_version="research-task-v2",
            task_type="competitive_research",
            payload={"goal": "other"},
            content_hash=canonical_sha256({"goal": "other"}),
        )
    )

    with pytest.raises(ResearchStoreConflict):
        repository.compare_and_swap_research_workflow(
            ResearchWorkflow(
                run_id="run_a",
                phase=ResearchPhase.PLANNING,
                active_requirement_version_id=other_requirement.id,
            ),
            expected_state_version=1,
        )

    assert repository.get_research_workflow("run_a").state_version == 1
    assert repository.list_agent_run_events("run_a") == []


def test_requirement_and_plan_versions_are_insert_only(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "versions.sqlite3")
    repository.save_agent_run(_run())
    requirement = RequirementVersion(
        id="requirement_1",
        run_id="run_research",
        version=1,
        schema_version="research-task-v2",
        task_type="competitive_research",
        payload={"goal": "compare"},
        content_hash=canonical_sha256({"goal": "compare"}),
    )
    plan = ExecutionPlanVersion(
        id="plan_1",
        run_id="run_research",
        requirement_version_id=requirement.id,
        version=1,
        schema_version="execution-plan-v2",
        plan_hash=canonical_sha256({"steps": []}),
        payload={"steps": []},
    )

    repository.add_research_requirement_version(requirement)
    repository.add_research_plan_version(plan)

    with pytest.raises(ResearchStoreConflict):
        repository.add_research_requirement_version(requirement.model_copy(update={"id": "requirement_conflict"}))
    with pytest.raises(ResearchStoreConflict):
        repository.add_research_plan_version(plan.model_copy(update={"id": "plan_conflict", "version": 2}))

    assert repository.get_research_requirement_version(requirement.id) == requirement
    assert repository.get_research_plan_version(plan.id) == plan


def test_research_command_replays_same_hash_and_rejects_different_hash(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "commands.sqlite3")
    repository.save_agent_run(_run())
    repository.create_research_workflow(ResearchWorkflow(run_id="run_research", phase=ResearchPhase.PLANNING))
    requirement, plan = _add_versions(repository)
    first = ResearchCommandReceipt(
        run_id="run_research",
        idempotency_key="command_1",
        command_type="confirm_plan",
        request_hash=HASH_A,
        response_status=200,
        response_payload={"state_version": 2},
    )
    transition = ResearchWorkflow(
        run_id="run_research",
        phase=ResearchPhase.PLANNING,
        active_gate=ResearchGate.PLAN_CONFIRMATION,
        active_requirement_version_id=requirement.id,
        active_plan_version_id=plan.id,
    )

    stored, updated, created = repository.apply_research_workflow_command(
        first,
        transition,
        expected_state_version=1,
    )
    replayed, replay_workflow, replay_created = repository.apply_research_workflow_command(
        first.model_copy(update={"response_payload": {"state_version": 999}}),
        transition,
        expected_state_version=1,
    )

    assert created
    assert not replay_created
    assert replayed == stored == first
    assert updated.state_version == replay_workflow.state_version == 2
    with pytest.raises(ResearchStoreConflict):
        repository.apply_research_workflow_command(
            first.model_copy(update={"request_hash": HASH_B}),
            transition,
            expected_state_version=2,
        )


def test_research_command_rolls_back_workflow_when_receipt_insert_fails(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "command-rollback.sqlite3")
    repository.save_agent_run(_run())
    repository.create_research_workflow(ResearchWorkflow(run_id="run_research", phase=ResearchPhase.PLANNING))
    requirement, plan = _add_versions(repository)
    receipt = ResearchCommandReceipt(
        run_id="run_research",
        idempotency_key="command_rollback",
        command_type="confirm_plan",
        request_hash=HASH_A,
        response_status=200,
        response_payload={"state_version": 2},
    )
    transition = ResearchWorkflow(
        run_id="run_research",
        phase=ResearchPhase.PLANNING,
        active_gate=ResearchGate.PLAN_CONFIRMATION,
        active_requirement_version_id=requirement.id,
        active_plan_version_id=plan.id,
    )
    with repository._connect() as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_research_command_insert
            BEFORE INSERT ON research_commands
            BEGIN
                SELECT RAISE(ABORT, 'injected command receipt failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError):
        repository.apply_research_workflow_command(receipt, transition, expected_state_version=1)

    workflow = repository.get_research_workflow("run_research")
    assert workflow is not None and workflow.state_version == 1
    assert workflow.active_gate == ResearchGate.NONE
    assert repository.get_agent_run("run_research").status == AgentRunStatus.PLANNING
    assert repository.list_agent_run_events("run_research") == []


def test_attempt_step_and_operation_key_are_persisted_without_upsert(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "execution-records.sqlite3")
    repository.save_agent_run(_run().model_copy(update={"orchestration_mode": "execute"}))
    requirement = repository.add_research_requirement_version(
        RequirementVersion(
            id="requirement_1",
            run_id="run_research",
            version=1,
            schema_version="research-task-v2",
            task_type="competitive_research",
            payload={"goal": "compare"},
            content_hash=canonical_sha256({"goal": "compare"}),
        )
    )
    plan = repository.add_research_plan_version(
        ExecutionPlanVersion(
            id="plan_1",
            run_id="run_research",
            requirement_version_id=requirement.id,
            version=1,
            schema_version="execution-plan-v2",
            plan_hash=canonical_sha256(
                {
                    "steps": [
                        {"step_number": 1, "actor_type": "tool"},
                        {"step_number": 2, "actor_type": "skill"},
                    ]
                }
            ),
            payload={
                "steps": [
                    {"step_number": 1, "actor_type": "tool"},
                    {"step_number": 2, "actor_type": "skill"},
                ]
            },
        )
    )
    attempt = repository.add_research_attempt(
        ExecutionAttempt(
            id="attempt_1",
            run_id="run_research",
            plan_version_id=plan.id,
            attempt_number=1,
            status=AttemptStatus.RUNNING,
            lease_owner="worker_1",
            lease_token="lease_1",
            fencing_epoch=1,
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
            deadline_at=datetime.now(UTC) + timedelta(minutes=5),
        )
    )
    step = repository.add_research_step(
        ResearchStep(
            attempt_id=attempt.id,
            step_number=1,
            status=StepStatus.RUNNING,
            claim_epoch=1,
            started_at=datetime.now(UTC),
        )
    )
    with pytest.raises(ResearchStoreConflict, match="not part of the frozen plan"):
        repository.add_research_step(
            ResearchStep(
                attempt_id=attempt.id,
                step_number=999,
                status=StepStatus.RUNNING,
                claim_epoch=1,
                started_at=datetime.now(UTC),
            )
        )
    repository.add_research_step(
        ResearchStep(
            attempt_id=attempt.id,
            step_number=2,
            status=StepStatus.RUNNING,
            claim_epoch=1,
            started_at=datetime.now(UTC),
        )
    )
    repository.create_research_workflow(
        ResearchWorkflow(
            run_id="run_research",
            phase=ResearchPhase.EXECUTION,
            active_requirement_version_id=requirement.id,
            active_plan_version_id=plan.id,
            active_attempt_id=attempt.id,
        )
    )
    artifact_store = ArtifactStore(repository)
    lineage = ArtifactLineage(
        run_id="run_research",
        user_id="user_1",
        workspace_id="workspace_1",
        project_id="project_1",
        requirement_version_id=requirement.id,
        plan_version_id=plan.id,
        attempt_id=attempt.id,
        step_number=1,
    )
    lease = ArtifactLease(owner="worker_1", token="lease_1", fencing_epoch=1)
    request_ref = artifact_store.seal(
        lineage,
        ArtifactDraft(
            artifact_id="artifact_request_1",
            kind="tool_request",
            schema_version="tool-request-v1",
            content={"query": "compare"},
        ),
        lease=lease,
    )
    step_two_lineage = lineage.model_copy(update={"step_number": 2})
    step_two_request = artifact_store.seal(
        step_two_lineage,
        ArtifactDraft(
            artifact_id="artifact_request_step_2",
            kind="tool_request",
            schema_version="tool-request-v1",
            content={"query": "wrong step"},
        ),
        lease=lease,
    )
    invocation = ToolInvocation(
        id="invocation_1",
        run_id="run_research",
        plan_version_id=plan.id,
        step_number=1,
        operation_key=HASH_A,
        resolved_input_hash=request_ref.content_hash,
        request_artifact_id=request_ref.artifact_id,
        active_attempt_id=attempt.id,
        state=InvocationState.PREPARED,
    )

    stored, created = repository.add_research_tool_invocation(invocation)
    replayed, replay_created = repository.add_research_tool_invocation(
        invocation.model_copy(update={"id": "invocation_2"})
    )

    assert repository.get_research_attempt(attempt.id) == attempt
    assert repository.get_research_step(attempt.id, 1) == step
    assert created
    assert not replay_created
    assert replayed == stored == invocation
    with pytest.raises(ResearchStoreConflict, match="missing or not sealed"):
        repository.add_research_tool_invocation(
            invocation.model_copy(
                update={
                    "id": "invocation_missing_request",
                    "operation_key": HASH_B,
                    "request_artifact_id": "artifact_missing",
                    "resolved_input_hash": HASH_B,
                }
            )
        )
    with pytest.raises(ResearchStoreConflict, match="provenance"):
        repository.add_research_tool_invocation(
            invocation.model_copy(
                update={
                    "id": "invocation_cross_step",
                    "operation_key": HASH_B,
                    "request_artifact_id": step_two_request.artifact_id,
                    "resolved_input_hash": step_two_request.content_hash,
                }
            )
        )
    with pytest.raises(ResearchStoreConflict):
        repository.add_research_tool_invocation(invocation.model_copy(update={"resolved_input_hash": HASH_A}))
    with pytest.raises(ResearchStoreConflict):
        repository.add_research_tool_invocation(
            invocation.model_copy(update={"id": "invocation_3", "operation_key": HASH_B})
        )


def test_legacy_artifact_api_cannot_create_or_overwrite_verified_artifacts(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "artifact-boundary.sqlite3")
    content = "{}"
    sealed = Artifact(
        id="artifact_sealed",
        run_id="run_research",
        workspace_id="workspace_1",
        project_id="project_1",
        user_id="user_1",
        artifact_type="tool_result",
        content_type="application/json",
        content=content,
        verification_state=ArtifactVerificationState.SEALED,
        schema_version="tool-result-v1",
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        size_bytes=len(content.encode()),
        requirement_version_id="requirement_1",
    )

    with pytest.raises(ResearchStoreConflict):
        repository.save_artifact(sealed)

    repository.save_agent_run(_run(version="v1"))
    legacy = repository.save_artifact(
        Artifact(
            id="artifact_legacy",
            run_id="run_research",
            workspace_id="workspace_1",
            project_id="project_1",
            user_id="user_1",
            artifact_type="legacy",
            content_type="text/plain",
            content="legacy",
        )
    )
    with pytest.raises(ResearchStoreConflict):
        repository.save_artifact(legacy.model_copy(update={"user_id": "other_user"}))


def test_version_store_rejects_hash_mismatch_and_detects_database_tampering(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "version-integrity.sqlite3")
    repository.save_agent_run(_run())
    requirement, plan = _add_versions(repository)

    with pytest.raises(ResearchStoreConflict, match="requirement content hash mismatch"):
        repository.add_research_requirement_version(
            requirement.model_copy(update={"id": "requirement_tampered", "payload": {"goal": "tampered"}})
        )
    with pytest.raises(ResearchStoreConflict, match="plan content hash mismatch"):
        repository.add_research_plan_version(
            plan.model_copy(update={"id": "plan_tampered", "version": 2, "payload": {"steps": ["tampered"]}})
        )

    stored = json.loads(plan.model_dump_json())
    stored["payload"]["steps"] = ["database_tampered"]
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            "UPDATE research_plan_versions SET payload = ? WHERE id = ?",
            (json.dumps(stored), plan.id),
        )
    with pytest.raises(ResearchStoreConflict, match="failed integrity verification"):
        repository.get_research_plan_version(plan.id)
