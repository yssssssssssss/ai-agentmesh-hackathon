# AI 工作台 ai-x Parity Gate 0 Verification

> 日期：2026-08-21
>
> Observation status: **HOLD pending exact visual matrix, complete target characterization, and final clean-commit handoff**
>
> Scope accepted by interim owner `@heyunshen`: **Gate 0 and isolated Slice 1 development only**. Production cutover is not authorized and remains subject to a separate decision by independent Architecture and Release QA reviewers.

This Gate changes only evidence, documentation, the lock/verifier, and sanitized fixtures. It does not modify production routes, Runtime, Store, models, frontend production components, migrations, Provider configuration, or user data. A dated prose status is not authorization; the focused verifier output is authoritative.

## 1. Frozen source and durable retention

| Field | Value |
| --- | --- |
| repository | `https://github.com/yssssssssssss/ai-x.git` |
| advertised ref | `refs/heads/agent/ai-x-parity-source-freeze-final` |
| source commit | `d7ec877fbff0684b0886cb86a7e09eb42ebf7d77` |
| source tree | `ca63e2fdb4c3fcff0f50c8095a1497f8db4cdd12` |
| bundle path | `agentmesh/research_catalog/source-bundles/ai-x-parity-source-d7ec877.bundle` |
| bundle SHA-256 | `bc498a854c0b60835036e87dfd576d37aa233c65833cdbde493a10504670369f` |
| bundle bytes | `16185062` |
| freeze manifest SHA-256 / bytes | `ffac6f591ca7e37739fd516d5d447f9b83ff351b86e1988da4c7cc8527850fb3` / `9611` |

`git bundle verify` reports the exact advertised ref and complete history. The focused verifier clones only the bundle into a new temporary repository, runs `git fsck --full --strict`, and requires the restored commit/tree above. This prevents an incomplete bundle from borrowing prerequisite objects from an existing checkout.

The bundle is evidence-only. `agentmesh/research_catalog/source-bundles/` has no `__init__.py`, is absent from `tool.setuptools.package-data`, and is never scanned by a runtime catalog/Skill loader. The verifier reads it only through its explicit evidence path.

## 2. Frozen target and complete Gate artifact binding

| Field | Value |
| --- | --- |
| target repository | `https://github.com/yssssssssssss/ai-agentmesh-hackathon.git` |
| target base commit | `dec6b55b3e97913c052ee2b665c063aec77a9dd3` |
| target base tree | `eb39f8159afb421233b657747192447734fd8b07` |
| protected runtime behavior | unchanged |

The v3 lock records every non-lock Gate artifact's status, mode, SHA-256, bytes, and path. The lock cannot truthfully embed the commit containing itself. The verifier therefore resolves the exact accepted target commit/tree at execution time, reads all changed blobs from that commit, hashes the complete artifact manifest including the lock, verifies the lock blob independently, requires the base as ancestor, rejects changes outside the narrow allowlist, and optionally requires clean target `HEAD`. This explicit no-self-reference rule replaces path-only evidence.

## 3. Owner binding and acceptance scope

The authenticated Gate instruction temporarily binds every role to `@heyunshen` only for **Gate 0 and isolated Slice 1 development**:

| Owner ID | Interim handle | Accountability |
| --- | --- | --- |
| `AX-SOURCE` | `@heyunshen` | immutable source identity, source approval, source quality, durable retention, source visual-fixture provenance |
| `AM-ARCH` | `@heyunshen` | ADR, schema namespace, owner registry, single-writer and cutover decision |
| `AM-CONTRACTS-HISTORY` | `@heyunshen` | v3 contracts, source adapter, immutable v2 decoder and historical database fixture |
| `AM-RUNTIME-STORE` | `@heyunshen` | atomic writer fence, v2 continuation, drain and retirement checks |
| `AM-WEB` | `@heyunshen` | source baselines and stored-version-specific renderers |
| `AM-SECURITY-RETENTION` | `@heyunshen` | owner scope, integrity failure, retention, purge and tombstone behavior |
| `AM-RELEASE-QA` | `@heyunshen` | verifier, target characterization, zero-diff validation and Gate handoff |
| `AM-PRODUCT-RESEARCH` | `@heyunshen` | Slice 1 scope and rollout acceptance policy |

The signed-attribution record is `docs/verification/ai-x-parity-evidence/gate0-owner-acceptance.json`. `AM-ARCH` plus `AM-CONTRACTS-HISTORY` accept the architecture/contracts package. `AM-ARCH` plus `AM-RELEASE-QA` may authorize isolated Slice 1 only when every verifier predicate passes. The interim same-person binding is expressly invalid for production cutover; production requires separate independent Architecture and Release QA reviewers.

Criterion ownership is exact:

| Criterion | Required owners |
| --- | --- |
| gate0-01 | `AM-ARCH` |
| gate0-02 | `AX-SOURCE` |
| gate0-03 | `AX-SOURCE`, `AM-RELEASE-QA` |
| gate0-04 | `AX-SOURCE`, `AM-RELEASE-QA` |
| gate0-05 | `AX-SOURCE`, `AM-WEB` |
| gate0-06 | `AM-ARCH`, `AM-CONTRACTS-HISTORY` |
| gate0-07 | `AM-RELEASE-QA` |
| gate0-08 | `AM-ARCH`, `AM-RELEASE-QA` |
| gate0-09 | `AM-CONTRACTS-HISTORY`, `AM-RUNTIME-STORE`, `AM-WEB`, `AM-SECURITY-RETENTION` |
| gate0-10 | `AM-ARCH`, `AM-RELEASE-QA` |

## 4. Source quality evidence and limitations

`docs/verification/ai-x-parity-evidence/source-quality.json` binds inherited records at the frozen lineage:

- `pnpm quality`: 1455 total, 1443 pass, 12 skip, 0 fail;
- `pnpm --dir apps/web build`: passed;
- source package contract: Node `>=22`, pnpm `9.12.1`;
- post-freeze work is limited to bundle materialization, hash/manifest, sanitization, and portability checks.

These commands were **not rerun by the Gate writer**. The verifier hashes their immutable source-tree record and labels the result `inherited_frozen_lineage`. No real Provider smoke, Provider release validation, or browser release validation is claimed.

## 5. Contract fixtures and canonical identities

`tests/fixtures/ai_x_parity/` contains exactly seven canonical characterization payloads plus `manifest.json`. They are not executable tests. The verifier rejects duplicate JSON keys; requires canonical UTF-8 JSON, exact paths and fixture IDs, no undeclared files, source/target identities, and all 33 source-contract blob hashes from the verified bundle or target base commit.

The complete historical identity policy is categorized as follows:

- orchestration: `research-v2`;
- payload/schema: `claim-ledger-v1`, `competitive-analysis-output-v1`, `deliverable-document-v1`, `deterministic-review-v1`, `evidence-manifest-v1`, `evidence-source-v1`, `execution-plan-v2`, `problem-contract-v1`, `report-document-v1`, `research-task-v2`;
- resources: `competitive-analysis-review-v1`, `evidence-policy-v1`.

The combined set is exactly thirteen identities in the lock, fixture manifest, historical characterization fixture, and SQLite fixture manifest. The current set is exactly `research-v3`, `research-task-v3`, `execution-plan-v3`, `research-deliverable-v3`, `report-review-v3`, and `report-document-v3`, with no overlap.

## 6. Historical v2 database evidence

`tests/fixtures/ai_x_history/` contains the copied SQLite fixture, focused offline characterizer, attestation, `SHA256SUMS`, and a repository manifest. The fixture is 425,984 bytes with SHA-256 `cd96b111ae3d2bb520576f3c3c470cf62a5ad73f9020c56c54561a3349c4794a`.

The verifier checks every declared hash/size, exact directory contents, SQLite `PRAGMA integrity_check`, absent WAL/SHM companions, target base identity, sanitization, zero network/Provider use, exact stored-version dispatch, owner hiding, corruption rejection, restart read without scheduling, purge/tombstone behavior, and the canonical historical identity set. This is historical compatibility evidence; it does not authorize rewriting v2 rows or activating a v2 writer.

## 7. Browser baseline disposition

`/tmp/ai-x-gate0-baselines-v2` is finalized and sanitized, and its ten files cover the eight requested workflow states at 1440×900 plus print and mobile idle. It does **not** satisfy the locked exact visual policy: eight states × three viewports (1440×900, 1280×800, and 390×844), exactly 24 unique PNGs with state-fixture hashes and no extra files. It was therefore not copied as Gate evidence. Transient or blocker-only screenshots are never promoted.

The verifier derives visual availability only after the exact 24-tuple matrix, image dimensions, browser/environment pins, hashes, sanitization, uniqueness, and directory exactness all pass. Visual identity remains a handoff blocker.

## 8. Canonical routing and architecture acceptance

ADR 0006 and the migration plan are Accepted by interim owner `@heyunshen` only for Gate 0 and isolated Slice 1 development:

| Stage | `off` | `preview` / `execute` eligible Competitive request | Other request | Selected writer unavailable |
| --- | --- | --- | --- | --- |
| Gate 0 production / pre-cutover | v1 | research-v2 | v1 | fail closed; no alternate writer |
| Isolated Slice 1 validation | v1 | research-v3, isolated only | v1 | fail closed |
| Separately approved production cutover | v1 | globally active research-v3 | v1 until later task-type slices are accepted | fail closed; never v2/v1 fallback |

Replay by `client_turn_id` precedes routing. Slice 1 covers only Competitive Text. The allowlist chooses preview versus execute, never v2 versus v3. `off` creates no new versioned research Workflow or research claims. Production cutover remains separately blocked.

## 9. Authorization observation and residual blockers

The lock builder derives Gate facts from committed JSON records and exact artifacts; it does not use literal false placeholders. The focused verifier independently derives the final decision. As of this evidence set:

- source bundle, interim owners, inherited source quality, contract fixtures, architecture acceptance, zero-production-diff policy, and historical SQLite evidence are available;
- exact 24-image browser evidence is absent;
- the historical characterizer passes five relevant cases, but the complete ten-case accepted-target characterization report is absent;
- final handoff cannot pass until all prior criteria and exact clean target commit/tree evidence pass.

Therefore `slice_1_authorized` must remain `false` and the result is **HOLD**. Even a future `true` result authorizes only an isolated Slice 1 branch from the exact accepted Gate commit. It never authorizes production cutover.
