# Research Orchestration v2 运行手册

> 状态：工程候选；默认保持 `off`
>
> 适用边界：单 Workspace、单 FastAPI 进程、单 SQLite、可信内网或隔离本机

## 1. 使用边界

Research v2 只接管 eligible competitive research 请求。普通聊天、其他 Skill 和 Legacy command 继续走 v1。当前工程门禁已通过，但 20 条真实观察、双人盲评和 10 人内部试点尚未完成，因此不得把本手册当作正式 `execute` 灰度授权。

生产控制只有一个开关：

| 值 | 新请求 | 历史 research-v2 |
| --- | --- | --- |
| `off` | 只创建 v1 | 只读可见 |
| `preview` | 创建 Requirement 和 Plan，不执行 Step | 可读 |
| `execute` | 经 Plan Confirmation 和独立 Tool Approval 后执行 | 可读 |

切换开关不会改变既有 Run 的 `orchestration_version`。

## 2. 前置条件

- Python 环境与前端依赖已按根目录 `README.md` 安装；
- `AGENTMESH_WIKI_ROOT` 指向批准的 Wiki 目录；
- real Web 验证使用批准的 Tavily 配置，密钥只从 secret manager 或 ignored `.env` 注入；
- 新 research-v2 请求只接受 `execution_mode=real` 且 `health_state=healthy` 的 Web Runtime；空配置与 `mock` 都会在创建 Thread/Run 前失败；
- 模型池只配置实际启用的 GPT-5.2、GPT-5.4、GPT-5.5；Kimi 不在备选池；
- Provider 验证必须使用隔离的 demo 数据库，不能对共享或生产 SQLite 运行 smoke；
- `.env`、SQLite、完整 prompt、Provider 原文、cookie 和 API key 不得进入 Git 或验证文档。

## 3. 本机 Web 体验

后端终端：

```bash
export AGENTMESH_AGENT_RUNTIME=v2
export AGENTMESH_SKILL_ORCHESTRATION=execute
export AGENTMESH_WEB_PROVIDER=tavily
export AGENTMESH_TAVILY_API_URL=https://api.tavily.com/search
# AGENTMESH_TAVILY_API_KEY 仅从 secret manager 或 ignored .env 注入
export AGENTMESH_WIKI_ROOT=/absolute/path/to/approved/wiki
export AGENTMESH_DEMO_MODE=1
.venv/bin/python -m uvicorn agentmesh.app:app --reload --port 8010
```

前端终端：

```bash
npm --prefix agentmesh-demo run dev -- --port 5178 --strictPort
```

打开 `http://127.0.0.1:5178`，登录后输入：

> 对比三款面向企业产品团队的 AI 研究助手，重点分析证据可追溯、任务恢复和协作能力，给出适用场景与局限。

应依次看到：

1. 一个持久化 Plan；明确请求不应出现空澄清页；
2. “确认此计划”，并明确提示该动作不会批准 Provider 调用；
3. “开始执行研究”；
4. 独立 Tool Approval，批准前 Provider 调用数必须为 0；
5. SSE Step 进度；刷新页面后继续读取同一 Run，不创建第二次执行；
6. 结构化 Deliverable、可点击 Evidence、gap、确定性 Review 和 Report；
7. 技术详情中的 requested/actual model、Tool implementation、Artifact 和 plan hash。

离开工作台后从左侧历史对话重新进入同一线程，即使 URL 没有 `?run=`，也应自动恢复该线程最新的 research-v2 审计面板；该读取不得创建新 Run 或 Provider 调用。

若 Provider 在提交时未就绪，`POST /api/agent/runs` 返回 `503`，`detail` 中包含稳定 `code` 与安全 `message`，且不会创建 Thread、Run 或后台任务。修复配置后应重新提交任务；不要修改或续跑在规划阶段已经失败的旧 Run。若 Provider 在准入后、计划冻结前失效，Run 仍会 fail closed，Workspace 必须显示“研究执行失败”和稳定错误代码，不能显示“研究已结束”或“计划预览”。

如果外部调用进入 `UNKNOWN`，页面只能显示 `retry` 与 `abort`：

- 只有人工确认 Provider 未完成原操作后，才选择 `retry`；
- 无法确认时选择 `abort`；
- 浏览器刷新、SSE 重连和进程重启都不得自动重发。

## 4. 本地确定性门禁

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
npm --prefix agentmesh-demo test -- --run
npm --prefix agentmesh-demo run api:types
npm --prefix agentmesh-demo run build
npm --prefix agentmesh-demo run test:e2e
.venv/bin/python eval/run_skill_retrieval_eval.py
.venv/bin/python scripts/skill_catalog_report.py agentmesh/builtin_skills
.venv/bin/python eval/research_orchestration/run_eval.py
```

最后一条命令只校验 20 条固定样本与 rubric。没有真实 observations、盲评和试点输入时，预期输出包含：

```json
{"assets_valid":true,"human_review_complete":false,"pilot_complete":false,"release_gate_passed":false}
```

这不是失败，也不是发布通过；它防止把评测资产存在误报为真人门禁完成。

传入 `--observations` 时，JSONL 还必须提供真实人工抽检得到的 Evidence 支持计数、模型/Tool 调用与 receipt 计数，以及同一计量口径下的 v1/v2 Provider 成本。runner 会执行 90% Evidence 支持准确率、100% receipt 覆盖和 v2 中位成本不超过 v1 两倍的门禁；这些字段不得由模型自评生成。

## 5. 授权 Provider 全链路

先创建隔离目录，并让服务和验证脚本读取同一数据库：

```bash
export RESEARCH_GATE_DIR="$(mktemp -d)"
export AGENTMESH_DB_PATH="$RESEARCH_GATE_DIR/agentmesh.sqlite3"
export AGENTMESH_DEMO_MODE=1
export AGENTMESH_AGENT_RUNTIME=v2
export AGENTMESH_SKILL_ORCHESTRATION=execute
export AGENTMESH_WEB_PROVIDER=tavily
```

在批准凭证已经注入的前提下启动后端，然后依次运行：

```bash
.venv/bin/python scripts/provider_smoke.py --web
AGENTMESH_CHAT_LLM_TIMEOUT_SECONDS=60 .venv/bin/python scripts/agent_sdk_smoke.py --all-configured
.venv/bin/python scripts/research_orchestration_smoke.py --database "$AGENTMESH_DB_PATH"
```

完整 smoke 会输出脱敏的 `run_id`、requested/actual model、Tool mode、receipt 状态、Artifact ID/hash、Evidence pointer、Claim coverage 和 Review 结果。它不得输出 prompt、API key、私有正文或完整 Tool payload。

保存输出中的 Run ID，重启同一后端和数据库后复核：

```bash
export RESEARCH_GATE_RUN_ID=<redacted-run-id>
.venv/bin/python scripts/research_orchestration_smoke.py \
  --database "$AGENTMESH_DB_PATH" \
  --verify-run-id "$RESEARCH_GATE_RUN_ID"
```

成功标准：同一 Run 可读，Artifact hash 被重新计算，Evidence pointer 可解析，factual Claim coverage 为 100%，Review 全部通过，Report 仍绑定已审查 Deliverable。

## 6. `off` 回滚演练

停止原服务，在同一数据库上以 `off` 重启：

```bash
export AGENTMESH_SKILL_ORCHESTRATION=off
.venv/bin/uvicorn agentmesh.app:app --port 8010
```

然后运行：

```bash
.venv/bin/python scripts/research_orchestration_smoke.py \
  --database "$AGENTMESH_DB_PATH" \
  --verify-off-run-id "$RESEARCH_GATE_RUN_ID"
```

必须同时满足：

- 旧 research-v2 Run 及其完整性链仍可读取；
- 新请求创建 `v1/off` Run；
- 新 Run 没有 research projection；
- open approval 不自动恢复；
- 不删除记录，不执行数据库 downgrade；
- 已 SENT 调用只能在完成记账后停到安全点，不能伪装成已取消。

## 7. 故障处置

| 信号 | 操作 |
| --- | --- |
| `409` state/version conflict | 重新读取 aggregate projection，不复用旧 `state_version` |
| Tool Approval 超时 | 读取最新 gate；不得直接调用 Provider 或复用过期 approval |
| Invocation `UNKNOWN` | 先向 Provider/审计系统核对；确认未执行才 retry，否则 abort |
| Artifact integrity error | 停止下游 Report；保留证据并重新运行任务，不手工覆盖 hash |
| 新请求返回 `503 tool_runtime_unregistered` | 注册 Web Research Runtime，确认服务加载的是当前配置后重新提交；不会产生 Run |
| 新请求返回 `503 tool_runtime_not_real` | 将空配置或 `mock` 替换为批准的 Tavily 配置；不得用 Mock 冒充真实通过 |
| 新请求返回 `503 tool_runtime_unhealthy` | 检查 Tavily 凭据、端点和连通性，通过 Provider smoke 后重新提交 |
| 已接受 Run 因 Provider health 失败 | 保留失败 Run 供审计，修复配置后提交新任务；不得改写旧 Run |
| `off` 后仍出现 research-v2 新 Run | 立即停止灰度，检查唯一服务端开关和进程环境 |

Runtime 默认每 30 秒扫描恢复候选；运行中 Attempt 每 15 秒 heartbeat，lease 默认 60 秒。超过一个扫描周期仍未收敛时，保存脱敏 Run/Attempt/Invocation ID 和事件序列，禁止通过重复点击制造新的 mutation。

## 8. 真人 Release Gate

工程候选之外还必须完成：

1. 对固定 20 条样本分别收集真实 v1/v2 observation；模型非确定性指标连续运行三次，至少两次满足门禁；
2. 将输出随机标为 A/B，由两名评审独立评分；任一维度分差超过 1/5 时交第三名评审裁决；
3. 完成 10 人内部试点，至少 8 人认可 Evidence 和 gap 的实际价值；
4. 只有以上证据与第 5 节机器阈值同时满足，Release owner 才能批准受控 `execute` 灰度。

observation 字段与阈值以 `eval/research_orchestration/rubric-v1.yaml` 为唯一口径。人工评分和试点记录只保存必要的脱敏结果，不将用户原文或 Provider 原文提交到仓库。
