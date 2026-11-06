from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta

from agentmesh.automation.changes import change_window, changed_definition_ids
from agentmesh.automation.contracts import ScheduledOccurrenceV1, ScheduledRunNowRequestV1, ScheduleDuePreviewV1
from agentmesh.automation.schedule_repository import ScheduleDefinitionError, ScheduleRepository
from agentmesh.automation.settings import automation_mode
from agentmesh.automation.time_policy import CronSchedule
from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.models import (
    AgentRun,
    AgentRunStatus,
    ChatThread,
    ChatThreadKind,
    RunDispatchReceiptV1,
    ScheduledAgentTaskDefinition,
    ScheduledInspectionUsageV1,
    User,
)


class OccurrenceRepository(ScheduleRepository):
    """A time slot and its dispatch are one aggregate transaction, never two queues."""

    def due_definitions(self, at: datetime, *, limit: int = 50) -> list[ScheduledAgentTaskDefinition]:
        with closing(self.store._connect()) as connection:
            rows = connection.execute(
                """
                SELECT payload FROM records WHERE collection = 'scheduled_agent_task_definitions'
                    AND json_extract(payload, '$.schema_version') = 'project-inspection-schedule-v1'
                    AND json_extract(payload, '$.enabled') = 1
                    AND julianday(json_extract(payload, '$.next_run_at')) <= julianday(?)
                ORDER BY julianday(json_extract(payload, '$.next_run_at')), id LIMIT ?
            """,
                (at.isoformat(), limit),
            ).fetchall()
        return [ScheduledAgentTaskDefinition.model_validate_json(row["payload"]) for row in rows]

    def preview_reason(self, definition, at: datetime, *, runtime_available: bool) -> str | None:
        with closing(self.store._read_connect()) as connection, connection:
            connection.execute("BEGIN")
            _, reason = self._admission_policy(connection, definition, at, runtime_available=runtime_available)
        return reason

    def change_previews(
        self, at: datetime, *, runtime_available: bool, limit: int,
    ) -> tuple[list[ScheduleDuePreviewV1], bool]:
        previews = []
        with closing(self.store._read_connect()) as connection, connection:
            connection.execute("BEGIN")
            ids = changed_definition_ids(connection, limit=limit + 1)
            for schedule_id in ids[:limit]:
                row = self._record(connection, "scheduled_agent_task_definitions", schedule_id)
                definition = ScheduledAgentTaskDefinition.model_validate_json(row["payload"])
                window = change_window(connection, definition)
                if window is None or window.ready_at > at:
                    continue
                _, reason = self._admission_policy(connection, definition, at, runtime_available=runtime_available)
                previews.append(ScheduleDuePreviewV1(
                    schedule_id=definition.id, definition_version=definition.version,
                    scheduled_at=window.ready_at, local_slot=None, trigger="change",
                    source_cursor=window.source_cursor, budget=definition.budget, blocked_reason=reason,
                ))
        return previews, len(ids) > limit

    def _admission_policy(self, connection, definition, at, *, runtime_available, is_manual=False):
        try:
            self._authorize(connection, definition.owner_user_id or "", definition.model_copy(update={"enabled": True}))
            if not runtime_available:
                raise ScheduleDefinitionError("automation_runtime_unavailable")
        except ScheduleDefinitionError as error:
            return "blocked", error.code
        active = connection.execute(
            """SELECT 1 FROM records AS occurrence JOIN agent_runs AS run
                ON run.id = json_extract(occurrence.payload, '$.run_id')
            WHERE occurrence.collection = 'scheduled_occurrences'
                AND json_extract(occurrence.payload, '$.schedule_id') = ?
                AND json_extract(run.payload, '$.status') IN
                    ('created','planning','running','waiting_input','waiting_clarification',
                     'waiting_approval','waiting_plan_approval') LIMIT 1""", (definition.id,),
        ).fetchone()
        if active is not None:
            return "skipped", "schedule_overlap"
        if not is_manual and definition.last_run_at is not None and at - definition.last_run_at < timedelta(minutes=5):
            return "skipped", "schedule_utc_frequency_limit"
        return "admitted", None

    def admit(
        self,
        schedule_id: str,
        at: datetime,
        *,
        runtime_available: bool,
        actor: User | None = None,
        manual: ScheduledRunNowRequestV1 | None = None,
        change: bool = False,
    ) -> ScheduledOccurrenceV1 | None:
        if manual is not None and change:
            raise ScheduleDefinitionError("automation_trigger_invalid", status_code=422)
        with closing(self.store._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            if automation_mode() != "execute":
                if manual is not None:
                    raise ScheduleDefinitionError("automation_execution_disabled")
                return None
            row = self._record(connection, "scheduled_agent_task_definitions", schedule_id)
            definition = ScheduledAgentTaskDefinition.model_validate_json(row["payload"]) if row else None
            if definition is None:
                raise ScheduleDefinitionError("schedule_not_found", status_code=404)
            if definition.schema_version is None or definition.validation_state != "valid":
                if manual is not None:
                    raise ScheduleDefinitionError("legacy_schedule_unvalidated")
                return None
            cron = CronSchedule(definition.schedule, definition.timezone)
            window = change_window(connection, definition)
            if change:
                if not definition.enabled or window is None or window.ready_at > at:
                    return None
                slot = None
                trigger_key = str(window.source_cursor)
                command_hash = None
            elif manual is None:
                if not definition.enabled or definition.next_run_at is None or definition.next_run_at > at:
                    return None
                slot = cron.latest_slot(at)
                trigger_key = slot.local_slot
                command_hash = None
            else:
                if actor is None or actor.workspace_id != definition.workspace_id:
                    raise ScheduleDefinitionError("schedule_not_found", status_code=404)
                self._authorize(connection, actor.id, definition.model_copy(update={"enabled": True}))
                slot = None
                trigger_key = canonical_json_sha256([actor.id, manual.command_id])
                command_hash = canonical_json_sha256([schedule_id, manual.model_dump(mode="json")])
            trigger = "change" if change else "manual" if manual else "scheduled"
            # Uniqueness crosses definition versions: editing a title during a
            # DST fold must never permit another execution of the same wall slot.
            occurrence_id = "occurrence_" + canonical_json_sha256([schedule_id, trigger, trigger_key])
            row = self._record(connection, "scheduled_occurrences", occurrence_id)
            if row is not None:
                existing = ScheduledOccurrenceV1.model_validate_json(row["payload"])
                if existing.command_hash != command_hash:
                    raise ScheduleDefinitionError("schedule_command_conflict")
                if manual is None and not change:
                    definition.next_run_at = cron.next_slot(at).scheduled_at
                    connection.execute(
                        "UPDATE records SET payload = ? WHERE collection = 'scheduled_agent_task_definitions' AND id = ?",
                        (definition.model_dump_json(), schedule_id),
                    )
                return existing if manual else None
            if manual is not None and definition.version != manual.expected_version:
                raise ScheduleDefinitionError("schedule_version_conflict")
            admission, reason = self._admission_policy(
                connection, definition, at, runtime_available=runtime_available, is_manual=manual is not None,
            )
            run_id = "run_" + canonical_json_sha256(occurrence_id)[:32] if admission == "admitted" else None
            occurrence = ScheduledOccurrenceV1(
                id=occurrence_id,
                schedule_id=schedule_id,
                definition_version=definition.version,
                trigger=trigger,
                trigger_key=trigger_key,
                scheduled_at=window.ready_at if change else slot.scheduled_at if slot else at,
                local_slot=slot.local_slot if slot else None,
                source_cursor=window.source_cursor if window else None,
                workspace_id=definition.workspace_id,
                project_id=definition.project_id,
                owner_user_id=definition.owner_user_id,
                template_id=definition.template_id,
                budget=definition.budget,
                run_id=run_id,
                admission=admission,
                reason=reason,
                manual_actor_id=actor.id if manual else None,
                command_hash=command_hash,
                created_at=at,
            )
            connection.execute(
                "INSERT INTO records(collection, id, payload) VALUES ('scheduled_occurrences', ?, ?)",
                (occurrence.id, occurrence.model_dump_json()),
            )
            if run_id is not None:
                thread = ChatThread(
                    id="thread_automation_" + canonical_json_sha256(schedule_id)[:32],
                    workspace_id=occurrence.workspace_id,
                    project_id=occurrence.project_id,
                    user_id=occurrence.owner_user_id,
                    title="项目巡检记录",
                    kind=ChatThreadKind.AUTOMATION,
                    created_at=at,
                    updated_at=at,
                )
                connection.execute(
                    "INSERT OR IGNORE INTO records(collection, id, payload) VALUES ('chat_threads', ?, ?)",
                    (thread.id, thread.model_dump_json()),
                )
                run = AgentRun(
                    id=run_id,
                    thread_id=thread.id,
                    user_id=occurrence.owner_user_id,
                    workspace_id=occurrence.workspace_id,
                    project_id=occurrence.project_id,
                    input_text=f"Project inspection: {occurrence.template_id}",
                    status=AgentRunStatus.CREATED,
                    inspection_usage=ScheduledInspectionUsageV1(),
                    execution_location="server",
                    orchestration_version="v1",
                    orchestration_mode="execute",
                    skill_name=occurrence.template_id,
                    deadline_at=at + timedelta(seconds=occurrence.budget.deadline_seconds),
                    created_at=at,
                    updated_at=at,
                )
                self.store._require_agent_run_thread_available(connection, run)
                self.store._insert_agent_run_claim(connection, run)
                dispatch = RunDispatchReceiptV1(
                    operation_key="dispatch:"
                    + canonical_json_sha256(
                        {
                            "run_id": run_id,
                            "operation_kind": "project_inspection",
                            "generation": 1,
                        }
                    ),
                    run_id=run_id,
                    operation_kind="project_inspection",
                    payload={"occurrence_id": occurrence.id},
                    created_at=at,
                    updated_at=at,
                )
                self.store._insert_run_dispatch_in_transaction(connection, dispatch)
                definition.last_run_at = at
            if window is not None:
                definition.change_cursor = window.source_cursor
            if manual is None and not change:
                definition.next_run_at = cron.next_slot(at).scheduled_at
            definition.blocked_reason = reason if admission == "blocked" else None
            connection.execute(
                "UPDATE records SET payload = ? WHERE collection = 'scheduled_agent_task_definitions' AND id = ?",
                (definition.model_dump_json(), schedule_id),
            )
        return occurrence
