"""Single-process recovery coordinator for durable DeepSearch runs."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from typing import Protocol

from agentmesh.agent_runtime.settings import (
    SkillOrchestrationMode,
    skill_orchestration_mode,
)
from agentmesh.models import AgentPlanningMode, AgentRun, AgentRunStatus, now_utc
from agentmesh.runtime_capacity import RuntimeCapacityError
from agentmesh.skill_runtime.quiesce import (
    OrchestrationQuiesceController,
    OrchestrationQuiescingError,
)


class DeepSearchRecoveryRepository(Protocol):
    def list_recoverable_deepsearch_runs(
        self,
        *,
        limit: int = 50,
        after: tuple[str, str] | None = None,
    ) -> list[AgentRun]: ...

    def expire_deepsearch_run_if_needed(
        self,
        run_id: str,
        *,
        user_id: str,
        checked_at: datetime | None = None,
    ) -> AgentRun | None: ...


class DeepSearchRecoveryRuntime(Protocol):
    async def recover_deepsearch_run(self, run_id: str) -> AgentRun | None: ...


_TERMINAL_STATUSES = frozenset(
    {
        AgentRunStatus.COMPLETED,
        AgentRunStatus.PARTIAL,
        AgentRunStatus.FAILED,
        AgentRunStatus.REJECTED,
        AgentRunStatus.CANCELLED,
    }
)
_WAITING_STATUSES = frozenset(
    {
        AgentRunStatus.WAITING_CLARIFICATION,
        AgentRunStatus.WAITING_PLAN_APPROVAL,
        AgentRunStatus.WAITING_APPROVAL,
    }
)


class DeepSearchRecoveryCoordinator:
    """Scan persisted DeepSearch state without creating a second execution engine.

    The runtime owns all Plan/node claims and all finalization CAS operations.  This
    coordinator merely expires waiting runs and asks that runtime to resume active
    computation.  Per-run failures are retried by a later scan so one corrupt run
    cannot stop recovery for every other user.
    """

    def __init__(
        self,
        repository: DeepSearchRecoveryRepository,
        runtime: DeepSearchRecoveryRuntime,
        *,
        interval_seconds: float = 30.0,
        clock: Callable[[], datetime] = now_utc,
        admission: OrchestrationQuiesceController | None = None,
        mode_provider: Callable[[], SkillOrchestrationMode] = skill_orchestration_mode,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("DeepSearch recovery interval must be positive")
        self._repository = repository
        self._runtime = runtime
        self._interval_seconds = interval_seconds
        self._clock = clock
        self._admission = admission or OrchestrationQuiesceController()
        self._mode_provider = mode_provider
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._scan_lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._run_tasks: dict[str, asyncio.Task[AgentRun | None]] = {}
        self._cursor: tuple[str, str] | None = None
        self._max_recovery_workers = 2

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def _recovery_allowed(self) -> bool:
        return (
            not self._stop.is_set()
            and self._mode_provider() is SkillOrchestrationMode.EXECUTE
            and not self._admission.is_quiescing
        )

    async def recover_once(self) -> int:
        """Schedule each recoverable Run once without awaiting long execution."""

        scheduled = 0
        if not self._recovery_allowed():
            return scheduled
        async with self._scan_lock:
            if not self._recovery_allowed():
                return scheduled
            available_workers = self._max_recovery_workers - sum(
                1 for task in self._run_tasks.values() if not task.done()
            )
            runs = await asyncio.to_thread(
                self._repository.list_recoverable_deepsearch_runs,
                limit=50,
                after=self._cursor,
            )
            checked_at = self._clock()
            next_cursor = self._cursor
            cursor_blocked = False
            for candidate in runs:
                candidate_cursor = (candidate.updated_at.isoformat(), candidate.id)
                if (
                    candidate.orchestration_version != "v1"
                    or candidate.planning_mode is not AgentPlanningMode.DEEPSEARCH
                    or candidate.status in _TERMINAL_STATUSES
                ):
                    if not cursor_blocked:
                        next_cursor = candidate_cursor
                    continue
                try:
                    run = await asyncio.to_thread(
                        self._repository.expire_deepsearch_run_if_needed,
                        candidate.id,
                        user_id=candidate.user_id,
                        checked_at=checked_at,
                    )
                    if (
                        run is None
                        or run.status in _TERMINAL_STATUSES
                        or run.status in _WAITING_STATUSES
                        or run.orchestration_mode != "execute"
                    ):
                        if not cursor_blocked:
                            next_cursor = candidate_cursor
                        continue
                    existing = self._run_tasks.get(run.id)
                    if existing is not None and not existing.done():
                        if not cursor_blocked:
                            next_cursor = candidate_cursor
                        continue
                    if available_workers <= 0:
                        cursor_blocked = True
                        continue
                    try:
                        with self._admission.permit():
                            if (
                                self._mode_provider()
                                is not SkillOrchestrationMode.EXECUTE
                            ):
                                cursor_blocked = True
                                continue
                            task = asyncio.create_task(
                                self._runtime.recover_deepsearch_run(run.id),
                                name=f"agentmesh-deepsearch-recovery-{run.id}",
                            )
                            self._run_tasks[run.id] = task
                            task.add_done_callback(
                                lambda completed, run_id=run.id: self._finish_run_task(
                                    run_id,
                                    completed,
                                )
                            )
                    except OrchestrationQuiescingError:
                        cursor_blocked = True
                        continue
                    scheduled += 1
                    available_workers -= 1
                    if not cursor_blocked:
                        next_cursor = candidate_cursor
                except asyncio.CancelledError:
                    raise
                except Exception:
                    cursor_blocked = True
                    continue
            self._cursor = next_cursor
        return scheduled

    def wake(self) -> None:
        """Restart the cursor so newly-active durable work is considered promptly."""

        self._cursor = None
        self._wake.set()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        if not self._recovery_allowed():
            return
        self._stop.clear()
        self._wake.clear()
        await self.recover_once()
        try:
            with self._admission.permit():
                if (
                    self._mode_provider()
                    is not SkillOrchestrationMode.EXECUTE
                ):
                    return
                self._task = asyncio.create_task(
                    self._run(),
                    name="agentmesh-deepsearch-recovery",
                )
        except OrchestrationQuiescingError:
            return

    async def begin_quiesce(self) -> None:
        """Stop future scans and wait for any current scan to leave its lock."""

        self._stop.set()
        self._wake.set()
        async with self._scan_lock:
            pass
        task = self._task
        if task is not None and task is not asyncio.current_task():
            await task
        self._task = None

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        task = self._task
        if task is not None:
            await task
        self._task = None
        run_tasks = list(self._run_tasks.values())
        for run_task in run_tasks:
            if not run_task.done():
                run_task.cancel()
        if run_tasks:
            await asyncio.gather(*run_tasks, return_exceptions=True)
        self._run_tasks.clear()

    def _finish_run_task(
        self,
        run_id: str,
        task: asyncio.Task[AgentRun | None],
    ) -> None:
        if self._run_tasks.get(run_id) is task:
            self._run_tasks.pop(run_id, None)
        if task.cancelled():
            return
        try:
            error = task.exception()
        except asyncio.CancelledError:
            return
        if error is not None and not self._stop.is_set():
            # Capacity pressure is ordinary deferred work: reset the cursor but
            # wait for the bounded interval (or an explicit capacity wakeup).
            self._cursor = None
            if isinstance(error, RuntimeCapacityError):
                return
            self._wake.set()
            return
        if error is None and not self._stop.is_set():
            result = task.result()
            if result is not None and result.status in {
                *_TERMINAL_STATUSES,
                *_WAITING_STATUSES,
            }:
                self._cursor = None
                self._wake.set()

    async def _run(self) -> None:
        while not self._stop.is_set():
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    self._wake.wait(),
                    timeout=self._interval_seconds,
                )
            self._wake.clear()
            if not self._stop.is_set():
                await self.recover_once()
