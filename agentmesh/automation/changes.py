from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from agentmesh.models import ScheduledAgentTaskDefinition

# Read only durable command receipts and the existing current visibility projection.
# In-progress writes, private chat and raw Task edits do not create an event stream.
_EVENTS = """
    FROM records AS receipt
    JOIN task_operations_projection AS task
      ON task.task_id = json_extract(receipt.payload, '$.result_task.id')
     AND task.thread_id = json_extract(receipt.payload, '$.result_task.thread_id')
    WHERE receipt.collection IN ('task_command_receipts', 'task_review_command_receipts')
      AND ((receipt.collection = 'task_command_receipts'
            AND json_extract(receipt.payload, '$.schema_version') = 'task-command-receipt-v1')
        OR (receipt.collection = 'task_review_command_receipts'
            AND json_extract(receipt.payload, '$.schema_version') = 'task-review-command-receipt-v1'))
      AND json_extract(receipt.payload, '$.result_task.management.version') >= 1
      AND receipt.created_order > {cursor}
      AND task.workspace_id = {workspace} AND task.project_id = {project} AND task.thread_kind = 'task'
"""


@dataclass(frozen=True)
class ProjectChangeWindow:
    source_cursor: int
    ready_at: datetime


def change_window(
    connection: sqlite3.Connection, definition: ScheduledAgentTaskDefinition,
) -> ProjectChangeWindow | None:
    if not definition.on_project_changes or definition.change_cursor is None:
        return None
    params = (definition.change_cursor, definition.workspace_id, definition.project_id)
    query = "SELECT receipt.created_order, json_extract(receipt.payload, '$.created_at') AS occurred_at " + _EVENTS.format(
        cursor="?", workspace="?", project="?",
    )
    first = connection.execute(query + " ORDER BY receipt.created_order LIMIT 1", params).fetchone()
    if first is None:
        return None
    latest = connection.execute(query + " ORDER BY receipt.created_order DESC LIMIT 1", params).fetchone()
    first_at, latest_at = (datetime.fromisoformat(row["occurred_at"]) for row in (first, latest))
    if first_at.utcoffset() is None or latest_at.utcoffset() is None:
        raise ValueError("project change timestamps require a timezone")
    # Quiet bursts for 30 seconds; sustained edits cannot defer a report beyond
    # five minutes. The existing five-minute automatic-run floor still applies.
    ready_at = min(latest_at + timedelta(seconds=30), first_at + timedelta(minutes=5))
    if definition.last_run_at is not None:
        ready_at = max(ready_at, definition.last_run_at + timedelta(minutes=5))
    return ProjectChangeWindow(source_cursor=latest["created_order"], ready_at=ready_at)


def changed_definition_ids(connection: sqlite3.Connection, *, limit: int) -> list[str]:
    rows = connection.execute(
        """SELECT definition.id FROM records AS definition
        WHERE definition.collection = 'scheduled_agent_task_definitions'
          AND json_extract(definition.payload, '$.schema_version') = 'project-inspection-schedule-v1'
          AND json_extract(definition.payload, '$.enabled') = 1
          AND json_extract(definition.payload, '$.on_project_changes') = 1
          AND EXISTS (SELECT 1 """ + _EVENTS.format(
            cursor="json_extract(definition.payload, '$.change_cursor')",
            workspace="json_extract(definition.payload, '$.workspace_id')",
            project="json_extract(definition.payload, '$.project_id')",
          ) + ") ORDER BY json_extract(definition.payload, '$.change_cursor'), definition.id LIMIT ?", (limit,),
    ).fetchall()
    return [row["id"] for row in rows]
