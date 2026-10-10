# Internal Pilot Runbook

Goal: learn whether real users keep coming back, whether governed Memory improves their work, and whether Task delivery closes. The pilot runs one path only (ADR 0053).

## 1. Scope

- 5–10 internal users from one team with real, recurring project work.
- One Workspace, one Project, one FastAPI instance, one SQLite database (current MVP limits).
- Four weeks minimum. Review metrics weekly.
- Not in scope: multi-Skill orchestration (ADR 0010), DeepSearch, Runner, document learning.

## 2. Configure

In the server's `.env`:

```bash
AGENTMESH_PROFILE=pilot
AI_API_URL=<OpenAI-compatible chat completions URL>
AI_API_KEY=<key, never committed>
AI_MODEL=<model id>
AI_API_STYLE=chat_completions
```

Leave `AGENTMESH_DEMO_MODE=0` and remove any explicit `AGENTMESH_AGENT_RUNTIME`, `AGENTMESH_MEMORY_CONTEXT`, `AGENTMESH_TASK_MANAGEMENT`, `AGENTMESH_SKILL_ORCHESTRATION` or `AGENTMESH_AUTOMATION_MODE` lines; explicit values override the profile.

## 3. Verify before inviting users

1. Start the server. Startup must not log `legacy chat runtime is deprecated`.
2. As an admin, open `GET /api/health/providers`. The `openai_agents_sdk` entry must show `config_profile: "pilot"`, `ready: true`, `memory_context_mode: "inject"`, `task_management_mode: "write"`, `skill_orchestration_mode: "off"`.
3. Send one chat message and one Task-linked Run end to end with a pilot user account.

## 4. Measure

Run weekly against the live database (read-only, safe while the server runs):

```bash
.venv/bin/python scripts/pilot_metrics.py --days 7
```

| Metric | Meaning | Healthy by week 4 |
| --- | --- | --- |
| `users.active` / `users.returning` | Users with a chat message; users active on 2+ days | Returning ≥ 60% of invited users |
| `memory.reach` | Share of Runs that received governed Memory | Rising week over week |
| `memory.acceptance` | Accepted / decided Team Memory candidates | ≥ 50% |
| `tasks.delivery` | Accepted / decided Task Reviews | ≥ 60% |

`null` means no decisions yet, not zero. Pair the numbers with a short weekly conversation with two or three users: what did they come back for, and what did they work around.

## 5. Decide

At the end of week 4, use the numbers to decide what to keep:

- Returning users low: the product loop does not hold. Fix the core chat-to-delivery path before adding anything.
- Memory reach high but acceptance low: retrieval surfaces the wrong things; tune candidates before expanding Memory features.
- Task delivery low: inspect `changes_requested` reasons before building more Task automation.
- Modules nobody touched during the pilot (for example Market or Collaboration graph) are candidates for archiving.
- If the ADR 0053 criteria hold, schedule removal of the legacy chat runtime.
