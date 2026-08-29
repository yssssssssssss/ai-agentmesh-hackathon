# Universal Skill Pool — Runtime Dispatch and Capacity Closure

- Date: 2026-08-29
- Branch: `feature/universal-skill-pool-platform`
- Base: `c0698c1` (`Update Phase 3 verification evidence`; implementation base `25aaf06`)
- Status: local durability/capacity implementation; production rollout still blocked by external gates

## Implemented locally

- Added indexed `run_dispatch_receipts` with immutable operation keys, per-Run active uniqueness, `pending → started → settled` CAS transitions, process epochs, generations, attempts, and audit events.
- New Standard direct, Standard planned, and DeepSearch planning Runs persist a pending dispatch in the same SQLite transaction as the Run claim.
- Standard and DeepSearch Plan approvals can persist an `approved_plan` dispatch in the same transaction as the approval transition.
- Startup starts a long-lived, wakeable dispatch pump: it repeatedly drains up to 1,000 pending receipts, wakes on capacity release, and stops under process quiesce. Planned work is not claimed while orchestration is `off`.
- DeepSearch dispatches are left to the existing two-worker `DeepSearchRecoveryCoordinator`; runtime completion wakes and resets that coordinator's cursor. Restarted `approved_plan` work therefore enters checkpoint-aware execution recovery rather than a fresh Plan claim.
- Approval atomically hands an active planning receipt off to the new `approved_plan` receipt, so an immediate approval cannot violate the one-active-dispatch invariant; execution remains queued until the planning task exits.
- Background completion settles the corresponding dispatch only after Runtime work and output projection return.
- Added idempotent `RunOutputProjectionReceiptV1`; assistant message, SDK-session synchronization, optional memory, projection receipt, and `run_output_projected` event commit in one transaction.
- Terminal pending dispatch recovery repairs missing message/status-only projections before settlement.
- Added process-wide Runtime capacity limits (10 Runs, 2 per user, 3 executing nodes, 4 concurrent LLM calls, and 6 concurrent Tool-provider calls) and retained the existing SSE limits (10 process, 2 per user, 1 per Run) and DeepSearch recovery worker limit (2).
- DeepSearch clarification reserves the same process/user Run capacity before any requirement mutation and returns stable `429 + Retry-After` on saturation.
- Added active dispatches to offline quiesce inventory. Rollback refuses terminal Runs with missing projection, preserves already-terminal Run/Plan state once projection exists, and only marks planned writes unknown when an unresolved or `outcome_unknown` write remains.

## Safety limits

- A pending dispatch is replayable because provider work has not been claimed.
- A started Standard dispatch from an older process fails closed; a started DeepSearch dispatch is reset only for checkpoint-aware recovery.
- Runtime Tool claims remain the authority for uncertain non-read side effects; dispatch replay never overrides an `external_outcome_unknown` result.
- The application SQLite writer lock remains the process-ownership boundary.

## Validation

- Backend: `1698 passed, 6 skipped` in `208.70s`; the only warnings were pre-existing SWIG deprecations.
- Focused dispatch/quiesce/recovery/Tool-revocation regression suite: `47 passed`; the final DeepSearch recovery mode-race suite: `18 passed`.
- Frontend: `161 passed`; production build and the 500 kB bundle budget passed (largest JS bundle: `315952` bytes).
- OpenAPI and generated TypeScript schema were regenerated with no tracked diff.
- `ruff check .` and `git diff --check` passed.
- Independent reviewer follow-up: no remaining P0/P1/P2 findings; merge verdict `OK`. The review did not satisfy external production approval/provenance requirements.

## External gates still required

Independent review/provenance, protected release and attestation, real Provider acceptance, production ingress/process-manager rehearsal, and production-shape concurrency/rollback evidence are not represented as locally satisfied.
