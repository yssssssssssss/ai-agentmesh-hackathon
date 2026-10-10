# Current project state comes from Task/Review SQL

Status: accepted for the local current-state ContextAssembler slice, 2026-10-04.

## Decision

Add a small current-state query to the existing Task operations domain. The
SQLiteStore reads current actor/project authority, stage counts, Review counts
and an optional Task with direct dependencies in one read transaction. It uses
the existing rebuildable Task projection and canonical Review table. It creates
no new Task, scheduler, Memory record or alternate source of business state.

SQL GROUP BY counts remain exact above the inspection UI's hydration limit.
Counts exclude conversation Tasks and archived Tasks; archive totals are reported
separately. Reviews join only active shared Tasks. Dependency joins filter
Workspace, Project, shared-thread kind and archival state before reading bodies.
Missing or unavailable targets contribute an explicit missing count and cannot
establish execution readiness. The selected Task's current active local Run count
also prevents duplicate execution readiness. Known zero counts are valid results.

Expose the same authority at GET /api/task-operations/{project_id}/state and as a
governed read-only project_state tool. The tool defaults Project from its Run,
refuses a different Project, and accepts a real Task ID without guessing names.
The normal tool grant and policy checks remain in force. Personal builtin Agents
receive the same local read capability through existing default tool grants.

## Context and recovery

MemoryContextService remains the ContextAssembler boundary. A conservative set
of explicit current-project count/status questions and current linked-Task
status/dependency questions route to the SQL query. Historical, free-form and
other-project questions do not silently become current-state queries. Automatic
delivery retains the existing off/observe/inject and private-chat boundaries.

An optional ProjectStateContextV1 in the existing private context bundle freezes
the exact query, computed result, watermarks, Task versions and selection decision.
It carries no Memory hits or use receipts. Absent fields preserve legacy canonical
bytes. Complete rendering passes the Memory character budget and the separate
complete SDK request budget. Unsafe bodies are quarantined; oversized bodies are
budget_dropped as a whole, with a bounded diagnostic.

Local snapshots restore that exact rendering after restart/approval. Recovery
checks the current SQL result before approval or tool execution; every admitted
model request repeats the check. The result signature excludes only the read
clock. A changed count, Review result, selected Task version or dependency stops
the stale handoff. Prepared tool output uses the existing private exact-output
delivery mechanism and is revalidated when entering the next model request.
Metadata reports query/result hashes, times and decisions without Task bodies.

Current-state evidence references link to the actual API query and Task drawer.
The source identifies the observed local query; its URL is a fresh lookup, not
an immutable archive. The frozen Run payload preserves the observed result.
Remote Runner delivery stays withheld until the actual-delivery and revalidation
protocol exists. This slice does not claim remote freshness or a Memory use.

## Remaining work

Terminology aliases, procedure applicability/reuse, candidate-level UI, budget
selection across all request classes, authorized retrieval capacity and frozen
Memory/procedure evaluations remain incomplete. Complete Session ownership,
source archives, non-streamed planning/synthesis budgets, remote
delivery receipts and aggregate runtime costs continue in Phase 4. Local
deterministic verification does not measure real model answer quality or
enterprise Provider readiness.

Verification: docs/verification/2026-10-04-project-state-context-regression.json.
