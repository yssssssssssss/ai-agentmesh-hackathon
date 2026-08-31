# Universal pre-merge WIP reconciliation

- Date: 2026-08-31
- Source branch: `codex/main-wip-20260826`
- Source HEAD: `7a28d41de8cfe35221f5d8467fab1b84fbebdd7d`
- Frozen snapshot: `snapshot/pre-universal-phase0-20260828` at `6bc146d005e804b4eda1896575aa8c7e353dabd1`
- Reconciliation base: `main` at `b24c1c290de4f20bdcdbb93b556c1efb6ca065ff`
- Decision: do not merge or recommit the legacy WIP tree; retain only reviewed documentation evidence and the private database backup outside the repository

## Inventory result

The root checkout reported 366 modified, deleted, or untracked paths relative to its old HEAD. Those paths were not 366 independent unfinished features:

- The working tree differed from the frozen `6bc146d` snapshot in only two paths: this plan revision and one local SQLite backup.
- It differed from the merged DeepSearch v1 baseline `48d51c9` in only four paths: the plan revision, the SQLite backup, and older copies of `useDialogFocus.ts` and `read-model-admin-mvp.spec.ts`.
- Against the reconciliation base it appeared as 237 effective changes: 145 deletions, 91 modifications, and one addition. That shape is an old pre-Universal tree, not a forward patch; applying it would remove or downgrade the shipped Catalog v2, Profiles, Candidate Snapshot, durable dispatch, capacity, recovery, runbook, tests, and review remediations.
- The two differing frontend files are intentionally discarded. `main` contains the reviewed focus-handler fix and the stronger browser regression steps.

The implementation content is already represented by the Research v2 retirement, DeepSearch v1 baseline, and Universal PR chain. No source-code file from the legacy root WIP is forwarded by this reconciliation.

## Planning material retained

The uncommitted plan revision added a point-in-time capability audit and stricter wording around:

- server-owned identity, authorization, readiness, and side-effect decisions;
- durable Run dispatch and terminal output projection;
- bounded process/user/Run/LLM/Tool/SSE/recovery capacity;
- single-writer SQLite operation and stop-and-roll-forward rollback;
- external content as untrusted data rather than instructions or authority;
- independent Profile review, frozen holdout, real Provider acceptance, deployment attestation, and rollback rehearsal.

The point-in-time branch name, test counts, phase estimates, and statements that only Phase 0/1A were approved are historical evidence, not current product state, so the full 248 KB draft is not copied over the canonical plan. Stable decisions remain in ADR 0009, the phase/runtime verification records, and the Universal release runbook. External gates remain tracked by Issues #6–#9. Project-wide authentication, multi-workspace authorization, Market state aggregation, full Task Center mutations, and complete memory-management workflows remain separate product work and are not claimed by the Universal delivery.

The canonical plan header now records that engineering and repository integration are complete while production orchestration remains `off`.

## Private backup disposition

The WIP contained `data/backups/agentmesh-pre-research-v2-retirement-20260825.sqlite3`, a 35 MB local SQLite snapshot with 31 application tables. It passed `PRAGMA integrity_check` and is intentionally not committed. The operator archive stores the database, the exact WIP plan, source metadata, and the full pre-cleanup worktree inventory with private file permissions.

Recorded SHA-256 identities:

```text
71901d3feba8b4220cef80a3b6044c2926a6a948ea0df6f3fe356e6f1b8330d1  universal-skill-pool-dynamic-orchestration.wip.md
6dee573a3e07827f19b6beb78ba32b34c2327b9e9ad6bd86974303db849cb255  agentmesh-pre-research-v2-retirement-20260825.sqlite3
```

The repository ignores nested SQLite files under `data/`; the external archive is recovery evidence, not a release artifact or production backup attestation.

## Cleanup boundary

After this reconciliation is committed and the external archive checksums are revalidated, the old root checkout may be restored to `origin/main`. The snapshot ref remains until the production-shaped rollback rehearsal in Issue #9 is complete. No cleanup operation may remove the external archive or treat it as evidence that the production backup/restore gate passed.
