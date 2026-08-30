---
name: search
harness-version: 0
description: '快速查询历史设计案例。在知识库和素材登记表里检索关键词， 返回相关案例的摘要和链接，不做分析不给建议。适合快速查找历史决策。 /search <关键词> /search <关键词> --detail

  '
user-invocable: true
triggers:
- 搜索需求
- 找相关案例
- 查找历史案例
allowed-tools:
- Bash
- Read
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/huangliu-design/product-details/JD-ProductDetails-web/brain-frontend/public/design-kb/skills/search/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: pre_design
  agentmesh-activation: explicit_only
  short-description: 快速查询历史设计案例。在知识库和素材登记表里检索关键词， 返回相关案例的摘要和链接，不做分析不给建议。适合快速查找历史决策。 /search <关键词> /search <关键词> --detail
disable-model-invocation: true
---

# /search · 快速查询历史案例

## 工作目录

执行本 skill 前，请先定位到仓库中的 `JD-ProductDetails-web/brain-frontend/` 目录，
所有路径均以此为根目录。

## 这个 Skill 做什么

在知识库里用关键词检索，快速返回相关历史案例：

- 在 INDEX.md 和 registry.md 里匹配关键词
- 读取匹配案例的 frontmatter 和核心章节摘要
- 返回案例名称、关键词、素材链接、一句话摘要
- 不分析、不给建议，只查找和展示

**和 /design-advisor 的区别：**
- `/search` → 快速查，2秒出结果，只看历史
- `/design-advisor` → 深度分析，给出有观点的设计建议

## 调用方式

```
/search <关键词>           ← 快速检索，返回摘要
/search <关键词> --detail  ← 返回更详细的内容（含核心决策）
```

例：
```
/search 国补腰带
/search 优惠弹层 附件
/search 以旧换新 三态
/search 国补腰带 --detail
```

---

## 执行流程

### Step 1：提取关键词

从输入中提取 1-3 个核心关键词，同时读取
`public/design-kb/knowledge/component-naming.md` 补充别名：

```bash
grep -i "腰带\|banner\|利益点区域" public/design-kb/knowledge/component-naming.md
```

---

### Step 2：检索已录入案例

**只用 grep，不读全文：**

```bash
# 在 INDEX.md 里匹配关键词，拿到文件路径
grep -i "<关键词>" public/design-kb/knowledge/INDEX.md

# 找到匹配文件后，必须读 frontmatter（前30行）取 feature_name
head -30 public/design-kb/knowledge/scene/strategies/nationalSubsidy/xxx-reasoning.md
```

> ⚠️ **INDEX.md 第二列是组件覆盖描述，不是案例名称。**
> 案例名称必须从 frontmatter 的 `feature_name` 字段读取，不可用 INDEX.md 任何列替代。

按相关性分级：
- 🔴 **强相关**：关键词与案例的组件名或核心场景完全匹配
- 🟡 **中等相关**：关键词与业务场景部分匹配
- 🟢 **背景参考**：同属一个功能区

---

### Step 3：检索素材登记表

```bash
grep -i "<关键词>" public/design-kb/knowledge/registry.md
```

找到「待录入」状态的相关记录，一并列出。

---

### Step 4：读取摘要（匹配到案例时）

对强相关和中等相关的案例：

**默认模式**：只读 `## 8. 可复用的设计模式` 章节

```bash
sed -n '/^## 8\./,/^## 9\./p' public/design-kb/knowledge/scene/strategies/nationalSubsidy/xxx-reasoning.md
```

**--detail 模式**：额外读取 `## 4. 核心设计决策` 章节

---

### Step 5：输出结果

```markdown
# 搜索结果：「[关键词]」

共找到 [N] 个相关案例，[M] 条待录入素材。

---

## 🔴 强相关

### [feature_name]（来自 frontmatter，非 INDEX.md 列）
- **功能区：** [product_area]
- **平台：** [platform]
- **关键词：** [keywords]
- **最后更新：** [last_updated]
- **设计稿：** [relay链接]（可点击查看）
- **截图：** [CDN链接]（可点击查看）

**可复用模式摘要：**
[Pattern 内容，2-3句]

---

## 🟡 中等相关

[同上结构]

---

## 📎 待录入素材（已登记未完整录入）

| 需求名称 | 功能区 | 关键词 | 素材链接 |
|---|---|---|---|
| [名称] | [功能区] | [关键词] | [设计稿链接] · [PRD链接] |

> 如需完整录入，运行：`/design-reasoning-input <relay链接>`
> 如需深度设计建议，运行：`/design-advisor [同样的关键词]`

---

*找到了想要的内容？还是需要基于这些历史案例给出新需求的设计建议？*
*需要建议请运行：`/design-advisor [你的新需求描述]`*
```

---

## 关键约束

1. **只用 grep 和 head，不用 Read 工具读全文。** 控制 token 消耗，保证速度快。
2. **不分析，不给建议。** 只呈现历史内容，观点和建议留给 `/design-advisor`。
3. **0 匹配时诚实告知。** 不编造相关案例，明确说明「知识库暂无相关案例」。
4. **末尾引导。** 每次结果末尾提示用户可以用 `/design-advisor` 获取更深度的建议。
5. **--detail 时多读一个章节，不读全文。** 控制上限，不过度消耗 token。
6. **案例名称必须来自 frontmatter `feature_name`。** INDEX.md 第二列是组件描述，不是案例名，禁止用它作为输出标题。

---

## 版本历史

- **v1.1** (2026-05-26) 修复案例名称来源：强制从 frontmatter `feature_name` 读取，禁止用 INDEX.md 第二列替代
- **v1.0** (2026-05-25) 初版
