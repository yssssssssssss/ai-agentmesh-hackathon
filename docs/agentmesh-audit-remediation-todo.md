# AgentMesh Audit Remediation Todo

> 来源：`docs/project-audit-report.md`  
> 实施计划：`docs/superpowers/plans/2026-08-13-agentmesh-audit-remediation-implementation-plan.md`  
> 当前 MVP 计划：`docs/superpowers/plans/2026-08-13-agentmesh-internal-pilot-mvp-stabilization-plan.md`  
> 当前 MVP Todo：`docs/agentmesh-internal-pilot-mvp-todo.md`  
> 基线：`bbbc882423eef0451711dbea0d6df9d9907fa2ff`  
> 状态：Post-MVP 路线图，当前不执行。

## 使用规则

- 每个顶层任务必须在独立 worktree/分支完成。
- 开始任务前填写 Owner、Branch 和 Start。
- 完成任务后填写 Commit、Tests 和 Evidence。
- 任务只有在代码、聚焦测试、Ruff 和验收条件全部通过后才能勾选。
- P0 未完成前，不开始向量 ANN 或无关重构。
- React 切换前，旧 `app.html` 保持可回滚。
- 不得提交 secret、`.env`、SQLite、`node_modules` 或 `dist`。

状态约定：

```text
[ ] pending
[~] in progress
[x] done
[!] blocked
[-] dropped with written reason
```

## Current Baseline

- [x] 审计报告完成：`docs/project-audit-report.md`
- [x] Backend pytest：373 passed，6 warnings
- [x] React build：PASS，1617 modules transformed
- [!] Ruff：23 errors
- [!] CI：不存在
- [!] Frontend tests：不存在
- [!] React production cutover：未完成
- [!] Tracked Embedding key：待立即轮换和删除

---

## Phase A: Stop-Ship Security

### T1 Remove Embedded Secrets and Make Embedding Opt-In

- [ ] Owner / Branch / Start 已填写
- [ ] 外部轮换或吊销当前 Embedding key
- [ ] 删除源码默认 key
- [ ] Embedding 默认关闭
- [ ] Enabled 但缺 URL/key 时 fail closed
- [ ] FTS-only 模式不发网络请求
- [ ] 增加 `tests/test_embedding_config.py`
- [ ] 更新 `.env.example` 和 README
- [ ] `test_embedding_config.py`、`test_vector_search.py` 通过
- [ ] Ruff 通过
- [ ] Commit 已记录

Dependencies: none  
Acceptance: 仓库扫描无 key；默认启动不访问 embedding provider。

### T2 Gate Demo Seeds and Default Credentials

- [ ] Demo seed 改为显式 opt-in
- [ ] Import app 不再写数据库
- [ ] Production 不创建 `usr_admin` 默认 credential
- [ ] Tests 显式启用 demo seed
- [ ] 增加 `tests/test_seed_security.py`
- [ ] README 区分 demo/production bootstrap
- [ ] Auth/permissions/OAuth 回归通过
- [ ] Ruff 通过
- [ ] Commit 已记录

Dependencies: none  
Acceptance: 空生产数据库启动后不存在公开固定管理员密码。

### T3 Introduce Request-Scoped AccessContext

- [ ] 新增 `agentmesh/access.py`
- [ ] 定义 `AccessContext(user, workspace, project, capabilities)`
- [ ] Store 增加 owner/project/member 查询
- [ ] Bootstrap 使用用户真实 workspace/default project
- [ ] 普通用户不能枚举无关 workspace/project/users
- [ ] 移除业务路径 seed tenant 依赖
- [ ] 增加第二 Workspace/Project 合同测试
- [ ] Team/project isolation 回归通过
- [ ] Ruff 通过
- [ ] Commit 已记录

Dependencies: T2  
Acceptance: 第二租户用户的 chat/document/search/bootstrap 全部落在正确租户。

### T4 Enforce Chat Ownership and Private Search Isolation

- [ ] 读取 history 前验证 thread owner/ACL
- [ ] 已有 thread 不允许其他用户写入
- [ ] 新 thread ID 由服务端生成
- [ ] Store history/append owner-scoped
- [ ] PRIVATE search 强制 thread owner
- [ ] Search tenant/project 参数经过 AccessContext 校验
- [ ] 增加跨用户 IDOR 回归测试
- [ ] Multiturn/search 回归通过
- [ ] Ruff 通过
- [ ] Commit 已记录

Dependencies: T3  
Acceptance: 攻击者无法搜索、读取上下文或写入他人私聊。

### T5 Secure Documents and Upload Budgets

- [ ] Document list/detail/update/import 共用 ACL
- [ ] 默认 owner-only，项目共享显式授权
- [ ] 未授权详情返回 404
- [ ] 上传改为流式限额
- [ ] 代理/ASGI 请求体上限明确
- [ ] ZIP entry/展开大小/压缩比限制
- [ ] PDF 页数、图片像素和 OCR 预算
- [ ] 增加 document authorization 测试
- [ ] 增加 upload/zip-bomb 限额测试
- [ ] PDF/documents 回归通过
- [ ] Ruff 通过
- [ ] Commit 已记录

Dependencies: T3  
Acceptance: 其他用户无法读取文档正文；恶意压缩文件在解析前被拒绝。

### T6 Implement a Governed Memory State Machine

- [ ] 新增 `memory_governance.py`
- [ ] Create 固定为 proposed/candidate
- [ ] Direct TEAM_ACCEPTED create 被拒绝
- [ ] 定义合法 from-to transition
- [ ] 检查 owner/tenant/project/team/capability
- [ ] status/scope invariant 明确
- [ ] List/detail 返回 allowed actions
- [ ] 每次 transition 写审计
- [ ] 增加 `tests/test_memory_governance.py`
- [ ] Permissions/share 回归通过
- [ ] Ruff 通过
- [ ] Commit 已记录

Dependencies: T3  
Acceptance: 普通用户不能晋升、降级、隐藏或废弃他人的共享记忆。

### T7 Authorize Blackboard Commands and Queue Review

- [ ] 新增统一 Blackboard action policy
- [ ] lock/unlock/handoff/read/reply 校验 visibility
- [ ] unlock 校验 lock owner/capability
- [ ] lock 使用原子 compare-and-set
- [ ] Create DTO 不接受 actor/status/reviewer 字段
- [ ] review/drain 要求治理 capability
- [ ] server 派生 actor/task/tenant
- [ ] 增加 `tests/test_blackboard_authorization.py`
- [ ] Chat/blackboard 回归通过
- [ ] Ruff 通过
- [ ] Commit 已记录

Dependencies: T3  
Acceptance: 普通用户不能冒充 Agent、抢任务、释放他人锁或绕过审批。

### T8 Fix OAuth, Market, and Connector Boundaries

- [ ] Disabled OAuth 用户保持 disabled
- [ ] IdP profile 不能直接设置本地 admin role
- [ ] Market board/status 敏感数据要求认证
- [ ] Market 按组织/workspace 过滤
- [ ] Anonymous health 与 board 分离
- [ ] Connector 映射 ToolDefinition/capability
- [ ] 校验 AgentToolGrant 和数据域
- [ ] Result scope 由授权决定
- [ ] 增加 OAuth/market/datasource 授权测试
- [ ] Ruff 通过
- [ ] Commit 已记录

Dependencies: T3  
Acceptance: 普通登录用户不能借服务端凭据访问未授权外部数据。

---

## Phase B: Availability and Data Consistency

### T9 Move Embedding Outside SQLite Transactions

- [ ] 新增 `vector_index.py`
- [ ] 网络/CPU 不在 SQLite 写事务内执行
- [ ] 定义 missing/pending/ready/stale/failed
- [ ] 更新正文后旧 vector 不参与排名
- [ ] 实现 batch 或有界并发
- [ ] 实现快速失败和熔断
- [ ] Health 暴露状态但不泄露 key
- [ ] 增加 concurrency/stale-vector 测试
- [ ] Vector/search 回归通过
- [ ] Ruff 通过
- [ ] Commit 已记录

Dependencies: T1  
Acceptance: embedding 阻塞时普通数据库写仍可完成；失败不会留下可用的旧向量。

### T10 Make Document Ingestion Recoverable

- [ ] 新增 import manifest/version
- [ ] 记录 expected/completed chunks
- [ ] Chunk ID 确定性且版本化
- [ ] 部分失败可 resume
- [ ] Update document 使旧 chunks/vector stale
- [ ] `already_imported` 只接受完整当前版本
- [ ] Job unexpected exception 进入 failed
- [ ] 增加 failure-injection/retry 测试
- [ ] Documents/cold-start 回归通过
- [ ] Ruff 通过
- [ ] Commit 已记录

Dependencies: T5, T9  
Acceptance: 任意 chunk 失败后重试可补齐，不重复已成功 chunk。

### T11 Isolate and Lease Background Workers

- [ ] 同步 DB/HTTP/LLM step 移出事件循环
- [ ] 使用有界线程池或独立 worker
- [ ] 增加 singleton lease/leader
- [ ] 多 Uvicorn 进程不重复执行
- [ ] Persist worker run state
- [ ] Manual drain 使用同一 service/authorization
- [ ] 增加 start/stop/cancel/recovery 测试
- [ ] 增加 lease expiry/competition 测试
- [ ] Worker 回归通过
- [ ] Ruff 通过
- [ ] Commit 已记录

Dependencies: T7, T9, T10  
Acceptance: Worker 执行不冻结 API event loop，且每个任务只有一个实例执行。

### T12 Batch Search Hydration and Version Indexes

- [ ] Search 候选按 collection 批量取 payload
- [ ] 保持 RRF 顺序
- [ ] `_ensure_schema` 移出连接热路径
- [ ] 增加 query-count 测试
- [ ] 增加 index key-set integrity 测试
- [ ] FTS/vector schema version 明确
- [ ] Full rebuild 变为显式维护操作
- [ ] Search/Vector 回归通过
- [ ] Ruff 通过
- [ ] Commit 已记录

Dependencies: T3, T9  
Acceptance: 200 候选使用有界查询数；等量但错位的索引能被检测和修复。

---

## Phase C: React Complete Replacement

### T13 Add Typed API, Query, and Auth Foundation

- [ ] 增加 TanStack Query
- [ ] 增加 OpenAPI TypeScript 生成
- [ ] 增加统一 `ApiError`/`apiRequest`
- [ ] Cookie session AuthProvider
- [ ] 401 清 auth/cache
- [ ] 403 保持 signed-in
- [ ] Query key 包含 user/workspace/project
- [ ] 增加 Vitest/Playwright
- [ ] Auth E2E 通过
- [ ] Build 通过
- [ ] Commit 已记录

Dependencies: T3, T4, T8  
Acceptance: React 不再假装已登录，刷新/退出/过期行为与服务端一致。

### T14 Serve the React Shell with Legacy Rollback

- [ ] FastAPI 挂载 React assets
- [ ] 显式 SPA product routes
- [ ] 未知 API 保持 JSON 404
- [ ] 旧 UI 临时迁到 `/legacy/app.html`
- [ ] Mobile/Desktop shell 可用
- [ ] Drawer/Modal/Tabs 可访问性通过
- [ ] 390/768/1512 无横向溢出
- [ ] Route/shell 测试通过
- [ ] Commit 已记录

Dependencies: T13  
Acceptance: React 深链和刷新可用，API 不被 SPA fallback 吞掉。

### T15 Connect Workspace

- [ ] Threads list/detail/create
- [ ] Real chat message mutation
- [ ] Explicit Skill list/trace
- [ ] Document upload/job status
- [ ] Search and sources
- [ ] Resource-driven detail panel
- [ ] Error keeps retryable draft
- [ ] Refresh persistence verified
- [ ] Workspace E2E 通过
- [ ] Backend chat/doc/search tests 通过
- [ ] Commit 已记录

Dependencies: T13, T14, T4, T5  
Acceptance: 无 timer 假成功，所有消息/资源刷新后仍存在。

### T16 Connect Knowledge and Governance

- [ ] Inbox list/actions
- [ ] Brief confirm idempotent
- [ ] Self-only 不进入 shared
- [ ] Snooze/resolve/restore
- [ ] Injection review
- [ ] Team candidate acceptance
- [ ] Document edit
- [ ] Memory allowed actions
- [ ] Knowledge E2E 通过
- [ ] Backend governance tests 通过
- [ ] Commit 已记录

Dependencies: T13, T14, T6, T10  
Acceptance: 所有治理状态来自服务端，没有本地业务 state machine。

### T17 Connect Collaboration, Blackboard, and Market

- [ ] Task cards/detail
- [ ] Lock/unlock
- [ ] Reply/handoff/read
- [ ] Dispatch/memory candidate
- [ ] Market status/board/participation
- [ ] Server allowed actions 驱动 UI
- [ ] Polling 仅页面可见时运行
- [ ] Mutation cache invalidation
- [ ] Collaboration E2E 通过
- [ ] Backend authorization tests 通过
- [ ] Commit 已记录

Dependencies: T13, T14, T7, T8  
Acceptance: 刷新后协作状态一致，不允许的动作不显示且直调 API 被拒绝。

### T18 Connect Digital Self, Insights, Settings, and Admin

- [ ] Digital profile/runtime/metrics
- [ ] Understanding edit collects real content
- [ ] Insights period uses server filters
- [ ] Project review/candidate uses stable IDs
- [ ] Settings preferences persist
- [ ] Admin routes capability-specific
- [ ] Users/teams/workspaces/projects
- [ ] Agents/models/tools/schedules
- [ ] Policies/O2/health/audit
- [ ] Role/browser tests 通过
- [ ] Commit 已记录

Dependencies: T13, T14, T3, T8, T22 where applicable  
Acceptance: 所有按钮有真实 handler，普通用户/Team Lead/Admin 看到正确入口。

### T19 Cut Over and Remove Production Mock State

- [ ] 完整旧 UI parity 矩阵通过
- [ ] React `/` 和深链生产可用
- [ ] `mockData.ts` 删除
- [ ] `DemoContext.tsx` 删除
- [ ] Handler-less components 删除
- [ ] 旧 UI rollback 周期完成
- [ ] `app.html` 删除或明确归档
- [ ] 全量 Playwright 通过
- [ ] Pytest/Ruff/build 通过
- [ ] Commit 已记录

Dependencies: T15-T18  
Acceptance: 生产只剩 React，所有业务数据来自 FastAPI/SQLite。

---

## Phase D: Product Capability Closure

### T20 Make Citations Structured and Retrieval Tiers Real

- [ ] `SynthesisResult.cited_source_ids`
- [ ] Stable citation tokens
- [ ] Invalid token fail closed
- [ ] Metrics consume canonical IDs
- [ ] 不使用 title/summary 模糊匹配
- [ ] Tier 使用真实 MemoryLayer + Scope
- [ ] Query embedding/request cache
- [ ] Citation/tier tests 通过
- [ ] Commit 已记录

Dependencies: T9, T12  
Acceptance: citation rate 由真实 source ID 计算，层级检索与注释一致。

### T21 Define and Execute LearnedSkill Safely

- [ ] 定义 SkillMatch
- [ ] 定义 allowlisted WorkflowPlan
- [ ] Static `$` Skill 优先级明确
- [ ] ACTIVE/scope/version 校验
- [ ] Unknown action fail closed
- [ ] 审计 match score/version/fallback
- [ ] Deprecate 后立即停止匹配
- [ ] Runtime/Extraction tests 通过
- [ ] Commit 已记录

Dependencies: T3, T13, T20  
Acceptance: LearnedSkill 激活后可安全触发真实工作流，不执行任意文本或工具。

### T22 Persist Delegated Answers, Adoption, and Lineage

- [ ] Persist DelegatedAnswerRecord
- [ ] Consent/request/decision/answer API
- [ ] High-sensitivity confirmation
- [ ] Answer-only response
- [ ] Idempotent adoption
- [ ] One shadow point and one lineage edge
- [ ] Lineage query API
- [ ] No raw target memory body leakage
- [ ] Collaboration API/E2E tests 通过
- [ ] Commit 已记录

Dependencies: T3, T6, T7, T13  
Acceptance: delegated collaboration 从请求到采纳完整可达并幂等。

---

## Phase E: Engineering and Release

### T23 Fix Repository Hygiene, Dependencies, and Reality Docs

- [x] `.gitignore` 增加 node_modules/dist/.vite/tsbuildinfo
- [x] 不破坏用户未跟踪文件
- [x] PyMuPDF 依赖/README 一致
- [x] React 版本与栈文档正确
- [x] FastAPI serving 状态正确
- [ ] Worker/Embedding 默认值正确
- [ ] CONTEXT capability 状态正确
- [ ] ADR 与 vector 实现一致
- [x] Clean install PDF smoke 通过
- [x] Commit 已记录

Dependencies: T1, T19, T20-T22  
Acceptance: 干净 clone 按 README 可安装、运行和验证，文档无过时事实。

### T24 Add CI, Coverage, Frontend Tests, and Clean Ruff

- [x] 23 个 Ruff 问题全部关闭
- [x] Backend clean-install job
- [x] Ruff job
- [ ] Pytest + coverage job
- [x] Frontend types/test/build job
- [x] Playwright job
- [x] Secret scan
- [ ] Dependency audit
- [x] Security denial paths coverage
- [x] Worker/concurrency tests 纳入 CI
- [x] Commit 已记录

Dependencies: T1-T23  
Acceptance: PR 无法在任一必需门禁失败时合并。

### T25 Benchmark Retrieval and Run Final Release Gate

- [ ] 1k lexical/vector/hybrid benchmark
- [ ] 5k lexical/vector/hybrid benchmark
- [ ] p50/p95/memory/citation 指标
- [ ] Tenant filtering cost
- [ ] 根据 ADR 证据决定 KNN/ANN
- [ ] 全量 pytest 通过
- [ ] Ruff 通过
- [ ] React types/test/build/E2E 通过
- [ ] Production-like restart/persistence smoke
- [ ] 每个角色主链验证
- [ ] 无默认 admin/secret
- [ ] Audit/README/CONTEXT 更新
- [ ] Final commit/release evidence 记录

Dependencies: T1-T24  
Acceptance: 所有 Program Completion Criteria 有命令输出和可追溯证据。

---

## Final Program Gate

- [ ] No tracked secrets or default production credentials
- [ ] Owner/tenant/project/capability enforced on every object operation
- [ ] PRIVATE data cannot cross users
- [ ] Memory and Blackboard transitions governed and audited
- [ ] Embedding/document processing do not block write transactions/event loop
- [ ] Document ingestion resumable and versioned
- [ ] React is the only production frontend
- [ ] No local business mock state
- [ ] LearnedSkill and delegated adoption reachable or removed from claims
- [ ] Backend/Frontend/E2E/Coverage/Secret scan pass in CI
- [ ] README/CONTEXT/ADR match code reality

## Execution Ledger

| Task | Owner | Branch | Status | Commit | Tests/Evidence |
| --- | --- | --- | --- | --- | --- |
| T1 |  |  | pending |  |  |
| T2 |  |  | pending |  |  |
| T3 |  |  | pending |  |  |
| T4 |  |  | pending |  |  |
| T5 |  |  | pending |  |  |
| T6 |  |  | pending |  |  |
| T7 |  |  | pending |  |  |
| T8 |  |  | pending |  |  |
| T9 |  |  | pending |  |  |
| T10 |  |  | pending |  |  |
| T11 |  |  | pending |  |  |
| T12 |  |  | pending |  |  |
| T13 |  |  | pending |  |  |
| T14 |  |  | pending |  |  |
| T15 |  |  | pending |  |  |
| T16 |  |  | pending |  |  |
| T17 |  |  | pending |  |  |
| T18 |  |  | pending |  |  |
| T19 |  |  | pending |  |  |
| T20 |  |  | pending |  |  |
| T21 |  |  | pending |  |  |
| T22 |  |  | pending |  |  |
| T23 |  |  | pending |  |  |
| T24 |  |  | pending |  |  |
| T25 |  |  | pending |  |  |
