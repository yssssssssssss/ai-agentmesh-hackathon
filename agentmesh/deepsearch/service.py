"""DeepSearch Requirement lifecycle orchestration.

This module owns the state machine around requirement refinement.  It never
constructs or invokes Tools; planning begins only after a complete Requirement
has been committed.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timedelta

from pydantic import ValidationError

from agentmesh.deepsearch.contracts import (
    DeepSearchClarifyRequestV1,
    DeepSearchPlanViewV1,
    DeepSearchRetryDisposition,
    DeepSearchReviewViewV1,
    DeepSearchStateResponse,
    ProblemGraphV1,
    RequirementPayloadV1,
    RequirementRefinementDraftV1,
    RequirementVersionV1,
    clarification_request_hash,
    materialize_requirement_payload,
    normalize_clarification_answers,
    normalize_clarification_request_answers,
    requirement_content_hash,
    validate_problem_graph_against_requirement,
)
from agentmesh.deepsearch.planning import (
    DeepSearchPlanningPipeline,
    RequirementRefiner,
    plan_content_hash,
)
from agentmesh.models import (
    AgentPlanningContractVersion,
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    SkillPlan,
    SkillPlanStatus,
    new_id,
    now_utc,
)
from agentmesh.skill_runtime.quiesce import OrchestrationQuiesceController
from agentmesh.store import ResearchStoreConflict, SQLiteStore


class DeepSearchRequirementInvalid(ValueError):
    """The submitted answers do not match the frozen Requirement questions."""


class DeepSearchRequirementIntegrityError(RuntimeError):
    """A persisted or Refiner-produced Requirement violated its strict contract."""


class DeepSearchExecutionUnavailable(RuntimeError):
    """The server cannot advance a new DeepSearch operation right now."""


_NO_RETRY_STATUSES = {
    AgentRunStatus.COMPLETED,
    AgentRunStatus.CANCELLED,
    AgentRunStatus.REJECTED,
}
_NO_RETRY_ERRORS = {
    "deepsearch_interaction_expired",
    "deepsearch_run_expired",
    "permission_denied",
    "external_outcome_unknown",
    "deepsearch_tool_policy_violation",
    "deepsearch_evidence_integrity_failed",
    "deepsearch_recovery_state_invalid",
}
_RETRY_RUN_ERRORS = {
    "deepsearch_planning_transient",
    "deepsearch_execution_transient",
    "deepsearch_report_persistence_failed",
    "deepsearch_recovery_exhausted",
}
_REVISE_GOAL_ERRORS = {
    "deepsearch_clarification_unresolved",
    "deepsearch_planning_failed",
    "deepsearch_budget_exhausted",
    "deepsearch_delivery_unavailable",
    "deepsearch_required_coverage_incomplete",
    "deepsearch_review_not_passed",
}


def deepsearch_retry_disposition(run: AgentRun) -> DeepSearchRetryDisposition:
    if run.status in _NO_RETRY_STATUSES or run.error_code in _NO_RETRY_ERRORS:
        return DeepSearchRetryDisposition.NONE
    if run.error_code in _RETRY_RUN_ERRORS:
        return DeepSearchRetryDisposition.RETRY_RUN
    if run.error_code in _REVISE_GOAL_ERRORS:
        return DeepSearchRetryDisposition.REVISE_GOAL
    return DeepSearchRetryDisposition.NONE


def _verified_problem_graph(
    requirement: RequirementVersionV1 | None,
    plan: SkillPlan | None,
) -> ProblemGraphV1 | None:
    if plan is None:
        return None
    if (
        requirement is None
        or plan.planning_mode is not AgentPlanningMode.DEEPSEARCH
        or plan.requirement_version_id != requirement.id
        or plan.requirement_content_hash != requirement.content_hash
    ):
        raise ValueError("DeepSearch Plan Requirement lineage is invalid")
    graph = ProblemGraphV1.model_validate(plan.problem_graph)
    validate_problem_graph_against_requirement(graph=graph, requirement=requirement)
    if plan.problem_graph_hash != graph.content_hash or plan.plan_content_hash != plan_content_hash(plan):
        raise ValueError("DeepSearch Plan hash lineage is invalid")
    return graph


class DeepSearchPlanningService:
    """Coordinates pure Refiner calls with append-only Requirement CAS writes."""

    def __init__(
        self,
        repository: SQLiteStore,
        refiner: RequirementRefiner,
        *,
        clock: Callable[[], datetime] = now_utc,
        can_refine: Callable[[], bool] = lambda: True,
        planning_pipeline: DeepSearchPlanningPipeline | None = None,
        admission: OrchestrationQuiesceController | None = None,
    ) -> None:
        self._repository = repository
        self._refiner = refiner
        self._clock = clock
        self._can_refine = can_refine
        self._planning_pipeline = planning_pipeline
        self._admission = admission or OrchestrationQuiesceController()

    def get_state(self, run: AgentRun) -> DeepSearchStateResponse:
        snapshot = self._repository.get_deepsearch_state_snapshot(run.id)
        if snapshot is None:
            raise LookupError("DeepSearch Run not found")
        if (
            snapshot.run.user_id != run.user_id
            or snapshot.run.workspace_id != run.workspace_id
            or snapshot.run.project_id != run.project_id
        ):
            raise DeepSearchRequirementIntegrityError("DeepSearch Run ownership changed")
        run = snapshot.run
        planning_skeleton = bool(
            snapshot.plan is not None
            and run.status is AgentRunStatus.PLANNING
            and run.planning_contract_version
            is AgentPlanningContractVersion.DEEPSEARCH_FROZEN_V2
            and snapshot.plan.status is SkillPlanStatus.PLANNING
            and snapshot.plan.candidate_snapshot is not None
            and not snapshot.plan.nodes
            and run.plan_id == snapshot.plan.id
        )
        if (
            not planning_skeleton
            and (
                (snapshot.plan is None) != (run.plan_id is None)
                or (snapshot.plan is not None and snapshot.plan.id != run.plan_id)
            )
        ):
            raise DeepSearchRequirementIntegrityError(
                "DeepSearch Run and Plan identity do not match"
            )
        try:
            requirement = (
                RequirementVersionV1.model_validate(snapshot.requirement)
                if snapshot.requirement is not None
                else None
            )
            if planning_skeleton:
                assert snapshot.plan is not None
                if requirement is None:
                    raise ValueError("DeepSearch planning skeleton requires Requirement")
                problem_graph = ProblemGraphV1.model_validate(snapshot.plan.problem_graph)
                validate_problem_graph_against_requirement(
                    graph=problem_graph,
                    requirement=requirement,
                )
                if snapshot.plan.problem_graph_hash != problem_graph.content_hash:
                    raise ValueError("DeepSearch planning skeleton graph hash is invalid")
            else:
                problem_graph = _verified_problem_graph(requirement, snapshot.plan)
        except ValidationError as error:
            raise DeepSearchRequirementIntegrityError(
                "DeepSearch Requirement failed integrity verification"
            ) from error
        except (TypeError, ValueError) as error:
            raise DeepSearchRequirementIntegrityError(
                "DeepSearch Plan failed integrity verification"
            ) from error
        if run.status is AgentRunStatus.WAITING_CLARIFICATION and (
            requirement is None or not requirement.payload.clarification_questions
        ):
            raise DeepSearchRequirementIntegrityError(
                "waiting_clarification requires an active question set"
            )
        if run.status is AgentRunStatus.WAITING_CLARIFICATION and (
            run.interaction_expires_at is None or run.deadline_at is not None
        ):
            raise DeepSearchRequirementIntegrityError(
                "waiting_clarification requires an interaction deadline only"
            )
        if (
            requirement is not None
            and requirement.payload.clarification_questions
            and run.status
            in {
                AgentRunStatus.CREATED,
                AgentRunStatus.PLANNING,
                AgentRunStatus.RUNNING,
                AgentRunStatus.WAITING_PLAN_APPROVAL,
                AgentRunStatus.WAITING_APPROVAL,
            }
        ):
            raise DeepSearchRequirementIntegrityError(
                "active clarification questions require waiting_clarification"
            )
        return DeepSearchStateResponse(
            run=run,
            active_requirement=requirement,
            problem_graph=problem_graph,
            plan=(
                DeepSearchPlanViewV1.from_plan(snapshot.plan)
                if snapshot.plan is not None and not planning_skeleton
                else None
            ),
            evidence_coverage=(
                snapshot.plan.evidence_coverage
                if snapshot.plan is not None and not planning_skeleton
                else None
            ),
            report_review=(
                DeepSearchReviewViewV1.from_outcome(snapshot.plan.review_outcomes[-1])
                if snapshot.plan is not None
                and not planning_skeleton
                and snapshot.plan.review_outcomes
                else None
            ),
            retry_disposition=deepsearch_retry_disposition(run),
        )

    async def refine_initial(self, run: AgentRun) -> DeepSearchStateResponse:
        """Create Requirement v1 for a newly claimed DeepSearch Run.

        The production runtime intentionally does not call this until a budgeted
        Refiner and Slice-3 planning continuation are installed.
        """

        request_key = run.client_turn_id
        request_hash = run.create_request_hash
        if not request_key or not request_hash:
            raise DeepSearchRequirementIntegrityError("DeepSearch Run creation identity is incomplete")
        checked_at = self._clock()
        with self._admission.permit():
            prepared = self._repository.prepare_deepsearch_requirement_append(
                run_id=run.id,
                user_id=run.user_id,
                request_key=request_key,
                request_hash=request_hash,
                expected_requirement_version=None,
                expected_run_status=AgentRunStatus.PLANNING,
                checked_at=checked_at,
            )
        if prepared is None:
            raise LookupError("DeepSearch Run not found")
        if prepared.replayed:
            return await self._continue_planning_if_ready(
                self.get_state(self._current_run(run.id))
            )
        if not self._can_refine():
            raise DeepSearchExecutionUnavailable("DeepSearch execution mode is unavailable")

        draft = await self._refine(previous=None, user_request=prepared.run.input_text, answers={})
        payload = materialize_requirement_payload(
            previous=None,
            draft=draft,
            answers={},
            target_version=1,
        )
        return await self._continue_planning_if_ready(
            self._commit_requirement(
                run=prepared.run,
                previous=None,
                payload=payload,
                request_key=request_key,
                request_hash=request_hash,
                checked_at=self._clock(),
            )
        )

    async def clarify(
        self,
        *,
        run: AgentRun,
        request: DeepSearchClarifyRequestV1,
    ) -> DeepSearchStateResponse:
        try:
            identity_answers = normalize_clarification_request_answers(request.answers)
            request_hash = clarification_request_hash(
                run_id=run.id,
                expected_requirement_version=request.expected_requirement_version,
                normalized_answers=identity_answers,
            )
        except ValueError as error:
            raise DeepSearchRequirementInvalid(str(error)) from error
        with self._admission.permit():
            prepared = self._repository.prepare_deepsearch_requirement_append(
                run_id=run.id,
                user_id=run.user_id,
                request_key=request.client_turn_id,
                request_hash=request_hash,
                expected_requirement_version=request.expected_requirement_version,
                expected_run_status=AgentRunStatus.WAITING_CLARIFICATION,
                checked_at=self._clock(),
            )
        if prepared is None:
            raise LookupError("DeepSearch Run not found")
        if prepared.replayed:
            return await self._continue_planning_if_ready(
                self.get_state(self._current_run(run.id))
            )
        if not self._can_refine():
            raise DeepSearchExecutionUnavailable("DeepSearch execution mode is unavailable")
        if prepared.requirement is None:
            raise DeepSearchRequirementIntegrityError("DeepSearch Run has no active Requirement")
        try:
            previous = RequirementVersionV1.model_validate(prepared.requirement)
            answers = normalize_clarification_answers(
                questions=previous.payload.clarification_questions,
                answers=request.answers,
            )
        except (TypeError, ValueError) as error:
            raise DeepSearchRequirementInvalid(str(error)) from error

        draft = await self._refine(
            previous=previous,
            user_request=prepared.run.input_text,
            answers=answers,
        )
        try:
            payload = materialize_requirement_payload(
                previous=previous,
                draft=draft,
                answers=answers,
                target_version=previous.version + 1,
            )
        except (TypeError, ValueError) as error:
            raise DeepSearchRequirementIntegrityError(
                "Requirement Refiner returned an invalid state transition"
            ) from error
        return await self._continue_planning_if_ready(
            self._commit_requirement(
                run=prepared.run,
                previous=previous,
                payload=payload,
                request_key=request.client_turn_id,
                request_hash=request_hash,
                checked_at=self._clock(),
            )
        )

    async def resume_planning(self, run: AgentRun) -> DeepSearchStateResponse:
        """Resume side-effect-free planning from the persisted Requirement snapshot."""

        state = self.get_state(run)
        if state.run.status is not AgentRunStatus.PLANNING:
            return state
        if state.active_requirement is None:
            raise DeepSearchRequirementIntegrityError(
                "planning requires an active DeepSearch Requirement"
            )
        return await self._continue_planning_if_ready(state)

    async def _refine(
        self,
        *,
        previous: RequirementVersionV1 | None,
        user_request: str,
        answers: dict[str, str | list[str]],
    ) -> RequirementRefinementDraftV1:
        try:
            result = await self._refiner.refine(
                previous=previous.model_copy(deep=True) if previous is not None else None,
                user_request=user_request,
                answers=deepcopy(answers),
            )
            return RequirementRefinementDraftV1.model_validate(result)
        except (TypeError, ValueError, ValidationError) as error:
            raise DeepSearchRequirementIntegrityError(
                "Requirement Refiner returned an invalid payload"
            ) from error

    def _commit_requirement(
        self,
        *,
        run: AgentRun,
        previous: RequirementVersionV1 | None,
        payload: RequirementPayloadV1,
        request_key: str,
        request_hash: str,
        checked_at: datetime,
    ) -> DeepSearchStateResponse:
        version = 1 if previous is None else previous.version + 1
        blocking_count = sum(1 for ambiguity in payload.ambiguities if ambiguity.blocking)
        exhausted = blocking_count > 0 and not payload.clarification_questions
        if exhausted:
            next_status = AgentRunStatus.FAILED
            error_code = "deepsearch_clarification_unresolved"
        elif payload.clarification_questions:
            next_status = AgentRunStatus.WAITING_CLARIFICATION
            error_code = None
        else:
            next_status = AgentRunStatus.PLANNING
            error_code = None

        requirement = RequirementVersionV1(
            id=new_id("requirement"),
            run_id=run.id,
            version=version,
            request_key=request_key,
            request_hash=request_hash,
            content_hash=requirement_content_hash(payload),
            derived_from_requirement_version_id=previous.id if previous is not None else None,
            payload=payload,
            created_at=checked_at,
        )
        events: list[tuple[str, dict[str, object]]] = []
        if previous is None:
            events.append(
                (
                    "deepsearch_requirement_created",
                    {
                        "requirement_version_id": requirement.id,
                        "requirement_version": requirement.version,
                        "content_hash": requirement.content_hash,
                    },
                )
            )
        else:
            events.append(
                (
                    "deepsearch_clarification_answered",
                    {
                        "requirement_version_id": requirement.id,
                        "requirement_version": requirement.version,
                        "clarification_round": previous.payload.clarification_round,
                        "answer_count": len(payload.clarification_history[-1].answers),
                        "content_hash": requirement.content_hash,
                    },
                )
            )
        if payload.clarification_questions:
            events.append(
                (
                    "deepsearch_clarification_requested",
                    {
                        "requirement_version_id": requirement.id,
                        "requirement_version": requirement.version,
                        "clarification_round": payload.clarification_round,
                        "question_count": len(payload.clarification_questions),
                        "content_hash": requirement.content_hash,
                    },
                )
            )
        elif exhausted:
            events.append(("run_failed", {"error_code": error_code}))

        interaction_expires_at = (
            checked_at + timedelta(hours=24)
            if next_status is AgentRunStatus.WAITING_CLARIFICATION
            else None
        )
        with self._admission.permit():
            result = self._repository.append_deepsearch_requirement_and_transition(
                run_id=run.id,
                user_id=run.user_id,
                requirement=requirement.model_dump(mode="json"),
                expected_requirement_version=previous.version if previous is not None else None,
                expected_run_status=run.status,
                next_run_status=next_status,
                interaction_expires_at=interaction_expires_at,
                error_code=error_code,
                events=events,
                checked_at=checked_at,
            )
        if result is None:
            raise LookupError("DeepSearch Run not found")
        if result.replayed:
            return self.get_state(self._current_run(run.id))
        committed_requirement = RequirementVersionV1.model_validate(result.requirement)
        return DeepSearchStateResponse(
            run=result.run,
            active_requirement=committed_requirement,
            retry_disposition=deepsearch_retry_disposition(result.run),
        )

    async def _continue_planning_if_ready(
        self,
        state: DeepSearchStateResponse,
    ) -> DeepSearchStateResponse:
        requirement = state.active_requirement
        if (
            self._planning_pipeline is None
            or state.plan is not None
            or state.run.status is not AgentRunStatus.PLANNING
            or requirement is None
            or requirement.payload.clarification_questions
            or any(ambiguity.blocking for ambiguity in requirement.payload.ambiguities)
        ):
            return state
        if not self._can_refine():
            raise DeepSearchExecutionUnavailable("DeepSearch execution mode is unavailable")
        user = self._repository.get_user(state.run.user_id)
        if (
            user is None
            or user.workspace_id != state.run.workspace_id
            or user.default_project_id != state.run.project_id
        ):
            raise DeepSearchRequirementIntegrityError("DeepSearch Run owner is invalid")

        created_at = self._clock()
        plan, snapshot = await self._planning_pipeline.create_plan(
            run=state.run,
            requirement=requirement,
            user=user,
            created_at=created_at,
        )
        try:
            with self._admission.permit():
                if not self._can_refine():
                    raise DeepSearchExecutionUnavailable(
                        "DeepSearch execution mode is unavailable"
                    )
                committed = self._repository.save_deepsearch_plan_and_transition(
                    run_id=state.run.id,
                    user_id=state.run.user_id,
                    expected_requirement_version=requirement.version,
                    plan=plan,
                    plan_snapshot=snapshot,
                    checked_at=created_at,
                )
        except ResearchStoreConflict:
            current = self.get_state(self._current_run(state.run.id))
            if (
                current.plan is not None
                and current.run.status is AgentRunStatus.WAITING_PLAN_APPROVAL
            ):
                return current
            raise
        if committed is None:
            raise LookupError("DeepSearch Run not found")
        committed_plan, committed_run, _committed_snapshot = committed
        return DeepSearchStateResponse(
            run=committed_run,
            active_requirement=requirement,
            problem_graph=_verified_problem_graph(requirement, committed_plan),
            plan=DeepSearchPlanViewV1.from_plan(committed_plan),
            retry_disposition=deepsearch_retry_disposition(committed_run),
        )

    def _current_run(self, run_id: str) -> AgentRun:
        run = self._repository.get_agent_run(run_id)
        if run is None:
            raise LookupError("DeepSearch Run not found")
        return run
