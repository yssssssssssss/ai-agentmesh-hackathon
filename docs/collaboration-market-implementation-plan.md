# 协作市场（Collaboration Market）开发方案

**目标**：将现有 `docs/collaboration-market-demo.html` 落地为 `agentmesh-demo/` 中的一个功能模块，对接现有的 `agentmesh` 后端 `MARKETPLACE_SIGNAL / MARKETPLACE_MATCH` 能力，让员工看到自己在自主协作市场中的位置。

---

## 一、总体判断

后端能力已就绪，工作重心在前端 + 一个新的后端聚合端点。整体工作量约 **3 – 4 人日**。

| 层 | 现状 | 需要做的事 |
|----|------|-----------|
| 后端能力（agent-1 / agent-2 worker） | ✅ 完整实现，测试覆盖齐全 | 无 |
| 后端 API | ✅ `/api/market/board` / `/status` / `/participation` 已存在 | 新增 `/api/market/me` 个人视角聚合端点 |
| 前端组件 | ❌ 目前 `agentmesh-demo/` 无协作市场页面 | 新建 `features/market/` 模块（页面 + 组件 + Query hooks） |
| 路由 | ❌ | 在 `App.tsx` 加 `/market` 路由，在侧栏加入口 |
| 类型契约 | ⚠️ `openapi-typescript` 已配置（见 `package.json` 的 `api:types` 脚本） | 后端 API 补完后执行 `pnpm api:types` 自动生成 |

---

## 二、后端补充 · 新增一个聚合端点

**为什么需要新端点**：现有的 `/api/market/board` 是"全市场"视角，个人页需要过滤到"我"的视角，并额外提供图数据。前端一次请求拿齐所有页面数据，无逻辑碎片。

### 端点定义

```
GET /api/market/me
Authorization: session cookie (current_user)

Response 200:
{
  "user": {
    "id": "user_chen",
    "name": "陈莉",
    "group": "家电设计组"
  },
  "presence": {
    "memory_count": 12,
    "signal_on": true,
    "signal_refreshed_at": "2026-08-14T10:32:00Z",
    "received_count": 2,
    "given_count": 3
  },
  "workers": {
    "publish": { "running": true, "interval_seconds": 300, "last_run_at": "..." },
    "scout":   { "running": true, "interval_seconds": 300, "last_run_at": "..." }
  },
  "graph": {
    "nodes": [
      {
        "id": "user_chen",
        "name": "陈莉",
        "group": "家电设计组",
        "size": 26,
        "tie_role": "me",   /* me | incoming | outgoing | peer */
        "offer": "家电大促首屏改版方案",
        "need": "大促核心指标口径与解读",
        "ties": 5
      },
      ...
    ],
    "edges": [
      { "from": "user_li", "to": "user_chen", "direction": "incoming" },
      { "from": "user_chen", "to": "user_sun", "direction": "outgoing" },
      { "from": "user_lin", "to": "user_zhou", "direction": "peer" },
      ...
    ]
  },
  "timeline": [
    {
      "id": "match_1",
      "at": "2026-08-14T10:44:22Z",
      "category": "incoming",  /* incoming | outgoing | request */
      "title": "李默的分身回答了《大促核心指标口径与解读》",
      "counterpart": { "id": "user_li", "name": "李默" },
      "topic": "大促核心指标口径与解读",
      "status": "answered",    /* answered | awaiting_confirm | denied */
      "sensitivity": "low",
      "meta": "agent-2 · scout · marketplace_match"
    },
    ...
  ]
}
```

### 实现位置

新增文件：`agentmesh/routes/market_me.py`（也可以直接加到现有 `market.py` 里，看模块规模）

关键函数：
```python
def build_me_view(user: User, store: SQLiteStore) -> MeView:
    # 1. presence: 计数 audit_events where action="marketplace_match"
    #    并按 metadata.helper == user.id / target_id == user.id 分类
    # 2. graph.nodes: list_users(store) + is_market_participant 过滤
    #    tie_role 相对当前 user 计算
    # 3. graph.edges: 从 blackboard_posts (MARKETPLACE_MATCH type) 提取
    # 4. timeline: 合并三类事件按时间倒序
    #    - request: bb_signal_{user.id} 的 created_at
    #    - incoming: audit_events where target_id == user.id
    #    - outgoing: audit_events where metadata.helper == user.id
```

### 需要的 Pydantic 模型（`agentmesh/models.py` 补充）

```python
class MarketMePresence(BaseModel):
    memory_count: int
    signal_on: bool
    signal_refreshed_at: datetime | None
    received_count: int
    given_count: int

class MarketMeGraphNode(BaseModel):
    id: str
    name: str
    group: str
    size: int
    tie_role: Literal["me", "incoming", "outgoing", "peer"]
    offer: str
    need: str
    ties: int

class MarketMeGraphEdge(BaseModel):
    from_: str = Field(alias="from")
    to: str
    direction: Literal["incoming", "outgoing", "peer"]

class MarketMeTimelineItem(BaseModel):
    id: str
    at: datetime
    category: Literal["request", "incoming", "outgoing"]
    title: str
    counterpart: dict[str, str] | None
    topic: str
    status: Literal["answered", "awaiting_confirm", "denied"]
    sensitivity: Literal["low", "medium", "high"]
    meta: str

class MarketMeView(BaseModel):
    user: UserPublic
    presence: MarketMePresence
    workers: dict[str, Any]
    graph: dict[str, list]
    timeline: list[MarketMeTimelineItem]
```

**工作量**：1 人日（含单元测试）

---

## 三、前端目录组织

延续 v2 项目已建立的 `features/*` 模式（`features/collaboration`、`features/knowledge` 已存在）：

```
agentmesh-demo/src/
├── pages/
│   └── Market.tsx                              # 新增 · 页面容器
├── features/
│   └── market/                                 # 新增
│       ├── api/
│       │   └── useMarketMe.ts                  # React Query hook: /api/market/me
│       ├── components/
│       │   ├── MarketHeader.tsx                # 顶部标题 + user badge
│       │   ├── PresenceTiles.tsx               # 4 个 tile
│       │   ├── graph/
│       │   │   ├── GraphCanvas.tsx             # 无限画布容器 (SVG + pan/zoom)
│       │   │   ├── useForceSimulation.ts       # 力学模拟 hook
│       │   │   ├── GraphNode.tsx               # 单个节点 (halo + circle + label)
│       │   │   ├── GraphEdge.tsx               # 单条边
│       │   │   ├── GraphToolbar.tsx            # 缩放/复位/聚焦
│       │   │   ├── GraphLegend.tsx             # 图例
│       │   │   └── NodeTooltip.tsx             # 悬浮 tooltip
│       │   ├── ExchangeTabs.tsx                # 底部 4 tab 容器
│       │   ├── TimelineList.tsx                # 全部/求助/收到/给出 列表
│       │   ├── TimelineRow.tsx                 # 单行
│       │   ├── CategoryTag.tsx                 # 类别 pill
│       │   └── StatusBadge.tsx                 # 状态 pill (answered/await/denied)
│       └── types.ts                            # 前端补充类型 (若 openapi 类型不够用)
├── App.tsx                                     # + Route path="/market"
└── components/layout/Sidebar.tsx               # + 侧栏入口
```

### 组件树

```
<Market>
  <MarketHeader />                              # user badge in top-right
  <PresenceTiles data={data.presence} />        # 4 tiles
  <GraphCanvas
      nodes={data.graph.nodes}
      edges={data.graph.edges}
      meId={data.user.id}
  >
    <GraphEdge x N />
    <GraphNode x N />                           # 悬停触发 <NodeTooltip>
    <GraphToolbar />                            # 绝对定位
    <GraphLegend />                             # 绝对定位
  </GraphCanvas>
  <ExchangeTabs>
    <TimelineList timeline={data.timeline} filter="all" />       # tab: 全部
    <TimelineList timeline={data.timeline} filter="request" />   # tab: 我求助
    <TimelineList timeline={data.timeline} filter="incoming" />  # tab: 收到
    <TimelineList timeline={data.timeline} filter="outgoing" />  # tab: 给出
  </ExchangeTabs>
</Market>
```

**工作量**：2 人日

---

## 四、力学模拟的实现选择

Demo HTML 里手写了简化版 FR，代码 ~120 行且可维护。但落地到 React 生产环境时，推荐 **`d3-force`**（gzip ~15KB，稳定、参数化好）。

```ts
// features/market/components/graph/useForceSimulation.ts
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceX, forceY } from 'd3-force'

export function useForceSimulation(nodes, edges, meId, width, height) {
  const [positions, setPositions] = useState(...)
  useEffect(() => {
    const sim = forceSimulation(nodes)
      .force('charge', forceManyBody().strength(-320))
      .force('link', forceLink(edges).id(d => d.id).distance(110))
      .force('center', forceCenter(width / 2, height / 2))
      // "我"钉在中心
      .force('anchor-me', forceX(width / 2).strength(n => n.id === meId ? 0.5 : 0))
      .force('anchor-me-y', forceY(height / 2).strength(n => n.id === meId ? 0.5 : 0))
      .alphaDecay(0.03)
      .on('tick', () => setPositions([...nodes]))
    return () => sim.stop()
  }, [nodes, edges, meId, width, height])
  return positions
}
```

安装：`pnpm add d3-force @types/d3-force`

---

## 五、数据流

```
                     ┌─────────────────────────────────┐
                     │  backend workers (already live) │
                     │  agent-1 publish · every 300s   │
                     │  agent-2 scout · every 300s     │
                     │  → mutate blackboard_posts +    │
                     │    audit_events in SQLite       │
                     └────────────┬────────────────────┘
                                  │
                     GET /api/market/me
                                  │
                     ┌────────────▼────────────┐
                     │  useMarketMe() hook     │
                     │  React Query cache      │
                     │  refetchInterval: 30s   │  ← 用户在页时轻量轮询,新撮合出现即可见
                     └────────────┬────────────┘
                                  │
              ┌──────────┬────────┼────────┬────────────┐
              │          │        │        │            │
        PresenceTiles  Graph   Toolbar  Timeline  Refresh badge
              │          │                │
         "12 memory"  render 12         "6 records"
         "Received 2"    nodes +         按 category
         "Given 3"       edges           tag 分色显示
```

**为什么用 React Query**：
1. `package.json` 已经装了 `@tanstack/react-query`
2. 免手写 loading/error 状态
3. `refetchInterval: 30_000` 轻量轮询，撮合发生后 30 秒内自动可见
4. `staleTime: 15_000` 避免快速切换页面时重复请求

---

## 六、类型契约同步

利用已配置的 `api:types` 脚本自动生成：

```bash
# 后端加完 /api/market/me 端点后
pnpm --filter agentmesh-demo api:types

# 输出到 src/api/generated/schema.ts
```

组件里使用：
```ts
import type { paths } from '@/api/generated/schema'

type MarketMeResponse = paths['/api/market/me']['get']['responses']['200']['content']['application/json']
```

---

## 七、路由 + 侧栏入口

### `App.tsx` diff

```tsx
import { Market } from './pages/Market'

// ...
<Route path="/market" element={<Market />} />
```

### `Sidebar.tsx` diff

```tsx
{
  key: 'market',
  label: '协作市场',
  icon: <NetworkIcon />,      // lucide-react 已装
  to: '/market',
}
```

放在"协作"入口下方即可，因为语义上市场是协作的一种子形态（异步 vs 同步）。

---

## 八、开发排期

| 天 | 内容 | 交付物 |
|----|------|--------|
| Day 1 (backend) | 新增 `/api/market/me` + models + tests | 端点上线、`pnpm api:types` 通过 |
| Day 2 (frontend · scaffold) | 目录结构 + 路由 + `useMarketMe` + `PresenceTiles` + `MarketHeader` | 页面能打开，顶部显示我的数据 |
| Day 3 (frontend · graph) | `GraphCanvas` + `useForceSimulation` + 节点/边渲染 + 交互（拖动/缩放/hover） | 无限画布完整工作 |
| Day 4 (frontend · tabs + 打磨) | `ExchangeTabs` + `TimelineList` + `CategoryTag` + 响应式 + 单元测试 | 整页可用，进入 UAT |

如果并行：backend 1 天 + frontend 3 天并行开始，实际墙钟 3.5 天。

---

## 九、风险 & 打磨点

1. **图节点数量**：目前 seed 只有 3 个用户，看不出 graph 效果。可以在 backend 加一个 `AGENTMESH_MARKET_DEMO_USERS=12` 环境变量注入 mock 用户，Hackathon 演示用。
2. **worker 未启用**：`AGENTMESH_MARKET_ENABLED=1` 必须开启才有真实数据。文档中要提示（也可以在 `PresenceTiles` 里检测 `workers.publish.running=false` 时显示"市场未启用"提示）。
3. **DelegatedAnswer 状态映射**：后端有 4 种 status（`ANSWERED / AWAITING_CONFIRM / DENIED / SKIPPED`），前端目前只显示前 3 种。SKIPPED 应过滤或聚合。
4. **配色可访问性**：mint 绿在深底上对比比较柔和，`--muted` 上的 tag 文字要保证 ≥ 4.5:1 对比度。demo 里的 `color-mix(..., transparent 88%)` 背景 + 完整文字色应能满足。
5. **数据规模**：当组织超过 100 人时，force simulation 有性能负担。可以：a) 仅显示与"我" 2 跳内的节点；b) 大集群下切换为聚类气泡视图。
6. **实时性**：目前 30 秒轮询够用。如果需要实时，用现有的 WebSocket / SSE 机制（若已有）。

---

## 十、验收标准

- [ ] 用户点击侧栏"协作市场"能进入页面，页面在 500ms 内首屏可见
- [ ] 顶部 4 tile 数值准确对应后端 audit_events 计数
- [ ] 无限画布可平移/缩放/拖节点，"我"始终在中心
- [ ] 节点 hover 时显示 tooltip，其他节点淡化到 opacity 0.08
- [ ] 底部 4 tab 可切换，"全部"tab 按时间倒序聚合三类
- [ ] 类别 tag 三色分别对应 collab 紫 / remind 橙 / knowledge 蓝
- [ ] 每 30 秒静默刷新一次数据，新撮合出现无需手动刷新
- [ ] 深色主题下所有色对比度 ≥ 4.5:1（WCAG AA）

---

## 十一、后续可扩展

1. **点击节点跳转到该用户的分身档案** —— 需要一个 `/user/{id}/twin-profile` 页
2. **点击 timeline 行展开完整代答内容** —— 已有 `DelegatedAnswer.answer` 字段，加个 drawer 即可
3. **手动触发市场刷新** —— 已有 `/api/market/board` 的 drain 概念，前端加 "Refresh now" 按钮触发一次 scout run
4. **市场参与开关** —— 已有 `PUT /api/market/participation`，加个 toggle 到 header 里
5. **敏感度分级 UX** —— awaiting_confirm 的行加"审核并发送"按钮打开确认 Modal，调用 `resolve_delegated_answer`
