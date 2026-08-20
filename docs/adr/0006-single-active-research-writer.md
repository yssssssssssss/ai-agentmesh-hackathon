# ADR 0006: Single Active Research Writer and v2 Compatibility

## Status

Proposed on 2026-08-20. Architecture acceptance remains blocked until `AM-ARCH` and `AM-RELEASE-QA` are bound to accountable `@handle`s and attest the Gate 0 record. This ADR does not authorize Slice 1 or change the current default rollout state of `off`.

## Context

AgentMesh currently persists `v1` and `research-v2` Runs. The proposed ai-x parity mainline will eventually persist a distinct current-generation value, `research-v3`, without changing the meaning of existing payloads. A migration design that lets cohorts create new v2 and v3 research Runs at the same time would leave two production research writers and make fallback, catalog identity, and rollback ambiguous.

Gate 0 is documentation and source-freeze work only. It must not add a production v3 route, runtime, model value, Provider call, database migration, or user-data rewrite.

The terms in this decision are intentionally narrow:

- **writer**: the implementation allowed to create a new research Run and its first durable Workflow state;
- **continuation**: a version-specific command handler that may advance only a Run already persisted with that version during a bounded drain;
- **settlement**: honest terminal accounting for an external call that was already SENT; settlement does not authorize a new claim or replay;
- **reader**: an owner-scoped projector/decoder that never schedules work;
- **purger**: the owner-authorized tombstone path that removes retained content while preserving required audit facts.

Readers, purgers, narrow settlement, and bounded continuations are not new-Run writers. They still require explicit version dispatch and least authority.

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

Production has at most one active research writer generation globally:

| Production state | New eligible research | Existing active v2 | Historical v2 |
| --- | --- | --- | --- |
| `off` | v1 | no new claims; settle already-SENT calls only | read and owner-authorized purge |
| pre-cutover `preview` / `execute` | research-v2 | continue by stored version | read and owner-authorized purge |
| v3 validation | isolated environment only; production remains unchanged | production remains v2 | read and owner-authorized purge |
| v3 cutover | research-v3 | bounded continuation by stored version until drained | read and owner-authorized purge |
| post-drain | research-v3 | none | read, audit, integrity handling, and owner-authorized purge |
| rollback `off` | v1 | no new claims and no v2 writer reactivation | read and owner-authorized purge; settle already-SENT calls honestly |

The Slice 1 implementation is validated and accepted in an isolated environment while production continues to route eligible research to v2. Production changes only through a **separate, jointly approved atomic cutover** after isolated Slice 1 acceptance. At that cutover, all new eligible Competitive Runs switch together: after cutover v2 cannot create a new Run. An allowlist may control whether the selected current writer can execute or must remain preview-only; it must not choose v2 versus v3.

### Immutable routing and durable fencing

The client-turn receipt, immutable orchestration version, active-writer generation, and Run creation must be checked and persisted in one SQLite transaction. A stale process cannot create a Run for a retired generation. Continuation and read dispatch use the Run's stored version, not the current routing mode.

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

During the bounded drain, a v2 continuation may act only on a persisted v2 Run and only within the pre-approved old command semantics. After drain, v2 is historical-only: no new Run, Plan, Attempt, claim, send, approval, retry, or recovery work may be created. The remaining mutation exceptions are honest terminal settlement for already-SENT calls, integrity/audit bookkeeping, and owner-authorized tombstone purge.

A `V2HistoryAdapter` must preserve the decoder and verified Artifact dependency closure required for:

- Requirement, Workflow, Plan, Attempt, Step, Invocation, and model/tool receipts;
- frozen Skill, Tool, model, resource, Evidence Policy, rubric, and template snapshots;
- Evidence, Claim Ledger, Deliverable, Review, Report, and v2 events;
- owner/project/workspace scoping, hash verification, corruption handling, restart reads, and purge.

"Retire" means removal from the new-Run writer path. It does not authorize deleting contracts, Store rows, projections, or Artifact readers required by history.

### Runtime ownership

FastAPI continues to own one lifespan-scoped `ResearchRuntime`; SQLite remains authoritative. The future composition root separates authorities conceptually:

```text
active_writer: ResearchWriter | None
continuations: {stored_version -> ExistingRunContinuation}
readers: {stored_version -> ResearchProjectionReader}
```

This is not permission to add a second Runtime or a module global. GET and SSE remain pure reads. Runtime background Tasks remain disposable mechanisms reconstructed from durable state.

### Safe deletion gate

v2 writer code may be deleted only when all of the following are attested:

- no nonterminal v2 AgentRun;
- no PENDING, RUNNING, or RECOVERY_REQUIRED v2 Attempt;
- no open v2 clarification, Plan, Tool approval, recovery gate, or Inbox approval;
- no SENT or UNKNOWN v2 Invocation;
- no v2 Runtime background Task;
- no STAGING v2 Artifact or unsettled model/tool receipt;
- a frozen historical database fixture decodes without importing writer services;
- owner hiding, integrity failure, restart read, purge/tombstone, and `off` rollback compatibility tests pass;
- the v2 history renderer mounts no mutation controls;
- retention, audit, architecture, and release owners approve deletion.

Migrations are additive. No v2 payload, hash, row, or Artifact content is rewritten into a current schema, and rollback performs no database downgrade.

### Named ownership boundary

Gate records use the following accountable owner IDs. Each ID must be bound to one individual `@handle` before Gate 0 can pass:

| Owner ID | Named owner | Accountability |
| --- | --- | --- |
| `AX-SOURCE` | ai-x Source Custodian | immutable source lock, dispositions, source quality |
| `AM-ARCH` | AgentMesh Architecture Owner | this ADR, schema namespace, single writer, cutover |
| `AM-CONTRACTS-HISTORY` | Research Contracts and v2 History Owner | v3 contracts, source adapter, immutable v2 history decoder |
| `AM-RUNTIME-STORE` | Research Runtime and Store Owner | writer fence, drain, retirement gate |
| `AM-WEB` | Workbench and Projection Owner | visual baselines and versioned renderers |
| `AM-SECURITY-RETENTION` | Security, Audit and Retention Owner | security review, retention, purge/tombstone |
| `AM-RELEASE-QA` | Release Verification Owner | lock verifier, release gate, go/no-go record |
| `AM-PRODUCT-RESEARCH` | Product and Research Owner | Slice acceptance and rollout policy |

`AM-ARCH` and `AM-RELEASE-QA` jointly authorize isolated Slice 1 work. `AX-SOURCE` approves source authority only; it cannot authorize AgentMesh implementation or production cutover. No handle bindings were supplied in this Gate 0 run, so all roles remain explicitly unbound blockers.

## Consequences

The migration cannot use simultaneous v2/v3 cohort writing. This reduces rollout flexibility but preserves one unambiguous production writer, deterministic catalog selection, and a rollback that never resurrects deprecated code.

The v2 decoder/projector dependency closure will outlive its writer. Some apparent duplication between immutable v2 contracts and current contracts is deliberate compatibility, not a refactoring defect.

`off` means no new research work and no new claims. It does not permit falsifying or abandoning accounting for a call already SENT, and it does not disable owner-authorized purge.

Gate 0 can freeze the decision without changing runtime behavior. Slice 1 must separately implement and verify the durable writer fence, current contracts, versioned projection dispatch, and atomic cutover.

## Gate 0 verification

Gate 0 passes this ADR's documentation boundary only when:

- production route, model, Store, Runtime, frontend, Provider, and database paths have no Gate 0 behavior diff;
- the ai-x approved snapshot lock is exact and source-owner approved; durable retention and the remaining Gate criteria are still required before it becomes migration-authoritative;
- the target baseline and v2 compatibility dependency closure are recorded;
- current identities are exactly `research-task-v3`, `execution-plan-v3`, `research-deliverable-v3`, `report-review-v3`, and `report-document-v3`, while historical identities remain immutable;
- the future routing table is a decision contract only, not a reachable v3 branch;
- no Provider smoke or user-data migration was performed;
- `AM-ARCH` and `AM-RELEASE-QA` have accepted this ADR and the Gate record.

Until the last item and all other Gate criteria are attested, this ADR remains **Proposed** and Slice 1 remains on HOLD.
