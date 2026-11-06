# ADR 0051：SDK producer 完成确认与节点取消传播

状态：本地确定性验收完成。此项补齐 ADR 0050 中的本地 SDK producer 取消检查；持久 lease、完整预算与远程交付继续实施。

受控真实 SDK 复现：模型 producer 抛出 `CancelledError` 后，`stream_events()` 会结束而不向消费者传播取消，直接 Runtime 因而返回空答案并提交成功。源码确认当前锁定 SDK 提供公开 `run_loop_task`，事件排空已经等待该任务，但会吞掉其取消。

Runtime 在事件流消费后显式等待这个公开任务，确认 producer 的真实完成状态，再允许结果进入既有 finalizer。取消沿原异常链传播，不用答案是否为空、事件数量或 provider 文本猜测执行状态；没有修改 SDK、增加异常协议、状态机或重试。直接聊天和审批恢复沿用 ADR 0050 的 writer 检查、终态收敛和未知副作用规则。

节点编排还复现了 Python `TaskGroup` 对单个子任务取消的处理：不取消父任务或兄弟任务，结果表缺项，父执行出现 `KeyError`。节点取消现在通知其实际父任务；已在取消中的父任务不重复增加取消请求。原 TaskGroup 负责等待和停止兄弟任务，容量上下文负责释放名额，父执行按既有业务规则收敛。

普通 executor 在领取执行后冻结 Run 身份和 Plan 版本，取消处理不能重新读取并接管新 writer、Runner 或新 Plan。无合成快照的终态写事务补查执行身份和 Plan 版本；读后变化拒绝提交，并保留原取消语义。共享瞬时 Run 摘要加入 Runner，已有合成快照继续返回自己的准入错误；不重算 Memory/Source 的持久 hash。无需增加新的运行控制表。DeepSearch 原有取消恢复与预算账本规则继续保留，不将过程取消误报为新报告成功。

确定性验证覆盖直接/恢复、原始/原子流、正文片段后的取消、真实 Runtime 批准 Plan、旧 writer、提交前版本/Runner 变化、兄弟任务停止和容量释放。未知外部写入使用持久受控 claim 验证，保持 `external_outcome_unknown` 且无自动副作用重试；没有调用真实写入工具。

新增 **20** 项场景：真实 SDK 流式/恢复与 Runtime Plan 12 项，executor 取消 7 项，合成封存 Runner 变化 1 项。修正后的四组聚焦回归 **73 passed / 51.02 秒**；最终 Python 3.12/3.13 的 **58** 组关联回归各 **952 passed**，耗时 **440.90/440.01 秒**，无警告；Ruff 与 diff 检查通过。初轮未通过结果、fixture 修正、队列观察诊断、精确回归文件与当前摘要见 `docs/verification/2026-10-07-settled-sdk-producers-and-node-cancellation.json`。公开 API/schema 与前端不变；未执行全后端、浏览器或真实 Provider/企业连接器验收。

此项证明当前锁定 SDK 的本地 producer 取消及普通 DAG 的取消收敛，不提供跨进程 durable lease、远程实际接收回执、所有规划/审批/节点状态提交的执行身份管理或完整来源/记忆失效传播。累计请求/成本预算、统一上下文、过程复用、连接器水位、部署级解析权限及真实 Provider/企业质量验收继续按主方案实施，阶段 3–5 保持实施中。
