"""Single persistence-backed budget gate for every DeepSearch resource consumer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from agentmesh.models import (
    DeepSearchBudgetReservationV1,
    DeepSearchBudgetUsageV1,
    DeepSearchBudgetV1,
    DeepSearchToolInvocationV1,
)

DeepSearchBudgetScope = Literal["standard", "finalization"]


@dataclass(frozen=True, slots=True)
class DeepSearchBudgetMutationResult:
    budget: DeepSearchBudgetV1
    reservation: DeepSearchBudgetReservationV1
    replayed: bool


class DeepSearchBudgetStore(Protocol):
    def reserve_deepsearch_budget(
        self,
        *,
        run_id: str,
        expected_budget_version: int,
        logical_operation_key: str,
        invocation_key: str,
        physical_attempt: int,
        resource_maxima: DeepSearchBudgetUsageV1,
        scope: DeepSearchBudgetScope,
        tool_invocation: DeepSearchToolInvocationV1 | None = None,
    ) -> DeepSearchBudgetMutationResult: ...

    def settle_deepsearch_budget(
        self,
        *,
        run_id: str,
        expected_budget_version: int,
        invocation_key: str,
        actual_usage: DeepSearchBudgetUsageV1,
    ) -> DeepSearchBudgetMutationResult: ...


class DeepSearchBudgetMeter:
    """Thin mandatory facade; all accounting remains atomic in the Store."""

    def __init__(self, repository: DeepSearchBudgetStore) -> None:
        self._repository = repository

    def reserve(
        self,
        *,
        run_id: str,
        expected_budget_version: int,
        logical_operation_key: str,
        invocation_key: str,
        physical_attempt: int,
        resource_maxima: DeepSearchBudgetUsageV1,
        scope: DeepSearchBudgetScope = "standard",
        tool_invocation: DeepSearchToolInvocationV1 | None = None,
    ) -> DeepSearchBudgetMutationResult:
        return self._repository.reserve_deepsearch_budget(
            run_id=run_id,
            expected_budget_version=expected_budget_version,
            logical_operation_key=logical_operation_key,
            invocation_key=invocation_key,
            physical_attempt=physical_attempt,
            resource_maxima=resource_maxima,
            scope=scope,
            tool_invocation=tool_invocation,
        )

    def settle(
        self,
        *,
        run_id: str,
        expected_budget_version: int,
        invocation_key: str,
        actual_usage: DeepSearchBudgetUsageV1,
    ) -> DeepSearchBudgetMutationResult:
        return self._repository.settle_deepsearch_budget(
            run_id=run_id,
            expected_budget_version=expected_budget_version,
            invocation_key=invocation_key,
            actual_usage=actual_usage,
        )
