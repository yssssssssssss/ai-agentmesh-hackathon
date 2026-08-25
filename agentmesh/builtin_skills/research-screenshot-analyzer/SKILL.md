---
name: research-screenshot-analyzer
description: '通过 DesignPeek 本地工具收集、整理并分析用研/竞品截图。适用于用户需要采集 App 截图、整理页面素材、做单图 UI 视觉识别、按研究主题生成跨平台截图对比、导出分析报告，或希望其他 AI/脚本通过 HTTP
  API 调用截图分析能力时。

  边界：本 skill/tool 负责截图素材采集、结构化整理、AI 视觉识别和报告生成，不代替正式研究结论或业务策略判断。

  '
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/horizontal/user-research/skills/research-screenshot-analyzer/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: pre_design
  agentmesh-activation: explicit_only
  short-description: 采集并分析用研或竞品截图，输出截图视觉分析；不处理访谈材料，不生成正式用研结论。
disable-model-invocation: true
---

# Research Screenshot Analyzer — 用研/竞品截图采集与 AI 视觉分析

DesignPeek / 设计透视是一个本地运行的截图素材工具，用于把 App 竞品截图从「散落在相册和文件夹里」整理成可分析、可检索、可导出的研究素材。它可以由设计师通过浏览器使用，也可以由 AI 助手或脚本通过 HTTP API 调用。

本条目属于 **tool 型 skill**，提供截图采集、视觉识别和报告导出的执行能力。

## 何时使用

当用户出现以下诉求时，可以使用本工具：

- 收集竞品 App 截图，并希望自动归档到本地素材库。
- 围绕某个研究主题整理多款 App 的页面截图。
- 需要识别截图中的页面类型、UI 组件、视觉风格、布局模式和交互特征。
- 需要把一组截图按模块归类，生成跨平台对比报告。
- 需要将截图分析结果导出为 HTML 报告，供评审、归档或后续沉淀到 design wiki。
- 需要让其他 AI 工具、脚本或自动化流程调用截图上传、分析和导出能力。

## 不适用场景

- 要求自动登录、自动浏览、自动抓取竞品 App 页面。
- 要求云端多人实时协作管理截图。
- 要求对未脱敏业务截图、用户隐私数据、订单信息、账号信息进行外部模型分析。
- 只需要竞品策略判断、战略意图推断或跟进决策矩阵，而没有截图采集和视觉识别需求。

本工具输出的 AI 分析结果必须经过人工校正后再进入正式研究结论。截图中的视觉现象可以作为证据，策略意图和设计建议需要结合业务背景与研究证据二次判断。

## 输入

| 输入 | 类型 | 必填 | 说明 |
|---|---|---|---|
| 截图文件 | image | 是 | 支持 png、jpg、jpeg、webp、heic |
| App 名称 | string | 否 | 可由 iPhone 快捷指令、手动分类或 AI 识别补全 |
| 页面类型/模块 | string | 否 | 如：首页、搜索页、详情页、转化入口、个人中心 |
| 研究项目名称 | string | 项目分析时必填 | 如：公益频道竞品分析 |
| 研究项目描述 | string | 否 | 描述研究主题、竞品范围和关注问题 |
| 备注/收藏 | string/bool | 否 | 用于人工标记重点截图 |

## 输出

| 输出 | 格式 | 说明 |
|---|---|---|
| 截图清单 | JSON | 本地截图路径、状态、App、页面类型、分析结果 |
| 单图分析 | JSON | App 名、页面类型、UI 组件、视觉风格、布局模式、交互特征、一句话总结 |
| 项目级分析 | JSON | 模块归类、平台对比、触点分析、设计亮点、综合建议 |
| 报告导出 | HTML | 自包含离线报告，截图以内嵌缩略图方式保存 |

## 工作流

### Stage 1 · 截图采集

1. 设计师通过本地网页、iPhone 快捷指令或 HTTP API 上传截图。
2. 工具将截图保存到本地 `screenshots/`。
3. 如果提供 App 名，按 App 自动命名并归档；否则进入待整理区。
4. macOS 环境下可异步执行 OCR，并把文本写入分析数据。

### Stage 2 · 素材整理

1. 在管理页中查看待整理截图。
2. 按 App、页面类型或研究模块进行分类。
3. 对重点截图添加收藏或备注。
4. 将相关截图加入同一个研究项目。

### Stage 3 · AI 视觉分析

1. 对单张截图执行视觉分析，提取页面类型、组件、视觉风格、布局和交互信息。
2. 对项目内多张截图执行项目级分析，归类为 4-6 个核心模块。
3. 输出平台对比、模块差异、设计亮点和可参考建议。
4. 人工检查 AI 结果，修正误识别的 App、模块或结论。

### Stage 4 · 报告导出与沉淀

1. 导出自包含 HTML 报告。
2. 将报告中的关键截图、对比表和洞察摘要沉淀到 design wiki。

## 调用方式

### 设计师使用

1. 在本地安装并启动 DesignPeek。
2. 浏览器访问 `http://localhost:8765`。
3. 上传或从手机发送截图。
4. 创建研究项目并添加截图。
5. 执行项目分析。
6. 导出报告。

安装说明见 [references/SETUP.md](references/SETUP.md)。

### AI 助手或脚本使用

DesignPeek 启动后可通过 HTTP API 调用，典型动作包括：

- 上传截图：`POST /api/upload/image`
- 获取截图列表：`GET /api/screenshots`
- 单图分析：`POST /api/analyze`
- 创建项目：`POST /api/projects`
- 更新项目截图：`PUT /api/projects/{pid}`
- 项目级分析：`POST /api/projects/{pid}/analyze`
- 导出报告：`GET /api/projects/{pid}/export`

接口说明见 [references/API.md](references/API.md)，调用示例见 [references/EXAMPLES.md](references/EXAMPLES.md)。

## 安全边界

- 默认本地运行，截图和分析结果保存在本机。
- `.env` 只保存本地 AI Key，禁止提交、打包或上传。
- `screenshots/` 和 `data/` 默认包含个人素材和分析结果，禁止作为工具包上传。
- 执行 AI 分析时，图片可能会发送到所配置的模型 provider 或公司网关；敏感截图必须先脱敏。
- 进入 design wiki 的内容只应包含工具说明、脱敏示例和可复用结论，不包含原始研究数据。

详细说明见 [references/SECURITY.md](references/SECURITY.md)。

## 建议入库结构

建议作为工具型 skill 放入：

```text
jd-design-system-md-v16/horizontal/user-research/skills/research-screenshot-analyzer/
  SKILL.md
  README.md
  downloads/
    designpeek-v0.1.zip
  examples/
    good/
    bad/
  anti-patterns.md
  references/
    API.md
    SETUP.md
    SECURITY.md
    PACKAGING.md
    EXAMPLES.md
```

## 后续规划（当前未实现）

以下能力不属于 V0.1 当前功能。为了从本地工具升级为更稳定的团队通用能力，建议按优先级补充：

1. 增加 `GET /api/health`，供 AI 助手判断服务是否可用。
2. 增加 `GET /api/schema` 或 OpenAPI 描述，固定输入输出协议。
3. 支持 `format=json|markdown|html` 导出。
4. 将分析 prompt 从代码抽离到 `prompts/`，便于不同研究场景复用。
5. 增加 CLI，例如 `designpeek analyze --project xxx`。
6. 增加异步任务状态查询，避免多图分析长时间阻塞。
7. 将源码整理为标准 Python package，方便安装和版本管理。

## 关联文档

| 文档 | 内容 |
|---|---|
| [references/API.md](references/API.md) | HTTP API 说明 |
| [references/SETUP.md](references/SETUP.md) | 安装与启动 |
| [references/SECURITY.md](references/SECURITY.md) | 安全与隐私边界 |
| [references/PACKAGING.md](references/PACKAGING.md) | 打包与入库建议 |
| [references/EXAMPLES.md](references/EXAMPLES.md) | 调用示例 |
