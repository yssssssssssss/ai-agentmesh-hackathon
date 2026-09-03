---
status: accepted
---

# Keep Memory governance and lineage inside AgentMesh

AgentMesh owns Memory identity, scope, lifecycle, version, review, provenance, and audit. An accepted Task Review may be explicitly captured as the Run owner's Personal Memory or as a Team Candidate, but it never publishes Team Knowledge automatically. Team Candidates require a separate `MemoryReviewV1`; external embedding, vector, Mem0, Zep, LangMem, or similar systems may index eligible records but cannot own governance state or expand visibility.

## Consequences

- `MemoryProvenanceV1` freezes source Task, Run, Task Review, Artifact IDs/hashes, source Memory IDs, creator, and creation time. Legacy records without it are displayed as `legacy_unverified`; provenance is never invented.
- Personal capture is private to the Run owner. Team Candidate capture creates a separate reviewer-specific Inbox projection and remains excluded from Team Knowledge until its Memory Review is accepted.
- Task Review judges delivery quality; Memory Review judges whether the captured content may become shared team knowledge.
- Governed writes use stable command IDs, optimistic versions, server-derived reviewers/actions, SQLite transactions, redacted AuditEvents, and fail-closed authorization rechecks.
- Accepted Team Knowledge is immutable in place. A correction creates a new Team Candidate with `supersedes_memory_id` plus frozen source Memory ID, version, and content hash. The predecessor remains unchanged while the revision is pending or rejected; accepting the revision atomically activates the new version and deprecates the predecessor.
- Only the Memory owner or a user with effective `manage_team_memory` permission may propose a revision. Direct lifecycle transitions require `manage_team_memory`; independent candidate acceptance continues to require the assigned reviewer and effective `accept_team_memory` permission.
- Lifecycle transitions are explicit and versioned: accepted may become disputed, deprecated, expired, or archived; disputed may become deprecated, expired, or archived; proposed may expire; deprecated and expired may archive; archived restores only to its recorded pre-archive status. Proposed candidates cannot bypass Memory Review through a lifecycle transition.
- Expiring a proposed candidate atomically cancels its pending Memory Review and resolves the reviewer Inbox projection without recording a reviewer rejection.
- Disputed, deprecated, expired, and archived versions remain readable to authorized users but are excluded before automatic retrieval ranking and budgets.
- FTS5 remains the baseline index. Optional retrieval adapters consume only records already eligible under AgentMesh permissions and lifecycle policy.
