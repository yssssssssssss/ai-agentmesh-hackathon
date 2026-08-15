from __future__ import annotations

import json

import httpx
import pytest

import agentmesh.web_research as web_research
from agentmesh.acquisition import AcquisitionRequest
from agentmesh.models import Intent
from agentmesh.seed import PROJECT, WORKSPACE
from agentmesh.web_research import (
    CommandWebSearchProvider,
    MockWebSearchProvider,
    TavilyWebSearchProvider,
    WebAcquisitionAgent,
    WebResearchError,
    provider_from_env,
)


def test_mock_web_search_provider_returns_contract() -> None:
    results = MockWebSearchProvider().search("618 家电会场")

    assert results[0].title == "Mock web research result"
    assert results[0].url.startswith("https://")


def test_missing_command_provider_fails_explicitly() -> None:
    provider = CommandWebSearchProvider("agentmesh-command-that-does-not-exist")

    with pytest.raises(RuntimeError, match="Web search command not found"):
        provider.search("query")


def test_command_provider_uses_template_and_results_payload(tmp_path) -> None:
    command = tmp_path / "fake_search.py"
    command.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json",
                "import sys",
                "print(json.dumps({'results': [{'name': sys.argv[1], 'href': 'https://example.invalid/a', 'summary': sys.argv[2]}]}))",
            ]
        ),
        encoding="utf-8",
    )
    command.chmod(0o755)

    provider = CommandWebSearchProvider(str(command), command_template=f"{command} {{query}} {{limit}}")

    results = provider.search("618 家电", limit=2)

    assert results[0].title == "618 家电"
    assert results[0].url == "https://example.invalid/a"
    assert results[0].snippet == "2"


def test_provider_from_env_supports_provider_specific_template(monkeypatch) -> None:
    monkeypatch.setenv("AGENTMESH_WEB_PROVIDER", "opencli")
    monkeypatch.setenv("AGENTMESH_OPENCLI_COMMAND", "opencli")
    monkeypatch.setenv("AGENTMESH_OPENCLI_COMMAND_TEMPLATE", "opencli search {query} --count {limit} --json")

    provider = provider_from_env()

    assert isinstance(provider, CommandWebSearchProvider)
    assert provider.command_template == "opencli search {query} --count {limit} --json"


def test_web_acquisition_agent_converts_results_to_evidence() -> None:
    agent = WebAcquisitionAgent(MockWebSearchProvider())

    result = agent.acquire(
        AcquisitionRequest(
            query="618 家电会场",
            intent=Intent.REQUEST_EXTERNAL_RESEARCH,
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
            user_id="usr",
            task_id="task_web",
            request_post_id="bb_web",
        )
    )

    assert result.actor == "web_research_agent"
    assert result.title == "Web 检索结果"
    assert result.sources[0].source_type == "web_page"
    assert "Mock result" in result.content


def test_tavily_provider_sends_safe_request_and_maps_results() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["payload"] = json.loads(request.read())
        return httpx.Response(
            200,
            request=request,
            json={
                "results": [
                    {
                        "title": "Agent systems",
                        "url": "https://example.test/agents",
                        "content": "Grounded search result",
                        "score": 0.9,
                    }
                ]
            },
        )

    provider = TavilyWebSearchProvider(
        "https://api.tavily.com/search",
        "test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    results = provider.search("agent systems", limit=3)

    assert captured["url"] == "https://api.tavily.com/search"
    assert captured["authorization"] == "Bearer test-key"
    assert captured["payload"] == {
        "query": "agent systems",
        "search_depth": "basic",
        "max_results": 3,
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
    }
    assert results[0].title == "Agent systems"
    assert results[0].url == "https://example.test/agents"
    assert results[0].snippet == "Grounded search result"


@pytest.mark.parametrize(
    ("status_code", "reason"),
    [(401, "auth_error"), (403, "auth_error"), (429, "rate_limited"), (432, "rate_limited"), (500, "provider_error")],
)
def test_tavily_provider_classifies_http_errors_without_leaking_body(status_code: int, reason: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, request=request, text="secret provider response body")

    provider = TavilyWebSearchProvider(
        "https://api.tavily.com/search",
        "secret-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(WebResearchError) as captured:
        provider.search("query")

    assert captured.value.reason == reason
    assert "secret-key" not in str(captured.value)
    assert "secret provider response body" not in str(captured.value)


def test_tavily_provider_classifies_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret timeout body", request=request)

    provider = TavilyWebSearchProvider(
        "https://api.tavily.com/search",
        "secret-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(WebResearchError) as captured:
        provider.search("query")

    assert captured.value.reason == "timeout"
    assert "secret" not in str(captured.value)


def test_tavily_provider_rejects_malformed_results_without_leaking_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, json={"results": "secret malformed payload"})

    provider = TavilyWebSearchProvider(
        "https://api.tavily.com/search",
        "secret-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(WebResearchError) as captured:
        provider.search("query")

    assert captured.value.reason == "malformed_response"
    assert "secret" not in str(captured.value)


def test_provider_from_env_selects_tavily_with_complete_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTMESH_WEB_PROVIDER", "tavily")
    monkeypatch.setenv("AGENTMESH_TAVILY_API_URL", "https://api.tavily.com/search")
    monkeypatch.setenv("AGENTMESH_TAVILY_API_KEY", "test-key")
    monkeypatch.setenv("AGENTMESH_TAVILY_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("AGENTMESH_TAVILY_SEARCH_DEPTH", "fast")

    provider = provider_from_env()

    assert isinstance(provider, TavilyWebSearchProvider)
    assert provider.api_url == "https://api.tavily.com/search"
    assert provider.search_depth == "basic"


def test_provider_from_env_rejects_incomplete_tavily_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTMESH_WEB_PROVIDER", "tavily")
    monkeypatch.setenv("AGENTMESH_TAVILY_API_URL", "https://api.tavily.com/search")
    monkeypatch.delenv("AGENTMESH_TAVILY_API_KEY", raising=False)

    assert provider_from_env() is None


def test_tavily_health_degrades_after_observed_auth_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    telemetry = web_research.ProviderTelemetry()
    monkeypatch.setattr(web_research, "_tavily_telemetry", telemetry)
    monkeypatch.setenv("AGENTMESH_WEB_PROVIDER", "tavily")
    monkeypatch.setenv("AGENTMESH_TAVILY_API_URL", "https://api.tavily.com/search")
    monkeypatch.setenv("AGENTMESH_TAVILY_API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, request=request)

    provider = TavilyWebSearchProvider(
        "https://api.tavily.com/search",
        "test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(WebResearchError):
        provider.search("query")

    status = web_research.web_research_provider_status()
    assert status.configured is True
    assert status.ready is False
    assert status.last_error == "auth_error"
