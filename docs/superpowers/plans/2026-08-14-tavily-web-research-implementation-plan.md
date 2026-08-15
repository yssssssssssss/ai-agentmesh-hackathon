# Tavily Web Research Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a native, secret-safe Tavily HTTP provider for general Web Research and verify it with real smoke while keeping O2 product search independent.

**Architecture:** Implement `TavilyWebSearchProvider` behind the existing `WebSearchProvider` protocol using injected `httpx.Client`. Extend provider selection and health telemetry without changing `WebAcquisitionAgent`. Keep credentials in ignored `.env`; CI uses MockTransport only.

**Tech Stack:** Python 3.12+, httpx, Pydantic, FastAPI, pytest.

## Global Constraints

- Never commit or print the supplied Tavily key.
- Use `POST https://api.tavily.com/search` with `Authorization: Bearer`.
- Request only `query`, `search_depth`, `max_results`, and false values for answer/raw/images.
- Map only `results[].title`, `results[].url`, and `results[].content`.
- Stable errors: `timeout`, `auth_error`, `rate_limited`, `provider_error`, `malformed_response`.
- O2 metasearch remains a separate product-search capability.

---

### Task 1: Implement Tavily HTTP Search Provider

**Files:**
- Modify: `agentmesh/web_research.py`
- Modify: `tests/test_web_research.py`

**Interfaces:**
- Produces: `TavilyWebSearchProvider(api_url, api_key, timeout_seconds, http_client)` and `.search(query, limit) -> list[WebSearchResult]`.

- [ ] **Step 1: Write failing request/response tests**

Add tests using `httpx.MockTransport`:

```python
import httpx

from agentmesh.web_research import TavilyWebSearchProvider, WebResearchError


def test_tavily_provider_sends_safe_request_and_maps_results() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["payload"] = request.read().decode()
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
    assert '"query":"agent systems"' in str(captured["payload"]).replace(" ", "")
    assert '"search_depth":"basic"' in str(captured["payload"]).replace(" ", "")
    assert '"max_results":3' in str(captured["payload"]).replace(" ", "")
    assert results[0].title == "Agent systems"
    assert results[0].url == "https://example.test/agents"
    assert results[0].snippet == "Grounded search result"
```

- [ ] **Step 2: Write failing error-category tests**

Parameterize 401/403 as `auth_error`, 429/432 as `rate_limited`, 500 as `provider_error`; add timeout and malformed payload tests. Assert exception text contains neither API key nor response body.

- [ ] **Step 3: Run RED tests**

```bash
.venv/bin/python -m pytest tests/test_web_research.py -q
```

Expected: import fails because `TavilyWebSearchProvider` does not exist.

- [ ] **Step 4: Implement minimal provider**

Use an injected or owned `httpx.Client`, clamp limit with `max(0, min(limit, 20))`, call the endpoint, map results, update `ProviderTelemetry`, and raise only redacted `WebResearchError` messages.

- [ ] **Step 5: Run GREEN tests and Ruff**

```bash
.venv/bin/python -m pytest tests/test_web_research.py -q
.venv/bin/ruff check agentmesh/web_research.py tests/test_web_research.py
```

- [ ] **Step 6: Commit**

```bash
git add agentmesh/web_research.py tests/test_web_research.py
git commit -m "Add Tavily web research provider"
```

---

### Task 2: Add Tavily Selection, Health, Smoke, and Safe Configuration

**Files:**
- Modify: `agentmesh/web_research.py`
- Modify: `agentmesh/routes/health.py`
- Modify: `scripts/provider_smoke.py`
- Modify: `.env.example`
- Local-only modify: `.env`
- Modify: `tests/test_web_research.py`
- Modify: `tests/test_health.py`
- Modify: `tests/test_mvp_provider_contracts.py`

**Interfaces:**
- Consumes: Task 1 provider.
- Produces: `AGENTMESH_WEB_PROVIDER=tavily` selection, canonical health status, and real `provider_smoke.py --web`.

- [ ] **Step 1: Write failing environment-selection and health tests**

Test complete configuration returns `TavilyWebSearchProvider`; missing key returns no provider and `not_configured`; an observed auth failure yields degraded `auth_error`. Assert health JSON excludes key and API URL.

- [ ] **Step 2: Write failing smoke test**

Monkeypatch `provider_from_env()` with a deterministic Tavily provider returning one result. Assert `provider_smoke.main(["--web"]) == 0`, output is `web_research: configured=true ready=true mode=real`, and no key/body appears.

- [ ] **Step 3: Run RED tests**

```bash
.venv/bin/python -m pytest tests/test_web_research.py tests/test_health.py tests/test_mvp_provider_contracts.py -q
```

- [ ] **Step 4: Implement environment and health wiring**

Read:

```text
AGENTMESH_TAVILY_API_URL
AGENTMESH_TAVILY_API_KEY
AGENTMESH_TAVILY_TIMEOUT_SECONDS
```

Support `AGENTMESH_WEB_PROVIDER=tavily`. Build status from configuration plus Tavily telemetry. Keep command-provider health behavior unchanged.

- [ ] **Step 5: Update safe templates and local configuration**

Add placeholders to `.env.example`. Confirm `.env` is ignored, then write the user-supplied key only to local `.env` together with `AGENTMESH_WEB_PROVIDER=tavily` and the official endpoint. Verify `git status --short` never lists `.env`.

- [ ] **Step 6: Run real Tavily smoke**

```bash
.venv/bin/python scripts/provider_smoke.py --web
```

Expected: `configured=true ready=true mode=real` with redacted latency and no secret.

- [ ] **Step 7: Commit tracked files**

```bash
git add .env.example agentmesh/web_research.py agentmesh/routes/health.py scripts/provider_smoke.py tests/test_web_research.py tests/test_health.py tests/test_mvp_provider_contracts.py
git commit -m "Configure observable Tavily research"
```

---

### Task 3: Verify Application Provenance and Full Regression Gates

**Files:**
- Update: `docs/agentmesh-internal-pilot-mvp-todo.md`
- Update: `docs/superpowers/specs/2026-08-14-tavily-web-research-design.md`

- [ ] **Step 1: Verify real acquisition through the application**

Start an isolated demo server with local `.env`, send `$research.request` with a general web query, and assert sources are HTTPS pages with trace requested provider `web_research`, actual provider `tavily`, and mode `real`.

- [ ] **Step 2: Run focused tests**

```bash
.venv/bin/python -m pytest tests/test_web_research.py tests/test_health.py tests/test_mvp_provider_contracts.py tests/test_chat_flow.py -q
.venv/bin/ruff check .
```

- [ ] **Step 3: Run full gates**

```bash
AGENTMESH_EMBEDDING_ENABLED=false .venv/bin/python -m pytest -q
cd agentmesh-demo
npm run api:types
npm run test
npm run build
npm run test:e2e
```

- [ ] **Step 4: Record redacted evidence and commit**

Record only provider name, mode, latency, source count, and stable errors. Never record the key or response content.

```bash
git add docs/agentmesh-internal-pilot-mvp-todo.md docs/superpowers/specs/2026-08-14-tavily-web-research-design.md
git commit -m "Record Tavily provider verification"
```
