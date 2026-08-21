# Research V3 Gate 2 — Local Merge Follow-through TODO

Date: 2026-08-21

## Current references

- Preserved WIP branch: `user/main-wip-before-multibranch-merge-20260821` at `b3436c9ef27bf736379e1c71414d9ba3359b25c4`.
- Reviewed Gate 2 integration branch: `agent/research-v3-gate2-main-integration` at `fed453f85902b62b85c01b127b4db50c3f23aced`.
- Combined merge commit: `c484b583c757b0f2ec13af54c0c08da33edb7ca9`.
- Local `main` after recording all absorbed branches: `fed9ac5774eef45e896bef8cdbcb1697c6382f59` before this checklist update.
- Combined tree: `f99956cf70f76bd895dd1905f0d555bc40e331e0` before this checklist update.
- Production mode remains `off`; active writer remains `research-v2`.

## Checklist

- [x] Complete isolated Slice 1 implementation and human visual acceptance.
- [x] Complete Gate 2 dormant preview implementation.
- [x] Run Gate 2 focused backend, frontend, Ruff, build, and browser checks.
- [x] Create clean local integration branch without changing the dirty main Worktree.
- [x] Run one independent read-only deep review of `main..agent/research-v3-gate2-main-integration`.
- [x] Classify every review finding as blocker or recorded non-blocking debt.
- [x] Fix the four confirmed code blockers without reopening Gate 0/Foundation.
- [x] Re-run only the directly affected focused verification after blocker fixes.
- [x] Obtain final independent code sign-off for `fed453f85902b62b85c01b127b4db50c3f23aced`.
- [x] Preserve current main WIP in a dedicated local branch and commit.
- [x] Reconcile the conflicting plan by using the accepted Gate 2 version while preserving the former draft in WIP history.
- [x] Merge the WIP and reviewed Gate 2 branches into a clean `main` Worktree.
- [x] Record all remaining local development branches as integrated or superseded without changing the merged tree.
- [x] Verify every local branch tip is an ancestor of `main`.
- [x] Run final full backend, Ruff, frontend unit, build, bundle, and E2E gates.
- [x] Record that no push, deployment, allowlist population, control-row change, Provider call, or cutover occurred.

## Merge result

All local branch tips are ancestors of local `main`. Patch-equivalent Slice 1 lane branches were recorded with no tree change, and the stale `backup/candidate-tip` snapshot was recorded as superseded with the `ours` strategy. The original dirty root Worktree remains on its preserved WIP branch; the merge and verification ran in `.worktrees/main-multibranch-integration`.

The only textual merge conflict was the migration plan. The accepted Gate 2 version was selected because it contains the final immutable source identity, single-writer routing table, schema namespaces, owner ledger, and cutover boundary. The older Proposed draft remains recoverable from `b3436c9`.

## Final verification

- backend: 1,274 passed;
- full Ruff: passed;
- research-v3/parity focused follow-up: 250 passed;
- frontend unit: 146 passed;
- TypeScript/Vite build and bundle budget: passed;
- Playwright E2E: 54 passed;
- real Provider calls: not run and not authorized.

## Closed code findings

The first independent review rejected `8d3d5511ce811f21905089318d885686e8dc3565` and identified four code blockers. The corrected change set now:

1. rejects generic retry/cancel for research-v3 and requires stored-version APIs;
2. derives server-created thread IDs deterministically from user plus `client_turn_id`, so overlapping identical requests replay one Run/thread;
3. discovers the latest research-v2 or research-v3 Run during canonical thread navigation;
4. persists `active | confirmed | cancelled` preview lifecycle state, locks confirmed projection, blocks post-cancel mutation, and synchronizes the coarse AgentRun state.

Focused evidence after the fixes:

- first blocker batch backend: 90 passed;
- second blocker batch backend: 46 passed;
- changed-file Ruff: passed;
- frontend: 42 passed;
- TypeScript/Vite build and bundle check: passed.

The fallback follow-up review closed the original four findings but found two additional blockers. The second correction batch now:

1. replays concurrent research-v2 creation by `(user_id, client_turn_id)` inside `ensure_workflow` before proposed Run insertion;
2. atomically changes an expired/reconciled v3 preview root to `cancelled` with its coarse AgentRun;
3. backfills `confirmed` or `cancelled` lifecycle status from durable command receipts when opening the rejected pre-fix schema;
4. permits owner-authorized purge after confirmation or cancellation.

A third focused review confirmed those seams but found that `ResearchWorkflowService.start_if_applicable()` discarded the canonical replayed v2 Run returned by `ensure_workflow`. The third correction now returns the canonical `AgentRun`, schedules planning against its canonical ID, and makes `ResearchRuntime.start_run()` return that persisted Run. Production-path concurrent v2 route coverage passes.

Latest direct evidence:

- production v2/v3 workflow and preview set: 26 passed;
- changed-file Ruff: passed.

## Out of scope

This checklist does not authorize:

- push or pull-request publication;
- production deployment;
- production preview allowlist population;
- changing `research_writer_control` in production;
- real Provider execution;
- research-v2 retirement;
- production cutover;
- Slice 2 Multimodal.
