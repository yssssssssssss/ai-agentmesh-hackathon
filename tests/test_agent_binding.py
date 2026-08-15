"""Tests for P4: Agent Memory Binding."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentmesh.app import app
from agentmesh.models import (
    Agent,
    AgentMemoryBinding,
    MemoryItem,
    MemoryStatus,
    Scope,
)
from agentmesh.seed import PROJECT, USER, WORKSPACE
from agentmesh.store import SQLiteStore, store


def _password(user_id: str) -> str:
    return {"usr_current_designer": "designer123", "usr_team_lead": "lead123", "usr_admin": "admin123"}[user_id]


def _authenticated_client(user_id: str = USER.id) -> TestClient:
    client = TestClient(app)
    resp = client.post("/api/auth/login", json={"user_id": user_id, "password": _password(user_id)})
    assert resp.status_code == 200
    return client


def _fresh_store() -> SQLiteStore:
    db_path = Path(tempfile.mktemp(suffix=".sqlite3"))
    return SQLiteStore(db_path=db_path)


class TestSearchForAgent:
    def test_no_binding_returns_full_results(self) -> None:
        s = _fresh_store()
        s.add_memory_item(
            MemoryItem(
                title="部署规范文档",
                summary="团队规范",
                memory_type="standard",
                scope=Scope.TEAM_ACCEPTED,
                status=MemoryStatus.ACCEPTED,
                workspace_id="ws1",
            )
        )
        results = s.search_for_agent("部署规范", "unknown_agent", workspace_id="ws1")
        assert len(results) == 1

    def test_binding_limits_scope(self) -> None:
        s = _fresh_store()
        agent = Agent(
            workspace_id="ws1", name="研究Agent", agent_type="service",
            description="only team", owner_user_id="user_a",
        )
        s._upsert("agents", agent)
        s.add_agent_memory_binding(
            AgentMemoryBinding(
                agent_id=agent.id,
                allowed_scopes=[Scope.TEAM_ACCEPTED],
                max_results_per_query=5,
            )
        )
        s.add_memory_item(
            MemoryItem(
                title="团队部署规范",
                summary="公开的团队规范",
                memory_type="standard",
                scope=Scope.TEAM_ACCEPTED,
                status=MemoryStatus.ACCEPTED,
                workspace_id="ws1",
            )
        )
        s.add_memory_item(
            MemoryItem(
                title="项目部署私密",
                summary="项目内部规范",
                memory_type="standard",
                scope=Scope.PROJECT,
                status=MemoryStatus.ACCEPTED,
                workspace_id="ws1",
            )
        )
        results = s.search_for_agent("部署", agent.id, workspace_id="ws1")
        assert all(r.scope == Scope.TEAM_ACCEPTED for r in results)

    def test_binding_limits_memory_types(self) -> None:
        s = _fresh_store()
        agent = Agent(
            workspace_id="ws1", name="Doc Agent", agent_type="service",
            description="only docs", owner_user_id="user_a",
        )
        s._upsert("agents", agent)
        s.add_agent_memory_binding(
            AgentMemoryBinding(
                agent_id=agent.id,
                allowed_scopes=[Scope.TEAM_ACCEPTED],
                allowed_memory_types=["document"],
                max_results_per_query=10,
            )
        )
        s.add_memory_item(
            MemoryItem(
                title="团队部署规范",
                summary="规范内容",
                memory_type="standard",
                scope=Scope.TEAM_ACCEPTED,
                workspace_id="ws1",
            )
        )
        results = s.search_for_agent("部署", agent.id, workspace_id="ws1")
        # memory_item type not in allowed_memory_types=["document"]
        assert all(r.result_type == "document" for r in results)

    def test_binding_limits_max_results(self) -> None:
        s = _fresh_store()
        agent = Agent(
            workspace_id="ws1", name="Slim Agent", agent_type="service",
            description="limited", owner_user_id="user_a",
        )
        s._upsert("agents", agent)
        s.add_agent_memory_binding(
            AgentMemoryBinding(
                agent_id=agent.id,
                allowed_scopes=[Scope.TEAM_ACCEPTED],
                max_results_per_query=2,
            )
        )
        for i in range(5):
            s.add_memory_item(
                MemoryItem(
                    title=f"团队部署规范{i}",
                    summary=f"第{i}条团队部署规范",
                    memory_type="standard",
                    scope=Scope.TEAM_ACCEPTED,
                    workspace_id="ws1",
                )
            )
        results = s.search_for_agent("部署规范", agent.id, workspace_id="ws1")
        assert len(results) <= 2


class TestAgentBindingAPI:
    def setup_method(self) -> None:
        store.reset()

    def test_get_binding_empty(self) -> None:
        client = _authenticated_client()
        resp = client.get("/api/agents/nonexistent/memory-binding")
        assert resp.status_code == 200
        assert resp.json()["binding"] is None

    def test_set_and_get_binding(self) -> None:
        agent = Agent(
            id="agent_test_binding",
            workspace_id=WORKSPACE.id,
            name="Test Agent",
            agent_type="personal",
            description="test",
            owner_user_id=USER.id,
        )
        store._upsert("agents", agent)
        client = _authenticated_client()
        resp = client.put(
            f"/api/agents/{agent.id}/memory-binding",
            json={
                "agent_id": agent.id,
                "allowed_scopes": ["team_accepted"],
                "allowed_memory_types": ["memory_item"],
                "allowed_project_ids": [PROJECT.id],
                "max_results_per_query": 3,
            },
        )
        assert resp.status_code == 200
        data = resp.json()["binding"]
        assert data["allowed_scopes"] == ["team_accepted"]
        assert data["max_results_per_query"] == 3

        # Get it back
        resp2 = client.get(f"/api/agents/{agent.id}/memory-binding")
        assert resp2.json()["binding"]["agent_id"] == agent.id

    def test_delete_binding(self) -> None:
        agent = Agent(
            id="agent_del_bind",
            workspace_id=WORKSPACE.id,
            name="Del Agent",
            agent_type="personal",
            description="test",
            owner_user_id=USER.id,
        )
        store._upsert("agents", agent)
        store.add_agent_memory_binding(
            AgentMemoryBinding(agent_id=agent.id, allowed_scopes=[Scope.PRIVATE])
        )
        client = _authenticated_client()
        resp = client.delete(f"/api/agents/{agent.id}/memory-binding")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"
        assert store.get_binding_for_agent(agent.id) is None
