"""Single-process admission latch for safe orchestration shutdown."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from concurrent.futures import Future
from contextlib import contextmanager
from threading import Condition, Event, RLock


class OrchestrationQuiescingError(RuntimeError):
    """Raised when forward work reaches a process that is quiescing."""

    code = "orchestration_quiescing"

    def __init__(self) -> None:
        super().__init__(self.code)


class OrchestrationQuiesceController:
    """Linearize short admission actions against a one-way quiesce latch.

    A permit protects only the transaction or queue action that admits new work;
    callers must release it before performing model, Tool, or other external I/O.
    """

    def __init__(self) -> None:
        self._condition = Condition(RLock())
        self._quiescing = False
        self._quiesced = False
        self._active_permits = 0
        self._quiescing_event = Event()
        self._completion: Future[None] = Future()

    @property
    def is_quiescing(self) -> bool:
        with self._condition:
            return self._quiescing

    @property
    def is_quiesced(self) -> bool:
        with self._condition:
            return self._quiesced

    @property
    def active_permits(self) -> int:
        with self._condition:
            return self._active_permits

    def wait_until_quiescing(self, timeout: float | None = None) -> bool:
        """Block a process-management observer until the latch closes."""

        return self._quiescing_event.wait(timeout)

    @contextmanager
    def permit(self) -> Iterator[None]:
        """Admit one short synchronous mutation or dispatch claim."""

        with self._condition:
            if self._quiescing:
                raise OrchestrationQuiescingError
            self._active_permits += 1
        try:
            yield
        finally:
            with self._condition:
                self._active_permits -= 1
                if self._active_permits == 0:
                    self._condition.notify_all()

    async def begin_quiesce(
        self,
        stop_recovery: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Close admission once, drain permits, then stop recovery scheduling.

        Concurrent callers wait on the same completion future. The latch never
        reopens during this process lifetime, including when recovery shutdown
        reports an error.
        """

        with self._condition:
            leader = not self._quiescing
            if leader:
                self._quiescing = True
                self._quiescing_event.set()
            completion = self._completion
        if not leader:
            await asyncio.shield(asyncio.wrap_future(completion))
            return

        try:
            await asyncio.to_thread(self._wait_for_active_permits)
            if stop_recovery is not None:
                await stop_recovery()
        except BaseException as error:
            if not completion.done():
                completion.set_exception(error)
            raise
        else:
            with self._condition:
                self._quiesced = True
            completion.set_result(None)

    def _wait_for_active_permits(self) -> None:
        with self._condition:
            self._condition.wait_for(lambda: self._active_permits == 0)
