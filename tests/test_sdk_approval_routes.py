from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from agents.testing import ScriptedModel, assistant_message, function_call
from fastapi.testclient import TestClient

import agentmesh.routes.chat as chat_routes
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.app import app
from agentmesh.models import AgentRun, AgentRunStatus, AgentToolGrant, InboxItem, Scope, now_utc
from agentmesh.seed import USER
from agentmesh.store import store
from agentmesh.tools import ensure_tool_seed_data


def test_expired_tool_approval_is_resolved_without_execution() -> None:
    run = store.save_agent_run(
        AgentRun(
            id="run_expired_approval",
            thread_id="thread_expired_approval",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="expired approval",
            status=AgentRunStatus.WAITING_APPROVAL,
            paused_state={"state": "expired"},
        )
    )
    item = store.add_inbox_item(
        InboxItem(
            id="inbox_expired_approval",
            title="Expired approval",
            summary="Expired",
            item_type="sdk_tool_approval",
            scope=Scope.PRIVATE,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            metadata={"run_id": run.id},
            created_at=now_utc() - timedelta(hours=25),
        )
    )
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"user_id": USER.id, "password": "designer123"}).status_code == 200

    response = client.post(
        f"/api/inbox/{item.id}/resolve-tool-approval",
        params={"action": "approve", "call_id": "expired-call"},
    )

    assert response.status_code == 409
    assert store.get_inbox_item(item.id).status == "resolved"  # type: ignore[union-attr]
    assert store.get_agent_run(run.id).status == AgentRunStatus.WAITING_APPROVAL  # type: ignore[union-attr]


def test_agent_run_approval_claim_is_atomic() -> None:
    run = store.save_agent_run(
        AgentRun(
            id="run_atomic_approval_claim",
            thread_id="thread_atomic_approval_claim",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="atomic approval",
            status=AgentRunStatus.WAITING_APPROVAL,
            paused_state={"state": "test"},
        )
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed = list(executor.map(lambda _: store.claim_agent_run_for_resume(run.id, USER.id), range(2)))

    assert sum(item is not None for item in claimed) == 1
    assert store.get_agent_run(run.id).status == AgentRunStatus.RUNNING


def test_route_preserves_json_for_remaining_call_scoped_approvals(monkeypatch) -> None:
    ensure_tool_seed_data(store, granted_by="system")
    store.save_agent_tool_grant(
        AgentToolGrant(
            id="grant_route_sdk_web_multi",
            agent_id=USER.personal_agent_id,
            tool_id="tool_web_research",
            granted_by="test",
        )
    )
    model = ScriptedModel(
        [
            [
                function_call("web_research", {"query": "first route"}, call_id="route_first"),
                function_call("web_research", {"query": "second route"}, call_id="route_second"),
            ],
            [assistant_message("Both route approvals completed")],
        ]
    )
    runtime = AgentRuntimeService(store, model=model, enabled=True)
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"user_id": USER.id, "password": "designer123"}).status_code == 200
    started = client.post(
        "/api/chat/messages",
        json={"content": "Research two route topics", "client_turn_id": "turn_sdk_route_multi"},
    )
    item = started.json()["inbox_items"][0]
    interruptions = json.loads(item["metadata"]["interruptions"])

    partial = client.post(
        f"/api/inbox/{item['id']}/resolve-tool-approval",
        params={"action": "approve", "call_id": interruptions[0]["call_id"]},
    )
    assert partial.status_code == 200
    assert partial.json()["waiting_approval"] is True
    remaining = json.loads(partial.json()["item"]["metadata"]["interruptions"])
    assert [entry["call_id"] for entry in remaining] == [interruptions[1]["call_id"]]

    completed = client.post(
        f"/api/inbox/{item['id']}/resolve-tool-approval",
        params={"action": "approve", "call_id": remaining[0]["call_id"]},
    )
    assert completed.status_code == 200
    assert completed.json()["answer"] == "Both route approvals completed"


def test_sdk_tool_approval_resumes_original_run(monkeypatch) -> None:
    ensure_tool_seed_data(store, granted_by="system")
    store.save_agent_tool_grant(
        AgentToolGrant(
            id="grant_route_sdk_web",
            agent_id=USER.personal_agent_id,
            tool_id="tool_web_research",
            granted_by="test",
        )
    )
    model = ScriptedModel(
        [
            [function_call("web_research", {"query": "route approval research"}, call_id="route_web_call")],
            [assistant_message("Approved route research answer")],
        ]
    )
    runtime = AgentRuntimeService(store, model=model, enabled=True)
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)

    client = TestClient(app)
    login = client.post("/api/auth/login", json={"user_id": USER.id, "password": "designer123"})
    assert login.status_code == 200
    response = client.post(
        "/api/chat/messages",
        json={
            "content": "Research route approval patterns",
            "client_turn_id": "turn_sdk_route_approval",
        },
    )

    assert response.status_code == 200
    item = response.json()["inbox_items"][0]
    assert item["item_type"] == "sdk_tool_approval"

    interruption = json.loads(item["metadata"]["interruptions"])[0]
    resolved = client.post(
        f"/api/inbox/{item['id']}/resolve-tool-approval",
        params={"action": "approve", "call_id": interruption["call_id"]},
    )

    assert resolved.status_code == 200
    assert resolved.json()["answer"] == "Approved route research answer"
    assert resolved.json()["item"]["status"] == "resolved"
    model.assert_complete()
