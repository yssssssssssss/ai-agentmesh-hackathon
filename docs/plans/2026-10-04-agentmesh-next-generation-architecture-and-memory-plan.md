# AgentMesh 架构升级与长期记忆方案

- 日期：2026-10-04
- 状态：历史提案；产品方向、优先级、阶段安排和技术决策已由 [完整优化方案](2026-10-04-agentmesh-complete-optimization-plan.md) 替代，本文件保留前序检查与研究记录
- 检查基线：`feature/workspace-memory-closed-loop`，HEAD `5a7e7c5`，包含工作区未提交的 Local Runner 改动
- 推荐目标：企业内网的个人分身与团队协作平台，先建立可靠的小团队闭环，再承载百人级使用
- 约束：继续使用 Python/FastAPI、React、OpenAI Agents SDK；保留自然聊天私有、显式 `$` 工作流、服务端授权和独立 Memory Review

## 1. 推荐结论

继续建设 AgentMesh。其值得投入的方向是：**能长期了解个人与项目、能执行并恢复任务、能把经验证的成果变成团队知识的 Agent 平台。**

现有项目已经有记忆治理、来源追踪、受控规划、任务审核和 Runner 的基础。主要差距是长期认知质量、服务器与 Runner 的上下文一致性、规模化持久层，以及能证明效果的评测。本方案围绕这四项升级，保留现有领域约束和有效实现。

推荐用 5 个可独立交付的阶段推进，约 40–58 个工程工作日，按一名熟悉仓库的工程师估计为 8–12 周；这是工作量估算，尚未包括真实 Provider 等待、组织审核及用户验收时间。第一项可用成果在阶段 1 交付，增强记忆在阶段 2 交付。

最小投入版本只实施阶段 1、2，约 13–20 个工作日，仍用 SQLite、单服务进程和现有检索。它能证明长期记忆是否改善真实任务，随后再投入生产基础设施。

本方案的关键假设是：用户愿意授权形成个人记忆，并提供可验证的工作材料。如果只有稀疏聊天或错误来源，增加向量库、图谱或后台反思无法弥补证据缺失。因此显式记忆操作、来源回查、未知时不猜和关闭自动学习必须始终可用。

## 2. 检查范围与证据边界

已检查项目入口与配置、CONTEXT、相关 ADR、已有升级计划、后端模块结构、认证与权限、Memory 治理/上下文/检索/摘要、Skill 规划与执行、工具/MCP/O2、文档导入、任务与审核、Runner/lease/spool、React 的 API/状态/记忆与执行界面、CI 和评测入口。

重点阅读实际运行链路与关键实现，并运行现有后端测试、Ruff、前端单元测试和生产构建。未发现本项目内的 `CLAUDE.md` 或 `.claude/rules/*.md`。此次是全项目架构检查和关键路径复核，不宣称对每一行源码完成逐行安全审计。

没有读取 `.env`、打印真实密钥、操作业务数据库、调用真实模型评测、登录企业系统或启动公网部署。历史审计报告只作线索；其中“没有 CI、默认凭据、没有前端测试”等旧结论不代表当前状态。

当前源码规模：`agentmesh/**/*.py` 共 172 个文件、79,511 行；React `src` 共 194 个文件。以下是维护热点，并非以文件长度直接判定功能错误：

| 文件 | 当前规模 | 影响 |
| --- | --- | --- |
| `agentmesh/store.py` | 18,770 行、479 个函数 | 持久化、领域事务、检索、多个执行代际和 Runner 集中，新增功能容易扩大变更面 |
| `agentmesh/agent_runtime/service.py` | 6,749 行、142 个函数 | 规划、执行、恢复、输出投影、记忆、远程调度高度交织 |
| `agentmesh/models.py` | 3,640 行 | 领域模型、API 契约、运行历史与兼容模型集中 |

工作区已有的 Runner 改动涉及 17 个 tracked 文件，另有新文件；本轮没有覆盖这些改动。升级实施前须冻结这一基线并保留作者的修改。

## 3. 当前优势与主要缺口

### 3.1 保留的基础

- `memory_governance/` 已实现候选、独立审核、修订、失效状态、来源和版本；Task Review 不会自动发布团队知识。
- `memory_context/` 已实现权限与生命周期过滤、安全隔离、预算、稳定引用标签和不可变使用回执。检索命中与实际上下文交付已经区分。
- `store.search()` 已有 FTS 与可选向量的 RRF 融合，不能把项目描述成完全没有混合检索。
- Skill DAG 已有候选快照、服务端校验、节点限制、执行前权限复核、预算及恢复路径。
- Run dispatch、Tool claim/outcome、任务操作和审核已有持久事实与幂等机制。
- Local Runner 已有设备授权、任务领取、续租、取消、事件、结果和本地 spool。
- React 已有 OpenAPI 类型、TanStack Query、用户会话切换处理、SSE 和构建预算；CI 已覆盖多类检查。

### 3.2 按影响排序的改进

| 优先级 | 发现 | 代码证据 | 推荐处理 |
| --- | --- | --- | --- |
| 高 | 缺少明确的结构化事实、现实有效时间与语义冲突机制 | `models.py:985` 的两类 Memory 以 title/summary 为主；现有 supersedes 是记录修订，不等于事实时间推理 | 给既有 Memory 增加类型化事实载荷、时间和证据，保留原治理权威 |
| 高 | 摘要无法代表完整长期事实 | `routes/memory.py:527` 的确定性摘要只展开最早 8 条；模型提示只展开最早 20 条、最多 6000 字；结果最多 2000 字 | 事实独立保存；摘要改为可重建导航，分批覆盖全部来源，支持回查 |
| 高 | Runner 的上下文与服务器执行能力有差异 | `routes/runners.py:278` 的直接执行取最近 10 条消息；`runner_executor.py:49` 拼接字符串历史，未使用 Session；审批中断直接报错 | 共用 ContextAssembler，结构化输入，版本化 Session/RunState 与远程审批 |
| 高 | 现有评测不能证明长期记忆效果 | `eval/metrics.py` 主要测工作流、来源存在和固定场景；没有长期事实/时间更新/遗忘/经验复用的独立质量集 | 建立记忆 holdout 和消融比较，单元测试与模型质量评测分开 |
| 高 | 云端规模受单 SQLite owner 限制 | `store.py:587`、writer flock、CONTEXT 单进程边界；RuntimeCapacity 是进程内状态 | 先形成聚合级 Repository，再迁移 PostgreSQL 和独立 Worker |
| 中 | 向量查询成本随可见向量数量线性增加 | `store.py:18542` 读取候选向量，在 Python 算余弦并排序 | 批量 SQL 加载，查询 embedding 复用；生产层使用数据库向量检索 |
| 中 | 权限/候选准备仍有全 collection 读取 | `memory_context/service.py:826`、`:917`，`store.search()` 候选逐条读取 | 将范围、生命周期与分页下推 SQL，保持原授权语义 |
| 中 | Token 预算不够贴合不同模型 | `compaction.py` 用 JSON 字符数除以 4、固定 60k 触发；Memory 以字符计预算 | 模型能力档案与 token 计数；上下文、输出和费用分别预算 |
| 中 | 可观测性偏向事件与审计，span 细节不足 | `trace_processor.py` 不记录 span；Runner 全局禁用 tracing | 本地脱敏 span，关联 run/node/tool/retrieval，补 usage、等待和耗时 |
| 中 | 文档解析执行依赖进程内队列和请求 bytes | `ingestion.py` 使用 ThreadPoolExecutor；解析请求作为内存参数提交 | 先持久化上传输入与作业，再执行；重启后从输入恢复 |
| 中 | 过程学习已存在，但证据较弱 | `skill_extractor.py` 按文本模式重复 3 次提出 LearnedSkill | 用成功/失败轨迹、交付反馈和环境验证提炼操作经验 |
| 中 | 部分协作能力仍是内部方法 | CONTEXT 的 delegated answer/consent/adoption 描述 | 形成授权请求、回答、采用和记忆提议的用户闭环 |
| 中 | 后端安装缺少完整依赖锁 | `pyproject.toml` 多数依赖无锁定，仓库没有 Python lockfile | 加 `uv.lock`，CI 使用锁定安装，SDK 升级独立验证 |

配置基线也需要如实理解：`.env.example` 当前是 Runtime `legacy`、Skill orchestration `off`、Task management `read_only`、Memory context `off`、Embedding `false`、execution location `server`。这些是既有默认和发布门禁，不是本轮检查出的 bug；功能存在不能等同于已经生产启用。

## 4. 对照当前官方实现后的技术判断

核验日期为 2026-10-04，只取官方文档和仓库实现，不依据宣传排名判断能力。

| 参考 | 已核实机制 | AgentMesh 采用的部分 |
| --- | --- | --- |
| [OpenAI Agents SDK Sessions](https://openai.github.io/openai-agents-python/sessions/) 与 [HITL](https://openai.github.io/openai-agents-python/human_in_the_loop/) | 会话存储与 RunState 审批恢复是不同职责 | 继续使用已安装 `openai-agents==0.21.1`，补齐 Runner 接入 |
| [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/checkpointers) | checkpoint 与已完成节点写入分开；恢复涉及重放 | 保留现有节点结果与 claim，补故障注入和明确恢复边界 |
| [Anthropic context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | 按需取上下文、压缩、结构化笔记 | 统一上下文组装，原始事件与派生摘要分开 |
| [Letta MemFS](https://docs.letta.com/concepts/memfs) | 常驻少量核心记忆、详情按需读取、后台整理 | 用户可编辑核心记忆与索引；后台只提出有证据的变更 |
| [Mem0 OSS 源码](https://github.com/mem0ai/mem0/blob/abb81c88e1f738a8117d8293530fbc31a5ef8fd9/mem0/memory/main.py) | 当前 add 路径抽取新事实、去重与关联 | 借鉴受限抽取；不把 Platform 时间推理当作 OSS 自带能力 |
| [Graphiti edge 源码](https://github.com/getzep/graphiti/blob/4f98b7ca45fef96925dc04134c42c526df73bb28/graphiti_core/edges.py) | episode 溯源、获知时间和事实有效区间 | 在关系数据库中保存时间事实和来源边 |

本轮同时阅读了 Mem0、Graphiti、Letta Code 与 LangGraph 的实现。借鉴结果是架构机制，未复制其产品架构。Mem0/Zep/Letta 均不作为必需运行时；AgentMesh 继续拥有 Memory 身份、权限、审核、版本与回执，符合 ADR 0012/0013。

不推荐现阶段迁移到第二套完整 Agent 框架：既有受控 DAG 的候选、授权、审批、版本兼容不会因换框架自动消失，迁移会同时增加运行历史转换和行为回归风险。只有现有 DAG 无法表达真实需求且替换实验证明收益时，才另立框架迁移决策。

## 5. 目标架构

继续保持一个仓库和模块化单体。生产增加 PostgreSQL 与一个后台 Worker 进程；用户侧继续运行现有 CLI/Local Runner。整个方案会涉及超过 8 个文件，并新增 2 项运行组件，必须分阶段交付。

```text
React / AgentMesh CLI
         |
         v
FastAPI Control Plane
  身份与授权 -> Task / Run / Review / Memory 命令
         |                 |
         |                 +-> ContextAssembler
         |                       当前任务 + 会话投影 + 授权记忆 + 证据
         v
PostgreSQL（权威状态、事件、dispatch、Memory、可重建索引）
         |
         +-> Worker：记忆抽取 / 索引 / 文档 / 调度恢复
         |
         +-> Server Executor 或已授权 Local Runner
                     |
                     v
              OpenAI Agents SDK
                     |
               Governed ToolGateway
                     |
             Native / O2 / MCP / 本地读工具

执行事件、结果、Artifact 与使用回执 -> Control Plane -> 持久化 -> SSE / UI
```

数据反馈是持久化事件，不允许模块互相递归调用来推进工作流。依赖方向固定为：API/Worker → Application Service → Repository/Tool Adapter。记忆内容不能改变授权、Skill trust 或工具配置。

### 5.1 模块职责与改造范围

| 模块 | 职责 | 建设方式 |
| --- | --- | --- |
| ContextAssembler | 统一任务状态、历史、核心记忆、检索内容与 token 预算 | 新增 `agentmesh/context/`；继续通过 MemoryContextService 做记忆授权和回执 |
| Memory ingestion | 有证据的事实抽取、去重、语义冲突与撤回传播 | 新增 `agentmesh/memory_ingestion/`；复用 governance/lifecycle |
| Memory context | 可见性、有效性、相关性、预算、引用和实际使用 | 加强现有 `memory_context/`，保持唯一 Memory 上下文出口 |
| Runtime | 规划、节点执行、恢复、输出投影 | 从 `agent_runtime/service.py` 按职责抽出 dispatch、node execution、projection；保留门面 |
| Persistence | 事务、聚合存取、查询与数据库迁移 | 新增 `agentmesh/persistence/`；先抽 Memory/Runtime/Task 聚合，避免复制 479 个方法的大接口 |
| Worker | 领取持久作业、续租、执行、提交结果 | 新增 `agentmesh/worker.py`，CLI 增加 `agentmesh worker` |
| Runner | 用户本机模型和能力执行 | 扩展既有 runner 文件，不新造第二个 Runner 产品 |

事务按业务原子边界组织。例如 Memory Review 激活新版本并废弃前驱必须保持同一事务；不能为了拆文件让调用者串联多个独立提交。已有 `SQLiteStore` 保留兼容门面，逐个聚合迁移。

## 6. 记忆系统：从分层摘要升级为可验证的长期认知

Scope、Layer 和认知类型各自解决不同问题。保留 private/project/team 与 short/mid/long；增加认知类型用于选择处理规则。

| 类型 | 保存内容 | 主要作用 |
| --- | --- | --- |
| 工作状态 | 当前目标、计划版本、已完成步骤、待补输入、审批与预算 | 随 Run/checkpoint 保存，可靠恢复任务 |
| 情景记忆 | 发生过的任务、决策、结果、反馈及来源事件 | 回忆经历、回查证据 |
| 语义记忆 | 用户偏好、项目事实、成员职责、状态与约束 | 跨会话保持一致，支持事实变化 |
| 过程记忆 | 已验证方法、前置条件、环境陷阱、验证办法 | 下次任务复用经验，减少重复错误 |

工作状态继续属于 Runtime，不因命名为“工作记忆”而再建一套任务状态机。文档和工具原始输出属于 Evidence；只有抽取后可追溯的声明才成为事实。用户说过、工具观察到和模型推测必须区分。

### 6.1 数据契约

给既有 Memory 增加可选类型化载荷，不重写原记录 ID：

- `MemoryFactV1`：subject、predicate、value、observed_at、valid_from/valid_to、时间精度、source event/span/hash、来源类别和 conflict group。
- `ProcedureMemoryV1`：适用目标、前置条件、环境与能力版本、步骤、验证办法、成功/失败 Run 引用、人工确认状态。
- 认知类型字段与载荷进入新的 `memory-content-v3` canonical hash；旧记录继续使用原 v1/v2 hash，不升级旧回执。
- 新事实仍是 Personal Memory 或经独立审核的 Team Memory。事实索引、实体关系、向量和缓存都是它们的可重建投影。
- 扩展来源契约时使用显式版本，保留旧 `MemoryProvenanceV1` 解码；原消息、Span、工具结果只引用实际已持久化的身份，不补造 legacy provenance。

不会把 LLM 给出的 confidence 数字当作真值概率。记录证据类别、验证状态与冲突；质量必须通过评测验证。

### 6.2 写入：显式操作与受控自动抽取

1. 用户显式“记住”立即保存私有候选及来源，返回可见状态；“纠正”产生修订；“忘记”立即撤出 Agent 上下文。
2. 自动抽取只在用户主动开启个人学习后处理其授权来源。普通聊天继续私有，不产生团队发布或隐式 `$` 工作流。
3. 新增每用户策略 `off / suggest / private_auto`，默认 `off`；`suggest` 只提议，`private_auto` 只接受可引用的本人明确陈述和受信工具观察。模型回答中的猜测只保留为待验证候选。
4. 抽取作为持久作业，以来源 ID、版本、抽取器版本形成幂等键；批量处理，初始上限每批 10 个事件、8k input tokens、2k output tokens、每日每用户 50k total tokens。
5. schema、源范围、来源 hash、敏感信息、删除水位和语义冲突校验通过后才发布。过期作业不得复活已撤回的内容。
6. 团队共享仍由显式 capture 与 Memory Review 决定，后台整理不能自行接受 Team Candidate。

抽取失败不会阻塞聊天；UI 显示“待处理/失败/未形成记忆”，避免静默宣称已经记住。

### 6.3 时间、更新和冲突

- 区分系统获知时间 `observed_at` 和现实有效时间区间。无法从证据确定的时间保持未知，不能拿写入时间填充事件时间。
- 默认事实允许多值。首版只对已登记的排他属性应用替代规则：首选语言、当前角色、项目负责人、当前状态、明确截止时间。
- 只有同主体、属性、授权范围及重叠有效区间，才比较是否相互排斥。
- 本人明确纠正自己的私有事实，可以形成新修订；权限不足时不能修改团队事实。
- 推断出的矛盾只标记为待澄清，保留双方来源；不采用简单“后写入者覆盖”。
- 历史问题按指定日期选择有效版本，未来生效事实不进入“现在”回答。

示例：9 月已由张某负责，10 月改由李某负责，应能同时回答“现在是谁”和“9 月是谁”；10 月补录的 8 月经历不能覆盖 9 月开始的状态。

### 6.4 召回与上下文

召回过程固定为：服务端授权 → 生命周期/有效时间/类型过滤 → 关键词与向量候选 → 现有 RRF → 证据与冲突处理 → 去重 → 预算 → 引用保留 → 最终上下文交付回执。

- 核心记忆只放用户明确确认的稳定偏好、目标和索引，初始上限 1k tokens；当前请求与当前任务约束优先。
- 当前工作状态初始上限 2k tokens；自动检索记忆初始上限 4k tokens、最多 8 条；必要的完整来源由工具按需获取。
- 整体输入上限由模型 profile 决定：输入、预留输出和余量之和不得超过 context window。模型未知时使用保守 profile，不套用所有模型统一的 60k 阈值。
- 提供 tokenizer adapter；没有精确 tokenizer 时采用保守估算并标明 estimated，不能把估算量当作计费 usage。
- 为冲突、历史版本和“没有证据”保留显式返回状态，禁止把无命中解释为事实不存在。
- 原始历史保留独立事件记录。压缩产生有 source IDs 的派生摘要，不覆盖原记录。
- 近期消息、工具调用及其结果按完整单元裁剪，避免截断 function call/result 配对。
- 阶段 2 不新增必需 reranker 服务。若后续引入，必须在固定 holdout 上有增益；其超时应回退已有 RRF。

摘要只作为导航：按全部来源的分批覆盖生成，并保存覆盖水位和来源集合。源失效时标记摘要需要重建；来源不足时返回材料不足。

### 6.5 忘记、撤回与隐私

“已过时”保留历史版本；“忘记”停止使用并清理适用范围内的事实、索引和派生内容，二者是不同操作。

- 用户可忘记自己拥有的个人记忆。提交事务即标记不可检索，并写删除/抑制水位；异步删除向量、缓存与派生摘要。
- 来源链上的派生私有事实与经验立即失效或重算。仍在运行的抽取任务提交时必须校验水位。
- 默认保留可供本人查看的原始聊天，但含被撤回声明的来源事件不得重新进入自动上下文或学习。另提供显式清理原始来源的选项。
- 已发布的团队知识按现有权限撤回或废弃，不能让个人删除操作无条件删除其他成员的合法资产。
- 历史 MemoryUseReceipt 保留身份/hash/版本事实；详情显示已撤回，不再提供被删除的内容。审计中不新增原文。
- 备份采用部署侧明确的保留期限，并在恢复后重放删除水位；不能声称在线删除等于备份即时擦除。

### 6.6 过程学习

扩展现有 LearnedSkill，而非另建自动插件平台。成功/失败 Run、验证结果与用户纠正组成经验候选；重复成功的相似任务仍只提出草稿。

程序经验必须有前置条件、适用环境和验证步骤，人工激活后才参与后续任务。它只能建议已有授权工具，不能生成 grants、绕过 Profile trust 或自行安装第三方脚本。第二次执行记录“复用了什么、是否成功、是否再次犯同类错误”。

后台整理初始只做去重、索引摘要和经验提议，按源水位增量运行；不配置无限反思循环。

## 7. 执行、工具与 Runner

### 7.1 统一上下文与审批

服务器和 Runner 使用同一 `ContextSnapshotV1`：冻结结构化输入、任务/计划版本、Skill 身份、记忆 ID/version/hash、source IDs 和预算。完整内容只在授权存储与执行通道中出现，Audit/Event 只存安全 metadata。

Runner 消费结构化消息，Session 通过控制平面的版本化接口读取/提交，不另建长期会话权威。收到 SDK 审批中断时保存版本化 RunState，云端审批后在有效 lease 下恢复；恢复前复核用户、grant、输入和节点版本。

远程记忆使用不能在“云端搜到了”时记回执。先冻结引用，再由 Runner 的实际模型交付事件提交 snapshot hash，服务端校验并幂等记账；无法证实交付的状态只显示 prepared。旧 V1 回执语义和历史 hash 保持原样，新远程状态使用版本化契约。

### 7.2 持久执行

复用 dispatch/lease/tool claim/node result，明确三类恢复：

- 已提交的节点结果直接复用。
- 未执行的节点重新调度并复核权限。
- 已调用外部系统但结果未知的操作标记 indeterminate，查询 Provider 状态或转人工对账。

调度采用至少一次投递，数据库结果按幂等键提交。外部副作用是否恰好一次取决于 Provider 的业务幂等支持，不能仅靠本地 claim 保证。尚不支持可靠对账的写工具继续不可自动执行。

把等待审批/Runner 下线和有效执行时间分开。继续有总体 deadline、节点 deadline、tool call、token 和费用上限；状态不明、预算耗尽和人工等待到期均有明确停止原因。

### 7.3 工具与协议

保留现有 ToolGateway，统一 Native/O2/MCP/Runner 的契约、授权、side effect、超时、取消、输出上限和 claim/outcome。先完善已有五类企业工具与本地读能力，再按真实用户需求增加操作。

当前 MCP 官方规范为 [2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/changelog)，Tasks 是可选扩展。实现依照实际客户端与服务端协商结果，不假设所有连接器支持新版 Tasks。AgentMesh 自身的 SSE cursor、事件持久化和业务幂等独立于 MCP 连接恢复。

当前 Runner 只有受限本地文件读取，没有任意 shell。引入执行代码或写工具必须是独立能力切片，具有授权目录、操作白名单和 OS/容器级隔离；不能将正则拦截或本地目录检查宣称为沙箱。本方案前四阶段不把任意 shell 作为必需能力，也不要求用户终端安装 Docker。

## 8. 持久化与新增技术

| 技术 | 是否采用 | 解决的问题与维护成本 |
| --- | --- | --- |
| OpenAI Agents SDK | 保留当前版本 | 继续作为 Agent loop，单独升级并验行为；不因追新同时换 Provider |
| PostgreSQL + pgvector | 阶段 3 引入 | 持久状态、事务、并发与向量统一；增加数据库备份和升级责任 |
| SQLAlchemy Core 2.x + Psycopg 3 | 阶段 3 引入 | 显式 SQL/连接池/事务，降低数据库重复代码；不引入庞大 ORM 关系对象图 |
| Alembic | 阶段 3 引入 | 显式版本迁移与校验，取代持续扩大的启动 schema 脚本 |
| 单一数据库作业队列 | 阶段 3 引入 | 复用 lease/outcome，支持重启；一个 Worker 进程，无 Redis broker |
| OpenTelemetry Python | 阶段 4 引入 | 脱敏 span 与 usage 关联；默认本地出口，有现成内网 OTLP 才接入 |
| uv + uv.lock | 阶段 1 引入开发流程 | 可复现 Python 安装；不自动升级所有包，不改用户现有 venv |
| Neo4j/Graphiti、Mem0/Zep 服务 | 暂不引入 | 时间与来源关系先用关系表表达；多跳 holdout 证明收益后再决策 |
| Redis/Celery、Temporal、Kafka、Kubernetes | 暂不引入 | 当前没有证据证明需要这些独立系统 |
| 第二种后端语言或新的前端框架 | 不引入 | 保持团队技能和运行栈稳定 |

选用 [SQLAlchemy Core/async](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)、[Alembic](https://alembic.sqlalchemy.org/en/latest/tutorial.html) 和 [uv 锁定机制](https://docs.astral.sh/uv/concepts/projects/sync/)；采用它们的标准接口，避免自建迁移框架与安装器。

### 8.1 PostgreSQL 迁移方式

1. 先从 SQLite 巨型 Store 提取聚合级接口，保持事务与行为；阶段 2 的增强记忆仍可用 SQLite。
2. PostgreSQL 第一切片迁移所有现有 records、专用事务表与索引，包括历史兼容表。规范化 Memory/Runtime/Task 查询；低频旧集合可暂保留 JSONB payload，不要求一次规范化全部领域。
3. 不跨数据库长期双写。停写、备份、全量导入、校验，再切换连接；导入失败继续运行原 SQLite。
4. 保持 ID、版本、时间戳、canonical hashes、command receipt、Skill/Run 历史和审批关系。必须校验行数、hash、引用闭合、授权投影与旧数据解码。
5. 使用 PostgreSQL 行级 claim/锁实现多个 Worker 的互斥；事务不覆盖 LLM、embedding 或工具网络 I/O。`SKIP LOCKED` 适合作业领取，依据[官方 SELECT 文档](https://www.postgresql.org/docs/current/sql-select.html)实现。
6. 全部 Repository 行为合同在 SQLite/PostgreSQL 运行；数据库切换后 SQLite 只保留小团队/开发模式，不成为生产双权威。

PostgreSQL 启用后先保留单 Workspace 产品边界。并发数据库并不自动提供多租户产品能力，公网 SaaS 需要另一份租户与部署设计。

### 8.2 4096 维向量与中文检索

当前 embedding 模型为 `Qwen3-Embedding-8B-joybuilder`，维度硬编码为 4096，索引 signature 已包含模型与维度。

[pgvector 官方说明](https://github.com/pgvector/pgvector)中常规 HNSW 的 `vector` 上限为 2000 维、`halfvec` 为 4000 维。4096 维可以保存和精确检索，但不能直接创建这些常规 HNSW 索引。

明确采用以下策略：

- 首次迁移继续保存完整 4096 维向量并做授权范围内精确检索，避免切模型导致旧向量不可比。
- 以 10k/50k/100k 条可检索记录、受限授权范围和 10 个并发查询测 p95、召回与内存。
- 当受限查询 p95 超过 500ms，使用 4096-bit binary quantization 的 HNSW 召回最多 128 条，再用完整向量重排；与精确结果相比 Recall@8 至少 95% 才启用，否则维持精确查询。
- SQL WHERE 保留权限、状态和有效时间条件；近似索引的扫描方式与返回数量必须测试，应用再次复核最终候选。
- PostgreSQL 的英文全文检索不能直接替代当前中文匹配。保留并测试现有中文 bigram 规则，使用应用规范化 token 的倒排投影；另以 pg_trgm 处理明确的子串查询，再与向量 RRF 融合。
- Embedding 按来源 hash 和 index signature 幂等索引；模型改变必须另建索引并重嵌入，不混用不同空间或简单截断维度。

## 9. 产品闭环

增强现有页面，避免新增一组互相重复的记忆管理入口。

- Knowledge：事实/经历/经验过滤、来源原文、有效时间、冲突、修订和忘记；沿用现有治理历史与 lineage。
- Digital Self：展示可编辑核心偏好及个人学习策略，显示最近记住/纠正的内容。
- Workspace：沿用 MemoryUsePanel，展示本次实际引用、准备但未交付、冲突或证据不足；正文提供引用回查。
- Task：展示恢复位置、待决审批、采用经验与验证结果，延续 Task Review → explicit capture → Memory Review。
- Collaboration：补齐有授权边界的 delegated query、本人确认、回答和采用流程；采用不会自动获得原始私有记忆权限。
- Admin：显示 queue age、Runner 健康、模型/工具耗时、token、降级与失败原因；真实数据和 Mock 展示保持明确区分。

自然聊天的私有默认和显式 `$` 行为保持现有产品规则。个人学习策略可选择关闭；团队共享由独立命令和审核驱动。

## 10. 公共接口与配置增量

复用现有 `/api/memory/entries` 列表/详情/lineage、`/api/memory/{id}/revisions`、`transitions` 与 Memory Review decisions。仅新增以下必要接口：

| 接口 | 用途 | 授权与一致性 |
| --- | --- | --- |
| `GET/PATCH /api/memory/preferences` | 当前用户的学习策略和核心偏好 | scope 由会话推导；PATCH 带 command_id/expected_version |
| `POST /api/memory/facts` | 显式私有事实及来源 | 只允许当前用户；不得借参数提交其他 owner |
| `POST /api/memory/{id}/forget` | 撤回个人记忆及适用派生物 | command_id/expected_version；返回删除作业状态与影响范围 |

个人事实纠正沿用 revisions 并增加 owner-scoped personal revision 行为；团队修订仍走候选和独立审核。所有命令重新检查权限、版本和幂等，详情可添加认知载荷但不改旧记录 hash。

Runner 增加版本化 envelope/approval/session submission 契约，旧 envelope 保留兼容读取，只有声明新能力的 Runner 获得新任务。Session 提交携带 expected_version、提交幂等键与完整消息单元；不开放任意数据库方法调用。

配置增量限定为数据库 URL、Worker concurrency 和可选 OTLP endpoint；预算集中在服务端类型化配置，个人策略存在用户配置中。继续使用 `AGENTMESH_MEMORY_CONTEXT=off|observe|inject` 及现有 Runtime/Task/Orchestration 门禁，避免再添加多组平行 env 开关。

数据库 URL 只在 Server/Worker，绝不进入 Runner。OTLP 默认不发送原始 prompt、来源正文或文件内容；GenAI span 按[官方约定](https://opentelemetry.io/docs/specs/semconv/)接入并固定所使用的版本。

## 11. 分阶段交付与验收

| 阶段 | 工作量 | 交付内容 | 独立价值与验收 |
| --- | --- | --- | --- |
| 1：可信基线 | 3–5 天 | 隔离 Provider 的测试、修正评测口径、依赖锁、Memory/Runtime Repository 边界、120 个记忆 fixture | 当前产品照常可用；CI 无真实业务服务依赖；形成当前质量/耗时基线 |
| 2：增强记忆 | 10–15 天 | 私有事实、时间/冲突/纠正/忘记、持久抽取作业、统一 ContextAssembler、事实 UI | SQLite 下可用；个人记忆闭环可交付；来源和撤回硬断言全部通过 |
| 3：生产持久层 | 12–18 天 | PostgreSQL、Alembic、完整状态迁移、检索投影、独立 Worker、持久文档输入、备份恢复 | 现有 API 行为兼容；迁移 row/hash parity；并发 claim 与重启测试通过 |
| 4：可靠 Runner | 7–10 天 | 结构化 Session、ContextSnapshot、远程记忆交付回执、审批恢复、节点重启与脱敏 OTel | Server/Runner 在相同 fixture 上有一致上下文和结果边界；断线/旧 lease/重复提交不会污染状态 |
| 5：经验与协作 | 8–10 天 | 经验证的过程记忆、核心偏好、delegated query/consent/adoption 用户闭环 | 第二次任务能复用已确认方法；协作全过程可追踪，独立团队审核继续生效 |

阶段 2 的初始受控抽取作业复用单进程 dispatch 与 SQLite 事务，不等待阶段 3 的 Worker 才能执行。阶段 2 的服务器记忆先形成完整闭环，阶段 4 再使 Runner 获得相同增强能力；UI 必须如实显示执行位置的支持范围。

预计代码目标：`memory_context/`、`memory_governance/`、`routes/memory*.py`、`agent_runtime/{service,session,compaction,hooks,trace_processor}.py`、`store.py`、`models.py`、Runner 文件、Knowledge/Digital Self/Workspace/Task/Collaboration/Admin 对应 feature，以及新增 context、memory ingestion、persistence、worker、迁移与评测文件。

先交付纵向功能再继续拆分热点。每个阶段采用独立分支/PR，不将 8–12 周的变化积累为一次大提交。

## 12. 如何证明记忆与 Agent 能力达到目标

### 12.1 确定性行为验证

增加 120 个版本控制 fixture：事实提取、事实更新、时间查询、冲突、证据不足、隔离/撤回各 20 个；过程学习另加 24 个两次执行的固定任务轨迹。测试使用 ScriptedModel/固定 Tool 与临时数据库。

必须覆盖：

- 正常记住、查找、纠正、忘记和来源回查。
- 跨用户/项目拒绝、停用用户、审核未通过、权限在任务中变化。
- 重复抽取、并发修订、乱序历史、未来有效事实、多值事实。
- 来源撤回后的派生摘要/经验失效，作业晚提交不能复活数据。
- 工具失败、模型超时、embedding 失效、Worker 重启、两个 Worker 同时 claim。
- 审批中重启、Runner 掉线、过期 lease 回传、重复事件/完成请求。
- 模型上下文压缩后工具调用配对、任务约束和来源身份仍完整。
- 外部副作用成功但回执未提交：支持业务幂等的 Provider 不重复执行；不支持的进入 indeterminate。
- 记忆中的“忽略权限/执行脚本/上传密钥”不能改变授权。

### 12.2 长期质量评测

使用冻结的项目 holdout 为发布主指标，以 [LongMemEval](https://github.com/xiaowu0162/LongMemEval)、[LongMemEval-V2](https://github.com/xiaowu0162/LongMemEval-V2) 和 [LoCoMo](https://github.com/snap-research/locomo) 作外部对照。V2 包含任务轨迹知识，适合检验过程记忆；公开 benchmark 分数与本项目任务完成率分开报告。

比较 4 个版本：无长期记忆、近期历史+摘要、现有 FTS/向量+治理、增强记忆。使用相同任务、模型、输入/输出预算和评价规则，并分别统计后台学习成本。

下列为拟定发布目标，**不是本轮测得的性能**：

| 指标 | 目标与解释 |
| --- | --- |
| 权限/版本/hash/来源/撤回硬断言 | 100% 通过；跨用户泄漏和撤回复活为 0 |
| 持久状态故障注入 | 所有列出的恢复边界通过；不宣称任意外部写恰好一次 |
| 120 个 holdout 的有证据答案正确率 | 至少 85%，且比现有记忆基线提升至少 10 个百分点 |
| 事实更新/时间推理正确率 | 两类分别至少 90%，避免总分掩盖弱项 |
| 无证据时正确表示未知 | 至少 95% |
| 过程复用的重复错误率 | 24 个轨迹集比无过程记忆基线下降至少 30% |
| 检索 p95 | 目标环境 50k 记录、10 并发下端到端 ≤1s；另报告 DB 与 embedding/rerank 部分 |
| 在线 token | 不超过对应无增强方案预算的 1.25 倍；后台 token 单独公开 |

若相对增益因现有基线已经很高而不可达，则依据置信区间与单项错误分布调整门槛并记录 ADR，不能修改测试答案来通过。评测输出记录模型/Provider/version、fixture hash、配置、usage、耗时与错误类型。

真实模型评测沿用既有闭环计划的分批方式：先 24 个代表任务、单批总 token 上限 500,000；之后根据报告再决定下一批。本轮不执行真实付费评测，自动评价不等于人工 Task/Memory/Profile 审核。

## 13. 依赖、失败处理与发布

### 13.1 外部依赖与凭据

| 项目 | 要求 | 本轮验证状态 |
| --- | --- | --- |
| 既有模型 Provider | 现有 API URL/key；用于回答、受限抽取和可选 embedding | SDK 本地版本可用、mock 路径验证；真实凭据和可用性未验证 |
| PostgreSQL | Server/Worker 专用 DB credential、备份位置 | 官方能力已核实；本轮未创建数据库或连接企业实例 |
| O2 | 宿主机既有 CLI 登录态 | `o2 --help` 可用；本轮不以业务查询证明发布可用性 |
| MCP/Web/Data | 继续使用已有、被授权的 Provider 配置 | 不新增必需第三方账号；真实 smoke 在发布环境进行 |
| OTel | 可选内网 OTLP endpoint；如需 auth 只在服务端 | 官方约定可访问；默认本地出口不依赖外部观测服务 |

无需购买 Mem0/Zep/Letta 托管服务账号。现有 Provider 配置不是自动执行真实 smoke 的授权；发布时先展示具体环境与用量，再按已有门禁完成。

### 13.2 失败与规模处理

- 模型/embedding 不可用：显式操作和 FTS 继续可用；抽取 job 可重试，不能把无 embedding 当作完整语义能力。
- Worker 下线：作业保留 pending，API 与已存在记忆可用；queue age 可见。
- Runner 下线：保持排队或要求用户选择执行位置；不擅自把本地任务移到服务器以改变数据边界。
- 增长 10 倍：首先检查向量精确扫描、collection hydration、事件增长和 Worker backlog；限制队列、分页及预算，按第 8.2 节的召回门槛开启 ANN。
- 抽取错误：用户可修订或忘记，派生关系可回查；暂停学习不影响已有任务系统。
- 不在版本化结果与事件接口中暴露原始私有 prompt、Provider keys 或不相关用户数据。

### 13.3 迁移与回退

- 新载荷、投影和契约采用增量迁移，旧 Memory/Run 不原地改 hash。
- 功能回退先将 Memory injection/learning 关闭，继续使用兼容旧记录的新二进制。
- PostgreSQL 切换前可回到原 SQLite；切换且已有新写入后必须使用兼容的新版本继续前进。禁止直接恢复旧 SQLite 丢掉新增事实。
- 对重建索引使用独立 signature/投影，验证后切换，失败保留旧可用索引。
- 新 Runtime 数据的回退遵守既有 quiesce/roll-forward，不承诺旧二进制可读全部新增记录。
- 首次上线做停写备份、迁移校验、恢复演练、受控用户验证；默认不直接开启所有 Skill 或全部 Provider。

需要重开 ADR 0001 的 pgvector 暂缓决定、落实 ADR 0002，并更新 CONTEXT 的单 SQLite/单进程边界；这是下一阶段提案，不会暗中修改当前 MVP 默认。ADR 0012/0013 的治理与回执权威继续成立。ADR 0009/0010 的独立 Profile/Provider/发布证据要求仍适用，AI 评测不替代它们。

## 14. 实施验证与本轮结果

每个 PR 运行适合变化的测试；阶段验收运行以下基线：

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest
npm --prefix agentmesh-demo test
npm --prefix agentmesh-demo run build
```

阶段 1 必须让标准 pytest 命令对已安装 O2 和其他 Provider 保持隔离。现有 admin capability 测试会触发实际 O2 状态/setup probes；本轮通过将 `AGENTMESH_O2_COMMAND` 指向不存在的审计专用命令隔离宿主机默认探测后重跑。该临时环境设置没有写入仓库。

后续新增 `eval/run_memory_eval.py`、`eval/memory/cases.json` 和结果报告命令，默认 ScriptedModel；真实模型模式必须显式指定 model、案例批次及 token cap。PostgreSQL 集成测试使用独立临时实例，禁止使用个人或生产数据库。

本轮已确认：隔离默认 O2 探测后，后端 1,900 项测试全部通过，耗时 372.95 秒，5 项依赖弃用警告；Ruff 通过；前端 34 个测试文件、200 项测试通过；TypeScript/Vite 生产构建与 500,000-byte bundle budget 通过。本机后端环境为 Python 3.13，仓库 CI 配置为 Python 3.12，本轮没有重跑远程 CI，也没有运行浏览器端 E2E、生产数据库压力测试或真实 Provider 质量验收。

人工验收采用真实用户动作：跨会话记住偏好、纠正项目负责人、回答过去日期、忘记后再次提问、Runner 断线重连、审批期间重启、来源撤回和第二次任务复用经验。

## 15. 执行顺序

先冻结当前 Runner 工作区，交付阶段 1 的隔离测试与质量基线，再实施阶段 2 的私有增强记忆。以实测长期质量决定后续投入。达到阶段 2 验收后，分别提交 PostgreSQL 迁移、可靠 Runner、过程记忆与协作闭环的独立 PR。

该顺序能逐步把“知道历史”“理解变化”“恢复执行”“吸取经验”变成可验证的产品行为；每个阶段结束后系统都能独立使用。
