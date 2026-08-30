---
name: popup-design-skill
description: PopupGenerationSkill — 从京东 Zero/Relay「Popup 半弹层」组件库 1:1 像素级生成 React + Tailwind v3 + TypeScript 组件。 当用户粘贴 relay.jd.com
  设计链接、输入 /gen-component、或要求「生成 / 还原 / 实现」半弹层(Popup/Half Sheet)、 品类频道下拉、树形选择器、通用筛选器、一/二/三级子项、完成/重置按钮、筛选 chip、图标12*12 等 Zero
  组件时使用。 技能通过 zero-design MCP 读取设计、提取 design tokens，强制「只用 token、禁魔法值、1:1 还原」， 并按 atoms/composites/layouts/pages 原子化目录输出代码。
license: internal-jd
allowed-tools:
- mcp__zero-design__get_design_context
- mcp__zero-design__get_design_metadata
- mcp__zero-design__get_variables
- mcp__zero-design__get_screenshot
- Read
- Write
- Edit
- Bash
metadata:
  zero_file_id: '2057090330888527873'
  zero_page_id: '324:3'
  design_system: JD APP 15.0 GUIDELINE
  stack: React 18 + Tailwind v3 + TypeScript
  last_synced: '2026-06-04'
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/local-life/Channel 频道/popup半弹层/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: during_design
  agentmesh-activation: explicit_only
  short-description: PopupGenerationSkill — 从京东 Zero/Relay「Popup 半弹层」组件库 1:1 像素级生成 React + Tailwind v3 + TypeScript 组件…
disable-model-invocation: true
---

# PopupGenerationSkill · Popup 半弹层代码生成

把京东 Zero（Relay）「Popup 半弹层」组件库（file `2057090330888527873` · page `[p]Popup 半弹层`）**1:1 像素级**翻译成 **React 18 + Tailwind v3 + TypeScript**。

真相源 = Zero 设计文件本身 + 随技能附带、从该文件 `get_variables`/`get_design_context`/`get_screenshot` 实测反查得到的 [`TOKENS.json`](TOKENS.json) 与 [`components/`](components/)。本文件三大块：**§A 约束 · §B Tokens · §C 组件规范**。

> ⚠ 形态校正（实测结论）：本文件的「半弹层」是**品类频道下拉**——面板锚定屏幕**顶部**、**底部两角圆角**(`rounded-b-sheet`=12)、全屏 70% 蒙层在面板**下方**、自顶部下滑入场。与 design-notes(331:721) 文字「底部上滑」不同，**以实测组件为准**。

---

## §A 约束（强制 / 不可协商）

1. **1:1 像素级还原 Zero**
   每个尺寸/颜色/字重/间距/圆角都能在 §B 或 §C 反查到来源节点。生成后**必须**用 `get_screenshot` 与 Zero 原稿目视比对（§D Step 4）。

2. **只用 Token，禁止裸魔法值**
   代码里**不允许**出现 `#FF0F23`、`12px`、`rgba(0,0,0,.7)` 等裸值；全部走 §B 的 token → Tailwind class。
   唯一例外（已登记为 token）：高度 `h-[46vh]/[80vh]/[87vh]`、宽 `max-w-[375px]`、热区 `min-h-[44px]`。

3. **技术栈固定：React 18 + Tailwind v3 + TypeScript**
   函数组件 + hooks，`.tsx`；每组件导出 `Props` 接口；不引第三方 UI 库；动画用 Tailwind transition + token 化 `duration/ease`；不把 Tailwind 装进目标项目依赖（假定已配置 §B 的 `tailwind.config`）。每组件落 `Xxx.tsx + types.ts + index.ts` 三文件。

4. **原子化目录（强制）**
   ```
   src/components/
   ├── atoms/        Icon · Chip · Button
   ├── composites/   TreeItem · TreeSelector · FilterPanel
   ├── layouts/      HalfSheet（蒙层 + 底圆角面板 + 顶部下拉动效）
   └── pages/        CategoryChannelPopup（一/两/三列）· FilterPopup
   ```

5. **选中态三件套缺一不可**：字重 400→500 **+** 配色翻转(灰黑→`brand` 红) **+** 红勾/红字。
   （L1 左红勾、L3 右红勾、L2 以红字代红勾——见 §C。）

6. **半弹层形态锁定**：`anchor="top"` 默认 → `rounded-b-sheet`(底圆角) + 自顶下滑 + 全屏 `bg-mask`(70%) 在下 + 点蒙层关闭 + `shadow-none`。

### Don't（违反即判不合格）
- ❌ 直接交付 `get_design_context` 的参考代码（绝对定位 / 裸 hex / svg 占位）——必须改写为 token 化 flex/grid。
- ❌ 任意裸色值 / 裸 px / 裸 rgba（除已登记 `vh` / `375px` / `44px`）。
- ❌ 圆角方向搞反（top 锚定必须 `rounded-b-sheet`）；❌ 四角全圆；❌ 加 `shadow-*`。
- ❌ 选中只改其一；❌ 三级子项布局统一（必须按 level 区分左勾/右勾/无勾、px-3/px-4、行底/列右分割线）。
- ❌ 蒙层非 70% 或非 `bg-mask`；❌ 用淡入/缩放替代滑动；❌ 移除点蒙层关闭。
- ❌ 「完成」非 `bg-brand` 或弱化为次按钮；❌ 高度偏离 46/80/87（常规 80），内容少压缩自适应。
- ❌ chip 自定义字号/圆角（必须 `text-body` + `rounded-chip`，复用 [Chip](components/Chip.md)）。

---

## §B Tokens（生成代码只准用「class」列；完整版见 [TOKENS.json](TOKENS.json)）

### 颜色
| 用途 | Zero 实测 | class |
|---|---|---|
| 京东红 / 选中 / 完成底 | `color_primary` `#FF0F23` | `bg-brand` / `text-brand` |
| 选中浅红底 | `color_primary_light` `#FFF0F4` | `bg-brand-light` |
| 主按钮文字 | `color-primary-text` `#FFFFFF` | `text-on-color` / `text-brand-foreground` |
| 面板 / 行底（白） | `color-background-overlay` `#FFFFFF` | `bg-overlay` |
| 页面沉底 | `color_background` `#F2F3F7` | `bg-page` |
| 重置按钮浅底 | `color-background` `#F2F2F4` | `bg-gray` |
| chip 默认底 | `color-background-sunken` `#F7F8FC` | `bg-sunken` |
| 两列目录列/容器底 | `#FAFAFA`（变量未登记） | `bg-directory` |
| 标题 / 分组标题 | `color_title` `#171A26` | `text-title` |
| 子项默认文字 | `color_text` `#3D414D` | `text-content` |
| 分割线（行底/列右，0.5px） | `color_border` `#00000014` (8%) | `border-line` |
| 禁用 / 轨道 | `color_border_disabled` `#C2C4CC` | `border-disabled` |
| 全屏蒙层 | `color_mask` `#000000B2` (70%) | `bg-mask` |

### 字体（PingFang-SC）
| 角色 | 实测 | class |
|---|---|---|
| 子项 / chip 正文 | 12 / lh16 / 400 | `text-body font-normal` |
| 选中态 | 12 / lh16 / **500** | `text-body font-medium` |
| 筛选分组标题 | 14 / lh20 / 600 | `text-group font-semibold` |
| 完成 / 重置 按钮 | 16 / lh24 / 600 | `text-button font-semibold` |
| 人均价数值 | 京东正黑 | `font-number` |

### 圆角 / 间距 / 尺寸 / 动效 / 层级
| 类目 | 实测 | class |
|---|---|---|
| 面板圆角（底两角） | 12 | `rounded-b-sheet` |
| 按钮 / 内卡圆角 | 8 | `rounded-button` |
| chip 圆角 | 4 | `rounded-chip` |
| L1 行内边距 / 图文间距 | left12 / gap4 | `px-3` / `gap-1` |
| L2 行内边距 / 图文间距 | left16 / gap12 | `px-4` / `gap-3` |
| L3 行内边距 | left16 | `px-4` |
| 容器 / 筛选内边距 | 20 | `p-5` |
| 筛选分组间距 | 28 | `gap-7` |
| 树形分组间距 | 40 | `gap-10` |
| 行高 | 40 | `h-10` |
| 图标 | 12 | `size-3` |
| 容器宽 | 375 | `w-full max-w-[375px]` |
| 最小热区 | 44 | `min-h-[44px]` |
| 高度三档 | 46/80/87 vh | `h-[46vh]`/`h-[80vh]`/`h-[87vh]` |
| 入场（自顶下滑） | 300ms 减速 | `duration-sheet-in ease-decelerate` |
| 出场（上滑） | 200ms 加速 | `duration-sheet-out ease-accelerate` |
| 蒙层层级 / 面板层级 | 1000 / 1001 | `z-mask` / `z-sheet` |
| 阴影 | 无 | `shadow-none` |

### `tailwind.config.js`（由 TOKENS.json 生成，目标项目无此配置时由本技能补）
```js
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: { extend: {
    colors: {
      brand: { DEFAULT: '#FF0F23', light: '#FFF0F4', foreground: '#FFFFFF' },
      page: '#F2F3F7', gray: '#F2F2F4', overlay: '#FFFFFF', sunken: '#F7F8FC', directory: '#FAFAFA',
      title: '#171A26', content: '#3D414D', 'on-color': '#FFFFFF',
      line: '#00000014', disabled: '#C2C4CC', mask: 'rgba(0,0,0,0.7)',
    },
    fontFamily: {
      sans: ['"PingFang SC"', 'system-ui', 'sans-serif'],
      number: ['JDZhengHei', '"PingFang SC"', 'sans-serif'],
    },
    fontSize: { body: ['12px','16px'], group: ['14px','20px'], button: ['16px','24px'] },
    borderRadius: { sheet: '12px', button: '8px', chip: '4px' },
    transitionTimingFunction: { decelerate: 'cubic-bezier(0,0,0.2,1)', accelerate: 'cubic-bezier(0.4,0,1,1)' },
    transitionDuration: { 'sheet-in': '300ms', 'sheet-out': '200ms' },
    zIndex: { mask: '1000', sheet: '1001' },
  }},
  plugins: [],
}
```
> 间距 4/8/12/16/20/28/40px 全命中 Tailwind 默认 4px 栅格（`p-1/2/3/4/5/7/10`…），**不扩展 spacing**，直接用默认 class 即视为 token 化。

---

## §C 组件规范（摘要 + 变体矩阵；完整 Canonical 代码见各 `components/*.md`）

> 组件 → Zero 节点 → 规格文件：

| 组件 | Zero nodeId | 规格 |
|---|---|---|
| 半弹层-品类频道（一/两/三列） | `331:1281`（`331:1275/1277/1279`） | [HalfSheet](components/HalfSheet.md) · [CategoryChannelPopup](components/CategoryChannelPopup.md) |
| 树形选择器（12 变体） | `324:6822` | [TreeSelector](components/TreeSelector.md) |
| 一/二/三级子项 | `324:6009` `324:6120` `324:6191` | [TreeItem](components/TreeItem.md) |
| 通用筛选器 | `331:977` | [FilterPanel](components/FilterPanel.md) |
| 完成/重置 按钮 | `331:977` 内 | [Button](components/Button.md) |
| 筛选 chip | `331:977` 内 | [Chip](components/Chip.md) |
| 图标12*12（默认/对号） | `324:5588`（`324:5584`/`324:5608`） | [Icon](components/Icon.md) |

### C1 · atoms/Icon — 图标12*12
- 12×12，颜色走 `currentColor`（父级 `text-brand`）。变体 `default`(324:5584) / `check`(324:5608 红勾)。
- 选中插入 `check`：L1 行首左、L3 行尾右。

### C2 · atoms/Chip — 筛选标签（复用 Tag Button）
| 状态 | 底 | 文字 | 圆角 |
|---|---|---|---|
| 默认 | `bg-sunken` | `text-content font-normal` | `rounded-chip` |
| 选中 | `bg-brand-light` | `text-brand font-medium` | `rounded-chip` |
- 视觉高 ≈36，热区 `min-h-[44px]`。

### C3 · atoms/Button — 完成 / 重置
| variant | 底 | 文字 |
|---|---|---|
| `primary`（完成） | `bg-brand` | `text-on-color font-semibold` |
| `secondary`（重置） | `bg-gray` | `text-title font-semibold` |
- `h-12` `rounded-button` `text-button`；底部按钮组 `重置 flex-1` + `完成 flex-[2]`，`gap-3`。

### C4 · composites/TreeItem — 一/二/三级子项 ⚠ 三级布局**不同**
| 维度 | L1（目录列） | L2（中间列） | L3（内容列） |
|---|---|---|---|
| 内边距 | `px-3`(12) | `px-4`(16) | `px-4`(16) |
| 图文间距 | `gap-1`(4) | `gap-3`(12) | — |
| 选中标记 | **左**红勾 | **无**（红字） | **右**红勾 |
| 分割线 | 行底 `border-b` | 列右 `border-r` | 行底 `border-b` |
- 全级：`h-10` · `text-body` · 默认 `text-content font-normal` · 选中 `text-brand font-medium` · 行底 `bg-overlay` · 分割线 `border-line`(8%) · 末行 `last` 去线。

### C5 · composites/TreeSelector — 树形选择器
- 单列纵向滚动 `overflow-y-auto bg-overlay`；`level` 透传 TreeItem；末行传 `last`。
- 变体 = 层级×数量（2/4/8/10 为档位，数据驱动）。

### C6 · composites/FilterPanel — 通用筛选器
- 分组：配送 / 人均价(slider ¥9.9–¥100+) / 速度 / 商家特色 + 底部 重置·完成。
- 标题 `text-group font-semibold text-title`；组间距 `gap-7`；chip 网格 `gap-3`；价格数值 `font-number text-brand`；轨道 `bg-disabled`、已选段 `bg-brand`。
- ⚠ slider/chip/按钮精确 px 主稿无标注，落地前 `get_design_context(331:977)` 复核。

### C7 · layouts/HalfSheet — 半弹层容器（品类频道下拉）
- `anchor="top"`：面板贴顶、`rounded-b-sheet`(底圆角)、自顶下滑、全屏 `bg-mask`(70%) 在下、点蒙层关闭、`shadow-none`。
- 高度 `h-[80vh]`(常规) / `46` / `87`；`z-sheet` 面板、`z-mask` 蒙层；portal 到 body + 锁滚动 + 两段式进/退场动画。
- 备 `anchor="bottom"`（通用底部 sheet，圆角/滑向自动翻转）。

### C8 · pages/CategoryChannelPopup — 一/两/三列
- `HalfSheet(anchor=top)` + N×`TreeSelector`；列数=变体（`columns.length`）；L1 目录/L2 中间/L3 内容；列右分割线由 L2 `border-r` 提供。

---

## §D 工作流（粘贴链接 / `/gen-component` 触发后）

**Step 0 解析输入**：链接抽 `node_id`（`324-5502`→`324:5502`）；组件名查 §C 表；为空则问用户。
**Step 1 读 Zero**：`get_design_metadata`(看骨架，827 节点主稿按子 frame 分块) → `get_variables`(对账 §B) → `get_design_context`(仅参考) → `get_screenshot`(留比对)。
**Step 2 反查 Token**：把 context 里每个裸值映射回 §B 的 class（`#3D414D`→`text-content`、`#FF0F23`→`text/bg-brand`、`12/16/400`→`text-body font-normal`、`weight500`→`font-medium`、底圆角12→`rounded-b-sheet`、`left12`→`px-3`、`left16`→`px-4`、`gap4`→`gap-1`、`gap12`→`gap-3`、`h40`→`h-10`、`#000000B2`→`bg-mask`、`rgba(0,0,0,0.08)`→`border-line`）。命中不了就停下提 token-miss，**不硬编码**。
**Step 3 生成**：按 §A.4 目录落盘，复用已存 atoms/composites，文件头加溯源注释，照 §C / `components/*.md` 的 Canonical 段产出。
**Step 4 自校验（必做）**：① 再 `get_screenshot` 与 Step1 比对（底圆角12 / 蒙层70% / 行高40 / L1左勾L2红字L3右勾 / 按钮红底 / 下滑动效）；② 跑禁魔法值自检 `grep -nE '#[0-9a-fA-F]{3,8}|[0-9]+px|rgba?\(' src/components`（应只剩 vh/375px/44px 或注释）；③ 回答给 ✅/⚠ 比对表。

---

## §E 触发方式
- **一键命令（推荐）·Zero 模式**：`/jd-now-ui 【Zero 链接】` —— 走 §D 四步（MCP 读取→匹配→生成→自校验）并落盘三文件结构。
- **一键命令·离线模式**：`/jd-now-ui 【组件描述】`（不带链接）—— 走 §G，仅以本地规范+TOKENS 生成，未指定维度取标准主变体。例：`/jd-now-ui 生成一个次按钮，尺寸lg，禁用状态`。
- **命令**：`/gen-component [组件名或 Zero 链接]`（交互式，见 `.claude/commands/gen-component.md`）。
- **粘贴链接 / 自然语言**：贴 `relay.jd.com/file/design?...` 或「生成/还原 + 组件名」即命中本技能描述。

---

## §F Prompt Template（`/jd-now-ui` 一键模板 · 可直接复制使用）

> 把 `<ZERO_NODE>` 换成 Zero 链接或 node_id 即可。`/jd-now-ui` 命令内部即用此模板；手动粘贴也等效。

```text
你是 PopupGenerationSkill。严格按 popup-design-skill 规范，把下面的 Zero 节点 1:1 生成 React 18 + TypeScript + Tailwind v3 代码，全自动、不反问（输入为空才问一次）。

【输入节点】<ZERO_NODE>

【执行】
1. 解析 node_id：relay.jd.com/...&node_id=324:6009 → 324:6009；324-6009 → 324:6009。
2. MCP 读取（依次）：get_design_metadata → get_variables → get_design_context（仅参考，禁直接交付）→ get_screenshot（留比对）。
3. 反查 token（禁魔法值）：把每个裸值映射到 TOKENS.json 的 class——
   #FF0F23→brand · #FFF0F4→bg-brand-light · #FFFFFF→bg-overlay/text-on-color · #171A26→text-title ·
   #3D414D→text-content · #00000014或rgba(0,0,0,0.08)→border-line · #000000B2→bg-mask · #F2F2F4→bg-gray ·
   #F7F8FC→bg-sunken · 12/16/400→text-body font-normal · weight500→font-medium · 14/600→text-group font-semibold ·
   16/600→text-button font-semibold · 底圆角12→rounded-b-sheet · 圆角8→rounded-button · 圆角4→rounded-chip ·
   left12→px-3 · left16→px-4 · gap4→gap-1 · gap12→gap-3 · h40→h-10 · 12×12→size-3。
   命中不了任何 token → 停下标 ⚠ token-miss，禁硬编码。
4. 匹配组件 & 自动分层：
   Icon/Chip/Button→atoms；TreeItem/TreeSelector/FilterPanel→composites；HalfSheet→layouts；CategoryChannelPopup/FilterPopup→pages。
   表外节点按结构推断：叶子→atoms，组合 atoms→composites，全屏含蒙层容器→layouts，装配成屏→pages。
   参照 components/<Name>.md 的 Canonical 实现。
5. 落盘 3 文件：
   src/components/<layer>/<Name>/<Name>.tsx（文件头注释 // Zero: file 2057090330888527873 · node <id> · synced 2026-06-04）
   src/components/<layer>/<Name>/types.ts（export interface <Name>Props）
   src/components/<layer>/<Name>/index.ts（export { <Name> }; export type { <Name>Props }）
   复用已存在的下层组件；若缺 tailwind.config.js 或 token，按 SKILL.md §B 补。
6. 自校验：再 get_screenshot 比对（底圆角12 / 蒙层70% / 行高40 / 选中三件套[L1左勾·L2红字·L3右勾] / 按钮红底 / 下滑动效）；
   grep -nE '#[0-9a-fA-F]{3,8}|[0-9]+px|rgba?\(' src/components（应只剩 vh/375px/44px 或注释）；输出 ✅/⚠ 比对表 + 文件清单。

【硬约束】1:1 像素级；只用 token 的 class，禁裸 #hex/px/rgba（仅 vh/375px/44px 例外）；
选中三件套（字重400→500 + 配色翻 brand + 红勾/红字）；半弹层 anchor=top + rounded-b-sheet + 全屏 bg-mask(70%)在下 + 点蒙层关闭；
TreeItem 按 level 区分布局（L1 px-3 gap-1 左勾 border-b / L2 px-4 gap-3 无图标 border-r / L3 px-4 右勾 border-b）；shadow-none；三文件结构。
```

---

## §G 无链接调用（离线生成 · 唯一依据 = 本地规范 + TOKENS.json）

`/jd-now-ui` 按输入**自动分流**：

| 输入形态 | 模式 | 行为 |
|---|---|---|
| 含 `relay.jd.com` / `node_id=` / 形如 `\d+:\d+` | **Zero 模式** | 走 §D 四步：MCP 读取 → 匹配 → 生成 → 截图自校验 |
| 自然语言（组件名 [+变体/尺寸/状态]） | **离线模式** | **不调用 MCP**，仅以 [`TOKENS.json`](TOKENS.json) + `components/*.md` 为唯一依据生成；未指定的维度取**标准主变体**默认值 |
| 完全为空 | **菜单** | 打印下方「参数目录」并问生成哪个组件 |

### G1 · 参数目录（**加粗 = 默认/标准主变体**）

| 组件（层） | 维度 → 取值 |
|---|---|
| **atoms/Icon** | `name`: **default** \| check(对号红勾) |
| **atoms/Chip** | `state`: **default** \| selected \| disabled |
| **atoms/Button** | `variant`: **primary(完成)** \| secondary(重置)；`size`: sm \| **md** \| lg；`state`: **default** \| disabled；`block` |
| **composites/TreeItem** | `level`: **1** \| 2 \| 3；`state`: **default** \| selected |
| **composites/TreeSelector** | `level`: **1** \| 2 \| 3；`count`: 数据驱动（默认示例 4 项） |
| **composites/FilterPanel** | 默认示例分组（配送 / 人均价 / 速度 / 商家特色）+ 重置·完成 |
| **layouts/HalfSheet** | `anchor`: **top** \| bottom；`height`: **regular(80vh)** \| min(46) \| max(87) |
| **pages/CategoryChannelPopup** | `columns`: **1** \| 2 \| 3 |

### G2 · 自然语言 → 参数（解析词表）

- **组件**：主按钮/完成→Button·primary｜次按钮/重置→Button·secondary｜chip/标签/筛选项→Chip｜图标/icon，对号/勾→Icon(check)｜一级/二级/三级 子项→TreeItem(level)｜树形选择器/选择列→TreeSelector｜筛选器/通用筛选→FilterPanel｜半弹层/弹层/下拉/sheet→HalfSheet｜品类频道/一列/两列/三列→CategoryChannelPopup(columns)
- **尺寸**：小/sm｜中/md｜大/lg　**状态**：选中/selected｜禁用/disabled｜默认/default
- **其他**：占满/block｜最高/max·最低/min·常规/regular｜底部/bottom

### G3 · 示例

| 输入 | 解析 | 落盘 |
|---|---|---|
| `/jd-now-ui 生成一个次按钮，尺寸lg，禁用状态` | Button `{variant:secondary, size:lg, state:disabled}` | `src/components/atoms/Button/` |
| `/jd-now-ui 主按钮` | Button `{primary, md, default}`（标准主变体） | `atoms/Button/` |
| `/jd-now-ui 占满宽的完成按钮` | Button `{primary, md, block}` | `atoms/Button/` |
| `/jd-now-ui 选中态的筛选 chip` | Chip `{selected}` | `atoms/Chip/` |
| `/jd-now-ui 三级子项 选中` | TreeItem `{level:3, selected}` | `composites/TreeItem/` |
| `/jd-now-ui 树形选择器 二级 8项` | TreeSelector `{level:2, count:8}` | `composites/TreeSelector/` |
| `/jd-now-ui 两列品类频道` | CategoryChannelPopup `{columns:2}` | `pages/CategoryChannelPopup/` |
| `/jd-now-ui 半弹层 最大高度` | HalfSheet `{anchor:top, height:max}` | `layouts/HalfSheet/` |
| `/jd-now-ui` | —（无参） | 打印 G1 目录并问要哪个 |

### G4 · 离线 = 同样 token-pure

离线模式**仍禁魔法值**：只用 `TOKENS.json` 的 class；`sm/lg` 尺寸走 4px 栅格（`h-10/12/14`）、`disabled` 走标准 `opacity-40` 工具——凡 Zero 未实测的扩展项一律标 ⚠「离线扩展，接真 Zero 后以实测覆盖」。落盘后同样跑 `grep` 自检（§D Step4），输出 ✅/⚠ 表 + 文件清单。

---

> 仅覆盖 `2057090330888527873` 这一 Zero 文件的 Popup 组件族。换文件时复用「读 Zero → 反查 token → 原子化生成 → 截图自校验」四步法，按新文件重建 [`TOKENS.json`](TOKENS.json) 与 [`components/`](components/)。
