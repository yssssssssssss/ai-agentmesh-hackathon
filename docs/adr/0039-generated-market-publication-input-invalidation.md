# ADR 0039：自动协作摘要的私有依赖与来源变更撤回

状态：接受（原生发布依赖及索引撤回；外部来源、统一 SDK 治理继续开发）。

ADR 0037 已阻止模型等待期间发布过期内容，但提交成功后，普通 Memory 归档、修订、敏感级别/范围变化或 MemoryBinding 收紧仍会留下旧公共摘要。实际失败回归还发现：原生 Document 正文改变但版本未递增时，等待中的发布仍会成功；Task 所属 Thread 归档未撤回摘要；重开时索引回填会重新登记已撤回信号。

发布保存一个私有的 `market_publication_inputs` 关系投影。它依附现有唯一自动 BlackboardPost，不新增 Task、Memory、Runtime、事件总线或独立队列。行仅为 post ID、collection 和记录键，不保存正文。公开 metadata 仍只有 workspace/project 与 opaque publication hash，不包含私人 Memory/Document ID。最多八条选中 Memory、八条 Task，连同最多八个 Thread、64 个原生 Document 和六个身份/配置键，共最多 94 个唯一依赖；未选中候选不建立依赖。

当前 User/Project/PersonalAgent/MarketParticipation、MemoryBinding、模型定义、选中 Memory/Task/Thread 和版本化原生 Document 都成为依赖。可选绑定用 agent ID 作为逻辑键，模型用当前规范化 model ID；不存在的绑定/模型定义也登记该键，使首次创建限制仍能撤回旧摘要。原生 Document 完整记录 hash 和 Thread 记录加入发送前、提交时的快照证明。文档逐个计算 hash，不在快照中累计所有文档正文。依赖行、信号正文、FTS、向量待处理状态和发布审计一次提交；依赖写入失败不能留下无血缘摘要。

三个 SQLite records 变更触发器按索引查找依赖，覆盖 INSERT、实际 payload 改变的 UPDATE、DELETE，包括已有 raw SQL 写路径。匹配后在源写事务内先清理 FTS/向量/向量状态，再把自动摘要置为 withdrawn、清空正文，最后删除其私有依赖。索引删除失败会同时回滚源写和摘要撤回。删除向量状态继续使用现有内容 CAS 阻止晚 embedding 附着。无需 Provider 或模型调用。

撤回按已选中的记录依赖保守执行：该依赖的任何实际 payload 变更（包括时间/进度等元数据）都撤回，暂不维护另一套字段级语义规则。依赖触发器忽略完全相同、未选中/他人 Memory 及普通新资料 INSERT；已有资料编辑/撤回和遗忘命令仍可保守撤回本人聚合摘要，不受这个最小依赖集合限制。未来发布 tick 重新选择当前合格来源，不自动恢复旧正文。Post 的读取标记不会删除依赖；正文/公开身份变更或 Post 删除会丢弃旧依赖。本人退出、遗忘和资料撤回也清理该投影。

启动不猜测旧自动摘要的来源。使用确定性 `bb_signal_<user>` / `signal_<user>` 身份但没有私有依赖的旧摘要清空正文并撤回，随后可重新发布；人工帖身份保留。已撤回市场信号不参加 FTS/vector 回填。新依赖在数据库重开后继续有效。

相关持久化、发布、市场读取、匹配、遗忘及文档回归在 Python 3.12、3.13 各 **151 passed**。新增场景覆盖正文未递增版本、绑定首次创建/修改、模型定义首次创建、User/Project/Agent 撤权、Thread 归档、原始 UPDATE/DELETE、无关/相同写入、重开/重新发布、依赖写失败、索引清理失败及晚 embedding。验证记录见 `docs/verification/2026-10-06-generated-publication-input-invalidation.json`；全量快照及浏览器结果由该记录另行给出。

首次全量运行出现 Task 列表性能门槛失败。单独执行同样失败；剖析中三个列表及少量详情测量共读取权限规则 660 次，相关累计耗时 2.279 秒，三个列表总耗时 2.597 秒。现在每次列表请求只读取一次权限规则，作为该页动作提示的短期快照；单条视图同样复用已算出的管理权限。下一次请求和实际写事务继续重查，不建立全局权限缓存。原有集合读取改为既有只读连接并显式关闭，避免等待垃圾回收释放连接。

权限变更回归验证同一 Service 的下一次列表及时隐藏团队管理动作，本人编辑保留，旧提示不能授权实际关系写入。当前任务/权限/发布/匹配专项双版本各 **102 passed**。10,000 Task、50,000 审计事件、10,000 Memory、1,000 accepted team knowledge 的七次测量全部低于原 500ms 门槛：列表 p95 297.976ms、详情 483.819ms，另三项同样通过。数据见 `docs/verification/2026-10-06-generated-publication-project-operations-benchmark.json`。首次全量 Python 3.12 还出现一次五秒测试门卡未进入，单独执行通过；没有提高生产期限或测试门卡期限。最终全量 Python 3.12/3.13 各 **2,455 passed / 5 个既有 PyMuPDF 警告**，包含全部后端修改；前端 **241 passed / 50 files** 和构建/bundle、Ruff/diff 通过。Ego Lite 的隔离库实际保存资料 v4 后，旧信号和活动从市场消失，最终截图已检查；页面不再猜测未发布原因。

匹配回归的输入信号是人工编写的 fixture，现使用人工 ID，保留其重启去重和 helper 知识变更断言；没有把旧自动摘要伪造为已证明来源。这里没有给任意外部 Source、旧 SDK 历史或私人派生知识补造来源。通用 Connector 水位/删除/权限变更、scout 材料选择、完整 SDK 请求预算/实际交付、真实模型质量仍需后续切片。
