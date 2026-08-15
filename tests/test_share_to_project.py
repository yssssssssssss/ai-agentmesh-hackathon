"""Tests for A1: share personal memory to project scope."""

from __future__ import annotations

from fastapi.testclient import TestClient

from agentmesh.app import app
from agentmesh.models import (
    MemoryLayer,
    MemoryStatus,
    Scope,
    UserMemoryItem,
)
from agentmesh.seed import PROJECT, TEAM_LEAD, USER, WORKSPACE
from agentmesh.store import store


def _password(user_id: str) -> str:
    return {USER.id: "designer123", TEAM_LEAD.id: "lead123"}[user_id]


def _authenticated_client(user_id: str = USER.id) -> TestClient:
    client = TestClient(app)
    resp = client.post("/api/auth/login", json={"user_id": user_id, "password": _password(user_id)})
    assert resp.status_code == 200
    return client


def _create_user_memory(project_id: str | None = None) -> UserMemoryItem:
    item = UserMemoryItem(
        user_id=USER.id,
        layer=MemoryLayer.MID_TERM,
        title="首屏性能优化方案",
        summary="通过骨架屏和懒加载将首屏时间从3秒降至1.5秒",
        source_kind="note",
        memory_type="decision",
        workspace_id=WORKSPACE.id,
        project_id=project_id or PROJECT.id,
    )
    return store.add_user_memory_item(item)


class TestShareToProject:
    def setup_method(self) -> None:
        store.reset()

    def test_share_creates_team_candidate_for_project_review(self) -> None:
        item = _create_user_memory()
        client = _authenticated_client()
        resp = client.post(f"/api/memory/user/{item.id}/share-to-project")
        assert resp.status_code == 200
        data = resp.json()
        assert data["item"]["scope"] == Scope.TEAM_CANDIDATE.value
        assert data["item"]["title"] == item.title
        assert data["item"]["summary"] == item.summary
        assert data["item"]["project_id"] == PROJECT.id

    def test_shared_memory_status_is_proposed(self) -> None:
        item = _create_user_memory()
        client = _authenticated_client()
        resp = client.post(f"/api/memory/user/{item.id}/share-to-project")
        data = resp.json()
        assert data["item"]["status"] == MemoryStatus.PROPOSED.value

    def test_share_creates_lineage_relation(self) -> None:
        item = _create_user_memory()
        client = _authenticated_client()
        resp = client.post(f"/api/memory/user/{item.id}/share-to-project")
        shared_id = resp.json()["item"]["id"]
        relations = [r for r in store.memory_relations if r.from_memory_id == shared_id]
        assert len(relations) == 1
        assert relations[0].to_source_id == item.id
        assert relations[0].relation_type == "shared_from_personal"

    def test_share_nonexistent_item_returns_404(self) -> None:
        client = _authenticated_client()
        resp = client.post("/api/memory/user/umem_nonexistent/share-to-project")
        assert resp.status_code == 404

    def test_share_other_users_item_returns_404(self) -> None:
        item = UserMemoryItem(
            user_id="other_user_id",
            layer=MemoryLayer.SHORT_TERM,
            title="别人的记忆",
            summary="不属于当前用户",
            source_kind="note",
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
        )
        store.add_user_memory_item(item)
        client = _authenticated_client()
        resp = client.post(f"/api/memory/user/{item.id}/share-to-project")
        assert resp.status_code == 404

    def test_share_item_without_project_returns_400(self) -> None:
        item = _create_user_memory(project_id=None)
        # Force project_id to None after creation
        item.project_id = None
        store.save_user_memory_item(item)
        client = _authenticated_client()
        resp = client.post(f"/api/memory/user/{item.id}/share-to-project")
        assert resp.status_code == 400

    def test_accepted_candidate_is_searchable_as_team_memory(self) -> None:
        item = _create_user_memory()
        client = _authenticated_client()
        share_response = client.post(f"/api/memory/user/{item.id}/share-to-project")
        candidate_id = share_response.json()["item"]["id"]
        lead_client = _authenticated_client(TEAM_LEAD.id)
        accepted = lead_client.patch(f"/api/memory/{candidate_id}", json={"status": "accepted"})
        assert accepted.status_code == 200
        results = store.search(
            "首屏性能",
            {Scope.TEAM_ACCEPTED},
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
            user_id=TEAM_LEAD.id,
        )
        team_results = [r for r in results if r.result_type == "memory_item" and r.scope == Scope.TEAM_ACCEPTED]
        assert len(team_results) >= 1
        assert any("首屏" in r.title for r in team_results)
