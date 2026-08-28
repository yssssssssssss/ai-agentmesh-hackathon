from __future__ import annotations

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from agents.testing import ScriptedModel, assistant_message
from fastapi.testclient import TestClient

import agentmesh.routes.chat as chat_routes
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.app import app
from agentmesh.artifacts import V1VerifiedArtifactStore
from agentmesh.canonical_json import canonical_json_bytes
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    Artifact,
    ArtifactVerificationState,
    ChatThread,
    DeepSearchBudgetV1,
    SkillOrchestrationRequestMode,
)
from agentmesh.routes.deps import current_user
from agentmesh.seed import TEAM_LEAD, USER
from agentmesh.store import SQLiteStore, store


def _login(client: TestClient, user_id: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"user_id": user_id, "password": password})
    assert response.status_code == 200


def _save_historical_v2_run(run: AgentRun) -> AgentRun:
    """Seed a persisted historical row without reopening the retired writer."""

    legacy = run.model_copy(update={"orchestration_version": "v1", "writer_generation_epoch": None})
    store.claim_new_agent_run(legacy)
    with store._connect() as connection:
        connection.execute(
            "UPDATE agent_runs SET payload = ?, orchestration_version = ? WHERE id = ?",
            (run.model_dump_json(), "research-v2", run.id),
        )
    return run


def _insert_historical_artifact(artifact: Artifact) -> Artifact:
    """Insert a pre-existing v2 Artifact fixture without a production writer API."""

    with store._connect() as connection:
        connection.execute(
            """INSERT INTO artifacts(
                id, run_id, payload, created_at, workspace_id, project_id, user_id,
                artifact_type, content_type, truncated, verification_state, schema_version,
                content_hash, size_bytes, requirement_version_id, plan_version_id,
                attempt_id, step_number, purged_at, purged_by, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                artifact.id,
                artifact.run_id,
                artifact.model_dump_json(),
                artifact.created_at.isoformat(),
                artifact.workspace_id,
                artifact.project_id,
                artifact.user_id,
                artifact.artifact_type,
                artifact.content_type,
                int(artifact.truncated),
                artifact.verification_state.value if artifact.verification_state is not None else None,
                artifact.schema_version,
                artifact.content_hash,
                artifact.size_bytes,
                artifact.requirement_version_id,
                artifact.plan_version_id,
                artifact.attempt_id,
                artifact.step_number,
                artifact.purged_at.isoformat() if artifact.purged_at is not None else None,
                artifact.purged_by,
                artifact.updated_at.isoformat() if artifact.updated_at is not None else None,
            ),
        )
    return artifact


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


def test_competitive_research_falls_back_to_v1_without_touching_retired_v2_runtime(monkeypatch) -> None:
    class RuntimeStub:
        enabled = True
        orchestrated_calls = 0

        async def start_orchestrated(self, **kwargs):
            self.orchestrated_calls += 1
            return AgentRun(
                id="run_competitive_v1_fallback",
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
            raise AssertionError("eligible auto request must use the v1 DAG")

    runtime = RuntimeStub()
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "preview")
    monkeypatch.setenv("AGENTMESH_TASK_SCENARIO_ROUTING", "false")
    client = TestClient(app)
    _login(client, USER.id, "designer123")

    response = client.post(
        "/api/agent/runs",
        json={
            "content": "对比淘宝和拼多多的协作能力并分析差异",
            "client_turn_id": "competitive-v1-after-v2-retirement",
            "orchestration_mode": "auto",
        },
    )

    assert response.status_code == 202
    assert runtime.orchestrated_calls == 1
    assert response.json()["item"]["orchestration_version"] == "v1"


def test_existing_v2_client_turn_replay_precedes_live_routing(
    monkeypatch,
) -> None:
    prior = _save_historical_v2_run(
        AgentRun(
            id="run_existing_v2_client_turn",
            thread_id="thread_existing_v2_client_turn",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="对比淘宝和拼多多的协作能力并分析差异",
            client_turn_id="existing-v2-client-turn",
            requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
            orchestration_version="research-v2",
            orchestration_mode="preview",
            status=AgentRunStatus.FAILED,
        )
    )

    class ForbiddenRuntime:
        enabled = True

        def __getattribute__(self, name):  # noqa: ANN001, ANN204
            if name != "enabled":
                raise AssertionError("client-turn replay must not dispatch any Runtime")
            return super().__getattribute__(name)

    monkeypatch.setattr(chat_routes.agent, "agent_runtime", ForbiddenRuntime())
    client = TestClient(app)
    _login(client, USER.id, "designer123")

    response = client.post(
        "/api/agent/runs",
        json={
            "content": prior.input_text,
            "client_turn_id": prior.client_turn_id,
            "orchestration_mode": "auto",
        },
    )

    assert response.status_code == 202
    assert response.json()["item"]["id"] == prior.id
    assert response.json()["item"]["orchestration_version"] == "research-v2"


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


@pytest.mark.parametrize("corruption", ["hash", "index", "owner_index", "noncanonical_json"])
def test_v2_artifact_route_returns_only_integrity_verified_sealed_content(corruption: str) -> None:
    suffix = corruption
    run = _save_historical_v2_run(
        AgentRun(
            id=f"run_v2_artifact_route_{suffix}",
            thread_id=f"thread_v2_artifact_route_{suffix}",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="route verified Artifact",
            status=AgentRunStatus.PLANNING,
            orchestration_version="research-v2",
            orchestration_mode="execute",
        )
    )
    content = '{"result":"verified"}'
    sealed = _insert_historical_artifact(
        Artifact(
            id=f"artifact_v2_route_sealed_{suffix}",
            run_id=run.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            artifact_type="tool_result",
            content_type="application/json",
            content=content,
            verification_state=ArtifactVerificationState.SEALED,
            schema_version="result-v1",
            content_hash=hashlib.sha256(content.encode()).hexdigest(),
            size_bytes=len(content.encode()),
            requirement_version_id=f"requirement_v2_artifact_route_{suffix}",
            plan_version_id=f"plan_v2_artifact_route_{suffix}",
            attempt_id=f"attempt_v2_artifact_route_{suffix}",
            step_number=1,
        )
    )
    staging = _insert_historical_artifact(
        Artifact(
            id=f"artifact_v2_route_staging_{suffix}",
            run_id=run.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            artifact_type="tool_result",
            content_type="application/json",
            content="",
            verification_state=ArtifactVerificationState.STAGING,
            schema_version="result-v1",
            requirement_version_id=f"requirement_v2_artifact_route_{suffix}",
            plan_version_id=f"plan_v2_artifact_route_{suffix}",
            attempt_id=f"attempt_v2_artifact_route_{suffix}",
            step_number=1,
        )
    )
    client = TestClient(app)
    _login(client, USER.id, "designer123")

    sealed_response = client.get(f"/api/artifacts/{sealed.id}")
    staging_response = client.get(f"/api/artifacts/{staging.id}")

    assert sealed_response.status_code == 200
    assert sealed_response.json() == {"result": "verified"}
    assert sealed_response.headers["X-AgentMesh-Artifact-Hash"] == sealed.content_hash
    assert sealed_response.headers["X-Content-Type-Options"] == "nosniff"
    assert sealed_response.headers["Content-Security-Policy"] == "default-src 'none'; sandbox"
    assert staging_response.status_code == 409
    assert staging_response.json()["detail"] == "artifact_not_ready"

    _login(client, TEAM_LEAD.id, "lead123")
    assert client.get(f"/api/artifacts/{sealed.id}").status_code == 404

    with store._connect() as connection:
        row = connection.execute(
            "SELECT payload, content_hash, size_bytes FROM artifacts WHERE id = ?",
            (sealed.id,),
        ).fetchone()
        payload = json.loads(row["payload"])
        if corruption == "hash":
            payload["content"] = '{"result":"tampered"}'
            connection.execute(
                "UPDATE artifacts SET payload = ? WHERE id = ?",
                (json.dumps(payload), sealed.id),
            )
        elif corruption == "index":
            connection.execute(
                "UPDATE artifacts SET size_bytes = size_bytes + 1 WHERE id = ?",
                (sealed.id,),
            )
        elif corruption == "owner_index":
            connection.execute(
                "UPDATE artifacts SET user_id = ? WHERE id = ?",
                (TEAM_LEAD.id, sealed.id),
            )
        else:
            noncanonical = '{"result": "verified"}'
            content_hash = hashlib.sha256(noncanonical.encode()).hexdigest()
            payload["content"] = noncanonical
            payload["content_hash"] = content_hash
            payload["size_bytes"] = len(noncanonical.encode())
            connection.execute(
                """UPDATE artifacts
                SET payload = ?, content_hash = ?, size_bytes = ?
                WHERE id = ?""",
                (json.dumps(payload), content_hash, payload["size_bytes"], sealed.id),
            )

    app.dependency_overrides[current_user] = lambda: USER
    try:
        with sqlite3.connect(store.db_path) as observer:
            observer.row_factory = sqlite3.Row
            before_version = int(observer.execute("PRAGMA data_version").fetchone()[0])
            before_row = observer.execute(
                "SELECT payload, content_hash, size_bytes, verification_state FROM artifacts WHERE id = ?",
                (sealed.id,),
            ).fetchone()
            tampered_response = client.get(f"/api/artifacts/{sealed.id}")
            after_version = int(observer.execute("PRAGMA data_version").fetchone()[0])
            after_row = observer.execute(
                "SELECT payload, content_hash, size_bytes, verification_state FROM artifacts WHERE id = ?",
                (sealed.id,),
            ).fetchone()
    finally:
        app.dependency_overrides.pop(current_user, None)

    assert tampered_response.status_code == 409
    assert tampered_response.json()["detail"] == "artifact_integrity_failed"
    assert after_version == before_version
    assert after_row == before_row
    assert after_row["verification_state"] == "sealed"


def test_v1_deepsearch_artifact_route_returns_only_sealed_content() -> None:
    created_at = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    thread = store.add_chat_thread(
        ChatThread(
            id="thread_v1_deepsearch_artifact_route",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            title="DeepSearch artifact route",
            created_at=created_at,
            updated_at=created_at,
        )
    )
    run, created = store.claim_new_agent_run(
        AgentRun(
            id="run_v1_deepsearch_artifact_route",
            thread_id=thread.id,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="route a DeepSearch report",
            client_turn_id="turn_v1_deepsearch_artifact_route",
            status=AgentRunStatus.PLANNING,
            planning_mode=AgentPlanningMode.DEEPSEARCH,
            requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
            orchestration_mode="execute",
            deadline_at=None,
            absolute_expires_at=created_at + timedelta(days=7),
            deepsearch_budget=DeepSearchBudgetV1(),
            created_at=created_at,
            updated_at=created_at,
        )
    )
    assert created
    report_payload = {
        "schema_version": "deepsearch-report-v1",
        "run_id": run.id,
        "requirement_version_id": "requirement_v1_deepsearch_artifact_route",
        "plan_id": "plan_v1_deepsearch_artifact_route",
        "plan_version": 1,
        "requirement_content_hash": "1" * 64,
        "problem_graph_hash": "2" * 64,
        "plan_content_hash": "3" * 64,
        "evidence_manifest_hash": "4" * 64,
        "synthesis_content_hash": "5" * 64,
        "review_outcome": "pass",
        "review_reason_code": None,
        "report_status": "complete",
        "title": "Verified report",
        "claims": [],
        "executive_summary_claim_ids": [],
        "sections": [],
        "sources": [],
        "limitations": [],
        "rendered_text": "Verified report",
    }
    content = canonical_json_bytes(report_payload).decode("utf-8")
    content_bytes = content.encode("utf-8")
    staging = Artifact(
        id="artifact_v1_deepsearch_route_sealed",
        run_id=run.id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        user_id=run.user_id,
        artifact_type="deepsearch_report",
        content_type="application/json",
        content="",
        verification_state=ArtifactVerificationState.STAGING,
        schema_version="deepsearch-report-v1",
        requirement_version_id=report_payload["requirement_version_id"],
        plan_version_id=f"{report_payload['plan_id']}:v1",
    )
    sealed = staging.model_copy(
        update={
            "content": content,
            "verification_state": ArtifactVerificationState.SEALED,
            "content_hash": hashlib.sha256(content_bytes).hexdigest(),
            "size_bytes": len(content_bytes),
        }
    )
    pending = staging.model_copy(update={"id": "artifact_v1_deepsearch_route_staging"})
    writer = V1VerifiedArtifactStore(store)
    writer.create_staging_report(staging)
    writer.seal_report(sealed)
    writer.create_staging_report(pending)

    client = TestClient(app)
    _login(client, USER.id, "designer123")

    sealed_response = client.get(f"/api/artifacts/{sealed.id}")
    pending_response = client.get(f"/api/artifacts/{pending.id}")

    assert sealed_response.status_code == 200
    assert sealed_response.json() == report_payload
    assert sealed_response.headers["X-AgentMesh-Artifact-Hash"] == sealed.content_hash
    assert pending_response.status_code == 409
    assert pending_response.json()["detail"] == "artifact_not_ready"
    assert "Verified report" not in pending_response.text
