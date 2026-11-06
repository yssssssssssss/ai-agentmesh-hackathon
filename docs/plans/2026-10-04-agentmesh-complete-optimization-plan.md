# AgentMesh 完整优化方案：团队项目记忆与可靠 Agent 执行

- 日期：2026-10-04。
- 状态：实施中。阶段 1/2 已完成本地确定性验收；阶段 3–5 已完成结构化记忆、学习/遗忘、审批/Session 来源检查、持久代答、资料恢复、当前授权市场读取/发布、本地非流式 SDK 请求准入、原子合成封存、结果投影当前权限、直接 SDK 状态提交隔离、SDK producer/普通节点取消、节点审批执行身份隔离、普通 Run 累计模型预算及文档解析进程/资源限制等开发切片，整体仍未完成。统一上下文、累计预算、完整 Session/Runner 对齐、部署级解析文件/网络隔离、外部连接器/关系及过程复用继续开发；真实 Provider/企业试点和 120/24-case 模型质量验收待完成。阶段 6 按实际负载条件触发。最新逐项证据见第 19 节。
- 基线：`feature/workspace-memory-closed-loop`，HEAD `5a7e7c5`，包含尚未提交的 Local Runner 工作。
- 适用范围：可信企业内网，先服务 1 个真实项目、5–15 位试点成员，再扩大到多个项目。
- 权威说明：本文件替代同日《架构升级与长期记忆方案》的产品方向、优先级、阶段安排和技术决策；旧文档保留前序检查记录。

执行节奏（2026-10-07 按用户反馈收敛）：日常开发只新增或运行直接受影响的关键行为检查，尤其是权限、数据写入、取消、恢复与失败重试；检查通过后继续功能开发。没有新改动、新失败或尚未解决的问题，不重复已通过的检查，也不扩展假设性边界测试。完整回归、双 Python 版本、浏览器端到端及真实 Provider 验收集中在相应阶段交付，实际外部依赖仍按本方案执行。测试数量不作为进度，进度以用户可用功能和阶段验收为准。

恢复开发后的优先级：收尾暂停时已开始的改动后，先完成一个真实项目的资料同步、带来源查询、问题巡检、确认行动和经验复用入口。新增架构和技术以该流程的实际缺口为依据，控制 Runner 协议和假设性边界工作扩张。

下一项产品切片的具体范围、直接收益、来源契约和完成标准见[项目巡检到处理行动与经验复用开发计划](2026-10-07-project-inspection-action-memory-development-plan.md)。该文档当前为待实施计划，不能作为新增功能完成证据。

## 1. 推荐方向与投入边界

将 AgentMesh 定位为 **以团队项目记忆为核心、以个人 Agent 为入口的项目协作与执行平台**。

用户首先购买或采用的价值应当是：查清项目进展与问题、还原决策原因、找到相关经验、减少重复同步，并让明确授权的任务可靠执行。个人 Agent 负责理解用户、保存私有上下文、查询项目证据、提出行动和执行已授权工作。团队知识依靠来源、时间、版本和审核积累。

先聚焦一个真实项目的四个动作：**查询 → 巡检 → 确认行动 → 沉淀经验**。建议投入分配为团队事实与记忆约 50%、可靠执行与自动化约 30%、个人体验约 20%；这是产品优先级建议，不是已有商业验证。

本方案不承诺“比所有最新 Agent 更强”。可比较的目标是：长期事实更新、中文项目检索、来源可验证、执行可恢复和团队治理达到明确验收指标。先证明这些能力，再扩展通用 Agent 场景。

最小交付只做阶段 1、2：保留 SQLite 与单进程，约 17–23 个工程工作日，即可提供真实查询和三个自动巡检模板。完整核心交付阶段 1–5 约 51–69 个工程工作日，另留 20% 集成与验收余量；一名熟悉仓库的工程师约 12–17 周，两名工程师约 8–12 周。PostgreSQL 等规模化工作另计，不作为试点前提。

关键假设：试点团队愿意提供真实、可授权、可追溯的项目材料，并使用已有 Task/Review 流程。若材料长期稀疏或过时，Agent 必须报告未知和数据缺口，不能靠更大模型或更多记忆生成项目事实。材料来源不足时仍可使用本地 Task 巡检与显式记忆，不依赖外部系统才能启动。

## 2. 检查结果与证据边界

已检查入口、配置、领域文档与 ADR、认证授权、任务及审核、记忆治理/检索/上下文、Skill 规划执行、工具与 O2/MCP、文档导入、Runner、前端关键页面、CI 和评测。没有发现项目内 `CLAUDE.md` 或 `.claude/rules/*.md`。这是全项目架构检查及关键链路复核，不等于逐行安全审计。

前序审计在隔离宿主机默认 O2 探测后得到：后端 1,900 项测试通过，Ruff 通过，前端 200 项测试通过，生产构建及 bundle budget 通过。自动查询专项的 25 项相关测试也通过。本机 Python 为 3.13，CI 配置为 3.12；本轮未重跑远程 CI、浏览器 E2E、真实 Provider 质量评测或生产负载测试。

下表区分源码能力与发布可用性；默认值来自 `.env.example` 和对应设置代码，未读取真实 `.env`，不代表正在运行实例的实际开关。

| 领域 | 现状 | 优化结论 |
| --- | --- | --- |
| 团队 Memory | 已有独立审核、版本、生命周期、来源与使用回执 | 保留并增强，不替换治理权威 |
| 项目 Task | 已有依赖图、交付审核、Run 关联和运营投影 | 保持唯一任务事实，增加自动巡检与明确启动入口 |
| 自动协作市场 | 有定期发布、扫描、匹配和代答；默认关闭，用户需加入市场 | 能运行，仍需持久去重、质量门禁和用户闭环 |
| 自动调研消费 | 有后台消费请求、证据回帖和任务更新；默认关闭 | 补失败记录、重试、幂等和真实结果要求 |
| 定时 Agent 任务 | 有定义的增改查，没有消费定义的时间调度器 | P0 补完整调度执行闭环 |
| Agent 队列 | 任务状态的只读投影，不会自动接活 | 保留语义；定时任务通过独立授权入口创建 Run |
| 调研兜底 | 未配置真实 Provider 时返回固定复盘内容 | 禁止作为生产查询成功 |
| 数据兜底 | `local_metrics` 返回固定样本 `0.123` | 仅供演示，必须标注为样本 |
| SDK/Runner | 服务端有 Session；Runner 历史拼接成文本，当前不支持工具审批恢复 | 统一结构化上下文、审批状态和交付回执 |
| 持久化 | 当前产品边界为单 Workspace、单进程 SQLite | 先优化查询与事务，再按实测迁移 |
| 工程维护 | Store、Runtime、models 集中；依赖锁与行为评测需要加强 | 按领域事务提取模块，不做一次性重写 |

关键源码：`agentmesh/acquisition.py` 的 `MockAcquisitionAgent`；`datasources.py` 的 `LocalMetricsConnector`；`routes/agents.py` 的 scheduled-tasks CRUD；`routes/blackboard.py` 的 research dispatch；`marketplace.py` 的周期 worker；`runner_executor.py` 的历史构造及审批拒绝逻辑。

维护热点的前序检查规模：`store.py` 18,770 行，`agent_runtime/service.py` 6,749 行，`models.py` 3,640 行。文件长度不是缺陷本身，风险是跨领域事务、执行状态与兼容路径在同一修改面交织。

## 3. 产品范围与用户闭环

### 3.1 第一批必须交付的场景

| 场景 | 用户动作 | 可见结果与判断依据 |
| --- | --- | --- |
| 查项目现状 | “本周有哪些变化、哪些任务阻塞？” | Task/Review 的确定性结果，加来源、截至时间和缺失数据说明 |
| 查决策原因 | “为什么当时改用方案 B？” | 决策记录、当时证据、对应版本；区分已确认与候选观点 |
| 查历史事实 | “上个月谁负责这个模块？” | 按有效时间回答，显示后来变更，不拿现在状态代替过去 |
| 自动巡检 | 开启每天 9:30 的项目巡检 | 检查逾期、阻塞、依赖未完成和待审核；变更才通知 |
| 查询外部问题进展 | 授权一个真实连接器同步状态 | 可查询观察到的外部状态与同步时间；映射经确认后才能改变本地 Task |
| 执行后续工作 | 在巡检结果中确认生成 Brief/调研 | 创建现有 AgentRun，跟踪执行、审批、产物与 Task Review |
| 跨项目复用 | “有哪些已验证的同类解决办法？” | 有适用条件、结果证据和失效说明的团队经验 |
| 纠正与忘记 | 修改负责人、撤回资料或删除个人记忆 | 新查询立即排除旧的自动上下文，历史审计保持可解释 |

第一批巡检固定三个模板：**每日进展、阻塞/逾期、待审核**。规则计算对象和变化，LLM 只负责有证据的摘要与建议。不上来就开放任意提示词驱动的后台写工具。

### 3.2 个人与团队记忆的关系

个人层保存工作偏好、私有笔记与个人执行经验；项目层保存有来源的决策、约束、风险和变更；团队层保存独立审核通过、适合复用的知识。Scope 与短/中/长期层级继续作为两个独立维度。

普通聊天仍私有，显式 `$` 工作流保留。Task Review 验收交付质量，Memory Review 验收共享知识质量；前者不能自动完成后者。自动化可以生成候选和建议，不会自动把私有内容升为团队知识。

### 3.3 暂不纳入核心交付

不建设通用 Agent 商店、贡献积分兑换、人员绩效评分、全自动替团队作决策、任意 shell 自动执行或会议双通道音频。公网多租户 SaaS、移动端、全量连接器平台和无限多 Agent 自组织也不在本次核心范围。

这些功能有各自的权限、运维和产品成本，不能为了“功能看起来多”并入主线。

## 4. 优化优先级

| 优先级 | 工作 | 为什么先做 | 完成标志 |
| --- | --- | --- | --- |
| P0 | 真实/模拟/失败结果语义统一 | 解决“完成却没真实查询”的可信度问题 | 生产路径不能靠 mock 完成；UI 显示实际 Provider 和降级原因 |
| P0 | 定时调度及三个巡检模板 | 补齐自动查询真实缺口 | 到点执行、重启恢复、权限撤销停止、结果可回查 |
| P0 | 后台失败、去重、重试和预算 | 解决静默失败与重复调用 | 每次触发都有运行记录，重试受限、异常可见 |
| P1 | 项目事实、时间、冲突、纠正和遗忘 | 形成长期项目记忆的核心价值 | 跨会话更新正确，旧事实不会冒充当前事实 |
| P1 | 统一上下文与 Server/Runner 恢复 | 让长任务可靠执行 | 结构化消息完整，审批/断线/重启可恢复 |
| P1 | 实际连接器与协作采用闭环 | 形成真实数据与重复使用 | 一条真实读取链路及确认/采用流程通过验收 |
| P1 | 评测、依赖锁、观测与模块提取 | 给能力和维护成本提供证据 | 固定质量报告、可复现安装、关键事务集中 |
| P2 | PostgreSQL、独立 Worker、pgvector 索引 | 满足并发、恢复和检索规模 | 实测门槛触发后迁移，完成数据校验与恢复演练 |
| P2 | 更复杂的图检索、事件触发、多 Agent 并行 | 提高已证明的复杂任务效果 | holdout 显示收益，成本和错误率不恶化 |

## 5. 目标架构

继续使用 Python/FastAPI、React/TypeScript 和现有 OpenAI Agents SDK。先形成模块化单体，模块拥有领域规则与小接口，不把每个模块拆成独立网络服务。

```text
React：Workspace / Tasks / Knowledge / Collaboration / Admin
                         |
FastAPI：认证、输入校验、授权、命令和查询入口
                         |
       +-----------------+------------------+
       |                 |                  |
 Task/Review 模块   Memory Governance   Automation 模块
 唯一任务事实       版本/来源/共享审核     规则/时间/触发记录
       |                 |                  |
       +------------- Agent Runtime <-------+
                     Plan / Run / Node
                     Session / Recovery
                      |              |
                ContextAssembler  ToolGateway
                授权记忆与快照     Native / O2 / MCP
                      |              |
                      +------- Server / Local Runner
                                      |
                       封存产物 -> Task Review
                                      |
                         显式捕获 -> Memory Review

持久化：先 SQLite + 可重建投影；触发规模门槛后 PostgreSQL
后台执行：先一个进程内协调器；迁移后独立 Worker
观测：Run/Event/Audit/Usage，脱敏 trace 关联，不作为业务真相
```

依赖方向保持单向：Automation 创建 Runtime 命令；Runtime 使用工具和上下文；Memory 学习消费已完成事件；候选记忆不会反过来控制正在执行的权限或任务状态。

事实权威分工：Task/Review 管交付；Run/Node 管执行；Memory/Review 管长期知识；Source/Artifact 管证据；Schedule 管未来触发。项目摘要、图、检索索引和仪表盘都是投影，不能独立修改事实。

## 6. 自动查询与任务调度的完整设计

### 6.1 三种触发，统一进入已有 Runtime

1. 手动查询：显式 Skill 或现有聊天工作流。
2. 定时巡检：Schedule 到点产生一次触发记录，再通过已有权限与 Runtime admission 创建 Run。
3. 变更触发：阶段 5 先仅消费本地已提交的 Task/Review 变更，合并短时间内的重复变化；外部 webhook 在真实连接器支持并验收后才启用。

Agent 队列仍是只读投影。不能把“任务排在 ready”解释为用户已授权自动执行。任务执行需要 Task 状态、依赖、分配、现有 write 门禁和明确命令全部满足。

配置名需要明确区分：`AGENTMESH_AGENT_RUNTIME=v2` 表示现有 SDK Runtime；新可执行规划仍使用 `orchestration_version=v1`。本方案不会恢复已退役的 research-v2/research-v3 writer。

### 6.2 复用并扩展定时定义

扩展 `ScheduledAgentTaskDefinition`，而非另建一套重复定时入口：

- 增加显式契约版本、workspace/project、owner、template_id、expected_version。
- 仅接受五段 cron、IANA 时区；默认 `Asia/Shanghai`，最小频率 5 分钟。
- 新增 server-derived `next_run_at`、最近成功/失败和可执行状态；UTC 存储，按配置时区显示。
- 项目巡检定义由具备有效 `manage_project_tasks` 权限的成员或管理员创建，执行身份不能由普通请求伪造。只读巡检不要求 Task mutation 门禁为 write；用户确认后续任务动作时仍须满足该门禁。
- 固定 `misfire=coalesce_latest`、`overlap=skip`：停机后每个定义只补最新一次，不重放所有错过的周期；上一轮未结束则记录 skipped。
- cron 的日/月与星期使用明确的标准 OR 语义；DST 跳过不存在的本地时间，同一本地槽位在回拨时最多执行一次，唯一身份包含规范化时区和本地槽位。
- 日历计算使用 [croniter](https://github.com/pallets-eco/croniter)，按官方建议输入带时区 datetime；上述 misfire、重复时段和最小频率由业务契约和固定时间测试约束。
- 旧定义保持可读，标为 `legacy_schedule_unvalidated`，不因历史 `enabled=true` 自动执行；用户重新选择项目、模板并保存有效定义后才可运行。

第一期 Schedule 只允许这三个模板和只读工具。对不满足 SDK Runtime、模型或权限条件的定义显示 blocked 及原因，不偷偷退回模拟或 legacy 执行。

### 6.3 触发记录与执行幂等

新增 `ScheduledOccurrenceV1` 记录一次时间槽的触发事实，冻结 definition/version、计划时间、project/owner、Run ID、预算；执行状态和摘要投影来自既有 Run。唯一键为定义 ID、触发种类和规范化槽位；版本在记录内冻结，但不作为允许重跑同一墙钟槽的条件，避免编辑配置后重复执行 DST 回拨槽。手动命令使用独立的 actor/command 身份。

同一事务内写入 occurrence、Run 和现有 dispatch receipt，并推进 `next_run_at`。`ScheduledOccurrence` 记录触发归属，已有 Runtime dispatch 是执行队列，不再维护第二套 Run 状态。数据库领取事务不覆盖模型或网络调用。

启动时恢复已提交 dispatch；不能仅依靠 `asyncio.create_task()` 表示任务已交付。SQLite 阶段只支持单应用进程；PostgreSQL 后用行级 claim 和 lease 支持多个 Worker。

初始只读巡检默认预算：最多 8 次模型轮次、12 次工具调用、总 usage 32k tokens、执行 deadline 10 分钟，每个定义最多一轮活跃执行。创建页显示预算，运行中实时累计，耗尽进入 partial/failed 并显示原因。费用只在 Provider 有有效价格映射时估算，不伪造金额。

瞬时读取故障最多 3 次尝试，间隔 5s、30s，尊重 `Retry-After`；读取幂等键相同，attempt 独立。鉴权失败、无权限、非法输入和取消不自动重试。后续写工具若调用结果未知，进入 indeterminate 并对账，不能盲目重放。

### 6.4 三个模板的结果契约

- 每日进展：上次成功巡检至本次快照之间的 Task/Review 变化；明确列出完成、重新打开、阻塞和待审核。
- 阻塞/逾期：按现有依赖图、交付阶段、阻塞原因和 due_at 计算；“长期未更新”使用可见 Task 的更新时间，不推断人员怠工。
- 待审核：查询用户实际可见的 Task Review/Memory Review 与分配给本人的待决项，给出可操作链接。

输出结构至少包括 snapshot_at、source_watermarks、changes、blockers、pending_reviews、recommendations、missing_data、actual_providers、evidence_refs。LLM 摘要必须由这些结构化证据支持；无变化返回 no_change，无材料返回 insufficient_evidence。

规则产生候选行动，例如“生成调研”“确认负责人”“发起 Task Review”；行动由用户点击后调用现有命令。后台不能替用户分配任务、完成 Task 或采纳团队记忆。

### 6.5 通知、暂停与失败可见性

先使用已有 Inbox，不引入邮件或 IM 发送平台。通知面向定义 owner 或预先授权的项目受众；共享巡检禁止将 owner 的私有记忆混入报告。按规范化结果 hash 去重，变化才通知，24 小时内同一风险最多一次；手动重跑仍留记录。

暂停定义立即阻止新调度，并取消尚未开始的 occurrence；已运行任务遵守取消命令与工具边界。用户离职、项目权限撤销、模型失效或工具 grant 变化时，下次触发和恢复均重新检查。结果分享时再检查当前权限。

修正当前 research drain 的逐条 `except Exception: continue`：每个请求记录脱敏错误码、attempt、next_retry_at 和最终 outcome。单项失败不阻塞其他请求，也不能让 worker 状态显示“无错误”却丢失失败证据。

协作市场的内存 `seen` 改为持久去重：fingerprint 包含需求内容 hash、帮助者知识版本、匹配策略/模型版本和授权版本。新经验或权限变化必须重新评估；失败不会永久标为已处理。worker 领取人数与帖子分页，停止每轮全量加载。

## 7. 真实查询与 Provider 契约

沿用现有 metadata，增加统一的类型化结果投影：requested_provider、actual_provider、data_mode、outcome、evidence_refs、observed_at、source_version、latency、usage、error_code 和 fallback_reason。

`data_mode` 区分 real、demo、derived；`outcome` 区分 success、no_change、insufficient_evidence、blocked、failed、indeterminate。成功不能仅由 HTTP 200、records 非空或 LLM 输出文本判定。

生产查询的规则：

1. 本地真实 Task/Review 查询属于 real，可在外部 Provider 不可用时继续巡检。
2. MockAcquisitionAgent、固定 local_metrics 和演示 seed 属于 demo；只有显式 demo/test 路径可用。
3. 外部查询失败可保留旧资料并标记其观察时间与过期状态；不能换固定样本后报告当前查询成功。
4. 缺乏证据不能完成 evidence-required 节点、写事实、参与真实成功率或生成已确认团队知识。
5. Provider readiness 需区分 configured、reachable、authorized 和最近一次实际成功。状态检测不能被当作业务 smoke。
6. 请求、模型、工具和结果身份可审计，原始密钥、prompt 和业务正文不进入普通日志。

为 chat、data query、research dispatch、Runtime Tool 和前端 Presenter 共用结果投影。测试覆盖无配置、超时、401/403、空返回、内容风险、部分证据、错误格式和 fallback，避免各入口自行定义“成功”。

## 8. 出色记忆系统的设计

### 8.1 四类记忆与唯一治理权威

| 类型 | 内容 | 使用方法 |
| --- | --- | --- |
| 工作状态 | 当前目标、节点、审批、待决问题、工具结果 | 属于 Run/Session，支持恢复，不复制成第二套任务状态 |
| 事件记忆 | 谁在何时做了什么、会议记录、执行经过 | 按来源与时间检索，可回查原文 |
| 事实记忆 | 负责人、项目约束、有效决策、接口口径、个人偏好 | 按实体/关系及有效时间检索，支持更新与冲突 |
| 过程记忆 | 已验证方法、前置条件、失败原因、验证方法 | 在匹配任务中检索，不直接成为可执行 Skill |

长期载荷继续附着在既有 Personal/Project/Team Memory 身份上，由 AgentMesh 管 scope、版本、审核与生命周期。外部记忆库最多做检索 Adapter。

新增可选 `MemoryFactV1`：subject_type/id、predicate、value、observed_at、valid_from/valid_to、时间精度、证据身份/hash、来源类别和 conflict_group。事实的“有效时间”和系统“观察到它的时间”分开，解决迟到资料与历史查询。

新增 `ProcedureMemoryV1`：适用目标、前置条件、工具/环境版本、建议步骤、验证条件、成功/失败 Run 引用和人工确认。只有通过验证和适用性检查的经验才能用于自动上下文；“模型自评成功”不等于已验证。

新载荷使用新的 canonical hash 契约，旧 Memory、Source 和使用回执不重新计算 hash。索引、实体链接、冲突组和向量是可重建投影，不成为新的事实权威。

### 8.2 写入：来源优先，抽取受控

明确允许三种写入：用户显式记住；授权文档/连接器观察产生候选；已验收任务被显式捕获为经验。普通自然聊天不会自动共享。

异步抽取链路：已持久化来源 → 规范化实体 → 提取候选事实/事件 → 逐条检查出处 → 去重/冲突 → 私有候选或团队候选 → 现有审核/激活规则 → 索引更新。

新增持久 `MemoryLearningJobV1`，以 source_id/version/hash 和 extraction_schema_version 为幂等键；保存 attempt、input identity、状态与安全错误码。只能引用真实持久化 Span/Artifact/Source，不能为旧数据补造来源。晚提交时重检来源版本、删除墓碑与授权，防止资料撤回后被抽取任务复活。

自动抽取不把模型 confidence 当真值概率。来源类别区分人类确认、系统观察、模型推断；推断只能作为候选建议。后台抽取有独立 token cap 和暂停入口，不阻塞当前对话。

### 8.3 更新、冲突与时间

实体优先复用 Project、Task、User 的真实 ID；没有 ID 的术语使用项目内规范名与人工可校正 alias。不能用名称相似自动合并两个人或跨项目事实。

事实具有单值/多值谓词约束，例如“当前负责人”通常单值，“参与人”多值。仅在同主体、同谓词、有效区间重叠且值不兼容时形成冲突。来源较新不自动胜出；人类确认、权威系统观察和来源质量必须可见。

团队纠正沿用新候选与 supersedes/独立 Memory Review；个人纠正限定 owner 权限。未决冲突按现有 disputed 规则排除自动注入，查询仍可展示冲突双方和待确认项。

对“现在”“截至某日”和“某段期间”的查询使用不同时间条件。事实载荷支持一组经过确认的历史有效区间；修订时将必要历史事实保留在新的可用版本中。历史问题使用当前治理合格版本中的过去区间，不重新注入 deprecated/expired/archived 的旧 Memory；原版本仅作授权历史回查。状态失效与事实历史有效期是两个维度。

### 8.4 检索与上下文组装

采用分层路由：当前状态/统计/依赖走 Task/Review SQL；明确事实走实体、谓词、时间；决策和经验走 Memory 检索；外部未知信息才调用读取工具。模型不从长聊天里重新猜任务完成数。

Memory 检索顺序：权限/生命周期/有效时间过滤 → 中文 FTS 与可选向量召回 → RRF 融合去重 → 来源与时间检查 → 按查询类别重排 → 冻结版本/引用 → 安全与预算 → 模型上下文交付 → 使用回执。

先使用已有 FTS、中文分词/bigram 与可选 embedding。reranker 不是初始必需服务；只有固定检索 holdout 显示 top-k 错排是主因、效果提升且耗时达标时再引入。

在现有 `MemoryContextService` 内形成统一 ContextAssembler 能力，融合受限核心偏好、当前目标、授权项目事实、近期完整 Session、检索命中和工具输出。复用既有治理，不建立可以绕过它的第二个 context 服务。

预算同时约束条数、完整渲染字符数和 model-aware token 估计；Provider 无 tokenizer 时使用中文/JSON 的保守估计并报告估计方式。标题、引用、元数据和工具 schema 都占预算，不能仅限制摘要正文。

召回不等于使用。只有最终安全、授权与模型交付通过的精确 Memory 版本才能记使用回执；prepared、quarantined、withheld、budget_dropped 和 delivered 在 UI 中明确区分。

### 8.5 遗忘、撤回与知识衰减

用户可删除本人记忆、撤回来源或关闭学习。同步写失效/墓碑阻断新查询，异步清理向量、全文投影、摘要和派生缓存；派生记录按 lineage 失效，晚到 job 不得复活。

forget 命令限当前用户自己的私有记忆。已共享团队知识的删除/修订遵守 Memory governance 权限和审核，不能因最初由本人创建就绕过团队规则；来源撤回也必须先验证来源操作权限，再对可证明的派生链执行失效。

项目进展和外部问题状态有来源水位与新鲜度期限；期限依据连接器及数据类型配置。稳定规范与决策不因访问少就删除，超出复核期只提示复核。不能把“被常用”直接等同于“正确”。

遗忘只能阻止将来使用，无法撤回已交付给用户、Provider 或已有产物的内容。历史审计与备份按明确保留政策处理，产品必须说明删除范围与预计清理时间。

## 9. 项目同步、问题关联与知识图

### 9.1 单一任务事实

项目进度继续来自 Task 的交付阶段、依赖、Run 与 Review。外部工单读取保存为 Source/观察结果；映射到本地 Task 的状态变更必须带版本和明确命令，不在两个系统长期自动双向写入。

项目“问题”第一期使用现有 Task 的阻塞原因、相关证据和关联任务展示；不另建一套 Issue 状态机。需要独立问题处理流程时，以真实使用数据再决定领域扩展。

### 9.2 连接器最小契约

复用 Native/O2/MCP ToolGateway，第一批只完成一个经过授权的真实项目资料或问题状态读取链路。没有企业凭证时使用用户导入文档和本地 Task，保持产品可用。

连接器保存稳定 external_id、source_version/hash、observed_at、同步游标及可见范围。分页和增量读取；来源删除/权限变化会失效本地投影；全量回补限速且可取消。MCP 协议版本按双方协商，不假设新扩展在现有企业网关可用。

新增 `ConnectorSyncCursorV1` 仅记录该连接器在项目内的增量水位、近期结果和错误，凭据继续在已有服务端配置/宿主机 keyring，不进入 cursor、前端或 Runner envelope。

### 9.3 轻量关系检索

复用 MemoryRelation 与 Task 依赖/父子图，增加受控关系类型：relates_to、supports、contradicts、supersedes、caused_by。关系携带来源与版本，自动推测的边必须标为候选，不能当作确定因果。

支持从“一个阻塞”沿 Task → 决策 → 证据 → 经验展开，初始最多两跳，每次扩展独立执行可见性检查、数量限制和预算。共享答案的采用不授予原始个人记忆读取权。

先用关系表与可重建投影，不引入 Neo4j。只有多跳问题在冻结 holdout 上显著失败、关系表方案优化后仍不能满足 p95 时，再比较独立图数据库的收益。

### 9.4 代答与授权闭环

新增小型 `DelegatedQueryV1`，持久保存 requester/target、project、问题与版本、状态、授权版本、确认 Inbox ID、答案产物、引用和采用命令回执。状态为 pending、awaiting_confirm、answered、insufficient_evidence、blocked、denied、failed；不另建 Runtime。已有代答方法执行模型合成，结果写现有 Artifact/Source，query 记录使用户在审批后或重启后仍能找回结果。

发起、确认、恢复与交付时检查双方当前身份、项目范围和有效 consent。敏感命中仍须 target 确认；只有请求方和回答方能读取该 query 的受限投影。引用标题与链接也需检查可暴露范围，不能仅过滤正文。

当前 scout 会调用 `grant_consent` 后自动代答。改为用户在加入市场时明确选择授权策略，显式撤销优先，scout 不得重新授予已撤销授权；需要再次授权时由用户操作。默认答复只交付请求方，发布项目摘要或采用为共享候选是另外的明确动作。

没有 LLM 或没有可用证据的代答返回 blocked/insufficient_evidence 投影，不用“已归纳”模板宣称真正解决问题。采用只记录已交付答案与血缘，不授予原始记忆访问权，也不自动产生已审核团队知识。

## 10. Runtime、工具与 Local Runner

### 10.1 复用 SDK，不同时替换编排框架

保留锁定的 `openai-agents==0.21.1`，SDK 升级独立成 PR，在现有企业 Chat Completions/JSON-mode 网关下验兼容。Session、工具审批与 RunState 使用 SDK 标准接口，业务授权和执行状态由 AgentMesh 保持权威。[官方 Sessions](https://openai.github.io/openai-agents-python/sessions/)与[审批恢复文档](https://openai.github.io/openai-agents-python/human_in_the_loop/)提供对应接口。

不同时引入 LangGraph/CrewAI/AutoGen 来重写当前 DAG；从成熟实现借机制即可，见第 18 节。工具只能看请求范围的能力，Planner 相关性不授予执行权限；节点开始、恢复、调用前重检 grant。

### 10.2 结构化 Session 与压缩

Server 与 Runner 统一完整消息单元，保留 user/assistant、tool call/result 的身份和配对。Session 有单一写入归属、版本比较和幂等提交；Runner 不另建用户长期记忆权威。

替换固定“最近 20 项”的切分策略：按完整交互单元保留近期上下文，工具调用和结果不可从中间切断。摘要保存目标、约束、已确定决策、未决事项和来源指针；不得把摘要中的推断提升为新事实。压缩发生在可安全提交的时点，CAS 防止覆盖新消息。

新增版本化 ContextSnapshot，冻结输入、计划/Skill 身份、适用记忆 ID/version/hash、引用和预算。完整正文仅存在授权执行通道与存储，Audit/trace 只存身份和安全元数据。

### 10.3 故障恢复与审批

已提交节点结果复用；未执行节点重新领取；外部副作用结果不明的节点对账或人工处理。投递是至少一次，数据库结果按幂等提交，外部恰好一次依赖 Provider 业务幂等支持。

SDK 审批中断保存可信 RunState 和 Session version；UI 只提交不透明决策 ID，不能提交替换后的完整状态、工具参数或授权。恢复时重检审核人、用户、工具 grant、节点版本和有效 lease。

Local Runner 保留本地环境和受限文件读取；掉线后显示排队/失联/等待恢复，不能擅自切到服务器改变数据边界。旧 lease 的事件或完成请求不能污染新执行。

远程 Memory 使用回执由实际模型输入交付事件提交 snapshot hash，云端校验并幂等记账；云端完成检索只算 prepared。历史 V1 回执与 hash 保持原样，新远程行为使用版本化契约。

### 10.4 工具质量与副作用

统一 Native/O2/MCP/Runner 的输入 schema、授权、超时、取消、输出大小、风险分类、实际 Provider 和 claim/outcome。读取工具先上线，写工具要求幂等、状态查询和对账能力；无法对账的写操作不进入后台自动执行。

任意 shell、代码执行和文件写入需要独立的授权目录、操作边界与 OS/容器隔离设计。目录白名单或正则过滤不能被宣称为沙箱，本次核心交付不以这些能力为前提。

## 11. 工程架构与持久化优化

### 11.1 按领域事务提取深模块

从巨型 Store 提取聚合级 Repository Interface，先聚焦 Runtime、Memory、Task；Interface 表达一次可检查的业务原子操作，Implementation 隐藏记录、索引和事务细节。SQLite 与后续 PostgreSQL 是相同 Seam 上的不同 Adapter。

禁止按每张表机械建 CRUD 包，禁止把 479 个 Store 方法原样搬成一个大 Protocol。领取 Run、提交节点结果、接受修订、捕获审核产物等跨表操作仍是一笔领域事务，不能由路由串联几次独立提交。

Runtime 按已有职责提取 planning、dispatch/recovery、execution、context、output projection；models 按 Runtime/Task/Memory 契约分组，保留兼容 import。每次提取随一个实际纵向功能完成，验证行为不变，不做无收益的全仓格式重排。

预计核心交付涉及 8 个以上文件、约 30–50 个模块及测试目标；新增一个 Automation 模块，但阶段 1–5 不增加独立网络服务。改动以独立 PR 分批合并，避免一批大重构掩盖行为变化。

### 11.2 SQLite 阶段

保留单应用进程，优化 SQL 过滤、分页、专用索引和投影；禁止列表查询每次 hydrate 整个 records collection。重用现有事务与 dispatch，不假设设置 WAL 就能支持多进程产品运行。

持久文档解析必须保存可恢复输入身份或受控 staging 文件，带版本/hash；只存 Job ID 而把输入留在内存 Future 里，无法可靠恢复。导入、抽取和索引由同一进程内协调器限制并发及队列容量。

### 11.3 PostgreSQL 启动条件

任一条件成立并有实际使用需求时启动阶段 6：需要多个 Worker/应用进程；优化后写锁等待或 Task/检索查询持续超出验收门槛；长期积压超过调度 SLA；需要组织提供的 PITR/高可用恢复能力。只因“百人团队”或源码很大，不直接迁库。

采用 PostgreSQL、SQLAlchemy Core 2.x、Psycopg 3、Alembic 和可选 pgvector。SQLAlchemy 具体 minor 固定到迁移验收版本，不以追逐最新版本为目标。[Core](https://docs.sqlalchemy.org/en/20/core/)提供 SQL/事务抽象，[Alembic](https://alembic.sqlalchemy.org/en/latest/tutorial.html)负责版本迁移。

数据库迁移顺序：先完成领域 Interface；SQLite 内增量建立关系表/投影与回填校验；再停写备份、全量迁入 PostgreSQL、校验后切换。数据库间不长期双写。低频历史集合可保留 JSONB 解码，不能遗漏旧 Run、审批、使用回执和 Runner lease。

校验行数、ID、版本、时间、canonical hash、引用闭合、权限结果与 API 行为；迁移前后运行相同 Repository 合同。PostgreSQL 作业领取使用短事务与行锁，`SKIP LOCKED` 只用于领取队列，不用于一般事实查询。[官方 SELECT 文档](https://www.postgresql.org/docs/current/sql-select.html)说明其队列适用性及非一致读取限制。

### 11.4 向量、中文与容量

当前 `embedding.py` 硬编码 4096 维。pgvector 的 HNSW `vector` 支持至 2000 维、`halfvec` 至 4000 维，因此现有 4096 维不能直接建立这些常规 HNSW 索引。[pgvector 官方说明](https://github.com/pgvector/pgvector)。

迁移初期保留完整向量，先在授权范围内精确检索。若 50k/100k 记录下 p95 超限，采用 binary quantization 的 HNSW 候选召回并用完整向量重排；与精确检索相比 Recall@8 达到 95% 才启用，否则维持精确检索。不得直接截断旧向量、混用模型空间或假设查询 WHERE 能解决所有 ANN 权限与召回问题。

索引 signature 包含模型、维度、分块和归一化版本；新模型建独立投影并重嵌入。中文 FTS 不用 PostgreSQL 英文分词直接替代，保留可验证的中文 token/bigram 和倒排投影，再与向量融合。

## 12. 技术选型与维护成本

| 技术 | 决策与阶段 | 用户收益 | 维护责任 |
| --- | --- | --- | --- |
| Python/FastAPI、React/Vite | 保留 | 延续已存在的功能和团队熟悉的栈 | 后端/前端负责人 |
| OpenAI Agents SDK | 保留，版本升级独立验收 | Session、工具调用、审批恢复 | Runtime 负责人维护网关合同 |
| croniter + Python zoneinfo | 阶段 2 新增 | 有时区、可验证的定时查询 | Automation 负责人维护时间语义测试 |
| uv + uv.lock | 阶段 1 引入开发/CI 锁定流程 | 可复现依赖，减少安装漂移 | 工程负责人维护锁与 Python 3.12/3.13 验证 |
| OpenTelemetry Python | 阶段 4，默认本地出口 | 关联模型、工具、Runner 和队列耗时 | 平台负责人维护脱敏、保留与采样 |
| PostgreSQL/SQLAlchemy/Psycopg/Alembic | 阶段 6，门槛触发 | 并发 Worker、数据恢复与事务索引 | 平台负责人负责备份恢复、迁移与升级 |
| pgvector | 阶段 6 按检索需要启用 | 更大规模语义检索 | 记忆负责人维护索引 signature 与召回报告 |
| LangGraph、Letta、Mem0/Zep 服务 | 不作为第二套 Runtime/Memory 权威引入 | 借用成熟机制，避免额外运维 | 不新增服务账号与迁移负担 |
| Redis/Celery、Temporal、Kafka、Kubernetes、Neo4j | 当前不引入 | 当前单队列/关系表已能满足核心闭环 | 有实测需求才另行决策 |
| 第二种后端语言/新的前端框架 | 不引入 | 保持交付与排障简单 | 不新增运行环境 |

依赖锁使用 [uv 官方 locking/sync](https://docs.astral.sh/uv/concepts/projects/sync/)机制，初次锁定优先复现已验证版本，不顺便升级所有依赖。项目版本与 SDK 版本不得按部署时的“latest”漂移。

OTel 只导出身份、耗时、状态、token 和安全错误码，默认不导出 prompt/记忆/文件正文。GenAI 约定已迁到[独立官方仓库](https://github.com/open-telemetry/semantic-conventions-genai)，接入时固定版本，不依赖旧文档路径或不稳定字段。

## 13. 前端与操作体验

复用现有页面，不另起一套“自动化中心”与“记忆中心”导航。

- Tasks：项目状态、依赖、阻塞与审核；增加三个巡检模板的启停、下次运行、最近结果、失败及确认行动。
- Workspace：显示实际 Provider、执行位置、引用版本、记忆 prepared/delivered、未知原因和恢复位置；后台完成结果能回到对应线程。
- Knowledge：事实/事件/经验筛选、有效时间、原始来源、冲突、纠正与遗忘；团队审核沿用现有入口。
- Digital Self：可编辑的私有核心偏好、学习开关、最近记住/纠正的内容。
- Collaboration：把代答发起、授权、本人确认、回答和采用变为可达用户流程，保留已存在的 participation。
- Admin：统一有效配置、Provider 最近成功、queue age、worker heartbeat、失败重试、token 与 Runner 健康。

产品标签使用“真实资料”“演示样本”“资料不足”“数据截至某时”；不把 T/M、内部枚举或 hash 作为主要用户提示。开发诊断可在授权详情中展开。普通用户无需学习数据库或编排版本才能理解结果。

SSE 沿用持久事件与 cursor，断线后查询 Run 最终状态并补事件，不能因前端乐观更新把失败显示为完成。新的定时配置必须显示项目、执行身份、频率、工具范围、预算和通知受众。

## 14. Interface、持久实体与配置增量

### 14.1 必要持久实体

核心计划新增四个独立 durable entity：ScheduledOccurrenceV1、MemoryLearningJobV1、ConnectorSyncCursorV1、DelegatedQueryV1。MemoryFact/Procedure 是现有 Memory 的版本化载荷，ContextSnapshot 是现有 Run 的执行载荷，项目洞察是 Run/Artifact 投影。

| 实体 | 为什么不能只改默认值 | Owner | 回退与维护成本 |
| --- | --- | --- | --- |
| ScheduledOccurrence | 必须证明某时间槽是否创建过 Run，防重启重复调度 | Automation | 停新调度，保留记录；维护唯一键、时间与触发合同 |
| MemoryLearningJob | 抽取输入与来源版本须跨重启可恢复，且删除后不能复活 | Memory | 暂停学习不影响查询；维护输入保留、幂等与墓碑 |
| ConnectorSyncCursor | 增量读取必须持久记录水位并识别遗漏/删除 | Connector | 停止同步，显示已有数据时间；维护分页与权限变更 |
| DelegatedQuery | 当前代答只是内存返回值，审批后恢复、结果查询与采用必须有持久身份 | Collaboration | 停新查询，保留已授权结果；维护双方权限、授权撤销与采用幂等 |

现有 dispatch、lease、Run、Inbox、Review、Source 和 Audit 持续复用，不另建通用消息总线、通知状态机或第二套工作流引擎。

### 14.2 公共入口

| 入口 | 行为与一致性 |
| --- | --- |
| 现有 `/api/agents/scheduled-tasks` GET/POST/PATCH | 增加项目、模板、时区、预算、可执行状态；管理员旧操作兼容，项目操作须有效 manage_project_tasks；写入带 command_id/expected_version |
| `POST /api/agents/scheduled-tasks/{id}/run-now` | 明确创建一次受预算约束的 Run，幂等；不修改未来时间槽身份 |
| `GET /api/agents/scheduled-tasks/{id}/runs` | 分页返回授权范围内的触发记录、Run 摘要和失败 |
| 现有 `/api/task-operations/{project_id}` | 增加巡检结果链接和来源水位投影，不改变任务事实 |
| `GET/PATCH /api/memory/preferences` | 当前用户私有学习策略与核心偏好，写入版本化 |
| `POST /api/memory/facts` | 当前用户显式记忆事实；团队候选沿用既有捕获/审核命令 |
| 现有 Memory revisions/lineage | 支持时间/事实载荷和个人 owner 修订，保持团队审核规则 |
| `POST /api/memory/{id}/forget` | 本人私有记忆，返回同步失效结果与清理状态；团队知识继续走治理命令 |
| `POST /api/market/queries`、`GET /api/market/queries/{id}` | 项目内受限代答及可见结果；敏感内容走 target 确认 |
| `GET/PUT /api/market/consents/{peer_id}` | 当前用户管理向指定同事的授权，撤销仅影响将来 |
| `POST /api/market/queries/{id}/adopt` | 显式采用；保留来源和 derived_from，不自动共享私有原文 |

代答确认复用 Inbox 的项目权限/target 专属 action；避免浏览器提交任意 target 身份或完整状态。新入口在对应阶段生成 OpenAPI 与前端类型，全部命令授权由会话推导。

### 14.3 配置

新增 `AGENTMESH_AUTOMATION_MODE=off|observe|execute`，默认 off，非法值 fail closed 到 off。Observe 计算应执行项及预算，不调用模型/业务工具，不产生使用回执或通知；execute 仅运行用户已启用且通过权限条件的定义。

复用 Runtime、Task management、Skill orchestration、Memory context 和现有 Provider 配置。模板策略、预算与 owner 设置存在版本化定义中，不为每个模板增加环境开关。

阶段 6 才增加服务端数据库 URL、独立 Worker 并发与可选 OTLP endpoint。Runner 不接收数据库 credential。旧 market/research worker 开关在迁入协调器时保留兼容映射，同一工作来源只能有一个有效消费者。

## 15. 分阶段交付、依赖与估算

以下工作日是工程投入估计，不包括企业凭据等待、审批与组织验收。每阶段可以独立合并、单独使用和停止继续投入。

| 阶段 | 优先级/投入 | 交付 | 独立验收 |
| --- | --- | --- | --- |
| 1. 可信查询与工程基线 | P0，5–7 日 | Provider 结果语义、demo 隔离、默认探测 mock、依赖锁、三类巡检的手动确定性查询、质量基线 | 未配置外部服务也能查真实本地任务；固定样本不会完成生产查询 |
| 2. 真实自动巡检 | P0，12–16 日 | Schedule 扩展、时间槽与 dispatch 原子提交、三个模板、持久去重、失败重试、预算、Tasks/Inbox 结果 | 到点运行、重启恢复、权限变化、暂停/取消与通知去重全部验证；不依赖后续数据库迁移 |
| 3. 团队项目记忆 | P1，15–20 日 | 事实/事件载荷、时间/冲突、学习 job、纠正/遗忘、统一 ContextAssembler、Knowledge 体验、记忆评测 | SQLite 下记住/更新/回查/忘记可用，团队共享仍独立审核 |
| 4. 可靠执行与 Runner | P1，10–14 日 | 结构化 Session、工具单元压缩、可信审批状态、ContextSnapshot、远程交付回执、恢复与脱敏观测 | 相同 fixture 的 Server/Runner 行为一致；断线、旧 lease、重启审批不污染状态 |
| 5. 同步、关联与复用 | P1，9–12 日 | 一条真实读取连接器、增量游标、关系查询、代答授权/确认/采用、已验证过程记忆、本地变更触发 | 材料导入与来源回查可用；真实 Provider smoke 单独计；第二次任务可复用经验 |
| 6. 规模化持久层 | P2，14–20 日，仅门槛触发 | PostgreSQL、迁移与校验、独立 Worker、索引、备份恢复 | 原有行为合同与 row/hash parity；并发 claim 和恢复演练通过 |

阶段 1 可交付手动巡检，不等待阶段 2。阶段 2 使用现有单进程 SDK Runtime，不等待阶段 4 的 Runner 或阶段 6。阶段 3 显式来源写入可用，学习错误不会影响现有 Task。阶段 5 没有企业凭据时导入/本地变更/代答闭环仍可用，外部连接器必须保持 blocked，不能通过模拟宣布整项真实集成完成。

先保留并审查现有 Local Runner 工作区，不覆盖他人改动。实现采用按阶段分支与小 PR；一次 PR 只处理一条纵向行为或一次领域模块提取，避免在业务变更中同时升级框架。

## 16. 测试、评测与发布门槛

### 16.1 自动化的确定性验收

固定时钟、临时数据库和 ScriptedModel/Tool，覆盖：

- 正常触发、手动运行、定义修改、非法 cron、时区错误、DST、停机补最新一次和重叠跳过。
- 调度提交前/后崩溃、同一槽重复领取、权限撤销、停用用户、项目删除、暂停/取消。
- Provider 无配置/401/403/超时/空结果/样本/风险内容/部分证据，准确显示 outcome。
- 读取重试、预算耗尽、无变化、变化 hash 去重、来源水位落后和 Inbox 受众授权。
- Scheduler/Runtime/worker 模块正常启停，不只测试 drain step；失败有持久记录。
- 市场保持 participation 但撤销 consent 后不得被 scout 重新授权；代答高敏确认、结果重启恢复、受众范围和重复采用保持正确。

一次槽位最多对应一个 Run；重复回传不重复通知。不能把这个保证宣传为所有外部副作用恰好一次。

### 16.2 记忆与项目质量评测

建立 120 个冻结项目 memory case：事实提取、跨会话、多版本更新、历史时间、冲突/未知、撤回/权限各 20 个。另设 30 个巡检 case 和 24 个两次执行的过程复用轨迹。版本化 fixture、expected evidence、时间、角色与权限，生成样例和评分样例分开。

比较无长期记忆、近期历史+摘要、现有 FTS/向量+治理、增强记忆四组；固定模型、任务、工具和预算，单独统计后台抽取成本。借用 [LongMemEval](https://github.com/xiaowu0162/LongMemEval) 的提取、多会话、知识更新、时间与未知五类评测；用 [LongMemEval-V2](https://github.com/xiaowu0162/LongMemEval-V2) 对照任务轨迹。公开 benchmark 与真实项目完成率分别报告。

以下为建议发布目标，尚未实测，不代表当前成绩：

| 指标 | 门槛 |
| --- | --- |
| 权限/来源/hash/版本/撤回硬断言 | 全部通过；跨用户泄漏与撤回后自动复活为 0 |
| Mock 冒充真实成功 | 0；所有 demo 结果可识别，不能完成 evidence-required 任务 |
| 时间槽去重与故障恢复 | 全部故障注入 case 通过 |
| 调度启动延迟 | 在已证明容量范围内 p95 ≤60s；外部等待与实际执行耗时分开 |
| 120-case 有证据答案正确率 | ≥85%，且较现有基线提升至少 10 个百分点 |
| 事实更新/历史时间正确率 | 两类分别 ≥90% |
| 无证据时正确报告未知 | ≥95% |
| 确定性进度/阻塞/待审核规则 | 固定 case 全部正确，统计不由 LLM 计算 |
| 过程复用重复错误率 | 比无过程记忆基线下降 ≥30%，报告绝对错误数 |
| Task/运营查询 | 10k Tasks、50k 事件规模下 p95 ≤500ms，沿用现有容量口径 |
| 授权检索 | 50k 记录、10 并发，端到端 p95 ≤1s；DB/embedding/rerank 分别报告 |
| 在线 token | 不超过对应基线预算的 1.25 倍，后台成本独立公开 |

若当前基线已接近上限，相对提升门槛可依据错误分布和置信区间调整并记录 ADR；不得修改正确答案或过滤失败样例以达标。真实模型先跑 24 个代表 case，单批总 token 上限 500,000，再依据报告安排下一批。

### 16.3 工程检查与人工验收

每个 PR 运行适合变更的测试；阶段结束运行以下现有命令：

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest
npm --prefix agentmesh-demo run api:types
npm --prefix agentmesh-demo test
npm --prefix agentmesh-demo run build
npm --prefix agentmesh-demo run test:e2e
```

阶段 1 修复标准 pytest 的宿主机 CLI 探测隔离，CI 不依赖真实 OAuth/O2/LLM。真实 smoke 使用专门发布命令/数据集，不混进单元测试。E2E 验证产品路径，关键行为不能只靠前端 mock。

新增评测入口为 `eval/run_memory_eval.py` 与 `eval/run_automation_eval.py`，默认 scripted；真实模式显式指定 model、case batch 和 token cap。PostgreSQL 合同使用临时实例，不能连接个人或生产数据库测试。

人工验收顺序：开启每日巡检 → 下一次到点看到真实进展 → 制造阻塞并收到一次通知 → 修复阻塞并看到变化 → 跨会话查询负责人 → 修改负责人并查过去日期 → 撤回来源后再次问 → 确认后续任务 → 审批期间重启 → Runner 断线恢复 → 验收产物 → 提交并独立审核团队经验 → 第二次任务引用该经验。

## 17. 依赖、发布与回退

### 17.1 必要依赖及本轮验证状态

| 依赖 | 用途与凭据 | 本轮状态 |
| --- | --- | --- |
| 已有模型网关 | 回答、摘要、抽取；现有 URL/key/model，地域与数据处理政策沿用企业约束 | 本地 SDK/模拟合同已验证；真实连通和质量未验证 |
| 本地 Task/Review/导入文档 | 最小试点的事实与来源 | 源码及确定性测试已验证，无新账号 |
| O2/MCP/项目资料读取 | 一条真实企业集成；已有登录态、读取 scope 或批准的 API key | `o2 --help` 可用；业务访问未验证，不假设某业务 CLI 已安装 |
| Web/Data Provider | 外部调研或指标读取；只有模板确实需要时启用 | 接口与 mock 路径存在，真实 smoke 未运行 |
| PostgreSQL | 阶段 6 的服务器数据库 credential 与备份位置 | 官方能力已核实；未创建或连接实例 |
| OTLP | 可选观测出口及认证 | 官方约定已核实；默认本地出口无需外部账号 |

阶段 1–2 不要求购买额外记忆服务或消息平台。需要真实企业访问的切片，发布前先核对有效读取授权、数据受众与用量限制；依赖不可用显示 blocked，其余本地闭环继续可用。

### 17.2 灰度与运维

选择一个真实项目、5–15 位成员，第一周只查真实资料和 observe，之后逐项开启三个只读模板。自然聊天私有、共享候选审核、工具权限继续保留；不一次启用全部 Skill/连接器。

记录每次运行的来源新鲜度、结果采用、纠正、误报、失败与成本。观察两周，若没有重复使用、查询更快或同步负担下降的证据，暂停扩大基础设施投入，优先修复来源与产品流程。不会以活跃 Agent 数或记忆条数代替用户价值。

运行告警先在 Admin/Inbox：长期无 heartbeat、queue age 超 SLA、鉴权失败、连续 3 次失败、预算耗尽、遗忘清理积压。负责人可暂停定义、停学习或禁用连接器；生产日志保留与备份策略由平台负责人配置并演练。

### 17.3 迁移与回退

- 新字段与 schema 增量引入，旧记录继续精确解码；历史 hash/receipt 不重写。
- Automation off 停新触发，已运行任务按取消或完成流程收尾；禁止直接删除 pending 状态逃避对账。
- Memory context 回退到 observe/off，学习暂停，保留已有治理与显式查询。遗忘墓碑和已失效状态不能因回退恢复。
- 新 Runner envelope 按 capability/version 分配，旧 Runner 不领取新契约任务。
- PostgreSQL 切换前可继续使用原 SQLite；切换有新写入后使用兼容新数据的版本 roll forward，不能恢复旧 SQLite 丢失新增事实。
- 备份恢复保留删除墓碑、权限撤销与版本关系，恢复后先停止自动注入和调度，完成失效重放再开放。
- 停写备份、导入校验、恢复演练和小项目验收通过后，才扩大范围。

### 17.4 ADR 与维护规则

ADR 0012/0013 的 Memory 治理与使用回执权威、0011/0014 的 Task/Review/队列语义继续成立。定时创建 Run 是独立授权入口，不让 Agent queue 自动调度。

阶段 6 与当前 CONTEXT 的单 SQLite/单进程限制不同，必须在该切片正式更新运行边界；不是暗中改变默认。按检索门槛重开 ADR 0001 的 pgvector 暂缓决定，数据库迁移落实 ADR 0002。新增调度时间语义、真实结果要求及远程交付回执的 ADR。

发布仍遵守既有 Profile/Provider/权限门禁和真实 smoke 要求；自动评测不替代 Task/Memory 的人类审核。

## 18. 与成熟 Agent 项目的能力对齐

本轮核实的是官方资料中的机制，不根据宣传宣称本项目已有同等能力；资料与仓库锁定版本的差异须在实现时通过合同测试确认。

| 参考 | 可迁移机制 | AgentMesh 的选择 |
| --- | --- | --- |
| [OpenAI Agents SDK Sessions](https://openai.github.io/openai-agents-python/sessions/) | 结构化历史、统一 Session Interface | 复用已有 AgentMeshSession，与团队治理上下文合并 |
| [OpenAI SDK Human-in-the-loop](https://openai.github.io/openai-agents-python/human_in_the_loop/) | 持久 RunState、可信存储与恢复授权 | 用现有 Run/Inbox/lease 完成审批恢复 |
| [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) | 线程内 checkpoint 与跨线程知识分开 | Run/Session 与长期 Memory 分开，不增加第二套编排引擎 |
| [Letta Stateful Agents](https://docs.letta.com/v1-sdk/concepts/stateful-agents) | 核心上下文与可检索历史、状态长期保存 | 受限核心偏好+治理记忆；Agent 不可自行扩大共享权限 |
| [LongMemEval](https://github.com/xiaowu0162/LongMemEval)、[V2](https://github.com/xiaowu0162/LongMemEval-V2) | 时间、更新、未知与任务轨迹评测 | 冻结项目 holdout，并与外部 benchmark 分开报告 |

需要达到的能力是长期一致性、受控工具执行、持续任务恢复、事实来源可验证和质量可测。多 Agent 并行不是必需前提；只有独立子任务通过相同权限、预算与结果合同，且实测优于顺序执行时才增加并行。

## 19. 实施交接与第一批 PR

### 19.1 文件目标

| 工作 | 主要目标 |
| --- | --- |
| 可信 Provider | `acquisition.py`、`datasources.py`、`o2.py`、`provider_status.py`、`tool_runtime/`、相关 chat/blackboard/data routes 与前端结果投影 |
| 自动巡检 | 新增 `automation/{contracts,service,scheduler,templates,settings}.py`；扩展 scheduled routes/models；`app.py` lifespan；`marketplace.py` 和 research worker 接入 |
| 长期记忆 | `memory_context/`、`memory_governance/`、`ingestion.py`、Memory routes；新增 `memory_learning/`，事实/关系投影与冻结评测 |
| 可靠 Runtime | `agent_runtime/{service,session,compaction,hooks,trace_processor}.py`；逐步提取 dispatch/recovery/context 职责 |
| Local Runner | `runner_contracts.py`、`runner_executor.py`、`runner_service.py`、`runner_spool.py`、Runner routes 与节点结果合同 |
| 产品体验 | React Tasks、Workspace、Knowledge、Digital Self、Collaboration、Admin 与 generated schema |
| 工程与迁移 | `pyproject.toml`、`uv.lock`、CI、Repository 合同、eval；阶段 6 的 persistence Adapter/Alembic 与恢复工具 |

### 19.2 第一批可独立合并的 PR

1. **真实结果与 demo 隔离**：统一结果投影，生产请求不能用固定样本完成；所有入口展示实际 Provider/未知原因，补确定性合同。
2. **手动项目巡检**：三个模板先从真实 Task/Review 计算，用户手动查询即可受益，报告可回查来源。
3. **定时定义与时间槽提交**：增加有效定义、时区和幂等 occurrence；observe 可查应执行时间，不依赖模型。
4. **Runtime 调度与持久失败**：execute 只创建受限读取 Run；补重启、预算、重试、暂停/取消及 worker 生命周期测试。
5. **Tasks/Inbox 闭环**：启停、最近结果、下一次运行、失败和确认行动；通知去重与权限变化验证。

随后进入阶段 3 的项目事实记忆，再做结构化 Runner 与协作复用。所有 PR 的说明包含具体触发、前后行为、验证结果和回退方式。当前开发修改保留在工作区，尚未创建 Issue、提交代码、合并或部署。

### 19.3 首个开发切片：真实查询与演示隔离

已实现以下行为，复用 `AGENTMESH_DEMO_MODE=1`，不新增服务或运行开关：

- `local_metrics` 和模拟调研只在明确启用演示模式时返回样本。生产模式未配置真实调研源时返回 `no_real_provider_configured`，不会生成固定复盘作为成功回答。
- 数据 API、显式聊天能力、BBS 调研派发和 Runtime ToolGateway 在接收证据时校验资料类型与可用来源；空结果或未标注来源的生产结果不能完成证据查询。
- Provider 合并保留演示属性，不能把样本合并成真实资料；从演示模式切回生产后，历史隔离样本也不能通过人工放行完成查询。
- 新增可选的 `data_mode` / `outcome` 到聊天执行记录，并同步 OpenAPI 类型。前端明确显示演示提示，模型整理成功不会改变样本属性；旧记录显示“未标注”。
- 查询被结果策略拒绝时（未配置、演示禁用、未标注来源、证据不足）写失败任务与安全审计原因，聊天回执记为 failed；后台派发不会反复消费已失败任务。真实来源回退和用户上传文档的生产查询继续可用。

测试与交付边界：新增 18 项后端行为测试和 3 项前端展示测试；使用隔离数据库与模拟 HTTP/模型，未调用真实企业 Provider。已有 Runner 工作区已保留。真实 Provider smoke、标准测试的宿主 CLI 探测隔离、依赖锁定和三个手动巡检模板仍需后续完成；本切片不代表定时任务或长期事实记忆已上线。

验证结果：全量后端 **1918 passed**（沿用已知的 5 条 SWIG 弃用提示），前端 **203 passed**；Ruff、OpenAPI 类型生成、TypeScript/Vite 构建、包体预算与 `git diff --check` 均通过。后端验证显式设置 `AGENTMESH_O2_COMMAND=agentmesh-o2-disabled-for-tests`、`AGENTMESH_O2_RESEARCH_ENABLED=false`、`AGENTMESH_WEB_PROVIDER=`，避免宿主机真实 CLI/调研 Provider 影响结果。

### 19.4 手动巡检与锁定工程基线

已实现 `POST /api/task-operations/{project_id}/inspections` 和 Tasks 内的三个手动入口：每日进展、阻塞/逾期、待审核。规则直接计算真实本地 Task/Review；无需模型或 Task 写入权限，也不变更任何 Task/Memory。查询使用一个 SQLite 读取事务，在该快照内检查当前用户状态、Workspace 和 Project 成员身份。共享报告排除私人聊天任务；记忆审核只显示当前具备有效审核权限的指派审核人的事项。

每日进展使用冻结的 Task/Task Review 命令版本，并读取时间窗口之前的上一版本，因此能识别完成、重新打开和审核驱动的状态变化。缺历史、缺材料、缺依赖或超过查询上限时明确报告数据缺口。已有阻塞不会被误算为新的每日变化；风险仍保留供查看。报告含查询时间、来源水位、具体版本与来源链接。手动报告尚未持久保存为 Run；持久结果与通知属于阶段 2。

标准 pytest 的入口已隔离宿主 O2/Web/Data/LLM 配置，并用带宿主配置的子进程测试验证。Playwright 服务也使用明确的 Provider 隔离设置。新增 `uv.lock`、构建后端配置与 Python 3.12/3.13 CI 矩阵；本地新建隔离环境完成锁定安装，没有升级既有已验证依赖。

浏览器验收发现并修复了 Task 首次读取与创建成功的竞态：未完成的首次查询会被刷新复用，令列表停在创建前的快照。现在先取消旧查询再读取提交后的投影，并用真实 QueryClient 的延迟响应测试复现和验证。同步修正两条过期浏览器断言：普通用户可以管理自身 Runner；Digital Self 有真实今日活动时应显示活动历史。

已完成验证：Python 3.12 与 3.13 全量后端分别 **1933 passed**；前端全量 **208 passed**。Ruff、OpenAPI 类型生成、TypeScript/Vite 构建、包体预算、锁一致性和 diff 检查通过。相关浏览器回归 **19 passed**，参考页面回归 **4 passed**；修正后的单次全量浏览器检查 **78 passed**。新增手动巡检后端合同为 14 项，宿主配置隔离合同为 1 项；阶段 1 的本地代码验收完成，不把脚本/模拟验证称为真实企业联调。

容量基线：10,000 Tasks、50,000 Task/Audit 事件、10,000 Memory 记录、1,000 条已接受团队知识，7 次测量。Task 列表 p95 378.780ms、详情 426.913ms、运营视图 264.548ms、关联选项 200.394ms、Memory FTS 37.867ms，均低于现有 500ms 门槛。结果见 `docs/verification/2026-10-04-stage1-project-operations-benchmark.json`。这是现有查询容量基线，尚未代表新增记忆、自动调度或真实模型质量成绩。

### 19.5 阶段 2 进行中：持久自动巡检

已引入并锁定 croniter 6.2.4，保留原 SDK/框架版本。时间策略使用 IANA 时区和带时区的 cron 迭代，显式使用 DOM/DOW 的 OR 语义。支持五段标准 cron 的数字、列表、范围、步长及月份/星期名称；不支持秒、年份、宏、随机/哈希和 L/# 等扩展。最小墙钟槽间隔为 5 分钟，跨午夜校验考虑实际可匹配的日期，而不会误拒仅周一运行的定义。调度层也限制相邻定时 Run 的实际 UTC 间隔。

春季不存在的墙钟槽跳过，秋季重复槽只采用第一次实际时刻；槽位身份为时区加本地年月日/分钟。旧定义保留 `legacy_schedule_unvalidated`，有效定义通过服务端 owner/Agent 身份、实时项目权限、命令幂等和版本 CAS 更新。配置修改保留事务内最新的运行水位，不能覆盖并发完成的巡检进度。

到期触发在同一事务内提交 occurrence、既有 v1 Run、既有 dispatch 和 next_run。固定补最新一次、重叠跳过；暂停会在配置事务内取消未开始的 Run。启动恢复保留同一个只读 Run，旧 epoch 不能提交结果；结果提交故障还可在同一进程恢复，不靠临时协程表示派发成功。三个模板执行已完成的本地查询内核，不需要模型配置：实际模型/Token 用量为 0，读取次数与冻结工具预算、10 分钟 deadline、最多三次尝试在 Run 上记录。暂未加入 LLM 摘要或企业查询模板。

瞬时读取重试 5/30 秒并尊重 Retry-After；鉴权、输入和预算失败直接终止，错误只记录安全代码。结构化报告保存在 Run，完成状态与 Inbox、结果 hash、派发结算同事务提交。报告只允许创建者在当前项目权限下读取；其他负责人只可查看运行元数据。规范化结果 hash 忽略查询时间和水位；同一风险在 owner/项目范围内 24 小时最多提醒一次，手动重跑仍有独立执行记录。资料不足不会推进每日进展的完整巡检水位。

任务中心新增创建/编辑、显式历史配置绑定、暂停/恢复、立即巡检、分页运行记录和报告；全局 off/observe/execute 状态单独显示。Inbox 提供报告链接。该切片完整 Python 3.12/3.13 回归各 **1988 passed**，前端 **212 passed**，默认关闭模式浏览器 **79 passed**；另以 SDK Runtime + execute 模式通过真实本地记录的自动执行、报告和移动布局闭环。未调用企业 Provider 或真实模型。演示个人 Agent 已在 SQLite 初始化，不再只靠列表回退。

后续边界回归补齐了进程 quiesce 后禁止手动准入、暂停配置仍需可达日历，以及 observe 对当前权限/重叠/UTC 间隔的只读诊断。对应自动化与研究测试共 **71 passed**。冻结巡检评测随后已完成，见 §19.8；其余记忆、Runner 和同步阶段保持未完成状态。

### 19.6 阶段 2 进行中：研究请求持久派发

已有研究请求帖新增版本化派发状态，Task/Thread 继续拥有业务状态，没有建立第二个研究 Runtime 或独立任务队列。手动派发和后台 drain 共用 SQLite 事务领取；每轮默认处理最多 50 条，管理员操作按当前 Workspace 筛选。请求 hash 和 owner/Workspace/Project/Thread 身份冻结；领取和 Provider 返回后重新检查当前用户、项目与请求身份。共享 Project Task 不能通过此兼容路径绕过 Runtime 或 Task Review。

记录 attempt、lease、next_retry_at、安全错误码、证据指针与最终 outcome。瞬时读取最多三次、5/30 秒重试，支持 Retry-After 秒数和 HTTP 日期；401/403、输入和权限失败不重试。单条失败不吞掉其他结果；worker 查询包含数据库持久队列计数和最近安全错误，重启后仍可查看。

进程中断且未产生证据的读取可以重新领取；已有部分证据的中断进入 `indeterminate`，不会默默当作完成，也不会盲目重放多步发布。遗留 fulfillment 尚非整个多记录发布事务，待对账项需人工核查；不宣称该兼容路径已有完整的 exactly-once 发布保证。取消/已结算的业务状态也不会被迟到 Provider 失败覆盖。13 项新增公开服务回归覆盖重启、并发手动/后台领取、权限撤销、读取预算、限流、部分发布和有界扫描。

### 19.7 阶段 2 进行中：市场持久匹配与当前回归

匹配去重不再依赖进程内 seen。每个 helper/信号持久保存 fingerprint、领取、尝试、重试与结果指针；fingerprint 包含需求内容、当前合格知识版本、匹配策略/模型和身份/项目/参与/权限/consent 版本。知识变更、模型变更和撤销授权后会重新评估；非法模型回复不被误缓存为“不匹配”。模型鉴权失败阻断当前配置，其他读取失败按退避再次评估；中断的多步交付进入待对账。

参与者和信号使用持久分页游标；匹配读取上限计算整个 worker tick 的负向判断，停止每轮加载全部用户和帖子。发布信号只读取本人当前合格记录，模型材料各最多 8 条。Scout 不创建任何 standing consent，默认本人确认；原有明确授权仍受撤销和高敏闸门约束。共享匹配帖只包含协作状态，不复制私人代答正文，普通日志也不记录需求或原始异常。重复 participation PUT 不改变授权水位或重复创建确认。

代答主流程的持久 Query/Artifact、授权策略选项、无模型/薄证据结果契约和采用命令仍属于后续阶段，不能把当前兼容模板视为已验证的真实答案质量。

当前完整回归：Python 3.12/3.13 各 **2011 passed**、前端 **212 passed**、浏览器 **79 passed**；Ruff、uv lock、类型生成、构建与 bundle budget 通过。结果记录在 `docs/verification/2026-10-04-stage2-workers-regression.json`。尚未运行企业 Provider 和真实模型评测。

### 19.8 阶段 2 本地验收完成：冻结巡检评测

新增 `eval/automation_cases_v1.json`，固定 30 个 synthetic case，三个模板各 10 个；期望结果预先填写，不从运行输出生成。CLI `eval/run_automation_eval.py` 默认离线，使用临时 SQLite 回放固定 Task、命令历史和 Review，调用公开巡检服务。逐项检查 outcome、变更、阻塞、评审分配、证据身份/版本、缺失诊断和数量；额外检查数据库不变、私聊不进入结果、宿主数据库不被打开。错误期望或重复数据集会返回非零状态。

30/30 通过，模型 Token 为 0，数据集 SHA-256 为 `f479181f3f9153a89d82c943cf061c2d694453fe9f0d40c36bb2dffb5c6573dc`。报告见 `docs/verification/2026-10-04-stage2-automation-evaluation.json`。Python 3.12 对巡检/调度/评测的合并回归为 **75 passed**。该成绩仅代表确定性规则和授权；真实模型质量、企业 Provider 联调与真实试点人工验收保持待完成。阶段 2 的本地开发与确定性验收完成，阶段 3 开始。

### 19.9 阶段 3 首个切片：有来源的事实、过程载荷与时间查询

在现有 Personal/Project/Team Memory 上增加可选事实和过程载荷。新载荷使用新的 canonical hash；没有新载荷的旧内容与 capture/revision 命令 hash 保持兼容。个人显式确认使用本人持久 Document 的版本与 hash，同事务完成命令去重、纠正、旧记录停用、索引和安全审计。查询在授权 SQLite 快照中检查当前 Memory 生命周期与来源，区分有效时间和观察时间、当前/某日/区间及“当时已知”查询；半开区间、日/月精度和 NFC 等价规则均有回归。重叠的不兼容单值事实返回冲突，较新观察不自动胜出；推断和缺失来源不被报告为已确认事实。

已接受 Task Review 可显式捕获事实和过程经验。成功 Run、Review 与 Artifact 引用由服务端冻结，调用者不能自报成功。团队载荷仍需独立 Memory Review；捕获、修订和接受时在既有事务中检查来源与实体。仅修改说明会保留结构化历史；提交新完整区间也可以独立审核后替代原版本。知识详情与候选审核显示有效/记录时间、来源类别、证据与方法的前置/验证条件。

旧摘要、市场上下文和 legacy sharing 暂不把结构化载荷转换为未经时间/冲突检查的自动上下文。这一验证快照中，完整 ContextAssembler、持久学习/遗忘队列、来源墓碑与清理、别名编辑、过程适用性/复用和 120/24-case 评测仍待完成；后续学习/遗忘进展见 19.10。来源 ID/hash 校验也不等于文本语义蕴含证明或真实模型质量成绩。架构见 ADR 0019。

载荷初始切片全量验证：Python 3.12/3.13 各 **2046 passed**、前端 **215 passed**、浏览器 **80 passed**，其中新增浏览器用例通过实际本地上传/事实 API 与详情页验证确认、显示和冲突，零 LLM。Ruff、类型生成、构建与 bundle budget、diff 检查通过。详见 `docs/verification/2026-10-04-stage3-memory-payloads-regression.json`。这是历史快照，后续验证见 19.10–19.12。

### 19.10 阶段 3：持久资料学习与本人遗忘

新增默认 off、用户独立 opt-in 的 Document 学习 job，按真实来源 ID/version/hash/schema 去重，保存 lease epoch、重试、独立每日预算及不退款的尝试预留。复用官方 SDK 和模型工厂，抽取无工具、单轮、输出上限 2,000 token；只有真实 usage 才计已报告成本。来源、身份、项目权限、偏好与模型变更会阻止晚提交。逐字 Span 支持私有候选；用户选择确认后才激活，未知有效期保持未知，模型未确认摘要不会混入记忆。

本人私有记忆 forget 与本人资料 withdrawal 使用版本/幂等命令、同步墓碑和原子索引清理，持久清理队列可重启恢复；数据库屏障阻止旧 worker/raw SQL 复活。新摘要和显式项目分享冻结来源血缘，来源仅变更生命周期版本时仍按相同内容 hash 撤回派生副本。团队记录保留正文和独立治理，已接受转 disputed、候选转 expired，仍允许管理者归档。旧数据无血缘时不补造证明。

Digital Self 可保存私有核心偏好、学习开关与每日上限。Knowledge 可查看学习、原文片段、逐项确认、受限重试和本人遗忘；资料撤回 API 验证上传者权限。偏好尚未接入自动上下文，逐字来源校验不等于事实蕴含证明，删除范围不含已交付内容、团队审核、审计与备份。

完整回归快照：Python 3.12/3.13 各 **2,079**，前端 **217**，E2E **81**；真实本地 API 的偏好/事实/遗忘路径零模型调用。快照后的生命周期版本边界修复通过 **64** 项学习/遗忘/事实测试。OpenAPI、构建/bundle、Ruff、lock 检查通过。见 ADR 0020 和 `docs/verification/2026-10-04-stage3-memory-learning-regression.json`。

阶段 3 仍未完成：完整 ContextAssembler/完整请求预算、别名编辑、过程适用性/复用、120/24-case 评测、授权检索容量及学习运行告警仍待开发。真实 Provider/企业 smoke、语义质量和后续 SDK/连接器验收尚未完成；不能以本次确定性回归代替。

### 19.11 阶段 3：本地 SDK 完整请求预算与记忆交付

在原 MemoryContextService 内接入实际 SDK Model 请求检查，本地流式 Runtime 每轮统计完整指令、Session、工具结果、工具/handoff schema 和输出 schema。审批恢复复用的原 Agent 也受到检查。默认限制 200,000 渲染字符、64,000 输入加输出估算 Token、8,192 输出 Token；无已验证 tokenizer 时明确标记 UTF-8 保守估算及协议预留。超限、无法计量的媒体和隐藏 Provider 上下文会停止请求，不截断工具结构。

核心偏好在 inject 模式用于本人本地 direct/Standard Agent，独立于学习 opt-in；交付时检查版本。自动记忆的使用回执延后到完整请求预算通过的本地模型入口。SDK memory_search 保存私有待交付快照和最终可见输出 hash，下一轮确实包含该输出且通过检查才提交回执。forget 清空待交付正文并保留撤回屏障，数据库阻止晚重建；回执不能把 Provider 响应成功作为既成事实。

提交时复核本人记忆的 scope/归档标记、原生 Document 版本/归属/项目和摘要/分享的冻结父链。无血缘的旧 rollup 不补造证明；父链最多四层并拒绝循环。压缩保留完整并行调用/结果单元和未完成调用，沿用 Session CAS，单轮输出上限 2,000，成功压缩用量单独报告、缺失为 unknown。Workspace 展示最近请求预算决策，并明确估算与实测用量、预算通过与记忆交付的区别。

本切片完整回归：Python 3.12/3.13 各 **2,102**，前端 **218**，E2E **81**；Ruff、OpenAPI、构建/bundle、lock 和 diff 检查通过。见 ADR 0021 和 `docs/verification/2026-10-04-stage3-context-delivery-regression.json`。

完整 ContextAssembler 仍未完成：结构化事实/过程的适用选择、显式查询路由、候选级 prepared/quarantined/withheld/budget_dropped/delivered 投影及预算选择仍待做。远程 Runner、非流式计划/合成请求、审批中的冻结自动上下文、Session 归属/来源归档、失败压缩成本/期限和完整累计成本验收仍需后续切片。别名、120/24-case 评测、检索容量、学习告警和阶段 4–5 保持未完成；本次测试不代表真实 Provider 或语义质量。

### 19.12 阶段 3/4：本地冻结上下文与审批恢复

新增现有 Run 的私有 `RunContextSnapshotV1` 执行载荷，冻结输入 hash、owner/workspace/project/thread/Task、writer generation、计划版本/节点、实际构建 Agent 的 Skill 身份、精确 Memory bundle、核心偏好版本、附加指令和完整请求预算。SDK RunState 只携带快照 ID；快照不进入公开记忆检索或 API 正文，事件只记录身份、hash、数量及安全错误码。

本人本地 direct/Standard 的 inject 执行先准备快照，实际模型请求预算通过后才复核并提交回执。审批恢复先从可信 SDK 状态还原上下文，在领取审批和执行工具之前检查身份、冻结输入、当前授权、来源/记忆生命周期、偏好、模式、Skill/绑定与计划版本；重建 Agent 恢复冻结的附加指令。后续交付重复检查。多次分批审批、新 Runtime 实例恢复、替换输入/项目、owner 停用和旧 writer generation 均有回归。DeepSearch 保留已有计划/证据边界，不新增自动私有记忆注入。

快照的 canonical hash 决定 ID，数据库阻止覆盖准备载荷。forget/来源撤回在同事务清空受影响快照的 bundle、query、偏好与附加指令，并保留撤回屏障；已撤回快照和其忘记的来源不能被晚到写入重建，数据库重开仍成立。Skill 在构建与保存之间被替换、交付前禁用或撤销本人绑定都会阻止旧指令执行，不把新版本身份与旧正文混用。

完整回归快照为 Python 3.12/3.13 各 **2,114**；随后 Skill 竞争边界修复及最终相关回归为两版本各 **193**，含新增三个边界 case。Ruff、diff 检查通过。本切片没有前端或公开 API 契约变化；前端/E2E 的上一完整验证仍见 19.11。详见 ADR 0022 和 `docs/verification/2026-10-04-local-context-snapshot-regression.json`。

这完成本地冻结自动上下文恢复切片，阶段 3/4 尚未整体完成。结构化事实/过程组装、候选状态与预算选择、别名、过程复用、120/24-case 评测、授权检索容量和学习告警继续开发。远程 Runner 的实际交付回执、完整 Session 归属/去重/来源归档、lease fencing、非流式调用预算及累计成本仍待验收。真实 Provider/企业 smoke 和语义质量不以本次确定性测试替代。

### 19.13 阶段 3：授权时间事实进入本地上下文

现有 MemoryContextService 增加首个结构化选择能力。明确的当前项目负责人问题走实体/谓词/时间查询；SDK memory_search 支持有类型的时间查询，项目与项目/Task 主体默认采用当前 Run 的真实 ID，人物和术语必须提供明确 ID。自由研究、历史自然语言和其他未指定项目的问题不被猜成当前事实。

SQL 在有界载荷读取和冲突判断之前应用当前 scope/type/layer 与本人 Agent 绑定。已确认的完整断言、有效/观察时间、来源版本/hash 和引用进入上下文，不混入未选摘要或过程步骤。未知、冲突、隔离和预算不足只提供诊断；完整事实组超出预算时整体放弃，不能裁剪参与者后宣称完整事实。

每次本地模型交付和审批恢复复查冻结的时间查询；Store 在提交使用回执的同一写事务内再次查询，阻止准备后新增冲突或来源变化被遗漏。SDK 工具保留实际完整输出 hash 与 Run 范围来源，完整可见输出进入下一轮模型且预算通过才记录使用。取消 Run 不能交付零命中的诊断快照。混合事实/过程载荷只交付选定事实。

forget 的清理和数据库屏障同时跟踪选中命中与冻结事实候选，即使冲突/未知导致零命中也会清空待交付正文；数据库重开后仍拒绝晚恢复。旧摘要 bundle 不增加空字段，保持既有快照 canonical hash。Pydantic 测试下限明确为 2.13，锁文件仍为原有 69 个包。远程 Runner 在实际交付协议完成前拒绝派发这类事实上下文，也不预记事实使用。

完整回归快照：Python 3.12/3.13 各 **2,132 passed**；最后两项边界修复另通过各 **180** 项相关回归。前端 **218**、结构化记忆/使用/治理浏览器回归 **4**，OpenAPI、构建/bundle、Ruff、offline lock 和 diff 检查通过。详见 ADR 0023 和 `docs/verification/2026-10-04-temporal-fact-context-regression.json`。没有把修复前的全量快照声称为修复后的全量验证。

本切片不代表完整 ContextAssembler：Task/Review 当前状态与统计路由、人工术语 alias、过程适用性与复用、候选级 UI 和跨输入预算选择、120/24-case 评测、检索容量及学习告警仍需完成。来源身份/逐字片段通过不等于语义蕴含、企业联调或真实模型质量达标。

### 19.14 阶段 3：当前 Task/Review SQL 上下文

增加同一 Task operations 权威下的当前状态查询、GET state API 和受既有 grant/policy 约束的 project_state 工具。一次读事务内复核 actor/项目权限、统计当前共享受管理 Task 与关联 Review，并提供指定 Task 版本、直接依赖和活动 Run 数。会话 Task、其他项目和归档对象不混入活动计数；不可访问依赖保留缺失计数，不能据此判定可执行。超过巡检详情上限的 SQL 统计仍完整。

明确的当前项目统计和已关联 Task 状态问题进入这个查询；历史或自由问题不猜成当前状态。结果使用原 ContextBundle/Snapshot 和完整请求预算，不生成第二套任务状态或 Memory 使用回执。审批恢复、工具结果下一轮交付与本地模型请求重新比较冻结结果；统计、Review、依赖、Task 版本或活动 Run 变化会停止旧上下文交付。Task 标题中的危险指令整体隔离，超预算结果整体丢弃并返回有界诊断。

### 19.15 阶段 4：本地模型排队后的准入与真实交付边界

每次通过既有 RequestBudgetModel 的本地请求核验持久 Run、冻结 writer/执行身份、活动 actor/项目、Thread 权限和 deadline；Memory off 也适用。SDK 原子流重试重新检查，不能为已撤权用户继续调用 Provider。容量包装模型先完成预算预检，取得实际 LLM 槽位后再次计量实际请求并检查授权/来源，然后才提交记忆使用和调用模型。task-local gate 隔离并发用户；等待槽位不会提前提交回执，排队期间变化的工具 schema 也会重新计量和拒绝。

这两个切片的完整回归为 Python 3.12/3.13 各 **2,182 passed**；前端 **218**，相关浏览器 **3**，生成类型、构建/bundle、Ruff、offline lock 和 diff 检查通过。浏览器项目巡检与结构化记忆使用实际本地 API，记忆回执展示用例仍采用模拟 Run 投影，均不调用真实 LLM。详见 ADR 0024/0025 与 `docs/verification/2026-10-04-project-state-context-regression.json`。

完整 Session 归属/幂等/来源归档、非流式计划/合成及压缩的完整预算/期限/失败成本、远程 Runner 交付回执和 lease fencing 仍需完成。人工 alias、过程适用性/复用、候选 UI、120/24-case 评测、容量及学习告警继续开发；阶段 3/4 不能据此标记整体完成，真实 Provider 和模型质量仍须单独验收。

### 19.16 阶段 4：本人 Session、写入版本与 Memory 来源血缘

本地 AgentMeshSession 必须绑定已准入 Run 的独立身份。每个读取/修改在同一 SQLite 事务内检查当前 actor/项目/私有 Thread、运行状态/期限和 writer generation；SDK wrapper 不能换成其他执行身份。一个 Thread 的 Session 只有一个活动 Run writer，终态才允许后续 Run 领取；同一 Run 的更高有效 generation 可接管，旧实例被阻断。没有归属证明的非空旧 SDK body 不被静默收养。

Bootstrap 只用调用方提供的消息 ID，从当前持久 ChatMessage 验证 Thread/role 并读取正文，未知/其他会话 ID 使整批失败。SDK append/pop/clear 对比观察版本，单实例操作串行，独立实例不能覆盖新上下文；每次 append 保存仅含 ID/version/hash 的命令回执，同一命令在数据库重开后重放不重复追加。重新构建的 SDK 执行自动找回原 append 命令身份尚未完成。

压缩在模型准入时复核冻结 Session 版本/授权，包括容量排队后的时点，保留完整工具单元、2,000 输出上限和最终 CAS。新增不超过 90 秒且受 Run deadline 限制的外层期限，关闭 SDK retry；失败不覆盖原历史。bootstrap/压缩错误进入已有 Run 终态处理并使用静态错误码。

Session 写入归档实际使用回执和精确匹配的 prepared memory_search 输出对应的 Memory ID/version/hash 血缘；prepared 血缘不计记忆使用。读取、压缩和模型交付复用既有治理/Agent 绑定/原生来源检查，Memory off 也不能复用失效旧工具正文。版本、归属、scope、归档或原生 Document 版本/撤回变化阻止继续读取。摘要保留其历史依赖。本人 forget/原生资料撤回在同一屏障事务清空受影响 Session cache，提升版本，DB trigger 在重开后继续阻止晚恢复。已交付 Chat/产物与审计/备份保留原有政策。

检查点跟进之前的完整快照为 Python 3.12/3.13 各 **2,219 passed**；来源专项 **97**，最后 wrapper/血缘专项 **37**。Ruff 和 diff 检查通过；未改变公开 API/前端契约，沿用 19.15 前端/浏览器快照。此前两套全量各发现一个测试同步失败，分别改为模型开始事件握手和有界较长的排队等待后，已重新通过完整回归。详见 ADR 0026 与 `docs/verification/2026-10-05-owned-session-regression.json`。

Session 审批检查点正在继续开发。任意外部工具的完整来源归档、无 frozen version/hash 的 legacy 来源迁移、SDK restart/replay 自动去重、远程结构化 Session 对齐、压缩失败成本与累计预算仍未完成；不能据此声明阶段 4 完成。

### 19.17 阶段 4：可信的直接会话审批检查点

直接 SDK 暂停在服务端状态中附带 Session identity、owner/项目、writer generation、version 和正文/Memory 血缘的 canonical hash，Memory off 也适用。恢复在重建外部 MCP 连接前检查当前 Session；领取审批的同一事务再比较冻结检查点并核验当前版本/来源，预检后发生变化也不能消费审批或执行工具。同版本正文篡改、owner/writer 变化和没有证明的旧检查点均拒绝。

显示 pending approval 的 Chat 投影标记只用于去重，不提升 SDK 历史版本或改变检查点。实际历史导入仍提升版本。正常重开数据库与逐条审批继续沿用既有暂停/恢复路径；浏览器仍只传 call-ID 决策，不能替换 SDK state 或历史正文。

最终相关回归 Python 3.12/3.13 各 **178 passed**，包含新增 **10** 个检查点 case；Ruff/diff 通过。这是 19.16 全量快照之后的相关回归，未称为检查点修改后全量。无公开 API/前端契约变化。详见 ADR 0027 与 `docs/verification/2026-10-05-session-checkpoint-regression.json`。

节点/远程 Runner Session 合同、完整 SDK state sealing、Memory off 下 Skill 冻结版本、自动 restart/replay append 去重、任意工具来源归档和全请求累计成本仍待完成。阶段 3/4 与真实 Provider 验收继续保持未完成。

### 19.18 阶段 3：人工确认的项目术语库

Project 内增加最多 200 项的版本化 alias 载荷，不新增独立领域实体。当前有团队记忆管理权限的项目成员以 expected version 和幂等命令确认完整映射；同事务核验当前身份、项目与权限。普通 Project 保存不能覆盖这份治理载荷。仅做项目内 NFC/casefold/空白规范化的精确映射，拒绝自指、歧义、链、环、控制字符和超长名称，不合并 User 或跨项目 ID。

旧事实正文、主体 ID、Memory 版本和出处 hash 保持原样；查询同时检查规范名和当前已确认别名，按规范主体报告冲突，新确认事实使用规范 ID。冻结查询保留术语库版本，恢复、实际模型交付与使用回执写事务重检。SDK 归档的实际术语工具输出也保存该版本，Memory off 不复用失效解释。模型诊断仅保留匹配数量，避免完整 200 项列表占满上下文。

“我的知识”读取当前选择项目和账户，真实读取/编辑术语；并发冲突阻止旧保存并要求重新加载。网络重试保留相同命令，映射改变才更新命令。普通成员只读。相关事实/术语回归 **67 passed**，术语/结构化记忆真实 API 浏览器回归 **2 passed**，前端当时 **221 passed**，OpenAPI、构建/bundle、Ruff/diff/lock 通过。与检查点/过程切片一起通过 Python 3.12/3.13 各 **2,266** 项全量。见 ADR 0028 和 `docs/verification/2026-10-05-project-terminology-regression.json`。

### 19.19 阶段 3：已验收过程的本地适用性与交付

ProcedureContextSelectionV1 附着现有 Bundle/Snapshot，目标来自当前持久 Run。自动项目上下文在当前 scope/生命周期/类型过滤后最多检查八个字面目标命中并选择一条合格经验；SDK memory_search 可显式指定 procedure_query，与 fact_query 互斥。自由文字前置条件和未知企业环境/工具实现保持未知。当前 project_member/task_bound、原生工具 grant/实现版本/schema、Python/AgentMesh/SDK 安装版本、独立 Review 与 sealed Artifact 证明决定是否能交付完整步骤。

过程是待参考资料，不自动执行、不授予工具、不成为 Skill。完整步骤/来源计入预算，过大整体丢弃；诊断也无法容纳时保留空交付。恢复、本地模型交付和回执写事务重检能力与证据。Session 区分过程和混合载荷中的纯事实交付，Memory off 也重检历史过程适用性。forget 同时清空 withheld 过程选择，升级后的数据库屏障在重开后继续阻止晚恢复。远程过程上下文在实际交付协议完成前保持 withheld。

任务审核表单增加显式记录方法入口，要求目标、步骤和验证条件，保留所选当前工具版本；成功 Run、Review 与人工确认身份仍由服务端现有捕获事务产生。团队方法仍需独立 Memory Review。过程/事实专项 Python 3.12/3.13 各 **37 passed**，之后共享混合载荷交付专项 **1 passed**；此前合并边界回归 **133 passed**。前端 **224 passed**，项目运营/术语/结构化事实浏览器 **4 passed**，类型与生产构建/bundle 通过。初始过程选择完整快照 Python 3.12/3.13 各 **2,266 passed**。最后跟进将外部 data/research Provider 工具依赖保持 unverified，避免以已配置代替当前可用；跟进后的过程/事实专项两套 Python 各 **38 passed**，不冒称为先前全量快照内容。见 ADR 0029 和 `docs/verification/2026-10-05-procedure-context-regression.json`。

检查点全量初次重跑发现三个旧审批测试期待较晚的 Memory 错误，新 Session 检查点已更早拒绝来源/owner/writer 变化。测试已改为校验最早的静态错误码及零新增工具/模型调用，八项审批场景通过；修复后全量与当前切片一起重跑通过。原失败快照仍保留在验证记录中。

阶段 3/4 尚未整体完成：通用语义组装与候选 UI、自由条件确认及 Skill 人工发布、120/24-case 四基线质量评测、授权检索容量/细分计时、学习告警、完整 Session/Runner 和累计成本继续开发；企业 Provider 与真实模型质量保持独立验收。

### 19.20 阶段 3：授权 FTS 检索容量

上下文查询不再先加载完整 Memory、Document、Blackboard 集合构造白名单。内部 MemorySearchFilter 将当前 actor/workspace/project/team、生命周期、层级、类型及结构化载荷边界下推至 FTS/LIKE/向量候选；命中记录及当前可见性共用只读事务。安全过滤先于结果和正文预算。单次候选最多 200 条，fallback 最多八个具体术语，兼容 search_pool 上限 200；来源、冻结版本及实际交付回执继续由原链路复核。

FTS 默认 BM25 语义采用 rank 排序。单 Store 本地 FTS/LIKE 召回排队，Provider embedding 调用在锁外。最终独立合成压测 **50k 记录、10 并发、100 次查询，端到端 p95 642.471ms**，八条命中均授权。SQLite execute/fetch p95 141.068ms，连接/PRAGMA 29.594ms，Python RRF 0.205ms，排队 554.536ms；span 重叠，百分位不可相加。embedding 关闭、未引入外部 reranker，分别报告零 Provider 时间。原批量 hydrate 路径的初始诊断 p95 52.4s 未通过，保留失败证据但不视为同样本稳态比较。

见 ADR 0030、`eval/run_memory_retrieval_benchmark.py` 及 `docs/verification/2026-10-06-authorized-memory-retrieval-benchmark.json`。范围、生命周期和向量授权使用独立确定性回归；此次成绩仅覆盖合成 FTS 容量，向量容量、真实企业 Provider 和模型质量仍待实际配置及验收。完整阶段 3/4/5 保持未完成。

检索切片完整快照 Python 3.12/3.13 各 **2,278 passed**。原六项 strict-scope 测试未保存当前 actor，补齐真实身份后范围/容量专项 **20 passed**。一次连接替换误改了市场参与设置的写事务，原全量试跑发现 13 个市场失败后停止；写连接恢复、市场/范围 **59 passed**，然后完整重跑通过。Ruff/diff/lock 通过。失败与最终证据见 `docs/verification/2026-10-06-authorized-memory-search-regression.json`。

全量结束后，严格个人/团队 scope 独立复测同样的 50k/10 并发/100 次查询，p95 分别 **943.424ms / 715.123ms**，均零越权命中并通过 1s 门槛。报告为 `docs/verification/2026-10-06-authorized-memory-retrieval-personal-benchmark.json` 和 `docs/verification/2026-10-06-authorized-memory-retrieval-team-benchmark.json`；个人范围余量较小，后续增长沿用该夹具复测。

### 19.21 阶段 3：资料学习运行治理

暂时失败尊重 Provider Retry-After 秒数/HTTP 日期，或 retry-after-ms，取不早于原本退避的下次时间；超过一天的窗口 blocked，避免擅自提前重试。原三次尝试、单 Job/每日 token 预留及 SDK 禁用隐藏重试保持生效。实际抽取等待每 30 秒续租，原 90 秒期限继续控制整次调用；同事务检查未过期 lease epoch/attempt、当前来源、身份/项目、模型及 opt-in/偏好。关闭学习或撤回来源取消等待，未报告用量仍保留预算，失效 lease 不复活。

本人 learning/status 同事务 SQL 聚合当前可访问项目的就绪、执行、重试、过期、失败/blocked 与未报告尝试，显示每日预留/cap 及清理等待。Provider 退避尚未到期不算就绪积压。五分钟就绪积压、租约过期、预算达到 cap、一分钟清理积压及终止尝试未报告用量形成静态本人页面提示，不发送消息。知识页显示和刷新状态，API 不加载 job/source 正文。

Python 3.12/3.13 学习/遗忘最终专项各 **47 passed**，含实际异步等待续租/取消、来源和偏好变化、HTTP 限流时间、预算保留、到期年龄、当前项目撤权及本人元数据 API。前端 **226 passed / 43 files**，类型与生产构建/bundle、Ruff/diff 通过。上述 2,278 项全量快照先于本切片，未冒称包含这些新增行为；最终专项覆盖当前实现。见 ADR 0031 与 `docs/verification/2026-10-06-document-learning-operations.json`。

完整阶段 3 仍需通用组装/候选状态 UI、自由条件与 Skill 人工发布、120/24-case 四基线质量评测；阶段 4/5 的完整 Session/Runner、累计成本、连接器和代答闭环继续开发。真实 Provider/企业 smoke 及模型质量仍需实际配置后独立验收。

### 19.22 阶段 3：本人记忆候选、当前可用性与交付状态

现有 Bundle 附着最多 200 条不含标题/正文的候选决定：prepared、withheld、quarantined、budget_dropped。实际 SQL 授权后的安全/原生来源检查与组装预算记录这些状态。召回与组装之间改变 Memory version/hash 时丢弃候选，避免以新版本证明旧正文。准备快照和引用预留仍不计使用。

运行详情只向本人投影最近 16 个执行快照及 16 个工具准备载荷，校验 canonical hash 和 Run 归属后，最多显示 200 个唯一版本。当前 actor/project/Run/thread、binding、Memory scope/version/hash、原生来源与结构化适用性在同一只读事务复查。事实出现新冲突、术语变更或过程工具能力失效，会隐藏当前标题。只有此 Run 中完全相同 type/ID/version/hash 的持久使用回执才能显示“已使用”；历史已使用但当前失效仍保持历史事实并解释失效，不返回新版本标题。

Workspace 展示五种状态并解释待使用不等于交付。旧 bundle 从原命中及冻结事实/过程选择派生候选，不写入空字段、不改变历史 canonical hash。本人 forget/来源撤回同时清除 candidate-only 执行快照及工具准备载荷，v5 数据库屏障在重开后仍阻止晚恢复。

候选/事实/过程/遗忘/检索边界 Python 3.12、3.13 各 **124 passed**；最后 prepared 决策防线专项 **7 passed**。前端 **227 passed / 43 files**，类型生成、生产构建、bundle、Ruff 与 diff 检查通过。双版本全量快照各 **2,302 passed / 5 个既有 PyMuPDF 警告**，包含学习运行提示与候选切片，尚未包含之后新增的冻结评测入口。容量复查均为 50k 记录、10 并发、100 查询：auto p95 **650.052ms**、personal **923.263ms**、team **683.979ms**，各范围全部命中授权通过且低于 1s。个人范围仍有较小余量；这是无 embedding 的合成 FTS 结果，不能外推为真实企业或向量容量。

见 ADR 0032、`docs/verification/2026-10-06-memory-candidate-regression.json` 与 `docs/verification/2026-10-06-memory-candidate-retrieval-benchmark.json`。完整阶段 3/4/5 仍未完成：通用组装优先级、自由条件与 Skill 发布、120/24-case 四基线评测、Session/Runner 完整协议与累计成本、连接器和代答闭环继续开发。真实模型质量和企业读取分别验收。

### 19.23 阶段 3：冻结记忆控制集与有预算的真实 QA 入口

新增 `eval/memory_cases_v1.json`：六类各 20 条、共 120 个冻结合成 holdout，生成示例另列且 ID 不相交。离线入口通过显式确认 fixture 断言后重放当前事实、修订、半开历史时间、冲突/未知、撤回与当前权限；跨会话组只验证数据库重开，尚不代表完整 SDK 两次轨迹。每例还写入 peer 的私有同谓词断言，查询必须排除它。全部 120 个控制案例通过且无记忆使用回执。故意改变独立 literal 期望只通过 119 条并返回失败；重复 ID 和非对象数据集被拒绝，宿主数据库 sentinel 保持原样。

`eval/run_memory_eval.py` 默认 scripted/零模型调用，抽取质量、答案正确率、四基线质量与过程错误率均为未测量。真实模式要求显式 model、恰好 24 个 case（每类四个）、≤500,000 token cap 及新的结果文件。四种输入为无长期记忆、冻结近期历史/抽取式摘要、同一授权观察的 legacy 文本 FTS 适配、增强事实查询；固定问题/模型/512 输出 token，工具集合为空。该入口比较合成 QA 输入，不声称为真实 Task 完成、后台抽取质量或完整过程复用。完整 SDK 请求预算在实际调用前预留并写 checkpoint；已报告用量结算，失败/未知用量保留预留并停止，HTTP 隐藏重试关闭，Provider 超额记录真实用量并停止。

默认模型真实试点在第一条请求失败，尚无可评分答案。相同结构化 SDK 请求及取消结构化 schema 的普通请求均发生连接层 APIConnectionError；HTTP/HTTPS 的最小 GET 也未得到有效响应，未发现代理设置或证书验证失败。四个已配置模型共用该网关，未改配置或绕过证书。网关/网络依赖仍待解决，具体根因未确认。三次模型尝试保留共 **9,449 token**，已报告用量为 0、答案质量未测量；它不是成功 smoke。新增静态失败类别不保存 Provider 正文或凭据。

评测入口及预算/诊断专项 Python 3.12、3.13 各 **9 passed**，Ruff/diff 通过。前面的 2,302 项全量快照包含全部生产候选/学习修改，未包含本节随后新增的 eval 测试。见 `docs/verification/2026-10-06-frozen-memory-control-replay.json` 和 `docs/verification/2026-10-06-memory-qa-pilot-attempt.json`。真实 24/120-case 质量阈值、24 个两次过程轨迹及完整阶段 3/4/5 继续保持未完成。

### 19.24 阶段 5：真实代答结果状态与旧采纳入口封闭

空资料或模型明确报告不足返回 insufficient_evidence；未配置模型、调用失败或空结果返回 blocked。两者均无引用、confidence none，不再用“已归纳”模板宣称完成。直接采用方法拒绝非 answered、空答复或无引用。市场审计及 Timeline/Activity 保留真实状态，未知旧状态回到 open；前端用中文显示暂不可用和资料不足，不称为完成。

旧市场采纳 API 会从共享状态帖伪造 answered/high 并生成来源、私有知识和贡献。四种状态的实际 API 回归均复现错误成功。现已返回 409 verified_delegated_query_required，且零新增 Source/Memory/Relation/Point；前端移除旧采纳动作并解释缺少可核对产物。状态帖即使写 answered 也不能充当已交付答案。

Python 3.12/3.13 最终市场/代答/隔离专项各 **77 passed**，前端 **228 passed / 44 files**；OpenAPI 类型已生成。见 ADR 0033 与 `docs/verification/2026-10-06-truthful-delegated-answer-outcomes.json`。此前 2,302 项全量快照先于本切片。成功测试显式注入确定性模型 adapter，未声称真实答案质量。持久 Query/Artifact、当前双方/来源授权、项目 consent、敏感确认、重启恢复及幂等采用正在继续开发；完整阶段 3/4/5 未完成。

### 19.25 阶段 5：持久项目代答与已证明的私有采用

实现 DelegatedQueryV1 和八个查询/授权入口，复用 SQLite records、PersonalAgent 合成、Inbox 与 sealed Artifact/Source，不创建 Runtime。请求以本人/command ID 去重，保存问题版本/hash、双方/项目、冻结记忆版本/内容与完整记录 hash、授权水位、确认及 claim。只有请求方/回答方可以读取；当前 User/Project/member、本人 personal Agent、MemoryBinding 与原生来源在事务内核验。普通管理员无第三方 query/确认摘要的读取例外。

项目授权由 grantor 本人以版本和命令确认，旧无项目 grant 不迁移；自动答复须双方 opt-in，高敏仍本人确认。确认重检完整冻结匹配集，当前 Source/权限/绑定/参与/授权在模型调用期间变化时不保存答案。私有原始标题、链接与 Memory ID 不进入请求方投影，受限引用指向 query。历史 answered 保留，但当前失效时隐藏正文/引用并禁止采用；撤销/重新授权不恢复旧授权水位。

采用核对实际 query/Artifact hash、owner/scope/type/index 和当前来源，私有知识、血缘、一次不可兑换贡献、Audit 与回执同事务提交。重启及同/不同命令重复采用不重复记账；派生知识的未来检索仍检查 query 来源证明，不给予原始个人记忆访问权，也不直接创建已审核团队知识。已领取但中断的调用到期 failed，不自动重试；显式恢复只能领取尚未开始调用的已确认请求。scout 以匹配 fingerprint 发起 query，继续不得创建 consent。

Collaboration 提供发起、授权/撤销、本人确认/拒绝、状态、受限答复与私有采用，Inbox 直接打开 query。成功后可显式发起新请求，网络重试保留相同命令。Ego Lite 在关闭全部 Provider 的独立临时库中实测请求、角色确认、资料不足、无模型 blocked、授权/撤销和刷新恢复；这不是真实模型质量。

最新相关回归 Python 3.12/3.13 各 **142 passed**，前端 **231 passed / 45 files**；OpenAPI、生产构建/bundle、Ruff/diff、69 项依赖锁检查通过。两套全量各 **2,336 passed / 5 个既有 PyMuPDF 警告**。最终 Artifact content-type/index 与 record identity 防线另有真实失败再通过的专项；不冒称为全量启动时的实现。详见 ADR 0034 与 `docs/verification/2026-10-06-durable-project-delegated-queries.json`。

首个代答输入仅为当前合格纯文本个人记忆（8 条、单条 6,000/总 16,000 标题/正文字符、8,192 答复字符）；未把事实/过程载荷压平，也未宣称为完整 tokenizer/累计预算。旧同步模型接口的 SDK 预算/用量/实际交付回执及可取消期限仍需阶段 4 统一治理。完整阶段 3/4/5、连接器、关系查询、真实模型质量与企业读取均未整体完成。

### 19.26 阶段 4/5：持久原始上传与原子导入

新上传冻结原始输入为数据库旁的私有 opaque cache，Job 保存 SHA-256、大小、owner/workspace/project 和七天保留时间，Future 不再携带字节。目录/文件权限、dirfd/O_NOFOLLOW、常规文件/大小/hash 校验限制缓存引用；不称为 OS sandbox。输入上限 20 MiB，解析正文上限 1 MiB，标题/元数据/片段数量亦有明确边界，超限失败而不静默截断。

复用 DocumentParseJob，120 秒 claim 每 30 秒续期，最多三次实际尝试。领取、续期、提交复核当前 active User/Project/member、workspace、冻结输入和当前 claim。Source/Document 身份按 Job 固定派生，Source、文档、私有摘要/片段、FTS/vector pending 状态与完成记录同事务提交；异常整体回滚。失去权限或被接替的 worker 不提交旧输出，也不能使新的已完成结果失败。缓存清理与完成状态独立，失败以 cleanup_pending 跨重启续做。

启动恢复有界发现 queued/到期 running/待清理项，队列满不丢已受理工作；过期输入清理不删除已导入正文。未创建 Job 的过期 opaque/临时孤立文件由受控维护清理，每轮最多扫描 1,000 metadata/删除 100 项，注册输入、无关文件与 symlink 外部目标保留。Job scope 和原始引用使用局部索引。旧无输入证明或存在部分导入的记录明确要求重新上传/检查，不伪造恢复证明。

Knowledge 提供实际上传、状态、片段数、尝试与本人重试。重试命令以 expected_version/command ID/hash 与回执持久去重，普通管理员不能替上传者重试；保留原有管理员读取例外且检查当前项目权限。Job 列表在 SQL 中限定当前 owner/workspace/project 并分页。解析错误仅保存静态代码/异常类型，无异常正文。上传可显式选择当前有权访问的项目，仍不自动确认事实或发布团队知识。

Python 3.12/3.13 全量快照各 **2,356 passed / 5 个既有 PyMuPDF 警告**；该快照先于最后的孤立缓存/索引和两项额外测试。最终相关专项各 **114 passed**，前端 **234 passed / 46 files**，OpenAPI/生产构建、322,377-byte 最大 chunk、Ruff/diff、69 项依赖锁检查通过。Ego Lite 的独立临时库实测真实文本导入、损坏 PDF 失败、本人重试再次失败和刷新恢复，并检查截图；全部外部 Provider 关闭。详细失败与验证边界见 ADR 0035 和 `docs/verification/2026-10-06-durable-document-ingestion.json`。

本切片不代表强制取消解析线程、OS 资源隔离、旧部分导入修复、编辑后的手动重导入原子性、启用向量 Provider 的当前授权/容量或企业同步水位已完成。统一 SDK 请求治理、Session/远程 Runner、真实模型质量、连接器/关系查询和过程复用等剩余阶段 3/4/5 内容继续开发。

### 19.27 阶段 5：当前项目市场投影与本人运行状态

四个旧市场读取 API 的跨 workspace/项目泄漏已经由实际请求复现并修正。MarketReadSnapshot 在同一只读事务内读取当前持久身份和默认项目，检查 active workspace/member，再在 SQL 中过滤信号与匹配。信号须有显式 workspace/project、project_visible 和 published 状态；无项目证明的旧信号不随 owner 默认项目移动。匹配要求显式范围与双方当前 active 成员，新增审计冻结为信号项目。

每次最多解码 200 位成员、200 条信号/匹配，参与者 ID 同样有界；SQL 总计覆盖完整可见范围。授权数量只统计本人当前项目有效 grant。board 最近匹配 30 条、activity 40 条、个人时间线 200 条；图关系仅代表最近匹配窗口，界面明确该边界。跨时区按实际时间排序，多次协作使用独立事件 ID。旧共享 match 正文与猜测 Inbox 操作已从 timeline 移除，受限答案、确认和采用继续由 Query 校验。

公开 worker 保留运行/间隔/时间，队列数量和静态错误限定本人 workspace/project，不返回进程聚合的发布/触发数量或他人错误。最终市场/持久代答专项 Python 3.12/3.13 各 **106 passed**，前端 **234 passed / 46 files** 与生产构建/bundle 通过；此前 2,356 项全量快照先于本切片，当前范围由专项证明。见 ADR 0036 和 `docs/verification/2026-10-06-current-project-market-reads.json`。

后续继续修正自动发布来源及模型等待期间的授权变化，再接增量同步。没有企业试点配置时，本地 Task 与上传资料继续提供验收基础；不通过模拟宣称真实企业读取完成。统一 SDK 治理、完整 Session/Runner、关系查询、过程复用和真实模型质量仍待完成。

### 19.28 阶段 3/5：自动摘要发布的当前授权与撤回

旧发布的十二种真实失败场景已复现并修正：当前 opt-in、项目/成员、绑定、选中记录及原生来源在等待模型时变化，不再发布旧结果。材料仅为本人当前项目或通用的普通 private/active 未归档文本，以及当前项目本人 Task 标题；高敏、事实/过程、私人代答、个人汇总/归档载荷不自动发布。文档来源须有版本与当前 origin，旧未证明版本要求重新导入。

每类最多检查 32 条候选，最终各八条；Memory 标题/摘要 120/2,000 字符、最多八个来源，总 Memory 16,000 字符，Task 标题 120。模型解析后发送前和原子提交内核对当前身份、项目、Agent、参与/绑定/模型及完整冻结记录 hash。前条信号比较防止慢结果覆盖新发布。三行格式、单值 800/总 2,400 字符与危险输出检查阻止不合格输出；不存在以模板替代不安全模型输出的发布。

信号、FTS/vector pending 与审计同事务提交。退出及本人遗忘/资料撤回同其既有写事务清空唯一自动摘要及检索/向量状态，避免保留遗忘内容；后续 tick 只能使用剩余合格输入。界面刷新相关缓存，解释普通摘要范围并使用“回应记录”而非已解答数量。四个市场读取入口可显式选授权项目，请求和缓存都绑定该项目；省略时仍取当前持久默认项目。

Python 3.12/3.13 当前后端完整快照各 **2,400 passed / 5 个既有 PyMuPDF 警告**。最终前端 **236 passed / 47 files**，OpenAPI、生产构建/bundle、Ruff 与 diff 通过。Ego Lite 独立临时库实测本人摘要、其他工作区隔离、实际退出按钮撤回及刷新恢复，截图已检查；Provider 全部关闭。详见 ADR 0037 和 `docs/verification/2026-10-06-current-authority-market-publication.json`，不将无模型的页面验收称为真实模型质量。阶段 3/4/5 仍需统一 SDK 请求/成本/实际交付、完整 Session/Runner、通用来源失效传播、连接器水位、关系查询、编辑后重导入和过程复用等后续内容。

### 19.29 阶段 3/4：原子文档编辑与当前版本重导入

手动导入留下部分片段、编辑失效失败后正文已更新的两种真实故障已复现并修正。DocumentMemoryStore 在同一写事务检查当前文档、调用者/owner、workspace/项目/成员/实际角色；保留原管理员例外，停止使用旧角色或读请求作为写入授权。分块在事务外有界进行，提交内比较完整输入 hash，同版本正文变化也不能晚提交。

稳定的版本化片段及具备明确 owner/scope 的 Source，与 FTS、向量待处理状态、完整进度和审计原子提交。匹配的原生缺失/暂存片段可补齐；未知额外、内容/来源冲突、高敏/结构化/派生、归档/遗忘等记录要求检查，不能自动恢复。重复/并发/重开不复制内容；缺失 Source 和搜索投影可恢复。正文最多 1 MiB，标题/文件名各 512 字符、片段最多 2,200；当前片段 SQL 查询同样有界并限制单条 JSON，不再扫描全部个人记忆。

编辑的 expected_version CAS、正文索引、本人旧原生摘要/片段失效及自动协作摘要撤回一次提交。其他人的独立记录与共享团队知识保持其治理身份。旧向量状态删除以阻止晚返回附着。import-to-memory 的可选 expected_version 保持旧调用兼容，新界面明确提交所选版本。

Knowledge 提供选择当前项目本人资料、保留版本的正文草稿、保存、读取最新版本和单独重新导入。未保存改动不能导入，版本冲突与未知网络结果提示检查当前状态；原始上传记录注明其自身 vN。事实学习与团队共享继续要求确认。Ego Lite 已实际验证上传、编辑 v2/0 个片段、重导入 1 个片段、重复幂等与刷新恢复；入口布局简化后再次通过可见按钮完成 v3/0→1 个片段，最终截图已检查。外部 Provider 全部关闭。

25 项新专项通过，相关旧组合 Python 3.12/3.13 各 153 项通过；前端最终 **240 passed / 49 files**，生产构建/bundle 最大 322,377 bytes、OpenAPI、Ruff/diff 通过。首次完整回归两版各 **2,423 passed / 2 failed**，失败涉及 SDK 测试 UTC deadline。原用例单独两版均通过；只给两项非超时测试使用单调推进的测试 UTC，生产 deadline 保留，周边 SDK 两版各 **83 passed**。最终完整重跑两版各 **2,425 passed / 5 个既有 PDF 库警告**；首次失败快照仍保留，不改写为通过。前端布局简化后的再次验证仍为 240 项通过，构建 2.63 秒，包体预算通过。

详见 ADR 0038 和 `docs/verification/2026-10-06-atomic-document-edit-and-reimport.json`。解析器隔离/硬取消、旧无输入证明的 ParseJob 修复、启用向量 Provider 验收、完整 SDK/Runner、通用来源失效、连接器/关系与过程复用仍待完成；本项不将整个阶段标成完成。

### 19.30 阶段 4/5：已发布协作摘要的原生来源失效传播

发布后的普通 Memory 归档/修订、敏感级别/范围、身份/项目/Agent 权限或绑定变化，现在通过现有自动信号的私有依赖在源写事务中撤回公共正文和 FTS/vector/state。原始 SQL UPDATE/DELETE 同样生效；不存在的可选绑定/模型定义也登记逻辑键，首次创建限制会撤回旧摘要。依赖写失败和索引清理失败均整体回滚，晚 embedding 不复活索引。私人来源 ID 不写入公共 metadata。

每次仅跟踪实际选中的最多八条 Memory/八条 Task 及对应 Thread/原生 Document，连同六个身份/配置键，最多 94 个依赖。文档完整记录 hash 加入模型发送/提交的冻结证明，正文变更但版本未递增也使结果失效。依赖触发器忽略完全相同、未选中/他人 Memory 及普通新材料写入，依赖记录的其他 payload 变更保守撤回；已有资料编辑/撤回和遗忘命令仍可保守撤回本人聚合摘要。读取标记保留依赖。重开不补造旧自动摘要的来源，缺少依赖的确定性自动帖撤回，人工帖保留；已撤回信号不再回填索引。

Python 3.12/3.13 相关专项各 **151 passed**。最终记录见 ADR 0039 与 `docs/verification/2026-10-06-generated-publication-input-invalidation.json`。任意外部 Source 的同步/墓碑、绑定接口写入/读取资格、scout 当前材料资格、完整 SDK/Runner、真实 Provider/语义评测、关系与过程复用仍待完成；阶段 3/4/5 保持实施中。

全量检查随后暴露 Task 列表逐条读取权限的性能缺口。现每个请求只为该页提示读取一次规则，单条视图复用管理权限，下一次请求和写入继续实时复核；集合只读连接显式关闭。策略改变后同一 Service 仍及时撤权，旧提示不能授权新写入。双版本当前关联回归各 **102 passed**。10,000 Task/50,000 事件/10,000 Memory/1,000 团队知识的七次测量中，五项 p95 全部低于原 500ms；列表 297.976ms、详情 483.819ms。见 `docs/verification/2026-10-06-generated-publication-project-operations-benchmark.json`。首次全量失败如实保留，未降低门槛或放宽期限。

最终后端完整快照 Python 3.12/3.13 各 **2,455 passed / 5 个既有 PyMuPDF 警告**，前端 **241 passed / 50 files**、生产构建/bundle、Ruff/diff 通过；API 合同未改变。Ego Lite 独立临时库实测“已发布信号→资料保存 v4→旧摘要及活动消失”，截图已检查；无摘要时只显示当前未发布事实。未启用真实模型、企业或 embedding Provider；下一步继续绑定授权与匹配材料资格。

### 19.31 阶段 5：Agent 记忆绑定的配置授权与查询约束

已复现并修复调用者提交他人 binding ID 时覆盖配置、未授权读取私人项目列表、使用过期登录用户快照写入/删除的问题。三个 HTTP 接口现在委托给小型 `AgentMemoryBindingService`：读取采用一致只读快照，修改和删除在取得数据库写锁后复核当前 User/Agent/工作区/所有权/管理权限。管理员也不跨工作区；指定项目需当前活跃且调用者与私人 Agent 所有者具备访问资格。

ID、路径 Agent 身份与时间由服务端控制，两个同时创建的请求保留同一个绑定身份。载荷限制为 1–4 scope、32 类型、100 项目和 1–100 结果；重复、无效或身份不一致的绑定明确失败，不选择更宽松的一条。内部读取复用同一检查并只取最多两条载荷。普通查询保留指定项目，绑定仅收窄范围；结果类型在现有 SQL 中先过滤再计入预算。

绑定 API 沿用源事务内的摘要/索引失效机制；索引删除失败整体回滚。实际 SQLite 写锁等待中的停用、所有权转移、工作区变化和公共管理权限撤销均有回归。Python 3.12/3.13 当前关联回归各 **302 passed**，其中新增 40 个授权/身份/查询/事务场景；OpenAPI 已重新生成，前端 **241 passed / 50 files**、生产构建/bundle、Ruff/diff 通过。本项未重跑整个后端，前项 2,455 的完整快照保持原记录。记录见 ADR 0040 与 `docs/verification/2026-10-06-current-authority-agent-memory-binding.json`。

下一项继续 scout 按当前项目/绑定/生命周期/来源选择材料及完整 SDK/Runner 治理。跨消费者的绑定类型语义统一、外部连接器/关系、过程复用、解析隔离和真实 Provider/企业试点仍待完成；阶段 3–5 保持实施中。

### 19.32 阶段 5：匹配 Agent 的当前项目材料与发送资格

已复现并修复归档时间存在但状态仍 active、跨项目材料、绑定禁止的私人材料进入匹配提示词，以及领取任务后撤权仍发送和文档正文变更未递增版本仍接受旧判断的问题。`MarketScoutMaterials` 在信号的显式项目下复核当前 User/Project/私人 Agent/Binding/Model，再选当前合格的私人普通 Memory 与本人活动 Thread 的 Task。

最多八个问题关键词通过已有授权 FTS/中文短词回退选择最多 32 个不同 Memory 载荷候选；Task 在 SQL 先筛关键词/项目/归档后取最多 32 个候选。选中最多八条 Memory/八条 Task，只发送每项最多 120 字符的标题；求助上限 800 字符。不扫描和 hash 全部私人材料，64 条新无关记录之后的旧相关材料仍可召回。高敏感标题线索保留既有本人确认网关，不建立新共享授权。

完整当前身份/绑定/选中记录、对应 Thread 和最多 64 个原生文档/父 Memory hash 加入冻结证明；原生普通导入块必须与当前文档的对应分块完全一致，避免旧 chunk 被新的快照重新解释为当前证据。每次主/备用模型实际发送前与 YES/NO 返回后都复核证明、信号和 matching claim 身份/到期。撤权、来源变更或过期进入现有 retry_wait；未改变既有十分钟 lease、模型超时、同意与重试规则。

当前专项 **46 passed**，新增 24 个资格、正文变化、发送/回退、租约和旧材料召回场景。Python 3.12/3.13 各 **347 passed** 关联回归，加各 **74 passed** 无重叠的导入/恢复/学习/遗忘回归，合计各 **421 passed**；Ruff/diff 通过。API/存储模型合同及前端控件未改变；本项未重跑整个后端或启用真实 Provider。记录见 ADR 0041 与 `docs/verification/2026-10-06-current-project-market-scout-material.json`。

完整 token/成本/输出/取消及 SDK/Runner 交付预算、通用外部 Source 版本/hash/墓碑、统一上下文、绑定类型语义、Task/Review 变更巡检、连接器/关系及过程复用继续开发。真实 Provider/企业试点和模型质量验收仍按实际依赖推进；阶段 3–5 保持实施中。

### 19.33 阶段 5：本地已提交 Task/Review 变更触发巡检

现有 Schedule 新增默认关闭的显式变更触发和服务端消费水位，复用 ScheduledOccurrence、v1 Run、现有 dispatch、只读巡检与 owner 的报告/Inbox。创建/修改命令不接受客户端水位；启用、暂停后恢复和更换模板从当时已提交记录开始，其他配置修改保留并发推进的水位。旧配置不会自动启用。

仅本地原生 Task/Task Review 命令回执进入触发查询，通过当前 Task/thread 项目投影检查工作区、项目和共享身份；事务回滚、私人会话、跨范围和无命令的原始写入不触发。连续变化等待 30 秒，持续编辑的合并窗口上限五分钟，仍受五分钟自动 Run 频率和 tick 数量预算约束；排队等待不包含在合并窗口上限。扫描按未消费水位优先，已服务配置的新编辑不会持续挡住其他配置。

Execute 在实际写事务重读配置、源窗口和当前身份/项目/Agent/管理权限/Runtime，原子写入触发、Run/dispatch 与水位；失败回滚，竞争领取和重启不复制同一触发。变更不推进 cron 槽位，普通 cron/manual 可同时消费已提交输入。Blocked/overlap 按原政策保留 blocked/skipped 事实并消费窗口，不建立自动重放队列。模板仍为零模型只读查询，不自动修改 Task/Memory。

新增 32 项行为测试；Python 3.12/3.13 相关回归各 **148 passed**，包括真实 Task Review 接受后的 completed 变化、版本化来源、只读报告与 Inbox。前端新增显式勾选、编辑恢复和运行种类；Ego Lite 隔离库完成勾选配置→创建 Task→一次变更读取完成→真实 v1 来源报告→暂停→后端重启后同一报告，模型用量为 0。两次截图请求超时，未宣称截图通过。OpenAPI/前端构建、Ruff/diff 和前端测试证据见 ADR 0042 与 `docs/verification/2026-10-06-committed-project-change-inspections.json`；没有重跑整个后端或调用真实企业/模型 Provider。

连接器/外部 webhook、关系检索、已验证过程复用、解析隔离、完整上下文和 SDK/Runner 交付预算，以及真实模型质量/企业试点仍待完成，阶段 3–5 保持实施中。

### 19.34 阶段 5：当前项目记忆关联查询与冻结判断

保留旧 MemoryRelation 血缘记录，在现有模型上增加可选的 v1 类型、端点版本/hash、当前 Task/文档依据和操作身份。五类判断默认 candidate；显式人工确认新增独立判断，不接受团队 Memory Review、不改变 Task/Memory 生命周期、不授予私人来源访问权。写入在实际 SQLite 写事务内重读身份/项目/端点/权限，关系与无正文 audit 原子提交；竞争、重启和同一表单重试复用命令，完整冻结字段不一致会冲突。

新增当前项目只读 API 和任务/知识详情关联面板。两跳查询在同一快照独立核对每个节点、目标和附带依据；私人记忆、原始文档和 Artifact 不因管理员角色或团队共享而放开。原生 Task 父子/依赖可双向查询；Task Review/封存交付依据、已冻结的记忆父节点，以及能核对当前原文的导入片段/Fact/SourceSpan 引用复用当前领域记录。仅版本链接不补造历史 hash；全局笔记不能声明项目文档为原生来源。文档反向查询先筛类型/所属项目/owner/版本/hash，再取候选，旧未证明链接不会挤掉较早的有效事实。快照内的节点元数据/hash 复用，下次请求仍重新读取。

默认 20 节点/40 边/8,000 JSON 字符，最大 40/80/12,000；每次 SQL 候选窗口 128 行、请求总计 512 行；证明载荷解码限 200 次记录读取及 4 MiB，各实体还有单条上限。这不是 OS 隔离或 SQL 延迟保证。循环不绕过深度/输出限制，只报告有界诊断，不返回隐藏关联总数。API 不发送模型，也不成为第二套 SDK 上下文权威。前端按账号/工作区/项目/root 隔离缓存，只展示标题、版本和关系状态；可对图中已有记录选择当前 Task/文档依据保存判断，确认默认不勾选。

新增 **45** 个行为场景。Python 3.12/3.13 相关回归各 **256 passed**；最后的快照元数据缓存与等价 owner 提前筛选之后，关联专项各 **45 passed**。前端 **246 passed / 51 files**，类型生成、生产构建/bundle、Ruff 和 diff 检查通过。Ego Lite 隔离库验证原生引用、候选保存、文档跳转/反查、人工确认、相同表单重放、后端重启、文档编辑后旧边消失和 Task 面板；未启用真实 Provider、未宣称截图或全后端复测。精确结果、限制、QA 差异与当前文件 hash 见 ADR 0043 及 `docs/verification/2026-10-07-current-project-memory-relations.json`。

本项完成本地受治理记录的关联切片；通用外部 Source 版本/hash/归档/快照、真实连接器水位、模型推断关联、任意记录发现/候选审核、Artifact/记忆父节点的反向索引和 SDK 图交付仍待实现。阶段 3–5 的完整上下文、绑定类型语义、已验证过程复用、解析隔离、Session/Runner 请求/成本/取消/交付预算及真实模型/企业试点继续开发，不将完整阶段标成完成。

### 19.35 阶段 3–5：跨消费者的记忆内容类型与旧绑定确认

已统一 `allowed_memory_types` 为 Memory 的 finding、decision 等内容类型，覆盖普通/SDK 检索、MemoryContext 召回/池、事实重新校验、流程选择、候选元数据、事务内引用/交付、市场材料和代答。SDK 的 `RetrievalProfile.result_types` 仍是独立结果类别条件，与内容类型取交集；集合中相同的 ID 不再让原始文档通过 Memory 类型白名单。

绑定增加服务端确认的 `type_policy_version=1`。带非空类型列表的旧配置在版本缺失/null 时暂不提供 Memory，由当前管理者核对并调用原 PUT 后确认；GET 保留原配置，不自动猜测旧值含义或放宽访问范围。空类型列表保留已有身份/scope/owner/项目约束。数据库重开保留确认状态；升级前依赖未确认受限绑定与私人 Memory 的生成信号，在现有启动事务中撤回正文和索引，独立 Task 材料及已确认/不限制类型的配置不受此迁移条件影响。

普通与 SDK 查询在 FTS MATCH、中文短词 LIKE 和 vector SQL 内先过滤内容类型，再应用候选/解码/打分/输出预算；SDK 不再加载整张 Memory 表构造 ID 白名单。市场发布、直接材料读取和代答也在各自候选上限前应用类型。绑定语义变化后，旧事实/流程步骤不能提交使用回执，候选不返回旧标题，已交付代答不再返回答案或引用。

新增 **42** 个行为场景，其中绑定语义专项 **35** 个。最终 Python 3.12/3.13 的 18 个关联文件各 **375 passed**（240.77s / 242.06s），包含最后的启动迁移。前端 **246 passed / 51 files**，OpenAPI 生成、生产构建/bundle、Ruff/diff 通过。未新增 UI 控件或调用真实 Provider，未宣称浏览器或全后端复测。边界、先前 RED 及最终源文件 hash 见 ADR 0044 与 `docs/verification/2026-10-07-consistent-agent-memory-content-types.json`。

跨消费者的绑定类型语义切片已完成；完整 ContextAssembler 的优先级与全请求预算、通用 Source 版本/归档/快照、连接器水位、过程复用、解析隔离及 Session/Runner 交付仍继续开发。真实模型 120/24-case 质量、企业试点与完整阶段验收仍按实际依赖执行，阶段 3–5 保持实施中，阶段 6 保留负载触发条件。

### 19.36 阶段 4：本地非流式 SDK 请求的完整预算与当前发送准入

普通意图/计划/修复/汇总，以及 DeepSearch 需求、问题图、规划、汇总与审查，复用现有完整请求预算和当前 Run 发送检查。预算包含 SDK 实际消息、工具结果、instructions、工具/handoff/输出 schema 与 model settings；未知 tokenizer 保留明确的保守 UTF-8 估计。规划只允许 planning，汇总/审查只允许 running，当前 owner/workspace/project/thread/task、writer 身份和 deadline/absolute expiry 在取得模型槽位后复查；Memory 关闭也生效。

RequestBudgetModel 自行管理异步调用的发送检查，聊天和压缩移除重复安装。取消、错误与正常完成恢复调用上下文；不同 Run 的排队请求互不借用检查。初始超预算的 DeepSearch 需求在持久模型预留前拒绝；等待后才被拒绝的尝试仍沿用既有未知结算政策，不宣称退款或普通 Run 累计成本已完成。普通汇总在发送前再次核对现有 Source 存在/owner/项目/Run 身份，该检查尚不是通用版本/hash/墓碑证明。

授权/预算拒绝使用共同 ModelAdmissionError 分支，保留原 MemoryContextError/ContextRequestError 的静态安全码。意图、计划修复与汇总/审查不把它当成输出格式问题；DeepSearch Finalizer 提交 failed 原因，不生成降级 digest 或报告。实际 Provider/格式失败的原有修复与允许降级规则继续保留。没有向这些规划/审查阶段新增私人 Memory 注入。

新增 **26** 个行为场景。最终 Python 3.12/3.13 的 **26** 个关联测试文件各 **461 passed**（241.49s / 241.82s），覆盖聊天/计划/DeepSearch、排队发送、Session/压缩/审批恢复及结构化上下文。Ruff/diff 通过；公开 API/存储载荷与前端控件未改变，未重跑前端、浏览器或全后端，也未调用真实 Provider。记录见 ADR 0045 与 `docs/verification/2026-10-07-bounded-nonstream-sdk-model-handoffs.json`。

完整 ContextAssembler 的优先级、普通 Run 累计请求/输出/成本与压缩未知用量、通用 Source 生命周期、OS 解析隔离、Session 自动 replay/sealing、远程 Runner 实际交付、连接器水位、过程发布/复用，以及真实模型质量/企业试点仍继续实施；阶段 3–5 不标成完成。

### 19.37 阶段 4：文档解析进程、资源限制与取消

生产上传使用固定 Python parser 子进程与独立 POSIX session，保留原有两名线程池协调者、八个排队位置和持久 Job/claim。当前输入证明校验后写入私有临时目录；子进程隔离 Python 启动、关闭继承描述符并剔除 API/OAuth/Provider 环境。结果 JSON 最多 2 MiB，拒绝非法格式、未知错误码、symlink 与异主结果；原子导入独立复查当前授权/claim/输入，Source/Document/Memory 身份仍由服务端生成。

解析墙钟期限 90 秒，CPU/单文件/描述符/core dump 有系统限制；父进程最多每 100ms 检查 RSS 总量、后代数量与取消。停止服务或每 30 秒的 claim 续期失败会终止 parser/OCR 进程组并等待主 worker 退出，持久原始输入保留现有七天本人重试规则。macOS 的 RSS 监控是采样终止条件；Linux 额外 address-space 限制尚未在容器实测。本机 Docker daemon 不可连接，未启动 Docker 或冒称 Linux/远程 CI 验收。

PDF 页数与提取正文、OOXML entry/XML 数量和解压总量均有上限；XML parser 回调拒绝 DTD，真实测试复现并修复 UTF-16 绕过字节检查。超限明确失败，不将截断内容冒充完整资料。资源隔离仍需部署级文件/网络权限 policy，不能据此宣称完整安全沙箱。

新增 **26** 项行为场景。Python 3.12/3.13 的 14 组关联回归各 **261 passed / 5 个既有 PyMuPDF 警告**，耗时 **50.73/50.97 秒**；Ruff、diff 与 lock 检查通过。真实子进程验证文本/PDF/Word/Slides、超时/取消/内存分配、后代清理、撤权和旧 claim 晚返回、非法/超限/异主/崩溃结果及 HTTP 原子导入；图片使用受控 OCR 可执行程序验证适配/配置/凭据隔离，未宣称真实识别质量。API 模型与前端不变，未重跑全后端或真实 Provider。见 ADR 0046 和 `docs/verification/2026-10-07-bounded-document-parser-processes.json`。

完整上下文、普通 Run 累计请求/成本、通用 Source 生命周期、旧输入/部分导入修复、部署级文件/网络隔离、Session/Runner 交付、连接器水位、过程发布/复用及真实模型/企业试点继续实施；阶段 3–5 保持实施中，阶段 6 保留实际负载条件。

### 19.38 阶段 4：本地合成来源身份与原子 Source 创建

已复现并修复普通合成在等待模型名额时接受同一 Source ID 的标题/类型/引用/skill 身份变化，以及发送期间来源删除或 owner 撤权后仍交付结果的问题。首次合成核对持久引用与节点中的 id/title/type/reference，再冻结本次 Source 引用记录的完整身份摘要；实际发送和合成服务返回后重检当前来源/执行资格与摘要。静态拒绝不进入 schema repair/确定性降级，不提交本次合成报告或成功事件。来源为空且当前资格合法的合成保持可用。该摘要不证明远程原文内容，也未成为持久 ContextSnapshot/Runner 契约。

`add_source` 的原外置读取/upsert 竞态由真实 SQLite 线程测试复现：两个竞争身份先观察不存在，可能各自成功并覆盖对方。现在身份读取、冲突检查和写入处于同一短写事务；同一身份保留首条记录及 created_at，竞争身份或 row/payload ID 不一致明确冲突。原 Source 模型和公开 schema 不变，也不新增第二套来源存储或状态机。

新增 **17** 项行为场景，包含正常交付、旧引用、名额等待、模型返回期间变化/撤权、并发冲突、存储 ID 不一致与重开幂等。Python 3.12/3.13 的 37 组关联回归各 **650 passed**，耗时 **300.50/300.52 秒**；Ruff 和 diff 检查通过。精确结果见 ADR 0047 和 `docs/verification/2026-10-07-current-local-synthesis-source-identities.json`；未调用真实模型/外部系统、执行浏览器验收或重跑全后端，API 与前端不变。

返回后的 finalizer 原子封存资格复查、通用 Source external_id/版本/原文 hash/归档/墓碑与连接器水位继续实施。完整上下文、普通 Run 累计请求/成本、旧输入修复、部署级解析权限、Session/Runner、过程复用和真实模型/企业验收仍按主方案推进；阶段 3–5 保持实施中。

### 19.39 阶段 4：普通/Universal 合成的原子封存

已复现并修复合成返回后、最终写入前删除来源仍成功，以及 Universal synthesis Artifact 先独立提交、随后终态事件失败留下 sealed 产物的问题。合成前冻结内部 Run 执行身份、计划/节点结果与 Source 引用记录摘要；现有终态写事务重新检查当前用户/项目/成员资格/线程、期限、执行代次和全部冻结输入，再把 Universal Artifact、Plan/Run、Inbox 收敛与事件一起提交。Source 选择和模型发送共享同一快照读取、数量/载荷限制及引用身份规则；不新增公开授权字段或第二套来源存储。

当前 Source、用户或项目发生变化明确拒绝，不把 admission refusal 降级成 Universal partial。旧执行的失败处理不能修改新 writer 或新计划版本；普通终态写入也在事务内核对调用者执行身份。合法部分交付和未知外部副作用保留原规则，既有节点结果与工具证据不因本次封存失败被删除。

新增 **14** 项场景；确定性专项已验证来源/授权/期限/代次、计划和节点结果变化、Universal 正常封存、明确拒绝及真实 SQLite 事件失败回滚。Python 3.12/3.13 的 44 组关联回归各 **719 passed**，耗时 **319.80/321.30 秒**；最终聚焦的六组回归 **120 passed / 38.13 秒**，Ruff 与 diff 通过。精确回归与文件摘要见 ADR 0048 及 `docs/verification/2026-10-07-atomic-standard-synthesis-finalization.json`。原抽象 finalizer 测试补齐实际主体/项目；没有通过跳过门禁保留未授权的成功样本。API 与前端不变，未重跑全后端、浏览器或调用真实 Provider/企业连接器。

本项完成本地 finalizer 的返回/提交窗口；通用 Source external_id/版本/原文 hash/归档/墓碑、原生来源与工具证据的完整失效传播、持久 ContextSnapshot、后续输出投影当前权限和 Runner 实际交付仍待实现。统一上下文、累计预算、过程复用、旧输入修复、部署级解析权限及真实模型/企业验收继续执行；阶段 3–5 保持实施中。

### 19.40 阶段 4：Runtime 结果投影的当前权限与私人记忆策略

已复现并修复终态投影在写入前撤权、writer 替换或记忆策略关闭后仍保存的问题。聊天、私人记忆、Session 标记、线程更新时间、投影回执和事件复用原写事务；实际提交及回执重放重新核对当前主体/项目/成员/线程和预期 Run 执行身份/正文。合成完成调用携带 executor 返回的封存身份，不能因重新读取当前 Run 而接管新的 writer；已封存事实不因投影拒绝被修改为失败。

自动记忆在事务内读取当前 Skill/Standard Plan 的显式策略，关闭策略或 Skill 只跳过新记忆，合法聊天继续保存。手动 HTTP 保存携带刚验证过的 Run，检查后正文变化或撤权返回原 unavailable 结果。先手动保存、后恢复聊天投影保留原记忆和标题；本人运行记忆已遗忘/非活动时不重建，也不把重放对象的其他 owner/线程正文当作原投影。

私人 Session 标记核对当前归属，拒绝未证明的旧正文和同 Run 的新 generation；其他 writer 或已撤回 Session 保持不变。共享 Task 线程要求实际 Task/Thread 关系，交付不接管请求者的私人 Session、不改变 Task/Review 状态。已经合法封存的结果可以在执行期限之后恢复投影，当前访问权限仍必需。真实 SQLite 事件失败会回滚整批新投影；并发和数据库重开保持幂等。

新增 **34** 项确定性场景。最终 Python 3.12/3.13 的 **51** 组关联回归各 **807 passed**，耗时 **332.35/332.34 秒**，无警告；Ruff 与 diff 检查通过。精确最终结果与当前文件摘要封存在 ADR 0049 及 `docs/verification/2026-10-07-current-authority-runtime-output-projection.json`；旧测试补齐实际主体/项目/线程，不跳过权限检查。公开 API/schema 和前端不变，未调用真实 Provider/企业连接器，也未执行浏览器或全后端验收。

本项完成投影的当前权限、执行身份、记忆策略及目标归属切片，尚未持久化合成 Source/Plan/节点输入证明，不能据此证明封存后外部原文或引用仍有效。完整来源/记忆血缘失效、持久 ContextSnapshot、Runner 实际交付、累计预算、统一上下文、过程复用、连接器、旧输入修复及部署级解析权限继续开发。真实模型质量和企业试点仍按实际依赖验收，阶段 3–5 保持实施中。

### 19.41 阶段 4：直接 SDK 状态提交与旧 writer 隔离

受控真实 SDK 复现并修复旧 writer 被 Session 拒绝后，错误/取消处理重新读取并终止新 writer，以及模型返回后撤权/超时仍封存成功的问题。状态与事件复用短写事务，核对原执行身份、generation、契约/定义版本、Plan 关联和 Runner；目标更新也不能转移 writer。重试规划显式携带合法关联变更前的 Run，原流程保留。

直接完成在事务内复查当前 Session/来源、主体、项目/成员、线程和期限。审批暂停携带原 Run 与 Session checkpoint，在实际提交前核对版本/内容/资格；变化时不写入旧暂停或新收件箱。直接聊天与审批恢复的终态检查进入异常处理，同一 writer 的拒绝正确收敛为失败，旧 writer 的异常/内部取消不改变新执行。恢复失败清除旧暂停状态；外部非读取工具结果未知保持原保守结果，不自动重试副作用。用户主动取消仍针对当前执行。

终态 Run、收件箱关闭及事件一起提交；故障整体回滚，保留原状态并支持合法重试；并发完成仅一条终态事件。新增 **36** 项场景的聚焦验收 **36 passed / 75.39 秒**；早期七组关联回归 **152 passed / 101.29 秒**。最终 Python 3.12/3.13 的 **57** 组关联回归各 **932 passed / 无警告**，耗时 **408.45/407.78 秒**；Ruff 与 diff 通过。精确结果、开发阶段未通过记录及文件摘要见 ADR 0050 和 `docs/verification/2026-10-07-fenced-direct-sdk-state-transitions.json`。公开 API/schema 和前端不变，未执行全后端/浏览器或真实 Provider/企业连接器验收。

此项完成直接 SDK 本地状态写入切片，不建立持久 lease、独立 SDK producer 取消语义或远程实际交付证明，也不完成全部规划/节点取消的 writer 管理、累计预算和完整生成输入失效。统一上下文、Source 生命周期、过程复用、连接器水位、旧输入修复及部署级解析权限继续开发。真实模型质量/企业试点仍按实际依赖验收，阶段 3–5 保持实施中。

### 19.42 阶段 4：SDK producer 完成确认与节点取消传播

已复现并修复锁定 SDK 在模型 producer 取消后，事件流正常结束、直接 Runtime 因而提交空成功结果的问题。消费事件后等待 SDK 已公开的 producer task，沿原取消异常传播，再进入既有 finalizer；不以正文是否为空或事件数量推断完成，不修改 SDK、增加新状态或盲目重试。

普通 DAG 的独立子任务取消会通知父任务，并由原 TaskGroup 停止和等待兄弟任务、释放容量。取消领取时冻结 Run 身份和 Plan 版本，处理与实际事务都拒绝接管新 writer、Plan 或 Runner。共享瞬时 Run 身份补入 Runner，已有合成快照保留专门准入错误，不因提前通用冲突检查掩盖来源/输入变化。已有 Memory/Source 的持久 canonical hash 不重算。

实际 Runtime 批准 Plan、直接/恢复、原始/原子流、正文片段后取消、旧 writer、晚提交、兄弟任务、容量及未知外部写入均有确定性场景。新增 **20** 项行为；初期六组聚焦回归 **139 passed / 748.84 秒**，修正后的四组聚焦回归 **73 passed / 51.02 秒**。初轮双版本发现合成快照拒绝分类回归及 Python 3.13 并发准入观察超时，已修复后重跑，不能将旧结果计为最终通过。

队列测试以真实已提交的预算事件同步代替高频 SQL 轮询，保留原 10 秒超时、主体撤权与交付断言；同负载下五项检查 **5 passed / 12.08 秒**，临时任务/线程诊断已移除。最终 Python 3.12/3.13 的 **58** 组关联回归各 **952 passed**，耗时 **440.90/440.01 秒**，无警告；Ruff 与 diff 通过。精确结果、开发阶段未通过记录与文件摘要见 ADR 0051 和 `docs/verification/2026-10-07-settled-sdk-producers-and-node-cancellation.json`。公开 API/schema 与前端不变，未执行全后端、浏览器或真实 Provider/企业连接器验收。

此项证明当前锁定 SDK 的本地取消和普通 DAG 取消收敛，不提供跨进程 lease、远程实际接收回执或全部规划/审批/节点提交的执行身份管理。累计预算、统一上下文、完整来源/记忆失效、过程复用、连接器、旧输入修复与部署级解析权限继续开发。真实 Provider/企业质量验收按实际依赖推进，阶段 3–5 仍实施中。

### 19.43 阶段 4：冻结节点执行身份与审批恢复隔离

已复现节点审批恢复的错误/取消处理终止新 writer、旧结果/审批中断提交到新执行、SDK 恢复期间领取被替换的审批，以及节点提交后接管新 writer 继续合成的问题。Runtime 与 executor 携带原 Run/Plan，在真实领取、节点结果、暂停、恢复和取消事务内核对执行身份、Plan 输入与节点尝试。显式用户取消仍作用于当前执行。

Plan 和节点执行摘要只冻结执行定义，正常状态、尝试与时间沿用原 CAS；摘要不改动持久 Memory/Source hash。executor 的循环、容量等待后的领取及审批中断返回都拒绝旧定义；合法已提交结果保留，后续执行传递原身份。错误/冲突收敛不能接管新 Plan、节点或 writer；未知外部写入保留原保守结果且不自动重试。

关联检查暴露并修正两处兼容性回归：合法终态节点可在父任务取消时保留，新活跃尝试仍拒绝旧提交；Runner 节点的父 Run 设备标记可随各节点租约更新，DAG 控制面仍冻结 generation/契约/定义，终态保留当前标记。服务端/直接执行继续严格比较 Runner；不同设备交付和 Runner 模式的旧 generation/输入另有专项验证，不宣称远程 lease 的完整输入证明已完成。

新增 **54** 项确定性场景。初期七组聚焦回归 **169 passed / 225.97 秒**；修正终态节点后的四组 **131 passed / 113.29 秒**，修正 Runner 设备标记后的四组 **77 passed / 93.82 秒**。最终 Python 3.12/3.13 的 **60** 组关联回归各 **1,011 passed**，耗时 **529.70/530.18 秒**，无警告；Ruff 与 diff 通过。精确最终结果、未通过的开发记录、fixture 修正和当前摘要见 ADR 0052 与 `docs/verification/2026-10-07-frozen-node-execution-and-approval-identity.json`。公开 HTTP API/schema 与前端不变，未执行全后端/浏览器或真实 Provider/企业连接器验收，受控 Runner 路由测试不证明实际模型输入交付。

跨进程 lease、完整规划/到期审批状态管理、累计预算、持久输入/来源失效证明、远程节点 generation/输入证明与实际交付、统一上下文、过程复用及连接器继续实施；真实 Provider/企业质量仍按实际依赖验收。普通 Run 当前只有逐请求预算，持久累计模型预留/结算仍只用于 DeepSearch，后续补齐普通 Run 的累计调用/用量及未知结算；阶段 3–5 保持实施中。

### 19.44 阶段 4：普通 Run 的持久累计模型预算

已复现并修复审批恢复和 Session 压缩绕过同一 Run 的模型调用上限。普通本地规划、节点、审批恢复、合成与压缩共用有界 SQLite 账本，策略在首次预留冻结；不复用具有独立恢复规则的 DeepSearch 账本。默认 32 次调用、256k accounted tokens、65,536 输出 tokens、相同完整请求三次尝试；配置和适用范围见 ADR 0053 与 `.env.example`。

实际取得容量后先重复完整请求准入，再以冻结执行身份原子预留，预留成功才提交 Memory 使用回执。已报告的一致正 usage 按实际结算；失败、取消、缺失、畸形和 SDK 默认零值保持未知与全部预留。只有适配器调用前明确准入拒绝才释放本次未发送预留；重开、等待或 TTL 不退款。模型工厂默认关闭隐藏 HTTP 重试，各 SDK 请求/重试单独计量。超过请求上限的真实消费先记录再拒绝，不截断账本。

账本与安全元数据事件原子提交，重复结算不重复计量，并发请求不能争抢同一剩余额度。合法旧节点结果保留；预算原因可见，晚到 usage 只结算原调用、不改变新 writer。请求身份只存摘要，不存提示词/工具参数/凭据，不修改 Memory/Source 持久 hash 或公开 HTTP schema。

新增 **25** 项确定性场景，专项 **25 passed / 16.05 秒**。最终 Python 3.12/3.13 的 **67** 组关联回归各 **1,096 passed**，耗时 **560.11/558.97 秒**，无警告。完整请求晚变更错误优先级曾有回归，已修复并通过三组 **53 passed / 23.06 秒**； fixture 失败和开发结果保留，精确最终结果与当前摘要封存在 ADR 0053 及 `docs/verification/2026-10-07-durable-ordinary-run-model-budgets.json`。Ruff 与 diff 通过；本轮未执行浏览器、真实 Provider/企业连接器或全后端验收。

继续补齐有效价格映射与费用上限、工具/自动巡检预算统一、远程实际计量和交付；普通模型调用/token/output 累计切片不代表完整成本控制已完成。统一上下文、持久规划/审批恢复、完整 Source/Memory 失效、过程复用、连接器与真实模型/企业质量仍按主方案推进，阶段 3–5 保持实施中。

### 19.45 阶段 4：普通 Run 的冻结价格与费用估算门禁

普通本地模型请求复用 ADR 0053 的持久账本，按实际 SDK model name 精确匹配声明价格，在首次预留时冻结整个价格表和费用策略。可选货币/费用上限必须成对配置，价格缺失、未生效、到期或货币不匹配时在适配器调用前拒绝。费用单位、整数费率、版本及有效时间见 ADR 0054 和 `.env.example`；不引入新服务或第二套预算状态。

有可信正 usage 时按冻结费率估算，未知消费保留原预留；明确未发送的准入拒绝可以释放本次预留，但不重置价格。实际超限消费先如实记录再拒绝结果，数据库重开和晚到回执不重新定价。没有价格或混合货币的总费用保持未知，既有无价格账本不补算。容量等待后检查有效期；普通 finalizer、直接运行和审批恢复保留安全的准入错误码。

新增 **41** 项确定性场景，专项 **41 passed / 33.02 秒**；最终 Python 3.12/3.13 的 **68** 组关联回归各 **1,137 passed**，耗时 **676.81/673.15 秒**，无警告，86 项执行源码摘要在验收期间未变化。开发中未定价预留时间戳曾影响原接口值、空调用上限曾被忽略，均已修复；计划与直接/审批终态错误原因的受控 RED 也已修复。fixture 问题单独记录，不作为功能 RED；Ruff 与 diff 通过。精确结果与当前源码摘要封存于 ADR 0054 和 `docs/verification/2026-10-07-frozen-ordinary-run-model-costs.json`。

本项只提供声明价格下的普通本地模型费用估算，不能当作 Provider 账单；缓存优惠、税费、工具费、后台学习、DeepSearch/自动巡检统一策略和远程实际计量仍未完成。统一上下文、过程复用、持久规划/审批恢复、完整 Source/Memory 失效、连接器及真实模型/企业试点继续实施，阶段 3–5 保持未完成；阶段 6 仍按实际容量触发条件推进。

### 19.46 阶段 4：普通工具的冻结额度与实际调用身份

已复现并修复工具上限不能按配置收紧、旧 Run 保存归零计数，以及旧模型返回或容量排队接管新 writer／Plan／节点尝试的问题。普通 SDK 工具复用模型／费用账本的冻结策略，现有 Run 计数仍是唯一工具次数权威；`AGENTMESH_RUN_MAX_TOOL_CALLS` 默认 24，只能收紧到整数 1–24，审批、重开和配置变化不重置。工具准入的计数、策略与安全事件原子提交，事务失败一并回滚。

Runtime 携带原 Run/Plan 摘要与节点 attempt；SDK hook 在准入事务核对，原生工具、Skill 资源及 MCP 在容量等待后、实际 claim 事务再次核对执行和期限。排队后被拒绝的已准入尝试保留额度，不宣称真实消费。完整 Tool-definition/grant 版本原子绑定与 MCP 调用 ID 的全面审批恢复幂等仍未完成。

关联验证修正了两处错误收敛：已推进节点的 CAS 冲突不能终止父 Run 新执行；governed MCP 异常不能被 SDK 转成可继续执行的工具文本。MCP 现在停止异常调用，Runtime 只恢复 SDK 类型异常直接原因中的自有静态准入码，不解析 Provider 文本；未知外部写入不自动重试。DeepSearch 保持原独立计量。

新增 **23** 项确定性场景；6 组工具关联回归 **103 passed / 62.34 秒**。最终 Python 3.12/3.13 的 **73** 组关联回归各 **1,189 passed / 636.87、639.62 秒**，无警告，300 项执行源码／依赖摘要在验收期间未变。补充巡检测试发现固定日程与真实审核时钟混用的日期依赖，统一时钟后 Python 3.13 的 6 组补充回归 **107 passed / 16.01 秒**。原失败与 MCP fixture 超时分别保留，不作为最终成功或功能 RED；Ruff 与 diff 检查通过。精确结果和当前摘要见 ADR 0055 及 `docs/verification/2026-10-07-frozen-ordinary-tool-quotas.json`。

本轮没有修改公开 HTTP schema、前端或部署，没有执行真实 Provider／企业连接器、浏览器或全后端验收。工具费用、巡检／后台统一策略、远程实际计量与交付继续实施；统一上下文、记忆问答／抽取质量、已验证过程复用、持久规划／审批恢复、完整 Source/Memory 失效及真实连接器仍未完成。阶段 3–5 保持实施中，阶段 6 仍按容量触发条件推进。

### 19.47 阶段 3/5：版本化来源观察与当前来源检查

现有 Source 增加可选 `SourceSnapshotV1`，记录稳定 external_id、不透明外部版本、原文 UTF-8 SHA-256、带时区观察时间、服务端 revision 与 active/archived/deleted/unavailable 生命周期。无快照的旧记录继续省略字段，不给旧引用补造版本，不重算既有 Source/Memory 摘要。`observe_source` 在短写事务中重读 owner/项目权限，校验原文和 CAS，原子提交来源与安全审计；同版本换正文、过期变化、并发旧 CAS、revision 溢出和删除后的复活被拒绝。匹配当前 revision 的完全相同观察保留首次时间与审计。

当前来源检查进入现有 Memory 检索、准备后交付、SDK 容量等待后的回执、父文档片段、文档事实证据与学习结果提交。来源更新或不可用时只停止使用，不伪造 Memory 治理变更。资料 HTTP 读取同时核对当前文档和来源摘要；带快照的镜像暂不允许本地编辑。事实确认命令重放不返回失效证据；晚到抽取不能复活候选，原学习计量规则保留。

已选来源加入原有私有协作信号依赖，变更与正文/检索投影撤回同事务提交；相同观察和未选来源变化保留有完整证明的信号。启动时撤回缺少已登记直接 Memory 来源或父文档来源依赖的历史自动信号，不补造旧证明。生成期间来源撤回拒绝晚发布，审计失败同时回滚来源与撤回。

新增 **55** 项确定性场景，专项 **55 passed / 10.49 秒**；7 组关联回归 **221 passed / 49.36 秒**。最终 Python 3.12/3.13 的 **110** 组关联回归各 **1,837 passed / 1,077.79、1,078.84 秒**；各有 5 条 PDF 依赖的既有弃用提示，353 项执行源码、测试和依赖摘要在验收期间未变。SDK 持久上下文的严格时间恢复、旧来源升级发布依赖、事实命令重放及升级启动失效缺口均通过功能复现后修复。fixture 问题单独记录；第一次双版本回归因补齐启动兼容检查主动中止，不算最终通过。公开 Source schema 增加可选快照，前端 API 类型生成、构建、bundle、Ruff 与 diff 检查通过。精确日志/源码摘要封存在 ADR 0056 及 `docs/verification/2026-10-07-versioned-source-observations.json`。

这只完成来源协议基础和局部当前来源检查。普通上传仍使用原来源契约；原生引用别名、完整间接祖先/Session/Runner/Artifact 失效、Source 与资料镜像原子同步、ConnectorSyncCursorV1、分页增量和真实 Provider 权限/删除发现继续实施。真实读取试点优先考虑当前仓库 `docs/` 与 GitHub Issues；没有新建业务系统，也尚未接入真实连接器。统一上下文、过程复用和模型质量仍按主方案推进，阶段 3–5 保持未完成，阶段 6 按实际容量触发。

### 19.48 阶段 3/5：手动真实来源同步与原始来源关联引用

首条真实读取链路已接入。新增项目连接器 API，按服务端配置读取仓库 UTF-8 文档及 GitHub Issues；复用现有 Source/Document/索引，和 owner/项目隔离的 ConnectorSyncCursorV1 原子提交。外部读取期间不占写事务，实际提交重读当前主体、项目、来源 CAS、游标及配置。用户撤回的镜像不因外部更新恢复。同步是一页一次的显式操作，不改变本地 Task，不自动确认或共享资料。

Run 引用增加可选 SourceOriginV1，绑定原始 Source 的 revision、正文和完整记录摘要，保留稳定外部身份；来源更新或不可用会拒绝旧记忆和合成引用。旧引用省略新字段，已有摘要不重算。GitHub 真实读取复现 canonical repository Link 加 after cursor 的分页差异，修复后在隔离临时数据库同步了 **3 份仓库文档、9 个 Issue**；GitHub 共 3 页，正文摘要均验证一致。

新增功能检查 **30 passed / 3.86 秒**；13 组直接关联回归共 **295 passed / 54.45 秒**，Python 3.13；API 类型生成、前端构建和 bundle 检查通过。按用户反馈收敛验证成本，本轮没有重复大范围双版本回归，完整回归集中到阶段验收。具体行为、配置、限制及证据见 ADR 0057 和 `docs/verification/2026-10-07-manual-source-sync.json`。没有修改业务数据库、启动服务、调用真实 LLM 或完成企业团队试点。

本项只完成手动分页读取、内容去重、原子镜像和关联引用；since 增量水位、Provider ACL/删除/遗漏发现、持久失败状态、连接器禁用失效、游标配置迁移/重置、后台限速/取消与前端同步操作仍待开发。完整间接血缘、统一上下文、过程复用及模型质量继续执行，阶段 3–5 保持未完成；阶段 6 按实际容量触发。

### 19.49 阶段 3/5：增量读取、失败恢复与来源同步界面

GitHub 各页冻结 since 边界，最后一页才推进水位，下一轮重叠 60 秒并按内容去重。本地目录、首轮及用户发起的一日后复核使用完整扫描；完成后将本轮未见旧来源标记 unavailable。读取失败持久记录安全状态和新游标版本；访问/目录不可用时停止旧来源引用，恢复后从第一页完整读取。临时故障保留最后观察，增量缺席不推断删除。

Knowledge 已提供同步、继续、重试与完整复核。同步镜像只读，显式导入绑定当前版本。Ego Lite 在临时服务完成六份资料的两页同步及一份资料导入；真实公开 GitHub 零变化增量读取保留文档版本并推进水位。直接受影响后端 **37 passed / 7.42 秒**，前端 **4 passed**，类型构建、bundle 和定向 Ruff 通过。完整回归、双版本回归和真实 LLM 验收未运行；不扩大本轮验证范围。见 ADR 0058 和 `docs/verification/2026-10-07-incremental-source-sync.json`。

这完成手动增量与失败恢复，仍需连接器禁用/重置/配置迁移、后台限速/取消、完整 Provider ACL/删除发现和观察时效策略。完整间接血缘、统一上下文、过程复用及模型质量继续实施，阶段 3–5 保持未完成，阶段 6 按实际容量触发。

### 19.50 阶段 3/5：版本化连接器禁用、重置与取消

复用现有游标支持 disable/reset/cancel。禁用和重置在同一授权写事务使旧来源失效；重置采用当前同 provider/namespace 配置并清空水位，完整重读后才恢复来源。取消保留最后观察，更新游标版本，正在读取的旧页不能提交。API 状态保留配置移除的本人旧游标，Knowledge 提供禁用、恢复重置、取消与配置变化提示。

直接关联后端 **42 passed / 6.01 秒**；前端针对当前状态/操作检查，API 类型、构建、bundle 和定向静态检查记录于 `docs/verification/2026-10-07-connector-controls.json`，设计见 ADR 0059。本轮不重复完整/双版本回归、真实 Provider 或浏览器验收。

取消尚不能中断已发出的 HTTP 请求，第一页提交前尚无持久游标；移除配置后的自动失效、后台限速/租约/取消、完整 ACL/删除发现与观察时效继续开发。不同仓库 namespace 采用新游标，旧连接器显式禁用。完整间接血缘、统一上下文、过程复用及真实模型质量仍未完成，阶段 3–5 保持进行中。

### 19.51 阶段 3/5：当前连接器绑定与配置失效协调

规范连接器来源的共用 Source 检查现在证明精确 owner/workspace/project/provider/namespace 游标、启用状态和当前运维绑定。配置移除/更换后，检索和引用无需等待用户点击即可拒绝旧来源。服务启动与项目连接器状态读取持久停止旧游标、失效来源并经既有依赖撤回投影；还原配置不会自动恢复已失效来源，仍需重置并完整读取。Source/Memory 原摘要不重算，可信程序 Reader 保留显式本地配置契约。

直接关联 **101 passed / 12.65 秒**，启动检查 **14 passed / 6.05 秒**；前端状态、类型构建和 bundle/定向静态检查记录于 `docs/verification/2026-10-07-connector-binding-authority.json`，设计见 ADR 0060。未重复全量/双版本回归、真实 Provider/模型或浏览器验收。

引用检查不等于每次实时查询远端 ACL，也不等于即时删除所有历史输出。运行期间持久协调目前随状态读取触发，后台周期协调、首次页领取/租约、限速/重试/取消、完整 ACL/删除发现及观察新鲜度继续实施。完整间接血缘、统一上下文、过程复用和真实模型质量仍未完成；阶段 3–5 保持进行中，阶段 6 按实际容量触发。

### 19.52 阶段 3/5：页读取持久领取、首次取消和租约恢复

每页在外部读取前保存授权领取、随机身份、attempt version 和 90 秒租约；首次页可查看和取消，未过期领取拒绝重叠读取。终态资料写入重复实际权限、完整领取与期限检查，来源/镜像/索引/终态游标保持原子。取消/禁用/重置清除领取，旧结果和清理均不能覆盖替换执行。启动和状态协调恢复过期领取，保留最后观察与分页边界。

数据库重开恢复和旧过期 Reader 对新成功页的隔离已验证。直接关联 **49 passed / 5.74 秒**，前端 **5 passed**；类型生成、构建/bundle 和定向静态检查通过。原权限撤销检查仍拒绝来源提交，仅结算先前授权且精确匹配的私有领取。见 ADR 0061 和 `docs/verification/2026-10-07-connector-page-claims.json`。本轮不重复全量/双版本/真实 Provider 或浏览器检查。

下一步实现后台有界调度、周期协调、限速、Retry-After/受限重试与后台取消；当前取消仍不能直接中断 HTTP 请求。完整 ACL/删除发现、观察时效、间接血缘、统一上下文、过程复用及真实模型质量继续实施，整体阶段保持未完成。

### 19.53 阶段 3/5：显式后台同步、持久等待与有限重试

现有 SQLite 游标接入单进程生命周期 Worker；服务端默认关闭，每个用户来源还需显式开启。每轮最多读取一页并分页继续，完整周期结束后按配置间隔再读；周期协调配置失效与过期领取。读取沿用当前权限、完整领取与租约事务，停止/暂停/禁用/取消阻止旧结果提交。空闲自动计划在重启后保留；关闭时取消的在途计划需显式重新开启，崩溃遗留的过期领取可按受限重试恢复。

临时读取故障最多自动尝试三次，间隔 5/30 秒，权限与非法响应不自动重试。GitHub 限流遵守 Retry-After/主限流恢复时间，无有效等待头的已识别限流至少等待一分钟。来源等待持久保存；同 provider/configuration 的运维绑定共享读取准入等待，手动调用、其他用户和同配置重置均不能绕过。失败保留最近成功观察，已有权限失效规则仍撤回不可用资料。Knowledge 已提供开启/暂停、下一次读取、等待时间和自动资料刷新。

本轮直接关联后端 **57 passed / 9.33 秒**，前端 **6 passed**；类型生成、生产构建/bundle 和定向 Ruff 通过。见 ADR 0062 与 `docs/verification/2026-10-07-connector-background-sync.json`。按用户反馈，检查通过后停止扩大验证；没有全量/双版本/浏览器/真实 Provider 或模型检查，也没有部署。

后台调度这一切片已交付。直接中断已发出的 HTTP、完整远端 ACL/删除发现、按来源类型的观察时效、完整间接血缘、统一上下文、过程复用及真实模型/团队验收继续实施。阶段 3–5 与整体目标保持未完成，阶段 6 按实际负载条件触发。

### 19.54 阶段 3：统一 Run 上下文入口与共享组件预算

本地普通/Standard 执行的核心偏好与查询路由收敛到 MemoryContextService.assemble_for_run。复用 SQL 状态、结构化事实、已验收过程和普通检索的既有权威；偏好完整渲染优先占用默认 8000 字符的共同额度，资料正文、标题、引用与外围提示使用剩余空间。普通摘要可有界缩短，事实/过程保持完整或整体丢弃；不足以放入 SQL 诊断时记组件预算丢弃。普通私聊仍只自动使用本人核心偏好，observe/off 不交付资料或记使用。

完整请求的输入、近期完整 Session、平台/Skill 指令、工具 schema 和真实工具输出继续受现有最终 SDK 字符/token 预算检查；组件预算不代替完整请求预算。交付沿用既有私有快照、当前来源/版本检查与实际模型边界回执，不改旧 Source/Memory/快照 hash 契约。过程经验捕获和目标/能力/审核校验链路已有界面与 API，本轮复用这些能力。

新增共享预算、丢弃优先级、私聊/observe、SQL 路由与精确 SDK 回执检查，并选择直接相关 Runtime 验证：**18 passed / 24.32 秒**。注入模式下 Standard 节点/来源/合成链路另 **1 passed / 3.37 秒**；定向 Ruff 与 whitespace 检查通过。见 ADR 0063 和 `docs/verification/2026-10-07-shared-run-context-assembly.json`。没有界面/API 返回变化，没有重复前端构建、全量/双版本、浏览器或真实模型检查。

完整 ContextAssembler 尚未全部完成：全请求动态优先分配/压缩、可用 tokenizer 下的模型估算、远端 Runner 对齐、完整 Session/Artifact 血缘和更完整过程复用仍继续开发。观察时效、远端 ACL/删除策略、真实质量与团队验收也仍在方案范围内。阶段 3–5 和整体目标保持未完成。

### 19.55 阶段 3：按实际请求压力压缩本地 Session

本地普通执行入口先组装本次目标、平台/Skill/记忆指令、已启用原生/MCP 工具 schema 和输出预留，再按同一完整请求计量判断历史是否需要压缩。少于 20 项的大消息也能触发；请求已能容纳历史时直接继续。固定请求本身超预算时直接拒绝，避免无效的压缩模型调用。

保留区从完整 user 回合起点选择，并保护跨越边界的工具调用/结果及未完成调用。旧消息只交给有界摘要器，当前目标留给主执行；摘要仍经过大小、内容与完整请求预算检查，随后通过现有 Session 版本 CAS 替换，避免覆盖并发新增内容。旧显式阈值/强制压缩接口保持兼容。

验证只覆盖实际运行入口、少量大消息、并发替换、工具单元与完整请求准入，合计 13 项独立行为通过。发现旧强制压缩路径的兼容性问题后只复查失败单项；定向 Ruff/whitespace 检查通过。记录保存在 `/tmp/agentmesh-request-pressure-{runtime-green,focused,compatibility}.log`。不新增独立验收文档，不重复全量、双版本、前端、浏览器或真实模型检查。

本项完成本地首请求的历史压缩接入。记忆/工具输出的动态额度分配、模型 tokenizer、远端 Runner 的结构化 Session 对齐、完整间接血缘及真实质量/团队验收仍在开发或等待实际依赖；阶段 3–5 和整体目标保持未完成。

### 19.56 阶段 3：Runner 结构化 Session 传输与原子回写

新版 CLI 通过既有能力列表协商 `structured-session-v1`，普通执行领取 V2 envelope，完整携带原有私有 SDK Session 的 user/assistant、工具调用 ID/参数与结果。旧客户端和 Standard 节点仍使用 V1，不重算旧 hash。云端在有效租约内检查当前 owner/project/thread、写入归属与已归档 Memory 来源，只用 SQL 导入未同步的规范聊天消息；本次输入按已有规范消息 ID 排除，不靠正文相同判断。超出载荷限制明确报错，不截断工具单元。

Runner 将结构化消息直接交给 SDK，复用本地完整请求预算与回合/工具单元压缩。V1/V2 与 Standard 节点也统一限制每次实际请求的指令、schema、输出预留与后续工具结果。V2 完成携带 SDK 实际 continuation items，云端在同一事务内检查冻结快照 hash、当前 Session 版本/来源、租约与运行状态，然后回写 Session 并提交原有 Run/dispatch/lease 幂等完成回执。保留原 Memory 血缘，事件只写版本/hash/数量；平台角色注入、断裂工具配对、凭据正文、旧版本和降级提交均拒绝。原有本地 spool 支持版本化完成请求的持久化与重开，有效租约内重发不重跑模型。

合计 16 项独立关键行为通过，覆盖 HTTP→真实 SDK 输入→完成→重复完成→下一会话、压缩/完整请求、并发 CAS、角色注入、spool 重开及 V1/CLI 兼容。只运行直接受影响检查；定向 Ruff/whitespace 与 API 类型生成通过，没有全量、双版本、浏览器、前端构建或真实模型/Provider 调用。新增契约决策见 ADR 0064；原 Runner 工作区保留。

本项完成普通 Runner 的结构化 Session 往返和请求预算。远端自动 Memory 注入/精确交付回执、每次模型请求前的实时云端权限门、远端 Run 累计成本、未完成模型过程的重启恢复、审批及完整间接血缘继续开发；真实 Provider/试点/质量和条件触发的阶段 6 仍按实际依赖执行，整体目标保持进行中。

### 19.57 阶段 3：Runner 自动上下文、实时准入与响应后交付

新版 CLI 协商 `context-handoff-v1`，普通执行和 Standard 节点使用 V3 envelope，复用已有 Session、上下文快照和 spool。领取任务只准备记忆，不增加使用次数。每次实际 SDK 请求（包括工具返回后的下一轮及压缩）先检查完整请求预算并取得云端授权，重读有效租约、Run/Session/节点执行身份、当前主体/项目权限、Skill/工具授权和记忆来源。旧客户端契约/hash 保留，领取时不下发新增自动记忆及核心偏好。

模型返回响应后才持久化并发送交付确认。精确记忆版本的使用回执与交付状态原子提交；空上下文和压缩确认不造记忆回执，模型调用失败不算已交付。重复确认不重复使用。成功完成要求已确认执行交付，并再次检查当前上下文；普通执行的 Session 回写保留本次已交付记忆血缘。断线确认排在完成之前，重启 CLI 在有效租约内补交，无需重跑模型。这里依赖已认证 Runner 对实际响应的报告，没有宣称独立验证 Provider 收到请求。

将 Standard 节点检查接入实际 SDK 后，发现旧完成 hash 无法接受 SDK 浮点置信度；新增节点完成 V2 契约处理正常 JSON 浮点结果，旧 V1 hash 不变。直接 HTTP→SDK→交付→完成、断线队列重开及同设备/跨设备节点检查通过；受影响的旧接口、service/spool/CLI 和本地交付兼容检查通过。只做定向检查与 API 类型生成，不增加全量、双版本、浏览器或真实 Provider 验收。决策见 ADR 0065，运行日志位于 `/tmp/agentmesh-runner-context-*.log`。

本项完成上述远端上下文链路。远端累计成本、模型选择策略冻结、未完成模型过程的重启恢复、审批、完整间接血缘、上下文动态额度、tokenizer 和过程复用仍待开发；真实 Provider、团队试点与质量验收按实际依赖推进。阶段 3–5 和整体目标保持进行中。

### 19.58 阶段 3：远端模型调用共享 Run 累计预算与费用结算

V3 的新模型授权在同一 SQLite 事务中预留现有 Run 模型预算并记录 handoff。压缩、执行、后续 SDK 轮次与重试共享调用、token、输出和重复请求上限，也与同 Run 的云端 SDK 调用共享账本；重复授权不重复占用额度，配置变化不扩大已冻结预算。费用复用服务端显式版本化价格，无映射时不伪造金额；配置硬费用上限时缺失/币种不匹配的价格会阻止授权。预留与安全审计一同提交，无第二份成本账本。

响应确认新增可选输入/输出用量，只有正数且与总量一致的报告才按实际 token 结算；旧版仅报总量、默认零、失败或丢失响应保留估计输入与输出上限。成本归原授权尝试，取消/来源撤销后的迟到有效用量仍可结算，但不能恢复上下文交付或成功状态。超限实际用量保留在账本并阻止成功完成；断线队列获知超限后按普通/节点租约提交失败，撤下排队的成功完成请求。既有已签发授权保持旧策略；真实用量/模型身份依赖已认证 Runner 报告，没有独立 Provider 证明。

直接受影响的 HTTP/SDK、跨设备节点、预算持久化/重放、价格冻结、迟到用量和断线超限行为已检查；复用本地预算的并发、结算、重试和原子审计检查验证共享事务提取。已通过检查没有为获得重复绿色日志而重跑。仅更新 API 类型并运行定向静态检查，不扩大到全量、双版本、浏览器或真实 Provider。记录在 ADR 0065 与 `/tmp/agentmesh-runner-budget-*.log`。

本项完成新远端模型授权的累计预算。远端工具额度、模型选择策略冻结、未完成执行恢复、审批、完整间接血缘、上下文动态额度、tokenizer、过程复用和真实质量/团队验收继续推进；阶段 3–5 及整体目标仍未完成。

### 19.59 收尾暂停前的 Runner 工具授权与模型策略改动

CLI、HTTP 客户端、SDK 原生工具与现有授权接口已接通。新领取的文件工具必须协商 `tool-handoff-v1`，每次实际读取前核对当前工具/上下文授权并在原 Run 工具计数中占用额度；云端和远端共用冻结策略，重复授权不重复计数。只传参数与调用身份摘要，读取保持显式目录和凭据规则，并限制实际读取字节数。SDK 包装的准入失败保留静态错误码。缺少该能力的旧客户端领取结果不包含原生文件工具。

新领取执行冻结所选模型及相关定义，首个模型请求绑定声明的实际模型 ID。授权或模型变更会阻止后续读取和成功完成；此身份仍是已认证 Runner 的报告。此前已签发执行保持旧策略。针对性检查覆盖实际 SDK 工具额度、响应后授权撤销、模型切换、旧客户端、文件边界，以及共享事务受影响的并发/回滚；API 类型和定向静态检查通过。没有扩大到全量或真实 Provider 验收。

本项收尾完成，继续开发重心转向项目记忆的用户入口。完整 Runner 恢复/审批、阶段 3–5 和整体目标仍未完成。

### 19.60 项目事实查询的可用入口

Knowledge 新增项目/概念查询表单，复用已有授权事实 API；可按当前、历史时刻或时间区间查询，并可限定当时已记录的信息。用户可直接查询负责人、参与人、决策、约束和记忆中的状态，查看有效时间、记录时间、私有/团队来源与来源版本链接。未知、冲突和证据不足分别解释；实时 Task 进度仍从任务事实查询。查询不调用模型，不增加记忆使用回执。

客户端查询按账户、Workspace、项目和条件隔离；条件变化或查询失败时不展示旧结果，重新查询会核对当前来源。新增前端关键行为和类型检查通过，复用后端已实现的时间/权限语义，没有重复运行既有后端或全量检查。真实项目问答质量、自动学习质量和团队试点仍未验收。

### 19.61 已审核方法进入下一次任务草稿

当前可访问的有效方法详情新增「根据方法创建任务」，将已审核目标带入可编辑草稿；原文不写入 URL，保存和启动执行仍需显式操作。没有审核依据的方法不提供此入口；前端不会自动执行步骤，也不强制绕过服务端当前方法选择。

补齐过程中发现并修复项目上下文缺口：Tasks 读取、巡检和新建任务现在使用指定项目。创建 API 新增可选 project_id，沿用现有项目授权、事务及幂等回执；省略该字段保留原默认项目和旧命令 hash。切换账户/项目清除旧表单，草稿只在相同项目使用。非默认项目的负责人表单保守展示本人；完整跨项目成员选择仍需后续产品完善。

定向检查覆盖指定项目创建、重复提交、未授权项目、旧创建并发、草稿/链接和实际请求载荷；前端类型检查和生成类型通过。浏览器与真实 Provider 仍留到阶段交付。此入口打通从已记录经验到新任务的操作；实际执行继续核对当前条件、工具与来源，未宣称过程复用质量指标已经达标。

### 19.62 当前项目状态与已审核方法共同进入执行

共享上下文原先在 SQL 状态和方法记忆间只选其一。现在状态问题仍先读取当前 Task/Review SQL，再在剩余额度内选取同目标的合格方法。偏好与 SQL 优先，方法的步骤、验证条件和证据保持完整；放不下时省略方法，不用历史记忆替代统计。复用已有 bundle 的独立 SQL/过程字段，没有增加第二套上下文存储或工作流。事实与过程的混合、通用语义选择和完整动态分配仍未完成。

交付时验证两份内容与各自权威；方法使用回执提交前，在原事务写锁内再次核对当前 SQL 状态和方法的审核依据。SQL 不生成 Memory 使用回执，状态变化会阻止旧方法交付。既有快照、审批和模型准入复用两类选择的检查，旧单一上下文契约/hash 保持。

新的真实 SDK 确定性流程覆盖：已通过 Task Review 的方法 → 新建任务 → 显式开始 → 实际 SDK 同时收到当前 SQL 和方法 → 精确方法使用回执，且没有自动执行记忆步骤。状态在回执提交前变化、共同预算优先级及受影响的旧 SQL/过程行为检查通过。ScriptedModel 只证明执行链路，真实问答、两次任务质量与团队采用仍按方案验收；阶段 3–5 和整体目标保持未完成。
