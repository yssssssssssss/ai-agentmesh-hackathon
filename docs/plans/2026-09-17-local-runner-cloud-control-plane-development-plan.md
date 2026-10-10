# AgentMesh 本地 Runner + 云端控制平面开发方案

- 日期：2026-09-17
- 状态：Runner MVP 已完成；DeepSearch、写工具与生产基础设施按独立后续计划推进
- 编写基线：`5a7e7c5`
- 目标：将当前“FastAPI 进程内执行 Agent”的架构改造成“本地 Runner 执行，云端控制平面统一汇总”
- 适用范围：FastAPI、React、Agent Runtime v2、OpenAI Agents SDK、SQLite/PostgreSQL、CLI、Runner
- 实施原则：渐进改造、每个纵向切片可独立合并、保留日常开发能力、不建立重型审核与测试体系

## 1. 决策摘要

AgentMesh 采用以下目标架构：

```text
用户终端：AgentMesh CLI + Local Runner
云端服务：AgentMesh Control Plane + Web UI + Database
```

具体决策如下：

1. LLM 调用、Skill 规划、Skill 执行和本地 Tool 调用发生在用户终端 Runner。
2. 云端拥有 User、Workspace、Project、Task、AgentRun、Memory、Approval、Audit 和 Artifact 元数据的最终状态。
3. Runner 只通过 HTTPS API 领取任务、续租、上报事件、上传 Artifact 和提交执行结果。
4. Runner 不直接连接云数据库，也不获得数据库连接字符串。
5. 本地 Provider 密钥、CLI 登录态和本地文件权限默认不上传云端。
6. 云端 Web UI 继续使用现有 Run 查询和 SSE 接口，不感知执行发生在服务器还是 Runner。
7. 第一阶段仍可使用单进程 FastAPI + SQLite；Runner 闭环稳定后再单独迁移 PostgreSQL。
8. 用户终端不依赖 Docker。Docker 仅作为云端 Server 的可选部署方式。
9. 当前仓库继续作为单一代码仓库，不立即拆成多个仓库或多个独立产品。
10. 第一条远程执行链路只覆盖 `standard_direct`，不同时迁移 DeepSearch、完整 DAG 和所有 Tool。

## 2. 目标与成功标准

### 2.1 产品目标

多个用户可以在各自终端运行 AgentMesh Runner，使用本机的：

- 模型 Provider 凭据；
- 文件和项目目录；
- Git、Python、Node 等 CLI；
- MCP、Browser Bridge 和其他本地工具；
- 本地授权的 Skill 执行适配器。

执行过程中的 Run、Event、Artifact、Task、Memory 和 Audit 数据统一汇聚到云端，用户可以在任意浏览器或已登录终端查看同一份状态。

### 2.2 第一阶段成功标准

第一阶段只要求打通一个可靠的纵向闭环：

```text
用户从 Web/CLI 创建 Run
  → 云端持久化 Run 和待执行 Dispatch
  → 指定用户的本地 Runner 领取任务
  → Runner 本地调用模型完成 standard_direct
  → Runner 批量上报 Event
  → Runner 提交最终结果
  → 云端完成 Run 并通过 SSE 更新 Web
```

必须满足：

1. 云端 Server 不执行该 Run。
2. Runner 不访问云数据库。
3. 其他用户的 Runner 不能领取该 Run。
4. 重复领取、重复 Event 和重复完成请求不会造成重复数据。
5. Runner 断线后 Lease 可以过期，旧 Lease 不能覆盖新执行。
6. Web 刷新和 SSE 重连仍能读取完整进度。
7. 当前 Task、Memory、Inbox 和权限功能继续可用。

## 3. 非目标

第一阶段不建设以下能力：

- 公网多租户 SaaS；
- 多 Workspace 租户隔离重构；
- Kubernetes 和多区域高可用；
- Kafka、RabbitMQ 或 Redis 队列；
- 完整离线执行与双向冲突合并；
- 任意 Runner 自动抢占其他用户任务；
- 自动执行下载自互联网的第三方代码；
- Runner 自动升级平台；
- 桌面壳；
- 完整 DeepSearch 和多节点 DAG 迁移；
- SQLite 与 PostgreSQL 同时进行的大规模持久化重写；
- 大规模压力测试、形式化安全认证或多轮独立审核。

这些能力只有在实际用户规模和运行数据证明有需要时再增加。

## 4. 当前代码基线

### 4.1 已有可复用能力

当前项目已经具备：

- `AgentRun` 和稳定 Run 身份；
- `RunDispatchReceiptV1`；
- `operation_key`、`generation` 和 `attempt_count`；
- `pending → started → settled` 的持久化 Dispatch；
- `AgentRunEvent` 和服务端分配的有序 sequence；
- `GET /api/agent/runs/{run_id}/events/stream` SSE；
- Run retry、cancel、approval 和 terminal projection；
- Artifact、内容 Hash 和 Run 血缘；
- Workspace、Project、User 和权限范围；
- SQLite 中的原子 claim/settle；
- OpenAI Agents SDK Runtime；
- React Run 进度与结果 UI。

这些能力意味着项目不需要重新发明 Run、Event、Artifact 或 Web 状态模型。

### 4.2 当前需要改变的执行路径

当前执行路径位于 `agentmesh/agent_runtime/service.py`：

```text
FastAPI 启动 dispatch pump
  → 查询 pending dispatch
  → 当前服务进程 claim
  → asyncio.create_task(...)
  → 当前服务进程调用 SDK Runner
  → 直接写 SQLiteStore
```

目标路径为：

```text
FastAPI 创建 pending dispatch
  → Local Runner 通过 API claim
  → Local Runner 调用 SDK Runner
  → Local Runner 通过 API 上报 Event/Result
  → FastAPI 校验并写云端 Store
```

最大的改造点不是增加几个 HTTP 接口，而是把“执行引擎”和“云端 Repository 写入”分开。Runner 不能通过远程接口调用任意 `SQLiteStore` 方法。

### 4.3 当前平台限制

- `agentmesh/store.py` 使用 `sqlite3` 和 `fcntl`，不能直接作为跨平台 Runner 依赖。
- 当前 `RunDispatchReceiptV1.process_epoch` 表示服务端进程身份，不足以表达 Runner、Lease 和 Lease 过期。
- 当前 CLI 没有正式入口，`pyproject.toml` 未定义 `[project.scripts]`。
- 当前认证主要是浏览器 Cookie Session，不适合长期运行的设备 Runner。
- 当前 Server 和 Agent Runtime 在同一进程组合，应用启动时自动启动 dispatch pump。

## 5. 目标架构

```text
┌──────────────────── 用户终端 ────────────────────┐
│                                                  │
│  agentmesh CLI                                   │
│      │                                           │
│  Local Runner                                    │
│  ├── Runner API Client                           │
│  ├── Lease/Heartbeat                             │
│  ├── OpenAI Agents SDK                           │
│  ├── Skill Execution                             │
│  ├── Tool/MCP/CLI/File Adapters                  │
│  ├── Local Provider Credential Resolver          │
│  └── Local Event/Artifact Spool                  │
└──────────────────────┬───────────────────────────┘
                       │ 仅出站 HTTPS
                       ▼
┌────────────────── AgentMesh Cloud ────────────────┐
│                                                  │
│  FastAPI Control Plane                           │
│  ├── Authentication                              │
│  ├── Runner Enrollment                           │
│  ├── Run/Dispatch/Lease                          │
│  ├── Policy/Approval                             │
│  ├── Event Ingestion                             │
│  ├── Artifact Ingestion                          │
│  ├── Task/Memory/Audit                           │
│  └── React Web + SSE                             │
│                    │                             │
│              SQLite → PostgreSQL                 │
│              Local files → Object Storage        │
└──────────────────────────────────────────────────┘
```

### 5.1 云端控制平面职责

云端负责：

- 身份认证和 Runner 注册；
- Run 创建、权限检查和幂等请求；
- 选择允许领取任务的 Runner；
- 生成不可变 Execution Envelope；
- 原子发放和回收 Lease；
- 校验 Runner Event、Artifact 和完成请求；
- 分配全局 Event sequence；
- 维护 Run 状态机；
- 发起和处理 Approval；
- 持久化 Task、Memory、Audit 和 Artifact 元数据；
- 向 Web 和 CLI 提供统一查询、SSE 和取消接口。

云端不负责：

- 使用用户本地模型密钥调用模型；
- 读取用户本地目录；
- 调用用户本机 CLI；
- 在 FastAPI 进程执行第三方 Skill 代码。

### 5.2 Local Runner 职责

Runner 负责：

- 登录和注册当前设备；
- 检测本地模型、工具和执行能力；
- 长轮询领取属于当前用户的任务；
- 维护 Lease 和 Heartbeat；
- 在本地执行 LLM、Skill 和 Tool；
- 将事件先写入本地 spool，再批量上传；
- 上传允许汇聚的 Artifact；
- 接收取消和 Approval 恢复状态；
- 在断网时停止领取新任务，并重试上传已完成数据。

Runner 不负责：

- 决定最终权限；
- 任意修改 Run 状态；
- 直接写 Task、Memory 或 Audit；
- 将本地 API Key 发送给云端；
- 自动上传整个项目目录。

### 5.3 Web 和 CLI 职责

Web UI 继续由云端提供。现有页面和 SSE 模型原则上保持不变。

CLI 同时承担两种角色：

1. 用户命令客户端，例如 `agentmesh run`、`agentmesh task list`；
2. Runner 生命周期入口，例如 `agentmesh runner start`。

## 6. 执行边界

### 6.1 本地执行范围

以下行为属于 Runner：

- Skill 匹配中的模型调用；
- Plan 生成中的模型调用；
- Agent SDK Runner；
- Tool 调用；
- MCP 调用；
- Provider 请求；
- 本地文件读取和写入；
- 本地 CLI 调用；
- 输出生成和本地 Artifact 构建。

以下行为属于云端：

- 可见 Skill、Tool Grant 和 Policy 的计算；
- Run 和 Plan 的持久化；
- Approval 决策；
- Memory 权限过滤；
- AgentMesh 内部数据查询；
- Event、Artifact、Task 和 Memory 的最终写入；
- 审计和 UI 投影。

Runner 执行中需要读取云端 Memory、文档或 Task 时，应调用受限的 Control Plane API，而不是访问数据库。云端完成权限检查后返回有界数据，并记录对应使用回执。

### 6.2 Execution Envelope

云端发给 Runner 的任务必须是一个不可变执行包。建议首版合同：

```text
ExecutionEnvelopeV1
  schema_version
  envelope_id
  envelope_hash
  lease_id
  lease_expires_at
  run_id
  dispatch_operation_key
  dispatch_generation
  owner_user_id
  workspace_id
  project_id
  thread_id
  task_id
  input
  recent_context
  skill_snapshot
  agent_snapshot
  tool_grants
  policy_snapshot
  model_requirement
  input_artifacts
  budgets
  deadline_at
```

约束：

- 不包含数据库连接信息；
- 不包含云端 Provider 密钥；
- 不包含其他用户不可见内容；
- Skill 指令和 Policy 使用冻结版本；
- 执行适配器代码来自已安装 Runner，不从任务包动态执行任意代码；
- Runner 必须验证 Envelope Hash、Lease 和协议版本。

### 6.3 Model Requirement

云端只声明模型能力需求，不发送密钥：

```json
{
  "provider_protocol": "openai-compatible",
  "model_id": "default",
  "required_capabilities": ["streaming", "tool_calls"]
}
```

Runner 使用本地配置把逻辑 `model_id` 映射到本地 Provider：

```text
model_id=default
  → local provider profile
  → endpoint/model/key from OS credential store
```

如果本地没有满足条件的 Provider，Runner 不领取该任务，或者返回明确的 `capability_unavailable`，不能静默切换为云端执行。

## 7. Runner 身份、注册与能力

### 7.1 RunnerDeviceV1

```text
schema_version = runner-device-v1
id
owner_user_id
workspace_id
name
platform
architecture
runner_version
protocol_version
public_key
capabilities_digest
status: active | offline | revoked
last_seen_at
created_at
revoked_at
```

第一版约束：

- 一个 Runner 只属于一个用户；
- 默认一个用户只有一个 active Runner；
- Runner 只能领取该用户创建或明确分配给该用户 Runner 的 Run；
- revoked Runner 不能 Heartbeat、Claim、Renew 或上传结果。

### 7.2 注册流程

采用一次性设备码流程：

```text
agentmesh setup --server https://mesh.example.com
  → CLI 请求 device_code 和 user_code
  → CLI 打开云端 verification URL
  → 用户在浏览器登录并确认设备
  → CLI 轮询取得 Runner Credential
  → 本地生成并保存设备身份
```

建议接口：

| 方法与路径 | 用途 |
| --- | --- |
| `POST /api/runner/enrollment/start` | 创建短期设备码 |
| `POST /api/runner/enrollment/{user_code}/approve` | 已登录用户确认设备 |
| `POST /api/runner/enrollment/token` | CLI 轮询交换 Runner Credential |
| `GET /api/runners` | 用户查看自己的设备 |
| `POST /api/runners/{runner_id}/revoke` | 撤销设备 |

Runner Credential 只允许：

```text
runner:heartbeat
runner:claim
runner:renew
runner:event
runner:artifact
runner:complete
```

它不能调用用户管理、Memory 治理、Task 管理或数据库管理接口。

### 7.3 Capability Snapshot

Runner Heartbeat 上报非敏感能力：

```text
platform / architecture
runner_version / protocol_version
available model capabilities
installed execution adapters
available local tools
supported artifact types
allowed project roots 的摘要
```

不得上报：

- API Key；
- Cookie；
- 完整环境变量；
- 任意目录内容；
- 未授权的绝对路径列表；
- 本机 CLI 输出正文。

## 8. Dispatch 与 Lease

### 8.1 状态模型

当前 `pending → started → settled` 需要扩展为明确的 Runner Lease 语义：

```text
AVAILABLE
  → LEASED
  → RUNNING
  → SETTLED

LEASED/RUNNING
  → LEASE_EXPIRED
  → AVAILABLE

任意未终态
  → CANCELLED
```

数据库中 Run 和 Dispatch 状态仍由云端写入。Runner 只提交命令。

### 8.2 Lease 字段

```text
runner_id
lease_id
lease_generation
lease_expires_at
last_heartbeat_at
attempt_count
```

建议首版固定：

```text
Lease 时长：60 秒
续租间隔：20 秒
```

这些值先集中在一个服务端设置模型中，不为每个用户或 Skill 增加配置项。

### 8.3 Claim 规则

Claim 必须在一个数据库事务内完成：

1. Dispatch 仍可领取；
2. Run 不是终态；
3. Runner active 且属于正确用户；
4. Runner 协议版本兼容；
5. Runner 能力满足任务要求；
6. 当前没有未过期 Lease；
7. 写入 Runner、Lease、Generation 和过期时间；
8. 追加 `run_dispatch_leased` Event。

多个 Runner 同时 Claim 时只有一个成功。

### 8.4 Lease 过期

Lease 过期后：

- 云端允许下一次 Claim 创建新 Generation；
- 原 Runner 可以继续上传本地日志到自己的 spool，但云端拒绝其状态和结果写入；
- 旧 Runner 收到 `409 stale_lease` 后停止该 Run；
- 新 Generation 不复用旧 Generation 的本地副作用。

对于已经执行外部写操作的 Run，第一版不自动重试。云端将其标记为需要人工处理，避免重复副作用。

## 9. Runner API 合同

### 9.1 Runner 运行接口

| 方法与路径 | 用途 |
| --- | --- |
| `POST /api/runner/heartbeat` | 上报在线状态、能力和当前 Lease |
| `POST /api/runner/dispatches/claim` | 长轮询领取一个可执行任务 |
| `POST /api/runner/dispatches/{lease_id}/start` | 确认本地开始执行 |
| `POST /api/runner/dispatches/{lease_id}/renew` | 续租并读取取消状态 |
| `POST /api/runner/dispatches/{lease_id}/events` | 批量上报 Event |
| `POST /api/runner/dispatches/{lease_id}/artifacts` | 上传小型 Artifact |
| `POST /api/runner/dispatches/{lease_id}/complete` | 提交成功或 partial 结果 |
| `POST /api/runner/dispatches/{lease_id}/fail` | 提交稳定失败结果 |

第一版使用 HTTPS 长轮询，不增加 WebSocket。现有 SSE 继续用于云端向 Web/CLI 阅读者推送事件。

### 9.2 Event 批量上报

Runner Event：

```text
RunnerEventV1
  client_event_id
  local_sequence
  event_type
  occurred_at
  payload
```

请求：

```json
{
  "run_id": "run_123",
  "lease_generation": 1,
  "events": []
}
```

云端行为：

1. 验证 Runner 和 Lease；
2. 按 `client_event_id` 去重；
3. 校验事件类型和 payload 大小；
4. 分配现有 `AgentRunEvent.sequence`；
5. 在同一事务写入 dedup receipt 和 Event；
6. 返回已确认的 `client_event_id`。

Runner 收到确认后才能从本地 spool 删除 Event。

### 9.3 完成请求

```text
RunnerCompletionV1
  command_id
  run_id
  lease_id
  lease_generation
  terminal_status: completed | partial
  output_text
  artifact_ids
  usage
  tool_receipts
```

云端需要：

- 验证当前 Lease；
- 验证 Run 尚未终态；
- 检查 Artifact 所有权和 Hash；
- 原子更新 Run、Dispatch、终态 Event 和 output projection；
- 相同 `command_id` 重放返回原结果；
- 不允许 Runner提交任意 Task、Memory 或 Audit payload。

### 9.4 Cancel

用户仍调用现有：

```text
POST /api/agent/runs/{run_id}/cancel
```

云端把 Run 标记为 cancellation requested。Runner 在下一次 Renew/Heartbeat 响应中收到取消指令，停止新的模型和 Tool 调用，然后提交取消确认。

第一版不要求毫秒级取消；要求取消最终可达、状态可解释、不会继续启动新的副作用。

## 10. Artifact 与本地文件

### 10.1 第一版

小型 Artifact 通过 FastAPI 上传：

```text
Runner
  → 上传 bytes + metadata + sha256
  → 云端重新计算 Hash
  → 云端创建 Artifact
  → Runner 完成 Run 时引用 Artifact ID
```

限制沿用服务端请求大小限制，不在第一版引入对象存储。

### 10.2 后续对象存储

当 Artifact 大小或吞吐成为问题时：

```text
Runner 请求上传会话
  → 云端返回预签名 URL
  → Runner 上传对象存储
  → Runner 提交 size/hash/content-type
  → 云端校验并封存 Artifact
```

数据库只保存元数据、权限、Hash 和对象键。

### 10.3 本地文件权限

Runner 配置允许访问的根目录：

```toml
[runner.permissions]
allowed_roots = ["~/work/agentmesh-projects"]
```

规则：

- 默认没有任意文件系统权限；
- 路径必须位于授权根目录；
- 原始文件默认不上传；
- 只上传用户任务明确要求的 Artifact；
- Event 中不记录完整本机绝对路径和凭据内容。

## 11. 本地凭据与 Provider

Runner 使用本地 Credential Store 保存：

- Runner Credential；
- 设备私钥；
- LLM API Key；
- 可选 Tool Token。

云端只保存：

- Runner 公钥；
- Credential Hash；
- Provider 能力摘要；
- 实际使用的逻辑模型和脱敏 Provider 元数据。

CLI 示例：

```bash
agentmesh provider add default \
  --protocol openai-compatible \
  --base-url https://provider.example.com/v1 \
  --model example-model
```

API Key 通过安全输入写入系统 Credential Store，不写入 `config.toml`。

## 12. 本地 Runner 数据

Runner 使用一个独立、跨平台的小型 SQLite spool：

```text
pending_events
pending_artifact_uploads
active_lease
execution_checkpoints
```

它只用于：

- 网络中断重传；
- Event 上传确认；
- Artifact 分片或重试；
- 当前 Lease 的本地恢复提示。

它不保存云端完整业务数据库，也不是 Run 的最终事实源。

建议目录通过 `platformdirs` 获取：

```text
config.toml
runner-spool.sqlite3
logs/
cache/
```

Runner spool 不能导入当前 `agentmesh/store.py`，以避免 `fcntl` 和服务器 SQLite 语义进入 Windows 客户端。

## 13. 用户终端安装

### 13.1 开发者预览

第一条安装渠道：

```bash
pipx install agentmesh
```

或：

```bash
uv tool install agentmesh
```

`pyproject.toml` 增加：

```toml
[project.scripts]
agentmesh = "agentmesh.cli:main"
```

首次配置：

```bash
agentmesh setup --server https://mesh.example.com
agentmesh runner doctor
agentmesh runner start
```

### 13.2 稳定版独立包

GitHub Releases 提供：

```text
agentmesh-macos-arm64.tar.gz
agentmesh-macos-x64.tar.gz
agentmesh-linux-x64.tar.gz
agentmesh-windows-x64.zip
```

使用原生 CI Runner 构建 PyInstaller onedir 包。安装包包含 Python Runtime、Agent Runtime、CLI、内置 Skill 和必要资源，不包含云端 React UI 和 Server Store。

### 13.3 后台运行

第一版使用前台命令：

```bash
agentmesh runner start
```

稳定后增加用户级服务：

```bash
agentmesh runner install-service
```

对应：

- macOS：LaunchAgent；
- Linux：systemd user service；
- Windows：用户服务或计划任务。

不要求管理员权限作为默认安装条件。

## 14. 对当前仓库的最小改造

### 14.1 MVP 新增模块

优先使用少量文件，不提前拆出大量包：

```text
agentmesh/runner_contracts.py   # 云端和 Runner 共享合同
agentmesh/runner_client.py      # HTTPS Client、认证和重试
agentmesh/runner_service.py     # Claim、执行、spool、上报
agentmesh/runner_auth.py        # 设备码和 Runner Credential
agentmesh/cli.py                # CLI 入口
agentmesh/routes/runners.py     # 云端 Runner API
```

当单个模块实际变大后，再拆为 `agentmesh/runner/` 包。第一阶段不为假设中的未来 Provider、队列或部署方式建立插件框架。

### 14.2 修改模块

```text
pyproject.toml
agentmesh/app.py
agentmesh/models.py
agentmesh/store.py
agentmesh/agent_runtime/service.py
agentmesh/routes/agent_runs.py
agentmesh/routes/auth.py
agentmesh/routes/artifacts.py
```

主要变化：

- 增加 CLI entry point；
- 增加 Runner/Lease/Enrollment 模型；
- 将 server process claim 改为 Runner API claim；
- 把执行入口改成接受 `ExecutionEnvelopeV1`；
- 把执行过程写 Store 改成调用 Event Sink；
- 增加 Runner Event 和 Completion ingestion；
- Server 在 Runner 模式下不启动本地执行 dispatch pump；
- 保留现有 Web SSE 和 Run 查询路径。

### 14.3 不应做的改造

- 不为 Runner 暴露通用 Repository HTTP API；
- 不让 Runner 远程调用任意 Store 方法；
- 不复制一套 AgentRun/Task/Memory 状态机到 Runner；
- 不立即移动全部 `agent_runtime/service.py` 代码；
- 不同时更换前端框架；
- 不同时迁移 PostgreSQL；
- 不创建长期存在的两套执行业务逻辑。

## 15. 过渡模式与最终模式

迁移期间允许一个明确的执行位置设置：

```text
AGENTMESH_EXECUTION_LOCATION=server | runner
```

含义：

- `server`：当前进程内执行，仅用于迁移期间保持现有开发和测试；
- `runner`：云端只生成 Dispatch，由 Local Runner 执行。

规则：

1. 一个部署实例只能选择一个执行位置；
2. 同一个 Run 创建时冻结执行位置；
3. Runner 不可用时保持 pending，不自动回退到 server；
4. 远程 Runner 完整覆盖生产路径后，移除产品中的 `server` 模式；
5. 测试可以保留轻量的 in-process Runner Harness，但不保留第二套业务实现。

这不是长期兼容层，而是有删除终点的迁移开关。

## 16. 分阶段实施计划

### Slice 1：Runner 合同、身份与连接

交付：

- `RunnerDeviceV1`；
- `ExecutionEnvelopeV1`；
- Lease、Event Batch、Completion 合同；
- 设备码注册；
- Runner Credential；
- Heartbeat；
- `agentmesh` CLI 骨架；
- Runner 列表和撤销接口。

此 Slice 不改变现有 Run 执行方式。

完成标准：

- 用户可以注册和撤销一台 Runner；
- Runner 可以安全 Heartbeat；
- Credential 不能调用普通用户管理接口；
- 协议模型可以独立序列化和校验。

### Slice 2：`standard_direct` 远程执行闭环

状态：已完成。

交付：

- pending Dispatch 查询；
- 原子 Claim 和 Lease；
- Execution Envelope；
- Runner 本地 SDK 执行；
- Event 批量上报；
- Completion；
- 现有 SSE 展示 Runner Event。

完成标准：

```text
POST /api/agent/runs
→ 本地 Runner 执行
→ Web 实时显示
→ Run completed
```

该 Slice 是架构是否成立的主要验收点。

### Slice 3：可靠性和取消

状态：核心能力已完成，包括 Lease 续租、取消确认、幂等 Event/Completion 和本地 SQLite spool。

交付：

- Lease renew；
- Heartbeat；
- Lease expiry；
- stale lease 拒绝；
- Event idempotency；
- 本地 spool；
- cancel；
- 显式 retry；
- Runner 离线状态。

完成标准：

- 网络短暂中断不丢失已写入 spool 的 Event；
- 旧 Lease 不能提交完成结果；
- cancel 后不启动新的 Tool；
- Runner 崩溃后 Run 状态可解释且可显式重试。

### Slice 4：本地 Tool、文件和 Artifact

状态：Runner MVP 范围已完成。Artifact 上传、Hash 校验、封存和 Completion 绑定已完成；显式授权的只读本地工具 `local_file_read` 已完成。写工具与 Approval 不属于本次 Runner MVP，保留为独立后续范围。

交付：

- 本地 Tool capability；
- 本地文件授权根目录；
- 本地 CLI adapter；
- 小型 Artifact 上传；
- Tool Receipt；
- Provider 本地 Credential；
- Tool Approval 的暂停与恢复。

完成标准：

- 未授权路径不可访问；
- Tool Grant 仍由云端决定；
- Approval 前不能执行副作用；
- Artifact Hash 在云端重新验证。

### Slice 5：Plan 和多节点执行

状态：Runner MVP 范围已完成。Standard Plan 使用云端确定性规划和 DAG 状态机，模型节点通过 Runner 派发、续租和回传结构化结果，最终由云端进行确定性综合。

交付：

- 本地 Plan 模型调用；
- Plan 结果云端持久化；
- Plan Approval；
- approved-plan 新 Generation；
- 多节点 Skill DAG；
- 等待和恢复状态。

不在此 Slice 同时改造 DeepSearch 的所有特殊恢复逻辑。

### Slice 6：DeepSearch 与完整 Runtime

状态：不属于已确认的 Runner MVP，作为独立后续开发范围保留。

交付：

- DeepSearch planning；
- Evidence Artifact；
- Review/finalization；
- 现有 deadline、budget 和 recovery 语义；
- 完整 server execution path 删除。

### Slice 7：发行与云端持久化升级

状态：PyPI/pipx CLI 入口和发布说明已具备；独立二进制、Docker、PostgreSQL 与对象存储不属于本次 Runner MVP。

交付可以按实际需要独立选择：

- GitHub Runner 独立安装包；
- 用户级后台服务；
- 云端 Server Docker 镜像；
- PostgreSQL；
- 对象存储。

这些不是 Runner 协议成立的前置条件。

## 17. 日常开发方式

改造后仍然支持完整本地开发。

### 17.1 目标开发命令

终端一：

```bash
.venv/bin/uvicorn agentmesh.app:app --reload --port 8010
```

终端二：

```bash
.venv/bin/agentmesh runner start \
  --server http://127.0.0.1:8010 \
  --foreground
```

终端三：

```bash
npm --prefix agentmesh-demo run dev -- --port 5178 --strictPort
```

浏览器：

```text
http://127.0.0.1:5178
```

本地 Server 使用临时或开发 SQLite。本地 Runner 使用自己的 spool SQLite。两者不能共享数据库文件。

### 17.2 一键开发命令

Runner 闭环稳定后增加：

```bash
agentmesh dev
```

该命令只负责启动本地 Server 和本地 Runner，前端仍可按当前 Vite 流程独立运行。不要在第一阶段构建复杂进程管理器。

### 17.3 新功能代码归属

| 功能 | 位置 |
| --- | --- |
| User、Workspace、Project、Task、Memory | 云端 Server |
| Run 权限、Lease、Approval、Audit | 云端 Server |
| LLM、Skill、Tool、MCP、本地文件 | Local Runner |
| Execution Envelope、Event、Completion | 共享合同 |
| 页面和运行进度 | React Web |
| 用户命令与 Runner 管理 | CLI |

这样改造后仍然可以继续开发当前产品，只是执行相关功能需要明确落在 Runner 或 Control Plane 的一侧。

## 18. 数据库策略

### 18.1 第一阶段

继续使用：

```text
单个云端 FastAPI 进程
  +
持久化磁盘上的 SQLite
```

所有 Runner 通过 API 写入，由云端单进程串行控制 SQLite 写入。这样可以先验证产品和协议，而不是把执行拆分与数据库迁移绑定在一起。

### 18.2 PostgreSQL 触发条件

出现以下实际需求时再迁移：

- 需要多个 FastAPI 进程写同一数据库；
- SQLite Event 写入形成可观测瓶颈；
- 需要高可用和托管备份；
- 需要公网团队服务；
- 需要多个 Workspace 或更强租户隔离。

PostgreSQL 迁移是后续独立计划，不应阻塞本地 Runner 第一条闭环。

## 19. 安全边界

第一版必须遵守以下最低安全要求：

1. Runner API 只允许 HTTPS；本地开发例外使用 loopback HTTP。
2. Runner Credential 与普通用户 Session 分离。
3. Runner Credential 只具有 Runner 专用 Scope。
4. 服务端保存 Credential Hash，不保存明文。
5. Runner 私钥和 Provider Key 保存在系统 Credential Store。
6. Runner 只领取当前用户和授权项目的任务。
7. 每次 Claim、Renew、Event、Artifact、Completion 都重新验证 Runner 状态和 Lease。
8. Runner 不能提交任意 AuditEvent、Memory 或 Task 状态。
9. 本地文件默认不上传。
10. 日志和 Event 不记录 Token、Key、Cookie 或完整环境变量。
11. 外部写操作不自动跨 Lease 重试。
12. revoked Runner 的所有新请求立即失败。

第一阶段不需要建立独立安全评审委员会、形式化证明或完整攻击矩阵。以上边界通过代码和少量聚焦测试保证即可。

## 20. 精简测试与验证策略

本方案不要求为每个 Slice 建设大规模测试矩阵。只保留能证明核心行为的测试。

### 20.1 必要单元/合同测试

每个新增合同或状态转换覆盖主要成功路径和一个关键失败路径：

- Runner Credential scope；
- Claim 原子性；
- Lease 过期；
- stale lease 拒绝；
- Event 幂等；
- Completion 幂等；
- 用户和 Workspace 隔离；
- Artifact Hash 不匹配。

### 20.2 一条端到端闭环

维护一条不调用真实 Provider 的 fake-runner 测试：

```text
创建 Run
→ Claim
→ Start
→ 上传两条 Event
→ Complete
→ 查询 Run
→ 查询 Event
```

之后按 Slice 增加：

- 一个断线续传场景；
- 一个 cancel 场景；
- 一个 Artifact 场景。

不为每种操作系统、每个 Provider、每个 Skill 复制完整 E2E。

### 20.3 开发中验证

开发期间运行受影响的聚焦测试：

```bash
.venv/bin/python -m pytest tests/test_runner_*.py
.venv/bin/ruff check agentmesh tests
```

涉及 API Schema 时运行：

```bash
npm --prefix agentmesh-demo run api:types
npm --prefix agentmesh-demo test -- --run
```

一个 Slice 合并前运行现有全量后端测试和前端构建。只有涉及用户关键 Web 流程时才增加对应 Playwright 用例。

### 20.4 不要求的验证

第一阶段不要求：

- 大规模并发压测；
- 长时间 soak；
- 多评审人签字；
- 针对每个 Provider 的真实网络测试；
- 所有平台的完整 E2E；
- 故障注入平台；
- 复杂形式化审计报告。

这些不能代替基本测试，但也不应阻塞第一条 Runner 闭环。

## 21. 发布方式

### 21.1 云端 Server

发布：

```text
GitHub source
Docker image
compose.yaml
```

云端启动示例：

```text
AGENTMESH_EXECUTION_LOCATION=runner
AGENTMESH_DB_PATH=/data/agentmesh.sqlite3
```

### 21.2 Local Runner

发布：

```text
PyPI/pipx 开发者版本
GitHub Releases 独立安装包
```

用户安装和运行：

```bash
pipx install agentmesh
agentmesh setup --server https://mesh.example.com
agentmesh runner start
```

Web UI 地址由云端提供：

```bash
agentmesh open
```

## 22. 迁移与回退

### 22.1 迁移原则

- 先新增 Runner 协议，再切换执行位置；
- 每个 Slice 独立合并；
- 当前 Run API 和 SSE 尽量保持稳定；
- Runner 数据结构先 additive；
- 不同时改数据库引擎；
- 不长期维护两套执行逻辑。

### 22.2 迁移期间回退

远程闭环未完成前，可以将：

```text
AGENTMESH_EXECUTION_LOCATION=server
```

作为临时回退。已经创建为 Runner 执行位置的 Run 不自动改为 Server 执行，避免重复执行。

### 22.3 完成后的回退

远程 Runner 成为唯一产品执行路径后：

- 云端停止创建 server execution Run；
- 删除服务端 SDK 执行 dispatch pump；
- Runner 不可用时 Run 保持 pending 或显式失败；
- 回退通过部署上一版本完成，不在新版本保留隐藏执行旁路。

## 23. 风险与控制方式

### 风险 1：Runtime 与 Store 耦合过深

控制：先迁移 `standard_direct`，定义小型 `ExecutionEnvelope` 和 `EventSink`，不一次搬迁完整 DAG。

### 风险 2：断线导致事件丢失

控制：Runner 先写本地 spool，云端确认后删除；使用稳定 `client_event_id` 去重。

### 风险 3：Lease 过期后重复副作用

控制：读操作可显式重试；外部写操作过期后进入人工确认，不自动重放。

### 风险 4：Runner 版本不一致

控制：Claim 时检查 protocol version、runner version 和 capability digest；不满足时保持 pending 并返回可操作诊断。

### 风险 5：本地敏感数据上传

控制：Envelope 不要求上传本地目录；Artifact 明确选择；Event payload 有大小和字段限制；凭据只存本地。

### 风险 6：Windows 打包失败

控制：Runner 不导入服务器 `SQLiteStore` 和 `fcntl`；在 Runner MVP 稳定后再增加 Windows 构建。

## 24. 完成定义

本方案的基础改造完成，需要同时满足：

1. 云端可以创建 Runner 执行的 Run；
2. FastAPI 不执行该 Run；
3. 本地 Runner 可以安全注册和撤销；
4. Runner 可以 Claim、Renew、上报 Event 和完成；
5. Lease 和 Event 具有幂等性；
6. stale Runner 不能覆盖新 Generation；
7. Web SSE 可以实时显示本地执行进度；
8. cancel 最终能够到达 Runner；
9. Artifact 可以经过 Hash 校验汇聚到云端；
10. Runner 无数据库凭据；
11. Provider Key 和本地文件默认不上传；
12. 本地开发可以同时启动 Server、Runner 和 Vite；
13. 当前 Task、Memory、Inbox 和权限行为没有被执行拆分破坏；
14. 聚焦测试、现有后端测试和前端构建通过；
15. README 提供云端部署、Runner 安装和本地开发三条清晰路径。

## 25. 推荐的第一个开发任务

第一项实现已经完成：

```text
RunnerDeviceV1
+ Runner Enrollment
+ Runner Credential
+ Heartbeat
+ Runner CLI 骨架
+ Web 确认与设备撤销入口
```

下一项实现：

```text
standard_direct remote execution
```

这样可以在不影响当前 Agent 执行路径的情况下，先验证终端身份、网络连接和云端 Runner 管理边界。完成第二项后，才开始把 Tool、Artifact、Approval 和 DAG 逐步迁移到本地 Runner。

## 26. 工期估算

### 26.1 估算前提

以下估算基于：

- 一名熟悉当前代码库的全职开发者；
- 每周约 5 个有效开发日；
- 当前功能分支先合并到稳定基线；
- 使用 fake Provider 和精简测试策略；
- 不同时迁移 PostgreSQL；
- 不包含公网 SaaS 加固、桌面壳和复杂自动更新；
- 第一版只要求 macOS/Linux 开发运行，Windows 独立包后补；
- 产品功能开发如果与 Runtime/Store 改造并行，需要单独协调冲突。

### 26.2 分项估算

| 工作项 | 单人开发时间 | 主要内容 |
| --- | ---: | --- |
| 执行边界和协议落地 | 3～5 个工作日 | Runner、Envelope、Lease、Event、Completion 合同 |
| Slice 1：身份、注册、CLI、Heartbeat | 5～8 个工作日 | 设备码、Credential、Runner 管理接口、CLI 骨架 |
| Slice 2：`standard_direct` 闭环 | 8～12 个工作日 | Claim、本地 SDK 执行、Event、Completion、SSE |
| Slice 3：可靠性与取消 | 5～8 个工作日 | Renew、过期、spool、幂等、cancel、retry |
| Slice 4：Tool、文件、Artifact、Approval | 10～15 个工作日 | 本地能力、权限、上传、暂停恢复 |
| Slice 5：Plan 和多节点 DAG | 8～12 个工作日 | 本地规划、云端持久化、审批、节点执行 |
| Slice 6：DeepSearch 和完整 Runtime 迁移 | 8～12 个工作日 | Evidence、finalization、recovery、删除服务端执行路径 |
| Runner 安装包与发布流水线 | 5～8 个工作日 | pipx、macOS/Linux 独立包、基础安装脚本 |

### 26.3 里程碑时间

#### 里程碑 A：技术 MVP

范围：协议、Runner 注册、Heartbeat 和 `standard_direct` 完整闭环。

```text
预计：16～25 个工作日
单人日历时间：约 3～5 周
```

完成后可以证明“本地执行、云端汇总”架构成立，但还不适合替代全部现有 Runtime。

#### 里程碑 B：可日常试用 Alpha

范围：里程碑 A，加上 Lease 可靠性、断线重传、cancel、Tool、文件、Artifact 和 Approval。

```text
预计累计：31～48 个工作日
单人日历时间：约 6～10 周
```

这是推荐的第一版开源试用目标。它能够覆盖真实本地工具使用，不需要先完成 DeepSearch。

#### 里程碑 C：当前 Runtime 基本完整迁移

范围：里程碑 B，加上 Plan、多节点 DAG、DeepSearch 和服务端执行路径删除。

```text
预计累计：47～72 个工作日
单人日历时间：约 10～15 周
```

#### 里程碑 D：可发布的跨平台 Runner

范围：里程碑 C，加上 pipx、macOS/Linux 独立包、安装脚本和基础发布流水线。

```text
预计累计：52～80 个工作日
单人日历时间：约 11～16 周
```

Windows、代码签名和系统包管理器可在此后独立增加。

### 26.4 云端生产化的额外时间

以下工作不计入前述 Runner 迁移时间：

| 可选工作 | 额外时间 |
| --- | ---: |
| SQLite 迁移 PostgreSQL | 10～20 个工作日 |
| Artifact 迁移对象存储 | 5～8 个工作日 |
| Windows Runner 安装包 | 5～10 个工作日 |
| macOS/Windows 正式签名与发布配置 | 3～8 个工作日，不含证书等待时间 |
| 公网部署安全加固 | 10～20 个工作日 |

不建议把这些项目全部放入第一个 Runner MVP。

### 26.5 多人开发估算

如果由两名后端开发者加一名前端或发布支持人员协作：

```text
技术 MVP：约 2～3 周
可日常试用 Alpha：约 4～6 周
完整 Runtime + 基础发行：约 7～10 周
```

工期不能简单按人数等比例缩短，因为 `agent_runtime/service.py`、`store.py`、Run 状态和协议切分存在顺序依赖。最适合并行的工作是：

- 一人负责 Control Plane、Lease 和 Store；
- 一人负责 Runner、执行引擎和本地 spool；
- 一人负责 CLI、安装包、Web Runner 状态和文档。

### 26.6 推荐排期

如果目标是尽快得到可验证成果，建议承诺两个节点：

```text
第 4 周：完成技术 MVP
第 8～10 周：完成可日常试用 Alpha
```

之后再根据真实使用情况决定是否继续投入约 4～6 周迁移完整 DAG、DeepSearch 和跨平台发行。

当前最大不确定性是 `agentmesh/agent_runtime/service.py` 对 `SQLiteStore` 的直接依赖程度。建议在第一周完成一个小型 `standard_direct` 执行边界 Spike；如果该 Spike 证明无需大范围重写，后续估算可以收敛到区间下限。
