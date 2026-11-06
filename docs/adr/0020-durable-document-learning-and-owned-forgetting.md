# Durable document learning and owned forgetting

Status: accepted for the second Stage 3 slice, 2026-10-04.

## Decision

Keep Memory content, lifecycle and independent team review in the existing
aggregates. Learning jobs, preferences, source spans, command receipts and
tombstones are subordinate records in the same SQLite database. No additional
runtime, vector service or fact authority is introduced.

Learning defaults off. Execute mode also requires current owner opt-in, active
identity and current project access. The worker discovers persisted owned
Document versions with a bounded scan; admission freezes actual source ID,
version, canonical content hash and extraction schema. Oversized inputs remain
visible as blocked jobs rather than truncated successful extractions.

The existing model factory and official Agents SDK run extraction with no tools,
one turn, a 2,000 output-token limit and an outer 90-second deadline. SDK and
transport automatic retries are disabled for this path. The durable job admits
at most three attempts under a 32,000 reserved-token cap and an independent
owner daily cap. Reservations include instructions, source JSON and output
schema using conservative UTF-8 byte estimation; they are not actual token
usage. Crashes and unknown usage never refund reservations. Provider-reported
usage is recorded separately, and missing usage cannot become zero-cost success.

Attempt/lease epochs fence late completion. Apply rechecks actor, source,
project, selected model and preference version in its write transaction.
Transient reads retry after 5/30 seconds; authentication, input and budget
failures are blocked/terminal. Manual retry retains attempt and budget history.
Shutdown leaves claimed work recoverable under the existing quiesce controller.

Model assertions remain private proposed Memory. Unicode offsets must select
the literal quote from the current source; persisted spans include its actual
source identity. The owner selects facts, and confirmation regenerates content
only from the selected payload, discarding the model's unapproved summary.
Unknown validity remains unknown. Pointer/hash/quote verification establishes
source integrity, not semantic entailment or model quality. Approved historical
facts can refer to departed subjects without reading their current private data;
current caller, project, Memory and source authorization still apply.

## Withdrawal and lineage

Forget applies only to the caller's own private Memory. Document withdrawal
requires the current source owner. The command checks expected version and
idempotency, redacts owned content, writes tombstones, invalidates provable
derived records and removes FTS/vector/state bytes in one transaction.
Database barriers also reject raw late aggregate writes. Removing vector state
fences an embedding already in flight. A persistent bounded cleanup sweep
repeats projection removal after restart.

New summaries and explicit personal-to-project shares freeze their real parent
IDs, versions and hashes, and commit only against unchanged authorized parents.
Withdrawal follows matching frozen hashes across lifecycle-only version changes.
Legacy records without recorded lineage are not assigned invented evidence.
Shared accepted records become disputed; proposed records expire. Their bodies,
review history and manager archival remain available under team governance.
Source withdrawal cannot restore shared eligibility through a late acceptance.

Knowledge offers private candidate quotes/selection and owner-only forgetting.
Document withdrawal is available through the owned-source API. The UI states
that already delivered content, team review, audit and backups are outside the
deletion command's scope. Platform retention and backup policy still require
the deployment owner's configuration.

## Verification and remaining work

Both locked Python versions passed 2,079 tests, frontend passed 217 tests and
Playwright passed 81 cases. The added local API/browser flow saves preferences,
confirms a source-backed fact, forgets it and verifies unknown query results
without a model. A later lifecycle-version fix passed the 64-test focused
learning/forgetting/facts suite; that fix is subsequent to the full snapshot.
See `docs/verification/2026-10-04-stage3-memory-learning-regression.json`.

Stage 3 remains incomplete: full ContextAssembler and prompt budgets, aliases,
procedure applicability/reuse and the frozen 120/24 evaluations are outstanding.
Core preferences are stored but not automatically injected. Learning heartbeat,
queue-age alerts and Retry-After handling still need integration. General
document-to-team candidates must use independent Memory Review; this extraction
slice confirms private records only. Source changes outside explicit withdrawal
need fresh context checks. Legacy unprovable copies cannot be claimed deleted.
The lineage walk has not passed the large authorized-retrieval benchmark.
Real provider quality, enterprise integration and later SDK/connector phases
are not established by these deterministic checks.

ADR 0021 records the subsequent local request budget and core-preference
injection slice; the remaining-work list above describes this ADR's snapshot.
