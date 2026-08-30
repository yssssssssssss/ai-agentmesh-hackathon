---
name: jd-field-ppt-skill
harness-version: 0
description: 生成京东场域专用的横向翻页 HTML PPT / 业务汇报 deck / 方案演示页。用于京东 APP、零售、内容生态、店铺、交易、增长、设计系统、业务复盘、产品方案、规范发布等场景；当用户说“京东场域 PPT”“JD
  风格 PPT”“业务汇报页”“把文档做成演示 deck”“生成分享封面”时触发。输出优先为单文件 HTML deck，可配套生成图片素材与封面，并必须按 JD V16 token、场域叙事、信息密度和校验清单自检。
metadata:
  short-description: 京东场域 HTML PPT 生成技能
  author: 2C-DesignWiki
  source: 2C-DesignWiki/.agents/skills/jd-field-ppt-skill/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
disable-model-invocation: true
---

# JD Field PPT Skill

> 架构参考 guizang-ppt-skill 的“SKILL.md + assets + references + scripts”分层方式，但本 Skill 使用京东场域原创模板、JD V16 token 和业务汇报规则；不要复制外部仓库的模板代码、文案或视觉资产。

## 产物

默认生成一个可直接打开的单文件 HTML 横向 PPT：

```
项目名/
└── ppt/
    ├── index.html
    ├── fonts/        # 从 assets/fonts/ 复制，供 @font-face 相对引用
    ├── media/        # 从 assets/media/ 复制，供封面背景视频相对引用
    └── images/        # 可选，图片素材相对引用
```

除非用户明确要 `.pptx`，否则优先 HTML deck。HTML 方便 Agent 读写、浏览器验收、截图和二次迭代。

## 工作流

1. **识别场域**：先判断是业务复盘、产品方案、设计规范发布、增长实验、生态治理、项目路演还是汇报封面。若材料不足，只问最关键的 1-2 个问题。
2. **读参考**：按任务读取 `references/`：
   - 不确定该用什么 deck 结构：先读 `deck-structure-presets.md`
   - 用户要求画图 / 架构图 / 流程图 / 飞轮 / 鱼骨 / Dashboard / SVG / 精排：读 `drawing-paths.md`
   - 用户质疑“结构不够多 / 模板太单一 / 页面类型不够”：读 `html-ppt-patterns.md`
   - 业务 / 产品 / 设计汇报：读 `jd-field-deck-system.md` 和 `page-patterns.md`
   - 调整视觉主题 / 图表色 / 状态色：读 `jd-color-tokens.md`
   - 需要配图 / 封面：再读 `image-and-cover-guidelines.md`
   - 收尾自检：读 `quality-checklist.md`
3. **拷贝模板和资产**：从 `assets/template-jd-field.html` 复制为目标 `ppt/index.html`，并把 `assets/fonts/` 复制到目标 `ppt/fonts/`、`assets/media/` 复制到目标 `ppt/media/`，替换标题、章节、页面内容和 `data-layout`。
4. **先选路径**：根据 `deck-structure-presets.md` 判断是用户旅程型、系统机制型、经营复盘型、方案提案型、规范发布型还是一页压缩型。
5. **再选作图路径**：若页面包含结构图、流程图、飞轮、鱼骨、Dashboard、SVG 或精排架构图，根据 `drawing-paths.md` 选择 A-E 路径。
6. **再排节奏**：先写 slide plan，再填页面。多页默认 3-8 页；复杂汇报可扩展到 7-12 页；一页压缩必须控制信息密度。
7. **选择版式**：正文页优先使用 `page-patterns.md` 和 `html-ppt-patterns.md` 中登记的版式，不临时发明复杂结构；连续两页不要使用完全相同 layout。
8. **写京东场域语言**：标题是结论，不是栏目名；正文短句，保留业务对象、用户动作、指标、约束。
9. **可选配图**：需要图片时，用真实业务对象、界面状态、流程图或信息图；图片必须进入模板图片槽位，避免装饰性背景图。
10. **静态校验**：运行：

   ```bash
   node .agents/skills/jd-field-ppt-skill/scripts/validate-jd-deck.mjs path/to/ppt/index.html
   ```

   P0 必须全部通过，再交付。
11. **浏览器验收**：打开 HTML，检查桌面尺寸下每页无遮挡、无文字溢出、左右翻页可用。

## 京东场域原则

- **像业务工具，不像营销海报**：信息密度高、可扫描、结论先行，少用大面积空泛视觉。
- **红色只做锚点**：`#ff0f23` 用于关键数字、状态、页码、强调线，不铺满全屏。
- **V16 token 优先**：色彩必须来自 `jd-color-tokens.md` 的 JD V16 基础色；圆角、字体、间距使用 JD V16 token 映射。不要随手引入紫蓝渐变、米色杂志风、暗蓝科技风。
- **字体预设**：标题、关键数字、品牌强调使用 `JD ZhengHei`；普通正文、表格、注释使用苹方。
- **真实对象优先**：商品、店铺、内容、交易、履约、会员、搜索、推荐、频道、设计组件等业务对象要在首屏或关键页出现。
- **页面要能被复述**：每页只有一个主判断；页面标题读完后，听众应知道这一页要证明什么。
- **不做嵌套卡片**：页面区块可以分栏、分带、分表，不要卡片套卡片。

## 资源文件

```
jd-field-ppt-skill/
├── SKILL.md
├── agents/openai.yaml
├── assets/template-jd-field.html
├── assets/fonts/
│   ├── JDZhengHeiV2-Regular.otf
│   ├── JDZhengHeiV2-Light.otf
│   ├── JDZhengHeiV2-Bold.otf
│   └── JDZhengHeiV2-Heavy.otf
├── assets/media/
│   └── home-banner-bg.mp4
├── references/
│   ├── jd-field-deck-system.md
│   ├── deck-structure-presets.md
│   ├── drawing-paths.md
│   ├── html-ppt-patterns.md
│   ├── jd-color-tokens.md
│   ├── page-patterns.md
│   ├── image-and-cover-guidelines.md
│   └── quality-checklist.md
└── scripts/validate-jd-deck.mjs
```

## 交付格式

完成后告诉用户：

- 生成文件路径
- 使用的场域类型和页数
- 校验命令结果
- 仍需用户补充的真实数据或素材
