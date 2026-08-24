from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import agentmesh.routes.skills as skill_routes
from agentmesh.app import app
from agentmesh.models import ChatThread
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.store import SQLiteStore
from agentmesh.task_routing.contracts import TaskRoutingPreviewRequest


def test_task_routing_preview_returns_catalog_bound_route() -> None:
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"user_id": USER.id, "password": "designer123"}).status_code == 200

    response = client.post(
        "/api/skills/routing-preview",
        json={
            "content": (
                "请基于2025-2026年公开资料研究宠物主粮在品牌App和电商平台的用户心智，"
                "输出策略地图、设计原则、机会点和P0/P1/P2行动。"
            )
        },
    )

    assert response.status_code == 200
    payload = response.json()
    result = payload["routing_result"]
    assert result["task"]["task_id"] == "define-strategy"
    assert result["evidence_requirement"]["external_evidence_required"] is True
    assert "competitor-benchmark-research" in {
        result["scenario"]["scenario_id"],
        *result["scenario"]["supporting_scenarios"],
    }
    assert payload["diagnostics"][0] == "deterministic_task_router"
    assert "instructions" not in response.text


def test_task_routing_preview_rejects_foreign_thread(tmp_path, monkeypatch) -> None:
    repository = SQLiteStore(tmp_path / "routing-preview.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    repository.save_chat_thread(
        ChatThread(
            id="thread_foreign",
            user_id="usr_someone_else",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            title="Foreign",
        )
    )
    monkeypatch.setattr(skill_routes, "store", repository)

    with pytest.raises(HTTPException) as error:
        skill_routes.preview_task_routing(
            TaskRoutingPreviewRequest(content="帮我看看竞品", thread_id="thread_foreign"),
            user=USER,
        )

    assert error.value.status_code == 404


def test_task_routing_preview_rechecks_project_access(tmp_path, monkeypatch) -> None:
    repository = SQLiteStore(tmp_path / "routing-preview-recheck.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)

    class RevokingRouter:
        def route(self, content: str, **_kwargs):
            project = repository.get_project(USER.default_project_id)
            assert project is not None
            repository.save_project(project.model_copy(update={"member_ids": ["usr_someone_else"]}))
            return skill_routes.TaskScenarioRouter().route(content)

    monkeypatch.setattr(skill_routes, "store", repository)
    monkeypatch.setattr(skill_routes, "_task_router", RevokingRouter())

    with pytest.raises(HTTPException) as error:
        skill_routes.preview_task_routing(
            TaskRoutingPreviewRequest(content="帮我看看竞品"),
            user=USER,
        )

    assert error.value.status_code == 404
