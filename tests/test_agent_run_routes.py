from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from agents.testing import ScriptedModel, assistant_message
from fastapi.testclient import TestClient

import agentmesh.routes.chat as chat_routes
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.app import app
from agentmesh.models import AgentRun, AgentRunStatus, Artifact, SkillOrchestrationRequestMode
from agentmesh.research_orchestration.artifacts import ArtifactDraft, ArtifactLease, ArtifactLineage, ArtifactStore
from agentmesh.research_orchestration.contracts import (
    AttemptStatus,
    ExecutionAttempt,
    ExecutionPlanVersion,
    RequirementVersion,
    ResearchPhase,
    ResearchStep,
    ResearchWorkflow,
    StepStatus,
    canonical_sha256,
)
from agentmesh.seed import TEAM_LEAD, USER
from agentmesh.store import SQLiteStore, store


def _login(client: TestClient, user_id: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"user_id": user_id, "password": password})
    assert response.status_code == 200


def test_agent_run_create_is_idempotent_by_client_turn(monkeypatch) -> None:
    runtime = AgentRuntimeService(
        store,
        model=ScriptedModel([[assistant_message("idempotent answer")]]),
        enabled=True,
    )
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)
    payload = {"content": "one durable turn", "client_turn_id": "agent-run-idempotency"}

    client = TestClient(app)
    _login(client, USER.id, "designer123")
    first = client.post("/api/agent/runs", json=payload)
    second = client.post("/api/agent/runs", json=payload)

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["item"]["id"] == first.json()["item"]["id"]
    thread_id = first.json()["item"]["thread_id"]
    matching = [message for message in store.list_thread_messages(thread_id) if message.content == payload["content"]]
    assert len(matching) == 1


def test_agent_run_idempotency_compares_the_requested_orchestration_mode(monkeypatch) -> None:
    runtime = AgentRuntimeService(
        store,
        model=ScriptedModel([[assistant_message("original answer")]]),
        enabled=True,
    )
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "off")
    payload = {
        "content": "mode-sensitive durable turn",
        "client_turn_id": "agent-run-mode-idempotency",
        "orchestration_mode": "auto",
    }
    client = TestClient(app)
    _login(client, USER.id, "designer123")

    first = client.post("/api/agent/runs", json=payload)
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "execute")
    repeated = client.post("/api/agent/runs", json=payload)
    conflicting = client.post(
        "/api/agent/runs",
        json={**payload, "orchestration_mode": "single"},
    )

    assert first.status_code == 202
    assert repeated.status_code == 202
    assert repeated.json()["item"]["id"] == first.json()["item"]["id"]
    assert conflicting.status_code == 409


def test_atomic_run_claim_rejects_concurrent_orchestration_mode_mismatch(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "run-mode-race.sqlite3")

    def claim(mode: SkillOrchestrationRequestMode) -> tuple[str, bool] | str:
        try:
            claimed, created = repository.claim_new_agent_run(
                AgentRun(
                    thread_id="thread_mode_race",
                    user_id="user_mode_race",
                    workspace_id="workspace_mode_race",
                    project_id="project_mode_race",
                    input_text="same content",
                    client_turn_id="turn_mode_race",
                    requested_orchestration_mode=mode,
                )
            )
        except RuntimeError as error:
            return str(error)
        return claimed.id, created

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                claim,
                [SkillOrchestrationRequestMode.AUTO, SkillOrchestrationRequestMode.SINGLE],
            )
        )

    assert sum(isinstance(outcome, tuple) and outcome[1] for outcome in outcomes) == 1
    assert outcomes.count("client_turn_id was already used for another Agent run") == 1


def test_compound_research_request_prefers_task_scenario_orchestration(monkeypatch) -> None:
    class RuntimeStub:
        enabled = True
        orchestrated_calls = 0

        async def start_orchestrated(self, **kwargs):
            self.orchestrated_calls += 1
            return AgentRun(
                id="run_compound_task_route",
                thread_id=kwargs["thread_id"],
                user_id=kwargs["user"].id,
                workspace_id=kwargs["user"].workspace_id,
                project_id=kwargs["user"].default_project_id,
                input_text=kwargs["content"],
                client_turn_id=kwargs["client_turn_id"],
                requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
                orchestration_mode=kwargs["mode"].value,
                status=AgentRunStatus.PLANNING,
            )

        async def start(self, **_kwargs):
            raise AssertionError("compound auto request must use task orchestration")

    runtime = RuntimeStub()
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "preview")
    monkeypatch.setenv("AGENTMESH_TASK_SCENARIO_ROUTING", "true")
    client = TestClient(app)
    _login(client, USER.id, "designer123")

    response = client.post(
        "/api/agent/runs",
        json={
            "content": "研究竞品与用户心智，输出策略地图、设计原则和P0/P1/P2。",
            "client_turn_id": "compound-task-route-dispatch",
            "orchestration_mode": "auto",
        },
    )

    assert response.status_code == 202
    assert runtime.orchestrated_calls == 1
    assert response.json()["item"]["orchestration_version"] == "v1"


def test_no_plan_retry_preserves_auto_orchestration(monkeypatch) -> None:
    prior = store.save_agent_run(
        AgentRun(
            id="run_retry_preserves_auto",
            thread_id="thread_retry_preserves_auto",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="需要公开资料的竞品策略研究",
            client_turn_id="turn_retry_preserves_auto_original",
            requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
            orchestration_mode="execute",
            status=AgentRunStatus.FAILED,
            error_code="PlannerUnavailable",
        )
    )

    class RuntimeStub:
        enabled = True
        orchestrated_calls = 0
        ordinary_calls = 0

        async def start_orchestrated(self, **kwargs):
            self.orchestrated_calls += 1
            return AgentRun(
                id="run_retry_preserves_auto_new",
                thread_id=kwargs["thread_id"],
                user_id=kwargs["user"].id,
                workspace_id=kwargs["user"].workspace_id,
                project_id=prior.project_id,
                input_text=kwargs["content"],
                client_turn_id=kwargs["client_turn_id"],
                retry_of_run_id=kwargs["retry_of_run_id"],
                requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
                orchestration_mode=kwargs["mode"].value,
                status=AgentRunStatus.PLANNING,
            )

        async def start(self, **_kwargs):
            self.ordinary_calls += 1
            raise AssertionError("auto retry must not use ordinary runtime.start")

    runtime = RuntimeStub()
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "execute")
    client = TestClient(app)
    _login(client, USER.id, "designer123")

    response = client.post(
        f"/api/agent/runs/{prior.id}/retry",
        json={"client_turn_id": "turn_retry_preserves_auto_new"},
    )

    assert response.status_code == 202
    assert runtime.orchestrated_calls == 1
    assert runtime.ordinary_calls == 0
    assert response.json()["item"]["requested_orchestration_mode"] == "auto"
    assert response.json()["item"]["retry_of_run_id"] == prior.id


def test_single_skill_retry_fails_closed_when_original_skill_is_unavailable(monkeypatch) -> None:
    prior = store.save_agent_run(
        AgentRun(
            id="run_retry_missing_single_skill",
            thread_id="thread_retry_missing_single_skill",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="run the removed skill",
            client_turn_id="turn_retry_missing_single_skill_original",
            skill_name="removed-skill",
            requested_orchestration_mode=SkillOrchestrationRequestMode.SINGLE,
            status=AgentRunStatus.FAILED,
        )
    )

    class RuntimeStub:
        enabled = True

        async def start(self, **_kwargs):
            raise AssertionError("missing explicit Skill must not fall back to general runtime")

    monkeypatch.setattr(chat_routes.agent, "agent_runtime", RuntimeStub())
    client = TestClient(app)
    _login(client, USER.id, "designer123")

    response = client.post(
        f"/api/agent/runs/{prior.id}/retry",
        json={"client_turn_id": "turn_retry_missing_single_skill_new"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "The original Skill is no longer ready or authorized"


def test_agent_run_events_and_artifact_are_owner_scoped() -> None:
    run = store.save_agent_run(
        AgentRun(
            id="run_route_contract",
            thread_id="thread_route_contract",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="route contract",
            status=AgentRunStatus.COMPLETED,
            output_text="done",
        )
    )
    store.append_agent_run_event(run.id, "run_completed", {"total_tokens": 4})
    artifact = store.save_artifact(
        Artifact(
            id="artifact_route_contract",
            run_id=run.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            artifact_type="tool_output",
            content_type="text/plain",
            content="full tool output",
        )
    )
    client = TestClient(app)
    _login(client, USER.id, "designer123")

    run_response = client.get(f"/api/agent/runs/{run.id}")
    events_response = client.get(f"/api/agent/runs/{run.id}/events")
    stream_response = client.get(f"/api/agent/runs/{run.id}/events/stream")
    artifact_response = client.get(f"/api/artifacts/{artifact.id}")

    assert run_response.status_code == 200
    assert events_response.status_code == 200
    assert events_response.json()["items"][-1]["event_type"] == "run_completed"
    assert stream_response.status_code == 200
    assert "event: run_completed" in stream_response.text
    assert artifact_response.status_code == 200
    assert artifact_response.text == "full tool output"

    _login(client, TEAM_LEAD.id, "lead123")
    assert client.get(f"/api/agent/runs/{run.id}").status_code == 404
    assert client.get(f"/api/artifacts/{artifact.id}").status_code == 404


def test_v2_artifact_route_returns_only_integrity_verified_sealed_content() -> None:
    run = store.save_agent_run(
        AgentRun(
            id="run_v2_artifact_route",
            thread_id="thread_v2_artifact_route",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="route verified Artifact",
            status=AgentRunStatus.PLANNING,
            orchestration_version="research-v2",
            orchestration_mode="execute",
        )
    )
    requirement_payload = {"goal": "compare"}
    requirement = store.add_research_requirement_version(
        RequirementVersion(
            id="requirement_v2_artifact_route",
            run_id=run.id,
            version=1,
            schema_version="research-task-v2",
            task_type="competitive_research",
            payload=requirement_payload,
            content_hash=canonical_sha256(requirement_payload),
        )
    )
    plan_payload = {"steps": [{"step_number": 1, "actor_type": "tool"}]}
    plan = store.add_research_plan_version(
        ExecutionPlanVersion(
            id="plan_v2_artifact_route",
            run_id=run.id,
            requirement_version_id=requirement.id,
            version=1,
            schema_version="execution-plan-v2",
            plan_hash=canonical_sha256(plan_payload),
            payload=plan_payload,
        )
    )
    now = datetime.now(UTC)
    attempt = store.add_research_attempt(
        ExecutionAttempt(
            id="attempt_v2_artifact_route",
            run_id=run.id,
            plan_version_id=plan.id,
            attempt_number=1,
            status=AttemptStatus.RUNNING,
            lease_owner="worker_route",
            lease_token="lease_route",
            fencing_epoch=1,
            lease_expires_at=now + timedelta(minutes=5),
            deadline_at=now + timedelta(minutes=10),
        )
    )
    store.add_research_step(
        ResearchStep(
            attempt_id=attempt.id,
            step_number=1,
            status=StepStatus.RUNNING,
            claim_epoch=1,
            started_at=now,
        )
    )
    store.create_research_workflow(
        ResearchWorkflow(
            run_id=run.id,
            phase=ResearchPhase.EXECUTION,
            active_requirement_version_id=requirement.id,
            active_plan_version_id=plan.id,
            active_attempt_id=attempt.id,
        )
    )
    lineage = ArtifactLineage(
        run_id=run.id,
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        requirement_version_id=requirement.id,
        plan_version_id=plan.id,
        attempt_id=attempt.id,
        step_number=1,
    )
    lease = ArtifactLease(owner="worker_route", token="lease_route", fencing_epoch=1)
    artifacts = ArtifactStore(store)
    sealed = artifacts.seal(
        lineage,
        ArtifactDraft(
            artifact_id="artifact_v2_route_sealed",
            kind="tool_result",
            schema_version="result-v1",
            content={"result": "verified"},
        ),
        lease=lease,
    )
    staging = artifacts.stage(
        lineage,
        artifact_id="artifact_v2_route_staging",
        kind="tool_result",
        schema_version="result-v1",
        lease=lease,
    )
    client = TestClient(app)
    _login(client, USER.id, "designer123")

    sealed_response = client.get(f"/api/artifacts/{sealed.artifact_id}")
    staging_response = client.get(f"/api/artifacts/{staging.id}")

    assert sealed_response.status_code == 200
    assert sealed_response.json() == {"result": "verified"}
    assert sealed_response.headers["X-AgentMesh-Artifact-Hash"] == sealed.content_hash
    assert sealed_response.headers["X-Content-Type-Options"] == "nosniff"
    assert sealed_response.headers["Content-Security-Policy"] == "default-src 'none'; sandbox"
    assert staging_response.status_code == 409
    assert staging_response.json()["detail"] == "artifact_not_ready"

    _login(client, TEAM_LEAD.id, "lead123")
    assert client.get(f"/api/artifacts/{sealed.artifact_id}").status_code == 404

    with store._connect() as connection:
        row = connection.execute(
            "SELECT payload FROM artifacts WHERE id = ?",
            (sealed.artifact_id,),
        ).fetchone()
        payload = json.loads(row["payload"])
        payload["verification_state"] = None
        payload["content"] = '{"result":"tampered"}'
        connection.execute(
            "UPDATE artifacts SET payload = ? WHERE id = ?",
            (json.dumps(payload), sealed.artifact_id),
        )

    _login(client, USER.id, "designer123")
    tampered_response = client.get(f"/api/artifacts/{sealed.artifact_id}")
    assert tampered_response.status_code == 409
    assert tampered_response.json()["detail"] == "artifact_integrity_failed"
    with store._connect() as connection:
        state = connection.execute(
            "SELECT verification_state FROM artifacts WHERE id = ?",
            (sealed.artifact_id,),
        ).fetchone()["verification_state"]
    assert state == "failed"
