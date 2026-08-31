# ADR 0009: Universal Runtime Skill Retrieval and Versioned Plan Contracts

## Status

Accepted and implemented on `main`. Repository integration does not authorize production activation: orchestration remains `off` until the independent Profile, real Provider, holdout, attestation, deployment, and rollback gates tracked in Issues #6–#9 are complete.

## Decision

Natural-language orchestration will search every visible, attested, approved built-in Runtime Skill instead of treating Task/Scenario mappings or the ten Pilot Skills as a candidate whitelist. Deterministic server policy will classify readiness, freeze at most twelve ready capability cards in an immutable Candidate Snapshot, and validate an LLM-proposed DAG of at most six unique Skill nodes; full Skill instructions remain execution-time inputs only.

Task/Scenario remains authoritative for intent, canonical output requirements, evidence requirements, completion criteria, and ranking hints, but not for excluding otherwise legal Runtime Skills. The server—not the model or client—owns coverage atoms, capability gaps, Scenario assignment, Tool/resource requirements, side effects, permissions, and completion.

Every new plan-producing Run freezes an immutable `planning_contract_version`. Existing Standard Plans and `DeepSearchFrozenPlanV1`/`DeepSearchPlanSnapshotV1` remain on their original contracts and hashes; Universal Standard uses Candidate Snapshot v1 plus Task Catalog v2, and Universal DeepSearch uses FrozenPlan/Snapshot v2 with the same snapshot and exact routed Catalog identity (or canonical `null` when unrouted). No persisted v1 object is upgraded in place. A Universal Standard or DeepSearch v2 planning skeleton and its Candidate Snapshot are persisted atomically before Planner invocation, the same snapshot is reused for repair/recovery, and only a compare-and-set transition may publish the completed Preview. Public Plan projections expose candidate readiness and blocked reasons but omit Profile hashes, Tool implementations, Resource/Adapter identities, and evidence-path witnesses.

Universal Standard execution is a separate code capability from Preview. Phase 2A persists a null marker and those Plans remain permanently non-executable. Phase 2B may freeze `standard_universal_execution_v1` only on newly created Runs/Plans, and every approval, Plan claim, node claim, service entry, and executor checks exact Run/Plan/current-binary marker equality. Native, MCP, and Skill-resource Tool dispatches append a durable claim inside the shared short quiesce permit before provider I/O and one terminal outcome afterward; the permit deliberately does not span external I/O, while pre-quiesce claims may only settle or be reconciled conservatively.

Background work is represented by durable dispatch receipts rather than process-local tasks. Terminal Run state and its public output projection are committed as one recoverable boundary, while process, user, node, LLM, Tool, SSE, and recovery concurrency remain bounded. The implemented contract and verification evidence are recorded in `docs/verification/2026-08-29-universal-runtime-platform.md`.

External Provider, Tool, MCP, O2, Data, and file content is untrusted data, not authority. It cannot add candidate nodes, grants, resources, side effects, or approvals; selected operations are revalidated against server-owned identity and policy immediately before dispatch. An adapter that cannot enforce its input/output and transport bounds remains non-ready for production.

Rollback after new-contract records exist is stop-and-roll-forward: close runtime admission, quiesce recovery and new node/Tool claims, force-stop the sole SQLite-owning process, terminalize affected work offline, and restart the same forward-compatible binary with orchestration `off`. Deploying an older binary is not supported.

## Relationship to ADR 0004

This ADR supersedes ADR 0004 only where it limits automatic planning to ten Wiki domain Skills and where it treats Scenario-unbound or runtime-unready Skills as one pre-ranking exclusion class. ADR 0004's persisted bounded DAG, twelve-candidate/six-node limits, depth four, concurrency three, two approval gates, execution-time revalidation, failure propagation, audit, and `off|preview|execute` rollout remain in force.

## Consequences

All 84 currently installed built-in Skills require version-controlled capability Profiles and independent review before production Planner cutover. For this single-maintainer Hackathon, draft Profile authoring and offline Phase 1A/1B evaluation may continue without independent approval, but those Profiles gain no production trust and cannot expand public recommendations or Agent Run candidates. Relevant but non-ready Skills may produce safe diagnostics but never selectable nodes. Workspace, Project Package, Learned, and tool-limited Skills gain no implicit trust or permission. Task Catalog v1 and DeepSearch v1 artifacts remain packaged and readable for legacy Runs.
