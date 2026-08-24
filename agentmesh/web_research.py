from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import shlex
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from time import monotonic
from typing import Any, Protocol
from urllib.parse import SplitResult, urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, Field

from agentmesh.acquisition import (
    AcquiredEvidenceItem,
    AcquisitionAgent,
    AcquisitionQuery,
    AcquisitionRequest,
    AcquisitionResult,
    ProviderCallRecord,
)
from agentmesh.models import Source, now_utc
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
_FIRECRAWL_RAW_CONTENT_MAX_BYTES = 128 * 1024
_BOILERPLATE_TERMS = {
    "cookie",
    "copyright",
    "footer",
    "login",
    "menu",
    "navigation",
    "sign in",
    "sign up",
    "关注作者",
    "导航",
    "举报",
    "搜索关闭",
    "登录",
    "注册",
}
_QUERY_STOP_TERMS = {
    "about",
    "and",
    "for",
    "the",
    "with",
    "以及",
    "分析",
    "对比",
    "比较",
    "给出",
    "重点",
}
_SECONDARY_SOURCE_DOMAINS = {
    "csdn.net",
    "einkcn.com",
    "juejin.cn",
    "medium.com",
    "reddit.com",
    "zhihu.com",
}
_PRIMARY_PATH_MARKERS = ("/docs", "/documentation", "/help", "/release", "/security", "/support")


class FetchedWebContent(BaseModel):
    excerpt: str = Field(min_length=1, max_length=8192)
    retrieved_at: datetime
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    truncated: bool = False
    risk_flags: list[str] = Field(default_factory=list, max_length=10)
    provider_call: ProviderCallRecord


class WebSearchResult(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=1000)
    snippet: str = Field(default="", max_length=8192)
    content_provider: str | None = Field(default=None, max_length=120)
    fetched_content: FetchedWebContent | None = None
    enrichment_error: str | None = Field(default=None, max_length=80)
    question_ids: list[str] = Field(default_factory=list, max_length=20)


class WebSearchBatch(BaseModel):
    results: list[WebSearchResult] = Field(default_factory=list, max_length=20)
    provider_calls: list[ProviderCallRecord] = Field(default_factory=list, max_length=20)


class WebSearchProvider(Protocol):
    def search(self, query: str, limit: int = 3) -> list[WebSearchResult]: ...


class WebContentFetcher(Protocol):
    provider_name: str

    def fetch(self, url: str, *, query: str) -> FetchedWebContent: ...


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


def _sanitize_persisted_url(value: str) -> str:
    redacted = redact_sensitive_text(value)
    try:
        parsed = urlsplit(redacted)
        hostname = (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        port = parsed.port
    except (UnicodeError, ValueError):
        return redacted.split("?", 1)[0].split("#", 1)[0]
    if not hostname or parsed.scheme.lower() not in {"http", "https"}:
        return redacted.split("?", 1)[0].split("#", 1)[0]
    display_host = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    netloc = display_host if port in {None, default_port} else f"{display_host}:{port}"
    return urlunsplit(
        SplitResult(
            scheme=parsed.scheme.lower(),
            netloc=netloc,
            path=parsed.path or "/",
            query="",
            fragment="",
        )
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


def _truncate_utf8(value: str, max_bytes: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value, False
    return encoded[:max_bytes].decode("utf-8", errors="ignore"), True


def _query_terms(query: str) -> set[str]:
    terms: set[str] = set()
    for token in re.findall(r"[a-z0-9][a-z0-9_.+-]*|[\u3400-\u9fff]+", query.lower()):
        if token in _QUERY_STOP_TERMS:
            continue
        if re.fullmatch(r"[\u3400-\u9fff]+", token):
            if len(token) <= 6:
                terms.add(token)
            terms.update(token[index : index + 2] for index in range(max(0, len(token) - 1)))
            terms.update(token[index : index + 3] for index in range(max(0, len(token) - 2)))
            continue
        if len(token) >= 3:
            terms.add(token)
    return set(sorted(terms, key=lambda item: (-len(item), item))[:120])


def _is_boilerplate(block: str) -> bool:
    lowered = block.lower()
    if len(block) > 240:
        return False
    return any(term in lowered for term in _BOILERPLATE_TERMS)


def _relevant_excerpt(markdown: str, query: str, max_bytes: int) -> tuple[str, bool]:
    bounded, raw_truncated = _truncate_utf8(markdown.strip(), _FIRECRAWL_RAW_CONTENT_MAX_BYTES)
    blocks = [block.strip() for block in re.split(r"\n\s*\n+", bounded) if block.strip()]
    informative = [(index, block) for index, block in enumerate(blocks) if not _is_boilerplate(block)]
    if not informative:
        excerpt, excerpt_truncated = _truncate_utf8(bounded, max_bytes)
        return excerpt.strip(), raw_truncated or excerpt_truncated

    cleaned = "\n\n".join(block for _, block in informative)
    if len(cleaned.encode("utf-8")) <= max_bytes:
        return cleaned, raw_truncated or len(informative) < len(blocks)

    terms = _query_terms(query)
    scored: list[tuple[int, int, str]] = []
    for index, block in informative:
        lowered = block.lower()
        match_score = sum(min(lowered.count(term), 3) * min(len(term), 8) for term in terms)
        score = match_score
        if match_score and block.startswith("#"):
            score += 4
        if match_score and len(block) >= 120:
            score += 1
        scored.append((score, index, block))
    relevant = [item for item in scored if item[0] > 0]
    candidates = sorted(relevant or scored, key=lambda item: (-item[0], item[1]))[:8]
    selected_indices = {item[1] for item in candidates}
    selected_blocks = [block for index, block in informative if index in selected_indices]
    excerpt, excerpt_truncated = _truncate_utf8("\n\n".join(selected_blocks), max_bytes)
    omitted_blocks = len(selected_blocks) < len(informative)
    return excerpt.strip(), raw_truncated or excerpt_truncated or omitted_blocks


def _canonical_result_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        port = parsed.port
    except (UnicodeError, ValueError):
        return url
    if not hostname:
        return url
    display_host = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    netloc = display_host if port in {None, default_port} else f"{display_host}:{port}"
    return urlunsplit(
        SplitResult(
            scheme=parsed.scheme.lower(),
            netloc=netloc,
            path=parsed.path.rstrip("/") or "/",
            query=parsed.query,
            fragment="",
        )
    )


def _source_priority(result: WebSearchResult, queries: list[AcquisitionQuery]) -> tuple[int, int]:
    parsed = urlsplit(result.url)
    hostname = (parsed.hostname or "").lower()
    haystack = f"{result.title} {result.url} {result.snippet}".lower()
    terms = _query_terms(" ".join(item.query for item in queries))
    overlap = sum(min(haystack.count(term), 3) * min(len(term), 8) for term in terms)
    primary_bonus = 20 if any(marker in parsed.path.lower() for marker in _PRIMARY_PATH_MARKERS) else 0
    secondary_penalty = 20 if any(hostname == domain or hostname.endswith(f".{domain}") for domain in _SECONDARY_SOURCE_DOMAINS) else 0
    return primary_bonus - secondary_penalty, overlap


class FirecrawlContentFetcher:
    provider_name = "firecrawl"

    def __init__(
        self,
        api_url: str,
        api_key: str,
        timeout_seconds: float = 60.0,
        max_content_chars: int = 4000,
        http_client: httpx.Client | None = None,
    ):
        self.api_url = api_url
        self.api_key = api_key
        self.timeout_seconds = max(0.1, timeout_seconds)
        self.max_content_bytes = max(200, min(max_content_chars, 8192))
        self.http_client = http_client or httpx.Client(timeout=self.timeout_seconds)

    def fetch(self, url: str, *, query: str) -> FetchedWebContent:
        self._validate_public_url(url)
        started = monotonic()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request_payload = {
            "url": url,
            "formats": ["markdown"],
            "onlyMainContent": True,
            "timeout": min(60_000, max(1, round(self.timeout_seconds * 1000))),
        }
        request_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
        try:
            response = self.http_client.post(
                self.api_url,
                headers=headers,
                json=request_payload,
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
            if payload.get("success") is not True or not isinstance(data, dict):
                raise TypeError("invalid Firecrawl response")
            markdown = data["markdown"]
            if not isinstance(markdown, str) or not markdown.strip():
                raise ValueError("empty Firecrawl content")
            excerpt, truncated = _relevant_excerpt(markdown, query, self.max_content_bytes)
            if not excerpt:
                raise ValueError("empty Firecrawl excerpt")
        except (KeyError, TypeError, ValueError) as error:
            self._fail("malformed_response", "Firecrawl returned malformed JSON", error, started)

        elapsed_ms = (monotonic() - started) * 1000
        _firecrawl_telemetry.success(elapsed_ms)
        return FetchedWebContent(
            excerpt=excerpt,
            retrieved_at=now_utc(),
            content_hash=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
            truncated=truncated,
            risk_flags=["truncated"] if truncated else [],
            provider_call=ProviderCallRecord(
                provider=self.provider_name,
                operation="scrape",
                request_hash=request_hash,
                status="success",
                latency_ms=max(0, round(elapsed_ms)),
                result_count=1,
            ),
        )

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
        scrape_limit: int = 6,
    ):
        self.search_provider = search_provider
        self.content_fetcher = content_fetcher
        self.scrape_limit = max(1, min(scrape_limit, 10))

    def search(self, query: str, limit: int = 3) -> list[WebSearchResult]:
        return self.search_batch(
            [AcquisitionQuery(query=query)],
            result_limit=limit,
        ).results

    def search_batch(
        self,
        queries: list[AcquisitionQuery],
        *,
        result_limit: int,
    ) -> WebSearchBatch:
        normalized_queries: list[AcquisitionQuery] = []
        seen_queries: set[str] = set()
        for item in queries[:4]:
            query = item.query.strip()
            if not query or query in seen_queries:
                continue
            seen_queries.add(query)
            normalized_queries.append(
                item.model_copy(update={"query": query, "question_ids": list(dict.fromkeys(item.question_ids))})
            )
        if not normalized_queries:
            return WebSearchBatch()

        provider_calls: list[ProviderCallRecord] = []
        by_url: dict[str, tuple[int, WebSearchResult]] = {}
        errors: list[WebResearchError] = []
        per_query_limit = max(1, min(5, result_limit))
        discovery_order = 0

        def collect_query(item: AcquisitionQuery) -> None:
            nonlocal discovery_order
            started = monotonic()
            request_hash = hashlib.sha256(item.query.encode("utf-8")).hexdigest()
            try:
                search_results = self.search_provider.search(item.query, per_query_limit)
            except WebResearchError as error:
                errors.append(error)
                provider_calls.append(
                    ProviderCallRecord(
                        provider=self.search_provider_name,
                        operation="search",
                        request_hash=request_hash,
                        status="error",
                        latency_ms=max(0, round((monotonic() - started) * 1000)),
                        error_code=error.reason,
                    )
                )
                return
            provider_calls.append(
                ProviderCallRecord(
                    provider=self.search_provider_name,
                    operation="search",
                    request_hash=request_hash,
                    status="success",
                    latency_ms=max(0, round((monotonic() - started) * 1000)),
                    result_count=len(search_results),
                )
            )
            for result in search_results:
                key = _canonical_result_url(result.url)
                existing = by_url.get(key)
                question_ids = list(dict.fromkeys([*(existing[1].question_ids if existing else []), *item.question_ids]))
                candidate = result.model_copy(update={"url": key, "question_ids": question_ids})
                if existing is None:
                    by_url[key] = (discovery_order, candidate)
                    discovery_order += 1
                elif len(candidate.snippet) > len(existing[1].snippet):
                    by_url[key] = (existing[0], candidate)
                else:
                    by_url[key] = (existing[0], existing[1].model_copy(update={"question_ids": question_ids}))

        for item in normalized_queries:
            collect_query(item)

        required_question_ids = list(
            dict.fromkeys(question_id for item in normalized_queries for question_id in item.question_ids)
        )
        missing_question_ids = [
            question_id
            for question_id in required_question_ids
            if sum(question_id in result.question_ids for _, result in by_url.values()) < 2
        ]
        if missing_question_ids and len(normalized_queries) < 4:
            supplemental_query = AcquisitionQuery(
                query=(normalized_queries[0].query + " 官方帮助中心 发布说明 可验证证据")[:4000],
                question_ids=missing_question_ids,
            )
            if supplemental_query.query not in seen_queries:
                normalized_queries.append(supplemental_query)
                collect_query(supplemental_query)
        if not by_url and errors:
            raise errors[-1]

        ranked = sorted(
            by_url.values(),
            key=lambda pair: (
                -_source_priority(pair[1], normalized_queries)[0],
                -_source_priority(pair[1], normalized_queries)[1],
                pair[0],
            ),
        )
        selected_pairs: list[tuple[int, WebSearchResult]] = []
        selected_urls: set[str] = set()
        selected_limit = max(1, min(result_limit, self.scrape_limit))
        for question_id in required_question_ids:
            for pair in ranked:
                if pair[1].url in selected_urls or question_id not in pair[1].question_ids:
                    continue
                selected_pairs.append(pair)
                selected_urls.add(pair[1].url)
                if sum(question_id in item.question_ids for _, item in selected_pairs) >= 2:
                    break
                if len(selected_pairs) >= selected_limit:
                    break
            if len(selected_pairs) >= selected_limit:
                break
        for pair in ranked:
            if len(selected_pairs) >= selected_limit:
                break
            if pair[1].url not in selected_urls:
                selected_pairs.append(pair)
                selected_urls.add(pair[1].url)
        selected = [item for _, item in sorted(selected_pairs, key=lambda pair: pair[0])]

        def scrape_one(result: WebSearchResult) -> tuple[WebSearchResult, ProviderCallRecord]:
            scrape_query = " ".join(
                item.query
                for item in normalized_queries
                if not result.question_ids or set(item.question_ids) & set(result.question_ids)
            ) or normalized_queries[0].query
            started = monotonic()
            request_hash = hashlib.sha256(result.url.encode("utf-8")).hexdigest()
            try:
                fetched = self.content_fetcher.fetch(result.url, query=scrape_query)
            except WebResearchError as error:
                return (
                    result.model_copy(update={"enrichment_error": error.reason}),
                    ProviderCallRecord(
                        provider=self.content_provider_name,
                        operation="scrape",
                        request_hash=request_hash,
                        status="error",
                        latency_ms=max(0, round((monotonic() - started) * 1000)),
                        error_code=error.reason,
                    ),
                )
            return (
                result.model_copy(
                    update={
                        "snippet": fetched.excerpt,
                        "content_provider": self.content_fetcher.provider_name,
                        "fetched_content": fetched,
                    }
                ),
                fetched.provider_call,
            )

        if not selected:
            return WebSearchBatch(results=[], provider_calls=provider_calls)
        with ThreadPoolExecutor(max_workers=min(3, len(selected))) as executor:
            scrape_outcomes = list(executor.map(scrape_one, selected))
        enriched = [result for result, _call in scrape_outcomes]
        provider_calls.extend(call for _result, call in scrape_outcomes)
        return WebSearchBatch(results=enriched, provider_calls=provider_calls)


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
        provider_calls: list[ProviderCallRecord] = []
        if isinstance(self.provider, TavilyFirecrawlWebSearchProvider):
            queries = request.question_queries or [AcquisitionQuery(query=request.query)]
            batch = self.provider.search_batch(
                queries,
                result_limit=self.provider.scrape_limit if request.question_queries else 3,
            )
            results = batch.results
            provider_calls = batch.provider_calls
        else:
            results = self.provider.search(request.query)
        latency_ms = (monotonic() - started) * 1000
        provider_name = getattr(self.provider, "provider_name", "web_research")
        mode = getattr(self.provider, "mode", "real")
        content_provider = getattr(self.provider, "content_provider_name", None)
        scraped_count = sum(item.content_provider == content_provider for item in results) if content_provider else 0
        enrichment_errors = sorted({item.enrichment_error for item in results if item.enrichment_error})
        fallback_source_count = sum(item.content_provider != content_provider for item in results) if content_provider else 0
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
                    "search_call_count": str(
                        sum(call.provider == self.provider.search_provider_name for call in provider_calls)
                    ),
                    "scrape_call_count": str(
                        sum(call.provider == self.provider.content_provider_name for call in provider_calls)
                    ),
                    "fallback_source_count": str(fallback_source_count),
                    "estimated_firecrawl_credits": str(
                        sum(
                            call.provider == self.provider.content_provider_name and call.status == "success"
                            for call in provider_calls
                        )
                    ),
                }
            )
        safe_results: list[WebSearchResult] = []
        sensitive_content_redacted = False
        for item in results:
            title = redact_sensitive_text(item.title)
            url = _sanitize_persisted_url(item.url)
            snippet = redact_sensitive_text(item.snippet)
            fetched = item.fetched_content
            if fetched is not None and fetched.excerpt != snippet:
                fetched = fetched.model_copy(
                    update={
                        "excerpt": snippet,
                        "content_hash": hashlib.sha256(snippet.encode("utf-8")).hexdigest(),
                    }
                )
            sensitive_content_redacted = sensitive_content_redacted or (
                title != item.title or url != item.url or snippet != item.snippet
            )
            safe_results.append(
                item.model_copy(
                    update={
                        "title": title,
                        "url": url,
                        "snippet": snippet,
                        "fetched_content": fetched,
                    }
                )
            )
        results = safe_results
        if sensitive_content_redacted:
            metadata["sensitive_content_redacted"] = "true"
        if not results:
            return AcquisitionResult(
                actor=self.actor,
                title="未找到 Web 资料",
                content="Web 检索没有返回可用结果。",
                sources=[],
                provider_calls=provider_calls,
                metadata=metadata,
            )
        sources = [Source(title=item.title, source_type="web_page", reference=item.url) for item in results]
        source_evidence: list[AcquiredEvidenceItem] = []
        for item, source in zip(results, sources, strict=True):
            excerpt = item.snippet.strip() or item.title.strip()
            fetched = item.fetched_content
            evidence_provider = item.content_provider or (
                self.provider.search_provider_name
                if isinstance(self.provider, TavilyFirecrawlWebSearchProvider)
                else actual_provider
            )
            source_evidence.append(
                AcquiredEvidenceItem(
                    source_id=source.id,
                    content_provider=evidence_provider,
                    excerpt=excerpt,
                    retrieved_at=fetched.retrieved_at if fetched is not None else now_utc(),
                    content_hash=(
                        fetched.content_hash
                        if fetched is not None
                        else hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
                    ),
                    truncated=fetched.truncated if fetched is not None else False,
                    risk_flags=fetched.risk_flags if fetched is not None else [],
                    question_ids=item.question_ids,
                )
            )
        content = "\n".join(f"{item.title}: {item.snippet}" for item in results)
        content_truncated = len(content) > 4000
        if content_truncated:
            content = content[:3999].rstrip() + "…"
            metadata["content_truncated"] = "true"
        metadata["source_evidence_count"] = str(len(source_evidence))
        return AcquisitionResult(
            actor=self.actor,
            title="Web 检索结果",
            content=content,
            sources=sources,
            source_evidence=source_evidence,
            provider_calls=provider_calls,
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
                _int_env("AGENTMESH_FIRECRAWL_MAX_CONTENT_CHARS", 4000, minimum=200, maximum=8192),
            ),
            scrape_limit=_int_env("AGENTMESH_FIRECRAWL_MAX_PAGES", 6, minimum=1, maximum=10),
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
