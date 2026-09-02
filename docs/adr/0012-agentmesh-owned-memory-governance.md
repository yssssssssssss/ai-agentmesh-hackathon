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
- Accepted Team Knowledge is immutable in place. Corrections create a new version with `supersedes_memory_id`; lifecycle transitions and revision activation are delivered as the next bounded Slice 4B increment.
- FTS5 remains the baseline index. Optional retrieval adapters consume only records already eligible under AgentMesh permissions and lifecycle policy.
