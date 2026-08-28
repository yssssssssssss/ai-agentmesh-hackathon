from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from agentmesh.deepsearch.recovery import DeepSearchRecoveryCoordinator
from agentmesh.models import AgentPlanningMode, AgentRun, AgentRunStatus

NOW = datetime(2026, 8, 27, 8, 0, tzinfo=UTC)


def _run(
    run_id: str,
    status: AgentRunStatus,
    *,
    deepsearch: bool = True,
    orchestration_mode: str = "execute",
) -> AgentRun:
    return AgentRun(
        id=run_id,
        thread_id=f"thread_{run_id}",
        user_id="user_1",
        workspace_id="workspace_1",
        project_id="project_1",
        input_text="research",
        status=status,
        planning_mode=(
            AgentPlanningMode.DEEPSEARCH if deepsearch else AgentPlanningMode.STANDARD
        ),
        orchestration_version="v1",
        orchestration_mode=orchestration_mode,
        absolute_expires_at=NOW + timedelta(days=1) if deepsearch else None,
    )


class _Repository:
    def __init__(self, runs: list[AgentRun], *, expired: set[str] | None = None) -> None:
        self.runs = runs
        self.expired = expired or set()
        self.expiry_calls: list[str] = []

    def list_recoverable_deepsearch_runs(self) -> list[AgentRun]:
        return [run.model_copy(deep=True) for run in self.runs]

    def expire_deepsearch_run_if_needed(
        self,
        run_id: str,
        *,
        user_id: str,
        checked_at: datetime | None = None,
    ) -> AgentRun | None:
        assert user_id == "user_1"
        assert checked_at == NOW
        self.expiry_calls.append(run_id)
        run = next(item for item in self.runs if item.id == run_id).model_copy(deep=True)
        if run_id in self.expired:
            run.status = AgentRunStatus.CANCELLED
            run.error_code = "deepsearch_run_expired"
        return run


class _Runtime:
    def __init__(self, *, failing: set[str] | None = None) -> None:
        self.calls: list[str] = []
        self.failing = failing or set()

    async def recover_deepsearch_run(self, run_id: str) -> AgentRun | None:
        self.calls.append(run_id)
        if run_id in self.failing:
            raise RuntimeError("transient")
        return None


def test_recover_once_expires_waiting_runs_and_schedules_only_computation() -> None:
    repository = _Repository(
        [
            _run("planning", AgentRunStatus.PLANNING),
            _run("running", AgentRunStatus.RUNNING),
            _run("waiting", AgentRunStatus.WAITING_CLARIFICATION),
            _run("expired", AgentRunStatus.RUNNING),
            _run("complete", AgentRunStatus.COMPLETED),
            _run("standard", AgentRunStatus.RUNNING, deepsearch=False),
            _run("preview", AgentRunStatus.RUNNING, orchestration_mode="preview"),
        ],
        expired={"expired"},
    )
    runtime = _Runtime()
    coordinator = DeepSearchRecoveryCoordinator(
        repository,
        runtime,
        clock=lambda: NOW,
    )

    async def exercise() -> int:
        scheduled = await coordinator.recover_once()
        await asyncio.sleep(0)
        return scheduled

    recovered = asyncio.run(exercise())

    assert recovered == 2
    assert repository.expiry_calls == [
        "planning",
        "running",
        "waiting",
        "expired",
        "preview",
    ]
    assert runtime.calls == ["planning", "running"]


def test_recover_once_isolates_one_run_failure() -> None:
    repository = _Repository(
        [
            _run("first", AgentRunStatus.PLANNING),
            _run("second", AgentRunStatus.RUNNING),
        ]
    )
    runtime = _Runtime(failing={"first"})
    coordinator = DeepSearchRecoveryCoordinator(
        repository,
        runtime,
        clock=lambda: NOW,
    )

    async def exercise() -> int:
        scheduled = await coordinator.recover_once()
        await asyncio.sleep(0)
        return scheduled

    recovered = asyncio.run(exercise())

    assert recovered == 2
    assert runtime.calls == ["first", "second"]


def test_start_runs_initial_scan_and_stop_is_prompt() -> None:
    repository = _Repository([_run("planning", AgentRunStatus.PLANNING)])
    runtime = _Runtime()
    coordinator = DeepSearchRecoveryCoordinator(
        repository,
        runtime,
        interval_seconds=60,
        clock=lambda: NOW,
    )

    async def exercise() -> None:
        await coordinator.start()
        await asyncio.sleep(0)
        await asyncio.wait_for(coordinator.stop(), timeout=1)

    asyncio.run(exercise())

    assert runtime.calls == ["planning"]


def test_recovery_interval_must_be_positive() -> None:
    with pytest.raises(ValueError, match="interval"):
        DeepSearchRecoveryCoordinator(_Repository([]), _Runtime(), interval_seconds=0)


def test_repeated_scan_keeps_only_one_managed_task_per_run() -> None:
    repository = _Repository([_run("running", AgentRunStatus.RUNNING)])

    class BlockingRuntime:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def recover_deepsearch_run(self, run_id: str) -> AgentRun | None:
            self.calls.append(run_id)
            self.started.set()
            await self.release.wait()
            return None

    async def exercise() -> tuple[int, int, list[str]]:
        runtime = BlockingRuntime()
        coordinator = DeepSearchRecoveryCoordinator(
            repository,
            runtime,
            clock=lambda: NOW,
        )
        first = await coordinator.recover_once()
        await runtime.started.wait()
        second = await coordinator.recover_once()
        calls = list(runtime.calls)
        runtime.release.set()
        await asyncio.sleep(0)
        await coordinator.stop()
        return first, second, calls

    first, second, calls = asyncio.run(exercise())

    assert first == 1
    assert second == 0
    assert calls == ["running"]


def test_application_lifespan_starts_recovery_after_general_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agentmesh.app as application

    events: list[str] = []

    class RecordingCoordinator:
        def __init__(self, _repository: object, _runtime: object) -> None:
            events.append("coordinator_created")

        async def start(self) -> None:
            events.append("coordinator_started")

        async def stop(self) -> None:
            events.append("coordinator_stopped")

    async def no_op() -> None:
        return None

    monkeypatch.setattr(
        application,
        "initialize_application_data",
        lambda _repository: events.append("general_reconciled"),
    )
    monkeypatch.setattr(application, "DeepSearchRecoveryCoordinator", RecordingCoordinator)
    for name in (
        "start_auto_post_worker",
        "start_daily_memory_worker",
        "start_research_dispatch_worker",
        "start_market_publish_worker",
        "start_market_scout_worker",
        "stop_market_scout_worker",
        "stop_market_publish_worker",
        "stop_research_dispatch_worker",
        "stop_daily_memory_worker",
        "stop_auto_post_worker",
    ):
        monkeypatch.setattr(application, name, no_op)
    monkeypatch.setattr(application.ingestion_service, "shutdown", lambda: None)

    async def exercise() -> None:
        async with application.lifespan(application.app):
            assert events[:3] == [
                "general_reconciled",
                "coordinator_created",
                "coordinator_started",
            ]

    asyncio.run(exercise())

    assert events[-1] == "coordinator_stopped"
