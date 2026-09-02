---
status: accepted
---

# Separate project delivery state from execution and collaboration state

AgentMesh uses `Task` as the durable project work item. A Task may exist without an AgentRun and may have multiple execution attempts. Existing `Task.status` remains the execution-state compatibility field, and `Task.collaboration_stage` remains the Blackboard coordination field. Project planning uses the independent `TaskManagementMetadataV1.delivery_stage` lifecycle: `backlog`, `planned`, `in_progress`, `review`, `done`, and `cancelled`.

Human-created Tasks keep a required ChatThread for context, but that Thread is marked `kind=task` so it does not appear as an ordinary conversation. Workspace and Project ownership continue to come from the Thread. Task management fields are optional on stored legacy Tasks and are materialized only by a version-checked write.

A `TaskReviewV1` is the durable quality decision for one execution attempt. Only the owning user of that Run can submit its output for cross-user review. Submission freezes the Task, Run, ordered Artifact IDs, and their content hashes, selects an eligible reviewer on the server, and creates a reviewer-specific Inbox projection. The request cannot nominate its reviewer: the server prefers the requester when that user already has `review_task_deliverables`, otherwise it deterministically selects an active eligible project member. Review submission moves delivery from `in_progress` to `review` atomically. `accepted` moves it to `done`; `changes_requested` and `rejected` return it to `in_progress`. The decision, Task transition, Inbox resolution, command receipt, and AuditEvent share one SQLite transaction.

Task detail never grants cross-user Artifact downloads. The assigned reviewer receives a separate review-scoped inspection endpoint limited to the exact frozen Artifact ID/hash set; it revalidates reviewer permission and Artifact integrity on every read and does not grant general Run access.

Task Review does not decide whether an Artifact is reusable team knowledge. That remains a separate Memory Review and governance lifecycle. Inbox is a work projection, not the Review fact source.

## Consequences

- Task management cannot reinterpret or replace the existing execution and collaboration enums.
- Blocking is orthogonal metadata, not a second terminal state.
- A Task can be managed manually when every external Provider is unavailable.
- Task mutations use stable command IDs, optimistic versions, SQLite transactions, server-derived allowed actions, and AuditEvents.
- `AgentRun.task_id` is optional, immutable after creation, included in idempotency identity, and inherited by retries.
- Run completion does not directly complete a Task. A linked Run can enter delivery review only with canonical sealed Artifacts, and direct Task transitions cannot bypass that gate. A Task with no linked Run may still use the manager-controlled manual completion path.
- A pending Task Review freezes Task criteria and blocks ordinary Task mutation until its assigned reviewer decides it. Criterion-bearing Blackboard handoff and Task updates linearize against Review submission; managed handoff changes advance the Task management version.
- Reviewer-specific Inbox snooze/open changes use a transactional compare-and-set, while decision resolves the same Inbox in its atomic commit; stale Inbox updates cannot reopen completed work.
- Task Review and Memory Review remain different domain decisions; accepting a Task Review does not create or publish Memory.
- Task Center write behavior is independently gated by `AGENTMESH_TASK_MANAGEMENT=read_only|write`, defaulting to `read_only`.
- The existing Task Catalog concept remains an intent-routing contract and is never used as a Project Task identity.
