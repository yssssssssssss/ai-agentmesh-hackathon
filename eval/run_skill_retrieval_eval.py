"""Deterministic, offline gate for Skill candidate retrieval."""

# Direct execution must put this checkout ahead of any editable install.
# ruff: noqa: E402

from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentmesh.models import SkillBinding
from agentmesh.seed import USER
from agentmesh.skill_runtime.planner import deterministic_intent
from agentmesh.skill_runtime.profiles import PILOT_BUILTIN_SKILL_NAMES
from agentmesh.skill_runtime.retrieval import SkillCandidateRetriever
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore
from agentmesh.tools import ensure_tool_seed_data

DEFAULT_DATASET = ROOT / "eval" / "skill_retrieval_cases.json"
TOP_K = 3
TOP_K_RECALL_MIN = 0.90
P95_LATENCY_MAX_MS = 300.0
EXPECTED_SKILLS = PILOT_BUILTIN_SKILL_NAMES


@dataclass(frozen=True, slots=True)
class RetrievalCase:
    id: str
    request: str
    expected_skill: str


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    expected_skill: str
    candidates: tuple[str, ...]
    latency_ms: float

    @property
    def recalled(self) -> bool:
        return self.expected_skill in self.candidates[:TOP_K]


@dataclass(frozen=True, slots=True)
class SecurityProbeResult:
    name: str
    target_skill: str
    baseline_candidates: tuple[str, ...]
    filtered_candidates: tuple[str, ...]
    diagnostics: tuple[str, ...]

    @property
    def baseline_recalled(self) -> bool:
        return self.target_skill in self.baseline_candidates[:TOP_K]

    @property
    def filtered_recall(self) -> float:
        return float(self.target_skill in self.filtered_candidates)

    @property
    def passed(self) -> bool:
        return self.baseline_recalled and self.filtered_recall == 0


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    cases: tuple[CaseResult, ...]
    probes: tuple[SecurityProbeResult, ...]
    top3_recall: float
    p95_latency_ms: float

    @property
    def passed(self) -> bool:
        return (
            self.top3_recall >= TOP_K_RECALL_MIN
            and self.p95_latency_ms < P95_LATENCY_MAX_MS
            and all(probe.passed for probe in self.probes)
        )


def load_cases(path: Path = DEFAULT_DATASET) -> list[RetrievalCase]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("dataset_unreadable") from error
    if not isinstance(document, dict) or set(document) != {"version", "cases"} or document["version"] != 1:
        raise ValueError("dataset_document_invalid")
    raw_cases = document["cases"]
    if not isinstance(raw_cases, list) or len(raw_cases) != 40:
        raise ValueError("dataset_must_contain_40_cases")

    cases: list[RetrievalCase] = []
    for index, item in enumerate(raw_cases):
        if not isinstance(item, dict) or set(item) != {"id", "request", "expected_skill"}:
            raise ValueError(f"dataset_case_invalid:{index}")
        if not all(isinstance(item[key], str) and item[key].strip() for key in item):
            raise ValueError(f"dataset_case_invalid:{index}")
        case = RetrievalCase(
            id=item["id"].strip(),
            request=item["request"].strip(),
            expected_skill=item["expected_skill"].strip(),
        )
        if case.request.startswith("$"):
            raise ValueError(f"dataset_case_not_natural_language:{case.id}")
        cases.append(case)

    if len({case.id for case in cases}) != len(cases):
        raise ValueError("dataset_case_ids_not_unique")
    if len({case.request for case in cases}) != len(cases):
        raise ValueError("dataset_requests_not_unique")
    counts = Counter(case.expected_skill for case in cases)
    if set(counts) != EXPECTED_SKILLS or any(count != 4 for count in counts.values()):
        raise ValueError("dataset_skill_distribution_invalid")
    return cases


def recall_at_k(expected: Sequence[str], rankings: Sequence[Sequence[str]], *, k: int = TOP_K) -> float:
    if len(expected) != len(rankings):
        raise ValueError("expected_and_rankings_length_mismatch")
    if not expected:
        return 0.0
    hits = sum(target in ranking[:k] for target, ranking in zip(expected, rankings, strict=True))
    return hits / len(expected)


def nearest_rank_percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    if not 0 < percentile <= 1:
        raise ValueError("percentile_out_of_range")
    ordered = sorted(values)
    return ordered[math.ceil(percentile * len(ordered)) - 1]


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


def _create_wiki(root: Path) -> Path:
    wiki = root / "wiki"
    corpus_files = (
        wiki / "jd-design-system-md-v16" / "horizontal" / "user-research" / "canonical.md",
        wiki
        / "jd-design-system-md-v16"
        / "product-architecture"
        / "comprehensive-business"
        / "content-ecosystem"
        / "canonical.md",
    )
    for corpus in corpus_files:
        corpus.parent.mkdir(parents=True, exist_ok=True)
        corpus.write_text("deterministic design research corpus", encoding="utf-8")
    experiments = (
        wiki
        / "jd-design-system-md-v16"
        / "product-architecture"
        / "plus-and-new-channel"
        / "_knowledge"
        / "experiments"
        / "INDEX.json"
    )
    experiments.parent.mkdir(parents=True, exist_ok=True)
    experiments.write_text("{}", encoding="utf-8")
    return wiki


def _create_retriever(root: Path, wiki: Path) -> tuple[SQLiteStore, SkillCatalogService, SkillCandidateRetriever]:
    os.environ["AGENTMESH_WIKI_ROOT"] = str(wiki)
    repository = SQLiteStore(root / "retrieval.sqlite3")
    ensure_tool_seed_data(repository, granted_by="skill-retrieval-eval")
    catalog = SkillCatalogService(repository)
    catalog.reload()
    return repository, catalog, SkillCandidateRetriever(repository, catalog)


def _recommend(retriever: SkillCandidateRetriever, request: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    candidates, diagnostics = retriever.recommend(USER, deterministic_intent(request))
    return tuple(candidate.skill_name for candidate in candidates), tuple(diagnostics)


def evaluate_cases(cases: Sequence[RetrievalCase], root: Path) -> list[CaseResult]:
    wiki = _create_wiki(root)
    _repository, _catalog, retriever = _create_retriever(root, wiki)
    results: list[CaseResult] = []
    for case in cases:
        started = time.perf_counter()
        candidates, _diagnostics = _recommend(retriever, case.request)
        latency_ms = (time.perf_counter() - started) * 1000
        results.append(
            CaseResult(
                case_id=case.id,
                expected_skill=case.expected_skill,
                candidates=candidates,
                latency_ms=latency_ms,
            )
        )
    return results


def _probe_unavailable(root: Path) -> SecurityProbeResult:
    wiki = _create_wiki(root)
    _repository, _catalog, retriever = _create_retriever(root, wiki)
    target = "query-experiment-conclusions"
    request = "查询以前首页入口相关的 AB 实验结论和失败经验。"
    baseline, _ = _recommend(retriever, request)
    next(wiki.rglob("INDEX.json")).unlink()
    filtered, diagnostics = _recommend(retriever, request)
    return SecurityProbeResult("unavailable", target, baseline, filtered, diagnostics)


def _probe_disabled(root: Path) -> SecurityProbeResult:
    wiki = _create_wiki(root)
    repository, _catalog, retriever = _create_retriever(root, wiki)
    target = "prd-feasibility"
    request = "评审这份 PRD 的业务逻辑可行性、方案风险和上线影响。"
    baseline, _ = _recommend(retriever, request)
    skill = repository.get_skill_definition_by_name(target)
    if skill is None:
        raise RuntimeError("disabled_probe_skill_missing")
    repository.save_skill_binding(
        SkillBinding(
            id="eval_disabled_prd_feasibility",
            agent_id=USER.personal_agent_id,
            skill_id=skill.id,
            enabled=False,
            granted_by="skill-retrieval-eval",
        )
    )
    filtered, diagnostics = _recommend(retriever, request)
    return SecurityProbeResult("disabled", target, baseline, filtered, diagnostics)


def _probe_unauthorized(root: Path) -> SecurityProbeResult:
    wiki = _create_wiki(root)
    repository, _catalog, retriever = _create_retriever(root, wiki)
    target = "prd-feasibility"
    request = "评审这份 PRD 的业务逻辑可行性、方案风险和上线影响。"
    baseline, _ = _recommend(retriever, request)
    skill = repository.get_skill_definition_by_name(target)
    if skill is None:
        raise RuntimeError("unauthorized_probe_skill_missing")
    profile = repository.get_skill_capability_profile(skill.id)
    if profile is None:
        raise RuntimeError("unauthorized_probe_profile_missing")
    repository.save_skill_capability_profile(
        profile.model_copy(update={"required_capabilities": ["research.request"]})
    )
    filtered, diagnostics = _recommend(retriever, request)
    return SecurityProbeResult("unauthorized", target, baseline, filtered, diagnostics)


def run_security_probes(root: Path) -> list[SecurityProbeResult]:
    return [
        _probe_unavailable(root / "unavailable"),
        _probe_disabled(root / "disabled"),
        _probe_unauthorized(root / "unauthorized"),
    ]


def evaluate(cases: Sequence[RetrievalCase]) -> EvaluationReport:
    with offline_environment(), tempfile.TemporaryDirectory(prefix="agentmesh-skill-retrieval-") as temp_dir:
        root = Path(temp_dir)
        case_results = evaluate_cases(cases, root / "cases")
        probes = run_security_probes(root / "probes")
    return EvaluationReport(
        cases=tuple(case_results),
        probes=tuple(probes),
        top3_recall=recall_at_k(
            [result.expected_skill for result in case_results],
            [result.candidates for result in case_results],
        ),
        p95_latency_ms=nearest_rank_percentile([result.latency_ms for result in case_results], 0.95),
    )


def render_report(report: EvaluationReport) -> str:
    lines = [
        "Skill retrieval evaluation",
        f"cases: {len(report.cases)}",
        f"top_3_recall: {report.top3_recall:.1%} (gate >= {TOP_K_RECALL_MIN:.0%})",
        f"retrieval_p95_ms: {report.p95_latency_ms:.3f} (gate < {P95_LATENCY_MAX_MS:.0f})",
    ]
    for probe in report.probes:
        lines.append(f"{probe.name}_skill_recall: {probe.filtered_recall:.1%} (gate = 0%)")
    misses = [result for result in report.cases if not result.recalled]
    for result in misses:
        lines.append(
            f"CASE_MISS id={result.case_id} expected={result.expected_skill} "
            f"top3={list(result.candidates[:TOP_K])} latency_ms={result.latency_ms:.3f}"
        )
    if report.p95_latency_ms >= P95_LATENCY_MAX_MS:
        slow_count = max(1, math.ceil(len(report.cases) * 0.05))
        for result in sorted(report.cases, key=lambda item: item.latency_ms, reverse=True)[:slow_count]:
            lines.append(f"LATENCY_SLOW id={result.case_id} latency_ms={result.latency_ms:.3f}")
    for probe in report.probes:
        if not probe.passed:
            lines.append(
                f"PROBE_FAIL name={probe.name} target={probe.target_skill} "
                f"baseline_top3={list(probe.baseline_candidates[:TOP_K])} "
                f"filtered={list(probe.filtered_candidates)} "
                f"diagnostics={list(probe.diagnostics)}"
            )
    failed_gates: list[str] = []
    if report.top3_recall < TOP_K_RECALL_MIN:
        failed_gates.append("top_3_recall")
    if report.p95_latency_ms >= P95_LATENCY_MAX_MS:
        failed_gates.append("retrieval_p95_ms")
    failed_gates.extend(probe.name for probe in report.probes if not probe.passed)
    lines.append("PASS" if not failed_gates else "FAIL gates=" + ",".join(failed_gates))
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    arguments = parser.parse_args(argv)
    try:
        cases = load_cases(arguments.dataset)
        report = evaluate(cases)
    except (RuntimeError, ValueError) as error:
        print(f"FAIL setup={error}", file=sys.stderr)
        return 2
    print(render_report(report))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
