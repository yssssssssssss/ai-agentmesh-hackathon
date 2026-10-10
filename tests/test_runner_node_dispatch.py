from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from agentmesh.app import app
from agentmesh.models import AgentRun, AgentRunStatus, ChatThread, Scope, now_utc
from agentmesh.runner_contracts import (
    RunnerNodeDispatchStatus,
    RunnerNodeDispatchV1,
    RunnerSkillSnapshotV1,
)
from agentmesh.seed import PROJECT, USER
from agentmesh.store import store


def setup_function() -> None:
    store.reset()


def _capabilities() -> dict[str, object]:
    return {
        "schema_version": "runner-capabilities-v1",
        "platform": "darwin",
        "architecture": "arm64",
        "runner_version": "0.1.0",
        "protocol_version": "runner-v1",
        "tools": [],
        "model_capabilities": ["streaming"],
    }


def _enroll(client: TestClient) -> str:
    started = client.post(
        "/api/runner/enrollment/start",
        json={"device_name": "Node Runner", "capabilities": _capabilities()},
    ).json()
    assert (
        client.post(
            "/api/auth/login",
            json={"user_id": USER.id, "password": "designer123"},
        ).status_code
        == 200
    )
    assert client.post(f"/api/runner/enrollment/{started['user_code']}/approve").status_code == 200
    assert (
        client.post(
            "/api/runner/enrollment/token",
            json={"device_code": started["device_code"]},
        ).status_code
        == 200
    )
    return str(started["device_code"])


def test_runner_claims_and_completes_standard_skill_node(monkeypatch) -> None:
    monkeypatch.setenv("AGENTMESH_EXECUTION_LOCATION", "runner")
    client = TestClient(app)
    token = _enroll(client)
    thread = store.save_chat_thread(
        ChatThread(
            id="thread_runner_node",
            workspace_id=USER.workspace_id,
            project_id=PROJECT.id,
            user_id=USER.id,
            title="Runner node",
            scope=Scope.PRIVATE,
        )
    )
    run = store.save_agent_run(
        AgentRun(
            id="run_runner_node",
            thread_id=thread.id,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=PROJECT.id,
            input_text="Build the deliverable",
            status=AgentRunStatus.RUNNING,
            execution_location="runner",
            plan_id="plan_runner_node",
        )
    )
    now = now_utc()
    dispatch = store.create_runner_node_dispatch(
        RunnerNodeDispatchV1(
            id="runner_node_dispatch_test",
            run_id=run.id,
            plan_id="plan_runner_node",
            node_id="node_1",
            attempt=1,
            owner_user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=PROJECT.id,
            thread_id=thread.id,
            skill=RunnerSkillSnapshotV1(
                id="skill_test",
                name="test-skill",
                title="Test Skill",
                version="1",
                content_hash="skill-hash",
            ),
            instructions="Return a structured node result.",
            node_prompt={"goal": "Build the deliverable"},
            model_id="default",
            deadline_at=now + timedelta(minutes=5),
            created_at=now,
            updated_at=now,
        )
    )
    assert dispatch.status is RunnerNodeDispatchStatus.PENDING

    claim = client.post(
        "/api/runner/dispatches/claim",
        headers={"Authorization": f"Bearer {token}"},
        json={"capabilities": _capabilities()},
    )
    assert claim.status_code == 200
    envelope = claim.json()["envelope"]
    assert envelope["operation_kind"] == "standard_skill_node"
    assert envelope["plan_id"] == "plan_runner_node"
    assert envelope["node_id"] == "node_1"

    completed = client.post(
        f"/api/runner/dispatches/{envelope['lease_id']}/node-complete",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "command_id": "node-complete-1",
            "result_payload": {
                "node_id": "node_1",
                "skill_id": "skill_test",
                "summary": "Completed",
                "deliverable_markdown": "# Deliverable",
            },
            "requested_model": "default",
            "actual_model": "local-model",
            "total_tokens": 10,
        },
    )

    assert completed.status_code == 200
    persisted = store.get_runner_node_dispatch(dispatch.id)
    assert persisted is not None
    assert persisted.status is RunnerNodeDispatchStatus.COMPLETED
    assert persisted.result_payload["summary"] == "Completed"
