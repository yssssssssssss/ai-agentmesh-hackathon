from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Literal

from pydantic import BaseModel, ConfigDict

from agentmesh.automation.contracts import ScheduledAgentTaskPageV1
from agentmesh.models import (
    Agent,
    AgentRun,
    AuditEvent,
    PermissionPolicyRule,
    Project,
    RunDispatchState,
    ScheduledAgentTaskDefinition,
    User,
)
from agentmesh.permissions import ACTION_MANAGE_PROJECT_TASKS, ACTION_MANAGE_PUBLIC_AGENT, has_permission
from agentmesh.store import SQLiteStore


class ScheduleDefinitionError(RuntimeError):
    def __init__(self, code: str, *, status_code: int = 409):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class ScheduleCommandReceiptV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["schedule-command-v1"] = "schedule-command-v1"
    id: str
    actor_id: str
    operation: Literal["create", "update"]
    request_hash: str
    result: ScheduledAgentTaskDefinition


class ScheduleRepository:
    """Authorized definition commands; record layout and transaction stay private."""

    def __init__(self, store: SQLiteStore):
        self.store = store

    @staticmethod
    def _record(connection: sqlite3.Connection, collection: str, record_id: str):
        return connection.execute(
            "SELECT payload FROM records WHERE collection = ? AND id = ?",
            (collection, record_id),
        ).fetchone()

    @staticmethod
    def _authorize(connection: sqlite3.Connection, actor_id: str, definition: ScheduledAgentTaskDefinition) -> None:
        row = ScheduleRepository._record(connection, "users", actor_id)
        actor = User.model_validate_json(row["payload"]) if row else None
        if actor is None or actor.status != "active" or actor.workspace_id != definition.workspace_id:
            raise ScheduleDefinitionError("schedule_actor_not_authorized", status_code=403)
        row = ScheduleRepository._record(connection, "projects", definition.project_id or "")
        project = Project.model_validate_json(row["payload"]) if row else None
        if (
            project is None
            or project.workspace_id != actor.workspace_id
            or (project.member_ids and actor.id not in project.member_ids)
        ):
            raise ScheduleDefinitionError("project_not_found", status_code=404)
        rule_rows = connection.execute(
            "SELECT payload FROM records WHERE collection = 'permission_policy_rules' ORDER BY created_order"
        ).fetchall()
        rules = [PermissionPolicyRule.model_validate_json(row["payload"]) for row in rule_rows]
        if not has_permission(actor, ACTION_MANAGE_PROJECT_TASKS, rules):
            raise ScheduleDefinitionError("schedule_permission_denied", status_code=403)
        if definition.owner_user_id != definition.created_by:
            raise ScheduleDefinitionError("schedule_owner_invalid", status_code=403)
        # A manager must still be able to stop a schedule after its owner loses access.
        if not definition.enabled:
            return
        if project.status != "active":
            raise ScheduleDefinitionError("schedule_project_inactive", status_code=409)
        row = ScheduleRepository._record(connection, "users", definition.owner_user_id or "")
        owner = User.model_validate_json(row["payload"]) if row else None
        if (
            owner is None
            or owner.status != "active"
            or owner.workspace_id != actor.workspace_id
            or (project.member_ids and owner.id not in project.member_ids)
            or not has_permission(owner, ACTION_MANAGE_PROJECT_TASKS, rules)
        ):
            raise ScheduleDefinitionError("schedule_owner_not_authorized", status_code=403)
        row = ScheduleRepository._record(connection, "agents", definition.agent_id)
        agent = Agent.model_validate_json(row["payload"]) if row else None
        if (
            agent is None
            or agent.owner_user_id != owner.id
            or agent.workspace_id != owner.workspace_id
            or agent.id != owner.personal_agent_id
            or agent.agent_type != "personal"
            or agent.status != "online"
        ):
            raise ScheduleDefinitionError("schedule_agent_not_authorized", status_code=403)

    def commit_definition(
        self,
        receipt: ScheduleCommandReceiptV1,
        audit: AuditEvent,
        *,
        expected_version: int | None = None,
    ) -> ScheduledAgentTaskDefinition:
        definition = receipt.result
        with closing(self.store._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._record(connection, "schedule_command_receipts", receipt.id)
            if row is not None:
                existing = ScheduleCommandReceiptV1.model_validate_json(row["payload"])
                if (
                    existing.actor_id != receipt.actor_id
                    or existing.operation != receipt.operation
                    or existing.request_hash != receipt.request_hash
                ):
                    raise ScheduleDefinitionError("schedule_command_conflict")
                self._authorize(connection, receipt.actor_id, existing.result)
                return existing.result
            row = self._record(connection, "scheduled_agent_task_definitions", definition.id)
            current = ScheduledAgentTaskDefinition.model_validate_json(row["payload"]) if row else None
            if expected_version is None:
                if current is not None or receipt.operation != "create" or definition.version != 1:
                    raise ScheduleDefinitionError("schedule_version_conflict")
                if definition.owner_user_id != receipt.actor_id:
                    raise ScheduleDefinitionError("schedule_owner_invalid", status_code=403)
                self._authorize(connection, receipt.actor_id, definition)
                definition.change_cursor = self._initial_change_cursor(connection, definition)
                connection.execute(
                    "INSERT INTO records(collection, id, payload) VALUES ('scheduled_agent_task_definitions', ?, ?)",
                    (definition.id, definition.model_dump_json()),
                )
            else:
                if receipt.operation != "update":
                    raise ScheduleDefinitionError("schedule_version_conflict")
                if current is not None:
                    if current.schema_version is not None:
                        identity = (
                            "workspace_id",
                            "project_id",
                            "owner_user_id",
                            "created_by",
                            "agent_id",
                            "created_at",
                        )
                    else:
                        identity = ("created_by", "created_at")
                    if any(getattr(current, field) != getattr(definition, field) for field in identity):
                        raise ScheduleDefinitionError("schedule_identity_immutable")
                self._authorize(connection, receipt.actor_id, definition)
                if current is None or current.version != expected_version or definition.version != expected_version + 1:
                    raise ScheduleDefinitionError("schedule_version_conflict")
                if (
                    definition.on_project_changes and
                    (not current.on_project_changes or current.change_cursor is None
                     or definition.template_id != current.template_id or (definition.enabled and not current.enabled))
                ):
                    definition.change_cursor = self._initial_change_cursor(connection, definition)
                else:
                    definition.change_cursor = current.change_cursor if definition.on_project_changes else None
                # Runtime progress is updated independently of configuration
                # versions. A configuration command must not roll it back.
                for field in (
                    "last_run_at",
                    "last_success_at",
                    "last_failure_at",
                    "last_error_code",
                    "last_result_hash",
                    "last_result_run_id",
                ):
                    setattr(definition, field, getattr(current, field))
                if definition.template_id != current.template_id:
                    definition.last_success_at = None
                    definition.last_result_hash = None
                    definition.last_result_run_id = None
                connection.execute(
                    "UPDATE records SET payload = ? WHERE collection = 'scheduled_agent_task_definitions' AND id = ?",
                    (definition.model_dump_json(), definition.id),
                )
                if not definition.enabled:
                    pending = connection.execute(
                        """
                        SELECT run.payload AS run_payload, run.orchestration_version, dispatch.* FROM records AS occurrence
                        JOIN agent_runs AS run ON run.id = json_extract(occurrence.payload, '$.run_id')
                        JOIN run_dispatch_receipts AS dispatch ON dispatch.run_id = run.id
                        WHERE occurrence.collection = 'scheduled_occurrences'
                            AND json_extract(occurrence.payload, '$.schedule_id') = ?
                            AND dispatch.state = 'pending' AND dispatch.operation_kind = 'project_inspection'
                    """,
                        (definition.id,),
                    ).fetchall()
                    for row in pending:
                        run = AgentRun.model_validate_json(row["run_payload"])
                        self.store._cancel_agent_run_tree_in_transaction(
                            connection,
                            run,
                            stored_version=row["orchestration_version"],
                            reason="schedule_paused",
                            cancelled_at=definition.updated_at,
                        )
                        dispatch = self.store._decode_run_dispatch_row(row).model_copy(
                            update={
                                "state": RunDispatchState.SETTLED,
                                "updated_at": definition.updated_at,
                            }
                        )
                        connection.execute(
                            "UPDATE run_dispatch_receipts SET state = ?, payload = ?, updated_at = ? WHERE operation_key = ?",
                            (
                                dispatch.state.value,
                                dispatch.model_dump_json(),
                                dispatch.updated_at.isoformat(),
                                dispatch.operation_key,
                            ),
                        )
            connection.execute(
                "INSERT INTO records(collection, id, payload) VALUES ('schedule_command_receipts', ?, ?)",
                (receipt.id, receipt.model_dump_json()),
            )
            connection.execute(
                "INSERT INTO records(collection, id, payload) VALUES ('audit_events', ?, ?)",
                (audit.id, audit.model_dump_json()),
            )
        return definition

    @staticmethod
    def _initial_change_cursor(connection: sqlite3.Connection, definition: ScheduledAgentTaskDefinition) -> int | None:
        if not definition.on_project_changes:
            return None
        # Opt-in starts at the currently committed watermark, never replays
        # history from before the user's explicit configuration command.
        return connection.execute("SELECT COALESCE(MAX(created_order), 0) FROM records").fetchone()[0]

    def list_definitions(
        self,
        user: User,
        *,
        project_id: str | None = None,
        page: int = 1,
        page_size: int = 50,
        include_unvalidated: bool = False,
    ) -> ScheduledAgentTaskPageV1:
        if page < 1 or not 1 <= page_size <= 100:
            raise ScheduleDefinitionError("schedule_page_invalid", status_code=422)
        with closing(self.store._connect()) as connection, connection:
            connection.execute("BEGIN")
            row = self._record(connection, "users", user.id)
            actor = User.model_validate_json(row["payload"]) if row else None
            if actor is None or actor.status != "active" or actor.workspace_id != user.workspace_id:
                raise ScheduleDefinitionError("schedule_actor_not_authorized", status_code=403)
            rows = connection.execute(
                "SELECT payload FROM records WHERE collection = 'permission_policy_rules' ORDER BY created_order"
            ).fetchall()
            rules = [PermissionPolicyRule.model_validate_json(row["payload"]) for row in rows]
            inspection_allowed = has_permission(actor, ACTION_MANAGE_PROJECT_TASKS, rules)
            legacy_allowed = has_permission(actor, ACTION_MANAGE_PUBLIC_AGENT, rules)
            if not inspection_allowed and not legacy_allowed:
                raise ScheduleDefinitionError("schedule_permission_denied", status_code=403)
            if project_id is not None:
                row = self._record(connection, "projects", project_id)
                project = Project.model_validate_json(row["payload"]) if row else None
                if (
                    project is None
                    or project.workspace_id != actor.workspace_id
                    or (project.member_ids and actor.id not in project.member_ids)
                ):
                    raise ScheduleDefinitionError("project_not_found", status_code=404)
            query = """
                FROM records AS schedule
                LEFT JOIN records AS creator ON creator.collection = 'users'
                    AND creator.id = json_extract(schedule.payload, '$.created_by')
                LEFT JOIN records AS project ON project.collection = 'projects'
                    AND project.id = json_extract(schedule.payload, '$.project_id')
                WHERE schedule.collection = 'scheduled_agent_task_definitions' AND (
                    (? AND json_extract(schedule.payload, '$.schema_version') IS NULL
                        AND json_extract(creator.payload, '$.workspace_id') = ?
                        AND (? IS NULL OR (? AND creator.id = ?)))
                    OR (? AND json_extract(schedule.payload, '$.schema_version') = 'project-inspection-schedule-v1'
                        AND json_extract(schedule.payload, '$.workspace_id') = ?
                        AND json_extract(project.payload, '$.workspace_id') = ?
                        AND (? IS NULL OR project.id = ?)
                        AND (json_array_length(json_extract(project.payload, '$.member_ids')) = 0
                            OR EXISTS (SELECT 1 FROM json_each(project.payload, '$.member_ids') WHERE value = ?)))
                )
            """
            parameters = (
                legacy_allowed,
                actor.workspace_id,
                project_id,
                include_unvalidated,
                actor.id,
                inspection_allowed,
                actor.workspace_id,
                actor.workspace_id,
                project_id,
                project_id,
                actor.id,
            )
            total = connection.execute("SELECT COUNT(*) AS count " + query, parameters).fetchone()["count"]
            rows = connection.execute(
                "SELECT schedule.payload " + query + " ORDER BY schedule.created_order DESC LIMIT ? OFFSET ?",
                (*parameters, page_size, (page - 1) * page_size),
            ).fetchall()
        return ScheduledAgentTaskPageV1(
            items=[ScheduledAgentTaskDefinition.model_validate_json(row["payload"]) for row in rows],
            total_count=total,
            page=page,
            page_size=page_size,
        )
