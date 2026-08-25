---
name: design-review
description: 'Audit a JD APP design (V15.0 or V16.0) — either a Relay node OR a committed `design.md` in `jd-design-wiki-proposal`
  — through one of two lenses. Lens A · token 合规 (color / typography / radius / spacing / motion / icon / layout tokens +
  frontmatter compliance + token reverse-lookup + section completeness). Lens B · 设计评判 (philosophy-driven 组件评判 + 场域页面评判 from
  the V16 智性设计 judgment standard — 7 dimensions, page-type calibration, P0/P1/P2). Auto-routes lens by target: 整页/场域 → Lens
  B, 单组件/组件 design.md → Lens A. Triggered by relay.jd.com URLs / node IDs / design.md paths together with verbs like "审核",
  "走查", "review", "audit", "检查规范", "符合 15.0 吗", "符合 16.0 吗", "审 design.md" (token lens); or "评审体验", "场域走查", "任务路径", "符合设计哲学吗",
  "符合价值观吗", "P0/P1/P2", "这个页面/流程合理吗" (judgment lens). Outputs a structured report, saved to `design-review-report.md` for
  design.md targets and echoed to terminal.'
allowed-tools:
- mcp__zero-design__get_design_metadata
- mcp__zero-design__get_design_context
- mcp__zero-design__get_screenshot
- mcp__zero-design__get_variables
- Bash
- Read
- Write
- Edit
harness-version: 1
intent: 走查
profile: jd-v16
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/.agents/skills/design-review/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
  short-description: 检查页面或设计稿的问题并给出修改建议，适合通用设计评审与方案走查。
disable-model-invocation: true
---

# /design-review · JD V15.0 / V16.0 设计稿走查（双镜头）

> **v0.8 · 双镜头**(token 合规 + 设计评判)。把设计稿与 `jd-design-wiki-proposal` 仓库做交叉校验,输出可读 + 可复核的报告。**两个正交的镜头**:Lens A 查 token 合规(机械、确定性),Lens B 按 V16「智性设计」评判标准查组件/场域体验(定性、要背景输入)。镜头**按目标类型自动选**,见下面「评审镜头(Lens)选择」。

**支持两种输入**(输入形态,与镜头正交):
- **Relay 模式** — 输入 Relay URL 或 `nodeId`(`xxx:yyy`),审 Relay 节点的设计稿
- **design.md 模式** — 输入仓库内 `**/design.md` 路径或 bundle 目录,审已落地的 design.md 文件

**两个镜头**(决定做哪种评审):
- **Lens A · Token 合规** — token 体系交叉校验,**根据源 fileKey 自动选 V15 还是 V16 真相源**(color/typography/radius/spacing/motion/icon + design.md frontmatter/反查/章节)。本 skill 原有能力,内容见下面两个「工作流」。
- **Lens B · 设计评判** — 按 V16 [`设计评判标准`](../../../jd-design-system-md-v16/ai-mechanism/design-judgment-standard.md)(智性设计四层链路第 4 层)做组件评判 + 场域页面评判。见下面「工作流(评判镜头 · Lens B)」。

---

## 何时触发

用户给出一个 Relay 设计链接 / 节点 ID,**或**一份 `design.md` 文件路径 / 包含 design.md 的目录,并要求:
- "审核 / 走查 / review / audit 这个设计稿"
- "审 design.md" / "校验 design.md 是否合规" / "查 design.md 的 token 反查对不对"
- "符合 15.0 设计规范吗" / "符合 16.0 吗"
- "检查一下用了哪些 token"
- "这个 token 用对了吗"

如果用户只是问"这个设计长啥样",**不要**触发本 skill —— 那是单纯的 `get_design_context` 用法。

## 不适用场景

- 非 JD 内部 Relay 文件(仅覆盖 V15.0 + V16.0 wiki)
- 用户要求**生成**新设计(那是 design-on-zero 的工作)
- 设计稿是 Figma 而非 Relay(zero-design MCP 只接 Relay)

---

## 输入解析

**先判断模式**(根据用户输入字面形态):

| 输入形态 | 模式 | 转 |
|---|---|---|
| `https://relay.jd.com/file/design?id=...` | **Relay** | 下面"工作流(Relay 模式)" |
| 裸 `nodeId`(`xxx:yyy` 或 `xxx-yyy`) | **Relay** | 同上 |
| `*.md` 路径(典型:`jd-design-system-md{,-v16}/.../design.md`) | **design.md** | 下面"工作流(design.md 模式)" |
| 含 `design.md` 的目录(bundle 模式根目录) | **design.md** | 同上,自动定位 `{dir}/design.md` |
| glob(`jd-design-system-md-v16/**/design.md`) | **design.md(批量)** | 同上,逐文件跑 |

### Relay 模式输入解析

URL 形如 `https://relay.jd.com/file/design?id={fileKey}&page_id={pageId}&node_id={nodeId}`

提取:
- `fileKey` → query 参数 `id`
- `nodeId` → query 参数 `node_id`,把 `-` 替换为 `:`(例:`639-3394` → `639:3394`)

如果用户只给 `nodeId`(裸的 `xxx:yyy`),直接用。

### design.md 模式输入解析

- 路径必须存在且可读;否则报错退出
- 若是目录,定位 `{dir}/design.md`;不存在报错退出
- 若是 glob,展开为文件列表,逐份走 Step 1-4 + 落各自 `design-review-report.md`
- 从首条 `---` ~ `---` 段提取 frontmatter(YAML),取出 `relay_source.url` → 解析出 `fileKey` 走下面 Step 2 V15/V16 路由

---

## 评审镜头(Lens)选择

输入解析完**先选镜头**,再进对应工作流。镜头与输入形态(Relay / design.md)正交。

### 选镜头规则(优先级从高到低)

1. **显式 flag / 动词 → 直接定镜头**(永远压过自动判):
   | 信号 | 镜头 |
   |---|---|
   | `--token` / "走查 token" / "符合 15/16 吗" / "检查规范" / "token 用对了吗" | **Lens A** |
   | `--judge` / "评审体验" / "场域走查" / "任务路径" / "符合设计哲学/价值观吗" / "P0/P1/P2" / "这个页面/流程合理吗" | **Lens B** |

2. **无显式信号 → 按目标类型自动判**:

   | 目标 | 判别启发 | 镜头 |
   |---|---|---|
   | **整页 / 场域** | **Relay**:`get_design_metadata` bounds ≈ 375 宽 × 高(≥600)+ 多个子模块(导航/卡片/区块堆叠)。**design.md**:frontmatter `level: page`(见 [`level-vocab.md`](../../../.claude/shared/references/level-vocab.md)),典型路径 `product-architecture/**/design.md` | **Lens B** |
   | **单组件 / 组件 design.md** | **Relay**:小 bounds、单一结构、INSTANCE/COMPONENT 类型。**design.md**:`level ∈ {component-base, component-business, foundation}`,典型路径 `foundations/components-base/**` 或 `horizontal/components-business/**` | **Lens A** |

3. **判不准(模糊)→ 问用户**:不默认硬猜,问"这次要 token 合规走查(Lens A)还是设计评判(Lens B)?"

### 护栏(向后兼容)

- **现有 CI / 批量 glob** 跑的是 `foundations/components-base/**/design.md`(组件)→ 规则 2 自动判 = **Lens A**,与改动前**行为完全一致**,不破坏 CI。
- **整页 Relay URL 自动判成 Lens B** 时,在报告**顶部加一行**:`> 本次按场域设计评判(Lens B);若要 token 合规走查,加 --token`。避免老用户被静默改变预期。
- Lens A 的全部逻辑、契约文件名 `design-review-report.md`、5 段式输出**原封不动**。

> **下面两个「工作流(Relay 模式)」「工作流(design.md 模式)」是 Lens A 的实现**(token 合规),保持不变。Lens B 的实现见再往下的「工作流(评判镜头 · Lens B)」。

---

## 工作流(Relay 模式)

### Step 1 — 拉设计稿三件套(尽量并行)

并行调用以下 MCP 工具:
1. `mcp__zero-design__get_screenshot(nodeId)` —— 视觉参考
2. `mcp__zero-design__get_variables(nodeId)` —— **核心数据源**,返回设计稿引用的全部 design token
3. `mcp__zero-design__get_design_metadata(nodeId)` —— 结构与命名,大节点会写到 tool-results 文件,**不要**强制读全文,grep 即可

> **限速**:同一 file 短时间并发 5 个以上 MCP 请求会让服务侧丢连接。三件套并行 OK,更多请串行。

### Step 2 — 加载 token 真相源(按 fileKey 路由 V15 / V16)

#### 2.1 判断版本

| 输入 `fileKey` | 版本 | tokens.json 路径 | fallback snapshot |
|---|---|---|---|
| `1896756863949619202` | V15.0(历史 spec file) | `~/code/jd-design-wiki-proposal/jd-design-system-md/foundations/tokens/tokens.json` | `references/tokens-snapshot.md`(V15) |
| `2029484645871009793` | V16.0(当前 master) | `~/code/jd-design-wiki-proposal/jd-design-system-md-v16/foundations/tokens/tokens.json` | TBD(暂未提供 V16 fallback,无 tokens.json 时报错退出) |
| 其他 | 未知 | 默认按 V16 路径尝试;失败再按 V15 | 同上 |

> file_id 映射与 `relay-to-design-md/references/bg-mapping.json` 共用同一份真值,变更必须同步双方。

#### 2.2 读取

按版本选定 tokens.json 路径,仓库克隆存在 → **首选** tokens.json;不存在 → 走对应版本的 fallback snapshot。读 tokens.json 时只关心 `color` / `typography` / `radius` / `spacing` / `icon` / `motion` 6 大块的 `$value`。

V15 / V16 两套 tokens.json **结构兼容**(都是 `$value` token 树),但具体 token 名 / 命名空间不完全相同 —— 走 V16 时下面 Step 3a-3f 的命名空间启发(如"`色彩变量 Color/...` 命名空间")可能不再适用,见 Step 3 前的注。

### Step 3 — 交叉校验

> **V15 / V16 命名启发适用性提醒**:下方 3a-3f 的命名空间识别(如 `色彩变量 Color/...` / `日间` / `C_Newgray` 等 14.x→15.0 迁移痕迹)、Naming-conflict fingerprint 表(`colortexthelp` 等)均源于 V15 实战。V16 启用后命名空间可能改变,启发可能误报 / 漏报。**走 V16 跑出意外结果时,先把规则贴到报告里、标"V15 启发,V16 待校",然后开 follow-up issue 而不是直接静默**。

#### 3·前置 · Token 命名唯一性检查(kebab/snake 双轨)

**真相源**:[`../../shared/references/naming-conflict-rules.md`](../../shared/references/naming-conflict-rules.md) —— fingerprint 算法、触发判定、V15 已知冲突表(`colorborder` / `colortexthelp` / `colorbackgroundsunken`)、消费方契约都在那。

走任何颜色 / 字体 / 圆角白名单匹配**之前**,先对 `get_variables(nodeId)` 返回的 variables 表跑一次 fingerprint 唯一性检查:

- 不同 `$value` 撞同 fingerprint → ❌ **Naming-conflict**(违规)
- 同 `$value` 但命名风格混用 → ⚠️ **Naming-style**(警告,不阻塞)

#### 报告规则

- Naming-conflict 类违规**置于 ❌ 段顶部**,优先于 Off-token / Legacy
- 每条建议显式给出**保留哪个 / 删除哪个**(保留策略见 shared 规则文件)
- 触发后该 fingerprint 组内的其他错误(Off-token / Legacy)**仍要标**,但归并到同一组建议下输出
- 撞**新**未登记冲突 → 报 ❌ + 开 follow-up issue 把 fingerprint 加进 shared 规则文件的已知冲突表

#### 为什么这是前置全局规则

14.x → 15.0 迁移最普遍的残留模式 —— 同一概念两个 token 同时存在,值已漂移。让 AI / 设计师选取时随机命中,是设计漂移最隐蔽的源头,占典型走查 30%+ 的违规来源,机器可判,**优先扫掉**避免后续 3a-3f 重复报。

---

#### 3a. 颜色

把 variables 里每个 `色彩变量 Color/...` 与 `平台色板/...` 与 `灰阶/...` 等命名空间下的 token,逐一与 tokens.json `color.*` 路径对照:

判定 5 种结果:
| 状态 | 条件 |
|---|---|
| ✅ Pass | 设计稿 token 名 + 值都能映射到 tokens.json 某条目 |
| ⚠️ Naming | 值在 tokens.json 中存在,但**命名空间错位**(如 `color_primary_disabled = #c2c4cc`,#c2c4cc 实际是 `text.disabled` 而非 primary) |
| ⚠️ Legacy | token 命名带 `日间` / `C_Newgray` / `Newgray` 等 14.x 前缀 → 残留旧 token,15.0 已用新名 |
| ❌ Off-token | 值不在 tokens.json 的任何条目中(且非透明度组合) |
| ❌ Naming-conflict | 已由 Step 3 前置规则识别——同 fingerprint 出现 ≥2 个变体且值不同 |

**特殊判定**:
- `color_primary_light = #fff0f4` → 实际同 `semantic.danger-subtle` (15.0 中 brand 与 danger 同色,wash 共用) → 标 ⚠️ Naming,建议改名
- `color_service*` 用在**非 VIP / 非金融场景**(如普通筛选 chip)→ 标 ⚠️ Semantic drift

#### 3b. 字体

对每个 `Font(...)` token 检查:

| 维度 | 15.0 白名单 |
|---|---|
| `family` | `京东朗正体 V2.0`(品牌) / `PingFang SC`(中文正文) / `京东正黑 V2.2`(数字) |
| `size`(基础) | **10 / 12 / 14 / 15 / 18** |
| `size`(价格特殊) | **15 / 18 / 24**(羊角符 / 角分最低 12) |
| `weight` | **400** / **600** / **700**(数字限定) |
| `lineHeight` | 字号 × 1(单行) / 字号 × 1.5 奇数 -1(段落) |
| `letterSpacing` | 0 |

❌ **硬性违规**:size ∉ 上述阶梯 → 标 ❌ Off-spec。**特别注意 token 名带"临时新增"的字段** —— 这是 15.0 设立后被绕开的明确证据。

⚠️ **名实不符**:token 名说 `_600` 但实际 `weight: 500` → 命名残留。

#### 3c. 圆角

值需 ∈ **{0, 2, 4, 6, 8, 12, 24, 9999/full}**。
对应 token: `radius.{0, xs, s, base, detail, xl, structural, full}`。

不在白名单 = ❌ Off-token。

#### 3d. 间距

值需 ∈ **{0, 2, 4, 6, 7, 8, 12, 16, 20, 24, 28, 32, 40, …(4 的倍数延展)}**。
- 7 是 Feeds 特殊值
- 2 仅导购型慎用
- 6 平台型慎用、导购型常规

判语义层级(塔式原理):
- 卡片内上下安全 = 平台 16 / 导购 12
- 卡片内左右安全 = 平台 12 / 导购 8
- 区块内子元素 = 平台 8 / 导购 6
- 紧密关联 = 4
- 非卡片元素左右 = 16

错乱 → 标 ⚠️ Hierarchy violation。

#### 3e. 动效(若 metadata 包含)

时长 ∈ **{100, 150, 200, 300}ms**。
缓动 ∈ **standard / decelerate / accelerate / spring** 4 类贝塞尔。
出场必须 ≤ 入场 1 档(进 300 出 ≤ 200 / 进 200 出 ≤ 150 / 进 150 出 = 150)。

#### 3f. 结构 / 布局(从 screenshot 判断)

- 逻辑尺寸 375?(默认)
- 内容详情型(商详 / 结算 / 订详)→ **平铺式**(直角拉通)
- 导购入口型(首页 / 搜索 / 购物车)→ **卡片式**(小圆角收拢)
- 状态栏 44 / 起始指示器 34 / 屏幕左右 8(沉浸式专用)是否被尊重
- 起始指示器 34 区域**禁放操作按钮**

错乱 → 标 ⚠️ Structure mismatch。

### Step 4 — 输出报告

**输出渠道(两个模式共用)**:

| 模式 | 报告文件落点 | 终端 |
|---|---|---|
| Relay | 默认**不落文件**(节点不在仓库)。用户显式说"落文件"或加 `--report-file <path>` 时落到 `<path>` 或当前目录 `design-review-{nodeId}-{YYYY-MM-DD}.md` | ✅ 完整 markdown |
| design.md(单份) | 默认落 `{design.md 同目录}/design-review-report.md`(全量覆写) | ✅ 简短摘要(✅/⚠️/❌ 计数 + 报告路径) |
| design.md(批量 glob) | 每份各自落同目录 `design-review-report.md` | ✅ 表格汇总:文件 / ❌ / ⚠️ / ✅ 计数 + 报告路径 |

`design-review-report.md` 是契约文件名,**不要**改 / 起别的名字,这样设计师 / CI 能稳定 grep 出所有 review 结果。

**固定 5 段式 markdown 结构(两个模式都按此输出)**:

```
## 设计稿 Review · `<nodeId 或 design.md 路径>`

**类型识别**:<根据 screenshot 判断:页面 / 半弹层 / 弹窗 / 卡片 / etc.>
**逻辑尺寸**:<375 / 自适应>

### ❌ 违规(必须改)
<对每条:位置 + 规则引用 + 证据 + 建议>
<排序:Naming-conflict 优先 → Off-token → 其他>

### ⚠️ 警告(命名 / 残留 / 语义偏移)
<同上>

### ✅ 符合 V{version}(根据 Step 2 路由的版本填 V15.0 或 V16.0)
<表格:检查项 | 设计稿值 | 对应 token>

### 📋 无法仅凭 metadata 判断
<列出建议设计师补 variable 引用的项,如 radius / spacing>

### 文字总结
<1 段,X 个改动 + Y 个建议;主色彩 / 文本 / 字族遵守度评价;问题集中在哪>
```

每条违规 / 警告 **必须** 链接到 wiki 文件 + 章节,**链接前缀跟随 Step 2 路由的版本**:

| 版本 | 仓库内路径前缀 | GitHub URL 前缀 |
|---|---|---|
| V15 | `/jd-design-system-md/foundations/...` | `https://github.com/ShuaiMXu/jd-design-wiki-proposal/blob/main/jd-design-system-md/foundations/...` |
| V16 | `/jd-design-system-md-v16/foundations/...` | `https://github.com/ShuaiMXu/jd-design-wiki-proposal/blob/main/jd-design-system-md-v16/foundations/...` |

V15 例:
```
- 规则:[`tokens/typography.md` §2 字号阶梯](/jd-design-system-md/foundations/tokens/typography.md)
```

V16 例:
```
- 规则:[`tokens/typography.md` §2 字号阶梯](/jd-design-system-md-v16/foundations/tokens/typography.md)
```

---

## 工作流(design.md 模式)

> 校验对象不是 Relay 节点而是仓库内已落地的 `design.md`。校验维度比 Relay 模式更宽:**frontmatter 合规 + token 反查正确性 + 章节完整性 + Donts 数量**。一般不调 zero-design MCP —— 唯一例外是下面 **Step 0(ground truth 一致性审计)**,它需要回读 Relay 节点。

### Step 0 — Ground Truth 一致性审计(v0.1 · tabbar 试点)

> R3 走查补,见 [issue #60](https://github.com/ShuaiMXu/jd-design-wiki-proposal/issues/60) Gap 2。**仅当** design.md frontmatter 有 `ground_truth` 字段时执行;无该字段直接跳到 Step 1。

design.md 的尺寸文字可能过时 / 与 Relay 原版节点不符。Step 0 把 frontmatter 声明的 ground truth 节点与 design.md 表里的尺寸字段做交叉 diff。

1. 解析 frontmatter `ground_truth.nodes`(每条 `{ id, role }`)。
2. 检查 zero-design MCP 是否可用:
   - **不可用 / 无 Relay 访问** → 跳过 Step 0,在报告「📋 无法判断」段记一条「ground_truth 审计已跳过(无 Relay MCP)」,继续 Step 1。
   - 可用 → 继续。
3. 对每个 `ground_truth.nodes[].id` 跑 `get_design_metadata`,取子节点 bounds。
4. 把节点实测 bounds 与 design.md 正文表里**显式标注的尺寸字段**(坑位 / icon box / 文本框 / 容器宽高 / 灵动岛尺寸等)逐项 diff。
5. 判定(对齐 [`design-md-to-relay/references/fidelity-thresholds.md`](../design-md-to-relay/references/fidelity-thresholds.md)):

   | diff | 判定 |
   |---|---|
   | ≤ 0.5 DP | ✅ 一致 |
   | > 0.5 DP 且 ≤ 2 DP | ⚠️ 警告(可能命名漂移 / 残留草稿值) |
   | > 2 DP | ❌ 违规(design.md 与 ground truth 实质不符) |

6. 结果计入 Step 4 报告:`> 2 DP` 进「❌ 违规」段,`0.5~2 DP` 进「⚠️ 警告」段,每条标 `节点 id / 字段 / design.md 值 / 节点实测值 / diff`。

> Step 0 只**报告** diff,不改 design.md。修值由 design.md 维护者按报告决定 —— 可能是 design.md 文字过时,也可能是 Relay Frame 残留旧草稿值,需人工判断哪边是真相。

### Step 1 — 读 design.md + 解析 frontmatter

1. `cat` design.md 全文
2. 提取首条 `---` ~ `---` 段作为 frontmatter,YAML 解析
3. 关键字段读取:
   - `file` / `level` / `bg` / `slug` / `name_zh` / `name_en` / `status` / `version` / `last_synced`
   - `bundle: page-doc` 标识(若存在) + `bundle_files: [...]`
   - `auto_detected.*` 块
   - `relay_source.{file_id, page_id, node_id, url}`
   - `references.uses_tokens.{colors, typography, radius, spacing, materials}`
   - `used_by`
4. **若 `bundle: page-doc`**:同步读 `{dir}/spec.md` / `variants.md` / `behaviors.md` / `ai-schema.yaml` / `CHANGELOG.md`,各按以下形式验 `bundle_part_of: design.md` 反向指针:

   | 文件 | 反向指针位置 | 验法 |
   |---|---|---|
   | `spec.md` / `variants.md` / `behaviors.md` | 首段 `---` ~ `---` 标准 frontmatter | `bundle_part_of: design.md` 字段 |
   | `ai-schema.yaml` | 文件**顶部 yaml 注释**(`# bundle_part_of: design.md`) | grep `^# bundle_part_of:` |
   | `CHANGELOG.md` | 文件**顶部 markdown blockquote**(`> bundle_part_of: design.md`) | grep `^> bundle_part_of:` |

   3 种形式都接受,缺一个 → ❌ "bundle 子文件 X 反向指针缺失"。

### Step 2 — 加载 token 真相源(复用 Relay 模式 Step 2)

从 `relay_source.url`(或直接 `relay_source.file_id`)拿 fileKey,按上面"工作流(Relay 模式) → Step 2"的路由表选 V15 / V16 tokens.json。

无 `relay_source.url` 字段 → 标 ❌ 违规("frontmatter 缺 relay_source.url,无法定位 token 真相源版本");兜底用 V16 跑后续校验,但报告顶部标"版本未知,默认按 V16"。

### Step 3 — 4 维校验

#### 3a · Frontmatter 合规

按 [`../relay-to-design-md/references/frontmatter-spec.md`](../relay-to-design-md/references/frontmatter-spec.md) 校验:

| 维度 | 规则 | 失败级别 |
|---|---|---|
| 必填字段 | `file` / `level` / `bg` / `slug` / `name_zh` / `owner` / `status` / `version` / `last_synced` / `auto_detected` / `relay_source` 整块 全部在 | 缺一项 → ❌ |
| `used_by` 字段 | ⚠️ **可选**(issue #45 起 deprecated):字段存在则接受任意值不报错;不存在也不报错 | — |
| `file` 字段 | 固定值 `"design"` | ≠ → ❌ |
| `level` 在词表 | 与 [`../../shared/references/level-vocab.md`](../../shared/references/level-vocab.md) 5 枚举一致 | 不在 → ❌ |
| `bg` 在词表 | 与 frontmatter-spec.md `bg` 受控词表一致 | 不在 → ❌ |
| `slug` 格式 | kebab-case `^[a-z0-9]+(-[a-z0-9]+)*$`,2-50 字符,不能数字开头 | 违 → ❌ |
| `level + bg` 组合 | `component-base + bg ≠ horizontal` 或 `level ≠ component-base + bg = horizontal` | 触发 → ⚠️ |
| `last_synced` ISO date | `YYYY-MM-DD` | 不符 → ❌ |
| `relay_source.url` 可解析 | URL 中能提取 file_id / page_id / node_id 三者 | 不能 → ❌ |
| `auto_detected.*` 有 ⚠️ flag | level / bg / slug 中含 `⚠️ fallback` 标记 | 有 → ⚠️ 提示"需设计师 review 推断结果" |
| **slug 语义启发**(变体 vs 组件入口) | `relay_source.node_type` 是 `INSTANCE` + `bounds.w < 200` + `slug` 与 page 名同名 → 当前 design.md 可能是**单变体**而非组件总入口 | 触发 → ⚠️ 提示"建议设计师拍板:① 升级为组件总入口(扩展为 page-doc bundle) / ② 重命名为 `{slug}-{variant}` 作为变体文档,另起总入口" |
| Bundle frontmatter 单点存储 | `spec.md` / `variants.md` / `behaviors.md` / `ai-schema.yaml` 顶部应**只**有 `bundle_part_of: design.md` 反向指针,**不含**重复 `relay_source` 块(v0.5.1 起契约) | 重复了 → ⚠️ "build-up drift,改回单点存储" |

#### 3b · Token 反查正确性

**数据源**(按 mode 取):

| Mode | uses_tokens 在哪 |
|---|---|
| single design.md | `design.md` 自身 frontmatter `references.uses_tokens.*` |
| bundle (`bundle: page-doc`) | **`spec.md` frontmatter `uses_tokens.*`**(design.md index 通常只放 `uses_components`,不放 `uses_tokens`) |

> 漏看 bundle 数据源 → 误以为 design.md 没声明 token → 跳过 3b → 漏掉所有 Off-token / Value-drift。这是 v0.5 实战发现的常见错。

对取到的 `uses_tokens.{colors, typography, radius, spacing, materials}` 每条 token 名,按命名空间 3 路反查:

##### 路 1:role 层(优先)

V16 / V15 tokens.json 的 `color.*` / `radius.*` / `spacing.*` 节点带 `$extensions.relay_token_name` 标注,直接对名匹配:

```bash
jq -r '.. | objects | select(."relay_token_name") | ."relay_token_name"' tokens.json
# 列出所有 role 层 token 名(snake_case),如:
#   color_primary / color_text_help / color_border / radius_base / ...
```

design.md 声明的 `color_primary` 等命名直接进入此表查找,命中 → 拿对应 `$value` → 继续 hex/size 校验。

##### 路 2:typography role 反查归一化

typography role token 在 design.md 用 `{family}/{size_role}` 形式(因 Relay 章节原稿就这么写),tokens.json 用 dot path `typography.role.{family}.{size_role}`,需归一化:

```
pingfang_regular/font_size_10_400  →  typography.role.pingfang_regular.font_size_10_400
zhenghei_bold/font_size_14_600     →  typography.role.zhenghei_bold.font_size_14_600
```

规则:把 `/` 替换为 `.`,前缀加 `typography.role.`,直接按 dot path 查 tokens.json。`$extensions.relay_token_name` 在 typography role 节点**通常缺失**,所以**不走路 1**,只走本规则。

V16 typography 仅 4 family — `pingfang_regular` / `pingfang_semibold` / `zhenghei_regular` / `zhenghei_bold`。**`pingfang_medium`**(weight 500)等不在表 → ❌ Off-token,设计师应改用 regular(400)/ semibold(600)或申请加 token。

##### 路 3:atom 层兜底

V16 tokens.json `atom.*` 节点(`atom.jdred.6` / `atom.gray.3.light` / `atom.red.7` 等)**没有** `relay_token_name` 标注。design.md 引用 atom 层 token 时直接用 family 名或简短 alias(`jdred` / `gray_6` / `white` / `black`):

```bash
# atom path 直接匹配
jq -r '.atom | keys[]' tokens.json
# → errorred / gray / infoblue / jdred / red / servicegold / successgreen / warningyellow / white
```

design.md 声明的 atom 名按以下规则反查:

| design.md 名 | tokens.json path |
|---|---|
| `jdred` / `jdred_6`(单 family 单 shade) | `atom.jdred.6` |
| `gray_1` / `gray_3` / ... / `gray_10` | `atom.gray.{N}`(若不存在则报 ❌) |
| `white` / `black` | 在 `atom.*` 顶层独立 key,或映射到 `palette.*`(检查两处) |

**路 1 + 路 2 + 路 3 都未命中** → ❌ Off-token。**任一路命中** → ✅ Pass。

##### 值漂移校验

命中后,把 token `$value` 解析到底(如 `color.primary.$value = "{atom.jdred.6}"` → `atom.jdred.6.$value = "#FF0F23"`),与 design.md / spec.md 正文中该 token 旁边标注的 hex / size 对比:

- 对得上(case-insensitive)→ ✅
- 对不上 → ⚠️ Value-drift("声明 X = #aaa 但 V{version} 实际 = #bbb")
- 漂移属于 [`../../shared/references/naming-conflict-rules.md`](../../shared/references/naming-conflict-rules.md) 已知 V15 冲突表中的 fingerprint → 加注"V15 已知冲突,V16 是否已修请 follow-up 核"

> Token 反查算法详细启发见 [`../relay-to-design-md/references/token-reverse-lookup.md`](../relay-to-design-md/references/token-reverse-lookup.md)。本模式**不**做命名风格 fingerprint 检查(那是 Relay 模式 Step 3 前置规则的职责;design.md 已脱离设计稿命名空间)。

#### 3c · 章节完整性

按 [`../../shared/references/section-anchors.md`](../../shared/references/section-anchors.md) 7 章节 canonical 名,检查 design.md(或 bundle 文件)是否覆盖必要章节:

| 章节 | single mode 检查 | bundle mode 检查 |
|---|---|---|
| 1. 定义 | `## 一句话定义` 或 `## 定义` 段存在且非空 | `design.md ## 一句话定义` |
| 2. 行为准则 | `## 交互` 段(可选,缺 → ⚠️) | `behaviors.md ## 交互` |
| 3. 类型 | `## 变体 Variants` 段(可选) | `variants.md` 主表 |
| 4. 结构 | `## 视觉` 段(必,缺 → ❌) | `spec.md` colors / typography / radius / spacing 表至少一张 |
| 5. 布局 | `## 视觉 / 间距` 子段(可选) | `spec.md` 布局 / 间距段 |
| 6. 正反案例 | `## Donts` + `## 应用场景` 段(必,缺 → ❌) | `behaviors.md Donts` + `应用场景` |
| 7. 典型场景 | `## 应用场景` ✅ 子段 | `behaviors.md` 应用场景 ✅ 子段 |

##### 段在但内容空(实质空判定)

段标题存在 ≠ 章节合规。draft 阶段 design.md 经常出现"段标题在但下面只有 `<!-- TODO -->` 注释或 HTML 注释占位"的情况。**实质空判定**:

1. 取段落首 `^## ` 到下一个 `^## ` 之间的所有行
2. 过滤掉:空行、HTML 注释(`<!-- ... -->`)、纯标题行(`^###`)
3. 剩余文本字符数 < 20 → **实质空**

实质空处理(按章节必要性区分):

| 章节必要性 | 段缺 | 段在但实质空 |
|---|---|---|
| 必(1 定义 / 4 结构 / 6 正反案例) | ❌ "章节段缺失" | ❌ "章节段存在但实质空(全 TODO / HTML 注释占位),无可消费内容" |
| 可选(2 行为准则 / 3 类型 / 5 布局 / 7 典型场景) | ⚠️ | ⚠️ "可选章节实质空,建议补内容" |

> 实战(2026-05-18 button/design.md 二跑)发现:button v0.1 draft 7 段全在但 4 段实质空(`## 一句话定义` / `## Donts` / `## 应用场景 ✅` / `## 应用场景 ❌`),如果只查"段在"会全部漏报。实质空判定补这个洞。

##### Status 联动(issue #46)

按 frontmatter `status` 字段决定上述判定的最终输出级别:

| status | 实质空 / TODO 残留处理 | exit code |
|---|---|---|
| `draft` | 上面表格如实输出 ❌ / ⚠️,**不阻断** | 0 (warn) |
| `review` | 上面表格的 ⚠️ 全部**升级为 ❌**(可选章节实质空也不允许);任何 ❌ 出现立即报告 | **1 (block)** |
| `published` | 同 `review` + 额外要求 frontmatter 无 `⚠️ fallback` 残留 | **1 (block)** |
| `deprecated` | 全部 ❌/⚠️ 都改为 ℹ️ "已弃用,仅记录" | 0 |

实现:design-review 跑完 Step 3c 后,读 frontmatter `status` 字段并按上表重新分级。报告里在每条违规末尾标 `[status=X]` 让消费方知道是否阻断。

> 联动逻辑与 `relay-to-design-md/bin/validate.sh` line 201-206 一致(`status ∈ {review, published}` + TODO 残留 → error)。两边规则**保持同步**,改一处要改两处。CI workflow `.github/workflows/design-md-validate.yml` 跑 validate.sh,exit ≠ 0 阻断 PR merge。

#### 3d · Donts 数量

提取 6. 正反案例对应段(`## Donts` 或 bundle `behaviors.md` Donts 段)的条目数。**上限按 mode 区分**:

| Mode | 下限 | 上限 |
|---|---|---|
| single design.md | ≥ 3 ✅ / 1-2 ⚠️ / 0 ❌ | > 8 ⚠️ "建议精简到 8 条以内" |
| bundle / page-doc | ≥ 3 ✅ / 1-2 ⚠️ / 0 ❌ | > 12 ⚠️ "建议精简到 12 条以内" |

> 实战(2026-05-18 tabbar/design.md 首跑)发现:复杂 bundle 组件(底导含常规 + Joy Agent + 灵动岛三形态 + 多端适配)9 条 Donts 都对应独立规则,合并损失语义。所以 bundle mode 上限放宽到 12,与 [`../design-md-to-spec-page/references/section-mapping.md`](../design-md-to-spec-page/references/section-mapping.md) "6. 正反案例" 段的"取最重要 8 条 + 末尾加截断提示"启发不冲突——8 是详情页渲染目标,12 是源文件容忍上限。

#### 3e · (可选)AI Schema 完整性

AI Schema 在两种形态出现,**同等检查**:

| Mode | 位置 | 验法 |
|---|---|---|
| bundle / page-doc | 独立 `ai-schema.yaml` 文件 | 直接读 yaml |
| single design.md | `## AI Schema` 段内嵌 fenced yaml block(```yaml ... ```) | 提取 fenced 块作 yaml 解析 |

基础结构检查(两种 mode 共用):

- YAML 可解析(语法对) → ✅;不可解析 → ❌
- 至少含 `forms` / `slots` / `states` / `events` 4 个顶层 key 中的 1 个 → ✅;一个都没有 → ⚠️ "AI Schema 太空,可能漏填"
- key 存在但值是 `TODO` 字面量(如 `states: TODO` 或 `events: TODO`)→ ⚠️ "AI Schema 段标题在但内容 TODO,建议设计师 + 工程师补状态机 / 事件签名"

不做语义完整性检查(那需要业务知识)。

> 实战(2026-05-18 button/design.md 二跑)发现:button single mode `## AI Schema` 内嵌 yaml block,states 4 态 + events 全部 `TODO` 字面量。原 SKILL.md 只对 bundle 独立文件做 3e,single 内嵌 yaml 没规则。本次扩展覆盖两种形态。

### Step 4 — 输出报告

复用 Relay 模式 Step 4 同款 5 段 markdown 结构,只是:

- 标题改为 `## design.md Review · \`{相对仓库根路径}\``
- 报告文件**默认**落到 `{design.md 同目录}/design-review-report.md`(覆写)
- 终端只打**简短摘要**:`✅ N / ⚠️ M / ❌ K · 报告:{path}`
- 多份(glob)→ 报告各自落各自目录;终端打表格汇总

报告顶部加一行:`**版本**: V{version} | **fileKey**: {fileKey} | **last_synced**: {date}`

---

## 工作流（评判镜头 · Lens B）

> **这是 Lens B（设计评判）的实现**,与上面两个 Lens A 工作流并列。规则**唯一真相源**是 V16 [`设计评判标准`](../../../jd-design-system-md-v16/ai-mechanism/design-judgment-standard.md)(智性设计四层链路第 4 层)。本节只编码**驱动流程**——怎么开 MCP、怎么采背景、按什么顺序判、输出什么结构——**不复制**标准里的规则表(7 维度 / 10 类页面校准 / 触发边界 / 组件检查项),用到时**指向**标准对应章节。
>
> 上游链路(为什么这么判):[哲学](../../../jd-design-system-md-v16/knowledge/philosophy/00-intellective-design.md) → [价值观](../../../jd-design-system-md-v16/knowledge/philosophy/values.md) → [原则](../../../jd-design-system-md-v16/knowledge/philosophy/principles.md) → 评判标准(本节消费)。

Lens B 有两个子流程,**按目标类型**(同「镜头选择」的判别)二选一:
- 目标是**整页 / 场域** → [B-1 场域页面评判](#b-1-场域页面评判完整)（完整）
- 目标是**单组件** → [B-2 组件评判](#b-2-组件评判轻量)（轻量）

### Step B0 — 稿面事实前置（两个子流程共用，必做）

> 评判标准 §4 硬约定:**「先确认稿面事实,再判断是否构成问题,最后才用设计哲学解释」**。不得跳过事实直接打哲学分。

1. **Relay 输入** → 复用「工作流(Relay 模式) Step 1」的 MCP 三件套(`get_screenshot` / `get_variables` / `get_design_metadata`,并行,限速同 Step 1)。
2. **design.md 输入** → `cat` design.md(+ bundle 文件),把正文/截图引用当稿面事实;若 frontmatter 有 `relay_source` 且 MCP 可用,可回拉截图佐证。
3. **MCP 完全不可用 + 无 design.md 正文** → **告知并退出**:评判强依赖看到真实稿面,无稿面事实会退化成空对哲学背书。不硬跑。

落一句**稿面事实摘要**(页面有哪些模块 / 关键字段 / 状态),后续每条判断都要能回指到这里。

### Step B1 — 背景输入采集（阻断式）

> 评判标准 §2.3 要求 `用户画像` + `需求背景` 作为判断优先级的依据。**缺则先问再评**(决策:不带假设硬跑)。

按以下顺序取背景,取到即停:
1. **design.md frontmatter** —— 若源是 design.md,先读 frontmatter 有没有 `用户画像` / `需求背景` / `audience` / `goal` 等字段。
2. **用户本轮输入** —— 用户可能已在 prompt 里给了画像/场景/改版原因/核心目标。
3. **都没有 → 向用户索取**,按 §2.3 字段清单问(精简版):
   - 用户画像:用户类型 / 核心诉求 / 决策关注 / 当前意图
   - 需求背景:页面场景 / 改版原因 / 核心目标(要提升的数据)/ 必须保留 / 主要约束(高度/露出等)
   - 告诉用户「可只给关键几项,留空我按通用电商用户判,但结论置信度会降」。

> **为什么阻断**:同一个页面,「给追求低价的比价用户」和「给冲动型内容用户」判出的重点牵引/信息动线问题完全不同。没有背景的评判是空的。

### B-1 场域页面评判（完整）

编码评判标准 **§2.2 的 8 步评审流程**。逐步驱动:

| 步 | 动作 | 指向标准 |
|---|---|---|
| 1 | 读背景输入(已在 Step B1 采到) | §2.3 |
| 2 | **识别页面类型**(首页/搜索/商详/购物车/结算/支付成功/订单售后/活动/AI 导购…) | §2.5 表首列 |
| 3 | **7 个核心维度**判任务路径是否成立:场景目标 / 信息动线 / 任务流程 / 重点牵引 / 信任建立 / 状态覆盖 / 系统一致 | **§2.4**(7 维度表:评审问题 + 对应价值观/原则 + 典型问题信号) |
| 4 | **调用该页面类型的场域评判重点**(场域能力 × 京东特色心智) | **§2.5**(10 类页面校准 + 示例检查项) |
| 5 | 输出**场域级问题** | §2.2-5 |
| 6 | 输出**组件级问题**(仅列影响页面任务的:icon/按钮/卡片/弹窗/标签…) | §2.2-6;明细判别走 B-2 |
| 7 | **问题分级 P0/P1/P2**(阻断任务 / 明显影响理解转化 / 体验优化) | §2.2-7 |
| 8 | 按「现状 → 影响 → 建议」组织,落报告 | §2.2-8 + §2.6 |

每条判断**必须先引稿面事实**(Step B0 摘要),再说违反哪条维度/价值观,最后给建议。**触发前过 §3 触发边界**——某维度存在 ≠ 机械输出同类问题(如纯展示页不报「状态覆盖」)。

### B-2 组件评判（轻量）

> 本期轻量:不在 skill 里重写每类组件的检查项明细(标准 §1 目前只展开了金刚区 icon / 系统功能 icon / 弹窗 / 商品卡·优惠券 4 类 + 「……」占位),而是**驱动 + 复用**。

1. **定位组件类型** → 查评判标准 **§1 组件评判表**:该组件承接哪些价值观/原则、场景化检查项示例。表里没有的组件类型 → 按「承接的价值观/原则 → 转译为检查项」的方法(§1「组件文档中的使用方式」)即兴转译,并在报告里标「该组件类型标准未展开明细,按方法即兴评判,建议回流补 §1」。
2. **统一度 / token 一致性这一条 → 复用 Lens A**:对组件节点跑「工作流(Relay 模式) Step 3」的 token 校验(3a-3e),把 Off-token / Naming-conflict 结果作为组件评判「统一度」维度的客观证据。**这是两个镜头唯一的交点**。
3. 输出按 §2.6「组件问题」段格式,分 P0/P1/P2。

### Step B-out — Lens B 输出结构

> **用评判标准 §2.6 的报告结构,区别于 Lens A 的 5 段式。** 落点沿用 `design-review-report.md` 契约:Relay 默认不落文件(显式 `--report-file` 或「落文件」才落),design.md / 整页落 `{同目录}/design-review-report.md`(覆写),终端打简短摘要(P0/P1/P2 计数 + 路径)。

```
## 设计评判 Review · `<nodeId 或 design.md 路径>`   ← Lens B 标识

> 本次按场域设计评判(Lens B);若要 token 合规走查,加 --token   ← 自动判成 B 时的护栏行

**镜头**:Lens B · 设计评判 | **页面类型**:<§2.5 某类> | **依据**:V16 设计评判标准

### 背景输入
<用户画像 + 需求背景摘要;若用户留空,标「按通用电商用户,置信度降」>

### 稿面事实
<Step B0 摘要:页面模块 / 关键字段 / 已画状态>

### 页面任务判断
<该页面主要帮用户完成什么任务;当前目标是否清楚>

### 用户路径判断
<进入页面后应按什么顺序理解→判断→行动;当前路径是否顺畅>

### 场域重点判断
<按页面类型调 §2.5 对应重点;是否体现京东核心商业优势>

### 主要问题(场域级 · P0/P1/P2)
<每条:现状(引稿面事实)→ 影响 → 建议;标维度 + 对应价值观/原则;标 P0/P1/P2>

### 组件问题
<仅列影响页面任务的组件问题(B-2);不做无关规范罗列>

### 修改建议
<可执行方向:信息前置 / 降低干扰 / 补充状态 / 调整 CTA / 补充依据>

### 需人工复核 🔺
<涉及业务策略 / 风险合规 / 用户权益 / 转化取舍 / AI 推荐边界的,一律列这,不由 AI 终判>
```

每条问题引用评判标准时给**仓库内路径 + GitHub blob URL**(与 Lens A 引用前缀表一致):
```
- 依据:[`design-judgment-standard.md` §2.4 信息动线](/jd-design-system-md-v16/ai-mechanism/design-judgment-standard.md)
```

### 人工复核红线（§4 硬约定）

以下一律进「需人工复核 🔺」段,**不出 AI 终判结论**:
- 业务策略 / 转化取舍(如「这个利益点要不要前置」涉及运营策略)
- 风险合规 / 用户权益(如价格、限制、风险表达的合规性)
- AI 推荐 / 自动化的边界(推荐依据、可控性、接管方式的产品决策)

取舍优先级:**组件规则 < 上层价值观 < 业务策略/合规/用户权益**。组件规则与价值观冲突 → 以价值观取舍;碰到后两类 → 标人工复核。

---

## 失败模式

### Relay 模式

| 现象 | 处置 |
|---|---|
| `get_screenshot` 返回 transport dropped | 串行重试 1 次;再失败就只用 variables + metadata 出报告,在「📋 无法判断」中说明缺截图 |
| `get_variables` 返回 `{}` | 节点不引用变量(可能纯绘图 / 旧设计稿)→ 标注无变量,报告章节降级到只看结构与字号(从 metadata) |
| `get_design_metadata` 输出 > 25k tokens | grep 不要全读,模式见下面"片段提取" |
| 用户给的 fileKey 不在已知 spec file 列表(V15 `1896756863949619202` / V16 `2029484645871009793`) | 仍可走 review:Step 2 按"其他"分支默认 V16 路径,失败回退 V15;报告顶部标注「**警告:此 fileKey 不在已知 spec file 列表,默认按 V16 真相源校验,如属其他业务文件请指明**」|
| V16 tokens.json 缺失 + V16 fallback snapshot 未提供 | Step 2 报错退出,提示用户先 clone 仓库或 follow-up 提供 V16 fallback |

### design.md 模式

| 现象 | 处置 |
|---|---|
| design.md 路径不存在或不可读 | 报错退出,提示 "未找到 {path},请确认相对仓库根的正确路径" |
| frontmatter YAML 解析失败 | 报错退出,在终端 echo 出有问题的几行供设计师修;不写 report 文件(避免覆盖已有 review) |
| frontmatter 缺 `relay_source.url` | Step 2 走兜底 V16 路径;报告 ❌ 段加一条"frontmatter 缺 relay_source.url,版本路由失效" |
| Bundle 模式有缺文件 | 缺哪个就跳过对应章节校验,❌ 段加"bundle_files 声明含 X 但文件不存在" |
| `references.uses_tokens` 空 / 缺整段 | 跳过 3b token 反查,⚠️ "design.md 未声明 uses_tokens,无法做反查正确性校验;建议补 frontmatter" |
| `design-review-report.md` 已存在 | 默认**全量覆写**(report 是产物,不该手改;手改的内容会被下次跑覆盖)。**写之前**报告路径放在终端摘要里,设计师如要保留旧版本应先重命名 |
| ~~V16 `spacing.*` 仅 `_v15_inherited` + `safe-area`~~ ✅ 已修(issue #36 / 2026-05-25) | V16 tokens.json 已加 7 阶 t-shirt(`spacing.{xxs..xxl}`),按 3b 正常反查;V15 双梯度语义 + 13 个 atom 数值仍可通过 `_v15_inherited` 继承 |

### 评判镜头(Lens B)

| 现象 | 处置 |
|---|---|
| 目标类型判不准(整页 vs 组件模糊) | **问用户**选镜头(Lens A token / Lens B 评判),不默认硬猜 |
| 缺背景输入(用户画像 / 需求背景) | **先问再评**(Step B1 阻断);用户坚持留空 → 按通用电商用户判,报告顶部标「置信度降,关键结论需人工复核」 |
| 给的是单组件却要求场域评判 | 提示「这是组件,场域页面评判不适用;转组件评判(B-2)/ 或给整页节点」 |
| MCP 不可用且无 design.md 正文 | **告知并退出**(Step B0):评判强依赖稿面事实,无事实会退化成空背书,不硬跑 |
| 组件类型不在标准 §1 展开明细内 | 按 §1「价值观/原则 → 检查项」方法即兴转译,报告标「标准未展开,建议回流补 §1」 |
| 用户问「这页符合设计哲学吗」但只给了 token 诉求的稿 | 评判与 token 是两个镜头,可同时跑:先 Lens B 评判 + 末尾附 Lens A token 摘要(或提示分别加 --judge / --token) |

### Metadata 片段提取(应对超大节点)

```bash
python3 - <<'PY'
import json, re
with open('<tool-results-file>') as f:
    xml = json.load(f)[0]['text']
# 颜色 hex
hexes = set(re.findall(r'#[0-9a-fA-F]{6,8}\b', xml))
# 长文本(中文描述)
texts = [t for t in re.findall(r'name="([^"]{15,500})"', xml)
         if any('一'<=c<='鿿' for c in t)]
print(hexes, texts[:20])
PY
```

---

## 引用约定

报告中引用 wiki 时:
- token 文件用文档链接(`tokens/typography.md` §X)
- 具体 token 用 BEM 命名(`color.brand.primary`、`radius.role.button`)
- Relay 节点用 `relay.jd.com/file/design?...&node_id=X:Y` 而非内部 ID,方便接收方直接打开

---

## 示例

- **Relay 模式**:[`examples/shop-review-half-sheet.md`](examples/shop-review-half-sheet.md) —— 对节点 `639:3394`(店铺评价半弹层)的完整走查。这是黄金参考输出。
- **design.md 模式**(bundle):[`/jd-design-system-md-v16/foundations/components-base/tabbar/design-review-report.md`](/jd-design-system-md-v16/foundations/components-base/tabbar/design-review-report.md) —— 2026-05-18 首跑产物。对 tabbar bundle(6 文件 page-doc)做完整 4 维校验,产出 2 ❌ + 8 ⚠️ + 多维 ✅。是 SKILL.md v0.6 修补的实战来源(3b atom 反查 / typography role 归一化 / bundle 数据源 / Step 1.4 反向指针 3 形式 / Step 3d Donts 上限按 mode 区分)。
- **design.md 模式**(single):[`/jd-design-system-md-v16/foundations/components-base/button/design-review-report.md`](/jd-design-system-md-v16/foundations/components-base/button/design-review-report.md) —— 2026-05-18 二跑产物,验证 PR4 修补效果。对 button single design.md(v0.1 draft)校验,产出 3 ❌ + 6 ⚠️。是 SKILL.md v0.7 修补的实战来源(3a slug 语义启发 / 3c 段在但内容空判定 / 3e single mode 内嵌 AI Schema / 失败模式 V16 spacing 真空)。
  > 两份都是**活产物**,以后跑会被覆盖。如需冻结样例,见本目录 `examples/` 或 git log。
- **评判镜头(Lens B)**:暂无样例(本仓惯例「示例来自真实跑」)。首次对真实 V16 场域页面(商详/购物车/结算)跑 Lens B 后,把产出冻结为 `examples/` 下首个评判样例。

---

## 与其他 skill / 工具的关系

| 工具 | 区别 |
|---|---|
| `mcp__zero-design__get_design_context` | 取设计 + 出参考代码;**不做合规判定**,本 skill 在其上加规则层 |
| `/security-review` | 安全审计,scope 完全不同 |
| `/review`(Claude Code 内置) | PR 评审,scope 完全不同 |
| `mcp__zero-design__create_design_system_rules` | 生成接入规则文档,**不做对单稿的审计** |
| `design-advisor` | **对新需求给前瞻设计建议**(还没画稿,给方向);本 skill Lens B 是**对已画的稿做评判**(已有稿,挑问题)。方向相反,可串:advisor 给建议 → 画稿 → design-review Lens B 评判 |

本 skill 输出的是「**对设计稿做的事**」,不是「**生成什么**」。

## 镜头速查

| | Lens A · Token 合规 | Lens B · 设计评判 |
|---|---|---|
| 查什么 | hex/字号/圆角/间距 在不在 token 白名单 | 页面/组件是否帮用户完成真实任务(体验) |
| 性质 | 机械、确定性 | 定性、要背景输入 |
| 真相源 | `tokens.json`(V15/V16) | [`design-judgment-standard.md`](../../../jd-design-system-md-v16/ai-mechanism/design-judgment-standard.md) |
| 自动判目标 | 单组件 / 组件 design.md | 整页 / 场域节点 |
| 显式触发 | `--token` / "走查 token" / "符合 16 吗" | `--judge` / "评审体验" / "任务路径" |
| 输出结构 | 5 段式(❌/⚠️/✅/📋/总结) | §2.6(任务判断→路径→重点→P0-P2→人工复核) |
