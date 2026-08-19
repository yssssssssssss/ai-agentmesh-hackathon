# AgentMesh Research Orchestration v2 融合开发方案

> 状态：In Progress，Slice A 已批准实施
>
> 日期：2026-08-19
>
> 适用范围：当前 Python 3.12 + FastAPI + SQLite + React/Vite 内部试点
>
> 决策：保留审计级研究闭环方向，改为三个可独立发布的垂直切片；不按原六阶段方案实施

## 1. 执行摘要

本方案把 AgentMesh 从“受治理的多 Skill 编排器”演进为“可澄清、可规划、可追溯、可恢复的研究工作流”，但不再一次性建设第二套完整编排平台。

首期只交付一个用户可完整使用的 competitive research 垂直闭环：

1. 用户从 Web 输入自然语言研究请求，或显式直呼 competitive-analysis Skill；
2. 服务端形成版本化 Requirement 和 Problem Contract；
3. 默认生成一个可执行计划；只有存在实质性成本、风险或证据差异时才生成第二候选；
4. Tool 和 Skill 作为独立 Step 执行；
5. Tool 输出进入 SEALED Artifact，并形成可点击 Evidence；
6. Claim Ledger 将事实、推断和建议绑定到 Evidence；
7. 生成结构化 Competitive Analysis Deliverable；
8. 确定性 Review 通过后生成 Markdown/HTML Report；
9. 浏览器刷新、SSE 重连和进程重启不会重复接受同一步骤结果；
10. 关闭现有编排开关即可停止 v2 新执行，历史记录继续可读。

本方案保留以下核心机制：

- AgentRun 作为顶层任务身份、所有权、线程和事件流；
- 现有 Auth、Tool Grant、Inbox Approval、SSE、Artifact 读取和 SQLite CAS；
- 显式 Tool/Skill Actor、不可变 Plan、Artifact hash 和精确 input binding；
- Evidence、Claim、Deliverable、Review 和可选 Report 的可追溯链路；
- off / preview / execute 唯一灰度开关；
- 真实 Provider smoke 和无数据删除回滚。

本方案明确删除或推迟以下复杂度：

- 不向 AgentRunStatus 增加十余个研究阶段状态；
- 不强制每个任务生成 depth/speed 两个候选；
- 不在首期建设六层 FindingGraph；
- 不强制问卷、访谈提纲等生成 ReportDocument；
- 不宣称任意外部 Provider 都能 exactly-once；
- 不一次性迁移十个 Skill；
- 不预建微服务、Worker、消息队列、PostgreSQL 或对象存储。

## 2. 当前基线与实施门禁

### 2.1 已验证基线

截至 2026-08-19，当前 Skill Matrix 基线已记录：

- 725 项后端 pytest；
- Ruff；
- 92 项前端 Vitest；
- TypeScript 与 Vite production build；
- 61 项编排集中测试；
- 10 个 Wiki 领域 Skill 和 11 个 Legacy 能力的 Registry 校验；
- Web 自然语言输入、计划确认、DAG 执行、Wiki Resource、Synthesis 和聊天投影真实链路。

真实模型兼容验证已覆盖：

- GPT-5.2 JoyBuilder；
- GPT-5.4 JoyBuilder；
- GPT-5.5 JoyBuilder。

Kimi K2.6 已从 AGENTMESH_MODELS 备选池移除，不再属于发布门禁对象。后续只测试实际启用的模型，不保留无生产用途的候选模型。

### 2.2 基线提交门禁

Research Orchestration v2 开发开始前，Release owner 必须建立一个可回退的基线提交。门禁不是“工作区看起来干净”，而是以下证据同时存在：

- git status 已人工审查，确认无凭证、数据库、smoke payload 和无关大目录；
- 当前 Skill Matrix 代码、前端、OpenAPI、ADR 0004 和测试属于同一提交；
- 后端、Ruff、前端测试、OpenAPI 类型生成、production build、E2E、retrieval eval 和 catalog report 全部通过；
- docs/verification/2026-08-19-research-orchestration-v2-baseline.md 记录 commit SHA、命令、退出码和测试数量；
- .env、本地 SQLite、Provider key、原始 prompt 和真实 Tool payload 不进入提交。

v2 实现不得与未经审查的历史工作区修改混在同一个提交中。

### 2.3 唯一配置开关

继续使用现有 AGENTMESH_SKILL_ORCHESTRATION：

- off：不创建 v2 Workflow，新请求保持现有路径；
- preview：生成 Requirement、Problem Contract 和 Plan，但不执行 v2 Step；
- execute：允许满足门禁的 v2 Workflow 执行。

不增加第二个前后端 feature flag。前端继续从 Bootstrap 读取服务端 effective mode。

## 3. 产品假设、目标和停止条件

### 3.1 核心产品假设

本方案假设：内部用户需要的不只是更长的答案，而是能够检查“用了什么来源、哪条结论由什么证据支持、失败后能否安全恢复”的研究结果，并愿意为此接受有限的计划确认和额外等待。

### 3.2 用户目标

用户应能：

- 用一句自然语言启动研究；
- 只在真正阻断执行时回答澄清问题；
- 看懂即将使用的 Tool、Skill、预计时延、风险和证据策略；
- 不必理解 DAG、hash 或 JSON Pointer 也能完成任务；
- 在结果中点击事实引用并查看来源片段；
- 区分事实、推断、建议、冲突和资料缺口；
- 刷新页面或重连后继续查看同一任务；
- 对安全可重试的失败执行 retry；
- 对结果未知的外部调用看到明确警告，而不是静默重复执行；
- 获得任务类型真正需要的 Deliverable，而不是统一套一层报告。

### 3.3 停止扩张条件

Slice A 完成后，如果出现以下任一情况，不进入 Slice C：

- 在固定 20 条 competitive research 评测集上，v2 的证据可信度评分未比 v1 提升至少 0.5/5；
- v2 任一核心质量维度比 v1 下降超过 0.2/5；
- 仍存在 Severity 1 的无证据事实结论；
- 内部试点中计划或澄清放弃率超过 20%；
- 中位 Provider 成本超过 v1 的 2 倍，且人工质量评分提升不足 0.5/5；
- 少于 80% 的试点用户认为“可点击证据和明确缺口”有实际价值。

触发停止条件时，保留 v1 Executor，只吸收 Slice A 中已证明有价值的澄清、显式 Tool Step、可点击引用和 Deliverable 展示，不继续建设完整 v2。

## 4. 任务分型与首期范围

### 4.1 三类任务

十个 Wiki Skill 不再被强制塞进同一条报告流水线。

| archetype | task type / Skill | 必需结果链路 | 默认 Report |
| --- | --- | --- | --- |
| evidence_synthesis | competitive-analysis、query-experiment-conclusions | Requirement → Problem Contract → Tool/Resource → Evidence → Claim Ledger → Deliverable → Review | competitive 默认生成；experiment 按请求生成 |
| guided_generation | generate-research-plan、generate-interview-guide、generate-survey、generate-usability-test | Requirement → Skill/Resource → Deliverable schema → Review | 否 |
| decision_analysis | prd-feasibility、issue-prioritization、jobs-to-be-done、build-experience-metrics | Requirement → 输入/可选 Evidence → Claim Ledger → Deliverable → Review | 按请求生成 |

只有包含业务事实主张的任务才强制 Evidence。方法知识可以支撑方法选择，但不能冒充业务事实。

### 4.2 Slice A 固定范围

首个真实闭环固定为：

- archetype：evidence_synthesis；
- task type：competitive_research；
- core Tool：web_research；
- Skill：competitive-analysis；
- final reviewer：competitive-deliverable-reviewer；
- primary output：competitive_analysis Deliverable；
- optional renderer：Markdown/HTML ReportDocument；
- execution：一个默认候选、顺序执行 Tool → Skill → deterministic review → report composition；
- Provider：当前默认真实 GPT 模型和 real web_research Adapter。

Slice A 可以独立长期运行；即使 Slice B、C 永不实施，它仍然是完整可用的产品闭环。

### 4.3 非目标

首期明确不建设：

- 新语言、新 Runtime、独立微服务或第二套鉴权；
- PostgreSQL、Worker、消息队列、对象存储和水平扩容；
- 全部 78 个 Wiki Skill；
- 任意用户绘制 DAG edge；
- Skill 递归启动 Planner；
- 自动外部发布或自动写团队知识；
- PDF、复杂图表和多模态报告；
- 将旧 Artifact 追认为 verified Evidence；
- 用语义 Reviewer 证明事实真实性；
- 替换普通聊天、Personal Agent 或 11 个 Legacy command；
- 保存整页网页、未经脱敏的原始 Provider payload 或完整私有记忆正文。

## 5. 可验证成功标准

### 5.1 硬性技术不变量

- 未授权、未启用、unavailable 或已撤销 Skill/Tool 进入冻结计划的比例为 0；
- 客户端不能提交或篡改 structured Requirement、Problem Contract、Plan、actor identity 或 plan hash；
- 每份可执行计划都经过 PlanCompiler，并且冻结后不可原地修改；
- 每个标记为 factual 的 Claim 都能解析到 SEALED Artifact、Evidence ID 和精确 pointer；
- Artifact 读取时重新计算 hash，失败后不进入下游；
- required evidence 不足时不能生成“通过”的 Deliverable 或最终 Report；
- Tool Approval 与 Plan Confirmation 不互相授权；
- 相同 idempotency key + 相同 request hash 回放原响应；
- 相同 idempotency key + 不同 request hash 返回 409；
- lease fencing 拒绝旧执行者的晚到提交；
- 浏览器刷新、SSE 重连和重复 HTTP 请求不触发执行；
- 对不支持幂等或结果查询的外部写调用，未知结果进入人工恢复门禁，禁止自动重试；
- v1 后端、前端、E2E、retrieval eval 和 catalog 行为不回退。

### 5.2 产品和质量门禁

建立 20 条固定 competitive research 评测集：

- 5 条明确、低复杂度请求；
- 5 条存在范围或对象歧义的请求；
- 5 条来源冲突或信息过期的请求；
- 5 条包含缺失资料、恶意网页指令或不充分证据的请求。

使用相同默认模型、相同 Tool budget 和相同时间窗口比较 v1/v2。Slice A 进入 execute 灰度必须满足：

- 端到端完成至少 18/20；
- factual Claim 的机器可解析 Evidence 覆盖率 100%；
- 人工抽检“证据是否支持 Claim”的准确率至少 90%；
- Severity 1 无证据事实为 0；Severity 1 指直接支撑核心结论或建议、但没有有效 Evidence 的 factual Claim；
- 自然语言任务的计划无需重新生成即可接受的比例至少 80%；
- 正常 Provider 条件下 time-to-plan p50 不超过 30 秒；
- speed/default 路径端到端 p95 不超过 360 秒，其中执行预算仍不超过 300 秒；
- 单任务 Tool 调用不超过 4 次，模型和 Tool 实际用量均有 receipt；
- 中位 Provider 成本不超过 v1 的 2 倍；有价格配置时按货币计，无价格配置时按模型 token + Tool invocation 的归一化 usage unit 计；
- 10 名内部试点用户中至少 8 名认为证据和缺口展示有实际价值。

模型非确定性指标连续运行三次，至少两次满足门禁，且不得通过更换为 Mock 或隐藏失败样本达成。

评测样本固化在 eval/research_orchestration/competitive-research-v1.jsonl，评分规则固化在 eval/research_orchestration/rubric-v1.yaml。v1/v2 输出随机标为 A/B，由两名评审独立打分；任一维度分差超过 1/5 时由第三名评审裁决。计划接受、重新规划、澄清、完成、时延、usage 和 gap 使用现有 agent_run_events 记录脱敏指标，不增加外部分析服务。

## 6. 统一领域语言

| 术语 | 定义 |
| --- | --- |
| Research Workflow | 绑定一个 AgentRun 的 v2 研究控制状态，使用 run_id 作为聚合键 |
| Requirement Version | 一轮需求理解或澄清生成的不可变 ResearchTaskV2 |
| Problem Contract | 必须回答的问题、依赖、证据要求和成功标准；只有需要依赖时才形成图 |
| Plan Candidate | 尚未确认的一个或两个不可变执行候选 |
| Execution Plan Version | 服务端编译、确认并冻结的 Actor DAG |
| Execution Attempt | 对同一冻结计划的一次执行尝试 |
| Step | Tool、Skill 或 LLM 的一个显式执行节点；最终 Review 属于 ResultPipeline，不在 DAG 中重复建模 |
| Tool Invocation | 一次可对账的外部 Tool 调用，拥有稳定 operation key 和状态 |
| Artifact | 与 run、requirement、plan、attempt 和 step 绑定的持久化输出 |
| Evidence Record | 从可信来源 Artifact 中提取的事实依据及质量元数据 |
| Claim Ledger | 事实、推断或建议及其 Evidence/父 Claim 关系 |
| Deliverable | 满足任务类型 schema 和 coverage 规则的主要成果 |
| Review | 对 Deliverable 的确定性验证和按需语义质量检查 |
| ReportDocument | 对报告型 Deliverable 的可选渲染，不是所有任务的必经对象 |
| Gap | optional 能力失败、来源冲突或资料不足形成的明确缺口 |

SkillPlan 继续表示 v1 对象。v2 使用 ExecutionPlanVersion，不复用一个模型表达两种语义。

## 7. 核心架构

### 7.1 模块关系

~~~text
Workspace / HTTP / SSE
          │
          ▼
ResearchWorkflowService
  ├─ RequirementPlanner
  ├─ PlanCompiler
  ├─ ExecutionEngine
  │    ├─ ToolActor
  │    ├─ SkillActor
  │    └─ LlmActor
  └─ ResultPipeline
       ├─ Evidence + Claim Ledger
       ├─ Deliverable Review
       └─ Optional Report Renderer
          │
          ▼
SQLiteStore + ArtifactStore + existing Auth/Inbox
~~~

控制流从上到下，不允许 ResultPipeline 回调 Planner，不允许 Skill 递归创建 Workflow，不允许 SSE 或 GET 请求触发执行。

### 7.2 深 Module

| Module | 外部 Interface | 内部职责 |
| --- | --- | --- |
| ResearchWorkflowService | create、clarify、confirm、revise、execute、recover | 状态、gate、CAS、命令回放和 v1/v2 路由 |
| RequirementPlanner | raw input/answers → Requirement + Problem Contract + candidates | task archetype、阻断歧义、能力解析、候选差异判断 |
| PlanCompiler | candidate → frozen plan 或稳定错误码 | Actor、DAG、coverage、binding、approval、snapshot 和 hash |
| ExecutionEngine | plan + lease → attempt result | fencing、wave、invocation ledger、Actor dispatch、retry 和 restart reconciliation |
| ArtifactStore | stage、seal、read_verified、invalidate、purge | canonical hash、大小、scope、retention 和旧数据隔离 |
| ResultPipeline | verified outputs → Evidence/Claims/Deliverable/Review/Report | 证据质量、schema、coverage、gap、review 和安全渲染 |

不为每个小步骤创建单独 service。只有上述 Interface 进入路由或被其他深 Module 调用。

### 7.3 Port 与 Adapter

新 package 只依赖：

- LLM Port：结构化生成、文本生成、requested/actual identity、usage 和 receipt；
- Tool Port：resolve、health、invoke、reconcile 和 receipt；
- Repository Port：workflow、version、command、lease、step 和 invocation ledger；
- Artifact Port：stage、seal、read_verified、invalidate 和 purge；
- Clock Port：lease、TTL、deadline 和确定性测试；
- ID Port：生产随机 ID 和测试固定 ID。

现有实现作为 Adapter：

- AgentMeshModelFactory / Agents SDK → LLM Adapter；
- ToolGateway / Function Tool / MCP → Tool Adapter；
- SQLiteStore → Repository 和首期 inline Artifact Adapter；
- current_user、项目权限、Tool Grant 和 Inbox → Auth/Gate Adapter。

不新增生产 Runtime 依赖。

## 8. 状态模型

### 8.1 AgentRun 保持粗粒度生命周期

AgentRunStatus 不增加新枚举。继续使用现有：

- created；
- planning；
- waiting_plan_approval；
- running；
- waiting_approval；
- completed；
- partial；
- failed；
- rejected；
- cancelled。

completed_with_gaps 不新增状态，统一映射为 partial。

AgentRun 只新增一个字段：

- orchestration_version：v1 或 research-v2，创建后不可改变。

Research Workflow 以 run_id 作为主键，因此不保存恒等于 run_id 的 research_workflow_id。并发版本号只保存在
ResearchWorkflow.state_version；AgentRun 不保存第二份 state_version，避免两个 CAS 版本形成双真相。

### 8.2 Research Workflow 独立保存阶段

ResearchWorkflow 保存：

- phase：requirement、planning、execution、result、terminal；
- active_gate：none、clarification、plan_confirmation、tool_approval、recovery_decision；
- active requirement/plan/attempt/artifact IDs；
- state_version；
- created_at、updated_at。

映射规则：

| Workflow 状态 | AgentRun.status |
| --- | --- |
| requirement / planning | planning |
| plan_confirmation | waiting_plan_approval |
| execution | running |
| tool_approval | waiting_approval |
| recovery_decision | running；由 active_gate 阻止 scheduler 继续 claim |
| result | running |
| success | completed |
| success with optional gap | partial |
| unrecoverable | failed |
| user rejection | rejected |
| abort | cancelled |

前端通过 Research Workflow projection 判断具体阶段，不再从 AgentRun.status 猜测澄清、Review 或报告生成阶段。

## 9. Requirement 与澄清

### 9.1 ResearchTaskV2

每个 Requirement Version 至少包含：

- schema version；
- task archetype 和 task type；
- business domain；
- research goal；
- target audience；
- scope 和明确排除项；
- constraints 及 user/policy 来源；
- success criteria；
- expected deliverables；
- assumptions 及用户是否可接受；
- ambiguity code、blocking 标记和 rationale；
- clarification questions；
- sensitivity 和 PII 检测结果。

### 9.2 阻断规则

只有以下情况允许 blocking：

- Deliverable schema 的 required 输入缺失；
- 目标对象或比较范围存在互斥解释；
- 用户约束彼此冲突；
- 请求要求越权、不可用或被政策禁止的能力；
- required evidence 在当前授权范围内无法获取。

模型不能用自由文本创造新的阻断类型。服务端使用稳定 ambiguity code 校验。

### 9.3 澄清体验

- 每批最多 3 个问题；
- 最多 2 轮澄清；
- 非阻断 ambiguity 自动转成显式 assumption；
- 用户可以接受 assumption 或修改允许编辑的 assumption；
- 相同答案和 idempotency key 不产生第二个版本；
- 两轮后仍有 blocking issue，任务进入 failed，错误码为 clarification_exhausted；
- 原始输入、所有 Requirement Version 和用户答案保留审计，但不包含密钥或未脱敏私密正文。

明确输入不展示空的 ClarificationPanel，直接进入规划。

## 10. Registry、能力解析和冻结语义

### 10.1 Skill Profile

继续使用每个 Skill 的 agents/agentmesh.yaml，不增加中央手工 Skill 清单。Profile 增加或标准化：

- when_to_use；
- task_types 和 archetypes；
- input/output schema；
- required_tools 和 required_resources；
- produces_factual_claims；
- report_policy：never、on_request、default；
- cost_level、risk_level 和 owner；
- Skill version、body hash、profile hash 和 schema hash。

### 10.2 Tool Manifest

ToolDefinition 补充：

- adapter type 和 implementation ID；
- execution mode：real 或 fake；
- input/output schema；
- side_effect：read、idempotent_write、non_idempotent_write；
- idempotency_support：provider、reconcile_only、none；
- timeout 和 retry policy；
- risk、approval 和 redaction policy；
- evidence class；
- health state、checked_at 和 TTL。

health state 只允许：

- healthy；
- unavailable；
- unknown；
- stale。

planning 使用 60 秒 TTL 的 health snapshot；执行前必须重检。瞬时 unknown/stale 不被伪装成 healthy，也不永久污染 Registry。

### 10.3 能力过滤

确定性过滤顺序：

1. Skill active、binding enabled、profile current；
2. task type/archetype 匹配；
3. required resources 可解析；
4. required Tool active、granted、real；
5. Tool health snapshot 未过期且为 healthy；
6. 当前用户、Workspace、项目和 Memory Binding 允许；
7. 高风险能力存在审批角色；
8. 缺失业务输入转成 pending input；
9. eligible Skill 才进入现有 FTS/Vector 排名。

LLM 只能看到 eligible shortlist，不能看到被拒能力的完整说明。

### 10.4 真正的冻结范围

PlanCompiler 保存以下控制快照的实际内容和 hash：

- Skill Profile；
- SKILL.md；
- input/output schema；
- Tool manifest；
- Deliverable contract；
- Evidence policy；
- Review rubric。

Resource 不 hash 整棵 Wiki。规划期能够确定的方法资源在 Plan 冻结前形成 SEALED ResourceSnapshot，其 hash 进入 Plan；必须依赖上游输出才能选择的资源则成为显式 Resource Step，其 snapshot hash 进入 Attempt 和下游 resolved input。两类 snapshot 都只记录 manifest 允许范围内实际选中的文件、相对路径和内容 hash，重试复用同一 snapshot。

Adapter 可执行代码不复制进数据库。Plan 只冻结 implementation ID 和兼容版本。进程重启后如果该实现不存在或版本不兼容，当前 attempt 进入 recovery_decision，要求 replan；禁止用新代码静默执行旧计划。

## 11. Problem Contract 与候选计划

### 11.1 Problem Contract

Problem Contract 记录：

- 稳定 question ID；
- statement 和 rationale；
- required/optional；
- success criterion IDs；
- evidence requirements；
- acceptance criteria；
- question dependencies。

确定性校验：

- ID 唯一；
- dependency 存在且无环；
- required question 覆盖全部 success criteria；
- factual required question 有 evidence requirement；
- optional question 不能成为 required question 的唯一输入；
- Deliverable contract 和 Problem Contract 一致。

执行过程中禁止修改 Problem Contract。需求变化必须产生新的 Requirement Version 和 Plan Version。

### 11.2 自适应候选

默认只生成一个 recommended 候选。仅当第二候选与 recommended 至少存在一项实质差异时才展示两个：

- Actor/Skill 集合不同；
- Tool 调用数不同；
- Evidence 独立来源要求不同；
- 预计时延档位不同；
- Provider 成本档位不同；
- 风险或审批要求不同；
- Deliverable coverage 不同。

只有名称、措辞或节点顺序变化不算实质差异。

两个候选存在时使用 fast/thorough：

- fast：最多 4 个 Step、最多 4 次 Tool 调用、执行预算 300 秒；
- thorough：最多 8 个 Step、最多 12 次 Tool 调用、执行预算 600 秒；
- DAG 深度最多 4；
- 同 wave 最多 3 个并发 Step；
- AgentRun 的 24 次 Tool call 继续作为不可突破的最终防线。

### 11.3 显式 $skill 快速路径

服务端解析 $skill-name argument：

- 跳过自动 Skill 排名；
- 仍校验 active、binding、resource、Tool Grant、health 和 risk；
- 只生成一个包含指定 Skill 及其 required Tool/Resource 的计划；
- 不生成无意义的 fast/thorough 对比；
- 低风险、只读、单 Skill 计划沿用 v1 策略，可服务端自动确认并直接执行；
- 两个以上 Skill、写 Tool 或高风险 Tool 仍要求显式确认/审批；
- 仍保留 PlanCompiler、Artifact、Evidence 和任务类型要求的 Review；
- 只有 report_policy=default 或用户明确要求时生成 Report。

这条路径保留用户对显式 Skill 的快速体验，同时不绕过权限和证据边界。

## 12. PlanCompiler

每个 Step 至少包含：

- step number、name；
- actor type 和 actor ID；
- question IDs；
- dependencies；
- initial input 和 input bindings；
- expected outputs 和 acceptance criteria；
- required/optional；
- approval requirement；
- timeout、retry 和 invocation semantics；
- registry、manifest、schema、snapshot 和 actor hashes。

PlanCompiler 必须拒绝：

- 未知或非 eligible actor；
- cycle、未知 dependency 和超出规模上限；
- required Tool 未展开为更早 Step；
- optional Step 成为 required Step 的唯一关键输入；
- binding 引用非祖先 Step；
- source pointer 不属于 source output；
- target pointer 不存在或类型不兼容；
- 多个 binding 写入同一 target pointer；
- high-risk actor 缺少正确审批角色；
- factual question 缺少 Evidence policy；
- 模型策略或 Adapter compatibility 未冻结；
- canonical plan hash 不可重复计算。

canonical JSON 规则固定为：

- UTF-8；
- Unicode NFC；
- object key 按 Unicode code point 排序；
- 紧凑分隔符；
- 禁止 NaN、Infinity 和二进制浮点；
- decimal 使用规范字符串；
- datetime 使用 UTC Z；
- hash 使用 SHA-256。

冻结 Plan 不允许 PATCH。任何候选调整都产生新 Plan Version 并重新编译。

## 13. 执行、幂等与恢复

### 13.1 ExecutionAttempt 与 lease

每次执行创建新的 ExecutionAttempt，绑定：

- run ID；
- requirement version ID；
- plan version ID；
- attempt number；
- lease owner、token、fencing epoch 和 expiry；
- execution budget；
- retry lineage；
- terminal status。

默认 lease TTL 为 60 秒，heartbeat 每 15 秒一次。启动时和运行期间每 30 秒扫描过期 lease。

每次提交 Step、Artifact、Evidence、Deliverable、Review 或 Report 前，必须同时校验：

- active attempt；
- lease owner/token；
- fencing epoch；
- AgentRun 非 terminal；
- orchestration mode 允许完成当前安全点。

off 只阻止新的 claim。已经进入 SENT 的 Provider 调用仍允许提交 receipt、Artifact 和 terminal accounting，避免把已发生调用伪装成“未执行”；settlement 完成后不再 claim 后续 Step。

### 13.2 网络调用事务边界

外部调用不得持有 SQLite transaction。固定顺序：

1. 短事务 claim Step 并递增 fencing epoch；
2. 短事务创建 PREPARED ToolInvocation/ModelCallReceipt 并提交；
3. 调用前用短事务将 PREPARED 转为 SENT 并提交；
4. 在事务外调用 Provider；
5. 短事务校验 lease/fencing，写 receipt、Artifact 和 ACKNOWLEDGED；
6. CAS 推进 Step 和 Workflow。

### 13.3 ToolInvocation 状态

状态机：

~~~text
PREPARED → SENT → ACKNOWLEDGED
              └→ UNKNOWN
PREPARED → CANCELLED
~~~

- operation key 由 run、plan hash、step contract hash 和规范 input hash 生成，在相同输入的 retry attempt 间保持稳定；
- invocation ID 标识本地一次逻辑外部操作；严格匹配的 retry 继续使用同一 invocation 记录并增加 send_count；
- 支持 Provider idempotency key 时必须透传稳定 operation key；
- Provider 支持结果查询时，UNKNOWN 先 reconcile；
- read 或 provider-idempotent Tool 可按 manifest 规则重试；
- non-idempotent write 且无法 reconcile 时保持 UNKNOWN，进入 recovery_decision；
- 人工只能选择“标记已完成并附 receipt”“确认未发生后重试”或“终止任务”；
- 系统不允许把 UNKNOWN 自动当作失败并重放。

因此，本方案保证“同一个 operation key 最多接受一个结果”，而不是声称所有 Provider 最多收到一次请求。Provider 计费请求在网络超时边界可能重复，必须在审计和成本中披露。

### 13.4 启动恢复

进程启动后：

1. 扫描非 terminal Workflow；
2. 将 lease 未过期的 attempt 保持原状态；
3. 对过期 lease 增加 fencing epoch；
4. PREPARED 且未发送的 invocation 可安全重新 claim；
5. SENT 无 receipt 转为 UNKNOWN；
6. ACKNOWLEDGED 但 Step 未提交时，从已校验 Artifact 补交 Step；
7. idempotent read 根据 manifest 自动 reconcile/retry；
8. 不可判断的写操作进入 recovery_decision；
9. 重新计算 ready Step 并恢复 scheduler；
10. 旧 lease 的晚到结果只记录审计，不改变状态。

### 13.5 Wave 和失败传播

- Scheduler 根据 dependency 生成 wave；
- 同 wave 最多 3 个 Step；
- required Step 失败停止依赖链；
- optional Step 失败形成 gap，传递依赖标记 skipped；
- required contract 仍满足时最终为 partial；
- required contract 不满足时为 failed 或 recovery_decision；
- retry 创建新 Attempt，不修改旧 Attempt；
- skip 只允许 optional Step，并生成新 Plan Version；
- abort 终止 Workflow、关闭 open approval、保留已提交 Artifact。

### 13.6 复用规则

首期只复用 read-only Tool 和 ResourceSnapshot。复用必须同时匹配：

- plan hash；
- step contract hash；
- registry/manifest/schema/implementation ID；
- resolved input hash；
- Artifact hash；
- Evidence policy version；
- owner/project/scope。

任一不匹配都重新执行或重新规划。

## 14. Artifact、配额和保留

### 14.1 状态与完整性

Artifact 状态：

- STAGING；
- SEALED；
- FAILED；
- LEGACY_UNVERIFIED；
- PURGED。

规则：

- 只有 SEALED 能进入下游；
- seal 时记录 schema version、content hash、size 和 provenance；
- read_verified 每次重新计算 hash；
- 旧 Artifact 默认视为 LEGACY_UNVERIFIED，不批量改写为 SEALED；
- hash 失败立即 invalidate，暂停依赖链；
- STAGING 超过 24 小时由 cleanup 标记 FAILED。

### 14.2 大小限制

Slice A：

- 模型单次可见 Tool 内容最多 50 KiB、2000 行；
- 单个 JSON Artifact 最多 1 MiB；
- 单个 run 的 v2 Artifact 总量最多 5 MiB；
- 单个 Evidence quote 最多 8 KiB；
- 超限输出要求 Tool 分页或缩小查询；
- 截断内容不得标为完整 Evidence。

SQLite 只保存结构化、脱敏后的结果和必要引用片段，不保存完整网页。

### 14.3 保留与删除

- active/non-terminal Workflow 不清理；
- STAGING/FAILED 临时内容保留 24 小时；
- 原始 Tool Artifact 在任务 terminal 后保留 30 天；清理前必须确认所有被引用记录都已有 read_verified 的 EvidenceSource，随后可将原始正文标记 PURGED；
- EvidenceService 将每个被引用记录最小化为独立 SEALED EvidenceSource Artifact，保存 quote、来源身份、receipt 以及上游 Artifact ID/hash/pointer；EvidenceSource、Claim Ledger、Deliverable、Review 和 Report 保留到用户删除研究数据；
- DELETE research-data 只允许 owner 对 terminal run 执行；
- purge 删除 v2 Requirement 副本、Tool/Model 内容、EvidenceSource、Claim、Deliverable、Review 和 Report 正文；原始 AgentRun input/chat message 属于线程数据，继续遵循现有线程保留策略，UI 必须明确这一边界；
- 删除正文后保留不含内容的审计 tombstone：artifact ID、kind、hash、purged_at、actor；
- cleanup 和 purge 都写 AuditEvent；
- 删除不恢复 open approval，也不影响其他 run。

当数据库文件超过 5 GiB、单日 SEALED Artifact 超过 1 GiB或 SQLite transaction p95 超过 100 ms 时，停止扩大流量并单独设计文件 CAS/PostgreSQL 迁移；不在本计划内预建。

## 15. Evidence 与 Claim Ledger

### 15.1 Evidence Record

每条 Evidence 至少记录：

- evidence ID 和 class；
- source URL/document/source ID；
- canonical URL 和 redirect chain；
- retrieved_at；
- Provider/connector identity；
- operation 和 receipt；
- EvidenceSource Artifact ID、hash 和 JSON Pointer；
- origin Tool Artifact ID、hash 和 origin pointer；
- exact quote 或结构化 observation；
- source tier：primary、reputable_secondary、provider_summary、unverified；
- freshness 和 applicable scope；
- independent source group；
- conflict status；
- authorization scope；
- prompt-injection suspicion 标记。

Source URL/ID 必须与 EvidenceSource pointer 指向值一致。即使 30 天后清理原始 Tool payload，Claim 仍能解析到最小化、已封存的 EvidenceSource；origin hash 和 receipt 保留上游血缘，UI 同时标明原始 payload 已清理、不能再重建全文。

### 15.2 证据质量规则

- 高置信 factual Claim 至少需要一个 primary Evidence，或两个 independent reputable_secondary Evidence；
- provider_summary 不能单独支撑高置信 observed fact；
- 只拿到搜索摘要时标记为 provider_summary，不伪装成已读取原页面；
- 来源冲突必须保留双方 Evidence 并降低 confidence；
- 过期 Evidence 只能支撑历史描述；
- method knowledge 只能支撑方法选择；
- simulation 必须标明假设，不能标为 observed fact；
- internal/private/document Evidence 必须带 owner/project/scope。

### 15.3 Claim Ledger

首期不建设六层 FindingGraph。每条 Claim 包含：

- claim ID；
- type：fact、inference、recommendation；
- statement；
- evidence IDs；
- parent claim IDs；
- confidence；
- conflict status；
- question/success criterion IDs；
- recommendation flag；
- authoring actor 和 model receipt。

规则：

- fact 必须直接引用 Evidence；
- inference 必须引用 Evidence 或已有 Claim；
- recommendation 必须引用支撑它的 Claim，并标明建议性质；
- ID 唯一且关系无环；
- 模型不能创建未知 Evidence；
- 图形层级只作为 UI 投影，不持久化额外“总结/结论”空壳节点。

## 16. 不可信内容与安全

Tool Artifact、网页、文档、Memory 和用户粘贴内容全部视为不可信数据。

### 16.1 Prompt Injection 防线

- Tool 输出进入 UntrustedContent envelope；
- system instructions 与不可信正文使用不同消息和明确数据边界；
- Skill/LLM Actor 被告知不得执行正文中的指令；
- 不可信正文不能改变 actor、Tool 权限、schema、Evidence policy 或 Plan；
- injection detector 只产生风险标记，不能作为唯一安全边界；
- suspected 内容仍可作为被引用的数据，但默认降低 source tier；
- Reviewer 不能覆盖任何确定性失败。

### 16.2 Web 和导出安全

- web Adapter 只接受 HTTPS；
- DNS 解析及每次 redirect 后拒绝 loopback、private、link-local 和 metadata 地址；
- 限制 redirect 次数、响应大小、content type 和超时；
- 丢弃 script、style、event handler 和不可见指令；
- Markdown/HTML renderer 默认转义不可信文本；
- HTML 导出不包含可执行 script，设置严格 CSP；
- React 不使用未经 sanitization 的 dangerouslySetInnerHTML；
- 测试覆盖存储型 XSS、Markdown link 注入、伪造引用和恶意页面指令。

### 16.3 隐私和密钥

- Requirement、Tool input/output 和 Report 分别执行敏感字段扫描；
- API key、Bearer token、cookie、原始 prompt 和未脱敏错误不得进入长期 Artifact；
- 私有/Internal Evidence 只展示允许范围内的摘要和引用标签；
- 导出文件不包含原始私有正文；
- Artifact 读取继续执行 owner + workspace 检查；
- 当前可信内网是网络边界；部署环境必须提供加密磁盘/卷后才能处理 private/internal Artifact，未验证磁盘加密时 v2 只允许 public Evidence。

## 17. Deliverable、Review 和 Report

### 17.1 Deliverable 优先

Deliverable 是用户主要成果。输入：

- active Requirement Version；
- Problem Contract 和 frozen Plan；
- verified Step outputs；
- Evidence Manifest；
- Claim Ledger；
- gaps；
- task type contract。

输出：

- task-specific payload；
- method summary；
- Claim Ledger 引用；
- question/success criterion coverage；
- limitations、conflicts、gaps 和 open issues；
- provenance IDs。

校验顺序：

1. envelope schema；
2. task payload schema；
3. Evidence/Claim 引用；
4. required question coverage；
5. success criterion coverage；
6. privacy/redaction；
7. SEALED Deliverable Artifact。

### 17.2 Review

先执行确定性 Review：

- schema；
- requirement/question coverage；
- Evidence coverage 和 quality；
- Claim relation；
- privacy/scope；
- gap disclosure；
- Artifact hash。

确定性失败时不能 pass。

语义 Review 只检查：

- 分析是否回应问题；
- 推断是否过度；
- 建议是否可执行；
- 风险和限制是否表达清楚。

语义 Reviewer 不证明事实，也不能创建 Evidence。每次 Review 记录：

- reviewer model；
- requested/actual identity；
- independence：same_model 或 independent_model；
- rubric version；
- pass/revise/block。

最多允许一次受限修订。第二次失败时保留 blocked Deliverable 和失败维度供用户查看，但不生成 final Report。

### 17.3 ReportDocument 是可选 Renderer

只有 report_policy=default 或用户明确要求时生成：

- report-document-v1 JSON；
- Markdown；
- HTML。

competitive research 默认生成，guided_generation 默认不生成。

Slice A 的 Markdown/HTML Report 使用确定性模板渲染。Report 只能消费 Review 通过的 Deliverable，不能直接读取原始 Tool payload、调用模型补写内容或产生新事实。

## 18. 持久化设计

### 18.1 新增逻辑记录

| table / record | 唯一约束 |
| --- | --- |
| research_workflows | primary key run_id |
| research_requirement_versions | unique(run_id, version) |
| research_plan_versions | unique(run_id, version)，unique(run_id, plan_hash) |
| research_commands | unique(run_id, idempotency_key) |
| research_attempts | unique(run_id, attempt_number) |
| research_steps | primary key(attempt_id, step_number) |
| research_tool_invocations | unique(run_id, plan_version_id, step_number, operation_key) |
| research_model_call_receipts | unique(attempt_id, stage, call_key) |

Problem Contract、ResourceSnapshot、Evidence Manifest、Claim Ledger、Deliverable、Review 和 ReportDocument 作为带 kind/schema version 的 SEALED Artifact 保存，不为每个文档类型增加浅表索引表。

### 18.2 现有对象修改

- agent_runs：只增加 immutable orchestration_version；不增加 research_workflow_id、state_version 或状态枚举；
- artifacts：增加 nullable verification_state、kind、attempt_id、step_number、schema_version、content_hash、size_bytes 和 purged_at；
- agent_run_events：继续承担 SSE/审计投影；
- inbox_items：继续承担 Tool Approval，不新增第二套审批表；
- sources、Tool、Grant、Binding 和 AuditEvent 继续复用。

旧 artifact 新列为空时按 LEGACY_UNVERIFIED 处理，不需要重写 payload。

### 18.3 事务和索引

必须建立：

- workflow phase/gate/update time 索引；
- attempt lease expiry/status 索引；
- invocation state/update time 索引；
- artifact run/kind/state 索引；
- command idempotency 唯一索引。

每个命令在同一 SQLite transaction 内完成：

- reserve idempotency key；
- 校验 expected ResearchWorkflow.state_version；
- 写状态变化；
- 写事件；
- 保存可回放 response。

外部 Provider 调用不在该事务内。

### 18.4 数据库升级

使用幂等、additive SQLite migration：

- 启动前备份当前数据库；
- 在 transaction 内创建新表和 nullable 列；
- 通过 PRAGMA 校验列和索引；
- 用旧数据库 fixture 启动并读取 v1 Run；
- 迁移后 v1 全量测试通过；
- 回滚代码不删除新表、不降级 schema。

## 19. HTTP Interface

继续复用：

- POST /api/agent/runs；
- GET /api/agent/runs/{run_id}；
- cancel、events、SSE；
- GET /api/artifacts/{artifact_id}；
- 现有 Inbox Tool Approval。

新增七个 v2 Interface：

- GET /api/agent/runs/{run_id}/research；
- POST /api/agent/runs/{run_id}/research/clarify；
- POST /api/agent/runs/{run_id}/research/plans/{plan_version_id}/confirm；
- POST /api/agent/runs/{run_id}/research/plans/{plan_version_id}/revise；
- POST /api/agent/runs/{run_id}/research/execute；
- POST /api/agent/runs/{run_id}/research/recover；
- DELETE /api/agent/runs/{run_id}/research-data。

GET research 返回单一聚合投影：

- Requirement summary；
- Workflow phase/gate；
- 一个或两个 Plan candidate；
- Attempt/Step progress；
- gap；
- Evidence/Deliverable/Review/Report Artifact IDs；
- provenance summary。

不为 Evidence、Claim、Deliverable 和三种 Report 格式分别增加 GET 路由。正文继续走现有 owner-scoped Artifact API。

所有 mutation 要求：

- task owner；
- expected_state_version；
- Idempotency-Key；
- request hash；
- 原子 command reserve 和 response replay。

revise 只接受目标、范围、assumption、候选偏好和“移除 optional Step”等声明式变更；服务端重新规划和编译。客户端不能提交 plan body、DAG edge、plan hash、structured requirement、actor identity 或 Artifact verification state。

## 20. 前端体验

### 20.1 信息层级

默认只展示：

1. 系统理解的目标和范围；
2. 需要用户处理的一个当前动作；
3. 简洁 Plan；
4. 执行进度；
5. Deliverable；
6. 事实旁的可点击引用和明确 gap。

DAG、hash、pointer、Claim lineage、model receipt 和完整审计信息放在“技术详情”中，不占据主流程。

### 20.2 组件

新增或重构为五个主组件：

- ResearchRunPanel：Requirement、phase、gate 和当前动作；
- ResearchPlanPreview：一个候选时简洁展示，两个候选时才比较；
- ResearchExecutionProgress：Tool/Skill Step、wave、retry 和恢复状态；
- ResearchDeliverableView：任务类型成果、coverage、gap 和可选 Report；
- ResearchEvidenceDrawer：来源片段、质量、冲突、Claim lineage 和技术详情。

不新增独立的 ProblemGraphView、FindingGraphView 和十个同级页面。

### 20.3 交互原则

- 明确输入不显示空澄清页；
- 每次最多要求用户做一个决定；
- Plan Confirmation 与 Tool Approval 文案和视觉分离；
- $skill 低风险单 Skill 快速路径不增加多余确认；
- 有两个实质差异候选时才显示比较；
- partial 不使用“完整成功”的绿色状态；
- UNKNOWN invocation 明确显示“外部结果未知，系统没有自动重试”；
- Artifact hash 失败时隐藏 final Report，但保留可读错误和恢复动作；
- refresh/SSE reconnect 只重新读取投影；
- 所有界面支持键盘操作、焦点恢复和屏幕阅读器状态播报。

## 21. Package 与文件规划

首期新增一个紧凑 package，不预先拆成大量浅模块：

~~~text
agentmesh/research_orchestration/
  __init__.py
  contracts.py
  ports.py
  planning.py
  compiler.py
  workflow.py
  execution.py
  actors.py
  artifacts.py
  evidence.py
  delivery.py
~~~

Slice A policy/config：

~~~text
agentmesh/research_orchestration/config/
  task-contracts.yaml
  evidence-policy-v1.yaml
  review-rubrics/competitive-analysis-v1.yaml
  report-templates/competitive-analysis-v1.md
~~~

Slice A schemas：

~~~text
agentmesh/schemas/
  research-task-v2.schema.json
  problem-contract-v1.schema.json
  execution-plan-v2.schema.json
  actor-output-envelope-v2.schema.json
  evidence-manifest-v1.schema.json
  claim-ledger-v1.schema.json
  deliverables/competitive-analysis-v1.schema.json
  report-document-v1.schema.json
~~~

Competitive Skill contract：

~~~text
agentmesh/builtin_skills/competitive-analysis/agents/agentmesh.yaml
agentmesh/builtin_skills/competitive-analysis/input.schema.json
agentmesh/builtin_skills/competitive-analysis/output.schema.json
~~~

固定评测资产：

~~~text
eval/research_orchestration/competitive-research-v1.jsonl
eval/research_orchestration/rubric-v1.yaml
eval/research_orchestration/run_eval.py
~~~

主要修改：

- agentmesh/models.py；
- agentmesh/store.py；
- agentmesh/agent_runtime/service.py；
- agentmesh/routes/agent_runs.py；
- agentmesh/routes/artifacts.py；
- agentmesh/routes/inbox.py；
- agentmesh/tool_runtime/gateway.py；
- agentmesh/tools.py / agentmesh/web_research.py；
- competitive-analysis Skill profile 和 schemas；
- Workspace API、types、queries 和上述五个 React 组件；
- OpenAPI、README、CONTEXT、ADR 和验证文档；
- docs/adr/0005-research-orchestration-v2.md，记录垂直切片、状态分层、invocation UNKNOWN、EvidenceSource 和可选 Report 决策；
- 后端、前端、E2E、eval 和 smoke。

Slice A 预计触及 45–60 个文件；完整三切片预计 85–125 个文件。该工作明确超过 8 个文件并新增一个 package，必须保持单 Writer 或隔离 worktree。

## 22. 三个可独立发布的垂直切片

### Slice A：Competitive Research 可审计闭环

#### 用户可获得

- Web 自然语言或 $competitive-analysis 启动；
- 对缺少 required competitive input 的请求进行一轮、最多三个问题的阻断澄清；
- 清晰请求直接生成一个 recommended Plan；
- real web_research → competitive-analysis；
- SEALED Artifact、Evidence 和 Claim Ledger；
- Competitive Analysis Deliverable；
- deterministic Review；
- Markdown/HTML Report；
- 浏览器刷新、重复命令和进程重启安全；
- off/preview/execute 灰度。

#### 工程范围

- Research Workflow、Requirement Version 和 Problem Contract；
- 单轮 clarification command 和 Requirement versioning；
- 单候选 PlanCompiler；
- Tool/Skill Actor；
- ToolInvocation ledger、lease 和 fencing；
- Artifact stage/seal/read_verified；
- Evidence quality 和 Claim Ledger；
- Deliverable/Report；
- 聚合 research API；
- 五个主 UI 组件中的最小可用状态；
- 默认 GPT 全链 smoke 和全部启用 GPT 兼容 smoke。

#### 验收

- 20 条固定评测集满足第 5 节门禁；
- 一轮澄清后能够继续的歧义请求不会被直接失败；
- Tool 和 Skill 是独立 Step；
- Skill 不拥有 Function Tool/MCP 权限；
- factual Claim 100% 可反查；
- Provider summary 不冒充页面 observation；
- Artifact 篡改阻断下游；
- SENT 后崩溃能进入 reconcile/UNKNOWN，不静默重试写操作；
- 旧 lease 晚到结果无法覆盖；
- Web 输入、计划、执行、证据、Deliverable 和 Report 完整可见；
- 关闭开关后不创建新 v2 Workflow，历史结果仍可读；
- Slice A 合并后即使后续停止，competitive research 仍可长期使用。

### Slice B：澄清、选择、恢复和安全增强

#### 用户可获得

- 将 Slice A 的单轮澄清扩展为最多两轮，并支持 assumption edits；
- 只有存在实质差异时才显示 fast/thorough；
- 用户调整目标/节点后生成新 Plan Version；
- 并行 wave、optional gap 和清晰恢复动作；
- semantic quality Review 和一次受限修订；
- UNKNOWN invocation 人工对账；
- research data 删除；
- 更完整的 Evidence 冲突和注入风险展示。

#### 工程范围

- second-round clarify/assumption edit、revise、recover 和 purge commands；
- 双候选差异判定；
- 最多三并发 wave；
- Provider reconcile Adapter；
- semantic reviewer independence 标记；
- retention/cleanup；
- prompt injection、SSRF、XSS 和 PII adversarial suite；
- progressive disclosure 和 accessibility E2E。

#### 验收

- 澄清不会无限循环；
- 候选无实质差异时只展示一个；
- revise 产生新 plan hash，旧 Plan 不变；
- optional 失败只产生 gap，不污染 required output；
- UNKNOWN write 不自动 retry；
- purge 后正文不可读取，tombstone 和审计存在；
- 恶意网页不能修改 Plan、Tool 权限、schema 或 Review 结果；
- Slice B 未发布也不影响 Slice A 的完整使用。

### Slice C：按任务原型扩展九个 Skill

按三个独立批次发布，不要求九个 Skill 同时完成：

1. guided_generation：research plan、interview guide、survey、usability test；
2. decision_analysis：feasibility、issue prioritization、JTBD、experience metrics；
3. evidence_synthesis：experiment conclusions。

每个批次：

- 增加 task/Deliverable contract 和 Skill schema；
- 根据 archetype 启用必要 Stage；
- guided_generation 不强制 Evidence/Claim Ledger/Report；
- 包含 factual claims 时才启用 Evidence policy；
- 每个 Skill 单独 contract test 和 Web acceptance；
- 通过灰度后才停止该 Skill 的 v1 新运行；
- 其他未迁移 Skill 继续 v1，不做一次性切换。

#### 验收

- 10 个 Skill 均有明确 archetype、input/output schema、report_policy 和 owner；
- 自然语言与 $skill 共享权限、Artifact 和审计边界；
- 每个 Skill 输出其真实 Deliverable，不套统一报告；
- 每个迁移 Skill 的 v1/v2 对照评测通过；
- 普通聊天和 11 个 Legacy command 无回归；
- 任一批次停止不会破坏已发布批次。

## 23. 测试策略

### 23.1 Module 测试

- Requirement：schema、blocking code、版本、两轮上限、幂等；
- Planning：archetype、eligible filter、单/双候选差异；
- Compiler：DAG、actor、binding、coverage、snapshot、canonical hash；
- Workflow：CAS、command replay、phase/gate 映射；
- Lease：heartbeat、expiry、fencing、late result；
- Invocation：PREPARED/SENT/ACKNOWLEDGED/UNKNOWN/reconcile；
- Actor：schema、Tool 隔离、scope、provenance；
- Artifact：状态、hash、大小、retention、purge、legacy；
- Evidence：tier、freshness、conflict、independent group、pointer；
- Claim Ledger：关系、cycle、unknown evidence；
- Deliverable：payload、coverage、gap、repair；
- Review：deterministic precedence、semantic independence；
- Report：no new facts、escaping、CSP、privacy。

pytest 不访问真实 LLM、Web、O2、MCP 或业务数据。

### 23.2 Property、并发和崩溃注入

至少覆盖：

- 随机 DAG 无环和 dependency 验证；
- canonical JSON test vectors；
- JSON Pointer duplicate target、类型错配和大小攻击；
- 重复 confirm/execute/recover；
- 两个执行者争抢同一 Step；
- Provider 返回前、返回后、receipt 前、Artifact seal 前、Step commit 前崩溃；
- lease 过期与晚到回调；
- cancel 与 Step commit 竞态；
- SQLite busy/locked 和 transaction rollback；
- restart reconciliation 幂等。

### 23.3 Integration

1. 明确 competitive request → Plan → Tool → Skill → Deliverable → Report；
2. blocking clarification → answer → new Requirement；
3. Tool Artifact → binding → Skill payload；
4. optional Step 失败 → partial + gap；
5. required Tool 失败 → recovery/failed；
6. Tool Approval 只恢复一次；
7. SENT 后重启 → reconcile/UNKNOWN；
8. Artifact 篡改阻断 Evidence；
9. source conflict 降低 confidence；
10. semantic revise 一次后 pass；
11. deterministic failure 无法被 semantic pass 覆盖；
12. $skill 快速路径仍通过权限和 Artifact 门禁；
13. 跨用户、跨项目、撤销 Grant 全部拒绝；
14. refresh、SSE reconnect 和重复 GET 不执行；
15. off 回滚停止新 claim。

### 23.4 安全测试

- 网页指令要求“忽略系统规则”；
- 网页伪造 system/tool 消息；
- SSRF、redirect 到 private address；
- HTML/Markdown 存储型 XSS；
- Provider payload 带 API key/cookie；
- PII 进入 Tool Artifact 和 Report；
- 私有 Evidence 越权导出；
- Artifact hash/pointer/Source ID 篡改；
- 恶意超大 JSON、深层对象和 pointer。

### 23.5 前端和 E2E

- 明确输入直接展示 Plan；
- clarification；
- 单候选与双候选；
- version conflict；
- execution progress；
- Tool Approval 与 recovery；
- evidence drawer、conflict 和 gap；
- Deliverable/Report；
- partial；
- refresh/SSE reconnect；
- keyboard/focus/screen reader status；
- off/preview/execute。

## 24. 真实 Provider 验证

### 24.1 模型兼容门禁

运行：

~~~bash
AGENTMESH_CHAT_LLM_TIMEOUT_SECONDS=60 .venv/bin/python scripts/agent_sdk_smoke.py --all-configured
~~~

要求 AGENTMESH_MODELS 中每个实际启用模型分别通过：

- structured Requirement；
- structured Plan/Deliverable；
- streaming；
- Function Tool；
- usage；
- cancellation；
- requested/actual provenance。

当前对象是 GPT-5.2、GPT-5.4、GPT-5.5。Kimi 不在模型池，因此不测试。

### 24.2 完整研究闭环

新增 scripts/research_orchestration_smoke.py，使用默认生产模型执行一次 competitive research：

- 从 POST /api/agent/runs 创建；
- 读取 Requirement 和 Plan；
- 确认/执行；
- 调用 real web_research；
- 生成 Evidence、Claim Ledger、Deliverable、Review 和 Report；
- 重启服务后重新读取结果；
- 输出 run、requirement、plan、attempt、invocation、artifact、evidence、deliverable、review 和 report ID；
- 不输出 prompt、key、私有正文或完整 Tool payload。

必须验证：

- requested/actual model；
- Tool implementation ID 和 real mode；
- invocation state；
- Artifact hash；
- Evidence quote/pointer；
- Claim coverage；
- Review pass；
- Report 不含新事实。

完整闭环固定跑默认模型，避免每次发布对所有模型重复执行昂贵研究；其他启用模型由兼容 smoke 覆盖。

### 24.3 Web 手工验收

启动：

~~~bash
.venv/bin/uvicorn agentmesh.app:app --reload --port 8010
npm --prefix agentmesh-demo run dev -- --port 5178 --strictPort
~~~

在 http://127.0.0.1:5178 输入：

> 对比三款面向企业产品团队的 AI 研究助手，重点分析证据可追溯、任务恢复和协作能力，给出适用场景与局限。

验收：

1. 明确目标不出现空澄清页；
2. 默认展示一个 Plan；
3. Plan 明确列出 web_research 和 competitive-analysis；
4. 执行时刷新浏览器，任务不重复；
5. 每条 factual Claim 可以打开来源片段；
6. 冲突或不足资料显示 gap；
7. Deliverable 与 Report 内容一致；
8. Report 导出没有 script、私有正文或伪造引用；
9. 技术详情能查看 model、Tool、Artifact 和 plan hash；
10. 切换 off 后新请求回到兼容路径，已有 v2 结果仍可读取。

## 25. 发布命令

每个切片合并前执行：

~~~bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
npm --prefix agentmesh-demo test -- --run
npm --prefix agentmesh-demo run api:types
npm --prefix agentmesh-demo run build
npm --prefix agentmesh-demo run test:e2e
.venv/bin/python eval/run_skill_retrieval_eval.py
.venv/bin/python scripts/skill_catalog_report.py agentmesh/builtin_skills
~~~

授权环境执行：

~~~bash
.venv/bin/python scripts/provider_smoke.py --web
AGENTMESH_CHAT_LLM_TIMEOUT_SECONDS=60 .venv/bin/python scripts/agent_sdk_smoke.py --all-configured
.venv/bin/python scripts/research_orchestration_smoke.py
~~~

Release owner 保存脱敏退出码、耗时、Provider identity 和审计 ID，不保存敏感正文。

## 26. 灰度、迁移和回滚

### 26.1 灰度

- Slice A 首先只允许 competitive_research 进入 preview；
- 评测集和真实 smoke 通过后，对内部试点用户进入 execute；
- 其他 task type 继续 v1；
- Slice C 每个 Skill 单独达到门禁后迁移；
- 不按“十个 Skill 同时切换”发布。

### 26.2 immutable orchestration version

AgentRun 创建时冻结 orchestration_version。修改当前开关不能把历史 v1 Run 解释为 v2，也不能让历史 v2 Run 用 v1 Executor 继续执行。

### 26.3 off 回滚

切换为 off 后：

- 不创建新 v2 Workflow；
- 未 claim Step 不再 claim；
- 已发送 Provider 请求不能假装取消，返回后按 invocation ledger 记录；
- 在 Actor 边界停止并将 Workflow 置于 recovery_decision 或安全 terminal；
- 不自动恢复 open approval；
- 不删除 Requirement、Plan、Attempt、Artifact、Evidence 或 Report；
- 历史记录只读；
- 新请求回到现有普通、单 Skill 或 v1 兼容路径；
- 数据库不 downgrade。

“安全点”只指两个 Actor 之间或外部请求已完成记账之后，不包括正在飞行中的未知外部调用。

## 27. 依赖、凭证和运行边界

不新增生产 Runtime 或外部服务。继续依赖：

- Python 3.12、FastAPI、Pydantic、SQLite；
- OpenAI Agents SDK；
- 当前 GPT 模型配置；
- real web_research Provider；
- AGENTMESH_WIKI_ROOT；
- 当前 Tool/MCP/O2 Adapter；
- React、TanStack Query 和 SSE。

真实闭环需要：

- 当前默认 GPT 模型的批准配置；
- GPT-5.2/5.4/5.5 启用项的 smoke 权限；
- real web_research key 或已批准 Provider 登录态；
- approved Wiki root。

所有 key 由部署 secret manager 或 ignored .env 注入。计划、测试日志、Artifact 和 Git 均不得包含凭证。

运行边界：

- 单 Workspace；
- 单 FastAPI 进程；
- 单 SQLite；
- 最多 4 个 active Attempt；
- 单 Plan 最多 3 个并发 Step；
- default 300 秒，thorough 最多 600 秒；
- 每 run v2 Artifact 最多 5 MiB。

## 28. Durable Entity Delta

| 增量 | 数量 | 用户需要 | Owner / 维护成本 | 回滚 |
| --- | ---: | --- | --- | --- |
| HTTP routes | +7 | 澄清、确认、修订、执行、恢复、聚合读取和删除 | Backend；OpenAPI/E2E 必须同步 | off 后 mutation 拒绝，GET 保留 |
| 持久化记录类型 | +8 | 版本、命令幂等、attempt、step、invocation 和模型 receipt | Backend；需要 migration/reconciliation | 不删除，旧代码忽略新表 |
| AgentRun status | +0 | 用独立 workflow phase 避免污染现有生命周期 | Backend/Frontend | 无枚举迁移 |
| 环境开关 | +0 | 复用现有 off/preview/execute | Release owner | 设置 off |
| Runtime/服务 | +0 外部服务，+1 内部 package | 隔离研究控制复杂度 | Backend；约 10 个深模块文件 | 路由关闭，记录只读 |
| Slice A schemas | +10 | 8 个工作流 schema + competitive Skill input/output，稳定输入、计划、证据、Claim、Deliverable 和 Report | Skill/Backend owner | 按 schema version 只读 |
| Policy/template files | +4 | 冻结 task contract、Evidence policy、Review rubric 和确定性 Report 模板 | Backend/Product owner | 旧 Plan 继续引用原版本 |
| 主前端组件 | +5 | 用渐进披露完成研究任务 | Frontend | effective mode 隐藏 v2 |
| v1 新运行路径 | 最终按 Skill -1 | 每个迁移 Skill 只保留一个生产 Executor | Runtime owner | 未迁移 Skill 不受影响 |

每个新增表和路由都服务于现有接口无法可靠表达的独立用户行为；不为单个 Artifact 类型新增专用表或 GET endpoint。

## 29. 工作量与人员

以一名高级全栈/后端主导工程师估算：

| Slice | P50 | P90 | 主要不确定性 |
| --- | --- | --- | --- |
| A | 5 工程周 | 8 工程周 | invocation crash boundary、Evidence contract、真实 Web Provider |
| B | 4 工程周 | 7 工程周 | reconcile、双候选 UX、安全 adversarial suite |
| C | 5 工程周 | 9 工程周 | 九个 Skill 输入/输出差异和人工质量评测 |
| 总计 | 14 工程周 | 24 工程周 | Provider 稳定性、schema 迁移和真实用户反馈 |

2 名后端 + 1 名前端并不线性提速；预计 P50 8–10 个日历周、P90 12–16 个日历周。

职责：

- Backend A：workflow、planning、compiler、repository 和 routes；
- Backend B：execution、invocation、artifact、evidence、delivery 和 adapters；
- Frontend：ResearchRunPanel、Plan、Progress、Deliverable、Evidence；
- Release owner：基线、Provider smoke、灰度、回滚；
- Security reviewer：Prompt Injection、SSRF、XSS、PII、scope 和 export；
- Product owner：20 条评测集、盲评和停止/继续决策。

同一主工作区只允许一个 Writer；并行开发使用隔离 worktree。

## 30. 主要风险与应对

| 风险 | 应对 |
| --- | --- |
| 当前基线混有大量修改 | 先建立经过审查和全量验证的 baseline commit |
| v2 成为第二套永久编排内核 | 只做 Slice A 垂直闭环，后续受产品指标门禁 |
| 外部调用成功但 receipt 未提交 | invocation ledger、UNKNOWN、reconcile、禁止不安全自动重试 |
| 只有 hash 没有旧内容 | 冻结控制快照；Adapter 不兼容时 replan |
| Wiki 无关文件变化导致全部失效 | 只 snapshot 实际读取文件 |
| Evidence 可追溯但不真实 | source tier、quote、freshness、independent group、conflict |
| Web Prompt Injection | 不可信内容隔离、无 Tool 权限、deterministic gate、adversarial test |
| 同模型自审共享偏差 | independence 标记；语义 Review 不升级事实等级 |
| SQLite 被 Artifact 撑大 | 5 MiB/run、30 天 raw retention、规模触发器 |
| 用户被流程淹没 | 一个默认候选、阻断才澄清、渐进披露、$skill 快速路径 |
| 十个 Skill 语义不同 | archetype pipeline，按 Skill 单独迁移 |
| Provider 限流或不可用 | health TTL、执行前重检、退避、真实 smoke 和明确失败 |
| 回滚时请求仍在飞行 | 安全点停止、invocation reconciliation、不伪称取消 |

## 31. 拒绝的方案

### 31.1 原六阶段横向建设

拒绝：前几个阶段没有完整用户价值，只有 M6 才形成可用结果，任何中断都会留下第二套半成品基础设施。

### 31.2 原样复制 ai-x TypeScript 模块

拒绝：引入第二语言和第二控制面，重复 Auth、AgentRun、Tool Grant、SSE 和持久化。

### 31.3 新建 Research 微服务

拒绝：当前单进程 SQLite 试点不存在需要网络边界解决的问题。

### 31.4 强制 depth/speed 双候选

拒绝：简单请求增加模型成本、等待和用户认知负担。只有差异可感知时才展示两个。

### 31.5 六层 FindingGraph

拒绝：首期关系层级会生成大量形式正确但没有新增价值的中间节点。Claim Ledger 已能满足追溯和校验。

### 31.6 所有 Deliverable 强制 Report

拒绝：问卷、访谈提纲和测试方案本身就是成果，统一套报告会损害使用体验。

### 31.7 宣称通用 exactly-once

拒绝：外部 Provider 成功、进程落库前崩溃的窗口无法由本地 CAS 消除。只承诺一个 operation key 最多接受一个结果，并对 UNKNOWN fail closed。

### 31.8 hash 整棵 Wiki 或快照 Adapter 代码

拒绝：无关文件变化会大面积失效，数据库也不应成为代码部署系统。实际资源按读取集合 snapshot，Adapter 用 compatibility ID。

### 31.9 只保留 v1、不做任何垂直闭环

这是停止条件触发后的最小替代方案，不是当前推荐方向：保留现有 Executor，只吸收澄清、显式 Tool、Evidence citation 和 Deliverable UX。

## 32. 最终完成定义

### Slice A 完成

- competitive research 从 Web 输入到 Report 全链可用；
- 单候选、Tool→Skill、Artifact、Evidence、Claim、Deliverable、Review、Report 全部落库；
- lease、fencing、invocation ledger 和启动恢复通过崩溃测试；
- Prompt Injection、SSRF、XSS、PII 基础门禁通过；
- 20 条评测集和 10 人试点门禁通过；
- 默认 GPT 完整 smoke 与所有启用 GPT 兼容 smoke 通过；
- off 回滚演练通过；
- 文档、ADR、OpenAPI 和运营手册一致。

### Slice B 完成

- 阻断澄清、实质差异双候选、revise 和 recover 可用；
- 并发 wave、optional gap、semantic review、retention 和 purge 可用；
- UNKNOWN 外部调用可人工对账；
- adversarial security suite 和 accessibility E2E 通过；
- Slice A 无回归。

### Slice C 完成

- 剩余九个 Skill 按三个 archetype 批次迁移；
- 每个 Skill 有独立 contract、quality eval 和 Web acceptance；
- guided_generation 不被强制生成 Evidence/Report；
- 每个迁移 Skill 停止 v1 新运行，未迁移 Skill 保持 v1；
- 十个 Skill、普通聊天和 Legacy command 全量无回归。

## 33. 关键前提与前提失效处理

最关键前提是：审计级证据、明确缺口和可恢复执行能显著提升研究结果的可信度，而不是只增加流程。

如果 Slice A 的固定评测和用户试点不能证明这一点：

- 不实施 Slice C；
- AGENTMESH_SKILL_ORCHESTRATION 保持 preview 或 off；
- 保留现有 Skill Matrix Executor；
- 只合并已经单独证明价值的可点击证据、显式 Tool Step、澄清和 Deliverable 组件；
- 不继续建设通用 Research Workflow Platform。

该停止路径不要求删除数据或数据库 downgrade，已完成的 competitive research 历史记录继续只读。

## 34. 批准结论

本修订方案推荐批准的方向是：

- 先交付 competitive research 单闭环；
- 用 invocation ledger 和 UNKNOWN 语义修正错误的 exactly-once 承诺；
- 用独立 Research Workflow phase 避免污染 AgentRunStatus；
- 用 Evidence quality + Claim Ledger 取代“hash 即真实”和六层 FindingGraph；
- 用 archetype pipeline、可选 Report 和 $skill 快速路径保护真实用户体验；
- 只有 Slice A 的评测和试点证明价值后，才扩展恢复能力和其余九个 Skill。

方案批准后才开始代码实现；实现完成后必须执行独立 code review 和发布门禁。
