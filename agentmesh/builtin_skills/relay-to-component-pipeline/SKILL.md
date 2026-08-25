---
name: relay-to-component-pipeline
harness-version: 0
description: 业务组件全流程管线 —— 从一个 Relay 业务组件设计稿，一路产出 wiki bundle + 封装组件集 + Relay 设计规范长图 + HTML 规范页 + 校验。纯 orchestrator：每个 Phase
  都委托现有 skill（Phase 3 Relay 规范长图委托 relay-spec-longpage），自身只做就绪度预检 + 编排。每个 Phase 都是 confirm checkpoint，逐段用 sub-agent 起草，专门应对设计稿参差不齐。默认
  JD V16。Triggered by /relay-to-component-pipeline 或「走业务组件全流程」「把这个业务组件做成规范」「生成业务组件规范（bundle + 封装 + Relay 规范页 + HTML）」。
allowed-tools:
- Agent
- mcp__zero-design__get_design_metadata
- mcp__zero-design__get_design_context
- mcp__zero-design__get_screenshot
- mcp__zero-design__get_variables
- mcp__zero-design__use_design_script
- mcp__zero-design__resources_list
- mcp__zero-design__resources_read
- Bash
- Read
- Write
- Edit
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/.agents/skills/relay-to-component-pipeline/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: during_design
  agentmesh-activation: explicit_only
  short-description: 业务组件全流程管线 —— 从一个 Relay 业务组件设计稿，一路产出 wiki bundle + 封装组件集 + Relay 设计规范长图 + HTML 规范页 + 校验。纯 orchestrat…
disable-model-invocation: true
---

# /relay-to-component-pipeline · 业务组件全流程管线

> 一条龙：**Relay 业务组件设计稿 → bundle + 封装组件 + Relay 设计规范长图 + HTML 规范页 + 校验**。
>
> 本 skill 是**纯 orchestrator**：录入 / 封装 / Relay 规范长图 / HTML / 校验 / 上站**全部委托现有 skill**，不重写（Phase 3 已独立成 [`relay-spec-longpage`](../relay-spec-longpage/SKILL.md)）。自身只做 **Phase 0 就绪度预检 + 编排 + 逐段 confirm**。
>
> 全链路权威四段管线见 [`../../../.claude/shared/references/design-md-pipeline-sop.md`](../../../.claude/shared/references/design-md-pipeline-sop.md)；本 skill 在其上补「Relay 规范长图」一段，并串成单一入口。

## 设计理念

设计师的稿子**参差不齐**（命名残留 / 状态乱 / 没标注 / 并发改），硬套模板必翻车。所有设计围绕这点：**先体检**（Phase 0 预检暴露问题）→ **分段 sub-agent 起草**（每段读对应节点、抽取、标缺口）→ **逐段 confirm**（先给设计师看再落地）→ **三态兜底**（绝不脑补伪造，见下表）。

| 稿子状态 | 处理 |
|---|---|
| ✅ **有** | 忠实抽取，**以截图渲染为准**，不信残留命名（「变体3」「卖点信息」这种漂移名忽略，按截图文本走） |
| ⚠️ **残缺 / 乱**（重复态、营销混用、占位文案） | sub-agent 给**收敛建议** + 让设计师拍板，不静默替设计师决定 |
| ⛔ **缺**（交互 / 跳转没标注） | 留 `<TODO: 设计师补充>` + flag，**绝不脑补伪造** |

---

## 管线 6 段总览

| Phase | 做什么 | 委托给 | checkpoint |
|---|---|---|---|
| **0 就绪度预检** | sub-agent 扫全稿 → 各段 ✅/⚠️/⛔ 报告 + 范围确认 | （本 skill） | 设计师确认范围 |
| **1 录入 bundle** | Relay → design.md bundle（5 文件） | `relay-to-design-md` | bundle outline |
| **2 封装组件**（按需） | 多状态归纳成组件集 / 单组件扩变体 | `relay-component-set-architect` / `-variant-generator` | 封装计划 |
| **3 Relay 规范长图** | bundle → 业务组件类-XX设计规范 Relay 长图 | `relay-spec-longpage`（§03 标注 → `ruler-annotation`） | 逐段草稿 |
| **4 HTML 规范页** | bundle → spec-page.html（对外 4 要素页） | `design-md-to-spec-page` | — |
| **5 校验** | 规范符合性 + frontmatter + token | `design-review` / `bin/validate.sh` | 报告 |
| **6 上站**（可选） | 聚合进 docs/design.html 总站 | `design-md-to-portal` | — |

> 调用：`/relay-to-component-pipeline <relay_url>`。默认从 Phase 0 起逐段走；`--from <phase>` 从某段续跑（如 `--from 3` 只补 Relay 规范长图）。

---

## Phase 0 · 就绪度预检

派 **1 个 sub-agent**（只读）用 `get_design_metadata` + 分段 `get_screenshot` 扫整稿，对各维度打分 `✅ 完整 / ⚠️ 残缺 / ⛔ 缺失`：组件定义 / 业务边界、基础结构（必有 / 可选模块）、变体齐全度 + 命名漂移、典型场景覆盖、交互 / 跳转标注、节点规模是否超限。

产出**就绪度报告** + 建议范围（哪些段能建、哪些要设计师先补 / 拍板）。**停在此等设计师确认范围**再进 Phase 1。

> `⛔` 只留给「节点规模严重超限 / 整稿无法定位」这类致命情况；命名 / 标注 / 截图等模糊维度一律 `⚠️` 不阻断（沿用 relay-to-design-md preflight-gate 思路）。

## Phase 1 · 录入 bundle（委托 `relay-to-design-md`）

`relay-to-design-md <relay_url>`（outline 模式 → 确认 → `--confirm-outline` 落 bundle）。产物：`{slug}/` 下 design.md + spec.md + variants.md + behaviors.md + CHANGELOG.md（+ preview.png）。token 反查 / frontmatter / 路径规则 / 切图侦测全由该 skill 负责，本 skill 不重复。

## Phase 2 · 封装组件（按需，委托）

仅当 Phase 0 发现「多状态待归纳 / 状态乱待收敛」时：多个已画状态 → `relay-component-set-architect`；单基础组件扩状态 → `relay-component-variant-generator`。

**收敛冗余必须先出封装计划 + 设计师拍板**（如 `默认 + 沉浸式 + 变体3` 收敛为 `形态={标准,沉浸式}`）；动结构前全文件扫实例引用评估影响面（共享件绝不乱改）。产物（组件集 node + 形态轴 + 暴露子组件集）会被 Phase 3 规范页 + Phase 1 variants.md 同步引用，三处一致。

## Phase 3 · Relay 设计规范长图（委托 `relay-spec-longpage`）

bundle → 一份 `业务组件类-{name}设计规范` 的 Relay 章节长图（7 段，示例复用真实组件实例），**参照同文件已有规范模板克隆改写**（如 `464:3875` 优惠券 / `464:3816` 框架介绍 / `2250:1571` 沉浸式）。

- **执行细则以 [`relay-spec-longpage`](../relay-spec-longpage/SKILL.md) 为准**（克隆改写法、双色文字、`#F2F3F7` 演示卡、**哪些章节做真表格**、建表 sizing 顺序、截图缓存 gotcha…全在它 + [reference-template-tokens.md](../relay-spec-longpage/references/reference-template-tokens.md)）；本 skill 不内联，避免方法漂移。
- **§03 标注委托 [`ruler-annotation`](../ruler-annotation/SKILL.md)**：**复制组件模块成两份实例** —— 份① 内容标注（①②③ 引线 + 模块名）、份② 结构标注（**盒模型色块**，红大 / 蓝小 + chip），叠在演示卡里的真实实例上，不手搓引线 / 标尺。
- **从零搭 fallback**（无可参考模板时）：[references/relay-spec-page-build.md](./references/relay-spec-page-build.md)（+ Relay 平台 gotcha 全集）。

## Phase 4 · HTML 规范页（委托 `design-md-to-spec-page`）

同一 bundle → `spec-page.html`（对外 4 要素页 + Pro/Basic 切换 + V16 token CSS）。与 Phase 3 的 Relay 长图是**两个产物、两个受众**（对外网页 vs 设计师画布），都产出、同源于 bundle。

## Phase 5 · 校验（委托）

- `design-review`：规范符合性（color / typography / radius / spacing / icon / token 反查 + frontmatter + section 完整度）。
- `bin/validate.sh {slug}/design.md`：frontmatter / 受控词表 / slug / relay URL / preview.png。

> `status` 升到 `review` 前必须清掉 ⚠️ / TODO（draft 阶段允许残留）。

## Phase 6 · 上站（可选，委托 `design-md-to-portal`）

把新组件聚合进 `docs/design.html` 16.0 GUIDELINE 总站。

---

## Sub-agent 调度约定

- Phase 0 预检 = 1 个 sub-agent（只读，出报告）。
- Phase 3 逐段起草 = 每段 1 个 sub-agent，段间独立并行，**只起草不写画布**。
- sub-agent 产出 = **结构化草稿 + 缺口清单**，不是直接成品。
- 任何「动 Relay 画布 / 改组件结构」的写操作都在**主流程串行**执行（避免多 agent 并发写 Relay 撞车）。

## 横切铁律 & 必查（贯穿各 Phase，落地前逐条过）

**编排**
- [ ] 每个 Phase 都是 confirm checkpoint，不一次性糊完；可改方向 / 跳过 / `--from` 续跑。
- [ ] 不重写已有 skill：所有 Phase 均委托（含 Phase 3 → `relay-spec-longpage`），本 skill 只编排 + Phase 0 预检 + confirm。

**内容真实性**
- [ ] 三态兜底：有→抽取、残缺→收敛建议 + 拍板、缺→`<TODO>`，绝不伪造。
- [ ] 示例 / 典型场景 / 错误示例一律复用现有组件实例（`createInstance` + `setProperties`），不伪造实拍图，缺图留位。
- [ ] 视觉 / 方位以截图为准，不从图层名推几何（角标方位、橙字 vs 填充 chip 必须 `get_screenshot` 核对）。

**领域规则**
- [ ] 营销信息按 内容 / 种草 / 点评 / 直播 分类：种草数 / 种草商卡 / 话题仅种草类（点评类可用种草营销行），纯内容类不透出种草与话题，直播类配直播营销（预约 / 榜单 / 关注 / 直播券）；价格 / 名称数字用京东正黑 V2.3。

**并发韧性**
- [ ] 每段动手前重解析依赖节点（按 node id 不按 name）；捐赠源失效有回退。

**产出 gate（提交前）**
- [ ] bundle 5 文件齐 + `validate.sh` 过。
- [ ] 封装（如有）出过计划 + 拍板 + 扫过实例引用影响面；封装后下游实例已验证未脱挂（截图）。
- [ ] Relay 规范长图 7 段齐、章节号 01–0N；§03 复制两份实例 + 内容 / 结构标注（详见 `relay-spec-longpage`）。
- [ ] HTML 规范页已产出，与 Relay 规范页同源。
- [ ] 组件结构（Relay）↔ bundle md ↔ 规范页 **三处一致**（封装 / 改名后同步）。

## References

| 文件 | 作用 |
|---|---|
| [`../relay-spec-longpage/SKILL.md`](../relay-spec-longpage/SKILL.md) | **Phase 3 执行**：bundle → Relay 设计规范长图（克隆模板改写；哪些章节做表 / 双色 / 演示卡 / gotcha） |
| [`../ruler-annotation/SKILL.md`](../ruler-annotation/SKILL.md) | **Phase 3 §03 标注**：复制两份实例 → 内容标注 + 结构标注（盒型 / 双色 / 拉通） |
| [references/relay-spec-page-build.md](./references/relay-spec-page-build.md) | Phase 3 **从零搭 fallback** 脚本骨架 + Relay 平台 gotcha 全集 |
| [`../relay-to-design-md/SKILL.md`](../relay-to-design-md/SKILL.md) | Phase 1 录入 |
| [`../relay-component-set-architect/SKILL.md`](../relay-component-set-architect/SKILL.md) / [`../relay-component-variant-generator/SKILL.md`](../relay-component-variant-generator/SKILL.md) | Phase 2 封装（**已 vendor**，见各自 `VENDOR-NOTICE.md`；多状态→architect、单组件→variant-generator） |
| [`../design-md-to-spec-page/SKILL.md`](../design-md-to-spec-page/SKILL.md) | Phase 4 HTML 规范页 |
| [`../design-review/SKILL.md`](../design-review/SKILL.md) | Phase 5 校验 |
| [`../design-md-to-portal/SKILL.md`](../design-md-to-portal/SKILL.md) | Phase 6 上站 |
| [`../../../.claude/shared/references/design-md-pipeline-sop.md`](../../../.claude/shared/references/design-md-pipeline-sop.md) | 全链路权威四段管线 |

## 版本历史

- **v0.4** · §03 改为复制两份实例（份① 内容标注 / 份② 结构标注用盒型）；结构化重写 —— 合并重复的「核心理念 / 五条铁律 / 关键约束 / 必查清单」为「设计理念 + 横切铁律&必查」，删 Phase 3 changelog 旁白，版本史压成一行。
- **v0.3** · Phase 3 委托目标 `relay-spec-page` → `relay-spec-longpage`；改「唯一新逻辑」陈述为纯 orchestrator；删 Phase 3 冗余内联 3.1–3.4。
- **v0.2** · Phase 3 §03 标注耦合 `ruler-annotation`（内容标注 + 双色结构标注）。
- **v0.1** · 业务组件全流程串成单一 orchestrator skill（录入 → 封装 → Relay 规范长图 → HTML → 校验 → 上站）。
