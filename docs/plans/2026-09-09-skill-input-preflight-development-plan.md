# Skill Input Preflight 开发方案

- 日期：2026-09-09
- 状态：方向已确认，待实现
- 基线：`d4c2f945eaff1b79ea57e289857be15a46608883`
- 适用项目：AgentMesh
- 首期范围：Standard v1 的显式 `$skill` 与自动 Skill DAG
- 核心目标：在任何 Skill 节点执行前，稳定识别、收集、校验并冻结用户必须提供的文字、数据文件和参考材料

## 0. 决策摘要

AgentMesh 新增 **Skill Input Preflight**：先确定可执行 Skill/Plan，再依据服务端可信的用户输入契约检查当前请求和材料；必需输入缺失时，Run 进入持久化的 `waiting_input`，前端展示结构化问询与上传表单。只有全部必需输入校验通过并冻结到当前 Run 后，才允许进入 Plan Approval 或 Skill 节点执行。

首个可交付版本默认采用以下最小方案：

1. 只覆盖 Standard v1，不改变 DeepSearch 的 Requirement 澄清与 Evidence 边界。
2. 支持文本、Markdown/TXT 和 CSV 的执行前收集。
3. 文件作为私有、Run-scoped Input Artifact 保存，不自动导入长期 Memory，也不复用当前“上传文档到资料库”的语义。
4. 自动 Plan 与显式单 Skill 都经过同一个服务端 Preflight 校验边界。
5. `input_kinds` 继续只用于检索和路由；新增必填的 `user_input_mode`，并以 `user_input_schema_ref` 作为 Preflight Skill 的唯一用户输入契约。
6. 图片和 URL 纳入目标模型，但分别在视觉适配器与安全 URL Snapshot Adapter 就绪后启用；前端不得提前宣称可用。
7. “下一步建议”的可执行续跑属于后续能力，不混入本次 Preflight；没有可执行目标与输入契约的建议继续按信息性文本展示。
8. Preflight 只是输入完整性门禁，不新增人工审核角色或第三套 Approval；能与现有 Plan Approval 合并确认时只让用户确认一次。

## 1. 问题与触发案例

当前 Workspace 中，一个已完成的 Skill Run 可以在结果末尾输出 `next_actions`。用户随后输入“我是否可以直接给你相关数据，你可以继续进行分析”时，系统会创建一个新的自动编排 Run，而不是进入上一 Skill 的材料收集阶段。

已确认的当前行为：

- 上一 Run 已经是终态，`next_actions` 只是 `list[str]`。
- 新消息没有上一 Run、Plan、节点或目标 Skill 的输入绑定身份。
- 自动编排只收到当前消息和截断后的线程摘要，不能把结果末尾的建议当成可靠控制面。
- 请求如果不能匹配 Ready、Selectable、Executable 的 Skill，会以 `PlannerUnavailable` 失败，并且按现有策略不降级成无工具普通回答。
- Standard Run 活跃期间 Composer 被锁定，没有通用的用户材料补充入口。

这不是单一提示词问题，而是缺少以下产品与运行时合同：

```text
Skill 用户输入契约
  + 执行前缺口检查
  + 持久化等待状态
  + Run-scoped 材料上传
  + 输入版本与绑定
  + 提交后恢复执行
```

## 2. 当前实现基线

### 2.1 已有能力

- `TaskRoutingResult.input_check` 已包含：
  - `available_inputs`
  - `missing_required_inputs`
  - `missing_optional_inputs`
  - `input_decision`
- Capability Profile 已包含 `input_kinds`、`input_schema_ref` 和 Tool/Resource 要求。
- DeepSearch 已有版本化 Requirement、最多三轮澄清和 `waiting_clarification`。
- 文档上传支持 `.txt`、`.md`、`.markdown`、`.pdf`、`.docx`、`.pptx`、`.png`、`.jpg/.jpeg`、`.webp`、`.tif/.tiff`。
- 文档上传会解析并导入个人/项目资料检索空间。
- Agent Run、Plan、节点、Tool 审批和 SSE 恢复已有持久化状态基础。

### 2.2 已知缺口

- Standard Skill 没有 `waiting_input` 状态或输入提交 API。
- `AgentRunCreateRequest` 只有文本 `content`，没有附件或 Document 引用。
- `SkillPlanPreview` 不展示或收集 `missing_required_inputs`。
- `input_kinds` 不表达 required/optional、输入控件、文件格式、数量、大小或表格列约束。
- Profile 没有显式区分 prompt-only 与需要 Preflight 的 Skill。
- 当前 `input_schema_ref` 描述的是 Skill 执行输入结构，不等于用户可填写的 Intake Schema，不能直接当作前端表单合同。
- Intent Analyzer 虽然接受 `attachment_types` 参数，但当前编排调用没有传入附件信息。
- `.csv` / `text/csv` 没有解析器。
- 现有通用文档上传对图片只做 Tesseract OCR；Skill Input Preflight 不复用该路径，当前尚未建立把原图提交给多模态 LLM 的 Run 输入链路。
- URL 只会作为普通文本进入请求；没有安全抓取、快照、版本或 Run 绑定。
- 当前“上传文档”属于知识导入，会自动产生 Memory chunks，不适合作为默认的临时 Skill 输入。
- Standard 节点指令倾向于对非敏感缺失信息采用假设并继续产出，不能承担必需材料门禁。

## 3. 目标

### 3.1 产品目标

用户在发起 Skill 后、任何 Skill 节点执行前，可以稳定看到：

- 当前即将执行的 Skill 或 Plan；
- 已从原始请求中识别出的输入；
- 尚缺的必需输入；
- 可选输入及跳过后果；
- 每个输入支持的文字、文件或 URL 格式；
- 输入校验结果；
- “资料齐全，继续”与“取消任务”操作。

刷新页面或服务进程重启后，同一 Run 必须恢复到相同问询状态。

### 3.2 工程目标

1. 缺少必需输入时不得执行 Skill 节点、Tool 或输出合成。
2. 输入契约、缺口判断、文件解析和最终绑定由服务端负责，前端不复制规则。
3. 用户材料与 Run、Plan、节点、字段、版本和内容 hash 建立可审计绑定。
4. 只有当前用户、Workspace、Project 和 Run 可访问对应输入材料。
5. 输入材料默认不进入 Personal/Project/Team Memory。
6. unsupported、解析失败、越权、版本冲突和安全隔离都有稳定错误码。
7. 没有 Ready/Authorized Skill 时先返回能力缺口，不向用户索取系统无法消费的材料。
8. 页面只能为后端已确认可用的格式展示上传入口。
9. Preflight 不新增独立人工审核流程；合同走普通代码评审，运行时只保留现有 Plan Approval 和 Tool Approval。

### 3.3 避免过度问询与审核

- 原始请求已明确满足的字段直接标记为 satisfied，不要求用户重复确认。
- 可选字段默认折叠，缺失时不阻塞；只有展开后才展示详细输入控件。
- 用户提交必需材料的动作就是输入确认，不再创建 Input Review。
- 单 Skill 且无既有 Plan Approval 条件时，材料完整后直接执行。
- 原本需要 Plan Approval 的多 Skill 或高风险计划，将材料确认与 Plan 确认合并为一个最终按钮。
- Tool Approval 只在现有策略要求时出现，不能因为文件上传再次触发同类审批。
- Skill 合同随代码走现有 PR/CI，不新增合同审批角色、审批队列或每次运行的人工复核。

## 4. 明确不建设

首期不包含：

- 不实现已完成 Run 的通用 continuation、branch 或“按下一步建议续跑”。
- 不把 `retry_of_run_id` 改造成 continuation；Retry 继续表示按原始输入重试。
- 不把用户上传材料自动沉淀为 Memory 或组织知识。
- 不让模型自行定义任意表单字段、文件类型、权限或大小限制。
- 不允许客户端声明某输入已经满足；客户端只能提交值或 Artifact 引用。
- 不允许未批准、未可信或不可执行的 Skill 因声明了输入契约而进入 Planner。
- 不修改 ADR 0009 的 Ready → Selectable → Executable 边界。
- 不向 DeepSearch v1 注入用户上传 Evidence。其首版生产 Evidence 仍只允许真实 `web_research`；扩展需单独方案。
- 不建设或复用 OCR 作为 Skill 图片输入能力；截图中的文字和视觉结构统一由受支持的多模态 LLM 处理。
- 不建设通用网盘、素材库、版本管理平台或外部对象存储。
- 首期不支持在 Skill/Plan 尚未确定前预上传并暂存附件；用户先提交目标，再在 Preflight Panel 中提供材料。
- 不新增 Input Review、Artifact Review 或 Skill Input 审核人角色；格式与完整性由服务端自动校验。

## 5. 领域术语

### 5.1 Skill Input Preflight

在 Skill 已确定、节点尚未执行期间，由服务端依据冻结的用户输入契约检查材料完整性和可消费性。

### 5.2 User Input Contract

由受信任 Skill 包提供的版本化声明，描述用户必须或可以提供的字段、输入形态和验证规则。它不同于：

- `input_kinds`：检索与路由语义标签；
- `input_schema_ref`：Skill 内部执行输入结构；
- Tool input schema：一次 Tool 调用参数；
- DeepSearch Requirement：研究目标与歧义澄清。

### 5.3 Run Input Artifact

用户为一个 Run 提供的私有输入材料及其规范化结果。它是非可信输入，不是执行产物、Verified Artifact、Memory 或 Evidence。

### 5.4 Input Binding

将一个经校验的文本值或 Run Input Artifact 精确绑定到 `run_id + plan_id + node_id + field_id` 的不可变事实。

## 6. 用户流程

### 6.1 自动 Skill DAG

```text
用户提交任务
  -> Intent / Task / Scenario 路由
  -> Ready Skill 检索
  -> 生成并校验 Plan
  -> 编译 User Input Contract
  -> 检查原始消息与现有显式材料
     -> 输入完整：进入 Plan Approval 或执行
     -> 输入缺失：Run = waiting_input
        -> 前端展示“执行前需要补充”
        -> 用户输入文字、上传文件或提交 URL
        -> 服务端解析、校验、冻结和绑定
        -> 仍缺输入：返回更新后的同一 Input Request
        -> 输入完整：进入 Plan Approval 或执行
```

### 6.2 显式 `$skill`

```text
用户选择明确 Skill
  -> 先检查 Skill Ready / Authorized
  -> 加载并冻结 User Input Contract
  -> 检查 `$skill` 后的文字和已提交材料
  -> 缺输入时进入 waiting_input
  -> 完整后才创建执行上下文并调用模型/Tool
```

### 6.3 没有结构化输入要求的 Skill

Profile 必须显式声明 `user_input_mode: prompt_only`。其原始消息直接作为 `user.request`，不显示空 Preflight 页面。

声明 `user_input_mode: preflight` 时必须同时提供有效 `user_input_schema_ref`；缺失或无效时 Skill 为 non-ready，并返回安全诊断 `user_input_contract_missing` 或 `user_input_contract_invalid`。所有生产 Planner-eligible Profile 必须显式选择一种模式，不能依赖字段缺失推断行为。

### 6.4 前台问询形态

问询卡片固定包含：

- 标题：`执行前需要补充资料`；
- Skill/节点名称与用途；
- 必填字段；
- 可选字段及跳过影响；可选字段默认折叠，不阻塞执行；
- 每个字段的格式、大小和示例；
- 已上传材料的文件名、解析状态和错误；
- `保存草稿`、`资料齐全，继续`、`取消任务`；
- 服务端返回的版本冲突、格式错误和权限错误。

Composer 在 `waiting_input` 期间仍不发送普通新 Run；用户通过该问询卡提交当前 Run 的材料。这样保持“一线程一个活动 Run”的现有约束。

### 6.5 Skill 尚未确定时

Preflight 只在服务端已经确定至少一个 Ready/Authorized Skill 或合法 Plan 后创建。若候选本身不存在，直接返回 Capability Gap，不向用户索取系统无法消费的材料。Skill 选择本身存在实质歧义时属于 Routing Clarification；它应保持一次简短问题并与 Skill 输入表单分离，但其持久化完善不属于本计划首期。首期无法稳定澄清路由时返回明确缺口，不能提前索取某个 Skill 专属文件。

## 7. 状态机

新增顶层状态：

```python
AgentRunStatus.WAITING_INPUT = "waiting_input"
```

Standard 流程：

```text
created
  -> planning
     -> waiting_input
        -> waiting_input                 分批补充或修正材料
        -> waiting_plan_approval         仍需确认 Plan
        -> running                       无需 Plan Approval
     -> waiting_plan_approval            输入已完整
        -> running
           -> waiting_approval           Tool 审批
              -> running
           -> completed | partial | failed
        -> rejected

任意活动态 -> cancelled
waiting_input --到期--> cancelled
```

状态约束：

1. `waiting_input` 时 Plan 已确定，但任何 Skill 节点和 Tool 都尚未执行。
2. 一个 Run 同时只能有一个 active Input Request。
3. 等待用户输入不消耗 Skill 执行 deadline；使用现有 `interaction_expires_at` 语义，首期固定 24 小时。
4. 提交材料采用 `expected_version + client_turn_id`，完全相同的重放返回原结果，不同 payload 返回 409。
5. Input Request 完整后一次性冻结；进入 `running` 后不能替换输入。
6. 输入完整后是否进入 Plan Approval，由原 Plan 的节点数、Human Confirmation 和 side-effect 规则决定，Preflight 不改变审批政策。单节点只读/草稿任务在用户提交完整输入后直接执行；原本需要 Plan Approval 的任务把“输入确认”和“计划确认”合并为一个最终操作，不能连续要求用户确认两次。
7. `waiting_input` 加入线程 active Run 冲突、取消、恢复、SSE 和前端 active 状态集合。
8. Recovery 只恢复持久化状态；GET、SSE、页面刷新不得触发解析或执行。

SkillPlan 保持现有非执行状态：初始 Preflight 可保持 `planning`，已经形成并等待确认的 Plan 保持 `waiting_approval`。是否正在等待材料只由顶层 Run 的 `waiting_input` 和 `SkillInputRequestV1.status` 表达，首期不再给 SkillPlan 增加重复状态。Plan 为 `waiting_approval` 但 Run 为 `waiting_input` 时，前端先完成材料收集，再提供一次合并后的最终确认。

## 8. User Input Contract

### 8.1 Profile 声明

Capability Profile 新增：

```yaml
user_input_mode: preflight       # prompt_only | preflight
user_input_schema_ref: user-input.schema.json
```

`user_input_mode` 对生产 Planner-eligible Profile 为必填。`prompt_only` 禁止同时声明 `user_input_schema_ref`；`preflight` 必须声明该引用。

不复用现有 `input_schema_ref`，因为后者描述内部执行输入和 Evidence 引用结构，不是用户表单协议。

Skill 包加载时一次性验证：

- 引用必须位于当前 Skill 根目录；
- 文件大小和 JSON 深度受限；
- `$id`、`schema_version`、Skill 名称和版本一致；
- 字段 ID 唯一且符合稳定标识符格式；
- 必填字段必须存在；
- 声明的媒体类型必须有已注册且健康的 Input Adapter；
- 不能通过 Schema 声明 Tool、权限、外部写入或 Memory 写入。

Loader 对规范化合同计算 `user_input_contract_hash`。该 hash 与安全合同正文冻结在 `SkillInputRequestV1.contract_snapshots`，公开 Profile 不返回 Schema 正文。首期不修改既有 Candidate Snapshot v1；若未来要求把合同身份纳入 Candidate Snapshot，必须发布新版本而不能改写 v1。合同变更必须伴随 Skill/Profile 版本更新；既有 Run 始终按冻结合同校验，新 Run 才读取新合同。节点启动前只重新校验 Skill 身份、授权、Adapter readiness 和冻结 Binding，不用当前文件重解释旧 Run。

### 8.2 最小契约

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "agentmesh://skills/build-experience-metrics/user-input-v1",
  "schema_version": "skill-user-input-v1",
  "type": "object",
  "required": ["product_goal"],
  "properties": {
    "product_goal": {
      "type": "string",
      "title": "产品与业务目标",
      "description": "说明产品形态、核心目标和不可恶化的护栏",
      "maxLength": 4000
    },
    "baseline_metrics": {
      "type": "array",
      "title": "历史指标数据",
      "items": {
        "type": "string",
        "format": "agentmesh-input-artifact",
        "contentMediaType": "text/csv"
      },
      "maxItems": 3
    },
    "event_definition": {
      "type": "string",
      "title": "埋点口径说明",
      "format": "agentmesh-input-artifact",
      "contentMediaType": "text/markdown"
    }
  },
  "additionalProperties": false
}
```

首期只支持 JSON Schema 中明确批准的子集：

- object / string / array；
- `required`；
- `title` / `description`；
- `minLength` / `maxLength`；
- `minItems` / `maxItems`；
- `enum`；
- `format=uri`；
- `format=agentmesh-input-artifact`；
- `contentMediaType`；
- `additionalProperties=false`。

不实现任意条件表达式、远程 `$ref`、脚本校验器或客户端自定义组件。

### 8.3 路由与 Preflight 的职责

- `input_kinds`：回答“这个 Skill 能消费哪类业务输入”。
- `TaskRoutingResult.input_check`：提供 Scenario 层已有/缺失输入诊断。
- User Input Contract：回答“用户现在必须提交哪些具体值或材料”。
- Preflight Service：唯一负责合并 Plan 用户绑定、Input Contract 与已提交材料，并给出 complete/missing/invalid。

前端不得自行把 `input_kinds` 转换成必填字段。

### 8.4 不同 Skill 的问询如何生成

不同 Skill 的问题不写死在 Workspace，也不在运行时从自然语言 `SKILL.md` 中猜测。每个 Skill 在包内维护自己的 User Input Contract，Preflight Service 将它编译成统一的安全表单投影。

```text
Skill A 的 user-input.schema.json ─┐
Skill B 的 user-input.schema.json ─┼─> Preflight Service ─> SkillInputRequestV1 ─> 通用前端表单
Skill C 的 user-input.schema.json ─┘
```

编译过程：

1. Plan 确定节点与 Skill 身份。
2. 服务端按节点读取并校验对应的 User Input Contract。
3. 只处理节点中直接来自用户的输入；由上游节点产生的输入不向用户重复索取。
4. 用原始请求、已确认的结构化字段和已上传材料匹配合同字段。
5. 生成 `satisfied | missing | invalid | processing` 字段状态。
6. 任一 required 字段不是 `satisfied` 时，持久化同一个 `SkillInputRequestV1` 并进入 `waiting_input`。
7. 前端根据安全投影选择 textarea、单选、多选、文件、URL 等通用控件。
8. 每次提交后由服务端重新校验；仍缺字段时继续停留在同一问询阶段，完整后才推进 Run。

模型可以协助把原始请求映射到合同字段，但不能决定字段、required、媒体类型或校验规则。只有返回可在原始请求中逐字定位的 source span，且服务端验证匹配时，才可直接标记为 satisfied，避免重复询问用户已经明确提供的内容；需要推断、改写或低置信度的值仍按 missing 处理并由用户填写。模型不可新增合同外问题。

多 Skill Plan 的字段按 `node_id + field_id` 命名空间保存。只有 Contract hash 与字段 ID、类型完全一致时，服务端才允许一个用户输入复用于多个节点；否则分别询问，避免把语义相似但实际不同的材料错误合并。用户在 Plan Approval 阶段新增或替换节点后，服务端重新运行 Preflight；新节点引入必需输入时，Run 返回 `waiting_input`。

示例：

| Skill | 合同声明 | 前台实际问询 |
| --- | --- | --- |
| `build-experience-metrics` | 产品与业务目标 required；历史基线 CSV、埋点 Markdown optional | 原请求已包含目标时不重复询问；可选展示“补充历史数据可提高可落地性” |
| `conversion-funnel-analysis` | 漏斗数据 CSV required；事件口径 Markdown/text required；分群数据 optional | 缺 CSV 时不得执行，展示文件上传和必需列表头 |
| `prd-feasibility` | PRD 内容 required，可由文本或受支持文档满足；目标平台 optional | 原消息没有 PRD 正文或文件时展示 PRD 上传/粘贴入口 |
| `research-screenshot-analyzer` | 研究主题 required；截图集合 required；竞品名称 optional | 只有 `image_vision` Adapter Ready 时显示截图上传，否则 Skill 在候选阶段即 non-ready |
| `competitive-analysis` | 研究目标 required；竞品范围 required；可信 Evidence 由既有执行契约处理 | User Input Contract 只问用户范围，不把内部 Evidence Artifact 字段暴露给前端 |

首期不支持任意动态分支、脚本题目或模型自由追问。Skill 若确实需要“回答 A 后才决定是否问 B”，应先把 A、B 设计成一个版本化、可审查的有限合同；复杂条件问询作为后续 Schema 版本单独设计，不能在前端临时硬编码。

### 8.5 Skill 全量盘点与合同迁移

需要对已安装 Skill 做一次全量静态盘点，但不等于为每个 Skill 都编写复杂问卷。每个可调用 Skill 必须得到一个显式分类：

| 分类 | 适用情况 | 必需声明 |
| --- | --- | --- |
| `prompt_only` | 当前用户消息本身就是完整输入，不依赖额外材料 | `user_input_mode: prompt_only` |
| `preflight` | 执行前必须或可以收集结构化字段、文件或 URL | `user_input_mode: preflight` + `user_input_schema_ref` |
| `not_ready` | 所需 Adapter、权限、资源或合同尚不可用 | 保持不可选，并提供安全 reason code |

迁移分两层完成：

1. **全量 Inventory**：扫描全部已安装 Skill，输出 Skill ID/version/hash、当前 Profile 状态、`input_kinds`、现有 `input_schema_ref`、SKILL.md 中的输入描述、所需媒体类型和建议分类。该产物只用于迁移检查，不能直接获得生产权限，也不新增独立审批流程。
2. **可执行 Skill 合同化**：优先在普通代码评审中确认当前生产 Ready/Planner-eligible Skill。`prompt_only` 必须显式声明；`preflight` 必须提交合同和缺失输入测试。Draft/non-planner-eligible Skill 可以暂不完成合同，但在未来升级为 Ready 前必须通过同一自动门禁。

允许离线脚本从 Profile、Schema 和 SKILL.md 生成候选合同骨架，但禁止自动发布，原因是自然语言说明无法可靠判断 required/optional、文件格式、fallback 和数据敏感性。最终分类和合同随 Skill 代码一起评审，不设置单独的合同审核人、审批队列或运行时人工复核。

最终门禁不允许隐式默认：

- 缺少 `user_input_mode`：`user_input_contract_unclassified`；
- `prompt_only` 却声明 Schema：合同无效；
- `preflight` 缺少或无法解析 Schema：Skill non-ready；
- 合同要求当前不支持的 Adapter：Skill non-ready；
- 外部或 Learned Skill 在进入可执行目录前遵守同一合同，不获得例外。

当前基线文档记录约 84 个 built-in Skill，其中 10 个为可执行 Pilot、其余多数仍为 Draft。实现时不硬编码该数量：Inventory 每次从当前 Catalog 生成。首个发布门槛只要求所有实际可调用 Skill 完成分类；Draft Skill 不阻塞平台开发，但不能在未分类时被提升为 Ready。

## 9. 持久化模型

### 9.1 SkillInputRequestV1

```text
id
run_id
plan_id | null                  显式单 Skill 可为空
version
schema_version                  skill-input-request-v1
status                          open | complete | expired | cancelled
contract_snapshots[]
fields[]                        安全表单投影及当前草稿值/Artifact 引用
missing_required_field_ids[]
frozen_bindings[]               complete 后冻结，按节点限定可见输入
last_command_id / last_payload_hash
next_run_status                 waiting_plan_approval | running
created_at / updated_at / expires_at
```

`contract_snapshots` 冻结 Skill ID、Skill version、Skill content hash、User Input Contract hash 和节点 ID。Input Contract 后续变化不得重新解释既有 Request。

### 9.2 RunInputArtifactV1

```text
id
run_id
workspace_id / project_id / user_id
field_id
file_name
media_type
byte_size
content_hash
adapter_id / adapter_version
status                          uploaded | processing | ready | failed | quarantined
normalized_text | null
structured_payload | null
error_code | null
created_at / updated_at
```

Run Input Artifact 是私有输入，不复用 Verified Output Artifact，也不自动创建 `UserMemoryItem`。

### 9.3 提交与绑定

首期不新增独立的 Input Submission 审核聚合或人工审核记录。`SkillInputRequestV1` 通过版本 CAS 保存当前草稿值和 Artifact 引用，并用 `last_command_id + last_payload_hash` 保证最近一次提交可安全重放；进入 complete 后在同一记录中冻结 `frozen_bindings`。

每个冻结绑定至少包含：

```text
plan_id / node_id / field_id
value_kind                      text | artifact | url_snapshot
value_ref
value_version
content_hash
contract_hash
```

执行节点只能读取分配给自身的 Binding。一个 Artifact 可以经用户确认绑定到多个字段，但每条绑定独立列出。输入历史不额外复制为审核流水；已有 Run 事件只记录状态转换、ID、计数和 hash，不记录原始正文、URL、文件名或用户答案。

## 10. 输入 Adapter

### 10.1 文本

- 原始请求可预填到契约声明的主文本字段。
- 用户可以修改并确认。
- 服务端执行长度、Unicode、凭据样式和 Prompt Injection 检查。
- 文本值只进入明确绑定的节点，不作为全局控制指令。

### 10.2 Markdown / TXT

首期支持：

- `text/plain`：`.txt`
- `text/markdown`：`.md`、`.markdown`
- UTF-8 / UTF-8-SIG；其他编码返回稳定错误。
- 保留规范化文本、原始 hash 和文件名；不得自动导入 Memory。

### 10.3 CSV

首期新增专用 CSV Adapter：

- 支持 `text/csv` 与 `.csv`；
- UTF-8 / UTF-8-SIG；
- 使用 Python 标准库解析，不执行公式、宏或外部链接；
- 保留表头顺序和原始单元格文本；
- 校验重复表头、空表头、行列上限、单元格大小和契约要求列；
- 产生规范化列描述、行数和有界数据载荷；
- 错误明确区分 encoding、header、shape、size 和 schema mismatch。

表格列要求由对应 Skill 的 User Input Contract 声明，不建立全局业务列名表。

### 10.4 图片

图片输入只声明一种能力：`image_vision`。Input Adapter 负责文件安全校验、规范化和 Run 绑定，实际的文字识别、UI 布局理解、视觉层级和参考风格分析统一由具备视觉能力的多模态 LLM 完成。

规则：

- 支持 PNG、JPEG、WebP；TIFF 只有在当前多模态 Provider 明确支持时才能开放；
- 校验真实文件签名、像素上限和解压后大小；
- 清理 EXIF 等非必要元数据；
- 保留图片顺序，并允许用户填写简短用途说明；
- 执行前校验实际模型和 Provider 支持图片输入，而不只检查文本模型可用；模型注册信息新增服务端可信的 `input_modalities`，不能按模型名称猜测；
- OpenAI Agents SDK 当前支持 `list[TResponseInputItem]` 和 `input_image`，但 AgentMesh 现有调用仍只传字符串；实现时由节点输入构造器生成“文本指令 + 图片内容”的多模态列表；
- 原图以受限的多模态消息部分提交给对应节点，不先转成 OCR 文本；
- Base64/Data URL 只在最终 Provider 调用边界临时构造，不写入 ChatMessage、SDK Session、Run Event 或日志；持久化层只保存受控 Artifact 引用和 hash；
- 输入 Guardrail 只检查用户文本、图片元数据和安全扫描结果，不能把整段 Base64 当文本扫描或记录；
- 多模态能力不可用时，相关 Skill 为 non-ready，不降级到 OCR 或纯文本猜测；
- 图片适合界面结构、视觉层级、风格和参考案例分析；图片中的精确数值、完整表格或必须逐字准确的内容不得仅依赖视觉模型，Input Contract 应改为要求 CSV、Markdown 或原始文档；
- 视觉结论属于概率性模型输出，必须保留图片 Artifact 引用，并在结果中披露无法确认的小字、遮挡或低清区域。

图片能力不进入首个 text/CSV/Markdown release gate；作为独立 Slice 启用。

### 10.5 URL

URL 使用独立 Snapshot Adapter，不把普通 `web_research(query)` 当作精确 URL 读取：

- 只接受无用户名密码的公共 HTTP(S)；
- DNS 解析和每次重定向后都拒绝 loopback、link-local、private、保留地址和非 HTTP(S) scheme；
- 限制重定向次数、响应大小、超时和内容类型；
- 记录原 URL、最终 URL、抓取时间、内容 hash 和 Adapter 版本；
- HTML 提取正文，文本类型直接规范化；
- 抓取失败时保持 `waiting_input`，允许用户更换 URL 或改传文件；
- URL 正文作为不可信用户材料进入选定节点，不获得 Tool、Skill 或 Prompt 权限；
- 用户主动提交该 URL 即构成对这一个公开地址的只读抓取确认，不再增加一次 Tool Approval。

URL 能力在专用安全测试通过后单独启用。

### 10.6 其他已有文档格式

PDF、DOCX、PPTX 可以在后续复用现有解析器，但仍需走 Run-scoped 上传入口和 Input Binding；不得借用 `/api/documents/upload` 后依赖模糊检索。

### 10.7 执行上下文预算

文件上传上限不等于模型可消费上限。Preflight 必须在显示“资料就绪”前同时验证原始文件限制和规范化内容预算：

- 每个合同字段声明可接受的最大原始字节数、行数或图片数量；
- 服务端再施加单 Run 的统一硬上限；
- 首期只接受能够完整进入该节点输入预算的规范化文本或表格，不静默截断、不只取前若干行后声称已分析全量；
- 超出预算时返回 `input_content_too_large`，要求用户缩小范围或提供聚合数据；
- 大文件分块读取、分页查询或专用 `read_run_input` Tool 属于后续扩展，不能在首期文档中假装已经支持。

## 11. API 设计

### 11.1 读取问询状态

```http
GET /api/agent/runs/{run_id}/input-request
```

返回：

- Input Request 版本和状态；
- 安全字段定义；
- 已提交值的摘要；
- Artifact 解析状态；
- 缺失必填字段；
- 允许的下一操作。

### 11.2 上传 Run 输入文件

```http
POST /api/agent/runs/{run_id}/input-artifacts
Content-Type: multipart/form-data

field_id
expected_request_version
file
```

上传前校验 Run owner、状态、字段、媒体类型和大小；上传后异步或同步解析，但不推进 Run。

### 11.3 提交输入

```http
POST /api/agent/runs/{run_id}/inputs
Content-Type: application/json

{
  "client_turn_id": "...",
  "expected_request_version": 2,
  "text_values": {"product_goal": "..."},
  "artifact_ids": {"baseline_metrics": ["input_artifact_..."]},
  "url_values": {}
}
```

服务端在一个事务中：

1. 校验 idempotency 和 request version；
2. 校验所有值与 Artifact 的身份、状态、hash 和契约；
3. 更新 Input Request 的当前值和 Artifact 引用；
4. 重算缺口；
5. 若完整，冻结 Binding 并推进 Run/Plan；
6. 写最小状态事件；
7. 返回新的 Run、Plan 和 Input Request 投影。

### 11.4 删除或替换尚未冻结的材料

```http
DELETE /api/agent/runs/{run_id}/input-artifacts/{artifact_id}
```

仅在 `waiting_input` 且 Artifact 未冻结时允许。进入 Plan Approval 或 Running 后禁止删除和替换。

## 12. Runtime 集成

### 12.1 编排顺序

Standard 自动编排调整为：

```text
Intent Analyzer
  -> Candidate Retrieval
  -> Planner + deterministic validation
  -> User Input Preflight
  -> Plan Approval（如需要）
  -> Bounded DAG Executor
```

Preflight 不改变 Candidate Snapshot、Tool Grant、Resource Manifest、side-effect 和 execution-time revalidation。

### 12.2 节点输入

节点执行 prompt 新增服务端构造的 `user_inputs`：

```json
{
  "user_request": "...",
  "user_inputs": {
    "baseline_metrics": {
      "kind": "artifact",
      "artifact_id": "input_artifact_...",
      "media_type": "text/csv",
      "content_hash": "...",
      "normalized_payload": {}
    }
  }
}
```

只向节点提供其绑定字段。模型不能读取其他节点、其他 Run 或资料库中的未绑定上传内容。

### 12.3 可用性判断

Skill 的 readiness 新增安全原因：

- `user_input_contract_missing`
- `user_input_contract_invalid`
- `input_adapter_unavailable`
- `input_media_type_unsupported`

这些原因可以进入 Blocked Match，但不能泄露内部路径、Schema 正文或 Adapter 配置。

### 12.4 失败语义

- 用户尚未提交：`waiting_input`，不是 failed。
- 用户取消：`cancelled`。
- Input Request 到期：`cancelled`，原因 `input_request_expired`。
- 文件格式或内容错误：Artifact `failed`，Run 保持 `waiting_input`。
- 材料被安全隔离：Artifact `quarantined`，Run 保持 `waiting_input`。
- 输入完成后 Skill/Tool 状态变化：执行前 revalidation 失败，Run `failed` 或返回 Plan capability gap；不得换用未确认 Skill。

## 13. 前端设计

### 13.1 Workspace

新增 `SkillInputPreflightPanel`，位置与 Plan Preview 同级、Composer 上方。它只在服务端 Run 状态为 `waiting_input` 时出现。

组件职责：

- 渲染服务端字段投影；
- 文本、文件、URL 输入；
- 上传和解析进度；
- 必填/可选标签；
- 服务端校验错误；
- 提交、取消；
- 页面刷新后恢复。

组件不负责：

- 推断缺失字段；
- 决定文件是否合格；
- 修改 Skill/Plan；
- 读取或拼接文件正文；
- 判断是否可以开始执行。

### 13.2 Composer

`waiting_input` 继续属于活动 Run：

- 普通发送按钮保持禁用，避免创建第二个 Run；
- 文案显示“请先完成上方资料补充”；
- 文件按钮移入 Preflight Panel，避免误导成资料库上传；
- 非 `waiting_input` 状态下，现有上传入口明确改名为“导入资料库”，其上传结果不自动满足任何 Run 输入；
- 用户可取消当前 Run 后恢复普通对话。

### 13.3 输入控件

- 文本：textarea。
- 单文件：文件选择器和解析状态。
- 多文件：有界文件列表。
- URL：逐项 URL 输入，服务端抓取后显示快照状态。
- 图片：缩略图、用途说明和“由多模态模型分析”能力标签。
- CSV：显示文件名、行列数、识别出的表头及缺失列。

### 13.4 可访问性

- Input Panel 使用稳定 heading 和 form label。
- 状态更新使用 `aria-live=polite`；阻塞错误使用 `role=alert`。
- 上传、删除、重试、提交均支持键盘。
- 必填错误聚合到表单顶部并定位到字段。
- 不只依靠颜色区分 ready/failed/quarantined。

## 14. 安全与隐私

1. Run Input Artifact 默认 `Scope.PRIVATE`，绑定 Run owner、Workspace 和 Project。
2. 上传、读取、删除和提交均在服务端边界重新授权。
3. MIME 以服务端文件签名和 Adapter 识别为准，不信任浏览器声明。
4. 原始正文、文件名、URL 和用户回答不进入 Agent Run Event、审计摘要或日志。
5. 凭据样式内容和 Prompt Injection 进入现有安全筛查；被隔离内容不能进入模型上下文。
6. CSV 不执行公式；以 `= + - @` 开头的单元格按纯文本处理。
7. URL Adapter 必须完成 SSRF、重定向和响应大小防护。
8. 图片必须防止解压炸弹并移除不需要的元数据。
9. Input Artifact 不产生 MemoryUseReceipt，也不增加独立人工审核；冻结后的 Input Request 已足够证明本次 Run 使用了哪些输入。
10. 取消、失败和过期后的保留期限按后续数据保留决策执行；首期不得实现自动长期沉淀。

## 15. 与现有架构的关系

### 15.1 ADR 0004

保持父 AgentRun 拥有生命周期、节点不创建递归 Run、Plan/Tool 两类审批相互独立。Input Preflight 是执行前门禁，不是第三种权限审批。

### 15.2 ADR 0009

保持 Ready、Selectable、Executable 的顺序。Input Contract 可用性进入 Ready 检查；已选 Skill 在节点启动前仍需重新校验版本、hash、授权和 Adapter 状态。用户材料不能扩大候选、Tool、权限或 side-effect。

### 15.3 ADR 0013

复用“只有真正进入模型上下文才记录使用”的原则，但不复用 MemoryUseReceipt 数据模型。Run Input Binding 必须冻结实际交给节点的 Input Artifact 版本与 hash。

### 15.4 DeepSearch v1

DeepSearch 当前明确排除用户上传 Evidence。首期 Skill Input Preflight 不改变这一决策：

- DeepSearch Requirement 继续负责文本/选择型澄清；
- DeepSearch 仍不接受用户 CSV、Markdown、图片或 URL Evidence；
- 如未来扩展，必须单独定义 `deepsearch-user-evidence-v1` writer、Evidence 归属、预算、审查和报告引用规则。

### 15.5 历史数据

不回填、不重写旧 AgentRun、Plan、Document、Artifact 或 Memory。只有新创建并实际进入 Preflight 的 Run 产生新记录。

由于新增 Run/Plan 状态与私有输入事实，编码前应新增 ADR，建议编号为 `0015-skill-input-preflight.md`。

## 16. 实施切片

### Slice 0：合同与 ADR

- 新增 ADR 0015。
- 定义 User Input Contract、Input Request、Artifact 和内嵌 Binding Schema。
- 定义稳定错误码和状态转换。
- 生成全量 Skill Input Inventory，并将结果作为可评审的构建产物。
- 为 Profile Loader 增加 `user_input_mode` 和 `user_input_schema_ref` 校验。
- 添加纯合同和非法 Schema 测试。

独立价值：可以审计 Skill 是否声明了可执行前置输入，不改变运行行为。

### Slice 1：文本 Preflight

- 新增 `waiting_input`。
- 为显式 Skill 和 Standard Plan 编译文本字段缺口。
- 持久化 Input Request、Artifact 引用和冻结 Binding。
- 增加读取、提交、取消和恢复 API。
- Workspace 增加文本问询面板。
- 至少为一个现有 Ready Pilot Skill 增加真实 User Input Contract。

独立价值：核心必需信息缺失时，Skill 会在执行前稳定询问并恢复。

### Slice 2：Run-scoped Markdown/TXT 与 CSV

- 新增私有 Run Input Artifact Store。
- 新增 Markdown/TXT 和 CSV Adapter。
- 增加文件上传、解析、删除、绑定和消费回执。
- 展示 CSV 表头、行列数和契约缺口。
- 为指标、漏斗或用户材料类 Pilot Skill 增加测试合同。

独立价值：可以用真实数据文件完成执行前输入闭环，不依赖资料库模糊检索。

### Slice 3：URL Snapshot

- 新增安全 URL Adapter。
- 增加 SSRF、redirect、content-type、timeout、size 和 hash 测试。
- 前端增加 URL 状态和替换入口。

独立价值：可把指定公开参考页面作为冻结输入，而不是把 URL 当搜索关键词。

### Slice 4：图片视觉输入

- 增加图片签名、像素、EXIF、数量和模型上下文预算检查。
- 将原图作为受限多模态消息部分绑定到对应 Skill 节点。
- 只有实际模型与 Provider 均支持图片输入时才开放“截图分析”。
- 增加中文截图、纯视觉布局、多图顺序、图片损坏和多模态能力不可用测试。
- 不安装、不调用、不回退到 OCR。

独立价值：参考案例和 UI 截图能以诚实能力标签进入 Skill。

### Slice 5：Pilot Profile 收口与发布门禁

- 为全部实际可调用 Skill 补齐 `user_input_mode`；`preflight` 必须绑定合同，纯文字请求则显式声明 `prompt_only`。
- 为 Draft/non-planner-eligible Skill 增加“提升为 Ready 前必须完成输入分类”的 Catalog 门禁，不要求本阶段一次性编写其全部合同。
- D0 增加合同完整性检查。
- D1 的缺失输入案例改为真实 `waiting_input`、提交、恢复和执行。
- R2 执行真实模型的输入缺失批次前，先由维护者批准预算。
- 真实 Provider、CSV、URL 和多模态图片输入分别完成 smoke。

## 17. 预计代码落点

### 后端

- `agentmesh/models.py`：状态和公开/内部契约。
- `agentmesh/skill_runtime/profiles.py`：User Input Contract 引用及加载校验。
- `agentmesh/skill_runtime/input_preflight.py`：唯一 Preflight 编译与校验服务。
- `agentmesh/agent_runtime/service.py`：Plan 后、执行前状态转换、恢复，以及文本/图片多模态节点输入构造。
- `agentmesh/store.py`：Input Request、Artifact、内嵌 Binding 和 CAS。
- `agentmesh/routes/agent_runs.py`：Input Request 查询和提交入口。
- `agentmesh/routes/run_inputs.py`：Run-scoped 文件上传和删除。
- `agentmesh/input_adapters/`：text、markdown、csv，后续 url 和 image 安全适配。
- `agentmesh/agent_runtime/guardrails.py`：对多模态输入只检查文本、Artifact 元数据和安全结果，避免记录 Base64 图片正文。
- `agentmesh/skill_runtime/readiness.py` / `recommendation.py`：输入合同和 Adapter readiness。

### 前端

- `agentmesh-demo/src/pages/Workspace.tsx`：`waiting_input` 投影与 Composer 锁定。
- `agentmesh-demo/src/components/workspace/SkillInputPreflightPanel.tsx`：问询表单。
- `agentmesh-demo/src/features/workspace/api.ts`：读取、上传、提交、删除。
- `agentmesh-demo/src/features/workspace/queries.ts`：版本化 mutation 与失效。
- `agentmesh-demo/src/features/workspace/types.ts`：生成类型的本地收口。
- OpenAPI schema 和生成 TypeScript 类型。

### 测试

- `tests/test_skill_input_contracts.py`
- `tests/test_skill_input_preflight.py`
- `tests/test_run_input_artifacts.py`
- `tests/test_agent_runs.py` 或现有 Agent Run 路由测试
- `tests/test_documents.py` 中拆出或复用通用 Parser 测试
- `agentmesh-demo/src/components/workspace/SkillInputPreflightPanel.test.tsx`
- `agentmesh-demo/e2e/workspace-skill-input-preflight.spec.ts`

文件名为规划建议；实现时优先复用现有模块，若单独的 `run_inputs.py` 或 `input_adapters/` 不能降低职责复杂度，则保持在一个服务模块内，不为未来格式预建空抽象。

## 18. 测试矩阵

### 18.1 合同

1. 合法 text-only 合同。
2. 合法 Markdown/CSV 合同。
3. 非法远程 `$ref`。
4. 越界深度、字段数、字符串长度和文件数。
5. 不支持 media type。
6. Profile hash 或 Skill hash 漂移。
7. Planner-eligible 外部材料 Skill 缺少合同。

### 18.2 状态机

1. 输入完整：`planning -> waiting_plan_approval|running`，不出现 Preflight。
2. 输入缺失：`planning -> waiting_input`。
3. 分批提交后仍缺失：保持 `waiting_input` 且 version 增加。
4. 完整提交：原子冻结并推进。
5. 重复相同提交：幂等返回。
6. 相同 `client_turn_id` 不同 payload：409。
7. 旧 `expected_version`：409 并返回最新投影。
8. waiting 状态取消和到期。
9. 进程重启、页面刷新和 SSE 重连不触发执行。
10. 同线程第二个 Run 继续被拒绝。

### 18.3 文件

1. UTF-8 与 UTF-8-SIG Markdown/TXT。
2. CSV 表头、空值、重复列、缺列、过大、乱码和公式文本。
3. 上传 MIME 与真实文件类型不一致。
4. 解析失败后替换文件。
5. 跨用户、跨项目、跨 Run Artifact 引用。
6. Artifact 上传后未提交，不得进入节点上下文。
7. 提交后 hash 或版本变化，执行前拒绝。
8. 输入材料不得自动创建 Memory。

### 18.4 图片与 URL

1. 图片原始字节只绑定到声明 `image_vision` 的节点。
2. 多模态模型或 Provider 不支持图片输入时，视觉 Skill 不可执行。
3. 中文截图、图文混合截图和纯视觉布局由同一多模态路径处理。
4. 多图顺序、用途说明、图片损坏、错误签名、像素上限和 EXIF 清理。
5. 测试断言图片路径不会调用 Tesseract 或任何 OCR fallback。
6. URL loopback/private/link-local、DNS rebinding 和跨 scheme redirect。
7. URL 内容超限、超时、非支持类型和快照 hash。

### 18.5 前端 E2E

1. Skill 缺输入时显示稳定问询卡，不执行节点。
2. 普通 Composer 不创建第二 Run。
3. 文本提交后缺口减少。
4. CSV/Markdown 上传显示解析进度和错误。
5. 必填项完整后进入 Plan Approval 或 Running。
6. 刷新后恢复字段、Artifact 和状态。
7. 取消后 Composer 解锁。
8. Adapter 不可用时不显示虚假上传能力。

## 19. 验收标准

- 100% 的必需输入缺失案例在首个 Skill 节点或 Tool 调用前进入 `waiting_input`。
- `waiting_input` 状态下 Skill 节点执行次数和 Tool 调用次数均为 0。
- 所有输入字段来自冻结 User Input Contract，模型和客户端不能新增字段或放宽格式。
- Markdown/TXT、CSV 的成功和失败路径均有确定性测试。
- 上传材料只有在完成授权、解析、校验和 Binding 后才能进入节点上下文。
- 跨用户、跨 Workspace、跨 Project、跨 Run 输入泄露为 0。
- 用户材料自动写入 Memory 的次数为 0。
- 页面刷新、进程重启和重复提交不产生重复执行。
- 图片输入只能通过具备视觉能力的 LLM 进入对应节点；不存在 OCR 分支或 OCR fallback。
- URL 抓取通过 SSRF 与重定向安全测试后才可标记 Ready。
- 现有 Plan Approval、Tool Approval、Candidate Snapshot、Retry、取消和 Completion Check 测试保持通过。
- DeepSearch 现有文本澄清和仅真实 Web Evidence 的边界保持不变。
- 截图所示场景中，如果目标 Skill 在执行前声明历史指标为必需输入，系统必须先展示资料问询，而不是先完成报告后再让用户重新触发 Planner。

## 20. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 把所有缺失信息都变成人工阻塞 | 只有 Contract `required` 字段阻塞；可选字段允许跳过 |
| Planner 选择了实际不可消费材料的 Skill | Adapter readiness 进入 Skill Ready 检查，执行前再次校验 |
| 上传即长期记忆导致数据扩散 | Run Input Artifact 与 Document/Memory 分离，默认 private、run-scoped |
| 文件解析成功但节点未获得输入 | 节点 prompt 只从冻结 Binding 构造，并在测试中断言 Artifact ID/hash |
| 多模态模型不支持图片 | 图片 Skill 在 Ready 阶段失败并显示明确原因，不回退到 OCR 或文本猜测 |
| URL 引入 SSRF 或内容漂移 | 服务端安全抓取并冻结快照/hash，拒绝私网与危险重定向 |
| 多节点出现重复问项 | 只合并完全相同 Contract hash + field ID；其他字段保持节点命名空间 |
| 等待用户导致执行超时 | 暂停 execution deadline，使用独立 interaction expiry |
| Input Contract 修改重解释旧 Run | 冻结 Contract hash，不回填旧 Run |
| 继续显示无法执行的下一步 | 只有后端确认 Ready 且拥有输入契约的后续动作才能在未来标为可执行 |

## 21. 回滚

- 停止创建新的 Preflight-enabled Run。
- 已处于 `waiting_input` 的 Run 只能取消或由同版本代码继续，不能由旧逻辑跳过输入直接执行。
- 已冻结 Input Binding 的 Run 继续按原 Contract hash 执行。
- 回滚不删除 Input Request、Artifact 或冻结 Binding；它们保留为 Run 输入事实。
- 不回写或降级到 `/api/documents/upload`，不把 Run 输入转成 Memory。
- 由于状态和持久化契约是新增语义，发布采用 stop-and-roll-forward，不部署无法识别 `waiting_input` 的旧二进制处理这些 Run。

## 22. 未决决策与默认建议

以下细节不阻塞开发文档，进入 Slice 0 时确认：

1. **Input Artifact 保留期**：建议首期 Run 终态后保留 30 天，手动删除优先；正式策略需单独确认。
2. **单文件和单 Run 上限**：默认沿用现有单文件 20 MiB 上限，并增加 Contract 级更小限制；需基准测试后确认总量。
3. **首批 Pilot Skills**：建议选择 `build-experience-metrics`、`prd-feasibility` 和一个用户材料分析 Skill，覆盖文本、CSV/Markdown 和参考材料三类输入；不得因此提升 Draft Profile 的 Planner 权限。
4. **视觉 Adapter**：默认在真实多模态 Provider 和安全门禁完成前保持 disabled，不提供 OCR 降级。
5. **URL Adapter**：默认只支持公开、无需登录的 HTTP(S) 页面；认证页面和内网 URL 不在首期范围。
6. **下一步建议续跑**：单独形成 continuation 方案；本计划只保证 Skill 在第一次执行前收齐必需材料。

## 23. 最脆弱假设

本方案假设 Skill 维护者能够为生产 Planner-eligible Skill 提供准确、有限且可测试的 User Input Contract。如果合同把实际必需材料误标为可选，Runtime 仍可能生成基于假设的低质量结果；如果把大量非关键材料标为必需，用户会被过度阻塞。因此发布门禁必须同时检查合同测试与 Skill 实际执行行为，而不能只验证 Schema 语法；该检查纳入普通 PR/CI，不新增独立人工审核阶段。

## 24. 开发时间预估

估算前提：一名熟悉当前代码库的全栈开发者，复用现有 SQLite、AgentRun、SSE、React Query 和 Drawer/Form 组件；包含单元测试、API 测试、E2E 和文档，不包含等待外部 Provider、凭证或独立审批的时间。

| 阶段 | 内容 | 预估 |
| --- | --- | ---: |
| Slice 0 | ADR、合同模型、全量 Inventory、Profile 校验 | 1～2 个开发日 |
| Slice 1 | `waiting_input`、文本问询、持久化、API、恢复和基础前端 | 3～5 个开发日 |
| Slice 2 | Run-scoped 文件、Markdown/TXT、CSV、输入预算和 E2E | 3～5 个开发日 |
| Slice 3 | URL Snapshot、SSRF/redirect 防护和测试 | 2～4 个开发日 |
| Slice 4 | 图片安全处理、多模态消息绑定和视觉 Provider 接入 | 3～5 个开发日 |
| Slice 5 | 可调用 Skill 合同收口、D0/D1、回归和真实 smoke | 3～5 个开发日 |

交付区间：

- **最小可用闭环（Slice 0～2）**：7～12 个开发日。支持 Standard Skill 的稳定前置问询、文本、Markdown/TXT、CSV，以及首批 Pilot Skill。
- **可发布版本（加 URL 与全部可调用 Skill 收口）**：12～20 个开发日。
- **完整目标（再加图片视觉能力）**：15～26 个开发日。

两名开发者按后端/前端与 Adapter 分工时，完整目标可压缩到约 9～14 个工作日，但状态机、API 和 E2E 收口仍需串行集成。视觉 Provider 未就绪或 URL 安全策略变更不计入上述区间，应作为外部阻塞单独记录。
