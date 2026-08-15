# Tavily Web Research Provider Design

Date: 2026-08-14
Status: Implemented and locally verified

## Goal

Add Tavily as the real general-purpose Web Research provider while preserving the existing `WebSearchProvider` and `WebAcquisitionAgent` boundaries. Keep O2 metasearch separate because the installed CLI currently provides JD product search rather than general web search.

## Non-goals

- Do not add the Tavily Python SDK.
- Do not use Tavily for O2, Data API, or document search.
- Do not enable answer generation, raw page content, images, crawl, map, extract, or research endpoints.
- Do not commit, log, audit, or return the Tavily API key.
- Do not call Tavily from CI; CI uses deterministic mocked HTTP responses.

## Configuration

The ignored local `.env` will contain:

```dotenv
AGENTMESH_WEB_PROVIDER=tavily
AGENTMESH_TAVILY_API_URL=https://api.tavily.com/search
AGENTMESH_TAVILY_API_KEY=<local-secret>
AGENTMESH_TAVILY_TIMEOUT_SECONDS=20
```

`.env.example` will contain the same variable names with `replace-with-your-key`. The supplied key remains local and should be rotated before production because it appeared in chat.

## Provider Interface

Add `TavilyWebSearchProvider` in `agentmesh/web_research.py` with these public interfaces:

```python
TavilyWebSearchProvider(
    api_url: str,
    api_key: str,
    timeout_seconds: float = 20.0,
    http_client: httpx.Client | None = None,
)

TavilyWebSearchProvider.search(query: str, limit: int = 3) -> list[WebSearchResult]
```

The class exposes `provider_name = "tavily"` and `mode = "real"`.

`provider_from_env()` returns this provider when `AGENTMESH_WEB_PROVIDER=tavily` and both URL and key are present. Missing configuration returns no provider and health reports `not_configured` rather than silently using mock data.

## HTTP Contract

Call `POST https://api.tavily.com/search` with:

```http
Authorization: Bearer <local-secret>
Content-Type: application/json
```

```json
{
  "query": "user query",
  "search_depth": "basic",
  "max_results": 3,
  "include_answer": false,
  "include_raw_content": false,
  "include_images": false
}
```

Clamp `max_results` to Tavily's documented range `0..20`. Map `results[].title`, `results[].url`, and `results[].content` to `WebSearchResult.title`, `.url`, and `.snippet`. Ignore optional response fields.

Official contract: https://docs.tavily.com/documentation/api-reference/endpoint/search

## Error Handling and Telemetry

Use `WebResearchError` with stable, secret-safe reasons:

- timeout: `timeout`
- HTTP 401/403: `auth_error`
- HTTP 429 or plan-limit responses: `rate_limited`
- other HTTP failures: `provider_error`
- invalid JSON or missing/invalid `results`: `malformed_response`

Never include response bodies, Authorization headers, URLs with query secrets, or the API key in exceptions or telemetry. Record only stable error category and latency with `ProviderTelemetry`.

`web_research_provider_status()` reports Tavily configured when URL and key exist. It reports ready while configured and no current telemetry error exists; after an observed failure it reports degraded with the stable error category.

## Composition with O2

`build_acquisition_agent()` keeps its existing composition order. O2 remains opt-in and Tavily is the general web provider. On the current host, O2 0.0.8 and metasearch 0.1.6 are installed and real SKU search works, but the actual sub-CLI supports product search only. O2 must not be enabled as a generic Web Research substitute.

## Smoke Test

`provider_smoke.py --web` resolves Tavily from `.env`, executes one read-only query, requires at least one source, and prints only provider name, configured/ready/mode, latency, and stable error category.

## Tests

Backend tests cover:

1. Tavily request URL, Bearer header, safe JSON body, and `max_results`.
2. Response mapping from `title/url/content`.
3. Timeout, auth, rate limit, provider failure, and malformed response categories.
4. Error strings and status payloads never contain API key or response body.
5. `provider_from_env()` selects Tavily only with complete configuration.
6. Health transitions from configured/ready to degraded after an observed failure.
7. Web acquisition provenance records requested `web_research`, actual `tavily`, real mode, and latency.
8. Provider smoke succeeds against a mocked Tavily response and real smoke succeeds with the local ignored `.env`.

## Acceptance Criteria

- Real Tavily smoke reports configured, ready, and real.
- `$research.request` can return Tavily-backed sources and provenance.
- O2 product search remains independently usable and is not presented as general web search.
- Tavily failures remain explicit and never fall through to a fake Web success unless the existing composite provider deliberately chooses another real provider.
- No Tavily credential is tracked or printed.
- Full pytest, Ruff, React build, and Playwright gates pass.

## Verification Evidence

- Real `provider_smoke.py --web` reported Tavily configured, ready, and real.
- An isolated application user with no private documents received three HTTPS Tavily sources; trace persisted `requested_provider=web_research`, `actual_provider=tavily`, and `mode=real`.
- O2 0.0.8 and metasearch 0.1.6 are installed; doctor, local smoke, real JD product search, and AgentMesh O2 provider smoke passed. The installed sub-CLI is SKU-only and remains separate from general Web Research.
- Full gates passed: 523 pytest, Ruff, 7 Vitest, production build, and 24 Playwright tests.
