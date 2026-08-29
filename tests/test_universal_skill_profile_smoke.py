from __future__ import annotations

from eval.run_universal_skill_profile_smoke import EXPECTED_CASES, EXPECTED_SKILLS, evaluate, render


def test_all_draft_profiles_pass_the_explicit_example_smoke_gate() -> None:
    results = evaluate(fake_vector=False)
    report, passed = render(results, mode="fts-only")

    assert len(results) == EXPECTED_CASES
    assert len({result.skill_name for result in results}) == EXPECTED_SKILLS
    assert passed, report
