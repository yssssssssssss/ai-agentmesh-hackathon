"""Tests for C1: Cold Start Import Channel."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentmesh.app import app
from agentmesh.chunker import chunk_text
from agentmesh.models import (
    DocumentRecord,
    MemoryLayer,
    Scope,
    Source,
    UserMemoryItem,
)
from agentmesh.routes.documents import import_document_chunks
from agentmesh.seed import PROJECT, USER, WORKSPACE
from agentmesh.store import SQLiteStore, store


def _password(user_id: str) -> str:
    return {"usr_current_designer": "designer123", "usr_team_lead": "lead123", "usr_admin": "admin123"}[user_id]


def _authenticated_client(user_id: str = USER.id) -> TestClient:
    client = TestClient(app)
    resp = client.post("/api/auth/login", json={"user_id": user_id, "password": _password(user_id)})
    assert resp.status_code == 200
    return client


def _fresh_store() -> SQLiteStore:
    db_path = Path(tempfile.mktemp(suffix=".sqlite3"))
    return SQLiteStore(db_path=db_path)


class TestChunker:
    def test_empty_text_returns_empty(self) -> None:
        assert chunk_text("") == []
        assert chunk_text("   ") == []
        assert chunk_text("\n\n") == []

    def test_short_text_single_chunk(self) -> None:
        text = "这是一段短文本。"
        chunks = chunk_text(text, max_chunk_size=500)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_paragraph_split(self) -> None:
        para1 = "第一段内容" * 50  # 250 chars
        para2 = "第二段内容" * 50  # 250 chars
        text = para1 + "\n\n" + para2
        chunks = chunk_text(text, max_chunk_size=300)
        assert len(chunks) >= 2
        assert all(len(c) <= 300 for c in chunks)

    def test_respects_max_chunk_size(self) -> None:
        text = "测试文本。" * 200  # 1000 chars
        chunks = chunk_text(text, max_chunk_size=100)
        assert all(len(c) <= 100 for c in chunks)
        assert len(chunks) >= 10

    def test_long_paragraph_splits_by_sentence(self) -> None:
        text = "。".join([f"第{i}句话内容比较长" for i in range(50)])
        chunks = chunk_text(text, max_chunk_size=200)
        assert len(chunks) > 1
        assert all(len(c) <= 200 for c in chunks)

    def test_overlap_provides_context(self) -> None:
        para1 = "A" * 100
        para2 = "B" * 100
        text = para1 + "\n\n" + para2
        chunks = chunk_text(text, max_chunk_size=180, overlap=30)
        assert len(chunks) == 2
        # Second chunk should start with tail of first due to overlap
        assert chunks[1].startswith("A" * 30)

    def test_mixed_content(self) -> None:
        text = "# 标题\n\n第一段正文。\n\n第二段正文很长。" * 30
        chunks = chunk_text(text, max_chunk_size=200)
        assert all(len(c) <= 200 for c in chunks)
        joined = "".join(c.replace("\n", "") for c in chunks)
        assert "标题" in joined
        assert "第一段正文" in joined


class TestDocumentImportChunks:
    def setup_method(self) -> None:
        store.reset()

    def test_import_creates_long_term_memories(self) -> None:
        doc = store.add_document(
            DocumentRecord(
                title="部署规范",
                file_name="deploy.md",
                content_type="text/markdown",
                text="第一段部署说明。\n\n第二段部署步骤。\n\n第三段注意事项。",
                source=Source(title="deploy.md", source_type="document", reference="document://deploy.md"),
                workspace_id=WORKSPACE.id,
                project_id=PROJECT.id,
                uploaded_by=USER.id,
            )
        )
        items = import_document_chunks(doc)
        assert len(items) >= 1
        for item in items:
            assert item.layer == MemoryLayer.LONG_TERM
            assert item.source_kind == "document_import"
            assert item.memory_type == "document_chunk"
            assert item.user_id == USER.id
            assert item.workspace_id == WORKSPACE.id

    def test_chunks_are_searchable(self) -> None:
        doc = store.add_document(
            DocumentRecord(
                title="冒烟测试流程",
                file_name="smoke-test.md",
                content_type="text/markdown",
                text="冒烟测试必须在部署前执行。\n\n步骤一：拉取最新代码。\n\n步骤二：运行全量回归测试。",
                source=Source(title="smoke-test.md", source_type="document", reference="document://smoke.md"),
                workspace_id=WORKSPACE.id,
                project_id=PROJECT.id,
                uploaded_by=USER.id,
            )
        )
        import_document_chunks(doc)
        results = store.search("冒烟测试", {Scope.PRIVATE}, workspace_id=WORKSPACE.id, user_id=USER.id)
        assert any("冒烟测试" in r.title or "冒烟测试" in r.summary for r in results)

    def test_import_long_document_respects_chunk_size(self) -> None:
        long_text = "\n\n".join([f"第{i}段内容包含比较详细的说明文字。" * 20 for i in range(20)])
        doc = store.add_document(
            DocumentRecord(
                title="超长文档",
                file_name="long.md",
                content_type="text/markdown",
                text=long_text,
                source=Source(title="long.md", source_type="document", reference="document://long.md"),
                workspace_id=WORKSPACE.id,
                project_id=PROJECT.id,
                uploaded_by=USER.id,
            )
        )
        items = import_document_chunks(doc)
        assert len(items) > 5
        for item in items:
            assert len(item.summary) <= 500


class TestImportToMemoryAPI:
    def setup_method(self) -> None:
        store.reset()

    def test_import_existing_document(self) -> None:
        doc = store.add_document(
            DocumentRecord(
                title="API规范",
                file_name="api.md",
                content_type="text/markdown",
                text="接口规范文档内容。\n\n第一条规范。\n\n第二条规范。",
                source=Source(title="api.md", source_type="document", reference="document://api.md"),
                workspace_id=WORKSPACE.id,
                project_id=PROJECT.id,
                uploaded_by=USER.id,
            )
        )
        client = _authenticated_client()
        resp = client.post(f"/api/documents/{doc.id}/import-to-memory")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "imported"
        assert data["chunk_count"] >= 1

    def test_import_idempotent(self) -> None:
        doc = store.add_document(
            DocumentRecord(
                title="重复导入测试",
                file_name="dup.md",
                content_type="text/markdown",
                text="内容。\n\n更多内容。",
                source=Source(title="dup.md", source_type="document", reference="document://dup.md"),
                workspace_id=WORKSPACE.id,
                project_id=PROJECT.id,
                uploaded_by=USER.id,
            )
        )
        client = _authenticated_client()
        resp1 = client.post(f"/api/documents/{doc.id}/import-to-memory")
        assert resp1.json()["status"] == "imported"
        resp2 = client.post(f"/api/documents/{doc.id}/import-to-memory")
        assert resp2.json()["status"] == "already_imported"

    def test_import_not_found(self) -> None:
        client = _authenticated_client()
        resp = client.post("/api/documents/nonexistent/import-to-memory")
        assert resp.status_code == 404

    def test_upload_auto_imports_chunks(self) -> None:
        client = _authenticated_client()
        content = "# 自动导入文档\n\n第一段正文内容。\n\n第二段正文内容。"
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("auto.md", content.encode(), "text/markdown")},
        )
        assert resp.status_code == 200
        # Check chunks were created
        chunk_items = [
            item for item in store.user_memory_items
            if item.source_kind == "document_import"
        ]
        assert len(chunk_items) >= 1
        assert all(item.layer == MemoryLayer.LONG_TERM for item in chunk_items)
