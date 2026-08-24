from __future__ import annotations

import hashlib
import json

import httpx
import pytest

import agentmesh.web_research as web_research
from agentmesh.acquisition import AcquisitionQuery, AcquisitionRequest, ProviderCallRecord
from agentmesh.models import Intent
from agentmesh.research_orchestration.artifacts import contains_sensitive_artifact_content
from agentmesh.seed import PROJECT, WORKSPACE
from agentmesh.web_research import (
    CommandWebSearchProvider,
    FetchedWebContent,
    FirecrawlContentFetcher,
    MockWebSearchProvider,
    TavilyFirecrawlWebSearchProvider,
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


def test_web_acquisition_agent_redacts_sensitive_provider_content_before_artifact_sealing() -> None:
    class SensitiveProvider:
        provider_name = "tavily"
        mode = "real"

        def search(self, query: str, limit: int = 3) -> list[web_research.WebSearchResult]:
            del query, limit
            return [
                web_research.WebSearchResult(
                    title="Contact demo@example.test",
                    url="https://example.test/agents?X-Amz-Signature=opaque-signed-secret&code=oauth-secret#private",
                    snippet=(
                        "Call 19601575478; token=synthetic-value; "
                        "local cache /Users/example/private-result."
                    ),
                )
            ]

    result = WebAcquisitionAgent(SensitiveProvider()).acquire(
        AcquisitionRequest(
            query="agent systems",
            intent=Intent.REQUEST_EXTERNAL_RESEARCH,
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
            user_id="usr",
            task_id="task_sensitive_web",
            request_post_id="bb_sensitive_web",
        )
    )

    serialized = result.model_dump_json()
    assert result.metadata["sensitive_content_redacted"] == "true"
    assert "[REDACTED_EMAIL]" in serialized
    assert "[REDACTED_PHONE]" in serialized
    assert "[REDACTED_CREDENTIAL]" in serialized
    assert "[REDACTED_LOCAL_PATH]" in serialized
    assert "demo@example.test" not in serialized
    assert "19601575478" not in serialized
    assert "synthetic-value" not in serialized
    assert "opaque-signed-secret" not in serialized
    assert "oauth-secret" not in serialized
    assert "/Users/example/private-result" not in serialized
    assert result.sources[0].reference == "https://example.test/agents"
    assert contains_sensitive_artifact_content(serialized) is False


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


def test_firecrawl_fetcher_sends_safe_request_and_returns_markdown() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["payload"] = json.loads(request.read())
        return httpx.Response(
            200,
            request=request,
            json={
                "success": True,
                "data": {
                    "markdown": "# Agent systems\n\nGrounded page content",
                    "metadata": {"sourceURL": "https://example.test/agents"},
                },
            },
        )

    fetcher = FirecrawlContentFetcher(
        "https://api.firecrawl.dev/v2/scrape",
        "test-firecrawl-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    content = fetcher.fetch("https://example.test/agents", query="agent systems")

    assert captured["url"] == "https://api.firecrawl.dev/v2/scrape"
    assert captured["authorization"] == "Bearer test-firecrawl-key"
    assert captured["payload"] == {
        "url": "https://example.test/agents",
        "formats": ["markdown"],
        "onlyMainContent": True,
        "timeout": 60000,
    }
    assert content.excerpt == "# Agent systems\n\nGrounded page content"
    assert len(content.content_hash) == 64
    assert content.truncated is False
    assert content.provider_call.provider == "firecrawl"
    assert content.provider_call.operation == "scrape"
    assert content.provider_call.status == "success"


def test_firecrawl_fetcher_selects_relevant_body_instead_of_leading_navigation() -> None:
    markdown = "\n\n".join(
        [
            "登录 注册 首页 导航",
            "关注作者 举报 搜索关闭",
            "## 产品概览\n这是一个宽泛的产品介绍。" + "背景" * 150,
            "## 任务恢复\nTRAE Work 支持 checkpoint、失败重试和历史任务恢复。" + "恢复细节" * 80,
            "## 协作能力\nWorkBuddy 提供团队空间、角色权限和审批记录。" + "协作细节" * 80,
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, json={"success": True, "data": {"markdown": markdown}})

    fetcher = FirecrawlContentFetcher(
        "https://api.firecrawl.dev/v2/scrape",
        "test-firecrawl-key",
        max_content_chars=500,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    content = fetcher.fetch(
        "https://example.test/agents",
        query="TRAE Work 任务恢复 checkpoint 团队协作 权限",
    )

    assert "任务恢复" in content.excerpt
    assert "checkpoint" in content.excerpt
    assert "登录 注册 首页 导航" not in content.excerpt
    assert content.truncated is True
    assert content.risk_flags == ["truncated"]


def test_firecrawl_fetcher_rejects_private_target_without_calling_provider() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected request: {request.url}")

    fetcher = FirecrawlContentFetcher(
        "https://api.firecrawl.dev/v2/scrape",
        "test-firecrawl-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(WebResearchError) as captured:
        fetcher.fetch("http://127.0.0.1/admin", query="agent systems")

    assert captured.value.reason == "invalid_url"


@pytest.mark.parametrize(
    ("status_code", "reason"),
    [(401, "auth_error"), (402, "quota_exceeded"), (408, "timeout"), (429, "rate_limited"), (500, "provider_error")],
)
def test_firecrawl_fetcher_classifies_http_errors_without_leaking_body(status_code: int, reason: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, request=request, text="secret provider response body")

    fetcher = FirecrawlContentFetcher(
        "https://api.firecrawl.dev/v2/scrape",
        "secret-firecrawl-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(WebResearchError) as captured:
        fetcher.fetch("https://example.test/agents", query="agent systems")

    assert captured.value.reason == reason
    assert "secret-firecrawl-key" not in str(captured.value)
    assert "secret provider response body" not in str(captured.value)


def test_tavily_firecrawl_provider_enriches_search_results() -> None:
    search_provider = MockWebSearchProvider()

    class StubFetcher:
        provider_name = "firecrawl"

        def fetch(self, url: str, *, query: str) -> FetchedWebContent:
            assert url == "https://example.invalid/research"
            assert query == "agent systems"
            return FetchedWebContent(
                excerpt="Full page evidence",
                retrieved_at=web_research.now_utc(),
                content_hash=hashlib.sha256(b"Full page evidence").hexdigest(),
                provider_call=ProviderCallRecord(
                    provider="firecrawl",
                    operation="scrape",
                    request_hash="2" * 64,
                    status="success",
                    latency_ms=1,
                    result_count=1,
                ),
            )

    provider = TavilyFirecrawlWebSearchProvider(search_provider, StubFetcher())

    results = provider.search("agent systems")

    assert results[0].snippet == "Full page evidence"
    assert results[0].content_provider == "firecrawl"
    assert results[0].enrichment_error is None

    acquisition = WebAcquisitionAgent(provider).acquire(
        AcquisitionRequest(
            query="agent systems",
            intent=Intent.REQUEST_EXTERNAL_RESEARCH,
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
            user_id="usr",
            task_id="task_web",
            request_post_id="bb_web",
        )
    )
    assert acquisition.metadata["requested_provider"] == "web_research"
    assert acquisition.metadata["actual_provider"] == "tavily+firecrawl"
    assert acquisition.metadata["scraped_source_count"] == "1"
    assert len(acquisition.source_evidence) == 1
    assert acquisition.source_evidence[0].source_id == acquisition.sources[0].id
    assert acquisition.source_evidence[0].content_provider == "firecrawl"
    assert acquisition.source_evidence[0].question_ids == []
    assert len(acquisition.provider_calls) == 2


def test_tavily_firecrawl_batch_deduplicates_and_preserves_question_ids() -> None:
    class SearchProvider:
        provider_name = "tavily"
        mode = "real"

        def search(self, query: str, limit: int = 3) -> list[web_research.WebSearchResult]:
            del limit
            if "恢复" in query:
                return [
                    web_research.WebSearchResult(
                        title="Product recovery docs",
                        url="https://product.example/docs/recovery#overview",
                        snippet="Recovery overview",
                    ),
                    web_research.WebSearchResult(
                        title="Secondary comparison",
                        url="https://www.csdn.net/article/1",
                        snippet="Comparison",
                    ),
                ]
            return [
                web_research.WebSearchResult(
                    title="Product collaboration docs",
                    url="https://product.example/docs/recovery",
                    snippet="Collaboration overview with more detail",
                )
            ]

    class StubFetcher:
        provider_name = "firecrawl"

        def fetch(self, url: str, *, query: str) -> FetchedWebContent:
            excerpt = f"Evidence for {url}: {query}"
            return FetchedWebContent(
                excerpt=excerpt,
                retrieved_at=web_research.now_utc(),
                content_hash=hashlib.sha256(excerpt.encode()).hexdigest(),
                provider_call=ProviderCallRecord(
                    provider="firecrawl",
                    operation="scrape",
                    request_hash=hashlib.sha256(url.encode()).hexdigest(),
                    status="success",
                    latency_ms=1,
                    result_count=1,
                ),
            )

    provider = TavilyFirecrawlWebSearchProvider(SearchProvider(), StubFetcher(), scrape_limit=3)
    batch = provider.search_batch(
        [
            AcquisitionQuery(query="产品 任务恢复", question_ids=["q_recovery"]),
            AcquisitionQuery(query="产品 协作能力", question_ids=["q_collaboration"]),
        ],
        result_limit=3,
    )

    assert len(batch.results) == 2
    assert batch.results[0].url == "https://product.example/docs/recovery"
    assert batch.results[0].question_ids == ["q_recovery", "q_collaboration"]
    assert len(batch.provider_calls) == 5
    assert [call.operation for call in batch.provider_calls] == ["search", "search", "search", "scrape", "scrape"]
    assert len({call.request_hash for call in batch.provider_calls if call.operation == "search"}) == 3


def test_tavily_firecrawl_provider_preserves_search_snippet_when_scrape_fails() -> None:
    search_provider = MockWebSearchProvider()

    class FailingFetcher:
        provider_name = "firecrawl"

        def fetch(self, url: str, *, query: str) -> FetchedWebContent:
            raise WebResearchError("rate_limited", "Firecrawl rate limit was reached")

    provider = TavilyFirecrawlWebSearchProvider(search_provider, FailingFetcher())

    results = provider.search("agent systems")

    assert results[0].snippet == "Mock result for: agent systems"
    assert results[0].content_provider is None
    assert results[0].enrichment_error == "rate_limited"

    acquisition = WebAcquisitionAgent(provider).acquire(
        AcquisitionRequest(
            query="agent systems",
            intent=Intent.REQUEST_EXTERNAL_RESEARCH,
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
            user_id="usr",
            task_id="task_web",
            request_post_id="bb_web",
        )
    )
    assert acquisition.metadata["actual_provider"] == "tavily"
    assert acquisition.metadata["content_provider"] == "firecrawl"
    assert acquisition.metadata["scraped_source_count"] == "0"
    assert acquisition.metadata["fallback_reason"] == "firecrawl:rate_limited"


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
    monkeypatch.delenv("AGENTMESH_FIRECRAWL_ENABLED", raising=False)
    monkeypatch.setenv("AGENTMESH_TAVILY_API_URL", "https://api.tavily.com/search")
    monkeypatch.setenv("AGENTMESH_TAVILY_API_KEY", "test-key")
    monkeypatch.setenv("AGENTMESH_TAVILY_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("AGENTMESH_TAVILY_SEARCH_DEPTH", "fast")

    provider = provider_from_env()

    assert isinstance(provider, TavilyWebSearchProvider)
    assert provider.api_url == "https://api.tavily.com/search"
    assert provider.search_depth == "basic"


def test_provider_from_env_wraps_tavily_with_firecrawl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTMESH_WEB_PROVIDER", "tavily")
    monkeypatch.setenv("AGENTMESH_TAVILY_API_URL", "https://api.tavily.com/search")
    monkeypatch.setenv("AGENTMESH_TAVILY_API_KEY", "test-tavily-key")
    monkeypatch.setenv("AGENTMESH_FIRECRAWL_ENABLED", "true")
    monkeypatch.setenv("AGENTMESH_FIRECRAWL_API_URL", "https://api.firecrawl.dev/v2/scrape")
    monkeypatch.setenv("AGENTMESH_FIRECRAWL_API_KEY", "test-firecrawl-key")
    monkeypatch.setenv("AGENTMESH_FIRECRAWL_MAX_PAGES", "2")

    provider = provider_from_env()

    assert isinstance(provider, TavilyFirecrawlWebSearchProvider)
    assert provider.scrape_limit == 2
    assert isinstance(provider.search_provider, TavilyWebSearchProvider)
    assert isinstance(provider.content_fetcher, FirecrawlContentFetcher)


def test_provider_from_env_requires_key_for_firecrawl_cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTMESH_WEB_PROVIDER", "tavily")
    monkeypatch.setenv("AGENTMESH_TAVILY_API_URL", "https://api.tavily.com/search")
    monkeypatch.setenv("AGENTMESH_TAVILY_API_KEY", "test-tavily-key")
    monkeypatch.setenv("AGENTMESH_FIRECRAWL_ENABLED", "true")
    monkeypatch.setenv("AGENTMESH_FIRECRAWL_API_URL", "https://api.firecrawl.dev/v2/scrape")
    monkeypatch.delenv("AGENTMESH_FIRECRAWL_API_KEY", raising=False)

    assert provider_from_env() is None
    status = web_research.web_research_provider_status()
    assert status.configured is False
    assert status.ready is False
    assert status.last_error == "not_configured"


def test_provider_from_env_rejects_incomplete_tavily_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTMESH_WEB_PROVIDER", "tavily")
    monkeypatch.delenv("AGENTMESH_FIRECRAWL_ENABLED", raising=False)
    monkeypatch.setenv("AGENTMESH_TAVILY_API_URL", "https://api.tavily.com/search")
    monkeypatch.delenv("AGENTMESH_TAVILY_API_KEY", raising=False)

    assert provider_from_env() is None


def test_tavily_health_degrades_after_observed_auth_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    telemetry = web_research.ProviderTelemetry()
    monkeypatch.setattr(web_research, "_tavily_telemetry", telemetry)
    monkeypatch.delenv("AGENTMESH_FIRECRAWL_ENABLED", raising=False)
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
