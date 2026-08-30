# Universal Skill Orchestration 发布与回滚手册

- 适用范围：Universal Standard、DeepSearch v2、durable dispatch、terminal projection 和 Runtime capacity
- 最低兼容提交：`2c2cb66` (`Harden orchestration runtime dispatch`)
- 默认状态：`AGENTMESH_SKILL_ORCHESTRATION=off`
- 文档性质：操作模板，不是发布授权或演练证据

## 1. 当前发布结论

截至 2026-08-30，本地实现和回归测试已经完成，但生产切流仍被外部门禁阻断。不得把本手册、测试夹具、自审记录或本地 reviewer 结果当作 CODEOWNER 批准、制品证明或生产演练证据。

| 门禁 | 当前状态 | 放行要求 |
| --- | --- | --- |
| 本地代码与兼容性测试 | 已通过 | 绑定到候选提交和 tree hash 的完整测试记录 |
| 独立代码复审 | 已通过本地复审 | 生产仍需要仓库规则要求的独立 reviewer |
| 84 个 Profile 审签 | 阻断 | 84/84 具有真实 reviewed provenance；draft 不得改成 approved 充数 |
| 分支保护与制品证明 | 阻断 | protected branch、CODEOWNER、reviewed commit、wheel/blob attestation、不可变 release marker |
| 真实 Provider 验收 | 阻断 | Planner、Embedding（如启用）、Web、O2/Data/MCP 的受控环境 smoke |
| Preview 观察窗 | 阻断 | 冻结 holdout 和 500 次经同意的 Preview 请求达到方案门槛 |
| 生产形态容量 | 阻断 | 30 分钟 SQLite、SSE、3 节点并发和 recovery backlog soak |
| 停机与回滚演练 | 阻断 | ingress fence、关闭自动重启、force-stop、备份恢复和 `off` 重启演练 |

任一阻断项未关闭时，只能保持 `off`，或在隔离环境继续离线评测。不得进入生产 `preview` 或 `execute`。

## 2. 不变量

1. 只允许一个应用进程持有生产 SQLite writer lock。部署采用 stop-old-before-start-new，不使用共享 SQLite 的滚动副本。
2. Task Catalog v1、FrozenPlan v1、Snapshot v1 和 legacy parser 不得改写。v2 按精确 `(catalog_version, catalog_hash)` 读取，不允许回退。
3. 旧 `execution_contract_version=null` Plan 永久不可执行。
4. Universal 执行只允许 `read` 和 `draft`。`local_write`、`external_write` 保持关闭。
5. Draft Profile 只参加显式离线评测，不进入生产 Planner。
6. 一旦数据库写入新语义记录，不部署无法读取 v1/v2 合同的旧二进制，不直接用 `git revert` 做代码降级。故障处理使用兼容二进制、`off` 和 roll forward。
7. Quiesce 只关闭当前进程的 admission latch，不修改环境变量。进程重启后必须由配置继续保持 `off`。
8. Tool call 已 claim 但外部结果无法确认时，保留 `external_outcome_unknown`，不自动 retry 或 replan。

## 3. 候选提交和制品冻结

当前实现链如下，候选提交必须包含 `2c2cb66` 及其全部祖先：

| 提交 | 内容 |
| --- | --- |
| `130c1c3` | Phase 0 兼容、SQLite、quiesce 和 recovery 验证 |
| `0046726` | 离线 Universal Skill Profile 检索基础 |
| `141f0f6` | Task Catalog v2 不可变资产 |
| `8ebfffe` | Universal retrieval、coverage 和 readiness |
| `8b5561d` | 84 个 Profile sidecar |
| `fdc8e56` | Standard Universal Preview |
| `44a14dd` | Standard Universal execution contract |
| `25aaf06` | DeepSearch FrozenPlan v2 |
| `c0698c1` | Phase 3 验证证据 |
| `2c2cb66` | Durable dispatch、projection 和 Runtime capacity |

在受保护分支合并后，由发布系统记录实际候选提交。以下命令只生成本地事实，不构成签名或 attestation：

```bash
set -euo pipefail
export RC_COMMIT="$(git rev-parse HEAD)"
export RC_TREE="$(git rev-parse HEAD^{tree})"

test -z "$(git status --porcelain)"
git merge-base --is-ancestor 2c2cb66 "$RC_COMMIT"
printf 'commit=%s\ntree=%s\n' "$RC_COMMIT" "$RC_TREE"
```

发布记录必须另外包含：

- protected PR 和 merge queue 结果；
- 独立 reviewer 身份；
- 构建系统生成的 artifact digest；
- wheel/blob attestation；
- 部署环境、区域、Provider 配置摘要；
- 不可变 release marker；
- 本次 holdout、Preview、soak 和 rollback rehearsal 的证据地址。

上述字段缺一项，发布状态保持 blocked。不得手工补写伪造值。

## 4. 候选版本验证

所有命令必须在候选提交的干净工作树中运行。后端和前端顺序执行，避免 Vite 替换 `dist/` 时与静态路由测试竞态。

```bash
set -euo pipefail
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
git diff --check

PYTHONPATH="$PWD" .venv/bin/python agentmesh-demo/scripts/export_openapi.py
agentmesh-demo/node_modules/.bin/openapi-typescript \
  agentmesh-demo/openapi.json \
  -o agentmesh-demo/src/api/generated/schema.ts
npm --prefix agentmesh-demo test
npm --prefix agentmesh-demo run build

test -z "$(git status --porcelain)"
```

确定性 Catalog 和检索门禁：

```bash
set -euo pipefail
PYTHONPATH="$PWD" .venv/bin/python scripts/build_task_catalog.py \
  --catalog-version user-research-v1 \
  --output-root agentmesh/task_catalog/user-research-v1 \
  --check

PYTHONPATH="$PWD" .venv/bin/python scripts/build_task_catalog.py \
  --catalog-version user-research-v2 \
  --output-root agentmesh/task_catalog/user-research-v2 \
  --check

PYTHONPATH="$PWD" .venv/bin/python scripts/sync_wiki_skills.py --check
PYTHONPATH="$PWD" .venv/bin/python eval/run_skill_retrieval_eval.py
PYTHONPATH="$PWD" .venv/bin/python eval/run_universal_skill_retrieval_eval.py
PYTHONPATH="$PWD" .venv/bin/python -m eval.run_universal_skill_profile_smoke --mode both
```

必须核对：

```text
Task Catalog v1: 480d88f8f9d11c0f24bcff7ecb6f2a333d5852391bb80ee2de9217b81b6b9629
Task Catalog v2: 370fbb879ad6447a03f298cbd85009fd3435ac33ee134178c0864b17cebc49a5
Phase 1 calibration: d965ca93cae3f1985b33714df4b0f0bf4e52345acf1699fc45f0ed2eb85d8954
```

如果生成命令留下 tracked diff，候选版本无效。先修复并重新走评审，不在发布机上提交生成结果。

## 5. 部署前检查

### 5.1 数据库与进程

- 确认 `AGENTMESH_DB_PATH` 指向预期数据库。
- 确认只有一个应用进程使用该数据库。
- 确认备用目录与数据库源目录不同，容量至少覆盖当前数据库、预计增长和一份回滚副本。
- 确认进程管理器支持关闭自动重启、等待 PID 退出和必要时 `SIGKILL`。
- 确认公共 ingress 能原子拒绝所有 Runtime mutation。
- 确认部署器可以从 loopback 或受控管理网访问管理端点。

### 5.2 Profile 和 Provider

- 84/84 Profile 必须通过真实审签和 provenance 校验。
- `skill_profile_trust` 必须为 `ready`。
- 真实 Planner smoke 必须满足方案中的成功率和 p95/p99 门槛。
- 计划启用外部 Vector 时，必须先完成真实 Embedding smoke；否则保持 FTS-only。
- Web、O2、Data 和 MCP 只能启用已审 adapter。27 个 `tool_limited` Skill 不得标记为可执行。

### 5.3 健康检查

使用受保护的管理员会话读取：

```bash
set -euo pipefail
curl --fail --silent --show-error \
  -H 'Cookie: <authenticated-admin-session>' \
  https://<host>/api/health/providers \
  | jq '.providers[] | select(.name == "openai_agents_sdk" or .name == "sqlite_writer")'
```

检查项：

- `sqlite_writer.lock_enforced=true`；
- release id 与候选制品一致；
- `skill_profile_trust=ready`；
- `profile_errors=0`；
- `index_health=ready`；
- Runtime capacity 当前值没有持续贴近上限；
- `deepsearch_recovery_running` 与目标模式一致。

## 6. 切流顺序

### 6.1 `off`

先以兼容二进制和以下配置部署：

```bash
set -euo pipefail
export AGENTMESH_AGENT_RUNTIME=v2
export AGENTMESH_SKILL_ORCHESTRATION=off
```

验证历史 Standard、DeepSearch v1/v2、Plan、Artifact 和 SSE 读取。`off` 下不允许 planned orchestration 或 recovery 创建新工作；direct explicit 和普通 AgentRuntime 按既有合同继续工作。

### 6.2 `preview`

只有 Profile、Provider、holdout 和发布治理门禁全部通过后，才允许切换：

```bash
set -euo pipefail
export AGENTMESH_SKILL_ORCHESTRATION=preview
```

Preview 只生成和编辑 Plan，不执行 Universal 节点。观察窗至少包含 500 次经用户同意且已标注范围的请求。记录 coverage、澄清、repair、终态成功率、Planner 时延、token、费用、SQLite 锁等待和 SSE 指标，不保存原始敏感 Prompt。

达到任一停止条件时，关闭 ingress mutation，quiesce 并按第 8 节回滚，不直接热改环境变量。

### 6.3 `execute`

只有 Preview 观察窗和 rollback rehearsal 通过后，才允许切换：

```bash
set -euo pipefail
export AGENTMESH_SKILL_ORCHESTRATION=execute
```

首批执行仍只允许 `read` 和 `draft`。确认 `universal_execution_available=true`，并验证旧 null-marker Plan 仍被拒绝。DeepSearch 还要求 `AGENTMESH_DEEPSEARCH_ENABLED=true` 和真实健康的受信 Web adapter。

## 7. 停止条件

出现以下任一情况，停止新增流量并进入回滚：

- `database is locked`、writer lock owner 异常或 WAL/checkpoint 超出已审阈值；
- dispatch backlog 持续增长，或 terminal Run 缺少 projection receipt；
- `external_outcome_unknown` 异常增长；
- Planner schema/coverage failure、意外澄清或无候选比例超过冻结门槛；
- LLM、Tool、Run、SSE 或 recovery capacity 长时间饱和；
- Profile、Catalog、Tool implementation、Resource manifest 或 Evidence Policy identity 漂移；
- Provider 区域、保留策略、审计策略或凭据状态与审批记录不一致；
- 任何跨 Workspace/Project 数据泄漏、未经批准的写操作或 public projection 泄漏。

## 8. 回滚

### 8.1 进入停机窗口

以下两项由部署平台实现，本仓库没有可移植的通用命令：

1. 关闭进程管理器自动重启。
2. 在公共 ingress 原子拒绝所有新 Runtime mutation，只保留读取和显式 cancel。

缺少任一能力时，不执行在线回滚。

从 loopback 使用真实管理员会话调用。下面命令中的 `pipefail` 不可删除：

```bash
set -euo pipefail
curl --fail --silent --show-error \
  -X POST \
  -H 'Cookie: <authenticated-admin-session>' \
  http://127.0.0.1:8010/api/admin/skill-orchestration/quiesce
```

期望响应：

```json
{
  "state": "quiesced",
  "active_permits": 0,
  "deepsearch_recovery_running": false
}
```

收到响应后立即停止唯一应用进程。worker drain grace 为 0。进程管理器最多等待 10 秒确认 PID 消失，未退出则执行受控 `SIGKILL`。不得把这 10 秒当作继续运行任务的 drain 窗口。

### 8.2 离线 dry-run

确认 PID 已退出，且没有其他进程持有 SQLite writer lock：

```bash
set -euo pipefail
export DATABASE=/absolute/path/to/agentmesh.sqlite3
PYTHONPATH="$PWD" .venv/bin/python scripts/quiesce_skill_orchestration.py \
  --database "$DATABASE" \
  | tee /secure/release-evidence/quiesce-dry-run.json
```

检查：

- `anomaly_codes` 为空；
- Run、Plan、active dispatch 和 unresolved Tool call 数量符合停机前观测；
- `operation_checksum` 已保存；
- terminal Run 若缺 projection receipt，必须先调查，不能 apply。

### 8.3 双人批准

`--apply` 要求两个不同的真实批准人。单人项目不能满足该门禁，测试中的 `@operator-one`、`@operator-two` 只是假数据，不构成生产批准。

批准文件必须保存在仓库外，不得提交：

```json
{
  "schema_version": "orchestration-quiesce-approval-v1",
  "operation_checksum": "<dry-run-operation-checksum>",
  "approved_by": ["@real-reviewer-1", "@real-reviewer-2"]
}
```

### 8.4 备份、恢复 smoke 和 apply

备份必须写入与源数据库不同的目录，备份和 receipt 目标都必须不存在。两个父目录都必须由发布系统控制，不允许其他用户写入；脚本会以 `0600` 权限原子发布文件，并拒绝符号链接和并发占位。

```bash
set -euo pipefail
export CHECKSUM='<dry-run-operation-checksum>'
export APPROVAL_FILE=/secure/release-evidence/quiesce-approval.json
export BACKUP=/separate-volume/agentmesh-$(date -u +%Y%m%dT%H%M%SZ).sqlite3
export RECEIPT=/secure/release-evidence/quiesce-apply-$(date -u +%Y%m%dT%H%M%SZ).json

PYTHONPATH="$PWD" .venv/bin/python scripts/quiesce_skill_orchestration.py \
  --database "$DATABASE" \
  --apply \
  --expected-operation-checksum "$CHECKSUM" \
  --backup "$BACKUP" \
  --approval-file "$APPROVAL_FILE" \
  --receipt "$RECEIPT" \
  | tee /secure/release-evidence/quiesce-apply-stdout.json
```

脚本在修改前执行：

- SQLite backup API 备份；
- 源库和备份库 `PRAGMA integrity_check`；
- SHA-256 和字节数记录；
- source schema/user version 记录；
- Run、Plan、Artifact、dispatch 和 projection receipt 数量核对；
- 从备份恢复到隔离临时数据库；
- 恢复库 integrity check；
- 恢复库 repository inventory smoke；
- 恢复库 inventory checksum 与 dry-run checksum 核对；
- 以 `0600` 权限原子发布备份，拒绝既有文件、符号链接和并发占位；
- 在数据库变更前，以 `0600` 权限原子写入 `status=backup_verified` 的 durable receipt。

receipt 随后依次更新为 `applied` 和 `verified`。即使 apply 已提交后进程退出或 postcheck 失败，原有 receipt 仍包含备份路径、SHA-256 和 restore smoke。任一步备份验证失败，`--apply` 都不会执行。

### 8.5 apply 后检查

应用仍须保持停止状态：

```bash
set -euo pipefail
PYTHONPATH="$PWD" .venv/bin/python scripts/quiesce_skill_orchestration.py \
  --database "$DATABASE" \
  | tee /secure/release-evidence/quiesce-postcheck.json
```

期望：

- `run_ids=[]`；
- `unresolved_tool_call_ids=[]`；
- `anomaly_codes=[]`；
- 没有 active dispatch；
- 备份 SHA-256 与 apply receipt 一致。

### 8.6 失败恢复

如果 apply 后检查失败，不启动应用，也不覆盖原数据库文件。以 `--receipt` 指定的 durable receipt 为准，不依赖可能缺失的 stdout 文件。使用其中记录的备份，在隔离的新路径通过 SQLite backup API 恢复，再执行 integrity check、inventory 和只读 API smoke。由部署平台把 `AGENTMESH_DB_PATH` 原子切换到复验通过的新路径。

禁止：

- 用 `cp` 覆盖正在使用或已损坏的 SQLite 文件；
- 删除 WAL/SHM 文件来伪造恢复；
- 在原路径反复 apply；
- 部署旧 parser；
- 修改已封存 Plan、Result 或 Artifact；
- 把未知外部写结果改成成功或确定失败。

### 8.7 以 `off` 重启

只使用仍能读取 v1/v2 合同的同一候选二进制或更新的前向兼容修复版本：

```bash
set -euo pipefail
export AGENTMESH_SKILL_ORCHESTRATION=off
export AGENTMESH_DB_PATH=/path/selected-after-restore.sqlite3
```

采用 stop-old-before-start-new 启动一个进程。启动后验证：

- `skill_orchestration_mode=off`；
- `deepsearch_recovery_running=false`；
- `sqlite_writer.lock_enforced=true`；
- 历史 Standard、DeepSearch v1/v2、Plan 和 Artifact 可读；
- 新 planned orchestration 被拒绝；
- 普通读取和允许的 direct explicit 路径正常；
- 未解决 Tool approval 不会自动恢复。

## 9. 证据保存

每次候选发布建立独立证据目录，至少保存：

- commit、tree hash、PR、review 和 merge queue 记录；
- artifact digest、attestation 和 release marker；
- 后端、前端、Catalog、retrieval、Profile、E2E 和 Provider 测试结果；
- holdout、Preview 和 soak 报告；
- quiesce dry-run、apply、postcheck JSON；
- 备份 SHA-256、字节数、schema/user version 和 restore smoke；
- ingress fence、进程停止、writer-lock 竞争和 `off` 重启时间线；
- 停止条件、异常、人工处置和最终放行人。

证据目录不得包含数据库、Cookie、API Key、原始 Prompt、Tool 输出、用户内容或其他敏感数据。

## 10. 本地已验证基线

本地平台提交 `2c2cb66` 的完整实现验证记录在：

- `docs/verification/2026-08-29-universal-runtime-platform.md`
- `docs/verification/2026-08-29-universal-skill-phase3-deepsearch-v2.md`
- `docs/verification/2026-08-29-universal-skill-phase2b-execution.md`
- `docs/verification/2026-08-29-universal-skill-phase2a-preview.md`

本次 runbook 和 rollback tool 增量的聚焦验证记录在：

- `docs/verification/2026-08-30-universal-release-runbook.md`

后者只覆盖 runbook、备份/恢复和离线 rollback 命令，不替代第 4 节的完整候选门禁。以上记录都不能替代本手册第 1 节列出的生产外部门禁。
