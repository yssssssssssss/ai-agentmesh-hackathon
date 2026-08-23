# Research Provider Readiness, Failure-State, and Artifact Safety Fix

Status: Implemented and verified locally; production rollout remains governed by the existing release gate
Date: 2026-08-23
Scope: research-v2 request admission, terminal-state projection, Workspace failure UX, real Web acquisition, and Artifact-safe persistence

## Problem statement

An eligible competitive-research request can currently receive `202 Accepted`, persist a research-v2 Run, and then fail during asynchronous plan compilation before any Plan, Attempt, or Tool Invocation exists. When no real research Provider is configured, `ToolGateway.describe("web_research")` reports a fake and unavailable runtime. The capability resolver correctly fails closed with `tool_runtime_not_real`, but the Workspace renders the terminal Workflow as “研究已结束” and labels it “计划预览”. This hides the actual failure and makes an empty terminal projection look like a successful result.

The observed failure path is:

```text
Workspace POST /api/agent/runs
  -> route selects research-v2 / execute
  -> Run is persisted and 202 is returned
  -> requirement is prepared and persisted
  -> resource snapshot is sealed
  -> plan compilation resolves Tool capability
  -> web_research is fake/unavailable
  -> Run becomes failed(tool_runtime_not_real)
  -> projection omits Run status/error
  -> UI shows generic terminal/empty-report copy
```

## Goals

1. Reject a new research-v2 request before persistence when its required real Web Research runtime is unavailable.
2. Preserve the authoritative capability check during plan compilation so a readiness race still fails closed.
3. Make every accepted Run's terminal outcome and stable error code visible in the research aggregate and UI.
4. Restore a verified real-provider path for local development without committing credentials or test data.
5. Preserve historical Run identity, idempotent replay, owner scoping, and all existing approval gates.
6. Optionally enrich Tavily results with bounded Firecrawl page content while preserving Tavily snippets on enrichment failure.
7. Redact credentials, local paths, email addresses, and mobile numbers before Provider content reaches durable Artifacts.
8. Keep generated Claim roles aligned with the downstream evidence contract so valid real runs do not fail after Tool completion.

## Non-goals

- Do not fall back to Mock evidence, v1, or research-v3 after selecting research-v2.
- Do not cut production traffic over to research-v3.
- Do not add a queue, worker service, database migration, automatic retry, or new Provider abstraction.
- Do not rewrite or delete existing failed Runs.
- Do not treat O2 `metasearch` as general Web Research; its supported domains are SKU, hotel, and takeout.
- Do not enable production `execute` before the release gates in `docs/runbooks/research-orchestration-v2.md` are approved.

## Constraints and decisions

### Provider choice

Use the existing Tavily adapter as the supported general Web Research path. It already implements the required structured result contract and is the Provider named by the research-v2 runbook. The environment owner supplies `AGENTMESH_TAVILY_API_KEY` through a secret manager or ignored local `.env`; the key must never enter Git, logs, fixtures, screenshots, or verification documents.

Required existing settings:

- `AGENTMESH_WEB_PROVIDER=tavily`
- `AGENTMESH_TAVILY_API_URL=https://api.tavily.com/search`
- `AGENTMESH_TAVILY_API_KEY` set to an approved secret
- `AGENTMESH_AGENT_RUNTIME=v2`
- `AGENTMESH_SKILL_ORCHESTRATION=execute` only in an authorized, isolated environment

Optional Firecrawl enrichment settings:

- `AGENTMESH_FIRECRAWL_ENABLED=true`
- `AGENTMESH_FIRECRAWL_API_URL=https://api.firecrawl.dev/v2/scrape`
- `AGENTMESH_FIRECRAWL_API_KEY` set to an approved secret for Firecrawl Cloud
- `AGENTMESH_FIRECRAWL_MAX_PAGES` and `AGENTMESH_FIRECRAWL_MAX_CONTENT_CHARS` kept within the code-enforced bounds

Tavily remains the discovery Provider. Firecrawl is a bounded content fetcher, not a replacement search Provider. A Firecrawl request failure keeps the original Tavily snippet and records a stable fallback reason without persisting the response body.

`AGENTMESH_WEB_PROVIDER=mock` is not a fix and must continue to fail the real-runtime gate. O2 is installed locally, but the currently available `metasearch` capability is not suitable for generic product research. `opencli` and `agent-browser` executables exist, but their default command contracts do not match `CommandWebSearchProvider`; integrating either is separate work.

### Admission behavior

The backend remains authoritative. The route must not rely on a browser-side health flag because Provider health can change between rendering and submission.

The request order remains:

```text
client-turn replay
  -> request classification and writer selection
  -> runtime existence check
  -> research-v2 Provider readiness check
  -> thread creation
  -> Run/workflow persistence
  -> asynchronous planning
```

Replay stays before readiness checking so an existing `client_turn_id` always returns its immutable original Run. Readiness checking stays before thread creation so a rejected request leaves no empty Thread, Run, event, or background task.

The runtime readiness result uses the existing `ToolRuntimeDescriptor` and accepts only `execution_mode=real` plus `health_state=healthy`. Plan compilation keeps its existing full capability resolution; the admission check is an early diagnostic guard, not a replacement for the authoritative snapshot.

### API behavior

Add `status` and `error_code` to `ResearchRunProjection`, populated from the same `AgentRun` contained in the Workflow context. This keeps the aggregate self-contained and avoids reconciling two independently refreshed responses in the UI.

When admission fails, `POST /api/agent/runs` returns HTTP 503 with a structured `detail` containing:

- stable `code`: `tool_runtime_unregistered`, `tool_runtime_not_real`, or `tool_runtime_unhealthy`;
- safe user-facing `message` without Provider payloads, commands, credentials, or internal paths.

This is an additive projection change and a new documented failure response. No persisted schema changes are required.

### UI behavior

The Workspace derives terminal copy from `projection.status`, not from the presence of an Attempt:

- `completed`: “研究结果已就绪”;
- `failed`: “研究执行失败”, with a safe explanation and technical error code;
- `cancelled`: “研究已安全终止”;
- nonterminal with a Plan and no Attempt: “计划预览”;
- nonterminal without a Plan: “准备中”.

A failed Run must not render the generic “本次运行未生成可展示的最终 Report” message as though it were an empty successful result. Unknown error codes receive a generic failure message while retaining the stable code in technical details. The failed request remains manually resubmittable after configuration is repaired; refresh and SSE reconnect remain read-only.

## Implementation plan

Each phase is independently mergeable and leaves the application in a usable state.

### Phase 1 — Truthful terminal projection and UI

- [x] Add required `status: AgentRunStatus` and optional `error_code` fields to `ResearchRunProjection` in `agentmesh/research_orchestration/api.py`.
- [x] Populate both fields from `WorkflowContext.run` in `ResearchWorkflowService._projection`.
- [x] Regenerate `agentmesh-demo/src/api/generated/schema.ts` with the repository's `api:types` command.
- [x] Update `ResearchPreview` to render failed, cancelled, completed, planning, and execution states explicitly.
- [x] Add a small exhaustive error-code-to-message mapping for known research readiness failures; use a generic message for unknown codes.
- [x] Update `ResearchResults` so an empty-report message is shown only for a completed Run, not for a failed Run.
- [x] Keep raw Provider responses and sensitive configuration out of all UI messages.
- [x] Add backend projection tests and frontend rendering tests for failed-without-Attempt, completed, cancelled, and unknown-error cases.

Phase 1 is useful alone: already-persisted and future asynchronous failures become honest and actionable.

### Phase 2 — Fail-fast request admission

- [x] Give `ResearchRuntime` a narrow readiness method backed by the same `ToolGateway` instance used for planning and execution.
- [x] Return one stable readiness error code for missing, fake, or unhealthy `web_research` descriptors.
- [x] In `start_agent_run`, run the readiness check only after client-turn replay and writer selection, but before `_thread(...)` and Run persistence.
- [x] Map readiness failures to HTTP 503 with structured, redacted `detail`.
- [x] Preserve the existing capability resolver in plan compilation to catch Provider failure after admission.
- [x] Extend the frontend API error formatter to display structured `detail.message` while retaining its generic fallback.
- [x] Test that unavailable and Mock runtimes create no Thread, Run, event, Artifact, or background task.
- [x] Test that a healthy real descriptor preserves the existing 202 flow.
- [x] Test that replay of an existing client turn precedes and bypasses the live readiness check.
- [x] Test the readiness race: a Run accepted while healthy may still become terminal failed if the authoritative planning check later fails, and the UI must expose that failure.

Phase 2 is useful alone: new requests fail immediately and do not leave misleading partial records.

### Phase 3 — Local environment recovery and real-provider verification

- [x] Stop only the backend process listening on port 8010.
- [x] Move the copied `.venv` to a recoverable backup, recreate `.venv` at its final path with `/opt/homebrew/bin/python3 -m venv .venv`, and install `.[dev]`.
- [x] Verify `.venv/bin/uvicorn` references the current repository and imports `uvicorn`, `agents`, and `agentmesh` successfully.
- [x] Have the environment owner inject approved Provider keys without committing or printing them.
- [x] Create an isolated temporary directory and set its SQLite file as `AGENTMESH_DB_PATH` for Provider validation.
- [x] Run `.venv/bin/python scripts/provider_smoke.py --web`; require a real, ready Provider with redacted output.
- [x] Start the backend against the same isolated database and run `.venv/bin/python scripts/research_orchestration_smoke.py --database <isolated-db>`.
- [x] Verify Plan confirmation and Tool approval remain distinct, Provider calls remain zero before approval, and a final Report contains verifiable Evidence.
- [x] Restart the isolated backend and run the smoke verifier with the emitted Run ID to prove durable recovery.
- [x] Restore the normal local database only after the isolated smoke succeeds.
- [x] Submit a new task; do not mutate or attempt to resume the previously failed pre-Plan Run.
- [x] Keep `execute` limited to authorized local/isolated validation until the runbook's human Release Gate is complete.

Phase 3 restores actual research execution. Provider credentials remain only in the ignored local `.env`; smoke output contains status and stable error codes, never secret values or raw Provider bodies.

### Phase 4 — Operator documentation

- [x] Update `.env.example` to state that research-v2 planning requires a real, healthy Web Provider and that `mock` is rejected.
- [x] Update `docs/runbooks/research-orchestration-v2.md` with the 503 admission behavior, readiness checks, failed-Run resubmission rule, and isolated Provider smoke sequence.
- [x] Document the safe rollback: set `AGENTMESH_SKILL_ORCHESTRATION=off`, restart, and verify historical research-v2 reads without creating new research-v2 Runs.

Phase 4 is useful alone: operators can distinguish configuration failure from workflow failure without inspecting SQLite.

### Phase 5 — Bounded content enrichment and Artifact safety

- [x] Add optional Firecrawl REST enrichment behind explicit environment configuration.
- [x] Reject literal local/private Firecrawl targets and URLs containing user information.
- [x] Bound scraped page count and persisted excerpt length.
- [x] Fall back to the original Tavily snippet on Firecrawl timeout, quota, rate-limit, or malformed-response failures.
- [x] Redact credentials, host-local paths, email addresses, and mobile numbers from title, URL, and snippet fields before constructing `AcquisitionResult`.
- [x] Record only stable Provider/fallback metadata and whether sensitive content was redacted.
- [x] Add deterministic tests for request shape, failure classification, fallback behavior, configuration, health output, and sensitive-content removal.
- [x] State the Fact, Inference, and Recommendation evidence rules in the actual model instructions.
- [x] Conservatively reclassify parent-backed generated Facts as Inferences before sealing; never invent or attach Evidence.
- [x] Add a production-boundary regression test for generated Claim classification.

Phase 5 removes the need to weaken Artifact sealing: unsafe raw Provider content is normalized before persistence, while the Artifact store remains fail-closed as a final boundary.

## Expected file impact

This plan intentionally affects more than eight files because it crosses a public API projection, backend admission, frontend rendering, generated types, tests, and operator documentation. It adds no service and no database table.

Backend:

- `agentmesh/research_orchestration/runtime.py`
- `agentmesh/research_orchestration/actors.py`
- `agentmesh/research_orchestration/api.py`
- `agentmesh/research_orchestration/workflow.py`
- `agentmesh/routes/agent_runs.py`
- `agentmesh/routes/health.py`
- `agentmesh/tool_runtime/guardrails.py`
- `agentmesh/web_research.py`

Frontend:

- `agentmesh-demo/src/api/generated/schema.ts`
- `agentmesh-demo/src/features/workspace/queries.ts`
- `agentmesh-demo/src/components/workspace/ResearchPreview.tsx`
- `agentmesh-demo/src/components/workspace/ResearchResults.tsx`

Tests:

- `tests/test_research_orchestration_routes.py`
- `tests/test_research_orchestration_workflow.py`
- `tests/test_research_orchestration_actors.py`
- `tests/test_research_preview.py`
- `tests/test_research_v3_preview_composition.py`
- `agentmesh-demo/src/features/workspace/queries.test.tsx`
- `agentmesh-demo/src/features/workspace/research.test.tsx`
- `agentmesh-demo/src/components/workspace/ResearchPreview.test.tsx`
- `agentmesh-demo/src/components/workspace/ResearchExecution.test.tsx`
- `tests/test_health.py`
- `tests/test_web_research.py`

Documentation:

- `.env.example`
- `README.md`
- `docs/runbooks/research-orchestration-v2.md`

## Verification matrix

| Case | Expected result |
| --- | --- |
| Web Provider unset | POST returns 503; no durable state is created |
| Web Provider is Mock | POST returns 503 with `tool_runtime_not_real` |
| Real Provider command missing or unhealthy | POST returns 503 with `tool_runtime_unhealthy` |
| Real Provider healthy | POST returns 202 and creates exactly one Run |
| Duplicate `client_turn_id` | Returns the original Run regardless of current Provider health |
| Provider fails after admission | Accepted Run becomes `failed`; aggregate and UI expose its error code |
| Failed before Plan/Attempt | UI shows failure, not “研究已结束” or “计划预览” |
| Completed Run | Existing report, Evidence, Claim, review, and provenance views remain unchanged |
| Cancelled Run | Existing safe-termination behavior remains unchanged |
| Refresh/SSE reconnect | Read-only; creates no Run, command, or Provider invocation |
| `off` rollback | No new research-v2 Run; historical Runs remain readable |
| Firecrawl succeeds | Bounded page Markdown replaces only the selected Tavily snippets |
| Firecrawl fails | Original Tavily snippet remains usable; stable fallback metadata is recorded |
| Provider content contains sensitive text | Sensitive values are redacted before Artifact construction and sealing |
| Model labels a parent-backed Claim as a Fact | Claim is conservatively treated as an Inference; no Evidence is fabricated |

## Verification commands

Run deterministic checks without real external calls:

```bash
.venv/bin/python -m pytest \
  tests/test_research_orchestration_routes.py \
  tests/test_research_orchestration_workflow.py \
  tests/test_research_orchestration_planning.py
.venv/bin/ruff check .
npm --prefix agentmesh-demo test
npm --prefix agentmesh-demo run api:types
npm --prefix agentmesh-demo run build
```

Run authorized external checks only with an isolated database and approved credentials:

```bash
.venv/bin/python scripts/provider_smoke.py --web
.venv/bin/python scripts/research_orchestration_smoke.py --database <isolated-db>
.venv/bin/python scripts/research_orchestration_smoke.py \
  --database <isolated-db> \
  --verify-run-id <redacted-run-id>
```

Manual acceptance:

- [x] Missing Provider produces an immediate visible error and preserves the user's draft.
- [x] No misleading “研究已结束”, “计划预览”, or empty successful-result card appears for a failed Run.
- [x] A real Run reaches Plan confirmation, then separate Tool approval, then execution and final Report.
- [x] Durable re-read restores the same completed Run and does not duplicate Provider work.
- [x] No key, prompt, Provider body, cookie, or local database appears in Git status or test artifacts.

## Rollback

Code rollback is additive and requires no data migration: revert the projection/UI/admission commits and regenerate frontend API types. Operational rollback sets `AGENTMESH_SKILL_ORCHESTRATION=off` and restarts the backend. Historical research-v2 Runs remain readable, while new research requests route according to the existing `off` policy. Never rewrite failed rows or downgrade the database.

## Risks and mitigations

- **Provider readiness changes after admission:** retain the authoritative capability check during planning and surface terminal failure honestly.
- **External Provider outage or rate limiting:** fail closed; never substitute Mock evidence or silently retry a sent operation.
- **API/client drift:** regenerate OpenAPI types and run both backend and frontend contract tests in the same change.
- **Credential leakage:** use ignored environment injection and redacted smoke output only.
- **Sensitive Provider content:** redact before persistence and keep Artifact sealing fail-closed as defense in depth.
- **Firecrawl partial failure:** preserve the original Tavily snippet and record only stable fallback metadata.
- **Model Claim-role drift:** constrain the live prompt and downgrade parent-backed generated Facts to Inferences before validation.
- **Release-policy conflict:** the repository runbook says `execute` is not production-authorized yet; keep real execution in an isolated environment until release owners approve the existing gates.
- **Document drift:** this file is the sole implementation checklist; do not create a parallel `TODO.md`.

## Definition of done

- [x] Every implementation checklist item above is complete.
- [x] All deterministic verification commands pass.
- [x] Authorized isolated Provider and end-to-end smoke checks pass.
- [x] The original failure mode cannot create a misleading accepted Run.
- [x] A late Provider failure is visible and actionable in the Workspace.
- [x] Existing untracked user files remain untouched.
- [x] The final review records the root cause: execute mode was enabled without a real Web Research Provider, and the UI discarded the terminal Run error.
