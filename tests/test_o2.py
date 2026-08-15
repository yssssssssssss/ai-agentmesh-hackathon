from unittest.mock import patch

import pytest

from agentmesh.acquisition import AcquisitionRequest, AcquisitionResult
from agentmesh.datasources import DataSourceQuery
from agentmesh.models import Intent, Source
from agentmesh.o2 import (
    CompositeAcquisitionAgent,
    O2CommandError,
    O2DataSourceConnector,
    O2RegistryAdapter,
    O2ResearchProvider,
    o2_setup_checks,
)
from agentmesh.web_research import WebResearchError


class FakeRunner:
    binary = "o2"

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def available(self):
        return True

    def run_json(self, *args):
        self.calls.append(args)
        return self.payload


class FakeCommandResult:
    def __init__(self, stdout: str):
        self.stdout = stdout


class FakeStatusRunner(FakeRunner):
    def run(self, *args):
        self.calls.append(args)
        return FakeCommandResult("o2 0.0.5")


class FakeSetupRunner(FakeRunner):
    def __init__(self):
        self.calls = []
        self.binary = "o2"

    def available(self):
        return True

    def run_json(self, *args):
        self.calls.append(args)
        if args == ("login", "--status", "--json"):
            return {"logged_in": True}
        if args == ("launch", "metasearch", "--json", "doctor"):
            return {"data": {"token_available": True}}
        if args == ("launch", "o2-kb", "config", "list", "--json"):
            return {"ok": True}
        if args == ("launch", "oxygen-comment", "--json", "doctor"):
            return {"result": {"ready": False, "reason": "missing credentials"}}
        return {}

    def run(self, *args):
        self.calls.append(args)
        if args == ("launch", "bdp-copilot", "--help"):
            return FakeCommandResult("bdp-copilot help")
        raise RuntimeError("unsupported command")


def test_o2_registry_adapter_maps_discovered_tools() -> None:
    runner = FakeRunner(
        {
            "clis": [
                {
                    "name": "metasearch",
                    "description": "京东商品搜索 CLI",
                    "category": "retail",
                    "version": "1.0.0",
                    "entry_point": "metasearch",
                }
            ]
        }
    )

    tools = O2RegistryAdapter(runner).discover_tools()

    assert tools[0].id == "o2_metasearch"
    assert tools[0].provider == "o2"
    assert tools[0].external_name == "metasearch"
    assert tools[0].metadata["entry_point"] == "metasearch"


def test_o2_registry_status_redacts_sensitive_login_payload() -> None:
    runner = FakeStatusRunner(
        {
            "logged_in": True,
            "auth": {
                "sso_cookie": "sso.jd.com=secret",
                "access_token": "secret-token",
                "username": "designer",
                "server": "http://oxygen-clihub.jd.com",
            },
        }
    )

    with patch("agentmesh.o2.shutil.which", return_value=None):
        status = O2RegistryAdapter(runner).status()

    assert status["login"]["logged_in"] is True
    assert status["login"]["raw"]["auth"]["sso_cookie"] == "[REDACTED]"
    assert status["login"]["raw"]["auth"]["access_token"] == "[REDACTED]"
    assert status["login"]["raw"]["auth"]["username"] == "designer"


def test_o2_setup_checks_report_tool_prerequisites() -> None:
    runner = FakeSetupRunner()

    with patch("agentmesh.o2.shutil.which", return_value=None):
        checks = o2_setup_checks(runner)

    by_id = {item["id"]: item for item in checks}
    assert by_id["o2_registry_login"]["status"] == "ready"
    assert by_id["metasearch_token"]["status"] == "ready"
    assert by_id["o2_kb_init"]["status"] == "ready"
    assert by_id["oxygen_comment_credentials"]["status"] == "needs_config"
    assert by_id["bdp_copilot_runtime"]["status"] == "ready"
    assert by_id["browser_bridge"]["status"] == "unavailable"


def test_o2_research_provider_returns_source_ready_results() -> None:
    runner = FakeRunner(
        {"items": [{"title": "JoySpace 文档", "url": "https://joyspace.jd.com/doc", "snippet": "内部资料摘要"}]}
    )

    results = O2ResearchProvider(runner=runner, cli_name="oxygen-kb").search("会场复盘", limit=1)

    assert results[0].title == "JoySpace 文档"
    assert results[0].url == "https://joyspace.jd.com/doc"
    assert runner.calls[0][:3] == ("launch", "oxygen-kb", "search")


def test_o2_research_provider_uses_metasearch_command_shape() -> None:
    runner = FakeRunner(
        {"data": {"products": [{"title": "华为手机", "url": "https://jd.com/item", "snippet": "好评"}]}}
    )

    results = O2ResearchProvider(runner=runner, cli_name="metasearch").search("华为手机", limit=1)

    assert results[0].title == "华为手机"
    # o2 main-entry fallback shape (FakeRunner reports binary "o2"): verified
    # DesignOS contract carries an explicit endpoint and no token-env.
    assert runner.calls[0][:4] == ("launch", "metasearch", "search", "华为手机")
    assert "--endpoint" in runner.calls[0]
    assert "--token-env" not in runner.calls[0]


def test_o2_research_provider_uses_standalone_metasearch_when_available() -> None:
    runner = FakeRunner(
        {"data": {"products": [{"title": "华为手机", "url": "https://jd.com/item", "snippet": "好评"}]}}
    )
    runner.binary = "oxygen-metasearch"

    provider = O2ResearchProvider(runner=runner, cli_name="metasearch", endpoint="https://gw.example/agents/sku-search")
    provider.search("华为手机", limit=1)

    # Verified DesignOS standalone form: oxygen-metasearch --json search --output json --endpoint <ep> <query>
    assert runner.calls[0] == (
        "--json",
        "search",
        "--output",
        "json",
        "--endpoint",
        "https://gw.example/agents/sku-search",
        "华为手机",
    )


def test_o2_data_connector_keeps_read_only_business_query_shape() -> None:
    runner = FakeRunner({"items": [{"title": "SKU A", "price": 99, "nested": {"ignored": True}}]})
    connector = O2DataSourceConnector(runner=runner, cli_name="metasearch")

    result = connector.query(
        DataSourceQuery(
            connector_name="o2_cli",
            operation="search",
            parameters={"keyword": "夏日清凉体恤", "limit": 1},
            workspace_id="ws",
            project_id="proj",
            requested_by="usr",
        )
    )

    assert result.connector_name == "o2_cli"
    assert result.metadata["requested_provider"] == "o2_cli"
    assert result.metadata["actual_provider"] == "o2:metasearch"
    assert result.metadata["mode"] == "real"
    assert "provider" not in result.metadata
    assert result.records == [{"title": "SKU A", "price": 99}]
    assert result.source.reference == "o2://metasearch/search"


def test_o2_data_connector_uses_comment_and_bdp_command_shapes() -> None:
    comment_runner = FakeRunner({"result": {"data": {"results": [{"orderId": "1", "content": "差评"}]}}})
    comment_connector = O2DataSourceConnector(runner=comment_runner, cli_name="oxygen-comment")
    comment_result = comment_connector.query(
        DataSourceQuery(
            connector_name="o2_cli",
            operation="search",
            parameters={"comment_level": 1, "page": 1, "limit": 3, "dry_run": True},
            workspace_id="ws",
            project_id="proj",
            requested_by="usr",
        )
    )

    bdp_runner = FakeRunner({"tables": [{"name": "order_table"}]})
    bdp_connector = O2DataSourceConnector(runner=bdp_runner, cli_name="bdp-copilot")
    bdp_result = bdp_connector.query(
        DataSourceQuery(
            connector_name="o2_cli",
            operation="find-tables",
            parameters={"query": "用户订单"},
            workspace_id="ws",
            project_id="proj",
            requested_by="usr",
        )
    )

    assert comment_result.records == [{"orderId": "1", "content": "差评"}]
    assert comment_runner.calls[0][:4] == ("launch", "oxygen-comment", "--json", "--dry-run")
    assert "comment" in comment_runner.calls[0]
    assert bdp_result.records == [{"name": "order_table"}]
    assert bdp_runner.calls[0][:3] == ("launch", "bdp-copilot", "--json-output")


def test_composite_acquisition_uses_real_provider_with_sources_before_mock() -> None:
    class FailingAgent:
        actor = "o2_research_agent"

        def acquire(self, request):
            raise RuntimeError("auth_required")

    class WebAgent:
        actor = "web_research_agent"

        def acquire(self, request):
            return AcquisitionResult(
                actor=self.actor,
                title="Web 资料",
                content="外部 Web 找到了资料。",
                sources=[Source(title="Web Page", source_type="web_page", reference="https://example.com")],
                metadata={
                    "requested_provider": "o2_research",
                    "actual_provider": "web",
                    "mode": "real",
                    "latency_ms": "1.000",
                },
            )

    result = CompositeAcquisitionAgent([FailingAgent(), WebAgent()]).acquire(_acquisition_request())

    assert result.actor == "web_research_agent"
    assert result.metadata["requested_provider"] == "o2_research"
    assert result.metadata["actual_provider"] == "web"


def test_composite_propagates_configured_provider_failure_when_no_sources() -> None:
    class EmptyAgent:
        actor = "o2_research_agent"

        def acquire(self, request):
            return AcquisitionResult(
                actor=self.actor,
                title="未找到 Oxygen-CLI 资料",
                content="Oxygen-CLI 没有返回可用结果。",
                sources=[],
                metadata={
                    "requested_provider": "o2_research",
                    "actual_provider": "o2_research",
                    "mode": "real",
                    "latency_ms": "1.000",
                },
            )

    class FailingAgent:
        actor = "web_research_agent"

        def acquire(self, request):
            raise WebResearchError("auth_error", "Tavily authentication failed")

    with pytest.raises(WebResearchError) as captured:
        CompositeAcquisitionAgent([EmptyAgent(), FailingAgent()]).acquire(_acquisition_request())

    assert captured.value.reason == "auth_error"


def test_composite_raises_when_all_configured_providers_return_empty() -> None:
    class EmptyAgent:
        actor = "o2_research_agent"

        def acquire(self, request):
            return AcquisitionResult(
                actor=self.actor,
                title="No sources",
                content="No sources",
                sources=[],
                metadata={"mode": "real"},
            )

    with pytest.raises(O2CommandError) as captured:
        CompositeAcquisitionAgent([EmptyAgent()]).acquire(_acquisition_request())

    assert captured.value.reason == "empty_result"


def _acquisition_request() -> AcquisitionRequest:
    return AcquisitionRequest(
        query="618 家电会场",
        intent=Intent.REQUEST_EXTERNAL_RESEARCH,
        workspace_id="ws",
        project_id="prj",
        user_id="usr",
        task_id="task",
        request_post_id="post",
    )
