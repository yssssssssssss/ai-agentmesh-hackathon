import asyncio
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from agentmesh.models import MemoryLayer, UserMemoryItem, memory_date_for
from agentmesh.routes import memory as memory_route
from agentmesh.routes.memory import daily_summary_target_date, next_daily_memory_run
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.store import store


def test_memory_date_uses_the_beijing_calendar_day() -> None:
    instant = datetime(2026, 8, 24, 16, 30, tzinfo=UTC)

    assert memory_date_for(instant) == date(2026, 8, 25)


def test_daily_summary_runs_at_0005_and_summarizes_the_previous_beijing_day() -> None:
    now = datetime(2026, 8, 24, 15, 0, tzinfo=UTC)

    next_run = next_daily_memory_run(now)

    assert next_run == datetime(2026, 8, 25, 0, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert daily_summary_target_date(next_run) == date(2026, 8, 24)


def test_worker_waits_until_the_next_fixed_daily_run(monkeypatch: pytest.MonkeyPatch) -> None:
    delays: list[float] = []

    class WorkerStopped(Exception):
        pass

    async def stop_at_first_sleep(delay: float) -> None:
        delays.append(delay)
        raise WorkerStopped

    monkeypatch.setattr(memory_route.asyncio, "sleep", stop_at_first_sleep)

    with pytest.raises(WorkerStopped):
        asyncio.run(memory_route.daily_memory_worker_loop())

    assert len(delays) == 1
    assert 0 < delays[0] <= 24 * 60 * 60
    assert str(memory_route.daily_summary_worker_state["next_run_at"]).endswith("00:05:00+08:00")


def test_worker_start_catches_up_the_previous_day(monkeypatch: pytest.MonkeyPatch) -> None:
    store.reset()
    ensure_base_workspace_data(store)
    store.save_user(USER)
    target_date = memory_date_for() - timedelta(days=1)
    store.add_user_memory_item(
        UserMemoryItem(
            user_id=USER.id,
            layer=MemoryLayer.SHORT_TERM,
            title="昨日工作",
            summary="昨日完成了记忆机制核对。",
            source_kind="test",
            memory_date=target_date,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
        )
    )
    monkeypatch.setattr(memory_route, "DAILY_SUMMARY_WORKER_ENABLED", True)

    async def scenario() -> None:
        await memory_route.start_daily_memory_worker()
        try:
            summaries = store.list_user_memory_items(
                USER.id,
                MemoryLayer.SHORT_TERM,
                USER.default_project_id,
                target_date,
                "daily_summary",
            )
            assert len(summaries) == 1
            assert "昨日工作" in summaries[0].summary
        finally:
            await memory_route.stop_daily_memory_worker()

    try:
        asyncio.run(scenario())
    finally:
        store.reset()
