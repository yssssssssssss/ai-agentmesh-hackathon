# ADR 0005: Research Runtime and Web-First Vertical Slices

## Status

Accepted for implementation on 2026-08-19. Default rollout state remains `off`.

## Context

Research Orchestration already contains durable contracts, planning, compilation, Tool/Skill Actors, invocation recovery, verified Artifacts, Evidence, Claims, Deliverables and Reports. Related module tests pass, but the production product path is not assembled:

- `POST /api/agent/runs` still selects only the existing v1 runtime;
- the research route depends on a module-level service value that production never initializes;
- FastAPI lifespan does not own research startup recovery, reconciliation or shutdown;
- Workspace understands v1 `SkillPlan`, not the research aggregate projection;
- Plan Confirmation, Tool Approval and external-call recovery are not connected as one Web workflow.

This is a shadow implementation: internal modules exist, but users cannot reliably reach them. Further module-by-module patches would increase code volume without closing the product loop.

The original pre-v2 baseline gate was also missed. Commit `f2e09ca` is therefore recorded only as a scoped WIP recovery point, not as a release baseline.

## Decision

### One production composition root

Add one internal `ResearchRuntime`, created once by FastAPI lifespan and exposed through `app.state`.

It owns production dependency assembly and process lifecycle for:

- `CompetitiveResearchPlanning`;
- `ResearchWorkflowService`;
- `ExecutionEngine` and its Actors;
- `ArtifactStore` and `ResultPipeline`;
- startup recovery, periodic reconciliation, heartbeat supervision and shutdown.

`ResearchRuntime` is not a durable state source. SQLite remains authoritative. In-memory Tasks are disposable execution mechanisms reconstructed from persisted state after restart.

Routes obtain the Runtime through FastAPI dependency injection. Module-level mutable service globals are prohibited.

### One request routing decision

`POST /api/agent/runs` is the only place that selects an orchestration version:

- `off` creates v1;
- `preview` or `execute` creates `research-v2` only for explicit `$competitive-analysis` or a server-recognized competitive request;
- other natural-language requests, other explicit Skills and Legacy commands remain v1;
- the selected `orchestration_version` is immutable;
- replaying one `client_turn_id` returns the original Run and cannot switch versions.

The Workflow service does not route between v1 and v2.

### One control-state truth

`ResearchWorkflow.phase`, `active_gate` and `state_version` are the control truth. `AgentRun.status`, Attempt, Step and Invocation state are subordinate projections with explicit consistency checks.

Only mutation commands may schedule work. GET, SSE, browser refresh and projection building are pure reads.

### Lifecycle and recovery

- lease TTL defaults to 60 seconds;
- a running Attempt heartbeats every 15 seconds;
- startup and periodic recovery scan every 30 seconds;
- Attempt deadline is derived from the frozen execution budget plus a settlement grace, not from lease TTL;
- planning without a gate, PENDING Attempts and expired RUNNING Attempts are restart candidates;
- UNKNOWN Invocations never trigger automatic replay;
- normal execution and restart recovery use the same Workflow error coordinator;
- shutdown stops new claims and records already-SENT work before stopping at an Actor boundary.

The first release remains one FastAPI process, one Workspace and one SQLite database. No queue, separate Worker or new external service is added.

### Independent gates

Plan Confirmation authorizes only the immutable Plan. Tool Approval remains a separate Inbox decision and must be resolved before an approval-required Tool becomes SENT.

The first recovery API supports only:

- `retry`: the user confirms the external operation did not complete and authorizes another send;
- `abort`: the Workflow and Attempt are cancelled while the Invocation remains UNKNOWN.

Marking UNKNOWN complete from an attached receipt is deferred until receipt authenticity and settlement can be proved. The system guarantees at most one locally accepted result per operation key; it does not claim that every Provider receives at most one request.

The operation key is a transport parameter, not a Tool business argument.

### One Web projection

Workspace branches on immutable `AgentRun.orchestration_version`:

- v1 continues to use the existing SkillPlan UI;
- research-v2 reads `GET /api/agent/runs/{run_id}/research` and uses the existing Workspace shell;
- SSE only invalidates the query and causes a fresh read;
- Requirement, current gate, Plan, progress, recovery, Evidence, Deliverable, Review, Report and provenance are exposed through one aggregate projection plus owner-scoped Artifact reads.

No second workbench or per-Artifact family of GET endpoints is introduced.

### Vertical delivery order

1. Web Preview: Web input → version routing → Requirement/Plan → Workspace display → off fallback.
2. Web Execute: confirmation → Tool Approval → Tool → Skill → Evidence/Report, including restart, cancel and UNKNOWN recovery.
3. Release Gate: full local gates, browser E2E, security suite, default GPT real end-to-end, all enabled GPT compatibility smoke and off rollback drill.

Remaining Skills stay on v1 until competitive research passes the Release Gate and each later Skill passes its own vertical acceptance.

## Invariants

- No GET, SSE or refresh path may schedule Provider work.
- No Tool may become SENT from Plan Confirmation alone.
- A stale lease, Attempt or send sequence cannot settle a result.
- `off` prevents new research-v2 Runs and new claims while preserving historical reads and honest accounting of already-SENT calls.
- No credentials, raw private prompts, full Provider payloads or local databases enter Git or validation documents.
- Kimi is not configured and is not a release-gate model; only actually enabled GPT models are tested.

## Consequences

Complexity moves from route globals and disconnected background Tasks into one explicit runtime lifecycle. This adds a small supervisor and recovery loop, but removes multiple hidden owners and makes restart behavior testable.

The v1 and research-v2 domain models remain separate because their lifecycle and failure semantics differ. They share authentication, Store, Inbox, Artifact access, SSE and Workspace infrastructure without forcing one generic executor abstraction.

The current WIP remains large. Completion is therefore judged by independent vertical diffs and end-to-end behavior, not by module count or internal test count alone.

## Verification

Each slice requires L0 targeted tests, L1 cross-module integration and L2 user-path evidence. Release additionally requires:

- full backend and frontend gates;
- generated OpenAPI consistency and production build;
- browser E2E covering refresh and `off` fallback;
- crash/restart and late-result fault injection;
- authorized real Provider verification with redacted evidence;
- rollback rehearsal with historical research-v2 reads preserved.
