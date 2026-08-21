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

- Strict target contracts for `research-task-v3`, `execution-plan-v3`,
  `research-deliverable-v3`, `report-review-v3`, and `report-document-v3`.
- Supporting `problem-graph-v1`, candidate, control-snapshot, and Competitive Text payload contracts.
- A generation-specific canonical JSON/hash algorithm that does not modify research-v2 hashing.
- Exact source-only ai-x contract models and explicit source-to-target adapters. Source aliases are not
  target registry keys.
- A package-relative, hash-verifying Competitive Text catalog containing only the selected locked source
  assets required by Slice 1. The evidence-only Git bundle is not included by the package-data rule.
- Domain ports for requirement and ProblemGraph planning, capability resolution, candidate generation
  and compilation, heterogeneous actor execution, delivery, review, report composition, repository,
  clock, and IDs.

## Locked source

The imported source blobs are copied verbatim from the retained Gate 0 snapshot tree
`ca63e2fdb4c3fcff0f50c8095a1497f8db4cdd12`, corresponding to reviewed ai-x commit
`d7ec877fbff0684b0886cb86a7e09eb42ebf7d77`. `source-snapshot.json` records every selected path and
SHA-256. Runtime loading uses package resources and never reads the mutable ai-x checkout.

## Follow-on boundary

Later lanes may implement these ports in an isolated composition. They must not make a Store write,
Provider call, production route, default, migration, or current Workbench branch reachable without a
separate integration decision and the required Slice 1 acceptance gates. Human visual semantic review
remains due at Slice 1 completion.
