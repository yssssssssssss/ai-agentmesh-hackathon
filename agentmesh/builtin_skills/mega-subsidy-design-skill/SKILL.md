---
name: mega-subsidy-design-skill
description: MegaSubsidyGenerationSkill — 从京东 Zero/Relay「Mega Subsidy 百亿补贴」组件库 1:1 像素级生成 React 18 + Tailwind v3 + TypeScript
  组件。当用户粘贴 relay.jd.com 设计链接、输入 /gen-component、 或要求「生成 / 还原 / 实现」百亿补贴(百补)相关组件——商品图、百补价格徽标(button组件)、百补商品卡、 百补标题、百补组件封装、外卖/自营秒送/家政/家政营销
  业务变体等 Zero 组件时使用。技能通过 zero-design MCP 读取设计、提取 design tokens，强制「只用 token、禁魔法值、1:1 还原」，并按 atoms/composites/layouts/pages 原子化目录输出代码。
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
  zero_page_id: 72:11997
  zero_node_id: 149:90
  design_system: JD APP 15.0 GUIDELINE
  stack: React 18 + Tailwind v3 + TypeScript
  last_synced: '2026-06-16'
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/local-life/Channel 频道/Mega Subsidy 百亿补贴/mega-subsidy-design-skill-bundle/mega-subsidy-design-skill/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: during_design
  agentmesh-activation: explicit_only
  short-description: MegaSubsidyGenerationSkill — 从京东 Zero/Relay「Mega Subsidy 百亿补贴」组件库 1:1 像素级生成 React 18 + Tailwind v3…
disable-model-invocation: true
---

# MegaSubsidyGenerationSkill · Mega Subsidy 百亿补贴 代码生成

把京东 Zero（Relay）「**Mega Subsidy 百亿补贴**」组件库（file `2057090330888527873` · page `72:11997` · 主稿 node `149:90`）**1:1 像素级**翻译成 **React 18 + Tailwind v3 + TypeScript**。

真相源 = Zero 设计文件本身 + 随技能附带、从该文件 `get_variables`/`get_design_context`/`get_screenshot` 实测反查得到的 [`TOKENS.json`](TOKENS.json) 与 [`components/`](components/)。本文件四大块：**§A 约束 · §B Tokens · §C 组件规范 · §D 工作流**。

> 💡 形态说明：本组件库是**本地生活频道「百亿补贴」营销组件族**，核心是按**业务线**横向扩展同一套结构——`外卖 / 自营秒送 / 家政 / 家政营销`。同一组件（如商品卡）在不同业务线下，差异只在「角标样式 + 价格表达 + 标题文案」，**结构与 token 复用**。生成时优先复用下层 atoms，按 `biz` 维度切变体，**禁止为每条业务线重写一份**。

---

## §A 约束（强制 / 不可协商）

1. **1:1 像素级还原 Zero**
   每个尺寸/颜色/字重/间距/圆角都能在 §B 或 §C 反查到来源节点。生成后**必须**用 `get_screenshot` 与 Zero 原稿目视比对（§D Step 4）。

2. **只用 Token，禁止裸魔法值**
   代码里**不允许**出现 `#FF0F23`、`#C70512`、`11px`、`rgba(0,0,0,.1)`、`linear-gradient(...)` 等裸值；全部走 §B 的 token → Tailwind class。
   唯一登记的 px/渐变例外（已是 token / asset-native 尺寸）：商品图/卡片宽 `w-image`/`h-image`/`w-card`（=75）、`border-hairline`（0.5px）、模块根内描边 `border-module border-module-stroke`（#FFFFFF / 1px / INSIDE）、更多箭头描边 `stroke-more`（0.8px）与 `gap-0`、模块背景 `bg-module-mega`（参考 `7:104;7:105` 的渐变；Zero/Relay 使用精确 `gradientTransform=[[0.2087924948,0.6604530948,0.2351507096],[-0.6604530948,0.0484862041,0.7817403069]]`）、卡片行 `gap-[13px]`、3px 系列 `gap-[3px]`/`h-[3px]`/`size-[3px]`（现价↔原价间距 / 滚动点）、hot 角标 `w-hot-tag`/`h-hot-tag`（43×13）与 `right-hot-label-gap`（3.75px）、Title 容器 `w-title-mega h-9`（190×36）、SubsidyPrice 固定 75 布局 token（`w-price-chip` / `w-price-value` / `w-price-badge` / `left-price-badge-x` / `left-price-bolt-x` / `right-price-bolt-gap` / `left-price-badge-text-x` / `top-price-badge-text-y`）、SubsidyPrice badge 资产 `assets/subsidy-badge-gradient.svg`（44×16）、家政低价标整图 `h-[13px]`（内置 PNG `assets/home-lp-badge@3x.png`，原稿 91×13）。

3. **技术栈固定：React 18 + Tailwind v3 + TypeScript**
   函数组件 + hooks，`.tsx`；每组件导出 `Props` 接口；不引第三方 UI 库；不把 Tailwind 装进目标项目依赖（假定已配置 §B 的 `tailwind.config`）。每组件落 `Xxx.tsx + types.ts + index.ts` 三文件。

4. **原子化目录（强制）**
   ```
   src/components/
   ├── atoms/        BizTag · SubsidyPrice · PriceCompare · MoreEntry · Pagination
   ├── composites/   ProductImage · ProductCard · SubsidyTitle
   ├── layouts/      SubsidyModule（百补标题 + 商品卡横向行 gap-[13px] + 滚动指示点）
   └── pages/        MegaSubsidyPage（多业务线模块组装的示例页）
   ```

5. **业务线 `biz` 是一等维度**：`'takeout'(外卖) | 'instant'(自营秒送) | 'home'(家政) | 'home-promo'(家政营销)`。
   同一组件用一个 `biz` prop 切换角标/价格/文案，**不复制组件**。`biz` → 角标(BizTag)/价格(SubsidyPrice vs PriceCompare)/标题文案 的映射见 §C。

6. **三支红不可互换**：价格&补贴徽标 `brand`(#FF0F23) · 百补标题主文案 `subsidy`(#C70512) · 店铺名/外卖图描边 `shop`(#900210)。价格数字一律 `font-number`，中文一律 `font-sans`，『爆品一口价』走 `font-hot`。

### Don't（违反即判不合格）
- ❌ 直接交付 `get_design_context` 的参考代码（绝对定位 / 裸 hex / svg 占位）——必须改写为 token 化 flex/grid。
- ❌ 任意裸色值 / 裸 px / 裸 rgba / 裸 linear-gradient（除已登记 `w-image`/`h-image`/`w-card`/`border-hairline`/`border-module`/`border-module-stroke`/`stroke-more`/`gap-0`/`bg-module-mega`/`w-hot-tag`/`h-hot-tag`/`right-hot-label-gap`/`w-title-mega`/`w-price-*`/`left-price-*`/`top-price-*`/`right-price-bolt-gap`/`gap-[3px]`）。
- ❌ 使用 `Background / local subsidy-bg-mega lossless PNG` 或 `subsidy-bg-mega@3x.png` 作为外卖/自营模块背景；必须改用 `bg-module-mega` 根容器渐变。
- ❌ 把三支红混用（标题用 `brand` 或价格用 `subsidy`）；❌ 价格数字用 `font-sans`；❌ 角标渐变写成裸 `linear-gradient`（用 `bg-tag-self`）。
- ❌ 为每条业务线复制一份组件（必须 `biz` 维度切变体）；❌ 商品图圆角丢失（恒 `rounded-image`=6）；❌ 角标圆角用错（恒 `rounded-tag`=2）。
- ❌ 百补价 chip 四角全圆（只 `rounded-l-badge`，右侧接补贴尖角）；❌ 给卡片/徽标加 `shadow-*`。
- ❌ 家政现价丢失划线原价（`PriceCompare` 必含 `text-price-old line-through`）；❌ 划线价用 `text-content` 而非 `text-disabled`。

---

## §B Tokens（生成代码只准用「class」列；完整版见 [TOKENS.json](TOKENS.json)）

### 颜色
| 用途 | Zero 实测 | class |
|---|---|---|
| 百补价数字 / 『补X.X』『抢』徽标红 | `color_primary` `#FF0F23` | `text-brand` / `bg-brand` |
| 百补价 chip 浅红底 | `color_primary_light` `#FFF0F4` | `bg-brand-light` |
| 百补标题主文案（深红） | `#C70512` | `text-subsidy` |
| 店铺名 / 外卖图描边（深红） | `#900210`/`#900211` | `text-shop` / `border-shop` |
| 家政现价 | `#FF253D` | `text-price` |
| 标题文本 | `color_title` `#11141A` | `text-title` |
| 菜品名 / 描述文本 | `color_text` `#3D414D` | `text-content` |
| 『更多』文字 | `#505259` | `text-muted` |
| 划线原价 | `color_border_disabled` `#C2C4CC` | `text-disabled` |
| 徽标白字 / 反白 | `#FFFFFF` | `text-on-color` |
| 卡片 / 模块底（白） | `#FFFFFF` | `bg-overlay` |
| 外卖/自营模块渐变底 | `#FFE1E1 → #FFFFFF@53.6126%`；Zero `gradientTransform=[[0.2087924948,0.6604530948,0.2351507096],[-0.6604530948,0.0484862041,0.7817403069]]` | `bg-module-mega` |
| 外卖/自营模块 1px 内描边 | `#FFFFFF` + `1px INSIDE` | `border-module-stroke` + `border-module` |
| 分割线 / 卡片描边 8% | `color_border` `#11141A14` | `border-line` |
| 家政/自营图 0.5px 内描边 10% | `rgba(0,0,0,.1)` | `border-image` |
| 自营秒送角标底 | `#FF3333` | `bg-tag-instant` |
| 『秒送』金棕文字 | `#665005` | `text-tag-instant-fg` |
| 自营角标渐变底 | `#FF3D4C→#F92B18` | `bg-tag-self` |
| 『爆品一口价』金字 | `#FADEBF` | `text-tag-hot-fg` |

### 字体（族）
| 族 | 实测 | class | 用途 |
|---|---|---|---|
| PingFang SC | `PingFang-SC` | `font-sans` | 全部中文文本 |
| 京东正黑 / JDZhengHT | `京东正黑-V2.2`/`JDZhengHT`/`JDZhengHT-EN` | `font-number` | **所有价格数字** |
| 造字工房品宋体 | `造字工房品宋体` | `font-hot` | 『爆品一口价』 |
| 京东朗正体**2.0** | `jingdonglangzhengti2`(Bold) | `font-grab` | grab 价『抢』（**带 2.0** 版，非无2.0版、非 PingFang） |

### 字号 / 字重（role；size·lineHeight·weight）
| 角色 | 实测 | class |
|---|---|---|
| 百补价整数 | 14·12·700 | `text-price-int font-number font-bold` |
| 百补价小数 | 9·8·700 | `text-price-dec font-number font-bold` |
| 家政现价 | 16·16·400 | `text-price-now font-number` |
| 家政原价（划线） | 12·14·400 | `text-price-old font-number line-through` |
| 『补X.X』徽标 | 9·9·400 | `text-badge`（『抢』加 `font-bold`） |
| 自营/秒送 角标 | 10·9·500 | `text-tag font-medium` |
| 爆品一口价 | 11·10·400；文本框 36×10；Relay transform `[[1,-0.1051042353,3.25],[0,1,1.5]]` | `text-hot font-hot -skew-x-6 inline-block` |
| 百补标题主文案 / Title「超级补贴」 | 16·16·600 | `text-subsidy-title font-semibold` |
| 京东自营 全网低价 | 10·10·500 | `text-lp-badge font-medium` |
| 店铺名 | 11·10·500 | `text-shop font-medium` |
| 菜品名 | 11·10·400 | `text-dish` |
| 描述（随时退…） | 10·10·400 | `text-desc` |
| 更多 | 11·10·400 | `text-more` |

### 圆角 / 描边 / 间距 / 尺寸
| 类目 | 实测 | class |
|---|---|---|
| 模块容器圆角(四周) | 12 | `rounded-xl`(默认) + `overflow-hidden` |
| 商品图圆角 | 6 | `rounded-image` |
| 百补价整体容器 | 4（四角） | `rounded-badge` |
| 百补价 chip 子层 | 4（仅左两角） | `rounded-l-badge` |
| 角标圆角 | 2 | `rounded-tag` |
| 描边宽 | 0.5px | `border-hairline` |
| 模块内描边 | 1px | `border-module` |
| 商品图 / 卡片宽 | 75 | `size-image` / `w-card` |
| 角标高 | 14 | `h-[14px]` |
| 百补价高 | 16 | `h-4` |
| 更多 chevron | 12，描边 0.8，path `M4.5 3L7.5 6L4.5 9` 居中 | `size-3` + `stroke-more` |
| More 文字↔chevron | 0 | `gap-0` |
| 百补价整体容器 | 75×16 | `w-card h-4 rounded-badge bg-brand-light overflow-visible` |
| 百补价 badge | x31 / w44 / right=75 | `left-price-badge-x w-price-badge` + `assets/subsidy-badge-gradient.svg` |
| 百补价 bolt | 9×17 / x30 / bottom0 / right36 | `w-price-bolt h-price-bolt left-price-bolt-x right-price-bolt-gap` |
| 百补价补贴文案 | x42 / y3.5 / 27×9 | `left-price-badge-text-x top-price-badge-text-y w-price-badge-text h-price-badge-text` |
| hot 角标容器 | 43×13 | `w-hot-tag h-hot-tag` |
| hot 文案右距 | 3.75 | `right-hot-label-gap` |
| Title 容器 | 190×36 | `w-title-mega h-9` |
| 卡片纵向间距 / 图文间距 | 4 | `gap-1` |
| 信息块行距 / 徽标横内距 | 6 | `gap-1.5` / `px-1.5` |
| 百补价 chip 横/纵内距 | 8 / 2 | `px-2` / `py-0.5` |
| 百补标题内边距 | 10 | `p-2.5` |
| 更多 上下内距 | 12 | `py-3` |
| 模块卡片行内边距 | 10 | `px-2.5` |
| 模块卡片横向间距 | 13 | `gap-[13px]`（登记例外） |
| 现价↔原价 | 3 | `gap-[3px]`（登记例外） |
| 滚动当前点 | 6×3 | `w-1.5 h-[3px] rounded-tag bg-brand` |
| 滚动非当前点 | 3×3 | `size-[3px] rounded-tag bg-disabled opacity-40` |
| 阴影 | 无 | `shadow-none` |

### `tailwind.config.js`（由 TOKENS.json 生成，目标项目无此配置时由本技能补）
```js
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: { extend: {
    colors: {
      brand: { DEFAULT: '#FF0F23', light: '#FFF0F4', foreground: '#FFFFFF' },
      subsidy: '#C70512', shop: '#900210', price: '#FF253D',
      title: '#11141A', content: '#3D414D', muted: '#505259', disabled: '#C2C4CC',
      'on-color': '#FFFFFF', overlay: '#FFFFFF', page: '#F2F3F7',
      'module-stroke': '#FFFFFF',
      line: 'rgba(17,20,26,0.08)', subtle: 'rgba(17,20,26,0.02)', image: 'rgba(0,0,0,0.10)',
      'badge-from': '#FF1D1A', 'badge-to': '#FF505C',   // 百补价 badge 红渐变(右深→左浅)
      tag: {
        instant: '#FF3333', 'instant-fg': '#665005',
        'self-from': '#FF3D4C', 'self-to': '#F92B18', 'hot-fg': '#FADEBF',
      },
    },
    backgroundImage: {
      'tag-self': 'linear-gradient(90deg,#FF3D4C 0%,#F92B18 100%)',
      'module-mega': 'linear-gradient(135deg,#FFE1E1 0%,#FFFFFF 53.6126%)',
    },
    fontFamily: {
      sans: ['"PingFang SC"', 'system-ui', 'sans-serif'],
      number: ['JDZhengHT', '"京东正黑"', '"PingFang SC"', 'sans-serif'],
      hot: ['"造字工房品宋体"', '"PingFang SC"', 'serif'],
      grab: ['"京东朗正体2.0"', 'jingdonglangzhengti2', 'sans-serif'],  // grab『抢』Bold (Relay font: jingdonglangzhengti2，带2.0)
    },
    fontSize: {
      'price-int': ['14px', '12px'], 'price-dec': ['9px', '8px'],
      'price-now': ['16px', '16px'], 'price-old': ['12px', '14px'],
      badge: ['9px', '9px'], tag: ['10px', '9px'], hot: ['11px', '10px'],
      'subsidy-title': ['16px', '16px'], 'lp-badge': ['10px', '10px'],
      shop: ['11px', '10px'], dish: ['11px', '10px'], desc: ['10px', '10px'], more: ['11px', '10px'],
    },
    borderRadius: { image: '6px', badge: '4px', tag: '2px' },
    borderWidth: { hairline: '0.5px', module: '1px' },
    strokeWidth: { more: '0.8px' },
    spacing: {
      image: '75px', card: '75px',
      'price-chip': '33px',
      'price-value': '18px',
      'price-int': '10px',
      'price-dec': '8px',
      'price-badge-x': '31px',
      'price-badge': '44px',
      'price-bolt-x': '30px',
      'price-bolt': '9px',
      'price-bolt-gap': '36px',
      'price-badge-text-x': '42px',
      'price-badge-text-y': '3.5px',
      'price-badge-text': '27px',
      'price-badge-text-h': '9px',
      'price-bolt-h': '17px',
    },
    width: {
      'hot-tag': '43px', 'hot-label': '36px', 'title-mega': '190px', 'title-home': '210px',
      'price-chip': '33px',
      'price-value': '18px',
      'price-int': '10px',
      'price-dec': '8px',
      'price-badge': '44px',
      'price-bolt': '9px',
      'price-badge-text': '27px',
    },
    height: { 'hot-tag': '13px', 'price-bolt': '17px', 'price-badge-text': '9px' },
    inset: {
      'hot-label-gap': '3.75px',
      'hot-label-y': '1.5px',
      'price-badge-x': '31px',
      'price-bolt-x': '30px',
      'price-bolt-gap': '36px',
      'price-badge-text-x': '42px',
      'price-badge-text-y': '3.5px',
    },
  }},
  plugins: [],
}
```
> 间距 2/4/6/8/10/12/16px 全命中 Tailwind 默认 4px 栅格（`0.5/1/1.5/2/2.5/3/4`…），**不扩展 spacing**（只额外登记 `image`/`card`=75px）；直接用默认 class 即视为 token 化。`size-image` = `w-image h-image`。

---

## §C 组件规范（摘要 + 业务变体矩阵；完整 Canonical 代码见各 `components/*.md`）

> 组件 → Zero 节点 → 规格文件 → 目录层：

| 组件 | Zero nodeId | 规格 | 层 |
|---|---|---|---|
| 业务角标 BizTag | `156:8117` 内 | [BizTag](components/BizTag.md) | atoms |
| 百补价格徽标（button组件） | `149:607` | [SubsidyPrice](components/SubsidyPrice.md) | atoms |
| 现价/原价 PriceCompare | `149:870` | [PriceCompare](components/PriceCompare.md) | atoms |
| 更多入口 MoreEntry | `149:1021` | [MoreEntry](components/MoreEntry.md) | atoms |
| 滚动指示点 Pagination | `149:1551` | [Pagination](components/Pagination.md) | atoms |
| 商品图 ProductImage | `156:8117` | [ProductImage](components/ProductImage.md) | composites |
| 百补商品卡 ProductCard | `149:726`/`149:865` | [ProductCard](components/ProductCard.md) | composites |
| 百补标题 SubsidyTitle | `149:1010` | [SubsidyTitle](components/SubsidyTitle.md) | composites |
| 百补组件封装 SubsidyModule | `149:1511` | [SubsidyModule](components/SubsidyModule.md) | layouts |
| 百亿补贴示例页 MegaSubsidyPage | `149:90` | [MegaSubsidyPage](components/MegaSubsidyPage.md) | pages |

### 业务线 `biz` 主矩阵（一图看懂差异）
| biz | 角标 BizTag | 价格表达 | 标题文案 |
|---|---|---|---|
| `takeout` 外卖 | 『爆品一口价』金宋 + `border-shop` 描边 | SubsidyPrice『补X.X』 | 超级补贴 |
| `instant` 自营秒送 | 分体『自营｜秒送』(`bg-tag-instant`) | SubsidyPrice『补X.X』 | 超级补贴 |
| `home` 家政 | 渐变『自营』(`bg-tag-self`) | PriceCompare（现价+划线原价） | 家政官方补贴 + 低价标 |
| `home-promo` 家政营销 | 渐变『自营』(`bg-tag-self`) | SubsidyPrice『抢』 | 家政官方补贴 + 低价标 |

### C1 · atoms/BizTag — 业务角标（贴商品图左上）
- 三型：`self`(自营·渐变 `bg-tag-self`，白字 `text-tag`)；`instant`(自营秒送·整图)；`hot`(爆品一口价·43×13 SVG 深红底 + `font-hot -skew-x-6 text-tag-hot-fg`)。
- `hot` 必须按本地 md 规范：容器 `w-hot-tag h-hot-tag`（43×13），SVG 背景取 `assets/biztag-hot.svg`，文案宽 36、`top-hot-label-y`(1.5)、`right-hot-label-gap`(3.75)，即 Relay `x = 43 - 3.75 - 36 = 3.25`。文案不改，仍为「爆品一口价」。Zero/Relay transform 固定 `[[1,-0.1051042353,3.25],[0,1,1.5]]`，仅 X 轴斜切，禁止旋转矩阵。
- `instant` 高 14、右上；`self` 高 14、右上；`hot` 左上。

### C2 · atoms/SubsidyPrice — 百补价格徽标（用户截图里的「button组件」）
- **固定 75×16 整体容器**（参考 `7:217`，当前生成稿 `7:125/144/163/182` 已同步）：`SubsidyPrice / subsidy` 本身是 `w-card h-4 bg-brand-light rounded-badge overflow-visible`，Relay 必须 `clipsContent=false`，不是只给 chip 子节点上浅红底。
- 价格京东正黑红（`text-price-int` 14/lh12 + `text-price-dec` 9/lh8，`gap-0` 底对齐），标准价格区 `left-2 top-0.5 w-price-value`。标准外卖/自营展示价为 `9.9`；长价格需新变体重测，不得挤压 badge。
- `SubsidyPrice / badge gradient` 固定 `left-price-badge-x`(31) + `w-price-badge`(44)，右边界固定到 75；**必须直接调用 `assets/subsidy-badge-gradient.svg`**，禁止再用矩形渐变替代。
- `SubsidyPrice / bolt svg 9x17` 固定 `left-price-bolt-x`(30)、`bottom-0`、`w-price-bolt h-price-bolt`，底部对齐且距右边 `right-price-bolt-gap`(36)。
- `补20.1` 文案固定 `left-price-badge-text-x top-price-badge-text-y w-price-badge-text h-price-badge-text`，白字 `text-badge text-on-color`，上下居中。变体 `tag`: `subsidy`(补X.X) | `grab`(抢，`font-grab font-bold`)。
- **禁**：勾选 `SubsidyPrice / subsidy` 裁切内容 / 恢复动态 hug 三段布局 / 固定整图叠字 / clip-path 尖角 / badge 用纯色 `bg-brand` / 伪造闪电（必须 svg）。

### C3 · atoms/PriceCompare — 现价 + 划线原价（家政）
- 现价 `text-price text-price-now font-number`；原价 `text-disabled text-price-old font-number line-through`；`flex items-end gap-[3px]`。

### C4 · atoms/MoreEntry — 更多入口
- `更多`(`text-muted text-more`) + 12×12 chevron(`size-3`)；chevron 描边固定 `stroke-more`(0.8px)，不可用旧 1.2px；path 固定 `M4.5 3L7.5 6L4.5 9`，在 12×12 viewport 内居中；文字和 chevron 间距固定 `gap-0`（Relay 当前 textRight=24、chevronX=24）；`flex items-center gap-0 py-3 pr-2.5`。

### C4b · atoms/Pagination — 滚动指示点
- 模块卡片行下方居中：`Pagination / centered` 自身必须是**自适应横向 auto layout**，React 用 `inline-flex w-fit items-center gap-0.5`，Relay 用 `FRAME + layoutMode=HORIZONTAL + primaryAxisSizingMode=AUTO + counterAxisSizingMode=AUTO + itemSpacing=2`；外层轮播区负责居中。当前点 `w-1.5 h-[3px] rounded-tag bg-brand`(红长条 6×3)，其余 `size-[3px] rounded-tag bg-disabled opacity-40`(灰 3×3)。

### C5 · composites/ProductImage — 商品图 75×75
- Zero 中 `ProductImage / Data Slot` 必须生成为 **Frame 容器**：`relative size-image rounded-image overflow-hidden` 对应 Relay `FRAME + clipsContent=true`。未来商品图 `<img>` 与 `BizTag` 都必须作为该容器子节点，图片在下层，`BizTag` 在上层。
- 空图占位固定为一个居中文本：`ProductImage / placeholder text`，文案「图片占位」，`text-desc text-content font-sans`，在 75×75 Frame 内水平+垂直居中，并位于 `BizTag` 下层；**禁止**再生成 `Image placeholder shadow` / `Image placeholder highlight`。
- `<img>` 铺满容器；`home`/`instant` 额外 `border-hairline border-image` 内描边，`takeout` 用 `border-hairline border-shop`。

### C6 · composites/ProductCard — 百补商品卡
- 列宽 `w-card`，`flex-col gap-1`：① `ProductImage(biz)` ② 信息块 `flex-col gap-1.5`：店铺名 `text-shop` → (菜品名 `text-dish` / 家政描述 `text-desc`) → 价格区（`SubsidyPrice` 或 `PriceCompare`，由 `biz` 决定）。
- `takeout` 外卖卡里商品名称与店铺名称必须在 75 宽信息区内水平居中（`items-center text-center`）；`instant` 同居中。`home` 用 PriceCompare、左对齐(`items-start`)；`home-promo` 继续左对齐。

### C7 · composites/SubsidyTitle — 百补标题
- `flex justify-between items-center h-9`：左为 **Title Frame 文本容器**，不是旧标题 PNG。`takeout`/当前外卖百补标题容器固定 `w-title-mega h-9`（190×36），内部文本「超级补贴」用 `PingFang SC` / `text-subsidy-title` / `font-semibold` / `leading-none`，距左 `left-2.5`(10)，上下居中；右为 `MoreEntry`。
- 旧 `subsidy-title-mega@3x.png` 只作为历史参考，不再用于外卖百补本地 md-only 生成。

### C8 · layouts/SubsidyModule — 百补组件封装
- `relative flex-col rounded-xl overflow-hidden`（**容器四周 12 圆角**）：`takeout/instant` 背景必须直接使用根容器 `bg-module-mega` 渐变填充，Zero/Relay `gradientTransform` 固定 `[[0.2087924948,0.6604530948,0.2351507096],[-0.6604530948,0.0484862041,0.7817403069]]`，并加 `border-module border-module-stroke`（Zero `7:4`：#FFFFFF / 1px / INSIDE），禁止再挂 `Background / local subsidy-bg-mega lossless PNG`；家政两类仍可按规范使用对应背景资产。结构：① `SubsidyTitle(biz)` ② 卡片行 `flex gap-[13px] px-2.5 overflow-x-auto` 的 `ProductCard(biz) × N` ③ 底部轮播区 `flex w-full justify-center pt-[7px] pb-2`，内部 `Pagination` 为 `inline-flex w-fit` 自适应 auto layout。
- ⚠ 硬规范：容器 **`rounded-xl`(12) 四周圆角**；`takeout/instant` 必须有 `border-module border-module-stroke` 内描边；轮播条外层**居中**，`Pagination / centered` 自身**Hug contents / 自适应宽度**，禁止写死 `359×18` 或手写每个点 x 坐标；**两个家政（`home` + `home-promo`）均无轮播条**（批注「家政没有轮播条」）——**只有 `takeout`/`instant` 有**；家政无轮播时卡行 `pb-3`(12) 补底。卡间距实测 **13**（`gap-[13px]`，非 `gap-4`）；模块总高 181/175/159（外卖&自营/家政营销/家政常规）。

### C9 · pages/MegaSubsidyPage — 示例页
- `bg-page` 纵向堆叠四条业务线 `SubsidyModule`（外卖 / 自营秒送 / 家政 / 家政营销），演示组件族全貌。

---

## §D 工作流（粘贴链接 / `/gen-component` 触发后）

**Step 0 解析输入**：链接抽 `node_id`（`149-607`→`149:607`）；组件名查 §C 表；为空则问用户。
**Step 1 读 Zero**：`get_design_metadata`(看骨架) → `get_variables`(对账 §B) → `get_design_context`(仅参考) → `get_screenshot`(留比对)。
**Step 2 反查 Token**：把 context 里每个裸值映射回 §B 的 class（`#FF0F23`→`text-brand`、`#C70512`→`text-subsidy`、`#900210`→`text-shop`、`#FF253D`→`text-price`、`#3D414D`→`text-content`、`#505259`→`text-muted`、`#C2C4CC`→`text-disabled`、`#FFF0F4`→`bg-brand-light`、`#FF3333`→`bg-tag-instant`、`linear-gradient(...FF3D4C...)`→`bg-tag-self`、参考背景 `#FFE1E1→#FFFFFF@53.6126%` + `gradientTransform [[0.2087924948,0.6604530948,0.2351507096],[-0.6604530948,0.0484862041,0.7817403069]]`→`bg-module-mega`、模块根描边 `#FFFFFF + 1px INSIDE`→`border-module-stroke border-module`、`#FADEBF`→`text-tag-hot-fg`、圆角6→`rounded-image`、圆角4→`rounded-badge/rounded-l-badge`、圆角2→`rounded-tag`、0.5px→`border-hairline`、0.8px→`stroke-more`、More gap0→`gap-0`、More chevron `M4.5 3L7.5 6L4.5 9`→`size-3 stroke-more`、75→`size-image/w-card`、ProductImage 空图占位「图片占位」→`text-desc text-content font-sans`、SubsidyPrice 内部坐标 x31/w44/x30/right36/x42/y3.5→`left-price-badge-x/w-price-badge/left-price-bolt-x/right-price-bolt-gap/left-price-badge-text-x/top-price-badge-text-y`，badge 图形→`assets/subsidy-badge-gradient.svg`、43×13→`w-hot-tag h-hot-tag`、hot 右距3.75 与 transform `[[1,-0.1051042353,3.25],[0,1,1.5]]`→`right-hot-label-gap text-hot font-hot -skew-x-6`、Title 190×36→`w-title-mega h-9`、卡间距13→`gap-[13px]`、行内边距10→`px-2.5`、滚动点(6×3红/3×3灰40%)→`Pagination`、京东正黑→`font-number`、品宋→`font-hot`）。命中不了就停下提 token-miss，**不硬编码**。
**Step 3 生成**：按 §A.4 目录落盘，复用已存 atoms/composites，文件头加溯源注释，照 §C / `components/*.md` 的 Canonical 段产出；业务差异用 `biz` 维度切，不复制组件。
**Step 4 自校验（必做）**：① 再 `get_screenshot` 与 Step1 比对（背景为 `bg-module-mega` 渐变且无 `subsidy-bg-mega` PNG，Zero/Relay 渐变矩阵与 §B 完全一致 / 根容器有 #FFFFFF 1px 内描边 / Title 190×36/「超级补贴」左10上下居中 / More stroke 0.8、chevron path 居中且文字与 chevron gap=0 / hot 43×13、右距3.75、文字仅 X 轴斜切 / ProductImage Frame 裁剪且空图只显示「图片占位」、无 `Image placeholder shadow/highlight` / 外卖店铺名和商品名居中 / Pagination 为自适应横向 auto layout 且居中 / 三支红 / SubsidyPrice 75×16 整体浅红 r4 且 clipsContent=false、badge 直接调用 `subsidy-badge-gradient.svg` 且 x31 w44、bolt bottom0 right36 / 划线原价 / 图圆角6）；② 跑禁魔法值自检 `grep -nE '#[0-9a-fA-F]{3,8}|[0-9]+px|rgba?\(|linear-gradient' src/components`（应只剩 `w-image/h-image/w-card/border-hairline/border-module/border-module-stroke/stroke-more/gap-0/bg-module-mega/w-hot-tag/h-hot-tag/right-hot-label-gap/w-title-mega/w-price-*/left-price-*/top-price-*/right-price-bolt-gap/gap-[3px]/h-[13px](低价标图)`、SVG 文件内部渐变或注释）；③ 回答给 ✅/⚠ 比对表。

---

## §E 触发方式
- **一键命令（推荐）·Zero 模式**：`/jd-now-ui 【Zero 链接】` —— 走 §D 四步（MCP 读取→匹配→生成→自校验）并落盘三文件结构。
- **一键命令·离线模式**：`/jd-now-ui 【组件描述】`（不带链接）—— 走 §G，仅以本地规范+TOKENS 生成，未指定维度取标准主变体。例：`/jd-now-ui 家政百补商品卡`。
- **命令**：`/gen-component [组件名或 Zero 链接]`（交互式，见 `.claude/commands/gen-component.md`）。
- **粘贴链接 / 自然语言**：贴 `relay.jd.com/file/design?...` 或「生成/还原 + 百补/商品卡/百补价/百补标题…」即命中本技能描述。

---

## §F Prompt Template（`/jd-now-ui` 一键模板 · 复制即用）

**一键用法**（保存即用，链接或 node_id 二选一）：
```
/jd-now-ui https://relay.jd.com/file/design?id=2057090330888527873&page_id=72:11997&node_id=149:726
/jd-now-ui 149:726
```
`/jd-now-ui` 命令内部即运行下面这段模板（定义见 [`.claude/commands/jd-now-ui.md`](../../commands/jd-now-ui.md)）；手动把整段贴给 Claude 也等效——只需把 `<ZERO_NODE>` 换成你的 Zero 链接 / node_id。五个分段对应：①MCP 读 → ②匹配规范+Tokens → ③出代码 → ④落 `src/components/<层>/<名>/` → ⑤自校验。

```text
你是 MegaSubsidyGenerationSkill（mega-subsidy-design-skill）。严格按本技能规范，把下面的 Zero 节点
1:1 像素级生成 React 18 + TypeScript + Tailwind v3 代码。全自动、不反问（仅输入为空时问一次）。

【输入节点】<ZERO_NODE>
【Zero 源】file 2057090330888527873 · page 72:11997（Mega Subsidy 百亿补贴）

──① 用 MCP 读取该节点（依次）──────────────────────────
get_design_metadata（看骨架）→ get_variables（对账 TOKENS.json）→
get_design_context（仅参考，禁直接交付其绝对定位 / 裸 hex / svg 占位）→ get_screenshot（留比对）。
node_id 解析：...&node_id=149:726 → 149:726；149-726 → 149:726。

──② 匹配组件库规范 & Tokens（裸值反查，禁魔法值）──────────
颜色：#FF0F23→brand · #C70512→subsidy · #900210→shop · #FF253D→price · #3D414D→content ·
  #505259→muted · #C2C4CC→disabled · #11141A→title · #FFF0F4→bg-brand-light · #FF3333→bg-tag-instant ·
  #665005→tag-instant-fg · linear-gradient(FF3D4C→F92B18)→bg-tag-self · module background #FFE1E1→#FFFFFF→bg-module-mega · module stroke #FFFFFF→border-module-stroke · #FADEBF→tag-hot-fg · #11141A14→border-line。
字体：京东正黑/JDZhengHT→font-number（所有价格数字）· 造字工房品宋体→font-hot（爆品一口价）· 中文→font-sans。
字号：14/12/700→text-price-int · 9/8/700→text-price-dec · 16/16→text-price-now · 12/14→text-price-old ·
  16/16/600→text-subsidy-title · 11/10/500→text-shop · 11/10/400→text-dish · 10/10→text-desc · 11/10→text-more。
圆角：6→rounded-image · 4→rounded-badge（百补价整体容器四角）/ rounded-l-badge（chip 子层仅左两角） · 2→rounded-tag。
间距/尺寸/背景：75→size-image/w-card · 0.5px→border-hairline · 1px模块内描边→border-module · 0.8px→stroke-more · More gap0→gap-0 · More chevron path M4.5 3L7.5 6L4.5 9 居中 · 外卖/自营背景渐变→bg-module-mega（Zero/Relay gradientTransform 精确矩阵） · 43×13 hot→w-hot-tag/h-hot-tag ·
  hot 文案右距3.75→right-hot-label-gap，transform [[1,-0.1051042353,3.25],[0,1,1.5]] · ProductImage 空图占位「图片占位」→text-desc/text-content/font-sans · Title 190×36→w-title-mega/h-9 · SubsidyPrice x31/w44/x30/right36/x42/y3.5→left-price-badge-x/w-price-badge/left-price-bolt-x/right-price-bolt-gap/left-price-badge-text-x/top-price-badge-text-y · 卡行 gap13→gap-[13px] · 行内边距10→px-2.5 ·
  滚动当前点6×3→w-1.5 h-[3px] rounded-tag bg-brand · 滚动点3×3→size-[3px] rounded-tag bg-disabled opacity-40。
命中不了任何 token → 停下标 ⚠ token-miss，禁硬编码。
组件→层级：BizTag/SubsidyPrice/PriceCompare/MoreEntry/Pagination→atoms；
  ProductImage/ProductCard/SubsidyTitle→composites；SubsidyModule→layouts；MegaSubsidyPage→pages。
  表外节点按结构推断（叶子→atoms，组合→composites，标题+卡片行→layouts，装配成屏→pages）。
  业务差异用 biz=('takeout'|'instant'|'home'|'home-promo') 维度切，禁复制组件；参照 components/<Name>.md 的 Canonical。

──③ 输出 React + TS + Tailwind 代码──────────────────────
函数组件 + hooks；每组件导出 Props 接口；只用 ② 映射后的 class；不引第三方 UI 库；shadow-none。
Zero 图形资产（hot 角标 SVG / 低价标 / 百补价金色闪电⚡ / 百补价 badge SVG）：用内置或导出的图片，禁用裸 gradient/clip-path 伪造。外卖/自营模块背景不是图形资产，必须使用 `bg-module-mega` 渐变 token。

──④ 落盘（每组件三文件）────────────────────────────────
src/components/<layer>/<Name>/<Name>.tsx   // 头注：// Zero: file 2057090330888527873 · node <id> · synced 2026-06-04
src/components/<layer>/<Name>/types.ts     // export interface <Name>Props
src/components/<layer>/<Name>/index.ts     // export { <Name> }; export type { <Name>Props }
  例（atom）：src/components/atoms/SubsidyPrice/{SubsidyPrice.tsx, types.ts, index.ts}
复用已存在的下层组件；缺 tailwind.config.js 或 token 时按 §B 补一份。

──⑤ 自校验（必做）─────────────────────────────────────
get_screenshot 再比对（背景渐变 bg-module-mega 且无本地 PNG，Zero/Relay 渐变矩阵精确 / 根容器 #FFFFFF 1px 内描边 / Title 190×36 文本 / More stroke 0.8、chevron 居中且 gap0 / hot 43×13、右距3.75 且仅 X 轴斜切 / ProductImage Frame 裁剪且空图只显示「图片占位」、无 Image placeholder shadow/highlight / takeout 文本居中 / 角标 / 三支红 / SubsidyPrice 75×16 整体浅红 r4 不裁切、badge 直接调用 subsidy-badge-gradient.svg 且 x31 w44、bolt bottom0 right36 / 划线原价 / 图圆角6 / 卡间距13 / Pagination 自适应横向 auto layout 且居中 / 业务变体）；
grep -nE '#[0-9a-fA-F]{3,8}|[0-9]+px|rgba?\(|linear-gradient' src/components
  （应只剩 w-image/h-image/w-card/border-hairline/border-module/border-module-stroke/stroke-more/gap-0/bg-module-mega/w-hot-tag/h-hot-tag/right-hot-label-gap/w-title-mega/w-price-*/left-price-*/top-price-*/right-price-bolt-gap/gap-[13px]/(gap|h|size)-[3px]/h-[13px] 或注释）；
输出 ✅/⚠ 比对表 + 文件清单。

【硬约束·违反即重做】1:1 像素级；只用 token class，禁裸 #hex/px/rgba/gradient
（仅 w-image/h-image/w-card/border-hairline/border-module/border-module-stroke/stroke-more/gap-0/bg-module-mega/w-hot-tag/h-hot-tag/right-hot-label-gap/w-title-mega/w-price-*/left-price-*/top-price-*/right-price-bolt-gap/gap-[13px]/(gap|h|size)-[3px]/h-[13px] 例外）；
三支红不互换（brand 价格 / subsidy 标题 / shop 店铺名）；价格数字 font-number、爆品 font-hot；
百补价整体容器 fixed 75×16、bg-brand-light、rounded-badge、overflow-visible，badge 直接调用 assets/subsidy-badge-gradient.svg 且 x31 w44，bolt bottom0 right36；家政用 PriceCompare 含 line-through 原价；
biz 维度切变体不复制；外卖/自营背景=bg-module-mega 根容器渐变且删除本地 PNG，Zero/Relay 使用精确 gradientTransform，并有 border-module/border-module-stroke 内描边；外卖 Title=超级补贴 190×36 文本容器；More chevron 居中 stroke 0.8 gap0；hot 角标文字 transform 精确；ProductImage/Data Slot=Frame裁剪，空图只显示「图片占位」且禁止 shadow/highlight 占位形状；模块卡行 gap-[13px] + 底部 Pagination 自适应横向 auto layout；shadow-none；每组件三文件。
```

---

## §G 无链接调用（离线生成 · 唯一依据 = 本地规范 + TOKENS.json）

`/jd-now-ui` 看输入**自动分流**（优先级 Zero > 离线 > 菜单）：

| 输入形态 | 模式 | 行为 |
|---|---|---|
| 含 `relay.jd.com` / `node_id=` / 形如 `\d+:\d+` | **① Zero 模式** | 走 §D / §F：MCP 读取 → 匹配规范+Tokens → 生成 → 截图自校验 |
| 自然语言（组件名 [+业务线/变体/尺寸/状态]） | **② 离线模式** | **不调用 MCP**，仅以 [`TOKENS.json`](TOKENS.json) + `components/*.md` 为唯一依据生成；未指定的维度取**标准主变体**默认值 |
| 完全为空 | **③ 菜单** | 打印 G1 参数目录并问生成哪个组件（含默认主变体），收到答复后转 ② |

> 离线三原则：**① 只用本地 token（禁魔法值）· ② 未指定维度取标准主变体 · ③ Zero 未定义的尺寸/状态按「离线扩展」兜底并逐处标 ⚠**。

### G1 · 参数目录（**加粗 = 默认/标准主变体**；尺寸/状态为离线扩展）

| 组件（层） | 实测变体（Zero 已定义） | 尺寸/状态（离线扩展，默认加粗） |
|---|---|---|
| **atoms/BizTag** | `type`: **self(自营)** \| instant(自营秒送) \| hot(爆品一口价) | — |
| **atoms/SubsidyPrice**（=「button组件」） | `tag`: **subsidy(补X.X)** \| grab(抢)；`value` 价格数 | `size`: sm \| **md** \| lg；`state`: **default** \| disabled |
| **atoms/PriceCompare** | `now`(现价) [+ `origin` 划线原价] | — |
| **atoms/MoreEntry** | `text`: **更多** | — |
| **atoms/Pagination** | `total` 点数；`active` 当前页(默认 **0**) | — |
| **composites/ProductImage** | `biz`: **takeout** \| instant \| home \| home-promo | — |
| **composites/ProductCard** | `biz`: **takeout** \| instant \| home \| home-promo | — |
| **composites/SubsidyTitle** | `biz`: **takeout** \| instant \| home \| home-promo | — |
| **layouts/SubsidyModule** | `biz`: **takeout** \| instant \| home \| home-promo；`items` 卡数据 | `activePage`(默认 **0**) |
| **pages/MegaSubsidyPage** | 默认组装四业务线 SubsidyModule | — |

> **业务线 `biz` 是本库主维度**；多数组件 Zero 未定义「尺寸/状态」——仅 SubsidyPrice（即「button组件」）支持离线扩展的 `size`/`state`，其余组件请用 `biz` / 变体表达。

### G2 · 自然语言 → 参数（解析词表）
- **组件**：角标/标签→BizTag｜百补价/价格徽标/button组件/按钮→SubsidyPrice｜现价原价/划线价→PriceCompare｜更多→MoreEntry｜滚动点/分页/指示点→Pagination｜商品图→ProductImage｜商品卡/百补卡→ProductCard｜标题/百补标题→SubsidyTitle｜模块/封装/百补组件→SubsidyModule｜页/整页/示例→MegaSubsidyPage
- **业务线**：外卖→takeout｜自营秒送/秒送→instant｜家政→home｜家政营销/营销→home-promo
- **变体**：自营→type:self｜自营秒送→type:instant｜爆品/一口价→type:hot｜补→tag:subsidy｜抢→tag:grab
- **尺寸**（离线扩展）：小/sm｜中/md｜大/lg　**状态**：默认/default｜禁用/disabled　**其他**：占满/block
- **缺省**：描述里未出现的维度 → 取 G1 标准主变体默认值（如只说「百补价」= SubsidyPrice `{tag:'subsidy', size:'md', state:'default'}`）。

### G3 · 示例（无链接 · 离线模式）
| 输入 | 解析 | 落盘 |
|---|---|---|
| `/jd-now-ui 家政百补商品卡` | ProductCard `{biz:'home'}` | `composites/ProductCard/` |
| `/jd-now-ui 外卖商品卡` | ProductCard `{biz:'takeout'}`（标准主变体） | `composites/ProductCard/` |
| `/jd-now-ui 自营秒送商品图` | ProductImage `{biz:'instant'}` | `composites/ProductImage/` |
| `/jd-now-ui 百补价 抢` | SubsidyPrice `{tag:'grab', size:'md', state:'default'}` | `atoms/SubsidyPrice/` |
| `/jd-now-ui 生成一个次按钮，尺寸lg，禁用状态` | 「按钮」→ SubsidyPrice（本库「button组件」，无主/次之分）`{size:'lg' ⚠, state:'disabled' ⚠}` | `atoms/SubsidyPrice/` |
| `/jd-now-ui 爆品一口价角标` | BizTag `{type:'hot'}` | `atoms/BizTag/` |
| `/jd-now-ui 家政百补标题` | SubsidyTitle `{biz:'home'}` | `composites/SubsidyTitle/` |
| `/jd-now-ui 自营秒送百补模块` | SubsidyModule `{biz:'instant'}` | `layouts/SubsidyModule/` |
| `/jd-now-ui` | —（空） | 打印 G1 目录并问要哪个 |

### G4 · 离线 = 同样 token-pure + 扩展兜底
1. **只用 token**：仅 `TOKENS.json` 的 class，禁裸魔法值（例外白名单同 §A.2）。
2. **标准主变体**：未指定维度取 G1 加粗默认值。
3. **离线扩展**（Zero 未定义的 尺寸/状态）按下表兜底，并**逐处标 ⚠「离线扩展，接真 Zero 后以实测覆盖」**：

   | 维度 | 取值 | class（4px 栅格 / 标准工具类） |
   |---|---|---|
   | `size` | sm | 主变体缩一档（如 SubsidyPrice `h-3.5`）⚠ |
   | | **md（默认 = Zero 实测）** | 主稿尺寸（SubsidyPrice `w-card h-4` = 75×16） |
   | | lg | 放大一档（`h-5`，价格用 `text-price-now`）⚠ |
   | `state` | **default** | — |
   | | disabled | `opacity-40 pointer-events-none` + `disabled`（⚠ Zero 未定义禁用态） |
   | `block` | block | `w-full` |

4. **自校验**：跑 `grep` 禁魔法值自检（§D Step4 同款）；离线无 Zero 截图可比，改出「规范符合性自检表」（变体 class / 尺寸 / 状态 / 目录层 / 三文件齐全）+ ✅/⚠ 表 + 文件清单 + 一段用法示例。

---

> 仅覆盖 `2057090330888527873` 这一 Zero 文件 page `72:11997` 的 Mega Subsidy 百亿补贴 组件族。换文件/换页时复用「读 Zero → 反查 token → 原子化生成 → 截图自校验」四步法，按新节点重建 [`TOKENS.json`](TOKENS.json) 与 [`components/`](components/)。
