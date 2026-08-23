from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import agentmesh.routes.chat as chat_routes
from agentmesh.agent_runtime.settings import SkillOrchestrationMode
from agentmesh.app import app
from agentmesh.models import (
    AgentRun,
    AgentRunStatus,
    ChatThread,
    SkillDefinition,
    SkillOrchestrationRequestMode,
    SkillSourceScope,
)
from agentmesh.research_orchestration.api import ResearchOwnerScope
from agentmesh.research_orchestration.artifacts import ArtifactStore
from agentmesh.research_orchestration.compiler import CompetitivePlanCompiler, validate_execution_plan_version
from agentmesh.research_orchestration.planning import (
    CompetitiveRequirementPlanner,
    requirement_version_from_result,
)
from agentmesh.research_orchestration.runtime import CompetitiveResearchPlanning, ResearchRuntime
from agentmesh.research_orchestration.workflow import ResearchWorkflowService
from agentmesh.seed import PROJECT, TEAM_LEAD, USER, WORKSPACE, ensure_seed_data
from agentmesh.skill_runtime.service import SkillCatalogService, catalog_service
from agentmesh.store import SQLiteStore, store
from agentmesh.tool_runtime.gateway import ToolGateway, ToolRuntimeDescriptor
from tests.research_orchestration_testkit import competitive_snapshot


def _login(client: TestClient, user_id: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"user_id": user_id, "password": password})
    assert response.status_code == 200


def _research_state_counts() -> dict[str, int]:
    tables = (
        "agent_runs",
        "agent_run_events",
        "artifacts",
        "research_workflows",
        "research_requirement_versions",
        "research_plan_versions",
        "research_attempts",
        "research_tool_invocations",
    )
    with sqlite3.connect(store.db_path) as connection:
        counts = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608
            for table in tables
        }
        counts["chat_records"] = int(
            connection.execute(
                "SELECT COUNT(*) FROM records WHERE collection IN ('chat_threads', 'chat_messages')"
            ).fetchone()[0]
        )
        return counts


class DeterministicPlanning:
    def __init__(self) -> None:
        self.prepare_calls = 0
        self.compile_calls = 0

    async def prepare_requirement(
        self,
        run: AgentRun,
        *,
        version: int,
        clarification_answers: dict[str, str] | None = None,
        revision=None,  # noqa: ANN001
    ):
        self.prepare_calls += 1
        raw_input = revision.research_goal if revision is not None and revision.research_goal else run.input_text
        answers = dict(clarification_answers or {})
        if revision is not None and revision.competitor_scope:
            answers["clarify_competitor_scope"] = revision.competitor_scope
        result = await CompetitiveRequirementPlanner().plan(
            raw_input,
            explicit_skill_name="competitive-analysis",
            clarification_answers=answers,
            model=None,
        )
        return requirement_version_from_result(run.id, version, result)

    def compile_plan(self, run: AgentRun, requirement, *, version: int):  # noqa: ANN001, ANN201
        self.compile_calls += 1
        now = competitive_snapshot().resolved_at
        return CompetitivePlanCompiler().compile(
            requirement,
            competitive_snapshot(now),
            plan_version=version,
            now=now,
        )


class CountingExecution:
    def __init__(self) -> None:
        self.calls = 0

    async def claim_and_run(self, attempt_id: str, *, token: str | None = None) -> None:
        del attempt_id, token
        self.calls += 1


class SynchronousPreviewRuntime(ResearchRuntime):
    """Keep TestClient's request-local event loop alive until planning is durable."""

    async def start_run(self, **kwargs):  # noqa: ANN003, ANN201
        run = await super().start_run(**kwargs)
        await self.workflow_service.wait_for_idle()
        return self.repository.get_agent_run(run.id)


class MutableReadinessGateway:
    def __init__(self) -> None:
        self.descriptor: ToolRuntimeDescriptor | None = ToolRuntimeDescriptor(
            implementation_id="agentmesh.tool_runtime.gateway.ToolGateway.web_research",
            implementation_version="1",
            execution_mode="real",
            health_state="healthy",
            health_checked_at=datetime(2026, 8, 22, tzinfo=UTC),
        )

    def describe(self, tool_name: str) -> ToolRuntimeDescriptor | None:
        assert tool_name == "web_research"
        return self.descriptor


@dataclass
class PreviewHarness:
    runtime: ResearchRuntime
    planning: DeterministicPlanning
    execution: CountingExecution
    readiness: MutableReadinessGateway


@pytest.fixture
def preview_harness(monkeypatch: pytest.MonkeyPatch) -> PreviewHarness:
    planning = DeterministicPlanning()
    execution = CountingExecution()
    readiness = MutableReadinessGateway()
    service = ResearchWorkflowService(store, planning, execution, ArtifactStore(store))
    runtime = SynchronousPreviewRuntime(store, service, tool_gateway=readiness)
    asyncio.run(runtime.start())
    monkeypatch.setattr(app.state, "research_runtime", runtime, raising=False)
    yield PreviewHarness(runtime=runtime, planning=planning, execution=execution, readiness=readiness)
    asyncio.run(runtime.shutdown())


class ForbiddenV1Runtime:
    enabled = True

    async def start(self, **_kwargs):  # noqa: ANN003, ANN201
        raise AssertionError("eligible research-v2 request reached the v1 runtime")

    async def start_orchestrated(self, **_kwargs):  # noqa: ANN003, ANN201
        raise AssertionError("eligible research-v2 request reached the v1 runtime")


class RecordingV1Runtime:
    enabled = True

    def __init__(self) -> None:
        self.start_calls = 0

    async def start(
        self,
        *,
        content,
        user,
        thread_id,
        skill=None,
        client_turn_id=None,
        requested_orchestration_mode=None,
        **_kwargs,
    ):  # noqa: ANN001, ANN003, ANN201
        self.start_calls += 1
        run = AgentRun(
            thread_id=thread_id,
            user_id=user.id,
            workspace_id=user.workspace_id,
            project_id=user.default_project_id,
            input_text=content,
            client_turn_id=client_turn_id,
            status=AgentRunStatus.COMPLETED,
            skill_id=skill.id if skill is not None else None,
            skill_name=skill.name if skill is not None else None,
            requested_orchestration_mode=requested_orchestration_mode,
            output_text="v1 fallback",
        )
        return store.claim_new_agent_run(run)[0]


def test_web_preview_routes_natural_request_once_and_reads_never_execute(
    monkeypatch: pytest.MonkeyPatch,
    preview_harness: PreviewHarness,
) -> None:
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "preview")
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", ForbiddenV1Runtime())
    client = TestClient(app)
    _login(client, USER.id, "designer123")
    payload = {
        "content": "对比 Figma 和 Miro 的协作、任务恢复与适用场景",
        "client_turn_id": "research-preview-natural-v1",
    }

    created = client.post("/api/agent/runs", json=payload)
    replayed = client.post("/api/agent/runs", json=payload)

    assert created.status_code == replayed.status_code == 202
    run = created.json()["item"]
    assert replayed.json()["item"]["id"] == run["id"]
    assert run["orchestration_version"] == "research-v2"
    assert run["orchestration_mode"] == "preview"
    assert run["status"] == "waiting_plan_approval"

    first = client.get(f"/api/agent/runs/{run['id']}/research")
    refreshed = client.get(f"/api/agent/runs/{run['id']}/research")
    events = client.get(f"/api/agent/runs/{run['id']}/events")

    assert first.status_code == refreshed.status_code == events.status_code == 200
    assert first.json() == refreshed.json()
    assert first.json()["workflow"]["active_gate"] == "plan_confirmation"
    assert first.json()["requirement"]["competitor_scope"] == "Figma 和 Miro"
    assert [step["actor_type"] for step in first.json()["plans"][0]["steps"]] == ["tool", "skill"]
    assert preview_harness.planning.prepare_calls == 1
    assert preview_harness.planning.compile_calls == 1
    assert preview_harness.execution.calls == 0
    matching_messages = [
        message
        for message in store.list_thread_messages(run["thread_id"])
        if message.content == payload["content"]
    ]
    assert len(matching_messages) == 1

    _login(client, TEAM_LEAD.id, "lead123")
    assert client.get(f"/api/agent/runs/{run['id']}/research").status_code == 404

    _login(client, USER.id, "designer123")
    assert client.post(f"/api/agent/runs/{run['id']}/cancel").status_code == 200
    stream = client.get(f"/api/agent/runs/{run['id']}/events/stream")
    assert stream.status_code == 200
    assert "event: run_started" in stream.text
    assert preview_harness.execution.calls == 0


def test_explicit_dollar_competitive_skill_uses_the_same_research_route(
    monkeypatch: pytest.MonkeyPatch,
    preview_harness: PreviewHarness,
) -> None:
    skill = SkillDefinition(
        id="skill_http_competitive_preview",
        name="competitive-analysis",
        title="Competitive analysis",
        description="Test competitive research routing",
        instructions="Use verified evidence.",
        source_path="builtin://competitive-analysis",
        source_scope=SkillSourceScope.BUILTIN,
        content_hash="a" * 64,
    )
    monkeypatch.setattr(
        catalog_service(),
        "get_by_name",
        lambda name, _agent_id=None: skill if name.removeprefix("$") == skill.name else None,
    )
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "preview")
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", ForbiddenV1Runtime())
    client = TestClient(app)
    _login(client, USER.id, "designer123")
    payload = {
        "content": "$competitive-analysis 对比淘宝和拼多多的履约体验",
        "client_turn_id": "research-preview-explicit-v1",
        "explicit_skill_name": "$competitive-analysis",
        "orchestration_mode": "single",
    }

    response = client.post("/api/agent/runs", json=payload)
    replayed = client.post("/api/agent/runs", json=payload)

    assert response.status_code == replayed.status_code == 202
    assert response.json()["item"]["orchestration_version"] == "research-v2"
    assert response.json()["item"]["skill_name"] == "competitive-analysis"
    assert replayed.json()["item"]["id"] == response.json()["item"]["id"]
    assert preview_harness.execution.calls == 0


def test_off_mode_and_non_competitive_requests_stay_on_v1(
    monkeypatch: pytest.MonkeyPatch,
    preview_harness: PreviewHarness,
) -> None:
    v1 = RecordingV1Runtime()
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", v1)
    client = TestClient(app)
    _login(client, USER.id, "designer123")

    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "off")
    off_response = client.post(
        "/api/agent/runs",
        json={
            "content": "对比 Figma 和 Miro 的协作能力",
            "client_turn_id": "research-preview-off-fallback-v1",
        },
    )
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "preview")
    ordinary_response = client.post(
        "/api/agent/runs",
        json={
            "content": "帮我写一段欢迎语",
            "client_turn_id": "research-preview-ordinary-v1",
            "orchestration_mode": "single",
        },
    )

    assert off_response.status_code == ordinary_response.status_code == 202
    assert off_response.json()["item"]["orchestration_version"] == "v1"
    assert ordinary_response.json()["item"]["orchestration_version"] == "v1"
    assert v1.start_calls == 2
    assert preview_harness.planning.prepare_calls == 0
    assert preview_harness.execution.calls == 0


def test_eligible_request_fails_closed_when_runtime_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "preview")
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", ForbiddenV1Runtime())
    monkeypatch.delattr(app.state, "research_runtime", raising=False)
    thread_ids_before = {thread.id for thread in store.chat_threads}
    client = TestClient(app)
    _login(client, USER.id, "designer123")

    response = client.post(
        "/api/agent/runs",
        json={
            "content": "对比 Figma 和 Miro 的协作能力",
            "client_turn_id": "research-preview-runtime-missing-v1",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Research Runtime is unavailable"
    assert {thread.id for thread in store.chat_threads} == thread_ids_before


@pytest.mark.parametrize(
    ("descriptor", "expected_code"),
    [
        (None, "tool_runtime_unregistered"),
        (
            ToolRuntimeDescriptor(
                implementation_id="test.fake-web",
                implementation_version="1",
                execution_mode="fake",
                health_state="healthy",
                health_checked_at=datetime(2026, 8, 22, tzinfo=UTC),
            ),
            "tool_runtime_not_real",
        ),
        (
            ToolRuntimeDescriptor(
                implementation_id="test.real-web",
                implementation_version="1",
                execution_mode="real",
                health_state="unavailable",
                health_checked_at=datetime(2026, 8, 22, tzinfo=UTC),
            ),
            "tool_runtime_unhealthy",
        ),
    ],
)
def test_research_v2_rejects_unready_provider_before_creating_durable_state(
    monkeypatch: pytest.MonkeyPatch,
    preview_harness: PreviewHarness,
    descriptor: ToolRuntimeDescriptor | None,
    expected_code: str,
) -> None:
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "execute")
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", ForbiddenV1Runtime())
    preview_harness.readiness.descriptor = descriptor
    client = TestClient(app)
    _login(client, USER.id, "designer123")
    counts_before = _research_state_counts()

    response = client.post(
        "/api/agent/runs",
        json={
            "content": "对比 Figma 和 Miro 的协作能力",
            "client_turn_id": f"research-provider-{expected_code}",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == expected_code
    assert isinstance(response.json()["detail"]["message"], str)
    assert _research_state_counts() == counts_before
    assert preview_harness.planning.prepare_calls == 0
    assert preview_harness.runtime.workflow_service.background_task_count == 0


def test_existing_client_turn_replays_before_live_provider_readiness(
    monkeypatch: pytest.MonkeyPatch,
    preview_harness: PreviewHarness,
) -> None:
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "preview")
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", ForbiddenV1Runtime())
    client = TestClient(app)
    _login(client, USER.id, "designer123")
    payload = {
        "content": "对比 Figma 和 Miro 的协作能力",
        "client_turn_id": "research-provider-replay-before-readiness",
    }

    created = client.post("/api/agent/runs", json=payload)
    preview_harness.readiness.descriptor = None
    replayed = client.post("/api/agent/runs", json=payload)

    assert created.status_code == replayed.status_code == 202
    assert replayed.json()["item"]["id"] == created.json()["item"]["id"]
    assert preview_harness.planning.prepare_calls == 1


class NoModelFactory:
    def for_user(self, _user):  # noqa: ANN001, ANN201
        return None


class SnapshotCapabilityResolver:
    def __init__(self) -> None:
        self.resource_snapshot = None

    def resolve(self, *, run_id: str, user_id: str, resource_snapshot):  # noqa: ANN001, ANN201
        del run_id, user_id
        self.resource_snapshot = resource_snapshot
        return competitive_snapshot().model_copy(update={"resource_snapshot": resource_snapshot})


def test_competitive_planning_facade_seals_resource_and_compiles_one_plan(
    tmp_path: Path,
    configure_pilot_wiki,
) -> None:
    wiki_root = configure_pilot_wiki(tmp_path / "wiki")
    method = (
        wiki_root
        / "jd-design-system-md-v16"
        / "horizontal"
        / "user-research"
        / "methods"
        / "toolbox"
        / "analysis"
        / "competitive-analysis.md"
    )
    method.parent.mkdir(parents=True, exist_ok=True)
    method.write_text("# Canonical competitive analysis method\n", encoding="utf-8")
    repository = SQLiteStore(tmp_path / "preview-runtime.sqlite3")
    ensure_seed_data(repository)
    catalog = SkillCatalogService(repository)
    catalog.reload()
    artifacts = ArtifactStore(repository)
    planning = CompetitiveResearchPlanning(
        repository,
        catalog,
        artifacts,
        ToolGateway(repository),
        model_factory=NoModelFactory(),
    )
    capabilities = SnapshotCapabilityResolver()
    planning.capabilities = capabilities
    execution = CountingExecution()
    service = ResearchWorkflowService(repository, planning, execution, artifacts)
    runtime = ResearchRuntime(repository, service)
    thread = repository.add_chat_thread(
        ChatThread(
            id="thread_preview_facade",
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
            user_id=USER.id,
            title="Preview facade",
        )
    )

    async def scenario() -> tuple[AgentRun, object]:
        await runtime.start()
        run = await runtime.start_run(
            content="对比 Figma 和 Miro 的协作、恢复与局限",
            user=repository.get_user(USER.id),
            thread_id=thread.id,
            client_turn_id="preview-facade-v1",
            mode=SkillOrchestrationMode.PREVIEW,
            requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
        )
        await service.wait_for_idle()
        projection = service.get_projection(
            run.id,
            owner=ResearchOwnerScope(
                user_id=USER.id,
                workspace_id=WORKSPACE.id,
                project_id=PROJECT.id,
            ),
        )
        await runtime.shutdown()
        return repository.get_agent_run(run.id), projection

    run, projection = asyncio.run(scenario())

    assert run.status == AgentRunStatus.WAITING_PLAN_APPROVAL
    assert projection.workflow.active_gate == "plan_confirmation"
    assert len(projection.plans) == 1
    persisted_plan = repository.get_research_plan_version(projection.plans[0].plan_version_id)
    body = validate_execution_plan_version(persisted_plan)
    snapshot_artifact = repository.get_artifact(body.control_snapshot.resource_snapshot.artifact_id)
    assert snapshot_artifact is not None
    assert snapshot_artifact.content_hash == body.control_snapshot.resource_snapshot.content_hash
    assert capabilities.resource_snapshot == body.control_snapshot.resource_snapshot
    assert execution.calls == 0
