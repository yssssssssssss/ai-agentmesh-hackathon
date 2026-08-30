---
name: knowledge-preview
harness-version: 0
description: '知识库可视化预览工具。AI 只生成数据文件，HTML 模板静态复用，大幅减少 token 消耗。 支持增量模式，只更新有变化的 Case。 /knowledge-preview                  ←
  增量更新数据 + 打开浏览器 /knowledge-preview <case文件路径>   ← 只更新指定 Case 的数据 /knowledge-preview --full           ← 强制重新生成所有数据 /knowledge-preview
  --init           ← 首次初始化，写入静态模板文件

  '
user-invocable: true
triggers:
- 生成预览
- 更新预览文件
- 生成 cases.js
allowed-tools:
- Bash
- Read
- Write
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/huangliu-design/product-details/JD-ProductDetails-web/brain-frontend/public/design-kb/skills/knowledge-preview/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
  short-description: 知识库可视化预览工具。AI 只生成数据文件，HTML 模板静态复用，大幅减少 token 消耗。 支持增量模式，只更新有变化的 Case。 /knowledge-preview ← 增量更新数据 +…
disable-model-invocation: true
---

# /knowledge-preview · 知识库可视化预览

## 工作目录

执行本 skill 前，请先定位到仓库中的 `JD-ProductDetails-web/brain-frontend/` 目录，
所有路径均以此为根目录。

## 这个 Skill 做什么

把 reasoning.md 渲染成可在浏览器查看的 HTML 页面，核心优化：

- **AI 只生成数据（JSON），不生成 HTML/CSS/JS**
- 静态模板文件一次写入，永久复用，每次调用节省 ~90% token
- 增量模式：只更新比 HTML 更新的 reasoning.md

## 文件结构

```
public/design-kb/knowledge/preview/
├── _template.html     ← 静态模板，--init 时写入，之后不再修改
├── _cases.js          ← AI 每次生成的数据文件（所有 Case 的索引数据）
├── index.html         ← 软链接或复制自 _template.html，读取 _cases.js 渲染
└── cases/
    ├── pc-national-subsidy.js        ← 每个 Case 的详情数据
    └── app-national-subsidy-multisku.js
```

---

## 执行流程

### Step 0：检查模板是否存在

```bash
ls public/design-kb/knowledge/preview/_template.html 2>/dev/null
```

- 存在 → 继续
- 不存在 → 自动执行 `--init` 写入模板，然后继续

---

### Step 1：判断运行模式

- 有文件路径参数 → 只更新该 Case 的数据文件
- `--full` → 重新生成所有 Case 数据
- `--init` → 写入静态模板文件（见 Step Init）
- 无参数 → 增量模式

---

### Step 2：增量筛选

```bash
# 找出比对应 .js 数据文件更新的 reasoning.md
find public/design-kb/knowledge/ -name "*-reasoning.md" | while read f; do
  slug=$(basename "$f" -reasoning.md)
  js="public/design-kb/knowledge/preview/cases/${slug}.js"
  if [ ! -f "$js" ] || [ "$f" -nt "$js" ]; then
    echo "$f"
  fi
done
```

输出需要更新的文件列表：
```
增量检查：9 个 Case
- 需要更新：2 个
- 跳过：7 个（数据已是最新）
```

---

### Step 3：为每个需要更新的 Case 生成数据文件

**只用 Bash 读取文件，不用 Read 工具**，减少 token 消耗：

```bash
# 读取 frontmatter（只读前 30 行）
head -30 public/design-kb/knowledge/scene/strategies/nationalSubsidy/pc-national-subsidy-reasoning.md

# 读取各章节内容（用 grep + sed 提取）
grep -n "^## " public/design-kb/knowledge/scene/strategies/nationalSubsidy/pc-national-subsidy-reasoning.md
```

提取内容后，生成 `public/design-kb/knowledge/preview/cases/[slug].js`：

```javascript
window.CASE_DATA['pc-national-subsidy'] = {
  slug: 'pc-national-subsidy',
  feature_name: 'PC接入国补',
  product_area: 'scene/strategies/nationalSubsidy',
  platform: 'PC',
  last_updated: '2024-12-05',
  keywords: ['国补','国家补贴','促销行','引导行','资格判断'],
  relay_url: 'https://relay.jd.com/...',
  screenshots: [
    { label: '设计稿全览', url: 'https://img30.360buyimg.com/...' }
  ],
  related_cases: [
    { slug: 'app-national-subsidy-multisku', note: 'App 端参考方案' }
  ],
  sections: {
    background: '用户问题、业务影响、根本原因的文字内容...',
    goal: '设计目标与边界的文字内容...',
    constraints: [
      { type: '技术约束', content: '...' },
      { type: '业务约束', content: '...' }
    ],
    before_after: [
      { before: '...', decision: '...', after: '...' }
    ],
    decisions: [
      { title: 'Decision 1：...', decision: '...', reason: '...', excluded: '...', impact: '...' }
    ],
    states: [
      { name: '默认状态', visual: '...', note: '...', star: false },
      { name: '⭐ 容易遗漏的状态', visual: '...', note: '...', star: true }
    ],
    copy_decisions: [
      { element: '...', copy: '...', reason: '...', excluded: '...' }
    ],
    exclusions: '有意排除的内容...',
    patterns: [
      { title: 'Pattern 1：...', applies: '...', not_applies: '...', principle: '...' }
    ],
    issues: [
      { problem: '...', owner: '...', status: '...' }
    ]
  }
};
```

**生成规则：**
- 文字内容保留 Markdown 格式，模板负责渲染
- 表格数据转为数组对象
- TODO 项保留原文 `TODO: 待补充`，模板会高亮显示
- 每个 Case 的 JS 文件独立，不影响其他 Case

---

### Step 4：更新索引数据文件

每次运行结束，用 Bash 读取所有 Case 的 frontmatter（只读前 30 行），生成 `public/design-kb/knowledge/preview/_cases.js`：

```javascript
window.ALL_CASES = [
  {
    slug: 'pc-national-subsidy',
    feature_name: 'PC接入国补',
    platform: 'PC',
    product_area: 'scene/strategies/nationalSubsidy',
    last_updated: '2024-12-05',
    keywords: ['国补','国家补贴','促销行'],
    cover_url: 'https://img30.360buyimg.com/...',
    html: 'pc-national-subsidy.html'
  },
  ...
];
```

这个文件供 `index.html` 读取，渲染 Case 卡片列表。

---

### Step 4.5：补缩略图（列表卡片用）

新增或更新 Case 后，跑一次缩略图生成脚本，把首张设计稿截图压成 600px JPEG q70 存到 `preview/thumbnails/{slug}.jpg`（列表卡片走本地缩略图，免去每次拉 4-18MB 原图）。增量，已存在则跳过：

```bash
cd <brain-frontend 根目录>
npm run thumbnails
```

脚本会同时更新 `preview/thumbnails/_thumb_index.js`（library.html 据此决定卡片走缩略图还是占位 SVG）。`screenshots: []` 为空的 Case 自动跳过、卡片回退占位 SVG。

---

### Step 5：打开浏览器

```bash
open public/design-kb/knowledge/preview/index.html
```

输出：
```
✅ 预览已更新

本次更新：2 个 Case 数据
跳过：7 个（已是最新）
文件位置：public/design-kb/knowledge/preview/index.html
```

---

### Step Init：写入静态模板（只执行一次）

`--init` 时写入以下文件，之后永久复用，不再修改：

**`public/design-kb/knowledge/preview/_template.html`**（包含完整 CSS + JS，从 `_cases.js` 和 `cases/*.js` 读取数据动态渲染）

模板功能：
- 首页：读取 `_cases.js`，渲染 Case 卡片网格，支持平台筛选和关键词搜索
- 详情页：读取对应的 `cases/[slug].js`，渲染完整的 9 章内容
- ⭐ 高风险状态行黄色高亮
- TODO 项橙色标注
- 截图点击放大（lightbox）
- 折叠/展开次要章节
- 「返回知识库」导航

**`public/design-kb/knowledge/preview/index.html`**（一行，加载模板）：
```html
<!DOCTYPE html><html><head><meta charset="UTF-8"><script src="_cases.js"></script></head><body><script>window.location.href='_template.html'</script></body></html>
```

实际上 `_template.html` 直接作为首页使用，`index.html` 重定向过去即可。

---

## 关键约束

1. **不生成 HTML/CSS/JS。** 所有样式和交互逻辑在 `_template.html` 里，AI 只生成 JSON 数据。
2. **只用 Bash 读文件。** 用 `head`、`grep`、`sed` 提取内容，不用 `Read` 工具读全文。
3. **`_template.html` 写入后不再修改。** 样式更新需要手动编辑或重新 `--init`。
4. **增量是默认行为。** 没有变化的 Case 不重新生成数据文件。
5. **`public/design-kb/knowledge/preview/` 加入 `.gitignore`。** 生成物不纳入版本管理。

---

## 版本历史

- **v1.0** (2026-05-21) 初版
- **v1.1** (2026-05-22) 增量模式 + 压缩 HTML 模板
- **v2.0** (2026-05-25) 重构：AI 只生成数据文件，静态模板永久复用，token 消耗减少 90%
