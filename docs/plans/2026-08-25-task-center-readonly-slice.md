# 任务中心只读切片开发计划

- 日期：2026-08-25
- 基线：`67537c9`
- 状态：已完成
- 目标：基于现有 Task 与 Blackboard 能力，交付可独立上线的只读任务观察中心

## 1. 产品边界

`/tasks` 展示当前账号在默认项目中可见、且由现有 Agent 或协作流程产生的任务。它是观察入口，不是通用项目管理系统。

本切片提供：

- 看板和列表两种视图。
- 按真实 `collaboration_stage` 分组。
- 将 `Task.status` 明确标为执行状态，与协作阶段分开展示。
- 标题搜索、执行状态筛选、协作阶段筛选。
- 当前协作负责人、完成条件、执行锁、步骤和时间戳。
- 只读详情抽屉，以及服务端已过滤的 Blackboard 时间线。
- 加载、空数据、无匹配结果、404、错误和重试状态。
- 桌面端与窄屏布局。

本切片不提供：

- 创建、编辑、分派、归档或状态迁移。
- 交付阶段、优先级、截止日期、日历、依赖、子任务或里程碑。
- Agent 队列、容量、成功率、耗时或工作量统计。
- Run、Inbox、Memory、Artifact、Audit 聚合。
- 新数据库字段、迁移、新 API、OpenAPI 变更或前端模拟数据。

## 2. 数据契约

仅复用现有接口：

- `GET /api/blackboard/task-cards?project_id={project_id}`
- `GET /api/blackboard/tasks/{task_id}`

字段映射：

| 界面语义 | 服务端字段 | 规则 |
| --- | --- | --- |
| 标题 | `task.title` | 原样显示 |
| 执行状态 | `task.status` | 不映射成交付阶段 |
| 协作阶段 | `stage`，回退 `task.collaboration_stage` | 看板唯一分组依据 |
| 协作负责人 | `owner`，回退 `task.current_owner_label` | 为空时显示未指定 |
| 完成条件 | `done_when`，回退 `task.done_when` | 为空时诚实显示未设置 |
| 执行锁 | `active_lock`，回退 `task.execution_lock` | 仅展示，不提供操作 |
| 协作记录数 | `post_count` | 只能统计当前用户可见帖子 |
| 步骤 | `task.steps` | 保持服务端顺序 |
| 时间 | `task.created_at`、`task.updated_at` | 本地化显示，缺失时不推断 |
| 时间线 | 详情接口的 `posts` | 只使用服务端过滤结果 |

安全前置修复：`BlackboardTaskCard.latest_post`、`post_count` 和帖子参与者摘要只使用当前用户可见的帖子，防止私有帖正文或存在性通过卡片泄漏。`Task` 上的协作阶段、负责人和执行锁仍是任务级协调事实；隐藏帖子持有全局执行锁时，不向无权查看该帖的用户返回其目标 ID 或操作入口。

## 3. 前端结构

- `App.tsx` 懒加载 `/tasks`，避免主包继续增长。
- `Sidebar.tsx` 增加“任务中心”入口。
- `features/tasks/presenter.ts` 负责纯数据派生、稳定排序、筛选、标签和未知值回退。
- `pages/Tasks.tsx` 负责查询状态、URL 页面状态和视图组合。
- 任务卡、列表和详情抽屉保持只读，不复用协作网络中的 mutation 组件。

视觉方向：延续现有 AgentMesh 深色运维界面，采用紧凑信息密度、背景层级和细分隔线，不新增装饰性渐变或独立设计系统。交互以清晰焦点和按压反馈为主，抽屉沿用现有短时过渡。

## 4. 状态与错误

- 首次查询显示任务骨架或明确加载文案。
- 列表请求失败时保留错误信息与重试按钮。
- 项目无任务与筛选无结果使用不同空态。
- 详情 404 显示“任务已不存在或当前账号不可见”，允许关闭或重试。
- 未知执行状态或协作阶段显示原始值或“未知”，不静默归类为完成。
- 搜索与筛选只作用于服务端已返回的可见任务集合。

## 5. 验收与测试

后端：

- 混合公开与私有帖子时，普通成员的卡片不泄漏私有帖正文和数量，同时仍能看到防止重复执行所需的任务级锁状态。
- 兼容 actor 为 `personal_agent` 的旧私有帖时，只允许任务发起人读取，不能跨普通成员泄漏。
- 详情时间线与卡片统计使用一致的可见集合。
- `/tasks` 深链由 FastAPI 返回 React index，未知非产品路径仍返回 JSON 404。

前端：

- Presenter 覆盖分组顺序、执行状态与协作阶段分离、搜索、筛选、统计和未知值。
- E2E 覆盖真实接口、看板/列表切换、筛选、详情时间线、错误重试和窄屏。
- 生产构建通过 bundle 预算，现有路由和协作页面不回归。

验证命令：

```bash
.venv/bin/python -m pytest tests/test_frontend_routes.py tests/test_read_models.py tests/test_mvp_knowledge_collaboration_contracts.py
.venv/bin/python -m pytest tests/test_chat_flow.py -k task_cards
npm --prefix agentmesh-demo test -- src/features/tasks/presenter.test.ts
npm --prefix agentmesh-demo run build
npm --prefix agentmesh-demo run test:e2e -- task-center-readonly.spec.ts
.venv/bin/python -m pytest
.venv/bin/ruff check .
npm --prefix agentmesh-demo test
```

## 6. 回滚

该切片不含数据迁移和新写接口。功能回滚时只移除 `/tasks` 路由、导航、页面与 presenter；Blackboard 可见性安全修复必须独立保留。
