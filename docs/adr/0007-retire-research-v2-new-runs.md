# ADR 0007: Retire Research-v2

## Status

Accepted and completed on 2026-08-25. This decision removes the executable research-v2 writer; it does not delete historical data or authorize research-v3 execution. ADR 0008 later retires research-v3 and narrows item 6 by removing the shared writer-control mechanism while preserving v2 history compatibility.

## Context

Research-v2 is not part of the intended product direction. Before removal, every persisted research-v2 Run was moved to a terminal state, already-sent calls without an acknowledgement were preserved as `UNKNOWN`, and the database was backed up. Existing Runs and Artifacts still have audit value and must remain readable without restoring the retired Runtime.

## Decision

1. `POST /api/agent/runs` never selects research-v2. Eligible natural-language requests use the general v1 Skill DAG; explicit `$competitive-analysis` requests remain single-Skill v1 requests.
2. The research-v2 Runtime, actors, compiler writer, execution engine, planner, recovery path, approval path, mutation DTOs, background supervision, smoke runner, and evaluation harness are deleted.
3. Existing research-v2 Runs expose owner-scoped GET projections only. Retry, cancel, clarify, execute, recovery, purge, and Tool approval mutations are rejected or absent.
4. Historical reads use dedicated SQLite read-only connections with `query_only=ON`. Integrity failures are reported without repairing, invalidating, or otherwise mutating stored rows.
5. Client-turn replay may return an existing research-v2 Run, but cannot restart it.
6. Frozen payload models, exact-version decoders, historical SQLite fixtures, schema migrations, and the `research_writer_control` fence remain solely for compatibility and audit.
7. Research-v3 stays preview-only and is not enabled by this decision.
8. Physical deletion of the 18 retained Runs, their Artifacts, or legacy SQLite tables requires separate explicit authorization.

## Consequences

The application process no longer constructs or supervises a research-v2 Runtime, and no supported API or test fixture can reopen its writer. New requests may still produce report-shaped v1 Skill synthesis, but that output is not a research-v2 Report.

The remaining `research-v2` identifiers are persisted-data discriminators and read-side compatibility code. They are intentionally not aliases for a current workflow.

## Verification

- Import and route scans find no executable research-v2 writer module or mutation endpoint.
- The immutable historical fixture projects the same owner-visible Report after restart.
- Foreign-owner reads are hidden.
- Repeated Run and Artifact reads leave `PRAGMA data_version` and source rows unchanged.
- Hash, index, canonical-JSON, lineage, and tombstone failures fail closed without repair writes.
- New competitive requests use v1, while existing client-turn receipts replay their stored research-v2 identity.
- Backend, frontend, generated-schema, and browser regression suites pass.
