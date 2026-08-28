# DeepSearch v1 开发方案

- 状态：核心实现与自动化门禁已通过，默认关闭；真实 Provider readiness 已通过，待真实 DeepSearch 全链路 smoke 后受控启用
- 日期：2026-08-26
- 最近修订：2026-08-27（完成受控 E2E wire contract 收口与独立复跑，补齐 Artifact 预算、线程恢复与 ProblemGraph 语义映射）
- 适用项目：AgentMesh
- 参考项目：`/Users/heyunshen/work/PROJECT/jdc/ai-x`
- 核心决策：迁移 ai-x 的需求分析、多轮澄清、Skill 选择、单 Plan 编排、执行与总结语义；不复制其基础设施和像素级视觉实现
- Runtime 决策：DeepSearch 始终使用 `orchestration_version="v1"`，不依赖、复用或恢复已退役的 `research-v2/research-v3`

## 0. 当前实施状态

截至 2026-08-27，Slice 1～6 的核心代码已经落地：显式模式准入、版本化 Requirement 与最多三轮澄清、ProblemGraph、唯一可编辑 Plan、批准快照、复用现有 DAG Executor、可信 Web Evidence、Coverage、Review/一次修订、SEALED Report、恢复、固定预算、指标和 Workspace 界面均已接通。功能开关仍默认关闭，不代表已完成生产发布。

实施中进一步收紧了首个可启用版本的边界：

- 外部 Evidence 生产路径只允许内置真实 `web_research`；其他内置 Tool 在编译、批准和运行期均 fail closed。
- MCP 在 DeepSearch v1 中完全禁用；在具备统一 invocation、预算和 Evidence adapter 前不得接入。
- `read_skill_resource` 只读取批准 Plan 中已冻结 hash 的方法资料，调用进入 DeepSearch 预算，但其输出不能作为 Report Evidence。
- `deepsearch-user-evidence-v1` 与 `deepsearch-knowledge-evidence-v1` 契约暂作为未来扩展保留；首版公开生产调用链没有对应 writer/入口，受支持的生产路径只会产生真实 `web_research` Evidence。
- Provider readiness 通过后仍需使用真实配置完成 DeepSearch 从创建 Run 到 SEALED Report 的全链路 smoke；在此之前保持 `AGENTMESH_DEEPSEARCH_ENABLED=false`。

## 1. 建设目标

在现有 AgentMesh 通用 Skill DAG 上增加一个显式的 `deepsearch` 请求模式，使用户可以在同一个 AI 工作台中完成：

```text
输入研究目标
  -> 需求结构化
  -> 0～3 轮澄清
  -> ProblemGraph
  -> Skill 检索与单一 Plan 编排
  -> 用户编辑、确认 Plan
  -> 现有有界 DAG 执行
  -> Evidence Manifest 封存与完整性检查
  -> Synthesis
  -> claim 级 Evidence 覆盖检查
  -> Report Review
  -> 最多一次修订
  -> 结构化文本报告
```

具体目标：

1. 普通聊天、显式 `$skill` 和现有自动 Skill 编排行为保持不变。
2. DeepSearch 由用户显式选择，不根据一段自然语言自动猜测并切换模式。
3. 保留 ai-x 的“理解需求—多轮澄清—计划确认—执行反馈—报告”交互语义。
4. 复用 AgentMesh 已有的 Task Router、Skill Intent、Skill Retriever、Skill Planner、Plan 校验、审批、DAG Executor、节点结果和 Synthesis。
5. 一个 Run 只维护一个当前有效 Plan；允许编辑和版本递增，不生成 2～4 套候选计划。
6. 用 ProblemGraph 明确研究问题、证据要求、成功标准与 DAG 节点之间的映射。
7. 最终完成状态必须由节点结果、Evidence 覆盖、Review 和报告共同证明，不能只因为 LLM 生成了文本就标记为完成。
8. 保持 SQLite 单实例原型架构，不为首期 DeepSearch 引入分布式控制面。

ai-x 能力与 AgentMesh 落点如下：

| ai-x 能力 | AgentMesh 落点 | 迁移策略 |
| --- | --- | --- |
| 用户需求分析 | `RequirementRefiner` | 迁移交互和结构化契约 |
| 多轮澄清 | DeepSearch Requirement 版本链 | 保留，最多 3 轮、每轮最多 5 问 |
| Skill 查找 | 现有 `SkillCandidateRetriever` | 复用权限和就绪度过滤 |
| Plan 编排 | 现有 `SkillPlanner` + DeepSearch 校验 | 只保留一个当前 Plan |
| 任务执行 | 现有 `BoundedDAGExecutor` | 不迁移第二套 Execution Engine |
| 汇总报告 | 现有 Synthesis 服务 + DeepSearch claim/Evidence/Review 契约 | 增加完成门禁和一次修订 |
| 研究工作台 | AgentMesh Workspace | 保留阶段语义，使用 AgentMesh 视觉系统 |

## 2. 明确不建设

首期明确排除以下内容：

- 不复制 ai-x 的 PostgreSQL Control Plane。
- 不迁移 Lease Worker、任务抢占、分布式租约或巨型 Execution Engine。
- 不复制 ai-x 的 `/control-tasks` API；继续使用 Agent Run、Plan 和事件接口。
- 不生成 depth/speed 等多套完整候选 Plan；深度、时间、成本只作为 Requirement 或当前 Plan 参数。
- 不将已退役 `research-v2/research-v3` 的业务 Schema 作为 DeepSearch 领域模型，也不导入其 Repository、Executor、状态机或展示模型。
- `research-v2` 只保留历史 reader、fixture 和兼容 Schema；它们只服务已有历史 Run，并继续保持只读。
- `research-v3` 已在上线前退役；DeepSearch 不保留其 Preview、Catalog、Workbench 或任何恢复入口。
- 不复制 ai-x 的 Skill Registry；使用 AgentMesh 当前用户可见、已启用、资源就绪的 Skill Catalog。
- 不复制 ai-x 的导航、登录、全局侧栏、独立主题或像素级 CSS。
- 不建设 PDF、ZIP、截图采集、Visual Manifest、图片标注、视觉对比或 Zero 发布。
- 不引入后台队列、跨进程调度或多实例执行承诺。
- 不在首个可启用版本中接入 MCP、其他内置 Tool、用户上传 Evidence 或 Knowledge Evidence；外部证据只允许真实 `web_research`。
- 不允许 DeepSearch 执行 `WRITE` 或其他有外部写副作用的节点；首期 Plan 只允许 `READ | DRAFT`。需要落库、发布或修改外部系统时，用户基于报告另行发起 standard Run。
- 不允许 DeepSearch 绕过现有用户权限、Tool Grant、审批、Artifact、审计和取消语义。
- 不让模型发明 Skill、Tool、来源、Evidence 或完成状态。

如果未来确实要删除 `research-v2`，应另立退役任务，先完成历史数据清点、读取迁移、fixture 替换和回滚验证；不得把这项高风险清理混入 DeepSearch 功能开发。

## 3. 模式与路由规则

### 3.1 显式模式

在创建 Run 的请求中增加正交字段：

```python
class AgentPlanningMode(StrEnum):
    STANDARD = "standard"
    DEEPSEARCH = "deepsearch"
```

`AgentRunCreateRequest.planning_mode` 默认是 `standard`。旧客户端不传该字段时，行为完全不变。

```json
{
  "content": "分析国内协同设计工具市场并给出进入建议",
  "client_turn_id": "turn_123",
  "orchestration_mode": "auto",
  "planning_mode": "deepsearch"
}
```

### 3.2 路由优先级

`POST /api/agent/runs` 按以下顺序处理：

1. 鉴权并按服务端规范化后的请求身份校验 `client_turn_id` 幂等性。
2. 若命中完全相同的既有请求，直接返回原 Run；幂等重放先于当前功能开关和 Runtime 就绪度检查。
3. 校验 `planning_mode=deepsearch` 与显式 Skill 的冲突。
4. 对尚未创建的 DeepSearch 请求执行功能开关、有效执行模式和核心 Runtime 准入检查。
5. `planning_mode=deepsearch` 时进入 DeepSearch Planning Service。
6. DeepSearch Run 固定写入 `orchestration_version="v1"`，不得调用任何已退役 Research 代码。
7. `planning_mode=standard` 时，继续执行当前显式 Skill、Task/Scenario 和通用 v1 Skill DAG 逻辑。

Agent Run 的幂等身份固定包含：

```text
user_id
thread_id
client_turn_id
content
explicit_skill_name / skill_name
orchestration_mode
planning_mode
retry_of_run_id             普通创建为 null
```

缺失 `planning_mode` 时先规范化为 `standard`。同一 `user_id/client_turn_id` 的身份完全相同则返回原 Run；任一字段不同均返回 `409 client_turn_id_conflict`。路由层预检查和 Store 原子 claim 必须使用同一个 `create_request_hash`，不得各自维护不同判断。

DeepSearch 首期只支持自动多 Skill 规划：

- `planning_mode=deepsearch` 与 `explicit_skill_name`/`skill_name` 同时出现时返回 `400`。
- 请求侧 `orchestration_mode` 必须为 `auto`，服务端有效 `AGENTMESH_SKILL_ORCHESTRATION` 必须为 `execute`；`off/preview` 均拒绝创建或批准 DeepSearch Run，preview 不得把它直接标记为完成。
- DeepSearch 功能关闭或执行条件不满足时返回稳定错误，不静默降级成普通 LLM 回答。稳定错误码为 `deepsearch_disabled`、`deepsearch_execution_unavailable`、`deepsearch_runtime_unavailable`、`deepsearch_model_unavailable`、`deepsearch_planner_unavailable`。
- 前端可以提示用户切换 DeepSearch，但不能仅凭关键词代替用户选择。
- Run 创建后以服务端保存的 `planning_mode` 为准；前端不得二次猜测运行类型。

### 3.3 兼容性不变量

- DeepSearch 只是 v1 的规划模式，不引入 writer generation 或版本选择控制面。
- 现有 `SkillOrchestrationRequestMode.AUTO/SINGLE` 不重命名；`planning_mode` 只描述交互与规划路径。
- 现有 `$skill` 私有显式执行边界保持不变。
- Retry 总是创建新 Run，并继承 `planning_mode=deepsearch`，但不得直接复用旧 Run 的 Requirement ID、Plan、Node Result、Source 或 Artifact。允许重试时，服务端先验证新旧 Run 的 owner/workspace/project 一致，再把最后一个已验证 Requirement payload 复制成新 Run 的 Requirement v1，并记录 `derived_from_requirement_version_id`；随后重新生成和校验 ProblemGraph/Plan。
- `deepsearch_clarification_unresolved`、`external_outcome_unknown`、权限错误和 Evidence 完整性错误禁止通用 Retry。前端分别显示“修改目标并新建 DeepSearch”或人工处理原因。
- `AGENTMESH_DEEPSEARCH_ENABLED` 只控制新 Run 和 Retry 的准入；创建成功后以持久化的 `planning_mode` 为准。关闭该开关不改变既有 Run，安全事件若要停止既有 Run 必须显式取消。

## 4. 状态机

只新增一个顶层 Run 状态：

```python
AgentRunStatus.WAITING_CLARIFICATION = "waiting_clarification"
```

状态流：

```text
created
  -> planning
     -> waiting_clarification
        -> planning
           -> waiting_clarification       最多 3 轮
           -> waiting_plan_approval
     -> waiting_plan_approval             无需澄清
        -> running                        复用现有 Plan approve
           -> waiting_approval            复用现有 Tool 审批
              -> running
           -> completed | partial | failed
        -> rejected

任意活动态 -> cancelled
```

状态约束：

1. `waiting_clarification` 时没有可执行 Plan，禁止调用任何 Tool。
2. 每轮最多返回 5 个问题，最多 3 轮。初始无需提问时 `clarification_round=0`；首次问题为第 1 轮；提交第 3 轮答案后仍有阻塞歧义时原子失败，不生成第 4 轮。最后一轮必须把可安全默认的内容转成显式 assumption，并优先询问真正阻塞的问题。
3. 第三轮后仍存在阻塞歧义时，不再调用 LLM 继续追问，也不执行 Tool；Run 以 `deepsearch_clarification_unresolved` 失败，用户可修改目标后新建 Run。
4. 非阻塞歧义可以作为可见 assumption 进入 Plan。Requirement 完成前，用户可通过当前轮答案覆盖默认值；Plan 生成后 assumption 只读，若需修改则拒绝当前 Plan，并以修订后的目标新建 Run，避免原地修改 Requirement 后留下失效 Plan。
5. Plan 未确认时禁止执行节点；Plan 确认不等于 Run 完成。
6. Evidence、Review 和 Report finalization 都属于 `running` 的内部阶段，不继续膨胀顶层状态枚举。
7. finalization 的阶段和各阶段输出 hash 写入 Plan 的 DeepSearch 上下文；只有 DeepSearch Recovery Coordinator 能在启动时恢复，GET、SSE 和浏览器刷新不得触发写操作。
8. 现有“线程是否已有活动 Run”、取消、保留、重启恢复和前端 active 状态集合都必须加入 `waiting_clarification`。

建议事件类型：

- `deepsearch_requirement_created`
- `deepsearch_clarification_requested`
- `deepsearch_clarification_answered`
- `deepsearch_problem_graph_created`
- `deepsearch_plan_ready`
- `deepsearch_evidence_checked`
- `deepsearch_report_reviewed`
- `deepsearch_report_revised`
- `deepsearch_report_sealed`
- `deepsearch_finalization_stage_changed`

继续复用 `agent_run_events`，不增加新的事件表。
事件 payload 只能记录稳定 ID、枚举、计数、hash 和耗时；不得写入用户问题、澄清答案、完整 Prompt、Evidence 正文、URL、用户 ID 或 Provider 原始错误。

## 5. 数据模型

`AgentRunCreateRequest` 和 `AgentRun` 增加 `planning_mode: standard | deepsearch`，默认值都是 `standard`。旧 Run 反序列化时使用默认值，因此不需要重写历史 payload。

### 5.1 Requirement

新增版本化契约 `RequirementPayloadV1`：

- `goal`：用户最终要解决的问题。
- `scope`：对象、地区、时间、受众和边界。
- `constraints`：时间、成本、来源、权限和格式要求。
- `success_criteria`：可验证的成功标准，每项有稳定 ID。
- `deliverables`：期望交付物。
- `assumptions`：系统采用的显式假设，标记来源和 `editable_before_plan`；Plan 生成后统一只读。
- `ambiguities`：仍未解决的歧义及其阻塞级别。
- `clarification_questions`：当前轮问题，最多 5 个，每个问题有稳定 ID。
- `clarification_history`：历史轮次、问题和规范化答案，只存在 Requirement payload 中，不复制到事件或日志。
- `clarification_round`：`0..3`。

`ClarificationQuestionV1` 固定包含：

```text
id
prompt
required
answer_kind               text | single_choice | multi_choice
options                   非选择题为空
max_length                text 最大 2000
default_value | null
```

问题 ID 由服务端生成，作用域是单个 Requirement version，格式为 `q_{version}_{ordinal}_{prompt_hash8}`。同一版本的重放保持 ID 不变；新版本即使问题文字相同也生成新 ID，旧轮答案不能命中新问题。

`RequirementVersionV1` 至少包含：

```text
id / run_id / version / schema_version
request_key / request_hash / content_hash
derived_from_requirement_version_id | null
payload / created_at
```

每次有效澄清都会追加新版本，旧版本不可覆盖。

### 5.2 ProblemGraph

新增通用 `ProblemGraphV1`，不复用竞品研究专用 Schema：

```text
ProblemQuestionV1
  id
  question
  required
  success_criterion_ids
  evidence_requirements
  acceptance_criteria
  depends_on

ProblemGraphV1
  schema_version
  requirement_version_id
  questions
  content_hash
```

ProblemGraph 只表达问题分解和验证关系，不包含执行状态。执行状态仍以 `SkillPlanNode` 为唯一真相源。

### 5.3 Skill Plan 扩展

`AgentRun` 增加以下向后兼容字段：

```text
planning_mode                 standard | deepsearch，默认 standard
create_request_hash           普通旧 Run 为 null
interaction_expires_at        等待人工操作时使用
absolute_expires_at           DeepSearch Run 最长生命周期
deepsearch_budget             普通 Run 为 null
```

`DeepSearchBudgetV1` 是服务端权威计量状态：

```text
schema_version
version
limits                     §12.1 固定上限
consumed                   active_seconds / llm_calls / tokens /
                           tool_calls / evidence_items /
                           evidence_bytes / artifact_bytes
reservations[]             logical_operation_key / invocation_key /
                           physical_attempt / resource maxima /
                           status(reserved|settled) / actual usage
finalization_reserve       300 active seconds + 1179648 artifact bytes
stage_recovery_attempts    stage -> 0..3
```

`finalization_reserve` 是总活动时间和总 Artifact bytes 内从 Run 创建时就划出的分区，因此普通操作的可用上限分别为 `1800-300=1500` 秒和 `10485760-1179648=9306112` bytes；它不可被规划、节点、模型 Synthesis 或 Review 消耗，只供确定性 Evidence Manifest/Coverage、evidence-digest fallback Synthesis、partial renderer、恢复检查点和最终 Report Artifact 使用。1179648 bytes 恰好覆盖最坏情况下 3 次 Manifest（每次最多 131072）和 3 次 Report（每次最多 262144）物理尝试。300 秒固定拆分为 Manifest 构建+保存最多 90 秒、两次 Coverage 共 30 秒、最多一次 digest 30 秒、Report 构建+保存最多 90 秒、恢复/检查点总计 60 秒；任一子额度不可向普通预算借用。这样普通预算在节点阶段耗尽或一次写入结果未知后，Finalizer 仍有预算恢复并生成安全 partial；进程崩溃后未结算 reservation 按本次预占上限计入 consumed，不能返还后再次消费。

为 `SkillPlan` 增加向后兼容的 DeepSearch 上下文：

```text
planning_mode
requirement_version_id
requirement_content_hash
problem_graph
problem_graph_hash
plan_content_hash
approved_plan_artifact_id
capability_check             运行期投影，不进入 plan_content_hash
evidence_manifest_artifact_id
evidence_manifest_hash
evidence_coverage
deepsearch_syntheses[]         append-only，最多 v0/v1 两条
synthesis_content_hashes[]
review_outcomes[]             append-only；进入 review_v*_checked 的 revision 最多一条，
                              发布 Report 的当前 revision 恰好一条
report_revision_count        0..1
report_artifact_id
report_content_hash
finalization_stage
finalization_version
finalization_input_hashes
```

`SkillPlanNode` 只增加冻结的 `question_ids`，指明负责的问题；运行期 Evidence 不能写回 Plan Node。`SkillNodeResult` 增加 `evidence_items: list[DeepSearchEvidenceItemV1]`，保存语义绑定；服务端在持久化前补齐并校验 `node_result_id`。

standard 继续使用现有 `SkillSynthesisResult/SkillSynthesisClaim`，不改变其摘要和章节语义。DeepSearch 复用现有 Synthesis 服务的模型调用、超时和错误处理，但使用独立的严格输出契约，避免 standard 的自由文本字段进入报告：

```text
DeepSearchSynthesisClaimDraft       模型输出，不含 id
  text
  question_ids / success_criterion_ids
  node_result_ids / evidence_item_ids / source_ids
  recommendation

DeepSearchSynthesisClaimV1
  id
  上述全部字段

DeepSearchSynthesisV1
  schema_version
  revision_count                   0 | 1
  synthesis_mode                   model | deterministic_evidence_digest
  claims[]
```

服务端先校验 Draft 的所有引用，再按 `hash(run_id, plan_id, plan_version, revision_count, stable_ordinal, canonical_claim_payload)` 生成 claim ID；模型不得提交 ID。同一 revision 中 canonical payload 重复时拒绝，修订后只允许引用当前 revision 的 claim ID；未知、重复或跨 revision ID 均 fail closed。claim 级覆盖只通过 `evidence_item_ids` 建立。

普通预算不足以调用模型 Synthesis，或原始调用与一次格式修复都失败时，服务端可为当前 revision 生成 `deterministic_evidence_digest`：每条 claim text 只能逐字使用 sealed Envelope 的 excerpt，并附其既有 Evidence Item/Source/Question/Criterion 引用，不得组合出新事实或建议。该模式只能产出 `partial`，Review 记为 `not_run`，且仍需重新经过 Coverage 和 `safe_partial_report`。

`DeepSearchSynthesisV1` 按 revision append-only 保存到 Plan 的内部 `deepsearch_syntheses`，对应 hash 同步追加，禁止用 v1 覆盖 v0；DeepSearch 的既有 `synthesis` 字段保持 `null`，防止 `GET /plan` 按 `SkillSynthesisResult` 误解析。`GET /plan` 和 aggregate 中的 `plan` 都必须通过显式 view projection 隐藏 `deepsearch_syntheses` 及内部 stage payload；aggregate 只通过独立 DTO 返回不含正文的 Evidence Coverage 和 Review ID/code 投影。只有 SEALED Report Artifact 的服务端投影可以作为报告正文。standard 响应继续只使用原 `synthesis` 字段。

以上所有 DeepSearch 字段对 standard Run 使用默认空值。OpenAPI 可以出现 additive 字段，但 standard 的路由、状态、事件、终态和已有字段语义必须向后兼容。

`finalization_stage` 使用窄枚举：

```text
none
nodes_terminal
evidence_manifest_sealed
synthesis_v0_saved
coverage_v0_checked
review_v0_checked
synthesis_v1_saved
coverage_v1_checked
review_v1_checked
terminal_committed
```

允许的正常路径为：

```text
none -> nodes_terminal -> evidence_manifest_sealed
     -> synthesis_v0_saved -> coverage_v0_checked -> review_v0_checked

review_v0_checked(pass)   -> terminal_committed
review_v0_checked(revise) -> synthesis_v1_saved
                          -> coverage_v1_checked -> review_v1_checked
                          -> terminal_committed
```

非 happy-path 转移固定为：

```text
coverage_v0_checked(fail)
  -> review_v0_checked(outcome=not_run, reason=coverage_failed)
  -> terminal_committed(partial | failed)
coverage_v0_checked(pass + digest 或 Review budget unavailable)
  -> review_v0_checked(outcome=not_run) -> terminal_committed(partial | failed)
review_v0_checked(block) -> terminal_committed(partial | failed)
Review 物理尝试耗尽 -> review_v0_checked(outcome=error) -> terminal_committed(partial | failed)
coverage_v1_checked(fail)
  -> review_v1_checked(outcome=not_run, reason=coverage_failed)
  -> terminal_committed(partial | failed)
coverage_v1_checked(pass + digest 或 Review budget unavailable)
  -> review_v1_checked(outcome=not_run) -> terminal_committed(partial | failed)
review_v1_checked(revise | block) -> terminal_committed(partial | failed)
Review 物理尝试耗尽 -> review_v1_checked(outcome=error) -> terminal_committed(partial | failed)
任意非终态 stage 出现确定性失败/取消/过期 -> terminal_committed
```

`partial | failed` 必须由 §10.3 纯函数得出，不能由 stage handler 选择。`review_v1_checked` 不得再次触发修订。阶段禁止反向移动。`finalization_version` 初始为 0，每次成功 CAS 加 1；`finalization_input_hashes` 按 stage 保存输入 hash。每次 CAS 同时校验 Plan version、`finalization_version`、当前 stage、Requirement/Graph/Plan hash 和对应 stage 输入 hash。

`evidence_manifest_sealed` 的 CAS 必须在同一事务中 seal Manifest Artifact 并写入 Plan 的 Artifact ID/hash；其余阶段的结构化输出和 hash 同样与 stage 原子提交。

正常完成或 partial 在进入 `terminal_committed` 前先创建不可见的 STAGING Report Artifact；最终事务同时完成 Artifact seal、Plan link/hash、SkillPlan 终态、Run 终态、`output_text` 投影和最终事件。已有 Plan 时，Plan 与 Run 的终态一一对应为 `completed/completed`、`partial/partial`、`failed/failed`、`cancelled/cancelled`、`rejected/rejected`；确定性失败、拒绝、过期或取消直接 CAS 到 `terminal_committed`，不封存报告，并把遗留 STAGING Report Artifact 标记为 `FAILED`。如果 Run 在有效 Plan 产生前失败、取消或过期，则只用一个 Run/Event 事务写终态，不创建虚假 Plan 或 `terminal_committed` stage。`terminal_committed` 同时记录最终 Run status 和 error code。

### 5.4 Evidence 与 Review

新增服务端权威契约 `TrustedEvidenceEnvelopeV1`：

```text
schema_version
origin_type               tool | user_input | knowledge
run_id / requirement_version_id
plan_id / plan_version | null
node_id / attempt | null
tool_name / tool_implementation_id / tool_implementation_version | null
execution_mode             real | fake | fallback | null
content_provider | null
tool_call_id / operation_key | null
request_hash
source_id | null
source_ordinal | null
normalized_reference
retrieved_at
excerpt / content_hash / size_bytes
```

Tool 调用使用服务端契约：

```text
DeepSearchToolInvocationV1
  run_id / requirement_version_id
  plan_id / plan_version
  node_id / node_attempt
  tool_definition_id / implementation_id / implementation_version
  tool_call_id / operation_key
  canonical_arguments_hash
```

每个 DeepSearch 节点 attempt 都把 `plan_id/plan_version/node_id/node_attempt` 写入 `AgentMeshRunContext`。每次真正进入 Tool handler 前，服务端先生成 `tool_call_id`，再用 `hash(run_id, plan_id, plan_version, node_id, node_attempt, tool_call_id)` 生成唯一 `operation_key`，并将二者随预算 reservation 一起持久化；不得使用进程内计数器、模型返回值或 Provider 返回值作为调用身份。`AgentMeshToolFactory` 不再直接调用裸 handler，而是把完整的 `DeepSearchToolInvocationV1` 传给 `ToolGateway.invoke(...)`；Gateway 及当前 Web adapter 必须继续透传该身份，未来新增 adapter 也必须遵守同一契约。调用在持久化 reservation 前不得访问外部系统；进程崩溃后的未知调用不自动重放。

每一条 Tool `source_evidence`，无论正文大小，都必须由 Tool Gateway 在服务端生成一个 Envelope，并保存为 `sealed` 的 `deepsearch-tool-evidence-v1` Artifact；一个含多个 Source 的 Web 调用会生成多个 Envelope。Tool origin 必须具有非空 Plan/Node/Attempt 归属。模型只能引用 Artifact/Source ID，不得提交或覆盖 Provider、抓取时间、引用、内容 hash 或 Tool 模式。外部证据要求存在时，`origin_type=tool` 且 `execution_mode=real`；`fake`、`fallback`、缺失 Envelope 或归属/hash 不一致均 fail closed。

Web adapter 必须在写库前规范化整批结果，并按 `(normalized_reference, content_hash, title)` 排序；相同 `normalized_reference` 的结果按排序后位置得到稳定 `source_ordinal`。`source_id` 固定由 `run/plan/version/node/attempt/operation_key/normalized_reference/source_ordinal` 生成，Evidence Artifact ID 再由 `source_id` 派生；分配稳定 ID 后必须同步改写每个 `source_evidence.source_id`，再原子写入整批数据。Provider 返回顺序变化不得改变 ID；同一 operation key 下相同 ID 出现不同正文、hash 或 lineage 时整批 fail closed，不能覆盖旧 Source/Artifact。MCP 不属于 DeepSearch v1；未来若接入，必须先实现并验证等价的 invocation、预算和 Evidence adapter 契约。

`deepsearch-user-evidence-v1` 与 `deepsearch-knowledge-evidence-v1` DTO 只保留为后续扩展契约，首个可启用版本不提供对应生产入口。当前可由公开生产调用链生成并进入 Report 覆盖门禁的 Evidence，仅有内置真实 `web_research` 产生的 `deepsearch-tool-evidence-v1`；测试或内部构造其他 Envelope 不代表已提供对应生产能力。`read_skill_resource` 读取的是批准 Plan 中 hash 已冻结的方法资料：调用计入 DeepSearch Tool/活动时间预算，但不生成 Evidence Envelope，也不能支撑 claim。模型生成文本、普通 DRAFT Artifact、Skill Resource Source 或未冻结的 Knowledge 查询结果均不能成为 Evidence。

`DeepSearchEvidenceItemV1` 将语义覆盖绑定到可信凭据：

```text
id
question_ids / success_criterion_ids
node_result_id
source_id | null
evidence_artifact_id
```

模型返回不含 `id/node_result_id` 的 `DeepSearchEvidenceBindingDraft`；服务端校验后，根据 node result、Artifact、问题和 criterion 绑定的 canonical hash 生成 `DeepSearchEvidenceItemV1`，并写入 `SkillNodeResult.evidence_items`。`question_ids` 必须是该节点 Plan 中冻结的子集。Tool Source/Artifact 必须来自同一 Run/Plan/Node/Attempt；未来若开放 user_input/knowledge writer，其 Artifact 还必须满足同 owner/workspace/project 和冻结版本约束。Finalizer 从数据库中的节点结果和 sealed Envelope 构建 `DeepSearchEvidenceManifestV1` 并封存为 Artifact，不能接受模型直接提交的完整 Manifest。Synthesis claim 必须引用 `evidence_item_ids`，只引用 `source_ids` 不能通过 claim 覆盖门禁。

`DeepSearchEvidenceManifestV1` 是严格 DTO，不是任意 JSON：

```text
schema_version
run_id / requirement_version_id
plan_id / plan_version / plan_content_hash
items[]                       1..60，按 evidence_item_id 排序
  evidence_item_id / node_result_id
  evidence_artifact_id / evidence_artifact_content_hash
  source_id | null
  origin_type
  question_ids / success_criterion_ids
```

Manifest 不复制 excerpt，只封存已验证引用。`evidence_item_id` 必须唯一，完全重复的 canonical item 禁止出现；同一 Artifact/Source 可以被不同 Evidence Item 复用，但每项都必须逐字段匹配当前批准 Plan 的 Node Result、Evidence Item、SEALED Evidence Artifact 和 Source。Finalizer 构建与读取 Manifest 时都重新执行该校验；空对象、空 items、未知字段、重复 item、旧 Plan version 或只在 JSON 外层 hash 正确的内容均无效。

`DeepSearchEvidenceCoverageV1` 至少记录：

- required/covered/uncovered question IDs；
- required/covered/uncovered success criterion IDs；
- 已校验和无效的 claim/source/result 引用；
- 外部 Evidence 是否来自真实 Tool 结果；
- `passed` 和稳定 gap codes。

`DeepSearchReportReviewV1` 至少记录：

- 被审核的 Requirement、ProblemGraph、Plan、Synthesis content hash；
- `verdict: pass | revise | block`；
- `unsupported_claim_ids`、`contradictory_claim_ids`、missing section IDs 和稳定 limitation codes；
- `revision_count`；
- reviewer 类型、Schema 版本和时间。

Reviewer 只能返回当前 revision 的 claim/section ID；服务端拒绝未知、重复或跨 revision ID。`block` 若基于 claim 质量，必须列出对应 unsupported/contradictory claim IDs，不能只返回不可执行的自由文本判断。

每个进入 `review_v*_checked` 的 revision 都要持久化一个恢复检查点；最终发布 completed/partial Report 的当前 revision 必须恰好有一条：

```text
DeepSearchReviewOutcomeV1
  schema_version
  revision_count                 0 | 1
  synthesis_content_hash
  outcome                        not_run | pass | revise | block | error
  review                         DeepSearchReportReviewV1 | null
  reason_code                    stable code | null
```

`pass/revise/block` 必须带有 verdict 完全一致、revision/hash 匹配的 Review，且 `reason_code=null`；`not_run` 只允许在尚未调用 Reviewer 的 `coverage_failed`、`budget_unavailable` 或 `deterministic_digest` 路径出现，`review=null` 并写对应稳定原因码；`error` 必须在 Review 物理尝试耗尽后写稳定错误码且 `review=null`。Review stage CAS 按 `revision_count` 向 Plan 的 `review_outcomes` append-only 追加，禁止覆盖 v0，且同一 revision 只能有一条。取消、拒绝、过期或在 Review 检查点前进入无报告 `failed` 的 revision 可以没有 Outcome，不得为这些路径伪造 `not_run`；如果 Outcome 已在终态竞争前提交则保留，不得删除。仅当 Report 存在时，其 `review_outcome/review_reason_code/synthesis_content_hash` 才必须逐字匹配当前 revision 的记录；aggregate 的 `report_review` 在存在 Outcome 时只是最后一条记录的无正文投影，否则为 `null`。

`DeepSearchReportV1` 是最终 Artifact 内容：

```text
schema_version
run_id / requirement_version_id / plan_id / plan_version
requirement_content_hash / problem_graph_hash / plan_content_hash
evidence_manifest_hash
synthesis_content_hash
review_outcome              not_run | pass | revise | block | error
review_reason_code | null
report_status               complete | partial
title                       服务端从 Requirement goal 派生
claims[]                    DeepSearchSynthesisClaimV1 投影：id / text / node_result_ids /
                            evidence_item_ids / source_ids / question_ids /
                            success_criterion_ids
executive_summary_claim_ids[]
sections[]                  section_id / server_heading / claim_ids
sources                     规范化引用投影
limitations[]               稳定 gap/review code / related IDs /
                            服务端模板 description
rendered_text               服务端确定性投影
```

该 DTO 使用 `extra=forbid`。模型只能产出结构化 claim 草稿，不能提交独立的标题、摘要正文、章节标题/正文、limitation 描述、section/summary 编排或 `rendered_text`。服务端按 ProblemQuestion 的冻结顺序把已验证 claim 分组到 sections，按 required question/criterion 的稳定顺序选择 summary claim，并从 Requirement 与稳定 gap/review code 生成其他非 claim 文本；随后用固定模板把 claim text、规范化引用和结构化 limitations 渲染为 `rendered_text`。Review 未执行时写 `review_outcome=not_run`，timeout、非法 Schema 或调用失败时写 `error`，两者都写稳定 `review_reason_code` 并强制加入对应 limitation；不得伪造 `pass/revise/block`。模板之外不得出现模型自由文本，未在 `claims` 中建模的事实无法进入最终正文。Artifact `content_type=application/json`，内容使用 canonical JSON；`AgentRun.output_text` 必须逐字等于服务端生成的 `rendered_text`。

普通 Run 不强制生成以上 Artifact。对 DeepSearch，仅存在 `Source` 或模型自述不构成可信 Evidence。

### 5.5 DeepSearch 聚合响应

新增 `DeepSearchStateResponse`：

```text
run
active_requirement
problem_graph | null
plan | null
evidence_coverage | null
report_review | null
retry_disposition           retry_run | revise_goal | none
```

响应只投影服务端权威状态，不建立与 Run/Plan 并行的第二套状态源。

`BootstrapState` 增加 secret-safe 的入口状态：

```text
deepsearch_availability
  available
  enabled
  runtime_mode              off | preview | execute
  core_ready
  reason_code               null | disabled | execution_unavailable |
                            runtime_unavailable | model_unavailable |
                            planner_unavailable
```

这里仅检查 DeepSearch 必需的 Runtime、模型、Planner 和 Catalog，不要求所有 Provider 都健康，也不暴露 Provider 配置或密钥。具体 Tool/Provider 的授权和健康状态在 Plan 生成及批准前按 required capability 检查。
`available` 仅表示能否新建 DeepSearch Run，计算固定为 `enabled && runtime_mode == "execute" && core_ready`；`reason_code` 返回首个未满足条件，不能用于隐藏或阻断既有 Run。

## 6. 持久化

只新增一张表：

```sql
CREATE TABLE deepsearch_requirement_versions (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  request_key TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  derived_from_requirement_version_id TEXT,
  schema_version TEXT NOT NULL,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(run_id, version),
  UNIQUE(run_id, request_key),
  FOREIGN KEY(run_id) REFERENCES agent_runs(id) ON DELETE CASCADE
);
```

必要时为 `(run_id, version DESC)` 增加普通索引。其余数据继续使用现有存储：

- ProblemGraph 冻结在 `skill_plans.payload`。
- Evidence Manifest Artifact ID/hash、Coverage、Review、revision count、finalization stage 和各阶段 hash 写入同一个 Plan payload。
- 节点结果继续使用现有 Skill Node Result 存储。
- 每个 Plan 版本和最终报告使用现有 Artifact 表保存 sealed 快照；当前 `skill_plans.payload` 仍是执行真相源。
- `AgentRun.output_text` 只是 sealed Report Artifact 的展示投影，不能作为报告权威副本或完成依据。
- 事件继续写 `agent_run_events`。

DeepSearch Artifact 只使用现有 `artifacts` 表，`artifact_type` 与 `schema_version` 固定映射：

| `artifact_type` | `schema_version` | 允许的创建/转移 |
| --- | --- | --- |
| `deepsearch_plan_snapshot` | `deepsearch-plan-snapshot-v1` | `absent -> SEALED` |
| `deepsearch_tool_evidence` | `deepsearch-tool-evidence-v1` | `absent -> SEALED` |
| `deepsearch_user_evidence` | `deepsearch-user-evidence-v1` | `absent -> SEALED` |
| `deepsearch_knowledge_evidence` | `deepsearch-knowledge-evidence-v1` | `absent -> SEALED` |
| `deepsearch_evidence_manifest` | `deepsearch-evidence-manifest-v1` | `absent -> SEALED` |
| `deepsearch_report` | `deepsearch-report-v1` | `absent -> STAGING -> SEALED | FAILED` |

表中的序列化状态仍使用现有小写枚举值。DeepSearch 对 Artifact lineage 的映射固定为：`requirement_version_id` 使用真实 Requirement version row ID，`plan_version_id="{plan_id}:v{plan.version}"`；节点 Artifact 同时写入 `attempt_id="{node_id}:attempt:{attempt}"` 和冻结 Plan 中从 1 开始的 `step_number`。禁止把可变状态或 Provider 返回顺序塞进这些身份字段。

Artifact ID 按 kind 分域确定性生成：Plan Snapshot 使用 `run/plan/version/kind`；Tool Evidence 使用 `run/plan/version/node/attempt/operation_key/source_id/kind`；user/knowledge Evidence 使用 `run_id/requirement_version_id/kind/frozen_message|upload|resource_id/version/frozen_content_hash`；Manifest/Report 使用 `run/plan/version/stage/revision_count/kind`。因此同一 Run/Requirement 可幂等复用同一冻结材料，其他 Run 或 Retry 必然得到不同 ID。对 insert-only Artifact 和同状态重放，相同 ID、状态、canonical bytes 和 lineage 时返回原 Artifact，任一字段不同即 fail closed。Report 是唯一例外：只允许以预期旧状态为条件执行 `absent -> STAGING`、`STAGING -> SEALED` 或 `STAGING -> FAILED` CAS，因此合法 seal 可以把同一 ID 的空正文替换为最终 canonical bytes；到达 SEALED 或 FAILED 后只能接受内容、状态和 lineage 完全相同的幂等重放，其他变化一律拒绝。任何重试都不得产生两个有效 Report Artifact。

### 6.1 Verified Artifact 存取边界

当前 `SQLiteStore.save_artifact()` 明确拒绝 `verification_state != null` 的 v1 Artifact，而公开 Artifact 路由固定使用 `V2ArtifactHistoryReader`，该 Reader 又会把 v1 verified row 判为损坏。因此 DeepSearch 不得直接复用或放宽这两个历史入口；先建立通用 v1 Artifact seam：

```text
agentmesh/artifacts.py
  V1VerifiedArtifactStore     v1 verified insert/CAS；可加入调用方事务
  V1ArtifactReader            v1 legacy 与 v1 DeepSearch verified 的只读校验
  ArtifactAccessError         稳定错误码

agentmesh/routes/artifacts.py
  按持久化 Run 版本和 Artifact 状态分发 Reader
```

`agentmesh/artifacts.py` 内维护冻结的 `DeepSearchArtifactSchemaRegistry`，按上表的 `(artifact_type, schema_version)` 精确映射内容 DTO：Plan Snapshot → `DeepSearchPlanSnapshotV1`，三类 Evidence → `TrustedEvidenceEnvelopeV1` 并固定各自 `origin_type`，Manifest → `DeepSearchEvidenceManifestV1`，Report → `DeepSearchReportV1`。所有 DTO 都使用 `extra=forbid`；不存在“任意 canonical JSON”回退。

`DeepSearchPlanSnapshotV1` 固定包含 `schema_version/run_id/requirement_version_id/requirement_content_hash/plan_id/plan_version/plan_content_hash/frozen_plan`；`frozen_plan` 必须逐字段等于 §6.2 的 `plan_content_hash` 投影，不包含节点状态、结果、预算或 finalization 字段。

`V1VerifiedArtifactStore` 只接受 `orchestration_version` 的列值和 Run payload 都为 `v1`、`planning_mode=deepsearch`、schema 在上述 Registry、owner 和完整 lineage 匹配的 Artifact。Plan/Evidence/Manifest 的 `absent -> SEALED` 直接写入，以及 Report 的 `STAGING -> SEALED` 转移，必须严格解析内容 DTO，并把 DTO 内嵌的 Run/Requirement/Plan/Node/Attempt、origin 和内容引用与外层 Artifact、数据库权威记录逐字段交叉校验。Report 的 `absent -> STAGING` 和 `STAGING -> FAILED` 只校验外层 artifact type/schema、owner、完整 lineage、允许的状态转移及其数据库权威记录；这两个状态的正文必须为空，也不得尝试解析 `DeepSearchReportV1`。Plan/Evidence/Manifest 只能 insert-only 直接封存；Report 只能执行 `absent -> STAGING -> SEALED | FAILED` CAS；SEALED 或 FAILED 均不可复活或覆盖。它必须允许复用调用方已经打开的 SQLite transaction，使 Plan Snapshot、Evidence batch、Manifest stage 和 terminal commit 保持真正的单事务，而不是嵌套提交。

Artifact GET 的分发矩阵固定为：

| 持久化身份 | Reader |
| --- | --- |
| Run 列和 payload 都为 `v1`，Artifact 列和 payload 的 `verification_state` 都为空 | `V1ArtifactReader` legacy 分支，保持现有未验证读取语义 |
| Run 列和 payload 都为 `v1`，`planning_mode=deepsearch`，Artifact 为 allowlist 中的 verified schema | `V1ArtifactReader` verified 分支 |
| Run 列和 payload 都为 `research-v2` | 原封不动的 `V2ArtifactHistoryReader` |
| 列/payload 不一致、未知 verified v1 schema、其他 Runtime | fail closed，不尝试猜测 Reader |

`V1ArtifactReader` 先校验 owner、持久化身份、外层 artifact type/schema/lineage 以及 payload 与索引列的一致性，再判断状态；`STAGING/FAILED/PURGED` 必须立即分别返回 `409 artifact_not_ready`、`409 artifact_invalid`、`409 artifact_purged`，不得读取、解析或返回正文。只有 `SEALED` verified Artifact 才继续校验 UTF-8 byte size、SHA-256，严格解析 JSON、验证 canonical JSON 和 Schema Registry DTO，并让内嵌 lineage/origin 与外层和数据库记录逐字段一致，然后返回正文和 hash header。Finalizer 读取 Manifest 时还要逐项解析其所引用的 Node Result、Evidence Item、SEALED Evidence Artifact 和 Source。aggregate 和前端不得投影任何非 SEALED 正文；非 owner 始终为 `404`，SEALED 内容完整性失败返回 `409 artifact_integrity_failed`；读取保持纯读，不得在 GET 中修复或改写数据。v1 legacy 响应保持现有正文和无 hash header 语义。`V2ArtifactHistoryReader` 继续位于历史模块、完全只读且行为不变；DeepSearch 模块不得 import 它。

新增 Store 方法：

```text
get_active_deepsearch_requirement(run_id)
append_deepsearch_requirement_and_transition(...)
save_deepsearch_plan_and_transition(...)
save_deepsearch_evidence_batch(...)
compare_and_swap_deepsearch_finalization(...)
list_recoverable_deepsearch_runs(...)
reserve_deepsearch_budget(...)
settle_deepsearch_budget(...)
expire_deepsearch_run_if_needed(...)
```

写入规则：

1. 使用 `BEGIN IMMEDIATE` 完成 owner、Run 状态、expected Requirement/Plan version 校验和状态写入。
2. `request_key` 使用澄清请求的 `client_turn_id`；相同 key、相同 hash 返回原结果，相同 key、不同 hash 返回 `409`。
3. Requirement 新版本、Run 状态和事件在同一事务提交。
4. Plan、Run 的 `plan_id/status` 和事件在同一事务提交，禁止先保存 Plan 再单独更新 Run。
5. LLM 和 Tool 调用不得发生在 SQLite 事务内；先读取并固定输入快照，调用结束后以 CAS 提交。
6. 并发提交只允许一个 CAS 成功；失败者重新读取权威状态，不覆盖新版本。
7. 首期只保证状态变更 exactly-once，不承诺并发重试下的 LLM 调用 exactly-once；LLM 不得产生外部写副作用。
8. 不写入旧 `research_requirement_versions`，也不修改 `research-v2` 的存储投影。
9. 每次 Plan 创建或编辑时，在同一事务中写入 sealed `deepsearch-plan-snapshot-v1` Artifact。现有批准事务会把 `plan.version` 从 N 增加为 N+1，因此 DeepSearch 专用批准路径必须在同一事务中为批准后的 N+1 写入内容等价的新 sealed Snapshot，并冻结 `{plan_id, approved_version=N+1, plan_content_hash, artifact_id}`；执行、Evidence 和 finalization 全部引用 N+1，不能继续引用审批前快照。
10. Tool Gateway 在一个事务中写入本次调用的 Source、每条 Evidence Artifact 和关联元数据，全部成功后才返回可引用 ID；任一封存失败则整批回滚并使节点失败。节点结果、Manifest 和最终报告只能引用已经 sealed 且归属匹配的 Artifact。
11. 预算 reserve/settle、Artifact 字节计量和 stage recovery attempt 使用 `deepsearch_budget.version` CAS。逻辑结果幂等键与物理调用计费键必须分离：同一逻辑 stage 只有一个结果能提交，但每次真正的 Provider/Tool/Artifact 尝试都有独立 reservation。调用崩溃或 usage 缺失时按该物理尝试的预占上限结算；相同 `invocation_key` 的 settle 重放不重复扣费。
12. 所有 DeepSearch `agent_runs` 写入都必须在事务内重新读取最新 payload 后做字段级修改，禁止把事务外持有的旧 `AgentRun` 整体序列化回写；取消、过期、状态迁移和 finalization 必须保留最新 `deepsearch_budget.version/reservations`，预算 reserve/settle 也不得覆盖更新后的 status/error。

### 6.2 Canonical hash

所有结构化 hash 统一使用现有 `canonical_json_sha256()`；hash 字段自身、时间戳和运行时状态不进入对应投影：

```text
create_request_hash = hash(
  user_id, thread_id, client_turn_id, content,
  explicit_skill_name/skill_name, orchestration_mode, planning_mode,
  retry_of_run_id
)

clarification_request_hash = hash(
  run_id, expected_requirement_version, normalized_answers
)

requirement_content_hash = hash(schema_version, Requirement payload)
problem_graph_hash = hash(ProblemGraph excluding content_hash)

plan_content_hash = hash(
  schema_version,
  requirement_version_id / requirement_content_hash,
  problem_graph_hash,
  intent / routing_result / candidate_skill_ids,
  output contracts / required capabilities / structural gaps / preferred_order,
  frozen node definitions: id / Skill version+hash / dependencies /
  required / side_effect / input+output contracts / question_ids
)

evidence_manifest_hash = hash(validated Evidence Manifest)
synthesis_content_hash[revision] = hash(DeepSearchSynthesisV1)
report_content_hash = hash(DeepSearchReportV1 excluding report_content_hash)
```

节点 status、attempt、error、timestamps、Node Result、Evidence Item/Artifact ID、usage、`capability_check` 和其他运行期字段永远不进入 `plan_content_hash`。运行期结果只能改变 finalization 上下文，不能改变已经批准的 Plan 身份。

### 6.3 数据生命周期

- Requirement versions append-only；Run 的取消、失败或完成不会单独删除版本。
- Requirement、Plan 快照、ProblemGraph、节点结果、Source、Evidence、Review 和 Report 与父 AgentRun 同生命周期；活动 Run 的任何内容不得被清理。
- 首期继承现有 AgentRun 审计保留语义，不新增 DeepSearch 专用物理删除 API或后台清理 Worker。当前线程删除是软删除，不等于 purge，界面和文档不得宣称内容已物理擦除。
- 父线程对用户不可见后，DeepSearch aggregate 同样返回 `404`。未来若增加 AgentRun 硬删除，Requirement 子表随 Run 级联删除；Artifact 必须使用现有 `PURGED` tombstone 语义保留 hash/size 并清空正文。
- 事件、指标和应用日志不得重复保存 `AgentRun.input_text`、澄清答案、Evidence 正文、完整 Prompt 或 Provider 原始响应；异常只记录脱敏后的稳定错误码。
- 任何未来的清理任务都必须按 persisted `orchestration_version` 排除 `research-v2/research-v3` 历史数据。物理删除历史 Research 数据仍需独立授权。

## 7. 后端模块

新增窄模块：

```text
agentmesh/deepsearch/
├── __init__.py
├── admission.py       # 功能开关、Runtime 和 Provider 准入
├── artifact_budget.py # Artifact 写入与预算的原子边界
├── budget.py          # 全链路 reserve/settle 门面
├── contracts.py       # Requirement、ProblemGraph、Evidence、Review 契约
├── finalization.py    # Evidence gate、Review、一次修订与报告封存
├── modeling.py        # DeepSearch 结构化模型调用
├── planning.py        # Refiner、ProblemGraph Planner、Plan Compiler
├── recovery.py        # 单进程启动恢复协调器
├── reporting.py       # 确定性报告组装与渲染
├── service.py         # 只负责编排以上组件
└── tool_policy.py     # v1 Tool allowlist 与 fail-closed 校验

agentmesh/artifacts.py  # 通用 v1 legacy/verified Artifact 存取，不依赖 Research Runtime
agentmesh/routes/deepsearch.py
```

`planning.py` 暴露三个小接口：

```python
RequirementRefiner.refine(previous, user_request, answers)
ProblemGraphPlanner.build(requirement)
DeepSearchPlanCompiler.compile(requirement, graph, candidates, draft)
```

`DeepSearchPlanningService` 的控制流固定为：

```text
refine Requirement
  -> 有 blocking ambiguity：保存 Requirement，进入 waiting_clarification
  -> 无 blocking ambiguity：
       从 active Requirement 生成 canonical planning_input/hash
       -> TaskScenarioRouter
       -> SkillIntentAnalyzer
       -> ProblemGraphPlanner
       -> SkillCandidateRetriever(requirement, intent, graph)
       -> SkillPlanner.create_draft
       -> DeepSearchPlanCompiler
       -> 原子保存一个 SkillPlan
       -> waiting_plan_approval
```

Router、Intent、ProblemGraph、Retriever、Planner 必须消费同一个 `planning_input`，不能重新读取原始用户文本并忽略澄清答案。

现有执行器增加一个窄策略接口：

```python
class PlanFinalizationStrategy(Protocol):
    async def finalize(
        self,
        *,
        run_id: str,
        plan_id: str,
        expected_plan_version: int,
    ) -> PlanExecutionOutcome: ...
```

`BoundedDAGExecutor` 只负责节点调度和结果持久化。DeepSearch 节点全部终止后，由 DeepSearch Store 路径原子写入 `nodes_terminal`，再调用注入的 Strategy；standard 路径不写 DeepSearch stage，保留当前事件和终态事务：

- `StandardPlanFinalizer` 承接当前 Executor 内的 completion、Synthesis 和终态逻辑，确保 standard 路径行为不变。
- `DeepSearchFinalizer` 独占 DeepSearch 的 Evidence Manifest、Synthesis、Coverage、Review、一次修订、报告封存和终态写入。
- DeepSearch 路径中，除 `DeepSearchFinalizer` 外任何代码都不得把 Run 写成 `completed` 或 `partial`。
- Finalizer 禁止调用 Tool，只能读取本 Run 已持久化的节点结果和 sealed Evidence Artifact。

`DeepSearchFinalizer` 的固定流程：

```text
节点全部到达终态
  -> 生成并校验 Evidence Manifest
  -> Synthesis
     -> 普通预算可用：现有服务按 DeepSearchSynthesisV1 契约生成 claims
     -> 模型预算不足、原始调用和格式修复均失败：
        用 finalization reserve 生成 deterministic evidence digest
  -> EvidenceCoverageGate（含 claim 级引用检查）
  -> digest：持久化 Review outcome=not_run，确定性决定 partial/failed
  -> model synthesis 但 Review 预算不可用：
     持久化 Review outcome=not_run，确定性决定 partial/failed
  -> model synthesis 且 Review 可调用：ReportReviewer
     -> pass：封存并决定 completed/partial
     -> revise：基于同一批已验证 Evidence 重写一次；若修订 Synthesis 失败则改用 digest，
                否则重新做覆盖检查和审核
     -> block/error：持久化对应 Outcome，确定性决定 partial/failed
```

deterministic digest 不是 Model Synthesis 的“成功重试”，而是单独的安全降级产物；它必须进入对应的 `synthesis_v*_saved -> coverage_v*_checked -> review_v*_checked(not_run)` 检查点，禁止跳过 stage 或直接写 Report。

每个阶段在事务外计算、在事务内以 CAS 提交阶段产物和新 stage。重复 LLM 调用可以发生，但只有一个结果可以提交。最终报告先写入不可见的 STAGING Artifact；单个 `terminal_committed` 事务完成 Artifact seal、Plan link/hash、匹配的 SkillPlan/Run 终态、`output_text` 投影和最终事件，消除报告已可见但取消/失败先提交以及 Run 已终态但 Plan 仍为 running 的窗口。

### 7.1 启动恢复

应用初始化顺序调整为：先由通用 reconciler 处理 standard Run，但跳过 `planning_mode=deepsearch`；随后启动单实例 `DeepSearchRecoveryCoordinator`。Coordinator 在应用启动时、每 30 秒以及受管 Task 异常结束时扫描持久化的非终态 DeepSearch Run，并按以下矩阵处理：

| 状态 | 恢复行为 |
| --- | --- |
| 任意非终态且 `absolute_expires_at` 已到 | 原子取消为 `deepsearch_run_expired`，不再恢复 |
| `waiting_clarification` / `waiting_plan_approval` / `waiting_approval` | 绝对期限未到时再检查 `interaction_expires_at`；过期则原子取消，否则保持等待 |
| `planning` 且没有有效 Requirement | fail closed 为 `deepsearch_recovery_state_invalid` |
| `planning` 且已有有效 Requirement | 从固定 Requirement/hash 重跑无副作用规划，以 CAS 只保存一个 Plan |
| `running` 且 Plan 缺失、损坏或归属不匹配 | fail closed 为 `deepsearch_recovery_state_invalid` |
| `running` 且 Plan=`approved` | 处理 approve 已提交但 executor 尚未 claim 的窗口：调用现有 Plan claim CAS 转为 `running`，再进入节点调度 |
| `running` 且 Plan=`running`、节点为 `PENDING` | 重新计算依赖；满足时先 CAS 为 `READY` 再 claim |
| `running` 且 Plan=`running`、节点已为 `READY` | 直接调用现有 node claim CAS；不得只扫描 PENDING 而遗漏已持久化 READY |
| `running` 且节点在崩溃时为 `RUNNING` | 在同一 CAS 中把 attempt 和节点转为 `FAILED(error_code=external_outcome_unknown, completed_at=now)`，拒绝迟到提交且不自动重放；再进入同一调度循环传播依赖节点的 `SKIPPED`，并继续可独立执行的节点 |
| `running` 且所有节点已终态 | 从已提交的 `finalization_stage` 恢复 Finalizer |
| `running` 且 Plan 为其他状态或 Run/Plan 状态组合非法 | fail closed 为 `deepsearch_recovery_state_invalid` |
| 已取消或其他终态 | 不恢复，丢弃迟到结果 |

Coordinator 在单进程内保证同一 Run 只注册一个活动 Task；Store CAS 仍是最终所有权边界。每个可调用 Provider 的 planning/finalization stage 使用 `logical_stage_key=hash(run_id, requirement_version_id, plan_id|null, stage, revision_count, input_hash)` 标识唯一逻辑结果，再使用 `invocation_key=hash(logical_stage_key, physical_attempt)` 标识一次真实调用。调用前在一个 CAS 中把前一未结算尝试按上限结算、递增并持久化 `physical_attempt`、创建预算 reservation，然后才允许访问 Provider；stage 结果仍按 `logical_stage_key` 只提交一次。每个 stage 最多 3 次物理尝试，耗尽后原子失败为 `deepsearch_recovery_exhausted`。Tool 调用保持“一次已持久化 `tool_call_id` 对应一个 operation/invocation key”，外部结果未知时不创建下一尝试。功能开关关闭不阻止既有 Run 恢复；服务端有效 orchestration mode 不是 `execute` 时不恢复执行，必须由显式取消或重新启用处理。

同一个 `expire_deepsearch_run_if_needed(now)` 还必须在每个 DeepSearch mutation、Plan approve/reject、Tool approval/resume、Retry 创建和“线程是否已有活动 Run”的 claim 前惰性执行：任何状态先检查 absolute deadline，waiting 状态再检查 interaction deadline。GET、SSE、前端刷新和历史 Research reader 仍保持纯读，不能隐式恢复或续期。

必须复用：

- `TaskScenarioRouter`
- `SkillIntentAnalyzer`
- `SkillCandidateRetriever`
- `SkillPlanner`
- `validate_draft()` / `adjust_plan()`
- 现有 Plan `PATCH/approve/reject` API
- `BoundedDAGExecutor` 及其唯一节点调度/执行循环
- `SkillNodeResult`、现有 Synthesis 服务的调用/超时/错误处理（standard 的 `SkillSynthesisResult` 契约不复用于 DeepSearch）
- Tool Grant、审批、取消、事件和 owner 校验

主要修改文件：

```text
agentmesh/agent_run_identity.py
agentmesh/artifacts.py
agentmesh/canonical_json.py
agentmesh/models.py
agentmesh/store.py
agentmesh/app.py
agentmesh/routes/agent_runs.py
agentmesh/routes/artifacts.py
agentmesh/routes/deepsearch.py
agentmesh/routes/health.py
agentmesh/agent_runtime/models.py
agentmesh/agent_runtime/hooks.py
agentmesh/agent_runtime/service.py
agentmesh/agent_runtime/settings.py
agentmesh/skill_runtime/executor.py
agentmesh/skill_runtime/finalization.py
agentmesh/skill_runtime/plan_validation.py
agentmesh/skill_runtime/planner.py
agentmesh/skill_runtime/resources.py
agentmesh/skill_runtime/retrieval.py
agentmesh/tool_runtime/factory.py
agentmesh/tool_runtime/gateway.py
agentmesh/tool_runtime/mcp.py
agentmesh/tool_runtime/deepsearch.py
agentmesh/task_routing/catalog.py
agentmesh/task_routing/compiler.py
agentmesh-demo/src/features/deepsearch/
agentmesh-demo/src/components/workspace/Composer.tsx
agentmesh-demo/src/components/workspace/ConversationNav.tsx
agentmesh-demo/src/pages/Workspace.tsx
.env.example
```

DeepSearch 代码不得 import `agentmesh.research_orchestration` 下任何 v2/v3 历史模块。现有 executor 只增加两个窄 seam：注入 finalization strategy，以及从持久化 Plan 重新进入同一调度循环的恢复入口。恢复入口在 Run=`running`、Plan=`approved` 时先调用现有 Plan claim CAS；Plan=`running` 时复用现有依赖计算和 node claim，已持久化的 `READY` 节点必须直接 claim，不能只重算 `PENDING`。`DeepSearchRecoveryCoordinator` 只负责扫描、单 Task 所有权和调用该入口，不得复制 node runner、依赖调度或建立第二套执行循环。

## 8. Skill 选择和 Plan 规则

### 8.1 Skill 选择

1. 先完成 Requirement，再生成唯一 canonical `planning_input`，按 Router/Intent → ProblemGraph → Retriever → Planner 的固定顺序执行。
2. 只从当前用户可见、已启用、版本可解析且资源就绪的 Skill 中选择。
3. 模型只能在 Retriever 返回的 shortlist 中选择 Skill；返回未知 ID 立即拒绝。
4. Skill version、content hash、Tool 要求和权限在 Plan 中冻结，批准前再次校验。
5. Requirement 需要公开网络证据时，Plan 必须包含真实、健康且已授权的 Web Research 能力；未接通时 fail closed。
6. DeepSearch v1 的 Tool allowlist 固定为 `web_research`；其他内置 Tool 和 MCP 即使已经授权也不得进入 Plan。
7. `planned` 或缺少真实 adapter 的能力不得冒充可执行 Skill。

Plan 定义冻结 required capability 和结构性 gap；另用不进入 `plan_content_hash` 的 `capability_check` 记录稳定 gap code、检查时间和 Tool/Provider 标识。健康状态不是永久事实，创建 Plan、批准和节点启动前都重新检查；批准事务可更新 `capability_check` 但不能改变 Plan 身份。批准后 Provider 失效时调用确定性终态函数，不得切换到 fake/fallback 或普通 LLM。

### 8.2 单 Plan

- 每次 Requirement 版本只产出一个通过校验的当前 Plan。
- 用户继续使用现有 Plan 编辑、排序、确认和拒绝能力。
- 编辑后递增 `plan.version`，重新执行全部 DeepSearch 校验；旧版本以 sealed Plan Snapshot Artifact 保存，仅用于审计，永不参与执行。
- 不新增 candidate selection 状态、候选轮播或 depth/speed 二选一接口。

### 8.3 DeepSearch Plan 校验

在现有 `validate_draft()` 基础上增加：

1. 每个 required ProblemQuestion 至少由一个 required 节点覆盖。
2. `question_ids` 必须存在于当前 ProblemGraph。
3. 每个 success criterion 必须被 required question 和节点共同覆盖。
4. 每个节点只能引用 shortlist 中冻结版本的 Skill。
5. Requirement hash、ProblemGraph hash 和 Plan 引用必须一致。
6. DAG 无环，节点数继续不超过 6，依赖深度不超过 4，并发继续服从现有上限 3。
7. 输入绑定、输出契约、Knowledge 绑定、Tool Grant 和 side effect 必须合法；每个 requested Tool 都必须解析为内置 `web_research` 的当前真实 `ToolDefinition`，且 `ToolDefinition.side_effect=read`。其他内置 Tool 和 MCP 一律拒绝。
8. 必需能力缺失时在 Plan 中显示 capability gap，并禁止批准；不能删除节点后伪装完成。
9. 结构化规划输出失败时只允许一次格式修复，不允许无限重试模型。
10. 所有节点 side effect 必须是 `READ` 或 `DRAFT`；其他类型立即拒绝。

### 8.4 执行不变量

- Plan 未批准，Tool 调用数必须为 0。
- 继续使用现有节点 claim/CAS、依赖跳过、最多一次安全重试和取消语义。
- 未知外部调用结果不得自动重试，避免重复副作用。
- Skill 节点只允许 `READ/DRAFT`，但 `DRAFT` 只代表生成本地草稿，不授权写型 Tool。Plan 编译、Store transition、批准和节点启动均重验 `web_research` allowlist；`AgentMeshToolFactory` 与 `ToolGateway` 在调用前再次校验。MCP factory/list/call 对 DeepSearch 全部 fail closed。审批通过、模型选择或过期的 Plan 元数据均不能覆盖该门禁。
- DeepSearch 不执行任何外部写型 Tool，因此不承担外部写入 exactly-once 承诺；即使 read Tool 的外部结果未知，也按未知结果处理而非自动重放。
- Synthesis 只能引用本 Run 当前批准 Plan 的节点结果、Source 和 sealed Evidence Artifact。

## 9. 多轮澄清 API

新增两个端点：

```text
GET  /api/agent/runs/{run_id}/deepsearch
POST /api/agent/runs/{run_id}/deepsearch/clarify
```

### 9.1 查询状态

`GET` 返回 `DeepSearchStateResponse`。它用于首次加载、刷新恢复和冲突后的重新同步。非 owner 返回 `404`；非 DeepSearch Run 返回 `409`。

### 9.2 提交澄清

请求：

```json
{
  "client_turn_id": "clarify_002",
  "expected_requirement_version": 2,
  "answers": {
    "q_2_1_a41d8c22": "中国大陆",
    "q_2_2_72c46f90": "最近 24 个月"
  }
}
```

规则：

- 每项文本答案 trim 后为 `1..2000` 字符，全部规范化答案 JSON 不超过 8000 字节。
- 只接受 expected Requirement version 中存在的问题 ID；必答问题缺失、值为空、问题 ID 未知、类型错误或答案超限时返回 `422`，不创建版本。
- `expected_requirement_version` 过期时必须先返回 `409 deepsearch_requirement_version_conflict`，不得先按新版本问题集返回 `422`。
- 相同 `client_turn_id` 和请求 hash 重放时不重复调用 Refiner、也不追加 Requirement；响应返回当前服务端权威 aggregate（可能已因后续请求推进），相同 key 不同内容返回 `409`。客户端需要核对 `active_requirement.version`，不得把重放响应假定为历史快照。
- 有下一轮阻塞问题时返回 `202`，Run 仍是 `waiting_clarification`。
- Requirement 完整时返回 `202`，服务端生成 ProblemGraph 和单一 Plan，Run 进入 `waiting_plan_approval`。
- 端点只能更新 Requirement 和触发规划，不能绕过 Plan 确认执行 Tool。

服务端处理顺序固定为：

```text
owner / planning_mode / Run status 校验
-> 规范化 answers，计算 clarification_request_hash
-> BEGIN IMMEDIATE
-> request_key 已存在：同 hash 返回原结果，不同 hash 返回 409
-> 校验 active version == expected version；否则返回 409
-> 校验当前版本问题集、必答项和值
-> 固定输入快照并结束事务
-> 事务外调用 Requirement Refiner
-> 以 expected version/status CAS 提交新 Requirement、Run 和事件
-> CAS 失败时重新检查幂等记录，再返回当前 version 的 409
```

409 响应至少包含稳定 `code` 和 `current_requirement_version`。客户端收到后丢弃旧表单并重新 GET aggregate，不能自动重放旧答案。

Plan 生成后继续使用现有接口：

```text
GET   /api/agent/runs/{run_id}/plan
PATCH /api/agent/runs/{run_id}/plan
POST  /api/agent/runs/{run_id}/plan/approve
POST  /api/agent/runs/{run_id}/plan/reject
```

现有 PATCH 和状态转移都会递增 `plan.version`。DeepSearch approve 以请求中的 N 做 CAS，成功响应返回批准后的 N+1；该事务同时封存 N+1 Snapshot、更新 `approved_plan_artifact_id` 并把 Run 置为 `running`。Executor 只能接收响应中的批准版本，不能继续持有批准前 N 的对象。

进度继续使用现有 Run/Event 查询，不新增 `/control-tasks`。

### 9.3 Retry

现有 Run Retry API 对 DeepSearch 使用以下确定矩阵；所有允许的 Retry 都创建新 Run，并再次执行当前准入检查：

| 原 Run 结果 | Retry 行为 | `retry_disposition` |
| --- | --- | --- |
| `deepsearch_clarification_unresolved` | 拒绝 `/retry`，返回 `409 deepsearch_goal_revision_required`；用户修改目标并从第 0 轮新建 | `revise_goal` |
| Requirement 尚未形成或输入本身非法 | 不允许复制上下文，修改目标后新建 | `revise_goal` |
| 明确标记为瞬态的规划错误 | 复制最后一个已验证 Requirement payload 为新 Run 的 v1，重新生成 Graph/Plan | `retry_run` |
| 可重试的执行或 finalization 基础设施错误 | 复制已验证 Requirement payload，重新生成 Graph/Plan；不复用旧结果/Evidence | `retry_run` |
| `external_outcome_unknown`、权限错误、Evidence 完整性错误 | 禁止自动 Retry | `none` |

前端只按服务端 `retry_disposition` 展示动作，不自行解释 `error_code`。修改目标并新建必须使用新的 `client_turn_id`，不得继承已经耗尽的澄清轮次。

`retry_disposition` 由 Run error code、节点 cause codes 和 Finalizer cause code 按以下优先级计算，同一 Run 只能得到一个结果：

```text
none:
  completed / cancelled / rejected
  deepsearch_interaction_expired / deepsearch_run_expired
  permission_denied / external_outcome_unknown
  deepsearch_tool_policy_violation
  deepsearch_evidence_integrity_failed
  deepsearch_recovery_state_invalid

retry_run:
  deepsearch_planning_transient
  deepsearch_execution_transient
  deepsearch_report_persistence_failed
  deepsearch_recovery_exhausted

revise_goal:
  deepsearch_clarification_unresolved
  deepsearch_planning_failed
  deepsearch_budget_exhausted
  deepsearch_delivery_unavailable
  deepsearch_required_coverage_incomplete
  deepsearch_review_not_passed

其他或未知 cause code：none
```

高优先级 `none` 原因（完整性、权限、unknown external outcome）不得被 optional-node 等汇总 error code 覆盖。`retry_of_run_id` 是新 Run 幂等身份的一部分；相同 key 指向不同原 Run 必须返回 409。

## 10. Evidence、Review 和最终状态

### 10.1 Evidence 覆盖门禁

Evidence gate 是确定性校验，至少验证：

1. 当前 Plan 所有 required 节点已进入允许的终态。
2. 每个 required ProblemQuestion 有对应节点结果。
3. 每个 required success criterion 有结果和可追溯 claim 覆盖。
4. 当前 revision 的 DeepSearch Synthesis claim ID 唯一且可重算；其 `node_result_ids`、`evidence_item_ids`、`source_ids` 和 Artifact 引用真实存在，且属于同一 Run/Plan；未知、重复、跨 revision claim 或外部事实 claim 缺少 `evidence_item_ids` 时失败。
5. 外部事实所引用的来源来自真实 Tool，包含规范化 reference、抓取时间和内容 hash。
6. Artifact 需要封存时必须是 `sealed`，hash 和归属匹配。
7. 冲突证据、低置信度和缺失来源必须进入 limitations，不能在汇总时被抹掉。
8. 来源数量只能作为诊断指标，不能单独证明 Evidence 充分。
9. `executive_summary_claim_ids` 和每个 section 的 `claim_ids` 只能由服务端引用已通过覆盖检查的 claim；覆盖 required question/criterion 的 claim 必须至少出现在一个 section。报告不得包含 claims、结构化 limitations 和固定模板之外的事实 prose。

发现未知引用、跨 Run 引用、hash 不一致、LLM 自述冒充 Tool Evidence 或缺失必需证据时 fail closed。

### 10.2 Report Review

Review 分两层：

1. 确定性检查：契约、章节、覆盖、引用、limitations、长度和归属。
2. 结构化语义审核：检查是否回答 Requirement、结论是否受 Evidence 支持、是否存在明显矛盾或过度推断。

Reviewer 只能返回 `pass`、`revise` 或 `block`。`revise` 最多触发一次 Synthesis 修订，并且只能使用已验证 Evidence；Evidence 本身不足时不能靠改写补齐。修订后重新执行确定性检查和 Review，第二次仍不通过则进入 `partial` 或 `failed`。

### 10.3 完成判定

生成 partial 前，服务端先构造 `safe_claims`：从当前 revision 已通过确定性引用校验的 claims 中，剔除有效 Review 指出的全部 `unsupported_claim_ids` 和 `contradictory_claim_ids`，再重新计算 question/criterion Coverage，并重新生成 summary、sections、sources 和 limitations。被剔除的 claim 及其仅有引用不得出现在 Report 或 `rendered_text`；如果 Review verdict 为 block 但没有合法 claim IDs，则只能依据确定性 gap 生成不含争议事实的 partial，否则 failed。

`safe_partial_report` 是一个确定性谓词，仅在同时满足以下条件时为真：

- 至少一个 required 节点有已验证结果；
- 已存在通过 v1 Reader 校验的 sealed Evidence Manifest；
- `safe_claims` 非空，且至少一个 required ProblemQuestion 被其中的可信 Evidence 覆盖；
- 确定性 partial renderer 能生成合法、非空且明确标注缺口的报告；
- 所有没有可信引用、被 Review 标记 unsupported 或 contradictory 的事实 claim 已删除；
- 专用 `finalization_reserve` 尚可封存不超过 262144 bytes 的报告，或同一逻辑 Report Artifact ID 已存在可提交的 STAGING Artifact。

终态由纯函数按下表自上而下匹配，禁止调用方自行解释 `partial/failed`：

| 条件 | Run 状态 | `error_code` | 报告 |
| --- | --- | --- | --- |
| 用户取消 | `cancelled` | `null` | 不新增报告 |
| 用户拒绝 Plan | `rejected` | `null` | 不新增报告 |
| 人工交互超过 24 小时 | `cancelled` | `deepsearch_interaction_expired` | 不新增报告 |
| Run 超过 7 天绝对生命周期 | `cancelled` | `deepsearch_run_expired` | 不新增报告 |
| 3 轮后仍有阻塞歧义 | `failed` | `deepsearch_clarification_unresolved` | 无 |
| Requirement/Graph/Plan 无法形成 | `failed` | `deepsearch_planning_failed` | 无 |
| 瞬态 planning 调用达到恢复上限 | `failed` | `deepsearch_planning_transient` | 无 |
| 无未知外部结果的执行基础设施错误达到恢复上限 | `failed` | `deepsearch_execution_transient` | 无 |
| 单 stage 恢复达到 3 次 | `failed` | `deepsearch_recovery_exhausted` | 无 |
| 恢复时缺少有效 Requirement/Plan 或归属损坏 | `failed` | `deepsearch_recovery_state_invalid` | 无 |
| 实际 Tool side effect 非 `read`、定义缺失或 invocation lineage 不完整 | `failed` | `deepsearch_tool_policy_violation` | 无 |
| 跨 Run、归属、hash、权限或 Evidence 完整性失败 | `failed` | `deepsearch_evidence_integrity_failed` | 无 |
| Report Artifact 连续 3 次保存失败 | `failed` | `deepsearch_report_persistence_failed` | 无 |
| 预算耗尽且不满足 `safe_partial_report` | `failed` | `deepsearch_budget_exhausted` | 无 |
| required 覆盖或交付缺失且不满足 `safe_partial_report` | `failed` | `deepsearch_delivery_unavailable` | 无 |
| Review 未通过且不满足 `safe_partial_report` | `failed` | `deepsearch_delivery_unavailable` | 无 |
| 预算耗尽且满足 `safe_partial_report` | `partial` | `deepsearch_budget_exhausted` | sealed partial |
| required 节点、问题、criterion 或 Evidence 缺失，且满足 `safe_partial_report` | `partial` | `deepsearch_required_coverage_incomplete` | sealed partial |
| Review block、第二次 revise、timeout 或 Schema 修复失败，且满足 `safe_partial_report` | `partial` | `deepsearch_review_not_passed` | sealed partial |
| 只有 optional 节点失败或跳过，且满足 `safe_partial_report` | `partial` | `deepsearch_optional_node_failed` | sealed partial |
| optional 节点失败且不满足 `safe_partial_report` | `failed` | `deepsearch_delivery_unavailable` | 无 |
| 使用确定性 Synthesis fallback，且满足 `safe_partial_report` | `partial` | `deepsearch_synthesis_fallback` | sealed partial |
| Synthesis 失败且不满足 `safe_partial_report` | `failed` | `deepsearch_delivery_unavailable` | 无 |
| 所有节点成功、criteria 满足、Coverage 通过、Review pass、报告封存 | `completed` | `null` | sealed complete |
| 可恢复错误且恢复/重试预算未耗尽 | `running` | `null` | 不发布 |

`partial` 必须拥有 sealed partial Report Artifact，并列出未覆盖问题、失败节点、证据缺口和限制；`failed` 不得发布研究结论。`output_text` 非空、LLM 声称完成或来源数量达到阈值都不能触发 `completed`。

## 11. 前端交互

### 11.1 入口与阶段

在现有 Composer 增加显式“DeepSearch”模式开关。提交时写 `planning_mode=deepsearch`；关闭时仍是 `standard`。入口只消费 Bootstrap 的 `deepsearch_availability`：不可用时禁用并显示稳定原因，不调用管理员 Provider 健康 API。前端不根据输入文本自动切换模式，也不提供已退役 Research 版本选择器。

DeepSearch 在同一个 Workspace 中展示：

```text
需求理解
  -> 多轮澄清
  -> 单一 Plan 编辑/确认
  -> Tool 审批与 DAG 执行
  -> Evidence/Review 状态
  -> 结构化文本报告
```

具体行为：

- 需求区展示目标、范围、约束、交付物、成功标准和显式 assumptions；Plan 生成后 assumptions 标记为只读，修改目标必须新建 Run。
- 澄清区按轮次展示当前理解、本轮问题和历史答案；提交后允许继续出现下一轮，刷新后可恢复。
- 每轮最多 5 问，显示“第 N/3 轮”，阻塞问题与可采用默认值的问题有清晰区别。
- Plan 区只显示一个当前版本，复用现有 Skill 节点、依赖、顺序编辑和确认能力；存在 required capability gap 时禁用批准，并显示可处理的稳定原因。
- 执行区复用现有 DAG 进度、审批、取消和错误反馈；操作能力由服务端状态决定。
- 报告区只渲染 sealed Report Artifact 的服务端投影，显示结构化文本、来源引用、Evidence 覆盖、Review 结论和 limitations；partial 必须有明确标签。
- 终态操作只依据 `retry_disposition` 展示“以新 Run 重试”“修改目标并新建”或无动作。

### 11.2 视觉策略

保留 ai-x 的阶段顺序、当前理解、多轮澄清、显式确认和运行反馈等交互语义，但使用 AgentMesh 的 Workspace 壳、响应式布局、公共组件和视觉 token。不得复制 ai-x 的导航、独立暗色主题、warm-paper/serif 报告或像素级 CSS。

首期不展示：

- 候选 Plan 轮播；
- depth/speed 方案卡；
- PDF/ZIP 导出；
- 截图、视觉捕获或图片对比；
- research-v2 的可变操作入口。

### 11.3 前端代码边界

- `Workspace.tsx` 根据 `run.planning_mode` 展示 DeepSearch，而不是根据 `orchestration_version` 猜测。
- 新建独立 `features/deepsearch/` 状态适配层，消费本方案的 DeepSearch/Plan/Run Event API。
- 只复用 Workspace、Skill Plan、DAG 进度和 Synthesis 等通用组件；不复用已删除的 Research Workbench 或其 aggregate/candidate 状态。
- `research-v2` 保留隔离的历史只读 renderer，不提供修改、恢复或重跑。
- 409 后重新读取权威状态，不盲目重放用户命令。
- `AGENTMESH_DEEPSEARCH_ENABLED` 关闭后隐藏新建入口，但通过既有 URL 恢复的 DeepSearch Run 仍按持久化状态完整展示；停止活动 Run 必须使用显式取消。

### 11.4 可访问性

- 问题与输入建立明确的 `label`、错误和帮助文本关联。
- 状态迁移后聚焦新阶段标题。
- DAG 进度使用节制的 `aria-live`，颜色之外同时提供图标和文本。
- 所有澄清、编辑、确认、审批和取消操作可使用键盘完成。
- 遵守 `prefers-reduced-motion` 并保留可见焦点。

## 12. 预算、准入和故障语义

### 12.1 固定预算

首期预算由服务端 `DeepSearchBudgetV1` 固定，不允许客户端扩大：

| 项目 | 上限 |
| --- | ---: |
| 人工交互 TTL | 最近一次服务端提问或 Plan 生成后 24 小时 |
| Run 绝对生命周期 | 7 天 |
| 累计活动计算时间 | 1800 秒 |
| LLM 调用 | 64 次 |
| 累计模型 token | 250000 |
| Tool 调用 | 24 次 |
| Plan 节点 / DAG 深度 / 并发 | 6 / 4 / 3 |
| 单次普通 LLM / Research 节点 timeout | 120 秒 / 180 秒 |
| Evidence item | 60 条 |
| 单条 / 合计 Evidence excerpt | 8192 / 524288 bytes |
| 单个 / 单 Run Artifact | 1048576 / 10485760 bytes |
| Evidence Manifest canonical JSON | 131072 bytes |
| 最终 Report Artifact canonical JSON | 262144 bytes |
| Manifest / Report 单次确定性构建+保存 timeout | 30 秒 |
| Manifest / Report Artifact 保存 | 各最多 3 次 |
| Coverage / deterministic digest | 每次 15 秒（最多 2 次）/ 30 秒（最多 1 次） |
| Finalization 恢复与检查点总预算 | 60 秒 |
| 每个 planning/finalization stage 恢复 | 最多 3 次 |
| 结构化输出格式修复 / 报告内容修订 | 各 1 次 |

人工等待期间 `deadline_at=null`，不消耗活动计算时间。每次进入 `waiting_clarification`、`waiting_plan_approval` 或 `waiting_approval` 都把 `interaction_expires_at` 重置为 24 小时后；成功 Plan PATCH 后仍在 waiting 状态，也必须重置 TTL。离开 waiting gate 时清空该值并进入计算。

开始计算操作时按该操作 timeout 预占活动秒数；LLM 调用同时预占一次调用和配置的最大 token，Tool 调用预占一次调用，Evidence/Artifact 写入预占 item 和 bytes。成功后以实际 usage 结算，进程崩溃、Provider usage 缺失或 operation 结果未知时按预占上限结算。普通操作不能消费 `finalization_reserve`；预算不足以完成普通操作时立即进入终态判定，不能先透支再补记。

预算不能只停留在模型字段或 Finalizer 内。`DeepSearchBudgetMeter` 是唯一 reserve/settle 门面，必须包住所有真实消耗点：Requirement Refiner、ProblemGraph/Plan LLM、`skill_runtime/planner.py`、节点 `agent_runtime/service.py::_run_streamed`、`skill_runtime/synthesis.py`、Review/Revision、`ToolFactory -> ToolGateway.invoke` 以及 v1 verified Artifact 写入。任何 Provider client、Tool handler 或 Artifact writer 都不能在成功 reservation 之前被调用。

LLM 以 Provider 返回 usage 结算 call/token 和单调时钟耗时；usage 缺失、timeout、进程异常或结果是否提交不明时按该 `invocation_key` 的 reservation 上限结算。每次格式修复或崩溃恢复调用都递增 `physical_attempt` 并使用新的 `invocation_key`，不能复用逻辑 stage key 逃避计费。Tool 以已持久化的 `DeepSearchToolInvocationV1.operation_key` 同时作为单次 `invocation_key` 预占，handler 返回后结算；`AgentMeshRunHooks` 对 DeepSearch 只记录事件，不再调用通用 `consume_agent_run_tool_call()` 重复扣费，standard Run 维持原行为。Artifact 在写入前根据 canonical bytes 精确预占 item/bytes；每次真实保存尝试有独立 `invocation_key`，写入与 settle 同事务完成，而 logical Artifact ID 保持不变。若发现完全相同且已封存的 Artifact，幂等命中按新增 item/bytes 为 0 结算；内容或 lineage 不同则冲突。CAS/settle 重放按同一 `invocation_key` 重读，不重复扣费。所有 wrapper 都必须在 `planning_mode=standard` 时成为无行为变化的旁路。

首期不承诺人民币金额预算。用户提出不可执行的金额上限时，Plan 写入 `monetary_budget_not_enforceable` capability gap 并禁止批准，不得假装已经实施成本控制。

### 12.2 准入生命周期

| 操作 | 检查 `AGENTMESH_DEEPSEARCH_ENABLED` |
| --- | --- |
| 新建 DeepSearch Run | 是 |
| 为终态 Run 创建 Retry Run | 是 |
| 已接收请求的幂等重放 | 否 |
| GET aggregate/events | 否 |
| clarify、Plan 编辑/批准/拒绝 | 否 |
| Tool 审批、取消、恢复、finalization | 否 |

普通权限、Tool Grant、Catalog/Skill hash、required Provider 和服务端有效 orchestration mode 仍在各自操作点重新校验。rollout 开关不是安全取消开关；需要停止既有 Run 时走显式取消。

### 12.3 故障语义

| 阶段 | 故障 | 确定行为 |
| --- | --- | --- |
| Run 创建 | DeepSearch 未启用 | `409 deepsearch_disabled`，不创建 Run |
| Run 创建 | effective mode 非 execute | `409 deepsearch_execution_unavailable`，不创建 Run |
| Run 创建 | Runtime/模型/Planner 不可用 | 对应稳定 `503`，不降级为普通 LLM |
| 澄清 | 缺失、未知或非法答案 | `422`，Requirement 版本不变 |
| 澄清 | stale expected version | `409 deepsearch_requirement_version_conflict`，客户端重新读取 |
| 澄清 | 3 轮后仍有阻塞歧义 | `failed/deepsearch_clarification_unresolved`，零 Tool 调用 |
| 人工等待 | 24 小时无操作 | `cancelled/deepsearch_interaction_expired`，关闭开放审批 |
| 任意阶段 | Run 达到 7 天绝对生命周期 | `cancelled/deepsearch_run_expired`，不再恢复 |
| Requirement/Plan | 结构化输出格式非法 | 允许一次格式修复；仍失败则 `failed/deepsearch_planning_failed` |
| Planning/恢复 | 瞬态基础设施错误达到 stage 恢复上限 | `failed/deepsearch_planning_transient` 或 `failed/deepsearch_recovery_exhausted` |
| 恢复 | Requirement/Plan 缺失、损坏或归属不匹配 | `failed/deepsearch_recovery_state_invalid` |
| Skill 选择 | 模型返回 shortlist 外 Skill | 拒绝 Plan，不执行 |
| Tool 就绪度 | required adapter、授权或 Provider 不可用 | Plan 保持待批准，显示 gap，服务端和前端都禁止批准 |
| Tool 调用 | 定义已变为非 read、MCP side effect 未知或 invocation lineage 不完整 | handler 前失败为 `deepsearch_tool_policy_violation`，不允许审批绕过 |
| DAG | read/draft 节点的已确认瞬态错误 | 沿用现有最多一次安全重试并计入预算 |
| DAG | 外部调用 timeout、结果未知 | 不自动重试，记录 `external_outcome_unknown` |
| DAG | 无外部结果不确定性的执行基础设施错误耗尽恢复次数 | `failed/deepsearch_execution_transient` |
| DAG | required 节点失败 | 满足 `safe_partial_report` 则 sealed partial，否则 `failed/deepsearch_delivery_unavailable` |
| DAG | optional 节点失败 | 满足 `safe_partial_report` 则 sealed partial，否则 `failed/deepsearch_delivery_unavailable` |
| Evidence | 引用缺失、跨 Run、hash/归属错误 | `failed/deepsearch_evidence_integrity_failed`，无报告 |
| Coverage | required 覆盖不足 | 满足 `safe_partial_report` 则 sealed partial，否则 `failed/deepsearch_delivery_unavailable` |
| Synthesis | 原始调用和格式修复都失败 | 满足 `safe_partial_report` 则 sealed partial，否则 `failed/deepsearch_delivery_unavailable` |
| Review | 首次 `revise` | 只修订一次，并重新执行 Coverage 和 Review |
| Review | 第二次未通过、timeout 或 Schema 非法 | 满足 `safe_partial_report` 则 sealed partial，否则 failed |
| Report | 保存或封存失败 | 最多重试 3 次；期间保持 running，耗尽后 failed，不发布 `output_text` |
| 并发 | 双提交、双批准、迟到结果 | 仅一个 CAS 成功，其余 `409` 或丢弃迟到结果 |
| 取消 | 取消后节点或 Finalizer 返回 | 所有迟到提交失败，不复活 Run |
| 进程崩溃 | planning/执行/finalization 未完成 | 按 §7.1 恢复，不通过通用 reconciler 直接失败 |

权限错误遵循当前“不可见即 `404`”规则，错误响应不得泄漏其他用户的 Run、Skill、来源或 Artifact 信息。

### 12.4 可观测性

管理员诊断增加独立 `deepsearch_metrics`，只统计 `planning_mode=deepsearch`：

```text
runs_started
terminal_status_counts
clarification_round_counts / clarification_exhaustion_rate
planning_failure_rate / capability_gap_counts
evidence_pass_rate
review_verdict_counts / review_revision_rate
partial_failed_rate
stage_duration_p95_ms / end_to_end_p95_ms
admission_rejected_by_code
```

比率分母为 0 时返回 `null`；同一 Run/Plan 的终态指标只计一次。指标标签只允许稳定枚举，禁止 prompt、答案、user/run ID、URL 或 Provider 原始错误；DeepSearch 指标不得混入 standard 聚合。

Run 相关指标从 `agent_run_events` 的稳定事件和时间戳派生；准入拒绝因为没有 Run，只使用进程级计数器并在响应中标明 `window=process_lifetime`，进程重启后归零。首期不为指标新增数据库表或外部遥测服务。

## 13. 实施顺序

本功能跨越现有路由、Store、Executor、Tool Gateway 和前端，预计修改超过 8 个文件，但不新增服务或 Runtime。每个切片必须在 `AGENTMESH_DEEPSEARCH_ENABLED=false` 时可独立合并，所有既有功能保持可用；任何未完成切片都不得暴露半成品入口。

实施前先记录普通聊天、显式 `$skill`、标准 v1 Plan、research-v2 历史只读投影、全量 pytest、Ruff、前端测试和构建基线。这是首个切片的进入门禁，不作为单独的“调研阶段”。

### Slice 1：兼容契约、Artifact seam 与准入

- 在运行时配置和 `.env.example` 增加默认关闭的 `AGENTMESH_DEEPSEARCH_ENABLED`，并增加 `AgentPlanningMode`、`planning_mode`、`waiting_clarification`、预算字段和 Bootstrap availability。
- 将 `planning_mode` 纳入路由和 Store 两层幂等身份。
- 接入显式 DeepSearch 准入分支，强制 v1、auto request、execute server mode、无显式 Skill。
- 新增 `agentmesh/artifacts.py`，实现 strict DTO Schema Registry、v1 legacy/verified 读取及 verified insert/CAS；Artifact 路由按持久化版本分发，并保持 frozen v2 Reader 原样。
- 固化 standard、v1 legacy 和 retired Research 的反向隔离测试。

完成条件：开关关闭时 API、数据库和界面行为与基线一致；相同 `client_turn_id` 的 mode collision 稳定返回 409；v1 sealed 可读、非 sealed 不泄漏正文、research-v2 历史读取字节级无回归。

### Slice 2：Requirement 与多轮澄清

- 增加 `deepsearch_requirement_versions`、Question/Requirement DTO、canonical hash 和 CAS。
- 实现 Refiner、DeepSearch GET/clarify API、0～3 轮澄清和刷新恢复。
- 实现澄清幂等处理顺序、24 小时交互 TTL、Retry disposition。

完成条件：澄清阶段 Tool 调用始终为 0；stale version 优先返回 409；并发和重放不会覆盖版本。

### Slice 3：ProblemGraph 与单 Plan

- 从 canonical planning input 依次接入 Router、Intent、ProblemGraph、Retriever 和 Planner。
- 增加覆盖、canonical hash、Plan Snapshot、READ/DRAFT-only、真实 Tool side effect、Skill/Tool/Provider 就绪度校验。
- 原子保存一个 Plan，并复用现有编辑、批准、拒绝接口；DeepSearch 批准事务为批准后递增的 Plan version 写 sealed Snapshot 并冻结该版本；required capability gap 同时阻断后端批准和前端动作。

完成条件：未知 Skill、缺失覆盖、过期 hash、无授权 Tool、preview/off 模式和写副作用节点都不能通过 Plan gate。

### Slice 4：Executor seam 与可信 Evidence

- 从 `BoundedDAGExecutor` 提取 `StandardPlanFinalizer`，先证明 standard 行为无差异；在同一 Executor 增加窄恢复入口，使 `approved` Plan 先走现有 Plan claim、已持久化 `READY` 节点直接走现有 node claim，正常启动和恢复共用唯一调度循环与 node runner。
- 扩展 RunContext 的 Plan/Node attempt lineage；`ToolFactory` 通过统一 invocation adapter 在调用前持久化 `tool_call_id/operation_key`，并在批准和实际 invoke 两处拒绝写型 Tool。
- 内置 Web adapter 生成顺序无关的确定性 Source ID；Tool Gateway 在单事务中为所有 DeepSearch Evidence 保存 sealed Envelope，节点只引用 Artifact ID。MCP 在 v1 中 fail closed。
- 实现 `DeepSearchFinalizer`、typed Evidence Manifest/Coverage、Review Outcome checkpoint、一次修订、deterministic digest、sealed Report 和确定性终态函数。

完成条件：没有完整 lineage、可信 Evidence、Review 和 sealed Report 时不存在 `completed`；Provider 调换结果顺序不会产生新 Source/Artifact；standard 不调用任何 DeepSearch Finalizer/Gate。

### Slice 5：恢复、预算和观测

- 实现 `DeepSearchRecoveryCoordinator`，让通用 reconciler 跳过 DeepSearch。
- 实现阶段 CAS、断点故障注入、固定预算、交互 TTL、绝对生命周期和指标聚合；用同一个 `DeepSearchBudgetMeter` 包住 planning、node LLM、synthesis、review/revision、Tool 和 Artifact 全部真实消耗点。
- 验证取消、迟到提交、Provider 中途失效和每个终态矩阵分支。

完成条件：每个 planning/execution/finalization 断点重启后只有一个终态和一个 Report Artifact，且预算不会被并发透支。

### Slice 6：Workspace 与受控发布

- 增加 DeepSearch 入口和 Requirement/澄清/单 Plan/执行/Evidence/报告阶段 UI。
- 使用 AgentMesh 视觉 token 和公共组件，完成 availability、capability gap、retry disposition、409 同步、键盘和无障碍行为。
- 先仅在内部部署环境显式打开全局开关；通过真实 Provider smoke 和全量门禁后再在目标环境启用，不新增用户 allowlist。

完成条件：所有硬门禁通过，standard 与 v2-history 对照组无回归；前端不存在候选 Plan、Research 版本选择器、PDF/ZIP 或视觉捕获入口。

## 14. 验证清单

### 14.1 后端自动化

实际测试分布如下；用目录模式描述，避免文件继续拆分时让方案清单失真：

```text
tests/test_deepsearch_*.py
tests/test_artifact_access.py
tests/test_mcp_runtime.py
tests/test_mvp_chat_threads.py
tests/test_skill_orchestration.py
tests/test_skill_plans.py
tests/test_skill_resources.py
agentmesh-demo/src/features/deepsearch/deepsearch.test.tsx
agentmesh-demo/e2e/deepsearch.spec.ts
```

必须覆盖：

1. `standard/deepsearch` 显式路由，且 DeepSearch 固定为 v1；旧客户端缺省为 standard。
2. 相同 `client_turn_id` 的 standard/deepsearch 顺序冲突、并发冲突和完全相同请求重放；重放先于当前准入检查。
3. DeepSearch 在 server off/preview、显式 Skill 和任意 WRITE side effect 下稳定拒绝；对真实 ToolDefinition 的门禁分别在 Plan、批准和实际 Tool/MCP invoke 层验证，人工审批不能绕过。
4. 无需澄清、1 轮、2 轮、3 轮、超限、每轮超过 5 问和 round off-by-one。
5. 缺答、非法/旧 question ID、重复 key、key/hash 冲突、stale version 和并发双回答；stale version 必须优先返回 409。
6. 澄清及 Plan 批准前零 Tool 调用；人工等待超过 300 秒但未超过 24 小时仍可继续。
7. 单 Plan 生成、编辑递增版本、sealed 历史快照、双批准、拒绝和取消；批准从 N 递增到 N+1 时必须原子生成 N+1 Snapshot，后续 lineage 只引用 N+1。
8. 澄清答案进入 canonical planning input；Router/Intent/Graph/Retriever 不得回退到原始输入。
9. 模型虚构 Skill、Skill 版本漂移、hash 不一致、Tool 不健康和权限缺失。
10. required capability gap 同时阻断后端批准和前端按钮；Provider 批准后失效不会降级为 fake/fallback。
11. DAG 并发上限、瞬态重试、依赖跳过、required/optional 失败和未知外部结果。
12. ProblemQuestion、success criteria、claim、Source、Evidence Artifact 和 Report Artifact 的覆盖及归属。
13. 小 Evidence 仍被 sealed；模型伪造 Provider/retrieved_at/hash、未知引用、跨 Run 引用、hash 篡改、索引/payload 不一致和未封存 Artifact 均 fail closed。
14. Review 首次 pass、一次 revise 后 pass、二次失败、timeout 和非法 Schema；v0/v1 Synthesis 与 Review Outcome 均 append-only 保留并绑定对应 synthesis hash；未知/跨 revision claim ID 被拒绝，unsupported/contradictory claims 在 partial 前被删除并重算 Coverage。
15. 终态矩阵逐行参数化；Evidence、Review 或 sealed Report 任一缺失时不得 `completed`；Review 前预算耗尽写 `not_run`，timeout/非法 Schema 写 `error` 而不伪造 verdict；completed/partial Report 的当前 revision 恰好有一条匹配的 Outcome，Review 检查点前取消、拒绝、过期或无报告 failed 可以为零且不得伪造 `not_run`，已提交的 Outcome 在终态竞争后仍 append-only 保留；已有 Plan 的每个终态都断言 SkillPlan 与 Run 状态匹配，Plan 前失败则断言未伪造 Plan/finalization stage。
16. 在 planning 和每个 finalization stage 前后崩溃；另在 approve 事务提交后/Plan claim 前、节点 `READY` 提交后/Task 创建前、节点 claim 为 `RUNNING` 后/结果提交前注入崩溃；恢复时未知结果节点原子转为 `FAILED(external_outcome_unknown)`、依赖节点变为 `SKIPPED`、独立节点继续调度，最终只产生一个终态和最多一个 Report Artifact且不残留 `RUNNING` 节点。断言 Coordinator 只调用 Executor 的窄恢复入口，正常启动与恢复路径使用相同的 Plan/node claim、调度循环和 node runner。
17. 每项预算的边界值、超限一单位、并发预占、7 天绝对过期和报告保存 3 次失败；逐个 spy 证明 Refiner、Graph/Planner、节点 LLM、Synthesis、Review/Revision、Tool 和 Artifact 都先 reserve 后调用，并且 DeepSearch Tool hook 不重复扣费；普通 Artifact/LLM 预算在节点后耗尽时，保留预算仍可封存 bounded Manifest、生成 evidence digest 和 sealed partial。
18. 澄清耗尽无通用 Retry；允许 Retry 时新 Run 的 Requirement lineage 正确且不复用旧 Evidence。
19. 功能开关在各活动状态中途关闭后，既有 Run 仍可查询和继续；显式取消仍能终止。
20. owner-only、foreign owner `404`、取消后的迟到提交、日志/事件/指标脱敏。
21. 普通聊天、显式 `$skill`、标准 v1 Plan 行为完全不变，standard 不调用 Refiner、DeepSearch Validator、Evidence Gate 或 Reviewer。
22. research-v2 历史 Run 继续通过 frozen `V2ArtifactHistoryReader` 只读可见，既有 fixture 的响应、错误码和 hash header 无变化；DeepSearch 不导入或调用任何已退役 Research Runtime。
23. 运行期 Evidence Item 不改变批准后的 `plan_content_hash`；DeepSearch Synthesis Draft 缺少合法 `evidence_item_ids`，或出现未知、重复、跨 revision claim ID 时 Coverage 失败；把事实只藏在 summary/section prose、传入模型自定义 heading/limitation，或让 required claim 不进入任何 section 时，Schema/Coverage 必须失败，不能 `completed`。
24. STAGING/FAILED/PURGED Artifact 对 aggregate 和 GET 均不返回正文；Report seal/terminal 与并发取消只能有一个事务成功，取消后不得残留可见报告。
25. token/time/Tool/Artifact reserve-settle 的成功、崩溃按上限结算、相同 invocation key 重放、并发预占和 Finalizer 专用 reserve；同一 logical stage 的第 2/3 次真实调用必须使用新 invocation key 并再次计费，但 stage 结果仍只能提交一次。
26. 相同 `client_turn_id` 和内容、但 `retry_of_run_id` 不同，必须返回 409。
27. absolute expiry 优先于 interaction expiry；启动扫描、30 秒扫描、Task 异常 callback 和所有 mutation/active-claim 都使用同一过期函数。
28. `planning` 缺 Requirement、`running` 缺/坏 Plan、非法 Run/Plan 状态组合、stage 恢复超过 3 次都 fail closed，不留下永久 running Run；合法的 Run=running/Plan=approved 必须被 claim，而非误判损坏；遗留 `RUNNING` 节点必须终结为 `FAILED(external_outcome_unknown)` 并传播依赖 skip，不能被忽略或重放。
29. 每条 Web Tool source 生成正确 `tool` origin 的 sealed Evidence；普通 DRAFT、Skill Resource Source、用户材料和 Knowledge 内容不能冒充 Evidence。多 Source、重复 reference 和 Provider 结果换序时 Source/Artifact ID 保持稳定且不碰撞；同 operation key 内容漂移时 fail closed。用户材料与 Knowledge Evidence 的生产入口留待后续独立切片。
30. OpenAPI 新增字段保持 additive；standard 不写 `nodes_terminal` 或 DeepSearch finalization stage。
31. Artifact Reader 分发矩阵逐行覆盖：v1 legacy、v1 DeepSearch verified、research-v2 history、列/payload 版本不一致、未知 verified schema 和 research-v3 均走唯一预期分支。
32. 每次 Tool handler 都收到持久化的 `plan/version/node/attempt/tool_call_id/operation_key`；缺任一 lineage、调用前未 reservation 或 handler 绕过 Gateway 均失败。
33. verified Artifact 的 insert-only 幂等、`STAGING -> SEALED | FAILED` CAS、SEALED 不可覆盖、FAILED 不可复活、canonical JSON、byte size/hash 篡改和 owner 隔离；直接写 SEALED 与 `STAGING -> SEALED` 必须通过严格 DTO，Registry 对 `{}`、未知字段、错误 artifact type/schema 配对和内外 lineage/origin 不一致全部 fail closed；`absent -> STAGING` 与 `STAGING -> FAILED` 只接受合法外层元数据和空正文，非空正文必须拒绝且不得把空正文误判为 Report DTO 错误。Reader 对正文为空或故意损坏的 STAGING/FAILED/PURGED 必须按状态返回对应错误而非 Schema/完整性错误，只有 SEALED 才解析 DTO。
34. 预算 reserve/settle 与取消、过期、Run 状态迁移并发时，旧 Run 对象不能覆盖较新的 budget version，预算写入也不能复活或倒退 Run 状态。
35. Manifest 空 items、重复 item、未知 Evidence/Source/Node Result、非 sealed Evidence、旧 Plan version 和引用 content hash 漂移均不能通过 typed Reader 或 `safe_partial_report`。

单元和集成测试全部使用 fake LLM、Tool 和 Provider，不调用真实网络、OAuth、O2 或付费服务。

### 14.2 前端自动化

- DeepSearch 开关和请求字段测试。
- Bootstrap availability 和入口禁用原因测试。
- 至少两轮连续澄清及刷新恢复。
- stale question/version 后丢弃旧表单并重新同步。
- 单 Plan 编辑、版本冲突、capability gap、确认、拒绝和审批。
- 执行事件更新、断线恢复和取消。
- Evidence、Review、limitations、partial 标签和来源引用展示。
- `retry_disposition` 三种动作和澄清耗尽无通用 Retry。
- 功能开关关闭后隐藏新入口，但既有 DeepSearch URL 仍可恢复。
- 无候选 Plan、无 PDF/ZIP、无视觉捕获的反向检查。
- research-v2 历史只读和标准 Workspace 回归。
- 键盘、焦点、`aria-live`、错误关联和 reduced motion。

### 14.3 E2E 主路径

验收分三层，不能把受控前端 mock 当成真实 Provider 证明：浏览器 E2E 验证交互、重同步和恢复；后端集成测试验证多节点、Evidence、Review 修订和终态不变量；发布前 smoke 才验证真实 Web/LLM Provider 的完整调用链。

目标真实全链路为：

```text
显式 DeepSearch
  -> 两轮澄清
  -> 生成一个 Plan
  -> 编辑并确认
  -> 执行多个 Skill 节点
  -> sealed Evidence Manifest
  -> Evidence coverage 通过
  -> Review 要求一次修订
  -> 修订后通过
  -> 生成带引用和 limitations 的文本报告
  -> 刷新后状态完全恢复
```

受控浏览器用例必须使用与 OpenAPI/后端契约一致的 DTO，并覆盖显式模式、两轮澄清、单 Plan 编辑、409 权威重同步、批准版本递增、多节点展示、revision 1 审核通过、limitations、SEALED Report、刷新以及从线程侧栏重进恢复。它只证明前端消费合法状态的行为，不证明外部 Provider、Evidence writer 或 Finalizer 在浏览器进程中真实执行。

无需澄清、partial、planning failure、required node failure、Evidence block、Review block、预算耗尽、崩溃恢复、取消以及真实 Provider 调用链，继续由后端集成测试与发布前 smoke 分别覆盖。

### 14.4 门禁命令

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
npm --prefix agentmesh-demo test
npm --prefix agentmesh-demo run api:types
npm --prefix agentmesh-demo run build
npm --prefix agentmesh-demo run test:e2e -- e2e/deepsearch.spec.ts
git diff --check
```

发布硬门槛：

- 零跨用户读取。
- 零 Plan 批准前 Tool 调用。
- 零 DeepSearch WRITE 节点或外部写副作用。
- 零缺失 Plan/Node/Attempt/Tool-call lineage 的 Tool 调用。
- 零缺失或损坏 Evidence 却进入 `completed`。
- 零未封存 Report 却投影 `output_text`。
- 零 STAGING、FAILED 或 PURGED Artifact 正文泄漏。
- 零超过现有 DAG 并发上限。
- 零超出固定 token、Tool、Artifact 和活动时间预算。
- 零未知外部结果自动重试。
- standard 和 research-v2 历史读取零行为回归。

### 14.5 实施验证结果（2026-08-27）

已完成并通过：

- DeepSearch 后端及相邻兼容面定向回归：`515 passed`。
- 全量后端回归：`1491 passed`。
- Ruff：通过。
- 前端单元测试：`156 passed`。
- OpenAPI 类型生成：通过。
- 前端生产构建及 bundle gate：通过。
- DeepSearch Playwright E2E：`1 passed`；修订后的用例使用当前 OpenAPI 类型约束 fixture，覆盖两轮澄清、Plan 409 重同步、v3→v4 批准、多节点状态、revision 1 审核通过、partial limitation、SEALED Report、刷新及从线程侧栏恢复。
- 全量 Playwright 清单：12 个 spec、56 个测试已在隔离批次中全部通过；同时补齐旧标准 Skill 编排 fixture 的 `planning_mode=standard`，防止被 DeepSearch DTO 判别器误分类。
- `git diff --check`：通过。
- Provider readiness：Web 与 LLM 均为 `ready=true, mode=real`。

DeepSearch Playwright E2E 使用受控 API fixture，不访问真实 Provider；它已通过当前 wire contract 交叉审查和独立复跑，但不能替代下一节的真实全链路 smoke。

### 14.6 尚未解除的发布门禁

以下条件尚未完成，因此保持 `AGENTMESH_DEEPSEARCH_ENABLED=false`：

1. 在隔离的内部环境使用真实 Web/LLM Provider，完成一次“创建 Run → 澄清 → Plan 批准 → 真实 `web_research` Evidence → Manifest → Coverage → Review → SEALED Report → 刷新恢复”的全链路 smoke。
2. 验证 smoke 产出的 Evidence 均为 `execution_mode=real`，Report 与 Manifest hash/lineage 一致，且不存在 fake/fallback Evidence。
3. 确认目标部署仍满足“单 SQLite、单应用/executor 进程”前提。
4. smoke 通过后才可受控开启开关；本文档不授权部署或全量启用。

## 15. 回滚

1. 数据库变更保持 additive；先发布能够读取新字段和新状态、但功能关闭的兼容版本。
2. 关闭 `AGENTMESH_DEEPSEARCH_ENABLED` 后，前端隐藏新建入口，后端拒绝新 DeepSearch Run 和 Retry；幂等重放与既有 Run 不受该开关影响，standard 流量不受影响。
3. 已开始的 Run 按其固定的 `planning_mode` 完成，或由用户/管理员显式取消；不得在回滚时重新解释成 standard 或已退役 Research 流程。Recovery Coordinator 仍可恢复既有 Run。
4. 若执行或 finalization 存在风险，先关闭 DeepSearch 新建入口，再等待 READ/DRAFT 节点收尾或显式取消活动 Run；只有需要停止全部 Skill DAG 时才调整全局 `AGENTMESH_SKILL_ORCHESTRATION`。
5. `deepsearch_requirement_versions` 和向后兼容 JSON 字段不在紧急回滚时删除，避免破坏历史读取。
6. 不回滚到无法识别 `waiting_clarification` 或 `planning_mode` 的旧二进制；回滚目标必须是“兼容 Schema、功能关闭”的版本。
7. research-v2 历史 reader 全程不参与 DeepSearch 回滚；已退役的 research-v3 没有可恢复入口。

## 16. 风险与前提

### 16.1 已知风险

| 风险 | 影响 | 控制措施 |
| --- | --- | --- |
| Requirement LLM 输出不稳定 | 澄清循环或 Plan 错误 | 严格 Schema、最多一次格式修复、最多 3 轮 |
| Skill Registry 描述或就绪度失真 | 选错 Skill、执行失败 | 服务端 shortlist、版本/hash 固定、批准前重验 |
| Tool provenance 断链 | Evidence 无法验证 | Gateway 对每条 Evidence 生成 sealed Envelope；模型只能引用 ID |
| v1 verified Artifact 误走 v2 Reader | 合法报告被判损坏或非 sealed 正文泄漏 | 按持久化版本显式分发、v1 allowlist、frozen v2 Reader 回归测试 |
| Plan 批准递增版本后快照断链 | Evidence 无法绑定批准 Plan | 批准事务为 N+1 原子封存等价 Snapshot，执行只引用批准版本 |
| 预算只接入部分调用点 | 超限仍继续调用 Provider | 单一 BudgetMeter 包住全部 LLM、Tool 和 Artifact 边界，逐点 spy 测试 |
| Review 模型非确定 | 完成判定波动 | 确定性 gate 优先、结构化 verdict、最多一次修订 |
| SQLite 并发和进程崩溃 | 重复计算或恢复困难 | 单 executor 进程、短事务、CAS、持久化 stage、单 Recovery Coordinator |
| 前端错误引用已退役 Research 资产 | 构建失败或重新引入旧状态模型 | 独立 DeepSearch adapter，只复用通用 Workspace 组件 |
| 误删 research-v2 | 历史 Run 无法读取 | 保持只读兼容，退役另立专项 |
| 长任务超时或用户离开 | 体验中断 | 交互 TTL 与计算预算分离、事件恢复、可取消、刷新读取权威状态 |
| Requirement/答案/Evidence 含敏感数据 | 日志或指标泄漏 | 正文只存权威业务记录，事件/日志/指标仅保存 ID、hash、计数和稳定错误码 |

### 16.2 上线前提

- 现有 Skill Catalog 能返回用户级可见性、版本、hash 和执行就绪度。
- Web Research 等必需 Tool 有真实 adapter、健康检查和权限信息。
- 现有 Plan 编辑/批准、节点 CAS、取消和事件读取保持稳定。
- 单个 SQLite 数据库只由一个 executor 进程消费；首期不宣称多实例安全。
- 固定预算、Provider timeout 和结构化输出修复均可被测试替身和 fake clock 覆盖。
- 前端能够持久化并恢复当前 Run ID，而不是靠本地阶段状态继续流程。

本方案最脆弱、也是上线的硬前提，是“单个 SQLite 仅有一个应用/executor 进程”。如果该前提不成立，当前 Recovery Coordinator 不能提供跨进程所有权；必须停止 DeepSearch 上线并改为 PostgreSQL/队列/Lease Worker 设计，不能靠增加更多 SQLite 锁补丁继续扩张。

出现以下任一需求时，应另行设计 PostgreSQL Control Plane、Lease Worker 和队列，而不是继续扩张本方案：

- 同一数据库需要多个执行进程并发抢占任务；
- 任务必须跨机器故障转移；
- 需要长时间离线执行、精确租约、全局限流或运维控制台；
- 需要 PDF/ZIP、视觉采集或多种报告发布流水线。

在上述条件出现前，DeepSearch 应保持为现有 v1 Skill DAG 的一个受约束执行模式，而不是第二套 Research 平台。
