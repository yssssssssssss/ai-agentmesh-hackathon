"""Persisted vector lifecycle management for searchable records.

Record/FTS changes call :meth:`prepare` inside their short SQLite transaction.
Provider work is performed later by :meth:`process`, after that transaction has
committed.  The content hash is a compare-and-set token which prevents a late
provider response from attaching an old vector to newer text.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class VectorState(StrEnum):
    PENDING = "pending"
    READY = "ready"
    STALE = "stale"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class VectorWork:
    collection: str
    record_id: str
    text: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class VectorStatus:
    collection: str
    record_id: str
    state: VectorState
    content_hash: str
    error: str | None


class VectorIndex:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    @staticmethod
    def ensure_schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS vector_states (
                collection TEXT NOT NULL,
                record_id TEXT NOT NULL,
                state TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                error TEXT,
                PRIMARY KEY(collection, record_id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_vector_states_state ON vector_states(state)"
        )

    @staticmethod
    def _content_hash(text: str, *, index_signature: str | None = None) -> str:
        payload = text if index_signature is None else f"{index_signature}\0{text}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def prepare(
        connection: sqlite3.Connection,
        collection: str,
        record_id: str,
        text: str,
        *,
        index_signature: str | None = None,
    ) -> VectorWork | None:
        normalized = text.strip()
        if not normalized:
            connection.execute(
                "DELETE FROM records_vec WHERE collection = ? AND record_id = ?",
                (collection, record_id),
            )
            connection.execute(
                "DELETE FROM vector_states WHERE collection = ? AND record_id = ?",
                (collection, record_id),
            )
            return None

        content_hash = VectorIndex._content_hash(normalized, index_signature=index_signature)
        current = connection.execute(
            "SELECT state, content_hash FROM vector_states WHERE collection = ? AND record_id = ?",
            (collection, record_id),
        ).fetchone()
        ready_vector = connection.execute(
            "SELECT 1 FROM records_vec WHERE collection = ? AND record_id = ?",
            (collection, record_id),
        ).fetchone()
        if current is not None and current[0] == VectorState.READY and current[1] == content_hash and ready_vector:
            return None

        state = VectorState.STALE if current is not None or ready_vector else VectorState.PENDING
        connection.execute(
            "DELETE FROM records_vec WHERE collection = ? AND record_id = ?",
            (collection, record_id),
        )
        connection.execute(
            """
            INSERT INTO vector_states(collection, record_id, state, content_hash, error)
            VALUES (?, ?, ?, ?, NULL)
            ON CONFLICT(collection, record_id) DO UPDATE SET
                state = excluded.state,
                content_hash = excluded.content_hash,
                error = NULL
            """,
            (collection, record_id, state.value, content_hash),
        )
        return VectorWork(collection, record_id, normalized, content_hash)
    @staticmethod
    def adopt_ready(
        connection: sqlite3.Connection,
        collection: str,
        record_id: str,
        text: str,
        *,
        index_signature: str | None = None,
    ) -> None:
        normalized = text.strip()
        if not normalized:
            return
        content_hash = VectorIndex._content_hash(normalized, index_signature=index_signature)
        connection.execute(
            """
            INSERT OR IGNORE INTO vector_states(collection, record_id, state, content_hash, error)
            VALUES (?, ?, ?, ?, NULL)
            """,
            (collection, record_id, VectorState.READY.value, content_hash),
        )

    @staticmethod
    def mark_stale(connection: sqlite3.Connection, collection: str, record_id: str) -> None:
        connection.execute(
            "DELETE FROM records_vec WHERE collection = ? AND record_id = ?",
            (collection, record_id),
        )
        connection.execute(
            """
            UPDATE vector_states SET state = ?, error = NULL
            WHERE collection = ? AND record_id = ?
            """,
            (VectorState.STALE.value, collection, record_id),
        )

    def process(self, work: VectorWork) -> None:
        from agentmesh.embedding import embed_text, serialize_embedding

        try:
            embedding = embed_text(work.text)
            serialized = serialize_embedding(embedding) if embedding is not None else None
        except Exception as error:
            self._finish_failed(work, str(error) or error.__class__.__name__)
            return
        if serialized is None:
            self._finish_failed(work, "embedding_unavailable")
            return

        with sqlite3.connect(self.db_path) as connection:
            adopted = connection.execute(
                """
                UPDATE vector_states SET state = ?, error = NULL
                WHERE collection = ? AND record_id = ? AND content_hash = ? AND state != ?
                """,
                (
                    VectorState.READY.value,
                    work.collection,
                    work.record_id,
                    work.content_hash,
                    VectorState.READY.value,
                ),
            )
            if adopted.rowcount != 1:
                return
            connection.execute(
                """
                INSERT INTO records_vec(collection, record_id, embedding)
                VALUES (?, ?, ?)
                ON CONFLICT(collection, record_id) DO UPDATE SET embedding = excluded.embedding
                """,
                (work.collection, work.record_id, serialized),
            )

    def _finish_failed(self, work: VectorWork, error: str) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                UPDATE vector_states SET state = ?, error = ?
                WHERE collection = ? AND record_id = ? AND content_hash = ? AND state != ?
                """,
                (
                    VectorState.FAILED.value,
                    error[:500],
                    work.collection,
                    work.record_id,
                    work.content_hash,
                    VectorState.READY.value,
                ),
            )

    def status(self, collection: str, record_id: str) -> VectorStatus | None:
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT collection, record_id, state, content_hash, error
                FROM vector_states WHERE collection = ? AND record_id = ?
                """,
                (collection, record_id),
            ).fetchone()
        if row is None:
            return None
        return VectorStatus(
            collection=row[0],
            record_id=row[1],
            state=VectorState(row[2]),
            content_hash=row[3],
            error=row[4],
        )

    def count_ready(self, collection: str, record_id: str) -> int:
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*)
                FROM records_vec rv
                JOIN vector_states vs
                  ON vs.collection = rv.collection AND vs.record_id = rv.record_id
                WHERE rv.collection = ? AND rv.record_id = ? AND vs.state = ?
                """,
                (collection, record_id, VectorState.READY.value),
            ).fetchone()
        return int(row[0])
