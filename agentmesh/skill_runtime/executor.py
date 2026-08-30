from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from agentmesh.llm import llm_chat_timeout_seconds, research_skill_timeout_seconds
from agentmesh.models import (
    AgentPlanningContractVersion,
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    SkillNodeResult,
    SkillPlan,
    SkillPlanNode,
    SkillPlanNodeStatus,
    SkillPlanStatus,
    SkillSideEffect,
    SkillSynthesisResult,
    now_utc,
)
from agentmesh.runtime_admission import current_orchestration_admission
from agentmesh.runtime_capacity import RuntimeCapacityController, current_runtime_capacity
from agentmesh.skill_runtime.finalization import (
    NodePause,
    PlanExecutionOutcome,
    PlanFinalizationStrategy,
    StandardPlanFinalizer,
    SynthesisRunner,
)
from agentmesh.skill_runtime.quiesce import OrchestrationQuiesceController
from agentmesh.skill_runtime.universal_execution import universal_standard_execution_allowed
from agentmesh.store import SQLiteStore
from agentmesh.tool_runtime.guardrails import redact_sensitive_text


@dataclass(frozen=True, slots=True)
class NodeExecutionOutcome:
    result: SkillNodeResult | None = None
    pause: NodePause | None = None


NodeRunner = Callable[[SkillPlan, SkillPlanNode, list[SkillNodeResult]], Awaitable[NodeExecutionOutcome]]

_STANDARD_DELIVERABLE_TIMEOUT_SECONDS = 300.0


def skill_node_timeout_seconds(
    node: SkillPlanNode,
    *,
    planning_mode: AgentPlanningMode,
) -> float:
    timeout = (
        research_skill_timeout_seconds()
        if "web_research" in node.required_tool_names
        else llm_chat_timeout_seconds()
    )
    if planning_mode is AgentPlanningMode.STANDARD and node.output_contract:
        return max(timeout, _STANDARD_DELIVERABLE_TIMEOUT_SECONDS)
    return timeout


class PlanExecutionConflict(RuntimeError):
    """Another executor owns the Plan, or its persisted state changed."""


def _transient(error: Exception) -> bool:
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return False
    if isinstance(error, ConnectionError):
        return True
    return type(error).__name__ in {
        "APIConnectionError",
        "ConnectError",
        "InternalServerError",
        "NetworkError",
        "ReadError",
        "RemoteProtocolError",
        "RateLimitError",
        "ServiceUnavailableError",
        "TemporaryProviderError",
    }


def _error_code(error: Exception) -> str:
    root_error_code = getattr(error, "root_error_code", None)
    if isinstance(root_error_code, str) and root_error_code:
        return root_error_code
    message = str(error)
    safe = all(character.islower() or character.isdigit() or character == "_" for character in message)
    if message and len(message) <= 120 and safe:
        return message
    return type(error).__name__


def _error_detail(error: Exception) -> str:
    detail = redact_sensitive_text(str(error)).strip() or type(error).__name__
    attempts = getattr(error, "attempts", None)
    if type(attempts) is int and attempts > 1:
        detail = f"model stream failed after {attempts} attempts: {detail}"
    return detail[:500]


class BoundedDAGExecutor:
    def __init__(
        self,
        repository: SQLiteStore,
        *,
        node_runner: NodeRunner,
        synthesis_runner: SynthesisRunner | None = None,
        finalization_strategy: PlanFinalizationStrategy | None = None,
        admission: OrchestrationQuiesceController | None = None,
        capacity: RuntimeCapacityController | None = None,
    ):
        if synthesis_runner is not None and finalization_strategy is not None:
            raise ValueError("synthesis_runner and finalization_strategy are mutually exclusive")
        if synthesis_runner is None and finalization_strategy is None:
            raise ValueError("a finalization strategy or synthesis runner is required")
        self.repository = repository
        self.node_runner = node_runner
        self.admission = admission or current_orchestration_admission()
        self.capacity = capacity or current_runtime_capacity()
        if finalization_strategy is None:
            assert synthesis_runner is not None
            finalization_strategy = StandardPlanFinalizer(
                repository,
                synthesis_runner=synthesis_runner,
            )
        self.finalization_strategy = finalization_strategy

    @staticmethod
    def _replace_node(plan: SkillPlan, node: SkillPlanNode) -> None:
        plan.nodes = [node if item.id == node.id else item for item in plan.nodes]

    def _transition_node(
        self,
        *,
        plan: SkillPlan,
        run: AgentRun,
        node: SkillPlanNode,
        expected_statuses: set[SkillPlanNodeStatus],
        event_type: str,
        event_payload: dict[str, object],
        result: SkillNodeResult | None = None,
        expected_attempt: int | None = None,
    ) -> SkillPlanNode:
        transitioned = self.repository.transition_skill_plan_node(
            plan_id=plan.id,
            run_id=run.id,
            node=node,
            expected_statuses=expected_statuses,
            event_type=event_type,
            event_payload=event_payload,
            result=result,
            expected_attempt=expected_attempt,
        )
        if transitioned is None:
            current_run = self.repository.get_agent_run(run.id)
            if current_run is not None and current_run.status == AgentRunStatus.CANCELLED:
                raise asyncio.CancelledError
            raise RuntimeError(f"node_transition_conflict:{node.id}:{event_type}")
        self._replace_node(plan, transitioned)
        return transitioned

    async def _execute_one(
        self,
        plan: SkillPlan,
        run: AgentRun,
        node: SkillPlanNode,
        results: list[SkillNodeResult],
    ) -> tuple[SkillPlanNode, NodeExecutionOutcome | None, Exception | None]:
        async with self.capacity.node_slot():
            return await self._execute_one_reserved(plan, run, node, results)

    async def _execute_one_reserved(
        self,
        plan: SkillPlan,
        run: AgentRun,
        node: SkillPlanNode,
        results: list[SkillNodeResult],
    ) -> tuple[SkillPlanNode, NodeExecutionOutcome | None, Exception | None]:
        with self.admission.permit():
            claimed = self.repository.claim_skill_plan_node(plan.id, node.id)
        if claimed is None:
            return node, None, RuntimeError("node_claim_conflict")
        self._replace_node(plan, claimed)
        upstream = [result for result in results if result.node_id in set(claimed.depends_on)]
        node_timeout = skill_node_timeout_seconds(
            claimed,
            planning_mode=run.planning_mode,
        )
        remaining = node_timeout
        if run.deadline_at is not None:
            remaining = min(remaining, max(0.0, (run.deadline_at - now_utc()).total_seconds()))
        if remaining <= 0:
            return claimed, None, TimeoutError("parent_run_deadline_exceeded")
        try:
            async with asyncio.timeout(remaining):
                return claimed, await self.node_runner(plan, claimed, upstream), None
        except Exception as error:
            return claimed, None, error

    async def run(self, plan: SkillPlan, run: AgentRun, *, resume: bool = False) -> PlanExecutionOutcome:
        if (
            run.planning_contract_version
            is AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1
            and not universal_standard_execution_allowed(
                run_contract=run.execution_contract_version,
                plan_contract=plan.execution_contract_version,
            )
        ):
            raise PlanExecutionConflict("universal_execution_not_available")
        if resume:
            persisted_plan = self.repository.get_skill_plan(plan.id)
            persisted_run = self.repository.get_agent_run(run.id)
            if (
                persisted_plan is None
                or persisted_run is None
                or persisted_plan.run_id != persisted_run.id
                or persisted_plan.status != SkillPlanStatus.RUNNING
                or persisted_run.status != AgentRunStatus.RUNNING
            ):
                raise PlanExecutionConflict("plan_resume_conflict")
            plan = persisted_plan
            run = persisted_run
            self.repository.append_agent_run_event(run.id, "plan_execution_resumed", {"plan_id": plan.id})
        else:
            with self.admission.permit():
                claimed = self.repository.claim_skill_plan_for_execution(plan.id, run.id)
            if claimed is None:
                raise PlanExecutionConflict("plan_execution_claim_conflict")
            plan = claimed
            self.repository.append_agent_run_event(run.id, "plan_execution_started", {"plan_id": plan.id})
        try:
            while True:
                current_run = self.repository.get_agent_run(run.id)
                current_plan = self.repository.get_skill_plan(plan.id)
                if current_run is None or current_plan is None:
                    raise RuntimeError("Agent run disappeared during plan execution")
                run = current_run
                plan = current_plan
                if run.status == AgentRunStatus.CANCELLED:
                    raise asyncio.CancelledError
                if run.status != AgentRunStatus.RUNNING or plan.status != SkillPlanStatus.RUNNING:
                    raise RuntimeError("plan_execution_state_changed")
                result_rows = self.repository.list_skill_node_results(plan.id)
                latest_results = {result.node_id: result for result in result_rows}
                by_id = {node.id: node for node in plan.nodes}

                changed = False
                for node in list(plan.nodes):
                    if node.status != SkillPlanNodeStatus.PENDING:
                        continue
                    dependency_states = [by_id[dependency].status for dependency in node.depends_on]
                    if any(state in {SkillPlanNodeStatus.FAILED, SkillPlanNodeStatus.SKIPPED} for state in dependency_states):
                        skipped = node.model_copy(
                            update={
                                "status": SkillPlanNodeStatus.SKIPPED,
                                "error_code": "dependency_failed",
                                "completed_at": now_utc(),
                            }
                        )
                        self._transition_node(
                            plan=plan,
                            run=run,
                            node=skipped,
                            expected_statuses={SkillPlanNodeStatus.PENDING},
                            event_type="node_skipped",
                            event_payload={
                                "plan_id": plan.id,
                                "node_id": node.id,
                                "error_code": "dependency_failed",
                            },
                        )
                        changed = True
                if changed:
                    # A skipped node can make another dependency chain skippable.
                    # Reload the persisted plan and propagate one layer at a time.
                    continue

                ready = [node for node in plan.nodes if node.status == SkillPlanNodeStatus.READY][:3]
                if not ready:
                    pending = [node for node in plan.nodes if node.status == SkillPlanNodeStatus.PENDING]
                    if not pending:
                        terminal_statuses = {
                            SkillPlanNodeStatus.COMPLETED,
                            SkillPlanNodeStatus.FAILED,
                            SkillPlanNodeStatus.SKIPPED,
                            SkillPlanNodeStatus.CANCELLED,
                        }
                        if any(node.status not in terminal_statuses for node in plan.nodes):
                            raise RuntimeError("dag_has_nonterminal_node")
                        break
                    ready = [
                        node
                        for node in pending
                        if all(by_id[dependency].status == SkillPlanNodeStatus.COMPLETED for dependency in node.depends_on)
                    ][:3]
                    if not ready:
                        raise RuntimeError("dag_has_no_runnable_node")
                    marked_ready: list[SkillPlanNode] = []
                    for node in ready:
                        marked_ready.append(
                            self._transition_node(
                                plan=plan,
                                run=run,
                                node=node.model_copy(update={"status": SkillPlanNodeStatus.READY}),
                                expected_statuses={SkillPlanNodeStatus.PENDING},
                                event_type="node_ready",
                                event_payload={"plan_id": plan.id, "node_id": node.id},
                            )
                        )
                    ready = marked_ready

                outcomes: dict[str, tuple[SkillPlanNode, NodeExecutionOutcome | None, Exception | None]] = {}

                async def execute(
                    node: SkillPlanNode,
                    *,
                    current_plan: SkillPlan = plan,
                    current_run: AgentRun = run,
                    current_results: tuple[SkillNodeResult, ...] = tuple(latest_results.values()),
                    result_sink: dict[
                        str,
                        tuple[SkillPlanNode, NodeExecutionOutcome | None, Exception | None],
                    ] = outcomes,
                ) -> None:
                    result_sink[node.id] = await self._execute_one(
                        current_plan,
                        current_run,
                        node,
                        list(current_results),
                    )

                async with asyncio.TaskGroup() as group:
                    for node in ready:
                        group.create_task(execute(node))

                paused: list[tuple[SkillPlanNode, NodePause]] = []
                for node in ready:
                    claimed, outcome, error = outcomes[node.id]
                    if error is not None:
                        if claimed.status != SkillPlanNodeStatus.RUNNING:
                            raise error
                        external_outcome_unknown = (
                            claimed.side_effect
                            in {SkillSideEffect.LOCAL_WRITE, SkillSideEffect.EXTERNAL_WRITE}
                            and self.repository.runtime_tool_node_has_unknown_non_read(
                                run.id,
                                claimed.id,
                            )
                        )
                        error_code = (
                            "external_outcome_unknown"
                            if external_outcome_unknown
                            else _error_code(error)
                        )
                        retryable = (
                            claimed.side_effect in {SkillSideEffect.READ, SkillSideEffect.DRAFT}
                            and claimed.attempt < 2
                            and _transient(error)
                        )
                        transitioned = claimed.model_copy(
                            update={
                                "status": SkillPlanNodeStatus.PENDING if retryable else SkillPlanNodeStatus.FAILED,
                                "error_code": error_code,
                                "completed_at": None if retryable else now_utc(),
                            }
                        )
                        self._transition_node(
                            plan=plan,
                            run=run,
                            node=transitioned,
                            expected_statuses={SkillPlanNodeStatus.RUNNING},
                            event_type="node_retry_scheduled" if retryable else "node_failed",
                            event_payload={
                                "plan_id": plan.id,
                                "node_id": claimed.id,
                                "attempt": claimed.attempt,
                                "error_code": error_code,
                                "error_detail": _error_detail(error),
                            },
                        )
                        continue
                    if outcome is None:
                        continue
                    if outcome.pause is not None:
                        paused.append((claimed, outcome.pause))
                        continue
                    if outcome.result is None:
                        failed = claimed.model_copy(
                            update={
                                "status": SkillPlanNodeStatus.FAILED,
                                "error_code": "missing_node_result",
                                "completed_at": now_utc(),
                            }
                        )
                        self._transition_node(
                            plan=plan,
                            run=run,
                            node=failed,
                            expected_statuses={SkillPlanNodeStatus.RUNNING},
                            event_type="node_failed",
                            event_payload={
                                "plan_id": plan.id,
                                "node_id": claimed.id,
                                "attempt": claimed.attempt,
                                "error_code": "missing_node_result",
                            },
                        )
                        continue
                    completed = claimed.model_copy(
                        update={
                            "status": SkillPlanNodeStatus.COMPLETED,
                            "completed_at": now_utc(),
                            "error_code": None,
                        }
                    )
                    self._transition_node(
                        plan=plan,
                        run=run,
                        node=completed,
                        expected_statuses={SkillPlanNodeStatus.RUNNING},
                        event_type="node_completed",
                        event_payload={
                            "plan_id": plan.id,
                            "node_id": claimed.id,
                            "attempt": claimed.attempt,
                            "confidence": outcome.result.confidence,
                        },
                        result=outcome.result,
                    )
                if paused:
                    if len(paused) > 1:
                        for extra_node, _pause in paused[1:]:
                            self._transition_node(
                                plan=plan,
                                run=run,
                                node=extra_node.model_copy(
                                    update={
                                        "status": SkillPlanNodeStatus.PENDING,
                                        "attempt": extra_node.attempt - 1,
                                        "error_code": None,
                                        "started_at": None,
                                    }
                                ),
                                expected_statuses={SkillPlanNodeStatus.RUNNING},
                                event_type="node_rescheduled_after_parallel_approval",
                                event_payload={"plan_id": plan.id, "node_id": extra_node.id},
                                expected_attempt=extra_node.attempt,
                            )
                    paused_node, pause = paused[0]
                    plan = self.repository.get_skill_plan(plan.id) or plan
                    return PlanExecutionOutcome(
                        plan=plan,
                        run=run,
                        pause=pause,
                        paused_node_id=paused_node.id,
                    )

            return await self.finalization_strategy.finalize(
                run_id=run.id,
                plan_id=plan.id,
                expected_plan_version=plan.version,
            )
        except asyncio.CancelledError:
            current_plan = self.repository.get_skill_plan(plan.id) or plan
            current_run = self.repository.get_agent_run(run.id) or run
            if current_run.planning_mode is AgentPlanningMode.DEEPSEARCH:
                # Business cancellation is committed before the Runtime task is
                # cancelled. A process/shutdown cancellation has no such durable
                # transition and must remain recoverable; startup recovery will
                # mark any abandoned RUNNING node external_outcome_unknown.
                raise
            if current_run.status != AgentRunStatus.RUNNING:
                raise
            unknown_write = False
            for node in current_plan.nodes:
                if node.status is SkillPlanNodeStatus.RUNNING:
                    node_unknown = (
                        node.side_effect
                        in {SkillSideEffect.LOCAL_WRITE, SkillSideEffect.EXTERNAL_WRITE}
                        and self.repository.runtime_tool_node_has_unknown_non_read(
                            current_run.id,
                            node.id,
                        )
                    )
                    node.status = (
                        SkillPlanNodeStatus.FAILED
                        if node_unknown
                        else SkillPlanNodeStatus.CANCELLED
                    )
                    node.error_code = (
                        "external_outcome_unknown" if node_unknown else None
                    )
                    node.completed_at = now_utc()
                    unknown_write = unknown_write or node_unknown
                elif node.status in {
                    SkillPlanNodeStatus.PENDING,
                    SkillPlanNodeStatus.READY,
                    SkillPlanNodeStatus.WAITING_TOOL_APPROVAL,
                }:
                    node.status = SkillPlanNodeStatus.CANCELLED
                    node.completed_at = now_utc()
            if current_plan.candidate_snapshot is not None or unknown_write:
                partial = False
                if current_plan.candidate_snapshot is not None:
                    from agentmesh.skill_runtime.universal_plan import (
                        persisted_universal_partial_delivery,
                    )

                    synthesis = (
                        SkillSynthesisResult.model_validate(current_plan.synthesis)
                        if current_plan.synthesis is not None
                        else self.repository.get_universal_synthesis_for_plan(current_plan)
                    )
                    partial = persisted_universal_partial_delivery(
                        plan=current_plan,
                        results=self.repository.list_skill_node_results(current_plan.id),
                        synthesis=synthesis,
                        artifact_lookup=self.repository.get_artifact,
                    )
                current_plan.status = SkillPlanStatus.PARTIAL if partial else SkillPlanStatus.FAILED
                current_run.status = AgentRunStatus.PARTIAL if partial else AgentRunStatus.FAILED
                current_run.error_code = (
                    "external_outcome_unknown" if unknown_write else "process_restarted"
                )
                event_type = "run_partially_completed" if partial else "run_failed"
            else:
                current_plan.status = SkillPlanStatus.CANCELLED
                current_run.status = AgentRunStatus.CANCELLED
                current_run.error_code = None
                event_type = "run_cancelled"
            transition = self.repository.finish_skill_plan_and_run(
                plan=current_plan,
                run=current_run,
                expected_plan_statuses={SkillPlanStatus.RUNNING},
                expected_run_statuses={AgentRunStatus.RUNNING},
                events=[
                    (
                        event_type,
                        {
                            "plan_id": current_plan.id,
                            "error_code": current_run.error_code or "cancelled",
                        },
                    )
                ],
            )
            if transition is None:
                raise RuntimeError("plan_cancel_transition_conflict") from None
            raise
