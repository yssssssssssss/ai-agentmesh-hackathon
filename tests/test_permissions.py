"""Tests for auth edge cases, role permissions, memory state machine, and inbox behavior."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from agentmesh.app import app
from agentmesh.models import Scope, now_utc
from agentmesh.seed import ADMIN, TEAM, TEAM_LEAD, USER, WORKSPACE
from agentmesh.store import store


def clear_store() -> None:
    store.reset()


def password_for_user(user_id: str) -> str:
    return {
        USER.id: "designer123",
        TEAM_LEAD.id: "lead123",
        ADMIN.id: "admin123",
    }[user_id]


def authenticated_client(user_id: str = USER.id) -> TestClient:
    client = TestClient(app)
    login_response = client.post(
        "/api/auth/login",
        json={"user_id": user_id, "password": password_for_user(user_id)},
    )
    assert login_response.status_code == 200
    return client


# --- Auth edge cases ---


class TestAuthEdgeCases:
    def test_login_with_wrong_password_returns_401(self):
        clear_store()
        client = TestClient(app)
        response = client.post("/api/auth/login", json={"user_id": USER.id, "password": "wrongpass"})
        assert response.status_code == 401

    def test_login_with_nonexistent_user_returns_401(self):
        clear_store()
        client = TestClient(app)
        response = client.post("/api/auth/login", json={"user_id": "usr_ghost", "password": "any"})
        assert response.status_code == 401

    def test_auth_me_without_session_returns_401(self):
        clear_store()
        client = TestClient(app)
        response = client.get("/api/auth/me")
        assert response.status_code == 401

    def test_auth_me_with_valid_session(self):
        clear_store()
        client = authenticated_client()
        response = client.get("/api/auth/me")
        assert response.status_code == 200
        assert response.json()["user"]["id"] == USER.id

    def test_logout_clears_session(self):
        clear_store()
        client = authenticated_client()
        client.post("/api/auth/logout")
        response = client.get("/api/auth/me")
        assert response.status_code == 401

    def test_change_password_with_wrong_current_password(self):
        clear_store()
        client = authenticated_client()
        response = client.post(
            "/api/auth/password",
            json={"current_password": "wrongpassword", "new_password": "newpass123"},
        )
        assert response.status_code == 401

    def test_change_password_revokes_sessions(self):
        clear_store()
        client = authenticated_client()
        response = client.post(
            "/api/auth/password",
            json={"current_password": "designer123", "new_password": "newpass1234"},
        )
        assert response.status_code == 200
        # 旧 session 已失效
        response = client.get("/api/auth/me")
        assert response.status_code == 401

    def test_disabled_user_cannot_login(self):
        clear_store()
        admin_client = authenticated_client(ADMIN.id)
        # 禁用用户
        admin_client.patch(f"/api/users/{USER.id}", json={"status": "disabled"})
        # 被禁用用户尝试登录
        client = TestClient(app)
        response = client.post("/api/auth/login", json={"user_id": USER.id, "password": "designer123"})
        assert response.status_code == 401

    def test_disabled_user_existing_session_rejected(self):
        clear_store()
        user_client = authenticated_client()
        # 确认 session 有效
        assert user_client.get("/api/auth/me").status_code == 200
        # admin 禁用该用户
        admin_client = authenticated_client(ADMIN.id)
        admin_client.patch(f"/api/users/{USER.id}", json={"status": "disabled"})
        # 旧 session 被吊销
        response = user_client.get("/api/auth/me")
        assert response.status_code == 401


# --- Role permission checks ---


class TestRolePermissions:
    def test_regular_user_cannot_create_user(self):
        clear_store()
        client = authenticated_client()
        response = client.post("/api/users", json={"name": "New", "role": "user", "password": "pass12345"})
        assert response.status_code == 403

    def test_regular_user_cannot_disable_user(self):
        clear_store()
        client = authenticated_client()
        response = client.patch(f"/api/users/{TEAM_LEAD.id}", json={"status": "disabled"})
        assert response.status_code == 403

    def test_admin_can_create_user(self):
        clear_store()
        client = authenticated_client(ADMIN.id)
        response = client.post("/api/users", json={"name": "测试用户", "role": "user", "password": "pass12345"})
        assert response.status_code == 200
        new_user = response.json()["item"]
        assert new_user["name"] == "测试用户"
        assert new_user["personal_agent_id"].startswith("agent_personal_")

    def test_admin_can_reset_user_password(self):
        clear_store()
        client = authenticated_client(ADMIN.id)
        response = client.post(f"/api/users/{USER.id}/password", json={"new_password": "reset12345"})
        assert response.status_code == 200
        # 用新密码可以登录
        login_client = TestClient(app)
        login_response = login_client.post("/api/auth/login", json={"user_id": USER.id, "password": "reset12345"})
        assert login_response.status_code == 200

    def test_regular_user_cannot_reset_others_password(self):
        clear_store()
        client = authenticated_client()
        response = client.post(f"/api/users/{ADMIN.id}/password", json={"new_password": "hacked1234"})
        assert response.status_code == 403

    def test_regular_user_cannot_manage_other_agents(self):
        clear_store()
        client = authenticated_client()
        response = client.patch(f"/api/agents/{TEAM_LEAD.personal_agent_id}", json={"name": "hijacked"})
        assert response.status_code == 403

    def test_regular_user_can_manage_own_agent(self):
        clear_store()
        client = authenticated_client()
        response = client.patch(f"/api/agents/{USER.personal_agent_id}", json={"name": "我的新名字"})
        assert response.status_code == 200
        assert response.json()["name"] == "我的新名字"

    def test_admin_can_manage_any_agent(self):
        clear_store()
        client = authenticated_client(ADMIN.id)
        response = client.patch(f"/api/agents/{USER.personal_agent_id}", json={"description": "由管理员修改"})
        assert response.status_code == 200

    def test_regular_user_cannot_create_workspace(self):
        clear_store()
        client = authenticated_client()
        response = client.post("/api/workspaces", json={"name": "new-ws", "description": "test"})
        assert response.status_code == 403

    def test_regular_user_cannot_create_project(self):
        clear_store()
        client = authenticated_client()
        response = client.post("/api/projects", json={"workspace_id": WORKSPACE.id, "name": "proj", "goal": "test"})
        assert response.status_code == 403

    def test_regular_user_cannot_create_risk_policy(self):
        clear_store()
        client = authenticated_client()
        response = client.post(
            "/api/risk/policies",
            json={
                "rule_id": "test_rule",
                "category": "prompt_injection",
                "signal": "test",
                "message": "test",
                "decision": "block",
                "enabled": True,
            },
        )
        assert response.status_code == 403

    def test_admin_can_create_risk_policy(self):
        clear_store()
        client = authenticated_client(ADMIN.id)
        response = client.post(
            "/api/risk/policies",
            json={
                "rule_id": "admin_rule",
                "category": "prompt_injection",
                "signal": "eval\\(",
                "message": "Blocked eval",
                "decision": "block",
                "enabled": True,
            },
        )
        assert response.status_code == 200
        assert response.json()["item"]["rule_id"] == "admin_rule"

    def test_admin_can_manage_permission_policy_rules(self):
        clear_store()
        admin_client = authenticated_client(ADMIN.id)
        user_client = authenticated_client()

        create_response = admin_client.post(
            "/api/users/permission-policies",
            json={
                "role": "team_lead",
                "action": "accept_team_memory",
                "effect": "deny",
                "enabled": True,
                "description": "临时关闭团队记忆接受权限。",
            },
        )
        update_response = admin_client.patch(
            f"/api/users/permission-policies/{create_response.json()['item']['id']}",
            json={"enabled": False},
        )
        list_response = admin_client.get("/api/users/permission-policies")
        denied_list_response = user_client.get("/api/users/permission-policies")

        assert create_response.status_code == 200
        assert create_response.json()["item"]["effect"] == "deny"
        assert update_response.status_code == 200
        assert update_response.json()["item"]["enabled"] is False
        assert list_response.status_code == 200
        assert any(item["action"] == "accept_team_memory" for item in list_response.json()["items"])
        assert denied_list_response.status_code == 403

    def test_regular_user_cannot_create_permission_policy(self):
        clear_store()
        client = authenticated_client()

        response = client.post(
            "/api/users/permission-policies",
            json={"role": "team_lead", "action": "accept_team_memory", "effect": "deny"},
        )

        assert response.status_code == 403

    def test_permission_policy_can_deny_team_lead_team_memory_acceptance(self):
        clear_store()
        admin_client = authenticated_client(ADMIN.id)
        user_client = authenticated_client()
        lead_client = authenticated_client(TEAM_LEAD.id)
        admin_client.post(
            "/api/users/permission-policies",
            json={"role": "team_lead", "action": "accept_team_memory", "effect": "deny"},
        )
        create_response = user_client.post(
            "/api/memory",
            json={
                "title": "被策略拦截的团队记忆",
                "summary": "组长暂时不能接受。",
                "memory_type": "experience",
                "scope": "team_candidate",
            },
        )

        response = lead_client.patch(f"/api/memory/{create_response.json()['item']['id']}", json={"status": "accepted"})

        assert response.status_code == 403

    def test_permission_policy_can_deny_team_lead_public_agent_management(self):
        clear_store()
        admin_client = authenticated_client(ADMIN.id)
        lead_client = authenticated_client(TEAM_LEAD.id)
        admin_client.post(
            "/api/users/permission-policies",
            json={"role": "team_lead", "action": "manage_public_agent", "effect": "deny"},
        )

        response = lead_client.patch("/api/agents/agent_research", json={"description": "blocked"})

        assert response.status_code == 403

    def test_seed_team_membership_is_visible(self):
        clear_store()
        client = authenticated_client()

        response = client.get(f"/api/users/teams/{TEAM.id}")

        assert response.status_code == 200
        payload = response.json()["item"]
        assert payload["team"]["id"] == TEAM.id
        assert {member["user"]["id"] for member in payload["members"]} == {USER.id, TEAM_LEAD.id, ADMIN.id}

    def test_regular_user_cannot_manage_team_membership(self):
        clear_store()
        client = authenticated_client()

        response = client.post(
            f"/api/users/teams/{TEAM.id}/members",
            json={"user_id": USER.id, "role": "team_lead"},
        )
        delete_response = client.delete(f"/api/users/teams/{TEAM.id}/members/{USER.id}")

        assert response.status_code == 403
        assert delete_response.status_code == 403

    def test_admin_can_create_team_and_manage_membership(self):
        clear_store()
        client = authenticated_client(ADMIN.id)

        create_response = client.post(
            "/api/users/teams",
            json={"name": "体验设计组", "description": "用户体验方向。", "workspace_id": WORKSPACE.id},
        )
        team_id = create_response.json()["item"]["id"]
        add_response = client.post(
            f"/api/users/teams/{team_id}/members",
            json={"user_id": USER.id, "role": "user"},
        )
        detail_response = client.get(f"/api/users/teams/{team_id}")
        delete_response = client.delete(f"/api/users/teams/{team_id}/members/{USER.id}")
        detail_after_delete = client.get(f"/api/users/teams/{team_id}")

        assert create_response.status_code == 200
        assert add_response.status_code == 200
        assert detail_response.status_code == 200
        assert [member["user"]["id"] for member in detail_response.json()["item"]["members"]] == [USER.id]
        assert delete_response.status_code == 200
        assert detail_after_delete.json()["item"]["members"] == []


# --- Memory state machine ---


class TestMemoryStateMachine:
    def test_create_memory_with_private_scope(self):
        clear_store()
        client = authenticated_client()
        response = client.post(
            "/api/memory",
            json={
                "title": "私有记忆",
                "summary": "仅自己可见",
                "memory_type": "note",
                "scope": "private",
            },
        )
        assert response.status_code == 200
        item = response.json()["item"]
        assert item["scope"] == "private"
        assert item["status"] == "proposed"

    def test_regular_user_cannot_accept_team_memory(self):
        clear_store()
        client = authenticated_client()
        # 先创建一个记忆
        create_response = client.post(
            "/api/memory",
            json={
                "title": "候选记忆",
                "summary": "待审核",
                "memory_type": "experience",
                "scope": "team_candidate",
            },
        )
        item_id = create_response.json()["item"]["id"]
        # 普通用户不能接受团队记忆
        response = client.patch(f"/api/memory/{item_id}", json={"status": "accepted"})
        assert response.status_code == 403

    def test_team_lead_can_accept_team_memory(self):
        clear_store()
        user_client = authenticated_client()
        lead_client = authenticated_client(TEAM_LEAD.id)
        # 用户创建候选记忆
        create_response = user_client.post(
            "/api/memory",
            json={
                "title": "可接受记忆",
                "summary": "Team lead 审核",
                "memory_type": "methodology",
                "scope": "team_candidate",
            },
        )
        item_id = create_response.json()["item"]["id"]
        # Team lead 接受
        response = lead_client.patch(f"/api/memory/{item_id}", json={"status": "accepted"})
        assert response.status_code == 200
        item = response.json()["item"]
        assert item["status"] == "accepted"
        assert item["scope"] == "team_accepted"

    def test_accept_memory_auto_promotes_scope(self):
        clear_store()
        admin_client = authenticated_client(ADMIN.id)
        user_client = authenticated_client()
        create_response = user_client.post(
            "/api/memory",
            json={
                "title": "Auto promote",
                "summary": "Should become team_accepted",
                "memory_type": "experience",
                "scope": "team_candidate",
            },
        )
        item_id = create_response.json()["item"]["id"]
        response = admin_client.patch(f"/api/memory/{item_id}", json={"status": "accepted"})
        assert response.status_code == 200
        assert response.json()["item"]["scope"] == "team_accepted"

    def test_team_candidate_memory_is_review_visible_before_acceptance(self):
        clear_store()
        user_client = authenticated_client()
        lead_client = authenticated_client(TEAM_LEAD.id)
        create_response = lead_client.post(
            "/api/memory",
            json={
                "title": "待审核团队记忆",
                "summary": "普通成员不应在团队记忆列表看到它。",
                "memory_type": "experience",
                "scope": "team_candidate",
            },
        )
        item_id = create_response.json()["item"]["id"]

        user_items = user_client.get("/api/memory").json()["items"]
        lead_items = lead_client.get("/api/memory").json()["items"]
        lead_client.patch(f"/api/memory/{item_id}", json={"status": "accepted"})
        accepted_user_items = user_client.get("/api/memory").json()["items"]

        assert item_id not in [item["id"] for item in user_items]
        assert item_id in [item["id"] for item in lead_items]
        assert item_id in [item["id"] for item in accepted_user_items]

    def test_regular_user_can_dispute_memory(self):
        clear_store()
        client = authenticated_client()
        create_response = client.post(
            "/api/memory",
            json={
                "title": "Disputable",
                "summary": "To be disputed",
                "memory_type": "note",
                "scope": "private",
            },
        )
        item_id = create_response.json()["item"]["id"]
        response = client.patch(f"/api/memory/{item_id}", json={"status": "disputed"})
        assert response.status_code == 200
        assert response.json()["item"]["status"] == "disputed"

    def test_update_nonexistent_memory_returns_404(self):
        clear_store()
        client = authenticated_client()
        response = client.patch("/api/memory/nonexistent_id", json={"status": "deprecated"})
        assert response.status_code == 404


# --- Inbox behavior ---


class TestInboxBehavior:
    def _create_inbox_item(self):
        """直接在 store 中创建 inbox item 用于测试。"""
        from agentmesh.models import InboxItem

        item = InboxItem(
            title="测试确认项",
            summary="需要人工审核",
            item_type="memory_confirmation",
            scope=Scope.PROJECT,
            user_id=USER.id,
        )
        store.add_inbox_item(item)
        return item

    def test_inbox_list_excludes_resolved(self):
        clear_store()
        client = authenticated_client()
        item = self._create_inbox_item()
        # resolve it
        client.patch(f"/api/inbox/{item.id}", json={"status": "resolved"})
        # 默认列表不包含 resolved
        response = client.get("/api/inbox")
        assert response.status_code == 200
        ids = [i["id"] for i in response.json()["items"]]
        assert item.id not in ids

    def test_inbox_snooze_requires_future_time(self):
        clear_store()
        client = authenticated_client()
        item = self._create_inbox_item()
        # snooze_until 在过去应失败
        past = (now_utc() - timedelta(hours=1)).isoformat()
        response = client.patch(f"/api/inbox/{item.id}", json={"status": "snoozed", "snooze_until": past})
        assert response.status_code == 400

    def test_inbox_snooze_with_ttl(self):
        clear_store()
        client = authenticated_client()
        item = self._create_inbox_item()
        response = client.patch(f"/api/inbox/{item.id}", json={"status": "snoozed", "ttl_minutes": 60})
        assert response.status_code == 200
        data = response.json()["item"]
        assert data["status"] == "snoozed"
        assert data["snooze_until"] is not None

    def test_inbox_cannot_use_both_ttl_and_snooze_until(self):
        clear_store()
        client = authenticated_client()
        item = self._create_inbox_item()
        future = (now_utc() + timedelta(hours=1)).isoformat()
        response = client.patch(
            f"/api/inbox/{item.id}",
            json={"status": "snoozed", "ttl_minutes": 30, "snooze_until": future},
        )
        assert response.status_code == 400

    def test_inbox_resolve_sets_resolved_at(self):
        clear_store()
        client = authenticated_client()
        item = self._create_inbox_item()
        response = client.patch(f"/api/inbox/{item.id}", json={"status": "resolved"})
        assert response.status_code == 200
        data = response.json()["item"]
        assert data["resolved_at"] is not None
        assert data["acknowledged_at"] is not None

    def test_inbox_update_nonexistent_returns_404(self):
        clear_store()
        client = authenticated_client()
        response = client.patch("/api/inbox/nonexistent_id", json={"status": "resolved"})
        assert response.status_code == 404

    def test_inbox_invalid_status_returns_400(self):
        clear_store()
        client = authenticated_client()
        item = self._create_inbox_item()
        response = client.patch(f"/api/inbox/{item.id}", json={"status": "invalid_status"})
        assert response.status_code == 400

    def test_snoozed_item_reappears_after_expiry(self):
        clear_store()
        client = authenticated_client()
        item = self._create_inbox_item()
        # snooze 到过去（模拟到期）

        item.status = "snoozed"
        item.snooze_until = now_utc() - timedelta(minutes=1)
        store.save_inbox_item(item)
        # 查询 active items 时应该重新出现
        response = client.get("/api/inbox")
        assert response.status_code == 200
        ids = [i["id"] for i in response.json()["items"]]
        assert item.id in ids

    def test_inbox_private_items_are_hidden_from_other_users(self):
        clear_store()
        user_client = authenticated_client()
        other_client = authenticated_client(TEAM_LEAD.id)
        item = self._create_inbox_item()
        item.scope = Scope.PRIVATE
        item.workspace_id = WORKSPACE.id
        item.project_id = USER.default_project_id
        store.save_inbox_item(item)

        user_items = user_client.get("/api/inbox").json()["items"]
        other_items = other_client.get("/api/inbox").json()["items"]

        assert item.id in [row["id"] for row in user_items]
        assert item.id not in [row["id"] for row in other_items]
