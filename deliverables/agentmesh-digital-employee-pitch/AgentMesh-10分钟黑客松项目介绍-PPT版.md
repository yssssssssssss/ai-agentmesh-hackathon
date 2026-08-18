# AgentMesh 10 分钟黑客松项目介绍（PPT 演示稿）

> 用途：黑客松 10 分钟路演。结构按 PPT 模式组织，每个模块包含演示内容、口播内容、项目演示和技术架构图。
> 依据：项目 README、CONTEXT、三级记忆设计、协作市场落地报告及当前代码能力整理。

配套能力图片资源：

- [PPTX 路演文件](./AgentMesh-10分钟黑客松项目介绍.pptx)：可直接打开演示，12 页，16:9 深色路演风格。
- [Mermaid 版能力图](./AgentMesh-能力图片资源-Mermaid.md)：适合粘贴到 Mermaid Live、语雀、飞书或 VS Code 后导出 SVG/PNG。
- [HTML 版视觉稿](./AgentMesh-能力图片资源-HTML.html)：打开后可直接截图，适合放进 PPT。

AgentMesh 的一句话定位：把个人 AI 助手升级成团队数字员工网络，让 AI 能找资料、查数据、审风险、沉淀经验，还能让不同人的 Agent 在受控边界内互相帮忙。

## 核心价值点

1. 一个聊天入口，调度一组数字员工。用户只面对 Workspace 聊天框，通过 11 个显式 $ skill 发起调研、数据查询、风险审查、记忆沉淀和系统查询。
2. 记忆不是简单存档，而是个人、项目、团队三级资产。个人保留上下文，项目沉淀阶段经验，团队只接收经过审核的高价值知识。
3. Agent 协作不是黑盒。Personal Agent、Research Agent、Data Agent、Risk Agent 通过 Blackboard 留下请求、证据、风险、决策、候选记忆，过程可回放。
4. 互助市场让知识主动流动。用户 opt-in 后，个人 Agent 可以发布求助信号，其他 Agent 扫描匹配并代答，采纳后记录 ContributionPoint。
5. 企业可控。外部内容先过风险扫描，高风险工具和团队记忆写入进入 Inbox 人工确认，来源、审计、权限都落到代码里。
6. 工程可追问。当前测试收集数是 551，前端是 React/Vite，后端是 FastAPI，存储是 SQLite，O2、Web、Data、LLM 都通过适配器边界接入。

## 10 分钟 PPT 总结构

| 时间 | 模块 | 核心目标 | 建议页面 |
|---|---|---|---|
| 0:00 到 1:20 | 真实痛点 / 使用场景提要 | 把评委拉进真实工作场景 | 封面、痛点页 |
| 1:20 到 2:30 | 整体架构 | 说明这不是单 Agent，而是可治理的协作系统 | 架构图页 |
| 2:30 到 4:00 | 个人能力拓展 | 展示 $ skill 如何把 AI 能力变成工作流 | Workspace、DigitalSelf |
| 4:00 到 6:30 | 记忆模块 | 展示三级记忆、治理、检索、Skill 提炼 | Knowledge、Insights |
| 6:30 到 8:20 | Agent 互助模块 | 展示自动发布、匹配、代答、贡献记录 | Collaboration、Market |
| 8:20 到 10:00 | 项目价值 | 收束差异化、工程可信度和下一步 | 总结页、测试页 |

## 模块一：真实痛点 / 使用场景提要，0:00 到 1:20

### 场景问题

演示内容：一页放 3 个真实场景，旁边用一条暗线串起来。

- 去年 618 家电会场做过什么方案，效果如何，现在只能翻聊天记录和文档。
- 指标在 BI，竞品资料在外部搜索，风险规则在法务文档，一个问题要开好几个系统。
- AI 能帮忙产出，但素材授权、批量抓取、内网访问这些高风险动作，谁来确认，谁来留痕。

口播内容：

“我们做 AgentMesh 的起点，是团队每天都在损失三样东西：历史经验、跨系统上下文、可信的审批链。工作信息一直在流动，但大部分没有沉淀；AI 能力越来越强，但过程缺少治理。”

### 解决方案

演示内容：放一张“工作生命周期数字员工接力图”。

能力图片建议：用 4 个横向卡片表达，Research Agent 找资料，Data Agent 查指标，Risk Agent 审风险，Memory Agent 沉淀经验。每张卡只放一个图标和一句能力，不放长解释。

口播内容：

“AgentMesh 的解法不是让一个 Agent 什么都干，而是让一次工作生命周期里，不同数字员工在不同阶段接力。用户还是从一个聊天入口开始，后台把资料、数据、风险、记忆拆给合适的 Agent 处理。”

### 项目演示

演示内容：本页不做重操作，只给出后续 demo 路线：Workspace 聊天，Knowledge 我的知识，Insights 工作洞察，Collaboration 协作，Market 协作市场。

口播内容：

“接下来我不讲静态概念，会按这条真实工作链路演示：先拓展个人能力，再沉淀记忆，最后让 Agent 之间自动互助。”

### 技术架构

~~~mermaid
flowchart LR
  Pain1["经验散落"] --> Entry["Workspace 聊天入口"]
  Pain2["多源割裂"] --> Entry
  Pain3["审批黑洞"] --> Entry
  Entry --> Skills["显式 $ skill"]
  Skills --> Agents["多 Agent 接力"]
  Agents --> Memory["个人 / 项目 / 团队记忆"]
  Agents --> Audit["来源 / 审计 / Inbox"]
~~~

## 模块二：整体架构，1:20 到 2:30

### 场景问题

演示内容：左右对比图。左边是“单一 ChatBot”，所有能力塞在一个框里；右边是“AgentMesh”，聊天入口下面是多个专业 Agent 和 Blackboard。

口播内容：

“单一 ChatBot 的问题很直接：能力混在一起，权限也混在一起，出了问题很难追溯。企业需要的是可授权、可审计、可替换的 Agent 协作架构。”

### 解决方案

演示内容：展示主架构图，强调四层：React 前端，FastAPI 路由，Agent 协作引擎，SQLite 与外部 Provider。

口播内容：

“AgentMesh 是 chat-first 的团队 Agent 协作平台。用户输入 $ 唤起技能菜单，后端把请求路由给 Personal Agent，再由它调度 Research、Data、Risk 等专业 Agent。Agent 之间通过 Blackboard 共享证据和状态，不互相硬编码。”

### 项目演示

演示内容：

1. 在 Workspace 输入 $system.info，展示当前模型配置和技能菜单。
2. 打开接口文档或路由页面，展示 chat、memory、market、blackboard、inbox、users 等 API 分组。
3. 如果时间紧，只演第 1 步。

口播内容：

“这里的 $ skill 不是前端假按钮，它来自后端统一注册表。现在代码里有 11 个 ChatSkillSpec，前端只是把后端能力露出来。”

### 技术架构

~~~mermaid
flowchart TB
  UI["React / Vite 前端<br/>Workspace、Knowledge、Insights、Collaboration、Market"] --> API["FastAPI 路由层<br/>chat、memory、market、blackboard、inbox"]
  API --> PA["Personal Agent<br/>工作流调度、任务创建、答案合成"]
  PA --> RA["Research Agent"]
  PA --> DA["Data Agent"]
  PA --> RK["Risk Agent"]
  PA --> BB["Blackboard<br/>请求、证据、风险、决策、候选记忆"]
  RA --> EXT["Web / O2 / 文档 / 数据连接器"]
  DA --> EXT
  RK --> INBOX["Inbox 人工确认"]
  BB --> STORE["SQLite Store<br/>消息、任务、记忆、审计、来源"]
  API --> STORE
~~~

## 模块三：个人能力拓展，2:30 到 4:00

### 场景问题

演示内容：一句话卡片，“AI 已经能帮个人做更多事，但答案要有来源，风险要有人审”。

口播内容：

“个人能力拓展不是多接几个工具这么简单。真正进企业工作流后，评委会问三个问题：答案从哪来，工具有没有授权，高风险动作谁确认。”

### 解决方案

演示内容：展示 $ skill 能力菜单，重点标出 $research.request、$data.query、$risk.review、$note.save。

能力图片建议：做成“能力罗盘”，中心是 Personal Agent，四个方向是资料、数据、风险、笔记，每个方向都连到来源和审计。

口播内容：

“AgentMesh 把能力做成显式命令。普通聊天默认私有，不创建任务；只有用户明确输入 $ skill，系统才进入可审计的工作流。这一点让能力拓展和治理能放在同一个设计里。”

### 项目演示

演示内容：

1. 输入 $research.request 查找去年 618 家电会场的复盘经验，展示返回答案和来源。
2. 输入 $data.query 查询 618 会场入口点击率，展示 Data Agent 证据。
3. 输入 $risk.review 检查这批外部素材授权风险，展示风险项进入 Inbox 或我的知识待处理区。
4. 若现场 Provider 未配置，直接说明 research 和 data 会走 mock 或 local_metrics fallback，架构边界仍是真实代码。

口播内容：

“这一步展示的是个人能力如何被系统化。调研、数据、风险分别由不同 Agent 处理，最后回到一个回答里。更重要的是，风险项不会被 AI 自己吞掉，会进入人工确认流程。”

### 技术架构

~~~mermaid
sequenceDiagram
  autonumber
  participant U as 用户
  participant C as Chat Route
  participant S as Skill Registry
  participant P as Personal Agent
  participant A as 专业 Agent
  participant I as Inbox / Audit
  participant M as Memory / Sources

  U->>C: 输入 $research / $data / $risk
  C->>S: 解析 ChatSkillSpec
  S-->>C: intent + scope + 参数
  C->>P: 创建工作流任务
  P->>A: 调用 Research / Data / Risk
  A-->>P: 返回证据和来源
  alt 高风险或可疑内容
    P->>I: 创建待确认项
  else 正常
    P->>M: 写来源和短期记忆
  end
  P-->>U: 返回答案 + workflow trace
~~~

## 模块四：记忆模块，4:00 到 6:30

### 场景问题

演示内容：一页放“内容越来越多，复用越来越难”。背景可以用堆叠文档、聊天气泡、会议纪要的视觉。

口播内容：

“AI 让我们单位时间内产出更多内容，但内容变多以后，团队反而更难复用。真正的问题不是能不能存，而是能不能分层、提炼、审核、召回。”

### 解决方案

演示内容：放一张二维矩阵。横轴是 Scope：private、project、team_candidate、team_accepted；纵轴是 MemoryLayer：short_term、mid_term、long_term。

能力图片建议：用三级金字塔。底层是个人上下文，中层是项目经验，顶层是团队资产。旁边放一个“审核闸门”图标，表示普通成员的候选记忆要审核后才能进入团队层。

口播内容：

“AgentMesh 的记忆分两条轴：Layer 管沉淀深度，Scope 管谁能看。个人短期记忆记录今天做了什么，项目记忆沉淀阶段经验，团队记忆必须经过候选和接受流程。这里不是把所有东西塞进一个知识库，而是把知识变成有治理状态的资产。”

### 项目演示

演示内容：

1. 打开 Knowledge 我的知识，进入待处理，接受一条团队候选记忆，展示它进入共享知识。
2. 打开 Insights 工作洞察，展示 short_term、mid_term、long_term 统计。
3. 展示一条文档上传或项目归档如何生成长期记忆。
4. 口播补充 Skill 提炼：重复成功的工作流达到阈值后，skill_extractor.py 会提出 LearnedSkill。前端卡片如果仍是参考数据，要如实说明。

口播内容：

“这页最适合讲技术深度。记忆系统做了四件事：分层，治理，检索，提炼。分层解决内容堆积，治理解决质量和权限，FTS5 加向量检索解决找得到，LearnedSkill 解决同类工作下次不用重新推理。”

### 技术架构

~~~mermaid
flowchart TB
  Chat["$ skill 工作流 / 文档上传 / 手动笔记"] --> Short["个人短期记忆<br/>UserMemoryItem short_term"]
  Short --> Daily["每日摘要<br/>daily_summary"]
  Daily --> Project["项目中期记忆<br/>mid_term project_summary"]
  Project --> Archive["项目长期归档<br/>long_term project_archive"]
  Archive --> Candidate["团队候选记忆<br/>TEAM_CANDIDATE"]
  Candidate --> Gate{"lead / admin 审核"}
  Gate -->|接受| Team["团队记忆<br/>TEAM_ACCEPTED"]
  Gate -->|拒绝或争议| Review["disputed / deprecated / expired"]
  Short --> Search["检索层<br/>FTS5 + vector + RRF"]
  Project --> Search
  Team --> Search
  Search --> Answer["带来源回答"]
~~~

~~~mermaid
flowchart LR
  A["多次成功工作流"] --> B["归一化模式<br/>extract_workflow_pattern"]
  B --> C{"同类模式次数 >= 3"}
  C -->|是| D["提出 LearnedSkill 草稿"]
  C -->|否| E["继续观察"]
  D --> F["用户激活 / 分享 / 废弃"]
  F --> G["下次同类请求<br/>优先复用已验证步骤"]
~~~

## 模块五：Agent 互助模块，6:30 到 8:20

### 场景问题

演示内容：一句话卡片，“知识如果只能被动搜索，还是不够”。

口播内容：

“团队知识沉淀以后，还有一个更有价值的动作：让它主动流动。一个人正在做的问题，可能另一个人的 Agent 已经有经验，系统应该自动发现谁能帮谁。”

### 解决方案

演示内容：协作市场流程图。Agent-1 发布求助信号，Agent-2 扫描匹配并代答，用户采纳后记录贡献点。

能力图片建议：用“星图”或“节点网络”。中心节点是我，周围是同事 Agent，连线分三种颜色：我的求助、我收到的回答、我给别人的回应。

口播内容：

“互助市场默认不是全员广播。用户要 opt-in，个人 Agent 才参与。它发布的是需求信号和抽象答案，不是把原始记忆直接暴露给别人。被采纳的帮助会记录 ContributionPoint，为后续贡献排行榜和激励规则打基础。”

### 项目演示

演示内容：

1. 打开 Collaboration 页面，展示市场参与者、供需信号、完成匹配、授权记录。
2. 点击加入市场或退出市场，展示 opt-in。
3. 打开 Market 页面，展示当前用户的个人视角：我发出的求助、我收到的回答、我给出的回应。
4. 展示一条提前触发好的真实匹配。演示前用 publish_all_signals(store) 和 scout_all(store) 触发，不要台上等待 worker 周期。

口播内容：

“这里展示的是从静态知识库到主动协作网络的变化。Agent-1 负责发布需求信号，Agent-2 负责扫描和匹配，回答被采纳后会写回记忆血缘和贡献记录。”

### 技术架构

~~~mermaid
sequenceDiagram
  autonumber
  participant U1 as 用户 A 的 Agent
  participant B as Blackboard / Market
  participant U2 as 用户 B 的 Agent
  participant G as Consent / Risk Gate
  participant M as Memory
  participant P as ContributionPoint

  U1->>B: publish_all_signals 发布 marketplace_signal
  U2->>B: scout_all 扫描信号
  U2->>G: 检查参与状态、授权、敏感度
  alt 可自动回答
    U2->>M: 检索自己的可用记忆
    U2->>B: 发布 marketplace_match 和代答
  else 需要确认
    U2->>B: 创建待确认记录
  end
  U1->>B: 采纳代答
  B->>M: 写入 delegated_answer 记忆和 MemoryRelation
  B->>P: 记录贡献点
~~~

## 模块六：项目价值，8:20 到 10:00

### 场景问题

演示内容：对比表，通用 ChatBot、企业知识库、AgentMesh 三列，能力、记忆、协作、治理四行。

口播内容：

“只会聊天的工具，解决不了团队协作问题；只会检索的知识库，也解决不了主动互助和风险治理问题。AgentMesh 把能力、记忆、协作、治理放到一条工作链路里。”

### 解决方案

演示内容：价值飞轮图。个人工作产生记忆，项目沉淀经验，团队审核成资产，Agent 互助产生新贡献，新贡献再反哺记忆。

能力图片建议：做成闭环飞轮，中间放“团队 AI 工作大脑”，四个环节是做事、沉淀、互助、复用。

口播内容：

“这个项目的价值不在多一个入口，而在让工作过程变成可积累的资产。个人获得能力放大，项目获得历史复用，团队获得知识沉淀，公司获得可审计的 AI 工作流。”

### 项目演示

演示内容：

1. 回放前面 3 个关键画面：带来源回答、团队候选记忆接受、协作市场匹配。
2. 展示测试收集结果：551 tests collected。
3. 如果评委追问真实 Provider，说明 Web、O2、Data、LLM 都有边界和 smoke 脚本，但真实返回取决于演示环境凭证。

口播内容：

“我们没有把未接线的部分说成已经完整上线。真实 Provider 依赖环境凭证，但接口边界、权限、审计、fallback 和测试都已经就位。黑客松演示最怕只靠动画，我们这套每一步都能追到 API、模型和测试。”

### 技术架构

~~~mermaid
flowchart LR
  Work["个人工作流<br/>chat + skill"] --> PM["个人记忆<br/>上下文资产"]
  PM --> Project["项目记忆<br/>阶段经验"]
  Project --> Team["团队记忆<br/>审核后的知识资产"]
  Team --> Market["Agent 互助市场<br/>自动发现谁能帮谁"]
  Market --> Points["贡献记录<br/>ContributionPoint"]
  Points --> Work
  Team --> Search["检索和引用"]
  Search --> Work
~~~

### 收尾口播

“AgentMesh 不是让团队多用一个 AI 工具，而是让团队拥有一套安全、可审计、会协作、会记忆的数字员工体系。每个阶段都有合适的 Agent 接力，每一步都有来源和审计，经验不会因为项目结束或人员流动就散掉。谢谢。”

## 演示红线

- 不要说已经完成 ERP、C3、PostgreSQL、多租户和 designOS 融合。当前代码现实是本地 session、单 Workspace、SQLite、可信内网 MVP。
- O2、Web、真实数据 Provider 是否可用取决于演示机凭证。没有凭证时说“接口和适配器已就绪，当前演示环境走 mock 或本地样例”。
- ContributionPoint 已记录，但没有排行榜、兑换规则和公开 points UI，不要说奖励体系已完整上线。
- Insights 里的部分“知识提炼”展示如果仍来自参考数据，要标注为演示数据，Skill 提炼逻辑本身可用代码和测试证明。

## 建议放进 PPT 的来源锚点

- 项目现状：[README.md](../../README.md)
- 代码现实边界：[CONTEXT.md](../../CONTEXT.md)
- Skill 注册表：[agentmesh/chat_skills.py](../../agentmesh/chat_skills.py)
- 三级记忆设计：[docs/memory-three-tier-design.md](../../docs/memory-three-tier-design.md)
- 记忆架构图：[docs/memory-architecture.md](../../docs/memory-architecture.md)
- 协作市场落地报告：[docs/collaboration-market-delivery-report.md](../../docs/collaboration-market-delivery-report.md)
