from __future__ import annotations

import asyncio
from threading import Event

import pytest

from agentmesh.skill_runtime.quiesce import (
    OrchestrationQuiesceController,
    OrchestrationQuiescingError,
)


def test_quiesce_waits_for_inflight_permit_and_rejects_new_work() -> None:
    controller = OrchestrationQuiesceController()
    entered = Event()
    release = Event()
    recovery_stopped = Event()

    def admitted_work() -> None:
        with controller.permit():
            entered.set()
            assert release.wait(timeout=2)

    async def stop_recovery() -> None:
        recovery_stopped.set()

    async def exercise() -> None:
        worker = asyncio.create_task(asyncio.to_thread(admitted_work))
        assert await asyncio.to_thread(entered.wait, 2)
        quiesce = asyncio.create_task(controller.begin_quiesce(stop_recovery))
        assert await asyncio.to_thread(controller.wait_until_quiescing, 2)

        assert not quiesce.done()
        assert not recovery_stopped.is_set()
        with pytest.raises(OrchestrationQuiescingError) as error, controller.permit():
            raise AssertionError("quiescing controller admitted new work")
        assert error.value.code == "orchestration_quiescing"

        release.set()
        await worker
        await asyncio.wait_for(quiesce, timeout=2)

    asyncio.run(exercise())

    assert recovery_stopped.is_set()
    assert controller.is_quiesced
    assert controller.active_permits == 0


def test_concurrent_quiesce_callers_share_one_completion() -> None:
    controller = OrchestrationQuiesceController()
    recovery_entered = asyncio.Event()
    release_recovery = asyncio.Event()
    calls = 0

    async def stop_recovery() -> None:
        nonlocal calls
        calls += 1
        recovery_entered.set()
        await release_recovery.wait()

    async def exercise() -> None:
        first = asyncio.create_task(controller.begin_quiesce(stop_recovery))
        await recovery_entered.wait()
        second = asyncio.create_task(controller.begin_quiesce(stop_recovery))
        await asyncio.sleep(0)

        assert not first.done()
        assert not second.done()
        assert calls == 1

        release_recovery.set()
        await asyncio.gather(first, second)

    asyncio.run(exercise())

    assert calls == 1
    assert controller.is_quiesced


def test_cancelling_one_quiesce_waiter_does_not_cancel_shared_completion() -> None:
    controller = OrchestrationQuiesceController()
    entered = Event()
    release = Event()
    recovery_calls = 0

    def admitted_work() -> None:
        with controller.permit():
            entered.set()
            assert release.wait(timeout=2)

    async def stop_recovery() -> None:
        nonlocal recovery_calls
        recovery_calls += 1

    async def exercise() -> None:
        worker = asyncio.create_task(asyncio.to_thread(admitted_work))
        assert await asyncio.to_thread(entered.wait, 2)
        leader = asyncio.create_task(controller.begin_quiesce(stop_recovery))
        assert await asyncio.to_thread(controller.wait_until_quiescing, 2)
        follower = asyncio.create_task(controller.begin_quiesce(stop_recovery))
        await asyncio.sleep(0)
        follower.cancel()
        with pytest.raises(asyncio.CancelledError):
            await follower

        release.set()
        await worker
        await asyncio.wait_for(leader, timeout=2)
        await controller.begin_quiesce(stop_recovery)

    asyncio.run(exercise())

    assert recovery_calls == 1
    assert controller.is_quiesced


@pytest.mark.parametrize("action", ["resume_sync", "node_claim", "tool_claim"])
def test_sync_claims_used_from_to_thread_observe_quiesce_latch(action: str) -> None:
    controller = OrchestrationQuiesceController()
    claims: list[str] = []

    async def exercise() -> str:
        await controller.begin_quiesce()

        def claim() -> None:
            with controller.permit():
                claims.append(action)

        with pytest.raises(OrchestrationQuiescingError) as error:
            await asyncio.to_thread(claim)
        return error.value.code

    assert asyncio.run(exercise()) == "orchestration_quiescing"
    assert claims == []
