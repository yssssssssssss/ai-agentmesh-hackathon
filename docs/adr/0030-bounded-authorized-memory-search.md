# ADR 0030：授权记忆检索的 SQL 筛选与有界加载

状态：接受（单应用进程、SQLite、FTS 路径）。

原上下文搜索在 FTS 前加载完整 Personal/Memory 集合，并加载 Documents、Blackboard 集合建立 ID 白名单。50k 合成记录、10 并发诊断中端到端 p95 达到约 52.4s。索引查询前的 Python 筛选和大量独立连接会放大并发成本。

在现有 Store search 中使用内部 MemorySearchFilter：当前 actor/workspace/project、owner、team membership、生命周期、类型、层级及结构化载荷限制在 FTS/LIKE/向量候选上先执行。普通摘要检索不交付需要专用验证的事实和过程。候选查询、当前记录与可见性检查使用同一只读事务；仍保留后续来源检查、冻结版本和实际交付回执事务。

FTS/LIKE 每次最多返回 200 条候选，命中才加载记录，安全过滤先于结果数量和正文预算。自动 fallback 最多查询八个具体术语并合并候选；兼容 search_pool 上限为 200。共享 Blackboard 的证据、决策和归档可检索，按需读取所属 Task/Thread，不建立全量字典。Actor、Binding 或权限不允许的项目仍不进入候选。

保持默认 BM25 语义，使用 FTS5 的 rank 排序处理 LIMIT；[SQLite 官方说明](https://www.sqlite.org/fts5.html#sorting_by_auxiliary_function_results)列出了默认 rank 与无权重 BM25 的等价性。单 Store 的本地 FTS/LIKE 召回排队执行。50k 高密度词命中压测中，这比并发重复排序减少 CPU/SQLite 调用争用。队列等待计入端到端延迟，embedding Provider 调用位于该锁之外；不锁应用所有读写，不共享跨线程连接，不缓存权限结果。

最终隔离压测：50,000 条记录、10 并发、100 次查询，p95 **642.471ms**，全部返回八条授权结果。SQLite execute/fetch p95 **141.068ms**，连接/PRAGMA **29.594ms**，Python RRF **0.205ms**，召回排队 **554.536ms**。这些 span 重叠，各自的百分位不能相加。报告与命令见 `docs/verification/2026-10-06-authorized-memory-retrieval-benchmark.json` 和 `eval/run_memory_retrieval_benchmark.py`。

补充同规模的严格个人与团队范围，各 100 次查询，p95 分别 **943.424ms**、**715.123ms**，授权与延迟门槛均通过。个人范围接近 1s 门槛，后续容量变化继续以相同夹具复测。两份独立 scope 报告保留 execute/fetch、连接、RRF 及排队样本。

这是包含 owner 私有、已接受团队、其他 owner 和其他 Workspace 的合成容量证据。此次 embedding 关闭、未启用外部 reranker，分别报告零 Provider 时间。向量路径通过独立确定性权限/候选测试，但尚无 50k 向量容量成绩。不能据此声称真实模型质量、企业 Provider、任意突发负载或多进程 SQLite 已验收；仍无引入 PostgreSQL 的已证明需求。
