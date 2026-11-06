# AgentMesh Next MVP TODO

目标：把 AgentMesh 从“可运行原型”推进到“真实可试用 MVP”。当前阶段不要继续堆页面，优先打通三件事：显式 `$` skill chat、分层记忆系统、真实数据/工具接入。

## 当前状态总览

- [x] Chat 主流程已切换为“普通对话 + 显式 `$` skill 调用”，不再依赖隐式路由分类。
- [x] 普通对话 `general_chat` 已避免创建 task、BBS、memory。
- [x] `$` skill 请求已返回工作流信息并在前端展示。
- [x] 用户三层记忆的后端基础 API 已实现。
- [x] BBS、任务、Oxygen、文件上传、用户角色已有可运行基础。
- [ ] Oxygen 真实 query smoke test 已执行，真实返回仍阻塞于内部工具凭证/初始化。
- [x] Memory 页面已按三层记忆结构重做，并增加页面级 overview 与计数。
- [x] 权限矩阵已有角色、范围、团队成员、核心可见性规则和 MVP 级权限策略表；复杂 ABAC 条件策略留作后续增强。
- [ ] 前端仍是大型单文件 `app.html`，尚未迁移 React。
- [ ] 真实生产数据源 API 配置仍需补齐；项目已提供只读 HTTP 数据源 connector，文件上传、解析、检索、摘要记忆链路已完成 MVP 验收。

## 阶段 1：Chat 主流程重构

优先级：最高  
状态：基本完成；当前路线为显式 `$` skill 调用，后续重点扩大真实任务样本，而不是继续调旧式自动分类。

- [x] 自然输入走普通对话，不触发任务、BBS、Inbox、Memory。
- [x] 输入 `$` 唤起 skill 菜单。
- [x] `$` 菜单支持键盘上下选择、回车插入、鼠标点击。
- [x] `$memory.search`、`$brief.create`、`$note.save`、`$research.request`、`$data.query`、`$risk.review`、`$memory.propose`、`$system.info` 已注册。
- [x] 普通对话走 `general_chat`。
- [x] 普通对话不建任务。
- [x] 普通对话不写 BBS。
- [x] 普通对话不入记忆。
- [x] 只有显式 `$` skill 才创建 task、BBS、Inbox、Memory。
- [x] 接口返回工作流信息：`intent`、`source=skill/chat`、`selected_workflow`、`llm_used`。
- [x] 前端展示 skill 调用路径、来源和结果。
- [x] 增加测试：普通问题不会污染数据库。
- [x] 增加测试：明确查资料、查数据、生成 Brief 能进入正确 workflow。
- [x] 对话等待后端响应时显示“项目正在思考”loading。
- [x] 将前端字段命名统一为产品语言：调用路径、来源、结果。

## 阶段 2：记忆系统重建

优先级：最高  
状态：后端核心、前端分层视图和每日摘要自动化基础已完成。

- [x] 增加用户记忆模型 `UserMemoryItem`。
- [x] 支持 `short_term`、`mid_term`、`long_term` 三层。
- [x] 用户短期记忆按 `user_id` 隔离。
- [x] 用户项目记忆按 `user_id + project_id` 隔离。
- [x] 普通闲聊不进入记忆。
- [x] 有效 workflow 结果进入用户短期记忆。
- [x] 增加短期记忆每日汇总 API：`POST /api/memory/user/daily-summary`。
- [x] 增加短期到项目中期记忆 API：`POST /api/memory/user/project-summary`。
- [x] 增加项目中期到长期归档 API：`POST /api/memory/user/archive-project`。
- [x] 增加空源记忆拒绝生成的测试。
- [x] 增加跨用户不可见测试。
- [x] 给短期记忆增加显式 `memory_date` 字段，而不是仅依赖 `created_at.date()`。
- [x] 增加记忆类型字段：项目背景、数据、竞品、风险、决策、群聊总结、agent 结果。
- [x] 增加每日短期记忆自动生成任务。
- [x] 增加群聊总结进入短期记忆的入口。
- [x] 中期记忆使用 LLM 提炼，而不是简单拼接。
- [x] 长期归档生成项目总结和可召回索引。
- [x] Memory 页面按“我的短期 / 项目记忆 / 项目归档 / 团队候选”重做。
- [x] 验收：每天能产生短期记忆。
- [x] 验收：项目能独立沉淀中期记忆。
- [x] 验收：项目结束能生成归档总结。

## 阶段 3：Oxygen-CLI 真实接入

优先级：高  
状态：适配层已完成，真实可用性未最终验收。

- [x] 增加 O2 状态 API：`GET /api/integrations/o2/status`。
- [x] 增加管理员同步 O2 工具 API：`POST /api/integrations/o2/sync`。
- [x] Agent 页面展示 Oxygen 状态。
- [x] Agent 页面提供管理员同步 Oxygen 工具按钮。
- [x] 表达 `metasearch` 命令契约。
- [x] 表达 `o2-kb` 命令契约。
- [x] 表达 `oxygen-comment` 命令契约。
- [x] 表达 `bdp-copilot` 命令契约。
- [x] 增加 O2 返回 normalizer，转成统一 Source / Evidence / DataRecord 风格。
- [x] research_agent 支持通过环境变量启用 O2/Web provider。
- [x] data_agent 支持注册 O2 connector。
- [x] 固化本机 o2 安装检查流程。
- [x] 固化 o2 登录检查流程。
- [x] 固化 `o2-kb init` 检查流程。
- [x] 固化 Browser Bridge 状态检查流程。
- [ ] 用真实内部 query 做 O2 research smoke test：已执行，阻塞于 metasearch token / o2-kb init / oxygen-comment credentials。
- [ ] 确认真实 `metasearch` 返回格式：doctor 可用，真实 search 阻塞于 token。
- [ ] 确认真实 `o2-kb` 返回格式：阻塞于 `o2-kb init`。
- [ ] 确认真实 `oxygen-comment` 返回格式：doctor 可用，真实 query 阻塞于 credentials。
- [ ] 确认真实 `bdp-copilot` 返回格式。
- [x] research_agent 默认优先查内部 O2 + 外部 Web。
- [x] research_agent 两者都失败时才 fallback mock。
- [x] data_agent 默认优先查真实 connector。
- [x] data_agent 失败后才 fallback 到 `local_metrics`。
- [ ] 验收：真实 query 能通过 O2 返回内部资料。
- [ ] 验收：chat 响应能展示 O2 来源。

## 阶段 4：任务与 BBS 逻辑打磨

优先级：中高  
状态：部分完成。

- [x] BBS 支持请求、证据、风险、决策、记忆候选等类型。
- [x] BBS 帖子显示发帖 Agent。
- [x] BBS 帖子记录读取 Agent。
- [x] BBS 帖子关联任务。
- [x] BBS 帖子关联来源。
- [x] BBS 支持分页。
- [x] BBS 支持读标记。
- [x] BBS 支持回复。
- [x] BBS 支持结构化交接。
- [x] BBS 支持执行锁。
- [x] Agent 自动发帖进入队列。
- [x] 队列发帖支持手动 drain。
- [x] 明确 BBS 帖子类型：请求、证据、风险、决策、交接、归档。
- [x] 任务页展示用户发起任务。
- [x] 任务页展示个人 Agent 认领任务。
- [x] 任务页展示任务上游和下游。
- [x] 完善“领取执行”的权限和状态流转。
- [x] 完善“释放”的权限和状态流转。
- [x] 完善“交接”的权限和状态流转。
- [x] Agent 自动发帖先审计再发布。
- [x] 验收：从 chat 发起调研任务后，BBS 能清楚展示 Agent 协作链路。

## 阶段 5：用户与权限体系

优先级：中高  
状态：MVP RBAC 已完成，支持角色/范围/团队可见性和角色动作策略覆盖；复杂 ABAC 条件策略未做。

- [x] 支持用户、组长、管理员三类角色。
- [x] 支持登录、登出、本地用户创建、禁用。
- [x] 管理员可管理用户。
- [x] 管理员可管理公共 Agent 的部分配置。
- [x] 管理员可管理工具、模型、风险规则的部分配置。
- [x] 已有关键权限测试。
- [x] 定义并落地 MVP RBAC 权限矩阵：用户、组长、管理员，结合个人/项目/团队范围控制。
- [x] 用户只能看自己的任务。
- [x] 用户只能看自己的短期记忆。
- [x] 用户只能管理自己的个人 Agent。
- [x] 组长能看组内项目。
- [x] 组长能看团队候选记忆。
- [x] 组长能看组内任务状态。
- [x] 管理员拥有用户、公共 Agent、工具、模型、风险规则管理权限。
- [x] 每个 API 补权限测试。
- [x] 增加组织/团队成员管理。
- [x] 增加 OAuth/SSO adapter 框架：状态检查、授权跳转、回调换 token、用户映射和本地 session 复用。
- [x] 验收：设计师和组长看到的任务/记忆不再完全一样。

## 阶段 6：真实文件上传与文档记忆

优先级：中  
状态：上传、解析、检索、摘要记忆链路已完成 MVP 验收；OCR 依赖本机 `tesseract`。

- [x] 保留 `.txt` 上传解析。
- [x] 保留 `.md` 上传解析。
- [x] 增加 PDF 解析依赖。
- [x] 增加前端上传入口。
- [x] 上传文件后生成 `DocumentRecord`。
- [x] 上传文件后生成 `Source`。
- [x] 上传文档可被 chat 稳定检索。
- [x] 文档摘要进入短期记忆候选。
- [x] 大文件解析走异步任务。
- [x] 增加 Word 解析 connector。
- [x] 增加图片 OCR connector。
- [x] 增加 slide/PPT 解析 connector。
- [x] 验收：上传一份项目文档后，chat 能基于文档回答并引用来源。

## 阶段 7：工程结构升级

优先级：中  
状态：未完成。

- [x] 后端已拆成 FastAPI Router 结构。
- [x] 已有 ruff lint。
- [x] 已有 pytest 测试。
- [ ] 前端迁移到 Vite + React + TypeScript。
- [ ] 拆分 Chat 组件。
- [ ] 拆分 BBS 组件。
- [ ] 拆分 Tasks 组件。
- [ ] 拆分 Memory 组件。
- [ ] 拆分 Agent 组件。
- [ ] 拆分 Users 组件。
- [ ] 拆分 Inbox 组件。
- [ ] 保持现有 API 不大改，先迁移 UI。
- [ ] 数据库从单 KV records 表迁移到专用关系表。
- [ ] 验收：前端不再是 4000 行单文件。
- [ ] 验收：新功能能独立开发和测试。

## 推荐执行顺序

1. [x] Chat 主流程改为显式 `$` skill + 普通对话不入库。
2. [x] 记忆系统数据模型基础设计。
3. [x] 用户短期记忆落库。
4. [ ] O2 research 真实调用 smoke test。
5. [x] Memory 页面按三层结构重做。
6. [x] BBS/任务状态流优化：证据帖可沉淀为候选团队记忆。
7. [x] 权限矩阵落地。
8. [ ] 前端 React 拆分。

## 下一步建议

优先执行下面三个任务，能最快把项目推近“真实可试用 MVP”：

- [ ] O2 真实调用 smoke test：确认内部资料能真实返回并进入 chat 来源展示。
- [x] Memory 页面重做：让短期、中期、长期、团队候选在产品上可见。
- [x] 权限矩阵补齐：让设计师、组长、管理员看到的任务和记忆真正不同。
