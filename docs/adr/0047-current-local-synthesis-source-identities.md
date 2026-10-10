# ADR 0047：本地合成来源身份与原子 Source 创建

状态：接受（普通本地 SDK 合成的引用/身份检查与 Source 创建；通用来源版本、原文 hash、墓碑和原子交付复查继续实施）。

ADR 0045 在普通合成的模型名额等待后重检 Source 是否存在及其归属，但同一 ID 的 title/reference/type/skill 变化不会被发现。节点结果保存的引用也可能已经落后于首次合成时的 Source。模型发送期间发生来源删除或 owner 撤权，返回值仍可能进入 finalizer。这些路径已由真实 Runtime 与受控 SDK Model 的行为测试复现。

保留既有 Source/SkillResultSource 模型和 SDK wrapper，不新增公开协议或第二套来源库。普通本地 synthesis 先复查当前 Run 执行资格、Source 所属工作区/项目/owner 和既有允许的 Run 范围，再比较节点引用的 id/title/source_type/reference 与持久 Source。每个已检查 Source 的引用记录身份形成 canonical SHA-256 摘要，覆盖除 created_at 外的现有字段；created_at 不属于既有不可变身份，重试继续保留首条记录的时间。该摘要只证明本地引用记录，不能用来声称远程原文已经冻结。

摘要仅保留在本次合成调用内。每次实际模型发送（包括 repair/retry 的等待后发送）重新检查当前资格、节点引用与完整身份摘要；合成服务返回后再次检查，发现来源变化或当前 owner 不可执行时拒绝结果。既有 `synthesis_sources_changed` 静态错误绕过 schema repair/确定性降级，并由执行器记录失败，不生成本次合成的 report/output/synthesis_completed。已有节点结果保留，不伪造模型调用没有发生；已发送的内容也无法撤回。来源为空且当前执行资格合法的合成继续可用。

Source 的原创建方法在独立读取之后 upsert，两个并发调用可以各自发现不存在，再覆盖同一 ID 的身份。`add_source` 现在使用短 `BEGIN IMMEDIATE` 事务内的读取、identity 比较和写入，复用原 records 表。两个竞争身份仅一个成功，另一个明确 `source_identity_conflict`；相同身份保留首条完整记录，重开与重试不会改变 created_at。存储 row ID 与 payload ID 不一致也拒绝。Source 不属于全文/向量索引集合，因此直接写普通记录，不触发外部模型或索引工作。方法仍是可信服务端持久化接口，不代替调用者的授权检查。

测试接口为既有 Runtime 已批准计划执行、模型名额等待/返回，以及 `add_source`/`get_source`。并发测试控制旧接口的外置读取窗口，使两次 absence 观察先于旧写入，使用真实 SQLite 事务和线程；修复后的写入不依赖该外置读取。新增 17 项场景，覆盖已变引用、等待期间变化、模型返回时删除/变更/撤权、ID 不一致、成功引用、并发冲突和持久幂等。关联回归与精确文件摘要见 `docs/verification/2026-10-07-current-local-synthesis-source-identities.json`。

最终 Python 3.12/3.13 的 37 组关联回归各 650 passed，耗时 300.50/300.52 秒。Ruff 和 diff 检查通过；无公开 schema/前端变化，未调用真实 Provider、执行浏览器验收、重跑全后端或宣称远程 CI 通过。

本项检查到合成服务返回为止，返回后至 finalizer 写事务之间仍需统一原子封存时复查。Source 摘要尚未成为持久 ContextSnapshot/远程 Runner 契约；这里也没有新增 external_id、外部原文版本/hash、归档/删除墓碑、连接器水位或完整 Source 失效传播。Runner 的既有确定性合成仅增加首次引用一致性检查，不宣称远程实际交付已验收。DeepSearch 继续使用其原有证据 Artifact/manifest 规则。完整阶段 3–5 与真实模型/企业质量验收继续按主方案执行。
