---
name: relay-spec-longpage
harness-version: 0
description: '把一个业务组件 / 页面的 design.md bundle（design.md + spec / variants / behaviors）铺成 Relay 端「业务组件类-XX设计规范」长图 —— 章节式（组件定义
  / 行为准则 / 基础结构&设计属性 / 典型场景 / 交互 / Donts / 错误示例），示例一律复用真实组件实例。 首选「克隆同文件已有规范模板 → 系统改写」法，1:1 还原 JD 视觉 token（#F2F3F7 演示卡 / 双色文字
  / 20pt 正文 / 表格）。当用户说「出 Relay 设计规范长图」「按 XX 模板写规范稿」「把这个业务组件做成规范页（Relay）」 「生成业务组件规范长图」「点评图文详情页 / 优惠券 / 沉浸式 的设计规范」时触发。 与 design-md-to-spec-page（对外
  HTML 4 要素页）互补：本 skill 出 Relay 设计师侧画布长图。

  '
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/.agents/skills/relay-spec-longpage/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
  short-description: 把一个业务组件 / 页面的 design.md bundle（design.md + spec / variants / behaviors）铺成 Relay 端「业务组件类-XX设计规范」长图 —…
disable-model-invocation: true
---

# /relay-spec-longpage · 业务组件 Relay 设计规范长图

> **输入** 组件 / 页面 bundle（design.md + spec/variants/behaviors）+ 它在 Relay 里的组件节点（放真实实例示例）。
> **输出** Relay 画布上一张 `业务组件类-{name}设计规范` 章节长图，对齐 JD 现有规范模板的视觉语言。

## 边界

| | |
|---|---|
| ✅ 做 | bundle / 组件 → Relay 设计规范长图（设计师侧、画布上、可直接评审 / 截图分享） |
| ✅ 做 | 克隆同文件已有规范模板改写，保证格式 / token / 配色 1:1 一致 |
| ✅ 做（委托 `ruler-annotation`） | §03 结构示意（内容标注）+ 设计属性·尺寸/间距（结构标注） |
| ❌ 不做 | 录入 bundle（→ `relay-to-design-md`）、封装组件集（→ `relay-component-set-architect` / `-variant-generator`） |
| ❌ 不做 | 对外 HTML 规范页（→ `design-md-to-spec-page`，4 要素网页，受众外部 / 跨职能） |
| ❌ 不做 | token 走查 / 合规审核（→ `design-review`） |

**两个产物别混**：本 skill 出 **Relay 画布长图**（受众设计师 / 评审）；`design-md-to-spec-page` 出 **HTML 规范页**（受众对外 / 跨职能）。两者同源于 bundle，通常都产，本 skill 只负责 Relay 这份。

## 触发

| 场景 | 处理 |
|---|---|
| 「出一份 X 的 Relay 设计规范长图」「按优惠券模板写 X 的规范」「把业务组件做成规范（Relay 画布）」 | 直接走本 skill |
| `relay-to-component-pipeline` 的 Phase 3 | 由 pipeline 委托本 skill |
| 只要对外网页规范 | 改走 `design-md-to-spec-page`（HTML），不走本 skill |

---

## 方法：克隆参考模板 → 系统改写（首选）

JD 设计文件里通常已有一份或多份「业务组件类-XX设计规范」长图（优惠券 / 沉浸式 / 框架介绍…）。**别从零搭**——克隆最贴近的一份系统改写，格式 / 字号 / 配色 / 章节节奏天然 1:1 一致。

```
1. 找参考模板     同文件扫「设计规范 / 范例示意」类长图节点，选骨架最贴近目标的一份
2. 克隆 + 暂名     clone → '__draft {name} 规范'，放参考稿右侧空地
3. 提取模板 token  按角色扒字号 / 字色 / 演示卡 fills / padding / 圆角（见 References）
4. 逐章改写文字    扫所有 TEXT，按角色映射改写为目标组件内容（双色分级，见「视觉规范」）
5. 重做设计属性章   模板 mockup 卡换成目标组件真实实例（createInstance + setProperties）
6. 表格 / 场景重建  该用表格的用真表格（auto-layout，非空格对齐），配色对齐参考稿
7. 改正式名 + 重排号 去 __draft；章节 48 号数字按位置重写 01..0N
8. 逐章截图自检    数据层是真相，截图按 node 缓存会滞后
```

> **fallback**：文件里没有可参考模板时才走 [`../relay-to-component-pipeline/references/relay-spec-page-build.md`](../relay-to-component-pipeline/references/relay-spec-page-build.md)（从零搭 + Relay 平台 gotcha 全集，本 skill 不重复）。

---

## 视觉规范（必须对齐参考模板）

> 完整数值 + 脚本骨架见 [references/reference-template-tokens.md](./references/reference-template-tokens.md)。

**文字双色分级** —— 最易踩错的「发灰 / 扁平」点：同一行内分两色，用 `node.setRangeFills(start, end, gray)` 逐行做（默认全深，冒号/破折号后转灰），别全 `#11141A`。

| 角色 | 颜色 |
|---|---|
| 序号 48 / 标题 24 Semibold / 子标题 20 Semibold / 「1）」「a. 标签：」前缀 / 表格首列 | `#11141A`（深） |
| 「：」「——」「→」之后的说明文字 / 表格数据列 | `#8D9199`（灰） |

**演示卡 / 排版**
- 演示卡（放实例的底）：fill `#F2F3F7` · 圆角 `0` · padding `40`（不是白底 / 不是圆角）。
- 字号：正文 / 结构化列表 20 Regular；子标题 20 Semibold；章节标题 24 Semibold；序号 48。
- 章节子块透明（`fills=[]`）文字坐白底；只有放实例的演示区才有 `#F2F3F7` 卡。
- 文本格式：「1）结构说明 / 2）设计属性 / 3）待治理项」+ `a. 标签：说明`，不是自定义六段式。

**哪些做表格** —— 长图里下列内容一律做成**真表格**（auto-layout，非空格对齐），结构化、好比对：

| 长图内容 | 列 |
|---|---|
| 03 模块「配置 / 限制」 | 模块(A/B/C…) / 配置 / 限制 |
| 03 设计属性 | 属性 / 值 / token（尺寸 · 间距 · 颜色 · 字体分组） |
| 04 典型场景 | 场景 / 状态组合（变体） / 备注 |
| 页面构成（页面级） | 区段 / 节点 / y 范围 / 说明 |
| 多端适配 · 性能预算 · 风险汇总（页面级） | 项 / 值或风险 / 处理 |

> **非表格**：01 定义 / 02 行为准则 / 06 Donts 用双色编号**列表**；03 结构示意、设计属性·尺寸/间距用真实例 + ruler-annotation 标注（见「§03 标注」），不是表格。

**表格样式**（配色对齐参考稿、不要 zebra 紫）：
- 表头行 fill `#F2F3F7` + 文字 `#11141A` Semibold；数据行白底；行间 1px `#EDEEF2`。
- 首列 `#11141A` Semibold，数据列 `#8D9199` Regular；圆角 0；16pt。
- ⚠️ **sizing 陷阱**：`resizeWithoutConstraints` 会把 auto-layout 主轴 sizing 重置成 FIXED → 表格塌成单行。sizing mode 必须在 **resize + appendChild 全部完成后**再设（`counterAxisSizingMode='FIXED'` 宽固定 / `primaryAxisSizingMode='AUTO'` 高 hug）。

---

## 章节骨架（7 段，沿用 JD 业务组件规范模板）

```
头部              克隆模板「设计系统文档头部」instance，改标题 + 部门署名（JD APP 16.0 GUIDELINE）
01 组件定义        一句话定义（取 design.md ## 一句话定义）+ 边界
02 行为准则        设计原则（取 design.md），双色编号列表
03 基础结构&设计属性 结构说明(a/b/c 必有/可选) + 真实例结构示意 + 模块「配置/限制」表 + 设计属性表
                   ★ 用真实实例替换模板 mockup 卡，放进 #F2F3F7 演示卡
                   ★ 两张图示委托 ruler-annotation（见「§03 标注」），不手搓引线 / 标尺
04 典型场景        按内容类别分组，每组复用实例 + 切变体（表格或卡片）
05 交互逻辑        编号交互；没标注的留 <TODO: 设计师补充>
06 设计禁止 Donts  双色编号反例
07 错误示例        可视化 ✗ 卡（改坏现有实例）+ ✗ 文字反例
```

> 页面级可补「多端适配 / 性能预算 / 风险汇总」段（真表格）。章节多寡按目标裁剪，但逻辑与参考模板一致，别擅自加减大段。

---

## §03 标注：委托 ruler-annotation

§03 两张图示不手搓引线 / 标尺，统一调 [`ruler-annotation`](../ruler-annotation/SKILL.md)。**复制目标组件模块成两份真实实例并置**（份① 内容标注、份② 结构标注，别叠同一实例 —— 引线+编号 与 盒型色块会互相糊），都放进 §03 `#F2F3F7` 演示卡：

| 份 | §03 子块 | 调用 | 形态 |
|---|---|---|---|
| 份① | 结构示意（由哪些模块组成，对齐结构说明 a/b/c） | 内容标注 | 编号圆 ①②③ + 灰引线 `#8D9199` + 模块名标签；可选 / 条件模块标灰 |
| 份② | 设计属性·尺寸/间距（量化边距 / 间距 / 尺寸） | 结构标注（**盒模型色块·模式 B**） | 半透明色块铺间距区（红 `#FF0F23` 大 `@0.30` / 蓝 `#0C82F7` 小 `@0.15`）+ chip；元素尺寸用线标尺补两侧 |

- **同源真实例**：标注叠在 `createInstance` 的真实实例上，不画示意图 / 不伪造实拍；两份编号 / 模块名与结构说明 a/b/c、变体 tile 一致（多处对照）。
- **双色按层级**：红=整体框架（外边距 / 主区块间距 / 主结构尺寸）、蓝=元素细节（小间距 / 行间距 / 单元素尺寸）；数字不带单位、无外框 / 四角 / 蒙层。
- **本场景结构标注用盒型（模式 B）**；单独研发交付才以 A 线标尺为默认。
- **几何走真实 bbox**：标注线起止 == 真实 `absoluteBoundingBox`，读回核对，不凭截图估。
- 内容标注答 What（由什么组成）、结构标注答 How much（多大 / 多远）；全部沿用 ruler-annotation 落地铁律，别另起一套（详见其 SKILL.md / spec §13.5）。

---

## 铁律 & 必查（落地前逐条过；不照做必翻车）

**方法 / 示例真实性**
- [ ] 已在同文件找到并克隆最贴近的规范模板（没有才走从零搭 fallback）。
- [ ] 03 / 04 示例全用目标组件真实实例（`createInstance` + `setProperties` 切变体 / 嵌套子实例 `visible` 切），无伪造实拍；缺图留位。

**视觉对齐**
- [ ] 文字双色分级（标签 `#11141A` + 说明 `#8D9199`，`setRangeFills`），未全深扁平。
- [ ] 演示卡 `#F2F3F7` / 圆角 0 / padding 40；子块透明文字坐白底。
- [ ] 正文 20pt、「1）结构说明 / 2）设计属性 / 3）待治理项 + a. 标签：说明」格式。
- [ ] 表格用真 auto-layout（非空格对齐），配色对齐参考（非 zebra 紫）。
- [ ] 视觉 / 方位以截图核对（角标方位、橙字 vs 填充 chip），未从图层名推几何。

**§03 标注**
- [ ] 复制两份实例：份① 内容标注（编号引线 + 模块名）、份② 结构标注（盒型，红大 / 蓝小 + 拉通），叠真实实例上、几何经 bbox 校验。

**Relay 平台 gotcha**
- [ ] 建表 sizing 在 resize + appendChild 之后设（否则塌单行）。
- [ ] 改 TEXT 文字前 `autoRename=false`；克隆文本节点改 `characters` 前先 `loadFontAsync(node.fontName)`。
- [ ] TEXT / VARIANT 属性重命名走 `editComponentProperty(旧key, {name})`，保 `#uid` 不删旧加新。
- [ ] 截图按 node id 缓存会滞后：截子节点 / 新建节点强制刷新，或以数据层（fills / 尺寸 / visible）为真相。
- [ ] 写画布铁律（本 skill 自身落实例也踩）：每个 `create*()` 先 `appendChild` 再设 x/y；复用已拿到的工作页 id，**绝不遍历 `setCurrentPageAsync`**（会切走客户端、之后全「找不到」）；`.parent` 可能是 GROUP，要挂到真正 PAGE。

**并发韧性**
- [ ] 每段动手前重解析依赖节点（组件按 node id 不按 name）；模板捐赠节点失效则回退到本 skill 已产出节点。

**收尾**
- [ ] 去 `__draft` 正名；章节号按位置重写 01–0N。
- [ ] 逐章截图自检（裁切 / 错位 / 黑屏 / 透明 / 文字重叠先修再继续）。
- [ ] 缺标注 / 缺交互处留 `<TODO>`，未脑补（见「内容三态」）。
- [ ] 与 bundle（design.md）+ HTML 规范页三处内容一致。

## 内容三态兜底（绝不脑补）

| 稿子状态 | 处理 |
|---|---|
| ✅ 有 | 忠实抽取，以截图渲染为准，不信残留命名 |
| ⚠️ 残缺 / 乱 | 给收敛建议 + 让设计师拍板，不静默替设计师决定 |
| ⛔ 缺（交互 / 跳转没标注） | 留 `<TODO: 设计师补充>` + flag，绝不伪造 |

## Confirm checkpoint

- 选模板后先告诉设计师「克隆哪份、为什么贴近」→ 确认再克隆。
- 逐章草稿（文案 + 用哪些实例做示例 + 缺口清单）汇总 → confirm → 才落画布。
- 中途可改方向 / 跳过 / 只补某章。

## References

| 文件 | 作用 |
|---|---|
| [references/reference-template-tokens.md](./references/reference-template-tokens.md) | 视觉 token 全集 + 双色 / 表格 / 演示卡脚本骨架 + 截图缓存等 gotcha（本 skill 核心） |
| [`../relay-to-component-pipeline/references/relay-spec-page-build.md`](../relay-to-component-pipeline/references/relay-spec-page-build.md) | 从零搭 fallback（donor-clone + 手动布局）+ Relay 平台 gotcha 全集 + 场景营销分类规则 |
| [`../ruler-annotation/SKILL.md`](../ruler-annotation/SKILL.md) | §03 标注产出：内容标注 + 结构标注（盒型 / 双色 / 拉通 / 落地铁律以其为准） |
| [`../relay-to-design-md/SKILL.md`](../relay-to-design-md/SKILL.md) | 上游：录入 bundle |
| [`../design-md-to-spec-page/SKILL.md`](../design-md-to-spec-page/SKILL.md) | 姊妹：对外 HTML 4 要素页（同源 bundle，不同受众） |
| [`../relay-to-component-pipeline/SKILL.md`](../relay-to-component-pipeline/SKILL.md) | 编排：业务组件全流程，Phase 3 委托本 skill |
| [`../../../.claude/shared/references/design-md-pipeline-sop.md`](../../../.claude/shared/references/design-md-pipeline-sop.md) | 全链路权威四段管线 |

## 版本历史

- **v0.4** · §03 改为「复制两份实例（份① 内容标注 / 份② 结构标注），结构标注用盒型」。
- **v0.3** · 重命名 `relay-spec-page` → `relay-spec-longpage`。
- **v0.2** · §03 两张图示委托 `ruler-annotation`（内容标注 + 双色结构标注），不再手搓引线 / 标尺。
- **v0.1** · 从 `relay-to-component-pipeline` Phase 3 提炼为独立 skill；核心方法定为「克隆模板 → 系统改写」，从零搭降级为 fallback。
