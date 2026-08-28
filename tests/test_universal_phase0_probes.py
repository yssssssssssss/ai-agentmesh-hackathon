from __future__ import annotations

from agentmesh.canonical_json import canonical_json_bytes
from agentmesh.store import SQLiteStore
from scripts.probe_planning_contract_storage import _seed
from scripts.run_universal_phase0_sqlite_soak import _snapshot_payload


def test_planning_contract_probe_seeds_mode_compatible_records(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "planning-contract-probe.sqlite3")

    expected_active = _seed(repository, 4)

    assert expected_active == 1


def test_phase0_soak_snapshot_payload_is_exactly_32_kib() -> None:
    payload = _snapshot_payload()

    assert len(canonical_json_bytes(payload)) == 32 * 1024
