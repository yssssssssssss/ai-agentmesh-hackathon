---
name: knowledge-update
harness-version: 0
description: "知识库维护工具。扫描 public/design-kb/knowledge/ 目录下所有 reasoning.md 文件， 重建 INDEX.md 索引、检查 component-naming.md 完整性、自动追加\
  \ CHANGELOG、 汇总待补充项清单，并支持引导设计师逐条回填并写回原文件。 默认为增量模式，只处理上次更新后新增或修改的文件，节省 token。 调用示例：\n  /knowledge-update\n  /knowledge-update\
  \ --full\n  /knowledge-update --init\n  /knowledge-update --check-only\n  /knowledge-update --fill\n"
user-invocable: true
triggers:
- 更新知识库
- 更新 INDEX
- 知识库维护
allowed-tools:
- Bash
- Read
- Write
- Edit
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/huangliu-design/product-details/JD-ProductDetails-web/brain-frontend/public/design-kb/skills/knowledge-update/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
  short-description: 知识库维护工具。扫描 public/design-kb/knowledge/ 目录下所有 reasoning.md 文件， 重建 INDEX.md 索引、检查 component-naming.md…
disable-model-invocation: true
---

# /knowledge-update · 知识库索引维护

## 工作目录

执行本 skill 前，请先定位到仓库中的 `JD-ProductDetails-web/brain-frontend/` 目录，
所有路径均以此为根目录。

## 这个 Skill 做什么

维护知识库的健康状态，确保 `design-advisor` 能准确检索到内容：

- **增量模式（默认）**：只读取上次更新后新增或修改的文件，大幅减少 token 消耗
- **全量模式（--full）**：重建所有索引，用于索引异常或首次迁移
- 扫描 `*-reasoning.md` 文件，重建 `INDEX.md`
- 检查 `component-naming.md` 是否覆盖了所有出现过的组件名
- 自动追加本次变动到 `CHANGELOG.md`
- 汇总所有 `TODO: 待补充` 项，生成可读的 `TODO.md` 清单
- `--fill` 模式：逐条引导设计师补充 TODO 项，并自动写回原文件

## 调用方式

```
/knowledge-update              ← 增量扫描（默认），只处理新增或修改的文件
/knowledge-update --full       ← 全量扫描，重建所有索引（索引异常时使用）
/knowledge-update --init       ← 首次初始化，从零创建所有文件和目录结构
/knowledge-update --check-only ← 只检查，不写文件，输出健康报告
/knowledge-update --fill       ← 进入待补充回填模式，逐条引导设计师补充并写回
```

---

## 执行流程

### Step 0：判断运行模式（增量 vs 全量）

用 `Bash` 读取 `public/design-kb/knowledge/.last-update` 文件，获取上次运行的时间戳：

```bash
cat public/design-kb/knowledge/.last-update 2>/dev/null
```

- 文件存在且有时间戳 → **增量模式**：只处理比该时间戳更新的文件
- 文件不存在 → **首次运行**：自动降级为全量模式
- 传入 `--full` 参数 → **强制全量模式**

**增量模式下，用以下命令找出需要处理的文件：**

```bash
find public/design-kb/knowledge/ -name "*-reasoning.md" -newer public/design-kb/knowledge/.last-update
```

只对这些文件执行 Step 2 的读取操作。INDEX.md 中已有的其他 Case 条目保持不变，只追加或更新本次变动的部分。

**全量模式下**，扫描所有 `*-reasoning.md` 文件，完整重建 INDEX.md。

---

### Step 1：扫描知识库目录

用 `Bash(find *)` 扫描 `public/design-kb/knowledge/` 目录下所有 `*-reasoning.md` 文件，列出完整文件路径清单（用于统计总数）。

增量模式下仅读取 Step 0 筛选出的新文件，全量模式下读取所有文件。

若目录不存在：
- `--init` 模式：创建目录结构（见下方「知识库目录结构」）
- 其他模式：报错退出，提示路径

---

### Step 2：读取文件的 frontmatter 和 TODO 项

对**需要处理的文件**（增量模式下为新文件，全量模式下为所有文件），读取：

**frontmatter 字段：**
- `feature_name`
- `product_area`
- `platform`
- `keywords`
- `last_updated`
- `relay_source`（是否有设计稿来源）

**TODO 扫描：**
- 搜索文件中所有 `TODO: 待补充` 字符串
- 记录：所在文件路径、所在章节标题（`## 章节名`）、所在字段名、当前占位内容

检查必填字段是否完整，缺失的记录到健康报告。

---

### Step 3：更新 INDEX.md

**增量模式：**
- 读取现有 INDEX.md
- 新增：把本次新文件的条目追加到对应功能区分组下
- 更新：若文件已在 INDEX.md 中存在（同路径），用新数据替换该行
- 更新 `Case 总数` 和 `最后更新` 字段

**全量模式：**
按以下格式完整重建 `public/design-kb/knowledge/INDEX.md`：

```markdown
# 知识库索引

> 最后更新：[日期]
> Case 总数：[N]

## 商详 · 促销组件

| Case 文件 | 功能区 | 关键词 | 平台 | 最后更新 |
|---|---|---|---|---|
| [路径] | [功能区] | [关键词] | [PC/App/Both] | [日期] |

## 商详 · 以旧换新

| ... |

## 商详 · 价格楼层

| ... |

## 共用规则

| ... |
```

---

### Step 4：更新 component-naming.md

**增量模式：** 只扫描本次新文件的 `## 状态覆盖表` 和 `## 核心设计决策`，追加新出现的组件名。

**全量模式：** 扫描所有文件，完整对比并更新。

- 新出现的组件名：追加到命名表，标注 `⚠️ 别名待补充`
- 已有条目但 Case 引用列未更新：补充 Case 文件名

---

### Step 5：追加 CHANGELOG.md

每次运行（非 `--check-only`）后，在 `public/design-kb/knowledge/CHANGELOG.md` 末尾**追加**一条记录：

```markdown
## [日期] — [增量/全量]

**新增 / 更新 Case（[N] 个）**
- `[文件路径]`：[feature_name]（[product_area] · [platform]）

**INDEX.md 变动**
- 新增关键词：[关键词列表]
- 更新条目：[N] 条

**component-naming.md 变动**
- 新增组件：[组件名列表]

**待补充项（[N] 条）**
- `[文件路径]` § [章节]：[字段名]
```

若本次无任何变动：

```markdown
## [日期] — 无变动

增量扫描完成，无新增或修改的文件。
```

---

### Step 6：刷新 TODO.md

**增量模式：** 读取现有 TODO.md，合并本次新文件的 TODO 项，移除已补充的项，完整重写。

**全量模式：** 扫描所有文件，完整重写。

```markdown
# 待补充清单

> 最后更新：[日期]
> 待补充项总数：[N]
> 运行 `/knowledge-update --fill` 逐条补充

---

## [Case 名] · [文件路径]

| # | 章节 | 字段 | 说明 |
|---|---|---|---|
| 1 | § X. 章节名 | 字段名 | 说明 |
```

---

### Step 7：更新时间戳

每次运行（非 `--check-only`）完成后，写入当前时间戳：

```bash
date -u +"%Y-%m-%dT%H:%M:%SZ" > public/design-kb/knowledge/.last-update
```

`.last-update` 文件加入 `.gitignore`，不需要纳入版本管理（每人本地维护自己的时间戳）。

---

### Step 8：输出健康报告

```markdown
# 知识库健康报告 — [日期]

## 概览
- 运行模式：[增量 / 全量]
- 本次处理文件：[N] 个（增量）/ [N] 个（全量）
- Case 总数：[N]
- 待补充项：[N] 条

## ⚠️ 需要处理的问题

### 缺少必填字段
- [文件路径]：缺少 `keywords` 字段

### 组件命名表待补充别名
- [组件名]：别名列为空

### 可能过时的 Case
- [文件路径]：最后更新 > 180 天，建议 review

## ✅ 本次更新内容
- INDEX.md：新增 [N] 条，更新 [N] 条
- component-naming.md：新增 [N] 个组件条目
- CHANGELOG.md：已追加本次记录
- TODO.md：已刷新，当前待补充 [N] 项
```

---

## --fill 模式：逐条回填

`--fill` 模式只读取 TODO.md，不重新扫描所有文件，token 消耗极低。

**Step F1：读取 TODO.md**，列出所有待补充项。无则退出：
```
✅ 当前没有待补充项，知识库状态良好。
```

**Step F2：逐条展示并提问**

```
待补充项 1/3

需求：PC接入国补
文件：public/design-kb/knowledge/scene/strategies/nationalSubsidy/pc-national-subsidy-reasoning.md
章节：§ 6. 文案决策
字段：tooltip 文案
说明：国家补贴标签小 i hover 展示的具体文字

请输入补充内容（输入"跳过"进入下一条，输入"退出"结束）：
```

**Step F3：写回原文件**，用 `Edit` 工具替换对应的 `TODO: 待补充` 占位，输出确认。

**Step F4：回填完成后**，自动触发一次增量 `/knowledge-update` 刷新索引。

```
回填完成。
- 本次补充：[N] 条
- 跳过：[N] 条
- 知识库已同步更新
```

---

## 知识库目录结构（--init 时创建）

```
public/design-kb/knowledge/
│
├── .last-update          ← 增量时间戳，加入 .gitignore
├── INDEX.md              ← 自动维护，禁止手动编辑
├── component-naming.md   ← 自动维护 + 人工补充别名
├── CHANGELOG.md          ← 自动追加，禁止手动编辑
├── TODO.md               ← 自动重写，可手动查看
│
├── scene/
│   ├── strategies/
│   │   └── nationalSubsidy/    ← 国补促销案例
│   └── bizScene/
│       └── tradeInTab/         ← 以旧换新案例
│
└── shared/
    ├── priority-rules.md
    └── state-coverage-checklist.md
```

---

## 关键约束

1. **增量模式是默认行为。** 普通录入后跑 `/knowledge-update` 即可，不需要 `--full`。
2. **索引异常时用 `--full`。** Case 数量对不上、关键词丢失时，跑一次全量重建。
3. **`.last-update` 加入 `.gitignore`。** 每人本地维护自己的时间戳，不上传 GitHub。
4. **CHANGELOG 只追加，不覆盖。** 历史记录永久保留。
5. **TODO.md 每次完整重写。** 反映当前最新状态。
6. **`--check-only` 不写任何文件，不更新时间戳。**
7. **不删除任何 reasoning.md 文件。**

---

## 版本历史

- **v1.0** (2026-05-21) 初版
- **v1.1** (2026-05-21) 新增 CHANGELOG、TODO、--fill 回填模式
- **v1.2** (2026-05-22) 新增增量模式（默认），新增 --full 全量参数，新增 trade-in 目录
- **v1.3** (2026-05-31) 新增 Step 7：同步更新看板数据（已废弃，v1.4 移除）
- **v1.4** (2026-07-16) 移除 kanban.html 同步（kanban 已废弃）
