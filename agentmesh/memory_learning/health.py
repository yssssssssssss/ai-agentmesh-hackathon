"""Owner-only operational aggregates; no job/source bodies are loaded."""
from __future__ import annotations

import sqlite3
from datetime import datetime

from agentmesh.memory_learning.contracts import MemoryLearningQueueHealthV1
from agentmesh.models import User


def queue_health(connection: sqlite3.Connection, actor: User, now: datetime) -> MemoryLearningQueueHealthV1:
    row = connection.execute("""
      WITH visible AS (
        SELECT json_extract(j.payload, '$.status') AS status,
               julianday(json_extract(j.payload, '$.created_at')) AS created,
               julianday(json_extract(j.payload, '$.next_attempt_at')) AS next_attempt,
               julianday(json_extract(j.payload, '$.lease_expires_at')) AS lease_expires,
               COALESCE(json_extract(j.payload, '$.unreported_attempts'), 0) AS unreported
        FROM records j JOIN records p
          ON p.collection = 'projects' AND p.id = json_extract(j.payload, '$.project_id')
        WHERE j.collection = 'memory_learning_jobs'
          AND json_extract(j.payload, '$.user_id') = ? AND json_extract(j.payload, '$.workspace_id') = ?
          AND json_extract(p.payload, '$.workspace_id') = ?
          AND (COALESCE(json_array_length(p.payload, '$.member_ids'), 0) = 0
               OR EXISTS (SELECT 1 FROM json_each(p.payload, '$.member_ids') WHERE value = ?))
      ), clock AS (SELECT julianday(?) AS at)
      SELECT COUNT(*) FILTER (WHERE status = 'queued' OR (status = 'retry_wait' AND next_attempt <= at)) AS ready,
             COUNT(*) FILTER (WHERE status = 'running') AS running,
             COUNT(*) FILTER (WHERE status = 'retry_wait') AS retry_wait,
             COUNT(*) FILTER (WHERE status = 'running' AND (lease_expires IS NULL OR lease_expires <= at)) AS expired_leases,
             COUNT(*) FILTER (WHERE status = 'failed') AS failures,
             COUNT(*) FILTER (WHERE status = 'blocked') AS blocked,
             COALESCE(SUM(CASE WHEN status != 'running' OR lease_expires <= at OR lease_expires IS NULL
                              THEN unreported ELSE 0 END), 0) AS unreported_attempts,
             MIN(CASE WHEN status = 'queued' THEN created
                      WHEN status = 'retry_wait' AND next_attempt <= at THEN next_attempt END) AS oldest_ready
      FROM visible CROSS JOIN clock
    """, (actor.id, actor.workspace_id, actor.workspace_id, actor.id, now.isoformat())).fetchone()
    cleanup = connection.execute("""
      SELECT MIN(julianday(created_at)) FROM memory_tombstones
      WHERE owner_user_id = ? AND workspace_id = ? AND cleaned_at IS NULL
    """, (actor.id, actor.workspace_id)).fetchone()[0]
    instant = connection.execute('SELECT julianday(?)', (now.isoformat(),)).fetchone()[0]

    def age(at: float | None) -> int | None:
        return max(0, round((instant - at) * 86400)) if at is not None else None

    return MemoryLearningQueueHealthV1(**{key: row[key] for key in (
        'ready', 'running', 'retry_wait', 'expired_leases', 'failures', 'blocked', 'unreported_attempts',
    )}, oldest_ready_age_seconds=age(row['oldest_ready']), oldest_cleanup_age_seconds=age(cleanup))


def learning_alerts(queue: MemoryLearningQueueHealthV1, *, reserved_tokens: int, daily_cap: int) -> list[str]:
    alerts = []
    if queue.oldest_ready_age_seconds is not None and queue.oldest_ready_age_seconds >= 300:
        alerts.append('queue_delayed')
    if queue.expired_leases:
        alerts.append('lease_expired')
    if reserved_tokens >= daily_cap:
        alerts.append('budget_exhausted')
    if queue.oldest_cleanup_age_seconds is not None and queue.oldest_cleanup_age_seconds >= 60:
        alerts.append('cleanup_delayed')
    if queue.unreported_attempts:
        alerts.append('usage_unreported')
    return alerts
