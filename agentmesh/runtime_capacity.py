"""Process-local capacity controls shared by every Runtime service instance."""

from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager


class RuntimeCapacityError(RuntimeError):
    code = "runtime_capacity_exceeded"

    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(self.code)


class RuntimeCapacityController:
    def __init__(
        self,
        *,
        process_run_limit: int = 10,
        user_run_limit: int = 2,
        node_limit: int = 3,
        llm_limit: int = 4,
        tool_limit: int = 6,
    ) -> None:
        if min(
            process_run_limit,
            user_run_limit,
            node_limit,
            llm_limit,
            tool_limit,
        ) < 1:
            raise ValueError("runtime capacity limits must be positive")
        self.process_run_limit = process_run_limit
        self.user_run_limit = user_run_limit
        self.node_limit = node_limit
        self.llm_limit = llm_limit
        self.tool_limit = tool_limit
        self._lock = threading.Lock()
        self._run_reservations: dict[str, str] = {}
        self._runs_by_user: dict[str, int] = {}
        self._node_slots = threading.BoundedSemaphore(node_limit)
        self._llm_slots = threading.BoundedSemaphore(llm_limit)
        self._tool_slots = threading.BoundedSemaphore(tool_limit)
        self._active_nodes = 0
        self._active_llm_calls = 0
        self._active_tool_calls = 0

    def claim_run(
        self,
        *,
        operation_key: str,
        user_id: str,
    ) -> tuple[bool, bool]:
        """Return (accepted, newly_reserved)."""
        with self._lock:
            existing_user = self._run_reservations.get(operation_key)
            if existing_user is not None:
                return existing_user == user_id, False
            if len(self._run_reservations) >= self.process_run_limit:
                return False, False
            if self._runs_by_user.get(user_id, 0) >= self.user_run_limit:
                return False, False
            self._run_reservations[operation_key] = user_id
            self._runs_by_user[user_id] = self._runs_by_user.get(user_id, 0) + 1
            return True, True

    def reserve_run(self, *, operation_key: str, user_id: str) -> bool:
        accepted, _created = self.claim_run(
            operation_key=operation_key,
            user_id=user_id,
        )
        return accepted

    def release_run(self, operation_key: str) -> None:
        with self._lock:
            user_id = self._run_reservations.pop(operation_key, None)
            if user_id is None:
                return
            remaining = self._runs_by_user.get(user_id, 0) - 1
            if remaining > 0:
                self._runs_by_user[user_id] = remaining
            else:
                self._runs_by_user.pop(user_id, None)

    @asynccontextmanager
    async def node_slot(self):  # noqa: ANN201
        while not self._node_slots.acquire(blocking=False):
            await asyncio.sleep(0.01)
        with self._lock:
            self._active_nodes += 1
        try:
            yield
        finally:
            with self._lock:
                self._active_nodes -= 1
            self._node_slots.release()

    @asynccontextmanager
    async def llm_slot(self):  # noqa: ANN201
        while not self._llm_slots.acquire(blocking=False):
            await asyncio.sleep(0.01)
        with self._lock:
            self._active_llm_calls += 1
        try:
            yield
        finally:
            with self._lock:
                self._active_llm_calls -= 1
            self._llm_slots.release()

    async def acquire_tool(self) -> None:
        while not self._tool_slots.acquire(blocking=False):
            await asyncio.sleep(0.01)
        with self._lock:
            self._active_tool_calls += 1

    def release_tool(self) -> None:
        with self._lock:
            self._active_tool_calls -= 1
        self._tool_slots.release()

    @asynccontextmanager
    async def tool_slot(self):  # noqa: ANN201
        await self.acquire_tool()
        try:
            yield
        finally:
            self.release_tool()

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "active_runs": len(self._run_reservations),
                "active_nodes": self._active_nodes,
                "active_llm_calls": self._active_llm_calls,
                "active_tool_calls": self._active_tool_calls,
                "process_run_limit": self.process_run_limit,
                "user_run_limit": self.user_run_limit,
                "node_limit": self.node_limit,
                "llm_limit": self.llm_limit,
                "tool_limit": self.tool_limit,
            }


_lock = threading.Lock()
_capacity = RuntimeCapacityController()


def current_runtime_capacity() -> RuntimeCapacityController:
    with _lock:
        return _capacity


def install_runtime_capacity(
    controller: RuntimeCapacityController,
) -> RuntimeCapacityController:
    global _capacity
    with _lock:
        _capacity = controller
    return controller
