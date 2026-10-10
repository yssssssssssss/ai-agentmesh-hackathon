from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime

from agentmesh.memory_learning.extractor import SDKDocumentExtractor
from agentmesh.memory_learning.service import MemoryLearningService
from agentmesh.memory_lifecycle import MemoryForgettingService
from agentmesh.models import now_utc
from agentmesh.skill_runtime.quiesce import OrchestrationQuiesceController
from agentmesh.store import SQLiteStore


class MemoryLearningCoordinator:
    def __init__(self, store: SQLiteStore, *, admission: OrchestrationQuiesceController):
        self.service = MemoryLearningService(store, admission=admission)
        self.forgetting = MemoryForgettingService(store)
        self.extractor = SDKDocumentExtractor(store)
        self.admission = admission
        self.last_tick_at: datetime | None = None
        self.last_error_code: str | None = None
        self._task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if not self.running:
            self._task = asyncio.create_task(self._loop(), name='agentmesh-memory-learning')

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def tick(self) -> int:
        if self.admission.is_quiescing:
            return 0
        # Cleanup remains available when model learning is off or paused.
        self.forgetting.cleanup(limit=100)
        self.service.discover_sources(limit=20)
        processed = 0
        for _ in range(10):
            if self.admission.is_quiescing:
                break
            count = await self.service.run_once(self.extractor)
            if count == 0:
                break
            processed += count
            # One read-only extraction at a time; never monopolize the HTTP event loop.
            await asyncio.sleep(0)
            if self.service.mode_provider() != 'execute':
                break
        return processed

    async def _loop(self) -> None:
        while not self.admission.is_quiescing:
            try:
                await self.tick()
                self.last_tick_at, self.last_error_code = now_utc(), None
            except Exception:
                self.last_error_code = 'memory_learning_tick_failed'
            await asyncio.sleep(5)
