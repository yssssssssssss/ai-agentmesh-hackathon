# ADR 0064: Structured Runner Session round trip

Status: Accepted, implemented 2026-10-07.

## Decision

New CLI Runners advertise `structured-session-v1` in the existing extensible capability list. Direct claims then return `runner-execution-envelope-v2`; older Runners and Standard Skill node claims retain the V1 envelope and its original hash contract. Claim responses discriminate the two envelopes by schema version. Transport and enrollment remain `runner-v1`.

The new envelope contains a private, versioned snapshot of the existing SDK Session. It preserves user/assistant items, tool call IDs, arguments and corresponding results. The enclosing envelope binds its owner, project, Run, thread, lease and execution identities. SHA-256 identifies the frozen content; authenticated transport and active-lease checks authorize it. There is no second durable user-memory store on the Runner.

The control plane acquires the existing Session writer, checks current actor/thread/project and governed Memory origins, reconciles only unsynced canonical messages, and records the snapshot version/hash against the active lease. The current Run input is excluded by its existing canonical message ID, rather than by matching text. Synced bodies are filtered in SQL. The payload limit is 2000 items and 1 MB; exceeding it produces an explicit error instead of slicing messages.

The Runner passes structured items directly to the pinned SDK. Complete-request admission now applies to both V1/V2 direct execution and Standard nodes, including instructions, schemas, typed output schema and later tool results. V2 direct execution also uses the shared request-pressure compactor: retain complete recent user turns and tool units, bound the summary, and verify the resulting full first request. This uses the existing conservative UTF-8 estimate and output allowance. Compaction token usage is included when reported.

Successful V2 execution returns the SDK's complete `to_input_list()` in `runner-completion-v2`. In one SQLite transaction, completion checks the active lease, exact frozen snapshot and current Session version/authority, replaces the Session, and settles Run/dispatch/lease with the existing durable idempotency receipt. Original Memory dependencies remain attached after compression. Current-input and projected-answer message bookkeeping prevents later duplicate imports. Completion audit events contain hashes, versions and counts, not conversation bodies.

V2 completion cannot downgrade to the old request without its Session commit. Returned items reject platform-role injection, broken/duplicate tool pairs, unsupported SDK conversion and credential-like content. Invalid or stale commits roll back the whole transaction. A byte-identical completion replay returns the prior result without rewriting history. The private mode-0600 spool serializes the versioned request and restores it after a process restart; a valid lease can receive the queued completion without rerunning the model. Expired/revoked leases retain existing discard/fencing behavior.

## Evidence and scope

Public HTTP/SDK/service checks cover more than 20 historical items, tool identities, exact SDK delivery, completion replay, next-conversation continuity, stale-version rejection, role injection, downgrade rejection, request-pressure compaction, oversized-request refusal and spool reopen. Selected existing V1 dispatch/executor/service/spool/CLI and local compaction cases verify compatibility. Sixteen distinct focused checks passed; only affected checks were run. Targeted Ruff, whitespace checks and OpenAPI type generation passed. Logs: `/tmp/agentmesh-runner-session-{green,boundaries,spool,compatibility,canonical-history,api-types}.log`.

This completes direct Runner structured Session transport, budgeted compaction and transactional completion. It does not implement remote automatic Memory injection/delivery receipts, a live control-plane gate before every remote model request, cumulative remote Run cost accounting, remote SDK approvals, or resume of an unfinished model run after process death. Full indirect source lineage, freshness/remote ACL/deletion, real model quality and team acceptance remain in the complete optimization plan.
