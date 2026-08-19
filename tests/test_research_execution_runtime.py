from __future__ import annotations

import asyncio
import sqlite3
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

import agentmesh.routes.inbox as inbox_routes
from agentmesh.agent_runtime.settings import SkillOrchestrationMode
from agentmesh.app import app
from agentmesh.models import AgentRun, AgentRunStatus, User, now_utc
from agentmesh.research_orchestration.api import (
    ResearchExecuteRequest,
    ResearchOwnerScope,
)
from agentmesh.research_orchestration.artifacts import ArtifactStore
from agentmesh.research_orchestration.contracts import (
    AttemptStatus,
    ExecutionLease,
    ResearchGate,
    ResearchPhase,
    ResearchWorkflow,
    StepStatus,
)
from agentmesh.research_orchestration.execution import ExecutionEngine, ExecutionError
from agentmesh.research_orchestration.runtime import ResearchRuntime
from agentmesh.research_orchestration.workflow import ResearchWorkflowService
from agentmesh.routes.deps import current_user
from agentmesh.store import ResearchToolApprovalError, SQLiteStore
from tests.research_orchestration_testkit import compiled_competitive_plan

OWNER = ResearchOwnerScope(
    user_id="user_1",
    workspace_id="workspace_1",
    project_id="project_1",
)


class _UnusedPlanning:
    async def prepare_requirement(self, *_args: object, **_kwargs: object) -> object:
        raise AssertionError("execution tests must not enter planning")

    def compile_plan(self, *_args: object, **_kwargs: object) -> object:
        raise AssertionError("execution tests must not compile another plan")


class _SequentialIds:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def __call__(self, prefix: str) -> str:
        value = self.counts.get(prefix, 0) + 1
        self.counts[prefix] = value
        return f"{prefix}_{value}"


class _RecordingExecution:
    def __init__(self, *, block: bool = False) -> None:
        self.calls: list[str] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.block = block

    async def claim_and_run(self, attempt_id: str, *, token: str | None = None) -> None:
        del token
        self.calls.append(attempt_id)
        self.started.set()
        if self.block:
            await self.release.wait()


def _ready_execution_service(
    database: Any,
    *,
    approval_required: bool,
) -> tuple[SQLiteStore, ResearchWorkflowService, _RecordingExecution, AgentRun]:
    repository = SQLiteStore(database)
    requirement, plan = compiled_competitive_plan(
        "run_web_execute",
        approval_required=approval_required,
    )
    run = repository.save_agent_run(
        AgentRun(
            id=plan.run_id,
            thread_id="thread_web_execute",
            user_id=OWNER.user_id,
            workspace_id=OWNER.workspace_id,
            project_id=OWNER.project_id,
            input_text="对比 Figma 和 Miro 的证据与恢复能力",
            status=AgentRunStatus.PLANNING,
            orchestration_version="research-v2",
            orchestration_mode="execute",
        )
    )
    repository.add_research_requirement_version(requirement)
    repository.add_research_plan_version(plan)
    repository.create_research_workflow(
        ResearchWorkflow(
            run_id=run.id,
            phase=ResearchPhase.PLANNING,
            active_gate=ResearchGate.NONE,
            active_requirement_version_id=requirement.id,
            active_plan_version_id=plan.id,
        )
    )
    execution = _RecordingExecution()
    service = ResearchWorkflowService(
        repository,
        _UnusedPlanning(),
        execution,
        ArtifactStore(repository),
        id_factory=_SequentialIds(),
    )
    return repository, service, execution, run


async def _execute_with_approval(
    repository: SQLiteStore,
    service: ResearchWorkflowService,
    run: AgentRun,
) -> tuple[str, str, str]:
    await service.execute(
        run.id,
        ResearchExecuteRequest(expected_state_version=1),
        owner=OWNER,
        idempotency_key="execute-with-approval",
    )
    projection = service.get_projection(run.id, owner=OWNER)
    assert projection.tool_approval is not None
    assert projection.workflow.active_attempt_id is not None
    return (
        projection.workflow.active_attempt_id,
        projection.tool_approval.inbox_item_id,
        projection.tool_approval.call_id,
    )


def test_execute_atomically_opens_tool_approval_without_calling_provider(tmp_path) -> None:
    repository, service, execution, run = _ready_execution_service(
        tmp_path / "approval.sqlite3",
        approval_required=True,
    )

    attempt_id, inbox_item_id, call_id = asyncio.run(_execute_with_approval(repository, service, run))

    attempt = repository.get_research_attempt(attempt_id)
    workflow = repository.get_research_workflow(run.id)
    inbox = repository.get_inbox_item(inbox_item_id)
    assert execution.calls == []
    assert attempt is not None and attempt.status == AttemptStatus.PENDING
    assert workflow is not None and workflow.active_gate == ResearchGate.TOOL_APPROVAL
    assert inbox is not None and inbox.status == "open"
    assert inbox.metadata["call_id"] == call_id
    assert repository.list_recoverable_research_attempt_ids(now_utc()) == []


def test_approve_resumes_once_and_reject_atomically_terminates(tmp_path) -> None:
    approve_repository, approve_service, approve_execution, approve_run = _ready_execution_service(
        tmp_path / "approve.sqlite3",
        approval_required=True,
    )
    attempt_id, inbox_item_id, call_id = asyncio.run(
        _execute_with_approval(
            approve_repository,
            approve_service,
            approve_run,
        )
    )

    approved = approve_repository.resolve_research_tool_approval(
        inbox_item_id,
        owner_user_id=OWNER.user_id,
        action="approve",
        call_id=call_id,
    )
    assert approved.attempt_id == attempt_id

    async def resume() -> None:
        assert approve_service.resume_approved_attempt(attempt_id) is True
        await approve_service.wait_for_idle()

    asyncio.run(resume())
    assert approve_execution.calls == [attempt_id]
    assert approve_repository.get_research_workflow(approve_run.id).active_gate == ResearchGate.NONE
    with pytest.raises(ResearchToolApprovalError, match="no longer open"):
        approve_repository.resolve_research_tool_approval(
            inbox_item_id,
            owner_user_id=OWNER.user_id,
            action="approve",
            call_id=call_id,
        )

    reject_repository, reject_service, reject_execution, reject_run = _ready_execution_service(
        tmp_path / "reject.sqlite3",
        approval_required=True,
    )
    rejected_attempt_id, rejected_inbox_id, rejected_call_id = asyncio.run(
        _execute_with_approval(
            reject_repository,
            reject_service,
            reject_run,
        )
    )
    rejected = reject_repository.resolve_research_tool_approval(
        rejected_inbox_id,
        owner_user_id=OWNER.user_id,
        action="reject",
        call_id=rejected_call_id,
    )

    rejected_attempt = reject_repository.get_research_attempt(rejected_attempt_id)
    rejected_workflow = reject_repository.get_research_workflow(reject_run.id)
    rejected_run_state = reject_repository.get_agent_run(reject_run.id)
    assert rejected.attempt_id is None
    assert reject_execution.calls == []
    assert rejected_attempt is not None and rejected_attempt.status == AttemptStatus.CANCELLED
    assert all(
        reject_repository.get_research_step(rejected_attempt_id, number).status == StepStatus.CANCELLED
        for number in (1, 2)
    )
    assert rejected_workflow is not None and rejected_workflow.phase == ResearchPhase.TERMINAL
    assert rejected_run_state is not None and rejected_run_state.status == AgentRunStatus.REJECTED


def test_research_approval_http_route_schedules_from_the_request_event_loop(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, service, execution, run = _ready_execution_service(
        tmp_path / "approval-route.sqlite3",
        approval_required=True,
    )
    attempt_id, inbox_item_id, call_id = asyncio.run(
        _execute_with_approval(repository, service, run)
    )
    runtime = ResearchRuntime(
        repository,
        service,
        execution_enabled=True,
        mode_provider=lambda: SkillOrchestrationMode.EXECUTE,
    )
    user = User(
        id=OWNER.user_id,
        workspace_id=OWNER.workspace_id,
        default_project_id=OWNER.project_id,
        name="Research owner",
        role="user",
        personal_agent_id="agent_research_owner",
    )
    monkeypatch.setattr(inbox_routes, "store", repository)
    monkeypatch.setattr(app.state, "research_runtime", runtime, raising=False)
    app.dependency_overrides[current_user] = lambda: user
    try:
        response = TestClient(app).post(
            f"/api/inbox/{inbox_item_id}/resolve-tool-approval",
            params={"action": "approve", "call_id": call_id},
        )
    finally:
        app.dependency_overrides.pop(current_user, None)

    assert response.status_code == 200
    assert response.json()["attempt_id"] == attempt_id
    assert response.json()["scheduled"] is True
    assert execution.calls == [attempt_id]


def test_runtime_recovers_pending_on_start_and_expired_attempt_periodically(tmp_path) -> None:
    repository, original_service, original_execution, run = _ready_execution_service(
        tmp_path / "runtime-recovery.sqlite3",
        approval_required=True,
    )

    async def scenario() -> None:
        attempt_id, inbox_item_id, call_id = await _execute_with_approval(
            repository,
            original_service,
            run,
        )
        repository.resolve_research_tool_approval(
            inbox_item_id,
            owner_user_id=OWNER.user_id,
            action="approve",
            call_id=call_id,
        )
        assert original_execution.calls == []

        startup_execution = _RecordingExecution(block=True)
        startup_service = ResearchWorkflowService(
            repository,
            _UnusedPlanning(),
            startup_execution,
            ArtifactStore(repository),
        )
        startup_runtime = ResearchRuntime(
            repository,
            startup_service,
            execution_enabled=True,
            mode_provider=lambda: SkillOrchestrationMode.EXECUTE,
            reconcile_interval=timedelta(milliseconds=20),
        )
        await startup_runtime.start()
        await asyncio.wait_for(startup_execution.started.wait(), timeout=1)
        await asyncio.sleep(0.05)
        assert startup_execution.calls == [attempt_id]
        startup_execution.release.set()
        await startup_runtime.shutdown()

        claimed = repository.claim_research_attempt(
            attempt_id,
            owner="abandoned-worker",
            token="abandoned-token",
            now=now_utc(),
            lease_ttl=timedelta(milliseconds=1),
        )
        assert claimed is not None
        await asyncio.sleep(0.01)

        mode = [SkillOrchestrationMode.PREVIEW]
        periodic_execution = _RecordingExecution(block=True)
        periodic_service = ResearchWorkflowService(
            repository,
            _UnusedPlanning(),
            periodic_execution,
            ArtifactStore(repository),
        )
        periodic_runtime = ResearchRuntime(
            repository,
            periodic_service,
            execution_enabled=True,
            mode_provider=lambda: mode[0],
            reconcile_interval=timedelta(milliseconds=10),
        )
        await periodic_runtime.start()
        assert periodic_execution.calls == []
        mode[0] = SkillOrchestrationMode.EXECUTE
        await asyncio.wait_for(periodic_execution.started.wait(), timeout=1)
        await asyncio.sleep(0.03)
        assert periodic_execution.calls == [attempt_id]
        periodic_execution.release.set()
        await periodic_runtime.shutdown()

    asyncio.run(scenario())


def test_runtime_fails_attempt_that_crossed_its_frozen_deadline_before_restart(tmp_path) -> None:
    repository, original_service, _original_execution, run = _ready_execution_service(
        tmp_path / "runtime-deadline.sqlite3",
        approval_required=True,
    )

    async def scenario() -> None:
        attempt_id, inbox_item_id, call_id = await _execute_with_approval(
            repository,
            original_service,
            run,
        )
        repository.resolve_research_tool_approval(
            inbox_item_id,
            owner_user_id=OWNER.user_id,
            action="approve",
            call_id=call_id,
        )
        attempt = repository.get_research_attempt(attempt_id)
        assert attempt is not None and attempt.status == AttemptStatus.PENDING
        expired = attempt.model_copy(update={"deadline_at": attempt.created_at + timedelta(milliseconds=1)})
        with sqlite3.connect(repository.db_path) as connection:
            connection.execute(
                "UPDATE research_attempts SET payload = ? WHERE id = ?",
                (expired.model_dump_json(), attempt.id),
            )

        restarted_execution = _RecordingExecution()
        restarted_service = ResearchWorkflowService(
            repository,
            _UnusedPlanning(),
            restarted_execution,
            ArtifactStore(repository),
        )
        runtime = ResearchRuntime(
            repository,
            restarted_service,
            execution_enabled=True,
            mode_provider=lambda: SkillOrchestrationMode.EXECUTE,
        )
        await runtime.start()
        await runtime.shutdown()

        closed_attempt = repository.get_research_attempt(attempt.id)
        closed_workflow = repository.get_research_workflow(run.id)
        closed_run = repository.get_agent_run(run.id)
        assert restarted_execution.calls == []
        assert closed_attempt is not None and closed_attempt.status == AttemptStatus.FAILED
        assert all(
            repository.get_research_step(attempt.id, number).status == StepStatus.FAILED
            for number in (1, 2)
        )
        assert closed_workflow is not None and closed_workflow.phase == ResearchPhase.TERMINAL
        assert closed_run is not None and closed_run.status == AgentRunStatus.FAILED
        assert closed_run.error_code == "research_execution_deadline_exceeded"
        event_types = [event.event_type for event in repository.list_agent_run_events(run.id)]
        assert "research_attempt_failed" in event_types
        assert "run_failed" in event_types

    asyncio.run(scenario())


class _HeartbeatRepository:
    def __init__(self) -> None:
        self.calls = 0

    def heartbeat_research_attempt(self, *_args: object, **_kwargs: object) -> object:
        self.calls += 1
        return object()


class _HeartbeatEngine(ExecutionEngine):
    def __init__(self, repository: _HeartbeatRepository) -> None:
        super().__init__(
            repository,  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            lease_ttl=timedelta(milliseconds=50),
            heartbeat_interval=timedelta(milliseconds=10),
        )
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    def claim(self, attempt_id: str, *, token: str) -> ExecutionLease:
        del attempt_id
        return ExecutionLease(owner=self.worker_id, token=token, fencing_epoch=1)

    async def run(self, attempt_id: str, lease: ExecutionLease) -> Any:
        del attempt_id, lease
        self.started.set()
        await self.release.wait()
        return object()


def test_engine_heartbeats_while_running_and_off_blocks_claim() -> None:
    async def heartbeat_scenario() -> None:
        repository = _HeartbeatRepository()
        engine = _HeartbeatEngine(repository)
        task = asyncio.create_task(engine.claim_and_run("attempt_heartbeat"))
        await engine.started.wait()
        await asyncio.sleep(0.035)
        engine.release.set()
        await task
        assert repository.calls >= 2

    asyncio.run(heartbeat_scenario())

    class _ClaimForbiddenRepository:
        def claim_research_attempt(self, *_args: object, **_kwargs: object) -> object:
            raise AssertionError("off mode must stop before the persistent claim")

    engine = ExecutionEngine(
        _ClaimForbiddenRepository(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        execution_allowed=lambda: False,
    )
    with pytest.raises(ExecutionError, match="execution_disabled"):
        engine.claim("attempt_off", token="lease_off")
