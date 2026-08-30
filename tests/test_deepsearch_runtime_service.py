from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest
from agents.testing import ScriptedModel

import agentmesh.routes.chat as chat_routes
from agentmesh.agent_run_identity import agent_run_create_request_hash
from agentmesh.agent_runtime.service import (
    _DEEPSEARCH_PLANNING_MODEL_MAXIMA,
    AgentRuntimeService,
    _BudgetedDeepSearchModel,
    _BudgetedPlanningModel,
)
from agentmesh.agent_runtime.settings import SkillOrchestrationMode
from agentmesh.deepsearch.contracts import DeepSearchStateResponse
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    ChatThread,
    DeepSearchBudgetUsageV1,
    DeepSearchBudgetV1,
    SkillDefinition,
    SkillIntent,
    SkillOrchestrationRequestMode,
    SkillPlan,
    SkillPlanNode,
    SkillPlanNodeStatus,
    SkillPlanStatus,
    SkillSourceScope,
    now_utc,
)
from agentmesh.routes.deepsearch import get_deepsearch_planning_service
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.skill_runtime.executor import NodePause, PlanExecutionOutcome
from agentmesh.store import SQLiteStore


class _RecordingPlanningService:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[str] = []

    async def refine_initial(self, run: AgentRun) -> DeepSearchStateResponse:
        self.calls.append(run.id)
        if self.error is not None:
            raise self.error
        return DeepSearchStateResponse(run=run, active_requirement=None)


def _runtime_fixture(
    tmp_path,
    *,
    planning_service: _RecordingPlanningService | None = None,
) -> tuple[SQLiteStore, AgentRuntimeService, ChatThread]:
    repository = SQLiteStore(tmp_path / "deepsearch-runtime.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    thread = repository.add_chat_thread(
        ChatThread(
            id="thread_deepsearch_runtime",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="DeepSearch Runtime",
        )
    )
    runtime = AgentRuntimeService(
        repository,
        model=ScriptedModel([]),
        enabled=True,
        deepsearch_planning_service=planning_service,
    )
    return repository, runtime, thread


def _create_hash(*, thread_id: str, client_turn_id: str, content: str) -> str:
    return agent_run_create_request_hash(
        user_id=USER.id,
        thread_id=thread_id,
        client_turn_id=client_turn_id,
        content=content,
        skill_name=None,
        orchestration_mode=SkillOrchestrationRequestMode.AUTO,
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        retry_of_run_id=None,
    )


def _create_budgeted_run(
    tmp_path,
    *,
    suffix: str,
) -> tuple[SQLiteStore, AgentRun]:
    planning = _RecordingPlanningService()
    repository, runtime, thread = _runtime_fixture(tmp_path, planning_service=planning)
    content = f"Research {suffix}"
    client_turn_id = f"turn_{suffix}"
    run = asyncio.run(
        runtime.start_deepsearch(
            content=content,
            user=USER,
            thread_id=thread.id,
            history=[],
            client_turn_id=client_turn_id,
            mode=SkillOrchestrationMode.EXECUTE,
            create_request_hash=_create_hash(
                thread_id=thread.id,
                client_turn_id=client_turn_id,
                content=content,
            ),
        )
    )
    return repository, run


class _BudgetProbeModel:
    def __init__(
        self,
        repository: SQLiteStore,
        run_id: str,
        *,
        error: Exception | None = None,
        total_tokens: int = 17,
    ) -> None:
        self.repository = repository
        self.run_id = run_id
        self.error = error
        self.total_tokens = total_tokens
        self.observed_reservations: list[tuple[str, int]] = []

    async def get_response(self, *_args: object, **_kwargs: object):
        run = self.repository.get_agent_run(self.run_id)
        assert run is not None
        assert run.deepsearch_budget is not None
        reservation = run.deepsearch_budget.reservations[-1]
        self.observed_reservations.append(
            (reservation.status, reservation.physical_attempt)
        )
        if self.error is not None:
            raise self.error
        return SimpleNamespace(usage=SimpleNamespace(total_tokens=self.total_tokens))


class _StreamingBudgetProbeModel:
    def __init__(
        self,
        repository: SQLiteStore,
        run_id: str,
        *,
        events: list[object] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.repository = repository
        self.run_id = run_id
        self.events = events or []
        self.error = error
        self.observed_reservations: list[tuple[str, int]] = []

    async def stream_response(self, *_args: object, **_kwargs: object):
        run = self.repository.get_agent_run(self.run_id)
        assert run is not None
        assert run.deepsearch_budget is not None
        reservation = run.deepsearch_budget.reservations[-1]
        self.observed_reservations.append(
            (reservation.status, reservation.physical_attempt)
        )
        if self.error is not None:
            raise self.error
        for event in self.events:
            yield event


async def _collect_stream(model: _BudgetedDeepSearchModel, input_value: str) -> list[object]:
    return [event async for event in model.stream_response("system", input_value)]


def test_start_deepsearch_creates_one_v1_run_and_replay_does_not_repeat_side_effects(tmp_path) -> None:
    planning = _RecordingPlanningService()
    repository, runtime, thread = _runtime_fixture(tmp_path, planning_service=planning)
    content = "Research the collaboration software market"
    client_turn_id = "turn_deepsearch_runtime"
    kwargs = {
        "content": content,
        "user": USER,
        "thread_id": thread.id,
        "history": [],
        "client_turn_id": client_turn_id,
        "mode": SkillOrchestrationMode.EXECUTE,
        "create_request_hash": _create_hash(
            thread_id=thread.id,
            client_turn_id=client_turn_id,
            content=content,
        ),
    }

    created = asyncio.run(runtime.start_deepsearch(**kwargs))
    replayed = asyncio.run(runtime.start_deepsearch(**kwargs))

    assert replayed.id == created.id
    assert created.status is AgentRunStatus.PLANNING
    assert created.planning_mode is AgentPlanningMode.DEEPSEARCH
    assert created.orchestration_version == "v1"
    assert created.orchestration_mode == "execute"
    assert created.requested_orchestration_mode is SkillOrchestrationRequestMode.AUTO
    assert created.deadline_at is None
    assert created.absolute_expires_at == created.created_at + timedelta(days=7)
    assert created.deepsearch_budget == DeepSearchBudgetV1()
    assert planning.calls == [created.id]
    assert [message.content for message in repository.list_thread_messages(thread.id)] == [content]


def test_budgeted_planning_model_reserves_before_provider_and_settles_usage(tmp_path) -> None:
    repository, run = _create_budgeted_run(tmp_path, suffix="budgeted_planning_success")
    model = _BudgetProbeModel(repository, run.id, total_tokens=23)
    budgeted = _BudgetedPlanningModel(
        repository=repository,
        run_id=run.id,
        model=model,  # type: ignore[arg-type]
        logical_operation_key="planning:test-success",
    )

    response = asyncio.run(budgeted.get_response())

    assert response.usage.total_tokens == 23
    assert model.observed_reservations == [("reserved", 1)]
    persisted = repository.get_agent_run(run.id)
    assert persisted is not None
    assert persisted.deepsearch_budget is not None
    reservation = persisted.deepsearch_budget.reservations[0]
    assert reservation.status == "settled"
    assert reservation.actual_usage is not None
    assert reservation.actual_usage.llm_calls == 1
    assert reservation.actual_usage.tokens == 23
    assert 0 <= reservation.actual_usage.active_seconds <= 120


def test_budgeted_planning_model_settles_maxima_when_provider_fails(tmp_path) -> None:
    repository, run = _create_budgeted_run(tmp_path, suffix="budgeted_planning_failure")
    model = _BudgetProbeModel(repository, run.id, error=RuntimeError("provider failed"))
    budgeted = _BudgetedPlanningModel(
        repository=repository,
        run_id=run.id,
        model=model,  # type: ignore[arg-type]
        logical_operation_key="planning:test-failure",
    )

    with pytest.raises(RuntimeError, match="provider failed"):
        asyncio.run(budgeted.get_response())

    assert model.observed_reservations == [("reserved", 1)]
    persisted = repository.get_agent_run(run.id)
    assert persisted is not None
    assert persisted.deepsearch_budget is not None
    reservation = persisted.deepsearch_budget.reservations[0]
    assert reservation.status == "settled"
    assert reservation.actual_usage == _DEEPSEARCH_PLANNING_MODEL_MAXIMA


def test_budgeted_planning_model_bills_unsettled_attempt_before_retry(tmp_path) -> None:
    repository, run = _create_budgeted_run(tmp_path, suffix="budgeted_planning_retry")
    first = repository.reserve_deepsearch_budget(
        run_id=run.id,
        expected_budget_version=1,
        logical_operation_key="planning:test-retry",
        invocation_key="planning:test-retry:attempt:1",
        physical_attempt=1,
        resource_maxima=_DEEPSEARCH_PLANNING_MODEL_MAXIMA,
        scope="standard",
    )
    assert first.reservation.status == "reserved"
    model = _BudgetProbeModel(repository, run.id, total_tokens=11)
    budgeted = _BudgetedPlanningModel(
        repository=repository,
        run_id=run.id,
        model=model,  # type: ignore[arg-type]
        logical_operation_key="planning:test-retry",
    )

    asyncio.run(budgeted.get_response())

    assert model.observed_reservations == [("reserved", 2)]
    persisted = repository.get_agent_run(run.id)
    assert persisted is not None
    assert persisted.deepsearch_budget is not None
    first_attempt, second_attempt = persisted.deepsearch_budget.reservations
    assert first_attempt.actual_usage == _DEEPSEARCH_PLANNING_MODEL_MAXIMA
    assert second_attempt.status == "settled"
    assert second_attempt.actual_usage is not None
    assert second_attempt.actual_usage == DeepSearchBudgetUsageV1(
        active_seconds=second_attempt.actual_usage.active_seconds,
        llm_calls=1,
        tokens=11,
    )


def test_budgeted_deepsearch_stream_reserves_before_provider_and_settles_usage(tmp_path) -> None:
    repository, run = _create_budgeted_run(tmp_path, suffix="budgeted_stream_success")
    completed = SimpleNamespace(
        type="response.completed",
        response=SimpleNamespace(usage=SimpleNamespace(total_tokens=29)),
    )
    model = _StreamingBudgetProbeModel(repository, run.id, events=[completed])
    budgeted = _BudgetedDeepSearchModel(
        repository=repository,
        run_id=run.id,
        model=model,  # type: ignore[arg-type]
        logical_operation_key="standard:node:test-stream",
    )

    events = asyncio.run(_collect_stream(budgeted, "turn one"))

    assert events == [completed]
    assert model.observed_reservations == [("reserved", 1)]
    persisted = repository.get_agent_run(run.id)
    assert persisted is not None and persisted.deepsearch_budget is not None
    reservation = persisted.deepsearch_budget.reservations[0]
    assert reservation.status == "settled"
    assert reservation.actual_usage is not None
    assert reservation.actual_usage.tokens == 29
    assert reservation.actual_usage.llm_calls == 1


@pytest.mark.parametrize(
    ("events", "provider_error", "error_match"),
    [
        ([], RuntimeError("stream failed"), "stream failed"),
        (
            [SimpleNamespace(type="response.completed", response=SimpleNamespace(usage=None))],
            None,
            "deepsearch_model_usage_missing",
        ),
    ],
)
def test_budgeted_deepsearch_stream_settles_maxima_on_failure_or_missing_usage(
    tmp_path,
    events: list[object],
    provider_error: Exception | None,
    error_match: str,
) -> None:
    repository, run = _create_budgeted_run(
        tmp_path,
        suffix=f"budgeted_stream_failure_{error_match}",
    )
    model = _StreamingBudgetProbeModel(
        repository,
        run.id,
        events=events,
        error=provider_error,
    )
    budgeted = _BudgetedDeepSearchModel(
        repository=repository,
        run_id=run.id,
        model=model,  # type: ignore[arg-type]
        logical_operation_key="standard:node:test-stream-failure",
    )

    with pytest.raises(RuntimeError, match=error_match):
        asyncio.run(_collect_stream(budgeted, "turn one"))

    assert model.observed_reservations == [("reserved", 1)]
    persisted = repository.get_agent_run(run.id)
    assert persisted is not None and persisted.deepsearch_budget is not None
    assert persisted.deepsearch_budget.reservations[0].actual_usage == (
        _DEEPSEARCH_PLANNING_MODEL_MAXIMA
    )


def test_budgeted_deepsearch_model_uses_distinct_keys_for_distinct_requests(tmp_path) -> None:
    repository, run = _create_budgeted_run(tmp_path, suffix="budgeted_request_keys")
    model = _BudgetProbeModel(repository, run.id, total_tokens=3)
    budgeted = _BudgetedDeepSearchModel(
        repository=repository,
        run_id=run.id,
        model=model,  # type: ignore[arg-type]
        logical_operation_key="standard:node:stable-stage",
        request_scoped=True,
    )

    asyncio.run(budgeted.get_response("system", "turn one"))
    asyncio.run(budgeted.get_response("system", "turn two"))

    persisted = repository.get_agent_run(run.id)
    assert persisted is not None and persisted.deepsearch_budget is not None
    reservations = persisted.deepsearch_budget.reservations
    assert len(reservations) == 2
    assert len({item.logical_operation_key for item in reservations}) == 2
    assert all(item.invocation_key == f"{item.logical_operation_key}:attempt:1" for item in reservations)


def test_standard_run_uses_original_model_without_budget_writes(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, runtime, thread = _runtime_fixture(tmp_path)
    model = ScriptedModel([])
    run = AgentRun(
        id="run_standard_unbudgeted",
        thread_id=thread.id,
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        input_text="hello",
        status=AgentRunStatus.RUNNING,
        planning_mode=AgentPlanningMode.STANDARD,
    )
    budget_writes: list[object] = []
    monkeypatch.setattr(
        repository,
        "reserve_deepsearch_budget",
        lambda **kwargs: budget_writes.append(kwargs),
    )

    selected = runtime._budgeted_model_for_run(
        run=run,
        model=model,
        scope="standard",
        stage="node",
        identity={"turn": 1},
        timeout_seconds=30,
    )

    assert selected is model
    assert budget_writes == []


def test_start_deepsearch_planning_failure_uses_dedicated_terminal_transition(tmp_path) -> None:
    planning = _RecordingPlanningService(ValueError("invalid Requirement"))
    repository, runtime, thread = _runtime_fixture(tmp_path, planning_service=planning)
    content = "Research a market"
    client_turn_id = "turn_deepsearch_failure"

    with pytest.raises(ValueError, match="invalid Requirement"):
        asyncio.run(
            runtime.start_deepsearch(
                content=content,
                user=USER,
                thread_id=thread.id,
                history=[],
                client_turn_id=client_turn_id,
                mode=SkillOrchestrationMode.EXECUTE,
                create_request_hash=_create_hash(
                    thread_id=thread.id,
                    client_turn_id=client_turn_id,
                    content=content,
                ),
            )
        )

    failed = repository.get_agent_run_by_client_turn(USER.id, client_turn_id)
    assert failed is not None
    assert failed.status is AgentRunStatus.FAILED
    assert failed.error_code == "deepsearch_planning_failed"
    assert failed.plan_id is None


@pytest.mark.parametrize("enabled,mode", [(False, SkillOrchestrationMode.EXECUTE), (True, SkillOrchestrationMode.PREVIEW)])
def test_start_deepsearch_rejects_unavailable_runtime_before_writes(
    tmp_path,
    enabled: bool,
    mode: SkillOrchestrationMode,
) -> None:
    planning = _RecordingPlanningService()
    repository, _runtime, thread = _runtime_fixture(tmp_path, planning_service=planning)
    runtime = AgentRuntimeService(
        repository,
        model=ScriptedModel([]),
        enabled=enabled,
        deepsearch_planning_service=planning,
    )
    content = "Research a market"
    client_turn_id = f"turn_deepsearch_reject_{enabled}_{mode.value}"

    with pytest.raises(RuntimeError):
        asyncio.run(
            runtime.start_deepsearch(
                content=content,
                user=USER,
                thread_id=thread.id,
                history=[],
                client_turn_id=client_turn_id,
                mode=mode,
                create_request_hash=_create_hash(
                    thread_id=thread.id,
                    client_turn_id=client_turn_id,
                    content=content,
                ),
            )
        )

    assert repository.get_agent_run_by_client_turn(USER.id, client_turn_id) is None
    assert repository.list_thread_messages(thread.id) == []
    assert planning.calls == []


def test_deepsearch_route_resolves_the_runtime_owned_planning_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = object()
    runtime = SimpleNamespace(deepsearch_planning_service=sentinel)
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)

    assert get_deepsearch_planning_service() is sentinel


def test_deepsearch_pause_ttl_is_capped_by_absolute_expiry(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repository, runtime, _thread = _runtime_fixture(tmp_path)
    absolute_expires_at = now_utc() + timedelta(minutes=5)
    run = AgentRun(
        id="run_pause_absolute_cap",
        thread_id="thread_pause_absolute_cap",
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        input_text="research",
        status=AgentRunStatus.RUNNING,
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        orchestration_version="v1",
        orchestration_mode="execute",
        absolute_expires_at=absolute_expires_at,
        deepsearch_budget=DeepSearchBudgetV1(),
    )
    node = SkillPlanNode(
        id="node_pause_absolute_cap",
        skill_id="skill_pause_absolute_cap",
        skill_version="1",
        skill_content_hash="a" * 64,
        reason="research",
        attempt=1,
        status=SkillPlanNodeStatus.RUNNING,
    )
    plan = SkillPlan(
        id="plan_pause_absolute_cap",
        run_id=run.id,
        status=SkillPlanStatus.RUNNING,
        intent=SkillIntent(goal="research"),
        candidate_skill_ids=[node.skill_id],
        nodes=[node],
        planning_mode=AgentPlanningMode.DEEPSEARCH,
    )
    outcome = PlanExecutionOutcome(
        plan=plan,
        run=run,
        pause=NodePause(
            sdk_state={},
            interruptions=({"call_id": "call_1"},),
            grant_snapshot_ids=(),
        ),
        paused_node_id=node.id,
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(runtime.repository, "get_agent_run", lambda _run_id: run)

    def capture_pause(**kwargs: object):
        captured.update(kwargs)
        return plan, run, node

    monkeypatch.setattr(runtime.repository, "pause_skill_plan_node_and_run", capture_pause)

    runtime._persist_skill_plan_pause(outcome, user=USER)

    paused_state = captured["paused_state"]
    assert isinstance(paused_state, dict)
    assert paused_state["expires_at"] == absolute_expires_at.isoformat()


def test_invalid_deepsearch_pause_kind_fails_before_model_selection(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repository, runtime, _thread = _runtime_fixture(tmp_path)
    run = AgentRun(
        id="run_invalid_deepsearch_pause",
        thread_id="thread_invalid_deepsearch_pause",
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        input_text="research",
        status=AgentRunStatus.WAITING_APPROVAL,
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        orchestration_version="v1",
        orchestration_mode="execute",
        paused_state={"kind": "sdk_state"},
        absolute_expires_at=now_utc() + timedelta(days=1),
        deepsearch_budget=DeepSearchBudgetV1(),
    )
    monkeypatch.setattr(runtime.repository, "get_agent_run", lambda _run_id: run)
    monkeypatch.setattr(
        runtime.repository,
        "expire_deepsearch_run_if_needed",
        lambda _run_id, **_kwargs: run,
    )
    monkeypatch.setattr(
        runtime,
        "_select_model",
        lambda _user: (_ for _ in ()).throw(AssertionError("model must not be selected")),
    )

    with pytest.raises(RuntimeError, match="deepsearch_recovery_state_invalid"):
        asyncio.run(runtime.resume(run.id, user=USER, decisions={"call_1": True}))


def test_cancelled_resume_after_claim_cancels_the_run_tree(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repository, runtime, _thread = _runtime_fixture(tmp_path)
    node = SkillPlanNode(
        id="node_cancelled_resume",
        skill_id="skill_cancelled_resume",
        skill_version="1",
        skill_content_hash="a" * 64,
        reason="research",
        status=SkillPlanNodeStatus.WAITING_TOOL_APPROVAL,
        attempt=1,
    )
    plan = SkillPlan(
        id="plan_cancelled_resume",
        run_id="run_cancelled_resume",
        status=SkillPlanStatus.RUNNING,
        intent=SkillIntent(goal="research"),
        candidate_skill_ids=[node.skill_id],
        nodes=[node],
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        requirement_version_id="requirement_cancelled_resume",
    )
    paused = {
        "kind": "skill_plan_node",
        "plan_id": plan.id,
        "node_id": node.id,
        "skill_id": node.skill_id,
        "skill_content_hash": node.skill_content_hash,
        "grant_snapshot_ids": [],
        "sdk_state": {},
        "expires_at": (now_utc() + timedelta(hours=1)).isoformat(),
    }
    waiting = AgentRun(
        id=plan.run_id,
        thread_id="thread_cancelled_resume",
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        input_text="research",
        status=AgentRunStatus.WAITING_APPROVAL,
        plan_id=plan.id,
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        orchestration_version="v1",
        orchestration_mode="execute",
        paused_state=paused,
        absolute_expires_at=now_utc() + timedelta(days=1),
        deepsearch_budget=DeepSearchBudgetV1(),
    )
    claimed = waiting.model_copy(update={"status": AgentRunStatus.RUNNING})
    current = {"run": waiting}
    cancelled: list[str] = []
    skill = SkillDefinition(
        id=node.skill_id,
        name="cancelled-resume",
        title="Cancelled resume",
        description="Research",
        instructions="Research",
        source_path="/tmp/cancelled-resume/SKILL.md",
        source_scope=SkillSourceScope.BUILTIN,
        content_hash=node.skill_content_hash,
    )

    monkeypatch.setattr(runtime.repository, "get_skill_plan", lambda _plan_id: plan)
    monkeypatch.setattr(runtime.repository, "get_agent_run", lambda _run_id: current["run"])

    def claim(*_args: object, **_kwargs: object) -> AgentRun:
        current["run"] = claimed
        return claimed

    def cancel(run_id: str, **_kwargs: object) -> AgentRun:
        cancelled.append(run_id)
        current["run"] = claimed.model_copy(update={"status": AgentRunStatus.CANCELLED})
        return current["run"]

    monkeypatch.setattr(runtime.repository, "claim_agent_run_for_resume", claim)
    monkeypatch.setattr(runtime.repository, "append_agent_run_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runtime.repository, "cancel_agent_run_tree", cancel)
    monkeypatch.setattr(
        runtime,
        "_resolve_plan_node_security",
        lambda **_kwargs: (skill, set(), (), {}, True),
    )
    monkeypatch.setattr(runtime, "_build_agent", lambda **_kwargs: object())
    runtime.mcp_factory = SimpleNamespace(build=lambda **_kwargs: [])

    interruption = SimpleNamespace(
        arguments="{}",
        name="read",
        raw_item=SimpleNamespace(call_id="call_1"),
    )

    class FakeState:
        def get_interruptions(self):
            return [interruption]

        def approve(self, _item: object) -> None:
            return None

        def reject(self, _item: object, **_kwargs: object) -> None:
            return None

    async def from_json(*_args: object, **_kwargs: object) -> FakeState:
        return FakeState()

    async def cancelled_stream(*_args: object, **_kwargs: object):
        raise asyncio.CancelledError

    monkeypatch.setattr("agentmesh.agent_runtime.service.RunState.from_json", from_json)
    monkeypatch.setattr(runtime, "_run_streamed", cancelled_stream)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            runtime._resume_skill_plan_node(
                waiting,
                user=USER,
                decisions={"call_1": True},
            )
        )

    assert cancelled == [waiting.id]
    assert current["run"].status is AgentRunStatus.CANCELLED
