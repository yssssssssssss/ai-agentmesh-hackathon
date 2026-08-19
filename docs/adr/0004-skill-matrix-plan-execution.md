# ADR 0004: Skill Matrix Plan Execution

## Status

Accepted for the first ten Wiki domain Skills. Default rollout state is `off`.

## Context

AgentMesh already had eleven Legacy `$group.command` capabilities and a single-Skill OpenAI Agents SDK runtime. A natural-language design workflow may need several domain Skills, but exposing every Skill as an unconstrained Tool would mix selection, execution, write approval, recovery, and provenance inside one model loop.

The control plane must keep authorization, persistence, approval, cancellation, audit, and exactly-once recovery authoritative. Existing Legacy chat and explicit single-Skill behavior must remain compatible.

## Decision

AgentMesh owns a persisted `SkillPlan` and executes it as a bounded DAG:

1. Normalize intent without Tools or private-memory bodies.
2. Filter disabled, unbound, unauthorized, stale, and unready profiles before ranking.
3. Give the Planner at most twelve safe profiles; validate its structured draft deterministically.
4. Persist at most six nodes, depth four, with no more than three concurrent nodes.
5. Require Plan Approval before any plan containing two or more domain Skills executes.
6. Revalidate Skill version, content hash, binding, Tool Grant, and source scope when each node starts or resumes.
7. Normalize every node output before synthesis and retain Skill, node, source, artifact, usage, and attempt lineage.

The parent `AgentRun` owns the lifecycle. Nodes are not recursive Agent Runs and do not write chat messages or a shared SDK Session. Only the parent request and final synthesis are projected into the thread.

### Two independent approval gates

Plan Approval authorizes only the selected DAG version. It grants no Tool permission. A Tool requiring approval pauses the whole plan, persists the scheduler state, and creates a distinct Inbox item. Resume is claimed atomically per `call_id`; expiry, rejection, replay, cancellation, or a revoked Grant cannot execute the Tool twice.

### Failure and cancellation

- A required-node failure skips its dependants.
- An optional-node failure may continue when the output contract remains satisfiable.
- Usable required results plus a degraded contract produce `partial`, never `completed`.
- An unsatisfied contract produces `failed`.
- Cancellation atomically terminalizes the current database state, preserves committed results, resolves open approvals, and prevents late completions from overwriting the terminal state.

### Rollout

`AGENTMESH_SKILL_ORCHESTRATION` is the only orchestration flag:

- `off`: preserve existing behavior.
- `preview`: recommend and confirm Plans, but never execute a DAG.
- `execute`: execute confirmed Plans.

Invalid values fail closed to `off`. Health and Bootstrap expose the effective server value; no frontend build-time flag is added. Rollback to `off` retains all durable records and never auto-resumes an approval.

## Consequences

The design adds explicit state and transactions, but keeps model behavior outside the trust boundary. SSE reconnect and browser refresh are projections of persisted state, not execution triggers. SQLite and one process remain the first-release scheduling boundary; active plans and per-plan node concurrency are capped.

The first release intentionally excludes recursive planning, arbitrary user-authored DAG edges, automatic external writes, third-party Skill script execution, horizontal scheduling, and expansion beyond the ten governed domain Skills.

## Verification

Release requires deterministic retrieval evaluation, catalog/profile validation, backend and frontend suites, generated OpenAPI types, browser E2E, and an approved real-provider smoke for every configured compatible model. Top-3 retrieval recall must be at least 90%; disabled, unready, or unauthorized Skills must have zero recall.
