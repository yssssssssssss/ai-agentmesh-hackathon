"""Fail-closed DeepSearch finalization built on durable stage checkpoints."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from time import monotonic
from typing import Protocol, TypeVar

from agentmesh.artifacts import (
    ArtifactAccessError,
    DeepSearchEvidenceManifestV1,
    DeepSearchReportSectionV1,
    DeepSearchReportV1,
    V1VerifiedArtifactStore,
)
from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.deepsearch.budget import (
    DeepSearchBudgetMeter,
    DeepSearchBudgetMutationResult,
)
from agentmesh.deepsearch.contracts import ProblemGraphV1, RequirementVersionV1
from agentmesh.deepsearch.reporting import (
    DEEPSEARCH_EVIDENCE_MANIFEST_MAX_BYTES,
    DEEPSEARCH_REPORT_MAX_BYTES,
    DeepSearchReportingError,
    build_deepsearch_report,
    build_deepsearch_report_artifacts,
    build_deterministic_evidence_digest,
    build_evidence_manifest_artifact,
    decide_deepsearch_terminal,
    evaluate_evidence_coverage,
    read_evidence_manifest_artifact,
)
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    Artifact,
    ArtifactVerificationState,
    DeepSearchBudgetReservationV1,
    DeepSearchBudgetUsageV1,
    DeepSearchBudgetV1,
    DeepSearchEvidenceCoverageV1,
    DeepSearchFinalizationStage,
    DeepSearchReviewOutcomeV1,
    DeepSearchSynthesisV1,
    SkillNodeResult,
    SkillPlan,
    SkillPlanNodeStatus,
    SkillPlanStatus,
    Source,
    now_utc,
)
from agentmesh.skill_runtime.finalization import PlanExecutionOutcome
from agentmesh.skill_runtime.universal_plan import covered_result_atom_ids

_TERMINAL_NODE_STATUSES = frozenset(
    {
        SkillPlanNodeStatus.COMPLETED,
        SkillPlanNodeStatus.FAILED,
        SkillPlanNodeStatus.SKIPPED,
        SkillPlanNodeStatus.CANCELLED,
    }
)
_FINALIZATION_TERMINAL_STATUSES = frozenset(
    {
        AgentRunStatus.COMPLETED,
        AgentRunStatus.PARTIAL,
        AgentRunStatus.FAILED,
        AgentRunStatus.CANCELLED,
    }
)
_REPORT_PERSISTENCE_ATTEMPTS = 3
_FINALIZATION_BUDGET_CAS_ATTEMPTS = 4
_MANIFEST_MAXIMA = DeepSearchBudgetUsageV1(
    active_seconds=30,
    artifact_bytes=DEEPSEARCH_EVIDENCE_MANIFEST_MAX_BYTES,
)
_COVERAGE_MAXIMA = DeepSearchBudgetUsageV1(active_seconds=15)
_DIGEST_MAXIMA = DeepSearchBudgetUsageV1(active_seconds=30)
_REPORT_MAXIMA = DeepSearchBudgetUsageV1(
    active_seconds=30,
    artifact_bytes=DEEPSEARCH_REPORT_MAX_BYTES,
)

_FinalizationResultT = TypeVar("_FinalizationResultT")


@dataclass(frozen=True, slots=True)
class _ReservedFinalizationOperation:
    reservation: DeepSearchBudgetReservationV1
    started_at: float


class _FinalizationOperationBusy(RuntimeError):
    pass


def _is_report_persistence_failure(error: Exception) -> bool:
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, (ArtifactAccessError, sqlite3.Error, OSError)):
            return True
        current = current.__cause__
    return False


def _finalization_budget_error_code(error: Exception) -> str | None:
    code = getattr(error, "code", None)
    if code in {"deepsearch_budget_exhausted", "deepsearch_recovery_exhausted"}:
        return code
    message = str(error)
    if message in {"deepsearch_budget_exhausted", "deepsearch_recovery_exhausted"}:
        return message
    return None

DeepSearchSynthesisRunner = Callable[
    [
        AgentRun,
        SkillPlan,
        RequirementVersionV1,
        ProblemGraphV1,
        Sequence[SkillNodeResult],
        DeepSearchEvidenceManifestV1,
        Mapping[str, Artifact],
        int,
        DeepSearchReviewOutcomeV1 | None,
    ],
    Awaitable[DeepSearchSynthesisV1],
]
DeepSearchReviewRunner = Callable[
    [
        AgentRun,
        SkillPlan,
        RequirementVersionV1,
        ProblemGraphV1,
        DeepSearchSynthesisV1,
        DeepSearchEvidenceManifestV1,
        Mapping[str, Artifact],
        datetime,
    ],
    Awaitable[DeepSearchReviewOutcomeV1],
]


class DeepSearchFinalizationRepository(Protocol):
    def get_skill_plan(self, plan_id: str) -> SkillPlan | None: ...

    def get_agent_run(self, run_id: str) -> AgentRun | None: ...

    def list_skill_node_results(self, plan_id: str) -> list[SkillNodeResult]: ...

    def get_active_deepsearch_requirement(self, run_id: str) -> dict[str, object] | None: ...

    def get_artifact(self, artifact_id: str) -> Artifact | None: ...

    def get_source(self, source_id: str) -> Source | None: ...

    def compare_and_swap_deepsearch_finalization(self, **kwargs: object) -> tuple[SkillPlan, AgentRun] | None: ...

    def commit_deepsearch_terminal_without_report(self, **kwargs: object) -> tuple[SkillPlan, AgentRun] | None: ...

    def commit_deepsearch_terminal_with_report(self, **kwargs: object) -> tuple[SkillPlan, AgentRun] | None: ...

    def fail_deepsearch_staging_report_and_commit_terminal(
        self, **kwargs: object
    ) -> tuple[SkillPlan, AgentRun] | None: ...

    def reserve_deepsearch_budget(self, **kwargs: object) -> DeepSearchBudgetMutationResult: ...

    def settle_deepsearch_budget(self, **kwargs: object) -> DeepSearchBudgetMutationResult: ...


def _nodes_terminal_input_hash(plan: SkillPlan, results: list[SkillNodeResult]) -> str:
    """Hash only durable node/result identity, never mutable presentation text."""

    evidence_projection = []
    for result in sorted(results, key=lambda item: (item.node_id, item.id)):
        evidence_items = getattr(result, "evidence_items", [])
        evidence_projection.append(
            {
                "id": result.id,
                "node_id": result.node_id,
                "attempt": result.attempt,
                "source_ids": sorted(source.id for source in result.sources),
                "artifact_ids": sorted(result.artifact_ids),
                "evidence_item_ids": sorted(item.id for item in evidence_items),
            }
        )
    return canonical_json_sha256(
        {
            "stage": DeepSearchFinalizationStage.NODES_TERMINAL,
            "plan_id": plan.id,
            "plan_version": plan.version,
            "plan_content_hash": plan.plan_content_hash,
            "nodes": [
                {
                    "id": node.id,
                    "status": node.status,
                    "attempt": node.attempt,
                    "error_code": node.error_code,
                }
                for node in sorted(plan.nodes, key=lambda item: item.id)
            ],
            "results": evidence_projection,
        }
    )


def _terminal_input_hash(
    plan: SkillPlan,
    terminal_status: AgentRunStatus,
    error_code: str,
) -> str:
    return canonical_json_sha256(
        {
            "stage": DeepSearchFinalizationStage.TERMINAL_COMMITTED,
            "from_stage": plan.finalization_stage,
            "plan_id": plan.id,
            "plan_version": plan.version,
            "finalization_version": plan.finalization_version,
            "terminal_status": terminal_status,
            "error_code": error_code,
        }
    )


def _checkpoint_input_hash(
    stage: DeepSearchFinalizationStage,
    payload: object,
) -> str:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="python")
    return canonical_json_sha256({"stage": stage, "payload": payload})


def _terminal_report_input_hash(
    *,
    plan: SkillPlan,
    report: Artifact,
    terminal_status: AgentRunStatus,
    error_code: str | None,
) -> str:
    return canonical_json_sha256(
        {
            "stage": DeepSearchFinalizationStage.TERMINAL_COMMITTED,
            "from_stage": plan.finalization_stage,
            "plan_id": plan.id,
            "plan_version": plan.version,
            "finalization_version": plan.finalization_version,
            "terminal_status": terminal_status,
            "error_code": error_code,
            "report_artifact_id": report.id,
            "report_content_hash": report.content_hash,
        }
    )


def _not_run_review(
    synthesis: DeepSearchSynthesisV1,
    reason_code: str,
) -> DeepSearchReviewOutcomeV1:
    return DeepSearchReviewOutcomeV1(
        revision_count=synthesis.revision_count,
        synthesis_content_hash=canonical_json_sha256(synthesis.model_dump(mode="python")),
        outcome="not_run",
        reason_code=reason_code,
    )


def _error_review(
    synthesis: DeepSearchSynthesisV1,
    reason_code: str,
) -> DeepSearchReviewOutcomeV1:
    return DeepSearchReviewOutcomeV1(
        revision_count=synthesis.revision_count,
        synthesis_content_hash=canonical_json_sha256(synthesis.model_dump(mode="python")),
        outcome="error",
        reason_code=reason_code,
    )


def terminate_deepsearch_without_report(
    repository: DeepSearchFinalizationRepository,
    *,
    run_id: str,
    plan_id: str,
    terminal_status: AgentRunStatus,
    error_code: str | None,
) -> PlanExecutionOutcome:
    """Commit a fail-closed DeepSearch terminal state from fresh persisted data."""

    plan = repository.get_skill_plan(plan_id)
    run = repository.get_agent_run(run_id)
    expected_plan_status = {
        AgentRunStatus.FAILED: SkillPlanStatus.FAILED,
        AgentRunStatus.CANCELLED: SkillPlanStatus.CANCELLED,
    }.get(terminal_status)
    if (
        plan is not None
        and run is not None
        and expected_plan_status is not None
        and plan.status is expected_plan_status
        and run.status is terminal_status
        and plan.finalization_stage is DeepSearchFinalizationStage.TERMINAL_COMMITTED
    ):
        return PlanExecutionOutcome(plan=plan, run=run)
    if (
        plan is None
        or run is None
        or plan.run_id != run.id
        or run.plan_id != plan.id
        or plan.planning_mode is not AgentPlanningMode.DEEPSEARCH
        or run.planning_mode is not AgentPlanningMode.DEEPSEARCH
    ):
        raise RuntimeError("deepsearch_finalization_state_conflict")
    if terminal_status not in {AgentRunStatus.FAILED, AgentRunStatus.CANCELLED}:
        raise ValueError("DeepSearch terminal status must be failed or cancelled")
    stable_error_code = error_code or terminal_status.value
    terminal = repository.commit_deepsearch_terminal_without_report(
        run_id=run.id,
        plan_id=plan.id,
        expected_plan_version=plan.version,
        expected_finalization_version=plan.finalization_version,
        expected_stage=plan.finalization_stage,
        expected_plan_status=plan.status,
        expected_run_status=run.status,
        terminal_status=terminal_status,
        error_code=error_code,
        input_hash=_terminal_input_hash(plan, terminal_status, stable_error_code),
        events=[
            (
                "run_failed" if terminal_status is AgentRunStatus.FAILED else "run_cancelled",
                {"plan_id": plan.id, "error_code": error_code},
            )
        ],
    )
    if terminal is None:
        raise RuntimeError("deepsearch_finalization_state_conflict")
    terminal_plan, terminal_run = terminal
    return PlanExecutionOutcome(plan=terminal_plan, run=terminal_run)


_DEEPSEARCH_REPORT_SYNTHESIS_LABELS = {
    "design_analysis": "设计分析",
    "executive_summary": "执行摘要",
    "summary": "总结",
    "synthesis": "综合结论",
    "report": "综合报告",
    "strategy_map": "策略地图",
    "mental_model": "用户心智模型",
    "design_principles": "设计原则",
    "opportunity_list": "机会点",
    "prioritized_actions": "P0/P1/P2 行动",
    "roadmap": "实施路径",
    "metrics_plan": "指标与验证计划",
    "comparison_table": "对比结论",
}


def _with_required_synthesis_sections(
    *,
    plan: SkillPlan,
    report: DeepSearchReportV1,
) -> DeepSearchReportV1:
    snapshot = plan.candidate_snapshot
    if snapshot is None or not snapshot.required_synthesis_output_ids:
        return report
    claim_ids = [claim.id for claim in report.claims]
    claim_text = {claim.id: claim.text for claim in report.claims}
    sections = list(report.sections)
    rendered_parts: list[str] = []
    existing_ids = {section.section_id for section in sections}
    for output_id in snapshot.required_synthesis_output_ids:
        label = _DEEPSEARCH_REPORT_SYNTHESIS_LABELS.get(output_id)
        if label is None or not claim_ids:
            continue
        section_id = f"synthesis_output:{output_id}"
        if section_id not in existing_ids:
            sections.append(
                DeepSearchReportSectionV1(
                    section_id=section_id,
                    server_heading=label,
                    claim_ids=claim_ids,
                )
            )
            existing_ids.add(section_id)
        rendered_parts.append(
            f"## {label}\n\n"
            + "\n\n".join(claim_text[claim_id] for claim_id in claim_ids)
        )
    rendered_text = report.rendered_text
    if rendered_parts:
        rendered_text = rendered_text.rstrip() + "\n\n" + "\n\n".join(rendered_parts)
    return DeepSearchReportV1.model_validate(
        {
            **report.model_dump(mode="python"),
            "sections": sections,
            "rendered_text": rendered_text,
        }
    )


def _universal_deepsearch_obligations_complete(
    *,
    plan: SkillPlan,
    results: list[SkillNodeResult],
    coverage: DeepSearchEvidenceCoverageV1,
    evidence_artifacts: Mapping[str, Artifact],
    synthesis: DeepSearchSynthesisV1,
    graph: ProblemGraphV1,
) -> bool:
    snapshot = plan.candidate_snapshot
    if snapshot is None:
        return True
    valid_artifact_ids = {
        artifact.id
        for artifact in evidence_artifacts.values()
        if artifact.verification_state is ArtifactVerificationState.SEALED
    }
    covered = set(
        covered_result_atom_ids(
            plan=plan,
            results=results,
            evidence_artifact_valid=lambda artifact_id: artifact_id
            in valid_artifact_ids,
        )
    )
    required_atom_ids = {atom.id for atom in snapshot.required_coverage_atoms}
    if not required_atom_ids.issubset(covered):
        return False
    result_node_ids = {result.node_id for result in results}
    if any(
        criterion not in result.completion_criteria_met
        for node in plan.nodes
        if node.status is SkillPlanNodeStatus.COMPLETED
        for criterion in node.completion_criteria
        for result in results
        if result.node_id == node.id
    ):
        return False
    if any(
        node.required
        and (
            node.status is not SkillPlanNodeStatus.COMPLETED
            or node.id not in result_node_ids
        )
        for node in plan.nodes
    ):
        return False
    if plan.capability_gaps:
        return False
    required_synthesis = set(snapshot.required_synthesis_output_ids)
    if required_synthesis and (
        not required_synthesis.issubset(_DEEPSEARCH_REPORT_SYNTHESIS_LABELS)
        or not synthesis.claims
        or not graph.questions
    ):
        return False
    evidence_required = any(
        atom.id == "evidence:trusted_external_path"
        for atom in snapshot.required_coverage_atoms
    )
    return not evidence_required or (
        coverage.passed and coverage.external_evidence_is_real
    )


class DeepSearchFinalizer:
    """Own every DeepSearch checkpoint, report seal, and terminal write."""

    def __init__(
        self,
        repository: DeepSearchFinalizationRepository,
        *,
        synthesis_runner: DeepSearchSynthesisRunner | None = None,
        review_runner: DeepSearchReviewRunner | None = None,
        clock: Callable[[], datetime] = now_utc,
        monotonic_clock: Callable[[], float] = monotonic,
        recover_unsettled: bool = False,
    ) -> None:
        self.repository = repository
        self.synthesis_runner = synthesis_runner
        self.review_runner = review_runner
        self.clock = clock
        self.monotonic_clock = monotonic_clock
        self.recover_unsettled = recover_unsettled

    @staticmethod
    def _operation_key(
        *,
        run: AgentRun,
        plan: SkillPlan,
        operation: str,
        identity: object,
    ) -> str:
        digest = canonical_json_sha256(
            {
                "run_id": run.id,
                "requirement_version_id": plan.requirement_version_id,
                "plan_id": plan.id,
                "plan_version": plan.version,
                "operation": operation,
                "identity": identity,
            }
        )
        return f"finalization:{operation}:{digest}"

    def _current_budget(self, run_id: str) -> DeepSearchBudgetV1:
        run = self.repository.get_agent_run(run_id)
        if run is None:
            raise RuntimeError("deepsearch_budget_run_not_found")
        if run.deepsearch_budget is None:
            raise RuntimeError("deepsearch_budget_run_invalid")
        return run.deepsearch_budget

    def _settle_budget(
        self,
        *,
        run_id: str,
        invocation_key: str,
        actual_usage: DeepSearchBudgetUsageV1,
    ) -> DeepSearchBudgetMutationResult:
        meter = DeepSearchBudgetMeter(self.repository)
        last_conflict: Exception | None = None
        for _ in range(_FINALIZATION_BUDGET_CAS_ATTEMPTS):
            budget = self._current_budget(run_id)
            try:
                return meter.settle(
                    run_id=run_id,
                    expected_budget_version=budget.version,
                    invocation_key=invocation_key,
                    actual_usage=actual_usage,
                )
            except Exception as error:
                if getattr(error, "code", None) != "deepsearch_budget_version_conflict":
                    raise
                last_conflict = error
        assert last_conflict is not None
        raise last_conflict

    def _reserve_finalization_operation(
        self,
        *,
        run: AgentRun,
        plan: SkillPlan,
        operation: str,
        identity: object,
        resource_maxima: DeepSearchBudgetUsageV1,
    ) -> _ReservedFinalizationOperation:
        logical_operation_key = self._operation_key(
            run=run,
            plan=plan,
            operation=operation,
            identity=identity,
        )
        meter = DeepSearchBudgetMeter(self.repository)
        last_conflict: Exception | None = None
        for _ in range(_FINALIZATION_BUDGET_CAS_ATTEMPTS):
            budget = self._current_budget(run.id)
            logical_attempts = [
                item
                for item in budget.reservations
                if item.logical_operation_key == logical_operation_key
            ]
            unsettled = next(
                (item for item in logical_attempts if item.status == "reserved"),
                None,
            )
            if unsettled is not None:
                if not self.recover_unsettled:
                    raise _FinalizationOperationBusy
                self._settle_failed_operation(
                    run_id=run.id,
                    operation=_ReservedFinalizationOperation(
                        reservation=unsettled,
                        started_at=self.monotonic_clock(),
                    ),
                )
                continue
            physical_attempt = max(
                (item.physical_attempt for item in logical_attempts),
                default=0,
            ) + 1
            if physical_attempt > _REPORT_PERSISTENCE_ATTEMPTS:
                raise RuntimeError("deepsearch_recovery_exhausted")
            invocation_key = f"{logical_operation_key}:attempt:{physical_attempt}"
            try:
                result = meter.reserve(
                    run_id=run.id,
                    expected_budget_version=budget.version,
                    logical_operation_key=logical_operation_key,
                    invocation_key=invocation_key,
                    physical_attempt=physical_attempt,
                    resource_maxima=resource_maxima,
                    scope="finalization",
                )
                if result.replayed and not self.recover_unsettled:
                    raise _FinalizationOperationBusy
                return _ReservedFinalizationOperation(
                    reservation=result.reservation,
                    started_at=self.monotonic_clock(),
                )
            except Exception as error:
                if getattr(error, "code", None) not in {
                    "deepsearch_budget_version_conflict",
                    "deepsearch_budget_previous_attempt_unsettled",
                }:
                    raise
                last_conflict = error
        assert last_conflict is not None
        raise last_conflict

    def _actual_usage(
        self,
        operation: _ReservedFinalizationOperation,
        *,
        artifact_bytes: int = 0,
    ) -> DeepSearchBudgetUsageV1:
        maxima = operation.reservation.resource_maxima
        return DeepSearchBudgetUsageV1(
            active_seconds=min(
                max(self.monotonic_clock() - operation.started_at, 0),
                maxima.active_seconds,
            ),
            artifact_bytes=artifact_bytes,
        )

    def _remaining_operation_seconds(
        self,
        operation: _ReservedFinalizationOperation,
    ) -> float:
        elapsed = max(self.monotonic_clock() - operation.started_at, 0)
        return operation.reservation.resource_maxima.active_seconds - elapsed

    def _require_operation_within_timeout(
        self,
        operation: _ReservedFinalizationOperation,
    ) -> None:
        if self._remaining_operation_seconds(operation) < 0:
            raise DeepSearchReportingError("deepsearch_budget_exhausted")

    async def _run_reserved_builder(
        self,
        operation: _ReservedFinalizationOperation,
        builder: Callable[[], _FinalizationResultT],
    ) -> _FinalizationResultT:
        """Time-bound one pure finalization build under its persisted reservation."""

        remaining = self._remaining_operation_seconds(operation)
        if remaining <= 0:
            raise DeepSearchReportingError("deepsearch_budget_exhausted")
        try:
            result = await asyncio.wait_for(asyncio.to_thread(builder), timeout=remaining)
        except TimeoutError as error:
            raise DeepSearchReportingError("deepsearch_budget_exhausted") from error
        self._require_operation_within_timeout(operation)
        return result

    def _settle_failed_operation(
        self,
        *,
        run_id: str,
        operation: _ReservedFinalizationOperation,
    ) -> None:
        invocation_key = operation.reservation.invocation_key
        current = next(
            (
                item
                for item in self._current_budget(run_id).reservations
                if item.invocation_key == invocation_key
            ),
            None,
        )
        if current is not None and current.status == "settled":
            return
        try:
            self._settle_budget(
                run_id=run_id,
                invocation_key=invocation_key,
                actual_usage=operation.reservation.resource_maxima,
            )
        except Exception as error:
            if getattr(error, "code", None) != "deepsearch_budget_settlement_conflict":
                raise
            current = next(
                (
                    item
                    for item in self._current_budget(run_id).reservations
                    if item.invocation_key == invocation_key
                ),
                None,
            )
            if current is None or current.status != "settled":
                raise

    @staticmethod
    def _require_active_identity(
        plan: SkillPlan | None,
        run: AgentRun | None,
        *,
        run_id: str,
        plan_id: str,
        expected_plan_version: int,
    ) -> tuple[SkillPlan, AgentRun]:
        if (
            plan is None
            or run is None
            or plan.id != plan_id
            or run.id != run_id
            or plan.run_id != run.id
            or run.plan_id != plan.id
            or plan.version != expected_plan_version
            or plan.planning_mode is not AgentPlanningMode.DEEPSEARCH
            or run.planning_mode is not AgentPlanningMode.DEEPSEARCH
            or plan.status is not SkillPlanStatus.RUNNING
            or run.status is not AgentRunStatus.RUNNING
        ):
            raise RuntimeError("deepsearch_finalization_state_conflict")
        if any(node.status not in _TERMINAL_NODE_STATUSES for node in plan.nodes):
            raise RuntimeError("deepsearch_nodes_not_terminal")
        return plan, run

    def _load_inputs(
        self,
        *,
        plan: SkillPlan,
        run: AgentRun,
    ) -> tuple[
        RequirementVersionV1,
        ProblemGraphV1,
        list[SkillNodeResult],
        dict[str, Artifact],
    ]:
        try:
            requirement_payload = self.repository.get_active_deepsearch_requirement(run.id)
            requirement = RequirementVersionV1.model_validate(requirement_payload)
            graph = ProblemGraphV1.model_validate(plan.problem_graph)
        except (AttributeError, TypeError, ValueError) as error:
            raise DeepSearchReportingError() from error
        results = self.repository.list_skill_node_results(plan.id)
        evidence_artifact_ids = {
            item.evidence_artifact_id for result in results for item in result.evidence_items
        }
        evidence_artifacts: dict[str, Artifact] = {}
        for artifact_id in evidence_artifact_ids:
            artifact = self.repository.get_artifact(artifact_id)
            if artifact is None:
                raise DeepSearchReportingError()
            evidence_artifacts[artifact_id] = artifact
        return requirement, graph, results, evidence_artifacts

    def _load_manifest(
        self,
        *,
        plan: SkillPlan,
        run: AgentRun,
    ) -> tuple[DeepSearchEvidenceManifestV1, Artifact]:
        artifact_id = plan.evidence_manifest_artifact_id
        artifact = self.repository.get_artifact(artifact_id) if artifact_id is not None else None
        if (
            artifact is None
            or plan.evidence_manifest_hash is None
            or artifact.content_hash != plan.evidence_manifest_hash
        ):
            raise DeepSearchReportingError()
        return read_evidence_manifest_artifact(run=run, plan=plan, artifact=artifact), artifact

    async def _build_synthesis(
        self,
        *,
        run: AgentRun,
        plan: SkillPlan,
        requirement: RequirementVersionV1,
        graph: ProblemGraphV1,
        results: list[SkillNodeResult],
        manifest: DeepSearchEvidenceManifestV1,
        evidence_artifacts: Mapping[str, Artifact],
        revision_count: int,
        prior_review: DeepSearchReviewOutcomeV1 | None,
    ) -> tuple[
        DeepSearchSynthesisV1,
        _ReservedFinalizationOperation | None,
        DeepSearchBudgetUsageV1 | None,
    ]:
        if self.synthesis_runner is not None:
            try:
                synthesis = await self.synthesis_runner(
                    run,
                    plan,
                    requirement,
                    graph,
                    results,
                    manifest,
                    evidence_artifacts,
                    revision_count,
                    prior_review,
                )
                synthesis = DeepSearchSynthesisV1.model_validate(
                    synthesis.model_dump(mode="python")
                )
                if (
                    synthesis.revision_count != revision_count
                    or synthesis.synthesis_mode != "model"
                ):
                    raise DeepSearchReportingError("deepsearch_synthesis_invalid")
                return synthesis, None, None
            except Exception:
                pass
        operation = self._reserve_finalization_operation(
            run=run,
            plan=plan,
            operation=f"digest-v{revision_count}",
            identity={
                "manifest_hash": plan.evidence_manifest_hash,
                "prior_review": (
                    prior_review.model_dump(mode="python")
                    if prior_review is not None
                    else None
                ),
            },
            resource_maxima=_DIGEST_MAXIMA,
        )
        try:
            synthesis = await self._run_reserved_builder(
                operation,
                partial(
                    build_deterministic_evidence_digest,
                    run=run,
                    plan=plan,
                    manifest=manifest,
                    evidence_artifacts=evidence_artifacts,
                    revision_count=revision_count,
                ),
            )
        except DeepSearchReportingError:
            raise
        except Exception as error:
            raise DeepSearchReportingError("deepsearch_delivery_unavailable") from error
        return synthesis, operation, self._actual_usage(operation)

    async def _build_review(
        self,
        *,
        run: AgentRun,
        plan: SkillPlan,
        requirement: RequirementVersionV1,
        graph: ProblemGraphV1,
        synthesis: DeepSearchSynthesisV1,
        coverage: DeepSearchEvidenceCoverageV1,
        manifest: DeepSearchEvidenceManifestV1,
        evidence_artifacts: Mapping[str, Artifact],
    ) -> DeepSearchReviewOutcomeV1:
        if not coverage.passed:
            return _not_run_review(synthesis, "coverage_failed")
        if synthesis.synthesis_mode == "deterministic_evidence_digest":
            return _not_run_review(synthesis, "deterministic_digest")
        if self.review_runner is None:
            return _not_run_review(synthesis, "budget_unavailable")
        try:
            outcome = await self.review_runner(
                run,
                plan,
                requirement,
                graph,
                synthesis,
                manifest,
                evidence_artifacts,
                self.clock(),
            )
            outcome = DeepSearchReviewOutcomeV1.model_validate(
                outcome.model_dump(mode="python")
            )
            synthesis_hash = canonical_json_sha256(synthesis.model_dump(mode="python"))
            if (
                outcome.revision_count != synthesis.revision_count
                or outcome.synthesis_content_hash != synthesis_hash
            ):
                raise DeepSearchReportingError("deepsearch_review_invalid")
            return outcome
        except DeepSearchReportingError:
            return _error_review(synthesis, "deepsearch_review_invalid")
        except Exception as error:
            if getattr(error, "code", "") == "deepsearch_budget_exhausted":
                return _not_run_review(synthesis, "budget_unavailable")
            return _error_review(synthesis, "deepsearch_review_invalid")

    def _load_sources(
        self,
        synthesis: DeepSearchSynthesisV1,
    ) -> dict[str, Source]:
        sources: dict[str, Source] = {}
        for source_id in {
            source_id for claim in synthesis.claims for source_id in claim.source_ids
        }:
            source = self.repository.get_source(source_id)
            if source is None:
                raise DeepSearchReportingError()
            sources[source_id] = source
        return sources

    def _build_report_for_current_revision(
        self,
        *,
        run: AgentRun,
        plan: SkillPlan,
        requirement: RequirementVersionV1,
        graph: ProblemGraphV1,
        results: Sequence[SkillNodeResult],
        manifest: DeepSearchEvidenceManifestV1,
        manifest_artifact: Artifact,
        evidence_artifacts: Mapping[str, Artifact],
        synthesis: DeepSearchSynthesisV1,
        coverage: DeepSearchEvidenceCoverageV1,
        review_outcome: DeepSearchReviewOutcomeV1,
        complete_candidate: bool,
    ) -> DeepSearchReportV1:
        report = build_deepsearch_report(
            run=run,
            plan=plan,
            requirement=requirement,
            graph=graph,
            results=results,
            manifest=manifest,
            manifest_artifact=manifest_artifact,
            evidence_artifacts=evidence_artifacts,
            sources=self._load_sources(synthesis),
            synthesis=synthesis,
            coverage=coverage,
            review_outcome=review_outcome,
            report_status="complete" if complete_candidate else "partial",
        )
        return _with_required_synthesis_sections(plan=plan, report=report)

    def _commit_terminal_report_attempt(
        self,
        *,
        plan: SkillPlan,
        run: AgentRun,
        staging: Artifact,
        sealed: Artifact,
        terminal_status: AgentRunStatus,
        error_code: str | None,
        budget_operation: _ReservedFinalizationOperation,
    ) -> PlanExecutionOutcome | None:
        """Persist one physical Report attempt and settle it with the terminal CAS."""

        artifact_store = V1VerifiedArtifactStore(self.repository)  # type: ignore[arg-type]
        events = [
            (
                "run_completed"
                if terminal_status is AgentRunStatus.COMPLETED
                else "run_partial",
                {
                    "plan_id": plan.id,
                    "report_artifact_id": sealed.id,
                    "error_code": error_code,
                },
            )
        ]
        input_hash = _terminal_report_input_hash(
            plan=plan,
            report=sealed,
            terminal_status=terminal_status,
            error_code=error_code,
        )
        artifact_store.create_staging_report(staging)
        self._require_operation_within_timeout(budget_operation)
        terminal = self.repository.commit_deepsearch_terminal_with_report(
            run_id=run.id,
            plan_id=plan.id,
            expected_plan_version=plan.version,
            expected_finalization_version=plan.finalization_version,
            expected_stage=plan.finalization_stage,
            expected_plan_status=plan.status,
            expected_run_status=run.status,
            staging_artifact_id=staging.id,
            sealed_report=sealed,
            terminal_status=terminal_status,
            error_code=error_code,
            input_hash=input_hash,
            events=events,
            budget_invocation_key=budget_operation.reservation.invocation_key,
            budget_actual_usage=self._actual_usage(
                budget_operation,
                artifact_bytes=sealed.size_bytes,
            ),
        )
        if terminal is None:
            return None
        terminal_plan, terminal_run = terminal
        return PlanExecutionOutcome(plan=terminal_plan, run=terminal_run)

    def _fail_staging_report(
        self,
        *,
        plan: SkillPlan,
        run: AgentRun,
        staging: Artifact,
        error_code: str,
    ) -> PlanExecutionOutcome | None:
        """Close a durable STAGING report and the owning Run in one transaction."""

        persisted_report = self.repository.get_artifact(staging.id)
        if (
            persisted_report is None
            or persisted_report.verification_state is not ArtifactVerificationState.STAGING
        ):
            if persisted_report is not None:
                return None
            return terminate_deepsearch_without_report(
                self.repository,
                run_id=run.id,
                plan_id=plan.id,
                terminal_status=AgentRunStatus.FAILED,
                error_code=error_code,
            )

        failed_report = persisted_report.model_copy(
            update={
                "verification_state": ArtifactVerificationState.FAILED,
                "updated_at": self.clock(),
            }
        )
        terminal = self.repository.fail_deepsearch_staging_report_and_commit_terminal(
            run_id=run.id,
            plan_id=plan.id,
            expected_plan_version=plan.version,
            expected_finalization_version=plan.finalization_version,
            expected_stage=plan.finalization_stage,
            expected_plan_status=plan.status,
            expected_run_status=run.status,
            staging_artifact_id=persisted_report.id,
            failed_report=failed_report,
            error_code=error_code,
            input_hash=_terminal_report_input_hash(
                plan=plan,
                report=failed_report,
                terminal_status=AgentRunStatus.FAILED,
                error_code=error_code,
            ),
            events=[
                (
                    "run_failed",
                    {
                        "plan_id": plan.id,
                        "report_artifact_id": persisted_report.id,
                        "error_code": error_code,
                    },
                )
            ],
        )
        if terminal is None:
            return None
        terminal_plan, terminal_run = terminal
        return PlanExecutionOutcome(plan=terminal_plan, run=terminal_run)

    async def _finish_with_current_revision(
        self,
        *,
        plan: SkillPlan,
        run: AgentRun,
        requirement: RequirementVersionV1,
        graph: ProblemGraphV1,
        results: list[SkillNodeResult],
        manifest: DeepSearchEvidenceManifestV1,
        manifest_artifact: Artifact,
        evidence_artifacts: Mapping[str, Artifact],
    ) -> PlanExecutionOutcome | None:
        if not plan.deepsearch_syntheses or not plan.review_outcomes or plan.evidence_coverage is None:
            raise DeepSearchReportingError()
        synthesis = plan.deepsearch_syntheses[-1]
        coverage = plan.evidence_coverage
        review_outcome = plan.review_outcomes[-1]
        preflight = decide_deepsearch_terminal(
            plan=plan,
            synthesis=synthesis,
            coverage=coverage,
            review_outcome=review_outcome,
            safe_partial_report=False,
            report_available=False,
        )
        if preflight.status is AgentRunStatus.RUNNING:
            return None
        if preflight.error_code == "deepsearch_evidence_integrity_failed":
            return terminate_deepsearch_without_report(
                self.repository,
                run_id=run.id,
                plan_id=plan.id,
                terminal_status=AgentRunStatus.FAILED,
                error_code=preflight.error_code,
            )
        complete_candidate = (
            all(node.status is SkillPlanNodeStatus.COMPLETED for node in plan.nodes)
            and coverage.passed
            and review_outcome.outcome == "pass"
            and synthesis.synthesis_mode == "model"
            and _universal_deepsearch_obligations_complete(
                plan=plan,
                results=results,
                coverage=coverage,
                evidence_artifacts=evidence_artifacts,
                synthesis=synthesis,
                graph=graph,
            )
        )
        operation_identity = {
            "synthesis_hash": coverage.synthesis_content_hash,
            "coverage_hash": canonical_json_sha256(coverage.model_dump(mode="python")),
            "review_hash": canonical_json_sha256(review_outcome.model_dump(mode="python")),
        }
        last_staging: Artifact | None = None
        for _attempt in range(_REPORT_PERSISTENCE_ATTEMPTS):
            try:
                operation = self._reserve_finalization_operation(
                    run=run,
                    plan=plan,
                    operation=f"report-v{synthesis.revision_count}",
                    identity=operation_identity,
                    resource_maxima=_REPORT_MAXIMA,
                )
            except Exception as error:
                code = _finalization_budget_error_code(error)
                if code is not None and last_staging is not None:
                    return self._fail_staging_report(
                        plan=plan,
                        run=run,
                        staging=last_staging,
                        error_code=code,
                    )
                raise
            try:
                report = await self._run_reserved_builder(
                    operation,
                    partial(
                        self._build_report_for_current_revision,
                        run=run,
                        plan=plan,
                        requirement=requirement,
                        graph=graph,
                        results=results,
                        manifest=manifest,
                        manifest_artifact=manifest_artifact,
                        evidence_artifacts=evidence_artifacts,
                        synthesis=synthesis,
                        coverage=coverage,
                        review_outcome=review_outcome,
                        complete_candidate=complete_candidate,
                    ),
                )
            except DeepSearchReportingError:
                raise
            except Exception as error:
                raise DeepSearchReportingError("deepsearch_delivery_unavailable") from error

            safe_partial_report = report.report_status == "partial"
            decision = decide_deepsearch_terminal(
                plan=plan,
                synthesis=synthesis,
                coverage=coverage,
                review_outcome=review_outcome,
                safe_partial_report=safe_partial_report,
                report_available=True,
            )
            if decision.status not in {
                AgentRunStatus.COMPLETED,
                AgentRunStatus.PARTIAL,
            }:
                if decision.status is AgentRunStatus.RUNNING:
                    self._settle_budget(
                        run_id=run.id,
                        invocation_key=operation.reservation.invocation_key,
                        actual_usage=self._actual_usage(operation),
                    )
                    return None
                if decision.status is AgentRunStatus.FAILED:
                    return terminate_deepsearch_without_report(
                        self.repository,
                        run_id=run.id,
                        plan_id=plan.id,
                        terminal_status=AgentRunStatus.FAILED,
                        error_code=decision.error_code,
                    )
                raise DeepSearchReportingError("deepsearch_delivery_unavailable")

            try:
                staging, sealed = await self._run_reserved_builder(
                    operation,
                    partial(
                        build_deepsearch_report_artifacts,
                        run=run,
                        plan=plan,
                        report=report,
                        created_at=plan.updated_at,
                    ),
                )
            except DeepSearchReportingError:
                raise
            except Exception as error:
                raise DeepSearchReportingError("deepsearch_delivery_unavailable") from error
            last_staging = staging
            try:
                outcome = self._commit_terminal_report_attempt(
                    plan=plan,
                    run=run,
                    staging=staging,
                    sealed=sealed,
                    terminal_status=decision.status,
                    error_code=decision.error_code,
                    budget_operation=operation,
                )
            except DeepSearchReportingError as error:
                return self._fail_staging_report(
                    plan=plan,
                    run=run,
                    staging=staging,
                    error_code=error.code,
                )
            except Exception as error:
                budget_error_code = _finalization_budget_error_code(error)
                if budget_error_code is not None:
                    return self._fail_staging_report(
                        plan=plan,
                        run=run,
                        staging=staging,
                        error_code=budget_error_code,
                    )
                self._settle_failed_operation(run_id=run.id, operation=operation)
                if not _is_report_persistence_failure(error):
                    raise
                current_plan = self.repository.get_skill_plan(plan.id)
                current_run = self.repository.get_agent_run(run.id)
                if (
                    current_plan is None
                    or current_run is None
                    or current_plan.finalization_stage is not plan.finalization_stage
                    or current_plan.status is not SkillPlanStatus.RUNNING
                    or current_run.status is not AgentRunStatus.RUNNING
                ):
                    return None
                continue
            return outcome

        assert last_staging is not None
        return self._fail_staging_report(
            plan=plan,
            run=run,
            staging=last_staging,
            error_code="deepsearch_report_persistence_failed",
        )

    async def finalize(
        self,
        *,
        run_id: str,
        plan_id: str,
        expected_plan_version: int,
    ) -> PlanExecutionOutcome:
        for _ in range(64):
            current_plan = self.repository.get_skill_plan(plan_id)
            current_run = self.repository.get_agent_run(run_id)
            if (
                current_plan is not None
                and current_run is not None
                and current_plan.finalization_stage
                is DeepSearchFinalizationStage.TERMINAL_COMMITTED
                and current_run.status in _FINALIZATION_TERMINAL_STATUSES
            ):
                return PlanExecutionOutcome(plan=current_plan, run=current_run)
            try:
                plan, run = self._require_active_identity(
                    current_plan,
                    current_run,
                    run_id=run_id,
                    plan_id=plan_id,
                    expected_plan_version=expected_plan_version,
                )
            except RuntimeError:
                refreshed_plan = self.repository.get_skill_plan(plan_id)
                refreshed_run = self.repository.get_agent_run(run_id)
                if (
                    refreshed_plan is not None
                    and refreshed_run is not None
                    and refreshed_plan.finalization_stage
                    is DeepSearchFinalizationStage.TERMINAL_COMMITTED
                    and refreshed_run.status in _FINALIZATION_TERMINAL_STATUSES
                ):
                    return PlanExecutionOutcome(plan=refreshed_plan, run=refreshed_run)
                if refreshed_plan != current_plan or refreshed_run != current_run:
                    continue
                raise
            try:
                stage = plan.finalization_stage
                if stage is DeepSearchFinalizationStage.NONE:
                    results = self.repository.list_skill_node_results(plan.id)
                    checkpoint = self.repository.compare_and_swap_deepsearch_finalization(
                        run_id=run.id,
                        plan_id=plan.id,
                        expected_plan_version=plan.version,
                        expected_finalization_version=plan.finalization_version,
                        expected_stage=stage,
                        target_stage=DeepSearchFinalizationStage.NODES_TERMINAL,
                        input_hash=_nodes_terminal_input_hash(plan, results),
                    )
                    if checkpoint is None:
                        continue
                    continue

                requirement, graph, results, evidence_artifacts = self._load_inputs(
                    plan=plan,
                    run=run,
                )
                if stage is DeepSearchFinalizationStage.NODES_TERMINAL:
                    checkpoint = None
                    for _attempt in range(_REPORT_PERSISTENCE_ATTEMPTS):
                        operation = self._reserve_finalization_operation(
                            run=run,
                            plan=plan,
                            operation="manifest",
                            identity=plan.finalization_input_hashes.get(
                                DeepSearchFinalizationStage.NODES_TERMINAL
                            ),
                            resource_maxima=_MANIFEST_MAXIMA,
                        )
                        try:
                            manifest, manifest_artifact = await self._run_reserved_builder(
                                operation,
                                partial(
                                    build_evidence_manifest_artifact,
                                    run=run,
                                    plan=plan,
                                    requirement=requirement,
                                    graph=graph,
                                    results=results,
                                    evidence_artifacts=evidence_artifacts,
                                    created_at=plan.updated_at,
                                ),
                            )
                        except DeepSearchReportingError:
                            raise
                        except Exception as error:
                            raise DeepSearchReportingError(
                                "deepsearch_delivery_unavailable"
                            ) from error
                        try:
                            checkpoint = self.repository.compare_and_swap_deepsearch_finalization(
                                run_id=run.id,
                                plan_id=plan.id,
                                expected_plan_version=plan.version,
                                expected_finalization_version=plan.finalization_version,
                                expected_stage=stage,
                                target_stage=DeepSearchFinalizationStage.EVIDENCE_MANIFEST_SEALED,
                                input_hash=_checkpoint_input_hash(
                                    DeepSearchFinalizationStage.EVIDENCE_MANIFEST_SEALED,
                                    manifest,
                                ),
                                evidence_manifest_artifact=manifest_artifact,
                                budget_invocation_key=operation.reservation.invocation_key,
                                budget_actual_usage=self._actual_usage(
                                    operation,
                                    artifact_bytes=manifest_artifact.size_bytes,
                                ),
                            )
                        except Exception as error:
                            budget_error_code = _finalization_budget_error_code(error)
                            if budget_error_code is not None:
                                raise DeepSearchReportingError(
                                    budget_error_code
                                ) from error
                            self._settle_failed_operation(
                                run_id=run.id,
                                operation=operation,
                            )
                            if not _is_report_persistence_failure(error):
                                raise
                            current_plan = self.repository.get_skill_plan(plan.id)
                            current_run = self.repository.get_agent_run(run.id)
                            if (
                                current_plan is None
                                or current_run is None
                                or current_plan.finalization_stage is not stage
                                or current_plan.status is not SkillPlanStatus.RUNNING
                                or current_run.status is not AgentRunStatus.RUNNING
                            ):
                                checkpoint = None
                                break
                            continue
                        break
                    else:
                        raise RuntimeError("deepsearch_recovery_exhausted")
                elif stage in {
                    DeepSearchFinalizationStage.EVIDENCE_MANIFEST_SEALED,
                    DeepSearchFinalizationStage.REVIEW_V0_CHECKED,
                }:
                    manifest, _manifest_artifact = self._load_manifest(plan=plan, run=run)
                    revision_count = (
                        0
                        if stage is DeepSearchFinalizationStage.EVIDENCE_MANIFEST_SEALED
                        else 1
                    )
                    prior_review = plan.review_outcomes[-1] if plan.review_outcomes else None
                    if stage is DeepSearchFinalizationStage.REVIEW_V0_CHECKED and (
                        prior_review is None or prior_review.outcome != "revise"
                    ):
                        outcome = await self._finish_with_current_revision(
                            plan=plan,
                            run=run,
                            requirement=requirement,
                            graph=graph,
                            results=results,
                            manifest=manifest,
                            manifest_artifact=_manifest_artifact,
                            evidence_artifacts=evidence_artifacts,
                        )
                        if outcome is not None:
                            return outcome
                        continue
                    synthesis, budget_operation, budget_actual_usage = await self._build_synthesis(
                        run=run,
                        plan=plan,
                        requirement=requirement,
                        graph=graph,
                        results=results,
                        manifest=manifest,
                        evidence_artifacts=evidence_artifacts,
                        revision_count=revision_count,
                        prior_review=prior_review,
                    )
                    target = (
                        DeepSearchFinalizationStage.SYNTHESIS_V0_SAVED
                        if revision_count == 0
                        else DeepSearchFinalizationStage.SYNTHESIS_V1_SAVED
                    )
                    checkpoint_kwargs: dict[str, object] = {}
                    if budget_operation is not None and budget_actual_usage is not None:
                        checkpoint_kwargs = {
                            "budget_invocation_key": budget_operation.reservation.invocation_key,
                            "budget_actual_usage": budget_actual_usage,
                        }
                    checkpoint = self.repository.compare_and_swap_deepsearch_finalization(
                        run_id=run.id,
                        plan_id=plan.id,
                        expected_plan_version=plan.version,
                        expected_finalization_version=plan.finalization_version,
                        expected_stage=stage,
                        target_stage=target,
                        input_hash=_checkpoint_input_hash(target, synthesis),
                        synthesis=synthesis,
                        **checkpoint_kwargs,
                    )
                elif stage in {
                    DeepSearchFinalizationStage.SYNTHESIS_V0_SAVED,
                    DeepSearchFinalizationStage.SYNTHESIS_V1_SAVED,
                }:
                    manifest, _manifest_artifact = self._load_manifest(plan=plan, run=run)
                    synthesis = plan.deepsearch_syntheses[-1]
                    operation = self._reserve_finalization_operation(
                        run=run,
                        plan=plan,
                        operation=f"coverage-v{synthesis.revision_count}",
                        identity=canonical_json_sha256(synthesis.model_dump(mode="python")),
                        resource_maxima=_COVERAGE_MAXIMA,
                    )
                    try:
                        coverage = await self._run_reserved_builder(
                            operation,
                            partial(
                                evaluate_evidence_coverage,
                                run=run,
                                plan=plan,
                                requirement=requirement,
                                graph=graph,
                                results=results,
                                manifest=manifest,
                                evidence_artifacts=evidence_artifacts,
                                synthesis=synthesis,
                            ),
                        )
                    except DeepSearchReportingError:
                        raise
                    except Exception as error:
                        raise DeepSearchReportingError(
                            "deepsearch_delivery_unavailable"
                        ) from error
                    target = (
                        DeepSearchFinalizationStage.COVERAGE_V0_CHECKED
                        if synthesis.revision_count == 0
                        else DeepSearchFinalizationStage.COVERAGE_V1_CHECKED
                    )
                    checkpoint = self.repository.compare_and_swap_deepsearch_finalization(
                        run_id=run.id,
                        plan_id=plan.id,
                        expected_plan_version=plan.version,
                        expected_finalization_version=plan.finalization_version,
                        expected_stage=stage,
                        target_stage=target,
                        input_hash=_checkpoint_input_hash(target, coverage),
                        coverage=coverage,
                        budget_invocation_key=operation.reservation.invocation_key,
                        budget_actual_usage=self._actual_usage(operation),
                    )
                elif stage in {
                    DeepSearchFinalizationStage.COVERAGE_V0_CHECKED,
                    DeepSearchFinalizationStage.COVERAGE_V1_CHECKED,
                }:
                    manifest, _manifest_artifact = self._load_manifest(plan=plan, run=run)
                    synthesis = plan.deepsearch_syntheses[-1]
                    coverage = plan.evidence_coverage
                    if coverage is None:
                        raise DeepSearchReportingError()
                    review_outcome = await self._build_review(
                        run=run,
                        plan=plan,
                        requirement=requirement,
                        graph=graph,
                        synthesis=synthesis,
                        coverage=coverage,
                        manifest=manifest,
                        evidence_artifacts=evidence_artifacts,
                    )
                    target = (
                        DeepSearchFinalizationStage.REVIEW_V0_CHECKED
                        if synthesis.revision_count == 0
                        else DeepSearchFinalizationStage.REVIEW_V1_CHECKED
                    )
                    checkpoint = self.repository.compare_and_swap_deepsearch_finalization(
                        run_id=run.id,
                        plan_id=plan.id,
                        expected_plan_version=plan.version,
                        expected_finalization_version=plan.finalization_version,
                        expected_stage=stage,
                        target_stage=target,
                        input_hash=_checkpoint_input_hash(target, review_outcome),
                        review_outcome=review_outcome,
                    )
                elif stage is DeepSearchFinalizationStage.REVIEW_V1_CHECKED:
                    manifest, manifest_artifact = self._load_manifest(plan=plan, run=run)
                    outcome = await self._finish_with_current_revision(
                        plan=plan,
                        run=run,
                        requirement=requirement,
                        graph=graph,
                        results=results,
                        manifest=manifest,
                        manifest_artifact=manifest_artifact,
                        evidence_artifacts=evidence_artifacts,
                    )
                    if outcome is not None:
                        return outcome
                    continue
                else:
                    raise RuntimeError("deepsearch_finalization_state_invalid")
            except DeepSearchReportingError as error:
                return terminate_deepsearch_without_report(
                    self.repository,
                    run_id=run.id,
                    plan_id=plan.id,
                    terminal_status=AgentRunStatus.FAILED,
                    error_code=error.code,
                )
            except Exception as error:
                if isinstance(error, _FinalizationOperationBusy):
                    await asyncio.sleep(0.01)
                    continue
                if getattr(error, "code", None) == "deepsearch_budget_state_conflict":
                    refreshed_plan = self.repository.get_skill_plan(plan.id)
                    refreshed_run = self.repository.get_agent_run(run.id)
                    if (
                        refreshed_plan is not None
                        and refreshed_run is not None
                        and refreshed_plan.finalization_stage
                        is DeepSearchFinalizationStage.TERMINAL_COMMITTED
                        and refreshed_run.status in _FINALIZATION_TERMINAL_STATUSES
                    ):
                        return PlanExecutionOutcome(
                            plan=refreshed_plan,
                            run=refreshed_run,
                        )
                    if (
                        refreshed_plan is not None
                        and refreshed_run is not None
                        and (
                            refreshed_plan.finalization_stage is not stage
                            or refreshed_plan.status is not SkillPlanStatus.RUNNING
                            or refreshed_run.status is not AgentRunStatus.RUNNING
                        )
                    ):
                        continue
                code = _finalization_budget_error_code(error)
                if code is None:
                    raise
                return terminate_deepsearch_without_report(
                    self.repository,
                    run_id=run.id,
                    plan_id=plan.id,
                    terminal_status=AgentRunStatus.FAILED,
                    error_code=code,
                )
            if checkpoint is None:
                continue
        raise RuntimeError("deepsearch_finalization_state_conflict")
