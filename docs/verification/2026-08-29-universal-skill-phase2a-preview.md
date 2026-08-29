# Universal Skill Pool — Phase 2A Preview/Safety Implementation

- Date: 2026-08-29
- Branch: `feature/universal-skill-pool-phase2a`
- Base: `8b5561d` (`Author complete draft skill profiles`)
- Status: local implementation and fault tests in progress; production activation remains blocked

## Implemented locally

- Added immutable `CandidateSnapshotV1`, candidate identity, coverage atom, evidence-path witness, and safe public projection contracts. Full canonical snapshots are capped at 32 KiB; public nodes omit Skill content hashes and Resource manifests, and Tool events omit implementation/operation identities.
- Added a Standard Universal preview path that freezes `planning_contract_version=standard_universal_v1`, creates the `PLANNING` skeleton before Planner invocation, reuses one snapshot for repair, and commits the completed preview by compare-and-set.
- Preserved `standard_legacy_v1` and `deepsearch_frozen_v1` selection for non-Universal and current DeepSearch paths.
- Added a minimal Universal Planner response schema. Model output cannot supply Skill/Profile hashes, Tool identities, resources, side effects, Task/Scenario identity, or capability gaps.
- Added deterministic Scenario assignment and canonical coverage validation against Task Catalog v2.
- Added `SkillPlanPublicView`; public Plan responses exclude Profile hashes, Tool implementation identity, Resource/Adapter identity, and evidence-path witnesses.
- Added a code-level Phase 2A execution capability fixed to unavailable. Universal execution is rejected during creation, approval, and executor entry.
- Added append-only Runtime Tool claim/outcome records for native and MCP Tool dispatch. Duplicate call IDs fail closed and non-read outcomes remain conservative.
- Added shared process admission wiring across Run creation/resume, Plan mutations, node claims, Tool claims, and DeepSearch requirement transitions. Runtime Tool permits end after durable claim/reservation and do not span external I/O.
- Added bounded SSE replay pages with idle backoff and process/user/Run connection caps, plus pre-parse 64 KiB orchestration and 16 KiB DeepSearch clarification body limits.
- Added a process-lifetime SQLite writer lock acquired before schema/backfill writes; the offline rollback command uses the same lock protocol.
- Added admin-only, loopback-only `POST /api/admin/skill-orchestration/quiesce`; forwarded headers are not trusted.
- Added offline rollback inventory/checksum, backup, approval, apply, and post-check command at `scripts/quiesce_skill_orchestration.py`.
- Added startup reconciliation for unresolved Tool calls and retry rejection for any source Run with non-read/unknown Tool history.

## Safety state

`standard_universal_execution_contract` remains unavailable. The default runtime Profile verifier also remains unavailable because this repository has no verified production marker or schema-v2 reviewed Profile provenance. Consequently the production/default path continues to use legacy candidates and cannot execute a Universal node.

## External gates still required

- independent CODEOWNER review and high-risk double review;
- protected branch, merge queue, reviewed-blob verification, wheel attestation, and immutable release marker;
- real pre-production ingress/process-manager quiesce drill and exclusive SQLite rollback rehearsal;
- independent release holdout and 500-request Preview observation window;
- real Planner and optional Embedding Provider acceptance runs.

These constraints are deliberately not bypassed by local fixtures.

## Local verification

- Backend: `1659 passed, 6 skipped`.
- Frontend: `161 passed`; production build and 500 KiB bundle gate passed.
- Ruff and `git diff --check`: passed.
- Offline quiesce dry-run against a fresh initialized SQLite database returned an empty, anomaly-free inventory with a checksum.
- Real provider, pre-production ingress/process-manager, protected-branch, attestation, and independent-review evidence are not claimed by this record.
