# Memory Governance Slice 4A Verification

- Date: 2026-09-02
- Branch: `feature/memory-governance-slice4`
- Base: `da8a25aacd44e0c6d30a6f14bfe7a9c0510ecdaf`
- Status: Slice 4A implementation complete; revision and full lifecycle remain bounded Slice 4B scope

## Delivered scope

- Added ADR 0012, defining AgentMesh as the authority for Memory identity, scope, lifecycle, review, provenance, and audit.
- Added additive `MemoryProvenanceV1` fields to `UserMemoryItem` and `MemoryItem`; legacy rows remain readable and are projected as `legacy_unverified` rather than receiving invented lineage.
- Added base Memory versions, supersession/archive fields, `MemoryReviewV1`, and the `archived` status needed by the later lifecycle slice.
- Added `MemoryEntryViewV1`, unified pagination/detail, and lineage projections.
- Added explicit capture from an accepted Task Review to either:
  - private Personal Memory owned by the Run owner; or
  - proposed Team Candidate with an independently assigned Memory Review and private Inbox item.
- Froze source Task, Run, Task Review, Artifact IDs/hashes, source Memory IDs, creator, and creation time in provenance.
- Added independent Memory Review accepted/rejected decisions with optimistic Memory and Review versions.
- Accepted candidates become `team_accepted + accepted`; rejected candidates remain `team_candidate + disputed`.
- Added Task-to-Memory links and Memory-to-Task/Run/TaskReview/Artifact lineage, including Task navigation from pending and accepted Knowledge surfaces.
- Added Task Center controls to capture accepted delivery as Personal Memory or Team Candidate.
- Added Knowledge Center controls for assigned Memory reviewers, plus reviewer-specific Inbox navigation and cross-project context.
- Added stable browser command identities for capture and Memory Review decisions, retained across ambiguous responses and dialog closure.

## Transaction and authorization guarantees

- Capture rechecks actor status, Workspace/Project membership, accepted source Task Review, Run ownership, canonical sealed Artifact projections, content hashes, and provenance under `BEGIN IMMEDIATE`.
- Personal capture writes Memory, lineage relations, AuditEvent, and command receipt atomically.
- Team Candidate capture additionally selects the reviewer under the transaction and atomically writes `MemoryReviewV1` plus its private Inbox projection.
- Memory Review decision rechecks reviewer identity/effective permission, candidate visibility, Memory and Review CAS versions, accepted source Task Review, frozen Artifact integrity, and Inbox identity under one transaction.
- Review decision atomically updates Memory, Memory Review, Inbox, FTS projection, AuditEvent, and command receipt.
- Exact command replay is side-effect free; conflicting reuse of the same command ID fails closed.
- Legacy `/api/memory/{id}` PATCH remains available for legacy rows but rejects governed rows after first applying object visibility checks.
- Policy-granted regular users can be selected as Memory reviewers and receive matching candidate visibility; role names are not substituted for effective permission.

## Retrieval safety

- `team_candidate` is removed unconditionally from Agent Runtime retrieval scopes.
- Governed shared Memory enters automatic context only when `scope=team_accepted` and `status=accepted`.
- Inactive Personal Memory and disputed, deprecated, expired, archived, or proposed governed Memory are excluded.
- Eligibility filtering occurs inside `SQLiteStore.search()` before result-count and character budgets, preventing ineligible records from crowding out accepted knowledge.
- `RetrievalService`, `ToolGateway.memory_search()`, `SQLiteStore.search_for_agent()`, and legacy `PersonalAgent._search_team_brain(AUTO)` all use the same eligibility boundary.
- Candidate Blackboard posts are excluded from the legacy automatic fallback pool.

## Privacy and compatibility

- Personal Memory remains owner-only.
- Team Candidate visibility is limited to its author and users with effective `accept_team_memory` permission in the same Workspace/Project.
- Reviewer-specific Memory Inbox items cannot be read or mutated by unrelated admins or users.
- Task Review acceptance never publishes Team Knowledge automatically.
- Memory Review is a separate durable decision from Task Review.
- Existing manual, document, brief, Blackboard, Personal Memory, and legacy Team Candidate paths remain readable and retain their compatibility APIs.
- No LLM, Embedding, Web, O2, MCP, or Data Provider is required for capture, review, lineage, restart, or audit.
- Task and Memory governance writes remain disabled when `AGENTMESH_TASK_MANAGEMENT=read_only`.
- Universal orchestration remains `AGENTMESH_SKILL_ORCHESTRATION=off` for production.

## Review remediation

Independent static review initially found six issues: candidate/disputed Memory could still enter `RetrievalService` and legacy `PersonalAgent` context; lifecycle filtering occurred after retrieval budgets; a singleton browser command slot could lose ambiguous capture identity; policy-authorized regular reviewers could be selected but not see candidates; pending candidates omitted Task navigation; and legacy PATCH disclosed governed object existence before authorization.

The final implementation now:

- applies lifecycle eligibility centrally before search budgeting and across all runtime retrieval paths;
- excludes Memory Candidate Blackboard records from legacy fallback retrieval;
- retains capture command IDs in a payload-keyed map until confirmed success;
- aligns reviewer selection and candidate visibility on effective permission;
- exposes pending-candidate Task provenance and cross-project navigation;
- authorizes legacy PATCH visibility before returning the governed-transition conflict;
- revalidates Artifact integrity both at capture and at Memory Review decision.

Final reviewer verdict: no remaining P0, P1, or P2 findings; merge verdict `OK`.

## Validation

- Backend full suite: `1784 passed, 6 skipped` (`1790` collected).
- Memory Governance suite: `9 passed` as part of the final backend run.
- Frontend unit suite: `186 passed` across `29` files.
- Playwright full suite: `71 passed` in Chromium, including governed Team Candidate review and ambiguous capture retry.
- TypeScript production build and bundle budget: passed; largest bundle `316987` bytes (limit `500000`).
- Ruff: passed.
- OpenAPI export and generated TypeScript client: regenerated.
- `git diff --check`: passed.

The first full backend invocation crossed the fixed absolute expiry embedded in an older DeepSearch test fixture. The fixture now anchors its relative +7/+8-day semantics to the test process time; all 34 focused DeepSearch Requirement tests and the subsequent full backend suite passed.

## Deferred Slice 4B

- Memory revisions and `supersedes_memory_id` activation.
- Atomic deprecation of superseded accepted versions.
- dispute, deprecate, expire, archive, and restore state transitions.
- Complete governance-history filters and revision UI.
- Additional Run/Artifact reverse projections beyond the frozen lineage API.
