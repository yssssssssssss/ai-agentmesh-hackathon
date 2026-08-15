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
- 多 Workspace、ANN、LearnedSkill executor、delegated adoption 的公共 UI/API 和完整 Admin 延期。

## 执行前基线

以下为计划启动时快照，不代表合并后的现状；完成状态见下方 Wave Status、Execution Ledger 和 Review and Release Ledger。

- [x] 审计报告完成
- [x] MVP 规格批准
- [x] Backend pytest：373 passed
- [x] React build：PASS
- [!] Ruff：23 errors
- [!] React：仍为 mock，未进入生产
- [!] Tracked Embedding key：待轮换
- [!] CI：不存在

## Wave Execution Rules（流程规则，非完成状态）

- 每个 Wave 开始前冻结跨任务接口和允许修改文件。
- Worker 只实现代码和测试，不运行 pytest、Ruff、Build 或 Playwright。
- Worker 不生成 SDD 报告，不启动 Reviewer，不提交代码。
- 主协调者在 Wave 合并后统一运行验证。
- 每个正式 Gate 只进行一次 findings-first 审查。
- Gate 确认的问题修复后，只重跑受影响门禁和规定全量门禁。
- OpenAPI 类型只在 M6、R2 和 Final Gate 生成。
- 真实 Provider smoke 只在 Final Gate 运行一次。

## Wave Status

| Wave | Tasks | Status | Gate |
| --- | --- | --- | --- |
| Wave 1 | M1 + M2 + M3 | approved_external_rotation_pending | R1 Security Boundary |
| Wave 2 | M4 | approved | R2 Availability + React Foundation |
| Wave 3 | M5 + M6 | approved | R2 Availability + React Foundation |
| Wave 4 | M7 + M8 + M9 | approved | R3 Browser Main Flows |
| Wave 5 | M10 | done | Final Gate 前置 |
| Wave 6 | M11 | code_complete_external_gates_pending | Final Release Gate |

---


## M1 Secure Configuration and Explicit Demo Mode

- [x] Owner/Branch/Start 填写
- [ ] 轮换/吊销当前 Embedding key
- [x] 源码删除默认 key
- [x] Embedding 默认关闭
- [x] Enabled 缺 URL/key 时 fail closed
- [x] Seed 从 import 移到 lifespan
- [x] Demo 账号仅 `AGENTMESH_DEMO_MODE=1` 创建
- [x] Production 不生成固定管理员 credential
- [x] `.env.example` 和 README 更新
- [x] `tests/test_mvp_safe_config.py` 通过
- [x] Ruff 通过
- [x] Commit/Evidence 记录

Dependencies: none  
Done when: 默认启动不访问 Embedding，不生成公开管理员密码。

## M2 Enforce Cross-User Privacy

- [x] Chat history 读取前校验 owner
- [x] 其他用户不能向 thread 写消息
- [x] New thread ID 服务端生成
- [x] PRIVATE chat search owner-only
- [x] Document list owner/admin 过滤
- [x] Document detail 未授权返回 404
- [x] Update/import 复用同一 Document ACL
- [x] 无关 project 参数被拒绝
- [x] `tests/test_mvp_user_isolation.py` 通过
- [x] Multiturn/Documents/Search 回归通过
- [x] Ruff 通过
- [x] Commit/Evidence 记录

Dependencies: none  
Done when: 两个真实用户不能互读或互写私聊和文档。

## M3 Add Minimum Governance Guards

- [x] Memory create 不能直接 TEAM_ACCEPTED
- [x] MVP 只开放 proposed/candidate -> accepted
- [x] 普通用户不能降级/隐藏共享 Memory
- [x] Blackboard mutation 校验 visibility/action
- [x] Unlock 校验 lock owner
- [x] Actor/status 服务端派生
- [x] Review/drain 管理员或治理 capability
- [x] Market board 要求认证
- [x] OAuth disabled 用户保持 disabled
- [x] Profile role 不能直接提升 admin
- [x] `tests/test_mvp_governance.py` 通过
- [x] Ruff 通过
- [x] Commit/Evidence 记录

Dependencies: none  
Done when: 普通用户不能绕过最小 Memory/Blackboard/OAuth/Market 治理边界。

## Review Gate R1: Security Boundary

- [x] M1、M2、M3 Worker 改动全部返回
- [x] 跨任务配置、认证和权限接口已对齐
- [x] 聚焦安全测试通过
- [x] 完整 Backend pytest 通过
- [x] Wave 改动 Ruff 通过
- [x] Security Reviewer 完成一次正式审查
- [x] 无未处理 Critical/High finding
- [x] 确认问题修复并重新验证
- [x] 主协调者提交 Wave 1

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

- [x] 统一 `ProviderStatus`
- [x] Embedding health/config/mode/error
- [x] O2 Research health/config/mode/error
- [x] Web Research health/config/mode/error
- [x] Data API health/config/mode/error
- [x] LLM health/config/mode/error
- [x] Source 记录 requested/actual provider
- [x] Source 记录 fallback reason/latency
- [x] Status/error 不泄露 secret
- [x] Data Provider 检查 Agent grant
- [x] 增加 `scripts/provider_smoke.py`
- [x] Provider contract tests 通过
- [x] Commit/Evidence 记录

Dependencies: M1, M3  
Done when: 五类真实 Provider 可诊断、可区分 real/fallback，并有独立 smoke。

## M5 Decouple Embedding and Stabilize Document Jobs

- [x] Embedding 网络调用移出 SQLite 写事务
- [x] Embedding/解析移出 API event loop
- [x] Vector 状态 pending/ready/stale/failed
- [x] 更新正文后旧 vector 不参与排名
- [x] Document job queued/running/completed/failed
- [x] Unexpected exception 进入 failed
- [x] Document version/expected chunks 记录
- [x] Partial import 可 retry
- [x] Chunk 不重复
- [x] Blocked provider 不阻塞普通 SQLite 写
- [x] Ingestion/concurrency tests 通过
- [x] Commit/Evidence 记录

Dependencies: M1, M4  
Done when: Provider 卡住或失败不会锁 SQLite、冻结 API 或留下不可恢复 job。

## M6 Add React Auth, API, Query, and Shell

- [x] TanStack Query
- [x] OpenAPI TypeScript
- [x] `ApiError`/`apiRequest`
- [x] Cookie session AuthProvider
- [x] 401 清 auth/cache
- [x] 403 保持 signed-in
- [x] Login/reload/logout
- [x] FastAPI 挂 React assets
- [x] Product SPA routes
- [x] Unknown API JSON 404
- [x] `/legacy/app.html`、`/app.html` 回滚入口
- [x] 390/768/1512 shell 测试
- [x] Auth/Shell E2E 通过
- [x] Commit/Evidence 记录

Dependencies: M1-M3  
Done when: React 可真实登录并通过 FastAPI 同源访问，旧 UI 仍可回滚。

## Review Gate R2: Availability and React Foundation

- [x] M4、M5、M6 Worker 改动全部返回
- [x] Provider、Vector、Ingestion、Auth 接口已对齐
- [x] Provider/ingestion/concurrency 聚焦测试通过
- [x] React API types 生成成功
- [x] React unit tests/build 通过
- [x] Auth/Shell Playwright 通过
- [x] Reviewer 完成一次正式审查
- [x] 无未处理 Critical/High finding
- [x] 确认问题修复并重新验证
- [x] 主协调者提交 Wave 2/3

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

- [x] Threads list/detail/create
- [x] Natural chat mutation
- [x] Explicit `$` Skill
- [x] Pending/failed/retry state
- [x] Document upload/job status
- [x] Search
- [x] Source/detail panel
- [x] Actual provider/mode/latency/fallback
- [x] Refresh persistence
- [x] Provider failure 不显示成功
- [x] Workspace E2E 通过
- [x] Backend chat/doc/search/provider tests 通过
- [x] Commit/Evidence 记录

Dependencies: M2, M4-M6  
Done when: Workspace 没有 timer 假成功，真实 Provider 来源可见并可刷新恢复。

## M8 Connect Knowledge and Collaboration Core

- [x] Inbox list/counts
- [x] Brief confirm
- [x] Snooze/resolve
- [x] Team Lead accept candidate
- [x] Prompt injection review
- [x] Task cards/detail
- [x] Reply
- [x] Lock/unlock
- [x] Handoff
- [x] Market status/participation
- [x] Allowed actions 驱动按钮
- [x] 移除 DemoContext/local Sets
- [x] 409 刷新 canonical state
- [x] Governance/Collaboration E2E 通过
- [x] Commit/Evidence 记录

Dependencies: M3, M6  
Done when: 核心治理和协作刷新后仍一致，所有动作由服务端授权。

## M9 Add Read-Only Digital/Insights and Minimum Admin

- [x] Digital Self 使用 bootstrap/runtime/activity/memory
- [x] Insights 使用 task/activity/audit
- [x] 无后端资源显示空态
- [x] 隐藏 editable understanding/preferences/review
- [x] Admin 用户 list/create/disable/reset
- [x] Agent model/tool 基础配置
- [x] Provider diagnostics
- [x] O2 sync
- [x] Policies/Audit read-only
- [x] 独立 capability gate
- [x] 无 handler-less button
- [x] Role/E2E tests 通过
- [x] Commit/Evidence 记录

Dependencies: M3, M4, M6  
Done when: 只展示真实数据；未实现能力不伪装成功。

## Review Gate R3: Browser Main Flows

- [x] M7、M8、M9 Worker 改动全部返回
- [x] Workspace/Knowledge/Collaboration/Admin contracts 已对齐
- [x] React unit tests/build 通过
- [x] 四条核心 Playwright 文件通过
- [x] 相关 Backend contract tests 通过
- [x] 页面无 mock、timer success、Toast-only success
- [x] Reviewer 完成一次正式审查
- [x] 无未处理 Critical/High finding
- [x] 确认问题修复并重新验证
- [x] 主协调者提交 Wave 4

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

- [x] MVP parity E2E
- [x] `/` 切到 React
- [x] Deep-link refresh 可用
- [x] `mockData.ts` 删除
- [x] `DemoContext.tsx` 删除
- [x] Timer business success 删除
- [x] Toast-only success 删除
- [x] Handler-less controls 删除
- [x] `/legacy/app.html`、`/app.html` 保留一个周期
- [x] Unknown API 保持 JSON 404
- [x] Pytest/Ruff/React tests/build/E2E 通过
- [x] Commit/Evidence 记录

Dependencies: M6-M9  
Done when: React 是默认 UI，生产代码没有本地业务 mock。

## M11 Add Minimum CI and Run MVP Release Gate

- [x] `.gitignore` 覆盖 node_modules/dist/.vite/tsbuildinfo/Playwright
- [x] PyMuPDF 依赖和 README 一致
- [x] 23 个 Ruff 问题关闭
- [x] Backend clean install job
- [x] Secret scan job
- [x] Ruff job
- [x] Pytest job
- [x] Frontend types/test/build job
- [x] Core Playwright job
- [x] Embedding real smoke 通过
- [x] O2 real smoke 通过
- [x] Web Research real smoke 通过
- [ ] Data API real smoke 通过
- [x] LLM real smoke 通过
- [x] User/Team Lead/Admin production-like smoke
- [x] Restart/persistence smoke
- [x] README/CONTEXT 更新
- [x] Final commit/evidence 记录

Provider update observed 2026-08-14: Embedding, O2 metasearch, Tavily Web Research, `llm:primary`, and `llm:fallback` all reported `configured=true`, `ready=true`, `mode=real`. Tavily application verification returned three HTTPS sources with `actual_provider=tavily`; O2 returned real JD product results and AgentMesh O2 smoke passed. GitHub PR #18 CI passed backend clean install/pytest, frontend types/test/build, Playwright, and secret scan. Data API remains unconfigured, and credentials exposed in chat still require rotation before wider deployment.

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

- [x] 无 tracked secret/default production password
- [x] Cross-user chat/document isolation
- [x] React 五条 MVP 主链真实 API
- [ ] 五类 Provider 可观测且真实 smoke 通过
- [x] Provider failure 不锁 DB/阻塞 API
- [x] Memory/Blackboard MVP actions 已授权
- [x] CI 全绿
- [x] 单 Workspace/单实例/Post-MVP 限制写入文档

## Execution Ledger

| Task | Owner | Branch | Status | Commit | Tests/Evidence |
| --- | --- | --- | --- | --- | --- |
| M1 | M1SafeConfig | feat/internal-pilot-mvp-stabilization | code_complete_external_action_pending | 74841d2 | 425 pytest; Ruff pass; key rotation external |
| M2 | M2UserIsolation | feat/internal-pilot-mvp-stabilization | done | 74841d2 | 425 pytest; Ruff pass; R1 approved |
| M3 | M3Governance | feat/internal-pilot-mvp-stabilization | done | 74841d2 | 425 pytest; Ruff pass; R1 approved |
| M4 | M4ProviderObservability | feat/internal-pilot-mvp-stabilization | done | 1d28865 | Provider contracts; 461 full pytest; R2 approved |
| M5 | M5IngestionStability | feat/internal-pilot-mvp-stabilization | done | 1d28865 | Ingestion/concurrency regressions; 461 full pytest; R2 approved |
| M6 | M6ReactFoundation | feat/internal-pilot-mvp-stabilization | done | 1d28865 | 7 Vitest; build pass; 11 Playwright; R2 approved |
| M7 | M7Workspace + Main | feat/internal-pilot-mvp-stabilization | done | 9231c9a | Idempotent chat receipts; exact async ingestion; Workspace E2E; R3 approved |
| M8 | M8KnowledgeCollaboration + Main | feat/internal-pilot-mvp-stabilization | done | 9231c9a | Atomic Brief governance; handoff control; Governance/Collaboration E2E; R3 approved |
| M9 | M9ReadModelsAdmin + Main | feat/internal-pilot-mvp-stabilization | done | 9231c9a | Project-scoped read models; Admin capabilities; real-handler E2E; R3 approved |
| M10 | Main | feat/internal-pilot-mvp-stabilization | done | cf14e51 | Mock state removed; parity E2E; 23 Playwright; 487 pytest; Ruff; Vitest/build |
| M11 | Main | feat/internal-pilot-mvp-stabilization | code_complete_data_api_pending | 5b6e337 | 523 pytest; Ruff; 7 Vitest; build; 24 Playwright; PR #18 CI all green; Embedding/O2/Tavily/primary+fallback LLM real/ready; Data API pending |

## Review and Release Ledger

| Gate | Scope | Reviewer | Status | Evidence |
| --- | --- | --- | --- | --- |
| R1 | M1-M3 Security Boundary | R1AuthIsolation + R1GovernanceReview | approved | 425 pytest; Ruff pass; secret scan clean |
| R2 | M4-M6 Availability + React Foundation | R2FoundationReview + R2ReReview | approved | 8 findings resolved; 461 pytest; Ruff; 7 Vitest; build; 11 Playwright |
| R3 | M7-M9 Browser Main Flows | R3Review + R3ReReview | approved | 18 findings plus tenant-thread regression resolved; 487 pytest; Ruff; 7 Vitest; build; 22 Playwright |
| Final | M10-M11 Release | Main | blocked_external | Local and GitHub CI gates pass; Data API real smoke and credential rotation pending |
