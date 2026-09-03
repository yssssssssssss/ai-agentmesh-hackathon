"""Tests for P2: vector search + RRF hybrid ranking."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from agentmesh.models import MemoryItem, MemoryStatus, Scope
from agentmesh.store import SQLiteStore


def _fresh_store_with_embedding() -> SQLiteStore:
    """Create store with embedding enabled (mocked)."""
    db_path = Path(tempfile.mktemp(suffix=".sqlite3"))
    with patch("agentmesh.store.EMBEDDING_ENABLED", False):
        # Disable during init to avoid backfill API calls
        pass
    return SQLiteStore(db_path=db_path)


_COUNTER = 0


def _fake_embed(text: str) -> list[float] | None:
    """Generate a deterministic fake embedding based on text content."""
    global _COUNTER
    _COUNTER += 1
    vec = [0.0] * 128
    for i, ch in enumerate(text[:128]):
        vec[i] = ord(ch) / 10000.0
    return vec


def _fake_embed_query_deploy(text: str) -> list[float] | None:
    """Simulate query embedding that's similar to deploy-related content."""
    return _fake_embed("部署失败排查记录 发布异常")


class TestVectorSearchIntegration:
    def test_vec_table_created(self) -> None:
        db_path = Path(tempfile.mktemp(suffix=".sqlite3"))
        import sqlite3

        with patch("agentmesh.embedding.EMBEDDING_ENABLED", False):
            SQLiteStore(db_path=db_path)
        conn = sqlite3.connect(db_path)
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = [t[0] for t in tables]
        assert "records_vec" in table_names
        conn.close()

    def test_embedding_stored_on_write(self) -> None:
        db_path = Path(tempfile.mktemp(suffix=".sqlite3"))
        import sqlite3

        with patch("agentmesh.embedding.EMBEDDING_ENABLED", False):
            s = SQLiteStore(db_path=db_path)

        with patch("agentmesh.embedding.embed_text", side_effect=_fake_embed), \
             patch("agentmesh.embedding.EMBEDDING_ENABLED", True):
            s.add_memory_item(
                MemoryItem(
                    title="部署失败排查",
                    summary="生产环境部署失败根因",
                    memory_type="note",
                    scope=Scope.TEAM_ACCEPTED,
                    workspace_id="ws1",
                )
            )

        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM records_vec").fetchone()[0]
        assert count == 1
        conn.close()

    def test_reset_clears_vec_table(self) -> None:
        db_path = Path(tempfile.mktemp(suffix=".sqlite3"))
        import sqlite3

        with patch("agentmesh.embedding.EMBEDDING_ENABLED", False):
            s = SQLiteStore(db_path=db_path)

        with patch("agentmesh.embedding.embed_text", side_effect=_fake_embed), \
             patch("agentmesh.embedding.EMBEDDING_ENABLED", True):
            s.add_memory_item(
                MemoryItem(
                    title="测试记忆",
                    summary="测试内容",
                    memory_type="note",
                    scope=Scope.TEAM_ACCEPTED,
                )
            )

        s.reset()
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM records_vec").fetchone()[0]
        assert count == 0
        conn.close()



    def test_inactive_memory_cannot_crowd_out_vector_candidate_cap(self, tmp_path, monkeypatch) -> None:
        repository = SQLiteStore(tmp_path / "lifecycle-vector-crowdout.sqlite3")

        def fake_embedding(text: str) -> list[float]:
            if text == "lifecycle semantic query" or "inactive lifecycle" in text:
                return [1.0, 0.0]
            return [0.8, 0.2]

        monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", True)
        monkeypatch.setattr("agentmesh.embedding.embed_text", fake_embedding)
        target = repository.add_memory_item(
            MemoryItem(
                id="mem_active_vector_target",
                title="visible knowledge record",
                summary="valid lifecycle target",
                memory_type="note",
                scope=Scope.TEAM_ACCEPTED,
                status=MemoryStatus.ACCEPTED,
                workspace_id="ws_lifecycle",
                project_id="prj_lifecycle",
            )
        )
        for index in range(60):
            repository.add_memory_item(
                MemoryItem(
                    id=f"mem_inactive_vector_{index:02d}",
                    title=f"inactive lifecycle {index}",
                    summary="higher cosine score but not eligible for Agent context",
                    memory_type="note",
                    scope=Scope.TEAM_ACCEPTED,
                    status=MemoryStatus.DEPRECATED,
                    workspace_id="ws_lifecycle",
                    project_id="prj_lifecycle",
                )
            )

        results = repository.search(
            "lifecycle semantic query",
            {Scope.TEAM_ACCEPTED},
            workspace_id="ws_lifecycle",
            project_id="prj_lifecycle",
            result_types={"memory_item"},
            max_results=1,
            agent_context=True,
        )

        assert [result.id for result in results] == [target.id]

    def test_cross_tenant_vectors_cannot_crowd_out_authorized_candidate(self, tmp_path, monkeypatch) -> None:
        repository = SQLiteStore(tmp_path / "tenant-vector-crowdout.sqlite3")

        def fake_embedding(text: str) -> list[float]:
            if "authorized semantic target" in text:
                return [0.8, 0.2]
            return [1.0, 0.0]

        monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", True)
        monkeypatch.setattr("agentmesh.embedding.embed_text", fake_embedding)
        target = repository.add_memory_item(
            MemoryItem(
                id="mem_authorized_vector",
                title="authorized semantic target",
                summary="visible only in the requested tenant",
                memory_type="note",
                scope=Scope.TEAM_ACCEPTED,
                workspace_id="ws_authorized",
                project_id="prj_authorized",
            )
        )
        for index in range(50):
            repository.add_memory_item(
                MemoryItem(
                    id=f"mem_foreign_vector_{index:02d}",
                    title=f"foreign semantic candidate {index}",
                    summary="higher cosine score but a different tenant",
                    memory_type="note",
                    scope=Scope.TEAM_ACCEPTED,
                    workspace_id="ws_foreign",
                    project_id="prj_foreign",
                )
            )

        results = repository.search(
            "tenant isolated semantic query",
            {Scope.TEAM_ACCEPTED},
            workspace_id="ws_authorized",
            project_id="prj_authorized",
            result_types={"memory_item"},
        )

        assert [result.id for result in results] == [target.id]

class TestRRFMerge:
    def test_rrf_merges_unique_results(self) -> None:
        fts_rows = [
            {"collection": "memory_items", "record_id": "a", "scope": "team_accepted",
             "workspace_id": "ws1", "project_id": "", "user_id": "", "created_at": ""},
            {"collection": "memory_items", "record_id": "b", "scope": "team_accepted",
             "workspace_id": "ws1", "project_id": "", "user_id": "", "created_at": ""},
        ]
        vec_rows = [
            {"collection": "memory_items", "record_id": "b", "scope": "team_accepted",
             "workspace_id": "ws1", "project_id": "", "user_id": "", "created_at": ""},
            {"collection": "memory_items", "record_id": "c", "scope": "team_accepted",
             "workspace_id": "ws1", "project_id": "", "user_id": "", "created_at": ""},
        ]
        merged = SQLiteStore._rrf_merge(fts_rows, vec_rows)
        ids = [r["record_id"] for r in merged]
        assert "a" in ids
        assert "b" in ids
        assert "c" in ids
        assert len(ids) == 3

    def test_rrf_boosts_items_in_both_lists(self) -> None:
        fts_rows = [
            {"collection": "memory_items", "record_id": "a", "scope": "team_accepted",
             "workspace_id": "", "project_id": "", "user_id": "", "created_at": ""},
            {"collection": "memory_items", "record_id": "shared", "scope": "team_accepted",
             "workspace_id": "", "project_id": "", "user_id": "", "created_at": ""},
        ]
        vec_rows = [
            {"collection": "memory_items", "record_id": "shared", "scope": "team_accepted",
             "workspace_id": "", "project_id": "", "user_id": "", "created_at": ""},
            {"collection": "memory_items", "record_id": "c", "scope": "team_accepted",
             "workspace_id": "", "project_id": "", "user_id": "", "created_at": ""},
        ]
        merged = SQLiteStore._rrf_merge(fts_rows, vec_rows)
        assert merged[0]["record_id"] == "shared"

    def test_rrf_handles_empty_vec(self) -> None:
        fts_rows = [
            {"collection": "memory_items", "record_id": "a", "scope": "team_accepted",
             "workspace_id": "", "project_id": "", "user_id": "", "created_at": ""},
        ]
        merged = SQLiteStore._rrf_merge(fts_rows, [])
        assert len(merged) == 1
        assert merged[0]["record_id"] == "a"

    def test_rrf_handles_empty_fts(self) -> None:
        vec_rows = [
            {"collection": "memory_items", "record_id": "x", "scope": "team_accepted",
             "workspace_id": "", "project_id": "", "user_id": "", "created_at": ""},
        ]
        merged = SQLiteStore._rrf_merge([], vec_rows)
        assert len(merged) == 1
        assert merged[0]["record_id"] == "x"


class TestEmbeddingDisabledGraceful:
    def test_search_works_without_embedding(self) -> None:
        """With embedding disabled, search falls back to FTS-only."""
        db_path = Path(tempfile.mktemp(suffix=".sqlite3"))
        with patch("agentmesh.embedding.EMBEDDING_ENABLED", False):
            s = SQLiteStore(db_path=db_path)
            s.add_memory_item(
                MemoryItem(
                    title="部署流程文档记录",
                    summary="详细的部署步骤和注意事项",
                    memory_type="note",
                    scope=Scope.TEAM_ACCEPTED,
                    workspace_id="ws1",
                )
            )
            results = s.search("部署流程", {Scope.TEAM_ACCEPTED}, workspace_id="ws1")
        assert len(results) == 1

    def test_embedding_api_failure_doesnt_break_write(self) -> None:
        """If embedding API fails, write still succeeds (FTS still works)."""
        db_path = Path(tempfile.mktemp(suffix=".sqlite3"))
        with patch("agentmesh.embedding.EMBEDDING_ENABLED", False):
            s = SQLiteStore(db_path=db_path)

        with patch("agentmesh.embedding.embed_text", return_value=None), \
             patch("agentmesh.embedding.EMBEDDING_ENABLED", True):
            s.add_memory_item(
                MemoryItem(
                    title="部署流程文档",
                    summary="步骤说明",
                    memory_type="note",
                    scope=Scope.TEAM_ACCEPTED,
                    workspace_id="ws1",
                )
            )

        results = s.search("部署流程", {Scope.TEAM_ACCEPTED}, workspace_id="ws1")
        assert len(results) == 1
