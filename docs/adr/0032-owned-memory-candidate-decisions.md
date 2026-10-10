# ADR 0032：本人运行的记忆候选与真实交付状态

状态：接受（本地 Bundle、Snapshot 和 SDK 工具交付）。

候选选择附着现有 MemoryContextBundleV1，不新增独立内容库。每条只保存 Memory ID、record type、version、hash、决定和静态原因，最多 200 条；不保存候选标题、摘要或来源正文。SQL 授权之后的安全及原生来源检查记录隔离/不可用，组装记录预算丢弃。召回后版本或内容变化则 withheld，不能用新的版本证明旧的检索正文。准备与引用预留不产生使用回执。

本人运行详情读取每个 Run 最近 16 个执行快照及 16 个工具准备载荷，校验归属和 canonical hash，最多投影 200 个唯一版本。无 candidates 的旧 bundle 从选中命中、冻结事实或过程选择派生状态；空字段继续省略，旧快照字节和 hash 保持不变。当前 actor/project/Run/thread、Agent binding、Memory scope/版本/hash 和原生来源在同一个只读事务检查。事实重查新冲突和术语版本，过程重查当前条件、工具能力及验收证据。

只有该 Run 中相同 record type/ID/version/hash 的持久 MemoryUseReceipt 才能显示 delivered。来源或权限后来失效时仍保留“曾交付”的历史事实，但不返回当前标题；没有实际回执的失效准备项显示 withheld。候选 API 不返回摘要、步骤、事实值或来源正文。Workspace 展示待使用、暂不可用、安全隔离、超出预算和已使用，解释准备与交付的区别。

本人 forget 与来源撤回的既有事务同时清空候选引用的执行快照和工具准备载荷；v5 数据库屏障包含 candidates，重开后仍拒绝晚到恢复。已交付回执继续遵循原有保留政策。

确定性验证覆盖真实 API owner 隔离、准备不计使用、SDK 模型边界交付、当前事实冲突/过程工具撤销、召回与组装的版本竞态、候选专属快照及工具载荷遗忘/重开。它不验证语义安全、真实模型答案质量或远程 Runner 的交付。完整 ContextAssembler、四基线评测与 Runner 协议继续保持独立范围。
