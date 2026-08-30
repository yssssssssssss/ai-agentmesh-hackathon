# 2C-DesignWiki Skill 接入 AgentMesh 候选清单

> 分析日期：2026-08-17
> 来源范围：`2C-DesignWiki/` 中的全部 `SKILL.md`。
> 目标项目：AgentMesh（FastAPI + React/Vite + Personal Agent + `$` Skill 命令 + 三级记忆 + Tool Grant + Risk Approval）。
> 历史说明：本文保留 2026-08-17 的候选分析。2026-08-25 已完成全量目录接入：84 个唯一领域 Skill 均可显式启动，其中原 10 个继续参与自动编排；11 个 Legacy 命令保持不变。当前 57 个为完整执行状态，27 个标记为“工具待接通”。

## 1. 2026-08-17 历史扫描结果（旧解析口径）

当时使用的旧扫描口径统计为：

- 86 个 `SKILL.md` 文件；
- 80 个带标准 frontmatter 的 Skill 文件；
- 去重后约 78 个独立 Skill；
- 其余文件主要是场域路由 Skill 或重复发布副本。

现行同步器会解析全部 86 个源文件，并将两组内容重复副本各保留一个规范来源，因此当前准确结果为
84 个唯一 Skill。上面的“约 78 个”仅用于保留旧分析过程，不代表当前目录数量。

结合 AgentMesh 当前的聊天 Skill 注册表、文件上传、资料获取、数据查询、风险审批、项目记忆和 O2 工具能力，以下 Skills 适合分阶段接入。

> 历史决策说明：下方候选清单、优先级和实施阶段均是 2026-08-17 的接入建议，不代表 2026-08-25 的当前接入状态。
>
> 注意：目录接入、Wiki 资源读取和显式命令入口不等于外部工具已接通。27 个 Skill 声明的 Bash、文件或 Zero/JoySpace 等能力仍需独立适配、授权和审批；系统不会因导入 `SKILL.md` 自动扩权。

## 2. 可接入 Skill 清单

| 优先级 | Wiki Skill | 建议 `$` 命令 | 主要功能 | 接入条件 | 难度 |
|---|---|---|---|---|---|
| P0 | `generate-research-plan` | `$research.plan` | 把模糊研究需求整理成目标、方法、样本、排期和交付物完整研究方案 | LLM + 项目记忆，复用 `$brief.create` | 低 |
| P0 | `generate-interview-guide` | `$research.interview` | 根据研究目标生成访谈开场、主问题、追问和收尾提纲 | LLM + 模板输出 | 低 |
| P0 | `generate-survey` | `$research.survey` | 生成问卷结构、题型、量表、跳转逻辑和合规自检 | LLM + 结构化输出 | 低 |
| P0 | `generate-usability-test` | `$research.usability` | 生成可用性测试任务、主持脚本、观察表和 SEQ/SUS 度量计划 | LLM + 项目上下文 | 低 |
| P0 | `jobs-to-be-done` | `$product.jtbd` | 把表层需求还原成用户任务、障碍、四力和机会点 | LLM + 项目/团队记忆 | 低 |
| P0 | `issue-prioritization` | `$issue.prioritize` | 使用严重度、RICE、ICE、影响×难度等方法排序问题 | LLM；可接项目 Issue 数据 | 低 |
| P0 | `build-experience-metrics` | `$metrics.experience` | 建立体验北极星、HEART/GSM 指标、护栏和采集口径 | LLM + `$data.query` | 低 |
| P0 | `competitive-analysis` | `$analysis.competitor` | 做竞品范围、战略意图、体验五要素、SWOT 和机会分析 | 复用 `$research.request` 和来源绑定 | 中 |
| P0 | `prd-feasibility` | `$prd.review` | 从业务逻辑、用户体验、数据预估和副作用评估 PRD | 文件上传 + LLM + 项目记忆 | 中 |
| P0 | `leader-report` | `$report.leader` | 根据项目进度、活动、成果和风险生成管理层汇报页 | 读取 Activity/Audit/Task/Memory 数据 | 中 |
| P1 | `structure-interview-transcript` | `$research.transcript` | 把单场访谈逐字稿整理成受访者背景、主题发现、原话和痛点 | 文档上传、长文本切分 | 中 |
| P1 | `synthesize-qualitative-insights` | `$insight.qualitative` | 跨多场访谈聚类主题，形成带证据的定性洞察 | 多文档检索、来源引用 | 中 |
| P1 | `code-open-feedback` | `$feedback.code` | 对评价、工单、开放题进行模块、问题、情感、严重度编码 | CSV/Excel 解析 + 批处理 | 中 |
| P1 | `feedback-insight` | `$feedback.insight` | 从用户反馈中提取旅程痛点、S0/S1/S2、原声和改进方案 | Python 执行环境、Excel/CSV、产物存储 | 中高 |
| P1 | `generate-persona` | `$insight.persona` | 从访谈和行为数据聚类用户，生成人物角色和需求痛点 | 多文档检索 + 结构化输出 | 中 |
| P1 | `journey-map` | `$experience.journey` | 生成阶段、行为、触点、情绪、痛点和机会构成的用户旅程图 | LLM + HTML/JSON artifact | 中 |
| P1 | `analyze-satisfaction` | `$analysis.satisfaction` | 分析 CSAT/NPS/CES 驱动因素、IPA 四分图和异动原因 | 数据表解析、统计计算 | 中高 |
| P1 | `conversion-funnel-analysis` | `$analysis.funnel` | 计算分步转化和流失，按人群下钻并定位根因 | 复用 `$data.query`，增加漏斗计算器 | 中 |
| P1 | `feature-adoption-analysis` | `$analysis.adoption` | 分析曝光、激活、使用、复用、首次采纳和功能留存 | 事件数据、cohort 计算 | 中 |
| P1 | `design-abtest-analysis` | `$analysis.abtest` | 对比设计实验方案，结合数据判断差异、收益和下一步 | 实验数据 + 截图输入 | 中高 |
| P1 | `industry-market-analysis` | `$analysis.market` | 做市场、供给、竞品、体验、机会和策略的分阶段行业分析 | `$research.request` + 多来源合成 | 中 |
| P1 | `register-experiment` | `$experiment.save` | 把 A/B 实验结论结构化后保存到项目或团队记忆 | 映射到候选团队记忆和人工审核 | 中 |
| P1 | `query-experiment-conclusions` | `$experiment.search` | 按场景、人群和组件反查历史实验及避坑建议 | 映射到项目/团队记忆搜索 | 低 |
| P2 | `run-heuristic-evaluation` | `$ux.heuristic` | 按尼尔森十大原则进行专家走查和严重度评级 | 图片/原型输入 + Vision 模型 | 高 |
| P2 | `accessibility-review` | `$ux.accessibility` | 按 POUR、读屏、键盘、颜色、控件等规则检查无障碍 | Vision + 页面/浏览器检查工具 | 高 |
| P2 | `prelaunch-usability-review` | `$ux.prelaunch` | 对上线前方案进行模拟用户测试和 before/after 评估 | Vision + 项目目标和截图 | 高 |
| P2 | `AI-Decision-Lab` | `$design.decision` | 对单稿、多稿或多页面流程做用户、业务、设计、数据多视角评审 | 多图输入、Vision、HTML artifact | 高 |
| P2 | `research-screenshot-analyzer` | `$research.screenshot` | 采集、分类和分析研究/竞品截图，生成跨平台对比报告 | 浏览器/截图工具 + Vision | 高 |
| P2 | `design-review` | `$design.review` | 检查 Token、布局、交互和业务规范符合度 | Relay/Zero 读取工具或截图模式 | 高 |
| P2 | `motion-handoff-export` | `$design.motion` | 将 Web Demo 动效整理成时间轴、重播卡片和研发交付 HTML | 浏览器抓取 + HTML artifact | 高 |
| P2 | `prototype-generation` | `$design.prototype` | 从 PRD、截图或文字生成可编辑高保真原型 | Relay/Zero MCP + 写操作审批 | 高 |
| P2 | `relay-to-design-md` | `$relay.extract` | 将 Relay 设计稿提取为结构化设计规范 bundle | Relay/Zero MCP + 文件写入审批 | 高 |
| P2 | `relay-to-component-pipeline` | `$relay.component` | 编排设计稿提取、组件封装、规范长图、HTML 和校验 | 多 Skill 编排器 + checkpoint | 高 |
| P2 | `ruler-annotation` | `$design.annotate` | 给设计稿生成尺寸、间距、结构和内容标注 | Relay/Zero 写工具 + 人工确认 | 高 |
| P2 | `joyspace-docs` | `$doc.joyspace` | 读取、创建和发布 JoySpace 文档 | JoySpace MCP/O2 工具 + 授权审批 | 高 |

## 3. 最推荐先接入的 10 个

按 AgentMesh 当前能力和投入产出比排序：

1. `generate-research-plan`
2. `generate-interview-guide`
3. `generate-survey`
4. `generate-usability-test`
5. `issue-prioritization`
6. `jobs-to-be-done`
7. `build-experience-metrics`
8. `query-experiment-conclusions`
9. `competitive-analysis`
10. `prd-feasibility`

这些能力主要依赖现有 LLM、项目记忆、来源引用和 `$research.request`，不需要先接通 Relay、Vision 或复杂 Python 沙箱。

## 4. 暂不建议直接接入

| Skill 类别 | 示例 | 原因 |
|---|---|---|
| 特定组件生成器 | `navbar-generation`、`popup-design-skill`、`mega-subsidy-design-skill`、`filter-tabs-design-skill` | 绑定固定 JD 组件库、fileKey、节点和 Tailwind 版本，通用性低 |
| 特定页面生成器 | `qiangdan-hall-generator`、`relay-theme-replace`、`zero-banner-update` | 强依赖具体业务稿和 Relay 写能力 |
| 商详数据维护 | `instance-manage`、`instance-suggest`、`component-properties-admission` | 绑定商详特定 JSON schema 和目录结构 |
| 本地 Git 操作 | `git-workflow`、`coding-repo-sync` | AgentMesh 是服务端平台，仓库写操作需要独立沙箱和审批，不应直接执行本地 Git |
| 插件 Key 代理 | `plugin-api-key-ai` | 现有方案涉及客户端持久化 Key 和 localhost 代理，建议重新设计后再接入 |
| 发布型 Skill | `design-md-to-portal`、`design-md-to-spec-page`、`zero-md-to-page` | 应在 artifact/publishing 子系统建成后再接 |

## 5. AgentMesh 接入方式建议

当前 `agentmesh/chat_skills.py` 使用固定的：

```text
ChatSkillSpec → Intent → handler
```

不建议为三十多个 Skill 增加三十多个 `Intent`。更适合增加统一的目录执行层：

```text
Wiki SKILL.md
  → SkillDefinition
      command
      title
      prompt_path
      input_schema
      output_schema
      required_tools
      risk_level
      artifact_type
  → CatalogSkillExecutor
  → PersonalAgent / Tool Grants / Risk Approval
  → Source-bound output
  → 私有记忆或候选团队记忆
```

建议新增的数据模型：

```python
class SkillDefinition(BaseModel):
    id: str
    command: str
    title: str
    description: str
    prompt_path: str
    input_schema: dict
    output_schema: dict
    required_tools: list[str]
    risk_level: str
    artifact_type: str | None
    enabled: bool = True
```

建议执行流程：

1. 解析显式 `$command`；
2. 查询 `SkillDefinition`；
3. 检查用户、项目和 Tool Grant；
4. 校验输入结构；
5. 检索项目/个人/团队记忆；
6. 对外部资料执行提示注入检查；
7. 对高风险工具调用发起人工审批；
8. 执行 Skill prompt、确定性脚本或外部工具；
9. 校验输出 schema 和来源引用；
10. 产出写入私有短期记忆；
11. 用户确认后才能进入项目或团队记忆。

## 6. 接入原则

所有新 Skill 应继续遵守 AgentMesh 现有原则：

- 普通对话默认私有；
- 必须显式 `$command` 才执行 Skill；
- 外部资料必须绑定 Source；
- Relay、JoySpace、Git、批量抓取和文件写入必须进入审批；
- Skill 使用的工具必须经过 Tool Grant；
- Skill 输出先写入短期记忆；
- 用户确认后才能进入项目或团队记忆；
- Skill 执行过程写入 AuditEvent，保留输入、工具、来源、模型和审批信息；
- 高价值 Skill 可以进入 AgentMesh 的 LearnedSkill 激活、分享和废弃生命周期。

## 7. 建议实施阶段

### 阶段一：Prompt/Memory 型 Skill

优先接入 P0 Skill，建立通用 `SkillDefinition` 和 `CatalogSkillExecutor`，验证 `$` 命令、输入输出 schema、来源绑定和记忆沉淀闭环。

### 阶段二：数据分析型 Skill

增加 Excel/CSV 解析、统计计算和受限 Python worker，接入反馈、满意度、漏斗、采纳和 A/B 分析。

### 阶段三：视觉与设计工具型 Skill

增加图片附件、Vision Provider、HTML artifact、浏览器检查以及 Relay/Zero/JoySpace 工具适配；所有写操作走人工审批。

### 阶段四：Skill 市场化

把接入后的 Skill 纳入 AgentMesh 的上架、授权、使用统计、质量评估、版本、激活、分享和废弃流程。
