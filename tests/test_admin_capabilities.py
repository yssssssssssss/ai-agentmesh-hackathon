"""Capability boundaries for Admin APIs."""

from __future__ import annotations

from fastapi.testclient import TestClient

from agentmesh.app import app
from agentmesh.permissions import (
    ACTION_MANAGE_PERMISSION_POLICIES,
    ACTION_MANAGE_PUBLIC_AGENT,
    ACTION_MANAGE_RISK_POLICIES,
    ACTION_MANAGE_USERS,
    ACTION_SYNC_O2,
    ACTION_VIEW_AUDIT,
    ACTION_VIEW_PERMISSION_POLICIES,
    ACTION_VIEW_PROVIDER_HEALTH,
)
from agentmesh.seed import ADMIN, TEAM_LEAD, USER
from agentmesh.store import store

PASSWORDS = {
    USER.id: "designer123",
    TEAM_LEAD.id: "lead123",
    ADMIN.id: "admin123",
}


def authenticated_client(user_id: str) -> TestClient:
    client = TestClient(app)
    response = client.post(
        "/api/auth/login",
        json={"user_id": user_id, "password": PASSWORDS[user_id]},
    )
    assert response.status_code == 200
    return client


def grant_user_role_capability(admin: TestClient, action: str) -> None:
    response = admin.post(
        "/api/users/permission-policies",
        json={"role": "user", "action": action, "effect": "allow"},
    )
    assert response.status_code == 200


def test_regular_user_is_denied_every_admin_read_boundary() -> None:
    store.reset()
    client = authenticated_client(USER.id)

    responses = [
        client.get("/api/users"),
        client.get("/api/agents"),
        client.get("/api/agents/agent_research/tools"),
        client.get("/api/users/permission-policies"),
        client.get("/api/risk/policies"),
        client.get("/api/health/providers"),
        client.get("/api/integrations/o2/status"),
        client.get("/api/audit"),
    ]

    assert [response.status_code for response in responses] == [403] * len(responses)


def test_granted_non_admin_capabilities_authorize_the_matching_modules() -> None:
    store.reset()
    admin = authenticated_client(ADMIN.id)
    user = authenticated_client(USER.id)
    for action in (
        ACTION_MANAGE_PERMISSION_POLICIES,
        ACTION_MANAGE_PUBLIC_AGENT,
        ACTION_MANAGE_RISK_POLICIES,
        ACTION_MANAGE_USERS,
        ACTION_SYNC_O2,
        ACTION_VIEW_AUDIT,
        ACTION_VIEW_PERMISSION_POLICIES,
        ACTION_VIEW_PROVIDER_HEALTH,
    ):
        grant_user_role_capability(admin, action)

    assert user.get("/api/users").status_code == 200
    assert user.get("/api/agents").status_code == 200
    assert user.get("/api/agents/agent_research/tools").status_code == 200
    assert user.get("/api/users/permission-policies").status_code == 200
    assert user.get("/api/risk/policies").status_code == 200
    assert user.get("/api/health/providers").status_code == 200
    assert user.get("/api/integrations/o2/status").status_code == 200
    assert user.get("/api/audit").status_code == 200

    create_user = user.post(
        "/api/users",
        json={"name": "能力授权用户", "role": "user", "password": "testpass"},
    )
    create_policy = user.post(
        "/api/users/permission-policies",
        json={"role": "team_lead", "action": "view_audit", "effect": "allow"},
    )
    create_risk_policy = user.post(
        "/api/risk/policies",
        json={
            "rule_id": "capability_holder_rule",
            "category": "source_policy",
            "signal": "untrusted-source",
            "message": "Review the source",
            "decision": "needs_review",
            "enabled": True,
        },
    )
    update_agent = user.patch(
        "/api/agents/agent_research",
        json={"description": "由 capability holder 更新"},
    )

    assert create_user.status_code == 200
    assert create_policy.status_code == 200
    assert create_risk_policy.status_code == 200
    assert update_agent.status_code == 200


def test_admin_mutation_capability_can_be_denied_by_central_policy() -> None:
    store.reset()
    admin = authenticated_client(ADMIN.id)
    response = admin.post(
        "/api/users/permission-policies",
        json={"role": "team_lead", "action": ACTION_MANAGE_USERS, "effect": "deny"},
    )
    assert response.status_code == 200

    lead = authenticated_client(TEAM_LEAD.id)
    denied = lead.post(
        "/api/users",
        json={"name": "不应创建", "role": "user", "password": "blocked-pass-123"},
    )

    assert denied.status_code == 403
