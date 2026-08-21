from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import verify_ai_x_parity_lock as verifier  # noqa: E402


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


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


def test_exact_inventory_accepts_declared_flat_files(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text("{}")
    (tmp_path / "b.bin").write_bytes(b"x")
    assert verifier.exact_regular_inventory(tmp_path, {"a.json", "b.bin"}) == {"a.json", "b.bin"}


@pytest.mark.parametrize("mutation", ["nested-file", "empty-directory", "file-symlink", "directory-symlink", "fifo"])
def test_exact_inventory_rejects_nested_links_and_nonregular_entries(tmp_path: Path, mutation: str) -> None:
    (tmp_path / "declared.json").write_text("{}")
    if mutation == "nested-file":
        (tmp_path / "nested").mkdir()
        (tmp_path / "nested" / "extra.json").write_text("{}")
    elif mutation == "empty-directory":
        (tmp_path / "nested").mkdir()
    elif mutation == "file-symlink":
        (tmp_path / "link").symlink_to(tmp_path / "declared.json")
    elif mutation == "directory-symlink":
        outside = tmp_path.parent / f"{tmp_path.name}-outside"
        outside.mkdir()
        (tmp_path / "link").symlink_to(outside, target_is_directory=True)
    else:
        if not hasattr(os, "mkfifo"):
            pytest.skip("FIFO unsupported")
        os.mkfifo(tmp_path / "pipe")
    with pytest.raises(ValueError):
        verifier.exact_regular_inventory(tmp_path, {"declared.json"})


def sqlite_fixture(path: Path, value: object, *, column: str = "payload") -> Path:
    with sqlite3.connect(path) as connection:
        connection.execute(f'CREATE TABLE arbitrary (id INTEGER PRIMARY KEY, "{column}" BLOB)')
        connection.execute(f'INSERT INTO arbitrary("{column}") VALUES (?)', (value,))
    return path


@pytest.mark.parametrize(
    "value",
    [
        "sk-abcdefgh",
        "Bearer abcdefgh",
        "-----BEGIN PRIVATE KEY-----",
        json.dumps({"token": "nonempty-value"}),
        b"prefix sk-abcdefgh suffix",
        "/Users/example/private.txt",
    ],
)
def test_sqlite_scanner_detects_credentials_sensitive_json_blob_and_local_paths(
    tmp_path: Path, value: object
) -> None:
    result = verifier.scan_sqlite_for_secrets(sqlite_fixture(tmp_path / "fixture.sqlite3", value))
    assert result["passed"] is False
    assert result["hits"]


def test_sqlite_scanner_accepts_ordinary_token_words_empty_sensitive_fields_and_fixture_ids(tmp_path: Path) -> None:
    value = json.dumps(
        {
            "token": "",
            "token_count": 3,
            "fixture_id": "token_fixture_synthetic",
            "description": "ordinary fixture without credentials",
        }
    )
    result = verifier.scan_sqlite_for_secrets(sqlite_fixture(tmp_path / "fixture.sqlite3", value))
    assert result == {"hits": [], "passed": True}


def make_valid_baseline(project_root: Path) -> tuple[Path, dict[str, object]]:
    root = project_root / "baseline"
    (root / "states").mkdir(parents=True)
    (root / "screenshots").mkdir()
    state_rows: list[dict[str, object]] = []
    state_records: dict[str, tuple[str, str]] = {}
    for state in sorted(verifier.REQUIRED_BASELINE_STATES):
        fixture_id = f"fixture/{state}"
        payload = {
            "canonical_state_id": state,
            "fixture_id": fixture_id,
            "immutable": True,
            "sanitization": "synthetic",
            "schema_version": "agentmesh-ai-x-baseline-state-v1",
        }
        path = root / "states" / f"{state}.json"
        path.write_bytes(canonical(payload))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        state_rows.append(
            {
                "path": f"states/{state}.json",
                "sha256": digest,
                "state_fixture_id": fixture_id,
                "state_id": state,
            }
        )
        state_records[state] = (fixture_id, digest)
    screenshots: list[dict[str, object]] = []
    for state in sorted(verifier.REQUIRED_BASELINE_STATES):
        for viewport_id in sorted(verifier.REQUIRED_VIEWPORTS):
            viewport = verifier.REQUIRED_VIEWPORTS[viewport_id]
            raw = (
                b"\x89PNG\r\n\x1a\n"
                + b"\x00\x00\x00\x0dIHDR"
                + struct.pack(">II", viewport["width"], viewport["height"])
                + f"{state}/{viewport_id}".encode()
            )
            relative = f"screenshots/{state}--{viewport_id}.png"
            path = root / relative
            path.write_bytes(raw)
            fixture_id, fixture_hash = state_records[state]
            screenshots.append(
                {
                    "browser_engine": "chromium",
                    "browser_version": "151.0.7922.170",
                    "bytes": len(raw),
                    "path": relative,
                    "sanitization_statement": "synthetic",
                    "sanitization_status": "passed",
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "state_fixture_id": fixture_id,
                    "state_fixture_sha256": fixture_hash,
                    "state_id": state,
                    "viewport_id": viewport_id,
                }
            )
    manifest: dict[str, object] = {
        "capture": {
            "backend_api_mock_rule": "url.origin === backendOrigin && url.pathname.startsWith('/api/')",
            "browser_count": 1,
            "context_count": 1,
            "page_count": 1,
            "pass_count": 1,
            "providers_called": False,
        },
        "schema_version": "agentmesh-ai-x-browser-baseline-v1",
        "screenshots": screenshots,
        "source": {
            "commit": verifier.DEFAULT_REVISION,
            "repository": verifier.SOURCE_REPOSITORY,
            "root": "apps/web",
            "tree": verifier.SOURCE_SNAPSHOT_TREE,
        },
        "state_files": state_rows,
        "status": "PASS",
        "viewports": [
            {
                "device_scale_factor": verifier.REQUIRED_VIEWPORTS[key]["device_scale_factor"],
                "height": verifier.REQUIRED_VIEWPORTS[key]["height"],
                "id": key,
                "width": verifier.REQUIRED_VIEWPORTS[key]["width"],
            }
            for key in sorted(verifier.REQUIRED_VIEWPORTS)
        ],
    }
    (root / "manifest.json").write_bytes(canonical(manifest))
    return root, manifest


def validate_test_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    monkeypatch.setattr(verifier, "BASELINE_ROOT", Path("baseline"))
    return verifier.validate_browser_baseline(
        tmp_path,
        {"source": {"snapshot_tree": verifier.SOURCE_SNAPSHOT_TREE}},
    )


def test_baseline_accepts_exact_unique_matrix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_valid_baseline(tmp_path)
    assert validate_test_baseline(tmp_path, monkeypatch)["screenshot_count"] == 24


@pytest.mark.parametrize("mutation", ["duplicate-path", "duplicate-hash", "wrong-path", "fixture-hash", "nested-extra"])
def test_baseline_rejects_duplicate_or_noncanonical_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    root, manifest = make_valid_baseline(tmp_path)
    screenshots = manifest["screenshots"]
    assert isinstance(screenshots, list)
    if mutation == "duplicate-path":
        screenshots[1]["path"] = screenshots[0]["path"]
    elif mutation == "wrong-path":
        screenshots[0]["path"] = "screenshots/wrong.png"
    elif mutation == "fixture-hash":
        screenshots[0]["state_fixture_sha256"] = "0" * 64
    elif mutation == "nested-extra":
        (root / "screenshots" / "nested").mkdir()
        (root / "screenshots" / "nested" / "extra.png").write_bytes(b"extra")
    else:
        first = root / screenshots[0]["path"]
        second = root / screenshots[3]["path"]
        second.write_bytes(first.read_bytes())
        screenshots[3]["sha256"] = screenshots[0]["sha256"]
        screenshots[3]["bytes"] = screenshots[0]["bytes"]
    (root / "manifest.json").write_bytes(canonical(manifest))
    with pytest.raises(ValueError):
        validate_test_baseline(tmp_path, monkeypatch)


def test_criterion_assessment_has_reachable_positive_authorization() -> None:
    evidence = {
        "browser_baseline": {"available": True},
        "contract_fixtures": {"status": "valid_characterization_only"},
        "handoff": {"passed": True},
        "historical_database_fixture": {"status": "valid_sanitized_historical_fixture"},
        "owner_acceptance": {"bindings": [{} for _ in verifier.OWNER_ACCOUNTABILITIES]},
        "source_bundle": {"content_scope": "exact_reviewed_tree_snapshot_export"},
        "source_quality": {"passed": True},
        "target_characterization": {"complete": True},
    }
    criteria = verifier.criterion_assessment(evidence, {"file_count": 1})
    assert len(criteria) == 10
    assert all(row["satisfied_by_committed_evidence"] for row in criteria)
