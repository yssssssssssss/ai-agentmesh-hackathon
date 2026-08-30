# Universal Skill Pool Review Remediation

- Date: 2026-08-30
- Branch: `feature/universal-skill-pool-reviewed-stack`
- Implementation head: `b5139eb`
- Review base: `feature/deepsearch-v1-baseline-stack`
- Status: local review findings remediated; production activation remains blocked

## Remediation

- Pending `standard_plan` dispatches resume in `preview`; `off` remains closed and `approved_plan` still requires `execute`.
- Modal focus no longer resets when an inline close callback changes during a controlled-input render.
- Approved builtin Profiles can graduate beyond the legacy Pilot set; workspace/project Profiles remain explicit-only and legacy retrieval remains Pilot-scoped.
- The Catalog release gate validates canonical `SkillProfileProvenanceV2`, current Profile hashes, review policy, and path-specific CODEOWNER membership. Its positive test uses output from the real provenance builder.
- Candidate Snapshot static identity is checked for every candidate, while dynamic Tool/Grant/readiness checks apply only to selected nodes.
- Standard and DeepSearch responses expose Scenario assignment options. Plan Preview requires explicit selection for ambiguous nodes and drops carried assignments when an optional node is removed.
- DeepSearch Plans with persisted blocking gaps may be approved, but terminal policy returns `PARTIAL` when a safe report exists and `FAILED` otherwise. Such Runs cannot become `COMPLETED`.
- Safe blocked-match reason codes and canonical capability-gap ID/label are stored in the bounded `skill_search_completed` event, projected in Plan and DeepSearch state responses, and rendered separately, including failures before Plan creation. The initial DeepSearch POST returns the persisted failed Run so the client can navigate to the diagnostic state.
- The original combined PR was replaced by the stacked review chain: #10 modal focus, #11 research-v2 retirement, #12 DeepSearch v1 baseline, and #13 Universal orchestration.
- The Catalog release gate now consumes canonical builder output and can graduate all 84 Profiles after real approval while preserving draft and non-builtin fail-closed behavior.

## Validation

- Full backend: `1719 passed, 6 skipped` in `223.84s`; warnings were the existing SWIG deprecations.
- Focused backend review-remediation suite: `181 passed, 6 skipped`; all later targeted regressions passed.
- Frontend unit tests: `164 passed`.
- Playwright: `56 passed`.
- Production frontend build and bundle gate passed.
- Ruff and `git diff --check` passed.
- Final focused reviewer at implementation head `b5139eb`: no remaining P0/P1/P2 findings; merge verdict `OK with notes`.

## External gates

No human reviewer identity, Profile approval, Provider result, holdout result, production soak, deployment attestation, or rollback rehearsal was created by this remediation. Those gates remain tracked by GitHub issues #6 through #9 and continue to block production `preview` and `execute`.
