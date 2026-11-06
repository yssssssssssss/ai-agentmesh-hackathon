# ADR 0044：统一 Agent 记忆内容类型与旧绑定确认

状态：接受（本地绑定语义与相关消费者；完整 ContextAssembler、SDK/Runner 治理及真实质量验收继续开发）。

`allowed_memory_types` 原来有两种含义：普通 `search_for_agent` 用它筛选 document、memory_item 等搜索结果类别，SDK、上下文、市场材料与代答则用它筛选 Memory 的 finding、decision 等 `memory_type`。同一配置在普通查询可能返回空结果，在 SDK 却允许记忆；SDK 还加载整张记忆表构造 ID 白名单，无法区分不同集合中相同 ID 的原始文档和记忆。部分材料查询先取候选，再过滤类型，较新的不允许记录会挤掉较旧的允许记录。

现在 `allowed_memory_types` 只表示 `MemoryItem.memory_type` / `UserMemoryItem.memory_type` 的精确内容类型。保留自定义类型，不把 document 或 memory_item 自动转换为集合名。空列表表示类型不限，仍受原有身份、owner、scope、项目、生命周期和来源授权限制。`RetrievalProfile.result_types` 保留为独立的搜索结果类别条件，与内容类型取交集。存在内容类型限制时，普通/SDK/记忆上下文查询只允许匹配的 Memory，原始文档、聊天或其他无 `memory_type` 的搜索结果不能借用它通过。

现有绑定增加可空的 `type_policy_version`：`1` 表示上述内容类型语义，缺省/null 表示旧语义未确认。带非空类型列表的旧绑定一律暂不提供 Memory；没有类型限制的旧绑定保留原有行为。GET 暴露原配置及 null 标记，不重写旧记录。管理者核对内容类型后调用原 PUT，即可确认；服务端在当前授权写事务中设置 `1`，保留原 ID/创建时间，不信任请求指定的 Agent 身份、时间或语义版本。不存在自动猜测类型或后台放宽旧策略的迁移。内部直接构造受限绑定时同样必须显式给出 `type_policy_version=1`。

重新保存示例（沿用已有登录/服务端认证，省略凭据）：

```http
PUT /api/agents/<agent_id>/memory-binding
Content-Type: application/json

{
  "agent_id": "<agent_id>",
  "allowed_scopes": ["private", "project", "team_accepted"],
  "allowed_memory_types": ["finding", "decision"],
  "allowed_project_ids": ["<project_id>"],
  "max_results_per_query": 8
}
```

提交者应保留实际需要的 scope、项目和数量限制；示例不是批量迁移脚本。旧值若为搜索结果类别，需由管理者重新选择实际内容类型，不可机械原样迁移。

绑定模型提供一个有效类型集合及一个成员判断，所有现有消费者复用：普通查询、SDK Retrieval、MemoryContext 的普通召回/池、事实准备与重新校验、候选元数据、事务内引用/交付回执、流程选择、市场发布/匹配材料、代答选材及已交付答案的当前可用性。有效集合为 None 时类型不限，空集合时拒绝，不能用真假判断将空集合解释成不限。

普通与 SDK 搜索把内容类型条件放到已有 FTS MATCH、中文短词 LIKE 和 vector SQL 中，在 LIMIT、向量解码/打分、融合与输出预算前生效。条件同时匹配集合和 ID，SDK 不再扫描两张 Memory 集合构造 ID 列表。市场发布及无问题的直接匹配材料读取在 32 行候选上限前应用类型；代答在 200 行候选上限前应用类型。现有关键词、来源证明、内容检查和各自预算继续执行。市场 Task 标题仍按各自独立 Task 授权选择；内容类型限制不重新定义 Task 权限。

绑定语义撤销后，已准备的事实/流程步骤不能提交使用回执，候选不继续展示旧标题，已交付代答也不继续返回答案或引用。配置写入沿用 ADR 0039/0040 的同事务发布失效机制。确认状态与限制在数据库重开后保持一致。

升级前已生成、依赖私人 Memory 和未确认受限绑定的公开信号，也不能保留旧摘要。数据库初始化复用现有撤回/索引清理事务处理这些信号，保留原绑定配置；已确认配置、不限制类型的旧配置，以及仅使用独立 Task 材料的发布不会因这个迁移条件被撤回。

新增 **42** 个行为场景，其中绑定语义专项 **35** 个，其他场景覆盖事实/流程交付、候选可用性、代答及版本输入校验。最终 Python 3.12/3.13 的 18 个关联文件各 **375 passed**（240.77s / 242.06s），包含最后的旧公开摘要启动迁移。前端 **246 passed / 51 files**，OpenAPI 生成、生产构建/bundle、Ruff/diff 通过。

验收明细见 `docs/verification/2026-10-07-consistent-agent-memory-content-types.json`。本项不声称整个后端、真实模型质量、真实 embedding 容量或企业连接器验收完成；没有新增 UI 控件，也未进行浏览器验收。完整上下文优先级与预算、Source 通用版本/归档、连接器、过程复用、解析隔离及 Session/Runner 请求和交付治理继续按主方案推进。
