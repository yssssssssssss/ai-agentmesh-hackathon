# Research V3 Slice 1 Production-Shaped Integration Gate

Date: 2026-08-21

## Decision

The isolated Slice 1 production-shaped integration gate is **PASS**.

Code verification passed and the user recorded human visual semantic **PASS** on 2026-08-21 for the wide, desktop, and mobile Contact Sheets. Slice 1 is complete and paused at this boundary.

The integrated branch remains unreachable from production. No research-v3 router is mounted, no production `SQLiteStore` or startup migration is changed, no real Provider is called, and research-v2 remains the active production writer.

## Integrated stack

Base:

- `d9d0210a276c796b25d01003e148a55384c5af5f` — isolated Slice 1 actor snapshot binding

Persistence series:

- `69ec80a8a07621dcb0d4b2c20be09a7b563c65c8`
- `6e535c61f6607d905a45a73ad024f615cc1c004f`

Actor adapter series:

- `06c41a174f5b49722e0ead8a988dce7d6e8ea9e5`
- `a9673a3a254c2fd8fc21814ae47fbb0b9da4c38a`
- `d2eeb89d1276f4626b4549a93940536d59514a4b`

API/projection series:

- `06d6830ae727f8ffcb798212c2a4b8557ee39dd9`

Integration adds only the owner-scoped authoritative SQLite projector/API read seam and a test-only router composition.

## Focused gate evidence

Backend research-v3 gate:

```text
python -m pytest -q tests/test_research_v3_*.py
214 passed in 26.51s
```

Frontend Workbench/API-client gate:

```text
vitest run \
  src/features/research-workbench/ResearchWorkbench.test.tsx \
  src/features/research-workbench/apiClient.test.ts
2 files passed; 31 tests passed
```

Integration-glue lint:

```text
ruff check \
  agentmesh/research_orchestration/v3/repository_projector.py \
  tests/test_research_v3_production_shaped_integration.py
All checks passed
```

No full repository test suite, E2E suite, or live Provider smoke was run.

## Recorded technical debt

A diagnostic package-wide Ruff invocation reported 26 pre-existing findings across frozen Foundation and previously approved Slice 1 files. They include import ordering, Python 3.12 generic-style upgrades, simplification suggestions, one unused source-contract import, and one constant-attribute `getattr`. They did not affect the 214 passing research-v3 tests and are non-blocking under the agreed convergence policy. They must not reopen Gate 0 or Foundation; address them only in a later bounded lint-debt package.

## Human visual gate

The user recorded **PASS** on 2026-08-21 after reviewing:

- `/tmp/agentmesh-slice1-visual-review/contact-sheets/wide.png`
- `/tmp/agentmesh-slice1-visual-review/contact-sheets/desktop.png`
- `/tmp/agentmesh-slice1-visual-review/contact-sheets/mobile.png`

The required mobile candidates, DAG, paused, and report right-edge checks were accepted. The signed checklist remains at:

- `/tmp/agentmesh-slice1-visual-review/HUMAN_REVIEW_CHECKLIST.md`

Slice 1 stops here. Gate 2, production wiring, real Providers, and research-v2 cutover remain unauthorized.
