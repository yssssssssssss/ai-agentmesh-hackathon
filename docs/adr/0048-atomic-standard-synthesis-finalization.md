# ADR 0048：普通合成的原子封存与当前执行资格

状态：接受（本地 ordinary/Universal 最终提交；通用 Source 生命周期、证据原文失效和远程实际交付继续实施）。

ADR 0047 检查到合成服务返回为止。真实 Runtime 测试复现：返回后、finalizer 写入前删除 Source 仍能完成报告。Universal 合成 Artifact 又在独立事务中提前插入；随后 Run/Plan/事件写入失败，会留下没有成功交付的 sealed synthesis。拒绝后的错误处理还可能将新 writer generation 或新计划版本标为失败，或将来源/授权拒绝降级成 Universal partial。

复用原 `finish_skill_plan_and_run` 写事务和 VerifiedArtifactStore 的 caller-connection 接口，不新增存储系统或第二套 Run 状态。合成前冻结内部 `SynthesisFinalizationSnapshot`：Run 身份/执行代次/契约、计划版本及语义字段、完整节点结果和当前 Source 引用记录身份。计划的 created_at/updated_at、待计算 completion_check 和 synthesis 不属于输入摘要；节点结果按 ID 排序，包含正文、引用、血缘和用量。已有浮点字段先通过严格 JSON 解码成为 Decimal，再按 canonical JSON 求摘要，不降低原 canonical encoder 的规则。

Source 选择与身份摘要共享一个模块，实际模型发送与封存使用同一含义。每次读取在 SQLite 读快照内复用同一 Source，比较引用及 owner/workspace/project/允许的 Run；最多 600 个不同 Source，单条 JSON 最多 16 KiB，未知/损坏/超限来源明确失败。摘要仍只证明现有本地引用记录，不证明远程原文版本或内容。

最终 `BEGIN IMMEDIATE` 内重新读取当前 Run/Plan，并复核当前用户、活动项目与成员资格、线程范围/状态、期限、Run 身份/执行代次、完整计划/节点结果及 Source 摘要。共享 Task 线程保留既有执行关系；无持久线程的可信直接调用继续遵循既有无 Session 语义，不因此接管旧 Session。发生变化时返回静态 `synthesis_sources_changed` 或 `synthesis_finalization_*`，不提交本次报告、synthesis 或成功事件。调用者仍承担执行准入，内部 snapshot 不成为客户端可提交的授权。

Universal Artifact 先只构造在内存中，completion 计算使用待提交的同一对象。实际写入在上述已复核的事务内调用 VerifiedArtifactStore：校验类型、scope、内容 hash、lineage、plan version 和报告中的 Artifact ID；Artifact、Plan、Run、Inbox 收敛与有序事件一起提交。任一后续写入失败全部回滚，不保留本次 sealed synthesis。已有合法工具证据及节点结果不因失败被删掉。

所有非 snapshot 的终态写入也比较当前与调用者的 Run 执行身份，防止检查失败后的旧写入覆盖新 writer。Runtime 错误处理发现 writer/契约身份或计划版本已变时不修改新执行；来源、预算或授权的 ModelAdmissionError 不再进入 Universal partial 兜底。其他已验证部分交付与未知外部副作用规则保持原语义。

新增 14 项行为场景，覆盖提交前撤回/撤权/期限变化、writer 和计划替换、节点结果/引用变化、Universal 正常封存、明确拒绝与真实 SQLite 事件失败回滚。测试使用实际 Runtime、受控 SDK Model、当前主体/项目、SQLite 写入及故障触发器。原抽象 finalizer 测试补齐真实主体和项目；静态来源拒绝统一断言 ModelAdmissionError 与具体代码，不以模拟授权跳过新门禁。精确回归见 `docs/verification/2026-10-07-atomic-standard-synthesis-finalization.json`。

最终 Python 3.12/3.13 的 44 组关联回归各 **719 passed**，耗时 **319.80/321.30 秒**。最终聚焦的六组回归 **120 passed / 38.13 秒**，Ruff 与 diff 检查通过。没有重跑整个后端、前端或浏览器，没有调用真实 Provider 或宣称远程 CI 通过。

这是提交时的资格检查，不能撤回已发送的 Provider 输入。snapshot 目前仅存在本次调用，不是持久 ContextSnapshot/远程 Runner receipt。通用 Source external_id/version/原文 hash/归档/墓碑与连接器水位、原生文档/Task/工具证据的完整来源失效传播，以及 Runtime 输出投影的当前权限继续按主方案实施。DeepSearch 保持其独立 finalization/Artifact 事务契约；不将本项称为完整阶段 3–5 或真实模型质量验收。
