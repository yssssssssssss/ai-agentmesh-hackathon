from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from agentmesh.app import app
from agentmesh.models import now_utc
from agentmesh.runner_auth import hash_runner_token
from agentmesh.runner_contracts import RunnerDeviceStatus, RunnerEnrollmentStatus
from agentmesh.seed import TEAM_LEAD, USER
from agentmesh.store import store


def setup_function() -> None:
    store.reset()


def _capabilities(*, version: str = "0.1.0") -> dict[str, object]:
    return {
        "schema_version": "runner-capabilities-v1",
        "platform": "darwin",
        "architecture": "arm64",
        "runner_version": version,
        "protocol_version": "runner-v1",
        "tools": ["git", "python"],
        "model_capabilities": ["streaming", "tool_calls"],
    }


def _start_enrollment(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/runner/enrollment/start",
        json={"device_name": "Test Mac", "capabilities": _capabilities()},
    )
    assert response.status_code == 201
    return response.json()


def _login(client: TestClient, user_id: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"user_id": user_id, "password": password})
    assert response.status_code == 200


def test_runner_enrollment_heartbeat_and_revoke() -> None:
    client = TestClient(app)
    enrollment = _start_enrollment(client)
    device_code = str(enrollment["device_code"])
    user_code = str(enrollment["user_code"])
    assert "section=runners" in str(enrollment["verification_uri"])
    assert f"runner_enrollment={user_code}" in str(enrollment["verification_uri"])

    pending = client.post(
        "/api/runner/enrollment/token",
        json={"device_code": device_code},
    )
    assert pending.status_code == 200
    assert pending.json() == {
        "status": "authorization_pending",
        "runner": None,
        "access_token": None,
        "token_type": "Bearer",
    }

    _login(client, USER.id, "designer123")
    review = client.get(f"/api/runner/enrollment/{user_code}")
    assert review.status_code == 200
    assert review.json()["device_name"] == "Test Mac"
    assert review.json()["capabilities"]["protocol_version"] == "runner-v1"

    approved = client.post(f"/api/runner/enrollment/{user_code.lower()}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == RunnerEnrollmentStatus.APPROVED.value

    activated = client.post(
        "/api/runner/enrollment/token",
        json={"device_code": device_code},
    )
    assert activated.status_code == 200
    token_payload = activated.json()
    assert token_payload["status"] == "approved"
    assert token_payload["access_token"] == device_code
    runner_id = token_payload["runner"]["id"]

    credential = store.get_runner_credential_by_token_hash(hash_runner_token(device_code))
    assert credential is not None
    assert credential.token_hash != device_code
    assert credential.runner_id == runner_id

    heartbeat = client.post(
        "/api/runner/heartbeat",
        headers={"Authorization": f"Bearer {device_code}"},
        json={"capabilities": _capabilities(version="0.1.1")},
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["runner"]["capabilities"]["runner_version"] == "0.1.1"
    assert heartbeat.json()["runner"]["last_seen_at"] is not None

    listed = client.get("/api/runners")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [runner_id]

    revoked = client.post(f"/api/runners/{runner_id}/revoke")
    assert revoked.status_code == 200
    assert store.get_runner_device(runner_id).status is RunnerDeviceStatus.REVOKED

    rejected = client.post(
        "/api/runner/heartbeat",
        headers={"Authorization": f"Bearer {device_code}"},
        json={"capabilities": _capabilities()},
    )
    assert rejected.status_code == 401


def test_runner_devices_are_owner_scoped() -> None:
    client = TestClient(app)
    enrollment = _start_enrollment(client)
    _login(client, USER.id, "designer123")
    approved = client.post(f"/api/runner/enrollment/{enrollment['user_code']}/approve")
    runner_id = approved.json()["runner_id"]
    assert (
        client.post(
            "/api/runner/enrollment/token",
            json={"device_code": enrollment["device_code"]},
        ).status_code
        == 200
    )

    _login(client, TEAM_LEAD.id, "lead123")
    assert client.get("/api/runners").json()["items"] == []
    assert client.post(f"/api/runners/{runner_id}/revoke").status_code == 404

    runner_token_as_user = TestClient(app).get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {enrollment['device_code']}"},
    )
    assert runner_token_as_user.status_code == 401


def test_expired_runner_enrollment_cannot_be_approved_or_activated() -> None:
    client = TestClient(app)
    enrollment_payload = _start_enrollment(client)
    enrollment = store.get_runner_enrollment_by_user_code(str(enrollment_payload["user_code"]))
    assert enrollment is not None
    enrollment.expires_at = now_utc() - timedelta(seconds=1)
    store.save_runner_enrollment(enrollment)

    _login(client, USER.id, "designer123")
    approval = client.post(f"/api/runner/enrollment/{enrollment.user_code}/approve")
    exchange = client.post(
        "/api/runner/enrollment/token",
        json={"device_code": enrollment_payload["device_code"]},
    )

    assert approval.status_code == 410
    assert exchange.status_code == 410
    assert store.get_runner_enrollment(enrollment.id).status is RunnerEnrollmentStatus.EXPIRED
