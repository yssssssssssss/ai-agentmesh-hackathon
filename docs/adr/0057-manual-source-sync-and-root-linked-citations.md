# 0057：手动来源同步与原始来源关联引用

日期：2026-10-07。状态：首条真实读取链路可用；完整连接器生命周期继续实施。

外部来源需要稳定身份，而工具引用需要绑定具体 Run。直接给同一个来源改写 Run/Skill 会与不可变身份及外部唯一索引冲突。现有 Source 增加可选 `SourceOriginV1`，Run 引用保存原始 Source ID、revision、完整来源摘要和观察正文摘要。原始来源保持独立身份；引用检查和合成重新核对它的当前内容、生命周期及实际项目权限。无 origin 的旧引用继续省略字段，旧内容摘要不重算。

新增 `connector_sync`，复用 Source、Document、现有检索索引和 SQLite 写事务。`ConnectorSyncCursorV1` 按 owner/workspace/project/provider/namespace 隔离，记录配置摘要、逻辑版本、下一页位置、最近成功页和最近完整扫描时间。HTTP 入口只接受预期游标版本，资料目录、仓库及凭据由服务端配置。读取前和提交时检查实际主体、项目及配置绑定；并发旧游标不能提交。

每次只读取一页，外部读取期间不持有 SQLite 写事务。Source 版本、文档镜像、检索投影、旧导入片段失效和游标在同一写事务提交；来源审计失败整体回滚。相同观察不重写来源或文档。用户撤回的文档不会因外部更新恢复。

`RepoDocsReader` 读取配置目录中的 UTF-8 Markdown/TXT/RST。目录扫描最多 1,000 个条目；单文档最多 1 MiB，每页默认 5 份、最多 20 份。通过目录文件描述符和 `O_NOFOLLOW` 读取，拒绝符号链接文件和非普通文件；FIFO 使用非阻塞打开，避免等待写入者。这是受限目录读取，不是部署级操作系统沙箱。

`GitHubIssuesReader` 使用固定 GitHub API 主机和配置仓库的 GET 地址，每页最多 20 条，排除返回集合中的 PR。观察正文是包含标题、正文、状态、更新时间、标签和负责人登录名的规范化 Issue JSON；版本包含更新时间和该观察正文摘要，不把它声称为完整 HTTP 响应原文。关闭的 Issue 保留其观察状态，不改变本地 Task。公开仓库无需 token；私有 token 留在服务端，配置摘要只包含声明的凭据绑定版本，权限主体变化时由运维更新该版本。

实际 GitHub 响应使用 `/repositories/{id}/issues` 的 canonical Link，同时携带 page 和不透明 after cursor。读取器验证主机、路径形状和参数，只提取页位置；后续请求仍构造配置仓库的固定地址，不跟随 Link 地址或重定向。响应最多 2 MiB，错误只返回静态代码。真实读取发现并修复了初始仅支持 slug/page 的假设。

公开入口：

- `GET /api/projects/{project_id}/connectors`：当前授权项目的配置连接器及本人游标。
- `POST /api/projects/{project_id}/connectors/{provider}/sync`：`{"expected_version": 0}` 开始；继续提交上次返回的版本读取下一页。
- 下一页为空后再次同步会开始新扫描，内容按版本去重。镜像进入现有资料读取、显式导入和 document_search 流程；没有自动确认事实、共享私人资料或推进 Task。

隔离后端真实读取验收同步了当前仓库 `docs/agents/` 的 3 份文档及 GitHub 的 9 个 Issue，GitHub 共 3 页；全部观察正文摘要一致。凭据未读取或输出，现有服务端口和业务数据库未改动。该结果证明真实资料读取和本地镜像提交，不证明真实 LLM 回答质量或企业团队试点通过。

新增功能检查 30 passed / 3.86 秒；13 组直接关联回归共 295 passed / 54.45 秒，Python 3.13。API 类型生成、前端构建及 bundle 检查通过。根据用户对过度验证的反馈，本轮没有重复大范围双版本回归；完整回归集中到阶段验收。结果、初次真实读取失败和日志摘要见 `docs/verification/2026-10-07-manual-source-sync.json`。

仍待完成：增量 since 水位、完整扫描遗漏处理、Provider ACL/删除发现、持久失败状态、连接器禁用后的投影失效、游标配置迁移/重置、后台限速和取消，以及前端同步操作。现有观察不能当作 Provider 实时状态；变化时由已实现的来源观察命令使引用失效，但连接器尚未自动发现全部变化。完整 Session/Runner/Artifact 血缘及模型质量验收继续开发，阶段 3–5 保持未完成。
