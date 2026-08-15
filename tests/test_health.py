"""Tests for provider health check endpoint."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agentmesh.app import app
from agentmesh.provider_status import ProviderTelemetry
from agentmesh.seed import ADMIN


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
