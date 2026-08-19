from __future__ import annotations

from fastapi.testclient import TestClient

from agentmesh.app import app
from agentmesh.seed import ADMIN, USER


def _login(client: TestClient, user_id: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"user_id": user_id, "password": password})
    assert response.status_code == 200


def test_skill_catalog_and_chat_compatibility_routes(tmp_path, monkeypatch, configure_pilot_wiki) -> None:
    monkeypatch.setenv("AGENTMESH_AGENT_RUNTIME", "legacy")
    monkeypatch.delenv("AGENTMESH_WIKI_ROOT", raising=False)
    client = TestClient(app)
    _login(client, USER.id, "designer123")

    catalog_response = client.get("/api/skills")
    compatibility_response = client.get("/api/chat/skills")

    assert catalog_response.status_code == 200
    catalog_items = catalog_response.json()["items"]
    names = {item["command"] for item in catalog_items}
    assert {
        "$generate-research-plan",
        "$issue-prioritization",
        "$jobs-to-be-done",
    }.issubset(names)
    compatibility_names = {item["command"] for item in compatibility_response.json()["items"]}
    assert "$memory.search" in compatibility_names
    assert names.isdisjoint(compatibility_names)
    assert not any(item["enabled"] for item in catalog_items)

    monkeypatch.setenv("AGENTMESH_AGENT_RUNTIME", "v2")
    configure_pilot_wiki(tmp_path)
    compatibility_names = {item["command"] for item in client.get("/api/chat/skills").json()["items"]}
    assert names.issubset(compatibility_names)

    issue_skill = next(item for item in catalog_items if item["command"] == "$issue-prioritization")
    _login(client, USER.id, "designer123")
    disabled = client.patch(f"/api/skills/{issue_skill['id']}/binding", json={"enabled": False})
    after_disable = client.get("/api/chat/skills")
    restored = client.patch(f"/api/skills/{issue_skill['id']}/binding", json={"enabled": True})
    assert disabled.status_code == 200
    assert "$issue-prioritization" not in {item["command"] for item in after_disable.json()["items"]}
    assert restored.status_code == 200


def test_only_admin_can_reload_or_read_skill_diagnostics() -> None:
    client = TestClient(app)
    _login(client, USER.id, "designer123")
    assert client.post("/api/skills/reload").status_code == 403
    assert client.get("/api/skills/diagnostics").status_code == 403

    _login(client, ADMIN.id, "admin123")
    reload_response = client.post("/api/skills/reload")
    diagnostics_response = client.get("/api/skills/diagnostics")

    assert reload_response.status_code == 200
    assert diagnostics_response.status_code == 200
