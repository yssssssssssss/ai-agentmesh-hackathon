from __future__ import annotations

import threading
from dataclasses import dataclass

from agentmesh.skill_runtime.readiness import ToolHealthProbeCoordinator, ToolProbeRequest


@dataclass(frozen=True)
class _Descriptor:
    implementation_id: str
    implementation_version: str
    health_state: str


def _request(index: int, *, priority: int | None = None) -> ToolProbeRequest:
    return ToolProbeRequest(
        tool_name=f"tool-{index}",
        implementation_id=f"implementation-{index}",
        implementation_version="1",
        priority=(priority if priority is not None else index, 0, index, f"tool-{index}", f"implementation-{index}", "1"),
    )


def test_tool_health_probes_are_deduplicated_and_cached() -> None:
    now = [100.0]
    calls: list[str] = []

    def probe(tool_name: str) -> _Descriptor:
        calls.append(tool_name)
        index = tool_name.removeprefix("tool-")
        return _Descriptor(f"implementation-{index}", "1", "healthy")

    coordinator = ToolHealthProbeCoordinator(probe, clock=lambda: now[0])
    request = _request(1)

    first = coordinator.probe([request, request])
    second = coordinator.probe([request])

    assert first.states[request.key] == "healthy"
    assert first.probed_count == 1
    assert second.states[request.key] == "healthy"
    assert second.cache_hit_count == 1
    assert calls == ["tool-1"]

    now[0] += 31
    coordinator.probe([request])
    assert calls == ["tool-1", "tool-1"]


def test_tool_health_probe_budget_is_priority_ordered_and_tail_stays_unprobed() -> None:
    calls: list[str] = []

    def probe(tool_name: str) -> _Descriptor:
        calls.append(tool_name)
        index = tool_name.removeprefix("tool-")
        return _Descriptor(f"implementation-{index}", "1", "healthy")

    coordinator = ToolHealthProbeCoordinator(probe)
    requests = [_request(index, priority=20 - index) for index in range(10)]

    result = coordinator.probe(requests)

    assert result.probed_count == 8
    assert len(calls) == 8
    assert result.states[_request(0).key] == "unprobed"
    assert result.states[_request(1).key] == "unprobed"
    assert all(result.states[_request(index).key] == "healthy" for index in range(2, 10))


def test_tool_health_timeout_is_not_cached() -> None:
    release = threading.Event()
    calls = 0

    def probe(tool_name: str) -> _Descriptor:
        nonlocal calls
        calls += 1
        release.wait(timeout=2)
        index = tool_name.removeprefix("tool-")
        return _Descriptor(f"implementation-{index}", "1", "healthy")

    coordinator = ToolHealthProbeCoordinator(probe)
    request = _request(1)

    first = coordinator.probe([request])
    assert first.states[request.key] == "timeout"
    release.set()
    second = coordinator.probe([request])

    assert second.states[request.key] == "healthy"
    assert calls == 2


def test_tool_health_rejects_unhealthy_or_wrong_implementation() -> None:
    descriptors = {
        "tool-1": _Descriptor("implementation-1", "1", "unavailable"),
        "tool-2": _Descriptor("other", "1", "healthy"),
    }
    coordinator = ToolHealthProbeCoordinator(descriptors.get)

    result = coordinator.probe([_request(1), _request(2)])

    assert result.states[_request(1).key] == "unhealthy"
    assert result.states[_request(2).key] == "unavailable"
