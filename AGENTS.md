# Repository Guidelines

## Project Structure & Module Organization

AgentMesh is a Python 3.12+ FastAPI prototype. Core backend code lives in `agentmesh/`. Route handlers are under `agentmesh/routes/`, domain models are in `agentmesh/models.py`, persistence is in `agentmesh/store.py`, seed data is in `agentmesh/seed.py`, and agent/tool integrations are split across files such as `agents.py`, `tools.py`, `o2.py`, and `web_research.py`. The current frontend is the React/Vite app in `agentmesh-demo/`; root `app.html` is the legacy fallback during migration. Tests live in `tests/`; evaluation helpers live in `eval/`; ADRs and planning docs live in `docs/`. Runtime SQLite data is stored under `data/` and should not be committed.

## Build, Test, and Development Commands

Create and install the local environment:

```bash
/opt/homebrew/bin/python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

Install frontend dependencies:

```bash
npm --prefix agentmesh-demo install
```

Run the backend and current React frontend in separate terminals:

```bash
.venv/bin/uvicorn agentmesh.app:app --reload --port 8010
npm --prefix agentmesh-demo run dev -- --port 5178 --strictPort
```

Open `http://127.0.0.1:5178`. Vite proxies `/api` to `8010`; the legacy static page remains at `http://127.0.0.1:8010/app.html`. If a port is busy, inspect it with `lsof -nP -iTCP:<port> -sTCP:LISTEN` before starting another process.

Run tests and lint:

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
```

## Coding Style & Naming Conventions

Use 4-space indentation, type hints, and small functions with direct control flow. Prefer Pydantic models for structured data and keep route behavior thin: validation, authorization, then delegation. Follow existing names: `snake_case` for functions/modules, `PascalCase` for models/classes, and `test_*` for tests. Ruff is configured in `pyproject.toml` with line length `120`, import sorting, bugbear, pyupgrade, and simplification rules.

## Testing Guidelines

Use pytest. Add or update tests for every behavior change, especially auth, permissions, routing, persistence, and agent workflows. Keep tests deterministic; do not call real LLM, OAuth, O2, or web services unless explicitly mocked. The test bootstrap uses isolated temp SQLite databases, so avoid relying on `data/agentmesh.sqlite3`.

## Commit & Pull Request Guidelines

Recent commits use short imperative summaries such as `Add OAuth login adapter` or `Add permission policy rules`. Keep commits focused and describe the user-visible behavior changed. PRs should include a concise summary, linked issue or plan when applicable, test results, and screenshots only for UI changes.

## Security & Configuration Tips

Never commit `.env`, OAuth secrets, API keys, or local SQLite databases. Use `.env.example` for documented variables. Natural chat is private by default; preserve the explicit `$` skill behavior when changing chat or agent flows.

## Agent skills

### Issue tracker

Issues live in GitHub Issues (`gh` CLI); repo is `yssssssssssss/ai-agentmesh-hackathon` (`https://github.com/yssssssssssss/ai-agentmesh-hackathon.git`). See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `CONTEXT.md` + `docs/adr/`. See `docs/agents/domain.md`.
