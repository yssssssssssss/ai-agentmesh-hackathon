# Current authority at the local Runtime model boundary

Status: accepted for the first general local model-authorization slice, 2026-10-04.

## Decision

The existing RequestBudgetModel boundary also checks current execution authority
before invoking its delegate. This applies with no prepared Memory, with Memory
off, and with a frozen automatic snapshot. It does not create another Runtime or
separate authorization store.

Capture a detached copy of the admitted Run. Each request reads the persisted Run
and compares owner, Workspace, Project, Thread, Task, writer generation and
execution contract identities. Mutating the caller's Run cannot replace that
admitted writer identity. Require RUNNING, an unexpired deadline, an active actor
and Project, current Project access and the existing Thread/linked-Task execution
authority. Reject before execution callbacks or prepared Memory receipt commit.
Frozen-context paths retain their established safe error codes.

Both streamed and non-streamed calls through this wrapper use the same check.
SDK request retries re-enter it; a read-stream failure cannot retry a revoked
owner's request. Positive requests retain complete-request budgeting, output caps
and execution callbacks. Errors use static codes without private payloads.

Capacity-wrapped local models perform preflight budgeting before queueing and
final admission after acquiring the actual LLM slot. A task-local ContextVar carries
the detached Run's admission gate through SDK request/retry tasks without sharing
mutable callbacks between owners. Final admission remeasures the actual request,
caps its output, rechecks current authority and frozen sources, and only then
commits prepared delivery or Memory receipts and invokes the delegate. Queueing
does not count as delivery. An unchanged measurement is not reported twice;
changed tool schemas or request content are reported and checked again.

Existing Runtime tests now create real persisted actors and Projects before
executing models. Pure DAG tests that do not invoke a model retain their isolated
synthetic identities. The stream/tool reuse integration explicitly owns its Run
under a persisted actor rather than relying on a missing-user bypass.

## Remaining work

This is the local SDK wrapper boundary. Session ownership/source archives and
complete lease fencing remain to be implemented. Requirement/planning/synthesis and compaction paths
that do not use this wrapper still require their own equivalent checks and
complete request/cost/deadline contracts. Remote Runner admission is separate.
This decision does not claim continuous authorization throughout an already
started Provider stream or real Provider readiness.

Verification: docs/verification/2026-10-04-project-state-context-regression.json.
