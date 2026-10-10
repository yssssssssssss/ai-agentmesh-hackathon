# AgentMesh 项目说明报告

> **数字员工 × Agent 协作市场 × 受治理的工作执行平台**  
> 文档性质：基于当前仓库代码、配置、ADR 与本地验证结果形成的现状报告；不是产品路线图，也不是生产发布承诺。

| 项目快照 | 内容 |
| --- | --- |
| 报告日期 | 2026-09-10（CST） |
| Git 分支 | `feature/skill-input-preflight` |
| Git 提交 | `0ada4bb29973fff565e9120bad04165b83406e92`（`Add Skill input preflight workflow`） |
| 代码版本 | Backend `0.1.0`；Frontend `1.0.0` |
| 快照状态 | 生成报告前工作区 clean；报告仅新增本目录下 `.md` 与 `.html` 两个文件 |
| 主要运行形态 | Python 3.12+ / FastAPI / SQLite；React 18 + TypeScript + Vite；可信内网、单 Workspace、单进程 |

## 目录

- [1. 执行摘要](#executive-summary)
- [2. 项目定位与核心价值](#positioning)
- [3. 核心能力全景](#capabilities)
- [4. Skill 能力目录](#skill-catalog)
- [5. 技术特点](#technical-characteristics)
- [6. 项目架构](#architecture)
- [7. 核心业务流程](#core-flows)
- [8. 核心领域对象与状态边界](#domain-model)
- [9. 前端、API 与数据呈现](#frontend-api)
- [10. 部署与配置边界](#deployment)
- [11. 当前限制与风险](#limitations)
- [12. 验证结果](#verification)
- [13. 综合结论与近期优先级](#conclusion)
- [附录 A：证据索引](#evidence-index)
- [附录 B：ADR 生效关系](#adr-precedence)

<span id="executive-summary"></span>
## 1. 执行摘要

### 1.1 一句话定义

AgentMesh 不是单纯的聊天机器人，而是一个面向团队知识工作场景的 **Agent 控制面原型**：它以每位用户的个人数字员工为入口，把对话、Skill 选择与编排、工具调用、任务交付、人审、知识沉淀、记忆复用和跨人协作放进同一套可追踪的服务端状态机中。

### 1.2 当前判断

| 判断维度 | 结论 | 依据 |
| --- | --- | --- |
| 产品闭环 | **已形成** | 从个人对话/Skill，到 Task、Artifact、Review、Memory、再次检索复用均有实现 |
| 工程完整度 | **较高的原型级实现** | 169 个 OpenAPI 操作、持久化状态机、幂等/CAS、审计、SSE、恢复与容量控制 |
| Skill 平台 | **目录完整，生产信任未完成** | 84 个内置 Skill、84/84 Profile；仅 10 个当前 Planner eligible，74 个为 draft |
| 内网演示/受控试点 | **可用，但需按门禁配置** | 后端、前端单测与构建通过；核心 smoke 与容量基准通过 |
| 生产发布 | **当前不建议** | Universal 检索边界门禁失败；0/84 Profile 完成生产审批；真实 Provider 与浏览器 E2E 未完成 |
| 公网部署 | **明确不支持** | 当前边界是可信内网、单 Workspace、单应用进程、单 SQLite 数据库 |

### 1.3 最重要的五点

1. **核心价值是“受治理地完成工作”，而不只是生成文本。** AgentRun、SkillPlan、Artifact、Task Review、Memory Review 和 Inbox 共同形成可暂停、可审批、可恢复、可审计的执行链。
2. **个人记忆与团队知识有明确边界。** 个人内容默认私有；任务交付审核通过也不会自动进入团队知识，必须再次经过 Memory Review。
3. **Skill 平台已经具备目录、检索、快照、DAG、执行前重校验和输入预检等关键基础设施。** 但“代码能力存在”不等于“生产可信”：Profile 审批、Provider 验收和检索边界仍是硬门槛。
4. **DeepSearch 是 v1 Runtime 上的显式规划模式。** 它不是已退役的 `research-v2`/`research-v3`；后两者只保留历史读取或历史文档。
5. **当前最适合的定位是内部创新验证与受控试点。** 架构强调安全默认值和证据链，但尚未完成公网、多租户、水平扩展、真实 Provider 全链路验收。

<span id="positioning"></span>
## 2. 项目定位与核心价值

### 2.1 面向的问题

团队知识工作通常存在四个断点：

- 对话产生的结论没有进入任务与交付体系；
- Agent 能调用什么、何时需要批准，缺少稳定边界；
- 个人经验难以在不直接暴露原始材料的情况下参与协作；
- 交付物、审核、知识沉淀和后续复用之间没有可追溯链路。

AgentMesh 的设计把这些断点收敛为一条受治理链路：

```text
用户意图
  → 对话 / 显式 Skill / 自动规划
  → 运行前输入预检
  → AgentRun + SkillPlan
  → Tool / Skill 执行
  → Artifact 与来源证据
  → Task Review
  → Personal Memory 或 Team Candidate
  → Memory Review 与生命周期治理
  → 后续 Agent 上下文复用 + Memory Use Receipt
```

### 2.2 核心用户角色

- **普通成员**：使用个人数字员工、私有对话、文档、个人记忆、任务和协作市场。
- **Team Lead**：在默认角色策略上可管理项目任务、审核交付、审核/治理团队知识、管理公共 Agent。
- **Admin**：除业务能力外，可管理用户、团队、权限策略、风险策略、Provider/O2 状态与审计。

### 2.3 产品核心价值

| 价值 | 项目中的具体体现 |
| --- | --- |
| 工作可执行 | 显式 Skill、单 Skill Runtime、多 Skill DAG、DeepSearch、工具网关 |
| 人机边界清晰 | Plan Approval、Tool Approval、Task Review、Memory Review 是不同闸门 |
| 知识可治理 | 个人/项目/团队 Scope、短/中/长期 Layer、候选/接受/争议/废弃/归档生命周期 |
| 过程可追踪 | Run Event、AuditEvent、Provider/Model provenance、Artifact hash、Memory Use Receipt |
| 协作可闭环 | Blackboard、执行锁、交接、协作市场、代答确认、采纳、贡献记录、血缘关系 |
| 降级可解释 | 无模型或 Provider 时使用明确 fallback，并记录 requested/actual provider 与原因 |

<span id="capabilities"></span>
## 3. 核心能力全景

状态说明：**默认可用**表示不依赖额外生产 Provider；**条件可用**表示代码已实现但需要配置或开关；**历史只读**表示仅保留兼容读取；**未实现/后置**表示不应对外宣称已具备。

| 能力域 | 当前能力 | 状态与默认值 | 主要证据 |
| --- | --- | --- | --- |
| 身份与权限 | 本地密码、12 小时 HttpOnly Session、Bearer 兼容、企业 OAuth 适配、角色与可覆盖 capability 策略 | 本地能力默认可用；OAuth 条件可用 | `agentmesh/auth.py`、`routes/auth.py`、`permissions.py` |
| AI 工作台 | 私有 Thread、多轮消息、自然对话、显式 `$` Skill、来源、模型/Provider trace、历史恢复 | 默认可用；外部模型未配置时显式降级 | `routes/chat.py`、`agents.py`、`agent_runtime/` |
| Agent Runtime | OpenAI Agents SDK、结构化输出、Tool Grant、Tool 审批、中断恢复、Run Event、SSE | `AGENTMESH_AGENT_RUNTIME=v2` 时启用 | `agent_runtime/service.py`、`tool_runtime/` |
| Skill 平台 | 84 个内置 Skill、11 个 Legacy 命令、Profile、混合检索、候选快照、版本化规划合同 | 目录已实现；编排默认 `off` | `skill_runtime/`、`builtin_skills/`、ADR 0004/0009 |
| Skill Input Preflight | Schema 驱动表单、文本/Markdown/TXT/CSV、Run 私有输入 Artifact、冻结绑定、恢复执行 | 当前分支已实现；1 个 Skill 使用 preflight | `input_contracts.py`、`input_preflight.py`、ADR 0015 |
| 多 Skill 编排 | 最多 12 个候选、6 个节点、深度 4、并发 3；DAG、审批、重试、部分完成、取消 | `preview/execute` 条件可用；生产激活未授权 | `skill_runtime/planner.py`、`executor.py`、`finalization.py` |
| DeepSearch | 显式 Requirement、澄清、ProblemGraph、Plan、真实 Web 证据、预算、封存报告、恢复 | 默认关闭；需 Runtime/模型/真实 Web Provider/`execute` | `deepsearch/`、`routes/deepsearch.py`、ADR 0008/0009 |
| 项目任务 | 任务 CRUD、交付阶段、指派、优先级、父子/依赖图、里程碑、日历、Agent 队列 | 读取默认可用；写入默认 `read_only` | `task_management/`、`task_operations/`、ADR 0011/0014 |
| 任务交付审核 | Run 绑定、封存 Artifact 集合、指定 Reviewer、接受/返工/拒绝、Reviewer 专属读取 | 条件可用，受任务写入与权限控制 | `task_review/`、`routes/task_reviews.py` |
| 记忆与知识治理 | Personal/Project/Team、三层记忆、候选审核、修订、争议/废弃/过期/归档、血缘 | 默认可用；自动上下文注入默认关闭 | `memory_governance/`、`memory_context/`、ADR 0012/0013 |
| 检索 | SQLite FTS5、Scope/权限过滤、来源与引用；可选向量检索 | FTS 为基线；Embedding 默认关闭 | `retrieval/`、`store.py`、ADR 0001 |
| 文档 | TXT/Markdown/PDF/DOCX/PPTX/图片 OCR；同步/有界后台解析；分块写入私有记忆 | 文本与办公文档可用；图片依赖 Tesseract | `documents.py`、`ingestion.py`、`routes/documents.py` |
| Blackboard 协作 | 请求、证据、回复、已读、执行锁、交接、自动发布队列 | 基础能力可用；后台 Worker 默认关闭 | `routes/blackboard.py`、`agents.py` |
| 协作市场 | 参与开关、信号、匹配、代答确认、采纳、贡献记录与 lineage、个人关系图 | 代码和 UI 已实现；总开关默认关闭 | `marketplace.py`、`routes/market.py`、`pages/Market.tsx` |
| 外部数据与研究 | Tavily、可选 Firecrawl、O2 CLI、HTTP Data API、本地指标 fallback、MCP 工具 | 条件可用；真实 Provider 依赖宿主配置 | `web_research.py`、`o2.py`、`datasources.py`、`tool_runtime/mcp.py` |
| 运维与诊断 | 健康检查、Provider readiness、审计、容量控制、quiesce、dispatch receipt、启动恢复 | 已实现；真实发布 smoke 尚未执行 | `routes/health.py`、`runtime_capacity.py`、`runtime_admission.py` |
| 历史 Research | `research-v2` Run/Artifact 精确版本、Owner Scope、只读投影 | 历史只读；所有 mutation 已退役 | `research_orchestration/v2_history.py`、ADR 0007 |
| Research v3 | 无当前入口、Runtime、UI 或恢复路径 | 已退役，且未曾生产启用 | ADR 0008 |
| 双通道会议采集 | 麦克风/系统音频识别“我/他人” | 未实现；属于未纳入本仓库的 designOS | `CONTEXT.md`、ADR 0003 |

<span id="skill-catalog"></span>
## 4. Skill 能力目录

### 4.1 目录统计

本报告通过 `scripts/skill_catalog_report.py` 和实际 Profile 加载得到以下清单，而不是按目录名人工估算：

| 指标 | 当前值 | 解读 |
| --- | ---: | --- |
| 内置 Skill | 84 | 84 个唯一名称，Profile 覆盖 84/84 |
| 设计前 / 设计中 / 设计后 | 17 / 26 / 41 | 与 Profile `primary_stage` 一致 |
| Planner eligible | 10 | 当前遗留 Pilot 集合；不代表已完成生产审批 |
| Draft Profile | 74 | 不进入生产候选，不授予运行信任 |
| Legacy `$group.command` | 11 | 与内置 Skill 分开，均不参与 Planner |
| 当前适配路径完整 / tool-limited | 57 / 27 | 基于当前可访问 Wiki 与已注册工具；不是生产放行结论 |
| 用户输入模式 | 1 preflight / 9 prompt-only / 74 未分类 draft | preflight 当前仅用于 `build-experience-metrics` |
| Profile release gate | **未通过** | `0/84` 达到生产 approved；review roster 未完成；provenance v2 缺失 |

11 个 Legacy 命令为：`$memory.search`、`$memory.personal`、`$memory.project`、`$memory.team`、`$brief.create`、`$note.save`、`$research.request`、`$data.query`、`$risk.review`、`$memory.propose`、`$system.info`。

### 4.2 84 个内置 Skill 全量清单

图例：**粗体** = 当前 10 个 Planner eligible Pilot；◆ = 已启用 Skill Input Preflight。

#### 设计前（17）

- **`competitive-analysis`**、`design-advisor`、**`generate-interview-guide`**、`generate-persona`
- **`generate-research-plan`**、`industry-market-analysis`、`jd-app-journey-map`、**`jobs-to-be-done`**
- `journey-map`、`prd-design-brief`、**`prd-feasibility`**、**`query-experiment-conclusions`**
- `research-screenshot-analyzer`、`search`、`structure-interview-transcript`、`synthesize-qualitative-insights`、`welcome`

#### 设计中（26）

- `design-md-to-relay`、`field-design-build`、`filter-tabs-design-skill`
- **`generate-survey`**、**`generate-usability-test`**、`livestream-cover-generator`
- `mega-subsidy-design-skill`、`navbar-generation`、`nested-structure-generation-skill`
- `platform-transaction-address`、`platform-transaction-cart`、`platform-transaction-cashier`
- `platform-transaction-settlement`、`platform-transaction-shared-foundation`、`platform-transaction-success-page`
- `plugin-api-key-ai`、`popup-design-skill`、`prototype-generation`、`qiangdan-hall-generator`
- `relay-component-set-architect`、`relay-component-variant-generator`、`relay-demo-from-md`
- `relay-theme-replace`、`relay-to-component-pipeline`、`senior-adaptation-tool`、`zero-banner-update`

#### 设计后（41）

- `accessibility-review`、`ai-decision-lab`、`analyze-satisfaction`、**`build-experience-metrics`◆**
- `case-register`、`code-open-feedback`、`coding-repo-sync`、`component-properties-admission`
- `conversion-funnel-analysis`、`design-abtest-analysis`、`design-cleanup`、`design-md-to-portal`
- `design-md-to-spec-page`、`design-reasoning-input`、`design-review`、`dwiki`
- `feature-adoption-analysis`、`feedback-insight`、`git-workflow`、`instance-manage`
- `instance-suggest`、**`issue-prioritization`**、`jd-field-ppt-skill`、`joyspace-docs`
- `knowledge-preview`、`knowledge-update`、`leader-report`、`lieflat-charts`
- `motion-handoff-export`、`prelaunch-usability-review`、`register-experiment`
- `relay-spec-longpage`、`relay-to-design-md`、`ruler-annotation`、`run-heuristic-evaluation`
- `usability-review`、`zero-id-to-md`、`zero-md-to-page`、`zero-spec-to-md`
- `zero-superbrand-banner-audit`、`zero-to-joyspace`

### 4.3 当前 27 个 tool-limited Skill

这些 Skill 已被目录发现，但其声明的 Bash/Read/Write/Zero MCP 等宿主能力没有映射到当前 AgentMesh 内置 Tool Gateway，因此不得被描述为可执行能力：

`case-register`、`design-advisor`、`design-md-to-portal`、`design-md-to-relay`、`design-md-to-spec-page`、`design-reasoning-input`、`design-review`、`git-workflow`、`instance-manage`、`instance-suggest`、`knowledge-preview`、`knowledge-update`、`leader-report`、`livestream-cover-generator`、`mega-subsidy-design-skill`、`navbar-generation`、`nested-structure-generation-skill`、`popup-design-skill`、`relay-to-component-pipeline`、`relay-to-design-md`、`search`、`welcome`、`zero-banner-update`、`zero-id-to-md`、`zero-md-to-page`、`zero-spec-to-md`、`zero-to-joyspace`。

<span id="technical-characteristics"></span>
## 5. 技术特点

### 5.1 服务端是唯一业务权威

React 只提交用户意图、版本和选择；权限、状态转换、候选资格、审批要求、Skill/Tool 身份、Artifact 完整性都由 FastAPI 与 SQLite 决定。前端不能通过隐藏字段或本地状态绕过服务端约束。

### 5.2 持久化优先，而不是依赖浏览器或进程内状态

- AgentRun、SkillPlan、Node、Artifact、Review、Event、dispatch receipt 均持久化。
- `client_turn_id + canonical payload hash` 用于幂等与冲突拒绝。
- 关键更新使用乐观版本/CAS；图关系和审核等复合写入使用 SQLite 事务。
- 刷新、GET 与 SSE 重连只读取状态，不触发新的 Provider 工作。
- 进程内 `asyncio.Task` 只是执行机制；可恢复事实以 SQLite 为准。

### 5.3 多层人审，且每个闸门职责不同

```text
Plan Approval   → 同意“执行哪些 Skill 节点”
Tool Approval   → 同意“某次受控工具调用”
Task Review     → 判断“交付物是否满足任务”
Memory Review   → 判断“内容能否成为团队知识”
Inbox           → 上述待办的用户工作投影，不是事实源本身
```

这避免了“一次确认永久放权”或“任务完成自动发布团队知识”。

### 5.4 证据、来源与不可变身份贯穿执行链

- Source 记录来源类型和 reference；Runtime 进一步绑定 Run、Skill、用户和项目。
- Artifact 带内容哈希、验证状态、Requirement/Plan/Attempt/Step 血缘。
- Candidate Snapshot 冻结 Planner 实际看到的能力卡，后续修复与恢复不能换一批候选。
- Memory Use Receipt 只在内容真正跨过最终模型上下文边界时写入，不把搜索命中误算成使用。
- Provider/模型 trace 区分 requested 与 actual，并记录 fallback 原因。

### 5.5 外部内容默认不可信

Tool 参数会检查凭证型内容；外部输出经过大小、编码和提示词注入检查。可疑内容会被隔离并进入人工审核；高风险或非只读调用不能仅靠模型决定。DeepSearch v1 只接受真实、健康的 `web_research` 作为报告 Evidence，其他工具路径失败关闭。

### 5.6 适配器边界清晰

- 模型：OpenAI 兼容 Chat Completions，支持 JSON Schema / JSON Object 两类结构化输出模式与单次 fallback。
- Web：Tavily、可选 Firecrawl、命令型 provider、O2。
- Data：HTTP Data API → O2 → `local_metrics` fallback。
- Tool：5 个内置工具 `memory_search`、`document_search`、`data_query`、`web_research`、`risk_review`，另有 MCP 扩展边界。
- 文档：Parser Protocol + 组合解析器；外部解析器仅为扩展点。

### 5.7 安全默认值与可控启用

编排、DeepSearch、任务写入、自动记忆上下文、向量检索、协作市场和后台 Worker 均采用默认关闭或只读策略。错误配置通常回落到 `off/read_only`，而不是扩大权限。

<span id="architecture"></span>
## 6. 项目架构

### 6.1 总体架构

```text
┌────────────────────────────────────────────────────────────────────┐
│ React 18 SPA · TypeScript · Vite · Tailwind · TanStack Query       │
│ Digital Self / Workspace / Tasks / Insights / Knowledge /          │
│ Collaboration / Market / Digital Human / Admin                     │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ same-origin REST + SSE
┌──────────────────────────────▼─────────────────────────────────────┐
│ FastAPI 接入层                                                      │
│ Auth / Request limits / 23 Router modules / OpenAPI                │
└──────────────┬──────────────────────────────┬──────────────────────┘
               │                              │
┌──────────────▼────────────────┐  ┌──────────▼──────────────────────┐
│ Agent 与编排控制面             │  │ 业务治理域                       │
│ PersonalAgent                 │  │ Task Management / Operations    │
│ AgentRuntimeService           │  │ Task Review                     │
│ Skill Search / Planner / DAG  │  │ Memory Governance / Context     │
│ Input Preflight / DeepSearch  │  │ Blackboard / Market / Inbox     │
│ Tool Gateway / MCP            │  │ Documents / Retrieval / Risk    │
└──────────────┬────────────────┘  └──────────┬──────────────────────┘
               └──────────────────┬───────────┘
                                  │
┌─────────────────────────────────▼──────────────────────────────────┐
│ SQLiteStore                                                        │
│ JSON aggregate records + 专用 Run/Plan/Artifact/Review 表          │
│ FTS5 + 可选向量侧索引 + task_operations_projection + WAL          │
└─────────────────────────────────┬──────────────────────────────────┘
                                  │
┌─────────────────────────────────▼──────────────────────────────────┐
│ 可选外部边界：LLM / Tavily / Firecrawl / O2 CLI / Data API /      │
│ OAuth / MCP / Tesseract                                            │
└────────────────────────────────────────────────────────────────────┘
```

### 6.2 组件职责

| 层 | 核心模块 | 职责 |
| --- | --- | --- |
| Web UI | `agentmesh-demo/src/` | 登录态、页面编排、Server State 缓存、计划/输入/任务/知识/市场交互 |
| HTTP API | `agentmesh/routes/` | 鉴权、请求校验、权限检查、错误码和服务委派；当前 OpenAPI 为 147 paths / 169 operations |
| 个人 Agent | `agentmesh/agents.py` | 私有对话、Legacy Skill、BBS 求助、代答、市场信号与降级路径 |
| Agent Runtime | `agentmesh/agent_runtime/` | 模型选择、Run 生命周期、SDK Session、结构化输出、dispatch/recovery |
| Skill Runtime | `agentmesh/skill_runtime/` | 发现、Profile、检索、候选快照、规划、输入预检、DAG 执行、综合输出 |
| DeepSearch | `agentmesh/deepsearch/` | Requirement、澄清、问题图、预算、证据、评审、报告和恢复 |
| Task Domain | `task_management/`、`task_operations/`、`task_review/` | 项目任务、依赖图、运营读模型、交付审核 |
| Memory Domain | `memory_context/`、`memory_governance/` | 上下文选择、Use Receipt、候选审核、修订和生命周期 |
| Integration | `tool_runtime/`、`web_research.py`、`o2.py`、`datasources.py` | 统一工具策略、Provider 适配与 provenance |
| Persistence | `store.py` | 单库事务、WAL、JSON 聚合、专用控制表、FTS、只读历史连接 |

### 6.3 持久化设计

当前不是“纯 KV”，也不是完全关系化：

- 领域对象主体仍以 `records(collection, id, payload, created_order)` JSON 聚合保存，适合原型快速演进。
- AgentRun、SkillPlan/Node/Result、Artifact、Task/Memory Review、DeepSearch Requirement、dispatch receipt 等高一致性对象使用专用表。
- `records_fts` 提供 FTS5 检索；`records_vec`/`vector_states` 为可选向量路径。
- `task_operations_projection` 是可重建读模型，由触发器和启动重建维护，不拥有 Task 事实。
- SQLite 必须启用 WAL；当前设计只承诺单应用进程、单 Writer。
- ADR 0002 的全面关系化迁移仍是计划，尚未完成。

### 6.4 运行与部署形态

开发时由 Vite `5178` 代理 `/api` 到 FastAPI `8010`；构建后由 FastAPI 同源托管 `agentmesh-demo/dist`。根目录 `app.html` 仅作为 `/app.html` 与 `/legacy/app.html` 的临时回滚入口。主应用没有独立 Docker/Kubernetes 部署定义；仓库中的 Dockerfile 属于 `2C-DesignWiki` 子项目，不应视为 AgentMesh 发布方案。

<span id="core-flows"></span>
## 7. 核心业务流程

### 7.1 普通对话与显式 Skill

```text
登录用户提交消息
  → 服务端以 client_turn_id 领取幂等回执
  → 校验 Thread 所有权
  → 若 Agent Runtime v2 启用：
       自然语言 → SDK 对话
       $内置Skill → 单 Skill Run
  → 否则：Legacy $命令 / 意图分类 / 本地降级
  → Tool Grant + 参数/输出 guardrail
  → 保存私有用户消息、助手消息、Source、Trace、Audit
  → 刷新后由服务端 Thread 恢复
```

普通对话默认私有。明确工作流可创建 Task、Blackboard 请求、Inbox 项和短期个人记忆；未配置模型时返回可解释的本地 fallback，而不是伪装成真实模型结果。

### 7.2 Standard 多 Skill 编排与输入预检

```text
POST /api/agent/runs（planning_mode=standard）
  → 冻结 Run 身份、planning/execution contract
  → 解析意图与可选 Task/Scenario
  → 检索可见且可信的 Skill
  → 冻结最多 12 张 Candidate Snapshot 能力卡
  → Planner 生成最多 6 节点、深度 4、并发 3 的 DAG
  → 编译各节点 user-input contract
       ├─ 信息不足：Run → waiting_input
       │    → 用户填文本/上传 TXT、MD、CSV
       │    → 校验、哈希、冻结 node-scoped bindings
       └─ 信息完整：继续
  → 必要时 Plan Approval
  → 每个节点启动前重验 Skill/Profile/Tool/权限/资源
  → Tool Approval 与 Plan Approval 独立
  → 保存 Node Result、Artifact、Source、Usage
  → 综合输出 → completed / partial / failed
```

当前 `build-experience-metrics` 是首个 preflight Skill；另外 9 个 Pilot Skill 明确为 `prompt_only`，74 个 draft Profile 尚未分类为生产输入合同。

### 7.3 DeepSearch v1

```text
用户显式选择 planning_mode=deepsearch
  → 检查 DeepSearch 开关、execute 模式、Runtime、模型
  → 创建 orchestration_version=v1 的 Run
  → Requirement Refiner
       ├─ 有阻塞歧义：waiting_clarification（24h）
       └─ 完整：构建 ProblemGraph
  → Skill 检索 + 冻结 Plan/Snapshot
  → 用户审批 Plan
  → 仅真实且健康的 web_research 进入证据路径
  → 预算预留/结算 + Tool invocation identity
  → 封存 Evidence Artifact 与来源
  → 事实覆盖检查 + 报告评审
  → 生成 Markdown/HTML 可读报告
  → 持久化终态与恢复信息
```

DeepSearch 不根据提示词自动猜测开启，也不会回退到已退役 Research Runtime。当前发布条件还要求真实 Provider smoke 通过。

### 7.4 项目任务、交付审核与知识沉淀

```text
创建 Project Task（独立 delivery_stage）
  → 设置负责人、优先级、父任务、依赖任务
  → 未完成依赖阻止 start 与新 Task-linked AgentRun
  → 人工执行或创建绑定 task_id 的 AgentRun
  → Run 产出 sealed Artifacts
  → Run Owner 提交 Task Review
  → 服务端冻结 Artifact ID + hash，并选择 Reviewer
  → Reviewer 决策：
       accepted          → Task delivery_stage=done
       changes_requested → 回到 in_progress
       rejected          → 回到 in_progress
  → accepted 后可显式捕获：
       Personal Memory（私有）
       或 Team Candidate（待 Memory Review）
  → Memory Review accepted 后才成为 Team Knowledge
```

Task 状态、协作阶段和交付阶段是三条不同轴；Run 完成不自动完成 Task，Task Review 也不自动发布团队知识。

### 7.5 记忆检索与可审计复用

```text
AgentRun 需要上下文
  → Scope / Layer / 绑定 / 生命周期 / 权限过滤
  → 凭证与提示词注入隔离
  → FTS（可选 Vector）排序与去重
  → 对完整渲染载荷做预算
  → 预留稳定 citation label
  → 最终交给模型时才写 MemoryUseReceiptV1
  → Run 详情与 Memory lineage 可回看使用事实
```

`AGENTMESH_MEMORY_CONTEXT=off|observe|inject` 默认 `off`。`observe` 只测量不注入、不写使用回执；显式 `memory_search` 在实际安全输出交给模型后才记账。

### 7.6 协作市场与“只出答案”

```text
用户选择参与市场
  → Publisher 从个人任务/记忆生成抽象协作信号
  → Scout 扫描其他人的“需要”并匹配能力
  → Helper 对 Needer 建立可撤销 consent
  → Helper 的 PersonalAgent 仅在 Helper 的个人记忆中检索
       ├─ 有 standing consent 且非高敏：自动代答
       └─ 无 consent / 高敏：进入目标用户 Inbox 确认
  → 只回传抽象答案与引用标题
  → 请求方采纳
  → 记录不可兑换贡献点 + derived_from 血缘边
```

这里的“只出答案”是协作与交互模式，不是隐私安全保证；LLM 生成文本仍可能语义性泄露来源事实。当前代码已有参与、确认、拒绝、采纳 API 和 UI，但市场总开关默认关闭。

<span id="domain-model"></span>
## 8. 核心领域对象与状态边界

| 对象 | 是什么 | 不是什么 |
| --- | --- | --- |
| `ChatThread` | 用户与项目范围内的对话或 task-context 容器 | 不等于项目 Task |
| `Task` | 持久项目工作项；含执行兼容状态、协作阶段和交付元数据 | 不等于单次 Agent 执行 |
| `AgentRun` | 一次不可变身份的 Agent 执行尝试，可绑定 Task | 完成后不会直接把 Task 标为 done |
| `SkillPlan` | 服务端持久化的有界 DAG 与候选/合同快照 | 不授予 Tool 权限 |
| `Artifact` | Run 产物或证据，带哈希、验证状态和 lineage | 不自动成为 Memory |
| `TaskReviewV1` | 对一组冻结交付物是否满足 Task 的判断 | 不判断能否进入团队知识 |
| `MemoryReviewV1` | Team Candidate 是否可成为 Team Knowledge 的判断 | 不替代 Task Review |
| `MemoryItem` / `UserMemoryItem` | 团队治理记忆 / 用户分层私有记忆 | Scope 与 Layer 不能混为一谈 |
| `MemoryUseReceiptV1` | 精确 Memory 版本真正进入模型上下文的不可变事实 | 不是普通检索结果日志 |
| `InboxItem` | 面向人的待处理投影 | 不是审批/Review 的事实源 |
| `AuditEvent` | 跨域行为与决策记录 | 不存放敏感原始 Provider 载荷 |

### 关键状态分离

- **Task execution status**：兼容旧执行语义。
- **Task collaboration stage**：Blackboard 协作阶段。
- **Task delivery stage**：`backlog → planned → in_progress → review → done/cancelled`。
- **AgentRun status**：包括 planning、waiting_input、waiting_clarification、waiting_plan_approval、waiting_approval、running 与终态。
- **Memory lifecycle**：proposed、accepted、disputed、deprecated、expired、archived；修订不原地覆盖历史版本。

<span id="frontend-api"></span>
## 9. 前端、API 与数据呈现

### 9.1 当前 React 页面

| 路由 | 页面职责 |
| --- | --- |
| `/digital-self` | 当前用户的数字员工身份、活动与记忆概览 |
| `/workspace` | 对话、Skill、输入预检、计划、执行、来源、文档与报告 |
| `/tasks` | 项目任务、交付状态、依赖、里程碑、日历、Agent 队列、Review |
| `/insights` | 项目任务/活动/记忆/审计读模型 |
| `/knowledge` | 个人记忆、团队候选、治理历史、复用与 Inbox |
| `/collaboration` | Blackboard 任务、回复、锁与交接 |
| `/market` | 协作市场参与、关系图、信号、代答、确认与采纳 |
| `/digital-human` | Agent 配置、能力与知识权限展示 |
| `/admin` | 用户、Agent、Provider、策略、诊断与审计；按 capability 展示 |

前端采用路由级懒加载、TanStack Query 管理 Server State、OpenAPI 生成 TypeScript 类型。构建后 FastAPI 同源托管；开发态由 Vite 代理 API。

### 9.2 数据真实性标记

部分参考 UI 仍混合真实服务端数据与展示 Mock：

- `T数据`：当前用户权限范围内由 FastAPI/SQLite 返回的数据。
- `M数据`：参考 Mock、固定展示常量或明确 demo seed。

Mock 只能补足展示，不应被当成权限、状态或 mutation 成功证据。AI 工作台的核心消息、上传、搜索、Skill、Trace 和记忆检索以服务端数据为准。

### 9.3 API 规模

当前 OpenAPI 动态导出结果：

- **147** 个路径；**169** 个操作；
- 方法分布：GET 78、POST 70、PATCH 15、DELETE 4、PUT 2；
- 较大的能力域包括 Agents 19、Blackboard 18、Memory 17、Agent Runs 16、Users 12、Skills 11。

这些数字表示当前代码暴露面，不等于每个接口在默认配置下都可执行。

### 9.4 已确认的前端托管缺口

React Router 和侧边栏已经包含 `/market`，但 `agentmesh/app.py` 的 SPA deep-link 白名单尚未注册 `/market`。本地 FastAPI smoke 结果为：`/`、`/workspace`、`/tasks`、`/digital-human` 返回 200，而直接访问 `/market` 返回 404。应用内导航通常可工作，但刷新或直接打开 `/market` 会失败，应在下一次修复中补齐并加入 `test_frontend_routes.py`。

<span id="deployment"></span>
## 10. 部署与配置边界

### 10.1 最小运行方式

```bash
/opt/homebrew/bin/python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
npm --prefix agentmesh-demo install
npm --prefix agentmesh-demo run api:types
npm --prefix agentmesh-demo run build
.venv/bin/uvicorn agentmesh.app:app --reload --port 8010
```

开发前端可另启：

```bash
npm --prefix agentmesh-demo run dev -- --port 5178 --strictPort
```

### 10.2 关键功能开关

| 配置 | 默认 | 含义 |
| --- | --- | --- |
| `AGENTMESH_AGENT_RUNTIME` | `legacy` | 设为 `v2` 才启用 OpenAI Agents SDK Runtime；注意这与已退役的 `research-v2` 无关 |
| `AGENTMESH_SKILL_ORCHESTRATION` | `off` | `off / preview / execute` |
| `AGENTMESH_TASK_SCENARIO_ROUTING` | `false` | Task/Scenario 路由提示 |
| `AGENTMESH_DEEPSEARCH_ENABLED` | `false` | DeepSearch 创建入口 |
| `AGENTMESH_TASK_MANAGEMENT` | `read_only` | Task Center 写入开关 |
| `AGENTMESH_MEMORY_CONTEXT` | `off` | `off / observe / inject` |
| `AGENTMESH_EMBEDDING_ENABLED` | `false` | 可选向量检索；FTS5 始终为基线 |
| `AGENTMESH_MARKET_ENABLED` | `false` | 协作市场总开关 |
| `AGENTMESH_DEMO_MODE` | 关闭 | 仅本地演示时创建固定账号与数据 |
| 各后台 Worker | 关闭 | 自动 BBS、研究调度、每日记忆等需显式启用 |

### 10.3 外部依赖

真实运行可选接入 LLM、Embedding、Tavily、Firecrawl、O2 CLI、HTTP Data API、MCP、OAuth、Tesseract。API Key 仅由服务端环境读取；报告没有读取、复制或输出 `.env` 内容。若 Provider 未配置，系统应显示不可用或明确 fallback，而不是把 fixture 结果冒充真实数据。

<span id="limitations"></span>
## 11. 当前限制与风险

### 11.1 发布阻塞项

1. **Universal Skill 检索边界门禁未通过。** 当前校准的 boundary rejection 为 33.3%，目标为 100%；英文分组为 4/5。
2. **生产 Profile 信任链未完成。** 84 个 Profile 中 0 个达到 production approved；review roster 未完成，`profile_provenance_v2` 缺失。
3. **真实 Provider 尚未验收。** 本报告未运行 embedding、O2、Web、Data、LLM 五类真实 smoke。
4. **浏览器 E2E 未实际执行。** 本机缺少 Playwright Chromium；测试在 launch 阶段被环境阻塞。
5. **`/market` 生产托管 deep link 缺失。** 应补路由与回归测试。

### 11.2 架构边界

- 单 Workspace、单应用进程、单 SQLite；不支持多租户、水平扩展、高可用或 SQLite 多进程写入。
- 仅适合可信内网；Cookie `Secure` 依赖部署配置，仓库没有公网反向代理、TLS、WAF 或容器发布方案。
- FTS5 是默认检索；向量检索可选，PostgreSQL/pgvector 仍是未来决策，不是当前架构。
- 市场中的“只出答案”不能被宣传为防语义泄露的隐私技术。
- 部分参考页面保留 M 数据，展示完整度不等于后端业务完整度。
- `research-v2` 只读兼容表和模块仍在仓库中；它们不是可恢复的执行 Runtime。

### 11.3 尚未纳入本仓库

- designOS 的会议双通道采集与说话人归属；
- PostgreSQL / EmployeeTwin 融合；
- 公网安全加固、HA、横向调度、独立 Worker/队列；
- 贡献积分兑换及反作弊体系；
- 对“只出答案”的强隐私/防推断保证。

### 11.4 文档时效差异

根 `CONTEXT.md` 标注的现状时间为 2026-08-26；当前提交为 2026-09-09。其关于“代答确认/采纳尚无公共 API/UI”的描述已被当前 `routes/market.py` 与 `ExchangeTabs.tsx` 超越。本报告在冲突处以当前代码和更新后的 ADR 为准，并保留此差异作为文档维护提醒。

<span id="verification"></span>
## 12. 验证结果

### 12.1 已执行检查

| 检查 | 结果 | 关键数据 |
| --- | --- | --- |
| `.venv/bin/python -m pytest` | **通过** | 1873 passed，5 个 PyMuPDF/SWIG deprecation warnings，耗时 310.08s |
| `.venv/bin/ruff check .` | **通过** | `All checks passed!` |
| `scripts/skill_catalog_report.py` | **结构检查通过；发布资格否** | 84/84、无重复、0 error/0 warning；release gate false |
| `eval/run_skill_retrieval_eval.py` | **通过** | Top-3 recall 100%；p95 43.697ms；不可用/禁用/未授权召回均 0% |
| `eval/run_universal_skill_retrieval_eval.py` | **未通过** | FTS Top-3 96.7%、Recall@5 98.3%、p95 135.682ms，但 boundary rejection 33.3%；fake-vector 同样失败 |
| Universal 84-Profile smoke | **通过但不可作发布 holdout** | 252 cases；Top-1/Top-3/Recall@5 均 100%；脚本明确标注 dataset contaminated |
| `scripts/sync_wiki_skills.py --check` | **通过** | 84 total、10 preserved、74 generated |
| Skill Input Preflight smoke | **通过** | 2 个冻结 binding、模型被调用、第二个同 Thread Run 被阻止、终态 completed |
| Project Operations benchmark | **通过** | 10k Tasks / 50k Task-Audit / 10k Memory / 1k accepted Team Knowledge；全部 p95 < 500ms |
| `npm ... test -- --run` | **通过** | 33 files、198 tests；有 React Router SSR `useLayoutEffect` warning |
| `npm ... run api:types` | **通过** | OpenAPI 类型成功生成，生成文件无 diff |
| `npm ... run build` | **通过** | 1793 modules；最大 JS 320,326 bytes，小于 500,000 bytes 预算 |
| `npm ... run test:e2e` | **环境阻塞** | 缺少 Playwright Chromium；60 个 browser launch error、15 未运行、1 通过；未观察到应用断言结果 |
| FastAPI SPA deep-link smoke | **部分通过** | `/`、`/workspace`、`/tasks`、`/digital-human` 为 200；`/market` 为 404 |
| 报告自身校验 | **通过** | HTML doctype/解析/内部锚点/离线资源、Markdown fence、84 Skill 覆盖与文件边界均已检查 |

Project Operations 本次 p95：Task list 290.663ms、Task detail 383.671ms、Operations snapshot 262.512ms、Task options 158.121ms、Memory FTS 28.348ms。

### 12.2 未执行检查

- `scripts/provider_smoke.py --embedding --o2 --web --data --llm`：需要已授权的真实账号、Key 与 CLI；本报告没有使用真实外部服务。
- 真实企业 OAuth 登录、O2 登录态、Tavily/Firecrawl、Data API、Embedding 与生产模型端到端。
- Playwright 浏览器 E2E：需要先安装项目锁定版本的 Chromium。
- 生产部署、负载/长稳、故障注入、备份恢复与 rollback rehearsal。

### 12.3 如何理解这些结果

`pytest` 全绿证明大量领域状态机和安全边界在隔离 fixture 中成立；它不能替代真实 Provider、浏览器、网络和生产部署验证。反过来，本次 Playwright 失败是浏览器二进制缺失造成的环境阻塞，不应误报为 60 个产品逻辑失败。Universal 检索校准则是实际门禁失败，必须按失败处理。

<span id="conclusion"></span>
## 13. 综合结论与近期优先级

### 13.1 综合结论

AgentMesh 已经从“聊天 + 几个工具”的原型发展为一个结构完整的内部 Agent 工作平台：

- 产品上具备个人数字员工、工作台、任务中心、知识治理、协作网络和协作市场；
- 技术上具备服务端权威状态机、有界 Skill DAG、输入预检、双重审批、证据 Artifact、记忆使用回执、幂等、审计和恢复；
- 数据上坚持个人、项目、团队边界以及 Task Review / Memory Review 分离；
- 集成上已经形成 LLM、Web、Data、O2、MCP 和文档解析的适配器边界。

因此，**当前版本足以支撑功能演示、内部评审和受控试点**。但由于生产信任链和真实环境验收尚未完成，**不应把当前分支描述为已生产就绪，也不应面向公网部署**。

### 13.2 建议的近期优先级

1. **先修发布门禁，不扩功能面**：修复 Universal boundary rejection 与英文 miss，重新跑独立 holdout。
2. **完成 Profile 信任链**：84 个 Profile 的独立审批、review roster、provenance v2 和 production eligibility。
3. **补齐真实验证**：安装锁定版 Chromium 跑完整 E2E；在授权宿主机运行五类真实 Provider smoke。
4. **修复明确的小缺口**：为 FastAPI 增加 `/market` SPA deep link，并纳入前端路由回归。
5. **在试点反馈前保持架构边界**：继续使用单进程 SQLite 和默认关闭策略，不提前引入多租户、队列或 PostgreSQL 迁移。

<span id="evidence-index"></span>
## 附录 A：证据索引

| 主题 | 主要文件 |
| --- | --- |
| 当前术语、实现/缺失边界 | `CONTEXT.md` |
| 运行、配置与能力概述 | `README.md`、`.env.example` |
| 依赖和版本 | `pyproject.toml`、`agentmesh-demo/package.json` |
| 应用入口与前端托管 | `agentmesh/app.py`、`agentmesh-demo/src/App.tsx` |
| API 合同 | `agentmesh/routes/`、`agentmesh-demo/openapi.json` |
| 核心领域模型 | `agentmesh/models.py` |
| 持久化与事务 | `agentmesh/store.py` |
| 个人 Agent 与传统流程 | `agentmesh/agents.py` |
| Agent Runtime | `agentmesh/agent_runtime/service.py` |
| Skill 目录与 Profile | `agentmesh/skill_runtime/service.py`、`profiles.py`、`agentmesh/builtin_skills/` |
| Universal 检索与规划 | `recommendation.py`、`planner.py`、`universal_plan.py` |
| 输入预检 | `input_contracts.py`、`input_preflight.py`、`input_adapters.py` |
| DAG 与工具执行 | `executor.py`、`finalization.py`、`tool_runtime/` |
| DeepSearch | `agentmesh/deepsearch/`、`routes/deepsearch.py` |
| Task / Review / Operations | `task_management/`、`task_review/`、`task_operations/` |
| Memory 治理与复用 | `memory_governance/`、`memory_context/` |
| 协作市场 | `marketplace.py`、`routes/market.py`、`features/market/` |
| 文档与检索 | `documents.py`、`ingestion.py`、`retrieval/` |
| 外部集成 | `web_research.py`、`o2.py`、`datasources.py`、`llm.py` |
| 自动化质量门禁 | `.github/workflows/ci.yml`、`tests/`、`eval/`、`scripts/` |

<span id="adr-precedence"></span>
## 附录 B：ADR 生效关系

- ADR 0001：当前以 SQLite FTS 为主，不在 MVP 引入 pgvector。
- ADR 0002：全面关系化是未实施迁移计划；当前仍是 JSON 聚合 + 专用控制表的混合存储。
- ADR 0003：跨人“只出答案”是 MVP 核心，但不是隐私保证。
- ADR 0004：保留有界 DAG、双审批与 `off/preview/execute`；10 Skill 白名单限制被 ADR 0009 替代。
- ADR 0005、0006：Research Runtime 历史记录，已被 ADR 0007、0008 替代。
- ADR 0007：`research-v2` 执行面已退役，仅保留 Owner-scoped 历史读取。
- ADR 0008：`research-v3` 预览已退役；新深度研究走 v1 DeepSearch。
- ADR 0009：Universal Runtime Skill 检索、Candidate Snapshot 与版本化 Plan 合同。
- ADR 0010：单维护者 CI 合并例外不等于生产批准。
- ADR 0011：Task 交付状态、AgentRun 和协作状态分离。
- ADR 0012：Memory 身份、审核、修订和生命周期由 AgentMesh 自己治理。
- ADR 0013：Memory Use Receipt 在最终模型上下文边界写入。
- ADR 0014：项目运营是服务端 Task 图 + 可重建读模型，不是自动调度器。
- ADR 0015：Standard Skill 在执行前通过冻结的用户输入合同进行预检。

---

**报告维护建议**：后续每次形成发布候选时，重新记录分支/提交、运行 `skill_catalog_report`、两套检索评估、后端/前端/E2E、真实 Provider smoke，并同步修订 `CONTEXT.md` 中已经被代码超越的描述。
