# Task → Scenario → Skill → Knowledge 通用编排开发方案

- 状态：实施中；核心代码与自动化回归已完成，真实 Provider 验收、重启恢复验证和发布收尾待完成
- 日期：2026-08-24
- 适用版本：Agent Runtime v2 / Skill Orchestration
- 目标范围：通用任务识别、Scenario 路由、Skill/Knowledge 编排、Completion Check、降级与重试
- 非目标范围：Research v3 冻结 Catalog、特定行业专用 Skill、替换现有 Firecrawl Evidence Pipeline

## 1. 背景

当前 AgentMesh 的自动编排主要依赖 `SkillIntent.deliverables` 与 Skill Capability Profile 中 `output_kinds` 的精确字符串匹配。面对“公开资料研究 + 用户心智 + 策略地图 + 设计原则 + 机会点 + P0/P1/P2”这类复合任务时，Intent 被压缩成 `design_analysis`，现有 Skill 没有精确声明该输出，导致 `PlannerUnavailable`。

失败 Run 的 Retry 在没有 `plan_id` 时进入普通 `runtime.start()`，丢失原来的自动编排语义，并产生：

```text
PlannerUnavailable
→ Retry 降级到 v1 / orchestration_mode=off
→ 无 Web Research 的普通模型生成长答案
→ AGENTMESH_CHAT_LLM_TIMEOUT_SECONDS=60
→ ModelTimeoutError
```

问题不是“缺一个宠物主粮心智 Skill”，而是 Planner 缺少 Task/Scenario 层、Skill 组合语义、Knowledge 路由和完成度检查。

## 2. 设计依据

本方案以 `wiki/user-research` 的六区知识结构为设计来源：

- `wiki/user-research/README.md`
- `wiki/user-research/01-task-任务/index.md`
- `wiki/user-research/01-task-任务/task-skill-knowledge-mapping.md`
- `wiki/user-research/04-mechanism-机制/路由机制/任务路由规则.md`
- `wiki/user-research/04-mechanism-机制/路由机制/Skill与Knowledge路由规则.md`
- `wiki/user-research/04-mechanism-机制/路由机制/设计前任务路由Workflow.md`
- `wiki/user-research/04-mechanism-机制/降级机制/缺失信息降级规则.md`
- `wiki/user-research/04-mechanism-机制/质量机制/策略质量门禁.md`
- `wiki/user-research/05-registry-索引/task-registry.yaml`
- `wiki/user-research/05-registry-索引/skill-registry.yaml`
- `wiki/user-research/05-registry-索引/knowledge-registry.yaml`

核心原则：

1. 先判断用户最终要完成的 Task，再选择 Skill。
2. Task 只定义目标、输入、输出、完成标准和调用关系，不复制 Skill 步骤。
3. Skill 路由只能从 Scenario 和 Registry 中选择，不允许模型发明 Skill。
4. Knowledge 按 Task、Scenario、Domain 和 Input 最小化读取。
5. `planned` Skill 不得进入真实执行。
6. 完成度由 Scenario outputs 和 completion criteria 决定，不由“模型是否输出文本”决定。
7. 缺证据时降级并标注，不得用模型常识冒充外部事实。
8. 自动校验优先于人工审核；除高风险、不可逆或确实存在阻断歧义的情况外，开发和运行过程不等待人工签字。

## 3. 目标

1. 支持五类一级 Task 和 15 个 Scenario 的稳定识别。
2. 支持一个用户请求包含主 Task、次 Task 和串并行关系。
3. 根据 Scenario Registry 选择默认 Skill、按需 Skill 和 Knowledge。
4. 依据 Skill 状态、权限、输入、工具和知识可用性判断能否执行。
5. 生成可验证、可编辑、可恢复的执行 DAG。
6. 必须搜索的任务强制包含 Web Research 能力。
7. 多 Skill 结果经过统一 Completion Check 和 Synthesis 后形成最终报告。
8. Planner 失败或信息不足时返回可读的能力缺口，不静默降级为普通模型。
9. Retry 保留原 Task Route、编排模式和权限约束。
10. 为普通对话、Skill 节点、Web Research 和父 Run 配置分层超时。

## 4. 非目标

- 不为宠物、美妆、汽车等行业分别新增专用 Skill。
- 不把 `wiki/user-research` 整目录直接暴露给模型。
- 不在请求运行时扫描数千个 Wiki 文件。
- 不把所有 `draft` / `planned` Skill 自动视为生产能力。
- 不允许 Synthesis 新增未被上游结果支持的事实。
- 不绕过用户级 Tool Grant、Source、Artifact、Evidence 和 Audit 机制。
- 不为普通只读、草稿和可回滚开发步骤增加逐阶段人工审批。
- 不因 Skill 处于 `draft` 就在每次运行中重复要求人工确认；状态披露和自动质量检查优先。
- 不在本方案中重写 Research v2/v3 的证据流水线。

### 4.1 审核最小化原则

开发过程采用“一次方案确认、阶段内连续开发、一次合并前 Review”。每个 Phase 结束后运行自动化测试和静态检查，但不等待逐阶段人工签字，也不要求每个小改动单独审批。只有涉及数据迁移、安全边界、外部付费调用或不可逆操作时才暂停确认。

运行时同样避免重复确认：

- 高或中置信度、只读、可回滚的 Plan 自动继续执行。
- `draft` Skill 可以参与路由和执行，但必须披露状态并通过相同的自动校验。
- Completion Check 是自动验证，不是人工审核步骤。
- 只有低置信度且会实质改变执行路径、缺失无法降级的必需输入、高风险业务判断或不可逆副作用时，才请求人工确认。
- 已授予个人 Agent 的只读 Tool 由 Skill 直接继承，不重复逐调用确认；外部写入、不可逆操作或命中高风险策略时才保留单次确认。

## 5. 总体架构

```text
用户输入
   │
   ▼
Task Router
   ├─ 主 Task
   ├─ 次 Task
   ├─ 执行关系
   └─ 置信度
   │
   ▼
Scenario Router
   ├─ 二级 Scenario
   ├─ Context
   ├─ Input Check
   └─ Human Confirmation
   │
   ▼
Skill & Knowledge Router
   ├─ default Skills
   ├─ optional Skills
   ├─ planned/missing Skills
   ├─ required Knowledge
   └─ excluded Knowledge
   │
   ▼
Plan Compiler
   ├─ 串行节点
   ├─ 并行节点
   ├─ 条件节点
   ├─ Tool 权限
   └─ Knowledge Bindings
   │
   ▼
Bounded DAG Executor
   │
   ▼
SkillNodeResult / Evidence / Artifact
   │
   ▼
Completion Check
   ├─ outputs 齐全
   ├─ criteria 满足
   ├─ evidence 足够
   └─ human confirmation 状态
   │
   ▼
Synthesis / Report Composer
   │
   ▼
最终报告或明确的降级结果
```

## 6. Runtime Catalog

### 6.1 为什么不能直接扫描 Wiki

`wiki/user-research` 当前是本地未跟踪知识包，且多个 Task、Scenario、Skill 为 `draft`。Runtime 不能在每次请求中遍历该目录，也不能依赖中文目录位置保持不变。

### 6.2 编译后的 Catalog

新增受版本控制的 Runtime Catalog：

```text
agentmesh/task_catalog/user-research-v1/
├── catalog.json
├── tasks.json
├── scenarios.json
├── task-skill-mapping.json
├── skill-registry.json
├── knowledge-registry.json
└── schemas/
    ├── task.schema.json
    ├── scenario.schema.json
    ├── routing-result.schema.json
    └── completion-check.schema.json
```

新增编译脚本：

```text
scripts/build_task_catalog.py
```

编译流程：

```text
读取 wiki Registry 与 Task/Scenario frontmatter
→ 校验 ID 唯一
→ 校验 parent_task
→ 校验 Skill/Knowledge 引用存在
→ 校验状态枚举
→ 校验 outputs/completion_criteria
→ 生成规范化 JSON
→ 计算 Catalog Hash
```

Runtime 只读取编译后的 Catalog。Wiki 保持人可读真相源，Catalog 保持机器稳定接口。

### 6.3 Catalog 状态规则

| 状态 | Runtime 行为 |
| --- | --- |
| `validated` | 可在 execute 模式自动执行 |
| `reviewed` | 可执行，并在结果中保留状态 |
| `draft` | 可路由和执行，并在结果中保留状态；状态本身不触发逐次人工审批 |
| `planned` / `planned-*` | 不允许真实执行；有安全替代时自动降级，否则输出能力缺口 |
| Registry 不存在 | 断链，停止调用并记录诊断 |

## 7. Task Router

### 7.1 数据模型

新增 `TaskRoutingResult`：

```yaml
routing_result:
  task:
    task_id:
    confidence:
    reason:
    secondary_tasks:
    execution_relation:
  scenario:
    scenario_id:
    confidence:
    alternative_scenarios:
  context:
    domain:
    page:
    journey:
    project:
    user_segment:
    data_scope:
  input_check:
    available_inputs:
    missing_required_inputs:
    missing_optional_inputs:
    input_decision:
  skill_routing:
    default_skills:
    optional_skills:
    planned_skills:
    execution_mode:
    fallback_skill:
  knowledge_routing:
    required_knowledge:
    optional_knowledge:
    excluded_knowledge:
  completion_check:
    completed:
    missing_outputs:
    evidence_sufficient:
    confidence:
    reason:
  human_confirmation:
    required:
    reason:
```

### 7.2 一级 Task

首期固定支持：

- `find-direction`
- `understand-users`
- `find-problems`
- `solve-problems`
- `define-strategy`

模型不能生成 Registry 之外的 Task ID。

### 7.3 主 Task 与次 Task

以用户最终交付物确定主 Task，前置分析成为次 Task。

例如“研究市场和用户，最后给策略与优先级”：

```yaml
task_id: define-strategy
secondary_tasks:
  - find-direction
  - understand-users
execution_relation: parallel_then_merge
```

### 7.4 路由置信度

- `high`：直接进入 Scenario 路由。
- `medium`：选择得分最高的 Scenario 继续执行，同时记录备选 Scenario，不增加人工门禁。
- `low`：仅当歧义会实质改变执行路径或无法满足 required input 时澄清；否则按最高分方案降级执行并披露不确定性。

## 8. Scenario Router

根据 Task Registry 选择一个主 Scenario 和零到多个上游 Scenario。

支持关系：

- `serial`
- `parallel`
- `parallel_then_merge`
- `conditional`

宠物主粮任务的通用路由示例：

```text
competitor-benchmark-research ─┐
                               ├─ strategy-synthesis ─ priority-roadmap
user-journey-insight ──────────┘
```

这不是宠物行业特例。替换行业、品类或渠道后，Task/Scenario 关系保持不变。

## 9. Input Check

每个 Scenario 使用 Registry 中的：

- `required_inputs`
- `optional_inputs`
- `fallback`
- `human_confirmation`

输入检查顺序：

1. 当前用户消息和附件。
2. 当前项目资料。
3. 当前场域基础知识。
4. Scenario fallback。
5. 仅在 required input 无 fallback、存在高风险业务判断或执行路径无法确定时请求用户澄清或人工确认。

缺失 required input 不一定阻断；如果 Scenario 声明 fallback，则自动生成可完成部分、假设、缺口与置信度，不增加人工等待。

## 10. Skill Router

### 10.1 Skill 来源

Skill 选择只来自：

- Scenario `default_skills`
- Scenario `optional_skills`
- `skill-registry.json`
- 当前 Agent 的 Skill Binding

模型不能输出任意 Skill 名称。

### 10.2 Eligibility

Skill 必须同时满足：

- Registry 存在；
- 状态允许当前模式；
- SkillDefinition 已安装；
- Binding 已启用；
- Capability Profile 与 Skill Hash 一致；
- required input 可获得或可通过上游节点产生；
- required Tool 已授权；
- required Knowledge 可解析；
- side effect 符合用户请求与审批策略。

### 10.3 Default / Optional / Conditional

- default Skill：Scenario 的首选执行方法。
- optional Skill：仅当输入材料、场域或交付要求匹配时加入。
- conditional Skill：条件满足后运行；条件必须可由结构化上下文判断。
- planned Skill：永不进入执行节点，只生成 Capability Gap。

## 11. Skill 之间的兼容语义

当前 Skill Profile 存在同义但不一致的输入输出名，例如：

```text
research_evidence / research_material
research_findings / analysis_findings
opportunity_definition / opportunity_candidates
```

新增 Catalog 级 Compatibility Map：

```json
{
  "evidence_bundle": ["research_evidence", "research_material", "provider_summary"],
  "analysis_findings": ["competitive_analysis", "jtbd_analysis", "research_findings"],
  "opportunity_candidates": ["opportunity_definition", "opportunity_list"],
  "prioritization_candidates": ["issue_list", "analysis_findings", "opportunity_candidates"],
  "priority_output": ["prioritized_issues", "action_plan"]
}
```

原始 Profile 字段保持兼容，Plan Compiler 使用规范化类型判断上下游绑定。

## 12. Knowledge Router

每个执行节点增加 `knowledge_bindings`：

```yaml
knowledge_bindings:
  required:
  optional:
  excluded:
```

读取优先级：

```text
当前任务上下文
→ 场域基础知识
→ Scenario 直接相关方法
→ 场域洞察知识
→ 场域经验知识
→ 跨场域参考
```

约束：

- 不整库读取。
- 不读取无关场域。
- 用户材料是材料归纳类任务的主输入。
- 原始项目资料不得自动升级为稳定 Knowledge。
- 每个 Plan 冻结 Knowledge ID、路径、内容 Hash 和状态。

## 13. 外部 Evidence 路由

在路由上下文中新增：

```yaml
evidence_requirement:
  external_evidence_required: true | false
  freshness:
  minimum_sources:
  independent_sources:
```

以下表达触发 `external_evidence_required=true`：

- 公开资料
- 最新 / 指定年份
- 行业、市场、竞品、标杆
- 品牌表现
- 搜索、调研、网页

硬约束：

```text
external_evidence_required=true
→ Plan 至少包含一个可使用 web_research 的执行节点
→ 用户的个人 Agent 必须已获得 Tool Grant
→ Provider 必须 healthy
→ 已授权的只读 Web Research 直接执行，不重复逐调用确认
→ 外部写入、不可逆操作或高风险参数才进入单次确认
```

Tavily、Firecrawl 等只读 Provider 子调用继承当前用户个人 Agent 的 Tool Grant。授权缺失时在执行前输出 Capability Gap；授权有效时直接运行，禁止退回无 Search 的普通 Agent。

## 14. Plan Compiler

### 14.1 Plan 节点

扩展 `SkillPlanNode`：

- `task_id`
- `scenario_id`
- `skill_id`
- `skill_status`
- `depends_on`
- `parallel_group`
- `condition`
- `input_bindings`
- `output_contract`
- `knowledge_bindings`
- `required_tool_names`
- `completion_criteria`
- `side_effect`

### 14.2 确定性编译

LLM 负责建议 Task/Scenario 和 Skill 组合；服务端负责确定性验证和编译。

当 LLM Draft 无效时，使用 Registry 映射生成 fallback：

1. 选择主 Scenario 的 default Skills。
2. 添加次 Task Scenario 的 default Skills。
3. 根据 dependencies 连接。
4. 对可并行上游设置 parallel group。
5. 添加满足触发条件的 optional Skills。
6. planned/missing Skill 写入 Gap，不加入执行。
7. 最多 6 个节点、深度 4、并行 3。

不再要求一个 Skill 精确覆盖用户所有展示形式。

## 15. Completion Check

新增正式 `CompletionCheckResult`：

- `completed`
- `scenario_outputs`
- `missing_outputs`
- `criteria_results`
- `evidence_sufficient`
- `confidence`
- `gaps`
- `human_confirmation_required`
- `reason`

检查由服务端自动执行，不构成人工 Review 门禁。顺序如下：

1. required Skill 节点是否完成。
2. Scenario required outputs 是否有上游 Result 支持。
3. required completion criteria 是否满足。
4. factual Claim 是否有 Source。
5. external evidence 是否达到数量与独立性要求。
6. Knowledge 和 Skill 状态是否披露。
7. 是否命中明确的人工确认条件。

只有 required output、必需证据或安全条件缺失时才阻断完整完成。optional criteria 未满足时输出 `partial` 和缺口，不转入等待审批；命中明确人工确认条件时才使用 `waiting_approval`。

## 16. Synthesis 与最终报告

最终报告不要求某个 Skill 直接输出“策略地图”“汇报稿”等所有格式。

Synthesis 输入：

- 原始用户目标；
- Task/Scenario Route；
- 用户要求的最终输出；
- 已验证 SkillNodeResult；
- Completion Check；
- Source、Evidence、Artifact；
- Skill/Knowledge 状态；
- Gaps 和 Human Confirmation。

Synthesis 规则：

- 事实必须绑定 Source。
- 推断必须绑定上游 Result 或 Evidence。
- 建议必须说明依据。
- 不新增工具事实。
- 不删除局限。
- 按用户要求的最终结构编排 sections。
- 输出必须覆盖主 Scenario outputs 和 completion criteria。

## 17. Fallback 与 Human Confirmation

### Skill 不存在

- 保留 Registry 状态。
- 优先自动选择已存在的安全替代 Skill。
- planned Skill 只进入 Gap。
- 没有可接受替代时，先返回可完成部分和 Capability Gap；只有高风险业务决策或不可逆操作才转人工确认。

### Knowledge 不足

- 使用通用方法。
- 标注“场域适配未验证”。
- 价格、库存、履约、交易规则、合规和政策不得推断。

### 用户证据不足

- 输出假设与待补资料。
- 不将假设写成事实。

### Planner 无法完成

生成结构化 Capability Gap 和可读 Assistant Message，不只记录 `PlannerUnavailable`。

## 18. Retry 语义

修改 Retry 路由：

- 有 Plan：继续使用 `retry_orchestrated`。
- 无 Plan，但原请求是 auto orchestration：重新运行 Task/Scenario Router 和 Plan Compiler。
- 明确 single：执行原显式 Skill。
- 明确 off：普通 Agent。
- 需要 external evidence 的请求不得在 Retry 中切换为 off。

Retry 必须继承：

- 原始输入；
- Thread、Workspace、Project；
- requested orchestration mode；
- Task/Scenario route intent；
- Tool Approval 边界。

## 19. Timeout 预算

建议默认值：

```env
AGENTMESH_CHAT_LLM_TIMEOUT_SECONDS=120
```

执行预算：

| 执行类型 | 单次预算 |
| --- | ---: |
| 普通对话 | 120 秒 |
| 普通 Skill 节点 | 120 秒 |
| 需要 `research.request` 的 Skill 节点 | 180 秒 |
| 父 Run | 300 秒 |

超时错误必须返回可读信息，区分：

- 模型超时
- Provider 超时
- Skill 节点超时
- 父 Run 超时

## 20. 前端展示

Plan 卡片增加：

- 主 Task / 次 Task
- Scenario
- 串行 / 并行 / 条件关系
- Skill Registry 状态
- Tool 要求
- Knowledge Bindings
- required / optional / planned
- Completion Criteria
- Capability Gap

PlannerUnavailable 不再只显示技术错误名；显示缺失能力、不可用 Skill、可执行部分和下一步。

## 21. 目标任务的预期 Plan

对于宠物主粮请求，Router 应生成：

```text
主 Task：define-strategy
次 Task：find-direction、understand-users
执行关系：parallel_then_merge

Scenario A：competitor-benchmark-research
  默认 Skill：ds-skill-competitor-strategy-analysis
  按需 Skill：ur-skill-competitive-analysis
  Evidence：external/current

Scenario B：user-journey-insight
  默认 Skill：ur-skill-journey-map
  按需 Skill：ur-skill-jobs-to-be-done、ds-skill-user-insight-synthesis

Scenario C：strategy-synthesis
  默认 Skill：ds-skill-strategy-map-generation

Scenario D：priority-roadmap
  默认 Skill：ur-skill-issue-prioritization
```

执行图：

```text
竞品与标杆研究 ─┐
                 ├─ 策略提炼 ─ 优先级与路线 ─ 最终报告
用户旅程洞察 ───┘
```

如果设计策略 Skill 仍为 draft，只要 Registry、Binding、权限和自动质量检查通过，就可以参与执行，并在结果中披露 draft 状态。`planned` Skill 仍不得执行，系统应自动选择安全替代或输出 Capability Gap。

## 22. 实施阶段

### Phase 1：Catalog Compiler

- 定义 Runtime Catalog Schema。
- 编译 Task、Scenario、Skill、Knowledge Registry。
- 校验断链、状态、依赖和 Hash。
- 提供确定性加载接口。

独立交付：只提供 Catalog 和校验，不改变现有路由。

### Phase 2：Task/Scenario Router

- 新增 `TaskRoutingResult`。
- 支持主 Task、次 Task、Context、Input Check、Human Confirmation。
- 加入路由测试集。

独立交付：返回 Task/Scenario 路由结果；通过自动化测试后可以直接继续 Phase 3，无需等待阶段性人工 Review。

### Phase 3：Skill/Knowledge Plan Compiler

- 根据 Registry 选择 Skill。
- 生成串行、并行和条件节点。
- 绑定 Knowledge、工具和 completion criteria。
- planned Skill 生成 Gap。

独立交付：可以展示完整 Plan；通过自动化测试后继续 Phase 4，不设置人工审批门禁。

### Phase 4：Execution 与 Completion Check

- 执行允许的 Skill。
- 保持用户级 Tool Grant，并仅对外部写入、不可逆操作和高风险参数执行单次确认。
- 执行 Completion Check。
- 输出 partial、gap 或 human confirmation。

独立交付：通过功能开关在开发和测试环境执行，生产启用只进行一次合并前 Review。

### Phase 5：Synthesis、Retry 与 Timeout

- 按 Task/Scenario 输出最终报告。
- Retry 保持路由语义。
- 禁止静默 off 降级。
- 应用分层超时。
- 更新错误 UI。

独立交付：替换现有 auto orchestration 默认路径。

## 23. 测试矩阵

至少覆盖：

1. 竞品与标杆研究。
2. 用户材料归纳。
3. 用户旅程洞察。
4. 页面体验走查。
5. 数据异常诊断。
6. 根因分析。
7. 方案生成。
8. 方案比较。
9. 策略提炼。
10. 优先级与路线。
11. 指标与验证。
12. 跨 Task 串行任务。
13. 上游 Task 并行、下游汇合。
14. planned Skill 降级。
15. Knowledge 缺失。
16. Tool Grant 缺失。
17. 低置信度澄清。
18. Human Confirmation。
19. Retry 保持编排。
20. 长任务超时分层。

## 24. 验收标准

- 五类一级 Task 路由准确率达到评测集门槛。
- 15 个 Scenario 全部可被路由测试覆盖。
- 模型不能生成 Registry 之外的 Task、Scenario 或 Skill ID。
- planned Skill 永不进入真实执行。
- 外部资料请求必含可授权的 Web Research 能力。
- DAG 满足节点、深度和并行上限。
- 每个完成输出可追溯到 SkillResult 和 Source。
- Completion Check 不通过时不会误报 completed。
- Planner 失败时用户收到 Capability Gap。
- Retry 不会从 auto 静默降级到 off。
- 宠物主粮原始请求不再产生 PlannerUnavailable 或 ModelTimeoutError。

## 25. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| Wiki Registry 仍为 draft | 允许路由和执行，披露状态并依靠自动契约测试；`planned` 仍禁止执行 |
| Skill ID 与 Runtime SkillDefinition 不一致 | Catalog 编译阶段建立显式 binding 并校验 |
| 多 Skill 调用成本上升 | 节点最多 6、并行最多 3、按需 Knowledge |
| 模型路由不稳定 | Registry 枚举 + 服务端确定性验证 |
| Knowledge 读取过量 | required/optional/excluded 三段式绑定 |
| 缺证据时策略被过度推断 | Completion Check + Evidence Gate |
| 新 Router 不稳定 | 保留旧 Orchestration，通过配置回滚 |

回滚只切换 Router 版本，不修改已持久化历史 Run。

## 26. 预计工作量

- Phase 1：2～3 天
- Phase 2：2～4 天
- Phase 3：3～5 天
- Phase 4：3～5 天
- Phase 5：2～4 天
- 真实任务回归与灰度：2～3 天

总计约 14～24 个开发日。

## 27. 最脆弱假设

本方案假设 Wiki 中的 Task、Scenario、Skill 和 Registry ID 在实现周期内保持基本稳定。`draft` 状态不阻断开发或执行，只要求状态披露和自动契约校验；只有 `planned`、引用断链或安全条件不满足时才禁止执行。
