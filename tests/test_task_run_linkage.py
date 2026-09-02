from __future__ import annotations

import hashlib
import sqlite3

import pytest
from agents.testing import ScriptedModel, assistant_message
from fastapi.testclient import TestClient

import agentmesh.routes.chat as chat_routes
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.app import app
from agentmesh.artifacts import UniversalSynthesisEnvelopeV1, V1VerifiedArtifactStore
from agentmesh.auth import SESSION_COOKIE_NAME, issue_session
from agentmesh.canonical_json import canonical_json_bytes
from agentmesh.models import (
    Agent,
    AgentPlanningContractVersion,
    AgentRun,
    AgentRunStatus,
    Artifact,
    ArtifactVerificationState,
    SkillOrchestrationRequestMode,
    SkillSynthesisResult,
    User,
)
from agentmesh.seed import TEAM_LEAD, USER
from agentmesh.store import ResearchStoreConflict, SQLiteStore, store
from tests.test_chat_flow import authenticated_client, clear_store


def _insert_artifact(artifact: Artifact) -> None:
    with store._connect() as connection:
        connection.execute(
            """
            INSERT INTO artifacts(
                id, run_id, payload, created_at, workspace_id, project_id, user_id,
                artifact_type, content_type, truncated, verification_state, schema_version,
                content_hash, size_bytes, requirement_version_id, plan_version_id,
                attempt_id, step_number, purged_at, purged_by, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
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


def _create_in_progress_task(client: TestClient, suffix: str) -> dict:
    item = client.post(
        "/api/tasks",
        json={"command_id": f"task-run-create-{suffix}", "title": f"Linked task {suffix}"},
    ).json()["item"]
    version = item["management"]["version"]
    for action in ("plan", "start"):
        response = client.post(
            f"/api/tasks/{item['task']['id']}/transitions",
            json={
                "command_id": f"task-run-{action}-{suffix}",
                "expected_version": version,
                "action": action,
            },
        )
        assert response.status_code == 200
        item = response.json()["item"]
        version = item["management"]["version"]
    assert "start_agent_run" in item["allowed_actions"]
    return item


def test_agent_run_task_projection_migrates_legacy_schema(tmp_path) -> None:
    database = tmp_path / "legacy-agent-run-task-id.sqlite3"
    taskless = AgentRun(
        id="run_legacy_taskless",
        thread_id="thread_legacy_taskless",
        user_id="user_legacy",
        workspace_id="workspace_legacy",
        project_id="project_legacy",
        input_text="Legacy taskless run",
        status=AgentRunStatus.FAILED,
    )
    linked = taskless.model_copy(
        update={
            "id": "run_legacy_linked",
            "thread_id": "thread_legacy_linked",
            "task_id": "task_legacy_linked",
            "input_text": "Legacy linked payload",
        }
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE agent_runs (
                id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                orchestration_version TEXT NOT NULL DEFAULT 'v1'
            )
            """
        )
        for run in (taskless, linked):
            connection.execute(
                "INSERT INTO agent_runs(id, payload, updated_at, orchestration_version) VALUES (?, ?, ?, ?)",
                (run.id, run.model_dump_json(), run.updated_at.isoformat(), "v1"),
            )

    repository = SQLiteStore(database)
    with repository._connect() as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(agent_runs)")}
        rows = {
            row["id"]: row["task_id"]
            for row in connection.execute("SELECT id, task_id FROM agent_runs")
        }
    assert "task_id" in columns
    assert rows == {taskless.id: None, linked.id: linked.task_id}
    assert repository.get_agent_run(taskless.id).task_id is None
    assert repository.get_agent_run(linked.id).task_id == linked.task_id
    repository.close()


def test_task_linked_run_requires_in_progress_delivery_stage(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "off")
    runtime = AgentRuntimeService(
        store,
        model=ScriptedModel([[assistant_message("must not run")]]),
        enabled=True,
    )
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)
    client = authenticated_client()
    task = client.post(
        "/api/tasks",
        json={"command_id": "task-run-backlog", "title": "Backlog task"},
    ).json()["item"]

    response = client.post(
        "/api/agent/runs",
        json={
            "content": "Start too early",
            "client_turn_id": "task-run-too-early",
            "task_id": task["task"]["id"],
            "orchestration_mode": "single",
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "task_agent_run_requires_in_progress"}}
    assert store.get_agent_run_by_client_turn(USER.id, "task-run-too-early") is None


def test_task_run_failure_does_not_leave_an_implicit_thread(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "off")
    client = authenticated_client()
    task = _create_in_progress_task(client, "implicit-cleanup")
    before = {thread.id for thread in store.chat_threads}

    class FailingRuntime:
        enabled = True

        @staticmethod
        def ready_for_user(_user) -> bool:  # noqa: ANN001
            return True

        @staticmethod
        async def start(**_kwargs):  # noqa: ANN003, ANN205
            raise RuntimeError("task_claim_failed")

    monkeypatch.setattr(chat_routes.agent, "agent_runtime", FailingRuntime())
    response = client.post(
        "/api/agent/runs",
        json={
            "content": "Fail after implicit thread creation",
            "client_turn_id": "task-implicit-cleanup",
            "task_id": task["task"]["id"],
            "orchestration_mode": "single",
        },
    )

    assert response.status_code == 409
    assert {thread.id for thread in store.chat_threads} == before
    assert store.get_agent_run_by_client_turn(USER.id, "task-implicit-cleanup") is None


def test_task_run_model_unavailable_creates_neither_run_nor_thread(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "off")
    runtime = AgentRuntimeService(store, model=None, enabled=True)
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)
    client = authenticated_client()
    task = _create_in_progress_task(client, "model-unavailable")
    before = {thread.id for thread in store.chat_threads}

    response = client.post(
        "/api/agent/runs",
        json={
            "content": "No configured model",
            "client_turn_id": "task-model-unavailable",
            "task_id": task["task"]["id"],
            "orchestration_mode": "single",
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Agent model is not configured"}
    assert {thread.id for thread in store.chat_threads} == before
    assert store.get_agent_run_by_client_turn(USER.id, "task-model-unavailable") is None


def test_task_linked_agent_run_is_idempotent_and_projects_safe_detail(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "off")
    runtime = AgentRuntimeService(
        store,
        model=ScriptedModel([[assistant_message("linked answer")]]),
        enabled=True,
    )
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)
    client = authenticated_client()
    assert client.get("/api/bootstrap").json()["agent_runtime_ready"] is True
    task = _create_in_progress_task(client, "primary")
    payload = {
        "content": "Complete the linked task",
        "client_turn_id": "task-linked-run-001",
        "thread_id": task["task"]["thread_id"],
        "task_id": task["task"]["id"],
        "orchestration_mode": "single",
        "planning_mode": "standard",
    }

    first = client.post("/api/agent/runs", json=payload)
    replay = client.post("/api/agent/runs", json=payload)

    assert first.status_code == 202
    assert replay.status_code == 202
    assert replay.json()["item"]["id"] == first.json()["item"]["id"]
    assert first.json()["item"]["task_id"] == task["task"]["id"]
    run_id = first.json()["item"]["id"]
    with store._connect() as connection:
        task_projection = connection.execute(
            "SELECT task_id FROM agent_runs WHERE id = ?",
            (run_id,),
        ).fetchone()["task_id"]
    assert task_projection == task["task"]["id"]
    persisted_run = store.get_agent_run(run_id)
    assert persisted_run is not None
    with pytest.raises(ResearchStoreConflict, match="creation identity is immutable"):
        store.save_agent_run(persisted_run.model_copy(update={"task_id": "task_other"}))
    detail = client.get(f"/api/tasks/{task['task']['id']}")

    assert detail.status_code == 200
    assert [run["id"] for run in detail.json()["runs"]] == [run_id]
    assert detail.json()["runs"][0]["artifact_count"] == 0
    assert detail.json()["runs"][0]["navigation_href"].endswith(f"?run={run_id}")
    assert detail.json()["artifacts"] == []


def test_task_detail_exposes_only_canonically_verified_sealed_artifacts(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    client = authenticated_client()
    task = _create_in_progress_task(client, "sealed-artifact")
    run, created = store.claim_new_agent_run(
        AgentRun(
            id="run_task_verified_artifact",
            thread_id=task["task"]["thread_id"],
            task_id=task["task"]["id"],
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="Verified task result",
            client_turn_id="task-verified-artifact",
            status=AgentRunStatus.COMPLETED,
            requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
            orchestration_mode="preview",
            planning_contract_version=AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1,
        )
    )
    assert created is True
    envelope = UniversalSynthesisEnvelopeV1(
        run_id=run.id,
        requirement_version_id="task-requirement-v1",
        plan_id="task-plan",
        plan_version=1,
        synthesis=SkillSynthesisResult(summary="Verified task result"),
    )
    content = canonical_json_bytes(envelope.model_dump(mode="json")).decode()
    sealed = Artifact(
        id="artifact_task_linked",
        run_id=run.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        user_id=USER.id,
        artifact_type="universal_synthesis",
        content_type="application/json",
        content=content,
        verification_state=ArtifactVerificationState.SEALED,
        schema_version="universal-synthesis-v1",
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        size_bytes=len(content.encode()),
        requirement_version_id="task-requirement-v1",
        plan_version_id="task-plan:v1",
    )
    V1VerifiedArtifactStore(store).insert_sealed(sealed)
    store.save_artifact(
        Artifact(
            id="artifact_task_legacy",
            run_id=run.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            artifact_type="task_output",
            content_type="text/markdown",
            content="# Legacy mutable result",
        )
    )
    corrupted = sealed.model_copy(update={"id": "artifact_task_corrupted", "content_hash": "0" * 64})
    _insert_artifact(corrupted)

    detail = client.get(f"/api/tasks/{task['task']['id']}")
    assert detail.status_code == 200
    verified_run = next(item for item in detail.json()["runs"] if item["id"] == run.id)
    assert verified_run["artifact_count"] == 1
    assert detail.json()["artifacts"] == [
        {
            "id": sealed.id,
            "run_id": run.id,
            "artifact_type": "universal_synthesis",
            "content_type": "application/json",
            "verification_state": "sealed",
            "content_hash": sealed.content_hash,
            "size_bytes": sealed.size_bytes,
            "created_at": detail.json()["artifacts"][0]["created_at"],
            "download_href": f"/api/artifacts/{sealed.id}",
        }
    ]
    project = store.get_project(USER.default_project_id)
    assert project is not None
    viewer = store.save_user(
        User(
            id="usr_task_artifact_viewer",
            workspace_id=USER.workspace_id,
            default_project_id=project.id,
            name="Artifact summary viewer",
            role="user",
            personal_agent_id="agent_task_artifact_viewer",
        )
    )
    project.member_ids.append(viewer.id)
    store.save_project(project)
    _, viewer_token = issue_session(store, viewer)
    viewer_client = TestClient(app)
    viewer_client.cookies.set(SESSION_COOKIE_NAME, viewer_token)
    viewer_detail = viewer_client.get(f"/api/tasks/{task['task']['id']}")
    assert viewer_detail.status_code == 200
    viewer_run = next(item for item in viewer_detail.json()["runs"] if item["id"] == run.id)
    assert viewer_run["navigation_href"] is None
    assert "input_text" not in viewer_run
    assert viewer_detail.json()["artifacts"][0]["download_href"] is None
    assert "content" not in viewer_detail.json()["artifacts"][0]


def test_task_detail_reports_exact_run_and_artifact_truncation(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    client = authenticated_client()
    task = _create_in_progress_task(client, "truncation")
    for index in range(50):
        store.claim_new_agent_run(
            AgentRun(
                id=f"run_task_history_{index:02d}",
                thread_id=task["task"]["thread_id"],
                task_id=task["task"]["id"],
                user_id=USER.id,
                workspace_id=USER.workspace_id,
                project_id=USER.default_project_id,
                input_text=f"Historical run {index}",
                status=AgentRunStatus.COMPLETED,
            )
        )
    artifact_run, created = store.claim_new_agent_run(
        AgentRun(
            id="run_task_artifact_history",
            thread_id=task["task"]["thread_id"],
            task_id=task["task"]["id"],
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="Artifact history",
            status=AgentRunStatus.COMPLETED,
            planning_contract_version=AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1,
            requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
            orchestration_mode="preview",
        )
    )
    assert created is True
    envelope = UniversalSynthesisEnvelopeV1(
        run_id=artifact_run.id,
        requirement_version_id="task-history-requirement",
        plan_id="task-history-plan",
        plan_version=1,
        synthesis=SkillSynthesisResult(summary="Historical synthesis"),
    )
    content = canonical_json_bytes(envelope.model_dump(mode="json")).decode()
    artifact_template = Artifact(
        id="artifact_task_history_000",
        run_id=artifact_run.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        user_id=USER.id,
        artifact_type="universal_synthesis",
        content_type="application/json",
        content=content,
        verification_state=ArtifactVerificationState.SEALED,
        schema_version="universal-synthesis-v1",
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        size_bytes=len(content.encode()),
        requirement_version_id="task-history-requirement",
        plan_version_id="task-history-plan:v1",
    )
    for index in range(201):
        _insert_artifact(artifact_template.model_copy(update={"id": f"artifact_task_history_{index:03d}"}))
    for index in range(5):
        invalid = artifact_template.model_copy(update={"id": f"zz_invalid_task_history_{index}"})
        _insert_artifact(invalid)
        with store._connect() as connection:
            connection.execute(
                "UPDATE artifacts SET content_hash = ? WHERE id = ?",
                ("0" * 64, invalid.id),
            )

    detail = client.get(f"/api/tasks/{task['task']['id']}")

    assert detail.status_code == 200
    payload = detail.json()
    assert len(payload["runs"]) == 50
    assert payload["runs_truncated"] is True
    assert len(payload["artifacts"]) == 200
    assert payload["artifacts_truncated"] is True
    assert not any(item["id"].startswith("zz_invalid") for item in payload["artifacts"])


def test_pre_slice_run_hash_replays_without_task_and_rejects_task_upgrade(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    task = _create_in_progress_task(authenticated_client(), "legacy-hash")
    prior, created = store.claim_new_agent_run(
        AgentRun(
            id="run_pre_slice_hash",
            thread_id=task["task"]["thread_id"],
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="Legacy hash request",
            client_turn_id="pre-slice-hash",
            status=AgentRunStatus.FAILED,
            requested_orchestration_mode=SkillOrchestrationRequestMode.SINGLE,
            orchestration_mode="off",
        )
    )
    assert created is True

    class ForbiddenRuntime:
        enabled = True

        def __getattribute__(self, name):  # noqa: ANN001, ANN204
            if name != "enabled":
                raise AssertionError("exact replay must not dispatch")
            return super().__getattribute__(name)

    monkeypatch.setattr(chat_routes.agent, "agent_runtime", ForbiddenRuntime())
    client = authenticated_client()
    base = {
        "content": prior.input_text,
        "client_turn_id": prior.client_turn_id,
        "thread_id": prior.thread_id,
        "orchestration_mode": "single",
    }
    replay = client.post("/api/agent/runs", json=base)
    upgrade = client.post(
        "/api/agent/runs",
        json={**base, "task_id": task["task"]["id"]},
    )

    assert replay.status_code == 202
    assert replay.json()["item"]["id"] == prior.id
    assert replay.json()["item"]["task_id"] is None
    assert upgrade.status_code == 409
    assert upgrade.json() == {"detail": {"code": "client_turn_id_conflict"}}


def test_task_link_is_part_of_run_idempotency_identity(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "off")
    runtime = AgentRuntimeService(
        store,
        model=ScriptedModel([[assistant_message("linked answer")]]),
        enabled=True,
    )
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)
    client = authenticated_client()
    first_task = _create_in_progress_task(client, "identity-a")
    second_task = _create_in_progress_task(client, "identity-b")
    base = {
        "content": "Same request",
        "client_turn_id": "task-linked-identity",
        "orchestration_mode": "single",
    }

    first = client.post(
        "/api/agent/runs",
        json={
            **base,
            "thread_id": first_task["task"]["thread_id"],
            "task_id": first_task["task"]["id"],
        },
    )
    conflict = client.post(
        "/api/agent/runs",
        json={
            **base,
            "thread_id": second_task["task"]["thread_id"],
            "task_id": second_task["task"]["id"],
        },
    )

    assert first.status_code == 202
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": {"code": "client_turn_id_conflict"}}


def test_assigned_project_member_can_start_linked_run_on_task_thread(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "off")
    runtime = AgentRuntimeService(
        store,
        model=ScriptedModel([[assistant_message("assigned member answer")]]),
        enabled=True,
    )
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)
    owner_client = authenticated_client()
    task = _create_in_progress_task(owner_client, "assigned-member")
    project = store.get_project(USER.default_project_id)
    assert project is not None
    member = store.save_user(
        User(
            id="usr_task_run_member",
            workspace_id=USER.workspace_id,
            default_project_id=project.id,
            name="Task run member",
            role="user",
            personal_agent_id="agent_task_run_member",
        )
    )
    store.save_agent(
        Agent(
            id=member.personal_agent_id,
            workspace_id=member.workspace_id,
            name="Task run member Agent",
            agent_type="personal",
            description="Linked task executor",
            owner_user_id=member.id,
        )
    )
    project.member_ids.append(member.id)
    store.save_project(project)
    lead_client = authenticated_client(TEAM_LEAD.id)
    assigned = lead_client.patch(
        f"/api/tasks/{task['task']['id']}",
        json={
            "command_id": "assign-task-run-member",
            "expected_version": task["management"]["version"],
            "assignee_kind": "user",
            "assignee_id": member.id,
        },
    )
    assert assigned.status_code == 200
    _, token = issue_session(store, member)
    member_client = TestClient(app)
    member_client.cookies.set(SESSION_COOKIE_NAME, token)

    response = member_client.post(
        "/api/agent/runs",
        json={
            "content": "Execute assigned project task",
            "client_turn_id": "assigned-task-run",
            "task_id": task["task"]["id"],
            "orchestration_mode": "single",
        },
    )

    assert response.status_code == 202
    assert response.json()["item"]["user_id"] == member.id
    assert response.json()["item"]["task_id"] == task["task"]["id"]
    assert response.json()["item"]["thread_id"] != task["task"]["thread_id"]
    run_thread = store.get_chat_thread(response.json()["item"]["thread_id"])
    assert run_thread is not None and run_thread.user_id == member.id
    assert run_thread.kind == "task"
    assert run_thread.id not in {
        thread["id"] for thread in member_client.get("/api/chat/threads").json()["items"]
    }
    assert member_client.get(f"/api/agent/runs/{response.json()['item']['id']}").status_code == 200


def test_retry_inherits_task_link(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "off")
    runtime = AgentRuntimeService(
        store,
        model=ScriptedModel([[assistant_message("retried linked answer")]]),
        enabled=True,
    )
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)
    client = authenticated_client()
    task = _create_in_progress_task(client, "retry")
    prior, created = store.claim_new_agent_run(
        AgentRun(
            id="run_task_retry_source",
            thread_id=task["task"]["thread_id"],
            task_id=task["task"]["id"],
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="Retry linked work",
            client_turn_id="task-retry-source",
            status=AgentRunStatus.FAILED,
            requested_orchestration_mode=SkillOrchestrationRequestMode.SINGLE,
            orchestration_mode="off",
        )
    )
    assert created is True

    response = client.post(
        f"/api/agent/runs/{prior.id}/retry",
        json={"client_turn_id": "task-retry-child"},
    )

    assert response.status_code == 202
    assert response.json()["item"]["retry_of_run_id"] == prior.id
    assert response.json()["item"]["task_id"] == task["task"]["id"]


def test_retry_claim_requires_matching_parent_task_identity(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    client = authenticated_client()
    first_task = _create_in_progress_task(client, "retry-parent-a")
    second_task = _create_in_progress_task(client, "retry-parent-b")
    parent, created = store.claim_new_agent_run(
        AgentRun(
            thread_id=first_task["task"]["thread_id"],
            task_id=first_task["task"]["id"],
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="Parent task run",
            client_turn_id="retry-parent-source",
            status=AgentRunStatus.FAILED,
            requested_orchestration_mode=SkillOrchestrationRequestMode.SINGLE,
            orchestration_mode="off",
        )
    )
    assert created is True

    with pytest.raises(ResearchStoreConflict, match="agent_run_retry_identity_invalid"):
        store.claim_new_agent_run(
            AgentRun(
                id="run_retry_parent_mismatch",
                thread_id=parent.thread_id,
                task_id=second_task["task"]["id"],
                user_id=USER.id,
                workspace_id=USER.workspace_id,
                project_id=USER.default_project_id,
                input_text=parent.input_text,
                retry_of_run_id=parent.id,
                status=AgentRunStatus.FAILED,
                requested_orchestration_mode=SkillOrchestrationRequestMode.SINGLE,
                orchestration_mode="off",
            )
        )
    with pytest.raises(ResearchStoreConflict, match="agent_run_retry_parent_not_found"):
        store.claim_new_agent_run(
            AgentRun(
                id="run_retry_parent_missing",
                thread_id=parent.thread_id,
                task_id=parent.task_id,
                user_id=USER.id,
                workspace_id=USER.workspace_id,
                project_id=USER.default_project_id,
                input_text=parent.input_text,
                retry_of_run_id="run_missing_parent",
                status=AgentRunStatus.FAILED,
                requested_orchestration_mode=SkillOrchestrationRequestMode.SINGLE,
                orchestration_mode="off",
            )
        )


def test_indexed_task_id_mismatch_fails_primary_run_reads(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    client = authenticated_client()
    task = _create_in_progress_task(client, "projection-integrity")
    run, created = store.claim_new_agent_run(
        AgentRun(
            thread_id=task["task"]["thread_id"],
            task_id=task["task"]["id"],
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="Projection integrity",
            client_turn_id="task-projection-integrity",
            status=AgentRunStatus.FAILED,
            requested_orchestration_mode=SkillOrchestrationRequestMode.SINGLE,
            orchestration_mode="off",
        )
    )
    assert created is True
    with store._connect() as connection:
        connection.execute("UPDATE agent_runs SET task_id = ? WHERE id = ?", ("task_corrupt", run.id))

    with pytest.raises(ResearchStoreConflict, match="task identity"):
        store.get_agent_run(run.id)
    with pytest.raises(ResearchStoreConflict, match="task identity"):
        store.get_agent_run_by_client_turn(USER.id, "task-projection-integrity")
    with pytest.raises(ResearchStoreConflict, match="task identity"):
        store.list_agent_runs_for_task("task_corrupt")
    with pytest.raises(ResearchStoreConflict, match="task identity"):
        store.list_agent_runs()


def test_task_allows_only_one_active_linked_run(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    client = authenticated_client()
    task = _create_in_progress_task(client, "single-active")
    base = {
        "thread_id": task["task"]["thread_id"],
        "task_id": task["task"]["id"],
        "user_id": USER.id,
        "workspace_id": USER.workspace_id,
        "project_id": USER.default_project_id,
        "input_text": "Linked active run",
        "status": AgentRunStatus.RUNNING,
        "requested_orchestration_mode": SkillOrchestrationRequestMode.SINGLE,
        "orchestration_mode": "off",
    }
    first, created = store.claim_new_agent_run(
        AgentRun(**base, id="run_task_active_one")
    )
    assert created is True
    active_detail = client.get(f"/api/tasks/{task['task']['id']}")
    assert active_detail.status_code == 200
    assert "start_agent_run" not in active_detail.json()["item"]["allowed_actions"]

    with pytest.raises(ResearchStoreConflict, match="task_agent_run_already_active"):
        store.claim_new_agent_run(
            AgentRun(**base, id="run_task_active_two")
        )
    assert store.get_agent_run(first.id) is not None


def test_linked_run_claim_rechecks_current_task_state(monkeypatch) -> None:
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    client = authenticated_client()
    task = _create_in_progress_task(client, "claim")
    task_id = task["task"]["id"]
    thread_id = task["task"]["thread_id"]
    blocked = client.post(
        f"/api/tasks/{task_id}/transitions",
        json={
            "command_id": "task-claim-block",
            "expected_version": task["management"]["version"],
            "action": "block",
            "reason": "Concurrent blocker",
        },
    )
    assert blocked.status_code == 200

    with pytest.raises(ResearchStoreConflict, match="task_blocked"):
        store.claim_new_agent_run(
            AgentRun(
                thread_id=thread_id,
                task_id=task_id,
                user_id=USER.id,
                workspace_id=USER.workspace_id,
                project_id=USER.default_project_id,
                input_text="Must not start",
                client_turn_id="task-claim-blocked",
                status=AgentRunStatus.RUNNING,
            )
        )
