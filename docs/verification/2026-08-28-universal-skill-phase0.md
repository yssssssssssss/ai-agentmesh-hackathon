# Universal Skill Pool — Phase 0 Feasibility Record

- Date: 2026-08-28
- Plan: `docs/plans/2026-08-28-universal-skill-pool-dynamic-orchestration.md`
- Development branch: `feature/universal-skill-pool-phase0`
- Preserved WIP snapshot: `snapshot/pre-universal-phase0-20260828` at `6bc146d005e804b4eda1896575aa8c7e353dabd1`
- Status: **local Phase 0 complete; offline Phase 1A authorized for the solo Hackathon; production Preview remains blocked by external release and review gates**

## Baseline

The source worktree contained 290 tracked changes and 55 untracked entries. A local commit-tree snapshot was created without changing that worktree's index or files; runtime SQLite data under `data/` was excluded. The isolated Phase 0 worktree was created from that snapshot.

Baseline command:

```bash
.venv/bin/python -m pytest -q \
  tests/test_deepsearch_planning.py \
  tests/test_deepsearch_recovery.py \
  tests/test_deepsearch_store.py \
  tests/test_skill_orchestration.py
```

Result before Phase 0 changes: `95 passed in 11.89s`.

## Phase 0 gates

| Gate | Current result | Evidence / required follow-up |
| --- | --- | --- |
| FrozenPlan/Snapshot v1 compatibility | Local proof passed | Frozen fixture: `tests/fixtures/deepsearch_plan_snapshot_v1.json`; fixture SHA-256 `44250429e107f86107bd9e29d3705696d9b441f3ae9631c4d7545e8fcafe07e2`; frozen-plan hash `83d80bf6eef56fb30ed5897b702a302f44b93f831c1b4ff85480b83e081a057f`. |
| `planning_contract_version` JSON persistence | Local proof passed | Marker is part of new Run identity but absent legacy markers preserve the existing create-request hash. Tests cover atomic claim/receipt rollback, same-turn collision, mode/contract compatibility, immutability, process reopen, and no-Plan enumeration. A 10,000-row/100-scan probe returned 4,500 active matches with p95 `61.399 ms`, p99 `65.140 ms`. No indexed column is required for the measured offline preflight workload. |
| Shared quiesce/admission design | Local prototype passed | Thread-safe permit drain, one-way latch, concurrent callers sharing one completion, `asyncio.to_thread()` rejection, pre-enumeration and post-enumeration recovery races, and `off` startup/no-op behavior are covered by deterministic barriers. Production mutation and Tool-claim wiring remains Phase 2A-1 scope. |
| Protected release topology | **Blocked after local wheel and lock proofs** | A local wheel built successfully with SHA-256 `8e082814fe8e9d8429b6cd2c00747c69dd95811f4048da70441cd4ae415f1919` and contains the v1 Artifact decoder, recovery code, and Task Catalog v1. An actual WAL database test proves the offline rollback process cannot obtain `BEGIN EXCLUSIVE` while another writer owns the database and can obtain it after that owner exits. GitHub reports `main` is not protected, repository rulesets and deployment environments are empty, squash/rebase merge are enabled, and the sole active workflow is CI without artifact attestation or deployment. A repository administrator and preproduction target are required before reviewed-blob, attestation, immutable-release marker, ingress ACL, force-stop, and complete rollback rehearsal can pass. |
| SQLite concurrency/capacity | **30-minute local production-shaped probe passed** | Runner: macOS 14.5 (23F79), Apple M2 Pro, arm64, Python 3.13.0. The initial probe failed: repeated schema setup in every `_connect()` caused write p95 `540–727 ms`; DELETE journal also showed writer starvation. Schema setup now runs only at store initialization and the store requires WAL with a 5-second busy timeout. The final 1,800-second run used a 32 KiB snapshot payload, three writers, ten readers, and Tool claim/settlement events: 5,373/5,373 events persisted, zero sequence gaps, zero lock errors, write p95 `4.349 ms`, p99 `14.382 ms`, read p95 `2.636 ms`, p99 `6.817 ms`, event-loop lag max `73.943 ms`, WAL peak `4,293,072` bytes, checkpoint `12.734 ms`, and per-Run p99 growth `40,960` bytes. At the explicit probe assumption of 100 Runs/day, the 90-day doubled capacity requirement was `998,309,888` bytes versus `15,813,025,792` bytes free. Raw results: `docs/verification/2026-08-28-universal-skill-phase0-sqlite-soak.json`. A separate preproduction-host rerun remains part of the blocked deployment-topology gate. |
| 84-Skill reviewer roster | **Blocked by confirmed single-person project constraint** | The repository has no `.github/CODEOWNERS` and GitHub exposes only one collaborator, `@yssssssssssss`. The maintainer confirmed this is a solo Hackathon project and asked to continue the other Phase 0 work. No reviewer identities or approvals will be fabricated; this gate remains unfulfilled unless the ADR is explicitly changed to a single-maintainer trust model. |

## FrozenPlan/Snapshot v1 production consumer inventory

The version dispatch seam is `DeepSearchArtifactSchemaRegistry` in `agentmesh/artifacts.py`. The checked-in fixture proves its v1 parse/serialize path remains byte-for-byte canonical. Phase 3 must extend this seam rather than broadening the v1 models.

| Responsibility | Production consumers that must explicitly dispatch v1/v2 |
| --- | --- |
| Frozen contract and schema registry | `agentmesh/artifacts.py`: `DeepSearchFrozenPlanV1`, `DeepSearchPlanSnapshotV1`, `DeepSearchArtifactSchemaRegistry` |
| Plan freeze, canonical hash, and snapshot writer | `agentmesh/deepsearch/planning.py`: `deepsearch_frozen_plan()`, `plan_content_hash()`, `build_deepsearch_plan_snapshot()` |
| Artifact read/write integrity | `agentmesh/artifacts.py`: `V1ArtifactReader`, `V1VerifiedArtifactStore`, content-lineage validation |
| Plan persistence, edit/approve, execution and recovery validation | `agentmesh/store.py`: `_validate_deepsearch_plan_snapshot()`, `_load_deepsearch_plan_snapshot_in_transaction()`, initial save, edit, approval, claim, recovery, and finalization transactions |
| Planning lineage | `agentmesh/deepsearch/service.py` |
| Evidence/report lineage | `agentmesh/deepsearch/reporting.py` |
| Plan edit and approval routes | `agentmesh/routes/agent_runs.py` |
| Runtime evidence consumption | `agentmesh/agent_runtime/service.py` and `agentmesh/tool_runtime/deepsearch.py` |

No v1 field, schema literal, canonical projection, or hash input was changed in Phase 0.

## Reproducible commands

```bash
# Frozen v1 and planning-contract proof
.venv/bin/python -m pytest -q \
  tests/test_deepsearch_v1_compatibility.py \
  tests/test_deepsearch_store.py

# Quiesce/recovery proof
.venv/bin/python -m pytest -q \
  tests/test_orchestration_quiesce.py \
  tests/test_deepsearch_recovery.py \
  tests/test_health.py

# JSON marker scan
PYTHONPATH=. .venv/bin/python scripts/probe_planning_contract_storage.py \
  --records 10000 --iterations 100

# Local 30-minute production-shaped soak
PYTHONPATH=. .venv/bin/python scripts/run_universal_phase0_sqlite_soak.py \
  --duration-seconds 1800 --writers 3 --readers 10 \
  --writer-interval-ms 1000 --reader-interval-ms 250 \
  --expected-runs-per-day 100
```

## External topology observations

Read-only GitHub inspection used:

```bash
gh api repos/yssssssssssss/ai-agentmesh-hackathon/branches/main/protection
gh api repos/yssssssssssss/ai-agentmesh-hackathon/rulesets
gh api repos/yssssssssssss/ai-agentmesh-hackathon/collaborators
gh api repos/yssssssssssss/ai-agentmesh-hackathon/environments
gh repo view yssssssssssss/ai-agentmesh-hackathon \
  --json defaultBranchRef,mergeCommitAllowed,squashMergeAllowed,rebaseMergeAllowed
```

Observed state: branch protection returned `404 Branch not protected`; rulesets and deployment environments were empty; squash and rebase merges were enabled; only `@yssssssssssss` had repository access. These are observations only—Phase 0 made no GitHub settings mutation.

## Post-spike engineering estimate

The v1 consumer inventory and quiesce/storage probe increase the expected integration surface relative to the original estimate:

| Phase | Revised engineering estimate | Reason |
| --- | ---: | --- |
| Phase 2A | 8–12 days | Shared admission must cover async routes, `to_thread()` sync paths, recovery, node claims, Tool claims, health, and offline rollback; `store.py` remains a high-contention integration point. |
| Phase 2B | 5–8 days | Write-outcome uncertainty, partial-delivery convergence, and Resource Manifest checks require coordinated executor/store/finalization tests. |
| Phase 3 | 8–12 days | FrozenPlan v1 has production consumers across artifacts, store, routes, runtime, planning, reporting, and Tool evidence; every consumer needs explicit v1/v2 dispatch fixtures. |

These ranges exclude the blocked human-review work and preproduction infrastructure changes. They should be revisited after Phase 1B establishes the actual Profile and retrieval workload.

## Current validation

```text
Skill sync: 84 total, 10 preserved, 74 generated
Catalog report: 84 loaded, 10 Planner Profiles, 0 errors, 0 warnings
Current 10-Skill retrieval gate: PASS; Top-3 100%, p95 30.676 ms, all leakage recalls 0%
Backend: 1541 passed, 6 skipped
Ruff: all checks passed
Frontend unit: 27 files, 161 tests passed
Frontend build: passed; largest bundle 315,952 bytes <= 500,000-byte limit
OpenAPI TypeScript projection: regenerated successfully
```

## Phase 0 decision

The JSON marker design remains viable for the measured rollback/preflight scan, so Phase 0 does not require a new SQLite column. The shared admission-controller shape, v1 compatibility seam, and local 30-minute SQLite workload are also viable. The maintainer has authorized offline Phase 1A work under the single-maintainer Hackathon boundary. Production recommendation exposure and Phase 2A remain blocked until the external release topology has been rehearsed and the review-policy conflict has been explicitly resolved; no local result in this record substitutes for those external decisions.
