from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from agentmesh.models import MemoryItem, MemoryLayer, Scope, UserMemoryItem, Workspace
from agentmesh.store import SQLiteStore


def _memory(record_id: str, text: str) -> MemoryItem:
    return MemoryItem(
        id=record_id,
        title=text,
        summary=text,
        memory_type="note",
        scope=Scope.TEAM_ACCEPTED,
        workspace_id="ws_test",
    )


def _daily_summary(record_id: str) -> UserMemoryItem:
    return UserMemoryItem(
        id=record_id,
        user_id="usr_daily",
        layer=MemoryLayer.SHORT_TERM,
        title="2026-08-24 每日短期记忆摘要",
        summary="当天关键记忆。",
        source_kind="daily_summary",
        memory_type="daily_summary",
        memory_date=date(2026, 8, 24),
        workspace_id="ws_test",
        project_id="prj_daily",
    )


def test_daily_summary_insert_is_atomic_under_concurrency(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "daily-summary-concurrency.sqlite3")
    workers = 20
    barrier = threading.Barrier(workers)

    def insert(index: int) -> bool:
        barrier.wait(timeout=5)
        _item, created = repository.add_daily_summary_if_absent(_daily_summary(f"summary_{index}"))
        return created

    with ThreadPoolExecutor(max_workers=workers) as executor:
        created = list(executor.map(insert, range(workers)))

    assert created.count(True) == 1
    assert created.count(False) == workers - 1
    assert len(
        repository.list_user_memory_items(
            "usr_daily",
            MemoryLayer.SHORT_TERM,
            "prj_daily",
            date(2026, 8, 24),
            "daily_summary",
        )
    ) == 1


def test_blocked_embedding_does_not_hold_sqlite_write_transaction(tmp_path, monkeypatch) -> None:
    repository = SQLiteStore(tmp_path / "concurrency.sqlite3")
    embedding_started = threading.Event()
    release_embedding = threading.Event()
    writer_finished = threading.Event()
    errors: list[BaseException] = []

    def blocked_embedding(text: str) -> list[float]:
        embedding_started.set()
        assert release_embedding.wait(timeout=5)
        return [1.0, 0.0]

    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", True)
    monkeypatch.setattr("agentmesh.embedding.embed_text", blocked_embedding)

    def write_searchable_record() -> None:
        try:
            repository.add_memory_item(_memory("mem_blocked", "blocked embedding"))
        except BaseException as error:
            errors.append(error)

    def write_unrelated_record() -> None:
        try:
            repository.save_workspace(Workspace(id="ws_concurrent", name="Concurrent", description="write"))
        except BaseException as error:
            errors.append(error)
        finally:
            writer_finished.set()

    embedding_thread = threading.Thread(target=write_searchable_record)
    embedding_thread.start()
    assert embedding_started.wait(timeout=5)

    writer_thread = threading.Thread(target=write_unrelated_record)
    writer_thread.start()
    assert writer_finished.wait(timeout=1), "SQLite write was blocked by embedding provider"
    assert repository.get_workspace("ws_concurrent") is not None

    release_embedding.set()
    embedding_thread.join(timeout=5)
    writer_thread.join(timeout=5)
    assert not errors


def test_updated_text_cannot_keep_or_restore_old_ready_vector(tmp_path, monkeypatch) -> None:
    repository = SQLiteStore(tmp_path / "stale-vector.sqlite3")
    monkeypatch.setattr("agentmesh.embedding.embed_text", lambda text: [1.0, 0.0])
    item = _memory("mem_versioned", "old searchable text")
    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", True)
    repository.add_memory_item(item)
    assert repository.get_vector_state("memory_items", item.id).state == "ready"

    embedding_started = threading.Event()
    release_embedding = threading.Event()

    def failed_replacement_embedding(text: str):
        embedding_started.set()
        assert release_embedding.wait(timeout=5)
        return None

    monkeypatch.setattr("agentmesh.embedding.embed_text", failed_replacement_embedding)
    item.title = "new searchable text"
    item.summary = "new searchable text"
    update_thread = threading.Thread(target=repository.save_memory_item, args=(item,))
    update_thread.start()
    assert embedding_started.wait(timeout=5)

    in_flight = repository.get_vector_state("memory_items", item.id)
    assert in_flight.state == "stale"
    assert repository.count_ready_vectors("memory_items", item.id) == 0

    release_embedding.set()
    update_thread.join(timeout=5)
    failed = repository.get_vector_state("memory_items", item.id)
    assert failed.state == "failed"
    assert repository.count_ready_vectors("memory_items", item.id) == 0



def test_late_vector_work_cannot_publish_after_new_hash_is_prepared(tmp_path, monkeypatch) -> None:
    repository = SQLiteStore(tmp_path / "vector-cas.sqlite3")
    item = _memory("mem_interleaved", "old vector content")
    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", False)
    repository.add_memory_item(item)
    with repository._connect() as connection:
        old_work = repository.vector_index.prepare(
            connection,
            "memory_items",
            item.id,
            f"{item.title} {item.summary}",
        )
    assert old_work is not None

    item.title = "new vector content"
    item.summary = "new vector content"
    repository.save_memory_item(item)
    current = repository.get_vector_state("memory_items", item.id)
    assert current is not None
    assert current.content_hash != old_work.content_hash

    monkeypatch.setattr("agentmesh.embedding.embed_text", lambda text: [1.0, 0.0])
    repository.vector_index.process(old_work)

    assert repository.count_ready_vectors("memory_items", item.id) == 0
    assert repository.get_vector_state("memory_items", item.id).content_hash == current.content_hash


def test_vector_search_ignores_vector_rows_without_ready_state(tmp_path, monkeypatch) -> None:
    repository = SQLiteStore(tmp_path / "vector-ready-search.sqlite3")
    item = _memory("mem_not_ready", "lexically unrelated")
    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", False)
    repository.add_memory_item(item)
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            "INSERT INTO records_vec(collection, record_id, embedding) VALUES (?, ?, ?)",
            ("memory_items", item.id, b"[1.0, 0.0]"),
        )

    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", True)
    monkeypatch.setattr("agentmesh.embedding.embed_text", lambda text: [1.0, 0.0])
    with repository._connect() as connection:
        vector_rows = repository._vec_search(
            connection,
            "semantic-only-query",
            [Scope.TEAM_ACCEPTED.value],
            "?",
        )

    assert vector_rows == []
