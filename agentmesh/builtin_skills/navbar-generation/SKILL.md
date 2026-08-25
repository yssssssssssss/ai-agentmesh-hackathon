---
name: navbar-generation
description: 基于 Zero 组件库（京东本地生活·品类频道 Navbar 导航栏）的「设计转代码」一键生成器。用 Zero MCP 读组件库 → 提取设计 token / 组件 / 变体 → 1:1 像素级还原为 React 18
  + Tailwind v3 + TypeScript（落 atoms/composites/layouts/pages 四级目录，每组件文件夹内 {Name}.tsx+types.ts+index.ts 三文件，全部反查 TOKENS.json
  禁魔法值）。触发：用户输入 /jd-now-ui（即「JD Now-ui」一键命令）或 /gen-component；或粘贴 relay.jd.com/file/design 链接、Zero 节点 id（如 86:1937）；或说「JD Now-ui
  / 生成 Navbar 组件 / 生成品类频道头 / 生成搜索栏/地址栏/返回按钮组件 / design to code / 把这个 Zero 组件生成代码」。Zero 源 fileKey 2057090330888527873。
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
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/local-life/Channel 频道/Page Header 头部/Navbar 导航栏/navbar-generation-bundle/navbar-generation/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: during_design
  agentmesh-activation: explicit_only
  short-description: 基于 Zero 组件库（京东本地生活·品类频道 Navbar 导航栏）的「设计转代码」一键生成器。用 Zero MCP 读组件库 → 提取设计 token / 组件 / 变体 → 1:1 像素级还原…
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


# /gen-component · Zero 组件库 → React 组件代码（NavbarGenerationSkill）

把 **Zero 组件库**（本地生活 · 品类频道 Navbar 导航栏）**1:1 像素级**还原成 **React 18 + Tailwind CSS v3 + TypeScript**。

这是**设计转代码生成器**，不是创意编码助手：**忠实把 Zero 已画明的组件翻译成代码** —— token 不自己造，结构不自己改，尺寸不自己凑。

> Zero 源：`fileKey 2057090330888527873` · `page_id 74:1` ·
> [本地生活频道小组 MD 规范](https://relay.jd.com/file/design?id=2057090330888527873&page_id=74:1)
> 下文「Tokens」「组件规范」均**实读** Zero 节点（74:2503 / 122:511 / 86:1937 默认 / 86:2129 上划 / 122:714 背景 / 74:2531 标题）提取，非臆测。

## 这个 skill 做什么
1. 用 **Zero MCP** 读组件库（`get_design_context` / `get_variables` / `get_screenshot` / `get_design_metadata`）。
2. 提取 **token**（颜色/字体/间距/圆角/阴影/层级）→ 固化进 [`TOKENS.json`](TOKENS.json)，并标主稿反查路径；下文「Tokens」是其速览。
3. 提取 **组件 + 变体** → 详见 [`components/`](components/)；下文「组件规范」是其速览。
4. 生成 **React + Tailwind v3 + TS**，按类型落 `atoms / composites / layouts / pages`，每组件 3 文件。

> ⚠️ 该 Zero 文件是 **Navbar 专题库**，不含通用 Button/Input/Card/Modal。组件 = 导航栏各组成部分。生成时**以 Zero 实有组件为准**，不臆造不存在的组件。

## 何时触发

| 场景 | 调用 |
|---|---|
| `/gen-component <链接\|节点id\|组件名>` 或 `/navbar-generation ...` | 直接走 |
| 粘贴 `relay.jd.com/file/design...` 链接 / Zero 节点 id（如 `86:1937`） | 自动触发 |
| 「生成 Navbar / 品类频道头 / 搜索栏 / 地址栏 / 返回按钮组件」「把这个 Zero 组件生成代码」「design to code」 | 主动调 |
| Zero 设计更新 → 重新生成 | 主动调（先重 `get_*` 校准 TOKENS.json） |

**不适用**：只要设计规范不要代码 → `navbar-design-spec`；抽稿成 design.md → `relay-to-design-md`；渲 HTML 规范页 → `design-md-to-spec-page`；审合规 → `design-review`；源是 wiki 其它组件 design.md → `design-md-to-react`。

## 调用方式（一键 /jd-now-ui）

```text
# —— 模式 A：有 Zero 链接 / 节点id（在线，读 MCP）——
/jd-now-ui https://relay.jd.com/file/design?id=2057090330888527873&node_id=86:1937
/jd-now-ui 86:1937                          # 节点id：默认态整条 Navbar；86:2129 上划态

# —— 模式 B：无链接（离线，本地「组件规范 + TOKENS」为唯一依据）——
/jd-now-ui                                  # 默认整条 Navbar（标准主变体）+ 依赖
/jd-now-ui SearchBar                        # 单组件，标准主变体
/jd-now-ui 生成 SearchBar，带热标，上划态      # 自然语言指定 变体/态
/jd-now-ui 生成 Navbar 外卖频道 吸顶态
/jd-now-ui 生成 RightActions，已关注，只要关注和分享
/jd-now-ui ChannelTitle --type ziying       # 旗标写法
# 等价别名：/gen-component <同上参数>
```

> ⚠️ 命令名规则：Claude Code 斜杠命令只能小写连字符，`/JD Now-ui`（含空格/大写）无法注册 —— 实际生效命令为 **`/jd-now-ui`**；在对话里打「JD Now-ui」也会自动路由到本 skill。命令实现见 [`.claude/commands/jd-now-ui.md`](../../commands/jd-now-ui.md)。

## 两种调用模式（路由）

入口先判模式，二选一：

| 输入 | 模式 | 行为 |
|---|---|---|
| 含 relay 链接 / 节点id（`\d+:\d+`、`\d+-\d+`） | **Link Mode（在线）** | MCP 读 Zero → 匹配规范 → 出代码（原逻辑，见执行流程 ①–⑤） |
| 无链接（空 / 自然语言 / 组件名+参数） | **No-link Mode（离线）** | **以本地「组件规范 + TOKENS.json」为唯一依据**生成，**不读 MCP、不编 token**；未指定参数取「标准主变体」，指定的变体/态/频道按需应用，库内没有的组件/轴如实报告 |

## 无链接调用（本地规范模式）

### 参数文法（自然语言 与 旗标 皆可）
| 维度 | 自然语言关键词 | 旗标 | 合法取值（仅这些） |
|---|---|---|---|
| 组件 | 导航栏 / 品类频道头、搜索栏、地址栏、标题、返回(按钮)、右侧操作、关注/分享/更多、热标、状态栏 | `--component` | Navbar · SearchBar · AddressBar · ChannelTitle · BackButton · RightActions · HotTag · StatusBar |
| 频道(换肤) | 外卖 / 自营秒送 / 超市秒送 / 夜宵 / 美食团购 / 家政 / 默认 | `--channel` | default · waimai · ziying · chaoshi · yexiao · tuangou · jiazheng |
| 状态 | 默认态 / 吸顶·上划态 | `--state` | default · sticky（仅 Navbar） |
| 标题类型 | 品类频道 / 自营秒送 | `--type` | category · ziying（仅 ChannelTitle、AddressBar=category） |
| 热标 | 带热标 / 不带热标 | `--hotTag` | true · false（仅 SearchBar） |
| 关注态 | 已关注 / 未关注 | `--followed` | true · false（仅 RightActions） |
| 右操作项 | 只要关注和分享 / 全部 | `--items` | follow · share · more 的子集（仅 RightActions） |
| 输出目录 | — | `--out` | 默认 `src/components` |

> 本库**没有**通用「size（sm/md/lg）」「variant（primary/secondary）」「disabled」这些轴 —— 它们不属于 Navbar 组件库。命中时按下方「不在本库的请求」处理。

### 标准主变体（未指定参数时的默认）
| 组件 | 级别 | 标准主变体 |
|---|---|---|
| Navbar | layouts | `channel=default` · `state=default` · `hotTag=false` · `followed=false` |
| SearchBar | composites | `state=default` · `hotTag=false` |
| RightActions | composites | `followed=false` · `items=[follow,share,more]` |
| AddressBar | composites | `type=category` |
| ChannelTitle | atoms | `type=category` |
| BackButton | atoms | `count=one` |
| HotTag | atoms | `text=热` |
| StatusBar | atoms | `time=6:18` |

### 不在本库的请求 → 如实报告，不臆造
本 Zero 库是 **Navbar 专题**，无通用 Button/Card/Input，也无 primary/secondary、size sm·md·lg、disabled 轴。命中时：① 报「本库无此组件/轴」；② 列可用组件 + 各自变体；③ 给最接近的现有组件；④ 问是否用最近匹配生成（**确认前不产码**）。

例（即需求 §3 的示例）：`/jd-now-ui 生成一个次按钮，尺寸lg，禁用状态`
→ 解析 `{组件:按钮, 变体:次/secondary, 尺寸:lg, 状态:disabled}` → 库内无 Button、无 secondary/lg/disabled 轴 → 回应：

> 本库（Navbar 专题）无通用 Button。可用组件：Navbar · SearchBar · RightActions · AddressBar · ChannelTitle · BackButton · HotTag · StatusBar。
> 与「按钮」最接近的是：① SearchBar 内的「搜索」文字按钮；② RightActions 的图标按钮（关注/分享/更多）。
> 要用其中之一生成吗？若确需通用 Button，请提供含 Button 的 Zero 节点 / 组件库。

### 无链接示例（可直接抄）
```text
/jd-now-ui                                       → layouts/Navbar/*（default 频道 + 默认态）+ 全部依赖
/jd-now-ui SearchBar                             → composites/SearchBar/*（默认态，无热标）
/jd-now-ui 生成 SearchBar 带热标                  → composites/SearchBar/*（hotTag=true）
/jd-now-ui 生成 Navbar 外卖频道 吸顶态            → layouts/Navbar/*（channel=waimai, state=sticky）
/jd-now-ui 生成 RightActions 已关注 只要关注和分享 → composites/RightActions/*（followed=true, items=[follow,share]）
/jd-now-ui ChannelTitle --type ziying            → atoms/ChannelTitle/*（自营秒送品牌 lockup）
/jd-now-ui 生成 地址栏                            → composites/AddressBar/*（category）
/jd-now-ui 生成 家政频道导航栏                     → layouts/Navbar/*（channel=jiazheng, 默认态）
```

**零输入仍成立**：给链接走在线、给组件名/需求走离线；都不弹问卷，仅 scope 真二义时问一句。

---

## Prompt Template（/JD Now-ui 一键调用 · 可直接保存使用）

> 这段就是 `/jd-now-ui` 背后执行的提示词。已同步落在 [`.claude/commands/jd-now-ui.md`](../../commands/jd-now-ui.md)（含 `$ARGUMENTS` 占位），保存即用。手动触发时把 `{{INPUT}}` 换成 Zero 链接/节点id/组件名。

```text
你现在执行 NavbarGenerationSkill 一键调用（/JD Now-ui）。先读 skill 资产：
SKILL.md、TOKENS.json、references/token-class-map.md、references/output-contract.md、components/*.md。
对输入 {{INPUT}} 严格执行，全程不弹问卷（仅 scope 真二义时问一句）：

⓪ 路由（先判模式）
  - 输入含 relay 链接 或 节点id（\d+:\d+ / \d+-\d+）→ 【Link Mode】走 ①②③④⑤（用 MCP）。
  - 否则（空 / 自然语言 / 仅组件名+参数）→ 【No-link Mode】走 A→④⑤（不读 MCP）。

【Link Mode】（有 Zero 链接/节点）
① 解析入口
  - 从输入抽 fileKey + nodeId：URL 取 id(=fileKey)、node_id/page_id；nodeId 里 "-" 换 ":"（86-1937→86:1937）。
  - 只给文件无节点 → 默认 86:1937（整条 Navbar 默认态）。是组件名 → 查 components/<Name>.md 的「Zero 节点」。
  - 校验 fileKey 应为 2057090330888527873；不符则提示属其它 Zero 文件、token 可能不在快照内。

② 用 Zero MCP 读节点（按序，失败即停并报告）
  1. get_design_metadata(nodeId)   看结构、定位子节点
  2. get_design_context(nodeId)    拿参考结构/尺寸（仅参考，必改写，绝不照搬 inline 绝对定位）
  3. get_variables(nodeId)         拿该节点 token
  4. get_screenshot(nodeId)        视觉核对

③ 匹配组件库规范 + Tokens
  - 把节点匹配到「组件规范」里的已知组件（按节点 id 或结构）：得 组件名 / 级别 / Props / 变体。
  - 整条 Navbar 节点 → 生成 layout Navbar + 依赖(StatusBar·BackButton·ChannelTitle·AddressBar·SearchBar·RightActions·HotTag)。
  - 每个视觉值反查 TOKENS.json → 经 token-class-map.md 映射成 tailwind 语义 class；查不到 → 记「未覆盖项」，绝不编魔法值。
  - 变体取值只用 TOKENS.json.variants：channel(7)/state(default|sticky)/follow/hotTag/title type。

【No-link Mode】（唯一依据 = 本地 SKILL.md 组件规范 + TOKENS.json，不读 MCP、不编 token）
A 解析需求 → 校验 → 生成
  - 解析自然语言/旗标 → {component, channel, state, type, hotTag, followed, items, count}。
  - 组件在库（Navbar/SearchBar/AddressBar/ChannelTitle/BackButton/RightActions/HotTag/StatusBar）→ 取其可用轴；
    用户给的参数命中则用，未给的填该组件「标准主变体」（见「标准主变体」表）；给了该组件不支持的轴 → 提示忽略并说明。
  - 组件或轴不在库（通用 Button、primary/secondary、size sm/md/lg、disabled 等）→ 不臆造：
    报「本库无此项」+ 列可用组件&变体 + 给最近匹配，问是否用最近匹配生成（确认前不产码）。

④ 输出 React 18 + TypeScript + Tailwind v3
  - 首次：把 token-class-map.md §1 的 theme.extend 幂等合并进 tailwind.config.js。
  - 每组件一个文件夹，固定 3 文件：
      src/components/<级别>/<Name>/
        ├── <Name>.tsx     仅语义 class
        ├── types.ts       Props + variant/state union literal type
        └── index.ts       export 组件 + 类型
  - 约束：1:1 还原(44/44/30、r4、屏边距8、右操作gap16、上划行 pl8 pr12 py7)；
    .tsx 内无裸 hex/px、无 style={{color|fontSize|borderRadius|zIndex}}（例外仅渐变/rgba/运营底图）；
    union literal type；样式映射 as const+Record；可交互元素 <button>+aria-label，图标 currentColor 随频道 fg；不加投影。

⑤ 自检 + 摘要
  - grep 无裸值；union·映射·variants 三处一致；index 导出齐；对照截图核尺寸；6 频道+两态可渲染。问题自动修。
  - 末尾输出：文件清单(行数) / 用到的 token(路径+值+class) / 组件 props+变体 / Zero 来源节点 / 未覆盖项 / 是否需合并 tailwind.config。
```

---

## 约束（强制规则）

### ✅ MUST
1. **1:1 像素级还原** —— 尺寸/间距/字号/圆角/状态严格按 Zero + 「Tokens」。基准：状态栏 44、导航行 44、搜索行 30、搜索框 r4 白底、屏边距 8、右操作 gap16、上划行 `pl8 pr12 py7`。不取整、不重排组件树。
2. **token 唯一来源，禁魔法值** —— 所有 颜色/字号/圆角/间距/层级 反查 [`TOKENS.json`](TOKENS.json)，经 [`references/token-class-map.md`](references/token-class-map.md) 映射成 `tailwind.config` 语义 class。`.tsx` 里**不准出现裸 hex / 裸 px / `style={{ color|fontSize|borderRadius|zIndex }}`**。
3. **栈固定** —— React 18 + Tailwind v3 + TypeScript；variant/state 用 **union literal type**；样式映射 `as const` + `Record<>`；className 用 `[...].filter(Boolean).join(' ')`。
4. **3 文件 / 四级目录** —— 每组件 `{Name}.tsx + types.ts + index.ts`，按类型落 `atoms/composites/layouts/pages`（判级见 [`output-contract.md`](references/output-contract.md)）。
5. **可交互元素**（返回/关注/分享/更多/搜索）用 `<button type="button">` + `aria-label`；图标 `currentColor` 继承频道 fg。
6. **只用实有组件与变体** —— 仅生成「组件规范」里有、`TOKENS.json.variants` 列明的取值。
7. **固定间距默认强制执行** —— 每一级组件关系都必须按规范中的 token 精确设置并逐项验证，不得依赖目测、均分或默认 gap。Navbar 默认态固定为：返回↔标题 2px、标题↔地址 8px、pin↔文字 1px、文字↔箭头 0px、地址↔右操作至少 16px、右操作内部 16px。
8. **适用结构默认使用自动布局** —— 行、列、内容簇、图标文字簇、左右操作组等适合自动布局的结构必须使用 Auto Layout / flex，并设置明确的方向、对齐、hug/fill 与 token gap；只有状态栏等规范明确要求固定坐标的系统元素可使用固定定位。
9. **规范资产优先且不可替画** —— 导航、状态栏及业务图标必须调用规范目录中已有的正式 SVG/图片资产；文字必须保持可编辑。除非用户明确指定修改，否则不得自行改造资产、重绘图标、轮廓化文字或改变组件样式。

### ❌ MUST NOT
1. 不内嵌散落 token、不写魔法值（hex/px/字号/圆角/z）。查不到 token 的值 → **停下报「未覆盖项」**，不就地编值。
2. 非例外不用 `style={{}}`。**例外仅**：换肤/营销渐变与半透明（进 `backgroundImage`/`rgba` token，仍走 class）、运营 PNG 底图（自营秒送/夜宵，`style={{backgroundImage:url(asset)}}` 内容资产）。
3. 不照搬 `get_design_context` 的 inline 绝对定位（`position:absolute; left/top`）；改写为 flex/gap 语义布局。
4. 不把 `Navbar`（layout）塞进 `atoms/`；不把 `HotTag`（atom）拆进 layout。
5. 不擅自增删/扁平化组件树或换肤主题；自营秒送品牌 lockup 缺资产时报告并文字降级，不硬画 SVG。
6. 不给导航条加投影（Zero/主稿均无 shadow）。
7. 不使用自动布局工具的默认间距，不以 `SPACE_BETWEEN` 代替规范要求的固定间距，不为“视觉更协调”自行调整 token。
8. 不复制现有 Zero 节点作为生成结果；必须依据本地 MD、Tokens 与正式资产重新搭建。

---

## Tokens

> 速览。完整含 `canonical` 反查与 Zero 节点出处见 [`TOKENS.json`](TOKENS.json)；→ class 见 [`token-class-map.md`](references/token-class-map.md)。

### 颜色 · foundation
| token | 值 | 主稿反查 | class |
|---|---|---|---|
| primary | `#ff0f23` | color.brand.primary | `text/bg-nav-primary` |
| title | `#171a26` | color.neutral.text.primary | `text-nav-title` |
| text | `#3d414d` | color.neutral.text.secondary | `text-nav-text` |
| surface | `#ffffff` | color.neutral.bg.surface | `bg-nav-surface` |
| background | `#f2f3f7` | color.neutral.bg.body | `bg-nav-body` |
| border / divider | `#00000014` (8% 黑) | color.neutral.border.default | `border-nav-border` / `bg-nav-border` |

### 颜色 · 频道换肤（fg=文案色 实测精确；bg 实测自 122:714）
| channel | fg | bg | class |
|---|---|---|---|
| default | `#171a26` | 透明（继承页面底） | `bg-nav-body` |
| waimai 外卖 | `#ffe5ba` | `linear-gradient(66deg,#7C3E1D→#6B300F)` | `bg-ch-waimai` |
| ziying 自营秒送 | `#171a26` | 运营 PNG（降级 `#fdeef0`） | `bg-ch-ziying-bg`+img |
| chaoshi 超市秒送 | `#470300` | `linear-gradient(68deg,#FEF3F2→#FCE4E3)` | `bg-ch-chaoshi` |
| yexiao 夜宵 | `#ffffff` | 运营 PNG（降级 `#4a3a8c`） | `bg-ch-yexiao-bg`+img |
| tuangou 美食团购 | `#ffffff` | `#9F1329` + 红向渐变叠加 | `bg-ch-tuangou` |
| jiazheng 京东家政 | `#ffffff` | `#ff0f23` | `bg-ch-jiazheng-bg` |
| 自营秒送 lockup | 自营 `#ffffff` / 秒送 `#4b3c02` | — | `text-ziying-zy` / `text-ziying-ms` |
| 热标 HotTag | `linear-gradient(42deg,#FF1136→#F91525)` 白字 | — | `bg-hot-tag` |

### 字体（family：brand=京东朗正体 V2.0 `jingdonglangzhengti2`；sans=PingFang SC…）
| role | 字体/字号/字重/行高 | 用途 | class |
|---|---|---|---|
| navTitle | brand 20/600/20 | 频道标题（category），色随 fg | `font-brand text-nav-title` |
| ziyingTitle | sans 17/600/17 | 自营秒送 lockup | `font-sans text-nav-ziying font-semibold` |
| addressText | sans 13/500/13 | 地址，色随 fg | `font-sans text-nav-address` |
| searchPlaceholder | sans 14/400/14 (#3d414d) | 搜索底纹词 | `font-sans text-nav-search text-nav-text` |
| searchButton | sans 14/500/14 (#171a26) | 搜索按钮 | `font-sans text-nav-search font-medium text-nav-title` |
| hotTag | brand 10/600/9 (白) | 热标 | `font-brand text-nav-hot text-white` |
| statusBarTime | sans 15/500/18 | 状态栏时间，色随 fg | `font-sans text-nav-time` |

> 13px(addressText) 是 Zero 临时字号、20px(navTitle) 超主稿 18 字阶、searchButton 用 500(Zero 苹方Medium) —— 均为 strict-match 保留，已在 TOKENS.json 标注出处，**非随手魔法值**。

### 间距（全命中主稿 spacing 档）
| token | px | 主稿 | class | 用途 |
|---|---|---|---|---|
| screenEdge | 8 | safe-area.screen-edge | `px-nav-edge` | 行左右 inset / 上划 pl |
| searchPadX/Y | 12 / 8 | spacing.12 / .8 | `px-nav-search-x py-nav-search-y` | 搜索框内距 |
| searchLeftGap / RightGap | 4 / 8 | icon-text-gap / .8 | `gap-search-l` / `gap-search-r` | 搜索左/右簇 |
| rightOpsGap | 16 | spacing.16 | `gap-nav-gap` | 右操作 / 上划右簇 |
| titleBackGap / AddressGap | 2 / 8 | spacing.2 / .8 | `gap-title-back` / `gap-title-address` | 默认态左簇 |
| stickyRowPadY / PadRight | 7 / 12 | spacing.7 / .12 | `py-sticky-y` / `pr-sticky-r` | 上划行 |

### 尺寸 · 圆角 · 阴影 · 层级
| 项 | 值 | class |
|---|---|---|
| 状态栏 / 导航行 / 搜索行 高 | 44 / 44 / 30 | `h-status-bar` `h-nav-row` `h-search-row` |
| 基准宽 | 375 | — |
| 图标：导航 / 搜索 / pin / 箭头 | 20 / 16 / 15 / 12 | `w-5` `w-4` `w-[15px]` `w-3` |
| 圆角：搜索框 | 4 (radius.s) | `rounded-search` |
| 圆角：热标 TL/TR/BR/BL | 4/4/4/1 | `rounded-search rounded-bl-[1px]` |
| 阴影 | **none**（Zero/主稿均无） | 不加 |
| 层级：navbar / sticky / statusBar | 30 / 40 / 50 | `z-30` `z-navbar-sticky` `z-50` |

---

## 组件规范

> 速览（节点/级别/结构/Props/变体/token）。每个组件的完整解剖与代码骨架见 [`components/{Name}.md`](components/)。

### Navbar（layout）· `86:1937` 默认 / `86:2129` 上划
- **结构-默认**：`StatusBar(44)` → 导航行(44, `px-8` items-center)：左簇 `[Back]—2—[Title]—8—[Address]`、右簇 `RightActions(gap16)` → 搜索行(30, `px-8`)：`SearchBar w-full`。
- **结构-上划**：`StatusBar(44)` → 单行(`pl8 pr12 py7` gap8)：`[Back] [SearchBar flex-1]—16—[RightActions]`；隐藏 Title/Address；容器 `sticky top-0 z-navbar-sticky`。
- **Props**：`channel`(7) `state`('default'|'sticky') `title` `address` `placeholder` `hotTag` `followed` `time` `bgImageUrl` + 5 回调。
- **变体**：channel × state；换肤 bg/fg 见 Tokens；搜索框恒白底不随频道变。

### StatusBar（atom）· `86:2013`
iOS 状态栏，375×44。左时间(15/500)、右信号/Wifi/电量。**系统 chrome，仅预览用**。Props：`time` `colorClass`。token：`h-status-bar` `text-nav-time`。

### BackButton（atom）· `74:2516` / `86:1941`
返回箭头按钮 20×20，`currentColor` 随 fg。Props：`count`('one') `colorClass` `onClick`。`<button aria-label="返回">`。

### ChannelTitle（atom）· `74:2529`(category) / `74:2622`(ziying)
- `category`：纯文字 京东朗正体 **20/600**，色=频道 fg。
- `ziying`：品牌 lockup（苹方 17/600）—— 自营 `#fff` 落品牌 SVG 形状 + 秒送 `#4b3c02`；**优先用品牌资产**，缺则文字降级。
- Props：`text` `channel` `type`('category'|'ziying') `colorClass` `badgeAsset`。

### AddressBar（composite）· `74:2551` / `86:1943`
`[pin15]—1—[地址 13/500 可打点]—0—[chevron12 紧贴]`。**文字↔箭头 0px 恒定**（优先级高于「地址↔右操作 16px」）；地址过长致间距 <16px 时对文字打点(`truncate`)截断，箭头仍紧贴。色随 fg。Props：`address` `type`('category') `colorClass` `onClick`（外层传 `min-w-0`）。`<button>`+aria-label。token：`text-nav-address` `gap-px`（pin↔文字 1px；文字↔箭头同容器 0 间距）。

### SearchBar（composite）· `86:1963`(默认 359×30) / `92:600`(上划 flex-1)
白底 r4，`px-12`，高 30，`justify-between`。左簇(`gap-4`)：放大镜16 + 底纹词(14/400 #3d414d) + 可选 HotTag；右簇(`gap-8`)：竖分隔(1×12 8%黑) + 搜索(14/500 #171a26)。**恒白底深字**。Props：`placeholder` `hotTag` `state`('default') `searchText` `onSearch` `className`(父给宽 `w-full`/`flex-1`)。`role="search"`。

### RightActions（composite）· `74:3133`(关注) / `92:1414`(分享+更多)
`[Follow]—16—[Share]—16—[More]`，各 20×20，`currentColor` 随 fg。Props：`followed` `colorClass` `show`(子集) + 回调。关注 union `unfollowed|followed`（描边心/实心）；每枚 `<button>`+aria-label（关注 label 随态切换）。可拆 FollowButton/ShareButton/MoreButton 落 atoms。

### HotTag（atom）· `86:1963;74:2609`
搜索内「热」营销标。渐变底 `bg-hot-tag`，京东朗正体 10/600 白字，`px-[3px] py-[2.5px]`，圆角 4/4/4/1（`rounded-search rounded-bl-[1px]`）。Props：`text`('热')。微值已登记 `radius.hotTag`，有出处非魔法值。

---

## 执行流程
0. **解析入口**：链接→抽 fileKey/nodeId（`-`换`:`）；节点id 直接用；组件名→查 `components/<Name>.md` 的「Zero 节点」；空→默认整条 Navbar(`86:1937`/`86:2129`)。
1. **读 Zero（按需）**：`TOKENS.json`+`components/` 已是离线快照，常规生成直接用，**无需联网**。仅「快照缺该节点 / 用户说 Zero 改了 / 自检查不到值」时调 MCP：`get_design_metadata`→`get_design_context`→`get_variables`→`get_screenshot`。返回只是参考，必改写、绝不照搬 inline 定位。
2. **定 token 真源**：主源 `TOKENS.json`；foundation 终值以 `canonical` 指向的主稿 `tokens.json` 为准，漂移以主稿为准并回写+报告。
3. **读组件规范**：见上「组件规范」/ `components/{Name}.md`：Props、变体矩阵、各态 token、布局规则。
4. **token→class**：先把 `token-class-map.md §1` 的 `theme.extend` 幂等合并进目标 `tailwind.config.js`；再每值两跳映射 `Zero值→TOKENS→class`；查不到记「未覆盖项」。
5. **生成 3 文件**：按 `output-contract.md` 模板产 `{Name}.tsx + types.ts + index.ts` 落分级目录；生成 layout 连带其依赖（除非只点名子件）。
6. **自检**：跑 `output-contract.md` 末清单（grep 无裸值 / union·映射·variants 三处一致 / index 导出齐 / 尺寸对照 Zero / 6 频道+两态可渲染）；问题自动修。
7. **输出摘要**：文件清单(行数) + 用到的 token(路径+值+class) + 组件 props/变体 + Zero 来源 + 未覆盖项 + 是否需合并 tailwind.config（首次必提示）。

## 文件总览
```
navbar-generation/
├── SKILL.md            ← 本文件（触发/约束/Tokens/组件规范/流程，自包含）
├── .skill-meta.json    ← 元数据
├── TOKENS.json         ← Zero token 快照（颜色/字体/间距/圆角/阴影/层级 + 变体）
├── README.md
├── references/
│   ├── token-class-map.md   ← token → tailwind.config + 语义 class
│   └── output-contract.md   ← 3文件 + 四级目录 + 自检
└── components/         ← 8 份组件完整规范（Navbar/StatusBar/BackButton/ChannelTitle/AddressBar/SearchBar/RightActions/HotTag）
```
