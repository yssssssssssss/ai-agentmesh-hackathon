from __future__ import annotations

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.catalog import CompetitiveTextCatalog
from agentmesh.research_orchestration.v3.planning.models import (
    PlanningArtifactPort,
    PlanningModelCallReceiptV3,
    ProblemGraphPlanningResultV3,
    ProblemGraphProposalV3,
    ProblemGraphStructuredProposalPort,
)
from agentmesh.research_orchestration.v3.planning.validation import (
    competitive_text_evidence_requirements,
    validate_competitive_problem_graph,
)
from agentmesh.research_orchestration.v3.problem_graph import (
    ProblemGraphProvenanceV1,
    ProblemGraphV1,
    ProblemQuestionV1,
)
from agentmesh.research_orchestration.v3.requirement import RequirementVersionV3


class ProblemGraphPlanningError(ValueError):
    pass


def problem_graph_context_manifest_hash(
    requirement: RequirementVersionV3,
    catalog: CompetitiveTextCatalog,
) -> str:
    return canonical_json_v3_sha256(
        {
            "run_id": requirement.run_id,
            "requirement_version_id": requirement.id,
            "requirement_content_hash": requirement.content_hash,
            "catalog_id": catalog.catalog_id,
            "catalog_hash": catalog.catalog_hash,
        }
    )


class CompetitiveTextProblemGraphPlanner:
    """Accepts only receipt-bound graphs that cover the frozen evidence policy."""

    def __init__(
        self,
        *,
        proposal_port: ProblemGraphStructuredProposalPort,
        artifacts: PlanningArtifactPort,
    ) -> None:
        self._proposal_port = proposal_port
        self._artifacts = artifacts

    async def _propose(
        self,
        *,
        requirement: RequirementVersionV3,
        catalog: CompetitiveTextCatalog,
    ) -> ProblemGraphProposalV3:
        if requirement.payload.planning_blocked:
            raise ProblemGraphPlanningError("requirement_clarification_required")
        proposal = await self._proposal_port.propose(requirement=requirement, catalog=catalog)
        if proposal.receipt.run_id != requirement.run_id:
            raise ProblemGraphPlanningError("problem_graph_receipt_run_mismatch")
        expected_context_hash = problem_graph_context_manifest_hash(requirement, catalog)
        if proposal.receipt.context_manifest_hash != expected_context_hash:
            raise ProblemGraphPlanningError("problem_graph_receipt_context_mismatch")
        if proposal.graph.requirement_version_id != requirement.id:
            raise ProblemGraphPlanningError("problem_graph_requirement_mismatch")
        try:
            validate_competitive_problem_graph(proposal.graph, requirement.payload, catalog)
        except ValueError as exc:
            raise ProblemGraphPlanningError(str(exc)) from exc
        return proposal

    async def plan(
        self,
        *,
        requirement: RequirementVersionV3,
        catalog: CompetitiveTextCatalog,
    ) -> ProblemGraphV1:
        proposal = await self._propose(requirement=requirement, catalog=catalog)
        return proposal.graph

    async def plan_and_seal(
        self,
        *,
        requirement: RequirementVersionV3,
        catalog: CompetitiveTextCatalog,
    ) -> ProblemGraphPlanningResultV3:
        proposal = await self._propose(requirement=requirement, catalog=catalog)
        artifact = self._artifacts.seal_problem_graph(
            run_id=requirement.run_id,
            graph=proposal.graph,
        )
        return ProblemGraphPlanningResultV3(
            graph=proposal.graph,
            artifact=artifact,
            receipt=proposal.receipt,
        )


class DeterministicProblemGraphProposalFake:
    """Deterministic graph proposal fake used by unit tests instead of an LLM."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def propose(
        self,
        *,
        requirement: RequirementVersionV3,
        catalog: CompetitiveTextCatalog,
    ) -> ProblemGraphProposalV3:
        self.calls.append((requirement.id, catalog.catalog_id))
        policy = competitive_text_evidence_requirements(catalog)
        context_hash = problem_graph_context_manifest_hash(requirement, catalog)
        seed = canonical_json_v3_sha256(
            {
                "requirement": requirement.content_hash,
                "catalog": catalog.catalog_hash,
                "call_index": len(self.calls) - 1,
            }
        )
        receipt_id = f"receipt_graph_{seed[:24]}"
        trace_id = f"trace_graph_{seed[24:48]}"
        prompt_hash = canonical_json_v3_sha256(
            {"stage": "problem_graph", "schema": "problem-graph-v1"}
        )
        graph = ProblemGraphV1(
            schema_version="problem-graph-v1",
            requirement_version_id=requirement.id,
            questions=tuple(
                ProblemQuestionV1(
                    id=f"question_{index}",
                    statement=f"What evidence satisfies: {criterion.statement}",
                    rationale="Provide traceable coverage for the Requirement success criterion.",
                    priority="required",
                    success_criterion_ids=(criterion.id,),
                    evidence_requirements=policy,
                    acceptance_criteria=(
                        "Every material factual statement is supported by public-source evidence.",
                    ),
                    depends_on=(),
                )
                for index, criterion in enumerate(requirement.payload.success_criteria, start=1)
            ),
            provenance=ProblemGraphProvenanceV1(
                model_call_receipt_id=receipt_id,
                model_name="deterministic-problem-graph-fake",
                model_version="1",
                prompt_hash=prompt_hash,
                trace_id=trace_id,
                context_manifest_hash=context_hash,
            ),
        )
        receipt = PlanningModelCallReceiptV3(
            id=receipt_id,
            run_id=requirement.run_id,
            stage="problem_graph",
            model_name=graph.provenance.model_name,
            model_version=graph.provenance.model_version,
            prompt_hash=prompt_hash,
            trace_id=trace_id,
            context_manifest_hash=context_hash,
            output_hash=canonical_json_v3_sha256(graph),
        )
        return ProblemGraphProposalV3(graph=graph, receipt=receipt)
