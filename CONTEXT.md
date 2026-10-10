# CONTEXT.md — Digital Twin × Agent Market

Glossary for the "digital twin / agent collaboration market" work. Each term maps to its
**code reality** as of 2026-08-26, so downstream work doesn't mistake the design doc's
aspiration for what is built. Source design: `docs/2026-08-08-数字分身-Agent协作市场-产品设计.md`.
MVP scope decisions: `docs/adr/0003-mvp-scope-answer-only-gateway.md`.

Legend: ✅ implemented · ⚠️ convention/partial · ❌ absent (design-only). Public UI/API reachability is stated separately; an internal model or method is not necessarily a user-reachable workflow.

## 前端术语约定 / Frontend terminology

当前默认前端是 `agentmesh-demo/`：React 18 + Vite + Tailwind + TanStack Query 的
TypeScript 单页应用，由 FastAPI 从 `agentmesh-demo/dist` 同源托管。`/` 与产品
deep link 均返回 React index；业务状态和权限以 FastAPI/SQLite 为唯一真相。

项目根目录的 `app.html` 是已退役的单文件 UI，在一个发布周期内通过临时 URL
`/legacy/app.html` 和 `/app.html` 保留为回滚入口。它不再是默认入口，也不再承载新功能。
完整替换设计见 `docs/superpowers/specs/2026-08-11-react-frontend-complete-replacement-design.md`。

参考 UI 混合展示分支 `feature/reference-ui-mt-data` 以下载目录 Mock 前端作为视觉基线，并使用 Presenter 组合真实查询与参考展示数据。页面中的 `T数据` 表示当前登录用户可访问的服务端数据，`M数据` 表示参考 Mock、固定页面常量或明确的演示 seed。Mock 只补展示，不得模拟权限、状态或 mutation 成功。DigitalSelf、Knowledge、Collaboration、Insights 已完成页面代码改造，等待真人验收后合并；AI 工作台业务逻辑是冻结边界。

运行边界：当前 MVP 仅支持单 Workspace、单应用进程和单 SQLite 数据库，并且只部署在可信内网。多 Workspace 租户、SQLite 多进程协调、水平扩容、高可用和公网加固均为 Post-MVP。发布前必须在具备授权凭证/CLI 的内网宿主机运行五类真实 Provider smoke；fallback 通过单元测试不等于真实 Provider 发布验收通过。

## Terms

- **数字分身 / Digital Twin (PersonalAgent)** — the single agent representing one person.
  ✅ `class PersonalAgent` `agents.py:87`; per-user `personal_agent_id` `models.py:124`,
  provisioned on signup. Currently one shared module-level instance acting *as the calling
  user*, not a per-user resident agent.

- **个人记忆 / Personal memory** — a person's private, layered memory, distinct from org
  memory. ✅ `UserMemoryItem` `models.py:441`; short/mid/long-term `MemoryLayer` `models.py:36`;
  routes `routes/memory.py`. Hard-scoped to `user_id` (`store.py:480`).

- **事实与过程载荷 / Structured Memory payloads** — optional `MemoryFactV1` and
  `ProcedureMemoryV1` on existing Memory identities, implemented in the first Stage 3 slice.
  Explicit owned-document confirmation/correction and temporal fact queries are public at
  `/api/memory/facts`. Existing reviewed Task capture/revision accepts payloads; team material
  still requires independent Memory Review. Current eligible versions carry approved historical
  intervals; changed evidence and overlapping incompatible assertions remain visible as insufficient
  evidence/conflict. Legacy automatic summaries and marketplace context exclude these payloads
  pending the full ContextAssembler and complete prompt budgets. Opt-in durable document learning
  produces private suggestions with persisted literal source spans and requires owner confirmation.
  Owned forgetting/source withdrawal fences late writes, invalidates provable frozen lineage and
  cleans search projections; shared bodies and their independent governance are retained.
  Inject mode applies private core preferences in local direct/Standard execution.
  Shared Run assembly (ADR 0063) owns SQL/fact/procedure/recall routing and gives full
  preferences priority in the combined 8000-character component allowance, including
  rendered metadata and headers. Private chat keeps preferences without project recall;
  observe/off never deliver context or usage. Complete-request budgeting remains separate.
  Local direct Session compaction now reacts to the complete first-request allowance,
  including current input, instructions, enabled tool schemas and output reserve. It
  retains complete recent user turns and tool units, and checks the summary before CAS.
  Local streamed SDK calls budget complete requests on every turn, including approvals;
  SDK tool Memory receipts wait for exact-output model handoff. Local direct/Standard
  approvals restore private frozen context and recheck its input, Memory sources,
  core preferences, Skill/plan identities and current authority before approval and handoff.
  Owned forgetting redacts affected pending snapshots and fences their late reconstruction.
  Explicit current-project owner questions and typed SDK entity/time queries now select
  complete qualified facts through current SQL scope filters. Unknown/conflicting facts and
  budget drops provide diagnostics; receipt commit repeats the exact temporal query in the
  same transaction. Forgetting also redacts withheld fact candidates. Current Task/Review
  counts and linked-Task status/dependency questions now use the authorized SQL state query,
  shared by the state API and governed project_state tool. Private, foreign and archived
  Tasks are excluded; missing dependencies remain unknown and no Memory receipt is created.
  Recovery and local requests recheck frozen SQL results. Local Runtime model boundaries
  also recheck Run/writer identity, current actor/project/thread access and deadlines in off mode.
  Capacity-wrapped requests repeat budgeting and current authority/source checks after
  waiting for the actual model slot; queueing does not create a Memory receipt.
  Local Sessions bind an exact private owner/Project and fenced Run writer, import
  canonical ChatMessage bodies, and commit appends against observed versions with
  durable command receipts. Memory-derived cached history rechecks versioned origins;
  owned forgetting clears affected Session cache and rejects late restoration.
  Direct approvals freeze and transactionally recheck Session version/content hash,
  including Memory off and database reopen. General external evidence archives,
  automatic SDK replay deduplication and full remote context parity remain unfinished.
  New CLI Runners negotiate V2 direct envelopes containing full private SDK Session items.
  They use shared request-pressure compaction and return actual SDK continuation items;
  cloud completion checks the frozen snapshot/current Session version and authority in
  the Run settlement transaction. Durable completion replay and spool reopen preserve
  tool identities without model reexecution. V1 clients keep their original contract;
  both versions and Standard nodes enforce full request budgets; see ADR 0064.
  V3 Runners negotiate `context-handoff-v1` for prepared automatic Memory/core preferences.
  Every SDK request requires live cloud context/lease authorization; only a returned model
  response followed by accepted confirmation creates exact Memory-use receipts. Delivery
  confirmation persists before completion in the private spool. Successful V3 completion
  rechecks current context and requires confirmed execution; direct Session commits archive
  delivered dependencies. New node completion hashes support actual SDK floating-point
  output without changing V1 hashes. New remote handoffs atomically reserve against the
  existing Run model budget shared with cloud SDK requests, including compaction/retries.
  Limits/prices stay frozen; positive input/output usage settles the original reservation,
  while unknown calls remain conservatively charged. Late cost settlement cannot restore
  cancelled context. Confirmed over-cap output is retained in accounting and refused at
  completion; offline delivery fails its lease and withholds queued successful completion.
  New CLI Runners also negotiate `tool-handoff-v1`: each native file read obtains
  live cloud authorization and atomically consumes the same Run tool counter as
  local SDK work. Transport replay does not charge twice; failed admitted attempts
  retain their quota. Clients without this protocol receive no native file tools.
  New claims freeze the selected model profile/definition and pin the first declared
  actual model; policy changes block later model/tool admission and completion.
  Unfinished-run recovery remains; see ADR 0065.
  Knowledge now exposes authorized project/term fact queries at current, historical
  or interval time, with optional observation cutoff. Results distinguish unknown,
  conflict and insufficient evidence and link current accessible Memory/documents.
  They reuse the fact API without a model call or Memory-use receipt.
  Current verified procedure details offer a Task draft using the recorded goal.
  The draft travels in client navigation state, requires explicit save/start and
  does not bypass current procedure selection or execute stored steps. Tasks now
  read, inspect and create in the explicitly selected authorized Project; omitted
  create scope retains the old default and command hash.
  State questions may also assemble a qualified method within the remaining shared
  allowance. SQL counts keep priority and create no Memory receipt; committing the
  method receipt rechecks both current SQL and reviewed evidence under the writer lock.
  Project terminology uses manually confirmed exact aliases inside the Project aggregate;
  merged queries retain original fact evidence and report conflicts. Vocabulary changes
  invalidate frozen term selections and archived SDK tool output. Local procedure selection
  checks literal goals, machine-checkable preconditions, current native tool grants/versions,
  installed environment versions and independent Review/Artifact evidence. Unknown conditions
  withhold steps; references do not become executable Skills. SDK lineage distinguishes
  procedure and fact-only delivery. Forgetting also redacts withheld procedure selections.
  General semantic context assembly, reviewed Skill promotion, remote live authority checks and
  complete Session hardening remain unfinished.
  See `docs/adr/0019-source-backed-temporal-memory-payloads.md` and
  `docs/adr/0020-durable-document-learning-and-owned-forgetting.md` and
  `docs/adr/0021-bounded-sdk-requests-and-delayed-memory-delivery.md` and
  `docs/adr/0022-frozen-local-context-across-approvals.md` and
  `docs/adr/0023-authorized-temporal-fact-context.md` and
  `docs/adr/0024-current-project-state-context.md` and
  `docs/adr/0025-current-authority-at-local-model-boundary.md` and
  `docs/adr/0026-owned-local-sessions-and-memory-lineage.md` and
  `docs/adr/0027-trusted-local-session-approval-checkpoints.md` and
  `docs/adr/0028-confirmed-project-terminology.md` and
  `docs/adr/0029-qualified-local-procedure-context.md`.

- **组织知识资产 / Org knowledge asset** — governed project/team Memory. A Task Review acceptance can be explicitly captured as private Personal Memory or a proposed Team Candidate with frozen `MemoryProvenanceV1`. A Team Candidate becomes Team Knowledge only after its separate `MemoryReviewV1`; Task Review never publishes shared knowledge by itself.

- **记忆修订 / Memory revision** — a new Team Candidate that declares which governed Team Knowledge version it supersedes. The predecessor remains active while the revision is pending or rejected. Accepting the revision activates the new Team Knowledge and deprecates its predecessor as one decision.

- **记忆生命周期 / Memory lifecycle** — the governance state of one immutable Memory version. Disputed, deprecated, expired, and archived versions remain auditable but cannot enter automatic Agent context. Archive temporarily wraps the prior inactive or active state; restore returns only to that recorded pre-archive state.

- **记忆使用回执 / Memory Use Receipt** — an immutable fact that one exact Memory ID, record version, content hash, and retrieval layer passed the final local safety and context handoff for one Agent Run under a stable citation label. Search results, quarantined content, and locally failed dispatches do not count as Memory use. Citation labels are transactionally reserved per Run before use, so concurrent searches cannot map one label to different Memory versions. Later Memory revisions never rewrite an earlier Run's receipt.

- **记忆上下文 / Memory context** — the bounded, permission-filtered set of eligible Personal, Project, and Team Memory supplied to an Agent. Scope controls visibility; MemoryLayer independently filters retrieval depth before ranking. The complete rendered payload is budgeted, and credential-like or prompt-injection-like Memory is quarantined before context assembly.
  Current actor/project/team, lifecycle, layer and type filters run in SQL before bounded candidate retrieval. Search no longer loads entire Memory/Document/Blackboard collections; hits and visibility checks share a read transaction. Local FTS/LIKE recall is queued independently of external embeddings. The 50k/10-concurrent synthetic FTS gate passed at 642.471ms p95; vector capacity and real-model quality remain pending (ADR 0030).

- **学习运行提示 / Learning operations** — owner-only SQL aggregates over currently authorized projects show due queue age, expired leases, budget and cleanup backlog. Provider Retry-After is durable; active extraction renews its fenced lease and stops after policy/source changes. Unknown usage keeps its reservation. These operational signals do not approve facts or imply model quality (ADR 0031).

- **记忆候选 / Memory candidate** — body-free version/hash decisions subordinate to the owner's Run bundle. Prepared, withheld, quarantined and budget-dropped states differ from actual delivery proven by an exact immutable use receipt. Current authority, origin and structured applicability gate title projection. Forgetting redacts candidate-only snapshots and tool payloads and blocks late restoration (ADR 0032).

- **确认闸门 / Confirmation gate** — policy-driven human confirmation before data crosses a
  boundary or writes to org memory. ✅ Risk and Provider approvals use `InboxItem`; project
  deliverable quality decisions use the separate **Task Review** aggregate and project an assigned
  reviewer's pending work into Inbox.

- **任务图 / Task graph** — the server-owned parent and dependency relationships between Project Tasks. Parent edges drive work-breakdown and milestone rollups; dependency edges gate `start` and new Task-linked AgentRun claims. Relationship mutation is project-scoped, versioned, idempotent, and cycle-checked in the write transaction. It does not alter `Task.status` or `Task.collaboration_stage`.

- **项目运营投影 / Project operations projection** — a rebuildable SQLite projection over canonical Task and task-kind Thread records. It accelerates project overview, calendar, Agent queue, graph hydration, and pagination but does not own permissions, versions, transitions, reviews, or Run identity.

- **Agent 队列 / Agent queue** — a read model of Agent-assigned Project Tasks classified as backlog, waiting for dependencies, blocked, ready, running, or review. It never auto-dispatches a Run or bypasses Task and Runtime admission gates.

- **项目巡检 / Project inspection** — ✅ `/api/task-operations/{project_id}/inspections` and the Tasks page expose daily-progress, blocker/overdue, and pending-review queries. Rules read one permission-checked SQLite snapshot of shared task-kind Tasks and Reviews; private conversation Tasks are excluded. Progress uses frozen Task/Review command versions, with missing history reported as insufficient evidence. Memory-review entries are limited to the current assigned reviewer with a current effective review permission. Reports include source watermarks and versioned references, and never mutate Task or Memory state. Versioned project schedules atomically admit a frozen occurrence, an existing v1 AgentRun, and its existing Runtime dispatch, then advance the next slot. Automation defaults off; observe is read-only, execute requires the SDK Runtime. These templates read real local records with zero model usage. Owner-only durable reports and Inbox notifications do not share the owner's private review report with other managers. Legacy research delivery now persists request claims, bounded read retries, safe outcomes and restart-visible queue health; partially published evidence requires reconciliation. It cannot execute shared Project Tasks. Marketplace matching now uses durable version/authorization fingerprints and paginated scan cursors; scouts never grant consent and shared posts exclude private answer text. The full delegated-query lifecycle remains under development.

- **查询数据模式 / Query data mode** — ✅ `real`, `demo`, and `derived` distinguish trusted Provider evidence, explicit demo fixtures, and derived answers. Production evidence-required query paths reject missing/unverified or mock Provider output before persistence or completion. Local canonical Task/Review inspections are real reads and require no external model. Demo mode requires the exact value `AGENTMESH_DEMO_MODE=1`.

- **Task Review / 任务交付审核** — a versioned judgment about whether one frozen set of sealed
  Artifacts satisfies a Project Task. ✅ A pending Review binds one Task, one Run, Artifact IDs and
  content hashes. `accepted` may complete the Task; `changes_requested` and `rejected` return the
  Task to active work. It is distinct from Memory Review, which decides whether content may become
  shared organizational knowledge.

- **溯源 / source-citation** — origin tracking on messages, posts, memory. ✅ `class Source`
  `models.py:270`, propagated through synthesis (`agents.py:653`).

- **任务中心 / Task Center** — the authenticated React `/tasks` route is a project work view over permission-filtered Task and Blackboard data. It is read-only by default; `AGENTMESH_TASK_MANAGEMENT=write` enables server-authoritative creation, editing, assignment, delivery transitions, blocking, cancellation, archival, linked Agent execution, and Task Review. A linked Run keeps an immutable `task_id`; a Review freezes sealed Artifact identities and hashes before a human decision. Task detail exposes only safe Run, Artifact, and Review projections, never Run input/output or Artifact content. Only the assigned reviewer can use the separate review-scoped inspection endpoint for the exact frozen Artifact set submitted by its Run owner.

- **BBS 协作市场 / Collaboration board**: where twins post signals and collaborate. ✅
  `blackboard.py` provides the per-task board, and `marketplace.py` implements signal publishing
  plus the **marketplace scout**, which matches needs to helpers and triggers delegated answers.
  Authenticated `/api/market/*` routes and the Collaboration UI expose worker status, signals,
  and match audit data. Delegated-answer consent, resolution, and adoption are not exposed there.

- **数据不离境，只出答案 / Answer-only gateway**: other agents never touch raw memory; they
  receive an abstracted answer. ✅ Implemented internally by `PersonalAgent.answer_for_peer`,
  including standing-consent checks, Inbox confirmation for non-consented or sensitive requests,
  target-user personal-memory retrieval, citations, and audit events. The marketplace scout invokes
  this path. A target-owned confirmation/denial API exists. Dedicated initiation, standing-consent
  management, durable result lookup and adoption workflows remain incomplete. The legacy
  unconfigured-model answer template is not proof of real answer quality. An answer synthesized from another user's private memory is derived data and
  is **not** a privacy guarantee. **Decision (2026-08-09): this is an internal-company project where
  cross-user data flow is permitted, so "只出答案" is a collaboration/UX pattern, not a privacy
  control; see ADR 0003 privacy-posture.**

- **血缘链 / memory lineage**: derived-from / cites edges between memory items. ✅
  `MemoryRelation` is persisted and written by accepted personal-to-team sharing and delegated-answer
  adoption. Relations have no public list/detail API or UI.

- **贡献度 / Contribution points**: points settled only when output is adopted. ✅
  `ContributionPoint` implements record-only shadow points, and delegated-answer adoption records a
  point plus a `MemoryRelation`. Adoption and point listing are internal-only; there is no public
  points UI/API, redemption, or anti-collusion system.

- **会议双通道 / Meeting dual-channel** — mic=me, system-audio=others, for MVP meeting
  capture. ❌ absent from this repo — belongs to **designOS**, which is not checked in here
  (referenced only in `o2.py:21-28`). MVP replaces this entry point with pasted notes text.

## Universal Skill orchestration

- **Searchable Skill** — a visible built-in Runtime Skill whose capability Profile is current, approved, and trusted. Searchability means it may be considered for relevance; it does not grant execution permission.
- **Ready / Selectable / Executable** — successive request-scoped states. Ready means current Tool, resource, authorization, and side-effect policy checks pass; Selectable means the Skill is in the frozen Planner shortlist; Executable means the same conditions pass again when its node starts.
- **Candidate Snapshot** — the immutable, server-owned record of the safe capability cards and identities actually shown to a Planner. Later repair, editing, approval, and recovery interpret a candidate only through this snapshot.
- **Planning contract** — the immutable generation marker chosen when a plan-producing Run is first created. It determines the compatible Task Catalog and frozen Plan representation; deployment phase never reinterprets an existing Run.
- **Blocked match / capability gap** — a blocked match is a relevant but currently non-executable Skill disclosed through safe diagnostics. It becomes a capability gap only when a required output has no ready alternative; gaps prevent a completed outcome.
- **Task/Scenario** — the source of intent, canonical output requirements, evidence requirements, and completion criteria. It can influence ranking but is not a Runtime Skill permission boundary or candidate whitelist.
- **Zero MCP gateway** — an optional user-managed local MCP integration. AgentMesh maps imported `mcp__zero-design__*` requirements to a separately granted, read-only gateway and exposes only the active Skill's requested remote tools. Host-level `Bash`/file capabilities and Zero write tools are not implied by this connection.

## Research orchestration retirement

- **Research-v2** — historical, owner-scoped, read-only compatibility only. Its executable writer,
  planner, recovery path and mutation APIs are retired. Existing Runs and Artifacts remain readable
  through exact-version decoders and the history adapter; retry, cancel, clarify, execute and repair
  writes remain forbidden. See `docs/adr/0007-retire-research-v2-new-runs.md`.
- **Research-v3** — retired before production launch. The preview composition, active routing and UI
  entry points, dedicated catalog assets and rehearsal runbook were removed. The retirement audit found
  no local research-v3 Run or v3 repository row. Existing additive SQLite tables are left inert during
  the first retirement stage and are not evidence of a supported Runtime. See
  `docs/adr/0008-retire-research-v3-preview.md`.
- **Orchestration version** — `v1` is the only version used for new executable Agent Runs.
  `research-v2` remains solely as a historical persisted-data discriminator. Any residual v3 schema
  columns or tables are compatibility residue, not a selectable generation or future activation path.
- **DeepSearch** — implemented behind a default-off gate as an explicit planning mode on the existing
  v1 Skill DAG. It does not import, alias, revive or fall back to either retired Research generation.
  The first releasable slice accepts only real built-in `web_research` as report Evidence; MCP and other
  Tool paths fail closed. See `docs/plans/2026-08-26-deepsearch-v1-development-plan.md`.

ADRs 0005 and 0006 are retained as historical architecture records. Their descriptions of executable
Research runtimes, writer selection and future v3 activation are superseded by ADRs 0007 and 0008;
ADR 0008 also narrows ADR 0007's writer-control compatibility clause.

Truthful delegated answer outcomes (ADR 0033): absent evidence is insufficient_evidence; unavailable models are blocked. Shared market posts contain status only and cannot be adopted as answers. Durable project DelegatedQueryV1 (ADR 0034) now binds both current users/project/personal Agents, frozen private evidence, scoped consent, sensitive Inbox confirmation, sealed restricted answers and atomic idempotent private adoption. Query result projection and adopted origins recheck current authority. Legacy global grants/status posts cannot prove an answer. Plain-text input only; full SDK budgets/delivery receipts, structured delegation, connectors and real model quality remain in development.

## Not in this repo

New document upload recovery (ADR 0035): original bytes are frozen in private controlled staging, with hash/owner/scope identity and seven-day retention. Current-authority leases fence parsing commits; Sources/documents/private memories/FTS and completion commit atomically. Startup recovery, scoped paginated Jobs, versioned owned retry and truthful Knowledge upload/status controls are public. Cache cleanup is independent of completed imports. Parser process/resource containment is now covered by ADR 0046, and manual edits/reimports by ADR 0038. Deployment filesystem/network isolation, old incomplete Job repair, external connector watermarks and enabled vector Provider behavior remain unfinished.

Market projections (ADR 0036) use one current-project SQL read snapshot, explicit published signal/audit scope and current active membership. Decode windows are bounded while SQL counts cover the authorized scope. Worker queues/errors are owned current-project metadata; legacy match bodies cannot prove private answers. Publishing source authority and late opt-in/source changes are a separate remaining slice.

Automatic publication (ADR 0037) now freezes bounded, qualified ordinary inputs and current opt-in/identity/project/Agent/binding/model/previous-post authority. It rechecks before send and in the atomic post/index/audit commit; private peer answers and rollups do not become public signal material. Opt-out and owned forgetting/withdrawal clear the generated signal and indexes in their existing transaction. Market reads and client caches bind explicit authorized projects. General origin invalidation and full SDK call/budget/delivery governance remain unfinished.

Manual document maintenance (ADR 0038) is an atomic current-authority command on existing documents and personal Memory. Edits invalidate owned prior native text/indexes and the generated public summary in the same transaction. Selected-version reimports commit stable scoped Sources/chunks/progress together, repair matching missing projections and reject altered/extra/archived/forgotten chunks. Current chunk reads are SQL scoped and bounded. Knowledge exposes separate save/reimport operations and marks upload history with its original version; no fact or team review is implied. General Source propagation and old unproven Job repair remain separate.

Generated publication dependencies (ADR 0039) privately bind the selected native Memory/Task/Thread/Document records and current User/Project/Agent/participation/binding/model keys. Source changes or deletion retract the public body and search/vector projections in the same SQLite write; dependency triggers ignore identical/new/unselected Memory writes. Explicit document and forgetting commands retain conservative aggregate withdrawal. New optional binding/model definitions also invalidate earlier output. Reopen preserves proven dependencies and withdraws legacy generated aggregates without them; withdrawn signals are not reindexed. Public metadata contains no private source IDs. This does not implement external Source propagation, scout qualification or complete SDK governance.

Agent memory binding configuration (ADR 0040) authorizes current active User and same-workspace Agent ownership/management permission in the actual transaction. Server identities prevent caller-ID overwrites, and writer serialization preserves one binding per Agent. Unavailable projects and oversized settings are rejected; duplicate or mismatched stored bindings fail explicitly in API and internal readers. Ordinary queries retain the requested project. Binding writes share the existing publication invalidation transaction; current Scout material qualification is covered by ADR 0041, and content-type semantics by ADR 0044. External connectors and full SDK governance remain unfinished.

Market matching (ADR 0041) now selects bounded, qualified private material for each signal's explicit project under current actor/Agent/binding/model authority. Keyword-filtered SQL preserves older relevant material; only bounded titles reach the matching model. Native documents and parent Memory hashes join the frozen proof, and literal imported chunks must still match current document content. Every primary/fallback send and both YES/NO results recheck current material, signal and claim ownership/expiry. High material continues through the existing peer-confirmation gateway. Full request/cost/cancel budgets, external Source archives and complete SDK/Runner parity remain unfinished.

Local committed project changes (ADR 0042) can explicitly trigger the same durable read-only inspection schedules. Server-owned cursors consume native Task/Task Review command receipts under current shared-project visibility; private chat/raw edits are excluded. Quiet/coalescing windows and the existing run floor bound frequency, cursor ordering preserves scan progress, and occurrence/Run/dispatch/cursor commit together. Opt-in/resume/template changes start at the current watermark. Off/observe, current authority, overlap, owner reports and independent write gates remain in force. External connector/webhook triggers are still unfinished.

Current-project relations (ADR 0043) reuse legacy MemoryRelation storage with optional typed frozen annotations. Human read queries independently gate current nodes/targets/evidence under one SQLite snapshot and bounded two-hop/candidate/record/character budgets. Native Task links, reviewed delivery Memory and qualified literal/fact/span document citations are projections; unproven legacy links are not graph authority. Private parents/documents/Artifacts remain owner-only. Annotation/audit creation reloads authority in the write transaction, freezes versions/hashes and provides durable conflict-checked replay. Task/Knowledge drawers expose metadata and explicit candidate/human annotations without changing Memory/Task lifecycle. General external Source contracts, graph SDK delivery/discovery and model-inferred relations remain unfinished.

Memory binding content types (ADR 0044) now have one meaning across ordinary/SDK retrieval, context and structured delivery, market material and delegated answers. Nonempty legacy type lists with missing/null type_policy_version deny Memory until an authorized configuration PUT confirms version 1; untyped legacy bindings retain existing scope/owner/project rules. Search categories are separate intersections, and collection-local IDs cannot grant raw document access. Content type checks run before lexical/vector and material candidate limits; SDK retrieval no longer hydrates all Memory records to construct an ID whitelist. Current binding changes also withhold prepared structured delivery, candidate metadata and previously delivered delegated answers. Startup retracts pre-upgrade generated Memory publications that depend on unconfirmed restricted bindings, preserving independent Task-only material and current/untyped policies. Full context priorities, real quality and external/Runner source parity remain unfinished.

Local nonstream model stages (ADR 0045) now share complete SDK request admission for intent, legacy/Universal plans, DeepSearch requirements/graphs/plans, synthesis and semantic review. The wrapper owns the asynchronous gate and restores it on completion/error/cancellation; model capacity acquisition repeats budget, current actor/Run/writer/scope and deadline checks. Planning admits only planning Runs, finalization only running Runs. Standard synthesis repeats existing Source existence/identity checks after waiting. Admission errors preserve safe codes and bypass schema repair and DeepSearch digest/report fallback. Initial oversized DeepSearch input is rejected before its durable model reservation; late refusal follows the existing unknown-attempt settlement policy. No new private Memory injection or cumulative ordinary-Run cost ledger is implied. Full context priorities, general Source archives, Session/Runner parity and real-model quality remain unfinished.

Production document parsing (ADR 0046) runs in an owned POSIX process/session with private fixed-name input, isolated Python startup, a minimal environment and bounded JSON output. CPU/file/descriptor limits, a 90-second deadline and sampled process-tree RSS bound resource use; shutdown and failed claim renewal stop the parser/OCR group and preserve retryable original input. Current authority/claim/identity still gate the independent atomic import. PDF pages, OOXML expansion and encoding-independent DTD rejection prevent silent partial imports. Resource containment is not a filesystem/network security sandbox; Linux execution and real OCR recognition quality remain unverified.

Local ordinary synthesis source identity (ADR 0047) now compares persisted Source citation metadata with node results and freezes a per-call digest of its existing identity fields. Actual queued model handoffs and synthesis return recheck current sources/owner; stale, changed or mismatched identities cannot produce the new synthesis. Source creation compares and inserts under one SQLite write transaction, preserves identical replays and rejects competing/payload-ID-conflicting identities. This is local citation-record proof, not remote content hash or a durable Source lifecycle. Finalizer atomic rechecks are now covered by ADR 0048; persistent snapshots, archives/tombstones, connectors and Runner source delivery remain unfinished.

Ordinary/Universal synthesis finalization (ADR 0048) now freezes current Run/plan/node-result/Source identities before synthesis and rechecks them with active actor/project/thread, membership and deadlines in the terminal write transaction. Verified Universal synthesis Artifacts, Plan/Run, Inbox convergence and events commit together; failures leave no new synthesis Artifact. Old writers/plan versions cannot fail new execution, and admission refusals bypass partial fallback. Source reads share bounded citation semantics with model handoff. This is a per-call local seal, not generic external-content or persistent ContextSnapshot proof; projection authority is covered by ADR 0049, while origin lifecycle and remote delivery continue separately.

Terminal output projection (ADR 0049) now rechecks the expected sealed Run identity/writer/content and current actor/project/thread access within the existing chat/private-Memory/receipt/event transaction. Runtime execution cannot adopt a writer replaced after sealing. Automatic Memory policy is read in that transaction; manual HTTP saves freeze the validated Run and reject late changes. Existing owned manual saves remain intact, forgotten run memories cannot be restored, and replay checks stored message/Memory identity. Private Session markers bind a proven owner and leave other writers/withdrawn Sessions unchanged; shared Task delivery does not acquire the requester's private Session or mutate Task/Review state. Sealed-result recovery may follow execution expiry but still needs current access. This does not persist synthesis input proof, propagate all origin/Memory changes to outputs, or establish remote SDK delivery parity.

Direct SDK state transitions (ADR 0050) now compare the original execution identity in atomic completion/pause/error/cancellation writes. Completion repeats current Session access, source and deadline checks; pause freezes and rechecks its SDK checkpoint before committing approval state. Errors and old task cancellation cannot terminate a replacement writer. Approval-resume failures clear paused state, and terminal Run/Inbox/event writes commit or roll back together. Explicit user cancellation still addresses the current Run. Local producer cancellation is covered by ADR 0051; persistent leases, complete planning writer management and remote delivery proof remain pending.

Local SDK producer cancellation is covered by ADR 0051: Runtime awaits the pinned SDK's public producer task after event draining, and an independently cancelled child propagates to its parent and siblings through the existing TaskGroup. Ordinary cancellation freezes the execution Run/Plan version, and its terminal transaction rejects late writer/Plan/Runner changes while preserving cancellation semantics and unknown external outcomes. The shared transient Run identity includes runner_id; persistent Memory/Source hashes are unchanged. Model admission retains synthesis-specific snapshot refusal codes. This does not complete all planning/approval/transition identity checks, cumulative budgets, durable leases or remote delivery.

Approved local DAG claims and node approval recovery (ADR 0052) carry original Run/Plan inputs into actual claim, transition, pause, resume and cancellation transactions. Transient Plan/node identities exclude execution status/time fields; attempt/state CAS remains separate. The executor fences initial/resumed execution, capacity-delayed claims, subsequent loops and pause returns. A legitimate node commit is retained without adopting a new writer for subsequent synthesis. Error convergence fences the expected node/Plan/Run and preserves unknown external writes. These checks do not supply durable planning leases, complete restart replay, cumulative budgets, full origin invalidation or remote delivery.

Ordinary local model accounting (ADR 0053) is a bounded Run ledger in SQLite, independent of mutable Run state. All guarded local planning/execution/synthesis requests and direct Session compaction share its frozen first-reservation limits. Complete request checks repeat after capacity waiting; atomic reservation precedes Memory delivery. Only a proven admission refusal before calling the adapter can release a reservation. Failed/cancelled/missing/malformed/zero-default usage keeps estimated input plus capped output; reported positive consistent usage settles to actual counts. Budget and safe metadata events commit together; reopening, concurrent reservations and receipt replay preserve accounting. Late receipts can settle their own reservation without changing a replacement writer. The model factory defaults hidden HTTP retries off. Unified tool accounting and remote Runner receipts remain pending; DeepSearch accounting is unchanged.

Ordinary local cost estimates (ADR 0054) use an explicit bounded price map keyed by actual SDK model name, frozen at first reservation with the Run limits. Integer input/output rates declare currency, version and optional aware validity interval. The optional currency/micro-unit cap rejects unavailable, inactive or mismatched prices before the adapter call, including after capacity waiting. Reported positive usage settles the estimate; unknown usage retains the reservation, and known unsent admission releases it without replacing the price policy. Late receipts preserve original prices; actual overspend is retained before refusing output. Unpriced or mixed-currency totals remain unknown, and legacy unpriced calls are never retrospectively priced. Static admission error codes survive direct, approval and ordinary finalization. Estimates are not Provider invoices and exclude discounts, tools, background learning and remote calls.

Ordinary local SDK tool quotas (ADR 0055) freeze with that policy and use the existing monotonic Run tool counter. Operators may only tighten the prior 24-attempt maximum. Admission atomically verifies original Run/Plan inputs and running node attempt; native, Skill resource and governed MCP handoffs repeat identity/deadline checks after capacity waiting before the actual claim. An admitted but later refused queued attempt retains its quota, and approval recovery/reopening cannot reset it. Governed MCP exceptions propagate through the SDK instead of becoming model-visible retry material; typed static admission codes survive finalization. Node transition conflicts preserve an advanced execution. This is not tool billing, durable execution leases, complete current Tool-definition/grant proof, remote receipts or a unified DeepSearch/background policy.

Runner node leases authorize individual devices; the parent Run's runner_id records the latest leased node device and may change between nodes. The DAG controller's execution hash therefore excludes that marker only for Runner plans, retains generation/contracts/definition and preserves the current marker in terminal writes. Server/direct identity remains strict. Terminal-node progress can be retained during parent cancellation; active advanced attempts cannot be terminated by stale writes. Remote lease generation/input proof remains incomplete.

Optional Source observations (ADR 0056) attach a versioned external identity/text-hash/lifecycle snapshot to the existing Source, preserving absent-snapshot legacy serialization and hashes. An owner/project-authorized CAS command commits bounded matching text observations, server revisions and audit together; deleted is terminal, unchanged observations keep first timestamps, and old immutable writers cannot adopt newer snapshots. Current Source and parent-document checks gate existing Memory retrieval, structured evidence, late learning and queued SDK delivery. Managed mirrors reject local edits. Selected source dependencies retract generated signals atomically; startup withdraws older direct-source/document aggregates without matching dependencies. Native uploads remain on their original contract.

Source synchronization (ADRs 0057–0062) reads operator-bound repository documents and GitHub Issues into owned mirrors. Each page, including the first, persists a private claim and 90-second lease before reading. Exact claim/current authority/expiry checks fence completion; live claims refuse overlap, and startup/status/periodic reconciliation recovers expired claims. Sources/documents/indexes and terminal cursor state commit together. Incremental pages freeze since; full scans withhold omitted sources. Current-source checks prove exact owned cursors and current operator bindings; configuration invalidation persists and requires reset/fresh observation. Source hashes remain intact except actual observation/lifecycle changes. The lifecycle worker defaults off; owners separately opt in to bounded page/cycle scheduling. Transient failures allow three automatic attempts with persisted provider waits shared across the same configured source; access/invalid responses pause it. Versioned controls fence in-flight cancellation without aborting issued HTTP requests. Knowledge exposes automatic controls, waiting/progress and read-only mirror import. Complete remote ACL/deletion discovery, freshness, indirect repair and Session/Runner/Artifact invalidation remain unfinished.

- **designOS** — org-layer + meeting capture + business scenes. Referenced only; no source
  tree here.
- **PostgreSQL / EmployeeTwin fusion** — target of `docs/2026-07-10-...fusion-plan.md`.
  Current persistence is **SQLite** (`store.py:47`); Postgres/fusion are aspirational.
