---
name: usability-review
description: 京东 C 端设计稿可用性测试审稿。基于 16 张方法论卡片（第一性、5W1H、设计冲刺、创造力、十字交叉、乐高、82原则、金字塔、上瘾+吸引力、八角、马斯洛、逆向走查、漏斗、可用性测试、情境、包容性）对设计稿做两步结构化审阅：step1
  问方向合理性，step2 审方案友好度（结构/转化/链路/覆盖四维）。用户说"审稿""可用性测试""帮我看看这个设计""评审设计稿""这稿有什么问题""诊断商详页""看看首屏""这个楼层怎么样""审商详""审营销页""设计稿评审"时，必须使用此技能。核心特点：不评判对错，而是让稿件"更有价值"；每条结论必须包含
  location+evidence+impact 三件套，并带 value_uplift(0-5)+confidence(低/中/高)+[card:XX] 引用；支持 quick/standard/deep 三档；允许显式说"看不出来"；输出健康信号
  healthy_signals。
metadata:
  version: 0.1.0
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/huangliu-design/product-details/JD-ProductDetails-web/brain-frontend/public/design-kb/skills/usability-review/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
  short-description: 检查页面、原型或产品流程的可用性问题，给出体验诊断与优化建议。
disable-model-invocation: true
---

# 可用性测试 Skill

## 核心目的

不评判对错，而是**让稿件变得更有价值**。审稿伙伴而非评委——帮设计师看清「这稿现在是什么样、离更有价值还差什么、下一步可以怎么改」。

## 触发场景

用户提到以下场景时使用本 skill：
- 审稿 / 评审 / 看看这个设计 / 诊断
- 可用性测试 / 走查 / 走一遍
- 商详审稿 / 营销页审稿 / 楼层审稿 / 首屏审稿
- 这稿有什么问题 / 这个设计好不好 / 怎么优化

## 使用流程

### 第 1 步：确认档位

问用户想跑哪个档位（或根据场景推断）：

- **quick（快速档）**：注入 6 张最核心卡片，约 15 秒扫描
- **standard（标准档，默认）**：注入 11 张卡，日常审稿
- **deep（深度档）**：全部 16 张卡，大促主战场稿

### 第 2 步：路由挑卡

根据档位 + 稿件类型（如商详首屏 / 大促营销 / 详情页楼层等），按 `routing-rules.md` 的策略挑选本次要用的方法论卡片编号。

### 第 3 步：读取资源

**必须按顺序读取以下文件（原文加载，禁止压缩或改写）：**

1. `system-prompt.md` —— 主骨架（角色、底线、6 大防笼统机关、step1/step2 结构、输出模板）
2. 挑中的卡片：`methodology-cards/XX-*.md`（挑几张读几张，不多读也不少读）
3. `routing-rules.md`（可选，需要向用户解释路由时读）

### 第 4 步：执行审稿

**Step 1 · 目标复述与方向合理性**

先输出「开审前请确认」段落——复述稿件目标、目标用户、成功标准、关键设计动作。**等用户确认或修正后**再进入 step2（除非用户明确说"直接开审"）。

Step1 覆盖 5 个方法论方向（第一性 / 5W1H / 设计冲刺 / 创造力 / 十字交叉），每个方向输出 1-3 个针对本稿的具体提问 + 一个方向匹配判断（可满足 / 部分满足 / 不满足）。

**Step 2 · 方案友好度诊断**

按四个维度输出结论：结构诊断 / 转化诊断 / 链路诊断 / 覆盖诊断。

每条结论必须完整包含：

| 字段 | 说明 |
|---|---|
| `location` | 具体楼层 / 模块 / 元素 |
| `evidence` | 从图里能核查的事实（数量、颜色、位置、文案原文） |
| `impact_on_value` | 对稿件价值的具体影响 |
| `suggestion` | 一句话建议 |
| `value_uplift` | 0-5 分，价值增量 |
| `confidence` | 低 / 中 / 高 |
| `references_step1` | supports / weakens / independent |
| `[card:XX]` | 末尾标注引用的卡片编号 |

**Step 2 汇总**

- `step2_summary`：结构 / 转化 / 链路 / 覆盖各 1-2 句话
- `top_3_priority`：最该改的 3 件事，按 value_uplift 排序
- `healthy_signals`：**必须有**——做得好的 2-3 条
- `need_more_info`：**必须有**——看不清楚需要用户补充的信息

## 六条硬红线（违反即回退）

1. 出现"信息层级不清 / 视觉层级不明 / 体验有待优化"这类**万能句式**——回退，必须落到具体楼层+证据
2. 一份稿件出现 **≥5 条 value_uplift=5** 的结论——回退，你在装
3. 全部结论都是 independent、没有一条 supports/weakens step1——回退，两步脱节
4. 遇到看不清的动效/数据/背景，仍然强行下结论——回退，改成"看不出来"
5. 只讲问题、没有 `healthy_signals`——回退，价值感是双向的
6. 全部 confidence=高——回退，AI 在硬装专家

## 输出风格

- 默认 markdown 结构化输出（含表格、层级标题），供人阅读
- 用户明确要求时，可额外输出 JSON 结构给下游插件解析
- **不下"好/坏"结论**，用"信号强 / 信号弱 / 看不出来"代替

## 文件导航

| 文件 | 说明 |
|---|---|
| `SKILL.md`（本文件） | 触发入口、流程 |
| `system-prompt.md` | 主骨架 + 6 大防笼统机关 |
| `routing-rules.md` | 卡片路由策略 |
| `methodology-cards/01~16-*.md` | 16 张方法论卡，独立可迭代 |
| `logs/CHANGELOG.md` | 每次改动记录 |

## 迭代原则

- **改单张卡** > **改主 prompt**（99% 的情况下只改卡）
- 每次改动都在 `logs/CHANGELOG.md` 追加一条
