from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
import pytest

import agentmesh.datasources as datasources
import agentmesh.embedding as embedding
import agentmesh.llm as llm
import agentmesh.o2 as o2
from agentmesh.acquisition import AcquisitionRequest, AcquisitionResult
from agentmesh.data_authorization import DATA_QUERY_TOOL_ID
from agentmesh.datasources import DataSourceQuery, HTTPDataAPIConnector, LocalMetricsConnector
from agentmesh.llm import LLMClient, LLMRequestError
from agentmesh.models import Agent, AgentToolGrant, Intent, ToolDefinition, User, UserRole
from agentmesh.o2 import CompositeAcquisitionAgent
from agentmesh.provider_status import ProviderStatus, ProviderTelemetry, redact_sensitive_text
from agentmesh.routes import data_sources as data_source_routes
from agentmesh.routes import health
from agentmesh.web_research import WebAcquisitionAgent, WebSearchResult
from scripts import provider_smoke


class FakeEmbeddingResponse:
    def __init__(self, payload: object):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


class FakeEmbeddingClient:
    def __init__(self, response: FakeEmbeddingResponse | BaseException):
        self.response = response

    def post(self, *args, **kwargs):
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


class RecordingEmbeddingClient(FakeEmbeddingClient):
    def __init__(self, response: FakeEmbeddingResponse | BaseException):
        super().__init__(response)
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return super().post(*args, **kwargs)


def _query(connector_name: str = "http_data_api", operation: str = "query") -> DataSourceQuery:
    return DataSourceQuery(
        connector_name=connector_name,
        operation=operation,
        parameters={"metric": "ctr"},
        workspace_id="ws_default",
        project_id="proj_default",
        requested_by="usr_provider_test",
    )


def _acquisition_request() -> AcquisitionRequest:
    return AcquisitionRequest(
        query="provider contract",
        intent=Intent.REQUEST_EXTERNAL_RESEARCH,
        workspace_id="ws_default",
        project_id="proj_default",
        user_id="usr_provider_test",
        task_id="task_provider_test",
        request_post_id="post_provider_test",
    )


def test_provider_status_has_one_secret_safe_serializable_contract() -> None:
    status = ProviderStatus(
        name="llm",
        configured=True,
        ready=False,
        mode="fallback",
        last_error="Bearer super-secret token=abc https://user:pass@example.test/v1?api_key=hidden",
        latency_ms=12.25,
    )

    payload = status.model_dump(mode="json")
    serialized = json.dumps(payload)

    assert set(payload) == {
        "name",
        "configured",
        "ready",
        "mode",
        "checked_at",
        "last_error",
        "latency_ms",
    }
    assert payload["checked_at"].endswith("Z")
    assert "super-secret" not in serialized
    assert "hidden" not in serialized
    assert "user:pass" not in serialized
    assert payload["last_error"] == "Bearer [REDACTED] token=[REDACTED] https://example.test/v1"


def test_health_returns_canonical_secret_safe_provider_contracts(monkeypatch: pytest.MonkeyPatch) -> None:
    statuses = {
        "embedding_provider_status": ProviderStatus(
            name="embedding", configured=True, ready=True, mode="real", latency_ms=2.0
        ),
        "o2_research_provider_status": ProviderStatus(
            name="o2_research", configured=True, ready=False, mode="fallback", last_error="auth_error"
        ),
        "web_research_provider_status": ProviderStatus(
            name="web_research", configured=False, ready=False, mode="fallback", last_error="not_configured"
        ),
        "data_api_provider_status": ProviderStatus(
            name="data_api", configured=True, ready=True, mode="real", latency_ms=4.0
        ),
        "llm_provider_status": ProviderStatus(name="llm", configured=True, ready=True, mode="real", latency_ms=8.0),
    }
    for function_name, status in statuses.items():
        monkeypatch.setattr(health, function_name, lambda *_, value=status: value)

    payload = health._provider_health_snapshot()
    providers = payload.providers
    serialized = payload.model_dump_json()

    assert {item.name for item in providers} == {
        "embedding",
        "o2",
        "web_research",
        "data_connectors",
        "llm",
        "openai_agents_sdk",
        "sqlite_writer",
        "document_parser",
    }
    assert all(
        {"name", "configured", "ready", "mode", "last_error", "latency_ms"}
        <= set(item.model_dump())
        for item in providers
    )
    assert payload.overall == "degraded"
    assert "secret" not in serialized.lower()
    assert "base_url" not in serialized
    assert "api_key" not in serialized
    assert "authorization" not in serialized.lower()


def test_embedding_records_ready_and_degraded_observations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedding, "EMBEDDING_ENABLED", True)
    monkeypatch.setattr(embedding, "EMBEDDING_API_URL", "https://embedding.example/v1")
    monkeypatch.setattr(embedding, "EMBEDDING_API_KEY", "secret")
    monkeypatch.setattr(embedding, "EMBEDDING_DIMENSIONS", 1)
    monkeypatch.setattr(embedding, "_client", FakeEmbeddingClient(FakeEmbeddingResponse({"data": [{"embedding": [0.1]}]})))

    assert embedding.embed_text("health") == [0.1]
    assert embedding.embedding_provider_status().last_error is None
    assert embedding.embedding_provider_status().latency_ms is not None

    timeout_request = httpx.Request("POST", "https://embedding.example/v1")
    monkeypatch.setattr(
        embedding,
        "_client",
        FakeEmbeddingClient(httpx.ReadTimeout("contains secret-token", request=timeout_request)),
    )
    assert embedding.embed_text("health") is None
    assert embedding.embedding_provider_status().last_error == "timeout"


def test_embedding_batch_uses_one_request_and_preserves_input_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedding, "EMBEDDING_ENABLED", True)
    monkeypatch.setattr(embedding, "EMBEDDING_API_URL", "https://embedding.example/v1")
    monkeypatch.setattr(embedding, "EMBEDDING_API_KEY", "secret")
    monkeypatch.setattr(embedding, "EMBEDDING_DIMENSIONS", 2)
    client = RecordingEmbeddingClient(
        FakeEmbeddingResponse(
            {
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ]
            }
        )
    )
    monkeypatch.setattr(embedding, "_client", client)

    assert embedding.embed_texts(["first", "", "second"], timeout_seconds=0.35) == [
        [1.0, 0.0],
        None,
        [0.0, 1.0],
    ]
    assert len(client.calls) == 1
    _args, kwargs = client.calls[0]
    assert kwargs["json"] == {"model": embedding.EMBEDDING_MODEL, "input": ["first", "second"]}
    assert kwargs["timeout"] == 0.35


def test_embedding_batch_discards_every_vector_when_response_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(embedding, "EMBEDDING_ENABLED", True)
    monkeypatch.setattr(embedding, "EMBEDDING_API_URL", "https://embedding.example/v1")
    monkeypatch.setattr(embedding, "EMBEDDING_API_KEY", "secret")
    monkeypatch.setattr(embedding, "EMBEDDING_DIMENSIONS", 2)
    client = RecordingEmbeddingClient(
        FakeEmbeddingResponse({"data": [{"index": 0, "embedding": [1.0, 0.0]}]})
    )
    monkeypatch.setattr(embedding, "_client", client)

    assert embedding.embed_texts(["first", "second"]) == [None, None]
    assert len(client.calls) == 1
    assert embedding.embedding_provider_status().last_error == "malformed_response"


def test_embedding_rejects_a_vector_with_the_wrong_declared_dimension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(embedding, "EMBEDDING_ENABLED", True)
    monkeypatch.setattr(embedding, "EMBEDDING_API_URL", "https://embedding.example/v1")
    monkeypatch.setattr(embedding, "EMBEDDING_API_KEY", "secret")
    monkeypatch.setattr(embedding, "EMBEDDING_DIMENSIONS", 2)
    monkeypatch.setattr(
        embedding,
        "_client",
        FakeEmbeddingClient(FakeEmbeddingResponse({"data": [{"embedding": [0.1]}]})),
    )

    assert embedding.embed_text("health") is None
    assert embedding.embedding_provider_status().last_error == "malformed_response"


def test_embedding_malformed_response_is_explicit_and_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedding, "EMBEDDING_ENABLED", True)
    monkeypatch.setattr(embedding, "EMBEDDING_API_URL", "https://embedding.example/v1")
    monkeypatch.setattr(embedding, "EMBEDDING_API_KEY", "secret")
    monkeypatch.setattr(embedding, "_client", FakeEmbeddingClient(FakeEmbeddingResponse({"unexpected": "secret body"})))

    assert embedding.embed_text("health") is None
    assert embedding.embedding_provider_status().last_error == "malformed_response"
    assert "secret body" not in embedding.embedding_provider_status().model_dump_json()


def test_http_data_api_success_carries_real_provenance_and_latency() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "title": "CTR",
                "source_title": "metrics",
                "source_reference": "datasource://metrics/ctr",
                "records": [{"metric": "ctr", "value": 0.42}],
            },
        )

    connector = HTTPDataAPIConnector(
        base_url="https://data.example/api",
        api_key="secret",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = connector.query(_query())

    assert result.metadata["requested_provider"] == "http_data_api"
    assert result.metadata["actual_provider"] == "http_data_api"
    assert result.metadata["mode"] == "real"
    assert result.metadata["fallback_reason"] == ""
    assert float(result.metadata["latency_ms"]) >= 0


def test_http_data_api_auth_and_malformed_failures_are_explicit_without_body_leak() -> None:
    def auth_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="token=server-secret response body", request=request)

    auth_connector = HTTPDataAPIConnector(
        base_url="https://data.example/api",
        api_key="secret",
        http_client=httpx.Client(transport=httpx.MockTransport(auth_handler)),
    )
    with pytest.raises(Exception) as auth_error:
        auth_connector.query(_query())
    assert getattr(auth_error.value, "reason", None) == "auth_error"
    assert "server-secret" not in str(auth_error.value)

    def malformed_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json server-secret", request=request)

    malformed_connector = HTTPDataAPIConnector(
        base_url="https://data.example/api",
        api_key="secret",
        http_client=httpx.Client(transport=httpx.MockTransport(malformed_handler)),
    )
    with pytest.raises(Exception) as malformed_error:
        malformed_connector.query(_query())
    assert getattr(malformed_error.value, "reason", None) == "malformed_response"
    assert "server-secret" not in str(malformed_error.value)


def test_local_metrics_is_an_explicit_labeled_fallback() -> None:
    result = LocalMetricsConnector().query(_query(connector_name="local_metrics"))

    assert result.metadata["requested_provider"] == "local_metrics"
    assert result.metadata["actual_provider"] == "local_metrics"
    assert result.metadata["mode"] == "fallback"
    assert result.metadata["fallback_reason"] == "explicit_local_metrics"


class FakeWebProvider:
    provider_name = "web_fake"
    mode = "real"

    def search(self, query: str, limit: int = 3) -> list[WebSearchResult]:
        return [WebSearchResult(title="Result", url="https://example.test/result", snippet="Summary")]


def test_web_result_provenance_survives_success() -> None:
    result = WebAcquisitionAgent(FakeWebProvider()).acquire(_acquisition_request())

    assert result.metadata["requested_provider"] == "web_research"
    assert result.metadata["actual_provider"] == "web_fake"
    assert result.metadata["mode"] == "real"
    assert float(result.metadata["latency_ms"]) >= 0


def test_research_fallback_provenance_names_requested_and_actual_provider() -> None:
    class FailingO2Agent:
        actor = "o2_research_agent"

        def acquire(self, request: AcquisitionRequest) -> AcquisitionResult:
            raise RuntimeError("auth_required token=secret")

    result = CompositeAcquisitionAgent([FailingO2Agent(), WebAcquisitionAgent(FakeWebProvider())]).acquire(
        _acquisition_request()
    )

    assert result.metadata["requested_provider"] == "o2_research"
    assert result.metadata["actual_provider"] == "web_fake"
    assert result.metadata["mode"] == "real"
    assert result.metadata["fallback_reason"] == "o2_research:auth_error"
    assert "secret" not in json.dumps(result.metadata)


@dataclass
class FakeGrantRepository:
    agent: Agent | None
    grants: list[AgentToolGrant]
    tools: dict[str, ToolDefinition]

    def get_agent(self, agent_id: str) -> Agent | None:
        return self.agent if self.agent and self.agent.id == agent_id else None

    def list_agent_tool_grants(self, agent_id: str) -> list[AgentToolGrant]:
        return [grant for grant in self.grants if grant.agent_id == agent_id]

    def get_tool_definition(self, tool_id: str) -> ToolDefinition | None:
        return self.tools.get(tool_id)


def _provider_user() -> User:
    return User(
        id="usr_provider_test",
        workspace_id="ws_default",
        default_project_id="proj_default",
        name="Provider Test",
        role=UserRole.USER,
        personal_agent_id="agent_provider_test",
    )


def _personal_agent() -> Agent:
    return Agent(
        id="agent_provider_test",
        workspace_id="ws_default",
        name="Personal",
        agent_type="personal",
        description="Personal agent",
        owner_user_id="usr_provider_test",
    )


def test_external_data_query_requires_enabled_personal_agent_tool_grant_before_connector() -> None:
    repository = FakeGrantRepository(agent=_personal_agent(), grants=[], tools={})

    with pytest.raises(Exception) as denied:
        data_source_routes.authorize_data_source_query(
            _provider_user(), "http_data_api", "query", repository=repository
        )

    assert getattr(denied.value, "status_code", None) == 403


def test_data_query_rejects_non_read_only_operation_even_with_grant() -> None:
    tool = ToolDefinition(
        id=DATA_QUERY_TOOL_ID,
        name="data_query",
        description="Read-only data query",
        category="data",
    )
    repository = FakeGrantRepository(
        agent=_personal_agent(),
        grants=[
            AgentToolGrant(
                agent_id="agent_provider_test",
                tool_id=DATA_QUERY_TOOL_ID,
                granted_by="usr_admin",
            )
        ],
        tools={tool.id: tool},
    )

    with pytest.raises(Exception) as denied:
        data_source_routes.authorize_data_source_query(
            _provider_user(), "o2_cli", "delete", repository=repository
        )

    assert getattr(denied.value, "status_code", None) == 400


def test_data_query_allows_read_only_operation_with_enabled_grant() -> None:
    tool = ToolDefinition(
        id=DATA_QUERY_TOOL_ID,
        name="data_query",
        description="Read-only data query",
        category="data",
    )
    repository = FakeGrantRepository(
        agent=_personal_agent(),
        grants=[
            AgentToolGrant(
                agent_id="agent_provider_test",
                tool_id=DATA_QUERY_TOOL_ID,
                granted_by="usr_admin",
            )
        ],
        tools={tool.id: tool},
    )

    data_source_routes.authorize_data_source_query(
        _provider_user(), "o2_cli", "search", repository=repository
    )


def test_llm_timeout_auth_and_malformed_errors_do_not_include_response_body() -> None:
    request = httpx.Request("POST", "https://llm.example/v1/chat/completions")

    def timeout_handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("token=secret", request=request)

    timeout_client = LLMClient(
        "https://llm.example/v1",
        "secret",
        "model",
        http_client=httpx.Client(transport=httpx.MockTransport(timeout_handler)),
    )
    with pytest.raises(LLMRequestError, match="timed out") as timeout_error:
        timeout_client.complete("system", "health")
    assert timeout_error.value.reason == "timeout"
    assert "secret" not in str(timeout_error.value)

    def auth_handler(incoming: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="response token=secret", request=incoming)

    auth_client = LLMClient(
        "https://llm.example/v1",
        "secret",
        "model",
        http_client=httpx.Client(transport=httpx.MockTransport(auth_handler)),
    )
    with pytest.raises(LLMRequestError) as auth_error:
        auth_client.complete("system", "health")
    assert auth_error.value.reason == "auth_error"
    assert "response token" not in str(auth_error.value)

    def malformed_handler(incoming: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "secret body"}, request=incoming)

    malformed_client = LLMClient(
        "https://llm.example/v1",
        "secret",
        "model",
        http_client=httpx.Client(transport=httpx.MockTransport(malformed_handler)),
    )
    with pytest.raises(LLMRequestError) as malformed_error:
        malformed_client.complete("system", "health")
    assert malformed_error.value.reason == "invalid_response"
    assert "secret body" not in str(malformed_error.value)


def test_smoke_parser_is_deterministic_and_selected_failures_aggregate_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provider_smoke, "load_server_env", lambda path=None: None)
    calls: list[str] = []

    def ready() -> ProviderStatus:
        calls.append("embedding")
        return ProviderStatus(name="embedding", configured=True, ready=True, mode="real", latency_ms=1.0)

    def failed() -> ProviderStatus:
        calls.append("llm")
        return ProviderStatus(
            name="llm",
            configured=True,
            ready=False,
            mode="fallback",
            last_error="auth_error",
            latency_ms=2.0,
        )

    monkeypatch.setattr(provider_smoke, "SMOKE_HANDLERS", {"embedding": ready, "llm": failed})

    assert provider_smoke.main(["--embedding", "--llm"]) == 1
    assert calls == ["embedding", "llm"]
    assert provider_smoke.main([]) == 2


def test_llm_smoke_probes_primary_and_fallback_independently(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(provider_smoke, "load_server_env", lambda path=None: None)
    statuses = {
        "primary": ProviderStatus(name="llm:primary", configured=True, ready=True, mode="real", latency_ms=1.0),
        "fallback": ProviderStatus(
            name="llm:fallback",
            configured=True,
            ready=False,
            mode="fallback",
            last_error="timeout",
            latency_ms=2.0,
        ),
    }
    monkeypatch.setenv("AGENTMESH_MODEL_DEFAULT", "primary")
    monkeypatch.setenv("AGENTMESH_LLM_FALLBACK_MODEL_ID", "fallback")
    monkeypatch.setattr(provider_smoke, "smoke_llm_model", lambda model_id: statuses[model_id])
    monkeypatch.setitem(provider_smoke.SMOKE_HANDLERS, "llm", provider_smoke.smoke_llm_models)

    assert provider_smoke.main(["--llm"]) == 1
    output = capsys.readouterr().out
    assert "llm:primary: configured=true ready=true mode=real" in output
    assert "llm:fallback: configured=true ready=false mode=fallback" in output
    assert "shared-secret" not in output
    assert "provider-response-body" not in output


def test_llm_smoke_passes_only_when_both_models_are_real_and_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provider_smoke, "load_server_env", lambda path=None: None)
    monkeypatch.setenv("AGENTMESH_MODEL_DEFAULT", "primary")
    monkeypatch.setenv("AGENTMESH_LLM_FALLBACK_MODEL_ID", "fallback")
    monkeypatch.setattr(
        provider_smoke,
        "smoke_llm_model",
        lambda model_id: ProviderStatus(
            name=f"llm:{model_id}", configured=True, ready=True, mode="real", latency_ms=1.0
        ),
    )
    monkeypatch.setitem(provider_smoke.SMOKE_HANDLERS, "llm", provider_smoke.smoke_llm_models)

    assert provider_smoke.main(["--llm"]) == 0


def test_redaction_does_not_echo_command_or_url_secrets() -> None:
    value = "command failed token=abc Bearer xyz https://user:pass@example.test/run?api_key=hidden"

    redacted = redact_sensitive_text(value)

    assert "abc" not in redacted
    assert "xyz" not in redacted
    assert "pass" not in redacted
    assert "hidden" not in redacted



def test_data_health_is_not_ready_after_current_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    telemetry = ProviderTelemetry()
    telemetry.failure(RuntimeError("provider unavailable"))
    monkeypatch.setattr(datasources, "_data_api_telemetry", telemetry)
    monkeypatch.setenv("AGENTMESH_DATA_API_URL", "https://data.example/api")

    status = datasources.data_api_provider_status()

    assert status.configured is True
    assert status.ready is False
    assert status.last_error == "unavailable"


def test_llm_health_is_not_ready_after_current_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    telemetry = ProviderTelemetry()
    telemetry.failure(LLMRequestError("auth_error", "auth_error"))
    monkeypatch.setattr(llm, "_llm_telemetry", telemetry)
    monkeypatch.setenv("AI_API_URL", "https://llm.example/v1")
    monkeypatch.setenv("AI_API_KEY", "secret")
    monkeypatch.setenv("AI_MODEL", "model")

    status = llm.llm_provider_status()

    assert status.configured is True
    assert status.ready is False
    assert status.last_error == "auth_error"


def test_o2_health_is_not_ready_after_current_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class AvailableRunner:
        def available(self) -> bool:
            return True

    telemetry = ProviderTelemetry()
    telemetry.failure(RuntimeError("provider unavailable"))
    monkeypatch.setattr(o2, "_o2_research_telemetry", telemetry)
    monkeypatch.setenv("AGENTMESH_O2_RESEARCH_ENABLED", "true")

    status = o2.o2_research_provider_status(AvailableRunner())

    assert status.configured is True
    assert status.ready is False
    assert status.last_error == "unavailable"
