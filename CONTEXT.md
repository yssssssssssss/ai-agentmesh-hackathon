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

- **组织知识资产 / Org knowledge asset** — governed project/team Memory. A Task Review acceptance can be explicitly captured as private Personal Memory or a proposed Team Candidate with frozen `MemoryProvenanceV1`. A Team Candidate becomes Team Knowledge only after its separate `MemoryReviewV1`; Task Review never publishes shared knowledge by itself.

- **确认闸门 / Confirmation gate** — policy-driven human confirmation before data crosses a
  boundary or writes to org memory. ✅ Risk and Provider approvals use `InboxItem`; project
  deliverable quality decisions use the separate **Task Review** aggregate and project an assigned
  reviewer's pending work into Inbox.

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
  this path. There is no dedicated public UI/API for users to initiate a delegated query, manage
  consent, resolve its confirmation, or adopt its answer, so the complete user-facing workflow is
  not reachable yet. An answer synthesized from another user's private memory is derived data and
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

## Not in this repo

- **designOS** — org-layer + meeting capture + business scenes. Referenced only; no source
  tree here.
- **PostgreSQL / EmployeeTwin fusion** — target of `docs/2026-07-10-...fusion-plan.md`.
  Current persistence is **SQLite** (`store.py:47`); Postgres/fusion are aspirational.
