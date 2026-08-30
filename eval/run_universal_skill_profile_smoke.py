#!/usr/bin/env python3
"""Deterministic 84-Profile authoring smoke; this is not a release holdout."""

from __future__ import annotations

import argparse
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import quantiles

from agentmesh.models import SkillIntent
from agentmesh.seed import USER
from agentmesh.skill_runtime.profiles import load_capability_profile_record
from agentmesh.skill_runtime.recommendation import UniversalSkillSearchService
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore
from agentmesh.tools import ensure_tool_seed_data
from eval.run_universal_skill_retrieval_eval import (
    _FakeVectorRanker,
    _prepare_evaluation_tools,
    offline_environment,
)

EXPECTED_SKILLS = 84
EXPECTED_CASES = 252
TOP_3_MIN = 0.90
RECALL_AT_5_MIN = 0.95
P95_MAX_MS = 500.0


@dataclass(frozen=True, slots=True)
class SmokeResult:
    skill_name: str
    query: str
    candidates: tuple[str, ...]
    latency_ms: float


def evaluate(*, fake_vector: bool) -> list[SmokeResult]:
    with offline_environment(), tempfile.TemporaryDirectory(prefix="agentmesh-profile-smoke-") as directory:
        repository = SQLiteStore(Path(directory) / "profile-smoke.sqlite3")
        ensure_tool_seed_data(repository, granted_by="profile-smoke")
        catalog = SkillCatalogService(repository)
        catalog.reload()
        if len(catalog.list_for_agent(USER.personal_agent_id)) != EXPECTED_SKILLS:
            raise RuntimeError("profile_smoke_skill_count_invalid")
        search = UniversalSkillSearchService(
            repository,
            catalog,
            profile_ranker=_FakeVectorRanker(repository) if fake_vector else None,
            tool_health=_prepare_evaluation_tools(repository),
        )
        results: list[SmokeResult] = []
        for skill, _enabled in catalog.list_for_agent(USER.personal_agent_id):
            profile = load_capability_profile_record(skill).profile
            if len(profile.examples) < 3 or not profile.output_kinds:
                raise RuntimeError(f"profile_smoke_fixture_incomplete:{skill.name}")
            for query in profile.examples[:3]:
                started = time.perf_counter()
                outcome = search.search_for_coverage_evaluation(
                    USER,
                    SkillIntent(goal=query, deliverables=[profile.output_kinds[0]]),
                )
                results.append(
                    SmokeResult(
                        skill_name=skill.name,
                        query=query,
                        candidates=tuple(candidate.skill_name for candidate in outcome.ranked_matches),
                        latency_ms=(time.perf_counter() - started) * 1000,
                    )
                )
        return results


def render(results: list[SmokeResult], *, mode: str) -> tuple[str, bool]:
    if len(results) != EXPECTED_CASES:
        raise RuntimeError("profile_smoke_case_count_invalid")
    top1 = sum(result.skill_name in result.candidates[:1] for result in results) / len(results)
    top3 = sum(result.skill_name in result.candidates[:3] for result in results) / len(results)
    recall5 = sum(result.skill_name in result.candidates[:5] for result in results) / len(results)
    p95 = quantiles([result.latency_ms for result in results], n=20, method="inclusive")[18]
    per_skill: dict[str, int] = defaultdict(int)
    for result in results:
        if result.skill_name in result.candidates[:5]:
            per_skill[result.skill_name] += 1
    failed_skills = sorted(skill for skill, hits in per_skill.items() if hits < 3)
    observed_skills = {result.skill_name for result in results}
    failed_skills.extend(sorted(observed_skills - set(per_skill)))
    passed = (
        len(observed_skills) == EXPECTED_SKILLS
        and top3 >= TOP_3_MIN
        and recall5 >= RECALL_AT_5_MIN
        and p95 <= P95_MAX_MS
        and not failed_skills
    )
    lines = [
        "Universal Skill 84-Profile authoring smoke",
        "dataset: profile examples (contaminated; not release holdout)",
        f"mode: {mode}",
        f"skills: {len(observed_skills)}",
        f"cases: {len(results)}",
        f"top_1: {top1:.1%}",
        f"top_3: {top3:.1%} (gate >= {TOP_3_MIN:.0%})",
        f"recall_at_5: {recall5:.1%} (gate >= {RECALL_AT_5_MIN:.0%})",
        f"p95_ms: {p95:.3f} (gate <= {P95_MAX_MS:.0f})",
    ]
    if failed_skills:
        lines.append(f"FAILED_SKILLS={failed_skills}")
    lines.append("PASS" if passed else "FAIL")
    return "\n".join(lines), passed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("fts-only", "fake-vector", "both"), default="both")
    args = parser.parse_args(argv)
    passed = True
    modes = ("fts-only", "fake-vector") if args.mode == "both" else (args.mode,)
    for mode in modes:
        report, mode_passed = render(evaluate(fake_vector=mode == "fake-vector"), mode=mode)
        print(report)
        print()
        passed = passed and mode_passed
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
