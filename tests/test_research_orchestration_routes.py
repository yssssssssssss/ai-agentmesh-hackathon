from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

import agentmesh.routes.chat as chat_routes
from agentmesh.app import app
from agentmesh.models import AgentRun, AgentRunStatus
from agentmesh.research_orchestration.api import (
    ResearchCommandResponse,
    ResearchConflictError,
    ResearchNotFoundError,
    ResearchRunProjection,
    ResearchWorkflowProjection,
)
from agentmesh.research_orchestration.contracts import ResearchGate, ResearchPhase
from agentmesh.seed import USER
from agentmesh.store import store


def _login(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"user_id": USER.id, "password": "designer123"})
    assert response.status_code == 200


def _projection(run_id: str, *, state_version: int = 1) -> ResearchRunProjection:
    return ResearchRunProjection(
        run_id=run_id,
        workflow=ResearchWorkflowProjection(
            phase=ResearchPhase.PLANNING,
            active_gate=ResearchGate.PLAN_CONFIRMATION,
            state_version=state_version,
            active_requirement_version_id="requirement_1",
            active_plan_version_id="plan_1",
        ),
    )


@dataclass
class FakeResearchWorkflowService:
    calls: list[dict[str, Any]] = field(default_factory=list)
    failures: dict[str, Exception] = field(default_factory=dict)

    def _call(self, method: str, run_id: str, request=None, **kwargs):  # noqa: ANN001, ANN202
        failure = self.failures.get(method)
        if failure is not None:
            raise failure
        self.calls.append({"method": method, "run_id": run_id, "request": request, **kwargs})
        if method == "get_projection":
            return _projection(run_id)
        command_type = "confirm_plan" if method == "confirm_plan" else method.removesuffix("_plan")
        return ResearchCommandResponse(
            run_id=run_id,
            command_type=command_type,
            state_version=request.expected_state_version + 1,
            projection=_projection(run_id, state_version=request.expected_state_version + 1),
        )

    def get_projection(self, run_id: str, **kwargs):  # noqa: ANN003, ANN201
        return self._call("get_projection", run_id, **kwargs)

    def clarify(self, run_id: str, request, **kwargs):  # noqa: ANN001, ANN003, ANN201
        return self._call("clarify", run_id, request, **kwargs)

    def confirm_plan(self, run_id: str, plan_version_id: str, request, **kwargs):  # noqa: ANN001, ANN003, ANN201
        return self._call("confirm_plan", run_id, request, plan_version_id=plan_version_id, **kwargs)

    def revise_plan(self, run_id: str, plan_version_id: str, request, **kwargs):  # noqa: ANN001, ANN003, ANN201
        return self._call("revise_plan", run_id, request, plan_version_id=plan_version_id, **kwargs)

    async def execute(self, run_id: str, request, **kwargs):  # noqa: ANN001, ANN003, ANN201
        return self._call("execute", run_id, request, **kwargs)

    def recover(self, run_id: str, request, **kwargs):  # noqa: ANN001, ANN003, ANN201
        return self._call("recover", run_id, request, **kwargs)

    def purge(self, run_id: str, request, **kwargs):  # noqa: ANN001, ANN003, ANN201
        return self._call("purge", run_id, request, **kwargs)


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> FakeResearchWorkflowService:
    fake = FakeResearchWorkflowService()
    monkeypatch.setattr(
        app.state,
        "research_runtime",
        SimpleNamespace(workflow_service=fake),
        raising=False,
    )
    return fake


@pytest.fixture
def client() -> TestClient:
    result = TestClient(app)
    _login(result)
    return result


def test_research_get_is_owner_scoped_projection_only_and_refresh_safe(
    client: TestClient,
    service: FakeResearchWorkflowService,
) -> None:
    first = client.get("/api/agent/runs/run_research_http/research")
    refreshed = client.get("/api/agent/runs/run_research_http/research")

    assert first.status_code == refreshed.status_code == 200
    assert first.json()["workflow"]["active_gate"] == "plan_confirmation"
    assert [call["method"] for call in service.calls] == ["get_projection", "get_projection"]
    assert all(call["owner"].user_id == USER.id for call in service.calls)
    assert all(call["owner"].workspace_id == USER.workspace_id for call in service.calls)


@pytest.mark.parametrize(
    ("http_method", "path", "payload", "service_method", "command_type"),
    [
        (
            "post",
            "/api/agent/runs/run_research_http/research/clarify",
            {
                "expected_state_version": 1,
                "answers": [{"question_id": "clarify_competitor_scope", "answer": "Figma 与 Miro"}],
            },
            "clarify",
            "clarify",
        ),
        (
            "post",
            "/api/agent/runs/run_research_http/research/plans/plan_1/confirm",
            {"expected_state_version": 1},
            "confirm_plan",
            "confirm_plan",
        ),
        (
            "post",
            "/api/agent/runs/run_research_http/research/plans/plan_1/revise",
            {"expected_state_version": 1, "research_goal": "Compare collaboration and recovery"},
            "revise_plan",
            "revise",
        ),
        (
            "post",
            "/api/agent/runs/run_research_http/research/execute",
            {"expected_state_version": 1},
            "execute",
            "execute",
        ),
        (
            "post",
            "/api/agent/runs/run_research_http/research/recover",
            {"expected_state_version": 1, "invocation_id": "invocation_1", "action": "retry"},
            "recover",
            "recover",
        ),
        (
            "delete",
            "/api/agent/runs/run_research_http/research-data",
            {"expected_state_version": 1},
            "purge",
            "purge",
        ),
    ],
)
def test_research_mutations_forward_owner_version_and_idempotency_and_return_202(
    client: TestClient,
    service: FakeResearchWorkflowService,
    http_method: str,
    path: str,
    payload: dict[str, object],
    service_method: str,
    command_type: str,
) -> None:
    response = client.request(
        http_method,
        path,
        json=payload,
        headers={"Idempotency-Key": f"command-{service_method}"},
    )

    assert response.status_code == 202
    assert response.json()["command_type"] == command_type
    call = service.calls[-1]
    assert call["method"] == service_method
    assert call["request"].expected_state_version == 1
    assert call["idempotency_key"] == f"command-{service_method}"
    assert call["owner"].user_id == USER.id
    assert call["owner"].project_id == USER.default_project_id


@pytest.mark.parametrize(
    ("headers", "payload", "expected_status"),
    [
        ({}, {"expected_state_version": 1}, 422),
        ({"Idempotency-Key": "   "}, {"expected_state_version": 1}, 400),
        ({"Idempotency-Key": "execute-1"}, {}, 422),
        ({"Idempotency-Key": "execute-1"}, {"expected_state_version": 0}, 422),
    ],
)
def test_research_mutation_rejects_missing_control_inputs_before_service_call(
    client: TestClient,
    service: FakeResearchWorkflowService,
    headers: dict[str, str],
    payload: dict[str, object],
    expected_status: int,
) -> None:
    response = client.post(
        "/api/agent/runs/run_research_http/research/execute",
        json=payload,
        headers=headers,
    )

    assert response.status_code == expected_status
    assert service.calls == []


def test_revise_accepts_only_declarative_changes(
    client: TestClient,
    service: FakeResearchWorkflowService,
) -> None:
    response = client.post(
        "/api/agent/runs/run_research_http/research/plans/plan_1/revise",
        headers={"Idempotency-Key": "revise-forged-plan"},
        json={
            "expected_state_version": 1,
            "research_goal": "Compare recovery",
            "plan_hash": "0" * 64,
            "steps": [{"step_number": 99}],
        },
    )

    assert response.status_code == 422
    assert service.calls == []


def test_research_routes_map_hidden_owner_and_state_conflicts(
    client: TestClient,
    service: FakeResearchWorkflowService,
) -> None:
    service.failures["get_projection"] = ResearchNotFoundError("hidden")
    hidden = client.get("/api/agent/runs/run_hidden/research")
    assert hidden.status_code == 404
    assert hidden.json()["detail"] == "Research run not found"

    service.failures.clear()
    service.failures["execute"] = ResearchConflictError("research workflow state version conflict")
    conflict = client.post(
        "/api/agent/runs/run_research_http/research/execute",
        headers={"Idempotency-Key": "stale-execute"},
        json={"expected_state_version": 1},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "research workflow state version conflict"


def test_research_routes_do_not_disguise_programming_errors_as_conflicts(
    service: FakeResearchWorkflowService,
) -> None:
    service.failures["execute"] = RuntimeError("programming bug")
    client = TestClient(app, raise_server_exceptions=False)
    _login(client)

    response = client.post(
        "/api/agent/runs/run_research_http/research/execute",
        headers={"Idempotency-Key": "buggy-execute"},
        json={"expected_state_version": 1},
    )

    assert response.status_code == 500


def test_research_routes_require_authentication_and_configured_service(
    monkeypatch: pytest.MonkeyPatch,
    service: FakeResearchWorkflowService,
) -> None:
    monkeypatch.delattr(app.state, "research_runtime", raising=False)
    anonymous = TestClient(app).get("/api/agent/runs/run_research_http/research")
    assert anonymous.status_code == 401
    assert service.calls == []

    client = TestClient(app)
    _login(client)
    unavailable = client.get("/api/agent/runs/run_research_http/research")
    assert unavailable.status_code == 503


def test_openapi_exposes_exactly_the_seven_research_interfaces_with_guard_headers() -> None:
    schema = app.openapi()
    interfaces = {
        "/api/agent/runs/{run_id}/research": "get",
        "/api/agent/runs/{run_id}/research/clarify": "post",
        "/api/agent/runs/{run_id}/research/plans/{plan_version_id}/confirm": "post",
        "/api/agent/runs/{run_id}/research/plans/{plan_version_id}/revise": "post",
        "/api/agent/runs/{run_id}/research/execute": "post",
        "/api/agent/runs/{run_id}/research/recover": "post",
        "/api/agent/runs/{run_id}/research-data": "delete",
    }

    for path, method in interfaces.items():
        operation = schema["paths"][path][method]
        if method == "get":
            assert all(parameter["name"] != "Idempotency-Key" for parameter in operation["parameters"])
            assert "200" in operation["responses"]
            continue
        header = next(parameter for parameter in operation["parameters"] if parameter["name"] == "Idempotency-Key")
        assert header["in"] == "header"
        assert header["required"] is True
        assert "202" in operation["responses"]

    recover_schema = schema["components"]["schemas"]["ResearchRecoverRequest"]
    assert set(recover_schema["required"]) == {"expected_state_version", "invocation_id", "action"}
    assert recover_schema["properties"]["action"]["enum"] == ["retry", "abort"]


def test_legacy_retry_and_cancel_do_not_dispatch_research_v2_into_the_v1_runtime(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retry_run = store.save_agent_run(
        AgentRun(
            id="run_research_v2_retry_isolation",
            thread_id="thread_research_v2_retry_isolation",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="compare",
            status=AgentRunStatus.FAILED,
            orchestration_version="research-v2",
            orchestration_mode="execute",
        )
    )
    cancel_run = store.save_agent_run(
        AgentRun(
            id="run_research_v2_cancel_isolation",
            thread_id="thread_research_v2_cancel_isolation",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="compare",
            status=AgentRunStatus.RUNNING,
            orchestration_version="research-v2",
            orchestration_mode="execute",
        )
    )

    class ForbiddenRuntime:
        async def cancel(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            raise AssertionError("v1 runtime must not receive research-v2 cancellation")

    monkeypatch.setattr(chat_routes.agent, "agent_runtime", ForbiddenRuntime())
    retry = client.post(
        f"/api/agent/runs/{retry_run.id}/retry",
        json={"client_turn_id": "research-v2-retry"},
    )
    cancel = client.post(f"/api/agent/runs/{cancel_run.id}/cancel")

    assert retry.status_code == 409
    assert "research recovery API" in retry.json()["detail"]
    assert cancel.status_code == 200
    assert cancel.json()["item"]["status"] == "cancelled"
    assert store.get_agent_run(cancel_run.id).status == AgentRunStatus.CANCELLED
