# Task → Scenario → Skill → Knowledge 编排 Todolist

- 对应方案：[`2026-08-24-task-scenario-skill-orchestration.md`](./2026-08-24-task-scenario-skill-orchestration.md)
- 状态：实施中，Phase 1～3 已完成主体，Phase 4～5 进行中
- 执行顺序：Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5
- 原则：方案确认后连续实施。每个 Phase 用自动化测试和静态检查收口，不等待逐阶段人工审核；合并前只做一次集中 Code Review。

## 0. 实施前检查

- [x] 保存当前 `git status` 和相关 diff，避免 Planner 改造覆盖已有 Firecrawl Evidence Pipeline 改动；不要求先完成独立 Review 或提交。
- [x] 确认工作区没有意外 staged files。
- [x] 运行一次后端和前端基线测试；结果只用于对比，不作为额外人工审批门禁。
- [x] 保存宠物主粮失败 Run 的路由、错误码和事件序列作为回归证据。
- [x] 记录 `wiki/user-research` 的 Source Sync 版本和更新时间。
- [x] 通过编译脚本自动校验 Task、Scenario、Skill Registry ID 和 `planned` 状态。
- [x] 为新 Planner 增加独立功能开关，便于测试和回滚。

## Phase 1：Runtime Catalog Compiler

### 1.1 Catalog Schema

- [x] 新建 `agentmesh/task_catalog/user-research-v1/`。
- [x] 定义 `catalog.json` 元数据结构。
- [x] 定义 `tasks.json` Schema。
- [x] 定义 `scenarios.json` Schema。
- [x] 定义 `task-skill-mapping.json` Schema。
- [x] 定义 `skill-registry.json` Schema。
- [x] 定义 `knowledge-registry.json` Schema。
- [x] 定义 `routing-result.schema.json`。
- [x] 定义 `completion-check.schema.json`。
- [x] 定义状态枚举：`draft`、`reviewed`、`validated`、`planned`。
- [x] 定义执行关系枚举：`serial`、`parallel`、`parallel_then_merge`、`conditional`。

### 1.2 Catalog 编译脚本

- [x] 新建 `scripts/build_task_catalog.py`。
- [x] 读取 `wiki/user-research/05-registry-索引/task-registry.yaml`。
- [x] 读取 `skill-registry.yaml`。
- [x] 读取 `knowledge-registry.yaml`。
- [x] 读取 Task/Scenario frontmatter。
- [x] 校验 Task ID 唯一。
- [x] 校验 Scenario ID 唯一。
- [x] 校验 `parent_task` 存在。
- [x] 校验 default/optional Skill ID 在 Registry 中存在。
- [x] 校验 Knowledge ID 在 Registry 中存在或被明确标记为描述型引用。
- [x] 校验 planned Skill 不被输出为 executable。
- [x] 校验 Scenario outputs 非空。
- [x] 校验 completion criteria 非空。
- [x] 校验 source_path 位于允许根目录内。
- [x] 计算每个源文件 Hash。
- [x] 计算最终 Catalog Hash。
- [x] 以确定性顺序输出 JSON。

### 1.3 Runtime Loader

- [x] 新建 `agentmesh/task_routing/catalog.py`。
- [x] 实现 Catalog 加载和 Schema 校验。
- [x] 禁止 Runtime 请求期间扫描原始 Wiki。
- [x] 暴露按 Task ID 查询接口。
- [x] 暴露按 Scenario ID 查询接口。
- [x] 暴露按 Skill Registry ID 查询接口。
- [x] 暴露按 Knowledge ID 查询接口。
- [x] 返回 Catalog Hash 和版本。

### 1.4 Phase 1 测试

- [x] 测试五个一级 Task 全部可加载。
- [x] 测试 15 个 Scenario 全部可加载。
- [x] 测试重复 ID 被拒绝。
- [x] 测试缺失 parent Task 被拒绝。
- [x] 测试 Skill 断链被拒绝。
- [x] 测试 planned Skill 保持 planned。
- [x] 测试路径逃逸被拒绝。
- [x] 测试两次编译产生相同 Hash。
- [x] 运行 Phase 1 测试、全量 Pytest 和修改文件 Ruff。

### 1.5 Phase 1 完成条件

- [x] Runtime Catalog 可独立加载。
- [x] 不改变现有 Agent 路由行为。
- [x] Catalog 构建结果可提交到 Git。
- [x] Catalog 源与 Hash 可追溯。

## Phase 2：Task / Scenario Router

### 2.1 数据模型

- [x] 在 `agentmesh/task_routing/contracts.py` 中定义路由模型。
- [x] 实现 `TaskRoute`。
- [x] 实现 `ScenarioRoute`。
- [x] 实现 `RoutingContext`。
- [x] 实现 `InputCheckResult`。
- [x] 实现 `SkillRoutingDecision`。
- [x] 实现 `KnowledgeRoutingDecision`。
- [x] 实现 `HumanConfirmationDecision`。
- [x] 实现 `TaskRoutingResult`。
- [x] 限制所有 Task、Scenario、Skill ID 必须来自 Catalog。

### 2.2 Task Router

- [x] 新建 `agentmesh/task_routing/router.py`。
- [x] 实现五类一级 Task 的确定性触发规则。
- [x] 支持主 Task 与 secondary Tasks。
- [x] 按最终交付物选择主 Task。
- [x] 输出 `execution_relation`。
- [x] 抽取 Domain、Page、Journey、Project、User Segment、Data Scope。
- [x] 低置信度输出 alternative Scenarios。
- [x] 低置信度仅在歧义会改变执行路径或缺少无法降级的 required input 时澄清，否则按最高分方案继续并披露不确定性。
- [x] 确定性 Router 为默认路径，不依赖模型成功。
- [x] Router 输出经过 Catalog 成员校验，不能包含 Registry 外 ID。

### 2.3 Input Check

- [x] 根据 Scenario `required_inputs` 检查用户消息。
- [ ] 接入附件类型与附件元数据检查。
- [x] 检查当前项目摘要能否补足。
- [ ] 在执行前检查场域 Knowledge 是否能补足输入。
- [x] 检查 Scenario fallback。
- [x] 区分 missing required 和 missing optional。
- [x] 输出 `continue`、`degrade`、`clarify` 或 `human_confirmation`。

### 2.4 Evidence Requirement

- [x] 在 RoutingResult 增加 `external_evidence_required`。
- [x] 增加 freshness 要求。
- [x] 增加 minimum sources 和 independent sources。
- [x] 识别“公开资料、最新、指定年份、行业、市场、竞品、品牌、网页”等触发词。
- [x] 确认需要外部证据时不能降级到无 Search 的普通 Agent。

### 2.5 Phase 2 路由测试集

- [x] 从 Wiki 路由触发示例编译固定样本。
- [x] 测试竞品与标杆研究。
- [x] 测试已有用户资料归纳。
- [x] 测试用户分层。
- [x] 测试用户旅程。
- [x] 测试页面走查。
- [x] 测试反馈聚类。
- [x] 测试数据诊断。
- [x] 测试根因分析。
- [x] 测试解决方案生成。
- [x] 测试方案比较。
- [x] 测试策略提炼。
- [x] 测试优先级与路线。
- [x] 测试指标与验证。
- [x] 测试多 Task 并行后汇合。
- [x] 测试低置信度澄清。

### 2.6 Phase 2 完成条件

- [x] Preview API 可以返回 Task/Scenario RoutingResult。
- [x] 功能开关关闭时保持旧 execute 路径。
- [x] 宠物主粮请求主 Task 为 `define-strategy`。
- [x] 次 Task 包含 `find-direction` 和 `understand-users`。
- [x] 复合展示请求不再归一化为单一 `design_analysis`。

## Phase 3：Skill / Knowledge Plan Compiler

### 3.1 Skill Registry Binding

- [x] 新建 Runtime Registry Skill ID 到稳定 `SkillDefinition.name` 的显式 Binding，避免持久化路径相关 ID。
- [x] 校验绑定 Skill 已安装。
- [x] 校验 Skill Hash 和 Profile Hash。
- [x] 校验 Agent Skill Binding。
- [x] 校验 Tool Grant。
- [x] 校验 Skill 状态是否允许当前模式。
- [x] draft Skill 可以执行，但必须披露状态并通过自动契约校验。
- [x] planned Skill 不生成执行节点。

### 3.2 Compatibility Map

- [x] 定义 Evidence 到研究材料的兼容关系。
- [x] 定义竞品、JTBD 与研究发现的兼容关系。
- [x] 定义机会候选到优先级输入的兼容关系。
- [x] 定义分析发现到优先级输入的兼容关系。
- [x] 定义优先级结果到指标上下文的兼容关系。
- [x] 更新核心 Skill Profile 的 Task 和 Archetype 元数据。
- [x] 保留原 `input_kinds` / `output_kinds` 兼容。

### 3.3 Knowledge Bindings

- [x] 扩展 `SkillPlanNode`，增加 `task_id`。
- [x] 增加 `scenario_id`。
- [x] 增加 `skill_status`。
- [x] 增加 `knowledge_bindings`。
- [x] 增加 `required_tool_names`。
- [x] 增加 `completion_criteria`。
- [x] 增加 `condition`。
- [x] Plan 冻结 Catalog Hash 和 Knowledge ID，Catalog 冻结路径、Hash 和状态。

### 3.4 Plan Compiler

- [x] 根据 Scenario 添加可绑定的 default Skills。
- [x] default 不可用时按映射选择可执行 optional Skill。
- [x] 根据 Scenario dependencies 生成串行关系。
- [x] 为独立上游生成 parallel group。
- [ ] 为 conditional Skill 生成可验证条件。
- [x] required Task 不依赖 optional 节点；当前路由生成的节点均为 required。
- [x] planned Skill 进入 Capability Gap。
- [x] 限制最多 6 个节点。
- [x] 限制 DAG 深度最多 4。
- [x] 限制并行节点最多 3。
- [x] 校验每个节点输入可以由用户或兼容的上游输出提供。
- [x] 校验 external evidence 任务至少有一个 `web_research` 能力节点。

### 3.5 确定性 Fallback

- [x] 新 Task Router 开启时直接按 Task/Skill Mapping 确定性生成 Plan，不依赖 LLM Planner。
- [x] 不再要求一个 Skill 覆盖全部最终展示形式。
- [x] 无可执行 Skill 时输出可读 Capability Gap。
- [x] 需要外部证据但无 Research 能力时失败关闭，不调用普通模型伪装完成。

### 3.6 Phase 3 测试

- [x] 串行 Plan。
- [x] 并行 Plan。
- [x] parallel-then-merge Plan。
- [ ] conditional Plan。
- [x] Skill Binding 被禁用。
- [x] Tool Grant 被撤销。
- [x] draft Skill 执行并正确披露状态。
- [x] planned Skill 降级。
- [x] Knowledge 断链。
- [x] 输入绑定兼容映射。
- [x] DAG 循环拒绝。
- [x] 节点/深度/并行上限。

### 3.7 Phase 3 完成条件

- [x] Preview 显示 Task、Scenario、Skill 和 Knowledge Plan。
- [x] 宠物主粮请求产生多个可解释 Skill 节点。
- [x] PlannerUnavailable 在用户界面呈现为可读 Capability Gap，不静默降级。

## Phase 4：执行与 Completion Check

### 4.1 执行器

- [x] 执行前重新校验 Skill 状态和 Hash。
- [x] 执行前重新校验 Tool Grant。
- [x] 执行前重新校验 Project 权限。
- [x] 从冻结 Catalog 按节点加载最小 Knowledge 摘要与来源元数据。
- [x] Web Research 节点继承当前用户个人 Agent 的 Tool Grant，不再重复逐调用审批。
- [x] 外部写入、不可逆操作或高风险参数仍保留单次调用确认。
- [x] 上游 SkillResult 按依赖传递。
- [x] 并行节点使用现有并发上限。
- [x] 失败节点使依赖节点 skipped。
- [x] 无关分支可以继续。

### 4.2 Completion Check

- [x] 新增 `CompletionCheckResult`。
- [x] 校验 Scenario outputs。
- [x] 校验 completion criteria。
- [x] 校验 required 节点。
- [x] 校验 Evidence 来源。
- [x] 校验 external evidence 数量和独立性。
- [x] 校验 draft/planned 状态披露。
- [x] 校验 Human Confirmation。
- [x] 生成 missing outputs 和 gaps。
- [x] 未通过时禁止 completed。

### 4.3 Phase 4 测试

- [x] 完整成功。
- [x] Partial 分支。
- [x] Skill 失败。
- [x] Tool 拒绝。
- [x] Knowledge 缺失。
- [x] Evidence 不足。
- [x] 仅高风险、不可逆或无法降级的必需输入触发人工确认，普通 partial 不触发。
- [x] 重启恢复。
- [x] 取消。
- [x] 幂等重复请求。

### 4.4 Phase 4 完成条件

- [x] 通过功能开关在开发和测试环境执行新 Plan。
- [x] Completion Check 持久化在 SkillPlan。
- [x] Synthesis Claim 和 Source 保持现有结果血缘校验。

## Phase 5：Synthesis、Retry、Timeout 与 UI

### 5.1 Synthesis

- [x] Synthesis 接收 RoutingResult。
- [x] 接收 Scenario outputs。
- [x] 接收执行前 Completion Check，并在 Synthesis 后重新计算最终结果。
- [x] 接收用户最终展示要求。
- [x] 按用户要求组织 sections。
- [x] 事实 Claim 必须有 Source。
- [x] 推断必须有上游 Result 或 Evidence。
- [x] 建议必须绑定上游 Result。
- [x] 通过 Plan Nodes 保留 limitations、Skill 状态和 Knowledge 状态。
- [x] 不能新增未检索事实。

### 5.2 Retry

- [x] 有 Plan 时使用 `retry_orchestrated`。
- [x] 无 Plan 但原请求为 auto 时重新执行 Task Router。
- [x] single 只重跑原显式 Skill。
- [x] 仅非 auto 请求允许普通 Agent Retry。
- [x] external evidence 任务禁止 Retry 降级为 off。
- [x] Retry 继承 Thread、Project、Task Route 和审批约束。

### 5.3 Timeout

- [x] `.env.example` 将普通 Chat 默认改为 120 秒。
- [x] 普通 Skill 节点保持 120 秒。
- [x] Web Research Skill 节点使用 180 秒。
- [x] 父 Run 保持 300 秒。
- [x] Model Timeout 转为可读错误。
- [x] Provider Timeout 与 Model Timeout 分开展示。
- [x] Timeout 后不自动重复外部调用。

### 5.4 前端

- [x] Plan 卡展示主 Task 和次 Task。
- [x] 展示 Scenario。
- [x] 展示串行、并行和条件关系。
- [x] 展示 Skill 状态。
- [x] 展示 Knowledge Bindings。
- [x] 展示 required / optional / planned。
- [x] 展示 Completion Criteria。
- [x] 展示 Capability Gap。
- [x] PlannerUnavailable 显示缺失能力和可继续部分。
- [x] ModelTimeoutError 显示可操作建议。

### 5.5 Phase 5 完成条件

- [x] 新 Router 在功能开关启用后成为默认编排路径，不增加逐用户审核；关闭开关可回滚。
- [x] Retry 不再静默降级。
- [x] 长任务不再因普通 60 秒默认值失败。
- [x] 用户能看到完整执行计划、进度、证据、缺口和报告。

## 6. 原始问题回归

使用原始宠物主粮请求验证：

- [x] 主 Task 为 `define-strategy`。
- [x] 次 Task 包含 `find-direction`。
- [x] 次 Task 包含 `understand-users`。
- [x] Scenario 包含 `competitor-benchmark-research`。
- [x] Scenario 包含 `user-journey-insight`。
- [x] Scenario 包含 `strategy-synthesis`。
- [x] Scenario 包含 `priority-roadmap`。
- [x] Plan 中至少包含 2 个可执行 Skill。
- [x] 需要公开资料，因此 Plan 包含 Web Research。
- [x] 用户级 Tool Grant 有效时，只读 Web Research 直接执行；缺少授权时执行前失败关闭。
- [x] 真实 Provider 端到端最终输出包含受限版策略地图。
- [x] 真实 Provider 端到端最终输出包含用户心智模型。
- [ ] 真实 Provider 端到端最终输出包含至少 5 条设计原则。
- [ ] 真实 Provider 端到端最终输出包含机会点清单。
- [ ] 真实 Provider 端到端最终输出包含 P0/P1/P2。
- [x] 真实 Provider 最终事实保留可点击 Source。
- [x] 具备授权能力时不出现 `PlannerUnavailable`。
- [x] Retry 不产生 `orchestration_mode=off`。
- [x] 真实长任务在 120/180/300 秒分层预算内完成，未出现 `ModelTimeoutError`。

## 7. 全量验证

- [x] `.venv/bin/python -m pytest`：1370 passed。
- [x] `.venv/bin/ruff check` 覆盖项目源码、测试和脚本；未检查未跟踪 Wiki 内的历史脚本。
- [x] `npm --prefix agentmesh-demo test -- --run`：154 passed。
- [x] `npm --prefix agentmesh-demo run api:types`。
- [x] `npm --prefix agentmesh-demo run build`，Bundle Budget 通过。
- [x] Skill Catalog 回归测试通过。
- [x] Task Catalog 编译两次 Hash 一致。
- [x] 使用真实 Provider 完成 Tavily + Firecrawl Smoke；当前案例因外部来源 3/5 正确标记 Partial。
- [x] 本地持久化数据库无 active Run 遗留。
- [x] `git diff --check` 通过。
- [x] `.env`、Key、Cookie、数据库未进入 Git。

## 8. 灰度与发布

- [x] 本地 `.env` 已在功能开关下启用新 Router，未展示或提交其他环境变量。
- [x] 自动运行固定路由评测集，并对失败样本集中排查。
- [x] 每类 Task 使用代表样本测试，不逐一增加人工审核。
- [x] 验证 draft Skill 状态披露。
- [x] 验证 planned Skill 不执行。
- [ ] 使用持久化数据库验证新 Router 的进程重启恢复；Retry 已通过自动测试。
- [x] 验证关闭功能开关可保留旧 Router。
- [x] 更新 README 和环境变量示例。
- [ ] 关联 GitHub Issue 和 PR。
- [x] 完成一次合并前架构、安全和发布范围 Review；Phase 内未重复 Review。
- [ ] 合并后关闭对应 Issues。

## 9. 安全与运营

- [x] Firecrawl Key 轮换由用户明确豁免；继续使用当前 Key 的泄露风险作为已接受残余风险记录。
- [x] 自动测试和差异中未发现 Tavily Key。
- [x] Runtime Catalog 不包含内部密钥和原始用户材料。
- [x] Skill 不能绕过用户级 Tool Grant；已授权只读工具不重复审批，高风险写入仍需单次确认。
- [x] 外部内容继续使用现有 Prompt Injection 隔离。
- [x] 仅高风险业务规则、不可逆操作和无法降级的必需输入进入 Human Confirmation。
- [x] 多 Skill 节点数、深度、并发和调用次数有上限。
- [x] Timeout 和取消不会自动重复外部调用。

## 10. 完成定义

全部满足以下条件才关闭任务：

- [x] 五类 Task 和 15 个 Scenario 可稳定路由。
- [x] Runtime 不创建 Registry 外的 Skill。
- [x] 不新增任务专用 Skill。
- [x] 多 Skill DAG 可执行、可恢复、可解释。
- [x] Knowledge 按节点最小化绑定并从冻结 Catalog 加载摘要。
- [x] Completion Check 决定最终完整或 Partial 状态。
- [x] Synthesis 按用户要求编排报告。
- [x] 需要搜索的任务不会退回无 Search 普通模型。
- [ ] 原始宠物主粮请求通过真实 Provider 端到端验收。
- [x] 自动测试、构建和安全检查完成。
- [x] 完成一次合并前架构、安全和发布范围 Review，不要求逐阶段人工审核。
- [x] Firecrawl Key 轮换已由用户明确豁免并记录残余风险。
