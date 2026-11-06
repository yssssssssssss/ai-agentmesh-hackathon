# Committed project change inspections

Date: 2026-10-06
Status: accepted for the local SQLite implementation

## Context

The plan requires local committed Task/Task Review changes to trigger read-only inspections. Existing cron definitions, occurrences, Run dispatch, current authorization and owner-only reports already supply the execution contract. A second event queue or task state machine would duplicate those authorities.

## Decision

Extend the existing definition with explicit `on_project_changes=false` and a server-owned `change_cursor`. The request accepts opt-in and rejects a client cursor. Configuration initializes the watermark inside the authorized write transaction. Opt-in, resuming and changing the template start at currently committed records, without replaying earlier changes. Other edits preserve progress committed after command preparation. Legacy definitions cannot silently enable the trigger.

Only persisted native `task_command_receipts` and `task_review_command_receipts` with a managed Task snapshot are events. Snapshot Task/thread identities join the current project visibility projection; workspace/project and `thread_kind=task` restrict polling and admission. Private chat, foreign records and raw Task edits without a command do not trigger. Rolled-back commands never become visible. No Task/Review title or body enters the preview.

SQLite `created_order` is an append watermark, independent of editable Task timestamps. Two metadata rows identify the first/latest visible unconsumed events. Durable command timestamps set a 30-second quiet window, capped at five minutes for sustained edits; the existing five-minute automatic-run floor also applies. This bounds coalescing, not queue wait when a tick's budget is exhausted. Candidates sort by unconsumed cursor before ID so fresh edits on a previously served configuration cannot starve other pending definitions. A partial index excludes definitions that did not opt in. Each tick retains the existing 1–100 limit and `has_more`.

Observe reads a consistent snapshot without advancing the cursor. Execute reloads the definition/source window after `BEGIN IMMEDIATE`, checks current owner/project/Agent/management permission and Runtime availability, then atomically writes a `change` occurrence, its existing v1 Run/dispatch and consumed cursor. Identity contains definition ID, trigger and cursor. Competition/restart reuse that identity; insert failure rolls back all effects. Change admission leaves the cron slot unchanged. Scheduled/manual admission can consume current changes in the same transaction to avoid another report for already admitted input.

Blocked/overlapping triggers retain blocked/skipped facts and consume their source window, following the existing admission policy. Overlap creates no Run. There is no new automatic replay loop; the next change or ordinary cron/manual inspection can query current state. Normal read retries/deadline, source versions, owner-only Inbox/report, current execution/restore/completion authorization and independent Task/Memory write gates remain unchanged. These templates use zero model calls.

The Tasks form provides a default-unchecked option, explains coalescing/frequency/pause behavior, restores the saved value during editing and labels `变更触发` in history. Older valid definitions default to false. No entity backfill or external webhook is activated.

## Validation and boundary

The missing contract and scan-starvation case failed before implementation/fix. Python 3.12/3.13 related regression each passes 148 cases, including 32 new opt-in, authorization, visibility, time-window, rollback, competition/reopen, fairness, configuration CAS and Task Review/report scenarios. The review case accepts sealed local delivery evidence, verifies the completed Task change/native review-command reference and verifies the inspection leaves the Task unchanged.

Frontend tests/build/OpenAPI checks are recorded in `docs/verification/2026-10-06-committed-project-change-inspections.json`. Ego Lite uses an isolated QA database and explicit test manager/global execute mode: saving opt-in, creating a Task, observing one completed change Run with one tool/zero model usage, opening its versioned real report, pausing and restarting/reloading the same report. Screenshot capture timed out twice; DOM and authorized read evidence are recorded without claiming an image. Test role and global execute mode are restored afterward.

This validates local changes, not external connectors/webhooks, real-model quality, all Runtime/Runner budgets or completion of stages 3–5. The entire backend suite was not rerun for this slice.
