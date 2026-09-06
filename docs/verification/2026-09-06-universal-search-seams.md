# Universal Skill Search deterministic seams verification

Date: 2026-09-06
Issue: [#14](https://github.com/yssssssssssss/ai-agentmesh-hackathon/issues/14)

## Scope

`UniversalSkillSearchService._search()` is now a small orchestration method over four explicit private stages:

1. `_build_corpus()` loads Profiles and applies built-in source, enablement, binding, review, and trust boundaries.
2. `_assemble_ranked_candidates()` performs the single batch retrieval call, RRF/lexical scoring, relevance thresholds, deterministic ordering, and initial local readiness checks.
3. `_apply_readiness_probes()` schedules the bounded Tool-health probes once and applies timeout, unhealthy, unavailable, and unprobed outcomes.
4. `_assemble_coverage_result()` builds coverage witnesses, capability gaps, selectable/blocked quotas, outcome codes, and the final immutable projection.

The public `search()`, `search_for_evaluation()`, and `search_for_coverage_evaluation()` contracts are unchanged. The Universal service remains separate from `SkillCandidateRetriever`; no Provider call or model rerank was added.

## Regression evidence

- Added focused unit coverage for each extracted stage.
- A fixed two-candidate snapshot generated before and after the extraction has the same canonical content hash:
  - `45c5c610c4f55766eeba79d59d9f4cfa22ed60efbe5b4ff1e2adcfc60f7acd8a`
- Runtime Profile loading still bypasses the coverage-only cache; explicit coverage evaluation retains its bounded cache.

## Verification

- `ruff check .`: passed.
- `pytest tests/test_universal_skill_search.py -q`: `46 passed`.
- Full backend suite with embeddings disabled: `1839 passed, 6 skipped`.
- `scripts/skill_catalog_report.py agentmesh/builtin_skills`: 84 loaded, 84 unique, 84/84 Profile coverage, no errors or warnings.
- Legacy retrieval evaluation: 100% top-3 recall, 0% unavailable/disabled/unauthorized recall, p95 33.194 ms.
- Universal FTS-only calibration: 98.3% top-3, 100% recall@5, 100% compound witness coverage, 100% boundary rejection, p95 44.408 ms.
- Universal fake-vector calibration: 100% top-3, 100% recall@5, 100% compound witness coverage, 100% boundary rejection, p95 48.049 ms.
- 84-Profile FTS-only authoring smoke: 100% top-1/top-3/recall@5, p95 165.094 ms.

This refactor does not change production enablement. Independent Profile review, attestation, real-Provider holdout, and production-shaped rehearsal remain governed by Issues #6–#9.
