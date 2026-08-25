---
name: relay-component-variant-generator
harness-version: 0
description: '当用户只完成了 Relay/Zero 中的一个基础组件，并描述该组件需要支持的状态、结构或业务逻辑时使用。 本 skill 会读取基础组件，理解用户描述的组件逻辑，判断哪些逻辑适合做成 Variant、Boolean、
  Instance Swap、Slot、Text Property，并基于原组件 clone 生成缺失状态，最终封装成符合 token 规范的组件集。

  '
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/.agents/skills/relay-component-variant-generator/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: during_design
  agentmesh-activation: explicit_only
  short-description: 当用户只完成了 Relay/Zero 中的一个基础组件，并描述该组件需要支持的状态、结构或业务逻辑时使用。 本 skill 会读取基础组件，理解用户描述的组件逻辑，判断哪些逻辑适合做成 Varian…
disable-model-invocation: true
---

# Relay Component Variant Generator

把 Relay/Zero 中的**单个基础组件**扩展成稳定、可复用、可实例化的组件集。目标是从用户已经画好的一个视觉基准出发，理解用户描述的状态、结构、业务逻辑、显隐、替换和插槽能力，然后正向 clone 出缺失状态，并封装为符合 token 规范的组件集。

本 skill 的定位是：**单个基础组件 + 组件逻辑 -> 正向生成组件变体与组件属性**。

它不是：**已有多状态 -> 反向封装组件集**。如果用户已经画好了多个完整状态，并希望把它们整理、归纳、封装为组件集，应交给 `relay-component-set-architect`。

核心原则：**原基础组件是视觉基准。所有生成状态必须从它 clone，不允许重画，不直接修改原始组件，不凭空新增颜色、字号、圆角、阴影或视觉风格。**

## 适用场景与不适用场景

适用场景：

- 用户只做了默认态，希望生成完整组件变体。
- 用户描述组件需要支持选中、未选中、禁用、loading、pressed 等状态。
- 用户描述卡片有未完成、已完成、过期等业务状态。
- 用户描述模块支持展开、收起。
- 用户描述组件有图标可替换、标签可显示隐藏、底部操作区可插入不同内容。
- 用户希望基于一个现有组件生成符合 token 规范的组件变体。

不适用场景：

- 用户已经画好了多个完整状态，并希望整理封装成组件集；应交给 `relay-component-set-architect`。
- 用户想重新设计组件视觉。
- 用户想生成一个全新组件，而不是基于现有基础组件扩展。
- 用户只想修改文案。
- 用户只想替换图标。
- 用户想做页面级多状态，而不是单个组件变体。
- 缺少基础组件节点。
- 缺少组件逻辑描述，且无法从上下文合理推断。

## 核心原则

执行本 skill 时必须遵守：

1. 原基础组件是视觉基准，所有状态必须从它 clone，不允许重画。
2. 先分析组件结构和用户逻辑，再生成变体计划。
3. 先输出变体生成计划，再执行画布操作。
4. 不直接修改原始组件。
5. 不凭空新增颜色、字号、圆角、阴影或视觉风格。
6. 所有生成状态必须优先复用原组件已有样式。
7. 如果项目存在 token 规范，必须使用已有 token。
8. 不允许直接写 hex。
9. 找不到对应 token 时，必须在计划中标注“缺少 token”，不要自行发明。
10. 不要把所有差异都做成 Variant。
11. 状态语义强、影响多个节点的差异，才做 Variant。
12. 局部显隐差异做 Boolean。
13. 同类组件替换做 Instance Swap。
14. 复杂业务区域做 Slot。
15. 纯文案变化做 Text Property。
16. 变体轴最多 2-3 个，默认不超过 12 个变体。
17. 超过 12 个变体时必须停止，并建议拆分组件或改用 Boolean / Instance Swap / Slot。
18. 生成状态必须保持属性命名一致、节点命名一致、布局稳定。
19. 生成后必须检查文本重叠、内容溢出、尺寸异常和 token 使用情况。
20. 不生成没有业务意义的装饰性变体。

## 输入

必需输入：

- 一个 Relay/Zero 基础组件节点，或用户当前选中的单个组件。
- 用户描述的组件逻辑或状态需求。

可选输入：

- 组件名称。
- 组件分类。
- 需要生成的状态。
- 需要暴露的属性。
- 哪些区域必须做 Slot。
- 哪些元素必须做 Instance Swap。
- 哪些显隐必须做 Boolean。
- 项目的 token 文档。
- 已有组件库规范。
- 已有属性命名规范。

## 前置读取流程

执行前必须完成：

1. 解析 Relay 链接，提取：
   - `fileKey`
   - `nodeId`
   - `pageId`
2. 调用 Relay/Zero 设计读取能力：
   - `get_design_metadata`
   - `get_screenshot`
   - 如有必要，读取父级、子级和同级节点。
3. 写任何 design script 前，必须读取 use design script 相关资源：
   - 先通过资源列表找到 `use-design-script/SKILL.md`。
   - 再读取 `use-design-script/references/relay-plugin-api-index.md`。
   - 需要确认精确属性、方法、参数或返回类型时，再读取或搜索 `relay-plugin-api.d.ts`。
4. 确认当前环境是否支持：
   - clone 节点
   - 创建组件
   - 创建组件集
   - 创建 Variant 属性
   - 创建 Boolean 属性
   - 创建 Text Property
   - 创建 Instance Swap
   - 创建或模拟 Slot
   - 修改 auto layout
   - 修改显隐
   - 修改填充、描边、透明度
   - 修改尺寸、约束、旋转
5. 读取项目 token / design system 相关文档：
   - color token
   - typography token
   - spacing token
   - radius token
   - shadow token
   - component token
   - semantic token

如果当前项目没有明确 token 文档：

- 优先复用原组件已有样式。
- 不主动发明新 token。
- 在计划中标注：“未找到 token 文档，生成状态将基于原组件已有样式克隆和调整”。

## 基础组件结构分析

执行前必须分析基础组件结构，并输出：

```text
组件名称：
组件类型：
原始节点 ID：
是否已经是组件：
是否已经是组件集：
根节点尺寸：
布局方式：
auto layout 信息：
主要子节点：
文本节点：
图标节点：
图片节点：
背景节点：
描边节点：
状态层候选：
显隐层候选：
可替换节点：
可插槽区域：
可交互区域：
当前 token 使用情况：
潜在风险：
```

如果基础组件结构不完整、无法作为生成来源，必须停止，不继续执行。

## 用户逻辑解析

需要把用户自然语言转成组件属性架构：

```text
整体状态 -> Variant
局部显隐 -> Boolean
同类组件替换 -> Instance Swap
复杂业务区域 -> Slot
纯文案变化 -> Text Property
```

示例一：

用户说：

```text
这个卡片有未完成、已完成、过期三种状态，右侧按钮可替换，底部说明可有可无。
```

应解析为：

```text
Variant：
- 状态=未完成
- 状态=已完成
- 状态=已过期

Instance Swap：
- 右侧按钮

Boolean：
- 显示底部说明

Text Property：
- 标题
- 描述
- 状态文案
```

示例二：

用户说：

```text
这个模块支持展开收起，标题和描述可改，右上角 icon 可以替换。
```

应解析为：

```text
Variant：
- 展开状态=收起
- 展开状态=展开

Text Property：
- 标题
- 描述

Instance Swap：
- 右上角图标
```

## 组件属性决策规则

### 什么时候用 Variant

当差异代表组件整体状态，并影响多个视觉属性或结构表现时，使用 Variant。

适合做 Variant：

- 默认 / 选中 / 未选中
- 默认 / 禁用
- 默认 / 加载中 / 成功 / 错误
- 未完成 / 已完成 / 已过期
- 展开 / 收起
- 主类型 / 次类型 / 危险类型
- 小 / 中 / 大
- 横向 / 纵向
- 强提醒 / 弱提醒
- 空态 / 正常态 / 异常态
- 已领取 / 未领取 / 已失效
- 已安装 / 未安装 / 安装中
- 已读 / 未读
- 锁定 / 解锁

判断标准：

```text
如果这个差异不仅是一个图层显隐，而是代表组件整体状态变化，就用 Variant。
如果这个状态会影响背景、文字、图标、描边、布局中的多个节点，也应该用 Variant。
如果这个差异会被设计、开发、测试作为一种状态理解，也应该用 Variant。
```

不适合做 Variant：

- 只是换文案。
- 只是换图标。
- 只是显示 / 隐藏一个标签。
- 只是换图片。
- 只是业务内容不同。
- 用 Boolean 或 Instance Swap 更轻量就能解决。

### 什么时候用 Boolean

当差异只是某个元素显示或隐藏，且不会改变组件整体状态时，使用 Boolean。

适合做 Boolean：

- 显示图标 / 隐藏图标
- 显示徽标 / 隐藏徽标
- 显示标签 / 隐藏标签
- 显示副标题 / 隐藏副标题
- 显示关闭按钮 / 隐藏关闭按钮
- 显示分割线 / 隐藏分割线
- 显示辅助说明 / 隐藏辅助说明
- 显示底部操作区 / 隐藏底部操作区
- 显示右侧操作区 / 隐藏右侧操作区
- 显示进度条 / 隐藏进度条
- 显示倒计时 / 隐藏倒计时

判断标准：

```text
如果差异可以用“是否显示 xxx”表达，就优先用 Boolean。
如果这个差异只影响一个局部节点，不改变组件整体语义，就用 Boolean。
如果用 Variant 会导致组合爆炸，就优先改成 Boolean。
```

### 什么时候用 Instance Swap

当某个区域结构固定，但需要在同类组件之间替换时，使用 Instance Swap。

适合做 Instance Swap：

- 左侧图标可替换
- 右侧操作 icon 可替换
- 状态 icon 可替换
- 头像可替换
- 商品图可替换
- 奖品卡可替换
- 按钮实例可替换
- tag 组件可替换
- badge 组件可替换
- 主按钮可替换
- 辅助按钮可替换

判断标准：

```text
如果替换对象本身也是组件，并且位置、尺寸、约束基本稳定，就用 Instance Swap。
如果用户未来会在同一区域切换不同图标、按钮、标签、徽标，就用 Instance Swap。
```

不适合做 Instance Swap：

- 替换后布局完全不同。
- 替换内容高度不可控。
- 替换对象不是同类结构。
- 替换区域没有稳定约束。
- 替换对象复杂度很高，应改用 Slot。

### 什么时候用 Slot

当某个区域需要承载外部传入的复杂内容，并且内容类型不固定时，使用 Slot。

适合做 Slot：

- 卡片底部操作区
- 弹窗内容区
- 列表 item 右侧操作区
- 模块头部右侧区域
- 任务卡片扩展内容区
- 底 bar 上方复合组件区
- 通知条右侧操作区
- 商品卡片营销扩展区
- 自定义内容区
- 业务运营位
- 复合组件容器

判断标准：

```text
如果这个区域未来会放入不同结构的模块，而不是只换一个图标或文案，就用 Slot。
如果这个区域是业务方自定义内容入口，就用 Slot。
如果这里的内容复杂度超过一个简单 Instance Swap，就用 Slot。
```

不适合做 Slot：

- 只是换文案。
- 只是换 icon。
- 只是显示或隐藏一个标签。
- 内容结构固定且可用 Instance Swap 解决。

### 什么时候用 Text Property

当差异只是文案内容变化时，使用 Text Property。

适合做 Text Property：

- 标题
- 副标题
- 描述
- 按钮文案
- 数字
- 价格
- 状态文案
- 提示文案
- 倒计时文案
- 说明文案

判断标准：

```text
如果只改文字，不改变结构、不改变状态、不改变样式，就使用 Text Property。
```

不适合做 Text Property：

- 文案变化导致结构变化。
- 文案变化伴随状态变化。
- 文案变化需要不同图标、背景或按钮规则。

## Token 生成规则

这是本 skill 的重点。因为本 skill 会正向生成缺失状态，所以必须严格遵守 token 规范。

规则：

1. 生成状态时不允许直接写 hex。
2. 不允许凭空新增颜色 token。
3. 不允许凭空新增字号 token。
4. 不允许凭空新增圆角 token。
5. 不允许凭空新增阴影 token。
6. 不允许改变原组件的视觉风格。
7. hover / pressed / disabled / selected / error / success / warning / active 等状态必须优先使用已有语义 token。
8. 如果找不到对应 token，应在计划里标记：
   - 缺少 selected token
   - 缺少 disabled token
   - 缺少 error token
   - 缺少 hover token
9. 如果项目没有 token 文档，则优先从原组件已有样式中提取相邻状态策略。
10. 生成的新状态必须能解释清楚使用了哪个 token 或从哪个原样式继承而来。

禁止在脚本中硬编码 `#RRGGBB`、`rgb()`、`rgba()` 作为新状态样式。如果必须读取原组件已有颜色用于复制，应说明这是“继承原组件已有样式”，不是新增 token。

## 正向生成流程

### Step 1：读取基础组件

- 读取基础组件节点。
- 获取截图和结构。
- 判断它是否适合作为生成状态的基础。
- 如果它已经是组件集，需要谨慎处理，避免破坏已有属性。

### Step 2：解析用户逻辑

将用户描述拆成：

```text
整体状态 -> Variant
局部显隐 -> Boolean
同类组件替换 -> Instance Swap
复杂业务区域 -> Slot
纯文案变化 -> Text Property
```

### Step 3：生成组件属性架构

输出：

```text
组件名：
组件类型：
建议组件集名称：
Variant 轴：
Boolean 属性：
Instance Swap 属性：
Slot 区域：
Text Property：
预计生成变体数量：
是否存在变体爆炸风险：
```

### Step 4：生成变体计划

在执行画布操作前，必须输出计划：

```text
我已识别当前基础组件，并生成如下变体计划：

组件名：
组件类型：
原始节点 ID：
目标组件集名称：

一、建议生成的 Variant
- xxx：原因是 xxx；需要修改 xxx 节点；使用 xxx token

二、建议设置的 Boolean
- xxx：原因是 xxx；控制 xxx 节点显隐

三、建议设置的 Instance Swap
- xxx：原因是 xxx；替换 xxx 区域

四、建议设置的 Slot
- xxx：原因是 xxx；用于承载 xxx 内容

五、建议设置的 Text Property
- xxx：原因是 xxx

预计生成变体数量：
是否超过 12 个：
是否存在 token 缺失：
是否需要拆分组件：
不会修改原始组件，将基于 clone 执行。
```

只有当计划安全时才继续执行。如果计划暴露出停止条件，必须停止并输出原因。

### Step 5：执行生成

只有当计划安全时才执行：

- clone 原始组件。
- 为每个 Variant 生成一个状态。
- 应用符合 token 规范的样式变化。
- 创建组件或组件集。
- 添加 Boolean 属性。
- 添加 Text Property。
- 添加 Instance Swap。
- 添加 Slot 或 Slot 占位。
- 保持 auto layout 稳定。
- 保持节点语义命名一致。
- 保持属性命名一致。
- 不改变基础视觉风格。

执行时不要直接修改原始组件。应在原组件旁边或合适位置生成 clone 状态，并将 clone 结果组件化。

## 常见状态生成规则

### 选中 / 未选中

选中态：

- 显示 selected icon / indicator。
- 文本切换为 selected token。
- 背景或描边切换为 selected token。
- 图标切换为 active 样式。
- 不改变组件尺寸。

未选中态：

- 隐藏 selected icon / indicator。
- 文本恢复默认 token。
- 背景或描边恢复默认 token。
- 保持点击热区一致。

### 展开 / 收起

展开态：

- 显示内容区。
- 箭头旋转 180 度，或切换方向。
- 容器高度改为 hug content，或使用展开后的固定高度。
- 展开内容必须参与 auto layout。
- 不允许文本重叠。
- 不允许内容溢出。

收起态：

- 隐藏内容区。
- 箭头恢复默认方向。
- 容器高度恢复收起高度。
- 保留标题区和展开入口。

### 禁用

- 降低整体 opacity，或使用 disabled token。
- 文本和图标切换为 disabled token。
- 禁止强高亮。
- 不删除节点。
- 不改变尺寸。
- 禁用态下不表现 hover / pressed。

### Hover / Pressed

Hover：

- 只做轻量反馈。
- 可调整背景、描边、透明度或阴影。
- 不改变尺寸。
- 不移动文字和图标。

Pressed：

- 使用更明确的按压反馈。
- 优先调整背景深浅或透明度。
- 不造成布局跳动。

### Loading

- 保持组件尺寸。
- 主文案可替换为“加载中”或隐藏。
- 可显示 loading icon / spinner。
- 如果原组件没有 loading 图标，不主动创造复杂图形。
- loading 状态下默认不可重复点击。

### Error / Success / Warning

Error：

- 使用 error token。
- 显示错误文案或错误图标。
- 不使用过度装饰性警告样式。

Success：

- 使用 success token。
- 显示成功图标或成功文案。
- 不破坏组件结构。

Warning：

- 使用 warning token。
- 保持提示层级清晰。
- 不影响主操作区域布局。

## 变体数量控制

规则：

```text
单个组件最多 2-3 个 Variant 轴。
默认不超过 12 个 Variant 组合。
超过 12 个必须停止，不直接生成。
```

示例：

```text
状态 4 个 × 尺寸 3 个 × 显示图标 2 个 × 显示徽标 2 个 = 48 个
```

此时不应该生成 48 个变体，而应改为：

```text
Variant：状态、尺寸
Boolean：显示图标、显示徽标
```

如果仍然超过 12 个变体，必须停止，并建议：

- 拆分为多个组件。
- 将局部差异改为 Boolean。
- 将替换内容改为 Instance Swap。
- 将复杂业务区域改为 Slot。
- 缩减 Variant 轴或状态值。

## 命名规范

### 组件集命名

```text
分类/组件名
```

示例：

```text
Navigation/Bottom Bar
Card/Task Card
Input/Search Input
Feedback/Notice Bar
```

### Variant 属性命名

推荐：

```text
状态
交互状态
展开状态
尺寸
类型
强调级别
业务状态
```

### Boolean 属性命名

推荐：

```text
显示图标
显示徽标
显示标签
显示副标题
显示按钮
显示分割线
显示说明
显示扩展区
```

### Instance Swap 属性命名

推荐：

```text
左侧图标
右侧图标
主按钮
辅助按钮
状态图标
头像
封面图
标签组件
徽标组件
```

### Slot 命名

推荐：

```text
头部右侧插槽
内容插槽
底部操作插槽
扩展内容插槽
右侧操作插槽
营销内容插槽
复合组件插槽
```

### Text Property 命名

推荐：

```text
标题
副标题
描述
按钮文案
状态文案
提示文案
数量
价格
```

## 执行后输出

执行完成后必须输出：

```text
已完成组件变体生成。

组件集名称：
组件集 node ID：
原始节点 ID：
生成 Variant 数量：

Variant：
- xxx

Boolean：
- xxx

Instance Swap：
- xxx

Slot：
- xxx

Text Property：
- xxx

Token 使用：
- xxx

检查结果：
- 原始组件未被修改
- 所有状态均来自 clone
- 属性命名一致
- 同类节点命名一致
- 组件集可正常调用
- 变体数量合理
- auto layout 未破坏
- 文本无重叠
- 内容无溢出
- token 使用符合规范
```

如果有截图能力，必须同时输出或记录生成后的组件集截图、关键 node ID 和检查结论。

## 检查规则

执行后必须检查：

- 原始组件未被修改。
- 所有状态来自 clone。
- 组件集可正常调用。
- 变体数量没有爆炸。
- 属性命名一致。
- 同类节点命名一致。
- auto layout 没有破坏。
- 文本没有重叠。
- 内容没有溢出。
- Boolean 只控制显隐。
- Instance Swap 对象是同类结构。
- Slot 区域尺寸和约束合理。
- Text Property 没有误做成 Variant。
- 新生成状态符合 token 规范。
- 没有直接写 hex。
- 没有新增未定义 token。
- 没有重画原组件。

如发现严重尺寸异常、文本重叠或内容溢出，必须停止继续扩展，并输出风险与建议处理方式。

## 停止条件

遇到以下情况必须停止，不继续执行：

- 无法读取节点。
- 用户没有提供基础组件。
- 用户没有描述组件逻辑，且无法合理推断。
- 基础组件结构不完整，无法作为生成来源。
- 变体数量超过 12 个。
- 缺少关键 token，无法生成符合规范的状态。
- design script API 不支持必要的组件属性操作。
- 执行后出现严重尺寸异常、文本重叠或内容溢出。
- 生成状态需要重新设计，而不是基于原组件扩展。

停止时输出：

```text
当前不适合直接生成组件变体。

原因：
建议处理方式：
原始组件是否被修改：否
```

## 执行边界

- 必须先输出变体生成计划，再执行画布操作。
- 必须 clone 原始组件，不直接修改原图。
- 必须判断 Variant / Boolean / Instance Swap / Slot / Text Property。
- 不要把所有差异都做成 Variant。
- 必须遵守 token 规范，不直接写 hex，不新增未定义 token。
- 必须控制变体数量，默认不超过 12 个。
- 必须输出组件属性清单、token 使用说明、node ID、截图和检查结果。
- 如果当前任务其实是“已有多状态 -> 反向封装组件集”，立即切换到 `relay-component-set-architect`。
