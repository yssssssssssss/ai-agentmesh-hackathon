# ADR 0016: Trusted query results and deterministic project inspections

Date: 2026-10-04
Status: Accepted; manual inspection slice implemented, automatic execution remains separate.

## Context

Fixed acquisition samples and local metric fixtures previously looked like successful production queries. Schedule definitions existed without a durable execution path. Adding background execution on those semantics would create misleading reports.

Task, Task Review, Memory Review and their frozen command receipts already own project facts. A model must not infer counts, delivery transitions or missing history from prose.

## Decision

Provider results carry an independent data mode (`real`, `demo`, `derived`) and outcome. Production evidence-required query paths validate evidence before persisting or completing. Demo fixtures require the exact opt-in value `1`; provider fallback mode does not prove a real result.

Manual inspections use one authorized SQLite read transaction. The current persisted user, workspace and project membership are checked inside that snapshot. Only shared task-kind Tasks enter the report, including archived Tasks needed to interpret dependencies; personal conversation Tasks are excluded even for managers. Memory-review summaries require the current assigned reviewer and effective review permission, and contain no private memory payload.

The three initial templates compute daily progress, blockers/overdue/stale work and pending reviews. Daily progress compares frozen command versions, including review-driven Task transitions. It reads the predecessor outside the requested window to identify reopening correctly. Current state alone cannot establish a historical transition; incomplete history returns `insufficient_evidence`. Daily progress with no new changes returns `no_change` while retaining existing risks for inspection. Staleness initially means seven days without a Task update.

Reports expose snapshot time, source watermarks, changes, risks, review assignments, suggested navigation, missing data and exact source versions. Suggestions only navigate to existing Task/Knowledge flows; inspection never assigns, completes or accepts records. These local reads do not require Task write mode, an LLM or an external provider.

The read aggregate is bounded at 10,000 Tasks, 50,000 frozen command versions and 10,000 records per review class. Exceeding a bound is explicit insufficient evidence, never a silently complete report. Historical receipts are read only for daily progress. The UI shows at most fifty entries per class with an explicit notice.

Development and CI install from `uv.lock`; the initial lock preserves the validated environment's dependency versions. CI tests Python 3.12 and 3.13. Test bootstrap and browser-test servers isolate host Provider/CLI configuration. Real Provider smoke remains a separate release check.

## Consequences

Manual inspection works before scheduling and without enterprise credentials. Existing Task/Review commands remain the only mutation authority. The automation phase must persist reports and occurrences, recheck execution permission, and use the existing durable Runtime dispatch rather than treating this endpoint or a stored schedule as a background agent.

No new database, worker service, orchestration framework or memory authority is introduced. This decision does not assert real enterprise connector validation or scheduled execution readiness.
