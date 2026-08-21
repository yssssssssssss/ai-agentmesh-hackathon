from __future__ import annotations

from typing import Protocol

from agentmesh.research_orchestration.v3.common import (
    EvidenceManifestArtifactRefV3,
    Identifier,
    NonBlankString,
    StrictFrozenModel,
)
from agentmesh.research_orchestration.v3.deliverable import (
    CapabilityProvenanceV3,
    CompetitiveAnalysisTextPayloadV1,
    FindingGraphV3,
    ResearchDeliverableCoverageV3,
    ResearchDeliverableV3,
    RecommendationV3,
)
from agentmesh.research_orchestration.v3.evidence import (
    EvidenceManifestV3,
    VerifiedArtifactContentV3,
)
from agentmesh.research_orchestration.v3.evidence_materializer import read_verified_actor_artifacts
from agentmesh.research_orchestration.v3.execution_plan import ExecutionPlanVersionV3
from agentmesh.research_orchestration.v3.ports import (
    ActorExecutionResultV3,
    ArtifactReadPort,
    validate_delivery_inputs,
)
from agentmesh.research_orchestration.v3.requirement import RequirementVersionV3


class CompetitiveDeliverableDraftV3(StrictFrozenModel):
    """The synthesis-owned fields accepted at the deterministic Deliverable boundary."""

    method_summary: NonBlankString
    finding_graph: FindingGraphV3
    payload: CompetitiveAnalysisTextPayloadV1
    recommendations: tuple[RecommendationV3, ...]
    coverage: ResearchDeliverableCoverageV3
    risks_and_open_issues: tuple[NonBlankString, ...]


class CompetitiveTextSynthesisPort(Protocol):
    async def synthesize(
        self,
        *,
        requirement: RequirementVersionV3,
        plan: ExecutionPlanVersionV3,
        actor_results: tuple[ActorExecutionResultV3, ...],
        actor_artifacts: tuple[VerifiedArtifactContentV3, ...],
        evidence_manifest: EvidenceManifestV3,
    ) -> CompetitiveDeliverableDraftV3: ...


class DeliverableValidationError(ValueError):
    pass


class CompetitiveTextDeliverableService:
    """Create the Competitive Text Deliverable around an injected synthesis seam."""

    def __init__(
        self,
        synthesis: CompetitiveTextSynthesisPort,
        *,
        artifacts: ArtifactReadPort,
    ) -> None:
        self._synthesis = synthesis
        self._artifacts = artifacts

    async def create_deliverable(
        self,
        *,
        requirement: RequirementVersionV3,
        plan: ExecutionPlanVersionV3,
        attempt_id: Identifier,
        actor_results: tuple[ActorExecutionResultV3, ...],
        evidence_manifest: EvidenceManifestV3,
        evidence_manifest_artifact: EvidenceManifestArtifactRefV3,
    ) -> ResearchDeliverableV3:
        validate_delivery_inputs(
            requirement=requirement,
            plan=plan,
            attempt_id=attempt_id,
            actor_results=actor_results,
            evidence_manifest=evidence_manifest,
            evidence_manifest_artifact=evidence_manifest_artifact,
        )
        self._validate_evidence_policy(plan, evidence_manifest)
        actor_artifacts = read_verified_actor_artifacts(self._artifacts, actor_results)
        draft = await self._synthesis.synthesize(
            requirement=requirement,
            plan=plan,
            actor_results=actor_results,
            actor_artifacts=actor_artifacts,
            evidence_manifest=evidence_manifest,
        )
        self._validate_draft(
            requirement=requirement,
            plan=plan,
            evidence_manifest=evidence_manifest,
            draft=draft,
        )
        provenance = tuple(
            CapabilityProvenanceV3(
                actor_type=result.actor_type,
                actor_id=result.actor_id,
                result_artifact=result.result_artifact,
            )
            for result in sorted(actor_results, key=lambda item: item.step_number)
        )
        return ResearchDeliverableV3(
            schema_version="research-deliverable-v3",
            run_id=requirement.run_id,
            requirement_version_id=requirement.id,
            plan_version_id=plan.id,
            attempt_id=attempt_id,
            deliverable_type="competitive_analysis_report",
            payload_schema_version="competitive-analysis-text-v1",
            evidence_manifest_artifact=evidence_manifest_artifact,
            method_summary=draft.method_summary,
            finding_graph=draft.finding_graph,
            payload=draft.payload,
            recommendations=draft.recommendations,
            coverage=draft.coverage,
            risks_and_open_issues=draft.risks_and_open_issues,
            capability_provenance=provenance,
        )

    @staticmethod
    def _validate_evidence_policy(
        plan: ExecutionPlanVersionV3,
        evidence_manifest: EvidenceManifestV3,
    ) -> None:
        classes = tuple(item.evidence_class for item in evidence_manifest.evidence)
        for requirement in plan.payload.evidence_requirements:
            matching = sum(
                evidence_class in requirement.accepted_classes for evidence_class in classes
            )
            if requirement.required and matching < requirement.minimum_count:
                raise DeliverableValidationError(
                    f"Evidence Manifest does not satisfy required policy {requirement.id}"
                )

    @staticmethod
    def _validate_draft(
        *,
        requirement: RequirementVersionV3,
        plan: ExecutionPlanVersionV3,
        evidence_manifest: EvidenceManifestV3,
        draft: CompetitiveDeliverableDraftV3,
    ) -> None:
        known_evidence = {item.id for item in evidence_manifest.evidence}
        referenced_evidence = _deliverable_evidence_ids(draft)
        if not referenced_evidence.issubset(known_evidence):
            raise DeliverableValidationError("Deliverable references Evidence outside its Manifest")

        planned_questions = {
            question_id for step in plan.payload.steps for question_id in step.question_ids
        }
        covered_questions = {item.question_id for item in draft.coverage.question_coverage}
        if covered_questions != planned_questions:
            raise DeliverableValidationError(
                "Deliverable question coverage must exactly match selected Plan questions"
            )
        required_criteria = {item.id for item in requirement.payload.success_criteria}
        covered_criteria = {
            item.success_criterion_id for item in draft.coverage.success_criterion_coverage
        }
        if covered_criteria != required_criteria:
            raise DeliverableValidationError(
                "Deliverable success coverage must exactly match Requirement criteria"
            )

        undisclosed = [
            gap
            for gap in plan.payload.capability_gaps
            if not any(
                gap.capability_id in issue or gap.code in issue
                for issue in draft.risks_and_open_issues
            )
        ]
        if undisclosed:
            raise DeliverableValidationError("Deliverable must disclose every planned capability gap")
        if any(gap.required for gap in plan.payload.capability_gaps):
            raise DeliverableValidationError("a Plan with a required capability gap cannot be delivered")


def _deliverable_evidence_ids(draft: CompetitiveDeliverableDraftV3) -> set[str]:
    identifiers: set[str] = set()
    for finding in draft.finding_graph.findings:
        if finding.kind == "fact":
            identifiers.update(finding.evidence_ids)
    for sample in draft.payload.competitor_samples:
        identifiers.update(sample.evidence_ids)
    for row in draft.payload.dimension_matrix:
        for value in row.values:
            identifiers.update(value.evidence_ids)
    for difference in draft.payload.differences:
        identifiers.update(difference.evidence_ids)
    return identifiers
