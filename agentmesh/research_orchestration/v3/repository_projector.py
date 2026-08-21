"""Authoritative Workbench projection from isolated research-v3 SQLite rows."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentmesh.research_orchestration.v3.sqlite_repository import (
    RepositoryProjectionSnapshotV3,
    ResearchV3IntegrityError,
    SQLiteResearchV3Repository,
)
from agentmesh.research_orchestration.v3.web_projection import (
    ResearchV3WorkbenchAggregateV1,
    WorkbenchAggregateV1,
    WorkbenchAttemptV1,
    WorkbenchDeliverableV1,
    WorkbenchGateV1,
    WorkbenchProjectionProvenanceV1,
    WorkbenchRecoveryV1,
    WorkbenchReportV1,
    WorkbenchReviewV1,
    WorkbenchStepV1,
    WorkbenchWorkflowV1,
    project_verified_evidence_for_workbench,
)

if TYPE_CHECKING:
    from agentmesh.research_orchestration.v3.api import ResearchV3AggregateReadRequest


class ResearchV3RepositoryProjector:
    """Pure reader that rebuilds the Web aggregate only from verified persisted state."""

    def __init__(
        self,
        repository: SQLiteResearchV3Repository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))

    def project(self, run_id: str) -> WorkbenchAggregateV1 | None:
        source = self._repository.projection_snapshot(run_id)
        if source is None:
            return None
        aggregate = self._build(source)
        return WorkbenchAggregateV1.model_validate(aggregate.model_dump(mode="python"))

    def project_authoritative(
        self,
        request: ResearchV3AggregateReadRequest,
    ) -> ResearchV3WorkbenchAggregateV1:
        """Satisfy the isolated API read port without weakening repository scope."""

        expected_scope = (
            self._repository.scope.owner_id,
            self._repository.scope.workspace_id,
            self._repository.scope.project_id,
        )
        requested_scope = (
            request.owner.user_id,
            request.owner.workspace_id,
            request.owner.project_id,
        )
        if requested_scope != expected_scope:
            from agentmesh.research_orchestration.v3.api import ResearchV3NotFoundError

            raise ResearchV3NotFoundError
        aggregate = self.project(request.run_id)
        if aggregate is None:
            from agentmesh.research_orchestration.v3.api import ResearchV3NotFoundError

            raise ResearchV3NotFoundError
        return ResearchV3WorkbenchAggregateV1.model_validate(aggregate.model_dump(mode="python"))

    def _build(self, source: RepositoryProjectionSnapshotV3) -> ResearchV3WorkbenchAggregateV1:
        if source.run.orchestration_version != "research-v3":
            raise ResearchV3IntegrityError("Workbench dispatch requires the exact stored research-v3 version")

        state, gate = self._state_and_gate(source)
        attempt = self._attempt(source)
        recovery = None
        if state == "paused":
            if source.attempt is None or source.selected_plan is None:
                raise ResearchV3IntegrityError("paused projection lacks its persisted Attempt and Plan")
            failed_step = next(
                (
                    step
                    for step in source.selected_plan.payload.steps
                    if step.step_number == source.attempt.failed_step_number
                ),
                None,
            )
            if failed_step is None or source.attempt.failure_code is None:
                raise ResearchV3IntegrityError("paused projection failure does not bind a Plan Step")
            allowed = ("retry", "skip", "abort") if not failed_step.required else ("retry", "abort")
            recovery = WorkbenchRecoveryV1(
                failed_step_number=failed_step.step_number,
                reason_code=source.attempt.failure_code,
                allowed_actions=allowed,
                decision_required=True,
            )

        evidence = None
        if source.evidence is not None:
            evidence = project_verified_evidence_for_workbench(
                artifact=source.evidence[0],
                manifest=source.evidence[1],
                verified_artifacts=source.verified_artifacts,
            )

        deliverable = (
            WorkbenchDeliverableV1(artifact=source.deliverable[0], content=source.deliverable[1])
            if source.deliverable is not None
            else None
        )
        review = (
            WorkbenchReviewV1(artifact=source.review[0], content=source.review[1])
            if source.review is not None
            else None
        )
        report = (
            WorkbenchReportV1(artifact=source.report[0], content=source.report[1])
            if source.report is not None
            else None
        )
        return ResearchV3WorkbenchAggregateV1(
            schema_version="research-workbench-aggregate-v1",
            projection_kind="research-v3-current",
            orchestration_version="research-v3",
            run_id=source.run.run_id,
            workflow=WorkbenchWorkflowV1(
                state=state,
                state_version=source.run.state_version,
                gate=gate,
            ),
            requirement=source.requirement,
            candidates=source.candidates,
            selected_plan=source.selected_plan,
            approvals=source.approvals,
            attempt=attempt,
            recovery=recovery,
            evidence=evidence,
            deliverable=deliverable,
            review=review,
            report=report,
            provenance=WorkbenchProjectionProvenanceV1(
                source_kind="repository_projection",
                projection_schema_version="research-workbench-aggregate-v1",
                projected_at=self._clock(),
                source_state_version=source.run.state_version,
            ),
        )

    @staticmethod
    def _state_and_gate(
        source: RepositoryProjectionSnapshotV3,
    ) -> tuple[str, WorkbenchGateV1]:
        preview_status = source.run.preview_status
        if preview_status == "confirmed" and source.selected_plan is None:
            raise ResearchV3IntegrityError("confirmed preview lacks its persisted selected Plan")
        if source.requirement is None:
            return "idle", WorkbenchGateV1(kind="none", status="inactive")
        if source.candidates is None:
            return "clarify", WorkbenchGateV1(
                kind="clarification",
                status="blocked" if preview_status == "cancelled" else "pending",
            )
        if source.selected_plan is None:
            return "candidates", WorkbenchGateV1(
                kind="candidate_selection",
                status="blocked" if preview_status == "cancelled" else "pending",
            )
        if source.attempt is None:
            pending = tuple(approval for approval in source.approvals if approval.decision == "pending")
            if pending:
                roles = {approval.role for approval in pending}
                if len(roles) != 1:
                    raise ResearchV3IntegrityError("one projection gate cannot require multiple approval roles")
                return "approval", WorkbenchGateV1(
                    kind="role_approval",
                    status="pending",
                    required_role=next(iter(roles)),
                )
            gate_status = {
                "active": "pending",
                "confirmed": "satisfied",
                "cancelled": "blocked",
            }[preview_status]
            return "plan", WorkbenchGateV1(
                kind="plan_confirmation",
                status=gate_status,
            )
        if source.report is not None:
            required = (source.evidence, source.deliverable, source.review)
            if source.attempt.status != "completed" or any(item is None for item in required):
                raise ResearchV3IntegrityError("persisted Report dependency closure is incomplete")
            return "text_report", WorkbenchGateV1(kind="none", status="inactive")
        if source.attempt.status == "paused":
            return "paused", WorkbenchGateV1(kind="recovery", status="blocked")
        if source.attempt.status in {"pending", "running"}:
            return "dag_or_executing", WorkbenchGateV1(kind="none", status="inactive")
        raise ResearchV3IntegrityError("completed or aborted Attempt has no projectable terminal Report")

    @staticmethod
    def _attempt(source: RepositoryProjectionSnapshotV3) -> WorkbenchAttemptV1 | None:
        if source.attempt is None:
            return None
        if source.selected_plan is None:
            raise ResearchV3IntegrityError("persisted Attempt has no selected Plan")
        results = {result.step_number: result for result in source.actor_results}
        steps: list[WorkbenchStepV1] = []
        first_unfinished = next(
            (
                step.step_number
                for step in source.selected_plan.payload.steps
                if step.step_number not in results
            ),
            None,
        )
        for plan_step in source.selected_plan.payload.steps:
            result = results.get(plan_step.step_number)
            failure_code = None
            if result is not None:
                status = "succeeded"
            elif (
                source.attempt.status == "paused"
                and plan_step.step_number == source.attempt.failed_step_number
            ):
                status = "failed"
                failure_code = source.attempt.failure_code
            elif source.attempt.status == "running" and plan_step.step_number == first_unfinished:
                status = "running"
            else:
                status = "pending"
            steps.append(
                WorkbenchStepV1(
                    step_number=plan_step.step_number,
                    actor_type=plan_step.actor_type,
                    actor_id=plan_step.actor_id,
                    step_contract_hash=plan_step.contract_hash,
                    expected_outputs=plan_step.expected_outputs,
                    status=status,
                    result=result,
                    failure_code=failure_code,
                )
            )
        projected_status = {
            "pending": "running",
            "running": "running",
            "paused": "paused",
            "completed": "completed",
        }.get(source.attempt.status)
        if projected_status is None:
            raise ResearchV3IntegrityError("aborted Attempt is not a current Workbench projection")
        return WorkbenchAttemptV1(
            attempt_id=source.attempt.attempt_id,
            run_id=source.attempt.run_id,
            plan_version_id=source.attempt.plan_version_id,
            status=projected_status,
            steps=tuple(steps),
        )
