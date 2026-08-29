from __future__ import annotations

from importlib.resources import files

import pytest
from pydantic import ValidationError

from agentmesh.canonical_json import strict_json_loads
from agentmesh.skill_runtime.recommendation import UNIVERSAL_RETRIEVAL_POLICY_VERSION
from agentmesh.skill_runtime.universal_policy import (
    UniversalRetrievalPolicyV1,
    universal_retrieval_policy,
)
from agentmesh.store import SKILL_PROFILE_VECTOR_SIMILARITY_THRESHOLD


def test_universal_retrieval_policy_asset_is_hash_verified_and_shared() -> None:
    policy = universal_retrieval_policy()

    assert policy.retrieval_policy_version == UNIVERSAL_RETRIEVAL_POLICY_VERSION
    assert policy.max_query_atoms == 25
    assert policy.task_catalog_v2_hash == "0817f656eaf2781ce6b5d8510e33b95fd0aa2a1d3e8d1bc00dfb9711a88ebdd7"
    assert policy.scenario_output_mapping_hash == (
        "127fd67a1d5af0b3ba1680d31237af2c4ac9d661394442f5b3a6c27645faf0cf"
    )
    assert policy.max_coverage_atoms == 24
    assert policy.max_selectable_candidates == 12
    assert policy.max_coverage_witnesses == 6
    assert policy.tool_probe_budget == policy.tool_probe_concurrency == 8
    assert policy.vector_similarity_millis / 1000 == SKILL_PROFILE_VECTOR_SIMILARITY_THRESHOLD


def test_universal_retrieval_policy_rejects_semantic_change_without_new_hash() -> None:
    resource = files("agentmesh.skill_runtime").joinpath(
        "policies",
        "universal-retrieval-policy-v2.json",
    )
    payload = strict_json_loads(resource.read_bytes())
    payload["minimum_relevance_millis"] += 1

    with pytest.raises(ValidationError, match="retrieval_policy_hash_mismatch"):
        UniversalRetrievalPolicyV1.model_validate(payload)
