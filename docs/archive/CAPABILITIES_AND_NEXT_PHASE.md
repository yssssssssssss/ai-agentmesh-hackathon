# AgentMesh 能力总结与下一阶段发展计划

> 文档定位：面向管理层与研发团队的双视角材料。第 1–2 部分（概述、价值与成熟度）偏向管理层视角，第 3–6 部分（能力清单、计划、风险）偏向研发执行视角。
> 编写日期：2026-06-26 ｜ 依据：`README.md`、`DEVELOPMENT_PLAN.md`、`TODO.md`、`TODO_NEXT_MVP.md`、`eval/results.json` 及 `agentmesh/` 源码现状。

---

## 1. 管理层概述（Executive Summary）

AgentMesh 是一个 **chat-first（以对话为主入口）的团队 Agent 协作平台**。它的核心承诺是：

> 用户用自然语言向"团队大脑"提问，由个人 Agent 与服务 Agent 在后台收集上下文、协作完成任务，并把有价值的成果沉淀为受治理的个人 / 项目 / 团队记忆——整个过程用户无需管理 Agent 的内部细节。

经过多轮迭代，项目已经从"可演示的静态原型"推进到 **"端到端可运行的 MVP"**：从用户发起一条对话，到任务路由、服务 Agent 协作、带来源引用的回答、活动审计、再到记忆沉淀，主链路已全部打通，并有 **220 个自动化测试** 与一套评测数据集（eval）覆盖核心流程。

当前最关键的判断是：**产品骨架与治理机制已基本成型，但与真实企业数据 / 工具的"最后一公里"尚未接通**。研究、数据查询等关键能力默认仍走 mock 或本地样例连接器，真实的 Oxygen-CLI 内部检索受限于凭证 / 初始化未完成验收。这意味着下一阶段的重点不应再是"堆功能、堆页面"，而应是 **把真实数据接通、把工程底座做扎实、让产品真正可被一线用户试用**。

一句话定位：**"骨架已立、治理已备，差在通真实血脉与可规模化的躯干。"**

---

## 2. 产品价值与成熟度快照

### 2.1 与同类产品的差异点

AgentMesh 刻意不做以下事情，这正是它的设计取舍：它不是通用知识库，不是自由放养的多 Agent 聊天室，也不是一个"审批 Agent 杂活"的控制台。它的差异化主张集中在三点：

1. **对话为主、黑板为辅**：用户只面对聊天界面；Agent 之间的协作发生在内部"黑板（Blackboard）"上，普通用户默认无需阅读。
2. **隐私默认、记忆受治理**：自然闲聊默认私有、不入库；只有显式 `$` skill 产生的高价值成果才可能被提升为记忆，且团队记忆必须有来源、有权限、可撤销。
3. **可审计、非自由放养**：每一次 Agent 行为都有 actor / source / scope / permission / status / timestamp，可被审计追溯。

### 2.2 成熟度分级

| 维度 | 成熟度 | 说明 |
|---|---|---|
| 产品骨架 / 主链路 | 🟢 已可运行 | chat → task → blackboard → evidence → 带引用回答 → 活动日志，端到端打通 |
| 记忆治理体系 | 🟢 已可运行 | 三层记忆（短/中/长期）+ 团队候选/接受治理流程 + 每日摘要自动化 |
| 权限与用户体系 | 🟢 MVP 完成 | 三类角色 RBAC、范围可见性、团队成员、策略覆盖；OAuth 为适配框架 |
| 风险审查 | 🟢 已可运行 | 策略驱动的确定性规则引擎（prompt 注入 / 高危工具 / 来源策略 / 审批） |
| 文档接入 | 🟢 MVP 完成 | txt/md/PDF/Word/PPT/图片 OCR 解析、检索、摘要入记忆 |
| 真实数据 / 工具接入 | 🟡 接口就绪、未验收 | Oxygen-CLI、Web、HTTP 数据源均为"接口边界已搭、真实返回阻塞" |
| 前端工程化 | 🔴 待升级 | 仍为 6300+ 行单文件 `app.html`，未迁移 React |
| 数据持久化 | 🟡 可用但需演进 | 单 `records` KV 表，关系型迁移已有 ADR 但未实施 |

---

## 3. 当前已实现能力清单（研发视角）

以下按能力域归纳，均为代码中已实现并有测试覆盖的部分。

### 3.1 对话与技能（Chat & Skills）

对话主流程采用 **"普通对话 + 显式 `$` skill 调用"** 模型，不再依赖隐式意图分类。自然语言输入默认走 `general_chat`，**不创建任务、不写黑板、不入记忆、默认私有**；只有显式输入 `$` 唤起技能菜单并选定技能时，才会创建 task / BBS / Inbox / Memory。已注册的技能包括：`$memory.search`、`$brief.create`、`$note.save`、`$research.request`、`$data.query`、`$risk.review`、`$memory.propose`、`$system.info`。接口会回传 `intent`、`source`（skill/chat）、`selected_workflow`、`llm_used` 等工作流信息，前端展示调用路径、来源与结果。

### 3.2 任务路由与黑板协作（Task Router & Blackboard）

任务状态机覆盖 created / running / waiting_external_agent / completed / failed（planning、synthesizing 暂为占位）。黑板支持 request / evidence / risk / digest / decision / correction / memory_candidate 七类帖子，证据帖回链到请求帖，支持分页、读标记、回复、结构化交接（handoff）、执行锁，以及"先审计后发布"的队列化自动发帖（manual drain + env 开关的后台 worker）。任务页可展示用户发起任务、个人 Agent 认领任务及任务上下游。

### 3.3 服务 Agent（Service Agents）

已实现 `research_agent`、`data_agent`、`risk_agent`。research_agent 默认优先内部 O2 + 外部 Web，两者都失败才回落 mock；data_agent 优先真实 connector，失败回落 `local_metrics` 样例连接器；risk_agent 是策略驱动的确定性审查器。外部获取统一通过 `AcquisitionRequest`/`AcquisitionResult` 接口边界，便于由外部项目替换实现。

### 3.4 记忆治理（Memory Governance）

`UserMemoryItem` 支持 short_term / mid_term / long_term 三层，短期记忆按 `user_id` 隔离、项目记忆按 `user_id + project_id` 隔离，含显式 `memory_date` 与记忆类型字段。提供每日短期汇总、短期→项目中期、中期→长期归档的 API；中期记忆用 LLM 提炼，长期归档生成项目总结与可召回索引。团队记忆有 private / project / team_candidate / team_accepted 四种范围与 draft / proposed / accepted / disputed / deprecated / expired 六种状态，且不会自动接受。空来源记忆会被拒绝生成。

### 3.5 检索（Retrieval）

关键词检索覆盖聊天消息、活动日志、黑板证据、记忆条目，支持权限感知过滤、项目/工作区过滤、来源感知结果展示。是否引入 pgvector 已有 ADR 评估结论（当前关键词检索够用）。

### 3.6 权限与用户体系（Auth & RBAC）

最小化本地 cookie-session 认证 + 用户生命周期管理：登录/登出、管理员创建/禁用用户、密码轮换/重置、组织/团队成员管理。三类角色（用户/组长/管理员）结合个人/项目/团队范围控制，并有持久化的角色-动作策略覆盖表。OAuth/SSO 已实现为适配器框架（状态检查、授权跳转、回调换 token、用户映射），真实企业 SSO 仍需配置输入。

### 3.7 外部接入边界（Integrations）

均以"接口边界 + 适配器"的形式实现，便于替换：Oxygen-CLI 内部能力提供方（状态 API、管理员工具同步、只读 research/data 适配，含 metasearch / o2-kb / oxygen-comment / bdp-copilot 命令契约）；Web 研究（opencli / agent-browser / mock）；只读 HTTP 数据源连接器；文档解析连接器（PDF/Word/PPT/图片 OCR）。外部内容被视为不可信输入，prompt 注入文本会被留痕、标记 needs_review、转 Inbox 并排除出 LLM 合成。

### 3.8 LLM 与工程底座

OpenAI 兼容的 LLM 合成路径，支持多模型注册与服务端密钥管理、UI 切换；chat 用更短超时保证响应性，超时则回落确定性本地回答并记录 `fallback_reason`。后端已拆为 FastAPI Router 结构，含 ruff lint、220 个 pytest 用例、以及 eval 评测数据集与指标脚本（引用覆盖率、可用答案时延、记忆接受率、用户纠正率）。

---

## 4. 关键缺口与"仍为 Mock/占位"的部分

诚实地列出当前与"真实可试用"之间的差距，这是下一阶段计划的依据：

1. **真实数据/工具未验收**：research 默认走 `MockAcquisitionAgent`（除非配置 `AGENTMESH_WEB_PROVIDER`）；data_agent 真实 connector 需企业 API URL / 鉴权 / 返回契约；`local_metrics` 只是样例。关于 Oxygen 的接入方式已于 2026-06-26 校正（见下方说明），不再是"等 token"的问题，而是命令契约对齐 + 在装有 CLI 的宿主机上验证。
2. **前端未工程化**：`app.html` 仍是 6300+ 行单文件，无法独立开发/测试新功能，难以多人协作。
3. **数据层待演进**：单 `records(collection, id, payload)` KV 表，过滤需加载解析 JSON、缺关系约束与索引；关系型迁移有 ADR（0002）但未实施。
4. **后台 worker 默认关闭**：自动发帖 drain、每日记忆摘要均为 env-gated 且默认关闭，未在真实运行环境长期验证。
5. **可观测性 / 运维**：尚无系统化的日志、指标、告警、健康度面板（仅有 `/api/health` 与 eval 离线指标）。

---

## 5. 下一阶段发展计划

### 5.1 阶段划分原则

下一阶段的主线是 **"从可运行 MVP → 真实可试用产品"**，刻意不再扩展页面数量，而是围绕三条主轴推进：**(A) 接通真实数据血脉、(B) 夯实工程底座、(C) 让一线用户真正用起来并形成反馈闭环**。

建议按约 6–8 周的"下一个冲刺周期"组织，分为三个阶段；每阶段都以可验收的产出收口。

### 阶段一（第 1–2 周）：接通真实数据"最后一公里" — 最高优先级

目标是让至少一条真实数据链路端到端跑通，并在 chat 回答中展示真实来源，彻底摆脱"全是 mock"的状态。

核心工作包括：完成 Oxygen `metasearch` 真实 query smoke test，确认其真实返回格式并接入 normalizer；为 research_agent 配置一个可用的真实 provider（Oxygen 或 Web 二选一先跑通）；为 data_agent 接入第一个真实只读 HTTP 数据源（补齐企业 API URL / 鉴权 / 返回契约）；补充 `o2-kb init`、Browser Bridge、bdp-copilot 的就绪性自检与管理员可见的诊断面板。

> **2026-06-26 校正（来自 DesignOS 已验证实现）**：Oxygen 接入此前误判为"阻塞于 `JD_METASEARCH_ACCESS_TOKEN`"。对照同组项目 DesignOS 已在真机跑通的连接器后确认：(1) 没有可注入的静态 token，鉴权由本机已登录的 CLI 自身承担；(2) 真实可用入口是独立子 CLI（`oxygen-metasearch`/`o2-kb`/`oxygen-comment`），不是 `o2 launch`；(3) metasearch 必须带 `--endpoint https://agentkits-a2a-gateway.jd.com/agents/sku-search`。`agentmesh/o2.py` 的命令契约已据此改造（优先直连子 CLI、移除 token-env、补 endpoint），220 个测试通过。剩余动作是**在装有并登录了这些 CLI 的宿主机上跑一次真实 smoke**，沙箱 CI 无法执行该步。详见 `O2_SMOKE_TEST.md`。

**验收标准**：用户在 chat 中发起一次真实调研/数据查询，能返回内部真实资料并在回答中展示真实来源；BBS 能清晰展示这次 Agent 协作链路；至少一条真实数据链路在 CI 或手动 smoke 中可复现。

### 阶段二（第 3–5 周）：工程底座升级 — 高优先级

目标是让产品具备多人协作开发与规模化运行的基础，消除单文件前端与单表存储两个主要技术债。

核心工作包括：将前端从 `app.html` 迁移到 Vite + React + TypeScript，按 Chat / BBS / Tasks / Memory / Agent / Users / Inbox 拆分组件，**保持现有 API 不大改，先迁移 UI**；按 ADR-0002 的两阶段方案，把 `records` KV 表迁移到关系型表（先并行读写、再 backfill 校验、再逐表切换读取），优先迁移 users / tasks / blackboard_posts / memory 等高频过滤实体；将 `PersonalAgent` 工作流编排逻辑抽到独立 workflow 模块（如编排持续增长）。

**验收标准**：前端不再是单文件，新功能可独立开发与测试；至少核心实体已切换到关系型表读取且与旧表数据一致；现有 220 个测试保持通过，新增组件级/迁移校验测试。

### 阶段三（第 6–8 周）：可试用闭环与可观测性 — 中高优先级

目标是让真实用户（设计师 / 组长 / 管理员）能在受控环境中试用，并让团队能观测系统健康与产品效果。

核心工作包括：开启并长期验证后台 worker（自动发帖 drain、每日记忆摘要）的稳定性与幂等性；完成真实 OAuth/SSO 一次贯通（provider 配置 + 用户/角色映射确认）；搭建基础可观测性（结构化日志、关键指标、错误告警、健康度面板）；把 eval 指标（引用覆盖率、可用答案时延、记忆接受率、用户纠正率）接入持续运行，形成产品质量看板；组织一轮 3–5 名真实用户的小范围试用并收集反馈。

**验收标准**：后台 worker 在真实环境连续运行无副作用；真实 SSO 登录可用；有一个能持续刷新的质量/健康看板；产出一份基于真实试用的反馈与改进清单。

### 5.2 优先级与依赖关系

阶段一是其余一切的前提——没有真实数据，产品价值无法验证，故优先级最高。阶段二（工程底座）与阶段一可部分并行：前端 React 迁移不依赖真实数据，可由前端同学并行启动；关系型迁移建议在阶段一稳定后再切读，避免同时改动数据契约与数据访问。阶段三依赖前两阶段的产出（真实数据 + 稳定底座）才有意义。

### 5.3 明确的"暂不做"清单（避免范围蔓延）

延续既有设计取舍，下一阶段**不做**：自由放养的 Agent 互聊、私有活动的自动共享、把黑板变成主要人机界面、团队记忆自动接受、复杂 ABAC 条件策略引擎、面向用户的"公共 Agent 搭建器"、以及 pgvector（关键词检索仍够用前不引入）。

---

## 6. 风险与建议

**最大风险已从"凭证阻塞"修正为"环境一致性"**。2026-06-26 对照 DesignOS 后确认，Oxygen 不需要申请静态 token，鉴权随本机已登录的 CLI 走。因此真正的前置条件是：**AgentMesh 必须运行在已安装并登录了 `oxygen-metasearch`/`o2-kb`/`oxygen-comment` 的宿主机上**（隔离沙箱/CI 没有这些 CLI，无法验证）。建议把"在目标宿主机上确认 CLI 已安装且 `oxygen-metasearch --json doctor` 通过"作为阶段一的硬性前置检查项。

**次要风险是技术债与新功能争夺资源**。单文件前端与单表存储已开始制约开发效率，但它们"还能用"，容易被一再推迟。建议把阶段二的工程升级作为**与功能开发并行的固定投入**，而不是等"有空再做"。

**建议的度量**：继续用 eval 数据集量化每次迭代的引用覆盖率、可用答案时延、记忆接受率、用户纠正率，让"是否更可用"有客观依据，避免凭感觉判断进展。

---

*本文档基于当前仓库静态分析与既有规划文档综合而成；阶段时间为基于现状的建议估算，实际排期需结合团队人力与外部凭证到位情况调整。*
