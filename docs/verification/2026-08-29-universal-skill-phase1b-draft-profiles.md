# Universal Skill Pool — Phase 1B Draft Profile Authoring

- Date: 2026-08-29
- Branch: `feature/universal-skill-pool-phase1a`
- Status: local draft authoring complete; production review and release gates blocked

## Local result

- Built-in Runtime Skills: 84
- Versioned Profile sidecars: 84/84
- Newly authored draft Profiles: 62
- Total generated-import draft Profiles: 74
- Legacy Pilot Profiles retained without execution-field changes: 10
- Effective legacy Planner Profiles: 10
- Production-approved Profiles: 0

Every generated-import Profile is explicitly `review_state: draft` and `planner_eligible: false`. The ten legacy Pilot Profiles retain their existing fields so in-flight and legacy planning behavior is unchanged. Draft Profiles are not submitted to the external-capable vector worker and cannot enter normal Universal search.

The 62 drafts were authored from each checked-in `SKILL.md`. Identity fields are copied from the parsed Skill. Declared Tool references are preserved conservatively, and Skills whose semantics require an unavailable external/file/design adapter declare that dependency rather than being treated as text-only execution. No sync command infers or overwrites capability, safety, risk, or side-effect fields.

## Review roster

`docs/verification/skill-profile-review-roster.yaml` contains one row for every built-in Skill. Because this is a single-maintainer Hackathon, all rows remain `blocked_no_independent_reviewer`; reviewer lists and review dates are empty. High-risk, Tool-using, and write Profiles are marked as requiring two reviewers. This file is scheduling evidence, not an approval or trust root.

`scripts/skill_catalog_report.py --release-gate` fails closed while any Profile is unapproved, the roster is incomplete, `.github/CODEOWNERS` is absent, or Profile provenance schema v2 is unavailable. `scripts/build_skill_profile_provenance.py` can build schema-v2 provenance only from exact reviewed blobs and sufficient independent CODEOWNER identities; it cannot approve a draft or mint deployment attestation. Runtime trust additionally requires an immutable release directory and a matching `verified-build-marker.json`. The ordinary report remains usable for local draft validation and reports `release_gate_eligible: false`.

## Local validation

```text
profile_coverage: 84/84
draft_profiles: 74
legacy_unreviewed_profiles: 10
planner_profiles: 10
schema/hash errors: 0
release_gate_eligible: false
84-Profile example smoke (FTS): Top-1/Top-3/Recall@5 100%, p95 236.802 ms
84-Profile example smoke (fake-vector): Top-1/Top-3/Recall@5 100%, p95 315.869 ms
```

The 252-case Profile example smoke is intentionally marked contaminated because its inputs come from the same sidecars. It validates indexing, distinct identities, deterministic ranking, and latency only; it is not the independently authored and reviewed release holdout.

The following local checks pass:

```bash
PYTHONPATH=. .venv/bin/python scripts/skill_catalog_report.py agentmesh/builtin_skills
PYTHONPATH=. .venv/bin/python eval/run_universal_skill_profile_smoke.py
PYTHONPATH=. .venv/bin/python scripts/sync_wiki_skills.py --check --wiki-root <authorized-wiki-root>
.venv/bin/python -m pytest -q tests/test_wiki_skill_inventory.py
```

## External blockers

The approved production trust contract is intentionally not satisfied:

- no independent CODEOWNER is available;
- high-risk Profiles do not have two distinct reviewers;
- no protected-branch/merge-queue reviewed-blob evidence exists;
- no GitHub wheel attestation or immutable verified-build marker exists;
- no independent frozen release holdout has been reviewed.

Therefore these drafts may be used only by explicitly named offline evaluation interfaces. They do not expand public recommendations, Agent Run candidates, Planner candidates, or executable nodes.
