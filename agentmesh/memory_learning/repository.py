from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

from agentmesh.memory_learning.contracts import MemoryLearningJobV1

if TYPE_CHECKING:
    from agentmesh.store import SQLiteStore


def ensure_learning_schema(connection: sqlite3.Connection) -> None:
    connection.execute('''CREATE INDEX IF NOT EXISTS idx_memory_learning_due
        ON records(json_extract(payload, '$.status'), json_extract(payload, '$.next_attempt_at'), created_order)
        WHERE collection = 'memory_learning_jobs' ''')
    connection.execute('''CREATE INDEX IF NOT EXISTS idx_memory_learning_owner
        ON records(json_extract(payload, '$.user_id'), created_order DESC)
        WHERE collection = 'memory_learning_jobs' ''')
    connection.execute('''CREATE INDEX IF NOT EXISTS idx_memory_learning_source
        ON records(json_extract(payload, '$.source_document_id'), json_extract(payload, '$.source_version'),
                   json_extract(payload, '$.extraction_schema_version'))
        WHERE collection = 'memory_learning_jobs' ''')


class MemoryLearningRepository:
    def __init__(self, store: SQLiteStore):
        self.store = store

    def job(self, job_id: str) -> MemoryLearningJobV1 | None:
        with closing(self.store._read_connect()) as connection:
            return self.from_connection(connection, job_id)

    @staticmethod
    def from_connection(connection: sqlite3.Connection, job_id: str) -> MemoryLearningJobV1 | None:
        row = connection.execute("SELECT payload FROM records WHERE collection = 'memory_learning_jobs' AND id = ?",
                                 (job_id,)).fetchone()
        if row is None:
            return None
        job = MemoryLearningJobV1.model_validate_json(row['payload'])
        if job.id != job_id:
            raise ValueError('memory_learning_job_integrity_failed')
        return job

    @staticmethod
    def save(connection: sqlite3.Connection, job: MemoryLearningJobV1) -> None:
        connection.execute("INSERT INTO records(collection, id, payload) VALUES ('memory_learning_jobs', ?, ?) "
                           'ON CONFLICT(collection, id) DO UPDATE SET payload = excluded.payload',
                           (job.id, job.model_dump_json()))
