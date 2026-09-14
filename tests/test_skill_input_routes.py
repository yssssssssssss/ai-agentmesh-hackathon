from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

import agentmesh.routes.chat as chat_routes
from agentmesh.app import app
from agentmesh.models import (
    AgentRun,
    AgentRunStatus,
    RunDispatchReceiptV1,
    SkillInputContractSnapshotV1,
    SkillInputFieldV1,
    SkillInputRequestV1,
    now_utc,
)
from agentmesh.seed import TEAM_LEAD, USER
from agentmesh.store import store


def _login(client: TestClient, user_id: str = USER.id, password: str = "designer123") -> None:
    response = client.post("/api/auth/login", json={"user_id": user_id, "password": password})
    assert response.status_code == 200


def test_run_input_routes_upload_submit_and_replay(monkeypatch) -> None:
    run = store.save_agent_run(
        AgentRun(
            id="run_input_routes",
            thread_id="thread_input_routes",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="build metrics",
            status=AgentRunStatus.WAITING_INPUT,
        )
    )
    request = SkillInputRequestV1(
        id="input_request_routes",
        run_id=run.id,
        plan_id=None,
        contract_snapshots=[
            SkillInputContractSnapshotV1(
                node_id="direct",
                skill_id="skill_input_routes",
                skill_name="input-routes",
                skill_version="1",
                skill_content_hash="a" * 64,
                contract_hash="b" * 64,
                contract={"schema_version": "skill-user-input-v1"},
            )
        ],
        fields=[
            SkillInputFieldV1(
                id="direct.goal",
                node_id="direct",
                skill_id="skill_input_routes",
                skill_name="input-routes",
                field_id="goal",
                title="目标",
                required=True,
                value_kind="text",
                min_length=1,
            ),
            SkillInputFieldV1(
                id="direct.baseline",
                node_id="direct",
                skill_id="skill_input_routes",
                skill_name="input-routes",
                field_id="baseline",
                title="基线",
                required=True,
                value_kind="artifact",
                accepted_media_types=["text/csv"],
                required_columns=["date", "value"],
            ),
        ],
        missing_required_field_ids=["direct.goal", "direct.baseline"],
        next_run_status="running",
        expires_at=now_utc() + timedelta(hours=24),
    )
    created = store.create_skill_input_request(
        request,
        expected_run_statuses={AgentRunStatus.WAITING_INPUT},
    )
    assert created is not None

    resumed: list[str] = []

    class Runtime:
        enabled = True

        @staticmethod
        def new_dispatch_receipt(run_id: str, operation_kind: str) -> RunDispatchReceiptV1:
            return RunDispatchReceiptV1(
                operation_key="dispatch:input-routes",
                run_id=run_id,
                operation_kind=operation_kind,
            )

        @staticmethod
        def validate_input_resume(**_kwargs) -> None:
            return None

        @staticmethod
        async def resume_after_input(run_id: str, **_kwargs) -> AgentRun:
            resumed.append(run_id)
            persisted = store.get_agent_run(run_id)
            assert persisted is not None
            return persisted

    monkeypatch.setattr(chat_routes.agent, "agent_runtime", Runtime())
    client = TestClient(app)
    _login(client)

    read = client.get(f"/api/agent/runs/{run.id}/input-request")
    assert read.status_code == 200
    assert "contract" not in read.json()["item"]["contract_snapshots"][0]
    other_client = TestClient(app)
    _login(other_client, TEAM_LEAD.id, "lead123")
    assert other_client.get(f"/api/agent/runs/{run.id}/input-request").status_code == 404

    upload = client.post(
        f"/api/agent/runs/{run.id}/input-artifacts",
        data={"field_id": "direct.baseline", "expected_request_version": "1"},
        files={"file": ("baseline.csv", b"date,value\n2026-09-01,12\n", "text/csv")},
    )
    assert upload.status_code == 200
    artifact = upload.json()["item"]
    assert artifact["status"] == "ready"
    assert artifact["summary"]["columns"] == ["date", "value"]

    payload = {
        "client_turn_id": "input-routes-submit",
        "expected_request_version": 1,
        "text_values": {"direct.goal": "提升激活率"},
        "artifact_ids": {"direct.baseline": [artifact["id"]]},
    }
    submitted = client.post(f"/api/agent/runs/{run.id}/inputs", json=payload)
    assert submitted.status_code == 200
    assert submitted.json()["run"]["status"] == "running"
    assert submitted.json()["input_request"]["status"] == "complete"
    assert resumed == [run.id]

    replay = client.post(f"/api/agent/runs/{run.id}/inputs", json=payload)
    assert replay.status_code == 200
    assert replay.json()["input_request"]["version"] == 2
    assert resumed == [run.id]
    stale_upload = client.post(
        f"/api/agent/runs/{run.id}/input-artifacts",
        data={"field_id": "direct.baseline", "expected_request_version": "1"},
        files={"file": ("baseline.csv", b"date,value\n2026-09-02,13\n", "text/csv")},
    )
    assert stale_upload.status_code == 409
    assert stale_upload.json()["detail"]["code"] == "input_request_state_conflict"
