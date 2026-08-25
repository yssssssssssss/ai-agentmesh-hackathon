---
name: relay-to-design-md
harness-version: 0
description: 设计师给个 Relay URL,skill 自动产出 design.md + 主动分文件夹 + 校验 + hand-off brief。profile-aware 支持多团队,默认 JD V16。
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
  source: 2C-DesignWiki/.agents/skills/relay-to-design-md/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
  short-description: 设计师给个 Relay URL,skill 自动产出 design.md + 主动分文件夹 + 校验 + hand-off brief。profile-aware 支持多团队,默认 JD V16。
disable-model-invocation: true
---

# /relay-to-design-md · Relay → design.md 标准化录入流程

> **v1.0 标准化版**(2026-05-27)— 4 阶段 pipeline + profile 系统。新人看 [ADOPTION.md](./ADOPTION.md) 4 步上手,二次开发看本文件,加新团队 profile 看 [CONTRIBUTING.md](./CONTRIBUTING.md)。

## 4 阶段 pipeline(标准化视角)

11 step 详细流程归到 4 个 stage,职责清晰:

```
Stage 1  内容抽取(Step 1-5.5)
  ├─ Step 1   Parse URL
  ├─ Step 2   加载 Relay 节点 + 元数据
  ├─ Step 3   自动推断 level / bg / slug(profile-aware)
  ├─ Step 4   抽视觉(fills / imageHash / autoLayout)
  ├─ Step 4.5 preflight gate(nodeCount > 1200 阻断 → 分块)
  ├─ Step 5   Token 反查(profile 提供 catalog)
  └─ Step 5.5 生成 outline → 设计师 review

Stage 2  文件组织(Step 6-8.5,主动)
  ├─ Step 6   导出 preview.png
  ├─ Step 7   决定输出路径(profile-aware,见 profiles/<name>/path-rules.md)
  ├─ Step 8   套模板写 design.md(+ bundle 多文件)
  └─ Step 8.5 生成 / 更新 _assets-cdn.md(若有切图)

Stage 3  校验(Step 9 + bin/validate.sh)
  ├─ Step 9   更新 INDEX.md
  └─         frontmatter / 受控词表 / 路径 / 跨文件引用

Stage 4  Hand-off(Step 10-11)
  ├─ Step 10   反向引用 backlinks 查询
  ├─ Step 10.5 回写 Relay sharedPluginData(双向追溯)
  └─ Step 11   终端输出 hand-off brief 给设计师
```

每个 Step 在下面「执行流程」段有完整 spec。**11 step 是实现细节,4 stage 是用户视角**。

> 📐 **本 skill 是「design.md 录入标准管线」的 ① 录入段**。全链路权威流程(录入→校验→发布→上站)+ 录入 checklist 见 [`../../../.claude/shared/references/design-md-pipeline-sop.md`](../../../.claude/shared/references/design-md-pipeline-sop.md)。新发现的坑要编译回 SOP + 本 skill 执行件,不只改单个产物。

## 这个 skill 做什么

设计师传一个 Relay URL,默认先输出一份**结构化、token 化、可 review** 的 `design-outline.md`,待设计师确认后再生成正式 `design.md` + 主动组织文件夹 + 校验 + hand-off brief:

- 自动从 Relay 抽取节点视觉数据(fills / typography / radius / spacing / materials / instances / children)
- 自动反查 token(profile 提供 catalog)
- 自动推断 `level` / `bg` / `slug` / `name_zh` 字段(profile 提供受控词表)
- 默认先输出章节/状态/组合/缺失项大纲,帮助设计师确认边界
- 设计师确认后:**主动决定文件夹路径**(profile path-rules) + 写文件 + 维护 INDEX.md 双向追溯 + Relay sharedPluginData(v0.3+)
- 自动 flag 视觉问题:token-miss / 半步间距 / 子组件未录入 / 稿件 bug(共占位 imageHash / 命名错位)
- **Hand-off brief**:列「自动完成 X 项 / 设计师待补 Y 处 TODO / 稿件 bug Z 项 / 下一步建议」

## Profile 系统(v1.0)

skill 跑同一份 Relay 给不同团队会出不同的 design.md —— 因为 token / frontmatter / 路径规则 / 受控词表都不同。这些通过 **profile** 切换:

| Profile | 用途 |
|---|---|
| [`profiles/jd-v16/`](./profiles/jd-v16/) | JD V16 默认(无 `SKILL_PROFILE` 时走这个)|
| [`profiles/jd-v15/`](./profiles/jd-v15/) | JD V15(已冻结,仅 review)|
| [`profiles/generic/`](./profiles/generic/) | 外部团队 fork 起点 |

```bash
# 默认(jd-v16)
/relay-to-design-md <relay_url>

# 切换 profile
SKILL_PROFILE=generic /relay-to-design-md <relay_url>
SKILL_PROFILE=my-team /relay-to-design-md <relay_url>
```

skill 核心(本 SKILL.md / `bin/*.sh` / `references/*.md` / `templates/*`)是**跨 profile 通用**的;profile 只控制 token / frontmatter / 词表 / 路径。**改 profile 不需要改 skill;改 skill 不要 hardcode profile**。

## 关联文档

| 文档 | 给谁看 | 内容 |
|---|---|---|
| [README.md](./README.md) | 所有人 | 5 分钟概览 + 4 阶段 pipeline 视图 + 文档导航 |
| [ADOPTION.md](./ADOPTION.md) | 第 1 次用的设计师 | 4 步上手清单(checklist + Q&A 入口)|
| [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) | 遇到问题的用户 | 12 个 Q&A 覆盖常见错(推断错 / token unmapped / 冲突 / 等)|
| [CONTRIBUTING.md](./CONTRIBUTING.md) | 想加 profile / 改 skill 的人 | Part 1-5(加 profile / 改 jd-v16 / 改核心 / 贡献 upstream / 测试)|
| [profiles/<name>/README.md](./profiles/) | profile 维护者 | 该 profile 的 token / 词表 / 路径规则 |
| [INDEX.md](./INDEX.md) | 反查 Relay ↔ wiki | 双向追溯索引(自动维护) |

## 调用方式

```
/relay-to-design-md <relay_url>
/relay-to-design-md <relay_url> --confirm-outline
```

例：
```
/relay-to-design-md https://relay.jd.com/file/design?id=2029484645871009793&page_id=47%3A1&node_id=542%3A6495
/relay-to-design-md https://relay.jd.com/file/design?id=2029484645871009793&page_id=47%3A1&node_id=542%3A6495 --confirm-outline
```

默认只接受 1 个参数（URL）并进入 outline 模式。`--confirm-outline` 表示"设计师已确认大纲，可以写正式文档"。**不要**问设计师额外问题 —— 全部字段自动推断。

### 两阶段规则（v0.6 新加）

- **Phase 1 / 默认**：写 `design-outline.md`，展示结构范围、状态矩阵、章节拆分、已识别 token、待确认项、自动发现的风险
- **Phase 2 / `--confirm-outline`**：在设计师确认 outline 后，再写正式 `design.md` 或 page-doc bundle，并更新 traceability

> 目标：把"当前设计稿里明确存在的信息"和"仍待设计师确认的信息"分开展示，避免一上来就把不确定内容写进正式 design.md。

## v1.2 标准：所有组件统一 4 md + CHANGELOG bundle（覆盖以下旧分流）

> **2026-06-01 定调（设计组）**：取消「单份 design.md vs page-doc bundle」的分流。**所有组件、不论大小，统一输出 bundle**，文件集固定为：
>
> ```
> {slug}/
> ├── design.md       # 完整主文档：定义 / 边界 / 结构总览 / 形态总览 / 设计原则 / 典型场景 / 关联（不是薄 index）
> ├── spec.md         # 视觉与结构规格：token（浅/暗双列）/ 容器尺寸 / 间距 / 图标资产规则
> ├── variants.md     # 形态与变体：各形态详规 / 状态 / 内容类型 / 溢出降级
> ├── behaviors.md    # 行为规范：交互 / 点击区 / 跳转 / 优先级 / 降级 / Donts
> ├── CHANGELOG.md    # 变更记录（append-only，每个 PR 一条，最新在上）
> ├── _assets-cdn.md  # （有切图 / 图标 / 字体时）资产清单，下划线辅助文件
> └── assets/         # 导出的 SVG 图标 / 字体子集
> ```
>
> 变更点（相对旧文档）：
> - **不再产单份 `design.md`**（`templates/component.md` 已弃用，仅留读存量）；`pageDocMode` 不再决定「单份 vs bundle」，只用于决定章节切分抽取策略。
> - **`design.md` 是完整主文档**，不是薄 index——一句话定义 / 边界 / 结构总览 / 形态总览 / 设计原则 / 典型场景都在它里面，细规再下钻到 spec/variants/behaviors。
> - **去掉 `ai-schema.yaml`**（移出默认 bundle，`templates/page-doc/ai-schema.yaml` 标弃用，需要机器可读 schema 的组件才可选生成）。
> - `spec-page.html` 由 `design-md-to-spec-page` 生成，不是本 skill 产物。
> - `relay_source` 仍单点存储于 `design.md`，子文件只留 `bundle_part_of` 反向指针（v0.5.1 约定不变）。
>
> **下方 v0.1～v0.6 关于「单份 / 6 文件 / 7 文件 / 封板」的历史描述均被本节覆盖**，保留仅作演进记录。Step 7 / Step 8 以本节为准。

## v0.1 范围（被 v0.4 / v0.5 扩展；文件分流被 v1.2 覆盖）

- ✅ L1 通用组件（component-base）
- ⏳ L2/L3/L4（component-business / page / flow）→ v0.6+
- ✅ 单一 design.md（普通组件） + **multi-md bundle**（page-doc，v0.5；v0.5.1 起 6 文件；v0.6 试点 7 文件含 `implementation.md`）
- ✅ **page-doc 大节点**（高 > 5000px 或 ≥3 个章节 FRAME）→ **v0.4 单 md 内章节切分** → **v0.5 拆 4 文件 bundle** → **v0.5.1 拆 6 文件**（+ `ai-schema.yaml` + `CHANGELOG.md`，`relay_source` 单点存储）→ **v0.6 试点 7 文件**(+ `implementation.md`,见下)

> **v0.5.1 曾标"终态封板",v0.6 issue #60 Gap 3 破例新增 `implementation.md`**:R3 走查暴露 AI agent 按 spec.md 的几何结果手算 x/y 反复错位(label 偏移 12 DP),决定加一份"Auto Layout 接管说明"——描述布局引擎该怎么配,而非布局算完长什么样。先在 tabbar 试点(v0.1 文件版本),体例是否升为全 bundle 标配待 design system 组确认。
>
> 加完 v0.6 之后封板原则**未变**:**先开 issue 讨论"能否合到现有文件之一"再拆**,不允许 skill 直接新建第 8 个 bundle 文件。
>
> **辅助文件不计入封板**:下划线前缀文件(如 v0.5.2 的 `_assets-cdn.md` 切图清单)是 infra / manifest 性质,不是给设计师逐行 review 的正文文档,不受封板约束。

如果检测到 level ≠ component-base，**仍然写文件**，但 frontmatter `auto_detected.level` 标 ⚠️，并在终端输出"非 L1 节点，结果可能不准，请 review"。

**page-doc 模式**：
- v0.4：抽取脚本自动判定（`pageDocMode`），输出 `chapters[]` 元数据 + 每条 text/instance/layout 的 `chapter` 归属。模板渲染时在 `## 变体` 后追加 `## 设计规范细节(按章节)` 段
- **v0.5**：直接走 [templates/page-doc/](./templates/page-doc/) 4 模板 bundle，把 page-doc 内容拆成 design.md (index) + spec.md + variants.md + behaviors.md。design.md frontmatter 加 `bundle: page-doc` 标识 + `bundle_files: [...]` 清单

---

## 执行流程（严格按步骤跑）

> 默认先执行 Outline Gate。只有显式传入 `--confirm-outline`，才继续执行正式写入和双向追溯。
>
> Step 4.5 另有一道**稿件预检门**：预检整体结论 `⛔ 阻断` 时，即使传了 `--confirm-outline` 也不写入，要求设计师修稿后重跑。

### Step 1: Parse URL

从 URL 提取 3 个 id：

```
https://relay.jd.com/file/design?id={file_id}&page_id={page_id}&node_id={node_id}
```

注意：page_id / node_id 在 URL 里可能是 URL-encoded（`%3A` = `:`），需要 decode。

> 如果 URL 缺 `node_id`，**报错退出**："必须提供完整的 node_id，否则无法定位设计节点。"

### Step 2: 加载 Relay 节点 + 推断元数据

执行一次脚本（调 `use_design_script`），同时获取：

1. 节点本身：name / type / width / height
2. 父 page 名（用于 level 推断）
3. 是否在 V16 master 文件（用于 bg 推断）

```javascript
const node = await relay.getNodeByIdAsync('NODE_ID')
if (!node) return { error: 'node not found' }

// 找所属 page
let page = node
while (page && page.type !== 'PAGE') page = page.parent
if (page && page.loadAsync) await page.loadAsync()

return {
  node: {
    id: node.id, name: node.name, type: node.type,
    w: Math.round(node.width), h: Math.round(node.height),
  },
  page: { id: page.id, name: page.name },
  file_id: relay.fileKey,
}
```

### Step 3: 自动推断字段

按 [references/auto-detect-rules.md](./references/auto-detect-rules.md) 推断：
- `level` ← 看 page name 模式
- `bg` ← 看 file_id 查 [profiles/jd-v16/bg-mapping.json](./profiles/jd-v16/bg-mapping.json)
- `slug` ← 从节点名或 page 名提取英文，kebab-case
- `name_zh` ← 节点名去 emoji + 英文

记录"是否走兜底"，用于 frontmatter `auto_detected` 字段。

### Step 4: 抽取视觉数据

执行一个**完整提取脚本**（一次调用拿全部），见 [references/node-type-mapping.md](./references/node-type-mapping.md) 第 2 节"统一抽取脚本"。返回结构：

```typescript
{
  rootInfo: RootInfo,        // id/name/type/page_name/w/h/description/pageDocMode/nodeCount
  fileKey: string,
  uniqueFills: string[],     // ["#FFFFFF", "#000000@20%", ...]
  textStyles: TextStyle[],   // [{chars, fontSize, family, style, bucket, chapter}]
  uniqueRadii: number[],
  instances: Instance[],     // 子组件 / 材质 INSTANCE 引用
  layouts: Layout[],         // autoLayout padding / spacing
  variants: Variant[],       // COMPONENT_SET children（{id, name}）
  variantProps: object|null, // INSTANCE/COMPONENT 的 VARIANT 属性
  chapters: Chapter[]|null,  // 仅 page-doc 模式
  imageNodes: ImageNode[],   // v0.5.2: 带 IMAGE fill 的切图节点
}
```

> 字段名 / 结构**以 [node-type-mapping.md](./references/node-type-mapping.md) 第 2 节脚本的实际 `return` 为准** —— 该文件是唯一契约，本块仅速览。

### Step 4.5: 稿件预检门（v0.5.7）

Step 4 抽完数据后、进 Step 5 之前，按 [references/preflight-gate.md](./references/preflight-gate.md) 跑一次**稿件就绪度预检**：

- 用 Step 4 已抽数据（`rootInfo` / `textStyles` / `chapters` / `instances` / `layouts`）+ Step 2 节点信息，对 6 个维度做**机械规则判断**：节点规模 / 命名可信度 / 命名漂移率 / 标注完整度 / 截图可得性 / 结构清晰度
- 每个维度结论 `✅ 通过` / `⚠️ 待补充` / `⛔ 阻断`，聚合出整体结论
- 评估写进 outline 的 `## 稿件预检` 段（`{{section_preflight}}`），`⚠️` 项并入「待设计师确认」

**Phase 2 闸门**：整体结论 `⛔ 阻断`（仅节点规模严重超限会触发）时，即使传了 `--confirm-outline` 也**不写 design.md** —— 终端输出严重缺口，要求设计师修稿 / 分块后重跑。`✅` / `⚠️` 正常继续。

> 预检只做**规则判断**，不评价设计质量;`⛔` 只留给规模超限这种「转换必然产出垃圾」的致命情况，命名 / 标注 / 截图 / 结构等模糊维度一律 `⚠️` 不阻断 —— 避免误报把设计师挡在门外。

> **为什么要这道门**:skill 此前抽完数据直接转换，把「稿件没就绪」的代价后置到 design.md 里靠人反复 review（issue #56）。预检在动手前先把缺口列清楚。

### Step 4.6: 深浅双态展开（v0.5.4）

如果 Step 4 抽取发现组件含 **浅色 / 暗色双态**（判定信号，命中任一即触发）：
- 同一章节下有并列的浅 + 暗两份 frame（暗份 name 含「暗色」「暗黑」「dark」「dark mode」后缀）；
- `uniqueFills` 同时出现明显的浅底（`#FFFFFF` / 高明度）与暗底（`#14171A` / `#1F2226` / 低明度）；
- variantProps / componentProperties 出现「模式=日间/暗黑」「mode=light/dark」维度。

则**对暗色 frame 也跑一次完整 `get_design_context` + 逐节点 fill 抽取**，并：

1. **暗色 token 独立成列**：design.md / spec.md 的 token 表用「浅 / 暗」双列（或双行），暗色值单独写，**不写「暗色同浅色」或留空靠推断**。
2. **变体数对齐校验**：浅色有 N 个状态/变体 → 暗色也必须抽满 N 个，逐一比对。缺的记 `⚠️ wiki gap: 暗色缺 {变体名}`，不静默用浅色顶替。
3. **中性色尤其警惕**：背景 / 文本 / 边框 / 分隔线 / 占位 的中性灰在暗色下几乎一定换值（不是简单反色）；品牌色（红 / 主操作）通常浅暗一致，但仍要实测确认，不假设。

> **为什么单独一步**（issue：底导 ingest 复盘）：曾只抽浅色源、暗色靠 hue 推断重着色，导致暗色中性色（全选 / 灰副说明 / 凑单条底 / 面板底）系统性错值，且暗色变体只摆了部分 case。暗色必须当**独立态**逐节点拉，和浅色同等对待。

### Step 5: Token 反查

按 [references/token-reverse-lookup.md](./references/token-reverse-lookup.md) 把抽到的实际值反查到 V16 token：

- 读 `jd-design-system-md-v16/foundations/tokens/tokens.json`
- 色彩：hex → atom.* → color.* token 名
- 文字：fontSize + weight + family → `{family}_{weight}/font_size_N_W` role token
- 圆角：px → radius.* token
- 间距：px → spacing.* token
- 材质：INSTANCE name → material.* 引用

**没匹配到的 → 标 ⚠️ token-miss**，写到 frontmatter 注释 + section 表格说明，**不要尝试创建新 token**。

#### Step 5.1: Naming-conflict 检测(消费 shared 规则)

反查完拿到候选 token 名后,**写 frontmatter 之前**对每条 token 名跑一次 fingerprint 检查,真相源 [`../../../.claude/shared/references/naming-conflict-rules.md`](../../../.claude/shared/references/naming-conflict-rules.md):

- **撞已知冲突表**(如 `color_border` / `color-border` 同 fingerprint) → frontmatter 该 token 后追加一行注释:
  ```yaml
  references:
    uses_tokens:
      colors:
        - color_border  # ⚠️ naming-conflict: 与 color-border 同 fingerprint colorborder,值漂移(透明 8% vs 6%),详 shared/references/naming-conflict-rules.md
  ```
  并在终端 warn 设计师:`⚠️ token "color_border" 撞 V15 已知 naming-conflict,推荐保留 snake_case 版本。详情见报告 / shared/references/naming-conflict-rules.md`
- **未撞已知** + 反查返回 ≥ 2 个 fingerprint 一致候选且 `$value` 不同 → 同样加 ⚠️ 注释,但措辞为"**新**未登记 naming-conflict (fingerprint = X),建议开 follow-up issue 加进 shared 规则文件"。
- **未撞** → 不加注释,照常写。

> 目的:**让上游不静悄悄把已知 / 新冲突 token 写进 design.md** 让 design-review 后置才发现。

#### Step 5.2: 切图侦测（v0.5.2）

抽取脚本返回的 `imageNodes[]`（带 `IMAGE` 类型 fill 的节点 = 切图位图资产）按 [references/cutout-detection.md](./references/cutout-detection.md) 处理:

- 按 `imageHash` **去重**(同一张切图被多处复用合并为 1 条);
- 每条切图整理出「用途 / Relay 节点 ID / 尺寸」三列,CDN URL **留空**,状态 `⏳ 待上传 CDN`;
- outline 模式 → 写进 outline 的「切图清单」段(Step 5.5);
- `--confirm-outline` 模式 → 在 Step 8.5 登记到 `_assets-cdn.md`。

> **为什么单独侦测**:位图切图(卡通形象 / 彩色图标 / 实拍图)token 和矢量都无法表达,必须 CDN 托管。原抽取脚本只收 `SOLID` fill、`IMAGE` fill 被静默丢弃 —— 切图全靠人肉登记易漏(issue #54)。

`imageNodes` 为空 → 跳过,outline / `_assets-cdn.md` / 终端都不出现切图段。

### Step 5.5: 生成 outline（默认一定执行）

读 [templates/outline.md](./templates/outline.md)，先输出 `{slug}/design-outline.md`，包含：

- **稿件预检**：Step 4.5 的六维度就绪度评估，渲染到 `{{section_preflight}}`
- 本次识别范围（当前节点实际覆盖的原子 / 组合 / 页面示意）
- 结构大纲（章节 / frame / 关键子节点）
- 状态 / 变体 / 组合维度
- **领域相关** token / materials / uses_components 摘要：先按 [references/outline-domain-filter.md](./references/outline-domain-filter.md) 判定 `outlineDomain`，只把当前规范领域相关的 token 提升为主体内容；页面容器、表格、页头装饰、标注辅助图层等视觉噪声只做降级说明，不写成核心规范表
- **切图清单**：Step 5.2 侦测到的 IMAGE fill 切图，标 `⏳ 待上传 CDN`，渲染到 `{{section_cutouts_or_none}}`（无切图则填「无」）
- **待设计师确认**：只列"当前证据不足、截图未取到、上下文未读全、交互未标注"这类真实缺口，**不要**写成泛泛建议
- **自动发现的风险**：当前领域内的 token-miss / naming-conflict / 半步间距 / 子组件未录入 / pageDocMode 判定不稳等；已按领域过滤降级的页面噪声不计入 token-miss 风险

#### Outline 模式写入约束

- 默认只写 `design-outline.md`
- **不写** `design.md`
- **不更新** `INDEX.md`
- **不回写** Relay sharedPluginData
- **不维护** `used_by`

如果未传 `--confirm-outline`，到此结束并输出 outline 模式终端提示。

**如果传了 `--confirm-outline` 但 Step 4.5 预检整体结论为 `⛔ 阻断`**：同样到此结束 —— **不执行 Step 6 及之后任何写入**，不写 design.md / INDEX.md / sharedPluginData，终端输出预检阻断提示（见 Step 11B 末尾）。设计师修稿 / 分块后重跑。

### Step 6: 导出 preview.png（仅 `--confirm-outline` 且预检未阻断时执行）

按 [references/preview-export.md](./references/preview-export.md) 步骤：

1. `use_design_script` 调 `node.exportAsync({format: 'PNG', constraint: {type:'SCALE', value:2}})` + `relay.base64Encode(bytes)` 返回 base64
2. 体积检查（< 500KB 走 inline，超过降 SCALE=1 重试 / 跳过）
3. Bash `echo '<base64>' | base64 -d > <output-dir>/preview.png`
4. Bash `file <path>` 验证 PNG 头

> v0.2 链路通了。如果导出报错（节点不可见 / MCP 抖动），**继续往下走**，design.md 留 placeholder + 终端 warn，**不要 abort**。outline 模式下截图可选，不应阻断确认门。

### Step 7: 决定正式输出路径（仅 `--confirm-outline` 时执行）

按 [references/auto-detect-rules.md](./references/auto-detect-rules.md) 第 4 节路径规则：

```
component-base + horizontal     → jd-design-system-md-v16/foundations/components-base/{slug}/design.md
component-business + horizontal → jd-design-system-md-v16/horizontal/components-business/{slug}/design.md
page + {设计部门}                     → jd-design-system-md-v16/product-architecture/{设计部门}/{业务}/{slug}/design.md
flow + {设计部门}                     → jd-design-system-md-v16/product-architecture/{设计部门}/{业务}/{slug}/design.md
```

> 业务组件(component-business)是横向专项,不挂部门;product-architecture 下按 设计部门 → 业务 → 页面 层层往下,不设 pages/ flows/ 平行目录。

#### v1.2 bundle 路径（统一 5 文件）

**输出目录** `{slug}/`，写 **5 个正文件**（v1.2，去 ai-schema）：

```
{slug}/
├── design.md       # 完整主文档（bundle: page-doc 标识 + bundle_files 清单 + relay_source 单点存储）
├── spec.md         # 视觉与结构规格（frontmatter 只 bundle_part_of，relay_source 见 design.md）
├── variants.md     # 形态与变体
├── behaviors.md    # 行为规范：交互 / 点击区 / 跳转 / 优先级 / 降级 / Donts / 多端适配
└── CHANGELOG.md    # 变更记录（append-only，每个 PR 一条）
```

（有切图 / 图标时另出 `_assets-cdn.md` + `assets/`，辅助文件不计入正文件数。）

如果 `{slug}/design.md` 已存在 + 是 v0.1 单 md（`bundle:` 字段缺失）→ 全部 5 个文件都加 `.NEW` 后缀写入，让设计师手动迁移。终端输出："⚠️ {slug}/design.md 是 v0.1 单 md 形态，v1.2 bundle 写入 design.md.NEW / spec.md.NEW / variants.md.NEW / behaviors.md.NEW / CHANGELOG.md.NEW，请手动迁移。"

> **frontmatter 单点存储约定（v0.5.1）**：`relay_source` 整段（file_id / page_id / node_id / node_name / node_type / bounds / url）**只在 design.md 写**。spec.md / variants.md / behaviors.md / ai-schema.yaml 顶部 frontmatter 只保留 `bundle_part_of: design.md` 反向指针。这样 Relay URL / file_id / node_name 变更时只需改 1 处。

如果路径已存在 `design.md`，**不要覆盖**：改名为 `design.md.NEW`，让设计师手动 diff。终端输出："⚠️ {path}/design.md 已存在，新版本写入 design.md.NEW，请 diff 后合并。"

### Step 8: 套模板生成 design.md（仅 `--confirm-outline` 时执行）

#### v1.2 模板：统一 bundle（无分流）

> v1.2 起**不再按 `pageDocMode` 分流单份 / bundle**。所有组件一律走 [templates/page-doc/](./templates/page-doc/) bundle，写 **5 个正文件**：

| 模板 | 输出 |
|---|---|
| [templates/page-doc/](./templates/page-doc/)（design 完整主文档 + spec + variants + behaviors + CHANGELOG） | `{slug}/{design,spec,variants,behaviors}.md + CHANGELOG.md`（+ 有切图时 `_assets-cdn.md` / `assets/`） |

- `templates/component.md`（单份）已弃用，仅供读存量 design.md 参考。
- `ai-schema.yaml` 移出默认 bundle（需要才可选生成）。
- `pageDocMode` 仍用于**抽取策略**（大稿是否按章节切分抽），与文件分流无关。

##### page-doc bundle 渲染规则

读 5 个正文模板各自渲染（design 完整主文档 + spec + variants + behaviors + CHANGELOG；`ai-schema.yaml` v1.2 默认不产，见下「可选」）：

1. **[templates/page-doc/design.md](./templates/page-doc/design.md)** → `{slug}/design.md`（**完整主文档，非薄 index**）
   - frontmatter 含 `bundle: page-doc` 标识 + `bundle_files: [...]` **5 文件清单**（design/spec/variants/behaviors/CHANGELOG）+ 完整 `relay_source` 整段（v0.5.1：单点存储）
   - 主体是完整主文档：`## 一句话定义` / `## 边界` / `## 结构总览` / `## 形态总览` / `## 设计原则` / `## 典型场景` / `## 关联`（细规下钻 spec/variants/behaviors）+ 顶部 bundle 文件索引表 + 指向 CHANGELOG.md 的链接
   - 各 `{{section_*}}` 占位符由模型按抽取数据构造完整段；缺数据 → TODO / ⚠️，不留 `{{}}`

2. **[templates/page-doc/spec.md](./templates/page-doc/spec.md)** → `{slug}/spec.md`
   - frontmatter 含 `file: spec` + `bundle_part_of: design.md` 反向指针 + 完整 `uses_tokens` 段。**不再含 `relay_source` 段**（v0.5.1：单点存储，见 design.md）
   - 主体含 colors / typography / radius / spacing / materials 全表 + 章节 01-02 原文引用块
   - 占位符 `{{section_chapter_01_02_full_text_or_empty}}` = 章节 01 设计原则全文 + 章节 02 组件设计属性核心规范文字（按 v0.4 抽取的 chapters[].notes 渲染）

3. **[templates/page-doc/variants.md](./templates/page-doc/variants.md)** → `{slug}/variants.md`
   - frontmatter 含 `file: variants` + `bundle_part_of`。**不再含 `relay_source` 段**（v0.5.1）
   - 主体含变体维度概览 + 各维度详细规范 + 章节 02 状态/招手 + 章节 03 灵动岛三型原文
   - 占位符 `{{section_variant_dimensions_overview}}` = 形态 / 状态 / 坑位 / 子组件 等维度的 bullet list
   - 占位符 `{{section_variant_details_per_dimension}}` = 每个维度展开（继承 v0.4 章节细分段的渲染逻辑）

4. **[templates/page-doc/behaviors.md](./templates/page-doc/behaviors.md)** → `{slug}/behaviors.md`
   - frontmatter 含 `file: behaviors` + `bundle_part_of`。**不再含 `relay_source` 段**（v0.5.1）
   - 主体含应用场景 ✅/❌ + 交互 + Donts + 多端适配 + 章节 04-05 原文（v1.2 删 AI Schema 摘要段）
   - 占位符 `{{section_donts_auto_or_todo}}` = v0.4 自动收的 dont_rule 聚合（每条标来源章节）

5. **`ai-schema.yaml`（v1.2 默认不产 / 可选）** —— 仅当组件需要机器可读 schema 时显式生成，套 [templates/page-doc/ai-schema.yaml](./templates/page-doc/ai-schema.yaml)（已标弃用）；不进默认 `bundle_files`。

6. **[templates/page-doc/CHANGELOG.md](./templates/page-doc/CHANGELOG.md)** → `{slug}/CHANGELOG.md`（正文第 5 件）
   - 跨 bundle 的变更表，每次 skill 重跑追加一行（不覆写），design.md 内只保留指向 CHANGELOG.md 的链接
   - **"存在则追加"渲染规则**（仅本文件特殊，其它 5 个文件按"覆盖 / 或 .NEW"原路径处理）：
     - 渲染前先判 `[ -f "$BUNDLE_DIR/CHANGELOG.md" ]`
     - **存在** → `Read` 原文件，保留所有"标题 / 反向指针 / 已有 table 行"，**只在表末追加一行新 entry**（时间 / 操作 / 来源 / 备注），整体回写
     - **不存在** → 套模板生成首份（1 行"创建"）
   - 新增行字段约定：`时间`=`{{today_iso}}`，`操作`=本次升级语义（如"v0.5.1 优化"/"v0.6 升级"），`来源`=`skill {{skill_version}}` + flag 说明，`备注`=本次主要 diff 概述 + 关联 issue/PR

> **bundle 之间的反向引用**
>
> design.md（完整主文档）顶部 bundle 索引表列出 **5 文件链接**;spec.md / variants.md / behaviors.md 顶部有 `> design.md → [index](./design.md) · 同 bundle: ...` 导航条;子文件 frontmatter 都有 `bundle_part_of: design.md` 标识；`relay_source` 整段只在 design.md 出现一次。

> **v1.2：无 single 分支**
>
> 所有组件走上面的 bundle 渲染，不再有"单份 design.md"路径（`templates/component.md` 已弃用）。`pageDocMode` 只决定**抽取时是否按章节分块**（见顶部「v1.2 标准」节 + SOP ①），与文件分流 / 模板选择无关。

---

#### 旧路径：v0.1 单 md 模板（`pageDocMode === false`）

读 [templates/component.md](./templates/component.md)，把模板里的 `{{...}}` 占位符替换成 Step 2-5 的实际数据。

> **v0.4：page-doc 模式渲染**（已被 v0.5 bundle 路径取代，但保留兼容）
>
> 如果 `rootInfo.pageDocMode === true` **且 `chapters[]` 非空**（v1.3 起 chapters 已按 FRAME/GROUP 过滤，无合格子节点时为 `null`），渲染 `{{section_chapter_details_or_empty}}` 为完整的 "## 设计规范细节（按章节）" 段。对每个 chapter（来自返回的 `chapters[]`）：
>
> ```
> ### 章节 {N}：{chapter.name}（节点 `{chapter.id}`，{w}×{h}）
>
> - 章节标题：{第一条 bucket=chapter_title 的 text.chars}（无则省略）
>
> #### 图示
> | # | 标号 | 上下文 |
> |---|---|---|
> | 1 | {figure.label} | {figure.ctx 取同 frame 最近的 description bucket} |
> ...
>
> #### 尺寸标注
> | DP/px | 来源 |
> |---|---|
> | {dim.value} | {dim.ctx} |
>
> #### 禁止规则
> - {dont.chars}（章节 {N}）
>
> #### 关键说明
> > {notes[0].chars}
> > {notes[1].chars}
> > {notes[2].chars}（≤ 3 条，避免淹没）
> ```
>
> 如果 `pageDocMode === false`，**或 `chapters` 为 `null`/空**（v1.3：过滤后无 FRAME/GROUP 章节），`{{section_chapter_details_or_empty}}` 渲染为空字符串（不出现该段）。
>
> 同时，全局聚合所有 chapter 的 donts 数组到 `{{section_donts_auto_or_todo}}`：
> - 有 donts → 渲染为 markdown bullet 列表，每条标 `(章节 N)` 来源
> - 没 donts → 保留原 `<!-- TODO: 设计师列举常见误用 -->` 占位

#### 占位符语义 (v0.3.1 明确)

**简单字符串替换**，**不是** jinja2 / handlebars / mustache 等 DSL：
- `{{field_name}}` → 直接替换为对应字段的字面值（如 `{{slug}}` → `navbar`）
- **不支持**条件 (`{% if %}`)、循环 (`{% for %}`)、表达式 (`{{ a | b }}`)、嵌套引用
- 占位符位置如果数据缺失 → 替换为字面 `TODO` 或 ⚠️ 描述，**不要**留 `{{...}}` 在最终文件
- 需要循环生成的段落（如 `section_colors_table` 多行）—— **由模型自己构造完整段落**作为单个字符串塞进去，不依赖模板 control flow

> **这是明确契约,不是缺陷**:模板里不引入循环 DSL 是为了让模板"长得像最终产物",设计师 review 时不需理解 control flow 语法。代价是循环段落由模型构造 — 模型按变量名(`section_colors_table` / `section_donts_auto_or_todo` 等)识别"该这里构造什么形态",参考下方占位符语义表 + 同 bundle 现存样例。Liu review 提到的"回退到不确定性"是已知 tradeoff,接受。

例：
```
模板：name_zh: "{{name_zh}}"
数据：name_zh = "按钮"
结果：name_zh: "按钮"
```

```
模板：{{section_colors_table}}
数据：fills = [{用途:按钮底, token:color_primary, hex:#FF0F23}, ...]
结果（模型自己构造 markdown table）：
| 用途 | Token | 实际 hex |
|---|---|---|
| 按钮底 | `color_primary` | `#FF0F23` |
| 文字 | `color_primary_text` | `#FFFFFF` |
```

#### 严禁

- 任何 frontmatter 字段编造（缺数据 → 标 TODO）
- 任何 token 名编造（没反查到 → 标 ⚠️ token-miss）
- 任何视觉数据虚构（必须来自 Step 4 实际抽取）

frontmatter 必填字段见 [profiles/jd-v16/frontmatter-spec.md](./profiles/jd-v16/frontmatter-spec.md)。

5 处 TODO placeholder（设计师手填）：
- `## 一句话定义` 段
- `## 应用场景` 段 ✅/❌
- `## 交互` 段
- `## Donts` 段（**v0.4：page-doc 模式如果抽到 ≥1 条 dont_rule bucket，此段自动填**，不再 TODO）
- `## AI Schema` 段

其他全自动填。

#### v0.4.1 模板占位符补充

| 占位符 | 替换值 |
|---|---|
| `{{skill_version}}` | 当前 skill 版本号字符串（如 `v0.4.1`、`v0.5`），从 SKILL.md 版本历史最新一行取 |
| `{{todo_count}}` | 实际剩余 TODO 数（基础 5，page-doc 模式 + Donts 自动填 → 4） |

#### v0.5.2 切图侦测占位符

| 占位符 | 用在 | 替换值 |
|---|---|---|
| `{{section_cutouts_or_none}}` | `templates/outline.md` | 切图清单 markdown 列表（用途 / 尺寸 / 节点 ID / ⏳）；无切图填「无」 |
| `{{section_cutouts_table}}` | `templates/_assets-cdn.md` | 去重后的切图表体（多行，模型自己构造），列：用途 / Relay 节点 / 尺寸 / CDN URL（空）/ 状态 `⏳ 待上传 CDN` |
| `{{assets_cdn_link_or_empty}}` | `component.md` / `page-doc/design.md` 关联段 | 侦测到切图 → `- 位图切图清单：[_assets-cdn.md](./_assets-cdn.md)`；无切图 → 空字符串 |

#### v0.5.3 稿件预检占位符

| 占位符 | 用在 | 替换值 |
|---|---|---|
| `{{section_preflight}}` | `templates/outline.md` | Step 4.5 预检评估：整体结论 + 六维度逐行（`✅/⚠️/⛔` + 一句话），`⚠️` 项另在「待设计师确认」段展开 |
| `{{section_tokens_summary}}` | `templates/outline.md` | 按 `outlineDomain` 过滤后的领域相关 token / materials / 子组件摘要；字体/排版类 page-doc 只展开字体族、字号、字重、行高等排版信息，表格背景色、容器圆角、页头装饰图等页面噪声降级说明，不写核心 token 表 |

### Step 8.5: 生成 / 更新 _assets-cdn.md（仅 `--confirm-outline`，侦测到切图时）

如果 Step 5.2 侦测到切图(`imageNodes` 非空),按 [references/cutout-detection.md](./references/cutout-detection.md) §4 把切图清单写进输出目录的 `_assets-cdn.md`:

- 套 [templates/_assets-cdn.md](./templates/_assets-cdn.md) 模板,`{{section_cutouts_table}}` 渲染为去重后的切图表(用途 / Relay 节点 / 尺寸 / CDN URL 留空 / 状态 `⏳ 待上传 CDN`);
- **`_assets-cdn.md` 已存在 → 走「存在则合并」规则**:`Read` 原文件,命中节点 ID 的行**保留设计师已回填的 CDN URL / 状态**,只追加本次新侦测行,原文件有、本次没侦测到的行**保留不删**(可能是手工登记的 Relay 章节大图等);
- frontmatter 固定写 `bundle_part_of: design.md` + `bundle_role: assets-manifest`(harness v1，v1.2 起所有组件都走 bundle，单 md 分流已废);
- 在 design.md `## 关联` 段把 `{{assets_cdn_link_or_empty}}` 渲染为 `- 位图切图清单：[_assets-cdn.md](./_assets-cdn.md)`。

> `_assets-cdn.md` 是**辅助资产清单**,下划线前缀标识 infra 性质,**不计入 v0.5.1 封板的 6 文件 bundle**(封板针对增加 review 成本的正文文档)。

切图为空 → 跳过本步,不生成 `_assets-cdn.md`,`{{assets_cdn_link_or_empty}}` 渲染空。

### Step 8.6: 清理 Phase-1 大纲（仅 `--confirm-outline`，v1.2）

`design-outline.md` 是 **Phase-1 一次性确认门**产物,不是 bundle 文件。正式 bundle 写成功后,它已过期(待确认项 / 风险已在 bundle 各文件 + `design.md ## 待办` 段承接)。

- bundle 写入成功 → **删除同目录 `{slug}/design-outline.md`**(`Bash rm -f`),避免成品旁残留过期确认稿。
- 删除前确认 bundle 至少 `design.md` 已落盘;预检 `⛔ 阻断`未写 bundle 时**不删**(大纲要留着给设计师改)。
- 终端提示加一行:`🧹 已清理 design-outline.md(Phase-1 确认门,bundle 已生成)`。
- 需要追溯历史大纲 → 看 git 历史,不在工作区留。

### Step 9: 更新 INDEX.md（仅 `--confirm-outline` 时执行）

[references/traceability.md](./references/traceability.md) 第 1 节"INDEX.md 维护"。读 `.agents/skills/relay-to-design-md/INDEX.md`，按 BG 分组追加新条目（如已存在 slug → 更新 last_synced 行不是追加）。

### Step 10: 反向引用 — backlinks 实时查询（不再写 `used_by`）

> issue #45 (#41 第 1 条) 改造:`used_by` 双向硬写有 O(N²) 风险(一个被 100 处引用的基础组件改名要触发 100 处 `used_by[]` 更新),改为**按需扫**。

**本步不再写任何 design.md 的 `used_by` 字段**。新文件的 `used_by` 字段保留为空数组 `[]` 仅为向后兼容,不再由 skill 维护。

需要查"本组件被谁引用"时,跑:

```bash
bin/find-backlinks.sh <slug>           # 例:bin/find-backlinks.sh tabbar
bin/find-backlinks.sh <relative-path>  # 例:bin/find-backlinks.sh foundations/components-base/icon-home
```

输出引用本组件的所有 `design.md` 相对路径列表,无引用打印 `无引用`。脚本扫所有 wiki 目录(v15 / v16)的 `design.md`,在 frontmatter `references.uses_components` 段内 grep。

**`uses_components` 引用了尚未录入的子组件**(典型:joy-agent / icon-home 待图标库批量录入),只在 frontmatter 留注释 `# 注:A 尚未录入 design.md,待后续`,**不写 used_by**。

详见 [references/traceability.md](./references/traceability.md) 第 ④ 节。

### Step 10.5: 回写 Relay sharedPluginData（仅 `--confirm-outline` 时执行）

成功写完 design.md 后，把元数据回写到 Relay 节点。**namespace 固定 `jd-design-wiki`**(注册表与生命周期见 [`../../../.claude/shared/references/relay-namespaces.md`](../../../.claude/shared/references/relay-namespaces.md))。

通过 `use_design_script`：

```javascript
const node = await relay.getNodeByIdAsync('<NODE_ID>')
node.setSharedPluginData('jd-design-wiki', 'design_md_path', '<相对仓库根的 md 路径>')
node.setSharedPluginData('jd-design-wiki', 'last_synced', '<YYYY-MM-DD>')
node.setSharedPluginData('jd-design-wiki', 'slug', '<slug>')
node.setSharedPluginData('jd-design-wiki', 'level', '<level>')
node.setSharedPluginData('jd-design-wiki', 'bg', '<bg>')
return { keys: node.getSharedPluginDataKeys('jd-design-wiki') }
```

**写入失败 / Relay 离线 → 重试 3 次后不阻断**:

1. 失败 1:等 2s 重试(典型 transient MCP 抖动)
2. 失败 2:等 5s 重试
3. 失败 3:**最终失败**,终端**醒目** ⚠️ 输出:
   ```
   ⚠️⚠️⚠️ Relay sharedPluginData 回写 3 次失败!!
   ⚠️ 本地 design.md / INDEX.md 已就绪,但 Relay 端节点反查不到 md 路径(双向追溯单边断)
   ⚠️ 设计师必须手动补回:bin/sync-index.sh --push-shared-data {slug}
   ⚠️ 不补回的后果:下次跑 design-review 等 skill 拿不到 Relay 端反查链
   ```
4. 继续往下走(不 abort,因为 design.md 是核心产物)

设计师**应当**在 review 终端输出时看到 ⚠️ 提示并手动补回。**不补回**会让 [`../../../.claude/shared/references/relay-namespaces.md`](../../../.claude/shared/references/relay-namespaces.md) 中 `jd-design-wiki` namespace 永久持有的 keys 缺失,影响 design-review / spec-page 等下游 skill。

详见 [references/traceability.md](./references/traceability.md) 第 ③ 节。

### Step 11: 终端输出（给设计师）

#### 11A. 默认 outline 模式

```text
📝 已生成大纲: {输出路径}/design-outline.md
   ├─ level: {自动推断} {如走兜底 → 加 ⚠️}
   ├─ bg:    {自动推断} {同上}
   ├─ slug:  {自动推断} {同上}
   ├─ 待确认项: {N}
   ├─ 切图: {C} 处待上传 CDN {仅 C>0 时显示此行}
   └─ 风险项: {M}

🔍 稿件预检:{整体结论 ✅ 通过 / ⚠️ 待补充 / ⛔ 阻断}
   ├─ 节点规模:{✅/⚠️/⛔} {一句话}
   ├─ 命名可信度:{✅/⚠️} {可疑名个数}
   ├─ 命名漂移率:{✅/⚠️} {maxShare 百分比 + 占位值}
   ├─ 标注完整度:{✅/⚠️} {一句话}
   ├─ 截图可得性:{✅/⚠️} {一句话}
   └─ 结构清晰度:{✅/⚠️} {一句话}

⏸ 当前为 outline 模式，未写入 design.md
   未更新 INDEX.md / Relay sharedPluginData(`used_by` 已不再由 skill 维护,见 Step 10 + issue #45)

下一步：设计师确认大纲后执行
/relay-to-design-md <relay_url> --confirm-outline
```

#### 11B. `--confirm-outline` 正式写入模式

完成后输出格式如下（中文，含 emoji，简短）：

```
🔍 稿件预检:{整体结论 ✅ 通过 / ⚠️ 待补充}

✅ 已生成: {输出路径}
   ├─ level: {自动推断} {如走兜底 → 加 ⚠️}
   ├─ bg:    {自动推断} {同上}
   ├─ slug:  {自动推断} {同上}
   └─ {N} 处 <TODO: 设计师补充> 待填空

📎 已附 screenshot: {path}/preview.png  {或 ⚠️ 未导出}
📚 已更新 INDEX.md
🔗 双向追溯 OK: frontmatter.relay_source ↔ INDEX.md

{如有 token-miss / 半步间距 / 未录入子组件等}
⚠️ 检测到 {M} 个需要 review 的问题，详见 design.md 末尾 "本次自动同步发现的待办" 段

{如 Step 5.2 侦测到切图}
🖼 检测到 {C} 处切图（IMAGE fill），需导出并上传 CDN：
   ├─ {用途1}  ({w}×{h})  节点 {id}   ⏳ 待上传
   └─ ...
   已登记到 {slug}/_assets-cdn.md，请设计师 export → 上传京东 CDN → 回填 URL
```

**预检 `⛔ 阻断` 时**（Step 4.5 整体结论为阻断）改为输出，**不写任何文件**：

```
🔍 稿件预检:⛔ 阻断
   └─ 节点规模:⛔ {h / nodeCount 超限说明}

⛔ 稿件预检未过 —— 已停止,未写 design.md。
   严重缺口:{规模超限说明,建议分块录入}
   请设计师修稿 / 分块后重跑 /relay-to-design-md <relay_url> --confirm-outline
```

**TODO 计数 N 动态计算**：基础 5 处（一句话定义 / 应用场景 / 视觉预览 / 交互 / Donts / AI Schema 中无数据 placeholder）— 本次实际自动填上的（v0.4：page-doc 模式扫到 ≥1 条 dont_rule 时 Donts 自动填，N 减 1）。最少 4 处，最多 5 处。

#### 11C. Status 提示(issue #46)

11B 写入成功后,在终端尾部加一段:

```text
📝 本次产物 status=draft,含 {N} 处 TODO 待设计师补。
   升级 status 前必须补完:
   - status: review     → design-review / bin/validate.sh 任一 ❌ 即 exit 1(block PR)
   - status: published  → 同上 + frontmatter 不可有 ⚠️ fallback 残留
   规则详见 design-review SKILL.md Step 3c Status 联动 + bin/validate.sh line 201-206。
```

`N` 取 11B 倒数第二行计算结果。Status 联动只在 `status ≥ review` 起强约束,draft 阶段产物允许残留 TODO(skill 默认 draft)。

---

## 关键约束

1. **不要问设计师任何问题**。所有字段自动推断，不确定就用兜底值 + TODO flag。
2. **不要编造 token**。反查不到就 flag ⚠️ token-miss，保留实际 hex 值。
3. **不要覆盖已存在的 design.md**。用 `.NEW` 后缀，让设计师 diff。
4. **不要把检测错的字段 silent 过**。Frontmatter `auto_detected` 字段显式记录"哪些是推断、哪些走了兜底"，让 review 时一眼可见。
5. **不依赖模型聪明度**。所有判断走 references 里的查找表 / 规则，模型只做 string substitution。
6. **5 处 TODO 模板**保留原样，不要尝试帮设计师填。
7. **深浅双态各自抽，禁止靠浅色重着色推断暗色**（v0.5.4，见 Step 4.6）。当组件存在 浅色 / 暗色（日间 / 暗黑）两套变体（同名 frame 后缀「暗色」「dark」，或并列的浅/暗 section）时：**两套都要逐节点 `get_design_context` / 抽 fill，分别记录到 design.md（暗色 token 独立列，不与浅色合并）**。暗色中性色经常与浅色不同（实测案例 底导：全选 浅`#5A5E66`/暗`#A1A9B3`、灰副说明 浅`#8D9199`/暗`#717985`、容器底 浅`#FFEDEF`/暗`#3D2529`、面板 `#1F2226`；品牌红 `#FF0F23` 才浅暗一致）。**绝不能只抽浅色、暗色靠 hue 推断**——会系统性错。verify 阶段必须**对比浅/暗的变体数是否一致**（如浅色 7 个结算态、暗色也必须抽满 7 个），不齐记 wiki gap。

8. **空间方位 / 视觉样式事实必须以「抽取 + 截图」为准，禁止从 node name / 标注标签推几何**（v1.1，硬闸）。凡写进 design.md 的 **① 空间方位**（角标在左上 / 左下、标签贴底、利益点在标题上还是下、元素左右关系）和 **② "文字 vs 填充"视觉样式**（这段是橙色文字还是填充 chip、描边还是实底）:
   - **方位**优先取脚本 `instances[]` / `imageNodes[]` / `iconNodes[]` 的 `pos` 象限(v0.5.6,`{h,v}`) —— 确定性事实,不许凭标注标签名(「视频」「直播」)猜方位。注:矢量角标(播放标 = `BOOLEAN_OPERATION`)走 `iconNodes`,别漏看;
   - **`pos` 为 null(节点无 bbox)** 或要判 **样式**(文字 / 填充 / 描边)→ `pos` 不覆盖 → **必须对该区域 `get_screenshot` 截图核对后才落笔**,不许从 node name 推;
   - 踩坑实例(双列 Feed,见 SOP ②校验):角标方位误写「左下」(实为左上)、营销利益点误判「橙渐变填充 chip」(实为纯橙色文字) —— 都是"放着能抽 / 能看的事实不核对、凭标签脑补",且 design.md 错了下游 HTML 会忠实渲染错值。

## References

跨 skill 共享(`../../../.claude/shared/references/`,PR #115 工具中立化后 `.claude/shared/` 物理位置仍在,从 `.agents/skills/<name>/` 看是 3 层上+ `.claude/`):

| 文件 | 作用 |
|---|---|
| [level-vocab.md](../../../.claude/shared/references/level-vocab.md) | `level` 枚举词表 + 与 `bg` 边界(本 skill 写,site/spec-page 消费) |
| [relay-namespaces.md](../../../.claude/shared/references/relay-namespaces.md) | `jd-design-wiki` namespace 注册 + 生命周期 |
| [naming-conflict-rules.md](../../../.claude/shared/references/naming-conflict-rules.md) | Token fingerprint 算法 + V15 已知冲突表(Step 5.1 检测消费,与 design-review 共用) |

本 skill 私有(`templates/`, `references/`):

| 文件 | 作用 |
|---|---|
| [templates/component.md](./templates/component.md) | 单 md 模板 (v0.1) — 普通组件 |
| [templates/page-doc/design.md](./templates/page-doc/design.md) | page-doc bundle index 模板 (v0.5)；v0.5.1 起 relay_source 单点存储于此，变更记录链到 CHANGELOG.md |
| [templates/page-doc/spec.md](./templates/page-doc/spec.md) | page-doc bundle 视觉规范模板 (v0.5)；v0.5.1 删 relay_source |
| [templates/page-doc/variants.md](./templates/page-doc/variants.md) | page-doc bundle 变体模板 (v0.5)；v0.5.1 删 relay_source |
| [templates/page-doc/behaviors.md](./templates/page-doc/behaviors.md) | page-doc bundle 行为模板 (v0.5)；v0.5.1 AI Schema 改为摘要 + 链接 |
| [templates/page-doc/ai-schema.yaml](./templates/page-doc/ai-schema.yaml) | page-doc bundle AI Schema 独立模板 (v0.5.1，issue #23) |
| [templates/page-doc/CHANGELOG.md](./templates/page-doc/CHANGELOG.md) | page-doc bundle 变更记录独立模板 (v0.5.1，issue #23) |
| [templates/_assets-cdn.md](./templates/_assets-cdn.md) | 位图切图 CDN 清单模板 (v0.5.2，辅助资产清单，非 bundle 正文文档) |
| [references/auto-detect-rules.md](./references/auto-detect-rules.md) | 推断 level / bg / slug / name_zh 的规则表（v0.2 加 slug 变体后缀） |
| [references/node-type-mapping.md](./references/node-type-mapping.md) | Relay 节点属性 → design.md section 对照 + 统一抽取脚本 |
| [references/cutout-detection.md](./references/cutout-detection.md) | 切图侦测判据 + `_assets-cdn.md` 登记规则（v0.5.2） |
| [references/preflight-gate.md](./references/preflight-gate.md) | 稿件预检门六维度判据 + Phase 2 闸门规则（v0.5.7） |
| [references/outline-domain-filter.md](./references/outline-domain-filter.md) | outline 领域过滤规则：避免字体/色彩/圆角等 foundation 长页把页面容器视觉噪声误写成主体规范 |
| [references/token-reverse-lookup.md](./references/token-reverse-lookup.md) | hex / fontSize+weight / radius / spacing 反查 V16 token 算法（v0.2 加 rgba 容差） |
| [profiles/jd-v16/frontmatter-spec.md](./profiles/jd-v16/frontmatter-spec.md) | Frontmatter 字段定义 + 校验规则 |
| [references/traceability.md](./references/traceability.md) | INDEX.md 维护 + 反向引用维护 + （v0.3）Relay sharedPluginData |
| [profiles/jd-v16/bg-mapping.json](./profiles/jd-v16/bg-mapping.json) | file_id → bg 映射表（v0.1 仅 V16 master） |
| [references/variant-vocab.json](./references/variant-vocab.json) | VARIANT 中文值 → 英文 slug 片段映射（v0.2 加） |
| [references/preview-export.md](./references/preview-export.md) | preview.png 导出算法（v0.2 加） |
| [references/slug-pinyin-fallback.md](./references/slug-pinyin-fallback.md) | 节点名全中文时的 slug 词表（v0.3 加） |
| [references/checklist.md](./references/checklist.md) | 设计师提交 PR 前自检 10 条 |
| [bin/validate.sh](./bin/validate.sh) | 提交前自动校验（v0.2 加 / v0.3 加 cross-file） |
| [bin/sync-index.sh](./bin/sync-index.sh) | INDEX.md 自动重建（v0.3 加） |
| [examples/navbar-search-day/design.md](./examples/navbar-search-day/design.md) | 范例（搜索条日间 NavBar 实际跑出来的样本） |
| [references/text-pattern-rules.md](./references/text-pattern-rules.md) | text node 文本 5 类 bucket 分类规则（v0.4 加） |
| [INDEX.md](./INDEX.md) | 双向追溯索引（按 BG 分组） |

## 版本历史

### v1.4(2026-06-02)· chapters[] 按 FRAME/GROUP 过滤（治变体 / 扁平页假章节，issue #125 ①）

- **抽取脚本 v0.5.8**：`node-type-mapping.md` 的 `chapters[]` 与 `chapterOf()` 共用 `chapterChildIds`（只含 `FRAME`/`GROUP` 类型的第 1 层子节点）。修掉 latent bug：12 变体 `COMPONENT_SET` 被错当 12 章节（且与 `variants[]` 双重计数）、200 instance 扁平 L3 页让 outline 爆 200 行。过滤后无合格子节点 → `chapters = null`，章节细节段不渲染（v1.2 取消单份后等价于「不按章节切分」）。
- **渲染层**：Step 8 v0.4 章节段在 `chapters` 为 `null`/空时也渲染空；预检门维度 ⑤ 加 case——`pageDocMode === true` 但 `chapters` 过滤后为空 → `⚠️`，提示设计师确认是否需要章节切分。
- **issue #125 ②③④ 不做（v1.2 已覆盖）**：②（结构阈值松导致误报 bundle）/④（nodeCount 代理 bundle 决策）的前提是「单份 vs bundle 分流」，v1.2「统一 bundle」已取消该分流，前提消失；③（.NEW 雪片）的成因是 bundle 决策不稳，决策取消后 `.NEW` 仅用于 v0.1→v1.2 一次性迁移与既有文件保护，是预期设计。三者随 v1.2 自然消解，无需重做。

### v1.3(2026-06-02)· 预检门加「命名漂移率」维度（治 node name 大规模漂移，issue #137）

- **抽取脚本 v0.5.7**：`node-type-mapping.md` 的 `textStyles[]` 加 `name` 字段，让预检门能看到 TEXT node 的命名漂移。
- **预检门第 ⑥ 维度「命名漂移率」**：`preflight-gate.md` 用 `maxShare = maxCount/totalNames`（最高频单一 name 占比）检测「100+ node 全叫同一占位值」这类草稿残留（PR #128 录入字体规范时全叫「推流地址」）。`> 0.8` 时 `⚠️` 显著标出，提示先在 Relay 修 name 再重跑。原维度 ②「命名可信度」只抓数字残留 / 默认名，抓不到占位名，故另立一维。
- **`text-pattern-rules.md` §6 局限**：文档化 `characters` 缺失 / `name` 漂移两类失效场景 —— skill 不做 OCR 兜底、不从 ✅ 段反推 dont（避免 hallucinate），处理方式是预检显著告警 + 渲染以截图为准 + outline 留痕。这是 issue #136（typography Donts TODO）的源头机制。

### v1.2(2026-06-01)· 统一 bundle 标准（取消单份 / 文件集定为 4 md + CHANGELOG）

- **设计组定调**：取消「单份 design.md vs page-doc bundle」分流，**所有组件统一 bundle**，文件集固定 `design + spec + variants + behaviors + CHANGELOG`（对齐 bottom-bar 框架）。
- **`design.md` 改为完整主文档**（定义/边界/结构总览/形态总览/原则/场景），不再是薄 index；细规下钻 spec/variants/behaviors。
- **去 `ai-schema.yaml`**（移出默认 bundle，模板标弃用，可选生成）；**单份 `templates/component.md` 弃用**（仅读存量）。
- 改动件：SKILL.md（顶部 v1.2 标准节 + Step 7/8 路由）/ `templates/page-doc/design.md`（重写为完整主文档）/ `behaviors.md`（删 AI Schema 段）/ `ai-schema.yaml`·`component.md`（标弃用）/ profile `bundle-rules.md`·`path-rules.md` / 连带 `design-md-to-spec-page` 输入契约（不再依赖 ai-schema）。
- `pageDocMode` 退化为**仅抽取策略**（大稿是否按章节切分），不再决定文件分流。

### v1.1(2026-06-01)· 方位象限 + 视觉事实截图闸门（治"凭标签脑补几何"）

- **① 抽取脚本 v0.5.6**：`node-type-mapping.md` 新增 `posOf(n)`,`instances[]` / `imageNodes[]` 加 `pos` 象限 `{h,v}` —— 把"角标在左上还是左下"从**推断**变回**抽取**(坐标本就在 Relay metadata 里,原契约只取 size 丢了 position)。
- **② 关键约束 #8**：空间方位优先取 `pos`;"文字 vs 填充"等视觉样式事实必须 `get_screenshot` 核对后落笔,禁止从 node name / 标注标签推几何。
- **③ checklist.md**：必检加一条"空间方位 / 视觉样式以抽取+截图为准"。
- **④ 来源踩坑**:双列 Feed(`1758:251`)端到端实跑 —— 角标方位误写「左下」(实为左上)、营销利益点误判「橙渐变 chip」(实为纯橙文字);编译回 SOP ②校验「踩坑实例」段。这是 issue #56 预检门之外、**录入精度**的第一个系统性修复。

### v1.0.1(2026-05-27)· outline 领域过滤

- 新增 [references/outline-domain-filter.md](./references/outline-domain-filter.md)：Step 5.5 渲染 outline 前先判定 `outlineDomain`，字体/排版类 page-doc 只提升字体族、字号、字重、行高、价格字体、倒计时等排版信息
- `templates/outline.md` 中 token 段标题改为「领域相关 Tokens / 材质 / 子组件」，避免误导设计师把所有抽取到的视觉值都当成当前规范主体
- 对字体/排版长页，表格背景色、文档容器圆角、页头装饰图、标注辅助色、页面布局 gap 等只做降级说明，不再作为核心 token 表或 token-miss 风险

### v1.0(2026-05-27)· 标准化 + Profile 系统

- 加 4 阶段 pipeline overview(Stage 1 内容抽取 / Stage 2 文件组织 / Stage 3 校验 / Stage 4 Hand-off);11 step 详细流程归到对应 stage
- 加 `profiles/` 目录:`jd-v16`(默认)/ `jd-v15`(冻结)/ `generic`(外部团队 fork 起点)
- 把 V16 特定内容从 `references/` 搬到 `profiles/jd-v16/`:`frontmatter-spec.md`, `bg-mapping.json`, 新增 `controlled-vocab.json` / `path-rules.md` / `bundle-rules.md` / `token-catalog.json`
- 加新文档:`README.md`(5 分钟概览)/ `ADOPTION.md`(新人 4 步上手)/ `TROUBLESHOOTING.md`(12 个 Q&A)/ `CONTRIBUTING.md`(Part 1-5 扩展指南)
- 支持 `SKILL_PROFILE` env var 切换 profile;无值时默认 jd-v16
- skill 核心保持向后兼容:11 step 流程不变,只在 Step 3 / 5 / 7 / 8 用 profile config 而非 hardcode V16
- Hand-off brief 标准化输出(替代之前散落的 terminal 输出)

### 历史版本

- **v0.1** (2026-05-13) MVP：L1 通用组件 / 单 md / 仅 V16 master 文件 bg 推断 / 无 Relay sharedPluginData 回写
- **v0.1.1** (2026-05-13) 圆角抽取修复：
  - 统一抽取脚本 `all = [root, ...root.findAll()]`，root 自身被纳入遍历（原 `findAll` 不含 root）
  - 圆角支持 `relay.mixed`：抽取 4 个角的个体值（V15→V16 升级中可能出现 4 角不同的情况）
  - instances 过滤掉 root 自身（防止 root 是 INSTANCE 时被误算成"子组件引用"）
  - 影响范围：所有圆角在 root 节点上的组件（按钮 / 卡片 / 弹窗 / 容器类）现可正确抽到 radius
- **v0.2** (2026-05-13) 4 项升级：
  - **① slug 变体后缀**：用 `componentProperties` (VARIANT type) 自动 build 后缀；INDEX.md 冲突时数字后缀兜底；新建 `references/variant-vocab.json` 维护中→英映射
  - **② preview.png 自动导出**：`exportAsync({format:PNG, SCALE:2})` → base64 → Bash 写文件；新建 `references/preview-export.md`
  - **③ rgba 反查扩展**：rgba(R,G,B,opacity) 在 atom 里 ±2% 容差匹配；rgba-of-pure-color 启发式（white/black/jdred @opacity）→ 建议新 atom 名供设计组 review
  - **④ validate.sh 提交前校验**：扫所有 design.md，校验 frontmatter + 受控词表 + slug 格式 + relay URL + preview.png 存在 + TODO/⚠️ 残留；新建 `bin/validate.sh`
- **v0.3** (2026-05-13) 4 项升级：
  - **① Relay sharedPluginData 回写**：SKILL.md 新增 Step 10.5；写 5 个 key (`design_md_path`/`last_synced`/`slug`/`level`/`bg`) 到 Relay 节点的 namespace `jd-design-wiki`；设计师在 Relay 点节点可反查 md 路径；写失败不阻断
  - **② INDEX.md 全自动 sync**：新建 `bin/sync-index.sh` —— 扫所有 design.md 重建 INDEX；处理删除/移动/重命名/slug 冲突；支持 dry-run 和 --write；macOS bash 3.x 兼容
  - **③ slug 中文 fallback**：新建 `references/slug-pinyin-fallback.md` ~60 个 JD 设计常用词中→英映射；auto-detect S3 接入
  - **④ validate.sh cross-file 校验**：检查 `uses_components` 引用的子 design.md 是否存在、preview.png 非空、INDEX.md 是否含本 slug；新警告项
- **v0.4** (2026-05-13) page-doc 支持 — 兑现 issue #18 第一步：
  - **① page-doc 模式自动判定**：root.height > 5000 或 ≥3 个 FRAME 子项 ⇒ pageDocMode；抽取脚本返回 `chapters[]` 元数据
  - **② text node 5 类 bucket 分类**：chapter_title / figure_label / dont_rule / dimension_spec / description；新建 `references/text-pattern-rules.md`
  - **③ Donts 段自动收**：page-doc 模式下，扫到的禁止规则文本（"禁止*"/"不可*"/含 ❌）自动汇总到 `## Donts` 段，标注来源章节
  - **④ instance 加 size**：absoluteBoundingBox 抽 width/height，专治"灵动岛 131×44 DP"这类只在 instance 上的尺寸
  - **⑤ limit 全面提升**：textStyles 30→200，instances 30→150，layouts 20→50，text chars 80→200（page-doc 节点数据量大）
  - **⑥ 章节归属**：所有 text/instance/layout 加 `chapter` 字段（root.children 第 1 层），模板新增 `## 设计规范细节（按章节）` 段
- **v0.4.1** (2026-05-14) issue #20 follow-up — review 找到的 should-fix 集中收口：
  - **① chapterOf 修 root 边界 bug**：`if (n.id === root.id) return null` short-circuit（已在 PR #19 二次提交里修；本版加 rootChildIds Set 缓存优化性能）
  - **② pageDocMode 删冗余条件** `&& kids.length >= 3`（frameKids ⊆ kids，必然成立）
  - **③ text-pattern-rules.md 与 classifyText 1:1 对齐**：删英文 chapter 措辞、dimension_spec regex 加 `/`、章节聚合改为渲染层 group-by（抽取层只挂 `chapter` 字段）
  - **④ SKILL.md TODO 计数动态化**：原"5 处 TODO 待填空" → "{N} 处"，page-doc 模式 Donts 自动填时 N=4
  - **⑤ 模板加 `{{skill_version}}` / `{{todo_count}}` 占位符**：消除 `skill v0.1` 硬编码
  - **⑥ Radius token 改 T-shirt size**：tabbar design.md `Radius_6/8/12/16` (atom) → `radius_base/l/xl/xxl` (token)，与 V16 tokens.json `radius.*` 命名对齐
  - **⑦ frontmatter spacing list 类型规整**：`- TODO: xxx` (map) → `- "TODO: xxx"` (string)
  - **⑧ frontmatter 长行注释拆出独立块**：auto_detected.level 行内 100 字符注释 → 上方独立 # 块
- **v0.5** (2026-05-14) page-doc multi-md bundle —— 兑现 issue #18:
  - **① 新建 [templates/page-doc/](./templates/page-doc/) 4 模板**：design.md (index) / spec.md / variants.md / behaviors.md
  - **② Step 7 路径决策加 page-doc 分支**：同目录写 4 个文件，已存在 v0.1 单 md 时全 4 文件加 `.NEW` 后缀
  - **③ Step 8 模板分流**：`pageDocMode === true` 走 bundle 4 模板，否则走 v0.1 单 md。v0.4 单 md 内章节细分段保留作 fallback
  - **④ bundle 反向引用**：design.md frontmatter 加 `bundle: page-doc` + `bundle_files: [...]`；spec/variants/behaviors 三个子文件 frontmatter 加 `bundle_part_of: design.md` + 顶部导航条
  - **⑤ 回填重跑 tabbar**：540 行单 design.md 拆成 4 文件 bundle（PR 同时提交）
- **v0.5.1** (2026-05-18) issue #23 follow-up —— PR #22 review 找到的 bundle 优化集中收口：
  - **① AI Schema 拆独立 `ai-schema.yaml`**：原 behaviors.md 内嵌 108 行 yaml（机器可读 schema）和人类规范文字（应用场景 / 交互 / Donts / 多端适配）性质完全不同，拆为独立 `tabbar/ai-schema.yaml`；behaviors.md 改为一行摘要 + 链接；新建 [templates/page-doc/ai-schema.yaml](./templates/page-doc/ai-schema.yaml) 模板；bundle_files 清单加一项
  - **② 变更记录搬到独立 `CHANGELOG.md`**：design.md (index) 不该承担变更历史，原 8 行变更表移到 `tabbar/CHANGELOG.md`，design.md 只留指向链接；新建 [templates/page-doc/CHANGELOG.md](./templates/page-doc/CHANGELOG.md) 模板
  - **③ `relay_source` 单点存储到 design.md**：原 spec / variants / behaviors 三个子文件都重复 `relay_source: {node_id, url}`（一旦 url / file_id 变了要改 4 处）。改为只在 design.md 写完整 `relay_source` 整段，子文件 frontmatter 只保留 `bundle_part_of: design.md` 反向指针 + 一行注释说明
  - **④ tabbar bundle 同步回填**：tabbar/{design,spec,variants,behaviors}.md 按上面 3 项重组（新增 ai-schema.yaml + CHANGELOG.md，删 3 处 relay_source 重复，搬变更表）
- **v0.5.2** (2026-05-20) 切图侦测 —— 兑现 issue #54：
  - **① 抽取脚本收 IMAGE fill**：`node-type-mapping.md` 统一脚本新增 (g) 段，扫所有节点 `fills`，凡带 `type === 'IMAGE'` 判为切图收进 `imageNodes[]`。**原脚本只收 SOLID、IMAGE fill 被静默丢弃**是本问题根因
  - **② 新增 Step 5.2 切图侦测**：`imageNodes` 按 `imageHash` 去重，整理「用途 / 节点 ID / 尺寸」，CDN URL 留空 + 状态 `⏳ 待上传 CDN`
  - **③ 新增 Step 8.5 生成 `_assets-cdn.md`**：侦测到切图时套 [templates/_assets-cdn.md](./templates/_assets-cdn.md) 写辅助资产清单，「存在则合并」保留设计师已回填 URL；下划线前缀辅助文件，不计入 6 文件封板
  - **④ outline + 终端提醒**：outline 加「切图清单」段，`--confirm-outline` 终端打 `🖼 检测到 N 处切图` checklist
  - **⑤ 边界**：skill 只侦测 + 登记 + 提醒，京东 CDN 上传仍需设计师手动；新建 [references/cutout-detection.md](./references/cutout-detection.md)
- **v0.5.3** (2026-05-20) 稿件预检门 —— 兑现 issue #56：
  - **① 新增 Step 4.5 稿件预检门**：Step 4 抽取后、Step 5 前跑一次五维度就绪度评估（节点规模 / 命名可信度 / 标注完整度 / 截图可得性 / 结构清晰度），每维度 `✅/⚠️/⛔`
  - **② Phase 2 闸门**：整体 `⛔ 阻断`（仅节点规模严重超限触发）时，即使传 `--confirm-outline` 也不写 design.md，要求设计师修稿 / 分块后重跑
  - **③ outline + 终端**：outline 顶部加 `## 稿件预检` 段，终端打 `🔍 稿件预检` 五维度结论
  - **④ 抽取脚本加 `nodeCount`**：`rootInfo.nodeCount` = `all.length`，供规模维度判断
  - **⑤ 新建 [references/preflight-gate.md](./references/preflight-gate.md)**：五维度机械判据 + 闸门规则；只做规则判断不评设计质量，`⛔` 仅留给致命情况避免误报
- **v0.5.4** (2026-05-25) backlinks 实时化 —— 兑现 issue #45 / #41 第 1 条:
  - **① 新建 [`bin/find-backlinks.sh`](./bin/find-backlinks.sh)**:按 slug 或 relative-path 扫所有 design.md 的 frontmatter `references.uses_components` 段(awk 锁 frontmatter + 缩进感知锁段),输出引用本组件的相对路径列表;无引用打印「无引用」。覆盖 v15 + v16 两个 wiki 目录
  - **② Step 10「维护反向引用」改造**:取消 `used_by` 双向硬写(O(N²) 风险:基础组件改名要触发 N 处 design.md 更新),改为按需调脚本实时查;`uses_components` 引用未录入子组件时只在 frontmatter 留注释,不写 used_by
  - **③ 来源 PR**:[#84](https://github.com/ShuaiMXu/jd-design-wiki-proposal/pull/84)
- v0.6 (planned) 加 page.md / flow.md 模板 + batch 模式 + Diff 模式（只更新机器抽取段，保留人写段）
