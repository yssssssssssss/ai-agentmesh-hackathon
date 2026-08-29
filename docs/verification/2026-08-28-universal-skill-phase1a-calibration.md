# Universal Skill Pool — Phase 1A Offline Retrieval Calibration

- Date: 2026-08-28
- Branch: `feature/universal-skill-pool-phase1a`
- Parent gate: `130c1c3` (`Validate universal orchestration Phase 0`)
- Status: first offline retrieval vertical slice passed; no production Planner or public recommendation cutover

## Scope

This slice validates the Profile schema and retrieval discrimination before authoring the remaining Profiles:

- retained the ten legacy Pilot Profiles and their existing execution fields;
- added twelve complete `review_state=draft`, `planner_eligible=false` Profiles for adjacent research/analysis capabilities;
- added a read-only `UniversalSkillSearchService` that can inspect drafts only when the caller explicitly requests offline evaluation;
- kept `SkillCandidateRetriever`, Agent Run creation, Plan Preview, Standard execution, and DeepSearch execution on the legacy ten-Skill path;
- added strict sidecar and capability-card size/cardinality limits;
- added a versioned deterministic retrieval policy and calibration runner;
- added immutable Task Catalog v2 assets with structured Scenario output IDs and reviewed output-kind mappings while preserving the exact v1 tree and default loader.

The twelve draft Skills are:

```text
analyze-satisfaction
conversion-funnel-analysis
design-abtest-analysis
feature-adoption-analysis
feedback-insight
generate-persona
industry-market-analysis
journey-map
research-screenshot-analyzer
structure-interview-transcript
synthesize-qualitative-insights
usability-review
```

## Trust boundary

Draft Profiles are loaded into the local SQLite FTS index but remain runtime planner-ineligible and are never queued for the external-capable vector worker. The Universal search module excludes them from `search()`; only the explicitly offline `search_for_evaluation()` interface returns them as `ready=false` blocked matches. Existing public recommendation and Agent Run paths are unchanged. LLM directory reranking receives Profile fields only when the persisted Profile is already planner-eligible.

## Profile limits

- sidecar UTF-8 bytes: at most 32 KiB;
- canonical Profile JSON: at most 32 KiB;
- lifecycle tags: at most 8;
- input/output/capability/task/archetype/tool/resource lists: at most 20;
- positive and negative examples: at most 8;
- ordinary values: at most 120 Unicode code points;
- resource/schema references: at most 240 code points;
- examples: at most 300 code points;
- public capability card: at most 4 KiB and excludes instructions and resource identities.

## Calibration asset

- Dataset: `eval/universal_skill_retrieval_calibration_v1.json`
- Dataset SHA-256: `d965ca93cae3f1985b33714df4b0f0bf4e52345acf1699fc45f0ed2eb85d8954`
- Partition: calibration, not release holdout
- Cases: 60 single-intent cases (five independently written cases for each draft Skill), 6 compound cases, and 6 out-of-domain boundary cases
- Languages: Chinese, English, and mixed Chinese/English
- Retrieval policy: `universal-profile-rrf-v1`

The policy uses one canonical positive Profile projection for FTS, direct lexical scoring, and fake-vector scoring; a `0.4` vector-similarity floor; deterministic lexical and positive-example evidence; strong negative-example penalties; a `0.6` minimum relevance score; and stable score/match/Skill-ID ordering. Generic legacy intent kinds are not promoted to query atoms in this slice because the Universal canonicalizer is not yet implemented.

## Result

```text
Universal Skill retrieval calibration
fts-only:    Top-1 91.7%, Top-3 98.3%, Recall@5 100.0%, compound coverage 100.0%, boundary rejection 100.0%, p95 39.257 ms
fake-vector: Top-1 93.3%, Top-3 100.0%, Recall@5 100.0%, compound coverage 100.0%, boundary rejection 100.0%, p95 62.650 ms
family[behavior-metrics]: 15/15 in both modes
family[design-review]: 5/5 in both modes
family[experiment-analysis]: 5/5 in both modes
family[market-research]: 5/5 in both modes
family[qualitative-research]: 25/25 in both modes
family[visual-research]: 5/5 in both modes
language[en]: 5/5 in both modes
language[mixed]: 7/7 in both modes
language[zh]: 48/48 in both modes
PASS
```

The unchanged legacy gate also passed at Top-3 recall 100%, p95 31.839 ms, with unavailable/disabled/unauthorized recall all 0%. The full backend suite passed with `1569 passed, 6 skipped`; Ruff passed for the repository. The React unit suite passed with `161 passed`, the production build passed its 500 KiB bundle gate, and `tests/test_frontend_routes.py` passed with `6 passed`.

## Task Catalog v2 compatibility

- Legacy `user-research-v1` catalog hash remains `480d88f8f9d11c0f24bcff7ecb6f2a333d5852391bb80ee2de9217b81b6b9629`.
- Its 13-file tree digest remains `8d3527fb655ccee85a04f2b4f561c794bb4e3ea665d2eb521d8381a772ff799b`.
- New `user-research-v2` catalog hash is `0817f656eaf2781ce6b5d8510e33b95fd0aa2a1d3e8d1bc00dfb9711a88ebdd7`.
- V2 contains 15 Scenarios and 61 structured outputs. Labels and order match v1; IDs and `compatible_output_kinds` are machine contracts.
- The loader dispatches v1/v2 models from the manifest and resolves only exact version/hash identities. `load_default_task_catalog()` remains pinned to v1 in Phase 1A.
- Published version directories are create-only: rebuild is accepted only when every path and byte is identical.
- A built and isolated wheel check loaded both identities through `importlib.resources` (13 files per version).

## Reproduce

```bash
PYTHONPATH=. .venv/bin/python eval/run_universal_skill_retrieval_eval.py
PYTHONPATH=. AGENTMESH_EMBEDDING_ENABLED=false \
  .venv/bin/python eval/run_skill_retrieval_eval.py
.venv/bin/python scripts/skill_catalog_report.py agentmesh/builtin_skills
.venv/bin/python -m pytest tests/test_universal_skill_search.py \
  tests/test_universal_skill_retrieval_eval.py \
  tests/test_skill_recommendations.py \
  tests/test_skill_matches.py
```

## Remaining Phase 1A work

Batch production embedding, Tool-health probe budgeting, coverage atoms/witness selection, production trust/provenance enforcement, and the full 84-Profile authoring/review flow remain outside this first vertical slice. The create-only `--generate-profile-stubs` command now exists but intentionally emits identity-only, incomplete drafts so it never guesses capability or safety fields. Production recommendation exposure remains blocked by the solo-maintainer review and release-topology gates recorded in the Phase 0 report.
