# Task Dialog Refresh Race Verification

- Date: 2026-09-03
- Base: `6d0179407f699cc87090e5338e1011f256daf53d`
- Trigger: post-merge `main` CI run `33712996262`
- Scope: frontend query and test synchronization only; no Task or Memory domain contract changes

## Symptoms

The post-merge Playwright job reported two Task Center timing failures:

- a newly reopened Task dialog disappeared before the next transition action became available;
- the detail-failure test sometimes did not retain its expected error state.

A previously observed Workspace bottom-clearance assertion also failed intermittently when layout settled after the test's one-time scroll.

## Root cause

`Tasks` enabled the managed-detail query automatically and also called `refetch()` from its dialog-open effect. Task mutations then invalidated the same query family and performed additional explicit list refetches. Under slower CI scheduling, overlapping requests and a late completion from the preceding dialog session could either clear the injected error or close a newly opened dialog.

The Workspace layout assertion scrolled to the bottom once before polling. A later layout-height change could move the final message behind the fixed composer while the assertion continued measuring without restoring the intended scroll position.

## Fix

- `useManagedTaskDetail` now supports disabling automatic fetch for the Task edit dialog.
- The edit dialog uses one explicit detail refresh per open session.
- Form open/close operations carry a monotonically increasing session identity; late async completions can close or update only the session that started them.
- Redundant post-mutation list refetches were removed because the awaited mutation `onSettled` path already invalidates and refreshes Task queries.
- The detail-failure Playwright regression now fails every pre-retry detail request and asserts exactly one request for a dialog-open session.
- The Workspace bottom-clearance assertion re-applies the intended bottom scroll within each poll, after any late layout change.

## Validation

- Targeted Task Center regressions: three isolated runs, `6 passed` total.
- Frontend unit suite: `190 passed` across `30` files.
- TypeScript production build and bundle budget: passed; largest bundle `317111` bytes (limit `500000`).
- Full Playwright suite: `72 passed`.
- `git diff --check`: passed.

The fix changes only request/session coordination and test synchronization. It does not relax action gating, Task versions, Task Review rules, or Memory governance.
