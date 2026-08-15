from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from time import monotonic
from typing import Any, Protocol

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

_tavily_telemetry = ProviderTelemetry()

class WebSearchResult(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=1000)
    snippet: str = Field(default="", max_length=2000)


class WebSearchProvider(Protocol):
    def search(self, query: str, limit: int = 3) -> list[WebSearchResult]: ...


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
        actual_provider = getattr(self.provider, "provider_name", "web_research")
        mode = getattr(self.provider, "mode", "real")
        metadata = provider_metadata(
            requested_provider="web_research",
            actual_provider=actual_provider,
            mode=mode,
            latency_ms=latency_ms,
            fallback_reason="explicit_mock_provider" if mode == "fallback" else None,
        )
        if not results:
            return AcquisitionResult(
                actor=self.actor,
                title="未找到 Web 资料",
                content="Web 检索没有返回可用结果。",
                sources=[],
                metadata=metadata,
            )
        content = "\n".join(f"{item.title}: {item.snippet}" for item in results)
        return AcquisitionResult(
            actor=self.actor,
            title="Web 检索结果",
            content=content,
            sources=[Source(title=item.title, source_type="web_page", reference=item.url) for item in results],
            metadata=metadata,
        )


def provider_from_env() -> WebSearchProvider | None:
    provider = os.getenv("AGENTMESH_WEB_PROVIDER", "").strip().lower()
    if provider == "mock":
        return MockWebSearchProvider()
    if provider == "tavily":
        api_url = os.getenv("AGENTMESH_TAVILY_API_URL", "").strip()
        api_key = os.getenv("AGENTMESH_TAVILY_API_KEY", "").strip()
        if not api_url or not api_key:
            return None
        try:
            timeout_seconds = max(0.1, float(os.getenv("AGENTMESH_TAVILY_TIMEOUT_SECONDS", "20")))
        except ValueError:
            timeout_seconds = 20.0
        return TavilyWebSearchProvider(api_url, api_key, timeout_seconds)
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
        configured = bool(
            os.getenv("AGENTMESH_TAVILY_API_URL", "").strip()
            and os.getenv("AGENTMESH_TAVILY_API_KEY", "").strip()
        )
        return build_provider_status(
            name="web_research",
            configured=configured,
            ready=configured,
            telemetry=_tavily_telemetry,
            error=None if configured else "not_configured",
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
