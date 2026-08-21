# Research V3 Gate 2 Preview Production Composition Plan

**Status:** Approved for documentation only on 2026-08-21 by interim owner `@heyunshen`.  
**Implementation:** Not authorized.  
**Production reachability:** Not authorized.  
**Planning base:** `5bcaac910a252030248220babe75985d7cbc7b4e` (`agent/slice1-production-shaped-integration`).

## 1. Purpose

Gate 2 is **Research V3 Production Preview Composition Readiness**. It is not Slice 2 Multimodal and is not the production cutover.

The gate prepares the accepted isolated Slice 1 implementation for a production-shaped, default-off composition that can prove:

- one durable active research writer generation;
- atomic Run-version selection and creation;
- stored-version dispatch for reads and mutations;
- a research-v3 preview path that cannot invoke Tool, Skill, LLM, or Reviewer Actors;
- owner-scoped authoritative projection in the main Workspace;
- restart consistency and an `off` rollback rehearsal.

Gate 2 ends before production traffic can create research-v3 Runs. The production active writer remains research-v2 throughout this gate.

## 2. Governing constraints

This plan inherits ADR 0006 and the accepted Slice 1 boundary:

1. Production has at most one active research writer generation globally.
2. `POST /api/agent/runs` is the only new-Run version decision point.
3. `client_turn_id` replay precedes live routing and returns the persisted version.
4. The client cannot choose research-v2 or research-v3.
5. Rollout allowlisting controls `off` versus `preview`; it never selects a writer generation.
6. A selected writer failure is explicit and never falls back to v2, v1, a mock Tool, or another Provider.
7. Existing v2 Runs dispatch by their stored version and remain readable.
8. Gate 2 must not call a real Provider or instantiate an execution-capable Actor composition.
9. Gate 0 and Foundation remain frozen; their known non-blocking lint debt does not reopen them.
10. Production cutover requires a later, independent decision by distinct `AM-ARCH` and `AM-RELEASE-QA` reviewers.

## 3. Scope

### 3.1 In scope

- additive durable active-writer control and fencing;
- `research-v3` as an immutable AgentRun version;
- one atomic Run-creation coordinator using the existing SQLite database;
- one stored-version research facade for v2 and v3;
- an inactive v3 preview workflow supporting planning-only commands;
- main Workspace rendering selected from the stored Run version;
- server-owned preview allowlist parsing with an empty default;
- restart, owner scope, fail-closed, rollback, and no-outbound-call verification;
- Gate 2 runbook and exact commit/tree evidence.

### 3.2 Out of scope

- changing the production active writer to research-v3;
- stopping research-v2 new writes;
- production research-v3 data creation;
- `execute` mode for v3;
- Tavily, LLM, Skill, Reviewer, O2, Playwright, or Lab calls;
- real Provider smoke;
- production migrations against user data;
- moving or rewriting v2 data;
- Slice 2 Multimodal;
- Gold runs, independent researcher evaluation, or the ten-user pilot;
- a second FastAPI application, Runtime, orchestrator, database, or control service;
- merge to `main`, push, deployment, or cutover.

## 4. Chosen architecture

```text
POST /api/agent/runs
          |
          v
client_turn_id replay
          |
          v
Research Generation Control -------- SQLite research_writer_control
          |                           active_generation + generation_epoch
          v
Server Rollout Policy
  |-- off / non-allowlisted --------> explicit v1 policy
  |-- active research-v2 -----------> existing v2 writer
  `-- active research-v3 -----------> preview-only v3 writer
                                         |
                                         |-- Requirement
                                         |-- ProblemGraph
                                         |-- depth/speed candidates
                                         `-- selected/revised/confirmed Plan
                                         X  no Actor execution

GET / command by run_id
          |
          v
Stored-Version Research Facade
  |-- research-v2 ------------------> v2 continuation / reader
  `-- research-v3 ------------------> v3 preview workflow / projector
```

The FastAPI lifespan continues to own one research composition root. The existing v2 Runtime remains the production writer/continuation during Gate 2. The v3 preview service owns no background task and is not an execution Runtime.

## 5. Durable entity delta

Gate 2 adds only the following durable/public surfaces:

| Entity | Delta | Purpose | Rollback cost |
| --- | ---: | --- | --- |
| SQLite table `research_writer_control` | +1 | Durable writer generation and fencing epoch | Leave additive table unused; no downgrade |
| Environment variable `AGENTMESH_RESEARCH_PREVIEW_ALLOWLIST` | +1 | Server-only pilot eligibility; empty by default | Remove value/restart |
| Internal Research Current facade | +1 | Stored-version dispatch and one creation decision | Revert composition while no production v3 rows exist |
| AgentRun version `research-v3` | +1 enum value | Immutable version identity | Retain decoder even if dormant |
| New top-level HTTP route | +0 | Existing route namespace is reused | None |
| New service/process/database | +0 | Existing FastAPI and SQLite remain authoritative | None |
| New frontend flag | +0 | Frontend reads stored version | None |
| New external dependency | +0 | Gate is provider-free | None |

`AGENTMESH_SKILL_ORCHESTRATION=off|preview|execute` remains the only orchestration-mode flag. Gate 2 permits only `off` and `preview` for a v3 Run; `execute` fails closed.

## 6. Writer-generation control

### 6.1 Table

Add one singleton row:

```text
research_writer_control
- control_key: "global"
- active_generation: "research-v2" | "research-v3"
- generation_epoch: positive integer
- decision_receipt_hash: SHA-256
- updated_at: timezone-aware timestamp
```

The additive initialization seeds:

```text
active_generation = research-v2
generation_epoch = 1
```

No Gate 2 production path changes that row.

### 6.2 Creation transaction

A new `ResearchRunCreationCoordinator` owns one `BEGIN IMMEDIATE` transaction that:

1. rechecks `client_turn_id` and replays an existing Run if present;
2. reads `research_writer_control` and its epoch;
3. evaluates server mode and preview allowlist;
4. persists one AgentRun with immutable orchestration version and writer epoch;
5. for v3 only, initializes the owner-scoped `research_v3_runs` row and initial workflow state through a transaction-bound repository method;
6. commits all records together.

Any failure rolls back AgentRun, workflow, client-turn identity, and v3 records. A stale expected epoch fails before inserting a Run.

The v3 SQLite repository must expose a transaction-bound initialization method that does not begin, commit, or roll back the caller-owned transaction. It must not use a second database file or compensating dual writes.

## 7. Preview allowlist

Add:

```text
AGENTMESH_RESEARCH_PREVIEW_ALLOWLIST=user_gate2_preview_1,user_gate2_preview_2
```

Rules:

- absent or blank means an empty set;
- surrounding whitespace is normalized once;
- duplicate, blank, wildcard, or malformed IDs fail startup;
- the value contains user IDs only, not secrets;
- health output reports only count and a canonical SHA-256 digest;
- allowlisting decides `off` or `preview`, never research-v2 versus research-v3;
- Gate 2 production configuration leaves this variable empty.

## 8. Stored-version routing

Do not mount the existing v2 and v3 routers independently on overlapping paths. Add one Research Current facade under the existing `/api/agent/runs/{run_id}/research` namespace.

The facade performs an owner-scoped Run lookup, reads the persisted orchestration version, and delegates exactly once:

- `research-v2` -> existing v2 service/reader;
- `research-v3` -> v3 preview workflow/projector;
- unknown version -> integrity conflict;
- foreign owner/workspace/project -> 404.

GET, refresh, and SSE receive reader dependencies only and cannot schedule work. Mutations never reclassify the original request.

Version-specific route shapes remain explicit. A command unsupported by the stored version returns 409; it is not translated to another version's semantics.

## 9. V3 preview workflow

Add a concrete preview workflow implementing the isolated API protocol.

Allowed commands:

- create;
- clarify;
- select candidate;
- revise plan;
- confirm plan;
- cancel;
- purge.

Fail-closed commands:

- approval that could authorize a Provider call;
- execute;
- retry;
- skip;
- abort/recovery associated with an execution Attempt.

Planning uses frozen catalog resources and deterministic/local services only. The preview composition must not construct or inject:

- `TavilyToolGatewayAdapterV3`;
- `AgentSdkSkillAdapterV3`;
- `LlmSynthesisAdapterV3`;
- `ReviewerAdapterV3`;
- any real ToolGateway or model port.

The preview response must state that no external research was executed.

## 10. Workspace composition

The Workspace renders by `AgentRun.orchestration_version`:

| Stored version | UI |
| --- | --- |
| `v1` | existing ordinary Workspace |
| `research-v2` | existing v2 active/history UI according to stored state |
| `research-v3` | accepted ResearchWorkbench |

The frontend never receives active-writer configuration and cannot request a generation. It may submit only user answers and command intent; the server computes request hashes and validates state versions according to the approved API contract.

For v3 preview:

- Requirement, candidate, plan, confirmation, and read states are interactive;
- execute/approval/recovery controls are absent or explicitly disabled with preview copy;
- a refresh or SSE reconnect only reads authoritative persisted projection;
- v2 history remains read-only in the accepted Workbench presentation.

## 11. Work packages

Each work package has one writer, one final reviewer maximum, and one focused test checkpoint. Non-blocking findings are recorded instead of starting repeated review loops.

### Package A — Durable writer control

Primary files:

- `agentmesh/models.py`
- `agentmesh/store.py`
- `agentmesh/agent_runtime/settings.py`
- new `agentmesh/research_orchestration/current.py`
- `.env.example`
- new `tests/test_research_generation_control.py`

Deliverables:

- AgentRun `research-v3` discriminator;
- additive control table seeded to v2/epoch 1;
- exact control-row codec and CAS;
- strict preview allowlist parser;
- atomic creation coordinator and stale-epoch fencing;
- unchanged default v2/off behavior.

Focused test checkpoint:

```bash
.venv/bin/python -m pytest -q \
  tests/test_research_generation_control.py \
  tests/test_agent_run_routes.py
```

### Package B — Dormant preview composition

Primary files:

- new `agentmesh/research_orchestration/v3/preview_workflow.py`
- new `agentmesh/research_orchestration/v3/composition.py`
- `agentmesh/research_orchestration/v3/sqlite_repository.py`
- `agentmesh/routes/agent_runs.py`
- `agentmesh/routes/research.py`
- `agentmesh/app.py`
- new `tests/test_research_v3_preview_composition.py`

Deliverables:

- transaction-bound v3 initialization;
- planning-only workflow;
- one stored-version facade;
- preview execution denial;
- no Actor/provider composition;
- v2 behavior unchanged while control row remains v2.

Focused test checkpoint:

```bash
.venv/bin/python -m pytest -q \
  tests/test_research_v3_preview_composition.py \
  tests/test_research_v3_api.py \
  tests/test_research_v3_sqlite_repository.py \
  tests/test_research_orchestration_routes.py
```

### Package C — Version-aware Workspace

Primary files:

- `agentmesh-demo/src/pages/Workspace.tsx`
- `agentmesh-demo/src/features/workspace/queries.ts`
- `agentmesh-demo/src/features/research-workbench/apiClient.ts`
- new `agentmesh-demo/src/features/research-workbench/ResearchWorkbenchContainer.tsx`
- `agentmesh-demo/src/api/generated/schema.ts`
- `agentmesh-demo/src/features/research-workbench/ResearchWorkbench.test.tsx`
- `agentmesh-demo/src/features/research-workbench/apiClient.test.ts`
- `agentmesh-demo/src/features/workspace/research.test.tsx`
- new `agentmesh-demo/src/features/workspace/research-current.test.tsx`

Deliverables:

- stored-version UI dispatch;
- v3 query/mutation binding;
- preview-safe action presentation;
- unchanged v1/v2 flows;
- regenerated OpenAPI types.

Focused test checkpoint:

```bash
npm --prefix agentmesh-demo test -- \
  src/features/research-workbench \
  src/features/workspace/research-current.test.tsx
```

### Package D — Gate 2 verification and runbook

Primary files:

- new `docs/runbooks/research-v3-preview.md`
- new `docs/verification/2026-08-21-research-v3-gate2.md`
- update `README.md`, `CONTEXT.md`, and ADR 0006 only with the accepted Gate 2 boundary

Deliverables:

- exact commit/tree evidence;
- temporary-database v2-to-v3 preview rehearsal;
- restart and `off` rollback evidence;
- outbound Provider call count fixed at zero;
- production cutover explicitly marked unauthorized.

No full repository regression or real Provider smoke runs in this package. Those remain production-cutover Release Candidate gates.

## 12. Required test scenarios

1. Default `off` creates no versioned research Workflow or claim.
2. Default control row is research-v2 epoch 1.
3. Active research-v2 behavior matches the current route and persistence baseline.
4. Active research-v3 plus empty allowlist creates no v3 Run.
5. Active research-v3 plus one allowlisted user creates exactly one v3 preview Run in an isolated database.
6. Non-allowlisted Competitive requests follow the explicit v1 policy, not an error fallback.
7. Existing `client_turn_id` replay wins before all live routing decisions.
8. Reusing a client-turn ID with different input or skill returns 409.
9. AgentRun and `research_v3_runs` creation either both commit or both roll back.
10. Stale generation epoch fails before insertion.
11. Selected v3 writer unavailable returns an explicit error and creates no v2/v1 substitute Run.
12. V3 preview execute/approval/recovery returns 409.
13. Tool, Skill, LLM, Reviewer, and Provider fake call counters remain zero.
14. GET, refresh, and SSE do not invoke the workflow writer.
15. Owner, workspace, and project mismatch returns 404.
16. v2 Run reads and continuations dispatch only to v2.
17. v3 Run reads and planning mutations dispatch only to v3.
18. Restart preserves generation epoch, Run identity, command receipts, and projection.
19. `off` after a rehearsal prevents new research while preserving v2/v3 reads.
20. Frontend v1, v2, and v3 branches are selected only from stored version.
21. Production default configuration still creates no v3 Run.
22. Production application does not make an outbound Provider request during Gate 2 tests.

## 13. Gate 2 focused integration gate

After all four packages, run one Gate 2 focused gate:

```bash
.venv/bin/python -m pytest -q \
  tests/test_research_generation_control.py \
  tests/test_research_v3_preview_composition.py \
  tests/test_research_v3_api.py \
  tests/test_research_v3_sqlite_repository.py \
  tests/test_agent_run_routes.py \
  tests/test_research_orchestration_routes.py
```

```bash
.venv/bin/ruff check \
  agentmesh/models.py \
  agentmesh/store.py \
  agentmesh/agent_runtime/settings.py \
  agentmesh/research_orchestration/current.py \
  agentmesh/research_orchestration/v3/preview_workflow.py \
  agentmesh/research_orchestration/v3/composition.py \
  agentmesh/research_orchestration/v3/sqlite_repository.py \
  agentmesh/routes/agent_runs.py \
  agentmesh/routes/research.py \
  agentmesh/app.py \
  tests/test_research_generation_control.py \
  tests/test_research_v3_preview_composition.py \
  tests/test_research_v3_api.py \
  tests/test_agent_run_routes.py \
  tests/test_research_orchestration_routes.py
```

```bash
npm --prefix agentmesh-demo test -- \
  src/features/research-workbench \
  src/features/workspace/research-current.test.tsx
```

Run one browser check containing only v3 idle, clarify, candidates, and plan preview states if Package C changes visual composition. Do not regenerate the complete Slice 1 matrix unless those accepted inner surfaces change.

## 14. Rehearsal

Use only a disposable SQLite database and synthetic users:

1. initialize control row as research-v2 epoch 1;
2. confirm default off creates no research Run;
3. CAS the disposable control row to research-v3 epoch 2;
4. configure one synthetic preview allowlist user;
5. create one Competitive preview Run;
6. complete clarification, candidate selection, revision, and confirmation;
7. prove execute is denied and Provider call counters are zero;
8. restart the application against the same disposable database;
9. verify authoritative projection and client-turn replay;
10. switch orchestration mode to off;
11. verify no new research and both v2/v3 historical reads;
12. retain generation as v3 in the rehearsal database; never switch back to v2 as rollback.

No production database, credential, account, or Provider endpoint is used.

## 15. Rollback

Before production cutover, Gate 2 rollback is code/config rollback because production has no v3 rows:

- keep `AGENTMESH_SKILL_ORCHESTRATION=off`;
- leave the additive control table seeded to research-v2;
- revert the dormant composition if necessary;
- do not downgrade the database.

After a future cutover, rollback semantics are different and outside this gate:

- set orchestration mode to `off`;
- keep active generation research-v3;
- do not resurrect v2 new writes;
- preserve v2/v3 historical reads;
- settle already-SENT calls honestly;
- perform no data downgrade.

## 16. Failure and attack analysis

### External dependency failure

Gate 2 preview constructs no external Provider port. A Tool/model outage cannot affect preview because no call is permitted. Accidental adapter construction is a test failure.

### Scale increase

At ten times pilot volume, the first likely bottleneck is SQLite write serialization during Run creation. The control-row lookup is indexed and occurs only in the creation transaction. Gate 2 does not add polling or background writers. Performance expansion is deferred until measured contention exists.

### Rollback cost

Before cutover, rollback is low because no production v3 rows exist. After cutover, rollback cannot restore v2 writing; only `off` is allowed. This constraint is intentional and must be rehearsed before authorization.

### Premise collapse

The plan assumes the existing `SQLiteStore` and v3 repository can share one caller-owned SQLite transaction through a transaction-bound method. If that cannot be implemented without nested transaction or ownership ambiguity, Package B stops. The accepted fallback is to deepen the transaction interface; a second database, eventual consistency, or compensating dual write is forbidden.

## 17. Known technical debt

The Slice 1 diagnostic package-wide Ruff run reported 26 pre-existing findings. They remain non-blocking for Gate 2 focused packages and do not reopen Gate 0 or Foundation. They must be closed in a separate bounded lint-debt package before the future production-cutover Release Candidate runs full `ruff check .`.

## 18. Completion criteria

Gate 2 is complete only when:

1. all four work packages are independently mergeable;
2. default production behavior remains off/research-v2;
3. one synthetic disposable-database v3 preview rehearsal passes;
4. atomic creation, stale epoch, restart, owner hiding, and off rollback pass;
5. preview execution and every Actor/provider path fail closed;
6. frontend dispatches solely by stored version;
7. changed-file backend, frontend, and Ruff gates pass once;
8. no production user data, route activation, Provider, merge, push, or deployment occurred;
9. verification binds the exact clean commit and tree;
10. production cutover remains explicitly unauthorized.

## 19. Later cutover prerequisites

Gate 2 completion does not authorize cutover. A later production-cutover proposal must additionally provide:

- distinct individuals for `AM-ARCH` and `AM-RELEASE-QA` approval;
- full pytest, full Ruff, frontend test/build/E2E, catalog, and eval Release Candidate evidence;
- closure of known lint debt;
- real Provider smoke in an isolated/staging environment;
- independent researcher review;
- rollback rehearsal evidence;
- named preview pilot user IDs and stop conditions;
- an atomic control-row change receipt bound to the reviewed commit/tree.

## 20. Estimated impact

- four work packages;
- approximately 18–25 changed or new files;
- no new service or external dependency;
- estimated 4–7 engineering days for one engineer, including focused verification but excluding later cutover gates.

## 21. Implementation handoff

Implementation must branch from the exact accepted Slice 1 integration commit plus this plan commit. It must preserve one writer per worktree, use at most one final reviewer per package, and avoid new parallel workflow fanout unless the user separately authorizes it.

Authorization phrase required before implementation:

```text
implement this plan
```

Until that phrase or an equivalent explicit instruction is received, no Gate 2 code, production wiring, test run, migration, merge, push, or configuration change is authorized.
