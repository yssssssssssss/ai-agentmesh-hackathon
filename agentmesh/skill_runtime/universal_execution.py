"""Code-level release capability for Universal Standard execution."""

from __future__ import annotations

from typing import Literal

from agentmesh.models import AgentExecutionContractVersion

# Phase 2A is preview-only. Phase 2B changes this constant in a dedicated,
# reviewed release after execution and rollback gates pass.
STANDARD_UNIVERSAL_EXECUTION_CONTRACT: Literal["standard_universal_execution_v1"] | None = None


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
