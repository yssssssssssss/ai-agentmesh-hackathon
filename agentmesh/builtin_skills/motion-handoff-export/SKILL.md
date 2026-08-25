---
name: motion-handoff-export
description: 将本地 Web Demo 中可追溯的 UI 动效导出为单文件离线动效交付 HTML。适用于用户要求 UI motion handoff、动效交付、动效说明、动画时间轴、场景级多轨时间轴、组件级重播卡片、Before/After
  截图，或为 React/Vue/Web Demo 输出研发交付代码时。
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/search-recommend-foundation/skills&tools/motion-handoff-export/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
  short-description: 将本地 Web Demo 中可追溯的 UI 动效导出为单文件离线动效交付 HTML。适用于用户要求 UI motion handoff、动效交付、动效说明、动画时间轴、场景级多轨时间轴、组件级重播卡…
disable-model-invocation: true
---

# 动效交付导出

## 概述

创建一个自包含的 `motion-handoff.html`，用场景时间轴、组件重播卡片、真实截图、参数、验收标准和代码片段说明 UI 动效。skill 已在 `assets/motion-handoff-template.html` 内置 `AI Chat 2 Demo / Motion Delivery` 风格的交付页模板，不依赖使用者电脑上存在任何外部旧版 HTML 文件；生成结果应保持这套视觉：大页头摘要条、场景级动效编排、左侧真实预览、大型多轨时间轴、底部参数 inspector、组件详情卡和右侧代码抽屉。正式清单只纳入能追溯到源码或运行时行为的动效。

## 工作流

1. 识别源码和运行时中的显式动效：
   - 搜索 `animation`、`transition`、`@keyframes`、定时器驱动状态、`requestAnimationFrame`、动画库和 motion props。
   - 在确定正式动效清单前，阅读 [references/motion-identification.md](references/motion-identification.md)。
2. 截取真实 UI 状态：
   - 本地运行 Demo，并走真实交互路径。
   - 可用 Playwright 时使用 `scripts/capture-motion-states.mjs`；否则用内置浏览器或浏览器工具手动截图。
   - 将截图作为本地路径或 Data URI 写入 manifest。
3. 建模交付内容：
   - 准备包含 `title`、`sourceProject`、`scenes[]`、`motions[]` 和 `codeGroups[]` 的 manifest。
   - 当一个场景里存在并行、串行或嵌套动效时，阅读 [references/timeline-model.md](references/timeline-model.md)。
4. 生成 HTML：
   - 运行 `node scripts/build-motion-handoff.mjs --manifest <motion-manifest.json> --out <motion-handoff.html>`。
   - 生成文件会内嵌 CSS、JS、数据、截图和代码片段。
5. 校验输出：
   - 运行 `node scripts/validate-motion-handoff.mjs <motion-handoff.html>`。
   - 交付前按 [references/html-delivery-rules.md](references/html-delivery-rules.md) 核对验收标准。

## Manifest 结构

使用 JSON。ID 会成为页面锚点和交互键，必须保持稳定。

```json
{
  "title": "UI 动效交付",
  "sourceProject": "Demo 名称或路径",
  "summary": "本交付覆盖的范围。",
  "scenes": [
    {
      "id": "scene-01",
      "title": "AI 思考过程",
      "subtitle": "0-5s 场景级编排",
      "duration": 5000,
      "ticks": [0, 500, 1500, 2700, 3900, 5000],
      "frames": [{ "time": 0, "label": "初始态", "image": "captures/initial.png" }],
      "tracks": [
        {
          "label": "CoT 面板",
          "role": "父元素",
          "segments": [
            {
              "id": "cot-panel-in",
              "start": 0,
              "end": 260,
              "type": "opacity",
              "label": "面板入场",
              "properties": "opacity 0->1, translateY(6px)->0",
              "easing": "ease",
              "motionId": "motion-01"
            }
          ]
        }
      ]
    }
  ],
  "motions": [
    {
      "id": "motion-01",
      "title": "CoT 面板入场",
      "page": "AI Chat",
      "module": "CoT 面板",
      "trigger": "用户提交问题",
      "purpose": "让用户明确感知 AI 正在思考",
      "duration": 260,
      "easing": "ease",
      "properties": ["opacity 0->1", "translateY(6px)->0"],
      "beforeImage": "captures/cot-before.png",
      "afterImage": "captures/cot-after.png",
      "replay": { "kind": "rise" },
      "timeline": [{ "time": 0, "label": "开始" }, { "time": 260, "label": "结束" }],
      "acceptance": ["260ms 时面板达到完整可见状态。"],
      "codeGroupIds": ["cot-panel"]
    }
  ],
  "codeGroups": [
    {
      "id": "cot-panel",
      "title": "CoT 面板实现",
      "snippets": [
        {
          "title": "CSS 动画",
          "path": "src/styles.css",
          "start": 120,
          "end": 150
        }
      ]
    }
  ]
}
```

## 脚本

### 截取状态

```bash
node scripts/capture-motion-states.mjs --url http://127.0.0.1:5173 --plan capture-plan.json --out captures
```

截图计划支持 `viewport`、`steps` 和 `captures`。适合可重复的浏览器路径；如果路径不稳定，可以手动截图并在 manifest 中指向保存后的图片。

### 构建 HTML

```bash
node scripts/build-motion-handoff.mjs --manifest motion-manifest.json --out delivery/motion-handoff.html
```

构建脚本会读取 `assets/motion-handoff-template.html`，把本地图片转成 Data URI；当代码片段缺少 `code` 字段时，会按 `path/start/end` 抽取源码，并写出单文件 HTML。

### 校验 HTML

```bash
node scripts/validate-motion-handoff.mjs delivery/motion-handoff.html
```

当必要结构缺失、ID 重复、关联代码组不存在、图片字段为空或引用外部资源时，校验会失败。

## 交付规则

- 正式动效必须能追溯到源码、截图或运行时定时器。
- 用场景时间轴说明多个元素之间的编排关系；用组件卡片记录精确参数。
- 保留真实时长。状态切换用瞬时标记，不要拉成长条伪造成持续动画。
- 输出必须离线可用、可携带。HTML 内不要链接本机源码文件，要把代码片段内嵌到抽屉里。
