# Approval recovery freezes the local Session

Status: accepted for local direct SDK approvals, 2026-10-05.

## Decision

Persist an SDKSessionCheckpointV1 in the server-owned paused SDK state, including
Session identity, owner/Workspace/Project, writer Run/generation, observed version
and a canonical content hash. The hash covers the private history and Memory
dependencies; the checkpoint carries no body. Memory off mode also captures it.
This is subordinate Run recovery metadata, not another workflow or Session store.

Direct recovery verifies the checkpoint and current Session authority/source
eligibility before rebuilding external MCP connections or resolving approvals.
The existing approval claim transaction compares the persisted checkpoint and
checks the current Session again before changing WAITING_APPROVAL to RUNNING.
A Session mutation between precheck and claim therefore cannot admit tools or
consume the approval. Changed ownership, writer generation, versions or bodies
fail with static codes. A same-version body mutation is detected by its hash.

SDK history version represents history/writer changes. Projected ChatMessage
deduplication markers change neither that version nor the checkpoint content;
displaying a pending approval cannot invalidate its own recovery. Canonical
reconciliation still changes the version when it imports actual history items.

Unchanged checkpoints resume after database reopen and partial approvals create
the next checkpoint through the existing pause path. Legacy direct paused states
without a verified checkpoint remain unresumable until an explicit safe migration
exists. Browser decisions retain the current opaque call-ID contract and cannot
replace the Session or serialized SDK state.

## Remaining work

Standard/DeepSearch nodes retain their existing node/plan recovery contracts and
do not acquire a direct-chat Session through this change. Remote Runner Session
parity, full lease fencing, automatic SDK restart append command deduplication,
general external evidence archives, off-mode frozen Skill identity and complete
planning/synthesis/compaction cost contracts remain incomplete. This checkpoint
does not assert immutable sealing of every field in serialized SDK state or real
Provider readiness.

Verification: docs/verification/2026-10-05-session-checkpoint-regression.json.
