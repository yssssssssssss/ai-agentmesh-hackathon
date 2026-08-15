# AgentMesh 项目审计报告

> 更新日期：2026-08-13  
> 审计基线：`bbbc882423eef0451711dbea0d6df9d9907fa2ff`  
> 审计对象：当前根工作区，包括未提交修改  
> 审计范围：后端、旧前端、新 React 前端、测试、检索与向量链路、认证与权限、文档导入、后台 Worker、CI 与文档一致性

## 1. 结论摘要

Claude 原报告抓住了 LearnedSkill、检索 N+1、向量全表扫描、串行 embedding 和 SQLite 长事务等真实问题，但不能视为完整项目审计。

主要原因：

1. 报告声称覆盖“全量源码”，实际只统计和分析了 `agentmesh/**/*.py`，遗漏生产中的 6801 行旧前端、5428 行 React demo、`eval/`、CI、前端测试和仓库卫生。
2. 报告把功能闭环缺口、错误度量、规模优化和当前可达安全漏洞放在同一优先级中，导致 `match_skill()` 被列为 P0，而默认管理员凭据、跨用户私聊 IDOR、文档横向读取和 Blackboard 越权完全未出现。
3. 部分结论使用了不严谨的绝对表述，例如“引用率恒为 0”“MemoryRelation 永远不读取”“无连接池导致 database is locked”。
4. 部分优化方案缺少基准或会制造新错误，例如用 title/summary 模糊匹配修复 citation、立即引入 ANN、使用连接池解决 SQLite 单写者问题。

更新后的整体判断：

| 维度 | 评分 | 结论 |
| --- | ---: | --- |
| 功能完整性 | 4.0 / 10 | 后端能力丰富，但 LearnedSkill、delegated adoption 和新 React 前端没有形成端到端闭环 |
| 安全与租户隔离 | 2.5 / 10 | 存在默认凭据、跨用户会话、文档、搜索、Memory 和 Blackboard 越权 |
| 架构与可维护性 | 5.0 / 10 | 有清晰模型和路由拆分，但 seed 常量、巨型 Agent/Store 和双前端造成高耦合 |
| 性能与可用性 | 4.5 / 10 | 默认同步 embedding 在 SQLite 写事务内执行，是当前最直接的可用性风险 |
| 工程化 | 5.0 / 10 | 373 个后端测试通过，但 Ruff 失败、无 CI、无前端测试、依赖声明不完整 |
| 综合 | **4.2 / 10** | 可作为单机原型演示，不适合直接部署为多用户、多 Workspace 产品 |

## 2. 当前项目规模

统计口径必须分开，不能把不同目录混为“全量源码”。

| 范围 | 当前数值 | 说明 |
| --- | ---: | --- |
| `agentmesh/**/*.py` | 44 文件，11,510 行 | 原报告这一项准确 |
| `app.html` | 1 文件，6,801 行 | 当前 FastAPI 生产入口仍在服务 |
| `agentmesh-demo/src` | 47 文件，5,428 行 | React 18 demo，原报告完全遗漏 |
| `eval/` | 3 文件，514 行 | 原报告遗漏 |
| `tests/test_*.py` | 28 文件，7,833 行 | 不含 `conftest.py` |
| `tests/conftest.py` | 1 文件，36 行 | 合计测试目录 29 文件、7,869 行 |
| pytest 收集并执行 | 373 个测试 | 原报告写 372，少 1 个 |
| `/api` 操作 | 107 个 | 另有 `/` 和 `/app.html` 两个页面操作，共 109 个路由装饰器 |
| 后台 Worker | 5 个 | 全部接入 lifespan，但默认关闭 |

原报告附录还少算了部分路由：

- Blackboard 当前 17 个操作，不是 16 个。
- Memory 当前 18 个操作，不是 17 个。
- Workspace 当前 10 个操作，不是 9 个。

## 3. 对 Claude 原报告逐条校正

### 3.1 功能未接通与半接通

| 原编号 | 结论 | 复核结果 |
| --- | --- | --- |
| 1 | `match_skill()` 无生产 caller | **确认**。仅测试调用，LearnedSkill 激活后也不参与聊天路由。但静态 `$` ChatSkill 正常，不能说所有 Skill 失效。LearnedSkill 目前只有描述性 steps，没有执行器，不能在 0.5 天内靠加一个 caller 完成闭环。 |
| 2 | MemoryRelation 写后不读 | **部分确认**。生产无 API、逻辑或 UI consumer，但 Store property 和测试会读取。它不是纯 dead data，而是只落库未产品化的 lineage 审计数据。 |
| 3 | `adopt_delegated_answer()` 无 HTTP 入口 | **确认**。生产无 caller，只有测试触达。是否列为高优取决于 delegated adoption 是否属于当前交付。 |
| 4 | 通用对话不触发 Skill 提炼 | **部分确认**。GENERAL_CHAT 确实不提炼；但不是“只有 ASK_MEMORY 才提炼”，所有成功记录短期 workflow memory 的显式或分类工作流都会触发。所谓覆盖率 10% 到 80% 没有数据依据。 |
| 5 | 引用率永远为 0 | **方向正确，表述过度**。生产 prompt 不提供 raw source ID，因此指标严重向 0 偏置，但只要输出碰巧包含 ID 就可非 0。应使用结构化 citation token/ID，不应改成 title/summary 模糊匹配。 |
| 6 | Embedding 静默降级 | **部分确认**。已有 warning 日志，因此不算完全静默；但 API/UI 无健康状态，失败前可能等待 30 秒，并且默认开启。更严重的是源码包含默认 API key。 |

### 3.2 性能与存储

| 原编号 | 结论 | 复核结果 |
| --- | --- | --- |
| 7 | Search N+1 | **确认**。最多 200 个候选逐条 `_get()`，每次新连接并重复 schema ensure。它是本地 SQLite O(n) 查询/连接放大，不应描述为网络 `n × RTT`。 |
| 8 | 向量搜索全表扫描 | **确认扫描事实，否定立即 ANN 结论**。复杂度约为 O(V × d + V log V)，d=4096。当前没有 1k/5k 基准，ADR 0001 也要求约 5000 chunks、引用覆盖不足或用户投诉后再重开向量决策。 |
| 9 | 分层检索最多调用 search 三次 | **确认**。只在高层不足时进入下一层。三个 tier 实际按重叠 Scope 过滤，并没有按 `MemoryLayer` 实现 long/mid/short。机械合并为一次查询会改变 RRF、预算和早停语义。 |
| 10 | 大文档串行 embedding | **确认并升级严重度**。10 万字符约 200 个 chunk，每个 chunk 一次同步 HTTP；小于等于 1 MiB 的上传直接在 async 路由内执行，会冻结事件循环。 |
| 11 | `_sync_vec` 持连接执行 HTTP | **确认并升级为正确性/可用性风险**。records/FTS 写事务已经开始，随后最长 30 秒 HTTP，第二个写者可能在默认等待后报 locked。 |
| 12 | Skill 提炼加载全量数据 | **部分确认**。一次提炼确实全量加载并解析 memory/skills；但不是每次聊天，只在成功写入短期 workflow memory 后触发。 |
| 13 | FTS count 不一致即全量重建 | **部分确认**。仅 `fts_count < records_count` 时全删重建。数量相等但 ID 集合不一致，或 FTS 更多时不会修复，既有性能问题，也有完整性盲点。 |
| 16 | 无连接池导致 SQLite locked | **因果错误**。短连接是 SQLite 常见模式，连接池不能解决单写者约束。当前可证明的锁源是写事务中的外部 HTTP。先缩短事务，再依据实测决定 WAL、busy timeout、单写队列或迁移服务数据库。 |

### 3.3 Bug 与 Dead Code

| 原编号 | 结论 | 复核结果 |
| --- | --- | --- |
| 14 | Document ID 子串导致前缀误判 | **低概率潜在问题**。逻辑应改为精确解析，但正常 `doc_<12 hex>` ID 长度固定，不会互为严格前缀。更大的真实问题是文档更新后旧 chunks 和旧 vector 不重建。 |
| 15 | 空文档摘要与零 chunk 矛盾 | **不成立**。摘要记录“文档未解析出正文”，零 chunk 表示没有可检索正文，两者可以同时成立。是否拒绝空文档是产品策略。 |
| Dead 1 | `TaskStatus.SYNTHESIZING` 未使用 | **确认**。当前没有赋值或 consumer。 |
| Dead 2 | `DRAFT/EXPIRED/DEPRECATED` 未使用 | **部分正确**。内部无明确状态流，但通用 PATCH 可直接写入这些值。真正问题是状态可达却没有状态机约束。 |
| Dead 3 | Agent runtime 字段无用 | **错误**。`routes/agents.py` 动态填充，`app.html` 和测试真实消费。问题是领域持久模型与 runtime response DTO 混用，不是 dead code。 |

## 4. P0 安全与数据边界

原报告几乎没有覆盖安全面，以下问题优先级高于 LearnedSkill 和 ANN。

### 4.1 源码硬编码 Embedding API key

严重度：**Critical**

`agentmesh/embedding.py:13-17` 为内部 Embedding URL 配置了源码默认 Bearer key，并默认启用。

风险：

- 凭据进入 Git 历史、日志、构建包和所有开发者机器。
- 任何拿到源码的人都可能调用内部服务。
- 默认启用会让本地启动和测试意外访问内部网关。

处置：

1. 立即轮换或吊销当前 key。
2. 从源码和历史中移除，不在报告中重复 key 内容。
3. 仅从服务端环境变量/Secret Manager 注入。
4. 默认 `EMBEDDING_ENABLED=false`，未配置 key 时 fail closed 或明确 lexical-only。

### 4.2 默认管理员凭据自动创建

严重度：**High**

证据：

- `agentmesh/seed.py:67-81`
- `agentmesh/seed.py:399-419`
- `agentmesh/app.py:63-73`

空库启动或 credential 缺失时会自动创建 `usr_admin` 和公开固定密码。PBKDF2 哈希不改变初始密码已知这一事实。

修复：生产禁用 demo seed；首次管理员使用一次性随机 secret 或 SSO；发现默认凭据时拒绝生产启动。

### 4.3 OAuth 会复活 disabled 用户并覆盖角色

严重度：**High**

`agentmesh/routes/auth.py:209-227` 对已有 OAuth 用户无条件设置 `status="active"`，并用 profile role 覆盖本地 role。

管理员禁用用户、撤销 session 后，用户可再次完成 OAuth callback 获得新 session。

修复：本地 administrative status 与 IdP profile 分离；disabled 用户 callback 返回 403；角色通过服务端 group mapping/allowlist 管理。

### 4.4 Chat thread owner IDOR

严重度：**High**

证据：

- `agentmesh/routes/chat.py:38-40`
- `agentmesh/agents.py:119-145`
- `agentmesh/agents.py:1627-1662`

`POST /api/chat/messages` 接受客户端 thread ID，在授权前读取历史；已有 thread 被直接返回，不比较 `thread.user_id`。攻击者可把受害者私聊放入 LLM 上下文并向该线程写消息和任务。

修复：历史读取前强制 owner/ACL；Store append/history 使用 owner-scoped API；客户端不能抢占任意 thread ID。

### 4.5 Search 泄露其他用户 PRIVATE 聊天

严重度：**High**

`personal` 搜索包含 PRIVATE scope。`store.search()` 对 user memory/document 检查 user ID，但 chat message 分支只核对 workspace/project，不核对 thread owner，直接返回 `msg.content`。

证据：

- `agentmesh/routes/workspace.py:23-27`
- `agentmesh/routes/workspace.py:67-89`
- `agentmesh/store.py:920-943`

修复：PRIVATE chat 强制 `thread.user_id == current_user.id`；workspace/project 不能由普通客户端任意选择；统一 collection authorization predicate。

### 4.6 核心业务固定写入 seed 租户

严重度：**High**

以下路径忽略用户的真实 workspace/project：

- 新聊天：`agentmesh/routes/chat.py:20-28`
- 隐式 thread：`agentmesh/agents.py:1627-1640`
- 文档上传：`agentmesh/routes/documents.py:42-48`
- 数据查询：`agentmesh/routes/data_sources.py:25-36`
- 分层检索：`agentmesh/agents.py:503-537`
- Bootstrap：`agentmesh/seed.py:452-488`

虽然用户模型支持其他 Workspace/Project，业务路径仍写入默认 seed 租户。

修复：建立请求级 `TenantContext`，贯穿 route、agent、store 和 connector；禁止业务代码引用 seed 常量。

### 4.7 文档列表和详情横向泄露

严重度：**High**

`GET /api/documents` 返回所有文档，详情只检查存在性，任意认证用户可读取其他用户上传的正文。

证据：

- `agentmesh/routes/documents.py:143-153`
- `agentmesh/routes/documents.py:156-166` 的 update 已有 owner guard，说明 owner 数据可用

修复：默认 owner-only；项目共享需要显式 scope/ACL；列表和详情复用同一授权 predicate，未授权返回 404。

### 4.8 Memory 创建与状态机绕过

严重度：**High**

`POST /api/memory` 可由普通用户直接提交 `TEAM_ACCEPTED`。PATCH 只拦截提升，允许任意用户把任意共享记忆降为 draft/private/deprecated 等状态。

证据：

- `agentmesh/routes/memory.py:72-89`
- `agentmesh/routes/memory.py:282-299`
- `agentmesh/permissions.py:79-90`

修复：集中 Memory transition service；创建固定为 proposed/candidate；每次 mutation 检查 actor、tenant、from-to transition 和 status/scope invariant。

### 4.9 Blackboard mutation 与审批队列越权

严重度：**High**

任意认证用户可：

- 伪造 actor 发布帖子。
- 提交、review、drain auto-post。
- 对已知 post lock、unlock、handoff、read、reply。

证据：

- `agentmesh/routes/blackboard.py:492-567`
- `agentmesh/routes/blackboard.py:570-690`
- `agentmesh/routes/blackboard.py:694-720`

这些入口没有复用已有 `post_visible_to_user()`，也不验证 lock owner 或 reviewer capability。

### 4.10 数据连接器绕过 Agent grant

严重度：**High，条件触发**

配置 HTTP/O2 connector 后，任意登录用户可选择 connector、operation、parameters，以服务器 API key 或 O2 登录态访问外部数据，并把结果写为 PROJECT evidence。

证据：

- `agentmesh/routes/data_sources.py:20-59`
- `agentmesh/datasources.py:56-120`

Read-only operation allowlist 能阻止写操作，不等于请求者有权读取数据。

修复：connector 映射 ToolDefinition/capability；检查当前用户控制的 AgentToolGrant、租户成员关系和数据域；尽量使用用户委托 token。

### 4.11 Market board 匿名暴露人员和协作关系

严重度：**High**

`/api/market/status` 和 `/api/market/board` 没有认证。文件注释声称只返回非敏感计数，但 board 实际返回：

- 用户 ID 和姓名。
- 能力、可提供、需要。
- helper/needer 关系。
- 匹配状态和时间。

证据：

- `agentmesh/routes/market.py:1-5`
- `agentmesh/routes/market.py:30-98`
- `tests/test_market_status.py:8-33` 还把匿名 200 固化为测试契约

修复：board 必须认证并按组织/Workspace 过滤；如确需公开 status，拆分只含健康计数的匿名端点。

### 4.12 上传内存与解压 DoS

严重度：**High**

`await file.read()` 先把完整文件读入内存，随后才检查 20 MiB。DOCX/PPTX 解析没有展开大小、压缩比、entry 数或 XML 文本上限。

证据：

- `agentmesh/routes/documents.py:27-63`
- `agentmesh/documents.py:145-174`
- `agentmesh/documents.py:220-238`

修复：代理/ASGI 层先限请求体；应用流式读取；限制 ZIP 展开预算、PDF 页数、图片像素和并发配额；解析放入资源受限 worker。

## 5. P0 可用性与数据一致性

### 5.1 Embedding HTTP 在 SQLite 写事务内执行

`SQLiteStore._upsert()` 已写 records/FTS 后调用 `_sync_vec()`；后者在同一连接上下文中发最长 30 秒 HTTP。

证据：

- `agentmesh/store.py:255-301`
- `agentmesh/embedding.py:22-46`

影响：

- 持有写锁等待外部网络。
- 第二个并发写可能在 SQLite 默认等待后报 locked。
- 任意可搜索对象写入都受到外部 embedding 可用性影响。

最小修复：

1. 在事务外计算 embedding。
2. 使用短事务原子写 record、FTS 和 vector，或 record/FTS 先落库后异步重建 vector。
3. 加快速失败、熔断、指标和明确状态。
4. 不要先用连接池掩盖长事务。

### 5.2 文档导入同步串行且会阻塞事件循环

每个文档 chunk 都执行独立 `add_user_memory_item()` 和 embedding。10 万字符按 500 字符切片约 200 个 chunk。

小于等于 1 MiB 的上传在 async 路由内直接执行同步解析、SQLite 和 HTTP，阻塞事件循环；大文件虽返回 202，仍在应用进程 BackgroundTask 串行执行。

最小修复：整条 parse/import 放入有界线程池或独立 worker；优先使用 provider batch embedding 和 bulk DB write；禁止无界并发。

### 5.3 启动期向量 backfill 可拖慢服务启动

全局 `SQLiteStore()` 初始化同步执行 `_backfill_vec()`，每次最多 100 条，每条可能等待 30 秒，理论最坏约 50 分钟。失败条目下次启动继续重试。

这与 ADR 0001“当前 MVP 不引入向量检索，约 5000 chunks 或召回证据触发后再评估”的 Accepted 决策冲突。

修复：默认关闭；迁移为启动后有界、可观测、可暂停的 backfill job；先更新 ADR 或回退实现，不能代码与架构决策长期分叉。

### 5.4 向量失败会保留旧 vector

更新正文时 records 和 FTS 已更新。如果 embedding 返回 None，`_sync_vec()` 直接 return，旧 `records_vec` 不删除。服务恢复后，旧向量仍参与新正文排序。

修复：在语义更新中删除或标记旧向量 stale，并异步重建；搜索不能把 stale vector 与新 payload 组合。

### 5.5 文档导入不是事务性流程

Source、Document、摘要、各 chunk 分别提交。中途 DB 或网络失败会留下部分导入。手动 import 只要发现任意 chunk 就返回 `already_imported`，无法补齐缺失 chunk。后台 job 只捕 parser/Unicode 异常，其他异常可能让 job 永久停留 running。

修复：持久化 import manifest/version/expected chunk count；支持 resume/rebuild；job 在 finally 中进入明确终态并记录错误。

## 6. 新 React 前端与生产入口

这是原报告最大的遗漏。

### 6.1 当前生产仍服务旧 `app.html`

`agentmesh/app.py:91-103` 将 `/` 和 `/app.html` 指向根目录 `app.html`，只挂载可选 `static/`。FastAPI 没有托管 `agentmesh-demo/dist` 或 `/assets`。

当前真正生产可达的是 6801 行旧前端，而不是 React demo。

### 6.2 React demo 完全使用本地 mock

证据：

- `agentmesh-demo/src/main.tsx:1-16` 只挂 `DemoProvider`。
- `agentmesh-demo/src/store/DemoContext.tsx` 保存所有业务状态。
- `agentmesh-demo/src/data/mockData.ts` 提供所有领域数据。
- 全部 React src 中没有 fetch、API client、TanStack Query 或认证层。
- `package.json` 使用 React 18.3.1，不是 CONTEXT 声称的 React 19，也没有 TanStack Query。

页面级缺口：

| 页面 | 当前行为 | 未接通 |
| --- | --- | --- |
| Workspace | 清空输入，等待 1.4 秒，toast“已补充回答” | chat、threads、upload、Skill、search、错误处理 |
| Knowledge | 修改 DemoContext 计数和本地卡片 | Inbox、Memory、确认、忽略、共享范围、刷新持久化 |
| Collaboration | 本地 Set 授权/拒绝，toast 发起协作 | delegated answer、consent、adoption、Blackboard/Market |
| Insights | 本地 step 和 setTimeout 生成候选 | project review、candidate、与 Knowledge 共享同一 ID |
| Digital Self | 静态 mock 与本地理解状态 | profile、understanding、impact、preferences |
| Settings | 多个后台入口无 handler | users、agents、policies、O2、audit |

具体错误：

- Workspace 输入被丢弃：`agentmesh-demo/src/components/workspace/Composer.tsx:12-21`。
- 上传、Skill、邀请仅 toast：`Composer.tsx:49-63`。
- “仅自己”仍设置 `knowledgeShared=true`，随后进入已共享列表：`DemoContext.tsx:115-135`、`Knowledge.tsx:42,101-108`。
- 忽略只 toast，不移出队列：`PendingKnowledgeCard.tsx:103-108`。
- Collaboration 授权/拒绝仅本地：`Collaboration.tsx:44-58`。
- Project Review 丢弃 resultText，只切本地状态：`ProjectReviewDrawer.tsx:83-96`。

## 7. 功能闭环缺口

### 7.1 LearnedSkill 学了不会用

`match_skill()` 只有测试 caller。LearnedSkill 可以提炼、保存、激活、分享、废弃，但聊天路由只使用静态 ChatSkill 和 LLM intent。

不能简单在入口插入 `match_skill()`：LearnedSkill 只有描述性 steps/validation，没有执行器。接入前必须定义：

- 命中后如何执行或注入。
- 与静态 `$` Skill 的优先级。
- Personal/Project/Team scope 权限。
- 审计、版本和失败回退。

因此它是 P1/P2 产品能力缺口，不应压过安全和全局可用性。

### 7.2 Delegated adoption 无生产入口

`adopt_delegated_answer()` 只被测试调用。市场会触发 `answer_for_peer()`，但没有采纳、幂等贡献结算和 lineage 查询的 HTTP/worker 入口。

如果该能力属于当前产品承诺，需要：

- 持久化 delegated answer record。
- 请求/决策/回答/采纳 API。
- 幂等 adoption。
- Contribution 和 lineage 查询投影。
- React 协作流程。

### 7.3 MemoryRelation 只落库不消费

当前两条写路径：个人分享到项目、delegated adoption。生产没有查询 API、业务 consumer 或 UI。

应根据产品目标二选一：

- 若 lineage 是审计要求，增加只读查询/API/UI。
- 若只是未来预留，明确标为 reserved，不把它描述成当前完整能力。

### 7.4 Retrieval citation 指标严重向 0 偏置

当前计数仅检查 raw source ID 是否出现在 LLM 文本，但 prompt 只提供证据正文和来源标题，不提供 ID。

正确方案：

- 让模型输出结构化 `cited_source_ids`。
- 或在 prompt 中使用稳定 citation token，例如 `[S1]`，服务端映射回 source ID。
- 最终回答和消息 sources 使用同一 canonical ID。

不要使用 title/summary 模糊匹配，假阳性和标题重复会让指标失真。

### 7.5 “三层检索”注释与真实语义不一致

当前 tier 按 Scope 集合过滤，不按 `MemoryLayer`：

- Tier 1：TEAM_ACCEPTED。
- Tier 2：PROJECT、TEAM_ACCEPTED、TEAM_CANDIDATE。
- Tier 3：PRIVATE 加上述 Scope。

`long_term/mid_term/short_term` 只是注释，不是实际查询条件。需要先定义真实层级契约，再优化三次检索。

## 8. 性能优化的科学排序

### 8.1 Search N+1

确认存在。FTS/RRF 最多合并 200 个候选，每个候选逐条 `_get()`，每次建立 SQLite 连接并重复 schema ensure。

最小优化：

- 按 collection 批量 `WHERE id IN (...)` 取 payload。
- 一次反序列化候选。
- `_ensure_schema` 只在初始化执行。

这是优先级高于 ANN 的低风险优化。

### 8.2 向量全表扫描

事实成立，但当前没有基准支持立即引入 ANN。

复杂度约为 O(V × 4096 + V log V)。应先：

1. 在 SQL 层按 workspace/project/user/scope 预过滤。
2. 复用 query embedding 和向量 norm。
3. 使用 top-k heap，避免全量排序。
4. 构造 1k/5k 数据集测量 p50/p95。
5. 达到 ADR 触发条件后再选择 native exact KNN、sqlite-vec 或 ANN。

### 8.3 分层检索重复调用

最多三次 search 成立，但不是每次都三次。优化必须保留 early return、每层预算和 RRF 语义。

可以先缓存一次 query embedding，再评估一次 superset 候选加显式 tier ranking。

### 8.4 Skill 提炼全量读取

一次提炼会全量加载 `user_memory_items` 和 `learned_skills`，再在 Python 中过滤。当前触发频率低于原报告描述。

达到单用户数千条 workflow memory 前，可先增加 owner/project 的 Store 查询；后续再考虑增量提炼或异步任务。

### 8.5 FTS backfill

只在 `fts_count < records_count` 时全量重建。当前更重要的是完整性：数量相同但 key 不同，或 FTS 行更多时不会修复。

改为 key 集合对账、schema/index version 或显式 rebuild marker。数据量小时全量重建可接受，不必过早优化增量算法。

## 9. Worker 与运行时风险

5 个 worker 均接入 lifespan，但默认关闭：

- auto-post
- daily-memory
- research-dispatch
- market-publish
- market-scout

当前测试覆盖 step 函数，没有覆盖 worker start/stop/loop 生命周期。

启用后，async loop 直接调用同步 SQLite、LLM、HTTP 和 embedding，可能冻结 FastAPI 事件循环。多 Uvicorn 进程还会重复启动同一批 worker。

修复：

- 同步 step 使用 `asyncio.to_thread` 或独立 worker 进程。
- 增加 leader/lease，防止多实例重复执行。
- 增加 lifecycle、取消、重启、异常恢复测试。
- Worker 状态不能只放进程内 dict，应有持久化运行记录。

## 10. 工程化与文档问题

### 10.1 验证门禁

本次实际执行：

```text
AGENTMESH_EMBEDDING_ENABLED=false .venv/bin/python -m pytest -q
373 passed, 6 warnings
```

```text
cd agentmesh-demo && npm run build
1617 modules transformed，build passed
```

```text
.venv/bin/ruff check .
23 errors
```

Ruff 失败包括：

- 未使用 import。
- import 排序。
- B904。
- B905。
- SIM102/SIM108。
- 测试未使用变量。

后端测试数量充足，但没有 coverage 测量，不能把“测试文件和数量”直接称为测试覆盖率。

### 10.2 缺少 CI 和前端测试

当前没有：

- GitHub Actions、GitLab CI 或 Jenkinsfile。
- Playwright、Vitest、Jest 或 Testing Library。
- React test script。
- Coverage threshold。
- SQLite 并发写和 lock contention 测试。
- Worker lifecycle 测试。

### 10.3 依赖声明不完整

README 声称 PDF 解析使用项目依赖中的 PyMuPDF，但 `pyproject.toml` 未声明 `pymupdf`。干净环境按 README 安装后，PDF 路径不能保证可用。

### 10.4 `.gitignore` 不完整

根 `.gitignore` 没有忽略：

- `node_modules/`
- `dist/`
- TypeScript build info 和 Vite cache

当前工作树出现 7000 余个未跟踪前端依赖/构建文件，严重降低审查和提交安全性。

### 10.5 CONTEXT 与代码冲突

`CONTEXT.md:14-15` 声称：

- React 19。
- TanStack Query。
- FastAPI 同源托管 React dist。

实际是 React 18、本地 DemoContext、无 TanStack Query，FastAPI 仍服务旧 `app.html`。

CONTEXT 还称 delegated answer、lineage、contribution 缺失，但相关模型和部分 Agent 方法已经存在，文档需要按“模型存在、生产入口缺失”重新描述。

### 10.6 巨型模块

| 文件 | 行数 |
| --- | ---: |
| `app.html` | 6801 |
| `tests/test_chat_flow.py` | 3070 |
| `agentmesh/agents.py` | 1982 |
| `agentmesh/store.py` | 1205 |
| `agentmesh/models.py` | 967 |
| `agentmesh/routes/blackboard.py` | 720 |

`agents.py` 同时负责聊天、意图、检索、记忆、Brief、委托回答、市场、Skill 提炼和 LLM fallback。`store.py` 同时承担 KV、FTS、vector、权限辅助和所有 collection。后续修改应围绕真实 seam 拆分，不做无目标的文件拆分。

## 11. 推荐修复顺序

### P0：立即止血

1. 轮换并移除 Embedding 源码 key，默认关闭 embedding。
2. 禁止生产创建固定管理员凭据。
3. 修复 chat thread owner IDOR 和 PRIVATE search 泄露。
4. 修复 documents list/detail owner 隔离。
5. 修复 Memory create/PATCH 状态机与对象权限。
6. 修复 Blackboard mutation、review、drain 和 actor 伪造。
7. 修复 OAuth disabled 用户复活。
8. 为 market board 增加认证和组织过滤。
9. 给上传、OOXML、PDF、图片增加资源预算。

### P1：恢复全局可用性和数据一致性

1. 把 embedding HTTP 移出 SQLite 写事务。
2. 把文档解析、切片、embedding 移到有界 worker。
3. 修复 stale vector、导入 manifest、resume 和 job 终态。
4. 取消业务代码对 seed Workspace/Project 的依赖。
5. 给数据连接器增加 Agent grant 和数据域授权。
6. 修复 citation 的结构化 ID 契约。

### P1：完成产品闭环

1. 将 React 接入真实认证、API client 和 server state。
2. 迁移 Workspace、Knowledge、Collaboration、Insights、Digital Self 和 Admin。
3. 切换 FastAPI 根路由并退役旧 `app.html`。
4. 定义并实现 LearnedSkill executor 后再接 `match_skill()`。
5. 实现 delegated answer/adoption API、幂等状态和 lineage 查询。

### P2：规模与维护性

1. Search 候选批量 hydration。
2. 定义真实 MemoryLayer 检索语义并减少重复 search。
3. 根据 1k/5k benchmark 决定 vector KNN/ANN。
4. Store owner/project 查询和增量 Skill 提炼。
5. FTS/vector 版本与完整性校验。
6. 拆分 Agent workflow 和 Store repository seam。

### P2：工程门禁

1. 修复 23 个 Ruff 问题。
2. 补 PyMuPDF 依赖或修正文档承诺。
3. 完善 `.gitignore`。
4. 增加 CI：pytest、Ruff、OpenAPI、React build、前端测试。
5. 增加安全负向测试、SQLite 并发测试和 worker lifecycle 测试。
6. 更新 README、CONTEXT、ADR 和能力状态。

## 12. 最终完成标准

- [ ] 源码中没有默认凭据或 API key。
- [ ] 所有对象读取/写入经过 owner、tenant、project 和 capability 校验。
- [ ] PRIVATE chat、document 和 personal memory 不能跨用户访问。
- [ ] Memory 与 Blackboard 使用显式、可审计的状态机。
- [ ] Embedding 不在 SQLite 写事务和 FastAPI 事件循环中执行。
- [ ] 文档导入可恢复、可重试、可校验完整性。
- [ ] 新 React 前端使用真实 API，旧 `app.html` 已按计划退役。
- [ ] LearnedSkill 和 delegated adoption 有生产执行入口或明确标记为预留。
- [ ] pytest、Ruff、React build、前端测试和安全回归全部通过。
- [ ] CI 自动执行发布门禁。
- [ ] README、CONTEXT、ADR 与当前代码一致。
