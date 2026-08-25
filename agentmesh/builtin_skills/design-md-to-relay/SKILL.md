---
name: design-md-to-relay
harness-version: 0
description: 按 wiki design.md 规范在 Relay/Zero 当前打开文件里实例化一份参考设计稿。流程是:先确认 scope → 同步 foundation(auto-pull upstream main + commit
  SHA 追溯)→ 读 wiki bundle + foundation 规则 → 归一化为机器可读 spec → 仅生成用户请求的 scope → 用 metadata + 截图自校验。补 V16 编辑面缺失的「md → Relay」反向。用于「按
  wiki 画一个 X」/「根据 design.md 生成 Zero 设计稿」/「生成对照设计稿」等请求。
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
  source: 2C-DesignWiki/.agents/skills/design-md-to-relay/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: during_design
  agentmesh-activation: explicit_only
  short-description: 按 wiki design.md 规范在 Relay/Zero 当前打开文件里实例化一份参考设计稿。流程是:先确认 scope → 同步 foundation(auto-pull upstream…
disable-model-invocation: true
---

# /design-md-to-relay · wiki → Relay 参考稿

按 JD 设计 wiki 的 markdown 规范,在 Relay/Zero 当前打开文件里实例化一份**参考设计稿**。

这是一个 **wiki-to-Relay 生成器**,不是专为 Tabbar 写的组件生成器,也不是创意设计助手。它的职责是「**忠实按用户请求的 scope 实例化 wiki 规范**」—— 不多,不少。

> ✅ **v0.2**（2026-07-23）—— Step 2-5（解析 / 读 bundle / 读 foundation / 归一化 spec）已由 `bin/build-spec.py` 实现，**offline 可跑**（不碰 Relay）。Step 6-10（探原版 / 画节点 / 取资产 / 验证）需 Relay 在线，仍待实现。上游阻塞 [issue #60](https://github.com/ShuaiMXu/jd-design-wiki-proposal/issues/60) P0 已解除。详见 [`README.md`](README.md) 路线图 + [`CHANGELOG.md`](CHANGELOG.md)。

## 核心准则:不要猜 output shape

在写任何东西到 Relay 之前,**先弄清用户想要什么**。

「画一个底导设计稿」这种话,可能是「**375×812 页面里放一个底导示意**」,**不是**「全状态变体规范板 / 多个示例 / 完整 spec page」。

scope 不清楚就**问一个简练的澄清问题**,然后等。

**不要**自作主张创建额外的变体、状态网格、解释性章节、业务内容或多个页面 —— 除非用户显式要求。

## 何时触发

用户说任何下列之一:

- 「**按 wiki 规范画一个 X**」
- 「**根据 design.md 生成 Zero 设计稿**」
- 「**把 X 组件实例化到当前 Relay 文件**」
- 「**生成对照设计稿给设计师比对**」
- 「**根据最新 wiki 画一个组件 / 页面**」

**不**适用场景:

- 设计师想从零创意,不基于 wiki
- 只是想改 / 写 wiki 文档
- 只是想 review 一份已经存在的 Relay 稿
- 用户明确要求「**从 wiki 生成,不要 clone 原稿**」时,坚持走本 skill

## 调用方式

```text
/design-md-to-relay <design-md-path-or-slug>
/design-md-to-relay <slug> --scope "single instance on 375x812 page"
/design-md-to-relay <slug> --canvas-position 3200,-760
/design-md-to-relay <slug> --no-pull              # 跳过 Foundation auto-pull(离线 / dev)
/design-md-to-relay <slug> --foundation-from <path>   # 用指定 wiki 路径(调试 fork / PR 分支)
```

如果用户没给明确路径,从请求里推断 slug,在本地 wiki 仓库下查找。

默认 wiki 位置:`~/code/jd-design-wiki-proposal`

仓库不在默认位置 → 先在当前工作区找,然后再问用户路径。

## 真相源原则

**不要把组件 `design.md` 复制进 skill 的 `references/` 目录**。

每次运行从源 wiki 仓库实时读组件 spec:

```text
jd-design-system-md-v16/**/<slug>/design.md
jd-design-system-md-v16/**/<slug>/spec.md
jd-design-system-md-v16/**/<slug>/variants.md
jd-design-system-md-v16/**/<slug>/behaviors.md
jd-design-system-md-v16/**/<slug>/ai-schema.yaml
jd-design-system-md-v16/**/<slug>/_assets-cdn.md
```

skill 的 `references/` 目录**只**放工作流文档、归一化 spec schema、adapter 注解、实现指引。**不能**变成 wiki 内容的镜像副本。

Adapter 可以描述「**如何把某个组件的 wiki 字段映射成 Relay 节点计划**」,但**不能**复制 wiki 全文。

## 来源优先级(Source Precedence)

```text
用户 scope
> ai-schema.yaml / spec.md 的结构化字段
> design.md 的显式字段
> foundation token + 视觉规则
> 组件 adapter 的默认值
> ground truth(原版 Relay 节点,只用来补缺失字段)
```

如果 ground truth 跟 wiki 显式字段冲突,**记录 diff,优先 wiki 字段**(除非用户显式要求「跟原版 Relay 节点对齐」)。

---

## Workflow · 10 步

### Step 0 · Clarify Scope · 确认 scope

在读 / 画之前,先判断用户的 output scope 是否清楚。

不清楚就**问一个**简练问题。常问的维度:

| 维度 | 例子 |
|---|---|
| 输出层级 | 单组件 / 组件放页面里 / 状态矩阵板 / 完整业务页 |
| 数量 | 一份实例 / 全部变体 / 仅选中态 |
| 画布 | 仅组件 / 375×812 手机页 / 已有页面里的某区域 |
| 内容 | label 文案 / 选中坑位 / icon 名 / 占位文案 |
| 自由度 | 严格 wiki only / 允许合理占位 |

**只问一个**简练问题。优先用:

```text
你要的是一个 X 放在页面里的示意，还是 X 的多状态规范展示？
```

用户答了窄 scope,就**保持输出窄**。「在 375×812 页面里放一个底导」 = 就**正好**这个,不是 spec 板。

### Step 1 · Sync Foundation · 同步 foundation

Foundation 是真相源,读之前先同步 upstream:

```bash
git -C ~/code/jd-design-wiki-proposal pull --ff-only origin main
```

记录 commit SHA 到输出 `foundationVersion.commit`,可追溯。

| 状态 | 处理 |
|---|---|
| ✅ fast-forward / up-to-date | `pullStatus = "success"` |
| ⚠️ 本地领先有 commit | **不强 reset**;用本地 + warn(报告 SHA + 原因)`pullStatus = "diverged"` |
| ⚠️ 网络故障 | 用本地缓存 + warn(报告 SHA + 上次 pull 距今多久)`pullStatus = "offline"` |
| ❌ 仓库不存在 | fail,提示用户先 clone |
| `--no-pull` | 跳过 pull;`pullStatus = "skipped"` |
| `--foundation-from <path>` | 用指定路径(调试 / fork 验证);`foundationSource = <path>` |

详见 [`references/foundation-token-table.md`](references/foundation-token-table.md)。

### Step 2 · Resolve Target · 解析目标

解析目标 `design.md`,接受三种输入:

- 绝对 / 相对的 `design.md` 路径
- 组件 slug(如 `tabbar` → 在 `jd-design-system-md-v16/**/tabbar/design.md` 查找)
- wiki URL

slug 匹配多个文件 → 列出候选,让用户选。

### Step 3 · Read Wiki Bundle · 读 bundle

读目标 bundle 的全部可用文件:

| 文件 | 用途 |
|---|---|
| `design.md` | 主组件规范、frontmatter、anatomy、尺寸、状态 |
| `spec.md` | 视觉字段细分(如有) |
| `variants.md` | 变体维度 |
| `behaviors.md` | 交互 + Donts |
| `ai-schema.yaml` | 机器可读真相源(如有) |
| `_assets-cdn.md` | 资产清单(SVG 优先 / PNG fallback) |

`ai-schema.yaml` 和 `spec.md` 比散文更结构化,**结构化字段优先**;散文只用来补缺,不能覆盖结构化字段。

### Step 4 · Read Foundation Rules · 读 foundation

读跟目标 wiki 版本相关的 foundation 来源:

| 来源 | 必要数据 |
|---|---|
| `foundations/tokens/tokens.json` | colors / radius / spacing / typography / effects |
| `foundations/visual/layout.md` | canvas / grid / layer / safe-area / 页面布局规则 |
| `foundations/visual/materials.md` | 材质 / 玻璃 / 模糊 / 阴影规则 |
| icon 文档 / 资产文档(如有) | icon box / 描边 / 选中态 / 默认态规则 |

生成稿里**每一个**字面视觉值应当:
- 反查到一个 token,**或**
- 来自组件 spec 显式声明,**或**
- 列入 `unresolvedLiterals`(供人工/上游决策)

### Step 5 · Build Normalized Spec JSON · 归一化 spec ⭐

**画之前**把 wiki bundle + foundation 规则转成机器可读 spec。

Normalized spec 是**执行契约**,必须包含:

- 用户请求 scope
- 画布尺寸 + 背景
- 节点树计划
- 组件尺寸
- 布局策略
- token 映射
- 文本规范
- 资产规范
- 要实例化的状态
- 验证断言
- 未解析字段 + 假设

详见 [`references/normalized-spec.md`](references/normalized-spec.md)。

**v0.2 起 Step 2-5 已可执行**：直接跑 `bin/build-spec.py <slug> --out spec.json` 产出归一化 spec（offline，token 反查复用 `tokens.json`）。散文里的字段解析、token 绑定、尺寸档抽取、wikiGap 静态发现都在脚本里，无需手动边读边归一化。

#### ⭐ Step 5.1 · 状态清单（page 级必做,#183 Round 1 加）

> **根因**:#183 首轮批次(2026-07-24)4 条里 3 条栽在「状态覆盖」维度——生成链**系统性只画理想态**,批次良品率仅 25%。因为此前 page scope 无状态字段,生成时从不被提示要画哪些状态。

**level: page 的整页生成,`build-spec.py` 会在 `scope.requiredStates` 带出该页面类型的必备状态清单**(来源 [`design-judgment-standard.md` §2.5](../../../jd-design-system-md-v16/ai-mechanism/design-judgment-standard.md))。生成前**必须**:

1. 读 `scope.requiredStates`(如商详 = 默认/售罄/不可购/加载;支付成功 = 成功/处理中/部分支付延迟)。
2. **逐个确认画不画**——至少产出 **主态 + 1 个关键异常态**;跳过某状态要在 `assumptions` 显式记原因,不静默只画理想态。
3. 列表/流式页天然带多状态卡(如订列),单实体页(商详/订详/支付成功)最易漏——**单实体页尤其要主动补异常态**。

> 判据:生成完按 `requiredStates` 自查一遍,「只画了理想态」= 未达 §2.4 状态覆盖 = 该页评测直接 P1 不合格。

**如果能写成归一化 spec,就不要从散文直接画**。

### Step 6 · Probe Ground Truth Only When Useful · 仅在有用时探原版

Ground truth = wiki frontmatter / 相关文档里引用的原版 Relay 节点。

**用它来做**:

- 补缺失的尺寸
- 理解原版 layer anatomy
- 检测 wiki 字段过时 / 不完整
- 生成 wiki gap 报告

**不要**用它来:

- clone 一份原稿(除非用户显式要求)
- 静默用原版数值覆盖 wiki 显式字段
- 扩大请求的 scope
- 忽视用户「不要用原稿 clone」类的指示

ground truth 跟 wiki 显式字段冲突 → 记到 `wikiGapsFound`,按上面的「来源优先级」走。

### Step 7 · Plan Relay Node Tree · 节点树规划

执行脚本**之前**规划节点树。

**布局规则**:

- **重复 / 分布 / 自然居中**的结构用 Auto Layout
- 用**固定 bounds**(`x/y + resize`)的场景:
  - 画布、设备页
  - 安全区
  - icon box
  - 固定尺寸 atom
  - spec 明确指定 bounds 的文本框
  - 浮层 / 出血锚点(如 Joy Agent `x=-16` 出血到屏幕外)
  - 从 SVG/PNG 导入的资产
- **不要全局禁用 x/y**。x/y 用于顶层放置 + spec 固定锚点
- 避免对**重复子节点**手动算 x/y

**文本规则**:

- spec 定义了固定文本框 → 设置 `textAutoResize = 'NONE'`,然后 `x/y` + `resize(width, height)` + alignment + font + line-height + characters
- 文本是 Auto Layout 内的自然内容,且 spec 没指定固定框 → 允许 auto-resize

**分层规则**:

- 视觉层 / 行为层 / 内容层在「**状态只影响一层**」(如选中态 bg ≠ icon+label)时**分离**
- 不要把选中背景 / 浮层 / mask 挂在内容节点上 —— 如果 spec 把它们视为独立视觉表面
- **不要**过度拆层 —— spec 把它们视为一体时不拆

### Step 8 · Fetch and Normalize Assets · 资产获取

资产优先级:

```text
SVG 源
> wiki 里的 vector path 数据
> PNG fallback
> placeholder + 显式 warning
```

**SVG 处理**:

- 用 `createFrameFromSvgAsync` 导入
- 归一化到指定的 icon / asset box 大小
- 确保导入的 SVG **不会**调整父节点尺寸
- 保留 fill / stroke 状态

**PNG 处理**:

- 仅作 fallback
- 标 `assetUsage.png_fallback`
- 把「应当有 SVG」记入 wiki gap

**所有视觉值强制走 token binding**:

- 任何 `fill` / `stroke` / `cornerRadius` / `fontSize` / `lineHeight` / `itemSpacing` / `padding*` 在 foundation 有对应 token 时**必须**反查绑定
- 直接传 hex / px 是 anti-pattern,记到 `tokenCoverage.unresolvedLiterals`

### Step 9 · Execute In Small Batches · 小批次执行

调用 `mcp__zero-design__use_design_script` 之前,确保 design-on-zero skill + Relay plugin API index 已就位。

**每个 script 单一逻辑操作**:

1. 创建根 canvas / 页面 frame
2. 创建主要容器
3. 加重复的子节点
4. 加文本和资产
5. 应用状态 + 最终固定 bounds

#### ⚠️ Step 9.1 · use_design_html 宽度校正（#215 问题3 · 实测支撑）

用 `use_design_html`(HTML → Relay 图层)生成整页时,html2schema **会按内容裁边**——请求 375 实际产出 **359**(2026-07-24 实测:4 条页面框架 + 专项验证均复现)。

**生成后必须校正**:拿返回的 nodeId,用 `use_design_script` `node.resize(canvas.width, node.height)` 把宽度锁回目标值(实测 `resize(375, h)` 可把 359 校正回 375)。

```js
// use_design_html 返回 { nodeIds: ["x:y"] } 后:
const n = await relay.getNodeByIdAsync("x:y");
n.resize(375, n.height);   // 校正 html2schema 裁边(359 → 375)
```

> 只影响 `use_design_html` 路径;直接 `use_design_script` 建 frame 不裁边。整页生成(375×812)务必校正,否则右侧留 16px 空缺、与 spec canvas 宽不符。

每个 script 都返回结构化数据:

```json
{
  "createdNodeIds": [],
  "mutatedNodeIds": [],
  "bounds": [],
  "warnings": []
}
```

报错就停,先修再继续。

### Step 10 · Verify · 验证

写完后:

1. 对创建的根节点跑 `get_design_metadata`
2. 跑 `get_screenshot`
3. 把实际 bounds 跟归一化 spec assertion 比对
4. 把 token 使用情况跟 token 映射比对
5. 报告 unresolved literals / 假设 / warnings / violations

容忍度:

| 字段 | 容忍度 |
|---|---|
| 固定尺寸 | 0.5 DP |
| 位置锚点 | 0.5 DP |
| 重复分布漂移 | 1 DP 总累计 |
| 颜色 | 精确 token 或显式 accepted literal |
| 圆角 | 精确 token 或显式 accepted literal |

发现可修复的 mismatch → 修完再返回最终结果。

详见 [`references/fidelity-thresholds.md`](references/fidelity-thresholds.md)。

---

## 输出契约(Output Contract)

返回一段简练人类摘要 + 一份结构化 JSON:

```json
{
  "createdRootId": "59:xxxx",
  "scope": {
    "level": "single-instance-on-phone-page",
    "canvas": "375x812",
    "states": ["selected-home"]
  },
  "foundationVersion": {
    "commit": "99c2e6f",
    "pulledAt": "2026-05-21T14:32:00Z",
    "pullStatus": "success",
    "remote": "ShuaiMXu/jd-design-wiki-proposal@main",
    "foundationSource": "~/code/jd-design-wiki-proposal/jd-design-system-md-v16/foundations/"
  },
  "source": {
    "designMd": "jd-design-system-md-v16/.../design.md",
    "foundationTokens": "jd-design-system-md-v16/foundations/tokens/tokens.json",
    "visualRules": [
      "foundations/visual/layout.md",
      "foundations/visual/materials.md"
    ]
  },
  "tokenCoverage": {
    "resolved": ["color_background", "color_primary", "radius_xxl"],
    "unresolvedLiterals": []
  },
  "assetUsage": {
    "svg": [],
    "png_fallback": [],
    "placeholder": []
  },
  "verification": {
    "passed": true,
    "warnings": [],
    "violations": []
  },
  "wikiGapsFound": []
}
```

`foundationVersion.commit` 是**追溯锚** —— 任何时候都能精确指出「这次跑动用的是哪一版 foundation」。

---

## 组件 Adapter

主 skill 是通用的。**组件特异性**逻辑放在 adapter 里。

Adapter 可以定义:

- scope 澄清问题模板
- anatomy 映射
- 默认节点树模式
- 状态模型
- 资产命名约定
- 验证断言

Adapter 路径示例:

```text
references/adapters/tabbar.md
references/adapters/button.md
references/adapters/toast.md
references/adapters/navbar.md
```

没对应 adapter → 走通用归一化 spec 流程;anatomy 不清楚时问 scope。

Adapter **不能**复制源 wiki —— 只编码「映射决策 + skill 内部默认值」。

---

## 不变约束(Guardrails)

- **不**把 wiki 组件 markdown 复制进 skill;运行时实时读
- **不**创建 spec page,除非用户要 spec page
- **不**全套变体,除非用户要全套
- **不**编造业务内容,除非 scope 要求页面化 + 用户允许占位
- **不** clone ground truth 节点,除非用户显式要求 clone / 对齐原版
- **不**静默用 ground truth 覆盖 wiki 字段
- **不**跳过 foundation token + 视觉规则
- **不**在有 Relay 工具时跳过截图 + metadata 验证就收工
- **不**全局禁用 `x/y`;它仍是顶层放置 + spec 锚点的标准做法

---

## 跟 upstream issue #60 的关系

本 skill 跟 [issue #60](https://github.com/ShuaiMXu/jd-design-wiki-proposal/issues/60) 是**互为产物**:

- **skill** = wiki gap 修复后的「正确做法」固化
- **issue** = skill 设计中暴露的「wiki 不闭合点」反馈

v0.2 实现依赖 issue #60 的 P0(Gap 1 + Gap 4)合并到上游。详见 [`README.md`](README.md) 路线图。

---

## 关联文档

| Doc | 用途 | 状态 |
|---|---|---|
| [`README.md`](README.md) | 状态 / 使用 / 路线图 / 上游依赖 | ✅ v0.2 |
| [`CHANGELOG.md`](CHANGELOG.md) | 版本变更记录 | ✅ v0.2 |
| [`bin/build-spec.py`](bin/build-spec.py) | **Step 2-5 可执行实现**（offline 归一化 spec） | ✅ v0.2 |
| [`references/normalized-spec.md`](references/normalized-spec.md) | 归一化 spec JSON schema + 示例 | ✅ v0.1 |
| [`references/samples/`](references/samples/) | 归一化 spec 黄金样本（button single） | ✅ v0.2 |
| [`references/foundation-token-table.md`](references/foundation-token-table.md) | Foundation auto-pull + token 反查协议 | ✅ v0.1 |
| [`references/fidelity-thresholds.md`](references/fidelity-thresholds.md) | 验证容忍度 + token 覆盖率规则 | ✅ v0.1 |
| [`references/adapters/tabbar.md`](references/adapters/tabbar.md) | Tabbar 适配器 + R3 蒸馏教训 | ✅ v0.1 |
| [`references/adapters/button.md`](references/adapters/button.md) | Button 适配器 + 尺寸档 / 样式 / 状态映射 | ✅ v0.2 |
