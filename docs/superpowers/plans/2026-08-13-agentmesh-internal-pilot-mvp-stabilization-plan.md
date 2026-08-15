# AgentMesh Internal Pilot MVP Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在单 Workspace、单实例、企业内网环境中稳定运行 AgentMesh，并以新 React 前端完成登录、对话、真实 Provider、文档、知识和协作主链。

**Architecture:** 保留 FastAPI/SQLite 为业务真相，只修复跨用户边界、MVP 必需治理和 Provider 可用性。Embedding、文档解析和外部 Provider 脱离 SQLite 写事务与事件循环。React 使用 Cookie session、OpenAPI 类型和 TanStack Query；旧 `app.html` 保留一个发布周期作为回滚入口。

**Tech Stack:** Python 3.12+、FastAPI、Pydantic、SQLite、pytest、Ruff、React 18、TypeScript 5.6、Vite 5、TanStack Query、OpenAPI TypeScript、Playwright、Vitest。

## Global Constraints

- 只支持企业内网、单 Workspace、单默认 Project、单 FastAPI 实例。
- 不开放公网，不承诺通用多租户和分布式 Worker。
- 多个真实用户之间必须隔离 PRIVATE chat、document 和 personal memory。
- Embedding、O2 Research、Web Research、外部 Data API 和 LLM 均需真实配置与 smoke。
- 自动化测试不得访问真实 Provider。
- FastAPI/SQLite 是业务真相，React 不复制权限和状态机。
- Embedding 和文档处理不得在 SQLite 写事务或 FastAPI event loop 内执行。
- 新 React 主链通过前，旧 `app.html` 保持回滚能力。
- LearnedSkill executor、delegated adoption、lineage UI、ANN、多 Workspace 和完整 Admin 延期。
- 执行前使用独立 worktree，不清理当前根工作区的用户文件。

## Execution Model: Wave Parallel

本计划使用“Wave 并行实施 + 3 次正式审查 + 1 次最终发布门禁”。任务章节中的测试和提交命令保留为协调者的命令清单；并行 Worker 不运行测试、Ruff、Build、Playwright 或项目级验证，也不生成 SDD 报告。

### Worker Contract

每个 Worker 只接收：

1. 本设计规格。
2. 本 Wave 的 Worker Contract 和验证归属。
3. 自己的任务章节。
4. 上游已冻结接口。
5. 允许修改的文件和禁止范围。
6. 需要新增或修改的测试文件。

Worker 负责：

- 读取任务直接相关的代码。
- 写失败用例和实现。
- 保持改动可单独识别。
- 返回文件清单、接口变化、风险和未验证项。

Worker 不负责：

- 重新遍历全仓。
- 运行测试、Ruff、Build 或浏览器。
- 生成任务报告。
- 启动第二轮 Reviewer。
- 修改其他 Wave 的接口。
- 提交、推送或发布。

### Orchestrator Contract

主协调者在每个 Wave：

1. 冻结跨任务接口和 query key/DTO/配置字段。
2. 一次性并行派发该 Wave 的任务。
3. 合并并检查所有返回改动。
4. 运行该 Wave 的聚焦测试和门禁。
5. 只进行一次正式审查。
6. 修复审查确认的问题。
7. 重新运行受影响门禁后提交。

同一 Wave 某个任务失败时，保留其他已完成任务，不重跑整个 Wave；只重新派发失败任务或由主协调者完成最小修复。

### Verification Ownership

| Surface | Worker | Orchestrator at gate |
| --- | --- | --- |
| Tests | 只编写 | 统一运行 |
| Ruff | 不运行 | 只检查 Wave 改动和必要全局门禁 |
| React build | 不运行 | R2、R3 和最终门禁运行 |
| Playwright | 不运行 | R2、R3 和最终门禁运行 |
| Real Provider smoke | 不运行 | 最终发布门禁运行一次 |
| Review report | 不生成 | 每个正式 Gate 输出一份 findings-first 结果 |
| Commit | 不提交 | Gate 通过后由主协调者提交 |

### Wave Schedule

```text
Wave 1: M1 + M2 + M3 并行
  -> Review Gate R1: Security Boundary

Wave 2: M4

Wave 3: M5 + M6 并行
  -> Review Gate R2: Backend Availability + React Foundation

Wave 4: M7 + M8 + M9 并行
  -> Review Gate R3: Browser Main Flows

Wave 5: M10

Wave 6: M11
  -> Final Release Gate
```

### Review Gate R1: Security Boundary

审查范围：M1、M2、M3。

审查重点：

- Secret 和默认凭据。
- Chat/Search/Document 跨用户访问。
- Memory/Blackboard 对象授权。
- OAuth disabled 生命周期。
- Market 匿名访问。

验证命令：

```bash
AGENTMESH_EMBEDDING_ENABLED=false .venv/bin/python -m pytest \
  tests/test_mvp_safe_config.py \
  tests/test_mvp_user_isolation.py \
  tests/test_mvp_governance.py \
  tests/test_permissions.py \
  tests/test_oauth.py -v
.venv/bin/ruff check agentmesh tests/test_mvp_safe_config.py tests/test_mvp_user_isolation.py tests/test_mvp_governance.py
AGENTMESH_EMBEDDING_ENABLED=false .venv/bin/python -m pytest -q
```

通过条件：没有 Critical/High 未处理 finding，聚焦测试和完整 pytest 通过。

### Review Gate R2: Backend Availability and React Foundation

审查范围：M4、M5、M6。

审查重点：

- Provider 配置、来源、失败和 secret 红线。
- Embedding 不持 SQLite 写锁。
- Document job 终态和可恢复性。
- Cookie session、401/403 和 Query cache。
- React 资产、SPA 路由和 API JSON 404。

验证命令：

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

通过条件：Provider/ingestion/auth/shell 契约通过，React build 和 Auth/Shell E2E 通过。

### Review Gate R3: Browser Main Flows

审查范围：M7、M8、M9。

审查重点：

- Workspace 消息、上传、搜索和 Provider 来源。
- Knowledge 确认、接受和 canonical state。
- Collaboration task、reply、lock/handoff 和 Market。
- Digital/Insights 只读真实性。
- Admin capability 和 Provider diagnostics。
- 页面中不存在 mock、timer success 和 handler-less control。

验证命令：

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

通过条件：三个浏览器主链和相关后端合同通过，正式审查无未处理 High finding。

### Final Release Gate

Final Release Gate 只在 M10 和 M11 完成后执行。它替代任务内重复的全量验证。

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

随后运行生产化 smoke：登录 user/Team Lead/Admin，走通五条 React 主链，重启服务并确认持久化。

### Generated Artifact Policy

- OpenAPI 类型只在 M6、R2 和 Final Gate 生成。
- React build 只在 R2、R3 和 Final Gate 执行。
- 真实 Provider smoke 只在 Final Gate 执行一次。
- 完整 pytest 只在 R1 和 Final Gate 执行；其他 Gate 使用聚焦测试。
- 审查只输出 confirmed findings，不写逐任务报告。

---

### Task M1: Secure Configuration and Explicit Demo Mode

**Files:**
- Modify: `agentmesh/embedding.py:13-26`
- Modify: `agentmesh/app.py:63-73`
- Modify: `agentmesh/seed.py:67-81,399-419`
- Modify: `tests/conftest.py`
- Modify: `.env.example`
- Modify: `README.md`
- Create: `tests/test_mvp_safe_config.py`

**Interfaces:**
- Produces: `EmbeddingConfig.from_env()` with default disabled
- Produces: `AGENTMESH_DEMO_MODE=1` explicit seed mode

- [ ] **Step 1: Rotate the exposed Embedding key outside Git**

Revoke/rotate through the provider. Record only a ticket/reference. Never store the replacement key in Git, logs or docs.

- [ ] **Step 2: Write failing safe-default tests**

```python
def test_embedding_disabled_without_opt_in(monkeypatch):
    monkeypatch.delenv("AGENTMESH_EMBEDDING_ENABLED", raising=False)
    monkeypatch.delenv("AGENTMESH_EMBEDDING_API_KEY", raising=False)
    assert EmbeddingConfig.from_env().enabled is False


def test_production_mode_does_not_seed_default_admin(store, monkeypatch):
    monkeypatch.delenv("AGENTMESH_DEMO_MODE", raising=False)
    initialize_application_data(store)
    assert store.get_auth_credential("usr_admin") is None
```

- [ ] **Step 3: Verify RED**

```bash
.venv/bin/python -m pytest tests/test_mvp_safe_config.py -v
```

- [ ] **Step 4: Implement safe defaults**

Embedding requires explicit enable, URL and key. Move data seeding from import time into lifespan. Tests and local demo run with `AGENTMESH_DEMO_MODE=1`; production-like run does not create fixed credentials.

- [ ] **Step 5: Verify and commit**

```bash
AGENTMESH_EMBEDDING_ENABLED=false .venv/bin/python -m pytest tests/test_mvp_safe_config.py tests/test_oauth.py tests/test_vector_search.py -v
.venv/bin/ruff check agentmesh/embedding.py agentmesh/app.py agentmesh/seed.py tests/test_mvp_safe_config.py
git add agentmesh/embedding.py agentmesh/app.py agentmesh/seed.py tests/conftest.py tests/test_mvp_safe_config.py .env.example README.md
git commit -m "Secure MVP configuration"
```

### Task M2: Enforce Cross-User Privacy

**Files:**
- Modify: `agentmesh/routes/chat.py`
- Modify: `agentmesh/agents.py:119-145,1627-1662`
- Modify: `agentmesh/routes/workspace.py:67-89`
- Modify: `agentmesh/store.py:885-1055`
- Modify: `agentmesh/routes/documents.py:70-166`
- Create: `tests/test_mvp_user_isolation.py`

**Interfaces:**
- Produces: owner-scoped thread history and append
- Produces: `document_visible_to_user(document, user)`

- [ ] **Step 1: Write failing two-user tests**

```python
def test_user_cannot_send_to_another_users_thread():
    response = client_for(USER_B).post(
        "/api/chat/messages",
        json={"thread_id": thread_for_a.id, "content": "attack"},
    )
    assert response.status_code == 404


def test_private_search_and_documents_are_owner_only():
    assert search_as(USER_B, "private-a") == []
    assert client_for(USER_B).get(f"/api/documents/{document_a.id}").status_code == 404
```

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/python -m pytest tests/test_mvp_user_isolation.py -v
```

- [ ] **Step 3: Authorize before reading or writing**

Thread owner check runs before history load. PRIVATE chat search checks thread owner. Document list/detail/update/import share one owner/admin predicate. New thread IDs are generated server-side.

- [ ] **Step 4: Keep single Workspace explicit**

Do not add generic TenantContext in MVP. Routes use the configured single workspace/default project and reject attempts to target unrelated projects. Hide Workspace/Project creation from React.

- [ ] **Step 5: Verify and commit**

```bash
AGENTMESH_EMBEDDING_ENABLED=false .venv/bin/python -m pytest tests/test_mvp_user_isolation.py tests/test_multiturn.py tests/test_documents.py tests/test_search_fts.py -v
.venv/bin/ruff check agentmesh/routes/chat.py agentmesh/routes/workspace.py agentmesh/routes/documents.py agentmesh/agents.py agentmesh/store.py
git add agentmesh/routes/chat.py agentmesh/routes/workspace.py agentmesh/routes/documents.py agentmesh/agents.py agentmesh/store.py tests/test_mvp_user_isolation.py
git commit -m "Enforce MVP user isolation"
```

### Task M3: Add Minimum Governance Guards

**Files:**
- Modify: `agentmesh/routes/memory.py`
- Modify: `agentmesh/permissions.py`
- Modify: `agentmesh/routes/blackboard.py`
- Modify: `agentmesh/routes/market.py`
- Modify: `agentmesh/routes/auth.py`
- Modify: `agentmesh/models.py`
- Create: `tests/test_mvp_governance.py`

**Interfaces:**
- Produces: MVP Memory transitions `proposed/candidate -> accepted`
- Produces: unified `authorize_blackboard_action()`

- [ ] **Step 1: Write failing guard tests**

Cover direct TEAM_ACCEPTED create rejection, ordinary-user memory downgrade rejection, hidden-post lock/reply denial, non-owner unlock denial, actor/status mass-assignment rejection, anonymous market board 401 and disabled OAuth user 403.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/python -m pytest tests/test_mvp_governance.py -v
```

- [ ] **Step 3: Restrict Memory to MVP states**

Create yields proposed/team_candidate. Team Lead/Admin can accept. Other status mutations are unavailable through MVP API/UI. Existing unsupported states remain readable for compatibility but cannot be newly written.

- [ ] **Step 4: Secure Blackboard, Market and OAuth**

All post mutations check visibility and action permission; server sets actor and queue status. Review/drain requires admin/governance capability. Market board requires auth. OAuth preserves local disabled status and does not trust profile role directly.

- [ ] **Step 5: Verify and commit**

```bash
AGENTMESH_EMBEDDING_ENABLED=false .venv/bin/python -m pytest tests/test_mvp_governance.py tests/test_permissions.py tests/test_chat_flow.py -k "memory or blackboard or lock or handoff" -v
.venv/bin/ruff check agentmesh/routes/memory.py agentmesh/routes/blackboard.py agentmesh/routes/market.py agentmesh/routes/auth.py
git add agentmesh/routes/memory.py agentmesh/permissions.py agentmesh/routes/blackboard.py agentmesh/routes/market.py agentmesh/routes/auth.py agentmesh/models.py tests/test_mvp_governance.py
git commit -m "Add MVP governance guards"
```

### Task M4: Make All Real Providers Configurable and Observable

**Files:**
- Modify: `agentmesh/routes/health.py`
- Modify: `agentmesh/embedding.py`
- Modify: `agentmesh/o2.py`
- Modify: `agentmesh/web_research.py`
- Modify: `agentmesh/datasources.py`
- Modify: `agentmesh/routes/data_sources.py`
- Modify: `agentmesh/llm.py`
- Create: `agentmesh/provider_status.py`
- Create: `tests/test_mvp_provider_contracts.py`
- Create: `scripts/provider_smoke.py`

**Interfaces:**
- Produces: `ProviderStatus(name, configured, ready, mode, last_error, latency_ms)`
- Produces: source metadata `requested_provider`, `actual_provider`, `fallback_reason`

- [ ] **Step 1: Write provider contract tests**

Use mocks to cover success, timeout, auth failure, malformed response, fallback and no-fallback. Assert no secrets appear in status/errors. Assert Data Provider requires an authorized Agent tool grant.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/python -m pytest tests/test_mvp_provider_contracts.py -v
```

- [ ] **Step 3: Implement unified status and provenance**

Health includes Embedding, O2 Research, Web Research, Data API and LLM. Each result records actual provider and sources. Data connector checks allowlisted operation and current user's Agent grant.

- [ ] **Step 4: Add real smoke command**

```bash
.venv/bin/python scripts/provider_smoke.py --embedding --o2 --web --data --llm
```

The script executes one minimal read-only request per provider, prints redacted status and exits non-zero on failure. It never writes secrets or response bodies containing sensitive data.

- [ ] **Step 5: Verify and commit**

```bash
AGENTMESH_EMBEDDING_ENABLED=false .venv/bin/python -m pytest tests/test_mvp_provider_contracts.py tests/test_o2.py tests/test_web_research.py tests/test_datasources.py tests/test_health.py -v
.venv/bin/ruff check agentmesh/provider_status.py agentmesh/routes/health.py scripts/provider_smoke.py
git add agentmesh/provider_status.py agentmesh/routes/health.py agentmesh/embedding.py agentmesh/o2.py agentmesh/web_research.py agentmesh/datasources.py agentmesh/routes/data_sources.py agentmesh/llm.py tests/test_mvp_provider_contracts.py scripts/provider_smoke.py
git commit -m "Add observable real providers"
```

### Task M5: Decouple Embedding and Stabilize Document Jobs

**Files:**
- Create: `agentmesh/vector_index.py`
- Create: `agentmesh/ingestion.py`
- Modify: `agentmesh/store.py:255-354`
- Modify: `agentmesh/routes/documents.py`
- Modify: `agentmesh/documents.py`
- Modify: `agentmesh/models.py`
- Create: `tests/test_mvp_ingestion_stability.py`
- Create: `tests/test_mvp_sqlite_concurrency.py`

**Interfaces:**
- Produces: vector states `pending/ready/stale/failed`
- Produces: document job states `queued/running/completed/failed`

- [ ] **Step 1: Write blocked-provider and failure tests**

Assert a blocked embedding request does not block another SQLite write. Assert failed document chunk/import leaves failed job, invalidates partial current version and can retry. Assert old vector does not rank updated text.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/python -m pytest tests/test_mvp_ingestion_stability.py tests/test_mvp_sqlite_concurrency.py -v
```

- [ ] **Step 3: Move external work outside transaction/event loop**

Persist record/FTS with vector pending, compute embedding in bounded thread/worker, then short-transaction vector upsert. Parse/chunk/embed document in a bounded background worker, not directly inside async upload route.

- [ ] **Step 4: Make jobs terminal and retryable**

Unexpected exceptions enter failed. Track document version and expected chunk count. Update makes old chunks/vector stale. Retry completes missing current-version chunks without duplication.

- [ ] **Step 5: Verify and commit**

```bash
AGENTMESH_EMBEDDING_ENABLED=false .venv/bin/python -m pytest tests/test_mvp_ingestion_stability.py tests/test_mvp_sqlite_concurrency.py tests/test_documents.py tests/test_pdf.py tests/test_vector_search.py -v
.venv/bin/ruff check agentmesh/vector_index.py agentmesh/ingestion.py agentmesh/routes/documents.py agentmesh/store.py
git add agentmesh/vector_index.py agentmesh/ingestion.py agentmesh/store.py agentmesh/routes/documents.py agentmesh/documents.py agentmesh/models.py tests/test_mvp_ingestion_stability.py tests/test_mvp_sqlite_concurrency.py
git commit -m "Stabilize MVP ingestion"
```

### Task M6: Add React Auth, API, Query, and Shell

**Files:**
- Modify: `agentmesh-demo/package.json`
- Modify: `agentmesh-demo/vite.config.ts`
- Create: `agentmesh-demo/scripts/export_openapi.py`
- Create: `agentmesh-demo/src/api/`
- Create: `agentmesh-demo/src/app/queryClient.ts`
- Create: `agentmesh-demo/src/features/auth/`
- Modify: `agentmesh-demo/src/main.tsx`
- Modify: `agentmesh-demo/src/App.tsx`
- Modify: `agentmesh/app.py`
- Create: `agentmesh-demo/e2e/auth-shell.spec.ts`

**Interfaces:**
- Produces: `ApiError`, `apiRequest<T>`, `AuthProvider`, `useAuth()`
- Produces: React asset hosting and explicit SPA routes

- [ ] **Step 1: Add dependencies and failing browser tests**

Add TanStack Query, OpenAPI TypeScript, Vitest and Playwright. Test login/reload/logout, 401/403, root and deep links, JSON API 404, responsive shell and legacy rollback route.

- [ ] **Step 2: Implement typed client and auth**

Use relative `/api`, same-origin Cookie and generated types. 401 clears auth/query cache. 403 keeps signed-in state. No hardcoded login helper.

- [ ] **Step 3: Serve React safely**

Mount Vite assets and explicit product routes. Keep old UI at `/legacy/app.html`. Do not add a catch-all that can return HTML for unknown API paths.

- [ ] **Step 4: Verify**

```bash
cd agentmesh-demo
npm run api:types
npm run test
npm run build
npm run test:e2e -- e2e/auth-shell.spec.ts
cd ..
.venv/bin/python -m pytest tests/test_frontend_routes.py tests/test_oauth.py -v
```

- [ ] **Step 5: Commit**

```bash
git add agentmesh-demo agentmesh/app.py tests/test_frontend_routes.py
git commit -m "Add MVP React foundation"
```

### Task M7: Connect Workspace and Real Provider Traces

**Files:**
- Create: `agentmesh-demo/src/features/workspace/`
- Modify: `agentmesh-demo/src/pages/Workspace.tsx`
- Modify: `agentmesh-demo/src/components/workspace/`
- Create: `agentmesh-demo/e2e/workspace-mvp.spec.ts`

**Interfaces:**
- Consumes: threads/messages/skills/documents/search/provider sources

- [ ] **Step 1: Write failing browser flow**

Create thread, send natural message, run `$research.request`, observe actual provider/source, upload document, wait job terminal, search result, reload and verify persistence. Simulate provider failure and assert no success toast.

- [ ] **Step 2: Replace Workspace mocks**

Server thread/message/task/resources drive UI. Pending state is temporary only. Upload shows job status. Detail panel loads by stable resource ID.

- [ ] **Step 3: Render Provider provenance**

Show actual provider, source title/reference, fallback reason and degraded state without exposing credentials.

- [ ] **Step 4: Verify**

```bash
cd agentmesh-demo && npm run test && npm run build && npm run test:e2e -- e2e/workspace-mvp.spec.ts
cd ..
AGENTMESH_EMBEDDING_ENABLED=false .venv/bin/python -m pytest tests/test_multiturn.py tests/test_documents.py tests/test_search_fts.py tests/test_mvp_provider_contracts.py -v
```

- [ ] **Step 5: Commit**

```bash
git add agentmesh-demo/src/features/workspace agentmesh-demo/src/pages/Workspace.tsx agentmesh-demo/src/components/workspace agentmesh-demo/e2e/workspace-mvp.spec.ts
git commit -m "Connect MVP workspace"
```

### Task M8: Connect Knowledge and Collaboration Core

**Files:**
- Create: `agentmesh-demo/src/features/knowledge/`
- Create: `agentmesh-demo/src/features/collaboration/`
- Modify: `agentmesh-demo/src/pages/Knowledge.tsx`
- Modify: `agentmesh-demo/src/pages/Collaboration.tsx`
- Modify: related components
- Create: `agentmesh-demo/e2e/governance-collaboration-mvp.spec.ts`

**Interfaces:**
- Consumes: Inbox/Memory allowed actions, task cards/detail and authorized Blackboard commands

- [ ] **Step 1: Write failing governance flow**

Create/confirm Brief, snooze/resolve Inbox, Team Lead accepts candidate, open task, reply, lock/handoff/unlock, view authenticated market status and toggle participation.

- [ ] **Step 2: Remove local business state**

删除 `DemoContext` 计数器、本地授权集合和定时器成功状态。标签页、计数和动作来自服务端。“仅自己”不会进入共享列表。

- [ ] **Step 3: Invalidate exact resources**

After mutations refresh Inbox, Memory, task detail/cards, market, audit and bootstrap metrics. 409 refreshes canonical state.

- [ ] **Step 4: Verify**

```bash
cd agentmesh-demo && npm run test && npm run build && npm run test:e2e -- e2e/governance-collaboration-mvp.spec.ts
cd ..
AGENTMESH_EMBEDDING_ENABLED=false .venv/bin/python -m pytest tests/test_mvp_governance.py tests/test_permissions.py tests/test_chat_flow.py -k "memory or inbox or blackboard" -v
```

- [ ] **Step 5: Commit**

```bash
git add agentmesh-demo/src/features/knowledge agentmesh-demo/src/features/collaboration agentmesh-demo/src/pages/Knowledge.tsx agentmesh-demo/src/pages/Collaboration.tsx agentmesh-demo/src/components/knowledge agentmesh-demo/src/components/collaboration agentmesh-demo/e2e/governance-collaboration-mvp.spec.ts
git commit -m "Connect MVP governance and collaboration"
```

### Task M9: Add Read-Only Digital/Insights and Minimum Admin

**Files:**
- Create: `agentmesh-demo/src/features/digital-self/`
- Create: `agentmesh-demo/src/features/insights/`
- Create: `agentmesh-demo/src/features/admin/`
- Modify: corresponding pages and layout settings/profile
- Create: `agentmesh-demo/e2e/read-model-admin-mvp.spec.ts`

**Interfaces:**
- Consumes: bootstrap/activity/audit/memory/task/provider health/users/agents

- [ ] **Step 1: Write role and read-model tests**

Digital Self and Insights show server data/empty state only. Regular user denied Admin. Admin can list/create/disable/reset users, view Agent model/tools, provider health, O2 sync, policies and audit.

- [ ] **Step 2: Remove unsupported controls**

Hide editable understanding, preferences, impact scoring, project review, multi-workspace, schedules and full policy editor. No handler-less button remains.

- [ ] **Step 3: Capability-gate each Admin module**

Use relevant capability, not a single `manage_users` gate. Provider diagnostics display configured/ready/mode/last_error.

- [ ] **Step 4: Verify**

```bash
cd agentmesh-demo && npm run test && npm run build && npm run test:e2e -- e2e/read-model-admin-mvp.spec.ts
cd ..
AGENTMESH_EMBEDDING_ENABLED=false .venv/bin/python -m pytest tests/test_permissions.py tests/test_health.py tests/test_o2.py -v
```

- [ ] **Step 5: Commit**

```bash
git add agentmesh-demo/src/features/digital-self agentmesh-demo/src/features/insights agentmesh-demo/src/features/admin agentmesh-demo/src/pages agentmesh-demo/src/components/layout agentmesh-demo/src/components/digital-self agentmesh-demo/src/components/insights agentmesh-demo/e2e/read-model-admin-mvp.spec.ts
git commit -m "Add MVP read models and admin"
```

### Task M10: Cut Over React and Remove Production Mock State

**Files:**
- Modify: `agentmesh/app.py`
- Modify: `README.md`
- Modify: `CONTEXT.md`
- Delete: `agentmesh-demo/src/data/mockData.ts`
- Delete: `agentmesh-demo/src/store/DemoContext.tsx`
- Create: `agentmesh-demo/e2e/mvp-parity.spec.ts`

**Interfaces:**
- Consumes: M6-M9
- Produces: React default route and `/legacy/app.html` rollback

- [ ] **Step 1: Write MVP parity test**

Cover login, Workspace, Provider source, upload/search, Knowledge confirm, Collaboration task, Admin diagnostics, deep-link reload and no local demo strings.

- [ ] **Step 2: Delete production mock dependencies**

Remove mock data, local business counters, timer success and handler-less controls. Unsupported routes/controls are hidden, not simulated.

- [ ] **Step 3: Switch root to React**

`/` and product paths return React index. `/legacy/app.html` serves old page for one release cycle. Unknown API remains JSON 404.

- [ ] **Step 4: Verify**

```bash
cd agentmesh-demo && npm run api:types && npm run test && npm run build && npm run test:e2e
cd ..
AGENTMESH_EMBEDDING_ENABLED=false .venv/bin/python -m pytest
.venv/bin/ruff check .
```

- [ ] **Step 5: Commit**

```bash
git add -A agentmesh/app.py agentmesh-demo README.md CONTEXT.md
git commit -m "Cut over the internal pilot React UI"
```

### Task M11: Add Minimum CI and Run the MVP Release Gate

**Files:**
- Modify: `.gitignore`
- Modify: `pyproject.toml`
- Create: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `CONTEXT.md`
- Modify: `docs/superpowers/plans/2026-08-13-agentmesh-audit-remediation-implementation-plan.md`
- Modify: `docs/agentmesh-audit-remediation-todo.md`

**Interfaces:**
- Consumes: M1-M10
- Produces: repeatable CI and internal Provider smoke evidence

- [ ] **Step 1: Fix repository and dependency hygiene**

Ignore Node/Vite/Playwright artifacts. Declare PyMuPDF or remove unsupported promise. Fix all Ruff findings without blanket ignores.

- [ ] **Step 2: Add minimum CI**

Backend: clean install, secret scan, Ruff, pytest with embedding disabled. Frontend: npm ci, types, unit tests, build. E2E: isolated SQLite and mock providers.

- [ ] **Step 3: Run all real Provider smokes in the internal environment**

```bash
.venv/bin/python scripts/provider_smoke.py --embedding --o2 --web --data --llm
```

Record redacted provider, mode, source and latency. All five must pass for this MVP contract.

- [ ] **Step 4: Run final release gate**

```bash
AGENTMESH_EMBEDDING_ENABLED=false .venv/bin/python -m pytest
.venv/bin/ruff check .
cd agentmesh-demo
npm run api:types
npm run test
npm run build
npm run test:e2e
```

Then start production-like FastAPI with isolated SQLite, log in as user/Team Lead/Admin, exercise five React main paths, restart and confirm persistence.

- [ ] **Step 5: Update docs and commit**

README/CONTEXT explicitly state single Workspace, single instance, internal network, real Provider smoke and Post-MVP deferrals.

```bash
git add .gitignore pyproject.toml .github/workflows/ci.yml README.md CONTEXT.md docs
git commit -m "Complete internal pilot MVP stabilization"
```

## MVP Completion Criteria

- No tracked secret or fixed production password.
- Multiple users cannot read or write each other's PRIVATE chat/documents.
- New React is the default UI and uses real APIs for five MVP paths.
- Embedding, O2, Web, Data and LLM have health, timeout, provenance and passing internal smoke.
- Provider failure does not hold SQLite write lock or block the API event loop.
- Memory/Blackboard MVP actions are server-authorized and audited.
- Pytest, Ruff, React types/tests/build and core Playwright pass in CI.
- README/CONTEXT state the single Workspace/single instance limit and deferred capabilities.
