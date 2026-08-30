---
name: case-register
harness-version: 0
description: '素材登记工具。把历史设计需求的素材链接快速登记到 registry.md， 不做内容提取，只记录「这个需求存在、素材在哪里、关键词是什么」。 供 design-advisor 在检索不到案例时按需触发完整录入。 /case-register
  <relay链接> <prd链接或文字> <需求名称> /case-register <relay链接> --design-only <需求名称> /case-register --batch  ← 批量登记模式，逐条输入

  '
user-invocable: true
triggers:
- 素材登记
- 登记需求
- 快速登记
allowed-tools:
- mcp__zero-design__get_design_metadata
- Bash
- Read
- Write
- Edit
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/huangliu-design/product-details/JD-ProductDetails-web/brain-frontend/public/design-kb/skills/case-register/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
  short-description: 素材登记工具。把历史设计需求的素材链接快速登记到 registry.md， 不做内容提取，只记录「这个需求存在、素材在哪里、关键词是什么」。 供 design-advisor 在检索不到案例时按需触…
disable-model-invocation: true
---

# /case-register · 素材登记

## 工作目录

执行本 skill 前，请先定位到仓库中的 `JD-ProductDetails-web/brain-frontend/` 目录，
所有路径均以此为根目录。

## 这个 Skill 做什么

低成本批量登记历史需求素材，不做完整录入：

- 从设计稿标题自动提取需求名称、平台、功能区
- AI 自动推断关键词，设计师确认后写入
- 登记结果存入 `public/design-kb/knowledge/registry.md`
- 供 design-advisor 检索未录入的历史素材

## 调用方式

```
/case-register <relay链接> <prd链接> <需求名称>
/case-register <relay链接> --design-only <需求名称>
/case-register --batch
```

---

## 执行流程

### Step 1：解析输入

提取 Relay URL、PRD 链接/文字、需求名称、`--design-only` / `--batch` 标识。

**短链接处理：** 非 relay.jd.com 域名先用 `Bash(curl -sI <url> | grep -i location)` 自动解析。

**--batch 模式：** 进入逐条输入模式，每次提示设计师输入一条，直到输入「完成」退出。

---

### Step 2：读取设计稿节点结构（仅用 get_design_metadata）

只调用 `get_design_metadata`，**不调用其他 MCP 工具**，控制 token 消耗。

从返回数据中提取以下内容：

**基础信息：**
- 需求名称：从页面标题提取（若已手动输入则跳过）
- 平台：从画布尺寸判断（375px → App；1440px → PC；两者都有 → Both）
- 功能区：从页面名判断（商详/购物车/结算页/支付完成页等）

**节点关键词提取（核心优化）：**
遍历前3层节点名称，提取具体的组件名和场景名作为关键词候选：
- 取 Frame 名（如「国补腰带/领取前」「优惠弹层/附件说明」）
- 取重复出现3次以上的节点名（说明是主要组件）
- 过滤掉泛化词（如「背景」「文字」「图标」「矩形」等）
- 合并到需求名称提取的业务词，去重后得到关键词列表

例：设计稿标题「国补攻坚专项0318」（抽象）→ 节点名提取「国补腰带, 领取弹层, 优惠弹层, 以旧换新, 价格楼层」（具体）

MCP 失败时降级：仅用手动输入的需求名称推断关键词，标注 `⚠️ 设计稿未读取，关键词仅基于名称推断`。

---

### Step 3：推断关键词 + 设计师追加

综合以下来源生成关键词候选列表：
1. 节点名提取的组件名和场景名（Step 2）
2. 需求名称中的业务词
3. 读取 `public/design-kb/knowledge/component-naming.md` 补充别名（用 Bash grep，不用 Read 工具）

输出确认，**设计师可直接追加关键词**：

```
登记预览：

需求名称：国补攻坚专项-商详价格营销标签
功能区：商详
平台：Both
AI 提取关键词：国补, 腰带, 价格标签, 到手价, 营销标签
                ↑ 来自设计稿节点名

请追加关键词（逗号分隔，或直接回复「确认」跳过）：
→ （设计师输入，例：以旧换新, 服务金, 利益点区块）

Relay：relay.jd.com/...
PRD：joyspace.jd.com/...（无则留空）
一句话描述：（可补充，或直接回复「确认」跳过）
```

设计师输入追加词后，合并写入；直接回复「确认」则用 AI 提取的关键词。

---

### Step 4：写入 registry.md

确认后追加一行到 `public/design-kb/knowledge/registry.md`：

```markdown
| [需求名称] | [功能区] | [平台] | [关键词] | [一句话描述] | [Relay链接] | [PRD链接] | [登记时间] | 待录入 |
```

若 `registry.md` 不存在，先创建：

```markdown
# 素材登记表

> 登记历史需求素材链接，供按需触发完整录入。
> 状态：待录入 / 录入中 / 已完成

| 需求名称 | 功能区 | 平台 | 关键词 | 一句话描述 | Relay | PRD | 登记时间 | 状态 |
|---|---|---|---|---|---|---|---|---|
```

输出：
```
✅ 已登记：国补价格营销标签
当前待录入：[N] 条

继续登记下一条，或运行 /case-register --batch 批量登记。
```

---

### --batch 批量模式

适合一次性登记大量历史需求。进入后逐条提示：

```
批量登记模式（输入「完成」结束）

第 1 条：请输入 Relay 链接（可附需求名称）
```

每条确认后立即写入，不等全部完成。结束后输出汇总：
```
批量登记完成：共登记 [N] 条
待录入总数：[N] 条
运行 /knowledge-update 可查看完整登记表。
```

---

## 关键约束

1. **只调用 get_design_metadata，不调用其他 MCP 工具。** 控制每条登记的 token 消耗在 ~300 token 以内。
2. **关键词来源优先级：节点名 > 需求名称 > AI 推断。** 节点名提取的关键词最具体，优先使用。
3. **设计师追加关键词不强制。** 跳过时用 AI 提取的结果，不阻断流程。
4. **过滤泛化词。** 背景、文字、图标、矩形、组件、设计、优化、改版等词不写入关键词。
5. **不阻断流程。** MCP 失败、PRD 链接无法访问，都继续写入，标注缺失项。
6. **不重复登记。** 写入前检查 registry.md 是否已有同名需求，有则提示确认是否覆盖。
7. **不触发完整录入。** 本 Skill 只登记，不生成 reasoning.md，那是 design-advisor 按需触发的事。

---

## 版本历史

- **v1.0** (2026-05-25) 初版
- **v1.1** (2026-05-25) 关键词提取改为从设计稿节点名提取，新增设计师手动追加关键词步骤
