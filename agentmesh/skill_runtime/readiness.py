from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from time import monotonic
from typing import Literal, Protocol

from agentmesh.skill_runtime.universal_policy import universal_retrieval_policy

ToolHealthState = Literal["healthy", "unhealthy", "unavailable", "timeout", "unprobed"]
ToolImplementationKey = tuple[str, str, str]


class ToolHealthDescriptor(Protocol):
    implementation_id: str
    implementation_version: str
    health_state: str


@dataclass(frozen=True, slots=True)
class ToolProbeRequest:
    tool_name: str
    implementation_id: str
    implementation_version: str
    priority: tuple[int, int, int, str, str, str]

    @property
    def key(self) -> ToolImplementationKey:
        return (self.tool_name, self.implementation_id, self.implementation_version)


@dataclass(frozen=True, slots=True)
class ToolProbeBatchResult:
    states: Mapping[ToolImplementationKey, ToolHealthState]
    probed_count: int
    cache_hit_count: int


class ToolHealthProbeCoordinator:
    """Deduplicate, cache, and budget synchronous Tool health probes."""

    def __init__(
        self,
        probe: Callable[[str], ToolHealthDescriptor | None],
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._probe = probe
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: dict[ToolImplementationKey, tuple[float, ToolHealthState]] = {}

    def probe(self, requests: Iterable[ToolProbeRequest]) -> ToolProbeBatchResult:
        policy = universal_retrieval_policy()
        unique: dict[ToolImplementationKey, ToolProbeRequest] = {}
        for request in requests:
            existing = unique.get(request.key)
            if existing is None or request.priority < existing.priority:
                unique[request.key] = request
        ordered = sorted(unique.values(), key=lambda request: request.priority)
        now = self._clock()
        states: dict[ToolImplementationKey, ToolHealthState] = {}
        pending: list[ToolProbeRequest] = []
        cache_hits = 0
        with self._lock:
            for request in ordered:
                cached = self._cache.get(request.key)
                if cached is not None and cached[0] > now:
                    states[request.key] = cached[1]
                    cache_hits += 1
                else:
                    self._cache.pop(request.key, None)
                    pending.append(request)

        selected = pending[: policy.tool_probe_budget]
        for request in pending[policy.tool_probe_budget :]:
            states[request.key] = "unprobed"
        if not selected:
            return ToolProbeBatchResult(states=states, probed_count=0, cache_hit_count=cache_hits)

        executor = ThreadPoolExecutor(
            max_workers=min(policy.tool_probe_concurrency, len(selected)),
            thread_name_prefix="skill-tool-health",
        )
        futures = {executor.submit(self._probe, request.tool_name): request for request in selected}
        timeout_seconds = min(
            policy.tool_probe_timeout_ms / 1000,
            policy.tool_probe_batch_deadline_ms / 1000,
        )
        done, not_done = wait(futures, timeout=timeout_seconds)
        for future in not_done:
            request = futures[future]
            states[request.key] = "timeout"
            future.cancel()
        cache_updates: dict[ToolImplementationKey, tuple[float, ToolHealthState]] = {}
        expires_at = self._clock() + policy.tool_health_cache_ttl_seconds
        for future in done:
            request = futures[future]
            try:
                descriptor = future.result()
            except Exception:
                state: ToolHealthState = "timeout"
            else:
                if descriptor is None or (
                    descriptor.implementation_id != request.implementation_id
                    or descriptor.implementation_version != request.implementation_version
                ):
                    state = "unavailable"
                elif descriptor.health_state == "healthy":
                    state = "healthy"
                elif descriptor.health_state == "unavailable":
                    state = "unhealthy"
                else:
                    state = "timeout"
            states[request.key] = state
            if state in {"healthy", "unhealthy", "unavailable"}:
                cache_updates[request.key] = (expires_at, state)
        executor.shutdown(wait=False, cancel_futures=True)
        if cache_updates:
            with self._lock:
                self._cache.update(cache_updates)
        return ToolProbeBatchResult(
            states=states,
            probed_count=len(selected),
            cache_hit_count=cache_hits,
        )
