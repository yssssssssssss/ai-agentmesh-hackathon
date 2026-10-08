# S0/T01 — Project and legacy memory read visibility

Date: 2026-10-08  
Baseline: `fed741b029858adca735169f186cb604b7a84499`  
Delivery: [PR #44](https://github.com/yssssssssssss/ai-agentmesh-hackathon/pull/44)  
Branch: `fix/s0-t01-read-visibility`

## Purpose and scope

This is the first bounded implementation slice of the 2026-10-08 development plan. It closes inconsistent read authorization on four existing HTTP endpoints without changing database schemas, response shapes, role definitions, or task/review contracts.

| Endpoint | Implementation |
| --- | --- |
| `GET /api/projects` | Resolve the authenticated workspace, reject another workspace filter with 404, and filter projects through `user_can_access_project`. |
| `GET /api/projects/{project_id}` | Reuse `require_read_model_project`, also used by the existing activity read model. Missing, foreign-workspace, and inaccessible projects share the same 404 response. |
| `GET /api/memory` | Keep project resolution, and delegate item authorization to `memory_item_visible_to_user`. |
| `GET /api/memory/overview` | Apply the same predicate to Team items and derive counts from the filtered items. |

The route-local memory policy duplication is removed. Canonical policy methods in `store.py` remain unchanged.

## Compatibility constraints

- Projects with empty `member_ids` retain the existing legacy behavior within the authenticated workspace.
- Admin and team-lead roles still require membership for restricted projects.
- Existing admin/team-lead Team-memory visibility is preserved; another user's private memory stays hidden.
- Candidate-memory visibility follows the existing canonical owner, reviewer-permission, and Team rules.
- Membership changes are read on subsequent requests. The project-revocation regression reopens the same SQLite database and checks that the restriction survives.
- Natural chat, explicit `$` commands, model calls, daily-summary scheduling, and knowledge acceptance are unchanged.

This slice does not add multi-workspace support or claim a full tenancy audit. Workspace administration endpoints, user onboarding, marketplace lifecycle filters, collaboration request/answer identities, adoption idempotency, frontend settings, and production release gates remain separate work.

## Regression suite

`tests/test_read_visibility.py` adds **34 parameterized HTTP cases**. They use real FastAPI routers and temporary SQLite stores, with authentication overridden to focus on authorization. They do not call Providers, run application workers, or use a production database.

Coverage includes project list/detail consistency; ordinary user, team-lead and admin behavior; foreign workspace filters; legacy projects; private and candidate memory; Team isolation; filtered overview counts; Team membership changes; and project revocation after database reopen.

The focused workflow also runs the 15 existing project-member, Team-isolation, and read-model tests: **49 cases total**.

```bash
.venv/bin/ruff check tests/test_read_visibility.py agentmesh/routes/workspace.py agentmesh/routes/memory.py
.venv/bin/python -m pytest -q \
  tests/test_read_visibility.py \
  tests/test_project_member_access.py \
  tests/test_team_isolation.py \
  tests/test_read_models.py
```

## Observed test-first evidence

Before changing either production route, the tests were committed as `cc2e74c6ad4b2697edec306f356eadd70f0c68aa`; the workflow-only follow-up was `f1e37e318ad5039ff1b7b15af5e00e56fcb21881`.

[Baseline run 37760703681](https://github.com/yssssssssssss/ai-agentmesh-hackathon/actions/runs/37760703681), job `113256121623`, ran against merge ref `b8889c41134f6330c6bdbe26ff0b0cf7ef3bfcb0` and reported:

```text
Ruff: All checks passed!
pytest: 21 failed, 28 passed in 9.40s
Exit code: 1
```

All 21 failures came from the new HTTP regression file. The 15 existing tests passed. Failures demonstrated unauthorized project metadata being returned, unauthorized workspace filtering, other-Team accepted memory in both legacy views, and project metadata remaining readable after membership revocation. These were assertion failures, not test-collection or fixture errors.

## Acceptance and reporting

The final head must pass the focused suite and the repository's existing CI checks: backend/Ruff/evaluation, frontend types/tests/build, Core Playwright flows, and secret scanning. Inspect the head SHA and run IDs together; a green run from an earlier commit does not establish the final head's status. Final observed results are recorded in the PR description/comments so that reporting a completed run does not itself invalidate that run with another code commit.

The chat container could not directly clone the repository. Full-repository checks are executed by GitHub Actions, not claimed as local runs. Database reopen is tested in-process; this is not evidence of multi-process high availability, real-provider quality, or a deployment rehearsal.

## Local verification and release boundary

Save any local uncommitted work first, then fetch and check out this branch in a development environment. Use an isolated test database for manual authorization checks. No new environment variables or data migration are required.

Do not merge this PR until the final checks and review are complete. No production capability flags, branch protection, required checks, or deployment settings are changed. Rolling back the route changes would restore the original exposure; use a forward fix or restrict access if a regression is found.
