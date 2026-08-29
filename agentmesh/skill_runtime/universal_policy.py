from __future__ import annotations

import hashlib
from functools import lru_cache
from importlib.resources import files
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentmesh.canonical_json import canonical_json_sha256, strict_json_loads


class UniversalRetrievalPolicyV1(BaseModel):
    """Versioned deterministic policy shared by runtime and offline evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["universal-retrieval-policy-v1"]
    retrieval_policy_version: str = Field(min_length=1, max_length=120)
    canonicalizer_version: Literal["universal-canonicalizer-v1"]
    projection_version: Literal["profile-search-text-v1"]
    task_catalog_v2_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_output_mapping_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    fts_top_k_per_atom: int = Field(ge=1, le=50)
    vector_top_k_per_atom: int = Field(ge=1, le=50)
    rrf_k: int = Field(ge=1, le=1000)
    fts_rrf_weight: int = Field(gt=0)
    vector_rrf_weight: int = Field(gt=0)
    lexical_weight: int = Field(ge=0)
    positive_example_weight: int = Field(ge=0)
    negative_example_weight: int = Field(ge=0)
    minimum_relevance_millis: int = Field(ge=0)
    minimum_query_coverage_millis: int = Field(ge=0, le=1000)
    vector_similarity_millis: int = Field(ge=-1000, le=1000)
    max_query_atoms: int = Field(ge=1, le=25)
    max_coverage_atoms: int = Field(ge=1, le=24)
    max_selectable_candidates: int = Field(ge=1, le=12)
    max_blocked_matches: int = Field(ge=0, le=5)
    max_coverage_witnesses: int = Field(ge=1, le=6)
    embedding_batch_deadline_ms: int = Field(ge=1, le=5000)
    tool_health_cache_ttl_seconds: int = Field(ge=1, le=300)
    tool_probe_budget: int = Field(ge=1, le=32)
    tool_probe_concurrency: int = Field(ge=1, le=32)
    tool_probe_timeout_ms: int = Field(ge=1, le=5000)
    tool_probe_batch_deadline_ms: int = Field(ge=1, le=5000)
    generic_action_phrases: tuple[str, ...] = Field(min_length=1, max_length=50)
    generic_query_kinds: tuple[str, ...] = Field(min_length=1, max_length=50)
    fixed_synthesis_outputs: tuple[str, ...] = Field(min_length=1, max_length=20)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_policy(self) -> UniversalRetrievalPolicyV1:
        ordered_values = (
            self.generic_action_phrases,
            self.generic_query_kinds,
            self.fixed_synthesis_outputs,
        )
        if any(len(values) != len(set(values)) for values in ordered_values):
            raise ValueError("retrieval_policy_values_not_unique")
        body = self.model_dump(mode="json", exclude={"content_hash"})
        if canonical_json_sha256(body) != self.content_hash:
            raise ValueError("retrieval_policy_hash_mismatch")
        return self


@lru_cache(maxsize=1)
def universal_retrieval_policy() -> UniversalRetrievalPolicyV1:
    resource = files("agentmesh.skill_runtime").joinpath("policies", "universal-retrieval-policy-v2.json")
    try:
        payload = strict_json_loads(resource.read_bytes())
        policy = UniversalRetrievalPolicyV1.model_validate(payload)
        task_catalog_manifest = strict_json_loads(
            files("agentmesh").joinpath(
                "task_catalog",
                "user-research-v2",
                "catalog.json",
            ).read_bytes()
        )
        mapping_bytes = files("agentmesh").joinpath(
            "task_catalog",
            "sources",
            "user-research-v2-scenario-outputs.json",
        ).read_bytes()
        if (
            not isinstance(task_catalog_manifest, dict)
            or task_catalog_manifest.get("catalog_hash") != policy.task_catalog_v2_hash
            or hashlib.sha256(mapping_bytes).hexdigest() != policy.scenario_output_mapping_hash
        ):
            raise ValueError("retrieval_policy_dependency_hash_mismatch")
        return policy
    except (OSError, UnicodeError, ValueError) as error:
        raise RuntimeError("universal_retrieval_policy_invalid") from error
