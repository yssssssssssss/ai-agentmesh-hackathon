# Universal Skill Pool — Phase 2B Standard Execution

- Date: 2026-08-29
- Branch: `feature/universal-skill-pool-phase2b`
- Base: `fdc8e56` (`Add Universal Standard planning preview`)
- Status: local execution contract implemented; production enablement remains fail closed without verified Profile/release provenance

## Implemented locally

- Added the immutable `standard_universal_execution_v1` marker to new Universal Standard Runs and Plans.
- Enforced exact non-null Run/Plan/current-binary marker equality at approval, execution service, executor, Plan claim, and node claim boundaries.
- Preserved the permanent non-executability of Phase 2A Plans whose frozen execution marker is `null`, including after a newer binary recognizes v1.
- Allowed execution-time revalidation of approved built-in Universal candidates without broadening legacy Standard or DeepSearch v1 semantics.
- Revalidated Profile/Skill/capability-card identity, evidence Tool implementation identity, current grant/readiness, and frozen Resource manifests before execution.
- Kept `local_write` and `external_write` Universal candidates blocked with `write_execution_not_released`; this release only supports `read` and `draft` nodes.
- Added Task Catalog v2 Scenario/output-ID handling to Universal node prompts and result validation.
- Sealed trusted Universal web evidence and synthesis into lineage-bound, hash-verified artifacts before they can satisfy evidence or synthesis obligations; evidence is bound to the exact Tool call, cited result source, frozen witness, canonical source origin, source-count policy, and freshness policy.
- Sent only a dedicated safe node projection to synthesis and made the frozen synthesis output contract mandatory for model validation and deterministic fallback.
- Switched Universal completion/finalization to delivered output kinds, Scenario output IDs, scoped Scenario completion criteria, evidence artifacts, required atoms, required synthesis outputs, and the shared valid-partial-delivery predicate across normal, exceptional, restart, cancellation, and rollback paths.
- Preserved legacy Standard completion and current DeepSearch v1 behavior on their existing branches.

## Safety state

The binary recognizes the v1 execution contract, but the default runtime still cannot create Universal Runs unless the verified Profile trust root is available. No local fixture is treated as production approval. A Phase 2A Plan with `execution_contract_version=null` remains rejected even if the binary capability is later enabled.

## Local verification

- Backend regression: `1663 passed, 6 skipped`.
- Frontend: `161 passed`; production build and 500 KiB bundle gate passed.
- Ruff and `git diff --check`: passed.

## External gates still required

- independent CODEOWNER review and high-risk dual review;
- protected branch, merge queue, reviewed-blob verification, wheel attestation, and immutable release marker;
- reviewed release holdout and 500-request Preview observation window;
- real Planner/Embedding/Tool Provider acceptance;
- pre-production rollback, writer-lock, ingress, recovery, and production-shape concurrency drills.
