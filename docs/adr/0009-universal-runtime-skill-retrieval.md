# ADR 0009: Universal Runtime Skill Retrieval and Versioned Plan Contracts

## Status

Accepted. Phase 1A and later rollout remain gated by the Phase 0 evidence recorded in `docs/verification/2026-08-28-universal-skill-phase0.md`.

## Decision

Natural-language orchestration will search every visible, attested, approved built-in Runtime Skill instead of treating Task/Scenario mappings or the ten Pilot Skills as a candidate whitelist. Deterministic server policy will classify readiness, freeze at most twelve ready capability cards in an immutable Candidate Snapshot, and validate an LLM-proposed DAG of at most six unique Skill nodes; full Skill instructions remain execution-time inputs only.

Task/Scenario remains authoritative for intent, canonical output requirements, evidence requirements, completion criteria, and ranking hints, but not for excluding otherwise legal Runtime Skills. The server—not the model or client—owns coverage atoms, capability gaps, Scenario assignment, Tool/resource requirements, side effects, permissions, and completion.

Every new plan-producing Run freezes an immutable `planning_contract_version`. Existing Standard Plans and `DeepSearchFrozenPlanV1`/`DeepSearchPlanSnapshotV1` remain on their original contracts and hashes; Universal Standard uses Candidate Snapshot v1 plus Task Catalog v2, while Universal DeepSearch later introduces FrozenPlan/Snapshot v2. No persisted v1 object is upgraded in place. A Universal Standard planning skeleton and its Candidate Snapshot are persisted atomically before Planner invocation, the same snapshot is reused for the single repair attempt, and only a compare-and-set transition may publish the completed Preview. Public Plan projections expose candidate readiness and blocked reasons but omit Profile hashes, Tool implementations, Resource/Adapter identities, and evidence-path witnesses.

Universal Standard execution is a separate code capability from Preview. Phase 2A persists a null marker and those Plans remain permanently non-executable. Phase 2B may freeze `standard_universal_execution_v1` only on newly created Runs/Plans, and every approval, Plan claim, node claim, service entry, and executor checks exact Run/Plan/current-binary marker equality. Native, MCP, and Skill-resource Tool dispatches append a durable claim inside the shared short quiesce permit before provider I/O and one terminal outcome afterward; the permit deliberately does not span external I/O, while pre-quiesce claims may only settle or be reconciled conservatively.

Rollback after new-contract records exist is stop-and-roll-forward: close runtime admission, quiesce recovery and new node/Tool claims, force-stop the sole SQLite-owning process, terminalize affected work offline, and restart the same forward-compatible binary with orchestration `off`. Deploying an older binary is not supported.

## Relationship to ADR 0004

This ADR supersedes ADR 0004 only where it limits automatic planning to ten Wiki domain Skills and where it treats Scenario-unbound or runtime-unready Skills as one pre-ranking exclusion class. ADR 0004's persisted bounded DAG, twelve-candidate/six-node limits, depth four, concurrency three, two approval gates, execution-time revalidation, failure propagation, audit, and `off|preview|execute` rollout remain in force.

## Consequences

All 84 currently installed built-in Skills require version-controlled capability Profiles and independent review before production Planner cutover. For this single-maintainer Hackathon, draft Profile authoring and offline Phase 1A/1B evaluation may continue without independent approval, but those Profiles gain no production trust and cannot expand public recommendations or Agent Run candidates. Relevant but non-ready Skills may produce safe diagnostics but never selectable nodes. Workspace, Project Package, Learned, and tool-limited Skills gain no implicit trust or permission. Task Catalog v1 and DeepSearch v1 artifacts remain packaged and readable for legacy Runs.
