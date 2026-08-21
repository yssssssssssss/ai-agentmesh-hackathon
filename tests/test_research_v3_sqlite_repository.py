from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.competitive_text_integration import (
    CompletedCompetitiveTextRun,
    CompetitiveTextIntegrationHarness,
    PreparedCompetitiveTextRun,
)
from agentmesh.research_orchestration.v3.repository_projector import ResearchV3RepositoryProjector
from agentmesh.research_orchestration.v3.sqlite_repository import (
    AttemptLeaseV3,
    ResearchV3ConflictError,
    ResearchV3IntegrityError,
    ResearchV3NotFoundError,
    SQLiteResearchV3Repository,
)

NOW = datetime(2026, 8, 21, 9, 30, tzinfo=UTC)
SCOPE = {
    "owner_id": "owner_alpha",
    "workspace_id": "workspace_alpha",
    "project_id": "project_alpha",
}


@dataclass(frozen=True)
class PersistedSuccess:
    completed: CompletedCompetitiveTextRun
    repository: SQLiteResearchV3Repository


def _repository(path: Path, **scope: str) -> SQLiteResearchV3Repository:
    return SQLiteResearchV3Repository(path, clock=lambda: NOW, **(scope or SCOPE))


def _append_planning(
    repository: SQLiteResearchV3Repository,
    prepared: PreparedCompetitiveTextRun,
) -> None:
    run_id = prepared.run_id
    repository.create_run(run_id, created_at=NOW)
    repository.append_requirement(
        prepared.blocked.requirement,
        expected_state_version=repository.state_version(run_id),
    )
    repository.append_requirement(
        prepared.ready.requirement,
        expected_state_version=repository.state_version(run_id),
    )
    assert prepared.ready.problem_graph is not None
    graph_ref = repository.seal_problem_graph(
        run_id,
        prepared.ready.problem_graph,
        expected_state_version=repository.state_version(run_id),
    )
    assert graph_ref == prepared.ready.problem_graph_artifact
    snapshot = prepared.repository.get_control_snapshot(
        prepared.selected_plan.payload.control_snapshot_artifact
    )
    assert snapshot is not None
    snapshot_ref = repository.append_control_snapshot(
        run_id,
        snapshot,
        expected_state_version=repository.state_version(run_id),
    )
    assert snapshot_ref == prepared.selected_plan.payload.control_snapshot_artifact
    assert prepared.ready.candidates is not None
    repository.append_candidate_set(
        run_id,
        prepared.ready.requirement.id,
        prepared.ready.candidates,
        expected_state_version=repository.state_version(run_id),
    )
    repository.append_plan(
        prepared.selected_plan,
        expected_state_version=repository.state_version(run_id),
    )


async def _persist_success(path: Path, *, run_id: str = "run_sqlite_success") -> PersistedSuccess:
    completed = await CompetitiveTextIntegrationHarness().run_success(
        run_id=run_id,
        candidate_id="speed",
    )
    repository = _repository(path)
    repository.initialize_schema()
    _append_planning(repository, completed.prepared)
    aggregate = completed.workbench.root
    for approval in aggregate.approvals:
        repository.append_approval(
            run_id,
            approval,
            expected_state_version=repository.state_version(run_id),
        )
    attempt_id = completed.executed.attempt_id
    repository.create_attempt(
        run_id=run_id,
        plan_version_id=completed.prepared.selected_plan.id,
        attempt_id=attempt_id,
        deadline_at=NOW + timedelta(hours=1),
        created_at=NOW,
        expected_state_version=repository.state_version(run_id),
    )
    lease = repository.claim_attempt(
        attempt_id,
        owner="worker_alpha",
        token="lease_alpha",
        now=NOW,
        lease_ttl=timedelta(minutes=30),
        expected_state_version=repository.state_version(run_id),
    )
    assert lease is not None
    for result in completed.executed.execution.require_delivery_results():
        invocation_id = f"invocation_{result.step_number}"
        repository.prepare_invocation(
            invocation_id=invocation_id,
            run_id=run_id,
            plan_version_id=result.plan_version_id,
            attempt_id=attempt_id,
            step_number=result.step_number,
            lease=lease,
            now=NOW,
            expected_state_version=repository.state_version(run_id),
        )
        repository.mark_invocation_sent(
            invocation_id,
            lease=lease,
            now=NOW,
            expected_state_version=repository.state_version(run_id),
        )
        verified = completed.prepared.artifacts.read_verified_json(
            run_id=result.run_id,
            plan_version_id=result.plan_version_id,
            attempt_id=result.attempt_id,
            step_number=result.step_number,
            artifact=result.result_artifact,
        )
        assert verified is not None
        repository.append_verified_json(
            verified,
            lease=lease,
            expected_state_version=repository.state_version(run_id),
        )
        repository.acknowledge_invocation(
            invocation_id,
            receipt_id=result.receipt_id,
            result_artifact=result.result_artifact,
            lease=lease,
            now=NOW,
            expected_state_version=repository.state_version(run_id),
        )
        repository.append_actor_result(
            result,
            lease=lease,
            expected_state_version=repository.state_version(run_id),
        )
    repository.complete_attempt(
        lease,
        now=NOW,
        expected_state_version=repository.state_version(run_id),
    )
    evidence_ref = repository.append_evidence_manifest(
        completed.evidence_manifest,
        expected_state_version=repository.state_version(run_id),
    )
    assert aggregate.evidence is not None
    assert evidence_ref == aggregate.evidence.artifact
    assert aggregate.deliverable is not None
    deliverable_ref = repository.append_deliverable(
        aggregate.deliverable.content,
        expected_state_version=repository.state_version(run_id),
    )
    assert deliverable_ref == aggregate.deliverable.artifact
    assert aggregate.review is not None
    review_ref = repository.append_review(
        aggregate.review.content,
        expected_state_version=repository.state_version(run_id),
    )
    assert review_ref == aggregate.review.artifact
    assert aggregate.report is not None
    report_ref = repository.append_report(
        aggregate.report.content,
        expected_state_version=repository.state_version(run_id),
    )
    assert report_ref == aggregate.report.artifact
    return PersistedSuccess(completed=completed, repository=repository)


def test_repository_projects_verified_rows_after_restart_without_get_writes(
    tmp_path: Path,
) -> None:
    database = tmp_path / "v3.sqlite3"
    persisted = asyncio.run(_persist_success(database))
    expected_report = persisted.completed.report
    persisted.repository.close()

    restarted = _repository(database)
    before = restarted._connection.total_changes
    projected = ResearchV3RepositoryProjector(restarted, clock=lambda: NOW).project(
        "run_sqlite_success"
    )
    after = restarted._connection.total_changes

    assert projected is not None
    assert projected.root.workflow.state == "text_report"
    assert projected.root.workflow.state_version == restarted.state_version("run_sqlite_success")
    assert projected.root.provenance.source_kind == "repository_projection"
    assert projected.root.report is not None
    assert projected.root.report.content == expected_report
    assert projected.root.evidence is not None
    assert projected.root.evidence.presentation_mode == "text"
    assert after == before


def test_scope_cas_one_active_attempt_and_implementation_id_boundary(
    tmp_path: Path,
) -> None:
    database = tmp_path / "coordination.sqlite3"
    prepared = asyncio.run(
        CompetitiveTextIntegrationHarness().prepare(
            run_id="run_coordination",
            candidate_id="speed",
        )
    )
    repository = _repository(database)
    repository.initialize_schema()
    _append_planning(repository, prepared)
    stale_version = repository.state_version(prepared.run_id) - 1
    with pytest.raises(ResearchV3ConflictError, match="state version"):
        repository.record_command_receipt(
            run_id=prepared.run_id,
            idempotency_key="command_stale",
            command_type="confirm",
            request_hash="a" * 64,
            response_payload={"ok": True},
            expected_state_version=stale_version,
        )

    repository.create_attempt(
        run_id=prepared.run_id,
        plan_version_id=prepared.selected_plan.id,
        attempt_id="attempt_primary",
        deadline_at=NOW + timedelta(hours=1),
        expected_state_version=repository.state_version(prepared.run_id),
        created_at=NOW,
    )
    with pytest.raises(ResearchV3ConflictError, match="one active"):
        repository.create_attempt(
            run_id=prepared.run_id,
            plan_version_id=prepared.selected_plan.id,
            attempt_id="attempt_parallel",
            deadline_at=NOW + timedelta(hours=1),
            expected_state_version=repository.state_version(prepared.run_id),
            created_at=NOW,
        )
    lease = repository.claim_attempt(
        "attempt_primary",
        owner="worker_primary",
        token="token_primary",
        now=NOW,
        lease_ttl=timedelta(minutes=5),
        expected_state_version=repository.state_version(prepared.run_id),
    )
    assert lease is not None
    renewed = repository.heartbeat_attempt(
        lease,
        now=NOW + timedelta(minutes=1),
        lease_ttl=timedelta(minutes=5),
        expected_state_version=repository.state_version(prepared.run_id),
    )
    with pytest.raises(ResearchV3ConflictError, match="stale"):
        repository.heartbeat_attempt(
            lease,
            now=NOW + timedelta(minutes=2),
            lease_ttl=timedelta(minutes=5),
            expected_state_version=repository.state_version(prepared.run_id),
        )
    assert isinstance(renewed, AttemptLeaseV3)

    foreign = _repository(
        database,
        owner_id="owner_foreign",
        workspace_id="workspace_alpha",
        project_id="project_alpha",
    )
    assert foreign.get_requirement(prepared.run_id, prepared.ready.requirement.id) is None
    assert ResearchV3RepositoryProjector(foreign, clock=lambda: NOW).project(prepared.run_id) is None
    with pytest.raises(ResearchV3NotFoundError):
        foreign.state_version(prepared.run_id)

    snapshot = prepared.repository.get_control_snapshot(
        prepared.selected_plan.payload.control_snapshot_artifact
    )
    assert snapshot is not None
    too_wide_actor = snapshot.actors[0].model_copy(update={"implementation_id": "a" * 121})
    too_wide_snapshot = snapshot.model_copy(
        update={"actors": (too_wide_actor, *snapshot.actors[1:])}
    )
    separate = _repository(tmp_path / "ids.sqlite3")
    separate.initialize_schema()
    separate.create_run("run_ids", created_at=NOW)
    before_ids = separate.state_version("run_ids")
    with pytest.raises(ValueError, match="Identifier contract"):
        separate.append_control_snapshot(
            "run_ids",
            too_wide_snapshot,
            expected_state_version=before_ids,
        )
    assert separate.state_version("run_ids") == before_ids


def test_restart_accounts_sent_invocation_as_unknown_and_never_replays(
    tmp_path: Path,
) -> None:
    database = tmp_path / "unknown.sqlite3"
    prepared = asyncio.run(
        CompetitiveTextIntegrationHarness().prepare(
            run_id="run_unknown",
            candidate_id="speed",
        )
    )
    repository = _repository(database)
    repository.initialize_schema()
    _append_planning(repository, prepared)
    repository.create_attempt(
        run_id=prepared.run_id,
        plan_version_id=prepared.selected_plan.id,
        attempt_id="attempt_unknown",
        deadline_at=NOW + timedelta(hours=1),
        expected_state_version=repository.state_version(prepared.run_id),
        created_at=NOW,
    )
    lease = repository.claim_attempt(
        "attempt_unknown",
        owner="worker_old",
        token="token_old",
        now=NOW,
        lease_ttl=timedelta(seconds=1),
        expected_state_version=repository.state_version(prepared.run_id),
    )
    assert lease is not None
    repository.prepare_invocation(
        invocation_id="invocation_unknown",
        run_id=prepared.run_id,
        plan_version_id=prepared.selected_plan.id,
        attempt_id="attempt_unknown",
        step_number=1,
        lease=lease,
        now=NOW,
        expected_state_version=repository.state_version(prepared.run_id),
    )
    repository.mark_invocation_sent(
        "invocation_unknown",
        lease=lease,
        now=NOW,
        expected_state_version=repository.state_version(prepared.run_id),
    )
    repository.close()

    restarted = _repository(database)
    reclaimed = restarted.claim_attempt(
        "attempt_unknown",
        owner="worker_new",
        token="token_new",
        now=NOW + timedelta(seconds=2),
        lease_ttl=timedelta(minutes=5),
        expected_state_version=restarted.state_version(prepared.run_id),
    )
    assert reclaimed is None
    invocation = restarted.get_invocation("invocation_unknown")
    assert invocation is not None
    assert invocation.state == "unknown"
    assert invocation.send_count == 1
    attempt = restarted.get_attempt("attempt_unknown")
    assert attempt is not None
    assert attempt.status == "paused"
    assert attempt.pause_reason == "unknown"
    assert restarted.list_recoverable_attempts(now=NOW + timedelta(seconds=3)) == (attempt,)
    with pytest.raises(ResearchV3ConflictError):
        restarted.mark_invocation_sent(
            "invocation_unknown",
            lease=lease,
            now=NOW + timedelta(seconds=3),
            expected_state_version=restarted.state_version(prepared.run_id),
        )
    assert restarted.get_invocation("invocation_unknown").send_count == 1


def test_exact_codec_corruption_idempotent_receipt_and_purge_tombstone(
    tmp_path: Path,
) -> None:
    database = tmp_path / "integrity.sqlite3"
    prepared = asyncio.run(
        CompetitiveTextIntegrationHarness().prepare(
            run_id="run_integrity",
            candidate_id="speed",
        )
    )
    repository = _repository(database)
    repository.initialize_schema()
    _append_planning(repository, prepared)
    state = repository.state_version(prepared.run_id)
    receipt, replayed = repository.record_command_receipt(
        run_id=prepared.run_id,
        idempotency_key="command_confirm",
        command_type="confirm",
        request_hash="b" * 64,
        response_payload={"accepted": True},
        expected_state_version=state,
        created_at=NOW,
    )
    assert replayed is False
    replay, replayed = repository.record_command_receipt(
        run_id=prepared.run_id,
        idempotency_key="command_confirm",
        command_type="confirm",
        request_hash="b" * 64,
        response_payload={"ignored_on_replay": True},
        expected_state_version=state,
        created_at=NOW,
    )
    assert replayed is True
    assert replay == receipt
    assert repository.state_version(prepared.run_id) == state + 1
    with pytest.raises(ResearchV3ConflictError, match="different command"):
        repository.record_command_receipt(
            run_id=prepared.run_id,
            idempotency_key="command_confirm",
            command_type="abort",
            request_hash="c" * 64,
            response_payload={},
            expected_state_version=repository.state_version(prepared.run_id),
        )

    repository._connection.execute(
        """UPDATE research_v3_records SET payload = ?
        WHERE run_id = ? AND record_kind = 'requirement' AND natural_key = ?""",
        (b"{}", prepared.run_id, prepared.ready.requirement.id),
    )
    repository._connection.commit()
    with pytest.raises(ResearchV3IntegrityError, match="payload hash"):
        repository.get_requirement(prepared.run_id, prepared.ready.requirement.id)
    with pytest.raises(ResearchV3IntegrityError):
        ResearchV3RepositoryProjector(repository, clock=lambda: NOW).project(prepared.run_id)

    purge_receipt, replayed = repository.purge_run(
        run_id=prepared.run_id,
        idempotency_key="command_purge",
        request_hash=canonical_json_v3_sha256({"run_id": prepared.run_id}),
        expected_state_version=repository.get_run_record(
            prepared.run_id, include_tombstone=True
        ).state_version,
        purged_at=NOW,
    )
    assert replayed is False
    assert repository.get_run_record(prepared.run_id) is None
    tombstone = repository.get_run_record(prepared.run_id, include_tombstone=True)
    assert tombstone is not None and tombstone.tombstoned_at == NOW
    assert repository.get_requirement(prepared.run_id, prepared.ready.requirement.id) is None
    assert ResearchV3RepositoryProjector(repository, clock=lambda: NOW).project(prepared.run_id) is None
    repeated, replayed = repository.purge_run(
        run_id=prepared.run_id,
        idempotency_key="command_purge",
        request_hash=purge_receipt.request_hash,
        expected_state_version=0,
        purged_at=NOW,
    )
    assert replayed is True
    assert repeated == purge_receipt

    dispatch = _repository(tmp_path / "dispatch.sqlite3")
    dispatch.initialize_schema()
    dispatch.create_run("run_dispatch", created_at=NOW)
    dispatch._connection.execute(
        "UPDATE research_v3_runs SET orchestration_version = 'research-v2' WHERE run_id = ?",
        ("run_dispatch",),
    )
    dispatch._connection.commit()
    with pytest.raises(ResearchV3IntegrityError, match="exactly research-v3"):
        ResearchV3RepositoryProjector(dispatch, clock=lambda: NOW).project("run_dispatch")
