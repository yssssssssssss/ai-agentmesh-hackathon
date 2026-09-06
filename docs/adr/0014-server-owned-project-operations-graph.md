---
status: accepted
---

# Keep project operations as a server-owned Task graph and rebuildable read model

AgentMesh already owns Project Task identity, delivery stage, assignment, AgentRun linkage, Task Review, and Memory lineage. Slice 6 adds project operations without creating a second project-management source of truth.

`TaskManagementMetadataV1` therefore gains additive `parent_task_id` and `dependency_task_ids` fields. Parent edges describe work breakdown and milestone rollups. Dependency edges describe execution prerequisites. Both stay inside one Workspace and Project, reference managed Task records, and are validated under the same `BEGIN IMMEDIATE` transaction that persists the Task command and AuditEvent.

## Decisions

- Parent and dependency graphs are separate directed graphs. Each rejects self-links, missing or archived targets, and cycles.
- Relationship changes require effective `manage_project_tasks`, an expected Task version, a stable command ID, no pending Task Review, and no active AgentRun for the changed Task.
- Dependency readiness is server-owned. A Task cannot transition from `planned` to `in_progress`, and no Task-linked AgentRun can be claimed, while any dependency is not in delivery stage `done`.
- Reopening a dependency never rewrites or cancels an already persisted downstream Run. It prevents future starts and is visible as `waiting_dependencies`.
- Parent completion does not automatically complete children and child completion does not mutate the parent. Milestone progress is a read projection over non-cancelled descendants.
- The “critical dependency chain” is the longest currently unfinished dependency chain by edge count. It is not CPM, duration prediction, or a Gantt schedule because Task does not contain estimated duration.
- The Agent queue is a read model over assignments, dependency readiness, explicit blocks, reviews, and active Runs. It does not auto-dispatch work or bypass existing execution gates.
- Operational metrics describe project flow: Task, Run, Review, and Memory-use facts. They are not employee scoring or automated performance evaluation.

## Rebuildable projection

`task_operations_projection` is a SQLite query projection populated from canonical Task and task-kind Thread JSON. SQLite triggers keep it current for Task inserts, updates, and deletes; startup rebuilds it from canonical records. It may accelerate pagination, graph hydration, calendar, queue, and metrics, but it does not own authorization, Task versions, transitions, reviews, or Run identity.

The first capacity gate uses 10,000 Tasks, 50,000 Task/Audit events, 10,000 Memory records, and 1,000 accepted Team Knowledge records. Task list/detail, project operations, and FTS retrieval must remain under 500 ms p95 on the reference single-process SQLite deployment before considering a database migration.

## Consequences

- Existing Tasks deserialize with no parent and no dependencies.
- Task status, collaboration stage, and delivery stage remain independent.
- Task Review and Memory Review remain independent.
- Read-only deployments can read operations views but cannot mutate relationships or start newly ineligible work.
- Rollback removes the new UI/routes and stops relationship mutation; canonical Task, Run, Review, Memory, receipt, and Audit records remain intact. The projection can be dropped and rebuilt without losing facts.
