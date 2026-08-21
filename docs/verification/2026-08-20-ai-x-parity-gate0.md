# AI 工作台 ai-x Parity Gate 0 Verification

> 日期：2026-08-21
>
> Evidence status: **COMPLETE for exact clean-target verification**
>
> Authorized scope: **Gate 0 and isolated Slice 1 development only**. Production cutover remains
> unauthorized and requires a later decision by independent Architecture and Release QA reviewers.

This Gate changes evidence, documentation, the lock/verifier, deterministic screenshots, and sanitized
fixtures only. It does not modify production routes, Runtime, Store, models, frontend production code,
migrations, Provider configuration, or user data. The release verifier's result for the exact clean
committed target is authoritative; prose is not authorization.

## 1. Frozen source and minimal durable retention

| Field | Value |
| --- | --- |
| logical repository | `https://github.com/yssssssssssss/ai-x.git` |
| reviewed source commit | `d7ec877fbff0684b0886cb86a7e09eb42ebf7d77` |
| reviewed source tree | `ca63e2fdb4c3fcff0f50c8095a1497f8db4cdd12` |
| snapshot commit | `adf97f60f46ecceae5a2bc7f3d8c232484c334bd` |
| snapshot tree | `ca63e2fdb4c3fcff0f50c8095a1497f8db4cdd12` |
| advertised ref | `refs/heads/parity` |
| bundle path | `agentmesh/research_catalog/source-bundles/ai-x-parity-source-d7ec877.bundle` |
| bundle SHA-256 | `59169aa27438d973e2344670c7e995c937cefa68a90da5b7eddbc3eb7deb6075` |
| bundle bytes | `14103048` |

The retained object is a deterministic parentless snapshot, not the original source commit and not
source history. Equal Git tree IDs bind the synthetic snapshot bytes and modes to the reviewed source
commit. The verifier requires one advertised ref, one root commit, the exact tree, strict full `fsck`,
no hidden/unreachable objects, and an independent scan of all exported blobs. The committed attestation
also records deterministic rebuild, restore, all-blob scan, extracted-PDF scan, and the image-OCR
limitation.

## 2. Exact target and artifact binding

The target base remains commit `dec6b55b3e97913c052ee2b665c063aec77a9dd3`, tree
`eb39f8159afb421233b657747192447734fd8b07`. The lock stores every non-lock Gate artifact's A/M status,
mode, SHA-256, byte count, and normalized path. To avoid commit self-reference, the release verifier
resolves the exact accepted commit and tree after commit, hashes the complete artifact set including the
lock, requires target `HEAD` to equal that commit, requires an empty status, and requires the executing
verifier bytes to equal the verifier blob in that commit. Deletions, renames, symlinks, Gitlinks,
nonregular modes, path collisions, and changes outside the narrow Gate allowlist fail validation.

## 3. Owners, architecture, and handoff

The authenticated Gate instruction binds all eight owner IDs to `@heyunshen` for this interim scope.
`docs/verification/ai-x-parity-evidence/gate0-owner-acceptance.json` records exact accountabilities and
criterion ownership. ADR 0006 and the migration plan remain Accepted for Gate 0 and isolated Slice 1.
`docs/verification/ai-x-parity-evidence/gate0-handoff.json` records final `AM-ARCH` and `AM-RELEASE-QA`
acceptance, the clean-target/complete-manifest binding policy, and the explicit production-cutover
prohibition. The same-person interim binding is not valid for production cutover.

## 4. Source quality

`source-quality.json` binds the frozen source identity, minimal bundle bytes, snapshot/origin mapping,
all-blob scan result, inherited `pnpm quality` result (1443 passed, 12 skipped, zero failed), and inherited
web build pass. Those source commands were not rerun. No real Provider smoke, release browser validation,
or user-data access is claimed.

## 5. Exact contract and history inventories

`tests/fixtures/ai_x_parity/` contains exactly seven canonical payloads plus its manifest.
`tests/fixtures/ai_x_history/` contains exactly the SQLite fixture, portable characterizer, attestation,
`SHA256SUMS`, and manifest. The verifier traverses both roots without following links and rejects nested
files/directories, symlinks, nonregular entries, duplicate normalized paths, duplicate IDs, duplicate
manifest rows, noncanonical JSON, and undeclared files.

The history characterizer derives the repository root from its own path, uses a repository-relative
output, records a repository-relative fixture path, and uses credential regexes with real boundaries.
The verifier does not trust `sanitization.passed`: it opens SQLite read-only, reruns integrity checking,
scans `sqlite_schema`, enumerates every table and column, and examines every non-null text and BLOB cell,
including recursively decoded JSON and nonempty sensitive keys.

## 6. Visual matrix

`docs/verification/ai-x-parity-baselines/` contains exactly 24 unique PNGs, eight canonical state JSON
files, and one canonical manifest. It covers the exact cross-product:

- states: `approval`, `candidates`, `clarify`, `dag_or_executing`, `idle`, `paused`, `plan`, `text_report`;
- viewports: `wide` 1440×900, `desktop` 1280×800, and `mobile` 390×844 at DPR 1.

The verifier rejects duplicate tuples, paths, PNG hashes, state IDs, state fixture IDs/hashes,
non-tuple-derived paths, wrong dimensions, wrong browser/source identity, omitted entries, and nested or
linked extras. Capture used Chrome `151.0.7922.170`, one browser/context/page/pass, synthetic fixtures,
the exact backend `/api/` mock predicate, and zero Provider calls. Remaining visual risk is browser/font
rasterization drift and lack of a human semantic pixel review in the capture worker.

## 7. Ten-case accepted-target characterization

`docs/verification/ai-x-parity-evidence/target-characterization/` contains the complete ten-case report,
ten independently hashed case documents, portable characterizer, environment/source hashes, sanitized
SQLite fixture, attestation, `SHA256SUMS`, and exact manifest. It is bound to the production target base
and records the Gate head used during execution. All 103 production Python files matched the base bytes.
The evidence records zero network attempts, zero external Provider calls, synthetic identities only, and
passed routing, replay, fail-closed, rollback, owner read/hiding, corruption, restart, purge, and historical
read contracts.

Machine-local prefixes were removed from the copied fixture and metadata, all dependent hashes were
regenerated, and SQLite integrity was rechecked. The verifier independently validates every declared
hash, every compact canonical JSON document, exact recursive inventory, unique case IDs/sequences,
all ten mapped Gate case IDs, and all SQLite text/BLOB content.

## 8. Authorization derivation

Gate facts are evidence-driven:

1. exact owner ledger;
2. source origin plus minimal durable snapshot;
3. canonical parity lock and contract fixtures;
4. inherited source quality plus scan evidence;
5. exact browser matrix;
6. accepted ADR/contracts;
7. exact ten-case characterization;
8. narrow Gate-only target diff plus clean exact target;
9. independently scanned v2 compatibility fixture and accepted Slice 1 plan;
10. accepted handoff, all prior facts, exact committed verifier, complete artifact binding, and clean target.

`slice_1_authorized=true` is valid only when all ten predicates pass in release mode. It authorizes an
isolated Slice 1 branch from the exact reported target commit. `production_cutover_authorized` remains
`false` under every Gate 0 outcome.
