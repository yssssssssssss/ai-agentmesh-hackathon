# Closed-loop real-model R1 verification

Date: 2026-09-15

## Scope

R1 executed the 24 V0 synthetic tasks with the configured real model `GPT-5.2-joybuilder`. The 22 Standard cases used one structured model call each. T04 and T05 used a bounded three-stage real-model pipeline over frozen synthetic evidence to measure DeepSearch-shaped planning, evidence analysis, and synthesis costs without invoking Web, O2, MCP, or production data.

The run did not execute the production durable DeepSearch state machine. D1 and the existing DeepSearch test suite remain the engineering evidence for that state machine.

## Result

- Completed cases: 24/24
- Machine contract passed: 24/24
- Provider/model: `default` / `GPT-5.2-joybuilder`
- Measured requests: 28
- Measured input tokens: 172,219
- Measured output tokens: 116,695
- Measured cached tokens: 3,328
- Measured reasoning tokens: 0
- Measured successful-task tokens: 288,914
- Conservative reserve for preflight and failed attempts: 60,000
- Budget used for the 500,000-token gate: 348,914
- Budget remaining: 151,086
- Stop reason: none

Token distribution per completed task:

```text
average 12,038
p50     11,869.5
p95     18,966
minimum  4,987
maximum 20,471
```

Latency distribution:

```text
average 76.9 seconds
p50     73.3 seconds
p95    116.4 seconds
minimum 24.1 seconds
maximum 130.6 seconds
```

## Standard versus DeepSearch-shaped

```text
Standard cases: 22
Standard measured tokens: 249,477
Standard median: 11,599.5
Standard maximum: 18,515

DeepSearch-shaped cases: 2
DeepSearch-shaped measured tokens: 39,437
DeepSearch-shaped median: 19,718.5
DeepSearch-shaped maximum: 20,471
```

## Profile totals

| Profile | Cases | Measured tokens |
| --- | ---: | ---: |
| `build-experience-metrics` | 3 | 39,985 |
| `competitive-analysis` | 2 | 39,437 |
| `generate-interview-guide` | 2 | 20,961 |
| `generate-research-plan` | 3 | 28,350 |
| `generate-survey` | 2 | 20,553 |
| `generate-usability-test` | 2 | 24,697 |
| `issue-prioritization` | 3 | 40,802 |
| `jobs-to-be-done` | 2 | 27,706 |
| `prd-feasibility` | 3 | 36,441 |
| `query-experiment-conclusions` | 2 | 9,982 |

## Advisory six-output review

An AI-assisted spot check was performed on T01, T04, T08, T13, T18, and T22. This is diagnostic only, not human approval.

| Case | Advisory result | Observation |
| --- | --- | --- |
| T01 | usable draft | Defines a metric tree, event plan, segments, baselines, guardrails, and owners. |
| T04 | usable draft | Keeps the three fictional competitors and Source IDs separate and states evidence limitations. |
| T08 | conditional | Produces both required deliverables but intentionally stops short of sampling and scheduling because decision use and recruiting criteria are missing. |
| T13 | usable draft | Provides executable usability tasks and accessibility observations while refusing to invent unavailable canonical scales. |
| T18 | usable draft | Separates functional, emotional, and social jobs and preserves assumptions; `[T1]` reuse is visible. |
| T22 | usable draft | Recommends an internal-only degraded path while correctly blocking public release before external-data authorization. |

The sample suggests that the model is strong at structured drafts and explicit limitations. It also shows that V0 fixtures can still trigger legitimate input caveats; machine contract success must not be read as independent acceptance of every recommendation.

## Findings and remediation

The first direct-runtime canary exposed a real resource-read failure: the model attempted to exceed the cumulative 12-path Standard Skill resource limit, and the Tool raised a fatal exception. The Tool now returns a settled, model-visible `standard_resource_path_limit_exceeded` result so the model can continue without expanding access. The existing 12-path cap remains unchanged.

Two early DeepSearch-shaped structured attempts returned unusable structured output. The evaluation pipeline now uses plain text for the planning and evidence stages and reserves structured validation for the final deliverable. Unknown usage from these probes is covered by the 60,000-token conservative reserve.

One valid JTBD result was initially flagged because the substring `tbd` appears inside `jtbd`. Placeholder detection now uses word boundaries. Revalidation changed that case to passed without another model call.

## Verification

- `ruff check .`: passed.
- Focused closed-loop and Skill resource regression: `39 passed`.
- Full backend suite with frontend routes excluded: `1882 passed, 6 skipped`.
- `git diff --check`: passed.
- The real runner requires `--ack-real-provider`, refuses `CI=true`, checkpoints after each task, and stops at the configured budget boundary.

## Evidence boundary

The 24 outputs contain synthetic materials only and are retained under the local ignored evaluation directory. This report contains hashes and metrics, not output content or credentials.

All results passed machine-checkable structure, output-kind, minimum-content, credential, placeholder, and six `[T1]` citation checks. This is not independent human quality approval, real-user adoption evidence, Profile provenance, or production authorization.
