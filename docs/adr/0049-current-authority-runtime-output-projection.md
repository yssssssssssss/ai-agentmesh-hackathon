# ADR 0049：Runtime 结果投影的当前权限与私人记忆策略

状态：接受（本地终态聊天/私人记忆投影；完整来源失效传播和远程 SDK 交付继续实施）。

ADR 0048 封存 Run/Plan 后，Runtime 另行将结果投影到聊天和私人短期记忆。已有投影事务保证消息、记忆、Session 标记、回执与事件原子提交，但只检查终态和正文。测试复现了提交前撤权仍写入、相同正文掩盖 writer 替换、记忆策略关闭后仍保存，以及直接修改其他人的 Session。手动保存的 HTTP 路径也会保存检查后改变的 Run 正文。

复用原 `project_terminal_run_output` 的 `BEGIN IMMEDIATE`，不增加状态机或存储系统。调用者携带预期 Run，事务重新读取并比较执行身份/契约、writer generation、Skill、模式、终态、输入和输出；当前主体、项目状态/成员、工作区、线程状态/范围/归属再校验一次。缺失线程不能产生孤立 ChatMessage。拒绝发生在任何投影写入前，也适用于旧回执重放；已封存的 Run/Plan 不因此被改成失败。

实际 Runtime 测试进一步复现：终态封存后重新读取 Run 会使旧执行采用新 writer 的身份。普通合成和 DeepSearch 的执行调用现在使用 executor 返回的封存 Run，不重新读取并替换其身份。直接聊天和审批恢复也由 finalizer 返回封存 Run，不能将执行中的旧状态交给终态投影。独立恢复路径仍读取当前持久 Run，但实际投影事务会再次校验该读取与写入之间的变化。

自动记忆构造移入投影事务，使用当前持久 Run、Plan 和 Skill 策略。只有已完成/部分完成的直接 Skill 或 Standard Plan 明确允许私人短期记忆时才新增；Skill 已关闭或策略改变只跳过新记忆，合法聊天仍可交付。客户端和 Runtime 不再传入待写入的 UserMemoryItem。自然聊天仍需要用户显式保存，不会自动共享团队记忆。

手动保存也携带 HTTP 路径刚验证过的 Run，身份/正文变化、撤权或本人运行记忆已有遗忘墓碑时返回现有 unavailable 结果。先手动保存、后恢复聊天投影保留原记忆和标题，不因重复 INSERT 失败，也不将已有记忆改写为自动摘要。已有记忆和重放消息必须匹配 Run 的稳定身份及 private 范围；已遗忘/非活动记忆不会被投影重建。回执仍是历史事实，不重新宣称先前保存的记忆当前可用。

私人 Session 的同步标记核对 owner/workspace/project 和 writer。不存在的 Session 只在有当前本人线程的情况下建立明确归属；带旧正文/依赖而没有 owner 的 Session 拒绝接管；没有正文、只有同步标记的旧 Session，最多核对 1,000 个 ID，必须全部是当前线程的真实 private 消息后才能绑定。未知或跨线程标记拒绝。同一 Run 的 generation 不同明确冲突；合法的其他 writer 或已撤回 Session 保持原样，聊天自身仍按现有规范记录保存。共享 Task 线程必须具有实际 Task/Thread 关系；交付不创建或修改请求者的私人 Session，也不修改 Task 或 Review 状态。这里是产品结果与同步标记，不能代替远程模型实际接收回执、SDK replay 或审批恢复。

执行期限约束计算和封存；已经合法封存的终态结果可以在期限之后恢复投影，当前访问权限仍需满足。SQLite 事件失败会回滚全部新消息、记忆、Session 标记、线程更新时间和回执；并发重试及数据库重开保持一条消息、记忆和事件。

新增 34 项确定性场景，测试使用真实 SQLite、Runtime、受控 SDK Model 和 HTTP 接口；使用事务故障触发器验证回滚。旧 positive 测试补齐当前主体/项目/线程，不放宽写入检查。最终 Python 3.12/3.13 的 51 组关联回归各 **807 passed / 无警告**（332.35/332.34 秒），Ruff 与 diff 检查通过。结果和当前文件摘要记录在 `docs/verification/2026-10-07-current-authority-runtime-output-projection.json`；未调用真实模型/企业系统，也未执行浏览器或全后端验收。

本项校验当前投影权限、执行身份、现有记忆策略和目标归属。它不持久化 ADR 0048 的 Source/Plan 输入快照，不能证明封存以后外部原文、引用记录或节点结果仍与生成时一致，也不撤回已经交付的聊天内容。通用 Source external_id/version/原文 hash/归档/墓碑、完整记忆输入血缘的结果失效、Task 审核证据、持久 ContextSnapshot 和 Runner 实际交付按主方案继续实施。阶段 3–5 仍未完整验收。
