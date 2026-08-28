"""Budgeted persistence for ordinary runtime Artifacts produced by DeepSearch."""

from __future__ import annotations

from typing import Protocol

from agentmesh.canonical_json import canonical_json_bytes, canonical_json_sha256, strict_json_loads
from agentmesh.deepsearch.budget import DeepSearchBudgetMeter, DeepSearchBudgetStore
from agentmesh.models import AgentPlanningMode, AgentRun, Artifact, DeepSearchBudgetUsageV1

_BUDGET_CAS_ATTEMPTS = 4
_MAX_PHYSICAL_ATTEMPTS = 3
DEEPSEARCH_RUNTIME_ARTIFACT_MAX_BYTES = 1_048_576


class RuntimeArtifactStore(DeepSearchBudgetStore, Protocol):
    def get_agent_run(self, run_id: str) -> AgentRun | None: ...

    def save_artifact(self, artifact: Artifact) -> Artifact: ...

    def save_deepsearch_runtime_artifact(
        self,
        *,
        artifact: Artifact,
        budget_invocation_key: str,
        actual_usage: DeepSearchBudgetUsageV1,
    ) -> Artifact: ...


def _canonical_artifact(artifact: Artifact) -> tuple[Artifact, bytes]:
    if artifact.content_type == "application/json":
        content_bytes = canonical_json_bytes(strict_json_loads(artifact.content))
        artifact = artifact.model_copy(update={"content": content_bytes.decode("utf-8")})
        return artifact, content_bytes
    return artifact, artifact.content.encode("utf-8")


def _operation_key(artifact: Artifact) -> str:
    digest = canonical_json_sha256(
        {
            "artifact_id": artifact.id,
            "artifact_type": artifact.artifact_type,
            "run_id": artifact.run_id,
        }
    )
    return f"artifact:{digest}"


def _current_budget(repository: RuntimeArtifactStore, run_id: str):  # noqa: ANN202
    run = repository.get_agent_run(run_id)
    if run is None or run.deepsearch_budget is None:
        raise RuntimeError("deepsearch_artifact_budget_unavailable")
    return run.deepsearch_budget


def _settle(
    repository: RuntimeArtifactStore,
    *,
    run_id: str,
    invocation_key: str,
    actual_usage: DeepSearchBudgetUsageV1,
) -> None:
    meter = DeepSearchBudgetMeter(repository)
    last_conflict: Exception | None = None
    for _ in range(_BUDGET_CAS_ATTEMPTS):
        try:
            meter.settle(
                run_id=run_id,
                expected_budget_version=_current_budget(repository, run_id).version,
                invocation_key=invocation_key,
                actual_usage=actual_usage,
            )
            return
        except Exception as error:
            if getattr(error, "code", None) != "deepsearch_budget_version_conflict":
                raise
            last_conflict = error
    assert last_conflict is not None
    raise last_conflict


def _reserve(
    repository: RuntimeArtifactStore,
    *,
    artifact: Artifact,
    resource_maxima: DeepSearchBudgetUsageV1,
):  # noqa: ANN202
    meter = DeepSearchBudgetMeter(repository)
    logical_operation_key = _operation_key(artifact)
    last_conflict: Exception | None = None
    for _ in range(_BUDGET_CAS_ATTEMPTS):
        budget = _current_budget(repository, artifact.run_id)
        logical_attempts = [
            reservation
            for reservation in budget.reservations
            if reservation.logical_operation_key == logical_operation_key
        ]
        unsettled = next(
            (reservation for reservation in logical_attempts if reservation.status == "reserved"),
            None,
        )
        if unsettled is not None:
            _settle(
                repository,
                run_id=artifact.run_id,
                invocation_key=unsettled.invocation_key,
                actual_usage=unsettled.resource_maxima,
            )
            continue
        physical_attempt = max(
            (reservation.physical_attempt for reservation in logical_attempts),
            default=0,
        ) + 1
        if physical_attempt > _MAX_PHYSICAL_ATTEMPTS:
            raise RuntimeError("deepsearch_artifact_recovery_exhausted")
        invocation_key = f"{logical_operation_key}:attempt:{physical_attempt}"
        try:
            return meter.reserve(
                run_id=artifact.run_id,
                expected_budget_version=budget.version,
                logical_operation_key=logical_operation_key,
                invocation_key=invocation_key,
                physical_attempt=physical_attempt,
                resource_maxima=resource_maxima,
                scope="standard",
            )
        except Exception as error:
            if getattr(error, "code", None) != "deepsearch_budget_version_conflict":
                raise
            last_conflict = error
    assert last_conflict is not None
    raise last_conflict


def save_runtime_artifact(
    repository: RuntimeArtifactStore,
    artifact: Artifact,
    *,
    planning_mode: AgentPlanningMode,
) -> Artifact:
    """Persist one runtime Artifact, charging only DeepSearch Runs."""

    if planning_mode is not AgentPlanningMode.DEEPSEARCH:
        return repository.save_artifact(artifact)

    artifact, content_bytes = _canonical_artifact(artifact)
    if len(content_bytes) > DEEPSEARCH_RUNTIME_ARTIFACT_MAX_BYTES:
        raise RuntimeError("deepsearch_artifact_too_large")
    usage = DeepSearchBudgetUsageV1(artifact_bytes=len(content_bytes))
    operation = _reserve(
        repository,
        artifact=artifact,
        resource_maxima=usage,
    )
    invocation_key = operation.reservation.invocation_key
    try:
        return repository.save_deepsearch_runtime_artifact(
            artifact=artifact,
            budget_invocation_key=invocation_key,
            actual_usage=usage,
        )
    except BaseException as error:
        try:
            _settle(
                repository,
                run_id=artifact.run_id,
                invocation_key=invocation_key,
                actual_usage=usage,
            )
        except Exception as settlement_error:
            error.add_note(f"DeepSearch Artifact budget settlement failed: {settlement_error}")
        raise
