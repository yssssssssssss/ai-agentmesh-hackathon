---
status: accepted
---

# Separate project delivery state from execution and collaboration state

AgentMesh uses `Task` as the durable project work item. A Task may exist without an AgentRun and may have multiple execution attempts. Existing `Task.status` remains the execution-state compatibility field, and `Task.collaboration_stage` remains the Blackboard coordination field. Project planning uses the independent `TaskManagementMetadataV1.delivery_stage` lifecycle: `backlog`, `planned`, `in_progress`, `review`, `done`, and `cancelled`.

Human-created Tasks keep a required ChatThread for context, but that Thread is marked `kind=task` so it does not appear as an ordinary conversation. Workspace and Project ownership continue to come from the Thread. Task management fields are optional on stored legacy Tasks and are materialized only by a version-checked write.

## Consequences

- Task management cannot reinterpret or replace the existing execution and collaboration enums.
- Blocking is orthogonal metadata, not a second terminal state.
- A Task can be managed manually when every external Provider is unavailable.
- Task mutations use stable command IDs, optimistic versions, SQLite transactions, server-derived allowed actions, and AuditEvents.
- `AgentRun.task_id` will be optional, immutable after creation, and inherited by retries in the next delivery slice.
- Run completion will not directly complete a Task. A sealed Artifact and accepted Task Review are the planned completion gate.
- Task Center write behavior is independently gated by `AGENTMESH_TASK_MANAGEMENT=read_only|write`, defaulting to `read_only`.
- The existing Task Catalog concept remains an intent-routing contract and is never used as a Project Task identity.
