from __future__ import annotations

from contextlib import closing

from agentmesh.automation.contracts import (
    ProjectInspectionReportV1,
    ScheduledOccurrenceV1,
    ScheduledRunPageV1,
    ScheduledRunSummaryV1,
)
from agentmesh.automation.schedule_repository import ScheduleDefinitionError, ScheduleRepository
from agentmesh.models import AgentRun, ScheduledAgentTaskDefinition, User


class InspectionRunQuery(ScheduleRepository):
    def _visible_definition(self, connection, schedule_id: str, user: User) -> ScheduledAgentTaskDefinition:
        row = self._record(connection, "scheduled_agent_task_definitions", schedule_id)
        definition = ScheduledAgentTaskDefinition.model_validate_json(row["payload"]) if row else None
        if definition is None or definition.workspace_id != user.workspace_id:
            raise ScheduleDefinitionError("schedule_not_found", status_code=404)
        self._authorize(connection, user.id, definition.model_copy(update={"enabled": False}))
        return definition

    def list_runs(self, schedule_id: str, user: User, *, page: int = 1, page_size: int = 20) -> ScheduledRunPageV1:
        if page < 1 or not 1 <= page_size <= 100:
            raise ScheduleDefinitionError("schedule_page_invalid", status_code=422)
        with closing(self.store._connect()) as connection, connection:
            connection.execute("BEGIN")
            self._visible_definition(connection, schedule_id, user)
            query = """FROM records WHERE collection = 'scheduled_occurrences'
                       AND json_extract(payload, '$.schedule_id') = ?"""
            total = connection.execute("SELECT COUNT(*) " + query, (schedule_id,)).fetchone()[0]
            rows = connection.execute(
                "SELECT payload " + query + " ORDER BY created_order DESC LIMIT ? OFFSET ?",
                (schedule_id, page_size, (page - 1) * page_size),
            ).fetchall()
            items = []
            for row in rows:
                occurrence = ScheduledOccurrenceV1.model_validate_json(row["payload"])
                row = connection.execute("SELECT payload FROM agent_runs WHERE id = ?", (occurrence.run_id,)).fetchone()
                run = AgentRun.model_validate_json(row["payload"]) if row else None
                items.append(
                    ScheduledRunSummaryV1(
                        occurrence=occurrence,
                        status=run.status if run else None,
                        error_code=run.error_code if run else None,
                        tool_call_count=run.tool_call_count if run else 0,
                        usage=run.inspection_usage if run else None,
                    )
                )
        return ScheduledRunPageV1(items=items, total_count=total, page=page, page_size=page_size)

    def report(self, run_id: str, user: User) -> ProjectInspectionReportV1:
        with closing(self.store._connect()) as connection, connection:
            connection.execute("BEGIN")
            row = connection.execute("SELECT payload FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
            run = AgentRun.model_validate_json(row["payload"]) if row else None
            if (
                run is None
                or run.user_id != user.id
                or run.workspace_id != user.workspace_id
                or run.inspection_usage is None
            ):
                raise ScheduleDefinitionError("inspection_report_not_found", status_code=404)
            row = connection.execute(
                """SELECT payload FROM records WHERE collection = 'scheduled_occurrences'
                AND json_extract(payload, '$.run_id') = ? LIMIT 1""",
                (run_id,),
            ).fetchone()
            if row is None:
                raise ScheduleDefinitionError("inspection_report_not_found", status_code=404)
            occurrence = ScheduledOccurrenceV1.model_validate_json(row["payload"])
            self._visible_definition(connection, occurrence.schedule_id, user)
            if run.output_text is None:
                raise ScheduleDefinitionError("inspection_report_not_ready")
            return ProjectInspectionReportV1.model_validate_json(run.output_text)
