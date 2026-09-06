# Project Operations Slice 6 verification — 2026-09-06

## Scope

Slice 6 turns the completed Task → Run → Artifact → Task Review → Memory → reuse loop into a project-level operating surface. It adds server-owned Task relationships, execution readiness, milestones, calendar, Agent queue, operational metrics, pagination, and a measured SQLite read projection.

## Domain decisions

- `Task.status`, `Task.collaboration_stage`, and `TaskManagementMetadataV1.delivery_stage` remain separate.
- `parent_task_id` is a work-breakdown relationship. It drives child summaries and milestone progress but never mutates parent or child state automatically.
- `dependency_task_ids` are execution prerequisites. Every dependency must be in delivery stage `done` before the dependent Task may enter `in_progress` or claim a new Task-linked AgentRun.
- Parent and dependency graphs are separately cycle-checked in the same `BEGIN IMMEDIATE` transaction that persists the Task command, receipt, and AuditEvent.
- Relationship targets must be managed, non-archived Tasks in the same Workspace and Project. Relationship mutation requires effective `manage_project_tasks`, expected-version CAS, no pending Task Review, and no active AgentRun on the changed Task.
- An already-running AgentRun is never cancelled or rewritten if a dependency is later reopened. Future starts fail closed until dependencies are complete again.
- “Critical dependency chain” means the longest unfinished dependency chain by edge count. It is not CPM, a duration forecast, or a Gantt chart.
- Agent queue is a read model only. It never auto-dispatches work or bypasses Runtime admission.
- Operational metrics describe project flow and Memory reuse; they are not employee-performance scores.

See `docs/adr/0014-server-owned-project-operations-graph.md`.

## Delivered surfaces

### Backend

- Additive `TaskManagementMetadataV1.parent_task_id` and `dependency_task_ids`.
- Transactional relationship validation and current-state revalidation.
- Dependency gating at:
  - `planned → in_progress` Task transition;
  - preflight Task-linked Run authorization;
  - final SQLite AgentRun claim.
- Server-owned `TaskReadinessV1` on Task list/detail projections.
- Parent, dependency, and child summaries on Task detail.
- `GET /api/task-operations/{project_id}`:
  - Task/Run/Review/Memory-use metrics;
  - longest unfinished dependency chain;
  - milestone descendant progress;
  - paginated calendar;
  - paginated, filterable Agent queue.
- `GET /api/task-operations/{project_id}/task-options` for paginated relationship selection.
- Server-paginated managed Task and Blackboard-card feeds; the Task Center no longer chains every page before first render.
- Rebuildable `task_operations_projection`, maintained by SQLite triggers and rebuilt from canonical Task/Thread records at startup.
- Expression and projection indexes for project, due-date, assignee, parent, and AgentRun queries.

### React

- Task Center module switcher: Tasks, Overview, Calendar, Agent queue.
- Dense project metrics, critical-chain, milestone-progress, calendar, and queue views using existing dark utility tokens.
- Sliding three-month calendar window plus server pagination.
- Server-backed Task-page pagination; filters reset safely to page one.
- Agent queue filter and server pagination.
- Parent/dependency editor for users with server-backed `manage_relationships` action.
- Readiness and blocking dependencies shown in the Task management dialog.
- 390px viewport coverage and no page-level horizontal overflow.

## Permission and privacy checks

- Project access is checked before every operations query.
- Managed task-kind Threads are project-visible under the existing policy.
- A managed legacy conversation Task remains owner/manager/assignee scoped and does not leak through the operations projection.
- Agent queue exposes Task scheduling facts and aggregate Run status only; it does not expose Run input/output or Artifact content.
- Task Review and Memory Review remain separate aggregates and decision paths.

## Capacity evidence

The reproducible benchmark is:

```bash
.venv/bin/python scripts/run_project_operations_benchmark.py \
  --iterations 7 \
  --output docs/verification/2026-09-06-project-operations-benchmark.json
```

Dataset:

- 10,000 Tasks;
- 50,000 Task/Audit events;
- 10,000 Memory records;
- 1,000 accepted Team Knowledge records.

Reference single-process SQLite results after one warm-up iteration and seven measured iterations, all below the 500 ms p95 gate:

| Read path | p50 | p95 |
| --- | ---: | ---: |
| Task list | 248.952 ms | 274.797 ms |
| Task detail | 307.388 ms | 407.793 ms |
| Operations snapshot | 177.173 ms | 242.147 ms |
| Task relationship options | 97.959 ms | 170.024 ms |
| Memory FTS | 18.643 ms | 27.009 ms |

The JSON evidence is stored at `docs/verification/2026-09-06-project-operations-benchmark.json`.

## Verification status

- Ruff: passed (`.venv/bin/python -m ruff check .`).
- Backend: **1841 passed, 6 skipped** (`.venv/bin/python -m pytest`; required CI splits the 6 frontend-route tests into the frontend job).
- Project operations focused backend: graph, authorization, transaction race, projection rebuild, metrics, public routes, and benchmark contract all passed.
- Frontend unit: **195 passed**, 32 files.
- TypeScript, Vite build, OpenAPI regeneration, and bundle budget passed.
  - largest JS bundle: **317278 / 500000 bytes**.
- Playwright: **75 passed**, including project operations, relationship editing, server pagination, and 375px overflow coverage.
- Rendered browser QA: populated overview inspected at 1512px and 390px; semantic headings/actions were present and page-level horizontal overflow was false.
- Final code review: no remaining P0/P1/P2 found.
- Slice 6 PR #30 merged as `adf3b104f141e2afc7b6f7461582e92faf5ca944`.
- Post-merge `main` CI run `34019803741`: all four required jobs passed.

## Independent CI maintenance discovered during verification

The full-suite rerun on 2026-09-06 exposed one remaining DeepSearch v2 recovery fixture whose fixed absolute expiry had crossed the wall clock. Production expiry behavior was correct. PR #29 (`47674656e2580fe3ab583fea9a2e9f6166aa4a8b`) derives that fixture time at test import, and all required CI jobs passed in run `34011127625`.

The first Slice 6 PR run also exposed noise in the 84-Profile authoring smoke: retrieval quality remained 100%, but repeated YAML parsing pushed p95 to 502–515 ms on a shared runner. PR #31 (`088fc8f184c5e534e331e401fb7934e3adc9d84f`) caches validated Profiles only inside explicit offline coverage evaluation; production search continues to reload and revalidate. The focused smoke fell to 139.225 ms locally, and post-merge `main` CI run `34017491579` passed.

## Deployment posture

Production defaults remain fail-closed:

```bash
AGENTMESH_TASK_MANAGEMENT=read_only
AGENTMESH_SKILL_ORCHESTRATION=off
AGENTMESH_MEMORY_CONTEXT=off
```

This slice does not add cross-Workspace project management, automatic Agent scheduling, Gantt/CPM duration prediction, complex resource planning, time billing, employee ranking, external project-system synchronization, horizontal scaling, or a database migration.
