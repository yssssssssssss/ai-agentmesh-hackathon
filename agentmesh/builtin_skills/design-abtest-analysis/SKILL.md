---
name: design-abtest-analysis
description: Use when analyzing design control/experiment groups, multiple UI方案, AB test variants,上线前优劣势评估,上线后数据下跌/上涨复盘, or
  when the user provides screenshots and wants a concise HTML review page that explains方案差异、问题、验证数据和下一步动作. 默认中文输出，适合产品设计、用户体验、商详/交易/内容流等场景。
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/comprehensive-business/content-ecosystem/design-abtest-analysis/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
  short-description: Use when analyzing design control/experiment groups, multiple UI方案, AB test variants,上线前优劣势评估,上线后数据…
disable-model-invocation: true
---

# Design AB Test Analysis

## Output Goal

Turn user-provided方案截图、背景、目标、数据或简单描述 into a concise HTML review page.

Default deliverable:

```text
design-abtest-html/<topic-slug>/
├── index.html
└── assets/
```

The page should help reviewers quickly understand:

1. 这次在比较什么方案
2. 当前问题或机会是什么
3. 哪个环节可能影响用户行为
4. 接下来要看哪些数据
5. 下一步怎么改或怎么验证

## Scope

Use this skill when the main question is方案对比、AB 实验、上线后数据复盘、实验组/对照组解释、或下一轮实验策略。

Do not use this skill when:

- The design has not launched and the user mainly wants专家走查、真实用户模拟、优劣势和上线前验证: use `prelaunch-usability-review`.
- The user wants a cross-page user journey, user segmentation, emotion curve, and opportunity map: use `jd-app-journey-map`.
- The user only wants HTML visual polish: keep the existing analysis skill and optimize the page directly.

## Minimum Input

Minimum viable input:

1. 分析对象或页面类型.
2. 对照组/实验组 or 方案 A/B/C 是什么.
3. 目标指标.
4. 截图 or 方案说明.
5. 当前状态: 未上线、灰度中、已上线.

Ideal input:

- 每个方案的截图和关键差异.
- 曝光、点击、CTR、转化、停留、退出、加购、下单等数据.
- 品类、人群、入口、价格带、新老客等分层.
- 已知异常: 点击涨但转化降、停留升但购买降、父单转化走弱等.

## Triggered Workflow

1. **Identify scenario**
   - 上线前：focus on 优劣势、风险、实验假设、上线验证数据.
   - 上线后：focus on 数据变化、可能原因、行为断点、下一步优化.
   - 数据不足：separate “截图可见 / 用户提供 / 推测 / 待验证”.

2. **Collect inputs**
   - If the user gave enough context and screenshots, proceed directly.
   - If context is thin, first provide a short input prompt from `references/input-prompt.md`.
   - If the user only gives a simple idea, expand it into 2-3 possible analysis angles and ask the user to confirm before final HTML generation.

3. **Plan screenshot placement**
   - Put screenshots near the analysis point they prove.
   - Use side-by-side layout for control/experiment screenshots.
   - Use step-by-step layout for user flow screenshots.
   - Use Before/After layout for optimization稿.
   - Copy readable screenshots into the output `assets/` folder and reference them with relative paths.

4. **Analyze**
   - Keep language direct and short.
   - Avoid deep theory unless the user asks.
   - Prefer cards, short labels, flows, checklists, and priority blocks.
   - Always include: 结论、方案对比、关键断点、要盘的数据、下一步动作.

5. **Generate HTML**
   - Start from the integrated template `assets/html-template/index.html`; do not recreate the visual system from scratch.
   - Follow `references/visual-template.md` for color, width, card, screenshot, typography, and responsive rules.
   - Use the full structure by default, then remove or shorten sections only when the case is simple.
   - The page must open directly in a browser; no build tools.
   - Keep this skill's AB/review visual language. Do not apply the user-journey or prelaunch-usability templates.

6. **Verify**
   - Check `index.html` exists.
   - Check all screenshot paths exist.
   - Check no TODO/TBD placeholders remain.
   - Check desktop width is capped at 900px.

## Recommended Page Structure

1. **Header**
   - One-sentence conclusion
   - Known result / goal / scenario / evidence status

2. **方案截图对比**
   - Control vs Experiment, or 方案 A/B/C
   - Short captions: “它解决什么 / 它可能牺牲什么”

3. **核心判断**
   - 3 cards max: value, risk, current issue

4. **路径或断点**
   - 3-5 steps or 3 key breakpoints
   - Avoid large dense tables unless the user explicitly asks.

5. **要盘的数据**
   - What to check now
   - How to segment
   - Which metrics decide next action

6. **下一步动作**
   - P0/P1/P2 or Experiment A/B/C
   - Each action includes validation metric.

7. **实验建议**
   - 2-3 experiment options for next validation

8. **评审结论**
   - One short paragraph suitable for product review.

## Recommended Trigger Prompt

```text
使用 design-abtest-analysis 分析这个改版。
场景：
对照组：
实验组/方案：
业务目标：
当前状态：
已有数据：
截图：
我希望输出 HTML，重点讲清楚结论、原因和下一步动作。
```

## Verified Cases

- 京东商详评价上半年 AB 总结：`/Users/leixiaoming3/Documents/Codex/2026-06-18/webcli-https-mp-weixin-qq-com/outputs/jd-abtest-double-column-optimized/index.html`
- 旧版京东商详评价双列改版体验复盘：`/Users/leixiaoming3/Documents/京东项目尝试结合/jd-journey-html/review-double-column-analysis/index.html`

## Hard Rules

- Do not claim screenshots prove causality. Data explains outcome; screenshots help explain possible behavior mechanism.
- If data is missing, clearly label the conclusion as hypothesis or pre-launch risk.
- Keep方案介绍 before conclusions when the方案 itself is hard to understand.
- Put complete screenshots or readable crops near the point they prove; do not crop away key UI evidence.
- Separate “what changed”, “what data says”, “why users may behave this way”, and “what to do next”.

## Writing Rules

- Default Chinese.
- 先给结论，再给理由.
- Keep content concise; design review readers should understand the page in 3-5 minutes.
- Do not over-explain UI theory.
- Use “可能 / 待验证” when behavior data is missing.
- Do not claim causality from screenshots alone.
- For high-stakes decisions, explicitly list missing data.

## Screenshot Rules

- Use real screenshots when available.
- Prefer local copies in `assets/`.
- Desktop side-by-side screenshot cards should not stretch images.
- Phone screenshots should use `width: min(100%, 420px); height: auto; object-fit: contain;`.
- If many screenshots are provided:
  - Pair comparable designs together.
  - Put flow screenshots in chronological order.
  - Put details or弹层 screenshots near “断点” or “风险” sections.

## References

- Use `references/input-prompt.md` when asking the user what to provide.
- Use `references/analysis-framework.md` when deciding how to analyze上线前/上线后 cases.
- Use `references/visual-template.md` before generating any HTML, to keep visual output consistent.
- Use `assets/html-template/index.html` as the single integrated visual template for generated HTML.
