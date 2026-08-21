# Slice 1 foundation entry record

Date: 2026-08-21
Base commit: `288c3b361ac3ac761e804570650f1a2a517ae0e8`
Scope: isolated Slice 1 Competitive Text foundation only

## Authorization and writer boundary

The user explicitly authorized actual Slice 1 development in the isolated
`agent/ai-x-parity-slice1` worktree based on the exact closed Gate 0 commit above. This authorization
covers the non-production contract, catalog, source-adapter, port, and focused-test foundation in this
record. It does not authorize a production cutover.

There is one active implementation writer for this isolated foundation package. The architecture
continues to require one active research writer generation per composition. This package does not
instantiate a writer or composition, and it does not add `research-v3` to a production model, route,
Store codec, migration, Provider adapter, default flag, or UI branch.

Production remains unchanged:

- the active production research writer is `research-v2`;
- historical v2 identities and canonical hashes retain their existing meanings;
- `research-v3` is available only as a non-production Python contract/catalog namespace;
- `production_cutover_authorized=false`.

## Human visual semantic review

The user explicitly deferred the human visual semantic review of the frozen ai-x Workbench matrix to
Slice 1 completion. The review is deferred, not waived. This foundation contains no frontend branch and
therefore does not claim visual acceptance.

## Foundation contents

- Exact generation discriminators are frozen to six values: `research-v3`, `research-task-v3`,
  `execution-plan-v3`, `research-deliverable-v3`, `report-review-v3`, and `report-document-v3`.
- Supporting/persisted resource identities are explicit: `problem-graph-v1`, `plan-candidates-v3`,
  `research-control-snapshot-v3`, `competitive-analysis-text-v1`, and `evidence-manifest-v3`.
  The complete persisted/resource set is asserted disjoint from the canonical thirteen v2 identities;
  it is deliberately not aliased or described as the active/current production generation.
- Strict target contracts cover `research-task-v3`, `execution-plan-v3`,
  `evidence-manifest-v3`, `research-deliverable-v3`, `report-review-v3`, and `report-document-v3`.
  The Evidence Manifest binds every public text source and verified Artifact pointer to one Run, Plan,
  Attempt, Step contract, real Tool identity, and receipt.
- Supporting `problem-graph-v1`, candidate, control-snapshot, and Competitive Text payload contracts.
- A generation-specific canonical JSON/hash algorithm that does not modify research-v2 hashing.
  Arbitrary JSON fields use recursively frozen mappings/tuples and defensive serialization; frozen
  catalog documents verify their canonical content hash and byte count.
- Committed Draft 2020-12 schemas mirror the Pydantic contracts for expressible same-record structure,
  including required discriminators, scalar-array uniqueness, and Review check/dimension cardinality.
  The parity claim excludes only canonical hash bindings and cross-record lineage/ownership/readback
  invariants, which remain enforced at typed model and Port boundaries.
- Exact source-only ai-x contract models and explicit source-to-target adapters, including Deliverable,
  Review, and Report shapes. Source aliases are not target registry keys.
- A package-relative, hash-verifying Competitive Text catalog containing only the selected locked source
  assets required by Slice 1. The evidence-only Git bundle is not included by the package-data rule.
- Domain ports for requirement and ProblemGraph planning, capability resolution, candidate generation
  and compilation (with the sealed ProblemGraph reference supplied alongside its verified body),
  heterogeneous actor execution, delivery, review, report composition, typed repository reads, verified
  Artifact readback, clock, and IDs. Actor completion envelopes retain Run/Plan/Attempt/Step/actor/contract
  lineage independent of parallel completion order; Review receives the verified Manifest and Artifact
  contents explicitly.
- A non-production `research-workbench-aggregate-v1` DTO/schema and eight canonical fixtures freeze the
  idle, clarify, candidates, plan, approval, executing DAG, paused recovery, and text-report projections.
  The aggregate includes an explicit read-only `research-v2-history` discriminator and is not connected to
  the production research-v2 API.

## Locked source

The imported source blobs are copied verbatim from the retained Gate 0 snapshot tree
`ca63e2fdb4c3fcff0f50c8095a1497f8db4cdd12`, corresponding to reviewed ai-x commit
`d7ec877fbff0684b0886cb86a7e09eb42ebf7d77`. `source-snapshot.json` records every selected path and
SHA-256. Runtime loading uses package resources and never reads the mutable ai-x checkout.

## Lane ownership after the corrective contract baseline

The exact corrective foundation baseline is
`55f89846ba329084b93ac785cbc1900bbd2683cc` (`Correct research v3 foundation contracts`). After that
SHA, lane ownership for follow-on isolated Slice 1 work is explicit:

| Lane | Accountable owner | Boundary after the corrective SHA |
| --- | --- | --- |
| Evidence, contracts, schemas, source adapters, and historical discriminators | `AM-CONTRACTS-HISTORY` | Owns strict identities, lineage, canonical fixtures, and v2 read-only compatibility; no runtime writes. |
| Workbench aggregate DTO/schema and eight-state fixture semantics | `AM-WEB` | Owns stored-version-specific projection shape; no production API or current UI wiring in this package. |
| Repository, Artifact readback, execution, and recovery adapters | `AM-RUNTIME-STORE` | May implement the frozen Ports later; cannot change their contracts or make v3 reachable without review. |
| Integrity, evidence pointer verification, and retention behavior | `AM-SECURITY-RETENTION` | Reviews fail-closed readback and lineage checks before any isolated execution integration. |
| Focused seam verification and isolated handoff evidence | `AM-RELEASE-QA` | Owns contract/schema/fixture verification; production-cutover authority remains separate. |
| Scope and Competitive Text acceptance | `AM-PRODUCT-RESEARCH` | Keeps Slice 1 text-only and excludes multimodal capabilities. |

All interim owner IDs remain bound to `@heyunshen` for Gate 0 and isolated Slice 1 only, as recorded in
ADR 0006. The seam package has one writer; subsequent lanes may consume the frozen package but must not
silently edit another lane's contract.

## Follow-on boundary

Later lanes may implement these ports in an isolated composition. They must not make a Store write,
Provider call, production route, default, migration, or current Workbench branch reachable without a
separate integration decision and the required Slice 1 acceptance gates. Human visual semantic review
remains due at Slice 1 completion.
