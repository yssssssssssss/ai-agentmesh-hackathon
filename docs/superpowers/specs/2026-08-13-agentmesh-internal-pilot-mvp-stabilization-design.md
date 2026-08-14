# AgentMesh Internal Pilot MVP Stabilization Design

> 日期：2026-08-13  
> 来源：`docs/project-audit-report.md`  
> 完整产品化路线：`docs/superpowers/plans/2026-08-13-agentmesh-audit-remediation-implementation-plan.md`

## 1. 目标

将 AgentMesh 收敛为可在企业内网小范围试用的单 Workspace MVP：多个真实用户可以通过新 React 前端登录、对话、调用真实 Provider、上传与检索资料、确认知识并查看协作状态；系统不会因 Provider 故障锁住 SQLite 或冻结 API，也不会让普通用户互读私聊和文档。

本设计不追求完整产品化。所有不影响内网试点安全、稳定和核心用户流程的能力延期。

## 2. 部署边界

MVP 只承诺以下运行环境：

- 企业内网，不开放公网。
- 小范围真实用户。
- 单 Workspace、单默认 Project。
- 单个 FastAPI 应用实例。
- 单 SQLite 数据库。
- 新 React 为默认入口。
- 旧 `app.html` 保留一个发布周期作为回滚入口。
- Embedding、O2 Research、Web Research 和外部 Data Provider 真实可配置。
- 自动化测试不调用真实 Provider，真实 Provider 通过独立 smoke 验证。

如果出现公网访问、多 Workspace、多应用实例或分布式 Worker 需求，本 MVP 设计自动失效，应切回完整产品化路线。

## 3. 核心原则

### 3.1 服务端是业务真相

FastAPI/SQLite 决定：

- 登录态。
- 对象 owner。
- PRIVATE 可见性。
- Memory 确认和共享。
- Blackboard 任务动作。
- Provider capability。
- Workspace/Project 上下文。

React 只消费资源和 allowed actions，不复制角色、状态机或权限判断。

### 3.2 单 Workspace 是明确限制

MVP 不建设通用多租户框架，但必须避免跨用户泄露：

- Chat thread owner-only。
- PRIVATE search owner-only。
- Document owner-only，除非明确共享到当前项目。
- Personal memory owner-only。
- Blackboard mutation 要求任务参与或管理 capability。

Workspace/Project 创建和切换不进入 MVP UI。README 和 CONTEXT 必须明确这一限制。

### 3.3 Provider 故障不能拖垮主链

真实 Provider 包括：

- Embedding。
- O2 Research 和 Web Research。
- 外部 Data API。
- 可配置 LLM。

每类 Provider 必须具备：

- Server-side secret。
- Health 状态。
- Timeout。
- 明确来源标记。
- 失败原因。
- 安全 fallback 或 fail closed。

Embedding 和文档解析不得在 SQLite 写事务或 FastAPI 事件循环中执行。

## 4. MVP 用户流程

### 4.1 登录

1. 用户访问 React 根页面。
2. React 调用 `/api/auth/me` 恢复 Cookie session。
3. 未登录时展示本地账号或 OAuth 登录入口。
4. 登录后读取 bootstrap、当前用户、默认项目和 capabilities。
5. 401 清空前端缓存并回到登录页。
6. 403 保持登录态并展示无权限。

Demo 账号只在显式 demo mode 创建。源码和生产默认配置中没有固定管理员密码。

### 4.2 Workspace 对话

1. 用户创建或选择自己的 thread。
2. 输入自然语言或显式 `$` Skill。
3. 服务端校验 thread owner 后读取历史。
4. PersonalAgent 执行本地记忆、Provider 或工作流。
5. 返回 user message、assistant message、task、sources 和 workflow trace。
6. React 用服务端结果替换 pending 消息。
7. 刷新页面后会话和消息仍存在。

MVP 不执行 LearnedSkill。LearnedSkill 继续保存和管理，但不进入聊天路由，UI 标注为实验性或隐藏。

### 4.3 真实 Provider 调用

每次 Provider 结果必须附带：

- Provider 名称。
- Real/mock/fallback 模式。
- Source 标题与 reference。
- 调用耗时。
- 错误或 fallback 原因。

规则：

- Embedding 不可用时检索回退 FTS5，并在健康状态中显示 degraded。
- O2 Research 或 Web Research 单路不可用时，可以回退到另一条真实 Research 通道；两条都不可用时只能返回明确标记的 mock/local fallback 或可解释失败。
- Data Provider 未授权时 fail closed，不使用服务器凭据代理普通用户越权读取。
- LLM 不可用时返回确定性 fallback，并保留来源。

### 4.4 文档上传和检索

1. 用户上传受支持文件。
2. 应用在读取和解压前执行大小预算。
3. 文档进入 parse job。
4. 解析、切片和 embedding 在有界后台执行。
5. Job 进入 completed 或 failed，不能永久 running。
6. 用户只能读取自己的文档。
7. Search 只返回当前用户可见资源。

MVP 只要求完整导入或明确失败，不建设复杂的跨版本编辑历史。文档正文修改后必须使旧 chunks/vector 失效，并允许重新导入。

### 4.5 Knowledge

MVP 支持：

- Inbox 列表。
- Brief 确认。
- Personal memory 概览。
- Project/team candidate 展示。
- Team Lead 接受 candidate。
- Snooze、resolve 和 prompt-injection review。

Memory 状态只开放 MVP 必需路径：

```text
proposed/team_candidate -> accepted/team_accepted
open -> snoozed/resolved
```

`draft`、`expired`、`deprecated` 等通用状态不进入 MVP UI。任何共享或接受动作由服务端 allowed actions 决定。

### 4.6 Collaboration

MVP 支持：

- Task cards。
- Task detail。
- Blackboard timeline。
- Reply。
- Lock/unlock。
- Handoff。
- Market status 和 participation。

所有 mutation 复用统一对象授权。Auto-post review/drain 只对管理员或治理 capability 开放。

MVP 不支持：

- Delegated answer adoption。
- Contribution points。
- Lineage UI。
- 跨 Workspace market。

### 4.7 Digital Self 和 Insights

MVP 只提供真实只读投影：

- 当前用户和 Personal Agent。
- 当前项目。
- 活动、任务和记忆计数。
- Provider/Agent runtime 状态。
- 最近审计记录。

不提供：

- 可编辑数字人理解。
- 持久化偏好。
- 项目复盘生成候选。
- 影响力积分模型。

没有后端资源的区域显示明确空态，不使用 mock、定时器或假成功按钮。

### 4.8 最小 Admin

MVP Admin 只支持：

- 用户列表、创建、禁用和密码重置。
- Agent model/tool 查看与基础配置。
- Provider health。
- O2 sync。
- Risk/permission policy 查看。
- Audit 查看。

不支持：

- 多 Workspace 管理。
- 完整 Team/Project CRUD。
- Scheduled task UI。
- 完整策略编辑器。

每个入口使用独立 capability，不使用一个 `manage_users` 覆盖全部后台。

## 5. 安全边界

MVP 上线前必须关闭：

- 源码 Embedding API key。
- 固定生产管理员密码。
- Chat thread owner IDOR。
- PRIVATE search 跨用户泄露。
- Document list/detail 横向读取。
- Memory 直接 TEAM_ACCEPTED 创建。
- Memory 任意降级/隐藏。
- Blackboard actor 伪造和无权限 mutation。
- 匿名 Market board。
- OAuth 自动恢复 disabled 用户。
- Data Provider 无 Agent grant 调用。

MVP 接受的风险：

- 单 Workspace，不实现通用多租户隔离框架。
- 单应用实例，不实现分布式 Worker lease。
- SQLite 单写者限制，但写事务必须短且不含网络调用。
- Provider smoke 依赖内网运行环境，CI 只验证 mock 合同。

## 6. 前端范围

React MVP 包含五个完整主链：

1. Auth/Shell。
2. Workspace。
3. Knowledge。
4. Collaboration。
5. Minimal Admin。

Digital Self 和 Insights 为真实只读页面。

React 必须删除或隐藏：

- `mockData` 业务数据。
- `DemoContext` 业务计数器。
- Timer 假生成。
- Handler-less 按钮。
- Toast-only 业务成功。

旧 `app.html` 在 React 主链、角色矩阵和浏览器测试通过后切换到 `/legacy/app.html`。一个发布周期后删除。

## 7. 错误处理

### 7.1 API

- 400：显示具体输入问题。
- 401：清 session UI 和 Query cache。
- 403：保持登录态，隐藏数据不丢失。
- 404：对象不存在或不可见。
- 409：刷新 canonical state，提示并发或重复操作。
- 502/503：显示 Provider 名称、状态和 fallback。

### 7.2 Provider

Provider 错误不能写入假成功结果。每个任务记录：

- requested provider。
- actual provider。
- fallback reason。
- latency。
- source IDs。

### 7.3 Document Job

Job 必须进入终态：

```text
queued -> running -> completed | failed
```

Unexpected exception 也进入 failed，并保留可重试标记。

## 8. MVP 修复任务

计划压缩为 11 项：

1. 安全配置与 Demo mode。
2. Chat/Search/Document 跨用户隔离。
3. Memory/Blackboard/Market/OAuth 最小 guard。
4. Provider 配置、Health、来源和授权。
5. Embedding 与文档后台化和数据一致性。
6. React Auth/API/Query 基础。
7. Workspace 真实接线。
8. Knowledge/Collaboration 真实接线。
9. Digital Self/Insights 只读和最小 Admin。
10. React 切换、生产 mock 清理和旧 UI 回滚。
11. Ruff、最小 CI、真实 Provider smoke 和发布门禁。

## 9. 测试策略

### 9.1 Backend Contract

必须覆盖：

- 两个用户互相访问 thread、search、document。
- Memory 未授权 create/transition。
- Blackboard 未授权 lock/unlock/reply/handoff。
- OAuth disabled user。
- Anonymous market board。
- Connector without grant。
- Provider timeout/fallback/provenance。
- Embedding 不持 SQLite 写锁。
- Document job terminal state。

### 9.2 Frontend

Vitest 覆盖 API/client/query 基础状态。Playwright 覆盖：

- 登录、刷新、退出。
- 创建 thread、发送、Skill、刷新恢复。
- 上传、Job 状态、搜索来源。
- Brief 确认和 Team Lead 接受。
- Task detail、reply、lock/handoff。
- 普通用户和管理员权限差异。
- 390px、768px、1512px 基础布局。

### 9.3 Real Provider Smoke

不进入普通 CI，由内网环境执行：

- 一个 Embedding 请求和一次检索。
- 一个 O2 Research 请求和一个 Web Research 请求。
- 一个外部 Data API 请求。
- 一个真实 LLM 请求。

每个 smoke 验证 source、provider mode、latency 和错误可见性，不写真实 secret 到日志。

## 10. 发布门禁

```bash
AGENTMESH_EMBEDDING_ENABLED=false .venv/bin/python -m pytest
.venv/bin/ruff check .
cd agentmesh-demo
npm run api:types
npm run test
npm run build
npm run test:e2e
```

内网发布前额外运行真实 Provider smoke。

MVP 完成条件：

- [ ] 源码无 secret 和生产默认密码。
- [ ] 多个真实用户不能互读私聊或文档。
- [ ] 新 React 五条主链使用真实 API。
- [ ] Embedding/O2/Web/Data/LLM 有 health、timeout、来源和错误状态。
- [ ] Provider 失败不锁 SQLite、不冻结 API。
- [ ] 旧前端只作为临时回滚入口。
- [ ] Pytest、Ruff、React build、核心 Playwright 和 Provider smoke 通过。
- [ ] README/CONTEXT 明确单 Workspace、单实例和延期能力。

## 11. Post-MVP 延期项

以下内容保留在完整产品化路线中，不进入本次 MVP：

- 多 Workspace 和通用 TenantContext。
- 公网部署与完整威胁模型。
- 分布式 Worker lease。
- LearnedSkill executor。
- Delegated answer adoption、贡献结算和 lineage UI。
- ANN/sqlite-vec。
- 完整 Admin CRUD。
- 可编辑 Digital Understanding、Preferences、Impact 和 Project Review。
- 全量 Memory 状态机与历史版本。
- 多实例服务数据库迁移。
