---
status: accepted
---

# Pilot profile and legacy chat runtime deprecation

Out of the box AgentMesh runs the legacy chat path: `AGENTMESH_AGENT_RUNTIME=legacy`, Memory context `off`, Task Center `read_only`. The governed capabilities built since August are only reachable by setting several flags by hand, and two chat runtimes coexist. An internal pilot needs one path that real users exercise and that the evaluation measures.

## Decision

- `AGENTMESH_PROFILE` names a group of flag defaults (`agentmesh/profiles.py`). An explicitly set variable always wins. With no profile every default is unchanged, so existing deployments keep their behaviour.
- `pilot` sets: SDK runtime `v2`, Memory context `inject`, Task management `write`, project inspections `observe`, Skill orchestration `off`.
- Orchestration stays `off` because ADR 0010 blocks production `preview`/`execute` until its gates pass. Memory and Task settings match the closed-loop evaluation; a test fails if the two drift.
- An unknown profile name stops application startup; at runtime it falls back to defaults.
- `/api/health/providers` reports `config_profile` so operators can confirm what is active.
- The legacy chat runtime is deprecated. Startup logs a warning while it is active. The default stays `legacy` until removal so no deployment changes silently.

## Legacy removal criteria

Remove the legacy chat path in `agents.py` and make `v2` the only runtime when all of these hold:

1. The pilot has run on the `pilot` profile for at least four weeks with real users.
2. No open P0/P1 issue is attributed to the SDK runtime path.
3. The full backend suite passes with `AGENTMESH_PROFILE=pilot`.

Target date for the removal decision: 2026-12-01.

## Consequences

- `.env.example` documents `AGENTMESH_PROFILE` and comments out the profile-covered flags, because a copied explicit value would silently override the profile.
- `scripts/pilot_metrics.py` reads the database read-only and reports active and returning users, Memory reach and acceptance, and Task delivery (`docs/runbooks/internal-pilot.md`).
- New profiles must stay a short list of flag defaults; per-feature tuning keeps using its own variable.
