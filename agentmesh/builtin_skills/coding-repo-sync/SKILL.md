---
name: coding-repo-sync
description: '通过 Coding 平台 REST API v4 对 JD Coding (xingyun.jd.com/coding.jd.com) 仓库执行 git 操作：

  创建分支、提交文件（新建/更新/删除）、查看分支列表、读取文件内容、发起合并请求。

  当用户需要向 Coding 仓库推送代码、同步文件、创建分支、提交变更、发起 MR 时使用此 skill。

  即使用户只说"提交到仓库"、"推送到 Coding"、"同步到远程"也应触发。

  也适用于完全不了解 git 的新手——会从环境检测、账号注册、Token 生成开始引导。

  '
metadata:
  short-description: JD Coding 仓库操作（从零开始到提交 MR 全流程引导）
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/search-recommend-foundation/skills&tools/coding-repo-sync/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
disable-model-invocation: true
---

# Coding Repo Sync

帮助任何人（包括完全不懂 git 的小白）完成 JD Coding 仓库的克隆、提交、合并全流程。

## 核心理念

这个 skill 分两层：
1. **新手引导层**：检测用户环境，手把手引导完成前置准备
2. **操作执行层**：通过 REST API v4 执行实际的仓库操作

## 第一步：判断用户状态

收到用户请求后，按顺序检查以下条件，缺哪个就从哪步开始引导：

| 检查项 | 检测方式 | 缺失时的动作 |
|--------|---------|-------------|
| git 是否安装 | 终端执行 `git --version` | 引导安装 git（见下方） |
| 是否有 Coding 账号 | 询问用户 | 给出注册/登录链接 |
| 是否是仓库成员 | 询问用户或尝试 API | 引导联系管理员添加 |
| 是否有 API Token | 询问用户 | 给出 Token 生成步骤 |
| 本地是否已克隆 | 检查目标路径是否存在 `.git` | 执行克隆 |

## 第二步：环境准备引导

### 2.1 安装 Git（如未安装）

**macOS：**
```bash
# 方式 1：Xcode Command Line Tools（推荐，大部分 Mac 已有）
xcode-select --install

# 方式 2：Homebrew
brew install git
```

**Windows：**
- 下载地址：https://git-scm.com/download/win
- 安装时保持默认选项即

### 2.2 Coding 平台账号

- **登录地址**：https://xingyun.jd.com/codingRoot
- 使用京东 ERP 账号直接登录（域账号），无需额外注册
- 首次登录后即自动创建 Coding 账号

### 2.3 成为仓库成员

如果用户不是目标仓库的成员，需要：
1. 联系仓库管理员（Master 角色）将其添加为成员
2. 权限至少需要 **Developer**（可推送代码）
3. 告知用户具体的仓库成员管理页面：
   `https://xingyun.jd.com/codingRoot/{group}/{project}/settings/members`

### 2.4 生成 API Token

这是最关键的一步逐步引导用户：

1. 打开链接：**https://xingyun.jd.com/codingRoot/profile/settings/token**
2. 点击「生成新令牌」
3. 名称随意填写（如 "JoyCode API"）
4. 权限勾选 **api**（包含所有读写权限）
5. 点击创建，**立即复制保存 Token**（页面关闭后无法再次查看）

> 提示用户：Token 就像密码，请妥善保管，不要泄露给他人。

## 第三步：克隆仓库到本地

克隆是读操作，Internal 级别的仓库无需认证即可克隆：

```bash
# 克隆到指定目录
cd ~/Documents
git clone http://coding.jd.com/{group}/{project}.git

# 进入仓库目录
cd {project}

# 查看当前分支
git branch -a
```

如果用户指定了目标目录，克隆到对应位置。克隆完成后告知用户本地路径。

## 第四步：日常操作（通过 API）

由于 Coding 的 git push 不支持 API Token，所有写操作通过 REST API 完成。

### API 基础信息

- **Base URL**: `http://coding.jd.com/api/v4`
- **认证**: Header `PRIVATE-TOKEN: {token}`
- **项目路径**: URL-encoded，如 `JD-Design-Wiki%2F2C-DesignWiki`
  - 规则：仓库 URL 中 `/codingRoot/` 后的 `{group}/{project}` 部分，`/` 换成 `%2F`

### 4.1 创建分支

```bash
curl -s -X POST "http://coding.jd.com/api/v4/projects/{project_path}/repository/branches" \
  -H "PRIVATE-TOKEN: {token}" \
  -H "Content-Type: application/json" \
  -d '{"branch":"{new_branch}","ref":"{source_branch}"}'
```

### 4.2 提交文件

**新建文件：** POST `/repository/files/{encoded_file_path}`
**更新文件：** PUT `/repository/files/{encoded_file_path}`
**删除文件：** DELETE `/repository/files/{encoded_file_path}`

Body 格式：
```json
{
  "branch": "目标分支",
  "content": "文件内容",
  "commit_message": "提交说明"
}
```

文件路径中的 `/` 需编码为 `%2F`。

### 4.3 批量提交（一次 commit 多个文件）

```bash
curl -s -X POST "http://coding.jd.com/api/v4/projects/{project_path}/repository/commits" \
  -H "PRIVATE-TOKEN: {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "branch": "分支名",
    "commit_message": "提交说明",
    "actions": [
      {"action": "create", "file_path": "path/file.md", "content": "内容"},
      {"action": "update", "file_path": "path/existing.md", "content": "新内容"}
    ]
  }'
```

### 4.4 发起合并请求（MR）

```bash
curl -s -X POST "http://coding.jd.com/api/v4/projects/{project_path}/merge_requests" \
  -H "PRIVATE-TOKEN: {token}" \
  -H "Content-Type: application/json" \
  -d '{"source_branch":"{source}","target_branch":"{target}","title":"{标题}"}'
```

### 4.5 本地同步

每次通过 API 提交后，提醒用户同步本地：
```bash
cd /本地仓库路径
git pull origin {branch}
```

## 错误处理

| HTTP Code | 含义 | 对用户说 |
|-----------|------|---------|
| 200/201 | 成功 | 操作完成 |
| 401 | Token 无效 | "你的 Token 可能已过期，请重新生成：https://xingyun.jd.com/codingRoot/profile/settings/token" |
| 403 | 无权限 | "你还不是仓库成员，请联系管理员将你添加为 Developer" |
| 404 | 路径错误 | "文件/分支不存在，请确认路径是否正确" |
| 400 | 格式错误 | 检查文件路径编码和 JSON 格式 |

## 交互原则

1. **永远不要假设用户知道什么是 git/branch/commit** — 用通俗语言解释
2. **每一步都给出明确的操作** — 不说"请配置"，而说"请打开这个链接，点击这个按钮"
3. **遇到错误主动诊断** — 不要让用户自己看报错信息
4. **操作完成后告知结果** — 给出可验证的链接（如仓库页面 URL）
5. **记住用户的 Token 和仓库信息** — 避免每次重复询问（存入 memory）

## 参考资料

- 新手完整入门指南：`references/onboarding-guide.md`
- API 扩展示例：`references/api-examples.md`
- Coding API 在线测试：https://coding.jd.com/openapi.html
- Token 权限文档：https://joyspace.jd.com/pages/c83aYQ1rw6cImR1SAesf