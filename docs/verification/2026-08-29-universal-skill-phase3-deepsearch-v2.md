# Universal Skill Pool — Phase 3 DeepSearch v2

- Date: 2026-08-29
- Branch: `feature/universal-skill-pool-phase3`
- Base: `44a14dd` (`Add Universal Standard execution contract`)
- Status: local FrozenPlan/Snapshot v2 and recovery vertical slice implemented; production rollout remains gated

## Implemented locally

- Added strict `DeepSearchFrozenPlanV2` and `DeepSearchPlanSnapshotV2` contracts while preserving the v1 models, fixture bytes, hash, builder branch, reader, and Artifact schema.
- FrozenPlan v2 embeds the complete immutable `CandidateSnapshotV1`, preserves the ordered `candidate_skill_ids` projection, and freezes an explicit routed Catalog identity or canonical `null` for unrouted Plans.
- v2 Plan/content/artifact identities include the Candidate Snapshot and routed Catalog identity; v1 identity inputs remain unchanged.
- Added a DeepSearch v2 planning path using deterministic Universal Profile retrieval, Task Catalog v2, the bounded Universal Planner contract, server-owned Scenario assignment, and existing DeepSearch Tool/resource policy.
- Persisted a DeepSearch v2 planning skeleton and Candidate Snapshot before Planner invocation. The Planner gets exactly one semantic repair against that same snapshot; a second invalid proposal fails the skeleton with a stable error. Same-Run crash recovery reuses the snapshot and does not repeat retrieval.
- Extended repository validation, Plan snapshot sealing, approval, public Plan projection, executor revalidation, recovery, and rollback inventory to v2 while retaining explicit v1 dispatch.
- Recovery enumeration is SQL-filtered, cursor-paged at 50 records, schedules no more than two recovery workers per scan, and does not advance past a transient per-record failure.
- DeepSearch v2 report completion additionally checks frozen Candidate Snapshot atoms, node results, Scenario criteria, evidence, capability gaps, and the deterministic mapping of required synthesis outputs to the sealed report.

## Compatibility and safety

- Existing `deepsearch-plan-snapshot-v1` canonical fixtures and deterministic IDs remain unchanged.
- Runs select v2 only when the verified Universal Profile trust path is available; otherwise new DeepSearch Runs remain `deepsearch_frozen_v1`.
- An existing v1 Run is always resumed through the v1 pipeline. A v2 planning skeleton is resumed from its stored Candidate Snapshot; it is never upgraded, downgraded, or re-retrieved in place.
- Global `off` and process quiesce prevent both v1 and v2 recovery scan/scheduling and post-Provider Plan commit.

## Local verification

- Backend: `1669 passed, 6 skipped` (`222.33s`); the slowest gates were the draft-Profile smoke (`36.90s`) and Universal retrieval calibration (`21.83s`).
- Frontend: `161 passed`; production build and 500 KiB bundle gate passed.
- Ruff and `git diff --check`: passed.
- v1 deterministic snapshot tests remain green alongside routed/unrouted v2 hash and recovery tests.

## External gates still required

- independent CODEOWNER/high-risk review and protected release provenance;
- real Planner, Embedding, Web, O2, and Data Provider acceptance;
- frozen holdout and production-shape 30-minute concurrency/recovery soak;
- pre-production force-stop, backup/restore, ingress fence, and rollback drills.
