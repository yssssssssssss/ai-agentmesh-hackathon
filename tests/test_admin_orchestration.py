from __future__ import annotations

from fastapi.testclient import TestClient

from agentmesh.app import app
from agentmesh.seed import ADMIN, USER
from agentmesh.skill_runtime.quiesce import OrchestrationQuiesceController


def _client(host: str) -> TestClient:
    app.state.orchestration_quiesce_controller = OrchestrationQuiesceController()
    app.state.deepsearch_recovery_coordinator = None
    return TestClient(app, client=(host, 50000))


def _login(client: TestClient, user_id: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"user_id": user_id, "password": password})
    assert response.status_code == 200


def test_quiesce_endpoint_requires_admin() -> None:
    client = _client("127.0.0.1")
    _login(client, USER.id, "designer123")
    response = client.post("/api/admin/skill-orchestration/quiesce")

    assert response.status_code == 403


def test_quiesce_endpoint_rejects_public_peer_even_with_spoofed_headers() -> None:
    client = _client("203.0.113.10")
    _login(client, ADMIN.id, "admin123")
    response = client.post(
        "/api/admin/skill-orchestration/quiesce",
        headers={"host": "127.0.0.1", "x-forwarded-for": "127.0.0.1"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "management_network_required"


def test_quiesce_endpoint_is_idempotent_for_loopback_admin() -> None:
    client = _client("127.0.0.1")
    _login(client, ADMIN.id, "admin123")
    first = client.post("/api/admin/skill-orchestration/quiesce")
    second = client.post("/api/admin/skill-orchestration/quiesce")

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["state"] == "quiesced"
    assert first.json()["active_permits"] == 0
    assert first.json()["deepsearch_recovery_running"] is False
