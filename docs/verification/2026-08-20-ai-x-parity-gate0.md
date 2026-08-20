# AI 工作台 ai-x Parity Gate 0 Verification

> 日期：2026-08-20
>
> Gate 状态：**HOLD — final source snapshot 已批准并锁定；Slice 1 entry criteria 未全部满足**
>
> 本 Gate 只变更 source lock、验证脚本、架构文档和脱敏 characterization fixtures。没有修改 production route、Runtime、Store、model、frontend production component、migration、Provider 配置或用户数据；没有运行 Provider、browser capture、pytest、Ruff、frontend test/build 或 migration。

## 1. Current determination

ai-x 的 dirty-candidate blocker 已由 immutable Git snapshot 关闭。AgentMesh lock v2 从 final commit tree 枚举每个 regular blob，完整划分 included/excluded，并从已哈希 registry 派生 capability objects/counts。该事实不等于 Slice 1 authorization。

当前仍为 **HOLD**，因为 durable source retention、accountable handle bindings、source quality、browser baseline、architecture acceptance、executed target characterization、frozen v2 database fixture 和 accepted Gate 0 handoff commit 尚未全部存在。Lock 以 `lock_result=valid` 与 `authorization_result=hold` 区分“结构与 source integrity 有效”和“可开始 Slice 1”。

## 2. Frozen target and zero-behavior boundary

| Field | Value |
| --- | --- |
| target base commit | `dec6b55b3e97913c052ee2b665c063aec77a9dd3` |
| target base tree | `eb39f8159afb421233b657747192447734fd8b07` |
| target branch | `agent/ai-x-parity-gate0` |
| current production versions | `v1`, `research-v2`; Gate 0 does not add reachable `research-v3` |
| current rollout default | `off` |
| production diff | none; Gate files are documentation, lock/verifier, and sanitized fixtures only |

Protected production boundaries remain unchanged:

- `agentmesh/routes/`, `agentmesh/models.py`, `agentmesh/store.py`, `agentmesh/app.py`;
- `agentmesh/research_orchestration/`;
- `agentmesh-demo/src/`;
- database migrations, Provider/Tool/Lab implementation, Provider configuration, and `data/`.

## 3. Owner-approved immutable ai-x source

| Field | Locked value |
| --- | --- |
| logical repository | `https://github.com/yssssssss/ai-x.git` |
| branch label | `agent/ai-x-parity-source-freeze-final` |
| snapshot commit | `d7ec877fbff0684b0886cb86a7e09eb42ebf7d77` |
| snapshot tree | `ca63e2fdb4c3fcff0f50c8095a1497f8db4cdd12` |
| snapshot parent / approved content commit | `3a5fafe18a13714186150489c8434f7c5a58c887` |
| approved content tree | `00b7e87b0c9c592799d15884bc69d7dd0069f040` |
| base commit | `6c9f19fb8109ca6882241bc903d82332a9da0d5e` |
| final freeze manifest | `docs/development/ai-x-parity-source-freeze.json` |
| final manifest SHA-256 / bytes | `ffac6f591ca7e37739fd516d5d447f9b83ff351b86e1988da4c7cc8527850fb3` / `9611` |
| required-reference manifest | `90cce776ff548dad8537a8208e58a0fccc1204ac682917edcd2d946e8787dd66` (21 files) |
| migration guide SHA-256 | `5c0df919394ca33f22b996c9dcf9be060ed820e6c53c7752e6f3951c3d0169b2` |

Verified relationship: final snapshot has one parent; that parent equals the approved content commit; its tree equals the approved content tree; and `parent..snapshot` has one change, a **modified** freeze manifest.

The source manifest describes the approved content tree as “pre-manifest/non-self-referential,” but the parent tree contains the predecessor manifest blob. The target lock records this metadata discrepancy and relies only on the actual Git parent/tree/single-modified-path relationship.

`owner_approval=approved_snapshot` is tied to the final freeze manifest. `authoritative_for_migration=false` remains truthful because no protected remote ref, signed tag, or verified Git bundle was supplied. A local branch label alone is not durable-retention evidence.

### 3.1 Complete inventory and derived capabilities

The v2 verifier reads only commit blobs via `git ls-tree` and `git cat-file --batch`. It rejects unsupported modes, symlinks/Gitlinks, invalid/non-normalized paths, case-fold collisions, prohibited path classes, omitted paths, overlaps, bad dispositions, and mode/hash/size/category/reason drift. Included, excluded, per-category, and whole-tree manifests include mode, SHA-256, byte length, and path.

The verifier parses duplicate-key-rejecting YAML and compares the full normalized inventory derived from:

- `orchestrator/skill-registry.yaml` — 22 Skills, entries, task/input/visual roles, Tool references, schemas, risk;
- `orchestrator/tool-registry.yaml` plus each Tool manifest — 9 Tools, 7 active / 2 draft, adapter/tier/auth/risk/resources;
- `orchestrator/deliverable-registry.yaml`, evidence policy, templates — 5 authoritative task mappings;
- `orchestrator/decision-graph.yaml` — 7 Decision Nodes with tiers and full applicability;
- exact source paths — 5 Labs, ports/source manifests, schemas/prompts/rubrics/templates, knowledge, Skill bodies, references;
- exact CSS declarations in `:root` and `.report-document`.

Tool registry status is inventory, not execution readiness. O2 and Playwright remain draft; five source Labs remain unauthenticated and require later security review.

## 4. Persisted schema identity decision

| Meaning | Run version | Persisted schema identity | Target type / file |
| --- | --- | --- | --- |
| Historical Competitive requirement | `research-v2` | `research-task-v2` | existing `ResearchTaskV2`; unchanged |
| Historical Tool → Skill plan | `research-v2` | `execution-plan-v2` | existing `ExecutionPlanBody`; unchanged |
| Current requirement | `research-v3` | `research-task-v3` | `ResearchTaskV3`; `research-task-v3.schema.json` |
| Current heterogeneous DAG | `research-v3` | `execution-plan-v3` | `ExecutionPlanV3`; `execution-plan-v3.schema.json` |
| Current deliverable envelope | `research-v3` | `research-deliverable-v3` | `ResearchDeliverableV3`; `research-deliverable-v3.schema.json` |
| Current review | `research-v3` | `report-review-v3` | `ReportReviewV3`; `report-review-v3.schema.json` |
| Current report document | `research-v3` | `report-document-v3` | `ReportDocumentV3`; `report-document-v3.schema.json` |

Source mapping is explicit:

| ai-x provenance alias | AgentMesh persisted identity |
| --- | --- |
| `research-task-v2` / `ResearchTaskV2` | `research-task-v3` / `ResearchTaskV3` |
| `current-execution-plan` / `CurrentExecutionPlan` | `execution-plan-v3` / `ExecutionPlanV3` |
| `research-deliverable-v1` | `research-deliverable-v3` / `ResearchDeliverableV3` |
| `report-review-v1` | `report-review-v3` / `ReportReviewV3` |
| `report-document-v1` | `report-document-v3` / `ReportDocumentV3` |

Translation occurs before target validation, hashing, and persistence. Decoder dispatch begins from the Run's stored version and then requires the matching discriminator. Shape dispatch, historical-to-current aliases, and persisted `current`/`latest` identities are forbidden. Historical v2 rows, payloads, hashes, fixtures, and Artifacts are never rewritten.

## 5. Named ownership ledger

These are canonical accountable owner IDs. An owner is not assigned until exactly one individual `@handle` is recorded. No reliable bindings were provided, so every role is currently **unbound** and Gate criterion 1 fails.

| Owner ID | Named owner | Current binding | Accountability |
| --- | --- | --- | --- |
| `AX-SOURCE` | ai-x Source Custodian | unbound | source lock, approval, quality, durable retention |
| `AM-ARCH` | AgentMesh Architecture Owner | unbound | ADR, schema namespace, single writer, atomic cutover |
| `AM-CONTRACTS-HISTORY` | Research Contracts and v2 History Owner | unbound | v3 contracts, source adapter, v2 history adapter |
| `AM-RUNTIME-STORE` | Research Runtime and Store Owner | unbound | writer fence, drain, retirement gate |
| `AM-WEB` | Workbench and Projection Owner | unbound | visual baselines and versioned renderers |
| `AM-SECURITY-RETENTION` | Security, Audit and Retention Owner | unbound | security review, retention, purge/tombstone |
| `AM-RELEASE-QA` | Release Verification Owner | unbound | lock verifier, release gate, go/no-go |
| `AM-PRODUCT-RESEARCH` | Product and Research Owner | unbound | Slice acceptance and rollout policy |

`AM-ARCH` and `AM-RELEASE-QA` jointly authorize isolated Slice 1 work. `AX-SOURCE` approves source authority only. Production cutover is a separate approval after isolated Slice 1 acceptance.

## 6. v2 history, retirement, and security work package

`AM-CONTRACTS-HISTORY` owns the future `V2HistoryAdapter` and immutable decoder/projector closure. It must cover Requirement, Workflow, Plan, Attempt, Step, Invocation, receipts, snapshots, Evidence, Claim, Deliverable, Review, Report, events, owner/project/workspace scope, hash verification, corruption, restart read, and purge.

`AM-RUNTIME-STORE` owns the retirement gate: no nonterminal v2 Run/Attempt, open gate, SENT/UNKNOWN Invocation, background task, STAGING Artifact, or unsettled receipt may remain. `AM-WEB` owns a mutation-free historical renderer. `AM-SECURITY-RETENTION` owns owner hiding, integrity failure, audit retention, and purge/tombstone review. A frozen historical database fixture is still missing, so this work package is planned but not accepted.

## 7. Copied characterization evidence

`tests/fixtures/ai_x_parity/` contains the seven deterministic payload fixtures and their self-excluding `manifest.json`, copied byte-for-byte from `/tmp/ai-x-gate0-fixtures`. They are sanitized characterization assets, not executable/schema-valid payloads. They intentionally preserve historical target `research-task-v2` and `execution-plan-v2` identities while documenting the future v3 translation boundary.

No finalized files existed at `/tmp/ai-x-gate0-baselines`: only `.capture-work` files were present, with no screenshot or manifest. Nothing from that work directory was copied, and no missing screenshot was invented. `docs/verification/ai-x-parity-baselines/` therefore remains absent and visual identity remains a blocker.

## 8. Slice 1 entry criteria

All criteria must be attested against one accepted Gate 0 commit. “Passed” below reflects evidence available in this run, not intent.

| # | Criterion / owner | Status | Remaining evidence |
| --- | --- | --- | --- |
| 1 | ownership ledger — `AM-ARCH` | **FAIL** | bind every owner ID to one accountable `@handle` |
| 2 | source authority + durable retention — `AX-SOURCE` | **FAIL** | protected ref, signed tag, or verified bundle |
| 3 | migration-authoritative lock — `AM-RELEASE-QA` + `AX-SOURCE` | **FAIL** | criterion 2, then set authority through the owning process |
| 4 | offline source quality — `AX-SOURCE` + `AM-RELEASE-QA` | **FAIL** | authorized command, runtime versions, exit codes, concise result |
| 5 | visual identity — `AX-SOURCE` + `AM-WEB` | **FAIL** | sanitized idle, clarify, candidates, plan, approval, DAG/executing, paused, text-report images and manifest |
| 6 | accepted architecture/contracts — `AM-ARCH` + `AM-CONTRACTS-HISTORY` | **FAIL** | plan and ADR remain Proposed pending signatures |
| 7 | target characterization — `AM-RELEASE-QA` | **FAIL** | copied contract fixtures exist; required focused offline executions/attestation are not present |
| 8 | zero production behavior diff — `AM-ARCH` + `AM-RELEASE-QA` | **PASS** | verifier restricts changed paths to Gate artifacts |
| 9 | v2 compatibility work plan — history/runtime/web/security owners | **FAIL** | bound owners, frozen DB fixture, accepted work-package evidence |
| 10 | handoff and authorization — `AM-ARCH` + `AM-RELEASE-QA` | **FAIL** | accepted Gate commit, clean branch point, signatures, all prior criteria |

Current result: **1/10 passed; Slice 1 unauthorized; HOLD**. Passing Gate 0 would authorize work only in an isolated Slice 1 branch. It would not make `research-v3` production-reachable, authorize Provider calls, or perform cutover.

## 9. Handoff and residual risks

- Target base remains `dec6b55b3e97913c052ee2b665c063aec77a9dd3`; accepted Gate 0 commit is not known until a coherent verifier-passing commit exists.
- Next branch, if Gate 0 is later authorized, must start from that accepted commit rather than mutable `main` or an ai-x checkout.
- Source object durability is not demonstrated outside the local repository.
- Source freeze metadata wording is stronger than the actual predecessor-manifest relationship; the lock records the discrepancy.
- Browser baseline capture produced no finalized output; visual parity is unverified.
- Pervasive source `research-task-v2` naming can leak across the adapter unless exact v3 discriminator tests are added in Slice 1.
- Contract fixtures characterize behavior but do not replace focused offline target executions.
- Existing research-v2 remains an engineering candidate, not a completed human release baseline.
