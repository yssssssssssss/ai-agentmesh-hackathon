---
status: accepted
---

# Record Memory use at the model-context seam

AgentMesh distinguishes a search result from Memory that is actually supplied to an Agent Run. `MemoryContextService` is the only module that may assemble automatic or explicit Runtime Memory context. It applies authorization, lifecycle, Scope, MemoryLayer, binding, safety screening, ranking, deduplication, and a rendered-payload budget before forming model context. For a persisted Run it first reserves a stable citation without claiming use, completes all fallible local preparation, and only then atomically writes immutable `MemoryUseReceiptV1` records at the final model-context handoff.

## Consequences

- `AGENTMESH_MEMORY_CONTEXT=off|observe|inject` controls automatic Task-linked context and defaults to `off`. Observe mode measures eligible retrieval without injection or use receipts. Explicit governed `memory_search` tool calls continue to record the Memory they return to the model.
- A receipt freezes Run, Task, Memory identity, Memory record version, canonical content hash, retrieval layer, retrieval reason, query hash, citation label, Agent identity, and the original Source IDs actually exposed. It never stores the raw query, Memory title, summary, or model prompt.
- Receipt creation revalidates the active user, Run ownership, Workspace/Project membership, immutable `AgentRun.task_id`, the current `AgentMemoryBinding`, Memory visibility, lifecycle eligibility, version, hash, and source identities in one SQLite transaction.
- Citation labels are reserved per Run under `BEGIN IMMEDIATE`; a label can map to only one Memory record/version identity even when distinct searches execute concurrently. A reservation is not evidence of use and is never projected as a receipt.
- Memory titles, summaries, and exposed Source metadata pass the same credential and prompt-injection quarantine used for tool output before a bundle can be rendered or receive a citation reservation. Quarantined items cannot receive use receipts.
- Explicit Runtime `memory_search` defers receipt creation until encoding, output-size checks, safety checks, audit persistence, and tool-call settlement have succeeded. Withheld or transformed output does not create a receipt.
- The same Run, query, reason, Memory version, and citation label replay the existing receipt; a changed identity cannot overwrite historical use.
- Personal, Project, and Team are visibility scopes. Short-, mid-, and long-term are independent retrieval layers selected before ranking and context budgeting. New governed shared Memory stores an explicit layer; legacy shared Memory without one is projected through a deterministic fallback rather than rewriting stored history.
- Explicit `MemoryItem.layer` participates in the versioned `memory-content-v2` hash. Legacy shared records with no layer retain their exact `memory-content-v1` hash; their deterministic fallback layer is frozen separately in each new use receipt.
- `max_total_chars` bounds the complete rendered Memory payload, including policy, citation, identity, hash, Scope, Layer, and exposed Source metadata—not only title and summary text.
- Candidate, disputed, deprecated, expired, archived, or inactive Personal Memory is filtered before FTS/vector candidate limits and can never receive a new Runtime use receipt.
- Run details expose the exact receipt set and whether the final output cited each label. Memory lineage exposes only uses whose Run remains visible to the requesting user.
- External vector or Memory adapters remain replaceable retrieval adapters and cannot create receipts, expand visibility, or become the authority for version, hash, lineage, or audit.
