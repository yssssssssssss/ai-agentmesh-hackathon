# ADR 0006: Single Active Research Writer and v2 Compatibility

## Status

Superseded by ADR 0008 on 2026-08-26. The text below is retained as a historical record and no longer describes an available writer-selection mechanism.

Accepted on 2026-08-21 by interim owner `@heyunshen` for **Gate 0, isolated Slice 1, and dormant Gate 2 preview composition only**. Gate 2 may install additive generation fencing, stored-version dispatch, and provider-free preview code while production remains `off` with research-v2 as the control-row generation. This acceptance does not authorize production v3 traffic, a control-row change, allowlist population, Provider calls, research-v2 retirement, merge, push, or deployment. Production cutover remains blocked on a separate decision by distinct `AM-ARCH` and `AM-RELEASE-QA` individuals.

Amended on 2026-08-25 for completed v2 retirement: the durable Writer lifecycle is `retired`. The executable research-v2 writer and every continuation path have been removed; existing v2 Runs are available only through the frozen read adapter. This amendment does not activate research-v3 or delete historical data.

## Context

AgentMesh currently persists `v1` and `research-v2` Runs. The proposed ai-x parity mainline will eventually persist a distinct current-generation value, `research-v3`, without changing the meaning of existing payloads. A migration design that lets cohorts create new v2 and v3 research Runs at the same time would leave two production research writers and make fallback, catalog identity, and rollback ambiguous.

Gate 0 is documentation and source-freeze work only. It must not add a production v3 route, runtime, model value, Provider call, database migration, or user-data rewrite.

The terms in this decision are intentionally narrow:

- **writer**: the implementation allowed to create a new research Run and its first durable Workflow state;
- **continuation**: a version-specific command handler that may advance only a Run already persisted with that version during a bounded drain;
- **settlement**: honest terminal accounting for an external call that was already SENT; settlement does not authorize a new claim or replay;
- **reader**: an owner-scoped projector/decoder that never schedules work;
- **purger**: the owner-authorized tombstone path that removes retained content while preserving required audit facts.

Readers, purgers, narrow settlement, and bounded continuations are not new-Run writers. They still require explicit version dispatch and least authority. In the completed `research-v2 / retired` state, only the reader remains installed; v2 purge, settlement, and continuation mutations are unavailable.

## Decision

### One creation decision and one active writer

`POST /api/agent/runs` remains the only Run-version decision point. Its eventual ordered policy is:

1. replay an existing `client_turn_id` and return its original immutable Run;
2. route Legacy commands to v1;
3. resolve explicit Skill identity against server-owned, versioned catalog namespaces;
4. classify supported research intent;
5. apply the server-owned mode and the globally configured active writer generation;
6. persist exactly one immutable decision and create exactly one Run.

No Workflow service, GET, SSE reconnect, browser refresh, approval handler, or recovery loop may reclassify the original text. Same-name Skills are selected by the persisted catalog namespace and contract version, never by filesystem load order.

Production has at most one active research writer generation globally. This canonical routing table is also used by the migration plan:

| Stage | `off` | `preview` / `execute` eligible Competitive request | Other request | Selected writer unavailable |
| --- | --- | --- | --- | --- |
| Gate 0 production / pre-cutover | v1 | research-v2 | v1 | fail closed; no alternate writer |
| Isolated Slice 1 validation | v1 | research-v3, isolated only | v1 | fail closed |
| Separately approved production cutover | v1 | globally active research-v3 | v1 until later task-type slices are accepted | fail closed; never v2/v1 fallback |

Replay by `client_turn_id` precedes live routing and always returns the persisted version. Slice 1 enables only Competitive Text research, not all five future task types. An allowlist controls preview versus execution, never v2 versus v3. `off` means no new versioned research Workflow or research claims; routing an ordinary request to v1 does not make v1 the current research writer.

The singleton control row also carries a lifecycle independent of the generation name:

| Lifecycle | New research Run | Existing Run continuation |
| --- | --- | --- |
| `active` | allowed for the matching generation and epoch | allowed |
| `draining` | fenced | allowed so old work can reach a safe terminal state |
| `retired` | fenced | disabled; historical Runs and Artifacts are read-only |

Lifecycle transitions are durable compare-and-swap updates. The current default and migration target is `research-v2 / retired`; no environment variable or compatibility test can reopen admission. Moving to research-v3 is a separate generation transition and atomically establishes its own `active` lifecycle.

The Slice 1 implementation was validated in isolation while production continued to route eligible research to v2. Gate 2 added a dormant composition only, with the preview allowlist empty and no production request able to create a v3 Run. The completed 2026-08-25 retirement advanced the control row to `research-v2 / retired / epoch 2`; moving to research-v3 still requires a **separate, jointly approved atomic cutover**.

### Immutable routing and durable fencing

The client-turn receipt, immutable orchestration version, active-writer generation, lifecycle, epoch, and Run creation must be checked and persisted in one SQLite transaction. A SQLite trigger independently rejects a new research Run unless all three control values match and the lifecycle is `active`. Before retirement, existing Run IDs were excluded from that insert fence so a bounded drain could finish. In the retired state no v2 continuation or settlement mutation remains; historical reads dispatch by the Run's stored version.

A selected writer failure is explicit. Missing Runtime, catalog, core Tool, contract, or active-generation agreement must fail closed; it must not silently fall back to v2, v1, a mock Tool, or a different Provider. `off` routing to v1 is an explicit server policy, not an error fallback.

### v1 compatibility

v1 ordinary chat, Legacy commands, v1-only Skills, Skill Matrix execution, and existing catalog/profile hashes retain their current contracts. The research catalog is a separate namespace keyed by catalog generation, Skill slug, and contract version. Gate 0 does not overwrite builtin Skill packages or reinterpret v1 Runs.

### v2 retirement and historical compatibility

`research-v2` remains an immutable persisted value. Existing schema identities, including `research-task-v2` and `execution-plan-v2`, keep their exact historical meanings. Current-generation contracts use these distinct persisted identities:

| Meaning | Run version | Persisted schema identity | Target type / file |
| --- | --- | --- | --- |
| Historical Competitive requirement | `research-v2` | `research-task-v2` | existing `ResearchTaskV2`; unchanged |
| Historical fixed Tool → Skill plan | `research-v2` | `execution-plan-v2` | existing `ExecutionPlanBody`; unchanged |
| Current-generation requirement | `research-v3` | `research-task-v3` | `ResearchTaskV3`; `research-task-v3.schema.json` |
| Current-generation heterogeneous DAG | `research-v3` | `execution-plan-v3` | `ExecutionPlanV3`; `execution-plan-v3.schema.json` |
| Current-generation deliverable envelope | `research-v3` | `research-deliverable-v3` | `ResearchDeliverableV3`; `research-deliverable-v3.schema.json` |
| Current-generation review | `research-v3` | `report-review-v3` | `ReportReviewV3`; `report-review-v3.schema.json` |
| Current-generation report document | `research-v3` | `report-document-v3` | `ReportDocumentV3`; `report-document-v3.schema.json` |

The ai-x names `research-task-v2` / `ResearchTaskV2`, `current-execution-plan` / `CurrentExecutionPlan`, `research-deliverable-v1`, `report-review-v1`, and `report-document-v1` are source-provenance aliases only. The source adapter translates them to `research-task-v3` / `ResearchTaskV3`, `execution-plan-v3` / `ExecutionPlanV3`, `research-deliverable-v3`, `report-review-v3`, and `report-document-v3` **before** target validation, canonical hashing, or persistence. No permissive alias maps a historical target identity to a current contract, and neither `current` nor `latest` is a persisted schema version.

Decoder dispatch starts with the Run's stored orchestration version and then requires the exact matching schema discriminator. A `research-v2` Run rejects either v3 identity; a `research-v3` Run rejects either v2 identity. Dispatch by payload shape is forbidden. `RequirementVersion.schema_version`, `ExecutionPlanVersion.schema_version`, payload discriminators, registry keys, and JSON Schema `$id` values must agree with their generation. Existing v2 rows, payloads, hashes, fixtures, and Artifact contents are never rewritten.

During the bounded drain, a v2 continuation could act only on a persisted v2 Run and only within the pre-approved old command semantics. The drain is complete. V2 is now historical-only: no new Run, Plan, Attempt, claim, send, approval, retry, recovery, settlement, repair, or purge mutation is available. Physical deletion requires a separate explicit authorization and implementation.

A `V2HistoryAdapter` must preserve the decoder and verified Artifact dependency closure required for:

- Requirement, Workflow, Plan, Attempt, Step, Invocation, and model/tool receipts;
- frozen Skill, Tool, model, resource, Evidence Policy, rubric, and template snapshots;
- Evidence, Claim Ledger, Deliverable, Review, Report, and v2 events;
- owner/project/workspace scoping, hash verification, corruption handling, and restart reads.

"Retire" means removal from the new-Run writer path. It does not authorize deleting contracts, Store rows, projections, or Artifact readers required by history.

### Canonical historical identity policy

Exact decoders and frozen fixtures use one complete categorized policy. Narrower collision lists must be labeled as such and must not be called complete.

- orchestration: `research-v2`;
- payload/schema: `claim-ledger-v1`, `competitive-analysis-output-v1`, `deliverable-document-v1`, `deterministic-review-v1`, `evidence-manifest-v1`, `evidence-source-v1`, `execution-plan-v2`, `problem-contract-v1`, `report-document-v1`, `research-task-v2`;
- resources: `competitive-analysis-review-v1`, `evidence-policy-v1`.

The combined historical set is exactly those thirteen identities. The current set is exactly `research-v3`, `research-task-v3`, `execution-plan-v3`, `research-deliverable-v3`, `report-review-v3`, and `report-document-v3`; the sets may not overlap.

### Runtime ownership

FastAPI no longer constructs a research-v2 `ResearchRuntime`; SQLite remains authoritative. The current composition root separates authorities as follows:

```text
active_writer: None
continuations: {}
readers: {research-v2 -> V2HistoryAdapter}
```

This is not permission to add a second Runtime or a module global. Historical GET projections remain pure reads, and no v2 background Task is reconstructed.

### Safe deletion gate

v2 writer code may be deleted only when all of the following are attested:

- no nonterminal v2 AgentRun;
- no PENDING, RUNNING, or RECOVERY_REQUIRED v2 Attempt;
- no open v2 clarification, Plan, Tool approval, recovery gate, or Inbox approval;
- no SENT or UNKNOWN v2 Invocation;
- no v2 Runtime background Task;
- no STAGING v2 Artifact or unsettled model/tool receipt;
- a frozen historical database fixture decodes without importing writer services;
- owner hiding, integrity failure, restart read, mutation rejection, and `off` rollback compatibility tests pass;
- the v2 history renderer mounts no mutation controls;
- retention, audit, architecture, and release owners approve deletion.

Migrations are additive. No v2 payload, hash, row, or Artifact content is rewritten into a current schema, and rollback performs no database downgrade.

### Named ownership boundary

Gate records use the following accountable owner IDs. The user approved one temporary binding for the exact scope **Gate 0 and isolated Slice 1 development only**. That exception does not satisfy production-cutover reviewer independence.

| Owner ID | Interim handle | Accountability |
| --- | --- | --- |
| `AX-SOURCE` | `@heyunshen` | immutable source identity, source approval, source quality, durable retention, source visual-fixture provenance |
| `AM-ARCH` | `@heyunshen` | ADR, schema namespace, owner registry, single-writer and cutover decision |
| `AM-CONTRACTS-HISTORY` | `@heyunshen` | v3 contracts, source adapter, immutable v2 decoder and historical database fixture |
| `AM-RUNTIME-STORE` | `@heyunshen` | atomic writer fence, completed drain and retirement checks |
| `AM-WEB` | `@heyunshen` | source baselines and stored-version-specific renderers |
| `AM-SECURITY-RETENTION` | `@heyunshen` | owner scope, integrity failure, retention and retired mutation rejection |
| `AM-RELEASE-QA` | `@heyunshen` | verifier, target characterization, zero-diff validation and Gate handoff |
| `AM-PRODUCT-RESEARCH` | `@heyunshen` | Slice 1 scope and rollout acceptance policy |

`AM-ARCH` plus `AM-CONTRACTS-HISTORY` accept this architecture/contracts package. `AM-ARCH` plus `AM-RELEASE-QA` authorize a final isolated Slice 1 handoff only after every verifier criterion passes. Production cutover requires a later approval with those two roles represented by distinct individuals and review evidence.

## Consequences

The migration cannot use simultaneous v2/v3 cohort writing. This reduces rollout flexibility but preserves one unambiguous production writer, deterministic catalog selection, and a rollback that never resurrects deprecated code.

The v2 decoder/projector dependency closure will outlive its writer. Some apparent duplication between immutable v2 contracts and current contracts is deliberate compatibility, not a refactoring defect.

`off` means no new research work and no new claims. Historical accounting remains readable, but retired v2 exposes no settlement, repair, or owner-authorized purge mutation.

Gate 0 can freeze the decision without changing runtime behavior. Slice 1 must separately implement and verify the durable writer fence, current contracts, versioned projection dispatch, and atomic cutover.

## Gate 0 verification

Gate 0 accepts this ADR's documentation boundary when:

- production route, model, Store, Runtime, frontend, Provider, and database paths have no Gate 0 behavior diff;
- the ai-x approved snapshot lock is exact and source-owner approved; durable retention and the remaining Gate criteria are still required before it becomes migration-authoritative;
- the target baseline and v2 compatibility dependency closure are recorded;
- current identities are exactly `research-task-v3`, `execution-plan-v3`, `research-deliverable-v3`, `report-review-v3`, and `report-document-v3`, while historical identities remain immutable;
- the future routing table is a decision contract only, not a reachable v3 branch;
- no Provider smoke or user-data migration was performed;
- `AM-ARCH` and `AM-CONTRACTS-HISTORY` have accepted this architecture/contracts package for the stated interim scope.

This ADR is **Accepted** for Gate 0 and isolated Slice 1 development. The focused verifier, rather than this prose status, determines whether an isolated Slice 1 handoff is authorized. Production cutover remains separately blocked.

### Closed Gate 0 evidence

The Accepted decision is now backed by the exact 24-image/eight-state baseline, the independently verified ten-case accepted-target characterization, the portable and independently scanned historical SQLite fixture, and the deterministic minimal source snapshot bundle. The bundle retains synthetic orphan commit `adf97f60f46ecceae5a2bc7f3d8c232484c334bd` at tree `ca63e2fdb4c3fcff0f50c8095a1497f8db4cdd12`; origin remains reviewed source commit `d7ec877fbff0684b0886cb86a7e09eb42ebf7d77` with the same tree. It intentionally contains no source history.

Final isolated-Slice handoff is evidence-driven: the release verifier must bind the complete Gate artifact manifest, including the lock, to the exact clean target commit/tree and must report all ten criteria passed. This closes Gate 0 only; it does not alter the single-active-writer decision, enable a production v3 route, or authorize production cutover.
