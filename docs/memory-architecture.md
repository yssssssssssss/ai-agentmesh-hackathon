# AgentMesh 记忆架构图解

> 图解范围：双记忆模型、可见性(Scope)与时间分层(Layer)双轴、逐级汇总管线、团队治理晋升、写入时序、状态机。
> 代码锚点：`agentmesh/models.py`、`agentmesh/routes/memory.py`、`agentmesh/agents.py`、`agentmesh/store.py`。

---

## 1. 总体架构图（组件视图）

两套记忆模型 + 存储 + 汇总管线 + LLM + Worker + 检索的整体关系。

```mermaid
flowchart TB
    subgraph Entry["入口层"]
        Chat["Chat / $skill workflow"]
        API["Memory API<br/>/api/memory/*"]
        Worker["每日汇总 Worker<br/>(默认关闭 env-gated)"]
    end

    subgraph Core["记忆核心逻辑 agents.py + routes/memory.py"]
        Writer["短期记忆写入<br/>_record_short_term_memory"]
        Rollup["逐级汇总<br/>daily / project / archive"]
        Gov["治理晋升<br/>update_memory_item"]
        Perm["权限门<br/>ensure_can_update_memory"]
    end

    subgraph Models["两套记忆模型 models.py"]
        UM["UserMemoryItem<br/>个人 · 分层 Layer"]
        TM["MemoryItem<br/>团队 · 可见性 Scope"]
    end

    subgraph Infra["基础设施"]
        Store["Store (SQLite KV)<br/>user_memory_items / memory_items"]
        LLM["LLMClient<br/>摘要生成 (可回退)"]
        Search["个人/团队检索<br/>store.search"]
    end

    Chat --> Writer
    API --> Rollup
    API --> Gov
    Worker --> Rollup

    Writer --> UM
    Rollup --> UM
    Rollup -.LLM优先.-> LLM
    Gov --> Perm
    Perm --> TM

    UM --> Store
    TM --> Store
    Store --> Search
    LLM -.失败回退确定性摘要.-> Rollup
```

---

## 2. 双轴示意图（设计核心）

记忆被两条**正交**的轴管理：可见性(Scope) 管"谁能看"，时间分层(Layer) 管"存多久 / 多浓缩"。个人记忆走 Layer 轴沉淀，需要共享时才跨到 Scope 轴晋升为团队记忆。

```mermaid
flowchart LR
    subgraph AxisY["时间分层轴 (个人记忆 Layer)"]
        direction TB
        L1["short_term 短期<br/>每次 workflow 结果"]
        L2["mid_term 中期<br/>项目阶段沉淀"]
        L3["long_term 长期<br/>项目归档 + 召回索引"]
        L1 --> L2 --> L3
    end

    subgraph AxisX["可见性轴 (团队记忆 Scope)"]
        direction LR
        S1["PRIVATE<br/>私有"]
        S2["PROJECT<br/>项目"]
        S3["TEAM_CANDIDATE<br/>候选(待审)"]
        S4["TEAM_ACCEPTED<br/>已接受"]
        S1 --> S2 --> S3 --> S4
    end

    L3 -.需要共享时晋升.-> S3

    style AxisY fill:#eef6ff,stroke:#4a90d9
    style AxisX fill:#fff4e6,stroke:#e0912f
```

---

## 3. 分层汇总管线流程图（越老越浓缩）

个人记忆的核心生命周期：写入 → 每日汇总 → 项目中期 → 长期归档。每级都排除上一轮自身产物，防止自我循环汇总。

```mermaid
flowchart TB
    Start(["$skill workflow 完成"]) --> Guard{"intent 是<br/>ASK_SYSTEM_INFO?<br/>或待审批?"}
    Guard -->|是| Skip["跳过, 不写记忆"]
    Guard -->|否| W["写入 short_term<br/>source_kind=chat_workflow:intent<br/>带 task/thread/来源"]

    W --> D["每日汇总 (幂等)<br/>POST /user/daily-summary<br/>排除 source_kind=daily_summary"]
    D --> Dcheck{"当天已存在<br/>daily_summary?"}
    Dcheck -->|是 409| Dstop["拒绝重复生成"]
    Dcheck -->|否| Dmake["生成 '每日短期记忆摘要'"]

    Dmake --> P["项目中期汇总<br/>POST /user/project-summary<br/>short_term 排除 rollup"]
    P --> Pmake["生成 mid_term<br/>'项目中期记忆摘要'"]

    Pmake --> A["长期归档<br/>POST /user/archive-project<br/>mid_term 排除 archive"]
    A --> Amake["生成 long_term<br/>'项目长期归档'<br/>强制含 召回索引 关键词"]

    Amake --> End(["可被跨项目检索召回"])

    style W fill:#eef6ff
    style Dmake fill:#eef6ff
    style Pmake fill:#e6f7ec
    style Amake fill:#fdeaea
```

---

## 4. 摘要生成：LLM 优先 + 确定性回退

中期/归档摘要的生成策略，保证无模型环境下不塌。

```mermaid
flowchart TB
    In(["需要生成摘要"]) --> Has{"LLMClient<br/>可用?"}
    Has -->|否 client=None| FB["确定性回退<br/>_summarize_memory_items<br/>逐条列表汇总"]
    Has -->|是| Call["调用 LLM<br/>system: 不编造/固定结构"]
    Call --> Ok{"成功且<br/>非空?"}
    Ok -->|异常/空| FB
    Ok -->|是| Use["使用 LLM 摘要"]
    Use --> Idx["归档: _ensure_archive_index<br/>无'召回索引'则补关键词"]
    FB --> Idx
    Idx --> Out(["截断 2000 字后存储"])

    style FB fill:#fff4e6
    style Use fill:#e6f7ec
```

---

## 5. 团队记忆治理晋升流程图（带权限门）

个人/黑板证据晋升为团队记忆，必须过角色权限门；候选仅 lead/admin 可见。

```mermaid
flowchart TB
    Src["来源: 黑板证据/决策/摘要<br/>或 $memory.propose"] --> Cand["MemoryItem<br/>scope=TEAM_CANDIDATE<br/>status=PROPOSED"]

    Cand --> Vis{"当前用户角色?"}
    Vis -->|普通成员| Hide["不可见 (过滤)"]
    Vis -->|TEAM_LEAD / ADMIN| Show["可见于团队记忆待审列表"]

    Show --> Act["PATCH /api/memory/{id}<br/>status=ACCEPTED"]
    Act --> Gate["ensure_can_update_memory<br/>校验权限策略表"]
    Gate -->|拒绝| Deny["403 无权接受"]
    Gate -->|通过| Promote["scope=TEAM_ACCEPTED<br/>status=ACCEPTED"]
    Promote --> Team(["团队可见共享知识"])

    style Cand fill:#fff4e6
    style Promote fill:#e6f7ec
    style Hide fill:#f2f2f2
    style Deny fill:#fdeaea
```

---

## 6. 写入时序图（对话 → 短期记忆）

一次 `$skill` 对话如何落成一条短期记忆。

```mermaid
sequenceDiagram
    autonumber
    participant U as 用户
    participant C as Chat Route
    participant A as PersonalAgent
    participant S as Store(SQLite)

    U->>C: 发送 $skill 消息
    C->>A: 执行 workflow
    A->>A: 产出 assistant_content + evidence/risk sources
    A->>A: _record_short_term_memory()
    alt intent=ASK_SYSTEM_INFO 或待审批
        A-->>C: 返回 None (不写记忆)
    else 有效 workflow
        A->>S: add_user_memory_item(short_term)
        Note over S: 带 source_task_id / thread_id / sources
        S-->>A: UserMemoryItem
    end
    A-->>C: 回答 + workflow_trace
    C-->>U: 展示答案与来源
```

---

## 7. 记忆状态机（MemoryStatus）

团队记忆并非只增不减，可被争议、废弃、过期。

```mermaid
stateDiagram-v2
    [*] --> draft
    draft --> proposed: 提交候选
    proposed --> accepted: 独立 Memory Review 接受
    proposed --> disputed: 独立 Memory Review 拒绝
    proposed --> expired: 候选失效并取消待处理 Review
    accepted --> disputed: 标记争议
    accepted --> deprecated: 主动废弃或后继修订激活
    accepted --> expired: 标记失效
    accepted --> archived: 归档
    disputed --> deprecated: 废弃
    disputed --> expired: 标记失效
    disputed --> archived: 归档
    deprecated --> archived: 归档历史
    expired --> archived: 归档历史
    archived --> accepted: 恢复归档前状态
    archived --> disputed: 恢复归档前状态
    archived --> deprecated: 恢复归档前状态
    archived --> expired: 恢复归档前状态
```

Accepted 团队知识不可原地改写。修订会创建新的 proposed 记录并冻结来源 Memory 的 ID、版本和内容哈希；只有新候选的独立 Memory Review 接受后，才在同一事务中激活新版本并将前一版置为 deprecated。若同一前驱已经存在 accepted 后继，则 archived-from-accepted 的旧后继不得恢复，避免同时出现两个 active successor。

## 8. 记忆上下文与使用回执

搜索命中不等于已使用。`MemoryContextService` 在权限、生命周期、AgentMemoryBinding、Scope、MemoryLayer、FTS/Vector 排序和预算完成后，才形成可进入模型的上下文。实际进入某个 Agent Run 的每个 Memory 版本都会写入一个不可变 `MemoryUseReceiptV1`：

```text
Run / Task
  → Memory ID + record version + versioned content hash + retrieval layer
  → retrieval reason + query hash
  → stable citation label
  → Agent ID + original Source IDs
```

自动上下文默认 `off`，可先使用 `observe` 仅测量，再切换到 `inject`。显式 Runtime `memory_search` 仅在输出编码、大小限制、安全检查、审计和 Tool call settlement 全部成功后写回执；被隔离或改写的输出不记为使用。Memory 标题、摘要和实际暴露的 Source metadata 在候选上限前应用 credential / prompt-injection quarantine。Memory 后续 disputed、deprecated、expired、archived 或被新版本取代，都不能改写历史 Run 当时使用的版本事实。

每个 Run 的 Citation 先通过 `BEGIN IMMEDIATE` 事务保留，reservation 不是使用事实，也不出现在 Run/Memory 使用历史中。这样并发的不同查询不会把同一个 `[T1]` 分配给两个 Memory 版本。

Scope 与 MemoryLayer 是独立维度：Scope 决定谁可见，Layer 决定检索深度，并在排序与上下文预算前过滤。新 governed shared Memory 保存显式 Layer；缺少显式 Layer 的 legacy Project Memory 按 mid-term、Team Knowledge 按 long-term 投影，不回写或伪造旧记录。`max_total_chars` 约束完整渲染 payload，而不是只计算 title/summary。

---

## 图例速查

| 颜色 | 含义 |
|---|---|
| 蓝 | 短期 / 个人记忆写入 |
| 绿 | 成功 / 已接受 / 高层沉淀 |
| 橙 | 候选 / 待审 / 回退路径 |
| 红 | 拒绝 / 归档 / 高危 |
| 灰 | 被过滤 / 跳过 |
