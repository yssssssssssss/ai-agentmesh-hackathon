# AgentMesh 能力图片资源（Mermaid 版）

> 用途：配套 [AgentMesh 10 分钟黑客松项目介绍 PPT 版](./AgentMesh-10分钟黑客松项目介绍-PPT版.md) 中所有“能力图片建议”。
> 使用方式：复制任意 Mermaid 代码块到 Mermaid Live、VS Code、Typora、语雀或飞书文档，渲染后导出 SVG/PNG 放入 PPT。

## 01 工作生命周期数字员工接力图

用于模块一“真实痛点 / 使用场景提要”的解决方案页。

~~~mermaid
flowchart LR
  Start["用户在 Workspace<br/>提出一个工作问题"] --> R["Research Agent<br/>找资料<br/>相似项目 / 外部资料 / 文档来源"]
  R --> D["Data Agent<br/>查指标<br/>点击率 / 转化率 / 业务数据"]
  D --> K["Risk Agent<br/>审风险<br/>素材授权 / Prompt 注入 / 高危工具"]
  K --> M["Memory Agent<br/>沉淀经验<br/>个人 / 项目 / 团队记忆"]
  M --> Out["带来源的答案<br/>可审计 / 可复用 / 可追溯"]

  classDef entry fill:#eff6ff,stroke:#2563eb,color:#172554,stroke-width:1.5px;
  classDef agent fill:#f5f3ff,stroke:#7c3aed,color:#2e1065,stroke-width:1.5px;
  classDef output fill:#ecfdf5,stroke:#059669,color:#064e3b,stroke-width:1.5px;

  class Start entry;
  class R,D,K,M agent;
  class Out output;
~~~

## 02 个人能力罗盘

用于模块三“个人能力拓展”的解决方案页。

~~~mermaid
flowchart TB
  PA(("Personal Agent<br/>个人工作流调度"))

  PA --> Research["资料能力<br/>$research.request<br/>有来源的调研结果"]
  PA --> Data["数据能力<br/>$data.query<br/>指标查询与证据帖"]
  PA --> Risk["风险能力<br/>$risk.review<br/>进入 Inbox 人审"]
  PA --> Note["沉淀能力<br/>$note.save / $memory.propose<br/>写入个人或候选团队记忆"]

  Research --> Source["Sources<br/>来源引用"]
  Data --> Source
  Risk --> Audit["Audit / Inbox<br/>审计与确认"]
  Note --> Memory["Memory<br/>个人 / 项目 / 团队"]

  classDef center fill:#111827,stroke:#111827,color:#ffffff,stroke-width:2px;
  classDef cap fill:#eff6ff,stroke:#2563eb,color:#172554,stroke-width:1.5px;
  classDef guard fill:#fff7ed,stroke:#f97316,color:#7c2d12,stroke-width:1.5px;
  classDef mem fill:#ecfdf5,stroke:#059669,color:#064e3b,stroke-width:1.5px;

  class PA center;
  class Research,Data cap;
  class Risk,Audit guard;
  class Note,Memory,Source mem;
~~~

## 03 三级记忆金字塔与审核闸门

用于模块四“记忆模块”的解决方案页。

~~~mermaid
flowchart TB
  L1["个人记忆<br/>short_term<br/>今天做了什么、个人笔记、工作流结果"] --> L2["项目记忆<br/>mid_term / long_term<br/>项目阶段总结、归档、召回索引"]
  L2 --> Gate{"审核闸门<br/>lead / admin"}
  Gate -->|接受| L3["团队记忆<br/>TEAM_ACCEPTED<br/>可复用、可检索、带来源"]
  Gate -->|争议 / 过期 / 废弃| Hold["治理状态<br/>disputed / expired / deprecated"]

  L1 --> Search["检索融合<br/>FTS5 + vector + RRF"]
  L2 --> Search
  L3 --> Search
  Search --> Answer["带来源回答<br/>复用到下一次工作"]

  classDef personal fill:#eff6ff,stroke:#2563eb,color:#172554,stroke-width:1.5px;
  classDef project fill:#f0fdf4,stroke:#16a34a,color:#14532d,stroke-width:1.5px;
  classDef team fill:#fef2f2,stroke:#dc2626,color:#7f1d1d,stroke-width:1.5px;
  classDef gate fill:#fff7ed,stroke:#ea580c,color:#7c2d12,stroke-width:1.5px;
  classDef retrieval fill:#f8fafc,stroke:#475569,color:#0f172a,stroke-width:1.5px;

  class L1 personal;
  class L2 project;
  class L3 team;
  class Gate,Hold gate;
  class Search,Answer retrieval;
~~~

## 04 Agent 互助星图

用于模块五“Agent 互助模块”的解决方案页。

~~~mermaid
flowchart TB
  Me(("我<br/>Personal Agent"))
  Board["BBS / Market<br/>供需信号与匹配记录"]
  A["同事 A Agent<br/>有相关经验"]
  B["同事 B Agent<br/>正在求助"]
  C["同事 C Agent<br/>提供数据线索"]
  D["同事 D Agent<br/>需要风险建议"]

  Me -->|我的求助| Board
  Board -->|收到回答| Me
  A -->|发布可帮助信号| Board
  B -->|发布求助信号| Board
  C -->|提供证据| Board
  D -->|请求确认| Board
  Board -->|scout_all 自动匹配| A
  Board -->|publish_all_signals 自动发布| B
  Me --> Points["ContributionPoint<br/>采纳后记录贡献"]
  Board --> Memory["MemoryRelation<br/>互助结果回写记忆血缘"]

  classDef me fill:#111827,stroke:#111827,color:#ffffff,stroke-width:2px;
  classDef peer fill:#eff6ff,stroke:#2563eb,color:#172554,stroke-width:1.5px;
  classDef board fill:#f5f3ff,stroke:#7c3aed,color:#2e1065,stroke-width:1.5px;
  classDef asset fill:#ecfdf5,stroke:#059669,color:#064e3b,stroke-width:1.5px;

  class Me me;
  class A,B,C,D peer;
  class Board board;
  class Points,Memory asset;
~~~

## 05 团队价值飞轮

用于模块六“项目价值”的解决方案页。

~~~mermaid
flowchart LR
  Work["做事<br/>chat + skill<br/>资料、数据、风险"] --> Personal["个人记忆<br/>上下文资产"]
  Personal --> Project["项目记忆<br/>阶段经验"]
  Project --> Team["团队记忆<br/>审核后的知识资产"]
  Team --> Market["Agent 互助市场<br/>自动发现谁能帮谁"]
  Market --> Points["贡献记录<br/>ContributionPoint"]
  Points --> Reuse["复用<br/>下一次工作更快进入状态"]
  Reuse --> Work

  Team --> Search["检索和引用<br/>带来源回答"]
  Search --> Work

  classDef work fill:#eff6ff,stroke:#2563eb,color:#172554,stroke-width:1.5px;
  classDef mem fill:#ecfdf5,stroke:#059669,color:#064e3b,stroke-width:1.5px;
  classDef market fill:#f5f3ff,stroke:#7c3aed,color:#2e1065,stroke-width:1.5px;
  classDef value fill:#fff7ed,stroke:#ea580c,color:#7c2d12,stroke-width:1.5px;

  class Work,Search work;
  class Personal,Project,Team mem;
  class Market market;
  class Points,Reuse value;
~~~
