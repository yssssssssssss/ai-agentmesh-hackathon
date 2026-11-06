# AgentMesh 开发状态

## 当前分支收口（2026-11-06）

T01 / [PR #44](https://github.com/yssssssssssss/ai-agentmesh-hackathon/pull/44) 已合并至 main（`01e2d38755e8d6130d52aaae1d787c966f302f31`）。确切交付提交 `1c6a37d` 的权限专项和[完整 CI](https://github.com/yssssssssssss/ai-agentmesh-hackathon/actions/runs/42177076551) 均已通过。

当前 `feature/workspace-memory-closed-loop` 正常吸收该 main 基线，保留管理员目录兼容、项目与 Team 权限边界及既有记忆闭环实现。CI 增加与现有分支保护名称一致的后端汇总检查；Python 3.12/3.13 均成功时才通过。PR #45 / #46 仍按 T17 / 试点依赖顺序单独处理，尚未合并至 main。

后续业务开发目录保留为 `/Users/heyunshen/work/PROJECT/jdc/agentmesh-t01`。规格使用原工程根目录的 `AGENTMESH_DEVELOPMENT.md`；业务动态进度见活动目录的 [DEVELOPMENT_STATUS.md](../agentmesh-t01/DEVELOPMENT_STATUS.md)。

## 原工程基线记录（2026-10-10）

**基线变更（2026-10-10，用户授权）：** 原工程不再保留未提交源码。原 `5a7e7c5` 上的 126 项改动和 285 项未跟踪条目已分层提交，并合并 `origin/main`（`fed741b`）。旧的 `git diff HEAD --binary` SHA-256 `1ad64180…` 不再适用。合并前状态保留在本地分支 `backup/pre-main-merge-20261010`。运行数据 `data/` 与交接目录 `AgentMesh_Handoff_PR44/` 改为 gitignore，未删除。

## T01 历史验证记录（2026-10-09）

以下保留 T01 当时的兼容范围、验证证据和工作记录。此处的历史 Git 状态、远端检查及运行进程记录以当时日期为准；当前交付状态见上方 PR 链接。

更新时间：2026-10-09 11:33（Asia/Shanghai）。

### 当前工作

- 阶段：S0；工作项：T01 / PR #44 管理员 Workspace 目录兼容回归。
- 工作项状态：VERIFIED；本地交付状态：LOCAL_VERIFIED。本轮停在阶段检查点。
- 唯一活动源码目录：`/Users/heyunshen/work/PROJECT/jdc/agentmesh-t01`。
- 工作分支：`fix/t01-admin-workspace-compat`。
- 基线：`5fe161b5697ea00fa2fdb3444da801db601007c7`，来自本轮实际 fetch 的 `origin/fix/s0-t01-read-visibility`。
- T01 代码、测试、CONTEXT 和首轮状态记录的本地提交：`8ec017a3ede4f6c9e26836e004f3593f9a788e42`。
- 开发规格：用户提供的 `AGENTMESH_DEVELOPMENT.md` 原文副本已放在活动目录，与原工程相同；副本保留未跟踪，不纳入 T01 修复提交。
- 本地 Codex 统一负责分析、实现、测试、失败修复和记录。旧交接包的云端修复/本地回传分工已取消。
- 未执行推送、合并、部署、保护规则修改、真实数据破坏或付费模型调用。

### 原工程保护与环境

- 原工程仍为 `feature/workspace-memory-closed-loop` / `5a7e7c5d101df208b475ce696deed38150b9115a`。
- 原工程 126 项已跟踪改动保留；本轮前后 `git diff HEAD --binary` 的 SHA-256 一致：`1ad6418007d3a0d8cb91d079038e226b828390f862c56874500dfe1b49d1fb2b`。
- 原工程未跟踪条目由 284 增为 285；本轮仅新增指向此文件的 `DEVELOPMENT_STATUS.md`，未迁移、覆盖或提交历史工作。
- 原 `.env` 和数据库未用于本轮检查或运行。测试使用 conftest 的临时 SQLite；运行数据库为 `/Users/heyunshen/agentmesh-local/t01/state/demo.sqlite3`，仅含独立演示数据。
- 活动 worktree 单独安装 `.venv` 和 frontend dependencies，未修改依赖声明或 lockfile。后端沿用既有验收环境的版本约束，没有借权限修复升级框架。
- 实际执行版本：Python 3.12.7；命令包装器子进程 Node v26.7.0 / npm 11.19.0。远端 Node 20 / Linux 环境未由此次 Mac 本地检查替代。
- 本地命令包装器：`/Users/heyunshen/agentmesh-local/t01/run.py`，禁用 dotenv、真实 Provider、Embedding、O2、OAuth 和自动执行 worker，设置隔离数据库。

### 完成内容与权限边界

1. 在未修改的 PR 基线上复现原管理员创建/持久化/目录读回失败；同一轮原 49 项权限检查通过。
2. 项目列表增加第 20 章的窄兼容分支：仅管理员显式查询另一已存在 Workspace，且 `member_ids` 明确包含该管理员时，返回管理目录。
3. 默认/当前 Workspace 保留原权限及旧空成员开放语义；其他 Workspace 的空成员项目和非成员项目不补展示。
4. 普通用户/组长跨 Workspace 仍为 404；不存在的 Workspace 即使含孤立项目成员记录也为 404。撤销成员后，立即及重开 SQLite 后均不可列出。
5. 目录读回不授予跨 Workspace 的项目详情、任务、活动、知识、搜索或 Agent 上下文访问，Team 规则保留。
6. 原管理员测试及原 49 项断言未删除、跳过或削弱；在既有 `tests/test_read_visibility.py` 复用夹具增加 18 项边界案例，为跨 Workspace 项目构造真实 Workspace。
7. 更新 `CONTEXT.md` 的兼容说明。业务改动仅在 `routes/workspace.py`；无 schema、迁移、全局 Store policy、角色体系或前端业务变更。

### 本轮真实结果

日志目录：`/Users/heyunshen/agentmesh-local/t01/logs/`。以下均为本轮实际执行，没有用历史结果替代。

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 原管理员用例 + 原 49 项权限复现 | **1 failed / 49 passed**；目录响应缺少 `items` | `baseline-t01.log`；修复前 |
| 新增管理员目录正向用例，修复前 | **1 failed**；404 而非 200 | `catalog-red.log` |
| 原管理员 + 新正向用例，修复后 | **2 passed** | `catalog-green.log` |
| 原管理员、原 49 项权限及首批新边界 | **67 passed** | `t01-focused.log` |
| 后补的 Agent 上下文边界 | **1 passed** | `context-gate.log`；也包含在完整回归中 |
| 完整后端（排除需前端构建的路由文件） | **1936 passed / 6 skipped / 0 failed**；497.87 秒 | `backend-full.log`；原管理员和全部新增边界均执行 |
| 前端托管路由 | **6 passed** | `frontend-routes.log` |
| 全仓 Ruff、改动空白检查 | **PASS** | `ruff.log`；`git diff --check` exit 0；新增上下文测试后 Ruff 再检查通过 |
| API 类型生成与生成文件差异检查 | **PASS；无 schema.ts 差异** | `api-types.log`；`git diff --exit-code` exit 0 |
| 前端单测 | **33 files / 198 tests passed** | `frontend-tests.log` |
| 前端类型检查、生产构建 | **PASS** | `frontend-build.log`；最大 JS bundle 320326 / 500000 bytes |
| 本轮 Ego Lite 浏览器冒烟 | **PASS** | `browser-smoke.log`；登录、Tasks/Knowledge/Collaboration、深链接刷新、管理员切普通成员 |
| 真实本地会话的管理员创建/目录/业务边界 | **PASS** | 健康/创建 Workspace/创建项目/目录均 200；跨 Workspace 详情 404；切普通成员后目录 404、管理员入口移除 |

6 项跳过来自既有 `test_wiki_skill_inventory.py` 的外部 `2C-DesignWiki` 语料缺失条件；本轮没有新增 skip。第三方 SWIG 弃用警告和既有前端 SSR `useLayoutEffect` 警告保留。

仅执行一轮必要完整后端回归。定向红/绿检查用于复现和修复；未重复扩大到无关评估或真实模型验证。

### 远端状态与未测项

- 本轮只读查询：PR #44 仍 open / draft、未合并，远端 head 为基线 `5fe161b...`；后端 CI **failure**，其余四项 success。远端既有交付状态仍为 **BLOCKED_CI**。
- 失败记录：[Backend clean install, Ruff, pytest](https://github.com/yssssssssssss/ai-agentmesh-hackathon/actions/runs/37761712458/job/113259851190)。本地修复尚未推送，该记录未被此次本地通过替换。
- 新本地提交的远端 CI：**NOT_RUN**；当前未获推送授权。GitHub / main 尚未包含本地修复，PR 未通过全部检查。
- 本轮完整 Playwright suite：**NOT_RUN**；无前端改动，采用当前隔离实例的 Ego Lite 冒烟。旧 head 的远端 Playwright success 不能归到新本地代码。
- 真人产品体验：**PARTIAL**（用户截图及文字反馈）。M03 默认项目列表、M04 管理员跨 Workspace 目录读回符合预期；M05 的项目详情拒绝符合预期，知识拒绝尚未确认。页面、刷新及账号切换仍待确认，没有标记整体人工验收通过。
- 真实 Provider、付费模型、OAuth/O2 实际系统、外部 Wiki 语料、模型质量评估、部署验收：**NOT_RUN**，不在本轮 T01 范围。S0 其他工作项及整个产品没有因此完成。

### 本地运行与集中体验

修复后的同源 React + FastAPI 已运行在 **http://localhost:18011**，绑定 `127.0.0.1`，服务 PID `82406`。旧验收服务 `18010` 保留；本次体验使用 `18011`。

需要重启时，先确认端口现有进程，不要重复启动；在活动目录执行：

```bash
cd /Users/heyunshen/work/PROJECT/jdc/agentmesh-t01
/opt/homebrew/bin/python3.12 /Users/heyunshen/agentmesh-local/t01/run.py demo .venv/bin/python -m uvicorn agentmesh.app:app --host 127.0.0.1 --port 18011
```

日志为 `logs/demo.log`，停机用启动终端 Ctrl+C。无需读取原 `.env`、复制原数据库或调用外部模型。

用户只需集中体验：

完整可勾选清单：[T01_ACCEPTANCE_CHECKLIST.md](T01_ACCEPTANCE_CHECKLIST.md)。已按用户反馈勾选 M03/M04，M05 仅详情拒绝已确认；其余保留待验收。`/api/...` 返回 JSON 是接口契约，实际页面从 `http://localhost:18011` 进入；本轮未新增可视化 Workspace/项目管理页。

1. 打开 `http://localhost:18011`，选择「以平台管理员身份进入」，查看任务中心、我的知识、协作网络，并刷新一次。
2. 退出后选择「以何云深身份进入」，确认身份切换且管理入口消失。`T数据` 来自隔离演示库；`M数据` 为既有参考展示。

管理员创建后的目录回读和跨 Workspace 拒绝已由 Codex 在真实本地会话中完成，无需用户手工执行 API。目录兼容不代表跨 Workspace 业务协作。

### 唯一下一动作

停在 **T01 LOCAL_VERIFIED** 检查点。用户在本地说「继续」后，从此 worktree 推进 **T02：成员创建后的项目加入**，先分析管理员建号、注册/OAuth 初始化及默认项目访问，保留授权项目边界。

T03/T04 等按规格依赖顺序推进；原 Workspace 记忆分支在 T17 单独吸收。远端推送、合并和部署等待相应授权，普通本地修改无需逐条确认或云端回传包。
