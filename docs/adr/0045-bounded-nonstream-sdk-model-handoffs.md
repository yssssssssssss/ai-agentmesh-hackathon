# ADR 0045：非流式 SDK 请求的预算与当前准入

状态：接受（本地普通/Universal 规划与 DeepSearch 模型阶段；累计成本、远程 Runner 与通用 Source 合同继续开发）。

普通聊天的流式入口原来负责安装模型发送前的检查，非流式 `Runner.run` 则没有同样的入口保护。普通意图分析、计划生成与修复、结果汇总，以及 DeepSearch 的需求澄清、问题图、规划、汇总与语义审查，可能在未检查完整请求预算或等待模型槽位后授权已改变的情况下继续发送。部分适配器还会把授权/预算异常当作模型输出格式错误，重试或生成降级结果。

复用 `MemoryContextService.guard_model_request` 与 `RequestBudgetModel`，不建立第二套模型或记忆服务。请求检查包含 SDK 实际组装的 instructions、消息历史/工具结果、工具与 handoff schema、结构化输出 schema 和 model settings。未知 tokenizer 继续明确使用保守 UTF-8 估计及 1,024 的封装余量；默认总额 64,000、输出上限 8,192，调用者较低的输出限制保留。隐藏 Provider 会话与未计量媒体仍拒绝。只记录模型标识、计量和 allowed/withheld 决策，不记录拒绝的正文。

请求包装器现在自行安装、恢复当前异步调用的发送检查。`_CapacityBoundModel` 获得实际并发槽位之后重新测量请求，并验证当前 Run/writer、身份/项目/Thread/Task 授权及期限。取消、错误和正常完成均恢复 ContextVar；聊天和会话压缩移除重复安装。并发调用分别携带自己的检查。没有模型槽位包装的直接模型立即检查；不是将本地检查推广为远程交付证明。

模型调用明确区分规划和执行阶段。意图、需求/图/计划阶段只允许当前 `planning` Run；汇总和审查只允许当前 `running` Run。审批等待、取消/终态与写入 epoch 改变均拒绝继续发送。普通与 DeepSearch 运行分别复查适用的 deadline/absolute expiry；Memory 关闭也执行这些检查。授权身份在创建检查时冻结，不能通过调用者后来修改 Run 对象替换。

DeepSearch 的完整请求检查位于已有持久模型预算包装之外。因此，最初已超过请求上限的需求不会先建立模型尝试预留。排队后才被拒绝的请求仍遵循已有 DeepSearch 未知尝试结算政策；本项不宣称它们自动退款，也不增加普通 Run 累计 token/费用账本。

普通计划汇总复用现有 Source 检查，在实际模型发送前再次核对来源存在、owner、workspace/project 与允许的 Run 身份。排队时来源消失不能进入格式重试或确定性汇总。该检查尚不提供任意外部 Source 的版本/hash/墓碑/新鲜度合同，也不代替 DeepSearch 证据封存与报告验收。

`MemoryContextError` 与 `ContextRequestError` 保留原公共类名和静态安全码，使用共同的 `ModelAdmissionError` 区分发送拒绝。意图、计划修复、普通汇总、DeepSearch 汇总/审查都直接传递拒绝。DeepSearch Finalizer 对该拒绝提交 failed 终态与具体原因，不创建降级 digest 或报告。实际 Provider/格式错误的原有修复与允许的降级策略保留；新的检查不自动注入私人 Memory 到这些规划/审查阶段。

新增 26 个行为场景，涵盖完整中文请求预算、输出限制、DeepSearch 预留顺序、真实普通意图/Universal 规划入口、汇总排队后的 Source 消失、格式修复拒绝、DeepSearch Finalizer 终态、不同 Run 的并发隔离，以及流式/非流式 SDK 在槽位等待时取消。Python 3.12/3.13 的 26 个关联文件各 **461 passed**（241.49s / 241.82s），Ruff/diff 通过。最终关联回归及文件 hash 记录在 `docs/verification/2026-10-07-bounded-nonstream-sdk-model-handoffs.json`。没有改变公开 API/存储载荷或前端控件；未调用真实 Provider 或进行前端/浏览器/全后端验收。

完整 ContextAssembler 的选择优先级、普通 Run 累计请求/输出/成本账本、压缩未知用量、通用 Source 生命周期、OS 解析隔离、Session replay/sealing、远程 Runner 交付和真实质量/企业试点继续按主方案实施，阶段 3–5 保持实施中。
