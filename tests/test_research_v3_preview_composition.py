from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from agentmesh.agent_runtime.settings import SkillOrchestrationMode
from agentmesh.models import ChatThread, SkillOrchestrationRequestMode, User
from agentmesh.research_orchestration.current import ResearchWriterGeneration
from agentmesh.research_orchestration.v3.actor_adapters import (
    AgentSdkSkillAdapterV3,
    LlmSynthesisAdapterV3,
    ReviewerAdapterV3,
    TavilyToolGatewayAdapterV3,
)
from agentmesh.research_orchestration.v3.api import (
    ResearchV3AggregateReadRequest,
    ResearchV3CancelRequest,
    ResearchV3CandidateSelectRequest,
    ResearchV3ClarificationAnswer,
    ResearchV3ClarifyRequest,
    ResearchV3ConfirmRequest,
    ResearchV3ExecuteRequest,
    ResearchV3OwnerScope,
    ResearchV3ReviseRequest,
    create_research_v3_router,
    research_v3_request_hash,
)
from agentmesh.research_orchestration.v3.composition import ResearchV3PreviewComposition
from agentmesh.routes.deps import current_user
from agentmesh.store import SQLiteStore

NOW = datetime(2026, 8, 21, 10, 30, tzinfo=UTC)
OWNER = ResearchV3OwnerScope(
    user_id="user_gate2_preview_1",
    workspace_id="workspace_gate2",
    project_id="project_gate2",
)
USER = User(
    id=OWNER.user_id,
    workspace_id=OWNER.workspace_id,
    default_project_id=OWNER.project_id,
    name="Gate 2 Preview",
    role="user",
    personal_agent_id="agent_gate2_preview",
    created_at=NOW,
    updated_at=NOW,
)


def _activate_v3(store: SQLiteStore) -> None:
    store.compare_and_swap_research_writer_control(
        expected_generation=ResearchWriterGeneration.V2,
        expected_generation_epoch=1,
        target_generation=ResearchWriterGeneration.V3,
        decision_receipt_hash="e" * 64,
        changed_at=NOW,
    )


async def _start(
    composition: ResearchV3PreviewComposition,
    *,
    content: str,
    client_turn_id: str,
):
    return await composition.start_run(
        content=content,
        user=USER,
        thread_id=f"thread_{client_turn_id}",
        client_turn_id=client_turn_id,
        mode=SkillOrchestrationMode.PREVIEW,
        requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
    )


def _body(command_type: str, run_id: str, request):  # noqa: ANN001, ANN202
    return request.model_copy(
        update={"request_hash": research_v3_request_hash(command_type, run_id, request)}
    ).model_dump(mode="json")


def _client(composition: ResearchV3PreviewComposition) -> TestClient:
    async def owner_provider(_request: Request) -> ResearchV3OwnerScope:
        return OWNER

    app = FastAPI()
    app.include_router(
        create_research_v3_router(
            workflow=composition,
            projector=composition,
            owner_provider=owner_provider,
        )
    )
    return TestClient(app)


def test_preview_start_persists_candidates_without_calling_actor_adapters(
    tmp_path,
    monkeypatch,
) -> None:  # noqa: ANN001
    store = SQLiteStore(tmp_path / "preview-start.sqlite3")
    _activate_v3(store)
    composition = ResearchV3PreviewComposition(store)
    calls: list[str] = []

    async def forbidden_execute(self, request):  # noqa: ANN001, ANN202
        del self, request
        calls.append("actor")
        raise AssertionError("preview must not execute an Actor adapter")

    for adapter_type in (
        TavilyToolGatewayAdapterV3,
        AgentSdkSkillAdapterV3,
        LlmSynthesisAdapterV3,
        ReviewerAdapterV3,
    ):
        monkeypatch.setattr(adapter_type, "execute", forbidden_execute)

    run = asyncio.run(
        _start(
            composition,
            content="Compare Alpha and Beta.",
            client_turn_id="turn_preview_start",
        )
    )
    aggregate = composition.project_authoritative(
        ResearchV3AggregateReadRequest(run_id=run.id, owner=OWNER)
    )

    assert run.orchestration_version == "research-v3"
    assert run.orchestration_mode == "preview"
    assert run.writer_generation_epoch == 2
    assert aggregate.workflow.state == "candidates"
    assert aggregate.workflow.state_version == 1
    assert aggregate.candidates is not None
    assert tuple(item.candidate_id for item in aggregate.candidates.candidates) == ("depth", "speed")
    assert calls == []


def test_preview_clarification_select_confirm_and_execute_denial(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "preview-commands.sqlite3")
    _activate_v3(store)
    composition = ResearchV3PreviewComposition(store)
    run = asyncio.run(
        _start(
            composition,
            content="帮我做竞品分析",
            client_turn_id="turn_preview_commands",
        )
    )
    client = _client(composition)

    blocked = client.get(f"/api/agent/runs/{run.id}/research")
    assert blocked.status_code == 200
    assert blocked.json()["workflow"]["state"] == "clarify"
    assert blocked.json()["workflow"]["state_version"] == 1

    clarify = ResearchV3ClarifyRequest(
        expected_state_version=1,
        request_hash="0" * 64,
        answers=(
            ResearchV3ClarificationAnswer(
                question_key="competitors",
                answer="Alpha, Beta",
            ),
        ),
    )
    clarified = client.post(
        f"/api/agent/runs/{run.id}/research/clarify",
        headers={"Idempotency-Key": "clarify.preview.1"},
        json=_body("clarify", run.id, clarify),
    )
    assert clarified.status_code == 202
    assert clarified.json()["state_version"] == 2

    select = ResearchV3CandidateSelectRequest(
        expected_state_version=2,
        request_hash="0" * 64,
        candidate_id="speed",
    )
    selected = client.post(
        f"/api/agent/runs/{run.id}/research/candidates/select",
        headers={"Idempotency-Key": "select.preview.1"},
        json=_body("select_candidate", run.id, select),
    )
    assert selected.status_code == 202
    assert selected.json()["state_version"] == 3

    projection = client.get(f"/api/agent/runs/{run.id}/research").json()
    assert projection["workflow"]["state"] == "plan"
    plan_id = projection["selected_plan"]["id"]

    confirm = ResearchV3ConfirmRequest(
        expected_state_version=3,
        request_hash="0" * 64,
        plan_version_id=plan_id,
    )
    confirmed = client.post(
        f"/api/agent/runs/{run.id}/research/plans/confirm",
        headers={"Idempotency-Key": "confirm.preview.1"},
        json=_body("confirm_plan", run.id, confirm),
    )
    assert confirmed.status_code == 202
    assert confirmed.json()["state_version"] == 4
    confirmed_projection = client.get(f"/api/agent/runs/{run.id}/research").json()
    assert confirmed_projection["workflow"]["gate"]["status"] == "satisfied"
    assert store.get_agent_run(run.id).status == "completed"

    repeated_confirm = ResearchV3ConfirmRequest(
        expected_state_version=4,
        request_hash="0" * 64,
        plan_version_id=plan_id,
    )
    repeated = client.post(
        f"/api/agent/runs/{run.id}/research/plans/confirm",
        headers={"Idempotency-Key": "confirm.preview.second-key"},
        json=_body("confirm_plan", run.id, repeated_confirm),
    )
    assert repeated.status_code == 409
    assert "already confirmed" in repeated.json()["detail"]

    restarted = ResearchV3PreviewComposition(
        SQLiteStore(tmp_path / "preview-commands.sqlite3")
    ).project_authoritative(ResearchV3AggregateReadRequest(run_id=run.id, owner=OWNER))
    assert restarted.workflow.gate.status == "satisfied"

    execute = ResearchV3ExecuteRequest(
        expected_state_version=4,
        request_hash="0" * 64,
        plan_version_id=plan_id,
    )
    denied = client.post(
        f"/api/agent/runs/{run.id}/research/execute",
        headers={"Idempotency-Key": "execute.preview.denied"},
        json=_body("execute", run.id, execute),
    )
    assert denied.status_code == 409
    assert "cannot execute Provider-backed Actors" in denied.json()["detail"]
    assert client.get(f"/api/agent/runs/{run.id}/research").json()["workflow"]["state_version"] == 4


def test_preview_candidate_replay_and_declarative_revision_are_idempotent(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "preview-revision.sqlite3")
    _activate_v3(store)
    composition = ResearchV3PreviewComposition(store)
    run = asyncio.run(
        _start(
            composition,
            content="Compare Alpha and Beta.",
            client_turn_id="turn_preview_revision",
        )
    )
    client = _client(composition)
    select = ResearchV3CandidateSelectRequest(
        expected_state_version=1,
        request_hash="0" * 64,
        candidate_id="depth",
    )
    select_body = _body("select_candidate", run.id, select)
    first = client.post(
        f"/api/agent/runs/{run.id}/research/candidates/select",
        headers={"Idempotency-Key": "select.preview.replay"},
        json=select_body,
    )
    replay = client.post(
        f"/api/agent/runs/{run.id}/research/candidates/select",
        headers={"Idempotency-Key": "select.preview.replay"},
        json=select_body,
    )
    assert first.status_code == replay.status_code == 202
    assert replay.json() == {**first.json(), "replayed": True}

    plan_id = client.get(f"/api/agent/runs/{run.id}/research").json()["selected_plan"]["id"]
    revision = ResearchV3ReviseRequest(
        expected_state_version=2,
        request_hash="0" * 64,
        plan_version_id=plan_id,
        candidate_id="speed",
        revision_note="Prefer the shorter preview plan.",
    )
    revised = client.post(
        f"/api/agent/runs/{run.id}/research/plans/revise",
        headers={"Idempotency-Key": "revise.preview.1"},
        json=_body("revise_plan", run.id, revision),
    )
    assert revised.status_code == 202
    aggregate = client.get(f"/api/agent/runs/{run.id}/research").json()
    assert aggregate["workflow"]["state_version"] == 3
    assert aggregate["selected_plan"]["payload"]["candidate_id"] == "speed"
    assert {item["key"] for item in aggregate["requirement"]["payload"]["assumptions"]} >= {
        "preview_only",
        "revision_note",
    }


def test_preview_cancel_records_command_and_closes_the_agent_run(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "preview-cancel.sqlite3")
    _activate_v3(store)
    composition = ResearchV3PreviewComposition(store)
    run = asyncio.run(
        _start(
            composition,
            content="Compare Alpha and Beta.",
            client_turn_id="turn_preview_cancel",
        )
    )
    client = _client(composition)
    cancel = ResearchV3CancelRequest(
        expected_state_version=1,
        request_hash="0" * 64,
        reason="User stopped the preview.",
    )

    response = client.post(
        f"/api/agent/runs/{run.id}/research/cancel",
        headers={"Idempotency-Key": "cancel.preview.1"},
        json=_body("cancel", run.id, cancel),
    )

    assert response.status_code == 202
    assert store.get_agent_run(run.id).status == "cancelled"
    cancelled_projection = client.get(f"/api/agent/runs/{run.id}/research").json()
    assert cancelled_projection["workflow"]["gate"]["status"] == "blocked"

    select = ResearchV3CandidateSelectRequest(
        expected_state_version=2,
        request_hash="0" * 64,
        candidate_id="speed",
    )
    denied = client.post(
        f"/api/agent/runs/{run.id}/research/candidates/select",
        headers={"Idempotency-Key": "select.after.cancel"},
        json=_body("select_candidate", run.id, select),
    )
    assert denied.status_code == 409
    assert "already cancelled" in denied.json()["detail"]


def test_main_agent_run_route_selects_v3_preview_and_stored_version_reader(
    tmp_path,
    monkeypatch,
) -> None:  # noqa: ANN001
    import agentmesh.routes.agent_runs as agent_run_routes
    import agentmesh.routes.research as research_routes

    store = SQLiteStore(tmp_path / "preview-main-route.sqlite3")
    _activate_v3(store)
    composition = ResearchV3PreviewComposition(store)
    isolated = FastAPI()
    isolated.state.research_runtime = SimpleNamespace(workflow_service=object())
    isolated.state.research_v3_preview = composition
    isolated.include_router(agent_run_routes.router)
    isolated.include_router(research_routes.router)
    isolated.dependency_overrides[current_user] = lambda: USER
    monkeypatch.setattr(agent_run_routes, "store", store)
    monkeypatch.setattr(research_routes, "store", store)
    monkeypatch.setattr(
        agent_run_routes,
        "_visible_run",
        lambda run_id, _user: store.get_agent_run(run_id),
    )
    monkeypatch.setattr(
        agent_run_routes,
        "_thread",
        lambda _request, _user: ChatThread(
            id="thread_preview_main_route",
            workspace_id=OWNER.workspace_id,
            project_id=OWNER.project_id,
            user_id=OWNER.user_id,
            title="Gate 2 preview",
        ),
    )
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "preview")
    monkeypatch.setenv("AGENTMESH_RESEARCH_PREVIEW_ALLOWLIST", OWNER.user_id)
    client = TestClient(isolated)
    payload = {
        "content": "对比 Alpha 与 Beta，分析能力差异。",
        "client_turn_id": "turn_preview_main_route",
    }

    created = client.post("/api/agent/runs", json=payload)
    replayed = client.post("/api/agent/runs", json=payload)

    assert created.status_code == replayed.status_code == 202
    run = created.json()["item"]
    assert replayed.json()["item"]["id"] == run["id"]
    assert run["orchestration_version"] == "research-v3"
    assert run["orchestration_mode"] == "preview"
    projection = client.get(f"/api/agent/runs/{run['id']}/research")
    assert projection.status_code == 200
    assert projection.json()["orchestration_version"] == "research-v3"
    assert projection.json()["workflow"]["state"] == "candidates"
    assert store.get_latest_research_run_for_thread(run["thread_id"], USER.id).id == run["id"]

    generic_retry = client.post(
        f"/api/agent/runs/{run['id']}/retry",
        json={"client_turn_id": "turn_preview_generic_retry"},
    )
    generic_cancel = client.post(f"/api/agent/runs/{run['id']}/cancel")
    assert generic_retry.status_code == 409
    assert "stored-version research API" in generic_retry.json()["detail"]
    assert generic_cancel.status_code == 409
    assert "stored-version research cancel API" in generic_cancel.json()["detail"]


def test_concurrent_identical_client_turn_replays_one_generated_thread(
    tmp_path,
    monkeypatch,
) -> None:  # noqa: ANN001
    import agentmesh.routes.agent_runs as agent_run_routes
    import agentmesh.routes.research as research_routes

    store = SQLiteStore(tmp_path / "preview-concurrent-replay.sqlite3")
    _activate_v3(store)
    composition = ResearchV3PreviewComposition(store)
    isolated = FastAPI()
    isolated.state.research_runtime = SimpleNamespace(workflow_service=object())
    isolated.state.research_v3_preview = composition
    isolated.include_router(agent_run_routes.router)
    isolated.include_router(research_routes.router)
    isolated.dependency_overrides[current_user] = lambda: USER
    monkeypatch.setattr(agent_run_routes, "store", store)
    monkeypatch.setattr(research_routes, "store", store)
    monkeypatch.setattr(
        agent_run_routes,
        "_visible_run",
        lambda run_id, _user: store.get_agent_run(run_id),
    )
    monkeypatch.setattr(agent_run_routes, "require_default_project", lambda _user, _store: None)
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "preview")
    monkeypatch.setenv("AGENTMESH_RESEARCH_PREVIEW_ALLOWLIST", OWNER.user_id)
    payload = {
        "content": "对比 Alpha 与 Beta，分析能力差异。",
        "client_turn_id": "turn_preview_concurrent",
    }
    barrier = Barrier(2)

    def post_once() -> tuple[int, dict[str, object]]:
        with TestClient(isolated) as client:
            barrier.wait()
            response = client.post("/api/agent/runs", json=payload)
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _index: post_once(), range(2)))

    assert [status for status, _body_value in responses] == [202, 202]
    runs = [body["item"] for _status, body in responses]
    assert runs[0]["id"] == runs[1]["id"]
    assert runs[0]["thread_id"] == runs[1]["thread_id"]
    assert len([thread for thread in store.chat_threads if thread.id == runs[0]["thread_id"]]) == 1
    assert len(store.list_agent_runs(USER.id)) == 1


def test_preview_owner_scope_is_hidden(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "preview-owner.sqlite3")
    _activate_v3(store)
    composition = ResearchV3PreviewComposition(store)
    run = asyncio.run(
        _start(
            composition,
            content="Compare Alpha and Beta.",
            client_turn_id="turn_preview_owner",
        )
    )

    foreign = ResearchV3OwnerScope(
        user_id="user_foreign",
        workspace_id=OWNER.workspace_id,
        project_id=OWNER.project_id,
    )
    from agentmesh.research_orchestration.v3.api import ResearchV3NotFoundError

    with pytest.raises(ResearchV3NotFoundError):
        composition.project_authoritative(
            ResearchV3AggregateReadRequest(run_id=run.id, owner=foreign)
        )
