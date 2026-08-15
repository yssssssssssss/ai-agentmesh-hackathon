# AgentMesh Reference UI M/T Data Baseline

- 冻结日期：2026-08-14
- 功能分支：`feature/reference-ui-mt-data`
- 基线 HEAD：`cda36553444b6127ebf33f91d86d37f6121be062`
- 隔离 worktree：`.worktrees/reference-ui-mt-data`
- 参考前端：`/Users/heyunshen/Downloads/agentmesh-demo/`
- 实施前端：`agentmesh-demo/`

## 冻结结论

本轮改造在独立 worktree 和功能分支中实施。主工作区保持不变，后续页面 Agent 只在功能分支工作。参考 UI、公共 Presenter 接口和 AI 工作台分别冻结，任何并行任务改动冻结文件都必须停止当前波次并重新确认基线。

## Git 状态

### 主工作区

- 分支：`main`
- HEAD：`cda36553444b6127ebf33f91d86d37f6121be062`
- 已存在修改：
  - `docs/agents/issue-tracker.md`
  - `docs/superpowers/specs/2026-08-14-reference-ui-mt-data-design.md`
  - `docs/superpowers/plans/2026-08-14-reference-ui-mt-data-implementation-plan.md`

主工作区修改视为用户工作，不在功能分支执行时覆盖或清理。

### 功能 worktree

创建时仅包含两份已确认文档修改和 Wave 0 基线文件。功能代码尚未修改。

## 参考文件清单

参考文件校验清单位于：

`agentmesh-demo/e2e/reference-baselines/manifest.json`

清单包含 41 个参考文件：

- App、全局 CSS 和 Tailwind 配置。
- Layout 和共享 UI。
- DigitalSelf、Knowledge、Collaboration、Insights 页面。
- 四个页面的参考组件。
- `mockData.ts`。

每个文件记录相对路径、字节数和 SHA-256。后续任务只读取任务简报列出的参考文件。清单校验失败时不得继续实施。

## 参考截图

截图在 1512×944 浏览器视口捕获。浏览器工具将基线文件归一化为 1024×639 WebP。截图只用于模块顺序、布局、层级和代表性 Drawer 对比，不对动态文本和数值做像素断言。

已冻结：

- `digital-self.webp`
- `insights.webp`
- `collaboration.webp`
- `collaboration-drawer.webp`
- `knowledge-assets.webp`
- `knowledge-pending.webp`
- `knowledge-shared.webp`

截图的字节数、SHA-256、捕获视口和文件像素尺寸记录在 manifest 中。

## 运行环境

Wave 0 记录时：

- FastAPI：`127.0.0.1:8010`
- Vite：`127.0.0.1:5178`
- 参考 UI 临时 Vite：`127.0.0.1:5180`，截图完成后已停止
- Python 环境：复用主仓库 `.venv`
- Node 依赖：隔离 worktree 通过 `npm ci` 安装

## 基线验证

### 前端构建

命令：

```bash
npm --prefix agentmesh-demo run build
```

结果：通过。

- Vite 5.4.21
- 1735 modules transformed
- production bundle completed

### Workspace 聚焦回归

命令：

```bash
npm --prefix agentmesh-demo run test:e2e -- \
  e2e/workspace-mvp.spec.ts \
  --grep "creates, selects|shows pending immediately"
```

结果：2 passed。

覆盖：

- 创建和选择真实会话。
- optimistic pending 立即显示。
- 主对话自动滚动。
- `$` Skill 唤起。
- 消息和来源持久化。

## 冻结文件

### Wave 1 完成前由公共基础任务独占

- `agentmesh-demo/src/lib/presentation.ts`
- `agentmesh-demo/src/components/ui/DataSourceBadge.tsx`
- `agentmesh-demo/src/components/layout/**`
- `agentmesh-demo/src/components/ui/Tabs.tsx`
- `agentmesh-demo/src/components/ui/Modal.tsx`
- `agentmesh-demo/src/components/ui/Drawer.tsx`

### 全程冻结

- `agentmesh-demo/src/pages/Workspace.tsx`
- `agentmesh-demo/src/components/workspace/**`
- `agentmesh-demo/src/features/workspace/**`
- `agentmesh/routes/chat.py`
- `agentmesh/agents.py` 的聊天、Skill 和记忆检索协议

页面任务不得修改这些文件。Workspace 仅通过聚焦 Playwright 验证。

## Wave 2 文件所有权

- DigitalSelf Agent：`pages/DigitalSelf.tsx`、`features/digital-self/presenter*`、`components/digital-self/**`
- Knowledge Agent：`pages/Knowledge.tsx`、`features/knowledge/presenter*`、`components/knowledge/**`
- Collaboration Agent：`pages/Collaboration.tsx`、`features/collaboration/presenter*`、`components/collaboration/**`
- Insights Agent：`pages/Insights.tsx`、`features/insights/presenter*`、`components/insights/**`

除主会话整合外，页面 Agent 不得修改其他页面目录或共享冻结文件。

## 变更控制

以下情况必须停止当前波次：

- 功能分支 HEAD 被外部任务移动。
- 参考 manifest 校验失败。
- 冻结文件出现非本任务修改。
- Workspace 聚焦回归失败。
- 页面任务要求修改后端状态机才能继续。

停止后先更新基线、设计和任务简报，不在漂移状态上继续叠加。

## 提交策略

用户已授权创建本地基线 checkpoint。Wave 0 基线文件、设计规范和优化实施计划进入同一个本地提交，不推送远端。
