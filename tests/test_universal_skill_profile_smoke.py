from __future__ import annotations

from eval.run_universal_skill_profile_smoke import (
    EXPECTED_CASES,
    EXPECTED_SKILLS,
    P95_MAX_MS,
    SmokeResult,
    evaluate,
    render,
)


def test_all_draft_profiles_pass_the_explicit_example_smoke_gate() -> None:
    results = evaluate(fake_vector=False)
    # Latency is gated by the standalone CI smoke step; a loaded pytest worker would make it flaky.
    report, passed = render(results, mode="fts-only", enforce_latency=False)

    assert len(results) == EXPECTED_CASES
    assert len({result.skill_name for result in results}) == EXPECTED_SKILLS
    assert passed, report


def _synthetic_results(*, latency_ms: float, hit: bool = True) -> list[SmokeResult]:
    results = []
    for index in range(EXPECTED_CASES):
        skill = f"skill_{index % EXPECTED_SKILLS}"
        candidates = (skill,) if hit else ("other",)
        results.append(SmokeResult(skill_name=skill, query=f"q{index}", candidates=candidates, latency_ms=latency_ms))
    return results


def test_render_enforces_latency_gate_by_default() -> None:
    _, passed = render(_synthetic_results(latency_ms=P95_MAX_MS + 1), mode="fts-only")

    assert not passed


def test_render_can_skip_latency_gate_without_skipping_quality() -> None:
    _, slow_passed = render(_synthetic_results(latency_ms=P95_MAX_MS + 1), mode="fts-only", enforce_latency=False)
    report, miss_passed = render(_synthetic_results(latency_ms=1, hit=False), mode="fts-only", enforce_latency=False)

    assert slow_passed
    assert not miss_passed
    assert "not enforced" in report
