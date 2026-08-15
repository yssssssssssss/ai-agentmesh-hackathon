# Automatic LLM Failover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Configure the internal primary LLM, fallback LLM, and embedding endpoint safely, and automatically use the fallback model for eligible primary failures while preserving exact model provenance.

**Architecture:** Keep HTTP transport in `LLMClient`. Add a request-scoped `FailoverChatLLM` wrapper in `agentmesh/synthesis.py`, where model selection already enters chat workflows. Persist answer-generation model provenance separately from acquisition provider provenance, expose it through OpenAPI, and render it in Workspace. Extend the existing Provider smoke to probe both LLM models independently.

**Tech Stack:** Python 3.12+, Pydantic, httpx, FastAPI, SQLite, React 18, TypeScript, TanStack Query, pytest, Vitest, Playwright.

## Global Constraints

- Never commit or print the supplied credential.
- Keep the real credential only in the ignored local `.env`.
- Use non-streaming OpenAI-compatible chat completions at the configured `/v1` base URL.
- Use the full `/v1/embeddings` endpoint for Embedding.
- Fail over once on `timeout`, `request_error`, `http_status`, `invalid_response`, or `empty_response`.
- Never fail over on `auth_error`.
- Explicitly injected test clients bypass environment failover.
- Persist `requested_model` and `actual_model`; never overload requested/actual provider fields with model names.
- One healthy LLM must not mask a failed LLM smoke.

---

### Task 1: Add Request-Scoped Failover LLM

**Files:**
- Modify: `agentmesh/synthesis.py:1-106`
- Modify: `agentmesh/llm.py:142-180`
- Create: `tests/test_llm_failover.py`

**Interfaces:**
- Consumes: `LLMClient.from_model_id(model_id: str | None, timeout_seconds: float | None)`, `LLMRequestError.reason`, `resolve_agent_model_id(repository, user)`.
- Produces: `FailoverChatLLM(primary: ChatLLM, fallback: ChatLLM)`, `requested_model`, `actual_model`, `fallback_reason`, and `chat_llm_client(repository: SQLiteStore, user: User, llm_client: ChatLLM | None, timeout_seconds: float | None) -> ChatLLM | None` with environment failover.

- [ ] **Step 1: Write failure-classification and single-attempt tests**

Create `tests/test_llm_failover.py` with a deterministic stub:

```python
from __future__ import annotations

from dataclasses import dataclass

import pytest

from agentmesh.llm import LLMClient, LLMRequestError
from agentmesh.synthesis import FailoverChatLLM


@dataclass
class StubLLM:
    model: str
    result: str | None = None
    error: LLMRequestError | None = None
    calls: int = 0

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result or ""


def test_primary_success_does_not_call_fallback() -> None:
    primary = StubLLM("primary-model", result="primary answer")
    fallback = StubLLM("fallback-model", result="fallback answer")
    client = FailoverChatLLM(primary, fallback)

    assert client.complete("system", "user") == "primary answer"
    assert primary.calls == 1
    assert fallback.calls == 0
    assert client.requested_model == "primary-model"
    assert client.actual_model == "primary-model"
    assert client.fallback_reason is None


@pytest.mark.parametrize("reason", ["timeout", "request_error", "http_status", "invalid_response"])
def test_eligible_primary_errors_call_fallback_once(reason: str) -> None:
    primary = StubLLM("primary-model", error=LLMRequestError(reason, "redacted"))
    fallback = StubLLM("fallback-model", result="fallback answer")
    client = FailoverChatLLM(primary, fallback)

    assert client.complete("system", "user") == "fallback answer"
    assert primary.calls == 1
    assert fallback.calls == 1
    assert client.actual_model == "fallback-model"
    assert client.fallback_reason == reason


def test_empty_primary_response_calls_fallback_once() -> None:
    primary = StubLLM("primary-model", result="   ")
    fallback = StubLLM("fallback-model", result="fallback answer")
    client = FailoverChatLLM(primary, fallback)

    assert client.complete("system", "user") == "fallback answer"
    assert client.fallback_reason == "empty_response"


def test_auth_error_does_not_call_fallback() -> None:
    primary = StubLLM("primary-model", error=LLMRequestError("auth_error", "redacted"))
    fallback = StubLLM("fallback-model", result="fallback answer")
    client = FailoverChatLLM(primary, fallback)

    with pytest.raises(LLMRequestError, match="redacted"):
        client.complete("system", "user")
    assert fallback.calls == 0


def test_double_failure_has_stable_redacted_reason() -> None:
    primary = StubLLM("primary-model", error=LLMRequestError("timeout", "primary body secret"))
    fallback = StubLLM("fallback-model", error=LLMRequestError("request_error", "fallback body secret"))
    client = FailoverChatLLM(primary, fallback)

    with pytest.raises(LLMRequestError) as captured:
        client.complete("system", "user")
    assert captured.value.reason == "primary_timeout_fallback_request_error"
    assert "secret" not in str(captured.value)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_llm_failover.py -q
```

Expected: collection fails because `FailoverChatLLM` does not exist.

- [ ] **Step 3: Implement the minimal wrapper**

Add to `agentmesh/synthesis.py`:

```python
FAILOVER_REASONS = frozenset({"timeout", "request_error", "http_status", "invalid_response", "empty_response"})


class FailoverChatLLM:
    def __init__(self, primary: ChatLLM, fallback: ChatLLM):
        self.primary = primary
        self.fallback = fallback
        self.requested_model = str(getattr(primary, "model", "primary"))
        self.actual_model = self.requested_model
        self.fallback_reason: str | None = None

    @property
    def model(self) -> str:
        return self.actual_model

    @staticmethod
    def _nonempty(client: ChatLLM, system_prompt: str, user_prompt: str) -> str:
        result = client.complete(system_prompt, user_prompt)
        if not result.strip():
            raise LLMRequestError("empty_response", "LLM returned an empty response")
        return result

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        try:
            return self._nonempty(self.primary, system_prompt, user_prompt)
        except LLMRequestError as primary_error:
            if primary_error.reason not in FAILOVER_REASONS:
                raise
            self.fallback_reason = primary_error.reason

        self.actual_model = str(getattr(self.fallback, "model", "fallback"))
        try:
            return self._nonempty(self.fallback, system_prompt, user_prompt)
        except LLMRequestError as fallback_error:
            reason = f"primary_{self.fallback_reason}_fallback_{fallback_error.reason}"
            raise LLMRequestError(reason, "Primary and fallback LLM requests failed") from fallback_error
```

Update `chat_llm_client()` to resolve the selected model and `AGENTMESH_LLM_FALLBACK_MODEL_ID`. Return the injected client unchanged. Do not wrap when the fallback is absent, unconfigured, or the same normalized model ID.

- [ ] **Step 4: Add model-resolution tests**

Add these complete tests to `tests/test_llm_failover.py`:

```python
from agentmesh.seed import USER
from agentmesh.store import store
from agentmesh.synthesis import chat_llm_client


def install_model_factory(monkeypatch, clients: dict[str, StubLLM]) -> None:
    monkeypatch.setattr(
        LLMClient,
        "from_model_id",
        classmethod(lambda cls, model_id, *, timeout_seconds=None: clients.get(str(model_id))),
    )


def test_chat_client_wraps_selected_model_with_configured_fallback(monkeypatch) -> None:
    primary = StubLLM("primary-model", result="primary answer")
    fallback = StubLLM("fallback-model", result="fallback answer")
    install_model_factory(monkeypatch, {"primary": primary, "fallback": fallback})
    monkeypatch.setattr("agentmesh.synthesis.resolve_agent_model_id", lambda repository, user: "primary")
    monkeypatch.setenv("AGENTMESH_LLM_FALLBACK_MODEL_ID", "fallback")

    client = chat_llm_client(store, USER)

    assert isinstance(client, FailoverChatLLM)
    assert client.primary is primary
    assert client.fallback is fallback


def test_injected_client_bypasses_environment_fallback(monkeypatch) -> None:
    injected = StubLLM("injected", result="ok")
    monkeypatch.setenv("AGENTMESH_LLM_FALLBACK_MODEL_ID", "fallback")

    assert chat_llm_client(store, USER, injected) is injected


def test_explicit_fallback_selection_does_not_wrap_itself(monkeypatch) -> None:
    fallback = StubLLM("fallback-model", result="fallback answer")
    install_model_factory(monkeypatch, {"fallback": fallback})
    monkeypatch.setattr("agentmesh.synthesis.resolve_agent_model_id", lambda repository, user: "fallback")
    monkeypatch.setenv("AGENTMESH_LLM_FALLBACK_MODEL_ID", "fallback")

    client = chat_llm_client(store, USER)

    assert client is fallback
    assert not isinstance(client, FailoverChatLLM)
```

- [ ] **Step 5: Run Task 1 tests and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_llm_failover.py tests/test_chat_flow.py -q
.venv/bin/ruff check agentmesh/synthesis.py agentmesh/llm.py tests/test_llm_failover.py
```

Expected: all selected tests pass and Ruff reports no findings.

Commit:

```bash
git add agentmesh/synthesis.py agentmesh/llm.py tests/test_llm_failover.py
git commit -m "Add automatic LLM failover"
```

---

### Task 2: Persist and Render Requested and Actual Models

**Files:**
- Modify: `agentmesh/models.py:290-301`
- Modify: `agentmesh/synthesis.py:16-92`
- Modify: `agentmesh/agents.py:132-170, 323-341, 396-424, 1545-1581, 2022-2046`
- Modify: `tests/test_chat_flow.py`
- Modify: `tests/test_mvp_chat_threads.py`
- Modify: `agentmesh-demo/src/features/workspace/types.ts:12-25`
- Modify: `agentmesh-demo/src/components/workspace/ConversationThread.tsx:26-38`
- Modify: `agentmesh-demo/e2e/workspace-mvp.spec.ts`
- Regenerate: `agentmesh-demo/src/api/generated/schema.ts`

**Interfaces:**
- Consumes: Task 1 `FailoverChatLLM.requested_model`, `.actual_model`, `.fallback_reason`.
- Produces: `ChatWorkflowTrace.requested_model`, `ChatWorkflowTrace.actual_model`, `ChatWorkflowTrace.model_fallback_reason`, and `SynthesisResult` model provenance.

- [ ] **Step 1: Write persistence tests**

Add backend tests that force primary timeout and fallback success, then assert:

```python
assert response.workflow_trace.requested_model == "primary-model"
assert response.workflow_trace.actual_model == "fallback-model"
assert response.workflow_trace.model_fallback_reason == "timeout"

reloaded = client.get(f"/api/chat/threads/{response.thread_id}").json()
trace = reloaded["messages"][-1]["workflow_trace"]
assert trace["requested_model"] == "primary-model"
assert trace["actual_model"] == "fallback-model"
```

Add a primary-success case asserting both model fields are identical. Add a concurrency test using two request-scoped wrappers with opposite outcomes and assert no cross-request actual-model leakage.

- [ ] **Step 2: Run persistence tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_chat_flow.py tests/test_mvp_chat_threads.py -q
```

Expected: new assertions fail because model fields are absent.

- [ ] **Step 3: Extend backend models and synthesis result**

Add to `ChatWorkflowTrace`:

```python
requested_model: str | None = None
actual_model: str | None = None
model_fallback_reason: str | None = None
```

Extend `SynthesisResult`:

```python
requested_model: str | None = None
actual_model: str | None = None
```

After a successful call, derive model provenance from the request-scoped client:

```python
model = getattr(client, "model", None)
requested_value = getattr(client, "requested_model", None)
requested_model = requested_value if isinstance(requested_value, str) else model if isinstance(model, str) else None
actual_value = getattr(client, "actual_model", None)
actual_model = actual_value if isinstance(actual_value, str) else requested_model
fallback_value = getattr(client, "fallback_reason", None)
model_fallback_reason = fallback_value if isinstance(fallback_value, str) else None
```

Return these fields from both normal synthesis and general chat. For local fallback after both LLMs fail, preserve `requested_model` but leave `actual_model=None` because no model generated the persisted answer.

- [ ] **Step 4: Wire trace creation without overwriting provider provenance**

In skill synthesis and `_persist_private_chat_turn`, copy requested/actual model fields into `ChatWorkflowTrace`. For LLM-only turns, set provider fields to `llm`, not model names:

```python
trace.requested_provider = "llm"
trace.actual_provider = "llm" if trace.llm_used else "local_fallback"
trace.requested_model = synthesis.requested_model
trace.actual_model = synthesis.actual_model
trace.model_fallback_reason = synthesis.fallback_reason if synthesis.llm_used else None
```

Acquisition provider metadata remains authoritative for requested/actual provider fields. Model fields are assigned independently before `_apply_trace_provenance()`.

- [ ] **Step 5: Regenerate OpenAPI and update the UI**

Run:

```bash
cd agentmesh-demo
npm run api:types
```

Update `ChatWorkflowTrace` TypeScript projection and add two rows to `Provenance`:

```tsx
{trace.requested_model ? <div className="flex gap-1"><dt>请求模型</dt><dd>{trace.requested_model}</dd></div> : null}
{trace.actual_model ? <div className="flex gap-1"><dt>实际模型</dt><dd>{trace.actual_model}</dd></div> : null}
```

Add Playwright assertions for both labels before and after reload.

- [ ] **Step 6: Run Task 2 gates and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_chat_flow.py tests/test_mvp_chat_threads.py tests/test_llm_failover.py -q
.venv/bin/ruff check agentmesh tests/test_chat_flow.py tests/test_mvp_chat_threads.py tests/test_llm_failover.py
cd agentmesh-demo && npm run test && npm run build && npm run test:e2e -- e2e/workspace-mvp.spec.ts
```

Commit:

```bash
git add agentmesh/models.py agentmesh/synthesis.py agentmesh/agents.py tests/test_chat_flow.py tests/test_mvp_chat_threads.py tests/test_llm_failover.py agentmesh-demo/src/api/generated/schema.ts agentmesh-demo/src/features/workspace/types.ts agentmesh-demo/src/components/workspace/ConversationThread.tsx agentmesh-demo/e2e/workspace-mvp.spec.ts
git commit -m "Expose LLM failover provenance"
```

---

### Task 3: Configure Both Models and Strengthen Real Provider Smoke

**Files:**
- Modify: `.env.example`
- Local-only modify: `.env` (ignored, never staged)
- Modify: `scripts/provider_smoke.py:134-184`
- Modify: `tests/test_mvp_provider_contracts.py:416-433`

**Interfaces:**
- Consumes: named model environment contract from `agentmesh.llm.model_config_from_env()`.
- Produces: `provider_smoke.py --llm` independently probes `primary` and `fallback`; local `.env` configures both LLMs and Embedding.

- [ ] **Step 1: Write independent LLM smoke tests**

Add these tests to `tests/test_mvp_provider_contracts.py`:

```python
def test_llm_smoke_probes_primary_and_fallback_independently(monkeypatch, capsys) -> None:
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


def test_llm_smoke_passes_only_when_both_models_are_real_and_ready(monkeypatch) -> None:
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
```

- [ ] **Step 2: Run smoke tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_mvp_provider_contracts.py -q
```

Expected: the new two-model assertions fail because `smoke_llm()` probes only one model.

- [ ] **Step 3: Implement two-model smoke**

Add `smoke_llm_model(model_id: str) -> ProviderStatus`. Resolve each model with `LLMClient.from_model_id(model_id, timeout_seconds=10.0)`, run a minimal acknowledgement request, and return names `llm:primary` and `llm:fallback`.

Change smoke handler results to accept one status or a list, flatten results in `main()`, and preserve the final rule:

```python
return 0 if all(status.ready and status.mode == "real" for status in statuses) else 1
```

For `--llm`, probe `AGENTMESH_MODEL_DEFAULT` and `AGENTMESH_LLM_FALLBACK_MODEL_ID` independently. Deduplicate identical IDs.

- [ ] **Step 4: Update the safe environment template**

Replace legacy single-model examples in `.env.example` with named `primary` and `fallback` variables, `AGENTMESH_LLM_FALLBACK_MODEL_ID=fallback`, and the full embedding endpoint variable. Use `replace-with-your-key`; never include the supplied value.

- [ ] **Step 5: Write the local ignored `.env` safely**

Before writing, confirm `.env` is ignored with:

```bash
git check-ignore .env
```

Write the approved internal gateway URL, primary model name, fallback model name, embedding model name, and the user-supplied credential into `.env` without echoing it to logs. Confirm only variable names, never values. Verify `git status --short` does not list `.env`.

- [ ] **Step 6: Run focused real probes**

Run:

```bash
.venv/bin/python scripts/provider_smoke.py --embedding --llm
```

Expected: three redacted lines, `embedding`, `llm:primary`, and `llm:fallback`, each with `configured=true`, `ready=true`, and `mode=real`.

- [ ] **Step 7: Commit tracked configuration and smoke changes**

```bash
git add .env.example scripts/provider_smoke.py tests/test_mvp_provider_contracts.py
git commit -m "Configure observable LLM failover"
```

Verify `.env` is not staged.

---

### Task 4: Verify Controlled Failover and Full Regression Gates

**Files:**
- Modify only if verification reveals a real defect in Task 1-3 files.
- Update: `docs/agentmesh-internal-pilot-mvp-todo.md` with redacted evidence.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: release evidence for primary, fallback, and Embedding without exposing credentials.

- [ ] **Step 1: Exercise primary success through the application**

Start FastAPI with the ignored `.env`, log in with an isolated demo database, send a normal chat message, and assert persisted trace fields show the primary model for both requested and actual model.

- [ ] **Step 2: Exercise a controlled primary failure**

Use a test-only injected primary client that raises `LLMRequestError("timeout", "Primary request timed out")` and a deterministic fallback client returning `"fallback answer"`. Do not corrupt the local primary credential. Assert the assistant response succeeds once, fallback is called once, and the persisted trace shows primary requested, fallback actual, and `timeout` reason.

- [ ] **Step 3: Run focused Provider and chat gates**

```bash
.venv/bin/python -m pytest tests/test_llm_failover.py tests/test_mvp_provider_contracts.py tests/test_chat_flow.py tests/test_mvp_chat_threads.py -q
.venv/bin/ruff check .
```

- [ ] **Step 4: Run full regression gates**

```bash
AGENTMESH_EMBEDDING_ENABLED=false .venv/bin/python -m pytest -q
cd agentmesh-demo
npm run api:types
npm run test
npm run build
npm run test:e2e
```

Expected: all existing gates pass without retries or flaky tests.

- [ ] **Step 5: Record redacted evidence and commit**

Record only model IDs, ready/mode, latency, and stable failure reason. Never record the key, headers, request body, response body, or vector.

```bash
git add docs/agentmesh-internal-pilot-mvp-todo.md
git commit -m "Record LLM failover verification"
```

- [ ] **Step 6: Rotate the exposed credential**

Ask the credential owner to rotate the key that appeared in chat. Update only the ignored `.env` with the replacement. Re-run `provider_smoke.py --embedding --llm` and require all three probes to remain real and ready before marking the external Provider gate complete.
