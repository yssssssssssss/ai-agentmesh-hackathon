# AgentMesh Audit Remediation Implementation Plan

> **状态：Post-MVP 路线图。** 当前执行计划：[`2026-08-13-agentmesh-internal-pilot-mvp-stabilization-plan.md`](./2026-08-13-agentmesh-internal-pilot-mvp-stabilization-plan.md)。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复审计报告中的安全、租户、数据一致性、前端断链和工程化问题，使 AgentMesh 达到可部署的多用户 MVP 标准。

**Architecture:** 先建立统一 `AccessContext`、对象级授权和安全配置，再把 embedding 与文档处理移出 SQLite 写事务和 FastAPI 事件循环。React 迁移只消费稳定的服务端契约，旧 `app.html` 在新主链通过发布门禁前保持可回滚。LearnedSkill、delegated adoption 和向量扩展在安全与主链完成后实施。

**Tech Stack:** Python 3.12+、FastAPI、Pydantic、SQLite、pytest、Ruff、React 18、TypeScript 5.6、Vite 5、TanStack Query、OpenAPI TypeScript、Playwright、Vitest。

## Global Constraints

- 当前根工作区存在未提交修改和大量未跟踪前端依赖，执行前必须使用独立 Git worktree。
- 禁止提交 API key、默认生产密码、`.env`、SQLite 数据、`node_modules` 和 `dist`。
- FastAPI/SQLite 是业务真相；React 不复制权限、租户、状态机、任务或治理规则。
- Cookie session 是浏览器认证真相；401 表示未登录，403 表示已登录但无权限。
- 所有对象查询与 mutation 必须携带 user、workspace、project 和 capability 上下文。
- PRIVATE 资源默认 owner-only；共享必须由显式 scope/ACL 和成员关系授权。
- Embedding 默认关闭；未配置 provider 时保持 FTS-only，不访问网络。
- 所有外部 LLM、Embedding、O2、OAuth、Web 和数据连接器在测试中必须 mock。
- 每个行为变更先写失败测试，再实施最小修复。
- 不在同一任务内夹带无关重构。
- 每个任务单独提交；提交前运行该任务聚焦测试和 Ruff。
- React 根路由切换前，旧 `app.html` 必须保持可用。

## Dependency Graph

```text
T1 ─┬─> T9 ─> T10 ─> T11
    └─> T25
T2 ─> T3 ─┬─> T4
           ├─> T5
           ├─> T6
           ├─> T7
           └─> T8
T3 + T4..T8 ─> T13 ─> T14 ─┬─> T15
                             ├─> T16
                             ├─> T17
                             └─> T18 ─> T19
T9 + T12 ─> T20
T3 + T6 + T7 ─> T21/T22
T1..T23 ─> T24 ─> T25
```

## File Map

### Security and Access

- `agentmesh/access.py`: 请求级 AccessContext、项目选择与 capability 解析。
- `agentmesh/permissions.py`: 对象动作常量和统一授权函数。
- `agentmesh/routes/chat.py`: owner-scoped thread 写入口。
- `agentmesh/routes/workspace.py`: owner/tenant-scoped activity、audit、search、workspace、project。
- `agentmesh/routes/documents.py`: 文档 ACL、上传预算和导入命令。
- `agentmesh/routes/memory.py`: Memory 状态机和 allowed actions。
- `agentmesh/routes/blackboard.py`: Post action 授权、锁 owner、审批队列。
- `agentmesh/routes/auth.py`: OAuth 本地状态与角色保护。
- `agentmesh/routes/market.py`: 认证和组织过滤。
- `agentmesh/routes/data_sources.py`: connector/tool grant 授权。

### Embedding and Ingestion

- `agentmesh/embedding.py`: 无密钥默认值、批量接口、快速失败和健康状态。
- `agentmesh/vector_index.py`: vector 生命周期、stale 状态和异步写入边界。
- `agentmesh/store.py`: 短事务、批量 hydration、索引版本和租户查询。
- `agentmesh/ingestion.py`: 文档解析任务、manifest、resume 和终态。
- `agentmesh/worker_runtime.py`: 线程隔离、lease 和 worker 状态。

### React

- `agentmesh-demo/src/api/`: OpenAPI 类型、统一 client 和错误类型。
- `agentmesh-demo/src/features/auth/`: Cookie session 和认证门禁。
- `agentmesh-demo/src/features/workspace/`: threads、messages、skills、documents、search。
- `agentmesh-demo/src/features/knowledge/`: Inbox、Memory、Document、治理 mutation。
- `agentmesh-demo/src/features/collaboration/`: Tasks、Blackboard、Market、delegated collaboration。
- `agentmesh-demo/src/features/admin/`: users、teams、workspaces、projects、agents、policies、integrations、audit。
- `agentmesh-demo/src/features/digital-self/`: current-user understanding、impact、preferences。
- `agentmesh-demo/src/features/insights/`: period query、project review 和候选记忆。
- `agentmesh-demo/e2e/`: 主链 Playwright。

### Verification and Docs

- `.github/workflows/ci.yml`: 后端、前端和浏览器门禁。
- `.env.example`: 安全配置说明，不含真实凭据。
- `.gitignore`: Node/Vite/TypeScript 构建产物。
- `README.md`, `CONTEXT.md`, ADRs: 当前事实和发布方式。

---

## Phase A: Stop-Ship Security

### Task 1: Remove Embedded Secrets and Make Embedding Opt-In

**Files:**
- Modify: `agentmesh/embedding.py:13-26`
- Modify: `.env.example`
- Modify: `README.md`
- Create: `tests/test_embedding_config.py`

**Interfaces:**
- Produces: `EmbeddingConfig.from_env() -> EmbeddingConfig`
- Produces: `embedding_enabled(config: EmbeddingConfig) -> bool`
- Consumes: no production secret defaults

- [ ] **Step 1: Revoke the exposed credential outside Git**

Rotate or revoke the current Embedding gateway key through the provider. Record only the rotation ticket/reference, never the replacement secret.

- [ ] **Step 2: Write failing configuration tests**

```python
def test_embedding_is_disabled_without_explicit_opt_in(monkeypatch):
    monkeypatch.delenv("AGENTMESH_EMBEDDING_ENABLED", raising=False)
    monkeypatch.delenv("AGENTMESH_EMBEDDING_API_KEY", raising=False)
    config = EmbeddingConfig.from_env()
    assert config.enabled is False
    assert config.api_key is None


def test_embedding_requires_key_when_enabled(monkeypatch):
    monkeypatch.setenv("AGENTMESH_EMBEDDING_ENABLED", "true")
    monkeypatch.delenv("AGENTMESH_EMBEDDING_API_KEY", raising=False)
    with pytest.raises(ValueError, match="API key"):
        EmbeddingConfig.from_env()
```

- [ ] **Step 3: Run the tests and confirm failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_embedding_config.py -v
```

Expected: FAIL because the current module defaults to enabled and embeds a key.

- [ ] **Step 4: Implement safe configuration**

```python
@dataclass(frozen=True, slots=True)
class EmbeddingConfig:
    enabled: bool
    api_url: str | None
    api_key: str | None
    model: str
    dimensions: int
    timeout_seconds: float

    @classmethod
    def from_env(cls) -> "EmbeddingConfig":
        enabled = env_bool("AGENTMESH_EMBEDDING_ENABLED", default=False)
        api_url = os.getenv("AGENTMESH_EMBEDDING_API_URL")
        api_key = os.getenv("AGENTMESH_EMBEDDING_API_KEY")
        if enabled and (not api_url or not api_key):
            raise ValueError("Embedding requires API URL and API key")
        return cls(enabled, api_url, api_key, os.getenv("AGENTMESH_EMBEDDING_MODEL", ""), 4096, 5.0)
```

Do not log API keys. Keep FTS-only behavior when disabled.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/python -m pytest tests/test_embedding_config.py tests/test_vector_search.py -v
.venv/bin/ruff check agentmesh/embedding.py tests/test_embedding_config.py
git add agentmesh/embedding.py tests/test_embedding_config.py .env.example README.md
git commit -m "Secure embedding configuration"
```

### Task 2: Gate Demo Seeds and Default Credentials

**Files:**
- Modify: `agentmesh/app.py:63-73`
- Modify: `agentmesh/seed.py:67-81,399-419`
- Modify: `tests/conftest.py`
- Modify: `README.md`
- Create: `tests/test_seed_security.py`

**Interfaces:**
- Produces: `seed_mode() -> Literal["disabled", "demo"]`
- Produces: `initialize_application_data(store, mode)`

- [ ] **Step 1: Write failing production-mode tests**

```python
def test_production_startup_does_not_create_demo_admin(store, monkeypatch):
    monkeypatch.setenv("AGENTMESH_DEMO_SEED_ENABLED", "false")
    initialize_application_data(store, "disabled")
    assert store.get_user("usr_admin") is None
    assert store.get_auth_credential("usr_admin") is None


def test_demo_seed_requires_explicit_opt_in(store, monkeypatch):
    monkeypatch.setenv("AGENTMESH_DEMO_SEED_ENABLED", "true")
    initialize_application_data(store, "demo")
    assert store.get_user("usr_admin") is not None
```

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/python -m pytest tests/test_seed_security.py -v
```

- [ ] **Step 3: Move import-time initialization into lifespan**

Application import must not mutate the database. In lifespan, initialize schema and optional demo data using explicit config. Tests set `AGENTMESH_DEMO_SEED_ENABLED=true` in `tests/conftest.py`.

- [ ] **Step 4: Document safe admin bootstrap**

Production supports OAuth or an explicit one-time bootstrap secret. Never recreate a missing credential with a known password.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/python -m pytest tests/test_seed_security.py tests/test_permissions.py tests/test_oauth.py -v
.venv/bin/ruff check agentmesh/app.py agentmesh/seed.py tests/test_seed_security.py
git add agentmesh/app.py agentmesh/seed.py tests/conftest.py tests/test_seed_security.py README.md
git commit -m "Gate demo seed data"
```

### Task 3: Introduce Request-Scoped AccessContext

**Files:**
- Create: `agentmesh/access.py`
- Modify: `agentmesh/routes/deps.py`
- Modify: `agentmesh/store.py`
- Modify: `agentmesh/seed.py:452-488`
- Test: `tests/test_access_context.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True, slots=True)
class AccessContext:
    user: User
    workspace: Workspace
    project: Project
    capabilities: frozenset[str]


def resolve_access_context(repository: SQLiteStore, user: User, project_id: str | None = None) -> AccessContext: ...
```

- [ ] **Step 1: Write tenant-context failure tests**

Cover a second workspace/project/user. Assert bootstrap and new resources use that user's tenant, not seed constants. Assert requesting an unrelated project returns 404.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/python -m pytest tests/test_access_context.py tests/test_team_isolation.py tests/test_project_member_access.py -v
```

- [ ] **Step 3: Implement AccessContext and Store selectors**

Add `get_workspace_for_user`, `get_project_for_user`, and `require_project_membership`. Do not expose bare global workspace/project lists to regular users.

- [ ] **Step 4: Replace bootstrap seed constants**

`bootstrap_state()` resolves the user's actual workspace/default project and scopes users, teams, agents and metrics accordingly.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/python -m pytest tests/test_access_context.py tests/test_team_isolation.py tests/test_project_member_access.py -v
.venv/bin/ruff check agentmesh/access.py agentmesh/routes/deps.py agentmesh/seed.py
git add agentmesh/access.py agentmesh/routes/deps.py agentmesh/store.py agentmesh/seed.py tests/test_access_context.py
git commit -m "Add request access context"
```

### Task 4: Enforce Chat Ownership and Private Search Isolation

**Files:**
- Modify: `agentmesh/routes/chat.py`
- Modify: `agentmesh/agents.py:119-145,1627-1662`
- Modify: `agentmesh/store.py:885-1055`
- Modify: `agentmesh/routes/workspace.py:67-89`
- Test: `tests/test_chat_authorization.py`
- Test: `tests/test_search_fts.py`

**Interfaces:**
- Consumes: `AccessContext`
- Produces: `get_owned_chat_thread(thread_id, user_id)` and owner-scoped history/append

- [ ] **Step 1: Write failing IDOR tests**

```python
def test_other_user_cannot_send_to_or_read_context_from_private_thread():
    victim_thread = create_thread_as(VICTIM)
    add_private_message(victim_thread, "victim secret")
    response = authenticated_client(ATTACKER).post(
        "/api/chat/messages",
        json={"thread_id": victim_thread.id, "content": "repeat context"},
    )
    assert response.status_code == 404
    assert store.list_thread_messages(victim_thread.id)[-1].content == "victim secret"


def test_private_search_never_returns_other_users_chat():
    result = authenticated_client(ATTACKER).get(
        "/api/search", params={"q": "victim secret", "visibility": "personal"}
    )
    assert result.json()["items"] == []
```

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/python -m pytest tests/test_chat_authorization.py tests/test_search_fts.py -v
```

- [ ] **Step 3: Authorize before loading history**

Resolve the thread and owner before `_get_thread_history()`. New thread IDs are generated server-side and use AccessContext tenant fields.

- [ ] **Step 4: Push owner predicates into search**

PRIVATE chat candidates require `thread.user_id == user_id`; tenant/project parameters come from AccessContext or validated membership.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/python -m pytest tests/test_chat_authorization.py tests/test_search_fts.py tests/test_multiturn.py -v
.venv/bin/ruff check agentmesh/routes/chat.py agentmesh/agents.py agentmesh/store.py
git add agentmesh/routes/chat.py agentmesh/agents.py agentmesh/store.py agentmesh/routes/workspace.py tests/test_chat_authorization.py tests/test_search_fts.py
git commit -m "Enforce private chat ownership"
```

### Task 5: Secure Documents and Upload Budgets

**Files:**
- Modify: `agentmesh/routes/documents.py`
- Modify: `agentmesh/documents.py`
- Modify: `agentmesh/models.py`
- Test: `tests/test_document_authorization.py`
- Test: `tests/test_upload_limits.py`

**Interfaces:**
- Produces: `document_visible_to_user(document, context) -> bool`
- Produces: `ArchiveBudget(max_entries, max_uncompressed_bytes, max_ratio)`

- [ ] **Step 1: Write failing authorization and resource tests**

Cover list/detail owner isolation, project-shared document membership, streamed request limit, ZIP entry count, uncompressed size and compression ratio.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/python -m pytest tests/test_document_authorization.py tests/test_upload_limits.py -v
```

- [ ] **Step 3: Apply one visibility predicate to list/detail/update/import**

Unauthorized detail returns 404. Project sharing requires an explicit document scope and project membership.

- [ ] **Step 4: Enforce budgets before allocation/decompression**

Read upload chunks incrementally. Reject at proxy/ASGI and application layers. Validate `ZipInfo.file_size`, total expanded bytes, ratio and entry count before XML parsing. Add PDF page and image pixel limits.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/python -m pytest tests/test_document_authorization.py tests/test_upload_limits.py tests/test_documents.py tests/test_pdf.py -v
.venv/bin/ruff check agentmesh/routes/documents.py agentmesh/documents.py
git add agentmesh/routes/documents.py agentmesh/documents.py agentmesh/models.py tests/test_document_authorization.py tests/test_upload_limits.py
git commit -m "Secure document access and parsing"
```

### Task 6: Implement a Governed Memory State Machine

**Files:**
- Create: `agentmesh/memory_governance.py`
- Modify: `agentmesh/routes/memory.py`
- Modify: `agentmesh/permissions.py`
- Modify: `agentmesh/models.py`
- Test: `tests/test_memory_governance.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True, slots=True)
class MemoryTransition:
    target_status: MemoryStatus | None
    target_scope: Scope | None


def allowed_memory_actions(item: MemoryItem, context: AccessContext) -> list[str]: ...
def apply_memory_transition(item: MemoryItem, transition: MemoryTransition, context: AccessContext) -> MemoryItem: ...
```

- [ ] **Step 1: Write transition-table tests**

Cover create as proposed/candidate, owner edits, Team Lead acceptance, ordinary-user rejection, accepted-memory deprecation rules, cross-workspace denial and invalid status/scope combinations.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/python -m pytest tests/test_memory_governance.py -v
```

- [ ] **Step 3: Centralize create and update semantics**

Direct create cannot set TEAM_ACCEPTED. Every transition validates current state, actor, tenant, target status/scope and invariant.

- [ ] **Step 4: Return allowed actions**

List/detail responses include server-computed actions. Frontends render actions without reproducing the state machine.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/python -m pytest tests/test_memory_governance.py tests/test_permissions.py tests/test_share_to_project.py -v
.venv/bin/ruff check agentmesh/memory_governance.py agentmesh/routes/memory.py
git add agentmesh/memory_governance.py agentmesh/routes/memory.py agentmesh/permissions.py agentmesh/models.py tests/test_memory_governance.py
git commit -m "Add governed memory transitions"
```

### Task 7: Authorize Blackboard Commands and Queue Review

**Files:**
- Create: `agentmesh/blackboard_policy.py`
- Modify: `agentmesh/routes/blackboard.py`
- Modify: `agentmesh/models.py`
- Modify: `agentmesh/permissions.py`
- Test: `tests/test_blackboard_authorization.py`

**Interfaces:**
- Produces: `authorize_post_action(post, action, context)`
- Produces: separate `AutoBlackboardPostCreateRequest` without status/reviewer fields

- [ ] **Step 1: Write failing mutation tests**

Cover hidden-post lock/reply denial, unlock by non-owner, arbitrary actor rejection, ordinary review/drain denial, duplicate lock conflict and authorized handoff.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/python -m pytest tests/test_blackboard_authorization.py -v
```

- [ ] **Step 3: Centralize post authorization**

Every lock/unlock/handoff/read/reply/memory-candidate/dispatch command calls one visibility and capability policy. Use atomic compare-and-set for lock acquisition/release.

- [ ] **Step 4: Separate request DTO from persistence model**

Server sets actor, queued status, reviewed fields, task and tenant. Review/drain require explicit governance capability.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/python -m pytest tests/test_blackboard_authorization.py tests/test_chat_flow.py -k "blackboard or handoff or lock" -v
.venv/bin/ruff check agentmesh/blackboard_policy.py agentmesh/routes/blackboard.py
git add agentmesh/blackboard_policy.py agentmesh/routes/blackboard.py agentmesh/models.py agentmesh/permissions.py tests/test_blackboard_authorization.py
git commit -m "Authorize blackboard commands"
```

### Task 8: Fix OAuth, Market, and Connector Boundaries

**Files:**
- Modify: `agentmesh/routes/auth.py`
- Modify: `agentmesh/routes/market.py`
- Modify: `agentmesh/routes/data_sources.py`
- Modify: `agentmesh/datasources.py`
- Modify: `agentmesh/tools.py`
- Test: `tests/test_oauth_lifecycle.py`
- Test: `tests/test_market_authorization.py`
- Test: `tests/test_datasource_authorization.py`

**Interfaces:**
- Produces: local OAuth account state not overwritten by profile
- Produces: `authorize_connector_query(context, connector, operation)`

- [ ] **Step 1: Write failing tests**

Cover disabled OAuth user remains disabled, profile cannot promote to admin, anonymous market board returns 401, cross-workspace market filtering, and user without AgentToolGrant cannot query privileged connector.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/python -m pytest tests/test_oauth_lifecycle.py tests/test_market_authorization.py tests/test_datasource_authorization.py -v
```

- [ ] **Step 3: Preserve local account administration**

OAuth updates display identity only. Role comes from trusted group mapping; disabled remains disabled.

- [ ] **Step 4: Split market health from board data**

If anonymous health is required, expose only non-sensitive health counters. Board requires auth and tenant filtering. Connector route validates Agent grant, operation allowlist and data domain.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/python -m pytest tests/test_oauth.py tests/test_oauth_lifecycle.py tests/test_market_authorization.py tests/test_datasource_authorization.py -v
.venv/bin/ruff check agentmesh/routes/auth.py agentmesh/routes/market.py agentmesh/routes/data_sources.py
git add agentmesh/routes/auth.py agentmesh/routes/market.py agentmesh/routes/data_sources.py agentmesh/datasources.py agentmesh/tools.py tests/test_oauth_lifecycle.py tests/test_market_authorization.py tests/test_datasource_authorization.py
git commit -m "Secure OAuth market and connectors"
```

---

## Phase B: Availability and Data Consistency

### Task 9: Move Embedding Outside SQLite Transactions

**Files:**
- Create: `agentmesh/vector_index.py`
- Modify: `agentmesh/store.py:255-354`
- Modify: `agentmesh/embedding.py`
- Test: `tests/test_vector_index_lifecycle.py`
- Test: `tests/test_sqlite_concurrency.py`

**Interfaces:**
- Produces: `EmbeddingIndexService.index_record(record_ref, text)`
- Produces: vector states `missing | pending | ready | stale | failed`

- [ ] **Step 1: Write failing concurrency and stale-vector tests**

Use a blocked fake embedding client. Assert a second non-vector write completes while embedding is blocked. Update text with embedding failure and assert old vector cannot rank the new record.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/python -m pytest tests/test_vector_index_lifecycle.py tests/test_sqlite_concurrency.py -v
```

- [ ] **Step 3: Refactor write sequence**

Compute embedding before opening a write transaction, or persist record/FTS with vector state pending and process asynchronously. Never hold SQLite write lock during network or CPU-heavy vector work.

- [ ] **Step 4: Add batch and circuit breaker**

`embed_texts()` uses provider batch when supported, bounded concurrency otherwise. Health exposes enabled/configured/state/last_error without secrets.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/python -m pytest tests/test_vector_index_lifecycle.py tests/test_sqlite_concurrency.py tests/test_vector_search.py -v
.venv/bin/ruff check agentmesh/vector_index.py agentmesh/store.py agentmesh/embedding.py
git add agentmesh/vector_index.py agentmesh/store.py agentmesh/embedding.py tests/test_vector_index_lifecycle.py tests/test_sqlite_concurrency.py
git commit -m "Decouple vector indexing from writes"
```

### Task 10: Make Document Ingestion Recoverable

**Files:**
- Create: `agentmesh/ingestion.py`
- Modify: `agentmesh/models.py`
- Modify: `agentmesh/routes/documents.py`
- Modify: `agentmesh/store.py`
- Test: `tests/test_document_ingestion_recovery.py`

**Interfaces:**
- Produces: `DocumentImportManifest(document_id, version, expected_chunks, completed_chunks, status, error)`
- Produces: idempotent `run_document_import(manifest_id)`

- [ ] **Step 1: Write failure-injection tests**

Fail on chunk N, verify manifest records partial state, retry creates only missing chunks, and update document version invalidates old chunks/vector. Assert unexpected job exceptions end in failed, never running forever.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/python -m pytest tests/test_document_ingestion_recovery.py -v
```

- [ ] **Step 3: Implement versioned manifest**

Use exact document URI parsing, deterministic chunk IDs from document version/index, and expected chunk count. `already_imported` requires complete current version, not any matching chunk.

- [ ] **Step 4: Make job terminal states exhaustive**

Use try/except/finally to persist completed/failed. Store error class and retryability. Do not persist secrets or document body in errors.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/python -m pytest tests/test_document_ingestion_recovery.py tests/test_documents.py tests/test_cold_start_import.py -v
.venv/bin/ruff check agentmesh/ingestion.py agentmesh/routes/documents.py
git add agentmesh/ingestion.py agentmesh/models.py agentmesh/routes/documents.py agentmesh/store.py tests/test_document_ingestion_recovery.py
git commit -m "Make document ingestion recoverable"
```

### Task 11: Isolate and Lease Background Workers

**Files:**
- Create: `agentmesh/worker_runtime.py`
- Modify: `agentmesh/app.py`
- Modify: `agentmesh/marketplace.py`
- Modify: `agentmesh/routes/blackboard.py`
- Modify: `agentmesh/routes/memory.py`
- Test: `tests/test_worker_lifecycle.py`

**Interfaces:**
- Produces: `WorkerLease(name, owner_id, expires_at)`
- Produces: `run_sync_step(name, fn)` using bounded thread execution

- [ ] **Step 1: Write lifecycle tests**

Cover start/stop/cancel, step exception recovery, two app instances competing for one lease, lease expiry, and event-loop responsiveness while sync work blocks.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/python -m pytest tests/test_worker_lifecycle.py -v
```

- [ ] **Step 3: Move sync work off event loop**

Use `asyncio.to_thread` with bounded concurrency or separate worker process. Do not call blocking LLM/O2/SQLite operations directly in async loop.

- [ ] **Step 4: Add singleton lease and persisted state**

Only lease owner executes. Persist last start/run/success/error and processed counts. Manual drain uses the same authorization and worker service.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/python -m pytest tests/test_worker_lifecycle.py tests/test_marketplace_scout.py tests/test_marketplace_signal.py -v
.venv/bin/ruff check agentmesh/worker_runtime.py agentmesh/marketplace.py
git add agentmesh/worker_runtime.py agentmesh/app.py agentmesh/marketplace.py agentmesh/routes/blackboard.py agentmesh/routes/memory.py tests/test_worker_lifecycle.py
git commit -m "Isolate background workers"
```

### Task 12: Batch Search Hydration and Version Indexes

**Files:**
- Modify: `agentmesh/store.py:885-1205`
- Create: `tests/test_search_query_budget.py`
- Create: `tests/test_index_integrity.py`

**Interfaces:**
- Produces: `get_many(collection, ids) -> dict[str, BaseModel]`
- Produces: persisted index version and key-set reconciliation

- [ ] **Step 1: Write query-count and integrity tests**

Instrument SQLite connection/query count. Assert 200 candidates use bounded collection queries, not one `_get` each. Seed equal-count but mismatched FTS keys and assert reconciliation repairs them.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/python -m pytest tests/test_search_query_budget.py tests/test_index_integrity.py -v
```

- [ ] **Step 3: Batch candidate hydration**

Group rows by collection, fetch payloads using `WHERE id IN (...)`, deserialize once, preserve RRF order. Move `_ensure_schema` out of `_connect()` hot path.

- [ ] **Step 4: Replace count-only backfill check**

Use schema/index version plus missing/extra key reconciliation. Keep full rebuild as explicit maintenance operation for small databases.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/python -m pytest tests/test_search_query_budget.py tests/test_index_integrity.py tests/test_search_fts.py tests/test_vector_search.py -v
.venv/bin/ruff check agentmesh/store.py tests/test_search_query_budget.py tests/test_index_integrity.py
git add agentmesh/store.py tests/test_search_query_budget.py tests/test_index_integrity.py
git commit -m "Batch search hydration and repair indexes"
```

---

## Phase C: React Complete Replacement

### Task 13: Add Typed API, Query, and Auth Foundation

**Files:**
- Modify: `agentmesh-demo/package.json`
- Modify: `agentmesh-demo/vite.config.ts`
- Create: `agentmesh-demo/scripts/export_openapi.py`
- Create: `agentmesh-demo/src/api/client.ts`
- Create: `agentmesh-demo/src/api/generated/schema.ts`
- Create: `agentmesh-demo/src/app/queryClient.ts`
- Create: `agentmesh-demo/src/features/auth/`
- Create: `agentmesh-demo/e2e/auth.spec.ts`

**Interfaces:**
- Produces: `ApiError`, `apiRequest<T>()`, `AuthProvider`, `useAuth()`

- [ ] **Step 1: Add dependencies and scripts**

Add TanStack Query, OpenAPI TypeScript, Playwright and Vitest. Scripts: `api:types`, `test`, `test:e2e`, `build`.

- [ ] **Step 2: Write failing auth browser tests**

Cover login, reload, logout, 401 signed-out, 403 signed-in, session revocation and cache clear.

- [ ] **Step 3: Implement API and auth foundation**

Use relative `/api`, same-origin cookies and generated types. FormData must not receive JSON content type. Global 401 atomically clears auth state and Query cache.

- [ ] **Step 4: Verify**

```bash
cd agentmesh-demo
npm run api:types
npm run test
npm run build
npm run test:e2e -- e2e/auth.spec.ts
```

- [ ] **Step 5: Commit**

```bash
git add agentmesh-demo/package.json agentmesh-demo/package-lock.json agentmesh-demo/vite.config.ts agentmesh-demo/scripts agentmesh-demo/src/api agentmesh-demo/src/app agentmesh-demo/src/features/auth agentmesh-demo/e2e/auth.spec.ts
git commit -m "Add typed React auth foundation"
```

### Task 14: Serve the React Shell Without Breaking the Legacy Rollback

**Files:**
- Modify: `agentmesh/app.py`
- Modify: `agentmesh-demo/src/App.tsx`
- Modify: `agentmesh-demo/src/components/layout/`
- Create: `tests/test_frontend_routes.py`
- Create: `agentmesh-demo/e2e/shell.spec.ts`

**Interfaces:**
- Consumes: Task 13 auth foundation
- Produces: React route hosting and `/legacy/app.html` rollback route

- [ ] **Step 1: Write route and responsive tests**

Assert React paths return index, `/api/unknown` remains JSON 404, assets resolve, legacy route remains available, and 390/768/1512 widths have no overflow.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/python -m pytest tests/test_frontend_routes.py -v
cd agentmesh-demo && npm run test:e2e -- e2e/shell.spec.ts
```

- [ ] **Step 3: Mount dist and explicit SPA paths**

Mount `/assets`; add explicit route fallback for product routes only. Do not add catch-all before `/api`. Keep old UI under `/legacy/app.html` until Task 19.

- [ ] **Step 4: Verify accessibility**

Test Drawer/Modal focus trap, focus return, Tabs keyboard behavior, reduced motion and mobile navigation.

- [ ] **Step 5: Commit**

```bash
git add agentmesh/app.py tests/test_frontend_routes.py agentmesh-demo/src/App.tsx agentmesh-demo/src/components/layout agentmesh-demo/e2e/shell.spec.ts
git commit -m "Serve authenticated React shell"
```

### Task 15: Connect Workspace to Threads, Chat, Skills, Documents, and Search

**Files:**
- Create: `agentmesh-demo/src/features/workspace/`
- Modify: `agentmesh-demo/src/pages/Workspace.tsx`
- Modify: `agentmesh-demo/src/components/workspace/`
- Create: `agentmesh-demo/e2e/workspace.spec.ts`

**Interfaces:**
- Consumes: `/api/chat/threads`, `/api/chat/messages`, `/api/chat/skills`, `/api/documents`, `/api/search`

- [ ] **Step 1: Write failing browser flow**

Create thread, send private message, run explicit Skill, reload, upload document, observe parse status, search owned resource, and verify request failure keeps retryable draft.

- [ ] **Step 2: Replace mock conversation data**

Use server thread IDs and generated types. Pending messages are UI-only; server response replaces them. Errors never display success Toast.

- [ ] **Step 3: Connect resources and detail panel**

Reference, process, Brief and document details load by stable server IDs. Search results preserve sources and visibility.

- [ ] **Step 4: Verify**

```bash
cd agentmesh-demo && npm run test && npm run build && npm run test:e2e -- e2e/workspace.spec.ts
.venv/bin/python -m pytest tests/test_multiturn.py tests/test_documents.py tests/test_search_fts.py -v
```

- [ ] **Step 5: Commit**

```bash
git add agentmesh-demo/src/features/workspace agentmesh-demo/src/pages/Workspace.tsx agentmesh-demo/src/components/workspace agentmesh-demo/e2e/workspace.spec.ts
git commit -m "Connect React workspace"
```

### Task 16: Connect Knowledge and Governance

**Files:**
- Create: `agentmesh-demo/src/features/knowledge/`
- Modify: `agentmesh-demo/src/pages/Knowledge.tsx`
- Modify: `agentmesh-demo/src/components/knowledge/`
- Create: `agentmesh-demo/e2e/knowledge.spec.ts`

**Interfaces:**
- Consumes: Inbox allowed actions, Memory allowed actions, Document actions

- [ ] **Step 1: Write governance browser tests**

Cover confirm Brief, self-only vs shared scope, snooze/resolve, injection release/discard, team acceptance, conflict 409 and unauthorized actions hidden.

- [ ] **Step 2: Remove DemoContext business state**

标签页和计数由服务端资源驱动。“仅自己”不会进入共享列表。忽略、延后和确认操作必须等待服务端最终结果。

- [ ] **Step 3: Render server allowed actions**

No client role branching or local state machine. Mutation invalidates Inbox, Memory, documents, bootstrap metrics and relevant task data.

- [ ] **Step 4: Verify**

```bash
cd agentmesh-demo && npm run test && npm run build && npm run test:e2e -- e2e/knowledge.spec.ts
.venv/bin/python -m pytest tests/test_memory_governance.py tests/test_chat_flow.py -k "inbox or memory or brief" -v
```

- [ ] **Step 5: Commit**

```bash
git add agentmesh-demo/src/features/knowledge agentmesh-demo/src/pages/Knowledge.tsx agentmesh-demo/src/components/knowledge agentmesh-demo/e2e/knowledge.spec.ts
git commit -m "Connect knowledge governance"
```

### Task 17: Connect Collaboration, Blackboard, and Market

**Files:**
- Create: `agentmesh-demo/src/features/collaboration/`
- Modify: `agentmesh-demo/src/pages/Collaboration.tsx`
- Modify: `agentmesh-demo/src/components/collaboration/`
- Create: `agentmesh-demo/e2e/collaboration.spec.ts`

**Interfaces:**
- Consumes: task cards/detail, Blackboard allowed actions, authenticated market APIs

- [ ] **Step 1: Write browser flow**

View task, lock, reply, handoff, unlock, mark read, create candidate, participate in market and verify unauthorized action hidden.

- [ ] **Step 2: Replace mock cards and local Sets**

All status/counts/authorization come from server. Market polling runs only while page/tab visible and shows worker errors separately.

- [ ] **Step 3: Connect mutations with exact invalidation**

Refresh task detail/cards, Inbox, Memory and Audit after relevant commands.

- [ ] **Step 4: Verify**

```bash
cd agentmesh-demo && npm run test && npm run build && npm run test:e2e -- e2e/collaboration.spec.ts
.venv/bin/python -m pytest tests/test_blackboard_authorization.py tests/test_market_authorization.py -v
```

- [ ] **Step 5: Commit**

```bash
git add agentmesh-demo/src/features/collaboration agentmesh-demo/src/pages/Collaboration.tsx agentmesh-demo/src/components/collaboration agentmesh-demo/e2e/collaboration.spec.ts
git commit -m "Connect collaboration network"
```

### Task 18: Connect Digital Self, Insights, Settings, and Admin

**Files:**
- Create: `agentmesh-demo/src/features/digital-self/`
- Create: `agentmesh-demo/src/features/insights/`
- Create: `agentmesh-demo/src/features/admin/`
- Modify: corresponding pages/components
- Create: `agentmesh-demo/e2e/profile-insights-admin.spec.ts`

**Interfaces:**
- Consumes: bootstrap, profile APIs from Task 22 if available, audit/activity/memory/task APIs, admin capability APIs

- [ ] **Step 1: Write capability-gated browser tests**

Regular user denied admin; Team Lead sees public Agent/team memory actions; Admin manages users/workspaces/policies/O2. Period changes alter server query results. Understanding edits collect real text before success.

- [ ] **Step 2: Replace static metrics and controls**

Online status, counts, profile, activities and audit come from APIs. No button remains without handler.

- [ ] **Step 3: Use capability-specific routes**

Do not gate all admin pages with `manage_users`. Separate manage_public_agent, manage_workspaces, manage_risk_policies, sync_o2 and team membership.

- [ ] **Step 4: Verify**

```bash
cd agentmesh-demo && npm run test && npm run build && npm run test:e2e -- e2e/profile-insights-admin.spec.ts
.venv/bin/python -m pytest tests/test_permissions.py tests/test_o2.py tests/test_health.py -v
```

- [ ] **Step 5: Commit**

```bash
git add agentmesh-demo/src/features agentmesh-demo/src/pages agentmesh-demo/src/components/layout agentmesh-demo/src/components/digital-self agentmesh-demo/src/components/insights agentmesh-demo/e2e/profile-insights-admin.spec.ts
git commit -m "Connect profile insights and admin"
```

### Task 19: Cut Over and Remove Production Mock State

**Files:**
- Modify: `agentmesh/app.py`
- Modify: `README.md`
- Delete: root `app.html` after rollback period
- Delete: `agentmesh-demo/src/data/mockData.ts`
- Delete: `agentmesh-demo/src/store/DemoContext.tsx`
- Create: `agentmesh-demo/e2e/parity.spec.ts`

**Interfaces:**
- Consumes: Tasks 13-18
- Produces: React as only production frontend

- [ ] **Step 1: Add parity test before deletion**

Cover every old user/admin operation, root/deep-link reload, JSON API 404, mobile/desktop, and absence of local demo strings.

- [ ] **Step 2: Run parity with legacy still available**

Compare API mutations and persistent results, not screenshot similarity alone.

- [ ] **Step 3: Switch root and remove mocks**

React index becomes `/`; legacy route remains for one release only if explicitly required. Remove handler-less components and all mock imports.

- [ ] **Step 4: Verify clean cutover**

```bash
cd agentmesh-demo
npm run api:types
npm run test
npm run build
npm run test:e2e
cd ..
.venv/bin/python -m pytest
.venv/bin/ruff check .
```

- [ ] **Step 5: Commit**

```bash
git add -A app.html agentmesh/app.py agentmesh-demo README.md
git commit -m "Cut over to the React frontend"
```

---

## Phase D: Product Capability Closure

### Task 20: Make Citations Structured and Retrieval Tiers Real

**Files:**
- Modify: `agentmesh/models.py`
- Modify: `agentmesh/synthesis.py`
- Modify: `agentmesh/agents.py:318-326,503-578`
- Modify: `agentmesh/store.py`
- Test: `tests/test_structured_citations.py`
- Test: `tests/test_layered_retrieval.py`

**Interfaces:**
- Produces: `SynthesisResult.cited_source_ids`
- Produces: explicit tier predicate using MemoryLayer and Scope

- [ ] **Step 1: Write citation and tier tests**

Assert model output maps stable `[S1]` tokens to IDs, no fuzzy title matching, and long/mid/short rules select actual `MemoryLayer` rather than comments only.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/python -m pytest tests/test_structured_citations.py tests/test_layered_retrieval.py -v
```

- [ ] **Step 3: Implement structured citation contract**

Prompt assigns stable tokens; parser validates tokens against returned sources. Retrieval metrics consume canonical IDs.

- [ ] **Step 4: Define real tier semantics**

Use explicit layer/scope predicates and preserve early exit/budget behavior. Cache query embedding per request.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/python -m pytest tests/test_structured_citations.py tests/test_layered_retrieval.py tests/test_retrieval_metrics.py -v
git add agentmesh/models.py agentmesh/synthesis.py agentmesh/agents.py agentmesh/store.py tests/test_structured_citations.py tests/test_layered_retrieval.py
git commit -m "Add structured citations and retrieval tiers"
```

### Task 21: Define and Execute LearnedSkill Safely

**Files:**
- Create: `agentmesh/learned_skill_runtime.py`
- Modify: `agentmesh/skill_extractor.py`
- Modify: `agentmesh/agents.py`
- Modify: `agentmesh/routes/memory.py`
- Test: `tests/test_learned_skill_runtime.py`

**Interfaces:**
- Produces: `SkillMatch(skill_id, score, scope, version)`
- Produces: `execute_learned_skill(match, request, context) -> WorkflowPlan`

- [ ] **Step 1: Specify execution rules in tests**

Static `$` Skill wins over LearnedSkill. Only ACTIVE skills in authorized scope match. Match creates audited WorkflowPlan; it does not execute arbitrary text as code/tool.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/python -m pytest tests/test_learned_skill_runtime.py -v
```

- [ ] **Step 3: Implement matcher integration and safe plan executor**

LearnedSkill steps map to allowlisted workflow actions. Validation rules are enforced. Unknown actions fail closed.

- [ ] **Step 4: Add observability and versioning**

Record match score, skill version, chosen workflow and fallback reason. User can disable/deprecate and immediately stop matching.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/python -m pytest tests/test_learned_skill_runtime.py tests/test_skills_extraction.py -v
.venv/bin/ruff check agentmesh/learned_skill_runtime.py agentmesh/skill_extractor.py
git add agentmesh/learned_skill_runtime.py agentmesh/skill_extractor.py agentmesh/agents.py agentmesh/routes/memory.py tests/test_learned_skill_runtime.py
git commit -m "Execute learned skills safely"
```

### Task 22: Persist Delegated Answers, Adoption, and Lineage

**Files:**
- Modify: `agentmesh/models.py`
- Modify: `agentmesh/store.py`
- Create: `agentmesh/routes/collaboration.py`
- Modify: `agentmesh/app.py`
- Modify: `agentmesh/agents.py`
- Test: `tests/test_collaboration_api.py`

**Interfaces:**
- Produces: persisted DelegatedAnswerRecord with request/decision/answer/adoption state
- Produces: lineage query for MemoryRelation

- [ ] **Step 1: Write contract tests**

Cover consent, high-sensitivity confirmation, deny, answer-only payload, idempotent adoption, one shadow point, one lineage edge, cross-user isolation and no raw memory body leakage.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/python -m pytest tests/test_collaboration_api.py -v
```

- [ ] **Step 3: Persist lifecycle and expose routes**

Use stable record IDs. Reuse existing answer synthesis. Adoption returns existing result on retry and never double-awards.

- [ ] **Step 4: Add lineage API and React consumer**

Expose source lineage as read-only projection. Do not expose raw target memory bodies.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/python -m pytest tests/test_collaboration_api.py tests/test_delegated_answer.py -v
.venv/bin/ruff check agentmesh/routes/collaboration.py agentmesh/agents.py
git add agentmesh/models.py agentmesh/store.py agentmesh/routes/collaboration.py agentmesh/app.py agentmesh/agents.py tests/test_collaboration_api.py
git commit -m "Persist delegated collaboration"
```

---

## Phase E: Engineering and Release

### Task 23: Fix Repository Hygiene, Dependencies, and Reality Docs

**Files:**
- Modify: `.gitignore`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `CONTEXT.md`
- Modify: `docs/adr/0001-retrieval-vector-search.md`

- [ ] **Step 1: Ignore generated frontend artifacts**

Add `node_modules/`, `dist/`, `.vite/`, `*.tsbuildinfo` and Playwright artifacts. Do not delete user files without explicit approval.

- [ ] **Step 2: Fix dependency declaration**

Declare PyMuPDF in the correct optional/runtime dependency group or remove the unconditional README promise. Verify in a clean isolated venv.

- [ ] **Step 3: Reconcile docs with code**

Document React version, current serving route, Query stack, embedding default, worker default, capability status and mock provider limits.

- [ ] **Step 4: Run clean install smoke**

```bash
python3 -m venv /tmp/agentmesh-clean-venv
/tmp/agentmesh-clean-venv/bin/pip install -e '.[dev]'
AGENTMESH_EMBEDDING_ENABLED=false /tmp/agentmesh-clean-venv/bin/python -m pytest tests/test_pdf.py -q
```

- [ ] **Step 5: Commit**

```bash
git add .gitignore pyproject.toml README.md CONTEXT.md docs/adr/0001-retrieval-vector-search.md
git commit -m "Align repository configuration and docs"
```

### Task 24: Add CI, Frontend Tests, Coverage, and Clean Ruff

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `pyproject.toml`
- Modify: `agentmesh-demo/package.json`
- Modify: Ruff-reported files and tests

**Interfaces:**
- Produces: mandatory backend, frontend, E2E and secret-scan gates

- [ ] **Step 1: Fix current 23 Ruff findings**

No blanket ignores. Use `strict=` for vector zip; keep behavior unchanged.

- [ ] **Step 2: Add CI jobs**

Backend job: clean install, Ruff, pytest with coverage and embeddings disabled. Frontend job: npm ci, API types, unit tests, build. E2E job: isolated SQLite, backend, Vite/production serving, Playwright. Security job: secret scan and dependency audit.

- [ ] **Step 3: Add coverage thresholds**

Start with a measured baseline, then require no regression. Security boundary modules require branch coverage for denial paths.

- [ ] **Step 4: Verify locally**

```bash
AGENTMESH_EMBEDDING_ENABLED=false .venv/bin/python -m pytest --cov=agentmesh --cov-report=term-missing
.venv/bin/ruff check .
cd agentmesh-demo && npm ci && npm run api:types && npm run test && npm run build && npm run test:e2e
```

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml pyproject.toml agentmesh-demo/package.json agentmesh-demo/package-lock.json agentmesh tests
git commit -m "Add complete CI release gates"
```

### Task 25: Benchmark Retrieval and Run the Final Release Gate

**Files:**
- Create: `eval/retrieval_benchmark.py`
- Create: `eval/fixtures/retrieval-1k.jsonl`
- Create: `eval/fixtures/retrieval-5k.jsonl`
- Modify: `docs/project-audit-report.md`
- Modify: release docs

**Interfaces:**
- Consumes: all prior tasks
- Produces: measured vector decision and release evidence

- [ ] **Step 1: Build deterministic 1k/5k benchmarks**

Measure lexical, exact vector and hybrid p50/p95, memory, candidate counts, citation accuracy and tenant-filter cost. No real provider calls.

- [ ] **Step 2: Decide vector implementation from evidence**

Reopen ADR only if approximately 5000 chunks, citation coverage below 75% with relevant sources, or user latency/ranking complaints justify it. Do not claim ANN complexity without measuring the selected implementation.

- [ ] **Step 3: Run complete release gate**

```bash
AGENTMESH_EMBEDDING_ENABLED=false .venv/bin/python -m pytest
.venv/bin/ruff check .
cd agentmesh-demo
npm run api:types
npm run test
npm run build
npm run test:e2e
```

- [ ] **Step 4: Run production smoke**

Build React, start FastAPI with isolated production-like SQLite and safe env, log in as each role, exercise chat/upload/governance/collaboration/admin, restart and verify persistence. Confirm no default admin exists unless demo mode explicitly enabled.

- [ ] **Step 5: Update evidence and commit**

Record exact commands, commit hash, result counts, benchmark data and remaining accepted risks. Remove stale audit claims that have been fixed.

```bash
git add eval docs README.md CONTEXT.md
git commit -m "Complete AgentMesh remediation gate"
```

## Program Completion Criteria

- No tracked secrets or fixed production credentials.
- Owner/tenant/project/capability checks cover every object read and write.
- PRIVATE chat, document and memory cannot cross user boundaries.
- Memory and Blackboard state changes are explicit, authorized and audited.
- Embedding and document processing do not block SQLite write transactions or FastAPI event loop.
- Document ingestion is versioned, idempotent, resumable and observable.
- React is the production frontend and contains no local business mock state.
- LearnedSkill and delegated collaboration are either fully reachable or explicitly removed from product claims.
- Backend tests, Ruff, frontend tests, build, E2E, coverage and secret scan pass in CI.
- README, CONTEXT, ADRs and current implementation agree.
