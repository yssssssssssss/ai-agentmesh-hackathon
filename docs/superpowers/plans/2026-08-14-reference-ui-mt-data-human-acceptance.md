# AgentMesh 参考 UI M/T 数据真人验收清单

- 分支：`feature/reference-ui-mt-data`
- Worktree：`.worktrees/reference-ui-mt-data`
- 参考截图：`agentmesh-demo/e2e/reference-baselines/`
- 验收方式：真人浏览器检查
- 自动验证状态：按用户要求，最终 reviewer 修复后未继续运行测试、构建或浏览器自动化

## 1. 启动验收环境

在项目根目录执行：

```bash
cd .worktrees/reference-ui-mt-data
```

确认 FastAPI 已在 `8010` 运行。如果没有可用的本地账号和数据，可使用独立 Demo 数据库启动：

```bash
AGENTMESH_DEMO_MODE=1 \
AGENTMESH_DB_PATH=/tmp/agentmesh-reference-ui.sqlite3 \
.venv/bin/uvicorn agentmesh.app:app --reload --port 8010
```

在另一个终端启动本分支前端，使用 `5181` 避免与主工作区 `5178` 冲突：

```bash
cd .worktrees/reference-ui-mt-data
npm --prefix agentmesh-demo run dev -- --port 5181 --strictPort
```

打开：

```text
http://127.0.0.1:5181
```

使用当前环境中有效的测试账号登录。

## 2. 验收记录格式

每个检查项记录：

| 字段 | 内容 |
|---|---|
| 结果 | 通过 / 失败 / 阻塞 |
| 页面 | 当前 URL |
| 视口 | 1512 / 768 / 390 |
| 截图 | 文件名或路径 |
| 备注 | 实际现象与预期差异 |

发现问题时保留完整页面截图和复现步骤，不只记录局部文案。

## 3. 全局壳层

### 1512px

- [ ] 左侧栏宽度和层级与参考接近。
- [ ] 品牌显示 `AgentMesh` 和“我的数字员工”。
- [ ] 普通页面内容区不超过参考 1240px 宽度。
- [ ] 当前用户、角色、Profile、设置、退出和管理员入口仍来自真实账号。
- [ ] 主导航真实徽标和 capability 入口仍可见。
- [ ] Tabs 选中态与参考一致。
- [ ] Tabs 支持左右方向键、Home 和 End。
- [ ] 设置抽屉中的账号身份显示 `T数据`。
- [ ] 本地显示偏好显示 `M数据`。

### 390px

- [ ] “打开导航”可以打开侧栏。
- [ ] 关闭按钮和遮罩可以关闭侧栏。
- [ ] 页面无整体横向滚动。
- [ ] 多 Tab 页面可以横向滚动并点击最后一个 Tab。
- [ ] Drawer 和 Modal 不超出可视区域。

## 4. M数据 / T数据 通用规则

- [ ] 真实用户、项目、任务、记忆、Inbox、文档和 allowed actions 显示 `T数据`。
- [ ] 参考 Mock、固定指标和示例叙事显示 `M数据`。
- [ ] 同一模块混合两类数据时，Mock 字段附近有独立 `M数据` 标识。
- [ ] 页面没有使用“真实数据”“Mock 数据”“混合数据”等其他标签代替 M/T。
- [ ] M 数据按钮不会修改服务端状态。
- [ ] 没有真实接口的操作显示禁用或“能力暂未接入”。
- [ ] 401、403、网络错误和版本冲突不会被 M 数据内容掩盖。

## 5. 我的数字人

打开 `/digital-self`。

### 页面结构

- [ ] Hero 保留参考页面的当前进展结构。
- [ ] “需要你处理”区域存在。
- [ ] “数字员工动态”区域存在。
- [ ] 下方依次包含“对你的工作理解”“本周新掌握”“我的经验正在被复用”。
- [ ] 1512px 下三张动态卡视觉高度和宽度协调。
- [ ] 390px 下三张卡按单列排列，无横向溢出。

### 数据与操作

- [ ] 当前用户、Workspace、Project、Agent 状态显示 `T数据`。
- [ ] 参考推进叙事、参与人数和影响聚合显示 `M数据`。
- [ ] 真实 UserMemoryItem 存在时优先展示真实理解。
- [ ] 参考待办显示 `M数据` 且按钮禁用。
- [ ] 今日 ActivityLog 只作为只读工作记录，不被解释成可操作待办。
- [ ] “继续当前项目”仍能进入 AI 工作台。
- [ ] 影响卡入口仍能进入数字人管理活动页。

## 6. 我的知识

打开 `/knowledge`。

### 页面结构

- [ ] 只有三个主 Tab：“已沉淀知识”“待我确认”“使用与反馈”。
- [ ] 已沉淀知识保留参考筛选、排序和资产卡布局。
- [ ] 待确认保留参考候选卡和确认入口。
- [ ] 使用与反馈保留参考时间线结构。
- [ ] 资产和事件可以打开统一详情 Drawer。

### 数据和治理

- [ ] UserMemoryItem、team_accepted Memory、Document 使用 `T数据`。
- [ ] open Inbox 和 team_candidate 使用 `T数据`。
- [ ] 后端没有 reuse/feedback 时，参考 Timeline 显示 `M数据`。
- [ ] M Timeline 操作不可执行。
- [ ] Brief 文档版本来自真实 Document，而不是 Inbox 的不存在字段。
- [ ] 查询有 cached data 但同时 error/403/loading 时，所有 mutation 变为只读或禁用。
- [ ] Brief confirm 继续提交真实 text 和 expected document version。
- [ ] team candidate 只有存在真实 accept allowed action 时才能接受。
- [ ] Inbox snooze、resolve、injection 操作仍服从服务端 allowed actions。

## 7. 协作网络

打开 `/collaboration`。

### 页面结构

- [ ] “我的协作网络”概览存在。
- [ ] “协作能力类型”存在。
- [ ] 参与者和协作记录存在。
- [ ] “全部协作”“我的申请”“待我授权”Tab 存在。
- [ ] Market 信息没有替代主协作视图。
- [ ] 390px 下指标和卡片纵向排列，无横向溢出。

### 数据和操作

- [ ] Task、Post、status、owner、lock、source 和 allowed actions 显示 `T数据`。
- [ ] 后端缺少的能力比例、周期聚合和匹配原因显示 `M数据`。
- [ ] failed Task 不计入“协作进行中”。
- [ ] handoff current_result 归因于交接前 actor，不归因于 next owner。
- [ ] authorization task 只展示当前项目，或可以加载对应 timeline。
- [ ] 无专用 approve/deny 后端命令时，授权按钮禁用。
- [ ] reply、handoff、lock、unlock、read 只在 allowed_actions 允许时显示和执行。

### 协作详情 Drawer

- [ ] 默认显示用户叙事型时间线。
- [ ] 时间线包含原因、参与人、贡献和结果。
- [ ] 来源可以查看。
- [ ] 原始 Task/Post/actor/lock 位于折叠的“技术详情”。
- [ ] 真实 mutation 完成后页面状态刷新。

## 8. 工作洞察

打开 `/insights`。

### 页面结构

- [ ] 按顺序显示“近期工作概览”“洞察反馈”“值得复盘的历史项目”“复盘证据”“知识形成”。
- [ ] 原始 Task、Activity、Memory、Audit 位于次级诊断区域，不替代主叙事。
- [ ] 页面视觉层级与参考 Insights 接近。

### 数据和降级

- [ ] 当前 Project、Task、Activity、Memory、Audit 使用 `T数据`。
- [ ] 跨项目洞察、KPI、复盘建议、Workflow 推荐使用 `M数据`。
- [ ] 复盘、Workflow 和知识候选操作显示禁用或暂不可用。
- [ ] 不存在本地假成功、定时器或 Toast 模拟写入。
- [ ] 任一真实 read model 为 loading、forbidden、error 时，相关 M 模块被抑制，不掩盖真实错误。
- [ ] 所有真实 read model available 后，缺失聚合才允许显示 M 数据。

## 9. AI 工作台冻结边界

打开 `/workspace`。
- [ ] 点击历史中的“618 家电首屏历史经验查询”后，显示“2026 年 618 家电会场首页改版”完整演示内容。
- [ ] 演示会话包含项目理解、任务分析、参考建议和 Brief 入口，并显示 `M数据`。
- [ ] 点击“2025 年 618 家电会场复盘”，侧边栏独立显示项目背景、核心问题、设计方案、结果数据和当前任务关联。
- [ ] 点击“2024 年家电超级品类日”，侧边栏独立显示该项目自己的背景、方案、结果和关联，不复用 2025 内容。
- [ ] 点击“首页营销入口点击数据”，侧边栏显示数据范围、三项指标、涨跌幅、关键结论、统计时间和口径说明。
- [ ] 点击“2026 年 618 家电会场首页设计 Brief”，侧边栏显示项目目标、历史背景、核心问题、设计原则、设计方向和数据支撑。
- [ ] 上述四个侧边栏都显示 `M数据`，关闭后返回演示对话。
- [ ] 演示会话发送新消息时创建真实新线程，不写入演示线程。
- [ ] AI 工作台默认不再显示“搜索可见资料”搜索框。
- [ ] 上传文档、导入任务和消息来源详情仍可使用。

- [ ] 用户回车后消息立即出现在对话区。
- [ ] pending 状态可见。
- [ ] 对话更新时自动滚到底部。
- [ ] 输入 `$` 可以唤起后端 Skill。
- [ ] Skill 前缀过滤和键盘选择正常。
- [ ] 历史会话可选择，刷新后消息恢复。
- [ ] 文件上传、任务队列和资料搜索正常。
- [ ] “本轮执行依据”和 P/J/T 记忆标注正常。
- [ ] 本轮页面对齐没有改变 Workspace 核心交互和数据协议。

## 10. 响应式抽查

在 768px 和 390px 分别抽查：

- [ ] DigitalSelf 主结构。
- [ ] Knowledge 三 Tab 和详情 Drawer。
- [ ] Collaboration 卡片和 Drawer。
- [ ] Insights 五个主模块。
- [ ] Workspace Composer 和消息滚动。

只检查导航、可达性、溢出和关键操作，不要求重复完整内容验收。

## 11. 验收结论

全部检查完成后填写：

```text
验收人：
验收日期：
分支/Commit：
通过项：
失败项：
阻塞项：
是否允许进入合并：是 / 否
```

若存在失败项，按页面和模块回传，不在同一轮中顺带重构无关功能。
