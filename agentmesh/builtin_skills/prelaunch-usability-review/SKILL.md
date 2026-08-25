---
name: prelaunch-usability-review
description: Use when the user asks for 上线前可用性测试、专家走查、改版方案评审、模拟真实用户、before/after 体验评估、还没上线的设计可行性判断, or wants a Chinese HTML
  review report based on screenshots, page goals, business context, and known changes. Produces realistic user-simulation
  insights, advantage/disadvantage judgment, visual analysis, P0/P1/P2 issues, improvement priorities, and a pre-launch validation
  plan. Use design-abtest-analysis instead when the main evidence is already上线后的 AB 数据复盘.
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/comprehensive-business/content-ecosystem/prelaunch-usability-review/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
  short-description: Use when the user asks for 上线前可用性测试、专家走查、改版方案评审、模拟真实用户、before/after 体验评估、还没上线的设计可行性判断, or wants a C…
disable-model-invocation: true
---

# Prelaunch Usability Review

## 定位

把还没上线的页面或功能方案，转成一份面向产品、设计、业务评审的上线前可用性走查报告。默认输出中文；如果用户要求 HTML，优先生成本地可打开的 `index.html` 和 `assets/`。

该 skill 适合截图型评审，尤其是 APP 页面、内容流、电商交易链路、商详、问答、搜索、评价、购物车、下单、会员权益、AI 功能入口等场景。

## 与相邻 Skill 的分工

- `prelaunch-usability-review`：上线前；基于截图、业务目标、改版说明做专家走查和模拟用户反馈；重点是“该不该这样上线、哪里要先改、怎么做小样本验证”。
- `design-abtest-analysis`：上线后或已有实验数据；重点是“数据为什么涨跌、实验组/对照组怎么解释、下一轮怎么改”。
- `jd-app-journey-map`：更大链路的旅程地图；重点是“跨页面、跨阶段、用户任务链路和机会点”。

## 不要用在这些情况

- 已经有完整 AB 数据，需要解释涨跌原因：优先用 `design-abtest-analysis`。
- 目标是梳理跨页面完整用户链路：优先用 `jd-app-journey-map`。
- 只是想美化一个 HTML 页面：不要重跑本 skill，先做视觉和结构优化。
- 没有截图、没有改版说明、没有业务目标时，不要直接下强结论，只能先给输入清单和假设框架。

## 最小输入

最小输入包括：

1. 页面类型。
2. 业务目标。
3. 改版前后截图或关键方案截图。
4. 主要改动说明。

理想输入包括：目标用户、页面定位、改版约束、MVP 范围、竞品启发、关键局部图、已知风险、上线前最想判断的问题。

## 推荐触发语

```text
使用 prelaunch-usability-review，帮我对这个改版做上线前可用性走查，并输出 HTML 评审报告。
页面类型：
业务目标：
目标用户：
主要改动：
已知限制：
截图：
我最想判断：
```

## 默认工作流

1. **识别输入**
   - 页面类型、业务目标、目标用户、当前限制、上线状态。
   - 改版前后截图、关键交互截图、弹层/入口/底部区/重点模块截图。
   - 用户明确提供的信息、截图可见事实、模型推演、待验证内容要分开。

2. **判断页面定位**
   - 先判断页面承担的核心任务：浏览沉浸、商品理解、交易转化、互动探索、留资、内容消费、问题解决等。
   - 如果页面类型或竞品背景会影响结论，先补充轻量行业/竞品判断；需要最新资料时联网核对并标注来源。

3. **建立真实用户模拟**
   - 不使用生硬标签，如“目的型购买用户”“参数谨慎用户”。
   - 用接近真实用户的话命名和表达，例如：“我就想先刷一会儿，看有没有值得点进去的”“这个问题正好是我担心的，但我不确定答案是谁说的”。
   - 每类用户必须包含：进入场景、第一眼反应、继续/离开的原因、对核心改动的感受、会不会产生目标行为。
   - 明确标注“这是基于截图和场景的模拟用户反馈，不等同真实调研结论”。

4. **做专家走查**
   - 固定检查：用户目标是否清楚、核心路径是否顺畅、信息层级是否合理、交互成本是否过高、视觉重点是否清晰、边界状态是否缺失。
   - 每个结论必须能回到截图证据、用户目标或业务目标。
   - 必须同时写优势和劣势；不要只写“方向成立”。

5. **做视觉评审**
   - 对比改版前后：画面沉浸、内容密度、价格/卖点/购买按钮、互动入口、问答弹层、视觉层级、遮挡、对齐、可读性。
   - 判断“第一眼应该先看什么”和“实际第一眼被什么吸走”是否一致。
   - 对重点局部截图做标注说明，但不要用无意义拼贴。

6. **输出问题优先级**
   - P0：会影响主路径理解、购买点击、核心目标或导致明显误操作的问题。
   - P1：会增加认知负担、分流注意力、降低信任或削弱视觉重点的问题。
   - P2：体验润色、文案、边界状态、视觉一致性、次要效率问题。
   - 每个问题都要给：问题、证据、影响用户、修改建议、验证方式。

7. **给上线前验证计划**
   - 推荐 5-8 人小样本可用性测试，覆盖 3-4 类典型用户。
   - 任务要贴近真实场景，不要只问“你觉得好不好”。
   - 指标建议包括：首屏理解率、主动作找到时间、问答入口理解率、打扰感、可信度、继续浏览意愿、购买/进商详点击意向。

8. **生成 HTML**
   - 如果用户要求 HTML，先读取 `references/html-report-contract.md`。
   - 可以复制 `assets/html-template/index.html` 作为骨架，再替换内容和图片。
   - 把完整原稿截图前置到结论之后，便于读者先建立上下文；局部截图放在对应观点附近。
   - 页面必须在本地浏览器直接打开，不依赖构建工具。
   - 保留本 skill 的上线前评审模板，不要套用用户旅程图或 AB 分析模板。

9. **验收**
   - 检查所有图片路径存在。
   - 检查没有 TODO、占位文案和看不懂的标题。
   - 检查头部结论是否 5 秒内能看懂。
   - 检查底部卡片、截图说明、双列模块是否对齐。
   - 如果使用 `impeccable` 或视觉审查工具，优先检查信息层级、对齐、密度、可读性和视觉噪音。

## 默认报告结构

1. **一屏结论**：方向是否成立、是否建议原样上线、先改什么、怎么验证。
2. **完整原稿**：Before/After 或主流程截图，先让读者看清方案。
3. **证据链**：用局部截图解释关键问题，不堆图。
4. **真实用户模拟**：用自然语言描述不同用户的第一反应和行为倾向。
5. **优劣势判断**：分别说明新版带来的收益和代价。
6. **视觉走查**：主次层级、商业压力、沉浸感、入口可理解性、弹层可信度。
7. **P0/P1/P2 问题**：每条都有修改建议和验证指标。
8. **上线前测试计划**：测试对象、任务、观察点、通过标准。

## 已验证案例

- 京东逛频道视频页改版前可用性走查：`/Users/leixiaoming3/Documents/Codex/2026-06-18/webcli-https-mp-weixin-qq-com/outputs/jd-video-usability-review/index.html`

## 模板边界

- 本 skill 的 HTML 应该像评审页：结论强、截图证据靠前、优劣势明确、问题分 P0/P1/P2。
- 不要做成用户旅程地图表格，也不要做成 AB 数据复盘页。
- 如果用户要求“模拟真实用户”，必须用自然语言表达真实第一反应，不要写生硬用户标签。
- 如果只看到截图，不能把推断写成真实数据结论。

## 写作规则

- 先给结论，再给理由。
- 用产品、设计、业务和用户语言，不堆方法论。
- 保持“截图可见 / 用户提供 / 模型推演 / 待验证”的证据边界。
- 不把模拟用户当真实调研结果。
- 不用抽象用户标签替代真实表达。
- 不输出大段泛泛建议；每条建议都要能指导改稿或测试。
- 不把 HTML 做成纯文档堆叠；要通过版式帮助读者快速抓重点。

## 参考文件

- `references/review-framework.md`：走查维度、用户模拟、优劣势判断和测试计划。
- `references/html-report-contract.md`：HTML 信息结构、视觉要求和验收标准。
- `assets/html-template/index.html`：可复制改写的单页 HTML 骨架。
