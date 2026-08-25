---
name: design-md-to-portal
harness-version: 0
description: 把 jd-design-system-md-v16/**/design.md 集合一键聚合成 docs/design.html —— 一份对外公开的 16.0 GUIDELINE 设计系统总站。零输入、全量重建、覆写。仅做骨架，大量
  section 留 TBD 占位，预期多轮迭代。Triggered by /design-md-to-portal or verbs like "更新设计站", "重建 design.html", "发布最新设计系统", "把新规范挂上站点".
allowed-tools:
- Bash
- Read
- Write
- Edit
- Glob
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/.agents/skills/design-md-to-portal/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
  short-description: 把 jd-design-system-md-v16/**/design.md 集合一键聚合成 docs/design.html —— 一份对外公开的 16.0 GUIDELINE 设计系统总站。零输…
disable-model-invocation: true
---

# /design-md-to-portal · design.md 集合 → docs/design.html

把仓库内**所有**已存在的 `design.md`（V16 规范源）聚合成一份 `docs/design.html` 对外站点。

**职能边界**（与姊妹 skill 配套）：

| Skill | 输入 | 输出 | 用户 |
|---|---|---|---|
| `relay-to-design-md` | Relay URL | `design.md`（编辑面） | 设计师 maintainer |
| **`design-md-to-portal`（本）** | `design.md` 集合 | `docs/design.html`（发布面） | 公开站访客 |

本 skill **不调 Relay MCP**，**不**修改任何 `design.md` 源 —— 只读 + 渲染 + 覆写发布产物。

## 何时触发

满足任意一项：

- 用户调 `/design-md-to-portal`
- 用户说「更新设计站」/「重建 design.html」/「把新规范挂上站点」/「发布最新设计系统」
- 任何一份 `design.md` 新增 / 修改后，希望对外站点同步

## 不适用场景

| 场景 | 该走哪里 |
|---|---|
| 从 Relay 抽稿生成新 `design.md` | `relay-to-design-md` |
| 修单份 `design.md` 内容 | 手动 `Edit` |
| 审单份稿是否合规 | `design-review` |
| 生成 V15 站点 | 不适用（本 skill 只扫 V16） |

## 输入解析

- **glob**：`jd-design-system-md-v16/**/design.md`（递归全量)
- **不扫**：`jd-design-system-md/`（V15 已冻结)
- 每份读 **frontmatter 全部字段 + 正文 H2 段第一段作摘要**(章节级,不读全文)

> 实战修订(2026-05-18):原版宣言"只读 frontmatter 不读正文",但 Step 3 渲染表实际要正文 `## 定义` / `## 行为准则` / `## 结构` 段。两者矛盾。统一改为:**读 frontmatter 全部字段 + 正文 H2 段首段(每段取 1-3 行作卡片摘要)**,这是当前真实实现。

### 必读 frontmatter 字段(对齐 [`../relay-to-design-md/references/frontmatter-spec.md`](../relay-to-design-md/references/frontmatter-spec.md) 实际产物)

| 字段 | 用途 | 缺失兜底 |
|---|---|---|
| `file` | 校验是 design 主文件(bundle 模式 spec/variants/behaviors 不进站点 TOC) | ≠ `design` 跳过 |
| `bundle` | 标识 bundle 主文件;`bundle_files[]` 不展开,仅 design.md 入站 | 单 md 模式正常 |
| `slug` | section id + TOC 锚点 | 从文件路径推断 |
| `name_zh` | section 标题 + TOC 文案 | `slug` |
| `name_en` | section 副标题 | 空 |
| `level` | section 分组(枚举见 [`../../shared/references/level-vocab.md`](../../shared/references/level-vocab.md)) | `uncategorized` |
| `bg` | 业务背景标签 | 空 |
| `status` | 角标(draft / review / published / deprecated) | `draft` |
| `version` | 版本号 | `0.0` |
| `last_synced` | 抓取时间 | 空 |
| `relay_source.url` | 源链接(顶层 + 一层嵌套) | 空 |
| `references.uses_components` | 关联组件列表(渲染为站点内 cross-link) | `[]` |

> **uses_tokens / variants 不在 frontmatter**:relay-to-design-md 实际产物把这两类放在 design.md / spec.md(bundle)主体表格(`## 视觉` 表 / `## 变体 Variants` 段),frontmatter 只放 frontmatter-spec.md 列出的 14 个顶层字段。

### 读正文 H2 段首段(章节级摘要)

每份 design.md 渲染卡片时,从正文取以下 H2 段的**首段文字**(1-3 行):

| H2 段标题 | 取到的渲染到卡片哪 |
|---|---|
| `## 一句话定义` 或 `## 定义` | 卡片副标"定义"段 |
| `## 行为准则` 或 `## 交互` | 卡片"行为准则"段 |
| `## 视觉` 或 `## 结构` | 卡片"结构"段(只取概述句,不进表格) |
| `## 应用场景` | 卡片"典型场景"段 |
| `## 错误示例` 或 `## Donts` | 卡片"错误示例"段 |

> 缺段或段实质空(HTML 注释占位 / `<!-- TBD -->`)→ 站点卡片显示 `<!-- TBD -->` 占位文案,不报错。

> **bundle 模式特殊处理**:bundle 主文件 design.md 通常正文很薄(只放章节大纲表 + 链接),要展开摘要应转读 \`spec.md\` / \`behaviors.md\` 对应段。若不想做这步,fallback 渲染 "## 这是 page-doc bundle" 段提示用户跳详情页。

### 配套资源

每份 spec **可选**有一张同目录截图（推测约定：`preview.png` / `design-screenshot.png`）。skill 启动时按以下顺序探测，命中即用，找不到就用占位灰底：

1. 同目录 `preview.png`
2. 同目录 `design-screenshot.png`
3. 占位灰底（CSS `background: #f0f0f0`）

### banner 装饰图资产

`docs/design.html` 顶部 banner 右侧的装饰图(Relay 节点 `6:229;6:10`,548×240)走 **fallback 优先 + 手动是 nice-to-have** 约定:

- **fallback 永远兜底**:HTML 中已预置 CSS 径向渐变。PNG 缺失时站点正常渲染(只是装饰差点意思),**不报错、不阻断、跑批安全**
- **手动 export 可选**:设计师有空时,Relay 桌面端选中节点 → Export PNG → 落 `docs/assets/banner-art.png`,有则覆盖 CSS 渐变
- skill 本身**不**自动抓这张图(MCP `get_screenshot` 返回内联截图,没法落盘;且 banner 是装饰非内容,缺失不影响信息)

> 设计原则:**任何依赖手动操作的资产都走"自动 fallback + 手动覆盖"模式**,跑批时永不卡住。

详细规范见 `docs/assets/README.md`。

## 工作流

### Step 1 · 扫所有 design.md

```bash
find jd-design-system-md-v16 -name "design.md" -type f
```

### Step 2 · 解析每份 frontmatter

逐份读首 `---` ~ `---` 段，提取上表字段。frontmatter 解析按 YAML，但**只**取顶层 + `relay_source.url`，深层结构 TBD。

### Step 3 · 按 PDF 范式渲染 sections

每份 spec 按「design.html 范式」（见 `docs/design.html` v0.2）输出**示意黄头 + 7 圆点章节**。章节 anchor slug **必须**对齐 [`../../shared/references/section-anchors.md`](../../shared/references/section-anchors.md)（与详情页 spec-page.html 共用,允许章节渲染深度差异化,但 `id=` 不许漂）。

| 章节（PDF 顺位） | 必/选 | 数据源(对齐"读正文 H2 段首段"契约) |
|---|---|---|
| 示意黄头 | — | frontmatter `name_zh` / `name_en` / `status` / `version` / `relay_source.url` |
| `{{name_zh}} 定义` | 必写 | 正文 `## 一句话定义` 或 `## 定义` 段**首段** |
| `行为准则` | 选写 | 正文 `## 行为准则` 或 `## 交互` 段**首段** |
| `{{name_zh}} 类型` | 选写 | 正文 `## 变体 Variants` 段**首段**(bundle 模式转读 `variants.md`)|
| `{{name_zh}} 结构` | 必写 | 正文 `## 视觉` 或 `## 结构` 段**首段**(只取概述句,不进表格;bundle 模式转读 `spec.md`)|
| `设计属性` | 必写 | 主体 `## 视觉` 段下的 token 引用表(实际产物把 token 放主体而非 frontmatter,见上文 frontmatter 字段表注释) |
| `典型场景示意` | 必写 | 同目录 `preview.png` + `relay_source.url` + 正文 `## 应用场景` 段**首段** |
| `错误示例` | 选写 | 正文 `## 错误示例` 或 `## Donts` 段**首段** |

> 上表口径与"读正文 H2 段首段"段(输入解析)一致。所有 H2 段缺或实质空 → 该卡片章节渲染 `<!-- TBD -->` 占位文案,**不报错**。

**渲染规则**：
1. 复制 `references/site-template.html` 末尾的 **SPEC_SECTION 模板**
2. 替换 `{{spec_*}}` 占位符
3. 缺失字段保留 `<!-- TBD -->` 注释 + 一句话占位文案（不报错）

### Step 4 · 拼接 sections

- `{{spec_sections}}`：所有 spec sections 串联，按 frontmatter `level` 分组 —— 词表见 [`../../shared/references/level-vocab.md`](../../shared/references/level-vocab.md)（`foundation` / `component-base` / `component-business` / `page` / `flow`，**不要**把 `bg` 值如 `horizontal` 当 level 用）
- `{{generated_at}}`：ISO 时间戳
- **顶部 banner 和「规范要素参考」蓝框是固定的**，已写在 site-template.html 主体内，不需替换

### Step 5 · 覆写 docs/design.html

```bash
# 不 append，每次全量重建
```

写完跑 `git diff docs/design.html` 给用户看，等他 review。

**关于已删除 design.md 的清理**:Step 1 glob 扫**当前**仓库 design.md 集合,删过的文件不在结果里 → Step 4 全量重建产物自然不含该 section → Step 5 覆写 `docs/design.html` 后旧 section 消失。**整链路天然处理**,无需显式 GC 逻辑。设计师只需删 design.md 文件并重跑 \`/design-md-to-site\`。

## 输出契约（v0.2 PDF 范式）

`docs/design.html` 必须包含：

- ✅ **顶部唯一 banner**（16.0 GUIDELINE 板式，全站只一次）
- ✅ **规范要素参考蓝框**（按 PDF 完全照搬 7 条，固定不动）
- ✅ 每份 spec：**示意黄头 + 7 圆点章节**（定义 / 行为准则 / 类型 / 结构 / 设计属性 / 典型场景 / 错误示例）
- ✅ 页脚生成时间戳

**不要**：
- ❌ 每个 spec 再加 banner —— 顶部已唯一，spec 内只用 `<h3>` 圆点
- ❌ 加全站 TOC —— PDF 范式没有 TOC，长文章自然流式阅读

详见 `references/site-template.html` 顶部注释和文件末尾的 SPEC_SECTION 模板。

## 偏好默认值（无需追问）

| 项 | 默认 |
|---|---|
| 输入 glob | `jd-design-system-md-v16/**/design.md` |
| 输出路径 | 仓库根 `docs/design.html` |
| 截图相对路径 | 从 `docs/design.html` 看，是 `../jd-design-system-md-v16/.../preview.png` |
| 缺 frontmatter 字段 | 按上表 fallback，不报错 |
| 缺截图 | 占位灰底 |
| 全量重建 | 是，每次覆写 |
| 触发节奏 | 用户手动 `/design-md-to-portal`，**不自动**跟 design.md 变更联动 |

## 与其他 skill 的关系

- `relay-to-design-md` 上游：先有 `design.md`，再聚合
- `design-review` 平行：reviews `design.md`，本 skill 渲染同一份
- 4 份手写 HTML（executive-summary / master-diagram / knowledge-tree / contributor-guide）：与本 skill 产出的 `design.html` **同级共存**在 `docs/` 下，footer 互链 TBD

## 参考资源

跨 skill 共享(`../../shared/references/`):
- [`level-vocab.md`](../../shared/references/level-vocab.md) —— `level` 枚举词表 + 与 `bg` 边界
- [`section-anchors.md`](../../shared/references/section-anchors.md) —— 7 章节 canonical anchor slug,与详情页 spec-page.html 共用

本 skill 私有(`references/`):
- `header-template.md` —— 16.0 GUIDELINE banner 板式（HTML 块 + 占位符 + 设计参数）
- `site-template.html` —— 完整站点 HTML 骨架 + SPEC_SECTION 模板 + 所有 TBD 占位
- `design-html-paradigm.pdf` —— **范式真相源**：design.html 文档范式 PDF（顶部 banner + 规范要素参考蓝框 + 示意黄头 + 7 圆点章节）。改板式结构前先重读这份 PDF。
