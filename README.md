# AgentMesh

Chat-first team agent platform prototype.

**Repository**: <https://github.com/yssssssssssss/ai-agentmesh-hackathon>

## Current Slice

The first implementation slice proves:

1. A user sends a chat message.
2. The backend stores the message.
3. Natural chat stays private, while explicit `$` skills start workflows.
4. The backend creates a task.
5. The task creates an internal blackboard request.
6. A mock research Agent returns evidence.
7. The chat response includes a source.
8. Activity logs record what the personal Agent and external Agent did.
9. The workspace can search chat, activity, blackboard evidence, and memory items with source-aware results.
10. The UI loads workspace, project, user, Agent, and live metric context from the backend.
11. Chat sessions persist as project-bound threads and the UI reuses the active thread for follow-up messages.
12. Search results are filtered by the current workspace and project context.
13. Search supports permission-aware visibility modes: `personal`, `project`, and `team`.
14. Memory review uses explicit states, and accepting a memory promotes it to team scope.
15. `risk_agent` creates policy-backed risk posts and routes human confirmations to Inbox.
16. Chat answers can be synthesized by an OpenAI-compatible LLM when a configured model is selected.
17. External research is behind an acquisition Agent interface, so the crawler/search implementation can be supplied by another project.
18. The API now has a minimal cookie session auth layer, local user lifecycle APIs, and role checks for personal Agent edits and team-memory acceptance.
19. System tools are registered in the backend and explicitly granted to Agents; tools are not automatically exposed to every personal Agent.
20. Text, Markdown, PDF, Word, slide, and image files can be uploaded, parsed, stored, and surfaced as Sources.
21. Workspace/project APIs persist records in SQLite and allow admins to create new workspaces and projects.
22. Blackboard supports agent/system-created posts, read markers, replies, pagination, and a queued auto-post drain path.
23. Risk review uses persisted policy rules for prompt-injection, source policy, approval, and high-risk tool signals; admins can manage rules from the Members page.
24. `data_agent` has a connector registry with a local metrics connector and can answer chat-triggered metric queries.
25. `research_agent` can use a Web acquisition provider when `AGENTMESH_WEB_PROVIDER` is configured.
26. Chat exposes an explicit `$` skill menu for memory search, Brief creation, private notes, external research, data queries, risk review, memory proposals, and system/model info.
27. Brief drafts can be confirmed from Inbox and turned into sourced team memory candidates.
28. Blackboard evidence, decisions, digests, archives, and memory-candidate posts can be promoted into governed team memory candidates.
29. The React `/tasks` route provides a project board/list over permission-filtered Task and Blackboard data. It stays read-only by default; `AGENTMESH_TASK_MANAGEMENT=write` enables versioned creation, editing, assignment, delivery transitions, blocking, cancellation, and archival.
30. In-progress project Tasks can create Agent Runtime v2 Runs with an immutable `task_id`; Task detail exposes safe Run and Artifact summaries while retry preserves the Task link.

## Run Locally

Set up an isolated environment:

```bash
/opt/homebrew/bin/python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

Install and build the React frontend for FastAPI hosting:

```bash
cd agentmesh-demo
npm ci
npm run api:types
npm run build
cd ..
```

Start the app with production-safe defaults:

```bash
.venv/bin/uvicorn agentmesh.app:app --reload --port 8010
```

The default startup does not create demo users, fixed passwords, or demo content. This MVP supports one Workspace, one default Project, one application instance, and one SQLite database; do not expose it to the public internet.

For an isolated local demo database only, opt in explicitly:

```bash
AGENTMESH_DEMO_MODE=1 AGENTMESH_DB_PATH=data/agentmesh-demo.sqlite3 \
  .venv/bin/uvicorn agentmesh.app:app --reload --port 8010
```

Demo mode creates deterministic fixture accounts and content with known local-only credentials. Never enable it for a shared or production database.

Task Center mutations are fail-closed. The default `read_only` mode keeps the current board and details available without accepting project-task writes. Enable the approved Slice 1 mutation contract explicitly in a local or controlled environment:

```bash
export AGENTMESH_TASK_MANAGEMENT=write
```

Port `8000` is intentionally avoided because it may already be used by another local backend.
If `8010` is already in use, first check whether AgentMesh is already running:

```bash
lsof -nP -iTCP:8010 -sTCP:LISTEN
curl http://127.0.0.1:8010/api/health
```

If the listener is an old AgentMesh process, stop that process before starting a new reloader:

```bash
kill <PID>
```

Or start this instance on another port:

```bash
.venv/bin/uvicorn agentmesh.app:app --reload --port 8011
```

Open:

```text
http://127.0.0.1:8010/
```

The app UI shows a local login panel when no session exists. In explicit demo mode, use the fixture-account controls shown by the local UI; production-safe mode has no built-in account credentials.

For frontend development, keep FastAPI on port `8010` and run `npm run dev` in `agentmesh-demo/`; Vite serves `http://127.0.0.1:5178/` and proxies `/api` to FastAPI. The retired single-file UI remains temporarily available at `/legacy/app.html` and `/app.html` for one release cycle.

### Skill Matrix orchestration

Multi-Skill orchestration is disabled by default and requires Agent Runtime v2 plus a configured model and Wiki corpus:

```bash
export AGENTMESH_AGENT_RUNTIME=v2
export AGENTMESH_WIKI_ROOT=/absolute/path/to/approved/wiki
export AGENTMESH_SKILL_ORCHESTRATION=preview
export AGENTMESH_TASK_SCENARIO_ROUTING=true
```

The server is the only configuration authority; the React app reads the effective mode from `/api/bootstrap` and does not use a Vite feature flag.

The builtin catalog contains 84 unique 2C-DesignWiki Skills, grouped into 17 pre-design, 26 during-design, and 41 post-design capabilities. Ten governed Pilot Skills remain eligible for the unchanged legacy automatic-planning path. Phase 1B local authoring now provides versioned Profile sidecars for all 84 Skills: the 74 generated imports are explicit `review_state=draft`, `planner_eligible=false`, while the ten legacy Pilot Profiles retain their existing execution fields. The draft Profiles are offline-only, cannot enter public recommendations or Agent Runs, and grant no production trust. Of the 84 catalog entries, 57 have current runtime adapter paths and 27 are marked `tool_limited` from their declared host tools; conservative draft Profiles may declare additional unavailable dependencies so future Universal readiness fails closed. Catalog and explicit-command integration does not imply that external tools have been granted or implemented. The UI keeps Skills discoverable and explicitly startable, but labels unavailable adapters accordingly; runtime Tool Grant and approval checks remain authoritative. With Agent Runtime v2 enabled, `/api/chat/skills` exposes those 84 Skills plus the 11 Legacy commands (95 entries total). Refresh or verify the vendored snapshot with:

```bash
.venv/bin/python scripts/sync_wiki_skills.py
.venv/bin/python scripts/sync_wiki_skills.py --check
# Optional authoring scaffold; creates missing draft sidecars and never overwrites existing ones.
.venv/bin/python scripts/sync_wiki_skills.py --generate-profile-stubs
```

| Mode | Natural-language request | Explicit `$skill` | Existing Legacy `$group.command` |
| --- | --- | --- | --- |
| `off` | Existing single Runtime v2 path | Single Skill Runtime v2 | Legacy chat path |
| `preview` | Recommend and persist a plan; confirmation never executes its DAG | Single Skill Runtime v2 | Legacy chat path |
| `execute` | Confirmed plans execute a bounded DAG | Single Skill Runtime v2 | Legacy chat path |

Legacy plans with two or more domain Skills still stop at the Plan Approval gate. Task/Scenario plans with high or medium confidence and only read/draft effects continue automatically in `execute` mode; `preview`, high-risk decisions, and write effects still pause. Confirming a plan does not approve a Tool call: approved external tools use a separate node-level approval, without repeating approval for internal Provider subcalls. The parent Run is the durable control record; refresh or SSE reconnect reads the same Run and Plan instead of starting work again.

Roll out in order: `off` → `preview` → `execute`. Setting `off` is the final restart state, not by itself a safe online rollback. Production rollback must first fence ingress, quiesce the live process, stop the only SQLite writer, run the checksum-bound offline inventory and backup/restore checks, and then restart a forward-compatible binary with:

```bash
export AGENTMESH_SKILL_ORCHESTRATION=off
```

Follow the [Universal Skill orchestration release and rollback runbook](docs/runbooks/universal-skill-orchestration.md). Open Tool approvals remain stopped after rollback and are never auto-resumed.

The orchestration API surface is:

- `POST /api/skills/recommendations`
- `POST /api/skills/routing-preview`
- `POST /api/agent/runs`
- `GET|PATCH /api/agent/runs/{run_id}/plan`
- `POST /api/agent/runs/{run_id}/plan/approve`
- `POST /api/agent/runs/{run_id}/plan/reject`
- `POST /api/agent/runs/{run_id}/retry`
- `POST /api/agent/runs/{run_id}/cancel`
- `GET /api/agent/runs/{run_id}/events`
- `GET /api/agent/runs/{run_id}/events/stream`

Run the deterministic release gates before moving beyond `preview`:

```bash
.venv/bin/python eval/run_skill_retrieval_eval.py
.venv/bin/python eval/run_universal_skill_retrieval_eval.py
.venv/bin/python eval/run_universal_skill_profile_smoke.py --mode fts-only
# Offline rollback preflight; --apply additionally requires the printed checksum,
# a separate integrity-checked backup path, a durable receipt path, and a
# two-operator approval file.
.venv/bin/python scripts/quiesce_skill_orchestration.py --database data/agentmesh.sqlite3
.venv/bin/python scripts/skill_catalog_report.py agentmesh/builtin_skills
.venv/bin/python -m pytest
.venv/bin/ruff check agentmesh tests scripts eval
npm --prefix agentmesh-demo test -- --run
npm --prefix agentmesh-demo run api:types
npm --prefix agentmesh-demo run build
npm --prefix agentmesh-demo run test:e2e
```

### Research workflow retirement

Research-v2 is retired: no Runtime or mutation path remains, while owner-scoped historical Runs and Artifacts stay readable through a read-only adapter. Client-turn replay may return an existing v2 Run but cannot restart it.

Research-v3 was retired before production launch. Its preview entry points, dedicated catalog and Workbench were removed; residual additive SQLite tables are inert and are not an activation mechanism. New full-report work uses explicit DeepSearch on the existing v1 Skill DAG. See [ADR 0008](docs/adr/0008-retire-research-v3-preview.md) and the [DeepSearch v1 plan](docs/plans/2026-08-26-deepsearch-v1-development-plan.md).

### DeepSearch v1

DeepSearch is implemented behind a default-off release gate. A client must explicitly send `planning_mode="deepsearch"`; the server never infers it from prompt wording and never falls back to ordinary chat. New runs require `AGENTMESH_AGENT_RUNTIME=v2`, `AGENTMESH_SKILL_ORCHESTRATION=execute`, `AGENTMESH_DEEPSEARCH_ENABLED=true`, an available model, and a real healthy `web_research` adapter. The v1 evidence path rejects other built-in tools and MCP. Skill resources remain readable only from the approved frozen manifest, are budgeted, and cannot become report Evidence.

The DeepSearch-specific API surface is:

- `GET /api/agent/runs/{run_id}/deepsearch`
- `POST /api/agent/runs/{run_id}/deepsearch/clarify`
- shared Plan edit/approve/reject, cancel, retry, event, and Artifact endpoints listed above

Keep the feature flag disabled until the real Provider smoke described below succeeds.

### Reference UI and data provenance

The `feature/reference-ui-mt-data` branch restores the visual hierarchy of the reference Mock frontend for DigitalSelf, Knowledge, Collaboration, and Insights while keeping FastAPI and SQLite as the authority for identity, permissions, state, versions, and mutations.

User-facing provenance labels are intentionally short:

- `T数据`: data returned by the current backend for the signed-in user's visible scope.
- `M数据`: reference Mock data, fixed display constants, or explicit demo seed data.

Mixed modules label Mock-derived fields separately. Mock-only sections never expose a successful local mutation; unavailable actions are disabled or described as not connected. The AI Workspace message, history, upload, search, `$` Skill, trace, and memory-search paths are outside this page-alignment scope.

Manual acceptance for this branch is documented in `docs/superpowers/plans/2026-08-14-reference-ui-mt-data-human-acceptance.md`.

### Deployment boundaries

This internal-pilot MVP supports one Workspace, one application process, and one SQLite database. Run it only on a trusted internal network. Multi-workspace tenancy, multi-process SQLite coordination, horizontal scaling, high availability, and public-internet hardening are Post-MVP work.

Before an internal release, run the real read-only Provider gate from a host with approved credentials and CLIs:

```bash
.venv/bin/python scripts/provider_smoke.py --embedding --o2 --web --data --llm
```

The command prints only redacted provider readiness, mode, latency, and stable error categories. A release is blocked unless all five providers report `ready=true` and `mode=real`.

## Test

```bash
.venv/bin/python -m pytest
```

Tests use an isolated SQLite database under the system temp directory, so they do not clear `data/agentmesh.sqlite3`.
The pytest bootstrap also clears default LLM environment variables so unit tests stay deterministic and do not call the real model service unless a test explicitly configures a mocked model endpoint.

## Local Data

The prototype uses SQLite by default:

```text
data/agentmesh.sqlite3
```

Override it with:

```bash
AGENTMESH_DB_PATH=/path/to/agentmesh.sqlite3 .venv/bin/uvicorn agentmesh.app:app --port 8010
```

Embedding is disabled by default and search remains FTS-only. To enable vector search, set `AGENTMESH_EMBEDDING_ENABLED=true`, `AGENTMESH_EMBEDDING_API_URL`, and `AGENTMESH_EMBEDDING_API_KEY` in the server environment. Inject the key through your deployment secret manager; do not commit or log it.

## Auth and Permissions

AgentMesh uses a minimal local auth and user-management layer for the current MVP slice:

- `POST /api/auth/login` creates an HttpOnly cookie session.
- `GET /api/auth/oauth/status` reports whether OAuth is configured without exposing secrets.
- `GET /api/auth/oauth/start` redirects to the configured corporate OAuth provider.
- `GET /api/auth/oauth/callback` exchanges an OAuth code, maps userinfo to a local user, and reuses the same HttpOnly cookie session.
- `POST /api/auth/logout` revokes the session.
- `GET /api/auth/me` returns the current user.
- `POST /api/auth/password` lets the current user rotate their password and revokes existing sessions.
- Demo users are seeded only when `AGENTMESH_DEMO_MODE=1`; production-safe startup creates no built-in credentials.
- Admins can create local users with initial passwords.
- Admins can reset local user passwords and revoke existing sessions.
- Creating a local user also creates that user's personal Agent.
- Admins can disable users; disabled users cannot log in or continue an existing session.
- Regular users can manage only their own personal Agent.
- Team leads and admins can accept candidate memories into team scope.
- Admins can manage public Agents.
- Admins can create workspaces and projects.
- Permission policy rules are persisted and admin-managed through:
  - `GET /api/users/permission-policies`
  - `POST /api/users/permission-policies` admin only
  - `PATCH /api/users/permission-policies/{rule_id}` admin only
- The MVP policy table currently controls role-level allow/deny overrides for sensitive actions such as `accept_team_memory` and `manage_public_agent`.

OAuth is implemented as an adapter framework. A real enterprise SSO rollout still needs provider URLs, client ID, client secret, redirect URI registration, and user/role mapping confirmation.

Enable OAuth:

```bash
export AGENTMESH_OAUTH_ENABLED=true
export AGENTMESH_OAUTH_AUTHORIZE_URL=https://sso.example.com/oauth/authorize
export AGENTMESH_OAUTH_TOKEN_URL=https://sso.example.com/oauth/token
export AGENTMESH_OAUTH_USERINFO_URL=https://sso.example.com/oauth/userinfo
export AGENTMESH_OAUTH_CLIENT_ID=agentmesh
export AGENTMESH_OAUTH_CLIENT_SECRET=your-server-side-secret
export AGENTMESH_OAUTH_REDIRECT_URI=http://127.0.0.1:8010/api/auth/oauth/callback
```

Do not commit `AGENTMESH_OAUTH_CLIENT_SECRET`. Users created through OAuth receive a personal Agent automatically and default to `AGENTMESH_OAUTH_DEFAULT_ROLE`.

## Agents and Tools

Public Agents are registered by backend code first, then exposed through API:

- `GET /api/agents/public`
- `GET /api/tools`
- `GET /api/agents/{agent_id}/tools`
- `PATCH /api/agents/{agent_id}/tools`

Tools are explicitly granted to Agents. Some tools now have MVP execution paths (`document_upload`, local data queries, risk rules, and configurable web research), but web research still requires a provider to be configured.

## Oxygen-CLI Internal Provider

Oxygen-CLI is treated as an internal company capability provider, not the only data source. AgentMesh keeps external Web providers, uploaded documents, local memory, and future BI/database connectors as separate sources.

Status and tool discovery APIs:

- `GET /api/integrations/o2/status`
- `POST /api/integrations/o2/sync` admin only

The sync endpoint reads Oxygen registry metadata and stores discovered CLI capabilities as `ToolDefinition` records with `provider=o2`. It does not automatically grant those tools to every Agent; existing Agent tool grants still apply.

Enable Oxygen-backed internal research:

```bash
export AGENTMESH_O2_RESEARCH_ENABLED=true
export AGENTMESH_O2_RESEARCH_CLI=metasearch
```

Enable Oxygen-backed data queries:

```bash
export AGENTMESH_O2_DATA_ENABLED=true
export AGENTMESH_O2_DATA_CLI=metasearch
```

Built-in Oxygen command contracts (verified against the working DesignOS connector):

AgentMesh prefers the standalone sub-CLI binary when it is on `PATH` and falls back to the `o2 launch <cli>` main entry only when no standalone binary is found. Authentication is handled by each CLI's own login state on the host machine; AgentMesh does not inject an access token via an environment variable.

- Research through `metasearch`:
  - Standalone (preferred): `oxygen-metasearch --json search --output json --endpoint <AGENTMESH_O2_METASEARCH_ENDPOINT> <query>`
  - `o2` fallback: `o2 launch metasearch search <query> --endpoint <AGENTMESH_O2_METASEARCH_ENDPOINT> --output json`
  - The endpoint defaults to `https://agentkits-a2a-gateway.jd.com/agents/sku-search`.
- Research through `o2-kb`:
  - Standalone (preferred): `o2-kb recall list --json <query>`
  - `o2` fallback: `o2 launch o2-kb recall list <query> --json`
  - Optional `AGENTMESH_O2_KB_RECALL_TOKEN` and `AGENTMESH_O2_KB_FOLDER_TO_APP` are appended only when set.
- Data through `metasearch`: same read-only search contract as research.
- Data through `oxygen-comment`:
  - Standalone (preferred): `oxygen-comment comment list --json --page-size <limit> [--sku-name <q> | --sku-ids <ids> | ...]`
  - `o2` fallback: `o2 launch oxygen-comment --json comment list --page-size <limit> ...`
- Data through `bdp-copilot`: `o2 launch bdp-copilot --json-output find-tables <query>`

Override the metasearch gateway endpoint with:

```bash
export AGENTMESH_O2_METASEARCH_ENDPOINT=https://agentkits-a2a-gateway.jd.com/agents/sku-search
```

If an approved CLI uses a different shape, override it with:

```bash
export AGENTMESH_O2_RESEARCH_COMMAND_TEMPLATE='launch {cli} search {query} --limit {limit} --json'
export AGENTMESH_O2_DATA_COMMAND_TEMPLATE='launch {cli} {operation} {query} --limit {limit} --json'
```

The Oxygen data connector is read-only in this slice. Write actions such as upload, edit, delete, install, and batch operations should be routed through Inbox/Risk review before execution.

Known runtime prerequisites:

- The standalone sub-CLIs (`oxygen-metasearch`, `o2-kb`, `oxygen-comment`) must be installed and logged in on the host where AgentMesh runs. Auth is not injected by AgentMesh.
- `o2-kb` must be initialized by `o2-kb init` before its recall/config commands work.
- `webcli`/browser-backed CLIs need the Browser Bridge daemon and extension connected.
- `bdp-copilot` execution still depends on the user's internal runtime and auth context.

## LLM Configuration

AgentMesh reads model services from environment variables. The legacy single-model configuration still works as the `default` model:

```bash
export AI_API_URL=https://modelservice.jdcloud.com/v1/responses
export AI_MODEL=Gemini-3-Flash-Preview
export AI_API_KEY=your-api-key
```

If you prefer the older chat-completions layout, keep using:

```bash
export AGENTMESH_LLM_BASE_URL=https://modelservice.jdcloud.com/v1/
export AGENTMESH_LLM_MODEL=GPT-5.5
export AGENTMESH_LLM_API_KEY=your-api-key
.venv/bin/uvicorn agentmesh.app:app --port 8010
```

Chat and orchestrated research Skills use separate timeout budgets; the parent orchestrated Run keeps its 300-second deadline:

```bash
export AGENTMESH_CHAT_LLM_TIMEOUT_SECONDS=120
export AGENTMESH_RESEARCH_SKILL_TIMEOUT_SECONDS=180
export AGENTMESH_SKILL_MATCH_LLM_TIMEOUT_SECONDS=8
export AGENTMESH_LLM_TIMEOUT_SECONDS=30
export AGENTMESH_LLM_CONNECT_TIMEOUT_SECONDS=5
```

Skill matching uses its shorter budget only for ambiguous or explicitly multi-deliverable requests that need semantic
reranking. If a model call times out,
AgentMesh returns the deterministic local match and a stable diagnostic instead of failing the request. If the chat model
times out, AgentMesh returns the deterministic local answer and records the reason in `workflow_trace.model_fallback_reason`.

Additional selectable models use `AGENTMESH_MODELS` plus per-model variables:

```bash
export AGENTMESH_MODEL_DEFAULT=default
export AGENTMESH_MODELS=gpt52,gpt54,gpt55

export AGENTMESH_MODEL_GPT52_BASE_URL=http://internal-llm-gateway/v1
export AGENTMESH_MODEL_GPT52_MODEL=GPT-5.2-joybuilder
export AGENTMESH_MODEL_GPT52_LABEL="GPT-5.2 JoyBuilder"
export AGENTMESH_MODEL_GPT52_API_KEY=your-api-key
export AGENTMESH_MODEL_GPT52_API_STYLE=chat_completions

# Repeat the same five variables for GPT54 and GPT55.
# The complete secret-free template is in .env.example.
```

`AGENTMESH_MODEL_DEFAULT=default` keeps the `AI_API_*` model as the default while exposing the three named GPT models in the Agent model selector. JoyBuilder currently accepts JSON mode but rejects OpenAI Native Structured Outputs, so configure `AGENTMESH_SDK_STRUCTURED_OUTPUT_MODE=json_object`. Providers that implement `response_format=json_schema` can keep the default `json_schema`; mixed deployments can override one named model with `AGENTMESH_MODEL_<ID>_STRUCTURED_OUTPUT_MODE`. JSON-object mode injects the same schema into the system instructions and still validates the final value locally with the SDK and Pydantic.

Gateways that reject strict function declarations can separately set `AGENTMESH_SDK_STRICT_TOOLS=false`; this does not change structured-output validation, and AgentMesh still validates arguments locally through Pydantic and tool guardrails.

Configure one optional automatic fallback model with:

```bash
export AGENTMESH_LLM_FALLBACK_MODEL_ID=fast
```

The UI stores only `model_id` on the Agent. API keys stay server-side and are never returned by `/api/models`. Eligible primary failures (`timeout`, request/HTTP errors, malformed or empty responses) try the configured fallback once; authentication failures remain explicit. Persisted traces expose requested/actual model and model fallback reason separately from acquisition Provider provenance.

## Acquisition Agent Boundary

AgentMesh keeps external acquisition as an interface boundary:

- `AcquisitionRequest` describes what the personal Agent needs.
- `AcquisitionResult` returns evidence, sources, actor, permission, and metadata.
- `MockAcquisitionAgent` keeps the default local flow working.
- `WebAcquisitionAgent` can call a configured Web provider.
- `ExternalAcquisitionConnector` remains a placeholder for an implementation supplied by another project.
- External content is treated as untrusted input. Suspicious prompt-injection text is saved for audit, marked `needs_review`, routed to Inbox, and excluded from LLM synthesis.
- High-risk tool requests such as batch crawling, batch downloads, intranet access, or automatic team-memory writes are routed to Inbox for approval before any acquisition connector runs.

To enable the native Tavily Web provider:

```bash
export AGENTMESH_WEB_PROVIDER=tavily
export AGENTMESH_TAVILY_API_URL=https://api.tavily.com/search
export AGENTMESH_TAVILY_API_KEY=your-api-key
export AGENTMESH_TAVILY_TIMEOUT_SECONDS=20
```

The Tavily connector sends a basic search request, returns only title/URL/content snippets, and never returns its key or provider response body. To enrich the selected Tavily results with page body text through Firecrawl's REST API, enable the optional scraper:

```bash
export AGENTMESH_FIRECRAWL_ENABLED=true
export AGENTMESH_FIRECRAWL_API_URL=https://api.firecrawl.dev/v2/scrape
export AGENTMESH_FIRECRAWL_API_KEY=your-api-key
export AGENTMESH_FIRECRAWL_TIMEOUT_SECONDS=60
export AGENTMESH_FIRECRAWL_MAX_PAGES=6
export AGENTMESH_FIRECRAWL_MAX_CONTENT_CHARS=4000
```

Tavily remains the discovery provider. Firecrawl can enrich selected results with bounded page text; failed enrichment falls back to the original Tavily snippet and is recorded in Provider metadata. For a trusted self-hosted Firecrawl endpoint, set `AGENTMESH_FIRECRAWL_API_URL` to its `/v2/scrape` URL; an API key is optional outside `*.firecrawl.dev`. Never expose an unauthenticated self-hosted endpoint publicly.

Command-backed providers remain available as alternatives.

To enable command-backed Web research instead:

```bash
export AGENTMESH_WEB_PROVIDER=opencli
export AGENTMESH_OPENCLI_COMMAND=opencli
export AGENTMESH_OPENCLI_COMMAND_TEMPLATE='opencli search {query} --limit {limit} --json'
```

or:

```bash
export AGENTMESH_WEB_PROVIDER=agent_browser
export AGENTMESH_AGENT_BROWSER_COMMAND=agent-browser
export AGENTMESH_AGENT_BROWSER_COMMAND_TEMPLATE='agent-browser search {query} --limit {limit} --json'
```

Without a command template, the provider runs `COMMAND query --limit N --json`. Templates support `{query}` and `{limit}` placeholders. The command should return JSON as an array, or an object with `items`, `results`, or `data`, containing `title`/`name`, `url`/`href`/`link`, and `snippet`/`content`/`summary`.

## Document Ingestion Boundary

Document ingestion is also kept as a thin boundary:

- `DocumentIngestionRequest` carries file metadata, bytes, workspace, project, and uploader.
- `ParsedDocument` returns normalized text plus a document `Source`.
- `CompositeDocumentParser` routes `.txt`, `.md`, `.markdown`, `.pdf`, `.docx`, `.pptx`, and common image files to built-in parsers.
- PDF parsing uses PyMuPDF when available through the project dependencies.
- Word and slide parsing extract OOXML text from `.docx` and `.pptx`.
- Image OCR uses a configured `tesseract` command; without that runtime, image uploads fail with an explicit parser error.
- `POST /api/documents/upload` stores parsed documents, creates Sources, and writes a short-term document-summary memory item.
- Files larger than the sync threshold are parsed through a `DocumentParseJob` background task and can be checked with `/api/documents/jobs/{job_id}`.
- `ExternalDocumentParserConnector` remains only as an extension boundary for future richer parsers, not as the default path for the file types above.

## Data Source Connector Boundary

Data source integration is reserved as a generic connector contract:

- `DataSourceQuery` carries connector name, operation, free-form parameters, workspace, project, and requester.
- `DataSourceResult` returns generic records plus a `data_source` Source.
- `DataSourceRegistry` routes queries to registered connectors.
- `http_data_api` is a production-facing read-only HTTP connector enabled by `AGENTMESH_DATA_API_URL`.
- `data_agent` tries configured production data connectors before falling back to O2 and `local_metrics`.
- `local_metrics` is a working local connector used by `POST /api/data-agent/query`.
- `ExternalDataSourceConnector` is a placeholder until a concrete external project provides the real data shape and access method.

Enable a real read-only data API:

```bash
export AGENTMESH_DATA_API_URL=https://your-company-data-api.example/api/data
export AGENTMESH_DATA_API_KEY=your-server-side-token
```

For a query operation such as `query`, AgentMesh POSTs to:

```text
{AGENTMESH_DATA_API_URL}/query
```

with JSON containing `operation`, `parameters`, `workspace_id`, `project_id`, and `requested_by`. The response may be an array, or an object with `records`, `items`, `results`, `data`, or `rows`. API keys stay server-side and are not returned by health or connector list endpoints.

## Workspace And Blackboard

Workspace and project records are persisted through the same SQLite store as the rest of the prototype:

- `GET /api/workspaces`
- `POST /api/workspaces` admin only
- `GET /api/projects`
- `POST /api/projects` admin only

Blackboard also has an auto-post queue for Agent background jobs:

- `GET /api/blackboard/auto-posts`
- `POST /api/blackboard/auto-posts`
- `POST /api/blackboard/auto-posts/drain`
- `GET /api/blackboard/auto-posts/worker`

Auto-post requests must be reviewed before drain publishes them into the BBS. A background worker is available but disabled by default; enable it with `AGENTMESH_AUTO_POST_WORKER_ENABLED=true` and configure the interval with `AGENTMESH_AUTO_POST_WORKER_INTERVAL_SECONDS`.

User memory daily summaries also have a disabled-by-default worker. Enable it in the production environment with `AGENTMESH_DAILY_MEMORY_WORKER_ENABLED=true`. The worker runs at 00:05 Asia/Shanghai, summarizes the previous calendar day, and performs one idempotent catch-up pass for yesterday on startup. It creates at most one `daily_summary` per active user/project/date and skips users without short-term source memory.

Project memory summaries use the configured LLM when available, then fall back to deterministic source rollups if the model is unavailable.
Project archives now include a recall-index section, and personal search can resolve the current user's layered memory items.
Uploaded documents are indexed for personal search, written to short-term document-summary memory, and can be used as chat evidence for relevant Brief/research requests.

## API Snapshot

- `POST /api/chat/messages`
- `POST /api/chat/threads`
- `GET /api/bootstrap`
- `GET /api/activity/today`
- `GET /api/audit?limit=50&action=...&target_type=...`
- `GET /api/inbox`
- `PATCH /api/inbox/{id}` with `status=open|snoozed|resolved`, optional `ttl_minutes`, or optional `snooze_until`
- `GET /api/memory`
- `GET /api/memory/user?layer=short_term|mid_term|long_term&project_id=...&memory_date=YYYY-MM-DD&memory_type=...`
- `POST /api/memory/user`
- `POST /api/memory/user/daily-summary`
- `POST /api/memory/user/group-summary`
- `GET /api/memory/user/daily-summary/worker` admin only
- `POST /api/memory/user/project-summary`
- `POST /api/memory/user/archive-project`
- `GET /api/users`
- `POST /api/users`
- `PATCH /api/users/{id}`
- `GET /api/search?q=关键词&workspace_id=...&project_id=...&visibility=personal`
- `GET /api/agents` with derived runtime status and current task fields
- `GET /api/blackboard`
- `GET /api/blackboard/task-cards`
- `POST /api/blackboard/posts`
- `PATCH /api/blackboard/posts/{id}/read`
- `POST /api/blackboard/posts/{id}/reply`
- `POST /api/blackboard/posts/{id}/handoff`
- `GET /api/blackboard/auto-posts`
- `POST /api/blackboard/auto-posts`
- `POST /api/blackboard/auto-posts/drain`
- `GET /api/blackboard/auto-posts/worker`
- `GET /api/workspaces`
- `POST /api/workspaces`
- `GET /api/projects`
- `POST /api/projects`
- `POST /api/auth/password`
- `POST /api/users/{id}/password`
- `POST /api/documents/upload`
- `GET /api/documents`
- `GET /api/data-sources`
- `POST /api/data-agent/query`
- `GET /api/integrations/o2/status`
- `POST /api/integrations/o2/sync`
- `GET /api/risk/policies`
- `POST /api/risk/policies`
- `PATCH /api/risk/policies/{id}`
