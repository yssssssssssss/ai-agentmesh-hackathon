# ADR 0062: Explicit background source sync and bounded retries

Status: Accepted, implemented 2026-10-07.

## Context

ADRs 0057–0061 provide read-only connectors, incremental watermarks, current binding checks and durable page claims. Users still have to continue each page manually. Configuration and expired-claim reconciliation happen at startup or status reads. Automatic synchronization must preserve explicit authorization, existing SQLite transactions and owned mirrors.

## Decision

Use one application-lifecycle coordinator over the existing cursor; add no queue, broker or independent database. `AGENTMESH_CONNECTOR_WORKER_ENABLED=false` is the default. Each existing cursor also defaults to `auto_sync_enabled=false`; enabling the server does not start reading previously synchronized sources. The owner explicitly enables or pauses a cursor through its versioned control command.

The interval is 300–86400 seconds, default 900. Enabling schedules an initial read, preserving the pending page boundary. Successful intermediate pages schedule the next page after five seconds. Completion schedules the next cycle after the configured interval. The cursor and schedule are committed with the existing source/document transaction, so subsequent workers use persisted state.

Every five seconds the coordinator reconciles up to 20 stored cursor rows, scans at most 20 due candidates and reads at most one page. Round-robin ID positions prevent unavailable owners at the front of the candidate list from monopolizing the worker. Current active user, project membership, operator binding, exact claim and lease are checked through the existing service before observation commits. Quiescing, disabling the worker and stopping prevent further commits; shutdown cancels the exact active page through its versioned control. Already issued HTTP requests remain bounded by the existing timeout and may finish, but cannot publish after the claim is cancelled. Idle enabled schedules survive shutdown; the interrupted active cursor is paused and can be explicitly re-enabled. Crash-expired claims are reconciled with bounded retry scheduling.

Transient transport/5xx failures allow at most three automatic attempts per page, with five- and thirty-second delays. Successful pages reset the consecutive count. Access, input and response-contract errors pause automatic synchronization. Exhaustion and unexpected interruptions also pause it. Last successful observations remain unless the existing access/configuration invalidation rules withhold them. Explicit manual retries do not inherit automatic backoff, but obey provider waiting instructions.

`Retry-After` supports seconds and HTTP dates. A primary GitHub limit waits for `X-RateLimit-Reset`; a recognized limit without a usable waiting header waits at least one minute. Unclassified 403 remains a conservative access failure. These rules follow [GitHub's rate-limit documentation](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api#exceeding-the-rate-limit).

Provider waits persist as `next_allowed_at`. Both manual and background admission check waits from operator-bound cursors with the same provider/configuration hash, so another owner of the same configured source cannot bypass the wait. Pause/reset/re-enable retain a cursor's provider wait. Unsupported waits longer than one day pause automatic retries; unrepresentable dates conservatively use the maximum datetime. Response bodies and credentials are not stored in error metadata.

Knowledge displays the actual coordinator availability, explicit automatic controls, next read and provider wait. Status polling updates the owned document list after successful background reads. Source learning/team sharing still require their existing explicit confirmation; external Issues do not change project Task facts.

## Verification

Directly affected backend checks: **57 passed / 9.33 seconds**, Python 3.13. Frontend source controls: **6 passed**. API type generation, production build/bundle budget and targeted Ruff passed. Tests use temporary SQLite/files, injected clocks and mocked external reads. The retry check covers persisted waiting after coordinator replacement, manual and second-owner refusal, three-attempt pause and retained successful evidence. The stop check fences a delayed reader; lifecycle/status availability and continuation/cycle timing are covered.

See `docs/verification/2026-10-07-connector-background-sync.json`. Full regressions, dual-version checks, browser E2E, real Provider/model calls and deployment were not repeated for this slice.

## Remaining scope

This remains a single-application-process worker on SQLite. Deployment topology must follow that existing limit. Direct cancellation of issued HTTP requests, complete remote ACL/deletion discovery, provider-specific freshness, full indirect Session/Runner/Artifact lineage, unified context, process reuse and actual model/team acceptance remain in the complete optimization plan. This slice does not finish stages 3–5 or trigger stage 6.
