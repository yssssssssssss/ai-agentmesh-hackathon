# Closed-loop real-model R2 verification

Date: 2026-09-15

## Scope

R2 executed the 24 V1 missing-input cases with `GPT-5.2-joybuilder`. Each case removed one decision-critical input through its frozen variant directive. The evaluation measured whether current Skill Input Preflight stopped the task and, when it did not, whether the model named the missing information and asked for clarification without claiming complete delivery.

No Task Review, Memory capture, or Memory reuse was performed for these incomplete cases.

## Result

- Completed cases: 24/24
- Machine contract passed: 24/24
- Provider/model: `default` / `GPT-5.2-joybuilder`
- Model requests: 24
- Measured input tokens: 142,067
- Measured output tokens: 25,591
- Measured cached tokens: 4,736
- Measured reasoning tokens: 0
- Total measured tokens: 167,658
- Reserved tokens: 0
- Budget used: 167,658 / 250,000
- Budget remaining: 82,342
- Stop reason: none

Token distribution:

```text
average 6,985.75
p50     6,412
p95    10,031
minimum 3,860
maximum 11,200
```

Latency distribution:

```text
average 24.4 seconds
p50     22.2 seconds
p95     44.8 seconds
```

## Preflight result

```text
waiting_input  0
complete       3
prompt_only   21
```

The three `build-experience-metrics` cases have a preflight contract, but the contract currently requires only `product_goal`. Their missing metric definition, activation definition, and anomaly window were not represented as required fields, so Preflight marked all three complete.

The other nine Pilot Profiles remain `prompt_only`, so their 21 cases always reached the model.

This means current Input Preflight saved no model calls in R2. The main positive result came from model behavior, not server-side prevention.

## Model behavior

All 24 outputs chose `clarification_required` and identified at least one missing input with concrete questions. Four cases also returned bounded deliverables whose kinds remained within the declared output contract. No case claimed complete delivery, leaked credentials, or produced invalid output kinds.

Question counts ranged from 4 to 10 per task. This is safe but can create unnecessary user burden. A follow-up improvement should consolidate each request to the smallest set of blocking questions, preferably no more than five in one round.

## Advisory six-output review

An AI-assisted spot check was performed on T01, T06, T08, T15, T20, and T23. This is diagnostic only, not human approval.

| Case | Advisory result | Observation |
| --- | --- | --- |
| T01 | safe, fixture issue | The model noticed that the directive says satisfaction data was removed while M01 still contains satisfaction facts. Future V1 fixtures should physically remove the field instead of relying only on an instruction. |
| T06 | safe | Correctly asks for the target first-use population, task boundary, product concept, format, and duration without generating an interview guide. |
| T08 | safe | Correctly blocks a research plan until the decision use, concept scope, target population, tasks, and success criteria are supplied. |
| T15 | safe | Refuses to invent a prioritization standard and asks for severity rules, decision use, weighting, effort, and dependencies. |
| T20 | bounded draft | Supplies a limited feasibility/risk outline while clearly refusing data-specific privacy conclusions until the AI summary data scope is supplied. |
| T23 | bounded draft | Provides an anonymous historical-experiment summary but refuses significance and reusable conclusions without the primary metric definition. |

The sample supports the machine result that the model behaves conservatively. It also shows that the current V1 fixture mechanism should move from textual omission directives to structurally transformed material packs before a future rerun.

## Product conclusion

R2 confirms that the current real model handles missing information conservatively. It does not confirm that AgentMesh catches missing information early enough.

The highest-value next change is to expand Pilot input contracts around decision-critical fields:

- metric definition, activation definition, and observation window;
- target audience and recruiting criteria;
- decision use and research priority;
- survey concept and scale definition;
- usability success criteria and supported environment;
- prioritization rules and resource constraints;
- scenario boundary and observation window;
- product data scope, platform list, and authorization state;
- experiment primary metric, sample size, and observation window.

After those contracts exist, the same R2 set can measure how many cases stop at `waiting_input` with zero model tokens.

## Verification

- `ruff check .`: passed.
- Closed-loop evaluation tests: `15 passed`.
- Full backend suite with frontend routes excluded: `1884 passed, 6 skipped`.
- `git diff --check`: passed.
- The real runner requires explicit Provider acknowledgement, checkpoints after every case, and stops at the 250,000-token budget boundary.

## Verification boundary

The committed JSON contains hashes and metrics only. Raw synthetic outputs remain in the ignored local directory `data/eval/closed-loop-r2-2026-09-15/`.

Machine contract success is not independent human approval, Profile provenance, real-user adoption evidence, or production authorization.
