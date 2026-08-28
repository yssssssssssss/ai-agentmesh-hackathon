# 全量内置 Runtime Skill 候选池与 LLM 动态编排开发方案

- 状态：已批准；Phase 0 本地工程验证完成，Phase 1A 首个离线 Profile/检索纵切已通过；生产 Preview/执行仍受发布拓扑、独立审查人与预发布演练门禁阻断
- 日期：2026-08-28
- 适用范围：Agent Runtime v2、Standard、DeepSearch 运行时 v1（FrozenPlan v1/v2）
- 预计工期：核心工程 27~42 个工作日，另需 8~15 个 Profile 审查人日；27 个缺失工具适配另计 3~6 周
- 核心目标：当前 84 个内置 Runtime Skill 全部进入检索全集，由 LLM 从最多 12 个安全、可执行候选中选择并编排最多 6 个节点的 DAG

## 1. 决策摘要

本方案将当前“10 个 Pilot Skill + 25 个业务路由槽位”的受限编排，改造成“全量 Runtime Skill 检索 + LLM 动态规划 + 服务端确定性裁决”。

目标流程：

```text
用户需求
  ↓
意图、交付物与 Task/Scenario 语义分析
  ↓
权限前置过滤
  ↓
在全部 Binding 开启的内置 Runtime Skill 中检索
  ↓
相关性排序与 readiness 分类
  ├─ 最多 12 个可选择候选 → LLM 规划最多 6 节点 DAG
  └─ 不可执行但相关的 Skill → blocked-match；必要输出无替代时才形成 blocking gap
  ↓
服务端校验候选快照、版本、Hash、权限、Tool、资源、DAG 与副作用
  ↓
计划预览/确认
  ↓
节点启动时再次校验并按需加载所选 Skill 指令
  ↓
Bounded DAG 执行
  ↓
基于节点结果与证据生成最终报告
```

核心决定：

1. Runtime SkillDefinition 与其受版本控制的 Capability Profile 共同构成执行事实源。
2. 当前 84 个内置 Runtime Skill 全部进入全局检索语料；单次请求只在当前用户 Binding 开启的范围内检索。
3. Task/Scenario 保留意图、完成标准、证据要求和排序提示，不再充当 Runtime Skill 白名单。
4. 持久化候选上限保持 12，不改成 24；计划节点上限保持 6、深度 4、并发 3。
5. Planner 只接收安全能力卡，不接收 84 份完整 `SKILL.md`；完整指令仅在节点执行前按需加载。
6. LLM 只提出计划，服务端继续决定候选是否合法、节点是否可执行、Tool 是否授权、写入是否需要审批。
7. 复合任务的 Planner 在一次修复后仍失败时必须 fail closed；不得静默生成自由 LLM 报告，也不得把复合任务偷偷降级成单 Skill。
8. 不修改或复活已退役的 Research v2 / Research v3。本方案中的 DeepSearch 始终指当前 `planning_mode=deepsearch` 的 v1 流程。
9. `candidate_skill_ids` 只保留为兼容投影。新 Plan 必须冻结 Planner 实际看到的安全能力卡及 Skill/Profile 身份，不能把 ID 列表当成不可变快照。
10. Scenario 输出在 Task Catalog v2 使用稳定机器 ID、展示文案和受审的 Profile output-kind 兼容关系；v1 保持原文件和 hash，供 legacy Plan 使用。归属、缺口和完成判定不得比较展示文案，也不得交给 LLM 猜测。

当前验收基线是 84 个内置 Skill，但运行时代码不得硬编码 84。Workspace、Project Package 与 Learned Skill 当前缺少可验证的项目归属/审签合同，本期保持显式调用，不进入自然语言 Planner；其自动编排另立 ADR，不在本方案中假定已经安全。

## 2. 当前状态与根因

### 2.1 四个容易混淆的数量

| 口径 | 当前数量 | 含义 |
| --- | ---: | --- |
| 内置 Runtime Skill | 84 | `agentmesh/builtin_skills/*/SKILL.md` 下已安装、可发现的领域 Skill |
| 自动编排 Pilot Skill | 10 | 有完整 Profile 且通过硬编码白名单参加 DAG 规划的 Skill |
| `user-research-v1` 业务槽位 | 25 | Task/Scenario 目录中的业务能力条目，不是 Runtime Skill 总数 |
| 已绑定 Runtime 的业务槽位 | 8 | 25 个业务槽位中配置了 `runtime_skill_name` 的条目 |

另有 11 个 Legacy 平台命令。它们属于兼容命令层，不进入本方案的领域 Skill 池。

当前 84 个 Runtime Skill 中，57 个已有相对完整的工具适配路径，27 个被识别为 `tool_limited`。57 只是“存在适配路径”的静态分类，不表示任意用户此刻都能执行 57 个；最终可执行数仍取决于 Binding、授权、资源、Tool 健康和副作用政策。

### 2.2 当前失败链

以“宠物食品心智设计表达策略研究”为例：

1. Task Router 将请求识别为 `strategy-synthesis`。
2. Scenario 映射要求三个业务 Skill 槽位。
3. 三个槽位均未配置 `runtime_skill_name`。
4. `SkillCandidateRetriever.recommend_for_route()` 将其他 Runtime Skill 全部排除。
5. 候选变为空，最终抛出 `No ready and authorized Skill candidates`。

根因不是项目没有 Skill，也不是 LLM 本身失败，而是业务路由映射错误地成为了 Runtime 候选白名单。

### 2.3 当前必须拆除的耦合

- `PILOT_BUILTIN_SKILL_NAMES` 把自动编排范围固定为 10 个。
- 其余 74 个 Skill 主要只能通过 `$skill-name` 显式调用。
- `recommend_for_route()` 再按 25 个业务槽位与 8 个 Runtime 映射取交集。
- routed 分支直接调用确定性的 `route_skill_draft()`，不会让 LLM 在全量候选中规划。
- 节点启动时只要有 `scenario_id`，就要求 `skill_registry_id` 属于 Scenario mapping；全量检索产生的非映射节点会在执行前失败。
- Plan 编辑、重试、完成检查、Knowledge Binding 和 DeepSearch 冻结都隐含了同一套映射假设。
- 84 个 Skill 中目前只有 10 个具备完整 Capability Profile，无法安全地直接放开其余 74 个。

## 3. 目标、指标与完成边界

### 3.1 功能目标

1. 当前 84 个内置 Runtime Skill 在 Binding 开启后全部参与相关性检索。
2. 自然语言请求即使没有命中业务槽位或命中的槽位未绑定 Runtime，也能找到相关 Skill。
3. LLM 可以按复合任务的不同子目标选择多个 Skill，生成串行或并行 DAG。
4. Task/Scenario 只能加权或补充完成标准，不能排除其他合法 Runtime Skill。
5. 显式 `$skill-name` 继续精确走现有 direct explicit 路径，不创建 SkillPlan；本期不新增 planned explicit 分支。
6. Standard 与 DeepSearch 共用全量检索服务，但分别保留现有执行、预算和证据政策。
7. 继续复用 Bounded DAG Executor、审批、SSE、取消、恢复、节点结果和报告系统。
8. 保留当前 DeepSearch 多轮澄清、计划确认、DAG 进度和报告下载交互；本方案只更换候选来源与相关校验，不重做交互框架。

### 3.2 统一指标

以后不再用“接入了多少 Skill”混称不同状态，统一记录以下指标：

```text
Catalog coverage
  = 有效 Profile 数 / 当前安装 Runtime Skill 数
  验收基线 = 84 / 84

Request searchable
  = Installed
    ∩ source_scope=builtin
    ∩ Binding 开启
    ∩ Profile 已审、有效

Planner shortlist
  = 相关性排序后、规划时 ready=true 的 Skill
  上限 = 12

Plan nodes
  = LLM 从 Planner shortlist 中选出的执行节点
  上限 = 6

Executable N
  = Profile 有效
    ∩ Binding 开启
    ∩ 当前用户与项目范围允许
    ∩ 必需资源可读
    ∩ 必需 Tool 已适配、健康且已授权
    ∩ 副作用符合请求和审批政策
```

在 Binding 全开的测试基线中，`Request searchable` 必须为 84/84。非 builtin Skill 不计入本期分母，也不得为了凑 84 混入自动 Planner。

`Executable N` 是请求级动态值，不在文档中承诺固定为 57 或 84。

### 3.3 质量门槛

- 84/84 个内置 Skill 有受版本控制、与 Skill version/hash 一致的 Profile。
- 每个 Skill 至少有 3 条互不改写复用的黄金正向用例，分别覆盖直接表述、自然语言改写和相邻能力边界；Phase 1A 标出的易混淆能力族中，每个 Skill 至少扩为 5 条。整体 Top-3 Recall 不低于 90%，Recall@5 不低于 95%；普通 Skill 的 Recall@5 至少命中 2/3，易混淆 Skill 至少命中 4/5，高风险 Skill 必须命中全部用例。这里是确定性发布回归门禁，不把这些小样本包装成总体统计置信度。
- 核心复合任务集的正确 Skill 覆盖率不低于 90%。
- 标注为越域的冻结负向用例必须 100% 返回 `no_matching_skill`，不向 Planner 发送候选。相关性门槛只能在 calibration 集上调整，并写入 `retrieval_policy_version`。
- 对已标注存在 6 节点内 ready coverage witness 的冻结复合用例，生产贪心策略不得返回 `coverage_search_exhausted`；出现一例就阻断发布并重新评估启发式，不在本期预先塞入精确求解器。
- 召回数据分为可迭代 calibration 集和零重叠的冻结 `release_holdout`。holdout 至少包含 252 条单意图正向用例，保证每个 Skill 至少 3 条；易混淆能力族再为每个 Skill 增补到至少 5 条，另含不少于 40 条复合用例和 40 条越域/近邻边界用例；中文与中英混合用例数量写入数据集 manifest。除总体指标外，按 capability family、语言、风险级别和 tool-limited 状态分层报告 Recall@5，任一分层不得低于 90%，任一普通 Skill 为 0/3 或易混淆 Skill 为 0/5 都阻断发布。调参前冻结 case ID、输入、期望标签、分层统计、owner 与 content hash。三轮调参只看 calibration；holdout 只由发布门禁运行并单独报告指标。修改 holdout 内容或标签必须由领域 owner 与检索 owner 双审、升级数据集版本并作废旧基线。
- Binding 禁用及非 builtin Skill 的模型泄漏数为 0。
- `ready=false` Skill 进入 Planner selectable shortlist 的数量为 0。
- LLM 返回候选快照之外 Skill ID 的接受数为 0。
- Planner、Plan Preview 与后续编辑使用同一份不可变 Candidate Snapshot；Skill/Profile 漂移后不得把旧 ID 解释成新能力卡。
- 不再因 `runtime_skill_unbound` 直接导致自然语言任务空候选。
- 固定基准下的本地确定性检索 p95 不高于 500 ms：84 个 Profile、预热后 500 个混合查询、本地 SQLite、无并发写入，分别测 FTS-only 与 fake-vector。只有计划在生产启用外部 Vector 时，预发布环境才必须另用真实 Embedding Provider 跑至少 100 个混合查询，验证每个请求最多一次批量 embedding 调用、端到端检索与 readiness p95 不高于 1,000 ms、Provider 成功率不低于 95%；任一门槛未过只阻止启用外部 Vector，生产保持 FTS-only，不阻断 Phase 2A。测试记录 runner 的 OS/CPU 与 Provider 区域。
- 冷缓存 holdout 中，已有本地或缓存 ready 覆盖的请求不得因待探测 implementation 超过 8 而失败；已标注存在 8 次探测内 ready witness 的请求，`readiness_probe_budget_exceeded` 为 0。Phase 1B 在至少 500 次授权 preview 请求和冷/热缓存重启混合样本上要求热缓存端到端检索 p95 不高于 500 ms、冷缓存 p95 不高于 1,000 ms、`readiness_probe_budget_exceeded <= 1%`、`tool_health_timeout <= 2%`；超阈值阻断 Phase 2A，由检索 owner 调整 TTL、排序或 probe budget，升级 `retrieval_policy_version` 并重跑完整 holdout。上线后继续以同一阈值告警，但不在运行时自动改参数。
- 所有标注为本期可支持的正向与复合 holdout 用例必须由 canonicalizer 产生至少一个服务端义务，意外 `unsupported_requirement` 或非预期澄清为 0；越域和明确不支持的用例不计入该分母。
- 在生产形态 SQLite 上用最大 32 KiB Candidate Snapshot、Tool claim/settlement 事件、3 个并发执行节点、10 个并发 Preview/SSE 读连接做至少 30 分钟 soak：不得出现 `database is locked`、事件丢失或 event-loop 阻塞；写事务锁等待 p95 不高于 100 ms、p99 不高于 500 ms。报告必须记录每 Run p99 增量、WAL 峰值和 checkpoint 时间，并按不少于 90 天的内部试点容量窗口证明可用磁盘至少为“当前数据库 + 预计增长 + 一份回滚副本”的 2 倍；本期不自动清理审计事件。任一门槛未过即阻断 Phase 2A，并修订存储方案或范围。
- 使用拟上线的真实 Planner Provider 跑至少 100 个冻结 Standard planning 请求，`Run created → WAITING_PLAN_APPROVAL` p95 不高于 30 秒、p99 不高于 60 秒，planning 终态成功率不低于 95%，结构/语义 repair 后仍无合法 Plan 的比例不高于 1%。Provider、模型、区域、并发与超时写入报告；任一门槛未过阻断 Phase 2A，不以自由文本结果降级。
- Planner 失败不得产生未经验证的执行计划或伪完成报告。

除明确标注为“只阻止启用外部 Vector”的真实 Embedding Provider 门槛外，以上门槛都是 Phase 2A 的发布前置条件。任一召回、安全或快照完整性门槛未达标时，只允许继续 Phase 1A/1B 的离线评测，以及对已审 Profile 的只读 recommendation preview，不得扩大生产 Planner 候选范围。calibration 集最多进行三轮 Profile/检索规则修订，再对冻结 holdout 做发布判定；失败后由 Skill Catalog owner 与检索 owner 重新评估范围、算法和下一版数据集，门槛本身不得下调。

`retrieval_policy_version` 由检索 owner 与 Skill Catalog owner 共同维护，覆盖 atom canonicalizer、FTS/Vector/RRF 权重、相关性阈值、配额、Tool probe TTL/预算和 tie-break；任一语义变化必须经 PR 双审、升级版本并重跑 calibration、冻结 holdout 与 preview 门槛。默认版本升级不改写在途 Candidate Snapshot。

这些比例只是对固定样例集的发布回归门禁，不是对真实请求总体质量的统计推断。上线后另按真实流量记录无候选、保守误拒、Planner repair 和最终 gap 比例，不用小样本百分比宣称普遍准确率。

### 3.4 核心验收用例

输入：

```text
宠物食品心智设计表达策略研究
```

通过标准：

1. 不再出现笼统的 `No ready and authorized Skill candidates`。
2. 全量检索能覆盖竞品/市场研究、用户洞察、策略整合相关 Skill。
3. LLM 计划只能引用本次最多 12 个 selectable candidate ID。
4. 最佳能力缺少工具时，界面显示明确 gap；存在合法替代项时可以选择替代项并披露差异。
5. 执行成功后产出完整最终报告；无法完成时明确标记 partial/failed，不伪装成实证结论。
6. 相关 Skill 全部 blocked、`Executable N == 0` 时不调用 Planner，Run 以稳定错误 `no_executable_skill` 失败，并返回不泄露敏感信息的 blocking gap 与 blocked-match 诊断。
7. 越域请求没有任何 Skill 达到相关性门槛时返回 `no_matching_skill`，不用 Vector top-k 强行填满候选，也不调用 Planner。

## 4. 非目标

- 不把 84 份完整 `SKILL.md` 一次性送入模型。
- 不允许模型发明 Skill、Tool、权限、输入输出、资源或来源。
- 不因 Skill 可检索就自动授予 Bash、文件、Zero、JoySpace、O2 或外部 API 权限。
- 不移除 Plan Approval、Tool Grant、高风险操作确认、证据校验或审计。
- 不重写 Bounded DAG Executor、DeepSearch Evidence Pipeline 或报告渲染器。
- 不在本项目中接通 27 个 `tool_limited` Skill 的全部外部工具。
- 不新增 PostgreSQL Control Plane、Lease Worker、独立 Execution Engine 或 `/control-tasks` API。
- 不支持多进程或多副本共享同一 SQLite；本期继续使用已确认的单进程、单 SQLite MVP 部署边界。
- 不引入第二套 Skill Registry，也不把 25 个业务槽位扩写成 84 个重复定义。
- 不增加第二次 LLM 召回/重排调用；第一版由确定性检索产生最多 12 个候选，再由现有 LLM Planner 选择节点。
- 不在本期为 Workspace、Project Package 或 Learned Skill 新增 ownership/scope 数据模型；它们继续显式调用。
- 不新增 planned explicit 编排路径。未进入自然语言 Planner 的 Skill 继续由现有 direct explicit 执行链处理。
- 不修改已存在的 `DeepSearchFrozenPlanV1` 字段或 canonical hash。新 Universal DeepSearch Plan 使用版本化的 FrozenPlan v2，旧 v1 继续按原合同读取和恢复。
- 不在本期删除 Task Catalog v1、FrozenPlan v1 或 legacy Plan parser；其退役条件和数据保留期另立 ADR。

## 5. 状态与安全边界

### 5.1 Skill 状态

| 状态 | 定义 | 是否进入模型 |
| --- | --- | --- |
| Installed | Runtime 已发现并解析 `SKILL.md` | 否，仍需后续检查 |
| Visible | 内置 Skill 对当前 Agent 的 Binding 未关闭 | 仅可进入检索 |
| Searchable | builtin 且有已审、有效的安全能力卡 | 可参与确定性检索 |
| Ready | 当前 Profile、资源、Tool、授权和副作用条件满足 | 可进入 Planner shortlist |
| Selectable | Ready 且被截取到最多 12 个 Planner 候选 | 可被 LLM 选为节点 |
| Executable | 节点启动时重新校验仍通过 | 可以实际执行 |
| Blocked | 相关但当前不可执行 | 不可成为节点；先生成 informational match，必要能力无替代时才形成 blocking gap |

“全部 Skill 进入备选池”的准确含义是：

> 当前 84 个内置 Runtime Skill 在 Binding 开启且 Profile 已审、有效时全部参与相关性检索；只有通过确定性 readiness 检查的 Skill 才进入 LLM 可选择的最多 12 个候选。

### 5.2 模型调用前必须删除的对象

以下 Skill 在任何模型调用前从请求级语料中移除，模型、客户端和普通用户事件均不得看到其 ID、名称或描述：

- 非 builtin source scope；
- Agent Binding 明确禁用；
- Profile 缺失、非法或与 Skill version/hash 不一致；
- Profile 未通过审签；
- Profile 标记 `planner_eligible=false`。

服务端只记录聚合数量和管理员诊断，不向用户输出被过滤 Skill 的明细。

### 5.3 可以公开的 readiness 诊断

Skill 已通过可见性与 Profile 检查后，以下运行条件可以用稳定、非敏感代码表示：

- `required_tool_unavailable`
- `required_tool_unhealthy`
- `tool_health_timeout`
- `tool_grant_missing`
- `public_resource_unavailable`
- `external_write_not_requested`
- `deepsearch_evidence_path_unsupported`

这些 Skill 可以参与确定性相关性排序和用户可见的 gap 解释，但不能进入 Planner selectable shortlist。诊断不得包含私有资源路径、Tool 凭据、内部授权对象或其他项目名称。`readiness_probe_budget_exceeded` 是“必需 atom 或产生非空 Plan 所需的首个 ready candidate 仍依赖未探测 implementation”时的请求级失败，不是任何 Skill 已 blocked 的证据；未探测尾部不进入 `blocked_match_count`，也不返回上述 per-Skill 诊断。

这一区分明确替代 ADR 0004 中笼统的“unready/unauthorized 排序前过滤”：非 builtin、Binding 禁用或未审 Profile 仍在模型前删除；对可见内置 Skill 的执行就绪缺口只以安全代码展示。

## 6. 目标架构

```text
                         Runtime Skill Catalog
                                  │
                     builtin / Binding / Profile 审签过滤
                                  │
                                  ▼
                    全量请求级 Searchable Corpus
                                  │
          ┌───────────────────────┼────────────────────────┐
          │                       │                        │
    用户目标/交付物         Task/Scenario 提示        Profile 检索字段
          │                 仅加权和完成标准             │
          └───────────────────────┼────────────────────────┘
                                  ▼
                   FTS + Profile Vector + RRF + 规则分
                                  │
                          readiness 确定性分类
                         ┌────────┴─────────┐
                         │                  │
                 最多 12 个 Ready       相关 Blocked
                 Planner shortlist       blocked matches
                         │                  │
                         ▼                  ▼
                  LLM DAG Planner       用户可见诊断
                         │
                    最多 6 个节点
                         │
                         ▼
        Candidate / DAG / Profile / Tool / Resource / Policy 校验
                         │
                         ▼
                Plan Approval + Tool Approval
                         │
                         ▼
                  Bounded DAG Executor
                         │
                         ▼
                  Synthesis / HTML Report
```

架构中不存在“把 84 份完整 Skill 指令交给 LLM”的步骤。检索只使用能力卡；节点执行前才加载被选中 Skill 的完整 instructions 与批准资源。

## 7. 详细设计

### 7.1 全量 Capability Profile

继续使用现有 `SkillCapabilityProfile`，不创建第二套 Profile 模型。为全部 84 个内置 Skill 补齐 `agents/agentmesh.yaml`，至少包含：

- Skill version 与内容 Hash；
- 最多 100 字的公开能力描述；
- 生命周期阶段与能力类型；
- 输入类型、输出类型；
- 正向示例、负向示例；
- 必需 Tool、Capability、Resource；
- 是否产生事实性结论与报告策略；
- 成本、风险、副作用；
- `review_state: draft|approved`；
- `planner_eligible`。

Profile 与 Planner 投影必须有硬边界：单个 sidecar 的 UTF-8 原文和 canonical JSON 都不超过 32 KiB；`lifecycle_tags` 最多 8 项；`input_kinds`、`output_kinds`、`required_capabilities`、`task_types`、`archetypes`、`required_tools`、`required_resources` 各最多 20 项；正向与负向示例各最多 8 项。普通列表项最多 120 个 Unicode code point，schema/resource ref 最多 240，示例最多 300。生成的单张 `capability_card` canonical JSON 不超过 4 KiB，12 张卡及其公开 coverage metadata 合计不超过 32 KiB。任一 Profile 超限即 `profile_invalid`，不能进入 Searchable Corpus，不在运行时截断。

生成与审签规则：

1. 每个 `agents/agentmesh.yaml` sidecar 本身就是唯一的逐 Skill 人工配置源；它显式给出 `capability_type`、输入输出、正反例、工具、资源、事实性、风险和副作用，脚本不得再创建一份中央重复 Registry，也不得从自然语言正文猜这些安全字段。
2. `scripts/sync_wiki_skills.py --generate-profile-stubs` 只在 sidecar 不存在时创建 `review_state=draft`、`planner_eligible=false` 的初稿，永不覆盖已有人工 Profile。
3. 常规 `sync` 只更新 generated `SKILL.md`，不自动刷新 Profile 的 `skill_content_hash`。Skill 内容变化后，`--check` 必须报 stale，要求人工重新审查并更新 hash。
4. 84/84 个 Profile 均需审查，不只抽查高风险 Skill。Profile 作者不能批准自己的改动；普通 Profile 至少需要一名 CODEOWNER 审批。`risk_level=high`、`side_effect in {local_write, external_write}` 或 `required_tools` 非空的 Profile 需要两名不同 CODEOWNER 审批，这个判定由 CI 根据 sidecar 字段执行，不靠人工标签。
5. `review_state=approved` 只表示作者申请发布，不能单独构成信任凭据。生产信任根是受保护 GitHub Actions、GitHub artifact attestation 和部署验证，不是仓库工作区中的 JSON。
6. 生产只支持一条发布拓扑：Profile PR 在受保护分支上由 CODEOWNERS 审批，最后一次 push 后旧审批自动失效；merge queue 保证合并时基线最新，发布 workflow 只从受保护 `main` 的 merge commit 构建。workflow 必须证明 merge commit 中每个变更 Profile 的 blob hash 与最后受审 PR head 完全一致；生产禁用 squash/rebase merge、直接 push、非 PR build 和绕过审批的紧急发布。受保护 CI 针对精确 PR head 和 Profile blob hash 查询审批元数据，验证审批人与作者分离及单审/双审策略，再在 build staging 生成 `wiki-skill-provenance.json`。Manifest 记录 Profile hash/version、reviewed PR head/tree、release merge commit、review policy 和 reviewer IDs；CI 构建 wheel 后只对整个 wheel 生成一份 GitHub artifact attestation，将 wheel digest 绑定到仓库、workflow、ref 和 commit，不为 84 个 Profile 各造一套签名或密钥轮换机制，也不把合并后 commit 写回同一受审文件形成自引用。
7. 部署门禁先验证 artifact attestation 的 owner/repository、workflow/ref 和 wheel digest，成功后才安装。部署器以 wheel digest 作为 release ID，把 wheel 安装到工作区外的不可变 release 目录，并在同一受保护目录原子写入 verified-build marker；marker 只包含 release ID/wheel digest、内嵌 manifest hash、attestation identity 和验证时间。运行时从自身安装路径解析 release ID，要求它与同目录 marker 的 wheel digest 一致，再重算内嵌 manifest 以及其中列出的 Skill/Profile hash；wheel 不尝试内嵌或运行时重算自身 digest。没有 marker、release ID 不一致或任一内嵌 hash 不匹配时，所有 Profile 均 `planner_eligible=false`，并以聚合健康状态 `skill_profile_trust_unavailable` 告警。本地与测试通过注入 verifier 使用假证明，默认不能获得生产资格。
8. attestation 的撤销或安全通知由部署流程处理，不虚构请求时实时撤销协议。Phase 1A/1B 尚未写入新语义 Run，只需依赖 trust fail-closed、撤下 recommendation preview、停止旧进程、删除失效 marker，再部署已验证 wheel；不得调用尚未交付的 16.3 quiesce 工具。Phase 2A 起按 16.3 封住入口、quiesce、停机并离线终态化；之后删除失效 marker、重发经验证的 wheel，并运行 Catalog Report 和真实 Provider smoke，全部通过前不恢复切流。
9. `scripts/skill_catalog_report.py` 对 84/84 覆盖、Profile schema、Skill version/hash、Profile hash、工具名、资源声明、owner 能否解析到 CODEOWNERS、单审/双审状态和 roster `review_due_at` fail closed；缺失或已逾期项不能获得发布资格。
10. 当前 84 个内置 Skill 经审查后全部设置 `planner_eligible=true`；加载时的有效值还必须满足 builtin source、manifest attestation 和 `review_state=approved`。
11. 非 builtin 或缺少已审 Profile 的 Skill 仍可按现有 direct explicit 路径调用，但不得参加自然语言 Planner。

单人 Hackathon 开发边界：在当前仓库只有一名维护者、无法满足作者与审查人分离时，允许继续 Phase 1A/1B 的本地实现、draft Profile 起草和离线评测；这不产生生产信任，不得把自审 Profile 标记为生产 `approved`，也不得扩大公开 recommendation 或 Agent Run Planner 候选。独立 CODEOWNER 审查、attestation 和预发布演练继续作为 Phase 2A 生产 Preview 切流门禁。若项目最终只交付本地 Hackathon 演示而不进入生产，该未满足项必须在验收记录中明确列为限制，不能伪装为已通过。

`review_state` 只存在于文件级 `_ProfileDocument`；运行时仍投影到现有 `SkillCapabilityProfile.planner_eligible`，不增加数据库列。`wiki-skill-provenance.json` 根 `schema_version` 从 1 升为 2；它与单个 Profile 的 `profile_version` 是两个独立版本，校验和文档不得混用。这个数字也与已退役 Research v2 无关。

`planner_eligible` 表示审签后的规划资格，不兼作灰度开关。Phase 1A/1B 可以分批起草、审查和离线评测；只有已审 Profile 能进入只读 recommendation preview，Phase 2A 切流前必须达到 84/84。生产灰度继续使用现有 `off/preview/execute` 配置，不通过修改 Profile 信任状态实现。

现有 10 个 Profile 在 Phase 1B 只能补充检索文案、正反例和审签字段；`required_capabilities`、`required_tools`、`required_resources`、`side_effect`、Skill version/hash 等执行字段必须保持不变，避免使未完成 Plan 的重验失效。若审查发现这些字段本身错误，必须先阻止发布并取消或完成受影响的未终态 Plan，再单独提交更正。

不得在运行时根据 Skill 正文猜测权限、副作用或 Tool Grant。

### 7.2 删除 Pilot 白名单，但保留安全门

删除 `PILOT_BUILTIN_SKILL_NAMES` 作为自动编排资格判断的职责。新的检索资格为：

```text
Installed
AND source_scope=builtin
AND Binding enabled
AND Profile valid and current
AND manifest attested
AND review_state=approved
AND planner_eligible=true
```

`activation_policy` 与 `planner_eligible` 保持不同语义：

- `activation_policy` 控制运行中 Agent 能否通过 `activate_skill` 自主加载另一个 Skill；
- `planner_eligible` 控制服务端 Planner 能否把 Skill 提议为持久化 Plan 节点；
- Planner 选择不是即时执行，仍需候选快照、确定性校验和审批；
- 不批量修改现有 Skill 的 `disable-model-invocation` 或 `explicit_only` 声明。

因此，显式调用安全边界不变，但服务端受控 Planner 可以从全量合法 Profile 中规划。

### 7.3 两阶段检索与 12 个候选上限

抽取 `recommend_skill_directory()`、Profile FTS/vector ranking 和 RRF 逻辑为 Planner 与 Skill Center 共用的确定性检索服务。

检索流程：

1. 先执行 5.2 的访问控制过滤。
2. 服务端先构造三组对象。`query_atoms` 只用于召回与排序，包含用户目标及每个必需能力的检索文本；输入、分析和展示要求合并为查询上下文，不单独抢占候选配额。`required_coverage_atoms` 只能来自服务端确定的三个来源：现有确定性 SkillIntent canonicalizer 产生且存在于已审 Profile `output_kinds` 中的 deliverable ID、当次固定 Task Catalog 中的必需 Scenario output，以及 Evidence Policy 的受信任外部证据要求。映射到固定 Synthesis 输出的 deliverable 写入有序唯一的 `required_synthesis_output_ids`，在最终 Synthesis 阶段校验，不形成候选 coverage atom 或节点 gap；它是服务端义务，LLM 和编辑请求不能删除。两组服务端义务不得同时为空：纯 Synthesis 请求至少有一个 `required_synthesis_output_id`，其余请求至少有一个 coverage atom；若 canonicalizer 无法形成任何义务，则在检索和 Planner 前返回澄清或 `unsupported_requirement`。LLM 补充的自由文本只能进入 `query_atoms`，不能创建 hard coverage atom；用户明确要求但 canonicalizer 既无法映射到 Profile output kind，也无法映射到固定 Synthesis 输出时，同样在 Planner 前返回澄清或 `unsupported_requirement`。

   `required_coverage_atoms` 固定按 deliverable 请求顺序、Catalog 中的 Scenario/output 顺序和 evidence 最后的顺序编码，依次使用 `deliverable:<output_kind>`、`scenario:<scenario_id>:output:<output_id>` 和可选的 `evidence:trusted_external_path`，并按 canonical ID 保留首个、去掉重复项。用户目标不是 coverage atom。
3. `MAX_COVERAGE_ATOMS=24`。超限时返回 `requirement_budget_exceeded` 并要求拆分任务，不得截断。deliverable coverage 只由已审 Profile 的 `output_kinds` 判定；Scenario coverage 使用 7.6 的受审映射；`evidence:trusted_external_path` 只由这样的 candidate variant 覆盖：其 Profile 声明的 Tool/Resource 路径已被当前 Evidence Policy 接受，且本次 Tool、授权、资源 readiness 全部通过；实际获准的 Tool implementation/version 与 Resource/Adapter identity 必须作为 `EvidencePathWitnessV1` 冻结。该 precheck 只证明存在可执行的受信任取证路径，来源数量、独立性、新鲜度和实际证据仍留到执行后由 Evidence Policy 验证。FTS/Vector 相似度和 `matched_query_atom_ids` 都不能直接形成 coverage。
4. 每个 query atom 分别执行 FTS top-12 与 Vector top-12，使用 `RRF(k=60)` 合并。正向检索投影只包含名称、标题、公开短描述、别名、阶段、能力类型、输入输出和正向示例；负向示例只参与惩罚和边界判定，不写入正向 FTS/Vector 文本。所有权重、tie-break 和检索投影写入版本化 `retrieval_policy_version`。
5. 结果按 `skill_id` 去重并累加 RRF/规则分，同时记录只用于解释排序的临时 `matched_query_atom_ids`。同分时依次按命中的 query atom 数、总分和 `skill_id` 排序，结果必须稳定。合并后先应用由 calibration 集确定、写入 `retrieval_policy_version` 的最低相关性门槛，不允许仅因 Vector 返回 top-k 就进入 readiness 和 Planner。
6. Task/Scenario 命中只增加排序分，不删除未映射 Skill；随后执行 readiness 检查。
7. 为每个 ready Skill 构造 assignment-aware coverage variant。一个 variant 可以覆盖通用 atom 和至多一个 Scenario 下的 output atom，与“一节点只有一个 `scenario_id`”一致；每项 coverage 都必须来自第 3 条的确定性谓词。
8. 没有任何 ready variant 可覆盖的 atom 先形成 blocking capability gap，并从本次 `plannable_coverage_atoms` 中排除；它仍保留在原始 `required_coverage_atoms` 中用于最终完成判定。服务端再对剩余 `(skill_id, scenario_id|null)` variant 做确定性贪心覆盖，每轮按“新覆盖 atom 数降序、总分降序、`skill_id` 升序、Scenario sort key 升序”选择；Scenario sort key 固定为 `(scenario_id is not null, scenario_id or "")`，即 `null` 排在所有字符串 ID 前。选中后不再选择同一 Skill 的其他 variant。coverage witness 最多选择 6 个唯一 Skill，与执行节点上限相同；若已经没有合法未选 variant 可继续，或选满 6 个后仍有 `plannable_coverage_atoms` 未覆盖，则返回 `coverage_search_exhausted`、未覆盖的 canonical ID/label 和按 deliverable/Scenario 拆分任务的建议，不声称已证明不存在可行组合。本期不引入精确集合覆盖求解器，该保守失败率由冻结 holdout 监测。
9. `coverage_witness_scenario_id` 与 `covered_requirement_ids` 共同记录候选入围时选中的那个 assignment-aware variant，不是模糊检索命中或最终 Scenario assignment；后者必须恰好是该 variant 能覆盖的 atom，并按全局 canonical atom 顺序保存唯一 ID。贪心阶段选中的最多 6 个 Skill ID 按选择顺序写入 `coverage_witness_skill_ids`；按全局分补位的候选按第 8 条 tie-break 选择其第一个合法 variant。候选并集最后按全局 rank 排序并补满到最多 12 个唯一 ready Skill，形成不可变 Candidate Snapshot；`coverage_witness_skill_ids` 必须是其有序唯一子集，`SkillPlan.candidate_skill_ids` 仅从完整 candidates 顺序派生，供旧 API 兼容。
10. 对高相关 blocked 结果生成最多 5 条 informational blocked-match 诊断，不写入 Candidate Snapshot。没有候选达到相关性门槛时返回 `no_matching_skill`；有相关候选但没有 ready 结果时，先按本节冷缓存合同判断必需 atom 或首个 ready candidate 是否仍依赖超出 8 次预算的未探测 implementation，此时优先返回 `readiness_probe_budget_exceeded`。只有 readiness 已确定且相关候选全部 blocked 时，才按 3.4 的 `no_executable_skill` 合同结束。以上结果都不调用 Planner。
11. Planner 从快照中的候选选择 1 至 6 个节点；0 节点属于语义校验失败，进入一次 repair，不得持久化可执行空 Plan 或运行空 Synthesis。仅当快照中的 `plannable_coverage_atom_ids` 非空时才要求节点覆盖它们：已有具体 assignment 的节点按 7.6 严格计算；仍有多义 assignment 的 draft，在“每节点最多归属一个 Scenario”约束下，对服务端允许选项做确定性的存在性校验，只要至少一组 assignment 能覆盖全部可规划 atom，就持久化 `WAITING_APPROVAL`，但该验证 witness 不替用户写入 `scenario_id`。不存在合法组合，或一次 repair 后仍超限、为 0 节点或未覆盖可规划 atom 时，返回 `planner_coverage_unresolved`、未覆盖的 canonical ID/label 和拆分建议。批准和执行前必须用用户已保存的具体 assignment 再跑严格 coverage。已确认的 blocking-gap atom 不要求 Planner 伪造节点，但始终阻止 Plan 成为 `COMPLETED`。服务端不伪造“必须超过 6 个节点”的数学证明。

`unsupported_requirement`、`requirement_budget_exceeded`、`no_matching_skill`、`no_executable_skill`、`readiness_probe_budget_exceeded` 和 `coverage_search_exhausted` 都在 Candidate Snapshot 与 `PLANNING` skeleton 创建前终止检索：Agent Run 进入 `FAILED`，`plan_id=null`，不留下空 Plan。只有检索成功并冻结 Candidate Snapshot 后才进入 7.5 的 skeleton 事务。

canonicalizer 不拥有第二份 output-kind Registry。其合法 deliverable 词汇只能取自当前受信 Profile 的 `output_kinds` 并集与代码中固定的 Synthesis output 集，映射规则、同义词、语言归一化和上述两类输入资产的 hash 都进入 `retrieval_policy_version`。Skill Catalog owner 负责 output-kind 语义，检索 owner 负责确定性映射实现；任何新增、删除或映射变化必须 PR 双审、升级版本并重跑 calibration、完整 holdout 与 `unsupported_requirement` 门禁。运行时遇到多义映射先澄清，无法映射才返回 `unsupported_requirement`，不得让 LLM 创造新 kind。

现有 `SkillPlan.capability_gaps: list[str]` 仍只保存会阻止任务完成的缺口。服务端按 7.6 的 coverage 谓词从最终节点集重新计算，模型和客户端不能提交最终 gap。gap 按 atom 独立判定：ready variant 或最终节点覆盖某个 blocked match 对应的 atom 后，该 match 对该 atom 只作 informational；其他 atom 是否仍有缺口不改变这一结论。仅仅“存在一个更高分但 blocked 的 Skill”不是 blocking gap。

已知 blocking gap 阻止 `completed`，但不必然阻止用户获取其他有用结果。仍有 ready 节点时，服务端生成带 gap 的待批准 Plan，持久化 `SkillPlan.status=WAITING_APPROVAL` 并保持 `AgentRun.status=WAITING_PLAN_APPROVAL`；UI 必须在批准动作旁展示未覆盖的 canonical ID 和 label。执行后 7.6 的 `has_valid_partial_delivery` 为真时只能结束为 `PARTIAL`，否则为 `FAILED`。没有任何 ready 节点时按第 10 条的失败优先级结束。本期不增加第二个“接受不完整计划”开关，现有 Plan Approval 就是用户对可见 gap 的确认。

Vector 路径复用现有 `VectorIndex`，不另建缓存或索引服务。canonical index projection 包含标题、公开描述、别名、阶段、能力类型、输入输出与正向示例；负向示例保留在独立字段，只用于扣分。内容、Embedding model 或维度变化时，现有 content hash 与 index signature 使向量进入 pending/stale 并后台重建。

请求侧最多产生 25 个去重 query atom 文本，每项最多 2,000 字符。扩展现有 `embed_texts()`，一次批量请求全部 query embedding，不允许逐 atom 串行调用 Provider；FTS 与该批请求并行，向量批次 deadline 为 350 ms。Provider 关闭、超时、响应数量/维度错误或索引失败时，整批 Vector 结果作废并继续使用 FTS 与规则分，返回安全诊断，不得把请求误报为空候选。离线评测分别覆盖 FTS-only 与确定性 fake-vector，发布门禁另测真实 Provider 批量路径和降级后的端到端 p95。

外部 Embedding 默认关闭。启用前必须由部署配置确认 Provider 、数据区域和不用于训练/持久保留的策略符合内部数据要求；无法确认时强制 FTS-only。发送前对每个 query atom 复用 `redact_sensitive_text()`，不发送凭据、联系方式、本地路径、私有记忆正文、附件/文档正文或 Tool 输出。无法安全编码的 atom 只走 FTS；事件和 Provider 日志不记录原始 query atom。

Readiness 每个请求只构造一份快照。Binding、Profile、授权、资源和副作用先用本地状态检查；外部 Tool health 只考虑各 query atom top-12 并集中的候选，并按 `(tool_name, implementation_id, implementation_version)` 去重，不按 84 个 Skill 逐项探测。Gateway health cache 的 TTL 固定为 30 秒，cache key 不包含用户授权，授权仍逐请求本地判断。

冷缓存最多允许 8 个唯一远端 probe，并发上限 8、单项超时 200 ms、整批 deadline 300 ms。服务端先使用本地检查和未过期缓存，再对剩余 implementation 排序：能覆盖尚无 ready 替代的必需 atom 优先；若当前还没有任何 ready candidate，则候选全局 rank 更高者次优先；最后按 implementation identity 排序。只有结果已覆盖全部必需 atom，且至少存在一个相关 ready candidate 时，才不再为尾部候选发 probe；超出预算的尾部候选不进入 selectable shortlist，也不伪装成已确认 blocked。若未覆盖的必需 atom 或“至少一个 ready candidate”的条件仍依赖未探测 implementation，请求以 `readiness_probe_budget_exceeded` 失败；候选并集单纯超过 8 不能导致整单失败。单个已发出的 probe 超时记录 `tool_health_timeout`，只有明确失败的健康检查才记录 `required_tool_unhealthy`。节点启动仍执行 live 重验，因此规划阶段缓存不会成为持续授权。上述数值和排序规则均进入 `retrieval_policy_version`，不新增环境变量；发布门禁分别测空缓存与热缓存路径。

三个上限必须保持区分：

```text
检索全集：当前 Agent 全部 Searchable builtin Skill，基线 84
持久化 Planner shortlist：最多 12
持久化执行节点：最多 6
```

不把持久化候选上限改为 24。`SkillPlan`、DeepSearch FrozenPlan v1/v2 和已封存 Artifact 都保持 12 个候选上限；版本升级只补候选身份，不扩大上限。

第一版不增加 LLM rerank。现有 LLM Planner 已负责从候选中做语义选择；额外 rerank 会增加成本、DeepSearch 预算和恢复复杂度，却不是实现全量候选池的必要条件。

### 7.4 Task/Scenario 变成提示，而不是白名单

Task/Scenario 继续负责：

- 识别用户目标；
- 提供分析要求和展示要求；
- 提供带稳定机器 ID 的输出要求和完成标准；
- 提供 Skill 排序加分；
- 决定是否必须有外部证据；
- 判断是否需要澄清或人工确认。

删除以下行为：

- 不再把 Scenario default/optional Skill 当作唯一候选集合。
- 不再因 `runtime_skill_name=null` 排除其他 Runtime Skill。
- 不再因业务槽位未绑定直接抛出 PlannerUnavailable。
- routed 分支不再直接用 `route_skill_draft()` 绕过 LLM Planner。

`skill-registry.json` 继续保存业务别名和推荐关系，但不再是执行事实源。其未绑定项只形成目录诊断或排序缺口。

Scenario 输出不得再用展示文案充当机器标识。`outputs` 改为受版本控制的结构化项：

```yaml
- id: competitor_selection_logic
  label: 竞品选择逻辑
  compatible_output_kinds: [competitive_analysis]
```

- `id` 是 Scenario 内唯一、稳定的 `lower_snake_case` 标识。节点结果中的 `scenario_outputs` 保存该 ID；跨 Scenario 聚合时统一使用 `scenario:<scenario_id>:output:<output_id>` 作为 requirement atom、`covered_requirement_ids`、缺口代码和测试键，避免同名 output 碰撞。
- `label` 只用于 Prompt 与 UI 展示，不参与相等判断、映射或完成判定。
- `compatible_output_kinds` 是人工审查的 Scenario output 与 Profile `output_kinds` 映射；服务端只按该映射判断兼容，不做中文文案、模糊文本或 LLM 推断匹配。
- Catalog compiler 必须拒绝重复 output ID、非法 ID 和空 `compatible_output_kinds`。映射中的 kind 当前没有已审 Profile 提供时，Catalog 仍可加载，由 Catalog Report 报告并在请求时形成 blocking capability gap；本期不新增第二套 output-kind Registry。

canonical output 通过 Task Catalog v2 引入，不原地改写 v1 文件或 hash。有 `routing_result` 的 Plan 按其中的 `catalog_version` 和 `catalog_hash` 解析精确版本：legacy Standard Plan 与 Phase 2A/2B DeepSearch 继续走 v1 output/completion 分支；Phase 2A 起新 Standard Plan 使用 v2；Phase 3 新建、replan 或 retry 的 DeepSearch Plan 使用 v2。`routing_result=null` 的 unrouted Plan 不读取 Catalog。所有 hash/operation key 共用 `routing_catalog_identity`：routed 时是 `{catalog_version, catalog_hash}`，unrouted 时是 canonical JSON `null`，不得虚构默认 Catalog。需要 Catalog 但找不到精确版本时以 `task_catalog_snapshot_unavailable` fail closed，不能退回当前默认 Catalog。

每个已发布 Catalog 版本目录都不可变，构建器只允许 byte-identical 重建；任何语义或内容变化必须发布新版本，resolver 以 `(catalog_version, catalog_hash)` 建索引。本期随 wheel 永久保留 v1/v2 资产，不实现 Catalog 清理器；以后若要删除，必须在独立 ADR 中先定义生产引用扫描、备份和恢复门禁。

Catalog parser 必须先按 manifest version 分派模型。`ScenarioCatalogEntryV1.outputs: tuple[str, ...]` 保持原样，v2 使用独立的结构化 output 类型；不得把同一个 `outputs` 字段扩成 v1/v2 union，再让 v2 假设泄漏到 legacy completion。

Run 创建策略按当时启用的 Phase 与 `planning_mode` 选择并持久化 7.5 的 `planning_contract_version`；Catalog resolver 接收该 marker，而不是在恢复时读取当前 Phase。`standard_universal_v1` 解析 Catalog v2，`deepsearch_frozen_v1` 解析 v1，`deepsearch_frozen_v2` 解析 v2；legacy 缺失值按 7.5 处理。Router 返回的 version/hash 随 Plan 固定，后续不再查询“当前默认版本”。`/routing-preview` 没有持久化 Run，因此增加可选 `planning_mode=standard|deepsearch`，默认 `standard`，按当前创建策略预览并返回将要使用的 planning contract 与 Catalog identity，确保预览与紧随其后的实际 Run 一致；跨部署边界时仍以实际创建 Run 的 marker 为准。

### 7.5 Candidate Snapshot 与节点来源合同

任何可能生成 Plan 的 Run 都必须在创建 Run 的同一事务中先冻结 server-owned `planning_contract_version`，不能等到 Requirement refinement、检索、Candidate Snapshot 或 FrozenPlan 已生成后再推断。允许值只有 `standard_legacy_v1`、`standard_universal_v1`、`deepsearch_frozen_v1`、`deepsearch_frozen_v2`：Phase 2A 起新 Standard Run 写 `standard_universal_v1`，Phase 2A/2B DeepSearch 写 `deepsearch_frozen_v1`，Phase 3 新建、retry 或 replan 的 DeepSearch 写 `deepsearch_frozen_v2`。direct explicit 不生成 Plan，保持 `null`。

该字段进入不可变 Run creation identity；同一 Run 的 planning、resume、recovery、retry lineage 检查和 Plan/FrozenPlan resolver 只读该值，禁止按“当前部署 Phase”猜测合同。同一 `client_turn_id` 的重放先读取已有 Run，并用其已冻结 marker 校验和返回原结果，不能因部署跨 Phase 为该 Run 重新选择 marker；只有首次 claim 新 Run 时才使用当前创建策略。内部若尝试以同一幂等身份写入不同 marker 必须冲突。升级前已存在且缺少该字段的 Run 按兼容默认解释：Standard 为 `standard_legacy_v1`，DeepSearch 为 `deepsearch_frozen_v1`，不得自动升级。字段与实际 Plan/Candidate Snapshot/FrozenPlan schema 不一致时按持久化损坏 fail closed。这样即使进程在 Plan 生成前退出，Phase 2A/2B DeepSearch Run 跨 Phase 3 仍生成 v1，Phase 3 新 DeepSearch Run 也能被回滚预检识别为 v2 目标。

`candidate_skill_ids` 只能证明 ID 曾进入 shortlist，不能证明 Planner 当时看到的 Profile、能力卡和 readiness。Phase 2A 起新建的 Standard Plan，以及 Phase 3 新建或重新规划的 DeepSearch Plan，必须在生成任何 LLM 或确定性 draft 前构造不可变 `CandidateSnapshotV1`：

```text
CandidateSnapshotV1
  schema_version = candidate-snapshot-v1
  retrieval_policy_version
  required_coverage_atoms: ordered list[CoverageAtomV1], max 24, unique by id
  plannable_coverage_atom_ids: ordered subset of required_coverage_atoms[*].id
  required_synthesis_output_ids: ordered list[str], max 20, unique
  coverage_witness_skill_ids: ordered list[skill_id], max 6, unique and subset of candidates
  candidates: ordered list[CandidateIdentityV1], max 12, unique by skill_id
  content_hash = sha256(canonical JSON excluding content_hash)

CoverageAtomV1 = one of
  DeliverableAtomV1
    id / label / kind=deliverable / output_kind
  ScenarioOutputAtomV1
    id / label / kind=scenario_output
    scenario_id / output_id / compatible_output_kinds (ordered, unique)
  EvidenceAtomV1
    id / label / kind=evidence
    requirement_key / evidence_policy_id / evidence_policy_version / evidence_policy_hash

CandidateIdentityV1
  skill_id / skill_name
  skill_version / skill_content_hash
  profile_version / profile_content_hash
  capability_card
  capability_card_hash
  match_reason_codes
  coverage_witness_scenario_id
  evidence_path_witnesses: ordered list[EvidencePathWitnessV1]
  covered_requirement_ids
  ready_at_planning = true

EvidencePathWitnessV1
  atom_id / tool_implementation_id / tool_implementation_version
  resource_or_adapter_identity / identity_hash
```

`capability_card` 是从受审 Profile 生成的静态公开投影，不包含完整 `SKILL.md`、私有资源、权限对象、凭据或请求级检索理由；`capability_card_hash` 只对该静态投影的版本化 canonical JSON 计算，因此可以从同一 Profile 重算。`match_reason_codes` 是服务端生成的请求级稳定代码，作为 Candidate Snapshot 的一部分一起参与总 hash，但不参与 `capability_card_hash`。候选列表顺序就是 rank，分数只进入审计事件，不重复写入身份结构。

完整 Candidate Snapshot 是 server-internal 持久化合同，不能直接序列化到 Planner、Plan Detail、普通用户 SSE 或 UI。所有外发路径共用一个显式 public projection，只包含 snapshot hash、required atom 的安全 ID/label、`required_synthesis_output_ids`、candidate ID/公开 capability card、公开 reason code 和 coverage atom ID；不得包含 `EvidencePathWitnessV1`、Tool implementation identity、Resource/Adapter identity/hash 或私有路径。Planner 也只接收该 public projection。

`required_coverage_atoms`、`plannable_coverage_atom_ids` 与 `required_synthesis_output_ids` 在调用 Planner 前按 7.3 冻结；plannable 集保持 required atom 的相对顺序，检索阶段的初始 blocking atom 是两者的有序差集。Coverage Atom 是按 `kind` 分派的判别联合；校验不得从展示 label 或 canonical ID 反解析 `compatible_output_kinds`。`coverage_witness_skill_ids` 中最多 6 个 candidate 的 witness coverage 并集必须覆盖全部 plannable atom。每个 candidate 的 `coverage_witness_scenario_id` 标识 7.3 选中的唯一 variant，`covered_requirement_ids` 必须恰好等于该 variant 对 `plannable_coverage_atom_ids` 的有序覆盖子集；`null` 表示不绑定 Scenario 的通用 variant。Evidence coverage 还必须有同 candidate 内的 `EvidencePathWitnessV1`，冻结当时实际获准的 Tool implementation 与 Resource/Adapter identity；EvidenceAtom 的 policy id/version/hash 只作 drift fence，不要求新增历史 policy resolver。比较与完成判定只使用 atom ID，label 只用于展示，具体谓词读取同一 snapshot 内冻结的结构化字段。repair、编辑和 DeepSearch 同 Run 恢复都读取这些冻结值，不得从当前 Profile、Catalog 或检索结果重建；当前 Evidence Policy identity 与冻结值任一不同时必须 replan，不能给旧 snapshot 新增或删改 coverage。

Evidence Policy 发布前必须只读枚举引用旧 identity 的非终态 Plan。正常升级要求数量为 0，否则延期发布或由用户显式 cancel + replan；安全紧急升级则先按 16.3 停流并终态化受影响 Run，再发布新 policy。不得接受“批量在途 Plan 下次碰到时再随机失效”的未定状态，也不设绕过 drift fence 的兼容开关。

最终 `SkillPlan.synthesis_output_contract` 必须包含全部 `required_synthesis_output_ids`，模型和客户端只能增加合法可选输出，不能缩小服务端义务。`SkillPlan.capability_gaps` 始终按 `required_coverage_atoms` 减去当前具体节点/assignment coverage 后重算，并另含未解决的 `scenario_assignment_required:*`；不能把初始差集当成永久 gap。

生成 draft 前，服务端必须在同一事务中创建 `status=PLANNING`、`nodes=[]` 的 SkillPlan skeleton，写入完整 Candidate Snapshot 及其 `candidate_skill_ids` 投影，并把 `AgentRun.status=PLANNING` 的 Run 关联到该 Plan。Plan compiler 随后通过预期 version 与 `PLANNING` 状态的 compare-and-set 写入节点和下一状态。同进程内的 Provider、repair 或校验失败，必须在同一事务中把 Plan 与 Run 置为 `FAILED` 并记录稳定错误。Standard 进程崩溃后不自动重放 Planner；新进程只能在旧进程已停止且独占该 SQLite 后运行现有 `reconcile_orphaned_agent_runs()`。遗留 `PLANNING` skeleton 直接把 Plan/Run 置为 `FAILED + process_restarted`。对已经进入执行的 Plan，所有遗留 RUNNING READ/DRAFT 节点置为 `FAILED + process_restarted`，所有未启动节点置为 `CANCELLED`；若还存在 RUNNING `local_write`/`external_write` 节点，则这些写节点置为 `FAILED + external_outcome_unknown`。完成所有节点终态化后，统一按 7.6 的 `has_valid_partial_delivery` 把 Plan/Run 置为 `PARTIAL` 或 `FAILED`，禁止自动重放；不存在写节点时也不得只写错误码而遗漏 Plan/Run 终态。这里复用现有 DeepSearch 稳定错误码 `external_outcome_unknown`，不新增同义码。多进程或滚动副本共享 SQLite 不受支持；本期不为 Standard 新增租约、心跳或第二套恢复调度器。

Phase 3 的 DeepSearch 仍先持久化这份 Plan 快照，再以其 hash 建立计费 operation identity；FrozenPlan v2 在计划编译完成后生成。DeepSearch 沿用现有持久化预算和恢复协调器，同一 Run 的恢复只能读取已持久化的 Candidate Snapshot，不能重新检索。Phase 2A/2B 的 DeepSearch 继续使用 FrozenPlan v1，不要求 Candidate Snapshot。

`SkillPlan` 新增可空 `candidate_snapshot`。Phase 2A 起新 Standard Plan 和 Phase 3 新 DeepSearch Plan 必须有快照，并满足 `candidate_skill_ids == candidate_snapshot.candidates[*].skill_id`，包括顺序；旧 Plan 及 Phase 2A/2B DeepSearch 的空值只走 legacy 分支，不回填。首次调用与一次 repair 使用同一个 snapshot hash 和同一组能力卡。新语义下的 replan/retry 创建新 Plan 与新快照；只有 DeepSearch 的同 Run crash resume 继续使用旧快照。

本期新 Plan 节点只有两种来源，不新增持久化 `selection_source` 字段：

| 派生来源 | 判定方式 | 字段合同 | 执行重验 |
| --- | --- | --- | --- |
| `scenario_mapping` | `skill_registry_id != null` | 必须同时有合法 `task_id`、`scenario_id`、`skill_status` | 校验 Registry 条目与 Scenario mapping 成员关系 |
| `universal_retrieval` | `candidate_snapshot != null` 且 `skill_registry_id == null` | `task_id/scenario_id` 仅作语义与完成检查提示；`skill_status=null` | 校验候选快照、Profile、Tool、资源、权限和副作用，不校验 Scenario mapping 成员关系 |

自然语言 DIRECT 请求产生的确定性单节点 Plan，以及 Plan 编辑中新加的候选，都属于 `universal_retrieval`。`direct_explicit` 继续由顶层 Run 的 `skill_id/skill_name` 且 `plan_id=null` 派生，位于 SkillPlan 合同之外；DeepSearch 继续拒绝显式调用。非 builtin 或无已审 Profile 的 Skill 只能走 direct explicit。planned explicit 没有现有 producer，本期不实现，也不得仅凭 `intent.explicit_skill_names` 推导节点来源。

对旧 Plan 的兼容规则：

- 已有 `skill_registry_id` 的节点继续走旧 Registry 重验，包括历史上 `scenario_id=null` 的 deliverable fallback 节点。
- `candidate_snapshot=null` 且没有 `skill_registry_id` 的旧节点派生为 `legacy_unmapped`，继续按旧候选与 Profile 规则重验。
- API 或事件需要展示来源时，通过同一个纯函数派生，不写回旧记录。

该设计不增加 SQLite 列。Standard Plan 继续存入现有 JSON payload；DeepSearch v1 保持字节级不变，新 Universal 语义在 Phase 3 写入 FrozenPlan v2。

### 7.6 Universal 节点的 Scenario、Knowledge 与 Completion

Universal 节点可由服务端绑定 `task_id/scenario_id`，以复用 Scenario 的输出和完成标准，但必须保持 `skill_registry_id=null`。模型不提交 Scenario hint 或最终归属。

规则：

1. routed Planner 的 Prompt 只展示本次路由选中的 Scenario ID、output `id/label` 和 completion criteria，供其选择 output kind；临时输出 Schema 不接受 `scenario_hint_id`、`task_id` 或 `scenario_id`。
2. 服务端以纯函数计算节点可归属的 Scenario。节点 `output_contract` 必须与该 Scenario 至少一个必需 output 的 `compatible_output_kinds` 相交，比较只使用机器 ID 和受审映射，不依赖节点遍历顺序或当前 coverage 状态。
3. 唯一匹配由服务端自动绑定；没有匹配时节点保持未绑定，只参与 Plan output contract；多于一个匹配时节点保持 `scenario_id=null`，产生 `scenario_assignment_required:<skill_id>`，由用户在 Plan 编辑中选择。
4. 初始规划出现多义归属时不得让创建请求失败。服务端持久化 `SkillPlan.status=WAITING_APPROVAL`，并保持 `AgentRun.status=WAITING_PLAN_APPROVAL`，随后在 Plan Detail 返回派生的 `scenario_assignment_options[skill_id]`。每项包含允许的 Scenario ID、标题及匹配的 output ID/label，该字段不写入 Plan 或 FrozenPlan。
5. 只要存在 `scenario_assignment_required:*`，批准接口必须以 `scenario_assignment_required` 拒绝，执行入口也必须 fail closed。合法编辑后，服务端重新计算 options、gap、completion metadata 和 Plan version。
6. 服务端把已验证的 assignment 写入现有 `SkillPlanNode.scenario_id`，并从 Catalog 复制 `task_id` 与 `completion_criteria`；模型不能提交这些最终可信值，客户端只能通过受限 `scenario_assignments` 编辑字段从服务端给出的 options 中选择。
7. Universal 节点不自动继承 Scenario mapping 的 Knowledge Binding；它只读取 Skill 自有批准资源、用户显式输入和已授权上游结果。
8. 没有 `scenario_id` 的 Universal 节点只按 Plan output contract 参与完成检查；若必需 Scenario 未覆盖，服务端写入 blocking gap，Plan 不得标记 completed。

所有 atom 的 Plan/Result coverage 由服务端统一计算：

```text
can_plan_cover_atom(node, atom)
  deliverable = atom.output_kind ∈ node.output_contract
  scenario_output = node.scenario_id == atom.scenario_id
                    AND node.output_contract ∩ atom.compatible_output_kinds != ∅
  evidence = node 对该 atom 存在同一 Candidate Snapshot 中的
             EvidencePathWitnessV1，且 identity 与节点冻结 Tool/Resource 一致

is_result_cover_atom(node, result, atom)
  common = can_plan_cover_atom(node, atom)
           AND node.status == completed
           AND result.node_id == node.id
           AND result 包含非空 deliverable 或已封存 Artifact
  deliverable = common AND atom.output_kind ∈ result.delivered_output_kinds
  scenario_output = common AND atom.output_id ∈ result.scenario_outputs
  evidence = common AND result.evidence_items 中至少一项具有该节点血缘、
             受信任外部来源与已封存 Artifact，并通过执行后 Evidence Policy
```

部分成功只使用一个服务端谓词：`has_valid_partial_delivery` 为真，当且仅当至少一个节点结果通过 `is_result_cover_atom` 覆盖冻结的 `required_coverage_atoms`，或 `required_synthesis_output_ids` 中至少一个 output 已经仅基于至少一个已验证节点结果成功生成并封存。diagnostic、日志、空 claim、越界 output 和未封存内容都不计；Plan 与 Run 必须根据同一个谓词同步进入 `PARTIAL` 或 `FAILED`。

新语义 `SkillNodeResult` 增加唯一、有序的 `delivered_output_kinds`，必须是节点 `output_contract` 的子集，并由执行器在保存非空 deliverable/已封存 Artifact 时一起校验；节点承诺 A+B 而结果只声明 A 时，B 不得视为已交付。旧结果缺少该字段时只走 legacy completion，不能套用新合同。节点结果只能声明服务端传入的允许 output kind/Scenario output ID，越界值拒绝；这些声明只是谓词输入，模型不能直接设置 coverage 结果。Plan compiler、编辑、批准和重试用 `can_plan_cover_atom` 按最终选中节点集重新计算 capability gaps，完成与部分成功用 `is_result_cover_atom`。Scenario criteria 只能在结果阶段根据 `completion_criteria_met` 验证，不能从 output kind 推定；Evidence requirement 继续由 Evidence Policy 单独验证。最终 completed 必须同时满足 required nodes、Plan output contract、全部必需 atom、全部 `required_synthesis_output_ids` 已成功生成并封存、Scenario criteria、证据要求和无未解决 blocking gap。

采用新 canonical output 合同的 Plan 中，Synthesis 只能汇总已由节点结果覆盖的 output ID，不能仅凭 presentation output 或 claim 自动覆盖整个 Scenario。现有 `_SYNTHESIS_SCENARIO_PRESENTATIONS` 捷径只保留在 legacy Plan 分支。

这样 Task/Scenario 仍然定义“什么叫完成”，但不再决定“只能使用哪个 Skill”。

### 7.7 LLM Planner 合同

Planner 输入：

- 标准化用户目标；
- 输入和交付物；
- 分析、展示与证据要求；
- Task/Scenario 提示与完成标准；
- Candidate Snapshot 中最多 12 张 ready 安全能力卡；
- 冻结的 required/plannable atom、`required_synthesis_output_ids`，以及最多 6 个 coverage witness candidate ID 和各自的 witness reason；
- 非敏感的 blocking capability gap 摘要；informational blocked-match 仅用于解释候选选择。

完整 Planner request canonical JSON 不超过 64 KiB，输入预算不超过 24,000 tokens，并为模型输出保留配置中已有的 output budget。优先使用配置模型的 tokenizer；Provider 不提供 tokenizer 时，以 UTF-8 byte 数作为保守 token 上界。超限时在模型调用前以 `planner_context_budget_exceeded` 终态化已创建的 Plan/Run，不截断用户要求、coverage atom、witness 或能力卡，也不通过减少候选规避合同。

Planner 与 Embedding 使用同一数据出境底线：只发送经 `redact_sensitive_text()` 处理后的标准化目标、必要的有界输入摘要、服务端义务和公开能力卡；不得发送凭据、联系方式、本地路径、私有记忆正文、附件/文档正文、原始 Tool 输出、Evidence 私有路径或被过滤 Skill 信息。拟上线 Planner Provider 的区域、不用于训练/持久保留策略和审计日志策略必须在 Phase 1B 发布报告中获批；无法安全摘要的输入必须先澄清或 fail closed，不能为完成规划而扩大数据面。事件只记录 request hash、模型/区域、输入输出 token、延迟、重试/repair 次数和 Provider 可用的费用数据，不记录原始 Prompt；24,000-token 是拒绝上限，Phase 2A 真实 Preview 同时报告 p50/p95 token 与单请求费用，并按既有预算告警。

Planner 看到的每个候选只包含：

- Skill ID、名称、标题、公开短描述；
- 生命周期和能力类型；
- 输入、输出；
- side effect、成本与风险级别；
- 必需 Tool 的公开名称；
- 服务端生成的稳定检索理由代码。

Planner 可以：

- 从候选 ID 中选择最多 6 个 Skill；
- 声明依赖、并行组和必要性；
- 将用户输入或直接祖先输出绑定为输入；
- 选择候选 Profile 已声明的输出；
- 提议合法的可选输出与呈现方式；不能删除服务端冻结的 required synthesis output。

第一版保持现有唯一性约束：同一 Plan 中每个 `skill_id` 最多出现一次，`duplicate_skill` 继续作为确定性校验错误。同一 Skill 若匹配多个 Scenario，用户必须选择唯一归属；本期不通过重复节点再次执行同一 Skill。

Planner 不可以：

- 发明候选之外的 Skill；
- 提交 Skill/Profile version/hash、Tool、资源、副作用、Knowledge Binding 或 capability gaps；
- 把 blocked Skill 放进节点；
- 通过计划扩大 Tool Grant；
- 直接读取完整 Skill 指令、私有资源或被过滤 Skill；
- 自行声明 Registry mapping、Knowledge Binding、Task ID 或 Scenario 完成标准。

LLM 输出只包含 `skill_id`、依赖、并行组、必要性、input binding、所选 output kind 和可选输出提议。Schema 通过后，服务端 Plan compiler 从 Candidate Snapshot 与当前可信 Profile 纯函数派生 Scenario assignment，并补入 Skill/Profile identity、`task_id/scenario_id`、`completion_criteria`、空的 Universal Knowledge Binding、Tool、Resource Manifest 和 side effect，以 `required_synthesis_output_ids ∪ 合法可选输出` 构造最终 `synthesis_output_contract`，并重新计算 capability gaps。

自然语言中的直接单 Skill 请求只有满足以下服务端谓词，才能使用确定性单节点 `universal_retrieval` Plan：存在一个 ready candidate，其单一 witness variant 覆盖全部非空 `plannable_coverage_atom_ids`；全部 input binding 可直接绑定用户输入；Scenario assignment 为无匹配或唯一匹配；无需依赖或并行节点。同一请求有多个合格 candidate 时按 Candidate Snapshot rank 取首个。`intent.complexity=DIRECT` 本身不构成捷径资格；任一条件不满足时走 LLM Planner，不得固定取首候选或让 repair 重走同一个确定性分支。显式 `$skill` 仍走 7.5 的 direct explicit 路径。复合任务必须经过 LLM Planner；第一次结构或语义校验失败后允许带稳定错误码修复一次，第二次失败返回稳定错误。

Schema/语义 repair 与 Provider 重试是两套机制。连接失败、超时、HTTP 408/429/5xx 等瞬时错误按现有模型重试策略和同一幂等键处理，不消耗 repair 次数；认证、账户、模型或配置类确定性 4xx 不重试。DeepSearch 的每次物理尝试仍进入持久化 budget，Standard 使用现有有界重试。

### 7.8 确定性验证

`validate_draft()` 继续作为信任边界。以下新增校验适用于带 Candidate Snapshot 的新语义 Plan；legacy Plan 与 Phase 2A/2B DeepSearch 继续走原版本校验器，不套用新字段：

- Candidate Snapshot 的 canonical hash、candidate 顺序/唯一性及 `candidate_skill_ids` 投影必须一致；required atom 的顺序/唯一性、plannable 子集顺序、最多 6 个 `coverage_witness_skill_ids` 的合法子集及其 coverage 并集，以及每个 candidate 的单一 variant witness/coverage 子集也必须一致；
- 所有节点必须属于本次最多 12 个 Candidate Snapshot entry，且 entry 在规划时必须 `ready_at_planning=true`；
- Skill/Profile identity 必须与 snapshot 中的 version/hash、profile version/hash 和 capability-card hash 一致；漂移时返回 `candidate_snapshot_stale` 并要求 replan，不得静默刷新快照。`retrieval_policy_version` 是已冻结的审计/重放身份，只校验字段与 snapshot hash 的内部一致性，不要求等于当前默认策略；新策略发布不得使在途 Plan 失效；
- Plan 内 `skill_id` 必须唯一，同一 Skill 的重复节点以 `duplicate_skill` 拒绝；
- 节点来源必须满足 7.5 的联合类型合同；
- 模型选择的输出必须属于 Profile；Tool、资源、side effect 和其他可信字段只能由服务端填充；
- 依赖必须无环、深度不超过 4、并行不超过 3；
- input binding 只能来自用户输入或直接祖先的兼容输出；
- Universal 节点不得携带 Registry 专属状态或隐式 Knowledge Binding；
- 有 routing result 的 Plan 必须按其 `catalog_version/catalog_hash` 读取精确 Task Catalog；缺失或 hash 不匹配时返回 `task_catalog_snapshot_unavailable`，不得用当前默认版本替代；
- Scenario assignment 和 coverage 必须满足 7.6 的 canonical output 合同；未解决 assignment 时禁止批准和执行；
- capability gaps 必须等于服务端根据最终节点集、Scenario 和 Evidence requirement 重算的结果；
- `synthesis_output_contract` 必须包含 Candidate Snapshot 中全部 `required_synthesis_output_ids`；模型、编辑和 retry 都不能删减，最终完成逐项验证已成功生成并封存；
- 外部写入必须由用户明确请求并进入审批；
- DeepSearch 事实性节点必须满足 Evidence Policy；
- Task/Scenario 推荐永远不构成权限或执行资格。

批准、节点启动或恢复时，服务端先按 snapshot entry 重验静态 Skill/Profile/card identity，再检查当前 Skill 可见性、Binding、Tool health、Tool Grant、Resource Manifest、side effect 和项目范围。Evidence atom 的 Plan coverage 始终读取 snapshot 中冻结的 `EvidencePathWitnessV1`；当前 Evidence Policy 的 id/version/hash 与 atom 冻结值任一不同时，返回 `evidence_policy_changed` 并要求 replan，不能用当前规则静默重解释旧 snapshot。其他静态 identity 漂移返回 `candidate_snapshot_stale`；动态 readiness 变化返回对应稳定代码。所有变化都 fail closed。

写节点采用保守 outcome 合同：在节点 claim 为 `RUNNING` 前被确定性校验拒绝，可以记录普通失败；一旦 `local_write`/`external_write` 节点已 claim，只有 Tool 返回可验证的确定失败或成功结果才能写普通终态。timeout、连接中断、task cancel、用户取消、进程关闭或崩溃若没有 Tool 专用确认结果，写节点一律进入 `FAILED + external_outcome_unknown`。存活进程主动收口时，其余所有非终态节点（包括并行 RUNNING READ/DRAFT）进入 `CANCELLED`；崩溃后由 7.5 的 orphan reconciliation 把 RUNNING READ/DRAFT 置为 `FAILED + process_restarted`、未启动节点置为 `CANCELLED`。全部节点终态化后，Plan/Run 按 `has_valid_partial_delivery` 进入 `PARTIAL` 或 `FAILED`。现有错误码名称虽含 `external`，本方案为兼容也用于 outcome 无法确认的 local write。该终态禁止自动 retry/replan，late callback 不能改写。

资源冻结规则：

- Phase 2A 起，新建的 Standard `universal_retrieval` 节点也必须在 Plan 创建/编辑时写入 `SkillResourceManifestV1`，不能继续只读取 live manifest。
- 新节点启动时比较当前资源与冻结 manifest；不一致则以 `skill_resource_changed` 失败，不悄悄换用新内容。
- 旧 Standard 节点若 `resource_manifest=null`，继续使用现有 legacy live-manifest 行为，避免回写历史 Plan。
- DeepSearch 继续要求每个节点都有冻结 manifest，规则不变。

### 7.9 Plan 编辑与 Run 重试

Plan 编辑：

- 以下规则适用于带 Candidate Snapshot 的新语义 Plan。legacy Standard Plan 与 FrozenPlan v1 沿用现有 live 候选重验；有 `routing_result` 时按保存的 Task Catalog v1 version/hash 执行原编辑合同，unrouted Plan 不读取 Catalog。它们不能通过 PATCH 混入 Universal 节点；只有对应模式已到达 7.10 矩阵规定的新语义 Phase 后，显式 replan 才升级合同。
- 只能从原 Candidate Snapshot 中增删，仍不超过 6 个节点；PATCH 不得重新调用检索器构造 shortlist。
- 保留已有节点的来源元数据。
- `SkillPlanUpdateRequest` 增加可选 `scenario_assignments: dict[skill_id, scenario_id|null]`，最多 6 项；由于 Plan 内 `skill_id` 唯一，该键无歧义。
- 用户新加的候选默认形成 `universal_retrieval` 节点。合法 assignment 当次写入；唯一匹配自动绑定；多义且未提供 assignment 时仍保存节点、保持 `WAITING_APPROVAL` 并返回允许选项，不猜测也不丢弃本次编辑。
- 只有已有节点本来具有合法 Registry metadata 时才保留 `scenario_mapping` 来源；编辑新增节点不自动伪造 Registry 关系。
- 每次编辑按 Candidate Snapshot 加载当前 Skill/Profile，并核对静态 identity；任一项漂移返回 `candidate_snapshot_stale`。冻结的 `retrieval_policy_version` 不与当前默认值比较，动态 Tool/Grant 状态只对选中节点重新检查。
- 编辑后重新计算依赖、并行组、output contract、scenario assignment options、capability gaps 和 Plan version；`synthesis_output_contract` 始终并回全部冻结的 `required_synthesis_output_ids`，未解决归属可以继续编辑，但不能批准或执行。
- Phase 3 的 DeepSearch v2 编辑继续产生新的 FrozenPlan v2 快照与 Plan hash，不修改旧快照或 Candidate Snapshot。FrozenPlan v1 编辑继续留在 legacy 分支；切换 Universal 语义必须显式 replan 为 v2。

`replan` 不复用 PATCH，也不新增 Endpoint。对 `WAITING_PLAN_APPROVAL` 等非终态 Run，客户端先调用现有取消接口，以 compare-and-set 将旧 Run/Plan 置为终态，再用新的 `client_turn_id` 调用现有 `POST /api/agent/runs/{run_id}/retry`。Retry 通过 `retry_of_run_id` 保留 lineage，并创建新 Run 与 Plan；只有 Standard 已进入 Phase 2A 或 DeepSearch 已进入 Phase 3 时，才同时创建当前 Catalog v2 与 Candidate Snapshot，Phase 前行为保持 7.10 矩阵中的旧合同。旧 Plan 保持不可变。取消成功但 Retry 响应丢失时，用同一 `client_turn_id` 重放即可；取消未成功时不得创建新 Run。`candidate_snapshot_stale`、Catalog 升级和 FrozenPlan v1 切换 v2 都在相应新语义 Phase 启用后走该流程。

重试：

- 对已启用新语义的 planning mode，按原模式使用同一全量检索策略，创建新 Plan 与新 Candidate Snapshot，不再对 routed 请求调用 `recommend_for_route()`；Phase 2A 前的 Standard 和 Phase 3 前的 DeepSearch 仍按 7.10 唯一矩阵重建旧合同。
- Standard 跨 Run 只复用满足以下完整性谓词的节点结果：节点为 completed；side effect 为 READ/DRAFT；`required_tool_names` 为空；Profile 不产生事实性结论；Skill version/hash 与冻结 Resource Manifest 均一致；结果 identity、output contract、Scenario outputs、Source/Artifact 访问范围全部重新校验通过。
- 不满足完整性谓词的 Standard 节点重新执行；使用 Web/外部 Tool 或产生事实性结论的节点不得跨 Run 复用。
- DeepSearch 禁止跨 Run 复用节点结果；Retry 重新进入 Requirement/Problem Graph/Plan 流程。仅同一 Run 的 crash resume 可以沿用原 Candidate Snapshot，并按已封存 Evidence/Artifact checkpoint 继续。
- 任何来源 Run 只要自身结果码为 `external_outcome_unknown`、含该结果码的节点，或防御性检查发现任一非纯读 `RuntimeToolCallClaimV1` 尚未被 Tool 专用对账确认可安全重试，所有 retry producer（包括现有 `POST /api/agent/runs/{run_id}/retry`）都必须在创建新 Run 前返回稳定 `409 + external_outcome_unknown`。该规则与 `plan_id`、planning mode 和 direct explicit/`skill_id=null` 路径无关，不能只禁止后台自动 retry/replan；本地 `call_id` 或普通 `tool_call_settled` 不能证明端到端交付已完成。Tool 专用对账只能追加一条关联 `call_id` 的不可变 reconciliation/audit 记录，不得覆盖原 Node/Plan/Run 终态或改写已封存 Artifact/hash。只有该记录确定原调用结果，且对应 Tool 的专用政策明确允许后续操作时，用户才能另行发起新请求；本期不新增通用对账、终态纠正或补偿框架。
- 撤销授权、Tool 失效、Profile 漂移或候选退出时，重试必须失败或重新规划，不能沿用旧资格。
- `client_turn_id`、retry lineage 和节点 attempt 继续保证幂等。

### 7.10 Standard 与 DeepSearch

| 项目 | Standard | DeepSearch |
| --- | --- | --- |
| 检索全集 | 当前 Agent 全部 Searchable builtin Runtime Skill | 当前 Agent 全部 Searchable builtin Runtime Skill |
| Planner shortlist | 最多 12 个 ready Skill | 最多 12 个且满足 DeepSearch 工具/证据政策的 ready Skill |
| 最大节点 | 6 | 6 |
| 外部事实要求 | 按任务判断 | 强制 Evidence Policy |
| 可用 Tool | 当前授权 Tool | DeepSearch runtime v1 的受信任证据路径与现有白名单 Tool；FrozenPlan v1/v2 均执行同一政策 |
| 生成式 LLM 预算 | 现有 Standard 限制 | 所有生成式 LLM 调用进入持久化 DeepSearch budget |
| 报告 | 节点交付物 + Synthesis + HTML | Evidence Manifest + Coverage + Review + HTML |

DeepSearch 第一版不增加 LLM rerank，因此不会产生新的生成式 LLM 分支。已有 Requirement、Problem Graph、Skill Plan、Synthesis 和 Review 调用继续通过 `DeepSearchBudgetMeter`。FrozenPlan v2 的 Skill Plan operation key 使用 Requirement hash、Problem Graph hash、`routing_catalog_identity` 和 `candidate_snapshot.content_hash`，覆盖 Scenario 语义、coverage obligations、Skill/Profile/card identity 与检索策略版本；FrozenPlan v1 保持现有 operation key 与 canonical hash 合同，不读取不存在的 Candidate Snapshot。检索中的单次批量 Embedding 是可降级的检索基础设施，不计入 `DeepSearchBudgetMeter.llm_calls/tokens`；它单独记录请求次数、模型、延迟、成功/降级结果和 Provider 返回的用量数据，不因记账失败阻断 FTS 降级。

多轮澄清仍发生在候选冻结之前。每次用户回答形成新的 Requirement version 后，必须用新 Requirement hash 重新检索；旧 Candidate identity、Problem Graph 和未批准 Plan 不得跨版本复用。相同 clarification request 的重放继续命中现有幂等键，不重复创建版本或消耗预算。

DeepSearch 冻结兼容策略：

- `DeepSearchFrozenPlanV1`、`DeepSearchPlanSnapshotV1` 及其 canonical hash 保持字节级不变，只负责旧 Artifact。
- Phase 3 新建、replan 或 retry 的全部 DeepSearch Plan 使用 `DeepSearchFrozenPlanV2` 与 `DeepSearchPlanSnapshotV2`，嵌入 `CandidateSnapshotV1`；`candidate_skill_ids` 作为兼容投影保留，且必须与快照顺序一致。
- FrozenPlan v2 构建、读取和恢复时都必须满足 `frozen_plan.candidate_snapshot == SkillPlan.candidate_snapshot`，两侧 Candidate Snapshot hash、`candidate_skill_ids` 投影和顺序必须一致；任一处不一致均按快照篡改 fail closed。
- v2 `plan_content_hash` 覆盖完整 Candidate Snapshot 及 `routing_catalog_identity`；routed 固定 Task Catalog version/hash，unrouted 固定 canonical `null`。节点来源由已冻结的 `candidate_snapshot`、`skill_registry_id` 和 `scenario_id` 派生。
- 旧 v1 快照继续按原 hash 校验、读取和恢复。v1 若要进入 Universal 语义，必须显式 replan 为 v2，不原位升级，也不修改旧 Artifact。
- 若未来确实增加 LLM rerank，必须单独纳入 durable budget、operation key、重放和恢复测试，不在本方案中隐式加入。

兼容分支以下表为唯一矩阵，其他章节不得再定义新组合：

| Plan 来源 | Run planning contract | Task Catalog | Candidate Snapshot | 冻结合同 | 允许的后续操作 |
| --- | --- | --- | --- | --- | --- |
| legacy Standard | 缺失或 `standard_legacy_v1` | v1；unrouted 为 N/A | 空 | 旧 Plan JSON | 读取及按原合同编辑、批准和执行；Phase 2A 前 retry/replan 仍用旧合同，Phase 2A 起创建 v2 新 Plan |
| Phase 2A+ Standard | `standard_universal_v1` | v2；unrouted 为 N/A | v1 | 新 Plan JSON | 按新合同编辑、批准、执行和 retry |
| legacy/Phase 2A/2B DeepSearch | 缺失或 `deepsearch_frozen_v1` | v1；unrouted 为 N/A | 空 | FrozenPlan/Snapshot v1 | 读取及按原合同编辑、批准、执行和恢复；Phase 3 前 retry/replan 仍为 v1，Phase 3 起创建 v2 |
| Phase 3+ DeepSearch | `deepsearch_frozen_v2` | v2；unrouted 为 N/A | v1 | FrozenPlan/Snapshot v2 | 按新合同编辑、批准、执行、恢复和 retry |

全局 `off` 高于表中 Plan 操作：禁止新建 planned orchestration Run、Plan PATCH/批准/拒绝/执行、planned Tool approval resolution、resume、retry/replan 及内部 recovery schedule，只允许读取、显式取消、回滚预检和不产生新工作的 fail-closed orphan 终态化。direct explicit 与 `skill_id=null` 的既有通用 AgentRuntime 对话不生成 Plan，`off` 下继续按既有合同运行；进程级 quiesce 则为安全停机而临时阻断全部新 AgentRuntime/Tool dispatch，包括这两类 Run 的 start/resume。进程以 `off` 启动时不得启动 Recovery Coordinator；即使测试或运维代码直接调用 `recover_once()`，它也必须在枚举前及每次 schedule 前重读全局 mode，并对 v1/v2 Run 一律 no-op。

### 7.11 Tool-limited Skill

27 个 `tool_limited` Skill 的本阶段行为：

1. 作为已审、Binding 开启的 builtin Skill 参与 Searchable Corpus 排序。
2. 缺少必需工具时标记 blocked，不进入 12 个 selectable candidates。
3. 高相关 blocked Skill 先以 informational blocked-match 展示；只有 7.6 的服务端 coverage 谓词确认必需 requirement atom 无 ready 覆盖时，才形成 blocking capability gap。
4. ready Skill 覆盖同一组必需 requirement atoms 时，Planner 可以从 ready shortlist 选择替代项，报告披露能力差异。
5. 不允许删除工具要求后以纯文本方式假执行。

本方案交付“84 个 Skill 均可被发现和正确判断 readiness”；不承诺“84 个 Skill 当前全部可执行”。

## 8. 数据、API 与事件合同

### 8.1 持久化数据

保持 SQLite 表结构与现有数量上限，新增版本化 JSON 合同：

- `SkillPlan.candidate_snapshot`: Phase 2A 起新 Standard Plan 与 Phase 3 新 DeepSearch Plan 必填的 `CandidateSnapshotV1`；旧 Plan 和 Phase 2A/2B DeepSearch 允许为空并走 legacy 分支。
- `AgentRun.planning_contract_version`: 可空、不可变的 JSON payload 字段；新 Plan-producing Run 必填，旧 Run 缺失时只按 7.5 的 legacy 默认读取。它在任何异步规划前冻结目标 Plan/FrozenPlan 代际，不增加 SQLite 列。
- `SkillPlan.candidate_skill_ids`: 最多 12，作为 Candidate Snapshot 的顺序一致兼容投影保留。
- `SkillPlan.nodes`: 最多 6，不变。
- `DeepSearchFrozenPlanV1` 与 `DeepSearchPlanSnapshotV1`: 字段和 hash 规则不变，只负责旧 Artifact。
- `DeepSearchFrozenPlanV2` 与 `DeepSearchPlanSnapshotV2`: 新增 Candidate Snapshot，候选和节点上限仍为 12/6。
- Task Catalog v1/v2：v1 文件与 hash 保持不变；routed Plan 通过已有 `routing_result.catalog_version/catalog_hash` 固定读取版本，unrouted Plan 使用 canonical `routing_catalog_identity=null` 且不读取 Catalog；v2 承载 canonical Scenario output。
- `SkillCandidate.ready/diagnostics`: 正式承担 readiness 与安全诊断合同。
- `SkillPlan.capability_gaps`: 只保存服务端根据最终节点集计算、会阻止 completed 的稳定缺口。
- 新语义 `SkillNodeResult.delivered_output_kinds`: 唯一有序、必须为节点 `output_contract` 子集；与非空 deliverable/已封存 Artifact 一起作为 deliverable result coverage 的必要条件，legacy 结果允许缺失。
- `RuntimeToolCallClaimV1`: 在任何 Runtime Tool Provider 调用前，与 Run 当前状态以同一 repository 事务追加 server-internal `tool_call_claimed` 记录；字段包含唯一 `call_id`、`run_id`、可空 `plan_id/node_id`、Tool implementation identity、原始 `ToolDefinition.side_effect`、operation identity 和时间。对非纯读 Tool，claim 一经提交就保守视为 UNKNOWN-until-settled，不能以“尚未看到 Provider 响应”推断未发生副作用。Provider 返回并持久化结果后追加唯一 `tool_call_settled`；进程关闭、崩溃或回滚发现 claim 没有 settled 记录时，仅精确值 `side_effect=read` 追加 `tool_call_abandoned + process_restarted`，现有 `write|external|idempotent_write|non_idempotent_write` 以及未知/缺失值一律追加 `tool_call_outcome_unknown + external_outcome_unknown`。此外，启动 reconciliation 或离线回滚终态化任何无 Plan 的非终态父 Run 时，必须检查该 Run 的完整 claim 历史，而不只查未 settled claim；只要曾提交任一非纯读 claim，即使已有 `tool_call_settled`，父 Run 仍保守进入 `FAILED + external_outcome_unknown` 且禁止自动 retry，因为 Provider settlement 不能证明父 Run 已把副作用结果完整交付给用户。Plan Run 再按 7.6 进入 `PARTIAL`/`FAILED`。这些都是 append-only 审计事实，不允许覆盖原 claim 或 settlement。
- Recommendation/事件 diagnostics：保存相关但已被替代或非必要的 informational blocked-match，不参与完成判定。
- 新 Standard Universal 节点：`resource_manifest` 必填；旧 Standard 节点允许为空并走 legacy 兼容分支。

本方案不要求 SQLite 列迁移，Run 与 Plan 继续保存为 JSON payload，Tool call claim/settlement 复用持久化 AgentRun event store。repository 必须以 `call_id` 做 CAS 去重，并能在启动 reconciliation 与独占停机扫描中枚举 claimed 但未 settled/unknown 的调用，以及所有附属于非终态无 Plan Run 的 claim。新代码必须同时读取 legacy Plan、FrozenPlan v1 和 FrozenPlan v2；旧 v1 Artifact 保持可读、可验证、可恢复。

### 8.2 公共 API

产品 API 不新增 Endpoint，继续使用：

- `POST /api/skills/matches`
- `POST /api/skills/recommendations`
- `POST /api/skills/routing-preview`
- `POST /api/chat/messages`，任何进入 AgentRuntime 的分支，包括自然语言 planned orchestration、`$skill` direct explicit 与 `skill_id=null` 通用 Run，都受进程级 quiesce；`off` 只阻断 planned orchestration。完全不进入 AgentRuntime 的普通 chat 才可绕过 quiesce
- `POST /api/agent/runs`
- `POST /api/agent/runs/{run_id}/deepsearch/clarify`
- `POST /api/inbox/{item_id}/resolve-tool-approval`，approve 与 reject 都会进入现有 `resume_sync`；planned 与 direct-explicit Run 都受 quiesce，只有 planned Run 受 `off`
- 现有 Plan 编辑、确认、拒绝、执行、重试、取消和 SSE API

唯一新增的是不向普通客户端暴露的运维操作 `POST /api/admin/skill-orchestration/quiesce`。它必须复用现有认证并执行 `ensure_admin`，生产回滚只能从绕过公共入口 fence 的受控 loopback/管理路径调用。受信 ingress/部署 ACL 必须在网络边界只向 loopback 或管理网暴露该路径，并在公共入口拒绝它；应用不得通过客户端可伪造的 `Host`、`X-Forwarded-For` 或同类 Header 判断管理来源，`ensure_admin` 是网络隔离之外的第二道校验。该操作幂等地把进程内 `OrchestrationQuiesceController` 从 `open` 单向切到 `quiescing`，本进程生命周期内不可重新打开；controller 使用进程内 thread-safe lock，使 async route、Recovery Coordinator 与 `asyncio.to_thread()` 中的 `run_sync`/`resume_sync` 共用同一门禁。

planned orchestration 的 create、Plan PATCH/approve/reject/execute、DeepSearch clarify、Tool approval approve/reject resolution、retry/replan forward mutation，以及 executor 的 `READY → RUNNING` CAS、DeepSearch recovery scan/schedule，都必须取得短期 admission permit。所有 `AgentRuntime.run/run_sync/resume_sync` 分支及每次 Runtime Tool dispatch 也检查同一个 quiesce latch；direct explicit 与 `skill_id=null` 通用 Run 不检查 `AGENTMESH_SKILL_ORCHESTRATION=off`。成功的 `READY → RUNNING` CAS 是 node dispatch 的唯一线性化点；8.1 的持久化 Tool call claim 是 Tool dispatch 的线性化点。任一 claim 返回拒绝或空结果时绝不能调用 node runner 或 Tool Provider。当前 Tool approval reject 也会调用 `resume_sync` 并可能继续执行，不能把它误当成纯取消旁路。permit 检查与对应数据库事务或入队动作处于同一临界区，二者之间不得 `await` 外部 I/O，不能只在 HTTP 路由入口做一次易受 TOCTOU 影响的检查；长时间 LLM、Tool 或节点执行不得持有 permit，每次后续 CAS、Tool call claim 或入队都必须重新取 permit，一次 admission 不是整条 workflow 的通行证。

controller 为每个短期 permit 维护进程级 active count 与 condition。quiesce 在 admission lock 下把 latch 单向置为 `quiescing`，随后通过 condition 等待 `active_permits == 0`；等待会释放 mutex，不能把锁带入外部 I/O。已有或并发的 quiesce 调用共享同一个 completion future，必须等待同一轮清空，不得提前返回。短期 permit 清空后，quiesce 再调用并等待 `DeepSearchRecoveryCoordinator.begin_quiesce()` 取得其 scan lock、停止周期任务并等待当前 scan 退出。`recover_once()` 可以在持有 scan lock 时为单次 schedule 取得短期 permit；quiesce 绝不能持有 admission lock 等待 scan lock，由此固定锁序并避免锁环。

quiesce 响应后不得开始新的 AgentRuntime start/resume、用户或规划 forward mutation、`READY → RUNNING` claim、Tool call claim、recovery scan 或 schedule。latch 前已经提交 node/Tool claim 的工作可以保存结果并正常终态化；完成前驱后将依赖节点从 `PENDING → READY` 只是可允许的确定性记账，不构成 dispatch，但随后 `READY → RUNNING` 必须被 latch 拒绝。读取、显式 cancel 和 fail-closed orphan 收口也可以继续。它们不得 claim 或 dispatch 后继节点/Tool。进程随后按 16.3 立即 force-stop，停机后仍非终态的新语义 Run/Plan 与任何未解决 Runtime Tool call claim 由离线命令收口。

该运维操作不是运行模式切换：它不修改 `AGENTMESH_SKILL_ORCHESTRATION`，不持久化可恢复开关，也不能替代 `off` 重启。进程重启会重建 controller，因此回滚必须先关闭自动重启，最终以 `off` 启动。

被 quiesce 拒绝的新 AgentRuntime 工作统一返回 `503 + orchestration_quiescing`；被 `off` 拒绝的 planned orchestration 返回既有 disabled code，不得伪装成成功。幂等请求若在门禁检查前已经查到完整的既有响应，可以只读返回该响应；不得借重放创建缺失记录或继续未完成操作。完全不进入 AgentRuntime 的普通 chat、读取和显式 cancel 不取得新工作 permit；Plan reject 与 Tool approval approve/reject 都必须取得 permit，direct explicit 与 `skill_id=null` 通用 Run 只受 quiesce 而不受 `off`。

兼容性调整：

- `/routing-preview` 请求增加可选 `planning_mode`，默认 `standard`；响应增加将用于新 Run 的 `planning_contract_version` 与 Catalog identity。Phase 2A/2B 据此选择 Standard Universal/Catalog v2 或 DeepSearch FrozenPlan/Catalog v1，Phase 3 的 DeepSearch 再选择 FrozenPlan/Catalog v2。
- Recommendations 可以返回当前用户可见但 `ready=false` 的相关 Skill 与安全诊断。
- Plan Preview 只把 `ready=true` Skill 放入 candidate snapshot；blocking gaps 与 informational blocked matches 分区展示。
- Plan Detail、Preview、SSE 与 Planner 只能调用 7.5 的 Candidate Snapshot public projection；完整 snapshot 只在服务端存储/验证，Evidence path 与 Tool/Resource identity 不得外发。
- 响应增加可选统计：`searchable_count`、`selectable_count`、`blocked_match_count`；老客户端可忽略。
- UI 展示的 `selection_source` 由服务端按 7.5 派生，不进入持久化模型。
- Plan Detail 可返回派生字段 `scenario_assignment_options`，以 `skill_id` 为键，列出允许的 Scenario ID、标题及匹配的 output ID/label；不持久化该字段。
- Plan 编辑请求可选携带 `scenario_assignments`；旧客户端省略时仍执行唯一匹配推断，多义时返回可编辑的 `WAITING_APPROVAL` Plan。只有非法显式值或批准未解决 Plan 时返回稳定错误。
- UI 的 replan 操作复用现有 cancel + retry API：先终结旧 Run/Plan，再以新 `client_turn_id` 重试；`retry_of_run_id` 保留 lineage，任一步都按现有幂等/CAS 合同重放，不新增 `/replan`。
- 受保护的 `GET /api/health/providers` 增加只读字段 `skill_orchestration_mode` 与 `deepsearch_recovery_running`，供 `off` 重启后的 runbook 证明恢复调度器未启动；不得用 liveness `GET /api/health` 代替该检查。

### 8.3 运行事件

新增或扩展以下事件：

- `skill_pool_built`: 仅记录 installed、security_filtered、searchable、ready 数量。
- `skill_search_completed`: 记录 `candidate_snapshot_hash`、`retrieval_policy_version`、检索耗时、Embedding 批量调用次数/模型/延迟/降级结果及 Provider 可用的用量数据，以及最多 12 个候选的 Skill/Profile/card identity 与分数；不记录完整能力卡或原始查询文本。
- `skill_capability_gap_detected`: 仅记录会阻止完成的安全 gap code。
- `skill_blocked_match_detected`: 记录不影响完成判定的安全 readiness 诊断与内置 Skill ID。
- `plan_planning_failed`：记录 Plan version、snapshot hash 和稳定结果码。
- `planner_call_completed`：只记录 request hash、Provider/模型/区域、输入输出 token、延迟、重试/repair 次数和 Provider 可用的费用数据，不记录原始 Prompt 或用户输入。
- `plan_created`、`plan_updated`、`plan_approved` 和 repair 事件：记录同一个 Candidate Snapshot hash 与 derived selection source 计数。
- DeepSearch planning/budget 事件：记录 Candidate Snapshot hash，作为 durable operation identity 的一部分。

事件不得记录完整 Skill 指令、私有资源路径、凭据或被安全过滤 Skill 的明细。

### 8.4 配置

不新增永久环境变量，继续复用：

- `AGENTMESH_SKILL_ORCHESTRATION=off|preview|execute`
- `AGENTMESH_TASK_SCENARIO_ROUTING`
- 现有 LLM、Embedding、Tool 和 DeepSearch 配置

Standard 与 DeepSearch 的分流使用现有 `planning_mode`，不增加第二个全局开关。

Phase 2A 二进制必须把代码级 `standard_universal_execution_contract` 固定为 `null`：若启动配置为 `AGENTMESH_SKILL_ORCHESTRATION=execute`，应用直接以配置错误拒绝启动；即使绕过启动检查，Plan approve/execute 入口和 executor 也必须分别拒绝含 `standard_universal_v1` Universal 节点的 Plan，返回 `universal_execution_not_available`。Phase 2B 在执行合同和全部验收落地后才把该代码常量设为 `v1`。这不是可热切换的环境变量，也不影响 `off` 下 direct explicit；其目的是让 Phase 2A 的 Preview-only 边界不能因部署误配失效。

## 9. 代码改动范围

本方案涉及 15 个以上核心代码/前端/测试文件，以及约 74 个新增 Profile sidecar。它是一次中型架构改造，不是补三条映射的局部修复。

### 9.1 后端核心

| 文件 | 修改内容 |
| --- | --- |
| `agentmesh/models.py` | 保持 12/6 上限；增加 `AgentRun.planning_contract_version`、`RuntimeToolCallClaimV1`、`CandidateSnapshotV1`、server-internal Plan 快照字段、`SkillPlanPublicView`、响应统计、gap 合同及可选 `scenario_assignments` 编辑字段 |
| `agentmesh/agent_run_identity.py` | 将 `planning_contract_version` 纳入 canonical Run creation identity；首次 claim 才选当前代际，重放先读取并复用已有 Run marker，内部不同 marker 不能在同一 `client_turn_id` 下碰撞 |
| `agentmesh/skill_runtime/profiles.py` | 新增 builtin manifest/review trust 判定；Pilot helper 在 Phase 1A/1B 仅供旧 Run 路径，Phase 3 删除 |
| `agentmesh/skill_runtime/service.py` | 为全部内置 Runtime Skill 加载、更新和删除已审 Profile；非 builtin 保持显式策略 |
| `agentmesh/skill_runtime/recommendation.py` | Phase 1A 提供独立、只读的 `UniversalSkillSearchService`，供 Skill Center/Recommendations 使用 |
| `agentmesh/skill_runtime/retrieval.py` | 拆分访问过滤、逐 requirement atom 检索、RRF 合并和 readiness；Scenario 只加权；输出 ready 与 blocked 两组 |
| `agentmesh/embedding.py` | `embed_texts()` 改为单次批量请求并验证响应数量/维度；失败时整批降级 FTS，不做逐 atom 串行远端调用 |
| `agentmesh/tool_runtime/gateway.py`、`agentmesh/agent_runtime/hooks.py` | 按 Tool implementation identity 缓存并去重 health probe，执行 TTL、冷启动 probe 上限与 deadline 合同；所有 Runtime Tool Provider 调用前先在 quiesce permit 内持久化 `RuntimeToolCallClaimV1`，claim 失败不得调用 Provider，permit 不跨外部调用持有；结果/异常只追加 settled/unknown 记录 |
| `agentmesh/skill_runtime/planner.py` | routed 复合任务也走 LLM Planner；只接受模型负责的最小字段；对目标和输入做数据最小化/脱敏，记录无原文的 token/费用遥测；去掉复合任务单 Skill 静默降级 |
| `agentmesh/skill_runtime/plan_validation.py` | 保持 `MAX_CANDIDATES=12`；校验 Candidate Snapshot、来源联合类型、Scenario assignment、coverage、Tool、Knowledge、Resource Manifest、输出与 DAG |
| `agentmesh/skill_runtime/quiesce.py`、`agentmesh/routes/admin_orchestration.py` | 提供基于 thread-safe lock 的单向进程内 `OrchestrationQuiesceController` 与 admin-only 幂等 quiesce 操作；以短期 permit 统一线性化 async/sync forward mutation、节点 `READY → RUNNING` claim 和 recovery schedule admission，不做在线 drain 或终态修复 |
| `agentmesh/skill_runtime/executor.py` | 每个节点的 `READY → RUNNING` CAS 在 quiesce permit 内完成；写节点 claim 后的 timeout、连接异常、task/user/shutdown cancel 统一收口为 `external_outcome_unknown`，late callback 不得覆盖终态 |
| `agentmesh/agent_runtime/service.py`、`agentmesh/app.py` | 接入全量检索、Standard planning skeleton 失败收口、节点启动重验、Knowledge 规则、事件、Plan retry 和错误投影；注入共享 quiesce controller；planned orchestration 同时检查 mode 与 latch，全部 `run/run_sync/resume_sync` 及 Tool claim 都检查 latch；Phase 2A 以代码级 capability 和启动校验硬禁 Universal execute；启动时由 orphan reconciliation 收口所有未解决 Runtime Tool claim，并检查非终态无 Plan Run 的完整 claim 历史，再按各自合同终态化 Standard、direct explicit 与通用中断 Run |
| `agentmesh/routes/agent_runs.py` | Plan 编辑只读取原 Candidate Snapshot 并做 live identity/readiness 重验，不重新检索，不再依赖 Scenario 硬过滤；GET/PATCH/transition/SSE 一律通过同一个 `project_skill_plan_public()` 返回 `SkillPlanPublicView`，不得把持久化 `SkillPlan` 直接作为 response model；Phase 2A approve/execute 硬拒绝 Universal 节点；retry 在创建新 Run 前统一拒绝任何有 Plan 或无 Plan 的 `external_outcome_unknown` 来源 Run |
| `agentmesh/routes/chat.py`、`agentmesh/routes/deepsearch.py`、`agentmesh/routes/inbox.py` | 普通非-runtime chat 与显式 cancel 保持可用；自然语言 orchestration、direct explicit、DeepSearch clarify、Tool approval approve/reject resolution 必须进入中央 quiesce gate，不能因 sync/async 或 `to_thread` 绕过；`off` 仍允许 direct explicit |
| `agentmesh/store.py` | 将 planning contract 纳入不可变 Run creation identity；保持旧 Plan 兼容；原子创建 planning skeleton/Run 关联，并原子提交 draft 或终态失败；以 `call_id` CAS 追加 Tool claim/settlement；修改 cancel/orphan/quiesce 事务，按 planning contract 捕获尚无 Plan 的新代 Run，并检查非终态无 Plan Run 的完整 claim 历史，将不安全重试的父 Run 收口为 `external_outcome_unknown` |
| `scripts/quiesce_skill_orchestration.py` | 离线 dry-run/apply 回滚命令；只在应用停机且独占 SQLite 时按 planning contract 与防御性 Plan shape 枚举并终态化新语义 Run/Plan，包括尚未生成 Plan 的 Run；同时枚举所有 AgentRuntime 未解决 Tool claim 与非终态无 Plan Run 的完整 claim 历史，direct explicit/通用 Run 只收口其调用与父 Run，不误归类为新语义 Plan |
| `agentmesh/task_routing/router.py` | 保留意图、证据与完成标准，不再决定 Runtime 候选集合 |
| `agentmesh/task_routing/contracts.py` 与 Catalog 数据 | 保留 `ScenarioCatalogEntryV1` 字符串 outputs，新增 v2 独立结构化类型和数据；校验 ID 唯一性与兼容映射，不使用宽 union |
| `agentmesh/task_routing/compiler.py`、`scripts/build_task_catalog.py` | 去掉 `user-research-v1` 硬编码，显式接收目标版本和输出目录；版本不一致或对任何已发布目录做非 byte-identical 覆盖时 fail closed |
| `agentmesh/task_routing/catalog.py` | 按 Plan 保存的 `catalog_version/catalog_hash` 解析 v1/v2，不把 legacy Plan 绑定到当前默认 Catalog |
| `agentmesh/task_routing/completion.py` | v2 提供唯一的服务端 coverage 谓词；按 canonical output ID、节点结果血缘、criteria 与 evidence 判定完成；v1 保持 legacy 语义，Synthesis 整体覆盖捷径仅保留在 legacy 分支 |
| `pyproject.toml` | package data 从单列 `task_catalog/user-research-v1/**` 改为包含全部版本化 `task_catalog/**`，保证 wheel 同时携带 v1/v2 |
| `agentmesh/deepsearch/planning.py` | DeepSearch CandidateRetriever 改用全量确定性检索；Candidate Snapshot hash 进入预算 operation key |
| `agentmesh/deepsearch/contracts.py` | 公共 View 暴露派生 selection source 与 Scenario assignment options；同时读取 FrozenPlan v1/v2 |
| `agentmesh/deepsearch/service.py`、`recovery.py`、`finalization.py`、`reporting.py` | Phase 2A 先为 v1 实现 clarify/resume/节点 claim gate、`begin_quiesce()` 与 `off` scan/schedule guard；Phase 3 将所有 FrozenPlan/Snapshot 消费点按 v1/v2 显式分派并把同一门禁扩到 v2，`recover_once()` 在枚举前和每次 schedule 前都检查共享 controller 与当前 mode |
| `agentmesh/artifacts.py` | 保持 FrozenPlan v1 字节级兼容；新增包含 Candidate Snapshot 的 FrozenPlan/Snapshot v2 |
| `agentmesh/routes/health.py` | 从 `app.state` 中实际 coordinator/task 状态投影当前 orchestration mode 与 `deepsearch_recovery_running`，供回滚后只读验证；不得用配置值假造 worker 状态 |
| 受信 ingress 与进程管理配置 | 公共入口拒绝 admin quiesce 路径，只有 loopback/管理网 ACL 可达；不信任请求 Header 判源；提供关闭自动重启、固定 grace=0 force-stop 与 stop-old-before-start-new 能力 |

`agentmesh/task_routing/compiler.py` 和 `skill-registry.json` 不再扩展成 84 项；只移除“映射必须覆盖执行候选”的错误假设。

### 9.2 Profile 与同步脚本

| 文件/目录 | 修改内容 |
| --- | --- |
| `agentmesh/builtin_skills/*/agents/agentmesh.yaml` | 补齐并审查全部 84 个 Profile；现有 10 个冻结执行字段并补审签/检索信息，新增约 74 个 |
| `docs/verification/skill-profile-review-roster.yaml` | 版本化记录 84 项领域 owner、作者、普通/高风险第二审查人、`assigned_at`、`confirmed_at` 与 `review_due_at`；只保存 GitHub 身份和时间，不保存个人联系方式 |
| `scripts/sync_wiki_skills.py` | 提供 create-if-missing draft stub；常规 sync 不覆盖人工 Profile；校验全部 generated/preserved sidecar |
| build staging 中的 `wiki-skill-provenance.json` | 受保护 CI 从精确 PR head/CODEOWNERS 元数据生成，为 84 项记录 Profile hash/version、commit tree、review policy 与 reviewer IDs；仓库副本不作为生产信任根 |
| `scripts/skill_catalog_report.py` | 由“期望 10 个 Planner Profile”改为“当前安装 Skill 100% Profile 覆盖”，并校验 attestation |
| `eval/run_skill_retrieval_eval.py` | 增加 84 个 Skill 的 calibration/冻结 holdout、复合任务 coverage、FTS-only、fake-vector 与真实批量 Provider 评测 |
| `.github/CODEOWNERS` | 为普通和高风险 Profile 路径指定 owner；高风险双审由受保护 CI 对精确 head SHA 的两名不同 CODEOWNER 强制执行 |
| `.github/workflows/ci.yml` 与发布配置 | 以只读 PR metadata 权限校验 CODEOWNERS 审批，生成 manifest 与 GitHub artifact attestation；部署校验 owner/repository、workflow/ref、wheel digest，并写入 verified-build marker |

必须同步修改当前测试中以下旧合同：

- `generated_builtin_count == 74` 可以保留，但 generated Skill 不再等于“无 Profile”。
- 84 个 Skill 的 `activation_policy == explicit_only` 可以保留，它不再决定服务端 Planner 资格。
- `domain_profiles == 10` 改为当前安装且审核通过的 Profile 数。
- `unexpected_nonpilot_profile` 不再是错误。
- `test_catalog_uses_stage_metadata_for_unprofiled_wiki_imports` 改为验证缺失/未审 Profile 只能显式调用。
- Inventory 从“仅 preserved 有 Profile”改为 84 项 sidecar 的 hash/version/review-state 校验。
- 新增 generated Profile 缺失、非法、stale、manifest 篡改、`required_resources` 不可用和非 builtin 不进入 Planner 的测试。

### 9.3 前端

主要复用现有组件：

- `agentmesh-demo/src/components/workspace/SkillPlanPreview.tsx`
- `agentmesh-demo/src/components/workspace/SkillPlanNodeCard.tsx`
- `agentmesh-demo/src/components/workspace/SkillPlanningState.tsx`
- `agentmesh-demo/src/components/workspace/skillPlanPresentation.ts`
- `agentmesh-demo/src/features/deepsearch/DeepSearchWorkspace.tsx`
- `agentmesh-demo/src/features/workspace/types.ts`

调整内容：

- 显示“检索全集 / 可选择候选 / 执行节点”三种数量，不再把 84 和 12 混为一谈。
- 显示 Skill 选择原因和派生来源。
- 将 blocking gap、informational blocked match 与执行节点分区展示。
- 初始 Plan 和编辑新增 Skill 在 Scenario 归属有歧义时都显示选择器，并提交 `scenario_assignments`；未解决前禁用批准。
- 将笼统错误拆为无匹配、Profile 不可用、缺 Tool、缺 Grant、资源不可用、证据路径不支持。
- 继续复用当前计划确认、进度、综合结果和独立 HTML 报告交互，不复制 ai-x 的页面框架。
- 保留当前已迁移的多轮澄清视觉与交互，不因候选池改造新增另一套 DeepSearch 工作台。

### 9.4 ADR 与文档

新增 ADR，替代 ADR 0004 的两项决定：

1. “只允许十个 Wiki Domain Skill 自动规划”。
2. “unbound/unready/unauthorized 一律在排序前过滤”的混合定义。

ADR 同时记录 Candidate Snapshot v1、Task Catalog v1/v2 读取边界、DeepSearch FrozenPlan v2、Scenario canonical output/coverage 合同，以及流量回滚与不支持任意旧二进制降级的边界。

保留 ADR 0004 的持久化 Plan、12 候选、6 节点、深度 4、并发 3、两级审批、节点重验、失败传播、恢复、审计和 `off/preview/execute` 发布策略。

同步更新：

- `README.md`
- `CONTEXT.md`
- `docs/skill-matrix-orchestration-capabilities-and-user-experience.md`
- `docs/plans/2026-08-24-task-scenario-skill-orchestration.md` 的替代关系

## 10. 分阶段实施

每个 Phase 都能独立合并；后续 Phase 永久不实施时，系统仍处于可用状态。

### Phase 0：兼容、发布与回滚可行性 Spike（3~5 个工程日）

在承诺 Phase 2A/2B/3 排期前完成六个最小纵切：

1. 列出 FrozenPlan/Snapshot v1/v2 的全部生产消费点，用现有 v1 fixture 证明新 resolver 不改变 canonical bytes/hash。
2. 在实际 SQLite repository 上原型化 `planning_contract_version` 的首次 claim、同 `client_turn_id` 并发、事务中断、进程崩溃和 JSON 枚举；证明 marker 与 Run 原子落盘、CAS/幂等不碰撞、无 Plan Run 能被回滚查询。扫描无法可靠闭合或性能不可接受时，停止并修订 ADR，改用显式可索引列，不得硬守“无列迁移”。
3. 用 thread-safe 共享 admission gate 和可控 barrier 证明 admin quiesce 与 `recover_once()`、`asyncio.to_thread(resume_sync)`、node/Tool claim 并发时，响应后不会再产生新 claim/schedule，且 `off` 启动不创建恢复调度器。
4. 在预发布部署环境走通受保护 PR/merge queue、reviewed blob、wheel attestation、不可变 release/marker、ingress 管理 ACL、关闭自动重启、force-stop、SQLite 独占 dry-run/apply 和 `off` 健康检查；非 PR、squash/rebase、伪造 Header 与错误 digest 必须 fail closed。
5. 用生产形态 SQLite 和最大 Candidate Snapshot/Tool 事件负载完成 3.3 的 30 分钟并发 soak，记录锁等待、WAL/checkpoint、每 Run p99 增量及 90 天容量；任何门槛不满足时先改存储方案或范围，不把风险推迟到 Phase 2A。
6. 冻结 84 项初始 owner roster，并由列名 reviewer 书面确认 Phase 1B 的审查窗口、单审/双审职责和可用性；确认不了的项在 Phase 0 出口即阻断生产发布排期。单人 Hackathon 可在所有新增 Profile 保持 draft、且不进入公开 recommendation 或 Agent Run Planner 的前提下继续离线 Phase 1A/1B，但不得据此进入 Phase 2A。若业务决定永久移除或替换无法核实的 builtin Skill，必须另立 ADR、先完成目录变更再重新计算验收基线，不能在本发布中临时豁免或部分切流。

Spike 不接生产流量、不写生产新语义记录。产出是接受或修订替代 ADR、冻结 v1/v2 消费点清单、保存 CI/部署演练证据，并根据实际改动面重新估算 Phase 2A/2B/3、确认实现 owner 和退出门槛。单人 Hackathon 在外部发布拓扑或独立审查无法闭合时，只能继续 draft Profile 与离线检索开发；任一纵切无法在单进程 SQLite 前提下闭合时仍须停止实施，不得用放宽兼容、安全或回滚验收条件换取排期。

### Phase 1A：检索、审签与评测骨架（5~8 个工程日）

交付：

- 先提交并接受替代 ADR。
- 在批量起草 74 个 Profile 前，先用现有 10 个 Profile 加至少 12 个来自高相似能力族的 draft Profile 建立每 Skill 至少 5 条正向、近邻负向和复合用例；同时跑 FTS-only 与 fake-vector。若任一能力族 Recall@5 低于 90% 或出现无法通过稳定结构化字段区分的成对 Skill，立即停止全量起草并修订 Profile schema/检索方案。
- 更新 Wiki 同步、受保护发布 attestation、Provenance 和 Catalog Report 契约，并写明 Phase 1A/1B marker 失效时只执行 trust fail-closed、撤下 preview、停止旧进程、删除 marker、重发与复验；Phase 2A 写入新语义 Run 后才启用完整 16.3 runbook。
- 建立 Task Catalog v2 的独立 schema、源数据、构建参数、覆盖保护和 package-data；本 Phase 不切换默认 Catalog，也不改变 legacy Plan。
- 在 `recommendation.py` 建立独立的只读 `UniversalSkillSearchService`，实现 7.3 的 requirement atoms、RRF 合并、readiness 分类和最多 12 个 ready shortlist。
- 明确复用现有 VectorIndex 的生成、缓存、失效和 FTS-only 降级合同，补批量 query embedding 与去重 Tool health probe，不新增第二套向量或 health 服务。
- 扩展评测格式，使黄金用例可以声明多个 `expected_skills`、`required_deliverables` 和 blocked 替代项，并记录 calibration/冻结 holdout 分区与数据集 hash。
- calibration 必须产出首版可复现的 atom 规则、FTS/Vector/RRF 权重、相关性阈值、配额、Tool probe TTL/预算与 tie-break，统一写入 `retrieval_policy_version` 资产；不得把未记录的运行时默认值带入 holdout。
- `/api/skills/recommendations` 使用全量只读检索并展示 readiness/blocked-match；`/routing-preview` 保持只负责 Task/Scenario 诊断。
- Phase 1A 不修改 `SkillCandidateRetriever.recommend*()`；Agent Run、Plan Preview、Standard/DeepSearch Planner 和执行器仍使用旧策略，不改变生产执行行为。

验收：

- draft/approved、普通单审、确定性高风险双审、marker 缺失/release 不一致和 hash 失效均有 CI 测试；预发布环境至少演练一次 trust unavailable 到恢复的 runbook。
- Task Catalog v2 构建不改动 v1 tree/hash，wheel 安装后可同时按 version/hash 加载 v1/v2。
- 多交付物配额、硬 coverage、assignment-aware 贪心覆盖、稳定 tie-break、`coverage_search_exhausted`、FTS-only、fake-vector、批量 Embedding 及 readiness 冷/热路径均有确定性测试。
- Binding 禁用与非 builtin Skill 对模型和客户端零泄漏。
- 回归测试证明 Phase 1A/1B 的 Agent Run 候选集合仍由旧 Pilot/Scenario 策略产生，不能因共享 helper 意外扩大。
- 所有预览接口无执行副作用。

回滚：回滚检索与审签骨架提交即可；不涉及 Plan、Artifact 或数据库迁移。

### Phase 1B：全量 Profile 审查与发布门禁（8~15 个审查人日，另需 2~4 个工程日）

交付：

- 在 Phase 0 已确认的 84 项 owner roster 上记录每项领域 owner、作者、普通审查人、高风险第二审查人、分配时间和 `review_due_at`。普通 Profile 的最终审批 SLA 为分配后 3 个工作日，高风险 Profile 的双审 SLA 为分配后 5 个工作日；作者最后一次 push 会使旧审批失效，并从该次 push 重新计算 SLA。任一项无 owner、无 deadline 或逾期时 Phase 1B 门禁失败，只能重排 owner 与整体排期，不能自动批准或缩小发布范围。
- 补齐约 74 个缺失 sidecar，并按 7.1 审查全部 84 个 Profile；高风险项完成双审。
- 每个 Profile 的 `owner` 必须解析到实际 CODEOWNERS 个人或团队；无主或信息无法核实的项保持 draft，不用默认 `platform` 绕过审查。
- 为每个 Skill 建立至少 3 条正向黄金用例；Phase 1A 标出的易混淆能力族中，每个 Skill 扩为至少 5 条，并增加近邻负向、边界和复合任务用例。
- Profile 作者不能独自批准自己的黄金用例；领域 owner 审查期望结果并在调参前冻结 holdout hash，检索 owner 审查指标实现。
- 分批审查期间保持未批准 Profile 为 draft/`planner_eligible=false`，只允许内部离线评测，不进入模型、普通用户事件或公开 recommendation preview。已审 Profile 可进入只读 recommendation preview；全部门槛通过后一次进入 Phase 2A。

验收：

- 84/84 Profile 通过 schema、Skill/Profile hash、工具、资源和 attestation 校验。
- 冻结 holdout 的 Top-3、Recall@5、复合任务 coverage、安全零泄漏和 p95 全部达到 3.3 门槛。
- FTS-only 与 fake-vector 两套离线评测都通过；仅当发布配置计划启用外部 Vector 时，真实 Embedding Provider smoke 才必须通过，否则以 FTS-only 进入 Phase 2A。
- 最多三轮修订后仍不达标时阻断 Phase 2A，并由两个 owner 重新评估范围或算法。
- 84/84 是本方案的固定切流条件：owner 缺失、审查 SLA 逾期或 Profile 仍为 draft 时一律延期 Phase 2A，不缩小 Searchable 分母、不做部分上线，也不以运行时开关绕过。

回滚：Profile 保持静态资产，回退 `UniversalSkillSearchService` 与 Recommendations 路由改动并部署上一兼容版本；该接口没有独立开关，不能把切换 `AGENTMESH_SKILL_ORCHESTRATION` 当作回滚。生产 Planner 尚未切流。

### Phase 2A：Standard 全量规划 Preview 与回滚基础（6~9 个工程日）

交付：

- Phase 2A 内部按两个不可倒置的发布门实施：先交付 2A-1 安全基础层（Tool claim、quiesce、recovery/off fence、离线命令和 SQLite 压测），仍沿用旧候选且不写 `standard_universal_v1`；预发布故障注入和容量门槛通过后，2A-2 才切换 Universal Preview。两个门可以是连续提交/部署，不增加新的长期运行模式。
- Standard routed 与 unrouted 请求统一使用全量检索和 Plan compiler；自然语言 DIRECT 可确定性生成单节点 Universal Plan，复合任务使用 LLM Planner。本 Phase 只在 `preview` 生成和编辑 Plan，不执行 Universal 节点。
- 将 Phase 1A 的 `UniversalSkillSearchService` 接入 `SkillCandidateRetriever`/Agent Run；此时才改变生产 preview 候选范围。
- 在任何异步规划前随 Run 创建事务冻结 `planning_contract_version`：新 Standard 为 `standard_universal_v1`，现存 DeepSearch 为 `deepsearch_frozen_v1`；在任何 draft 生成前再为新 Standard Plan 原子写入 Candidate Snapshot v1 skeleton，Planner、repair 与编辑共享同一快照。
- 接通 Standard planning skeleton 的失败原子收口；启动时复用现有 orphan reconciliation 终态化中断计划，不重放 Planner。
- 在所有 Runtime Tool 调用前持久化 `RuntimeToolCallClaimV1`；正常返回追加 settled，异常退出、启动 reconciliation 和离线回滚按 side effect 追加 abandoned/unknown，并同步收口有 Plan 或无 Plan 的父 Run。终态化非终态无 Plan Run 时检查其完整 claim 历史，已 settled 的非纯读 claim 也使父 Run 保守进入 `external_outcome_unknown`，不自动 retry 或补偿。
- 实现共享 `OrchestrationQuiesceController` 和 admin-only quiesce 操作；Standard 与现存 DeepSearch v1 的 create、Plan PATCH/approve/reject/execute、clarify、Tool approval approve/reject resolution、retry/replan forward mutation 及每个节点的 `READY → RUNNING` CAS 全部通过同一 admission gate。direct explicit 与 `skill_id=null` 通用 Run 的 start/resume 和每次 Tool call claim 也检查 quiesce latch，但不检查 `off`。
- 将 DeepSearch v1 `RecoveryCoordinator.begin_quiesce()`、`recover_once()` 枚举前/逐 schedule 双重检查及 `off` 启动禁用恢复调度器前移到本 Phase；回滚安全不能等待 FrozenPlan v2 上线。
- 交付 16.3 的离线 quiesce 命令，按 `standard_universal_v1` 覆盖已有 Candidate Snapshot 的 Standard Plan 和尚未生成 Plan 的 Run，并覆盖全部未解决 Runtime Tool claim，以及附属于非终态无 Plan Run 的全部 claim。
- 新增 Task Catalog v2，将 Task/Scenario 从硬过滤器改为排序/完成提示并使用 canonical output/coverage 合同；新 routed Standard Plan 固定 v2，unrouted Plan 固定 `routing_catalog_identity=null`；保留 v1 文件和 hash 供旧 Plan 与 DeepSearch v1 使用。
- 实现 7.5 的节点来源联合类型、服务端 Scenario assignment 与公共 Plan DTO，不新增 `selection_source` 或 Planner `scenario_hint_id` 字段；更新 Standard 计划预览、gap UI 和错误文案。
- 除共享 quiesce/off 安全门外，DeepSearch 继续使用原候选路径、Task Catalog v1 和原冻结合同。

验收：

- 宠物食品核心用例在 preview 中不再空候选，单节点/多节点 Plan 均不能在本 Phase 执行。
- Planner 越权 ID、blocked Skill、伪造可信字段和伪造 Registry metadata 均被拒绝。
- Skill/Profile/card identity 漂移后，编辑返回 `candidate_snapshot_stale`，不会重新解释旧 ID。
- 初始多义 Scenario Plan 保持可编辑且不能批准，完成合法 assignment 后才具备 Phase 2B 的批准条件。
- 有 `routing_result` 的旧 Standard Plan 按保存的 Catalog v1 version/hash 继续读取，新 routed Standard Plan 使用 v2；unrouted Plan 始终走无 Catalog 分支，三者都不读取当前默认版本代替。
- quiesce、Tool claim、DeepSearch v1 recovery、离线 pre-apply/apply/post-check 与 `off` 健康检查通过 11.4/11.5 的竞态和故障注入；`off` 下 direct explicit/通用 Run 保持可用。
- Phase 2A 二进制在 `execute` 配置下拒绝启动；approve/execute API 与 executor 的独立防线都拒绝 `standard_universal_v1` Universal 节点，测试不得只断言 UI 隐藏按钮。

回滚：本 Phase 已写 `standard_universal_v1` preview Run，必须严格按 16.3 关闭自动重启、启用公共停机 fence、调用进程内 quiesce、零 grace 停进程、离线终态化，再以当前前向兼容二进制和 `off` 重启；不部署旧二进制。

### Phase 2B：Standard 执行与完成闭环（4~6 个工程日）

交付：

- 在 Phase 2A 全部验收通过后才允许 `execute` 模式运行 Universal 节点；为新节点冻结 Resource Manifest，旧 Standard Plan 保留 legacy 读取路径。
- 收紧 executor 与 store cancel：`READY → RUNNING`、RUNNING 写节点模糊异常、用户取消、进程关闭、结果封存和后继节点 readiness 全部遵守 7.6、7.8 与 quiesce 合同。
- 接通 Plan 确认、执行前重验、Tool approval、重试、Knowledge、Completion、Synthesis 和最终报告；初始与编辑态 Scenario assignment 共用服务端纯函数。
- 更新执行进度、SSE、partial/failed、重试与报告 UI，不改变 direct explicit 路径。

验收：

- 在至少 5 个工作日、500 次经用户同意且标注为本期可支持的内部真实 Preview 请求上，`coverage_search_exhausted <= 1%`、意外 `unsupported_requirement`/非预期澄清合计 `<= 1%`，且 Planner p95/p99 与终态成功率继续满足 3.3；样本不足或任一门槛未过都延期 Phase 2B。该流量只生成/编辑 Preview，不执行节点，报告按能力族、语言和风险分层且不保存原始敏感 Prompt。
- direct explicit `$skill`、`skill_id=null` 通用 Run、自然语言单节点/多节点、Plan 编辑、批准、拒绝、重试、取消和恢复均不回归；`off` 下无 Plan 路径仍可运行，quiesce 后新的 start/resume/Tool claim 被拒绝。
- Universal 节点能执行并参与 Scenario/Plan completion，不要求 Registry mapping；未解决 assignment、blocking gap、结果血缘或 Evidence 不完整时不得完成。
- 新 Standard Plan 在 Profile/Tool/资源/授权漂移后 fail closed，旧 Plan 不被回写；写结果未知时进入规定的 `PARTIAL`/`FAILED`，不能自动 retry/replan。
- 3.3 的真实 Provider planning 时延/成功率、全量后端/前端/E2E 和 12.1 真机场景全部通过。

回滚：严格按 16.3 执行。普通剩余任务取消，RUNNING 写节点与未解决 Tool claim 按 `external_outcome_unknown` 和 `has_valid_partial_delivery` 进入规定终态；不部署旧二进制。

### Phase 3：DeepSearch 全量检索与最终发布（7~10 个工程日）

交付：

- DeepSearch CandidateRetriever 切换到全量确定性检索。
- 最多 12 个候选形成 Candidate Snapshot v1，其 content hash 进入 planning operation identity。
- 新建、replan 或 retry 的 DeepSearch 在 Run 创建事务先写 `planning_contract_version=deepsearch_frozen_v2`，随后按该值写入 FrozenPlan/Snapshot v2；routed Plan 使用 Task Catalog v2，unrouted Plan 使用 canonical `routing_catalog_identity=null`；v1 Catalog、类型、解析器和 canonical hash 保持不变。
- `service/recovery/finalization/reporting/store/artifacts` 的所有读取、封存和恢复入口按 manifest version 显式分派 v1/v2；把 Phase 2A 已在 v1 验证的 `begin_quiesce()`、`recover_once()` 双重检查与中央 forward-mutation/node-claim gate 扩到 v2 fixture，`off` 时不得枚举、schedule 或 resume 任何 v1/v2 Run。
- 节点执行继续受 DeepSearch Tool 白名单、Resource Manifest 和 Evidence Policy 限制。
- 增加预算记账、重放、进程重启、旧快照恢复和真实 Provider smoke 测试，不放宽现有预算。
- 扩展离线 quiesce 命令，使其按 `deepsearch_frozen_v2` 捕获尚无 Plan 的 Run，并以 FrozenPlan v2 shape 作防御性复核；`deepsearch_frozen_v1` 与缺失 marker 的 legacy v1 记录不被误改。
- 删除只为 10 个 Pilot 服务的剩余执行路径和常量。
- 完成 ADR、README、CONTEXT、运维与验收记录。

验收：

- 同一 Requirement/Problem Graph/`routing_catalog_identity`/Candidate Snapshot hash 重放不重复消耗模型预算。
- 在检索后、Plan 冻结后、节点执行中三处模拟重启均可恢复。
- 旧 `deepsearch-plan-snapshot-v1` hash 校验与恢复不变。
- v2 Plan hash 覆盖完整 Candidate Snapshot 与 `routing_catalog_identity`；routed 的 Task Catalog identity、unrouted/routed 分支或快照 hash 改变都会产生新的 operation key。
- 不满足证据路径的 Skill 先形成 informational blocked-match；只有对应 evidence atom 没有 ready 替代时才形成 blocking gap，且该 Skill 不能进入 DeepSearch 节点。
- Standard 与 DeepSearch 真机用例、HTML 报告下载和来源展示通过。

回滚：严格按 16.3 终态化所有 `planning_contract_version in {standard_universal_v1, deepsearch_frozen_v2}` 的非终态 Run/Plan，包括尚无 Candidate Snapshot/Plan 的 Run；`candidate_snapshot != null` 或 FrozenPlan v2 shape 仅作防御性补漏。随后以当前二进制和 `off` 重启。当前二进制继续提供 Task Catalog v1/v2 与 FrozenPlan v1/v2 读取；v1/v2 终态 Artifact 都保留，不做降级写回或二进制降级。

### 后续独立项目：27 个 Tool-limited Skill 适配（3~6 周）

按工具族拆分独立交付：

- Zero Design MCP；
- JoySpace/O2；
- 文件读写与 Artifact；
- Git/Bash 受控操作；
- 其他业务系统 API。

每个工具族单独处理授权、审计、降级和验收，不阻塞全量 Skill 的发现与规划能力上线。

## 11. 测试计划

### 11.1 Profile 与目录

- 84/84 Skill 均有合法、当前的 Profile。
- Profile 缺失、过期、字段非法、未知 Tool 或资源越界时 fail closed。
- Profile 原文/canonical JSON、各列表数量、单项长度及 4 KiB capability-card 边界逐一做等于上限与超过上限测试；超限一律 `profile_invalid`，不得静默截断后改变 hash。
- 自审、审批人数不足、owner 无法解析到 CODEOWNERS、非 CODEOWNER、head SHA/blob hash 不匹配、手工伪造 provenance、错误 owner/repository/workflow/ref、wheel digest 不匹配、缺少 verified-build marker 或 marker 与当前 release 不一致时都不能获得 Planner 资格，并产生 `skill_profile_trust_unavailable` 聚合健康告警。
- generated 与 preserved Skill 都进入同一 Profile 校验。
- SQLite 旧 worktree 重复记录不把 84 错报成 168；候选只来自 `SkillCatalogService.list_for_agent()` 当前发现结果。
- 新增 Profile 不改变 Skill 的 `explicit_only` 激活策略。
- Scenario output ID 重复、非法 ID、label 被当作 ID 或空 `compatible_output_kinds` 均 fail closed；当前没有 Profile 提供的合法 kind 可加载，但 Catalog Report 必须报告。
- Task Catalog v1 文件和 hash 保持不变，v2 使用结构化 output；有 `routing_result` 的 Plan 只能解析保存的 version/hash，缺失版本不能回退到当前默认 Catalog，unrouted Plan 则保持 N/A 且不强造 Catalog 引用。
- v1 字符串 outputs 和 v2 结构化 outputs 由版本分派的不同模型解析；交叉输入和把 v2 completion 用于 v1 Plan 都会失败。
- Phase 2A/2B 并发创建 Standard 与 DeepSearch Run 时分别固定 Catalog v2/v1；带 `planning_mode` 的 routing preview 与实际 Run 返回相同 version/hash，Phase 3 DeepSearch 再切到 v2。
- 以 7.10 的单一兼容矩阵做表驱动测试，显式加入 Phase 1A/1B/2A/2B/3 与 routed/unrouted 维度，覆盖每类 Plan 的读取、编辑、批准、执行、恢复、retry/replan 和全局 `off` 行为，不为未列出的版本组合添加隐式 fallback。
- Catalog 构建命令必须显式给出目标版本；版本与目录不一致、对已发布 v1/v2 做非 byte-identical 重建时均失败，失败后旧 version/hash 仍可解析。
- 本期 wheel 始终包含 Catalog v1/v2，不提供清理入口或自动删除路径。
- 构建并安装 wheel 后，`importlib.resources` 能按精确 version/hash 同时加载 Task Catalog v1/v2，避免仅在源码树通过。

### 11.2 安全与检索

- Binding 开启且 Profile 已审、有效的 84 个基线 builtin Skill 全部参与检索。
- 禁用 Binding、Workspace/Project/Learned Skill 对自然语言 Planner 和 API 自动候选零泄漏。
- Candidate Snapshot 的 Planner/API/UI/SSE public projection 序列化测试证明 `EvidencePathWitnessV1`、Tool implementation、Resource/Adapter identity/hash 和私有路径零泄漏；服务端存储仍保留完整 hash-covered snapshot。
- Standard Plan GET、PATCH、approve/reject/cancel/execute 响应和 SSE 全部断言响应类型为 `SkillPlanPublicView`；禁止把持久化 `SkillPlan` 直接交给 response model，防止新增 internal 字段默认外泄。
- 越域冻结用例全部返回 `no_matching_skill`；达到相关性门槛但全部不可执行时返回 `no_executable_skill`，两者都不调用 Planner。
- `tool_grant_missing` 等可公开 readiness diagnostic 不进入 selectable shortlist。
- 有 ready 替代项完整覆盖时，blocked match 只进 diagnostics，`plan.capability_gaps` 为空且允许 completed。
- 必需输出没有 ready 覆盖时写入 blocking gap，并强制 partial/failed。
- Task/Scenario 只增加排序分，不删除非映射候选。
- 每个 Skill 至少 3 条互不改写复用的正向查询，分别覆盖直接表述、自然语言改写和相邻能力边界；易混淆能力族中的每个 Skill 至少 5 条，并另加近邻负向查询。
- 所有本期可支持的正向/复合 holdout 都生成非空、版本化的服务端义务；同义词或语言映射变化会升级 `retrieval_policy_version`，未知 kind 不能由 LLM 补造。多义输入返回澄清，明确不可映射输入返回 `unsupported_requirement`。
- 覆盖中文口语、中英文混合、简称、多交付物和否定表达。
- 多交付物逐 atom 召回、RRF、去重、稳定 tie-break、blocked 替代、12 槽截断和顺序置换结果确定。
- 模糊 `query_atoms` 命中不能形成 hard coverage；负向示例不写入正向 FTS/Vector 投影，只用于扣分和边界判定。
- canonical coverage atom 按 7.3 的固定顺序编码并去重；required/plannable 两组 atom、最多 6 个 `coverage_witness_skill_ids` 与每个 candidate 的单一 variant witness 一起进入 Candidate Snapshot hash，repair 和恢复只读冻结值；witness 并集必须覆盖全部 plannable atom，`covered_requirement_ids` 也按全局顺序唯一保存且不合并不同 Scenario variant。
- 24 个去重 coverage atom 被接受；第 25 个返回 `requirement_budget_exceeded`，发生在 snapshot/skeleton 创建前，Run 为 `FAILED + plan_id=null`，不得截断。
- LLM 自由文本不能创建 hard coverage atom；确定性 deliverable、固定 Catalog output 和 Evidence Policy 之外的要求返回澄清或 `unsupported_requirement`。
- 复合用例中，一个 Skill 只覆盖业务 deliverable、另一个 Skill 通过已接受且 ready 的 Tool/Resource 路径覆盖 `evidence:trusted_external_path` 时，两者都必须入围；仅有前者不能伪装成证据 coverage，实际证据仍由执行后 Evidence Policy 验证。
- 同一 Skill 同时匹配两个 Scenario 时，assignment-aware cover 只把它的 witness 计入一个 Scenario，并保留能覆盖另一 Scenario 的合法候选。
- 不同 Scenario 的同名 output 使用带 Scenario ID 的 canonical requirement key，不发生 coverage 或 gap 碰撞。
- 贪心因无合法未选 variant 而提前停止，或选满 6 个 coverage witness candidate 后仍未覆盖全部 plannable atom 时，都返回 `coverage_search_exhausted` 和未覆盖 ID，不把最多 12 个 shortlist 槽位误当成可执行节点预算，也不声称已证明不可行。
- coverage tie-break 覆盖同分、同 Skill 多 variant 及 `scenario_id=null`；`null` 必须稳定排在字符串 ID 前，重复运行产生相同 witness 和 snapshot hash。
- 冻结复合用例显式保存一组 6 节点内的 assignment-aware ready coverage witness；该 witness 存在时生产贪心策略返回 `coverage_search_exhausted` 即使发布失败。
- FTS-only 与 fake-vector 分别记录 Top-1、Top-3、Recall@5、复合任务 coverage、越域误推荐率和 p95；真实 Provider 每请求最多一次批量 embedding 调用并满足 3.3 的成功率/p95，单独记录调用次数、模型、延迟、降级和 Provider 用量；model/dimension 变化触发重建，Provider timeout、数量或维度异常保持 FTS 降级。
- 外部 Embedding 只接收经 `redact_sensitive_text()` 处理的有界 query atom，凭据、联系方式、本地路径、私有记忆、附件/文档正文和 Tool 输出均不出现在 Provider 请求或事件日志中；未批准 Provider 配置时强制 FTS-only。
- Tool health 按 implementation identity 去重，空/热缓存、覆盖优先级、TTL、8-probe 上限、并发、单项/整批超时和异常均有测试；超时使用 `tool_health_timeout`，明确不健康使用 `required_tool_unhealthy`。尾部候选超出 probe 上限但必需 atom 已有 ready 覆盖且至少有一个 ready candidate 时请求继续；未覆盖必需 atom 或首个 ready candidate 仍依赖未探测 implementation 时返回 `readiness_probe_budget_exceeded`，不把未检查候选降为 blocked。另覆盖 `required_coverage_atoms=[]`、`required_synthesis_output_ids` 非空且冷缓存待探测 implementation 超过 8 的纯 Synthesis 用例；两组义务同时为空时必须在检索前澄清或返回 `unsupported_requirement`。

### 11.3 Planner 与验证

- routed 复合任务实际调用 LLM Planner，不再调用确定性 `route_skill_draft()`。
- LLM 返回未知 ID、blocked ID、错误 output，或提交 version/hash、Tool、Resource、side effect、Knowledge Binding、completion metadata、capability gaps 等服务端字段时被 schema 拒绝。
- `scenario_mapping`、`universal_retrieval` 和 `legacy_unmapped` 按联合类型正确派生；direct explicit Run 不创建 Plan，DeepSearch 继续拒绝 explicit。
- 自然语言 DIRECT 只有在单个 ready candidate 独立覆盖全部非空 plannable atom、输入可从用户请求直接绑定且 assignment 无歧义时才走确定性单节点；否则必须调用 LLM Planner，不能按 `intent.complexity` 固定取首候选。
- Planner schema 拒绝 `scenario_hint_id`、`task_id` 与 `scenario_id`；归属只由服务端按 canonical output ID 与受审 output-kind 映射计算，中文 label 改动不改变归属或完成结果。
- 同一静态 Profile 在不同请求中产生相同 `capability_card_hash`；请求级 `match_reason_codes` 可不同并改变 Candidate Snapshot hash，但不被误判为 Profile/card 漂移。
- 唯一匹配自动补全；初始和编辑态多义匹配都形成可编辑的 `scenario_assignment_required`。存在至少一组合法 assignment 能覆盖全部 plannable atom 时，初始 draft 进入 `WAITING_APPROVAL`；不存在合法组合时进入一次 repair，仍失败则返回 `planner_coverage_unresolved`。
- Node Result 声明不兼容或未授权 output ID 时被拒绝，仅同名文案不能形成 coverage。
- canonicalizer 派生的 `required_synthesis_output_ids` 进入 snapshot hash；即使 LLM draft 或编辑请求省略它们，服务端最终 `synthesis_output_contract` 仍完整保留。缺少任一已冻结必需 Synthesis output 时不得 `COMPLETED`。
- `required_coverage_atoms` 与 `required_synthesis_output_ids` 同时为空时不创建 Candidate Snapshot；Planner 或客户端追加的可选 output 不能反向制造服务端义务，也不能单独让 `has_valid_partial_delivery` 成立。
- 对 deliverable、Scenario output、evidence 三类 atom 做表驱动测试：Plan gap 只认 `can_plan_cover_atom`，结果/完成/部分成功只认 `is_result_cover_atom`；错误血缘、空 deliverable、未封存 Artifact 或未通过 Evidence Policy 均不形成 result coverage。节点 `output_contract=[A,B]` 但 `delivered_output_kinds=[A]` 时，B 不得被判已交付。
- 没有节点 coverage 时，Synthesis 的 presentation output 或 claim 不能使新合同下的 Scenario completed；legacy Plan 行为不变。
- Universal 节点携带 `skill_registry_id`、私自 Knowledge Binding 或伪造完成标准时被拒绝。
- 同一 Plan 重复 `skill_id` 以 `duplicate_skill` 拒绝；0 节点 draft 进入一次 repair，耗尽后返回 `planner_coverage_unresolved`，不运行空 Synthesis。
- 单 Skill、串行 DAG、并行 DAG、深度超限、循环依赖和 required/optional 失败传播。
- Planner 首次调用与 repair 的 Candidate Snapshot hash 相同；一次语义修复成功或两次失败后的行为确定。
- 12 候选最坏合法能力卡的公开投影、完整 64 KiB request 和 24,000-token 上限有边界测试；任一超限在 LLM 前返回 `planner_context_budget_exceeded`，保留失败 skeleton/snapshot 且不删 coverage witness。
- 捕获发往 fake Planner Provider 的完整 request，断言凭据、联系方式、本地路径、私有记忆正文、附件/文档正文、原始 Tool 输出、Evidence 私有路径和被过滤 Skill 均为 0；事件只含 hash、模型/区域、token、时延、重试/repair 和费用元数据，不含原始 Prompt。
- 瞬时 Provider 错误使用独立重试策略，不消耗 repair；确定性 4xx 不重试。

### 11.4 Plan 生命周期

- 所有 7.3 列出的检索阶段终止码都在 snapshot/skeleton 前把 Run 置为 `FAILED + plan_id=null`，数据库中没有空 Plan；Planner 阶段失败则保留已冻结 snapshot 的失败 skeleton 供审计。
- Phase 2A 以 `execute` 配置启动必须失败；在测试中绕过启动检查后，approve/execute API 和 executor 仍分别以 `universal_execution_not_available` 拒绝 `standard_universal_v1` Universal 节点且 node runner 调用数为 0。Phase 2B capability=`v1` 后同一 fixture 才可进入正常批准/执行合同。
- 表驱动覆盖四种 `planning_contract_version` 与 legacy 缺失值：新 Plan-producing Run 在首个异步步骤前已持久化正确 marker，重复创建只能命中相同 creation identity；跨 Phase 重放同一 `client_turn_id` 时先读取并复用已有 marker，不能产生新 Run，内部强行替换为不同 marker 时必须冲突。resolver 不读取当前发布 Phase。marker 与 Candidate Snapshot、Catalog 或 FrozenPlan schema 不匹配时 fail closed，direct explicit 保持 `null`。
- 在 Run 创建后、Candidate Snapshot/Plan 生成前模拟崩溃：`standard_universal_v1` 被离线回滚识别并终态化；Phase 2A/2B 的 `deepsearch_frozen_v1` 即使跨过 Phase 3 发布仍只恢复为 v1；Phase 3 的 `deepsearch_frozen_v2` 即使尚无 FrozenPlan 也被回滚预检和 apply 捕获。缺失 marker 的 legacy DeepSearch fixture 继续解释为 v1，不按当前 Phase 升级。
- 新 Plan 的 `candidate_skill_ids` 与 Candidate Snapshot 顺序、唯一性或 hash 不一致时拒绝；旧空 snapshot fixture 仍按 legacy 合同读取。
- 有 `routing_result` 的 legacy Standard Plan 按保存的 Catalog v1 version/hash 完成校验；Catalog 默认版本切到 v2 不改变结果，精确 v1 资产缺失时返回 `task_catalog_snapshot_unavailable`。unrouted legacy Plan 不读取 Catalog，保持原合同。
- legacy Standard Plan 编辑沿用现有 live 候选重验且不能加入 Universal 节点；Phase 2A 起显式 replan 才创建 Catalog v2 + Candidate Snapshot 新 Plan，Phase 2A 前保持旧合同。
- LLM 或确定性 draft 生成前已原子持久化 `PLANNING` skeleton、Candidate Snapshot 和 Run 关联；Standard 调用异常时 Plan/Run 原子失败。模拟进程崩溃后，`PLANNING` skeleton 的 Plan/Run 明确进入 `FAILED + process_restarted`；执行中的 RUNNING READ/DRAFT 节点进入 `FAILED + process_restarted`，RUNNING 写节点进入 `FAILED + external_outcome_unknown`，未启动节点进入 `CANCELLED`。分别覆盖纯 READ/DRAFT 与“RUNNING 写 + 并行 RUNNING READ/DRAFT”的混合 DAG，断言所有节点先终态化，Plan/Run 再按 7.6 的 `has_valid_partial_delivery` 同步进入 `PARTIAL` 或 `FAILED`，且均不自动重放。
- Provider/repair 耗尽、规划阶段的 Run deadline 到期或快照损坏时，Plan 与 Run 原子进入 `FAILED`；执行或回滚阶段的外部结果未知服从 `external_outcome_unknown` 的 `PARTIAL`/`FAILED` 分支。全局模式为 `off` 时，Standard planning skeleton 不会重放，DeepSearch v1/v2 recoverable Run 都不会被枚举、schedule 或恢复。
- 编辑只能从 Candidate Snapshot 中选择，不重新检索或替换 shortlist。
- 初始规划或新增节点出现多义归属时，`SkillPlan.status=WAITING_APPROVAL` 且 `AgentRun.status=WAITING_PLAN_APPROVAL`，并返回允许选项；批准被拒绝；提交合法 assignment 后 `scenario_assignment_required` 消失并严格重算其他 blocking gap、版本递增，归属全部解决后才可批准。
- 有 ready 节点但仍有 blocking gap 时，Plan 可预览和人工批准，UI 显著展示未覆盖项；执行后按 7.6 的 `has_valid_partial_delivery` 只能进入 `PARTIAL` 或 `FAILED`，不得 `COMPLETED`。
- `has_valid_partial_delivery` 的正例必须有覆盖 frozen atom 的已验证非空节点结果，或已经从至少一个已验证节点结果生成并封存的请求内固定 Synthesis output；只有 diagnostic、日志、空/越界 claim 或未封存内容的反例必须为假，Plan 与 Run 终态一致。
- Skill、Profile 或能力卡投影漂移后，编辑和批准返回 `candidate_snapshot_stale`；仅默认 retrieval policy 升级不得使旧 Plan 失效，动态 Tool/Grant 变化按 readiness 失败。
- 默认 retrieval policy 从 vN 升到 vN+1 后，旧 Plan 的编辑、批准和 DeepSearch 同 Run 恢复继续使用冻结 snapshot；当前 Evidence Policy id/version/hash 任一变化时以 `evidence_policy_changed` fail closed 并要求 replan，新增或撤销路径都不得静默改写旧 snapshot coverage。
- 权限在批准后撤销，节点启动时失败。
- Tool/资源/Profile 在批准后漂移，节点启动时失败。
- Retry 使用全量策略并生成新 Candidate Snapshot，只复用合法 READ/DRAFT 结果；来源 Run 自身或节点含 `external_outcome_unknown` 时拒绝自动 retry/replan，不能通过新快照重复未知写入。另对有 Plan Standard、DeepSearch、direct explicit 和 `skill_id=null` 无 Plan Run 逐一调用现有 retry API，断言均在新 Run/Runtime 创建前返回 `409 + external_outcome_unknown`；防御性 claim-history 检查命中时行为相同。
- RUNNING 写节点分别模拟 timeout、连接中断、用户 cancel、executor `CancelledError`、进程关闭和 late callback；没有 Tool 专用确认结果时节点始终为 `FAILED + external_outcome_unknown`。存活进程收口时其余所有非终态节点（包括并行 RUNNING READ/DRAFT）进入 `CANCELLED`；崩溃恢复则服从上一条。Plan/Run 按统一 partial 谓词终态化且 retry/replan 被拒绝。
- Standard 跨 Run 复用满足完整性谓词；Tool/事实性节点不复用；DeepSearch 只允许同 Run checkpoint resume。
- SSE 重连、刷新、重复确认和重复 resume 不创建第二次执行。
- 回滚排空后所有新语义 Run/Plan 都必须终态化：未开始或普通剩余任务进入 `CANCELLED`；结果不明的 RUNNING 写节点进入 `FAILED + external_outcome_unknown`，其余所有非终态节点（含并行 RUNNING READ/DRAFT 与未启动节点）进入 `CANCELLED`，Plan/Run 按 7.6 的 `has_valid_partial_delivery` 进入 `PARTIAL` 或 `FAILED`。late callback 只能补充审计记录，不能覆盖上述终态。
- 持久化 `call_id` 只提供本地调用身份和追踪，不等于外部 Provider 保证幂等；只有 Provider 明确支持且已接收同一幂等键、并由 Tool 专用对账确认原调用状态时，才可按其合同安全处理。对账测试必须证明只追加关联 `call_id` 的不可变记录，不覆盖 Node/Plan/Run 终态或 Artifact/hash；结果未知时自动 retry/replan 默认拒绝，也不声称已回滚。
- 未认证或非 admin 的管理请求由应用拒绝；公共入口即使持有 admin 凭据也由 ingress ACL 拒绝，伪造 `Host`/`X-Forwarded-*` 不得绕过，只有受控 loopback/管理路径上的 admin 请求可成功。合法调用幂等，controller 只能从 `open` 单向进入 `quiescing`。用 barrier 而非 sleep 控制 create、PATCH/approve/reject/execute、DeepSearch clarify、Tool approval approve/reject resolution、retry/replan、自然语言 orchestration、direct explicit/`skill_id=null` start/resume/Tool claim 及 executor node claim 与 quiesce 的并发次序；覆盖请求已进入 handler 或 `to_thread` 但尚未取得 permit 的情况，证明 quiesce 响应后没有新 forward mutation、`READY → RUNNING` CAS 或 Tool call claim。对称覆盖 forward transaction/queue action 已持有 permit 但尚未结束的情况：`active_permits` 非零时 quiesce 不得返回，permit 释放后该短动作可完成且 quiesce 才完成；同一 workflow 的下一次 CAS/Tool claim/入队重新取 permit 并被拒绝。两个并发 quiesce 请求必须等待同一个 completion future 并返回同一终态。已 claim 工作的结果/终态写入、读取、完全非-runtime chat、显式取消和 fail-closed orphan 收口仍服从既有合同。
- 公共入口 mutation fence 生效后，通过 loopback/管理路径调用 quiesce；`begin_quiesce()` 返回后并发 create、PATCH/approve/reject/execute、clarify、Tool approval approve/reject resolution、retry/replan 和自然语言 orchestration 全部被拒绝，Recovery Coordinator 也不能再接受新 scan/schedule，executor 不能 claim 新节点。已 claim 节点可写结果但不由 quiesce 等待，且不能 claim 后继节点；关闭自动重启并以固定 grace=0 force-stop。离线命令的 dry-run 不写库，不能取得 SQLite 独占写锁时 apply 拒绝；停机后 apply 按上述节点与 Plan/Run 规则原子终态化，重复 apply 幂等。以同一二进制和 `off` 重启后不得创建、PATCH、批准、拒绝、执行、clarify、Tool approval resolution、retry/replan、claim 节点或恢复 v1/v2 Plan，preflight 结果必须为 0。
- `off` 启动集成测试从真实 `app.state` 断言 Recovery Coordinator 周期 task 未创建，并验证受保护 `GET /api/health/providers` 同时返回 `skill_orchestration_mode=off`、`deepsearch_recovery_running=false`；不得只 mock health 响应或配置读取器。
- 生产形态 SQLite soak 同时压入最大 Candidate Snapshot、Tool claim/settlement、3 个执行节点与 10 个 Preview/SSE 读连接，断言 30 分钟内无 lock error/事件丢失/event-loop 阻塞，并核对 3.3 的锁等待、WAL/checkpoint、每 Run 增量与磁盘容量门槛。

### 11.5 DeepSearch

- 全量检索不新增生成式 LLM 调用；单次批量 Embedding 不计入 `llm_calls/tokens`，但必须按 7.10 单独记录遥测。
- FrozenPlan v2 的 Candidate Snapshot 或 `routing_catalog_identity` 改变时产生新的 planning operation key；各输入 hash 完全相同时重放复用预算记录。表驱动覆盖 routed `{catalog_version,catalog_hash}` 与 unrouted canonical `null`，证明 unrouted 不解析或伪造 Catalog。FrozenPlan v1 的 operation key 与 hash 保持原值，不访问 Candidate Snapshot；routed v1 仍按保存的 Catalog identity，unrouted v1 仍保持原 N/A 合同。
- v1/v2 均覆盖 routed/unrouted hash fixture：routed 使用保存的 Catalog identity，unrouted 使用 canonical `null`；两者 operation key 不碰撞，也不把默认 Catalog 注入 unrouted Plan。
- FrozenPlan v1/v2 都拒绝超过 12 个候选和 6 个节点。
- 新 Universal 节点冻结、hash、读取和恢复一致。
- 旧 v1 Artifact 的 canonical hash 不变；routed v1 按保存的 Task Catalog v1 version/hash 恢复，unrouted v1 保持原来的无 Catalog 分支。
- FrozenPlan v1 编辑保持 v1 legacy 合同且不能加入 Universal 节点；Phase 3 前 replan/retry 仍创建 v1，Phase 3 起显式 replan/retry 才创建 Catalog v2 + FrozenPlan v2。
- v2 Artifact hash 覆盖 Candidate Snapshot；v1 不原位升级，当前解析器可读 v1/v2，全局 `off` 时两者都不得 resume/retry。
- FrozenPlan v2 与 SkillPlan 内嵌 Candidate Snapshot、各自 hash、`candidate_skill_ids` 或顺序任一不一致时，构建、读取和恢复都拒绝。
- 对 executor claim 做 pre-claim/post-claim 对称 barrier：quiesce 先线性化时 `READY → RUNNING` CAS 被拒绝且 node runner 调用数为 0；claim 先成功时允许该节点写结果/终态，并允许后继节点作 `PENDING → READY` 记账，但其所有后继 `READY → RUNNING` claim 均被拒绝，不能调用后继 node runner。
- 对 direct explicit 与 `skill_id=null` 通用 Run 的 Tool dispatch 做同样的 pre-claim/post-claim barrier：quiesce 先线性化时不创建 call claim 且 Provider 调用数为 0；call claim 先提交时允许原调用按既有合同写结果，但后续 Tool claim 被拒绝。对非纯读 Tool 分别在“Provider 已接受写入、settled 记录提交前”和“`tool_call_settled` 已提交、无 Plan 父 Run 仍非终态”两个切点杀死进程；前者证明启动 reconciliation 与离线 apply 都追加 `tool_call_outcome_unknown`，后者证明二者读取父 Run 的完整 claim 历史。两种情况都必须把父 Run 置为 `FAILED + external_outcome_unknown`；随后调用 retry API 必须返回同码且 AgentRuntime/Provider 调用数均为 0。另做 `off` 启动用例，证明 direct explicit/通用 Run 仍可用且 planned orchestration 被拒绝。
- Phase 2A 先用 v1 fixture、Phase 3 再增加 v2 fixture，以可控 barrier 覆盖 recovery scan 与 quiesce 的竞态：在枚举前 quiesce 时 `list_recoverable_deepsearch_runs()` repository spy 调用数为 0；在枚举后 quiesce 时不得 schedule 任一已枚举行；quiesce 响应后再次 `recover_once()` 仍须 no-op。以 `off` 启动时不创建周期任务，直接调用 `recover_once()` 对 v1/v2 fixture 都必须满足 list/schedule/resume 调用数均为 0。
- Tool 白名单、Evidence Manifest、Coverage、Review 和 HTML Report 不回归。
- 不支持证据链或资源冻结的 Skill fail closed。

### 11.6 前端与 E2E

- UI 正确区分 Searchable、Selectable、Plan Nodes 和 Blocked。
- blocking gap 与 informational blocked match 含义明确，不显示误导性的“未授权”，也不泄露敏感对象。
- 初始和编辑态 Scenario 多义归属都显示允许选项，未解决时批准按钮禁用并保留编辑入口。
- Plan 确认、拒绝、取消、刷新和重试保持幂等。
- 最终报告在对话中可读，可打开并下载独立 HTML。
- Standard 与 DeepSearch 模式严格隔离，切换模式不会复用错误策略。

### 11.7 验证命令

```bash
.venv/bin/python scripts/sync_wiki_skills.py --check
.venv/bin/python scripts/skill_catalog_report.py agentmesh/builtin_skills
.venv/bin/python eval/run_skill_retrieval_eval.py
.venv/bin/python eval/run_universal_skill_retrieval_eval.py
.venv/bin/python -m pytest
.venv/bin/ruff check agentmesh tests scripts eval
npm --prefix agentmesh-demo test -- --run
npm --prefix agentmesh-demo run api:types
npm --prefix agentmesh-demo run build
npm --prefix agentmesh-demo run test:e2e
```

## 12. 真机验收场景

至少执行：

1. `宠物食品心智设计表达策略研究`
2. `分析宠物食品竞品，并结合用户洞察制定表达策略`
3. `为企业设计团队制定用户研究计划、访谈提纲、问卷和可用性测试方案`
4. `根据现有访谈材料提炼用户洞察并生成旅程图`
5. `$competitive-analysis ...`
6. 一个需要 Zero/JoySpace 的 tool-limited 请求
7. 一个与任何 Skill 都无关的越域请求
8. 一个包含外部写入要求的高风险请求
9. 一个 Workspace/Project Package 中存在同名 Skill、但未获自动编排信任的请求
10. 一个执行期间撤销 Tool Grant 的请求
11. 一个节点同时兼容两个 Scenario、需要用户选择归属的请求
12. 一个 Plan 预览后 Profile 或能力卡发生变化的请求
13. 一个 Embedding 超时但 FTS 仍可召回的请求
14. 一个同时包含 FrozenPlan v2 非终态 Run 与 `deepsearch_frozen_v2` 无 Plan Run 的回滚预检

每次验收必须检查：

- Installed、security filtered、Searchable、Ready、Shortlist、Node 数量；
- LLM 实际收到的 Candidate Snapshot hash、能力卡 identity 与选中的 candidate ID；
- 派生 selection source 与 DAG 依赖；
- Scenario canonical output、assignment options、coverage 与 blocking gap；
- Tool 调用、授权、审批和节点启动重验；
- Node Result、Source、Artifact 与 evidence lineage；
- 最终报告是否仅使用已验证节点结果；
- partial/failed 是否没有伪装成完成；
- 刷新、重试和进程恢复是否复用正确 Run。

## 13. 风险与控制

| 风险 | 控制 |
| --- | --- |
| 84 个 Skill 增加误召回 | 分交付物检索、Profile Vector/FTS/RRF、正反例、黄金集 |
| 相关 Skill 被候选/节点上限截断 | 逐 requirement atom 召回、必需 atom 优先、稳定 RRF/去重；先冻结最多 6 节点的 coverage witness，再补满 12 候选；贪心未覆盖时返回 `coverage_search_exhausted` 并由 holdout 监测保守误拒 |
| 模型上下文膨胀 | 只发送最多 12 张安全能力卡，不发送 84 份指令 |
| Planner 泄露私有上下文 | 与 Embedding 共用数据最小化、脱敏和受审 Provider 政策；不发送附件/记忆正文、Tool 输出或私有路径，日志只存 hash/用量 |
| Skill 指令提示注入 | Planner 不读取指令；节点执行时仍受平台政策和 Tool allowlist |
| Profile 自动生成或伪造审签 | 84/84 人工审查、受保护分支、CODEOWNERS、发布 attestation、Profile hash 和高风险双审 |
| CODEOWNER 审查容量不足或逾期 | 冻结 owner roster、逐项 `review_due_at` 和单审/双审 SLA；任一缺失或逾期都整体延期 Phase 2A，不部分上线 |
| Tool-limited Skill 被假执行 | readiness 与相关性分离；blocked 不进入 candidate snapshot |
| 非 builtin 或 Binding 禁用 Skill 进入 Planner | source scope、manifest attestation 与 Binding 在任何模型调用前过滤 |
| 写入 Skill 被自动执行 | 用户请求检查 + Plan Approval + Tool Approval + 节点重验 |
| Phase 2A 因 `execute` 误配提前运行 Universal 节点 | 代码级 execution contract、启动拒绝、approve/execute 与 executor 三层 fail closed；Phase 2B 才启用 v1 |
| Candidate ID 在编辑时被解释成新 Profile | 冻结 Skill/Profile/card identity；静态漂移要求 replan，不从 live 检索静默替换 |
| Scenario 解耦后归属或完成检查失真 | canonical output ID、展示 label、受审 output-kind 映射和服务端统一 coverage 谓词；多义归属未解决前禁止批准和执行 |
| DeepSearch 预算重复消耗 | 第一版确定性检索；Task Catalog 与 Candidate Snapshot hash 都进入持久化 operation identity |
| 旧 Plan/FrozenPlan 被 Catalog v2 破坏 | Task Catalog v1 文件/hash 保留并按 Plan 保存的 version/hash 解析；新语义使用 Catalog v2 与 FrozenPlan v2，不原位升级 |
| Plan 生成前崩溃导致跨 Phase 错选合同或回滚漏检 | Run 创建事务冻结 `planning_contract_version`；resolver、恢复与离线回滚只读 marker，Plan/FrozenPlan shape 仅作一致性校验和防御性补漏 |
| 无 Plan 写调用已 settled、父 Run 完成前崩溃导致重复副作用 | 启动 reconciliation 与离线回滚检查非终态父 Run 的完整 claim 历史；任一非纯读 claim 都使父 Run 进入 `external_outcome_unknown`，后台与用户 retry 入口均拒绝 |
| SQLite 新事件与快照造成锁竞争或磁盘耗尽 | Phase 0 生产形态并发 soak、锁等待/WAL/checkpoint 门槛、90 天容量与 2 倍磁盘余量；失败则不进入 Phase 2A |
| 旧二进制会忽略或误读新语义记录 | 主回滚路径按 16.3 停流并离线终态化，再以当前前向兼容二进制和全局 `off` 重启；写入新记录后禁止旧二进制降级 |
| Provider 不稳定 | 瞬时故障走有界 Provider 重试，结构/语义错误只 repair 一次；两者都不得生成自由回答 |

最脆弱的假设是：84 个 Skill 的公开描述、正反例和输入输出足以区分相邻能力。黄金评测未达到 3.3 门槛时，Phase 2A 保持阻断；前三轮只补强 Profile 语义和确定性检索信号，仍失败则重新评估范围或算法，不恢复 10 个 Skill 白名单或 25 个业务硬过滤，也不降低门槛。

## 14. 被否决的方案

### 14.1 只补当前三个业务映射

只能修复一个案例，其他未绑定 Scenario 仍会失败，不符合全量备选池目标。

### 14.2 将 25 个业务槽位扩成 84 个

会形成两套重复目录，使每个新增 Skill 都要重复登记并持续漂移。

### 14.3 将候选快照从 12 扩成 24

会扩大 Planner 上下文、人工预览和验证面，却不能解决多交付物覆盖算法缺失。FrozenPlan v2 只补充候选身份，仍保持 12 个上限；检索全集与 Planner shortlist 不混为一层。

### 14.4 每次把 84 份完整 Skill 指令交给 LLM

成本高、噪声大、扩大提示注入面，也违背按需加载边界。

### 14.5 增加持久化 `selection_source`

来源可由 Candidate Snapshot、`skill_registry_id` 和 legacy 状态无歧义派生。再保存一份字符串会产生漂移，因此继续使用派生来源。

### 14.6 第一版增加 LLM rerank

它会增加 Standard 延迟并引入 DeepSearch 预算、幂等和恢复分支。确定性全量检索 + 现有 LLM Planner 已满足核心目标。

### 14.7 无 Skill 时退化为自由 LLM 报告

会把未执行分析包装成完整结果，破坏证据与可追溯性，因此继续禁止。

### 14.8 继续把 `candidate_skill_ids` 当作完整快照

ID 列表不能证明 Planner 看过哪版 Profile、哪张能力卡或哪套检索策略，也无法安全支持后续编辑。新 Plan 使用 Candidate Snapshot；ID 列表只作兼容投影。

### 14.9 用 Scenario 展示文案判断输出兼容

当前 Profile output kind 与中文 Scenario 文案不在同一命名空间，直接求交会拒绝合法节点。服务端只使用 canonical output ID 与受审映射，展示文案不参与逻辑。

### 14.10 第一版引入精确集合覆盖求解器

精确求解会增加算法、预算和错误分支，却不是放开全量候选池的必要条件。第一版使用确定性贪心策略，不能覆盖时返回保守错误并通过冻结 holdout 量化误拒；只在误拒超过发布门槛后再单独评估求解器。

## 15. ADR 冲突与处理

本方案明确替代 [ADR 0004](../adr/0004-skill-matrix-plan-execution.md) 的以下内容：

> 第一版只允许十个 Wiki Domain Skills 参加自动规划，并排除扩展到其他 Skill。

同时细化其“disabled, unbound, unauthorized, stale, unready profiles before ranking”规则：

- disabled、非 builtin、Profile 未审或 stale 仍在模型前删除；
- Task/Scenario unbound 不再等于 Runtime Skill 不可用；
- Binding 开启但 Tool/公共资源暂不可用的 builtin Skill 可以形成安全诊断；仅在必要能力无替代时形成 blocking gap，且永不进入 Planner shortlist。

以下 ADR 0004 决策继续有效：

- 持久化 SkillPlan；
- 最多 12 个候选；
- 最多 6 个节点、深度 4、并发 3；
- 服务端确定性校验；
- Plan 与 Tool 两级审批；
- 节点启动/恢复前重新授权；
- 失败传播、取消、恢复和审计；
- `off / preview / execute` 发布策略。

替代 ADR 新增以下决定：Candidate Snapshot v1 是新 Plan 的候选事实源；Scenario output 在 Task Catalog v2 使用 canonical ID 与受审兼容映射，v1 按保存的 version/hash 只读兼容；DeepSearch v1 Artifact 保持不变，新 Universal 语义使用 FrozenPlan v2；`off` 是主回滚路径，写入新语义记录后不支持任意旧二进制降级。

替代 ADR 必须在 Phase 1A 的代码改动前接受，避免实现与已接受架构决策相互冲突。

## 16. 工期与依赖

### 16.1 核心工期

| 工作项 | 预计时间 |
| --- | ---: |
| Phase 0：FrozenPlan v1/v2 兼容、发布与 quiesce/recovery 竞态 Spike | 3~5 个工程日 |
| Phase 1A：ADR、检索、审签与评测骨架 | 5~8 个工程日 |
| Phase 1B：74 个新 Profile、84 个 Profile 全审与黄金集 | 8~15 个审查人日，另需 2~4 个工程日 |
| Phase 2A：Standard Candidate Snapshot、Task Catalog v1/v2 兼容、Planner Preview 与回滚基础 | 6~9 个工程日 |
| Phase 2B：Standard 执行、完成判定、报告与 UI 闭环 | 4~6 个工程日 |
| Phase 3：DeepSearch FrozenPlan v2、恢复/预算/兼容、recovery fence 与真机验收 | 7~10 个工程日 |
| 合计 | 27~42 个工程日，另需 8~15 个审查人日 |

工程估算假设一名熟悉当前代码的后端开发为主、前端配合。Phase 0 完成后必须按冻结的 v1/v2 消费点和已验证的 quiesce 改动面重新做一次自底向上估算，表中范围不是跳过 Spike 的承诺。审查人日单独计算，日历工期取决于 CODEOWNER 和第二审人员的可用性；Profile 信息无法从现有材料核实时，该项保持 draft，不以赶工替代审签。

### 16.2 外部依赖

核心方案不增加 API Key、数据库、新服务或第三方运行时，复用现有：

- LLM Provider；
- Embedding/Profile Vector；
- SQLite；
- Tool Gateway；
- DeepSearch Budget、Artifact 和 Evidence Pipeline。

27 个 tool-limited Skill 的完整执行依赖 Zero、JoySpace、O2、MCP、受控文件/Git 或其他业务系统授权，是独立项目，不作为本方案完成条件。

部署必须保持一个应用进程独占该 SQLite，采用 stop-old-before-start-new，不使用共享数据库的滚动副本。需要多进程或高可用时，必须先以共享调度/租约和非 SQLite 存储另立方案。

部署入口必须能在停机窗口原子阻断全部新 runtime mutation，包括 planned orchestration 与 direct explicit，并通过受信 ingress ACL 只允许部署器从 loopback/管理网调用经过认证的 quiesce 操作；公共入口必须拒绝该路径，判定不得依赖客户端 Header。进程管理器必须能在 force-stop 前关闭自动重启。本期只增加不可逆的进程生命周期 quiesce latch，不增加可开关的临时运行模式或后台恢复 drain 协议；worker drain grace 固定为 0。该临时停机 fence 不改变重启后 `off` 仍允许 direct explicit 的产品语义。

### 16.3 回滚成本

- 无 SQLite 列迁移；新增的是 AgentRun JSON 中的 `planning_contract_version`、Plan JSON 中的 Candidate Snapshot 和 DeepSearch FrozenPlan/Snapshot v2。
- `AGENTMESH_SKILL_ORCHESTRATION` 是启动时环境变量，不假装支持进程内热切换。回滚按唯一顺序执行：先关闭进程管理器自动重启；公共入口原子启用进程停机 fence，临时拒绝所有新 runtime 工作，包括 create、Plan PATCH/approve/reject/execute、clarify、Tool approval approve/reject resolution、retry/replan、自然语言 orchestration 和 direct explicit start/resume，只保留读取及显式 cancel；部署器随后从不经过该公共 fence 的受控 loopback/管理路径调用 `POST /api/admin/skill-orchestration/quiesce`。该操作在共享 admission lock 下单向关闭上述 forward mutation、节点 `READY → RUNNING` claim、Tool call claim 与 recovery scan/schedule admission，调用 `DeepSearchRecoveryCoordinator.begin_quiesce()`，并在新 admission 全部被拒绝后响应；它不等待已执行工作，已 claim 节点/Tool 仍可写结果或稳定未知终态，但不能 claim 后继节点/Tool。确认响应后立即 force-stop 唯一应用进程，worker drain grace 固定为 0。进程管理器最多等待 10 秒确认 PID 消失，未退出则发送 `SIGKILL`；这 10 秒只用于确认停机，不允许运行任务继续 drain。

  确认 SQLite 无其他 owner 并取得独占锁后，先运行 `scripts/quiesce_skill_orchestration.py --database <path>` 默认 dry-run，列出并计数全部新语义 Run/Plan 目标、所有 AgentRuntime 未解决 Tool call claim，以及非终态无 Plan Run 的完整 claim 历史，且校验不存在 marker/Plan shape 不一致、孤立 Plan 或无法分类的 claim；任一异常必须停止并人工调查，禁止直接 apply。预览正确后运行 `--apply`，并在应用仍停机、仍持有独占条件时再次执行默认 dry-run，各类目标都必须为 0；验证失败不得启动应用。对 direct explicit/通用 Run，脚本不创建 Plan 或新语义，只按 8.1 追加 abandoned/unknown 并终态化父 Run。验证通过后才以同一个前向兼容二进制和 `AGENTMESH_SKILL_ORCHESTRATION=off` 启动；该模式既不启动 Recovery Coordinator，`recover_once()` 自身也在枚举和 schedule 前 fail closed，但新的 direct explicit/通用 Run 按既有合同重新可用。启动后通过受保护的 `GET /api/health/providers` 验证 `skill_orchestration_mode=off` 且 `deepsearch_recovery_running=false`，不得在运行中的应用旁再次调用要求独占 SQLite 的离线脚本。缺少公共停机 fence、受控 quiesce 路径或关闭自动重启能力时不得执行在线回滚；`preview` 不能代替 quiesce 或 `off`。
- 离线命令只通过 repository 的 compare-and-set/事务枚举并终态化 `planning_contract_version in {standard_universal_v1, deepsearch_frozen_v2}` 的关联 Run/Plan 对，包括尚无 Plan 的 Run；`candidate_snapshot != null` 或 FrozenPlan v2 shape 只作防御性补漏并要求与 marker 一致。它还枚举全部 AgentRuntime 中未解决的 `RuntimeToolCallClaimV1`，不受 planning contract 是否为空限制：仅 `side_effect=read` 追加 `tool_call_abandoned`，`write|external|idempotent_write|non_idempotent_write` 及未知/缺失值一律追加 `tool_call_outcome_unknown`；并对每个待终态化的无 Plan 父 Run 检查全部已提交 claim，任一非纯读 claim 即使已有 settlement，也使父 Run 进入 `FAILED + external_outcome_unknown`，后台和用户 retry 入口均须拒绝。没有非纯读 claim 的无 Plan 父 Run 进入 `FAILED + process_restarted`。进程仍在运行或数据库不能取得独占写锁时必须拒绝。`CREATED`、`PLANNING`、`WAITING_CLARIFICATION`、`WAITING_PLAN_APPROVAL`、`WAITING_APPROVAL`、`APPROVED` 及普通剩余任务进入 `CANCELLED`。遗留 RUNNING 写节点进入 `FAILED + external_outcome_unknown`，其余所有非终态节点（包括并行 RUNNING READ/DRAFT 与未启动节点）进入 `CANCELLED`；完成全部节点终态化后，含 outcome-unknown 写节点的 Plan/Run 按 7.6 的 `has_valid_partial_delivery` 进入 `PARTIAL` 或 `FAILED`。现有执行路径没有持久化 heartbeat，回滚合同不依赖无法证明的租约；重复执行命令必须幂等，late callback 不得覆盖终态或 Tool settlement。
- 取消只能阻止后续节点，不声称能撤回已被外部系统接收的写入。持久化 `call_id` 只提供本地调用身份与追踪，不等于外部 Provider 保证幂等；结果未知时自动 retry/replan 默认拒绝，也不启动替代节点。运维人员根据 Tool 审计记录核对或手工补偿；Tool 专用对账只能追加关联 `call_id` 的不可变记录，不能覆盖原终态或 Artifact/hash。只有该记录已确定原调用结果且 Tool 专用政策明确允许时，才可另行处理；本期不新建通用对账、终态纠正或补偿框架。
- 唯一代码回滚策略是保留当前能读 Task Catalog v1/v2、Candidate Snapshot 和 FrozenPlan v1/v2 的前向二进制，在 `off` 下修复并 roll forward。一旦写入新语义记录，就明确禁止部署旧二进制或直接 `git revert`；本期没有 parser-first release，也不承诺任何代码降级目标。
- 终态 Plan、Result 和 Artifact 不删除、不降级、不重新执行；恢复新版本后仍可读取。新增 Profile 继续作为静态资产保留。

## 17. 完成定义

以下条件全部满足才算完成：

- 84/84 内置 Runtime Skill 具有有效、按可信审签策略完成相应单审/双审、owner SLA 无未决项，且可按 7.1/16.3 通过停机撤版失效的 Profile；不承诺请求时实时撤销。
- 无额外权限限制的基线用户能检索 84/84；生产请求严格按可见范围缩小。
- Standard 与 DeepSearch 均不再依赖 10 Skill 自动编排白名单。
- Scenario 不再作为 Runtime 候选硬过滤器。
- 多交付物确定性召回、RRF 合并、配额、去重和保守的 coverage exhaustion 行为均有固定合同并达到 3.3 门槛。
- LLM 只能从最多 12 个 ready Candidate Snapshot entry 规划最多 6 个节点；repair、编辑、批准和恢复不能改变该快照。
- canonicalizer 的权威词汇、映射与版本有确定性合同；Planner 出站数据满足最小化/脱敏要求，并有无原文的 token、时延与费用遥测。
- Scenario 使用 canonical output ID 与受审 output-kind 映射；归属歧义在批准前由用户解决，coverage 与 capability gaps 只由服务端计算。
- Universal 节点从 Plan 创建、编辑、确认、执行、完成检查到重试全链路可用。
- direct explicit 保持无 Plan 的现有路径，不与自然语言 Universal 节点混用。
- blocked Skill 不进入执行节点；其匹配默认只生成 informational 诊断，只有对应 required atom 没有 ready coverage 时才生成 blocking gap。
- 27 个 tool-limited Skill 不会被假装执行。
- Standard 与 DeepSearch 的权限、预算、证据和报告边界没有放宽。
- 旧 Plan、Task Catalog v1、DeepSearch FrozenPlan/Snapshot v1 和旧 Artifact hash 兼容测试通过；新 routed Standard/DeepSearch 使用 Catalog v2，unrouted 使用 canonical `routing_catalog_identity=null`，FrozenPlan v2 hash 覆盖 Candidate Snapshot 和该 routing identity。
- `off` 流量回滚、`off` 下 direct explicit 保持可用、进程级 quiesce 阻断新 direct-explicit Tool claim、recovery 竞态、按 planning contract 捕获无 Plan/非终态 v2 Run 的 preflight，以及不支持任意旧二进制降级的运维合同通过。
- Phase 0 SQLite 并发/容量门槛和 Phase 2A 真实 Preview 门槛通过；Phase 2A 的代码级硬门禁证明 Universal 节点不能执行，Phase 2B 才启用 execution contract v1。
- 任何有 Plan 或无 Plan 的 `external_outcome_unknown` 来源 Run 都不能经后台或用户 retry 入口创建新 Run；只有 Tool 专用对账与政策明确允许后，用户才能另行发起不同幂等身份的新请求。
- 全量后端、前端、构建、E2E 和批准的真实 Provider smoke 通过。
- 替代 ADR、README、CONTEXT 和运维说明同步完成。

## 18. 开发交接结论

推荐实现“全量检索、12 个安全候选、按需加载、服务端强校验”，不实现“84 份指令一次性输入模型”或“扩大候选快照”。

交付后的准确用户承诺是：

> 当前 84 个内置 Skill 在 Binding 开启且 Profile 已审、有效时都会被检索系统考虑；LLM 会从当前真正可执行的候选中规划。缺少工具、资源或授权的能力会被明确说明，不会被隐藏，也不会被伪装成已经执行。

本方案没有待开发者自行决定的架构空白。批准后按 Phase 0 → Phase 1A → Phase 1B → Phase 2A → Phase 2B → Phase 3 实施；Phase 0 必须先验证兼容与回滚假设并重估后续工作，Phase 2A 只有在 84/84 审签、检索质量、安全和性能门槛全部通过后才能切流，Phase 2B 只有在 Phase 2A 的 Preview 与回滚验收全部通过后才能开放执行。
