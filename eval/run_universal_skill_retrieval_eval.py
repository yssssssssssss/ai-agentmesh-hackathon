#!/usr/bin/env python3
"""Offline Phase 1A calibration for UniversalSkillSearchService."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import re
import sys
import tempfile
import time
from collections import Counter, defaultdict
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentmesh.seed import USER  # noqa: E402
from agentmesh.skill_runtime.planner import deterministic_intent  # noqa: E402
from agentmesh.skill_runtime.recommendation import (  # noqa: E402
    UNIVERSAL_RETRIEVAL_POLICY_VERSION,
    UniversalSkillSearchService,
    profile_query_terms,
)
from agentmesh.skill_runtime.service import SkillCatalogService  # noqa: E402
from agentmesh.store import (  # noqa: E402
    SKILL_PROFILE_VECTOR_SIMILARITY_THRESHOLD,
    SQLiteStore,
)
from agentmesh.tools import ensure_tool_seed_data  # noqa: E402

DEFAULT_DATASET = ROOT / "eval" / "universal_skill_retrieval_calibration_v1.json"
EXPECTED_SINGLE_CASES = 60
EXPECTED_COMPOUND_CASES = 6
EXPECTED_BOUNDARY_CASES = 6
EXPECTED_SKILLS = 12
TOP_3_RECALL_MIN = 0.90
RECALL_AT_5_MIN = 0.95
PER_SKILL_HITS_MIN = 4
P95_LATENCY_MAX_MS = 500.0


@dataclass(frozen=True, slots=True)
class CalibrationCase:
    id: str
    request: str
    expected_skills: tuple[str, ...]
    family: str
    language: str
    kind: Literal["single", "compound", "boundary"] = "single"


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    case: CalibrationCase
    candidates: tuple[str, ...]
    latency_ms: float

    @property
    def recalled_at_5(self) -> bool:
        expected = set(self.case.expected_skills)
        actual = set(self.candidates[:5])
        return not actual if self.case.kind == "boundary" else expected <= actual

    def has_any_expected_at(self, limit: int) -> bool:
        return bool(set(self.case.expected_skills) & set(self.candidates[:limit]))


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[math.ceil(percentile * len(ordered)) - 1]


def load_cases(path: Path = DEFAULT_DATASET) -> list[CalibrationCase]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("dataset_unreadable") from error
    required_root = {
        "schema_version",
        "dataset_version",
        "partition",
        "description",
        "cases",
        "compound_cases",
        "boundary_cases",
    }
    if (
        not isinstance(document, dict)
        or set(document) != required_root
        or document["schema_version"] != "universal-skill-retrieval-dataset-v1"
        or document["partition"] != "calibration"
    ):
        raise ValueError("dataset_document_invalid")
    raw_groups = (
        ("single", document["cases"], EXPECTED_SINGLE_CASES),
        ("compound", document["compound_cases"], EXPECTED_COMPOUND_CASES),
        ("boundary", document["boundary_cases"], EXPECTED_BOUNDARY_CASES),
    )
    cases: list[CalibrationCase] = []
    for kind, raw_cases, expected_count in raw_groups:
        if not isinstance(raw_cases, list) or len(raw_cases) != expected_count:
            raise ValueError(f"dataset_{kind}_case_count_invalid")
        for index, item in enumerate(raw_cases):
            required_fields = {"id", "request", "expected_skills", "family", "language"}
            if not isinstance(item, dict) or set(item) != required_fields:
                raise ValueError(f"dataset_case_invalid:{kind}:{index}")
            expected = item["expected_skills"]
            if (
                not isinstance(expected, list)
                or len(expected) != len(set(expected))
                or not all(isinstance(value, str) and value for value in expected)
                or (kind != "boundary" and not expected)
                or (kind == "boundary" and expected)
            ):
                raise ValueError(f"dataset_case_invalid:{kind}:{index}")
            case = CalibrationCase(
                id=str(item["id"]).strip(),
                request=str(item["request"]).strip(),
                expected_skills=tuple(expected),
                family=str(item["family"]).strip(),
                language=str(item["language"]).strip(),
                kind=kind,
            )
            if not all((case.id, case.request, case.family, case.language)):
                raise ValueError(f"dataset_case_invalid:{kind}:{index}")
            cases.append(case)
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("dataset_case_ids_not_unique")
    if len({case.request for case in cases}) != len(cases):
        raise ValueError("dataset_requests_not_unique")
    single_cases = [case for case in cases if case.kind == "single"]
    counts = Counter(case.expected_skills[0] for case in single_cases)
    if len(counts) != EXPECTED_SKILLS or any(count != 5 for count in counts.values()):
        raise ValueError("dataset_skill_distribution_invalid")
    return cases


@contextmanager
def offline_environment() -> Iterator[None]:
    fixed = {
        "AGENTMESH_EMBEDDING_ENABLED": "false",
        "AGENTMESH_SKILL_PATHS": "",
        "AGENTMESH_TRUST_PROJECT_SKILLS": "false",
        "AGENTMESH_WIKI_ROOT": "",
    }
    previous = {key: os.environ.get(key) for key in fixed}
    os.environ.update(fixed)
    embedding = importlib.import_module("agentmesh.embedding")
    previous_embedding_enabled = embedding.EMBEDDING_ENABLED
    embedding.EMBEDDING_ENABLED = False
    try:
        yield
    finally:
        embedding.EMBEDDING_ENABLED = previous_embedding_enabled
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _fake_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for token in re.findall(r"[a-z0-9][a-z0-9_-]*|[\u3400-\u9fff]+", text.casefold()):
        terms.add(token)
        if re.fullmatch(r"[\u3400-\u9fff]+", token):
            terms.update(token[index : index + 2] for index in range(max(0, len(token) - 1)))
            terms.update(token[index : index + 3] for index in range(max(0, len(token) - 2)))
    return terms


def _stable_fake_similarity(left: str, right: str) -> float:
    left_terms = profile_query_terms(left)
    right_terms = _fake_terms(right)
    if not left_terms or not right_terms:
        return 0.0
    overlap = left_terms & right_terms
    if not overlap:
        return 0.0
    # Hashing the shared terms makes ties deterministic while retaining a
    # lexical fake that never calls an external embedding provider.
    weight = sum(1 + hashlib.sha256(term.encode("utf-8")).digest()[0] / 255 for term in overlap)
    raw_score = weight / math.sqrt(len(left_terms) * len(right_terms))
    return min(1.0, raw_score * 5)


class _FakeVectorRanker:
    def __init__(self, repository: SQLiteStore) -> None:
        self._repository = repository

    def __call__(
        self,
        query: str,
        allowed_skill_ids: set[str],
    ) -> tuple[list[str], list[str], list[str]]:
        fts_ids, _vector_ids, diagnostics = self._repository.rank_skill_profiles(
            query,
            allowed_skill_ids,
        )
        scores: list[tuple[float, str]] = []
        for profile in self._repository.skill_capability_profiles:
            if profile.skill_id not in allowed_skill_ids:
                continue
            skill = self._repository.get_skill_definition(profile.skill_id)
            if skill is None:
                continue
            score = _stable_fake_similarity(
                query,
                profile.search_text(),
            )
            if score >= SKILL_PROFILE_VECTOR_SIMILARITY_THRESHOLD:
                scores.append((score, profile.skill_id))
        scores.sort(key=lambda item: (-item[0], item[1]))
        safe_diagnostics = [item for item in diagnostics if item != "embedding_unavailable"]
        safe_diagnostics.append("fake_vector")
        return fts_ids, [skill_id for _score, skill_id in scores[:12]], safe_diagnostics


def evaluate(
    cases: Sequence[CalibrationCase],
    *,
    fake_vector: bool = False,
) -> list[CalibrationResult]:
    with offline_environment(), tempfile.TemporaryDirectory(
        prefix="agentmesh-universal-calibration-"
    ) as directory:
        repository = SQLiteStore(Path(directory) / "calibration.sqlite3")
        ensure_tool_seed_data(repository, granted_by="universal-calibration")
        catalog = SkillCatalogService(repository)
        catalog.reload()
        search = UniversalSkillSearchService(
            repository,
            catalog,
            profile_ranker=_FakeVectorRanker(repository) if fake_vector else None,
        )
        results: list[CalibrationResult] = []
        for case in cases:
            started = time.perf_counter()
            outcome = search.search_for_evaluation(
                USER,
                deterministic_intent(case.request),
            )
            results.append(
                CalibrationResult(
                    case=case,
                    candidates=tuple(
                        candidate.skill_name for candidate in outcome.ranked_matches
                    ),
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
            )
    return results


def render_report(
    results: Sequence[CalibrationResult],
    *,
    mode: str = "fts-only",
) -> tuple[str, bool]:
    single_results = [result for result in results if result.case.kind == "single"]
    compound_results = [result for result in results if result.case.kind == "compound"]
    boundary_results = [result for result in results if result.case.kind == "boundary"]
    single_top1 = sum(result.has_any_expected_at(1) for result in single_results) / max(
        1, len(single_results)
    )
    single_top3 = sum(result.has_any_expected_at(3) for result in single_results) / max(
        1, len(single_results)
    )
    single_recall = sum(result.recalled_at_5 for result in single_results) / max(
        1, len(single_results)
    )
    compound_coverage = sum(result.recalled_at_5 for result in compound_results) / max(
        1, len(compound_results)
    )
    boundary_rejection = sum(result.recalled_at_5 for result in boundary_results) / max(
        1, len(boundary_results)
    )
    p95 = _percentile([result.latency_ms for result in results], 0.95)
    hits_by_skill: dict[str, int] = defaultdict(int)
    total_by_skill: dict[str, int] = defaultdict(int)
    hits_by_family: dict[str, int] = defaultdict(int)
    total_by_family: dict[str, int] = defaultdict(int)
    hits_by_language: dict[str, int] = defaultdict(int)
    total_by_language: dict[str, int] = defaultdict(int)
    for result in single_results:
        expected = result.case.expected_skills[0]
        total_by_skill[expected] += 1
        total_by_family[result.case.family] += 1
        total_by_language[result.case.language] += 1
        if result.recalled_at_5:
            hits_by_skill[expected] += 1
            hits_by_family[result.case.family] += 1
            hits_by_language[result.case.language] += 1

    failed_skills = sorted(
        skill
        for skill, total in total_by_skill.items()
        if hits_by_skill[skill] < min(PER_SKILL_HITS_MIN, total)
    )
    failed_families = sorted(
        family
        for family, total in total_by_family.items()
        if hits_by_family[family] / total < RECALL_AT_5_MIN
    )
    failed_languages = sorted(
        language
        for language, total in total_by_language.items()
        if hits_by_language[language] / total < RECALL_AT_5_MIN
    )
    passed = (
        single_top3 >= TOP_3_RECALL_MIN
        and single_recall >= RECALL_AT_5_MIN
        and compound_coverage >= RECALL_AT_5_MIN
        and boundary_rejection == 1.0
        and p95 <= P95_LATENCY_MAX_MS
        and not failed_skills
        and not failed_families
        and not failed_languages
    )
    lines = [
        "Universal Skill retrieval calibration",
        f"mode: {mode}",
        f"retrieval_policy_version: {UNIVERSAL_RETRIEVAL_POLICY_VERSION}",
        f"single_cases: {len(single_results)}",
        f"single_top_1: {single_top1:.1%}",
        f"single_top_3: {single_top3:.1%} (gate >= {TOP_3_RECALL_MIN:.0%})",
        f"single_recall_at_5: {single_recall:.1%} (gate >= {RECALL_AT_5_MIN:.0%})",
        f"compound_cases: {len(compound_results)}",
        f"compound_coverage_at_5: {compound_coverage:.1%} (gate >= {RECALL_AT_5_MIN:.0%})",
        f"boundary_cases: {len(boundary_results)}",
        f"boundary_rejection: {boundary_rejection:.1%} (gate = 100%)",
        f"p95_ms: {p95:.3f} (gate <= {P95_LATENCY_MAX_MS:.0f})",
    ]
    for family in sorted(total_by_family):
        lines.append(
            f"family[{family}]: {hits_by_family[family]}/{total_by_family[family]}"
        )
    for language in sorted(total_by_language):
        lines.append(
            f"language[{language}]: {hits_by_language[language]}/{total_by_language[language]}"
        )
    for result in results:
        if not result.recalled_at_5:
            lines.append(
                f"MISS kind={result.case.kind} id={result.case.id} "
                f"expected={list(result.case.expected_skills)} "
                f"top5={list(result.candidates[:5])}"
            )
    if failed_skills:
        lines.append(f"FAILED_SKILLS={failed_skills}")
    if failed_families:
        lines.append(f"FAILED_FAMILIES={failed_families}")
    if failed_languages:
        lines.append(f"FAILED_LANGUAGES={failed_languages}")
    lines.append("PASS" if passed else "FAIL")
    return "\n".join(lines), passed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args(argv)
    try:
        cases = load_cases(args.dataset)
        reports: list[str] = []
        passed = True
        for mode, fake_vector in (("fts-only", False), ("fake-vector", True)):
            report, mode_passed = render_report(
                evaluate(cases, fake_vector=fake_vector),
                mode=mode,
            )
            reports.append(report)
            passed = passed and mode_passed
    except (RuntimeError, ValueError) as error:
        print(f"FAIL setup={error}", file=sys.stderr)
        return 2
    print("\n\n".join(reports))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
