from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime

from agentmesh.automation.contracts import AutomationTickV1, ScheduleDuePreviewV1
from agentmesh.automation.occurrences import OccurrenceRepository
from agentmesh.automation.schedule_repository import ScheduleDefinitionError
from agentmesh.automation.settings import automation_mode
from agentmesh.automation.time_policy import CronSchedule
from agentmesh.models import now_utc
from agentmesh.skill_runtime.quiesce import OrchestrationQuiesceController
from agentmesh.store import SQLiteStore


class AutomationCoordinator:
    def __init__(
        self,
        repository: SQLiteStore,
        *,
        runtime_available: Callable[[], bool],
        wake_dispatch: Callable[[], None] | None = None,
        admission: OrchestrationQuiesceController | None = None,
    ):
        self.repository = OccurrenceRepository(repository)
        self.runtime_available = runtime_available
        self.wake_dispatch = wake_dispatch
        self.admission = admission or OrchestrationQuiesceController()
        self.last_tick_at: datetime | None = None
        self.last_error_code: str | None = None
        self._task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if not self.running:
            self._task = asyncio.create_task(self._loop(), name="agentmesh-inspection-scheduler")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _loop(self) -> None:
        while not self.admission.is_quiescing:
            try:
                result = self.tick()
                self.last_tick_at, self.last_error_code = now_utc(), None
                if result.occurrences and self.wake_dispatch is not None:
                    self.wake_dispatch()
            except Exception:
                self.last_error_code = "automation_tick_failed"
            await asyncio.sleep(1)

    def tick(self, at: datetime | None = None, *, limit: int = 50) -> AutomationTickV1:
        at = at or now_utc()
        if at.utcoffset() is None or not 1 <= limit <= 100:
            raise ScheduleDefinitionError("automation_tick_invalid", status_code=422)
        mode = automation_mode()
        result = AutomationTickV1(mode=mode)
        if mode == "off" or self.admission.is_quiescing:
            return result
        definitions = self.repository.due_definitions(at, limit=limit + 1)
        result.has_more = len(definitions) > limit
        for definition in definitions[:limit]:
            slot = CronSchedule(definition.schedule, definition.timezone).latest_slot(at)
            result.due.append(
                ScheduleDuePreviewV1(
                    schedule_id=definition.id,
                    definition_version=definition.version,
                    scheduled_at=slot.scheduled_at,
                    local_slot=slot.local_slot,
                    budget=definition.budget,
                    blocked_reason=self.repository.preview_reason(definition, at, runtime_available=self.runtime_available()),
                )
            )
            if mode == "execute":
                with self.admission.permit():
                    occurrence = self.repository.admit(definition.id, at, runtime_available=self.runtime_available())
                if occurrence is not None:
                    result.occurrences.append(occurrence)
        remaining = limit - len(result.due)
        if remaining:
            previews, has_more = self.repository.change_previews(
                at, runtime_available=self.runtime_available(), limit=remaining,
            )
            result.has_more = result.has_more or has_more
            result.due.extend(previews)
            if mode == "execute":
                for preview in previews:
                    with self.admission.permit():
                        occurrence = self.repository.admit(
                            preview.schedule_id, at, runtime_available=self.runtime_available(), change=True,
                        )
                    if occurrence is not None:
                        result.occurrences.append(occurrence)
        return result
