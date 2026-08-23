from __future__ import annotations

import ipaddress
import json
import os
import shlex
import shutil
import subprocess
from time import monotonic
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field

from agentmesh.acquisition import AcquisitionAgent, AcquisitionRequest, AcquisitionResult
from agentmesh.models import Source
from agentmesh.provider_status import (
    ProviderStatus,
    ProviderTelemetry,
    build_provider_status,
    provider_error_code,
    provider_metadata,
)
from agentmesh.tool_runtime.guardrails import redact_sensitive_text

_tavily_telemetry = ProviderTelemetry()
_firecrawl_telemetry = ProviderTelemetry()


class WebSearchResult(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=1000)
    snippet: str = Field(default="", max_length=2000)
    content_provider: str | None = Field(default=None, max_length=120)
    enrichment_error: str | None = Field(default=None, max_length=80)


class WebSearchProvider(Protocol):
    def search(self, query: str, limit: int = 3) -> list[WebSearchResult]: ...


class WebContentFetcher(Protocol):
    provider_name: str

    def fetch(self, url: str) -> str: ...


class WebResearchError(RuntimeError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


class CommandWebSearchProvider:
    provider_name = "command_web"
    mode = "real"

    def __init__(self, command: str, command_template: str | None = None, provider_name: str | None = None):
        self.command = command
        self.command_template = command_template
        self.provider_name = provider_name or self.provider_name

    def search(self, query: str, limit: int = 3) -> list[WebSearchResult]:
        argv = self._argv(query, limit)
        executable = shutil.which(argv[0])
        if executable is None:
            raise WebResearchError("unavailable", f"Web search command not found: {argv[0]}")
        try:
            completed = subprocess.run(
                [executable, *argv[1:]],
                capture_output=True,
                check=True,
                text=True,
                timeout=45,
            )
            payload = json.loads(completed.stdout or "[]")
            return [self._result_from_item(item) for item in self._items_from_payload(payload)[:limit]]
        except subprocess.TimeoutExpired as error:
            raise WebResearchError("timeout", "Web search provider timed out") from error
        except subprocess.CalledProcessError as error:
            raise WebResearchError("provider_error", "Web search provider command failed") from error
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise WebResearchError("malformed_response", "Web search provider returned malformed JSON") from error

    def _argv(self, query: str, limit: int) -> list[str]:
        if not self.command_template:
            return [self.command, query, "--limit", str(limit), "--json"]
        rendered = self.command_template.format(query=shlex.quote(query), limit=str(limit))
        return shlex.split(rendered)

    @staticmethod
    def _items_from_payload(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if CommandWebSearchProvider._has_url(item)]
        if not isinstance(payload, dict):
            return []
        for key in ("items", "results", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if CommandWebSearchProvider._has_url(item)]
        return []

    @staticmethod
    def _has_url(item: object) -> bool:
        return isinstance(item, dict) and bool(item.get("url") or item.get("href") or item.get("link"))

    @staticmethod
    def _result_from_item(item: dict[str, Any]) -> WebSearchResult:
        url = str(item.get("url") or item.get("href") or item.get("link") or "")
        return WebSearchResult(
            title=str(item.get("title") or item.get("name") or url),
            url=url,
            snippet=str(item.get("snippet") or item.get("content") or item.get("summary") or ""),
        )


class TavilyWebSearchProvider:
    provider_name = "tavily"
    mode = "real"

    def __init__(
        self,
        api_url: str,
        api_key: str,
        timeout_seconds: float = 20.0,
        http_client: httpx.Client | None = None,
    ):
        self.api_url = api_url
        self.api_key = api_key
        self.search_depth = "basic"
        self.http_client = http_client or httpx.Client(timeout=max(0.1, timeout_seconds))

    def search(self, query: str, limit: int = 3) -> list[WebSearchResult]:
        started = monotonic()
        try:
            response = self.http_client.post(
                self.api_url,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "query": query,
                    "search_depth": self.search_depth,
                    "max_results": max(0, min(limit, 20)),
                    "include_answer": False,
                    "include_raw_content": False,
                    "include_images": False,
                },
            )
        except httpx.TimeoutException as error:
            self._fail("timeout", "Tavily search timed out", error, started)
        except httpx.RequestError as error:
            self._fail("provider_error", "Tavily search request failed", error, started)

        if response.status_code in {401, 403}:
            self._fail("auth_error", "Tavily authentication failed", None, started)
        if response.status_code in {429, 432}:
            self._fail("rate_limited", "Tavily search limit was reached", None, started)
        if response.status_code >= 400:
            self._fail("provider_error", f"Tavily search returned HTTP {response.status_code}", None, started)

        try:
            payload = response.json()
            raw_results = payload["results"]
            if not isinstance(raw_results, list):
                raise TypeError("results must be a list")
            results = [
                WebSearchResult(
                    title=str(item["title"]),
                    url=str(item["url"]),
                    snippet=str(item.get("content") or ""),
                )
                for item in raw_results
                if isinstance(item, dict)
            ]
        except (KeyError, TypeError, ValueError) as error:
            self._fail("malformed_response", "Tavily search returned malformed JSON", error, started)

        _tavily_telemetry.success((monotonic() - started) * 1000)
        return results

    @staticmethod
    def _fail(
        reason: str,
        message: str,
        error: BaseException | None,
        started: float,
    ) -> None:
        wrapped = WebResearchError(reason, message)
        _tavily_telemetry.failure(wrapped, (monotonic() - started) * 1000)
        raise wrapped from error


class FirecrawlContentFetcher:
    provider_name = "firecrawl"

    def __init__(
        self,
        api_url: str,
        api_key: str,
        timeout_seconds: float = 60.0,
        max_content_chars: int = 1200,
        http_client: httpx.Client | None = None,
    ):
        self.api_url = api_url
        self.api_key = api_key
        self.max_content_chars = max(200, min(max_content_chars, 2000))
        self.http_client = http_client or httpx.Client(timeout=max(0.1, timeout_seconds))

    def fetch(self, url: str) -> str:
        self._validate_public_url(url)
        started = monotonic()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = self.http_client.post(
                self.api_url,
                headers=headers,
                json={
                    "url": url,
                    "formats": ["markdown"],
                    "onlyMainContent": True,
                },
            )
        except httpx.TimeoutException as error:
            self._fail("timeout", "Firecrawl scrape timed out", error, started)
        except httpx.RequestError as error:
            self._fail("provider_error", "Firecrawl scrape request failed", error, started)

        if response.status_code in {401, 403}:
            self._fail("auth_error", "Firecrawl authentication failed", None, started)
        if response.status_code == 402:
            self._fail("quota_exceeded", "Firecrawl credits are exhausted", None, started)
        if response.status_code == 408:
            self._fail("timeout", "Firecrawl scrape timed out", None, started)
        if response.status_code == 429:
            self._fail("rate_limited", "Firecrawl rate limit was reached", None, started)
        if response.status_code >= 400:
            self._fail("provider_error", f"Firecrawl scrape returned HTTP {response.status_code}", None, started)

        try:
            payload = response.json()
            data = payload["data"]
            markdown = data["markdown"]
            if payload.get("success") is not True or not isinstance(data, dict) or not isinstance(markdown, str):
                raise TypeError("invalid Firecrawl response")
            normalized = markdown.strip()
            if not normalized:
                raise ValueError("empty Firecrawl content")
        except (KeyError, TypeError, ValueError) as error:
            self._fail("malformed_response", "Firecrawl returned malformed JSON", error, started)

        _firecrawl_telemetry.success((monotonic() - started) * 1000)
        if len(normalized) <= self.max_content_chars:
            return normalized
        return normalized[: self.max_content_chars - 1].rstrip() + "…"

    @staticmethod
    def _validate_public_url(url: str) -> None:
        try:
            parsed = urlsplit(url)
            hostname = parsed.hostname or ""
        except ValueError:
            raise WebResearchError("invalid_url", "Firecrawl target URL is not a public HTTP URL") from None
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None
        if (
            parsed.scheme not in {"http", "https"}
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or hostname.lower().rstrip(".") == "localhost"
            or (address is not None and not address.is_global)
        ):
            raise WebResearchError("invalid_url", "Firecrawl target URL is not a public HTTP URL")

    @staticmethod
    def _fail(
        reason: str,
        message: str,
        error: BaseException | None,
        started: float,
    ) -> None:
        wrapped = WebResearchError(reason, message)
        _firecrawl_telemetry.failure(wrapped, (monotonic() - started) * 1000)
        raise wrapped from error


class TavilyFirecrawlWebSearchProvider:
    provider_name = "tavily_firecrawl"
    search_provider_name = "tavily"
    content_provider_name = "firecrawl"
    mode = "real"

    def __init__(
        self,
        search_provider: WebSearchProvider,
        content_fetcher: WebContentFetcher,
        scrape_limit: int = 3,
    ):
        self.search_provider = search_provider
        self.content_fetcher = content_fetcher
        self.scrape_limit = max(1, min(scrape_limit, 10))

    def search(self, query: str, limit: int = 3) -> list[WebSearchResult]:
        results = self.search_provider.search(query, limit)
        enriched: list[WebSearchResult] = []
        for index, result in enumerate(results):
            if index >= self.scrape_limit:
                enriched.append(result)
                continue
            try:
                content = self.content_fetcher.fetch(result.url)
            except WebResearchError as error:
                enriched.append(result.model_copy(update={"enrichment_error": error.reason}))
                continue
            enriched.append(
                result.model_copy(
                    update={
                        "snippet": content,
                        "content_provider": self.content_fetcher.provider_name,
                    }
                )
            )
        return enriched


class MockWebSearchProvider:
    provider_name = "mock_web"
    mode = "fallback"

    def search(self, query: str, limit: int = 3) -> list[WebSearchResult]:
        return [
            WebSearchResult(
                title="Mock web research result",
                url="https://example.invalid/research",
                snippet=f"Mock result for: {query}",
            )
        ][:limit]


class WebAcquisitionAgent(AcquisitionAgent):
    actor = "web_research_agent"

    def __init__(self, provider: WebSearchProvider):
        self.provider = provider

    def acquire(self, request: AcquisitionRequest) -> AcquisitionResult:
        started = monotonic()
        results = self.provider.search(request.query)
        latency_ms = (monotonic() - started) * 1000
        provider_name = getattr(self.provider, "provider_name", "web_research")
        mode = getattr(self.provider, "mode", "real")
        content_provider = getattr(self.provider, "content_provider_name", None)
        scraped_count = sum(item.content_provider == content_provider for item in results) if content_provider else 0
        enrichment_errors = sorted({item.enrichment_error for item in results if item.enrichment_error})
        actual_provider = provider_name
        fallback_reason: str | None = "explicit_mock_provider" if mode == "fallback" else None
        if isinstance(self.provider, TavilyFirecrawlWebSearchProvider):
            actual_provider = "tavily+firecrawl" if scraped_count else self.provider.search_provider_name
            if enrichment_errors:
                fallback_reason = "firecrawl:" + ",".join(enrichment_errors)
        metadata = provider_metadata(
            requested_provider="web_research",
            actual_provider=actual_provider,
            mode=mode,
            latency_ms=latency_ms,
            fallback_reason=fallback_reason,
        )
        if isinstance(self.provider, TavilyFirecrawlWebSearchProvider):
            metadata.update(
                {
                    "search_provider": self.provider.search_provider_name,
                    "content_provider": self.provider.content_provider_name,
                    "scraped_source_count": str(scraped_count),
                }
            )
        safe_results: list[WebSearchResult] = []
        sensitive_content_redacted = False
        for item in results:
            title = redact_sensitive_text(item.title)
            url = redact_sensitive_text(item.url)
            snippet = redact_sensitive_text(item.snippet)
            sensitive_content_redacted = sensitive_content_redacted or (
                title != item.title or url != item.url or snippet != item.snippet
            )
            safe_results.append(item.model_copy(update={"title": title, "url": url, "snippet": snippet}))
        results = safe_results
        if sensitive_content_redacted:
            metadata["sensitive_content_redacted"] = "true"
        if not results:
            return AcquisitionResult(
                actor=self.actor,
                title="未找到 Web 资料",
                content="Web 检索没有返回可用结果。",
                sources=[],
                metadata=metadata,
            )
        content = "\n".join(f"{item.title}: {item.snippet}" for item in results)
        content_truncated = len(content) > 4000
        if content_truncated:
            content = content[:3999].rstrip() + "…"
            metadata["content_truncated"] = "true"
        return AcquisitionResult(
            actor=self.actor,
            title="Web 检索结果",
            content=content,
            sources=[Source(title=item.title, source_type="web_page", reference=item.url) for item in results],
            metadata=metadata,
        )


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    try:
        return max(0.1, float(os.getenv(name, str(default))))
    except ValueError:
        return default


def _int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def _firecrawl_configuration() -> tuple[str, str] | None:
    api_url = os.getenv("AGENTMESH_FIRECRAWL_API_URL", "https://api.firecrawl.dev/v2/scrape").strip()
    api_key = os.getenv("AGENTMESH_FIRECRAWL_API_KEY", "").strip()
    if not api_url:
        return None
    hostname = (urlsplit(api_url).hostname or "").lower()
    if (hostname == "api.firecrawl.dev" or hostname.endswith(".firecrawl.dev")) and not api_key:
        return None
    return api_url, api_key


def provider_from_env() -> WebSearchProvider | None:
    provider = os.getenv("AGENTMESH_WEB_PROVIDER", "").strip().lower()
    if provider == "mock":
        return MockWebSearchProvider()
    if provider == "tavily":
        api_url = os.getenv("AGENTMESH_TAVILY_API_URL", "").strip()
        api_key = os.getenv("AGENTMESH_TAVILY_API_KEY", "").strip()
        if not api_url or not api_key:
            return None
        tavily = TavilyWebSearchProvider(
            api_url,
            api_key,
            _float_env("AGENTMESH_TAVILY_TIMEOUT_SECONDS", 20.0),
        )
        if not _env_flag("AGENTMESH_FIRECRAWL_ENABLED"):
            return tavily
        firecrawl_config = _firecrawl_configuration()
        if firecrawl_config is None:
            return None
        firecrawl_url, firecrawl_key = firecrawl_config
        return TavilyFirecrawlWebSearchProvider(
            tavily,
            FirecrawlContentFetcher(
                firecrawl_url,
                firecrawl_key,
                _float_env("AGENTMESH_FIRECRAWL_TIMEOUT_SECONDS", 60.0),
                _int_env("AGENTMESH_FIRECRAWL_MAX_CONTENT_CHARS", 1200, minimum=200, maximum=2000),
            ),
            scrape_limit=_int_env("AGENTMESH_FIRECRAWL_MAX_PAGES", 3, minimum=1, maximum=10),
        )
    if provider == "opencli":
        return CommandWebSearchProvider(
            os.getenv("AGENTMESH_OPENCLI_COMMAND", "opencli"),
            os.getenv("AGENTMESH_OPENCLI_COMMAND_TEMPLATE") or os.getenv("AGENTMESH_WEB_COMMAND_TEMPLATE"),
            provider_name="opencli",
        )
    if provider == "agent_browser":
        return CommandWebSearchProvider(
            os.getenv("AGENTMESH_AGENT_BROWSER_COMMAND", "agent-browser"),
            os.getenv("AGENTMESH_AGENT_BROWSER_COMMAND_TEMPLATE") or os.getenv("AGENTMESH_WEB_COMMAND_TEMPLATE"),
            provider_name="agent_browser",
        )
    return None


def web_research_provider_status() -> ProviderStatus:
    configured_provider = os.getenv("AGENTMESH_WEB_PROVIDER", "").strip().lower()
    if not configured_provider:
        return build_provider_status(
            name="web_research", configured=False, ready=False, error="not_configured"
        )
    if configured_provider == "tavily":
        tavily_configured = bool(
            os.getenv("AGENTMESH_TAVILY_API_URL", "").strip()
            and os.getenv("AGENTMESH_TAVILY_API_KEY", "").strip()
        )
        if not _env_flag("AGENTMESH_FIRECRAWL_ENABLED"):
            return build_provider_status(
                name="web_research",
                configured=tavily_configured,
                ready=tavily_configured,
                telemetry=_tavily_telemetry,
                error=None if tavily_configured else "not_configured",
            )
        firecrawl_configured = _firecrawl_configuration() is not None
        configured = tavily_configured and firecrawl_configured
        tavily_observation = _tavily_telemetry.snapshot()
        firecrawl_observation = _firecrawl_telemetry.snapshot()
        last_error = tavily_observation.last_error or firecrawl_observation.last_error
        latency_values = [
            value
            for value in (tavily_observation.latency_ms, firecrawl_observation.latency_ms)
            if value is not None
        ]
        return ProviderStatus(
            name="web_research",
            configured=configured,
            ready=configured and last_error is None,
            mode="real" if configured and last_error is None else "fallback",
            last_error=last_error if configured else "not_configured",
            latency_ms=sum(latency_values) if latency_values else None,
        )
    provider = provider_from_env()
    if provider is None:
        return build_provider_status(
            name="web_research", configured=False, ready=False, error="unsupported_provider"
        )
    if isinstance(provider, MockWebSearchProvider):
        return build_provider_status(
            name="web_research", configured=True, ready=True, mode="fallback"
        )
    ready = shutil.which(provider.command) is not None
    return build_provider_status(
        name="web_research",
        configured=True,
        ready=ready,
        error=None if ready else provider_error_code(RuntimeError("command not found")),
    )
