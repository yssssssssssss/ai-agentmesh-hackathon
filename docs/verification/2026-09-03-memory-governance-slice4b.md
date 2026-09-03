# Memory Governance Slice 4B Verification

- Date: 2026-09-03
- Branch: `feature/memory-governance-slice4b`
- Base: `1b12887d8919f9a00f400d1a695ec90352e31c4d`
- Status: implementation and local verification complete; pending PR integration

## Delivered scope

- Added governed Team Knowledge revisions through `POST /api/memory/{memory_id}/revisions`.
- A revision is a new Team Candidate with its own independent `MemoryReviewV1`, reviewer Inbox item, command receipt, and AuditEvent.
- Revision provenance freezes the predecessor Memory ID, record version, and canonical content hash, while carrying forward the original Task, Run, Task Review, and Artifact lineage.
- The predecessor remains unchanged while a revision is pending or rejected.
- Accepting a revision atomically activates the new Team Knowledge and deprecates its predecessor under one `BEGIN IMMEDIATE` transaction.
- Rejected revision candidates remain disputed and do not deactivate the accepted predecessor; a later corrected attempt is allowed when no pending or accepted sibling exists.
- No-op revisions and concurrent pending or already-active successor branches fail closed.

## Lifecycle state machine

Added versioned command handling through `POST /api/memory/{memory_id}/transitions`:

- accepted → disputed, deprecated, expired, or archived
- disputed → deprecated, expired, or archived
- proposed → expired
- deprecated or expired → archived
- archived → its recorded pre-archive status

Additional invariants:

- Direct lifecycle commands cannot accept a Team Candidate or bypass Memory Review.
- Expiring a proposed candidate atomically marks its Memory Review `cancelled` and resolves its reviewer Inbox item without recording a reviewer rejection.
- Restoring an archived-from-accepted revision is rejected when another accepted sibling already supersedes the same predecessor.
- Governed lifecycle mutation requires effective `manage_team_memory`; the Memory owner may propose a revision but cannot directly change Team Knowledge lifecycle without that permission.
- Legacy records remain readable and keep their compatibility path, but cannot acquire invented provenance through revision or lifecycle endpoints.

## Integrity, concurrency, and idempotency

- Every revision and transition uses a stable caller-supplied `command_id` and canonical request hash.
- Exact replay returns the same persisted response projection; conflicting command reuse returns `409`.
- Candidate Memory, Memory Review, reviewer Inbox, lineage relations, AuditEvent, and receipt are created atomically.
- Revision acceptance revalidates candidate and Review CAS versions, predecessor version/hash/status, original Task Review, and sealed Artifact IDs/hashes.
- Predecessor deprecation, successor activation, Memory Review decision, Inbox resolution, FTS update, AuditEvent, and receipt commit atomically.
- Source content tampering without a version increment is detected by the frozen content hash.
- Browser revision and lifecycle command IDs are keyed by canonical payload intent and retained after ambiguous responses.
- Existing Slice 4A receipts without the additive `content_hash` projection remain decodable and replayable.

## Retrieval and privacy

- Governed proposed, disputed, deprecated, expired, and archived Memory is removed inside the SQLite FTS, LIKE fallback, and vector candidate queries before their `LIMIT` caps and before RRF/result budgets.
- Regression coverage uses 225 inactive FTS records and 60 higher-scoring inactive vector records to prove accepted knowledge cannot be crowded out.
- Pending revision records and their governance events remain concealed from unrelated project members until acceptance.
- Server-derived list and detail `allowed_actions` both account for hidden pending successors without exposing those successor records.
- Personal Memory remains owner-only; Run and Artifact reverse Memory links remain Run-owner-only and apply Memory visibility checks.
- Project-aware Memory navigation preserves non-default project context.

## Read models and UI

- Unified Memory entries expose content hashes, archive origin state, Memory Review, revision links, and governance events.
- Added Run and Artifact reverse Memory-link endpoints without exposing Run input/output or Artifact content.
- Governance history uses a dedicated server-filtered, paginated query with status, scope, kind, and layer filters.
- Empty filtered pages retain filters and Previous/Next controls, so users can recover without reloading.
- Off-page and cross-project Memory deep links hydrate through the lineage endpoint.
- Knowledge detail shows predecessor/successor links, lifecycle history, content hash, and server-authorized revision/lifecycle actions.
- Revision and lifecycle forms do not optimistically mutate business state; a conflict preserves the revision draft and reloads server data.
- Desktop and 375px browser coverage verifies the governance flow without page-level horizontal overflow.

## Review remediation

Static review initially found five blocking or material issues:

1. restoring an archived accepted successor could create two accepted siblings;
2. inactive records could crowd accepted Memory out before FTS/vector candidate caps;
3. governance history filtered only the first 100 loaded records;
4. revision links lost project context;
5. transition replay responses differed from the first successful response.

A later re-review found two projection issues:

1. zero-result governance filters removed their own recovery controls;
2. list `allowed_actions` ignored hidden manager-created pending revisions even though detail and mutation checks rejected a competing revision.

All findings were corrected with transaction checks, SQL prefilters, server-backed pagination, project-aware links, stable receipt projections, persistent empty-state controls, and global project successor detection. Final AI technical review reported no remaining P0, P1, or P2 findings and a merge verdict of `OK`; this is technical review, not independent human approval or production authorization.

## Validation

- Backend full suite: `1804 passed, 6 skipped` (`1810` collected).
- Focused Memory Governance suite: `27 passed`.
- Frontend unit suite: `190 passed` across `30` files.
- Playwright full suite: `72 passed` in Chromium.
- Interactive Chromium inspection: desktop `1512×823` and mobile `375×812`; mobile document width remained `375`, all four governance filters remained usable, and pagination controls retained 40px hit areas. Screenshot capture in the auxiliary browser timed out, but semantic inspection and measured layout checks completed; Playwright supplied the executable UI verification.
- TypeScript production build: passed.
- Bundle budget: passed; largest bundle `317111` bytes (limit `500000`).
- OpenAPI export and generated TypeScript client: regenerated.
- Ruff: passed.
- `git diff --check`: passed.

## Boundaries retained

- Task Review and Memory Review remain separate aggregates and decisions.
- Task Catalog v1/v2, FrozenPlan v1, and Snapshot v1 canonical contracts are unchanged.
- Core Task, Review, Memory, lineage, receipt, and audit paths do not require LLM, Embedding, Web, O2, MCP, or Data Providers.
- Production remains `AGENTMESH_TASK_MANAGEMENT=read_only` and `AGENTMESH_SKILL_ORCHESTRATION=off`.
- SQLite remains a single-Workspace, single-process, single-writer deployment model.
- AI review and green repository CI do not provide production attestation or independent human approval.

## Deferred

- Multi-source Memory merge is not part of Slice 4B; revisions have one direct predecessor.
- Personal Memory lifecycle expansion remains separate from governed Team Knowledge lifecycle.
- `MemoryUseReceiptV1`, context-use accounting, and second-Task reuse proof remain Slice 5.
- Scale benchmarking and advanced project operations remain later slices.
