"""Code-level release capability for Universal Standard execution."""

from __future__ import annotations

from typing import Literal

from agentmesh.models import AgentExecutionContractVersion

# Phase 2B recognizes the immutable execution contract. Production creation is
# still gated by verified Profile provenance and the release marker.
STANDARD_UNIVERSAL_EXECUTION_CONTRACT: Literal["standard_universal_execution_v1"] | None = (
    "standard_universal_execution_v1"
)


def universal_standard_execution_contract() -> AgentExecutionContractVersion | None:
    if STANDARD_UNIVERSAL_EXECUTION_CONTRACT is None:
        return None
    return AgentExecutionContractVersion(STANDARD_UNIVERSAL_EXECUTION_CONTRACT)


def universal_standard_execution_available() -> bool:
    return universal_standard_execution_contract() is not None


def universal_standard_execution_allowed(*, run_contract, plan_contract) -> bool:  # noqa: ANN001
    available = universal_standard_execution_contract()
    return (
        available is not None
        and run_contract is available
        and plan_contract is available
    )
