# AgentMesh 独立项目任务与记忆闭环开发方案

- 日期：2026-08-31
- 状态：已批准；Slice 1～5 已合并，当前停在 Slice 5 检查点
- 基线：`main` at `ce780c975811e91d4c0a10f408a8cfa4309fd136`
- 目标：在 AgentMesh 可独立安装和运行的前提下，打通“任务创建、Agent 执行、产物审核、记忆沉淀、后续复用、全程审计”的真实产品闭环
- 适用范围：FastAPI、React、SQLite、Agent Runtime v2、Task Center、Artifact、Inbox、Memory/RAG
- 相关方案：`docs/plans/2026-08-25-task-center-integration-plan.md`、`docs/memory-optimization-plan.md`

## 1. 决策摘要

AgentMesh 继续作为独立产品运行。FastAPI 和 SQLite 是业务状态的唯一事实源，React 只消费服务端公开投影。Task、Review、Memory 和 Audit 的核心读写不得依赖 LLM、Embedding、Web、O2、MCP、Data Provider、DesignOS 或其他项目的数据库。

本方案不先建设大而全的项目管理界面，而是按以下纵向链路交付：

```text
创建 Task
  → 分派给人或 Agent
  → 创建 AgentRun
  → 产生并封存 Artifact
  → 发起 TaskReview
  → 人工接受或要求修改
  → 创建个人记忆或团队知识候选
  → 完成 Memory Review
  → 后续 Task/Run 检索并引用 Memory
  → 记录 MemoryUseReceipt 与 AuditEvent
```

每个纵切都必须可独立合并。后续纵切停止时，已经合并的功能仍然可用，不依赖尚未完成的下一阶段。

## 2. 当前基线

### 2.1 已具备

- React `/tasks` 只读任务中心，支持看板、列表、搜索、筛选和任务详情。
- `Task`、`BlackboardPost`、执行锁和协作交接。
- `AgentRun`、Plan、SSE、重试、取消、durable dispatch 和 terminal output projection。
- `Artifact` 及 Run 血缘。
- `UserMemoryItem` 个人短期、中期、长期记忆。
- `MemoryItem` 项目和团队候选、团队接受记忆。
- `MemoryRelation`、Source、AuditEvent 和 Inbox。
- SQLite FTS5、可选向量检索、RRF、检索预算、AgentMemoryBinding 和 RetrievalMetrics。
- 团队记忆人工接受、个人记忆分享到项目候选、日报和项目摘要。

### 2.2 主要缺口

- Task Center 没有创建、编辑、分派、状态迁移和归档。
- `Task` 没有独立的项目交付生命周期和并发版本。
- `AgentRun` 没有不可变 `task_id`。
- Artifact 没有面向项目交付的人工审核对象。
- Task Review 和 Memory Review 尚未分离。
- Memory 血缘不能完整表达 Task、Run、Artifact、Review 和内容 Hash。
- `UserMemoryItem` 与 `MemoryItem` 缺少统一公开投影。
- `RetrievalService` 与旧 `_search_team_brain()` 两条检索路径并存。
- Scope 下钻与 MemoryLayer 分层混用。
- 缺少 accepted Memory 的 revision、supersedes、merge、archive 和 restore 合同。
- 缺少证明某一版 Memory 实际进入某个 Run 上下文的不可变回执。

### 2.3 Memory 框架决策

当前 Memory 是 AgentMesh 自研的治理型 Memory/RAG 实现，底层使用 Pydantic、SQLite records、FTS5、可选 Embedding、向量 BLOB 和 RRF。它参考过 TencentDB-Agent-Memory 的分层检索、预算、Agent Binding 和冷启动思想，也参考 LangGraph 将运行检查点与长期 Memory 分离的原则，但没有引入 Mem0、Zep、LangMem 或 LangGraph 运行时。

本方案保留 AgentMesh 对权限、审核、版本、血缘和审计的所有权。未来成熟 Memory 产品只能作为检索或索引 Adapter，不能成为 Task、Review、Memory 状态和权限的事实源。

## 3. 独立运行合同

“独立运行”指运行时不依赖其他业务系统或外部凭据，不表示没有 Python、npm 等构建依赖，也不表示已经具备多租户和高可用能力。

每个纵切合并时都必须满足以下条件：

1. Fresh clone 可以完成 Python clean install、前端 `npm ci` 和生产构建。
2. 未配置真实 Provider 时，应用可以启动并完成 Task、Review、Memory 和 Audit 的人工流程。
3. FastAPI 可以同源托管 React 生产构建和产品 deep link。
4. 所有业务状态只写当前配置的 SQLite。
5. Provider 不可用时，只禁用对应自动能力，不影响已有任务和记忆的读取与人工管理。
6. FTS5 是 Memory 基础检索路径，Embedding 和 Vector 只是可选增强。
7. 自动化测试不访问真实 LLM、Embedding、Web、O2、MCP 或 Data Provider。
8. 备份和恢复不依赖外部平台。
9. Universal 编排保持独立开关，Task/Memory 开发不得绕过生产门禁。
10. 每个新增外部后端都位于 Adapter seam 后，不能拥有 AgentMesh 的权限、审核、版本和审计事实。

新增 CI 验证面 `standalone-product-smoke`。它使用临时 SQLite 和 fake provider，逐步覆盖当前已经交付的闭环步骤。

## 4. 领域语言与不变量

### 4.1 Project Task

Project Task 是持久化项目工作项，表示“需要交付什么”。它不是 Task Catalog 中用于意图分类的 Task ID。

现有 `Task.thread_id` 保持必填。人工创建 Task 时，服务端在同一事务创建 `kind=task` 的 ChatThread。Task 的 Workspace 和 Project 归属以该 Thread 为权威，不增加一组可能漂移的重复字段。

### 4.2 三种状态

| 状态 | 所有者 | 含义 |
| --- | --- | --- |
| `Task.status` | 现有执行流程 | 当前执行是否创建、运行、等待、汇总、完成或失败 |
| `Task.collaboration_stage` | Blackboard 协作 | 当前讨论、执行、审核、阻塞或协作完成阶段 |
| `Task.management.delivery_stage` | 项目管理 | backlog、planned、in_progress、review、done、cancelled |

三种状态不能互相覆盖。`blocked_reason` 和 `blocked_at` 是交付状态之外的正交字段，不增加第二个“blocked 交付阶段”。

### 4.3 AgentRun

AgentRun 表示 Task 的一次执行尝试。一个 Task 可以没有 Run，也可以拥有多个 Run。Run 创建后绑定的 `task_id` 不可修改，retry 必须继承来源 Run 的 `task_id`。

Run 失败或取消不能自动取消 Task。Run 完成也不能直接把 Task 标记为 `done`。

### 4.4 Artifact

Artifact 是 Run 产生的不可变产物。Task 通过 `AgentRun.task_id` 推导 Artifact 归属，不在 Artifact 上复制 `task_id`。只有 `sealed` Artifact 可以进入 Task Review。

### 4.5 Task Review

Task Review 判断 Artifact 是否满足 Task 的交付要求。它不负责决定内容能否成为团队知识。

状态：

```text
pending
accepted
changes_requested
rejected
```

`accepted` 可以推动 Task 进入 `done`。`changes_requested` 把 Task 返回 `in_progress`。审核必须绑定 Artifact ID 和 content hash，不能只引用可变标题。

### 4.6 Personal Memory、Memory Candidate 与 Team Knowledge

- Personal Memory 使用 `UserMemoryItem`，只对所有者可见。
- Memory Candidate 使用 `MemoryItem(status=proposed, scope=team_candidate)`。
- Team Knowledge 使用 `MemoryItem(status=accepted, scope=team_accepted)`。
- Task Review 通过不自动发布 Team Knowledge。
- Team Knowledge 必须经过独立 Memory Review。
- Accepted Memory 正文不可原地覆盖。纠错通过新 revision 和 `supersedes` 关系完成。

### 4.7 Inbox 与 Audit

Inbox 是待办投影，不是 Task、Review 或 Memory 的事实源。AuditEvent 记录命令结果和对象身份，不存储敏感正文，也不承担状态恢复。

## 5. 目标架构

```text
React Task Center / Memory Center
                │
                ▼
        FastAPI thin routes
                │
       ┌────────┼─────────┐
       ▼        ▼         ▼
TaskManagement  TaskCompletion  MemoryContext
    Service         Service         Service
       │              │               │
       │              ├── AgentRun    ├── FTS5
       │              ├── Artifact    ├── Optional Vector Adapter
       │              ├── TaskReview  ├── MemoryUseReceipt
       │              └── Memory      └── Citation
       │
       └──────────── SQLiteStore ─────────────┐
                                              ▼
                              Task / Run / Artifact / Review
                              Memory / Relation / Receipt / Audit
```

### 5.1 TaskManagementService

Interface：

```text
create_task(command, actor) -> TaskViewV1
update_task(task_id, command, actor) -> TaskViewV1
transition_task(task_id, command, actor) -> TaskViewV1
archive_task(task_id, command, actor) -> TaskViewV1
get_task(task_id, actor) -> TaskDetailViewV1
list_tasks(query, actor) -> TaskPageV1
```

模块内部负责兼容投影、授权、状态机、依赖检查、版本 CAS、allowed actions、审计和列表投影。路由和 React 不复制这些规则。

### 5.2 TaskCompletionService

Interface：

```text
submit_review(command, actor) -> TaskReviewViewV1
decide_review(command, actor) -> TaskReviewViewV1
capture_memory(command, actor) -> MemoryEntryViewV1
```

模块内部负责 Task、Run、Artifact、Review、Inbox、Memory 和 Audit 的跨对象事务。一次命令只能产生一个稳定结果，重放返回原结果。

### 5.3 MemoryContextService

Interface：

```text
retrieve_for_run(query, user, agent, task, budget) -> MemoryContextBundleV1
get_memory(memory_id, actor) -> MemoryEntryViewV1
list_memory(query, actor) -> MemoryPageV1
transition_memory(command, actor) -> MemoryEntryViewV1
get_lineage(memory_id, actor) -> MemoryLineageViewV1
```

模块内部负责 Scope、MemoryLayer、状态、AgentMemoryBinding、FTS/Vector/RRF、上下文预算、Citation、Metrics 和 MemoryUseReceipt。

`agentmesh/agents.py::_search_team_brain()` 逐步改成兼容调用，最终删除其中重复的权限和排序逻辑。

## 6. 数据合同

### 6.1 TaskManagementMetadataV1

```text
schema_version = task-management-v1
description: string <= 4000
task_type: design | research | data | risk | review | project_action | milestone
delivery_stage: backlog | planned | in_progress | review | done | cancelled
priority: p0 | p1 | p2 | p3 | null
due_at: datetime | null
assignee_kind: user | agent | null
assignee_id: string | null
tags: unique string[], max 12
parent_task_id: string | null
dependency_task_ids: unique string[]
blocked_reason: string | null
blocked_at: datetime | null
version: integer >= 1
archived_at: datetime | null
created_by: user_id
updated_by: user_id
```

`assignee_kind` 与 `assignee_id` 必须同时为空或同时存在。用户负责人必须是当前项目成员；Agent 负责人必须是当前用户的 Personal Agent 或当前项目允许使用的公共 Agent。

### 6.2 TaskReviewV1

```text
schema_version = task-review-v1
id
task_id
run_id
artifact_ids
artifact_hashes
round
status
requested_by
reviewer_id
task_version
decision_note
version
created_at
updated_at
decided_at
```

同一 Task 可以有多轮 Review。每轮必须引用同一 Workspace/Project 下的 Run 和 sealed Artifact，并冻结进入审核时的 Task management version；审核期间普通 Task mutation 被拒绝，避免交付要求漂移。

### 6.3 MemoryProvenanceV1

作为 `UserMemoryItem` 和 `MemoryItem` 的可选结构化字段：

```text
source_kind: manual | task_artifact | memory_revision | imported_document
task_id: string | null
run_id: string | null
review_id: string | null
artifact_ids: string[]
artifact_hashes: string[]
source_memory_ids: string[]
created_by: user_id
created_at
```

旧 Memory 没有 provenance 时按 `legacy_unverified` 展示，不能伪造来源。

### 6.4 MemoryRevisionV1

现有 Memory 记录增加：

```text
version: integer >= 1
supersedes_memory_id: string | null
archived_at: datetime | null
archived_by: user_id | null
```

Accepted Memory 修订时创建新记录。旧记录进入 `deprecated`，并保留可导航关系。

### 6.5 MemoryUseReceiptV1

```text
schema_version = memory-use-receipt-v1
id
run_id
task_id
memory_id
memory_version
memory_hash
retrieval_reason
citation_label
agent_id
created_at
```

Receipt 是不可变事实。Memory 后续修订不能改写历史 Run 当时使用的版本。

## 7. API 合同

### 7.1 Task API

| 方法与路径 | 用途 |
| --- | --- |
| `GET /api/tasks` | 分页、筛选和统计 |
| `GET /api/tasks/{task_id}` | 聚合详情 |
| `POST /api/tasks` | 创建 Task 与 task-kind Thread |
| `PATCH /api/tasks/{task_id}` | 编辑管理字段 |
| `POST /api/tasks/{task_id}/transitions` | plan、start、submit_review、complete、reopen、block、unblock、cancel |
| `POST /api/tasks/{task_id}/archive` | 软归档 |

所有 POST mutation 包含 `command_id`。更新和 transition 包含 `expected_version`。

列表响应：

```text
items
total
page
page_size
has_next
counts
```

详情响应包含 Task、Run 摘要、Artifact 摘要、Review、Memory link、Blackboard 摘要和 Audit timeline。列表不能逐 Task 请求详情。

### 7.2 AgentRun API

继续使用：

```text
POST /api/agent/runs
```

`AgentRunCreateRequest` 增加可空 `task_id`。服务端验证 Task 可见性和 Workspace/Project 一致性。Retry 忽略客户端 task_id，只继承来源 Run。

### 7.3 Review API

| 方法与路径 | 用途 |
| --- | --- |
| `POST /api/tasks/{task_id}/reviews` | 选择 Run 和 Artifact 发起审核；只有 Run owner 可显式提交跨用户审核 |
| `GET /api/task-reviews/{review_id}/artifacts/{artifact_id}` | assigned reviewer 按冻结 ID/hash 检查单个产物，不授予通用 Run 访问 |
| `POST /api/task-reviews/{review_id}/decisions` | accepted、changes_requested、rejected |
| `POST /api/task-reviews/{review_id}/memory-candidates` | 从已接受产物创建个人记忆或团队候选 |

### 7.4 Memory API

保留现有 `/api/memory` 兼容接口，新增统一读取和治理能力：

| 方法与路径 | 用途 |
| --- | --- |
| `GET /api/memory` | 统一分页列表 |
| `GET /api/memory/{memory_id}` | 统一详情与 allowed actions |
| `GET /api/memory/{memory_id}/lineage` | 来源、版本和使用关系 |
| `POST /api/memory/{memory_id}/transitions` | accept、dispute、deprecate、expire、archive、restore |
| `POST /api/memory/{memory_id}/revisions` | 创建修订版 |
| `POST /api/memory/merge` | 合并重复 Memory，生成新版本 |

## 8. 权限合同

新增权限动作：

```text
manage_project_tasks
review_task_deliverables
accept_team_memory
manage_team_memory
```

规则：

- 项目成员可以创建 Task，编辑自己创建或分派给自己的 Task。
- 用户可以分派给自己或自己的 Personal Agent。
- Team Lead/Admin 可以管理项目内全部 Task，并分派公共 Agent。
- 跨成员改派、强制完成和归档需要 `manage_project_tasks`。
- Review 只能由服务端计算的 reviewer 执行。
- Personal Memory 只有所有者可见。
- Team Candidate 对作者、Team Lead 和 Admin 可见。
- Team Knowledge 按 Workspace、Project、Team membership 过滤。
- Task 访问权限不能扩大 Memory 权限，Memory 权限也不能反向授予 Task 权限。
- 无权访问与对象不存在统一返回 `404`。
- 每次 mutation 在提交前重新授权，不能信任前端 allowed actions。

## 9. 幂等、事务与并发

### 9.1 命令身份

以下入口必须接受稳定 `command_id`：

- Task 创建
- Task transition
- AgentRun 从 Task 启动
- Review 发起和决策
- Memory Candidate 创建
- Memory transition、revision 和 merge

相同用户和 command ID 的重放只读返回原结果。相同 command ID 携带不同请求 Hash 时返回 `409`。

### 9.2 版本 CAS

Task、TaskReview 和可变 Memory 状态使用 `expected_version`。SQLite 在单个 `BEGIN IMMEDIATE` 中完成读取、比较、写入、AuditEvent 和相关 Inbox 更新。

### 9.3 跨对象原子性

以下操作不能拆成多个提交：

- Task 创建与 task-kind ChatThread 创建。
- Task Review 发起与 Task 进入 review。
- Review decision、Task transition 和 Inbox resolution。
- Memory Candidate 创建、provenance、relation、Inbox 和 AuditEvent。
- Memory accept、旧版本 deprecated 和新版本激活。

Embedding 和其他 Provider 调用不得位于 SQLite 写事务中。

## 10. Memory 检索合同

执行顺序：

```text
对象权限过滤
  → Memory 状态过滤
  → AgentMemoryBinding
  → Scope 过滤
  → MemoryLayer 策略
  → FTS5
  → 可选 Vector
  → RRF
  → 去重
  → top-k/字符预算
  → MemoryUseReceipt
  → 带 Citation 的模型上下文
```

基础预算：

```text
top_k <= 8
总标题和摘要 <= 8000 字符
单个摘要 <= 2000 字符
```

默认 Layer 策略：

1. Long-term accepted Team Knowledge 作为稳定背景。
2. Mid-term Project Memory 补充当前项目上下文。
3. Short-term Personal Memory 只在需要当前细节时下钻。
4. 用户显式指定 personal/project/team 时不跨 Scope 扩张。
5. Candidate、disputed、deprecated、expired 和 archived Memory 不进入自动上下文。

Embedding 不可用时稳定退回 FTS-only。向量结果不能绕过权限、状态和 AgentMemoryBinding。

## 11. 前端产品结构

### 11.1 Task Center

视图：

```text
overview
board
list
calendar
agents
```

Task 详情页签：

```text
工作项
执行记录
产物
审核
记忆
协作
审计
```

所有字段来自服务端 DTO。React 不推导权限、交付状态或完成条件。

### 11.2 Memory Center

统一导航：

```text
个人记忆
项目记忆
团队候选
团队知识
已归档/已失效
```

Memory 详情展示：

- 内容、Scope、Layer、状态和版本。
- 来源 Task、Run、Artifact 和 Review。
- 前一版和后一版。
- 审核历史。
- 被哪些 Task/Run 使用。
- 服务端 allowed actions。

治理 mutation 不做业务状态乐观更新。409 时保留用户表单并重新加载服务端版本。

## 12. 分阶段交付

### Slice 1：可写任务核心与 standalone smoke

状态：已通过 PR #18 合并。

交付：

- ADR 0011。
- TaskManagementMetadataV1、ChatThread kind、版本 CAS 和权限。
- Task CRUD、transition、archive 和统一 Task DTO。
- React 新建、编辑、分派和状态操作。
- `AGENTMESH_TASK_MANAGEMENT=read_only|write`，默认 `read_only`。
- 首条无 Provider standalone smoke。

独立价值：用户可以把 AgentMesh 当作基础项目任务系统使用。

### Slice 2：Task、AgentRun 与 Artifact

状态：已通过 PR #19 合并。

交付：

- AgentRun immutable `task_id`。
- Retry 继承关联。
- 从 Task 启动 Run。
- Task 详情展示 Run 和 sealed Artifact。
- Provider 不可用时诚实禁用自动执行，人工 Task 继续可用。

独立价值：Task 成为 Agent 执行的真实上下文。

### Slice 3：Artifact Review

状态：已通过 PR #20 合并；刷新期 stale-action 修复已通过 PR #21 合并。

交付：

- TaskReviewV1、审核接口和 Inbox 投影。
- Artifact ID/hash 冻结。
- accepted、changes_requested、rejected 状态机。
- Review decision 与 Task transition 原子提交。

独立价值：Agent 输出经过人工质量门后才能完成 Task。

### Slice 4：Memory Governance

#### Slice 4A：Review Capture 与独立 Memory Review

状态：已通过 PR #22 合并；Slice 4B 仍为独立后续增量。

交付：

- ADR 0012。
- `MemoryEntryViewV1`、`MemoryProvenanceV1` 和基础版本字段。
- 从 accepted Task Review 显式创建 Personal Memory 或 Team Candidate。
- Team Candidate 使用独立 `MemoryReviewV1`、Reviewer 与 Inbox，不复用 Task Review 结论。
- Task → Memory 与 Memory → Task/Run/Artifact/TaskReview 的导航和 lineage。
- Candidate/争议状态不进入 Agent 自动检索；Embedding 不可用时不影响治理流程。

独立价值：已验收交付可以安全沉淀为个人经验或进入独立团队知识审核。

#### Slice 4B：Revision 与完整生命周期

状态：已通过 PR #24 合并；Slice 5 仍为独立后续增量。

交付：

- revision 与 `supersedes_memory_id` 候选流程，冻结来源 Memory ID、版本和内容哈希。
- 新修订通过独立 Memory Review 后，原子激活新版本并废弃前一版。
- dispute、deprecate、expire、archive 和 restore 状态机；候选失效会取消待处理 Memory Review 和 Inbox。
- `manage_team_memory` 权限、服务端 `allowed_actions`、版本 CAS、稳定 command receipt 和 AuditEvent。
- Task、Run、Artifact、Task Review、前后版本与治理事件的双向 lineage。
- 服务端治理历史筛选和分页，以及 Knowledge Center 修订、状态操作和历史视图。
- 所有非 accepted 生命周期状态在 FTS、fallback 和 Vector 候选上限之前退出 Agent 自动检索。

独立价值：团队知识成为可修订、可撤回且保留历史的长期资产。

### Slice 5：Memory Reuse

状态：已合并并完成验证。

交付：

- 唯一 `MemoryContextService`，统一自动上下文、Runtime `memory_search` 与 legacy `_search_team_brain()`。
- Scope 与 MemoryLayer 独立投影及严格范围检索。
- `AGENTMESH_MEMORY_CONTEXT=off|observe|inject`，默认 `off`。
- `MemoryUseReceiptV1`，冻结 Run、Task、Memory 版本/hash、reason、query hash、citation、Agent 和实际暴露的 Source IDs；per-Run Citation 先以独立 reservation 事务化分配。
- MemoryLayer 独立于 Scope，在 ranking/candidate budget 前筛选；完整 rendered payload 受字符预算约束。
- Memory title/summary/Source metadata 先经过 credential 与 prompt-injection quarantine，被隔离内容不进入模型、不写 receipt。
- 显式 Runtime `memory_search` 在编码、大小、安全、审计和 Tool settlement 完成后才提交 receipt。
- Run 详情显示使用过的 Memory 版本、Citation、原始 Source 和输出引用状态。
- Memory lineage 显示当前用户可见的后续 Task/Run 使用记录。
- standalone smoke 完成“任务 A 产出，任务 B 通过 FTS 检索、记录回执并引用该 Memory”。

独立价值：团队经验开始减少后续任务的重复工作。

### Slice 6：完整项目管理和运营能力

交付：

- 子任务、依赖、环检测和关键路径。
- 里程碑、日历、项目总览和 Agent 队列。
- Task/Run/Review/Memory 指标。
- 分页和大数据量基准。
- 必要时增加可重建的 SQLite 查询投影或表达式索引。
- 清理跨页面重复状态推导和剩余 Mock。

独立价值：形成可日常使用的人机协同项目管理系统。

## 13. 测试矩阵

### 13.1 后端

- 旧 Task 无 management 时可读取，首次编辑无损物化。
- Task 创建与 Thread 创建同成同败。
- 并发更新中只有一个 expected version 成功。
- 非法状态迁移、跨项目分派、自依赖和依赖环失败。
- Run 与 Task 必须同 Workspace/Project，retry 不得改绑。
- Run 失败、取消或 partial 不伪造 Task 完成。
- 未 sealed Artifact 不能发起 Review。
- Review decision 重放不重复推进 Task。
- 未 accepted Review 不能创建团队候选。
- Team Candidate 未审核不能进入自动检索。
- Personal Memory 不跨用户泄漏。
- deprecated、expired、disputed Memory 不进入上下文。
- Memory revision 保留旧 Hash 和 supersedes 关系。
- MemoryUseReceipt 与实际传入模型的 Memory 集合一致。
- 所有 mutation 产生 AuditEvent，且 Audit metadata 不含敏感正文。

### 13.2 前端

- `/tasks` 所有视图刷新后保持状态。
- 创建、编辑、分派、transition、archive 使用真实 API。
- 401、403、404、409、422 和 503 有明确状态。
- 409 保留未提交表单。
- Task 详情可以导航到 Run、Artifact、Review 和 Memory。
- Memory Center 可以按 kind、layer、status 和 scope 筛选。
- Memory 详情展示 lineage、revision 和 usage。
- 390px、768px、1512px 可操作，无页面级横向溢出。
- 键盘可以完成 Dialog、Drawer、Review 和 Memory 操作。

### 13.3 独立运行 smoke

最终 smoke：

```text
无真实 Provider 启动
→ 登录
→ 创建并分派 Task
→ 手工完成 Task 或使用 fake AgentRun
→ 创建 sealed Artifact
→ 审核通过
→ 创建 Personal Memory
→ 提交 Team Candidate
→ 接受 Team Knowledge
→ 创建第二个 Task
→ FTS 检索并引用该 Memory
→ 重启服务
→ 所有状态、血缘和审计仍然存在
```

### 13.4 验证命令

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
npm --prefix agentmesh-demo run api:types
npm --prefix agentmesh-demo test
npm --prefix agentmesh-demo run build
npm --prefix agentmesh-demo run test:e2e
```

前端构建与 `tests/test_frontend_routes.py` 顺序执行，避免 Vite 替换 `dist/` 时产生竞态。

## 14. 性能与可观测性

首个规模基准使用：

```text
10000 Tasks
50000 Task/Audit events
10000 Memory records
1000 accepted Team Knowledge records
```

记录：

- Task 列表和详情 p50/p95。
- Memory FTS-only 和 hybrid retrieval p50/p95。
- SQLite 写锁等待。
- 单次 Agent 上下文 Memory 字节数。
- Memory 返回、引用和用户采纳比例。
- 409 冲突、Review changes requested、Memory deprecated 和 retrieval miss 比例。

如果 Task 聚合或 Memory hydration p95 超过 500 ms，先增加可重建查询投影和表达式索引，再评估独立数据库。没有基准证据时不提前引入 PostgreSQL、Redis、外部向量库或微服务。

## 15. 发布与回滚

### 15.1 发布顺序

```text
Task read_only
→ Task write 内部账号
→ Task write 全项目
→ Task 启动 AgentRun
→ Artifact Review
→ Personal Memory Capture
→ Team Candidate Review
→ Memory observe-only retrieval
→ Memory context injection
→ 高级项目管理视图
```

### 15.2 回滚

- Task mutation 异常时切回 `read_only`，保留已有 Task。
- Agent 联动异常时停止从 Task 创建新 Run，已有 Run 继续由 AgentRun 控制面管理。
- Review 异常时停止新 Review，已有 Artifact 和 Review 只读保留。
- Memory capture 异常时停止新 Candidate，不删除已接受 Memory。
- Memory retrieval 异常时回退 FTS-only 或停止 context injection。
- 回滚不删除 Task、Run、Artifact、Review、Memory、Receipt 或 AuditEvent。

Universal 编排继续遵循独立 runbook，生产环境保持：

```text
AGENTMESH_SKILL_ORCHESTRATION=off
```

## 16. 非目标

本方案不包含：

- 跨 Workspace 项目管理。
- 多实例共享 SQLite 或高可用。
- designOS 双写或外部项目管理系统同步。
- 物理删除 Task、Run、Review 或 Audit。
- 未审核内容自动发布为 Team Knowledge。
- 把 Mem0、Zep、LangMem 或外部向量库设为核心运行依赖。
- 在没有规模基准前迁移数据库。
- 在核心闭环完成前建设甘特图、复杂资源排期、工时计费或自动绩效评价。

## 17. 风险与应对

| 风险 | 应对 |
| --- | --- |
| 三套 Task 状态被混用 | ADR 0011 固定语义，服务端统一投影和 transition |
| Task 与 Run 双写漂移 | `AgentRun.task_id` 不可变，Task 不复制 Run 状态 |
| Review 与 Inbox 状态不一致 | Review 是事实源，Inbox 只在同一事务生成投影 |
| 错误 Artifact 进入团队知识 | sealed Artifact、Task Review、Memory Review 两道门 |
| Accepted Memory 被覆盖 | 新 revision + supersedes，旧版 deprecated |
| 私有记忆泄漏 | owner/project/team 过滤先于检索和向量排序 |
| Provider 故障阻断人工流程 | Task、Review、Memory 核心路径不调用 Provider |
| SQLite 查询随数据量恶化 | 固定规模基准，达到门槛后增加可重建投影或索引 |
| 新增配置过多 | 只新增 Task write 模式，Memory 依赖现有状态和权限 |
| 大型 PR 无法审查 | 每个 Slice 独立 PR，前一 Slice 合并后再开始下一 Slice |

## 18. 完成定义

只有以下路径在真实浏览器、服务重启和权限测试下全部通过，才能称为任务与记忆闭环完成：

```text
用户创建 Task
→ 分派 Personal Agent
→ 创建 AgentRun
→ 产生 sealed Artifact
→ 发起 Task Review
→ 审核通过并完成 Task
→ 创建 Personal Memory
→ 提交 Team Candidate
→ Team Lead 接受为 Team Knowledge
→ 第二个 Task 检索到该 Memory
→ Agent 输出引用 Memory 和原始 Source
→ Task 与 Memory 页面均可追溯完整 lineage
→ Audit 页面可还原全部状态变化
```

同时满足：

- 无 Provider 时人工闭环可用。
- 重放不产生重复副作用。
- 跨用户、项目和团队泄漏数为 0。
- 旧 Task、Run、Artifact 和 Memory 可继续读取。
- 所有新写入可通过关闭 mutation 安全停用。
- 主分支 Backend、Frontend、Playwright 和 Secret Scan 全部通过。

## 19. 交付顺序与工作量

| Slice | 主要结果 | 粗略工程量 |
| --- | --- | ---: |
| 1 | 可写 Task 核心与 standalone smoke | 4～6 工程日 |
| 2 | Task、AgentRun、Artifact 关联 | 3～5 工程日 |
| 3 | Artifact Review | 3～4 工程日 |
| 4 | Memory Governance | 5～7 工程日 |
| 5 | Memory Reuse 与 Use Receipt | 4～6 工程日 |
| 6 | 子任务、依赖、日历和运营视图 | 5～8 工程日 |

合计约 24～36 个工程日，不含真实 Provider 验收、多租户、高可用和外部部署门禁。每个 Slice 完成后重新估算剩余工作，不用总工期压缩审核、安全和兼容测试。

## 20. 实施入口

第一个实施 PR 从 Slice 1 开始，范围固定为：

1. ADR 0011。
2. TaskManagementMetadataV1 和 ChatThread kind。
3. TaskManagementService 与 `/api/tasks`。
4. 权限、allowed actions、command id 和 expected version。
5. Task Center 创建、编辑、分派和 transition。
6. 无 Provider standalone smoke。
7. OpenAPI、后端、前端、构建和浏览器测试。

该 PR 不包含 AgentRun 关联、Artifact Review、Memory Candidate、子任务、依赖、日历和 Agent 队列。这些能力按后续 Slice 独立交付。
