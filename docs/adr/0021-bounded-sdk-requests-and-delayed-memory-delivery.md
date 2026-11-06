# Bounded SDK requests and delayed Memory delivery

Status: accepted for the third Stage 3 slice, 2026-10-04.

## Decision

Extend the existing MemoryContextService with request admission rather than
introducing a second context authority. A Model wrapper measures the request
after the SDK has assembled instructions, complete Session items, tool results,
function/handoff schemas, output schema and settings. Every local streamed
Runtime model turn, including restored approvals, passes this boundary.

The default text request caps are 200,000 rendered characters, 64,000 estimated
input-plus-output tokens and 8,192 output tokens. The configured enterprise
aliases do not provide a verified tokenizer; measurements explicitly report
`utf8_conservative`, count UTF-8 bytes and include 1,024 framing reserve. They
are estimates, not Provider usage. Unsupported hidden Provider state and media
whose token costs cannot be established are refused rather than counted as text.
Existing model retry advice and cleanup continue through the wrapper.

The guard attaches to the original Agent object while the SDK executes and
restores its model afterward. Cloning only the initial Agent would leave the
Agent already resolved inside a restored RunState outside the guard.

## Local handoff and source checks

Automatic Memory preparation reserves labels but does not write use receipts.
The final local model handoff follows full-request budget admission and rechecks
the frozen Memory before recording use. It does not assert that the Provider
has returned a successful response. Owner core preferences apply in inject mode
independently of learning opt-in; local direct/Standard execution rechecks their
version before each handoff. They never become project facts or permissions.

SDK memory_search tools persist a private pending delivery snapshot and the
hash of their final visible output. Returning a tool result does not record
Memory use. An admitted subsequent request must include the exact tool-output
hash before its frozen references can be committed. Snapshot records are
subordinate to the Run and Memory authority, carry no credentials and are not
exposed through public Memory search. Their lookup uses a Run expression index
and a 24-record bound. Direct legacy adapters retain their existing explicit
local-handoff contract.

Receipt commit checks current private scope/archive markers, native Document
version/ownership/scope, and frozen personal summary/share lineage. Rollups with
no recorded lineage are withheld; no legacy proof is invented. Parent traversal
is bounded to four ancestors and rejects cycles. Governed Memory revisions are
not treated as summaries requiring an active predecessor: their independent
review and own evidence remain the authority.

Forgetting redacts pending delivery bodies and queries while retaining their
output hashes as withdrawal barriers. Matching old outputs are then refused;
database triggers reject late snapshot reconstruction from tombstoned Memory.
Already delivered Session/output retention is a separate platform policy.

## Session compaction and product projection

Compaction retains complete parallel/interleaved call-result units and keeps
unfinished calls outside the summarized prefix. Replacement still uses the
existing Session version CAS. The compactor has one turn, a 2,000 output-token
cap, bounded complete input and no trace export; unsafe/oversized summaries are
not committed. Successful compaction reports Provider usage separately, with
missing usage marked unknown.

Run detail and Workspace expose the latest eight metadata-only request budget
decisions. The UI distinguishes an admitted budget from an over-budget request
that was never delivered, and distinguishes estimates from actual Provider
usage. Memory-use entries remain exact immutable version receipts.

## Scope and remaining work

This is not the completed ContextAssembler. Structured temporal facts/procedure
injection, explicit query routing, applicability, individual candidate decision
states and budget-driven selection remain outstanding. Oversized complete
requests currently stop safely; they do not silently truncate tool schemas or
call-result units. Known-tokenizer integration requires a verified model mapping.

Remote Runner request admission, planning/non-streamed synthesis calls, frozen
automatic-context snapshots across approvals, Session ownership/dedup/source
archives, failed-compaction cost/deadline accounting and broader SDK hardening
remain later work. Pending tools recover from persisted snapshots, but this
slice does not claim a complete Runtime ContextSnapshot contract. Full-request
limits do not by themselves establish cumulative online cost/quality targets.
The frozen 120/24 evaluations, authorized retrieval capacity and real Provider
quality still require their own evidence.

Verification is recorded in
`docs/verification/2026-10-04-stage3-context-delivery-regression.json`.

The subsequent local frozen-context recovery slice is described in ADR 0022.
The remaining-work list above records this slice's original verification scope.
