# AgentMesh

Chat-first team agent platform prototype.

**Repository**: <https://github.com/yssssssssssss/ai-agentmesh-hackathon>

## Current Slice

The first implementation slice proves:

1. A user sends a chat message.
2. The backend stores the message.
3. Natural chat stays private, while explicit `$` skills start workflows.
4. The backend creates a task.
5. The task creates an internal blackboard request.
6. A configured research provider returns evidence; demo mode can return explicitly labelled samples.
7. The chat response includes a source.
8. Activity logs record what the personal Agent and external Agent did.
9. The workspace can search chat, activity, blackboard evidence, and memory items with source-aware results.
10. The UI loads workspace, project, user, Agent, and live metric context from the backend.
11. Chat sessions persist as project-bound threads and the UI reuses the active thread for follow-up messages.
12. Search results are filtered by the current workspace and project context.
13. Search supports permission-aware visibility modes: `personal`, `project`, and `team`.
14. Memory review uses explicit states, and accepting a memory promotes it to team scope.
15. `risk_agent` creates policy-backed risk posts and routes human confirmations to Inbox.
16. Chat answers can be synthesized by an OpenAI-compatible LLM when a configured model is selected.
17. External research is behind an acquisition Agent interface, so the crawler/search implementation can be supplied by another project.
18. The API now has a minimal cookie session auth layer, local user lifecycle APIs, and role checks for personal Agent edits and team-memory acceptance.
19. System tools are registered in the backend and explicitly granted to Agents; tools are not automatically exposed to every personal Agent.
20. Text, Markdown, PDF, Word, slide, and image files can be uploaded, parsed, stored, and surfaced as Sources.
21. Workspace/project APIs persist records in SQLite and allow admins to create new workspaces and projects.
22. Blackboard supports agent/system-created posts, read markers, replies, pagination, and a queued auto-post drain path.
23. Risk review uses persisted policy rules for prompt-injection, source policy, approval, and high-risk tool signals; admins can manage rules from the Members page.
24. `data_agent` has a connector registry with a local metrics connector and can answer chat-triggered metric queries.
25. `research_agent` can use a Web acquisition provider when `AGENTMESH_WEB_PROVIDER` is configured.
26. Chat exposes an explicit `$` skill menu for memory search, Brief creation, private notes, external research, data queries, risk review, memory proposals, and system/model info.
27. Brief drafts can be confirmed from Inbox and turned into sourced team memory candidates.
28. Blackboard evidence, decisions, digests, archives, and memory-candidate posts can be promoted into governed team memory candidates.
29. The React `/tasks` route provides a project board/list over permission-filtered Task and Blackboard data. It stays read-only by default; `AGENTMESH_TASK_MANAGEMENT=write` enables versioned creation, editing, assignment, delivery transitions, blocking, cancellation, and archival.
30. In-progress project Tasks can create Agent Runtime v2 Runs with an immutable `task_id`; Task detail exposes safe Run and Artifact summaries while retry preserves the Task link.

## Run Locally

Set up an isolated environment:

```bash
uv sync --locked --extra dev --python 3.12
```

The committed `uv.lock` is the dependency baseline. CI checks clean installs on Python 3.12 and 3.13; use `uv lock --check` to verify it and update the lock intentionally when changing dependencies.

Task and Knowledge drawers now query bounded current-project relations through `POST /api/memory/relations/query`. Native Task relationships, reviewed delivery evidence and qualified document/fact/span citations reuse the current records. An authorized Memory panel can annotate displayed records using frozen Task/document evidence; `POST /api/memory/relations` also accepts other visible endpoints. Candidate is the default, and explicit human confirmation does not change Task/Memory governance or expose private origins. Changed references stop expanding; writes/audit and replay are atomic. See [ADR 0043](docs/adr/0043-current-project-memory-relations.md) for limits and remaining graph/connector work.

The Tasks page provides three project inspections: daily progress, blockers/overdue, and pending reviews. They query shared local Task/Review records without an LLM or Task write mode, show source versions and missing evidence, and link to existing action flows. Project managers can save versioned schedules, edit/pause/restore them, run an inspection, and inspect durable execution records. Reports and Inbox notifications are owner-only.

Automatic inspections default to `AGENTMESH_AUTOMATION_MODE=off`. Use `observe` to calculate due slots and budgets without creating Runs, dispatches, or notifications. `execute` additionally requires `AGENTMESH_AGENT_RUNTIME=v2`; the three templates use the existing Runtime dispatch queue and real local records, with zero model usage. A schedule being enabled does not override this global switch. Historical unvalidated definitions require an explicit project/template resave. Cron is five-field/IANA-timezone, minimum five minutes; missed slots coalesce to the latest, overlap skips, and committed read dispatches recover on restart.

Schedules can explicitly opt into committed project Task/Task Review changes in the same form. This defaults off; private chat and raw edits without a native command do not trigger. A 30-second quiet window merges bursts, sustained edits coalesce within five minutes before queue admission, and automatic Runs retain their five-minute floor. Opt-in/resuming/template changes begin at the current committed watermark. Change Runs use the same authorized read-only dispatch, owner report and Inbox; paused-period changes do not independently replay on resume. History distinguishes change, cron and manual triggers.

Legacy research requests now persist shared manual/background claims, bounded read retries, safe outcomes and restart-visible queue health. Partially published evidence requires reconciliation. Marketplace workers paginate participants and signals, persist matching fingerprints, and never create standing consent. Shared match posts contain status only. Unconfigured/failed answer models return blocked, and absent evidence returns insufficient_evidence. Legacy status posts cannot be adopted as answers. Collaboration now offers durable project queries, owner confirmation and explicit per-peer automatic policies. Automatic answering requires both users' market opt-in, and sensitive inputs still require confirmation. Only requester/target can read a currently authorized sealed result; private adoption is atomic and idempotent. Queries survive restart, while interrupted started model calls are not retried automatically. This first slice covers governed plain-text personal evidence; structured delegation, full synchronous-model budget/delivery governance and real model quality remain in development.

Structured facts and procedures attach to the existing governed Memory records. `GET /api/memory/facts/source-documents/{id}` freezes an owned Document evidence identity; `POST /api/memory/facts/remember` explicitly confirms private facts and optionally corrects an existing owned fact record using its expected version. Corrections submit the complete approved history. `POST /api/memory/facts/query` supports a point or interval and reports conflicts, unknowns or unavailable evidence. Task capture/revision can include structured payloads; team acceptance still requires independent Memory Review. The knowledge drawer displays their times, sources and procedure conditions.

Document learning defaults to `AGENTMESH_MEMORY_LEARNING=off` and additionally requires the owner's opt-in. `execute` observes eligible persisted documents and runs bounded, durable SDK extraction jobs. Exact source spans support private suggestions; the owner must select and confirm facts before activation. Unknown validity remains unknown. Digital Self stores private core preferences and a separate daily learning cap. Knowledge exposes jobs, source quotes, confirmation, bounded retry and owned forgetting. Forgetting/owned document withdrawal writes a durable barrier, invalidates provable derived records and removes searchable bytes; it cannot recall already delivered content, audits or backups. Shared records retain team governance and become disputed/expired when their source is withdrawn. See ADR 0020 for the current limits.

Learning retries respect bounded Provider `Retry-After` timing and preserve unknown-usage reservations. Active extraction renews its fenced lease while rechecking current source and learning policy; opting out cancels the wait. The owner's learning panel shows current authorized queue counts, daily reserved budget, expired leases and cleanup backlog, without job/source bodies in the status API. See [ADR 0031](docs/adr/0031-document-learning-operations.md).

`AGENTMESH_MEMORY_CONTEXT=inject` applies owner core preferences in local direct/Standard execution. Shared Run assembly gives full core preferences priority within an 8000-character component allowance, then budgets the complete recalled material and headers; it uses the existing SQL/fact/reviewed-procedure/Memory authorities. Natural private chat does not automatically retrieve project Memory. Local streamed SDK requests additionally budget the complete instructions, Session, tool results and schemas on every turn, including approval recovery. Unknown tokenizers use an explicitly labeled UTF-8 estimate. Automatic Memory and SDK memory_search results record use after final budget/source checks at the local model boundary. Local direct/Standard approvals restore a private frozen context snapshot and recheck its input, sources, preferences and execution identities before approval and handoff. Owned forgetting redacts affected snapshots and rejects late restoration. Workspace shows recent request budget decisions separately from actual Memory use. Local direct compaction uses the complete first-request budget, even for a few large messages, and retains complete recent user turns and tool-call/result units. The bounded summary must fit before replacing the Session through its existing version check. Adaptive recall allocation and remote context parity remain in development; see ADR 0063 and the complete optimization plan.

Local SDK Sessions bind a private owner/Project and fenced Run writer. Bootstrap imports canonical ChatMessage bodies; append/pop/clear compare observed versions and append commands have durable replay receipts. Memory-derived history rechecks its frozen dependencies, including in off mode; forgetting clears affected cached bodies and blocks late restoration. Compaction has a bounded deadline and repeats Session checks after capacity waits. Direct approvals also freeze Session version/content hash and recheck it in the approval claim transaction. Automatic SDK replay deduplication, unverified legacy migration, general external evidence archives and remote Session parity remain unfinished; see ADRs 0026–0027.

Explicit current-project owner questions route through authorized temporal facts; memory_search also supports typed entity/time queries using current Run IDs. Only complete eligible assertions enter context; conflicts, unknowns and budget drops provide diagnostics. Receipt commit rechecks evidence and newly introduced conflicts in the same transaction. Withheld fact candidates are included in forgetting barriers. Explicit current-project count/status and linked-Task state/dependency questions now route through the current Task/Review SQL authority. `GET /api/task-operations/{project_id}/state` and the governed project_state tool expose the same exact counts and bounded dependency evidence. Private/foreign/archived Tasks are excluded, unavailable dependencies remain unknown, and SQL state creates no Memory use receipts. Frozen results are checked on local approval recovery and model requests. Local Runtime model requests also check current Run/writer identity, actor/project/thread authority and deadline when Memory is off. Capacity-wrapped calls repeat budgeting and source/authority checks after waiting for the model slot; prepared Memory is recorded only at that handoff. Remote Runner admission and complete Session hardening remain unfinished; see ADRs 0021–0025.

Knowledge exposes a current-project glossary confirmed by members with team-memory management permission. Exact aliases preserve original evidence and expose merged conflicts; version changes invalidate frozen term queries and archived SDK output. Task Review capture can explicitly record a procedure. Local project requests select one bounded literal-goal match; typed memory_search accepts procedure_query. Current preconditions, registered native tool grants/versions, installation versions and independent acceptance evidence determine applicability. Unknowns and oversized steps stay out of model context; qualified references never grant or automatically invoke tools. SDK history distinguishes fact-only and procedure delivery, and forgetting redacts withheld selections. See ADRs 0028–0029.

Memory search applies current scope, lifecycle, layer and binding filters in SQL before its bounded candidate limit. Search hits and their visibility checks share a read transaction; unsafe Memory is removed before result budgeting. Local FTS recall queues without holding external embedding calls. The isolated 50k-record, 10-concurrent-query FTS benchmark passed at 642.471ms p95; vector capacity and real-model quality remain unverified. See [ADR 0030](docs/adr/0030-bounded-authorized-memory-search.md) and run `.venv/bin/python eval/run_memory_retrieval_benchmark.py --output /tmp/memory-retrieval.json` to reproduce.

Agent memory binding configuration checks current user, workspace, ownership and management permission in the actual read/write transaction. IDs and timestamps come from the server; duplicate or mismatched records fail explicitly, and project restrictions preserve the requested project. `allowed_memory_types` consistently means Memory content types such as finding or decision, filtered before candidate budgets. Restricted legacy bindings with missing/null `type_policy_version` require an authorized PUT after reviewing their types; the server saves version 1. Empty type lists retain existing authorization. See [ADR 0040](docs/adr/0040-current-authority-agent-memory-binding.md) and [ADR 0044](docs/adr/0044-consistent-agent-memory-content-types.md).

Local nonstream SDK intent/planning, requirement/problem-graph refinement, synthesis and review now apply complete-request budgets and current Run/actor/deadline checks after model capacity waits. Planning and execution have separate allowed phases. Admission refusals terminate with specific safe codes, without format repair or a DeepSearch digest/report. Standard synthesis also repeats existing Source identity checks at handoff. The request wrapper owns its asynchronous gate, including cancellation and compaction; cumulative cost, general Source versions and remote Runner delivery remain unfinished. See [ADR 0045](docs/adr/0045-bounded-nonstream-sdk-model-handoffs.md).

Market matching selects qualified private titles for each signal project with bounded SQL candidates and current source proofs. Every primary/fallback send and returned decision rechecks source authority and the matching claim; stale native chunks are withheld even when document versions were not bumped. Peer answers still require the existing consent workflow. See [ADR 0041](docs/adr/0041-current-project-market-scout-material.md).

Workspace also displays body-free candidate decisions for the owner's Run. Preparation does not count as use; an exact durable receipt proves delivery. Current permissions, sources, fact conflicts and procedure capabilities are rechecked before displaying titles. Forgetting clears candidate-only snapshots and tool payloads and fences late restoration. See [ADR 0032](docs/adr/0032-owned-memory-candidate-decisions.md).

Run the offline frozen inspection rule evaluation with `.venv/bin/python eval/run_automation_eval.py`. It uses isolated synthetic records and zero model calls; it is not a real-model quality score.

Replay 120 frozen memory controls with `.venv/bin/python eval/run_memory_eval.py`. It checks explicitly confirmed fixture facts, temporal updates, conflicts, current authority, withdrawal and database reopening in isolated stores. A separate generation example is excluded from the holdout. It makes zero model calls and reports extraction/answer quality as unmeasured; four real-model baselines and two-Run procedure traces remain pending.

Install and build the React frontend for FastAPI hosting:

```bash
cd agentmesh-demo
npm ci
npm run api:types
npm run build
cd ..
```

Start the app with production-safe defaults:

```bash
.venv/bin/uvicorn agentmesh.app:app --reload --port 8010
```

The default startup does not create demo users, fixed passwords, or demo content. This MVP supports one Workspace, one default Project, one application instance, and one SQLite database; do not expose it to the public internet.

For an internal pilot, set `AGENTMESH_PROFILE=pilot` to run the single governed path (SDK runtime, Memory inject, Task write). See `docs/runbooks/internal-pilot.md` and ADR 0053; the legacy chat runtime is deprecated.

For an isolated local demo database only, opt in explicitly:

```bash
AGENTMESH_DEMO_MODE=1 AGENTMESH_DB_PATH=data/agentmesh-demo.sqlite3 \
  .venv/bin/uvicorn agentmesh.app:app --reload --port 8010
```

Demo mode creates deterministic fixture accounts and content with known local-only credentials. Never enable it for a shared or production database.

Fixed research and `local_metrics` samples also require `AGENTMESH_DEMO_MODE=1`. Production queries without a real provider return a stable unavailable reason; empty or unverified evidence cannot complete a query. Uploaded documents remain usable as real local evidence. Query metadata and chat traces separate `data_mode` (`real`, `demo`, `derived`) from provider fallback mode, and the Workspace labels demo answers even when an LLM synthesizes them. Policy-rejected research dispatches persist a failed Task and an audit reason rather than completing with a sample.

Task Center mutations are fail-closed. The default `read_only` mode keeps the current board and details available without accepting project-task writes. Enable the approved Task, AgentRun, sealed Artifact, and Task Review mutation contracts explicitly in a local or controlled environment:

```bash
export AGENTMESH_TASK_MANAGEMENT=write
```

Linked Agent output can only use the dedicated Review path: the Run owner selects canonical sealed Artifacts, the server freezes their IDs and content hashes, creates a reviewer-specific Inbox item, and atomically moves the Task to review. The assigned reviewer can inspect only that frozen set through a review-scoped endpoint; this does not grant generic cross-user Run or Artifact access. `accepted` completes the Task; `changes_requested` and `rejected` return it to `in_progress`. Manual Tasks without linked Runs keep the manager-controlled delivery transition. Review decisions do not create or publish Memory.

After a Task Review is accepted, its Run owner may explicitly capture the frozen delivery as private Personal Memory or as a Team Candidate. Team Candidates require a separate `MemoryReviewV1` before becoming searchable Team Knowledge; the governance path works without external LLM, embedding, web, O2, MCP, or data providers.

Accepted Team Knowledge is immutable in place. Its owner or a user with effective `manage_team_memory` permission may submit a revision candidate; accepting that candidate atomically activates the new version and deprecates its predecessor. Lifecycle managers can dispute, deprecate, expire, archive, and restore governed versions through versioned command endpoints. Inactive versions remain auditable but are excluded from automatic Agent retrieval.

Automatic Task-linked and private Workspace AgentRun Memory context is separately gated and defaults to `off`:

```bash
export AGENTMESH_MEMORY_CONTEXT=observe  # retrieve and measure; do not inject or write use receipts
export AGENTMESH_MEMORY_CONTEXT=inject   # inject eligible Memory and persist MemoryUseReceiptV1
```

Only Task-linked Runs and private Workspace Runs (`project_chat=true`) are eligible for this automatic path. Only Memory that passes credential/prompt-injection quarantine and reaches the final model-context handoff receives an immutable use receipt. Explicit Runtime `memory_search` defers the receipt until its exact visible output passes encoding, size, safety, audit, and Tool settlement checks. Citation labels are transactionally reserved per Run so concurrent searches cannot assign one label to different Memory versions. Candidate, disputed, deprecated, expired, and archived versions remain excluded before retrieval ranking and budgets in every mode; the complete rendered context, including citation and Source metadata, is budgeted.

Completed direct Skills that declare `private_short_term` and completed Standard Skill Plans containing such Skills project exactly one private short-term Memory per Run. Ordinary Workspace conversations remain policy-skipped, but their owner can explicitly save a completed or partial result through the Workspace action; this never publishes Team Knowledge. Task-derived Team Knowledge continues to require accepted Task Review, explicit capture, and independent Memory Review.

Project operations build on the same Task facts. Project managers can define parent and dependency relationships; the server rejects cross-project targets and graph cycles, and incomplete dependencies prevent both the `start` transition and new Task-linked AgentRun claims. `GET /api/task-operations/{project_id}` serves the project overview, milestone progress, calendar, and Agent queue; `GET /api/task-operations/{project_id}/task-options` serves bounded relationship choices. These are read models, not an automatic scheduler. The SQLite `task_operations_projection` is rebuilt from canonical Task and Thread records at startup and can be dropped without losing project facts.

Port `8000` is intentionally avoided because it may already be used by another local backend.
If `8010` is already in use, first check whether AgentMesh is already running:

```bash
lsof -nP -iTCP:8010 -sTCP:LISTEN
curl http://127.0.0.1:8010/api/health
```

If the listener is an old AgentMesh process, stop that process before starting a new reloader:

```bash
kill <PID>
```

Or start this instance on another port:

```bash
.venv/bin/uvicorn agentmesh.app:app --reload --port 8011
```

Open:

```text
http://127.0.0.1:8010/
```

The app UI shows a local login panel when no session exists. In explicit demo mode, use the fixture-account controls shown by the local UI; production-safe mode has no built-in account credentials.

For frontend development, keep FastAPI on port `8010` and run `npm run dev` in `agentmesh-demo/`; Vite serves `http://127.0.0.1:5178/` and proxies `/api` to FastAPI. The retired single-file UI remains temporarily available at `/legacy/app.html` and `/app.html` for one release cycle.

### Local Runner execution (experimental)

The current local-Runner slice supports device enrollment, credential storage, heartbeat, lease renewal, cancellation, `standard_direct` execution, and read-only Standard Skill node execution. The control plane still owns plan creation, DAG state transitions, and final synthesis. DeepSearch and Runner-side Tool approval remain unavailable while Runner execution mode is selected.

New CLI Runners negotiate structured direct Sessions through `structured-session-v1`. They receive the existing Session's complete user/assistant and tool call/result items, compact history against the full request budget when needed, and return actual SDK continuation items in a versioned completion. Cloud completion checks the frozen snapshot and current version/authority in the same transaction as settling the Run. Duplicate completions and a reopened local spool reuse the prior execution result; restart `agentmesh runner start` to resend a pending completion while its lease remains valid. Older clients retain the V1 envelope. Both versions and Standard nodes check complete SDK request budgets; see [ADR 0064](docs/adr/0064-structured-runner-session-round-trip.md).

Current CLI Runners also negotiate `context-handoff-v1` for V3 direct and Standard node envelopes. Automatic Memory and core preferences remain prepared until execution: each model request obtains live cloud authorization, and Memory usage is recorded only after the model returns a response and the cloud accepts delivery. Confirmation persists before sending; restart resends confirmation before completion without rerunning the model. Successful completion rechecks current context and requires confirmed delivery. Remote model requests reserve against the same durable Run budget as cloud SDK work, including compaction and retries. Valid input/output usage settles the original reservation; unknown calls retain it, and late usage cannot restore cancelled context. Fees require explicitly configured prices. Native file tools additionally require `tool-handoff-v1`, current authorization and shared Run tool quota before IO. New claims freeze the selected profile and the first declared actual model identity. Clients without the tool protocol receive no native file tools. Unfinished-run recovery remains in development; see [ADR 0065](docs/adr/0065-runner-context-handoff-and-delivery.md).

Start the control plane without a server-side dispatch pump:

```bash
AGENTMESH_AGENT_RUNTIME=v2 AGENTMESH_EXECUTION_LOCATION=runner \
  .venv/bin/uvicorn agentmesh.app:app --reload --port 8010
```

Enroll the current terminal:

```bash
agentmesh setup --server http://127.0.0.1:8010
```

The CLI opens the authenticated Runner confirmation page. Configure the model Provider in the Runner process environment, then start local execution:

```bash
export AI_API_URL=https://your-openai-compatible-provider.example/v1/chat/completions
export AI_API_KEY=your-local-key
export AI_MODEL=your-model
# Optional: make the explicitly granted local_file_read tool available inside these roots.
export AGENTMESH_RUNNER_ALLOWED_ROOTS=/absolute/path/to/approved/projects
agentmesh runner start
```

`local_file_read` is not granted by default. Enable it explicitly for the user's Personal Agent from Agent configuration; the Runner still restricts reads to `AGENTMESH_RUNNER_ALLOWED_ROOTS`, resolves symlinks, rejects path escape, caps files at 100 KiB, and withholds credential-like content.

Use `agentmesh runner doctor` to inspect local protocol and credential readiness. The Runner token is stored through the operating-system keyring and is never written to `config.toml`.

### Skill Matrix orchestration

Multi-Skill orchestration is disabled by default and requires Agent Runtime v2 plus a configured model and Wiki corpus:

```bash
export AGENTMESH_AGENT_RUNTIME=v2
export AGENTMESH_WIKI_ROOT=/absolute/path/to/approved/wiki
export AGENTMESH_SKILL_ORCHESTRATION=preview
export AGENTMESH_TASK_SCENARIO_ROUTING=true
```

The server is the only configuration authority; the React app reads the effective mode from `/api/bootstrap` and does not use a Vite feature flag.

The builtin catalog contains 84 unique 2C-DesignWiki Skills, grouped into 17 pre-design, 26 during-design, and 41 post-design capabilities. Ten governed Pilot Skills remain eligible for the unchanged legacy automatic-planning path. Phase 1B local authoring now provides versioned Profile sidecars for all 84 Skills: the 74 generated imports are explicit `review_state=draft`, `planner_eligible=false`, while the ten legacy Pilot Profiles retain their existing execution fields. The draft Profiles are offline-only, cannot enter public recommendations or Agent Runs, and grant no production trust. Of the 84 catalog entries, 57 have current runtime adapter paths and 27 are marked `tool_limited` from their declared host tools; conservative draft Profiles may declare additional unavailable dependencies so future Universal readiness fails closed. Catalog and explicit-command integration does not imply that external tools have been granted or implemented. The UI keeps Skills discoverable and explicitly startable, but labels unavailable adapters accordingly; runtime Tool Grant and approval checks remain authoritative. With Agent Runtime v2 enabled, `/api/chat/skills` exposes those 84 Skills plus the 11 Legacy commands (95 entries total). Refresh or verify the vendored snapshot with:

```bash
.venv/bin/python scripts/sync_wiki_skills.py
.venv/bin/python scripts/sync_wiki_skills.py --check
# Optional authoring scaffold; creates missing draft sidecars and never overwrites existing ones.
.venv/bin/python scripts/sync_wiki_skills.py --generate-profile-stubs
```

| Mode | Natural-language request | Explicit `$skill` | Existing Legacy `$group.command` |
| --- | --- | --- | --- |
| `off` | Existing single Runtime v2 path | Single Skill Runtime v2 | Legacy chat path |
| `preview` | Recommend and persist a plan; confirmation never executes its DAG | Single Skill Runtime v2 | Legacy chat path |
| `execute` | Confirmed plans execute a bounded DAG | Single Skill Runtime v2 | Legacy chat path |

Legacy plans with two or more domain Skills still stop at the Plan Approval gate. Task/Scenario plans with high or medium confidence and only read/draft effects continue automatically in `execute` mode; `preview`, high-risk decisions, and write effects still pause. Confirming a plan does not approve a Tool call: approved external tools use a separate node-level approval, without repeating approval for internal Provider subcalls. The parent Run is the durable control record; refresh or SSE reconnect reads the same Run and Plan instead of starting work again.

Roll out in order: `off` → `preview` → `execute`. Setting `off` is the final restart state, not by itself a safe online rollback. Production rollback must first fence ingress, quiesce the live process, stop the only SQLite writer, run the checksum-bound offline inventory and backup/restore checks, and then restart a forward-compatible binary with:

```bash
export AGENTMESH_SKILL_ORCHESTRATION=off
```

Follow the [Universal Skill orchestration release and rollback runbook](docs/runbooks/universal-skill-orchestration.md). Open Tool approvals remain stopped after rollback and are never auto-resumed.

The orchestration API surface is:

- `POST /api/skills/recommendations`
- `POST /api/skills/routing-preview`
- `POST /api/agent/runs`
- `GET|PATCH /api/agent/runs/{run_id}/plan`
- `POST /api/agent/runs/{run_id}/plan/approve`
- `POST /api/agent/runs/{run_id}/plan/reject`
- `POST /api/agent/runs/{run_id}/retry`
- `POST /api/agent/runs/{run_id}/cancel`
- `GET /api/agent/runs/{run_id}/events`
- `GET /api/agent/runs/{run_id}/events/stream`

Run the deterministic release gates before moving beyond `preview`:

```bash
.venv/bin/python eval/run_skill_retrieval_eval.py
.venv/bin/python eval/run_universal_skill_retrieval_eval.py
.venv/bin/python eval/run_universal_skill_profile_smoke.py --mode fts-only
# Offline rollback preflight; --apply additionally requires the printed checksum,
# a separate integrity-checked backup path, a durable receipt path, and a
# two-operator approval file.
.venv/bin/python scripts/quiesce_skill_orchestration.py --database data/agentmesh.sqlite3
.venv/bin/python scripts/skill_catalog_report.py agentmesh/builtin_skills
.venv/bin/python scripts/run_project_operations_benchmark.py --output /tmp/project-operations-benchmark.json
.venv/bin/python -m pytest
.venv/bin/ruff check agentmesh tests scripts eval
npm --prefix agentmesh-demo test -- --run
npm --prefix agentmesh-demo run api:types
npm --prefix agentmesh-demo run build
npm --prefix agentmesh-demo run test:e2e
```

### Research workflow retirement

Research-v2 is retired: no Runtime or mutation path remains, while owner-scoped historical Runs and Artifacts stay readable through a read-only adapter. Client-turn replay may return an existing v2 Run but cannot restart it.

Research-v3 was retired before production launch. Its preview entry points, dedicated catalog and Workbench were removed; residual additive SQLite tables are inert and are not an activation mechanism. New full-report work uses explicit DeepSearch on the existing v1 Skill DAG. See [ADR 0008](docs/adr/0008-retire-research-v3-preview.md) and the [DeepSearch v1 plan](docs/plans/2026-08-26-deepsearch-v1-development-plan.md).

### DeepSearch v1

DeepSearch is implemented behind a default-off release gate. A client must explicitly send `planning_mode="deepsearch"`; the server never infers it from prompt wording and never falls back to ordinary chat. New runs require `AGENTMESH_AGENT_RUNTIME=v2`, `AGENTMESH_SKILL_ORCHESTRATION=execute`, `AGENTMESH_DEEPSEARCH_ENABLED=true`, an available model, and a real healthy `web_research` adapter. The v1 evidence path rejects other built-in tools and MCP. Skill resources remain readable only from the approved frozen manifest, are budgeted, and cannot become report Evidence.

The DeepSearch-specific API surface is:

- `GET /api/agent/runs/{run_id}/deepsearch`
- `POST /api/agent/runs/{run_id}/deepsearch/clarify`
- shared Plan edit/approve/reject, cancel, retry, event, and Artifact endpoints listed above

Keep the feature flag disabled until the real Provider smoke described below succeeds.

### Reference UI and data provenance

The `feature/reference-ui-mt-data` branch restores the visual hierarchy of the reference Mock frontend for DigitalSelf, Knowledge, Collaboration, and Insights while keeping FastAPI and SQLite as the authority for identity, permissions, state, versions, and mutations.

User-facing provenance labels are intentionally short:

- `T数据`: data returned by the current backend for the signed-in user's visible scope.
- `M数据`: reference Mock data, fixed display constants, or explicit demo seed data.

Mixed modules label Mock-derived fields separately. Mock-only sections never expose a successful local mutation; unavailable actions are disabled or described as not connected. The AI Workspace message, history, upload, search, `$` Skill, trace, and memory-search paths are outside this page-alignment scope.

Manual acceptance for this branch is documented in `docs/superpowers/plans/2026-08-14-reference-ui-mt-data-human-acceptance.md`.

### Deployment boundaries

This internal-pilot MVP supports one Workspace, one application process, and one SQLite database. Run it only on a trusted internal network. Multi-workspace tenancy, multi-process SQLite coordination, horizontal scaling, high availability, and public-internet hardening are Post-MVP work.

Before an internal release, run the real read-only Provider gate from a host with approved credentials and CLIs:

```bash
.venv/bin/python scripts/provider_smoke.py --embedding --o2 --web --data --llm
```

The command prints only redacted provider readiness, mode, latency, and stable error categories. A release is blocked unless all five providers report `ready=true` and `mode=real`.

## Test

```bash
.venv/bin/python -m pytest
.venv/bin/python -m eval.run_closed_loop_eval --mode validate --batch D0
.venv/bin/python -m eval.run_closed_loop_eval --mode deterministic --batch D1 --output data/eval/closed-loop
```

D0 validates the frozen 24-task/96-case dataset. D1 executes all 96 cases with isolated SQLite databases, blocked network access, and `ScriptedModel`; it never calls a real Provider or consumes billable model tokens.

R1 is manual and billable. It is forbidden in CI and requires an explicit acknowledgement and budget:

```bash
.venv/bin/python -m eval.run_closed_loop_eval \
  --mode real --batch R1 \
  --max-runs 24 --max-total-tokens 500000 \
  --initial-token-reserve 40000 \
  --ack-real-provider --env-file .env \
  --output data/eval/closed-loop-r1

.venv/bin/python -m eval.run_closed_loop_eval \
  --mode real --batch R2 \
  --max-runs 24 --max-total-tokens 250000 \
  --initial-token-reserve 0 \
  --ack-real-provider --env-file .env \
  --output data/eval/closed-loop-r2
```

Tests use an isolated SQLite database under the system temp directory, so they do not clear `data/agentmesh.sqlite3`.
The pytest bootstrap also clears default LLM environment variables so unit tests stay deterministic and do not call the real model service unless a test explicitly configures a mocked model endpoint.

## Local Data

The prototype uses SQLite by default:

```text
data/agentmesh.sqlite3
```

Override it with:

```bash
AGENTMESH_DB_PATH=/path/to/agentmesh.sqlite3 .venv/bin/uvicorn agentmesh.app:app --port 8010
```

Embedding is disabled by default and search remains FTS-only. To enable vector search, set `AGENTMESH_EMBEDDING_ENABLED=true`, `AGENTMESH_EMBEDDING_API_URL`, and `AGENTMESH_EMBEDDING_API_KEY` in the server environment. Inject the key through your deployment secret manager; do not commit or log it.

## Auth and Permissions

AgentMesh uses a minimal local auth and user-management layer for the current MVP slice:

- `POST /api/auth/login` creates an HttpOnly cookie session.
- `GET /api/auth/oauth/status` reports whether OAuth is configured without exposing secrets.
- `GET /api/auth/oauth/start` redirects to the configured corporate OAuth provider.
- `GET /api/auth/oauth/callback` exchanges an OAuth code, maps userinfo to a local user, and reuses the same HttpOnly cookie session.
- `POST /api/auth/logout` revokes the session.
- `GET /api/auth/me` returns the current user.
- `POST /api/auth/password` lets the current user rotate their password and revokes existing sessions.
- Demo users are seeded only when `AGENTMESH_DEMO_MODE=1`; production-safe startup creates no built-in credentials.
- Admins can create local users with initial passwords.
- Admins can reset local user passwords and revoke existing sessions.
- Creating a local user also creates that user's personal Agent.
- Admins can disable users; disabled users cannot log in or continue an existing session.
- Regular users can manage only their own personal Agent.
- Team leads and admins can accept candidate memories into team scope.
- Admins can manage public Agents.
- Admins can create workspaces and projects.
- Permission policy rules are persisted and admin-managed through:
  - `GET /api/users/permission-policies`
  - `POST /api/users/permission-policies` admin only
  - `PATCH /api/users/permission-policies/{rule_id}` admin only
- The MVP policy table currently controls role-level allow/deny overrides for sensitive actions such as `accept_team_memory` and `manage_public_agent`.

OAuth is implemented as an adapter framework. A real enterprise SSO rollout still needs provider URLs, client ID, client secret, redirect URI registration, and user/role mapping confirmation.

Enable OAuth:

```bash
export AGENTMESH_OAUTH_ENABLED=true
export AGENTMESH_OAUTH_AUTHORIZE_URL=https://sso.example.com/oauth/authorize
export AGENTMESH_OAUTH_TOKEN_URL=https://sso.example.com/oauth/token
export AGENTMESH_OAUTH_USERINFO_URL=https://sso.example.com/oauth/userinfo
export AGENTMESH_OAUTH_CLIENT_ID=agentmesh
export AGENTMESH_OAUTH_CLIENT_SECRET=your-server-side-secret
export AGENTMESH_OAUTH_REDIRECT_URI=http://127.0.0.1:8010/api/auth/oauth/callback
```

Do not commit `AGENTMESH_OAUTH_CLIENT_SECRET`. Users created through OAuth receive a personal Agent automatically and default to `AGENTMESH_OAUTH_DEFAULT_ROLE`.

## Agents and Tools

Public Agents are registered by backend code first, then exposed through API:

- `GET /api/agents/public`
- `GET /api/tools`
- `GET /api/agents/{agent_id}/tools`
- `PATCH /api/agents/{agent_id}/tools`

Tools are explicitly granted to Agents. Some tools now have MVP execution paths (`document_upload`, local data queries, risk rules, and configurable web research), but web research still requires a provider to be configured.

A user-managed local Zero MCP service can be connected through the governed read-only example at `config/zero-mcp.readonly.example.json`. It exposes only the six verified read capabilities mapped by imported Skill aliases and grants nothing automatically. See [Zero MCP read-only integration](docs/runbooks/zero-mcp-readonly.md).

## Oxygen-CLI Internal Provider

Oxygen-CLI is treated as an internal company capability provider, not the only data source. AgentMesh keeps external Web providers, uploaded documents, local memory, and future BI/database connectors as separate sources.

Status and tool discovery APIs:

- `GET /api/integrations/o2/status`
- `POST /api/integrations/o2/sync` admin only

The sync endpoint reads Oxygen registry metadata and stores discovered CLI capabilities as `ToolDefinition` records with `provider=o2`. It does not automatically grant those tools to every Agent; existing Agent tool grants still apply.

Enable Oxygen-backed internal research:

```bash
export AGENTMESH_O2_RESEARCH_ENABLED=true
export AGENTMESH_O2_RESEARCH_CLI=metasearch
```

Enable Oxygen-backed data queries:

```bash
export AGENTMESH_O2_DATA_ENABLED=true
export AGENTMESH_O2_DATA_CLI=metasearch
```

Built-in Oxygen command contracts (verified against the working DesignOS connector):

AgentMesh prefers the standalone sub-CLI binary when it is on `PATH` and falls back to the `o2 launch <cli>` main entry only when no standalone binary is found. Authentication is handled by each CLI's own login state on the host machine; AgentMesh does not inject an access token via an environment variable.

- Research through `metasearch`:
  - Standalone (preferred): `oxygen-metasearch --json search --output json --endpoint <AGENTMESH_O2_METASEARCH_ENDPOINT> <query>`
  - `o2` fallback: `o2 launch metasearch search <query> --endpoint <AGENTMESH_O2_METASEARCH_ENDPOINT> --output json`
  - The endpoint defaults to `https://agentkits-a2a-gateway.jd.com/agents/sku-search`.
- Research through `o2-kb`:
  - Standalone (preferred): `o2-kb recall list --json <query>`
  - `o2` fallback: `o2 launch o2-kb recall list <query> --json`
  - Optional `AGENTMESH_O2_KB_RECALL_TOKEN` and `AGENTMESH_O2_KB_FOLDER_TO_APP` are appended only when set.
- Data through `metasearch`: same read-only search contract as research.
- Data through `oxygen-comment`:
  - Standalone (preferred): `oxygen-comment comment list --json --page-size <limit> [--sku-name <q> | --sku-ids <ids> | ...]`
  - `o2` fallback: `o2 launch oxygen-comment --json comment list --page-size <limit> ...`
- Data through `bdp-copilot`: `o2 launch bdp-copilot --json-output find-tables <query>`

Override the metasearch gateway endpoint with:

```bash
export AGENTMESH_O2_METASEARCH_ENDPOINT=https://agentkits-a2a-gateway.jd.com/agents/sku-search
```

If an approved CLI uses a different shape, override it with:

```bash
export AGENTMESH_O2_RESEARCH_COMMAND_TEMPLATE='launch {cli} search {query} --limit {limit} --json'
export AGENTMESH_O2_DATA_COMMAND_TEMPLATE='launch {cli} {operation} {query} --limit {limit} --json'
```

The Oxygen data connector is read-only in this slice. Write actions such as upload, edit, delete, install, and batch operations should be routed through Inbox/Risk review before execution.

Known runtime prerequisites:

- The standalone sub-CLIs (`oxygen-metasearch`, `o2-kb`, `oxygen-comment`) must be installed and logged in on the host where AgentMesh runs. Auth is not injected by AgentMesh.
- `o2-kb` must be initialized by `o2-kb init` before its recall/config commands work.
- `webcli`/browser-backed CLIs need the Browser Bridge daemon and extension connected.
- `bdp-copilot` execution still depends on the user's internal runtime and auth context.

## LLM Configuration

AgentMesh reads model services from environment variables. The legacy single-model configuration still works as the `default` model:

```bash
export AI_API_URL=https://modelservice.jdcloud.com/v1/responses
export AI_MODEL=Gemini-3-Flash-Preview
export AI_API_KEY=your-api-key
```

If you prefer the older chat-completions layout, keep using:

```bash
export AGENTMESH_LLM_BASE_URL=https://modelservice.jdcloud.com/v1/
export AGENTMESH_LLM_MODEL=GPT-5.5
export AGENTMESH_LLM_API_KEY=your-api-key
.venv/bin/uvicorn agentmesh.app:app --port 8010
```

Chat and orchestrated research Skills use separate timeout budgets; the parent orchestrated Run keeps its 300-second deadline:

```bash
export AGENTMESH_CHAT_LLM_TIMEOUT_SECONDS=120
export AGENTMESH_RESEARCH_SKILL_TIMEOUT_SECONDS=180
export AGENTMESH_SKILL_MATCH_LLM_TIMEOUT_SECONDS=8
export AGENTMESH_LLM_TIMEOUT_SECONDS=30
export AGENTMESH_LLM_CONNECT_TIMEOUT_SECONDS=5
```

Skill matching uses its shorter budget only for ambiguous or explicitly multi-deliverable requests that need semantic
reranking. If a model call times out,
AgentMesh returns the deterministic local match and a stable diagnostic instead of failing the request. If the chat model
times out, AgentMesh returns the deterministic local answer and records the reason in `workflow_trace.model_fallback_reason`.

Additional selectable models use `AGENTMESH_MODELS` plus per-model variables:

```bash
export AGENTMESH_MODEL_DEFAULT=default
export AGENTMESH_MODELS=gpt52,gpt54,gpt55

export AGENTMESH_MODEL_GPT52_BASE_URL=http://internal-llm-gateway/v1
export AGENTMESH_MODEL_GPT52_MODEL=GPT-5.2-joybuilder
export AGENTMESH_MODEL_GPT52_LABEL="GPT-5.2 JoyBuilder"
export AGENTMESH_MODEL_GPT52_API_KEY=your-api-key
export AGENTMESH_MODEL_GPT52_API_STYLE=chat_completions

# Repeat the same five variables for GPT54 and GPT55.
# The complete secret-free template is in .env.example.
```

`AGENTMESH_MODEL_DEFAULT=default` keeps the `AI_API_*` model as the default while exposing the three named GPT models in the Agent model selector. JoyBuilder currently accepts JSON mode but rejects OpenAI Native Structured Outputs, so configure `AGENTMESH_SDK_STRUCTURED_OUTPUT_MODE=json_object`. Providers that implement `response_format=json_schema` can keep the default `json_schema`; mixed deployments can override one named model with `AGENTMESH_MODEL_<ID>_STRUCTURED_OUTPUT_MODE`. JSON-object mode injects the same schema into the system instructions and still validates the final value locally with the SDK and Pydantic.

Gateways that reject strict function declarations can separately set `AGENTMESH_SDK_STRICT_TOOLS=false`; this does not change structured-output validation, and AgentMesh still validates arguments locally through Pydantic and tool guardrails.

Configure one optional automatic fallback model with:

```bash
export AGENTMESH_LLM_FALLBACK_MODEL_ID=fast
```

The UI stores only `model_id` on the Agent. API keys stay server-side and are never returned by `/api/models`. Eligible primary failures (`timeout`, request/HTTP errors, malformed or empty responses) try the configured fallback once; authentication failures remain explicit. Persisted traces expose requested/actual model and model fallback reason separately from acquisition Provider provenance.

## Acquisition Agent Boundary

AgentMesh keeps external acquisition as an interface boundary:

- `AcquisitionRequest` describes what the personal Agent needs.
- `AcquisitionResult` returns evidence, sources, actor, permission, and metadata.
- `MockAcquisitionAgent` supplies labelled samples only in explicit demo mode; production requires a real provider or matching uploaded documents.
- `WebAcquisitionAgent` can call a configured Web provider.
- `ExternalAcquisitionConnector` remains a placeholder for an implementation supplied by another project.
- External content is treated as untrusted input. Suspicious prompt-injection text is saved for audit, marked `needs_review`, routed to Inbox, and excluded from LLM synthesis.
- High-risk tool requests such as batch crawling, batch downloads, intranet access, or automatic team-memory writes are routed to Inbox for approval before any acquisition connector runs.

To enable the native Tavily Web provider:

```bash
export AGENTMESH_WEB_PROVIDER=tavily
export AGENTMESH_TAVILY_API_URL=https://api.tavily.com/search
export AGENTMESH_TAVILY_API_KEY=your-api-key
export AGENTMESH_TAVILY_TIMEOUT_SECONDS=20
```

The Tavily connector sends a basic search request, returns only title/URL/content snippets, and never returns its key or provider response body. To enrich the selected Tavily results with page body text through Firecrawl's REST API, enable the optional scraper:

```bash
export AGENTMESH_FIRECRAWL_ENABLED=true
export AGENTMESH_FIRECRAWL_API_URL=https://api.firecrawl.dev/v2/scrape
export AGENTMESH_FIRECRAWL_API_KEY=your-api-key
export AGENTMESH_FIRECRAWL_TIMEOUT_SECONDS=60
export AGENTMESH_FIRECRAWL_MAX_PAGES=6
export AGENTMESH_FIRECRAWL_MAX_CONTENT_CHARS=4000
```

Tavily remains the discovery provider. Firecrawl can enrich selected results with bounded page text; failed enrichment falls back to the original Tavily snippet and is recorded in Provider metadata. For a trusted self-hosted Firecrawl endpoint, set `AGENTMESH_FIRECRAWL_API_URL` to its `/v2/scrape` URL; an API key is optional outside `*.firecrawl.dev`. Never expose an unauthenticated self-hosted endpoint publicly.

Command-backed providers remain available as alternatives.

To enable command-backed Web research instead:

```bash
export AGENTMESH_WEB_PROVIDER=opencli
export AGENTMESH_OPENCLI_COMMAND=opencli
export AGENTMESH_OPENCLI_COMMAND_TEMPLATE='opencli search {query} --limit {limit} --json'
```

or:

```bash
export AGENTMESH_WEB_PROVIDER=agent_browser
export AGENTMESH_AGENT_BROWSER_COMMAND=agent-browser
export AGENTMESH_AGENT_BROWSER_COMMAND_TEMPLATE='agent-browser search {query} --limit {limit} --json'
```

Without a command template, the provider runs `COMMAND query --limit N --json`. Templates support `{query}` and `{limit}` placeholders. The command should return JSON as an array, or an object with `items`, `results`, or `data`, containing `title`/`name`, `url`/`href`/`link`, and `snippet`/`content`/`summary`.

## Document Ingestion Boundary

Document ingestion is also kept as a thin boundary:

- `DocumentIngestionRequest` carries file metadata, bytes, workspace, project, and uploader.
- `ParsedDocument` returns normalized text plus a document `Source`.
- `CompositeDocumentParser` routes `.txt`, `.md`, `.markdown`, `.pdf`, `.docx`, `.pptx`, and common image files to built-in parsers.
- PDF parsing uses PyMuPDF when available through the project dependencies.
- Word and slide parsing extract OOXML text from `.docx` and `.pptx`.
- Image OCR uses a configured `tesseract` command; without that runtime, image uploads fail with an explicit parser error.
- `POST /api/documents/upload` stores parsed documents, creates Sources, and writes a short-term document-summary memory item.
- Files larger than the sync threshold are parsed through a `DocumentParseJob` background task and can be checked with `/api/documents/jobs/{job_id}`.
- New uploads retain hash-checked private original input for up to seven days, claim a durable lease, and atomically commit the Source/document/private memories and completed Job. Startup resumes queued/expired work; cache cleanup failure preserves successful results. Job lists are scoped/paginated and owned failed Jobs can be retried with `POST /api/documents/jobs/{id}/retry` using version/command identity, up to three attempts. Knowledge exposes upload/status/retry. Old incomplete Jobs without input proof require re-upload; partial legacy imports require review. See ADR 0035 for durable imports and ADR 0038 for manual edits/reimports.
- Production uploads use an owned POSIX parser process (ADR 0046), with a private temporary input, a minimal environment, a 90-second deadline, CPU/file/descriptor limits, and process-tree RSS monitoring. Shutdown or failed claim renewal cancels parsing; the parser and OCR process group are killed and reaped, while the durable original remains available for an authorized retry. PDF pages, OOXML expansion/DTD, parsed text and JSON results have explicit limits. This provides process/resource containment; filesystem/network permissions still require a deployment policy. macOS tests cover actual workers and a controlled OCR adapter; Linux container execution and real OCR quality are not yet verified.
- Ordinary local SDK synthesis (ADR 0047) checks persisted citation metadata, freezes the current Source record identity, and repeats source/owner checks at actual model handoff and after synthesis returns. Changed references or revoked execution authority yield a safe failure without delivering the new synthesis. Source identity creation is serialized in one SQLite transaction; conflicting concurrent creation cannot overwrite an earlier identity. The frozen identity describes the local citation record; external content versions/hashes and persistent source snapshots remain in development.
- Ordinary/Universal finalization (ADR 0048) now repeats current authority, deadline, writer/plan/input and Source checks in the actual terminal write transaction. Universal synthesis Artifacts, Plan/Run state and events commit or roll back together. Admission refusals cannot become partial output, and an old execution cannot fail a newer writer or plan version. This closes the synthesis-return/terminal-commit window; output authority is covered by ADR 0049, while generic origin invalidation and remote source delivery remain separate work.
- Terminal chat/private-Memory projection (ADR 0049) rechecks current actor/project/thread access and the expected Run writer/content inside its existing atomic write. Automatic Memory uses current Skill policy; explicit saving rejects outputs changed after HTTP validation. Projection preserves an existing manual save and respects forgetting tombstones. Session sync markers cannot acquire foreign or unproven bodies or overwrite another writer. Recovery remains idempotent; persistent Source/input proof and remote SDK delivery are still pending.
- Direct SDK completion/pause and approval recovery (ADR 0050) fence the original execution identity inside state commits. Completion repeats current Session authority/deadline checks; pause verifies its checkpoint before creating approval state. Old errors/cancellations cannot terminate a replacement writer. Terminal state, Inbox closure and event commit together, while explicit user cancellation still targets the current Run. Local producer cancellation is covered by ADR 0051; persistent leases and cumulative budgets remain pending.
- SDK stream completion (ADR 0051) now confirms the public producer task after event draining, so cancelled model work cannot become empty successful output. A cancelled DAG child stops its parent and siblings, releases capacity and preserves unknown external outcomes. Cancellation commits fence the original writer/Plan; shared transient Run identity now includes Runner identity. Full budgets, durable leases and remote delivery remain pending.
- Approved local node execution (ADR 0052) carries the original Run and Plan through claims, result commits, approval pauses/resumes and internal cancellation. Transient execution hashes freeze Plan inputs and node definitions while existing CAS checks allow normal state/attempt progress. Queued claims and post-commit continuation cannot adopt a replacement writer; legitimate committed results remain reusable. Planning leases, cumulative budgets and remote delivery remain pending.
- Ordinary local SDK requests (ADR 0053) and newly authorized V3 Runner requests (ADR 0065) share a durable Run model budget across planning, nodes, approval recovery, synthesis and Session compaction. Defaults cap 32 calls, 256k accounted tokens, 65,536 output tokens and three identical request attempts. Limits and configured prices freeze at first accounting. Concurrent remote authorization reserves atomically with its handoff; replay does not consume another call. Positive, internally consistent input/output usage settles to reported tokens; failed, cancelled, missing, legacy total-only or zero-default usage retains the conservative reservation. Known local admission refusal before the adapter call releases only that unsent reservation. The configured SDK model factory defaults HTTP retries to zero; SDK retries each consume a reservation. Native remote file tools share the Run tool counter; tool fees and unfinished-run recovery remain pending.
- Optional ordinary model cost estimates (ADR 0054) use a frozen server-declared price map keyed by actual model name. Set both cost currency and micro-unit cap to enable the gate; absent, expired or mismatched prices refuse calls. Without a cost gate, unavailable prices remain unknown. Integer per-request estimates retain unknown usage reservations, preserve actual overspend, and settle late receipts using original prices. They are not Provider invoices, do not combine currencies and do not price tools or background learning. Configuration and units are documented in `.env.example`.
- Ordinary local SDK tools (ADR 0055) reuse the same frozen policy and the existing Run counter. `AGENTMESH_RUN_MAX_TOOL_CALLS` can tighten the existing 24-attempt maximum. Admission checks the original Run, Plan and node attempt atomically; native tools, Skill resources and MCP repeat that proof and deadline checks after capacity waiting, before claiming an actual call. Stale Run saves and approval recovery cannot refund attempts. Governed MCP failures abort SDK execution and preserve typed admission codes. V3 native Runner file tools (ADR 0065) share this counter after live authorization; old clients receive no native file tools. This counts admitted attempts, excludes tool fees/background accounting, and leaves DeepSearch's ledger unchanged.
- Optional Source snapshots (ADR 0056) record external identity, opaque version, exact text hash and lifecycle on the existing Source. Current owner/project authority and CAS gate observations; retrieval, document evidence, learning and queued SDK Memory delivery withhold changed or unavailable origins. Selected sources join private publication dependencies; startup retracts older direct-source/document publications without that proof. Managed document mirrors are read-only locally. Legacy hashes are preserved; native upload snapshots and complete remote/derived-origin invalidation remain unfinished.
- Project connector APIs (ADRs 0057–0062) read configured repository documents and GitHub Issues into owned versioned mirrors. Each page claims a durable 90-second lease before external reading, including the first page. Exact claim/current authority checks fence completion; expired leases recover at startup/status/periodic reconciliation. Incremental pages freeze the since boundary; full scans withhold missing sources. Canonical-source checks verify current operator bindings. `AGENTMESH_CONNECTOR_WORKER_ENABLED=false` defaults off; each owner must separately enable a cursor's automatic sync. The worker continues pages, schedules completed cycles, limits transient retries to three attempts and persists provider waits shared by the same configured source. Knowledge supports automatic controls, waiting/progress, first-page cancellation and explicit mirror import. Direct HTTP abort, complete Provider ACL/deletion discovery and freshness remain in development.
- Market status/board/me/activity use the current authorized default project (ADR 0036). Explicit published scope and active membership precede SQL aggregation and bounded decoding; worker queues/errors are owned metadata. Recent graphs/timelines are projections, and verified private answers remain in the durable Query flow.
- Automatic signal publication (ADR 0037) requires current opt-in and qualified ordinary inputs, freezes authority/material and rechecks before send and atomic post/index/audit commit. Sensitive/structured/private peer-answer material is excluded. Opt-out and owned forgetting/withdrawal erase the generated public summary and its indexes. Market APIs accept an explicit authorized project and client caches keep projects separate. SDK budget/delivery governance and general origin invalidation remain in development.
- Manual document edits and reimports (ADR 0038) recheck current authority inside their atomic writes. Editing saves the new version and invalidates owned old native chunks/summary indexes together; import commits stable scoped Sources/chunks/indexes/progress once, with a selected-version check. Forgotten, archived or inconsistent chunks require review. Knowledge offers separate save/reimport controls; imported text still requires fact confirmation and independent team review.
- Generated signals now retain private selected-record dependencies (ADR 0039). Source or authority changes retract the old body and search projections inside the source write, including raw SQL paths and database reopen. Dependency triggers ignore identical, new and unselected Memory writes; explicit document/forgetting commands retain conservative aggregate withdrawal. Legacy generated aggregates without proof require fresh publication; private dependency IDs remain absent from public metadata. External Source propagation and full SDK governance continue separately.
- `ExternalDocumentParserConnector` remains only as an extension boundary for future richer parsers, not as the default path for the file types above.

Knowledge provides project/term fact queries for current, historical and interval time, with an optional observation cutoff. Results distinguish unknown, conflicting and insufficient evidence and link source Memory/documents. Current confirmed procedure details can carry their goal into a selected-project Task draft; saving and starting remain explicit actions. Task creation accepts an optional authorized project without changing legacy omitted-project command hashes. State questions can also reference a qualified method within the shared context allowance: current SQL retains priority and only the method creates a Memory receipt after both authorities are rechecked. These features reuse existing APIs and do not establish real-model quality or team adoption.

## Data Source Connector Boundary

Manual document/Issue sync is configured with `AGENTMESH_CONNECTOR_PROJECT_ID`,
`AGENTMESH_REPO_DOCS_ROOT` and/or `AGENTMESH_GITHUB_REPOSITORY` (`owner/repository`).
These bindings are disabled while empty. Public GitHub repositories require no token;
private repositories use server-only `AGENTMESH_GITHUB_TOKEN` and an explicit
`AGENTMESH_GITHUB_CREDENTIAL_VERSION` that changes with the credential's principal/permission binding.

Read `GET /api/projects/{project_id}/connectors`, then submit
`POST /api/projects/{project_id}/connectors/{provider}/sync` with `{"expected_version": 0}`
for a new cursor, or the returned cursor version for subsequent pages. Supported providers
are `repo_docs` and `github_issues`. Paths, API URLs and credentials are not HTTP request fields.
Each call reads one bounded page; a completed cursor starts a new scan on the next call.
The page attempt increments the cursor version when claimed, before external reading; terminal settlement
uses that version and its exact private claim identity. Status reads expose `reading` while the attempt holds
a 90-second lease. A live claim rejects overlapping sync; cancellation uses the latest status version.
Expired claims recover with a new version, retain the previous successful observation and allow a fresh read.
First-page claims are cancellable. Source/document/index and terminal cursor state still commit atomically.
The request defaults to `"mode": "incremental"`; use `"mode": "full"` for a complete review.
GitHub uses a fixed since boundary with a 60-second overlap; repository documents always scan fully.
The first scan and a sync invoked at least one day after the last full scan also scan fully.
Failures persist a new cursor version: refresh connector status before retrying. Access/root failures
withhold prior sources and restart a full scan on recovery; transient failures retain the last observation.
Only completed full scans mark unseen old sources unavailable. These are observations, not live Provider state.
Changed configuration returns a conflict until explicitly reset. Knowledge exposes versioned controls;
`POST /api/projects/{project_id}/connectors/{cursor_id}/control` accepts `expected_version`
and `action` (`disable`, `reset`, `cancel`). Disable/reset withhold old sources atomically;
reset adopts the current operator binding for the same provider/namespace and requires a fresh full scan.
Cancel retains prior observations and rejects late commits; already issued HTTP requests may still run until timeout.
Removed bindings remain listed so the owner can disable them. A changed repository namespace starts a new cursor;
the old binding becomes unavailable under current-source checks and is durably invalidated at startup or a status read.
Canonical connector sources require their exact owned cursor and active operator binding; credentials remain server-only.
Restoring an invalidated binding requires explicit reset and fresh full observation. This checks declared configuration,
not live Provider ACL on every citation; complete remote ACL/deletion discovery and freshness policy remain unfinished.
Synced mirrors use existing document APIs and explicit import/learning. No Task state changes are implied.

Data source integration is reserved as a generic connector contract:

- `DataSourceQuery` carries connector name, operation, free-form parameters, workspace, project, and requester.
- `DataSourceResult` returns generic records plus a `data_source` Source.
- `DataSourceRegistry` routes queries to registered connectors.
- `http_data_api` is a production-facing read-only HTTP connector enabled by `AGENTMESH_DATA_API_URL`.
- `data_agent` tries configured production data connectors before falling back to O2 and `local_metrics`.
- `local_metrics` supplies fixed demo samples to `POST /api/data-agent/query` only when `AGENTMESH_DEMO_MODE=1`.
- `ExternalDataSourceConnector` is a placeholder until a concrete external project provides the real data shape and access method.

Enable a real read-only data API:

```bash
export AGENTMESH_DATA_API_URL=https://your-company-data-api.example/api/data
export AGENTMESH_DATA_API_KEY=your-server-side-token
```

For a query operation such as `query`, AgentMesh POSTs to:

```text
{AGENTMESH_DATA_API_URL}/query
```

with JSON containing `operation`, `parameters`, `workspace_id`, `project_id`, and `requested_by`. The response may be an array, or an object with `records`, `items`, `results`, `data`, or `rows`. API keys stay server-side and are not returned by health or connector list endpoints.

## Workspace And Blackboard

Workspace and project records are persisted through the same SQLite store as the rest of the prototype:

- `GET /api/workspaces`
- `POST /api/workspaces` admin only
- `GET /api/projects`
- `POST /api/projects` admin only

Blackboard also has an auto-post queue for Agent background jobs:

- `GET /api/blackboard/auto-posts`
- `POST /api/blackboard/auto-posts`
- `POST /api/blackboard/auto-posts/drain`
- `GET /api/blackboard/auto-posts/worker`

Auto-post requests must be reviewed before drain publishes them into the BBS. A background worker is available but disabled by default; enable it with `AGENTMESH_AUTO_POST_WORKER_ENABLED=true` and configure the interval with `AGENTMESH_AUTO_POST_WORKER_INTERVAL_SECONDS`.

User memory daily summaries also have a disabled-by-default worker. Enable it in the production environment with `AGENTMESH_DAILY_MEMORY_WORKER_ENABLED=true`. The worker runs at 00:05 Asia/Shanghai, summarizes the previous calendar day, and performs one idempotent catch-up pass for yesterday on startup. It creates at most one `daily_summary` per active user/project/date and skips users without short-term source memory.

Project memory summaries use the configured LLM when available, then fall back to deterministic source rollups if the model is unavailable.
Project archives now include a recall-index section, and personal search can resolve the current user's layered memory items.
Uploaded documents are indexed for personal search, written to short-term document-summary memory, and can be used as chat evidence for relevant Brief/research requests.

## API Snapshot

- `POST /api/chat/messages`
- `POST /api/chat/threads`
- `GET /api/bootstrap`
- `GET /api/activity/today`
- `GET /api/audit?limit=50&action=...&target_type=...`
- `GET /api/inbox`
- `PATCH /api/inbox/{id}` with `status=open|snoozed|resolved`, optional `ttl_minutes`, or optional `snooze_until`
- `GET /api/memory`
- `GET /api/memory/user?layer=short_term|mid_term|long_term&project_id=...&memory_date=YYYY-MM-DD&memory_type=...`
- `POST /api/memory/user`
- `POST /api/memory/user/daily-summary`
- `POST /api/memory/user/group-summary`
- `GET /api/memory/user/daily-summary/worker` admin only
- `POST /api/memory/user/project-summary`
- `POST /api/memory/user/archive-project`
- `GET /api/users`
- `POST /api/users`
- `PATCH /api/users/{id}`
- `GET /api/search?q=关键词&workspace_id=...&project_id=...&visibility=personal`
- `GET /api/agents` with derived runtime status and current task fields
- `GET /api/blackboard`
- `GET /api/blackboard/task-cards`
- `POST /api/blackboard/posts`
- `PATCH /api/blackboard/posts/{id}/read`
- `POST /api/blackboard/posts/{id}/reply`
- `POST /api/blackboard/posts/{id}/handoff`
- `GET /api/blackboard/auto-posts`
- `POST /api/blackboard/auto-posts`
- `POST /api/blackboard/auto-posts/drain`
- `GET /api/blackboard/auto-posts/worker`
- `GET /api/workspaces`
- `POST /api/workspaces`
- `GET /api/projects`
- `POST /api/projects`
- `POST /api/auth/password`
- `POST /api/users/{id}/password`
- `POST /api/documents/upload`
- `GET /api/documents`
- `GET /api/data-sources`
- `POST /api/data-agent/query`
- `GET /api/integrations/o2/status`
- `POST /api/integrations/o2/sync`
- `GET /api/risk/policies`
- `POST /api/risk/policies`
- `PATCH /api/risk/policies/{id}`
