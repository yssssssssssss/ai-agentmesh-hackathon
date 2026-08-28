# AgentMesh vs. waku-agent: A Comparison

**Date:** 2026-08-21
**Scope:** Compares this repo's AgentMesh prototype against [ShenSeanChen/waku-agent](https://github.com/ShenSeanChen/waku-agent), researched live from its GitHub source (README, `pyproject.toml`, directory listings, commit history, contributor stats — via `gh api` and `raw.githubusercontent.com`).

---

## 1. Purpose & positioning

**AgentMesh** is a "chat-first team agent platform prototype" (`pyproject.toml` description) — a multi-user, multi-agent **team workspace**. It is built for a hackathon (directory name `ai-agentmesh-hackathon`) around the idea of several specialized agents (`risk_agent`, `data_agent`, `research_agent`, service agents) collaborating with humans and each other inside shared surfaces: chat, tasks, a blackboard evidence log, memory, and a risk-review inbox. The target user is a **team** — multiple people in a project/workspace, with permission-scoped visibility (personal/project/team) and role-based access control. It's explicitly a prototype meant to be run single-instance, not exposed to the public internet, per its own README.

**waku-agent** is "a local-first personal assistant" and, more precisely, "a minimal, transparent, local-first Waku: harness + loop + memory + eval, in code you can read in an afternoon" (README.md lines 3–7, 5). It is explicitly a **teaching / reference codebase** — its stated differentiator is not features but *legibility*: "Those are products you use. This is a codebase you own... Versus the big open-source assistants (OpenClaw, Hermes)? Same architecture, 1/100th the code" (README.md lines 119–124). The target user is a **single individual** running a personal AI assistant on their own laptop (calendar, memory, messaging), and/or a developer who wants to learn how a production-grade agent harness (loop, memory, eval, LLM-ops) is built, by reading ~95 lines of loop code (README.md line 12, confirmed: `waku/loop/agent.py` is 114 lines including comments/imports).

**Positioning gap:** AgentMesh is a *multi-user team collaboration platform*; waku-agent is a *single-user personal assistant / pedagogical framework*. These are fundamentally different product categories that happen to both be "AI agent" projects.

---

## 2. Architecture & tech stack

| Axis | AgentMesh | waku-agent |
|---|---|---|
| Primary language | Python (backend) + TypeScript (frontend) | Python (1,068,147 bytes) + JavaScript (201,815 bytes, dashboard frontend, no build step) + minor CSS/PLpgSQL/HTML/TS/Shell (`gh api repos/ShenSeanChen/waku-agent/languages`) |
| Backend framework | FastAPI | None — plain Python stdlib + `anthropic`/`openai` SDK clients; explicitly "no frameworks hiding the good parts" (README.md line 6) |
| Agent orchestration | `openai-agents==0.21.1` SDK (per prior AgentMesh research) | Hand-written ~95-line reason/act/repeat loop (`waku/loop/agent.py`, README.md lines 196–215) plus an optional graph engine (`waku/graph/engine.py`) for structured/parallel workflows, opt-in via `WAKU_GRAPH_WORKFLOWS=1` (README.md lines 237–282) |
| Frontend | React 18 + Vite + TypeScript, TanStack Query, Tailwind, react-router-dom, d3-force | Plain static JS/HTML/CSS dashboard, "no build step" (README.md line 81), served by `waku/ops/dashboard.py` |
| Data storage | SQLite (single-instance) | SQLite (`.waku/state.db`) with FTS5 keyword search as the default; explicit "your memory is one SQLite file. Open it. Read it. It's yours." (README.md line 9). Optional upgrade path to Supabase pgvector (`sql/init_supabase.sql`, README.md line 428) |
| LLM providers | OpenAI-compatible (per prior AgentMesh research) | Anthropic (default), OpenAI, Gemini, DeepSeek, MiniMax, Kimi, GLM, OpenRouter, OpenCode Zen, OpenCode Go — via a "~60-line adapter" (`waku/loop/models.py`, README.md lines 65–68); deps declared in `pyproject.toml` (`anthropic>=0.40`, `openai>=1.50`) |
| Deployment target | Single server instance (dev/demo), README warns against public internet exposure | Local laptop process (`127.0.0.1`, "nothing leaves your laptop", README.md lines 76–77); optional Telegram/Discord/WhatsApp/voice gateways, all opt-in extras in `pyproject.toml` |
| Packaging | Not published as a package (hackathon repo) | Published as a pip package: `pip install waku-agent` (README.md line 33; `pyproject.toml` `[project.scripts] waku = "waku.__main__:main"`) |
| License | Not stated in provided facts | MIT (`gh api repos/ShenSeanChen/waku-agent` → `license.spdx_id: "MIT"`; also `LICENSE` file at repo root) |
| Repo structure | Monolith app: `agentmesh/` (backend) + `agentmesh-demo/` (frontend) + `tests/` + `eval/` + `docs/` + `deliverables/` | Installable library/CLI: `waku/` (package: `loop/`, `memory/`, `tools/`, `gateway/`, `graph/`, `runtime/`, `ops/`, `db.py`, `config.py`, `app.py`) + `evals/` + `skills/` + `docs/` + `examples/` + `scripts/` + `sql/` (top-level contents via `gh api repos/ShenSeanChen/waku-agent/contents/`) |

Notably, despite the name, waku-agent is **not** built on the [Waku](https://waku.gg) React/Next-style SSR meta-framework — "Waku" here is the assistant's given name/brand ("Meet Waku"), and the stack is pure Python + vanilla JS. This is worth flagging explicitly since the name invites confusion.

---

## 3. Agent capabilities

| Capability | AgentMesh | waku-agent |
|---|---|---|
| Multi-agent orchestration | Yes — multiple named agents (`risk_agent`, `data_agent`, `research_agent`, service agents in `agentmesh/service_agents/`) coordinating via a shared blackboard | No native multi-agent swarm. Single agent loop per turn. A `delegate_task` tool can hand off coding jobs to an external CLI coding agent ("pi") as a subprocess — described as "Sub-Agents is now LIVE" but scoped narrowly to coding tasks (README.md lines 396–408; implemented in `waku/tools/experimental.py`, gated behind `WAKU_EXPERIMENTAL=1`) |
| Tool use | Explicit per-agent tool grants via a tool registry (`agentmesh/tool_runtime/`, `agentmesh/tools.py`) — "not auto-exposed" | Tool registry (`waku/tools/registry.py`) with built-in tools: calendar (`calendar.py`, `google_calendar.py`, `apple.py`), notes (`notes.py`), web search (`search.py`), messaging (`messages.py`), workspace/code (`workspace.py`), GitHub (`github.py`), MCP client (`mcp_client.py`); MCP server support is an optional extra (`pyproject.toml`: `mcp = ["mcp>=1.0"]`) |
| Memory | Personal/project/team memory review & promotion workflow; blackboard-to-governed-memory-candidate pipeline (`agentmesh/store.py`, per prior research) | Three explicit "pillars" — semantic (durable facts, `waku/memory/semantic/`), episodic (dated events/past chats, `waku/memory/episodic/`), procedural (skills, `waku/memory/procedural/` + `skills/`) — plus a **retrieval gate** that decides per-turn whether memory lookup is needed at all (`waku/memory/retrieval_gate.py`, README.md lines 286–295) and a consolidation pass that summarizes chat history into facts every N turns (`waku/memory/consolidation.py`) |
| RAG / retrieval | Layered retrieval described in prior research (`agentmesh/retrieval/`), vector index (`agentmesh/vector_index.py`), embedding module (`agentmesh/embedding.py`) | Default is SQLite FTS5 keyword search, not vector/semantic RAG, by design ("SQLite FTS5 keyword memory" — README.md line 427 table). Optional upgrade path to Supabase pgvector semantic search via `WAKU_SEMANTIC_STORE=supabase` (README.md line 428), or to hosted vector memory backends (mem0, Zep, LangMem) benchmarked against the built-in store via an "Arena" (`waku/memory/semantic/mem0_store.py`, `zep_store.py`, `langmem_store.py`; `pyproject.toml` `arena` extra) |
| Workflows | Task creation from chat, Brief draft → Inbox confirm pipeline, marketplace/skill flows (per prior research) | Graph workflow engine for structured multi-step turns (parallel branches, conditional routing) as an alternative to the plain reason/act loop, opt-in via `WAKU_GRAPH_WORKFLOWS=1` (`waku/graph/engine.py`, `waku/graph/workflows/`; README.md lines 237–282). Shipped example: a "triage" graph that classifies + checks calendar in parallel before routing to a fast or full-agent path |
| Streaming / real-time UX | Not confirmed from provided AgentMesh facts | Not called out in README as a streaming feature; dashboard shows live per-turn trace/state instead (README.md lines 70–98) |
| Chat interface | Chat with `$`-prefixed skill commands, multi-surface search across chat/activity/blackboard/memory | Terminal chat (`waku`), browser "cockpit" dashboard at `localhost:7777` with a persistent chat dock, plus voice, Telegram, Discord, WhatsApp gateways — all funneling into one shared session/memory (README.md lines 28–36, 70–98, 345–349; gateways in `waku/gateway/`) |
| Risk / governance | Dedicated `risk_agent` with policy-backed risk posts routed to a human-confirmation Inbox; persisted, UI-manageable risk policy rules (per prior research, `agentmesh/risk.py`) | No equivalent risk/governance/approval subsystem. Closest analog is the release-gate eval mechanism (`make gate`, `waku/ops/release_gate.py`) which is a CI-style quality gate for the *codebase*, not a runtime governance layer over agent actions |
| Eval / observability | `eval/` directory (evaluation harness), per prior research | First-class, two-track eval system: deterministic pytest suite (`evals/deterministic/`, "did the right tool fire? 0 or 1") and LLM-as-judge suite using DeepEval (`evals/judge/`, "was the reply helpful? scored %"), unified into `make gate` as a release gate requiring both to pass (README.md lines 297–327). Always-on JSONL tracing (`.waku/traces/<date>.jsonl`) and optional OpenTelemetry export to Arize Phoenix / Langfuse (README.md lines 334–343; `waku/ops/tracing.py`) |

**Summary of capability shape:** AgentMesh's differentiator is **cross-agent, cross-human coordination and governance** (blackboard, risk inbox, permissions, marketplace). waku-agent's differentiator is **memory engineering and eval discipline for a single agent** (three-pillar memory with a retrieval gate, deterministic-vs-judged eval split, always-on tracing). AgentMesh has essentially no built-in eval harness comparable in depth to waku-agent's; waku-agent has no multi-agent, multi-user, or governance/risk layer.

---

## 4. Technical maturity / stability

| Signal | AgentMesh | waku-agent |
|---|---|---|
| Stars / forks / watchers | Not a public GitHub repo in the same sense (local hackathon prototype) | 1,505 stars, 280 forks, 1,505 watchers, 6 subscribers (`gh api repos/ShenSeanChen/waku-agent` — as of 2026-08-21) |
| Open issues / PRs | Not tracked publicly | 18 open issues, 9 open PRs (`gh api repos/ShenSeanChen/waku-agent` → `open_issues_count`; `gh api "repos/ShenSeanChen/waku-agent/pulls?state=open"`) |
| Contributors | Single team (hackathon context) | 20 distinct contributors visible via `gh api repos/ShenSeanChen/waku-agent/contributors`; heavily maintainer-driven (ShenSeanChen: 272 contributions) with a long tail of 1–7 contributions each from community members |
| Repo age / activity | Active, in-progress (per git log in this session: 5 recent commits dated around current work) | Created 2026-07-10, last push 2026-08-17 (`gh api repos/ShenSeanChen/waku-agent` → `created_at`, `pushed_at`) — roughly 5–6 weeks old but very high commit velocity; recent commits include real bug fixes (e.g. an OpenAI model-deprecation break, commit `8328f56`, and an environment-variable leak in a subprocess spawn, commit `4b50bd4`), not just feature churn |
| Release / tag history | No tags observed | 4 published tags: v0.1.0, v0.1.1, v0.1.3, v0.1.4 (`gh api repos/ShenSeanChen/waku-agent/tags`); `pyproject.toml` version `0.1.4`, classifier `"Development Status :: 4 - Beta"` |
| CI | None described in provided facts (tests run manually/locally) | One GitHub Actions workflow: `.github/workflows/validate-skills.yml` (validates community-contributed skill frontmatter). No broader "run pytest on every PR" workflow visible in the top-level `.github/workflows/` listing — CI coverage appears narrow (skills validation only), with `make gate` (deterministic + judge evals) apparently run manually/pre-merge rather than as an automated GitHub Actions gate |
| Test coverage | `tests/` — 31,890 total lines across ~50+ files, covering chat flow, agent binding, agent runtime, MVP governance/ingestion/isolation, permissions, research orchestration, marketplace, etc. (per prior AgentMesh research, verified: `tests/` dir contains 86 Python test files in this session's `find tests -name "*.py" | wc -l`) | `evals/deterministic/` contains 62 files (`gh api .../contents/evals/deterministic` count), split further into a judged suite (`evals/judge/`: `test_response_quality.py`, `test_retrieval_gate_accuracy.py`) plus a `coding.jsonl` and `dataset.jsonl` fixture set. Commit `7631e09` references "pytest evals/deterministic: 416 passed, 13 skipped" as a real, current pass count |
| "Not production ready" disclaimers | Explicit — README warns against exposing to public internet, single-workspace/single-DB (per prior AgentMesh research) | No explicit "not production ready" disclaimer, but the entire framing is "a codebase you own" for personal/local use, not a hosted product; `pyproject.toml` classifier is `"Development Status :: 4 - Beta"` |
| Scalability constraints | SQLite, single-instance, explicitly not for multi-tenant/public internet | SQLite is the explicit, permanent default for a single local user (`.waku/state.db`); this is a design choice (local-first), not a limitation to be fixed — but it means waku-agent has no built-in multi-tenant or multi-instance story at all. An upgrade path to Supabase Postgres/pgvector exists for teams that outgrow local SQLite (README.md line 428) |
| Deployment guidance | Local/dev server only | `pip install waku-agent` for end users; `uv venv && uv pip install -e .` for contributors reading the code (README.md lines 28–47); explicitly runs on `127.0.0.1` only, no hosted/cloud deployment story provided |

**Maturity verdict:** waku-agent shows stronger *open-source project* maturity signals (real external contributors, tagged releases, a growing star count, evidence of live bug triage against real user reports like the OpenAI model-deprecation incident). AgentMesh shows stronger *internal test-depth* signals (86 test files / ~32K lines covering many governance/permission/isolation edge cases) appropriate to its more complex multi-agent, multi-user surface area, but has no public release history, external contributors, or CI evidence in the facts gathered. Neither project claims production-hardened, internet-facing readiness — waku-agent by design (local-first, single-user), AgentMesh by explicit disclaimer (prototype, don't expose publicly).

---

## 5. Notable strengths and gaps

### AgentMesh — strengths
- Rich multi-agent, multi-human collaboration model: blackboard, risk inbox, permission-scoped cross-surface search — capabilities waku-agent does not attempt at all.
- Deep governance primitives: persisted, UI-editable risk policy rules; human-confirmation gates on agent-originated risk findings.
- Broad document ingestion (text/Markdown/PDF/Word/slides/images via PyMuPDF and other parsers) feeding a "Sources" retrieval surface.
- Large, structured test suite specifically probing multi-tenant-adjacent concerns (user isolation, permissions, project member access) even though the app itself is single-instance today.

### AgentMesh — gaps/risks
- Explicitly a prototype: single SQLite instance, README itself warns against public-internet exposure — no story yet for concurrent multi-instance or multi-tenant deployment.
- No public release/versioning, no external contributor base, no CI signal provided — maturity is asserted internally (tests) rather than demonstrated externally (releases, community usage).
- No dedicated eval harness with the deterministic-vs-judged rigor waku-agent has; an `eval/` directory exists but its depth/discipline is not documented to the same level.

### waku-agent — strengths
- Exceptional engineering discipline for its scope: a two-track eval system (deterministic pytest + DeepEval LLM-as-judge) unified into a release gate, always-on JSONL tracing, and a real bug-fix-then-lock-with-a-test workflow demonstrated in its own commit history (README.md lines 322–327; commit `7631e09`).
- Genuinely minimal, readable core (~95-line loop) that is easy to audit and extend — the stated pedagogical goal is credibly met by the file structure (`waku/loop/agent.py` at 114 lines).
- Broad LLM-provider portability (9+ providers/gateways via one small adapter) and multiple upgrade paths (SQLite → Supabase pgvector, built-in memory → mem0/Zep/LangMem) that are opt-in rather than forced complexity.
- Live external community: 1,505 stars, 280 forks, 20 contributors, tagged releases, and issues/PRs being actively triaged (e.g., closing #132 and #106 in the commits reviewed).

### waku-agent — gaps/risks
- No multi-user or multi-agent-swarm story; "sub-agent" support is narrowly scoped to delegating coding tasks to an external CLI tool (`pi`), not general agent-to-agent collaboration.
- No governance/risk/approval layer for agent actions — nothing analogous to AgentMesh's risk inbox or permission-scoped visibility.
- Default retrieval is keyword-based (SQLite FTS5), not semantic/vector search; true RAG requires opting into an external backend (Supabase, mem0, Zep).
- CI coverage visible in the repo is narrow — only a skills-frontmatter validator workflow (`validate-skills.yml`); no evidence of `pytest`/`make gate` running automatically on every PR via GitHub Actions.
- Local-first by design means no built-in multi-instance or hosted-service deployment path — appropriate for a personal assistant, not usable as-is for a team platform.

---

## 6. Where they do (and don't) compete head-on

**They largely don't compete head-on.** AgentMesh is a **team collaboration platform** — its unit of value is coordinating multiple agents and multiple humans around shared tasks, evidence, memory, and risk within a workspace. waku-agent is a **personal assistant framework/teaching codebase** — its unit of value is a single, well-instrumented agent loop that one person runs locally, with best-in-class memory and eval engineering as the selling point. Swapping one for the other would mean AgentMesh users losing multi-agent/multi-user/governance features, or waku-agent users losing the entire "team platform" surface (blackboard, risk inbox, permissions) that doesn't exist in its architecture at all.

**Where they do overlap:**
- Both are LLM-agnostic agent harnesses in Python, with a tool-use loop, pluggable LLM providers, and a memory subsystem backed by SQLite.
- Both explicitly reject heavyweight agent-orchestration frameworks (AgentMesh uses the relatively thin `openai-agents` SDK; waku-agent hand-rolls its own loop) in favor of code that's legible and directly modifiable.
- Both have a "memory that gets reviewed/promoted" concept — AgentMesh's blackboard-to-governed-memory pipeline and waku-agent's consolidation-to-facts pass solve structurally similar problems (turning raw activity into durable, curated memory) at different scales (team-governed vs. single-user-automatic).
- If AgentMesh were to add a "personal assistant" mode for individual contributors, or waku-agent were to grow a multi-agent/multi-user layer, the two would converge — but as they stand today, they answer different questions ("how do a team's agents collaborate and get governed" vs. "how do I build a legible personal agent with excellent memory and eval discipline").

---

## Sources

- `gh api repos/ShenSeanChen/waku-agent` — stars, forks, license, open issues, language, created/pushed dates
- `gh api repos/ShenSeanChen/waku-agent/languages` — language byte breakdown
- `gh api repos/ShenSeanChen/waku-agent/contributors` — contributor list and contribution counts
- `gh api "repos/ShenSeanChen/waku-agent/commits?per_page=8"` — recent commit messages and dates
- `gh api repos/ShenSeanChen/waku-agent/tags` — release tags
- `gh api "repos/ShenSeanChen/waku-agent/pulls?state=open&per_page=100"` — open PR count
- `gh api repos/ShenSeanChen/waku-agent/contents/...` — top-level and subdirectory listings (`waku/`, `evals/`, `docs/`, `.github/workflows/`, `waku/loop/`, `waku/memory/`, `waku/tools/`, `waku/gateway/`, `waku/graph/`, `waku/runtime/`, `waku/ops/`)
- `https://raw.githubusercontent.com/ShenSeanChen/waku-agent/main/README.md` (457 lines, fetched in full)
- `https://raw.githubusercontent.com/ShenSeanChen/waku-agent/main/pyproject.toml` (full contents fetched)
- `https://raw.githubusercontent.com/ShenSeanChen/waku-agent/main/Makefile` (first 60 lines fetched)
- `https://raw.githubusercontent.com/ShenSeanChen/waku-agent/main/waku/loop/agent.py` — line count (114 lines)
- AgentMesh facts: as supplied in task context, spot-verified against `/Users/heyunshen/work/PROJECT/jdc/ai-agentmesh-hackathon/README.md` (540 lines), `pyproject.toml` (`description = "Chat-first team agent platform prototype"`), `tests/` (86 Python test files), `agentmesh-demo/e2e/` (Playwright specs present)
