from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from agentmesh.research_orchestration.api import ResearchNotFoundError, ResearchOwnerScope
from agentmesh.research_orchestration.v2_artifact_history import (
    ArtifactReaderScope,
    ArtifactStoreError,
    V2ArtifactHistoryReader,
)
from agentmesh.research_orchestration.v2_history import V2HistoryAdapter
from agentmesh.store import SQLiteStore

FIXTURE = Path(__file__).parent / "fixtures" / "ai_x_history" / "research-v2-history.sqlite3"
RUN_ID = "run_v2_history_001"
MANIFEST_ID = "artifact_manifest_6f93dae744ab9de20487912dffb5961d"
REPORT_ID = "artifact_report_ca784c802b99661684965a69b4887393"
TOMBSTONE_ID = "artifact_fixture_tombstone"
OWNER = ResearchOwnerScope(
    user_id="user_fixture_owner",
    workspace_id="workspace_fixture",
    project_id="project_fixture",
)
ARTIFACT_SCOPE = ArtifactReaderScope(
    user_id=OWNER.user_id,
    workspace_id=OWNER.workspace_id,
    project_id=OWNER.project_id,
    run_id=RUN_ID,
)


def _historical_repository(tmp_path: Path) -> SQLiteStore:
    database = tmp_path / "research-v2-history.sqlite3"
    shutil.copy2(FIXTURE, database)
    return SQLiteStore(database)


def _reader(repository: SQLiteStore) -> V2HistoryAdapter:
    return V2HistoryAdapter(repository, V2ArtifactHistoryReader(repository))


def test_v2_history_fixture_is_owner_scoped_deterministic_and_read_only(tmp_path: Path) -> None:
    repository = _historical_repository(tmp_path)
    artifact_reader = V2ArtifactHistoryReader(repository)
    reader = V2HistoryAdapter(repository, artifact_reader)

    with sqlite3.connect(repository.db_path) as observer:
        before = int(observer.execute("PRAGMA data_version").fetchone()[0])
        first = reader.get_projection(RUN_ID, owner=OWNER)
        second = reader.get_projection(RUN_ID, owner=OWNER)
        after = int(observer.execute("PRAGMA data_version").fetchone()[0])

    assert first == second
    assert first.status.value == "completed"
    assert first.workflow.phase.value == "terminal"
    assert first.result.report is not None
    assert first.result.report.title == "Competitive Analysis Report"
    assert first.integrity_errors == []
    assert before == after
    assert not any(
        hasattr(artifact_reader, method)
        for method in ("stage", "seal", "seal_bundle", "purge_research_data", "cleanup_expired_transients")
    )

    with repository._read_connect() as connection, pytest.raises(sqlite3.OperationalError):
        connection.execute("UPDATE agent_runs SET status = status WHERE id = ?", (RUN_ID,))

    with pytest.raises(ResearchNotFoundError):
        reader.get_projection(RUN_ID, owner=OWNER.model_copy(update={"user_id": "foreign_user"}))


def test_v2_artifact_history_hides_foreign_owner_and_purged_content(tmp_path: Path) -> None:
    repository = _historical_repository(tmp_path)
    reader = V2ArtifactHistoryReader(repository)

    with pytest.raises(ArtifactStoreError, match="artifact_not_found"):
        reader.read_verified_for_owner(
            REPORT_ID,
            reader_scope=ARTIFACT_SCOPE.model_copy(update={"user_id": "foreign_user"}),
        )
    with pytest.raises(ArtifactStoreError, match="artifact_purged"):
        reader.read_verified_for_owner(TOMBSTONE_ID, reader_scope=ARTIFACT_SCOPE)


def test_v2_history_hides_report_when_an_upstream_artifact_is_corrupt(tmp_path: Path) -> None:
    repository = _historical_repository(tmp_path)
    with sqlite3.connect(repository.db_path) as connection:
        row = connection.execute("SELECT payload FROM artifacts WHERE id = ?", (MANIFEST_ID,)).fetchone()
        payload = json.loads(row[0])
        payload["content"] = f'{payload["content"]} '
        connection.execute(
            "UPDATE artifacts SET payload = ? WHERE id = ?",
            (json.dumps(payload), MANIFEST_ID),
        )

    with sqlite3.connect(repository.db_path) as observer:
        row_before = observer.execute("SELECT * FROM artifacts WHERE id = ?", (MANIFEST_ID,)).fetchone()
        version_before = int(observer.execute("PRAGMA data_version").fetchone()[0])
        projection = _reader(repository).get_projection(RUN_ID, owner=OWNER)
        version_after = int(observer.execute("PRAGMA data_version").fetchone()[0])
        row_after = observer.execute("SELECT * FROM artifacts WHERE id = ?", (MANIFEST_ID,)).fetchone()

    assert projection.result.report is None
    assert projection.artifacts.report_id is None
    assert "evidence_manifest:artifact_integrity_failed" in projection.integrity_errors
    assert row_before == row_after
    assert version_before == version_after


def test_v2_artifact_history_rejects_noncanonical_json_without_repairing_it(tmp_path: Path) -> None:
    repository = _historical_repository(tmp_path)
    with sqlite3.connect(repository.db_path) as connection:
        row = connection.execute("SELECT payload FROM artifacts WHERE id = ?", (MANIFEST_ID,)).fetchone()
        payload = json.loads(row[0])
        noncanonical = json.dumps(json.loads(payload["content"]), indent=2)
        encoded = noncanonical.encode("utf-8")
        payload.update(
            content=noncanonical,
            content_hash=hashlib.sha256(encoded).hexdigest(),
            size_bytes=len(encoded),
        )
        connection.execute(
            "UPDATE artifacts SET payload = ?, content_hash = ?, size_bytes = ? WHERE id = ?",
            (json.dumps(payload), payload["content_hash"], payload["size_bytes"], MANIFEST_ID),
        )

    with sqlite3.connect(repository.db_path) as observer:
        row_before = observer.execute("SELECT * FROM artifacts WHERE id = ?", (MANIFEST_ID,)).fetchone()
        version_before = int(observer.execute("PRAGMA data_version").fetchone()[0])
        with pytest.raises(ArtifactStoreError, match="artifact_integrity_failed"):
            V2ArtifactHistoryReader(repository).read_verified_for_owner(
                MANIFEST_ID,
                reader_scope=ARTIFACT_SCOPE,
            )
        version_after = int(observer.execute("PRAGMA data_version").fetchone()[0])
        row_after = observer.execute("SELECT * FROM artifacts WHERE id = ?", (MANIFEST_ID,)).fetchone()

    assert row_before == row_after
    assert version_before == version_after


def test_research_v2_writer_modules_are_absent() -> None:
    writer_modules = (
        "actors",
        "artifacts",
        "capabilities",
        "execution",
        "planning",
        "ports",
        "resource_snapshot",
        "runtime",
        "workflow",
    )

    for module in writer_modules:
        assert importlib.util.find_spec(f"agentmesh.research_orchestration.{module}") is None
