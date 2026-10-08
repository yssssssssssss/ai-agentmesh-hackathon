# T01 本地验收 Checklist

范围：管理员创建其他 Workspace 的项目后可以读回管理目录，项目、Team 和 Agent 的业务访问边界保留。
验证的源码提交：`8ec017a3ede4f6c9e26836e004f3593f9a788e42`。
活动目录：`/Users/heyunshen/work/PROJECT/jdc/agentmesh-t01`。
工程检查及进度的权威记录：[DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md)。

## 用户体验清单（约 5–10 分钟）

下列项目默认未勾选，表示等待用户体验，不代表工程检查失败。只需浏览器，不需要终端、数据库修改或真实模型调用。
本轮 Codex 已在隔离演示库创建「T01 本地目录验收」Workspace 和「T01 管理目录读回」项目；以下接口链接仅进行 GET 查询。
先在同一浏览器登录，再打开查询链接。API 页面显示 JSON 是正常行为。

- [ ] **M01：进入修复后的实例。** 打开 [http://localhost:18011](http://localhost:18011)，确认可以显示登录页或已登录页面。使用 `18011`；`18010` 是旧验收实例。
- [ ] **M02：管理员登录。** 如果当前是其他账号，先退出；选择「以平台管理员身份进入」。预期身份为「平台管理员」，侧栏有「管理控制台」。
- [ ] **M03：默认项目可用。** 打开 [默认项目列表](http://localhost:18011/api/projects)。预期 `items` 包含「618 家电会场首页改版」，不会混入下述跨 Workspace 的「T01 管理目录读回」。
- [ ] **M04：管理员目录读回成功。** 打开 [T01 管理目录](http://localhost:18011/api/projects?workspace_id=ws_7349cf873a30)。预期 HTTP 200，`items` 包含「T01 管理目录读回」，ID 为 `prj_4aebda39927c`，成员包含 `usr_admin`。这是本次修复的直接收益。
- [ ] **M05：目录可读不扩大业务权限。** 在管理员身份下打开 [该项目详情](http://localhost:18011/api/projects/prj_4aebda39927c) 和 [该项目知识](http://localhost:18011/api/memory?project_id=prj_4aebda39927c)。两者均应为 HTTP 404，正文 `{"detail":"Project not found"}`。这两项的拒绝是通过条件。
- [ ] **M06：当前项目上下文保持正常。** 返回 [任务中心](http://localhost:18011/tasks)，查看 [我的知识](http://localhost:18011/knowledge) 和 [协作网络](http://localhost:18011/collaboration)，刷新一次。预期登录保持、页面正常加载，当前项目没有被目录查询切换为「T01 管理目录读回」。
- [ ] **M07：账号切换生效。** 退出管理员，选择「以何云深身份进入」。预期身份变为普通成员，侧栏的「管理控制台」入口消失。
- [ ] **M08：普通成员边界生效。** 在普通成员身份下再次打开 [T01 管理目录](http://localhost:18011/api/projects?workspace_id=ws_7349cf873a30)。预期 HTTP 404，正文 `{"detail":"Workspace not found"}`；[默认项目列表](http://localhost:18011/api/projects) 仍可正常读取当前项目。

如果接口返回 `{"detail":"Authentication required"}` 等 401 响应，先在同一浏览器的 `localhost:18011` 登录再检查；不要把未登录的拒绝当作权限用例通过。
若 M04 没有上述项目或返回空列表，先记录为「未验证」，由 Codex 检查隔离演示数据；不可用 M05/M08 的 404 单独证明修复有效。

当前运行配置中任务中心为只读，页面已有 `T数据` / `M数据` 标识：`T数据` 来自此隔离演示库，`M数据` 为参考展示。此验收不触发 Agent 执行或付费模型。

## Codex 已完成的工程证据

以下勾选绑定上述源码版本和既有执行日志；本次编写清单没有重跑全量测试。

- [x] **修复前后对照成立。** 原管理员创建、持久化及目录读回用例修复前失败，修复后通过；原测试保留。证据：[修复前日志](/Users/heyunshen/agentmesh-local/t01/logs/baseline-t01.log)、[修复后日志](/Users/heyunshen/agentmesh-local/t01/logs/catalog-green.log)。
- [x] **原权限检查保留。** 原 49 项项目/Team/记忆权限检查通过，断言没有削弱。证据：[定向回归](/Users/heyunshen/agentmesh-local/t01/logs/t01-focused.log)。
- [x] **新增 18 项边界案例通过。** 包括组长跨 Workspace 拒绝、真实 Workspace 夹具、不存在 Workspace、非成员及空成员项目、默认上下文保持、成员撤销及重开数据库后的拒绝、业务读取和 Agent 上下文拒绝。证据：[测试源码](tests/test_read_visibility.py)、[Agent 上下文日志](/Users/heyunshen/agentmesh-local/t01/logs/context-gate.log)、[完整后端日志](/Users/heyunshen/agentmesh-local/t01/logs/backend-full.log)。
- [x] **必要回归完成。** 后端 1936 passed / 6 skipped，前端托管路由 6 passed，前端单测 198 passed；Ruff、API 类型无差异和生产构建通过。6 项跳过因缺少既有外部 Wiki 语料，详见进度记录。
- [x] **真实运行实例验证完成。** Ego Lite 已验证登录、页面、刷新及账号切换；真实本地会话创建 Workspace/项目后目录 200，项目详情 404，切普通成员后目录 404。证据：[浏览器日志](/Users/heyunshen/agentmesh-local/t01/logs/browser-smoke.log)。

## 未验证范围

完整 Playwright suite、真实 Provider/模型效果、外部 Wiki 语料、新本地提交的远端 CI 和部署验收均为 **NOT_RUN**。
本地修复尚未推送；此前记录的远端旧提交后端 CI 为 failure。这里的勾选不代表 GitHub CI、S0 全阶段或整个项目完成。

## 通过判定与异常记录

M01–M08 均符合预期，可记录「T01 用户体验通过」。其中 M04 的成功和 M05/M08 的拒绝必须同时成立。
其他工程边界已有证据，用户无需重复构造测试数据或重跑 1936 项测试。

发现异常时记录以下内容即可，由本地 Codex 修复：

```text
清单项：M__
账号角色：管理员 / 普通成员
访问地址：
实际结果：页面文字、JSON 或 HTTP 状态
```

用户体验结果尚未确认；动态结论由 Codex 更新到 `DEVELOPMENT_STATUS.md`。后续开发工作为 T02「成员创建后的项目加入」。
