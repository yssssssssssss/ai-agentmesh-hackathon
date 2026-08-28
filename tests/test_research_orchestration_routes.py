from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient

import agentmesh.routes.chat as chat_routes
from agentmesh.app import app
from agentmesh.models import AgentRun, AgentRunStatus, InboxItem, Scope
from agentmesh.research_orchestration.api import (
    ResearchConflictError,
    ResearchNotFoundError,
    ResearchRunProjection,
    ResearchWorkflowProjection,
)
from agentmesh.research_orchestration.contracts import ResearchGate, ResearchPhase
from agentmesh.seed import USER
from agentmesh.store import store

_V2_READ_ONLY = "Research-v2 runs are historical and read-only"


def _login(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"user_id": USER.id, "password": "designer123"})
    assert response.status_code == 200


def _projection(run_id: str, *, state_version: int = 1) -> ResearchRunProjection:
    return ResearchRunProjection(
        run_id=run_id,
        status=AgentRunStatus.PLANNING,
        workflow=ResearchWorkflowProjection(
            phase=ResearchPhase.PLANNING,
            active_gate=ResearchGate.PLAN_CONFIRMATION,
            state_version=state_version,
            active_requirement_version_id="requirement_1",
            active_plan_version_id="plan_1",
        ),
    )


@dataclass
class FakeV2HistoryReader:
    calls: list[dict[str, Any]] = field(default_factory=list)
    failure: Exception | None = None

    def get_projection(self, run_id: str, **kwargs):  # noqa: ANN003, ANN201
        if self.failure is not None:
            raise self.failure
        self.calls.append({"run_id": run_id, **kwargs})
        return _projection(run_id)


@pytest.fixture
def history_reader(monkeypatch: pytest.MonkeyPatch) -> FakeV2HistoryReader:
    reader = FakeV2HistoryReader()
    monkeypatch.setattr(app.state, "research_v2_history_reader", reader, raising=False)
    return reader


@pytest.fixture
def client() -> TestClient:
    result = TestClient(app)
    _login(result)
    return result


def _save_v2_run(run_id: str, *, status: AgentRunStatus = AgentRunStatus.FAILED) -> AgentRun:
    historical = AgentRun(
        id=run_id,
        thread_id=f"thread_{run_id}",
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        input_text="compare",
        status=status,
        orchestration_version="research-v2",
        orchestration_mode="execute",
    )
    store.save_agent_run(historical.model_copy(update={"orchestration_version": "v1"}))
    with store._connect() as connection:
        connection.execute(
            "UPDATE agent_runs SET payload = ?, orchestration_version = ? WHERE id = ?",
            (historical.model_dump_json(), "research-v2", historical.id),
        )
    return historical


def test_research_get_is_owner_scoped_projection_only_and_refresh_safe(
    client: TestClient,
    history_reader: FakeV2HistoryReader,
) -> None:
    first = client.get("/api/agent/runs/run_research_http/research")
    refreshed = client.get("/api/agent/runs/run_research_http/research")

    assert first.status_code == refreshed.status_code == 200
    assert first.json()["status"] == "planning"
    assert first.json()["workflow"]["active_gate"] == "plan_confirmation"
    assert len(history_reader.calls) == 2
    assert all(call["owner"].user_id == USER.id for call in history_reader.calls)
    assert all(call["owner"].workspace_id == USER.workspace_id for call in history_reader.calls)


def test_research_get_does_not_write_v2_state(
    client: TestClient,
    history_reader: FakeV2HistoryReader,
) -> None:
    tables = (
        "agent_runs",
        "agent_run_events",
        "artifacts",
        "research_workflows",
        "research_requirement_versions",
        "research_plan_versions",
        "research_attempts",
        "research_steps",
        "research_tool_invocations",
        "research_commands",
        "research_model_call_receipts",
    )
    with store._connect() as connection:
        before = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608
            for table in tables
        }

    response = client.get("/api/agent/runs/run_research_http/research")

    with store._connect() as connection:
        after = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608
            for table in tables
        }
    assert response.status_code == 200
    assert before == after
    assert len(history_reader.calls) == 1


def test_research_get_maps_history_errors(
    client: TestClient,
    history_reader: FakeV2HistoryReader,
) -> None:
    history_reader.failure = ResearchNotFoundError("hidden")
    hidden = client.get("/api/agent/runs/run_hidden/research")
    assert hidden.status_code == 404
    assert hidden.json()["detail"] == "Research run not found"

    history_reader.failure = ResearchConflictError("history integrity conflict")
    conflict = client.get("/api/agent/runs/run_corrupt/research")
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "history integrity conflict"


def test_research_get_uses_dedicated_history_reader(
    monkeypatch: pytest.MonkeyPatch,
    history_reader: FakeV2HistoryReader,
) -> None:
    anonymous = TestClient(app).get("/api/agent/runs/run_research_http/research")
    assert anonymous.status_code == 401
    assert history_reader.calls == []

    client = TestClient(app)
    _login(client)
    available = client.get("/api/agent/runs/run_research_http/research")
    assert available.status_code == 200
    assert len(history_reader.calls) == 1

    monkeypatch.delattr(app.state, "research_v2_history_reader", raising=False)
    unavailable = client.get("/api/agent/runs/run_research_http/research")
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"] == "Research history reader is unavailable"


@pytest.mark.parametrize(
    ("http_method", "suffix"),
    [
        ("post", "research/clarify"),
        ("post", "research/execute"),
        ("delete", "research-data"),
    ],
)
def test_retired_research_mutation_routes_are_removed(
    client: TestClient,
    http_method: str,
    suffix: str,
) -> None:
    response = client.request(
        http_method,
        f"/api/agent/runs/run_removed_research_mutation/{suffix}",
        json={},
        headers={"Idempotency-Key": f"removed-{http_method}"},
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "suffix",
    [
        "research/plans/plan_1/confirm",
        "research/plans/plan_1/revise",
        "research/recover",
    ],
)
def test_v2_only_research_mutation_routes_are_removed(client: TestClient, suffix: str) -> None:
    response = client.post(
        f"/api/agent/runs/run_removed_v2_route/{suffix}",
        json={"expected_state_version": 1},
        headers={"Idempotency-Key": "removed-v2-route"},
    )

    assert response.status_code == 404


def test_openapi_exposes_only_the_v2_history_research_route() -> None:
    schema = app.openapi()
    paths = schema["paths"]
    assert paths["/api/agent/runs/{run_id}/research"].keys() == {"get"}
    assert "/api/agent/runs/{run_id}/research/plans/{plan_version_id}/confirm" not in paths
    assert "/api/agent/runs/{run_id}/research/plans/{plan_version_id}/revise" not in paths
    assert "/api/agent/runs/{run_id}/research/recover" not in paths
    assert "/api/agent/runs/{run_id}/research/clarify" not in paths
    assert "/api/agent/runs/{run_id}/research/execute" not in paths
    assert "/api/agent/runs/{run_id}/research-data" not in paths


def test_research_tool_approval_is_visible_but_has_no_actions(
    client: TestClient,
) -> None:
    item = store.save_inbox_item(
        InboxItem(
            id="inbox_historical_research_tool_approval",
            title="Historical approval",
            summary="Retained for audit only",
            item_type="research_tool_approval",
            scope=Scope.PRIVATE,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            metadata={"call_id": "historical_call"},
        )
    )

    listed = client.get("/api/inbox")
    patched = client.patch(f"/api/inbox/{item.id}", json={"status": "snoozed", "ttl_minutes": 10})
    resolved = client.post(
        f"/api/inbox/{item.id}/resolve-tool-approval",
        params={"action": "approve", "call_id": "historical_call"},
    )

    projected = next(value for value in listed.json()["items"] if value["id"] == item.id)
    assert projected["allowed_actions"] == []
    assert patched.status_code == resolved.status_code == 409
    assert patched.json()["detail"] == resolved.json()["detail"]
    assert store.get_inbox_item(item.id).status == "open"


def test_legacy_retry_and_cancel_leave_research_v2_unchanged(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retry_run = _save_v2_run("run_research_v2_retry_isolation")
    cancel_run = _save_v2_run(
        "run_research_v2_cancel_isolation",
        status=AgentRunStatus.RUNNING,
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

    assert retry.status_code == cancel.status_code == 409
    assert retry.json()["detail"] == cancel.json()["detail"] == _V2_READ_ONLY
    assert store.get_agent_run(retry_run.id).status == AgentRunStatus.FAILED
    assert store.get_agent_run(cancel_run.id).status == AgentRunStatus.RUNNING


def test_retry_rejects_column_projected_v3_before_runtime_dispatch(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy = AgentRun(
        id="run_column_projected_v3_retry",
        thread_id="thread_column_projected_v3_retry",
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        input_text="legacy",
        status=AgentRunStatus.FAILED,
        orchestration_version="v1",
    )
    store.save_agent_run(legacy)
    original_payload = legacy.model_dump_json()
    with store._connect() as connection:
        connection.execute(
            "UPDATE agent_runs SET orchestration_version = 'research-v3' WHERE id = ?",
            (legacy.id,),
        )

    class ForbiddenRuntime:
        @property
        def enabled(self) -> bool:
            raise AssertionError("retired v3 retry must not inspect or invoke the Runtime")

    monkeypatch.setattr(chat_routes.agent, "agent_runtime", ForbiddenRuntime())
    response = client.post(
        f"/api/agent/runs/{legacy.id}/retry",
        json={"client_turn_id": "turn_column_projected_v3_retry"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Research-v3 is retired and its runs cannot be changed"
    with store._connect() as connection:
        stored = connection.execute(
            "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
            (legacy.id,),
        ).fetchone()
    assert stored["payload"] == original_payload
    assert stored["orchestration_version"] == "research-v3"
