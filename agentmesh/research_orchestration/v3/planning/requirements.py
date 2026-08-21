from __future__ import annotations

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.ports import ClockPort, IdGeneratorPort
from agentmesh.research_orchestration.v3.requirement import RequirementVersionV3, ResearchTaskV3
from agentmesh.research_orchestration.v3.planning.models import (
    PlanningModelCallReceiptV3,
    RequirementPlanningResultV3,
    RequirementProposalRequestV3,
    RequirementProposalV3,
    RequirementStructuredProposalPort,
)


class RequirementPlanningError(ValueError):
    pass


def requirement_context_manifest_hash(request: RequirementProposalRequestV3) -> str:
    return canonical_json_v3_sha256(
        {
            "run_id": request.run_id,
            "user_request": request.user_request,
            "previous_requirement_id": request.previous.id if request.previous is not None else None,
            "previous_content_hash": request.previous.content_hash if request.previous is not None else None,
        }
    )


class CompetitiveTextRequirementPlanner:
    """Validates a structured proposal and creates an immutable Requirement version."""

    def __init__(
        self,
        *,
        proposal_port: RequirementStructuredProposalPort,
        id_generator: IdGeneratorPort,
        clock: ClockPort,
    ) -> None:
        self._proposal_port = proposal_port
        self._id_generator = id_generator
        self._clock = clock

    async def _propose(
        self,
        *,
        run_id: str,
        user_request: str,
        previous: RequirementVersionV3 | None,
    ) -> RequirementProposalV3:
        if previous is not None and previous.run_id != run_id:
            raise RequirementPlanningError("previous_requirement_run_mismatch")
        try:
            request = RequirementProposalRequestV3(
                run_id=run_id,
                user_request=user_request.strip(),
                previous=previous,
            )
        except ValueError as exc:
            raise RequirementPlanningError("invalid_requirement_request") from exc
        proposal = await self._proposal_port.propose(request)
        if proposal.receipt.run_id != run_id:
            raise RequirementPlanningError("requirement_receipt_run_mismatch")
        if proposal.receipt.context_manifest_hash != requirement_context_manifest_hash(request):
            raise RequirementPlanningError("requirement_receipt_context_mismatch")
        task = proposal.task
        if task.planning_blocked and not task.clarification_questions:
            raise RequirementPlanningError("blocking_requirement_requires_clarification")
        if not task.planning_blocked and task.clarification_questions:
            raise RequirementPlanningError("resolved_requirement_contains_stale_clarification")
        return proposal

    async def refine(
        self,
        *,
        run_id: str,
        user_request: str,
        previous: RequirementVersionV3 | None,
    ) -> ResearchTaskV3:
        proposal = await self._propose(run_id=run_id, user_request=user_request, previous=previous)
        return proposal.task

    async def refine_version(
        self,
        *,
        run_id: str,
        user_request: str,
        previous: RequirementVersionV3 | None,
    ) -> RequirementPlanningResultV3:
        proposal = await self._propose(run_id=run_id, user_request=user_request, previous=previous)
        version = 1 if previous is None else previous.version + 1
        requirement_id = self._id_generator.new("requirement")
        if previous is not None and requirement_id == previous.id:
            raise RequirementPlanningError("requirement_id_reused")
        requirement = RequirementVersionV3(
            id=requirement_id,
            run_id=run_id,
            version=version,
            schema_version="research-task-v3",
            task_type="competitive_research",
            payload=proposal.task,
            content_hash=canonical_json_v3_sha256(proposal.task),
            created_at=self._clock.now(),
        )
        return RequirementPlanningResultV3(requirement=requirement, receipt=proposal.receipt)


class DeterministicRequirementProposalFake:
    """Scripted structured-output fake; it never imports or calls a Provider SDK."""

    def __init__(self, *tasks: ResearchTaskV3) -> None:
        if not tasks:
            raise ValueError("the deterministic Requirement fake needs at least one task")
        self._tasks = tasks
        self.calls: list[RequirementProposalRequestV3] = []

    async def propose(self, request: RequirementProposalRequestV3) -> RequirementProposalV3:
        index = len(self.calls)
        if index >= len(self._tasks):
            raise RuntimeError("deterministic Requirement proposals exhausted")
        self.calls.append(request)
        task = self._tasks[index]
        call_hash = canonical_json_v3_sha256(
            {
                "stage": "requirement_refinement",
                "call_index": index,
                "context": requirement_context_manifest_hash(request),
                "output": canonical_json_v3_sha256(task),
            }
        )
        receipt = PlanningModelCallReceiptV3(
            id=f"receipt_requirement_{call_hash[:24]}",
            run_id=request.run_id,
            stage="requirement_refinement",
            model_name="deterministic-requirement-fake",
            model_version="1",
            prompt_hash=canonical_json_v3_sha256(
                {"stage": "requirement_refinement", "schema": "research-task-v3"}
            ),
            trace_id=f"trace_requirement_{call_hash[24:48]}",
            context_manifest_hash=requirement_context_manifest_hash(request),
            output_hash=canonical_json_v3_sha256(task),
        )
        return RequirementProposalV3(task=task, receipt=receipt)
