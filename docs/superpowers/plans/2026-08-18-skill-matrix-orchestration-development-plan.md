# AgentMesh Skill Matrix 多技能编排完整开发方案

> **状态：** 待审核
> **日期：** 2026-08-18
> **首期范围：** 10 个已接入 Wiki 领域 Skill + 11 个 Legacy 平台原子能力
> **目标：** 实现自然语言意图理解、Skill 语义召回、结构化 DAG 规划、治理校验、受控执行、结果标准化、综合总结和完整交互闭环。

---

## 一、项目背景

AgentMesh 当前已经具备两类能力入口：

1. `agentmesh/chat_skills.py` 中的 11 个 Legacy `$` 命令，主要承担 Memory、Data、Research、Risk、Note、Brief 和 System 等平台原子能力。
2. 由 `SkillCatalogService` 发现并持久化的 Agent Skills 标准目录能力，目前已有 10 个 Wiki Skill 完成首批接入。

Runtime v2 已经具备以下基础设施：

- OpenAI Agents SDK 运行器；
- 流式 Agent Run；
- SDK Session 与上下文压缩；
- Function Tool 与 MCP 治理；
- Tool Grant；
- 按 `call_id` 独立审批；
- Artifact；
- Memory 与 RAG 权限过滤；
- Tracing 与 Audit；
- 幂等 Run；
- 取消与重启失败恢复；
- 24 次 Tool Call 上限；
- 300 秒整轮执行时限。

当前尚未具备：

- 对自然语言目标的结构化意图提取；
- 从 Skill Catalog 中进行语义候选召回；
- 生成多个 Skill 的依赖 DAG；
- 多 Skill 执行前计划确认；
- DAG 节点并发、失败传播和恢复；
- 统一的 Skill 节点结果协议；
- 带来源和 Skill 血缘的最终综合结果；
- 多 Skill 计划预览、调整和执行进度 UI。

本方案的目标是补齐这些能力，同时保持 AgentMesh 作为权限、审批、状态、审计和持久化的唯一控制面。

---

## 二、已确认的产品决策

### 2.1 首期 Skill 范围

首期只覆盖：

- 10 个已接入、可治理、可测试的 Wiki 领域 Skill；
- 11 个 Legacy 平台原子能力。

其中：

- 10 个 Wiki Skill 是用户可见的领域工作流节点；
- 11 个 Legacy 能力只作为底层依赖和 Tool 使用；
- Legacy 能力不作为与领域 Skill 同级的推荐项；
- 全部 78 个 Wiki Skill 的接入属于后续独立版本。

### 2.2 多 Skill 确认规则

- 只有 1 个低风险领域 Skill 时，可以直接执行；
- 计划中包含 2 个及以上领域 Skill 时，必须先展示计划并由用户确认；
- 计划确认不等于 Tool 审批；
- 所有本地写入和外部写入仍在实际调用时逐 `call_id` 审批。

### 2.3 用户调整范围

用户可以：

- 从服务端返回的候选 Skill 中增加或删除节点；
- 调整依赖允许范围内的执行顺序；
- 选择只执行计划中的部分可选节点。

用户不能：

- 添加候选集之外的任意 Skill；
- 自定义任意 DAG 边；
- 删除输出契约依赖的必需节点；
- 绕过 Skill readiness、Tool Grant、Memory Binding 或 Risk Policy。

每次计划修改必须携带 `expected_version`，服务端重新计算依赖并执行完整校验。

### 2.4 首期业务方向

第一版优先优化内部设计工作流：

- 设计前：需求理解、研究、历史实验、竞品和 Brief；
- 设计中：方案生成、原型、评审、可用性和无障碍；
- 设计后：交付、复盘、实验、知识沉淀。

第一版不追求跨行业、跨部门的通用编排平台。

### 2.5 模型与 Runtime 决策

- Planner 复用当前用户 Agent 已选择的模型；
- 不新增独立 Planner 模型配置；
- 一个父级 `AgentRun` 负责整份计划；
- DAG 节点不是递归 Agent Run；
- 节点不独立向聊天线程写消息；
- 父级 Run 只投影一条用户消息和一条最终综合消息。

---

## 三、建设目标与成功标准

### 3.1 功能目标

系统能够从自然语言请求中识别：

- 用户最终目标；
- 当前设计阶段；
- 已提供输入；
- 需要的证据；
- 期望交付物；
- 时间、权限和写入约束；
- 成功完成条件。

系统能够：

1. 从已启用、已授权、已就绪的 Skill 中召回最多 12 个候选；
2. 生成最多 6 个领域 Skill 的结构化 DAG；
3. 正确表达节点依赖、并行关系、输入绑定和输出契约；
4. 对多 Skill 计划进行确认；
5. 按依赖执行节点；
6. 对每个节点产出结构化结果；
7. 生成带来源、限制和 Skill 血缘的最终综合结果；
8. 支持取消、审批、部分失败、重连和重启后的安全终止。

### 3.2 质量目标

- 40 条设计请求评测集中，目标 Skill Top-3 Recall 不低于 90%；
- 未就绪、未授权、已停用、跨用户和跨项目 Skill 的召回率必须为 0；
- 规划结果 100% 通过结构化 Schema，或进入明确的确定性降级；
- 多 Skill 计划 100% 在执行前等待确认；
- 同一个逻辑节点、计划审批、Tool 审批最多执行一次；
- 最终综合结果中的每条核心结论都能关联到节点结果和来源；
- 不把 API Key、Token、主机绝对路径、隐藏推理和完整私有记忆正文写入事件或 Trace；
- 不影响现有 Legacy 路径和单 Skill Runtime v2 路径。

---

## 四、非目标范围

首期不建设：

- 将全部 89 个能力直接暴露给模型自由选择；
- 递归 Skill 编排；
- Skill 自己再调用 Skill Planner；
- 用户自由绘制完整 DAG；
- 自动外部写入；
- 自动发布项目或团队知识；
- 在 FastAPI 进程中执行第三方 Skill 脚本；
- PostgreSQL、多 Workspace、多进程调度或水平扩容；
- 替换 OpenAI Agents SDK 的自研模型循环。

---

## 五、总体架构

```text
用户输入 + 当前项目/线程上下文
                │
                ▼
        Intent Analyzer
        结构化意图理解
                │
                ▼
    Skill Semantic Retriever
    语义召回最多 12 个候选
                │
                ▼
          Skill Planner
      生成结构化 Skill DAG
                │
                ▼
   AgentMesh Policy Validator
   权限、版本、依赖、风险校验
                │
        ┌───────┴────────┐
        │                │
   单 Skill 直接执行   多 Skill 计划预览
        │                │
        │          用户有限调整与确认
        │                │
        └───────┬────────┘
                ▼
       Bounded DAG Executor
       有界并发与失败传播
                │
                ▼
      Skill Result Normalizer
       统一节点结果协议
                │
                ▼
        Synthesis Agent
       来源约束的综合总结
                │
                ▼
 最终回答 + 来源 + Artifact + Audit
```

### 5.1 AgentMesh 控制层职责

AgentMesh 负责：

- Skill Catalog；
- Skill Capability Profile；
- 候选召回；
- 计划和节点持久化；
- DAG 校验和调度；
- 用户、项目和 Workspace 权限；
- Skill Binding；
- Tool Grant；
- Memory Binding；
- Risk Policy；
- 计划确认；
- Tool 调用审批；
- Artifact；
- Audit；
- 结果投影和记忆写入边界。

### 5.2 OpenAI Agents SDK 职责

OpenAI Agents SDK 负责：

- 结构化意图生成；
- 结构化计划生成；
- 节点 Skill Agent 执行；
- Function Tool/MCP 调用；
- Guardrail；
- Streaming；
- 节点结构化输出；
- 最终综合输出。

---

## 六、Skill 能力画像

### 6.1 文件组织

不扩展 Agent Skills 标准 Frontmatter。每个首批内置 Skill 增加：

```text
agentmesh/builtin_skills/<skill-name>/agents/agentmesh.yaml
```

Legacy 原子能力的画像定义在：

```text
agentmesh/skill_runtime/profiles.py
```

### 6.2 SkillCapabilityProfile

字段包括：

```yaml
skill_id: skilldef_xxx
skill_version: "1"
profile_version: "1"
primary_stage: pre_design
lifecycle_tags:
  - pre_design
capability_type: planning
input_kinds:
  - prd
  - design_requirement
output_kinds:
  - design_brief
examples:
  - 根据这份 PRD 生成设计 Brief
negative_examples:
  - 直接修改 Zero 设计稿
required_capabilities:
  - memory.project
side_effect: draft
planner_eligible: true
```

受控枚举：

#### 生命周期阶段

- `pre_design`
- `during_design`
- `post_design`
- `platform`

#### 能力类型

- `retrieval`
- `research`
- `analysis`
- `synthesis`
- `planning`
- `generation`
- `transformation`
- `review`
- `delivery`
- `knowledge`
- `platform`

#### 副作用

- `read`
- `draft`
- `local_write`
- `external_write`

### 6.3 首期画像规则

- 10 个 Wiki Skill：`planner_eligible=true`；
- 11 个 Legacy：`planner_eligible=false`；
- Legacy 可以作为节点依赖，但不能作为领域 Skill 推荐卡；
- Skill 画像版本、Skill 版本和 `content_hash` 不一致时，Skill 不允许进入 Planner；
- Wiki 语料未就绪时，依赖该语料的 Skill 不进入候选。

---

## 七、意图理解

### 7.1 SkillIntent

```json
{
  "goal": "形成 618 首页设计方案并完成上线前评审",
  "primary_stage": "during_design",
  "input_kinds": ["prd", "historical_experiment"],
  "deliverables": [
    "design_brief",
    "design_direction",
    "usability_review",
    "accessibility_review",
    "executive_summary"
  ],
  "constraints": {
    "external_write": false,
    "project_scope": "current"
  },
  "explicit_skill_names": [],
  "complexity": "workflow"
}
```

### 7.2 实现方式

- 使用一个无 Tool 的 SDK Intent Agent；
- 使用 `output_type=SkillIntent`；
- 输入只包含用户请求、当前项目摘要、线程摘要和附件类型；
- 不输入完整私有记忆正文；
- 不输入 Skill 指令；
- 不输入 Tool 凭据。

### 7.3 复杂度分类

- `direct`：一个 Skill 可完成；
- `assisted`：2-3 个 Skill；
- `workflow`：4-6 个 Skill。

显式 `$skill` 请求优先。除非用户明确要求更完整流程，否则显式 Skill 不扩展为多 Skill 计划。

---

## 八、Skill 候选召回

### 8.1 召回流程

1. 检查显式 Skill；
2. 过滤未启用、未绑定、未就绪、跨用户或跨项目 Skill；
3. 使用 FTS 召回；
4. Embedding 可用时进行向量召回；
5. 融合语义、阶段、输入输出和交付物分数；
6. 取 Top 12；
7. 将候选画像交给 Planner。

### 8.2 分数构成

```text
最终分数 =
  FTS / Embedding 语义相关度
  + 当前阶段加权
  + 输入类型匹配
  + 输出类型匹配
  + 明确交付物匹配
  + 最近成功使用加权
  - 负例匹配惩罚
```

### 8.3 安全顺序

权限和 readiness 过滤必须发生在排序之前。不能先检索全部 Skill，再让模型决定是否有权使用。

### 8.4 降级

Embedding 不可用时：

- 使用 FTS；
- 保留阶段和输入输出加权；
- 不使用 Mock 结果冒充真实语义召回；
- 在诊断信息中记录 `embedding_unavailable`。

---

## 九、Skill Plan 和 DAG

### 9.1 SkillPlan

```json
{
  "id": "plan_xxx",
  "run_id": "run_xxx",
  "version": 1,
  "status": "waiting_approval",
  "intent": {},
  "candidate_skill_ids": [],
  "output_contract": {},
  "nodes": []
}
```

### 9.2 SkillPlanNode

```json
{
  "id": "node_a",
  "skill_id": "skill_prd_design_brief",
  "skill_version": "1",
  "skill_content_hash": "...",
  "reason": "需要先从 PRD 形成设计 Brief",
  "required": true,
  "depends_on": [],
  "parallel_group": null,
  "input_bindings": ["user.current_prd"],
  "output_contract": ["design_brief"],
  "side_effect": "draft",
  "status": "pending",
  "attempt": 0
}
```

### 9.3 限制

- 候选 Skill 最多 12 个；
- 领域节点最多 6 个；
- 并行节点最多 3 个；
- DAG 深度最多 4 层；
- Tool Call 总数最多 24 次；
- 父级 Run 最长 300 秒；
- 单节点最长 120 秒。

### 9.4 Planner

- 使用无 Tool 的 SDK Planner Agent；
- 输入为 `SkillIntent` 和最多 12 个安全画像；
- 不加载完整 Skill 指令；
- 输出 `SkillPlanDraft`；
- Planner 输出必须经过确定性校验；
- 校验失败时只允许一次基于错误码的修复；
- 第二次仍失败时，能单 Skill 降级则退回单 Skill，否则明确失败。

### 9.5 DAG 校验

校验包括：

- 是否有环；
- 是否超过节点、深度和并行上限；
- 是否存在未知 Skill；
- Skill 版本和哈希是否有效；
- 输入是否来自用户或上游输出；
- 输出契约是否可满足；
- 是否存在无意义重复能力；
- Skill 是否就绪、启用和授权；
- Tool Grant、Memory Binding 和 Risk Policy 是否满足。

---

## 十、计划确认和有限调整

### 10.1 确认规则

- 0-1 个领域节点：直接执行；
- 2 个及以上领域节点：进入 `waiting_plan_approval`；
- 未确认前不能加载 Skill 指令、读取 Skill Resource 或调用 Tool；
- 计划确认不批准任何 Tool。

### 10.2 用户可调整内容

PATCH 请求：

```json
{
  "expected_version": 2,
  "selected_skill_ids": ["skill_a", "skill_b"],
  "preferred_order": ["skill_a", "skill_b"]
}
```

服务端必须：

- 校验 Skill 是否在候选集；
- 校验版本；
- 重新生成依赖；
- 重新计算并行组；
- 检查输出契约；
- 计划版本加一。

出现版本冲突返回 409，前端刷新最新计划。

---

## 十一、持久化模型

新增 SQLite 表：

```sql
skill_plans(
  id TEXT PRIMARY KEY,
  run_id TEXT UNIQUE NOT NULL,
  version INTEGER NOT NULL,
  status TEXT NOT NULL,
  payload TEXT NOT NULL,
  updated_at TEXT NOT NULL
)

skill_plan_nodes(
  plan_id TEXT NOT NULL,
  id TEXT NOT NULL,
  status TEXT NOT NULL,
  payload TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(plan_id, id)
)

skill_node_results(
  node_id TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(node_id, attempt)
)
```

新增状态：

### Plan

- `planning`
- `waiting_approval`
- `approved`
- `running`
- `completed`
- `partial`
- `failed`
- `rejected`
- `cancelled`

### Node

- `pending`
- `ready`
- `running`
- `waiting_tool_approval`
- `completed`
- `failed`
- `skipped`
- `cancelled`

### Agent Run

增加：

- `planning`
- `waiting_plan_approval`
- `partial`

`partial` 属于终态，SSE 必须正常结束。

---

## 十二、DAG Executor

### 12.1 调度原则

- 使用确定性拓扑调度；
- 使用 SQLite 原子抢占 `ready` 节点；
- 使用 `asyncio.TaskGroup`；
- 单计划最多 3 个节点并发；
- 进程级最多 4 个活跃计划；
- 超出部分排队；
- 节点不能递归启动 Planner。

### 12.2 节点上下文

节点只接收：

- 当前 Skill 指令；
- 当前 Skill 已批准的 Resource；
- 明确的输入绑定；
- 上游标准化结果；
- 当前用户、项目、线程和 Run ID；
- 当前有效 Tool Grant 和 Memory Binding。

并行节点不写共享 SDK Session，避免并发覆盖。父线程历史仅用于 Intent 和 Planner。

### 12.3 重试

- `read` 和 `draft` 节点：只对明确的临时 Provider/网络错误重试一次；
- `local_write`：不自动重试；
- `external_write`：不自动重试；
- Tool 审批拒绝：节点失败或按计划声明为跳过；
- 超时：节点失败，不继续占用执行槽。

### 12.4 失败传播

- 必需节点失败：依赖它的节点标记为 `skipped`；
- 可选证据节点失败：计划继续，但标记降级；
- 至少存在可用必需结果，且输出契约仍可满足：执行综合，Run 结束为 `partial`；
- 输出契约无法满足：Run 结束为 `failed`；
- 取消：停止运行节点，剩余节点全部设为 `cancelled`。

### 12.5 审批暂停

任何节点触发 Tool 审批时：

- 暂停整个 DAG；
- 持久化 Scheduler 状态；
- 保存 Plan ID、Node ID、Skill hash、Tool Grant 快照和过期时间；
- 通过现有 call-ID CAS 恢复；
- 同一个审批最多恢复一次。

---

## 十三、统一节点结果协议

```json
{
  "node_id": "node_e",
  "skill_id": "skill_usability_review",
  "summary": "发现 4 个主要可用性问题",
  "findings": [],
  "recommendations": [],
  "sources": [],
  "confidence": 0.86,
  "limitations": [],
  "artifact_ids": [],
  "usage": {
    "total_tokens": 0
  },
  "degradation": null
}
```

规则：

- 节点必须使用 SDK 结构化输出；
- 结果 Schema 校验失败时节点失败；
- Legacy 原子能力结果由父节点吸收，不作为独立领域节点展示；
- 大结果进入 Artifact；
- 来源必须经过用户、项目和权限校验；
- 节点结果不能包含隐藏推理。

---

## 十四、综合总结

### 14.1 输入

Synthesis Agent 只接收：

- 最终输出契约；
- 标准化节点结果；
- 来源元数据；
- 计划降级状态。

不接收：

- 任意节点完整 Session；
- Tool 凭据；
- 隐藏推理；
- 未经标准化的原始 Tool 输出。

### 14.2 SkillSynthesisResult

```json
{
  "summary": "...",
  "sections": [],
  "claims": [
    {
      "text": "效率型首屏结构更适合当前目标",
      "node_result_ids": ["node_b", "node_c"],
      "source_ids": ["source_1"]
    }
  ],
  "limitations": [],
  "next_actions": [],
  "artifact_ids": []
}
```

### 14.3 校验

- 每条 Claim 必须引用存在的 Node Result；
- 每个 Source ID 必须存在且对当前用户可见；
- 不允许无来源的事实性结论；
- 允许模型建议，但必须标记为建议；
- 校验失败允许修复一次；
- 再失败时使用确定性的部分结果模板。

---

## 十五、API 设计

### 15.1 Skill 推荐

```text
POST /api/skills/recommendations
```

请求：

```json
{
  "content": "根据这份 PRD 生成首页方案并评审",
  "thread_id": "thread_xxx"
}
```

返回：

- 结构化 Intent；
- 最多 12 个候选 Skill；
- 分数组成；
- 推荐理由；
- readiness 和副作用；
- 不创建 Run；
- 不加载 Skill 指令。

### 15.2 创建 Run

继续使用：

```text
POST /api/agent/runs
```

增加：

```json
{
  "orchestration_mode": "auto",
  "explicit_skill_name": null
}
```

兼容期内原 `skill_name` 映射到 `explicit_skill_name`。

### 15.3 Plan API

```text
GET   /api/agent/runs/{run_id}/plan
PATCH /api/agent/runs/{run_id}/plan
POST  /api/agent/runs/{run_id}/plan/approve
POST  /api/agent/runs/{run_id}/plan/reject
POST  /api/agent/runs/{run_id}/retry
```

`retry` 必须使用新的 `client_turn_id`，复制并重新校验旧计划和可用结果，绝不自动恢复外部写入。

### 15.4 事件类型

新增：

```text
intent_normalized
skill_candidates_ranked
plan_created
plan_waiting_approval
plan_updated
plan_approved
plan_rejected
node_ready
node_started
node_waiting_tool_approval
node_completed
node_failed
node_skipped
node_cancelled
synthesis_started
synthesis_completed
run_partial
```

事件中只保存 ID、状态、分数、错误码和安全摘要。完整节点内容进入结果表或 Artifact。

---

## 十六、前端交互方案

### 16.1 AI 工作台是主入口

用户输入自然语言或上传 PRD 后：

- 单 Skill：显示 Skill Chip 并直接执行；
- 多 Skill：展示计划预览；
- 用户确认后执行；
- 执行过程中展示 DAG 进度；
- 最后展示综合结果。

### 16.2 Skill Plan Preview

展示：

- 目标；
- 输入；
- 预计交付物；
- Skill 节点；
- 串行和并行关系；
- 每个节点的作用；
- 读取范围；
- 是否写入；
- 计划限制和降级提示。

操作：

- 按计划执行；
- 有限调整；
- 只执行一个 Skill；
- 拒绝计划。

### 16.3 Progress UI

展示：

```text
✓ 生成设计 Brief
├─ ✓ 查询历史实验
├─ ● 竞品分析
└─ ○ 形成设计方案
   ├─ ○ 可用性评审
   └─ ○ 无障碍评审
```

状态包括：

- 等待；
- 可执行；
- 运行中；
- 等待审批；
- 完成；
- 失败；
- 跳过；
- 取消。

### 16.4 综合结果

按章节展示：

- 需求和历史依据；
- 设计方向；
- 可用性问题；
- 无障碍问题；
- 优先级；
- 下一步；
- 来源和限制。

每个章节可以查看：

- 由哪个 Skill 生成；
- 使用了哪些来源；
- 是否发生降级；
- 相关 Artifact。

### 16.5 Skill Center

Skill Center 负责：

- Skill 发现；
- readiness；
- 启停；
- 收藏；
- 来源；
- 显式启动。

增加“在工作台中使用”，进入预填 Skill 的工作台草稿，不在 Skill Center 直接执行。

交互参考：

```text
deliverables/skill-architecture-interactive-demo.html
```

该 HTML 仅作为交互原型，不进入生产组件。

---

## 十七、文件改动范围

本功能会修改超过 8 个文件，并新增多个模块。每个里程碑必须独立提交和审核，只允许一个 Writer 修改主工作区。

### 17.1 后端核心

- `agentmesh/models.py`
- `agentmesh/store.py`
- `agentmesh/agent_runtime/service.py`
- `agentmesh/agent_runtime/models.py`
- `agentmesh/agent_runtime/hooks.py`
- `agentmesh/routes/agent_runs.py`
- `agentmesh/routes/chat.py`
- `agentmesh/routes/skills.py`
- `agentmesh/skill_runtime/service.py`

### 17.2 新增模块

- `agentmesh/skill_runtime/profiles.py`
- `agentmesh/skill_runtime/retrieval.py`
- `agentmesh/skill_runtime/planner.py`
- `agentmesh/skill_runtime/plan_validation.py`
- `agentmesh/skill_runtime/executor.py`
- `agentmesh/skill_runtime/synthesis.py`

### 17.3 Capability Profile

在 10 个目录下新增：

```text
agentmesh/builtin_skills/<skill>/agents/agentmesh.yaml
```

### 17.4 前端

- `agentmesh-demo/src/features/workspace/api.ts`
- `agentmesh-demo/src/features/workspace/types.ts`
- `agentmesh-demo/src/features/workspace/queries.ts`
- `agentmesh-demo/src/features/workspace/keys.ts`
- `agentmesh-demo/src/pages/Workspace.tsx`
- `agentmesh-demo/src/components/workspace/ConversationThread.tsx`
- `agentmesh-demo/src/components/workspace/Composer.tsx`
- `agentmesh-demo/src/components/digital-human/SkillsSection.tsx`

新增：

- `SkillPlanPreview.tsx`
- `SkillPlanProgress.tsx`
- `SkillPlanNodeCard.tsx`
- `SkillSynthesisView.tsx`

### 17.5 配置、文档和生成文件

- `.env.example`
- `README.md`
- `docs/adr/0004-skill-matrix-plan-execution.md`
- `agentmesh-demo/src/api/generated/schema.ts`
- `scripts/agent_sdk_smoke.py`

---

## 十八、复用现有能力

- `SkillCatalogService.list_for_agent()` 和 `list_enabled()`；
- `SkillDefinition.content_hash` 和 version；
- SQLite `records_fts`、`VectorIndex` 和 embedding 状态；
- `AgentMeshToolFactory.build()`；
- `AgentMeshMCPFactory.build()`；
- `AgentRuntimeService._build_agent()`、`_run_streamed()`、`_run_config()`；
- `AgentMeshSession`；
- Agent Run 幂等和 SSE 重连；
- 现有 Tool Approval CAS；
- `Artifact`、`Source`、`AgentRunEvent`、`ChatWorkflowTrace`；
- Trace Processor；
- TanStack Query 和 Workspace 事件流。

Skill Candidate 搜索必须与用户 Memory RAG 分离，Skill Profile 不进入用户知识检索结果。

---

## 十九、开发里程碑和 Todo List

### Milestone 1：Skill 画像和语义推荐

**预计：4-5 个工程日**

交付：可以根据自然语言和项目上下文推荐首批 10 个 Skill，但不改变执行逻辑。

- [ ] 新增生命周期、能力类型、输入输出和副作用枚举；
- [ ] 新增 `SkillCapabilityProfile`；
- [ ] 为 10 个 Wiki Skill 编写 `agents/agentmesh.yaml`；
- [ ] 为 11 个 Legacy 能力建立平台画像；
- [ ] 加入画像版本与 Skill hash 一致性检查；
- [ ] 持久化 Skill Profile；
- [ ] 建立 Skill Profile FTS/Vector 索引；
- [ ] 实现 readiness、binding、权限和副作用前置过滤；
- [ ] 实现 Top-12 召回和分数解释；
- [ ] 新增 `/api/skills/recommendations`；
- [ ] 扩展 Skill Catalog 安全字段；
- [ ] 建立 40 条设计请求评测集；
- [ ] 达到 Top-3 Recall 90% 门禁；
- [ ] 在 Skill Center 展示只读上下文推荐。

### Milestone 2：结构化计划预览和有限调整

**预计：5-7 个工程日**

交付：多 Skill 请求可以生成并持久化计划，用户可以查看和有限调整，但 Preview 模式暂不执行 DAG。

- [ ] 新增 Intent、Plan、Node、Result、Synthesis 模型；
- [ ] 新增 Plan/Node 状态；
- [ ] 新增三张 SQLite 表和索引；
- [ ] 实现 Plan Version CAS；
- [ ] 实现 Intent Agent；
- [ ] 实现 Planner Agent；
- [ ] 实现结构化输出；
- [ ] 实现一次校验修复；
- [ ] 实现 DAG 校验；
- [ ] 扩展 Agent Run 创建请求；
- [ ] 实现 Plan GET/PATCH/Approve/Reject；
- [ ] 实现有限调整；
- [ ] 新增 `AGENTMESH_SKILL_ORCHESTRATION=off|preview|execute`；
- [ ] 默认设置为 `off`；
- [ ] 从后端 Health/Bootstrap 暴露实际模式；
- [ ] 实现 `SkillPlanPreview`；
- [ ] 实现 Skill Center 到 Workspace 的显式启动；
- [ ] 验证多 Skill 在确认前不加载指令和 Tool。

### Milestone 3：只读/草稿 DAG 执行和综合总结

**预计：8-10 个工程日**

交付：经过确认的只读/草稿计划可以执行，并输出一份带来源的综合结果。

- [ ] 从 `AgentRuntimeService` 抽取可复用节点执行方法；
- [ ] 实现原子节点抢占；
- [ ] 实现拓扑调度；
- [ ] 实现最多 3 节点并行；
- [ ] 实现父 Run 共享 Tool Call 和时间预算；
- [ ] 节点不写共享 Session；
- [ ] 节点启动前重新校验权限和 Skill 版本；
- [ ] 实现 `SkillNodeResult`；
- [ ] 实现 Artifact 和 Source 归一化；
- [ ] 实现节点 Usage；
- [ ] 实现必需/可选节点失败传播；
- [ ] 实现读/草稿节点一次临时错误重试；
- [ ] 实现 Synthesis Agent；
- [ ] 实现 Claim/Source 校验；
- [ ] 实现确定性 Partial Fallback；
- [ ] 最终只投影一条 Assistant Message；
- [ ] 扩展 SSE 事件；
- [ ] 实现 `SkillPlanProgress`；
- [ ] 实现 `SkillPlanNodeCard`；
- [ ] 实现 `SkillSynthesisView`；
- [ ] 验证并行、部分失败、必需失败、取消和重连。

### Milestone 4：审批、恢复和写边界

**预计：5-7 个工程日**

交付：计划可以安全包含本地写入和外部写入依赖。

- [ ] 持久化 Scheduler 暂停状态；
- [ ] 将审批绑定到 Plan、Node、Skill hash 和 Grant 快照；
- [ ] 保持 Plan Approval 与 Tool Approval 完全分离；
- [ ] 禁止自动重试写操作；
- [ ] 防止并发审批重复执行；
- [ ] 审批恢复时重新校验 Skill 和 Tool；
- [ ] 扩展 Cancel；
- [ ] 实现 `/retry` 新 Run；
- [ ] 禁止自动恢复中断写操作；
- [ ] 补充 Retention；
- [ ] 增加 Plan 篡改测试；
- [ ] 增加过期版本测试；
- [ ] 增加 Skill Disable/Tool Revoke 测试；
- [ ] 增加跨用户/跨项目测试；
- [ ] 增加 Prompt Injection 和重复审批测试。

### Milestone 5：Runtime v2 E2E、指标和灰度

**预计：4-6 个工程日**

交付：确定性的浏览器级证据和可回滚的设计团队灰度。

- [ ] 为 E2E 增加确定性 Planner/Model Seam；
- [ ] 覆盖单 Skill；
- [ ] 覆盖计划预览；
- [ ] 覆盖有限调整；
- [ ] 覆盖确认和审批；
- [ ] 覆盖并行进度；
- [ ] 覆盖 Partial；
- [ ] 覆盖取消；
- [ ] 覆盖 SSE 重连；
- [ ] 覆盖刷新恢复；
- [ ] 扩展真实模型 Smoke；
- [ ] 增加召回、计划接受率和修改率指标；
- [ ] 增加节点成功率、重试、耗时和审批延迟指标；
- [ ] 增加 Token、Cost、p95 和来源覆盖率指标；
- [ ] 增加 Profile/Index/Planner Health；
- [ ] 先以 `preview` 模式灰度；
- [ ] 通过验收后进入 `execute` 模式；
- [ ] 编写 ADR 0004。

### 总周期

- 1 名后端工程师 + 1 名前端协作：约 5-7 周；
- 单工程师串行：约 7-9 周；
- 后续扩展到全部 78 个 Wiki Skill：额外 2-4 周。

---

## 二十、测试与验收

### 20.1 必须执行的自动化命令

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
npm --prefix agentmesh-demo test -- --run
npm --prefix agentmesh-demo run api:types
npm --prefix agentmesh-demo run build
npm --prefix agentmesh-demo run test:e2e
.venv/bin/python scripts/skill_catalog_report.py
```

Milestone 3-5 还必须使用所有已配置 JoyBuilder 模型运行：

```bash
.venv/bin/python scripts/agent_sdk_smoke.py
```

验证：

- 结构化 Intent；
- 结构化 Plan；
- 结构化 Node Result；
- 结构化 Synthesis；
- 并行节点；
- Streaming；
- Usage；
- Cancellation；
- 真实 Provider Provenance。

### 20.2 自动化门禁

- 当前 617 个后端测试不能回退；
- 当前 66 个前端测试不能回退；
- 当前 46 个 Playwright 测试不能回退；
- 召回 Top-3 Recall ≥ 90%；
- 不可用和未授权 Skill 召回率 = 0；
- 多 Skill 计划确认率 = 100%；
- 规划 Schema 或确定性降级成功率 = 100%；
- DAG 环、超限、未知输入和未授权节点通过率 = 0；
- 重复创建、审批、重连和节点抢占最多执行一次；
- 每个综合 Claim 都有合法 Node Result；
- 每个 Source 都存在且对用户可见；
- 计划和事件中不存在敏感数据；
- Candidate Retrieval p95 < 300 ms；
- Plan Preview p95 < 15 秒；
- 3 节点只读流程 p95 < 120 秒；
- 父 Run 始终受 300 秒上限约束。

### 20.3 人工验收场景

1. 明确单 Skill 请求直接执行；
2. 自然语言生成 3 节点计划，包含 2 个并行证据节点；
3. 用户删除可选 Skill 并调整合法顺序；
4. 用户尝试删除必需节点或添加非候选 Skill，服务端拒绝；
5. 外部写入逐调用审批，拒绝和批准都只恢复一次；
6. 可选节点失败后输出带限制的 Partial；
7. 必需节点失败后跳过下游；
8. 浏览器断开和刷新后不重复执行；
9. 并行执行中取消，不再启动新节点；
10. Skill 被停用或 Tool Grant 被撤销后节点不启动；
11. Wiki 语料不可用时排除依赖 Skill；
12. Provider 不可用时不使用 Mock 冒充真实结果。

---

## 二十一、灰度与回滚

只增加一个配置：

```text
AGENTMESH_SKILL_ORCHESTRATION=off|preview|execute
```

默认：

```text
off
```

### off

保持当前 Legacy 和单 Skill Runtime v2 行为。

### preview

- 支持推荐和计划预览；
- 多 Skill 不执行；
- 用户可以选择一个候选走现有单 Skill 路径。

### execute

允许确认后的 DAG 执行。

前端从后端 Health/Bootstrap 读取模式，不增加新的 Vite Flag。

回滚：

```text
AGENTMESH_SKILL_ORCHESTRATION=off
```

回滚不删除：

- Plan；
- Node Result；
- Artifact；
- Event；
- Audit。

任何已经等待审批的外部写操作都不能因为回滚而自动执行。

---

## 二十二、依赖与故障处理

复用：

- `openai-agents==0.21.1`；
- Pydantic；
- SQLite；
- 现有 FTS/Vector；
- 当前 JoyBuilder 模型；
- 当前 Tool/MCP/Approval/Session/Trace 基础设施。

不新增 Runtime 依赖。

依赖条件：

- Wiki Skill 需要 `AGENTMESH_WIKI_ROOT`；
- Embedding 可选；
- Embedding 不可用时必须 FTS 降级；
- Provider 不可用时可以返回候选，但不能伪造 Plan 或执行结果。

10 倍负载时，首先达到瓶颈的是 SQLite 写串行和单进程任务所有权。首期通过以下限制保护：

- 进程最多 4 个活跃计划；
- 单计划最多 3 个并行节点；
- 单计划最多 6 个领域 Skill；
- 整轮最多 24 次 Tool Call。

水平扩容不属于首期。

---

## 二十三、关键风险与应对

### 画像质量不足

应对：

- 只做 10 个 Skill；
- 使用正反例；
- 建立 40 条评测集；
- 召回门禁不过时不进入 Execute。

### 延迟和成本增加

应对：

- 单 Skill 直接执行；
- 候选 12；
- 节点 6；
- 并行 3；
- 深度 4；
- 共享 Tool 和时间预算；
- 记录节点 Usage。

### Planner 不稳定

应对：

- 严格 Schema；
- 确定性校验；
- 只修复一次；
- 单 Skill 或明确失败降级。

### 节点间不可信组合

应对：

- Planner 不读取完整 Skill 指令；
- 节点只读取批准输入；
- 上游结果必须先标准化；
- Synthesis 只读取标准化结果和 Source。

### 审批语义混淆

应对：

- Plan Approval 和 Tool Approval 使用不同状态和 API；
- Plan Approval 永远不授予 Tool；
- 外部写入继续按 call-ID 审批。

### 并行 Session 污染

应对：

- 并行节点不写共享 SDK Session；
- 父级线程只投影请求和最终结果。

---

## 二十四、拒绝的方案

不采用以下方案：

```text
把全部 Skill 暴露成工具，让一个通用 Agent 在单次 SDK Run 中自由选择、串联和并行。
```

原因：

- 候选选择不可解释；
- 无法保证多 Skill 执行前确认；
- 多节点共享 Session 容易污染；
- 难以实现节点级重试、取消和来源；
- Tool Approval 与 Skill 计划混在一起；
- 从 10 个扩到 78 个时上下文和工具列表失控。

---

## 二十五、最终完成定义

当以下条件全部满足时，本功能完成：

1. 设计师可以用自然语言描述目标；
2. 系统只从 10 个已就绪领域 Skill 中召回候选；
3. 11 个 Legacy 能力只作为底层依赖；
4. 多 Skill 计划必须确认；
5. 用户可以有限增删和调整顺序；
6. DAG 能受控串行和并行执行；
7. Tool 写入仍逐调用审批；
8. 最终结果保留 Skill、Node、Source 和 Artifact 血缘；
9. Partial 和失败不会伪装成完整成功；
10. 完整自动化和人工门禁通过；
11. `off` 可以无数据损失地恢复当前行为。

---

## 二十六、关键前提

本方案依赖一个关键前提：首批 10 个 Wiki Skill 可以通过稳定的输入、输出、阶段和正反例画像，覆盖足够多的设计工作流，并达到 40 条评测集的 Top-3 Recall 90% 门禁。

如果该前提不成立：

- 停留在 `off` 或 `preview`；
- 优化画像和首批 Skill 范围；
- 不通过扩大到 78 个 Skill 来掩盖召回问题；
- 不启用 DAG Execute。
