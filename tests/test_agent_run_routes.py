from __future__ import annotations

from agents.testing import ScriptedModel, assistant_message
from fastapi.testclient import TestClient

import agentmesh.routes.chat as chat_routes
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.app import app
from agentmesh.models import AgentRun, AgentRunStatus, Artifact
from agentmesh.seed import TEAM_LEAD, USER
from agentmesh.store import store


def _login(client: TestClient, user_id: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"user_id": user_id, "password": password})
    assert response.status_code == 200


def test_agent_run_create_is_idempotent_by_client_turn(monkeypatch) -> None:
    runtime = AgentRuntimeService(
        store,
        model=ScriptedModel([[assistant_message("idempotent answer")]]),
        enabled=True,
    )
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)
    payload = {"content": "one durable turn", "client_turn_id": "agent-run-idempotency"}

    client = TestClient(app)
    _login(client, USER.id, "designer123")
    first = client.post("/api/agent/runs", json=payload)
    second = client.post("/api/agent/runs", json=payload)

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["item"]["id"] == first.json()["item"]["id"]
    thread_id = first.json()["item"]["thread_id"]
    matching = [message for message in store.list_thread_messages(thread_id) if message.content == payload["content"]]
    assert len(matching) == 1


def test_agent_run_events_and_artifact_are_owner_scoped() -> None:
    run = store.save_agent_run(
        AgentRun(
            id="run_route_contract",
            thread_id="thread_route_contract",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="route contract",
            status=AgentRunStatus.COMPLETED,
            output_text="done",
        )
    )
    store.append_agent_run_event(run.id, "run_completed", {"total_tokens": 4})
    artifact = store.save_artifact(
        Artifact(
            id="artifact_route_contract",
            run_id=run.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            artifact_type="tool_output",
            content_type="text/plain",
            content="full tool output",
        )
    )
    client = TestClient(app)
    _login(client, USER.id, "designer123")

    run_response = client.get(f"/api/agent/runs/{run.id}")
    events_response = client.get(f"/api/agent/runs/{run.id}/events")
    stream_response = client.get(f"/api/agent/runs/{run.id}/events/stream")
    artifact_response = client.get(f"/api/artifacts/{artifact.id}")

    assert run_response.status_code == 200
    assert events_response.status_code == 200
    assert events_response.json()["items"][-1]["event_type"] == "run_completed"
    assert stream_response.status_code == 200
    assert "event: run_completed" in stream_response.text
    assert artifact_response.status_code == 200
    assert artifact_response.text == "full tool output"

    _login(client, TEAM_LEAD.id, "lead123")
    assert client.get(f"/api/agent/runs/{run.id}").status_code == 404
    assert client.get(f"/api/artifacts/{artifact.id}").status_code == 404
