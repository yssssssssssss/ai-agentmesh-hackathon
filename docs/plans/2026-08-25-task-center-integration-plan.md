# AgentMesh 任务中心真实数据接入方案

- 日期：2026-08-25
- 状态：只读阶段、可写 Task 核心及 Task-AgentRun-Artifact 关联已实施；Artifact Review、Memory 闭环及高级项目管理能力按后续 Slice 交付
- 路线确认：项目后续继续向完整项目管理与记忆管理闭环演进；本轮只交付只读观察面，写能力、独立交付生命周期和记忆联动必须按独立阶段验证后合并
- 方案调研基线：`67537c9`
- 缩减版实施基线：`7a28d41`
- 目标应用：`agentmesh-demo/` React/Vite 前端与 `agentmesh/` FastAPI/SQLite 后端
- 视觉与交互参考：`deliverables/agentmesh-integrated-task-management-demo.html`
- 结论：可以接入，但必须按真实数据垂直切片重新实现，不能把单文件 Demo 原样嵌入产品

> 实施说明（2026-08-26）：当前交付范围以
> [`2026-08-25-task-center-readonly-slice.md`](./2026-08-25-task-center-readonly-slice.md)
> 为准，已提供主导航、`/tasks`、真实 Blackboard 任务看板/列表和只读详情。
> 本文规划的 `/api/tasks` 聚合、项目总览、日历、Agent 视图以及创建、编辑、分派等写能力尚未实施，
> 因此当前不能宣称完整任务中心已经接入。

## 1. 执行摘要

本方案把现有任务管理 Demo 转换为 AgentMesh 的正式“任务中心”。任务中心统一呈现项目中的人类任务、Agent 执行、协作记录、审批、知识沉淀和项目进度，同时保留现有“我的数字员工、AI 工作台、工作洞察、我的知识、协作网络、协作市场、管理控制台”。

现有项目已经具备 Task、Agent、AgentRun、Blackboard、Inbox、Memory、Audit、权限和真实 API 基础，但当前 `Task` 主要表达聊天或 Agent 工作流的执行状态，不足以直接承载优先级、截止时间、项目负责人、子任务、依赖和项目交付阶段。当前 Demo 则完全使用页面内 Mock 数据和内存 mutation，没有接入任何 `/api`。

推荐采用向后兼容扩展：保留现有 `Task.status` 和 `Task.collaboration_stage` 的语义，在 `Task` 上增加可选的项目管理元数据；新增任务中心专用读写 API、React `/tasks` 路由和任务聚合视图。`AgentRun` 继续表示一次执行尝试，通过可选 `task_id` 关联任务。所有权限、状态迁移、审批、取消、审计和并发控制均由 FastAPI/SQLite 决定。

该实施预计涉及超过 8 个文件，但不新增外部服务、运行时、前端依赖、API Key 或第三方账号。

## 2. 当前事实

### 2.1 已经存在的能力

- `Project`、项目成员与 Workspace 真实存在。
- `Task`、Blackboard 帖子、执行锁、交接和协作阶段真实存在。
- Agent、模型、Skill、Tool Grant 和 Agent 运行状态真实存在。
- AgentRun、审批 Inbox、Memory、Source、Artifact 和 Audit 真实存在。
- 协作网络已经读取 `/api/blackboard/task-cards` 和 `/api/blackboard/tasks/{task_id}`。
- 工作洞察已经读取真实任务卡片。
- React 前端已经具备统一 API client、OpenAPI 类型生成、TanStack Query、认证和错误处理基础。
- FastAPI/SQLite 是当前业务状态和权限的唯一真相源。

### 2.2 尚未实现的能力

- React 应用已提供 `/tasks` 只读入口和“任务中心”导航，但项目总览、日历和 Agent 视图尚未实现。
- 后端没有通用的任务创建、编辑、归档和项目交付状态迁移接口。
- `Task` 缺少项目管理描述、类型、优先级、截止时间、人类负责人、父任务、依赖、标签和并发版本。
- `AgentRun` 尚未显式关联 `Task`。
- 后端没有面向任务中心的项目概览、Agent 队列和运行质量聚合。
- Demo 中的任务、Agent、进度、里程碑和统计均为 Mock。
- Demo 的创建、编辑、推进、暂停 Agent 和知识确认只修改浏览器内存或显示 Toast。

### 2.3 当前风险面

`TaskStatus`、`task.status` 和 `collaboration_stage` 在后端、前端与测试中至少存在 84 处引用。它们控制 Agent 工作流、Blackboard、协作网络、工作洞察、种子数据和测试。把现有 `Task.status` 直接替换为 `backlog / todo / in_progress / review / done` 会破坏已有执行语义，属于禁止方案。

当前主工作区还存在未提交修改，其中包括 `agentmesh/models.py` 和多项 Workspace/Skill 编排前端代码。任务中心实施必须使用独立 worktree，不能在当前脏工作区直接混合开发。

## 3. 产品目标

任务中心完成后，用户应当能够：

1. 在项目内统一查看所有人与 Agent 的工作项。
2. 在看板、列表、日历、项目总览和 Agent 视图之间切换。
3. 创建、编辑、分派、阻塞、推进、完成、重开和归档任务。
4. 将任务分派给自己、项目成员、个人数字员工或获准使用的公共 Agent。
5. 在任务详情中查看子任务、依赖、协作记录、Agent 运行、审批、产物、知识和审计活动。
6. 从任务启动 Agent 执行，并明确区分“暂停 Agent 接收新任务”和“取消正在执行的 Run”。
7. 刷新浏览器或重启服务后继续看到相同的服务端状态。
8. 在权限不足、版本冲突、Provider 降级或数据为空时看到诚实状态，而不是前端假成功。

## 4. 成功标准

- `http://127.0.0.1:5178/tasks` 可直接访问并出现在主导航中。
- 原有七个产品入口均保留，任务中心不替换或隐藏原模块。
- 看板、列表、日历、总览和 Agent 视图只显示服务端数据或明确的空态。
- 页面刷新后，创建、编辑、分派和状态迁移结果保持不变。
- 协作网络、工作洞察和任务中心对同一个 Task 的标题、负责人和完成状态保持一致。
- 无权限操作不显示或禁用；即使绕过前端调用，后端仍返回 403。
- 并发编辑使用版本号；过期写入返回 409，不能静默覆盖他人修改。
- 旧 SQLite Task 记录无需一次性破坏性迁移即可读取。
- 现有聊天、Agent 编排、Blackboard 锁定/解锁/交接、Inbox 审批和 Memory 流程回归通过。
- 前端生产构建、后端全量测试、Ruff、Vitest 和任务中心浏览器 E2E 全部通过。

## 5. 术语与生命周期边界

### 5.1 三种状态不得混用

| 名称 | 所有者 | 含义 | 示例 |
| --- | --- | --- | --- |
| 执行状态 `Task.status` | 现有 Agent 工作流 | 当前执行是否创建、运行、等待、合成、完成或失败 | `running`、`waiting_external_agent` |
| 协作阶段 `Task.collaboration_stage` | Blackboard 协作 | 当前讨论、执行、审核、阻塞或协作完成阶段 | `discussion`、`review` |
| 交付阶段 `management.delivery_stage` | 新任务中心 | 项目工作项在计划和交付流程中的位置 | `backlog`、`planned`、`in_progress`、`review`、`done`、`cancelled` |

任务中心不能重定义前两种状态。服务端可以根据执行事件建议或推进交付阶段，但必须通过明确的状态迁移规则，不允许前端自行拼接。

### 5.2 领域关系

```text
Project
└── Task（项目工作项，拥有交付生命周期）
    ├── ChatThread（任务上下文）
    ├── AgentRun[]（零到多次执行尝试）
    ├── BlackboardPost[]（协作、证据、交接）
    ├── InboxItem[]（审批与人工介入）
    ├── Artifact[] / Memory[]（产出与知识血缘）
    ├── child Task[]（子任务）
    └── dependency Task[]（前置依赖）
```

`Task` 表示“要交付什么”，`AgentRun` 表示“某一次如何执行”。一个 Task 可以没有 AgentRun，也可以因重试、切换 Agent 或分段执行拥有多个 AgentRun。

### 5.3 与 Task → Scenario → Skill 编排的区别

`docs/plans/2026-08-24-task-scenario-skill-orchestration.md` 中的 Task 是意图分类和能力路由概念；本方案中的 Task 是持久化项目工作项。实现中不得把 Registry Task ID 当成项目任务 ID。需要关联时，在任务管理元数据中保存可选的 `scenario_id`，不共享生命周期状态机。

## 6. 范围

### 6.1 本方案建设内容

- React 任务中心和主导航入口。
- 项目总览、看板、列表、日历、Agent 管理和任务详情。
- 真实 Task 聚合读取接口。
- 项目管理字段、任务创建/编辑/分派/迁移/归档。
- 子任务和任务依赖。
- Task 与 AgentRun 的真实关联。
- Agent 队列、运行状态、成功率、耗时和人工介入统计。
- Task 与 Blackboard、Inbox、Memory、Artifact、Audit 的聚合详情。
- 服务端权限、`allowed_actions`、审计和乐观并发控制。
- 旧 Task 的兼容投影和无损升级。

### 6.2 明确不建设

- 不引入 PostgreSQL、Redis、新队列或新微服务。
- 不接入 designOS 或其他外部项目数据源。
- 不支持多 Workspace 租户隔离、水平扩容或公网生产加固。
- 不引入第三方任务管理系统同步。
- 不提供物理删除任务；只允许取消和归档。
- 不允许前端模拟权限、执行状态或 mutation 成功。
- 不把 Demo 作为 iframe 或静态页面嵌入 React。
- 不把 Agent 暂停等同于取消已经开始的 AgentRun。
- 不改变自然聊天的私有默认值和显式 `$` Skill 行为。

## 7. 方案选择

### 7.1 采用：向后兼容扩展现有 Task

保留现有 `Task` 作为唯一项目工作项，在其上增加可选的 `TaskManagementMetadata`。旧记录没有该字段时，由服务端生成兼容投影；第一次真实编辑时再持久化管理元数据。

这样可以复用现有 Task、Blackboard、Memory、Inbox 和审计关系，同时避免引入第二套相互竞争的 WorkItem 状态机。

### 7.2 拒绝：直接修改 TaskStatus

拒绝把 `TaskStatus` 改成 Demo 的看板状态。该方案会影响 Agent 工作流、Blackboard 和现有前端投影，回归面过大。

### 7.3 拒绝：新增独立 WorkItem 并双向同步

独立 WorkItem 可以隔离现有 Task，但会产生 Task 与 WorkItem 的双写、同步和冲突恢复问题。当前单 Workspace 原型没有足够收益支撑第二套持久化生命周期。

### 7.4 最小可交付版本

最小版本仅新增真实只读 `/tasks` 页面与聚合读取接口，展示现有 Task、Agent 和 Blackboard 数据；不开放任何后端尚未支持的 mutation。该版本独立可用，可以先验证信息架构和真实数据密度。

## 8. 数据模型

### 8.1 新增枚举

| 类型 | 值 |
| --- | --- |
| `TaskDeliveryStage` | `backlog`、`planned`、`in_progress`、`review`、`done`、`cancelled` |
| `TaskPriority` | `p0`、`p1`、`p2`、`p3` |
| `TaskAssigneeKind` | `user`、`agent` |
| `ChatThreadKind` | `conversation`、`task` |

阻塞不是交付阶段。阻塞信息通过 `blocked_reason` 和 `blocked_at` 表达，解除阻塞后任务回到原交付阶段。

### 8.2 TaskManagementMetadata

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| `description` | `str` | 最长 4000 字符 |
| `task_type` | 可空字符串枚举 | `design`、`research`、`data`、`risk`、`review`、`project_action`、`milestone` |
| `delivery_stage` | `TaskDeliveryStage` | 新建任务默认为 `backlog` |
| `priority` | 可空 `TaskPriority` | 新建任务默认为 `p2`；旧任务为空，不伪造优先级 |
| `due_at` | 可空时间 | 使用带时区 ISO 8601 |
| `assignee_kind` | 可空 `TaskAssigneeKind` | 与 `assignee_id` 同时为空或同时存在 |
| `assignee_id` | 可空字符串 | 必须是当前项目成员或获准使用的 Agent |
| `tags` | 字符串列表 | 去重，单项最长 40，最多 12 项 |
| `parent_task_id` | 可空 Task ID | 子任务只能与父任务属于同一项目 |
| `dependency_task_ids` | Task ID 列表 | 同项目、去重、禁止自依赖和环 |
| `blocked_reason` | 可空字符串 | 最长 1000 字符 |
| `blocked_at` | 可空时间 | 与 `blocked_reason` 一致出现 |
| `scenario_id` | 可空字符串 | 只记录编排分类，不参与任务生命周期 |
| `version` | 正整数 | mutation 成功后加一 |
| `archived_at` | 可空时间 | 归档后默认列表不返回 |

`Task` 增加可选字段 `management: TaskManagementMetadata | None`。现有 `status`、`collaboration_stage`、`current_owner_*`、`execution_lock` 和 `done_when` 保持原义。

### 8.3 ChatThread

`ChatThread` 增加 `kind: ChatThreadKind = conversation`。通过任务中心创建 Task 时，服务端在同一事务中创建 `kind=task` 的上下文线程并继续满足现有 `Task.thread_id` 必填约束。

默认会话列表只显示 `kind=conversation`；任务详情可以读取任务线程并提供“在 AI 工作台中继续”入口。旧 ChatThread 缺少字段时按 `conversation` 读取。

### 8.4 AgentRun

`AgentRun` 和 `AgentRunCreateRequest` 增加可选 `task_id`：

- 指定时，Task 必须存在、与 Run 位于同一 Workspace/Project，当前用户必须可见。
- 重试 Run 继承原 Run 的 `task_id`，客户端不能把重试改绑到另一任务。
- Run 取消、失败或部分完成不直接删除或归档 Task。
- Run 完成只能按服务端规则建议或推进 Task 的交付阶段，不能覆盖人工已完成或已取消状态。

### 8.5 派生字段

以下内容不重复持久化：

- `progress`：有子任务时按已完成子任务比例计算；无子任务时由交付阶段和当前 Run 步骤生成展示值。
- Agent 队列：由分派给 Agent、未归档且尚未完成的 Task 按优先级、截止时间和创建时间排序。
- Agent 成功率与耗时：由 AgentRun 聚合。
- 任务活动：由 AuditEvent、BlackboardPost、AgentRunEvent、Inbox 和 Memory 关系聚合。
- 项目健康和里程碑：里程碑使用 `task_type=milestone` 的 Task，风险由逾期、阻塞和依赖状态计算。

## 9. 状态迁移

### 9.1 交付阶段

```text
backlog ──plan──> planned ──start──> in_progress ──submit_review──> review ──complete──> done
   │                  │                    │               │                         │
   └────cancel────────┴────cancel──────────┴────cancel─────┴────cancel──────────────> cancelled

done ──reopen──> in_progress
cancelled ──reopen──> backlog
```

`block` 和 `unblock` 不改变交付阶段，只修改阻塞字段。存在未完成的硬依赖时，服务端不允许 `start`；存在未完成子任务时，默认不允许 `complete`，Team Lead/Admin 可以带原因强制完成并写审计。

### 9.2 执行状态与交付阶段

- 新 AgentRun 开始时，`planned` 可以自动推进为 `in_progress`。
- Run 等待审批或外部输入时，Task 保持 `in_progress`，同时显示阻塞或等待原因。
- Run `completed` 不自动把 Task 标记为 `done`；需要满足 `done_when`、子任务和审批条件。
- Run `partial` 保持 `in_progress` 或进入 `review`，由服务端完成度检查决定。
- Run `failed` 标记风险但不取消 Task。
- 暂停 Agent 只阻止新任务调度；取消正在运行的 Run 必须调用 AgentRun 取消接口。

## 10. 权限模型

### 10.1 基础规则

- 所有读取首先验证 Workspace 和 Project 访问权限。
- 活跃项目成员可以创建任务、编辑自己创建或分派给自己的任务。
- 用户可以把任务分派给自己或自己的 Personal Agent。
- Team Lead/Admin 可以编辑项目内全部任务，并分派给其他成员或公共 Agent。
- 公共 Agent 的模型、工具和能力配置继续使用现有 Agent 管理权限；任务分派不能隐式修改 Agent 配置。
- 归档、强制完成、跨成员改派和公共 Agent 分派需要新的 `manage_project_tasks` 权限。
- 每次 mutation 在服务端重新授权并写入 AuditEvent。

### 10.2 allowed_actions

任务列表和详情返回服务端计算的 `allowed_actions`。允许的动作集合为：

- `edit`
- `assign`
- `plan`
- `start`
- `submit_review`
- `complete`
- `reopen`
- `block`
- `unblock`
- `cancel`
- `archive`
- `start_agent_run`
- `cancel_agent_run`

前端只用该字段控制按钮状态，不根据 `role` 或本地状态重新推断权限。

## 11. API 契约

### 11.1 读取接口

| 方法与路径 | 用途 |
| --- | --- |
| `GET /api/tasks` | 分页任务列表；支持项目、阶段、负责人类型、负责人、优先级、截止范围和关键字筛选 |
| `GET /api/tasks/overview` | 项目任务计数、逾期、阻塞、审核、里程碑和人/Agent 分工 |
| `GET /api/tasks/agent-overview` | Agent 当前任务、队列、运行状态和近 7 日质量指标 |
| `GET /api/tasks/{task_id}` | 聚合任务详情、子任务、依赖、Run、Blackboard、Inbox、Memory、Artifact 和活动 |

静态路径 `overview` 与 `agent-overview` 必须在动态 `{task_id}` 路由前注册。

### 11.2 写入接口

| 方法与路径 | 用途 |
| --- | --- |
| `POST /api/tasks` | 创建任务及其任务上下文 ChatThread |
| `PATCH /api/tasks/{task_id}` | 使用 `expected_version` 编辑描述、类型、优先级、截止时间、负责人、标签、父任务和依赖 |
| `POST /api/tasks/{task_id}/transitions` | 执行 `plan/start/submit_review/complete/reopen/block/unblock/cancel` |
| `POST /api/tasks/{task_id}/archive` | 软归档任务 |
| `POST /api/agent/runs` | 复用现有入口，新增可选 `task_id` 启动与任务关联的 AgentRun |

### 11.3 响应和错误

- 列表返回 `items`、`total`、`page`、`page_size`、`has_next` 和筛选后的 `counts`。
- 详情返回聚合对象，避免前端为每张卡片发起 N+1 请求。
- 401：清除认证缓存并进入登录态。
- 403：显示服务端权限原因。
- 404：资源不存在或不可见，不泄漏其真实存在性。
- 409：版本冲突或非法状态迁移；前端刷新任务并保留用户未提交表单。
- 422：映射至具体表单字段。
- 502/503：任务仍可访问，Agent 执行能力显示降级或不可用。

## 12. 旧数据兼容与迁移

### 12.1 兼容投影

旧 Task 没有 `management` 时，服务端只在响应中生成下列投影，不立即重写数据库：

| 旧状态 | 交付阶段投影 | 补充状态 |
| --- | --- | --- |
| `created` | `backlog` | 无 |
| `running` / `synthesizing` | `in_progress` | 无 |
| `waiting_external_agent` | `in_progress` | 显示等待外部输入 |
| `completed` | `done` | 无 |
| `failed` | `in_progress` | 标记阻塞，原因来自错误或最新风险记录 |
| `collaboration_stage=review` | `review` | 覆盖上述非终态投影 |

旧任务的优先级、截止时间和类型保持空值，界面显示“未设置”，不得伪造默认数据。负责人优先读取管理元数据，其次读取现有 `current_owner_*`。

### 12.2 首次编辑

旧 Task 第一次被真实编辑时：

1. 服务端以兼容投影创建 `TaskManagementMetadata`。
2. `version` 从 1 开始。
3. 在 SQLite `BEGIN IMMEDIATE` 事务中比较期望版本并更新。
4. 写入 AuditEvent，记录修改前后字段。

### 12.3 数据安全

- 不批量覆盖现有 Task 状态。
- 不删除现有 ChatThread、Blackboard、Inbox、Memory 或 AgentRun。
- 不提交 `data/agentmesh.sqlite3`。
- 测试使用临时 SQLite 数据库覆盖旧记录读取、首次编辑、并发冲突和回滚。

## 13. 后端实现结构

### 13.1 新增文件

- `agentmesh/routes/tasks.py`：薄路由，负责请求校验、认证、授权和调用服务。
- `agentmesh/task_management.py`：任务聚合、兼容投影、状态机、依赖校验、权限动作和统计。
- `tests/test_task_management_routes.py`：API、权限、错误和聚合响应测试。
- `tests/test_task_management_service.py`：状态机、依赖环、旧数据映射和统计测试。
- `tests/test_task_management_persistence.py`：版本冲突和持久化测试。
- `docs/adr/0008-task-center-delivery-lifecycle.md`：记录执行状态、协作阶段和交付阶段的边界。

### 13.2 修改文件

- `agentmesh/models.py`：新增枚举、管理元数据、请求/响应视图、ChatThread kind 和 AgentRun task_id。
- `agentmesh/store.py`：增加版本比较保存、项目任务查询和聚合所需的存取方法。
- `agentmesh/permissions.py`：增加 `manage_project_tasks` 权限和对象级判定。
- `agentmesh/app.py`：注册 tasks router 和 `/tasks` SPA 回退路径。
- `agentmesh/routes/chat.py`：默认会话列表排除 `kind=task`，直接读取仍可访问。
- `agentmesh/routes/agent_runs.py`：校验并持久化 `task_id`，重试继承关联。
- `agentmesh/agents.py`：只增加必要的执行事件到交付状态协调，不重写现有 TaskStatus 流程。
- `agentmesh/seed.py`：仅为 Demo 模式提供可验证的管理字段，不在生产模式注入 Mock。
- `CONTEXT.md`：实现完成后把任务中心、状态边界和真实可达能力写入代码现实说明。

## 14. 前端实现结构

### 14.1 新增文件

- `agentmesh-demo/src/pages/Tasks.tsx`
- `agentmesh-demo/src/features/tasks/api.ts`
- `agentmesh-demo/src/features/tasks/queries.ts`
- `agentmesh-demo/src/features/tasks/types.ts`
- `agentmesh-demo/src/features/tasks/presenter.ts`
- `agentmesh-demo/src/features/tasks/presenter.test.ts`
- `agentmesh-demo/src/features/tasks/api.test.ts`
- `agentmesh-demo/src/components/tasks/TaskOverview.tsx`
- `agentmesh-demo/src/components/tasks/TaskBoard.tsx`
- `agentmesh-demo/src/components/tasks/TaskList.tsx`
- `agentmesh-demo/src/components/tasks/TaskCalendar.tsx`
- `agentmesh-demo/src/components/tasks/AgentTaskPanel.tsx`
- `agentmesh-demo/src/components/tasks/TaskDrawer.tsx`
- `agentmesh-demo/src/components/tasks/TaskFormDialog.tsx`
- `agentmesh-demo/e2e/task-management.spec.ts`

### 14.2 修改文件

- `agentmesh-demo/src/App.tsx`：懒加载 `/tasks/*`。
- `agentmesh-demo/src/components/layout/Sidebar.tsx`：在“AI 工作台”和“工作洞察”之间增加“任务管理”。
- `agentmesh-demo/src/app/queryKeys.ts`：增加列表、详情、概览和 Agent 聚合查询键。
- `agentmesh-demo/src/api/generated/schema.ts`：由 OpenAPI 重新生成，不手工编辑。
- `agentmesh-demo/src/index.css`：只增加任务中心需要且不能由现有组件表达的布局样式。

### 14.3 界面状态

- 主路由：`/tasks`。
- 页内视图使用 URL 查询参数：`view=overview|board|list|calendar|agents`。
- 筛选条件同步到 URL，以便刷新和分享后保持。
- Drawer、Dialog、Toast 和键盘焦点属于本地 UI 状态。
- Task、Agent、Run、Inbox 和 Memory 均由 TanStack Query 管理。
- mutation 成功后使用服务端返回更新缓存并失效相关 Overview、Insights 和 Collaboration 查询。
- 治理类 mutation 不做业务状态乐观更新。

### 14.4 Demo 迁移规则

- 保留视觉层级、看板/列表/日历切换、任务详情抽屉和 Agent 面板结构。
- 把内联 SVG 替换为项目已有 Lucide 图标。
- 把固定人名、TASK 编号、日期、统计和进度全部替换为服务端字段。
- 没有真实字段时显示空态或隐藏模块，不能继续保留示例数字。
- 创建、编辑、推进、暂停、知识确认和消息发送必须调用真实 endpoint。
- 原有产品模块仍使用现有 React 页面，不复制 Demo 中对应模块的静态替身。
- 390px 使用可关闭导航和全屏任务详情；768px 使用单列或双列自适应；1512px 保留完整多列看板。

## 15. 分阶段交付

### 阶段一：真实只读任务中心

交付内容：

- 新增 `/tasks`、主导航入口和 SPA 回退。
- 新增任务聚合列表、详情、概览和 Agent 概览读取接口。
- 看板、列表、项目总览、Agent 视图和任务详情读取真实数据。
- 日历只显示具有真实截止时间的任务；没有数据时显示空态。
- 所有后端尚未支持的写按钮隐藏或明确禁用。

独立价值：用户可以从一个入口真实查看项目任务、人/Agent 分工、协作和运行状态，不再依赖 Mock。即使后续阶段不实施，该阶段仍可上线使用。

### 阶段二：核心任务管理

交付内容：

- 增加 Task 管理元数据和 ChatThread kind。
- 实现创建、编辑、分派、状态迁移、阻塞、重开和归档。
- 实现子任务、依赖、标签、优先级、截止时间和日历。
- 实现服务端 `allowed_actions`、AuditEvent 和版本冲突控制。
- 实现旧 Task 首次编辑的无损物化。

独立价值：任务中心成为可日常使用的人机统一项目管理工具，不依赖 Agent 执行功能才能完成普通任务管理。

### 阶段三：Agent 执行与队列

交付内容：

- AgentRun 增加 Task 关联并在重试时继承。
- 从任务启动 AgentRun，展示执行、等待审批、部分完成、失败和取消。
- Agent 视图展示当前任务、真实队列、容量、近 7 日成功率、耗时和人工介入。
- 区分暂停 Agent 和取消 Run。
- Provider 不可用时保留任务并显示诚实降级状态。

独立价值：用户可以在任务中心分派并干预 Agent 工作，而不是只看静态 Agent 配置。

### 阶段四：跨模块闭环

交付内容：

- Task 与协作网络互相跳转并共享同一聚合状态。
- Task 与工作洞察共享计数、风险和进度口径。
- Task 与 Inbox 审批、Memory 候选、Artifact 和 Source 血缘互相跳转。
- `task_type=milestone` 支撑项目里程碑和关键路径展示。
- 移除任务中心内部剩余的展示 Mock；只保留明确的 Demo seed。

独立价值：任务成为 AI 工作台、协作、洞察和知识之间的统一上下文入口。

## 16. 测试方案

### 16.1 后端行为

- 项目成员只能读取可访问项目的任务。
- 普通用户、Task 创建者、被分派用户、Team Lead 和 Admin 的 `allowed_actions` 符合规则。
- 公共 Agent 分派和跨成员改派受 `manage_project_tasks` 控制。
- 旧 Task 无管理字段时可以读取、筛选并生成正确投影。
- 首次编辑旧 Task 后版本为 1，第二个过期编辑返回 409。
- 非法交付状态迁移返回 409。
- 依赖不存在、跨项目、自依赖或形成环时返回 422。
- 未完成硬依赖不能启动；未完成子任务不能普通完成。
- 创建 Task 和任务 ChatThread 在同一事务成功或失败。
- Run 的 Task 关联必须同 Workspace/Project，重试不能改绑。
- Run 失败不把 Task 误标为完成，取消 Run 不归档 Task。
- Blackboard lock/unlock/handoff 的旧行为保持不变。
- 所有 mutation 写入审计且不记录敏感输入正文。

### 16.2 前端行为

- `/tasks` 五种视图可加载、刷新和通过 URL 恢复状态。
- 看板、列表和日历对同一 Task 展示一致。
- loading、empty、403、404、409、422 和 503 均有明确界面。
- 409 刷新服务端数据，并保留用户尚未重新提交的表单内容。
- 创建、编辑、分派、迁移、阻塞和归档成功后刷新相关查询。
- 无权限按钮不可操作，直接 API 调用仍被后端拒绝。
- Agent 暂停和 Run 取消显示为不同操作。
- 任务详情的协作、审批、知识和运行链接可返回原任务。
- 390px、768px、1512px 视口可操作，无水平页面溢出；看板内部允许横向滚动。
- 键盘可以打开任务、切换焦点、提交/取消 Dialog，并用 Escape 关闭最上层浮层。

### 16.3 回归范围

- AI 工作台聊天、会话列表和显式 `$` Skill。
- Task 创建和现有 Agent 工作流状态更新。
- 协作网络任务列表、详情、锁定、解锁和交接。
- 工作洞察任务计数和状态展示。
- Inbox 审批、Knowledge 接受和 Memory 血缘。
- Agent 模型、工具、Skill 和状态配置。
- React 登录、路由、深链和静态构建回退。

### 16.4 验证命令

```bash
.venv/bin/python -m pytest tests/test_task_management_routes.py tests/test_task_management_service.py tests/test_task_management_persistence.py
.venv/bin/python -m pytest
.venv/bin/ruff check .
npm --prefix agentmesh-demo run api:types
npm --prefix agentmesh-demo test
npm --prefix agentmesh-demo run build
npm --prefix agentmesh-demo run test:e2e -- task-management.spec.ts
```

手工验收时分别启动：

```bash
.venv/bin/uvicorn agentmesh.app:app --reload --port 8010
npm --prefix agentmesh-demo run dev -- --port 5178 --strictPort
```

浏览器验收入口为 `http://127.0.0.1:5178/tasks`。

## 17. 风险与控制

| 风险 | 后果 | 控制 |
| --- | --- | --- |
| 重定义现有 TaskStatus | Agent 工作流、协作和洞察回归 | 禁止修改既有语义；增加独立交付阶段 |
| 前端继续使用 Mock mutation | 刷新丢失、权限绕过、假成功 | 所有 mutation 必须有服务端 endpoint；没有接口就禁用 |
| Task 与 AgentRun 混为同一对象 | 重试、取消和多次执行无法表达 | Task 1:N AgentRun；Run 只拥有执行生命周期 |
| 同时编辑覆盖 | 丢失用户修改 | `expected_version` + SQLite 事务 + 409 |
| 依赖形成环 | 任务永远无法开始 | 服务端写入前做同项目 DAG 环检测 |
| 列表逐任务拉详情 | 任务量增长后请求爆炸 | 列表和详情使用聚合接口、分页和批量查询 |
| 假统计 | 用户误判项目和 Agent 质量 | 只从 Task/AgentRun/Audit 推导；不足时显示无数据 |
| Provider 故障 | 任务页面不可用或状态错误 | 任务读取不依赖 Provider；执行失败单独降级 |
| 暂停 Agent 误取消运行 | 丢失正在执行的工作 | Agent 接单状态与 Run 取消分离 |
| 当前工作区脏改动冲突 | 覆盖研究编排和 Workspace WIP | 在独立 worktree 开发并单独审查 |
| Demo 文件未跟踪 | 视觉基准丢失 | 实施开始前把批准的整合 Demo 纳入任务分支或保存验收截图 |

## 18. 扩展与故障攻击

### 18.1 外部依赖失败

任务读取、编辑和人工管理不依赖 LLM、O2 或 Web Provider。外部能力不可用时，只禁用对应的 `start_agent_run` 或显示 Run 失败；任务、协作、审批和历史仍可访问。

### 18.2 十倍数据量

首个瓶颈会是从 JSON records 扫描任务并聚合详情。首期通过项目过滤、分页、单次批量加载和避免 N+1 控制；不提前引入新数据库。真实任务量证明扫描成为瓶颈后，再为 Task 项目、交付阶段、负责人和截止时间增加 SQLite 表或表达式索引。

### 18.3 回滚成本

任务中心采用可选字段和新增路由，不改变旧状态枚举。回滚时移除导航和 `/tasks` 路由、停止新 mutation 即可；已有管理元数据仍留在 JSON payload 中并被旧代码忽略。不得通过回滚删除任务、Run、审计或知识关系。

## 19. Worktree 与交付纪律

文档生成时主分支基线为 `67537c9`，当前工作区存在其他未提交修改。实施时执行以下隔离策略：

1. 重新读取 `git status --short --branch -uall` 和当前 HEAD。
2. 若 HEAD 仍为 `67537c9`，从该提交创建 `agent/task-center-integration` 分支和 `.worktrees/task-center-integration` worktree。
3. 若 HEAD 已前进，先检查新提交是否改变 Task、AgentRun、Blackboard 或前端路由，再从审核后的新 HEAD 创建同名任务分支。
4. 不复制、stash、清理或覆盖主工作区的未提交文件。
5. 每个阶段使用独立、可审查提交；阶段结束必须处于可运行状态。
6. 合并前运行完整验证，并检查生成 OpenAPI 类型是否与后端一致。
7. 未经明确授权不提交、不推送、不合并、不发布。

## 20. 发布与回滚

### 20.1 发布顺序

1. 合并后端只读接口与测试。
2. 生成并提交 OpenAPI 类型。
3. 合并 React 只读任务中心，完成真实浏览器验收。
4. 依次合并核心 mutation、Agent 执行和跨模块闭环。
5. 每个阶段上线后观察 401/403/409/422/5xx、Task 查询耗时和 AgentRun 失败率。

### 20.2 回滚

- 前端异常：回退 `/tasks` 导航与路由，原有模块继续工作。
- 读取接口异常：回退 tasks router，协作网络继续使用 Blackboard 原接口。
- mutation 异常：禁用任务写入口，保留只读中心和已有数据。
- Agent 联动异常：停止从任务创建新 Run，已有 Run 继续由原 AgentRun 控制面管理。
- 任何回滚都不得重写或删除运行中的 AgentRun、审批和审计记录。

## 21. 依赖与凭据

- 不新增 npm 或 Python 依赖。
- 不新增环境变量和前端构建开关。
- 不需要新的 API Key、OAuth 应用、O2 Token、MCP Server 或第三方账号。
- 真实 Provider smoke 只在验证 Agent 执行联动时使用项目已有配置；任务管理核心测试全部使用 mock/fake provider。

## 22. 承重假设

本方案假设 FastAPI/SQLite 继续是本轮唯一业务真相，并且任务中心服务的是当前 AgentMesh 项目数据。

如果数据实际必须来自 designOS、另一套 PostgreSQL 服务或跨 Workspace 调度，本方案的数据模型、权限、迁移和回滚边界不再成立；应先定义外部 API 与身份映射，再单独制定集成方案，不能把两项迁移放在同一实施批次。

## 23. 完成定义

只有同时满足以下条件，才能声称“任务中心已经接入项目”：

- React 产品代码中存在 `/tasks` 路由和主导航入口。
- 页面使用真实 `/api/tasks` 数据，不包含业务 Mock mutation。
- 创建、编辑、分派、迁移、归档和 Agent 执行均持久化。
- 原有模块保留且回归通过。
- 任务详情可以追溯到 Run、协作、审批、产物和知识。
- 权限、状态迁移、并发和审计由服务端权威控制。
- OpenAPI 类型、后端测试、前端测试、生产构建和 E2E 全部通过。
- 浏览器在 390px、768px 和 1512px 下完成手工验收。
- `CONTEXT.md` 与 ADR 已更新为代码现实。

在这些条件完成之前，准确状态只能表述为“任务中心方案或原型”，不能表述为“已实现”或“已接入真实数据”。
