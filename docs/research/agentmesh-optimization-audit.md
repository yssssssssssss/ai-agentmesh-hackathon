# AgentMesh Optimization Audit

**Date:** 2026-08-21
**Scope:** Internal, read-only capability audit of this repo's own code — not a comparison against another project (see [`waku-agent-vs-agentmesh-comparison.md`](./waku-agent-vs-agentmesh-comparison.md) for that). Every finding below cites the exact file/line read in this session; nothing here is inferred from documentation.

---

## 1. Backend / data layer

1. **Single generic EAV table, no domain indexes except `artifacts`.** `agentmesh/store.py:386-393` defines one shared table — `records(collection, id, payload JSON, created_order)` — used for every entity type (tasks, chat threads, memory items, blackboard posts, users, …), distinguished only by the `collection` column. The only index is `idx_records_collection ON records(collection, created_order)` (`store.py:396`). All other filtering (user_id, project_id, status, scope) happens by deserializing the JSON payload in Python *after* the row is fetched — SQL can only narrow by collection, never by any domain field. `artifacts` is the one exception: it got dedicated columns and 5 indexes (`store.py:470-534`). **Consequence:** every list/search query for tasks, memory, blackboard, etc. is effectively a full collection scan; the cost grows linearly with total record count per collection and cannot be optimized by adding a WHERE clause.

2. **Confirmed N+1 query patterns.**
   - `agentmesh/routes/blackboard.py:260` (`post_visible_to_user`) calls `store.get_task` (`blackboard.py:426`) and `store.get_chat_thread` (`blackboard.py:397`) once per post inside a list comprehension — a fresh SQLite connection + query per post rendered.
   - `agentmesh/routes/blackboard.py:272-295` (`blackboard_task_cards`) iterates `reversed(store.tasks)` (an unfiltered full scan) and calls `store.get_chat_thread` twice per task (once directly, once again inside `task_visible_to_user`).
   - `agentmesh/store.py:7381-7398` (`list_user_memory_items`) does a full scan of the entire `user_memory_items` collection, filtered in Python. It's called 3× per `/api/memory/overview` request (`routes/memory.py:124-144`) and 2× per user inside the background summarizer's loop over `store.users` (`routes/memory.py:351-369`) — i.e. 2×W full collection scans per worker tick for W users.
   - **Consequence:** blackboard and memory endpoints scale poorly as post/task/user counts grow; each additional entity adds a full round trip, not O(1) lookup work.

3. **Connections opened per call, never explicitly closed, no WAL/busy_timeout.** `store.py:323-327` — `_connect()` calls `sqlite3.connect(self.db_path)` fresh every time (~91+ call sites use `with self._connect() as connection:`). `with connection:` in the stdlib only commits/rolls back the transaction — it does **not** close the connection, so every connection is left to Python's GC. No `PRAGMA journal_mode=WAL`, no `busy_timeout`, no `check_same_thread` override anywhere in the file. **Consequence:** under concurrent requests (the FastAPI default threadpool for sync routes, plus `asyncio.to_thread` background workers), SQLite's default rollback-journal mode locks the whole file for writers, so concurrent writes are liable to raise `database is locked` rather than queue gracefully. This is a structural risk, not yet load-tested in this session.

4. **Blocking sync calls inside `async def` route handlers.** `agentmesh/routes/agent_runs.py` — `start_agent_run`, `approve_agent_run_plan`, `retry_agent_run`, `cancel_agent_run` are declared `async def` but call `store.*` methods synchronously with no `asyncio.to_thread` wrapping (e.g. `agent_runs.py:117, 174, 245`). By contrast, background workers in `blackboard.py:119/210` and `memory.py:384` correctly offload blocking store calls via `asyncio.to_thread`. **Consequence:** these four handlers block the single asyncio event loop for the duration of their (potentially multi-query) SQLite work, stalling every other concurrent async request on the same worker process — unlike sync `def` routes, which FastAPI/Starlette automatically runs in a threadpool and don't have this problem.

5. **Brute-force, unbounded vector search.** `store.py:7779-7857` (`_vec_search`) fetches **every** row matching the scope/tenant filters from `records_vec` joined to `records_fts` — with no `LIMIT` before scoring — deserializes each embedding (4096-dim float32 = 16 KB per vector, per `embedding.py:44`), computes cosine similarity in a pure-Python loop (`embedding.py:123-129`), sorts, and only then truncates to the top 50 (`store.py:7856-7857`). The narrower `_search_skill_definitions` path at `store.py:1378-1396` does the same pattern at smaller scale. **Consequence:** query latency and memory grow linearly with the number of embedded records in scope, with no cap — this is fine at hackathon/demo scale but will degrade as the "Sources"/memory corpus grows, since there's no ANN index (e.g. sqlite-vec, FAISS) backing it.

---

## 2. LLM & agent orchestration

6. **`LLMClient.complete()` itself has no retry — but the layer above it does, and it's a failover, not a retry.** `agentmesh/llm.py:62-86` makes exactly one HTTP attempt per call and wraps any `httpx.TimeoutException`/`HTTPStatusError`/`RequestError` into `LLMRequestError`, no loop, no backoff — confirmed by direct read. One layer up, `agentmesh/synthesis.py:20-54` (`FailoverChatLLM`) does catch `LLMRequestError` where `reason in FAILOVER_REASONS` and retry once against a **different configured model** (primary→fallback) — a legitimate resilience pattern, but it only helps if a second model is configured, and it's not a retry against the *same* provider after a transient blip. `embed_text()` (`embedding.py:67-90`) has no equivalent — one attempt, log-and-return-`None` on any failure, no fallback embedding provider. **Consequence:** a transient network blip against a single-model deployment (the common case per the `AI_API_URL`/`AI_API_KEY` env-var story in `llm.py:145-149`) fails the whole chat turn with no recovery; embedding failures silently drop that record's vector with no retry at all.

7. **No streaming to the client despite the underlying SDK supporting it.** `agentmesh/agent_runtime/service.py:373-405` (`_run_streamed`) does call `Runner.run_streamed(...)` and iterate `stream_events()`, but only to log each event via `append_agent_run_event(..., "sdk_stream_event", ...)` — the full response is still buffered before returning. `routes/chat.py:145` (`create_chat_message`) calls `agent.handle_chat(...)` as a single blocking call returning a complete `ChatResponse`; no `StreamingResponse`/SSE found in `routes/chat.py` or `routes/agent_runs.py`. **Consequence:** users wait for the full LLM turnaround with zero partial-token feedback, even though the agent SDK already streams internally — the token stream is captured for audit logging and then thrown away instead of being forwarded to the client.

8. **Prompt construction is duplicated across 10+ call sites with no shared builder.** Three separate, non-unified prompt subsystems, confirmed by direct reading: (a) `agentmesh/synthesis.py:build_llm_prompt()` (lines 204-245) + inline system prompt (124-130), used only for the main chat-synthesis path; (b) at least 7 standalone inline prompts in `agentmesh/agents.py` with no shared template — `_INTENT_CLASSIFIER_SYSTEM_PROMPT` (249-265), `_general_chat_answer()` (2038-2042), `_llm_delegated_answer()` (1728-1732), `_llm_marketplace_signal()` (1797-1801), `_match_signal()` (1895-1898), `_generate_brief_draft_with_llm()` (2242-2246); (c) a third pathway in `agentmesh/skill_runtime/planner.py` (`_INTENT_INSTRUCTIONS` 20-25, `_PLANNER_INSTRUCTIONS` 27-38) and `skill_runtime/synthesis.py` (`_SYNTHESIS_INSTRUCTIONS` 10-14). Some prompts are Chinese-only, others English-only — an observed, not hypothetical, drift. **Consequence:** any future change to citation format, safety framing (e.g. the "evidence is untrusted data" framing in `research_orchestration/actors.py:374-389`), or language policy has to be replicated by hand across 10+ sites; nothing enforces they stay in sync.

9. **Token/cost budgeting is character-based, not token-based, and inconsistent within one file.** `agentmesh/agents.py:125-126` defines `MAX_HISTORY_MESSAGES = 10` and `MAX_HISTORY_CHARS = 4000`, applied in `_get_thread_history()` (2153-2171). But `_general_chat_answer()` (~line 2018) independently uses `history[-6:]` — a different, hardcoded window than the 10-message constant used elsewhere in the same file, with no shared source of truth. All budgets are character counts, not tokens — for CJK text (this codebase's UI and much of its prompt content is Chinese) that's a meaningfully inaccurate proxy for actual token cost. No tokenizer (e.g. tiktoken) is used anywhere. **Consequence:** history truncation is inconsistent between chat paths and imprecise as a cost/context-window control, especially for Chinese-heavy conversations.

10. **Embedding batching not used despite a batch-shaped function existing.** `embedding.py:105-111` — `embed_texts(texts)` loops and calls `embed_text` one at a time, issuing N sequential HTTP round trips instead of one batched request (the underlying API takes an `input` field per `embed_text`'s payload at `embedding.py:78`, which is commonly batchable on OpenAI-compatible embedding endpoints). **Consequence:** any bulk ingestion path (e.g. document upload → chunk → embed) pays N network round-trips serially instead of 1; this is the dominant latency cost of ingesting a multi-chunk document today.

11. **Silent truncation of embedding input, and silent failures with no logging at several secondary LLM call sites.** `embedding.py:78` truncates to `text[:2000]` chars with no signal to the caller. Separately, in `agentmesh/agents.py`, four call sites — `_llm_delegated_answer()` (1737-1740), `_llm_marketplace_signal()` (1805-1808), `_match_signal()` (1900-1903), `_generate_brief_draft_with_llm()` (2257-2259) — use bare `except Exception: return None/False/fallback` with **no logging at all**, unlike `_try_extract_skills()` (2437-2452) in the same file, which does `logger.warning` on failure. **Consequence:** longer chunks silently lose tail content in embeddings, and a real bug (e.g. a `TypeError` introduced by a future change) at those four sites is indistinguishable from an expected provider outage — both just silently degrade with zero trace.

12. **Positive finding — provider error handling is well-designed where it's used.** `agentmesh/provider_status.py:110-153` maps exceptions to stable categories (`timeout`, `auth_error`, `http_XXX`, `malformed_response`, `unavailable`, `provider_error`) and redacts bearer tokens/API keys from anything logged (`redact_sensitive_text`/`redact_url`). `agentmesh/agent_runtime/session.py` correctly wraps every sync repository call in `await asyncio.to_thread(...)`, and `agentmesh/ingestion.py`'s `BoundedIngestionExecutor` (43-81) explicitly offloads chunking/embedding to a `ThreadPoolExecutor`. Noted so the audit isn't read as uniformly negative — these are the patterns the sloppier call sites above should be made to match.

---

## 3. Frontend

13. **No ESLint configuration at all.** `find agentmesh-demo -maxdepth 1 -iname "eslint*"` returns nothing, and `package.json` (`agentmesh-demo/package.json:6-14`) has no `lint` script. TypeScript is `strict: true` (`tsconfig.json`), which catches type errors, but nothing enforces React hooks rules (`exhaustive-deps`), unused-variable hygiene, or import consistency — `tsc -b` in the CI `build` step (`.github/workflows/ci.yml`, frontend job) only type-checks, it doesn't lint. **Consequence:** hook-dependency bugs (stale closures, missing deps) and dead code can land without any automated gate catching them — currently unenforced.

14. **`d3-force` + `@types/d3-force` are dependencies but only referenced from one file.** `grep -rln "d3-force" agentmesh-demo/src/` finds a single usage site: `agentmesh-demo/src/features/market/components/graph/useForceSimulation.ts`. This is a real, in-tree usage (not dead), but it's worth flagging: `d3-force` is a non-trivial physics-simulation dependency pulled into the bundle for one graph visualization in the `market` feature — confirm it's still reachable/used from a live route before assuming it's load-bearing for the current chat-workspace-focused surface area under active development.

---

## 4. Testing

15. **Zero skipped or xfail tests.** `grep -rln "pytest.mark.skip\|pytest.mark.xfail" tests/` returns nothing across 84 test files. This is a positive signal (no silently-disabled coverage), not a gap — noted for completeness since it's the kind of thing that's easy to assume is bad without checking.

16. **CI backend job disables embeddings.** `.github/workflows/ci.yml`, `backend` job: `AGENTMESH_EMBEDDING_ENABLED: "false"`. Same for the `e2e` job. This means the vector-search code paths described in findings #5 and #10 above are **never exercised in CI** — they only run when a developer has `AGENTMESH_EMBEDDING_ENABLED=1` and real embedding credentials locally. **Consequence:** regressions in embedding/vector-search code (including the brute-force scaling issue in #5) would not be caught by CI at all; there's no embedding-path test coverage running automatically today.

17. **DB isolation between tests relies on per-file discipline, not a global guard.** `tests/conftest.py:10-14` uses one shared, disk-backed SQLite temp file for the whole session (not `:memory:`); isolation between tests depends on each test file's own `setup_function` calling `store.reset()`, confirmed present in most sampled files but with no autouse global reset in `conftest.py` itself. **Consequence:** a new test file that forgets its own `setup_function` reset can silently leak state into other tests — the safety net is convention, not enforcement. Separately, a positive finding worth recording: the eval harness (`eval/`) is genuinely substantial, not a stub — three layers (11-scenario MVP chat eval with 7 quantitative gates; 40-case skill-retrieval eval with recall/latency gates plus 3 adversarial security probes; 20-case research-orchestration eval with a 5-dimension weighted human rubric and 10 machine gates) — this is one of the stronger-engineered parts of the codebase and should not be assumed thin.

---

## 5. Security

18. **No brute-force protection on `/api/auth/login`.** `agentmesh/routes/auth.py:44-57` — `login()` checks `verify_password` (PBKDF2-HMAC-SHA256, 120,000 iterations, `agentmesh/auth.py:19-22`) with no attempt counter, lockout, or rate limit. Grepping the whole `agentmesh/` tree for `failed_login|login_attempts|too_many|429` finds nothing auth-related (the one `429` hit is in `web_research.py:143`, an unrelated external-crawl retry-on-429 path). **Consequence:** an attacker with network access to `/api/auth/login` can attempt unlimited password guesses against any known `user_id`; the 120K PBKDF2 iterations slow each guess (~tens of ms) but do not stop sustained automated guessing.

19. **Session cookie `secure` flag defaults to insecure unless explicitly opted in.** `agentmesh/auth.py:61` — `secure=os.getenv("AGENTMESH_COOKIE_SECURE") == "1"`. Same pattern in `routes/auth.py:92` for the OAuth state cookie. If this env var is not set in a deployment (easy to forget), session and OAuth-state cookies are sent over plain HTTP. `samesite="lax"` is set correctly, which does mitigate basic cross-site POST CSRF. **Consequence:** this is a config footgun, not a code bug — worth a startup-time warning/assertion when running outside `127.0.0.1`/localhost rather than a silent default.

20. **No CSRF token — relies entirely on `SameSite=Lax` with no redundancy.** Confirmed by direct grep: no CSRF token generation/validation anywhere in `agentmesh/routes/`. All state-changing endpoints are POST/PATCH/DELETE (not state-changing GETs), so `SameSite=Lax` should hold in modern browsers, but there is zero defense-in-depth (no Origin/Referer check) if that single control ever fails — e.g. via a browser bug, a `SameSite=None` misconfiguration, or a legacy-browser client. **Consequence:** the app has exactly one CSRF defense layer with no fallback.

21. **Cross-tenant IDOR: 5 confirmed authorization gaps across route handlers**, found via a full sweep of `routes/*.py` against `permissions.py`'s ownership/workspace checks:
    - **HIGH** — `agentmesh/permissions.py:115-145` (`ensure_can_update_memory`) never checks `workspace_id`, only owner/scope/role. A `team_lead`/`admin` in one workspace can mutate another workspace's memory items.
    - **HIGH** — `agentmesh/agents.py:293-299` (`get_agent_memory_binding`) has zero ownership check at all (sibling functions in the same file do check) — any authenticated user can read any agent's memory-binding configuration, regardless of who owns that agent.
    - **HIGH** — `agentmesh/routes/workspace.py:155-160` and `:175-180` (`workspace_detail`, `project_detail`) perform no membership check — any authenticated user can read any workspace's or project's metadata by guessing/enumerating IDs.
    - **MEDIUM** — `agentmesh/routes/blackboard.py:649-667` (`enqueue_auto_blackboard_post`) skips the workspace check specifically for `TEAM_LEAD`/`ADMIN` roles, inconsistent with the rest of the file.
    - **MEDIUM** — `agentmesh/permissions.py:93-104` (`ensure_can_manage_agent`) never checks `workspace_id` for public agents — may be intentional, but is inconsistent with the equivalent check in `resolve_handoff_recipient`, so it's unclear whether the omission is deliberate.
    - Everything else checked in this sweep — chat, agent_runs, documents, inbox, data_sources, market, artifacts, users routes — was correctly scoped. **Consequence:** the two HIGH findings are directly exploitable cross-tenant data exposure/mutation bugs in a multi-tenant, multi-workspace product; they should be treated as the most urgent items in this entire audit, ahead of the performance findings in §1.

22. **Hardcoded demo credentials, gated but present in source.** `agentmesh/seed.py:84-88` hardcodes demo passwords (`admin123`, `lead123`, `designer123`) for seeded demo users, only activated when `AGENTMESH_DEMO_MODE=1` (`seed.py:406-407`). Inactive by default, but a real risk if that flag is ever accidentally set in a production config, since the values are static and now public (this audit). **Consequence:** low likelihood, high severity if it ever happens — worth a startup assertion that refuses to boot with `AGENTMESH_DEMO_MODE=1` when `AGENTMESH_COOKIE_SECURE` (or an equivalent "is this prod" signal) is also set.

23. **Positive findings — password hashing and token generation are done correctly.** PBKDF2-HMAC-SHA256 at 120,000 iterations with a 16-byte salt and constant-time comparison (`auth.py:19-38`) is a solid, non-weak scheme. All session tokens, OAuth state values, and fallback IDs use the `secrets` module (CSPRNG) — no predictable `random`/bare-`uuid4` usage found anywhere in the auth path. Noted so the two HIGH IDOR findings above aren't read as "the whole auth system is weak" — the cryptographic primitives are sound; the gaps are in authorization logic, not cryptography.

---

## 6. Dead code / duplication

24. **Near-identical `_visible_*` ownership-check helpers duplicated per route file** instead of a shared dependency: `chat.py:42`, `agent_runs.py:40` and `:53`, `blackboard.py:396` and `:425`. Same shape (fetch entity, check membership/ownership, raise 404 if not visible), reimplemented per file. **Consequence:** a fix to the visibility logic (e.g. a new sharing rule) has to be applied in 4+ places by hand; nothing enforces they stay in sync — and this exact category of duplication is very likely *why* the IDOR gaps in finding #21 exist (checks copy-pasted instead of shared, so they drift).

25. **`agent_runs.py` re-imports `from agentmesh.routes.chat import agent` inside 4 separate function bodies** (lines 110, 239, 317, 347, per the delegated sub-audit) instead of a single module-level import. Not a correctness bug (Python caches imports), but it's a repeated pattern that suggests the module boundary between `chat.py` and `agent_runs.py` wants tidying — likely a circular-import workaround rather than a deliberate choice.

26. **Overly broad exception handling in the chat path.** `routes/chat.py:166` — a bare `except Exception` catches everything (including genuine bugs, not just expected failure modes) and records them into the chat-turn failure audit trail before re-raising. **Consequence:** unexpected defects (e.g. a `TypeError` from a code change) get logged identically to ordinary, expected chat failures (e.g. LLM timeout), making it harder to distinguish "known failure mode" from "new bug" by scanning the audit trail alone.

---

## 7. DX / CI

27. **CI is genuinely solid where it runs.** `.github/workflows/ci.yml` has 4 jobs: `backend` (ruff + pytest, excluding frontend-route tests), `frontend` (schema-drift check via `git diff --exit-code` on the generated OpenAPI types, vitest, `tsc -b` build), `e2e` (Playwright), and `secret-scan` (gitleaks). This is a real, automated gate — noted as a strength, not a gap, correcting any assumption from the external comparison doc that CI is thin. The one real gap: no `eslint` step (see #13), and embeddings are off in every job (see #16).

28. **SQL injection surface checked — no reachable injection found.** 4 f-string-built SQL sites exist (`store.py:848/861`, `1607`, `6646`, `373/376/378`); all were verified to interpolate only hardcoded constants (a fixed `_FTS_COLLECTIONS` tuple, a placeholder-count string with values bound via `?`, an enum-keyed dict lookup, and startup-only schema-migration literals) — none interpolate HTTP-supplied values directly into SQL text. This is a confirmed **non-finding**, included because the audit explicitly checked for it.

---

## Top 5 priority

Ranked by severity and impact-to-effort ratio — the two HIGH-severity cross-tenant bugs come first regardless of effort, then cheapest fixes with the clearest blast radius:

1. **#21 — Fix the two HIGH-severity IDOR gaps**: `permissions.py:115-145 ensure_can_update_memory` (add `workspace_id` check) and `agents.py:293-299 get_agent_memory_binding` (add the ownership check every sibling function already has), plus `routes/workspace.py:155-180` (add membership checks to `workspace_detail`/`project_detail`). These are live, exploitable cross-tenant data exposure/mutation bugs in a multi-workspace product — highest severity finding in this audit, fix before anything else here.
2. **#3 — Add `PRAGMA journal_mode=WAL` and a `busy_timeout`** to `_connect()` in `store.py:323-327`. One-line change, directly reduces `database is locked` risk under any concurrent load, and is the standard fix for exactly this SQLite access pattern.
3. **#18 — Add a login attempt counter/lockout (or at minimum a rate limit) to `/api/auth/login`.** Security-relevant, currently zero protection, and the codebase already has an audit-event mechanism (`create_audit_event`) that could record failed attempts with minimal new plumbing.
4. **#4 — Wrap the blocking `store.*` calls in `agent_runs.py`'s async handlers with `asyncio.to_thread`**, matching the pattern already used correctly in `blackboard.py`/`memory.py`. Small, mechanical fix; removes an event-loop-stalling bug from exactly 4 handlers.
5. **#5 + #16 — Cap `_vec_search`'s row fetch with a `LIMIT` before scoring, and turn embeddings on in at least one CI job.** Bounds the worst-case query cost today, and closes the current CI blind spot on the entire vector-search code path (which is currently untested in CI at all).

Also worth tracking near-term: #2 (batch the N+1 lookups in `blackboard.py`), #7 (surface the SDK's existing token stream to the client instead of discarding it), #8 (unify prompt construction), #9 (fix the `history[-6:]` vs `MAX_HISTORY_MESSAGES=10` inconsistency). Lower priority: #13 (add ESLint), #10 (batch embedding calls), #19 (warn on insecure cookie config), #20 (add CSRF defense-in-depth), #22 (startup guard against demo-mode-in-prod), #24/#25/#26 (consolidation/cleanup, no urgency).

---

## Sources

All findings above are based on direct reads of the following files in this repo during this session, plus three delegated sub-audits whose findings are folded in throughout (backend store/routes → §1 items 2, 4 and §6 items 24-26; LLM/agent orchestration → §2 items 6-12; security/testing → §4 item 17 and §5 items 20-23):

- `agentmesh/store.py` (targeted reads: header/imports, schema block ~lines 320-760, 912-928, 1355-1398, 7355-7420, 7770-7860, plus greps across the full file)
- `agentmesh/models.py`, `agentmesh/agents.py` (targeted reads and structural context)
- `agentmesh/llm.py` (full file, 330 lines)
- `agentmesh/auth.py` (full file, 92 lines)
- `agentmesh/routes/auth.py` (full file, 277 lines)
- `agentmesh/vector_index.py` (full file, 224 lines)
- `agentmesh/embedding.py` (full file, 129 lines)
- `agentmesh/synthesis.py`, `agentmesh/agent_runtime/service.py`, `agentmesh/agent_runtime/session.py`, `agentmesh/skill_runtime/synthesis.py`, `agentmesh/skill_runtime/planner.py`, `agentmesh/provider_status.py`, `agentmesh/ingestion.py`, `agentmesh/research_orchestration/actors.py` (via delegated sub-audit)
- `agentmesh/permissions.py`, `agentmesh/data_authorization.py`, `agentmesh/seed.py`, `agentmesh/risk.py`, `agentmesh/routes/deps.py`, `agentmesh/routes/workspace.py` (via delegated sub-audit)
- `agentmesh/routes/blackboard.py`, `agentmesh/routes/agent_runs.py`, `agentmesh/routes/memory.py`, `agentmesh/routes/chat.py` (via delegated sub-audits, cross-checked against this session's greps)
- `tests/conftest.py`, sampled `tests/test_*.py` files, full `eval/` directory including `eval/research_orchestration/` (via delegated sub-audit)
- `.github/workflows/ci.yml` (full file)
- `agentmesh-demo/package.json` (full file)
- `agentmesh-demo/tsconfig.json` (strict-mode check)
- `agentmesh-demo/src/features/workspace/queries.ts`, `api.ts`, `agentmesh-demo/src/pages/Workspace.tsx` (line counts, polling pattern grep)
- Repo-wide greps: `retry|Retry|backoff`, `failed_login|login_attempts|too_many|429`, `pytest.mark.skip|xfail`, `d3-force` usage, ESLint config presence, CSRF token usage
