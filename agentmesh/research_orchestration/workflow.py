from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal, Protocol

from agentmesh.models import AgentRun, AgentRunStatus, InboxItem, Scope, new_id
from agentmesh.research_orchestration.api import (
    ResearchAttemptProjection,
    ResearchClarificationProjection,
    ResearchClarifyRequest,
    ResearchCommandResponse,
    ResearchCommandType,
    ResearchConfirmPlanRequest,
    ResearchConflictError,
    ResearchExecuteRequest,
    ResearchGapProjection,
    ResearchNotFoundError,
    ResearchOwnerScope,
    ResearchPlanProjection,
    ResearchPlanStepProjection,
    ResearchProvenanceProjection,
    ResearchPurgeRequest,
    ResearchRecoverRequest,
    ResearchRecoveryProjection,
    ResearchRequirementProjection,
    ResearchRevisePlanRequest,
    ResearchRunProjection,
    ResearchStepProgressProjection,
    ResearchToolApprovalProjection,
    ResearchWorkflowProjection,
)
from agentmesh.research_orchestration.artifacts import (
    ArtifactReaderScope,
    ArtifactStoreError,
    ResearchResultSnapshot,
)
from agentmesh.research_orchestration.compiler import (
    PlanCompileError,
    validate_execution_plan_version,
)
from agentmesh.research_orchestration.contracts import (
    AttemptStatus,
    ExecutionAttempt,
    ExecutionPlanVersion,
    InvocationState,
    RequirementVersion,
    ResearchCommandReceipt,
    ResearchGate,
    ResearchPhase,
    ResearchStep,
    ResearchTaskV2,
    ResearchWorkflow,
    StepStatus,
    ToolInvocation,
    canonical_sha256,
)
from agentmesh.research_orchestration.result_projection import build_verified_research_result
from agentmesh.store import ResearchStoreConflict


@dataclass(frozen=True, slots=True)
class WorkflowContext:
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


@dataclass(frozen=True, slots=True)
class PlanningMutation:
    run_id: str
    expected_state_version: int
    workflow: ResearchWorkflow
    requirement: RequirementVersion | None = None
    plan: ExecutionPlanVersion | None = None
    terminal_status: AgentRunStatus | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class CommandMutation:
    receipt: ResearchCommandReceipt
    expected_state_version: int
    workflow: ResearchWorkflow
    attempt: ExecutionAttempt | None = None
    steps: tuple[ResearchStep, ...] = ()
    approval_inbox: InboxItem | None = None
    superseded_attempt_id: str | None = None
    superseded_attempt_status: AttemptStatus | None = None
    recovery_invocation_id: str | None = None
    recovery_action: Literal["retry", "abort"] | None = None
    terminal_status: AgentRunStatus | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class CommandCommitResult:
    receipt: ResearchCommandReceipt
    context: WorkflowContext
    created: bool


class ResearchWorkflowRepository(Protocol):
    def ensure_workflow(self, run: AgentRun, workflow: ResearchWorkflow) -> WorkflowContext: ...

    def load_context(self, run_id: str, *, owner: ResearchOwnerScope) -> WorkflowContext | None: ...

    def replay_command(
        self,
        run_id: str,
        *,
        owner: ResearchOwnerScope,
        idempotency_key: str,
        command_type: ResearchCommandType,
        request_hash: str,
    ) -> ResearchCommandReceipt | None: ...

    def publish_planning(self, mutation: PlanningMutation) -> WorkflowContext: ...

    def commit_command(self, mutation: CommandMutation) -> CommandCommitResult: ...

    def get_research_tool_invocation(self, invocation_id: str) -> ToolInvocation | None: ...

    def enter_research_recovery_decision(
        self,
        attempt_id: str,
        *,
        error_code: str,
        now: Any,
    ) -> ToolInvocation | None: ...

    def list_recoverable_research_attempt_ids(self, now: Any) -> list[str]: ...

    def expire_research_attempt_deadlines(self, now: Any) -> int: ...


class ResearchPlanning(Protocol):
    async def prepare_requirement(
        self,
        run: AgentRun,
        *,
        version: int,
        clarification_answers: dict[str, str] | None = None,
        revision: ResearchRevisePlanRequest | None = None,
    ) -> RequirementVersion: ...

    def compile_plan(
        self,
        run: AgentRun,
        requirement: RequirementVersion,
        *,
        version: int,
    ) -> ExecutionPlanVersion: ...


class ResearchExecution(Protocol):
    async def claim_and_run(self, attempt_id: str, *, token: str | None = None) -> object: ...


class ResearchArtifactAccess(Protocol):
    def purge_research_data_command(
        self,
        run_id: str,
        *,
        actor_user_id: str,
        workspace_id: str,
        expected_state_version: int,
        idempotency_key: str,
        request_hash: str,
        now: Any,
    ) -> ResearchCommandReceipt: ...

    def research_result_snapshot(
        self,
        *,
        run_id: str,
        attempt_id: str | None,
        reader_scope: ArtifactReaderScope,
    ) -> ResearchResultSnapshot: ...


class WorkflowClock(Protocol):
    def now(self) -> Any: ...


class _SystemClock:
    def now(self):  # noqa: ANN201
        from agentmesh.models import now_utc

        return now_utc()


class ResearchWorkflowService:
    """Own the v2 control state; reads are pure and only mutation commands schedule work."""

    def __init__(
        self,
        repository: ResearchWorkflowRepository,
        planning: ResearchPlanning,
        execution: ResearchExecution,
        purger: ResearchArtifactAccess,
        *,
        clock: WorkflowClock | None = None,
        id_factory: Callable[[str], str] | None = None,
        settlement_grace: timedelta = timedelta(seconds=60),
        execution_allowed: Callable[[], bool] | None = None,
    ):
        if settlement_grace < timedelta(0):
            raise ValueError("research settlement grace cannot be negative")
        self.repository = repository
        self.planning = planning
        self.execution = execution
        self.purger = purger
        self.artifacts = purger
        self.clock = clock or _SystemClock()
        self.id_factory = id_factory or new_id
        self.settlement_grace = settlement_grace
        self.execution_allowed = execution_allowed or (lambda: True)
        self._background_tasks: dict[str, asyncio.Task[None]] = {}
        self._background_errors: list[BaseException] = []

    @property
    def background_task_count(self) -> int:
        return len(self._background_tasks)

    async def wait_for_idle(self) -> None:
        while self._background_tasks:
            await asyncio.gather(*tuple(self._background_tasks.values()), return_exceptions=True)
        if self._background_errors:
            error = self._background_errors.pop(0)
            raise error

    async def start_if_applicable(self, run: AgentRun) -> AgentRun | None:
        if run.orchestration_version != "research-v2" or run.orchestration_mode == "off":
            return None
        now = self.clock.now()
        workflow = ResearchWorkflow(run_id=run.id, phase=ResearchPhase.REQUIREMENT, created_at=now, updated_at=now)
        try:
            context = self.repository.ensure_workflow(run, workflow)
        except ResearchStoreConflict as error:
            raise ResearchConflictError(str(error)) from error
        canonical_run = context.run
        if (
            context.workflow.phase == ResearchPhase.REQUIREMENT
            and context.workflow.active_gate == ResearchGate.NONE
            and context.active_requirement is None
        ):
            self._schedule(
                f"planning:{canonical_run.id}",
                self._plan_and_publish(
                    canonical_run,
                    expected_state_version=context.workflow.state_version,
                ),
            )
        return canonical_run

    def get_projection(self, run_id: str, *, owner: ResearchOwnerScope) -> ResearchRunProjection:
        return self._projection(self._require_context(run_id, owner=owner))

    async def clarify(
        self,
        run_id: str,
        request: ResearchClarifyRequest,
        *,
        owner: ResearchOwnerScope,
        idempotency_key: str,
    ) -> ResearchCommandResponse:
        request_hash = self._command_hash("clarify", run_id, request)
        replay = self._replay(
            run_id,
            owner=owner,
            idempotency_key=idempotency_key,
            command_type="clarify",
            request_hash=request_hash,
        )
        if replay is not None:
            return replay
        context = self._require_context(run_id, owner=owner)
        self._require_version(context, request.expected_state_version)
        if (
            context.workflow.phase != ResearchPhase.REQUIREMENT
            or context.workflow.active_gate != ResearchGate.CLARIFICATION
            or context.active_requirement is None
        ):
            raise ResearchConflictError("research workflow is not awaiting clarification")
        if len(context.requirements) >= 2:
            raise ResearchConflictError("Slice A clarification has already been exhausted")
        task = self._requirement_task(context.active_requirement)
        expected_questions = {item.id for item in task.clarification_questions}
        answer_ids = {item.question_id for item in request.answers}
        if not expected_questions or answer_ids != expected_questions:
            raise ResearchConflictError("clarification answers do not match the active questions")
        workflow = context.workflow.model_copy(update={"active_gate": ResearchGate.NONE})
        result = self._commit(
            CommandMutation(
                receipt=self._receipt(
                    run_id,
                    idempotency_key,
                    "clarify",
                    request_hash,
                    request.expected_state_version + 1,
                ),
                expected_state_version=request.expected_state_version,
                workflow=workflow,
            )
        )
        if result.created:
            answers = {item.question_id: item.answer for item in request.answers}
            self._schedule(
                f"planning:{run_id}",
                self._plan_and_publish(
                    result.context.run,
                    expected_state_version=result.context.workflow.state_version,
                    clarification_answers=answers,
                ),
            )
        return self._command_response(result.receipt, replayed=not result.created)

    async def confirm_plan(
        self,
        run_id: str,
        plan_version_id: str,
        request: ResearchConfirmPlanRequest,
        *,
        owner: ResearchOwnerScope,
        idempotency_key: str,
    ) -> ResearchCommandResponse:
        request_hash = self._command_hash(
            "confirm_plan",
            run_id,
            request,
            plan_version_id=plan_version_id,
        )
        replay = self._replay(
            run_id,
            owner=owner,
            idempotency_key=idempotency_key,
            command_type="confirm_plan",
            request_hash=request_hash,
        )
        if replay is not None:
            return replay
        context = self._require_context(run_id, owner=owner)
        self._require_version(context, request.expected_state_version)
        if (
            context.workflow.phase != ResearchPhase.PLANNING
            or context.workflow.active_gate != ResearchGate.PLAN_CONFIRMATION
            or context.active_plan is None
            or context.active_plan.id != plan_version_id
        ):
            raise ResearchConflictError("research plan is not awaiting confirmation")
        result = self._commit(
            CommandMutation(
                receipt=self._receipt(
                    run_id,
                    idempotency_key,
                    "confirm_plan",
                    request_hash,
                    request.expected_state_version + 1,
                ),
                expected_state_version=request.expected_state_version,
                workflow=context.workflow.model_copy(update={"active_gate": ResearchGate.NONE}),
            )
        )
        return self._command_response(result.receipt, replayed=not result.created)

    async def revise_plan(
        self,
        run_id: str,
        plan_version_id: str,
        request: ResearchRevisePlanRequest,
        *,
        owner: ResearchOwnerScope,
        idempotency_key: str,
    ) -> ResearchCommandResponse:
        request_hash = self._command_hash("revise", run_id, request, plan_version_id=plan_version_id)
        replay = self._replay(
            run_id,
            owner=owner,
            idempotency_key=idempotency_key,
            command_type="revise",
            request_hash=request_hash,
        )
        if replay is not None:
            return replay
        if request.assumptions or request.preferred_plan_version_id or request.remove_optional_step_numbers:
            raise ResearchConflictError("Slice A only supports research goal and competitor scope revisions")
        context = self._require_context(run_id, owner=owner)
        self._require_version(context, request.expected_state_version)
        if (
            context.workflow.phase != ResearchPhase.PLANNING
            or context.workflow.active_gate != ResearchGate.PLAN_CONFIRMATION
            or context.active_plan is None
            or context.active_plan.id != plan_version_id
        ):
            raise ResearchConflictError("research plan is not revisable")
        result = self._commit(
            CommandMutation(
                receipt=self._receipt(
                    run_id,
                    idempotency_key,
                    "revise",
                    request_hash,
                    request.expected_state_version + 1,
                ),
                expected_state_version=request.expected_state_version,
                workflow=context.workflow.model_copy(update={"active_gate": ResearchGate.NONE}),
            )
        )
        if result.created:
            self._schedule(
                f"planning:{run_id}",
                self._plan_and_publish(
                    result.context.run,
                    expected_state_version=result.context.workflow.state_version,
                    revision=request,
                ),
            )
        return self._command_response(result.receipt, replayed=not result.created)

    async def execute(
        self,
        run_id: str,
        request: ResearchExecuteRequest,
        *,
        owner: ResearchOwnerScope,
        idempotency_key: str,
    ) -> ResearchCommandResponse:
        request_hash = self._command_hash("execute", run_id, request)
        replay = self._replay(
            run_id,
            owner=owner,
            idempotency_key=idempotency_key,
            command_type="execute",
            request_hash=request_hash,
        )
        if replay is not None:
            return replay
        context = self._require_context(run_id, owner=owner)
        self._require_version(context, request.expected_state_version)
        if context.run.orchestration_mode != "execute" or not self.execution_allowed():
            raise ResearchConflictError("research execution is disabled in preview mode")
        if (
            context.workflow.phase != ResearchPhase.PLANNING
            or context.workflow.active_gate != ResearchGate.NONE
            or context.active_plan is None
            or context.active_attempt is not None
        ):
            raise ResearchConflictError("research workflow is not ready to execute")
        attempt, steps = self._new_attempt(context)
        body = validate_execution_plan_version(context.active_plan)
        tool_step = body.steps[0]
        approval_inbox = None
        next_gate = ResearchGate.NONE
        if tool_step.approval_required:
            next_gate = ResearchGate.TOOL_APPROVAL
            call_id = f"research-tool:{attempt.id}:{tool_step.step_number}"
            now = self.clock.now()
            approval_inbox = InboxItem(
                id=self.id_factory("inbox"),
                title="批准研究工具调用",
                summary="允许 web_research 检索并封存本次研究所需的外部证据。",
                item_type="research_tool_approval",
                scope=Scope.PRIVATE,
                user_id=context.run.user_id,
                workspace_id=context.run.workspace_id,
                project_id=context.run.project_id,
                metadata={
                    "run_id": run_id,
                    "attempt_id": attempt.id,
                    "plan_version_id": context.active_plan.id,
                    "step_number": str(tool_step.step_number),
                    "tool_name": body.control_snapshot.tool.tool_name,
                    "call_id": call_id,
                },
                created_at=now,
                updated_at=now,
            )
        result = self._commit(
            CommandMutation(
                receipt=self._receipt(
                    run_id,
                    idempotency_key,
                    "execute",
                    request_hash,
                    request.expected_state_version + 1,
                ),
                expected_state_version=request.expected_state_version,
                workflow=context.workflow.model_copy(
                    update={
                        "phase": ResearchPhase.EXECUTION,
                        "active_gate": next_gate,
                        "active_attempt_id": attempt.id,
                    }
                ),
                attempt=attempt,
                steps=steps,
                approval_inbox=approval_inbox,
            )
        )
        if result.created and approval_inbox is None:
            self._schedule_execution(attempt.id)
        return self._command_response(result.receipt, replayed=not result.created)

    async def recover(
        self,
        run_id: str,
        request: ResearchRecoverRequest,
        *,
        owner: ResearchOwnerScope,
        idempotency_key: str,
    ) -> ResearchCommandResponse:
        request_hash = self._command_hash("recover", run_id, request)
        replay = self._replay(
            run_id,
            owner=owner,
            idempotency_key=idempotency_key,
            command_type="recover",
            request_hash=request_hash,
        )
        if replay is not None:
            return replay
        context = self._require_context(run_id, owner=owner)
        self._require_version(context, request.expected_state_version)
        if (
            context.workflow.phase != ResearchPhase.EXECUTION
            or context.workflow.active_gate != ResearchGate.RECOVERY_DECISION
            or context.active_attempt is None
            or context.active_attempt.status != AttemptStatus.RECOVERY_REQUIRED
        ):
            raise ResearchConflictError("research workflow is not awaiting recovery")
        invocation = self.repository.get_research_tool_invocation(request.invocation_id)
        if (
            invocation is None
            or invocation.run_id != run_id
            or invocation.active_attempt_id != context.active_attempt.id
            or invocation.state != InvocationState.UNKNOWN
        ):
            raise ResearchConflictError("recovery invocation is not the active unknown operation")
        if request.action == "retry":
            if not self.execution_allowed():
                raise ResearchConflictError("research execution is disabled")
            attempt, steps = self._new_attempt(context, retry_of=context.active_attempt.id)
            workflow = context.workflow.model_copy(
                update={"active_gate": ResearchGate.NONE, "active_attempt_id": attempt.id}
            )
            mutation = CommandMutation(
                receipt=self._receipt(
                    run_id,
                    idempotency_key,
                    "recover",
                    request_hash,
                    request.expected_state_version + 1,
                ),
                expected_state_version=request.expected_state_version,
                workflow=workflow,
                attempt=attempt,
                steps=steps,
                superseded_attempt_id=context.active_attempt.id,
                superseded_attempt_status=AttemptStatus.FAILED,
                recovery_invocation_id=invocation.id,
                recovery_action="retry",
            )
        else:
            attempt = None
            mutation = CommandMutation(
                receipt=self._receipt(
                    run_id,
                    idempotency_key,
                    "recover",
                    request_hash,
                    request.expected_state_version + 1,
                ),
                expected_state_version=request.expected_state_version,
                workflow=context.workflow.model_copy(
                    update={"phase": ResearchPhase.TERMINAL, "active_gate": ResearchGate.NONE}
                ),
                superseded_attempt_id=context.active_attempt.id,
                superseded_attempt_status=AttemptStatus.CANCELLED,
                recovery_invocation_id=invocation.id,
                recovery_action="abort",
                terminal_status=AgentRunStatus.CANCELLED,
                error_code="recovery_aborted",
            )
        result = self._commit(mutation)
        if result.created and attempt is not None:
            self._schedule_execution(attempt.id)
        return self._command_response(result.receipt, replayed=not result.created)

    async def purge(
        self,
        run_id: str,
        request: ResearchPurgeRequest,
        *,
        owner: ResearchOwnerScope,
        idempotency_key: str,
    ) -> ResearchCommandResponse:
        request_hash = self._command_hash("purge", run_id, request)
        replay = self._replay(
            run_id,
            owner=owner,
            idempotency_key=idempotency_key,
            command_type="purge",
            request_hash=request_hash,
        )
        if replay is not None:
            return replay
        context = self._require_context(run_id, owner=owner)
        self._require_version(context, request.expected_state_version)
        if context.workflow.phase != ResearchPhase.TERMINAL:
            raise ResearchConflictError("research data can only be deleted after the run is terminal")
        try:
            receipt = self.purger.purge_research_data_command(
                run_id,
                actor_user_id=owner.user_id,
                workspace_id=owner.workspace_id,
                expected_state_version=request.expected_state_version,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                now=self.clock.now(),
            )
        except ResearchStoreConflict as error:
            raise ResearchConflictError(str(error)) from error
        except ArtifactStoreError as error:
            if error.args and error.args[0] == "artifact_not_found":
                raise ResearchNotFoundError(run_id) from error
            raise ResearchConflictError(str(error)) from error
        return ResearchCommandResponse(
            run_id=run_id,
            command_type="purge",
            state_version=request.expected_state_version,
            replayed=False,
            purged_artifact_count=int(receipt.response_payload.get("artifact_count", 0)),
        )

    async def _plan_and_publish(
        self,
        run: AgentRun,
        *,
        expected_state_version: int,
        clarification_answers: dict[str, str] | None = None,
        revision: ResearchRevisePlanRequest | None = None,
    ) -> None:
        owner = ResearchOwnerScope(
            user_id=run.user_id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
        )
        try:
            context = self._require_context(run.id, owner=owner)
            if context.workflow.state_version != expected_state_version:
                return
            requirement = await self.planning.prepare_requirement(
                run,
                version=len(context.requirements) + 1,
                clarification_answers=clarification_answers,
                revision=revision,
            )
            task = self._requirement_task(requirement)
            blocked = any(item.blocking for item in task.ambiguities)
            requirement_workflow = context.workflow.model_copy(
                update={
                    "phase": ResearchPhase.REQUIREMENT if blocked else ResearchPhase.PLANNING,
                    "active_gate": ResearchGate.CLARIFICATION if blocked else ResearchGate.NONE,
                    "active_requirement_version_id": requirement.id,
                    "active_plan_version_id": None,
                    "active_attempt_id": None,
                }
            )
            context = self.repository.publish_planning(
                PlanningMutation(
                    run_id=run.id,
                    expected_state_version=expected_state_version,
                    workflow=requirement_workflow,
                    requirement=requirement,
                )
            )
            if blocked:
                return
            plan_value = self.planning.compile_plan(
                context.run,
                requirement,
                version=len(context.plans) + 1,
            )
            if inspect.isawaitable(plan_value):
                plan_value = await plan_value
            plan = ExecutionPlanVersion.model_validate(plan_value)
            self.repository.publish_planning(
                PlanningMutation(
                    run_id=run.id,
                    expected_state_version=context.workflow.state_version,
                    workflow=context.workflow.model_copy(
                        update={
                            "phase": ResearchPhase.PLANNING,
                            "active_gate": ResearchGate.PLAN_CONFIRMATION,
                            "active_plan_version_id": plan.id,
                        }
                    ),
                    plan=plan,
                )
            )
        except ResearchStoreConflict as error:
            if "state version" in str(error):
                return
            raise ResearchConflictError(str(error)) from error
        except (PlanCompileError, RuntimeError, ValueError) as error:
            await self._fail_planning(run, owner=owner, error_code=self._error_code(error))

    async def _fail_planning(
        self,
        run: AgentRun,
        *,
        owner: ResearchOwnerScope,
        error_code: str,
    ) -> None:
        context = self._require_context(run.id, owner=owner)
        if context.workflow.phase == ResearchPhase.TERMINAL:
            return
        self.repository.publish_planning(
            PlanningMutation(
                run_id=run.id,
                expected_state_version=context.workflow.state_version,
                workflow=context.workflow.model_copy(
                    update={"phase": ResearchPhase.TERMINAL, "active_gate": ResearchGate.NONE}
                ),
                terminal_status=AgentRunStatus.FAILED,
                error_code=error_code,
            )
        )

    def _schedule_execution(self, attempt_id: str) -> None:
        self._schedule(f"execution:{attempt_id}", self._run_execution(attempt_id))

    def resume_approved_attempt(self, attempt_id: str) -> bool:
        """Schedule an atomically approved PENDING attempt exactly once per process."""

        if not self.execution_allowed():
            return False
        self._schedule_execution(attempt_id)
        return True

    def recover_eligible_attempts(self) -> int:
        """Schedule persisted PENDING or expired attempts; SQLite remains the claim arbiter."""

        if not self.execution_allowed():
            return 0
        now = self.clock.now()
        self.repository.expire_research_attempt_deadlines(now)
        attempt_ids = self.repository.list_recoverable_research_attempt_ids(now)
        for attempt_id in attempt_ids:
            self._schedule_execution(attempt_id)
        return len(attempt_ids)

    async def _run_execution(self, attempt_id: str) -> None:
        try:
            await self.execution.claim_and_run(attempt_id)
        except Exception as error:
            code = self._error_code(error)
            if code == "execution_disabled":
                return
            if code == "tool_result_unknown":
                invocation = self.repository.enter_research_recovery_decision(
                    attempt_id,
                    error_code=code,
                    now=self.clock.now(),
                )
                if invocation is not None:
                    return
            raise

    def _schedule(self, key: str, coroutine) -> None:  # noqa: ANN001
        current = self._background_tasks.get(key)
        if current is not None and not current.done():
            coroutine.close()
            return
        task = asyncio.create_task(coroutine, name=f"research:{key}")
        self._background_tasks[key] = task

        def complete(done: asyncio.Task[None]) -> None:
            if self._background_tasks.get(key) is done:
                self._background_tasks.pop(key, None)
            if done.cancelled():
                return
            error = done.exception()
            if error is not None:
                self._background_errors.append(error)

        task.add_done_callback(complete)

    def _new_attempt(
        self,
        context: WorkflowContext,
        *,
        retry_of: str | None = None,
    ) -> tuple[ExecutionAttempt, tuple[ResearchStep, ...]]:
        if context.active_plan is None:
            raise ResearchConflictError("research execution plan is missing")
        now = self.clock.now()
        body = validate_execution_plan_version(context.active_plan)
        attempt = ExecutionAttempt(
            id=self.id_factory("attempt"),
            run_id=context.run.id,
            plan_version_id=context.active_plan.id,
            attempt_number=context.attempt_count + 1,
            retry_of_attempt_id=retry_of,
            deadline_at=now + timedelta(seconds=body.execution_budget_seconds) + self.settlement_grace,
            created_at=now,
            updated_at=now,
        )
        steps = tuple(
            ResearchStep(
                attempt_id=attempt.id,
                step_number=step.step_number,
                status=StepStatus.READY if not step.depends_on else StepStatus.PENDING,
                updated_at=now,
            )
            for step in body.steps
        )
        return attempt, steps

    def _projection(self, context: WorkflowContext) -> ResearchRunProjection:
        requirement_projection = None
        if context.active_requirement is not None:
            task = self._requirement_task(context.active_requirement)
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
        result_snapshot = self.artifacts.research_result_snapshot(
            run_id=context.run.id,
            attempt_id=context.workflow.active_attempt_id,
            reader_scope=ArtifactReaderScope(
                user_id=context.run.user_id,
                workspace_id=context.run.workspace_id,
                project_id=context.run.project_id,
                run_id=context.run.id,
            ),
        )
        verified_result = build_verified_research_result(
            self.artifacts,
            result_snapshot,
            run_id=context.run.id,
            attempt_id=context.workflow.active_attempt_id,
            reader_scope=ArtifactReaderScope(
                user_id=context.run.user_id,
                workspace_id=context.run.workspace_id,
                project_id=context.run.project_id,
                run_id=context.run.id,
            ),
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
            context = self.repository.load_context(run_id, owner=owner)
        except ResearchStoreConflict as error:
            raise ResearchConflictError(str(error)) from error
        if context is None:
            raise ResearchNotFoundError(run_id)
        return context

    @staticmethod
    def _require_version(context: WorkflowContext, expected: int) -> None:
        if context.workflow.state_version != expected:
            raise ResearchConflictError("research workflow state version conflict")

    def _commit(self, mutation: CommandMutation) -> CommandCommitResult:
        try:
            return self.repository.commit_command(mutation)
        except ResearchStoreConflict as error:
            raise ResearchConflictError(str(error)) from error
        except RuntimeError as error:
            if "state version conflict" in str(error) or "different research command" in str(error):
                raise ResearchConflictError(str(error)) from error
            raise

    def _replay(
        self,
        run_id: str,
        *,
        owner: ResearchOwnerScope,
        idempotency_key: str,
        command_type: ResearchCommandType,
        request_hash: str,
    ) -> ResearchCommandResponse | None:
        try:
            receipt = self.repository.replay_command(
                run_id,
                owner=owner,
                idempotency_key=idempotency_key,
                command_type=command_type,
                request_hash=request_hash,
            )
        except ResearchStoreConflict as error:
            raise ResearchConflictError(str(error)) from error
        except RuntimeError as error:
            if "different research command" in str(error):
                raise ResearchConflictError(str(error)) from error
            raise
        return self._command_response(receipt, replayed=True) if receipt is not None else None

    def _receipt(
        self,
        run_id: str,
        idempotency_key: str,
        command_type: ResearchCommandType,
        request_hash: str,
        state_version: int,
    ) -> ResearchCommandReceipt:
        return ResearchCommandReceipt(
            run_id=run_id,
            idempotency_key=idempotency_key,
            command_type=command_type,
            request_hash=request_hash,
            response_status=202,
            response_payload={
                "run_id": run_id,
                "command_type": command_type,
                "state_version": state_version,
                "accepted": True,
                "replayed": False,
            },
            created_at=self.clock.now(),
        )

    @staticmethod
    def _command_response(receipt: ResearchCommandReceipt, *, replayed: bool) -> ResearchCommandResponse:
        payload = dict(receipt.response_payload)
        payload["replayed"] = replayed
        if receipt.command_type == "purge":
            payload = {
                "run_id": receipt.run_id,
                "command_type": "purge",
                "state_version": None,
                "accepted": True,
                "replayed": replayed,
                "purged_artifact_count": int(receipt.response_payload.get("artifact_count", 0)),
            }
        return ResearchCommandResponse.model_validate(payload)

    @staticmethod
    def _command_hash(
        command_type: ResearchCommandType,
        run_id: str,
        request: object,
        **path_values: str,
    ) -> str:
        request_payload = request.model_dump(mode="json") if hasattr(request, "model_dump") else request
        return canonical_sha256(
            {
                "run_id": run_id,
                "command_type": command_type,
                "path": path_values,
                "request": request_payload,
            }
        )

    @staticmethod
    def _requirement_task(requirement: RequirementVersion) -> ResearchTaskV2:
        try:
            return ResearchTaskV2.model_validate(requirement.payload["requirement"])
        except (KeyError, TypeError, ValueError):
            raise ResearchConflictError("research requirement failed integrity verification") from None

    @staticmethod
    def _error_code(error: BaseException) -> str:
        code = getattr(error, "code", None)
        if isinstance(code, str) and code:
            return code[:120]
        codes = getattr(error, "codes", None)
        if isinstance(codes, list) and codes and isinstance(codes[0], str):
            return codes[0][:120]
        return "research_background_failed"
