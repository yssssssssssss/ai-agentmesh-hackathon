from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from agentmesh.automation.schedule_repository import (
    ScheduleCommandReceiptV1,
    ScheduleDefinitionError,
    ScheduleRepository,
)
from agentmesh.automation.time_policy import CronSchedule, ScheduleTimeError
from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.models import (
    AuditEvent,
    ScheduledAgentTaskCreateRequest,
    ScheduledAgentTaskDefinition,
    ScheduledAgentTaskUpdateRequest,
    User,
    now_utc,
)
from agentmesh.store import SQLiteStore


class ScheduleDefinitionService:
    def __init__(self, repository: SQLiteStore, *, clock: Callable[[], datetime] = now_utc):
        self.store = repository
        self.repository = ScheduleRepository(repository)
        self.clock = clock

    def create(self, request: ScheduledAgentTaskCreateRequest, user: User) -> ScheduledAgentTaskDefinition:
        if request.project_id is None or request.template_id is None or request.command_id is None:
            raise ScheduleDefinitionError("schedule_project_template_required", status_code=422)
        actor = self.store.get_user(user.id)
        if actor is None or actor.status != "active" or actor.workspace_id != user.workspace_id:
            raise ScheduleDefinitionError("schedule_actor_not_authorized", status_code=403)
        if request.agent_id is not None and request.agent_id != actor.personal_agent_id:
            raise ScheduleDefinitionError("schedule_agent_not_authorized", status_code=403)
        now = self.clock()
        try:
            cron = CronSchedule(request.schedule, request.timezone)
            next_slot = cron.next_slot(now)
            next_run_at = next_slot.scheduled_at if request.enabled else None
        except ScheduleTimeError as error:
            raise ScheduleDefinitionError(error.code, status_code=422) from error
        definition = ScheduledAgentTaskDefinition(
            agent_id=actor.personal_agent_id,
            title=request.title,
            prompt=f"Project inspection: {request.template_id}",
            schedule=cron.expression,
            enabled=request.enabled,
            created_by=actor.id,
            schema_version="project-inspection-schedule-v1",
            workspace_id=actor.workspace_id,
            project_id=request.project_id,
            owner_user_id=actor.id,
            template_id=request.template_id,
            timezone=request.timezone,
            validation_state="valid",
            next_run_at=next_run_at,
            on_project_changes=request.on_project_changes,
            created_at=now,
            updated_at=now,
        )
        receipt = ScheduleCommandReceiptV1(
            id=f"schedule_command_{canonical_json_sha256([actor.id, request.command_id])}",
            actor_id=actor.id,
            operation="create",
            request_hash=canonical_json_sha256(request.model_dump(mode="json")),
            result=definition,
        )
        return self.repository.commit_definition(
            receipt,
            AuditEvent(
                actor=actor.id,
                action="create_project_inspection_schedule",
                target_type="scheduled_agent_task",
                target_id=definition.id,
                workspace_id=actor.workspace_id,
                project_id=request.project_id,
                metadata={"version": definition.version, "template_id": request.template_id},
                created_at=now,
            ),
        )

    def update(
        self,
        definition_id: str,
        request: ScheduledAgentTaskUpdateRequest,
        user: User,
    ) -> ScheduledAgentTaskDefinition:
        if request.command_id is None or request.expected_version is None:
            raise ScheduleDefinitionError("schedule_command_version_required", status_code=422)
        current = self.store.get_scheduled_agent_task_definition(definition_id)
        if current is None:
            raise ScheduleDefinitionError("schedule_not_found", status_code=404)
        if request.prompt is not None:
            raise ScheduleDefinitionError("schedule_template_prompt_fixed", status_code=422)
        actor = self.store.get_user(user.id)
        if actor is None or actor.status != "active" or actor.workspace_id != user.workspace_id:
            raise ScheduleDefinitionError("schedule_actor_not_authorized", status_code=403)
        if current.schema_version is None:
            if request.project_id is None or request.template_id is None:
                raise ScheduleDefinitionError("schedule_project_template_required", status_code=422)
            owner = self.store.get_user(current.created_by)
            if owner is None:
                raise ScheduleDefinitionError("schedule_owner_invalid", status_code=403)
            identity = {
                "schema_version": "project-inspection-schedule-v1",
                "validation_state": "valid",
                "workspace_id": owner.workspace_id,
                "project_id": request.project_id,
                "owner_user_id": owner.id,
                "agent_id": owner.personal_agent_id,
            }
        else:
            if request.project_id is not None and request.project_id != current.project_id:
                raise ScheduleDefinitionError("schedule_project_immutable", status_code=422)
            identity = {}
        values = request.model_dump(exclude_none=True, exclude={"command_id", "expected_version", "project_id"})
        now = self.clock()
        definition = ScheduledAgentTaskDefinition.model_validate(
            {
                **current.model_dump(),
                **identity,
                **values,
                "version": request.expected_version + 1,
                "updated_at": now,
            }
        )
        try:
            cron = CronSchedule(definition.schedule, definition.timezone)
            next_slot = cron.next_slot(now)
            definition.next_run_at = next_slot.scheduled_at if definition.enabled else None
        except ScheduleTimeError as error:
            raise ScheduleDefinitionError(error.code, status_code=422) from error
        definition.prompt = f"Project inspection: {definition.template_id}"
        definition.blocked_reason = None
        receipt = ScheduleCommandReceiptV1(
            id=f"schedule_command_{canonical_json_sha256([actor.id, request.command_id])}",
            actor_id=actor.id,
            operation="update",
            request_hash=canonical_json_sha256([definition_id, request.model_dump(mode="json")]),
            result=definition,
        )
        return self.repository.commit_definition(
            receipt,
            AuditEvent(
                actor=actor.id,
                action="update_project_inspection_schedule",
                target_type="scheduled_agent_task",
                target_id=definition.id,
                workspace_id=actor.workspace_id,
                project_id=definition.project_id,
                metadata={"version": definition.version, "enabled": definition.enabled},
                created_at=now,
            ),
            expected_version=request.expected_version,
        )
