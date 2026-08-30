---
name: joyspace-docs
description: JoySpace 文档读写与本地文档发布通用技能。用于读取/总结 JoySpace 页面、创建 JoySpace 文档、把本地 PRD/TRD/Markdown 上传发布到 JoySpace、按模板克隆填空、发布评论、搜索团队/目录，以及在
  ai-native 其他 PRD/TRD skills 生成本地文档后继续发布到 JoySpace。用户提到“上传 TRD 到 JoySpace / joyspace / JoySpace 文档 / 写入 JoySpace / 创建在线文档
  / 读取 JoySpace 链接 / 发布到 joyspace / 同步到 JoySpace”时必须使用。
metadata:
  owner: ai-native
  version: 0.1.0
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/local-life/Skill/joyspace-docs/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
  short-description: JoySpace 文档读写与本地文档发布通用技能。用于读取/总结 JoySpace 页面、创建 JoySpace 文档、把本地 PRD/TRD/Markdown 上传发布到 JoySpace、按模板…
disable-model-invocation: true
---

# JoySpace Docs

统一入口：MCP 工具 `joyme_joyspace`，通过 `action` 参数路由。

## 适用范围

- 读取 JoySpace 页面基础信息、正文 JSON，并总结或转成本地材料。
- 创建普通文档、表格、多维表、PPT、白板等 JoySpace 页面。
- 把本地 Markdown/TRD/PRD 发布成 JoySpace 普通文档。
- 基于已有模板克隆并按字段填空。
- 搜索团队、目录、文档，或给页面发布评论。

不处理“把 JoySpace 页面完整下载成本地 Markdown + 图片本地化”的场景；这类需求使用 `joyspace-doc-to-md`。

## 前置检查

1. 优先确认当前工具列表是否已经暴露 `joyme_joyspace`。
2. 若工具不可用，先自动做本地自查，除非缺少权限或文件不存在，不要让用户自己提醒：
   - Codex：检查 `~/.codex/config.toml` 是否存在 `[mcp_servers.joyspace]`，并检查 `~/.codex/skills/joyspace-docs/SKILL.md` 是否存在。
   - Cursor：检查项目 `.cursor/mcp.json` 或用户说明中的 Cursor MCP 配置是否包含 `joyspace`。
   - Claude：检查 `.mcp.json` 或 Claude MCP 配置是否包含 `joyspace`。
   - 检查 `joyspace-mcp` 是否在 PATH，或是否可用 `npx -y -p @jd/h2o-joyspace-mcp -c joyspace-mcp`。
3. 如果本地已配置但当前会话仍没有 `joyme_joyspace`，明确结论为“当前客户端需要重启/开启新会话加载 MCP”，并保留已经定位好的文件、标题和保存位置；不要反复要求用户解释同一问题。
4. 如果本地未配置，按 `references/mcp-setup.md` 给出对应客户端的最小配置；用户要求“帮我安装/配置”时，直接修改本机配置并同步本 skill 到对应全局 skills 目录。
5. 若用户要创建或发布文档，必须先确认保存位置：`team_id`、`folder_id` 或一个可解析的 JoySpace 空间/目录链接。缺保存位置时只问保存位置，不再重复询问 MCP 背景。
6. 只有用户明确说“私人空间/我的空间”时，才使用 `team_id=root, folder_id=root`。

## 自动恢复与少打扰规则

- 用户说“上传/发布到 JoySpace”时，先定位本地文档并推导标题，即使 MCP 暂不可用也要完成这些准备工作。
- MCP 不可用时，禁止把问题停留在“没有工具”一句话；必须给出当前状态：
  - 文档是否已找到
  - 标题是什么
  - 保存位置是否缺失
  - MCP 是未配置，还是已配置但需要重启
- 同一轮里如果已经判断为“已配置但当前会话未加载”，后续不要继续搜索工具；直接提醒重启客户端/新开会话。
- 重启后用户再次说“继续上传”时，复用上次的文档路径和标题；只补缺失的保存位置，然后调用 MCP。
- 登录态失败时，优先建议或执行 `joyspace-mcp-refresh`，不要改用裸 API。

## 操作原则

- 所有 JoySpace 文档能力必须经 `joyme_joyspace` 调用，不直接请求 JoySpace API。
- 不使用 `fill_doc_routing`；该能力已移除。
- 写入普通文档时，内容必须在同一次 `create_doc_routing` 调用中提交。
- 不确定内容留空，不写“待补充/待确认”。
- 涉及评审区、checklist、上线检查等默认留空，除非用户明确给出内容。
- 不在日志、文档、commit 中暴露 cookie、token、storage state。

## 链接与位置解析

- `/teams/<team_id>/<folder_id>` -> `team_id=<team_id>`, `folder_id=<folder_id>`
- `/teams/<team_id>/root` -> `team_id=<team_id>`, `folder_id=root`
- `/teams/<team_id>` -> `team_id=<team_id>`, `folder_id=root`
- `/documents/<folder_id>` -> `team_id=root`, `folder_id=<folder_id>`
- `/documents` -> `team_id=root`, `folder_id=root`，但仅限用户明确要求私人空间
- `/pages/<page_id>` -> `page_id=<page_id>`

如果只有空间名称或目录关键词，先用 `joyspace.search_team` 搜索团队/知识库，再让用户确认候选；目录内搜索 action 以 `../joyspace-official-full/references/actions.md` 当前版本为准。

## 常用工作流

### 读取 JoySpace 文档

1. 从链接提取 `page_id`。
2. 调用 `get_page_basic_info` 确认标题、类型、权限与页面状态。
3. 普通文档调用 `get_normal_json_content`；表格/多维表读取规则按 `../joyspace-official-full/references/actions.md`。
4. 输出结论时给出页面标题、链接、读取到的证据和无法读取的原因。

调用形态：

```json
{
  "action": "get_page_basic_info",
  "page_id": "<page_id>"
}
```

```json
{
  "action": "get_normal_json_content",
  "page_id": "<page_id>"
}
```

### 上传本地 TRD/PRD/Markdown 到 JoySpace

触发示例：“把 TRD 上传到 JoySpace”“发布 `TRD-FE.md` 到 joyspace”“把这个技术方案创建成在线文档”。

1. 定位本地文件；若用户只说“TRD”，优先在当前 feature 目录找 `frontend/TRD*.md` 或 `TRD*.md`，其次扫描 `features/**/frontend/TRD*.md`。
2. 读取文件内容，保留 Markdown 结构；不要把文件路径直接传给 `create_doc_routing`。
3. 推导标题：优先文件内一级标题，其次文件名，最后用用户给的标题。
4. 确认保存位置；缺少 `team_id/folder_id` 时先问用户。
5. 调用 `create_doc_routing` 创建普通文档，`content` 传 Markdown 正文。
6. 创建后用 `get_page_basic_info` + `get_normal_json_content` 回读校验：标题存在、正文非空、关键标题可检索。
7. 返回 JoySpace 链接、标题、回读校验结果和本地来源文件。

调用形态：

```json
{
  "action": "create_doc_routing",
  "team_id": "<team_id>",
  "folder_id": "<folder_id>",
  "title": "<title>",
  "content": "# <title>\n\n..."
}
```

### 基于模板创建 TRD

当用户要求“按 JoySpace 模板生成/上传 TRD”时：

1. 读取模板：`get_normal_json_content(template_page_id)`。
2. 在模板 JSON 中按字段原位填空。
3. 不传 `source_page_id`，直接用 `create_doc_routing` 提交填好后的整包 JoySpace Slate JSON 字符串。
4. 回读新文档并校验关键字段。

注意：`source_page_id` 克隆链路只接受“键: 值”结构化文本，不接受整包 `[...]` Slate JSON。两条链路不能混用。

### 克隆模板并结构化填空

适用于简单模板复用：

````json
{
  "action": "clone_doc_routing",
  "source_page_id": "<template_page_id>",
  "team_id": "<team_id>",
  "folder_id": "<folder_id>",
  "title": "<title>",
  "content": "摘要: ...\n模块: ...\n方案流程图:\n```mermaid\nflowchart TD\n  A --> B\n```"
}
````

`content` 必须是“键: 值 / 键：值”多行文本，可附 Mermaid；不要传本地 Markdown 全文或整包 JSON。

### 创建其他类型文档

- 表格：`doc_type: "sheets"`
- 多维表：`doc_type: "table"`
- PPT：`doc_type: "ppt"`
- 白板：`doc_type: "board"`
- 思维导图：`doc_type: "mind"`
- 会议文档：`doc_type: "meeting"`

```json
{
  "action": "create_doc_routing",
  "doc_type": "sheets",
  "title": "<title>",
  "team_id": "<team_id>",
  "folder_id": "<folder_id>"
}
```

### 评论与协同

- 发布评论：`publish_comment`
- 搜索员工：`search_employee`
- 发送给联系人：`send_to_contact`
- 本地文件发送场景优先走文件上传/发送链路，不先创建普通文档。

## ai-native 串联约定

其他 skill 生成本地文档后，只要用户说“上传/发布/同步到 JoySpace”，转入本 skill：

- PRD：发布 `features/<feature>/prd/*.md`
- 前端 TRD：发布 `features/<feature>/frontend/TRD-FE*.md`
- 前端技术设计：发布 `features/<feature>/frontend/*前端技术设计*.md`
- 客户端 TRD：发布 `features/<feature>/client/TRD-CLIENT*.md`
- 客户端技术设计：发布 `features/<feature>/client/*客户端技术设计*.md`
- 测试用例：发布 `features/<feature>/frontend/TEST-CASES*.md` 或 `features/<feature>/client/TEST-CASES*.md`

发布成功后，若用户要求回写链接，写入对应 `features/<需求>/frontend/README.md`、`features/<需求>/client/README.md` 或 `implementation-*.md`；未得到用户明确要求时不主动改交付目录。

## 需要查阅的参考

- MCP 安装、配置、登录态刷新：`references/mcp-setup.md`
- action 参数细节：优先查 `../joyspace-official-full/references/actions.md`
- 表格细节：`../joyspace-official-full/references/sheets.md`
- 多维表细节：`../joyspace-official-full/references/aitable.md`

## 完成回报

低噪输出：

```text
已发布到 JoySpace：
- 标题：<title>
- 链接：<link>
- 来源：<local file 或 page_id>
- 校验：正文可回读 / 关键标题命中 <n>/<m>
```

如果失败，返回失败 action、关键错误、已确认的保存位置和下一步需要用户补充的信息。
