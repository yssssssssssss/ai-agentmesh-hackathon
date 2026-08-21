from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import verify_ai_x_parity_lock as verifier  # noqa: E402


def test_strict_json_rejects_duplicate_keys() -> None:
    with pytest.raises(ValueError, match="duplicate JSON key"):
        verifier.strict_json_bytes(b'{"value":1,"value":2}\n', "duplicate.json")


def test_strict_json_rejects_noncanonical_bytes() -> None:
    with pytest.raises(ValueError, match="not canonical"):
        verifier.strict_json_bytes(b'{"value": 1}\n', "noncanonical.json")


def test_relative_path_rejects_parent_traversal() -> None:
    with pytest.raises(ValueError, match="parent traversal"):
        verifier.validate_relative_path("../fixture.json")


def test_identity_sets_are_complete_and_disjoint() -> None:
    historical = verifier.HISTORICAL_IDENTITY_POLICY["combined"]
    assert len(historical) == 13
    assert len(historical) == len(set(historical))
    assert set(historical).isdisjoint(verifier.CURRENT_IDENTITIES)


def test_owner_and_criterion_policies_are_exact() -> None:
    assert len(verifier.OWNER_ACCOUNTABILITIES) == 8
    assert set(verifier.CRITERION_OWNERS) == {
        f"gate0-{number:02d}-{suffix}"
        for number, suffix in (
            (1, "ownership-ledger"),
            (2, "final-source-authority-and-durable-retention"),
            (3, "authoritative-parity-lock"),
            (4, "offline-source-quality"),
            (5, "visual-identity"),
            (6, "accepted-architecture-and-exact-contracts"),
            (7, "target-characterization"),
            (8, "zero-production-behavior-diff"),
            (9, "v2-compatibility-and-slice-1-work-plan"),
            (10, "handoff-and-authorization"),
        )
    }


def test_baseline_policy_requires_exact_cross_product() -> None:
    expected = {
        (state, viewport)
        for state in verifier.REQUIRED_BASELINE_STATES
        for viewport in verifier.REQUIRED_VIEWPORTS
    }
    assert len(expected) == 24
