from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from agentmesh.models import MemoryLayer, Scope, UserMemoryItem
from agentmesh.store import SQLiteStore


def test_schema_upgrade_archives_duplicate_active_daily_summaries(tmp_path: Path) -> None:
    database = tmp_path / "legacy-duplicates.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE records (
              collection TEXT NOT NULL,
              id TEXT NOT NULL,
              payload TEXT NOT NULL,
              created_order INTEGER PRIMARY KEY AUTOINCREMENT,
              UNIQUE(collection, id)
            )
            """
        )
        base = {
            "user_id": "user-1",
            "project_id": "project-1",
            "memory_date": "2026-08-24",
            "memory_type": "daily_summary",
            "status": "active",
        }
        for index in range(2):
            item = UserMemoryItem(
                id=f"summary-{index}",
                user_id=base["user_id"],
                layer=MemoryLayer.MID_TERM,
                title=f"Summary {index}",
                summary="Daily summary",
                source_kind="daily_summary",
                memory_type=base["memory_type"],
                memory_date=base["memory_date"],
                scope=Scope.PRIVATE,
                workspace_id="workspace-1",
                project_id=base["project_id"],
                status=base["status"],
            )
            payload = item.model_dump(mode="json")
            connection.execute(
                "INSERT INTO records(collection, id, payload) VALUES (?, ?, ?)",
                ("user_memory_items", payload["id"], json.dumps(payload)),
            )

    SQLiteStore(database)

    with sqlite3.connect(database) as connection:
        statuses = [
            row[0]
            for row in connection.execute(
                """
                SELECT json_extract(payload, '$.status')
                FROM records
                WHERE collection = 'user_memory_items'
                ORDER BY created_order
                """
            )
        ]
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(records)")}

    assert statuses == ["archived", "active"]
    assert "idx_user_daily_summary_unique" in indexes
