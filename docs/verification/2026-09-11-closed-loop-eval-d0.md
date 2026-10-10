# Closed-loop evaluation D0 verification

Date: 2026-09-11

## Scope

D0 adds the versioned, synthetic input contract for the approved closed-loop model evaluation plan. It does not create Agent Runs or call a model, embedding service, Web, O2, MCP, or data provider.

The dataset contains:

- 24 base tasks across the 10 currently executable Pilot Profiles.
- 8 synthetic material packs.
- 4 variants per task and 96 stable case identities.
- 6 bounded Team Knowledge reuse chains.
- 1 Personal Memory case and 2 `changes_requested` cases.
- 8 targeted fault-injection cases.
- 24 stable `core_pr` cases.
- Exact Task Catalog v1/v2 and Profile content identities.

Dataset identity:

```text
32e380502771845bed7408e4456590257547fa5d93fa9f6522ab40fb32d50aa9
```

## Validation behavior

`python -m eval.run_closed_loop_eval --mode validate --batch D0` fails closed when:

- the manifest or task-file hash changes;
- the 24 by 4 case matrix is incomplete or duplicated;
- a material, task, review, reuse, fault, or `core_pr` reference is invalid;
- Catalog identity, Scenario identity, Pilot Profile identity, eligibility, or output support drifts;
- a rendered case exceeds the 6,000-token conservative preflight bound;
- fixture text contains a recognized credential or private-key pattern.

The CLI emits a deterministic JSON summary and reports `provider_calls=0`.

## Verification

- `ruff check .`: passed.
- `pytest tests/test_closed_loop_eval.py -q`: `8 passed`.
- Focused D0, input-preflight, Catalog, and Universal search regression: `102 passed`.
- Full backend suite with frontend routes excluded: `1869 passed, 6 skipped`.
- D0 CLI: 24 tasks, 96 cases, 8 material packs, 10 Profiles, 11 Scenarios, no diagnostics, no Provider calls.
- `git diff --check`: passed.

The CI backend job now runs D0 validation before retrieval evaluations. This evidence is synthetic engineering validation and is not independent human approval, production attestation, or real-user observation.
