"""Single-process recovery coordinator for durable DeepSearch runs."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from typing import Protocol

from agentmesh.models import AgentPlanningMode, AgentRun, AgentRunStatus, now_utc


class DeepSearchRecoveryRepository(Protocol):
    def list_recoverable_deepsearch_runs(self) -> list[AgentRun]: ...

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
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("DeepSearch recovery interval must be positive")
        self._repository = repository
        self._runtime = runtime
        self._interval_seconds = interval_seconds
        self._clock = clock
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._scan_lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._run_tasks: dict[str, asyncio.Task[AgentRun | None]] = {}

    async def recover_once(self) -> int:
        """Schedule each recoverable Run once without awaiting long execution."""

        scheduled = 0
        async with self._scan_lock:
            runs = self._repository.list_recoverable_deepsearch_runs()
            checked_at = self._clock()
            for candidate in runs:
                if (
                    candidate.orchestration_version != "v1"
                    or candidate.planning_mode is not AgentPlanningMode.DEEPSEARCH
                    or candidate.status in _TERMINAL_STATUSES
                ):
                    continue
                try:
                    run = self._repository.expire_deepsearch_run_if_needed(
                        candidate.id,
                        user_id=candidate.user_id,
                        checked_at=checked_at,
                    )
                    if run is None or run.status in _TERMINAL_STATUSES:
                        continue
                    if run.status in _WAITING_STATUSES:
                        continue
                    if run.orchestration_mode != "execute":
                        continue
                    existing = self._run_tasks.get(run.id)
                    if existing is not None and not existing.done():
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
                    scheduled += 1
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # A malformed candidate must not prevent other Runs from being
                    # considered. The next periodic scan retries repository-level
                    # transient failures; Runtime failures wake the loop below.
                    continue
        return scheduled

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._wake.clear()
        await self.recover_once()
        self._task = asyncio.create_task(
            self._run(),
            name="agentmesh-deepsearch-recovery",
        )

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
            # One managed task failed abnormally. Wake the sole scan loop instead
            # of spawning a second scheduler or recursively retrying here.
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
