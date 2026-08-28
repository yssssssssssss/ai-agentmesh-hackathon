from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    SkillNodeResult,
    SkillPlan,
    SkillPlanNodeStatus,
    SkillPlanStatus,
    SkillSynthesisResult,
    now_utc,
)
from agentmesh.skill_runtime.synthesis import render_synthesis
from agentmesh.store import SQLiteStore
from agentmesh.task_routing.completion import evaluate_plan_completion


@dataclass(frozen=True, slots=True)
class NodePause:
    sdk_state: dict[str, object]
    interruptions: tuple[dict[str, str], ...]
    grant_snapshot_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlanExecutionOutcome:
    plan: SkillPlan
    run: AgentRun
    synthesis: SkillSynthesisResult | None = None
    pause: NodePause | None = None
    paused_node_id: str | None = None
    synthesis_fallback: bool = False


SynthesisRunner = Callable[[SkillPlan, list[SkillNodeResult]], Awaitable[tuple[SkillSynthesisResult, bool]]]


class PlanFinalizationStrategy(Protocol):
    async def finalize(
        self,
        *,
        run_id: str,
        plan_id: str,
        expected_plan_version: int,
    ) -> PlanExecutionOutcome: ...


class StandardPlanFinalizer:
    """Finalize an ordinary Skill Plan without exposing DeepSearch semantics."""

    def __init__(self, repository: SQLiteStore, *, synthesis_runner: SynthesisRunner) -> None:
        self.repository = repository
        self.synthesis_runner = synthesis_runner

    def _load_active_plan(
        self,
        *,
        run_id: str,
        plan_id: str,
        expected_plan_version: int,
    ) -> tuple[SkillPlan, AgentRun]:
        plan = self.repository.get_skill_plan(plan_id)
        run = self.repository.get_agent_run(run_id)
        if (
            plan is None
            or run is None
            or plan.run_id != run.id
            or plan.version != expected_plan_version
            or plan.status is not SkillPlanStatus.RUNNING
            or run.status is not AgentRunStatus.RUNNING
        ):
            raise RuntimeError("plan_terminal_transition_conflict")
        if (
            plan.planning_mode is AgentPlanningMode.DEEPSEARCH
            or run.planning_mode is AgentPlanningMode.DEEPSEARCH
        ):
            raise RuntimeError("deepsearch_finalization_strategy_required")
        terminal_statuses = {
            SkillPlanNodeStatus.COMPLETED,
            SkillPlanNodeStatus.FAILED,
            SkillPlanNodeStatus.SKIPPED,
            SkillPlanNodeStatus.CANCELLED,
        }
        if any(node.status not in terminal_statuses for node in plan.nodes):
            raise RuntimeError("plan_nodes_not_terminal")
        return plan, run

    async def finalize(
        self,
        *,
        run_id: str,
        plan_id: str,
        expected_plan_version: int,
    ) -> PlanExecutionOutcome:
        plan, run = self._load_active_plan(
            run_id=run_id,
            plan_id=plan_id,
            expected_plan_version=expected_plan_version,
        )
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
            causes = [
                {
                    "node_id": node.id,
                    "error_code": node.error_code,
                    "attempt": node.attempt,
                }
                for node in plan.nodes
                if node.status is SkillPlanNodeStatus.FAILED and node.error_code
            ]
            missing_outputs = sorted(set(plan.output_contract) - available_outputs)
            plan.status = SkillPlanStatus.FAILED
            run = self.repository.get_agent_run(run.id) or run
            run.status = AgentRunStatus.FAILED
            run.error_code = "output_contract_unsatisfied"
            transition = self.repository.finish_skill_plan_and_run(
                plan=plan,
                run=run,
                expected_plan_statuses={SkillPlanStatus.RUNNING},
                expected_run_statuses={AgentRunStatus.RUNNING},
                events=[
                    (
                        "run_failed",
                        {
                            "error_code": run.error_code,
                            "causes": causes,
                            "missing_outputs": missing_outputs,
                        },
                    )
                ],
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
