"""Read-only projection boundary for historical research-v2 runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agentmesh.models import AgentRun, InboxItem
from agentmesh.research_orchestration.api import (
    ResearchAttemptProjection,
    ResearchClarificationProjection,
    ResearchConflictError,
    ResearchGapProjection,
    ResearchNotFoundError,
    ResearchOwnerScope,
    ResearchPlanProjection,
    ResearchPlanStepProjection,
    ResearchProvenanceProjection,
    ResearchRecoveryProjection,
    ResearchRequirementProjection,
    ResearchRunProjection,
    ResearchStepProgressProjection,
    ResearchToolApprovalProjection,
    ResearchWorkflowProjection,
)
from agentmesh.research_orchestration.compiler import validate_execution_plan_version
from agentmesh.research_orchestration.contracts import (
    ExecutionAttempt,
    ExecutionPlanVersion,
    RequirementVersion,
    ResearchStep,
    ResearchTaskV2,
    ResearchWorkflow,
    ToolInvocation,
)
from agentmesh.research_orchestration.result_projection import (
    ResearchArtifactReader,
    build_verified_research_result,
)
from agentmesh.research_orchestration.v2_artifact_history import (
    ArtifactReaderScope,
    ResearchResultSnapshot,
)
from agentmesh.store import ResearchStoreConflict


@dataclass(frozen=True, slots=True)
class WorkflowContext:
    """The immutable v2 aggregate loaded for projection or writer transitions."""

    run: AgentRun
    workflow: ResearchWorkflow
    active_requirement: RequirementVersion | None
    active_plan: ExecutionPlanVersion | None
    active_attempt: ExecutionAttempt | None
    steps: tuple[ResearchStep, ...]
    requirements: tuple[RequirementVersion, ...]
    plans: tuple[ExecutionPlanVersion, ...]
    attempt_count: int
    active_tool_approval: InboxItem | None = None
    active_recovery_invocation: ToolInvocation | None = None


class V2HistoryRepository(Protocol):
    def load_context(self, run_id: str, *, owner: ResearchOwnerScope) -> WorkflowContext | None: ...


class V2HistoryArtifactReader(ResearchArtifactReader, Protocol):
    def research_result_snapshot(
        self,
        *,
        run_id: str,
        attempt_id: str | None,
        reader_scope: ArtifactReaderScope,
    ) -> ResearchResultSnapshot: ...


class V2HistoryReader(Protocol):
    def get_projection(self, run_id: str, *, owner: ResearchOwnerScope) -> ResearchRunProjection: ...


def decode_research_task_v2(requirement: RequirementVersion) -> ResearchTaskV2:
    try:
        return ResearchTaskV2.model_validate(requirement.payload["requirement"])
    except (KeyError, TypeError, ValueError):
        raise ResearchConflictError("research requirement failed integrity verification") from None


class V2HistoryAdapter:
    """Project persisted v2 state without owning planning, execution, or background work."""

    def __init__(
        self,
        repository: V2HistoryRepository,
        artifacts: V2HistoryArtifactReader,
    ) -> None:
        self._repository = repository
        self._artifacts = artifacts

    def get_projection(self, run_id: str, *, owner: ResearchOwnerScope) -> ResearchRunProjection:
        return self._project(self._require_context(run_id, owner=owner))

    def _project(self, context: WorkflowContext) -> ResearchRunProjection:
        requirement_projection = None
        if context.active_requirement is not None:
            task = decode_research_task_v2(context.active_requirement)
            requirement_projection = ResearchRequirementProjection(
                requirement_version_id=context.active_requirement.id,
                version=context.active_requirement.version,
                research_goal=task.research_goal,
                competitor_scope=task.competitor_scope,
                blocking=any(item.blocking for item in task.ambiguities),
                clarification_questions=[
                    ResearchClarificationProjection(question_id=item.id, prompt=item.prompt)
                    for item in task.clarification_questions
                ],
            )
        reader_scope = ArtifactReaderScope(
            user_id=context.run.user_id,
            workspace_id=context.run.workspace_id,
            project_id=context.run.project_id,
            run_id=context.run.id,
        )
        result_snapshot = self._artifacts.research_result_snapshot(
            run_id=context.run.id,
            attempt_id=context.workflow.active_attempt_id,
            reader_scope=reader_scope,
        )
        verified_result = build_verified_research_result(
            self._artifacts,
            result_snapshot,
            run_id=context.run.id,
            attempt_id=context.workflow.active_attempt_id,
            reader_scope=reader_scope,
        )
        plans: list[ResearchPlanProjection] = []
        provenance = ResearchProvenanceProjection()
        if context.active_plan is not None:
            body = validate_execution_plan_version(context.active_plan)
            plans.append(
                ResearchPlanProjection(
                    plan_version_id=context.active_plan.id,
                    version=context.active_plan.version,
                    recommended=True,
                    plan_hash=context.active_plan.plan_hash,
                    steps=[
                        ResearchPlanStepProjection(
                            step_number=step.step_number,
                            name=step.name,
                            actor_type=step.actor_type.value,
                            actor_id=step.actor_id,
                            required=step.required,
                        )
                        for step in body.steps
                    ],
                )
            )
            provenance = ResearchProvenanceProjection(
                requested_model=body.control_snapshot.model_policy.requested_model_id,
                actual_model=result_snapshot.actual_model,
                tool_implementation_id=body.control_snapshot.tool.implementation_id,
                tool_execution_mode=body.control_snapshot.tool.execution_mode,
            )
        attempt_projection = None
        if context.active_attempt is not None:
            attempt_projection = ResearchAttemptProjection(
                attempt_id=context.active_attempt.id,
                attempt_number=context.active_attempt.attempt_number,
                status=context.active_attempt.status.value,
                steps=[
                    ResearchStepProgressProjection(
                        step_number=step.step_number,
                        status=step.status.value,
                        attempt_count=step.claim_epoch,
                        result_artifact_id=step.result_artifact_id,
                        error_code=step.error_code,
                    )
                    for step in context.steps
                ],
            )
        recovery_projection = None
        if context.active_recovery_invocation is not None:
            recovery_projection = ResearchRecoveryProjection(
                invocation_id=context.active_recovery_invocation.id,
                send_count=context.active_recovery_invocation.send_count,
                error_code=context.active_recovery_invocation.error_code,
            )
        tool_approval_projection = None
        if context.active_tool_approval is not None:
            call_id = context.active_tool_approval.metadata.get("call_id")
            tool_name = context.active_tool_approval.metadata.get("tool_name")
            if not call_id or not tool_name:
                raise ResearchConflictError("research Tool approval failed integrity verification")
            tool_approval_projection = ResearchToolApprovalProjection(
                inbox_item_id=context.active_tool_approval.id,
                call_id=call_id,
                tool_name=tool_name,
            )
        return ResearchRunProjection(
            run_id=context.run.id,
            status=context.run.status,
            error_code=context.run.error_code,
            workflow=ResearchWorkflowProjection(
                phase=context.workflow.phase,
                active_gate=context.workflow.active_gate,
                state_version=context.workflow.state_version,
                active_requirement_version_id=context.workflow.active_requirement_version_id,
                active_plan_version_id=context.workflow.active_plan_version_id,
                active_attempt_id=context.workflow.active_attempt_id,
                updated_at=context.workflow.updated_at,
            ),
            requirement=requirement_projection,
            plans=plans,
            attempt=attempt_projection,
            gaps=[
                ResearchGapProjection(
                    code=code,
                    message=code.replace("_", " "),
                    question_ids=[],
                )
                for code in result_snapshot.gap_codes
            ],
            artifacts=verified_result.artifacts,
            result=verified_result.result,
            provenance=provenance,
            tool_approval=tool_approval_projection,
            recovery=recovery_projection,
            integrity_errors=list(verified_result.integrity_errors),
        )

    def _require_context(self, run_id: str, *, owner: ResearchOwnerScope) -> WorkflowContext:
        try:
            context = self._repository.load_context(run_id, owner=owner)
        except ResearchStoreConflict as error:
            raise ResearchConflictError(str(error)) from error
        if context is None:
            raise ResearchNotFoundError(run_id)
        return context
