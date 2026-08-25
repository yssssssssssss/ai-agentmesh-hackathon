# Research-v2 Writer Retirement Receipt

## Scope

This receipt records retirement of the research-v2 writer. It does not authorize or record deletion of historical Runs, Artifacts, messages, or SQLite tables. Research-v3 remains preview-only.

## Pre-retirement settlement

- Cancelled the expired plan-approval Run `run_288ba34a7164` through `cancel_agent_run_tree`.
- Moved `invocation_c7ac2e53c80fc1294de0d9d5dbb00608` from `sent` to `unknown` through the repository state machine.
- Moved `invocation_a11f75966bba036f4b7ced4ea78410fd` from `sent` to `unknown` through the repository state machine.
- Preserved the pre-retirement database at `data/backups/agentmesh-pre-research-v2-retirement-20260825.sqlite3` (SHA-256 `6dee573a3e07827f19b6beb78ba32b34c2327b9e9ad6bd86974303db849cb255`).

No Provider acknowledgement was fabricated and no unknown invocation was retried.

## Canonical decision receipt

The `decision_receipt_hash` for the `draining -> retired` compare-and-swap is the SHA-256 of this exact UTF-8 string:

```text
{"active_generation":"research-v2","decision":"retire-writer-after-settlement","historical_data":"retained","target_lifecycle":"retired","version":1}
```

The resulting receipt hash is
`14a4f6fca80b3d91c17321065699130b44fc44db7a03561e45ab490d7aa0c273`.
The durable control row is `research-v2 / retired / epoch 2`. Advancing to
research-v3 still requires a separate decision; this retirement did not do so.

## Executable surface removed

- The v2 Runtime, actors, capabilities, execution, planning, ports, resource
  snapshot, workflow, and Artifact writer modules are absent.
- FastAPI constructs only `V2HistoryAdapter` and `V2ArtifactHistoryReader` for
  v2. It starts no v2 worker or background task.
- V2 routes expose owner-scoped Run and Artifact reads only. Research mutation,
  retry, cancel, approval, recovery, and purge paths reject v2.
- General Run, Skill-plan, node, result, event, startup reconciliation, and
  retention mutations all skip or reject rows owned by v2.
- The historical readers use SQLite `mode=ro` connections with
  `PRAGMA query_only=ON`; corrupt history fails closed and is never repaired.
- V2 smoke/evaluation code and writer-oriented tests/configuration were removed.
  The hash-locked historical fixture and its provenance files remain unchanged.

## Retained production history

The live database retains all 18 v2 Runs and 119 associated Artifacts. Every Run
is terminal: 3 cancelled, 2 completed, 10 failed, and 3 partial. Tool invocation
accounting contains 9 acknowledged and 3 unknown records, with no `sent` record.
Unknown outcomes remain unknown; retirement did not fabricate an acknowledgement
or retry a call.

No v2 Run, Artifact, receipt, event, or legacy table was deleted.

## Live read-only audit

The final audit opened `data/agentmesh.sqlite3` read-only, kept an independent
observer connection open, and projected every retained Run through the production
history adapter using its persisted owner scope.

- `query_only`: `1`
- Runs projected: `18/18`
- Stored/projected status matches: `18/18`
- Runs reporting integrity errors: `0`
- Runs with a visible verified report: `5`
- Observer `PRAGMA data_version`: `1 -> 1`
- Database SHA-256 during the final audit window, before/after:
  `9f2d3b60ab14321a6566d7b97ae6cd3781b0a486859bd8246510016f0874c908`
- Changed related-table snapshots: none

The row comparison covered all v2-owned rows in `agent_runs`, receipts, events,
workflows, requirements, plans, commands, attempts, steps, Tool invocations,
model-call receipts, Artifacts, and Run-linked records, plus the writer-control
row. Counts and content hashes were identical before and after all 18 projections.

## Regression verification

- Backend Pytest: 1,251 passed (5 third-party SWIG deprecation warnings).
- Ruff: passed.
- Frontend Vitest: 176 passed.
- Frontend production build: passed; bundle `490571 / 500000` bytes.
- Research Playwright E2E: 3 passed.
- `git diff --check`: passed.
