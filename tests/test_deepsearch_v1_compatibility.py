from __future__ import annotations

import hashlib
from pathlib import Path

from agentmesh.artifacts import DeepSearchArtifactSchemaRegistry, DeepSearchPlanSnapshotV1
from agentmesh.canonical_json import canonical_json_bytes, canonical_json_sha256

_FIXTURE = Path(__file__).parent / "fixtures" / "deepsearch_plan_snapshot_v1.json"
_FIXTURE_BYTES_SHA256 = "44250429e107f86107bd9e29d3705696d9b441f3ae9631c4d7545e8fcafe07e2"
_FROZEN_PLAN_SHA256 = "83d80bf6eef56fb30ed5897b702a302f44b93f831c1b4ff85480b83e081a057f"


def test_frozen_v1_snapshot_registry_round_trip_preserves_bytes_and_hash() -> None:
    content_bytes = _FIXTURE.read_bytes()
    content = content_bytes.decode("utf-8")

    assert hashlib.sha256(content_bytes).hexdigest() == _FIXTURE_BYTES_SHA256
    parsed = DeepSearchArtifactSchemaRegistry.parse(
        "deepsearch_plan_snapshot",
        "deepsearch-plan-snapshot-v1",
        content,
    )

    assert isinstance(parsed, DeepSearchPlanSnapshotV1)
    assert canonical_json_bytes(parsed.model_dump(mode="python")) == content_bytes
    assert canonical_json_sha256(parsed.frozen_plan.model_dump(mode="python")) == _FROZEN_PLAN_SHA256
    assert parsed.plan_content_hash == _FROZEN_PLAN_SHA256
