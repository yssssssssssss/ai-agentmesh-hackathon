from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from agentmesh.research_orchestration.v3.common import (
    FrozenJson,
    FrozenJsonObject,
    Identifier,
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


_TERMINAL_DEPENDENCY_STATES = {
    StepExecutionStatus.SUCCEEDED,
    StepExecutionStatus.OPTIONAL_FAILED,
}
_BLOCKING_DEPENDENCY_STATES = {
    StepExecutionStatus.CORE_FAILED,
    StepExecutionStatus.BLOCKED,
}


@dataclass(frozen=True, slots=True)
class StepExecutionRecord:
    step_number: int
    required: bool
    status: StepExecutionStatus
    result: ActorExecutionResultV3 | None = None
    error: str | None = None


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
    def succeeded(self) -> bool:
        return all(
            record.status in {StepExecutionStatus.SUCCEEDED, StepExecutionStatus.OPTIONAL_FAILED}
            for record in self.steps
        )


class DeterministicWaveScheduler:
    """Choose stable topological waves; optional failures are non-blocking gaps."""

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


class WaveExecutionEngine:
    """Execute independent branches concurrently while preserving deterministic outcome ordering."""

    def __init__(
        self,
        dispatcher: HeterogeneousActorDispatcher,
        *,
        input_resolver: PlanInputResolver | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._input_resolver = input_resolver or PlanInputResolver()

    async def execute(
        self,
        *,
        plan: ExecutionPlanVersionV3,
        attempt_id: Identifier,
    ) -> WaveExecutionResult:
        statuses = {
            step.step_number: StepExecutionStatus.PENDING for step in plan.payload.steps
        }
        records: dict[int, StepExecutionRecord] = {}
        successful_results: dict[int, ActorExecutionResultV3] = {}
        waves: list[tuple[int, ...]] = []

        while any(status == StepExecutionStatus.PENDING for status in statuses.values()):
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
                    )
                    for step in wave
                ),
                return_exceptions=True,
            )
            for step, completion in zip(wave, completions, strict=True):
                if isinstance(completion, BaseException):
                    if isinstance(completion, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
                        raise completion
                    status = (
                        StepExecutionStatus.CORE_FAILED
                        if step.required
                        else StepExecutionStatus.OPTIONAL_FAILED
                    )
                    statuses[step.step_number] = status
                    records[step.step_number] = StepExecutionRecord(
                        step_number=step.step_number,
                        required=step.required,
                        status=status,
                        error=f"{type(completion).__name__}: {completion}",
                    )
                    continue
                statuses[step.step_number] = StepExecutionStatus.SUCCEEDED
                successful_results[step.step_number] = completion
                records[step.step_number] = StepExecutionRecord(
                    step_number=step.step_number,
                    required=step.required,
                    status=StepExecutionStatus.SUCCEEDED,
                    result=completion,
                )

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
    ) -> ActorExecutionResultV3:
        resolved_input = self._input_resolver.resolve(step, successful_results)
        request = ActorExecutionRequestV3(
            run_id=run_id,
            plan_version_id=plan_version_id,
            attempt_id=attempt_id,
            step=step,
            resolved_input=resolved_input,
        )
        return await self._dispatcher.execute(request)


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
class ExecutionRecoveryState:
    attempt_id: str
    status: RecoveryStatus
    failed_step_number: int | None = None
    failed_step_required: bool | None = None
    pause_reason: RecoveryPauseReason | None = None
    successor_attempt_id: str | None = None
    successor_plan_version_id: str | None = None


class RecoveryTransitionError(ValueError):
    pass


class ExecutionRecoveryStateMachine:
    """Pure retry/skip/abort transitions; it has no route, Store, or Provider dependency."""

    @staticmethod
    def start(attempt_id: str) -> ExecutionRecoveryState:
        return ExecutionRecoveryState(attempt_id=attempt_id, status=RecoveryStatus.RUNNING)

    @staticmethod
    def pause(
        state: ExecutionRecoveryState,
        *,
        step_number: int,
        required: bool,
        reason: RecoveryPauseReason,
    ) -> ExecutionRecoveryState:
        if state.status != RecoveryStatus.RUNNING:
            raise RecoveryTransitionError("only a running attempt can be paused")
        return ExecutionRecoveryState(
            attempt_id=state.attempt_id,
            status=RecoveryStatus.PAUSED,
            failed_step_number=step_number,
            failed_step_required=required,
            pause_reason=reason,
        )

    @staticmethod
    def retry(state: ExecutionRecoveryState, *, new_attempt_id: str) -> ExecutionRecoveryState:
        ExecutionRecoveryStateMachine._require_paused(state)
        if new_attempt_id == state.attempt_id:
            raise RecoveryTransitionError("retry must create a new Attempt identity")
        return ExecutionRecoveryState(
            attempt_id=state.attempt_id,
            status=RecoveryStatus.RETRY_SCHEDULED,
            failed_step_number=state.failed_step_number,
            failed_step_required=state.failed_step_required,
            pause_reason=state.pause_reason,
            successor_attempt_id=new_attempt_id,
        )

    @staticmethod
    def skip(state: ExecutionRecoveryState, *, new_plan_version_id: str) -> ExecutionRecoveryState:
        ExecutionRecoveryStateMachine._require_paused(state)
        if state.pause_reason != RecoveryPauseReason.FAILED or state.failed_step_required is not False:
            raise RecoveryTransitionError("skip is allowed only for an optional failed Step")
        return ExecutionRecoveryState(
            attempt_id=state.attempt_id,
            status=RecoveryStatus.SKIP_SCHEDULED,
            failed_step_number=state.failed_step_number,
            failed_step_required=False,
            pause_reason=state.pause_reason,
            successor_plan_version_id=new_plan_version_id,
        )

    @staticmethod
    def abort(state: ExecutionRecoveryState) -> ExecutionRecoveryState:
        if state.status not in {RecoveryStatus.RUNNING, RecoveryStatus.PAUSED}:
            raise RecoveryTransitionError("a terminal recovery decision cannot be replaced")
        return ExecutionRecoveryState(
            attempt_id=state.attempt_id,
            status=RecoveryStatus.ABORTED,
            failed_step_number=state.failed_step_number,
            failed_step_required=state.failed_step_required,
            pause_reason=state.pause_reason,
        )

    @staticmethod
    def accept_late_success(state: ExecutionRecoveryState) -> ExecutionRecoveryState:
        ExecutionRecoveryStateMachine._require_paused(state)
        if state.pause_reason != RecoveryPauseReason.UNKNOWN:
            raise RecoveryTransitionError("only an UNKNOWN invocation can reconcile a late success")
        return ExecutionRecoveryState(attempt_id=state.attempt_id, status=RecoveryStatus.RUNNING)

    @staticmethod
    def _require_paused(state: ExecutionRecoveryState) -> None:
        if state.status != RecoveryStatus.PAUSED:
            raise RecoveryTransitionError("recovery decisions require a paused Attempt")
