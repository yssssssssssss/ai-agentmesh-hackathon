from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal, Protocol, TypeVar

from pydantic import Field

from agentmesh.research_orchestration.v3.common import (
    ApprovalRole,
    FrozenJson,
    FrozenJsonObject,
    Identifier,
    StrictFrozenModel,
    freeze_json_object,
    thaw_json_value,
)
from agentmesh.research_orchestration.v3.execution_plan import ExecutionPlanVersionV3, PlanStepV3
from agentmesh.research_orchestration.v3.ports import (
    ActorExecutionRequestV3,
    ActorExecutionResultV3,
    ArtifactReadPort,
    validate_actor_result_for_request,
)

MAX_WAVE_CONCURRENCY = 3
_MISSING = object()
_ResultT = TypeVar("_ResultT")


class ExecutionClock(Protocol):
    def monotonic(self) -> float: ...


class ExecutionCancellationPort(Protocol):
    async def run(
        self,
        operation: Callable[[], Awaitable[_ResultT]],
        *,
        timeout_seconds: float,
    ) -> _ResultT: ...


class MonotonicExecutionClock:
    def monotonic(self) -> float:
        return time.monotonic()


class AsyncioExecutionCancellation:
    async def run(
        self,
        operation: Callable[[], Awaitable[_ResultT]],
        *,
        timeout_seconds: float,
    ) -> _ResultT:
        return await asyncio.wait_for(operation(), timeout=timeout_seconds)


class StepApprovalProofV3(StrictFrozenModel):
    """An approved receipt bound to one exact Plan attempt and Step."""

    run_id: Identifier
    plan_version_id: Identifier
    attempt_id: Identifier
    step_number: Annotated[int, Field(ge=1, le=8)]
    role: ApprovalRole
    decision: Literal["approved"]
    receipt_id: Identifier


class ToolActorPort(Protocol):
    async def execute(self, request: ActorExecutionRequestV3) -> ActorExecutionResultV3: ...


class SkillActorPort(Protocol):
    async def execute(self, request: ActorExecutionRequestV3) -> ActorExecutionResultV3: ...


class LlmActorPort(Protocol):
    async def execute(self, request: ActorExecutionRequestV3) -> ActorExecutionResultV3: ...


class ReviewerActorPort(Protocol):
    async def execute(self, request: ActorExecutionRequestV3) -> ActorExecutionResultV3: ...


class HeterogeneousActorDispatcher:
    """Dispatch one frozen step to its injected actor port and verify its completion envelope."""

    def __init__(
        self,
        *,
        tool: ToolActorPort,
        skill: SkillActorPort,
        llm: LlmActorPort,
        reviewer: ReviewerActorPort,
    ) -> None:
        self._ports = {
            "tool": tool,
            "skill": skill,
            "llm": llm,
            "reviewer": reviewer,
        }

    async def execute(self, request: ActorExecutionRequestV3) -> ActorExecutionResultV3:
        result = await self._ports[request.step.actor_type].execute(request)
        validate_actor_result_for_request(request, result)
        if request.step.actor_type == "tool" and result.execution_mode != "real":
            raise ValueError("Slice 1 Tool execution results must come from a real implementation")
        return result


class StepExecutionStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    CORE_FAILED = "core_failed"
    OPTIONAL_FAILED = "optional_failed"
    BLOCKED = "blocked"


class ExecutionOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    PLAN_REVISION_REQUIRED = "plan_revision_required"
    FAILED = "failed"


_TERMINAL_DEPENDENCY_STATES = {StepExecutionStatus.SUCCEEDED}
_BLOCKING_DEPENDENCY_STATES = {
    StepExecutionStatus.CORE_FAILED,
    StepExecutionStatus.OPTIONAL_FAILED,
    StepExecutionStatus.BLOCKED,
}


@dataclass(frozen=True, slots=True)
class StepExecutionRecord:
    step_number: int
    required: bool
    status: StepExecutionStatus
    result: ActorExecutionResultV3 | None = None
    error: str | None = None
    send_count: int = 0


@dataclass(frozen=True, slots=True)
class WaveExecutionResult:
    waves: tuple[tuple[int, ...], ...]
    steps: tuple[StepExecutionRecord, ...]

    @property
    def actor_results(self) -> tuple[ActorExecutionResultV3, ...]:
        return tuple(record.result for record in self.steps if record.result is not None)

    @property
    def optional_gap_step_numbers(self) -> tuple[int, ...]:
        return tuple(
            record.step_number
            for record in self.steps
            if record.status == StepExecutionStatus.OPTIONAL_FAILED
        )

    @property
    def outcome(self) -> ExecutionOutcome:
        if any(record.status == StepExecutionStatus.CORE_FAILED for record in self.steps):
            return ExecutionOutcome.FAILED
        if any(record.status == StepExecutionStatus.OPTIONAL_FAILED for record in self.steps):
            return ExecutionOutcome.PLAN_REVISION_REQUIRED
        if all(record.status == StepExecutionStatus.SUCCEEDED for record in self.steps):
            return ExecutionOutcome.SUCCEEDED
        return ExecutionOutcome.FAILED

    @property
    def succeeded(self) -> bool:
        return self.outcome == ExecutionOutcome.SUCCEEDED

    def require_delivery_results(self) -> tuple[ActorExecutionResultV3, ...]:
        """Return exact delivery coverage only for a wholly successful Plan attempt."""

        if not self.succeeded or len(self.actor_results) != len(self.steps):
            raise ValueError("delivery requires a successful result for every selected Plan Step")
        return self.actor_results


class DeterministicWaveScheduler:
    """Choose stable topological waves; any failure prevents dependent dispatch."""

    max_concurrency = MAX_WAVE_CONCURRENCY

    @staticmethod
    def propagate_blocked(
        plan: ExecutionPlanVersionV3,
        statuses: Mapping[int, StepExecutionStatus],
    ) -> dict[int, StepExecutionStatus]:
        resolved = {
            step.step_number: statuses.get(step.step_number, StepExecutionStatus.PENDING)
            for step in plan.payload.steps
        }
        changed = True
        while changed:
            changed = False
            for step in plan.payload.steps:
                if resolved[step.step_number] != StepExecutionStatus.PENDING:
                    continue
                if any(resolved[dependency] in _BLOCKING_DEPENDENCY_STATES for dependency in step.depends_on):
                    resolved[step.step_number] = StepExecutionStatus.BLOCKED
                    changed = True
        return resolved

    @classmethod
    def next_wave(
        cls,
        plan: ExecutionPlanVersionV3,
        statuses: Mapping[int, StepExecutionStatus],
    ) -> tuple[PlanStepV3, ...]:
        resolved = cls.propagate_blocked(plan, statuses)
        ready = [
            step
            for step in plan.payload.steps
            if resolved[step.step_number] == StepExecutionStatus.PENDING
            and all(resolved[dependency] in _TERMINAL_DEPENDENCY_STATES for dependency in step.depends_on)
        ]
        return tuple(sorted(ready, key=lambda step: step.step_number)[: cls.max_concurrency])


class PlanInputResolver:
    """Resolve declared input bindings only through verified Artifact reads."""

    def __init__(self, artifacts: ArtifactReadPort | None = None) -> None:
        self._artifacts = artifacts

    def resolve(
        self,
        step: PlanStepV3,
        successful_results: Mapping[int, ActorExecutionResultV3],
    ) -> FrozenJsonObject:
        resolved = thaw_json_value(step.input)
        if not isinstance(resolved, dict):
            raise ValueError("plan step input must be a JSON object")
        for binding in step.input_bindings:
            if self._artifacts is None:
                raise ValueError("verified Artifact reads are required to resolve input bindings")
            source_result = successful_results.get(binding.source_step_number)
            if source_result is None:
                raise ValueError("input binding source step has no successful Actor result")
            verified = self._artifacts.read_verified_json(
                run_id=source_result.run_id,
                plan_version_id=source_result.plan_version_id,
                attempt_id=source_result.attempt_id,
                step_number=source_result.step_number,
                artifact=source_result.result_artifact,
            )
            if verified is None:
                raise ValueError("input binding source Artifact failed verified readback")
            if (
                verified.actor_type,
                verified.actor_id,
                verified.step_contract_hash,
                verified.receipt_id,
                verified.implementation_id,
                verified.execution_mode,
                verified.artifact,
            ) != (
                source_result.actor_type,
                source_result.actor_id,
                source_result.step_contract_hash,
                source_result.receipt_id,
                source_result.implementation_id,
                source_result.execution_mode,
                source_result.result_artifact,
            ):
                raise ValueError("input binding Artifact identity does not match its Actor result")
            value = _resolve_result_pointer(verified.content, binding.source_pointer)
            if value is _MISSING:
                raise ValueError("input binding source pointer does not resolve")
            _replace_json_pointer(resolved, binding.target_pointer, thaw_json_value(value))
        return freeze_json_object(resolved)


def _pointer_segments(pointer: str) -> tuple[str, ...]:
    return tuple(segment.replace("~1", "/").replace("~0", "~") for segment in pointer[1:].split("/"))


def _resolve_pointer(value: object, pointer: str) -> object:
    current = value
    for segment in _pointer_segments(pointer):
        if isinstance(current, Mapping):
            if segment not in current:
                return _MISSING
            current = current[segment]
        elif isinstance(current, (list, tuple)):
            if not segment.isdigit() or (segment.startswith("0") and segment != "0"):
                return _MISSING
            index = int(segment)
            if index >= len(current):
                return _MISSING
            current = current[index]
        else:
            return _MISSING
    return current


def _resolve_result_pointer(content: FrozenJson, pointer: str) -> object:
    """Bindings address Actor output; persisted result envelopes may wrap it in ``output``."""

    if isinstance(content, Mapping) and "output" in content:
        resolved = _resolve_pointer(content["output"], pointer)
        if resolved is not _MISSING:
            return resolved
    return _resolve_pointer(content, pointer)


def _replace_json_pointer(root: object, pointer: str, value: object) -> None:
    segments = _pointer_segments(pointer)
    current = root
    for segment in segments[:-1]:
        if isinstance(current, dict):
            if segment not in current:
                raise ValueError("input binding target pointer does not resolve")
            current = current[segment]
        elif isinstance(current, list):
            if not segment.isdigit() or (segment.startswith("0") and segment != "0"):
                raise ValueError("input binding target array index is invalid")
            index = int(segment)
            if index >= len(current):
                raise ValueError("input binding target array index is out of range")
            current = current[index]
        else:
            raise ValueError("input binding target pointer does not resolve")
    final = segments[-1]
    if isinstance(current, dict):
        if final not in current:
            raise ValueError("input binding target pointer does not resolve")
        current[final] = value
    elif isinstance(current, list):
        if not final.isdigit() or (final.startswith("0") and final != "0"):
            raise ValueError("input binding target array index is invalid")
        index = int(final)
        if index >= len(current):
            raise ValueError("input binding target array index is out of range")
        current[index] = value
    else:
        raise ValueError("input binding target pointer does not resolve")


@dataclass(frozen=True, slots=True)
class _StepCompletion:
    result: ActorExecutionResultV3
    send_count: int


class StepDispatchError(RuntimeError):
    def __init__(self, message: str, *, send_count: int) -> None:
        super().__init__(message)
        self.send_count = send_count


class ActorInvocationTimedOut(StepDispatchError):
    pass


class WaveExecutionEngine:
    """Execute frozen waves with approval, send, timeout, and Plan-budget fences."""

    def __init__(
        self,
        dispatcher: HeterogeneousActorDispatcher,
        *,
        input_resolver: PlanInputResolver | None = None,
        clock: ExecutionClock | None = None,
        cancellation: ExecutionCancellationPort | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._input_resolver = input_resolver or PlanInputResolver()
        self._clock = clock or MonotonicExecutionClock()
        self._cancellation = cancellation or AsyncioExecutionCancellation()

    async def execute(
        self,
        *,
        plan: ExecutionPlanVersionV3,
        attempt_id: Identifier,
        approval_proofs: tuple[StepApprovalProofV3, ...] = (),
    ) -> WaveExecutionResult:
        self._validate_approval_proofs(plan, attempt_id, approval_proofs)
        plan_started_at = self._clock.monotonic()
        statuses = {
            step.step_number: StepExecutionStatus.PENDING for step in plan.payload.steps
        }
        records: dict[int, StepExecutionRecord] = {}
        successful_results: dict[int, ActorExecutionResultV3] = {}
        waves: list[tuple[int, ...]] = []

        while any(status == StepExecutionStatus.PENDING for status in statuses.values()):
            if self._remaining_plan_budget(plan, plan_started_at) <= 0:
                self._block_pending(
                    plan,
                    statuses,
                    records,
                    error="blocked because the 300-second Plan execution budget expired",
                )
                break
            propagated = DeterministicWaveScheduler.propagate_blocked(plan, statuses)
            for step in plan.payload.steps:
                number = step.step_number
                if statuses[number] != propagated[number]:
                    statuses[number] = propagated[number]
                    records[number] = StepExecutionRecord(
                        step_number=number,
                        required=step.required,
                        status=StepExecutionStatus.BLOCKED,
                        error="blocked by a failed core dependency",
                    )
            wave = DeterministicWaveScheduler.next_wave(plan, statuses)
            if not wave:
                if any(status == StepExecutionStatus.PENDING for status in statuses.values()):
                    raise RuntimeError("validated execution plan could not make scheduling progress")
                break
            waves.append(tuple(step.step_number for step in wave))
            completions = await asyncio.gather(
                *(
                    self._execute_step(
                        run_id=plan.run_id,
                        plan_version_id=plan.id,
                        attempt_id=attempt_id,
                        step=step,
                        successful_results=successful_results,
                        plan_started_at=plan_started_at,
                        plan_budget_seconds=plan.payload.execution_budget_seconds,
                    )
                    for step in wave
                ),
                return_exceptions=True,
            )
            optional_failure = False
            for step, completion in zip(wave, completions, strict=True):
                if isinstance(completion, BaseException):
                    if isinstance(completion, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
                        raise completion
                    status = (
                        StepExecutionStatus.CORE_FAILED
                        if step.required
                        else StepExecutionStatus.OPTIONAL_FAILED
                    )
                    optional_failure = optional_failure or status == StepExecutionStatus.OPTIONAL_FAILED
                    statuses[step.step_number] = status
                    records[step.step_number] = StepExecutionRecord(
                        step_number=step.step_number,
                        required=step.required,
                        status=status,
                        error=f"{type(completion).__name__}: {completion}",
                        send_count=getattr(completion, "send_count", 0),
                    )
                    continue
                statuses[step.step_number] = StepExecutionStatus.SUCCEEDED
                successful_results[step.step_number] = completion.result
                records[step.step_number] = StepExecutionRecord(
                    step_number=step.step_number,
                    required=step.required,
                    status=StepExecutionStatus.SUCCEEDED,
                    result=completion.result,
                    send_count=completion.send_count,
                )

            if optional_failure:
                self._block_pending(
                    plan,
                    statuses,
                    records,
                    error="blocked until an optional-failure Plan revision is selected",
                )
                break

        return WaveExecutionResult(
            waves=tuple(waves),
            steps=tuple(records[step.step_number] for step in plan.payload.steps),
        )

    async def _execute_step(
        self,
        *,
        run_id: Identifier,
        plan_version_id: Identifier,
        attempt_id: Identifier,
        step: PlanStepV3,
        successful_results: Mapping[int, ActorExecutionResultV3],
        plan_started_at: float,
        plan_budget_seconds: int,
    ) -> _StepCompletion:
        try:
            resolved_input = self._input_resolver.resolve(step, successful_results)
        except Exception as exc:
            raise StepDispatchError(str(exc), send_count=0) from exc
        request = ActorExecutionRequestV3(
            run_id=run_id,
            plan_version_id=plan_version_id,
            attempt_id=attempt_id,
            step=step,
            resolved_input=resolved_input,
        )
        step_started_at = self._clock.monotonic()
        for send_count in range(1, step.max_sends + 1):
            now = self._clock.monotonic()
            remaining_budget = plan_budget_seconds - (now - plan_started_at)
            remaining_step = step.timeout_seconds - (now - step_started_at)
            if remaining_budget <= 0:
                raise ActorInvocationTimedOut(
                    "Plan execution budget expired before Actor dispatch",
                    send_count=send_count - 1,
                )
            if remaining_step <= 0:
                raise ActorInvocationTimedOut(
                    "Step execution timeout expired before Actor dispatch",
                    send_count=send_count - 1,
                )
            timeout_seconds = min(remaining_step, remaining_budget)
            try:
                result = await self._cancellation.run(
                    lambda: self._dispatcher.execute(request),
                    timeout_seconds=timeout_seconds,
                )
            except asyncio.CancelledError:
                raise
            except TimeoutError as exc:
                # A timed-out external call is UNKNOWN and must never be resent automatically.
                raise ActorInvocationTimedOut(
                    "Actor invocation timed out and requires UNKNOWN reconciliation",
                    send_count=send_count,
                ) from exc
            except Exception as exc:
                if send_count == step.max_sends:
                    raise StepDispatchError(
                        f"Actor failed after {send_count} send(s): {exc}",
                        send_count=send_count,
                    ) from exc
                continue
            step_elapsed = self._clock.monotonic() - step_started_at
            total_elapsed = self._clock.monotonic() - plan_started_at
            if step_elapsed >= step.timeout_seconds or total_elapsed >= plan_budget_seconds:
                raise ActorInvocationTimedOut(
                    "Actor completion arrived after its execution deadline",
                    send_count=send_count,
                )
            return _StepCompletion(result=result, send_count=send_count)
        raise AssertionError("validated max_sends must permit at least one send")

    def _remaining_plan_budget(
        self,
        plan: ExecutionPlanVersionV3,
        plan_started_at: float,
    ) -> float:
        return plan.payload.execution_budget_seconds - (
            self._clock.monotonic() - plan_started_at
        )

    @staticmethod
    def _validate_approval_proofs(
        plan: ExecutionPlanVersionV3,
        attempt_id: Identifier,
        approval_proofs: tuple[StepApprovalProofV3, ...],
    ) -> None:
        proof_steps = tuple(proof.step_number for proof in approval_proofs)
        if len(set(proof_steps)) != len(proof_steps):
            raise ValueError("approval proofs must bind distinct Steps")
        required_steps = {
            step.step_number: step
            for step in plan.payload.steps
            if step.requires_approval
        }
        if set(proof_steps) != set(required_steps):
            raise ValueError("approval proofs must exactly cover approval-required Plan Steps")
        for proof in approval_proofs:
            step = required_steps[proof.step_number]
            if (
                proof.run_id,
                proof.plan_version_id,
                proof.attempt_id,
                proof.role,
            ) != (
                plan.run_id,
                plan.id,
                attempt_id,
                step.approval_role,
            ):
                raise ValueError("approval proof does not bind the selected Plan attempt and role")

    @staticmethod
    def _block_pending(
        plan: ExecutionPlanVersionV3,
        statuses: dict[int, StepExecutionStatus],
        records: dict[int, StepExecutionRecord],
        *,
        error: str,
    ) -> None:
        for step in plan.payload.steps:
            if statuses[step.step_number] == StepExecutionStatus.PENDING:
                statuses[step.step_number] = StepExecutionStatus.BLOCKED
                records[step.step_number] = StepExecutionRecord(
                    step_number=step.step_number,
                    required=step.required,
                    status=StepExecutionStatus.BLOCKED,
                    error=error,
                )


class RecoveryStatus(StrEnum):
    RUNNING = "running"
    PAUSED = "paused"
    RETRY_SCHEDULED = "retry_scheduled"
    SKIP_SCHEDULED = "skip_scheduled"
    ABORTED = "aborted"


class RecoveryPauseReason(StrEnum):
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class LateSuccessProof:
    plan_version_id: str
    attempt_id: str
    step_number: int
    invocation_id: str
    receipt_id: str

    def __post_init__(self) -> None:
        _require_identity(self.plan_version_id, "late-success Plan")
        _require_identity(self.attempt_id, "late-success Attempt")
        _require_identity(self.invocation_id, "late-success invocation")
        _require_identity(self.receipt_id, "late-success receipt")
        if self.step_number < 1:
            raise RecoveryTransitionError("late-success Step identity must be positive")


@dataclass(frozen=True, slots=True)
class ExecutionRecoveryState:
    plan_version_id: str
    attempt_id: str
    status: RecoveryStatus
    source_plan_version_id: str | None = None
    source_attempt_id: str | None = None
    failed_step_number: int | None = None
    failed_step_required: bool | None = None
    pause_reason: RecoveryPauseReason | None = None
    unknown_invocation_id: str | None = None
    late_success_receipt_id: str | None = None
    successor_attempt_id: str | None = None
    successor_plan_version_id: str | None = None

    def __post_init__(self) -> None:
        _require_identity(self.plan_version_id, "Plan")
        _require_identity(self.attempt_id, "Attempt")
        optional_identities = (
            (self.source_plan_version_id, "source Plan"),
            (self.source_attempt_id, "source Attempt"),
            (self.unknown_invocation_id, "UNKNOWN invocation"),
            (self.late_success_receipt_id, "late-success receipt"),
            (self.successor_attempt_id, "successor Attempt"),
            (self.successor_plan_version_id, "successor Plan"),
        )
        for value, label in optional_identities:
            if value is not None:
                _require_identity(value, label)


class RecoveryTransitionError(ValueError):
    pass


class ExecutionRecoveryStateMachine:
    """Pure identity-bound recovery transitions with terminal decision fencing."""

    @staticmethod
    def start(*, plan_version_id: str, attempt_id: str) -> ExecutionRecoveryState:
        _require_identity(plan_version_id, "Plan")
        _require_identity(attempt_id, "Attempt")
        return ExecutionRecoveryState(
            plan_version_id=plan_version_id,
            attempt_id=attempt_id,
            status=RecoveryStatus.RUNNING,
        )

    @staticmethod
    def pause(
        state: ExecutionRecoveryState,
        *,
        step_number: int,
        required: bool,
        reason: RecoveryPauseReason,
        invocation_id: str | None = None,
    ) -> ExecutionRecoveryState:
        if state.status != RecoveryStatus.RUNNING:
            raise RecoveryTransitionError("only a running attempt can be paused")
        if step_number < 1:
            raise RecoveryTransitionError("paused Step identity must be positive")
        if reason == RecoveryPauseReason.UNKNOWN:
            _require_identity(invocation_id, "UNKNOWN invocation")
        elif invocation_id is not None:
            raise RecoveryTransitionError("only an UNKNOWN pause may retain an invocation identity")
        return ExecutionRecoveryState(
            plan_version_id=state.plan_version_id,
            attempt_id=state.attempt_id,
            status=RecoveryStatus.PAUSED,
            source_plan_version_id=state.source_plan_version_id,
            source_attempt_id=state.source_attempt_id,
            failed_step_number=step_number,
            failed_step_required=required,
            pause_reason=reason,
            unknown_invocation_id=invocation_id,
        )

    @staticmethod
    def retry(state: ExecutionRecoveryState, *, new_attempt_id: str) -> ExecutionRecoveryState:
        ExecutionRecoveryStateMachine._require_paused(state)
        _require_distinct_identity(
            new_attempt_id,
            state.attempt_id,
            "retry Attempt",
        )
        return ExecutionRecoveryState(
            plan_version_id=state.plan_version_id,
            attempt_id=state.attempt_id,
            status=RecoveryStatus.RETRY_SCHEDULED,
            source_plan_version_id=state.source_plan_version_id,
            source_attempt_id=state.source_attempt_id,
            failed_step_number=state.failed_step_number,
            failed_step_required=state.failed_step_required,
            pause_reason=state.pause_reason,
            unknown_invocation_id=state.unknown_invocation_id,
            successor_plan_version_id=state.plan_version_id,
            successor_attempt_id=new_attempt_id,
        )

    @staticmethod
    def skip(
        state: ExecutionRecoveryState,
        *,
        new_plan_version_id: str,
        new_attempt_id: str,
    ) -> ExecutionRecoveryState:
        ExecutionRecoveryStateMachine._require_paused(state)
        if state.pause_reason != RecoveryPauseReason.FAILED or state.failed_step_required is not False:
            raise RecoveryTransitionError("skip is allowed only for an optional failed Step")
        _require_distinct_identity(
            new_plan_version_id,
            state.plan_version_id,
            "skip Plan",
        )
        _require_distinct_identity(
            new_attempt_id,
            state.attempt_id,
            "skip Attempt",
        )
        return ExecutionRecoveryState(
            plan_version_id=state.plan_version_id,
            attempt_id=state.attempt_id,
            status=RecoveryStatus.SKIP_SCHEDULED,
            source_plan_version_id=state.source_plan_version_id,
            source_attempt_id=state.source_attempt_id,
            failed_step_number=state.failed_step_number,
            failed_step_required=False,
            pause_reason=state.pause_reason,
            successor_plan_version_id=new_plan_version_id,
            successor_attempt_id=new_attempt_id,
        )

    @staticmethod
    def begin_successor(state: ExecutionRecoveryState) -> ExecutionRecoveryState:
        if state.status not in {RecoveryStatus.RETRY_SCHEDULED, RecoveryStatus.SKIP_SCHEDULED}:
            raise RecoveryTransitionError("only a scheduled recovery may start a successor execution")
        if state.successor_plan_version_id is None or state.successor_attempt_id is None:
            raise RecoveryTransitionError("scheduled recovery lacks successor Plan or Attempt identity")
        return ExecutionRecoveryState(
            plan_version_id=state.successor_plan_version_id,
            attempt_id=state.successor_attempt_id,
            status=RecoveryStatus.RUNNING,
            source_plan_version_id=state.plan_version_id,
            source_attempt_id=state.attempt_id,
        )

    @staticmethod
    def abort(state: ExecutionRecoveryState) -> ExecutionRecoveryState:
        if state.status not in {RecoveryStatus.RUNNING, RecoveryStatus.PAUSED}:
            raise RecoveryTransitionError("a terminal recovery decision cannot be replaced")
        return ExecutionRecoveryState(
            plan_version_id=state.plan_version_id,
            attempt_id=state.attempt_id,
            status=RecoveryStatus.ABORTED,
            source_plan_version_id=state.source_plan_version_id,
            source_attempt_id=state.source_attempt_id,
            failed_step_number=state.failed_step_number,
            failed_step_required=state.failed_step_required,
            pause_reason=state.pause_reason,
            unknown_invocation_id=state.unknown_invocation_id,
        )

    @staticmethod
    def accept_late_success(
        state: ExecutionRecoveryState,
        *,
        proof: LateSuccessProof,
    ) -> ExecutionRecoveryState:
        ExecutionRecoveryStateMachine._require_paused(state)
        if state.pause_reason != RecoveryPauseReason.UNKNOWN:
            raise RecoveryTransitionError("only an UNKNOWN invocation can reconcile a late success")
        _require_identity(proof.invocation_id, "late-success invocation")
        _require_identity(proof.receipt_id, "late-success receipt")
        if (
            proof.plan_version_id,
            proof.attempt_id,
            proof.step_number,
            proof.invocation_id,
        ) != (
            state.plan_version_id,
            state.attempt_id,
            state.failed_step_number,
            state.unknown_invocation_id,
        ):
            raise RecoveryTransitionError(
                "late-success proof does not bind the UNKNOWN Plan, Attempt, Step, and invocation"
            )
        return ExecutionRecoveryState(
            plan_version_id=state.plan_version_id,
            attempt_id=state.attempt_id,
            status=RecoveryStatus.RUNNING,
            source_plan_version_id=state.source_plan_version_id,
            source_attempt_id=state.source_attempt_id,
            late_success_receipt_id=proof.receipt_id,
        )

    @staticmethod
    def _require_paused(state: ExecutionRecoveryState) -> None:
        if state.status != RecoveryStatus.PAUSED:
            raise RecoveryTransitionError("recovery decisions require a paused Attempt")


def _require_identity(value: str | None, label: str) -> None:
    if value is None or not value.strip():
        raise RecoveryTransitionError(f"{label} identity must be nonempty")


def _require_distinct_identity(value: str, source: str, label: str) -> None:
    _require_identity(value, label)
    if value == source:
        raise RecoveryTransitionError(f"{label} must be distinct from its source identity")
