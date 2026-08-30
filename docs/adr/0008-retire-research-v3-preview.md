# ADR 0008: Retire Research-v3 Preview

## Status

Accepted and completed on 2026-08-26. Research-v3 never received production-cutover approval and is not a supported AgentMesh workflow.

## Context

Research-v3 was built as an isolated, provider-free preview and production-shaped rehearsal for the ai-x parity proposal. It was never enabled for production traffic, never became the active report workflow, and never executed a real production Provider path.

The retirement audit found zero `orchestration_version='research-v3'` rows in the local application database, zero rows in its v3 repository root table, and zero research-v3 Runs in the retained pre-v2-retirement local backup. There is therefore no local v3 user history that requires a read adapter or migration.

DeepSearch replaces the proposed product direction as an explicit `planning_mode` on the existing v1 Skill DAG. It has its own Requirement and ProblemGraph contracts and does not depend on either retired Research generation.

## Decision

1. Remove every active research-v3 creation, routing, preview, mutation, projection, recovery, health/configuration and frontend entry point.
2. Remove the research-v3 Runtime package, its dedicated schemas, frozen catalog/source assets, generated Workbench assets and enablement/rehearsal runbook.
3. Remove verification receipts whose sole purpose was to operate the dormant Gate 2 preview or production-shaped rehearsal.
4. Keep ADR 0006 and the original ai-x/Slice planning records as historical evidence. Their proposed future v3 activation and writer-generation model are superseded by this ADR.
5. Keep research-v2 historical reads exactly as defined by ADR 0007. V3 retirement does not authorize deletion or mutation of v2 history. This decision amends ADR 0007 item 6 only for the shared generation control: exact v2 decoders and fixtures remain, but new databases no longer create `research_writer_control`, old control rows are never consulted, and legacy writer triggers are replaced by a permanent retired-version admission fence.
6. Do not drop existing research-v3 or writer-control SQLite tables in the first retirement stage. They remain inert compatibility residue so retirement is additive and rollback-safe. Physical schema removal requires a separate migration decision after deployed databases have been inventoried.
7. Do not retain a dormant feature flag, allowlist, catalog loader or control-row transition that could reactivate v3. A future research product must be designed as a new decision, not by reopening this preview.

## Consequences

- New executable work uses v1 only; DeepSearch is identified by `planning_mode`, not by a Research generation.
- Requests cannot select, preview, retry, resume or execute research-v3.
- Removing v3 application code does not perform destructive database migration and does not rewrite existing AgentRun payloads.
- Residual tables may remain visible in old SQLite files but have no writer, route, scheduler or UI consumer.
- Historical documents can explain why v3 existed, but they are not operational instructions and cannot authorize restoration.

## Verification

- Import and route scans contain no active research-v3 Runtime, router, preview allowlist or Workbench branch.
- Package-data configuration contains no research-v3 catalog or schema assets.
- The local database and retained local backup contain no research-v3 Run data.
- Research-v2 owner-scoped history tests remain green and all v2 mutation fences remain closed.
- The DeepSearch implementation plan fixes `orchestration_version="v1"`; its future acceptance tests must prove that invariant and contain no imports from research-v2 or research-v3.
