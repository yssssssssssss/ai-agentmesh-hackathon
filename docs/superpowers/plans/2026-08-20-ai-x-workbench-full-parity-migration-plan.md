# AgentMesh AI 工作台完整复刻 ai-x 开发方案（优化版）

> 状态：Proposed，待批准
>
> 日期：2026-08-20
>
> 目标：保留 AgentMesh 主壳，将 AI 工作台内部的研究流程、控制逻辑、能力资产、独立 Tool、报告系统和视觉交互完整对齐 ai-x
>
> 核心优化：最终只有一个可创建新研究任务的主链。现有 `research-v2` 退役为历史兼容，完整研究主链内部标识为 `research-v3`，用户界面统一称为“研究任务”

## 1. 执行摘要

当前 AgentMesh 同时存在：

- v1 普通聊天和 Skill Matrix；
- research-v2 Competitive Research 最小闭环；
- 规划中的 ai-x 完整研究能力。

如果继续让 research-v2 和 research-v3 同时根据自然语言抢占请求，会产生路由、同名 Skill、计划语义和失败降级混淆。本方案将架构收敛为：

```text
普通聊天、Legacy、非研究 Skill
  -> v1

所有新的研究任务和研究 $skill
  -> research-current（持久化值 research-v3）

已有 research-v2
  -> 历史只读兼容
```

用户不会看到 v1、v2、v3 选择器。服务端在 Run 创建时只做一次路由，持久化 immutable orchestration version，后续刷新、SSE、重试和历史打开都不得重新判断。

完整目标包含：

- 5 类 ResearchTask；
- 7 个 Decision Node；
- 22 个研究 Skill；
- 9 个 Tool；
- 5 个独立 Lab；
- 5 个 Deliverable；
- ResearchTaskV2、澄清、ProblemGraph、depth/speed、PlanCompiler；
- Tool、Skill、LLM、Reviewer 异构 DAG；
- lease、wave、retry、skip、abort、UNKNOWN recovery；
- JSON/Binary Artifact、Evidence、FindingGraph、Review；
- Playwright 网页截图、视觉资产、可信图表；
- 专业 ReportDocument、Print/PDF 和 Markdown ZIP；
- ai-x 四阶段 Workbench 和纸质报告视觉；
- Gold Run、独立研究员评审、真实 Provider 和 rollback 门禁。

## 2. 已确认的产品边界

### 2.1 保留 AgentMesh 主壳

继续保留：

- 全局导航；
- 数字员工；
- 个人记忆和团队知识；
- 工作洞察；
- 协作网络和协作市场；
- 当前用户、Workspace、Project 和权限；
- 普通聊天和 Legacy 命令。

AI 工作台内部替换为 ai-x 风格研究工作台。任务历史使用当前 AI 工作台导航展开区，不增加第二套全局侧栏。

### 2.2 研究优先兼容

进入完整研究主链的请求：

- 五类自然语言研究任务；
- 命中 research catalog 的 `$skill`；
- 附带研究输入、截图或数据集的受支持任务。

继续进入 v1 的请求：

- 普通问答；
- Memory、Brief、Note、Data 和 Risk Legacy command；
- 只存在于 v1 Catalog 的 Skill；
- 未迁移的当前项目独有 Skill；
- `AGENTMESH_SKILL_ORCHESTRATION=off` 时的全部新请求。

### 2.3 不原样搬入 ai-x 后端

不复制：

- Express API；
- PostgreSQL Repository；
- TypeScript Orchestrator Runtime；
- ai-x 登录和用户体系；
- ai-x 本地数据库、运行目录和 `.env`。

复刻领域合同、运行语义、能力资产、独立 Tool 源码和 UI。生产实现继续使用当前 FastAPI、Python、Pydantic、SQLite 和 OpenAI Agents SDK。

## 3. ai-x 来源冻结

### 3.1 当前来源身份

- 仓库：`/Users/heyunshen/work/PROJECT/jdc/ai-x`；
- HEAD：`6c9f19fb8109ca6882241bc903d82332a9da0d5e`；
- tracked diff SHA-256：`129e04a175bfd2f657dd705bc56bb6e1a53d4b6693b27265bb19eab15f2d71d0`；
- migration guide SHA-256：`5c0df919394ca33f22b996c9dcf9be060ed820e6c53c7752e6f3951c3d0169b2`；
- 工作区状态：18 个 tracked 修改项，1 个 untracked 文件。

Gate 0 生成并提交：

```text
agentmesh/research_catalog/ai-x-parity-lock.json
```

内容包括：

- source HEAD；
- tracked patch hash；
- 每个迁移文件的路径和 hash；
- Registry、Schema、Prompt、Rubric、Template 和 UI token inventory；
- 22 Skill、9 Tool、5 Deliverable、7 Decision Node 的规范化清单；
- source browser screenshot baseline identity。

开发过程中不自动读取 ai-x 最新文件。任何 source 更新都必须更新 parity lock、运行 source quality、重新生成 fixtures 并经过评审。

### 3.2 禁止迁移的内容

- `.env`、API key、cookie；
- `node_modules`、dist、logs、pids；
- PostgreSQL 和运行时数据；
- run-workspaces、Gold 原始用户材料；
- prompt 原文、Provider 原始响应、Base64；
- 未脱敏错误和本地绝对 secret 路径。

## 4. 最终版本与路由模型

### 4.1 内部版本

| 持久化版本 | 新建 | 历史读取 | 责任 |
| --- | --- | --- | --- |
| `v1` | 是 | 是 | 普通聊天、Legacy、非研究 Skill Matrix |
| `research-v2` | 迁移完成后否 | 是 | 当前 Competitive 最小闭环历史 |
| `research-v3` | 是 | 是 | ai-x 完整研究主链 |

用户界面不显示版本号。开发文档将 `research-v3` 称为 `research-current`。

### 4.2 唯一创建入口

`POST /api/agent/runs` 是唯一版本选择位置。

路由顺序：

1. 若 `client_turn_id` 已存在，回放原 Run；
2. 解析 Legacy `$group.command`，进入 v1；
3. 解析 research catalog `$skill`；
4. Intent Router 判断五类研究任务；
5. 若用户、task type 和 rollout mode 允许，创建 research-v3；
6. 其他请求创建 v1；
7. research-v3 已选中但 Runtime、core Tool 或合同不可用时明确失败，不回退到 research-v2 或普通聊天。

### 4.3 迁移期路由

在 Competitive Text Slice 完成前：

- 非 v3 cohort 的 Competitive Research 继续进入 research-v2；
- v3 cohort 的同类请求只进入 research-v3；
- 同一个用户不会同时看到两个 `$competitive-analysis`；
- Catalog 响应根据 rollout cohort 返回唯一版本。

Competitive Text Slice 通过后：

- 删除 research-v2 新写路由；
- 所有新 Competitive Research 进入 research-v3；
- research-v2 只保留历史读取。

### 4.4 Feature flag

继续使用：

```text
AGENTMESH_SKILL_ORCHESTRATION=off|preview|execute
```

- off：所有新请求进入 v1，历史 v2/v3 只读；
- preview：eligible research-v3 生成 Requirement、ProblemGraph 和 Plan，不执行 Provider；
- execute：eligible research-v3 经确认和审批后执行；
- rollout allowlist 由服务端控制，不增加 Vite flag。

## 5. research-v2 退役策略

### 5.1 复用为 research-current 基础

保留并泛化：

- ResearchRuntime lifespan；
- ResearchWorkflow、state version 和 CAS；
- ArtifactStore；
- Invocation ledger 和 operation key；
- Tool Approval 与 Plan Confirmation 分离；
- lease、heartbeat、fencing；
- UNKNOWN recovery；
- owner/project/workspace scope；
- idempotent command；
- purge/tombstone；
- result integrity projection；
- startup reconciliation 和 off rollback。

这些属于通用控制能力，不属于 v2 专用功能。

### 5.2 被完整模块替换

替换：

- `CompetitiveRequirementPlanner`；
- 简化 `ProblemContract`；
- 单推荐计划；
- 固定 Tool → Skill 两步；
- 固定 `CompetitivePlanCompiler`；
- 只支持 Tool/Skill 的执行器；
- Claim Ledger 作为唯一报告主合同；
- Deterministic-only Review；
- Markdown 字符串 Report；
- v2 新写路由。

替代模块：

- RequirementRefinementService；
- DecisionGraphService；
- ProblemGraphPlanner；
- CapabilityResolver；
- CandidateGenerator；
- 通用 PlanCompiler；
- WaveExecutionEngine；
- Tool/Skill/LLM/Reviewer Actors；
- FindingGraph、DeliverableService；
- ReportReviewService；
- ReportCompositionService。

### 5.3 历史兼容

保留：

- v2 AgentRun、Requirement、Plan、Attempt、Invocation；
- Artifact、Evidence、Claim、Deliverable、Review、Report；
- owner-scoped read；
- integrity verify；
- purge；
- 轻量 V2HistoryAdapter。

新 Workbench 根据 stored orchestration version 选择：

- v2 history renderer；
- v3 current renderer。

满足以下条件后删除 v2 专用交互组件和执行代码：

1. v3 Competitive Text 完整覆盖；
2. v2 无 active Run；
3. v2 历史由兼容 renderer 稳定读取；
4. off rollback 不需要 v2 new-write；
5. 数据保留和审计要求已确认。

## 6. 完整能力目录

### 6.1 Task types

- `competitive_research`；
- `user_research_planning`；
- `voc_diagnosis`；
- `design_audit`；
- `a11y_audit`。

### 6.2 Decision Nodes

- D1 Research Goal；
- D2 Target Audience；
- D3 Method Selection；
- D4 Experience Status；
- D5 Competitive Reference；
- D6 Data Sensitivity；
- D7 Output Standard。

### 6.3 Research Skills

复刻 22 个 ai-x Skill：

- `digital-human-competitive-analysis`；
- `competitive-web-research`；
- `competitive-app-analysis`；
- `design-experience-review`；
- `accessibility-review`；
- `analyze-satisfaction`；
- `build-experience-metrics`；
- `code-open-feedback`；
- `competitive-analysis`；
- `conversion-funnel-analysis`；
- `feature-adoption-analysis`；
- `generate-interview-guide`；
- `generate-persona`；
- `generate-research-plan`；
- `generate-survey`；
- `generate-usability-test`；
- `issue-prioritization`；
- `jobs-to-be-done`；
- `journey-map`；
- `run-heuristic-evaluation`；
- `structure-interview-transcript`；
- `synthesize-qualitative-insights`。

### 6.4 Tools

- `tavily-web-search`，core；
- `playwright-page-capture`，optional；
- `ai-spider-search`，optional；
- `aesthetic-quant-lab`，optional；
- `attention-analysis-lab`，optional；
- `experience-model-lab`，optional；
- `virtual-user-lab`，optional；
- `vision-brand-lab`，optional；
- `o2-web-search`，draft optional。

### 6.5 Deliverables

- `research_plan`；
- `competitive_analysis_report`；
- `voc_diagnosis_report`；
- `design_audit_report`；
- `accessibility_audit_report`。

### 6.6 Knowledge

复刻或映射：

- 179 个方法知识 Markdown；
- 22 个 Schema；
- Decision Graph；
- Skill/Tool/Deliverable Registry；
- Evidence Policy；
- prompts、rubrics 和 templates。

与当前 2C DesignWiki 内容相同且 hash 一致时复用。不同版本保留 ai-x snapshot，不覆盖当前 Wiki。

## 7. Skill 版本处理

### 7.1 重叠 Skill

当前项目与 ai-x 重叠 8 个 Skill，但文件 hash 全部不同：

- `build-experience-metrics`；
- `competitive-analysis`；
- `generate-interview-guide`；
- `generate-research-plan`；
- `generate-survey`；
- `generate-usability-test`；
- `issue-prioritization`；
- `jobs-to-be-done`。

处理：

```text
v1 Run
  -> 当前 builtin_skills 版本

research-v3 Run
  -> ai-x parity lock 版本
```

不允许按加载顺序覆盖同名 Skill。Catalog 由 immutable orchestration version 选择。

### 7.2 当前项目独有 Skill

`prd-feasibility`、`query-experiment-conclusions` 和后续当前项目 Skill 继续 v1。进入 research-current 前必须补齐：

- task type；
- input/payload schema；
- required/optional Tool；
- Evidence Policy；
- Deliverable mapping；
- planning/execution/review/report tests。

### 7.3 ai-x 独有 Skill

只进入 research catalog，不自动暴露给 v1 Skill Matrix。

### 7.4 Legacy

11 个 `$group.command` 保持 v1。需要成为研究 Tool 时必须经过 manifest、permission、risk、receipt、Artifact 和 Evidence Adapter 包装。

## 8. 独立 Tool 进程

### 8.1 五个 Lab 原始边界

迁移以下完整项目源码，保留 core、server、web 和独立 package：

| Lab | server | web |
| --- | ---: | ---: |
| aesthetic-quant-lab | 8801 | 5801 |
| attention-analysis-lab | 8802 | 5802 |
| experience-model-lab | 8803 | 5803 |
| virtual-user-lab | 8804 | 5804 |
| vision-brand-lab | 8805 | 5805 |

目标目录：

```text
external-tools/
  aesthetic-quant-lab/
  attention-analysis-lab/
  experience-model-lab/
  virtual-user-lab/
  vision-brand-lab/
```

主系统不 import Lab 代码，通过 HTTP 调用 880x，通过工具箱打开 580x。

### 8.2 加固

ai-x 本地 Lab 默认无鉴权，不能原样用于共享环境。迁移后增加：

- server-to-server token 或受控反向代理；
- health/readiness；
- request size 和 concurrency limit；
- timeout、retry、redaction；
- implementation ID、package version、build hash；
- 独立 install/build/start/stop/smoke；
- tool-stack 状态文件和 PID identity；
- required fail closed、optional gap。

### 8.3 其他 Tool

- Tavily、ai-spider、O2：迁移 manifest、schema 和 Adapter，不复制 Provider；
- Playwright：迁移语义，使用 Python Adapter 启动受控 Chromium 子进程，不引入 ai-x Node Orchestrator；
- `users-research-all` 不在 active Registry 或 Workbench Labs，不属于本次范围。

### 8.4 自包含验收

迁移完成后移除 ai-x 目录，AgentMesh 和五个 Lab 必须仍能安装、启动、执行、恢复和通过 smoke。

## 9. 目标研究流程

```text
用户输入
  -> 单一路由裁决
  -> ResearchTaskV2
  -> 阻断歧义澄清
  -> Decision Graph
  -> 方法知识召回
  -> ProblemGraph
  -> CapabilityResolver
  -> depth / speed
  -> 用户选择 / revise
  -> pending values / images
  -> Plan Confirmation
  -> Role Approval
  -> 用户明确 Execute
  -> DAG waves
  -> Tool / Skill / LLM / Reviewer
  -> SEALED Artifacts
  -> Evidence Manifest
  -> FindingGraph
  -> Deliverable
  -> Deterministic Review
  -> Semantic Review
  -> 最多一次 Revision
  -> ReportDocument
  -> Web / PDF / Markdown ZIP
  -> History / Audit / Purge
```

`$skill` 只跳过自动 Skill 排名，不能跳过 Requirement、ProblemGraph、Tool、Approval、Artifact、Evidence 和 Review。

## 10. 领域合同

### 10.1 ResearchTaskV2

字段：

- task type；
- business domain；
- research goal；
- comparison dimensions；
- target audience；
- scope；
- constraints；
- success criteria；
- expected deliverables；
- assumptions；
- ambiguities；
- clarification questions；
- blocking issues；
- sensitivity；
- PII status。

每次理解或澄清创建 immutable Requirement Version。

### 10.2 ProblemGraph

每个问题包含：

- stable ID；
- statement、rationale；
- required/optional；
- success criterion IDs；
- Evidence requirements；
- acceptance criteria；
- dependencies。

ProblemGraph 与 Execution DAG 分开保存，并记录模型 receipt 和 provenance。

### 10.3 Candidate 和 Plan

- depth 最多 8 Step；
- speed 最多 4 Step；
- actor：Tool、Skill、LLM、Reviewer；
- input 和 RFC6901 bindings；
- expected outputs；
- required approval；
- capability decisions/gaps；
- deliverable contract；
- Evidence Policy；
- actor/schema/resource/model snapshots；
- canonical plan hash。

Plan revision 创建新版本，不修改 frozen plan。

## 11. PlanCompiler

校验：

- strict Candidate/Step schema；
- server-owned step identity；
- DAG cycle 和 dependency；
- ProblemGraph coverage；
- Evidence Policy coverage；
- actor eligibility；
- required Tool 前置；
- optional Tool 非关键输入；
- JSON Pointer source/target；
- pending input targets；
- approval authority；
- Skill `/payload`；
- LLM `/text`；
- Reviewer `/review`；
- model/resource snapshots；
- plan hash。

LLM 只提出候选，PlanCompiler 决定能否执行。

## 12. 执行与恢复

### 12.1 DAG

- 最多 8 Step；
- DAG depth 最多 4；
- 每 wave 最多 3 个并发 Step；
- 每 attempt 最多 24 次 Tool 调用；
- deadline 300 秒；
- 最多 4 个 active attempt；
- core failure 阻断下游；
- optional failure 形成 gap；
- Tool/Skill/LLM/Reviewer 各自产生 Artifact。

### 12.2 Invocation

状态：

- prepared；
- sent；
- acknowledged；
- unknown；
- failed；
- aborted。

Provider 支持幂等时传递 operation key。不支持结果查询时，UNKNOWN 禁止自动 replay，必须用户 retry 或 abort。

### 12.3 Retry、Skip、Abort

- retry 创建新 Attempt；
- 只复用全部 hash 一致的 read-only Tool output；
- browser screenshot 不复用；
- skip 只允许 optional failed Step，并生成新 Plan Version；
- abort 保留审计，晚到结果不能覆盖 terminal state。

### 12.4 Recovery

FastAPI lifespan 负责：

- startup recovery；
- 15 秒 heartbeat；
- 30 秒 reconciliation；
- expired lease；
- STAGING cleanup；
- visual publication recovery；
- graceful shutdown；
- SENT/UNKNOWN 诚实记账。

## 13. Artifact、多模态和安全

### 13.1 JSON Artifact

```text
STAGING -> SEALED 或 FAILED
```

读取重新校验 owner、task、plan、attempt、step、kind、schema、hash 和 lineage。

### 13.2 Binary Artifact

- PNG、JPEG、WebP、sealed SVG；
- 最大 10 MiB；
- 最大 20 MP；
- 拒绝动画、多页、截断和伪造图片；
- Pillow 完整解码；
- no-clobber 和 fixed-length read；
- allow/mask/block export policy。

### 13.3 Playwright

```text
Tavily URL
  -> optional Playwright Tool
  -> JSON metadata + in-memory bytes
  -> Binary Artifact
  -> Visual Manifest
```

安全：

- sandbox；
- 无持久 Cookie/storage；
- HTTPS only；
- private IP / metadata host 阻断；
- redirect 最多 5；
- Service Worker、WebSocket、下载和弹窗阻断；
- 2 active、8 queued、10 秒 queue timeout、90 秒 total deadline；
- 不访问登录、付费、验证码和个人账户页面；
- 不执行模型提供的 JavaScript。

## 14. Evidence、FindingGraph 和 Deliverable

### 14.1 Evidence classes

- public source；
- screenshot；
- user input；
- knowledge；
- dataset；
- simulation；
- derived。

公开事实必须绑定 real Tool、SEALED Artifact、pointer、URL 和 receipt。

保留：

- quote；
- retrieved at；
- source kind；
- registrable domain；
- independence group；
- conflict status；
- risk flags；
- truncation marker。

### 14.2 FindingGraph

- Fact；
- Inference；
- Analysis；
- SubQuestion Summary；
- Overall Conclusion；
- Recommendation。

Claim Ledger 只作为历史兼容和轻量投影，不再是研究主合同。

### 14.3 Deliverable

每个 Deliverable 冻结：

- payload schema；
- synthesis prompt；
- Evidence Policy；
- review rubric；
- report template；
- visual requirements。

校验 schema、FindingGraph、Evidence、question coverage、success criterion coverage、provenance、visual references 和 gaps。允许一次受限修复。

## 15. Review 和 Report

### 15.1 Review

确定性与语义维度：

- requirement coverage；
- question coverage；
- evidence coverage；
- reasoning quality；
- recommendation quality；
- visual quality；
- risk disclosure。

结果：pass、revise、block。revise 最多一次，确定性失败不能被模型覆盖。

### 15.2 ReportDocument

支持五类专业模板。竞品报告包括：

- Cover；
- Executive Summary；
- Context / Objectives；
- Sample / Method；
- Metrics；
- Findings / Matrix；
- Question Analysis；
- Visual Evidence；
- Competitive Impact；
- Conclusions；
- Prioritized Actions；
- Risks；
- Sources / Appendix。

支持 Web、Print/PDF、Markdown ZIP、images、Manifest、Review 和 ReportDocument JSON。

## 16. AI 工作台视觉

### 16.1 视觉原则

- 暗色研究桌面；
- 靛蓝流程强调；
- 760px 阶段流；
- 1240px 报告阅读；
- warm paper 专业报告；
- serif report headings；
- Evidence、图片和图表渐进披露。

### 16.2 精确 token

| Token | Value |
| --- | --- |
| bg | `#0a0d16` |
| elevated | `#10141f` |
| card | `#151a27` |
| card high | `#1c2233` |
| border | `#232a3d` |
| text | `#e6e9f0` |
| dim | `#a5adbf` |
| faint | `#6b7488` |
| primary | `#7c7cf0` |
| primary strong | `#9ea0ff` |
| success | `#34d399` |
| warning | `#fbbf24` |
| danger | `#f87171` |
| report paper | `#f6f4ee` |
| report ink | `#1c2230` |
| report accent | `#5f60d9` |

CSS 限制在 `.research-workbench-current`，不覆盖 AgentMesh 全局 Tailwind。

### 16.3 组件

- Welcome；
- UserBubble；
- PlanProgress；
- Stage1 Understand / Clarify；
- Stage2 Candidates / Plan；
- Approval / Ready；
- Stage3 DAG；
- Failure / Gap；
- Stage4 Report；
- Evidence disclosure；
- Image zoom / comparison；
- Chart；
- Labs；
- `$skill` menu。

research-v2 历史只使用兼容 renderer，不继续维护完整旧交互。

## 17. HTTP 和数据

### 17.1 Aggregate projection

`GET /api/agent/runs/{run_id}/research` 返回 versioned union：

- v2 history projection；
- research-current projection。

GET、SSE 和 refresh 纯读取。

### 17.2 Mutations

- clarify；
- select；
- revise；
- confirm；
- approve；
- execute；
- resume retry/skip/abort；
- cancel；
- purge。

全部要求 expected state version、Idempotency-Key 和 request hash。

### 17.3 数据兼容

- migration additive；
- v1 不变；
- v2 历史不改写；
- research-current 使用新 contract version；
- v2 Artifact 不自动升级为 current Evidence；
- purge 保留 tombstone 和必要审计；
- 不做数据库 downgrade。

## 18. 纵向实施计划

### Gate 0：来源冻结和路由收敛

交付：

- ai-x parity lock；
- ADR 0006，明确单 active research writer；
- v2 reusable / replace / retire 清单；
- source/target fixtures；
- visual screenshot baselines；
- current v1/v2 regression baseline；
- rollout cohort 和唯一 Router tests。

不修改生产路由，不调用 Provider。

### Slice 1：Competitive Text Research

完整用户闭环：

- ResearchTaskV2；
- clarification；
- Decision Graph；
- knowledge recall；
- ProblemGraph；
- depth/speed；
- select/revise/confirm；
- Tool/Skill/LLM/Reviewer DAG；
- wave/retry/skip/abort；
- Evidence/FindingGraph；
- Competitive Deliverable；
- deterministic + semantic Review；
- text ReportDocument；
- ai-x stage UI；
- history restore。

Slice 1 通过后立即停止 research-v2 新写。

### Slice 2：Competitive Multimodal

- Playwright；
- Binary Artifact；
- Visual Manifest；
- screenshot Evidence；
- annotation/heatmap；
- trusted chart；
- paper report；
- Print/PDF；
- Markdown ZIP；
- five Lab UI；
- history restore。

### Slice 3：User Research Planning

迁移对应 Skill 和 `research_plan`，支持研究计划、访谈、问卷、Persona、Journey、指标和方法组合。

### Slice 4：VOC Diagnosis

迁移满意度、开放反馈编码、Journey 和 `voc_diagnosis_report`。

### Slice 5：Design / Accessibility Audit

迁移设计体验审查、启发式评估、可用性测试、无障碍审查和两个专业报告。

### Slice 6：独立 Tool、Gold 和最终切换

- 五个 Lab server/web 完整迁移和加固；
- ai-spider real；
- digital-human 和 app competitive skills；
- O2 draft parity；
- Gold batches；
- independent researcher review；
- 10 人 pilot；
- research-current default；
- v2 specialized execution/UI removal；
- rollback rehearsal。

每个 Slice 可独立合并和使用。

## 19. 测试节奏、Parity 和发布门禁

### 19.1 测试执行原则

开发过程中禁止“完成一个函数、组件或小功能就运行测试”的碎片化循环。测试代码仍需随行为变化补充，但统一在有意义的集成边界执行。

执行节奏固定为四级：

1. **实现批次**：连续完成一组强相关修改，不运行全量测试；
2. **工作包检查点**：一个完整 Module、Actor、页面阶段或 Tool Adapter 接通后，只运行直接相关的 targeted tests；
3. **Slice 门禁**：一个纵向 Slice 达到可用闭环后，统一运行该 Slice 的 backend、frontend 和 browser integration；
4. **Release Candidate 门禁**：准备合并或灰度前，才运行全量 pytest、Ruff、前端单测、build、E2E、catalog 和 eval。

禁止：

- 每改一个文件运行一次 pytest；
- 每完成一个小组件运行全部 Vitest；
- 每修复一个失败立即重跑全量套件；
- 在同一工作包中反复运行没有相关代码变化的测试；
- 在每个开发批次调用真实 LLM、Tavily、Playwright 或 Lab；
- 为每个 CSS 微调生成全套截图；
- 把测试次数或测试数量当成开发进度。

测试失败时：

- 先集中修复同一原因影响的全部代码；
- 只重跑失败测试和直接依赖测试；
- 工作包结束时再运行一次 targeted set；
- Release Candidate 最后只做一次完整串行回归。

### 19.2 工作包测试预算

每个工作包默认最多执行：

- 一次相关后端测试集合；
- 一次相关前端测试集合；
- 需要真实渲染时一次限定状态的 browser check；
- 不运行真实 Provider smoke。

以下高风险工作包允许在模块完成后增加一次 focused verification，但仍不能按小功能执行：

- 数据库 migration；
- auth 和 owner scope；
- lease/fencing；
- Tool Approval 和 UNKNOWN recovery；
- Artifact seal/readback；
- SSRF、Prompt Injection 和 export security；
- 外部副作用 settlement。

真实 Provider 只在 Slice 验收和 Release Candidate 阶段运行。

### 19.3 Source parity

规范化比较：

- Requirement；
- ProblemGraph；
- Capability decisions；
- depth/speed；
- state transitions；
- Evidence；
- Deliverable；
- Review；
- ReportDocument。

忽略 UUID 和时间，只比较语义字段、错误码和状态。Source parity 在工作包中只更新 fixture，不逐文件运行；统一在 Slice 门禁执行。

### 19.4 Capability parity

Slice 门禁统一断言：

- 5 task types；
- 7 Decision Nodes；
- 22 Skills；
- 9 Tools；
- 5 Deliverables；
- 5 Labs；
- Registry 和资源 hash。

未涉及 Catalog 的工作包不运行 Capability parity。

### 19.5 Visual parity

只比较 AI 工作台 inner surface：

- 1440x900；
- 1280x800；
- 390x844。

状态：idle、clarify、candidates、plan、approval、DAG、paused、text report、multimodal report、print。

Visual parity 只在 Slice 1、Slice 2 和最终 Release Candidate 执行。普通文案、间距或单组件修改不单独运行整套截图。

### 19.6 Slice 门禁

每个 Slice 完成后只运行与该 Slice 相关的集合：

- Slice 1：路由、Requirement、Planning、DAG、Text Report 和 Workbench E2E；
- Slice 2：Playwright、Binary Artifact、Visual、Chart、Export 和 multimodal E2E；
- Slice 3：User Research Planning contracts、Skills、Deliverable 和 journey E2E；
- Slice 4：VOC contracts、dataset security、Deliverable 和 journey E2E；
- Slice 5：Design/A11y、visual input、annotation 和 report E2E；
- Slice 6：Labs、Gold、cutover、off rollback 和 compatibility。

Slice 内部工作包不重复执行全量门禁。

### 19.7 Release Candidate 全量门禁

仅在准备合并、进入 preview/execute 灰度或完成重大 Slice 时运行：

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
npm --prefix agentmesh-demo test -- --run
npm --prefix agentmesh-demo run api:types
npm --prefix agentmesh-demo run build
npm --prefix agentmesh-demo run test:e2e
.venv/bin/python eval/run_skill_retrieval_eval.py
.venv/bin/python scripts/skill_catalog_report.py agentmesh/builtin_skills
.venv/bin/python eval/research_orchestration/run_eval.py
```

新增 parity、crash、tamper、SSRF、prompt injection、export 和 independent Tool process tests，但它们按对应 Slice 和 Release Candidate 批量执行。

### 19.8 Source gate

只有更新 parity lock 时才在 ai-x 执行：

```bash
pnpm quality
```

普通 target 开发不重复运行 source 全量测试。

### 19.9 真实 Provider 和真人门禁

真实 Provider smoke 每个 Slice 最多执行一个预定义闭环，Release Candidate 再执行完整矩阵。

真人门禁只在对应 task type 工程闭环稳定后执行：

- 五类任务各一个 Gold；
- 关键场景连续三次真实运行，至少两次研究员判定可用；
- 两名独立研究员盲评；
- 10 人试点，至少 8 人认可 Evidence 和 gap；
- 来源伪造、敏感泄漏或 gate bypass 立即重置批次。

## 20. 安全不变量

- 单一版本路由；
- 客户端不提交 structured task、ProblemGraph、plan 或 hash；
- core Tool 必须 real；
- Plan Confirmation 不批准 Tool；
- GET/SSE/refresh 不调度；
- Skill 无隐式 Tool；
- Artifact SEALED + hash readback；
- Evidence 精确 Artifact/pointer；
- LLM、simulation、knowledge 不冒充 public fact；
- stale lease/fencing 不能 settle；
- UNKNOWN 不自动 replay；
- Web 内容不可信；
- SSRF、redirect、script 和 export 门禁；
- blocked visual 不显示、不导出；
- Review 未 pass 不生成 Report；
- private prompt、key、Bearer、Base64 不进入长期 Artifact；
- owner/project/workspace 失败返回 404；
- Lab service 有独立 auth 和 health；
- purge 保留 tombstone，不保留原文。

## 21. 灰度与回滚

### 21.1 灰度

1. off：全部新请求 v1；
2. preview allowlist：research-current 只规划；
3. execute competitive allowlist；
4. Competitive 全量进入 current，v2 停止新写；
5. 按 task type 扩展；
6. 完成人工门禁后扩大 execute；
7. 删除 v2 专用 writer 和 UI。

### 21.2 回滚

设置 off：

- 新请求 v1；
- v2/current 历史可读；
- 不删除数据；
- 不 downgrade；
- 不自动恢复 approval；
- 已 SENT 调用只做诚实结算；
- 不重新启用 v2 新写作为 fallback。

## 22. 工作量

完整范围包含 22 Skill、9 Tool、五个独立 Lab、五类任务、视觉报告和真人门禁。

预计：

- 主仓库修改或新增 120 到 180 个文件；
- 五个 Lab 迁移约 164 个源码文件；
- 总影响约 250 到 350 个文件；
- 新增前端依赖：Embla、ECharts、fflate；
- 新增 Python 依赖：Playwright、Pillow；
- 不新增第二个 Orchestrator、消息队列或 PostgreSQL。

P50：

- 2 后端 + 1 前端 + 1 Tool Integration + 1 Research QA：18 个日历周；
- 单工程师：36 个工程周。

P90：

- 同配置团队：26 个日历周；
- 单工程师：52 个工程周。

## 23. 关键风险

| 风险 | 应对 |
| --- | --- |
| v2/current 同时抢请求 | 单 Router、cohort 隔离、Competitive 切换后删除 v2 writer |
| 同名 Skill 覆盖 | orchestration version 选择 catalog |
| source 继续变化 | parity lock，不静默更新 |
| 独立 Lab 无鉴权 | token/反向代理、health、smoke |
| Python/TS 语义漂移 | fixture、state 和 error parity |
| v2 历史损坏 | 只读 Adapter、hash verify、无数据 rewrite |
| Playwright 安全 | sandbox、SSRF、queue、deadline、no login |
| SQLite 写放大 | active attempt 上限、batch write、retention/GC |
| 报告 bundle 过重 | lazy assets、chunk、bundle budget |
| 研究质量不达标 | Gold、独立评审、三次运行和 pilot stop condition |
| 工期低估 | Slice 验收和 P50/P90，不按文件完成率宣称成功 |

## 24. 明确未知项

| 未知项 | Owner | 最晚时点 | 处理 |
| --- | --- | --- | --- |
| ai-x dirty patch 是否纳入 lock | ai-x maintainer | Gate 0 | 未批准文件不迁移 |
| ai-spider endpoint/credential | Integration owner | Slice 6 | 未通过保持 optional unavailable |
| 五 Lab 鉴权和生产容量 | Lab owners | Slice 2/6 | 每个独立 smoke |
| Playwright 出站隔离 | Platform/Security | Slice 2 execute | 无隔离仅 preview |
| 五类 Gold rubric | Research lead | 对应 execute 前 | 先冻结 rubric |
| execute allowlist | Product/Release owner | Slice 1 | 服务端配置 |

## 25. 拒绝的方案

- 不让用户选择 v2/v3；
- 不让两个自然语言路由器并行抢请求；
- 不在 current 失败后回退 v2；
- 不 iframe 或反向代理 ai-x 主应用；
- 不把 TypeScript Orchestrator 放入当前仓库；
- 不继续扩展固定两步 research-v2；
- 不覆盖当前同名 v1 Skill；
- 不把五个 Lab 塞进 FastAPI；
- 不一次性 Big Bang；
- 不删除历史审计数据；
- 不把 Mock 结果算作能力 parity。

## 26. 完成定义

1. 来源 parity lock 可重复验证；
2. 新研究任务只有 research-current 一个 writer；
3. research-v2 不再新建，历史可读；
4. 五类任务完整；
5. 7 Decision Nodes、22 Skills、9 Tools、5 Deliverables、5 Labs 等价；
6. depth/speed、select、revise、confirm、approval 完整；
7. Tool/Skill/LLM/Reviewer DAG 和 wave 完整；
8. JSON/Binary Artifact、Evidence、FindingGraph、Review、Report 完整；
9. Playwright、Visual、Chart、PDF、ZIP 完整；
10. Workbench inner visual parity 完整；
11. v1 普通聊天、Legacy、知识和协作无回归；
12. v1/v2/current 历史读取正确；
13. owner、approval、lease、UNKNOWN、SSRF、prompt injection、export tests 通过；
14. source/target contract/state/capability/browser/report parity 通过；
15. full test、build、E2E、catalog 和 eval 通过；
16. real Provider、restart verify、off rollback 通过；
17. Gold、独立研究员和 10 人 pilot 通过；
18. v2 专用执行和交互代码已删除或归档；
19. README、CONTEXT、ADR、runbook 和 OpenAPI 与实现一致。

## 27. 批准后的第一步

只执行 Gate 0：

- 冻结 ai-x parity lock；
- 创建 ADR 0006；
- 固定 single active research writer；
- 建立 source/target fixtures 和 screenshot baselines；
- 记录当前 v1/v2 回归；
- 不改生产路由；
- 不复制 Tool 源码；
- 不调用真实 Provider；
- 不迁移用户数据。

Gate 0 评审通过后再开始 Slice 1。
