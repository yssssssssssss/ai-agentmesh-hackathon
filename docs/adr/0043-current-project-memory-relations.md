# Current-project Memory relations

Date: 2026-10-07
Status: accepted for local governed records

## Context

MemoryRelation already stores several kinds of lineage, but its legacy target ID can mean a Source, Memory, Review or Artifact. Interpreting every old row as a verified graph would invent authority. The plan needs bounded relations among current local knowledge and project work, without a second memory store or graph database.

## Decision

Keep legacy rows and add an optional `memory-relation-v1` snapshot to the existing model. A new annotation freezes the record kind, ID, version and canonical content hash of its Memory source, target and attached Task/document evidence. Five types are allowed: `relates_to`, `supports`, `contradicts`, `supersedes`, `caused_by`. Default assertion is candidate; a caller can explicitly save a separate human-confirmed annotation. Confirmation does not accept a Memory Review, change a Task, supersede a Memory lifecycle or grant access. Earlier annotations remain independent records.

`POST /api/memory/relations` reloads the actor/project and all three references inside `BEGIN IMMEDIATE`. Private Memory requires ownership; annotating another member's visible shared Memory also requires current team-memory management permission. Rules retain existing creation-order precedence. User/workspace changes, membership removal, archive/withdrawal and changed bytes or versions reject creation and replay. Server-owned IDs derive from actor plus command ID; replay compares the entire stored snapshot, excluding creation time. Relation and body-free audit commit together. Audit failure rolls both back; competing/restarted writes reuse one record.

`POST /api/memory/relations/query` reads one SQLite snapshot of the explicit project. It is a human governance/read API, not a new SDK tool or model-context policy. Every root, node, annotation target and attached evidence independently passes current visibility and lifecycle checks. Private documents and raw Artifacts require the current owner, including for admins. Only current private personal Memory and accepted project/team Memory enter this graph. Candidate/disputed/archived Memory and private-chat/foreign/archived Tasks do not.

The graph reprojects native Task dependencies/parent relationships in both directions. Accepted native Task Review/Run/sealed-Artifact proofs can link eligible Memory to its current Task and independently visible Artifacts. Frozen Memory parents and original personal-share metadata are checked against their current records; sharing does not expose another user's private parent. Review caches use record kind plus ID.

Document citations require exact current native imported chunks, frozen Fact document evidence, or frozen literal source-span evidence. Document/Memory owner and project identity must agree, including for otherwise readable global notes. Fact/span hashes and versions must still match; version-only legacy links do not invent a frozen body hash. Document backlinks apply the eligible type/owner/project/version/hash predicates before the candidate limit and repeat the actual proof. Unproven newer legacy links cannot hide older qualified facts. This does not claim that a plain chunk stored a historical whole-document hash: it proves its exact current literal chunk and returns the current document hash.

Query limits are two hops; default 20 nodes/40 edges/8,000 JSON characters, maximum 40/80/12,000. Each candidate query reads at most 128 rows, with 512 candidate rows per request. Payload proof decoding is charged against 200 record reads and 4 MiB. Individual payload ceilings are 64 KiB for Memory/Task/Thread/Review/span/User, 128 KiB for Run, 256 KiB for Artifact/project, 16 KiB for an annotation and 1,200,000 bytes for a document, whose text also cannot exceed 1 MiB. Authorization/evidence size checks precede decoding. These are application decoding/output limits, not OS isolation or a SQL latency guarantee. Visibility predicates precede candidate limits; no hidden-node/edge totals are returned. Cycles cannot bypass depth, record or output budgets. Unsupported legacy IDs outside the 1–120 character interface are skipped in backlink candidates.

Results expose bounded titles, kinds, current versions/hashes, relation state and navigation, without summaries, quotes or Artifact bodies. Metadata-only diagnostics distinguish visible truncation. Native edges are reconstructed from current domain records; opaque legacy edges remain available through the existing lineage API, without being asserted as verified graph edges.

Task and Knowledge drawers reuse a small relation panel. Account/workspace/project/root form the cache key; a failed fresh query hides cached results. Safe local links open the matching knowledge document or project-scoped Task drawer. An authorized Memory panel can annotate already displayed records using a selected current Task/document. Confirmation starts unchecked; retries with the same form snapshots retain their command ID. Arbitrary-record discovery and candidate-review workflows are not added here.

## Validation and boundary

Behavior is checked at the API/service and persisted-domain seams: native accepted review evidence, scoped graph traversal, frozen documents/spans, private-origin isolation, current authorization after a writer-lock wait, policy precedence, command conflicts, rollback, concurrent/reopened replay, changed stored snapshots, stale bodies without version changes, cycles and candidate/read/output boundaries. Missing citations/backlinks, collection-ID collision, global-note/project-document mismatch, legacy-link starvation, altered replay records and unsupported legacy IDs failed before the corresponding fixes.

Final Python/frontend/build and browser evidence is recorded in `docs/verification/2026-10-07-current-project-memory-relations.json`. Browser QA uses the same isolated task space/database as previous slices, with all Providers disabled. It checks native citation, candidate save, document navigation/backlinks, explicit confirmation, same-form replay, backend restart, source edit invalidation and the Task drawer. Pointer actions encountered nested-drawer interception; keyboard focus/Space/Enter verified the real controls. No screenshot is claimed.

General external Source version/archive/snapshot contracts, connectors, model-inferred relation extraction, broader record discovery, Artifact/Memory-parent reverse indexes, graph delivery into the SDK, complete context/Runner budgets and real-model/enterprise acceptance remain separate work. This local slice does not complete stages 3–5, replace current governance or justify Neo4j.
