---
name: nested-structure-generation-skill
description: 基于 Zero 组件库生成 Nested Structure 父子嵌套 Tab 的 React 18 + Tailwind v3 + TypeScript 组件代码。使用 Zero MCP 读取 fileKey 2057090330888527873
  / page_id 57:18 / 节点 110:1306 与 110:22408，抽取组件、tokens、变体与截图上下文；输出 atoms/composites/layouts/pages 四级目录，每组件固定 {Name}.tsx +
  types.ts + index.ts，全部样式反查 TOKENS.json，禁止魔法值。触发：/gen-component，粘贴 relay.jd.com/file/design 链接或 Zero node id，或说生成父子嵌套Tab/Nested
  Structure 组件。
allowed-tools:
- Read
- Write
- Edit
- Glob
- Grep
- Bash
- mcp__zero-design__get_design_context
- mcp__zero-design__get_screenshot
- mcp__zero-design__get_design_metadata
- mcp__zero-design__get_variables
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/local-life/Channel 频道/Page Header 头部/Nested Structure
    父子嵌套Tab/nested-structure-generation-skill-backup/nested-structure-generation-skill/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: during_design
  agentmesh-activation: explicit_only
  short-description: 基于 Zero 组件库生成 Nested Structure 父子嵌套 Tab 的 React 18 + Tailwind v3 + TypeScript 组件代码。使用 Zero MCP 读取 f…
disable-model-invocation: true
---

<!-- ABSOLUTE-PROHIBITIONS:START -->
# 绝对禁止事项（最高优先级）

> 以下规则优先级最高，任何页面、模块、组件生成都必须遵守。

## 一、禁止重画设计资产

* 禁止自行绘制 icon。
* 禁止自行绘制插画。
* 禁止自行绘制图片元素。
* 禁止用 CSS 画 icon。
* 禁止用 SVG 临时重画 icon。
* 禁止用 emoji 替代 icon。
* 禁止使用第三方 icon 库替代原设计图标。
* 禁止把已有图片、插画、装饰元素重新设计成另一种风格。

正确做法：只能引用已有资产。
如果找不到资产，必须保留占位，并标注：`TODO：缺少对应资产`。

## 二、禁止修改已确认模块

以下模块如果已经单独生成并确认，合成页面时禁止修改内部结构：

* Page Header
* 百亿补贴
* Banner
* 页面筛选栏
* 店卡 Feed

禁止行为包括：

* 禁止改模块内部布局。
* 禁止改模块内部间距。
* 禁止改模块内部 icon。
* 禁止改模块内部图片。
* 禁止改模块内部文字。
* 禁止新增模块内部装饰。
* 禁止删除模块内部元素。
* 禁止重新生成一个“相似但不一样”的模块。

合成页面时只允许组合模块，不允许重构模块。

## 三、禁止擅自新增元素

* 禁止新增规范中没有写到的 icon。
* 禁止新增规范中没有写到的按钮。
* 禁止新增规范中没有写到的标签。
* 禁止新增规范中没有写到的装饰图形。
* 禁止新增背景纹理、光效、阴影、气泡、贴纸等视觉元素。
* 禁止为了“更美观”自行补充元素。

规范没有写，就不生成。

## 四、禁止改变页面结构

页面必须严格按照以下顺序排列：

1. Page Header
2. 百亿补贴
3. Banner
4. 页面筛选栏
5. 店卡 Feed

禁止行为：

* 禁止改变模块顺序。
* 禁止模块重叠。
* 禁止模块错位。
* 禁止把 Banner 插入店卡 Feed。
* 禁止把筛选栏放到 Banner 上方。
* 禁止重复生成 Page Header。
* 禁止重复生成筛选栏。
* 禁止让 Feed 从页面顶部开始渲染。

## 五、禁止擅自改变样式

* 禁止修改字体大小。
* 禁止修改字重。
* 禁止修改颜色。
* 禁止修改圆角。
* 禁止修改阴影。
* 禁止修改渐变。
* 禁止修改模块高度。
* 禁止修改左右边距。
* 禁止修改卡片间距。
* 禁止修改设计稿中的视觉比例。

除非 md 规范明确要求修改，否则必须保持原样。

## 六、禁止擅自改文案

* 禁止改标题文案。
* 禁止改按钮文案。
* 禁止改标签文案。
* 禁止改价格文案。
* 禁止改店铺名称。
* 禁止改活动名称。
* 禁止把中文改成英文。
* 禁止为了简化布局而删减文案。

文案必须和 md 规范一致。

## 七、禁止错误处理方式

当信息缺失时，禁止自行猜测。

禁止行为：

* 禁止猜测 icon 长什么样。
* 禁止猜测图片内容。
* 禁止猜测模块尺寸。
* 禁止猜测颜色。
* 禁止猜测间距。
* 禁止自动补齐不存在的设计元素。

正确做法：

* 缺少资产：保留占位，并标注 `TODO：缺少资产`。
* 缺少尺寸：使用 md 中已有的最近一级规则。
* 缺少模块说明：不新增内容，不自行发挥。

## 八、禁止合成时重新设计

页面合成阶段只允许做以下事情：

* 创建页面容器。
* 按顺序引入已确认模块。
* 设置页面整体布局。
* 设置滚动关系。
* 设置模块之间的外部间距。

页面合成阶段禁止做以下事情：

* 禁止重新设计模块。
* 禁止重画 icon。
* 禁止替换图片。
* 禁止修改组件内部。
* 禁止新增视觉元素。
* 禁止改模块样式。
* 禁止生成和单模块不同的新版本。

## 九、最终执行原则

只组合，不重画。
只引用，不自绘。
只还原，不发挥。
只按规范生成，不自行优化。
缺什么就标注 TODO，不允许自己补。
<!-- ABSOLUTE-PROHIBITIONS:END -->


# Nested Structure GenerationSkill

把 **Zero 组件库**中的 `Nested structure 父子嵌套Tab` 1:1 还原为 **React 18 + Tailwind CSS v3 + TypeScript**。

这是设计转代码 skill，不是创意编码助手：Zero 里画了什么就翻译什么；token 不自己造，结构不自己改，尺寸不自己凑。

## Zero Source

| 用途 | Zero 节点 |
|---|---|
| Icon 组件库 | `https://relay.jd.com/file/design?id=2057090330888527873&page_id=57%3A18&node_id=110%3A1306` |
| 父子嵌套组合与频道封装 | `https://relay.jd.com/file/design?id=2057090330888527873&page_id=57%3A18&node_id=110%3A22408` |

必须使用 Zero MCP 读取这些节点。完整流程：

1. `get_design_metadata(nodeId)` 看结构、组件/实例命名、尺寸。
2. `get_design_context(nodeId)` 拿参考代码和节点映射。只能作为结构参考，不能照搬 inline absolute 样式。
3. `get_variables(nodeId)` 抽取颜色、字体、间距、圆角等 token。
4. `get_screenshot(nodeId)` 做视觉核对。

本地快照见 [`TOKENS.json`](TOKENS.json) 与 [`components/`](components/)。

## Trigger

```text
/gen-component
/gen-component nested-structure
/gen-component https://relay.jd.com/file/design?id=2057090330888527873&page_id=57%3A18&node_id=110%3A22408
/gen-component 110:22408
/gen-component 生成 父子嵌套Tab 家政频道 上划态
```

粘贴 `relay.jd.com/file/design` 链接、`110:1306`、`110:22408`，或自然语言提到 `Nested Structure` / `父子嵌套Tab` / `父子嵌套组件` 时也应触发。

## Routing

### Link Mode

输入含 Zero 链接或 node id 时：

1. 抽取 `fileKey`、`page_id`、`node_id`，把 `110-22408` 规范化为 `110:22408`。
2. 校验 `fileKey=2057090330888527873`，`page_id=57:18`。不匹配时提示属于其它组件库，不能使用本快照直接生成。
3. 按 Zero MCP 四步读取：metadata → context → variables → screenshot。
4. 匹配 [`components/`](components/) 的组件规范。
5. 所有视觉值反查 [`TOKENS.json`](TOKENS.json)。查不到即列入 unresolved tokens，不写魔法值。

### No-Link Mode

没有链接时，以本地 `TOKENS.json + components/*.md` 为唯一依据，不读 MCP，不编 token。

默认主变体：

| 组件 | 默认 |
|---|---|
| `NestedStructure` | `mode=default`, `selectedIndex=0`, `channel=waimai`, `items` 取该频道前 5 项 |
| `NestedStructureSticky` | `mode=sticky`, `selectedIndex=0`, `channel=waimai` |
| `NestedTabItem` | `state=unselected`, `mode=default`, `channel=waimai` |
| `CategoryIcon` | `channel=waimai`, `name=recommend`, `state=unselected` |
| `ChannelHeaderNested` | `channel=waimai`, `mode=default`, `withNavbar=true`, `withSearch=true` |

## Component Inventory

本 Zero 组件库不是通用 Button/Input/Card/Modal 库。实际可生成组件如下：

| 组件 | 层级 | 说明 |
|---|---|---|
| `CategoryIcon` | atoms | 单个频道 icon，支持 selected/unselected 与 channel/name 资产映射。 |
| `NestedTabItem` | atoms | 单个父级 Tab item，包含 icon、label、选中背板或胶囊。 |
| `NestedStructure` | composites | 375 容器内的父子嵌套 Tab 横向列表。 |
| `NestedStructureSticky` | composites | 上滑/内容态 375×36 横向胶囊列表。 |
| `ChannelHeaderNested` | layouts | 频道头部 + 搜索栏 + NestedStructure 的组合封装，375×197 或 375×127。 |
| `NestedStructurePageExample` | pages | 页面级示例拼装，用于视觉验收，不作为业务默认输出。 |

如果用户要求 Button/Input/Card/Modal 等通用组件，必须报告：本 Zero 源节点未包含该组件；列出上表可用组件；要求用户提供包含对应组件的 Zero 节点后再生成。

## Variant Axes

| 轴 | 合法取值 |
|---|---|
| `channel` | `waimai` / `tuangou` / `ziying` / `jiazheng` / `chaoshi` / `yexiao` |
| `mode` | `default` / `sticky` |
| `state` | `selected` / `unselected` |
| `selectedIndex` | 非负整数，默认 0 |
| `iconState` | `selected` / `unselected` |

频道资产包：

- `tuangou`: 美食团购 icon 包，节点 `110:1317`
- `waimai` / `yexiao`: 外卖&夜宵 icon 包，节点 `110:1545`
- `ziying`: 自营秒送 icon 包，节点 `110:1948`
- `jiazheng`: 家政频道 icon 包，节点 `110:2081`
- `chaoshi`: 超市秒送 icon sheet，节点 `75:330`，导出基准 168×168

## Mandatory Rules

0. **冻结覆盖（2026-06-11）**：`waimai` 选中按钮固定 `#773810`；所有选中背板固定 `#FFFFFF`；外卖首个“推荐”固定使用“全部美食/选中”icon；夜宵首个“推荐”继续使用“推荐/选中”icon；所有页面头部默认启用自动布局且不得改变任何既有间距或坐标。除这些覆盖项外不做其他更改。
1. **1:1 像素级还原**：核心尺寸必须命中 Zero，尤其是 `375×74`、`76×74`、`68×74`、`44×44`、`36×36`、`375×36`、`94×36`、`26` 高胶囊。
2. **Tokens only**：颜色、字体、间距、圆角、阴影、层级全部来自 `TOKENS.json`。`.tsx` 禁止裸 hex、裸 px、裸字号、裸圆角、裸 z-index。
3. **React + Tailwind v3 + TypeScript**：variant/state 用 union literal type；样式映射表用 `as const + Record<>`；className 用 `[...].filter(Boolean).join(' ')`。
4. **四级目录**：按 `src/components/atoms/`、`composites/`、`layouts/`、`pages/` 落文件。
5. **每组件 3 文件**：`{Name}.tsx`、`types.ts`、`index.ts`，不得合并或缺省。
6. **资产可追溯**：图片 icon 不手绘。用 `assetKey`/`src`/`spriteName` 引用，并在 unresolved assets 中列出缺失项。
7. **横向滚动不压缩**：items 超出 375 可视宽时横向滚动，不压缩 76/68/94/胶囊尺寸。
8. **频道不混用**：每个频道只能使用自己的 icon 包。外卖与夜宵共享 icon 包但背景/导航色不同；外卖首个“推荐”调用同包内“全部美食/选中”资产是唯一固定例外。
9. **状态联动**：选中态必须同时改变 icon、label、背板/胶囊，不允许只改文字颜色。
10. **Navbar 继承**：频道头部里的状态栏、搜索栏、返回/关注/分享/更多沿用 Navbar 规范；本 skill 只组合，不重造 Navbar token。
11. **头部自动布局**：`ChannelHeaderNested` 和 Page Header 外层必须默认启用纵向自动布局；内部语义行使用横向自动布局。为保留源稿位置可把直接子层设为 absolute，但启用前后 `x/y/w/h`、padding、gap 必须逐项一致。

## Must Not

- 不生成 Zero 源节点里不存在的 Button/Input/Card/Modal。
- 不用 `style={{ color/fontSize/borderRadius/zIndex }}` 写视觉值。例外仅图片背景或 CSS gradient token，且必须登记在 `TOKENS.json`。
- 不照搬 `get_design_context` 的绝对定位代码。输出要改写为 flex、gap、overflow-x 等语义布局。
- 不把 `NestedStructure` 放进 `atoms`，不把 `CategoryIcon` 放进 `layouts`。
- 不拉伸 36×36 未选中图标成选中态。
- 不给组件新增 Zero 未画出的 shadow 或动效。

## Output Contract

默认输出目录：

```text
src/components/
├── atoms/
│   ├── CategoryIcon/
│   └── NestedTabItem/
├── composites/
│   ├── NestedStructure/
│   └── NestedStructureSticky/
├── layouts/
│   └── ChannelHeaderNested/
└── pages/
    └── NestedStructurePageExample/
```

每个组件：

```text
{Name}/
├── {Name}.tsx
├── types.ts
└── index.ts
```

## Generation Steps

1. 解析输入，确定 `component/channel/mode/selectedIndex/items/out`。
2. 若输入含 Zero 节点，调用 Zero MCP 刷新上下文；否则读取本地快照。
3. 读取对应 `components/*.md`，确认 props、变体、尺寸、token。
4. 将每个视觉值映射到 `TOKENS.json` 的 token path，再映射为 Tailwind class。
5. 生成 TSX/types/index 三文件。
6. 自检：
   - 无裸 hex/px/字号/圆角；
   - union literal 与样式映射 key 完全一致；
   - 目录分级正确；
   - 375×74/default 与 375×36/sticky 尺寸关系正确；
   - 频道 icon 包不串用；
   - 缺失 token/资产列入最终摘要。

## Final Summary

完成后输出：

- 文件清单与行数；
- 使用的 token path/value/class；
- 组件 props 与 variant；
- Zero 来源节点；
- unresolved tokens；
- unresolved assets；
- 是否修改了 `tailwind.config.js`。
