---
name: welcome
harness-version: 0
description: '新用户引导。展示所有可用工具、当前知识库状态、知识库浏览链接。 每次新会话开始时自动触发，也可手动运行。 /welcome

  '
user-invocable: true
triggers:
- 新会话开始
- 介绍工具
- 有哪些功能
allowed-tools:
- Bash
- Read
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/huangliu-design/product-details/JD-ProductDetails-web/brain-frontend/public/design-kb/skills/welcome/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: pre_design
  agentmesh-activation: explicit_only
  short-description: 新用户引导。展示所有可用工具、当前知识库状态、知识库浏览链接。 每次新会话开始时自动触发，也可手动运行。 /welcome
disable-model-invocation: true
---

# /welcome · 欢迎引导

## 工作目录

执行本 skill 前，请先定位到仓库中的 `JD-ProductDetails-web/brain-frontend/` 目录，
所有路径均以此为根目录。

## 这个 Skill 做什么

新用户进入时展示：
- 当前知识库的案例数量和最近更新
- 分类的可用工具说明
- 知识库浏览页面的本地路径
- 推荐的起始操作

---

## 执行流程

### Step 1：读取知识库状态

用 Bash 快速获取基本数据：

```bash
# 案例总数
grep -c "^|" public/design-kb/knowledge/INDEX.md 2>/dev/null || echo "0"

# 最近更新
head -5 public/design-kb/knowledge/CHANGELOG.md 2>/dev/null

# 待录入素材数
grep -c "待录入" public/design-kb/knowledge/registry.md 2>/dev/null || echo "0"

# preview 主页路径
ls public/design-kb/knowledge/preview/index.html 2>/dev/null && echo "存在" || echo "未生成"
```

### Step 2：输出引导内容

```markdown
# 👋 欢迎使用设计知识库

> 当前共有 **[N] 个**历史案例 · 最近更新：[日期] · 待录入素材：[M] 条

---

## 🗂 浏览知识库

在 Finder 中打开以下路径，双击 index.html 即可在浏览器里浏览所有案例：

📁 `public/design-kb/knowledge/preview/index.html`

（如果文件不存在，运行 `/knowledge-preview` 生成）

---

## 你可以做什么

### 🔍 查找历史案例
在知识库里搜索相关场景或组件，返回历史决策摘要。
```
/search 国补腰带
/search 优惠弹层
/search 以旧换新 三态
```

### 💡 获取设计建议
描述你的新需求，AI 检索历史案例，给出有依据的设计建议。
```
/design-advisor 我要做国补资格有效期在商详的展示
/design-advisor [relay设计稿链接]
```

### 📥 录入新完成的案例
提供设计稿链接，AI 自动生成结构化案例文档录入知识库。
```
/design-reasoning-input [relay链接] --design-only
/design-reasoning-input [relay链接] [prd文字或链接]
```

### 🗃 批量登记历史素材
快速登记大量历史需求的链接，不做完整录入，供后续按需查询。
```
/case-register --batch
```

### 👁 在浏览器查看知识库
生成可视化页面，在浏览器里浏览所有案例。
```
/knowledge-preview
```

---

## 🔧 项目维护（无需了解细节）

以下工具由项目管理员使用，普通用户无需关注：

- `/knowledge-update` — 录入案例后自动更新索引
- `/git-workflow` — 版本管理和分支操作
- `/leader-report` — 生成领导汇报页

---

## 推荐起始操作

**第一次使用？** 先浏览一下现有案例，了解知识库里有什么：
```
/knowledge-preview
```

**有新需求想参考历史？**
```
/search [你的关键词]
```

**刚完成一个需求想录入？**
```
/design-reasoning-input [relay链接] --design-only
```
```

---

## 关键约束

1. **只用 Bash 读取状态数据，不用 Read 工具。** 保持启动速度快。
2. **preview 路径直接展示，不自动打开浏览器。** 用户自己决定何时查看。
3. **案例数量读取失败时显示「暂无数据」，不报错。**
4. **输出完成后不追问。** 等待用户选择下一步操作。

---

## 版本历史

- **v1.0** (2026-05-25) 初版
