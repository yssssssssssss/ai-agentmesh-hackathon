from __future__ import annotations

import hashlib
from collections import Counter
from difflib import SequenceMatcher

import yaml

from eval.run_universal_skill_retrieval_eval import (
    DEFAULT_DATASET,
    evaluate,
    load_cases,
    render_report,
)


def test_phase1a_calibration_manifest_has_five_independent_cases_per_skill() -> None:
    cases = load_cases()
    single_cases = [case for case in cases if case.kind == "single"]
    compound_cases = [case for case in cases if case.kind == "compound"]
    boundary_cases = [case for case in cases if case.kind == "boundary"]
    counts = Counter(case.expected_skills[0] for case in single_cases)

    assert hashlib.sha256(DEFAULT_DATASET.read_bytes()).hexdigest() == (
        "e5599af8cbfca91edb4820c61a93d8604293e754b3991d30602b6af19062221d"
    )
    assert len(cases) == 72
    assert len(single_cases) == 60
    assert len(compound_cases) == 6
    assert all(len(case.expected_skills) >= 2 for case in compound_cases)
    assert all(case.required_deliverables and case.expected_outcome == "ok" for case in compound_cases)
    assert len(boundary_cases) == 6
    assert all(not case.expected_skills for case in boundary_cases)
    assert all(case.expected_outcome == "no_matching_skill" for case in boundary_cases)
    assert len(counts) == 12
    assert set(counts.values()) == {5}
    assert len({case.request for case in cases}) == 72
    for case in single_cases:
        sidecar = (
            DEFAULT_DATASET.parents[1]
            / "agentmesh"
            / "builtin_skills"
            / case.expected_skills[0]
            / "agents"
            / "agentmesh.yaml"
        )
        profile = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
        assert case.request not in profile["examples"]
        assert max(
            SequenceMatcher(None, case.request, example).ratio()
            for example in profile["examples"]
        ) < 0.8


def test_phase1a_offline_universal_retrieval_meets_calibration_gate() -> None:
    cases = load_cases()
    fts_report, fts_passed = render_report(evaluate(cases), mode="fts-only")
    vector_report, vector_passed = render_report(
        evaluate(cases, fake_vector=True),
        mode="fake-vector",
    )

    assert fts_passed, fts_report
    assert vector_passed, vector_report
