# Research V3 Gate 2 — Local Merge Follow-through TODO

Date: 2026-08-21

## Current references

- Source implementation branch: `agent/research-v3-gate2-preview-composition`
- Local integration branch: `agent/research-v3-gate2-main-integration`
- Integration base/head before this checklist: `4c6123128cd258b6b11f1b7f5a5436698820e6da`
- Integration tree before this checklist: `75f3dc5362c33f7e87a7f4ea06e1b9fd3fec8cfe`
- Current `main`: `dec6b55b3e97913c052ee2b665c063aec77a9dd3`
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
- [ ] Resume the same independent reviewer against the corrected exact HEAD and obtain final sign-off.
- [ ] Reconcile the conflicting untracked main-Worktree file:
  `docs/superpowers/plans/2026-08-20-ai-x-workbench-full-parity-migration-plan.md`.
- [ ] Confirm the main Worktree has no tracked modification and no untracked path that the integration branch would overwrite.
- [ ] Fast-forward `main` with:
  `git merge --ff-only agent/research-v3-gate2-main-integration`.
- [ ] Verify post-merge `main` has the exact integration commit/tree and no merge commit.
- [ ] Record that no push, deployment, allowlist population, control-row change, Provider call, or cutover occurred.

## Merge blockers

1. Corrected HEAD still requires follow-up sign-off from the same independent reviewer.
2. Main contains 10,737 untracked paths at the last inventory.
3. One untracked path directly conflicts with a tracked integration path, and its content differs by 225 lines:
   `docs/superpowers/plans/2026-08-20-ai-x-workbench-full-parity-migration-plan.md`.

The conflicting file is user work. It must not be moved, overwritten, deleted, or silently replaced without a separate explicit decision.

## Closed code findings

The first independent review rejected `8d3d5511ce811f21905089318d885686e8dc3565` and identified four code blockers. The corrected change set now:

1. rejects generic retry/cancel for research-v3 and requires stored-version APIs;
2. derives server-created thread IDs deterministically from user plus `client_turn_id`, so overlapping identical requests replay one Run/thread;
3. discovers the latest research-v2 or research-v3 Run during canonical thread navigation;
4. persists `active | confirmed | cancelled` preview lifecycle state, locks confirmed projection, blocks post-cancel mutation, and synchronizes the coarse AgentRun state.

Focused evidence after the fixes:

- backend: 90 passed;
- changed-file Ruff: passed;
- frontend: 42 passed;
- TypeScript/Vite build and bundle check: passed.

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
