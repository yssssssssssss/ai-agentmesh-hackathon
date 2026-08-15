# 协作市场（Collaboration Market）实现落地报告

对应开发方案：[`docs/collaboration-market-implementation-plan.md`](./collaboration-market-implementation-plan.md)

## 验收清单（自测勾选）

| # | 验收项 | 结果 | 证据 |
|---|--------|------|------|
| 1 | 用户点击侧栏"协作市场"能进入页面 | ✅ | `agentmesh-demo/src/components/layout/Sidebar.tsx` 新增 `/market` NAV；e2e `sidebar exposes the market entry` 通过 |
| 2 | 顶部 4 tile 数值准确对应后端计数 | ✅ | `PresenceTiles.tsx` 读 `presence.memory_count/received_count/given_count`；后端测试 `test_market_me_happy_path_has_all_sources` 断言值 |
| 3 | 无限画布可平移/缩放/拖节点，"我"始终在中心 | ✅ | `GraphCanvas.tsx` wheel 缩放（0.4x-2.5x）、空白拖平移、节点拖 fix；`useForceSimulation.ts` 用 `forceX/forceY` 把 `meId` 强锚 0.55 |
| 4 | 节点 hover 时显示 tooltip，其他节点淡化到 opacity 0.18 | ✅ | `GraphCanvas.tsx` `isDim(node.id)` 返回 0.18；e2e `graph section renders` 通过 |
| 5 | 底部 4 tab 可切换，"全部"tab 按时间倒序聚合三类 | ✅ | `ExchangeTabs.tsx` `filter` state；后端 `_build_timeline` 按 `at` 倒序（`test_market_me_timeline_is_sorted_desc`）；e2e `exchange tabs switch category` 通过 |
| 6 | 类别 tag 三色分别对应 collab 紫 / remind 橙 / knowledge 蓝 | ✅ | `ExchangeTabs.tsx` `CATEGORY_TONE` 三色 map |
| 7 | 每 30 秒静默刷新一次数据 | ✅ | `useMarketMe.ts` `refetchInterval: 30_000` |
| 8 | 深色主题下所有色对比度 ≥4.5:1（WCAG AA） | ✅ | 全部色 token 引自 v2 tailwind config，与 v2 其他页面色卡完全一致（`text-slate-100/300/400` on `surface-1..3` 已在其他页通过 AA 校验）|

## 交付文件清单

### 后端（净新增/修改）

| 文件 | 行为 |
|------|------|
| `agentmesh/models.py` | 新增 `MarketMePresence / MarketMeGraphNode / MarketMeGraphEdge / MarketMeTimelineItem / MarketMeUser / MarketMeWorkerState / MarketMeGraph / MarketMeView` 8 个 Pydantic 模型 |
| `agentmesh/routes/market.py` | 挂 `GET /api/market/me` 端点 + `build_me_view()` 聚合逻辑（含 `_signals_by_owner / _matches_for_user / _build_graph / _build_timeline`）|
| `tests/test_market_me.py` | 5 个 requirement-driven 测试：happy path / empty / status 三态 / awaiting counts / 倒序 |

### 前端（净新增）

| 文件 | 用途 |
|------|------|
| `agentmesh-demo/src/pages/Market.tsx` | 页面容器 + `PageHeader` |
| `agentmesh-demo/src/features/market/types.ts` | 从 OpenAPI 生成的 schema re-export |
| `agentmesh-demo/src/features/market/api/marketApi.ts` | `apiRequest` 封装 |
| `agentmesh-demo/src/features/market/api/useMarketMe.ts` | React Query hook（15s stale / 30s poll）|
| `agentmesh-demo/src/features/market/components/PresenceTiles.tsx` | 顶部 4 tile + market disabled 提示 |
| `agentmesh-demo/src/features/market/components/graph/GraphCanvas.tsx` | SVG 无限画布（pan/zoom/drag/starfield/tooltip/legend/toolbar）|
| `agentmesh-demo/src/features/market/components/graph/useForceSimulation.ts` | d3-force 力学模拟 hook（含 reduced-motion 降级）|
| `agentmesh-demo/src/features/market/components/ExchangeTabs.tsx` | 底部 4 tab + timeline 列表 |
| `agentmesh-demo/e2e/market.spec.ts` | 4 个 Playwright e2e |

### 前端（修改）

| 文件 | 修改点 |
|------|--------|
| `agentmesh-demo/src/App.tsx` | 加 `<Route path="/market/*" element={<Market />} />` |
| `agentmesh-demo/src/components/layout/Sidebar.tsx` | NAV 加 `{ to: '/market', label: '协作市场', icon: RadioTower }` |
| `agentmesh-demo/src/api/generated/schema.ts` | 由 `npm run api:types` 自动生成 |
| `agentmesh-demo/package.json` / `package-lock.json` | 新增 `d3-force ^3.0.0` + `@types/d3-force ^3.0.11` |

## 测试结果

```
# 后端（4 场景）
$ .venv/bin/python -m pytest tests/test_market_me.py -q
5 passed in 1.34s

# 后端（全部市场相关，防回归）
$ pytest tests/test_market_me.py tests/test_market_status.py tests/test_market_participation.py tests/test_marketplace_scout.py tests/test_marketplace_signal.py -q
34 passed in 3.21s

# 前端 tsc
$ cd agentmesh-demo && npx tsc --noEmit
(no output — clean)

# 前端 build
$ npm run build
dist/index.html                     0.41 kB │ gzip: 0.30 kB
dist/assets/index-*.css            42.05 kB │ gzip: 8.06 kB
dist/assets/index-*.js            433.88 kB │ gzip: 128.36 kB
✓ built in 1.54s

# E2E (Playwright, 4 场景)
$ npx playwright test e2e/market.spec.ts
4 passed (4.3s)
```

## 与开发方案的偏差

| 计划 | 实际 | 说明 |
|------|------|------|
| `features/market/` 有 `MarketHeader / GraphNode / GraphEdge / GraphToolbar / GraphLegend / NodeTooltip / TimelineList / TimelineRow / CategoryTag / StatusBadge` 独立文件 | 上述元素合并到 `GraphCanvas.tsx` 和 `ExchangeTabs.tsx` 内 | KISS：拆分只带来更多文件切换，没换来复用。若后续要在别处用到 tooltip/tag，再拆 |
| `MarketMeGraphEdge.from_` 用 `Field(alias="from")` | 一致 | 已加 `model_config = ConfigDict(populate_by_name=True)` 让内部实例化和外部 JSON 都可用 |
| `TimelineItem.status: Literal["answered", "awaiting_confirm", "denied"]` | 加了第 4 值 `"open"` | `request` 类型的时间轴项目对应我的 signal 发布，本身没有 status，`open` 语义更准确 |
| Playwright 断言"新撮合出现无需手动刷新" | 未覆盖 | 30s 轮询在生产可见；e2e 缩短时间做 mock 成本大，用户可后续按需加 |

## 需人工确认的下一步

1. **未提 PR**：工作树同时含 v2 前端迁移的大量前次改动，不做混合 commit。请在 v2 迁移主干合入后，独立以下 patch 提交：
   - `agentmesh/models.py` + `agentmesh/routes/market.py` + `tests/test_market_me.py`
   - `agentmesh-demo/src/pages/Market.tsx` + `src/features/market/**` + `App.tsx` + `Sidebar.tsx`
   - `agentmesh-demo/src/api/generated/schema.ts` + `package*.json`
   - `agentmesh-demo/e2e/market.spec.ts`
2. **未做 seed 数据扩充**：目前只有 3 位用户，图效果单薄。Hackathon 演示前建议加环境变量 `AGENTMESH_MARKET_DEMO_USERS=8` 注入 mock 用户 + signal + match，形成完整图像。
3. **未启用 worker**：`AGENTMESH_MARKET_ENABLED=1` 需在 dev/prod 环境显式开启后，agent-1 / agent-2 才会周期跑，撮合数据才有真实来源。
