# Authorized temporal fact context

Status: accepted for the first structured ContextAssembler slice, 2026-10-04.

## Decision

Extend the existing MemoryContextService and Memory bundle with an optional
`FactContextSelectionV1`. Continue using the same Memory identities, governed
versions, citation reservations and use receipts. The selector reads through
MemoryFactsService and its existing source/temporal/conflict authority; it does
not synthesize facts from summaries or create another Memory content store.

Only a small set of explicit current-project owner questions receive automatic
fact routing. Free-form research requests, unnamed other projects and historical
questions are not guessed into current-state queries. The existing memory_search
tool additionally accepts typed entity/predicate/time queries. Its Run-scoped
input defaults project and project/Task subject IDs from the authorized Run;
people and terms require explicit IDs. An explicitly different project is refused.
Ordinary summary retrieval retains its existing contract.

## Selection and delivery

Current actor/project authorization, Memory lifecycle, scope, type and layer
filters apply in SQL before bounded hydration and conflict detection. Frozen
filters are intersected with current Agent binding policy on recovery. Historical
subject membership is not re-read as private current data: the currently eligible
Memory and its approved evidence remain the authority.

The selected point in time, assertions, source references, Memory versions/hashes
and result outcome are frozen. Context renders complete qualified facts and their
labels; it omits unselected summaries and procedure steps. Unknown, insufficient
evidence and conflict outcomes carry a diagnostic rather than a confirmed value.
Unsafe metadata is quarantined. If complete fact groups exceed the Memory budget,
the whole selection is budget_dropped rather than silently omitting participants
or cutting an assertion. The complete SDK request still passes the separate
full-request budget before any local model handoff.

Recovery and every handoff re-query the frozen entity/time under current authority
and compare the source-backed result. The Store repeats that query within the
same BEGIN IMMEDIATE transaction as receipt commit. This catches newly introduced
conflicts as well as changed evidence even when the originally selected Memory
versions remain unchanged. SDK tool use still waits for its exact complete output
to enter an admitted request; truncated Memory output is rejected by the existing
tool boundary. Returning a tool value alone records no use.

## Withdrawal and compatibility

Pending bundles can hold withheld candidate facts even with no selected hits.
Forgetting therefore follows both hit references and frozen fact-result references
when redacting Run snapshots and pending tool deliveries. Tombstone triggers also
fence late restoration through either reference path. Reopening the database
preserves the barriers.

The new optional bundle field is excluded when absent, preserving canonical
serialization of existing summary bundles and frozen snapshots. Pydantic 2.13 is
the tested minimum for this serialization behavior; the offline dependency lock
remains at the existing 69 packages. The extended native tool implementation is
version 2. Audit metadata contains counts, outcome, decision and query hashes.

Remote Runner fact delivery is withheld until its actual-delivery acknowledgement
and source revalidation protocol is implemented. Cloud preparation cannot count
as remote fact use.

## Remaining work

This is a structured fact slice, not the completed ContextAssembler. Broader
Task/Review status routing, manual terminology aliases, procedure applicability
and reuse, per-candidate UI decisions, budget-driven selection across all input
classes, authorized retrieval capacity, the frozen 120/24 evaluations and real
model quality remain subsequent work. Literal/current evidence identity does not
establish semantic entailment or a real-Provider quality score.

Verification: `docs/verification/2026-10-04-temporal-fact-context-regression.json`.
