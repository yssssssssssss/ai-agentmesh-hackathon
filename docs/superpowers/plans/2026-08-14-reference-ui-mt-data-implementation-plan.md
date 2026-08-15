# AgentMesh Reference UI and M/T Data Optimized Implementation Plan

> **For agentic workers:** Use subagent-driven development. Wave 2 contains four isolated page tasks that may run in parallel after Wave 1 freezes shared interfaces.

**Goal:** 在不修改聊天与后端状态机的前提下，把 DigitalSelf、Knowledge、Collaboration、Insights 恢复到参考 Mock 前端的视觉和产品结构，并对展示字段使用 `M数据`、`T数据` 标识。

**Architecture:** FastAPI 和 SQLite 继续提供身份、权限、状态和 mutation。页面 Presenter 把真实查询与参考 Mock 合成为 Reference View Model。公共 M/T 接口在 Wave 1 冻结，四个页面在 Wave 2 并行实现，Wave 3 统一验收。

**Design:** `docs/superpowers/specs/2026-08-14-reference-ui-mt-data-design.md`

**Tech Stack:** React 18、TypeScript 5.6、TanStack Query 5、Vitest 2、Playwright 1.48、Vite 5、Tailwind 3。

## Execution Order Override

用户已要求先完成全部页面修改，最终验证改由真人执行。Wave 2 reviewer 修复完成后，停止自动测试、build、Playwright 和截图对比。原 Wave 3 自动门禁保留为历史计划，不再由 Agent 执行。人工验收入口：`docs/superpowers/plans/2026-08-14-reference-ui-mt-data-human-acceptance.md`。

## Global Constraints

- `/Users/heyunshen/Downloads/agentmesh-demo/` 是视觉和产品内容基线。
- FastAPI、SQLite、权限、版本和 allowed_actions 是唯一业务事实源。
- 标签只使用 `M数据` 和 `T数据`。
- Mock 只补展示，不得模拟真实 mutation 成功。
- AI 工作台和聊天后端是冻结区，不修改业务逻辑。
- 验证工具只使用 Vitest、Vite build、Playwright。
- 每个波次最多运行一次完整 build 和一次 Workspace 聚焦回归。
- 默认不运行后端全量测试；仅在确实修改后端时运行对应聚焦测试。
- Wave 2 的页面任务不得修改 Wave 1 冻结的公共文件。

---

## Wave 0: Freeze the implementation baseline

**Purpose:** 消除并行修改、参考版本漂移和 Agent 重复探索。

**Files:**

- Create: `docs/superpowers/specs/2026-08-14-reference-ui-mt-data-baseline.md`
- Create: `agentmesh-demo/e2e/reference-baselines/manifest.json`
- Create: `agentmesh-demo/e2e/reference-baselines/` 下稳定截图
- Read only: 当前 Git 状态、参考项目、当前四个页面和 Workspace

- [ ] **Record repository state**

  记录：

  ```bash
  git rev-parse HEAD
  git status --short --branch -uall
  ```

  文档中列出当前分支、HEAD、已修改文件、未跟踪文件和当前运行端口。

- [ ] **Freeze reference files**

  对参考项目中的以下文件生成 SHA-256：

  - `src/App.tsx`
  - `src/index.css`
  - `tailwind.config.js`
  - `src/components/layout/**`
  - `src/components/ui/**`
  - `src/pages/{DigitalSelf,Knowledge,Collaboration,Insights}.tsx`
  - 四个页面对应的组件目录
  - `src/data/mockData.ts`

  将路径和校验值写入 `manifest.json`。

- [ ] **Capture reference screenshots once**

  在 1512px 捕获：

  - DigitalSelf
  - Knowledge 三个 Tab
  - Collaboration 主页面和详情 Drawer
  - Insights 主页面和代表性 Drawer

  只保存稳定页面，不捕获动态时间、随机 ID 和动画帧。

- [ ] **Run baseline gates once**

  ```bash
  npm --prefix agentmesh-demo run build
  npm --prefix agentmesh-demo run test:e2e -- e2e/workspace-mvp.spec.ts --grep "creates, selects|shows pending immediately"
  ```

- [ ] **Create a baseline checkpoint after explicit authorization**

  未取得提交授权时，只记录建议命令，不执行：

  ```bash
  git add agentmesh-demo docs/superpowers/specs docs/superpowers/plans
  git commit -m "Checkpoint reference UI migration baseline"
  ```

**Exit criteria:** 当前代码、参考文件、参考截图和 Workspace 行为都有不可歧义的基线。

---

## Wave 1: Build and freeze shared presentation foundations

**Purpose:** 公共接口只实现一次，避免四个页面重复读写和相互覆盖。

**Files:**

- Create: `agentmesh-demo/src/lib/presentation.ts`
- Create: `agentmesh-demo/src/lib/presentation.test.ts`
- Create: `agentmesh-demo/src/components/ui/DataSourceBadge.tsx`
- Modify: `agentmesh-demo/src/components/layout/AppLayout.tsx`
- Modify: `agentmesh-demo/src/components/layout/Sidebar.tsx`
- Modify: `agentmesh-demo/src/components/layout/SettingsDrawer.tsx`
- Modify: `agentmesh-demo/src/components/ui/Tabs.tsx`
- Modify: `agentmesh-demo/src/components/ui/Modal.tsx`
- Modify: `agentmesh-demo/src/components/ui/Drawer.tsx`
- Create: `agentmesh-demo/e2e/reference-shell-parity.spec.ts`

**Produces:**

- `DataSourceKind = 'M' | 'T'`
- `PresentedValue<T>`
- `PresentedModule<T>`
- `DataSourceBadge`
- 参考宽度、侧栏层级、Tabs 语义和 Modal/Drawer focus 行为

- [ ] **Write one table-driven Presenter foundation test**

  覆盖：

  - T 数据原样保留。
  - 真实值缺失时允许 M 数据 fallback。
  - mixed 字段保留各自来源。
  - 权限空结果和错误不能触发 Mock fallback。
  - 未知 source 直接报错，不静默转成 M 数据。

- [ ] **Run the focused RED test**

  ```bash
  npm --prefix agentmesh-demo run test -- src/lib/presentation.test.ts
  ```

- [ ] **Implement presentation primitives and DataSourceBadge**

  `DataSourceBadge` 只显示 `M数据` 或 `T数据`，并提供同名 aria-label。组件复用现有 Badge，不修改 Badge 默认样式。

- [ ] **Align the shell once**

  - 普通内容宽度恢复参考 `1240px`。
  - 保留 AuthProvider、QueryClient、capability、移动导航、Profile、真实退出。
  - 恢复参考品牌和导航视觉层级。
  - Tabs 恢复参考 active 样式和键盘行为。
  - Modal/Drawer 恢复 focus trap 和标题关联。

- [ ] **Run Wave 1 verification once**

  ```bash
  npm --prefix agentmesh-demo run test -- src/lib/presentation.test.ts
  npm --prefix agentmesh-demo run build
  npm --prefix agentmesh-demo run test:e2e -- e2e/reference-shell-parity.spec.ts
  npm --prefix agentmesh-demo run test:e2e -- e2e/workspace-mvp.spec.ts --grep "shows pending immediately"
  ```

- [ ] **Freeze shared ownership**

  Wave 2 页面 Agent 禁止修改：

  - `src/lib/presentation.ts`
  - `src/components/ui/DataSourceBadge.tsx`
  - `src/components/layout/**`
  - `src/components/ui/Tabs.tsx`
  - `src/components/ui/Modal.tsx`
  - `src/components/ui/Drawer.tsx`
  - `src/pages/Workspace.tsx`
  - `src/components/workspace/**`
  - `src/features/workspace/**`

**Exit criteria:** 公共接口、壳层和 M/T 视觉均已通过一次构建和浏览器门禁，之后不再由页面任务修改。

---

## Wave 2: Implement four page presenters in parallel

**Purpose:** 四个页面共享冻结接口，但文件所有权完全隔离。

### Page A: DigitalSelf

**Owned files:**

- `agentmesh-demo/src/features/digital-self/presenter.ts`
- `agentmesh-demo/src/features/digital-self/presenter.test.ts`
- `agentmesh-demo/src/pages/DigitalSelf.tsx`
- `agentmesh-demo/src/components/digital-self/**`

**Requirements:**

- 恢复参考 Hero、待处理事项、理解、成长、影响三卡结构。
- 用户、Workspace、Project、Agent、Activity、Memory overview 使用 T 数据。
- 后端缺少的推进叙事、参与人数、影响力聚合使用 M 数据。
- 恢复 MyImpact 挂载。
- 权限空结果不使用 Mock 补齐。

- [ ] Write Presenter tests for all-real, mixed, all-display-fallback, loading, error and permission-empty.
- [ ] Implement Presenter and reference composition.
- [ ] Add module/field M/T labels.
- [ ] Run only `src/features/digital-self/presenter.test.ts`.

### Page B: Knowledge

**Owned files:**

- `agentmesh-demo/src/features/knowledge/presenter.ts`
- `agentmesh-demo/src/features/knowledge/presenter.test.ts`
- `agentmesh-demo/src/pages/Knowledge.tsx`
- `agentmesh-demo/src/components/knowledge/**`

**Requirements:**

- 恢复“已沉淀知识、待我确认、使用与反馈”三类用户心智。
- UserMemory、accepted Memory、Document、Inbox、team candidate 使用 T 数据。
- 缺少真实 reuse/feedback 时使用 M Timeline，并禁用 Mock mutation。
- 保留版本检查、Brief 确认、candidate accept、Inbox allowed actions。
- 恢复 AssetsPanel、筛选、详情 Drawer 和参考卡片视觉。

- [ ] Write mapping and mutation-visibility Presenter tests.
- [ ] Implement three-tab View Model and reference components.
- [ ] Add M/T labels without changing real mutations.
- [ ] Run only `src/features/knowledge/presenter.test.ts`.

### Page C: Collaboration

**Owned files:**

- `agentmesh-demo/src/features/collaboration/presenter.ts`
- `agentmesh-demo/src/features/collaboration/presenter.test.ts`
- `agentmesh-demo/src/pages/Collaboration.tsx`
- `agentmesh-demo/src/components/collaboration/**`

**Requirements:**

- 恢复网络概览、能力分布、参与人、协作记录和参考 Tabs。
- Task/Post/status/owner/lock/source/allowed_actions 使用 T 数据。
- upstream/downstream/actor/handoff 映射成参与人和贡献。
- 缺少的比例、周期聚合、匹配原因使用 M 数据。
- Drawer 默认是用户叙事，原始 Task/Post 放入“技术详情”。
- reply、handoff、lock、unlock、read 保持真实。

- [ ] Write Task/Post/Market/Inbox Presenter tests.
- [ ] Implement reference page structure and narrative Drawer.
- [ ] Add M/T labels and preserve allowed actions.
- [ ] Run only `src/features/collaboration/presenter.test.ts`.

### Page D: Insights

**Owned files:**

- `agentmesh-demo/src/features/insights/presenter.ts`
- `agentmesh-demo/src/features/insights/presenter.test.ts`
- `agentmesh-demo/src/pages/Insights.tsx`
- `agentmesh-demo/src/components/insights/**`

**Requirements:**

- 恢复近期工作、洞察、历史复盘、依据和知识形成的纵向结构。
- Project、Task、Activity、Memory、Audit 使用 T 数据。
- 跨项目规律、KPI、复盘建议、Workflow 推荐使用 M 数据。
- Mock 操作显示“能力暂未接入”，不得修改本地业务状态。
- 原始 Task/Audit 面板下沉到详情或折叠区。

- [ ] Write current-facts and fallback Presenter tests.
- [ ] Implement reference information architecture.
- [ ] Add M/T labels and honest unavailable actions.
- [ ] Run only `src/features/insights/presenter.test.ts`.

### Wave 2 integration

四个页面 Agent 完成后，由主会话统一执行：

- [ ] Resolve only page-local merge conflicts. Shared frozen files must remain unchanged.
- [ ] Run all four Presenter tests in one Vitest command.
- [ ] Run one production build.
- [ ] Create and run one combined `reference-pages-smoke.spec.ts` at 1512px.
- [ ] Run one Workspace focused regression.

```bash
npm --prefix agentmesh-demo run test -- \
  src/features/digital-self/presenter.test.ts \
  src/features/knowledge/presenter.test.ts \
  src/features/collaboration/presenter.test.ts \
  src/features/insights/presenter.test.ts
npm --prefix agentmesh-demo run build
npm --prefix agentmesh-demo run test:e2e -- e2e/reference-pages-smoke.spec.ts
npm --prefix agentmesh-demo run test:e2e -- e2e/workspace-mvp.spec.ts --grep "shows pending immediately"
```

**Exit criteria:** 四个页面在 1512px 具备参考模块结构和正确 M/T 标识，Workspace 不回归。

---

## Wave 3: Final integration and minimal release gate

**Purpose:** 一次性完成最终功能、视觉和响应式检查，不重复各页面局部验证。

**Files:**

- Modify: `agentmesh-demo/e2e/reference-pages-smoke.spec.ts`
- Create: `agentmesh-demo/e2e/reference-visual-parity.spec.ts`
- Modify: `agentmesh-demo/e2e/mvp-parity.spec.ts`
- Modify: `README.md`
- Modify: `CONTEXT.md`

- [ ] **Run Vitest once**

  ```bash
  npm --prefix agentmesh-demo run test
  ```

- [ ] **Run production build once**

  ```bash
  npm --prefix agentmesh-demo run build
  ```

- [ ] **Run the minimum browser gate**

  ```bash
  npm --prefix agentmesh-demo run test:e2e -- \
    e2e/auth-shell.spec.ts \
    e2e/reference-pages-smoke.spec.ts \
    e2e/workspace-mvp.spec.ts
  ```

  Knowledge 和 Collaboration 的真实 mutation 只运行代表性用例：

  ```bash
  npm --prefix agentmesh-demo run test:e2e -- \
    e2e/governance-collaboration-mvp.spec.ts \
    --grep "Brief|candidate|handoff|lock"
  ```

- [ ] **Run visual comparison once**

  - 1512px 对比 DigitalSelf、Knowledge、Collaboration、Insights 和代表性 Drawer。
  - 390px、768px 只检查导航、溢出、Drawer/Modal 和关键按钮。
  - 不对动态数值、时间和服务端文本做像素断言。

- [ ] **Check M/T integrity once**

  - Mock fallback 模块有 `M数据`。
  - 真实模块有 `T数据`。
  - mixed 模块对 Mock 字段单独标注。
  - Mock-only 模块没有可修改服务端状态的按钮。

- [ ] **Backend tests only if backend changed**

  如果整个实施只改前端，跳过 pytest 和后端 Ruff。如果某页需要新后端字段，只运行对应 route/state tests，不运行全套后端测试。

- [ ] **Update product reality docs**

  README 和 CONTEXT 记录：

  - 哪些模块是 T 数据。
  - 哪些模块是 M 数据。
  - 哪些模块 mixed。
  - 哪些真实能力仍未接入。
  - Workspace 隔离边界和回归命令。

**Final exit criteria:** 参考结构、M/T 诚信、真实 mutation、响应式和 Workspace 核心行为均通过一套最小门禁。

---

## Toolchain policy

实施只使用：

- Read/Edit/Write 完成代码变更。
- Vitest 验证 Presenter。
- Vite build 验证 TypeScript 和生产构建。
- Playwright 验证用户行为、视觉结构和响应式。

不使用：

- 多套浏览器自动化工具重复验证同一页面。
- 每个页面完成后重复完整 build。
- 每个页面完成后重复 Workspace E2E。
- 纯前端变更触发全量后端测试。
- 为 Presenter 映射编写 E2E。
- 对动态服务端内容做脆弱的像素级断言。

## Rollback

- Wave 1 可整体回滚公共壳层和 Presentation primitives。
- Wave 2 每个页面独立回滚，不影响其他页面和后端状态。
- Wave 3 只包含测试和文档，可独立回滚。
- 任何回滚不得修改 SQLite 数据。
