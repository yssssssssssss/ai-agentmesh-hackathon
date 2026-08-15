import httpx
import pytest

from agentmesh.datasources import (
    DataSourceQuery,
    DataSourceRegistry,
    DataSourceResult,
    ExternalDataSourceConnector,
    HTTPDataAPIConnector,
    LocalMetricsConnector,
    default_data_source_registry,
)
from agentmesh.models import Source
from agentmesh.seed import PROJECT, USER, WORKSPACE


def test_data_source_query_accepts_generic_parameters() -> None:
    query = DataSourceQuery(
        connector_name="future_bi",
        operation="query",
        parameters={"metric": "conversion_rate", "date": "2026-06-13"},
        workspace_id=WORKSPACE.id,
        project_id=PROJECT.id,
        requested_by=USER.id,
    )

    assert query.connector_name == "future_bi"
    assert query.parameters["metric"] == "conversion_rate"
    assert query.workspace_id == WORKSPACE.id


def test_data_source_result_carries_records_and_source() -> None:
    result = DataSourceResult(
        connector_name="future_bi",
        title="转化率查询结果",
        records=[{"date": "2026-06-13", "conversion_rate": 0.123}],
        source=Source(
            title="future_bi",
            source_type="data_source",
            reference="datasource://future_bi/query",
        ),
        metadata={
            "requested_provider": "future_bi",
            "actual_provider": "external_project",
            "mode": "real",
            "latency_ms": "4.000",
        },
    )

    assert result.records[0]["conversion_rate"] == 0.123
    assert result.source.source_type == "data_source"
    assert result.metadata["requested_provider"] == "future_bi"
    assert result.metadata["actual_provider"] == "external_project"
    assert "provider" not in result.metadata


def test_external_data_source_connector_is_explicit_placeholder() -> None:
    query = DataSourceQuery(
        connector_name="future_bi",
        operation="query",
        parameters={"metric": "conversion_rate"},
        workspace_id=WORKSPACE.id,
        project_id=PROJECT.id,
        requested_by=USER.id,
    )

    with pytest.raises(NotImplementedError, match="External data source"):
        ExternalDataSourceConnector().query(query)


def test_data_source_registry_routes_to_connector() -> None:
    registry = DataSourceRegistry()
    registry.register(LocalMetricsConnector.connector_name, LocalMetricsConnector())

    result = registry.query(
        DataSourceQuery(
            connector_name="local_metrics",
            operation="query",
            parameters={"metric": "ctr"},
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
            requested_by=USER.id,
        )
    )

    assert result.connector_name == "local_metrics"
    assert result.records[0]["metric"] == "ctr"
    assert registry.list_connectors() == ["local_metrics"]


def test_data_source_registry_falls_back_to_next_connector() -> None:
    class FailingConnector:
        def query(self, query: DataSourceQuery) -> DataSourceResult:
            raise RuntimeError("auth_required")

    registry = DataSourceRegistry()
    registry.register("o2_cli", FailingConnector())
    registry.register(LocalMetricsConnector.connector_name, LocalMetricsConnector())

    result = registry.query_first_available(
        connector_names=["o2_cli", "local_metrics"],
        operation="query",
        parameters={"metric": "ctr"},
        workspace_id=WORKSPACE.id,
        project_id=PROJECT.id,
        requested_by=USER.id,
    )

    assert result.connector_name == "local_metrics"
    assert result.metadata["fallback_diagnostics"] == "o2_cli: auth_required"
    assert result.metadata["requested_provider"] == "o2_cli"
    assert result.metadata["actual_provider"] == "local_metrics"
    assert result.metadata["mode"] == "fallback"
    assert result.metadata["fallback_reason"] == "explicit_local_metrics"
    assert float(result.metadata["latency_ms"]) >= 0


def test_http_data_api_connector_posts_query_and_normalizes_records() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["payload"] = request.read()
        return httpx.Response(
            200,
            json={
                "title": "真实 BI 查询结果",
                "source_title": "business_metrics_api",
                "source_reference": "https://bi.example/query/123",
                "records": [{"metric": "ctr", "value": 0.42, "nested": {"date": "2026-06-18"}}],
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = HTTPDataAPIConnector(
        base_url="https://bi.example/api/data",
        api_key="secret-token",
        http_client=http_client,
    )

    result = connector.query(
        DataSourceQuery(
            connector_name="http_data_api",
            operation="query ctr",
            parameters={"metric": "ctr"},
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
            requested_by=USER.id,
        )
    )

    assert result.connector_name == "http_data_api"
    assert result.title == "真实 BI 查询结果"
    assert result.records == [{"metric": "ctr", "value": 0.42, "nested": "{'date': '2026-06-18'}"}]
    assert result.source.title == "business_metrics_api"
    assert captured["url"] == "https://bi.example/api/data/query_ctr"
    assert captured["authorization"] == "Bearer secret-token"
    assert f'"workspace_id":"{WORKSPACE.id}"'.encode() in captured["payload"]


def test_default_registry_registers_http_data_api_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTMESH_DATA_API_URL", "https://bi.example/api/data")

    registry = default_data_source_registry()

    assert registry.list_connectors() == ["http_data_api", "local_metrics"]
