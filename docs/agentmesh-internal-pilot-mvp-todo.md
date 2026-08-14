# AgentMesh Internal Pilot MVP Stabilization Todo

> 设计规格：`docs/superpowers/specs/2026-08-13-agentmesh-internal-pilot-mvp-stabilization-design.md`  
> 实施计划：`docs/superpowers/plans/2026-08-13-agentmesh-internal-pilot-mvp-stabilization-plan.md`  
> 完整 Post-MVP 路线：`docs/superpowers/plans/2026-08-13-agentmesh-audit-remediation-implementation-plan.md`  
> 状态：Active MVP Plan

## MVP 约束

- 企业内网、小范围真实用户。
- 单 Workspace、单默认 Project、单 FastAPI 实例。
- 新 React 为默认入口。
- Embedding、O2 Research、Web Research、Data API、LLM 都要真实 smoke。
- CI 使用 mock Provider。
- 多 Workspace、ANN、LearnedSkill executor、delegated adoption 和完整 Admin 延期。

## 当前基线

- [x] 审计报告完成
- [x] MVP 规格批准
- [x] Backend pytest：373 passed
- [x] React build：PASS
- [!] Ruff：23 errors
- [!] React：仍为 mock，未进入生产
- [!] Tracked Embedding key：待轮换
- [!] CI：不存在

## Wave Execution Rules

- [ ] 每个 Wave 开始前冻结跨任务接口和允许修改文件。
- [ ] Worker 只实现代码和测试，不运行 pytest、Ruff、Build 或 Playwright。
- [ ] Worker 不生成 SDD 报告，不启动 Reviewer，不提交代码。
- [ ] 主协调者在 Wave 合并后统一运行验证。
- [ ] 每个正式 Gate 只进行一次 findings-first 审查。
- [ ] Gate 确认的问题修复后，只重跑受影响门禁和规定全量门禁。
- [ ] OpenAPI 类型只在 M6、R2 和 Final Gate 生成。
- [ ] 真实 Provider smoke 只在 Final Gate 运行一次。

## Wave Status

| Wave | Tasks | Status | Gate |
| --- | --- | --- | --- |
| Wave 1 | M1 + M2 + M3 | pending | R1 Security Boundary |
| Wave 2 | M4 | pending | 与 Wave 3 合并审查 |
| Wave 3 | M5 + M6 | pending | R2 Availability + React Foundation |
| Wave 4 | M7 + M8 + M9 | pending | R3 Browser Main Flows |
| Wave 5 | M10 | pending | Final Gate 前置 |
| Wave 6 | M11 | pending | Final Release Gate |

---


## M1 Secure Configuration and Explicit Demo Mode

- [ ] Owner/Branch/Start 填写
- [ ] 轮换/吊销当前 Embedding key
- [ ] 源码删除默认 key
- [ ] Embedding 默认关闭
- [ ] Enabled 缺 URL/key 时 fail closed
- [ ] Seed 从 import 移到 lifespan
- [ ] Demo 账号仅 `AGENTMESH_DEMO_MODE=1` 创建
- [ ] Production 不生成固定管理员 credential
- [ ] `.env.example` 和 README 更新
- [ ] `tests/test_mvp_safe_config.py` 通过
- [ ] Ruff 通过
- [ ] Commit/Evidence 记录

Dependencies: none  
Done when: 默认启动不访问 Embedding，不生成公开管理员密码。

## M2 Enforce Cross-User Privacy

- [ ] Chat history 读取前校验 owner
- [ ] 其他用户不能向 thread 写消息
- [ ] New thread ID 服务端生成
- [ ] PRIVATE chat search owner-only
- [ ] Document list owner/admin 过滤
- [ ] Document detail 未授权返回 404
- [ ] Update/import 复用同一 Document ACL
- [ ] 无关 project 参数被拒绝
- [ ] `tests/test_mvp_user_isolation.py` 通过
- [ ] Multiturn/Documents/Search 回归通过
- [ ] Ruff 通过
- [ ] Commit/Evidence 记录

Dependencies: none  
Done when: 两个真实用户不能互读或互写私聊和文档。

## M3 Add Minimum Governance Guards

- [ ] Memory create 不能直接 TEAM_ACCEPTED
- [ ] MVP 只开放 proposed/candidate -> accepted
- [ ] 普通用户不能降级/隐藏共享 Memory
- [ ] Blackboard mutation 校验 visibility/action
- [ ] Unlock 校验 lock owner
- [ ] Actor/status 服务端派生
- [ ] Review/drain 管理员或治理 capability
- [ ] Market board 要求认证
- [ ] OAuth disabled 用户保持 disabled
- [ ] Profile role 不能直接提升 admin
- [ ] `tests/test_mvp_governance.py` 通过
- [ ] Ruff 通过
- [ ] Commit/Evidence 记录

Dependencies: none  
Done when: 普通用户不能绕过最小 Memory/Blackboard/OAuth/Market 治理边界。

## Review Gate R1: Security Boundary

- [ ] M1、M2、M3 Worker 改动全部返回
- [ ] 跨任务配置、认证和权限接口已对齐
- [ ] 聚焦安全测试通过
- [ ] 完整 Backend pytest 通过
- [ ] Wave 改动 Ruff 通过
- [ ] Security Reviewer 完成一次正式审查
- [ ] 无未处理 Critical/High finding
- [ ] 确认问题修复并重新验证
- [ ] 主协调者提交 Wave 1

Commands:

```bash
AGENTMESH_EMBEDDING_ENABLED=false .venv/bin/python -m pytest \
  tests/test_mvp_safe_config.py \
  tests/test_mvp_user_isolation.py \
  tests/test_mvp_governance.py \
  tests/test_permissions.py \
  tests/test_oauth.py -v
AGENTMESH_EMBEDDING_ENABLED=false .venv/bin/python -m pytest -q
.venv/bin/ruff check agentmesh tests/test_mvp_safe_config.py tests/test_mvp_user_isolation.py tests/test_mvp_governance.py
```

---


## M4 Make All Real Providers Configurable and Observable

- [ ] 统一 `ProviderStatus`
- [ ] Embedding health/config/mode/error
- [ ] O2 Research health/config/mode/error
- [ ] Web Research health/config/mode/error
- [ ] Data API health/config/mode/error
- [ ] LLM health/config/mode/error
- [ ] Source 记录 requested/actual provider
- [ ] Source 记录 fallback reason/latency
- [ ] Status/error 不泄露 secret
- [ ] Data Provider 检查 Agent grant
- [ ] 增加 `scripts/provider_smoke.py`
- [ ] Provider contract tests 通过
- [ ] Commit/Evidence 记录

Dependencies: M1, M3  
Done when: 五类真实 Provider 可诊断、可区分 real/fallback，并有独立 smoke。

## M5 Decouple Embedding and Stabilize Document Jobs

- [ ] Embedding 网络调用移出 SQLite 写事务
- [ ] Embedding/解析移出 API event loop
- [ ] Vector 状态 pending/ready/stale/failed
- [ ] 更新正文后旧 vector 不参与排名
- [ ] Document job queued/running/completed/failed
- [ ] Unexpected exception 进入 failed
- [ ] Document version/expected chunks 记录
- [ ] Partial import 可 retry
- [ ] Chunk 不重复
- [ ] Blocked provider 不阻塞普通 SQLite 写
- [ ] Ingestion/concurrency tests 通过
- [ ] Commit/Evidence 记录

Dependencies: M1, M4  
Done when: Provider 卡住或失败不会锁 SQLite、冻结 API 或留下不可恢复 job。

## M6 Add React Auth, API, Query, and Shell

- [ ] TanStack Query
- [ ] OpenAPI TypeScript
- [ ] `ApiError`/`apiRequest`
- [ ] Cookie session AuthProvider
- [ ] 401 清 auth/cache
- [ ] 403 保持 signed-in
- [ ] Login/reload/logout
- [ ] FastAPI 挂 React assets
- [ ] Product SPA routes
- [ ] Unknown API JSON 404
- [ ] `/legacy/app.html` 回滚入口
- [ ] 390/768/1512 shell 测试
- [ ] Auth/Shell E2E 通过
- [ ] Commit/Evidence 记录

Dependencies: M1-M3  
Done when: React 可真实登录并通过 FastAPI 同源访问，旧 UI 仍可回滚。

## Review Gate R2: Availability and React Foundation

- [ ] M4、M5、M6 Worker 改动全部返回
- [ ] Provider、Vector、Ingestion、Auth 接口已对齐
- [ ] Provider/ingestion/concurrency 聚焦测试通过
- [ ] React API types 生成成功
- [ ] React unit tests/build 通过
- [ ] Auth/Shell Playwright 通过
- [ ] Reviewer 完成一次正式审查
- [ ] 无未处理 Critical/High finding
- [ ] 确认问题修复并重新验证
- [ ] 主协调者提交 Wave 2/3

Commands:

```bash
AGENTMESH_EMBEDDING_ENABLED=false .venv/bin/python -m pytest \
  tests/test_mvp_provider_contracts.py \
  tests/test_mvp_ingestion_stability.py \
  tests/test_mvp_sqlite_concurrency.py \
  tests/test_health.py \
  tests/test_documents.py -v
cd agentmesh-demo
npm run api:types
npm run test
npm run build
npm run test:e2e -- e2e/auth-shell.spec.ts
```

---


## M7 Connect Workspace and Real Provider Traces

- [ ] Threads list/detail/create
- [ ] Natural chat mutation
- [ ] Explicit `$` Skill
- [ ] Pending/failed/retry state
- [ ] Document upload/job status
- [ ] Search
- [ ] Source/detail panel
- [ ] Actual provider/mode/latency/fallback
- [ ] Refresh persistence
- [ ] Provider failure 不显示成功
- [ ] Workspace E2E 通过
- [ ] Backend chat/doc/search/provider tests 通过
- [ ] Commit/Evidence 记录

Dependencies: M2, M4-M6  
Done when: Workspace 没有 timer 假成功，真实 Provider 来源可见并可刷新恢复。

## M8 Connect Knowledge and Collaboration Core

- [ ] Inbox list/counts
- [ ] Brief confirm
- [ ] Snooze/resolve
- [ ] Team Lead accept candidate
- [ ] Prompt injection review
- [ ] Task cards/detail
- [ ] Reply
- [ ] Lock/unlock
- [ ] Handoff
- [ ] Market status/participation
- [ ] Allowed actions 驱动按钮
- [ ] 移除 DemoContext/local Sets
- [ ] 409 刷新 canonical state
- [ ] Governance/Collaboration E2E 通过
- [ ] Commit/Evidence 记录

Dependencies: M3, M6  
Done when: 核心治理和协作刷新后仍一致，所有动作由服务端授权。

## M9 Add Read-Only Digital/Insights and Minimum Admin

- [ ] Digital Self 使用 bootstrap/runtime/activity/memory
- [ ] Insights 使用 task/activity/audit
- [ ] 无后端资源显示空态
- [ ] 隐藏 editable understanding/preferences/review
- [ ] Admin 用户 list/create/disable/reset
- [ ] Agent model/tool 基础配置
- [ ] Provider diagnostics
- [ ] O2 sync
- [ ] Policies/Audit read-only
- [ ] 独立 capability gate
- [ ] 无 handler-less button
- [ ] Role/E2E tests 通过
- [ ] Commit/Evidence 记录

Dependencies: M3, M4, M6  
Done when: 只展示真实数据；未实现能力不伪装成功。

## Review Gate R3: Browser Main Flows

- [ ] M7、M8、M9 Worker 改动全部返回
- [ ] Workspace/Knowledge/Collaboration/Admin contracts 已对齐
- [ ] React unit tests/build 通过
- [ ] 三条核心 Playwright 文件通过
- [ ] 相关 Backend contract tests 通过
- [ ] 页面无 mock、timer success、Toast-only success
- [ ] Reviewer 完成一次正式审查
- [ ] 无未处理 Critical/High finding
- [ ] 确认问题修复并重新验证
- [ ] 主协调者提交 Wave 4

Commands:

```bash
cd agentmesh-demo
npm run test
npm run build
npm run test:e2e -- \
  e2e/workspace-mvp.spec.ts \
  e2e/governance-collaboration-mvp.spec.ts \
  e2e/read-model-admin-mvp.spec.ts
cd ..
AGENTMESH_EMBEDDING_ENABLED=false .venv/bin/python -m pytest \
  tests/test_multiturn.py \
  tests/test_documents.py \
  tests/test_search_fts.py \
  tests/test_permissions.py \
  tests/test_health.py -v
```

---


## M10 Cut Over React and Remove Production Mock State

- [ ] MVP parity E2E
- [ ] `/` 切到 React
- [ ] Deep-link refresh 可用
- [ ] `mockData.ts` 删除
- [ ] `DemoContext.tsx` 删除
- [ ] Timer business success 删除
- [ ] Toast-only success 删除
- [ ] Handler-less controls 删除
- [ ] `/legacy/app.html` 保留一个周期
- [ ] Unknown API 保持 JSON 404
- [ ] Pytest/Ruff/React tests/build/E2E 通过
- [ ] Commit/Evidence 记录

Dependencies: M6-M9  
Done when: React 是默认 UI，生产代码没有本地业务 mock。

## M11 Add Minimum CI and Run MVP Release Gate

- [ ] `.gitignore` 覆盖 node_modules/dist/.vite/tsbuildinfo/Playwright
- [ ] PyMuPDF 依赖和 README 一致
- [ ] 23 个 Ruff 问题关闭
- [ ] Backend clean install job
- [ ] Secret scan
- [ ] Ruff job
- [ ] Pytest job
- [ ] Frontend types/test/build job
- [ ] Core Playwright job
- [ ] Embedding real smoke 通过
- [ ] O2 real smoke 通过
- [ ] Web Research real smoke 通过
- [ ] Data API real smoke 通过
- [ ] LLM real smoke 通过
- [ ] User/Team Lead/Admin production-like smoke
- [ ] Restart/persistence smoke
- [ ] README/CONTEXT 更新
- [ ] Final commit/evidence 记录

Dependencies: M1-M10  
Done when: CI 全绿，五类真实 Provider smoke 全绿，文档明确单 Workspace/单实例限制。

---

## Final Release Gate

```bash
AGENTMESH_EMBEDDING_ENABLED=false .venv/bin/python -m pytest
.venv/bin/ruff check .
cd agentmesh-demo
npm run api:types
npm run test
npm run build
npm run test:e2e
cd ..
.venv/bin/python scripts/provider_smoke.py --embedding --o2 --web --data --llm
```

- [ ] 无 tracked secret/default production password
- [ ] Cross-user chat/document isolation
- [ ] React 五条 MVP 主链真实 API
- [ ] 五类 Provider 可观测且真实 smoke 通过
- [ ] Provider failure 不锁 DB/阻塞 API
- [ ] Memory/Blackboard MVP actions 已授权
- [ ] CI 全绿
- [ ] 单 Workspace/单实例/Post-MVP 限制写入文档

## Execution Ledger

| Task | Owner | Branch | Status | Commit | Tests/Evidence |
| --- | --- | --- | --- | --- | --- |
| M1 |  |  | pending |  |  |
| M2 |  |  | pending |  |  |
| M3 |  |  | pending |  |  |
| M4 |  |  | pending |  |  |
| M5 |  |  | pending |  |  |
| M6 |  |  | pending |  |  |
| M7 |  |  | pending |  |  |
| M8 |  |  | pending |  |  |
| M9 |  |  | pending |  |  |
| M10 |  |  | pending |  |  |
| M11 |  |  | pending |  |  |

## Review and Release Ledger

| Gate | Scope | Reviewer | Status | Evidence |
| --- | --- | --- | --- | --- |
| R1 | M1-M3 Security Boundary |  | pending |  |
| R2 | M4-M6 Availability + React Foundation |  | pending |  |
| R3 | M7-M9 Browser Main Flows |  | pending |  |
| Final | M10-M11 Release |  | pending |  |
