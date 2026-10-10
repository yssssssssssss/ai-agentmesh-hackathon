# 0056：版本化来源观察与当前来源检查

日期：2026-10-07。状态：本地开发切片；完整来源同步仍在实施。

旧 Source 只有引用信息，不能表达外部资料的版本、正文摘要和撤回状态。即使 Memory 本身仍然有效，已经准备好的上下文、资料抽取结果和协作信号也可能继续使用变更前的来源。连接真实读取系统前，需要让这些入口能核对同一份当前来源。

复用 `records/sources`，新增可选 `SourceSnapshotV1`，不另建来源状态机或事件存储。字段包含受限 provider、稳定 external_id、不透明外部 version、原文 UTF-8 SHA-256、服务端逻辑 revision、带时区 observed_at，以及 active/archived/deleted/unavailable 生命周期。revision 不代表 Provider 版本排序；观察时间也不证明 Provider 真实性。快照允许从 JSON 字典恢复 ISO 时间，同时保持整数、生命周期和额外字段校验。

没有快照的旧 Source 仍省略该字段，旧 Source/Memory 的持久内容摘要不重算，不给旧引用补造版本或正文证明。普通文档上传目前仍使用原契约。这个字段是公开 Source schema 的增量，前端 API 类型已同步。

`SQLiteStore.observe_source` 是受控观察入口。它重读实际用户和项目权限，在短写事务内核对 owner、不可变作用域、provider/external_id 和 expected_revision。新增或变更的活跃观察必须提交不超过 1 MiB 的原文，且与声明摘要一致；完全相同的当前观察或已有快照的撤回可以省略原文。首次写入为 revision 1，后续变化递增，最大值拒绝溢出。同一外部版本不能换正文；更早的变化观察、旧 CAS 和 deleted 之后的新内容被拒绝。匹配当前 revision 的完全相同观察保留第一次时间、revision 与审计，不作为同步心跳。

来源及安全审计原子提交。现有记录上的唯一索引约束同一 owner/workspace/project/provider/external_id；旧 `add_source` 仍支持原引用创建与相同重放，但不能把旧快照改认成新快照。原文校验不在 Source 中另存一份正文，也不自动确认事实或改变本地 Task。

Memory 来源检查现在重读已登记来源。带快照的引用要求当前快照仍 active，且版本、摘要、revision、引用信息、owner 与当前项目权限一致；旧引用遇到同 ID 的新快照也被拒绝。文档片段同时核对父文档的来源；带快照的资料镜像必须与原文摘要一致。检查覆盖现有检索、准备后交付、SDK 容量等待后的 Memory 回执、结构化文档证据、学习任务与市场材料选择。只改变可用性，不伪造 Memory 治理版本或重新计算旧摘要。

资料 HTTP 读取在授权快照中重检实际文档和当前来源；失效或不一致的正文返回 404。带快照的资料镜像暂不接受本地编辑，返回 `document_source_read_only`，避免把本地内容冒充为外部版本。无快照文档保留原编辑能力。事实确认的重复命令也重检当前来源和载荷证据，不返回已经失效的确认结果。晚到学习结果不能创建候选；此前已观察到的实际用量按原学习账本处理。

协作信号把已选来源加入既有私有发布依赖，来源变化与正文/检索投影撤回同事务提交。相同观察和未选来源变更保持已证明的发布；生成期间来源撤回则拒绝晚提交。启动检查撤回缺少已登记直接 Memory 来源或父文档来源依赖的历史自动信号，不补造旧依赖，保留完整证明和独立的既有 Task 材料。私有依赖 ID 不进入公开元数据。

验证通过现有 Store、MemoryContext、DocumentMemory、MemoryFacts、Learning、Runtime 与 HTTP 入口，使用隔离 SQLite、固定 SDK 和受控模型，无真实 Provider 请求。新增 55 项场景；7 组专项回归 221 passed / 49.36 秒。最终 Python 3.12/3.13 的 110 组关联回归各 1,837 passed，耗时 1,077.79/1,078.84 秒；各有 5 条 PDF 依赖 SWIG 类型的既有弃用提示。验收期间 353 项执行源码、测试和依赖摘要没有变化，前端类型生成、构建、bundle、Ruff 与 diff 检查通过。精确结果、开发 RED、fixture 修正及摘要见 `docs/verification/2026-10-07-versioned-source-observations.json`。早期 Runtime 测试确实复现严格时间字段不能从持久上下文恢复，已修复；无效 extra 字段的 model_copy fixture 和未知有效时间的事实 fixture 单独修正，不当作功能 RED。启动兼容检查补齐后，第一次双版本回归主动中止，不能计作最终通过。

这是来源协议基础与局部当前来源检查。没有实现真实 GitHub/O2/MCP 连接器、ConnectorSyncCursorV1、Provider ACL/删除发现、分页/增量同步、Source 与外部资料镜像的原子同步、原生上传自动快照化或完整引用别名协议。未登记旧引用保持兼容，不能据此声称旧物理删除已有墓碑；历史依赖检查也不宣称补齐所有间接摘要祖先。完整 Session/Runner/产物来源失效、关系与过程复用和真实质量仍未完成。阶段 3–5 保持实施中。
