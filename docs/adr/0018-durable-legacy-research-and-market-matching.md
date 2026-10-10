# ADR 0018: Durable legacy research delivery and marketplace matching

## Status

Accepted for the single-process SQLite implementation.

## Decision

Attach delivery state to the existing research request post. Claim and outcome changes
are SQLite transactions; manual dispatch and the background drain share that claim.
Record exact request/context identity, attempts, leases, safe error codes, retry time,
evidence pointer and outcome. Existing Task, Thread and evidence remain the business
authorities. This compatibility path cannot execute managed Project Tasks.

Read retries use at most three attempts, 5/30 seconds and valid Retry-After values.
Permissions, source identity and Task settlement are checked around provider reads.
Interrupted reads without evidence can recover; partially published legacy results are
indeterminate and require reconciliation. The old multi-write fulfillment is not made
atomic merely by adding a durable claim.

Persist a rebuildable matching receipt per helper/signal. Its fingerprint covers the
signal content, eligible helper knowledge, matching policy/model and current identity,
project, participation, permission and consent versions. Negative decisions are cached;
read failures remain retryable, authorization failures wait for changed configuration,
and interrupted delivery is indeterminate. Do not replay an unknown multi-write delivery.

Store participant/signal scan cursors separately from business authority. Paginate
active participants and currently visible signals before hydration. Cap matching reads
across the worker tick, including negative decisions. Publisher context is restricted to
eligible owned records and bounded before rendering.

Joining the market does not create a standing consent. Scouts never grant consent;
existing explicit consent remains subject to revocation and sensitive-content gates.
The shared board contains collaboration status only. Raw needs, private answer text,
provider exception text and credentials do not enter ordinary worker logs.

## Limits and next work

Matching receipts are cost/recovery records, not a replacement for the planned
DelegatedQuery aggregate. The legacy answer gateway still needs durable answer artifacts,
explicit answer-policy choices, evidence-aware outcomes, frozen context and adoption
commands. Its unconfigured-model template is not validated as a successful real answer.
Source forgetting must invalidate derived records through the later learning/lineage work.

Local complete regression: Python 3.12/3.13 each 2,011 tests, frontend 212 tests and
browser 79 tests. These checks do not establish real-provider or model-answer quality.
