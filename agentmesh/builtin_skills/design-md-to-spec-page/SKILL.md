---
name: design-md-to-spec-page
description: 把组件 bundle（design.md + spec.md + variants.md + behaviors.md + CHANGELOG.md；ai-schema.yaml 可选；v1.2 起 relay-to-design-md
  统一产此 bundle，旧单份 design.md 仍兼容读）渲染成一份对外、可展示的 **4 要素** 单页 HTML 规范文档（组件定义 / 行为准则 / 设计属性 / 应用场景），保留 Pro/Basic 切换 UI，沿用现有 V16
  token CSS variable 视觉语言。输出到组件目录下 spec-page.html。Triggered by /design-md-to-spec-page 或 "为 X 生成 spec 页"、"design.md to html"、"出一份
  X 的规范 HTML"。
allowed-tools:
- Bash
- Read
- Write
- Edit
- Glob
harness-version: 1
intent: 发布
profile: jd-v16
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/.agents/skills/design-md-to-spec-page/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
  short-description: 把组件 bundle（design.md + spec.md + variants.md + behaviors.md + CHANGELOG.md；ai-schema.yaml 可选；v1.2 起…
disable-model-invocation: true
---

# /design-md-to-spec-page · 单组件 design.md → 4 要素 spec HTML

> 📐 **本 skill 是「design.md 录入标准管线」的 ③ 发布段**。全链路权威流程 + checklist 见 [`../../shared/references/design-md-pipeline-sop.md`](../../shared/references/design-md-pipeline-sop.md)。

## 这个 skill 做什么

把**单个组件**的 design.md（或 page-doc 4 文件 bundle）渲染成一份**对外公开、可展示**的单页 HTML 规范，结构压成 **4 要素**：

1. **组件定义** — 一句话用途 / 边界
2. **行为准则** — 用户约定行为 / 反例边界
3. **设计属性** — 类型 / 解剖结构 / 尺寸布局 / token swatch / 演示 stage
4. **应用场景** — 典型场景 ✅ / ❌ Donts

视觉风格沿用 V16 token CSS variable 那套（与 portal `docs/design.html` / tabbar spec-page 一致），不改色彩 / 字体 / token swatch / 顶部 nav 的 V16 视觉语言。Pro/Basic 切换 UI 保留（设计师跨职能解读看 basic 段有价值）。

## 何时触发

| 场景 | 调用 |
|---|---|
| 用户调 `/design-md-to-spec-page <slug>` | 直接走 |
| 用户说"为 X 生成 spec 页" / "用 design.md 出一份 HTML 规范" / "把 X 的 design.md 渲染成对外站点单页" | 主动调 |
| 单份 design.md 内容更新 → 同步更新 spec-page.html | 主动调 |

## 不适用场景

| 场景 | 该走哪里 |
|---|---|
| 把仓库**所有** design.md 聚合成总站 | `design-md-to-portal` |
| 从 Relay 抽稿生成新 design.md | `relay-to-design-md` |
| 审稿 design.md 是否合规 | `design-review` |

## 职能边界（与姊妹 skill 配套）

| Skill | 输入 | 输出 |
|---|---|---|
| `relay-to-design-md` | Relay URL | design.md / bundle（编辑面） |
| `design-md-to-portal` | design.md 集合 | docs/design.html（总站发布面） |
| **`design-md-to-spec-page`（本）** | 单 design.md / bundle | `<slug>/spec-page.html`（单组件发布面） |
| `design-review` | design.md | review 报告（不改文件） |

---

## 执行流程（6 step）

### Step 1: 解析输入 + flag

支持 3 种调用形态：

```
/design-md-to-spec-page tabbar                    # 仅 slug，自动找路径
/design-md-to-spec-page jd-design-system-md-v16/foundations/components-base/tabbar/  # bundle 目录
/design-md-to-spec-page jd-design-system-md-v16/.../tabbar/design.md                # 单文件
```

输出路径：**`<bundle-dir>/spec-page.html`**（与 design.md 同目录）。

#### CLI flag（v2.0 简化版）

| flag | 默认 | 行为 |
|---|---|---|
| `--no-view-toggle` | 关 | 跳过 Pro/Basic 切换 UI，生成只读单视图（适合对外简报 / 印刷场景）|
| `--dry-run` | 关 | 渲染但不写文件，输出 diff（前 200 行 unified diff）|

> v2.0 砍掉的 flag：`--refresh-assets` / `--no-refresh-assets` / `--no-deploy`（切图链路 + deploy 整段砍了，skill 不越界做 git ops）。

### Step 2: 读 frontmatter + bundle 全文

读 `design.md` 的 frontmatter：
- `bundle: page-doc` + `bundle_files: [...]` 存在 → **page-doc bundle 模式**
- 否则 → **single 模式**

bundle 模式下追加读取 `spec.md` / `variants.md` / `behaviors.md` 全文，按 Step 3 映射。（`ai-schema.yaml` v1.2 起默认不产 —— **如有则读**进 meta + 页脚折叠区，缺则按 section-mapping §4 跳过，不阻断。）

> `ai-schema.yaml` 不进 4 要素正文，只参与 `<head>` meta（SEO / AI 探测）+ 页脚折叠区 `<details>`。详见 [references/section-mapping.md](./references/section-mapping.md)。

### Step 3: 判组件类型 → 选 schema → 映射章节

**先判组件类型**（[`../../shared/references/section-anchors.md`](../../shared/references/section-anchors.md) 判定表）：frontmatter `component_class` 显式 > 路径含 `/components-base/`(通用) > `product-architecture/`(业务) > 默认通用。

- **通用组件 → Schema A（4 要素）**：组件定义 / 行为准则 / 设计属性 / 应用场景。
- **业务组件 → Schema B（7 要素）**：组件定义(必) / 行为准则(选) / 组件类型(选) / 组件结构(必) / 组件设计属性(必) / 典型场景示意(必) / 错误示例(选)。

anchor slug 真相源 = section-anchors.md 两张表（不许漂）。字段映射详见 [references/section-mapping.md](./references/section-mapping.md)。

**Schema A（通用 4 要素）来源映射**：

| 章节 | anchor | 来源 |
|---|---|---|
| §1 组件定义 | `sec-1-definition` | `## 一句话定义` + frontmatter 边界 |
| §2 行为准则 | `sec-2-behavior` | `## 交互` + ai-schema donts |
| §3 设计属性 | `sec-3-attributes` | spec/token + variants 形态表 + 演示 stage（多变体走 showcase）|
| §4 应用场景 | `sec-4-scenarios` | `## 应用场景` ✅/❌ + Donts |

**Schema B（业务 7 要素）来源映射**：

| 章节 | anchor | 必/选 | 来源 |
|---|---|---|---|
| §1 组件定义 | `sec-1-definition` | 必 | `## 一句话定义` / 目的用途 |
| §2 行为准则 | `sec-2-behavior` | 选 | `## 交互行为` |
| §3 组件类型 | `sec-3-types` | 选 | `## 形态/变体` 分类（按交互/视觉/功能模式）|
| §4 组件结构 | `sec-4-structure` | 必 | `## 解剖结构` + **元素规范表**（必配/可选 · 使用上下限 · 字数限制 · 按钮数量）|
| §5 组件设计属性 | `sec-5-attributes` | 必 | token / 空间关系 / 对齐 / 间距 / 颜色（多变体走 showcase）|
| §6 典型场景示意 | `sec-6-scenarios` | 必 | `## 应用场景` 尽量覆盖全部典型场景 |
| §7 错误示例 | `sec-7-donts` | 选 | `## Donts` ❌ 反面案例 |

**缺数据处理**：**必写**缺 → 保留 `<h2>` + `<blockquote class="warn">⚠️ TBD…</blockquote>`（必写是契约，不跳）；**选写**缺 → **整段省略**（不留空 TBD，TOC 也不列）。

### Step 4: 填模板字符串

读 [templates/spec-page.html](./templates/spec-page.html)。占位符语义：

- `{{field}}` → 字面值替换
- 缺失数据 → 标 TBD，不留 `{{}}`
- **`{{toc_items}}`（v2.3）**：按所选 schema 输出 TOC `<li>`（每章一条，`<a href="#sec-N-{label}">章节名</a>`）；选写缺省的章节不列。
- **`{{sections_block}}`（v2.3）**：按所选 schema 输出全部 `<h2 id="sec-N-{label}"><span class="num">N</span>章节名</h2>` + 章节 HTML，模型逐章构造。通用 4 段 / 业务 7 段；`<h2>` 的 num 按章节序号。§3(通用)/§5(业务) 设计属性多变体走 showcase。

合并入 Step 4 的三件事：

#### 4a. Pro/Basic class 标记

`pro-only` / `basic-only` / `basic-only summary` 三 class，按 [references/view-toggle.md](./references/view-toggle.md) 给元素加。不加 class 的元素 → 两版共享。

`--no-view-toggle` 模式：跳过 `.title-row .view-tabs` 渲染 + 不输出末尾 view-toggle JS，所有内容默认可见（CSS class 失效不影响显示）。

#### 4b. V16 token CSS variable

模板 `<style>` 头部 `:root { --c-text: ... }` 等 CSS variable 直接按 [references/style-tokens.md](./references/style-tokens.md) 走 V16 tokens.json 的 hex 值。**禁止**：inline-style hex 颜色，直接 `style="color:#xxx"` 硬编码 V15 风格的颜色。

#### 4c. 顶部 5-zone nav（hardcode）

模板内 hardcode 5 个 zone link：knowledge / foundations / ai-mechanism / product-architecture / horizontal。根据 frontmatter `bg` 字段（或 bundle 路径顶层目录）自动加 `is-current` class：

| frontmatter `bg` / 路径顶层 | is-current 落点 |
|---|---|
| `knowledge/` | knowledge |
| `foundations/` | foundations |
| `ai-mechanism/` | ai |
| `product-architecture/` 或 `bg: horizontal` 且路径在 product-architecture/ 下 | arch |
| `horizontal/` | horizontal |

`{{rel_root}}` 按 bundle 相对 v16 根的路径段数算（每段一个 `../`），如 `foundations/components-base/tabbar/spec-page.html` → `../../../`。

#### 4d. 版本标签契约（自检 + 防回归）

生成 HTML 页头 / eyebrow / meta 时，版本标签必须从目标目录或 frontmatter 推导，**不允许从旧页面示例直接继承**。

| 输入位置 / 线索 | 页面展示 |
|---|---|
| `jd-design-system-md-v16/**` | `JD APP 16.0 GUIDELINE` / `Relay V16.0 GUIDELINE` |
| `jd-design-system-md/**` | `JD APP 15.0 GUIDELINE` / `Relay V15.0 GUIDELINE` |
| frontmatter 显式 `guideline_version` | 使用该字段，格式化为 `JD APP {version} GUIDELINE` |

防回归要求：V16 单组件页可见页头不得出现 `JD APP 15.0`。写入前用 `rg -n "JD APP 15\.0|V15\.0" <output-html>` 自检（V16 路径下必须 0 命中）。

#### 4f. Zone-aware sidebar 渲染（v2.1 起）

模板内有 `{{sidebar_block_or_empty}}` + `{{layout_close_or_empty}}` 一对占位符，决定是否在 `<div class="doc">` 左侧渲染 13 部门 sidebar：

| frontmatter `bg` / 路径顶层 | 是否渲染 sidebar | `{{sidebar_block_or_empty}}` 内容 | `{{layout_close_or_empty}}` 内容 |
|---|---|---|---|
| `product-architecture/` | 是 | `<div class="layout has-sidebar"><aside class="sidebar">...全套 13 部门 HTML...</aside>` | `</div><!-- /.layout -->` |
| 其它 zone（knowledge / foundations / ai-mechanism / horizontal） | 否 | `""`（空串） | `""`（空串） |

`product-architecture` 模式下的 sidebar 结构（hardcode 在 skill 里）：

```html
<div class="layout has-sidebar">
<aside class="sidebar" aria-label="🏗 组织架构 - 13 部门导览">
  <div class="sidebar__zone-tag">ZONE 04 · 🏗 组织架构</div>
  <div class="sidebar__group">
    <a class="sidebar__link" href="{{rel_root}}product-architecture/spec-page.html">页面说明</a>
  </div>
  <div class="sidebar__group">
    <!-- 13 部门行，按 controlled-vocab.json design_dept.values 顺序 -->
    {{sidebar_dept_<slug>_link}}   <!-- 每行：已录入 → <a>；未录入 → <span class="sidebar__link is-placeholder"> -->
  </div>
</aside>
```

**13 部门 slug 真相源**：[`../../../.agents/skills/relay-to-design-md/profiles/jd-v16/controlled-vocab.json`](../../../.agents/skills/relay-to-design-md/profiles/jd-v16/controlled-vocab.json) 的 `design_dept.values` 数组，与 V15 `jd-design-system-md/product-architecture/README.md` 13 设计部门一致。每个部门当前录入状态由 skill 内 hardcode `dept_content_status` 表决定（comprehensive-business + brand-and-marketing = 已录入；其余 11 = placeholder）。中文名 ↔ slug 对照见 [references/section-mapping.md](./references/section-mapping.md)。

**当前部门（is-current）判定**：
- 优先取 `frontmatter.design_dept` 字段
- 缺则从 bundle 路径推断：`product-architecture/<slug>/...` → slug
- 推断不出 → 任何部门都不加 `is-current`

#### 4f.1 占位符表

| 占位符 | 含义 | 取值 |
|---|---|---|
| `{{sidebar_block_or_empty}}` | 完整 sidebar HTML（含 `<div class="layout has-sidebar">` 开标签 + `<aside>`） | bg=product-architecture → 完整串；其它 zone → `""` |
| `{{layout_close_or_empty}}` | layout 闭标签 | bg=product-architecture → `</div><!-- /.layout -->`；其它 zone → `""` |
| `{{sidebar_dept_<slug>_cls}}` × 13 | 13 个部门各自的 class（`is-current` / 空） | 当前部门 → `is-current`；其它 → `""` |
| `{{sidebar_dept_<slug>_link}}` × 13 | 13 个部门各自的 `<a>` 或 `<span>` 整行 HTML | 已录入 → `<a class="sidebar__link {{cls}}" href="{{rel_root}}product-architecture/<slug>/spec-page.html">{中文名}</a>`；placeholder → `<span class="sidebar__link is-placeholder {{cls}}" title="该设计部门待录入">{中文名}</span>` |

> v2.1 之前的页面（无 sidebar）：占位符全空串，原 `<div class="doc">` 直接挂在 body 上，渲染结果与 v2.0 等价（CSS `.layout.has-sidebar` 没触发就不生效）。

#### 4e. 演示 stage 视觉还原优先级（v0.6 起，继续生效）

> **v2.2 起：多变体 / 双主题 / 移动端组件优先用「交互式 showcase」**（浅/暗切换 + 变体 tabs + 手机外框 + token 复制/悬停高亮），结构与组件视觉 CSS 约定见 [references/showcase.md](./references/showcase.md)。外壳 CSS+JS 已内置模板，作者只产出 `.showcase` 结构 + §3 内联组件视觉 `<style>`（含 @font-face / 图标 base64）。单一静态视觉（色板 / 字阶）仍用下列 `.stage` 系列，不必套 showcase。

1. **HTML / CSS / SVG 还原优先** — 任何能用前端代码做出来的视觉（布局 / 形状 / 颜色 / token swatch / ASCII 框图 / 简单插画）**都不用截图**。spec-page.html 直接渲染：
   - 色彩 token → `.color-swatch-grid`
   - 字阶演示 → `.size-ladder`（行 = sample + meta）
   - 价格 demo → `.price-demo`（5 档梯度 + ¥ 0.75x 缩放）
   - 倒计时 chip → `.countdown-demo`（`font-variant-numeric: tabular-nums` 等宽）
   - 布局结构 → 静态 div mockup 或 `<pre>` ASCII 框图
   - 简单图形 → inline SVG
2. **截图作为 backup** — 仅当前端无法还原时（设计师绘制的复杂插画 / 实拍 / 业务投放图 / 品牌角色），嵌在 §3 末尾，点击新 tab 看高清。
3. **截图不嵌入文字标注** — 设计师文字描述（章节标题 / 尺寸数字 / 备注）必须抽到 design.md 用 markdown 结构化呈现，**不留在截图里**。pixel 死数据不可搜不可解析。

### Step 5: 写文件 + 校验

> `--dry-run` 模式：**不写文件**，改在终端打 unified diff（旧 spec-page.html vs 新渲染串）。完成后退出。

1. `Write` 到 `<bundle-dir>/spec-page.html`
2. 校验清单（4 项必跑）：
   - `grep -E '\{\{[^}]+\}\}' <output>` → 0 命中（无 `{{` 占位符残留）
   - V16 路径下 `rg "JD APP 15\.0|V15\.0" <output>` → 0 命中（无版本标签污染）
   - 锚点齐全（按 schema）：**通用** `grep -cE 'id="sec-1-definition|id="sec-2-behavior|id="sec-3-attributes|id="sec-4-scenarios"'` → 4；**业务** 必含 4 个必写锚点 `id="sec-1-definition` / `sec-4-structure` / `sec-5-attributes` / `sec-6-scenarios`（选写的 sec-2/3/7 视内容可有可无）
   - `grep -cE 'class="[^"]*pro-only|class="[^"]*basic-only' <output>` → 合理（Pro/Basic class 双向都有元素，无 view-toggle 模式下应为 0）
3. **不要**自动打开浏览器（对外发布物，由用户决定何时 publish）。

#### v2.0 dry-run 实现

```bash
if [ "$FLAG_DRY_RUN" = "1" ]; then
  TMP=$(mktemp)
  printf '%s' "$NEW_HTML" > "$TMP"
  if [ -f "$BUNDLE_DIR/spec-page.html" ]; then
    diff -u "$BUNDLE_DIR/spec-page.html" "$TMP" | head -200 || true
    echo "💡 --dry-run 模式：仅 diff，不写文件。如要落盘，去掉 --dry-run 重跑"
  else
    echo "🆕 --dry-run + 新文件：会创建 $BUNDLE_DIR/spec-page.html（$(wc -c < "$TMP") bytes / $(wc -l < "$TMP") 行）"
  fi
  rm -f "$TMP"
  exit 0
fi
```

### Step 6: 终端输出

```
✅ 已生成: {output_path}
   ├─ 章节齐全度: 4/4
   ├─ TBD 段: {N} 个（详见 HTML 内 blockquote.warn）
   ├─ Pro/Basic class 计数:
   │    pro-only        : {N}
   │    basic-only      : {M}
   │    basic-only summary: {K}
   ├─ 视图模式: {view-toggle | no-view-toggle}
   └─ 字数: {N} 字 / 行数: {M}

📎 来源: {bundle 或 single design.md path}
📌 渲染样式: V16 token CSS variable（与 portal docs/design.html 一致）

{如有 TBD / 字段缺失}
⚠️ 检测到 {K} 处来源 design.md 数据缺失，已在 HTML 内标 ⚠️ TBD，建议回补 design.md 后重跑

{若 --dry-run}
💡 --dry-run 模式：仅 diff 不写文件。去掉 --dry-run 重跑落盘
```

---

## 关键约束

1. **不要修改 design.md / spec.md / variants.md / behaviors.md** — 这个 skill 是只读源 + 渲染发布物
2. **不要编造数据** — design.md 缺哪段，HTML 对应章节就标 TBD
3. **不要 invent CSS 风格** — 严格基于 V16 token CSS variable 模板，需要调样式时改 [templates/spec-page.html](./templates/spec-page.html)
4. **不要把 4 要素合并 / 拆分** — 数量固定 4。即使内容稀薄也要保留章节标题（标 TBD）
5. **不要嵌入 inline-style hex 颜色** — 走 CSS variable
6. **演示 stage HTML/CSS/SVG 优先** — 截图只作 backup，严禁带文字标注
7. **不做 git ops / deploy** — skill 不越界做 commit / push / `.nojekyll` / Pages build；user 自己决定何时 publish
8. **不做切图导出 / 增量启发** — 无切图链路，无 mtime 比对
9. **Output 路径固定**：`<bundle-dir>/spec-page.html`，不要换文件名 / 位置

## References

跨 skill 共享（`../../shared/references/`）：

| 文件 | 作用 |
|---|---|
| [section-anchors.md](../../shared/references/section-anchors.md) | 4 章节 canonical 名称 + anchor slug，与总站 design.html 共用 |

本 skill 私有（`templates/`, `references/`）：

| 文件 | 作用 |
|---|---|
| [templates/spec-page.html](./templates/spec-page.html) | 4 要素单页 HTML 模板（V16 token CSS variable）+ 交互式 showcase 外壳（v2.2） |
| [references/showcase.md](./references/showcase.md) | 交互式 showcase 结构契约（v2.2）：浅/暗切换 + 变体 tabs + 手机外框 + token 复制/高亮 |
| [references/section-mapping.md](./references/section-mapping.md) | 4 要素 ↔ design.md / bundle 字段详细映射表（含 7→4 改造对照） |
| [references/style-tokens.md](./references/style-tokens.md) | CSS variable ↔ V16 tokens.json 映射 |
| [references/view-toggle.md](./references/view-toggle.md) | Pro / Basic 视图切换标记规则 — 元素级 / inline / 4 要素标记策略 |

弃用（保留原位、SKILL.md 不再引用，文件头加"已弃用 by v2.0"注释，给后悔留路径）：

| 文件 | 弃用原因 |
|---|---|
| `references/stage-images-export.md` | v2.0 砍切图链路（HTML/CSS/SVG 还原优先 + 截图仅 backup） |
| `references/deploy-notes.md` | v2.0 砍 deploy 自动化（skill 不越界做 git ops） |

## 版本历史

- **v2.3** (2026-06-01) 按组件类型分 schema：**通用组件(components-base) 4 要素 / 业务组件(product-architecture) 7 要素**(组件定义·必 / 行为准则·选 / 组件类型·选 / 组件结构·必 / 组件设计属性·必 / 典型场景示意·必 / 错误示例·选)。Step 1 判 `component_class`(frontmatter > 路径);模板章节区参数化为 `{{toc_items}}` + `{{sections_block}}`(支持 4/7 段);必写缺→TBD、选写缺→整段省略。anchor 真相源 section-anchors.md 扩为双表(Schema A/B)。
- **v2.2** (2026-05-29) 交互式 showcase：§3 演示 stage 从静态平铺升级为可交互展示台 —— ① 浅/暗主题切换（`[data-theme]` 锚）② 变体切换 tabs ③ 手机外框 device-frame（375）④ token 点击复制 + 悬停高亮联动。外壳 CSS+JS 内置模板，新增 [references/showcase.md](./references/showcase.md) 结构契约；多变体/双主题/移动端组件优先用 showcase，单一静态视觉仍用 `.stage` 系列。首个落地：`components-base/toolbar-general`。
- **v0.1** (2026-05-14) MVP：7 章节固定结构 + jd-toast-spec 模板
- **v0.2** (2026-05-14) 切图能力（chunked b64 + sharedPluginData + dump-readback）
- **v0.3** (2026-05-14) Pro / Basic 视图切换 + 增强 token 分层
- **v0.3.1** (2026-05-14) GitHub Pages 部署实战 + deploy-notes.md
- **v0.4** (2026-05-15) 部署自动化 + cache-bust + 切图融合度
- **v0.4.1** (2026-05-15) Basic 段写作模式沉淀（5 pattern）
- **v0.5** (2026-05-18) 增量更新逻辑（mtime 启发 + `--refresh-assets` / `--dry-run` flag）
- **v0.5.1** (2026-05-19) 顶部 5-zone nav 进模板
- **v0.6** (2026-05-27) 视觉还原 HTML/CSS/SVG 优先 + 截图不嵌入文字标注
- **v2.1** (2026-05-29) zone-aware sidebar：bg=product-architecture 时在 `.doc` 左侧加 13 部门 sidebar（页面说明 + 13 部门，按 V15 README 真相源 slug + dept_content_status hardcoded 决定 link 还是 placeholder，当前部门加 is-current）；其它 zone 仍走顶部 5-zone nav-only 模式。`controlled-vocab.json design_dept.values` 同步切换到 V15 业务设计部门维度（13 个 slug），原技术 BG 维度旧 13 个标 `$migration_note` 留档。
- **v2.0** (2026-05-29) 4 要素改造（设计师 review 定调）：
  - **① 7 章节压成 4 要素**：组件定义 / 行为准则 / 设计属性 / 应用场景。jd-toast 7 章节模板对业务规范不贴合，2026-05-28 设计师 review 后定调
  - **② 流程 11 step → 6 step**：砍 Step 5a 增量启发 / Step 5b 切图导出 / Step 7b cache-bust / Step 9 deploy。Step 4 合并 Pro/Basic class 标记 + token CSS variable + 5-zone nav + 视觉还原优先级 + 版本标签自检
  - **③ Pro/Basic 切换保留**：设计师跨职能解读看 basic 段有价值，[view-toggle.md](./references/view-toggle.md) 真相源跟着留
  - **④ 视觉风格沿用**：V16 token CSS variable + portal `docs/design.html` 一致，只改章节结构不改色彩 / 字体 / token swatch / 顶部 nav
  - **⑤ CLI flag 简化**：保留 `--no-view-toggle` / `--dry-run`；砍 `--refresh-assets` / `--no-refresh-assets` / `--no-deploy`
  - **⑥ 顶部 5-zone nav hardcode**：模板内直接 hardcode 5 个 zone link，根据 frontmatter `bg` 字段自动加 `is-current`，不再依赖外部 zone-mapping 计算
  - **⑦ References 收口**：[section-mapping.md](./references/section-mapping.md) / [view-toggle.md](./references/view-toggle.md) / [style-tokens.md](./references/style-tokens.md) 保留；[stage-images-export.md](./references/stage-images-export.md) / [deploy-notes.md](./references/deploy-notes.md) 弃用（原位标注，给后悔留路径）
  - **⑧ Skill 自给自足**：不依赖 git ops / 不依赖切图链路 / 不依赖 cache-bust / 不依赖 deploy
