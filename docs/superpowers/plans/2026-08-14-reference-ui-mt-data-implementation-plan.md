# AgentMesh Reference UI and M/T Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 在保持 FastAPI 为事实源的前提下，把 DigitalSelf、Insights、Knowledge、Collaboration 的布局和内容表达恢复到参考 Mock 前端，并用 `M数据`、`T数据` 标明每个展示模块或字段的数据来源。

**Architecture:** 页面通过 Presenter 将 React Query 的 Canonical Model 和参考 `mockData.ts` 合成为 Reference View Model。页面只消费 View Model。身份、权限、状态和 mutation 永远使用后端；Mock 只补展示字段。AI 工作台业务逻辑保持隔离，只运行回归测试。

**Tech Stack:** React 18、TypeScript 5.6、Vite 5、Tailwind 3、TanStack Query 5、Vitest 2、Playwright 1.48、FastAPI、SQLite。

**Design:** `docs/superpowers/specs/2026-08-14-reference-ui-mt-data-design.md`

## Global Constraints

- `/Users/heyunshen/Downloads/agentmesh-demo/` 是视觉和产品内容基线。
- FastAPI、SQLite、allowed_actions、版本和权限是唯一业务事实源。
- Mock 数据只用于展示 fallback，不得改变服务端业务状态。
- 标签只使用 `M数据` 和 `T数据`。
- mixed 模块必须字段级标注，不能只显示一个模糊总标签。
- 不修改 AI 工作台消息、Skill、历史、上传、搜索、trace 和记忆检索协议。
- 不新增后端服务、数据库表、SSE 或 WebSocket。
- 每个页面任务独立可用、可测试、可回滚。
- 每个页面任务完成后运行 Workspace 主链和回归 Playwright。
- 视口验收覆盖 390px、768px、1512px。

---

## Task 1: Data provenance primitives and Presenter contract

**Files:**

- Create: `agentmesh-demo/src/lib/presentation.ts`
- Create: `agentmesh-demo/src/lib/presentation.test.ts`
- Create: `agentmesh-demo/src/components/ui/DataSourceBadge.tsx`
- Test DataSourceBadge rendering in `agentmesh-demo/e2e/reference-shell-parity.spec.ts`; do not add a new DOM test dependency.

**Interfaces:**

- Produces `DataSourceKind = 'M' | 'T'`.
- Produces `PresentedValue<T>` with `value`, `source`, and optional `reason`.
- Produces `PresentedModule<T>` with `data`, `sources`, `missingFields`, `loading`, `error`.
- Produces `<DataSourceBadge source="M" | "T" />` rendering exact text `M数据` or `T数据`.

- [ ] **Step 1: Add failing provenance tests**

  Test exact label text, aria-label, mixed-source aggregation, and refusal to silently coerce an unknown source.

- [ ] **Step 2: Run RED**

  ```bash
  npm --prefix agentmesh-demo run test -- src/lib/presentation.test.ts
  ```

  Expected: fail because presentation types/helpers do not exist.

- [ ] **Step 3: Implement presentation primitives**

  Keep the interface small. Presenter helpers may combine fields and source metadata, but may not fetch, mutate, read global auth state, or infer permission.

- [ ] **Step 4: Implement DataSourceBadge**

  Requirements:

  - T data uses mint low-contrast styling.
  - M data uses remind low-contrast styling.
  - Text and aria-label are exactly `T数据` or `M数据`.
  - The component composes the existing Badge primitive without modifying Badge defaults.

- [ ] **Step 5: Run GREEN and build**

  ```bash
  npm --prefix agentmesh-demo run test -- src/lib/presentation.test.ts
  npm --prefix agentmesh-demo run build
  ```

- [ ] **Step 6: Commit suggestion**

  ```bash
  git add agentmesh-demo/src/lib/presentation.ts agentmesh-demo/src/lib/presentation.test.ts agentmesh-demo/src/components/ui/DataSourceBadge.tsx
  git commit -m "Add frontend data provenance primitives"
  ```

---

## Task 2: Align the global shell without weakening auth or responsiveness

**Files:**

- Modify: `agentmesh-demo/src/components/layout/AppLayout.tsx`
- Modify: `agentmesh-demo/src/components/layout/Sidebar.tsx`
- Modify: `agentmesh-demo/src/components/layout/SettingsDrawer.tsx`
- Modify: `agentmesh-demo/src/components/ui/Tabs.tsx`
- Modify: `agentmesh-demo/src/components/ui/Modal.tsx`
- Modify: `agentmesh-demo/src/components/ui/Drawer.tsx`
- Test: `agentmesh-demo/e2e/reference-shell-parity.spec.ts`
- Reference: `/Users/heyunshen/Downloads/agentmesh-demo/src/components/layout/**`
- Reference: `/Users/heyunshen/Downloads/agentmesh-demo/src/components/ui/{Tabs,Modal,Drawer}.tsx`

**Interfaces:**

- Consumes real AuthProvider user/bootstrap/capabilities.
- Preserves mobile navigation and current admin capability routing.
- Produces the common 1240px reference content shell and reference navigation hierarchy.

- [ ] **Step 1: Write shell parity tests**

  Assertions at 1512px:

  - Main content max width is 1240px.
  - Sidebar width remains 260px.
  - Brand hierarchy and primary navigation text match the reference.
  - Real user, workspace badge, profile, settings and logout remain reachable.
  - Tabs support tablist/tab semantics and ArrowLeft/ArrowRight/Home/End.

  Assertions at 390px and 768px:

  - Mobile header and overlay remain operable.
  - Sidebar can open and close.
  - No horizontal overflow.

- [ ] **Step 2: Run RED**

  ```bash
  npm --prefix agentmesh-demo run test:e2e -- e2e/reference-shell-parity.spec.ts
  ```

- [ ] **Step 3: Align AppLayout and Sidebar**

  Restore reference width, spacing, brand and navigation hierarchy. Keep dynamic badges, capabilities, profile, logout, mobile overlay and AuthProvider behavior.

- [ ] **Step 4: Restore shared primitive semantics**

  Restore reference Tabs visuals and keyboard behavior. Restore Modal/Drawer focus management and title wiring. Keep current Drawer headerAction support.

- [ ] **Step 5: Verify**

  ```bash
  npm --prefix agentmesh-demo run test:e2e -- e2e/reference-shell-parity.spec.ts
  npm --prefix agentmesh-demo run test:e2e -- e2e/auth-shell.spec.ts
  npm --prefix agentmesh-demo run build
  ```

- [ ] **Step 6: Commit suggestion**

  ```bash
  git add agentmesh-demo/src/components/layout agentmesh-demo/src/components/ui agentmesh-demo/e2e/reference-shell-parity.spec.ts
  git commit -m "Align the authenticated shell with the reference UI"
  ```

---

## Task 3: Restore the DigitalSelf reference composition

**Files:**

- Create: `agentmesh-demo/src/features/digital-self/presenter.ts`
- Create: `agentmesh-demo/src/features/digital-self/presenter.test.ts`
- Modify: `agentmesh-demo/src/pages/DigitalSelf.tsx`
- Modify: `agentmesh-demo/src/components/digital-self/WelcomeHero.tsx`
- Modify: `agentmesh-demo/src/components/digital-self/UnderstandingList.tsx`
- Modify: `agentmesh-demo/src/components/digital-self/RecentGrowth.tsx`
- Modify: `agentmesh-demo/src/components/digital-self/MyImpact.tsx`
- Modify: `agentmesh-demo/src/components/digital-self/TodayWork.tsx` if it remains part of the reference composition.
- Test: `agentmesh-demo/e2e/reference-digital-self-parity.spec.ts`
- Reference: `/Users/heyunshen/Downloads/agentmesh-demo/src/pages/DigitalSelf.tsx`
- Reference: `/Users/heyunshen/Downloads/agentmesh-demo/src/components/digital-self/**`

**Presenter mapping:**

- Hero identity/project: T data from bootstrap.
- Hero narrative/participant count without backend aggregation: M data.
- Pending items: T data from visible Inbox/Task when present; otherwise reference M data.
- Understanding: T data from UserMemoryItem when present; otherwise reference M data.
- Growth: T data from memory overview; missing category breakdown fields use M data.
- Impact: future real reuse records; current reference values are M data.
- Agent identity/runtime/model: T data, shown without changing reference module order.

- [ ] **Step 1: Write Presenter RED tests**

  Cover all-real, all-mock, mixed, loading, error, empty-permission and unavailable aggregation cases. Assert exact M/T provenance per field.

- [ ] **Step 2: Implement DigitalSelf Presenter**

  The Presenter accepts bootstrap, Agent, activity, memory overview and reference Mock data. It returns a complete reference View Model even when real endpoints are empty.

- [ ] **Step 3: Restore reference page composition**

  Restore Hero, pending section and the three equal dynamic cards. Reattach MyImpact. Integrate the real Agent identity into the reference hierarchy rather than inserting a new top-level dashboard card.

- [ ] **Step 4: Add DataSourceBadge**

  Label each module or field according to Presenter provenance. Do not mark real identity/project as M data because the narrative is Mock.

- [ ] **Step 5: Browser verification**

  ```bash
  npm --prefix agentmesh-demo run test -- src/features/digital-self/presenter.test.ts
  npm --prefix agentmesh-demo run test:e2e -- e2e/reference-digital-self-parity.spec.ts
  npm --prefix agentmesh-demo run test:e2e -- e2e/workspace-mvp.spec.ts --grep "creates, selects|shows pending immediately"
  npm --prefix agentmesh-demo run build
  ```

- [ ] **Step 6: Commit suggestion**

  ```bash
  git add agentmesh-demo/src/features/digital-self agentmesh-demo/src/pages/DigitalSelf.tsx agentmesh-demo/src/components/digital-self agentmesh-demo/e2e/reference-digital-self-parity.spec.ts
  git commit -m "Restore the reference digital self experience"
  ```

---

## Task 4: Restore the Knowledge reference information architecture

**Files:**

- Create: `agentmesh-demo/src/features/knowledge/presenter.ts`
- Create: `agentmesh-demo/src/features/knowledge/presenter.test.ts`
- Modify: `agentmesh-demo/src/pages/Knowledge.tsx`
- Modify: `agentmesh-demo/src/components/knowledge/AssetsPanel.tsx`
- Modify: `agentmesh-demo/src/components/knowledge/AssetCard.tsx`
- Modify: `agentmesh-demo/src/components/knowledge/PendingCandidatePanel.tsx`
- Modify: `agentmesh-demo/src/components/knowledge/KnowledgeDetailDrawer.tsx`
- Modify: `agentmesh-demo/src/components/knowledge/ShareTimeline.tsx`
- Modify: `agentmesh-demo/src/components/knowledge/ConfirmKnowledgeModal.tsx`
- Keep or adapt: `KnowledgeCard.tsx`, `PendingKnowledgeCard.tsx`, `ReuseSection.tsx` as internal renderers if they earn their interface.
- Test: `agentmesh-demo/e2e/reference-knowledge-parity.spec.ts`
- Reference: `/Users/heyunshen/Downloads/agentmesh-demo/src/pages/Knowledge.tsx`
- Reference: `/Users/heyunshen/Downloads/agentmesh-demo/src/components/knowledge/**`

**Presenter mapping:**

- Reference “已沉淀知识”: UserMemoryItem, accepted MemoryItem and DocumentRecord。
- Reference “待我确认”: open InboxItem and proposed team_candidate MemoryItem。
- Reference “使用与反馈”: real reuse/feedback events when available; otherwise reference M timeline。
- All versions, allowed_actions and state transitions remain T data.

- [ ] **Step 1: Write Presenter RED tests**

  Cover five current resource sets mapping into three reference tabs. Assert resolved Inbox does not appear, team candidate stays pending, team accepted appears as asset, documents map to assets without fabricated memory fields, and missing reuse events fall back to M data.

- [ ] **Step 2: Restore reference three-tab shell**

  Keep URL tab synchronization. Default to “已沉淀知识”. Restore reference counts, panels and unified detail Drawer。

- [ ] **Step 3: Restore assets and filtering**

  Reuse AssetsPanel/AssetCard visuals. Presenter provides safe defaults for missing scope, limitation, citation and feedback fields, with M data labels next to only those fields.

- [ ] **Step 4: Preserve real governance**

  Confirm Brief with text and expected document version. Accept team candidates only when allowed_actions includes accept. Resolve/snooze/injection actions remain real. No DemoContext mutation.

- [ ] **Step 5: Restore usage timeline**

  Real events are T data. If unavailable, show the reference timeline as M data. M timeline actions remain disabled or explicitly marked demo; they cannot mutate backend state.

- [ ] **Step 6: Verify**

  ```bash
  npm --prefix agentmesh-demo run test -- src/features/knowledge/presenter.test.ts
  npm --prefix agentmesh-demo run test:e2e -- e2e/reference-knowledge-parity.spec.ts
  npm --prefix agentmesh-demo run test:e2e -- e2e/governance-collaboration-mvp.spec.ts --grep "Brief|candidate|version"
  npm --prefix agentmesh-demo run test:e2e -- e2e/workspace-mvp.spec.ts --grep "shows pending immediately"
  npm --prefix agentmesh-demo run build
  ```

- [ ] **Step 7: Commit suggestion**

  ```bash
  git add agentmesh-demo/src/features/knowledge agentmesh-demo/src/pages/Knowledge.tsx agentmesh-demo/src/components/knowledge agentmesh-demo/e2e/reference-knowledge-parity.spec.ts
  git commit -m "Restore the reference knowledge experience"
  ```

---

## Task 5: Restore Collaboration narrative over real Task and Post data

**Files:**

- Create: `agentmesh-demo/src/features/collaboration/presenter.ts`
- Create: `agentmesh-demo/src/features/collaboration/presenter.test.ts`
- Modify: `agentmesh-demo/src/pages/Collaboration.tsx`
- Modify: `agentmesh-demo/src/components/collaboration/MyCollabCard.tsx`
- Modify: `agentmesh-demo/src/components/collaboration/PeerCard.tsx`
- Modify: `agentmesh-demo/src/components/collaboration/HelpRequestCard.tsx`
- Modify: `agentmesh-demo/src/components/collaboration/CollabTimelineDrawer.tsx`
- Modify: `agentmesh-demo/src/features/collaboration/api.ts` only if an existing backend field is not exposed.
- Modify: `agentmesh-demo/src/features/knowledge/api.ts` only to reuse existing Inbox reads, not to duplicate them.
- Test: `agentmesh-demo/e2e/reference-collaboration-parity.spec.ts`
- Reference: `/Users/heyunshen/Downloads/agentmesh-demo/src/pages/Collaboration.tsx`
- Reference: `/Users/heyunshen/Downloads/agentmesh-demo/src/components/collaboration/**`

**Presenter mapping:**

- Task/Post status, stage, owner, lock, sources, actions: T data.
- upstream/downstream agents, actor and handoff: T data mapped to participants and contributions.
- Market counts/signals/matches/consent/participants: T data where returned.
- Ability percentages, period aggregates and unavailable matching reasons: M data.
- Inbox authorization: T data when a real Inbox resource and dedicated action exist; otherwise M display with no fake mutation.

- [ ] **Step 1: Write Presenter RED tests**

  Cover TaskCard to narrative card, Post timeline ordering, participant extraction, allowed action projection, Market aggregation fallback, authorization unavailable state and M/T provenance.

- [ ] **Step 2: Restore reference page structure**

  Restore network overview, capability distribution, participant groups, collaboration records and the reference tab hierarchy. Add Market as a secondary tab without replacing the main collaboration view.

- [ ] **Step 3: Restore narrative Drawer**

  Default view maps real posts into semantic steps with numbering, avatars, reason, contribution and result. Add a collapsed “技术详情” section for raw post_type, actor, owner, lock and done_when。

- [ ] **Step 4: Preserve real mutations**

  reply, handoff, lock, unlock and mark read remain visible only when allowed_actions permits. Mutation errors and optimistic state remain real.

- [ ] **Step 5: Restore application and authorization slots**

  Reuse real Inbox where possible. When approve/deny is not implemented, show “能力暂未接入”; do not replace it with generic resolve or local Toast success。

- [ ] **Step 6: Verify**

  ```bash
  npm --prefix agentmesh-demo run test -- src/features/collaboration/presenter.test.ts
  npm --prefix agentmesh-demo run test:e2e -- e2e/reference-collaboration-parity.spec.ts
  npm --prefix agentmesh-demo run test:e2e -- e2e/governance-collaboration-mvp.spec.ts
  npm --prefix agentmesh-demo run test:e2e -- e2e/workspace-mvp.spec.ts --grep "shows pending immediately"
  npm --prefix agentmesh-demo run build
  ```

- [ ] **Step 7: Commit suggestion**

  ```bash
  git add agentmesh-demo/src/features/collaboration agentmesh-demo/src/pages/Collaboration.tsx agentmesh-demo/src/components/collaboration agentmesh-demo/e2e/reference-collaboration-parity.spec.ts
  git commit -m "Restore the reference collaboration narrative"
  ```

---

## Task 6: Restore the Insights product narrative with honest fallbacks

**Files:**

- Create: `agentmesh-demo/src/features/insights/presenter.ts`
- Create: `agentmesh-demo/src/features/insights/presenter.test.ts`
- Modify: `agentmesh-demo/src/pages/Insights.tsx`
- Modify: `agentmesh-demo/src/components/insights/ReadModelPanels.tsx`
- Modify: `agentmesh-demo/src/components/insights/ProjectReviewDrawer.tsx`
- Create or restore focused reference modules under `agentmesh-demo/src/components/insights/` rather than leaving a 500-line page.
- Test: `agentmesh-demo/e2e/reference-insights-parity.spec.ts`
- Reference: `/Users/heyunshen/Downloads/agentmesh-demo/src/pages/Insights.tsx`

**Presenter mapping:**

- Current project, tasks, activity, memory and audit: T data.
- Cross-project pattern, historical review, KPI, evidence narrative and Workflow recommendation: M data until backend models exist.
- Audit remains a detail/evidence surface, not the primary product module.

- [ ] **Step 1: Write Presenter RED tests**

  Cover current project facts, Task/Activity/Memory/Audit mapping, missing insight/KPI fallback, M/T provenance, endpoint failure and permission-empty behavior.

- [ ] **Step 2: Restore the reference vertical information architecture**

  Restore work overview, insight card, historical review, evidence and knowledge formation sections. Keep the current read models as inputs and details, not as four top-level equal cards.

- [ ] **Step 3: Restore reference interactions honestly**

  Source chips can open real details where possible. Mock review/Workflow actions display M data and “能力暂未接入”; they cannot create local success state。

- [ ] **Step 4: Retain operational diagnostics as secondary content**

  Move raw Task/Activity/Audit panels into drawers, expandable evidence or a secondary section. Do not expose project IDs and English technical labels in the main visual hierarchy.

- [ ] **Step 5: Verify**

  ```bash
  npm --prefix agentmesh-demo run test -- src/features/insights/presenter.test.ts
  npm --prefix agentmesh-demo run test:e2e -- e2e/reference-insights-parity.spec.ts
  npm --prefix agentmesh-demo run test:e2e -- e2e/read-model-admin-mvp.spec.ts
  npm --prefix agentmesh-demo run test:e2e -- e2e/workspace-mvp.spec.ts --grep "shows pending immediately"
  npm --prefix agentmesh-demo run build
  ```

- [ ] **Step 6: Commit suggestion**

  ```bash
  git add agentmesh-demo/src/features/insights agentmesh-demo/src/pages/Insights.tsx agentmesh-demo/src/components/insights agentmesh-demo/e2e/reference-insights-parity.spec.ts
  git commit -m "Restore the reference insights narrative"
  ```

---

## Task 7: Cross-page visual parity and non-regression gate

**Files:**

- Create: `agentmesh-demo/e2e/reference-visual-parity.spec.ts`
- Modify: `agentmesh-demo/e2e/mvp-parity.spec.ts`
- Modify: `agentmesh-demo/e2e/workspace-mvp.spec.ts` only to add regression coverage, never to weaken existing assertions.
- Modify: `README.md` and `CONTEXT.md` after implementation to document M/T semantics and completed pages.

- [ ] **Step 1: Capture reference checkpoints**

  At 1512px record module order, headings, key card counts, Drawer titles and representative screenshots for DigitalSelf, Insights, Knowledge and Collaboration. Store only stable reference screenshots needed by Playwright.

- [ ] **Step 2: Add structural parity assertions**

  Assert module order, page headings, tab labels, Drawer entry points and M/T labels. Avoid pixel assertions for dynamic text and counts.

- [ ] **Step 3: Add M/T integrity assertions**

  - Every Mock fallback module contains `M数据`.
  - Every real-only module contains `T数据`.
  - Mixed modules expose field-level labels.
  - No mutation button exists on a Mock-only capability.

- [ ] **Step 4: Run the complete frontend gate**

  ```bash
  npm --prefix agentmesh-demo run test
  npm --prefix agentmesh-demo run build
  npm --prefix agentmesh-demo run test:e2e -- e2e/auth-shell.spec.ts
  npm --prefix agentmesh-demo run test:e2e -- e2e/workspace-mvp.spec.ts
  npm --prefix agentmesh-demo run test:e2e -- e2e/reference-shell-parity.spec.ts
  npm --prefix agentmesh-demo run test:e2e -- e2e/reference-digital-self-parity.spec.ts
  npm --prefix agentmesh-demo run test:e2e -- e2e/reference-knowledge-parity.spec.ts
  npm --prefix agentmesh-demo run test:e2e -- e2e/reference-collaboration-parity.spec.ts
  npm --prefix agentmesh-demo run test:e2e -- e2e/reference-insights-parity.spec.ts
  npm --prefix agentmesh-demo run test:e2e -- e2e/reference-visual-parity.spec.ts
  ```

- [ ] **Step 5: Run backend gates covering real mutations**

  ```bash
  .venv/bin/python -m pytest tests/test_frontend_contracts.py tests/test_read_models.py tests/test_chat_flow.py -q
  .venv/bin/ruff check agentmesh tests
  ```

  If the known `test_chat_data_query_denies_disabled_grant_before_connector` fixture failure still exists, isolate and resolve it as a separate test hygiene task before claiming the full backend suite is green.

- [ ] **Step 6: Manual responsive acceptance**

  At 390px, 768px and 1512px verify:

  - No horizontal overflow.
  - Sidebar/mobile navigation works.
  - M/T labels remain legible without dominating cards.
  - Drawers and modals fit the viewport.
  - Workspace pending, auto-scroll and `$` Skill remain operational.

- [ ] **Step 7: Update product reality docs**

  Document which modules are T data, M data or mixed, and list backend gaps that still require Mock fallback.

- [ ] **Step 8: Commit suggestion**

  ```bash
  git add agentmesh-demo/e2e README.md CONTEXT.md
  git commit -m "Add reference UI parity gates"
  ```

---

## Delivery order

1. Task 1, provenance foundation.
2. Task 2, global shell.
3. Task 3, DigitalSelf.
4. Task 4, Knowledge.
5. Task 5, Collaboration.
6. Task 6, Insights.
7. Task 7, whole-frontend gate.

Each task is independently mergeable. If later tasks stop, completed pages remain usable and real mutations remain intact.

## Rollback

All changes are front-end presentation and test changes. Roll back one page by restoring its current endpoint-shaped page and removing only that page Presenter. Do not roll back backend data, permissions or state. `DataSourceBadge` can remain even if a page Presenter is reverted.
