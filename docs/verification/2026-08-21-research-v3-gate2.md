# Research V3 Gate 2 Preview Composition Verification

Date: 2026-08-21

## Decision

Gate 2 implementation is **PASS for dormant preview composition** and **HOLD for production cutover**.

The code prepares a default-off research-v3 preview path, but no production control row, allowlist, route traffic, Provider, user data, deployment, merge, or push was changed. Production remains `off` with research-v2 as the active writer generation.

## Reviewed stack

Planning base:

- commit `07076d6cfe9d98ff767cd11b8dcea18f41f1726a`

Implementation commits:

- `c3db73c748034686147ee9ce669a9f3350df7631` — durable writer generation control;
- `86f3fc16d54a16158c4b29905f64bade96611054` — dormant v3 preview runtime and versioned routes;
- `dd54972b62f197ec8ff83fe3d8ff399543967288` — stored-version Workspace composition;
- `806670b88817aec532c1e96378565bbd3b7bbe72` — stale-writer database fence and preview cancellation hardening;
- `59e29a31fa0b0893a0a2803133a156c1cc3fdf7d` — secret-safe writer generation and allowlist health diagnostics.

Final code-under-test commit before this verification document:

- commit `59e29a31fa0b0893a0a2803133a156c1cc3fdf7d`;
- tree `3413513850dd42af8ed0136a567eb7269092efa4`.

## Implemented boundary

- additive singleton `research_writer_control`, seeded to research-v2 epoch 1;
- SQLite trigger fencing stale v2/v3 writer inserts against the active generation;
- server-only preview allowlist, empty by default and wildcard-forbidden;
- immutable `research-v3` AgentRun identity and generation epoch;
- atomic AgentRun/client-turn/v3-root creation;
- provider-free Requirement, ProblemGraph, candidate, Plan, revise, confirm, cancel, and purge workflow;
- stored-version v2/v3 HTTP dispatch;
- authoritative scoped SQLite projection;
- version-aware Workspace Workbench container;
- execute/approval/recovery fail-closed behavior;
- no second Runtime, database, orchestrator, service, frontend flag, or external dependency.

## Focused verification

### Gate 2 backend and lint

```text
65 passed in 23.97s
All checks passed
```

The set covered:

- generation control and stale fencing;
- atomic creation and client-turn replay;
- preview planning and command idempotency;
- API/projector integration;
- SQLite persistence integrity;
- existing v2 routes and Agent Run creation.

After stale-v2 trigger and cancel hardening, the directly affected set ran once:

```text
51 passed in 10.78s
All changed-file Ruff checks passed
```

The final secret-safe rollout-health check ran once:

```text
6 passed; 16 deselected
Health route/test Ruff checks passed
```

### Frontend focused gate

```text
4 test files passed
39 tests passed
```

Covered:

- Workbench canonical validation and all accepted inner states;
- API request hashing and exact receipts;
- research-v3 stored-version cache invalidation;
- provider-free preview container;
- unchanged research-v2 Workspace flow.

### Frontend build

```text
tsc -b: passed
vite build: passed
bundle check: passed
largest bundle: Workspace-BFZsF5vY.js, 382601 bytes
budget: 500000 bytes
```

### Live browser check

A disposable database and local-only servers were used with:

```text
backend: 127.0.0.1:8022
frontend: 127.0.0.1:5182
synthetic preview user: usr_current_designer
browser task space: 25
```

Observed state sequence:

1. empty AI Workspace;
2. research-v3 clarification after `帮我做竞品分析`;
3. candidates after answering `Alpha, Beta`;
4. plan after selecting Depth.

Final DOM measurements:

```json
{
  "state": "plan",
  "previewNotice": true,
  "confirmButtons": 1,
  "executeButtons": 0,
  "horizontalOverflow": 0,
  "errors": []
}
```

The semantic browser check passed. A full-page screenshot capture timed out and no new screenshot artifact was retained; the accepted Slice 1 visual matrix remains the visual baseline because Gate 2 did not change Workbench inner-state markup. The task space and local servers were closed, and the disposable database was deleted.

## Provider isolation

- Preview planning uses a deterministic local proposal and frozen adapter declarations.
- Actor adapter `execute` methods were patched to fail if called in focused tests; call count remained zero.
- Live browser preview exposed no execute action.
- No Tavily, LLM, Skill SDK, Reviewer, O2, Playwright acquisition, or Lab call was made.
- Preview control snapshots are non-executable and must be re-resolved against real runtime health before any future execute authorization.

## Defaults and rollback

Production-safe defaults remain:

```text
AGENTMESH_SKILL_ORCHESTRATION=off
AGENTMESH_RESEARCH_PREVIEW_ALLOWLIST=
active_generation=research-v2
generation_epoch=1
```

In an isolated rehearsal, advancing to v3 is one-way. Rollback is `off`; it never changes the generation back to v2, rewrites data, or performs a downgrade.

## Recorded residuals

- The previously recorded 26 Foundation/Slice 1 Ruff findings remain bounded technical debt; Gate 2 changed files pass Ruff.
- Full repository pytest/Ruff, frontend full test, E2E, catalog, eval, real Provider, independent researcher, pilot, and production rollback gates were intentionally not run.
- Production cutover still requires distinct `AM-ARCH` and `AM-RELEASE-QA` individuals and a new decision receipt.

## Final authorization state

| Action | State |
| --- | --- |
| Keep Gate 2 code on isolated branch | Authorized |
| Merge or push | Not authorized |
| Deploy dormant composition | Not authorized |
| Populate production preview allowlist | Not authorized |
| Change production writer generation | Not authorized |
| Call real Providers | Not authorized |
| Stop research-v2 new writes | Not authorized |
| Begin Slice 2 Multimodal | Not authorized |
