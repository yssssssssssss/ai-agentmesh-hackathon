from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

import agentmesh.routes.agent_runs as agent_run_routes
import agentmesh.routes.chat as chat_routes
from agentmesh.app import app
from agentmesh.deepsearch.contracts import DeepSearchStateResponse
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    ChatThread,
    DeepSearchBudgetV1,
    SkillIntent,
    SkillOrchestrationRequestMode,
    SkillPlan,
    SkillPlanStatus,
    now_utc,
)
from agentmesh.seed import USER
from agentmesh.skill_runtime.plan_validation import PlanValidationError
from agentmesh.store import store


def _login(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"user_id": USER.id, "password": "designer123"})
    assert response.status_code == 200


def _derived_thread_id(client_turn_id: str) -> str:
    digest = hashlib.sha256(f"agent-run-thread-v1\0{USER.id}\0{client_turn_id}".encode()).hexdigest()
    return f"thread_{digest[:24]}"


def _deepsearch_payload(client_turn_id: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "content": "compare the collaboration software market",
        "client_turn_id": client_turn_id,
        "orchestration_mode": "auto",
        "planning_mode": "deepsearch",
    }
    payload.update(overrides)
    return payload


def _assert_request_created_nothing(client_turn_id: str) -> None:
    assert store.get_agent_run_by_client_turn(USER.id, client_turn_id) is None
    assert store.get_chat_thread(_derived_thread_id(client_turn_id)) is None


def _replace_run_fixture(run: AgentRun) -> AgentRun:
    """Seed an otherwise unreachable persisted state without reopening production writers."""
    with store._connect() as connection:
        cursor = connection.execute(
            "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
            (run.model_dump_json(), run.updated_at.isoformat(), run.id),
        )
    assert cursor.rowcount == 1
    persisted = store.get_agent_run(run.id)
    assert persisted is not None
    return persisted


class _ForbiddenRuntime:
    def __getattribute__(self, name: str) -> object:
        raise AssertionError(f"rejected request must not inspect or invoke the Runtime: {name}")


class _NoModelRuntime:
    enabled = True

    def __init__(self) -> None:
        self.select_calls = 0

    def select_model(self, _user: object) -> None:
        self.select_calls += 1
        return None


class _RuntimeWithoutDeepSearchPlanner:
    enabled = True

    def __init__(self) -> None:
        self.select_calls = 0

    def select_model(self, _user: object) -> object:
        self.select_calls += 1
        return object()


class _DeepSearchRuntime:
    enabled = True

    def select_model(self, _user: object) -> object:
        return object()

    async def start_deepsearch(self, **kwargs: object) -> AgentRun:
        created_at = now_utc()
        run, _created = store.claim_new_agent_run(
            AgentRun(
                id=f"run_{kwargs['client_turn_id']}",
                thread_id=str(kwargs["thread_id"]),
                user_id=USER.id,
                workspace_id=USER.workspace_id,
                project_id=str(kwargs.get("project_id") or USER.default_project_id),
                input_text=str(kwargs["content"]),
                client_turn_id=str(kwargs["client_turn_id"]),
                retry_of_run_id=kwargs.get("retry_of_run_id"),
                planning_mode=AgentPlanningMode.DEEPSEARCH,
                create_request_hash=str(kwargs["create_request_hash"]),
                requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
                orchestration_version="v1",
                orchestration_mode="execute",
                status=AgentRunStatus.PLANNING,
                deadline_at=None,
                absolute_expires_at=created_at + timedelta(days=7),
                deepsearch_budget=DeepSearchBudgetV1(),
                created_at=created_at,
                updated_at=created_at,
            )
        )
        return run


class _NoExecutableDeepSearchRuntime(_DeepSearchRuntime):
    class PlanningService:
        @staticmethod
        def get_state(run: AgentRun) -> DeepSearchStateResponse:
            return DeepSearchStateResponse(run=run, active_requirement=None)

    deepsearch_planning_service = PlanningService()

    async def start_deepsearch(self, **kwargs: object) -> AgentRun:
        run = await super().start_deepsearch(**kwargs)
        store.append_agent_run_event(
            run.id,
            "skill_search_completed",
            {
                "outcome_code": "no_executable_skill",
                "blocked_matches": [
                    {
                        "skill_id": "skill_blocked",
                        "skill_name": "blocked-skill",
                        "title": "Blocked Skill",
                        "reason_codes": ["tool_grant_missing"],
                    }
                ],
                "capability_gaps": [
                    {
                        "requirement_id": "deliverable:research_plan",
                        "label": "Research plan",
                        "diagnostics": ["tool_grant_missing"],
                    }
                ],
            },
        )
        failed = store.fail_deepsearch_recovery_state(
            run_id=run.id,
            error_code="no_executable_skill",
        )
        assert failed is not None
        raise PlanValidationError(["no_executable_skill"])


def test_deepsearch_initial_no_executable_skill_returns_failed_run_and_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_turn_id = "turn_deepsearch_no_executable"
    monkeypatch.setenv("AGENTMESH_DEEPSEARCH_ENABLED", "true")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "execute")
    monkeypatch.setattr(
        chat_routes.agent,
        "agent_runtime",
        _NoExecutableDeepSearchRuntime(),
    )
    client = TestClient(app)
    _login(client)

    created = client.post(
        "/api/agent/runs",
        json=_deepsearch_payload(client_turn_id),
    )

    assert created.status_code == 202
    run = created.json()["item"]
    assert run["status"] == "failed"
    assert run["error_code"] == "no_executable_skill"
    state = client.get(f"/api/agent/runs/{run['id']}/deepsearch")
    assert state.status_code == 200
    assert state.json()["plan"] is None
    assert state.json()["blocked_matches"] == [
        {
            "skill_id": "skill_blocked",
            "skill_name": "blocked-skill",
            "title": "Blocked Skill",
            "reason_codes": ["tool_grant_missing"],
        }
    ]
    assert state.json()["capability_gap_details"] == [
        {
            "requirement_id": "deliverable:research_plan",
            "label": "Research plan",
            "diagnostics": ["tool_grant_missing"],
        }
    ]


@pytest.mark.parametrize(
    ("case", "feature_enabled", "server_mode", "request_overrides", "status_code", "error_code"),
    [
        (
            "explicit-skill-name",
            True,
            "execute",
            {"skill_name": "$competitive-analysis"},
            400,
            "deepsearch_explicit_skill_conflict",
        ),
        (
            "explicit-skill-alias",
            True,
            "execute",
            {"explicit_skill_name": "competitive-analysis"},
            400,
            "deepsearch_explicit_skill_conflict",
        ),
        (
            "single-request-mode",
            True,
            "execute",
            {"orchestration_mode": "single"},
            400,
            "deepsearch_requires_auto",
        ),
        ("server-off", True, "off", {}, 409, "deepsearch_execution_unavailable"),
        ("server-preview", True, "preview", {}, 409, "deepsearch_execution_unavailable"),
        ("feature-disabled", False, "execute", {}, 409, "deepsearch_disabled"),
    ],
)
def test_deepsearch_early_admission_rejections_have_no_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    feature_enabled: bool,
    server_mode: str,
    request_overrides: dict[str, object],
    status_code: int,
    error_code: str,
) -> None:
    client_turn_id = f"turn_deepsearch_reject_{case}"
    monkeypatch.setenv("AGENTMESH_DEEPSEARCH_ENABLED", "true" if feature_enabled else "false")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", server_mode)
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", _ForbiddenRuntime())
    client = TestClient(app)
    _login(client)

    response = client.post(
        "/api/agent/runs",
        json=_deepsearch_payload(client_turn_id, **request_overrides),
    )

    assert response.status_code == status_code
    assert response.json()["detail"] == {"code": error_code}
    _assert_request_created_nothing(client_turn_id)


@pytest.mark.parametrize(
    ("case", "runtime_factory", "error_code"),
    [
        ("runtime", lambda: None, "deepsearch_runtime_unavailable"),
        ("model", _NoModelRuntime, "deepsearch_model_unavailable"),
        ("planner", _RuntimeWithoutDeepSearchPlanner, "deepsearch_planner_unavailable"),
    ],
)
def test_deepsearch_core_admission_fails_closed_without_creating_state(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    runtime_factory: Callable[[], object | None],
    error_code: str,
) -> None:
    client_turn_id = f"turn_deepsearch_core_{case}"
    runtime = runtime_factory()
    monkeypatch.setenv("AGENTMESH_DEEPSEARCH_ENABLED", "true")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "execute")
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)
    client = TestClient(app)
    _login(client)

    response = client.post("/api/agent/runs", json=_deepsearch_payload(client_turn_id))

    assert response.status_code == 503
    assert response.json()["detail"] == {"code": error_code}
    _assert_request_created_nothing(client_turn_id)
    if isinstance(runtime, (_NoModelRuntime, _RuntimeWithoutDeepSearchPlanner)):
        assert runtime.select_calls == 1


def test_deepsearch_admission_dispatches_only_to_the_v1_deepsearch_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_turn_id = "turn_deepsearch_dispatch"
    monkeypatch.setenv("AGENTMESH_DEEPSEARCH_ENABLED", "true")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "execute")
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", _DeepSearchRuntime())
    client = TestClient(app)
    _login(client)

    response = client.post("/api/agent/runs", json=_deepsearch_payload(client_turn_id))

    assert response.status_code == 202
    assert response.json()["item"]["orchestration_version"] == "v1"
    assert response.json()["item"]["planning_mode"] == "deepsearch"


def test_atomic_client_turn_conflict_uses_the_stable_route_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class ConflictingRuntime:
        enabled = True

        async def start_orchestrated(self, **_kwargs: object) -> AgentRun:
            raise RuntimeError("client_turn_id was already used for another Agent run")

    monkeypatch.setenv("AGENTMESH_DEEPSEARCH_ENABLED", "false")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "execute")
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", ConflictingRuntime())
    client = TestClient(app)
    _login(client)

    response = client.post(
        "/api/agent/runs",
        json={"content": "standard request", "client_turn_id": "turn_atomic_route_conflict"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "client_turn_id_conflict"}


def _seed_route_run(
    *,
    run_id: str,
    client_turn_id: str,
    thread_id: str,
    planning_mode: AgentPlanningMode,
    status: AgentRunStatus,
    error_code: str | None = None,
    retry_of_run_id: str | None = None,
) -> AgentRun:
    created_at = now_utc()
    is_deepsearch = planning_mode is AgentPlanningMode.DEEPSEARCH
    store.add_chat_thread(
        ChatThread(
            id=thread_id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="DeepSearch route test thread",
            status="active",
        )
    )
    run, created = store.claim_new_agent_run(
        AgentRun(
            id=run_id,
            thread_id=thread_id,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="compare the collaboration software market",
            client_turn_id=client_turn_id,
            retry_of_run_id=retry_of_run_id,
            planning_mode=planning_mode,
            requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
            orchestration_version="v1",
            orchestration_mode="execute",
            status=AgentRunStatus.PLANNING if is_deepsearch else status,
            error_code=None if is_deepsearch else error_code,
            deadline_at=None,
            absolute_expires_at=created_at + timedelta(days=7) if is_deepsearch else None,
            deepsearch_budget=DeepSearchBudgetV1() if is_deepsearch else None,
            created_at=created_at,
            updated_at=created_at,
        )
    )
    assert created is True
    if is_deepsearch and (status is not AgentRunStatus.PLANNING or error_code is not None):
        run = _replace_run_fixture(
            run.model_copy(
                update={
                    "status": status,
                    "error_code": error_code,
                    "interaction_expires_at": (
                        created_at + timedelta(hours=24)
                        if status
                        in {
                            AgentRunStatus.WAITING_CLARIFICATION,
                            AgentRunStatus.WAITING_PLAN_APPROVAL,
                            AgentRunStatus.WAITING_APPROVAL,
                        }
                        else None
                    ),
                }
            )
        )
    return run


def test_deepsearch_retry_hides_a_run_with_a_deleted_parent_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _seed_route_run(
        run_id="run_deepsearch_retry_deleted_thread",
        client_turn_id="turn_deepsearch_retry_deleted_thread",
        thread_id="thread_deepsearch_retry_deleted_thread",
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        status=AgentRunStatus.FAILED,
        error_code="deepsearch_planning_transient",
    )
    store.add_chat_thread(
        ChatThread(
            id=original.thread_id,
            workspace_id=original.workspace_id,
            project_id=original.project_id,
            user_id=original.user_id,
            title="Deleted DeepSearch route test thread",
            status="deleted",
        )
    )
    monkeypatch.setenv("AGENTMESH_DEEPSEARCH_ENABLED", "true")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "execute")
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", _DeepSearchRuntime())
    client = TestClient(app)
    _login(client)

    response = client.post(
        f"/api/agent/runs/{original.id}/retry",
        json={"client_turn_id": "turn_deepsearch_retry_deleted_thread_new"},
    )

    assert response.status_code == 404


def test_identical_deepsearch_replay_precedes_current_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    client_turn_id = "turn_deepsearch_replay_before_admission"
    thread_id = "thread_deepsearch_replay_before_admission"
    client = TestClient(app)
    _login(client)
    prior = _seed_route_run(
        run_id="run_deepsearch_replay_before_admission",
        client_turn_id=client_turn_id,
        thread_id=thread_id,
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        status=AgentRunStatus.WAITING_CLARIFICATION,
    )
    monkeypatch.setenv("AGENTMESH_DEEPSEARCH_ENABLED", "false")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "off")
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", _ForbiddenRuntime())

    response = client.post(
        "/api/agent/runs",
        json=_deepsearch_payload(client_turn_id, thread_id=thread_id),
    )

    assert response.status_code == 202
    assert response.json()["item"]["id"] == prior.id
    assert response.json()["item"]["planning_mode"] == "deepsearch"


def test_identical_deepsearch_retry_replay_precedes_current_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    original = _seed_route_run(
        run_id="run_deepsearch_retry_original",
        client_turn_id="turn_deepsearch_retry_original",
        thread_id="thread_deepsearch_retry_replay",
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        status=AgentRunStatus.FAILED,
    )
    retry = _seed_route_run(
        run_id="run_deepsearch_retry_existing",
        client_turn_id="turn_deepsearch_retry_existing",
        thread_id=original.thread_id,
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        status=AgentRunStatus.WAITING_CLARIFICATION,
        retry_of_run_id=original.id,
    )
    monkeypatch.setenv("AGENTMESH_DEEPSEARCH_ENABLED", "false")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "off")
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", _ForbiddenRuntime())
    client = TestClient(app)
    _login(client)

    response = client.post(
        f"/api/agent/runs/{original.id}/retry",
        json={"client_turn_id": retry.client_turn_id},
    )

    assert response.status_code == 202
    assert response.json()["item"]["id"] == retry.id


def test_deepsearch_retry_requires_goal_revision_after_unresolved_clarification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _seed_route_run(
        run_id="run_deepsearch_retry_requires_revision",
        client_turn_id="turn_deepsearch_retry_requires_revision",
        thread_id="thread_deepsearch_retry_requires_revision",
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        status=AgentRunStatus.FAILED,
        error_code="deepsearch_clarification_unresolved",
    )
    monkeypatch.setenv("AGENTMESH_DEEPSEARCH_ENABLED", "true")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "execute")
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", _ForbiddenRuntime())
    client = TestClient(app)
    _login(client)

    response = client.post(
        f"/api/agent/runs/{original.id}/retry",
        json={"client_turn_id": "turn_deepsearch_retry_requires_revision_new"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "deepsearch_goal_revision_required"}
    assert store.get_agent_run_by_client_turn(USER.id, "turn_deepsearch_retry_requires_revision_new") is None


def test_deepsearch_retry_allows_only_the_retry_run_disposition(monkeypatch: pytest.MonkeyPatch) -> None:
    original = _seed_route_run(
        run_id="run_deepsearch_retry_transient",
        client_turn_id="turn_deepsearch_retry_transient",
        thread_id="thread_deepsearch_retry_transient",
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        status=AgentRunStatus.FAILED,
        error_code="deepsearch_planning_transient",
    )
    monkeypatch.setenv("AGENTMESH_DEEPSEARCH_ENABLED", "true")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "execute")
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", _DeepSearchRuntime())
    client = TestClient(app)
    _login(client)

    response = client.post(
        f"/api/agent/runs/{original.id}/retry",
        json={"client_turn_id": "turn_deepsearch_retry_transient_new"},
    )

    assert response.status_code == 202
    assert response.json()["item"]["retry_of_run_id"] == original.id


def test_deepsearch_retry_client_turn_collision_precedes_current_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    original_a = _seed_route_run(
        run_id="run_deepsearch_retry_collision_a",
        client_turn_id="turn_deepsearch_retry_collision_a",
        thread_id="thread_deepsearch_retry_collision",
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        status=AgentRunStatus.FAILED,
    )
    original_b = _seed_route_run(
        run_id="run_deepsearch_retry_collision_b",
        client_turn_id="turn_deepsearch_retry_collision_b",
        thread_id="thread_deepsearch_retry_collision",
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        status=AgentRunStatus.FAILED,
    )
    retry = _seed_route_run(
        run_id="run_deepsearch_retry_collision_existing",
        client_turn_id="turn_deepsearch_retry_collision_existing",
        thread_id=original_a.thread_id,
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        status=AgentRunStatus.WAITING_CLARIFICATION,
        retry_of_run_id=original_a.id,
    )
    monkeypatch.setenv("AGENTMESH_DEEPSEARCH_ENABLED", "false")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "off")
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", _ForbiddenRuntime())
    client = TestClient(app)
    _login(client)

    response = client.post(
        f"/api/agent/runs/{original_b.id}/retry",
        json={"client_turn_id": retry.client_turn_id},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "client_turn_id_conflict"}


@pytest.mark.parametrize("server_mode", ["off", "preview"])
def test_deepsearch_plan_approval_requires_execute_without_cancelling_the_run(
    monkeypatch: pytest.MonkeyPatch,
    server_mode: str,
) -> None:
    suffix = server_mode
    run = _seed_route_run(
        run_id=f"run_deepsearch_approve_{suffix}",
        client_turn_id=f"turn_deepsearch_approve_{suffix}",
        thread_id=f"thread_deepsearch_approve_{suffix}",
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        status=AgentRunStatus.WAITING_PLAN_APPROVAL,
    )
    plan = SkillPlan(
        id=f"plan_deepsearch_approve_{suffix}",
        run_id=run.id,
        status=SkillPlanStatus.WAITING_APPROVAL,
        intent=SkillIntent(goal="approve one DeepSearch plan"),
        planning_mode=AgentPlanningMode.DEEPSEARCH,
    )
    monkeypatch.setattr(agent_run_routes, "_visible_plan", lambda *_args: (run, plan))
    monkeypatch.setenv("AGENTMESH_DEEPSEARCH_ENABLED", "false")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", server_mode)
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", _ForbiddenRuntime())
    client = TestClient(app)
    _login(client)

    response = client.post(
        f"/api/agent/runs/{run.id}/plan/approve",
        json={"expected_version": plan.version},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "deepsearch_execution_unavailable"}
    persisted = store.get_agent_run(run.id)
    assert persisted is not None
    assert persisted.status == AgentRunStatus.WAITING_PLAN_APPROVAL


@pytest.mark.parametrize(
    ("stored_mode", "requested_mode"),
    [
        (AgentPlanningMode.STANDARD, AgentPlanningMode.DEEPSEARCH),
        (AgentPlanningMode.DEEPSEARCH, AgentPlanningMode.STANDARD),
    ],
)
def test_planning_mode_collision_precedes_current_admission(
    monkeypatch: pytest.MonkeyPatch,
    stored_mode: AgentPlanningMode,
    requested_mode: AgentPlanningMode,
) -> None:
    suffix = f"{stored_mode.value}_to_{requested_mode.value}"
    client_turn_id = f"turn_deepsearch_route_collision_{suffix}"
    thread_id = f"thread_deepsearch_route_collision_{suffix}"
    client = TestClient(app)
    _login(client)
    prior = _seed_route_run(
        run_id=f"run_deepsearch_route_collision_{suffix}",
        client_turn_id=client_turn_id,
        thread_id=thread_id,
        planning_mode=stored_mode,
        status=AgentRunStatus.FAILED,
    )
    monkeypatch.setenv("AGENTMESH_DEEPSEARCH_ENABLED", "false")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "off")
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", _ForbiddenRuntime())

    response = client.post(
        "/api/agent/runs",
        json=_deepsearch_payload(
            client_turn_id,
            thread_id=thread_id,
            planning_mode=requested_mode.value,
        ),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "client_turn_id_conflict"}
    persisted = store.get_agent_run_by_client_turn(USER.id, client_turn_id)
    assert persisted is not None
    assert persisted.id == prior.id
    assert persisted.planning_mode == stored_mode


@pytest.mark.parametrize(
    ("feature_enabled", "server_mode", "runtime_factory", "expected"),
    [
        (
            False,
            "execute",
            _RuntimeWithoutDeepSearchPlanner,
            {
                "available": False,
                "enabled": False,
                "runtime_mode": "execute",
                "core_ready": False,
                "reason_code": "disabled",
            },
        ),
        (
            True,
            "preview",
            _RuntimeWithoutDeepSearchPlanner,
            {
                "available": False,
                "enabled": True,
                "runtime_mode": "preview",
                "core_ready": False,
                "reason_code": "execution_unavailable",
            },
        ),
        (
            True,
            "execute",
            lambda: None,
            {
                "available": False,
                "enabled": True,
                "runtime_mode": "execute",
                "core_ready": False,
                "reason_code": "runtime_unavailable",
            },
        ),
        (
            True,
            "execute",
            _NoModelRuntime,
            {
                "available": False,
                "enabled": True,
                "runtime_mode": "execute",
                "core_ready": False,
                "reason_code": "model_unavailable",
            },
        ),
        (
            True,
            "execute",
            _RuntimeWithoutDeepSearchPlanner,
            {
                "available": False,
                "enabled": True,
                "runtime_mode": "execute",
                "core_ready": False,
                "reason_code": "planner_unavailable",
            },
        ),
    ],
)
def test_bootstrap_exposes_secret_safe_deepsearch_availability(
    monkeypatch: pytest.MonkeyPatch,
    feature_enabled: bool,
    server_mode: str,
    runtime_factory: Callable[[], object | None],
    expected: dict[str, object],
) -> None:
    monkeypatch.setenv("AGENTMESH_DEEPSEARCH_ENABLED", "true" if feature_enabled else "false")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", server_mode)
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime_factory())
    client = TestClient(app)
    _login(client)

    response = client.get("/api/bootstrap")

    assert response.status_code == 200
    assert response.json()["deepsearch_availability"] == expected
