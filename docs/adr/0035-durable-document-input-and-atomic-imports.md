# ADR 0035：可恢复上传输入与原子文档导入

状态：接受（新上传闭环；解析器进程隔离、旧部分导入修复与企业同步另行验收）。

原 DocumentParseJob 仅保存文件名和进度，原始字节留在 Future 参数中；未解析时进程退出无法恢复。分段写入 Source、Document、摘要和片段也可能留下部分结果。新的上传将原始输入存入数据库旁的受控 `.inputs` 目录，Job 保存 opaque reference、原始 SHA-256、字节数、owner/workspace/project 与七天保留时间。单文件最多 20 MiB，文件以 0600 原子写入并 fsync；读取使用 dirfd、O_NOFOLLOW、常规文件/大小/hash 检查，引用不能改成任意主机路径。目录属于私有输入缓存，明确不代表 OS sandbox。

持久执行仍复用 DocumentParseJob 与 records，不新增工作流引擎。BEGIN IMMEDIATE 领取 claim，最多三次实际尝试；120 秒 lease 每 30 秒续期。当前 active uploader、active Project、同 workspace 和项目成员关系在领取、续期、最终写事务核验。当前 claim 和冻结输入 metadata 不一致时，旧执行者不能提交或使新执行者失败。两个服务实例共同操作 SQLite 的测试只产生一次解析与一次导入；这不代表应用整体已支持多进程部署。

解析在有界线程池中进行，Future 不再携带上传字节。解析后的 owner/scope 必须匹配 Job；正文最多 1 MiB，标题最多 512 字符，元数据最多 32 项，片段最多 2,200 项，超限明确失败而非静默截断。Source/Document 身份由 Job 稳定派生。Source、Document、私有摘要/片段、FTS/vector pending 状态与 completed Job 在同一事务提交，失败整体回滚，不向检索暴露半成品。导入文档不是第二套 Task/Review 真相，也不自动成为已审核团队知识。

原始缓存清理在提交后执行。清理失败保留 completed 与 durable cleanup_pending，不能回滚有效文档或使其片段失效。启动恢复每五秒有界发现 queued、到期 running 和待清理记录；活动 lease 不重复执行，队列满时保持 queued。过期上传输入被清理，历史成功状态保留，未完成记录标记 input_expired；不删除已经导入的文档正文。旧没有原始输入证明的未完成 Job 要求重新上传，已有部分 Document 的旧 Job 要求检查和修复，不冒造恢复证明。

本人重试使用 expected_version/command_id，版本检查、命令 hash 和重试回执同事务记录。重启和相同命令重复操作不会再创建文档/来源；其他用户和管理员不能替上传者重试。保留已有管理员读取文档/Job 的范围例外，增加当前项目成员与 workspace 检查，停止使用浏览器/旧 User 中的角色作为当前授权。Job 列表在 SQL 中限制当前授权/项目/owner 并分页，不读取全部历史。解析器错误只记录静态代码和异常类型，不保存或返回异常正文。

Knowledge 的资料导入面板可选择文件、显示等待/解析/完成/失败、当前尝试数、清理状态与本人重试；异步上传仅显示已保存，不能先宣称已导入。缓存/片段导入、事实学习、团队审核的状态各自保留。API 支持显式选择当前有权访问的项目。OpenAPI 类型随命令与状态生成。

验证覆盖数据库重开、启动发现、两实例竞争、权限在解析前/期间撤销、旧 worker 晚提交、lease 续期、原始输入篡改、事务中断、幂等重试/上限、管理员重试拒绝、分页、清理失败和过期缓存。Ego Lite 使用关闭全部 Provider 的独立临时数据库验证真实文本上传、损坏 PDF 失败、再次失败与刷新恢复；没有替代真实 OCR/企业 Provider 联调或答案质量验收。

崩溃发生在文件落盘但 Job 创建前的孤立缓存，由有界维护检查清理：每轮最多扫描 1,000 条目录 metadata、删除 100 项，严格限制到受控 opaque input 或临时写入名，七天以前且没有注册 Job 的文件才清理。symlink 只移除目录项，不跟随删除外部目标；注册输入与无关文件保留。当前 Job scope 与 input-reference 使用局部 SQLite 索引。

本切片不声称解析线程可以强制取消、存在 OS 资源隔离或完成 ZIP/PDF 恶意资源消耗防护。失去 claim 后可以阻止写入，无法撤销已经开始的解析。可选向量处理保持提交外的既有行为；启用向量的容量/Provider 当前授权验收仍待补齐。旧部分导入的人工修复、编辑后手动重导入路径与 SourceAuthority 外部同步水位继续处理。完整阶段 3/4/5 尚未完成。
