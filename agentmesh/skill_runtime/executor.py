from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from agentmesh.llm import llm_chat_timeout_seconds, research_skill_timeout_seconds
from agentmesh.models import (
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
from agentmesh.skill_runtime.synthesis import render_synthesis
from agentmesh.store import SQLiteStore
from agentmesh.task_routing.completion import evaluate_plan_completion
from agentmesh.tool_runtime.guardrails import redact_sensitive_text


@dataclass(frozen=True, slots=True)
class NodePause:
    sdk_state: dict[str, object]
    interruptions: tuple[dict[str, str], ...]
    grant_snapshot_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NodeExecutionOutcome:
    result: SkillNodeResult | None = None
    pause: NodePause | None = None


@dataclass(frozen=True, slots=True)
class PlanExecutionOutcome:
    plan: SkillPlan
    run: AgentRun
    synthesis: SkillSynthesisResult | None = None
    pause: NodePause | None = None
    paused_node_id: str | None = None
    synthesis_fallback: bool = False


NodeRunner = Callable[[SkillPlan, SkillPlanNode, list[SkillNodeResult]], Awaitable[NodeExecutionOutcome]]
SynthesisRunner = Callable[[SkillPlan, list[SkillNodeResult]], Awaitable[tuple[SkillSynthesisResult, bool]]]


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
    message = str(error)
    safe = all(character.islower() or character.isdigit() or character == "_" for character in message)
    if message and len(message) <= 120 and safe:
        return message
    return type(error).__name__


def _error_detail(error: Exception) -> str:
    return redact_sensitive_text(str(error)).strip()[:500] or type(error).__name__


class BoundedDAGExecutor:
    def __init__(
        self,
        repository: SQLiteStore,
        *,
        node_runner: NodeRunner,
        synthesis_runner: SynthesisRunner,
    ):
        self.repository = repository
        self.node_runner = node_runner
        self.synthesis_runner = synthesis_runner

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
        claimed = self.repository.claim_skill_plan_node(plan.id, node.id)
        if claimed is None:
            return node, None, RuntimeError("node_claim_conflict")
        self._replace_node(plan, claimed)
        upstream = [result for result in results if result.node_id in set(claimed.depends_on)]
        node_timeout = (
            research_skill_timeout_seconds()
            if "web_research" in node.required_tool_names
            else llm_chat_timeout_seconds()
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

                pending = [node for node in plan.nodes if node.status == SkillPlanNodeStatus.PENDING]
                if not pending:
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
                        error_code = _error_code(error)
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

            plan = self.repository.get_skill_plan(plan.id) or plan
            results = self.repository.list_skill_node_results(plan.id)
            provisional_completion = evaluate_plan_completion(plan, results)
            if provisional_completion is not None:
                plan.completion_check = provisional_completion
            completed_nodes = {result.node_id for result in results}
            available_outputs = {
                output
                for node in plan.nodes
                if node.id in completed_nodes
                for output in node.output_contract
            } | {"executive_summary", "summary", "synthesis", *plan.synthesis_output_contract}
            required_results = [node for node in plan.nodes if node.required and node.id in completed_nodes]
            if not required_results or not set(plan.output_contract).issubset(available_outputs):
                plan.status = SkillPlanStatus.FAILED
                run = self.repository.get_agent_run(run.id) or run
                run.status = AgentRunStatus.FAILED
                run.error_code = "output_contract_unsatisfied"
                transition = self.repository.finish_skill_plan_and_run(
                    plan=plan,
                    run=run,
                    expected_plan_statuses={SkillPlanStatus.RUNNING},
                    expected_run_statuses={AgentRunStatus.RUNNING},
                    events=[("run_failed", {"error_code": run.error_code})],
                )
                if transition is None:
                    raise RuntimeError("plan_terminal_transition_conflict")
                plan, run = transition
                return PlanExecutionOutcome(plan=plan, run=run)

            self.repository.append_agent_run_event(run.id, "synthesis_started", {"plan_id": plan.id})
            remaining = 300.0
            if run.deadline_at is not None:
                remaining = max(0.0, (run.deadline_at - now_utc()).total_seconds())
            if remaining <= 0:
                raise TimeoutError("parent_run_deadline_exceeded")
            async with asyncio.timeout(remaining):
                synthesis, fallback = await self.synthesis_runner(plan, results)
            completion_check = evaluate_plan_completion(plan, results, synthesis=synthesis)
            if completion_check is not None:
                plan.completion_check = completion_check
                if not completion_check.completed:
                    completion_gap = "completion_check_partial:" + ",".join(completion_check.gaps)
                    plan.degradation = ";".join(
                        item for item in (plan.degradation, completion_gap) if item
                    )[:1000]
            plan.synthesis = synthesis.model_dump(mode="json")
            degraded = (
                fallback
                or bool(plan.degradation)
                or any(result.degradation for result in results)
                or any(
                    node.status in {SkillPlanNodeStatus.FAILED, SkillPlanNodeStatus.SKIPPED}
                    for node in plan.nodes
                )
            )
            plan.status = SkillPlanStatus.PARTIAL if degraded else SkillPlanStatus.COMPLETED
            run = self.repository.get_agent_run(run.id) or run
            run.status = AgentRunStatus.PARTIAL if degraded else AgentRunStatus.COMPLETED
            run.error_code = None
            run.output_text = render_synthesis(synthesis)
            run.paused_state = None
            event_type = "run_partial" if degraded else "run_completed"
            transition = self.repository.finish_skill_plan_and_run(
                plan=plan,
                run=run,
                expected_plan_statuses={SkillPlanStatus.RUNNING},
                expected_run_statuses={AgentRunStatus.RUNNING},
                events=[
                    ("synthesis_completed", {"plan_id": plan.id, "fallback": fallback}),
                    (event_type, {"plan_id": plan.id, "synthesis_fallback": fallback}),
                ],
            )
            if transition is None:
                raise RuntimeError("plan_terminal_transition_conflict")
            plan, run = transition
            return PlanExecutionOutcome(
                plan=plan,
                run=run,
                synthesis=synthesis,
                synthesis_fallback=fallback,
            )
        except asyncio.CancelledError:
            for node in plan.nodes:
                if node.status not in {
                    SkillPlanNodeStatus.COMPLETED,
                    SkillPlanNodeStatus.FAILED,
                    SkillPlanNodeStatus.SKIPPED,
                }:
                    node.status = SkillPlanNodeStatus.CANCELLED
                    node.completed_at = now_utc()
            plan.status = SkillPlanStatus.CANCELLED
            current_run = self.repository.get_agent_run(run.id) or run
            if current_run.status == AgentRunStatus.RUNNING:
                current_run.status = AgentRunStatus.CANCELLED
                current_run.error_code = None
                transition = self.repository.finish_skill_plan_and_run(
                    plan=plan,
                    run=current_run,
                    expected_plan_statuses={SkillPlanStatus.RUNNING},
                    expected_run_statuses={AgentRunStatus.RUNNING},
                    events=[("run_cancelled", {"plan_id": plan.id})],
                )
                if transition is None:
                    raise RuntimeError("plan_cancel_transition_conflict") from None
            raise
