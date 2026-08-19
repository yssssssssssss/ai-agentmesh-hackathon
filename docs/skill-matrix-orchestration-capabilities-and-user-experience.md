# Skill Matrix 编排技术能力与用户体验提升

当前实现把 AgentMesh 从“用户需要手动选择单个 Skill”升级为“自然语言驱动、可预览、可治理、可恢复的多 Skill 工作流”。

## 一、核心技术能力与体验提升

| 技术能力 | 当前实现 | 用户实际感知 |
| --- | --- | --- |
| 自然语言意图理解 | 将请求结构化为目标、设计阶段、输入类型、交付物、写入约束和复杂度；模型不可用时有确定性降级 | 用户可以直接说“评审 PRD，并准备访谈和问卷”，无需了解 Skill 名称或命令 |
| Skill 安全召回 | 基于能力画像、生命周期、输入输出、示例和语义相关度，从 10 个领域 Skill 中召回最多 12 个候选；11 个 Legacy 能力只作为底层工具 | 推荐结果更贴合任务，不会把内部原子工具混入用户候选列表 |
| 权限与就绪过滤 | 召回前检查 Skill 启用状态、绑定、Wiki 语料、Tool Grant、项目权限和所需能力 | 用户只会看到当前真正可用、可执行的 Skill，减少“点了才发现不能用” |
| 多 Skill DAG 规划 | 最多 6 个节点、深度 4、同层并行 3 个；显式记录依赖、输入绑定、输出契约、是否必需和副作用 | 复杂任务会被自动拆解，独立任务可并行执行，整体等待时间更短 |
| 严格计划校验 | 拒绝环、未知依赖、重复 Skill、无效输入、上下游契约不匹配、版本/hash 漂移、越权候选和无法满足的交付物 | 系统不会展示一个“看起来合理但实际跑不通”的计划 |
| 执行前确认 | 多 Skill 计划进入确认页；用户只能增删候选范围内的可选节点、调整合法顺序，必需节点不可删除 | 用户在消耗模型、调用工具前能够看懂并控制实际执行内容 |
| Preview 灰度模式 | `preview` 模式只生成并确认计划，不执行 Skill | 团队可以先体验规划质量，不承担真实工具调用风险；界面明确显示“预览模式未执行” |
| 有界并发执行 | DAG 按依赖调度，最多同时运行 3 个节点；整轮受 300 秒截止时间约束 | 多项分析可以并行完成，同时避免无限并发或任务长期占用 |
| 安全重试 | 仅 `read`、`draft` 节点在明确临时网络/Provider 错误时重试一次；写入节点不自动重试 | 临时故障可自动恢复，同时避免重复发布、重复写入或重复产生副作用 |
| 失败传播 | 上游失败后，所有传递依赖节点自动跳过；可选节点失败产生 Partial，必需输出无法满足才整体失败 | 用户可以保留已经完成的有效结果，不会因为非关键证据失败而一无所获 |
| 结构化综合结果 | 每个节点输出摘要、发现、建议、来源、置信度、限制和 Artifact；最终结论关联 Node Result 与 Source | 用户得到的是一份统一成果，而不是多个 Skill 输出的简单拼接，并可追溯结论来源 |
| JoyBuilder 结构化输出兼容 | 按模型显式选择 `json_schema` 或 `json_object`；JoyBuilder 使用 JSON mode、系统指令内 Schema 和本地 Pydantic 校验，带工具的结构化回合避免发送冲突的 `response_format` | 用户仍获得稳定的结构化计划和结果，同时保留真实 Function Tool 调用，不会因 Provider 协议差异在第一步直接失败 |
| 持久化状态机 | Run、Plan、Node、Result、Event、Approval 均持久化到 SQLite，并使用版本号/CAS 控制状态转换 | 刷新页面、断线重连后仍能恢复进度，不需要重新执行任务 |
| SSE 实时进度 | 提供计划、节点、审批、综合、完成和失败事件流 | 用户能实时看到“规划中、等待确认、执行中、等待工具审批、部分完成”等状态 |
| 幂等创建与重试 | `client_turn_id` 在 SQLite 事务中原子占用，并区分原始 `auto/single` 请求模式 | 网络响应丢失后再次发送或重试，不会创建第二个 Run、重复调用模型或重复写入 |
| 安全取消与回滚 | 取消会终止 Run、Plan 和未完成节点；切换到 `off` 或关闭 Runtime 会释放等待中的编排任务 | 管理员回滚功能开关后，不会留下锁死会话或继续执行的后台任务 |
| 过期审批回收 | 计划审批和 Tool 审批过期后，在启动恢复或创建新 Run 时自动取消，并关闭 Inbox | 用户不会因为一条旧审批永久无法继续当前对话 |
| 调用时重新授权 | Function Tool、MCP、Skill Resource 在实际调用前重新检查项目权限和当前 Tool Grant | 即使管理员在规划后撤权，系统也不会使用旧授权继续访问数据或工具 |
| Wiki 资源隔离 | Skill 只能读取其登记的完整 Wiki 子树，拒绝同后缀目录、路径穿越和跨 Skill 访问 | 不同领域 Skill 的知识边界不会因为目录名称相似而被绕过 |
| 可控灰度 | 统一支持 `off / preview / execute`，前端从后端 Bootstrap 获取真实模式 | 运维无需重新构建前端，即可关闭、预览或开放多 Skill 执行 |

## 二、用户界面的具体变化

### Skill Center

- 展示 Skill 是否已绑定、是否具备规划条件以及不可用原因。
- 用户可以从 Skill Center 跳转 Workspace，并自动预填 `$skill-name`。
- 不会自动发送，用户仍可补充任务描述后再确认。

### Workspace 计划预览

用户可以直接看到：

- 本次任务目标；
- 候选 Skill 和最终选中节点；
- 每个节点的作用、输入、输出和依赖；
- 哪些节点是必需节点；
- 哪些节点可以并行；
- 当前是 Preview 还是 Execute 模式。

修改计划时使用版本号控制。如果其他操作已经更新计划，前端会刷新服务端权威状态，避免覆盖新版本。

### 执行进度

每个节点有独立状态：

- 待执行；
- 已就绪；
- 执行中；
- 等待工具审批；
- 已完成；
- 失败；
- 已跳过；
- 已取消。

用户可以在执行过程中取消，也可以直接跳转待处理审批。

### 结果展示

- Partial 结果会明确标记缺失证据和限制。
- 综合结论能够打开关联来源和 Artifact。
- Preview 完成不会再误显示为“任务已完成”，而是“计划已确认，预览模式未执行”。

### 失败恢复

- 普通发送失败或服务端状态未知时，Composer 不再被永久锁死。
- 草稿会保留并允许继续编辑。
- 用户未修改内容时，“重新核对/重试”会复用原 `client_turn_id`。
- 用户主动修改内容后才生成新的请求 ID，避免把不同内容误认为同一次请求。
- Run 重试成功后会刷新线程和线程列表，计划审批期间也能看到新增用户消息。

## 三、一次完整用户旅程

用户输入：

> 帮我评审这份 PRD，分析可行性，并准备后续用户访谈。

系统将执行：

1. 提取 `prd` 输入、可行性评审和访谈交付物。
2. 从当前用户已授权、已就绪的 Skill 中召回候选。
3. 生成 PRD 评审与访谈准备的依赖计划。
4. 服务端校验输入输出、权限、Skill 版本和交付物。
5. 向用户展示计划，等待确认。
6. 用户可删除可选节点或调整合法顺序。
7. 确认后执行；独立节点并行运行。
8. 如节点需要外部工具，整个 DAG 暂停并等待逐调用审批。
9. 审批后从原节点恢复，而不是重新执行整份计划。
10. 最终输出统一报告，标明来源、限制和各 Skill 的贡献。
11. 页面刷新或网络重连后，仍从持久化 Run/Plan 恢复进度。

## 四、安全与可靠性提升

当前已重点封堵：

- Run 实际项目与用户默认项目不一致时的越权访问；
- Intent 分析等待期间项目权限被撤销；
- Plan 确认后、节点执行前或综合阶段撤权；
- Function/MCP 规划完成后撤销 Tool Grant；
- Wiki 同后缀错误目录被误认为授权子树；
- 并发确认导致重复执行；
- 网络丢包后重试产生第二个 Run；
- 多层依赖失败未完整传播；
- 过期审批永久锁住线程；
- 切换功能开关后旧审批仍可继续执行。

## 五、当前质量证据

- 后端：725 项测试通过。
- 前端：92 项测试通过。
- Playwright：49 项浏览器测试通过。
- Ruff：通过。
- TypeScript、Vite 构建和 Bundle 门禁：通过。
- 40 条召回评测 Top-3 Recall：100%。
- 召回 p95：14.9ms。
- 不可用、禁用、未授权 Skill 召回率：0%。
- 10 个领域画像、11 个 Legacy 画像检查：0 错误、0 警告。

### 真实 Provider 授权环境验证（2026-08-19）

- 最终命令：`AGENTMESH_CHAT_LLM_TIMEOUT_SECONDS=60 .venv/bin/python scripts/agent_sdk_smoke.py --all-configured`；退出码 `0`；耗时 `89.02s`；`passed=true`；`skipped=[]`。
- Provider provenance：`requested_provider=openai_agents_sdk`，`actual_provider=JSONObjectChatCompletionsModel`，结构化输出模式为 `json_object`；脚本没有项目 Mock 或本地 fallback 分支。
- GPT‑5.2 JoyBuilder：6 次请求，1,698 tokens，9 项检查全部通过。
- GPT‑5.4 JoyBuilder：6 次请求，1,491 tokens，9 项检查全部通过。
- GPT‑5.5 JoyBuilder：6 次请求，1,606 tokens，9 项检查全部通过。
- 每个模型通过的检查均为：结构化 Intent、结构化 Plan、两个并行 Node Result、结构化 Synthesis、Streaming、Function Tool、Usage、Cancellation 和 Provider provenance。
- 一次较早的聚合运行中 GPT‑5.4 出现瞬时 `RateLimitError`；其独立全链随后通过，冷却后的最终聚合运行也通过。该恢复过程没有改用 Mock 或 fallback。
- 按当前验收范围，Kimi K2.6 已从 `AGENTMESH_MODELS` 备选池移除，不属于最终 Provider 门禁对象。

### Web 自然语言入口到真实 GPT 的完整链路验证（2026-08-19）

- 使用与 React `Workspace.send()` 完全相同的请求协议，从自然语言输入提交 `POST /api/agent/runs`，请求模式为 `auto`；Bootstrap 实际返回 `agent_runtime_enabled=true`、`skill_orchestration_mode=execute`。
- 最终验收 Run 为 `run_3ec37fb75c80`，Plan 为 `plan_d4b0a3210b7a`。该轮从 `http://127.0.0.1:5178` 完成登录、输入、计划确认、DAG 执行和结果读取，Intent 交付物稳定为 `research_plan / interview_guide / survey / synthesis`，`explicit_skill_names=[]`。
- GPT 生成并通过校验的 DAG 为 `generate-research-plan → (generate-interview-guide ∥ generate-survey)`；确认计划后三个节点均在首次尝试完成，综合完成。
- 整轮只使用 `5 / 24` 次 Tool Call；三个节点读取并引用 29 个真实 Wiki 资源，覆盖 `methods/...`、`assets/...`、`models/...` 与 `references/...`。
- 最终聊天投影已由错误的 `chat / fallback / model=null` 修正为 `skill_orchestration / openai_agents_sdk / default → GPT-5.2-joybuilder / real`，`model_fallback_reason=null`。
- 根因是 `AgentRuntimeService.project_orchestration_output()` 曾把真实编排结果硬编码为 `llm_used=False`，并丢弃请求模型和实际模型；现改为透传执行阶段的 `SelectedSDKModel`，同时显式标记编排工作流。
- 回归测试 `test_orchestration_projection_preserves_real_model_provenance` 已实际执行 red→green：修复前因缺少 provenance 参数失败，修复后校验 Provider、模型、模式和工作流字段全部通过。
- 最终 Run 与 Plan 均为 `completed`，三个节点均首次执行成功，Synthesis 存在。此前的 `run_fecafbe12b30` 曾如实返回 `partial`：三个节点与 Synthesis 仍成功且 `synthesis_fallback=false`，Partial 只来自 Wiki 正典仍为 draft，以及请求未提供真实费用项、优惠类型、支付方式清单和当前页面信息结构，没有 Provider 或执行失败。
- 另发现旧 Vite 进程曾从仓库根目录启动，导致 5178 虽占用端口但首页和 `/api` 均返回 404；现已按 `npm --prefix agentmesh-demo run dev` 从正确应用目录重启，首页与到 8010 的 API 代理均验证为 200。
- 经 `http://127.0.0.1:5178` 的真实 Vite 代理创建并完成最终 Run，返回的可见字段为 `skill_orchestration / GPT-5.2-joybuilder / real`，证明修复不是后端直连特例。
- 自动化浏览器扩展对本机 `127.0.0.1:5178` 返回 `ERR_BLOCKED_BY_CLIENT`，因此本次未伪称取得真实页面截图；同一轮同时通过 49 条 Playwright Web 测试，且线程 API 返回的 provenance 字段正是 `ConversationThread` 直接渲染的字段。

## 六、当前边界

- 首期只编排 10 个已治理的 Wiki 领域 Skill，不是全部 Wiki Skill。
- 当前仍是 FastAPI + SQLite 原型，不包含多进程调度和水平扩展。
- 编排 Playwright 使用 API mock；真实 HTTP、权限、SQLite 和 DAG 链路由后端集成测试覆盖。
- 真实 Provider 已补充本地 HTTP、SQLite、计划确认、DAG、Wiki Resource Tool、Synthesis 和聊天投影全链路验证；它仍不等同于生产部署、真实外部 MCP 或业务写入工具验收。
- Provider 曾出现可恢复的瞬时限流；进入持续流量前仍需配置容量、退避和限流观测。

因此，当前实现已具备从 `preview` 进入受控 `execute` 灰度所需的真实 Provider 兼容证据，但仍不应被表述为完整生产环境验收。
