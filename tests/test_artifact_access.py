from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from typing import Any

import pytest

from agentmesh.artifacts import (
    ArtifactAccessError,
    ArtifactAccessScope,
    V1ArtifactReader,
    V1VerifiedArtifactStore,
    resolve_artifact_runtime,
)
from agentmesh.canonical_json import canonical_json_bytes
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    Artifact,
    ArtifactVerificationState,
    DeepSearchBudgetV1,
    SkillOrchestrationRequestMode,
)
from agentmesh.store import SQLiteStore

NOW = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)
OWNER = ArtifactAccessScope(
    user_id="user_artifact_owner",
    workspace_id="workspace_artifact",
    project_id="project_artifact",
)
FOREIGN_OWNER = ArtifactAccessScope(
    user_id="user_artifact_foreign",
    workspace_id=OWNER.workspace_id,
    project_id=OWNER.project_id,
)


def _run(
    *,
    run_id: str,
    planning_mode: AgentPlanningMode = AgentPlanningMode.DEEPSEARCH,
) -> AgentRun:
    is_deepsearch = planning_mode is AgentPlanningMode.DEEPSEARCH
    return AgentRun(
        id=run_id,
        thread_id=f"thread_{run_id}",
        user_id=OWNER.user_id,
        workspace_id=OWNER.workspace_id,
        project_id=OWNER.project_id,
        input_text="produce a verified report",
        status=AgentRunStatus.PLANNING if is_deepsearch else AgentRunStatus.CREATED,
        planning_mode=planning_mode,
        requested_orchestration_mode=(SkillOrchestrationRequestMode.AUTO if is_deepsearch else None),
        orchestration_version="v1",
        orchestration_mode="execute",
        deadline_at=None,
        absolute_expires_at=NOW + timedelta(days=7) if is_deepsearch else None,
        deepsearch_budget=DeepSearchBudgetV1() if is_deepsearch else None,
        created_at=NOW,
        updated_at=NOW,
    )


def _report_content(run: AgentRun, *, rendered_text: str = "Verified report") -> str:
    payload = {
        "schema_version": "deepsearch-report-v1",
        "run_id": run.id,
        "requirement_version_id": f"requirement_{run.id}",
        "plan_id": f"plan_{run.id}",
        "plan_version": 1,
        "requirement_content_hash": "1" * 64,
        "problem_graph_hash": "2" * 64,
        "plan_content_hash": "3" * 64,
        "evidence_manifest_hash": "4" * 64,
        "synthesis_content_hash": "5" * 64,
        "review_outcome": "pass",
        "review_reason_code": None,
        "report_status": "complete",
        "title": "Verified report",
        "claims": [],
        "executive_summary_claim_ids": [],
        "sections": [],
        "sources": [],
        "limitations": [],
        "rendered_text": rendered_text,
    }
    return canonical_json_bytes(payload).decode("utf-8")


def _report_artifact(
    run: AgentRun,
    *,
    artifact_id: str,
    state: ArtifactVerificationState,
    content: str | None = None,
) -> Artifact:
    body = "" if content is None else content
    encoded = body.encode("utf-8")
    sealed = state == ArtifactVerificationState.SEALED
    return Artifact(
        id=artifact_id,
        run_id=run.id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        user_id=run.user_id,
        artifact_type="deepsearch_report",
        content_type="application/json",
        content=body,
        verification_state=state,
        schema_version="deepsearch-report-v1",
        content_hash=hashlib.sha256(encoded).hexdigest() if sealed else None,
        size_bytes=len(encoded) if sealed else None,
        requirement_version_id=f"requirement_{run.id}",
        plan_version_id=f"plan_{run.id}:v1",
        created_at=NOW,
        updated_at=NOW + timedelta(seconds=1),
    )


def _user_evidence_artifact(
    run: AgentRun,
    *,
    artifact_id: str,
    excerpt: str,
) -> Artifact:
    excerpt_bytes = excerpt.encode("utf-8")
    payload = {
        "schema_version": "deepsearch-user-evidence-v1",
        "origin_type": "user_input",
        "run_id": run.id,
        "requirement_version_id": f"requirement_{run.id}",
        "plan_id": None,
        "plan_version": None,
        "node_id": None,
        "attempt": None,
        "tool_name": None,
        "tool_implementation_id": None,
        "tool_implementation_version": None,
        "execution_mode": None,
        "content_provider": None,
        "tool_call_id": None,
        "operation_key": None,
        "request_hash": "6" * 64,
        "source_id": None,
        "source_ordinal": None,
        "normalized_reference": "message:message_evidence_1",
        "retrieved_at": "2026-08-26T08:00:00Z",
        "excerpt": excerpt,
        "content_hash": hashlib.sha256(excerpt_bytes).hexdigest(),
        "size_bytes": len(excerpt_bytes),
    }
    content = canonical_json_bytes(payload).decode("utf-8")
    encoded = content.encode("utf-8")
    return Artifact(
        id=artifact_id,
        run_id=run.id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        user_id=run.user_id,
        artifact_type="deepsearch_user_evidence",
        content_type="application/json",
        content=content,
        verification_state=ArtifactVerificationState.SEALED,
        schema_version="deepsearch-user-evidence-v1",
        content_hash=hashlib.sha256(encoded).hexdigest(),
        size_bytes=len(encoded),
        requirement_version_id=f"requirement_{run.id}",
        created_at=NOW,
        updated_at=NOW,
    )


def _insert_artifact_payload(
    repository: SQLiteStore,
    payload: dict[str, Any],
    *,
    indexed_overrides: dict[str, Any] | None = None,
) -> None:
    indexed = {
        "id": payload["id"],
        "run_id": payload["run_id"],
        "created_at": payload["created_at"],
        "workspace_id": payload["workspace_id"],
        "project_id": payload["project_id"],
        "user_id": payload["user_id"],
        "artifact_type": payload["artifact_type"],
        "content_type": payload["content_type"],
        "truncated": int(payload["truncated"]),
        "verification_state": payload["verification_state"],
        "schema_version": payload["schema_version"],
        "content_hash": payload["content_hash"],
        "size_bytes": payload["size_bytes"],
        "requirement_version_id": payload["requirement_version_id"],
        "plan_version_id": payload["plan_version_id"],
        "attempt_id": payload["attempt_id"],
        "step_number": payload["step_number"],
        "purged_at": payload["purged_at"],
        "purged_by": payload["purged_by"],
        "updated_at": payload["updated_at"],
    }
    indexed.update(indexed_overrides or {})
    with repository._connect() as connection:
        connection.execute(
            """INSERT INTO artifacts(
                id, run_id, payload, created_at, workspace_id, project_id, user_id,
                artifact_type, content_type, truncated, verification_state, schema_version,
                content_hash, size_bytes, requirement_version_id, plan_version_id,
                attempt_id, step_number, purged_at, purged_by, updated_at
            ) VALUES (
                :id, :run_id, :payload, :created_at, :workspace_id, :project_id, :user_id,
                :artifact_type, :content_type, :truncated, :verification_state, :schema_version,
                :content_hash, :size_bytes, :requirement_version_id, :plan_version_id,
                :attempt_id, :step_number, :purged_at, :purged_by, :updated_at
            )""",
            {**indexed, "payload": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
        )


def _rewrite_run_identity(
    repository: SQLiteStore,
    run: AgentRun,
    *,
    payload_version: str,
    indexed_version: str,
) -> None:
    payload = run.model_dump(mode="json")
    payload["orchestration_version"] = payload_version
    with repository._connect() as connection:
        connection.execute(
            "UPDATE agent_runs SET payload = ?, orchestration_version = ? WHERE id = ?",
            (json.dumps(payload, ensure_ascii=False, separators=(",", ":")), indexed_version, run.id),
        )


def _assert_access_error(code: str, action) -> None:  # noqa: ANN001
    with pytest.raises(ArtifactAccessError) as captured:
        action()
    assert captured.value.code == code


def test_v1_legacy_reader_preserves_last_payload_without_hash_verification(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "legacy.sqlite3")
    run = repository.save_agent_run(_run(run_id="run_legacy", planning_mode=AgentPlanningMode.STANDARD))
    first = Artifact(
        id="artifact_legacy",
        run_id=run.id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        user_id=run.user_id,
        artifact_type="tool_output",
        content_type="text/plain",
        content="old body",
        created_at=NOW,
    )
    replacement = first.model_copy(
        update={"content": "new body", "created_at": NOW + timedelta(minutes=1)}
    )
    repository.save_artifact(first)
    repository.save_artifact(replacement)

    assert resolve_artifact_runtime(repository, replacement.id, reader_scope=OWNER) == "v1_legacy"
    loaded = V1ArtifactReader(repository).read_for_owner(replacement.id, reader_scope=OWNER)

    assert loaded.content == "new body"
    assert loaded.verification_state is None
    assert loaded.content_hash is None


def test_v1_deepsearch_reader_returns_only_schema_valid_sealed_content(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "verified.sqlite3")
    run = repository.save_agent_run(_run(run_id="run_verified"))
    writer = V1VerifiedArtifactStore(repository)
    staging = _report_artifact(
        run,
        artifact_id="artifact_verified_report",
        state=ArtifactVerificationState.STAGING,
    )
    sealed = _report_artifact(
        run,
        artifact_id=staging.id,
        state=ArtifactVerificationState.SEALED,
        content=_report_content(run),
    )
    writer.create_staging_report(staging)
    writer.seal_report(sealed)

    assert resolve_artifact_runtime(repository, sealed.id, reader_scope=OWNER) == "v1_verified"
    loaded = V1ArtifactReader(repository).read_for_owner(sealed.id, reader_scope=OWNER)

    assert loaded.content == sealed.content
    assert loaded.content_hash == "34929990009f8f2bd905513e97329643d86bad6d212e8a307de2b08ec476b12c"


@pytest.mark.parametrize(
    ("state", "expected_code"),
    [
        (ArtifactVerificationState.STAGING, "artifact_not_ready"),
        (ArtifactVerificationState.FAILED, "artifact_invalid"),
        (ArtifactVerificationState.PURGED, "artifact_purged"),
    ],
)
def test_nonsealed_state_wins_before_body_validation(tmp_path, state, expected_code) -> None:  # noqa: ANN001
    repository = SQLiteStore(tmp_path / f"{state.value}.sqlite3")
    run = repository.save_agent_run(_run(run_id=f"run_{state.value}"))
    sealed = _report_artifact(
        run,
        artifact_id=f"artifact_{state.value}",
        state=ArtifactVerificationState.SEALED,
        content=_report_content(run),
    )
    payload = sealed.model_dump(mode="json")
    payload.update(
        verification_state=state.value,
        content="{this is deliberately not JSON",
        content_hash=None if state != ArtifactVerificationState.PURGED else sealed.content_hash,
        size_bytes=None if state != ArtifactVerificationState.PURGED else sealed.size_bytes,
        purged_at=NOW.isoformat() if state == ArtifactVerificationState.PURGED else None,
        purged_by=OWNER.user_id if state == ArtifactVerificationState.PURGED else None,
    )
    _insert_artifact_payload(repository, payload)

    _assert_access_error(
        expected_code,
        lambda: V1ArtifactReader(repository).read_for_owner(sealed.id, reader_scope=OWNER),
    )


def test_v1_reader_hides_artifacts_from_foreign_owners(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "owner.sqlite3")
    run = repository.save_agent_run(_run(run_id="run_owner"))
    artifact = _report_artifact(
        run,
        artifact_id="artifact_owner",
        state=ArtifactVerificationState.SEALED,
        content=_report_content(run),
    )
    _insert_artifact_payload(repository, artifact.model_dump(mode="json"))

    _assert_access_error(
        "artifact_not_found",
        lambda: V1ArtifactReader(repository).read_for_owner(artifact.id, reader_scope=FOREIGN_OWNER),
    )


def test_verified_reader_rejects_canonical_json_that_does_not_match_the_registered_dto(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "schema-invalid.sqlite3")
    run = repository.save_agent_run(_run(run_id="run_schema_invalid"))
    artifact = _report_artifact(
        run,
        artifact_id="artifact_schema_invalid",
        state=ArtifactVerificationState.SEALED,
        content="{}",
    )
    _insert_artifact_payload(repository, artifact.model_dump(mode="json"))

    _assert_access_error(
        "artifact_integrity_failed",
        lambda: V1ArtifactReader(repository).read_for_owner(artifact.id, reader_scope=OWNER),
    )


@pytest.mark.parametrize(
    "corruption",
    [
        "unknown_schema",
        "standard_verified",
        "run_version_mismatch",
        "unknown_runtime",
        "retired_runtime",
        "artifact_index",
    ],
)
def test_runtime_resolution_fails_closed_for_unknown_or_mismatched_identity(tmp_path, corruption: str) -> None:
    repository = SQLiteStore(tmp_path / f"{corruption}.sqlite3")
    run = repository.save_agent_run(_run(run_id=f"run_{corruption}"))
    artifact = _report_artifact(
        run,
        artifact_id=f"artifact_{corruption}",
        state=ArtifactVerificationState.SEALED,
        content=_report_content(run),
    )
    payload = artifact.model_dump(mode="json")
    indexed_overrides: dict[str, Any] = {}
    if corruption == "unknown_schema":
        payload["schema_version"] = "deepsearch-report-v999"
        indexed_overrides["schema_version"] = payload["schema_version"]
    elif corruption == "standard_verified":
        run_payload = run.model_dump(mode="json")
        run_payload["planning_mode"] = AgentPlanningMode.STANDARD.value
        with repository._connect() as connection:
            connection.execute(
                "UPDATE agent_runs SET payload = ? WHERE id = ?",
                (json.dumps(run_payload, ensure_ascii=False, separators=(",", ":")), run.id),
            )
    elif corruption == "run_version_mismatch":
        _rewrite_run_identity(repository, run, payload_version="v1", indexed_version="research-v2")
    elif corruption == "unknown_runtime":
        _rewrite_run_identity(repository, run, payload_version="future-v9", indexed_version="future-v9")
    elif corruption == "retired_runtime":
        _rewrite_run_identity(repository, run, payload_version="research-v3", indexed_version="research-v3")
    else:
        indexed_overrides["artifact_type"] = "deepsearch_evidence_manifest"
    _insert_artifact_payload(repository, payload, indexed_overrides=indexed_overrides)

    _assert_access_error(
        "artifact_integrity_failed",
        lambda: resolve_artifact_runtime(repository, artifact.id, reader_scope=OWNER),
    )


def test_runtime_resolution_keeps_research_v2_on_its_frozen_reader(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "research-v2.sqlite3")
    run = repository.save_agent_run(_run(run_id="run_research_v2", planning_mode=AgentPlanningMode.STANDARD))
    artifact = Artifact(
        id="artifact_research_v2",
        run_id=run.id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        user_id=run.user_id,
        artifact_type="tool_result",
        content_type="application/json",
        content="{}",
        verification_state=ArtifactVerificationState.SEALED,
        schema_version="result-v1",
        content_hash="44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
        size_bytes=2,
        requirement_version_id="requirement_research_v2",
        created_at=NOW,
        updated_at=NOW,
    )
    _insert_artifact_payload(repository, artifact.model_dump(mode="json"))
    _rewrite_run_identity(
        repository,
        run,
        payload_version="research-v2",
        indexed_version="research-v2",
    )

    assert resolve_artifact_runtime(repository, artifact.id, reader_scope=OWNER) == "research-v2"


def test_report_writer_is_idempotent_but_rejects_illegal_terminal_transitions(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "writer-cas.sqlite3")
    run = repository.save_agent_run(_run(run_id="run_writer_cas"))
    writer = V1VerifiedArtifactStore(repository)
    staging = _report_artifact(
        run,
        artifact_id="artifact_writer_cas",
        state=ArtifactVerificationState.STAGING,
    )
    sealed = _report_artifact(
        run,
        artifact_id=staging.id,
        state=ArtifactVerificationState.SEALED,
        content=_report_content(run),
    )

    assert writer.create_staging_report(staging) == writer.create_staging_report(staging)
    assert writer.seal_report(sealed) == writer.seal_report(sealed)

    conflicting = _report_artifact(
        run,
        artifact_id=sealed.id,
        state=ArtifactVerificationState.SEALED,
        content=_report_content(run, rendered_text="Conflicting report"),
    )
    failed = _report_artifact(
        run,
        artifact_id=sealed.id,
        state=ArtifactVerificationState.FAILED,
    )
    with pytest.raises(ArtifactAccessError):
        writer.seal_report(conflicting)
    with pytest.raises(ArtifactAccessError):
        writer.fail_report(failed)


def test_insert_only_verified_artifact_accepts_exact_replay_and_rejects_overwrite(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "writer-insert-only.sqlite3")
    run = repository.save_agent_run(_run(run_id="run_writer_insert_only"))
    writer = V1VerifiedArtifactStore(repository)
    artifact = _user_evidence_artifact(
        run,
        artifact_id="artifact_writer_insert_only",
        excerpt="User supplied evidence",
    )

    assert writer.insert_sealed(artifact) == writer.insert_sealed(artifact)

    conflicting = _user_evidence_artifact(
        run,
        artifact_id=artifact.id,
        excerpt="Different evidence",
    )
    with pytest.raises(ArtifactAccessError):
        writer.insert_sealed(conflicting)


def test_verified_writer_rejects_outer_hash_and_evidence_schema_spoofing(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "writer-integrity.sqlite3")
    run = repository.save_agent_run(_run(run_id="run_writer_integrity"))
    writer = V1VerifiedArtifactStore(repository)
    evidence = _user_evidence_artifact(
        run,
        artifact_id="artifact_writer_integrity",
        excerpt="User supplied evidence",
    )

    bad_hash = evidence.model_copy(update={"content_hash": "0" * 64})
    _assert_access_error("artifact_integrity_failed", lambda: writer.insert_sealed(bad_hash))

    disguised = evidence.model_copy(
        update={
            "artifact_type": "deepsearch_tool_evidence",
            "schema_version": "deepsearch-tool-evidence-v1",
            "plan_version_id": f"plan_{run.id}:v1",
            "attempt_id": "node_1:attempt:1",
            "step_number": 1,
        }
    )
    _assert_access_error("artifact_integrity_failed", lambda: writer.insert_sealed(disguised))


def test_report_writer_rejects_incomplete_staging_lineage_and_corrupt_existing_state(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "writer-staging-integrity.sqlite3")
    run = repository.save_agent_run(_run(run_id="run_writer_staging_integrity"))
    writer = V1VerifiedArtifactStore(repository)
    staging = _report_artifact(
        run,
        artifact_id="artifact_writer_staging_integrity",
        state=ArtifactVerificationState.STAGING,
    )

    missing_plan = staging.model_copy(update={"plan_version_id": None})
    _assert_access_error("artifact_integrity_failed", lambda: writer.create_staging_report(missing_plan))

    writer.create_staging_report(staging)
    with repository._connect() as connection:
        row = connection.execute("SELECT payload FROM artifacts WHERE id = ?", (staging.id,)).fetchone()
        payload = json.loads(row["payload"])
        payload["verification_state"] = ArtifactVerificationState.FAILED.value
        connection.execute(
            "UPDATE artifacts SET payload = ? WHERE id = ?",
            (json.dumps(payload, ensure_ascii=False, separators=(",", ":")), staging.id),
        )

    sealed = _report_artifact(
        run,
        artifact_id=staging.id,
        state=ArtifactVerificationState.SEALED,
        content=_report_content(run),
    )
    _assert_access_error("artifact_integrity_failed", lambda: writer.seal_report(sealed))


def test_failed_report_is_idempotent_and_cannot_be_revived(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "writer-failed.sqlite3")
    run = repository.save_agent_run(_run(run_id="run_writer_failed"))
    writer = V1VerifiedArtifactStore(repository)
    staging = _report_artifact(
        run,
        artifact_id="artifact_writer_failed",
        state=ArtifactVerificationState.STAGING,
    )
    failed = _report_artifact(
        run,
        artifact_id=staging.id,
        state=ArtifactVerificationState.FAILED,
    )
    sealed = _report_artifact(
        run,
        artifact_id=staging.id,
        state=ArtifactVerificationState.SEALED,
        content=_report_content(run),
    )

    writer.create_staging_report(staging)
    assert writer.fail_report(failed) == writer.fail_report(failed)
    with pytest.raises(ArtifactAccessError):
        writer.seal_report(sealed)


def test_report_terminal_transition_has_one_concurrent_winner(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "writer-terminal-race.sqlite3")
    run = repository.save_agent_run(_run(run_id="run_writer_terminal_race"))
    writer = V1VerifiedArtifactStore(repository)
    staging = _report_artifact(
        run,
        artifact_id="artifact_writer_terminal_race",
        state=ArtifactVerificationState.STAGING,
    )
    sealed = _report_artifact(
        run,
        artifact_id=staging.id,
        state=ArtifactVerificationState.SEALED,
        content=_report_content(run),
    )
    failed = _report_artifact(
        run,
        artifact_id=staging.id,
        state=ArtifactVerificationState.FAILED,
    )
    writer.create_staging_report(staging)
    barrier = Barrier(2)

    def transition(target: Artifact) -> str:
        barrier.wait()
        try:
            if target.verification_state == ArtifactVerificationState.SEALED:
                writer.seal_report(target)
            else:
                writer.fail_report(target)
        except ArtifactAccessError as error:
            return error.code
        return target.verification_state.value

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(transition, [sealed, failed]))

    assert len([outcome for outcome in outcomes if outcome in {"sealed", "failed"}]) == 1
    assert len([outcome for outcome in outcomes if outcome == "artifact_state_transition_invalid"]) == 1
    with repository._read_connect() as connection:
        row = connection.execute(
            "SELECT verification_state FROM artifacts WHERE id = ?",
            (staging.id,),
        ).fetchone()
    assert row["verification_state"] in {"sealed", "failed"}


def test_verified_writer_does_not_commit_a_caller_owned_transaction(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "writer-transaction.sqlite3")
    run = repository.save_agent_run(_run(run_id="run_writer_transaction"))
    writer = V1VerifiedArtifactStore(repository)
    staging = _report_artifact(
        run,
        artifact_id="artifact_writer_transaction",
        state=ArtifactVerificationState.STAGING,
    )

    with repository._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        writer.create_staging_report(staging, connection=connection)
        connection.rollback()

    _assert_access_error(
        "artifact_not_found",
        lambda: V1ArtifactReader(repository).read_for_owner(staging.id, reader_scope=OWNER),
    )
