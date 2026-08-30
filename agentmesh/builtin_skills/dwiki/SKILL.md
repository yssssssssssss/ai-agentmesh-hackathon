---
name: dwiki
description: 'Design Wiki 设计工作流 CLI。查询 wiki 组件索引、校验 design.md、统计库状态、 读取 Relay 设计稿、准备 Coding 同步分支。覆盖设计前/中/后三阶段，人可终端用、 AI agent
  可通过 --json 调用。

  '
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/tools/dwiki/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
  short-description: Design Wiki 设计工作流 CLI。查询 wiki 组件索引、校验 design.md、统计库状态、 读取 Relay 设计稿、准备 Coding 同步分支。覆盖设计前/中/后三阶段，人可终…
disable-model-invocation: true
---

# dwiki

## Summary

京东 Design Wiki 主仓（2C-DesignWiki）的工作流 CLI。把仓库的高频能力封装成子命令：
检索组件、校验规范、库统计、Relay 读取、Coding 同步准备。所有命令支持 `--json`
输出，供 AI agent 解析。数据源锁定主 wiki 仓 `jd-design-system-md-v16/`。

## When To Use

- 设计前：查历史组件/案例 → `dwiki search`
- 设计中/后：提交前校验 design.md → `dwiki validate`
- 汇报/盘点：库有多少 bundle、分类分布 → `dwiki report`
- 读设计稿：拿 Relay 节点上下文/截图 → `dwiki relay`
- 同步内网：把本地工作准备成 Coding 分支 → `dwiki sync-coding`

## Capabilities

### search
Type: read
Command: `dwiki search <关键词> [--detail] [--json]`
Inputs: 关键词（1-N 个，空格分隔）；--detail 显示路径/Relay/owner
Outputs: 分级（强/中/弱相关）的组件列表；--json 返回 {results:[{slug,path,relayNode,relevance}]}
Safe Example: `dwiki search 商卡 --json`

### new
Type: write（本地生成文件）
Command: `dwiki new <slug> [--level <l>] [--title <中文名>] [--dir <相对目录>]`
Inputs: kebab-case slug；--level 默认 component-business；--dir 默认 foundations/_new/<slug>
Outputs: bundle 五文件骨架（design/spec/variants/behaviors/CHANGELOG）+ frontmatter 占位。目标已存在则拒绝
Safe Example: `dwiki new my-card --title 我的卡片 --json`

### backlinks
Type: read
Command: `dwiki backlinks <slug> [--json]`
Inputs: 组件 slug 或相对路径
Outputs: 引用该组件的 design.md 列表。透传 find-backlinks.sh
Safe Example: `dwiki backlinks product-card-container --json`

### validate
Type: read
Command: `dwiki validate [design.md路径] [--json]`
Inputs: 可选单文件路径，不传=全仓校验
Outputs: 校验报告 + 退出码（0 通过/1 有错）。透传 .agents/shared/bin/validate.sh
Safe Example: `dwiki validate --json`

### index
Type: read（只读 dry-run，禁 --write）
Command: `dwiki index [--json]`
Inputs: 无
Outputs: INDEX.md 该加/改哪些行的 dry-run 预览。透传 sync-index.sh（绝不写回）
Safe Example: `dwiki index --json`

### report
Type: read
Command: `dwiki report [--json]`
Inputs: 无
Outputs: bundle 总数、按分类/level/status 分布
Safe Example: `dwiki report --json`

### portal
Type: write（--build 时跑构建）
Command: `dwiki portal [--build] [--json]`
Inputs: 不带参=诊断 site 状态；--build=跑 site 的 build:full 产出 site/.build
Outputs: 站点构建产物路径。复用 site/ 成熟工程，不重造渲染
Safe Example: `dwiki portal --json`

### doctor
Type: read
Command: `dwiki doctor [--json]`
Inputs: 无
Outputs: 环境自检（node/zero 客户端/jd remote/数据源/validate.sh）
Safe Example: `dwiki doctor --json`

### relay
Type: read
Command: `dwiki relay <status|context|shot|export> [node|url] [--json]`
Inputs: 子命令 + Relay nodeId 或 URL。依赖 Zero 桌面客户端在跑且登录
Outputs: 客户端状态 / 设计上下文 / 截图链接。透传 zero CLI
Safe Example: `dwiki relay status --json`

### sync-coding
Type: write（半自动，停在 push 前）
Command: `dwiki sync-coding [--prepare] [--json]`
Inputs: 不带参=只诊断；--prepare=建 jd-sync 分支+重写身份
Outputs: 待同步 commit 清单 + MR compare URL。**绝不自动 push/建 MR**
Safe Example: `dwiki sync-coding --json`

## 约束

- Relay 能力硬依赖 Zero 桌面客户端（`zero` CLI）在跑并登录。
- sync-coding 只准备分支，push 与建 MR 需人工在 review diff 后手动执行。
- 数据源是主 wiki 仓，不覆盖商详大脑 design-kb。
