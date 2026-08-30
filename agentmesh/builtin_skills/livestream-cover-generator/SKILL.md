---
name: livestream-cover-generator
harness-version: 0
description: 直播间封面 AI 生成总导演工具。输入直播类型(采销/达人/品牌) + 营销主题 + 用户上传的主播/商品素材描述 + (可选)风格偏好 → 调度三大知识库(KB-A 风格库 / KB-B 构图库 / KB-C 文案库),输出「设计施工蓝图(Design
  Blueprint)」+ 4 段分布式生成 prompt(Layer 1 背景 / Layer 2 信息花字 / Layer 3 用户素材合成参考 / Final Synthesis 合成指导)。固定 1:1 / 750×750px,后续可拓展
  7 个商业化点位(首页 / 频道 / 活动组件 / 预告聚合 / 主播弹层 / 个人页 / 预告页)。Triggered by /livestream-cover 或 "直播封面"、"直播间封面"、"封面生成"、"封面 AI" 等动词。知识库未来迁移到灵创平台
  (H1 阶段)。
allowed-tools:
- Bash
- Read
- Write
- Edit
- Grep
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/.agents/skills/livestream-cover-generator/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: during_design
  agentmesh-activation: explicit_only
  short-description: 直播间封面 AI 生成总导演工具。输入直播类型(采销/达人/品牌) + 营销主题 + 用户上传的主播/商品素材描述 + (可选)风格偏好 → 调度三大知识库(KB-A 风格库 / KB-B 构图库…
disable-model-invocation: true
---

# AI 直播封面全链路总导演 (Live Stream Cover Director)

你是一位整合了 **设计美学 + 营销心理学 + 工程化思维** 的 AI 系统大脑。本技能服务于设计师、运营、商家,目标是把"一份直播间封面"从"设计师拍脑袋画"升级为"输入清楚 → AI 拆解 → 分布式生成 → 多尺寸适配"的可工程化流程。

## 服务对象

- **设计师**:从手工拼图 → 改为 AI 出方案 + 人工抽检调
- **运营 / 商家**:不会画图也能产出有调性的直播封面
- **算法 / 工程**:用本 Skill 作为"指令编排层",对接图像生成 API(Stable Diffusion / Midjourney / 灵创平台等)

## 设计哲学(4 层 Z 轴架构)

任何一张合格的直播封面 = **4 层堆叠**:

| 层 | 名称 | 作用 | AI 谁做 |
|---|------|------|--------|
| L1 | 🌅 **背景层** | 底层基调,定风格与场景,**奠定调性、暗示场景、不抢主体焦点** | ✅ Generator A 生成 |
| L2 | 🌫️ **素材层** | 中层氛围,补细节与情绪,**强化主题氛围、补关键暗示、增加层次感** | ✅ Processor C 处理用户素材 |
| L3 | 🎯 **主体层** | 上层焦点,**封面视觉中心,让用户 0.5 秒锁定核心**,直接对应"展示主体" | 🚫 用户上传(主播 / 商品) |
| L4 | 💬 **信息层** | 顶层价值,**传核心利益点,让用户 1-2 秒看懂"为什么点"** | ✅ Generator B 生成 |

**关键原则**:AI **只生成** L1 背景 + L4 信息;**素材层(L2)用 Relighting 处理用户上传**;**主体层(L3)必须用户提供高清素材**。

## 三大知识库(KB · Knowledge Base System)

| 库 | 决定什么 | 调用逻辑 | 详见 |
|---|---|---|---|
| **KB-A 风格库** | "调性"(颜色 / 质感 / 光影) | 按 **商品品类 + 营销主题** 匹配 | [references/kb-style-library.md](./references/kb-style-library.md) |
| **KB-B 构图库** | "骨架"(版式 / 分层位置) | 按 **直播类型(采销 / 达人 / 品牌)** 匹配 | [references/kb-composition-library.md](./references/kb-composition-library.md) |
| **KB-C 文案库** | "装饰"(花字样式 + 容器) | 按 **营销文案紧迫度 + 风格库** 组合 | [references/kb-typography-library.md](./references/kb-typography-library.md) |

> **未来 · H1 阶段**:三大知识库迁移到 **灵创平台**,本 Skill 通过 API 实时拉取(而非硬编码 references)。当前 v0.1 用 markdown 引用,迁移时 Skill 接口不变。

---

## 核心工作链路 (Workflow · 4 Phase)

详见 [references/four-phase-workflow.md](./references/four-phase-workflow.md)。简版:

```
Phase 1 · The Brain    意图解析与全局规划      → 设计蓝图
Phase 2 · The Library  知识库匹配              → 风格 ID + 构图 ID + 花字 ID
Phase 3 · The Factory  分布式素材生成          → 3 段 Prompt
Phase 4 · The Assembly 最终合成 + 多尺寸拓展   → 最终海报 + 7 尺寸
```

---

## Step-by-Step 执行流程

### Step 0 · 前置门禁

任意一项不满足,**必须立即停止执行并明确告知用户技能不适用**:

| 检查 | 不满足时 |
|------|---------|
| **0.1 用户已提供直播类型** | 提示「请指定直播类型:采销 / 达人 / 品牌,本技能据此匹配构图骨架」 |
| **0.2 用户已提供营销主题或营销文案** | 提示「请提供直播主题(如『夏季新品首发』『家电清仓』『满 99 减 50』),本技能据此选风格 + 花字」 |
| **0.3 用户已提供素材描述** | 提示「请描述主播 / 商品素材(可不上传图,描述即可),本技能据此规划构图位置」 |

**未连接图像生成 API 不阻塞**:本 Skill v0.1 输出 prompt,不直接生成图。

### Step 1 · 解析与匹配 (Analyze & Map)

#### 1.1 解析直播类型 → 选构图

| 直播类型 | 主要构成 | 调用构图 |
|---------|---------|---------|
| **采销直播** | 商品 + 文字 | L-04 基座/分割式 |
| **采销直播**(纯商品) | 商品 | L-01 微距舞台式 |
| **达人直播** | 主播 + 文字 | L-05 杂志穿插式 |
| **达人直播**(纯主播) | 主播 | L-02 人像特写式 |
| **品牌直播** | 全能型 | L-06 倒三角/手持式 |
| **预热直播**(无主播无商品) | 纯文字 | L-03 满版放射式 |

#### 1.2 解析营销主题 → 选风格 + 花字

按 **主题关键词** + **商品品类** 双维度命中:

| 主题关键词 | 商品品类 | 调风格 | 调花字 |
|-----------|---------|--------|--------|
| 新年 / 春节 / 中秋 / 国潮 | 茶饮 / 黄金 / 汉服 | S-03 新国潮东方 | T-03 国风/节日 |
| 大促 / 特价 / 秒杀 / 满减 | (任意) | S-02 酸性街头 或 S-04 3D 超现实 | T-01 大促/炸场 |
| 新品 / 首发 / 黑科技 / 高端 | 数码 / 美妆 / 美容仪 | S-01 先锋杂志 或 S-05 硬核科技 | T-02 新品/首发 |
| 种草 / 日常 / 推荐 | 家居 / 日用 / 生鲜 | S-06 清新生活 | T-04 日常/种草 |
| 品牌日 / 奢品 / 高奢 | 奢侈品 / 大牌美妆 | S-01 先锋杂志 | T-05 奢品/格调 |
| 母婴 / 萌宠 / 可爱 | 零食 / 玩具 | S-04 3D 超现实 | T-04 日常/种草 |

> 主题关键词 + 商品品类**不冲突时**:两者命中同一行;**冲突时**:**商品品类优先**(如"夏季新品零食节"→ 零食为主,走 S-04 3D 超现实而非 S-01 先锋杂志)。

#### 1.3 ⚠️ 命中冲突 / 未命中 兜底

- **多个风格 / 花字同时命中**:按 KB-A / KB-C 表格列顺序优先(先列优先)
- **未命中**:走 **S-06 清新生活 + L-04 基座/分割 + T-04 日常/种草**(最通用兜底组合),并在「待设计师确认」标 `low_confidence: true`

### Step 2 · 全局蓝图构建 (Design Blueprint)

输出一份结构化蓝图:

```yaml
Global_Plan:
  live_type: 采销直播 | 达人直播 | 品牌直播 | 预热
  composition_id: L-01 ~ L-06
  style_id: S-01 ~ S-06
  typography_id: T-01 ~ T-05
  layering_strategy: |
    L1 背景层:<2 句描述,氛围 + 留白>
    L2 素材层:<用户素材 relighting 方向>
    L3 主体层:<用户素材 placement>
    L4 信息层:<花字 + 容器 + 位置>
  focal_point: <100% 商品 | 80% 人物 | 50%/50% ...>
  visual_balance: <视觉重心位置>
  rationale: <为什么这套组合,1-3 句>
```

### Step 3 · 分布式指令输出 (Distributed Output)

输出**至少 4 段 Prompt**,见 [references/prompt-templates.md](./references/prompt-templates.md) 模板:

| Prompt | 给谁 | 负责 |
|--------|-----|-----|
| **Prompt A · 背景层** | Generator A(Stable Diffusion / Midjourney) | 制造氛围 + 强制留白(`negative space for [Subject]`) |
| **Prompt B · 信息花字** | Generator B(SD / MJ / 灵创花字模块) | 文案"花字化" + "容器化"(`isolated on black background`) |
| **Prompt C · 素材处理** | Processor C(Relighting / 抠图工具) | 用户上传素材的抠图 + 光影重绘指引 |
| **Prompt D · Final Synthesis** | 合成 AI 或人工合成 | 描述各层 Z 轴堆叠 + 最终效果 |

### Step 4 · 多尺寸适配 (Multi-Size Output)

详见 [references/multi-size-adaptation.md](./references/multi-size-adaptation.md)。

主输出 = 1:1 / 750×750px(适配淘宝直播 + 小红书直播)
拓展尺寸(可选):**7 个商业化点位**的尺寸 + 安全区 + 信息层重排规则。

---

## 输入约定 (User Input)

用户在调用时提供以下输入(也可分步骤问出来):

```yaml
直播类型: 采销直播 | 达人直播 | 品牌直播 | 预热直播
直播主题: <2-10 字主题,例 "夏季新品首发">
营销文案:
  - 主标: <例 "满 99 减 50">
  - 副标: <例 "全场低至 5 折">
  - (可选)促销机制: <例 "限时 24 小时">
素材描述:
  - 主播: <例 "女性主播,30 岁左右,微笑正面照"> (可不填)
  - 商品: <例 "蓝色无线吸尘器,带配件包"> (可不填)
风格偏好: <可选,例 "清新风" / "国潮" / "高奢">
```

---

## 输出格式 (Strict Output)

```markdown
# 直播封面 AI 生成 · 设计蓝图

## 1. 📋 Design Blueprint

| 字段 | 值 |
|------|---|
| 直播类型 | <采销/达人/品牌/预热> |
| 营销主题 | <主题> |
| 调用风格 | S-xx <风格名> |
| 调用构图 | L-xx <构图名> |
| 调用花字 | T-xx <花字名> |
| 视觉重心 | <100% 商品 / 80% 人物 / ...> |

**设计逻辑**:<为什么这样搭配,1-3 句>

## 2. 🌅 Prompt A · 背景层

\`\`\`text
<英文 prompt,带 --no text --ar 1:1>
\`\`\`

## 3. 🌫️ Prompt C · 素材处理(Relighting)

<对用户上传素材的处理指引>

## 4. 💬 Prompt B · 信息花字

\`\`\`text
<英文 prompt,带 isolated on black background>
\`\`\`

## 5. 🎬 Prompt D · Final Synthesis(合成指导)

\`\`\`text
<英文 prompt,描述 Z 轴堆叠 + 各层互动>
\`\`\`

## 6. ⚠️ 待设计师确认

- <若任一兜底触发,标注 low_confidence + 原因>
- <若用户素材描述不足以判定 placement,提示补充>
- <平台合规性提醒:如医美 / 药品 / 金融需平台审核>

## 7. 📐 多尺寸拓展(可选)

<若用户要求多尺寸,引用 references/multi-size-adaptation.md 给出 7 尺寸的 prompt 微调建议>
```

---

## 输出约束

| 约束 | 原因 |
|------|------|
| **必须先输出 Design Blueprint,再输出 Prompts** | 让设计师 / 算法工程 5 秒看懂这套组合的逻辑 |
| **所有 Prompt 用英文** | SD / MJ / 灵创平台对英文 prompt 识别率最高 |
| **禁止在 Prompt 中包含具体品牌名 / 名人名 / 政治符号** | 平台合规性 + 版权风险 |
| **L1 背景层 Prompt 必须含 `negative space for [subject]`** | 给 L2/L3 留位 |
| **L4 信息层 Prompt 必须含 `isolated on black background`** | 后续合成时方便扣 alpha 通道 |
| **预热直播(无主播无商品)走 L-03 满版放射式** | 文字承担全部视觉 |
| **未命中风格 / 构图时 不要硬编造**,走兜底组合并标 `low_confidence` | 避免输出"看起来合理但不可用"的 Prompt |

---

## 兜底与边界 (Edge Cases)

| 场景 | 处理 |
|------|------|
| 用户没提供素材描述 | Prompt C 留空 + Prompt A 标 `studio backdrop` |
| 用户提供了真人主播照片但有版权风险 | 提示「主播肖像权确认」,**不内嵌生成**,只指引 Relighting |
| 直播主题含敏感词(药品 / 医美 / 金融) | 在 Step 0 提示「需平台合规审核」,但继续输出 prompt |
| 风格偏好与商品品类冲突(如"国潮风" + 数码家电) | 优先用户偏好,但在 rationale 说明冲突 |
| 一张封面要适配 7 个点位 | Step 4 输出 7 套微调建议,信息层位置按平台安全区调整 |

---

## 三大知识库索引

| 库 | 当前状态 | H1 平台迁移规划 |
|---|---|---|
| KB-A 风格库 | ✅ v0.1 6 个风格 ID 已录入 | 🟡 拟迁移到 灵创平台 · 拉 API |
| KB-B 构图库 | ✅ v0.1 6 个构图 ID 已录入 | 🟡 拟迁移到 灵创平台 · 拉 API |
| KB-C 文案库 | ✅ v0.1 5 个花字 ID 已录入 | 🟡 拟迁移到 灵创平台 · 拉 API |

---

## 版本历史

### v0.1(2026-05-29)· 首次录入

- 4 Phase 工作链路 + 三大知识库初始版本(KB-A 6 / KB-B 6 / KB-C 5)
- Prompt 模板基于 PE v16 改写
- 多尺寸拓展规则 v0.1(7 商业化点位)
- 已知差距:
  - 算法 API 对接 stub(待对接灵创平台 H1)
  - 真实 dogfood case 待补
  - 失败案例库待补(`examples/fail-cases/`)
