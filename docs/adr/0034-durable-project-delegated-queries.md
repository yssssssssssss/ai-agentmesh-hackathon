# ADR 0034：持久项目代答、受限答案与已证明的采用

状态：接受（首个本地闭环；真实模型质量与统一 SDK 请求治理仍需单独完成）。

新增计划中的 DelegatedQueryV1，使用现有 SQLite records，不新建 Runtime。发起命令按 requester/command ID 去重；不同问题、target 或 project 不能复用命令。问题版本/hash、双方/项目、冻结输入证据的 Memory version/content hash/完整 record hash、授权状态、本人确认、claim、Artifact 和一次采用回执持久保存。

双方当前 active User、同 workspace 的 active Project/member 和本人 online personal Agent 在同一事务验证。读取仅请求方与回答方，admin 不获得第三方访问例外。匹配限定回答方本人、当前项目、active 私有纯文本记忆；最多八项，SQL 最多召回 200 项，每项最多 6,000、总共 16,000 个标题/正文字符。当前 AgentMemoryBinding、安全检查及原生来源继续约束匹配和返回。这是字符/条数边界，不冒称完整模型 token 预算；事实/过程载荷暂不转换为无时间语义的普通代答输入。

自动答复需要项目内明确授权和双方市场 opt-in。历史无 project 的 consent 不自动迁移。授权 API 的 grantor 从会话推导，以 expected version 和命令确认启用/撤销；它不会替用户加入市场。高敏命中始终进入回答方私有 Inbox。确认事务核验问题、原 Inbox、精确证据及当前匹配集，避免待确认期间新增高敏依据被静默采用。普通 Inbox resolve 不能消费此确认，第三方也不能读取确认摘要。

复用 PersonalAgent 的同步合成方法。首次生成领取唯一 claim 与 90 秒期限；生成前后重检双方、授权/参与水位、绑定和冻结依据。变化使结果 blocked 且不写答案 Artifact。已领取但中断的调用不自动重试；DB 重开后可看 pending，到期转 failed。显式 resume 仅能继续尚未领取调用的已批准请求，不能再次调用已领取请求。未知 Provider 成本不被伪装为零；该旧同步接口的累计预算、实际 MemoryUseReceipt 和可取消模型期限仍属于阶段 4 的统一请求治理工作。

只有实际 answered、非空且不超过 8,192 字符、有引用的结果创建 insert-only sealed Artifact 与 Source。Artifact 内容绑定 query、问题 hash、证据 hash 与受限答复，外层 hash/size/owner/scope/type/index 一并复核。复用 artifacts 表；历史列 run_id 在此存 query 的执行身份，由 delegated_answer type/schema 明确区分，不创建虚假 SDK AgentRun、不让通用 Run Artifact API绕过 Query 授权。请求方收到泛化引用和 query 链接，不复制私有资料标题、链接或 Memory ID。

GET 与采用重检当前双方、原授权水位、记忆绑定/生命周期/版本/hash、原生来源及 sealed Artifact。历史 answered 状态保留；当前失效时隐藏答复和引用，并停止采用。撤销或重新授权不会恢复旧水位；需发起新请求。答案历史保留不等于继续交付权限。

采用只由 requester 对精确 Artifact hash/version 执行，私有 Memory、Source 血缘、不可兑换贡献、Audit 和 query 回执在同一事务写入。每个 query 最多采用一次，同命令重试、DB 重开或不同命令重复采用均返回原回执。不给 requester 读取回答方原记忆的权限，也不生成 accepted 团队知识。采纳后的来源检查继续穿过 query 证明；回答方依据、绑定、授权或当前双方失效时，新上下文不能再使用该派生记忆。已经交付的内容仍遵守原历史/备份保留边界。

Collaboration 增加发起、自动提问策略、本人确认/拒绝、实际状态、受限答案与私有采用流程；Inbox 能打开对应 query，较旧请求可独立读取而不依赖最近 50 条列表。浏览器重试保留命令，成功后下一次显式发起使用新命令。旧无 query 身份的确认和市场状态采纳保持不可执行；scout 通过持久 query 发起且使用匹配 fingerprint 去重，不授予 consent。

确定性测试覆盖数据库重开、实际 API/角色、确认、幂等采用、当前撤权/来源/绑定变化、模型调用期间变化、Artifact 篡改以及中断不重试。Ego Lite 使用独立临时数据库和关闭的 Provider 验证真实页面请求、确认、空资料/无模型状态、授权/撤销与刷新。注入模型仅验证控制合同，不证明答案质量。真实网关依赖仍未恢复，完整阶段 3/4/5 保持未完成。
