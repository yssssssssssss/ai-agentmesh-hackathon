# Research Orchestration v2 工程候选基线

> 证据日期：2026-08-20
>
> 状态：Engineering Candidate；不是正式 Release Gate 授权
>
> 默认运行模式：`off`

本文档只保存可复核的脱敏工程证据。它不包含 prompt、Provider 原文、API key、cookie、私有正文或本地数据库，也不把尚未发生的真人评测写成通过。

## 1. 判定

Web Preview 和 Web Execute 已形成可运行的纵向闭环；本地门禁、真实 Tavily + GPT-5.2 闭环、三种启用 GPT 兼容 smoke、进程重启复核和 `off` 回滚演练均通过。当前结论只能是“工程候选可进入真人评测”，不能是“Release Gate 已通过”或“允许正式 `execute` 灰度”。

阻断项仍为：

- 固定 20 条样本的真实 v1/v2 observation 与非确定性重复运行；
- 两名评审独立 A/B 盲评及必要的第三人裁决；
- 10 人内部试点，至少 8 人认可 Evidence 和 gap 的实际价值。

## 2. 代码与回退锚点

| 对象 | 锚点 |
| --- | --- |
| scoped WIP recovery | `f2e09ca` |
| Web Preview | `7ce55fb` |
| Web Execute 与 review 缺口关闭 | `391caeb` |
| Release Gate patch | 本文档所在提交 |
| 安全回退 | `AGENTMESH_SKILL_ORCHESTRATION=off`；不删除数据、不 downgrade |

用户拥有的 `2C-DesignWiki/`、`deliverables/`、本地 SQLite 和 Harness 状态不属于候选提交。

## 3. 自动化门禁

| 层级 | 结果 | 关键证据 |
| --- | --- | --- |
| 相关后端 | PASS | 52 项 thread/history、delivery、smoke、eval 回归通过 |
| 全量后端 | PASS | 1,001 项 pytest 通过；5 条既有 SWIG deprecation warning |
| Python 静态检查 | PASS | `ruff check .` |
| 前端单测 | PASS | 18 files、106 tests |
| API 合约 | PASS | OpenAPI 与 TypeScript types 重新生成；thread detail 含只读 `latest_research_run_id` |
| 生产构建 | PASS | 1,764 modules；最大入口 302,874 bytes，小于 500,000-byte budget |
| 浏览器 | PASS | 53 项 Chromium E2E；其中 4 项 research-v2 场景 |
| Skill retrieval | PASS | 40 cases；Top-3 recall 100%；p95 26.618 ms；不可用/禁用/越权召回均为 0 |
| Skill catalog | PASS | 10 个唯一 v2 profile + 11 个 Legacy profile；0 error、0 warning |
| 固定研究资产 | PASS | 20 cases，四类各 5；rubric schema 有效 |

`eval/research_orchestration/run_eval.py` 在没有 observations 时明确输出：

```json
{"assets_valid":true,"human_review_complete":false,"machine_gate_evaluated":false,"pilot_complete":false,"release_gate_passed":false}
```

这说明评测资产可用，但发布门禁尚未完成。

最终串行门禁首次运行暴露了两个既有测试链路缺口：Legacy Skill mock Run 缺少必需的 `orchestration_version`，因此 SSE 订阅按契约拒绝建连；协作 mutation 成功后会刷新全部 Task detail，使交接成功提示被无关请求延迟。前者补齐 v1 fixture，后者收敛为只刷新 cards、当前 Task、audit 和 bootstrap。两个场景分别连续运行三次通过，随后完整 53 项串行通过；research-v2 的 4 项场景始终通过。

## 4. 真实 Provider 全链路

完整 Run：`run_685bf5ab05ce`

| 字段 | 脱敏结果 |
| --- | --- |
| Requirement | `requirement_34841f8bf294` |
| Plan | `research_plan_1cbff9b0e062` |
| Attempt | `attempt_57863f57d1d6` |
| Invocation | `invocation_cd2c32ea3b1c0b2b89f137057ed632e6` |
| Model call | `model_call_2ee6e9983f4c8338223c8dd78b930a87` |
| requested / actual model | `default` / `GPT-5.2-joybuilder` |
| Tool implementation | `agentmesh.tool_runtime.gateway.ToolGateway.web_research` |
| Provider | `tavily`，`real` |
| Invocation | `acknowledged`，`send_count=1` |
| Evidence | 1 个 verified Evidence，pointer 为 `/quote` |
| Claims | 11 个；其中 factual 5 个；机器可解析 Evidence coverage 100% |
| Review | `pass`，11/11 checks |
| Report | 与已审查 Deliverable 和 Review hash 绑定；没有新增事实 |

持久化 Artifact：

| Kind | ID | SHA-256 |
| --- | --- | --- |
| Evidence Manifest | `artifact_manifest_73de2167755075a171ff14f710d1280f` | `f5f3b3451cd8db314857b2453919cb60ca86f04a4c5be0bb9318f0ab4675f6e0` |
| Claim Ledger | `artifact_claims_2ee8ee08176721be1421de2c960482d7` | `6fae120f9eda4aa89b58db18f14d13870e7a4af2342b873b235413bad6301196` |
| Deliverable | `artifact_deliverable_50ad84a7b8f596a1bef1766305fbd729` | `17132f0996aa1c3af625cd255d47425360b0fd15509d8edbc77d69b0f43a1bc3` |
| Review | `artifact_review_1aeffd8bfcd2da4284e300c6ccd74549` | `9bb3ae16880441a3148fda2386a21a03a51621e7525500897d66716f1b01ecac` |
| Report | `artifact_report_8e1232e54c0f7ce2dc58e53331e370c1` | `c603387df908da9c52854deb08643b7337267fb602039936743371a2c96c6861` |

服务 worker 重启后使用 `--verify-run-id` 重新读取同一 Run，并重新计算以上 hash、解析 Evidence pointer、检查 Claim coverage、Review 与 Report 绑定，结果仍为 `passed=true`。这证明恢复依赖 SQLite 持久化事实，而不是残留内存 Task。

## 5. 模型兼容矩阵

| 模型 | structured output | streaming | Function Tool | usage | cancellation | provenance |
| --- | --- | --- | --- | --- | --- | --- |
| GPT-5.2 JoyBuilder | PASS | PASS | PASS | PASS | PASS | PASS |
| GPT-5.4 JoyBuilder | PASS | PASS | PASS | PASS | PASS | PASS |
| GPT-5.5 JoyBuilder | PASS | PASS | PASS | PASS | PASS | PASS |

Kimi 已从 `AGENTMESH_MODELS` 备选池移除，不是本次门禁对象，也未运行测试。

## 6. Web 用户路径证据

Chromium E2E 覆盖：

1. Plan Confirmation 与 Tool Approval 独立；批准 Tool 前 Provider 调用数为 0；
2. SSE Step 进度、Deliverable、Claim → Evidence、Review 和 Report；
3. refresh 不重复 confirm、execute 或 approval mutation；
4. `UNKNOWN` 必须显式 `retry` 或 `abort`，系统不自动重发；
5. `off` 时历史 research-v2 可读，新请求进入 v1；
6. 从对话历史进入、URL 不含 `?run=` 时，thread detail 只读恢复最新 research-v2 Run。

真实 Chrome 对既有 Run `run_685bf5ab05ce` 做了不触发 Provider 的复读：从历史列表打开后，页面在无 `?run=` 参数的情况下展示 Requirement、Tool → Skill、两步完成状态、Deliverable、Evidence 和确定性 Review；22 个渲染引用锚点均指向 verified Evidence，点击后来源区可见，实际模型显示为 GPT-5.2 JoyBuilder。

浏览器自动化只验证 UI 状态与交互；真实 HTTP/SQLite/Provider 完整性由第 4 节的 live smoke 独立覆盖，二者不能互相替代。

## 7. `off` 回滚与恢复证据

独立 `off` 进程使用同一数据库完成演练：

- 历史 `run_685bf5ab05ce` 仍可读取并通过完整性复核；
- 新请求创建 `run_b2076147f3a3`，固定为 `v1/off`；
- 新 Run 不暴露 research projection，并已安全取消；
- open approval 不自动恢复；
- 数据库未 downgrade，Requirement、Plan、Attempt、Artifact、Evidence 和 Report 未删除。

恢复目标为：运行时重启后一个 30 秒 reconciliation 周期内发现可恢复工作；`UNKNOWN` 永不自动重发。真实 Run 的 worker 重启复读和 `off` 演练均满足安全恢复语义。

## 8. 剩余门禁与发布边界

| 判定 | 当前状态 |
| --- | --- |
| Web Preview 工程完成 | 是 |
| Web Execute 工程完成 | 是 |
| Release Gate 工程候选 | 是 |
| 20 条真实 observation | 否 |
| 双人盲评/必要裁决 | 否 |
| 10 人内部试点、至少 8 人认可 | 否 |
| 正式 Release Gate 通过 | 否 |
| 批准 `execute` 灰度 | 否 |
| 迁移其余九个 Skill | 否 |

运行、复核和回滚命令见 `docs/runbooks/research-orchestration-v2.md`。真人门禁完成前，默认继续保持 `off`；若试点不能证明证据与缺口展示的用户价值，则停止扩张 v2，只保留已被单独证明有价值的组件。
