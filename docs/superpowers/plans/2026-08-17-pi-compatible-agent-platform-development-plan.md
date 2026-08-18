# AgentMesh · OpenAI Agents SDK Platform Development Plan

> **Status:** Implemented and independently reviewed as merge-ready. 604 backend tests, 66 frontend tests, all 46 Playwright tests, Ruff, OpenAPI generation and production build pass. The authenticated pages are route-split; the main JS entry is 286.21 KB (92.16 KB gzip) and the 500,000-byte chunk budget passes without Vite warnings. Real OpenAI-compatible and SDK tool-call smoke pass for GPT-5.2, GPT-5.4, GPT-5.5 and Kimi K2.6 JoyBuilder.
> **Date:** 2026-08-17
> **Target:** Evolve AgentMesh into an OpenAI Agents SDK-based AI platform with standards-compliant Skills and AgentMesh enterprise governance.
> **Decisions confirmed:** OpenAI Agents SDK for Python is the sole LLM/Agent execution framework; Agent Skills standard first; enterprise tools first; trusted-intranet single Workspace first.

## Requirement clarification (2026-08-17)

The product requirement is broader than “implement a Pi-like loop in Python.” LLM-facing concerns—question answering, Skill execution, Agent loops, sessions, memory injection, RAG context, hooks/guardrails, streaming, and tool calls—must run on a mature AI framework rather than a newly built AgentMesh loop. FastAPI, Python, JavaScript, and TypeScript remain valid for the product control plane, connectors, workflow coordination, UI, and data services.

OpenAI Agents SDK for Python is the selected framework. AgentMesh will integrate that one framework deeply; Pi and Claude remain architectural references, not additional runtimes. AgentMesh must not reproduce the SDK Runner, tool-call loop, guardrails, HITL state, sessions, streaming, MCP or tracing.

## 1. Goal

Build an OpenAI Agents SDK execution layer for AgentMesh. AgentMesh discovers and governs standard Skills, converts approved enterprise capabilities into SDK tools/MCP servers, and delegates LLM/Agent execution to the SDK Runner. AgentMesh does not implement its own model/tool loop.

AgentMesh continues to own identity, Skill catalog, Tool Grant, approval, memory, RAG, Source, AuditEvent, Artifact, and product APIs. OpenAI Agents SDK owns Agent/Runner semantics, model invocation, tool-call orchestration, streaming, SDK sessions, guardrails, handoffs and tracing. Non-OpenAI models remain possible through the SDK's documented model-provider adapters, subject to a tool-calling compatibility smoke against the current internal gateway.

## 2. Success Criteria

The platform is complete for the selected internal deployment boundary when all of the following are true:

1. AgentMesh discovers standard `SKILL.md` packages from built-in, Workspace-managed, and trusted project scopes.
2. The Wiki baseline can be scanned without a crash: 86 `SKILL.md` files are classified, 80 standard-frontmatter files are parsed, and the current 78 unique names are reconciled with deterministic duplicate diagnostics.
3. Skill metadata is progressively disclosed: catalog at session start, full instructions on activation, referenced resources only on demand.
4. Existing `$memory.*`, `$brief.create`, `$research.request`, `$data.query`, `$risk.review`, and related commands keep working without behavior regressions.
5. At least three standard prompt Skills execute end-to-end without adding new `Intent` branches: `generate-research-plan`, `issue-prioritization`, and `jobs-to-be-done`.
6. A model can perform a bounded multi-turn tool loop using granted read-only enterprise tools, with every model turn, tool call, result, provider, source, and policy decision audited.
7. High-risk or mutating calls cannot run before an explicit Inbox approval; denied or expired approvals cannot be replayed.
8. Runs support streaming, cancellation, browser reconnect, durable resume after approval, idempotent user retries and context compaction. A process crash during an in-flight model/tool call is marked interrupted and retried explicitly; the plan does not claim exactly-once recovery for arbitrary in-flight work.
9. Session-scoped context and long-term memory remain separate; permissions are applied before retrieval/ranking.
10. RAG returns source-bound evidence and meets the existing ADR trigger of at least 75% citation coverage when relevant sources exist.
11. Third-party Skill code never executes inside the FastAPI process. Scripts require a policy-controlled worker and an approved execution manifest.
12. The legacy chat path remains available behind a rollback flag until Runtime v2 passes production smoke and one internal pilot cycle.

## 3. Scope

### Building

- Agent Skills specification compatibility.
- `.agents/skills`, `.pi/skills`, configured `.claude/skills`, and configured `.codex/skills` discovery adapters.
- Skill diagnostics, precedence, trust, enable/disable, explicit `$` activation, and controlled model activation.
- OpenAI Agents SDK Runner integration with streaming and usage accounting.
- Tool grants, SDK guardrails, approval interruptions, serialized RunState and resume.
- Append-only AgentMesh run projections, SDK sessions, context compaction and replayable UI events.
- Harness behavior implemented through SDK guardrails, hooks and a local tracing processor.
- Skill package import, version, provenance, hash, rollout, and rollback.
- Existing memory integration and a permission-aware RAG service.
- Real Skill catalog and run timeline in the React frontend.
- Evaluation fixtures, replay tests, provider smoke, metrics, and audit views.

### Not building in this plan

- Exact Pi TypeScript Extension API compatibility.
- Arbitrary npm packages or extension code running in the FastAPI process.
- Shell, Git, local filesystem mutation, browser automation, or coding-agent tools in the first usable release.
- Public SaaS, billing, quotas, cross-Workspace tenancy, or internet-facing hardening.
- A terminal UI; AgentMesh remains FastAPI + React.
- Automatic sharing of private outputs or automatic acceptance into team memory.
- A new vector database before the existing FTS5/optional-vector evaluation shows it is necessary.
- Exact Claude Code hook or Codex command compatibility; their Skill directories are input adapters only.

## 4. Chosen AI Framework

Use **OpenAI Agents SDK for Python 0.21.1** as the sole LLM/Agent execution kernel. It runs in the existing FastAPI environment and supplies the mature Runner, Agent, FunctionTool, guardrails, sessions, durable RunState approvals, streaming, MCP and tracing primitives that AgentMesh must not rebuild.

AgentMesh adds only the platform capabilities outside the SDK's responsibility:

1. Agent Skills standard discovery, validation, progressive disclosure and package governance.
2. Mapping existing ToolDefinition, Tool Grant, RiskPolicy and Inbox decisions into SDK tools, guardrails and approval interruptions.
3. Project/user/team Memory and permission-aware RAG as RunContext services and FunctionTools.
4. Projection of SDK run/trace events into AgentMesh Task, ChatMessage, ChatTurnTrace, AgentRunEvent, AuditEvent and React UI.
5. Model-provider configuration for the current internal OpenAI-compatible gateway.

Generic Skills do not create new `Intent` values or PersonalAgent handler branches. Pi SDK and Claude Agent SDK are references only and are not runtime dependencies in this plan.

## 5. Transferable Mechanisms

### From Pi

- Minimal Agent core with capabilities moved into Skills, tools, and hooks.
- Agent Skills standard and three-tier progressive disclosure.
- Explicit user activation plus model activation.
- Dynamic tool registry and active-tool selection.
- Event lifecycle around run, model, tool, context, and compaction.
- Append-only, branchable session entries.
- Context compaction that preserves recent turns and durable instructions.
- Provider/model capability metadata and graceful provider fallback.
- Package provenance, project trust, and deterministic resource precedence.
- Tool output truncation with full-output artifact references.

### From Agent Skills specification

- Standard frontmatter and directory structure.
- Project/user/organization scope discovery.
- Lenient parsing with diagnostics rather than global failure.
- Catalog-only startup context and on-demand instruction/resource loading.
- Skill content preservation across compaction.
- Deterministic duplicate handling.

### From LangGraph persistence

- Keep thread/run checkpoints separate from long-term cross-thread storage.
- Treat interruption/resume state as runtime state, not as long-term memory.
- Apply retention to checkpoints/events independently from memory retention.

### From OpenAI Agents SDK

- Explicit run state and bounded Runner semantics.
- Tool/guardrail/human-in-the-loop lifecycle.
- Streaming events, tracing, sessions, and MCP as independent surfaces.

The OpenAI Agents SDK is a production dependency and owns the model/Agent loop. AgentMesh owns Skill governance, enterprise tool authorization, memory/RAG, audit and product state. Pi and LangGraph remain design references rather than additional runtime dependencies.

### Requirement-to-SDK mapping

| Required capability | OpenAI Agents SDK primitive | AgentMesh integration responsibility |
|---|---|---|
| LLM question answering | `Agent`, `Runner.run`, model/provider configuration | Build Agent instructions from platform policy, selected Skill and project context |
| Skill application | Agent instructions, dynamic tools, structured output | Discover/validate Agent Skills, activate progressively, bind tools and version provenance |
| Agent loop | `Runner` bounded by `max_turns` | Start/cancel runs and project SDK events into product state |
| Multi-agent | Handoffs and `Agent.as_tool()` | Bind approved specialist Agents and retain collaboration/audit identity |
| Short-term memory | SDK `Session` protocol | Implement `AgentMeshSession` over ChatThread/ChatMessage storage |
| Long-term memory | RunContext + FunctionTools | Expose scoped UserMemoryItem/MemoryItem retrieval and governed write candidates |
| RAG | FunctionTools, dynamic instructions, session/model input callbacks | Permission filtering, FTS/vector retrieval, context packing and citations |
| Harness/guardrails | Input/output/tool guardrails, RunHooks/AgentHooks | Map RiskPolicy, Tool Grants, Source rules and output contracts |
| Human approval | `needs_approval`, interruptions, serializable `RunState` | Map to InboxItem, store decisions and resume original run |
| MCP/tools | SDK FunctionTool and MCP server integrations | Wrap O2/HTTP/doc/data services and filter by grants |
| Streaming | `Runner.run_streamed()` and StreamEvent | Persist ordered events and expose resumable SSE |
| Observability | SDK tracing and custom TracingProcessor | Disable external sensitive export and write local run/audit metrics |

## 6. Runtime Architecture

```text
React Workspace / Digital Human / Inbox
                 │
                 ▼
FastAPI Agent API ─────── Compatibility adapter for /api/chat/messages
                 │
                 ▼
             RunService
                 │
       ┌─────────┼─────────┐
       ▼         ▼         ▼
Mature SDK    Context    Event Stream
Runner        Builder         │
   │            │             ▼
   │            ├── Skill Catalog / Activated Skills
   │            ├── Workspace Instructions
   │            ├── SDK Session / AgentMesh Run Checkpoint
   │            └── Memory / RAG Evidence
   │
   ├── SDK-native Model / Agent / Tool Loop
   ├── AgentMesh Tool Gateway ── MCP / O2 / HTTP / Documents / Memory
   └── AgentMesh Policy Bridge ── Grants / Risk / Approval / Audit
                 │
                 ▼
SQLite: AgentRun + AgentRunEvent + Skill records + existing domain records
Artifacts: bounded generated files and full truncated tool output
```

### Prompt precedence

The Context Builder must preserve this order, from strongest to weakest:

1. Platform safety and immutable runtime rules.
2. Workspace policy and Agent profile.
3. Active tool descriptions and tool-specific constraints.
4. Available Skill catalog.
5. Explicitly activated Skill instructions.
6. Retrieved memory/RAG evidence, clearly marked as untrusted data.
7. Session summary and recent turns.
8. Current user input.

A Skill cannot override platform safety, expand its own grants, or authorize its own scripts.

### Skill activation policy

To preserve AgentMesh's explicit `$` behavior:

- Imported Skills default to `explicit_only`.
- `$skill-name` or an approved alias activates a Skill before the first model call.
- Admin-approved read-only Skills may use `model_allowed`; the model invokes `activate_skill` from the disclosed catalog.
- Model activation during natural chat does not change the turn into a team workflow, does not create team memory, and does not grant new tools.
- `disable-model-invocation: true` always forces explicit activation.
- `allowed-tools` is treated as a requested subset and is intersected with Tool Grants and policy; it is never authorization.

### Agent run state machine

```text
CREATED
  → PREFLIGHT
  → MODEL_RUNNING
  → TOOL_PREFLIGHT
      → TOOL_RUNNING → MODEL_RUNNING
      → WAITING_APPROVAL → TOOL_RUNNING → MODEL_RUNNING
  → COMPLETED

Any active state may become FAILED or CANCELLED.
A process restart reconstructs the last durable state from AgentRunEvent.
```

### Bounded defaults

Runtime defaults are held in one `RuntimeSettings` model rather than exposed as many independent environment variables:

| Limit | Default |
|---|---:|
| Model turns per run | 8 |
| Tool calls per run | 24 |
| Whole-run timeout | 300 seconds |
| Individual tool timeout | 45 seconds |
| Concurrent read-only tools | 4 |
| Tool output sent to model | 50 KB or 2,000 lines |
| Skill scan depth | 6 directories |
| Skill scan traversal cap | 2,000 directories |
| Recommended activated Skill body | 5,000 tokens |
| Recent context kept during compaction | 20,000 tokens |
| Output reserve before compaction | 16,384 tokens |

Only these deployment inputs are public in the first release:

- `AGENTMESH_AGENT_RUNTIME=legacy|v2`
- `AGENTMESH_SKILL_PATHS=<comma-separated managed roots>`
- `AGENTMESH_MCP_CONFIG=<path to admin-managed MCP configuration>`

## 7. Durable Entity Delta

The plan adds six durable entity types and extends one existing type.

| Entity | Need | Ownership and rollback |
|---|---|---|
| `SkillDefinition` | Parsed standard Skill, provenance, body hash, trust and activation metadata | Skill runtime owns it; deleting imported records does not delete source files |
| `SkillBinding` | Enable/disable and alias per Agent/Workspace | Agent administration owns it; removing a binding disables access immediately |
| `SkillPackage` | Source, version, hash and contained resources | Harness/package service owns it; rollback selects previous immutable version |
| `AgentRun` | One durable execution of a user request | RunService owns it; legacy ChatResponse remains a projection |
| `AgentRunEvent` | Ordered model/tool/policy/usage lifecycle | Append-only; retention can prune completed old events after projection/export |
| `Artifact` | HTML/JSON/file result or full truncated tool output | Artifact service owns it; references are immutable and access-scoped |
| Extend `ToolDefinition` | Add JSON schemas, side-effect class, timeout and capability metadata | Existing grants remain valid; new fields have safe defaults |

`ChatThread` remains the product conversation identity. `ChatMessage` remains the user-visible projection. `ChatTurnReceipt` remains the idempotency claim. `LearnedSkill` remains the experience-extraction record and is materialized as an approved `SkillDefinition` only in Phase 5; it is not reused as the installed Skill schema.

## 8. Public API Plan

### Skill catalog

- `GET /api/skills` — visible, enabled Skill metadata and diagnostics summary.
- `GET /api/skills/{skill_id}` — metadata, provenance, compatibility, required tools and current binding; body visible only to authorized administrators.
- `POST /api/skills/reload` — admin-only rescan of configured roots.
- `PATCH /api/agents/{agent_id}/skills` — enable, disable and set aliases.
- Keep `GET /api/chat/skills` as a compatibility projection until the React client migrates.

### Agent runs

- `POST /api/agent/runs` — claim a client turn and return `run_id` plus `thread_id`.
- `GET /api/agent/runs/{run_id}` — durable run status and summary.
- `GET /api/agent/runs/{run_id}/events` — SSE with resumable sequence cursor.
- `POST /api/agent/runs/{run_id}/cancel` — idempotent cancellation.
- `POST /api/agent/runs/{run_id}/resume` — internal/approval path; user-facing approval continues through Inbox actions.
- Keep `POST /api/chat/messages` as a start-and-wait compatibility adapter while Runtime v2 is behind the rollout flag.

### Artifacts

- `GET /api/artifacts/{artifact_id}` — permission-checked metadata or content response.
- Artifacts never expose arbitrary filesystem paths.

## 9. Phased Delivery

- [x] Phase 1: route general chat and three pilot standard Skills through OpenAI Agents SDK.
- [x] Phase 2: expose governed enterprise FunctionTools/MCP and map SDK interruptions to Inbox approval.
- [x] Phase 3: adopt SDK Sessions, streamed runs, cancellation, RunState resume and context compaction.
- [x] Phase 4: implement harness behavior with SDK guardrails/hooks/tracing and add trusted Skill packages.
- [x] Phase 5: connect existing Memory and permission-aware RAG through SDK RunContext, sessions and tools.
- [x] Phase 6: complete metrics, retention, provider smoke, canary rollout and the ten-Skill internal pilot.

Every phase is independently deployable and leaves AgentMesh usable if later phases stop.

### Phase 1 — OpenAI Agents SDK Foundation and Standard Skill Catalog

**Calendar:** 2 weeks.
**Usable outcome:** General chat and three pilot Skills execute through OpenAI Agents SDK `Agent` + `Runner`, while all current `$` commands remain available through the legacy compatibility path.

#### Work

1. Add the `openai-agents` dependency and an `agentmesh/agent_runtime/` integration layer; do not implement a custom model/tool loop.
2. Build `AgentMeshModelFactory` around the current model registry. For the internal OpenAI-compatible gateway, use the SDK's `AsyncOpenAI` + `OpenAIChatCompletionsModel` path first; use Responses only after a provider smoke proves support.
3. Add a compatibility smoke covering text, streaming, native function-tool calls, malformed tool arguments, usage reporting and cancellation against the configured internal model. Enable SDK streamed-tool-call buffering when the gateway's deltas require it.
4. Disable the SDK's default outbound OpenAI tracing and register an AgentMesh-local trace processor with sensitive payload capture disabled.
5. Add a serializable `AgentMeshRunContext` containing only user/workspace/project/thread/run IDs and policy snapshot IDs; do not place credentials or service clients in context because SDK `RunState` may persist it.
6. Add `agentmesh/skill_runtime/` with standard contracts, parser, discovery, diagnostics, registry, activation and host-field adapters.
7. Implement deterministic Skill scope precedence: trusted project > Workspace-managed > built-in. Same-scope collisions keep the first canonical source and emit a diagnostic.
8. Parse standard fields and preserve unknown host fields in metadata. Missing description or completely invalid YAML skips only that Skill.
9. Add explicit `$name`/alias activation and generate SDK Agent instructions from platform policy + selected Skill body. Phase 1 remains explicit-only.
10. Add `SkillDefinition` and `SkillBinding` persistence using additive records; no existing collection is migrated.
11. Package `generate-research-plan`, `issue-prioritization`, and `jobs-to-be-done` as built-in pilot Skills with provenance back to the Wiki source.
12. Expose the real catalog through `/api/skills` and the compatibility `/api/chat/skills` response.
13. Route natural general chat and the three pilot Skills through SDK `Runner.run`; the Runtime v2 path bypasses `_classify_intent` and activates a Skill only for an explicit `$` command. Leave existing fixed tool workflows on the legacy PersonalAgent until Phase 2.
14. Replace the mock configured-Skill cards in Digital Human with real catalog/binding data.
15. Project SDK final output, usage and Skill identity into ChatMessage, ChatTurnTrace and AuditEvent.
16. Add ADR 0004 documenting OpenAI Agents SDK as the sole execution framework and superseding only the old “no public Agent builder” constraint for this internal platform.

#### Primary files

- Create `agentmesh/agent_runtime/__init__.py`, `models.py`, `model_factory.py`, `agent_factory.py`, `run_context.py`, `trace_processor.py`, and `service.py`.
- Create `agentmesh/skill_runtime/` modules and `agentmesh/builtin_skills/` pilot packages.
- Create `agentmesh/routes/skills.py`.
- Modify `pyproject.toml`, `agentmesh/models.py`, `agentmesh/store.py`, `agentmesh/chat_skills.py`, `agentmesh/agents.py`, `agentmesh/routes/chat.py`, `agentmesh/app.py`, `agentmesh/llm.py`, and `agentmesh/model_registry.py`.
- Modify `agentmesh-demo/src/features/workspace/`, `agentmesh-demo/src/components/workspace/Composer.tsx`, and `agentmesh-demo/src/components/digital-human/SkillsSection.tsx`.
- Create SDK model smoke, Skill parser/registry/activation, trace-redaction and frontend catalog tests.
- Create `docs/adr/0004-openai-agents-sdk-runtime.md`.

#### Reuse

- `agentmesh.llm.model_config_from_env()` and model registry values for endpoint/model discovery.
- `ChatTurnReceipt` for idempotent request claims.
- Existing ChatThread/ChatMessage/ChatTurnTrace/AuditEvent projections.
- Existing `$` Composer autocomplete and `/api/chat/skills` query.

#### Acceptance

- SDK text and streaming smoke passes against a deterministic fake model; configured internal-provider smoke reports each capability separately without printing credentials.
- Default SDK tracing cannot send prompt, model or tool data to OpenAI; the local trace processor records only approved metadata.
- Wiki scan report reconciles the current baseline without crashing.
- Valid names, malformed YAML fallback, missing description, duplicate precedence, depth cap, symlink escape and untrusted project cases are tested.
- Three pilot Skills execute through SDK `Runner` without a new `Intent` or handler branch per Skill.
- Natural chat remains private and does not write long-term/team memory.
- Existing fixed Skill workflows and workspace E2E tests pass unchanged through the legacy path.

#### Rollback

Set `AGENTMESH_AGENT_RUNTIME=legacy`. New Skill records remain inert and the SDK path stops receiving requests.

---

### Phase 2 — SDK Tools, Enterprise Gateway and Human Approval

**Calendar:** 2.5 weeks.
**Usable outcome:** OpenAI Agents SDK runs the complete model/tool loop. Activated Skills can use granted Memory, Document, O2, HTTP Data, Research and MCP tools, and sensitive calls pause through the SDK's durable HITL flow.

#### Work

1. Extend `AgentMeshRunContext` with immutable authorization and provenance IDs needed by SDK function tools.
2. Add `agentmesh/tool_runtime/` as a gateway/factory layer, not an Agent loop. Convert enabled `ToolDefinition` records into SDK `FunctionTool` objects with Pydantic-generated input schemas.
3. Reuse existing Memory, Document, O2 Research, Data Query and Risk Review services inside tool handlers.
4. Use SDK `is_enabled` callbacks to hide tools that are not granted to the current Agent/user/project before the model sees them.
5. Use SDK tool input/output guardrails to validate schema, prevent secrets, assess external content and redact unsafe output.
6. Use SDK `needs_approval` for write/external/high-risk calls. Convert `RunResult.interruptions` into existing InboxItems, serialize `RunState`, and resume the original `Runner` after approve/reject.
7. Store only pure-data IDs in `RunState` context. Reconstruct repository/services from the AgentMesh process when loading the state.
8. Use SDK MCP support for admin-configured stdio and Streamable HTTP servers. Apply static/dynamic tool filters and SDK approval policies; MCP remains disabled without configuration.
9. Extend `ToolDefinition` with input/output JSON Schema, side-effect class (`read`, `write`, `external`), timeout and SDK capability metadata.
10. Configure SDK `ToolExecutionConfig(max_function_tool_concurrency=4, pre_approval_tool_input_guardrails=True)` and `max_turns=8`.
11. Use SDK function-tool timeouts at 45 seconds and an outer 300-second run budget. Tool errors return stable redacted results or fail the run according to ToolDefinition policy.
12. Truncate model-visible tool output to 50 KB/2,000 lines and store full output as an access-scoped Artifact.
13. Add `AgentRun` and ordered `AgentRunEvent` persistence. Project SDK stream/run items and trace spans into additive `agent_runs`, `agent_run_events`, and `artifacts` SQLite tables, then into existing Task, ChatMessage, ChatTurnTrace and AuditEvent views.
14. Preserve current model fallback only for replay-safe failures before any tool side effect. After a tool runs, rely on SDK retry safety and never restart the full run automatically on another model.
15. Do not silently use mock evidence when a production tool provider fails.

#### Primary files

- Extend `agentmesh/agent_runtime/` with SDK run projection, state serialization and approval resume.
- Create `agentmesh/tool_runtime/registry.py`, `factory.py`, `guardrails.py`, `gateway.py`, `artifacts.py`, and adapter modules.
- Create `agentmesh/routes/agent_runs.py`; extend Inbox approval completion.
- Modify `agentmesh/tools.py`, `agentmesh/risk.py`, `agentmesh/models.py`, `agentmesh/store.py`, `agentmesh/synthesis.py`, `agentmesh/routes/inbox.py`, and `agentmesh/app.py`.
- Modify Workspace detail/timeline components to render SDK agent, tool, approval and handoff items.
- Add deterministic SDK fake-model, function-tool and local reference MCP fixtures.

#### Reuse

- `list_agent_tools()` and AgentToolGrant as the authoritative tool allowlist.
- Existing O2, data source, acquisition, document and memory services as tool implementations.
- RiskPolicyRule/PermissionPolicyRule and InboxItem as the policy/HITL control plane.
- SDK `FunctionTool`, guardrails, `needs_approval`, `RunState`, MCP server classes, Runner streaming and tracing.

#### Acceptance

- Text-only, single-tool, chained-tool, parallel-tool, malformed arguments, tool timeout, tool error, max-turn and cancellation paths run through SDK Runner tests.
- A Skill cannot expose or call an ungranted tool or expand its own grant.
- Tool input guardrails run before approval and again immediately before execution.
- A write/external side effect creates one idempotent SDK interruption/Inbox item and executes only after the matching RunState approval.
- Serialized paused state survives process reconstruction without persisting secrets or service objects.
- A failed MCP/O2/HTTP provider degrades visibly without inserting untrusted evidence into synthesis.
- Every completed run has complete SDK Agent, model, usage, tool, source, approval and audit provenance.

#### Rollback

The compatibility adapter routes all requests to legacy PersonalAgent. Paused SDK runs are rejected with a stable “runtime disabled” resolution; additive run records remain auditable.

---

### Phase 3 — SDK Sessions, Streaming and Durable Resume

**Calendar:** 2 weeks.
**Usable outcome:** AgentMesh uses SDK sessions and streamed runs for multi-turn context; browser reconnect, cancellation and approval resume work without recreating Agent loop behavior.

#### Work

1. Implement `AgentMeshSession` against the OpenAI Agents SDK `Session` protocol, backed by existing ChatThread/ChatMessage and SDK-normalized run items. Do not create a second standalone SDK SQLite database.
2. Use `Runner.run_streamed()` and project raw response, run-item and agent-update events into resumable AgentRunEvent SSE.
3. Drain SDK streams to completion even after the final visible token so session persistence, approvals and post-processing finish correctly.
4. Map UI cancellation to SDK `RunResultStreaming.cancel()` and propagate cancellation to AgentMesh tool handlers and MCP/O2/HTTP calls.
5. Persist SDK `RunState.to_json()` when interruptions occur; reload with the same top-level Agent definition/version and the same AgentMeshSession ID.
6. Store the Agent/Skill/tool-definition version marker beside paused state and reject incompatible resume after package removal or an unsafe schema change.
7. Implement `RunConfig.session_input_callback` to merge SDK session history with current input and `call_model_input_filter` for final redaction/context limits.
8. Protect platform policy, active Skill instructions, unresolved approval context and the recent 20k-token tail during context management.
9. For the initial Chat Completions-compatible gateway, generate compaction summaries through a dedicated SDK summarizer Agent and transactionally replace old AgentMeshSession items with summary + retained tail. If a later provider passes Responses capability smoke, permit `OpenAIResponsesCompactionSession` as an optional adapter, not as the source of truth.
10. Add Artifact references for full output and generated HTML/JSON instead of embedding large payloads in session context.
11. Migrate Workspace message sending to `POST /api/agent/runs` + SSE while retaining the synchronous `/api/chat/messages` compatibility endpoint.

#### Primary files

- Create `agentmesh/agent_runtime/session.py`, `stream_projection.py`, `compaction.py`, `recovery.py`, and `versioning.py`.
- Extend `agentmesh/routes/agent_runs.py` and Inbox approval completion.
- Modify `agentmesh/routes/chat.py`, `agentmesh/routes/inbox.py`, `agentmesh/models.py`, `agentmesh/store.py`.
- Modify Workspace query/mutation hooks, Composer state, message timeline and reconnect reducer.
- Add SDK Session protocol, RunState serialization, SSE reconnect, cancellation, approval-resume and compaction tests.

#### Reuse

- OpenAI Agents SDK Session protocol, `Runner.run_streamed`, StreamEvent, `RunState`, `session_input_callback` and `call_model_input_filter`.
- Existing ChatThread/ChatMessage as product history and ChatTurnReceipt as turn idempotency.
- Existing Inbox decisions as the human approval UI.

#### Acceptance

- SDK session history is loaded once and new run items are persisted once; no duplicated context appears on retries.
- SSE reconnect with the last event sequence emits no duplicates and misses no events.
- Cancelled runs stop SDK streaming and new tool work and finish as `CANCELLED`.
- Restart while waiting approval reloads RunState and resumes the same SDK run after a decision.
- Changed Agent/Skill/tool versions fail resume safely with an actionable message.
- Context overflow compacts once and retries through SDK Runner without an infinite loop.
- Active Skill instructions survive repeated compactions without duplicate injection.
- Legacy API responses remain schema-compatible.

#### Rollback

Switch the React client back to `/api/chat/messages` and select the legacy runtime. Completed SDK session/run records remain readable for audit; no new SDK runs start.

---

### Phase 4 — SDK Harness, Skill Trust and Package Lifecycle

**Calendar:** 2.5 weeks.
**Usable outcome:** AgentMesh maps its governance into SDK guardrails/hooks/tracing, and administrators can safely import, validate, enable, version and roll back Skill packages.

#### Work

1. Implement AgentMesh blocking input guardrails with `run_in_parallel=False` for authentication, prompt-injection quarantine and request policy; the expensive Agent must not start when these trip.
2. Implement output guardrails for source/citation and output-schema requirements.
3. Implement FunctionTool input/output guardrails for argument policy, secret detection, source safety and output redaction.
4. Implement SDK RunHooks/AgentHooks adapters that project Agent, model, handoff and tool lifecycle into AgentRunEvent/AuditEvent. Do not create a second competing hook lifecycle.
5. Replace the SDK default trace exporter with an AgentMesh `TracingProcessor`; set sensitive data capture off and map trace/group IDs to AgentRun/ChatThread.
6. Define failure semantics around SDK primitives: policy guardrails fail closed; local telemetry projection failures are recorded and do not broaden permissions; SDK model/tool exceptions retain stable redacted codes.
7. Add `SkillPackage` with immutable version, content hash, source URI, license, compatibility, resources and validation report.
8. Support local directory and uploaded ZIP import first. Add pinned Git commit import only after checksum and quarantine tests pass. Do not auto-install package dependencies.
9. Quarantine every imported package until an administrator reviews diagnostics, requested tools, scripts and network requirements.
10. Add package rollback by selecting a prior immutable SkillDefinition version; active/paused SDK runs retain the Agent/Skill/tool version with which they started.
11. Add script manifests. Imported script execution remains disabled until routed to a restricted worker with no ambient credentials; SDK hosted shell/code interpreter are outside the internal first-release boundary.
12. Add harness evaluators for output schema, citations, required sections, forbidden actions and per-Skill golden fixtures.
13. Add model-driven progressive activation only for administrator-approved `model_allowed` Skills by exposing an `activate_skill` SDK FunctionTool constrained to the visible catalog. Explicit-only Skills never appear in that tool's enum.
14. Add Skill administration UI: source, version, hash, diagnostics, bindings, tools, activation policy, risk, usage and rollback.

#### Primary files

- Create `agentmesh/agent_runtime/guardrails.py`, `hooks.py`, `tracing.py`, and `errors.py`.
- Create `agentmesh/harness/skill_packages.py`, `validation.py`, `evaluators.py`, and archive/import modules.
- Create/extend Skill administration routes.
- Modify `agentmesh/app.py`, `agentmesh/models.py`, `agentmesh/store.py`, `agentmesh/risk.py`, `agentmesh/permissions.py`.
- Add Skill administration pages/components and OpenAPI-generated types.
- Add guardrail timing, tool guardrail, trace redaction, package archive, traversal, collision, hash, quarantine and rollback tests.

#### Reuse

- OpenAI Agents SDK blocking input/output guardrails, tool guardrails, RunHooks/AgentHooks and tracing processor API.
- Existing RiskPolicyRule, PermissionPolicyRule, AuditEvent and InboxItem.
- Existing AgentMesh provider metadata and secret-redaction conventions.

#### Acceptance

- Blocking input guardrails prevent SDK model/tool execution when they trip.
- Tool guardrails cannot be bypassed by approval; they run again immediately before execution.
- No trace processor sends sensitive data to OpenAI or another external backend.
- ZIP traversal, symlink escape, oversized archive, duplicate name and malformed frontmatter cases cannot escape quarantine.
- No package import executes lifecycle scripts or arbitrary code.
- A package rollback changes only new runs; existing/paused run provenance remains reproducible or fails closed on incompatible resume.
- Admin-approved `model_allowed` Skills activate through the constrained SDK tool; explicit-only or disabled Skills cannot be activated by the model.
- The three pilot Skills and at least seven additional P0 Wiki Skills pass contract fixtures.

#### Rollback

Disable the package and restore the previous immutable version. SDK Runner and built-in Skills remain available.

---

### Phase 5 — Memory and RAG Integration

**Calendar:** 3 weeks.
**Usable outcome:** Skills can request scoped memory/RAG context through a standard retrieval interface, with permission-safe ranking and citations.

#### Work

1. Keep SDK session memory and AgentMesh long-term memory separate:
   - `AgentMeshSession`/SDK run items for thread-scoped conversation continuity;
   - UserMemoryItem/MemoryItem for cross-thread durable knowledge.
2. Add a `RetrievalService` interface over existing FTS5, optional vector retrieval, documents, personal/project/team memory and connector evidence.
3. Apply workspace/project/user/scope filters before lexical or vector ranking.
4. Use lexical FTS5 as the baseline. Enable current optional embeddings only behind the existing feature flag and RRF hybrid merge.
5. Add context packing with per-source token budgets, deduplication, freshness, provenance and citation labels.
6. Add Skill retrieval profiles: allowed scopes, source types, top-k, freshness and whether an empty result is fatal or advisory. Expose retrieval through SDK FunctionTools and, for preloaded context, through Agent instructions/session input callbacks.
7. Add memory write policies: none, private short-term, project candidate or team candidate. No Skill can directly create accepted team memory.
8. Connect approved LearnedSkill activation to materialization as a prompt-only SkillDefinition with explicit provenance and no scripts.
9. Add offline retrieval evaluation for recall, citation coverage, permission leakage, latency and correction rate.
10. Revisit external vector storage only when ADR 0001 triggers occur: over roughly 5,000 searchable chunks, semantic misses, citation coverage below 75%, or search latency complaints.

#### Primary files

- Create `agentmesh/retrieval/` and evaluation fixtures.
- Modify `agentmesh/store.py`, `agentmesh/embedding.py`, `agentmesh/vector_index.py`, `agentmesh/routes/memory.py`, `agentmesh/skill_extractor.py`, `agentmesh/models.py`.
- Extend SDK Agent factories, RunContext services, AgentMeshSession input callbacks and Skill retrieval policy.
- Add retrieval trace and citation UI to Workspace details.

#### Acceptance

- Private, project and accepted-team visibility tests pass before and after hybrid retrieval.
- No unauthorized candidate/private memory enters ranking, model context or citations.
- RRF results are deterministic for fixed inputs.
- Empty and conflicting evidence produce explicit insufficiency, not invented claims.
- Citation coverage is measured per Skill and reported in the evaluation output.
- LearnedSkill materialization requires activation and remains prompt-only.

#### Rollback

Disable hybrid retrieval and keep FTS5. SDK sessions and long-term AgentMesh memory remain independently usable.

---

### Phase 6 — Operational Readiness and Internal Skill Platform

**Calendar:** 2 weeks.
**Usable outcome:** One internal Workspace can operate and govern the platform with measurable quality, provider health and Skill lifecycle.

#### Work

1. Add dashboards for run success, latency, token/cost, tool error, approval wait, provider fallback, Skill activation, citation coverage and user correction.
2. Add retention:
   - retain audit and run summaries;
   - prune old high-volume streaming deltas after Artifact/export confirmation;
   - preserve approval, tool result, usage and final output events.
3. Add provider and MCP/O2 smoke commands that never print secrets.
4. Add per-Skill canary rollout: disabled, admin-only, selected Agents, all Workspace users.
5. Add replay-based regression evaluation using stored sanitized run fixtures.
6. Connect the LearnedSkill lifecycle to the same catalog while retaining separate source and review labels.
7. Run an internal pilot with the ten P0 Skills from `docs/wiki-skill-integration-candidates.md`.
8. Produce a go/no-go report covering quality, security, provider readiness, rollback and support ownership.

#### Acceptance

- A provider outage, MCP outage and embedding outage each produce honest degradation and actionable health status.
- Runtime v2 can be disabled without a data rollback.
- Ten P0 Skills have owner, version, contract fixture, permissions and quality metrics.
- Pilot users can discover, invoke, inspect, approve and audit Skills without reading backend logs.
- No secret appears in run events, audit payloads, tool output artifacts or provider diagnostics.

#### Rollback

Set the global Runtime flag to legacy and disable package bindings. No destructive data migration is required.

## 10. Testing Strategy

### Backend

- Unit tests for Skill parsers, registries, context packing, SDK Agent factories, guardrail intersections and model configuration.
- Contract tests for each AgentMesh FunctionTool and configured SDK MCP server type.
- SDK fake-model tests for Runner turns, streaming items, tool calls, approvals, RunState serialization, session persistence and cancellation.
- Property-style tests for event projection sequence, idempotency and context budgets.
- Integration tests using an SDK-compatible fake model, fake function tools, a local reference MCP server and temporary SQLite.
- Security tests for path traversal, symlinks, archive bombs, prompt injection boundaries, grant escalation, trace leakage and approval replay.
- Recovery tests for browser reconnect, paused RunState reload and explicit retry after interrupted in-flight work.

### Frontend

- Vitest for Skill catalog, Composer activation, run timeline, approval state, SSE reducer and reconnect cursor.
- Playwright for explicit `$` invocation, tool progress, provider failure, cancellation, approval/resume, Artifact viewing and Runtime rollback.
- OpenAPI type regeneration is required whenever an API schema changes.

### Verification commands

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
npm --prefix agentmesh-demo run api:types
npm --prefix agentmesh-demo run test
npm --prefix agentmesh-demo run build
npm --prefix agentmesh-demo run test:e2e
```

### Manual acceptance

1. Load the Wiki Skill roots and review diagnostics without enabling scripts.
2. Invoke each pilot Skill explicitly from the Workspace Composer.
3. Observe progressive activation and source/Skill provenance.
4. Run one Memory tool call, one Document search, one O2/Research call and one local MCP fixture call.
5. Trigger a denied tool, an approval-required tool and an approved resume.
6. Disconnect the browser and reconnect to the same run.
7. Restart the API during a waiting approval and resume safely.
8. Force context compaction and confirm the active Skill remains effective.
9. Disable Runtime v2 and confirm legacy chat still works.

## 11. Migration and Compatibility

- Current `ChatSkillSpec` entries become compatibility projections backed by built-in SkillDefinition records.
- Phase 1 stores `SkillDefinition` and `SkillBinding` in the existing records store to avoid an unrelated migration.
- Phase 2 adds only three dedicated relational tables—`agent_runs`, `agent_run_events`, and `artifacts`—because they require transactional sequence allocation, replay indexes, and retention queries. This is the first isolated slice of ADR 0002.
- Current dotted commands such as `$memory.search` remain aliases; standard Skill names use lowercase hyphenated names.
- Current `Intent` values remain for product analytics and legacy workflows, but generic Skills do not require a new Intent.
- Current PersonalAgent delegates Runtime v2 runs behind the feature flag and retains the legacy implementation through Phase 6.
- OpenAI Agents SDK `Agent`/`Runner` replace only the LLM/Agent execution path; existing AgentMesh Task, BBS, Inbox, Memory, Source and Audit models remain product projections and governance truth.
- `AgentMeshSession` implements the SDK Session protocol over AgentMesh storage; the SDK does not create a second conversation database.
- Current ChatResponse stays stable while async run endpoints are introduced.
- LearnedSkill is not renamed or overloaded. Approved learned workflows materialize a separate SkillDefinition with a provenance link.

## 12. Security and Trust Model

1. Workspace administrators control imported Skill sources and enablement.
2. Project-local Skill roots are ignored until explicitly trusted by an administrator.
3. Skill instructions are untrusted input below platform policy in prompt precedence.
4. Skill `allowed-tools` never grants access.
5. Tool arguments are validated by SDK/Pydantic before policy evaluation; SDK tool input guardrails run before approval and again before execution.
6. Read-only and side-effecting tools are distinct in metadata and execution policy.
7. External content is separated from instructions and assessed before entering model evidence.
8. Third-party scripts do not execute in-process; the first release executes no imported scripts.
9. Secrets stay in provider/tool credential stores and are never copied into Skill metadata, model context or run events.
10. Full tool outputs are permission-scoped Artifacts; model-visible output is truncated.
11. Every run snapshots Skill version, SDK Agent definition version, tool version, grants, model and policy version for reproducibility.
12. SDK default tracing export is disabled; only the AgentMesh local trace processor is enabled, with sensitive input/output capture off.

## 13. Dependency and Failure Attacks

### Dependency failure

- Model provider down: use SDK model-call retries only when replay safety permits. Cross-model fallback is allowed only before any local tool side effect; otherwise fail the run with a stable reason and require an explicit retry.
- Optional Tool provider down: return a source-attributed tool error and let the model continue only when the Skill does not mark the tool as required.
- Required Tool provider down: stop with an actionable unavailable result; never substitute mock data in production mode.
- Embedding down: fall back to FTS5 without broadening permissions.
- MCP server down: isolate failure to that server and expose health diagnostics.

### Scale explosion

The first limits likely to break at 10× are SQLite write contention and event volume, not Skill discovery. Trigger the accepted relational/PostgreSQL migration when any of these occur:

- more than 50 concurrent active runs;
- more than 1,000,000 retained AgentRunEvent rows;
- more than one API process must write the same database;
- p95 event append latency exceeds 100 ms during an internal load test.

### Rollback cost

All phases use additive schemas and compatibility projections. Runtime selection is reversible through one flag. Package versions are immutable. No phase removes the legacy path or accepted memory data.

## 14. Effort and Staffing

Assumption: two backend engineers, one frontend engineer, and shared QA/security support familiar with this repository.

| Phase | Backend effort | Frontend effort | QA/security effort | Calendar |
|---|---:|---:|---:|---:|
| 1. SDK foundation + Skill catalog | 3 person-weeks | 1 | 1 | 2 weeks |
| 2. SDK tools + HITL | 4 | 1 | 2 | 2.5 weeks |
| 3. SDK sessions + streaming | 3 | 2 | 1.5 | 2 weeks |
| 4. SDK harness + packages | 3 | 1.5 | 2 | 2.5 weeks |
| 5. Memory/RAG | 4 | 1 | 2 | 2.5 weeks |
| 6. Operational readiness | 2 | 1.5 | 2 | 1.5 weeks |

Expected calendar with partial overlap: **9–11 weeks**.
Expected solo implementation: **18–24 weeks**.

This plan affects more than eight files and introduces four new internal component families (`agent_runtime`, `skill_runtime`, `tool_runtime`, `harness`, plus `retrieval` in Phase 5). The SDK supplies the Agent loop; these AgentMesh modules provide integration and governance rather than a competing runtime.

## 15. Dependencies and Credentials

| Dependency or credential | Phase | Purpose | Handling |
|---|---:|---|---|
| `openai-agents==0.21.1` | 1–6 | Sole Agent/Runner/tools/guardrails/sessions/MCP/tracing framework | Exact version pinned; upgrades require SDK conformance, internal-provider and approval-resume tests. Current Python 3.13.0 and Pydantic 2.13.4 satisfy its declared Python/Pydantic ranges. |
| `PyYAML` | 1 | Parse standard Skill frontmatter with a controlled fallback | Use safe loading; never execute YAML tags |
| `jsonschema` | 1–2 | Validate Skill package metadata and dynamic ToolDefinition schemas | Pinned in the Python environment |
| Existing internal LLM credential | 1–6 | SDK `AsyncOpenAI` client against the current OpenAI-compatible gateway | Server-side only; never placed in RunContext or RunState |
| Existing O2 CLI login state | 2 and 6 | Internal research/data FunctionTools | Verified on the trusted host with the existing secret-safe smoke; no token copied into AgentMesh |
| MCP server credentials | 2 and 6 | SDK MCP integrations | Referenced by admin-managed environment/secret store; never accepted from a Skill package |
| Existing embedding credential | 5 | Optional hybrid retrieval | Feature-gated; FTS5 remains available when absent |

Phase 1 requires no new external account if the current internal gateway passes the SDK Chat Completions compatibility smoke. SDK default OpenAI trace export remains disabled, so no OpenAI tracing key is required. Phase 2 tests use a local reference MCP server and fake SDK model/tools. Production MCP enablement remains blocked until the platform administrator supplies a server inventory and each server passes a secret-safe connectivity smoke.

## 16. Fragile Assumption

This plan assumes the current internal OpenAI-compatible gateway can satisfy the OpenAI Agents SDK Chat Completions contract for streaming function-tool calls.

Phase 1 tests this as a release gate. If text/streaming works but tool-call deltas are unreliable, enable the SDK's streamed-tool-call buffering. If native function-tool calls still fail, Phase 1 prompt Skills remain usable, but Phase 2 autonomous tools do not enter production until a tool-capable model endpoint is configured. The plan does not add a home-grown JSON action loop as a fallback, because that would violate the requirement to use a mature AI framework.

## 17. Deferred Inputs With Owners

These do not block Phase 1 approval:

| Input | Owner | Resolution point | Reason for deferral |
|---|---|---|---|
| Production MCP server list and credentials | Platform administrator | Before Phase 2 production smoke | Phase 2 is contract-tested against a local reference server first |
| First restricted script-worker technology | Security/platform team | Phase 4 design review | Imported scripts are disabled through Phases 1–3 |
| PostgreSQL production topology | Platform/DBA | Only when a scale trigger in Section 13 occurs | Internal single-process SQLite is the confirmed first boundary |
| Public SaaS tenancy, billing and compliance | Product owner | Outside this plan | The confirmed release target is trusted-intranet single Workspace |

## 18. Approval Decision

Approval authorizes OpenAI Agents SDK as the sole LLM/Agent execution framework and the six independently deployable phases. It does not authorize implementation, package imports, provider credential changes or external writes. Implementation begins only after the owner approves this revised plan in Plannotator.

## Sources

- [Agent Skills specification](https://agentskills.io/specification)
- [How to add Skills support to an agent](https://agentskills.io/integrate-skills)
- [OpenAI Agents SDK agents and Runner](https://openai.github.io/openai-agents-python/agents/)
- [OpenAI Agents SDK tools](https://openai.github.io/openai-agents-python/tools/)
- [OpenAI Agents SDK guardrails](https://openai.github.io/openai-agents-python/guardrails/)
- [OpenAI Agents SDK sessions](https://openai.github.io/openai-agents-python/sessions/)
- [OpenAI Agents SDK human-in-the-loop](https://openai.github.io/openai-agents-python/human_in_the_loop/)
- [OpenAI Agents SDK MCP](https://openai.github.io/openai-agents-python/mcp/)
- [OpenAI Agents SDK tracing](https://openai.github.io/openai-agents-python/tracing/)
- [LangGraph persistence reference](https://docs.langchain.com/oss/python/langgraph/durable-execution)
- [Pi coding agent reference](https://github.com/earendil-works/pi-mono/tree/main/packages/coding-agent)
