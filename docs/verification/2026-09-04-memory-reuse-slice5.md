# Memory Reuse Slice 5 verification — 2026-09-04

## Scope

Slice 5 closes the first cross-Task organizational-memory loop:

```text
Task A → AgentRun → sealed Artifact → accepted Task Review
       → explicit Team Candidate → independent Memory Review → accepted Team Knowledge
       → Task B / AgentRun context → citation → MemoryUseReceiptV1 → lineage and audit
```

This slice does not add Task dependency/calendar/milestone/queue work from Slice 6 and does not enable production Skill orchestration.

## Delivered behavior

- Added the AgentMesh-owned `MemoryContextService` as the shared Memory retrieval/context seam for:
  - Task-linked automatic Run context;
  - explicit Runtime `memory_search` tool calls;
  - legacy `PersonalAgent._search_team_brain()` compatibility.
- Added `AGENTMESH_MEMORY_CONTEXT=off|observe|inject`, defaulting fail-closed to `off`.
  - `off`: no automatic retrieval or injection;
  - `observe`: eligibility/ranking metrics only, no injection and no use receipt;
  - `inject`: safe, eligible, budgeted context is handed to the model and recorded.
- Added immutable `MemoryUseReceiptV1` records that freeze:
  - Run and Task IDs;
  - Memory ID, storage kind, record type, version, versioned content hash, and retrieval layer;
  - retrieval reason and a hash of the query, never the raw query;
  - stable citation label, Agent identity, and exposed original Source IDs.
- Added per-Run citation reservations. Labels are allocated under `BEGIN IMMEDIATE`, and a persisted unique index prevents one label from identifying two Memory versions during concurrent searches. Reservations are not projected as Memory use.
- Receipt commit revalidates the active user, Run ownership/status, immutable Task link, Workspace/Project membership, current `AgentMemoryBinding`, Memory visibility/lifecycle/version/hash/layer, team membership, Source IDs, and citation reservation in one SQLite transaction.
- Automatic and explicit context apply credential and prompt-injection quarantine before candidate limits and before a receipt can be written.
- Explicit Runtime `memory_search` defers receipt commit until output encoding, size checks, policy checks, audit persistence, and Tool-call settlement succeed. Withheld or transformed output does not create a receipt.
- The complete rendered context payload is bounded; the budget includes policy, IDs, hashes, citations, Scope, Layer, and Source metadata.
- Scope and MemoryLayer are independent retrieval dimensions. New governed shared Memory records an explicit layer. Legacy shared records retain their `memory-content-v1` hash and deterministic fallback layer; explicit-layer records use `memory-content-v2`.
- Run detail returns permission-safe Memory-use views and whether the final output cites each label.
- Memory lineage returns only usage backlinks whose Run is visible to the requesting user.
- The React Workspace displays “本次使用的记忆”; Knowledge detail displays later reuse records.

## End-to-end proof

`tests/test_memory_governance.py::test_task_a_team_memory_is_reused_by_task_b_without_providers` uses the public Run API and a local `ScriptedModel`:

1. Task A produces a sealed Artifact.
2. A separate Task Review is accepted.
3. The Run owner explicitly captures a Team Candidate.
4. An independently assigned reviewer accepts the Memory Review.
5. Task B starts a Task-linked Agent Run through `POST /api/agent/runs`.
6. The accepted Team Knowledge is present in the actual model system context as `[T1]`.
7. The model output cites `[T1]`.
8. Run detail and Memory lineage expose the same receipt to the Run owner and conceal the Run backlink from another user.
9. A reopened `SQLiteStore` reads the same receipt.

No real LLM, embedding, web, O2, MCP, or data provider is required for this proof.

## Safety and race regressions

`tests/test_memory_context.py` covers:

- exact receipt identity, replay, multiple reasons, and restart persistence;
- concurrent same-Memory idempotency and concurrent distinct-Memory citation allocation;
- lifecycle/version, explicit layer, and `AgentMemoryBinding` prepare/commit races;
- Scope/Layer independence and pre-ranking Layer filtering;
- strict Team project isolation;
- unsafe Memory crowding ahead of safe Memory, including the legacy AUTO path;
- model-build, prepared-event, and metrics failures before receipt commit;
- `off`, `observe`, and `inject` semantics;
- rendered-payload and per-summary budgets.

`tests/test_sdk_tool_runtime.py` verifies both successful explicit tool receipts and that unsafe tool output is withheld without a use receipt.

## Verification results

- Ruff: passed (`.venv/bin/python -m ruff check .`).
- Backend: **1831 passed, 6 skipped** (`.venv/bin/python -m pytest`).
- Frontend unit: **192 passed**, 31 files (`npm --prefix agentmesh-demo test -- --run`).
- TypeScript/Vite/bundle budget: passed (`npm --prefix agentmesh-demo run build`).
  - largest JS bundle: **317111 / 500000 bytes**.
- Playwright: **73 passed** (`npm --prefix agentmesh-demo run test:e2e`).
- OpenAPI client regeneration: passed (`npm --prefix agentmesh-demo run api:types`).
- `git diff --check`: passed.
- Final technical review: no remaining P0/P1/P2; merge verdict `OK`.

## Independent CI maintenance discovered during verification

The full suite exposed three DeepSearch tests whose fixed August 2026 clock made their seven-day Run expiry cross the real wall clock. The production expiry guard was correct; the fixtures were time-dependent. PR #26 (`ce780c975811e91d4c0a10f408a8cfa4309fd136`) changes only those test clocks to a current import-time baseline. Its targeted 57-test run passed. Required CI run `33832772122` passed after rerunning a Playwright setup job whose first attempt failed before tests because the external Microsoft apt repository returned HTTP 403.

## Deployment posture

Keep production defaults unchanged:

```bash
AGENTMESH_TASK_MANAGEMENT=read_only
AGENTMESH_SKILL_ORCHESTRATION=off
AGENTMESH_MEMORY_CONTEXT=off
```

This repository/CI result is not an independent human approval, Profile provenance attestation, production capacity exercise, backup/restore rehearsal, or production authorization. Universal production gates in Issues #6–#9 remain open.
