# Source-backed temporal Memory payloads

Status: accepted for the first Stage 3 slice, 2026-10-04.

## Decision

Attach optional `MemoryFactV1` and `ProcedureMemoryV1` payloads to the existing
Personal/Project/Team Memory records. Keep Memory governance as the authority for
ownership, scope, revisions, review and lifecycle. No separate fact database or
graph authority is introduced.

New payloads use `user-memory-content-v2` or `memory-content-v3`. Records without
those payloads retain their existing canonical content hash. Absent new capture
and revision fields retain existing command hashes; explicit revision nulls are
distinct from omission because they remove a payload under independent review.

Explicit private fact confirmation references the owner's persisted Document
version and `document-fact-evidence-v1` hash. Confirmation, idempotent command,
personal correction, old-record deprecation, indexing and safe audit are one
SQLite transaction. A correction submits the complete approved fact intervals;
the service does not infer when an old assertion stopped being true.

Reviewed Task capture freezes the accepted Review and sealed Artifact references.
Procedure confirmation and successful Run evidence come from that existing
accepted Review, never from caller-supplied success claims. Team payloads remain
proposed until an independent Memory Review. Capture, revision and acceptance
recheck subjects and evidence inside the existing governance transaction.

Temporal queries read one authorized SQLite snapshot. Valid time is separate
from observation time, endpoints are half-open, and day/month precision requires
matching local calendar boundaries. Project/Task/User subjects use actual IDs;
terms normalize only inside their project namespace. Names do not merge people.

Current accepted/private active Memory versions supply historical intervals;
deprecated, archived and superseded records do not re-enter current queries.
Changed/unavailable source versions yield insufficient evidence. A newer
observation does not win a conflict. `participant`, `constraint` and `tag` are
multi-value predicates; other v1 predicates are single-value. Incompatible values
conflict only where their effective intervals overlap the requested time range.
Unicode comparison uses the same NFC equivalence as canonical JSON.

Source checks cache only within the open SQLite snapshot and include ownership,
project and provenance identity. Candidate/result limits are explicit diagnostics,
never silently scored as complete results. Ordinary audit includes IDs/counts,
not source or fact bodies.

## Reachability and limits

Public APIs provide owned Document evidence identity, explicit private fact
confirmation/correction and authorized point/interval queries. Existing Task
capture/revision APIs accept optional structured payloads. The knowledge drawer
shows validity, observation, classification, evidence and procedure conditions
for review and inspection.

Legacy summary retrieval, summary generation, marketplace publication and legacy
sharing do not flatten structured payloads into unchecked automatic context.
The full ContextAssembler must check temporal conflicts, procedure applicability,
budgets and actual delivery before enabling automatic injection.

This slice does not implement durable extraction/forgetting jobs, source tombstone
cleanup, alias correction UI, full prompt budgets, semantic entailment evaluation,
procedure reuse or real-model quality measurement. A human source-backed assertion
is recorded as human confirmation; verifying its pointer/hash is not a semantic
proof that every value is entailed by the source text.

ADR 0020 records the subsequent durable document learning and owned forgetting
slice. The limits above describe this ADR's original verification snapshot.
