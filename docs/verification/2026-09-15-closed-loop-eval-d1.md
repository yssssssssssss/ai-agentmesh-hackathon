# Closed-loop evaluation D1 verification

Date: 2026-09-15

## Scope

D1 executes all 96 versioned synthetic cases through an isolated SQLite database with network access blocked. It uses the Agents SDK `ScriptedModel` only for V0 and V2 cases; missing-input and security cases stop before model execution. It does not call a real model, embedding service, Web, O2, MCP, or data provider.

## Result

- Cases: 96
- Expected-boundary matches: 96
- Failures: 0
- Project Tasks: 96
- Agent Runs: 72
- Sealed Artifacts: 48
- Open input requests: 24
- Synthetic Task Reviews: 9
- Synthetic Memory Reviews: 6
- Memory use receipts: 6
- Fault contracts verified: 8
- ScriptedModel calls: 48
- Provider calls: 0
- p50 case time: 49 ms
- p95 case time: 90 ms
- Full D1 duration: 4.711 seconds inside the runner, approximately 7 seconds including process startup

Boundary distribution:

```text
sealed_artifact   24
input_gap         24
partial_or_gap    24
security_boundary 24
```

## Covered behavior

- Managed Task creation and transition to `in_progress`.
- Immutable Task-linked AgentRun identity.
- `waiting_input` plus durable SkillInputRequest for V1.
- Standard universal sealed Artifact integrity for V0 and V2.
- Six accepted Team Knowledge chains and one Personal Memory capture.
- Six follow-up MemoryUseReceipts with stable citations.
- Two `changes_requested` Task Reviews.
- Prompt-injection and credential-like input rejection.
- Cross-project denial markers and canonical command replay.
- Run claim replay, Artifact replay, Memory capture replay, receipt replay, SQLite reopen, projection rebuild, version conflict, and command replay.

## Verification

- `ruff check .`: passed.
- Focused closed-loop and governance regression: `92 passed`.
- Full backend suite with frontend routes excluded: `1879 passed, 6 skipped`.
- `git diff --check`: passed.
- D1 CLI: 96 cases, 0 failures, 0 Provider calls, 48 ScriptedModel calls.

The full 96-case cold run is well below the 120-second threshold, so CI runs all D1 cases. The 24-case `core_pr` set remains available for local diagnosis only.

This is synthetic engineering evidence. It is not real-model quality evidence, independent human review, Profile approval, or production authorization.
