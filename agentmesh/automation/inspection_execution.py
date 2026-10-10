from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from collections.abc import Awaitable, Callable
from contextlib import closing
from datetime import datetime, timedelta

from agentmesh.automation.contracts import ProjectInspectionReportV1, ProjectInspectionRequestV1, ScheduledOccurrenceV1
from agentmesh.automation.schedule_repository import ScheduleDefinitionError, ScheduleRepository
from agentmesh.automation.service import ProjectInspectionService
from agentmesh.automation.settings import automation_mode
from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.models import (
    AgentRun,
    AgentRunStatus,
    InboxItem,
    RunDispatchReceiptV1,
    RunDispatchState,
    RunOutputProjectionReceiptV1,
    ScheduledAgentTaskDefinition,
    Scope,
    now_utc,
)
from agentmesh.task_operations.service import TaskOperationsError


class InspectionReadTransientError(RuntimeError):
    def __init__(self, *, retry_after: float = 0):
        super().__init__("inspection_read_unavailable")
        self.retry_after = max(0, retry_after)


def inspection_result_hash(report: ProjectInspectionReportV1) -> str:
    return canonical_json_sha256(
        report.model_dump(
            mode="json",
            exclude={
                "snapshot_at",
                "since",
                "source_watermarks",
                "evidence_refs",
                "recommendations",
            },
        )
    )


class InspectionExecutionRepository(ScheduleRepository):
    def recover_stalled(self, process_epoch: str, active_run_ids: set[str], *, limit: int = 50) -> int:
        recovered = 0
        with closing(self.store._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT * FROM run_dispatch_receipts WHERE operation_kind = 'project_inspection'
                    AND state = 'started' AND process_epoch = ? ORDER BY created_at LIMIT ?
            """,
                (process_epoch, limit),
            ).fetchall()
            for row in rows:
                dispatch = self.store._decode_run_dispatch_row(row)
                if dispatch.run_id in active_run_ids:
                    continue
                pending = dispatch.model_copy(
                    update={"state": RunDispatchState.PENDING, "process_epoch": None, "updated_at": now_utc()}
                )
                connection.execute(
                    """UPDATE run_dispatch_receipts SET state = ?, process_epoch = NULL,
                    payload = ?, updated_at = ? WHERE operation_key = ? AND process_epoch = ?""",
                    (
                        pending.state.value,
                        pending.model_dump_json(),
                        pending.updated_at.isoformat(),
                        pending.operation_key,
                        process_epoch,
                    ),
                )
                self.store._append_agent_run_events(
                    connection,
                    dispatch.run_id,
                    [
                        (
                            "inspection_dispatch_recovered",
                            {
                                "error_code": "inspection_result_commit_interrupted",
                                "attempt": dispatch.attempt_count,
                            },
                        )
                    ],
                )
                recovered += 1
        return recovered

    def _execution(self, connection, receipt: RunDispatchReceiptV1):
        row = connection.execute(
            "SELECT * FROM run_dispatch_receipts WHERE operation_key = ?", (receipt.operation_key,)
        ).fetchone()
        if row is None:
            return None
        current = self.store._decode_run_dispatch_row(row)
        if current.state != RunDispatchState.STARTED or current.process_epoch != receipt.process_epoch:
            return None
        row = self._record(connection, "scheduled_occurrences", current.payload.get("occurrence_id", ""))
        occurrence = ScheduledOccurrenceV1.model_validate_json(row["payload"]) if row else None
        row = connection.execute("SELECT payload FROM agent_runs WHERE id = ?", (current.run_id,)).fetchone()
        run = AgentRun.model_validate_json(row["payload"]) if row else None
        if (
            occurrence is None
            or run is None
            or occurrence.run_id != run.id
            or run.inspection_usage is None
            or (run.user_id, run.workspace_id, run.project_id)
            != (occurrence.owner_user_id, occurrence.workspace_id, occurrence.project_id)
        ):
            raise ScheduleDefinitionError("inspection_execution_identity_invalid")
        row = self._record(connection, "scheduled_agent_task_definitions", occurrence.schedule_id)
        definition = ScheduledAgentTaskDefinition.model_validate_json(row["payload"]) if row else None
        if definition is None or (definition.owner_user_id, definition.workspace_id, definition.project_id) != (
            occurrence.owner_user_id,
            occurrence.workspace_id,
            occurrence.project_id,
        ):
            raise ScheduleDefinitionError("inspection_execution_identity_invalid")
        return current, run, occurrence, definition

    def start_attempt(self, receipt: RunDispatchReceiptV1, at: datetime):
        with closing(self.store._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            state = self._execution(connection, receipt)
            if state is None:
                return None
            _, run, occurrence, definition = state
            if run.status in {
                AgentRunStatus.COMPLETED,
                AgentRunStatus.PARTIAL,
                AgentRunStatus.FAILED,
                AgentRunStatus.CANCELLED,
                AgentRunStatus.REJECTED,
            }:
                return None
            if automation_mode() != "execute":
                raise ScheduleDefinitionError("automation_execution_disabled")
            self._authorize(connection, run.user_id, definition.model_copy(update={"enabled": True}))
            if run.deadline_at is None or at >= run.deadline_at:
                raise ScheduleDefinitionError("inspection_deadline_exceeded")
            if run.inspection_usage.attempt_count >= 3:
                raise ScheduleDefinitionError("inspection_read_retry_exhausted")
            if run.tool_call_count >= occurrence.budget.max_tool_calls:
                raise ScheduleDefinitionError("inspection_tool_budget_exceeded")
            if run.inspection_usage.next_retry_at is not None and at < run.inspection_usage.next_retry_at:
                raise ScheduleDefinitionError("inspection_retry_not_due")
            run.inspection_usage.attempt_count += 1
            run.inspection_usage.next_retry_at = None
            run.tool_call_count += 1
            run.status = AgentRunStatus.RUNNING
            run.updated_at = at
            connection.execute(
                "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                (run.model_dump_json(), at.isoformat(), run.id),
            )
            self.store._append_agent_run_events(
                connection,
                run.id,
                [
                    (
                        "inspection_read_started",
                        {
                            "occurrence_id": occurrence.id,
                            "attempt": run.inspection_usage.attempt_count,
                            "provider": "local_task_store",
                            "tool_call_count": run.tool_call_count,
                        },
                    )
                ],
            )
            return run, occurrence, definition.last_success_at

    def retry(self, receipt: RunDispatchReceiptV1, at: datetime, delay: float) -> bool:
        with closing(self.store._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            state = self._execution(connection, receipt)
            if state is None:
                return False
            _, run, _, _ = state
            if run.status != AgentRunStatus.RUNNING:
                return False
            run.inspection_usage.last_error_code = "inspection_read_unavailable"
            run.inspection_usage.next_retry_at = at + timedelta(seconds=delay)
            run.updated_at = at
            connection.execute(
                "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                (run.model_dump_json(), at.isoformat(), run.id),
            )
            self.store._append_agent_run_events(
                connection,
                run.id,
                [
                    (
                        "inspection_read_retry",
                        {
                            "attempt": run.inspection_usage.attempt_count,
                            "error_code": "inspection_read_unavailable",
                            "next_retry_at": run.inspection_usage.next_retry_at.isoformat(),
                        },
                    )
                ],
            )
        return True

    def finish(
        self,
        receipt: RunDispatchReceiptV1,
        at: datetime,
        *,
        report: ProjectInspectionReportV1 | None = None,
        error_code: str | None = None,
    ) -> AgentRun | None:
        with closing(self.store._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            state = self._execution(connection, receipt)
            if state is None:
                return None
            dispatch, run, occurrence, definition = state
            terminal = run.status in {
                AgentRunStatus.COMPLETED,
                AgentRunStatus.PARTIAL,
                AgentRunStatus.FAILED,
                AgentRunStatus.CANCELLED,
                AgentRunStatus.REJECTED,
            }
            if terminal:
                report = None
            elif report is not None:
                try:
                    self._authorize(connection, run.user_id, definition.model_copy(update={"enabled": True}))
                    if run.deadline_at is None or at >= run.deadline_at:
                        raise ScheduleDefinitionError("inspection_deadline_exceeded")
                    if automation_mode() != "execute":
                        raise ScheduleDefinitionError("automation_execution_disabled")
                except ScheduleDefinitionError as error:
                    report, error_code = None, error.code
            if not terminal:
                run.status = AgentRunStatus.COMPLETED if report is not None else AgentRunStatus.FAILED
                run.error_code = error_code
                run.output_text = report.model_dump_json() if report else None
            run.inspection_usage.next_retry_at = None
            run.inspection_usage.last_error_code = error_code
            run.updated_at = at
            if report is not None:
                result_hash = inspection_result_hash(report)
                if definition.last_result_hash != result_hash:
                    self._notify_report(connection, run, occurrence, definition, report, result_hash, at)
                if report.template_id == definition.template_id:
                    definition.last_result_hash = result_hash
                    definition.last_result_run_id = run.id
                    if report.outcome != "insufficient_evidence":
                        definition.last_success_at = report.snapshot_at
                definition.last_error_code = None
                definition.blocked_reason = None
            elif run.status == AgentRunStatus.FAILED:
                definition.last_failure_at = at
                definition.last_error_code = error_code
            connection.execute(
                "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                (run.model_dump_json(), at.isoformat(), run.id),
            )
            connection.execute(
                "UPDATE records SET payload = ? WHERE collection = 'scheduled_agent_task_definitions' AND id = ?",
                (definition.model_dump_json(), definition.id),
            )
            projection = RunOutputProjectionReceiptV1(
                id="run_output_projection_" + hashlib.sha256(run.id.encode()).hexdigest()[:24],
                run_id=run.id,
                run_origin="internal",
                terminal_status=run.status,
                disposition="status_only",
                memory_disposition="not_applicable",
                skipped_reason="structured_inspection_report",
                output_hash=hashlib.sha256((run.output_text or run.status.value).encode()).hexdigest(),
                created_at=at,
            )
            connection.execute(
                "INSERT OR IGNORE INTO records(collection, id, payload) VALUES ('run_output_projection_receipts', ?, ?)",
                (projection.id, projection.model_dump_json()),
            )
            settled = dispatch.model_copy(update={"state": RunDispatchState.SETTLED, "updated_at": at})
            connection.execute(
                "UPDATE run_dispatch_receipts SET state = ?, payload = ?, updated_at = ? WHERE operation_key = ?",
                (settled.state.value, settled.model_dump_json(), at.isoformat(), dispatch.operation_key),
            )
            self.store._append_agent_run_events(
                connection,
                run.id,
                [
                    (
                        "inspection_finished",
                        {
                            "occurrence_id": occurrence.id,
                            "status": run.status.value,
                            "error_code": run.error_code,
                            "outcome": report.outcome if report else "failed",
                            "attempt": run.inspection_usage.attempt_count,
                            "tool_call_count": run.tool_call_count,
                            "model_turns": run.inspection_usage.model_turns,
                            "total_tokens": run.inspection_usage.total_tokens,
                        },
                    ),
                    (
                        "run_dispatch_settled",
                        {"operation_key": dispatch.operation_key, "operation_kind": dispatch.operation_kind},
                    ),
                ],
            )
        return run

    @staticmethod
    def _notify_report(connection, run, occurrence, definition, report, result_hash, at) -> None:
        risks = {
            canonical_json_sha256(["task", item.task_id, reason]) for item in report.blockers for reason in item.reasons
        }
        risks.update(canonical_json_sha256(["review", item.kind, item.review_id]) for item in report.pending_reviews)
        risks.update(canonical_json_sha256(["missing", code]) for code in report.missing_data)
        rows = connection.execute(
            """
            SELECT DISTINCT fingerprint.value FROM records AS inbox,
                json_each(json_extract(inbox.payload, '$.metadata.risk_fingerprints')) AS fingerprint
            WHERE inbox.collection = 'inbox_items' AND json_extract(inbox.payload, '$.item_type') = 'project_inspection'
                AND json_extract(inbox.payload, '$.user_id') = ? AND json_extract(inbox.payload, '$.project_id') = ?
                AND julianday(json_extract(inbox.payload, '$.created_at')) > julianday(?)
        """,
            (run.user_id, run.project_id, (at - timedelta(hours=24)).isoformat()),
        ).fetchall()
        fresh_risks = risks - {row["value"] for row in rows}
        if not report.changes and not fresh_risks:
            return
        inbox = InboxItem(
            id="inbox_inspection_" + canonical_json_sha256(run.id)[:32],
            title=f"项目巡检：{definition.title}",
            summary=f"发现 {len(report.changes)} 项进展变化、{len(fresh_risks)} 项新提醒，请查看巡检证据后确认行动。",
            item_type="project_inspection",
            scope=Scope.PRIVATE,
            user_id=run.user_id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            metadata={
                "schedule_id": definition.id,
                "occurrence_id": occurrence.id,
                "run_id": run.id,
                "result_hash": result_hash,
                "risk_fingerprints": json.dumps(sorted(fresh_risks)),
                "navigation_href": f"/tasks?inspection={run.id}",
            },
            created_at=at,
            updated_at=at,
        )
        connection.execute(
            "INSERT INTO records(collection, id, payload) VALUES ('inbox_items', ?, ?)",
            (inbox.id, inbox.model_dump_json()),
        )


class InspectionDispatchExecutor:
    def __init__(
        self,
        repository,
        *,
        clock: Callable[[], datetime] = now_utc,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.store = repository
        self.repository = InspectionExecutionRepository(repository)
        self.clock = clock
        self.sleep = sleep

    async def execute(self, receipt: RunDispatchReceiptV1) -> None:
        while True:
            run = self.store.get_agent_run(receipt.run_id)
            if run is None:
                return
            retry_at = run.inspection_usage.next_retry_at if run.inspection_usage else None
            if retry_at is not None and retry_at > self.clock():
                await self.sleep(
                    min(
                        (retry_at - self.clock()).total_seconds(),
                        max(0, (run.deadline_at - self.clock()).total_seconds()),
                    )
                )
            try:
                attempt = self.repository.start_attempt(receipt, self.clock())
                if attempt is None:
                    self.repository.finish(receipt, self.clock(), error_code=run.error_code)
                    return
                run, occurrence, last_success_at = attempt
                user = self.store.get_user(run.user_id)
                truncated_history = last_success_at is not None and self.clock() - last_success_at > timedelta(days=366)
                if truncated_history:
                    last_success_at = self.clock() - timedelta(days=366) + timedelta(seconds=1)
                request = ProjectInspectionRequestV1(template_id=occurrence.template_id, since=last_success_at)
                report = await asyncio.to_thread(
                    ProjectInspectionService(self.store, clock=self.clock).inspect,
                    run.project_id,
                    request,
                    user,
                )
                if truncated_history:
                    report.missing_data.append("inspection_history_window_truncated")
                    report.outcome = "insufficient_evidence"
            except (InspectionReadTransientError, sqlite3.OperationalError) as error:
                transient = isinstance(error, InspectionReadTransientError) or getattr(
                    error, "sqlite_errorcode", None
                ) in {
                    sqlite3.SQLITE_BUSY,
                    sqlite3.SQLITE_LOCKED,
                }
                run = self.store.get_agent_run(receipt.run_id)
                if transient and run.inspection_usage.attempt_count < 3:
                    delay = max(
                        (5, 30)[max(0, run.inspection_usage.attempt_count - 1)], getattr(error, "retry_after", 0)
                    )
                    if self.repository.retry(receipt, self.clock(), delay):
                        continue
                self.repository.finish(
                    receipt,
                    self.clock(),
                    error_code=("inspection_read_retry_exhausted" if transient else "inspection_execution_failed"),
                )
                return
            except (ScheduleDefinitionError, TaskOperationsError) as error:
                self.repository.finish(receipt, self.clock(), error_code=error.code)
                return
            except Exception:
                self.repository.finish(receipt, self.clock(), error_code="inspection_execution_failed")
                return
            self.repository.finish(receipt, self.clock(), report=report)
            return
