from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

import agentmesh.routes.auth as auth_routes
from agentmesh.app import app
from agentmesh.seed import PROJECT
from agentmesh.store import store


def clear_store() -> None:
    store.reset()


def oauth_env() -> dict[str, str]:
    return {
        "AGENTMESH_OAUTH_ENABLED": "true",
        "AGENTMESH_OAUTH_PROVIDER": "corp",
        "AGENTMESH_OAUTH_AUTHORIZE_URL": "https://sso.example/authorize",
        "AGENTMESH_OAUTH_TOKEN_URL": "https://sso.example/token",
        "AGENTMESH_OAUTH_USERINFO_URL": "https://sso.example/userinfo",
        "AGENTMESH_OAUTH_CLIENT_ID": "agentmesh-client",
        "AGENTMESH_OAUTH_CLIENT_SECRET": "secret",
        "AGENTMESH_OAUTH_REDIRECT_URI": "http://127.0.0.1:8010/api/auth/oauth/callback",
    }


def test_oauth_status_reports_unconfigured_without_secret_leak(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_OAUTH_ENABLED", "false")
    monkeypatch.setenv("AGENTMESH_OAUTH_CLIENT_SECRET", "do-not-return")
    client = TestClient(app)

    response = client.get("/api/auth/oauth/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["configured"] is False
    assert "secret" not in payload
    assert "do-not-return" not in str(payload)


def test_oauth_start_redirects_to_provider_with_state(monkeypatch) -> None:
    clear_store()
    for key, value in oauth_env().items():
        monkeypatch.setenv(key, value)
    client = TestClient(app)

    response = client.get("/api/auth/oauth/start", follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://sso.example/authorize"
    assert query["client_id"] == ["agentmesh-client"]
    assert query["response_type"] == ["code"]
    assert query["state"][0]
    assert response.cookies.get(auth_routes.OAUTH_STATE_COOKIE) == query["state"][0]


def test_oauth_callback_provisions_user_and_reuses_session_cookie(monkeypatch) -> None:
    clear_store()
    for key, value in oauth_env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(auth_routes, "exchange_oauth_code", lambda config, code: {"access_token": "access-token"})
    monkeypatch.setattr(
        auth_routes,
        "fetch_oauth_userinfo",
        lambda config, token: {
            "sub": "erp-001",
            "email": "designer@example.com",
            "name": "OAuth Designer",
            "role": "team_lead",
        },
    )
    client = TestClient(app)
    start = client.get("/api/auth/oauth/start", follow_redirects=False)
    state = start.cookies.get(auth_routes.OAUTH_STATE_COOKIE)

    callback = client.get(f"/api/auth/oauth/callback?code=ok&state={state}")
    me = client.get("/api/auth/me")

    assert callback.status_code == 200
    user = callback.json()["user"]
    assert user["id"].startswith("usr_oauth_")
    assert user["name"] == "OAuth Designer"
    assert user["oauth_provider"] == "corp"
    assert user["oauth_subject"] == "erp-001"
    assert user["role"] == "user"
    assert me.status_code == 200
    assert me.json()["user"]["id"] == user["id"]
    assert me.json()["user"]["role"] == "user"
    assert store.get_agent(user["personal_agent_id"]) is not None
    project = store.get_project(PROJECT.id)
    assert project is not None
    assert user["id"] in project.member_ids


def test_oauth_callback_rejects_invalid_state(monkeypatch) -> None:
    clear_store()
    for key, value in oauth_env().items():
        monkeypatch.setenv(key, value)
    client = TestClient(app)

    response = client.get("/api/auth/oauth/callback?code=ok&state=bad")

    assert response.status_code == 400
