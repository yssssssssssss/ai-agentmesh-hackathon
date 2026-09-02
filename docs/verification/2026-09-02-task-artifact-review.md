# Task Artifact Review Verification

- Date: 2026-09-02
- Branch: `feature/task-artifact-review`
- Base: `8ea46a986af7a9ffc0a67aeace279bf7e760fb62`
- Status: implementation complete; production Task writes and Universal orchestration remain disabled by default

## Delivered scope

- Added the versioned `TaskReviewV1` aggregate with `pending`, `accepted`, `changes_requested`, and `rejected` states.
- Added durable review rounds, optimistic Review versions, stable command receipts, and bounded Task-detail Review history.
- Added `POST /api/tasks/{task_id}/reviews` for a Run owner to select canonical sealed Artifacts and freeze their ordered IDs and SHA-256 content hashes.
- Added server-derived reviewer selection from active project members with effective `review_task_deliverables` permission; clients cannot nominate a reviewer.
- Added `POST /api/task-reviews/{review_id}/decisions` for the assigned reviewer.
- Made Review submission atomically persist the pending Review, move Task delivery from `in_progress` to `review`, create the reviewer-specific Inbox projection, append a redacted AuditEvent, and save the command receipt.
- Made Review decision atomically update the Review, move the Task to `done` or back to `in_progress`, resolve the Inbox projection, append a redacted AuditEvent, and save the command receipt.
- Added exact review-scoped Artifact inspection for the assigned reviewer at `GET /api/task-reviews/{review_id}/artifacts/{artifact_id}`. Every read rechecks reviewer permission, Task visibility, frozen membership/hash, canonical seal state, Run lineage, and content integrity.
- Kept generic Task detail privacy-safe: non-owners still receive no generic Artifact download link, Run input/output and Artifact content remain absent, and review-scoped inspection grants no general Run access.
- Added reviewer-specific Inbox projection and Task Center navigation, including direct Task fallback when the reviewed Task is outside the user's default-project list.
- Added Task Center Review submission, frozen Artifact/hash display, accept/change/reject controls, review history, retryable detail-refresh errors, and stale-action suppression.
- Added server-derived per-Run `can_submit_review`; linked Tasks expose no review submission action when the current user owns no reviewable sealed delivery.
- Added provider-free restart coverage through Task creation, linked completed Run, sealed Artifact, Review submission, restart, acceptance, Inbox resolution, and Audit persistence.

## Transaction and concurrency guarantees

- Submission rechecks actor status, project membership, Task authority, Task version/stage/block/archive state, reviewer eligibility, pending-review uniqueness, Run lineage/status, Artifact seal/projections/hash/size, and Run ownership under `BEGIN IMMEDIATE`.
- Decision rechecks reviewer identity and permission, Review version/status, frozen identity fields, Task version/stage, Run ownership, Artifact integrity, and Inbox identity under `BEGIN IMMEDIATE`.
- Exact command replay returns the original durable result; the same user command ID with a different operation or request hash fails closed.
- One pending Review is allowed per Task, and Review rounds remain unique and monotonically assigned.
- Ordinary Task mutations are rejected while a Review is pending.
- Legacy Task writers preserve `intent`, `done_when`, and `steps` while a Review is pending.
- Criterion-bearing Blackboard handoff for persisted Tasks now rechecks authorization, expected parent and Task snapshots, target Agent eligibility, and pending Review state, then writes the handoff post, parent lock release, Task update/version, FTS projection, and AuditEvent in one transaction.
- A controlled Review-submit versus handoff race proves that the losing handoff leaves no partial post, Task criterion change, or AuditEvent.
- Task Review Inbox snooze/open updates reload Inbox, Review, actor, membership, and permission in one transaction and write their AuditEvent atomically. A controlled stale-snooze race proves a completed Review cannot be reopened.

## Compatibility and safety

- `Task.status`, `Task.collaboration_stage`, and `TaskManagementMetadataV1.delivery_stage` remain separate state axes.
- Task Review evaluates delivery quality only. It does not create Personal Memory, Team Candidate, or Team Knowledge and does not substitute for Memory Review.
- Linked Runs cannot use the legacy manual `submit_review` or `complete` transitions to bypass Artifact Review. Manual Tasks without a linked Run retain the manager-controlled path.
- Run completion still does not complete a Task automatically.
- Private Task Review Inbox items are visible and mutable only to the assigned reviewer, after Workspace and Project membership checks; admin role does not bypass that private projection.
- Audit metadata contains object IDs, counts, versions, and decisions, but not Artifact content or Review decision prose.
- Review submit/decision and inspection require no LLM, Embedding, Web, O2, MCP, or Data Provider.
- Task writes still default to `AGENTMESH_TASK_MANAGEMENT=read_only`.
- Universal production orchestration remains `AGENTMESH_SKILL_ORCHESTRATION=off`.

## Review remediation

Independent static review initially found four P1 issues: assigned reviewers could not inspect cross-user Artifacts, compatibility writers could change Task criteria during review, a stale Inbox update could reopen a resolved projection, and admins could see or mutate private Task Review Inbox items across ownership/workspace boundaries. It also found P2 issues around cross-project navigation, non-owner Review affordances, stale detail actions, and a Blackboard handoff race.

The implementation now:

- requires the Run owner to submit and grants only the assigned eligible reviewer an exact frozen-Artifact inspection path;
- freezes Task criteria across both managed and compatibility writers;
- uses transactional Inbox compare-and-set updates with atomic audit;
- applies Workspace, Project, and assigned-user isolation before admin role handling;
- falls back to direct Task detail retrieval for cross-project Inbox navigation;
- derives `can_submit_review` per Run and suppresses non-owner or stale UI actions;
- keeps actions disabled until an error-free per-open detail refresh succeeds and exposes a retry action on failure;
- linearizes Blackboard handoff and Review submission through one SQLite writer transaction.

Final reviewer verdict: no remaining P0, P1, or P2 findings; merge verdict `OK`.

## Validation

- Backend full suite: `1773 passed, 6 skipped` (`1779` collected).
- Task Review suite: `10 passed` as part of the final backend run.
- Standalone Task/Review suite: `8 passed` as part of the final backend run.
- Frontend unit suite: `184 passed` across `29` files.
- Full Playwright suite: `70 passed` using one Chromium worker.
- Task Center Playwright coverage: `14 passed` as part of the final full run.
- TypeScript production build and bundle budget: passed; largest bundle `316987` bytes (limit `500000`).
- Ruff: passed.
- `git diff --check`: passed.
- OpenAPI schema and generated TypeScript client: regenerated.

During browser validation, the new delayed-detail test first exposed that React Query could retain cached detail while a fresh request was pending or failed. The final implementation requires a successful, error-free per-open refetch before enabling any Task action; the subsequent Task Center and full Playwright runs passed.

## Deferred scope

- Personal Memory capture from an accepted Task Review.
- Team Candidate creation and separate Memory Review.
- Memory revision, supersession, dispute, deprecation, expiry, archival, and restore.
- `MemoryUseReceiptV1`, citations, and downstream reuse measurement.
- Subtasks, dependencies, calendar, milestones, Agent queue, and project analytics.
- Real Provider acceptance and Universal production release gates, tracked separately from this non-production repository integration.
