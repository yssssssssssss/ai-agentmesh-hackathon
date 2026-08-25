---
name: zero-id-to-md
description: 将 Relay/Zero 团队库组件录入为 AI 可理解、可检索、可实例化的组件知识；结合 relay-to-design-md 的深度抽取能力与 importKey/sourceNodeId 精准绑定能力。
allowed-tools:
- mcp__zero-design__get_design_metadata
- mcp__zero-design__get_design_context
- mcp__zero-design__get_screenshot
- mcp__zero-design__get_variables
- mcp__zero-design__use_design_script
- Bash
- Read
- Write
- Edit
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/plus-and-new-channel/_skills/zero-id-to-md/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
  short-description: 将 Relay/Zero 团队库组件录入为 AI 可理解、可检索、可实例化的组件知识；结合 relay-to-design-md 的深度抽取能力与 importKey/sourceNodeId 精准…
disable-model-invocation: true
---

# zero-id-to-md

> v0.5（2026-06-12）  
> 定位：`relay-to-design-md` 的知识抽取深度 + 本 skill 的组件绑定/调用精度。

## 一句话

这个 skill 把团队库组件变成两类资产：

1. **可理解资产**：AI 知道组件是什么、怎么用、有哪些变体、哪些节点可改、有哪些 token 和行为约束。
2. **可调用资产**：AI 知道如何通过 `importKey` 跨文件导入，或在无 importKey 时使用 `sourceNodeId fallback` 做当前文件验证。

## 关键判断

本 skill 面向 **已发布到团队组件库的 Relay/Zero 组件**。用户提供的 node 必须能回溯到已发布组件库中的 `COMPONENT` / `COMPONENT_SET`，或至少能在源文件中确认 `publishStatus=CURRENT`。

如果用户给的是普通画板、未发布组件、临时 Frame、页面草稿：

- 可以做结构诊断或生成 outline。
- 不得承诺跨文件 import。
- 不得写成 `key-ready`。
- 需要提醒用户：请先发布组件库，或切换到已发布组件库源文件/外部消费文件再录入。

`importKey` 是跨文件导入的实际凭证；`sourceComponentKey/componentKey` 只用于回溯源节点。  
因此注册表必须区分三种导入状态：

| importStatus | 含义 | 能否跨文件调用 |
|---|---|---|
| `key-ready` | 已获得可用于 `importComponent*ByKeyAsync` 的 importKey，并验证可导入 | 是 |
| `node-fallback` | 只有源文件 `nodeId` / 变体节点，可用于当前文件或源文件验证 | 否 |
| `blocked` | 既无 importKey，也无法稳定定位源组件 | 否 |

`componentUid`、`node.id`、`componentVersion`、`libraryKey`、TeamLibrary map 的 `componentKey` 都不能自动等同于可导入 importKey。  
只有两件事能证明跨文件可调用：

- 拿到 TeamLibrary map 条目的 `id`，且它能传给 `relay.importComponentByKeyAsync(id)` 或 `relay.importComponentSetByKeyAsync(id)`。
- 或在消费文件中实际 import 成功。

## 双环境绑定策略

组件录入优先支持两种工作环境：

| 环境 | 可获得信息 | 绑定策略 |
|---|---|---|
| 源文件 | `relay.fileKey` / 选中组件 `node.id` / `publishStatus` / 组件结构 | 生成完整知识；若已发布但无法 import，先记 `sourceNodeId` 与 `sourceComponentKeyCandidate`，标 `node-fallback` 或 `source-confirmed` 风险 |
| 外部消费文件 | `teamLibrary.getAvailableLibraryListAsync()` / `teamLibrary.getAvailableLibraryMapAsync()` | 先无参获取全量 map，再用 `allMap[libraryKey]` 取库条目；条目 `componentKey` 用于回溯源节点，条目 `id` 才是当前 Zero API 实测可导入的 `importKey` |

`key-ready` 必须同时满足：

1. 在外部消费文件的 TeamLibrary map 中找到目标组件条目。
2. 记录 `teamLibrary.importKey = item.id`。
3. 对组件集优先验证 `relay.importComponentSetByKeyAsync(importKey)`，对单组件验证 `relay.importComponentByKeyAsync(importKey)`。
4. import 调用不抛错还不够，必须返回非空节点，并且返回节点类型与目标类型匹配，才写 `importVerified=true`。

## 固定工作目录

skill 本体：

```text
jd-design-system-md-v16/product-architecture/plus-and-new-channel/_skills/zero-id-to-md/
```

录入产物默认写入当前业务域的 `components/`，不要新建跨域全局目录。  
例如榜单域写入：

```text
jd-design-system-md-v16/product-architecture/plus-and-new-channel/ranking/components/
├── COMPONENT_NODE_MAP.json
└── {component-slug}/
    ├── {component-slug}.outline.md
    ├── {component-slug}.knowledge.md
    ├── {component-slug}.registry.json
    └── {component-slug}.preview.png
```

如果无法从路径/用户上下文判断业务域，先询问用户落点；不要擅自创建 `component-library/` 这类新的大结构。

旧版 `component-ingest-outline.md` / `component-knowledge.md` / `registry-entry.json` 可读但不再优先生成。批量录入时必须使用 slug 命名文件，避免多个组件在搜索、打包、汇总时只看到一堆同名文件。

## 命名与分层规则

### artifact 命名

每个录入组件必须先确定稳定 `slug`：

- 优先使用组件英文名 kebab-case，例如 `Reasons` → `reasons`，`Ranking Card` → `ranking-card`。
- 若同名组件存在，追加业务域或层级，例如 `ranking-card-product`、`ranking-card-shop`。
- 文件名必须带 slug：
  - `{slug}.outline.md`
  - `{slug}.knowledge.md`
  - `{slug}.registry.json`
  - `{slug}.preview.png`
- registry 的 `knowledge.*` 路径必须指向 slug 命名文件。
- 如需兼容旧产物，可额外保留旧名副本，但不得只生成旧名。

### 组件层级

录入时给每个节点标 `level`：

| level | 含义 | 示例 |
|---|---|---|
| `component-base` | 单一职责基础元件 | 价格、标签、图标理由、排名标 |
| `shared-component` | 可跨多个业务组件复用的小组件 | Reasons、Promotion tag |
| `component-business` | 由多个子组件组成的业务组件 | ranking card、product card |
| `floor` | 承载多个业务组件的楼层 | marketing floor、ranking floor |
| `page` | 多楼层页面或频道页 | channel page |

父组件必须记录 `dependencies` / `slots` / `semanticSlots` / `compositionRules`；子组件只有具备独立复用、独立变体或独立 importKey 时才单独录入。

## Stage 0 · 业务语义预检

当目标节点是 `component-business` / `floor` / `page`，或一个父组件包含多个子组件、标签、价格、理由、行为、服务等模块时，先做业务语义预检，再进入 Stage 1。

### 0.1 给用户的引导提示

在正式录入前，主动提示用户补充关键子模块的业务定义。可以用这段话：

```text
这个父组件里，哪些子模块有明确业务含义？
比如：
- Reasons = 成榜理由，不是促销标签
- Behavior = 用户行为/在榜时长，不是榜单名次
- Promotion tag = 价促/活动信息
- service tag = 服务承诺

你可以只补 1-3 句；如果不补，我会继续抽取，但会把子组件语义标为“节点命名推断，待确认”。
```

不要阻塞用户：如果用户未补充，也可以继续执行，但必须在 outline / knowledge / registry 中写风险。

### 0.2 semanticSlots 必填

复杂父组件必须产出 `semanticSlots`。每个关键子组件/槽位至少包含：

```json
{
  "semantic_id": "product.reason",
  "component": "Reasons",
  "semantic_role": "成榜理由",
  "allowed_content": ["好评率", "购买人数", "近7日销量"],
  "forbidden_content": ["价格促销", "服务承诺", "榜单名次"],
  "source": "designer-provided | node-name | structure-inferred | unknown",
  "confidence": "high | medium | low"
}
```

规则：

- `semantic_role` 不等于节点名翻译，必须写业务职责。
- `allowed_content` 写这个槽位可以承载什么。
- `forbidden_content` 写这个槽位绝对不能承载什么。
- 用户明确给出的业务定义，`source=designer-provided`。
- 仅靠节点名/结构推断时，`confidence` 不得写 high，并必须在 `risks` 中标注“子组件语义来自推断，待确认”。

### 0.3 语义路由原则

后续调用组件时，先按 `semanticSlots` 路由内容，再改节点：

- 榜单名次 → `rank.mark`
- 成榜理由 / 好评 / 热卖 / 销量 → `Reasons` 或对应 reason slot
- 用户行为 / 在榜时长 / 蝉联多久 → `Behavior`
- 价格、降价、补贴、活动周期 → `price description` / `Promotion tag`
- 服务承诺、价保、售后 → `service tag`

如果用户需求无法路由到明确槽位，不要硬塞到看起来空的标签里；标为待确认或询问用户。

## 必读参考

执行前按任务读取：

- `references/extraction-schema.md`：深抽取中间数据结构。
- `references/preflight-gate.md`：稿件/组件可录入检查。
- `references/outline-template.md`：outline gate 输出模板。
- `references/knowledge-template.md`：正式组件知识模板。
- `references/registry-schema.md`：注册表结构。
- `references/variant-detection.md`：变体扫描规则。

## 5 阶段 pipeline

```text
Stage 0 业务语义预检
  复杂父组件 → 引导用户补业务定义 → semanticSlots / allowed_content / forbidden_content

Stage 1 深度抽取
  Relay 节点 → rootInfo / identity / variants / anatomy / editableNodes / visual / tokens / risks

Stage 2 Outline Gate
  先产 {slug}.outline.md，设计师确认理解是否正确

Stage 3 正式知识包
  写 {slug}.knowledge.md + {slug}.registry.json + COMPONENT_NODE_MAP.json

Stage 4 调用与反哺
  用户自然语言 → 查注册表 → 调组件 → 微调 → 截图验证 → 反哺知识缺口
```

默认只做 Stage 0-2。  
只有用户明确说“确认写入正式知识包 / confirm outline / 继续正式录入”，才执行 Stage 3。  
Stage 4 是日常消费模式。

## 触发方式

### 录入模式

```text
/zero-id-to-md <relay_url>
/zero-id-to-md 录入这个组件 <relay_url>
/zero-id-to-md <relay_url> --confirm-outline
```

如果 URL 缺 `node_id`：

- 可以先扫当前 page 候选组件。
- 但正式录入必须定位到明确的 `COMPONENT` / `COMPONENT_SET` / 可回溯 main component 的 `INSTANCE`。
- 如果目标不是已发布组件库组件，只能诊断或写 outline，不能写 `key-ready` 正式注册表。

### 调用模式

```text
帮我画一个 Ranking mark，大号，第3名
调一个 Promotion tag，文案是官方立减
用 ranking card 生成一张排行榜商卡
```

## Stage 1 · 深度抽取

参考 `relay-to-design-md` 的抽取思路，但目标不是生成普通 `design.md`，而是生成“组件可调用知识”。

### 1.1 定位节点

必须确认：

- `file_id`
- `page_id`
- `node_id`
- 节点类型
- 父 page
- 是否属于组件库源文件

节点类型处理：

| 类型 | 处理 |
|---|---|
| `COMPONENT_SET` | 作为组件集录入，children 作为变体 |
| `COMPONENT` | 作为单组件录入 |
| `INSTANCE` | 回溯 `mainComponent`，不能直接把实例当源组件 |
| `FRAME` / `GROUP` | 只可作为容器，继续定位内部组件 |

### 1.2 抽 identity

使用 `use_design_script` 读取：

- `id`
- `name`
- `type`
- `key`
- `remote`
- `publishStatus`
- `componentUid`
- `libraryKey`
- `libraryName`
- `sourceComponentKey`（TeamLibrary map 条目的 `componentKey`，通常等于源组件 node id）
- `importKey`（TeamLibrary map 条目的 `id`，实际传给 import API）
- `importMethod`
- `componentVersion`
- `componentBinding`
- `componentPropertyDefinitions`
- `componentProperties`

将 import 状态写入：

```text
key-ready / node-fallback / blocked
```

规则：

- 在源文件内，`node.id` 只作为 `sourceNodeId/sourceComponentKeyCandidate`，即使 `publishStatus=CURRENT` 也不直接标 `key-ready`。
- 在外部消费文件内，用 TeamLibrary map 反查：`const allMap = await relay.teamLibrary.getAvailableLibraryMapAsync()`，再取 `allMap[libraryKey]`。
- `item.componentKey` 用于确认源节点，`item.id` 写入 `importKey`。
- `importKey` 非空但未验证 import：先标 `node-fallback`，风险写“importKey 未验证”。
- `importKey` 非空且 import 返回非空匹配节点：标 `key-ready`。
- `importKey` 为空但 `node_id` 可定位：标 `node-fallback`。
- 组件不可定位：标 `blocked`。

### 1.3 抽 variants

按 `references/variant-detection.md`：

1. 优先读取 `componentPropertyDefinitions` 和 `variantProperties`。
2. 再解析节点命名，如 `size=big,ranking=3`。
3. 再结构启发式推断。

输出：

- `variants.dimensions`
- `variants.entries`
- `variantCoverage`
- `missingCombinations`
- `defaultVariant`

### 1.3.1 嵌套子组件扫描（必须执行）

Stage 1.3 完成顶层变体扫描后，**必须**对每个变体的内部结构做一层递归扫描，找出嵌套的 `INSTANCE` 节点，并检查它们各自归属的 `COMPONENT_SET`。

**触发条件**：只要抽取的是 `component-business` / `floor` 级别的组件，或任何变体的 children 数量 ≥ 2，就必须执行本步骤。

**执行方法**（通过 `use_design_script`）：

```js
// 对每个顶层变体实例递归收集嵌套 INSTANCE，
// 检查其 mainComponent.parent 是否为 COMPONENT_SET
function findNestedInstances(node, depth) {
  if (depth > 4) return [];
  const results = [];
  if (node.type === 'INSTANCE' && depth > 0) {
    const mc = node.mainComponent;
    const parent = mc?.parent;
    if (parent?.type === 'COMPONENT_SET') {
      results.push({
        path: node.name,
        id: node.id,
        componentProperties: node.componentProperties,
        componentSetName: parent.name,
        componentSetId: parent.id,
        variantOptions: parent.componentPropertyDefinitions
      });
    }
  }
  for (const child of (node.children ?? [])) {
    results.push(...findNestedInstances(child, depth + 1));
  }
  return results;
}
```

**对每个发现的嵌套 COMPONENT_SET，必须判断**：

| 情况 | 处理 |
|---|---|
| 已在 TeamLibrary map 中有 importKey | 单独录入为独立组件，或在父组件 registry 中记录 `importStatus: key-ready` |
| 不在 TeamLibrary map（未发布） | 在父组件 registry 的对应变体 entry 下记录 `nestedComponents[]`，写明 `importStatus: not-published`、`accessPath`、`switchMethod`、所有变体 entries |
| 与父组件同库同文件，但作为独立组件 | 评估是否需要单独录入；至少在父组件 registry 中 cross-reference |

**`nestedComponents` 记录格式**（写在父组件 `variants.entries[i]` 内）：

```json
{
  "slug": "activity-benefit-point",
  "name_zh": ".活动栏目利益点",
  "componentSetId": "6:403",
  "importStatus": "not-published",
  "note": "未单独发布到团队库，无 importKey",
  "accessPath": "instance.children[0].children[0]",
  "switchMethod": "nestedInst.setProperties({'栏目类型': '<variantValue>'})",
  "dimensions": ["栏目类型"],
  "defaultProps": { "栏目类型": "爆品活动" },
  "entries": [
    { "name": "栏目类型=爆品活动", "props": { "栏目类型": "爆品活动" }, "desc": "爆款商品活动" },
    { "name": "栏目类型=签到互动", "props": { "栏目类型": "签到互动" }, "desc": "签到打卡互动" }
  ]
}
```

**不允许**：
- 扫描到嵌套子组件但不记录。
- 只记录默认显示的那个变体，忽略其他变体选项。
- 认为「父组件已发布」就代表「嵌套子组件也能跨文件切换」——两者独立。

**Outline Gate 中必须汇报**：
- 发现了哪些嵌套子组件（名称 / componentSetId / 变体数量）。
- 哪些已发布（可独立 import），哪些未发布（只能通过父组件实例路径访问）。
- 设计师是否需要补充语义描述。

### 1.4 抽 anatomy

抽组件结构树，不只列节点名，要识别语义：

- 容器层级
- 子组件/实例引用
- 文本节点
- 图片节点
- 状态节点
- 装饰节点
- 可见性差异

输出时给关键节点分配 `semantic_id`，例如：

```text
ranking.value
title.text
tag.label
button.primary.text
```

复杂父组件还必须把关键区域写入 `semanticSlots`，并继承 Stage 0 的 `allowed_content` / `forbidden_content`。不能只写“标签”“文案”这类泛化角色。

### 1.5 抽 editableNodes

这是本 skill 的核心增强。  
不要只依赖 `textNodes[0]` 这种顺序索引。

每个可编辑节点至少记录：

- `semantic_id`
- `node_id`
- `node_path`
- `type`
- `default_value`
- `editable`
- `edit_rule`
- `fallback_match`
- `semantic_role`
- `allowed_content`
- `forbidden_content`

可编辑类型：

- 文案
- 布尔显隐
- 变体属性
- 图片占位
- 排名/数字
- 标签类型

### 1.6 抽 visual / token

参考 `relay-to-design-md` 的视觉抽取：

- fills
- textStyles
- radii
- spacing / autoLayout
- strokes
- shadows / effects
- imageHash
- instances

再做 token reverse lookup：

- 能映射 token：写 token 名。
- 不能映射：写原始值并标 `token-miss`。
- 不在本 skill 内发明新 token。

### 1.7 抽 behavior

来源优先级：

1. 组件已有 design.md bundle。
2. 组件/变体命名。
3. component properties。
4. anatomy 和可见性关系。
5. 设计师补充。

推断内容必须标 `⚠️ 待确认`。

### 1.8 预检

按 `references/preflight-gate.md` 对抽取结果打标：

- 节点定位
- importKey / sourceComponentKey 状态
- 命名可信度
- 变体完整度
- 可编辑节点识别
- token 映射率
- 截图可得性

预检结果写入 outline。

## Stage 2 · Outline Gate

默认输出：

```text
{domain}/components/{slug}/{slug}.outline.md
```

如果目标目录不存在，可以创建。

outline 必须回答：

- 我理解这个组件是什么。
- 如果是复杂父组件：哪些关键子组件的业务语义已确认，哪些仍是推断。
- 它有哪些变体。
- 哪些自然语言能映射到哪些变体。
- 哪些内容应该路由到哪些 semantic slot，哪些内容禁止写入某些 slot。
- 哪些文案/状态/属性可以微调。
- 哪些 token 成功识别。
- 哪些字段是推断的。
- 当前 importStatus 是什么。
- 如果是 `node-fallback`，明确说明不能证明跨文件导入。

设计师确认 outline 后，才能写正式知识包。

## Stage 3 · 正式知识包

执行条件：

- 用户明确确认 outline。
- 或用户显式传 `--confirm-outline`。

输出：

```text
{slug}.knowledge.md
{slug}.registry.json
COMPONENT_NODE_MAP.json
{slug}.preview.png
```

实际文件名必须使用 slug：

```text
{slug}.knowledge.md
{slug}.registry.json
{slug}.preview.png
```

### 3.1 component-knowledge.md

按 `references/knowledge-template.md`，写完整 AI 认知知识。

必须包含：

- 一句话定义
- 使用边界
- anatomy
- semanticSlots / 语义槽位表
- 变体矩阵
- 自然语言映射
- 状态模型
- 交互逻辑
- editableNodes
- 文案规则
- token 表
- 组合关系
- Do / Don't
- 待确认项

### 3.2 registry-entry.json

按 `references/registry-schema.md` 写严格 JSON。

重点字段：

- `importStatus`
- `teamLibrary`
- `relay`
- `variants`
- `semanticSlots`
- `editableNodes`
- `knowledge`
- `traceability`

### 3.3 COMPONENT_NODE_MAP.json

合并规则：

- 不存在则创建 `{}`。
- 已存在同 slug，不覆盖，先写 `.NEW.json`。
- 新 slug 合并到顶层。
- 合并后必须验证 JSON 可解析。

## Stage 4 · 调用与反哺

当用户说自然语言生成组件：

1. 查 `COMPONENT_NODE_MAP.json`。
2. 读取对应 `{slug}.knowledge.md`。
3. 识别需求中的组件、变体、文案、状态。
4. 先用 `semanticSlots.allowed_content/forbidden_content` 做语义路由，确认每段内容该进入哪个槽位；无法路由时标待确认，不要硬塞。
5. 根据 `importStatus` 决定策略：
   - `key-ready`：组件集优先用 `importComponentSetByKeyAsync(teamLibrary.importKey)`，单组件用 `importComponentByKeyAsync(teamLibrary.importKey)`；验证时必须确认返回节点非空。
   - `node-fallback`：只在源文件/当前文件内用 nodeId 验证，不承诺跨文件。
   - `blocked`：停止并说明原因。
6. 实例化组件。
7. 根据 `editableNodes` 微调。
8. 截图验证。
9. 发现知识缺口，写入“反哺建议”，不要静默改正式知识，除非用户要求。

## Guardrails

- 不从零绘制已录入组件。
- 不把 `node.id` / `componentUid` / TeamLibrary map 的 `componentKey` 当成可导入 `importKey`；当前 Zero API 实测可导入的是 map 条目的 `id`。
- 不承诺 `node-fallback` 可跨文件导入。
- 不跳过 outline gate。
- 不跳过复杂父组件的业务语义预检。
- 不跳过截图验证。
- 不用纯文本顺序索引替代 editableNodes。
- 不覆盖已有知识包。
- 不编造 token / 行为 / 交互。
- 不把内容写入 `forbidden_content` 已禁止的槽位；宁可待确认，也不要误路由。
- 不写密钥、token、内部凭证。

## 汇报格式

### Stage 1-2 完成

汇报：

- 组件 slug / 中文名。
- importStatus。
- 识别变体数量。
- semanticSlots 数量与低置信度槽位。
- editableNodes 数量。
- token-miss 数量。
- outline 路径。
- 需要设计师确认的事项。

### Stage 3 完成

汇报：

- 正式知识文件路径。
- registry 路径。
- 是否更新全局 COMPONENT_NODE_MAP。
- importStatus。
- 可用于测试的自然语言样例。

### Stage 4 完成

汇报：

- 调用组件。
- 匹配变体。
- 微调字段。
- 截图验证结果。
- 是否发现知识缺口。
