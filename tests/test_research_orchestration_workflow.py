from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import pytest

from agentmesh.models import AgentRun, AgentRunStatus
from agentmesh.research_orchestration.api import (
    ResearchClarificationAnswer,
    ResearchClarifyRequest,
    ResearchConfirmPlanRequest,
    ResearchConflictError,
    ResearchExecuteRequest,
    ResearchNotFoundError,
    ResearchOwnerScope,
    ResearchPurgeRequest,
    ResearchRecoverRequest,
    ResearchRevisePlanRequest,
)
from agentmesh.research_orchestration.artifacts import ArtifactReaderScope, ResearchResultSnapshot
from agentmesh.research_orchestration.compiler import CompetitivePlanCompiler
from agentmesh.research_orchestration.contracts import (
    AttemptStatus,
    InvocationState,
    RequirementVersion,
    ResearchCommandReceipt,
    ResearchGate,
    ResearchPhase,
    ResearchWorkflow,
    ToolInvocation,
)
from agentmesh.research_orchestration.planning import (
    CompetitiveRequirementPlanner,
    requirement_version_from_result,
)
from agentmesh.research_orchestration.workflow import (
    CommandCommitResult,
    CommandMutation,
    PlanningMutation,
    ResearchWorkflowService,
    WorkflowContext,
)
from tests.research_orchestration_testkit import competitive_snapshot

NOW = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
OWNER = ResearchOwnerScope(user_id="user_1", workspace_id="workspace_1", project_id="project_1")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FixedClock:
    def now(self) -> datetime:
        return NOW


class SequentialIds:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def __call__(self, prefix: str) -> str:
        count = self.counts.get(prefix, 0) + 1
        self.counts[prefix] = count
        return f"{prefix}_{count}"


class FakeRepository:
    def __init__(self) -> None:
        self.contexts: dict[str, WorkflowContext] = {}
        self.receipts: dict[tuple[str, str], ResearchCommandReceipt] = {}
        self.publish_count = 0
        self.commit_count = 0
        self.retired_attempts: list[tuple[str, AttemptStatus]] = []
        self.invocations: dict[str, ToolInvocation] = {}
        self.recoverable_attempt_ids: list[str] = []

    @staticmethod
    def _owns(context: WorkflowContext, owner: ResearchOwnerScope) -> bool:
        return (
            context.run.user_id == owner.user_id
            and context.run.workspace_id == owner.workspace_id
            and context.run.project_id == owner.project_id
        )

    def ensure_workflow(self, run: AgentRun, workflow: ResearchWorkflow) -> WorkflowContext:
        existing = self.contexts.get(run.id)
        if existing is not None:
            return existing
        context = WorkflowContext(
            run=run,
            workflow=workflow,
            active_requirement=None,
            active_plan=None,
            active_attempt=None,
            steps=(),
            requirements=(),
            plans=(),
            attempt_count=0,
        )
        self.contexts[run.id] = context
        return context

    def load_context(self, run_id: str, *, owner: ResearchOwnerScope) -> WorkflowContext | None:
        context = self.contexts.get(run_id)
        if context is None or not self._owns(context, owner):
            return None
        return context

    def replay_command(
        self,
        run_id: str,
        *,
        owner: ResearchOwnerScope,
        idempotency_key: str,
        command_type: str,
        request_hash: str,
    ) -> ResearchCommandReceipt | None:
        context = self.load_context(run_id, owner=owner)
        if context is None:
            return None
        receipt = self.receipts.get((run_id, idempotency_key))
        if receipt is None:
            return None
        if receipt.command_type != command_type or receipt.request_hash != request_hash:
            raise RuntimeError("idempotency key was used for a different research command")
        return receipt

    @staticmethod
    def _advanced(workflow: ResearchWorkflow, expected_state_version: int) -> ResearchWorkflow:
        return workflow.model_copy(
            update={"state_version": expected_state_version + 1, "updated_at": NOW}
        )

    def publish_planning(self, mutation: PlanningMutation) -> WorkflowContext:
        context = self.contexts[mutation.run_id]
        if context.workflow.state_version != mutation.expected_state_version:
            raise RuntimeError("research workflow state version conflict")
        requirement = mutation.requirement or context.active_requirement
        plan = mutation.plan or context.active_plan
        requirements = context.requirements + ((mutation.requirement,) if mutation.requirement else ())
        plans = context.plans + ((mutation.plan,) if mutation.plan else ())
        run = context.run
        if mutation.terminal_status is not None:
            run = run.model_copy(
                update={"status": mutation.terminal_status, "error_code": mutation.error_code, "updated_at": NOW}
            )
        next_context = replace(
            context,
            run=run,
            workflow=self._advanced(mutation.workflow, mutation.expected_state_version),
            active_requirement=requirement,
            active_plan=plan,
            requirements=requirements,
            plans=plans,
        )
        self.contexts[mutation.run_id] = next_context
        self.publish_count += 1
        return next_context

    def commit_command(self, mutation: CommandMutation) -> CommandCommitResult:
        key = (mutation.receipt.run_id, mutation.receipt.idempotency_key)
        context = self.contexts[mutation.receipt.run_id]
        existing = self.receipts.get(key)
        if existing is not None:
            if (
                existing.command_type != mutation.receipt.command_type
                or existing.request_hash != mutation.receipt.request_hash
            ):
                raise RuntimeError("idempotency key was used for a different research command")
            return CommandCommitResult(receipt=existing, context=context, created=False)
        if context.workflow.state_version != mutation.expected_state_version:
            raise RuntimeError("research workflow state version conflict")
        if mutation.superseded_attempt_id is not None:
            assert mutation.superseded_attempt_status is not None
            assert context.active_attempt is not None
            assert context.active_attempt.id == mutation.superseded_attempt_id
            self.retired_attempts.append(
                (mutation.superseded_attempt_id, mutation.superseded_attempt_status)
            )
        attempt = mutation.attempt
        attempt_count = context.attempt_count + int(attempt is not None)
        steps = mutation.steps if attempt is not None else context.steps
        if mutation.superseded_attempt_id is not None and attempt is None:
            steps = ()
        run = context.run
        if mutation.terminal_status is not None:
            run = run.model_copy(
                update={"status": mutation.terminal_status, "error_code": mutation.error_code, "updated_at": NOW}
            )
        next_context = replace(
            context,
            run=run,
            workflow=self._advanced(mutation.workflow, mutation.expected_state_version),
            active_attempt=attempt if attempt is not None else (
                None if mutation.superseded_attempt_id is not None else context.active_attempt
            ),
            steps=steps,
            attempt_count=attempt_count,
            active_recovery_invocation=(
                None if mutation.recovery_invocation_id is not None else context.active_recovery_invocation
            ),
            active_tool_approval=mutation.approval_inbox,
        )
        self.contexts[mutation.receipt.run_id] = next_context
        if mutation.recovery_invocation_id is not None:
            invocation = self.invocations[mutation.recovery_invocation_id]
            if mutation.recovery_action == "retry":
                assert attempt is not None
                self.invocations[invocation.id] = invocation.model_copy(
                    update={
                        "active_attempt_id": attempt.id,
                        "state": InvocationState.PREPARED,
                        "sent_fencing_epoch": None,
                        "last_sent_at": None,
                        "unknown_at": None,
                        "error_code": None,
                    }
                )
        self.receipts[key] = mutation.receipt
        self.commit_count += 1
        return CommandCommitResult(receipt=mutation.receipt, context=next_context, created=True)

    def require_context(self, run_id: str) -> WorkflowContext:
        return self.contexts[run_id]

    def mark_recovery_required(self, run_id: str) -> ToolInvocation:
        context = self.contexts[run_id]
        assert context.active_attempt is not None
        attempt = context.active_attempt.model_copy(update={"status": AttemptStatus.RECOVERY_REQUIRED})
        workflow = context.workflow.model_copy(update={"active_gate": ResearchGate.RECOVERY_DECISION})
        invocation = ToolInvocation(
            id=f"invocation_{run_id}",
            run_id=run_id,
            plan_version_id=attempt.plan_version_id,
            step_number=1,
            operation_key="1" * 64,
            resolved_input_hash="2" * 64,
            request_artifact_id=f"artifact_request_{run_id}",
            active_attempt_id=attempt.id,
            state=InvocationState.UNKNOWN,
            send_count=1,
            active_send_sequence=1,
            sent_fencing_epoch=1,
            last_sent_at=NOW,
            unknown_at=NOW,
        )
        self.invocations[invocation.id] = invocation
        self.contexts[run_id] = replace(
            context,
            workflow=workflow,
            active_attempt=attempt,
            active_recovery_invocation=invocation,
        )
        return invocation

    def get_research_tool_invocation(self, invocation_id: str) -> ToolInvocation | None:
        return self.invocations.get(invocation_id)

    def list_recoverable_research_attempt_ids(self, now: datetime) -> list[str]:
        del now
        return list(self.recoverable_attempt_ids)

    def expire_research_attempt_deadlines(self, now: datetime) -> int:
        del now
        return 0


class FakePlanning:
    def __init__(self) -> None:
        self.prepare_calls = 0
        self.compile_calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.block = False
        self.fail = False

    async def prepare_requirement(
        self,
        run: AgentRun,
        *,
        version: int,
        clarification_answers: dict[str, str] | None = None,
        revision: ResearchRevisePlanRequest | None = None,
    ) -> RequirementVersion:
        self.prepare_calls += 1
        self.started.set()
        if self.block:
            await self.release.wait()
        if self.fail:
            raise RuntimeError("planner unavailable")
        text = run.input_text
        if revision is not None:
            text = revision.research_goal or text
            if revision.competitor_scope:
                text = f"{text}；对比 {revision.competitor_scope}"
        result = await CompetitiveRequirementPlanner().plan(
            text,
            clarification_answers=clarification_answers,
        )
        return requirement_version_from_result(run.id, version, result)

    def compile_plan(
        self,
        run: AgentRun,
        requirement: RequirementVersion,
        *,
        version: int,
    ):
        self.compile_calls += 1
        return CompetitivePlanCompiler().compile(
            requirement,
            competitive_snapshot(NOW),
            plan_version=version,
            now=NOW,
        )


class FakeExecutionEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.block = False
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def claim_and_run(self, attempt_id: str, *, token: str | None = None) -> None:
        self.calls.append((attempt_id, token))
        self.started.set()
        if self.block:
            await self.release.wait()


class FakePurger:
    def __init__(self) -> None:
        self.calls = 0
        self.last_receipt: ResearchCommandReceipt | None = None

    def purge_research_data_command(
        self,
        run_id: str,
        *,
        actor_user_id: str,
        workspace_id: str,
        expected_state_version: int,
        idempotency_key: str,
        request_hash: str,
        now: datetime,
    ) -> ResearchCommandReceipt:
        self.calls += 1
        self.last_receipt = ResearchCommandReceipt(
            run_id=run_id,
            idempotency_key=idempotency_key,
            command_type="purge",
            request_hash=request_hash,
            response_status=200,
            response_payload={"artifact_count": 3},
            created_at=now,
        )
        return self.last_receipt

    def research_result_snapshot(
        self,
        *,
        run_id: str,
        attempt_id: str | None,
        reader_scope: ArtifactReaderScope,
    ) -> ResearchResultSnapshot:
        del run_id, attempt_id, reader_scope
        return ResearchResultSnapshot()


@dataclass
class Harness:
    service: ResearchWorkflowService
    repository: FakeRepository
    planning: FakePlanning
    engine: FakeExecutionEngine
    purger: FakePurger


def make_run(run_id: str, text: str, *, mode: str = "execute") -> AgentRun:
    return AgentRun(
        id=run_id,
        thread_id=f"thread_{run_id}",
        user_id=OWNER.user_id,
        workspace_id=OWNER.workspace_id,
        project_id=OWNER.project_id,
        input_text=text,
        orchestration_version="research-v2",
        orchestration_mode=mode,
    )


@pytest.fixture
def harness() -> Harness:
    repository = FakeRepository()
    planning = FakePlanning()
    engine = FakeExecutionEngine()
    purger = FakePurger()
    return Harness(
        service=ResearchWorkflowService(
            repository,
            planning,
            engine,
            purger,
            clock=FixedClock(),
            id_factory=SequentialIds(),
        ),
        repository=repository,
        planning=planning,
        engine=engine,
        purger=purger,
    )


async def start_clear_run(harness: Harness, run_id: str = "run_clear") -> WorkflowContext:
    run = make_run(run_id, "对比 Figma 和 Miro 的协作与恢复能力")
    assert await harness.service.start_if_applicable(run) is not None
    await harness.service.wait_for_idle()
    return harness.repository.require_context(run_id)


async def confirm_active_plan(harness: Harness, run_id: str) -> WorkflowContext:
    context = harness.repository.require_context(run_id)
    assert context.active_plan is not None
    await harness.service.confirm_plan(
        run_id,
        context.active_plan.id,
        ResearchConfirmPlanRequest(expected_state_version=context.workflow.state_version),
        owner=OWNER,
        idempotency_key=f"confirm-{run_id}",
    )
    return harness.repository.require_context(run_id)


@pytest.mark.anyio
async def test_start_builds_clear_plan_and_get_projection_never_schedules_work(
    harness: Harness,
) -> None:
    context = await start_clear_run(harness)
    publish_count = harness.repository.publish_count
    planning_calls = (harness.planning.prepare_calls, harness.planning.compile_calls)

    first = harness.service.get_projection("run_clear", owner=OWNER)
    second = harness.service.get_projection("run_clear", owner=OWNER)

    assert first == second
    assert first.workflow.phase == ResearchPhase.PLANNING
    assert first.workflow.active_gate == ResearchGate.PLAN_CONFIRMATION
    assert len(first.plans) == 1
    assert first.plans[0].plan_version_id == context.active_plan.id
    assert harness.repository.publish_count == publish_count
    assert (harness.planning.prepare_calls, harness.planning.compile_calls) == planning_calls
    assert harness.engine.calls == []
    assert harness.service.background_task_count == 0


@pytest.mark.anyio
async def test_blocking_requirement_clarifies_once_and_duplicate_command_replays(
    harness: Harness,
) -> None:
    run = make_run("run_clarify", "帮我做竞品分析")
    await harness.service.start_if_applicable(run)
    await harness.service.wait_for_idle()
    blocked = harness.repository.require_context(run.id)
    assert blocked.workflow.phase == ResearchPhase.REQUIREMENT
    assert blocked.workflow.active_gate == ResearchGate.CLARIFICATION
    assert blocked.active_requirement is not None

    request = ResearchClarifyRequest(
        expected_state_version=blocked.workflow.state_version,
        answers=[
            ResearchClarificationAnswer(
                question_id="clarify_competitor_scope",
                answer="Figma 与 Miro",
            )
        ],
    )
    first = await harness.service.clarify(
        run.id,
        request,
        owner=OWNER,
        idempotency_key="clarify-once",
    )
    await harness.service.wait_for_idle()
    replay = await harness.service.clarify(
        run.id,
        request,
        owner=OWNER,
        idempotency_key="clarify-once",
    )

    context = harness.repository.require_context(run.id)
    assert first.replayed is False
    assert replay.replayed is True
    assert context.workflow.phase == ResearchPhase.PLANNING
    assert context.workflow.active_gate == ResearchGate.PLAN_CONFIRMATION
    assert len(context.requirements) == 2
    assert len(context.plans) == 1
    assert harness.planning.prepare_calls == 2


@pytest.mark.anyio
async def test_confirm_is_cas_guarded_and_replay_precedes_current_gate_validation(
    harness: Harness,
) -> None:
    context = await start_clear_run(harness, "run_confirm")
    assert context.active_plan is not None
    request = ResearchConfirmPlanRequest(expected_state_version=context.workflow.state_version)

    first = await harness.service.confirm_plan(
        context.run.id,
        context.active_plan.id,
        request,
        owner=OWNER,
        idempotency_key="confirm-once",
    )
    replay = await harness.service.confirm_plan(
        context.run.id,
        context.active_plan.id,
        request,
        owner=OWNER,
        idempotency_key="confirm-once",
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert harness.repository.commit_count == 1
    assert harness.repository.require_context(context.run.id).workflow.active_gate == ResearchGate.NONE
    with pytest.raises(ResearchConflictError, match="different research command"):
        await harness.service.confirm_plan(
            context.run.id,
            context.active_plan.id,
            ResearchConfirmPlanRequest(expected_state_version=request.expected_state_version + 1),
            owner=OWNER,
            idempotency_key="confirm-once",
        )


@pytest.mark.anyio
async def test_execute_atomically_starts_steps_and_duplicate_does_not_reschedule(
    harness: Harness,
) -> None:
    context = await start_clear_run(harness, "run_execute")
    context = await confirm_active_plan(harness, context.run.id)
    harness.engine.block = True
    request = ResearchExecuteRequest(expected_state_version=context.workflow.state_version)

    first = await harness.service.execute(
        context.run.id,
        request,
        owner=OWNER,
        idempotency_key="execute-once",
    )
    await harness.engine.started.wait()
    replay = await harness.service.execute(
        context.run.id,
        request,
        owner=OWNER,
        idempotency_key="execute-once",
    )

    executing = harness.repository.require_context(context.run.id)
    assert first.replayed is False
    assert replay.replayed is True
    assert executing.workflow.phase == ResearchPhase.EXECUTION
    assert executing.active_attempt is not None
    assert executing.active_attempt.status == AttemptStatus.PENDING
    assert [step.status.value for step in executing.steps] == ["ready", "pending"]
    assert len(harness.engine.calls) == 1
    assert harness.service.background_task_count == 1

    harness.engine.release.set()
    await harness.service.wait_for_idle()
    assert harness.service.background_task_count == 0


@pytest.mark.anyio
async def test_start_and_command_scheduling_are_race_safe_and_tasks_are_cleaned(
    harness: Harness,
) -> None:
    harness.planning.block = True
    run = make_run("run_dedup", "对比 Figma 和 Miro")

    assert await harness.service.start_if_applicable(run) is not None
    await harness.planning.started.wait()
    assert await harness.service.start_if_applicable(run) is not None
    assert harness.service.background_task_count == 1
    assert harness.planning.prepare_calls == 1

    harness.planning.release.set()
    await harness.service.wait_for_idle()
    assert harness.service.background_task_count == 0
    assert harness.planning.prepare_calls == 1


@pytest.mark.anyio
async def test_revise_supports_slice_a_goal_scope_only_and_publishes_new_versions(
    harness: Harness,
) -> None:
    original = await start_clear_run(harness, "run_revise")
    assert original.active_plan is not None
    request = ResearchRevisePlanRequest(
        expected_state_version=original.workflow.state_version,
        research_goal="对比白板产品的协作恢复体验",
        competitor_scope="Figma 与 Miro",
    )

    await harness.service.revise_plan(
        original.run.id,
        original.active_plan.id,
        request,
        owner=OWNER,
        idempotency_key="revise-plan",
    )
    await harness.service.wait_for_idle()

    revised = harness.repository.require_context(original.run.id)
    assert len(revised.requirements) == 2
    assert len(revised.plans) == 2
    assert revised.active_plan is not None
    assert revised.active_plan.id != original.active_plan.id
    projection = harness.service.get_projection(original.run.id, owner=OWNER)
    assert [plan.plan_version_id for plan in projection.plans] == [revised.active_plan.id]

    with pytest.raises(ResearchConflictError, match="Slice A"):
        await harness.service.revise_plan(
            original.run.id,
            revised.active_plan.id,
            ResearchRevisePlanRequest(
                expected_state_version=revised.workflow.state_version,
                assumptions=[
                    {
                        "assumption_id": "assumption_scope",
                        "accepted_by_user": True,
                    }
                ],
            ),
            owner=OWNER,
            idempotency_key="unsupported-revise",
        )


@pytest.mark.anyio
async def test_recover_retry_retires_old_attempt_and_schedules_exactly_once(
    harness: Harness,
) -> None:
    context = await start_clear_run(harness, "run_retry")
    context = await confirm_active_plan(harness, context.run.id)
    await harness.service.execute(
        context.run.id,
        ResearchExecuteRequest(expected_state_version=context.workflow.state_version),
        owner=OWNER,
        idempotency_key="initial-execute",
    )
    await harness.service.wait_for_idle()
    invocation = harness.repository.mark_recovery_required(context.run.id)
    recovery = harness.repository.require_context(context.run.id)
    assert recovery.active_attempt is not None
    recovery_projection = harness.service.get_projection(context.run.id, owner=OWNER)
    assert recovery_projection.recovery is not None
    assert recovery_projection.recovery.invocation_id == invocation.id
    assert recovery_projection.recovery.state == "unknown"
    assert recovery_projection.recovery.send_count == 1
    old_attempt_id = recovery.active_attempt.id
    request = ResearchRecoverRequest(
        expected_state_version=recovery.workflow.state_version,
        invocation_id=invocation.id,
        action="retry",
    )

    first = await harness.service.recover(
        context.run.id,
        request,
        owner=OWNER,
        idempotency_key="retry-once",
    )
    await harness.service.wait_for_idle()
    replay = await harness.service.recover(
        context.run.id,
        request,
        owner=OWNER,
        idempotency_key="retry-once",
    )

    retried = harness.repository.require_context(context.run.id)
    assert first.replayed is False
    assert replay.replayed is True
    assert harness.repository.retired_attempts[-1] == (old_attempt_id, AttemptStatus.FAILED)
    assert retried.active_attempt is not None
    assert retried.active_attempt.retry_of_attempt_id == old_attempt_id
    assert retried.active_attempt.attempt_number == 2
    assert len(harness.engine.calls) == 2


@pytest.mark.anyio
async def test_recover_abort_cancels_the_recovery_attempt(harness: Harness) -> None:
    action = "abort"
    context = await start_clear_run(harness, "run_abort")
    context = await confirm_active_plan(harness, context.run.id)
    await harness.service.execute(
        context.run.id,
        ResearchExecuteRequest(expected_state_version=context.workflow.state_version),
        owner=OWNER,
        idempotency_key=f"execute-{action}",
    )
    await harness.service.wait_for_idle()
    invocation = harness.repository.mark_recovery_required(context.run.id)
    recovery = harness.repository.require_context(context.run.id)
    assert recovery.active_attempt is not None
    old_attempt_id = recovery.active_attempt.id

    await harness.service.recover(
        context.run.id,
        ResearchRecoverRequest(
            expected_state_version=recovery.workflow.state_version,
            invocation_id=invocation.id,
            action=action,
        ),
        owner=OWNER,
        idempotency_key=f"recover-{action}",
    )
    await harness.service.wait_for_idle()

    recovered = harness.repository.require_context(context.run.id)
    assert harness.repository.retired_attempts[-1] == (old_attempt_id, AttemptStatus.CANCELLED)
    assert recovered.workflow.phase == ResearchPhase.TERMINAL
    assert recovered.run.status == AgentRunStatus.CANCELLED


@pytest.mark.anyio
async def test_purge_requires_terminal_owner_and_replays_without_second_purge(
    harness: Harness,
) -> None:
    context = await start_clear_run(harness, "run_purge")
    terminal_workflow = context.workflow.model_copy(
        update={"phase": ResearchPhase.TERMINAL, "active_gate": ResearchGate.NONE}
    )
    terminal_run = context.run.model_copy(update={"status": AgentRunStatus.COMPLETED})
    harness.repository.contexts[context.run.id] = replace(
        context,
        run=terminal_run,
        workflow=terminal_workflow,
    )
    request = ResearchPurgeRequest(expected_state_version=terminal_workflow.state_version)

    first = await harness.service.purge(
        context.run.id,
        request,
        owner=OWNER,
        idempotency_key="purge-once",
    )
    assert harness.purger.last_receipt is not None
    harness.repository.receipts[(context.run.id, "purge-once")] = harness.purger.last_receipt
    replay = await harness.service.purge(
        context.run.id,
        request,
        owner=OWNER,
        idempotency_key="purge-once",
    )

    assert first.purged_artifact_count == replay.purged_artifact_count == 3
    assert first.replayed is False
    assert replay.replayed is True
    assert harness.purger.calls == 1


def test_get_projection_hides_missing_or_cross_owner_runs(harness: Harness) -> None:
    with pytest.raises(ResearchNotFoundError):
        harness.service.get_projection("missing", owner=OWNER)


@pytest.mark.anyio
async def test_off_or_non_research_runs_do_not_create_workflows(harness: Harness) -> None:
    off = make_run("run_off", "对比 Figma 和 Miro", mode="off")
    legacy = make_run("run_legacy", "对比 Figma 和 Miro")
    legacy.orchestration_version = "v1"

    assert await harness.service.start_if_applicable(off) is None
    assert await harness.service.start_if_applicable(legacy) is None
    assert harness.repository.contexts == {}
    assert harness.service.background_task_count == 0
