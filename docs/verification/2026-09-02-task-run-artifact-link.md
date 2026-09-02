# Task–AgentRun–Artifact Link Verification

- Date: 2026-09-02
- Branch: `feature/task-run-artifact-link`
- Base: `5048499ee674cefb5b3b9ec5f97b414a0866351b`
- Status: implementation complete; production Task writes and Universal orchestration remain disabled by default

## Delivered scope

- Added nullable, immutable `AgentRun.task_id` linkage and accepted `task_id` on new Run requests.
- Included `task_id` in new Run idempotency identity while preserving the historical hash for taskless legacy Runs.
- Made linked retries inherit their parent Task and revalidate parent/project/thread/Task identity inside the Run claim transaction.
- Enforced linked-Run Task stage, blocked state, assignee, project, task-kind thread, and single-active-Run rules under `BEGIN IMMEDIATE`, including claims without `client_turn_id`.
- Added the indexed `agent_runs.task_id` projection, migration backfill, and payload/projection integrity checks on primary Run readers.
- Added Task aggregate execution history with bounded Run summaries and canonical sealed Artifact metadata.
- Validated every shared Artifact through `V1ArtifactReader`; raw, unsealed, malformed, mismatched, or integrity-invalid rows are not projected.
- Applied owner-safe links: only a Run owner receives Run navigation and only an Artifact owner receives a download link. Run inputs/outputs and Artifact content are never included in the Task aggregate.
- Added explicit 50-Run and 200-Artifact safe-item limits plus `runs_truncated` and `artifacts_truncated` signals.
- Added Task Center execution-history loading, independent error/retry, empty, truncation, navigation, and active-Run states.
- Added Task Center “启动个人 Agent” for eligible assignees, stable browser command IDs, refreshed aggregate actions, and duplicate-start suppression.
- Added `AgentRuntimeService.ready_for_user()` and `BootstrapState.agent_runtime_ready` so the UI distinguishes configured runtime from user-ready runtime.
- Made Task-started execution create a private task-kind executor Thread only after readiness is established; deterministic reuse validates thread kind and failed starts remove an unused newly-created Thread.

## Compatibility and safety

- Existing taskless Runs remain valid and retain their original idempotency digest.
- `task_id` is nullable for legacy and non-Task execution, but cannot be changed after Run creation.
- Retry linkage is inherited from the parent and cannot be moved to another Task.
- Task, AgentRun, ChatThread, and Project relationships are transactionally revalidated immediately before persistence.
- Existing non-task ChatThreads cannot be repurposed as Task executor Threads.
- Task detail remains available without any external LLM, embedding, web, O2, MCP, or data Provider.
- Provider/runtime unavailability disables Task-started Agent execution without affecting manual Task management or Task history reads.
- Task writes still default to `AGENTMESH_TASK_MANAGEMENT=read_only`.
- Universal orchestration remains independently controlled and production configuration remains `AGENTMESH_SKILL_ORCHESTRATION=off`.
- Current storage assumptions remain one Workspace, one application process, one SQLite writer, and trusted local/intranet deployment.

## Review remediation

Independent static review identified retry-parent identity gaps, raw Artifact metadata projection, missing Task-to-Run navigation, a stale duplicate-start action, possible orphan task Threads when runtime startup failed, missing indexed `task_id` integrity checks, ambiguous execution-history failure rendering, and missing no-client/migration/truncation regression coverage. The implementation now:

- validates linked parent and Task identity inside every claim path while preserving unlinked legacy retries;
- filters Artifact references through the canonical sealed reader before applying the safe-item cap;
- exposes only owner-authorized navigation/download links;
- derives the start action from a fresh aggregate and separately checks for any active linked Run;
- checks runtime readiness before creating a Thread and cleans up an unused Thread after a failed start;
- validates the SQL projection against the canonical Run payload in primary readers;
- renders aggregate failures as retryable errors rather than empty history;
- covers no-client claims, schema migration/backfill, payload-column corruption, invalid Artifact rows, and exact 51/201 truncation boundaries.

Final reviewer verdict: no remaining P0, P1, or P2 findings; merge verdict `OK`.

## Validation

- Backend full suite: `1761 passed, 6 skipped` (`1767` collected).
- Task–Run linkage suite: `15 passed` as part of the final backend run.
- Frontend unit suite: `182 passed` across `29` files.
- Full Playwright suite: `67 passed` using one Chromium worker.
- Task Center Playwright coverage: `11 passed` as part of the final full run.
- TypeScript production build and bundle budget: passed; largest bundle `316987` bytes (limit `500000`).
- Ruff: passed.
- `git diff --check`: passed.
- OpenAPI schema and generated TypeScript client: regenerated.

An initial full Playwright run exposed an E2E-only race: the runtime-ready test reopened the Task before the two preceding delivery transitions were visible. The test now waits for `已计划` and `进行中` after each transition. The subsequent full run passed all 67 tests.

## Deferred scope

- `TaskReviewV1` and sealed Artifact review decisions.
- Atomic Review, Task transition, Inbox, and Audit writes.
- Memory Candidate capture and Memory governance.
- `MemoryUseReceiptV1`, citations, and downstream reuse measurement.
- Subtasks, dependencies, calendar, milestones, Agent queue, and project analytics.
- Real Provider acceptance and Universal production release gates tracked separately from this non-production repository integration.
