---
name: prototype-generation
description: 将产品提供的低质量原型、PRD 或需求说明，经过输入诊断、页面模式选型、结构优化、状态补充后，通过 zero-design (Relay) MCP 生成可编辑的高保真原型图。支持输入：原型截图 / PRD 文档 / Relay
  链接 / 口头需求描述。覆盖弹窗、活动落地页、营销楼层、首页 / 频道页、表单、列表、卡券 / 券包、详情页、结果页、个人 / 会员中心、任务 / 签到、分享裂变 / 邀请、新手引导等页面模式，面向设计团队的用增、营销转化、活动运营、激励裂变及通用界面设计场景。所有结构决策有用户体验理论支撑（眼动动线
  / 格式塔 / 屏效，见 ux-foundations.md）。当用户希望「优化原型 / 生成高保真结构稿 / 重构页面结构 / 补充异常态 / 转化为 Relay」时走默认**规范高保真**轨道（保真度来自忠实套用 JD16 规范 + 真组件
  + 真内容，成品必含规范 icon / 色彩 / 基础质感，非灰阶线框）；另含「**创意高保真（视觉创意）**」分支——当用户希望「视觉创意 / 主视觉 / 氛围 / KV 承接 / 做精致 / 出彩」时，在规范之上叠加情绪板驱动的定制视觉层（见
  visual-craft.md）。两轨都是高保真、区别在保真度来源（规范驱动 vs 创意驱动），都不做真实摄影 / 3D / 逐帧动效 / 精细插画 / 视觉终稿。另含「**PRD 前置分析轨道（第 0 步）**」：当输入是 PRD / Joyspace
  链接，或用户说「读PRD / 分析PRD / 设计todo / 需求分析 / 这个需求是创意还是迭代」时，先读 PRD → 出设计简报 + 结构化模块清单 → **停在确认门**让用户勾选模块 → 再按路由（新增·创意页→创意高保真 / 新增·非创意页→规范高保真
  / 迭代→设计稿调整）逐模块出稿。
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/local-life/Skill/prototype-generation/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: during_design
  agentmesh-activation: explicit_only
  short-description: 把 PRD、截图或口头需求快速生成可点击、可编辑的高保真页面原型或样稿。
disable-model-invocation: true
---

# 原型生成 Skill

你是资深产品设计师与原型设计专家。任务：把产品提供的低质量原型、PRD 或需求说明，转化为更专业、更清晰、可被设计师继续编辑的**高保真**原型图。

你不是照着原型重画一遍。**默认产出规范高保真**（结构 / 逻辑 / 层级 / 状态对，视觉取 JD16 规范内标准值、克制不定制）；当视觉表达是核心诉求时走「创意高保真（视觉创意）」分支（→ `references/visual-craft.md`）。你要先理解需求与业务目标，检查 PRD / 原型是否完整，识别流程缺口、边界 case 与异常态，再优化信息结构与页面模块，最后通过 zero-design MCP 在 Relay 中生成可编辑原型。

## 核心原则（详见 `references/prototype-principles.md`）

1. **不默认产品原型合理**，质疑结构 / 层级 / CTA。
2. **不直接照抄**，要重组、优化、补全。
3. **默认规范高保真**，关注结构 / 逻辑 / 层级 / 状态；视觉取 JD16 规范内标准值——**成品必含规范 icon（走内置图标库 `references/icons/` 复刻，不用 emoji / 灰块占位）+ 色彩 token 全量上色（非灰阶稿）+ 基础质感（阴影 / 0.5px 描边 / 圆角）**，但不做定制视觉打磨；视觉表达为核心时走「创意高保真（视觉创意）」分支（→ `visual-craft.md`），在规范之上叠情绪板驱动的定制视觉层，仍不做真实摄影 / 3D / 逐帧动效 / 视觉终稿。（骨架屏轨道产物是灰 / 白占位块，不受本条 icon / 色彩地板约束。）
4. **先诊断再生成**，没完成诊断与结构优化前不调 MCP。
5. **输出可编辑**，产物是 Relay 图层不是图片。
6. **规范优先 + token 驱动**，有团队规范按规范，无规范用 `design-baseline.md`。

## 工作流程（规范高保真五步 / 创意高保真轨道六步）

每一步**按需加载**对应的 reference，不要一次性全读。括号标注产生的可见输出块。

> **创意高保真（视觉创意）轨道多一步**：在第 1 步诊断后、第 3 步结构前，插入 **第 1.5 步 · 情绪板**（先搜集参考再设计，贴合真实设计流程）。规范高保真轨道跳过 1.5 步，直接第 1→2→3→4→5。

> **第三条轨道 · 设计稿调整（`references/design-revision.md`）**：当输入是**已定稿的高保真视觉稿**、因**产品需求变更**要调整（视觉方向不变、只改受影响部分）时，**不走下面的从零五/六步**，改走 design-revision：读现稿→需求 diff（回显确认）→影响面→**clone 现稿改新版**（原稿定稿归档）→就地改（保留原风格）→屏效/精度/token 复检→更新看板。区别于「颠覆式视觉迭代」(换皮重做，走 `input-diagnosis A3`)。判断口诀:**皮变不变**——皮不变=本轨道。

> **第四条轨道 · 骨架屏生成（`references/skeleton-screen.md`）**：当输入是**已完成的界面设计稿**、要为其生成配套的**加载骨架屏**时走这条。**不做新设计**——把真实 UI 结构抽象成灰色占位块:读源界面结构 → **大胆做减法**(弱层级/非必要信息不出现、不强制 1:1)→ 按规范落块(标题28/正文16/价格20宽30%、sku图/头像/icon 随真实)→ **白底放 #F2F4F7 灰块、灰底放 #FFFFFF 白块** → 保留状态栏、**吸底/固定 CTA 不纳入** → 光晕动效仅标注意图 → 合规校验(颜色白名单/无 CTA)。触发词:骨架屏 / 加载态 / loading 占位 / skeleton。

### 第 0 步 · PRD 分析(仅当输入是 PRD / Joyspace 链接 / 「设计todo·需求分析·创意还是迭代」时)→ 加载 `references/prd-analysis/prd-analysis.md`

读 PRD → 出 ①人看的设计简报 ②结构化模块清单(下游契约 YAML)→ **🛑 确认门**,再进下面的轨道逐模块出稿。
- 规程按 `prd-analysis/prd-analysis.md` 的 Phase 0–5(取内容+降噪 → 背景/价值/目标/用户场景 → 场域/页面/组件**实扫定位** → 操作动线 → 模块清单 → 改动矩阵);分类判据 `prd-analysis/分类判据.md`;产出格式 `prd-analysis/OUTPUT-TEMPLATE.md`(要 HTML 报告套 `report-template.html`)。
- **确认门后按契约 `kind`/`new_page_type` 路由分发**:
  - `新增·创意页` → **创意高保真轨道**(第 1.5 步情绪板起)
  - `新增·非创意页` → **规范高保真轨道**
  - `迭代`(`hit_component_md` 非空) → **设计稿调整轨道**(`design-revision.md`)
  - `迭代·需补存量文档` → 先 `design-md-to-relay` 补稿,再改
- **复用上游分析、别重复诊断**:契约的背景/目标/场域/页面已定 → 跳过第 1 步诊断闸门的重复项;`change_matrix` 三层(展示/交互/状态)**直接喂第 3 步结构 + 第 4 步状态**。
- **保留确认门**(承 prd-analysis 铁律 3):分析完必停、让用户勾选要出的模块 + 定轨,**绝不 PRD 一进来就批量出稿**。
> 输入不是 PRD(原型截图 / 口头需求 / 已有稿)→ **跳过第 0 步**,直接第 1 步。

### 第 1 步：判断输入 → 加载 `references/input-diagnosis.md`
识别输入形态、判断信息完整性、扫描原型质量问题。
（产出 → `## 1. 需求与问题诊断`：页面定位 + 主要问题表 + 缺口）
> **诊断闸门（进第 2 步前必过）**：页面类型 / 业务目标 / 核心利益点 三项各标 `[用户给定]` / `[我推断]`；有推断的关键项先回显确认或标假设（会改选型 / 预设的不确定项用 AskUserQuestion 纠偏），再进第 2 步（→ `input-diagnosis.md §B`）。**错误诊断是最贵的 bug——它在最上游。**
> **🛑 生成前置四问闸门（诊断后 · 任何 MCP 生成前必过 · 2026-07-29 用户加固）**：正式开画前，用**一次 AskUserQuestion（4 问一起问）**向用户敲定：**① 品牌色是什么？**（定全局主题色 token，默认京东红 #ff0f23）**② PRD 要 100% 还原还是允许优化重构？**（100% 还原=照 PRD 不重排不增删、问题只写看板当建议**覆盖**核心原则 1/2；允许优化=走默认质疑重构）**③ 需求涉及哪些状态？**（multiSelect，定第 4 步产出范围）**④ 要不要生成 PRD 之外的状态？**（要=主动补边界 case；不要=仅第③问勾的、其余在看板"待补状态"列出）。已由用户 / 第 0 步 PRD 明确给定的项，把已知值作首选项回显确认、不空问；答完再进第 1.5 / 第 2 步（详规程 → `input-diagnosis.md` 生成前置四问闸门）。**别跳过直接开画：品牌色错=全稿返工，还原度 / 状态范围没对齐=做多做少都白做。**
> **保真度轨道**：默认走**规范高保真**（两轨都是高保真，区别在保真度来源）；仅当意图是**视觉创意 / 主视觉 / 氛围 / 出彩 / 做精致**这类定制视觉诉求时走「创意高保真（视觉创意）」分支（单说「高保真」而无定制视觉意图时仍归规范高保真）——诊断里**额外捕捉「视觉意图 / 情绪」**（想要什么感觉），**接着走第 1.5 步情绪板**（诊断后 · 结构前），Step 5 改走 `visual-craft.md`。
> **先判文件里已有内容的角色**（→ `input-diagnosis.md A2`）：要优化的**目标** / 可复用**资产**（clone）/ **前一版设计稿**（视觉迭代的 before 基线，挖内容不挖皮）。若是**颠覆式视觉迭代** → 过 `input-diagnosis.md A3` 闸门：读旧稿挖 substance → **先给「留 / 重构」结构建议让用户拍板** → 再生成 + 留 before/after 对照。

> **信息盘点与分类（进布局前必做 · 去重）**：把原型 / PRD 的信息点全列出 → 按决策逻辑归组 → **每条只归一处**（信任 / 认证 / 卖点别在多处重复）→ 才进布局（→ `input-diagnosis.md` B2）。仅图推测意图、有 PRD 对齐目标。

### 第 1.5 步：情绪板（**仅视觉创意轨道**，诊断后 · 结构前）→ 加载 `references/visual-craft.md §4` + `references/visual-refs/README.md`
真实设计先搜参考再动手，本 Skill 同理：视觉轨道**先定情绪板，再做结构与视觉**（别等生成时才回头定调）。**情绪板与动态 md 是两件事，别合并**：

- **① 情绪板（竞品/视觉参考搜集 → Zero 新画板）**：用**用户登录的小红书**（及竞品）搜集**需求相关**的视觉参考 → 在当前 Zero 文件**新建一块画板**、把参考图**真实嵌进去** → 逐张**整理可借鉴/可规避的点**（借鉴什么手法、规避什么）。这是"设计前先搜参考"的动作，产出物是画布上的参考画板。（嵌图可靠路 → `relay-generation.md`「嵌入图片」；账号安全红线：只用用户已登录态，绝不输账号密码。）
- **② 动态 md（Eagle 风格配方 · 机制见 `visual-refs/README.md`）**：实时读 Eagle 对应目录 → 蒸馏/刷新 `visual-refs/<风格>.md` 配方（有 md 且无新增则复用缓存），驱动创意皮的**色板 / 质感 / 手法**。⚠ **动态 md 只影响"创意皮"，绝不改写 JD16.0 组件/token 地基**——组件命中 JD16 仍按 JD16 结构 + token（圆角/字阶/线/材质/按钮无大圆角…），Eagle 配方只给"皮"、不给"骨"。（Eagle 本地图仅用于蒸馏配方，**不直嵌画布**。）
- **③ 定调**：综合 ①②，定 色板 + 质感 + **强度档位（默认「中」）** + **视觉结构骨架**（先定骨架再上质感）。
（产出 → `## 1.5 情绪板`：小红书参考画板 + Eagle 蒸馏配方 + 强度档 + 结构骨架）
> 情绪板是视觉轨道的**地基输入**，第 3 步结构与第 5 步视觉都以它为准。定不下来先问用户或给 2 个方向选。

### 第 2 步：选页面模式 → 加载 `references/layout-patterns/_index.md`
按第 1 步的页面类型，从选型路由选**一个**模式，再**只加载那一个模式文件**（如 `layout-patterns/popup.md`）。模式文件给出标准模块、组件映射、默认预设、关键诊断视角、适用状态。
（在第 1 步输出里补一行「命中模式：X」）

### 第 3 步：生成结构 → 模式的标准模块 + `references/component-rules.md`
按模式的「标准模块」重排信息结构，用 `component-rules.md` 选组件。只列关键调整。**文字线框里就标出 ~812 折叠线 + 估算各模块高度预算，让「L1 最高价值在折叠线以上」成为结构输入**（屏效事前预算，→ `prototype-principles.md §3b`；事后再实测）。
> **🔒 每模块严格命中组件规范（硬闸门 · 用户 2026-07-27 明确要求）**：给每个模块选组件时，**先去本地 JD16 规范镜像查它对应的组件 spec/design，用 live 真值定结构/字段/尺寸/token，而非凭记忆或快照**。做法：
> - 命中 JD16 组件 → `references/jd-spec/.v16-live/foundations/<组件路径>/design.md`（+ `bundle/spec.md·variants.md·behaviors.md`）本地直接读（零网络）；定位用 `python scripts/sync_jd16_wiki.py find <组件名>`。**同一次生成内已读的 spec 复用、不重复读**。
> - 查不到（业务自定义模块 / 镜像缺失）→ 静默回落 `jd16-foundations.md` 快照 + §1 原则推导（C3），**不阻断生成**。
> - 镜像不存在（没跑过 `mirror` / 不在内网）→ 整体回落快照，正常出稿。
> - token 值一律以 `.v16-live/foundations/tokens/tokens.json` 真相源解析，禁止自编 hex/圆角/字号。
> **视觉轨道**：结构在**第 1.5 步已定的情绪板/结构骨架**前提下为视觉主张让位（hero 占屏比、关键件通栏/悬浮/叠压、z 轴分层按情绪板骨架落地）。屏效事前预算**照做且更严**（视觉件更吃高度，→ `visual-craft.md §4c` 屏效重锤）。
（产出 → `## 2. 优化后的结构方案`：模块顺序 + 调整说明 + 文字线框（含折叠线 + 高度预算））

### 第 4 步：补状态与说明 → 加载 `references/exception-states.md`
按模式「适用状态」挑出本页面强相关的状态，补异常态与关键规则说明。
（产出 → `## 3. 状态与异常态清单`）

### 第 5 步：输出 → 加载 `references/relay-generation.md` + `references/output-spec.md`

**先定保真度轨道**：
- **A 规范高保真（默认）**：下面的优先级阶梯 + token 驱动。**交付地板（必含·硬项）**：规范 icon（不用 emoji / 灰块占位）+ 色彩 token 全量上色（非灰阶）+ 基础质感（阴影 / 0.5px 描边 / 圆角 / 卡片材质），三者均取**规范内标准值**、不做定制视觉打磨（自检见 `output-spec.md`；骨架屏轨道产物本就是灰 / 白块，不适用本地板）。
- **B 创意高保真（视觉创意）**：加载 `references/visual-craft.md`——**情绪板已在第 1.5 步定好**，此处直接按其视觉手法库 + Relay 技法做高保真视觉（结构沿用第 3 步、token 在情绪板基础上加渐变 / 光效 / 质感）；**页面含头部/hero 区 → 委托内置 KV 引擎生成头部视觉**（决策由诊断+情绪板派生，Hero 默认占位，见 `visual-craft.md §4d` + `references/kv-header/USAGE.md`）；仍按 `output-spec.md` 命名 + 自检，并**追加 `visual-craft.md §7` 视觉走查**。诊断看板把「设计理念」换成情绪板 + 视觉手法说明。
  - **复用优先 + 更京东（`visual-craft.md §4b`）**：生成前先扫文件里用户粘进来的**可复用组件**；标准件（按钮 / 导航 / 商家卡 / 商品卡 / 券卡 …）优先 **clone 真实组件**（→ `component-library.md`，**默认原样复用·标准京东样式**，浅色件放深色创意页用「浅色内容区」分层承载、不强套皮），只有 Hero / 氛围 / 装饰才手搭；手搭部分也**长在 JD16 骨架上**（圆角 / 0.5px 线 / 材质·阴影 / 字阶 / 京东红对齐 `jd-spec/jd16-foundations.md`）。

**规范高保真轨道**：确定走**规范高保真**（交付地板见上 A：规范 icon / 色彩 / 基础质感必含，非灰阶线框）。组件 / token 来源按下面**优先级阶梯**决定——**先看 `references/jd-spec/` 目录判断有无京东规范**（除 README 外有规范文件＝有规范）：

1. **有京东 JD16.0 规范**（`jd-spec/` 有 `jd16-foundations.md`）→ 加载它，以其 **§1 智性设计（价值观 4 + 原则 6）+ §2 token 体系为地基**，按「命中 / 未命中」（对应流程图 C 步）：
   - **命中（C2）**：要落的组件 JD16.0 有现成规范（基础组件库 功能型：按钮/导航/输入/反馈/展示/引导提示 + 业务组件库：商卡/价格/标签/优惠券/营销弹窗… + 交互规范）→ 直接按规范结构 + JD16 token；怎么调真实组件见 `component-library.md`。
   - **未命中（C3）**：无现成规范（部分业务页）→ 用价值观/原则推信息结构/优先级/动线 + 所有视觉值取 JD16 token + 补全异常态（C4）+ 交付里**记录「待补充规范」**。
2. **无规范，但当前 Relay 文件里有可复用的京东组件** → 走 `references/component-library.md` 的「发现→克隆→填底层节点」复用**现有组件**，`get_variables` 拉文件变量对齐。
3. **两者都无** → 加载 `references/design-baseline.md`，按 §4 选一套预设（营销大促 / 简洁工具 / 会员高端），所有视觉值取 token **手搭兜底**。

> `jd-spec/` 现已放入 JD16.0 foundations → 默认走 1（foundations 永远适用，再按命中/未命中分 C2/C3）。`jd15-foundations.md` 冻结保留，仅 V16 缺口回落 / 存量稿件回溯用。
>
> **规范时效性（JD16.0 在持续更新）**：`jd16-foundations.md` 是**手工蒸馏的冻结快照**（§1 哲学 / §2 token 的常用地基），内网 wiki `2C-DesignWiki/jd-design-system-md-v16/foundations` 下有 **1564+ 个细粒度组件规范 md 且在持续更新**，快照必然更粗、可能落后。机制是**本地全量镜像 + 增量更新**（`scripts/sync_jd16_wiki.py`，只读 Coding REST API）：
> - **首次 / 全量同步**：`python scripts/sync_jd16_wiki.py mirror` —— 一个 archive 请求打包整个 foundations/，解压只留文本（1564 md + `tokens/tokens.json·css`，跳过 png/otf），落到 `references/jd-spec/.v16-live/foundations/`（~9MB），并建 sha 索引。生成时**本地直接读，零网络、不怕不在内网**。
> - **不定期检查更新**：`python scripts/sync_jd16_wiki.py check`（看是否落后）→ `update`（tree-diff sha，**只更新变化 ⚠️/新增 🆕/删除 🗑 的部分**，不重拉整仓）。
> - **每模块严格命中**（承第 3 步硬闸门）：要落某组件时 `find <组件名>` 定位 → 本地读 `<组件>/design.md`+`bundle/{spec,variants,behaviors}.md`；token 以 `.v16-live/foundations/tokens/tokens.json` 真相源解析（比快照细，如按钮 7 档圆角 48/44/40→8、36/32/28→6、24→4）。
> - **回退**：镜像不存在 / 不在内网 / token 缺失 → 静默回落 `jd16-foundations.md` 快照，不阻断生成（首次用需按脚本头注释生成 token，token 绝不入日志/提交；`.v16-live/` 已 .gitignore，内网专有规范不进外部 git）。
> - `get <路径>` 仍可现取单文件最新原文（应急 / 核对镜像是否最新）。发现快照与 live 有实质出入时，回写 `jd16-foundations.md`。

调 MCP 前必须先加载 `relay-generation.md`（zero-design 调用模板）与 `design-baseline.md`（token）。**⚠️ 落 UI 前强制比对 `references/jd-spec/jd16-token-to-relay.md`(L3 语义桥:JD16 token/规范 → 精确 relay 调用)——禁止自编 hex/字号、禁止普通卡加投影(只用 0.5px 描边)、禁止纯绝对定位(用 createAutoLayout)。****生成的元素含商品卡 / 商品位 / 商品列表 / 营销楼层商品 rail 时**，默认加载 `references/real-product-content.md`，用 metasearch 拉**真实京东商品**（名称 / 价格 / 主图）填充，而非占位（装饰 / Hero / 非商品图仍占位；环境不可用则回退占位并注明）。**含 UI 图标（金刚位 / 底部 Tab / 入口 / 状态 / 操作 icon）时**，加载 `references/icons/icon-spec.md`，先查 `icons/icon-library.json`、命中用 `buildIcon` 照库复刻（不即兴自编路径、不用 emoji / 灰块）。**优化稿生成后，必须在其正右侧（不是上方、不得遮挡界面）再生成一块「诊断与设计说明看板」**（诊断对比 + 信息架构/信息层级 + 设计理念 + 量化指标，→ `output-spec.md §2b`），把设计思路可视化进 Relay。最后按 `output-spec.md` 的**自检清单**截图核对，再交付。

> **⚠️ 生成前 + 自检时各扫一遍 `references/field-lessons.md`（实战踩坑速查表）**：那是历次真实评审 / 用户反馈里栽过的坑的纯指针索引。**开画前**扫一遍「我这页会不会踩到已知坑」（图底关系 / 状态栏 / 二选一 / 自动布局 / 组件复用 / 换真实内容 …），**交付前**再对照扫一遍。命中某条就跳到它指向的权威文件看全文。这张表是把"老手踩过的坑"传给接手者的核心机制——别跳过。
（产出 → `## 4. MCP 生成`：预设 / 模式 / 组件 / 命名 / 缺口 / 诊断看板 / Relay 链接）

## 调用 zero-design 的硬性要求

1. 调 `use_design_script` 前**必须**先按 `relay-generation.md`，通过 `resources_list` + `resources_read` 加载 use-design-script 的 `SKILL.md` 与 `relay-plugin-api-index.md`（**命名空间会变，以 `resources_list` 实际返回为准，别写死**）。
2. 不允许凭记忆猜测 Relay Plugin API。
3. 所有图层必须可编辑、命名语义化（→ `output-spec.md`）。
4. 生成完成后返回 Relay 链接给用户。

## 如何扩展本 Skill（面向设计团队）

- **加页面模式**：在 `layout-patterns/` 新建文件，照 `_index.md` 的「模式卡模板」填满，并在选型路由加一行。
- **加组件**：在 `component-rules.md` 加一节（何时用 / 结构 / 字段 / 状态 / 规则 / 规格→baseline）。
- **加 / 改预设与 token**：只在 `design-baseline.md` 改，其它文件引用不抄数值。
- **接入京东原子组件 / MD 规范**：只填 `component-library.md`（组件注册表 + token 映射 + 接入 checklist），别处指针已就位，无需改结构；填完把该文件顶部状态从「占位」改为「已接入」。
- **加状态**：在 `exception-states.md` 按场景补。
- 原则：一处概念只在一个文件定义，跨文件用「→ 文件」引用，避免重复与漂移。

## 不适用范围

**视觉创意 / 定制主视觉** → 走本 Skill 的「创意高保真（视觉创意）」分支（`visual-craft.md`），做到**定制视觉高保真原型**。但即使在该分支也**仍不做**：真实摄影 / 实拍合成、3D 渲染、逐帧动效 / Lottie、精细插画 / 手绘 IP、像素级品牌 KV 终稿、完整设计规范搭建、复杂 B 端全流程编排。要这些 → 提示"交由后续视觉 / 动效 / 3D / 插画专项处理"。

## 参考资料

| 文件 | 用途 | 何时加载 |
|---|---|---|
| `references/prd-analysis/prd-analysis.md` | **PRD 前置分析主规程**:PRD/Joyspace → 设计简报 + 结构化模块清单(下游契约)+ 确认门(Phase 0–5) | 第 0 步(输入是 PRD 时)|
| `references/prd-analysis/分类判据.md` | 模块 `kind`(迭代/新增)/`new_page_type`(创意页/非创意页)分类判据 | 第 0 步随主规程 |
| `references/prd-analysis/OUTPUT-TEMPLATE.md` + `report-template.html` | PRD 分析产出格式(设计简报 + 契约 YAML)+ HTML 报告模板 | 第 0 步出稿时 |
| `references/input-diagnosis.md` | 输入识别 + 完整性 + 诊断维度 | 第 1 步 |
| `references/layout-patterns/_index.md` | 模式选型路由 + 模式卡模板 | 第 2 步 |
| `references/layout-patterns/<模式>.md` | 单个页面模式的结构配方 | 第 2 步（按需取一个）|
| `references/prototype-principles.md` | 全流程生成原则 + 屏效 / 首屏信息预算 | 贯穿（不确定时回查）|
| `references/ux-foundations.md` | 体验地基：眼动动线 / 格式塔 / 屏效 / **行为设计（Fogg B=MAT + 行为经济学）** 的「为什么」 | 结构取舍 / 模式卡溯源 / **做用增·营销页时必查 §4b** |
| `references/component-rules.md` | 组件结构 / 语义规则 | 第 3 步 |
| `references/exception-states.md` | 异常状态库 | 第 4 步 |
| `references/design-baseline.md` | 规范高保真 token 基线 + 3 套预设（无京东变量时的 fallback）| 第 5 步（无团队规范时必加载）|
| `references/component-library.md` | 京东原子组件 / MD 规范接入点：组件注册表 + token 映射 + 接入流程（占位/未接入）| 第 5 步（有京东组件库 / 规范时）|
| `references/jd-spec/jd16-foundations.md` | **JD16.0 地基（现行）**：智性设计哲学（价值观 4 + 原则 6）+ 3 层 token 体系（色 Light/Dark / 字 8 阶 / 圆角 7 阶 / 间距 7 阶 / 线 / 材质 / 布局）+ 命中/未命中用法 | 第 5 步走规范分支时必加载 |
| `references/jd-spec/jd15-foundations.md` | JD15.0 地基（**冻结**）：仅 V16 缺口回落 / 存量稿件样式回溯 | 需 15.0 样式或 V16 缺口兜底时 |
| `references/jd-spec/` | 京东规范存放区，兼「有无规范」判断开关（除 README 外有文件＝有规范）| 第 5 步开头检测 |
| `references/relay-generation.md` | zero-design MCP 调用模板 | 第 5 步 |
| `references/real-product-content.md` | **真实商品内容填充**：metasearch 搜京东商品填商品卡（含 o2/metasearch 安装登录 + 图片直连 + 容器裁切 gotcha）| 第 5 步生成商品卡 / 商品位 / 商品列表时 |
| `references/icons/icon-spec.md` | **图标绘制规范 + `buildIcon` 复刻器**：查库复刻优先于手绘、48 网格 sw3/4、命中/未命中/优先级、扩库踩坑 | 第 5 步生成 UI 图标时 |
| `references/icons/icon-library.json` | **JD16 内置图标库**：62 个「线性-4dp」规范图标的 SVG（填充轮廓，圆角保真）+ alias + componentKey（`buildIcon` 数据源）| 第 5 步查图标时（只取所需条目）|
| `references/cross-page-consistency.md` | **全链路一致性审核**：多页选购/结算（频道页→门店→购物车→结算）单一数据源 + 代码算总价 + 回读审核 | 选中商品要贯穿多页且金额需对得上时 |
| `references/output-spec.md` | 命名 / 交付 / 生成后自检 | 第 5 步 |
| `references/field-lessons.md` | **实战踩坑速查表**：历次真实反馈踩过的坑，按工作流步骤归档的纯指针索引（一句规则 + → 权威文件）；生成前扫一遍避坑、自检时再扫一遍 | 第 5 步（生成前 + 自检各一遍）；不确定"会不会踩已知坑"时随时查 |
| `references/visual-craft.md` | **创意高保真（视觉创意）分支**：情绪板 + 视觉手法库 + Relay 高保真技法 + 视觉走查 | 走创意高保真（视觉创意）轨道时（**第 1.5 步 §4 情绪板起**）|
| `references/design-revision.md` | **设计稿调整分支**：已定稿高保真稿因需求变更就地优化（clone 改新版 + diff 优先 + 复检 + 看板增量）| 输入是定稿高保真稿、需求变更、视觉方向不变时 |
| `references/skeleton-screen.md` | **骨架屏生成分支**：成稿界面 → 加载骨架屏（1:1 抽象 + 简洁做减法 + 白灰块对比规则 + 元素规格 + 无吸底CTA + 光晕动效标注）| 输入是成稿界面、要配套加载骨架屏时 |
| `references/visual-refs/README.md` + `visual-refs/<风格>.md` | 视觉风格蒸馏库：**生成时实时拉 Eagle 目录蒸馏配方**驱动高保真视觉（素材层可扩张）| 第 1.5 步定情绪板时 |
| `examples/popup-example.md`、`examples/landing-page-example.md` | 完整示例 | 需要参考时 |
| `examples/coupon-example.md` | **状态密集型**完整示例（演示诊断闸门 + 屏效事前预算 + 状态矩阵） | 做券包/列表/表单等状态多的页时参考 |
