"""Tests for FTS5 full-text search upgrade in SQLiteStore."""

from __future__ import annotations

import tempfile
from pathlib import Path

from agentmesh.models import DocumentRecord, MemoryItem, MemoryLayer, Scope, Source, UserMemoryItem
from agentmesh.store import SQLiteStore


def _fresh_store() -> SQLiteStore:
    db_path = Path(tempfile.mktemp(suffix=".sqlite3"))
    return SQLiteStore(db_path=db_path)


class TestFTSBasicSearch:
    def test_chinese_trigram_match(self) -> None:
        """3+ character Chinese queries use FTS5 trigram matching."""
        s = _fresh_store()
        s.add_memory_item(
            MemoryItem(
                title="部署失败排查记录",
                summary="生产环境部署失败的根因是配置错误",
                memory_type="note",
                scope=Scope.TEAM_ACCEPTED,
                workspace_id="ws1",
                project_id="proj1",
            )
        )
        results = s.search("部署失败", {Scope.TEAM_ACCEPTED}, workspace_id="ws1", project_id="proj1")
        assert len(results) == 1
        assert results[0].result_type == "memory_item"
        assert "部署失败" in results[0].title

    def test_short_query_fallback(self) -> None:
        """2-character Chinese queries fall back to LIKE matching."""
        s = _fresh_store()
        s.add_memory_item(
            MemoryItem(
                title="首屏效率优先",
                summary="首屏加载速度是第一优先级",
                memory_type="decision",
                scope=Scope.TEAM_CANDIDATE,
                workspace_id="ws1",
                project_id="proj1",
            )
        )
        results = s.search("首屏", {Scope.TEAM_CANDIDATE}, workspace_id="ws1", project_id="proj1")
        assert len(results) == 1
        assert "首屏" in results[0].title

    def test_empty_query_returns_nothing(self) -> None:
        s = _fresh_store()
        s.add_memory_item(
            MemoryItem(title="test", summary="test", memory_type="note", scope=Scope.PRIVATE)
        )
        assert s.search("", {Scope.PRIVATE}) == []
        assert s.search("   ", {Scope.PRIVATE}) == []


class TestFTSScopeFiltering:
    def test_scope_filters_results(self) -> None:
        s = _fresh_store()
        s.add_memory_item(
            MemoryItem(
                title="团队可见记忆",
                summary="这是团队级的部署规范",
                memory_type="note",
                scope=Scope.TEAM_ACCEPTED,
                workspace_id="ws1",
            )
        )
        s.add_memory_item(
            MemoryItem(
                title="候选记忆部署",
                summary="这是待审核的部署记忆",
                memory_type="note",
                scope=Scope.TEAM_CANDIDATE,
                workspace_id="ws1",
            )
        )
        # Only TEAM_ACCEPTED scope
        results = s.search("部署", {Scope.TEAM_ACCEPTED}, workspace_id="ws1")
        assert all(r.scope == Scope.TEAM_ACCEPTED for r in results)
        assert len(results) == 1

    def test_user_memory_requires_private_scope_and_user_id(self) -> None:
        s = _fresh_store()
        s.add_user_memory_item(
            UserMemoryItem(
                user_id="user_a",
                layer=MemoryLayer.SHORT_TERM,
                title="用户A的部署笔记",
                summary="记录了今天的部署流程要点",
                source_kind="note",
                workspace_id="ws1",
                project_id="proj1",
            )
        )
        # Without PRIVATE scope: no results
        results = s.search("部署", {Scope.TEAM_ACCEPTED}, workspace_id="ws1", project_id="proj1", user_id="user_a")
        user_mem_results = [r for r in results if r.result_type == "user_memory_item"]
        assert len(user_mem_results) == 0

        # With PRIVATE scope but wrong user_id: no results
        results = s.search("部署", {Scope.PRIVATE}, workspace_id="ws1", project_id="proj1", user_id="user_b")
        user_mem_results = [r for r in results if r.result_type == "user_memory_item"]
        assert len(user_mem_results) == 0

        # Correct scope + user_id: found
        results = s.search("部署", {Scope.PRIVATE}, workspace_id="ws1", project_id="proj1", user_id="user_a")
        user_mem_results = [r for r in results if r.result_type == "user_memory_item"]
        assert len(user_mem_results) == 1


class TestFTSBackfill:
    def test_backfill_rebuilds_index_on_new_instance(self) -> None:
        """Recreating a store instance from the same DB backfills FTS."""
        db_path = Path(tempfile.mktemp(suffix=".sqlite3"))
        s1 = SQLiteStore(db_path=db_path)
        s1.add_memory_item(
            MemoryItem(
                title="自动化部署方案设计",
                summary="CI/CD 管线配置规范",
                memory_type="note",
                scope=Scope.TEAM_ACCEPTED,
                workspace_id="ws1",
            )
        )
        # Simulate FTS corruption by clearing it manually
        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.execute("DELETE FROM records_fts")
        conn.commit()
        conn.close()

        # New instance should backfill
        s2 = SQLiteStore(db_path=db_path)
        results = s2.search("自动化部署", {Scope.TEAM_ACCEPTED}, workspace_id="ws1")
        assert len(results) == 1

    def test_reset_clears_fts(self) -> None:
        s = _fresh_store()
        s.add_memory_item(
            MemoryItem(
                title="部署流程文档",
                summary="详细的部署步骤说明",
                memory_type="note",
                scope=Scope.TEAM_ACCEPTED,
            )
        )
        assert len(s.search("部署流程", {Scope.TEAM_ACCEPTED})) == 1
        s.reset()
        assert len(s.search("部署流程", {Scope.TEAM_ACCEPTED})) == 0


class TestFTSSpecialChars:
    def test_special_characters_dont_crash(self) -> None:
        s = _fresh_store()
        s.add_memory_item(
            MemoryItem(title="test", summary="test value", memory_type="note", scope=Scope.PRIVATE)
        )
        # These should not raise
        s.search('"quoted"', {Scope.PRIVATE})
        s.search("col:value", {Scope.PRIVATE})
        s.search("star*", {Scope.PRIVATE})
        s.search("(parens)", {Scope.PRIVATE})
        s.search("a AND b OR c", {Scope.PRIVATE})


class TestFTSDocumentSearch:
    def test_document_searchable_by_content(self) -> None:
        s = _fresh_store()
        s.add_document(
            DocumentRecord(
                title="API设计规范",
                file_name="api-design.md",
                content_type="text/markdown",
                text="RESTful API 设计时应该遵循资源导向原则",
                source=Source(title="手动上传", source_type="upload", reference="local"),
                workspace_id="ws1",
                project_id="proj1",
                uploaded_by="user_a",
            )
        )
        results = s.search(
            "RESTful API", {Scope.PRIVATE}, workspace_id="ws1", project_id="proj1", user_id="user_a"
        )
        doc_results = [r for r in results if r.result_type == "document"]
        assert len(doc_results) == 1
        assert doc_results[0].title == "API设计规范"
