---
name: design-reasoning-input
harness-version: 0
description: '录入历史设计需求到知识库，生成 reasoning.md 并更新索引。 接受 Zero/Relay 设计稿 URL + PRD/BRD 文档作为输入，两阶段执行。 /design-reasoning-input <relay_url>
  <prd_path> /design-reasoning-input <relay_url> --design-only /design-reasoning-input --prd-only <prd_path> /design-reasoning-input
  <relay_url> <prd_path> --confirm

  '
user-invocable: true
triggers:
- 录入需求
- 新增需求
- 提供了 Relay 设计稿链接
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
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/huangliu-design/product-details/JD-ProductDetails-web/brain-frontend/public/design-kb/skills/design-reasoning-input/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
  short-description: 录入历史设计需求到知识库，生成 reasoning.md 并更新索引。 接受 Zero/Relay 设计稿 URL + PRD/BRD 文档作为输入，两阶段执行。 /design-reasoning…
disable-model-invocation: true
---

# /design-reasoning-input·历史需求录入

## 工作目录

执行本 skill 前，请先定位到仓库中的 `JD-ProductDetails-web/brain-frontend/` 目录，
所有路径均以此为根目录。

## ⚠️ 全局内容规则

**只写有来源的内容，无来源一律填 `TODO: 待补充`，不推测不编造。**

| 章节 | 规则 |
|---|---|
| 需求背景 / 约束条件 / 设计决策原因 | 只来自 PRD/BRD 或设计稿标注 |
| Before | 来自 PRD 描述、设计稿标注、或历史 Case（需标注来源） |
| 排除的方案 / 遗留问题 | 只来自 PRD/BRD 或设计师明确说明，无则留空 |
| 方案优劣判断 | **不做主观评价**。多套方案并行时，只客观记录各方案的差异和各自的优劣，不给出「AI 推荐」或「建议选用」的结论。最终选用哪套方案由设计师/评审决定，AI 只记录结论，不参与判断 |

---

## 执行流程

### 重新录入前快速检查

重新录入或连续录入前，先确认三件事，避免把文件写到错误分支、覆盖未提交内容或漏掉缩略图：

```bash
git branch --show-current
git status --short
npm run build
```

- 分支必须是用户指定分支（例如 `feature/huangliu/盖浇小面`）
- `git status --short` 如有未提交内容，先向用户确认是保留、提交还是暂存，不得覆盖
- 若上一个需求刚录完，先确认已跑 `npm run thumbnails` 和 `npm run validate-case -- <slug>`

---

### Step 0：重复检测

在解析输入之前，先检查本次录入是否与现有需求档案重复。

**读取索引：**
读取 `public/design-kb/knowledge/preview/index.js` 文件，解析 `window.CASES_INDEX = [...]` 数组，得到所有已录入档案条目。

**提取 Relay 关键字段：**
从输入的 Relay URL 中提取 `id`（文件 ID）和 `page_id`（页面 ID），忽略 `node_id` 和其他 query 参数。对索引中每个条目的 `relay` 字段做同样提取。

比对规则：`id` + `page_id` 完全相同即视为匹配（node_id 差异忽略——同一设计稿页面的不同节点属于同一需求）。

**PRD 比对（仅 PRD 链接非空时）：**
对输入的 PRD URL 和索引中每个条目的 `prd` 字段做归一化比对（统一 https、去末尾斜杠、转小写）。完全相同即视为匹配。

#### 0-A. 链接重复检测

- **未命中** → 静默继续。
- **命中** → 暂停执行，输出：

```
⚠️ 检测到疑似重复档案：
- 已有档案：[name]（slug: [slug]）
- 已有档案的 Relay：[relay]
- 你输入的 URL：[input_url]
- 匹配依据：id + page_id 相同（node_id 差异忽略）

请确认：
A. 这是同一个需求的迭代版本 → 回复"继续录入"，将自动加版本后缀
B. 这是新需求，只是共用了设计稿 → 回复"确认新档案"
C. 搞错了，取消录入 → 回复"取消"
```

- 用户选 **A** → 进入下方 0-B 同名版本号分配。
- 用户选 **B** → 不做改名，直接进入 Step 1。
- 用户选 **C** → 终止整个录入流程，不生成任何文件。

#### 0-B. 同名档案版本号分配

在确定 `feature_name` 后（来自表单预填 `# 需求名称：` 或 0-A 中用户确认后沿用原名），执行以下逻辑：

1. 收集索引中所有 baseName 相同的条目（剥离已有版本后缀后比较；后缀匹配规则：`/\s+(v?\d+(\.\d+)?)$/i`，覆盖 `2.0` / `2` / `v2` / `V2.5` 等手写格式）。
2. 若无同名条目 → 跳过，进入 Step 1。
3. 若有同名条目 → 按 `date` 字段升序排列（空 date 视为最早，排在最前）。
4. 确定新档案的设计时间（优先级）：
   a. 表单命令里如果已含 `# 设计时间：YYYY-MM-DD` → 用这个
   b. 否则从 Zero 设计稿元数据的时间字段读取
   c. 都读不到 → 输出：`⚠️ 无法确定设计时间，跳过场景 2 判断，按场景 1（追加末尾）处理`

**场景 1：新档案的设计时间 ≥ 所有同名档案的最晚 date**

自动追加到末尾：
- 新档案命名为 `baseName + (同名数量+1).0`
- 不修改已有档案
- 输出提示后继续进入 Step 1：
  ```
  ℹ️ 检测到同名档案，已自动命名为 "[name] N.0"（追加到末尾）。
  已有同名：[name]（2025-08-01）、[name] 2.0（2025-11-01）
  ```

**场景 2：新档案的设计时间早于某个已有同名档案**

暂停执行，输出：

```
⚠️ 检测到同名档案，且新档案设计时间不是最新：

⚠️ 请再次确认设计时间字段填对了吗？
   新档案时间：[new_date]
   此档案时间早于所有已有同名档案，这在实际工作中很少见。
   如果时间填错，会导致版本号排序混乱。

已有档案（按设计时间排序）：
- [name]（date: 2025-08-01，slug: xxx）
- [name] 2.0（date: 2025-11-01，slug: yyy）

你要录入的档案：
- [name]（date: 2025-06-01）

建议方案：
A. 保持已有档案不变，新档案命名为 "[name] 3.0"（追加到末尾，不严格按时间排序）
B. 严格按时间排序，需要重排已有档案（见下方清单）
C. 我搞错了，取消录入

请回复 A/B/C
```

- 用户选 **A** → 同场景 1 逻辑，追加末尾。
- 用户选 **B** → 输出重排文件清单（不自动执行修改），格式如下：

```
📋 需要手动重排的档案清单（共 X 个）：

1. [name] 保持不变（当前是最早的档案）
   - reasoning.md: 无需改
   - cases.js: 无需改
   - index.js entry: 无需改

2. [name] 2.0 需要改名为 [name] 3.0（因为新档案的时间在它之前）
   - reasoning.md: public/design-kb/knowledge/[slug]/reasoning.md
     修改：frontmatter feature_name: "[name] 2.0" → "[name] 3.0"
   - cases.js: public/design-kb/knowledge/preview/cases/[slug].js
     修改：feature_name: '[name] 2.0' → '[name] 3.0'
   - index.js entry: public/design-kb/knowledge/preview/index.js
     修改：name: "[name] 2.0" → "[name] 3.0"
   - timeline.js: public/design-kb/knowledge/preview/timeline/[slug].js（如果存在）
     修改：feature_name: '[name] 2.0' → '[name] 3.0'

3. 新档案：[name] 2.0（按时间应插入此位置）
   - 正常录入即可

提示：以上重排涉及 X 个文件的 X 处修改，为避免误改建议手动执行。
完成后运行 `git diff --stat` 确认改动范围。
```

输出清单后暂停，等待用户确认已手动完成重排（或放弃），再继续录入新档案。

- 用户选 **C** → 终止录入。

**index.js 不存在或解析失败时：** 静默跳过 Step 0，直接进入 Step 1。

---

### Step 1：解析输入

提取 Relay URL、PRD 路径、`--confirm / --prd-only / --design-only` 标识。至少需要一种输入。

同时提取表单注释字段（若存在）：
- `# 预览图：<url>` → 作为截图链接使用，Step 5 步骤 3 跳过截图询问，直接展示已填值
- `# 需求名称：`、`# 实例标签：`、`# 状态：`、`# 预期效果：` → 优先用于 Step 5 对应字段的预填
- `# PRD本地：<path>` → **仅用于 AI 分析**，Step 3 读取此路径的文件内容，不写入任何输出文档
- `# PRD链接：<url>` → **仅用于展示**，写入 reasoning.md frontmatter 的 `prd_url` 字段（md-viewer 中显示为「查看 PRD」按钮），不用于内容读取

> 两个字段可同时使用（本地分析 + 在线展示），也可单独使用任意一个。
> 若同时提供了命令行 PRD 路径参数和 `# PRD本地：`，以 `# PRD本地：` 为准。

**短链接处理：** 若 URL 非 relay.jd.com 域名，先用 `Bash(curl -sI <url> | grep -i location)` 自动解析真实 URL。解析失败才报错，不得停下来询问用户。

---

### Step 2：读取设计稿（有 URL 时）

```
① get_design_metadata  → 节点层级结构、图层名、节点尺寸和坐标

② get_design_context（以下场景必须调用，获取实际渲染字符）

   【核心原因】get_design_metadata 只返回图层 name 属性（Relay 图层面板里的名字），
   不返回文字图层的实际 characters 内容。两者可能不同步：
   - 图层名为通用占位符：「Component-title」「Label」「Frame 123」等
   - 图层名为旧版占位符：「UE：某某某 / 产品：某某某」而实际内容已更新为真实姓名
   只有 get_design_context 才能返回文字图层实际渲染的字符内容。

   必须调用 get_design_context 的场景：

   A. 人名 + 日期节点
      - 找到含 UE/UI/UX/产品/PM 前缀的节点后，对该节点调用 get_design_context
      - 若 metadata 未找到带角色前缀的节点，则对头部框架（通常名为「邮件模版头部」）调用

   B. 功能名称 / 页面标题
      - 若 metadata 中标题节点的 name 属性为「Component-title」等通用名，
        必须对该节点调用 get_design_context 获取实际标题文字

   C. UI 文案（按钮文字、标签文字、区块标题）
      - 状态枚举「视觉处理」字段中引用的所有界面文字，必须来自以下之一：
        · get_design_context 返回的 JSX 文本内容（首选，最可靠）
        · get_screenshot 截图中可见的文字
      - 禁止只用 metadata name 属性作为 UI 文案来源

   D. 设计标注引用节点
      - 节点 ID 仅允许作为内部核验依据，用于定位并调用 get_design_context
      - reasoning.md 正文不得暴露具体节点 ID、Relay 查询参数或「节点 X:XXXXXX」等引用痕迹
      - 设计稿来源最终只能写「设计稿」，PRD 来源可保留具体章节，不得直接把 metadata 的 name 属性当作标注原文

③ export_image（预览图自动导出，2× PNG）
   - 若 Step 1 已从 `# 预览图：<url>` 提取到截图 URL → 跳过，直接使用该 URL
   - 若未提供 → 调用 export_image，参数固定为 scale=2, format=png，nodeId 取 Relay URL 中的根节点 ID
   - export_image 返回永久 CDN 链接（image_url 字段），直接写入 screenshots 字段
   - 注意：export_image 仅对 ERP 用户开放；若返回权限不足，降级展示空字段并提示用户手动粘贴
```

提取：帧/画面名（状态名）、所有文本标签、设计标注文字、组件/图层名、节点尺寸。

**人名识别规则（设计师 / 产品）：**
- **设计师**：前缀为 `UI`、`UX`、`UE`（不区分大小写）后跟的姓名，可能有多位
- **产品**：前缀为 `产品`、`PM`（不区分大小写）后跟的姓名，可能有多位
- 无法通过前缀确认角色的人名，一律填 `TODO: 待补充`，不得猜测归属——但 designer / pm 两个字段为强制字段（见约束 15），两个角色都必须至少有一位真实姓名，识别不到必须在 Step 5 步骤 1 前暂停录入并要求用户补充（`# 设计师：` / `# 产品：`），不得写 TODO。
- **关键**：人名必须从 `get_design_context` 返回的 JSX 文字内容中提取，不得从 `get_design_metadata` 的 name 属性推断

**去重：** 完全相同的文本只保留一条，组件名/标注重复出现时合并。

---

### Step 3：读取 PRD/BRD（有文档时）

读取路径优先级：`# PRD本地：<path>` > 命令行参数传入的本地路径。

**本地文档**：用 `Read` 提取内容。

**在线 Joyspace 文档**（`joyspace.jd.com/pages/` 或 `joyspace.jd.com/apply`）：

```bash
# 使用 web-search 技能读取 Joyspace PRD 页面内容
bash "$SKILLS_ROOT/web-search/scripts/open-page.sh" "https://joyspace.jd.com/pages/xxxxxx" --content --selector "div.sl-editor-container"

# /apply/ 审批页面（需要文档所有权人授予你访问权限）
bash "$SKILLS_ROOT/web-search/scripts/open-page.sh" "https://joyspace.jd.com/apply?pageId=xxxxx" --content --selector "div.sl-editor-container"
```

> web-search 技能通过本地 Chrome 实例（127.0.0.1:8923 Bridge Server）使用 Playwright 操控 Chrome 来打开 JoySpace 页面。由于 Chrome 实例会继承你当前 JD 登录 Cookie，故无需额外认证即可读取你拥有权限的 Joyspace 文档。

提取：需求背景、设计目标、约束条件、Non-Goals。

**注意：** 读取的文件路径只用于内容分析，**不写入**任何输出文档（reasoning.md 正文、frontmatter、index.js 均不出现本地路径）。

---

### Step 4：推断元数据

| 字段 | 推断方式 |
|---|---|
| `feature_name` | PRD 标题或设计稿页面名 |
| `product_area` | 页面名 / PRD 功能区 |
| `platform` | 设计稿尺寸或 PRD 描述（PC/App/Both） |
| `keywords` | 见下方「关键词提取规则」 |

不确定的标注 `⚠️ 待确认`。

**标签提取规则（实例标签 + 隐性标签）：**

**实例标签**（写入 `tags_instance`，弹窗第二步展示给用户确认）：

- 数据来源：`public/design-schema/instances.json`，结构为 `大类 > 区块 > [模块列表]`
- 先用 `Bash(cat public/design-schema/instances.json)` 读取完整实例表
- 从设计稿节点名、PRD 模块名中，**只从 instances.json 中匹配实例**，格式为 `区块·模块名`，如「首卡区·腰带」
- **格式只取 Level 2（区块）+ Level 3（模块名），Level 1（大类）不写入**：
  - ✅ `已选弹层·商品信息`
  - ❌ `二级承接·商品信息`（大类不出现在格式中）
  - ❌ `二级承接-商品信息`（分隔符用 `·` 不是 `-`）
- **🚫 严格禁止**：不得使用任何 instances.json 之外的词汇填入 `tags_instance` 或 `keywords_component`。代码组件名（如 `confirmDialog`、`couponSheet`）、UI 框架词（如 `bottomSheet`）、自造业务词均属违规，一律不写入这两个字段。
- instances.json 中没有的新模块，必须先追加到对应区块（标注来源后请用户确认），再使用
- 任何需求都可以通过录入弹窗 Step 2 的"找不到？暂存一条新实例"来添加新实例，暂存后由白名单用户后续审核入库

**玩法/场景标签**（写入 `tags_gameplay: []`，AI 不填写，后续人工配置）：

- 映射关系维护在 `public/design-schema/scene.json`，现阶段 AI 统一输出空数组，不尝试推断

**隐性标签**（写入 `tags_hidden`，不在卡片展示，仅用于搜索召回和相关需求 AI 匹配）：

- `tags_action`：设计动作词，从 PRD 核心举措提取，如 `新增入口`、`状态机驱动`、`聚合展示`
- `tags_user_state`：用户路径词，描述用户所处状态或阶段，如 `领取前`、`已领取`、`无资格`
- `tags_interaction`：交互模式词，描述交互形态，如 `滑动切换`、`倒计时`、`条件显隐`
- `tags_metric`：数据指标词，只从「采用后的数据效果」里提取**带明确数值/比例/pp/金额/订单量**的核心指标，如 `转化率 +0.05pp`、`GMV +5%`。只有指标名但没有数据（如“提升转化率”“关注点击率”“核心看转化率”）不得提取；数据效果为「待上线 / 未上线 / 待观察 / 暂无数据 / —」时，步骤 2 展示 `数据指标：无`，`tags_hidden.tags_metric` 写空数组 `[]`。

**兼容旧格式：** Step 6 的 frontmatter 同时保留旧字段供现有检索逻辑使用：

```yaml
keywords_component: [tags_instance 平铺合并]
keywords: [tags_instance 平铺合并，供检索用]
```

---

### Step 5：分步骤 Outline（Phase 1）

Phase 1 分四步输出，每步等用户确认后才继续。不写入任何文件。

**⚠️ 冲突暂停规则：** 解析过程中，若发现设计稿标注文字和 PRD 对同一功能点存在矛盾或不一致，必须立即暂停，将冲突点逐条列出后告知用户，等用户手动确认或补充后再继续。不得自行判断取其中一个。

**⚠️ 禁止跳步（硬约束，见 §关键约束 12）：** 即使初始命令文本里已经包含全部 4 步所需信息，也必须依次输出「步骤 1 / 4」→「步骤 2 / 4」→「步骤 3 / 4」→「步骤 4 / 4」四个 Outline，每步等用户回复「确认 / 修改 / 提交」后才能进入下一步，不得合并步骤、不得直接跳到 Phase 2。

---

#### 步骤 1：基础信息确认

**前置校验（强约束）：** 进入步骤 1 之前，先确认设计师与产品姓名是否齐全。

来源优先级：
1. 用户在命令中显式提供（`# 设计师：张三` / `# 产品：李四`） → 直接采用，跳过设计稿识别
2. 否则从 Step 2 的 `get_design_context` 结果中按前缀规则提取（UI/UX/UE → 设计师，产品/PM → 产品）

**校验规则（两个角色都必须至少有一位真实姓名，不允许 TODO/空）**：
- 设计师：至少一位 UI/UX/UE 姓名
- 产品：至少一位 产品/PM 姓名

任一角色为空、或仅识别出 TODO、或前缀无法判定角色时，**必须暂停录入流程**，输出：

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ 录入暂停：设计师/产品姓名缺失
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

从设计稿中识别到的：
  设计师：[姓名列表 或「未识别」]
  产品：  [姓名列表 或「未识别」]

请补充以下任一缺失字段：
  # 设计师：张三
  # 产品：李四

收到补充后，直接接续进入步骤 1，无需重跑 Step 2/3/4。
```

不得带着空白/TODO 的设计师或产品字段继续进入步骤 1。

---

输出以下内容，等待用户确认或修正：

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
步骤 1 / 4　基础信息
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

需求标题：[从 PRD 标题或设计稿页面名提取]
功能区：  [product_area，如 scene/strategies/nationalSubsidy]
平台：    [PC / App / Both]
需求类型：优化迭代（固定值，字段已废弃但保留兼容）
Relay：   [URL，无则「未提供」]
PRD：     [已提供 / 未提供]

以上信息是否正确？可直接修改，或回复「确认」进入下一步。
```

用户回复「确认」或修改后，继续步骤 2。

---

#### 步骤 2：AI 推荐标签

读取 `public/design-schema/instances.json`，结合设计稿节点名和 PRD 内容，推荐实例标签：

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
步骤 2 / 4　选择实例
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🧩 实例标签（来源：instances.json，格式：区块·模块名）

  大类：[通用楼层] / [二级承接]
  区块：[选择大类后展开，如：首卡区 / 二卡区 / 已选弹层 / ...]
  实例：[选择区块后展开，每个模块旁显示关联业务（非通用时显示事业群名称）]

  已选：☑ [区块·模块名，如：首卡区·腰带]  ☑ [...]

  [找不到？可暂存一条新实例到待审核队列]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
隐性标签（AI 自动，不在卡片展示，可查看）：

🔍 设计动作：[自动抽取]
   用户状态：[自动抽取]
   交互模式：[自动抽取]
   数据指标：[自动抽取；仅展示有明确数值的核心指标；待上线/无数据时写「无」]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

可直接修改实例选择，或回复「确认」进入下一步。
```

**实例推荐规则：**
- 只从 `public/design-schema/instances.json` 中选取，不得自造词
- 推荐数量：1-5 个，精准匹配设计稿涉及的模块
- 找不到合适实例时，可通过"找不到？暂存一条新实例"暂存到待审核队列
- 隐性标签由 AI 自动生成，用户无需修改

用户回复「确认」或修改后，继续步骤 3。

---

#### 步骤 3：补充归档

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
步骤 3 / 4　补充归档
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

核心举措（AI 推断，可修改）：
[这次需求的核心动作是：一句话]

📸 设计稿截图链接（2× PNG，自动导出）
[若 Step 1 已从输入中提取到 `# 预览图：<url>` → 直接展示该 URL
 否则 → Step 2 已通过 export_image(scale=2) 自动导出，展示返回的 CDN URL]
  截图链接：<url>（可修改，或回复「跳过」清空）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
可直接修改核心举措或截图链接，或回复「确认」进入下一步。
```

用户回复「确认」或修改后，继续步骤 4。

---

#### 步骤 4：数据效果确认

读取用户初始命令文本中的 `# 数据效果·预期收益：` / `# 数据效果·实际收益：` / `# 数据效果·AB测设置：` / `# 数据效果·AB测结果：` 四行（如有）作为「用户输入」；同时从 PRD / 设计稿抽取「PRD 候选」。两者并列输出供用户裁决：

#### 数据指标提炼规则（强约束）

- 只提炼**有真实数据的核心指标**：必须同时出现指标名和明确数值/比例/pp/金额/订单量，例如「转化率 +0.05pp」「GMV +5%」「订单量 +2000/日」。
- 只有指标名但没有数据的内容不提炼，例如「提升转化率」「核心看点击率」「关注加购率」「提升用户体验」都不写入数据指标。
- PRD 里只有目标方向、收益假设、待评估口径，但没有数值时，该项采用值写「—」，不为了凑完整而提炼。
- 如果数据效果或用户输入写的是「待上线 / 未上线 / 待观察 / 暂无数据 / 无数据」，则四项采用值按「—」处理，步骤 2 的「数据指标」写「无」，`tags_hidden.tags_metric` 写 `[]`，`cases/{slug}.js` 的 `data_effect` 写 `null`。
- 多个指标同时有数据时，只保留与本次设计动作直接相关的 1-3 个核心指标；预算、ROI 公式、复杂测算过程、历史背景数据不作为数据指标。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
步骤 4 / 4　数据效果确认
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 数据效果（来源优先级：用户输入 > PRD 抽取）

  ① 预期收益
     - 用户输入：[展示用户填的，或「未填」]
     - PRD 候选：[从 PRD / 设计稿抽取，或「无相关内容」]
     - 采用值：  [若两者一致 → 直接展示；若不一致 → 列冲突让用户裁决]

  ② 实际收益
     - 用户输入：[同上]
     - PRD 候选：[从 PRD / 设计稿抽取上线后数据]
     - 采用值：  [...]

  ③ AB 测设置（含分桶维度、分桶比例、实验周期）
     - 用户输入：[同上]
     - PRD 候选：[从 PRD / 设计稿抽取 AB 实验/灰度]
     - 采用值：  [...]

  ④ AB 测数据结果
     - 用户输入：[同上]
     - PRD 候选：[同上]
     - 采用值：  [...]

⚠️ 冲突暂停：
  若某一项「用户输入」与「PRD 候选」不一致，必须明确提示并请用户裁决：
    例：① 预期收益冲突
        - 用户填写：转化率 +0.2%
        - PRD 候选：转化率 +0.5% / 月度 GMV +1.12 亿
        请回复：A 采用用户值 / B 采用 PRD 值 / C 合并表述（请补充合并方案）

📝 数据来源（采用 PRD/设计稿/用户输入 三选一，不标注具体章节或节点）

💡 「采用值」为「—」的字段写入规则：
  - reasoning.md 五.X 章节正文写「—」（保留章节结构，让人看到 AI 没漏问）
  - cases/{slug}.js 的 data_effect 对应 key **省略不写**（不是空串、不是 null、不是「—」），让 UI 自动隐藏该卡片
  - 仅当 4 项均为「—」时，cases.js 的 data_effect 整字段设为 null

可直接修改任一字段，或回复「提交」生成四个文件并写入知识库：
  ① reasoning.md（含「五、数据效果」章节，全空时仍生成、各项填「—」）
  ② cases/{slug}.js（含 data_effect 字段：全 4 项空时整字段设为 null；部分项空时省略空项的 key，让 UI 仅渲染有数据的卡片）
  ③ index.js 追加条目（统一索引）
  ④ timeline/{slug}.js（弹层人名/日期按需加载）
```

用户回复「提交」后，执行 Step 6 生成文件。

---

### Step 6：生成四个文件（Phase 2）

**必须同时生成以下四个文件，缺少文件 ①②③ 任意一个都会导致预览页弹层显示「详情数据暂时无法加载」。**

#### 文件 ①：reasoning.md

将截图链接写入 frontmatter，按以下模板生成文件：

```markdown
---
feature_name: [功能名称]
requirement_type: 优化迭代
product_area: [功能区]
platform: [PC / App / Both]
relay_source:
  url: [Relay URL]
  node_id: [节点 ID]
prd_url: [# PRD链接：提供的在线 URL，无则省略此行]
screenshots:
  - label: [设计稿标题]
    url: [CDN链接，无则留空]
tags_instance: [实例标签，格式：区块·模块名，如：首卡区·腰带, 二级弹层·以旧换新弹层]
tags_gameplay: []
tags_hidden:
  tags_action: [设计动作词，如：新增入口, 聚合展示]
  tags_user_state: [用户路径词，如：领取前, 已领取, 无资格]
  tags_interaction: [交互模式词，如：倒计时, 条件显隐]
  tags_metric: [数据指标词，如：CTR, 加购率]
keywords_component: [tags_instance 合并，供检索用]
keywords: [所有显性标签合并，供检索用]
wiki_refs: []
last_updated: [YYYY-MM-DD]
related_cases:
  - path: [关联 Case 路径]
    note: [一句话关联说明]
---

<!--
wiki_refs：设计规范或组件 Token 的 wiki 链接，暂未接入时留空数组即可。
-->

# [功能名称]·设计决策记录

> 来源：设计稿 [Relay URL] / PRD [来源说明]
> 设计：[UX姓名] / 产品：[PM姓名] / 时间：[YYYY-MM-DD]

---

## 一、需求背景

**核心问题：** [用户/业务遇到了什么问题，1-2句]

**核心痛点及目标：** [解决这个问题要达成什么，1句]

> 来源：PRD §[章节] / 设计稿 / 用户输入

---

## 二、设计核心打法

> 这一章记录本次需求的关键设计举措——围绕核心动作深思熟虑的部分。
> 其他模块的改动（文案微调、图标替换、跟随核心改动的联动修改）不在此记录。
>
> 以下内容**不得**写入核心打法。需求档案是精炼摘要，不重复承载这些信息——
> 它们以设计稿标注 / PRD / 组件规范的**原始形态**留存：
> - 设计规范细节（间距、字号、配色） → 留在设计稿标注 / 组件规范
> - 组件实现规范（组件属性、状态切换逻辑） → 留在组件规范
> - 视觉规则与边界规则（容错、自适应、超长缩放） → 见约束 10
> - QA 用例、验收标准、测试场景 → 留在设计稿验收说明 / PRD 验收章节
> - 工程实现细节（接口、埋点字段、技术方案） → 留在 PRD 技术章节
>
> 多动作时按**用户主决策路径**排序：用户先感知到的、决定其下一步行为的动作在前；联动改动、辅助优化在后。

### 核心举措

**这次需求的核心动作是：** [一句话，例：「在优惠弹层顶部增加双优惠聚合展示区块」]

**为什么这样做：**
[理由，来自 PRD/设计稿/历史依据，无来源填 TODO: 待补充]

**排除的方案：**（无明确输入则留空）

### 是否有多套方案

- [ ] 只有一套方案（已定稿）
- [ ] 有多套方案并行输出，最终选用方案：[方案名 / TODO: 待评审确认]

**多套方案说明：**（仅有多套方案时填写，无则留空）

| 方案 | 核心差异 | 优势 | 劣势 |
|---|---|---|---|
| 方案一 | | | |
| 方案二 | | | |

---

## 三、状态枚举

> 各模块在不同条件下的视觉状态及对应样式。
> ⭐ 标注历史曾遗漏的高风险状态。

| 模块 | 状态 / 触发条件 | 视觉处理 | 备注 |
|---|---|---|---|
| [模块名] | [状态名] | [视觉描述] | |
| [模块名] | ⭐ [容易遗漏的状态] | [视觉描述] | 历史曾遗漏 |
| [模块名] | 异常 / 兜底 | [视觉描述] | |

---

## 四、交互流程及逻辑判断

> 模块之间的点击跳转、展开/收起等交互逻辑。
> 对应设计稿中用箭头连接的交互稿部分。

**主流程：**
[用文字描述主要的页面/模块跳转路径，例：商详主页 → 点击国补腰带 → 触发优惠弹层 → 点击附件提示 → 触发说明弹窗]

**分支逻辑：**

| 触发条件 | 动作 | 结果 |
|---|---|---|
| [用户做了什么 / 满足什么条件] | [点击/展开/跳转] | [进入哪个状态/页面] |

---

## 五、数据效果

> 本次需求的预期收益、实际收益、AB 测设置、AB 测数据结果。
> 数据来源：用户在录入命令中提供（# 数据效果·xxx 行），或从 PRD / 设计稿抽取。
> 四项中任何一项无数据，填「—」。
>
> **写作要求（强约束）**：四项均服务于「快速理解需求价值」，不得整段搬运 PRD §收益章节。
>
> 推荐句式：
> `预计影响 [对象/范围]，核心看 [1-2 个指标]。来源：PRD / 设计稿 / 用户输入（三选一，不标注具体章节或节点）`
>
> 写作规则：
> - **删除**：预算投入、ROI 测算公式、复杂分项口径、历史背景数据、对比基线的完整推导过程
> - **弱化**：与当前设计动作弱关联的次级指标（例如本次只动腰带，却列出全站 DAU 变化）——保留指标名和方向（如「DAU 微正」），不抄具体数值和测算过程
>
> 如果用户/PRD 提供的内容超过推荐句式范围，先按上述规则精简，再写入；不得为了「信息完整」而保留冗余。

### 预期收益
[转化率 / GMV / UV / 客单价等指标的预期变化值；填「—」表示无数据（仅 md 写「—」，cases.js 对应 key 省略不写，见约束 14）]

> 来源：[PRD / 设计稿 / 用户输入 / —]

### 实际收益
[上线后的实测数据；填「—」表示尚未上线 / 数据未回收（仅 md 写「—」，cases.js 对应 key 省略不写，见约束 14）]

> 来源：[PRD / 设计稿 / 用户输入 / —]

### AB 测设置
[分桶维度（按品类 / 按用户标签 / 按 App 版本）、分桶比例、实验周期、实验 ID；填「—」表示无 AB 测（仅 md 写「—」，cases.js 对应 key 省略不写，见约束 14）]

> 来源：[PRD / 设计稿 / 用户输入 / —]

### AB 测数据结果
[AB 测各组对照指标 + 是否扩量 + 扩量节奏；填「—」表示尚未有结果（仅 md 写「—」，cases.js 对应 key 省略不写，见约束 14）]

> 来源：[PRD / 设计稿 / 用户输入 / —]

---

## 六、关联 Case

> 与本需求框架相似或有直接参考价值的历史案例。
>
> **判定标准**：关联必须能帮助读者理解或评审当前需求，仅是关键词命中不算关联。
>
> - 🔴 **强关联**：构成以下关系之一 → 继承（沿用已有框架/模式）/ 对比（同一问题的不同解法）/ 依赖（当前需求建立在另一 case 的成果上）/ 可复用模式（核心打法直接复用历史 case 的 Pattern）
> - 🟡 **弱关联**：局部参考（仅某一交互/组件/状态可参考），不构成整体框架的继承或对比
> - ❌ **不写入**：仅关键词命中、表面词汇相似、同一业务域但设计决策无关
>
> AI 判断不出明确关联时**留空**，不凭关键词命中强行写入，不要写「需要人工确认」之类的占位。

| 相关性 | Case | 关联点 | 设计稿 |
|---|---|---|---|
| 🔴 | [Case 名] | [框架/组件/决策的关联说明] | [Relay 链接] |
| 🟡 | [Case 名] | [局部参考点] | [Relay 链接] |

---

## 附：经验沉淀

> 本次需求中提炼的经验与规律，供未来参考复用。
> 仅在本次确实产生了新的经验沉淀时填写，无则留空。
>
> **写作约束（强约束）**：每条 Pattern 必须能指导未来需求的设计决策。
> 如果提炼不出明确取舍（决策权衡 / 入口策略 / 路径连续 / 指标选择 / 边界归属等），
> 整段留空，不得填写泛泛总结来凑数。
>
> ❌ **不要写**：
> - 「要注重用户体验」「要保持视觉一致性」「要尊重业务诉求」（无具体取舍，任何需求都成立）
> - 单纯描述本次做了什么（这是核心打法的工作，不是经验沉淀）
> - 行业通识（「移动端按钮要够大」「重要操作要二次确认」）
>
> ✅ **应该写**：
> - 「在已有入口的页面追加同类入口时，优先合并到现有入口而非新增——避免入口分裂导致用户决策成本上升。」（决策取舍）
> - 「优惠聚合展示优先级：用户已领 > 待领取 > 仅展示——已领取的优惠决定用户已感知的让利预期，应优先呈现。」（路径策略）
>
> ---
>
> **AI 生成策略（内部规则，不展示给用户）**
>
> **触发信号**——出现以下任一情况时，尝试提炼 Pattern：
> - 核心打法章节里有「排除的方案」段落（说明存在决策取舍）
> - 设计决策的 Reason 里提到了可泛化的原则（不只是"PRD 要求"）
> - 同一个设计决策在多个模块/状态下被复用（说明有底层模式）
> - Before → After 的转变中包含违反直觉的选择（如"反而删掉了入口"）
>
> **提炼方法**——从 Decision → Reason → Excluded Alternative 三元组抽象：
> 1. 找到核心打法中的每个 Decision
> 2. 看它的 Reason：如果 Reason 是"PRD 要求/业务方指定"→ 不提炼（无设计判断）
> 3. 看它的 Excluded Alternative：如果有被排除的方案 → 问"排除的本质原因是什么？"
> 4. 把这个本质原因抽象为一句可复用的原则
> 5. 验证：换一个不同业务的需求，这条原则还能指导决策吗？能 → 保留；不能 → 丢弃
>
> **去重机制**——写完后与已有历史 Pattern 对比：
> - 用 grep 搜索 `public/design-kb/knowledge/` 目录下所有 reasoning.md 的"附：经验沉淀"章节
> - 如果同样的原则已经被其他档案沉淀过（核心含义相同，不是字面重复）→ 不重复写入
> - 如果是对已有 Pattern 的细化/补充（新增了适用边界）→ 可以写入，但在 note 中标注"扩展自 {slug} 的 Pattern N"
>
> **质量自检**——AI 写完每条 Pattern 后自问：
> 1. "如果我不写这条，读者看完核心打法能自己推导出来吗？" → 能 → 删（冗余）
> 2. "这条只在本业务场景成立，还是跨业务都成立？" → 只在本业务 → 改写得更抽象，或删
> 3. "这条的 not_applies 是否清晰？" → 如果想不出不适用场景 → 说明太泛，需要收窄

### Pattern 1：[模式名]

**适用场景：** [什么情况下用这个模式]

**不适用场景：** [什么情况下不要用]

**核心原则：** [为什么这样做是对的，一句话]
```

---

#### 文件 ②：cases/{slug}.js（预览弹层详情数据）

路径：`public/design-kb/knowledge/preview/cases/{slug}.js`

内容与 reasoning.md 完全对应，不单独推断新内容：

```js
window.CASE_DATA = window.CASE_DATA || {};
window.CASE_DATA['{slug}'] = {
  slug: '{slug}',
  feature_name: '[功能名称]',
  product_area: '[功能区]',
  platform: '[App / PC / Both]',
  last_updated: '[YYYY-MM-DD]',
  relay_url: '[Relay URL]',
  prd: '[prd_url，无则留空字符串]',
  keywords: [/* tags_instance + tags_hidden 展开为字符串数组 */],
  screenshots: [{ label: '[标题]', url: '[CDN链接，无则留空字符串]' }],
  related_cases: [
    { slug: '[关联Case的slug]', note: '[一句话关联说明]' }
  ],
  // data_effect：与 reasoning.md「五、数据效果」字节一致的派生数据。
  // 四项全为「—」时，整个 data_effect 字段填 null（library.html 的 renderDataEffect 收到 null 不渲染整段）。
  data_effect: {
    expected:  '[预期收益，与 md 五.预期收益正文一致；无则填「—」]',
    actual:    '[实际收益，与 md 五.实际收益正文一致；无则填「—」]',
    ab_setup:  '[AB 测设置，与 md 五.AB 测设置正文一致；无则填「—」]',
    ab_result: '[AB 测数据结果，与 md 五.AB 测数据结果正文一致；无则填「—」]'
  },
  sections: {
    background: '[需求背景，含用户问题和业务影响，支持\\n换行和**加粗**]',
    goal: '[设计目标与核心举措]',
    constraints: [
      { type: '[业务约束/技术约束/平台约束]', content: '[约束内容]' }
    ],
    states: [
      { name: '[状态名，容易遗漏的状态加 ⭐ 前缀]', visual: '[视觉处理描述]', note: '[备注]', star: true/false }
    ],
    patterns: [
      { title: '[模式名]', applies: '[适用场景]', not_applies: '[不适用场景]', principle: '[核心原则]' }
    ],
    exclusions: '[排除项，多条用\\n分隔]',
    issues: [
      { problem: '[待确认问题]', owner: '[产品/研发/设计]', status: '⏳ 待确认' }
    ]
  }
};
```

**字段来源规则：**
- `background` ← 一、需求背景
- `goal` ← 核心举措
- `states` ← 三、状态枚举（star: true 对应 ⭐ 标注的高风险状态）
- `data_effect` ← 五、数据效果（四个 sub-field 必须与 md 章节正文**字节一致**，违反 §关键约束 14）
- `patterns` ← 附：经验沉淀
- `exclusions` ← 排除的方案

#### 文件 ③：index.js 追加条目（统一索引）

路径：`public/design-kb/knowledge/preview/index.js`

用 Python **文本级插入**追加新条目，不 parse 整个数组、不重新 dump，避免 diff 爆炸：

```python
import json, re

idx_path = 'public/design-kb/knowledge/preview/index.js'

new_entry = {
    "slug": "{slug}",
    "name": "[功能名称]",
    "platform": "[App / PC / Both]",
    "area": "[promotion / trade-in / content / ...]",
    "req_type": "[新增功能 / 优化迭代 / 问题修复]",
    "status": "online",          # 已上线填 online，其他填 draft
    "online_date": "",           # 预计上线日期，如 "2026-07-01"，无则留空
    "launch_ver": "",            # 预计版本号，如 "7.0"，无则留空
    "rollout_percent": "",       # 灰度比例，无则留空
    "relay": "[Relay URL]",
    "prd": "[prd_url，无则留空字符串]",
    "archive": "/design-kb/knowledge/preview/library.html#{slug}",
    "screenshot": "[截图CDN URL，无则留空字符串]",
    "date": "[YYYY-MM-DD]",      # 设计完成日期，来自 reasoning.md 正文「时间：」
    "updated": "[YYYY-MM-DD]",   # 知识库录入日期，即今天
    "designer": "[设计师姓名]",
    "pm": "[产品姓名]",
    "keywords_component": ["[instances.json 实例名，格式：区块·模块名]"],
    "keywords_business": ["[主业务词，如：国补]"],
    "keywords": ["[搜索关键词列表]"],
    "tags_gameplay": [],         # 玩法场景标签，人工配置，默认空数组
    "isNew": True
}

content = open(idx_path, encoding='utf-8').read()

# 跳过重复录入
if f'"slug": "{new_entry["slug"]}"' in content:
    print(f'已存在 {new_entry["slug"]}，跳过')
else:
    # 只序列化新条目，缩进 2 空格（与文件格式一致）
    entry_text = json.dumps(new_entry, ensure_ascii=False, indent=2)
    # 每行加 2 空格缩进，使其嵌套在数组里
    entry_indented = '\n'.join('  ' + line for line in entry_text.splitlines())

    # 找到数组末尾 ] 的位置
    close_bracket = content.rfind(']')
    before = content[:close_bracket].rstrip()

    # 数组非空时在新条目前加逗号
    separator = ',\n' if before.rstrip().endswith('}') else '\n'

    new_content = before + separator + entry_indented + '\n' + content[close_bracket:]
    open(idx_path, 'w', encoding='utf-8').write(new_content)
    print(f'已追加 {new_entry["slug"]}')
```

> `cases.json` 和 `timeline/index.js` 已于 v3.x 删除（统一索引为 preview/index.js）。

#### 文件 ④：timeline/{slug}.js（弹层详情按需加载）

路径：`public/design-kb/knowledge/preview/timeline/{slug}.js`

此文件供需求详情弹层按需加载人名和日期，**继续独立维护，不受索引合并影响**。

**字段来源：**
- `name / relay / prd` ← reasoning.md frontmatter（`feature_name / relay_source.url / prd_url`）
- `date` ← reasoning.md 正文 `> 设计：xxx / 产品：xxx / 时间：YYYY-MM-DD` 行中的**时间**字段（设计完成日期）
- `designer / pm` ← reasoning.md 正文 `> 设计：xxx / 产品：xxx` 行（只取姓名）
- `archive` ← 固定格式 `/design-kb/knowledge/preview/library.html#{slug}`

```js
window.TIMELINE_DATA = window.TIMELINE_DATA || {};
window.TIMELINE_DATA["{slug}"] = {
  slug: "{slug}",
  name: "[功能名称]",
  date: "[YYYY-MM-DD]",
  designer: "[设计师姓名]",
  pm: "[产品姓名]",
  relay: "[Relay URL]",
  prd: "[prd_url，无则留空字符串]",
  archive: "/design-kb/knowledge/preview/library.html#{slug}"
};
```

---

### Step 7：查找关联 Case（写入 related_cases）

**不使用 Read 工具读取完整文件**，用两步 Bash 完成：

**第一步：关键词扫描，找候选文件**
```bash
grep -rl "<关键词1>\|<关键词2>" public/design-kb/knowledge/
```
用本次提取到的 keywords 作为搜索词，只返回文件路径列表，不读内容。

**第二步：只读 frontmatter，判断相关性**
```bash
head -30 <文件路径>
```
对每个候选文件只读前 30 行（frontmatter 范围），从 `feature_name` 和 `keywords` 字段判断是否相关。不读正文。

写入 `related_cases` 字段，每条附一句关联说明。无匹配则留空。

**写入前自检（强约束）**：每条候选必须满足「六、关联 Case」的判定标准之一（继承 / 对比 / 依赖 / 可复用模式 / 局部参考）。仅关键词命中、表面词汇相似、同一业务域但设计决策无关的 case **不写入**。AI 判断不出明确关联时直接留空，不写占位。

---

### Step 8：更新索引

- **INDEX.md**：在对应功能区追加新行
- **component-naming.md**：新组件名追加到命名表

> index.js（统一索引）已在 Step 6 文件 ③ 中更新，此处无需重复操作。

---

### Step 9：生成缩略图（列表卡片用）

文件写入和索引更新完成后，**必须**跑一次缩略图脚本，把本次新增 case 的首张截图压成 900×600 JPEG q80，存到 `preview/thumbnails/{slug}.jpg`，并更新 `preview/thumbnails/_thumb_index.js`，让 library.html 列表卡片走本地缩略图（免去每次拉 4-18MB 原图）。

```bash
npm run thumbnails
```

**增量执行规则：**
- 已存在 `{slug}.jpg` 自动跳过，单次录入只处理本次新增 case，无网络/CPU 浪费
- `screenshots: []` 或截图字段为空的 case 自动跳过，卡片回退占位 SVG
- 脚本失败（如截图 URL 404、CDN 暂时不可达）不阻塞录入流程，仅在日志中提示失败 slug，下次录入或手动 `/knowledge-preview` 时会自动补跑

**禁止跳过本步**：跳过会导致新录入的 case 在 library.html 列表上显示占位 SVG 而非缩略图，与既有 case 视觉表现不一致。

**卡顿优化要求（强约束）**：录入需求档案后必须生成 `public/design-kb/knowledge/preview/thumbnails/{slug}.jpg` 和更新 `_thumb_index.js`，让需求档案列表直接展示本地缩略图，而不是每次从 CDN 拉取原始大图。缩略图脚本失败时不得静默忽略，最终回复必须提示失败 slug 和原因。

---

### Step 9.5：落库自检（提交前必做）

完成 Step 9 后，必须对本次新增 slug 运行一次自检：

```bash
npm run validate-case -- <slug>
```

自检覆盖：index/case/timeline 三处 slug 是否齐全且唯一、designer/pm 是否为空、archive/reasoning_path 是否正确、cases.js 是否出现双重转义 `\\n`、是否误写本地路径、data_effect 是否把无数据内容写成卡片、缩略图和 `_thumb_index.js` 是否已生成。

若自检失败：必须先修复再继续，不得提交或推送。若只有缩略图 warning：先补跑 `npm run thumbnails`；仍失败时在最终回复中说明失败 slug 和原因。

推荐最终验证顺序：

```bash
npm run thumbnails
npm run validate-case -- <slug>
npm run build
git diff --stat
```

---

### Step 10：处理新增待审核实例（有 `# 新增待审核实例：` 时）

若命令输入中包含 `# 新增待审核实例：` 行，执行以下操作：

**1. 解析命令中的 pending 信息：**

```
# 新增待审核实例：腰带倒计时
# 实例所属场景：universalFloors
# 实例所属区块：card1Area
# 实例类型：通用
# 来源需求：国补资格有效期
# 来源Relay：https://relay.jd.com/file/design?id=xxx
```

**2. 生成英文 ID 建议：**

读取 `public/design-schema/instances.json`，学习现有命名风格（严格 camelCase，意译，后缀惯例：Sheet/Dialog/Tabs/Formula/Widget），为新实例生成英文 ID。

命名规则：
- 严格 camelCase，无连字符/下划线/前缀
- 意译（不是拼音），以功能/对象为核心
- 后缀：弹层用 Sheet，弹窗用 Dialog，多 Tab 用 Tabs，公式用 Formula
- 检查生成的 ID 是否与已有实例冲突，冲突则加业务前缀区分

**3. 写入 pending-instances.json：**

用 Edit 工具在 `public/design-schema/pending-instances.json` 的 `pending` 数组末尾追加新条目（文本级操作）：

```json
{
  "id": "pending_<时间戳>",
  "name": "<中文名>",
  "suggested_depth": "<所属场景或null>",
  "suggested_area": "<所属区块或null>",
  "suggested_ytype": "<类型或null>",
  "keyword_ref": "<区块·中文名，与档案 keywords_component 里写入的值一致>",
  "source_requirement": {
    "name": "<来源需求名>",
    "relay_url": "<来源Relay>",
    "slug": "<本次录入的slug>"
  },
  "submitted_at": "<ISO时间>",
  "suggestion": {
    "id": "<AI生成的英文ID>",
    "area": "<建议区块>",
    "ytype": "<建议Ytype>",
    "xtype": 0,
    "scene": "<建议Scene或空>",
    "confidence": "high",
    "reasoning": "<一句话命名理由>"
  }
}
```

**无 `# 新增待审核实例：` 行时跳过本步。**

---

## 关键约束

1. 不编造内容，无来源填 TODO，无输入的章节留空
2. 不覆盖已有文件，已存在加 `.NEW` 后缀
3. Phase 1 不写文件
4. 截图链接优先使用 `# 预览图：` 提供的 URL；未提供时调用 get_screenshot 取 URL，不保存 base64；均无则 screenshots 字段留空
5. 不保存 base64 截图数据（get_screenshot 只取 URL 字段）
6. MCP 失败时降级为仅用 PRD，标注 `⚠️ 设计稿数据缺失`
7. **`tags_instance` 和 `keywords_component` 只能使用 instances.json 中的词，格式 `区块·模块名`；代码组件名（如 `confirmDialog`、`couponSheet`）不属于 instances.json，一律不写入这两个字段**
8. 🚫 **禁止推测**：reasoning.md 所有内容必须有明确来源（设计稿标注或 PRD 原文）。如果某字段在设计稿和 PRD 中均无对应信息，必须留空或标注 `—`，不得基于常识、经验或推断填写。
9. 🚫 **禁止跨 case 填充**：不得参考历史 reasoning.md 或其他 case 的内容补全当前需求。每个需求只能基于当次提供的设计稿和 PRD 生成。历史案例仅用于「关联 Case」章节，不得用于填充其他任何字段。
10. 🚫 **状态枚举不得从坐标推断**：通过坐标范围扫描（如搜索 x/y 值区间）在 metadata 中发现的文字节点，不能直接作为状态名称或状态内容录入。必须调用 `get_screenshot` 截取**含周围父框架的上下文截图**，确认该文字节点属于手机 Frame 内的完整状态，而非注释区、流程图或连接线上的零散标注词。若截图仍无法确认上下文，备注须明确标注「上下文待核实」，且禁止对视觉样式、交互行为做任何推断描述。此外，**空状态 / 兜底状态须有设计稿或 PRD 明确描述**，AI 不得自行推断其存在并添加状态行。

    同时，状态枚举**只保留用户主链路关键状态**。以下内容**不得**写入状态枚举，也不在需求档案中其它章节承载，归组件规范 / 设计稿本身管理：
    - 纯视觉容错（如金额超长缩放、字符自适应、文字截断）
    - 边界适配（如不同屏幕尺寸下的布局微调）
    - 暗黑模式 / 深色主题适配（纯视觉层切换，不影响业务逻辑）
    - 实验命中 / 不命中（试金石、AB 测等纯开关逻辑，不产生独立视觉状态）
    - 不改变用户理解、审批判断、实现范围、验收标准的状态行

    判断口径：删掉这一行，用户是否还能完成主链路决策？能 → 删。
11. 🚫 **UI 文案必须来自 get_design_context 或截图，不得只用 metadata**：状态「视觉处理」字段中的界面文案（按钮文字、标签文字、区块标题等）只能来自 `get_design_context` 返回的 JSX 文字内容，或 `get_screenshot` 截图中可见的文字。`get_design_metadata` 的 `name` 属性是图层名而非字符内容，**不得单独作为 UI 文案来源**。**禁止使用行业常见模式（如「猜你喜欢」「为你推荐」等）或 PRD 功能模块描述名称填充 UI 文案**——PRD 描述的是功能意图，不是设计定稿的界面文字。
12. 🚫 **禁止跳步**：Phase 1 必须依次执行步骤 1 → 2 → 3 → 4，每步用 `步骤 N / 4 XXX` 头部输出、列出本步所需字段、等用户回复「确认 / 修改」后才能进入下一步。**即使用户在初始命令中已经一次性提供了 4 步所需全部信息，也不得合并步骤或跳到 Phase 2**。违反本条视为录入流程未完成、不得写入文件。
13. 🚫 **数据效果必有来源**：步骤 4 中任一非空字段（预期收益 / 实际收益 / AB 测设置 / AB 测数据结果）必须在「数据来源」中标注出处（**PRD / 设计稿 / 用户输入**，三选一，不标注具体章节或节点）。若用户未填且 PRD/设计稿中也无相关内容，该项必须填「—」并标注来源「—」，**禁止用 AI 推测、行业经验、类比 case 的数据填空**。
14. 🚫 **数据效果两份必须语义一致**：reasoning.md 的「五、数据效果」四个子段（预期收益 / 实际收益 / AB 测设置 / AB 测数据结果）和 cases/{slug}.js 的 `data_effect.expected / actual / ab_setup / ab_result` 来自同一份用户确认结果。Phase 2 写两份文件时遵守以下三条规则：

    - **某项有内容**：cases.js 写入该 key，**正文字节完全一致**（含标点、加粗 Markdown、换行符 `\n`）。
    - **某项无数据**：md 写「—」，来源行也写「—」；cases.js **省略该 key**（不是空串 `''`、不是 `null`、不是「—」字符串），让 library.html `renderDataEffect()` 自动隐藏该卡片。
    - **无实际指标时不得占位**：如果某项没有具体数值/结论（如"PRD 未提供实验指标结果"、"已上线切量100%但无数据"），视同「无数据」，必须省略该 key，不得用"未提供"等占位文案填充。UI 不展示 = 不误导。
    - **4 项均无数据**：md 仍生成本章节、4 项都填「—」；cases.js 的 `data_effect` 整字段填 `null`（不是空对象 `{}`、不是 `undefined`），让 `renderDataEffect(null)` 不渲染整段。

    示例：仅有「预期收益」时
    ```js
    data_effect: {
      expected: '转化率 +0.2% / 月度 GMV +1.12 亿\n> 来源：PRD'
      // actual / ab_setup / ab_result 都不写，UI 自动隐藏对应 3 张卡片
    }
    ```

15. 🚫 **设计师与产品姓名必须有**：reasoning.md 正文「> 设计：xxx / 产品：xxx」、cases/{slug}.js、timeline/{slug}.js、index.js 的 `designer` 与 `pm` 字段**两个角色都必须至少有一位真实姓名**，不允许写入 TODO、待补充、未识别、空字符串。来源优先级：用户显式提供（`# 设计师：` / `# 产品：`）> Step 2 设计稿识别。任一角色为空时，在 Step 5 步骤 1 之前暂停录入并要求用户补充，收到补充后直接接续进入步骤 1，不重跑 Step 2/3/4。本条覆盖 v2.14 的「无前缀人名一律填 TODO」兜底——TODO 仅适用于其它字段，不适用于设计师/产品姓名。
16. 🚫 **正文来源不得暴露具体引用节点**：reasoning.md 正文中的需求背景、核心打法、状态枚举、数据效果、关联说明、经验沉淀等章节，来源标注可保留 PRD 具体章节，但设计稿来源只能写「设计稿」，禁止出现 Relay 节点 ID、`id=`、`node_id=`、`page_id=`、`节点 X:XXXXXX` 等调试型引用信息。`frontmatter.relay_source.node_id` 属于结构化元数据，可保留；正文中的设计稿来源必须去标识化。
17. 🚫 **cases.js 展示字段禁止双重转义换行**：`sections.background / goal / exclusions / data_effect.* / issues[].problem / patterns.*` 等会被 `library.html` 的 `mdToHtml()` 渲染的文本字段，JS 文件中只能使用单层换行转义 `\n` 表示换行，禁止写成 `\\n`。`\\n` 会在页面显示成字面量 `\n`，导致需求背景等区域出现异常文本。Phase 2 写完 cases/{slug}.js 后必须校验：若展示字段中 grep 到 `\\\\n`，必须修正为 `\n` 后再结束。

---

## 版本历史

- **v1.0** (2026-05-21) 初版
- **v1.1** (2026-05-22) 精简 Skill 文件，节省 60% token
- **v1.2** (2026-05-25) 新增 ui_pattern 字段、related_cases 关联说明
- **v2.0** (2026-05-27) 重构 reasoning.md 模板结构，对齐设计团队工作流
- **v2.1** (2026-05-31) 关键词拆分为业务词和组件词两类，组件词对照 floor-naming.md 标准命名表
- **v2.2** (2026-06-01) Phase 1 改为三步骤分步确认模式，标签推荐分组件/业务两类
- **v2.3** (2026-06-04) 标签体系重构为显性（通用楼层/垂类场景/二级承接）+ 隐性（动作/状态/交互/指标）两大类；新增 secondary-tags.md；业务标签限定为 business-tags.md 标准词，禁止通用词混入
- **v2.4** (2026-06-05) 实例标签体系重构：废弃 floor/vertical/secondary 三分类，改为统一 tags_instance（来源 instances.json）；新增 tags_gameplay 预留字段（空数组，人工配置）；UI 改为三级联动实例选择器
- **v2.5** (2026-06-09) Phase 2 写文件改为三文件同时生成：reasoning.md + cases/{slug}.js + cases.json 条目；缺少详情文件会导致预览弹层「无法加载」
- **v2.6** (2026-06-09) 新增双 PRD 字段：`# PRD本地：<path>`（仅 AI 分析用，不写入文档）+ `# PRD链接：<url>`（写入 frontmatter prd_url，展示为「查看 PRD」按钮）
- **v2.7** (2026-06-10) 明确禁止在 `tags_instance` / `keywords_component` 写入代码组件名等非 instances.json 词汇；cases.json 模板示例改为 `区块·模块名` 格式
- **v2.8** (2026-06-10) 删除 `get_design_context` 和 `get_variables`；`get_screenshot` 改为条件调用（已提供 `# 预览图:` 则跳过，否则调用取 URL 不保存 base64）
- **v2.9** (2026-06-10) 新增 `timeline/{slug}.js` 和 `timeline/index.js`，供同事时间轴调用；Phase 2 写文件从三个升为四个
- **v2.10** (2026-06-10) 删除 `ui_pattern` 字段（无前端代码消费，冗余）
- **v2.11** (2026-06-11) 删除「设计边界」「人工待确认」「对其他模块的影响」「设计规范关联」四个章节；新增冲突暂停规则、禁止推测、禁止跨 case 填充三条红线约束。
- **v2.12** (2026-06-11) 新增约束 10：状态枚举禁止从坐标扫描推断——坐标区间内发现的文字节点须截图确认父框架上下文后才可录入；空状态须有明确来源，禁止 AI 自行添加。（来源：国补关联类目推荐需求录入复盘）
- **v2.13** (2026-06-11) 新增约束 11：UI 文案必须来自截图或 metadata 文本节点，禁止用行业常见模式或 PRD 功能描述名称填充界面文字。（来源：国补关联类目推荐复盘，「猜您可能还需要」为 AI 凭常识填入，既不在 PRD 也不在设计稿中）
- **v2.14** (2026-06-11) Step 2 新增人名识别规则：UI/UX/UE 前缀 → 设计师，产品/PM 前缀 → 产品，可多位；无前缀人名一律 TODO。（来源：国补关联类目推荐复盘，沈天义被误填为设计师）
- **v2.15** (2026-06-11) 修正 timeline.date 和 cases.json updated 的来源：取 reasoning.md 正文「时间：」字段（设计完成日期），不得使用 last_updated（知识库录入日期）。（来源：国补关联类目推荐复盘，设计时间和最近更新均显示录入日期）
- **v2.16** (2026-06-12) Step 2 新增 `get_design_context` 调用步骤：`get_design_metadata` 只返回图层 name 属性，实际文字 characters 必须用 `get_design_context` 读取；人名节点图层名可能停留在占位符而文字内容已更新，因此人名提取必须调用 `get_design_context`，不得从 metadata name 属性推断。同步恢复 v2.8 删除的 `get_design_context`。（来源：国补支持混单结算录入，「某某某」图层名掩盖了真实姓名「王静祎 / 马兰」）
- **v2.17** (2026-06-12) 将 `get_design_context` 的使用范围从「人名专用」扩展为四类场景：A.人名+日期 B.功能名称/页面标题（层名为通用名时）C.UI文案（按钮/标签/区块标题，首选来源）D.设计标注引用节点。节点 ID 仅用于内部调用 get_design_context 确认原文，最终正文不得暴露具体节点。同步更新约束 11，明确 metadata name 属性不得单独作为 UI 文案来源。
- **v2.18** (2026-06-12) 预览图从手动粘贴改为自动调用 `export_image(scale=2, format=png)`：Step 2 ③ 由 get_screenshot 替换为 export_image，返回永久 CDN 链接直接写入 screenshots 字段；Step 3/3 补充归档不再展示手动粘贴入口。ERP 权限不足时降级为空字段 + 提示手动粘贴。
- **v2.19** (2026-06-17) `timeline/index.js` 的 `new_entry` 补入 `designer` / `pm` 字段，与 `timeline/{slug}.js` 保持一致。（来源：存量数据修复发现 index.js 条目长期缺失人名，根因是 new_entry 模板从未写这两个字段）
- **v3.0** (2026-06-18) 统一索引：`cases.json` + `timeline/index.js` 合并为 `index.js`（`window.CASES_INDEX`），录入时只维护一个索引文件；`timeline/{slug}.js` 和 `cases/{slug}.js` 两个详情文件继续独立维护，供弹层按需加载。
- **v3.1** (2026-06-23) Phase 1 从 3 步扩到 4 步，新增「步骤 4 数据效果确认」：4 类数据效果（预期收益 / 实际收益 / AB 测设置 / AB 测数据结果）逐项跟用户确认，用户输入与 PRD 候选并列展示，冲突时必须用户裁决不得 AI 自选；reasoning.md 新增「五、数据效果」章节（原"五、关联 Case"挪为"六"）；cases/{slug}.js 新增 `data_effect` 字段，与 md 章节字节一致，全空时填 null。同时新增 3 条硬约束：约束 12「禁止跳步」（即使初始命令完整也必须 4 步分别等待用户确认）、约束 13「数据效果必有来源」、约束 14「md 和 cases.js 的数据效果必须字节一致」。
- **v3.2** (2026-06-25) 约束 10 追加「状态枚举只保留主链路关键状态」：纯视觉容错、边界适配、不改变用户理解/审批判断/实现范围/验收标准的状态行一律不得写入状态枚举，也不在需求档案其它章节承载，归组件规范/设计稿本身管理。判断口径：删掉这一行用户是否仍能完成主链路决策——能则删。（来源：审批 skill `design-requirement-review` 状态枚举沉淀规则迁移）
- **v3.3** (2026-06-25) 「二、设计核心打法」章节注释追加排除清单与多动作排序规则：设计规范细节、组件实现规范、视觉/边界规则、QA 用例、工程实现细节一律不得写入核心打法（需求档案为精炼摘要，这些信息以设计稿标注/PRD/组件规范的原始形态留存）；多动作时按用户主决策路径排序，用户先感知、决定下一步行为的动作在前。（来源：审批 skill `design-requirement-review` 核心打法沉淀规则迁移）
- **v3.4** (2026-06-25) 「五、数据效果」章节追加写作要求：四项均服务于「快速理解需求价值」，给出推荐句式 `预计影响 X，核心看 Y。来源：PRD/设计稿/用户输入`；删除预算投入、ROI 测算公式、复杂分项口径、历史背景数据；弱化次级指标（保留指标名和方向，不抄具体数值）。同步精简来源标注：四个子段、约束 13、步骤 4 输出、约束 14 示例统一为「PRD / 设计稿 / 用户输入」三选一，不标注具体章节或节点。（来源：审批 skill `design-requirement-review` 数据效果沉淀规则迁移）
- **v3.5** (2026-06-25) 「六、关联 Case」章节注释追加强/弱关联判定标准：🔴 强关联限定为继承/对比/依赖/可复用模式四类关系；🟡 弱关联限定为局部参考；仅关键词命中、表面词汇相似、同一业务域但设计决策无关的 case 一律不写入。Step 7 同步追加写入前自检规则：AI 判断不出明确关联时直接留空，不写占位。（来源：审批 skill `design-requirement-review` 关联案例沉淀规则迁移）
- **v3.6** (2026-06-25) 「附：经验沉淀」章节注释追加写作约束：每条 Pattern 必须能指导未来需求的设计决策（决策权衡/入口策略/路径连续/指标选择/边界归属），提炼不出明确取舍时整段留空，不得填写「要注重用户体验」「要保持视觉一致性」等泛泛总结、单纯描述本次做了什么、或行业通识。附 ❌/✅ 反例对照。（来源：审批 skill `design-requirement-review` 经验沉淀规则迁移）
- **v3.7** (2026-06-25) 新增约束 15：设计师与产品姓名为强制字段，两个角色都必须至少有一位真实姓名，不允许写入 TODO/空。来源优先级：用户显式提供（`# 设计师：` / `# 产品：`）> Step 2 设计稿识别。任一角色为空时在 Step 5 步骤 1 之前暂停录入并要求用户补充，收到补充后直接接续进入步骤 1，不重跑 Step 2/3/4。本条覆盖 v2.14 的「无前缀人名一律填 TODO」兜底——TODO 仅适用于其它字段，不适用于设计师/产品姓名。
- **v3.8** (2026-06-29) 新增 Step 9：录入完成（文件写入 + 索引更新后）自动执行 `npm run thumbnails`，把本次新增 case 的首张截图压成 900×600 JPEG q80 写入 `preview/thumbnails/{slug}.jpg` 并更新 `_thumb_index.js`。脚本本身增量（已存在跳过），单次录入只处理新 case；脚本失败不阻塞录入流程。原本需要用户额外调 `/knowledge-preview` 才能拿到缩略图，现在录入完即完成全链路。
- **v3.9** (2026-06-29) 新增约束 16（现为约束 17）：cases.js 展示字段禁止双重转义换行。`sections.* / data_effect.* / issues / patterns` 等会进入 `mdToHtml()` 的文本只允许写单层 `\n`，禁止 `\\n`，并要求 Phase 2 后 grep 校验，避免页面展示字面量 `\n\n`。
- **v3.10** (2026-07-01) 新增约束 16：reasoning.md 正文中的设计稿来源去标识化，PRD 可保留具体章节，但禁止暴露 Relay 节点 ID、`id=`、`node_id=`、`page_id=` 等调试型引用信息；frontmatter 的结构化 `relay_source.node_id` 可保留。原约束 16（双重转义换行）顺延为约束 17。
- **v3.12** (2026-08-05) 优化数据指标提炼与缩略图流程：数据指标只保留带明确数值的核心指标；待上线/无数据时数据指标写「无」、`tags_metric` 写空数组、`data_effect` 写 `null`；录入后强制跑 `npm run thumbnails` 与 `npm run validate-case -- <slug>`，避免列表卡顿、详情缺失和无数据卡片噪音。
- **v3.11** (2026-07-06) 新增约束 18：index.js 维护只允许文本级操作。`preview/index.js`（window.CASES_INDEX）**禁止**用 `JSON.parse` + `JSON.stringify` / `json.dumps` / 其他"整体反序列化再重新格式化"的方式修改。原因：整体重新格式化导致 diff 爆炸（每行都变），后续 merge 冲突无法自动解决。允许：文本级追加新条目、字符串 replace 精确替换字段值、定位起止行删除条目。禁止：`data = json.loads(content); content = json.dumps(data, indent=...)`。（来源：2026-07-06 主图区 5 实例合并时误用 json.dumps 重排导致 9699 行冲突）
