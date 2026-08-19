# CONTEXT.md — Digital Twin × Agent Market

Glossary for the "digital twin / agent collaboration market" work. Each term maps to its
**code reality** as of 2026-08-20, so downstream work doesn't mistake the design doc's
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

- **组织知识资产 / Org knowledge asset** — confirmed project/team memory. ✅ `MemoryItem`
  `models.py:427`, distinct store from personal memory.

- **确认闸门 / Confirmation gate** — policy-driven human confirmation before data crosses a
  boundary or writes to org memory. ✅ `RiskPolicyRule` `models.py:236` → engine `risk.py` →
  `InboxItem` `models.py:409` quarantine that halts the task (`agents.py:608`). Note: reviews
  ride on `InboxItem`; there is no separate `review_items` table.

- **溯源 / source-citation** — origin tracking on messages, posts, memory. ✅ `class Source`
  `models.py:270`, propagated through synthesis (`agents.py:653`).

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

## Research orchestration v2

- **ResearchRuntime** — the single in-process composition root and lifecycle owner for
  research-v2 planning, execution, recovery, reconciliation and shutdown. ✅ Created by the
  FastAPI lifespan, injected through `app.state`, and used by the production Web path. It is
  not a durable state source; SQLite remains authoritative.
- **Research Workflow** — durable control state bound one-to-one to a research-v2
  `AgentRun`. ✅ `ResearchWorkflow.phase`, `active_gate` and `state_version` are persisted;
  AgentRun/Attempt/Step/Invocation states are subordinate projections.
- **Orchestration version** — immutable per Run: `v1` or `research-v2`. ✅ The single
  `POST /api/agent/runs` routing decision, client-turn replay, aggregate projection and
  Workspace branch are connected. `off` creates only v1 Runs while historical v2 remains readable.
- **Research recovery** — UNKNOWN external calls are never automatically replayed. ✅ The
  runtime and Web expose explicit retry/abort decisions; refresh, SSE reconnect and process
  restart recover persisted state without silently resending Provider work.

Web Preview and Web Execute are implemented. The engineering candidate has passed local gates,
one authorized Tavily + GPT-5.2 end-to-end Run, all three enabled GPT compatibility smokes and an
`off` rollback drill. Formal Release Gate approval and `execute` rollout are still blocked on the
20-case real observation set, two-reviewer blind scoring and the 10-person internal pilot. See
`docs/verification/2026-08-19-research-orchestration-v2-baseline.md`.

Architecture and delivery boundaries are fixed by `docs/adr/0005-research-runtime-web-vertical-slices.md`.

## Not in this repo

- **designOS** — org-layer + meeting capture + business scenes. Referenced only; no source
  tree here.
- **PostgreSQL / EmployeeTwin fusion** — target of `docs/2026-07-10-...fusion-plan.md`.
  Current persistence is **SQLite** (`store.py:47`); Postgres/fusion are aspirational.
