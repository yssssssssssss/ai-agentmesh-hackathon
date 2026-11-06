# Local SDK Sessions have an owner and fenced writer

Status: accepted for the local Session authority and Memory lineage slice, 2026-10-05.

## Decision

AgentMeshSession requires a detached admitted Run. Every history operation verifies
the persisted Run identity, writer generation, RUNNING status, deadline, active actor,
current Project membership and exact private Thread owner in the same SQLite
transaction as its read or mutation. SDK context wrappers must identify that same
execution. Session bodies remain private to one user, Workspace and Project.

The Session record binds one Run writer. A different Run can claim it only after
the old Run is terminal. A newly admitted higher generation of the same Run may
reclaim it; older instances fail against the persisted generation. Trusted direct
Runtime calls can create a new private Thread when none exists. Existing nonempty
unowned SDK bodies remain unverified and cannot silently acquire an owner.

Bootstrap resolves supplied message IDs against canonical ChatMessage records
inside the transaction, checks Thread and role, and imports current persisted
content in canonical order. Caller-supplied bodies cannot replace that content.
Unknown or foreign IDs abort the whole reconciliation. Existing message-ID
deduplication remains transactional.

One Session instance serializes its own mutations. Independent instances commit
against their observed version; stale append/pop/clear operations fail and stale
compaction replacement returns false. Each append has a command identity and a
durable SDKSessionCommitV1 receipt containing IDs, versions and a content hash.
Replaying that exact command after database reopen does not append again;
conflicting identity or content fails. This does not claim that a newly reconstructed
SDK Run automatically recovers the previous append command identity.

## Compaction and model admission

Compaction checks the owner and frozen Session version at model admission, including
after an LLM capacity wait. It uses the existing request budget, a 2,000 output cap,
one turn, no SDK retry, a maximum 90-second outer timeout bounded by the Run
deadline, and the existing final CAS. A failed admission or timeout preserves the
original history. Direct Runtime bootstrap and compaction failures are handled by
the existing terminal failure transition with static Session error codes.

All local direct Session model requests validate current Session authority and
version before prepared Memory delivery, even in Memory off mode. This check
precedes receipt commit and runs again after capacity waits. It does not claim
continuous revocation of a request already handed to the Provider.

## Memory provenance and forgetting

Session commits archive bounded ID/version/hash dependencies from actual Memory
use receipts and matching exact prepared memory_search outputs. Prepared output
provenance does not create a Memory use receipt. Repeated dependencies retain one
original Run proof rather than growing with every reuse. Reads, compaction and
model admission reuse the existing Memory eligibility, binding and native-origin
checks. Changed versions, scope, owner, archival state, native Document version or
withdrawal prevent future use of an older cached body. Compacted summaries retain
the dependencies of their earlier context.

Owned forgetting and native Document withdrawal clear affected Session item bodies
in the same invalidation transaction, advance their versions and retain only
withdrawn provenance metadata. SQLite triggers reject late restoration, including
after database reopen. Already delivered ChatMessage bodies, artifacts, audit and
backups retain their existing policy; this is a future-context cache barrier.

## Remaining work

Trusted direct approval checkpoints are now implemented in ADR 0027. Automatic restart/replay commit deduplication,
explicit safe migration/reset of unverified legacy bodies and complete remote
Runner Session parity remain incomplete. This first source archive covers Memory
dependencies and their proven native origins; arbitrary external tool evidence,
legacy origins without frozen version/hash, and a general source archive are not
claimed. Complete compaction attempt cost accounting, planning/synthesis admission
and aggregate runtime budgets continue in Phase 4. Phase 3/4 and real Provider
acceptance remain incomplete.

Verification: docs/verification/2026-10-05-owned-session-regression.json.
