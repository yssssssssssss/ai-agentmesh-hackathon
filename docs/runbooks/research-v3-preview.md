# Research V3 Gate 2 Preview Runbook

## Status and boundary

Research-v3 preview composition exists in code but remains dormant under production-safe defaults:

```text
AGENTMESH_SKILL_ORCHESTRATION=off
AGENTMESH_RESEARCH_PREVIEW_ALLOWLIST=
research_writer_control.active_generation=research-v2
research_writer_control.generation_epoch=1
```

Do not change the production `research_writer_control` row. Gate 2 does not authorize production research-v3 Runs, real Provider calls, research-v2 retirement, deployment, or cutover.

## What preview can do

For an isolated database whose writer control has been deliberately advanced to research-v3, an allowlisted synthetic user can:

- create one research-v3 Run through `POST /api/agent/runs`;
- clarify a blocked Requirement;
- inspect depth and speed candidates;
- select or revise a Plan;
- confirm a Plan;
- restore the authoritative projection through GET, refresh, or SSE;
- cancel or purge preview state.

Preview rejects approval, execute, retry, skip, and abort commands with `409`. The preview composition does not construct or call Tool, Skill, LLM, or Reviewer adapters.

## Disposable local rehearsal

Use only a disposable database. The following IDs are synthetic and must not be replaced with production users:

```bash
export GATE2_DB=/tmp/agentmesh-gate2-preview.sqlite3
rm -f "$GATE2_DB" "$GATE2_DB-wal" "$GATE2_DB-shm"

AGENTMESH_DB_PATH="$GATE2_DB" .venv/bin/python - <<'PY'
from agentmesh.research_orchestration.current import ResearchWriterGeneration
from agentmesh.store import SQLiteStore

store = SQLiteStore('/tmp/agentmesh-gate2-preview.sqlite3')
control = store.compare_and_swap_research_writer_control(
    expected_generation=ResearchWriterGeneration.V2,
    expected_generation_epoch=1,
    target_generation=ResearchWriterGeneration.V3,
    decision_receipt_hash='f' * 64,
)
print(control.model_dump(mode='json'))
PY
```

Start the isolated backend:

```bash
AGENTMESH_DB_PATH="$GATE2_DB" \
AGENTMESH_DEMO_MODE=1 \
AGENTMESH_AGENT_RUNTIME=v2 \
AGENTMESH_SKILL_ORCHESTRATION=preview \
AGENTMESH_RESEARCH_PREVIEW_ALLOWLIST=usr_current_designer \
.venv/bin/python -m uvicorn agentmesh.app:app --port 8022
```

Start the frontend separately:

```bash
AGENTMESH_API_PROXY=http://127.0.0.1:8022 \
npm --prefix agentmesh-demo run dev -- --port 5182 --strictPort
```

Open `http://127.0.0.1:5182`, use the local demo account `usr_current_designer`, and submit:

```text
帮我做竞品分析
```

Expected sequence:

1. Workbench shows the preview-only notice and clarification state.
2. Answer `Alpha, Beta`.
3. Workbench shows depth and speed candidates.
4. Select one candidate.
5. Workbench shows a confirmable Plan.
6. No `开始执行` action is present.
7. The document has no horizontal overflow at a desktop viewport.

## Verify durable state

```bash
AGENTMESH_DB_PATH="$GATE2_DB" .venv/bin/python - <<'PY'
from agentmesh.store import SQLiteStore

store = SQLiteStore('/tmp/agentmesh-gate2-preview.sqlite3')
control = store.get_research_writer_control()
runs = [run for run in store.list_agent_runs() if run.orchestration_version == 'research-v3']
print({
    'active_generation': control.active_generation,
    'generation_epoch': control.generation_epoch,
    'v3_run_count': len(runs),
    'provider_execution_allowed': False,
})
PY
```

Restart the backend against the same disposable database and confirm that the same Run and projection remain readable.

## Off rollback rehearsal

Stop the isolated backend and restart it with:

```bash
AGENTMESH_DB_PATH="$GATE2_DB" \
AGENTMESH_DEMO_MODE=1 \
AGENTMESH_AGENT_RUNTIME=v2 \
AGENTMESH_SKILL_ORCHESTRATION=off \
AGENTMESH_RESEARCH_PREVIEW_ALLOWLIST= \
.venv/bin/python -m uvicorn agentmesh.app:app --port 8022
```

Expected behavior:

- no new versioned research workflow or claim is created;
- existing v2/v3 records remain readable by stored version;
- the control row remains research-v3 in the disposable rehearsal database;
- research-v2 writing is not re-enabled;
- no database downgrade or content deletion occurs.

Delete the disposable database after the rehearsal:

```bash
rm -f "$GATE2_DB" "$GATE2_DB-wal" "$GATE2_DB-shm"
```

## Stale-writer fence

The SQLite `research_writer_generation_fence` trigger rejects a stale research-v2 process that attempts to insert a new research-v2 AgentRun after the control row has advanced to research-v3. Application code also checks generation and epoch inside the creation transaction. Client-turn replay is checked first and continues returning the original persisted version.

## Failure interpretation

| Signal | Meaning | Action |
| --- | --- | --- |
| `Research-v3 execution is not authorized` | Gate 2 received execute mode | Restore `preview` or `off`; do not bypass |
| `research writer generation changed before Run creation` | Process used a stale epoch | Restart the process; do not retry with another writer |
| `research writer generation fenced` | SQLite blocked a stale writer | Stop the stale process |
| `Research-v3 preview Runtime is unavailable` | Dormant composition is absent | Fail closed; do not route to v2/v1 as fallback |
| `409` from approval/execute/recovery | Expected preview boundary | Do not enable Actor adapters |

## Production-cutover blockers

Before any production control-row change, a separate proposal must provide:

- distinct `AM-ARCH` and `AM-RELEASE-QA` reviewers;
- full release-candidate test, lint, build, E2E, catalog, and eval evidence;
- closure of the recorded lint debt;
- real Provider smoke in isolated/staging infrastructure;
- independent researcher review;
- named pilot users and stop conditions;
- an atomic cutover receipt bound to the reviewed commit and tree.
