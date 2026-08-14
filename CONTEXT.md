# CONTEXT.md — Digital Twin × Agent Market

Glossary for the "digital twin / agent collaboration market" work. Each term maps to its
**code reality** as of 2026-08-14, so downstream work doesn't mistake the design doc's
aspiration for what is built. Source design: `docs/2026-08-08-数字分身-Agent协作市场-产品设计.md`.
MVP scope decisions: `docs/adr/0003-mvp-scope-answer-only-gateway.md`.

Legend: ✅ works · ⚠️ convention/partial · ❌ absent (design-only).

## 前端术语约定 / Frontend terminology

后续对话与文档中,"新前端"/"旧前端"固定指代以下两处,不得混用:

- **新前端** — `agentmesh-demo/`。React 18 + Vite + Tailwind 的 TypeScript 单页应用；
  开发环境由 Vite `5178` 提供页面并将 `/api` 代理到 FastAPI `8010`。这是当前使用的前端，
  其中 Digital Self、Workspace、Collaboration 已部分接入后端，Insights、Knowledge、Digital Human 仍含 Mock 数据。
- **旧前端** — 项目根目录的 `app.html`。单文件深色工作台,无任何构建步骤,
  `agentmesh/app.py:93` 以 `FileResponse` 直接 serve。等价切换完成后按计划退役
  (先迁至 `/legacy/app.html` 保留一个发布周期,再删除)。

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

- **BBS 协作市场 / Collaboration board** — where twins post signals and collaborate. ⚠️
  `blackboard.py` is a working *per-task* board (posts, task-cards, handoff, execution locks),
  **not** a signal-matching *marketplace* — no problem/need/offered-value matching algorithm.

- **数据不离境,只出答案 / Answer-only gateway** — other agents never touch raw data; they
  query a twin that returns an abstracted answer. ⚠️/❌ Visibility filtering exists as a
  *convention* (`blackboard.py:361`), but the cross-user execution path — B's twin triggers
  A's twin to answer from A's private memory — **does not exist** (`agents.py:496-497`,
  `store.py:587-592`; the only responder path `fulfill_research_request` `agents.py:769` fetches
  *external* evidence for the requester, touching no one's `UserMemoryItem`). **This is the
  MVP's single load-bearing build.** Caveat: even once built, an answer synthesized from A's
  private memory is derived data and is **not** a privacy guarantee. **Decision (2026-08-09):
  this is an internal-company project where cross-user data flow is permitted, so "只出答案"
  is a collaboration/UX pattern, not a privacy control — see ADR 0003 privacy-posture.**

- **血缘链 / memory lineage** — derived-from / cites edges between memory items. ❌ absent
  (zero code). MVP builds one `derived_from` edge as an extension of `source/citation`.

- **贡献度 / Contribution points** — points settled only when output is adopted, converted to
  employee rewards. ❌ absent (zero code). MVP does **shadow points only** (record, no
  redemption); redemption + anti-collusion is deferred.

- **会议双通道 / Meeting dual-channel** — mic=me, system-audio=others, for MVP meeting
  capture. ❌ absent from this repo — belongs to **designOS**, which is not checked in here
  (referenced only in `o2.py:21-28`). MVP replaces this entry point with pasted notes text.

## Not in this repo

- **designOS** — org-layer + meeting capture + business scenes. Referenced only; no source
  tree here.
- **PostgreSQL / EmployeeTwin fusion** — target of `docs/2026-07-10-...fusion-plan.md`.
  Current persistence is **SQLite** (`store.py:47`); Postgres/fusion are aspirational.
