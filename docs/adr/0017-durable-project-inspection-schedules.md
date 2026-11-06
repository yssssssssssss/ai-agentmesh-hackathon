# Durable project inspection schedules

Date: 2026-10-04
Status: accepted for the local SQLite implementation

## Context

Existing scheduled definitions were editable metadata without a durable execution claim. Automatic queries must survive a process restart without duplicating a time slot, preserve current project permissions, and never convert a read-only query into a Task or Memory mutation.

## Decision

Extend the existing definition with explicit project/template, server-owned execution identity, versioned commands, IANA timezone, and a bounded budget. Historical definitions remain unvalidated until explicitly resaved. Croniter computes five-field wall slots, while application policy skips DST gaps and repeated folds and enforces a five-minute elapsed interval for automatic Runs.

One SQLite write transaction records a frozen occurrence, an existing v1 AgentRun, its existing dispatch receipt, and the next slot. A slot remains unique across configuration versions. Manual command identity is separate from scheduled slots. The occurrence is a trigger fact; Run and dispatch remain execution authorities. The scheduler only admits work and wakes the existing Runtime pump.

The first three templates call the real local Task/Review query service directly through that Runtime path. Model usage is zero; optional model summaries are not implemented here. Durable attempt counts, retry times, tool limits, and deadlines bound the read. Restart recovery reuses the same Run and fences stale process epochs. Completion, an owner Inbox projection, result hash, and dispatch settlement commit together. Reports never auto-create Memory.

`AGENTMESH_AUTOMATION_MODE` defaults to off and rejects unknown values as off. Observe computes diagnostics without writes or provider calls. Execute also requires the SDK Runtime. Configured enabled state cannot override these gates. Project membership and effective management permission are rechecked at admission, read, restore, completion, and report access. Other managers may pause a revoked owner's definition but cannot read its private report.

## Consequences

No new queue, orchestration engine, or Worker infrastructure is needed. The supported deployment remains a single SQLite application process. Reports use canonical Run storage and source references; Task and Memory actions retain their existing confirmation and write gates. Corporate Provider integration, research-drain failures, marketplace persistence, and later memory/runtime phases have separate acceptance work and remain unfinished.
