"""Tests for provider health check endpoint."""

import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agentmesh.app import app
from agentmesh.models import (
    AgentPlanningMode,
    AgentRunStatus,
    SkillCapabilityProfile,
    SkillCapabilityType,
    SkillDefinition,
    SkillLifecycleStage,
    SkillSourceScope,
)
from agentmesh.provider_status import ProviderTelemetry
from agentmesh.routes import health as health_routes
from agentmesh.seed import ADMIN
from agentmesh.store import SQLiteStore


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def auth_client(client: TestClient):
    """返回已登录的 TestClient。"""
    response = client.post("/api/auth/login", json={"user_id": ADMIN.id, "password": "admin123"})
    assert response.status_code == 200
    return client


class TestProviderHealthCheck:
    """测试 /api/health/providers 端点。"""

    def test_requires_auth(self, client: TestClient):
        response = client.get("/api/health/providers")
        assert response.status_code == 401

    def test_returns_all_providers(self, auth_client: TestClient):
        response = auth_client.get("/api/health/providers")
        assert response.status_code == 200
        data = response.json()
        assert "overall" in data
        assert "providers" in data
        provider_names = [p["name"] for p in data["providers"]]
        assert "llm" in provider_names
        assert "web_research" in provider_names
        assert "o2" in provider_names
        assert "data_connectors" in provider_names
        assert "document_parser" in provider_names
        canonical_fields = {"name", "configured", "ready", "mode", "last_error", "latency_ms"}
        assert all(canonical_fields <= set(item) for item in data["providers"])
        assert all("provider" not in item for item in data["providers"])
        runtime = next(item for item in data["providers"] if item["name"] == "openai_agents_sdk")
        assert runtime["profile_health"] in {"ready", "degraded"}
        assert runtime["skill_profile_trust"] == "unavailable"
        assert runtime["skill_profile_trust_error"] == "skill_profile_trust_unavailable"
        assert runtime["index_health"] in {"ready", "degraded"}
        assert runtime["planner_health"] in {"disabled", "ready", "degraded"}
        assert runtime["task_management_mode"] == "read_only"
        assert runtime["deepsearch_recovery_running"] is False
        assert not any(key.startswith("research_writer_") for key in runtime)
        assert not any(key.startswith("research_preview_") for key in runtime)
        metrics = runtime["orchestration_metrics"]
        assert metrics["cost"] is None
        assert "candidate_retrieval_p95_ms" in metrics
        assert "source_coverage_rate" in metrics

    @pytest.mark.parametrize(
        ("configured", "effective"),
        [("off", "off"), ("preview", "preview"), ("execute", "execute"), ("invalid", "off")],
    )
    def test_bootstrap_and_health_expose_the_same_fail_closed_orchestration_mode(
        self,
        auth_client: TestClient,
        configured: str,
        effective: str,
    ):
        with patch.dict(
            "os.environ",
            {
                "AGENTMESH_AGENT_RUNTIME": "v2",
                "AGENTMESH_SKILL_ORCHESTRATION": configured,
            },
        ):
            bootstrap = auth_client.get("/api/bootstrap")
            health = auth_client.get("/api/health/providers")

        assert bootstrap.status_code == 200
        assert bootstrap.json()["agent_runtime_enabled"] is True
        assert bootstrap.json()["skill_orchestration_mode"] == effective
        runtime = next(item for item in health.json()["providers"] if item["name"] == "openai_agents_sdk")
        assert runtime["runtime_enabled"] is True
        assert runtime["skill_orchestration_mode"] == effective

    @pytest.mark.parametrize(
        ("configured", "effective"),
        [("read_only", "read_only"), ("write", "write"), ("invalid", "read_only")],
    )
    def test_bootstrap_and_health_expose_the_same_fail_closed_task_management_mode(
        self,
        auth_client: TestClient,
        configured: str,
        effective: str,
    ) -> None:
        with patch.dict("os.environ", {"AGENTMESH_TASK_MANAGEMENT": configured}):
            bootstrap = auth_client.get("/api/bootstrap")
            health = auth_client.get("/api/health/providers")

        assert bootstrap.status_code == 200
        assert bootstrap.json()["task_management_mode"] == effective
        runtime = next(item for item in health.json()["providers"] if item["name"] == "openai_agents_sdk")
        assert runtime["task_management_mode"] == effective

    def test_health_projects_actual_recovery_task_state_instead_of_inferring_from_mode(
        self,
        auth_client: TestClient,
    ) -> None:
        app.state.deepsearch_recovery_coordinator = SimpleNamespace(running=True)
        try:
            with patch.dict(
                "os.environ",
                {"AGENTMESH_SKILL_ORCHESTRATION": "off"},
            ):
                health = auth_client.get("/api/health/providers")
        finally:
            del app.state.deepsearch_recovery_coordinator

        runtime = next(item for item in health.json()["providers"] if item["name"] == "openai_agents_sdk")
        assert runtime["skill_orchestration_mode"] == "off"
        assert runtime["deepsearch_recovery_running"] is True

    def test_off_lifespan_reports_real_recovery_task_as_stopped(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import agentmesh.app as application

        monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "off")
        monkeypatch.setattr(application.ingestion_service, "shutdown", lambda: None)
        with TestClient(app) as client:
            login = client.post(
                "/api/auth/login",
                json={"user_id": ADMIN.id, "password": "admin123"},
            )
            assert login.status_code == 200
            health = client.get("/api/health/providers")
            assert health.status_code == 200
            coordinator = app.state.deepsearch_recovery_coordinator
            assert coordinator is not None
            assert coordinator.running is False

        runtime = next(item for item in health.json()["providers"] if item["name"] == "openai_agents_sdk")
        assert runtime["skill_orchestration_mode"] == "off"
        assert runtime["deepsearch_recovery_running"] is False

    def test_skill_search_index_health_degrades_when_a_definition_is_missing(
        self,
        auth_client: TestClient,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        repository = SQLiteStore(tmp_path / "health-index.sqlite3")
        profile = SkillCapabilityProfile(
            id="skill_health_index",
            skill_id="skill_health_index",
            skill_name="health-index",
            skill_version="1",
            skill_content_hash="skill-hash",
            profile_version="1",
            profile_content_hash="profile-hash",
            primary_stage=SkillLifecycleStage.PRE_DESIGN,
            capability_type=SkillCapabilityType.ANALYSIS,
        )
        definition = SkillDefinition(
            id=profile.skill_id,
            name=profile.skill_name,
            title="Health index",
            description="Health index test Skill",
            instructions="# Test",
            source_path="/test/health-index/SKILL.md",
            source_scope=SkillSourceScope.WORKSPACE,
            content_hash=profile.skill_content_hash,
        )
        repository.save_skill_definition(definition)
        repository.save_skill_capability_profile(profile)
        catalog = SimpleNamespace(diagnostics=[], list_enabled=lambda: [])
        monkeypatch.setattr(health_routes, "store", repository)
        monkeypatch.setattr(health_routes, "catalog_service", lambda: catalog)

        ready_response = auth_client.get("/api/health/providers")
        ready_runtime = next(
            item for item in ready_response.json()["providers"] if item["name"] == "openai_agents_sdk"
        )
        assert ready_runtime["index_health"] == "ready"
        assert ready_runtime["index_counts"] == {"records": 2, "indexed": 2, "missing": 0}

        with sqlite3.connect(repository.db_path) as connection:
            connection.execute(
                "DELETE FROM records_fts WHERE collection = ? AND record_id = ?",
                ("skill_definitions", definition.id),
            )

        degraded_response = auth_client.get("/api/health/providers")
        degraded_runtime = next(
            item for item in degraded_response.json()["providers"] if item["name"] == "openai_agents_sdk"
        )
        assert degraded_runtime["index_health"] == "degraded"
        assert degraded_runtime["index_counts"] == {"records": 2, "indexed": 1, "missing": 1}

    def test_plan_modification_rate_counts_modified_plans_once(self, monkeypatch: pytest.MonkeyPatch):
        created_at = datetime(2026, 8, 19, tzinfo=UTC)
        run = SimpleNamespace(
            id="run_modified_plan",
            status=SimpleNamespace(value="completed"),
            orchestration_mode="execute",
            created_at=created_at,
            updated_at=created_at,
        )
        plan = SimpleNamespace(
            id="plan_modified_once",
            status=SimpleNamespace(value="completed"),
            nodes=[],
        )
        events = [
            SimpleNamespace(event_type="plan_waiting_approval", payload={}, created_at=created_at),
            SimpleNamespace(event_type="plan_updated", payload={}, created_at=created_at),
            SimpleNamespace(event_type="plan_updated", payload={}, created_at=created_at),
        ]
        repository = SimpleNamespace(
            get_skill_plan_for_run=lambda _run_id: plan,
            list_skill_node_results=lambda _plan_id: [],
            list_agent_run_events=lambda _run_id: events,
        )
        monkeypatch.setattr(health_routes, "store", repository)

        metrics = health_routes._orchestration_metrics([run])

        assert metrics["plan_modification_rate"] == 1.0

    def test_three_node_latency_uses_execution_events_not_confirmation_wait(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        created_at = datetime(2026, 8, 19, tzinfo=UTC)
        run = SimpleNamespace(
            id="run_three_nodes",
            status=SimpleNamespace(value="completed"),
            orchestration_mode="execute",
            created_at=created_at,
            updated_at=created_at + timedelta(hours=2),
        )
        node = SimpleNamespace(started_at=None, completed_at=None)
        plan = SimpleNamespace(
            id="plan_three_nodes",
            status=SimpleNamespace(value="completed"),
            nodes=[node, node, node],
        )
        events = [
            SimpleNamespace(event_type="plan_waiting_approval", payload={}, created_at=created_at),
            SimpleNamespace(
                event_type="plan_approved",
                payload={},
                created_at=created_at + timedelta(hours=1),
            ),
            SimpleNamespace(
                event_type="plan_execution_started",
                payload={},
                created_at=created_at + timedelta(hours=1, seconds=1),
            ),
            SimpleNamespace(
                event_type="run_completed",
                payload={},
                created_at=created_at + timedelta(hours=1, seconds=11),
            ),
        ]
        repository = SimpleNamespace(
            get_skill_plan_for_run=lambda _run_id: plan,
            list_skill_node_results=lambda _plan_id: [],
            list_agent_run_events=lambda _run_id: events,
        )
        monkeypatch.setattr(health_routes, "store", repository)

        metrics = health_routes._orchestration_metrics([run])

        assert metrics["three_node_run_p95_ms"] == 10_000.0

    def test_deepsearch_metrics_are_isolated_and_use_only_stable_labels(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        created_at = datetime(2026, 8, 26, tzinfo=UTC)
        deepsearch_run = SimpleNamespace(
            id="run_deepsearch_metrics",
            planning_mode=AgentPlanningMode.DEEPSEARCH,
            status=AgentRunStatus.PARTIAL,
            error_code="deepsearch_review_not_passed",
            created_at=created_at,
            updated_at=created_at + timedelta(seconds=10),
        )
        standard_run = SimpleNamespace(
            id="run_standard_metrics",
            planning_mode=AgentPlanningMode.STANDARD,
            status=AgentRunStatus.FAILED,
            error_code="deepsearch_planning_failed",
            created_at=created_at,
            updated_at=created_at + timedelta(days=1),
        )
        plan = SimpleNamespace(
            capability_gaps=["required_tool_unavailable:secret-tool-name"],
            evidence_coverage=SimpleNamespace(passed=True),
            review_outcomes=[
                SimpleNamespace(outcome="revise"),
                SimpleNamespace(outcome="pass"),
            ],
        )
        events = [
            SimpleNamespace(
                event_type="deepsearch_clarification_requested",
                payload={"clarification_round": 2},
                created_at=created_at + timedelta(seconds=1),
            ),
            SimpleNamespace(
                event_type="deepsearch_finalization_stage_changed",
                payload={"to_stage": "nodes_terminal"},
                created_at=created_at + timedelta(seconds=4),
            ),
            SimpleNamespace(
                event_type="deepsearch_finalization_stage_changed",
                payload={"to_stage": "evidence_manifest_sealed"},
                created_at=created_at + timedelta(seconds=7),
            ),
        ]
        repository = SimpleNamespace(
            get_skill_plan_for_run=lambda run_id: plan if run_id == deepsearch_run.id else None,
            list_agent_run_events=lambda run_id: events if run_id == deepsearch_run.id else [],
        )
        monkeypatch.setattr(health_routes, "store", repository)
        monkeypatch.setattr(
            health_routes,
            "deepsearch_admission_rejections",
            lambda: {"disabled": 2},
        )

        metrics = health_routes._deepsearch_metrics([deepsearch_run, standard_run])

        assert metrics == {
            "runs_started": 1,
            "terminal_status_counts": {"partial": 1},
            "clarification_round_counts": {"2": 1},
            "clarification_exhaustion_rate": 0.0,
            "planning_failure_rate": 0.0,
            "capability_gap_counts": {"required_tool_unavailable": 1},
            "evidence_pass_rate": 1.0,
            "review_verdict_counts": {"revise": 1, "pass": 1},
            "review_revision_rate": 1.0,
            "partial_failed_rate": 1.0,
            "stage_duration_p95_ms": 3000.0,
            "end_to_end_p95_ms": 10000.0,
            "admission_rejected_by_code": {"disabled": 2},
            "admission_window": "process_lifetime",
        }

    def test_llm_not_configured(self, auth_client: TestClient):
        """LLM 未配置时返回 not_configured 状态。"""
        env_overrides = {
            "AI_API_URL": "",
            "AI_API_KEY": "",
            "AI_MODEL": "",
            "AGENTMESH_LLM_BASE_URL": "",
            "AGENTMESH_LLM_API_KEY": "",
            "AGENTMESH_LLM_MODEL": "",
        }
        with patch.dict("os.environ", env_overrides):
            response = auth_client.get("/api/health/providers")
        data = response.json()
        llm = next(p for p in data["providers"] if p["name"] == "llm")
        assert llm["status"] == "not_configured"

    def test_llm_configured(self, auth_client: TestClient):
        """LLM 配置正确时返回 configured 状态。"""
        env = {
            "AI_API_URL": "",
            "AI_API_KEY": "",
            "AI_MODEL": "",
            "AGENTMESH_LLM_BASE_URL": "https://api.example.com/v1",
            "AGENTMESH_LLM_API_KEY": "sk-test-key",
            "AGENTMESH_LLM_MODEL": "gpt-4",
            "AGENTMESH_CHAT_LLM_TIMEOUT_SECONDS": "2.5",
            "AGENTMESH_SKILL_MATCH_LLM_TIMEOUT_SECONDS": "4.5",
            "AGENTMESH_LLM_CONNECT_TIMEOUT_SECONDS": "1.5",
        }
        with patch.dict("os.environ", env):
            response = auth_client.get("/api/health/providers")
        data = response.json()
        llm = next(p for p in data["providers"] if p["name"] == "llm")
        assert llm["status"] == "configured"
        assert "base_url" not in llm
        assert "sk-test-key" not in response.text
        assert llm["model"] == "gpt-4"
        assert llm["timeouts"]["chat_timeout_seconds"] == 2.5
        assert llm["timeouts"]["skill_match_timeout_seconds"] == 4.5
        assert llm["timeouts"]["connect_timeout_seconds"] == 1.5

    def test_ai_api_responses_configured(self, auth_client: TestClient):
        """兼容 AI_* Responses API 配置。"""
        env = {
            "AI_API_URL": "https://modelservice.jdcloud.com/v1/responses",
            "AI_API_KEY": "pk-test-key",
            "AI_MODEL": "Gemini-3-Flash-Preview",
        }
        with patch.dict("os.environ", env, clear=False):
            response = auth_client.get("/api/health/providers")
        data = response.json()
        llm = next(p for p in data["providers"] if p["name"] == "llm")
        assert llm["status"] == "configured"
        assert "base_url" not in llm
        assert "pk-test-key" not in response.text
        assert llm["model"] == "Gemini-3-Flash-Preview"
        assert llm["api_style"] == "gemini_contents"

    def test_web_provider_not_configured(self, auth_client: TestClient):
        """Web provider 未配置时返回 not_configured。"""
        with patch.dict("os.environ", {"AGENTMESH_WEB_PROVIDER": ""}):
            response = auth_client.get("/api/health/providers")
        data = response.json()
        web = next(p for p in data["providers"] if p["name"] == "web_research")
        assert web["status"] == "not_configured"

    def test_web_provider_command_not_found(self, auth_client: TestClient):
        """Web provider 命令不存在时返回 command_not_found。"""
        with (
            patch.dict("os.environ", {"AGENTMESH_WEB_PROVIDER": "opencli"}),
            patch("agentmesh.routes.health.shutil.which", return_value=None),
        ):
            response = auth_client.get("/api/health/providers")
        data = response.json()
        web = next(p for p in data["providers"] if p["name"] == "web_research")
        assert web["status"] == "command_not_found"
        assert web["provider_type"] == "opencli"

    def test_tavily_provider_is_ready_and_secret_safe(self, auth_client: TestClient):
        env = {
            "AGENTMESH_WEB_PROVIDER": "tavily",
            "AGENTMESH_TAVILY_API_URL": "https://api.tavily.com/search",
            "AGENTMESH_TAVILY_API_KEY": "secret-tavily-key",
            "AGENTMESH_FIRECRAWL_ENABLED": "",
        }
        with (
            patch.dict("os.environ", env),
            patch("agentmesh.web_research._tavily_telemetry", ProviderTelemetry()),
        ):
            response = auth_client.get("/api/health/providers")

        web = next(item for item in response.json()["providers"] if item["name"] == "web_research")
        assert web["configured"] is True
        assert web["ready"] is True
        assert web["provider_type"] == "tavily"
        assert "secret-tavily-key" not in response.text
        assert "api.tavily.com" not in response.text

    def test_tavily_firecrawl_provider_is_ready_and_secret_safe(self, auth_client: TestClient):
        env = {
            "AGENTMESH_WEB_PROVIDER": "tavily",
            "AGENTMESH_TAVILY_API_URL": "https://api.tavily.com/search",
            "AGENTMESH_TAVILY_API_KEY": "secret-tavily-key",
            "AGENTMESH_FIRECRAWL_ENABLED": "true",
            "AGENTMESH_FIRECRAWL_API_URL": "https://api.firecrawl.dev/v2/scrape",
            "AGENTMESH_FIRECRAWL_API_KEY": "secret-firecrawl-key",
        }
        with (
            patch.dict("os.environ", env),
            patch("agentmesh.web_research._tavily_telemetry", ProviderTelemetry()),
            patch("agentmesh.web_research._firecrawl_telemetry", ProviderTelemetry()),
        ):
            response = auth_client.get("/api/health/providers")

        web = next(item for item in response.json()["providers"] if item["name"] == "web_research")
        assert web["configured"] is True
        assert web["ready"] is True
        assert web["provider_type"] == "tavily"
        assert web["content_provider"] == "firecrawl"
        assert "secret-tavily-key" not in response.text
        assert "secret-firecrawl-key" not in response.text
        assert "api.firecrawl.dev" not in response.text

    def test_o2_not_installed(self, auth_client: TestClient):
        """O2 CLI 未安装时返回 not_installed。"""
        with patch("agentmesh.routes.health.O2CommandRunner") as mock_runner_cls:
            mock_runner = mock_runner_cls.return_value
            mock_runner.available.return_value = False
            mock_runner.binary = "o2"
            response = auth_client.get("/api/health/providers")
        data = response.json()
        o2 = next(p for p in data["providers"] if p["name"] == "o2")
        assert o2["status"] == "not_installed"

    def test_o2_installed(self, auth_client: TestClient):
        """O2 CLI 已安装时返回 installed 状态。"""
        env = {
            "AGENTMESH_O2_RESEARCH_ENABLED": "true",
            "AGENTMESH_O2_DATA_ENABLED": "false",
            "AGENTMESH_O2_RESEARCH_CLI": "metasearch",
        }
        with patch("agentmesh.routes.health.O2CommandRunner") as mock_runner_cls:
            mock_runner = mock_runner_cls.return_value
            mock_runner.available.return_value = True
            mock_runner.binary = "o2"
            with patch.dict("os.environ", env):
                response = auth_client.get("/api/health/providers")
        data = response.json()
        o2 = next(p for p in data["providers"] if p["name"] == "o2")
        assert o2["status"] == "installed"
        assert o2["research_enabled"] is True
        assert o2["data_enabled"] is False
        assert o2["research_cli"] == "metasearch"

    def test_data_connectors_has_default(self, auth_client: TestClient):
        """数据连接器默认包含 local_metrics。"""
        response = auth_client.get("/api/health/providers")
        data = response.json()
        dc = next(p for p in data["providers"] if p["name"] == "data_connectors")
        assert dc["status"] == "ready"
        assert dc["count"] >= 1
        assert "local_metrics" in dc["connectors"]

    def test_data_connectors_include_http_api_when_configured(self, auth_client: TestClient):
        """配置真实数据 API 后暴露 http_data_api connector。"""
        with patch.dict("os.environ", {"AGENTMESH_DATA_API_URL": "https://bi.example/api/data"}):
            response = auth_client.get("/api/health/providers")
        data = response.json()
        dc = next(p for p in data["providers"] if p["name"] == "data_connectors")
        assert "http_data_api" in dc["connectors"]
        assert "local_metrics" in dc["connectors"]

    def test_document_parser_always_ready(self, auth_client: TestClient):
        """文档解析器始终返回 ready 状态。"""
        response = auth_client.get("/api/health/providers")
        data = response.json()
        dp = next(p for p in data["providers"] if p["name"] == "document_parser")
        assert dp["configured"] is True
        assert dp["ready"] is True
        assert dp["mode"] == "real"
        assert dp["last_error"] is None
        assert dp["latency_ms"] is None
        assert dp["status"] == "ready"
        assert ".txt" in dp["supported_extensions"]
        assert ".md" in dp["supported_extensions"]

    def test_overall_degraded_when_not_all_ready(self, auth_client: TestClient):
        """有 provider 异常时 overall 为 degraded。"""
        with patch.dict("os.environ", {"AGENTMESH_WEB_PROVIDER": ""}):
            response = auth_client.get("/api/health/providers")
        data = response.json()
        assert data["overall"] == "degraded"
